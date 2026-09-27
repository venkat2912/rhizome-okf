"""Loc-Bench V1 file-level localisation benchmark for Rhizome (multi-file baseline).

Frozen protocol, fixed before any Loc-Bench result was seen:
  * dataset  czlll/Loc-Bench_V1, split test (560 instances), the release named in the LocAgent README
  * gold     .py files touched by the gold ``patch`` that exist at ``base_commit``
  * cands    .py files from ``rhizome.parse_python.iter_python_files``; variant B = non-test files (Rhizome's
             ``test`` tag), variant A = all files (optional)
  * query    the full ``problem_statement``, unmodified, identical for every method
  * code     Rhizome at tag v0.2.0-rc1 (branch feat/v0.2-retrieval). Each snapshot is scanned once with that
             code; every Rhizome method is ranked twice on the same bundle: with RetrievalConfig.v01() ("v0.1",
             i.e. v0.1 retrieval on a v0.2 bundle) and with the v0.2 defaults ("v0.2")
  * methods  random; file-bm25; bm25-graph; and, per config, rhizome-search, rhizome-ctx-cat, rhizome-ctx-bug,
             fusion-rrf (file-bm25 + rhizome-ctx-cat), fusion-rrf-search (file-bm25 + rhizome-search)
  * metrics  Acc@{5,10} (all gold files in the top k), Recall@{5,10}, MRR of the first gold file

Usage:
  python bench/run_locbench.py --limit 20 --variants B --out bench/runs/locbench-v01-smoke
  python bench/run_locbench.py --out bench/runs/locbench-v01 --report-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import platform
import random
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import run_swebench as rs  # noqa: E402  (snapshots, bundle cache, BM25, RRF, McNemar)
from rhizome.parse_python import iter_python_files  # noqa: E402
from rhizome.retrieve import Bundle, RetrievalConfig, gather, tokens  # noqa: E402

DATA = os.path.join(rs.CACHE, "loc_bench_v1.jsonl")
DATASET = "czlll/Loc-Bench_V1"
CATEGORY = {"Bug Report": "bug", "Feature Request": "feature", "Security Vulnerability": "security",
            "Performance Issue": "bug"}
CONFIGS = {"v0.1": RetrievalConfig.v01(), "v0.2": RetrievalConfig()}
RHIZOME = ["rhizome-search", "rhizome-ctx-cat", "rhizome-ctx-bug", "fusion-rrf", "fusion-rrf-search"]
METHODS = ["random", "file-bm25", "bm25-graph"] + [f"{m} [{c}]" for c in CONFIGS for m in RHIZOME]
KS = (5, 10)
TOP_SAVED = 100
BM25_GRAPH_ENTRIES = 4          # the top 4 file-bm25 files, as fixed in the protocol
PROTOCOL_VERSION = 1

PUBLISHED = [  # LocAgent (Chen et al., ACL 2025, arXiv:2503.09089), Loc-Bench, file level, Acc@5
    ("BM25", 70.72), ("CodeRankEmbed", 77.81), ("LocAgent (Qwen2.5-7B)", 79.20), ("LocAgent (Claude-3.5)", 84.59)]


def comparisons() -> list[tuple[str, str]]:
    out = []
    for c in CONFIGS:
        for m in RHIZOME:
            out.append((f"{m} [{c}]", "file-bm25"))
    out.append(("bm25-graph", "file-bm25"))
    for c in CONFIGS:
        out.append((f"fusion-rrf [{c}]", f"fusion-rrf-search [{c}]"))
        out.append((f"rhizome-ctx-cat [{c}]", f"rhizome-ctx-bug [{c}]"))
    for m in RHIZOME:
        out.append((f"{m} [v0.2]", f"{m} [v0.1]"))
    return out


# ------------------------------------------------------------------ data

def load_dataset() -> list[dict]:
    if not os.path.exists(DATA):
        from huggingface_hub import hf_hub_download
        import pyarrow.parquet as pq
        rows = pq.read_table(hf_hub_download(DATASET, "data/test-00000-of-00001.parquet",
                                             repo_type="dataset")).to_pylist()
        with open(DATA, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, default=str) + "\n")
    with open(DATA, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def metrics(ranking: list[str], gold: list[str]) -> dict:
    pos = {p: i + 1 for i, p in enumerate(ranking)}
    ranks = sorted(pos[g] for g in gold if g in pos)
    m = {f"acc@{k}": int(len(ranks) == len(gold) and bool(gold) and ranks[-1] <= k) for k in KS}
    m.update({f"recall@{k}": sum(1 for r in ranks if r <= k) / len(gold) for k in KS})
    m["mrr"] = 1.0 / ranks[0] if ranks else 0.0
    return m


# ------------------------------------------------------------------ one instance

def run_instance(inst: dict, variants: list[str]) -> dict:
    rec = {"instance_id": inst["instance_id"], "repo": inst["repo"], "base_commit": inst["base_commit"],
           "category": inst["category"], "rhizome_category": CATEGORY[inst["category"]]}
    timings: dict = {}
    t0 = time.perf_counter()
    repo_dir = rs.ensure_repo(inst["repo"])
    rs.ensure_commit(repo_dir, inst["base_commit"])
    tmp = tempfile.mkdtemp(prefix="rzl_")
    try:
        snap = os.path.join(tmp, "s")
        os.makedirs(snap)
        t = time.perf_counter()
        mat = rs.materialise(repo_dir, inst["base_commit"], snap)
        timings["materialise_s"] = round(time.perf_counter() - t, 3)
        rec["extract_errors_py"] = [n for n, _ in mat["errors"] if n.endswith(".py")]
        gold_all = rs.gold_files(inst["patch"])
        gold = [g for g in gold_all if g in mat["names"]]
        rec.update(gold=gold, gold_added=[g for g in gold_all if g not in mat["names"]], n_gold=len(gold))
        if not gold:
            rec.update(status="excluded", exclude_reason="no gold .py file present at base_commit")
            return rec

        all_cands = list(iter_python_files(snap))
        bdir, binfo = rs.bundle_for(inst["repo"], inst["base_commit"], snap, tmp)
        timings["scan_s" if not binfo["cache_hit"] else "bundle_cache_load_s"] = binfo["seconds"]
        rec["scan_stats"] = binfo["stats"]
        t = time.perf_counter()
        bundle = Bundle(bdir, repo=snap)
        timings["bundle_load_s"] = round(time.perf_counter() - t, 3)
        path_of = {r: str(c.fm.get("title")) for r, c in bundle.files.items()}
        rel_of = {p: r for r, p in path_of.items()}
        is_test = {path_of[r]: "test" in (c.fm.get("tags") or []) for r, c in bundle.files.items()}
        rec["candidates_without_concept"] = sum(1 for p in all_cands if p not in is_test)
        rec["parse_errors"] = [{"path": path_of[r], "parser": c.fm.get("parser"), "error": c.fm.get("parse_error")}
                               for r, c in bundle.files.items() if c.fm.get("parse_error")]

        t = time.perf_counter()
        toks = {}
        for p in all_cands:
            with open(os.path.join(snap, *p.split("/")), encoding="utf-8", errors="replace") as fh:
                toks[p] = Counter(tokens(fh.read()))
        timings["bm25_tokenise_s"] = round(time.perf_counter() - t, 3)

        query, cat = inst["problem_statement"], CATEGORY[inst["category"]]
        rec["variants"] = {}
        for v in variants:
            cands = all_cands if v == "A" else [p for p in all_cands if not is_test.get(p, False)]
            cset = set(cands)
            qt, rk = {}, {}
            r = sorted(cands)
            random.Random(rs.SEED).shuffle(r)
            rk["random"] = r
            t = time.perf_counter()
            bm = rs.bm25_rank(query, cands, toks)
            qt["file-bm25"] = round(time.perf_counter() - t, 4)
            rk["file-bm25"] = bm

            t = time.perf_counter()     # bm25-graph: top 4 BM25 files, then the v0.1 bug walk (deps, distance 2)
            entries = [rel_of[p] for p in bm[:BM25_GRAPH_ENTRIES] if p in rel_of]
            walk = [path_of[x] for x, d in bundle.bfs(entries, bundle.deps, 2).items() if d and x in path_of]
            rk["bm25-graph"], _ = rs.complete(bm[:BM25_GRAPH_ENTRIES] + walk, cset, bm)
            qt["bm25-graph"] = round(time.perf_counter() - t, 4)

            for c, cfg in CONFIGS.items():
                t = time.perf_counter()
                hits = bundle.search(query, k=len(bundle.files), types=("Source File",), config=cfg)
                rk[f"rhizome-search [{c}]"], _ = rs.complete([path_of[h] for h, _ in hits], cset, bm)
                qt[f"rhizome-search [{c}]"] = round(time.perf_counter() - t, 4)
                for name, gcat in (("rhizome-ctx-cat", cat), ("rhizome-ctx-bug", "bug")):
                    t = time.perf_counter()
                    _, items, _ = gather(bundle, query, gcat, include_tests=(v == "A"), config=cfg)
                    rk[f"{name} [{c}]"], _ = rs.complete([path_of[i.rel] for i in items if i.rel in path_of],
                                                         cset, bm)
                    qt[f"{name} [{c}]"] = round(time.perf_counter() - t, 4)
                rk[f"fusion-rrf [{c}]"] = rs.rrf(bm, rk[f"rhizome-ctx-cat [{c}]"])
                rk[f"fusion-rrf-search [{c}]"] = rs.rrf(bm, rk[f"rhizome-search [{c}]"])
            rec["variants"][v] = {
                "n_candidates": len(cands), "gold_not_in_candidates": [g for g in gold if g not in cset],
                "query_s": qt,
                "methods": {m: {"top": rk[m][:TOP_SAVED], **metrics(rk[m], gold)} for m in METHODS}}
        rec["status"] = "ok"
        return rec
    finally:
        timings["total_s"] = round(time.perf_counter() - t0, 3)
        rec["timings"] = timings
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ summary

def agg(recs, v):
    out = {"n": len(recs)}
    for m in METHODS:
        rows = [r["variants"][v]["methods"][m] for r in recs]
        d = {f"acc@{k}": 100 * rs.mean(x[f"acc@{k}"] for x in rows) for k in KS}
        d.update({f"recall@{k}": 100 * rs.mean(x[f"recall@{k}"] for x in rows) for k in KS})
        d["mrr"] = rs.mean(x["mrr"] for x in rows)
        out[m] = d
    return out


def paired(recs, v, a, b, k):
    x = sum(1 for r in recs if r["variants"][v]["methods"][a][f"acc@{k}"] and not r["variants"][v]["methods"][b][f"acc@{k}"])
    y = sum(1 for r in recs if r["variants"][v]["methods"][b][f"acc@{k}"] and not r["variants"][v]["methods"][a][f"acc@{k}"])
    return {"a_only": x, "b_only": y, "p": rs.binom_two_sided(x, y)}


def recovered(recs, v, method, base="file-bm25", k=10):
    """Gold files in ``method``'s top k but not ``base``'s (recovered), and the reverse (pushed out)."""
    rec_n = out_n = total = 0
    for r in recs:
        tm = set(r["variants"][v]["methods"][method]["top"][:k])
        tb = set(r["variants"][v]["methods"][base]["top"][:k])
        for g in r["gold"]:
            total += 1
            rec_n += g in tm and g not in tb
            out_n += g in tb and g not in tm
    return {"recovered": rec_n, "pushed_out": out_n, "gold_files": total}


def summarise(out_dir, dataset_n, variants):
    recs = rs.load_records(os.path.join(out_dir, "per_instance.jsonl"))
    ok = [r for r in recs.values() if r.get("status") == "ok"]
    s = {"dataset_instances": dataset_n, "attempted": len(recs), "evaluated": len(ok),
         "excluded": [{"instance_id": r["instance_id"], "reason": r.get("exclude_reason")}
                      for r in recs.values() if r.get("status") == "excluded"],
         "errors": [{"instance_id": r["instance_id"], "error": r.get("error", "")[:300]}
                    for r in recs.values() if r.get("status") == "error"],
         "gold_files": dict(sorted(Counter(min(r["n_gold"], 3) for r in ok).items())),
         "variants": {}}
    for v in variants:
        vr = [r for r in ok if v in r.get("variants", {})]
        d = {"all": agg(vr, v), "paired": {}, "by_category": {}, "by_gold": {}, "recovered_2plus": {},
             "mean_candidates": rs.mean(r["variants"][v]["n_candidates"] for r in vr),
             "instances_with_gold_outside_candidates": sum(1 for r in vr if r["variants"][v]["gold_not_in_candidates"]),
             "query_s": {m: rs.mean(r["variants"][v]["query_s"].get(m, 0) for r in vr)
                         for m in METHODS if m != "random" and not m.startswith("fusion")}}
        for a, b in comparisons():
            d["paired"][f"{a} vs {b}"] = {f"acc@{k}": paired(vr, v, a, b, k) for k in KS}
        for c in sorted({r["category"] for r in vr}):
            d["by_category"][c] = agg([r for r in vr if r["category"] == c], v)
        multi = [r for r in vr if r["n_gold"] >= 2]
        d["by_gold"] = {"1": agg([r for r in vr if r["n_gold"] == 1], v), "2+": agg(multi, v)}
        for m in ["bm25-graph"] + [f"fusion-rrf [{c}]" for c in CONFIGS] + [f"rhizome-ctx-cat [{c}]" for c in CONFIGS]:
            d["recovered_2plus"][m] = recovered(multi, v, m)
        s["variants"][v] = d
    first = [r["timings"]["scan_s"] for r in ok if "scan_s" in r.get("timings", {})]
    s["cost"] = {"first_scans": len(first), "scan_mean_s": rs.mean(first), "scan_median_s": rs.median(first),
                 "scan_max_s": max(first) if first else None,
                 "materialise_mean_s": rs.mean(r["timings"].get("materialise_s", 0) for r in ok),
                 "bundle_load_mean_s": rs.mean(r["timings"].get("bundle_load_s", 0) for r in ok),
                 "bm25_tokenise_mean_s": rs.mean(r["timings"].get("bm25_tokenise_s", 0) for r in ok),
                 "instance_mean_s": rs.mean(r["timings"].get("total_s", 0) for r in ok),
                 "llm_calls": 0, "llm_tokens": 0}
    pe = {}
    for r in ok:
        for e in r.get("parse_errors", []):
            pe.setdefault((r["repo"], e["path"]), {"repo": r["repo"], "path": e["path"], "parser": e["parser"],
                                                   "error": e["error"], "instances": 0})["instances"] += 1
    s["parse_errors"] = sorted(pe.values(), key=lambda x: (x["repo"], x["path"]))
    s["extract_errors_py"] = sum(len(r.get("extract_errors_py", [])) for r in recs.values())
    s["candidates_without_concept"] = sum(r.get("candidates_without_concept", 0) for r in ok)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)
    return s


# ------------------------------------------------------------------ report

def f2(x, d=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def table(a: dict, methods=METHODS) -> list[str]:
    L = ["| Method | Acc@5 | Acc@10 | Recall@5 | Recall@10 | MRR |", "|---|---:|---:|---:|---:|---:|"]
    for m in methods:
        d = a[m]
        L.append(f"| {m} | {f2(d['acc@5'])} | {f2(d['acc@10'])} | {f2(d['recall@5'])} | {f2(d['recall@10'])} | "
                 f"{f2(d['mrr'], 3)} |")
    return L


def verdict(s, v) -> list[str]:
    d = s["variants"][v]
    a, P = d["all"], d["paired"]

    def line(x, y, k="acc@5"):
        p = P[f"{x} vs {y}"][k]
        diff = a[x][k] - a[y][k]
        word = ("no significant difference" if p["p"] >= 0.05 else ("better" if diff > 0 else "worse"))
        return (f"`{x}` vs `{y}` on {k.replace('acc', 'Acc')}: {word} ({a[x][k]:.1f} vs {a[y][k]:.1f}, "
                f"{diff:+.1f}; {p['a_only']} vs {p['b_only']} discordant, p = {p['p']:.3g}).")

    L = [f"**Variant {v}** (n = {a['n']}). \"Better\" / \"worse\" only where the exact McNemar p < 0.05."]
    for c in CONFIGS:
        for m in RHIZOME:
            L.append("- " + line(f"{m} [{c}]", "file-bm25"))
    L.append("- " + line("bm25-graph", "file-bm25"))
    L.append("- " + line("bm25-graph", "file-bm25", "acc@10"))
    for c in CONFIGS:
        L.append("- " + line(f"fusion-rrf [{c}]", f"fusion-rrf-search [{c}]"))
        L.append("- " + line(f"rhizome-ctx-cat [{c}]", f"rhizome-ctx-bug [{c}]"))
    for m in RHIZOME:
        L.append("- " + line(f"{m} [v0.2]", f"{m} [v0.1]"))
    rec = d["recovered_2plus"]
    L.append(f"- Multi-file instances ({d['by_gold']['2+']['n']}): in the top 10, `bm25-graph` recovers "
             f"{rec['bm25-graph']['recovered']} gold files that File-BM25 misses and pushes out "
             f"{rec['bm25-graph']['pushed_out']} (of {rec['bm25-graph']['gold_files']}); `fusion-rrf [v0.2]` "
             f"recovers {rec['fusion-rrf [v0.2]']['recovered']} and pushes out {rec['fusion-rrf [v0.2]']['pushed_out']}.")
    best = max((m for m in METHODS if m != "random"), key=lambda m: a[m]["acc@5"])
    L.append(f"- Highest Acc@5 here: `{best}` ({a[best]['acc@5']:.1f}). Published file-level Acc@5 (different setup, "
             f"not directly comparable): BM25 70.72, CodeRankEmbed 77.81, LocAgent (Claude-3.5) 84.59.")
    return L


def write_report(out_dir, s, variants, proto):
    L = ["# Rhizome on Loc-Bench V1: file-level localisation", "", "## 1. Protocol", "",
         f"- **Dataset**: `{DATASET}`, split `test` ({s['dataset_instances']} instances), the release named in the "
         f"LocAgent README. {s['attempted']} attempted, {s['evaluated']} evaluated, {len(s['excluded'])} excluded, "
         f"{len(s['errors'])} crashed.",
         "- **Gold**: `.py` files in the gold `patch` (`diff --git` lines) that exist at `base_commit`.",
         "- **Candidates**: `.py` files from `rhizome.parse_python.iter_python_files(snapshot)`; variant B = non-test "
         "files (Rhizome's `test` tag), variant A = all files.",
         "- **Query**: the full `problem_statement`, unmodified, identical for every method.",
         f"- **Rhizome code**: `{proto['rhizome_commit']}` (tag `v0.2.0-rc1`, branch `feat/v0.2-retrieval`). Every "
         "snapshot is scanned once with this code (heuristic summaries, no LLM). Each Rhizome method is ranked on the "
         "same bundle with `RetrievalConfig.v01()` (**[v0.1]**: v0.1 retrieval on a v0.2 bundle; the v0.2 scanner "
         "changes - tree-sitter fallback, re-export edges, cleaned descriptions - still apply) and with the v0.2 "
         "defaults (**[v0.2]**, `Bundle(..., repo=snapshot)`, so BM25F sees file bodies).",
         "- **Category mapping** for `rhizome-ctx-cat`: Bug Report -> `bug`, Feature Request -> `feature`, "
         "Security Vulnerability -> `security`, Performance Issue -> `bug`. `rhizome-ctx-bug` uses `bug` for all.",
         "- **Methods** (full rankings; Rhizome methods rank the files they return, then the rest in File-BM25 order):",
         "  - `random` (seed 0); `file-bm25` (Okapi BM25, k1 = 1.2, b = 0.75, whole files, Rhizome's tokeniser);",
         f"  - `bm25-graph`: the top {BM25_GRAPH_ENTRIES} File-BM25 files as entry points, then the v0.1 bug walk "
         "(dependencies to distance 2) in walk order;",
         "  - `rhizome-search`, `rhizome-ctx-cat`, `rhizome-ctx-bug` (`Bundle.search` / `gather`); `fusion-rrf` = RRF "
         "(k = 60) of File-BM25 and `rhizome-ctx-cat`; `fusion-rrf-search` = RRF of File-BM25 and `rhizome-search`.",
         "- **Metrics**: Acc@k = all gold files in the top k; Recall@k = fraction of gold files in the top k; MRR = "
         "1 / rank of the first gold file. Percent except MRR. Paired exact McNemar tests on Acc@5 and Acc@10.",
         "- **Frozen**: methods, comparisons and parameters were fixed before any Loc-Bench result; one run, no tuning.",
         f"- **Machine**: {proto['machine']}; Python {proto['python']}; started {proto['started']}; "
         f"arguments `{proto['args']}`.", ""]
    L += ["## 2. Results", ""]
    for v in variants:
        d = s["variants"][v]
        L += [f"### Variant {v} ({'non-test files' if v == 'B' else 'all files'})", "",
              f"n = {d['all']['n']}; mean {d['mean_candidates']:.0f} candidates; "
              f"{d['instances_with_gold_outside_candidates']} instances have a gold file outside the candidates "
              "(counted as misses).", ""] + table(d["all"]) + [""]
        L += ["Paired comparisons (instances solved by only the first / only the second method, exact McNemar):", "",
              "| Comparison | Acc@5 first / second / p | Acc@10 first / second / p |", "|---|---|---|"]
        for name, x in d["paired"].items():
            L.append(f"| {name} | {x['acc@5']['a_only']} / {x['acc@5']['b_only']} / {x['acc@5']['p']:.3g} | "
                     f"{x['acc@10']['a_only']} / {x['acc@10']['b_only']} / {x['acc@10']['p']:.3g} |")
        L += ["", "#### By category (Acc@5 / Acc@10)", ""]
        cats = list(d["by_category"])
        L += ["| Method | " + " | ".join(f"{c} (n = {d['by_category'][c]['n']})" for c in cats) + " |",
              "|---|" + "---:|" * len(cats)]
        for m in METHODS:
            L.append(f"| {m} | " + " | ".join(f"{d['by_category'][c][m]['acc@5']:.1f} / {d['by_category'][c][m]['acc@10']:.1f}"
                                            for c in cats) + " |")
        g1, g2 = d["by_gold"]["1"], d["by_gold"]["2+"]
        L += ["", "#### By number of gold files (Acc@5 / Acc@10 / Recall@10)", "",
              f"| Method | 1 gold file (n = {g1['n']}) | 2+ gold files (n = {g2['n']}) |", "|---|---:|---:|"]
        for m in METHODS:
            L.append(f"| {m} | {g1[m]['acc@5']:.1f} / {g1[m]['acc@10']:.1f} / {g1[m]['recall@10']:.1f} | "
                     f"{g2[m]['acc@5']:.1f} / {g2[m]['acc@10']:.1f} / {g2[m]['recall@10']:.1f} |")
        L += ["", "#### Multi-file instances: gold files recovered / pushed out in the top 10 vs File-BM25", "",
              "| Method | Recovered (in its top 10, not File-BM25's) | Pushed out (in File-BM25's top 10, not its) | Gold files |",
              "|---|---:|---:|---:|"]
        for m, x in d["recovered_2plus"].items():
            L.append(f"| {m} | {x['recovered']} | {x['pushed_out']} | {x['gold_files']} |")
        L.append("")
    c = s["cost"]
    L += ["### Cost", "", "LLM calls and tokens: 0 for every method.", "", "| Step | Seconds |", "|---|---:|",
          f"| Materialise snapshot, mean | {f2(c['materialise_mean_s'], 2)} |",
          f"| Rhizome scan, mean / median / max ({c['first_scans']} scans) | {f2(c['scan_mean_s'], 2)} / "
          f"{f2(c['scan_median_s'], 2)} / {f2(c['scan_max_s'], 2)} |",
          f"| Load bundle, mean | {f2(c['bundle_load_mean_s'], 2)} |",
          f"| Tokenise snapshot for File-BM25, mean | {f2(c['bm25_tokenise_mean_s'], 2)} |",
          f"| Whole instance, mean | {f2(c['instance_mean_s'], 2)} |"]
    for v in variants:
        for m, x in s["variants"][v]["query_s"].items():
            L.append(f"| Query `{m}` (variant {v}), mean | {f2(x, 4)} |")
    L += ["", "### Counts, crashes and parse errors", "",
          f"- Gold files per evaluated instance (3 = 3 or more): {s['gold_files']}.",
          f"- Excluded: {len(s['excluded'])}; crashed: {len(s['errors'])}"
          + ("".join(f"; `{e['instance_id']}`: {e['error']}" for e in s["errors"])) + ".",
          f"- `.py` files not extractable: {s['extract_errors_py']}; candidates without a concept: "
          f"{s['candidates_without_concept']}.",
          f"- Files `ast` could not parse: {len(s['parse_errors'])} distinct (repo, path). With parser `tree-sitter` "
          "imports and top-level definitions were recovered; with `failed` the file has no symbols or edges.", ""]
    if s["parse_errors"]:
        L += ["| Repository | Path | Parser | Error | Instances |", "|---|---|---|---|---:|"]
        L += [f"| {e['repo']} | `{e['path']}` | {e['parser']} | {str(e['error']).replace('|', '/')[:120]} | "
              f"{e['instances']} |" for e in s["parse_errors"]]
    L += ["", "## 3. Published results (different setups — not directly comparable)", "",
          "Z. Chen et al., *LocAgent: Graph-Guided LLM Agents for Code Localization*, ACL 2025, arXiv:2503.09089. "
          "Loc-Bench, file level, Acc@5. Copied from the paper, not measured here.", "",
          "| Method | Acc@5 |", "|---|---:|"] + [f"| {n} | {x:.2f} |" for n, x in PUBLISHED]
    L += ["", "## 4. Verdict", ""]
    for v in variants:
        L += verdict(s, v) + [""]
    L += ["## 5. Threats to validity", "",
          "- **[v0.1] is not the v0.1 system.** It is v0.1 retrieval on bundles built by the v0.2 scanner.",
          "- **Our BM25 is not LocAgent's.** Different tokeniser and indexing; published numbers also differ in candidate "
          "handling. Only our own rows are comparable with each other.",
          "- **Test files.** Variant B removes test files with Rhizome's path heuristic; a gold test file then counts as a miss.",
          "- **Fallback ordering.** Rhizome methods fill the rest of the ranking in File-BM25 order.",
          "- **Category mapping.** Performance issues use the `bug` walk; the mapping was fixed before the run.",
          "- **Multi-file subset is small** (see the gold-file breakdown), so its differences are noisy.",
          "- **v0.2 was designed after SWE-bench Lite, not Loc-Bench.** Loc-Bench was not looked at before the freeze.",
          "- **Many comparisons.** p-values are not corrected for multiple testing.",
          "- **Single run, one machine.** Timings depend on this machine and on on-demand blob fetching from GitHub.", ""]
    with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--variants", nargs="+", default=["B"], choices=["A", "B"])
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "locbench-v01"))
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    data = load_dataset()
    todo = data[: args.limit] if args.limit else data
    variants = sorted(set(args.variants))
    ppath = os.path.join(args.out, "protocol.json")
    proto = {"version": PROTOCOL_VERSION, "variants": variants, "methods": METHODS, "configs": list(CONFIGS),
             "rhizome_commit": rs.git_info(), "code_tag": rs.CODE_TAG,
             "machine": f"{platform.platform()}, {platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs",
             "python": platform.python_version(), "started": dt.datetime.now().isoformat(timespec="seconds"),
             "args": " ".join(sys.argv[1:])}
    if os.path.exists(ppath):
        old = json.load(open(ppath, encoding="utf-8"))
        for key in ("version", "variants", "methods", "configs", "code_tag"):   # code_tag = hash of rhizome/*.py
            if old.get(key) != proto[key]:
                sys.exit(f"protocol mismatch on resume ({key}: {old.get(key)} != {proto[key]}); use a new --out")
        proto = old
    else:
        json.dump(proto, open(ppath, "w", encoding="utf-8"), indent=1)
    jpath = os.path.join(args.out, "per_instance.jsonl")
    if not args.report_only:
        done = {k for k, r in rs.load_records(jpath).items() if r.get("status") in ("ok", "excluded")}
        pending = [x for x in todo if x["instance_id"] not in done]
        print(f"{len(todo)} selected, {len(todo) - len(pending)} done, {len(pending)} to run", flush=True)
        for i, inst in enumerate(pending, 1):
            t = time.perf_counter()
            try:
                rec = run_instance(inst, variants)
            except BaseException as exc:          # includes RecursionError; KeyboardInterrupt still stops the run
                if isinstance(exc, KeyboardInterrupt):
                    raise
                rec = {"instance_id": inst["instance_id"], "repo": inst["repo"], "category": inst["category"],
                       "status": "error", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            with open(jpath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            extra = ""
            if rec["status"] == "ok":
                m = rec["variants"][variants[-1]]["methods"]
                extra = (f"gold={rec['n_gold']} bm25={m['file-bm25']['acc@5']} "
                         f"ctx02={m['rhizome-ctx-cat [v0.2]']['acc@5']} fus02={m['fusion-rrf [v0.2]']['acc@5']}")
            print(f"[{i}/{len(pending)}] {inst['instance_id']} {rec['status']} {time.perf_counter() - t:.1f}s {extra}"
                  + (f" {rec.get('error', '')[:200]}" if rec["status"] == "error" else ""), flush=True)
    s = summarise(args.out, len(data), variants)
    write_report(args.out, s, variants, proto)
    for v in variants:
        print(f"\nVariant {v} (n = {s['variants'][v]['all']['n']})\n" + "\n".join(table(s["variants"][v]["all"])))
    print(f"\nevaluated {s['evaluated']}, excluded {len(s['excluded'])}, errors {len(s['errors'])}; "
          f"report: {os.path.join(args.out, 'REPORT.md')}")


if __name__ == "__main__":
    main()
