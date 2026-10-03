"""EXPLORATORY, POST-HOC. Sections A-I of the Loc-Bench component analysis (variant B).

Reads bench/analysis/locbench/data/*.csv (trace.py, relations.py) and the saved run
(bench/runs/locbench-v01). Writes tables/*.csv, figures/*.png, results.json and TABLES.md.
Only instances whose traced rankings matched the saved top 100 are used. Nothing here is a benchmark result.

Usage: python bench/analysis/locbench/analyse.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict, deque

import numpy as np
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DATA, TAB, FIG = (os.path.join(HERE, d) for d in ("data", "tables", "figures"))
RUN = os.path.join(REPO, "bench", "runs", "locbench-v01")
B = 10_000
SEED = 0
CATS = ["Bug Report", "Feature Request", "Performance Issue", "Security Vulnerability"]


def read(name):
    """data/<name>.csv, or its gzip-compressed copy (components.csv is committed compressed)."""
    path = os.path.join(DATA, f"{name}.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    import gzip
    with gzip.open(path + ".gz", "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def num(x, default=None):
    if x in ("", None):
        return default
    if x == "inf":
        return math.inf
    return float(x)


# ------------------------------------------------------------------ statistics

RNG = np.random.default_rng(SEED)
_IDX_CACHE = {}


def boot_idx(n):
    if n not in _IDX_CACHE:
        _IDX_CACHE[n] = np.random.default_rng(SEED).integers(0, n, size=(B, n))
    return _IDX_CACHE[n]


def ci_ratio(num_, den):
    """Ratio of sums with a 95% instance-bootstrap CI."""
    num_, den = np.asarray(num_, float), np.asarray(den, float)
    n = len(num_)
    if n == 0 or den.sum() == 0:
        return (float("nan"),) * 3
    idx = boot_idx(n)
    d = den[idx].sum(1)
    r = np.where(d > 0, num_[idx].sum(1) / np.where(d > 0, d, 1), np.nan)
    return float(num_.sum() / den.sum()), float(np.nanpercentile(r, 2.5)), float(np.nanpercentile(r, 97.5))


def ci_lift(n1, d1, n0, d0):
    """(sum n1 / sum d1) / (sum n0 / sum d0), paired by instance, bootstrap CI."""
    arrs = [np.asarray(a, float) for a in (n1, d1, n0, d0)]
    n = len(arrs[0])
    if n == 0 or arrs[1].sum() == 0 or arrs[3].sum() == 0 or arrs[2].sum() == 0:
        return (float("nan"),) * 3
    idx = boot_idx(n)
    s = [a[idx].sum(1) for a in arrs]
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = (s[0] / s[1]) / (s[2] / s[3])
    point = (arrs[0].sum() / arrs[1].sum()) / (arrs[2].sum() / arrs[3].sum())
    lift = lift[np.isfinite(lift)]
    return float(point), float(np.percentile(lift, 2.5)), float(np.percentile(lift, 97.5))


def ci_mean(x):
    x = np.asarray(x, float)
    if len(x) == 0:
        return (float("nan"),) * 3
    m = x[boot_idx(len(x))].mean(1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def fmt_ci(t, d=2, pct=False):
    if any(isinstance(v, float) and math.isnan(v) for v in t):
        return "–"
    k = 100 if pct else 1
    return f"{t[0] * k:.{d}f} [{t[1] * k:.{d}f}, {t[2] * k:.{d}f}]"


def mcnemar(a, b):
    """Exact McNemar on paired booleans; returns (a_only, b_only, p)."""
    x = sum(1 for u, v in zip(a, b) if u and not v)
    y = sum(1 for u, v in zip(a, b) if v and not u)
    n = x + y
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(x, y) + 1)) / 2 ** n)
    return x, y, p


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def write_csv(name, header, rows):
    with open(os.path.join(TAB, f"{name}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


# ------------------------------------------------------------------ load

def load():
    inst = {r["instance_id"]: r for r in read("instances")}
    verified = {k for k, r in inst.items() if r["verified"] == "1"}
    comps = defaultdict(lambda: defaultdict(list))
    for r in read("components"):
        if r["instance_id"] in verified:
            comps[r["instance_id"]][r["component"]].append(r)
    gold = [r for r in read("gold") if r["instance_id"] in verified]
    fields = [r for r in read("fields") if r["instance_id"] in verified]
    pairs = [r for r in read("pairs") if r["instance_id"] in verified]
    co = {}
    if os.path.exists(os.path.join(DATA, "cochange.csv")):
        for r in read("cochange"):
            co[(r["instance_id"], r["kind"], r["src"], r["dst"])] = r
    saved = {}
    with open(os.path.join(RUN, "per_instance.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            saved[r["instance_id"]] = r
    ds = {}
    with open(os.path.join(REPO, "bench", ".cache", "loc_bench_v1.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            ds[r["instance_id"]] = r
    return inst, verified, comps, gold, fields, pairs, co, saved, ds


# ------------------------------------------------------------------ main

def main():
    for d in (TAB, FIG):
        os.makedirs(d, exist_ok=True)
    inst, verified, comps, gold, fields, pairs, co, saved, ds = load()
    ids = sorted(verified)
    res, md = {}, ["# Tables (generated by analyse.py; EXPLORATORY, POST-HOC)", ""]
    gold_by = defaultdict(list)
    for g in gold:
        gold_by[g["instance_id"]].append(g)
    multi = [i for i in ids if int(inst[i]["n_gold"]) >= 2]

    # ---------------- A. inventory and integrity
    a = {"instances_traced": len(inst), "verified": len(verified),
         "mismatched": {k: r["mismatches"] for k, r in inst.items() if r["verified"] != "1"},
         "categories": dict(Counter(inst[i]["category"] for i in ids)),
         "gold_files": dict(Counter(min(int(inst[i]["n_gold"]), 3) for i in ids)),
         "repos": len({inst[i]["repo"] for i in ids}),
         "gold_parser": dict(Counter(g["parser"] or "not in bundle" for g in gold)),
         "gold_tests": sum(1 for g in gold if g["is_test"] == "1"),
         "gold_not_in_bundle": sum(1 for g in gold if g["in_bundle"] == "0")}
    summ = json.load(open(os.path.join(RUN, "summary.json"), encoding="utf-8"))
    a["parse_errors_in_run"] = dict(Counter(e["parser"] for e in summ["parse_errors"]))
    res["A"] = a
    md += ["## A. Inventory and integrity", "", "```", json.dumps(a, indent=1), "```", ""]

    # ---------------- B. provenance
    def comp_rank(i, component):
        return {r["path"]: int(r["rank"]) for r in comps[i][component]}

    prov_rows, venn, venn_any = [], Counter(), Counter()
    only_graph10 = 0
    intro10 = {m: Counter() for m in ("rhizome-ctx-cat [v0.2]", "rhizome-ctx-cat [v0.1]", "bm25-graph")}
    intro20 = {m: Counter() for m in intro10}
    only_graph = 0
    for i in ids:
        sv = saved[i]["variants"]["B"]["methods"]
        bm_r = {p: k + 1 for k, p in enumerate(sv["file-bm25"]["top"])}
        s2_r = {p: k + 1 for k, p in enumerate(sv["rhizome-search [v0.2]"]["top"])}
        ppr = {r["path"]: r for r in comps[i]["ppr-rhizome-ctx-cat-v0.2"]}
        items02 = {r["path"]: r for r in comps[i]["items-rhizome-ctx-cat-v0.2"]}
        items01 = {r["path"]: r for r in comps[i]["items-rhizome-ctx-cat-v0.1"]}
        walkg = {r["path"]: r for r in comps[i]["bm25-graph-walk"]}
        # each graph component's own top 10: PPR ranks 1-10, the first 10 v0.1 walk/extra items, the first 10
        # bm25-graph walk items (BFS order); "any depth" = anywhere in those lists (PPR: the 25 used)
        walk01_order = [r["path"] for r in comps[i]["items-rhizome-ctx-cat-v0.1"] if r["extra1"].startswith(("walk", "extra"))]
        walkg_order = [r["path"] for r in comps[i]["bm25-graph-walk"] if r["extra1"] not in ("0", "")]
        graph10 = {p for p, r in ppr.items() if int(r["rank"]) <= 10} | set(walk01_order[:10]) | set(walkg_order[:10])
        graph_any = {p for p, r in ppr.items() if r["reason"] == "used"} | set(walk01_order) | set(walkg_order)
        for g in gold_by[i]:
            p = g["path"]
            in_bm10, in_s10 = bm_r.get(p, 999) <= 10, s2_r.get(p, 999) <= 10
            venn[(in_bm10, in_s10, p in graph10)] += 1
            venn_any[(in_bm10, in_s10, p in graph_any)] += 1
            if p not in bm_r and p in graph_any:
                only_graph += 1
            if p not in bm_r and p in graph10:
                only_graph10 += 1
            for m, items, final_top in (("rhizome-ctx-cat [v0.2]", items02, sv["rhizome-ctx-cat [v0.2]"]["top"]),
                                        ("rhizome-ctx-cat [v0.1]", items01, sv["rhizome-ctx-cat [v0.1]"]["top"]),
                                        ("bm25-graph", None, sv["bm25-graph"]["top"])):
                rank = final_top.index(p) + 1 if p in final_top else 999
                if items is not None:
                    src = items[p]["extra1"] if p in items else "bm25-fallback"
                else:
                    src = ("bm25-top4" if bm_r.get(p, 999) <= 4 else
                           "walk" if p in walkg and walkg[p]["extra1"] not in ("0", "") else "bm25-fallback")
                if rank <= 10:
                    intro10[m][src] += 1
                if rank <= 20:
                    intro20[m][src] += 1
            prov_rows.append([i, p, bm_r.get(p, ""), s2_r.get(p, ""), g["ppr_rank_v02_cat"], g["walk_dist_v01_cat"],
                              g["entry_v02_cat"], g["entry_v01_cat"], g["reason_v02_cat"]])
    write_csv("B_provenance", ["instance_id", "gold", "rank_bm25", "rank_search_v02", "ppr_rank_v02", "walk_dist_v01",
                               "entry_v02", "entry_v01", "reason_v02"], prov_rows)
    labels = {(1, 0, 0): "BM25 only", (0, 1, 0): "search v0.2 only", (0, 0, 1): "graph only",
              (1, 1, 0): "BM25 + search", (1, 0, 1): "BM25 + graph", (0, 1, 1): "search + graph",
              (1, 1, 1): "all three", (0, 0, 0): "none"}
    venn_rows = [[labels[tuple(int(x) for x in k)], v, venn_any.get(k, 0)] for k, v in
                 sorted(venn.items(), key=lambda x: -x[1])]
    venn_rows += [[labels[tuple(int(x) for x in k)], 0, v] for k, v in venn_any.items() if k not in venn]
    res["B"] = {"n_gold": len(gold), "venn": {r[0]: {"graph top 10": r[1], "graph any depth": r[2]} for r in venn_rows},
                "gold_only_by_graph_not_in_bm25_top100": {"graph any depth": only_graph, "graph top 10": only_graph10},
                "introduced_top10": {m: dict(c) for m, c in intro10.items()},
                "introduced_top20": {m: dict(c) for m, c in intro20.items()}}
    md += ["## B. Provenance", "",
           "Gold files by which component has them: BM25 and search v0.2 = in their top 10; graph = in the top 10 "
           "of a graph component's own list (PPR ranks 1-10 of v0.2 ctx-cat, the first 10 v0.1 ctx-cat walk/extra "
           "items, the first 10 bm25-graph walk items), or at any depth of those lists (PPR: the 25 used). "
           f"n = {len(gold)} gold files.", "",
           md_table(["Found by", "Gold files (graph top 10)", "Gold files (graph any depth)"], venn_rows), "",
           f"Gold files absent from File-BM25's top 100 but in a graph list: {only_graph10} (graph top 10), "
           f"{only_graph} (any depth).", "",
           "Component that placed each gold file in the final top 10 / top 20:", ""]
    for m in intro10:
        md.append(f"- `{m}` top 10: {dict(intro10[m])}; top 20: {dict(intro20[m])}")
    md.append("")

    # ---------------- C. signal vs noise
    def lists_for(i):
        """(name, candidate paths in order, baseline paths) per component; tests removed."""
        sv = saved[i]["variants"]["B"]["methods"]
        bm = sv["file-bm25"]["top"]
        out = []
        ppr = [r["path"] for r in comps[i]["ppr-rhizome-ctx-cat-v0.2"] if r["is_test"] == "0"]
        for d in (5, 10, 25):
            out.append((f"PPR v0.2 top {d}", ppr[:d], bm[10:10 + len(ppr[:d])]))
        pprn = [p for p in ppr[:25] if p not in bm[:10]]
        out.append(("PPR v0.2 top 25, new vs BM25 top 10", pprn, bm[10:10 + len(pprn)]))
        w01 = [r["path"] for r in comps[i]["items-rhizome-ctx-cat-v0.1"]
               if r["extra1"].startswith(("walk", "extra")) and r["is_test"] == "0"]
        out.append(("v0.1 walk + extras (ctx-cat)", w01, bm[10:10 + len(w01)]))
        wg = [r["path"] for r in comps[i]["bm25-graph-walk"] if r["extra1"] not in ("0", "") and r["is_test"] == "0"]
        out.append(("bm25-graph walk", wg, bm[4:4 + len(wg)]))
        return out

    groups = {"all": ids, "1 gold": [i for i in ids if i not in set(multi)], "2+ gold": multi}
    for c in CATS:
        groups[c] = [i for i in ids if inst[i]["category"] == c]
    c_rows, c_res = [], {}
    curve = {"ppr": np.zeros(25), "base": np.zeros(25), "rand": np.zeros(25), "n": np.zeros(25)}
    for gname, gids in groups.items():
        per = defaultdict(lambda: {"hit": [], "len": [], "bhit": [], "blen": [], "rexp": [], "recall": []})
        for i in gids:
            gset = {g["path"] for g in gold_by[i]}
            ncand = int(inst[i]["n_candidates"])
            entries = {r["path"] for r in comps[i]["items-rhizome-ctx-cat-v0.2"] if r["extra2"] == "1"}
            for name, lst, base in lists_for(i):
                h = sum(p in gset for p in lst)
                per[name]["hit"].append(h)
                per[name]["len"].append(len(lst))
                per[name]["bhit"].append(sum(p in gset for p in base))
                per[name]["blen"].append(len(base))
                avail = len(gset - entries)
                per[name]["rexp"].append(len(lst) * avail / max(1, ncand - len(entries)))
                per[name]["recall"].append(h / len(gset))
            if gname == "all":
                ppr = [r["path"] for r in comps[i]["ppr-rhizome-ctx-cat-v0.2"] if r["is_test"] == "0"][:25]
                bm = saved[i]["variants"]["B"]["methods"]["file-bm25"]["top"]
                for d in range(1, len(ppr) + 1):
                    curve["ppr"][d - 1] += sum(p in gset for p in ppr[:d])
                    curve["base"][d - 1] += sum(p in gset for p in bm[10:10 + d])
                    curve["rand"][d - 1] += d * len(gset - entries) / max(1, ncand - len(entries))
                    curve["n"][d - 1] += d
        for name, v in per.items():
            prec = ci_ratio(v["hit"], v["len"])
            bprec = ci_ratio(v["bhit"], v["blen"])
            lift_b = ci_lift(v["hit"], v["len"], v["bhit"], v["blen"])
            lift_r = ci_lift(v["hit"], v["len"], v["rexp"], v["len"])
            c_rows.append([gname, name, len(v["hit"]), int(sum(v["len"])), int(sum(v["hit"])), fmt_ci(prec, 1, True),
                           fmt_ci(bprec, 1, True), fmt_ci(lift_b, 2), fmt_ci(lift_r, 2),
                           f"{100 * np.mean(v['recall']):.1f}"])
            c_res[f"{gname} | {name}"] = {"n": len(v["hit"]), "precision": prec, "baseline_precision": bprec,
                                          "lift_vs_displaced": lift_b, "lift_vs_random": lift_r}
    hdr = ["Group", "Component list", "Instances", "Files", "Gold hits", "Precision % [95% CI]",
           "Displaced BM25 ranks precision %", "Lift vs displaced", "Lift vs random", "Mean recall %"]
    write_csv("C_signal_vs_noise", hdr, c_rows)
    res["C"] = c_res
    md += ["## C. Signal vs noise", "",
           "Baseline 'displaced' = File-BM25 ranks 11.. of the same count (for bm25-graph: ranks 5.., which its walk "
           "displaces). Random = expected gold for the same number of files drawn from the candidates (entry points "
           "excluded). Lift = precision ratio; 95% CI from 10,000 instance-bootstrap resamples (seed 0).", "",
           md_table(hdr, c_rows), ""]
    fig, ax = plt.subplots(figsize=(6.5, 4))
    d = np.arange(1, 26)
    ok = curve["n"] > 0
    ax.plot(d[ok], 100 * curve["ppr"][ok] / curve["n"][ok], label="PPR v0.2 top d (ctx-cat)")
    ax.plot(d[ok], 100 * curve["base"][ok] / curve["n"][ok], label="File-BM25 ranks 11..10+d")
    ax.plot(d[ok], 100 * curve["rand"][ok] / curve["n"][ok], "--", label="random files (expected)")
    ax.set_xlabel("depth d")
    ax.set_ylabel("gold density (%)")
    ax.set_title("Precision vs depth (all instances; exploratory)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "C_precision_vs_depth.png"), dpi=150)
    plt.close(fig)

    # ---------------- D. oracle union
    d_rows = []
    rec = defaultdict(list)
    missed_in_ppr = [0, 0]
    for i in ids:
        gset = {g["path"] for g in gold_by[i]}
        bm = saved[i]["variants"]["B"]["methods"]["file-bm25"]["top"]
        ppr = {r["path"] for r in comps[i]["ppr-rhizome-ctx-cat-v0.2"] if r["reason"] == "used"}
        for k, pool_bm in ((10, 10), (20, 20)):
            u = (set(bm[:pool_bm]) | ppr) & gset
            same = set(bm[:pool_bm + 25]) & gset
            rec[f"bm25@{k}"].append(len(set(bm[:k]) & gset) / len(gset))
            rec[f"oracle BM25 top{pool_bm} + PPR25 @{k}"].append(min(k, len(u)) / len(gset))
            rec[f"oracle BM25 top{pool_bm + 25} @{k}"].append(min(k, len(same)) / len(gset))
        if len(gset) >= 2:
            for g in gset - set(bm[:20]):
                missed_in_ppr[1] += 1
                missed_in_ppr[0] += g in ppr
    for k, v in rec.items():
        d_rows.append([k, len(v), fmt_ci(ci_mean(v), 1, True)])
    write_csv("D_oracle", ["Pool", "Instances", "Recall % [95% CI]"], d_rows)
    res["D"] = {k: ci_mean(v) for k, v in rec.items()}
    res["D"]["2plus_missed_by_bm25_top20_in_ppr25"] = missed_in_ppr
    md += ["## D. Oracle union (upper bound)", "",
           "Recall if one could pick perfectly from the pool; compares BM25 top k + PPR 25 with BM25 extended by the "
           "same 25 slots.", "", md_table(["Pool", "Instances", "Recall % [95% CI]"], d_rows), "",
           f"2+-gold instances: gold files missed by BM25's top 20 that are in PPR's top 25: "
           f"{missed_in_ppr[0]} of {missed_in_ppr[1]}.", ""]

    # ---------------- E. failure modes (2+-gold, gold missed by BM25 top 10)
    e_rows, modes, by_cat, by_repo = [], Counter(), defaultdict(Counter), defaultdict(Counter)
    outranked_detail = []
    for i in multi:
        gs = gold_by[i]
        any_entry = any(g["entry_v02_cat"] == "1" for g in gs)
        cutoff = int(float(inst[i]["hub_fanin_cutoff"] or 0))
        ppr_list = comps[i]["ppr-rhizome-ctx-cat-v0.2"]
        for g in gs:
            if num(g["rank_bm25"], 999) <= 10:
                continue
            final = num(g["rank_ctxcat_v02"], 999)
            du = num(g["dist_entry_und"], math.inf)
            pr = num(g["ppr_rank_v02_cat"], None)
            if final <= 10:
                mode = "0 recovered by ctx-cat v0.2"
            elif not any_entry:
                mode = "1 bad seeds"
            elif du > 3 or g["degree_und"] in ("0", "") or g["parser"] == "failed":
                mode = "2 unreachable"
            elif pr is None or pr > 25:
                mode = "3 reachable, outranked"
                above = [r for r in ppr_list if pr is None or int(r["rank"]) < pr]
                hubs = sum(1 for r in above if r["is_init"] == "1" or int(r["fan_in"] or 0) >= max(cutoff, 1))
                outranked_detail.append([i, g["path"], pr if pr else "not reached", g["ppr_candidates_v02_cat"],
                                         len(above), hubs])
            elif pr <= 25:
                mode = "4 crowded out"
            else:
                mode = "5 other"
            modes[mode] += 1
            by_cat[inst[i]["category"]][mode] += 1
            by_repo[inst[i]["repo"]][mode] += 1
            e_rows.append([i, g["path"], inst[i]["category"], mode, g["rank_bm25"], g["rank_ctxcat_v02"],
                           g["ppr_rank_v02_cat"], g["dist_entry_und"], inst[i]["v02_band_cat"]])
    write_csv("E_failure_modes", ["instance_id", "gold", "category", "mode", "rank_bm25", "rank_ctxcat_v02",
                                  "ppr_rank", "dist_entry_und", "band_size"], e_rows)
    write_csv("E_outranked_detail", ["instance_id", "gold", "ppr_rank", "ppr_candidates", "files_above_recorded",
                                     "hubs_above"], outranked_detail)
    tot = sum(modes.values())
    mode_names = sorted(modes)
    res["E"] = {"total_missed": tot, "modes": dict(modes), "by_category": {c: dict(v) for c, v in by_cat.items()},
                "by_repo": {r: dict(v) for r, v in by_repo.items()}}
    band = [int(inst[i]["v02_band_cat"]) for i in ids]
    qlen = [int(inst[i]["query_tokens"]) for i in ids]
    rho = stats.spearmanr(qlen, band)
    res["E"]["band_size"] = {"median": float(np.median(band)), "p90": float(np.percentile(band, 90)),
                             "max": max(band), "share_band_gt_4": float(np.mean([b > 4 for b in band]))}
    res["E"]["query_tokens_vs_band_spearman"] = (float(rho.statistic), float(rho.pvalue), len(band))
    md += ["## E. Failure modes (2+-gold instances, gold files missed by File-BM25's top 10)", "",
           md_table(["Mode", "Gold files", "%"], [[m, modes[m], f"{100 * modes[m] / tot:.1f}"] for m in mode_names]), "",
           "By category:", "",
           md_table(["Category"] + mode_names, [[c] + [by_cat[c][m] for m in mode_names] for c in CATS if c in by_cat]), "",
           "By repository:", "",
           md_table(["Repository"] + mode_names, [[r] + [by_repo[r][m] for m in mode_names] for r in sorted(by_repo)]), "",
           f"Strong-match band size (v0.2 ctx-cat, all {len(band)} instances): median {np.median(band):.0f}, "
           f"90th percentile {np.percentile(band, 90):.0f}, max {max(band)}; share with more than 4 strong matches "
           f"{100 * np.mean([b > 4 for b in band]):.1f}%. Spearman rho(query tokens, band size) = "
           f"{rho.statistic:.3f} (p = {rho.pvalue:.3g}, n = {len(band)}).", ""]
    fig, ax = plt.subplots(figsize=(7, 4))
    bottom = np.zeros(len(CATS))
    for m in mode_names:
        vals = np.array([by_cat[c][m] for c in CATS], float)
        ax.bar(range(len(CATS)), vals, bottom=bottom, label=m)
        bottom += vals
    ax.set_xticks(range(len(CATS)), [c.replace(" ", "\n") for c in CATS])
    ax.set_ylabel("missed gold files")
    ax.set_title("Failure modes by category (2+-gold; exploratory)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "E_failure_modes.png"), dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.hist(band, bins=range(0, min(max(band), 60) + 2), color="tab:blue")
    ax.set_xlabel("strong-match band size (files >= 50% of top score)")
    ax.set_ylabel("instances")
    ax.set_title(f"Strong-match band sizes (n = {len(band)}; exploratory)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "E_band_sizes.png"), dpi=150)
    plt.close(fig)

    # ---------------- F. distances
    def bucket(v):
        v = num(v, math.inf)
        return "unreachable" if v == math.inf else ("3+" if v >= 3 else str(int(v)))
    missed = [g for g in gold if g["instance_id"] in set(multi) and num(g["rank_bm25"], 999) > 10]
    f_tab = {}
    for key in ("dist_entry_und", "dist_entry_dep", "dist_entry_caller", "dist_found_und", "dist_found_dep",
                "dist_found_caller"):
        f_tab[key] = Counter(bucket(g[key]) for g in missed)
    order = ["0", "1", "2", "3+", "unreachable"]
    f_rows = [[k] + [f_tab[k].get(b, 0) for b in order] for k in f_tab]
    deg_gold = [num(g["fan_in"], 0) + num(g["fan_out"], 0) for g in gold if g["in_bundle"] == "1"]
    deg_nb = [num(r["fan_in"], 0) + num(r["fan_out"], 0) for i in ids for r in comps[i]["ppr-rhizome-ctx-cat-v0.2"]
              if r["reason"] == "used" and r["gold"] == "0"]
    mw = stats.mannwhitneyu(deg_gold, deg_nb) if deg_gold and deg_nb else None
    hub = [num(inst[i]["ppr_hub_mass_cat"]) for i in ids if inst[i]["ppr_hub_mass_cat"] != ""]
    res["F"] = {"missed_gold_2plus": len(missed), "distances": {k: dict(v) for k, v in f_tab.items()},
                "degree_gold_median": float(np.median(deg_gold)), "degree_ppr_nongold_median": float(np.median(deg_nb)),
                "mannwhitney_p": float(mw.pvalue) if mw else None, "n_gold": len(deg_gold), "n_nongold": len(deg_nb),
                "ppr_hub_mass_share": ci_mean(hub), "n_hub": len(hub)}
    md += ["## F. Graph distances", "",
           f"Missed gold files in 2+-gold instances (n = {len(missed)}): shortest distance to the nearest v0.2 entry "
           "point and to the nearest gold file File-BM25 found (undirected, dependency direction, caller direction).",
           "", md_table(["Distance from"] + order, f_rows), "",
           f"Degree (fan-in + fan-out): gold files median {np.median(deg_gold):.0f} (n = {len(deg_gold)}), non-gold "
           f"PPR candidates median {np.median(deg_nb):.0f} (n = {len(deg_nb)}); Mann-Whitney p = "
           f"{mw.pvalue:.3g}." if mw else "", "",
           f"Share of PPR mass (excluding entry points) on hub files (top 5% fan-in or `__init__.py`): "
           f"{fmt_ci(ci_mean(hub), 1, True)} % (n = {len(hub)}).", ""]
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, key, title in ((axs[0], "dist_entry_und", "to nearest entry point"),
                           (axs[1], "dist_found_und", "to nearest found gold file")):
        ax.bar(order, [f_tab[key].get(b, 0) for b in order])
        ax.set_title(title)
        ax.set_xlabel("undirected import-graph distance")
    axs[0].set_ylabel("missed gold files (2+-gold)")
    fig.suptitle("Distances of missed gold files (exploratory)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "F_distances.png"), dpi=150)
    plt.close(fig)

    # ---------------- G. relations
    rels = ["import_edge", "same_dir", "same_pkg", "name_ref", "call_ref", "shared_test", "dist<=2", "co_change>=1",
            "co_change>=2"]
    def has(p, rel):
        if rel == "dist<=2":
            return num(p["dist_und"], math.inf) <= 2
        if rel.startswith("co_change"):
            c = co.get((p["instance_id"], p["kind"], p["src"], p["dst"]))
            return c is not None and int(c["co_commits"]) >= int(rel[-1])
        return p[rel] == "1"
    per_inst = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))   # rel -> inst -> [gold_hit, gold_n, rnd_hit, rnd_n]
    missed_conn = defaultdict(lambda: defaultdict(set))
    missed_all = defaultdict(set)
    for p in pairs:
        if p["kind"] == "gold":
            missed_all[p["instance_id"]].add(p["dst"])
        for rel in rels:
            if rel.startswith("co_change") and not co:
                continue
            h = has(p, rel)
            cell = per_inst[rel][p["instance_id"]]
            if p["kind"] == "gold":
                cell[0] += h
                cell[1] += 1
                if h:
                    missed_conn[rel][p["instance_id"]].add(p["dst"])
            elif p["kind"] == "random":
                cell[2] += h
                cell[3] += 1
    g_rows, g_res = [], {}
    n_missed = sum(len(v) for v in missed_all.values())
    for rel in rels:
        cells = [c for c in per_inst[rel].values() if c[1] and c[3]]
        if not cells:
            continue
        gh, gn, rh, rn = (np.array([c[k] for c in cells]) for k in range(4))
        lift = ci_lift(gh, gn, rh, rn)
        conn = sum(len(v) for v in missed_conn[rel].values())
        g_rows.append([rel, len(cells), f"{100 * gh.sum() / gn.sum():.1f}", f"{100 * rh.sum() / rn.sum():.1f}",
                       fmt_ci(lift, 2), f"{conn} / {n_missed}"])
        g_res[rel] = {"gold_rate": float(gh.sum() / gn.sum()), "random_rate": float(rh.sum() / rn.sum()),
                      "lift": lift, "missed_connected": conn, "missed_total": n_missed, "instances": len(cells)}
    hdr = ["Relation", "Instances", "Gold pairs %", "Random pairs %", "Lift [95% CI]", "Missed gold connected"]
    write_csv("G_relations", hdr, g_rows)
    res["G"] = g_res
    md += ["## G. Other link types (found gold -> missed gold vs found gold -> random non-gold file)", "",
           "Anchored random baseline: 10 random non-gold candidate files per found gold file, same instance.", "",
           md_table(hdr, g_rows), ""]
    if g_rows:
        fig, ax = plt.subplots(figsize=(7, 4))
        names = [r[0] for r in g_rows]
        pts = [g_res[n]["lift"] for n in names]
        y = np.arange(len(names))
        ax.errorbar([p[0] for p in pts], y, xerr=[[p[0] - p[1] for p in pts], [p[2] - p[0] for p in pts]], fmt="o")
        ax.axvline(1, color="grey", ls="--")
        ax.set_yticks(y, names)
        ax.set_xscale("log")
        ax.set_xlabel("lift over random pairs (log scale, 95% CI)")
        ax.set_title("Relations linking found -> missed gold files (exploratory)")
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "G_relation_lift.png"), dpi=150)
        plt.close(fig)

    # ---------------- H. search v0.2 vs File-BM25
    fl = {(r["instance_id"], r["path"]): r for r in fields}
    h_rows, h_res = [], {}
    name_share = {"v0.2 better": [], "v0.2 worse": []}
    rb, rs2 = [], []
    for g in gold:
        b_, s_ = num(g["rank_bm25"], 1000), num(g["rank_search_v02"], 1000)
        rb.append(b_)
        rs2.append(s_)
        for k in (5, 10):
            if (b_ <= k) != (s_ <= k):
                kind = "v0.2 better" if s_ <= k else "v0.2 worse"
                f = fl.get((g["instance_id"], g["path"]))
                parts = [num(f[x], 0) for x in ("name", "doc", "body")] if f else [0, 0, 0]
                tot_ = sum(parts) or 1
                if k == 10:
                    name_share[kind].append(parts[0] / tot_)
                h_rows.append([g["instance_id"], g["path"], k, kind, int(b_), int(s_)] +
                              [f"{x / tot_:.2f}" for x in parts])
    write_csv("H_disagreements", ["instance_id", "gold", "k", "direction", "rank_bm25", "rank_search_v02",
                                  "name_share", "doc_share", "body_share"], h_rows)
    wil = stats.wilcoxon(rb, rs2)
    h_res = {"disagreements": Counter((r[2], r[3]) for r in h_rows),
             "name_share_mean": {k: ci_mean(v) for k, v in name_share.items()},
             "wilcoxon_rank_bm25_vs_search_v02": (float(wil.statistic), float(wil.pvalue), len(rb)),
             "median_rank_bm25": float(np.median(rb)), "median_rank_search_v02": float(np.median(rs2))}
    res["H"] = {"disagreements": {f"top{k} {d}": v for (k, d), v in h_res["disagreements"].items()},
                "name_share_mean": h_res["name_share_mean"], "wilcoxon": h_res["wilcoxon_rank_bm25_vs_search_v02"],
                "median_rank_bm25": h_res["median_rank_bm25"], "median_rank_search_v02": h_res["median_rank_search_v02"]}
    md += ["## H. Where rhizome-search v0.2 and File-BM25 disagree", "",
           md_table(["k", "Direction", "Gold files"], [[k, d, v] for (k, d), v in sorted(h_res["disagreements"].items())]),
           "", "Share of the gold file's BM25F score from the name field (path + symbol names), top-10 disagreements: "
           + "; ".join(f"{k}: {fmt_ci(v, 2)} (n = {len(name_share[k])})" for k, v in h_res["name_share_mean"].items()),
           "", f"Gold-file ranks, File-BM25 vs search v0.2 (Wilcoxon signed-rank): statistic {wil.statistic:.0f}, "
           f"p = {wil.pvalue:.3g}, n = {len(rb)}; medians {np.median(rb):.0f} vs {np.median(rs2):.0f}.", ""]

    # ---------------- I. case studies (selection only; narratives written in ANALYSIS.md)
    added, pushed, unreach = [], [], []
    for i in ids:
        sv = saved[i]["variants"]["B"]["methods"]
        bm10 = set(sv["file-bm25"]["top"][:10])
        for m in ("rhizome-ctx-cat [v0.2]", "bm25-graph", "rhizome-ctx-cat [v0.1]"):
            top10 = sv[m]["top"][:10]
            items = {r["path"]: r for r in comps[i]["items-rhizome-ctx-cat-v0.2" if "v0.2" in m else
                                                  "items-rhizome-ctx-cat-v0.1" if "v0.1" in m else "bm25-graph-walk"]}
            for g in gold_by[i]:
                p = g["path"]
                graph_src = p in items and ((items[p]["extra1"] in ("ppr",) or items[p]["extra1"].startswith(("walk", "extra")))
                                            if m != "bm25-graph" else items[p]["extra1"] not in ("0", ""))
                if p in top10 and p not in bm10 and graph_src:
                    added.append((i, m, p))
                graph_in_top10 = any(q in items and ((items[q]["extra1"] == "ppr") if m != "bm25-graph"
                                                     else items[q]["extra1"] not in ("0", "")) for q in top10)
                if m != "rhizome-ctx-cat [v0.1]" and p in bm10 and p not in top10 and graph_in_top10:
                    pushed.append((i, m, p))       # a graph item sits in the top 10 the gold file dropped out of
    for r in e_rows:                               # by distance, whatever the primary failure mode
        if num(r[7], math.inf) > 3:
            unreach.append((r[0], "rhizome-ctx-cat [v0.2]", r[1]))
    def pick(lst, n):
        out, repos = [], set()
        for x in sorted(lst):
            if inst[x[0]]["repo"] not in repos:
                out.append(x)
                repos.add(inst[x[0]]["repo"])
            if len(out) == n:
                break
        return out
    cases = {"added": pick(added, 4), "pushed out": pick(pushed, 4), "unreachable": pick(unreach, 2)}
    res["I"] = {"candidates": {"added": len(added), "pushed out": len(pushed), "unreachable": len(unreach)},
                "picked": cases}
    case_md = case_studies(cases, saved, ds, inst, comps, gold_by)
    with open(os.path.join(HERE, "CASES.md"), "w", encoding="utf-8") as fh:
        fh.write(case_md)

    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)
    with open(os.path.join(HERE, "TABLES.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print("wrote results.json, TABLES.md, CASES.md, tables/, figures/")


def case_studies(cases, saved, ds, inst, comps, gold_by):
    """Short factual case sheets; graph paths from the cached v0.2.0-rc1 bundle (read only)."""
    sys.path.insert(0, os.path.join(REPO, "bench", ".cache", "wt-rc1"))
    from rhizome import retrieve as R
    sys.path.insert(1, os.path.join(REPO, "bench"))
    import run_swebench as rs
    out = ["# Case studies (EXPLORATORY, POST-HOC; factual sheets for ANALYSIS.md section I)", ""]
    for kind, lst in cases.items():
        for iid, method, gpath in lst:
            r = ds[iid]
            key = f"{r['repo'].replace('/', '__')}__{r['base_commit'][:12]}__{rs.CODE_TAG}"
            tmp_root = "C:\\rzb" if r["repo"] == "prowler-cloud/prowler" else None   # Windows path limit
            if tmp_root:
                os.makedirs(tmp_root, exist_ok=True)
            tmp = tempfile.mkdtemp(prefix="rzc_", dir=tmp_root)
            try:
                with zipfile.ZipFile(os.path.join(rs.BUNDLES, key + ".zip")) as zf:
                    zf.extractall(tmp)
                b = R.Bundle(tmp)
                path_of = {x: str(c.fm.get("title")) for x, c in b.files.items()}
                rel_of = {p: x for x, p in path_of.items()}
                und = defaultdict(set)
                for x in b.files:
                    for y in b.deps(x):
                        und[x].add(y)
                        und[y].add(x)
                entries = [x["path"] for x in comps[iid]["items-rhizome-ctx-cat-v0.2"] if x["extra2"] == "1"]
                starts = [rel_of[p] for p in entries if p in rel_of]
                parent = {s: None for s in starts}
                dq = deque(starts)
                while dq:
                    u = dq.popleft()
                    for v in und[u]:
                        if v not in parent:
                            parent[v] = u
                            dq.append(v)
                tgt = rel_of.get(gpath)
                path = []
                while tgt is not None and tgt in parent:
                    path.append(path_of[tgt])
                    tgt = parent[tgt]
                graph_path = " <- ".join(path) if path else "no path from any v0.2 entry point"
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            sv = saved[iid]["variants"]["B"]["methods"]
            gset = {g["path"] for g in gold_by[iid]}
            def top10(m):
                return ", ".join(("**" + p + "**") if p in gset else p for p in sv[m]["top"][:10])
            ppr = [x["path"] for x in comps[iid]["ppr-rhizome-ctx-cat-v0.2"]][:10]
            stmt = " ".join(r["problem_statement"].split())[:300]
            out += [f"## {kind}: `{iid}` ({inst[iid]['category']}; method {method})", "",
                    f"- Issue (first 300 characters): {stmt}", f"- Gold files: {', '.join(sorted(gset))}",
                    f"- Focus gold file: `{gpath}`",
                    f"- File-BM25 top 10: {top10('file-bm25')}",
                    f"- rhizome-search [v0.2] top 10: {top10('rhizome-search [v0.2]')}",
                    f"- rhizome-ctx-cat [v0.2] top 10: {top10('rhizome-ctx-cat [v0.2]')}",
                    f"- bm25-graph top 10: {top10('bm25-graph')}",
                    f"- v0.2 entry points: {', '.join(entries)}; strong band {inst[iid]['v02_band_cat']}",
                    f"- PPR top 10 (v0.2 ctx-cat): {', '.join(('**' + p + '**') if p in gset else p for p in ppr)}",
                    f"- Shortest import path from a v0.2 entry point to the focus gold file: {graph_path}", ""]
    try:
        os.rmdir("C:\\rzb")
    except OSError:
        pass
    return "\n".join(out)


if __name__ == "__main__":
    main()
