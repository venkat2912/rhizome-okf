# Claude Code prompt — commit the benchmark, then build Rhizome v0.2 on a new branch

Paste everything below the line into Claude Code, started in the Rhizome repository folder.

---

You are working in the **Rhizome** repository. There are two phases. Finish Phase 1 completely, show me the result, and wait for my go-ahead before starting Phase 2.

## General rules

- Git identity for every commit: `Venkat Malviya <venkatmalviyaa@gmail.com>`. Check `git config user.name` / `user.email` in this repo and set them locally if they differ. Do not change global git config.
- Never commit `bench/.cache/`, virtual environments, cloned benchmark repos, or large temporary files. Check `git status` and the staged file list before every commit and show it to me.
- Never force-push, never rewrite history on `main`, and do not push anything until I say so.
- Small, focused commits with clear messages. Run `pytest` before every commit; do not commit with failing tests.
- If anything is unclear or a step fails, stop and ask instead of guessing.

## Phase 1 — Finalise and commit the SWE-bench Lite results on `main`

1. **Confirm the run is complete.** `bench/runs/full/` must contain all 300 instances (299 evaluated + 1 crashed is expected) (check `per_instance.jsonl` line count and `summary.json`). If it isn't finished, stop and tell me.
2. **Final report fixes** — rebuild `REPORT.md` from the saved results, without re-running the benchmark:
   - Verdict wording: do not say a method "helps" or "hurts" unless the paired test is significant (p < 0.05); otherwise say "no significant difference" and give the numbers.
   - Do not call fusion the "best Rhizome-based method". Describe it as "a hybrid of File-BM25 and Rhizome context".
   - Add one row, clearly labelled **"Exploratory (not pre-registered, decided after seeing the results)"**: `fusion-rrf-search` = RRF (k = 60) of File-BM25 and **rhizome-search** (no graph walk). Compute it from the rankings already saved in `per_instance.jsonl`. If the top-10 lists saved there are not enough to compute it correctly, say so in the report and compute it by re-running only the query step using the cached bundles. Report Acc@1/3/5, MRR and the paired McNemar test against File-BM25 and against `fusion-rrf`.
   - Add a **"Gold files per instance"** note: all instances have exactly one gold file (SWE-bench Lite is single-file), so Acc@k equals Recall@k, and graph expansion cannot recover additional gold files on this benchmark.
   - Add a **"Crashes"** note: `sympy__sympy-24909` crashed with `RecursionError` (a Rhizome bug, fixed in v0.2 as #0); it is excluded from all numbers, so n = 299.
   - Add a **"Parse errors"** section: list the files Rhizome could not parse (path, repo, error message), grouped by cause (Python 2 syntax, intentionally broken fixtures, other). Note that these files lose all symbols and import edges.
   - Add a **"Findings and planned changes"** section with these points, stated plainly: Rhizome search alone is below File-BM25 (metadata-only index); the bug walk is below Rhizome search in variant B; the BM25+Rhizome hybrid is above File-BM25 in variant A (give p) and in the same direction in B; Lite cannot test cross-file expansion; v0.2 will address this (list the Phase 2 changes by title).
3. **Keep the results where git can see them.** `bench/runs/` is git-ignored, so copy the final artefacts to `bench/results/swebench-lite-v0.1/`:
   `REPORT.md`, `summary.json`, `per_instance.jsonl` (if it is over 20 MB, compress it to `.jsonl.gz`), and a `PROTOCOL.md` containing the exact command line, the Rhizome commit hash used, the dataset source, machine and Python version.
4. **Commit on `main`**, in this order:
   1. `bench: add SWE-bench Lite file-localisation harness` — `bench/run_swebench.py`, `bench/CHANGES.md`, `.gitignore` updates, and `BENCHMARK_PROMPT.md` if it is not yet committed.
   2. `bench: add SWE-bench Lite v0.1 results (300 instances)` — everything in `bench/results/swebench-lite-v0.1/`.
   3. `docs: add v0.2 plan prompt` — this file (`V02_PLAN_PROMPT.md`).
5. Tag the results commit: `git tag -a bench-swebench-lite-v0.1 -m "SWE-bench Lite baseline results for Rhizome v0.1"`.
6. Show me `git log --oneline -5`, `git status`, the final summary table, and the exploratory row. **Stop and wait for my go-ahead.**

## Phase 2 — Create a branch from `main` and implement v0.2

1. Make sure `main` is clean and up to date locally, then create the branch: `git checkout -b feat/v0.2-retrieval main`. All Phase 2 work happens on this branch.
2. **Ablation switches.** Every retrieval change below must be controllable by an option, so each can be switched on and off for evaluation. Add a small config object (for example `RetrievalConfig` in `rhizome/retrieve.py`) and expose it via CLI flags on `rhizome context`. The defaults are the new v0.2 behaviour, but `RetrievalConfig.v01()` must reproduce v0.1 rankings exactly. Add a test that proves this on the `shop` fixture.
3. **Do not tune anything on SWE-bench Lite.** Choose parameters from first principles and write the reason next to each one in the code. Lite is already-seen data. You may run it at the end only as a regression check, clearly labelled as such.
4. Implement in this order, **one commit per item**, each with tests:

**Quick fixes**
- **#0 RecursionError crash** — the SWE-bench run crashed on `sympy__sympy-24909` with `RecursionError: maximum recursion depth exceeded`. First find exactly where it happens (reproduce on that snapshot and read the traceback: `ast.parse`, the `_Visitor` in `parse_python.py`, `ast.walk`, YAML rendering, or elsewhere). Then:
  - make the code that recursed iterative (e.g. an explicit stack instead of recursive `NodeVisitor` calls); if the recursion is inside `ast.parse` itself, catch it;
  - wrap per-file parsing so that **any** exception in one file is recorded as a parse failure (`parser: failed`, with the error message) and never crashes the scan;
  - add a test with a very deeply nested expression (e.g. 5,000 nested additions, or nested parentheses) that previously crashed, and a test that one bad file does not stop the rest of the scan;
  - re-run the harness on `sympy__sympy-24909` only, as a regression check, and confirm it completes.
- **#6 `include_tests` bug** — `gather()` must respect `include_tests` for every category, including `bug`. Add a test.
- **#10 Description clean-up** — in `summarize.py`, drop docstring title-underline lines (`~~~`, `===`, `---`) and a leading line that only repeats the module name (e.g. `requests.sessions`), so the next meaningful line becomes the description. Add tests with a Requests-style docstring.

**Retrieval**
- **#1 Field-weighted full-text search (BM25F)** — fields: path and symbol names (weight 3), docstrings and descriptions (weight 2), full file body (weight 1). `Bundle(path, repo=None)`: when `repo` is given, read source text from the repository for the body field; when it isn't, fall back to v0.1 metadata-only search and log a warning. Keep one shared tokeniser.
- **#2 Query analysis** — new `rhizome/query.py`: extract from the bug text (a) traceback frames (`File "x.py", line N, in func`), (b) dotted module paths and `path/to/file.py` mentions, (c) exception class names, (d) quoted error strings and identifiers in backticks. Exact file and symbol matches become high-priority entry points. Unit tests with realistic traceback text.
- **#3 Adaptive entry points** — keep entries whose score is at least 50% of the top entry's score, with a maximum of 4 and a minimum of 1.
- **#4 Never-demote rule** — the final ranking keeps the text-search order for the top entries; graph-expanded files are inserted after them and can never move a stronger text match down.
- **#5 Personalized PageRank expansion** — replace the flat distance-based walk with personalized PageRank seeded on the entry points (restart probability 0.15 — the standard value; state this in the code), over the weighted undirected import graph with direction-aware weighting per category (bug: dependencies weighted higher; security and refactor: callers weighted higher). Final expansion score = PPR score × (1 + normalised text score of that file). Keep the old walk available via config for ablation.

**Parser and graph**
- **#7 Parser fallback** — when `ast.parse` fails, fall back to `tree-sitter` with `tree-sitter-python` (add as an optional extra, `pip install -e ".[treesitter]"`) to extract imports and top-level definitions. Record which parser was used per file in the concept frontmatter (`parser: ast | tree-sitter | failed`). List parse failures on the bundle's root `index.md`. If tree-sitter isn't installed, keep the current behaviour and warn once.
- **#8 Re-export resolution** — when a file imports a name from a package `__init__.py` that re-exports it from a submodule (`from .sub import X` or `X = sub.X`), add the edge to the submodule that defines `X` (keep the `__init__` edge with low weight). Tests with a small package fixture.
- **#9 Hub down-weighting** — during expansion, scale edge weights by `1 / log(2 + fan_in)` of the target, so very high fan-in files don't dominate. State the formula in the code.

**Cost**
- **#11 Parse cache** — store per-file parse results keyed by content hash in `.rhizome/parse-cache/` (or inside `state.json` if small); unchanged files are not re-parsed. Test: after a one-file change, only that file is parsed (count parse calls).
- **#12 Persisted search index** — write a compact index (`.rhizome/index.json`, or a gzip'd version) at scan time; `Bundle` loads it instead of re-reading every markdown file when it is present and up to date (check the root `source_digest`). Test that rankings are identical with and without the persisted index.

5. **Docs** — update `README.md` (new options and the ablation flags) and `docs/okf-code-profile.md` (new `parser` field and any other frontmatter additions). Bump the version to `0.2.0.dev0` in `pyproject.toml` and `rhizome/__init__.py`.
6. **Regression checks only:**
   - `pytest` passes.
   - `rhizome scan` / `validate` / `check` work on `examples/shop` and on one real repo (e.g. `requests`).
   - Run the SWE-bench Lite harness with `--limit 30` for: v0.1 config, v0.2 full config, and each change alone, as a **labelled regression check on already-seen data**. Save it to `bench/runs/v02-regression/`. Do not commit it and do not change parameters based on it.
7. Tag the frozen candidate on the branch: `git tag -a v0.2.0-rc1 -m "Rhizome v0.2 release candidate (frozen before Loc-Bench)"`.
8. Show me: `git log --oneline main..feat/v0.2-retrieval`, the test results, and the regression table. **Do not merge into `main`, do not push, and do not start Loc-Bench.** Wait for my instructions.

## Out of scope for this task

Call-graph edges, role tags, `Flow` concepts, path queries and co-change edges (planned for v0.3), Loc-Bench, and any embedding model.
