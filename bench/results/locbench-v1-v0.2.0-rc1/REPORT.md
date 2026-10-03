# Rhizome on Loc-Bench V1: file-level localisation

## 1. Protocol

- **Dataset**: `czlll/Loc-Bench_V1`, split `test` (560 instances), the release named in the LocAgent README. 560 attempted, 560 evaluated, 0 excluded, 0 crashed.
- **Gold**: `.py` files in the gold `patch` (`diff --git` lines) that exist at `base_commit`.
- **Candidates**: `.py` files from `rhizome.parse_python.iter_python_files(snapshot)`; variant B = non-test files (Rhizome's `test` tag), variant A = all files.
- **Query**: the full `problem_statement`, unmodified, identical for every method.
- **Rhizome code**: `54b0e2d9fdda0a5a9a5fa913af44aa5b643f3e3a` (tag `v0.2.0-rc1`, branch `feat/v0.2-retrieval`). Every snapshot is scanned once with this code (heuristic summaries, no LLM). Each Rhizome method is ranked on the same bundle with `RetrievalConfig.v01()` (**[v0.1]**: v0.1 retrieval on a v0.2 bundle; the v0.2 scanner changes - tree-sitter fallback, re-export edges, cleaned descriptions - still apply) and with the v0.2 defaults (**[v0.2]**, `Bundle(..., repo=snapshot)`, so BM25F sees file bodies).
- **Category mapping** for `rhizome-ctx-cat`: Bug Report -> `bug`, Feature Request -> `feature`, Security Vulnerability -> `security`, Performance Issue -> `bug`. `rhizome-ctx-bug` uses `bug` for all.
- **Methods** (full rankings; Rhizome methods rank the files they return, then the rest in File-BM25 order):
  - `random` (seed 0); `file-bm25` (Okapi BM25, k1 = 1.2, b = 0.75, whole files, Rhizome's tokeniser);
  - `bm25-graph`: the top 4 File-BM25 files as entry points, then the v0.1 bug walk (dependencies to distance 2) in walk order;
  - `rhizome-search`, `rhizome-ctx-cat`, `rhizome-ctx-bug` (`Bundle.search` / `gather`); `fusion-rrf` = RRF (k = 60) of File-BM25 and `rhizome-ctx-cat`; `fusion-rrf-search` = RRF of File-BM25 and `rhizome-search`.
- **Metrics**: Acc@k = all gold files in the top k; Recall@k = fraction of gold files in the top k; MRR = 1 / rank of the first gold file. Percent except MRR. Paired exact McNemar tests on Acc@5 and Acc@10.
- **Frozen**: methods, comparisons and parameters were fixed before any Loc-Bench result; one run, no tuning.
- **Harness corrections during the run** (details in `bench/CHANGES.md`): `git archive` dropped paths marked `export-ignore`, so 61 instances in 10 repositories had incomplete candidate pools (one, `scikit-learn__scikit-learn-29130`, also lost its gold file and was wrongly excluded); the 12 `prowler-cloud/prowler` instances crashed on the Windows 260-character path limit. The snapshot code was fixed and these 73 instances were re-run with fresh snapshots and scans (prowler from a short temporary directory); their new records replace the old ones. Records with exact-tree snapshots: 73. The other 487 instances are unaffected.
- **Machine**: Windows-11-10.0.26200-SP0, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.2; started 2026-09-27T12:14:00; arguments `--variants B --out bench/runs/locbench-v01`.

## 2. Results

### Variant B (non-test files)

n = 560; mean 602 candidates; 0 instances have a gold file outside the candidates (counted as misses).

| Method | Acc@5 | Acc@10 | Recall@5 | Recall@10 | MRR |
|---|---:|---:|---:|---:|---:|
| random | 2.9 | 6.6 | 4.2 | 8.3 | 0.049 |
| file-bm25 | 61.3 | 71.1 | 65.1 | 74.6 | 0.534 |
| bm25-graph | 58.0 | 63.0 | 62.0 | 66.2 | 0.521 |
| rhizome-search [v0.1] | 52.0 | 64.1 | 56.6 | 68.6 | 0.482 |
| rhizome-ctx-cat [v0.1] | 48.2 | 56.2 | 52.5 | 60.2 | 0.457 |
| rhizome-ctx-bug [v0.1] | 47.7 | 55.2 | 51.9 | 59.2 | 0.454 |
| fusion-rrf [v0.1] | 57.9 | 71.4 | 62.5 | 75.0 | 0.540 |
| fusion-rrf-search [v0.1] | 62.5 | 73.6 | 66.7 | 77.5 | 0.560 |
| rhizome-search [v0.2] | 63.0 | 73.2 | 66.9 | 76.9 | 0.552 |
| rhizome-ctx-cat [v0.2] | 63.0 | 71.6 | 66.8 | 75.3 | 0.544 |
| rhizome-ctx-bug [v0.2] | 63.0 | 71.8 | 66.8 | 75.5 | 0.550 |
| fusion-rrf [v0.2] | 62.5 | 71.8 | 66.1 | 75.6 | 0.542 |
| fusion-rrf-search [v0.2] | 62.3 | 72.7 | 66.0 | 76.1 | 0.544 |

Paired comparisons (instances solved by only the first / only the second method, exact McNemar):

| Comparison | Acc@5 first / second / p | Acc@10 first / second / p |
|---|---|---|
| rhizome-search [v0.1] vs file-bm25 | 44 / 96 / 1.31e-05 | 47 / 86 / 0.000913 |
| rhizome-ctx-cat [v0.1] vs file-bm25 | 39 / 112 / 2.27e-09 | 34 / 117 / 7.2e-12 |
| rhizome-ctx-bug [v0.1] vs file-bm25 | 41 / 117 / 1.16e-09 | 35 / 124 / 7.16e-13 |
| fusion-rrf [v0.1] vs file-bm25 | 38 / 57 / 0.0642 | 25 / 23 / 0.885 |
| fusion-rrf-search [v0.1] vs file-bm25 | 51 / 44 / 0.538 | 38 / 24 / 0.098 |
| rhizome-search [v0.2] vs file-bm25 | 22 / 12 / 0.121 | 17 / 5 / 0.0169 |
| rhizome-ctx-cat [v0.2] vs file-bm25 | 22 / 12 / 0.121 | 15 / 12 / 0.701 |
| rhizome-ctx-bug [v0.2] vs file-bm25 | 22 / 12 / 0.121 | 15 / 11 / 0.557 |
| fusion-rrf [v0.2] vs file-bm25 | 13 / 6 / 0.167 | 10 / 6 / 0.454 |
| fusion-rrf-search [v0.2] vs file-bm25 | 10 / 4 / 0.18 | 11 / 2 / 0.0225 |
| bm25-graph vs file-bm25 | 4 / 22 / 0.000534 | 12 / 57 / 3.74e-08 |
| fusion-rrf [v0.1] vs fusion-rrf-search [v0.1] | 32 / 58 / 0.00805 | 24 / 36 / 0.155 |
| rhizome-ctx-cat [v0.1] vs rhizome-ctx-bug [v0.1] | 8 / 5 / 0.581 | 16 / 10 / 0.327 |
| fusion-rrf [v0.2] vs fusion-rrf-search [v0.2] | 3 / 2 / 1 | 0 / 5 / 0.0625 |
| rhizome-ctx-cat [v0.2] vs rhizome-ctx-bug [v0.2] | 0 / 0 / 1 | 0 / 1 / 1 |
| rhizome-search [v0.2] vs rhizome-search [v0.1] | 97 / 35 / 6.36e-08 | 87 / 36 / 4.85e-06 |
| rhizome-ctx-cat [v0.2] vs rhizome-ctx-cat [v0.1] | 117 / 34 / 7.2e-12 | 118 / 32 / 8.84e-13 |
| rhizome-ctx-bug [v0.2] vs rhizome-ctx-bug [v0.1] | 122 / 36 / 3.88e-12 | 125 / 32 / 3.46e-14 |
| fusion-rrf [v0.2] vs fusion-rrf [v0.1] | 62 / 36 / 0.0112 | 27 / 25 / 0.89 |
| fusion-rrf-search [v0.2] vs fusion-rrf-search [v0.1] | 44 / 45 / 1 | 26 / 31 / 0.597 |

#### By category (Acc@5 / Acc@10)

| Method | Bug Report (n = 242) | Feature Request (n = 150) | Performance Issue (n = 139) | Security Vulnerability (n = 29) |
|---|---:|---:|---:|---:|
| random | 2.5 / 4.1 | 2.0 / 3.3 | 3.6 / 10.1 | 6.9 / 27.6 |
| file-bm25 | 66.5 / 74.8 | 65.3 / 72.7 | 46.8 / 61.2 | 65.5 / 79.3 |
| bm25-graph | 62.4 / 66.1 | 62.7 / 64.7 | 44.6 / 54.7 | 62.1 / 69.0 |
| rhizome-search [v0.1] | 59.5 / 71.9 | 46.0 / 56.7 | 45.3 / 58.3 | 51.7 / 65.5 |
| rhizome-ctx-cat [v0.1] | 57.0 / 62.4 | 44.7 / 52.0 | 36.7 / 48.9 | 48.3 / 62.1 |
| rhizome-ctx-bug [v0.1] | 57.0 / 62.4 | 43.3 / 49.3 | 36.7 / 48.9 | 44.8 / 55.2 |
| fusion-rrf [v0.1] | 65.3 / 74.8 | 58.7 / 73.3 | 43.9 / 62.6 | 58.6 / 75.9 |
| fusion-rrf-search [v0.1] | 69.8 / 81.0 | 58.0 / 70.0 | 54.0 / 62.6 | 65.5 / 82.8 |
| rhizome-search [v0.2] | 68.2 / 78.5 | 66.0 / 75.3 | 49.6 / 60.4 | 69.0 / 79.3 |
| rhizome-ctx-cat [v0.2] | 67.8 / 76.4 | 66.0 / 75.3 | 49.6 / 58.3 | 72.4 / 75.9 |
| rhizome-ctx-bug [v0.2] | 67.8 / 76.4 | 66.0 / 75.3 | 49.6 / 58.3 | 72.4 / 79.3 |
| fusion-rrf [v0.2] | 66.5 / 76.9 | 66.0 / 74.0 | 49.6 / 59.7 | 72.4 / 75.9 |
| fusion-rrf-search [v0.2] | 66.5 / 77.3 | 66.0 / 74.0 | 50.4 / 61.9 | 65.5 / 79.3 |

#### By number of gold files (Acc@5 / Acc@10 / Recall@10)

| Method | 1 gold file (n = 468) | 2+ gold files (n = 92) |
|---|---:|---:|
| random | 3.4 / 6.4 / 6.4 | 0.0 / 7.6 / 18.1 |
| file-bm25 | 68.2 / 76.5 / 76.5 | 26.1 / 43.5 / 65.1 |
| bm25-graph | 65.2 / 67.9 / 67.9 | 21.7 / 38.0 / 57.4 |
| rhizome-search [v0.1] | 58.8 / 70.7 / 70.7 | 17.4 / 30.4 / 58.0 |
| rhizome-ctx-cat [v0.1] | 54.9 / 61.3 / 61.3 | 14.1 / 30.4 / 54.7 |
| rhizome-ctx-bug [v0.1] | 54.1 / 60.0 / 60.0 | 15.2 / 30.4 / 54.7 |
| fusion-rrf [v0.1] | 65.2 / 76.9 / 76.9 | 20.7 / 43.5 / 65.2 |
| fusion-rrf-search [v0.1] | 69.7 / 79.9 / 79.9 | 26.1 / 41.3 / 65.3 |
| rhizome-search [v0.2] | 70.1 / 79.1 / 79.1 | 27.2 / 43.5 / 65.7 |
| rhizome-ctx-cat [v0.2] | 69.9 / 77.8 / 77.8 | 28.3 / 40.2 / 62.9 |
| rhizome-ctx-bug [v0.2] | 69.9 / 77.8 / 77.8 | 28.3 / 41.3 / 63.7 |
| fusion-rrf [v0.2] | 69.0 / 77.8 / 77.8 | 29.3 / 41.3 / 64.6 |
| fusion-rrf-search [v0.2] | 69.0 / 78.2 / 78.2 | 28.3 / 44.6 / 65.5 |

#### Multi-file instances: gold files recovered / pushed out in the top 10 vs File-BM25

| Method | Recovered (in its top 10, not File-BM25's) | Pushed out (in File-BM25's top 10, not its) | Gold files |
|---|---:|---:|---:|
| bm25-graph | 15 | 32 | 263 |
| fusion-rrf [v0.1] | 16 | 13 | 263 |
| fusion-rrf [v0.2] | 2 | 3 | 263 |
| rhizome-ctx-cat [v0.1] | 24 | 46 | 263 |
| rhizome-ctx-cat [v0.2] | 7 | 12 | 263 |

### Cost

LLM calls and tokens: 0 for every method.

| Step | Seconds |
|---|---:|
| Materialise snapshot, mean | 9.73 |
| Rhizome scan, mean / median / max (507 scans) | 19.80 / 10.40 / 177.71 |
| Load bundle, mean | 0.32 |
| Tokenise snapshot for File-BM25, mean | 1.79 |
| Whole instance, mean | 32.44 |
| Query `file-bm25` (variant B), mean | 0.0666 |
| Query `bm25-graph` (variant B), mean | 0.0003 |
| Query `rhizome-search [v0.1]` (variant B), mean | 0.0448 |
| Query `rhizome-ctx-cat [v0.1]` (variant B), mean | 0.0444 |
| Query `rhizome-ctx-bug [v0.1]` (variant B), mean | 0.0449 |
| Query `rhizome-search [v0.2]` (variant B), mean | 0.2316 |
| Query `rhizome-ctx-cat [v0.2]` (variant B), mean | 0.2091 |
| Query `rhizome-ctx-bug [v0.2]` (variant B), mean | 0.1969 |

### Counts, crashes and parse errors

- Gold files per evaluated instance (3 = 3 or more): {1: 468, 2: 40, 3: 52}.
- Excluded: 0; crashed: 0.
- `.py` files not extractable: 0; candidates without a concept: 0.
- Files `ast` could not parse: 160 distinct (repo, path). With parser `tree-sitter` imports and top-level definitions were recovered; with `failed` the file has no symbols or edges.

| Repository | Path | Parser | Error | Instances |
|---|---|---|---|---:|
| AzureAD/microsoft-authentication-library-for-python | `msal/exceptions.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 2 |
| AzureAD/microsoft-authentication-library-for-python | `msal/mex.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 2 |
| AzureAD/microsoft-authentication-library-for-python | `msal/token_cache.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 2 |
| AzureAD/microsoft-authentication-library-for-python | `setup.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 2 |
| Bears-R-Us/arkouda | `tests/deprecated/groupby_compare_strategies.py` | tree-sitter | expected an indented block after class definition on line 41 (line 43) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/compound-statement-without-trailing-newline.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 4) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/crlf-line-endings.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 1) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/mixed-spaces-tabs.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 2) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/multiple-newlines.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 5) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/python2-grammar-crlf.py` | tree-sitter | leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal integers (line 31) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/python2-grammar.py` | tree-sitter | leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal integers (line 31) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/python3.8_grammar.py` | tree-sitter | expected an indented block after function definition on line 315 (line 317) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/simple-statements-without-trailing-newline.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 1) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/examples/trailing-whitespace.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 1) | 1 |
| ShishirPatil/gorilla | `eval/eval-scripts/codebleu/parser/tree-sitter-python/test/highlight/pattern_matching.py` | tree-sitter | only single target (not tuple) can be annotated (line 48) | 1 |
| ccxt/ccxt | `examples/py/kucoin-withdraw-chain.py` | tree-sitter | invalid non-printable character U+00A0 (line 16) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/hooks/post_gen_project.py` | tree-sitter | invalid syntax (line 27) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/cli.py` | tree-sitter | invalid syntax (line 5) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/helpers.py` | tree-sitter | invalid syntax (line 2) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/logic/action.py` | tree-sitter | invalid syntax (line 2) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/logic/auth.py` | tree-sitter | invalid syntax (line 5) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/logic/schema.py` | tree-sitter | invalid syntax (line 4) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/logic/validators.py` | tree-sitter | invalid syntax (line 4) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/plugin.py` | tree-sitter | invalid syntax (line 4) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/tests/logic/test_action.py` | tree-sitter | expected '(' (line 10) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/tests/logic/test_auth.py` | tree-sitter | expected '(' (line 12) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/tests/logic/test_validators.py` | tree-sitter | invalid syntax (line 7) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/tests/test_helpers.py` | tree-sitter | invalid syntax (line 3) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/tests/test_plugin.py` | tree-sitter | invalid syntax (line 50) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/tests/test_views.py` | tree-sitter | invalid syntax (line 5) | 1 |
| ckan/ckan | `contrib/cookiecutter/ckan_extension/{{cookiecutter.project}}/ckanext/{{cookiecutter.project_shortname}}/views.py` | tree-sitter | cannot assign to set display here. Maybe you meant '==' instead of '='? (line 4) | 1 |
| cython/cython | `Doc/s5/ep2008/stupidlowercase.py` | tree-sitter | invalid syntax (line 2) | 1 |
| cython/cython | `tests/errors/e_cdef_in_py.py` | tree-sitter | invalid syntax (line 4) | 1 |
| cython/cython | `tests/errors/e_int_literals_py2.py` | tree-sitter | invalid decimal literal (line 5) | 1 |
| cython/cython | `tests/errors/e_int_literals_py3.py` | tree-sitter | invalid decimal literal (line 5) | 1 |
| cython/cython | `tests/errors/e_tuple_args_T692.py` | tree-sitter | Function parameters cannot be parenthesized (line 4) | 1 |
| django/django | `django/contrib/admin/widgets.py` | tree-sitter | invalid syntax (line 151) | 1 |
| django/django | `tests/test_runner_apps/tagged/tests_syntax_error.py` | tree-sitter | invalid decimal literal (line 11) | 32 |
| home-assistant/core | `homeassistant/components/homematicip_cloud.py` | tree-sitter | invalid syntax (line 104) | 1 |
| huggingface/transformers | `templates/adding_a_missing_tokenization_test/cookiecutter-template-{{cookiecutter.modelname}}/test_tokenization_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 20) | 15 |
| huggingface/transformers | `templates/adding_a_new_example_script/{{cookiecutter.directory_name}}/run_{{cookiecutter.example_shortcut}}.py` | tree-sitter | invalid syntax (line 21) | 15 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/__init__.py` | tree-sitter | invalid syntax (line 19) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/configuration_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 23) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/modeling_flax_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 17) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/modeling_tf_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 17) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/modeling_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 17) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/test_modeling_flax_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 16) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/test_modeling_tf_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 16) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/test_modeling_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 18) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/to_replace_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 30) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/tokenization_fast_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 17) | 5 |
| huggingface/transformers | `templates/adding_a_new_model/cookiecutter-template-{{cookiecutter.modelname}}/tokenization_{{cookiecutter.lowercase_modelname}}.py` | tree-sitter | invalid syntax (line 17) | 5 |
| internetarchive/openlibrary | `scripts/2009/01/dbmirror.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 28) | 1 |
| internetarchive/openlibrary | `scripts/2009/01/dumps/jsondump.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 73) | 1 |
| internetarchive/openlibrary | `scripts/2009/01/index.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 89) | 1 |
| internetarchive/openlibrary | `scripts/2009/01/olpc/make.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 4) | 1 |
| internetarchive/openlibrary | `scripts/2009/01/scod_stats/get_scan_records.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 45) | 1 |
| internetarchive/openlibrary | `scripts/2009/01/scod_stats/make_report.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 32) | 1 |
| internetarchive/openlibrary | `scripts/2009/04/add_language.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 28) | 1 |
| internetarchive/openlibrary | `scripts/2009/04/add_oclc.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 70) | 1 |
| internetarchive/openlibrary | `scripts/2009/04/check_scribe_vol.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 38) | 1 |
| internetarchive/openlibrary | `scripts/2009/05/Abraham_ibn_Daud.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 21) | 1 |
| internetarchive/openlibrary | `scripts/2009/07/auto.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 27) | 1 |
| internetarchive/openlibrary | `scripts/2009/07/tarindex.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 10) | 1 |
| internetarchive/openlibrary | `scripts/2009/07/tarsplit.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 17) | 1 |
| internetarchive/openlibrary | `scripts/2009/07/thumbnail.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 43) | 1 |
| internetarchive/openlibrary | `scripts/2009/09/link_scan_records.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 37) | 1 |
| internetarchive/openlibrary | `scripts/2009/09/link_volumes.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 51) | 1 |
| internetarchive/openlibrary | `scripts/2009/10/couchload.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 29) | 1 |
| internetarchive/openlibrary | `scripts/2009/10/dbstats.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 40) | 1 |
| internetarchive/openlibrary | `scripts/2009/11/fetch.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 69) | 1 |
| internetarchive/openlibrary | `scripts/2009/12/find_dark.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 11) | 1 |
| internetarchive/openlibrary | `scripts/2009/12/load.py` | tree-sitter | (unicode error) 'unicodeescape' codec can't decode bytes in position 0-1: malformed \N character escape (line 129) | 1 |
| internetarchive/openlibrary | `scripts/2009/12/updatestats.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 16) | 1 |
| internetarchive/openlibrary | `scripts/2010/01/report_errors.py` | tree-sitter | Lambda expression parameters cannot be parenthesized (line 43) | 1 |
| internetarchive/openlibrary | `scripts/2010/02/fix_records.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 18) | 1 |
| internetarchive/openlibrary | `scripts/2010/03/makedump.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 9) | 1 |
| internetarchive/openlibrary | `scripts/2010/03/olload.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 52) | 1 |
| internetarchive/openlibrary | `scripts/2010/04/add_to_editions.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 71) | 1 |
| internetarchive/openlibrary | `scripts/2010/04/changes_dump.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 45) | 1 |
| internetarchive/openlibrary | `scripts/2010/04/fix_dups.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 24) | 1 |
| internetarchive/openlibrary | `scripts/2010/04/reindex.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 124) | 1 |
| internetarchive/openlibrary | `scripts/2010/04/update_docs.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 43) | 1 |
| internetarchive/openlibrary | `scripts/2010/05/load_print_disabled.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 52) | 1 |
| internetarchive/openlibrary | `scripts/2010/07/jsontest.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 18) | 1 |
| internetarchive/openlibrary | `scripts/2010/07/mark-templates.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 27) | 1 |
| internetarchive/openlibrary | `scripts/2010/08/gen_cover_mapping.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 25) | 1 |
| internetarchive/openlibrary | `scripts/2010/08/infobase_couchdb_replay.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 26) | 1 |
| internetarchive/openlibrary | `scripts/2010/10/analytics/crunch_logs.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 125) | 1 |
| internetarchive/openlibrary | `scripts/2010/10/analytics/make_plot.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 49) | 1 |
| internetarchive/openlibrary | `scripts/2010/10/lendable_books.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 59) | 1 |
| internetarchive/openlibrary | `scripts/2010/12/compare_subject_works.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 54) | 1 |
| internetarchive/openlibrary | `scripts/2011/02/loan_status.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 33) | 1 |
| internetarchive/openlibrary | `scripts/2011/03/get_titles.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 8) | 1 |
| internetarchive/openlibrary | `scripts/2011/03/oldump.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 110) | 1 |
| internetarchive/openlibrary | `scripts/2011/03/titles_from_couch.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 35) | 1 |
| internetarchive/openlibrary | `scripts/2011/04/reindex_transactions.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 62) | 1 |
| internetarchive/openlibrary | `scripts/2011/04/smashwords.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 64) | 1 |
| internetarchive/openlibrary | `scripts/2011/04/smashwords_load.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 39) | 1 |
| internetarchive/openlibrary | `scripts/2011/04/solr_author_merge.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 44) | 1 |
| internetarchive/openlibrary | `scripts/2011/04/test_olcompress.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 28) | 1 |
| internetarchive/openlibrary | `scripts/2011/08/expire_accounts.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 11) | 1 |
| internetarchive/openlibrary | `scripts/2011/08/inspect-memcache.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 16) | 1 |
| internetarchive/openlibrary | `scripts/2011/08/memcache-size.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 38) | 1 |
| internetarchive/openlibrary | `scripts/2011/08/oldoc.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 28) | 1 |
| internetarchive/openlibrary | `scripts/2011/09/generate_deworks.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 187) | 1 |
| internetarchive/openlibrary | `scripts/2011/12/detect-bad-author-merge.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 45) | 1 |
| internetarchive/openlibrary | `scripts/2011/12/solr_update.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 63) | 1 |
| internetarchive/openlibrary | `scripts/2012/01/undo-author-merge.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 31) | 1 |
| internetarchive/openlibrary | `scripts/2012/dump-ia-items.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 42) | 1 |
| internetarchive/openlibrary | `scripts/2013/find-indexed-works.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 38) | 1 |
| kedro-org/kedro | `features/steps/test_starter/{{ cookiecutter.repo_name }}/docs/source/conf.py` | tree-sitter | invalid syntax (line 20) | 2 |
| kedro-org/kedro | `kedro/templates/project/{{ cookiecutter.repo_name }}/docs/source/conf.py` | tree-sitter | invalid syntax (line 24) | 2 |
| nautobot/nautobot | `nautobot/extras/tests/git_data/02-invalid-files/jobs/__init__.py` | tree-sitter | invalid syntax (line 1) | 2 |
| nautobot/nautobot | `nautobot/extras/tests/git_data/02-invalid-files/jobs/syntaxerror.py` | tree-sitter | '(' was never closed (line 1) | 2 |
| numba/numba | `docs/source/extending/template.py` | tree-sitter | invalid syntax (line 6) | 1 |
| numpy/numpy | `numpy/linalg/lapack_lite/make_lite.py` | tree-sitter | invalid syntax (line 84) | 1 |
| oppia/oppia | `scripts/linters/test_files/invalid_merge_conflict.py` | tree-sitter | invalid syntax (line 23) | 1 |
| oppia/oppia | `scripts/linters/test_files/invalid_tabs.py` | tree-sitter | inconsistent use of tabs and spaces in indentation (line 39) | 1 |
| pyca/pyopenssl | `examples/proxy.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 19) | 1 |
| pyca/pyopenssl | `examples/sni/client.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 16) | 1 |
| pyca/pyopenssl | `examples/sni/server.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 32) | 1 |
| pyca/pyopenssl | `leakcheck/context-info-callback.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 61) | 1 |
| pyca/pyopenssl | `leakcheck/context-passphrase-callback.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 23) | 1 |
| pyca/pyopenssl | `leakcheck/context-verify-callback.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 61) | 1 |
| pyca/pyopenssl | `leakcheck/crypto.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 173) | 1 |
| pyca/pyopenssl | `leakcheck/thread-crash.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 21) | 1 |
| pylint-dev/pylint | `doc/data/messages/s/syntax-error/bad.py` | tree-sitter | invalid syntax. Perhaps you forgot a comma? (line 3) | 1 |
| pylint-dev/pylint | `tests/functional/s/syntax/syntax_error.py` | tree-sitter | invalid syntax (line 1) | 1 |
| pylint-dev/pylint | `tests/functional/s/syntax/syntax_error_jython.py` | tree-sitter | expected '(' (line 1) | 1 |
| pylint-dev/pylint | `tests/functional/t/tokenize_error.py` | tree-sitter | unexpected EOF while parsing (line 4) | 1 |
| pylint-dev/pylint | `tests/functional/t/tokenize_error_jython.py` | tree-sitter | unexpected EOF while parsing (line 7) | 1 |
| pylint-dev/pylint | `tests/functional/t/tokenize_error_py312.py` | tree-sitter | unexpected EOF while parsing (line 4) | 1 |
| pylint-dev/pylint | `tests/functional/u/unknown_encoding_jython.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 1 |
| pylint-dev/pylint | `tests/input/func_w0122_py_30.py` | tree-sitter | Missing parentheses in call to 'exec'. Did you mean exec(...)? (line 5) | 1 |
| pylint-dev/pylint | `tests/regrtest_data/bad_package/__init__.py` | tree-sitter | invalid syntax (line 2) | 1 |
| pylint-dev/pylint | `tests/regrtest_data/descriptor_crash.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 20) | 1 |
| pylint-dev/pylint | `tests/regrtest_data/syntax_error.py` | tree-sitter | invalid syntax (line 1) | 1 |
| python/cpython | `Lib/test/bad_coding2.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 1 |
| python/cpython | `Lib/test/badsyntax_3131.py` | tree-sitter | invalid character '€' (U+20AC) (line 2) | 1 |
| python/cpython | `Lib/test/badsyntax_future3.py` | tree-sitter | future feature rested_snopes is not defined (line 3) | 1 |
| python/cpython | `Lib/test/badsyntax_future8.py` | tree-sitter | future feature * is not defined (line 3) | 1 |
| python/cpython | `Lib/test/badsyntax_future9.py` | tree-sitter | not a chance (line 3) | 1 |
| python/cpython | `Lib/test/test_lib2to3/data/bom.py` | tree-sitter | invalid non-printable character U+FEFF (line 1) | 1 |
| python/cpython | `Lib/test/test_lib2to3/data/crlf.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 1) | 1 |
| python/cpython | `Lib/test/test_lib2to3/data/different_encoding.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 3) | 1 |
| python/cpython | `Lib/test/test_lib2to3/data/false_encoding.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 2) | 1 |
| python/cpython | `Lib/test/test_lib2to3/data/py2_test_grammar.py` | tree-sitter | leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal integers (line 31) | 1 |
| python/cpython | `Tools/c-analyzer/c_parser/parser/_delim.py` | tree-sitter | f-string: valid expression required before '}' (line 23) | 1 |
| ray-project/ray | `python/ray/serve/tests/test_config_files/syntax_error.py` | tree-sitter | '(' was never closed (line 2) | 13 |
| scikit-learn/scikit-learn | `doc/tutorial/machine_learning_map/parse_path.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 164) | 1 |
| scikit-learn/scikit-learn | `doc/tutorial/machine_learning_map/pyparsing.py` | tree-sitter | invalid syntax (line 151) | 1 |
| scikit-learn/scikit-learn | `doc/tutorial/machine_learning_map/svg2imagemap.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 73) | 1 |
| scipy/scipy | `doc/source/conf.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 62) | 1 |
| scipy/scipy | `doc/source/tutorial/examples/newton_krylov_preconditioning.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 75) | 1 |
| scipy/scipy | `tools/osx/build.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 25) | 1 |
| scipy/scipy | `tools/osx/install_and_test.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 16) | 1 |
| scipy/scipy | `tools/win32/build_scripts/pavement.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 244) | 1 |
| scipy/scipy | `tools/win32/detect_cpu_extensions_wine.py` | tree-sitter | Missing parentheses in call to 'print'. Did you mean print(...)? (line 71) | 1 |
| streamlit/streamlit | `e2e_playwright/compilation_error_dialog.py` | tree-sitter | invalid syntax (line 20) | 1 |

## 3. Published results (different setups — not directly comparable)

Z. Chen et al., *LocAgent: Graph-Guided LLM Agents for Code Localization*, ACL 2025, arXiv:2503.09089. Loc-Bench, file level, Acc@5. Copied from the paper, not measured here.

| Method | Acc@5 |
|---|---:|
| BM25 | 70.72 |
| CodeRankEmbed | 77.81 |
| LocAgent (Qwen2.5-7B) | 79.20 |
| LocAgent (Claude-3.5) | 84.59 |

## 4. Verdict

**Variant B** (n = 560). "Better" / "worse" only where the exact McNemar p < 0.05.
- `rhizome-search [v0.1]` vs `file-bm25` on Acc@5: worse (52.0 vs 61.3, -9.3; 44 vs 96 discordant, p = 1.31e-05).
- `rhizome-ctx-cat [v0.1]` vs `file-bm25` on Acc@5: worse (48.2 vs 61.3, -13.0; 39 vs 112 discordant, p = 2.27e-09).
- `rhizome-ctx-bug [v0.1]` vs `file-bm25` on Acc@5: worse (47.7 vs 61.3, -13.6; 41 vs 117 discordant, p = 1.16e-09).
- `fusion-rrf [v0.1]` vs `file-bm25` on Acc@5: no significant difference (57.9 vs 61.3, -3.4; 38 vs 57 discordant, p = 0.0642).
- `fusion-rrf-search [v0.1]` vs `file-bm25` on Acc@5: no significant difference (62.5 vs 61.3, +1.2; 51 vs 44 discordant, p = 0.538).
- `rhizome-search [v0.2]` vs `file-bm25` on Acc@5: no significant difference (63.0 vs 61.3, +1.8; 22 vs 12 discordant, p = 0.121).
- `rhizome-ctx-cat [v0.2]` vs `file-bm25` on Acc@5: no significant difference (63.0 vs 61.3, +1.8; 22 vs 12 discordant, p = 0.121).
- `rhizome-ctx-bug [v0.2]` vs `file-bm25` on Acc@5: no significant difference (63.0 vs 61.3, +1.8; 22 vs 12 discordant, p = 0.121).
- `fusion-rrf [v0.2]` vs `file-bm25` on Acc@5: no significant difference (62.5 vs 61.3, +1.2; 13 vs 6 discordant, p = 0.167).
- `fusion-rrf-search [v0.2]` vs `file-bm25` on Acc@5: no significant difference (62.3 vs 61.3, +1.1; 10 vs 4 discordant, p = 0.18).
- `bm25-graph` vs `file-bm25` on Acc@5: worse (58.0 vs 61.3, -3.2; 4 vs 22 discordant, p = 0.000534).
- `bm25-graph` vs `file-bm25` on Acc@10: worse (63.0 vs 71.1, -8.0; 12 vs 57 discordant, p = 3.74e-08).
- `fusion-rrf [v0.1]` vs `fusion-rrf-search [v0.1]` on Acc@5: worse (57.9 vs 62.5, -4.6; 32 vs 58 discordant, p = 0.00805).
- `rhizome-ctx-cat [v0.1]` vs `rhizome-ctx-bug [v0.1]` on Acc@5: no significant difference (48.2 vs 47.7, +0.5; 8 vs 5 discordant, p = 0.581).
- `fusion-rrf [v0.2]` vs `fusion-rrf-search [v0.2]` on Acc@5: no significant difference (62.5 vs 62.3, +0.2; 3 vs 2 discordant, p = 1).
- `rhizome-ctx-cat [v0.2]` vs `rhizome-ctx-bug [v0.2]` on Acc@5: no significant difference (63.0 vs 63.0, +0.0; 0 vs 0 discordant, p = 1).
- `rhizome-search [v0.2]` vs `rhizome-search [v0.1]` on Acc@5: better (63.0 vs 52.0, +11.1; 97 vs 35 discordant, p = 6.36e-08).
- `rhizome-ctx-cat [v0.2]` vs `rhizome-ctx-cat [v0.1]` on Acc@5: better (63.0 vs 48.2, +14.8; 117 vs 34 discordant, p = 7.2e-12).
- `rhizome-ctx-bug [v0.2]` vs `rhizome-ctx-bug [v0.1]` on Acc@5: better (63.0 vs 47.7, +15.4; 122 vs 36 discordant, p = 3.88e-12).
- `fusion-rrf [v0.2]` vs `fusion-rrf [v0.1]` on Acc@5: better (62.5 vs 57.9, +4.6; 62 vs 36 discordant, p = 0.0112).
- `fusion-rrf-search [v0.2]` vs `fusion-rrf-search [v0.1]` on Acc@5: no significant difference (62.3 vs 62.5, -0.2; 44 vs 45 discordant, p = 1).
- Multi-file instances (92): in the top 10, `bm25-graph` recovers 15 gold files that File-BM25 misses and pushes out 32 (of 263); `fusion-rrf [v0.2]` recovers 2 and pushes out 3.
- Highest Acc@5 here: `rhizome-search [v0.2]` (63.0). Published file-level Acc@5 (different setup, not directly comparable): BM25 70.72, CodeRankEmbed 77.81, LocAgent (Claude-3.5) 84.59.

## 5. Threats to validity

- **[v0.1] is not the v0.1 system.** It is v0.1 retrieval on bundles built by the v0.2 scanner.
- **Our BM25 is not LocAgent's.** Different tokeniser and indexing; published numbers also differ in candidate handling. Only our own rows are comparable with each other.
- **Test files.** Variant B removes test files with Rhizome's path heuristic; a gold test file then counts as a miss.
- **Fallback ordering.** Rhizome methods fill the rest of the ranking in File-BM25 order.
- **Category mapping.** Performance issues use the `bug` walk; the mapping was fixed before the run.
- **Multi-file subset is small** (see the gold-file breakdown), so its differences are noisy.
- **v0.2 was designed after SWE-bench Lite, not Loc-Bench.** Loc-Bench was not looked at before the freeze.
- **Many comparisons.** p-values are not corrected for multiple testing.
- **Single run, one machine.** Timings depend on this machine and on on-demand blob fetching from GitHub.
