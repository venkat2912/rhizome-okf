"""SWE-rebench file- and function-level localisation benchmark for Rhizome v0.3 (PLAN.md, Phase 1).

  * tasks    bench/splits/swe-rebench-v0.3.json (bench/rebench_select.py): a dev split for choosing settings
             and a SEALED test split that is run once, in Phase 6 (needs --unseal)
  * gold     files: non-test .py files in the patch, all present at base_commit; functions: the functions and
             methods whose lines the patch changes (bench/funcs.py)
  * cands    non-test .py files of the snapshot (Rhizome's ``test`` tag)
  * query    the full problem statement, unmodified, identical for every method
  * methods  file-bm25 (Okapi BM25 over whole files), rhizome-search (v0.2 BM25F, ``Bundle.search`` with the
             repository), function-bm25 (BM25 over function chunks; a file's score is its best chunk)
  * scores   file Acc@k and Recall@k (k = 1, 5, 10), MRR, all-gold-in-top-10 on multi-file tasks, function
             Recall@k (k = 5, 10, 20), seconds per query; LLM tokens are 0 for every method

Usage:
  python bench/run_rebench.py --split dev --limit 10 --out bench/runs/rebench-dev-smoke
  python bench/run_rebench.py --split dev --out bench/runs/rebench-dev
  python bench/run_rebench.py --split dev --out bench/runs/rebench-dev --report-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import funcs  # noqa: E402
import rebench_select as sel  # noqa: E402
import run_swebench as rs  # noqa: E402
from rhizome.parse_python import iter_python_files  # noqa: E402
from rhizome.retrieve import Bundle, RetrievalConfig, tokens  # noqa: E402

SPLITS = sel.OUT
FILE_METHODS = ["file-bm25", "rhizome-search", "function-bm25"]
KS = (1, 5, 10)
FKS = (5, 10, 20)
TOP_SAVED = 100
BOOT, SEED = 10_000, 0
PROTOCOL_VERSION = 1


def bm25_generic(query_tokens, docs: dict[str, Counter]) -> list[str]:
    """Okapi BM25 (k1 = 1.2, b = 0.75) over arbitrary documents; ties keep insertion order."""
    ids = list(docs)
    n = len(ids)
    dl = {d: sum(docs[d].values()) for d in ids}
    avgdl = (sum(dl.values()) / n) if n else 1.0
    df = Counter()
    for d in ids:
        df.update(docs[d].keys())
    scores = {}
    for d in ids:
        tf, s = docs[d], 0.0
        for t in query_tokens:
            f = tf.get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (rs.BM25_K1 + 1) / (f + rs.BM25_K1 * (1 - rs.BM25_B + rs.BM25_B * dl[d] / (avgdl or 1.0)))
        scores[d] = s
    order = {d: i for i, d in enumerate(ids)}
    return sorted(ids, key=lambda d: (-scores[d], order[d]))


def file_metrics(ranking, gold):
    pos = {p: i + 1 for i, p in enumerate(ranking)}
    ranks = sorted(pos[g] for g in gold if g in pos)
    m = {f"acc@{k}": int(len(ranks) == len(gold) and ranks[-1] <= k) for k in KS}
    m.update({f"recall@{k}": sum(1 for r in ranks if r <= k) / len(gold) for k in KS})
    m["mrr"] = 1.0 / ranks[0] if ranks else 0.0
    return m


def run_task(task: dict, statement: str, tmp_root: str | None) -> dict:
    rec = {"instance_id": task["instance_id"], "repo": task["repo"], "base_commit": task["base_commit"],
           "gold": task["gold"], "n_gold": len(task["gold"])}
    timings: dict = {}
    t0 = time.perf_counter()
    repo_dir = rs.ensure_repo(task["repo"])
    rs.ensure_commit(repo_dir, task["base_commit"])
    tmp = tempfile.mkdtemp(prefix="rzr_", dir=tmp_root)
    try:
        snap = os.path.join(tmp, "s")
        os.makedirs(snap)
        t = time.perf_counter()
        mat = rs.materialise(repo_dir, task["base_commit"], snap)
        timings["materialise_s"] = round(time.perf_counter() - t, 3)
        rec["extract_errors_py"] = [n for n, _ in mat["errors"] if n.endswith(".py")]
        missing = [g for g in task["gold"] if g not in mat["names"]]
        if missing:
            rec.update(status="excluded", exclude_reason=f"gold file not in snapshot: {missing}")
            return rec

        bdir, binfo = rs.bundle_for(task["repo"], task["base_commit"], snap, tmp)
        timings["scan_s" if not binfo["cache_hit"] else "bundle_cache_load_s"] = binfo["seconds"]
        rec["scan_stats"] = binfo["stats"]
        t = time.perf_counter()
        bundle = Bundle(bdir, repo=snap)
        timings["bundle_load_s"] = round(time.perf_counter() - t, 3)
        path_of = {r: str(c.fm.get("title")) for r, c in bundle.files.items()}
        is_test = {path_of[r]: "test" in (c.fm.get("tags") or []) for r, c in bundle.files.items()}
        cands = [p for p in iter_python_files(snap) if not is_test.get(p, False)]
        cset = set(cands)
        rec["n_candidates"] = len(cands)
        rec["gold_not_in_candidates"] = [g for g in task["gold"] if g not in cset]
        rec["parse_errors"] = [{"path": path_of[r], "parser": c.fm.get("parser"), "error": c.fm.get("parse_error")}
                               for r, c in bundle.files.items() if c.fm.get("parse_error")]

        t = time.perf_counter()
        texts, toks = {}, {}
        for p in cands:
            with open(os.path.join(snap, *p.split("/")), encoding="utf-8", errors="replace") as fh:
                texts[p] = fh.read()
            toks[p] = Counter(tokens(texts[p]))
        timings["file_tokenise_s"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        chunk_tf, chunk_file = {}, {}
        for p in cands:
            for cid, src in funcs.chunks(p, texts[p]):
                chunk_tf[cid] = Counter(tokens(src))
                chunk_file[cid] = p
        timings["function_index_s"] = round(time.perf_counter() - t, 3)
        rec["n_chunks"] = len(chunk_tf)

        gold_fn, module_only = funcs.gold_functions(
            task_patch(task), lambda p: texts.get(p))
        gold_fn = [g for g in gold_fn if g.split("::")[0] in task["gold"]]
        rec["gold_functions"] = gold_fn
        rec["gold_module_only_files"] = [p for p in module_only if p in task["gold"]]

        q = tokens(statement)
        rk, qs = {}, {}
        t = time.perf_counter()
        bm = rs.bm25_rank(statement, cands, toks)
        qs["file-bm25"] = round(time.perf_counter() - t, 4)
        rk["file-bm25"] = bm
        t = time.perf_counter()
        hits = bundle.search(statement, k=len(bundle.files), types=("Source File",), config=RetrievalConfig())
        rk["rhizome-search"], _ = rs.complete([path_of[h] for h, _ in hits], cset, bm)
        qs["rhizome-search"] = round(time.perf_counter() - t, 4)
        t = time.perf_counter()
        fn_rank = bm25_generic(q, chunk_tf)
        seen, best = set(), []
        for cid in fn_rank:
            f = chunk_file[cid]
            if f not in seen:
                seen.add(f)
                best.append(f)
        rk["function-bm25"] = best
        qs["function-bm25"] = round(time.perf_counter() - t, 4)

        rec["methods"] = {m: {"top": rk[m][:TOP_SAVED], **file_metrics(rk[m], task["gold"])} for m in FILE_METHODS}
        fn_only = [c for c in fn_rank if not c.endswith("::" + funcs.MODULE)]
        fpos = {c: i + 1 for i, c in enumerate(fn_only)}
        rec["function"] = {"function-bm25": {
            "top": fn_only[:TOP_SAVED],
            **({f"recall@{k}": sum(1 for g in gold_fn if fpos.get(g, 10 ** 9) <= k) / len(gold_fn) for k in FKS}
               if gold_fn else {})}}
        rec["query_s"] = qs
        rec["status"] = "ok"
        return rec
    finally:
        timings["total_s"] = round(time.perf_counter() - t0, 3)
        rec["timings"] = timings
        shutil.rmtree(tmp, ignore_errors=True)


_PATCHES: dict = {}


def task_patch(task):
    return _PATCHES[task["instance_id"]]


# ------------------------------------------------------------------ summary and report

def boot_mean(x):
    x = np.asarray(x, float)
    if len(x) == 0:
        return [float("nan")] * 3
    idx = np.random.default_rng(SEED).integers(0, len(x), size=(BOOT, len(x)))
    m = x[idx].mean(1)
    return [float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summarise(out_dir, n_tasks):
    recs = rs.load_records(os.path.join(out_dir, "per_instance.jsonl"))
    ok = [r for r in recs.values() if r.get("status") == "ok"]
    multi = [r for r in ok if r["n_gold"] >= 2]
    s = {"tasks_in_split": n_tasks, "attempted": len(recs), "evaluated": len(ok), "repos": len({r["repo"] for r in ok}),
         "excluded": [{"instance_id": r["instance_id"], "reason": r.get("exclude_reason")} for r in recs.values()
                      if r.get("status") == "excluded"],
         "errors": [{"instance_id": r["instance_id"], "error": r.get("error", "")[:300]} for r in recs.values()
                    if r.get("status") == "error"],
         "gold_files": dict(sorted(Counter(min(r["n_gold"], 3) for r in ok).items())),
         "methods": {}, "multi_file": {"n": len(multi)}, "paired": {}, "function": {}}
    for m in FILE_METHODS:
        d = {}
        for k in KS:
            d[f"acc@{k}"] = boot_mean([r["methods"][m][f"acc@{k}"] for r in ok])
            d[f"recall@{k}"] = boot_mean([r["methods"][m][f"recall@{k}"] for r in ok])
        d["mrr"] = boot_mean([r["methods"][m]["mrr"] for r in ok])
        s["methods"][m] = d
        s["multi_file"][m] = {"all_gold_top10": boot_mean([r["methods"][m]["acc@10"] for r in multi]),
                              "all_gold_top5": boot_mean([r["methods"][m]["acc@5"] for r in multi]),
                              "recall@10": boot_mean([r["methods"][m]["recall@10"] for r in multi])}
    for a, b in (("rhizome-search", "file-bm25"), ("function-bm25", "file-bm25"), ("function-bm25", "rhizome-search")):
        s["paired"][f"{a} vs {b}"] = {}
        for k in KS:
            x = sum(1 for r in ok if r["methods"][a][f"acc@{k}"] and not r["methods"][b][f"acc@{k}"])
            y = sum(1 for r in ok if r["methods"][b][f"acc@{k}"] and not r["methods"][a][f"acc@{k}"])
            s["paired"][f"{a} vs {b}"][f"acc@{k}"] = {"a_only": x, "b_only": y, "p": rs.binom_two_sided(x, y)}
    fn = [r for r in ok if r.get("gold_functions")]
    s["function"] = {"n_with_function_gold": len(fn),
                     "n_module_level_only": sum(1 for r in ok if not r.get("gold_functions")),
                     "gold_functions_per_task": dict(sorted(Counter(min(len(r["gold_functions"]), 6) for r in fn).items())),
                     "function-bm25": {f"recall@{k}": boot_mean([r["function"]["function-bm25"][f"recall@{k}"] for r in fn])
                                       for k in FKS}}
    first = [r["timings"]["scan_s"] for r in ok if "scan_s" in r.get("timings", {})]
    s["cost"] = {"scan_median_s": rs.median(first), "scan_mean_s": rs.mean(first),
                 "scan_max_s": max(first) if first else None, "first_scans": len(first),
                 "materialise_mean_s": rs.mean(r["timings"].get("materialise_s", 0) for r in ok),
                 "task_mean_s": rs.mean(r["timings"].get("total_s", 0) for r in ok),
                 "query_s": {m: rs.mean(r["query_s"][m] for r in ok) for m in FILE_METHODS},
                 "mean_candidates": rs.mean(r["n_candidates"] for r in ok),
                 "mean_function_chunks": rs.mean(r["n_chunks"] for r in ok), "llm_tokens": 0}
    s["gold_outside_candidates"] = sum(1 for r in ok if r["gold_not_in_candidates"])
    s["parse_errors"] = dict(Counter(e["parser"] for r in ok for e in r.get("parse_errors", [])))
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)
    return s


def ci(t, pct=True, d=1):
    k = 100 if pct else 1
    return "–" if any(isinstance(v, float) and math.isnan(v) for v in t) else \
        f"{t[0] * k:.{d}f} [{t[1] * k:.{d}f}, {t[2] * k:.{d}f}]"


def results_table(s):
    L = ["| Method | Acc@1 | Acc@5 | Acc@10 | Recall@5 | Recall@10 | MRR |", "|---|---|---|---|---|---|---|"]
    for m in FILE_METHODS:
        d = s["methods"][m]
        L.append(f"| {m} | {ci(d['acc@1'])} | {ci(d['acc@5'])} | {ci(d['acc@10'])} | {ci(d['recall@5'])} | "
                 f"{ci(d['recall@10'])} | {ci(d['mrr'], False, 3)} |")
    return L


def write_report(out_dir, s, proto):
    L = [f"# Rhizome on SWE-rebench ({proto['split']} split): baselines for v0.3", "", "## 1. Protocol", "",
         f"- **Dataset**: `{sel.DATASET}`; tasks from `bench/splits/swe-rebench-v0.3.json` "
         f"(seed {sel.SEED}; repos not in SWE-bench Lite or Loc-Bench; 1-{sel.MAX_GOLD} non-test gold `.py` files, all "
         f"present at `base_commit`; at most {sel.MAX_TASKS} tasks per repo). Split by repository; the test split "
         "is sealed until Phase 6.",
         f"- **This run**: split `{proto['split']}`, {s['tasks_in_split']} tasks; {s['attempted']} attempted, "
         f"{s['evaluated']} evaluated in {s['repos']} repos, {len(s['excluded'])} excluded, {len(s['errors'])} crashed.",
         "- **Candidates**: non-test `.py` files of the snapshot. **Query**: the full problem statement.",
         "- **Methods**: `file-bm25` (Okapi BM25, whole files); `rhizome-search` (v0.2 BM25F with file bodies, "
         "`RetrievalConfig()` defaults); `function-bm25` (BM25 over function and method chunks plus each file's "
         "module-level remainder; a file ranks by its best chunk). All use Rhizome's tokeniser.",
         "- **Gold functions**: functions and methods whose lines the patch changes (an inserted line counts when "
         "both its neighbours are inside the same function).",
         "- **Scores**: Acc@k = all gold files in the top k; Recall@k = fraction of gold files in the top k; 95% "
         f"intervals from {BOOT:,} bootstrap resamples over tasks (seed {SEED}); exact McNemar tests on Acc@k.",
         f"- **Rhizome code**: `{proto['rhizome_commit']}` (code hash `{proto['code_tag']}`). **Machine**: "
         f"{proto['machine']}; Python {proto['python']}; started {proto['started']}.", "",
         "## 2. File-level results", ""] + results_table(s) + ["",
         "Paired comparisons (tasks solved by only the first / only the second method, exact McNemar p):", "",
         "| Comparison | Acc@1 | Acc@5 | Acc@10 |", "|---|---|---|---|"]
    for name, d in s["paired"].items():
        L.append(f"| {name} | " + " | ".join(f"{d[f'acc@{k}']['a_only']} / {d[f'acc@{k}']['b_only']} / "
                                             f"{d[f'acc@{k}']['p']:.3g}" for k in KS) + " |")
    L += ["", f"### Multi-file tasks (2+ gold files, n = {s['multi_file']['n']})", "",
          "| Method | All gold in top 5 | All gold in top 10 | Recall@10 |", "|---|---|---|---|"]
    for m in FILE_METHODS:
        d = s["multi_file"][m]
        L.append(f"| {m} | {ci(d['all_gold_top5'])} | {ci(d['all_gold_top10'])} | {ci(d['recall@10'])} |")
    f = s["function"]
    L += ["", "## 3. Function-level results", "",
          f"{f['n_with_function_gold']} tasks have at least one gold function; {f['n_module_level_only']} change only "
          f"module-level code and are left out. Gold functions per task (6 = 6 or more): {f['gold_functions_per_task']}.",
          "", "| Method | Function Recall@5 | Recall@10 | Recall@20 |", "|---|---|---|---|",
          f"| function-bm25 | {ci(f['function-bm25']['recall@5'])} | {ci(f['function-bm25']['recall@10'])} | "
          f"{ci(f['function-bm25']['recall@20'])} |"]
    c = s["cost"]
    L += ["", "## 4. Cost", "", "LLM calls and tokens: 0.", "", "| Step | Seconds |", "|---|---:|",
          f"| Rhizome scan, median / mean / max ({c['first_scans']} scans) | {c['scan_median_s']:.1f} / "
          f"{c['scan_mean_s']:.1f} / {c['scan_max_s']:.1f} |" if c["first_scans"] else "| Rhizome scan | (cached) |",
          f"| Snapshot, mean | {c['materialise_mean_s']:.1f} |", f"| Whole task, mean | {c['task_mean_s']:.1f} |"]
    L += [f"| Query `{m}`, mean | {v:.3f} |" for m, v in c["query_s"].items()]
    L += ["", f"Mean candidates per task: {c['mean_candidates']:.0f} files, {c['mean_function_chunks']:.0f} function "
          "chunks.", "", "## 5. Counts", "",
          f"- Gold files per task (3 = 3-5): {s['gold_files']}; tasks with a gold file outside the candidates: "
          f"{s['gold_outside_candidates']}.",
          f"- Files `ast` could not parse, by parser used: {s['parse_errors']}.",
          f"- Excluded: {len(s['excluded'])}" + "".join(f"; `{e['instance_id']}` ({e['reason']})" for e in s["excluded"][:10]) + ".",
          f"- Crashed: {len(s['errors'])}" + "".join(f"; `{e['instance_id']}`: {e['error'][:120]}" for e in s["errors"][:10]) + ".",
          ""]
    with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--unseal", action="store_true", help="required to run the sealed test split (Phase 6 only)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sample", type=int, help="smoke test: a seeded random sample of N tasks across the split")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmp-root", help="short directory for snapshots (Windows 260-character path limit)")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)
    spec = json.load(open(SPLITS, encoding="utf-8"))
    if args.split in spec.get("sealed", []) and not args.unseal:
        sys.exit(f"the {args.split} split is sealed until Phase 6; pass --unseal only for the final run")
    tasks = spec["splits"][args.split]["tasks"]
    todo = tasks[: args.limit] if args.limit else tasks
    if args.sample:
        import random
        todo = sorted(random.Random(SEED).sample(tasks, min(args.sample, len(tasks))), key=lambda t: t["instance_id"])
    os.makedirs(args.out, exist_ok=True)
    ppath = os.path.join(args.out, "protocol.json")
    proto = {"version": PROTOCOL_VERSION, "split": args.split, "methods": FILE_METHODS,
             "rhizome_commit": rs.git_info(), "code_tag": rs.CODE_TAG,
             "machine": f"{platform.platform()}, {platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs",
             "python": platform.python_version(), "started": dt.datetime.now().isoformat(timespec="seconds"),
             "args": " ".join(sys.argv[1:])}
    if os.path.exists(ppath):
        old = json.load(open(ppath, encoding="utf-8"))
        for key in ("version", "split", "methods", "code_tag"):
            if old.get(key) != proto[key]:
                sys.exit(f"protocol mismatch on resume ({key}: {old.get(key)} != {proto[key]}); use a new --out")
        proto = old
    else:
        json.dump(proto, open(ppath, "w", encoding="utf-8"), indent=1)
    jpath = os.path.join(args.out, "per_instance.jsonl")
    if not args.report_only:
        want = {t["instance_id"] for t in todo}
        for r in sel.load_rows(["instance_id", "problem_statement", "patch"]):
            if r["instance_id"] in want:
                _PATCHES[r["instance_id"]] = r["patch"]
                _PATCHES[("stmt", r["instance_id"])] = r["problem_statement"]
        done = {k for k, r in rs.load_records(jpath).items() if r.get("status") in ("ok", "excluded")}
        pending = [t for t in todo if t["instance_id"] not in done]
        print(f"{len(todo)} selected, {len(todo) - len(pending)} done, {len(pending)} to run", flush=True)
        for i, task in enumerate(pending, 1):
            t = time.perf_counter()
            try:
                rec = run_task(task, _PATCHES[("stmt", task["instance_id"])], args.tmp_root)
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                rec = {"instance_id": task["instance_id"], "repo": task["repo"], "status": "error",
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            with open(jpath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            extra = ""
            if rec["status"] == "ok":
                extra = (f"gold={rec['n_gold']} fn={len(rec['gold_functions'])} " +
                         " ".join(f"{m.split('-')[0]}@10={rec['methods'][m]['acc@10']}" for m in FILE_METHODS))
            print(f"[{i}/{len(pending)}] {task['instance_id']} {rec['status']} {time.perf_counter() - t:.1f}s {extra}"
                  + (f" {rec.get('error', '')[:200]}" if rec["status"] == "error" else ""), flush=True)
    s = summarise(args.out, len(tasks))
    write_report(args.out, s, proto)
    print("\n" + "\n".join(results_table(s)))
    print(f"\nevaluated {s['evaluated']}, excluded {len(s['excluded'])}, errors {len(s['errors'])}; report: "
          f"{os.path.join(args.out, 'REPORT.md')}")


if __name__ == "__main__":
    main()
