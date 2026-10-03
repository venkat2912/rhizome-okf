"""Call edges between functions (v0.3 function map). Deterministic, no LLM.

Python calls cannot always be resolved statically, so every call is either

* **resolved**: the target function is known (a function in the same file, ``self.method`` in the same class,
  a name imported from a repository module, ``module.func`` through an import alias, or a class, which
  resolves to its ``__init__``); or
* **name-only**: only the called name is known (``obj.method()``, an inherited ``self.method()``, a name
  that comes from outside the repository). It is kept when some function in the repository has that name,
  so a consumer can follow it as a weaker link.
"""
from __future__ import annotations

from collections import defaultdict

from .graph import _longest_prefix, module_index, reexport_source
from .parse_python import FileInfo

FunctionId = tuple[str, str]      # (file path, qualified name)


def function_id(path: str, name: str) -> str:
    return f"{path}::{name}"


def resolve_calls(files: dict[str, FileInfo]):
    """Return (resolved, name_only): {caller id: [callee id]} and {caller id: [called name]} in call order."""
    idx = module_index(files)
    defs = {p: {fn.name for fn in f.functions} for p, f in files.items()}
    classes = {p: {s.name for s in f.symbols if s.kind == "class"} for p, f in files.items()}
    by_last = defaultdict(int)
    for p, names in defs.items():
        for n in names:
            by_last[n.rsplit(".", 1)[-1]] += 1

    def in_file(path: str, rest: list[str]) -> str | None:
        """``rest`` (name parts after the module) -> function id in ``path``, following a class to __init__."""
        if not rest:
            return None
        name = ".".join(rest)
        if name in defs[path]:
            return function_id(path, name)
        if len(rest) == 1 and rest[0] in classes[path]:
            init = f"{rest[0]}.__init__"
            return function_id(path, init) if init in defs[path] else None
        if files[path].is_package:                      # name re-exported by a package __init__
            src = reexport_source(files, idx, path, rest[0])
            if src and src != path:
                return in_file(src, rest)
        return None

    def dotted(full: str) -> str | None:
        mod = _longest_prefix(full, idx)
        if mod is None:
            return None
        rest = full[len(mod):].lstrip(".")
        return in_file(idx[mod], rest.split(".") if rest else [])

    resolved, name_only = {}, {}
    for path, f in files.items():
        for fn in f.functions:
            src = function_id(path, fn.name)
            cls = fn.name.rsplit(".", 1)[0] if "." in fn.name else None
            res, weak = [], []
            for call in fn.calls:
                parts = call.split(".")
                target = None
                if parts[0] in ("self", "cls") and cls and len(parts) == 2:
                    target = in_file(path, [cls, parts[1]])
                elif len(parts) == 1:
                    target = in_file(path, parts)
                    if target is None and parts[0] in f.alias_map:
                        target = dotted(f.alias_map[parts[0]])
                elif parts[0] in f.alias_map:
                    target = dotted(f.alias_map[parts[0]] + "." + ".".join(parts[1:]))
                elif parts[0] in classes[path] or parts[0] in defs[path]:
                    target = in_file(path, parts)
                if target and target != src:
                    if target not in res:
                        res.append(target)
                elif target is None and by_last.get(parts[-1]) and parts[-1] not in weak:
                    weak.append(parts[-1])
            if res:
                resolved[src] = res
            if weak:
                name_only[src] = weak
    return resolved, name_only


def call_stats(files: dict[str, FileInfo], resolved: dict, name_only: dict) -> dict:
    """Counts for the scan stats: how many calls to repository functions could be resolved."""
    r = sum(len(v) for v in resolved.values())
    w = sum(len(v) for v in name_only.values())
    return {"functions": sum(len(f.functions) for f in files.values()), "calls_resolved": r, "calls_name_only": w,
            "resolved_share": round(r / (r + w), 3) if r + w else None}
