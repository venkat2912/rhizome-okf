# Rhizome v0.3 plan

Author: Venkat Malviya. Written 3 October 2026. Status: agreed design, nothing built yet.

Scope: Python only. The scan stays zero-LLM. Queries use no tokens by default.

## 1. Where we are

Rhizome v0.2.0-rc1 sits on branch `feat/v0.2-retrieval`. It was measured on SWE-bench Lite (300 issues, all single-file) and Loc-Bench (560 issues, up to 5 files).

| Finding | Number |
|---|---|
| v0.2 search against plain file BM25, Loc-Bench Acc@10 | 73.2% against 71.1% (p = 0.017) |
| v0.2 search against plain file BM25, Loc-Bench Acc@5 | 63.0% against 61.3% (not significant) |
| BM25 + Rhizome fusion against BM25, SWE-bench Lite | +7.0 points (p = 0.017) |
| Walking the import graph from text hits | Lowers Acc@10 (p ≈ 4e-8) |
| PageRank expansion | No gain over v0.2 search |
| Category-specific walks (bug, feature, security, refactor) | No difference |
| Multi-file issues, all gold files in top 5 | 22–29% |

What worked: BM25F text search with the name field, and the persisted index. What did not: every use of the graph for ranking.

## 2. The core weakness

**Rhizome cannot judge.** Its only measure of "is this code relevant to this issue" is counting shared words. Entry points, score bands, never-demote, PageRank and category walks are all ordering rules stacked on that one weak signal.

| Evidence (Loc-Bench analysis) | What it says |
|---|---|
| Picking perfectly from BM25's own top 35 gives 87.1% recall@10; actual is 74.6% | The right files are mostly already in the list. Nothing can pick them. |
| The graph's best case with perfect picking is 83.4% | The graph is a worse candidate source than reading further down the text list. |
| Graph candidates not already found by text: lift 0.85 against the next text results | The graph has no opinion of its own. |
| Median of 20 files score as "strong matches" | Word counting cannot separate the top 20. |
| 39.3% of PageRank mass lands on hub files | A structure-only walk drifts to popular files. |
| 59.4% of multi-file misses start from the wrong files | The start matters more than the edges. |
| Import edge is the most selective link (lift 5.7); file-level call link is 3.0 | Adding edges to the same machine would not help. |

The fix is to add the missing ability (a judge that reads code) and to change how the graph is used (as roads to walk, never as a ranker).

## 3. Final system

### 3.1 Scan time (zero LLM)

| Built at scan | Status | Notes |
|---|---|---|
| BM25F text index | Kept from v0.2 | Persisted index, parse cache, tree-sitter fallback and re-export resolution all stay. Adds function-level chunks. |
| Function map | New | Every function with its line span, body and call edges. Each call edge is marked resolved or name-only (Python's dynamic calls cannot always be resolved). |
| Entry-point index | New | Routes, CLI commands, handlers, scheduled jobs and public API, each with its user-facing words (path, name, help text, docstring). Built without the graph. |
| Fly memory (context memory) | New | See 3.3. |
| OKF bundle | Kept, extended | File pages gain function sections with "Calls" and "Called by" links. One new page type: the entry-point index. Leiden subsystems stay for navigation only. |

Functions are sections inside the file page, not separate pages, so the bundle does not grow by an order of magnitude.

### 3.2 Query time (zero tokens)

1. **Starts.** Three sources, none of them the graph:
   - BM25F hits (file and function level);
   - entry-point index matches (where the feature begins);
   - fly-memory hits (functions tied to the issue's words through their flows, tests and docs).
2. **Judged walk along calls.** From the starts, follow call edges. A local reranker model scores every function reached against the issue.
3. **Final rank.** A sort on the judge's score. A file's score is its best function's score. The call path ("A calls B") is shown as the reason.

**Walk rules**

| Rule | How it is implemented |
|---|---|
| Never use the graph to find the start | Starts come only from BM25F, the entry-point index and the memory. |
| Verify each direction | The reranker scores every function reached. |
| Drop a direction that is not useful | A low-scoring branch is not expanded. |
| Allow for glue code | The walk continues up to two hops past a low-scoring function before giving up on that direction. |
| Never block a node from a revisit | A function is reopened when a better path reaches it. |
| The graph is cyclic | A path's score fades with every hop, so going around a loop always lowers the score and the walk stops. |
| Order of expansion | Highest-scoring function next (best-first), not strict level-by-level, so the reranker is not spent on a whole level before a strong lead is followed. |
| Two ends | Walk forward from the entry point and backward from the symptom anchor (where the issue's words land). The cause usually lies where they meet. |

Starting values, to be set on the dev set and written down before the sealed test: fade 0.7 per hop, glue patience 2 hops, budget 60 judged functions, at most 8 starts.

**Fallbacks**

- Reranker not installed: return the plain BM25F ranking. The system can never do worse than v0.2 search.
- LLM judge: an off-by-default flag. Not part of this plan's results.

### 3.3 The fly memory

The fly's mushroom body spreads an input across many neurons, keeps only the few strongest, and learns by strengthening links for the one thing being learned. As an algorithm:

1. Spread the words randomly across a very large number of slots.
2. Keep the top few percent. That is the fingerprint.
3. Strengthen the link between the fingerprint and its target. Nothing else changes.

It is trained once at scan time on the whole repo, on pairs where one side is user language and the other is code:

| Pair | What the memory learns |
|---|---|
| Entry point → every function on its call path | A deep function inherits the words of the feature it serves. |
| Test → the functions it exercises | Behaviour words in test names linked to the implementing code. |
| Docstring, comment, README section → the function described | Plain-language descriptions linked to code. |
| Past fix → files changed | Added when git history exists. |

Training on each function's own words is excluded: that only reproduces text search.

Hub control: words attached to many functions count for little, and inherited words fade with call depth.

At query time the memory supplies starts and a fast "scent" score that steers the walk. It never ranks by itself.

**Condition.** The same pairs are also fed to BM25F as a plain "context" field. The fly version stays if it beats the plain one; otherwise the plain one stays. (Open decision: keep the fly version regardless.)

### 3.4 Dropped

Score bands, never-demote, PageRank ranking, category walks and hub down-weighting. They remain only behind `RetrievalConfig.v02()` for comparison.

Query analysis (#2) stays removed. The symptom anchor comes from BM25F plus the reranker.

## 4. Benchmark

**Main: SWE-rebench** (about 21,000 issue and fix pairs from over 3,400 Python repos; issue text, patch and base commit per task).

- **Filter:** drop every repo that appears in SWE-bench Lite or Loc-Bench. Keep tasks whose gold files exist at the base commit.
- **Split by repo:** a dev set for choosing settings, and a sealed test set run once at the end.
- **Gold:** files and functions touched by the patch.
- **Scores:** file Acc@k and Recall@k (k = 1, 5, 10), function recall, all-gold-in-top-10 on multi-file issues, seconds per query, tokens per query (zero).
- **Baselines:** file BM25 and v0.2 search.
- **Statistics:** paired McNemar tests, bootstrap 95% intervals, as before.

**Application subset.** The design fits programs with clear entry points; most benchmark repos are libraries and will understate it. Candidates, to be checked against SWE-rebench and mined from issue-linked merged PRs where missing:

| Repo | Entry type |
|---|---|
| saleor, zulip, netbox, paperless-ngx, pretix | Django routes and views |
| apache/superset | Flask routes |
| mealie | FastAPI routes |
| apache/airflow | Web routes plus CLI |
| httpie/cli, mitmproxy | CLI commands and event hooks |

**Later check:** Swarm Debugging (recorded breakpoints and stepped paths of developers) to compare our starts and paths with human ones. It is Java, so it waits for Java support.

## 5. Build order

| Phase | Work | Gate to continue |
|---|---|---|
| 0 | Commit Loc-Bench results and analysis to `bench/results/`. Finish the `export-ignore` check on the SWE-bench Lite results. Merge v0.2 into `main`, tag `v0.2.0`. Branch `feat/v0.3-trace`. | Clean `main` |
| 1 | Benchmark harness on SWE-rebench: filter, repo split, function-level gold, baselines | Baseline numbers on dev |
| 2 | Diagnosis test: local reranker over the BM25 top 35 on dev. No Rhizome changes. | Clear lift over BM25. If not, stop and rethink. |
| 3 | Function map, function-level BM25F, judge as final ranker | Beats v0.2 search on dev |
| 4 | Entry-point index and judged walk | Improves multi-file all-gold-in-top-10 over judge-only |
| 5 | Fly memory against the plain context field | Keep the winner. Drop both if neither helps. |
| 6 | Freeze, tag `v0.3.0-rc1`, run the sealed test once, update the paper | — |

Every change keeps an on/off switch in `RetrievalConfig`, one commit per item, tests with each.

## 6. Success criteria (fixed before any v0.3 result)

1. The judge beats file BM25 at Acc@10 on the sealed test with p < 0.05.
2. The walk adds to multi-file all-gold-in-top-10 over the judge alone.
3. A query finishes in seconds on CPU with zero tokens.

## 7. What to hope for (estimates, not results)

| Measure | Today | Hope | Basis |
|---|---|---|---|
| Gold files in top 10 (Loc-Bench recall@10) | 74.6% | 78–83% off the shelf; mid-80s if the reranker is fine-tuned on code | Estimate. The ceiling with perfect picking from the text top 35 is 87.1%. |
| Multi-file, all gold in top 5 | 22–29% | Higher, no number | The walk targets this. |
| Issues with no shared words | Unfindable | Some findable | Only through the memory. |
| Cost per query | Zero tokens, under a second | Zero tokens, seconds on CPU | — |

Target position: embedding-model level accuracy at zero token cost. LLM-agent level is out of reach without the LLM flag.

## 8. Open questions

| # | Question | How it gets answered |
|---|---|---|
| 1 | Does a local reranker lift results at all? | Phase 2 |
| 2 | Will the reranker run on the laptop, and under what licence? | Try loading one model; check the licence before depending on it |
| 3 | How many Python calls can be resolved? | Count the resolved share on two or three repos in Phase 3 |
| 4 | Can entry points be detected reliably across frameworks? | Check against a hand count on a few repos in Phase 4 |
| 5 | Fly memory or plain context field? | Phase 5 |
| 6 | Does the reranker need fine-tuning on issue and code pairs? | Decide after Phase 2; train only on dev repos |
| 7 | Is the OKF bundle itself useful to an agent? | Still untested; a separate agent-efficiency test |
| 8 | Do Leiden communities match features? | Gold-pair, co-change and directory-agreement checks on existing data |

## 9. Outside the build

- The paper needs a rewrite: the graph-ranking result was negative, and judged graph walking already exists with LLM agents. The claim shifts to the zero-LLM scan, the entry-point index, the flow-trained memory and the OKF bundle.
- Move the work to a personal machine and settle the employer approval question before anything goes public.
