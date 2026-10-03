"""EXPLORATORY, POST-HOC. Co-change history for the gold and anchored random pairs of section G.

For every pair written by trace.py (data/pairs.csv), counts the commits that touched both files in the
repository's history up to and including ``base_commit`` (only information available at the base commit).
Reads the blobless bare clones in bench/.cache/repos; path-limited `git log` needs commits and trees only.

Usage: python bench/analysis/locbench/relations.py
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DATA = os.path.join(HERE, "data")
REPOS = os.path.join(REPO, "bench", ".cache", "repos")
LOCBENCH = os.path.join(REPO, "bench", ".cache", "loc_bench_v1.jsonl")


def commits_touching(repo_dir, base, path, cache):
    key = (repo_dir, base, path)
    if key not in cache:
        r = subprocess.run(["git", "-C", repo_dir, "log", "--format=%H", base, "--", path],
                           capture_output=True, text=True, timeout=600)
        cache[key] = set(r.stdout.split()) if r.returncode == 0 else set()
    return cache[key]


def main():
    base = {}
    with open(LOCBENCH, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            base[r["instance_id"]] = (r["repo"], r["base_commit"])
    pairs = list(csv.DictReader(open(os.path.join(DATA, "pairs.csv"), encoding="utf-8")))
    cache: dict = {}
    out = open(os.path.join(DATA, "cochange.csv"), "w", newline="", encoding="utf-8")
    w = csv.DictWriter(out, fieldnames=["instance_id", "kind", "src", "dst", "commits_src", "commits_dst",
                                        "co_commits", "jaccard"])
    w.writeheader()
    t0 = time.perf_counter()
    for i, p in enumerate(pairs, 1):
        repo, commit = base[p["instance_id"]]
        rd = os.path.join(REPOS, repo.replace("/", "__"))
        a = commits_touching(rd, commit, p["src"], cache)
        b = commits_touching(rd, commit, p["dst"], cache)
        co = len(a & b)
        w.writerow({"instance_id": p["instance_id"], "kind": p["kind"], "src": p["src"], "dst": p["dst"],
                    "commits_src": len(a), "commits_dst": len(b), "co_commits": co,
                    "jaccard": round(co / len(a | b), 6) if a | b else 0.0})
        if i % 200 == 0:
            print(f"{i}/{len(pairs)} pairs, {time.perf_counter() - t0:.0f}s", flush=True)
    out.close()
    print(f"done: {len(pairs)} pairs in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
