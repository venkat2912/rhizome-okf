# Changes made for the SWE-bench Lite benchmark

## Changes to `rhizome/`

None. The run used commit `f35f2d3`, whose `rhizome/` code is identical to `c57a02f` (Rhizome v0.1.0);
`f35f2d3` only adds the numpy/scipy dependencies and refreshes the example bundle. Retrieval logic,
weights, tokenisation and `k` values are unchanged. Any crash fix needed during the run will be listed here with its reason.

## Changes to the benchmark protocol

- **Dataset loader.** `datasets.load_dataset("princeton-nlp/SWE-bench_Lite", split="test")` fails on this
  machine: Windows application control blocks `pyarrow/_dataset.pyd`. `bench/run_swebench.py` tries
  `datasets` first and falls back to downloading the same file (`data/test-00000-of-00001.parquet`)
  with `huggingface_hub` and reading it with `pyarrow.parquet`. It has the same 300 rows.
- **Bare clones.** Repositories are cloned with `git clone --bare` (full history, no working tree),
  because only `git archive` is needed. This also avoids Windows `MAX_PATH` problems (`LongPathsEnabled`
  is 0 on this machine) with checked-out trees.
- **Bundle cache format.** Cached bundles are stored as one zip per `(repo, base_commit)` plus a JSON file
  with the scan stats, in `bench/.cache/bundles/`. The zip is unpacked to a temporary directory on a cache hit.
  This keeps disk use and path lengths down (297 of the 300 instances have distinct snapshots).

## Known crash (not fixed)

- `sympy__sympy-24909` crashed during the full run: `rhizome/parse_python.py` (`parse_file`, `v.visit(tree)`)
  raises `RecursionError` on `sympy/polys/numberfields/resolvent_lookup.py`, a 40 KB file of deeply nested
  polynomial expressions. The recursive `ast.NodeVisitor` exceeds Python's recursion limit. By decision of the
  repository owner this was left unfixed for the benchmark (it will be addressed in a planned refactor); the
  instance is reported as crashed and excluded from the metrics, which cover 299 instances.

## Follow-up pass (stopped)

- `--rescore` re-runs only the query step on the cached bundles, to compute an exploratory
  `fusion-rrf-search` row (RRF of File-BM25 and rhizome-search) and a per-file parse-error list. It was
  stopped after 20 of 299 instances to save time; nothing from it is reported. Its rankings for the
  original methods matched the saved top-10 lists exactly on those 20 instances.

## v0.2: change #2 (query analysis) removed

- #2 removed before the v0.2 freeze and before any Loc-Bench run. Reason: BM25F (#1) already weights
  path and symbol names; #2's weaker hints (module, exception, symbol names) could take entry slots ahead
  of the best text match and resolved module mentions to package `__init__.py` hubs. Design decision, not
  based on benchmark results. (A 30-instance SWE-bench Lite regression check had been started on the
  branch; it was stopped before it produced any results, and none were looked at.)
- This deviates from `V02_PLAN_PROMPT.md`, which lists #2 and stays unchanged as the record of the
  original plan. The #2 commit (57cb4f5) remains in history; it was removed by a later commit, not by
  rewriting history.

## Harness bug: `git archive` dropped `export-ignore` paths (found during the Loc-Bench run)

- **Bug.** Snapshots were made with `git archive`, which drops paths marked `export-ignore` in the
  commit's `.gitattributes` (and would rewrite `export-subst` files). Found when
  `scikit-learn__scikit-learn-29130` (Loc-Bench) was excluded although its gold file
  `build_tools/update_environments_and_lock_files.py` exists at the base commit: scikit-learn marks
  `build_tools`, `benchmarks`, `asv_benchmarks`, `maint_tools` and dot-files `export-ignore`.
- **Fix.** `materialise()` still uses `git archive` for the bulk of the tree, then writes every regular file
  of the commit that the archive dropped, and every `export-subst` file, straight from the object store
  (`git cat-file`). Snapshots now equal the commit's tree (checked on the scikit-learn instance: 172 files,
  67 of them `.py`, restored).
- **Affected instances** (`bench/find_export_ignored.py`, which checks `.py` files and their parent
  directories against each base commit's attributes):
  - Loc-Bench: 61 of 560 instances in 10 repositories; only `scikit-learn__scikit-learn-29130` lost a gold
    file, the others only lost candidate files. These 61 are re-run with fresh snapshots and scans after the
    main run; their new records replace the old ones.
  - SWE-bench Lite v0.1 (committed results): 1 of 300 (`pydata/xarray`), candidates only, no gold file.
    Those results are left as they are; this note is the correction.

## Windows path limit: prowler (Loc-Bench)

- All 12 `prowler-cloud/prowler` instances failed with `FileNotFoundError`: their longest `.py` path is 228
  characters, and the bundle document `<temp>\rzl_xxxxxxxx\b\files\<path>.md` under the default temp dir
  (`C:\Users\VENKAT~1\AppData\Local\Temp`, 36 characters) exceeds Windows' 260-character limit
  (`LongPathsEnabled` is 0 on this machine). No other repository is affected, and no other instance lost a
  file during extraction.
- These 12 instances are re-run with `--tmp-root C:\rzb` (snapshots and bundles in a short directory outside
  the repository, deleted afterwards). Nothing else changes: same code, methods and parameters.
- **SWE-bench Lite check finished.** `bench/results/swebench-lite-v0.1/export_ignored.json` lists the one affected
  instance (`pydata/xarray`; candidate files only, no gold file). The committed Lite numbers are unchanged.
