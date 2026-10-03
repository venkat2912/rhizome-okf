"""Phase 2 diagnosis (PLAN.md): does a local reranker lift File-BM25 on the SWE-rebench dev split?

No Rhizome changes and no bundle: for each task the File-BM25 ranking is computed, its top TOP_FILES files are
split into function chunks, the best CHUNKS_PER_FILE chunks of each file (by chunk BM25) are scored against
the issue by a local cross-encoder, and the top files are re-sorted by their best chunk's score. Files
beyond the top TOP_FILES keep their BM25 order. Paired with File-BM25 on the same tasks.

Settings are from first principles, not tuned: TOP_FILES = 35 (the pool whose perfect re-ranking gave 87.1%
recall@10 on Loc-Bench), CHUNKS_PER_FILE = 2 (70 judged chunks, close to the plan's budget of 60), query
truncated to QUERY_TOKENS = 256 of the model's 512-token window so the code gets the other half.

Usage: python bench/run_judge.py --sample 150 --out bench/runs/judge-dev-sample
"""
from __future__ import annotations

import argparse
import json
import os
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

import funcs  # noqa: E402
import rebench_select as sel  # noqa: E402
import run_rebench as rb  # noqa: E402
import run_swebench as rs  # noqa: E402
from rhizome.parse_python import iter_python_files  # noqa: E402
from rhizome.retrieve import tokens  # noqa: E402

TOP_FILES, CHUNKS_PER_FILE, QUERY_TOKENS, MAX_LEN, BATCH = 35, 2, 256, 512, 16
MODELS = {"minilm": "cross-encoder/ms-marco-MiniLM-L-6-v2", "gte": "Alibaba-NLP/gte-reranker-modernbert-base"}


class Judge:
    def __init__(self, name: str):
        os.environ.setdefault("HF_HOME", sel.HF_HOME)
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name).eval()

    def score(self, query: str, docs: list[str]) -> list[float]:
        q = self.tok.decode(self.tok(query, truncation=True, max_length=QUERY_TOKENS, add_special_tokens=False)["input_ids"])
        out = []
        with self.torch.inference_mode():
            for i in range(0, len(docs), BATCH):
                batch = docs[i:i + BATCH]
                enc = self.tok([q] * len(batch), batch, truncation="only_second", max_length=MAX_LEN, padding=True,
                               return_tensors="pt")
                out += self.model(**enc).logits.view(-1).tolist()
        return out


def is_test(p: str) -> bool:
    return sel.is_test_path(p)


def run_task(task, statement, judge, tmp_root=None):
    rec = {"instance_id": task["instance_id"], "repo": task["repo"], "gold": task["gold"], "n_gold": len(task["gold"])}
    repo_dir = rs.ensure_repo(task["repo"])
    rs.ensure_commit(repo_dir, task["base_commit"])
    tmp = tempfile.mkdtemp(prefix="rzj_", dir=tmp_root)
    try:
        t0 = time.perf_counter()
        rs.materialise(repo_dir, task["base_commit"], tmp)
        cands = [p for p in iter_python_files(tmp) if not is_test(p)]
        texts, toks = {}, {}
        for p in cands:
            with open(os.path.join(tmp, *p.split("/")), encoding="utf-8", errors="replace") as fh:
                texts[p] = fh.read()
            toks[p] = Counter(tokens(texts[p]))
        rec["n_candidates"] = len(cands)
        rec["prepare_s"] = round(time.perf_counter() - t0, 2)
        t = time.perf_counter()
        bm = rs.bm25_rank(statement, cands, toks)
        pool = bm[:TOP_FILES]
        chunk_tf, chunk_src, chunk_file = {}, {}, {}
        for p in pool:
            for cid, src in funcs.chunks(p, texts[p]):
                chunk_tf[cid], chunk_src[cid], chunk_file[cid] = Counter(tokens(src)), src, p
        order = rb.bm25_generic(tokens(statement), chunk_tf)
        picked, per_file = [], Counter()
        for cid in order:
            if per_file[chunk_file[cid]] < CHUNKS_PER_FILE:
                per_file[chunk_file[cid]] += 1
                picked.append(cid)
        docs = [f"{chunk_file[c]}\n{c.split('::', 1)[1]}\n{chunk_src[c]}" for c in picked]
        scores = judge.score(statement, docs)
        best = {}
        for c, s in zip(picked, scores):
            f = chunk_file[c]
            if f not in best or s > best[f][0]:
                best[f] = (s, c)
        pos = {p: i for i, p in enumerate(pool)}
        judged = sorted(pool, key=lambda p: (-best[p][0] if p in best else float("inf"), pos[p]))
        ranking = judged + bm[TOP_FILES:]
        rec["query_s"] = round(time.perf_counter() - t, 2)
        rec["judged_chunks"] = len(picked)
        rec["methods"] = {"file-bm25": {"top": bm[:50], **rb.file_metrics(bm, task["gold"])},
                          "judge": {"top": ranking[:50], **rb.file_metrics(ranking, task["gold"])}}
        rec["judge_reason"] = {p: best[p][1] for p in ranking[:10] if p in best}
        gset = set(task["gold"])
        rec["gold_in_pool"] = sum(1 for g in task["gold"] if g in set(pool))
        rec["oracle_recall@10"] = min(10, len(gset & set(pool))) / len(gset)
        rec["status"] = "ok"
        return rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def summarise(out_dir):
    recs = [r for r in rs.load_records(os.path.join(out_dir, "per_instance.jsonl")).values() if r.get("status") == "ok"]
    multi = [r for r in recs if r["n_gold"] >= 2]
    s = {"n": len(recs), "repos": len({r["repo"] for r in recs}), "multi_n": len(multi), "methods": {}, "paired": {}}
    for m in ("file-bm25", "judge"):
        d = {f"{a}@{k}": rb.boot_mean([r["methods"][m][f"{a}@{k}"] for r in recs]) for a in ("acc", "recall") for k in rb.KS}
        d["mrr"] = rb.boot_mean([r["methods"][m]["mrr"] for r in recs])
        d["multi_all_gold_top10"] = rb.boot_mean([r["methods"][m]["acc@10"] for r in multi])
        d["multi_all_gold_top5"] = rb.boot_mean([r["methods"][m]["acc@5"] for r in multi])
        s["methods"][m] = d
    for k in rb.KS:
        x = sum(1 for r in recs if r["methods"]["judge"][f"acc@{k}"] and not r["methods"]["file-bm25"][f"acc@{k}"])
        y = sum(1 for r in recs if r["methods"]["file-bm25"][f"acc@{k}"] and not r["methods"]["judge"][f"acc@{k}"])
        s["paired"][f"acc@{k}"] = {"judge_only": x, "bm25_only": y, "p": rs.binom_two_sided(x, y)}
    s["recall@10_diff"] = rb.boot_mean([r["methods"]["judge"]["recall@10"] - r["methods"]["file-bm25"]["recall@10"] for r in recs])
    s["oracle_recall@10_top35"] = rb.boot_mean([r["oracle_recall@10"] for r in recs])
    s["query_s_mean"] = rs.mean(r["query_s"] for r in recs)
    s["query_s_median"] = rs.median([r["query_s"] for r in recs])
    s["judged_chunks_mean"] = rs.mean(r["judged_chunks"] for r in recs)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)
    return s


def show(s):
    print(f"\nn = {s['n']} tasks in {s['repos']} repos; multi-file n = {s['multi_n']}")
    print("| Method | Acc@1 | Acc@5 | Acc@10 | Recall@5 | Recall@10 | MRR | multi: all gold top 10 |")
    print("|---|---|---|---|---|---|---|---|")
    for m, d in s["methods"].items():
        print(f"| {m} | {rb.ci(d['acc@1'])} | {rb.ci(d['acc@5'])} | {rb.ci(d['acc@10'])} | {rb.ci(d['recall@5'])} | "
              f"{rb.ci(d['recall@10'])} | {rb.ci(d['mrr'], False, 3)} | {rb.ci(d['multi_all_gold_top10'])} |")
    print("paired (judge only / BM25 only / p):", {k: (v["judge_only"], v["bm25_only"], round(v["p"], 4)) for k, v in s["paired"].items()})
    print("recall@10 difference judge - bm25:", rb.ci(s["recall@10_diff"]), "| oracle recall@10 from the BM25 top 35:",
          rb.ci(s["oracle_recall@10_top35"]))
    print(f"query seconds: median {s['query_s_median']:.1f}, mean {s['query_s_mean']:.1f}; judged chunks mean "
          f"{s['judged_chunks_mean']:.0f}; LLM tokens 0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS), default="minilm")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    if not args.report_only:
        tasks = json.load(open(rb.SPLITS, encoding="utf-8"))["splits"]["dev"]["tasks"]      # dev only, never test
        if args.sample:
            tasks = sorted(random.Random(rb.SEED).sample(tasks, min(args.sample, len(tasks))), key=lambda t: t["instance_id"])
        want = {t["instance_id"] for t in tasks}
        stmt = {r["instance_id"]: r["problem_statement"] for r in sel.load_rows(["instance_id", "problem_statement"])
                if r["instance_id"] in want}
        jpath = os.path.join(args.out, "per_instance.jsonl")
        done = {k for k, r in rs.load_records(jpath).items() if r.get("status") == "ok"}
        judge = Judge(MODELS[args.model])
        json.dump({"model": MODELS[args.model], "top_files": TOP_FILES, "chunks_per_file": CHUNKS_PER_FILE,
                   "query_tokens": QUERY_TOKENS, "max_len": MAX_LEN, "sample": args.sample, "split": "dev"},
                  open(os.path.join(args.out, "protocol.json"), "w", encoding="utf-8"), indent=1)
        todo = [t for t in tasks if t["instance_id"] not in done]
        print(f"{len(tasks)} tasks, {len(todo)} to run, model {MODELS[args.model]}", flush=True)
        for i, task in enumerate(todo, 1):
            t = time.perf_counter()
            try:
                rec = run_task(task, stmt[task["instance_id"]], judge)
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                rec = {"instance_id": task["instance_id"], "repo": task["repo"], "status": "error",
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            with open(jpath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            extra = (f"bm25@10={rec['methods']['file-bm25']['acc@10']} judge@10={rec['methods']['judge']['acc@10']} "
                     f"q={rec['query_s']}s") if rec["status"] == "ok" else rec.get("error", "")[:160]
            print(f"[{i}/{len(todo)}] {task['instance_id']} {rec['status']} {time.perf_counter() - t:.1f}s {extra}", flush=True)
    show(summarise(args.out))


if __name__ == "__main__":
    main()
