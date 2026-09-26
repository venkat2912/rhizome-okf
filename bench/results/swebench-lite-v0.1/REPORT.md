# Rhizome on SWE-bench Lite: file-level localisation

## 1. Protocol

- **Dataset**: `princeton-nlp/SWE-bench_Lite`, split `test` (300 instances); 300 attempted, 299 evaluated, 0 excluded, 1 crashed.
- **Gold**: `.py` files named in `diff --git a/… b/…` lines of the gold `patch` that exist at `base_commit`. 0 evaluated instances also add a new `.py` file; the added file is not scored (no method can rank a file that does not exist). Instances whose gold files are all absent are excluded.
- **Snapshot**: `git archive --format=tar <base_commit>` of a full-history clone, extracted with Python `tarfile`.
- **Candidates**: every `.py` file from `rhizome.parse_python.iter_python_files(snapshot)`. Variant **A** = all of them; variant **B** = non-test files (Rhizome's `test` tag, i.e. `FileInfo.is_test`). In B a gold file that is itself a test stays in the gold set and counts as a miss.
- **Query**: the full `problem_statement`, unmodified, identical for every method.
- **Methods** (each produces a full ranking of the candidates):
  - `random`: shuffle with seed 0 (floor).
  - `file-bm25`: Okapi BM25 (k1 = 1.2, b = 0.75) over whole file contents, tokenised with `rhizome.retrieve.tokens`, IDF over the variant's candidate set.
  - `rhizome-search`: `Bundle.search(query, k=all, types=("Source File",))` on a fresh `rhizome.scanner.scan` bundle (heuristic summaries, no LLM), then unranked candidates in File-BM25 order.
  - `rhizome-ctx-bug`: `gather(bundle, query, "bug", include_tests=(variant == "A"))` items in order, then the remaining candidates in File-BM25 order. **Every instance uses the `bug` category.** Note that `gather` keeps tests for `bug` regardless of `include_tests`; in variant B they are removed by the candidate filter.
  - `rhizome-ctx-refactor`: the same with category `refactor` (sensitivity check).
  - `fusion-rrf`: reciprocal rank fusion (k = 60) of `file-bm25` and `rhizome-ctx-bug`.
- **Metrics**: Acc@k (k = 1, 3, 5) = the instance succeeds only if *all* gold files are in the top k (LocAgent's definition); Recall@k = fraction of gold files in the top k; MRR = 1 / rank of the first gold file (0 if unreachable). All in percent except MRR.
- **Frozen**: Rhizome's retrieval code, weights, tokeniser and `k_entry` were not changed for this benchmark (see `bench/CHANGES.md`). One run, no tuning.
- **Rhizome commit**: `f35f2d3d90a5ae1fc9b3880977370ac8b83e9f11`
- **Machine**: Windows-11-10.0.26200-SP0, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.2
- **Run**: started 2026-09-27T00:37:24, arguments `--variants A B --out bench/runs/full`

## 2. Our results

### Variant A: all .py files

n = 299 instances; mean 1580 candidates per instance; 0 instances have a gold file outside the candidate set. Mean files ranked by Rhizome itself before the BM25 fallback: rhizome-search 1326.4, rhizome-ctx-bug 105.5, rhizome-ctx-refactor 556.5.

| Method | Acc@1 | Acc@3 | Acc@5 | Recall@5 | Recall@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| random | 0.00 | 0.00 | 0.67 | 0.67 | 1.67 | 0.008 |
| file-bm25 | 30.10 | 51.17 | 56.19 | 56.19 | 67.56 | 0.433 |
| rhizome-search | 27.76 | 46.49 | 55.85 | 55.85 | 66.22 | 0.403 |
| rhizome-ctx-bug | 27.76 | 46.49 | 53.51 | 53.51 | 60.54 | 0.396 |
| rhizome-ctx-refactor | 27.76 | 46.49 | 53.18 | 53.18 | 59.20 | 0.390 |
| fusion-rrf | 29.10 | 53.18 | 63.21 | 63.21 | 73.91 | 0.443 |

Paired Acc@5 comparisons (instances solved by only one of the two methods, exact McNemar test):

| Comparison | first only | second only | p |
|---|---:|---:|---:|
| rhizome-ctx-bug vs file-bm25 | 44 | 52 | 0.475 |
| rhizome-search vs file-bm25 | 45 | 46 | 1 |
| rhizome-ctx-bug vs rhizome-search | 6 | 13 | 0.167 |
| fusion-rrf vs file-bm25 | 46 | 25 | 0.017 |

### Variant B: non-test .py files

n = 299 instances; mean 658 candidates per instance; 0 instances have a gold file outside the candidate set. Mean files ranked by Rhizome itself before the BM25 fallback: rhizome-search 583.9, rhizome-ctx-bug 87.7, rhizome-ctx-refactor 303.9.

| Method | Acc@1 | Acc@3 | Acc@5 | Recall@5 | Recall@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| random | 0.00 | 0.00 | 1.00 | 1.00 | 2.68 | 0.013 |
| file-bm25 | 40.80 | 57.53 | 65.89 | 65.89 | 76.25 | 0.526 |
| rhizome-search | 37.46 | 54.52 | 62.54 | 62.54 | 71.91 | 0.491 |
| rhizome-ctx-bug | 37.12 | 51.84 | 57.19 | 57.19 | 62.88 | 0.468 |
| rhizome-ctx-refactor | 37.46 | 54.52 | 62.88 | 62.88 | 66.56 | 0.481 |
| fusion-rrf | 40.80 | 62.21 | 71.57 | 71.57 | 80.60 | 0.543 |

Paired Acc@5 comparisons (instances solved by only one of the two methods, exact McNemar test):

| Comparison | first only | second only | p |
|---|---:|---:|---:|
| rhizome-ctx-bug vs file-bm25 | 33 | 59 | 0.00878 |
| rhizome-search vs file-bm25 | 35 | 45 | 0.314 |
| rhizome-ctx-bug vs rhizome-search | 11 | 27 | 0.0139 |
| fusion-rrf vs file-bm25 | 37 | 20 | 0.0331 |

### Exploratory (not pre-registered, decided after seeing the results)

**Not produced.** A row `fusion-rrf-search` (RRF, k = 60, of `file-bm25` and `rhizome-search`, no graph walk) was planned as an exploratory comparison decided after seeing the results. The top-10 lists saved in `per_instance.jsonl` are not enough to compute an RRF ranking or MRR exactly, so it needed a follow-up pass that re-runs the query step on the cached bundles (`--rescore`). That pass was stopped after 20 of 299 instances to save time, and no numbers from it are reported.

### Breakdown by repository (Acc@1 / Acc@5)

Variant A:

| Repository | n | file-bm25 | rhizome-search | rhizome-ctx-bug | rhizome-ctx-refactor | fusion-rrf |
|---|---:|---:|---:|---:|---:|---:|
| astropy/astropy | 6 | 83 / 83 | 67 / 67 | 67 / 67 | 67 / 67 | 67 / 83 |
| django/django | 114 | 28 / 55 | 18 / 50 | 18 / 51 | 18 / 49 | 25 / 60 |
| matplotlib/matplotlib | 23 | 22 / 43 | 26 / 57 | 26 / 48 | 26 / 48 | 39 / 52 |
| mwaskom/seaborn | 4 | 50 / 75 | 25 / 100 | 25 / 100 | 25 / 100 | 25 / 100 |
| pallets/flask | 3 | 33 / 67 | 33 / 67 | 33 / 33 | 33 / 33 | 33 / 33 |
| psf/requests | 6 | 50 / 83 | 33 / 67 | 33 / 67 | 33 / 67 | 50 / 67 |
| pydata/xarray | 5 | 0 / 40 | 0 / 40 | 0 / 60 | 0 / 40 | 0 / 80 |
| pylint-dev/pylint | 6 | 50 / 67 | 17 / 33 | 17 / 50 | 17 / 33 | 33 / 67 |
| pytest-dev/pytest | 17 | 6 / 41 | 18 / 47 | 18 / 47 | 18 / 53 | 6 / 47 |
| scikit-learn/scikit-learn | 23 | 30 / 74 | 48 / 83 | 48 / 78 | 48 / 78 | 30 / 91 |
| sphinx-doc/sphinx | 16 | 38 / 62 | 19 / 56 | 19 / 44 | 19 / 56 | 25 / 62 |
| sympy/sympy | 76 | 33 / 53 | 39 / 57 | 39 / 51 | 39 / 51 | 36 / 63 |

Variant B:

| Repository | n | file-bm25 | rhizome-search | rhizome-ctx-bug | rhizome-ctx-refactor | fusion-rrf |
|---|---:|---:|---:|---:|---:|---:|
| astropy/astropy | 6 | 83 / 83 | 67 / 83 | 67 / 67 | 67 / 67 | 67 / 83 |
| django/django | 114 | 46 / 72 | 32 / 60 | 32 / 54 | 32 / 62 | 40 / 72 |
| matplotlib/matplotlib | 23 | 22 / 48 | 30 / 61 | 30 / 48 | 30 / 61 | 39 / 65 |
| mwaskom/seaborn | 4 | 50 / 75 | 50 / 100 | 50 / 100 | 50 / 100 | 50 / 100 |
| pallets/flask | 3 | 33 / 100 | 33 / 67 | 33 / 67 | 33 / 67 | 33 / 100 |
| psf/requests | 6 | 67 / 100 | 33 / 67 | 33 / 67 | 33 / 67 | 50 / 83 |
| pydata/xarray | 5 | 0 / 60 | 0 / 40 | 0 / 80 | 0 / 60 | 0 / 100 |
| pylint-dev/pylint | 6 | 67 / 67 | 17 / 33 | 17 / 50 | 17 / 33 | 67 / 67 |
| pytest-dev/pytest | 17 | 29 / 47 | 29 / 71 | 29 / 53 | 29 / 59 | 29 / 59 |
| scikit-learn/scikit-learn | 23 | 52 / 87 | 74 / 83 | 74 / 83 | 74 / 83 | 65 / 91 |
| sphinx-doc/sphinx | 16 | 50 / 75 | 31 / 69 | 25 / 62 | 31 / 69 | 38 / 69 |
| sympy/sympy | 76 | 32 / 53 | 42 / 58 | 42 / 53 | 42 / 58 | 36 / 64 |

### Cost

LLM calls: 0 and LLM tokens: 0 for every method (Rhizome runs without `--llm`).

| Step | Seconds |
|---|---:|
| Materialise snapshot (git archive + extract), mean | 6.32 |
| Rhizome first scan, mean / median / max (286 scans) | 16.66 / 15.73 / 87.98 |
| Rhizome bundle from cache, mean (13 hits) | 1.90 |
| Load bundle (`Bundle(path)`), mean | 2.76 |
| Tokenise snapshot for File-BM25, mean | 1.78 |
| Whole instance (both variants, all methods), mean | 29.22 |
| Query `file-bm25` (variant A), mean | 0.0651 |
| Query `rhizome-search` (variant A), mean | 0.0284 |
| Query `rhizome-ctx-bug` (variant A), mean | 0.0280 |
| Query `rhizome-ctx-refactor` (variant A), mean | 0.0289 |
| Query `fusion-rrf` (variant A), mean | 0.0012 |
| Query `file-bm25` (variant B), mean | 0.0313 |
| Query `rhizome-search` (variant B), mean | 0.0282 |
| Query `rhizome-ctx-bug` (variant B), mean | 0.0284 |
| Query `rhizome-ctx-refactor` (variant B), mean | 0.0297 |
| Query `fusion-rrf` (variant B), mean | 0.0005 |

### Counts

- Evaluated: 299; excluded: 0; crashed: 1.
- Snapshots scanned: 296; with at least one Rhizome parse error: 60 (131 files in total; files that fail to parse stay in the bundle as nodes without symbols or imports).
- `.py` files that could not be extracted from the archive: 0; candidates without a Rhizome concept: 0.
- Gold files per evaluated instance: {1: 299}.
- Crashed: `sympy__sympy-24909`: RecursionError: maximum recursion depth exceeded.

### Gold files per instance

All 299 evaluated instances have exactly one gold file (SWE-bench Lite only contains single-file patches). Acc@k therefore equals Recall@k, and graph expansion cannot recover *additional* gold files on this benchmark: it can only move the one gold file up or down.

### Crashes

`sympy__sympy-24909` crashed with `RecursionError: maximum recursion depth exceeded`. The recursive AST visitor in `rhizome/parse_python.py` (`parse_file` -> `_Visitor.visit`) exceeds Python's recursion limit on `sympy/polys/numberfields/resolvent_lookup.py`, a file of very deeply nested polynomial expressions. This is a Rhizome bug, to be fixed in v0.2 as #0. The instance is excluded from all numbers, so n = 299.

### Parse errors

**Only counts are available.** The per-file list (path, error, cause) was to come from the same follow-up pass, which was stopped, so it was not produced. The scan recorded these counts per snapshot. A file that fails `ast.parse` stays in the bundle as a node but loses all its symbols and import edges, so it can only be found by its path and heuristic summary, and graph expansion cannot reach it.

| Repository | Snapshots with parse errors | Files (summed over snapshots) |
|---|---:|---:|
| django/django | 52 | 52 |
| psf/requests | 1 | 15 |
| pylint-dev/pylint | 6 | 61 |
| scikit-learn/scikit-learn | 1 | 3 |
| **Total** | 60 | 131 |

## 3. Published results (different setups — not directly comparable)

Source: Z. Chen et al., *LocAgent: Graph-Guided LLM Agents for Code Localization*, ACL 2025, arXiv:2503.09089. File-level localisation on SWE-bench Lite, Acc@k as defined above. Copied from the paper, not measured here.

| Method | Acc@1 | Acc@3 | Acc@5 |
|---|---:|---:|---:|
| BM25 | 38.69 | 51.82 | 61.68 |
| E5-base-v2 | 49.64 | 74.45 | 80.29 |
| CodeRankEmbed | 52.55 | 77.74 | 84.67 |
| Agentless (Claude-3.5) | 72.63 | 79.20 | 79.56 |
| OpenHands (Claude-3.5) | 76.28 | 89.78 | 90.15 |
| LocAgent (Claude-3.5) | 77.74 | 91.97 | 94.16 |

## 4. Verdict

**Variant A** (n = 299).
- Rhizome context (bug) is 2.7 points below our File-BM25 on Acc@5 (53.5 vs 56.2); paired, Rhizome-only successes 44 vs BM25-only 52 (exact McNemar p = 0.475).
- Rhizome search is 0.3 points below our File-BM25 on Acc@5 (55.9 vs 56.2) (p = 1).
- Graph expansion (bug walk) vs Rhizome search alone: no significant difference (-2.3 Acc@5, +0.0 Acc@1, -0.007 MRR; p = 0.167).
- fusion-rrf, a hybrid of File-BM25 and Rhizome context (RRF), vs File-BM25: helps on Acc@5 (+7.0 Acc@5, -1.0 Acc@1, +0.010 MRR; p = 0.017).
- Best Rhizome-only method (rhizome-search, Acc@5 55.9) lands below the published BM25 Acc@5 (61.7) and below the published E5-base-v2 Acc@5 (80.3); fusion-rrf, a hybrid of File-BM25 and Rhizome context (Acc@5 63.2), lands above the published BM25 Acc@5 (61.7) and below the published E5-base-v2 Acc@5 (80.3). These published numbers come from a different setup and are not directly comparable.
**Variant B** (n = 299).
- Rhizome context (bug) is 8.7 points below our File-BM25 on Acc@5 (57.2 vs 65.9); paired, Rhizome-only successes 33 vs BM25-only 59 (exact McNemar p = 0.00878).
- Rhizome search is 3.3 points below our File-BM25 on Acc@5 (62.5 vs 65.9) (p = 0.314).
- Graph expansion (bug walk) vs Rhizome search alone: hurts (-5.4 Acc@5, -0.3 Acc@1, -0.023 MRR; p = 0.0139).
- fusion-rrf, a hybrid of File-BM25 and Rhizome context (RRF), vs File-BM25: helps on Acc@5 (+5.7 Acc@5, +0.0 Acc@1, +0.018 MRR; p = 0.0331).
- Best Rhizome-only method (rhizome-ctx-refactor, Acc@5 62.9) lands above the published BM25 Acc@5 (61.7) and below the published E5-base-v2 Acc@5 (80.3); fusion-rrf, a hybrid of File-BM25 and Rhizome context (Acc@5 71.6), lands above the published BM25 Acc@5 (61.7) and below the published E5-base-v2 Acc@5 (80.3). These published numbers come from a different setup and are not directly comparable.

**Cost.** No LLM calls and no tokens for any method. A first Rhizome scan took a median 15.7 s per snapshot (mean 16.7 s, max 88.0 s); loading the bundle took a mean 2.8 s; each Rhizome query then takes well under a second (see the cost table). File-BM25 needs a mean 1.8 s to tokenise the snapshot and no persistent index.

## 5. Findings and planned changes

- **Rhizome search alone is below File-BM25** on Acc@5 (A: 55.9 vs 56.2, p = 1, not significant; B: 62.5 vs 65.9, p = 0.314, not significant). Its index covers only concept metadata (path, heuristic summary, tags, symbol names and first docstring lines), not file bodies.
- **The bug walk is below Rhizome search in variant B** (57.2 vs 62.5 Acc@5, p = 0.0139; in A 53.5 vs 55.9, p = 0.167, not significant). Graph-expanded dependencies are inserted with fixed scores and push the text match down.
- **The BM25 + Rhizome hybrid (fusion-rrf) is above File-BM25** on Acc@5 in variant A and in the same direction in variant B (A: 63.2 vs 56.2, p = 0.017; B: 71.6 vs 65.9, p = 0.0331). It does not improve Acc@1. Rhizome's ranking finds some files BM25 misses, but on its own it does not beat BM25.
- **SWE-bench Lite cannot test cross-file expansion.** Every instance has a single gold file, so the benchmark cannot reward finding related files; a multi-file benchmark is needed for that.
- **Planned for v0.2**, each behind an ablation switch: #0 RecursionError crash fix (iterative AST visitor, per-file failure isolation); #1 Field-weighted full-text search (BM25F over path/symbols, docstrings, file body); #2 Query analysis (traceback frames, module paths, exception names, quoted strings); #3 Adaptive entry points; #4 Never-demote rule for text matches; #5 Personalized PageRank expansion; #6 `include_tests` respected for every category; #7 Parser fallback with tree-sitter; #8 Re-export resolution through package `__init__.py`; #9 Hub down-weighting; #10 Description clean-up; #11 Parse cache; #12 Persisted search index.

## 6. Threats to validity

- **Our BM25 is not theirs.** Our File-BM25 uses Rhizome's tokeniser (camelCase/snake splitting, a small stop list, crude plural stripping) over whole files. LocAgent's BM25 baseline uses a different tokeniser and indexing, so the published row and ours can differ for reasons unrelated to the method.
- **Candidate set and test files.** Published baselines differ in whether test files are candidates. Variant A (all files) is closer to typical BM25 runs; variant B removes tests using Rhizome's own path heuristic, which favours no method but shrinks the search space for all of them.
- **Excluded and partially-new gold.** Instances whose gold files are all new are excluded; files added by the patch are dropped from the gold set. Published numbers may count these differently.
- **Fallback ordering.** Rhizome methods rank only the files they return; the rest of the list is File-BM25 order. Acc@5 therefore reflects a mix whenever Rhizome returns fewer than 5 candidate files.
- **Single category.** The `bug` walk is used for every instance, including feature requests.
- **Single run, one machine.** Rhizome's Leiden step is seeded, so rankings are deterministic, but timings depend on this machine and on disk caching. No confidence intervals beyond the paired McNemar tests.
- **Dataset loading.** `datasets.load_dataset` could not be used on this machine (a pyarrow DLL is blocked by Windows application control); the same `test` parquet file was read from the Hugging Face Hub with `pyarrow.parquet`.
- **Timings.** For part of the run the machine ran at roughly half speed (background load), so per-instance times are indicative only. Rankings are unaffected.
