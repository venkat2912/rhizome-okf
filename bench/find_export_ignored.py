"""List benchmark instances whose snapshot lost or altered .py files through `git archive` attributes.

`git archive` drops paths marked `export-ignore` and rewrites `export-subst` files. Snapshots made that way
(SWE-bench Lite v0.1 run, first Loc-Bench run) can therefore miss candidate .py files. This checks the
.gitattributes of each base commit and writes the affected instance ids.

Usage: python bench/find_export_ignored.py loc_bench_v1.jsonl bench/runs/locbench-v01/export_ignored.json
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_swebench as rs  # noqa: E402


def check(inst):
    repo = os.path.join(rs.REPOS, inst["repo"].replace("/", "__"))
    py = [p for p in rs.tree_files(repo, inst["base_commit"]) if p.endswith(".py")]
    # git archive applies export-ignore to a directory entry and drops everything under it, but a directory
    # pattern does not match the files inside when queried, so ancestors are checked as well
    dirs = sorted({"/".join(p.split("/")[:i]) for p in py for i in range(1, p.count("/") + 1)})
    ign_paths = rs._attr_set(repo, inst["base_commit"], "export-ignore", py + dirs)
    ign = {p for p in py if p in ign_paths or any("/".join(p.split("/")[:i]) in ign_paths
                                                   for i in range(1, p.count("/") + 1))}
    sub = rs._attr_set(repo, inst["base_commit"], "export-subst", py)
    gold = set(rs.gold_files(inst["patch"]))
    return {"instance_id": inst["instance_id"], "repo": inst["repo"], "py_files": len(py),
            "export_ignored_py": len(ign), "export_subst_py": len(sub), "gold_affected": sorted(gold & (ign | sub))}


def main():
    data_file, out = sys.argv[1], sys.argv[2]
    data = [json.loads(l) for l in open(os.path.join(rs.CACHE, data_file), encoding="utf-8") if l.strip()]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(check, data))
    hit = [r for r in res if r["export_ignored_py"] or r["export_subst_py"]]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"instances": len(res), "affected": hit}, fh, indent=1)
    print(f"{len(hit)} of {len(res)} instances affected; {sum(1 for r in hit if r['gold_affected'])} with a gold file "
          f"affected; repos: {sorted({r['repo'] for r in hit})}")


if __name__ == "__main__":
    main()
