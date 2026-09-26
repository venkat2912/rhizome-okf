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
