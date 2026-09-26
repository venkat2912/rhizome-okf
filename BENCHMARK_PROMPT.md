# Claude Code prompt — SWE-bench Lite file-localization benchmark for Rhizome

Paste everything below the line into Claude Code, started in the Rhizome repository folder.

---

You are working in the **Rhizome** repository (a Python tool that scans a code repo and publishes an Open Knowledge Format bundle; see `README.md`, `rhizome/retrieve.py`, `rhizome/scanner.py`). Your job is to build and run a **reproducible, honest benchmark** of Rhizome's retrieval on **SWE-bench Lite file-level localization**, and compare it with published baselines.

## Ground rules (read first, follow strictly)

1. **Do not tune Rhizome on the benchmark.** Do not change retrieval logic, weights, tokenisation or `k` values in `rhizome/` to improve scores. You may only fix genuine crashes or bugs, and every such fix must be listed in `bench/CHANGES.md` with the reason. Run the full benchmark once with a frozen protocol.
2. **Same candidates and same query for every method.** Differences in scores must come from the method, not from setup.
3. **Report honestly.** Include failures, parse errors, skipped instances and runtimes. Never invent or copy numbers into the results that you did not measure. Published numbers go in a separate, clearly labelled table with the citation.
4. Work only inside this repository (put everything new under `bench/`) and a cache folder you create (`bench/.cache/`). Do not commit the cache. Add `bench/.cache/` and `bench/runs/` to `.gitignore`.
5. This machine is Windows. Use Python for file and archive handling (not `tar`, `sed` or `grep`). Quote paths — the user profile path contains a space. Run `git config --global core.longpaths true` before cloning.
6. Before any long run, do a **smoke test with `--limit 10`** and show me the output. Ask me before starting the full run.

## Step 1 — Environment

- Use the existing virtual environment `.venv` if present; otherwise create one (`py -m venv .venv`) and activate it.
- `pip install -e ".[dev]" datasets`
- Run `pytest` and confirm all tests pass before continuing. If they fail, stop and report.

## Step 2 — Dataset

- Load `princeton-nlp/SWE-bench_Lite`, split `test` (300 instances), with `datasets.load_dataset`. Save a local copy to `bench/.cache/swe_bench_lite.jsonl` so later runs work offline.
- If Hugging Face is unreachable, stop and tell me; I will download the dataset manually.
- Fields used: `instance_id`, `repo`, `base_commit`, `problem_statement`, `patch`.
- **Gold files** = the files modified by `patch`, parsed from lines of the form `diff --git a/<path> b/<path>`. Keep only `.py` paths. Record, per instance, the number of gold files and whether any gold file was *added* (not present at `base_commit`); instances whose gold files are all absent at `base_commit` are reported separately and excluded from the accuracy calculations.

## Step 3 — Snapshots

- For each distinct `repo`, clone once into `bench/.cache/repos/<owner>__<name>` (full history is needed for `base_commit`).
- For each instance, materialise the tree at `base_commit` into a temporary directory by running `git archive --format=tar <base_commit>` and extracting it with Python's `tarfile` from the captured bytes. Delete the temporary tree after the instance is finished.
- Cache Rhizome bundles by `(repo, base_commit)` under `bench/.cache/bundles/` so identical snapshots are scanned only once.

## Step 4 — Candidates and query

- **Candidates**: every `.py` file in the snapshot, relative POSIX paths, excluding the same directories Rhizome skips (use `rhizome.parse_python.iter_python_files`).
- Run two variants and report both: **(A) all `.py` files** and **(B) non-test files only** (use Rhizome's own test detection: the `test` tag in the concept, or `FileInfo.is_test`). SWE-bench gold patches almost never touch tests, so B is the fairer variant; A is closer to how BM25 baselines are usually run.
- **Query**: the full `problem_statement`, unmodified.

## Step 5 — Methods (all produce a full ranking of candidates)

1. **Random** — seeded shuffle (seed 0), as a floor.
2. **File-BM25** — Okapi BM25 (k1 = 1.2, b = 0.75) over whole-file contents, tokenised with `rhizome.retrieve.tokens` so all methods share one tokeniser.
3. **Rhizome search** — scan the snapshot with `rhizome.scanner.scan(snapshot, out=<bundle dir outside the snapshot>)`, load `rhizome.retrieve.Bundle`, rank Source File concepts with `Bundle.search(query, k=len(candidates), types=("Source File",))`. Map concept paths back to file paths via the concept's `title`. Append any unranked candidates in File-BM25 order.
4. **Rhizome context (bug)** — `rhizome.retrieve.gather(bundle, query, "bug", include_tests=(variant == "A"))`. Ranking = the returned items in order, then remaining candidates in File-BM25 order. (SWE-bench Lite issues are mostly bug reports; use `bug` for every instance and state this in the report.)
5. **Rhizome context (refactor)** — same as 4 with category `refactor`, as a sensitivity check.
6. **Fusion** — reciprocal rank fusion (k = 60) of File-BM25 and Rhizome context (bug).
7. **Optional, only if I say yes**: an embedding baseline with `sentence-transformers` and `intfloat/e5-base-v2` (prefix `query: ` / `passage: `, first 512 tokens of each file). It downloads a model and needs a lot of CPU time — ask me first.

## Step 6 — Metrics

For each method and variant:

- **Acc@k** for k ∈ {1, 3, 5}: an instance counts as a success only if **all** gold files are in the top k (this is the definition used by LocAgent, so numbers are comparable).
- **Recall@5, Recall@10** (fraction of gold files in the top k) and **MRR** of the first gold file.
- **Cost**: wall-clock seconds per instance for scanning (first scan vs cache hit) and for querying; **LLM calls and tokens = 0** for all non-embedding methods (state it).
- A breakdown by `repo`.
- Counts of: instances evaluated, excluded (gold file absent), Rhizome parse errors per snapshot, and any crashes.

## Step 7 — Output

Create `bench/run_swebench.py` with a CLI:

```
python bench/run_swebench.py --limit 10 --variants A B --out bench/runs/<timestamp>
```

It must write:
- `per_instance.jsonl` — instance_id, repo, gold files, the top 10 of every method, per-method hit flags, timings.
- `summary.json` — all metrics above.
- `REPORT.md` containing:
  1. The protocol in a few lines (dataset, candidates, query, methods, metric definitions, Rhizome git commit hash, machine and Python version).
  2. **Our results table** (Acc@1/3/5, Recall@5/10, MRR) for each variant.
  3. A separate **"Published results (different setups — not directly comparable)"** table with these numbers, cited to *LocAgent: Graph-Guided LLM Agents for Code Localization*, Chen et al., ACL 2025, arXiv:2503.09089, file-level, SWE-bench Lite, Acc@1/3/5:
     - BM25 38.69 / 51.82 / 61.68
     - E5-base-v2 49.64 / 74.45 / 80.29
     - CodeRankEmbed 52.55 / 77.74 / 84.67
     - Agentless (Claude-3.5) 72.63 / 79.20 / 79.56
     - OpenHands (Claude-3.5) 76.28 / 89.78 / 90.15
     - LocAgent (Claude-3.5) 77.74 / 91.97 / 94.16
  4. A plain-language **verdict**: where Rhizome lands relative to our own File-BM25 and to the published BM25 and embedding baselines; whether the graph expansion helps or hurts over Rhizome search alone; the cost per instance. Do not overclaim. If Rhizome does not beat a baseline, say so directly.
  5. Threats to validity (our BM25 vs theirs, test-file handling, excluded instances, single run).

## Step 8 — Run

1. Smoke test: `--limit 10`, both variants. Show me the summary table and any errors. Wait for my go-ahead.
2. Full run: all 300 instances, both variants. Resume safely if interrupted (skip instances already present in `per_instance.jsonl`).
3. Show me `REPORT.md` at the end.

## Optional Step 9 — agent pre-filter experiment (only if I explicitly ask later)

Measure whether giving an LLM Rhizome's context pack (`rhizome.retrieve.context_pack`, budget 16,000 characters) instead of a plain file listing keeps localisation accuracy while reducing input tokens. This needs an API key and costs money: propose a cost cap and a 30-instance sample first, and do not start without my approval.
