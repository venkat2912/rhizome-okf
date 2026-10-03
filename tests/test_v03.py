"""Tests for the v0.3 changes (PLAN.md)."""
import os

from conftest import write_repo

from rhizome import okf
from rhizome.calls import resolve_calls
from rhizome.parse_python import iter_python_files, parse_file
from rhizome.scanner import scan

CALL_FILES = {
    "app/__init__.py": "from .core import Engine\n",
    "app/core.py": (
        "from app.util import helper, missing\nimport app.util as u\n\n"
        "class Engine:\n"
        "    def __init__(self):\n        self.n = 0\n\n"
        "    def run(self, job):\n        self.step()\n        helper(job)\n        u.fmt(job)\n"
        "        job.save()\n        self.unknown()\n        len(job)\n\n"
        "    def step(self):\n        return local()\n\n"
        "def local():\n    return 1\n"),
    "app/util.py": "def helper(x):\n    return fmt(x)\n\ndef fmt(x):\n    return str(x)\n\nclass Store:\n    def save(self):\n        pass\n",
    "main.py": "from app import Engine\n\ndef main():\n    e = Engine()\n    e.run(1)\n",
}


def _files(repo):
    return {p: parse_file(repo, p) for p in iter_python_files(repo)}


# ---------------------------------------------------------------- function map

def test_functions_have_spans_and_calls(tmp_path):
    repo = write_repo(str(tmp_path / "r"), CALL_FILES)
    f = parse_file(repo, "app/core.py")
    by = {fn.name: fn for fn in f.functions}
    assert list(by) == ["Engine.__init__", "Engine.run", "Engine.step", "local"]
    assert (by["Engine.run"].line, by["Engine.run"].end_line) == (8, 14)
    assert by["Engine.run"].calls == ["self.step", "helper", "u.fmt", "job.save", "self.unknown", "len"]


def test_calls_are_resolved_or_name_only(tmp_path):
    repo = write_repo(str(tmp_path / "r"), CALL_FILES)
    resolved, weak = resolve_calls(_files(repo))
    run = "app/core.py::Engine.run"
    # self.method, an imported name and module.func through an alias are resolved
    assert resolved[run] == ["app/core.py::Engine.step", "app/util.py::helper", "app/util.py::fmt"]
    # obj.method() is name-only (Store.save exists in the repo); self.unknown and len match nothing and are dropped
    assert weak[run] == ["save"]
    assert resolved["app/core.py::Engine.step"] == ["app/core.py::local"]
    assert resolved["app/util.py::helper"] == ["app/util.py::fmt"]
    # a class called through a package re-export resolves to its __init__ in the defining module
    assert resolved["main.py::main"] == ["app/core.py::Engine.__init__"]
    assert weak["main.py::main"] == ["run"]


def test_bundle_publishes_the_function_map(tmp_path):
    repo = write_repo(str(tmp_path / "r"), CALL_FILES)
    res = scan(repo)
    out = os.path.join(repo, ".knowledge")
    assert okf.validate(out)["ok"]
    text = open(os.path.join(out, "files/app/core.py.md"), encoding="utf-8").read()
    body = okf.sections(okf.split(text)[1])["Functions"]
    assert "- `Engine.run` (L8-L14)" in body
    assert "  - calls: [app/core.py::Engine.step](/files/app/core.py.md), [app/util.py::helper](/files/app/util.py.md)" in body
    assert "  - name-only calls: `save`" in body
    util = okf.sections(okf.split(open(os.path.join(out, "files/app/util.py.md"), encoding="utf-8").read())[1])["Functions"]
    assert "  - called by: [app/core.py::Engine.run](/files/app/core.py.md)" in util
    assert res.stats["functions"] == 8 and res.stats["calls_resolved"] == 6 and res.stats["calls_name_only"] == 2
    assert scan(repo, dry_run=True).changed == []            # deterministic and idempotent
