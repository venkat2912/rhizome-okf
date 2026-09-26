"""Tests for the v0.2 changes (numbered as in V02_PLAN_PROMPT.md)."""
import os

from conftest import write_repo

from rhizome import okf
from rhizome.parse_python import parse_file
from rhizome.scanner import scan


def _fm(bundle, path):
    with open(os.path.join(bundle, "files", path + ".md"), encoding="utf-8") as fh:
        return okf.split(fh.read())[0]


# ---------------------------------------------------------------- #0 RecursionError crash

def test_deeply_nested_expression_parses(tmp_path):
    # 5,000 chained additions: ast.parse accepts it, but v0.1's recursive visitor hit the recursion limit
    (tmp_path / "deep.py").write_text("x = " + " + ".join(["a"] * 5000) + "\n")
    info = parse_file(str(tmp_path), "deep.py")
    assert info.parser == "ast" and info.parse_error is None
    assert info.name_refs["a"] == 5000


def test_nested_parentheses_become_parse_failure(tmp_path):
    (tmp_path / "parens.py").write_text("x = " + "(" * 5000 + "1" + ")" * 5000 + "\n")
    info = parse_file(str(tmp_path), "parens.py")
    assert info.parser == "failed" and info.parse_error


def test_one_bad_file_does_not_stop_the_scan(tmp_path, monkeypatch):
    repo = write_repo(str(tmp_path / "repo"))
    import rhizome.parse_python as pp
    real = pp.parse_file

    def flaky(root, rel):
        if rel == "shop/db.py":
            raise RuntimeError("boom")
        return real(root, rel)

    monkeypatch.setattr(pp, "parse_file", flaky)
    res = scan(repo)
    out = os.path.join(repo, ".knowledge")
    assert res.stats["files"] == 9 and res.stats["parse_errors"] == 1
    fm = _fm(out, "shop/db.py")
    assert fm["parser"] == "failed" and "boom" in fm["parse_error"]
    assert _fm(out, "shop/api.py")["parser"] == "ast"
    assert okf.validate(out)["ok"]


# ---------------------------------------------------------------- RetrievalConfig.v01() reproduces v0.1

def _golden_bundle(tmp_path):
    from rhizome.retrieve import Bundle
    repo = write_repo(str(tmp_path / "shop_repo"))
    scan(repo, docs="docs/requirements")
    return Bundle(os.path.join(repo, ".knowledge"))


def test_v01_config_reproduces_v01_rankings(tmp_path):
    import json
    from rhizome.retrieve import RetrievalConfig, gather
    with open(os.path.join(os.path.dirname(__file__), "data", "v01_golden.json"), encoding="utf-8") as fh:
        golden = json.load(fh)
    b = _golden_bundle(tmp_path)
    cfg = RetrievalConfig.v01()
    for q, want in golden["search"].items():
        got = [[r, round(s, 6)] for r, s in b.search(q, k=50, config=cfg)]
        assert got == want, q
    for key, want in golden["gather"].items():
        cat, tests, q = key.split("|", 2)
        e, items, subs = gather(b, q, cat, include_tests=(tests == "True"), config=cfg)
        got = {"entries": e, "subs": subs, "items": [[i.rel, round(i.score, 6), i.reason] for i in items]}
        assert got == want, key


# ---------------------------------------------------------------- #6 include_tests for every category

def test_bug_category_respects_include_tests(tmp_path):
    from rhizome.retrieve import RetrievalConfig, gather
    b = _golden_bundle(tmp_path)
    q = "login handler returns wrong result"
    def paths(**kw):
        return {b.concepts[i.rel].fm["title"] for i in gather(b, q, "bug", **kw)[1]}
    assert "tests/test_api.py" not in paths(include_tests=False)
    assert "tests/test_api.py" in paths(include_tests=True)
    assert "tests/test_api.py" in paths(include_tests=False, config=RetrievalConfig.v01())


# ---------------------------------------------------------------- #10 description clean-up

REQUESTS_DOC = '''
requests.sessions
~~~~~~~~~~~~~~~~~

This module provides a Session object to manage and persist settings across
requests (cookies, auth, proxies).
'''


def test_requests_style_docstring_is_cleaned():
    from rhizome.summarize import clean_docstring
    want = ("This module provides a Session object to manage and persist settings across "
            "requests (cookies, auth, proxies).")
    assert clean_docstring(REQUESTS_DOC, "requests.sessions", "requests/sessions.py") == want
    assert clean_docstring("``sessions``\n==========\n\nSession handling.", "requests.sessions") == "Session handling."
    assert clean_docstring("Title\n-----\n\nBody text.", "pkg.mod") == "Title"          # a real title is kept
    assert clean_docstring("Database access helpers.", "shop.db") == "Database access helpers."


def test_scan_description_uses_cleaned_docstring(tmp_path):
    files = {"requests/__init__.py": "", "requests/sessions.py": f'"""{REQUESTS_DOC}"""\n\nclass Session:\n    pass\n',
             "requests/models.py": '"""\nrequests.models\n~~~~~~~~~~~~~~~\n"""\n\ndef get():\n    pass\n'}
    repo = write_repo(str(tmp_path / "r"), files)
    scan(repo)
    out = os.path.join(repo, ".knowledge")
    assert _fm(out, "requests/sessions.py")["description"].startswith("This module provides a Session object")
    assert _fm(out, "requests/models.py")["description"] == "Module defining 1 public function (get)."


# ---------------------------------------------------------------- #1 field-weighted full-text search

BODY_FILES = {
    "app/__init__.py": "",
    "app/cache.py": '"""Caching layer."""\n\ndef get(key):\n    raise LookupError("stale entry evicted twice")\n',
    "app/views.py": '"""Views."""\nfrom app.cache import get\n\ndef index():\n    return get("home")\n',
    "app/evicted.py": '"""Eviction policy."""\n\ndef run():\n    pass\n',
}


def _bundle(tmp_path, files, **kw):
    from rhizome.retrieve import Bundle
    repo = write_repo(str(tmp_path / "r"), files)
    scan(repo)
    return Bundle(os.path.join(repo, ".knowledge"), **kw), repo


def _titles(b, hits):
    return [b.concepts[r].fm["title"] for r, _ in hits]


def test_bm25f_finds_text_that_only_appears_in_the_body(tmp_path):
    from rhizome.retrieve import Bundle, RetrievalConfig
    b, repo = _bundle(tmp_path, BODY_FILES)
    assert "app/cache.py" not in _titles(b, b.search("stale entry twice", k=5))     # metadata only
    full = Bundle(b.path, repo=repo)
    assert _titles(full, full.search("stale entry twice", k=5))[0] == "app/cache.py"
    assert "app/cache.py" not in _titles(full, full.search("stale entry twice", k=5, config=RetrievalConfig.v01()))


def test_bm25f_name_field_outweighs_body(tmp_path):
    from rhizome.retrieve import Bundle
    b, repo = _bundle(tmp_path, BODY_FILES)
    full = Bundle(b.path, repo=repo)
    # "evicted" is the file name of app/evicted.py (weight 3) and a body word of app/cache.py (weight 1)
    assert _titles(full, full.search("evicted", k=5))[0] == "app/evicted.py"


def test_bm25f_without_repo_warns_and_falls_back(tmp_path, caplog):
    import logging
    b, _ = _bundle(tmp_path, BODY_FILES)
    with caplog.at_level(logging.WARNING, logger="rhizome"):
        b.search("cache", k=5)
    assert "metadata-only" in caplog.text


# ---------------------------------------------------------------- #2 query analysis

TRACEBACK = """Using `QuerySet.bulk_update()` with an F() expression fails in django.db.models.query.

Traceback (most recent call last):
  File "/home/me/proj/manage.py", line 22, in <module>
    main()
  File "/usr/lib/python3.11/site-packages/django/db/models/query.py", line 781, in bulk_update
    raise ValueError("All bulk_update() objects must have a primary key set.")
ValueError: All bulk_update() objects must have a primary key set.

See also db/models/expressions.py and C:\\work\\app\\models.py
"""


def test_analyze_traceback():
    from rhizome.query import analyze
    qa = analyze(TRACEBACK)
    assert [(f.path, f.line, f.func) for f in qa.frames] == [
        ("/home/me/proj/manage.py", 22, "<module>"),
        ("/usr/lib/python3.11/site-packages/django/db/models/query.py", 781, "bulk_update")]
    assert qa.paths == ["db/models/expressions.py", "C:/work/app/models.py"]
    assert "django.db.models.query" in qa.modules
    assert qa.exceptions == ["ValueError"]
    assert qa.quoted == ["All bulk_update() objects must have a primary key set."]
    assert qa.identifiers == ["QuerySet", "bulk_update"]


def test_analyze_plain_text_has_no_hints():
    from rhizome.query import analyze
    assert analyze("the login page is slow when many users sign in").empty()


def test_exact_matches_become_first_entry_points(tmp_path):
    from rhizome.retrieve import Bundle, RetrievalConfig, gather
    b, repo = _bundle(tmp_path, BODY_FILES)
    full = Bundle(b.path, repo=repo)
    q = ('Traceback (most recent call last):\n  File "/srv/site/app/views.py", line 5, in index\n'
         '    return get("home")\nLookupError: stale entry evicted twice')
    entries, items, _ = gather(full, q, "bug")
    assert full.concepts[entries[0]].fm["title"] == "app/views.py"               # innermost repo frame
    assert "traceback frame" in items[0].reason
    assert "app/cache.py" in [full.concepts[e].fm["title"] for e in entries]     # quoted message
    v01_items = gather(full, q, "bug", config=RetrievalConfig.v01())[1]
    assert not any("traceback" in i.reason or "quoted" in i.reason for i in v01_items)


def test_resolution_rejects_ambiguous_names(tmp_path):
    from rhizome.retrieve import Bundle
    files = {f"pkg{i}/__init__.py": "" for i in range(5)}
    files.update({f"pkg{i}/util.py": "def helper():\n    pass\n" for i in range(5)})
    b, repo = _bundle(tmp_path, files)
    assert b.resolve_symbol("helper") == []               # defined in 5 files
    assert b.resolve_path("util.py") == []                # 5 candidates
    assert len(b.resolve_path("x/y/pkg3/util.py")) == 1   # absolute path ending in a repository path
    assert len(b.resolve_module("pkg3.util.helper")) == 1
