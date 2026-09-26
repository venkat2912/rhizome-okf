"""Deterministic Python source analysis using the standard-library ``ast`` module.

Extracts, per file: module identity, top-level symbols, imports (resolved later to
repository files), name references (used to weight dependency edges) and
security-relevant call patterns. No LLM is involved at this stage.
"""
from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", ".env", "build",
    "dist", "__pycache__", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    "site-packages", ".knowledge", ".eggs", ".idea", ".vscode",
}

SECRET_NAME = re.compile(r"(password|passwd|secret|token|api_?key|private_?key)", re.I)
AUTH_WORDS = re.compile(r"(auth|login|logout|password|passwd|token|session|crypt|permission|credential|oauth|jwt|acl|secret)", re.I)


@dataclass
class Symbol:
    kind: str            # "class" | "function"
    name: str
    line: int
    doc: str = ""
    methods: list[str] = field(default_factory=list)


@dataclass
class ImportRef:
    module: str          # absolute dotted module (after relative resolution)
    names: list[str]     # imported names ("*" allowed); empty for "import a.b"
    alias: str | None    # local alias for "import a.b as x"
    line: int


@dataclass
class SecurityFinding:
    line: int
    rule: str
    severity: str        # "high" | "medium" | "info"
    detail: str


@dataclass
class FileInfo:
    path: str                        # posix path relative to repo root
    module: str                      # canonical dotted module name
    aliases: list[str]               # other dotted names this file may be imported as
    is_package: bool
    is_test: bool
    loc: int
    sha: str
    doc: str
    symbols: list[Symbol]
    imports: list[ImportRef]
    name_refs: Counter
    security: list[SecurityFinding]
    external_imports: list[str] = field(default_factory=list)
    parse_error: str | None = None
    parser: str = "ast"              # "ast" | "tree-sitter" | "failed"
    doc_full: str = ""               # whole module docstring (descriptions are cleaned from it)


def iter_python_files(root: str, exclude: list[str] | None = None):
    exclude = exclude or []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
            and not any(_match(f"{rel_dir}/{d}".lstrip("./"), p) for p in exclude)
        )
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
                if not any(_match(rel, p) for p in exclude):
                    yield rel


def _match(path: str, pattern: str) -> bool:
    pattern = pattern.rstrip("/")
    return path == pattern or path.startswith(pattern + "/")


def module_names(root: str, rel: str) -> tuple[str, list[str], bool]:
    """Return (canonical module, aliases, is_package) for a file path."""
    parts = rel[:-3].split("/")
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts = parts[:-1]
    # canonical: walk up while the parent directory is a package
    dir_parts = rel.split("/")[:-1]
    start = len(dir_parts)
    while start > 0 and os.path.exists(os.path.join(root, *dir_parts[:start], "__init__.py")):
        start -= 1
    canonical = ".".join(parts[start:]) or parts[-1] if parts else ""
    aliases = {".".join(parts)}
    if parts and parts[0] == "src":
        aliases.add(".".join(parts[1:]))
    aliases.discard(canonical)
    aliases.discard("")
    return canonical, sorted(aliases), is_pkg


def _dotted(node) -> str | None:
    # iterative: attribute chains can be arbitrarily long
    attrs = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id] + attrs[::-1])
    return ".".join(attrs[::-1]) if attrs else None


def _first_line(doc: str | None) -> str:
    if not doc:
        return ""
    doc = doc.strip().split("\n\n")[0]
    return " ".join(doc.split())[:240]


def _resolve_relative(module: str, is_pkg: bool, level: int, target: str | None) -> str:
    base = module.split(".") if module else []
    if not is_pkg:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)] if level - 1 <= len(base) else []
    if target:
        base = base + target.split(".")
    return ".".join(base)


class _Visitor(ast.NodeVisitor):
    def __init__(self, alias_map: dict[str, str]):
        self.alias_map = alias_map
        self.refs: Counter = Counter()
        self.findings: list[SecurityFinding] = []

    def run(self, tree: ast.AST):
        """Visit every node in the same pre-order as ``NodeVisitor.visit``, with an explicit stack.

        The recursive visitor needs two Python frames per nesting level, so deeply nested
        expressions (e.g. generated polynomial tables) exceed the recursion limit.
        """
        handlers = {ast.Name: self._on_name, ast.Attribute: self._on_attribute,
                    ast.Assign: self._on_assign, ast.Call: self._on_call}
        stack = [tree]
        while stack:
            node = stack.pop()
            h = handlers.get(type(node))
            if h:
                h(node)
            if type(node) is not ast.Name:   # visit_Name did not descend
                stack.extend(reversed(list(ast.iter_child_nodes(node))))

    def visit(self, node):  # kept for API compatibility; never recurses
        self.run(node)

    def _canon(self, dotted: str) -> str:
        head, _, rest = dotted.partition(".")
        head = self.alias_map.get(head, head)
        return f"{head}.{rest}" if rest else head

    def _on_name(self, node):
        self.refs[node.id] += 1

    def _on_attribute(self, node):
        self.refs[node.attr] += 1

    def _on_assign(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            val = node.value.value
            for t in node.targets:
                name = _dotted(t) or ""
                if SECRET_NAME.search(name.split(".")[-1]) and len(val) >= 8 and " " not in val:
                    self._add(node.lineno, "hardcoded-secret", "high",
                              f"string literal assigned to `{name}`")

    def _on_call(self, node):
        name = _dotted(node.func)
        if name:
            full = self._canon(name)
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            last = full.split(".")[-1]
            if full in ("eval", "exec"):
                self._add(node.lineno, "dynamic-code-exec", "high", f"`{full}()` call")
            elif full in ("os.system", "os.popen"):
                self._add(node.lineno, "shell-exec", "high", f"`{full}()` runs a shell command")
            elif full.startswith("subprocess."):
                shell = kw.get("shell")
                if isinstance(shell, ast.Constant) and shell.value is True:
                    self._add(node.lineno, "shell-exec", "high", f"`{full}(..., shell=True)`")
                else:
                    self._add(node.lineno, "process-exec", "info", f"`{full}()` spawns a process")
            elif full in ("pickle.load", "pickle.loads", "marshal.load", "marshal.loads", "dill.loads"):
                self._add(node.lineno, "unsafe-deserialization", "high", f"`{full}()`")
            elif full in ("yaml.load", "yaml.load_all") and "Loader" not in kw:
                self._add(node.lineno, "unsafe-yaml", "medium", f"`{full}()` without explicit Loader")
            elif full in ("yaml.load", "yaml.load_all"):
                loader = _dotted(kw["Loader"]) or ""
                if "Safe" not in loader:
                    self._add(node.lineno, "unsafe-yaml", "medium", f"`{full}()` with `{loader}`")
            elif full in ("hashlib.md5", "hashlib.sha1"):
                self._add(node.lineno, "weak-hash", "medium", f"`{full}()`")
            elif full == "tempfile.mktemp":
                self._add(node.lineno, "insecure-tempfile", "medium", "`tempfile.mktemp()` is race-prone")
            if last in ("execute", "executemany", "raw") and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.JoinedStr) or (
                    isinstance(a0, ast.BinOp) and isinstance(a0.op, (ast.Mod, ast.Add))
                ) or (isinstance(a0, ast.Call) and _dotted(a0.func) and _dotted(a0.func).endswith(".format")):
                    self._add(node.lineno, "sql-string-building", "high",
                              f"query passed to `.{last}()` is built by string formatting")
            v = kw.get("verify")
            if isinstance(v, ast.Constant) and v.value is False:
                self._add(node.lineno, "tls-verify-disabled", "high", f"`{name}(..., verify=False)`")

    def _add(self, line, rule, sev, detail):
        self.findings.append(SecurityFinding(line, rule, sev, detail))


# ------------------------------------------------------------------ #7 tree-sitter fallback

log = logging.getLogger("rhizome")
_TS_PARSER = None          # None: not tried yet; False: unavailable


def treesitter_parser():
    """The tree-sitter Python parser, or None if the optional extra is not installed (warned once)."""
    global _TS_PARSER
    if _TS_PARSER is None:
        try:
            import tree_sitter_python
            from tree_sitter import Language, Parser
            _TS_PARSER = Parser(Language(tree_sitter_python.language()))
        except Exception as exc:   # ImportError, or a native library that cannot be loaded
            log.warning("tree-sitter is not available (%s): files that ast cannot parse keep no imports or "
                        "symbols; install with `pip install rhizome-okf[treesitter]`", exc)
            _TS_PARSER = False
    return _TS_PARSER or None


def _ts_text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def parse_with_treesitter(info: "FileInfo", raw: bytes) -> bool:
    """Fill imports, top-level definitions and name references from tree-sitter. Returns False if unavailable.

    tree-sitter's grammar is error-tolerant, so this recovers structure from Python 2 files and from
    files with local syntax errors. Security rules are not applied to these files.
    """
    parser = treesitter_parser()
    if parser is None:
        return False
    root = parser.parse(raw).root_node
    stack = [root]
    while stack:                      # imports anywhere in the file, as with ast.walk
        node = stack.pop()
        line = node.start_point[0] + 1
        if node.type == "import_statement":
            for c in node.named_children:
                if c.type == "dotted_name":
                    info.imports.append(ImportRef(_ts_text(c), [], None, line))
                elif c.type == "aliased_import":
                    info.imports.append(ImportRef(_ts_text(c.child_by_field_name("name")), [],
                                                  _ts_text(c.child_by_field_name("alias")), line))
        elif node.type == "import_from_statement":
            mod = node.child_by_field_name("module_name")
            names = []
            for c in node.named_children:
                if c == mod:
                    continue
                if c.type == "dotted_name":
                    names.append(_ts_text(c))
                elif c.type == "aliased_import":
                    names.append(_ts_text(c.child_by_field_name("name")))
                elif c.type == "wildcard_import":
                    names.append("*")
            target = _ts_text(mod)
            if mod is not None and mod.type == "relative_import":
                dots = len(target) - len(target.lstrip("."))
                target = _resolve_relative(info.module, info.is_package, dots, target.lstrip(".") or None)
            if target:
                info.imports.append(ImportRef(target, names, None, line))
        elif node.type == "identifier":
            info.name_refs[_ts_text(node)] += 1
        stack.extend(reversed(node.children))
    for node in root.named_children:  # top-level definitions
        if node.type == "decorated_definition":
            node = node.child_by_field_name("definition") or node
        name = _ts_text(node.child_by_field_name("name"))
        if node.type == "class_definition" and name:
            body = node.child_by_field_name("body")
            methods = []
            for m in (body.named_children if body is not None else []):
                if m.type == "decorated_definition":
                    m = m.child_by_field_name("definition") or m
                mname = _ts_text(m.child_by_field_name("name"))
                if m.type == "function_definition" and not (mname.startswith("__") and mname != "__init__"):
                    methods.append(mname)
            info.symbols.append(Symbol("class", name, node.start_point[0] + 1, "", methods))
        elif node.type == "function_definition" and name:
            info.symbols.append(Symbol("function", name, node.start_point[0] + 1, ""))
    info.parser = "tree-sitter"
    return True


def parse_file(root: str, rel: str, fallback: bool = True) -> FileInfo:
    full = os.path.join(root, rel)
    with open(full, "rb") as fh:
        raw = fh.read()
    sha = "sha256:" + hashlib.sha256(raw).hexdigest()[:16]
    text = raw.decode("utf-8", errors="replace")
    module, aliases, is_pkg = module_names(root, rel)
    parts = rel.split("/")
    is_test = any(p in ("tests", "test", "testing") for p in parts[:-1]) or parts[-1].startswith("test_") \
        or parts[-1].endswith("_test.py") or parts[-1] == "conftest.py"
    loc = sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    info = FileInfo(rel, module, aliases, is_pkg, is_test, loc, sha, "", [], [], Counter(), [])
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:  # keep the file as a node even if it does not parse
        info.parse_error = f"{exc.msg} (line {exc.lineno})"
        info.parser = "failed"
    except (RecursionError, MemoryError, ValueError) as exc:  # e.g. nesting beyond the parser's limits
        info.parse_error = f"{type(exc).__name__}: {exc}"
        info.parser = "failed"
    if info.parser == "failed":
        if fallback:
            parse_with_treesitter(info, raw)
        return info

    info.doc_full = ast.get_docstring(tree) or ""
    info.doc = _first_line(info.doc_full)
    alias_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                info.imports.append(ImportRef(a.name, [], a.asname, node.lineno))
                if a.asname:
                    alias_map[a.asname] = a.name
        elif isinstance(node, ast.ImportFrom):
            target = node.module
            if node.level:
                target = _resolve_relative(module, is_pkg, node.level, node.module)
            if target:
                info.imports.append(ImportRef(target, [a.name for a in node.names], None, node.lineno))
                for a in node.names:
                    alias_map[a.asname or a.name] = f"{target}.{a.name}"

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and not (n.name.startswith("__") and n.name != "__init__")]
            info.symbols.append(Symbol("class", node.name, node.lineno,
                                       _first_line(ast.get_docstring(node)), methods))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.symbols.append(Symbol("function", node.name, node.lineno,
                                       _first_line(ast.get_docstring(node))))

    v = _Visitor(alias_map)
    v.run(tree)
    info.name_refs = v.refs
    info.security = v.findings
    return info


def failed_file(root: str, rel: str, exc: BaseException) -> FileInfo:
    """A node for a file whose analysis raised; the scan records it and carries on."""
    try:
        with open(os.path.join(root, rel), "rb") as fh:
            sha = "sha256:" + hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        sha = "sha256:unreadable"
    module, aliases, is_pkg = module_names(root, rel)
    parts = rel.split("/")
    is_test = any(p in ("tests", "test", "testing") for p in parts[:-1]) or parts[-1].startswith("test_")         or parts[-1].endswith("_test.py") or parts[-1] == "conftest.py"
    return FileInfo(rel, module, aliases, is_pkg, is_test, 0, sha, "", [], [], Counter(), [],
                    parse_error=f"{type(exc).__name__}: {exc}", parser="failed")


def safe_parse_file(root: str, rel: str, fallback: bool = True) -> FileInfo:
    """``parse_file`` that never raises: any error in one file becomes a parse failure."""
    try:
        return parse_file(root, rel, fallback)
    except Exception as exc:
        return failed_file(root, rel, exc)


def area_tags(info: FileInfo) -> list[str]:
    tags = []
    hay = info.path + " " + " ".join(s.name for s in info.symbols)
    if AUTH_WORDS.search(hay):
        tags.append("area:auth")
    return tags
