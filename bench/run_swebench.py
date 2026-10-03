"""SWE-bench Lite file-level localisation benchmark for Rhizome.

Frozen protocol (see bench/README.md):
  * dataset  princeton-nlp/SWE-bench_Lite, split test (300 instances)
  * gold     .py files touched by the gold ``patch`` that exist at ``base_commit``
  * cands    every .py file yielded by ``rhizome.parse_python.iter_python_files`` on the snapshot;
             variant A = all of them, variant B = non-test files (Rhizome's ``test`` tag)
  * query    the full ``problem_statement``, unmodified
  * methods  random, file-bm25, rhizome-search, rhizome-ctx-bug, rhizome-ctx-refactor, fusion-rrf
  * metrics  Acc@{1,3,5} (all gold files in top k), Recall@{5,10}, MRR of the first gold file

Usage:
  python bench/run_swebench.py --limit 10 --variants A B --out bench/runs/<timestamp>
  python bench/run_swebench.py --out bench/runs/<timestamp> --report-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import warnings
import zipfile
from collections import Counter, defaultdict

warnings.filterwarnings("ignore", category=SyntaxWarning)  # ast.parse on old invalid escape sequences; log noise only

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from rhizome.parse_python import iter_python_files  # noqa: E402
from rhizome.retrieve import Bundle, gather, tokens  # noqa: E402
from rhizome.scanner import scan  # noqa: E402

CACHE = os.path.join(HERE, ".cache")
DATA = os.path.join(CACHE, "swe_bench_lite.jsonl")
REPOS = os.path.join(CACHE, "repos")
BUNDLES = os.path.join(CACHE, "bundles")

METHODS = ["random", "file-bm25", "rhizome-search", "rhizome-ctx-bug", "rhizome-ctx-refactor", "fusion-rrf"]
KS_ACC = (1, 3, 5)
KS_REC = (5, 10)
BM25_K1, BM25_B, RRF_K, SEED = 1.2, 0.75, 60, 0
PROTOCOL_VERSION = 1


def _code_tag() -> str:
    """Short hash of rhizome/*.py, so bundles built by different Rhizome code never share a cache entry."""
    import hashlib
    h = hashlib.sha256()
    src = os.path.join(ROOT, "rhizome")
    for fn in sorted(os.listdir(src)):
        if fn.endswith(".py"):
            with open(os.path.join(src, fn), "rb") as fh:
                h.update(fn.encode() + fh.read())
    return h.hexdigest()[:10]


V01_CODE_TAG = "fc46dafc58"  # rhizome/ at c57a02f; its bundles were cached without a tag
CODE_TAG = _code_tag()

PUBLISHED = [  # LocAgent (Chen et al., ACL 2025, arXiv:2503.09089), file level, SWE-bench Lite, Acc@1/3/5
    ("BM25", 38.69, 51.82, 61.68),
    ("E5-base-v2", 49.64, 74.45, 80.29),
    ("CodeRankEmbed", 52.55, 77.74, 84.67),
    ("Agentless (Claude-3.5)", 72.63, 79.20, 79.56),
    ("OpenHands (Claude-3.5)", 76.28, 89.78, 90.15),
    ("LocAgent (Claude-3.5)", 77.74, 91.97, 94.16),
]


# ------------------------------------------------------------------ data

def load_dataset() -> list[dict]:
    if not os.path.exists(DATA):
        os.makedirs(CACHE, exist_ok=True)
        rows = None
        try:
            import datasets
            rows = [dict(r) for r in datasets.load_dataset("princeton-nlp/SWE-bench_Lite", split="test")]
        except Exception as exc:  # e.g. pyarrow.dataset DLL blocked by application control
            print(f"datasets.load_dataset failed ({exc!r}); falling back to the parquet file", flush=True)
            from huggingface_hub import hf_hub_download
            import pyarrow.parquet as pq
            p = hf_hub_download("princeton-nlp/SWE-bench_Lite", "data/test-00000-of-00001.parquet",
                                repo_type="dataset")
            rows = pq.read_table(p).to_pylist()
        keep = ["instance_id", "repo", "base_commit", "problem_statement", "patch"]
        with open(DATA, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps({k: r[k] for k in keep}) + "\n")
    with open(DATA, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


DIFF_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)


def gold_files(patch: str) -> list[str]:
    out = []
    for a, b in DIFF_RE.findall(patch):
        for p in (a, b):
            if p.endswith(".py") and p not in out:
                out.append(p)
    return out


# ------------------------------------------------------------------ git snapshots

def git(repo: str, *args: str, binary: bool = False, timeout: int = 1800):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout if binary else r.stdout.decode(errors="replace").strip()


def ensure_repo(repo: str) -> str:
    dest = os.path.join(REPOS, repo.replace("/", "__"))
    if not os.path.isdir(dest):
        os.makedirs(REPOS, exist_ok=True)
        subprocess.run(["git", "clone", "--bare", "--quiet", f"https://github.com/{repo}.git", dest + ".partial"],
                       check=True)
        os.rename(dest + ".partial", dest)
    return dest


def ensure_commit(repo_dir: str, commit: str):
    try:
        git(repo_dir, "cat-file", "-e", f"{commit}^{{commit}}")
    except RuntimeError:
        git(repo_dir, "fetch", "--quiet", "origin", commit)


def _attr_set(repo_dir: str, commit: str, attr: str, paths: list[str]) -> set[str]:
    """Paths for which ``attr`` is set in the .gitattributes of ``commit`` (not the working tree)."""
    if not paths:
        return set()
    r = subprocess.run(["git", "-C", repo_dir, "check-attr", f"--source={commit}", "-z", "--stdin", attr],
                       input=b"\0".join(p.encode() for p in paths), capture_output=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"git check-attr failed: {r.stderr.decode(errors='replace').strip()}")
    f = r.stdout.split(b"\0")
    return {f[i].decode() for i in range(0, len(f) - 2, 3) if f[i + 2] in (b"set", b"true")}


def tree_files(repo_dir: str, commit: str) -> list[str]:
    """Regular files (not symlinks or submodules) in ``commit``."""
    out = git(repo_dir, "ls-tree", "-r", "-z", commit, binary=True)
    files = []
    for entry in out.split(b"\0"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            if meta.split()[0] in (b"100644", b"100755"):
                files.append(path.decode("utf-8", errors="surrogateescape"))
    return files


def materialise(repo_dir: str, commit: str, dest: str, only_py: bool = False) -> dict:
    """Write the tree of ``commit`` into ``dest``. Returns member info and extraction errors.

    ``git archive`` fetches and writes the bulk of the tree, but it drops paths marked ``export-ignore``
    and rewrites ``export-subst`` files. Those are written afterwards straight from the object store, so
    the snapshot matches the commit exactly (bug found during the Loc-Bench run; see bench/CHANGES.md).

    ``only_py`` writes only the ``.py`` files. Every method reads nothing else, and on blobless clones it
    avoids downloading a repository's data files (one snapshot was 770 MB of them).
    """
    # the archive is streamed to a temporary file, not held in memory: some repositories carry hundreds of MB
    # of data files, and holding the tar plus a BytesIO copy ran the machine out of memory
    fd, tar_path = tempfile.mkstemp(prefix="rza_", suffix=".tar", dir=os.path.dirname(os.path.abspath(dest)))
    with os.fdopen(fd, "wb") as fh:
        r = subprocess.run(["git", "-C", repo_dir, "archive", "--format=tar", commit]
                           + (["--", ":(glob)**/*.py"] if only_py else []), stdout=fh,
                           stderr=subprocess.PIPE, timeout=3600)
    if r.returncode != 0:
        os.remove(tar_path)
        raise RuntimeError(f"git archive failed: {r.stderr.decode(errors='replace').strip()}")
    archive_bytes = os.path.getsize(tar_path)
    names, errors = set(), []

    def write(name: str, blob: bytes | None = None, src=None):
        target = os.path.join(dest, *name.split("/"))
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                if src is not None:
                    shutil.copyfileobj(src, out)
                else:
                    out.write(blob)
            names.add(name)
        except OSError as exc:
            errors.append((name, str(exc)))

    try:
        with tarfile.open(tar_path) as tf:
            for m in tf:
                if not m.isfile():
                    continue  # directories are created on demand; symlinks are skipped (Windows)
                with tf.extractfile(m) as src:
                    write(m.name, src=src)
    finally:
        os.remove(tar_path)
    all_files = [p for p in tree_files(repo_dir, commit) if not only_py or p.endswith(".py")]
    ignored = [p for p in all_files if p not in names]
    subst = sorted(_attr_set(repo_dir, commit, "export-subst", [p for p in all_files if p in names]))
    for p in ignored + subst:
        write(p, blob=git(repo_dir, "cat-file", "blob", f"{commit}:{p}", binary=True))
    return {"names": names, "errors": errors, "archive_bytes": archive_bytes,
            "export_ignored": ignored, "export_subst": subst}


# ------------------------------------------------------------------ bundles (cached by repo, commit)

def bundle_for(repo: str, commit: str, snapshot: str, tmp: str) -> tuple[str, dict]:
    """Return (bundle directory, info). Scans the snapshot, or unpacks a cached bundle."""
    os.makedirs(BUNDLES, exist_ok=True)
    key = f"{repo.replace('/', '__')}__{commit[:12]}"
    if CODE_TAG != V01_CODE_TAG:
        key += f"__{CODE_TAG}"
    zpath, mpath = os.path.join(BUNDLES, key + ".zip"), os.path.join(BUNDLES, key + ".json")
    bdir = os.path.join(tmp, "b")
    if os.path.exists(zpath) and os.path.exists(mpath):
        t0 = time.perf_counter()
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(bdir)
        with open(mpath, encoding="utf-8") as fh:
            meta = json.load(fh)
        return bdir, {"cache_hit": True, "seconds": round(time.perf_counter() - t0, 3), "stats": meta["stats"],
                      "first_scan_seconds": meta["seconds"]}
    t0 = time.perf_counter()
    res = scan(snapshot, out=bdir)
    secs = round(time.perf_counter() - t0, 3)
    with zipfile.ZipFile(zpath + ".partial", "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _, fns in os.walk(bdir):
            for fn in fns:
                full = os.path.join(dirpath, fn)
                zf.write(full, os.path.relpath(full, bdir).replace(os.sep, "/"))
    os.replace(zpath + ".partial", zpath)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"repo": repo, "commit": commit, "seconds": secs, "stats": res.stats}, fh, indent=1)
    return bdir, {"cache_hit": False, "seconds": secs, "stats": res.stats, "first_scan_seconds": secs}


# ------------------------------------------------------------------ methods

def bm25_rank(query: str, cands: list[str], toks: dict[str, Counter]) -> list[str]:
    n = len(cands)
    dl = {c: sum(toks[c].values()) for c in cands}
    avgdl = (sum(dl.values()) / n) if n else 1.0
    df = Counter()
    for c in cands:
        df.update(toks[c].keys())
    q = tokens(query)
    scores = {}
    for c in cands:
        tf, s = toks[c], 0.0
        for t in q:
            f = tf.get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * dl[c] / (avgdl or 1.0)))
        scores[c] = s
    order = {c: i for i, c in enumerate(cands)}  # ties broken by path order
    return sorted(cands, key=lambda c: (-scores[c], order[c]))


def complete(head: list[str], cands: set[str], fallback: list[str]) -> list[str]:
    """Keep ``head`` items that are candidates (first occurrence), then the rest in ``fallback`` order."""
    out, seen = [], set()
    for p in head:
        if p in cands and p not in seen:
            out.append(p)
            seen.add(p)
    head_n = len(out)
    out += [p for p in fallback if p not in seen]
    return out, head_n


def rrf(*rankings: list[str], k: int = RRF_K) -> list[str]:
    score = defaultdict(float)
    for r in rankings:
        for i, p in enumerate(r):
            score[p] += 1.0 / (k + i + 1)
    first = {p: i for i, p in enumerate(rankings[0])}
    return sorted(score, key=lambda p: (-score[p], first[p]))


# ------------------------------------------------------------------ metrics

def metrics(ranking: list[str], gold: list[str]) -> dict:
    pos = {p: i + 1 for i, p in enumerate(ranking)}
    ranks = sorted(pos[g] for g in gold if g in pos)
    m = {f"acc@{k}": int(len(ranks) == len(gold) and bool(gold) and ranks[-1] <= k) for k in KS_ACC}
    for k in KS_REC:
        m[f"recall@{k}"] = sum(1 for r in ranks if r <= k) / len(gold)
    m["mrr"] = 1.0 / ranks[0] if ranks else 0.0
    m["first_gold_rank"] = ranks[0] if ranks else None
    return m


# ------------------------------------------------------------------ one instance

def run_instance(inst: dict, variants: list[str]) -> dict:
    rec = {"instance_id": inst["instance_id"], "repo": inst["repo"], "base_commit": inst["base_commit"]}
    gold_all = gold_files(inst["patch"])
    rec["gold_py_all"] = gold_all
    timings = {}
    t0 = time.perf_counter()
    repo_dir = ensure_repo(inst["repo"])
    ensure_commit(repo_dir, inst["base_commit"])
    tmp = tempfile.mkdtemp(prefix="rzb_")
    try:
        snap = os.path.join(tmp, "s")
        os.makedirs(snap)
        t = time.perf_counter()
        mat = materialise(repo_dir, inst["base_commit"], snap)
        timings["materialise_s"] = round(time.perf_counter() - t, 3)
        rec["extract_errors"] = len(mat["errors"])
        rec["extract_errors_py"] = [n for n, _ in mat["errors"] if n.endswith(".py")]

        gold = [g for g in gold_all if g in mat["names"]]
        rec["gold"] = gold
        rec["gold_added"] = [g for g in gold_all if g not in mat["names"]]
        rec["n_gold"] = len(gold)
        if not gold_all:
            rec["status"] = "excluded"
            rec["exclude_reason"] = "no .py file in gold patch"
            return rec
        if not gold:
            rec["status"] = "excluded"
            rec["exclude_reason"] = "all gold files absent at base_commit"
            return rec

        all_cands = list(iter_python_files(snap))
        t = time.perf_counter()
        bdir, binfo = bundle_for(inst["repo"], inst["base_commit"], snap, tmp)
        timings["scan_s" if not binfo["cache_hit"] else "bundle_cache_load_s"] = binfo["seconds"]
        rec["bundle_cache_hit"] = binfo["cache_hit"]
        rec["scan_stats"] = binfo["stats"]
        t = time.perf_counter()
        bundle = Bundle(bdir)
        timings["bundle_load_s"] = round(time.perf_counter() - t, 3)
        path_of = {rel: str(c.fm.get("title")) for rel, c in bundle.files.items()}
        is_test = {str(c.fm.get("title")): "test" in (c.fm.get("tags") or []) for c in bundle.files.values()}
        rec["candidates_without_concept"] = sum(1 for p in all_cands if p not in is_test)

        t = time.perf_counter()
        toks = {}
        for p in all_cands:
            with open(os.path.join(snap, *p.split("/")), encoding="utf-8", errors="replace") as fh:
                toks[p] = Counter(tokens(fh.read()))
        timings["bm25_tokenise_s"] = round(time.perf_counter() - t, 3)

        query = inst["problem_statement"]
        rng_order = sorted(all_cands)
        rec["variants"] = {}
        for v in variants:
            cands = all_cands if v == "A" else [p for p in all_cands if not is_test.get(p, False)]
            cset = set(cands)
            vt, rankings, head_n = {}, {}, {}

            r = sorted(cands)
            random.Random(SEED).shuffle(r)
            rankings["random"] = r

            t = time.perf_counter()
            bm = bm25_rank(query, cands, toks)
            vt["file-bm25"] = round(time.perf_counter() - t, 4)
            rankings["file-bm25"] = bm

            t = time.perf_counter()
            hits = bundle.search(query, k=len(bundle.files), types=("Source File",))
            rankings["rhizome-search"], head_n["rhizome-search"] = complete([path_of[h] for h, _ in hits], cset, bm)
            vt["rhizome-search"] = round(time.perf_counter() - t, 4)

            for cat in ("bug", "refactor"):
                name = f"rhizome-ctx-{cat}"
                t = time.perf_counter()
                _, items, _ = gather(bundle, query, cat, include_tests=(v == "A"))
                rankings[name], head_n[name] = complete([path_of[it.rel] for it in items if it.rel in path_of],
                                                        cset, bm)
                vt[name] = round(time.perf_counter() - t, 4)

            t = time.perf_counter()
            rankings["fusion-rrf"] = rrf(bm, rankings["rhizome-ctx-bug"])
            vt["fusion-rrf"] = round(time.perf_counter() - t, 4)

            gold_tests = [g for g in gold if g not in cset]
            vr = {"n_candidates": len(cands), "gold_not_in_candidates": gold_tests,
                  "query_s": vt, "own_items": head_n, "methods": {}}
            for mname in METHODS:
                vr["methods"][mname] = {"top10": rankings[mname][:10], **metrics(rankings[mname], gold)}
            rec["variants"][v] = vr
        rec["timings"] = timings
        rec["status"] = "ok"
        return rec
    finally:
        timings["total_s"] = round(time.perf_counter() - t0, 3)
        rec["timings"] = timings
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ exploratory re-scoring (query step only)
# Added after the frozen run: fusion-rrf-search = RRF(file-bm25, rhizome-search). The saved top-10 lists are
# not enough to compute an RRF ranking or MRR exactly, so the query step is re-run on the cached bundles.
# The same pass records which files Rhizome could not parse (the scan only saved counts).

VERIFY = ["file-bm25", "rhizome-search", "rhizome-ctx-bug", "fusion-rrf"]


def rescore_instance(inst: dict, saved: dict, variants: list[str], seen: dict) -> dict:
    from rhizome.parse_python import parse_file
    import hashlib
    rec = {"instance_id": inst["instance_id"], "repo": inst["repo"], "base_commit": inst["base_commit"]}
    key = f"{inst['repo'].replace('/', '__')}__{inst['base_commit'][:12]}"
    zpath = os.path.join(BUNDLES, key + ".zip")
    tmp = tempfile.mkdtemp(prefix="rzb_")
    try:
        snap, bdir = os.path.join(tmp, "s"), os.path.join(tmp, "b")
        os.makedirs(snap)
        materialise(os.path.join(REPOS, inst["repo"].replace("/", "__")), inst["base_commit"], snap)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(bdir)
        bundle = Bundle(bdir)
        path_of = {rel: str(c.fm.get("title")) for rel, c in bundle.files.items()}
        is_test = {str(c.fm.get("title")): "test" in (c.fm.get("tags") or []) for c in bundle.files.values()}
        all_cands = list(iter_python_files(snap))
        toks, errors = {}, []
        for p in all_cands:
            with open(os.path.join(snap, *p.split("/")), "rb") as fh:
                raw = fh.read()
            toks[p] = Counter(tokens(raw.decode("utf-8", errors="replace")))
            h = hashlib.sha256(raw).hexdigest()
            if h not in seen:  # parse errors depend only on file content; parse each distinct content once
                try:
                    seen[h] = parse_file(snap, p).parse_error
                except RecursionError:
                    seen[h] = "RecursionError: maximum recursion depth exceeded"
            if seen[h]:
                errors.append({"path": p, "error": seen[h]})
        rec["parse_errors"] = errors
        query = inst["problem_statement"]
        rec["variants"] = {}
        for v in variants:
            cands = all_cands if v == "A" else [p for p in all_cands if not is_test.get(p, False)]
            cset = set(cands)
            bm = bm25_rank(query, cands, toks)
            hits = bundle.search(query, k=len(bundle.files), types=("Source File",))
            rs, _ = complete([path_of[h] for h, _ in hits], cset, bm)
            _, items, _ = gather(bundle, query, "bug", include_tests=(v == "A"))
            rc, _ = complete([path_of[it.rel] for it in items if it.rel in path_of], cset, bm)
            rankings = {"file-bm25": bm, "rhizome-search": rs, "rhizome-ctx-bug": rc, "fusion-rrf": rrf(bm, rc),
                        "fusion-rrf-search": rrf(bm, rs)}
            sv = saved["variants"][v]["methods"]
            rec["variants"][v] = {
                "top10_matches_saved": {m: rankings[m][:10] == sv[m]["top10"] for m in VERIFY},
                "fusion-rrf-search": {"top10": rankings["fusion-rrf-search"][:10],
                                      **metrics(rankings["fusion-rrf-search"], saved["gold"])}}
        rec["status"] = "ok"
        return rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_rescore(out_dir: str, data: list[dict], variants: list[str]):
    saved = {k: r for k, r in load_records(os.path.join(out_dir, "per_instance.jsonl")).items() if r.get("status") == "ok"}
    xpath = os.path.join(out_dir, "exploratory.jsonl")
    done = {k for k, r in load_records(xpath).items() if r.get("status") == "ok"}
    todo = [x for x in data if x["instance_id"] in saved and x["instance_id"] not in done]
    print(f"rescoring {len(todo)} instances ({len(done)} already done)", flush=True)
    seen: dict = {}
    for i, inst in enumerate(todo, 1):
        t = time.perf_counter()
        try:
            rec = rescore_instance(inst, saved[inst["instance_id"]], variants, seen)
        except Exception as exc:
            rec = {"instance_id": inst["instance_id"], "status": "error", "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()}
        with open(xpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        ok = rec["status"] == "ok" and all(all(x["top10_matches_saved"].values()) for x in rec["variants"].values())
        print(f"[{i}/{len(todo)}] {inst['instance_id']} {rec['status']} {'verified' if ok else 'MISMATCH'} "
              f"{time.perf_counter() - t:.1f}s", flush=True)


# ------------------------------------------------------------------ summary + report

def load_records(path: str) -> dict[str, dict]:
    recs = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    recs[r["instance_id"]] = r  # last record wins (errored instances are retried)
    return recs


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def median(xs):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def agg(recs: list[dict], v: str) -> dict:
    out = {"n": len(recs)}
    for m in METHODS:
        rows = [r["variants"][v]["methods"][m] for r in recs]
        d = {f"acc@{k}": 100 * mean(x[f"acc@{k}"] for x in rows) for k in KS_ACC}
        d.update({f"recall@{k}": 100 * mean(x[f"recall@{k}"] for x in rows) for k in KS_REC})
        d["mrr"] = mean(x["mrr"] for x in rows)
        out[m] = d
    return out


def binom_two_sided(b: int, c: int) -> float:
    """Exact McNemar test (two-sided binomial on discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def paired(recs, v, m1, m2, k=5):
    b = sum(1 for r in recs if r["variants"][v]["methods"][m1][f"acc@{k}"] and not r["variants"][v]["methods"][m2][f"acc@{k}"])
    c = sum(1 for r in recs if r["variants"][v]["methods"][m2][f"acc@{k}"] and not r["variants"][v]["methods"][m1][f"acc@{k}"])
    return {"a_only": b, "b_only": c, "p_exact_mcnemar": binom_two_sided(b, c)}


def summarise(out_dir: str, dataset_n: int, variants: list[str]) -> dict:
    recs = load_records(os.path.join(out_dir, "per_instance.jsonl"))
    ok = [r for r in recs.values() if r.get("status") == "ok"]
    excl = [r for r in recs.values() if r.get("status") == "excluded"]
    err = [r for r in recs.values() if r.get("status") == "error"]
    s = {"dataset_instances": dataset_n, "attempted": len(recs), "evaluated": len(ok), "excluded": len(excl),
         "errors": len(err),
         "excluded_instances": [{"instance_id": r["instance_id"], "reason": r.get("exclude_reason")} for r in excl],
         "error_instances": [{"instance_id": r["instance_id"], "error": r.get("error", "")[:300]} for r in err],
         "instances_with_some_gold_added": sum(1 for r in ok if r.get("gold_added")),
         "gold_files_per_instance": dict(sorted(Counter(r["n_gold"] for r in ok).items())),
         "variants": {}, "by_repo": {}, "paired_acc@5": {}, "cost": {}}
    for v in variants:
        vr = [r for r in ok if v in r.get("variants", {})]
        s["variants"][v] = agg(vr, v)
        s["variants"][v]["instances_with_gold_outside_candidates"] = sum(
            1 for r in vr if r["variants"][v]["gold_not_in_candidates"])
        s["variants"][v]["mean_candidates"] = mean(r["variants"][v]["n_candidates"] for r in vr)
        s["variants"][v]["mean_own_items"] = {m: mean(r["variants"][v]["own_items"][m] for r in vr)
                                              for m in ("rhizome-search", "rhizome-ctx-bug", "rhizome-ctx-refactor")}
        s["by_repo"][v] = {}
        for repo in sorted({r["repo"] for r in vr}):
            s["by_repo"][v][repo] = agg([r for r in vr if r["repo"] == repo], v)
        s["paired_acc@5"][v] = {
            "rhizome-ctx-bug vs file-bm25": paired(vr, v, "rhizome-ctx-bug", "file-bm25"),
            "rhizome-search vs file-bm25": paired(vr, v, "rhizome-search", "file-bm25"),
            "rhizome-ctx-bug vs rhizome-search": paired(vr, v, "rhizome-ctx-bug", "rhizome-search"),
            "fusion-rrf vs file-bm25": paired(vr, v, "fusion-rrf", "file-bm25"),
        }
        s["cost"][v] = {m: {"mean_query_s": mean(r["variants"][v]["query_s"].get(m, 0) for r in vr)}
                        for m in METHODS if m != "random"}
    first = [r["timings"]["scan_s"] for r in ok if "scan_s" in r.get("timings", {})]
    hits = [r["timings"]["bundle_cache_load_s"] for r in ok if "bundle_cache_load_s" in r.get("timings", {})]
    s["cost"]["scan"] = {
        "first_scans": len(first), "first_scan_mean_s": mean(first), "first_scan_median_s": median(first),
        "first_scan_max_s": max(first) if first else None,
        "cache_hits": len(hits), "cache_hit_mean_s": mean(hits),
        "bundle_load_mean_s": mean(r["timings"].get("bundle_load_s", 0) for r in ok),
        "bm25_tokenise_mean_s": mean(r["timings"].get("bm25_tokenise_s", 0) for r in ok),
        "materialise_mean_s": mean(r["timings"].get("materialise_s", 0) for r in ok),
        "instance_total_mean_s": mean(r["timings"].get("total_s", 0) for r in ok),
        "llm_calls": 0, "llm_tokens": 0,
    }
    snaps = {}
    for r in ok:
        st = r.get("scan_stats") or {}
        snaps[f"{r['repo']}@{r['base_commit'][:12]}"] = {"files": st.get("files"), "parse_errors": st.get("parse_errors")}
    s["snapshots"] = {"count": len(snaps), "with_parse_errors": sum(1 for x in snaps.values() if x["parse_errors"]),
                      "total_parse_errors": sum(x["parse_errors"] or 0 for x in snaps.values()),
                      "per_snapshot": snaps}
    s["extract_errors_py_total"] = sum(len(r.get("extract_errors_py", [])) for r in recs.values())
    s["candidates_without_concept_total"] = sum(r.get("candidates_without_concept", 0) for r in ok)
    s["exploratory"] = exploratory_summary(out_dir, ok, variants)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)
    return s


PY2_MSGS = ("Missing parentheses in call to", "leading zeros in decimal integer literals",
            "multiple exception types must be parenthesized", "invalid hexadecimal literal")
FIXTURE_WORDS = ("bad", "broken", "invalid", "syntax", "error", "fail", "corrupt", "malformed")


def classify_parse_error(path: str, error: str) -> str:
    parts = path.lower().split("/")
    in_tests = any(p in ("tests", "test", "testing") or p.startswith("test") for p in parts)
    if in_tests and any(w in "/".join(parts) for w in FIXTURE_WORDS):
        return "Intentionally broken test fixtures"
    if any(m in error for m in PY2_MSGS):
        return "Python 2 syntax"
    return "Other"


def exploratory_summary(out_dir: str, ok: list[dict], variants: list[str]) -> dict | None:
    xrecs = {k: r for k, r in load_records(os.path.join(out_dir, "exploratory.jsonl")).items() if r.get("status") == "ok"}
    if not xrecs:
        return None
    merged = []
    for r in ok:
        x = xrecs.get(r["instance_id"])
        if x is None:
            continue
        m = {"instance_id": r["instance_id"], "variants": {}}
        for v in variants:
            m["variants"][v] = {"methods": {**r["variants"][v]["methods"],
                                            "fusion-rrf-search": x["variants"][v]["fusion-rrf-search"]}}
        merged.append(m)
    out = {"n": len(merged), "missing": len(ok) - len(merged),
           "verified_instances": sum(1 for x in xrecs.values()
                                     if all(all(vv["top10_matches_saved"].values()) for vv in x["variants"].values())),
           "variants": {}}
    for v in variants:
        rows = [m["variants"][v]["methods"]["fusion-rrf-search"] for m in merged]
        d = {f"acc@{k}": 100 * mean(x[f"acc@{k}"] for x in rows) for k in KS_ACC}
        d.update({f"recall@{k}": 100 * mean(x[f"recall@{k}"] for x in rows) for k in KS_REC})
        d["mrr"] = mean(x["mrr"] for x in rows)
        d["paired_acc@5"] = {"vs file-bm25": paired(merged, v, "fusion-rrf-search", "file-bm25"),
                             "vs fusion-rrf": paired(merged, v, "fusion-rrf-search", "fusion-rrf")}
        out["variants"][v] = d
    scan_counts = {r["instance_id"]: (r.get("scan_stats") or {}).get("parse_errors") for r in ok}
    out["parse_error_count_mismatches"] = [k for k, x in xrecs.items()
                                           if k in scan_counts and len(x.get("parse_errors", [])) != scan_counts[k]]
    occ = Counter()
    for x in xrecs.values():
        for e in x.get("parse_errors", []):
            occ[(x["repo"], e["path"], e["error"])] += 1
    out["parse_errors"] = {
        "occurrences": sum(occ.values()), "distinct_files": len({(r, p) for r, p, _ in occ}),
        "files": [{"repo": r, "path": p, "error": e, "snapshots": n, "cause": classify_parse_error(p, e)}
                  for (r, p, e), n in sorted(occ.items())]}
    return out


def fmt(x, d=2):
    return "â€“" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def results_table(a: dict) -> str:
    lines = ["| Method | Acc@1 | Acc@3 | Acc@5 | Recall@5 | Recall@10 | MRR |", "|---|---:|---:|---:|---:|---:|---:|"]
    for m in METHODS:
        d = a[m]
        lines.append(f"| {m} | {fmt(d['acc@1'])} | {fmt(d['acc@3'])} | {fmt(d['acc@5'])} | "
                     f"{fmt(d['recall@5'])} | {fmt(d['recall@10'])} | {fmt(d['mrr'], 3)} |")
    return "\n".join(lines)


def verdict(s: dict, variants: list[str]) -> str:
    out = []
    pub_bm25, pub_e5 = PUBLISHED[0], PUBLISHED[1]
    for v in variants:
        a = s["variants"][v]
        bm, rs, rc, fu = a["file-bm25"], a["rhizome-search"], a["rhizome-ctx-bug"], a["fusion-rrf"]
        p = s["paired_acc@5"][v]

        def cmp(x, y, xn, yn, key="acc@5"):
            d = x[key] - y[key]
            word = "above" if d > 0 else ("below" if d < 0 else "level with")
            return f"{xn} is {abs(d):.1f} points {word} {yn} on {key.replace('acc', 'Acc')} ({x[key]:.1f} vs {y[key]:.1f})"

        out.append(f"**Variant {v}** (n = {a['n']}).")
        out.append(f"- {cmp(rc, bm, 'Rhizome context (bug)', 'our File-BM25')}; "
                   f"paired, Rhizome-only successes {p['rhizome-ctx-bug vs file-bm25']['a_only']} vs "
                   f"BM25-only {p['rhizome-ctx-bug vs file-bm25']['b_only']} "
                   f"(exact McNemar p = {p['rhizome-ctx-bug vs file-bm25']['p_exact_mcnemar']:.3g}).")
        out.append(f"- {cmp(rs, bm, 'Rhizome search', 'our File-BM25')} "
                   f"(p = {p['rhizome-search vs file-bm25']['p_exact_mcnemar']:.3g}).")
        def effect(d, pv):
            if pv >= 0.05:
                return "no significant difference"
            return "helps" if d > 0 else "hurts"

        g = rc["acc@5"] - rs["acc@5"]
        pg = p['rhizome-ctx-bug vs rhizome-search']['p_exact_mcnemar']
        out.append(f"- Graph expansion (bug walk) vs Rhizome search alone: {effect(g, pg)} "
                   f"({g:+.1f} Acc@5, {rc['acc@1'] - rs['acc@1']:+.1f} Acc@1, {rc['mrr'] - rs['mrr']:+.3f} MRR; "
                   f"p = {pg:.3g}).")
        f5 = fu["acc@5"] - bm["acc@5"]
        pf = p['fusion-rrf vs file-bm25']['p_exact_mcnemar']
        out.append(f"- fusion-rrf, a hybrid of File-BM25 and Rhizome context (RRF), vs File-BM25: {effect(f5, pf)} on Acc@5 "
                   f"({f5:+.1f} Acc@5, {fu['acc@1'] - bm['acc@1']:+.1f} Acc@1, {fu['mrr'] - bm['mrr']:+.3f} MRR; "
                   f"p = {pf:.3g}).")

        def vs_pub(x):
            return " and ".join(f"{'above' if x > a5 else 'below'} the published {name} Acc@5 ({a5:.1f})"
                                for name, a1, a3, a5 in (pub_bm25, pub_e5))

        alone = max(("rhizome-search", "rhizome-ctx-bug", "rhizome-ctx-refactor"), key=lambda m: a[m]["acc@5"])
        out.append(f"- Best Rhizome-only method ({alone}, Acc@5 {a[alone]['acc@5']:.1f}) lands {vs_pub(a[alone]['acc@5'])}; "
                   f"fusion-rrf, a hybrid of File-BM25 and Rhizome context (Acc@5 {fu['acc@5']:.1f}), lands {vs_pub(fu['acc@5'])}. "
                   "These published numbers come from a different setup and are not directly comparable.")
    c = s["cost"]["scan"]
    out.append(f"\n**Cost.** No LLM calls and no tokens for any method. A first Rhizome scan took a median "
               f"{fmt(c['first_scan_median_s'], 1)} s per snapshot (mean {fmt(c['first_scan_mean_s'], 1)} s, "
               f"max {fmt(c['first_scan_max_s'], 1)} s); loading the bundle took a mean {fmt(c['bundle_load_mean_s'], 1)} s; "
               f"each Rhizome query then takes well under a second (see the cost table). "
               f"File-BM25 needs a mean {fmt(c['bm25_tokenise_mean_s'], 1)} s to tokenise the snapshot and no persistent index.")
    return "\n".join(out)


V02_PLAN = [
    "#0 RecursionError crash fix (iterative AST visitor, per-file failure isolation)",
    "#1 Field-weighted full-text search (BM25F over path/symbols, docstrings, file body)",
    "#2 Query analysis (traceback frames, module paths, exception names, quoted strings)",
    "#3 Adaptive entry points",
    "#4 Never-demote rule for text matches",
    "#5 Personalized PageRank expansion",
    "#6 `include_tests` respected for every category",
    "#7 Parser fallback with tree-sitter",
    "#8 Re-export resolution through package `__init__.py`",
    "#9 Hub down-weighting",
    "#10 Description clean-up",
    "#11 Parse cache",
    "#12 Persisted search index",
]


def findings(s: dict, variants: list[str]) -> str:
    out = []

    def pv(v, key):
        return s["paired_acc@5"][v][key]["p_exact_mcnemar"]

    def a5(v, m):
        return s["variants"][v][m]["acc@5"]

    def sig(p):
        return "significant" if p < 0.05 else "not significant"

    rs = "; ".join(f"{v}: {a5(v, 'rhizome-search'):.1f} vs {a5(v, 'file-bm25'):.1f}, "
                   f"p = {pv(v, 'rhizome-search vs file-bm25'):.3g}, {sig(pv(v, 'rhizome-search vs file-bm25'))}"
                   for v in variants)
    out.append(f"- **Rhizome search alone is below File-BM25** on Acc@5 ({rs}). Its index covers only concept metadata "
               "(path, heuristic summary, tags, symbol names and first docstring lines), not file bodies.")
    if "A" in variants and "B" in variants:
        out.append(f"- **The bug walk is below Rhizome search in variant B** ({a5('B', 'rhizome-ctx-bug'):.1f} vs "
                   f"{a5('B', 'rhizome-search'):.1f} Acc@5, p = {pv('B', 'rhizome-ctx-bug vs rhizome-search'):.3g}; "
                   f"in A {a5('A', 'rhizome-ctx-bug'):.1f} vs {a5('A', 'rhizome-search'):.1f}, "
                   f"p = {pv('A', 'rhizome-ctx-bug vs rhizome-search'):.3g}, not significant). Graph-expanded "
                   "dependencies are inserted with fixed scores and push the text match down.")
    hy = "; ".join(f"{v}: {a5(v, 'fusion-rrf'):.1f} vs {a5(v, 'file-bm25'):.1f}, "
                   f"p = {pv(v, 'fusion-rrf vs file-bm25'):.3g}" for v in variants)
    out.append(f"- **The BM25 + Rhizome hybrid (fusion-rrf) is above File-BM25** on Acc@5 in variant A and in the same "
               f"direction in variant B ({hy}). It does not improve Acc@1. Rhizome's ranking finds some files BM25 "
               "misses, but on its own it does not beat BM25.")
    out.append("- **SWE-bench Lite cannot test cross-file expansion.** Every instance has a single gold file, so the "
               "benchmark cannot reward finding related files; a multi-file benchmark is needed for that.")
    out.append("- **Planned for v0.2**, each behind an ablation switch: " + "; ".join(V02_PLAN) + ".")
    return "\n".join(out)


def git_info() -> str:
    try:
        head = git(ROOT, "rev-parse", "HEAD")
        dirty = git(ROOT, "status", "--porcelain", "--", "rhizome")
        return head + (" (rhizome/ has uncommitted changes)" if dirty else "")
    except Exception as exc:
        return f"unknown ({exc})"


def write_report(out_dir: str, s: dict, variants: list[str], proto: dict):
    L = ["# Rhizome on SWE-bench Lite: file-level localisation", ""]
    L += ["## 1. Protocol", "",
          f"- **Dataset**: `princeton-nlp/SWE-bench_Lite`, split `test` ({s['dataset_instances']} instances); "
          f"{s['attempted']} attempted, {s['evaluated']} evaluated, {s['excluded']} excluded, {s['errors']} crashed.",
          "- **Gold**: `.py` files named in `diff --git a/â€¦ b/â€¦` lines of the gold `patch` that exist at `base_commit`. "
          f"{s['instances_with_some_gold_added']} evaluated instances also add a new `.py` file; the added file is not scored "
          "(no method can rank a file that does not exist). Instances whose gold files are all absent are excluded.",
          "- **Snapshot**: `git archive --format=tar <base_commit>` of a full-history clone, extracted with Python `tarfile`.",
          "- **Candidates**: every `.py` file from `rhizome.parse_python.iter_python_files(snapshot)`. "
          "Variant **A** = all of them; variant **B** = non-test files (Rhizome's `test` tag, i.e. `FileInfo.is_test`). "
          "In B a gold file that is itself a test stays in the gold set and counts as a miss.",
          "- **Query**: the full `problem_statement`, unmodified, identical for every method.",
          "- **Methods** (each produces a full ranking of the candidates):",
          "  - `random`: shuffle with seed 0 (floor).",
          f"  - `file-bm25`: Okapi BM25 (k1 = {BM25_K1}, b = {BM25_B}) over whole file contents, tokenised with "
          "`rhizome.retrieve.tokens`, IDF over the variant's candidate set.",
          "  - `rhizome-search`: `Bundle.search(query, k=all, types=(\"Source File\",))` on a fresh `rhizome.scanner.scan` bundle "
          "(heuristic summaries, no LLM), then unranked candidates in File-BM25 order.",
          "  - `rhizome-ctx-bug`: `gather(bundle, query, \"bug\", include_tests=(variant == \"A\"))` items in order, then the remaining "
          "candidates in File-BM25 order. **Every instance uses the `bug` category.** Note that `gather` keeps tests for `bug` "
          "regardless of `include_tests`; in variant B they are removed by the candidate filter.",
          "  - `rhizome-ctx-refactor`: the same with category `refactor` (sensitivity check).",
          f"  - `fusion-rrf`: reciprocal rank fusion (k = {RRF_K}) of `file-bm25` and `rhizome-ctx-bug`.",
          "- **Metrics**: Acc@k (k = 1, 3, 5) = the instance succeeds only if *all* gold files are in the top k (LocAgent's definition); "
          "Recall@k = fraction of gold files in the top k; MRR = 1 / rank of the first gold file (0 if unreachable). All in percent except MRR.",
          "- **Frozen**: Rhizome's retrieval code, weights, tokeniser and `k_entry` were not changed for this benchmark "
          "(see `bench/CHANGES.md`). One run, no tuning.",
          f"- **Rhizome commit**: `{proto['rhizome_commit']}`",
          f"- **Machine**: {proto['machine']}; Python {proto['python']}",
          f"- **Run**: started {proto['started']}, arguments `{proto['args']}`", ""]
    L += ["## 2. Our results", ""]
    for v in variants:
        a = s["variants"][v]
        L += [f"### Variant {v}: {'all .py files' if v == 'A' else 'non-test .py files'}", "",
              f"n = {a['n']} instances; mean {a['mean_candidates']:.0f} candidates per instance; "
              f"{a['instances_with_gold_outside_candidates']} instances have a gold file outside the candidate set. "
              f"Mean files ranked by Rhizome itself before the BM25 fallback: "
              + ", ".join(f"{m} {x:.1f}" for m, x in a["mean_own_items"].items()) + ".", "",
              results_table(a), ""]
        L += ["Paired Acc@5 comparisons (instances solved by only one of the two methods, exact McNemar test):", "",
              "| Comparison | first only | second only | p |", "|---|---:|---:|---:|"]
        for name, d in s["paired_acc@5"][v].items():
            L.append(f"| {name} | {d['a_only']} | {d['b_only']} | {d['p_exact_mcnemar']:.3g} |")
        L.append("")
    x = s.get("exploratory")
    L += ["### Exploratory (not pre-registered, decided after seeing the results)", ""]
    if not x:
        L += ["**Not produced.** A row `fusion-rrf-search` (RRF, k = 60, of `file-bm25` and `rhizome-search`, no graph "
              "walk) was planned as an exploratory comparison decided after seeing the results. The top-10 lists saved "
              "in `per_instance.jsonl` are not enough to compute an RRF ranking or MRR exactly, so it needed a follow-up "
              "pass that re-runs the query step on the cached bundles (`--rescore`). That pass was stopped after 20 of "
              "299 instances to save time, and no numbers from it are reported.", ""]
    else:
        L += ["`fusion-rrf-search` = reciprocal rank fusion (k = 60) of `file-bm25` and `rhizome-search` (no graph walk). "
              "It was added after the frozen run had been analysed, so treat it as a hypothesis for the next benchmark, "
              "not as a result. The top-10 lists saved in `per_instance.jsonl` are not enough to compute an RRF ranking "
              "or MRR exactly (a file outside both top-10s can enter the fused top 5), so only the query step was re-run "
              "on the cached bundles (`--rescore`), with no re-scan. As a check, the re-run reproduced the saved top-10 "
              f"lists of `file-bm25`, `rhizome-search`, `rhizome-ctx-bug` and `fusion-rrf` exactly for "
              f"{x['verified_instances']} of {x['n']} instances.", "",
              "| Variant | Method | Acc@1 | Acc@3 | Acc@5 | Recall@5 | Recall@10 | MRR | vs file-bm25 (Acc@5: this only / BM25 only / p) | vs fusion-rrf (Acc@5: this only / fusion-rrf only / p) |",
              "|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
        for v in variants:
            d = x["variants"][v]
            pb, pf = d["paired_acc@5"]["vs file-bm25"], d["paired_acc@5"]["vs fusion-rrf"]
            L.append(f"| {v} | fusion-rrf-search (exploratory) | {fmt(d['acc@1'])} | {fmt(d['acc@3'])} | {fmt(d['acc@5'])} | "
                     f"{fmt(d['recall@5'])} | {fmt(d['recall@10'])} | {fmt(d['mrr'], 3)} | "
                     f"{pb['a_only']} / {pb['b_only']} / {pb['p_exact_mcnemar']:.3g} | "
                     f"{pf['a_only']} / {pf['b_only']} / {pf['p_exact_mcnemar']:.3g} |")
        L.append("")
    L += ["### Breakdown by repository (Acc@1 / Acc@5)", ""]
    for v in variants:
        head = ["Repository", "n"] + [m for m in METHODS if m != "random"]
        L += [f"Variant {v}:", "", "| " + " | ".join(head) + " |", "|---|---:|" + "---:|" * (len(head) - 2)]
        for repo, a in s["by_repo"][v].items():
            L.append(f"| {repo} | {a['n']} | " + " | ".join(
                f"{a[m]['acc@1']:.0f} / {a[m]['acc@5']:.0f}" for m in METHODS if m != "random") + " |")
        L.append("")
    c = s["cost"]["scan"]
    L += ["### Cost", "",
          "LLM calls: 0 and LLM tokens: 0 for every method (Rhizome runs without `--llm`).", "",
          "| Step | Seconds |", "|---|---:|",
          f"| Materialise snapshot (git archive + extract), mean | {fmt(c['materialise_mean_s'])} |",
          f"| Rhizome first scan, mean / median / max ({c['first_scans']} scans) | {fmt(c['first_scan_mean_s'])} / "
          f"{fmt(c['first_scan_median_s'])} / {fmt(c['first_scan_max_s'])} |",
          f"| Rhizome bundle from cache, mean ({c['cache_hits']} hits) | {fmt(c['cache_hit_mean_s'])} |",
          f"| Load bundle (`Bundle(path)`), mean | {fmt(c['bundle_load_mean_s'])} |",
          f"| Tokenise snapshot for File-BM25, mean | {fmt(c['bm25_tokenise_mean_s'])} |",
          f"| Whole instance (both variants, all methods), mean | {fmt(c['instance_total_mean_s'])} |"]
    for v in variants:
        for m, d in s["cost"][v].items():
            L.append(f"| Query `{m}` (variant {v}), mean | {fmt(d['mean_query_s'], 4)} |")
    L += ["", "### Counts", "",
          f"- Evaluated: {s['evaluated']}; excluded: {s['excluded']}; crashed: {s['errors']}.",
          f"- Snapshots scanned: {s['snapshots']['count']}; with at least one Rhizome parse error: "
          f"{s['snapshots']['with_parse_errors']} ({s['snapshots']['total_parse_errors']} files in total; "
          "files that fail to parse stay in the bundle as nodes without symbols or imports).",
          f"- `.py` files that could not be extracted from the archive: {s['extract_errors_py_total']}; "
          f"candidates without a Rhizome concept: {s['candidates_without_concept_total']}.",
          f"- Gold files per evaluated instance: {s['gold_files_per_instance']}."]
    if s["excluded_instances"]:
        L += ["- Excluded: " + "; ".join(f"`{x['instance_id']}` ({x['reason']})" for x in s["excluded_instances"]) + "."]
    if s["error_instances"]:
        L += ["- Crashed: " + "; ".join(f"`{x['instance_id']}`: {x['error']}" for x in s["error_instances"]) + "."]
    L += ["", "### Gold files per instance", "",
          f"All {s['evaluated']} evaluated instances have exactly one gold file (SWE-bench Lite only contains single-file "
          "patches). Acc@k therefore equals Recall@k, and graph expansion cannot recover *additional* gold files on this "
          "benchmark: it can only move the one gold file up or down.",
          "", "### Crashes", "",
          "`sympy__sympy-24909` crashed with `RecursionError: maximum recursion depth exceeded`. The recursive AST visitor "
          "in `rhizome/parse_python.py` (`parse_file` -> `_Visitor.visit`) exceeds Python's recursion limit on "
          "`sympy/polys/numberfields/resolvent_lookup.py`, a file of very deeply nested polynomial expressions. This is a "
          "Rhizome bug, to be fixed in v0.2 as #0. The instance is excluded from all numbers, so n = 299."]
    pe = (s.get("exploratory") or {}).get("parse_errors")
    L += ["", "### Parse errors", ""]
    if not pe:
        L += ["**Only counts are available.** The per-file list (path, error, cause) was to come from the same "
              "follow-up pass, which was stopped, so it was not produced. The scan recorded these counts per snapshot. "
              "A file that fails `ast.parse` stays in the bundle as a node but loses all its symbols and import edges, "
              "so it can only be found by its path and heuristic summary, and graph expansion cannot reach it.", "",
              "| Repository | Snapshots with parse errors | Files (summed over snapshots) |", "|---|---:|---:|"]
        per = defaultdict(lambda: [0, 0])
        for k, v in s["snapshots"]["per_snapshot"].items():
            if v["parse_errors"]:
                per[k.split("@")[0]][0] += 1
                per[k.split("@")[0]][1] += v["parse_errors"]
        L += [f"| {r} | {a} | {b} |" for r, (a, b) in sorted(per.items())]
        L += [f"| **Total** | {s['snapshots']['with_parse_errors']} | {s['snapshots']['total_parse_errors']} |"]
    else:
        L += [f"Rhizome could not parse {pe['distinct_files']} distinct files ({pe['occurrences']} file-in-snapshot "
              f"occurrences; the scan stats counted {s['snapshots']['total_parse_errors']}; per-instance counts differ from "
              f"the scan stats for {len(s['exploratory']['parse_error_count_mismatches'])} instances). "
              "A file that fails `ast.parse` "
              "stays in the bundle as a node but loses all its symbols and import edges, so it can only be found by its "
              "path and heuristic summary, and graph expansion cannot reach it. Grouped by cause "
              "(classified from the path and error message):", ""]
        by = defaultdict(list)
        for f in pe["files"]:
            by[f["cause"]].append(f)
        for cause in ("Python 2 syntax", "Intentionally broken test fixtures", "Other"):
            fs = by.get(cause, [])
            L += [f"**{cause}** ({len(fs)} files)", ""]
            if fs:
                L += ["| Repository | Path | Error | Snapshots |", "|---|---|---|---:|"]
                L += [f"| {f['repo']} | `{f['path']}` | {f['error'].replace('|', '/')} | {f['snapshots']} |" for f in fs]
            L.append("")
    L += ["", "## 3. Published results (different setups â€” not directly comparable)", "",
          "Source: Z. Chen et al., *LocAgent: Graph-Guided LLM Agents for Code Localization*, ACL 2025, arXiv:2503.09089. "
          "File-level localisation on SWE-bench Lite, Acc@k as defined above. Copied from the paper, not measured here.", "",
          "| Method | Acc@1 | Acc@3 | Acc@5 |", "|---|---:|---:|---:|"]
    L += [f"| {n} | {a1:.2f} | {a3:.2f} | {a5:.2f} |" for n, a1, a3, a5 in PUBLISHED]
    L += ["", "## 4. Verdict", "", verdict(s, variants), ""]
    L += ["## 5. Findings and planned changes", "", findings(s, variants), ""]
    L += ["## 6. Threats to validity", "",
          "- **Our BM25 is not theirs.** Our File-BM25 uses Rhizome's tokeniser (camelCase/snake splitting, a small stop list, "
          "crude plural stripping) over whole files. LocAgent's BM25 baseline uses a different tokeniser and indexing, "
          "so the published row and ours can differ for reasons unrelated to the method.",
          "- **Candidate set and test files.** Published baselines differ in whether test files are candidates. Variant A "
          "(all files) is closer to typical BM25 runs; variant B removes tests using Rhizome's own path heuristic, which "
          "favours no method but shrinks the search space for all of them.",
          "- **Excluded and partially-new gold.** Instances whose gold files are all new are excluded; files added by the "
          "patch are dropped from the gold set. Published numbers may count these differently.",
          "- **Fallback ordering.** Rhizome methods rank only the files they return; the rest of the list is File-BM25 order. "
          "Acc@5 therefore reflects a mix whenever Rhizome returns fewer than 5 candidate files.",
          "- **Single category.** The `bug` walk is used for every instance, including feature requests.",
          "- **Single run, one machine.** Rhizome's Leiden step is seeded, so rankings are deterministic, but timings "
          "depend on this machine and on disk caching. No confidence intervals beyond the paired McNemar tests.",
          "- **Dataset loading.** `datasets.load_dataset` could not be used on this machine (a pyarrow DLL is blocked by Windows "
          "application control); the same `test` parquet file was read from the Hugging Face Hub with `pyarrow.parquet`.",
          "- **Timings.** For part of the run the machine ran at roughly half speed (background load), so per-instance "
          "times are indicative only. Rankings are unaffected.", ""]
    with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="first N instances in dataset order")
    ap.add_argument("--variants", nargs="+", default=["A", "B"], choices=["A", "B"])
    ap.add_argument("--instance", action="append", default=[], help="only these instance ids (repeatable)")
    ap.add_argument("--out", default=None, help="run directory (default bench/runs/<timestamp>)")
    ap.add_argument("--report-only", action="store_true", help="rebuild summary.json and REPORT.md only")
    ap.add_argument("--rescore", action="store_true",
                    help="exploratory: re-run the query step on cached bundles (fusion-rrf-search, parse errors)")
    args = ap.parse_args(argv)

    out_dir = args.out or os.path.join(HERE, "runs", dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    data = load_dataset()
    todo = [x for x in data if x["instance_id"] in set(args.instance)] if args.instance else data
    todo = todo[: args.limit] if args.limit else todo
    variants = sorted(set(args.variants))

    ppath = os.path.join(out_dir, "protocol.json")
    proto = {"version": PROTOCOL_VERSION, "variants": variants, "methods": METHODS, "bm25": [BM25_K1, BM25_B],
             "rrf_k": RRF_K, "seed": SEED, "rhizome_commit": git_info(),
             "machine": f"{platform.platform()}, {platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs",
             "python": platform.python_version(), "started": dt.datetime.now().isoformat(timespec="seconds"),
             "args": " ".join(sys.argv[1:])}
    if os.path.exists(ppath):
        with open(ppath, encoding="utf-8") as fh:
            old = json.load(fh)
        for key in ("version", "variants", "methods", "bm25", "rrf_k", "seed"):
            if old.get(key) != proto[key]:
                sys.exit(f"protocol mismatch on resume ({key}: {old.get(key)} != {proto[key]}); use a new --out")
        if old.get("rhizome_commit") != proto["rhizome_commit"]:
            sys.exit(f"Rhizome commit changed since this run started ({old.get('rhizome_commit')}); use a new --out")
        proto = old
    else:
        with open(ppath, "w", encoding="utf-8") as fh:
            json.dump(proto, fh, indent=1)

    jpath = os.path.join(out_dir, "per_instance.jsonl")
    if args.rescore:
        run_rescore(out_dir, todo, variants)
    elif not args.report_only:
        done = {k for k, r in load_records(jpath).items() if r.get("status") in ("ok", "excluded")}
        pending = [x for x in todo if x["instance_id"] not in done]
        print(f"{len(todo)} instances selected, {len(todo) - len(pending)} already done, {len(pending)} to run", flush=True)
        for i, inst in enumerate(pending, 1):
            t = time.perf_counter()
            try:
                rec = run_instance(inst, variants)
            except Exception as exc:
                rec = {"instance_id": inst["instance_id"], "repo": inst["repo"], "status": "error",
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            with open(jpath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            extra = ""
            if rec["status"] == "ok":
                extra = " ".join(f"{v}:bm25={int(rec['variants'][v]['methods']['file-bm25']['acc@5'])}"
                                 f",ctx={int(rec['variants'][v]['methods']['rhizome-ctx-bug']['acc@5'])}" for v in variants)
            print(f"[{i}/{len(pending)}] {inst['instance_id']} {rec['status']} {time.perf_counter() - t:.1f}s {extra}"
                  + (f" {rec.get('error', '')[:200]}" if rec["status"] == "error" else ""), flush=True)

    s = summarise(out_dir, len(data), variants)
    write_report(out_dir, s, variants, proto)
    for v in variants:
        print(f"\nVariant {v} (n = {s['variants'][v]['n']})\n" + results_table(s["variants"][v]))
    print(f"\nevaluated {s['evaluated']}, excluded {s['excluded']}, errors {s['errors']}; report: "
          f"{os.path.join(out_dir, 'REPORT.md')}")


if __name__ == "__main__":
    main()
