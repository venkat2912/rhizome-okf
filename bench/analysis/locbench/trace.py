"""EXPLORATORY, POST-HOC. Trace every retrieval component of the Loc-Bench run (variant B).

Uses Rhizome exactly as frozen at tag v0.2.0-rc1, imported from a separate worktree
(bench/.cache/wt-rc1), and the cached bundles that produced the saved results. For each instance it
re-derives all 13 rankings, checks them against the saved top 100 (instances that do not match are
flagged and excluded downstream), and records what each component suggested:

  * file-bm25, rhizome-search [v0.1] / [v0.2]: top 100 with scores
  * gather() items (exact, from the tag's own gather) with their reason -> component provenance
  * v0.2 entry threshold, strong-match band, full PPR candidate list (mass, text, combined score)
  * v0.1 walk / bm25-graph walk items with distance
  * per-file attributes: gold, fan-in/out, __init__.py, same directory as a gold file, parser
  * BM25F name / doc / body contributions (v0.2 search) for gold files and top-10 files
  * graph distances for gold files, PPR mass on hubs
  * relation features for gold pairs and anchored random pairs (2+-gold instances, section G)

Nothing in rhizome/ is changed. Outputs go to bench/analysis/locbench/data/.

Usage: python bench/analysis/locbench/trace.py [--limit N] [--instance ID ...]
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from collections import Counter, defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
WT = os.path.join(REPO, "bench", ".cache", "wt-rc1")
sys.path.insert(0, WT)                       # frozen Rhizome (tag v0.2.0-rc1) first
import rhizome                              # noqa: E402
assert os.path.normcase(os.path.dirname(os.path.dirname(rhizome.__file__))) == os.path.normcase(WT), rhizome.__file__
from rhizome import retrieve as R            # noqa: E402
from rhizome.parse_python import iter_python_files  # noqa: E402
sys.path.insert(1, os.path.join(REPO, "bench"))
import run_swebench as rs                    # noqa: E402  (harness helpers; rhizome already imported from WT)
import run_locbench as lb                    # noqa: E402

RUN = os.path.join(REPO, "bench", "runs", "locbench-v01")
OUT = os.path.join(HERE, "data")
V = "B"
SHORT_TMP = "C:\\rzb"                         # Windows path limit (prowler), as in the main run
LONG_PATH_REPOS = {"prowler-cloud/prowler"}
TOPN = 100
N_RANDOM_PAIRS = 10                           # anchored random pairs per found gold file (section G)

CSV_FIELDS = {
    "instances": ["instance_id", "repo", "category", "rhizome_category", "n_gold", "n_candidates", "query_tokens",
                  "verified", "mismatches", "bundle_files", "graph_edges",
                  "v01_entries", "v02_top_score", "v02_threshold", "v02_entries_cat", "v02_entries_bug",
                  "v02_band_cat", "v02_band_bug", "v02_band_all_hits", "ppr_candidates_cat", "ppr_hub_mass_cat",
                  "ppr_hub_mass_bug", "hub_fanin_cutoff", "seconds"],
    "components": ["instance_id", "component", "rank", "path", "gold", "score", "extra1", "extra2", "reason",
                   "fan_in", "fan_out", "is_init", "same_dir_gold", "parser", "is_test"],
    "gold": ["instance_id", "path", "n_gold", "category", "fan_in", "fan_out", "is_init", "parser", "in_bundle",
             "is_test", "rank_bm25", "rank_search_v01", "rank_search_v02", "rank_ctxcat_v01", "rank_ctxcat_v02",
             "rank_ctxbug_v02", "rank_fusion_v02", "rank_fusion_search_v02", "rank_bm25graph",
             "entry_v01_cat", "entry_v02_cat", "in_band_v02_cat", "ppr_rank_v02_cat", "ppr_candidates_v02_cat",
             "ppr_mass_v02_cat", "ppr_used_v02_cat", "walk_dist_v01_cat", "bm25graph_walk_dist",
             "reason_v02_cat", "reason_v01_cat",
             "dist_entry_und", "dist_entry_dep", "dist_entry_caller", "dist_found_und", "dist_found_dep",
             "dist_found_caller", "degree_und"],
    "fields": ["instance_id", "path", "gold", "rank_bm25", "rank_search_v02", "score_v02", "name", "doc", "body"],
    "pairs": ["instance_id", "repo", "kind", "src", "dst", "same_dir", "same_pkg", "import_edge", "name_ref",
              "call_ref", "shared_test", "dist_und"],
}


# ------------------------------------------------------------------ helpers

def ranks_of(ranking):
    return {p: i + 1 for i, p in enumerate(ranking)}


def bm25_scored(query, cands, toks):
    """Same formula and tie-break as run_swebench.bm25_rank, with scores."""
    n = len(cands)
    dl = {c: sum(toks[c].values()) for c in cands}
    avgdl = (sum(dl.values()) / n) if n else 1.0
    df = Counter()
    for c in cands:
        df.update(toks[c].keys())
    q = R.tokens(query)
    scores = {}
    for c in cands:
        tf, s = toks[c], 0.0
        for t in q:
            f = tf.get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (rs.BM25_K1 + 1) / (f + rs.BM25_K1 * (1 - rs.BM25_B + rs.BM25_B * dl[c] / (avgdl or 1.0)))
        scores[c] = s
    order = {c: i for i, c in enumerate(cands)}
    return sorted(cands, key=lambda c: (-scores[c], order[c])), scores


def gather_boost(category, drop_tests):
    """The boost gather() passes to Bundle.search (copied from the tag's gather)."""
    boost = None
    if category == "security":
        boost = lambda c: 1.0 + 0.6 * bool(R._security_tags(c)) + 0.4 * ("area:auth" in (c.fm.get("tags") or []))
    if drop_tests:
        base = boost or (lambda c: 1.0)
        boost = lambda c, _b=base: 0.0 if R._is_test(c) else _b(c)
    return boost


def component_of(reason: str) -> str:
    r = reason or ""
    if r.startswith("entry point") or r.startswith("implements requirement"):
        return "entry"
    if r.startswith("strong text match"):
        return "band"
    if r.startswith("graph neighbour"):
        return "ppr"
    if r.startswith("dependency at distance"):
        return "walk-dep"
    if r.startswith("caller at distance") or r.startswith("blast radius"):
        return "walk-caller"
    if r.startswith("dependency of"):
        return "walk-dep"
    if r.startswith("central member"):
        return "extra-subsystem"
    if r.startswith("test exercising"):
        return "extra-test"
    if r.startswith("security-flagged"):
        return "extra-security"
    return "other"


def bfs(starts, nbrs, limit=None):
    dist = {s: 0 for s in starts}
    dq = deque(starts)
    while dq:
        u = dq.popleft()
        if limit is not None and dist[u] >= limit:
            continue
        for v in nbrs.get(u, ()):
            if v not in dist:
                dist[v] = dist[u] + 1
                dq.append(v)
    return dist


def defined_names(text):
    """Top-level classes/functions and methods defined in a file (ast; empty if it does not parse)."""
    try:
        tree = ast.parse(text)
    except Exception:
        return set()
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
            if isinstance(node, ast.ClassDef):
                out.update(n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return {n for n in out if len(n) >= 4 and not (n.startswith("__") and n.endswith("__"))}


def called_names(text):
    try:
        tree = ast.parse(text)
    except Exception:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


# ------------------------------------------------------------------ one instance

def trace(inst, saved, writers, rng_seed):
    t0 = time.perf_counter()
    iid = inst["instance_id"]
    gold = saved["gold"]
    gset = set(gold)
    gold_dirs = {g.rsplit("/", 1)[0] if "/" in g else "" for g in gold}
    tmp_root = SHORT_TMP if inst["repo"] in LONG_PATH_REPOS else None
    if tmp_root:
        os.makedirs(tmp_root, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rza_", dir=tmp_root)
    try:
        snap, bdir = os.path.join(tmp, "s"), os.path.join(tmp, "b")
        os.makedirs(snap)
        rs.materialise(rs.ensure_repo(inst["repo"]), inst["base_commit"], snap)
        key = f"{inst['repo'].replace('/', '__')}__{inst['base_commit'][:12]}__{rs.CODE_TAG}"
        with zipfile.ZipFile(os.path.join(rs.BUNDLES, key + ".zip")) as zf:   # never re-scan: cached bundle only
            zf.extractall(bdir)
        bundle = R.Bundle(bdir, repo=snap)
        path_of = {r: str(c.fm.get("title")) for r, c in bundle.files.items()}
        rel_of = {p: r for r, p in path_of.items()}
        fm = {path_of[r]: c.fm for r, c in bundle.files.items()}
        is_test = {p: "test" in (f.get("tags") or []) for p, f in fm.items()}
        all_cands = list(iter_python_files(snap))
        cands = [p for p in all_cands if not is_test.get(p, False)]
        cset = set(cands)
        toks, texts = {}, {}
        for p in all_cands:
            with open(os.path.join(snap, *p.split("/")), encoding="utf-8", errors="replace") as fh:
                texts[p] = fh.read()
            toks[p] = Counter(R.tokens(texts[p]))
        query = inst["problem_statement"]
        cat = lb.CATEGORY[inst["category"]]

        def attrs(p):
            f = fm.get(p, {})
            return {"fan_in": f.get("fan_in", ""), "fan_out": f.get("fan_out", ""),
                    "is_init": int(p.endswith("__init__.py")),
                    "same_dir_gold": int((p.rsplit("/", 1)[0] if "/" in p else "") in gold_dirs),
                    "parser": f.get("parser", ""), "is_test": int(is_test.get(p, False))}

        def emit(component, rows):
            for i, (p, score, e1, e2, reason) in enumerate(rows, 1):
                writers["components"].writerow({"instance_id": iid, "component": component, "rank": i, "path": p,
                                                "gold": int(p in gset), "score": score, "extra1": e1, "extra2": e2,
                                                "reason": reason, **attrs(p)})

        # ---- rankings, exactly as run_locbench builds them
        bm, bm_score = bm25_scored(query, cands, toks)
        assert bm == rs.bm25_rank(query, cands, toks)
        rk = {"file-bm25": bm}
        r = sorted(cands)
        random.Random(rs.SEED).shuffle(r)
        rk["random"] = r
        entries_g = [rel_of[p] for p in bm[:lb.BM25_GRAPH_ENTRIES] if p in rel_of]
        g_dist = bundle.bfs(entries_g, bundle.deps, 2)
        walk = [path_of[x] for x, d in g_dist.items() if d and x in path_of]
        rk["bm25-graph"], _ = rs.complete(bm[:lb.BM25_GRAPH_ENTRIES] + walk, cset, bm)
        search_scores, items_by = {}, {}
        for c, cfg in lb.CONFIGS.items():
            hits = bundle.search(query, k=len(bundle.files), types=("Source File",), config=cfg)
            search_scores[c] = {path_of[h]: s for h, s in hits}
            rk[f"rhizome-search [{c}]"], _ = rs.complete([path_of[h] for h, _ in hits], cset, bm)
            for name, gcat in (("rhizome-ctx-cat", cat), ("rhizome-ctx-bug", "bug")):
                e, items, subs = R.gather(bundle, query, gcat, include_tests=False, config=cfg)
                items_by[(name, c)] = (e, items)
                rk[f"{name} [{c}]"], _ = rs.complete([path_of[i.rel] for i in items if i.rel in path_of], cset, bm)
            rk[f"fusion-rrf [{c}]"] = rs.rrf(bm, rk[f"rhizome-ctx-cat [{c}]"])
            rk[f"fusion-rrf-search [{c}]"] = rs.rrf(bm, rk[f"rhizome-search [{c}]"])
        sv = saved["variants"][V]["methods"]
        mism = [m for m in lb.METHODS if rk[m][:TOPN] != sv[m]["top"][:TOPN]]
        R_ = {m: ranks_of(rk[m]) for m in lb.METHODS}

        # ---- component outputs
        emit("file-bm25", [(p, round(bm_score[p], 6), "", "", "") for p in bm[:TOPN]])
        for c in lb.CONFIGS:
            order = [p for p in sorted(search_scores[c], key=lambda p: -search_scores[c][p]) if p in cset]
            emit(f"search-{c}", [(p, round(search_scores[c][p], 6), "", "", "") for p in order[:TOPN]])
            for name in ("rhizome-ctx-cat", "rhizome-ctx-bug"):
                e, items = items_by[(name, c)]
                emit(f"items-{name}-{c}", [(path_of[i.rel], round(i.score, 4), component_of(i.reason),
                                            int(i.rel in e), i.reason) for i in items if i.rel in path_of])
        emit("bm25-graph-walk", [(path_of[x], "", d, int(x in entries_g), "entry" if d == 0 else f"dependency at distance {d}")
                                 for x, d in g_dist.items() if x in path_of])

        # ---- v0.2 internals: threshold, band, full PPR list (recomputed like gather; checked against items)
        cfg2 = lb.CONFIGS["v0.2"]
        internals = {}
        for name, gcat in (("rhizome-ctx-cat", cat), ("rhizome-ctx-bug", "bug")):
            hits = bundle.search(query, k=len(bundle.searchable), boost=gather_boost(gcat, True), config=cfg2)
            top = hits[0][1] if hits else 0.0
            band = [(rr, s) for rr, s in hits if rr in bundle.files and s >= R.ENTRY_RATIO * top]
            e, items = items_by[(name, "v0.2")]
            text = {rr: s / top for rr, s in hits} if top > 0 else {}
            keep = lambda x: not R._is_test(bundle.concepts[x])
            fan = lambda x: int(bundle.concepts[x].fm.get("fan_in") or 0)
            pr = bundle.ppr(e, gcat, keep=keep, target_weight=lambda x: R.hub_weight(fan(x))) if e else {}
            cand = sorted(((p * (1 + text.get(x, 0.0)), x) for x, p in pr.items() if x not in e and p > 0),
                          key=lambda x: (-x[0], x[1]))
            ppr_items = {i.rel for i in items if i.reason.startswith("graph neighbour")}
            used = {x for _, x in cand[:R.MAX_EXPANSION]}
            if not ppr_items <= used:
                mism.append(f"ppr-{name}")
            internals[name] = {"top": top, "band": band, "entries": e, "pr": pr, "cand": cand, "text": text}
            emit(f"ppr-{name}-v0.2", [(path_of[x], round(sc, 8), round(pr[x], 8), round(text.get(x, 0.0), 6),
                                       "used" if x in used else "beyond-25")
                                      for sc, x in cand[:TOPN] if x in path_of])
        ic = internals["rhizome-ctx-cat"]

        # hub mass share: top 5% fan-in or __init__.py, excluding the entry points
        fans = sorted(int(f.get("fan_in") or 0) for f in fm.values())
        cutoff = fans[int(0.95 * (len(fans) - 1))] if fans else 0
        def hub_share(pr, e):
            tot = sum(v for x, v in pr.items() if x not in e)
            if tot <= 0:
                return ""
            hub = sum(v for x, v in pr.items() if x not in e and x in path_of and
                      (path_of[x].endswith("__init__.py") or int(bundle.concepts[x].fm.get("fan_in") or 0) >= max(cutoff, 1)))
            return round(hub / tot, 6)

        # ---- graph for distances (import graph over all files; tests included)
        dep = {rr: set(bundle.deps(rr)) for rr in bundle.files}
        use = defaultdict(set)
        for a, bs in dep.items():
            for b in bs:
                use[b].add(a)
        und = {rr: dep[rr] | use[rr] for rr in bundle.files}
        n_edges = sum(len(v) for v in dep.values())
        found = [g for g in gold if R_["file-bm25"].get(g, 10 ** 9) <= 10]
        e01 = items_by[("rhizome-ctx-cat", "v0.1")][0]
        e02 = ic["entries"]
        seeds = [x for x in e02]
        d_entry = {k: bfs(seeds, nb) for k, nb in (("und", und), ("dep", dep), ("caller", use))}
        found_rels = [rel_of[g] for g in found if g in rel_of]
        d_found = {k: bfs(found_rels, nb) for k, nb in (("und", und), ("dep", dep), ("caller", use))}
        pr_rank = {x: i + 1 for i, (_, x) in enumerate(ic["cand"])}
        band_set = {x for x, _ in ic["band"]}
        reason_v02 = {i.rel: i.reason for i in items_by[("rhizome-ctx-cat", "v0.2")][1]}
        reason_v01 = {i.rel: i.reason for i in items_by[("rhizome-ctx-cat", "v0.1")][1]}
        walk01 = {i.rel: int(re.search(r"distance (\d)", i.reason).group(1))
                  for i in items_by[("rhizome-ctx-cat", "v0.1")][1] if re.search(r"distance (\d)", i.reason)}
        for g in gold:
            x = rel_of.get(g)
            a = attrs(g)
            def dd(tab, k):
                return tab[k].get(x, "inf") if x else "inf"
            writers["gold"].writerow({
                "instance_id": iid, "path": g, "n_gold": len(gold), "category": inst["category"],
                "fan_in": a["fan_in"], "fan_out": a["fan_out"], "is_init": a["is_init"], "parser": a["parser"],
                "in_bundle": int(x is not None), "is_test": a["is_test"],
                "rank_bm25": R_["file-bm25"].get(g, ""), "rank_search_v01": R_["rhizome-search [v0.1]"].get(g, ""),
                "rank_search_v02": R_["rhizome-search [v0.2]"].get(g, ""),
                "rank_ctxcat_v01": R_["rhizome-ctx-cat [v0.1]"].get(g, ""),
                "rank_ctxcat_v02": R_["rhizome-ctx-cat [v0.2]"].get(g, ""),
                "rank_ctxbug_v02": R_["rhizome-ctx-bug [v0.2]"].get(g, ""),
                "rank_fusion_v02": R_["fusion-rrf [v0.2]"].get(g, ""),
                "rank_fusion_search_v02": R_["fusion-rrf-search [v0.2]"].get(g, ""),
                "rank_bm25graph": R_["bm25-graph"].get(g, ""),
                "entry_v01_cat": int(x in e01), "entry_v02_cat": int(x in e02), "in_band_v02_cat": int(x in band_set),
                "ppr_rank_v02_cat": pr_rank.get(x, ""), "ppr_candidates_v02_cat": len(ic["cand"]),
                "ppr_mass_v02_cat": round(ic["pr"].get(x, 0.0), 8) if x else "",
                "ppr_used_v02_cat": int(pr_rank.get(x, 10 ** 9) <= R.MAX_EXPANSION),
                "walk_dist_v01_cat": walk01.get(x, ""), "bm25graph_walk_dist": g_dist.get(x, "") if x else "",
                "reason_v02_cat": reason_v02.get(x, ""), "reason_v01_cat": reason_v01.get(x, ""),
                "dist_entry_und": dd(d_entry, "und"), "dist_entry_dep": dd(d_entry, "dep"),
                "dist_entry_caller": dd(d_entry, "caller"), "dist_found_und": dd(d_found, "und"),
                "dist_found_dep": dd(d_found, "dep"), "dist_found_caller": dd(d_found, "caller"),
                "degree_und": len(und.get(x, ())) if x else ""})

        # ---- BM25F field contributions (section H): gold files + top 10 of v0.2 search and of file-bm25
        post, idf = (bundle._build_bm25f() or bundle._bm25f) if bundle._bm25f is None else bundle._bm25f
        field_tf, avg = {}, {}
        for rr in bundle.searchable:
            c = bundle.concepts[rr]
            field_tf[rr] = {k: Counter(R.tokens(s)) for k, s in bundle._fields(c).items()}
            field_tf[rr]["body"] = bundle._body_tf(c)
        for f in R.FIELD_WEIGHTS:
            avg[f] = (sum(sum(d[f].values()) for d in field_tf.values()) / len(field_tf)) or 1.0
        qt = R.tokens(query)
        want = set(gold) | set(rk["rhizome-search [v0.2]"][:10]) | set(bm[:10])
        for p in want:
            rr = rel_of.get(p)
            if rr is None:
                continue
            ft = field_tf[rr]
            norm = {f: 1 - R.BM25_B + R.BM25_B * sum(ft[f].values()) / avg[f] for f in R.FIELD_WEIGHTS}
            contrib = defaultdict(float)
            for t in qt:
                v = post.get(t, {}).get(rr, 0.0)
                if v <= 0:
                    continue
                s_t = idf[t] * v / (R.BM25_K1 + v)
                for f in R.FIELD_WEIGHTS:
                    share = R.FIELD_WEIGHTS[f] * ft[f].get(t, 0) / norm[f] / v
                    contrib[f] += s_t * share
            writers["fields"].writerow({"instance_id": iid, "path": p, "gold": int(p in gset),
                                        "rank_bm25": R_["file-bm25"].get(p, ""),
                                        "rank_search_v02": R_["rhizome-search [v0.2]"].get(p, ""),
                                        "score_v02": round(search_scores["v0.2"].get(p, 0.0), 6),
                                        **{f: round(contrib[f], 6) for f in R.FIELD_WEIGHTS}})

        # ---- relation features (section G): found gold -> missed gold, and anchored random pairs
        if len(gold) >= 2:
            missed = [g for g in gold if g not in found]
            rng = random.Random(f"{rng_seed}:{iid}")
            pool = [p for p in cands if p not in gset]
            dn = {}
            def rel_row(kind, a, b):
                if a not in dn:
                    dn[a] = (defined_names(texts.get(a, "")), called_names(texts.get(a, "")), set(WORD.findall(texts.get(a, ""))))
                if b not in dn:
                    dn[b] = (defined_names(texts.get(b, "")), called_names(texts.get(b, "")), set(WORD.findall(texts.get(b, ""))))
                ra, rb = rel_of.get(a), rel_of.get(b)
                imp = int(bool(ra and rb and (rb in dep.get(ra, ()) or ra in dep.get(rb, ()))))
                name_ref = int(not imp and bool((dn[b][0] & dn[a][2]) or (dn[a][0] & dn[b][2])))
                call_ref = int(bool((dn[b][0] & dn[a][1]) or (dn[a][0] & dn[b][1])))
                tests_a = {u for u in use.get(ra, ()) if R._is_test(bundle.concepts[u])} if ra else set()
                tests_b = {u for u in use.get(rb, ()) if R._is_test(bundle.concepts[u])} if rb else set()
                da, db = (a.rsplit("/", 1)[0] if "/" in a else ""), (b.rsplit("/", 1)[0] if "/" in b else "")
                pa, pb = da.split("/")[:2], db.split("/")[:2]
                dist = bfs([ra], und).get(rb, "inf") if ra and rb else "inf"
                writers["pairs"].writerow({"instance_id": iid, "repo": inst["repo"], "kind": kind, "src": a, "dst": b,
                                           "same_dir": int(da == db), "same_pkg": int(pa == pb),
                                           "import_edge": imp, "name_ref": name_ref, "call_ref": call_ref,
                                           "shared_test": int(bool(tests_a & tests_b)), "dist_und": dist})
            for a in found:
                for b in missed:
                    rel_row("gold", a, b)
                for b in rng.sample(pool, min(N_RANDOM_PAIRS, len(pool))):
                    rel_row("random", a, b)
            for a in gold:                      # all ordered gold pairs, for completeness
                for b in gold:
                    if a != b and not (a in found and b in missed):
                        rel_row("gold-other", a, b)

        writers["instances"].writerow({
            "instance_id": iid, "repo": inst["repo"], "category": inst["category"], "rhizome_category": cat,
            "n_gold": len(gold), "n_candidates": len(cands), "query_tokens": len(R.tokens(query)),
            "verified": int(not mism), "mismatches": ";".join(mism), "bundle_files": len(bundle.files),
            "graph_edges": n_edges, "v01_entries": len(e01), "v02_top_score": round(ic["top"], 6),
            "v02_threshold": round(R.ENTRY_RATIO * ic["top"], 6), "v02_entries_cat": len(e02),
            "v02_entries_bug": len(internals["rhizome-ctx-bug"]["entries"]),
            "v02_band_cat": len(ic["band"]), "v02_band_bug": len(internals["rhizome-ctx-bug"]["band"]),
            "v02_band_all_hits": sum(1 for x, s in bundle.search(query, k=len(bundle.searchable), config=cfg2)
                                     if x in bundle.files and s >= R.ENTRY_RATIO * ic["top"]),
            "ppr_candidates_cat": len(ic["cand"]), "ppr_hub_mass_cat": hub_share(ic["pr"], e02),
            "ppr_hub_mass_bug": hub_share(internals["rhizome-ctx-bug"]["pr"], internals["rhizome-ctx-bug"]["entries"]),
            "hub_fanin_cutoff": cutoff, "seconds": round(time.perf_counter() - t0, 1)})
        return mism
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--instance", action="append", default=[])
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    saved = {k: r for k, r in rs.load_records(os.path.join(RUN, "per_instance.jsonl")).items() if r.get("status") == "ok"}
    proto = json.load(open(os.path.join(RUN, "protocol.json"), encoding="utf-8"))
    assert proto["code_tag"] == rs.CODE_TAG, (proto["code_tag"], rs.CODE_TAG)
    data = [x for x in lb.load_dataset() if x["instance_id"] in saved]
    if args.instance:
        data = [x for x in data if x["instance_id"] in set(args.instance)]
    if args.limit:
        data = data[: args.limit]
    done_path = os.path.join(args.out, "done.txt")
    done = set(open(done_path, encoding="utf-8").read().split()) if os.path.exists(done_path) else set()
    files, writers = {}, {}
    for name, cols in CSV_FIELDS.items():
        path = os.path.join(args.out, f"{name}.csv")
        new = not os.path.exists(path)
        files[name] = open(path, "a", newline="", encoding="utf-8")
        writers[name] = csv.DictWriter(files[name], fieldnames=cols)
        if new:
            writers[name].writeheader()
    errors = open(os.path.join(args.out, "errors.log"), "a", encoding="utf-8")
    todo = [x for x in data if x["instance_id"] not in done]
    print(f"{len(data)} instances, {len(todo)} to trace", flush=True)
    for i, inst in enumerate(todo, 1):
        t = time.perf_counter()
        try:
            mism = trace(inst, saved[inst["instance_id"]], writers, 0)
            status = "verified" if not mism else "MISMATCH " + ";".join(mism)
        except Exception as exc:
            status = f"ERROR {type(exc).__name__}: {exc}"
            errors.write(f"{inst['instance_id']}\n{traceback.format_exc()}\n")
            errors.flush()
        for f in files.values():
            f.flush()
        if not status.startswith("ERROR"):
            with open(done_path, "a", encoding="utf-8") as fh:
                fh.write(inst["instance_id"] + "\n")
        print(f"[{i}/{len(todo)}] {inst['instance_id']} {status} {time.perf_counter() - t:.1f}s", flush=True)
    for f in files.values():
        f.close()
    try:
        os.rmdir(SHORT_TMP)
    except OSError:
        pass


if __name__ == "__main__":
    main()
