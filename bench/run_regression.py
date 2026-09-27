"""Regression check (NOT an evaluation): Rhizome retrieval configs on already-seen SWE-bench Lite instances.

SWE-bench Lite was used to design v0.2, so numbers here must not be read as evidence that a change works,
and no parameter may be changed because of them. This only checks that every configuration runs and that
nothing regressed badly. Each instance is scanned once with the current (v0.2) scanner; every configuration
then ranks the same candidates with the same query. Scanner-level changes (#7 tree-sitter fallback,
#8 re-exports, #10 descriptions) are active in all configurations, so "v0.1 config" is v0.1 retrieval on a
v0.2 bundle, not the v0.1 system.

Usage: python bench/run_regression.py --limit 30 --out bench/runs/v02-regression
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import run_swebench as rs  # noqa: E402
from rhizome.parse_python import iter_python_files  # noqa: E402
from rhizome.retrieve import Bundle, RetrievalConfig, gather, tokens  # noqa: E402

V01 = RetrievalConfig.v01()
CONFIGS = {
    "v0.1 config": V01,
    "v0.2 full": RetrievalConfig(),
    "+#1 bm25f": dataclasses.replace(V01, bm25f=True),
    "+#3 adaptive entries": dataclasses.replace(V01, adaptive_entries=True),
    "+#4 never demote": dataclasses.replace(V01, never_demote=True),
    "+#5 ppr": dataclasses.replace(V01, expansion="ppr"),
    "+#5 ppr +#9 hubs": dataclasses.replace(V01, expansion="ppr", hub_downweight=True),
    "+#6 include_tests": dataclasses.replace(V01, respect_include_tests=True),
}


def run_one(inst: dict) -> dict:
    rec = {"instance_id": inst["instance_id"], "repo": inst["repo"]}
    repo_dir = rs.ensure_repo(inst["repo"])
    rs.ensure_commit(repo_dir, inst["base_commit"])
    tmp = tempfile.mkdtemp(prefix="rzr_")
    try:
        snap = os.path.join(tmp, "s")
        os.makedirs(snap)
        mat = rs.materialise(repo_dir, inst["base_commit"], snap)
        gold = [g for g in rs.gold_files(inst["patch"]) if g in mat["names"]]
        if not gold:
            rec["status"] = "excluded"
            return rec
        t = time.perf_counter()
        bdir, binfo = rs.bundle_for(inst["repo"], inst["base_commit"], snap, tmp)
        rec["scan_s"] = binfo["seconds"]
        rec["scan_stats"] = binfo["stats"]
        bundle = Bundle(bdir, repo=snap)
        path_of = {r: str(c.fm.get("title")) for r, c in bundle.files.items()}
        is_test = {path_of[r]: "test" in (c.fm.get("tags") or []) for r, c in bundle.files.items()}
        cands = [p for p in iter_python_files(snap) if not is_test.get(p, False)]   # variant B
        cset = set(cands)
        toks = {}
        for p in cands:
            with open(os.path.join(snap, *p.split("/")), encoding="utf-8", errors="replace") as fh:
                toks[p] = Counter(tokens(fh.read()))
        bm = rs.bm25_rank(inst["problem_statement"], cands, toks)
        rec["gold"] = gold
        rec["methods"] = {"file-bm25": rs.metrics(bm, gold)}
        for name, cfg in CONFIGS.items():
            t = time.perf_counter()
            hits = bundle.search(inst["problem_statement"], k=len(bundle.files), types=("Source File",), config=cfg)
            search, _ = rs.complete([path_of[h] for h, _ in hits], cset, bm)
            _, items, _ = gather(bundle, inst["problem_statement"], "bug", include_tests=False, config=cfg)
            ctx, _ = rs.complete([path_of[i.rel] for i in items if i.rel in path_of], cset, bm)
            rec["methods"][f"{name} | search"] = rs.metrics(search, gold)
            rec["methods"][f"{name} | ctx-bug"] = rs.metrics(ctx, gold)
            rec["methods"][f"{name} | ctx-bug"]["query_s"] = round(time.perf_counter() - t, 3)
        rec["status"] = "ok"
        return rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "v02-regression"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    data = rs.load_dataset()[: args.limit]
    path = os.path.join(args.out, "per_instance.jsonl")
    done = set(rs.load_records(path))
    for i, inst in enumerate(data, 1):
        if inst["instance_id"] in done:
            continue
        t = time.perf_counter()
        try:
            rec = run_one(inst)
        except Exception as exc:
            rec = {"instance_id": inst["instance_id"], "status": "error", "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"[{i}/{len(data)}] {inst['instance_id']} {rec['status']} {time.perf_counter() - t:.1f}s", flush=True)
    recs = [r for r in rs.load_records(path).values() if r.get("status") == "ok"]
    names = list(recs[0]["methods"]) if recs else []
    lines = ["# v0.2 regression check on SWE-bench Lite (already-seen data, NOT an evaluation)", "",
             f"First {args.limit} instances, variant B (non-test files), query = problem statement, category `bug`. "
             f"{len(recs)} ok, {sum(1 for r in rs.load_records(path).values() if r.get('status') == 'error')} errors. "
             "Do not tune on these numbers. See the module docstring for what \"v0.1 config\" means here.", "",
             "| Method | Acc@1 | Acc@5 | MRR |", "|---|---:|---:|---:|"]
    for n in names:
        rows = [r["methods"][n] for r in recs]
        lines.append(f"| {n} | {100 * rs.mean(x['acc@1'] for x in rows):.1f} | "
                     f"{100 * rs.mean(x['acc@5'] for x in rows):.1f} | {rs.mean(x['mrr'] for x in rows):.3f} |")
    with open(os.path.join(args.out, "REGRESSION.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
