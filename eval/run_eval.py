"""Evaluation harness used for the paper.

A. Scan statistics per repository (size, time, bundle size, conformance, incremental cost).
B. Leiden vs Louvain: disconnected communities on real import graphs (10 seeds each).
C. Co-change retrieval: build the graph at an older snapshot T, then for every later
   commit that touched 2-10 Python files, use each touched file as the "task seed" and
   measure how many of the *other* files changed in that commit each method ranks in its
   top-k. Ground truth comes from real future history, so there is no leakage.

Usage: python eval/run_eval.py <repo> [<repo> ...] --out results.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict

import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rhizome import okf  # noqa: E402
from rhizome.graph import (build_graph, disconnected_count, hierarchy, leiden, louvain,  # noqa: E402
                           undirected)
from rhizome.parse_python import iter_python_files, parse_file  # noqa: E402
from rhizome.retrieve import tokens  # noqa: E402
from rhizome.scanner import scan  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def dir_size(path):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)


# ------------------------------------------------------------------ A. scan stats

def scan_stats(repo):
    work = tempfile.mkdtemp()
    dst = os.path.join(work, os.path.basename(repo))
    shutil.copytree(repo, dst, symlinks=True, ignore=shutil.ignore_patterns(".knowledge"))
    res = scan(dst)
    out = os.path.join(dst, ".knowledge")
    v = okf.validate(out)
    # incremental: append a function to the most central non-test file, rescan
    files = {p: parse_file(dst, p) for p in iter_python_files(dst, [".knowledge"])}
    G = build_graph(files)
    cand = sorted((p for p in files if not files[p].is_test), key=lambda p: -G.in_degree(p))
    target = cand[len(cand) // 2]
    with open(os.path.join(dst, target), "a") as fh:
        fh.write("\n\ndef _rhizome_eval_probe():\n    return 1\n")
    t = time.time()
    res2 = scan(dst)
    inc_s = time.time() - t
    stale_ok = scan(dst, dry_run=True).changed == []
    stats = dict(res.stats)
    stats.update({"validate_ok": v["ok"], "documents_on_disk": v["documents"],
                  "bundle_kb": round(dir_size(out) / 1024, 1),
                  "incremental_target": target, "incremental_changed_docs": len(res2.changed),
                  "incremental_seconds": round(inc_s, 2), "idempotent_after_update": stale_ok})
    shutil.rmtree(work)
    return stats


# ------------------------------------------------------------------ B. Leiden vs Louvain

def connectivity(repo, seeds=10):
    files = {p: parse_file(repo, p) for p in iter_python_files(repo, [".knowledge"])}
    U = undirected(build_graph(files))
    L = U.subgraph([n for n in U if U.degree(n)]).copy()
    out = {"nodes": L.number_of_nodes(), "edges": L.number_of_edges(), "leiden": [], "louvain": []}
    for s in range(seeds):
        for name, fn in (("leiden", leiden), ("louvain", louvain)):
            comms = fn(L, seed=s)
            multi = [c for c in comms if len(c) > 1]
            out[name].append({"communities": len(comms), "multi": len(multi),
                              "disconnected": disconnected_count(L, comms),
                              "modularity": round(nx.community.modularity(L, comms, weight="weight"), 4)})
    for name in ("leiden", "louvain"):
        rows = out[name]
        out[f"{name}_summary"] = {
            "mean_communities": round(sum(r["communities"] for r in rows) / len(rows), 1),
            "mean_modularity": round(sum(r["modularity"] for r in rows) / len(rows), 4),
            "runs_with_disconnected": sum(1 for r in rows if r["disconnected"]),
            "total_disconnected": sum(r["disconnected"] for r in rows),
            "total_multi": sum(r["multi"] for r in rows),
        }
    return out


# ------------------------------------------------------------------ C. co-change retrieval

def pick_snapshot(repo, want=300, min_py=2, max_py=10):
    log = git(repo, "log", "--no-merges", "--name-only", "--format=@@%H")
    commits = []
    for block in log.split("@@")[1:]:
        lines = [ln for ln in block.strip().splitlines() if ln]
        sha, changed = lines[0], [ln for ln in lines[1:] if ln.endswith(".py")]
        if min_py <= len(changed) <= max_py:
            commits.append((sha, changed))
        if len(commits) >= want:
            break
    oldest = commits[-1][0]
    return git(repo, "rev-parse", f"{oldest}^").strip(), commits


def export_snapshot(repo, sha):
    d = tempfile.mkdtemp()
    p1 = subprocess.Popen(["git", "-C", repo, "archive", sha], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", d], stdin=p1.stdout, check=True)
    p1.wait()
    return d


def tfidf_vectors(snap, paths):
    tf = {}
    for p in paths:
        with open(os.path.join(snap, p), encoding="utf-8", errors="replace") as fh:
            tf[p] = Counter(tokens(fh.read()))
    df = Counter()
    for c in tf.values():
        df.update(c.keys())
    n = len(tf)
    vec = {}
    for p, c in tf.items():
        v = {t: (1 + math.log(f)) * math.log((1 + n) / (1 + df[t])) for t, f in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vec[p] = {t: x / norm for t, x in v.items()}
    return vec


def cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def cochange(repo, want=300, ks=(5, 10), seed=0):
    snap_sha, commits = pick_snapshot(repo, want)
    snap = export_snapshot(repo, snap_sha)
    files = {p: parse_file(snap, p) for p in iter_python_files(snap)}
    G = build_graph(files)
    U = undirected(G)
    comms = hierarchy(G, max_size=15)
    l1 = {m: c.slug for c in comms.values() if c.level == 1 for m in c.members}
    l2 = {m: c.slug for c in comms.values() if c.level == 2 for m in c.members}
    paths = sorted(files)
    vec = tfidf_vectors(snap, paths)
    rng = random.Random(seed)

    def lexical(s):
        return sorted((p for p in paths if p != s), key=lambda p: (-cos(vec[s], vec[p]), p))

    def directory(s):
        d = s.rsplit("/", 1)[0] if "/" in s else ""
        lex = lexical(s)
        same = [p for p in lex if (p.rsplit("/", 1)[0] if "/" in p else "") == d]
        return same + [p for p in lex if p not in set(same)]

    def graph_rank(s):
        dist = nx.single_source_shortest_path_length(U, s, cutoff=3) if s in U else {s: 0}
        lexs = {p: cos(vec[s], vec[p]) for p in paths}
        w = {n: U[s][n]["weight"] for n in U.neighbors(s)} if s in U else {}
        order = sorted((p for p in dist if p != s),
                       key=lambda p: (dist[p], -(w.get(p, 0)), -lexs[p]))
        seen = set(order) | {s}
        comm = [p for p in paths if p not in seen and (l2.get(p) and l2.get(p) == l2.get(s))]
        comm += [p for p in paths if p not in seen and p not in set(comm) and l1.get(p) == l1.get(s)]
        comm.sort(key=lambda p: -lexs[p])
        seen |= set(comm)
        rest = sorted((p for p in paths if p not in seen), key=lambda p: -lexs[p])
        return order + comm + rest

    def graph1_lex(s):
        # hybrid: direct neighbours (by weight) interleaved with lexical top hits
        g = graph_rank(s)
        lex = lexical(s)
        out, seen = [], set()
        for a, b in zip(g, lex):
            for x in (a, b):
                if x not in seen:
                    out.append(x)
                    seen.add(x)
        return out

    def rrf(s, k0=60):
        # reciprocal rank fusion of the lexical and graph rankings (Cormack et al., 2009)
        sc = defaultdict(float)
        for ranking in (lexical(s), graph_rank(s)):
            for i, p in enumerate(ranking):
                sc[p] += 1.0 / (k0 + i + 1)
        return sorted(sc, key=lambda p: (-sc[p], p))

    def community(s):
        lex = lexical(s)
        same2 = [p for p in lex if l2.get(s) and l2.get(p) == l2.get(s)]
        same1 = [p for p in lex if p not in set(same2) and l1.get(p) == l1.get(s)]
        seen = set(same2) | set(same1)
        return same2 + same1 + [p for p in lex if p not in seen]

    def rand(s):
        others = [p for p in paths if p != s]
        rng.shuffle(others)
        return others

    methods = {"random": rand, "lexical (TF-IDF)": lexical, "same directory + lexical": directory,
               "Leiden community + lexical": community, "graph (import distance)": graph_rank,
               "hybrid (graph ⊕ lexical)": graph1_lex, "fusion (RRF lexical+graph)": rrf}
    scores = {m: {k: [] for k in ks} for m in methods}
    hits = {m: {k: [] for k in ks} for m in methods}
    pairs = 0
    used_commits = 0
    only_graph, only_lex, both = [], [], []
    for sha, changed in commits:
        present = [p for p in changed if p in files]
        if len(present) < 2:
            continue
        used_commits += 1
        for s in present:
            gt = set(present) - {s}
            pairs += 1
            lx, gr = set(lexical(s)[:10]), set(graph_rank(s)[:10])
            only_graph.append(len(gt & (gr - lx)) / len(gt))
            only_lex.append(len(gt & (lx - gr)) / len(gt))
            both.append(len(gt & (lx | gr)) / len(gt))
            for m, fn in methods.items():
                ranked = fn(s)
                for k in ks:
                    top = set(ranked[:k])
                    scores[m][k].append(len(gt & top) / len(gt))
                    hits[m][k].append(1.0 if gt & top else 0.0)
    shutil.rmtree(snap)
    res = {"snapshot": snap_sha[:10], "snapshot_date": git(repo, "show", "-s", "--format=%cs", snap_sha).strip(),
           "files_at_snapshot": len(files), "edges": G.number_of_edges(), "commits_used": used_commits,
           "seed_pairs": pairs, "recall": {}, "hit": {},
           "complementarity_at10": {"found_only_by_graph": round(sum(only_graph) / max(1, pairs), 4),
                                    "found_only_by_lexical": round(sum(only_lex) / max(1, pairs), 4),
                                    "found_by_either": round(sum(both) / max(1, pairs), 4)}}
    for m in methods:
        res["recall"][m] = {k: round(sum(v) / len(v), 4) if v else None for k, v in scores[m].items()}
        res["hit"][m] = {k: round(sum(v) / len(v), 4) if v else None for k, v in hits[m].items()}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--commits", type=int, default=300)
    ap.add_argument("--skip-cochange", action="append", default=[])
    a = ap.parse_args()
    results = {}
    for r in a.repos:
        name = os.path.basename(os.path.abspath(r))
        print(f"== {name}", flush=True)
        entry = {"head": git(r, "rev-parse", "--short", "HEAD").strip()}
        entry["scan"] = scan_stats(r)
        print("  scan", entry["scan"], flush=True)
        entry["connectivity"] = connectivity(r)
        print("  leiden", entry["connectivity"]["leiden_summary"], "louvain",
              entry["connectivity"]["louvain_summary"], flush=True)
        if name not in a.skip_cochange:
            entry["cochange"] = cochange(r, a.commits)
            print("  cochange", json.dumps(entry["cochange"]["recall"]), flush=True)
        results[name] = entry
        with open(a.out, "w") as fh:
            json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
