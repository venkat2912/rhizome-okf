# Rhizome

**Rhizome turns a code repository into an [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) bundle that humans can review and coding agents can navigate.**

Most code-context systems chunk source files into a vector store and retrieve the top-k most similar chunks. That loses the structure of the code: who imports whom, which files form a subsystem, which callers are exposed to a vulnerable function, and what changed when. Rhizome keeps that structure and publishes it as plain markdown files that live in git next to the code.

1. **Exact dependency graph, no LLM.** Files are parsed deterministically (Python `ast`). Import edges are resolved to repository files and weighted by how often the imported names are used.
2. **Subsystems from the Leiden algorithm.** Communities are detected on the weighted import graph with Leiden, iterated to a stable partition, so every subsystem is guaranteed to be internally connected. Large subsystems are split again into components. The discovered architecture becomes the bundle's navigation hierarchy.
3. **Published as OKF.** One concept per file, subsystem, component and requirement, with typed sections (`Depends on`, `Used by`, `Members`, …) as defined in the [OKF code profile](docs/okf-code-profile.md).
4. **Co-evolves with the code.** Scans are incremental and content-addressed. Unchanged concepts are not rewritten and keep their timestamps. Every change is recorded in `log.md`. `rhizome check` fails CI when a pull request changes code without updating its knowledge.
5. **Category-aware retrieval.** `rhizome context` reads only the published bundle and walks the graph differently for feature, bug, security and refactor tasks.

## Install

```bash
pip install -e .                  # Python 3.10+; installs networkx, igraph, leidenalg, PyYAML
pip install -e ".[treesitter]"    # optional: tree-sitter fallback for files ast cannot parse
```

## Use

```bash
rhizome scan path/to/repo                      # writes path/to/repo/.knowledge
rhizome scan path/to/repo --docs docs/reqs     # also link requirement docs to code
rhizome scan path/to/repo --llm                # LLM descriptions (ANTHROPIC_API_KEY), cached by content hash
rhizome validate path/to/repo/.knowledge       # OKF conformance: every doc typed, every link resolves
rhizome check path/to/repo                     # exit 1 if the bundle is stale (CI / pre-commit)

rhizome context path/to/repo/.knowledge "sql injection in user lookup" --category security
rhizome context path/to/repo/.knowledge "rename save_order" --category refactor --json
rhizome context path/to/repo/.knowledge "$(cat issue.txt)" --category bug --repo path/to/repo   # full-text search

rhizome stats path/to/repo                     # Leiden vs Louvain connectivity on the import graph
```

### Retrieval strategies

| Category | Walk |
|---|---|
| `feature` | Entry points → their dominant subsystem → its most central members and the entry points' dependencies |
| `bug` | Entry points → dependencies up to distance 2 → tests that exercise the entry points |
| `security` | Entry points (boosted by security and auth tags) → callers up to distance 2 (exposure paths) → flagged files in the same subsystem and flagged dependencies |
| `refactor` | Entry points → transitive reverse dependencies up to distance 3 (blast radius) |

A requirement document matched by the query contributes its *Implemented by* files as entry points.

### Retrieval in v0.2

1. **Query analysis.** Traceback frames, file paths, dotted module paths, exception names, quoted error
   messages and backticked identifiers in the task text are resolved against the bundle; exact matches
   become the first entry points (a hint matching more than three files is ignored).
2. **Field-weighted full-text search (BM25F).** With `--repo`, search covers path and symbol names
   (weight 3), descriptions and docstrings (2) and the full file body (1). Without it, search falls back
   to v0.1 metadata-only BM25 and warns.
3. **Adaptive entry points.** Text hits scoring at least half the best hit (max 4, min 1).
4. **Personalized PageRank expansion** from the entry points (restart 0.15) over the weighted import graph,
   with the category's direction weighted twice the reverse one and high fan-in hubs damped by
   `1 / log(2 + fan_in)`. Expansion score = PPR × (1 + normalised text score), top 25.
5. **Never demote.** A strong text match is never ranked below a graph-expanded file.

Every change can be switched off for ablation; `--v01` reproduces v0.1 rankings exactly:

| Flag (`rhizome context`) | Turns off |
|---|---|
| `--v01` | all of the below (v0.1 behaviour) |
| `--no-bm25f` | full-text BM25F (metadata-only BM25) |
| `--no-query-analysis` | tracebacks, paths, module and symbol names as entry points |
| `--fixed-entries` | adaptive entry points (always the top 4 hits) |
| `--allow-demote` | never-demote rule |
| `--expansion walk` | personalized PageRank (v0.1 distance walk) |
| `--no-hub-downweight` | hub down-weighting |
| `--legacy-bug-tests` | `include_tests` for `bug` (v0.1 kept tests) |

In Python: `gather(bundle, query, category, config=RetrievalConfig(...))`, with `RetrievalConfig.v01()`
for the v0.1 behaviour.

Scanner options (`rhizome scan` / `check`): `--no-parser-fallback` (no tree-sitter for files `ast`
cannot parse; install the fallback with `pip install -e ".[treesitter]"`) and `--no-reexports` (link
imports from a package only to its `__init__.py`). Scans reuse a per-file parse cache and write a
persisted search index under `.knowledge/.rhizome/`.

### CI

```yaml
- run: pip install rhizome-okf && rhizome check .
```

## Layout of a bundle

See [docs/okf-code-profile.md](docs/okf-code-profile.md). `examples/shop/.knowledge` is a complete bundle for the toy repository in `tests/conftest.py`.

## Evaluation

`eval/run_eval.py` reproduces the numbers in the paper: scan statistics, Leiden vs Louvain connectivity, and a co-change retrieval benchmark that builds the graph at a past snapshot and scores each method against later real commits.

```bash
python eval/run_eval.py ../flask ../requests ../httpx ../rich ../celery --out eval/results.json
```

## Status

Proof of concept. Python only. The parser interface is small (`parse_python.py`), and other languages can be added with tree-sitter.

## Licence

Copyright © 2026 Venkat Malviya. All rights reserved. See [NOTICE](NOTICE).
