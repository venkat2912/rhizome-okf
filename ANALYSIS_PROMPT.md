# Claude Code prompt — deep post-hoc analysis of the Loc-Bench results

Paste everything below the line into Claude Code, in the Rhizome repository folder.

---

You are analysing the finished **Loc-Bench** run of Rhizome (v0.1 and v0.2.0-rc1 methods, variant B) in `bench/runs/locbench-v01/` (use the actual run folder). The goal is to understand **what each retrieval component actually suggested, whether its suggestions carried real signal or were noise, and why graph expansion did not add value**.

## Ground rules

1. **Analysis only.** Do not change any retrieval method, parameter or threshold in `rhizome/`. Everything here is **exploratory, post-hoc** and must be labelled so in every output. Nothing in this analysis may be used to claim a benchmark improvement.
2. **Wait for the main run to finish** before starting. If it is still running, stop and tell me; do not compete with it for CPU or disk.
3. **Reproducibility.** Where saved results are not enough (for example, the full PageRank candidate list, entry points, strong-match band sizes, or the graph itself), recompute them **using the exact frozen commits** that produced the results (the v0.1 commit on `main` and the `v0.2.0-rc1` tag), checked out into a separate git worktree, never on the working branch. For every recomputed ranking, first verify that it matches the saved ranking (top 100) exactly; report any mismatch and exclude those instances.
4. **Disk.** Bundles were deleted after scoring. Re-scan snapshots as needed, one instance at a time, and delete each bundle once its analysis rows are written. Check free disk space first.
5. **Statistics.** Report n for every number. Use paired tests (McNemar, or Wilcoxon for ranks) and 95% bootstrap confidence intervals (10,000 resamples, seed 0) for differences. Don't call something an effect unless its interval excludes zero, and remember this is exploratory, with many comparisons.
6. Put everything under `bench/analysis/locbench/`: scripts (`.py`, no notebooks), CSV tables, PNG figures (matplotlib), and one `ANALYSIS.md`. **Do not commit** until I have reviewed it.

## Components to trace

For every instance, record the **full output** of each component (not just the final top 10):

| Component | What to record |
|---|---|
| `file-bm25` | full ranking (top 100) with scores |
| `rhizome-search` v0.1 (metadata BM25) and v0.2 (BM25F) | full ranking (top 100) with scores |
| Entry-point selection (v0.1: top 4; v0.2: adaptive) | the entry files, their scores, and the threshold used |
| **Strong-match band** (v0.2 never-demote) | how many files scored ≥ 50% of the top score; the band size |
| **PageRank candidates** (v0.2 `ctx-cat` and `ctx-bug`) | the full expanded list (up to 25) with PPR mass, text score and combined score, plus the final rank each ended up at |
| v0.1 walk (`ctx-cat`, `bm25-graph`) | every walk item with its distance, direction and reason |
| Category extras | subsystem members, related tests and security-flagged files added by the category rules |
| Final ranking of every method | top 100, as saved |

For each file, record whether it is a **gold file**, its fan-in and fan-out, whether it is a package `__init__.py`, whether it is in the same directory as a gold file, and its parser status (`ast`, `tree-sitter` or `failed`).

## Analyses

### A. Data inventory and integrity
Instances, categories, number of gold files per instance, repos; how many instances were recomputed; mismatches; parse-failure counts; whether any gold file failed to parse.

### B. Provenance: which component found each gold file
For every gold file in every instance: its rank in `file-bm25`, in `rhizome-search` v0.2, in the PageRank list and in the v0.1 walk, and whether it was an entry point. Then:
- which component **first introduced** each gold file into the final top 10 / top 20;
- how many gold files are found **only** by a graph component (not in `file-bm25`'s top 100);
- a Venn-style breakdown (BM25 only / Rhizome-search only / graph only / several).

### C. Signal vs noise for each component's candidate list
For each component's candidate list, at the depths it produces (for example, the PageRank top 5 / 10 / 25):
- **gold density** (precision) and gold recall;
- compared with **random files of the same count**, drawn from the same candidates (with a CI);
- and, most importantly, compared with the **files they would displace**: `file-bm25`'s ranks 11–35 (the same budget). If PageRank's top 25 contains more gold than BM25's next 25, the graph carries signal that the ranking rules are hiding. If it contains less, it is noise.

Report the lift (component precision ÷ baseline precision) with CIs, overall, by category, and for 1-gold vs 2+-gold instances.

### D. Complementarity and the upper bound
- The **oracle union**: recall@10 and @20 if one could perfectly pick from BM25 ∪ PageRank; how much headroom the graph offers at best.
- For the 2+-gold subset: how often a missed gold file is in PageRank's top 25 but not BM25's top 20.

### E. Why the graph did not help: failure-mode breakdown
For every 2+-gold instance, for each gold file that `file-bm25` missed in its top 10, assign **exactly one** primary reason, in this order:
1. **Bad seeds:** no gold file among the entry points, so the graph started from the wrong place.
2. **Unreachable:** the missed gold file is not connected to any entry point within 3 hops in the import graph (undirected), or is isolated, or its parse failed.
3. **Reachable, outranked:** it is reachable, but PageRank ranked it below other neighbours. Report its rank among the neighbours, the number of competing neighbours, and whether the files above it are hubs (`__init__.py`, high fan-in).
4. **Crowded out:** PageRank ranked it within its top 25, but the never-demote band pushed it beyond the final top 10. Report the band size.
5. **Other** (explain).

Show counts and percentages overall, by category, and by repository, plus the distribution of **strong-band sizes** and of **query length** (tokens) with its correlation to band size. This tests the "long issues → flat scores → too many strong matches" explanation.

### F. Graph distance diagnostics
For missed gold files: the shortest distance to the nearest *found* gold file and to the nearest entry point, in the undirected import graph, and separately along dependency direction and caller direction (1 / 2 / 3+ / unreachable). Also the degree of gold files vs non-gold neighbours, and the share of PageRank mass that lands on hub files (top 5% fan-in, or `__init__.py`).

### G. Which other kinds of link would have connected the missed files
For gold pairs (found gold → missed gold) in 2+-gold instances, check which relations hold, using **only information available at the base commit**:
- **same directory** / same package;
- **co-change history:** how often the two files changed together in the repository's commits **before** `base_commit` (use `git log` on the clone, limited to before that commit), with a baseline rate for random file pairs from the same repo;
- **name references without an import:** one file mentions a symbol, class or function name defined in the other (possible dynamic dispatch, registries, strings, inheritance through a base class);
- **shared test file:** both are imported by the same test file;
- **call relation**, if cheaply computable with `ast` (a function in one calls a name defined in the other).

Report, for each relation, the fraction of missed gold files it would have connected, against its rate among random non-gold pairs (lift). This tells us which link type v0.3 should add first.

### H. Where Rhizome-search v0.2 differs from BM25
List the instances where v0.2 search and `file-bm25` disagree about whether a gold file is in the top 5 or 10. For each, explain the cause from the field scores (name / doc / body contributions of BM25F). Does the name/symbol field help or hurt?

### I. Case studies
Pick 10 instances: 4 where a graph component **added** a gold file to the top 10, 4 where it **pushed one out**, and 2 where the missed gold file was unreachable. For each, write a short narrative: the issue (first 300 characters), the gold files, what each component suggested (top 10 with gold marked), the relevant graph paths, and the failure mode.

## Output: `ANALYSIS.md`

1. **Summary** (10 bullet points, plain language, each with its supporting number and CI).
2. Data and method (what was recomputed, the integrity check, exploratory status).
3. Sections B–I with tables and figures:
   - a precision-vs-depth curve per component against the BM25 next-ranks baseline;
   - a stacked bar of failure modes by category;
   - a histogram of strong-band sizes;
   - a distance distribution;
   - a relation-lift chart for section G.
4. **Implications for v0.3**, stated as **hypotheses to be tested on fresh data**, not as conclusions. For example: "reserve graph slots", "blend text and graph scores", "hub down-weighting", "add co-change / call / name-reference edges". Rank them by the evidence behind each.
5. Limitations (post-hoc, single benchmark, variant B only, multiple comparisons).

Before starting, show me the analysis plan, which data will be recomputed, and a time and disk estimate. Then wait for my go-ahead.
