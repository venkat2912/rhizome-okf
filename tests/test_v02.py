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
