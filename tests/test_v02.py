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
