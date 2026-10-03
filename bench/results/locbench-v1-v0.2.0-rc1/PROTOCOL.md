# Protocol: Loc-Bench V1 file localisation, Rhizome v0.2.0-rc1

- **Commands**: `python bench/run_locbench.py --variants B --out bench/runs/locbench-v01` (full run, 560 instances); then
  `python bench/run_locbench.py --variants B --out bench/runs/locbench-v01 --rerun bench/runs/locbench-v01/export_ignored.json`
  (61 instances whose `git archive` snapshot lacked `export-ignore` files) and
  `python bench/run_locbench.py --variants B --out bench/runs/locbench-v01 --tmp-root C:zb`
  (12 prowler instances that hit the Windows path limit); `--report-only` rebuilds the report.
  See `bench/CHANGES.md` for both harness fixes.
- **Rhizome code**: tag `v0.2.0-rc1` (commit `54b0e2d9fdda0a5a9a5fa913af44aa5b643f3e3a`, code hash `1579f1f44e`); `[v0.1]` rows are
  `RetrievalConfig.v01()` on the same v0.2-scanned bundles.
- **Dataset**: `czlll/Loc-Bench_V1`, split `test`, 560 instances, 165 repositories (named in the LocAgent README);
  read from the Hugging Face Hub parquet file with `pyarrow.parquet`.
- **Repositories**: blobless bare clones (`--filter=blob:none`) of `https://github.com/<owner>/<name>.git`.
- **Variant**: ['B'] (non-test `.py` files). **Methods**: random, file-bm25, bm25-graph, rhizome-search [v0.1], rhizome-ctx-cat [v0.1], rhizome-ctx-bug [v0.1], fusion-rrf [v0.1], fusion-rrf-search [v0.1], rhizome-search [v0.2], rhizome-ctx-cat [v0.2], rhizome-ctx-bug [v0.2], fusion-rrf [v0.2], fusion-rrf-search [v0.2].
- **Machine**: Windows-11-10.0.26200-SP0, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.2; started 2026-09-27T12:14:00.
- **Outcome**: 560 evaluated, 0 excluded, 0 crashed.
- **Files**: `REPORT.md`, `summary.json`, `per_instance.jsonl.gz` (gzip; one line per instance with gold files,
  the top 100 of every method, metrics, timings and per-file parse errors), `export_ignored.json` (the 61 re-run
  instances). Post-hoc analysis: `bench/analysis/locbench/`.
