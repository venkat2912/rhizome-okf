"""Select the SWE-rebench dev and sealed-test splits for Rhizome v0.3 (PLAN.md, Phase 1).

Fixed before any v0.3 result:
  * source   nebius/SWE-rebench, split `test` (21,336 tasks)
  * filter   repo not in SWE-bench Lite or Loc-Bench; non-empty problem statement; 1-5 non-test gold .py
             files in the patch, all present at base_commit; at least MIN_FILES non-test .py files in the
             snapshot (in smaller repositories a random ranking already puts the gold file in the top 10)
  * sample   repos with at least MIN_TASKS eligible tasks, shuffled with seed 0 and taken in that order;
             alternately assigned to dev and test until each has N_REPOS repos; at most MAX_TASKS tasks per
             repo (seeded sample). A repo is skipped if it cannot be cloned or keeps fewer than MIN_TASKS tasks
             after the base-commit check.
  * split    by repository: no repo is in both splits. The test split is sealed until Phase 6.

Writes bench/splits/swe-rebench-v0.3.json (instance ids, repo, base commit, gold files; no issue text).

Usage: python bench/rebench_select.py
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import run_swebench as rs  # noqa: E402

DATASET = "nebius/SWE-rebench"
FILES = ["data/test-00000-of-00002.parquet", "data/test-00001-of-00002.parquet"]
SEED, N_REPOS, MIN_TASKS, MAX_TASKS, MAX_GOLD = 0, 150, 3, 8, 5
MIN_FILES = 50      # candidate files per snapshot; set after the 40-task smoke test, before any dev result
OUT = os.path.join(HERE, "splits", "swe-rebench-v0.3.json")
HF_HOME = os.path.join(rs.CACHE, "hf")


def load_rows(columns):
    os.environ.setdefault("HF_HOME", HF_HOME)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    rows = []
    for f in FILES:
        rows += pq.read_table(hf_hub_download(DATASET, f, repo_type="dataset"), columns=columns).to_pylist()
    return rows


def is_test_path(p: str) -> bool:
    """Same rule as rhizome.parse_python (FileInfo.is_test)."""
    parts = p.split("/")
    return (any(q in ("tests", "test", "testing") for q in parts[:-1]) or parts[-1].startswith("test_")
            or parts[-1].endswith("_test.py") or parts[-1] == "conftest.py")


def gold_files(patch: str) -> list[str]:
    return [p for p in rs.gold_files(patch or "") if not is_test_path(p)]


def seen_repos() -> set[str]:
    out = set()
    for fn in ("swe_bench_lite.jsonl", "loc_bench_v1.jsonl"):
        with open(os.path.join(rs.CACHE, fn), encoding="utf-8") as fh:
            out |= {json.loads(line)["repo"].lower() for line in fh}
    return out


def clone(repo: str) -> str | None:
    dest = os.path.join(rs.REPOS, repo.replace("/", "__"))
    if os.path.isdir(dest):
        return dest
    r = subprocess.run(["git", "clone", "--bare", "--quiet", "--filter=blob:none",
                        f"https://github.com/{repo}.git", dest + ".partial"], capture_output=True, text=True,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if r.returncode:
        return None
    for attempt in range(10):           # Windows: antivirus / indexer can hold the new folder briefly
        try:
            os.rename(dest + ".partial", dest)
            return dest
        except PermissionError:
            time.sleep(2 * (attempt + 1))
    return None


def candidate_count(repo_dir: str, commit: str, gold: list[str]) -> int:
    """Non-test .py files at ``commit`` (the harness's candidate set), or -1 if a gold file is missing."""
    from rhizome.parse_python import SKIP_DIRS
    try:
        rs.ensure_commit(repo_dir, commit)
        files = rs.tree_files(repo_dir, commit)
    except Exception:
        return -1
    if not set(gold) <= set(files):
        return -1
    n = 0
    for p in files:
        parts = p.split("/")
        if p.endswith(".py") and not is_test_path(p) and not any(d in SKIP_DIRS or d.startswith(".") for d in parts[:-1]):
            n += 1
    return n


def main():
    rows = load_rows(["instance_id", "repo", "base_commit", "patch", "problem_statement", "created_at"])
    seen = seen_repos()
    by_repo = defaultdict(list)
    counts = Counter()
    for r in rows:
        if r["repo"].lower() in seen:
            counts["repo in SWE-bench Lite / Loc-Bench"] += 1
            continue
        g = gold_files(r["patch"])
        if not (r["problem_statement"] or "").strip():
            counts["empty problem statement"] += 1
        elif not 1 <= len(g) <= MAX_GOLD:
            counts["0 or more than 5 non-test gold .py files"] += 1
        else:
            by_repo[r["repo"]].append({"instance_id": r["instance_id"], "repo": r["repo"],
                                       "base_commit": r["base_commit"], "gold": g, "created_at": r["created_at"]})
    eligible = sorted(r for r, t in by_repo.items() if len(t) >= MIN_TASKS)
    order = list(eligible)
    random.Random(SEED).shuffle(order)
    print(f"{len(rows)} tasks; patch-eligible {sum(len(t) for t in by_repo.values())} in {len(by_repo)} repos; "
          f"{len(eligible)} repos with >= {MIN_TASKS} tasks", flush=True)

    os.makedirs(rs.REPOS, exist_ok=True)
    splits = {"dev": [], "test": []}
    repos = {"dev": [], "test": []}
    skipped = []
    pos, turn = 0, 0
    while pos < len(order) and (len(repos["dev"]) < N_REPOS or len(repos["test"]) < N_REPOS):
        batch = order[pos:pos + 24]
        pos += len(batch)
        with ThreadPoolExecutor(6) as ex:
            dirs = dict(zip(batch, ex.map(clone, batch)))
        for repo in batch:
            name = "dev" if turn % 2 == 0 else "test"
            if len(repos[name]) >= N_REPOS:
                name = "test" if name == "dev" else "dev"
                if len(repos[name]) >= N_REPOS:
                    break
            if dirs[repo] is None:
                skipped.append({"repo": repo, "reason": "clone failed"})
                continue
            ok = []
            for t in by_repo[repo]:
                t["n_candidates"] = candidate_count(dirs[repo], t["base_commit"], t["gold"])
                if t["n_candidates"] >= MIN_FILES:
                    ok.append(t)
            if len(ok) < MIN_TASKS:
                small = sum(1 for t in by_repo[repo] if 0 <= t["n_candidates"] < MIN_FILES)
                skipped.append({"repo": repo, "reason": "too small" if small else "gold missing",
                                "detail": f"{len(ok)} of {len(by_repo[repo])} tasks usable; {small} below "
                                          f"{MIN_FILES} candidate files"})
                continue
            ok.sort(key=lambda t: t["instance_id"])
            chosen = sorted(random.Random(f"{SEED}:{repo}").sample(ok, min(MAX_TASKS, len(ok))),
                            key=lambda t: t["instance_id"])
            repos[name].append(repo)
            splits[name] += chosen
            turn += 1
        print(f"processed {pos}/{len(order)} repos: dev {len(repos['dev'])} repos / {len(splits['dev'])} tasks, "
              f"test {len(repos['test'])} / {len(splits['test'])}, skipped {len(skipped)}", flush=True)

    assert not set(repos["dev"]) & set(repos["test"])
    out = {"dataset": DATASET, "split": "test", "seed": SEED,
           "rule": {"n_repos_per_split": N_REPOS, "min_tasks_per_repo": MIN_TASKS, "max_tasks_per_repo": MAX_TASKS,
                    "max_gold_files": MAX_GOLD, "min_candidate_files": MIN_FILES, "gold": "non-test .py files in the patch, all present at base_commit"},
           "filtered_out": dict(counts), "eligible_repos": len(eligible), "repos_examined": pos, "skipped": skipped,
           "sealed": ["test"],
           "splits": {k: {"repos": sorted(repos[k]), "tasks": v} for k, v in splits.items()}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    for k, v in splits.items():
        print(f"{k}: {len(repos[k])} repos, {len(v)} tasks, gold files "
              f"{dict(sorted(Counter(min(len(t['gold']), 3) for t in v).items()))} (3 = 3-5)")
    print(f"skipped {len(skipped)} repos: {dict(Counter(s['reason'] for s in skipped))}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
