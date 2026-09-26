# Protocol: SWE-bench Lite file localisation, Rhizome v0.1

- **Command**: `python bench/run_swebench.py --variants A B --out bench/runs/full` (full run, 300 instances), then
  `python bench/run_swebench.py --out bench/runs/full --report-only` to rebuild `summary.json` and `REPORT.md`
  from the saved per-instance results (no re-run).
- **Rhizome commit**: `f35f2d3d90a5ae1fc9b3880977370ac8b83e9f11` (`rhizome/` identical to `c57a02f`, Rhizome v0.1.0).
- **Dataset**: `princeton-nlp/SWE-bench_Lite`, split `test`, 300 instances, read from the Hugging Face Hub file
  `data/test-00000-of-00001.parquet` with `pyarrow.parquet` (`datasets.load_dataset` is blocked on this machine
  by Windows application control; same rows).
- **Repositories**: full-history bare clones of `https://github.com/<owner>/<name>.git`; snapshots via
  `git archive --format=tar <base_commit>`.
- **Machine**: Windows-11-10.0.26200-SP0, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs
- **Python**: 3.14.2
- **Run started**: 2026-09-27T00:37:24
- **Fixed parameters**: variants ['A', 'B']; methods random, file-bm25, rhizome-search, rhizome-ctx-bug, rhizome-ctx-refactor, fusion-rrf; BM25 k1 = 1.2,
  b = 0.75; RRF k = 60; random seed 0.
- **Outcome**: 299 evaluated, 0 excluded, 1 crashed (`sympy__sympy-24909`, RecursionError in Rhizome's parser).
- **Files**: `REPORT.md` (results and verdict), `summary.json` (all metrics), `per_instance.jsonl`
  (2.3 MB, uncompressed; one line per instance with gold files, top 10 of every method, hit flags,
  timings).
