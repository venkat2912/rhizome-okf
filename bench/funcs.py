"""Function spans and function-level gold for the v0.3 benchmark (bench-side only; not part of rhizome/).

A "function" is a top-level function or a method of a (possibly nested) class. Nested functions belong to
their enclosing function. Code outside every function is the file's ``<module>`` remainder.
"""
from __future__ import annotations

import ast
import re

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MODULE = "<module>"


def functions(text: str) -> list[tuple[str, int, int]] | None:
    """[(qualified name, first line, last line)] in source order; None if the file does not parse."""
    try:
        tree = ast.parse(text)
    except Exception:
        return None
    out = []
    stack = [("", node) for node in reversed(tree.body)]
    while stack:
        prefix, node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            out.append((prefix + node.name, first, node.end_lineno or node.lineno))
        elif isinstance(node, ast.ClassDef):
            stack.extend((prefix + node.name + ".", child) for child in reversed(node.body))
    return sorted(out, key=lambda x: x[1])


def function_at(spans: list[tuple[str, int, int]], line: int) -> str | None:
    for name, a, b in spans:
        if a <= line <= b:
            return name
    return None


def touched_old_lines(patch: str) -> dict[str, list[tuple[int, int]]]:
    """Per file: (old line, old line) pairs a change sits between or on.

    A removed line n gives (n, n). An added line inserted before old line n gives (n - 1, n): it belongs to
    a function only if both neighbours are inside that function.
    """
    out: dict[str, list[tuple[int, int]]] = {}
    path, old = None, 0
    for line in (patch or "").split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            path = m.group(1) if m else None
            old = 0
            continue
        m = HUNK.match(line)
        if m:
            old = int(m.group(1))
            continue
        if path is None or old == 0 and not line.startswith("+"):
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            out.setdefault(path, []).append((old, old))
            old += 1
        elif line.startswith("+"):
            out.setdefault(path, []).append((max(old - 1, 1), max(old, 1)))
        elif line.startswith(" ") or line == "":
            old += 1
    return out


def gold_functions(patch: str, read_file) -> tuple[list[str], list[str]]:
    """(gold function ids ``path::qualname``, files whose changes are all module-level or unparsable).

    ``read_file(path)`` returns the file's text at the base commit, or None.
    """
    gold, module_only = [], []
    for path, pairs in touched_old_lines(patch).items():
        if not path.endswith(".py"):
            continue
        text = read_file(path)
        spans = functions(text) if text is not None else None
        hit = []
        for a, b in pairs:
            fa = function_at(spans, a) if spans else None
            if fa is not None and fa == (function_at(spans, b) if spans else None):
                fid = f"{path}::{fa}"
                if fid not in hit:
                    hit.append(fid)
        gold += hit
        if not hit:
            module_only.append(path)
    return gold, module_only


def chunks(path: str, text: str) -> list[tuple[str, str]]:
    """[(``path::qualname``, source)] for every function, plus the ``<module>`` remainder if not empty."""
    spans = functions(text)
    lines = text.split("\n")
    if not spans:
        return [(f"{path}::{MODULE}", text)]
    out, used = [], [False] * (len(lines) + 2)
    for name, a, b in spans:
        out.append((f"{path}::{name}", "\n".join(lines[a - 1:b])))
        for i in range(a, min(b, len(lines)) + 1):
            used[i] = True
    rest = "\n".join(ln for i, ln in enumerate(lines, 1) if not used[i])
    if rest.strip():
        out.append((f"{path}::{MODULE}", rest))
    return out
