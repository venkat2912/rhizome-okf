"""Natural-language descriptions for concepts.

Default: deterministic summaries built from docstrings and symbol names (no network,
reproducible). Optional: an LLM writes the description (``--llm``); results are cached
by content hash so only changed files are ever re-summarized.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from .parse_python import FileInfo


# a reStructuredText title underline/overline: one repeated punctuation character, e.g. ~~~~ or ====
_UNDERLINE = re.compile(r"^\s*([=~\-^*#+`'\".:_])\1{2,}\s*$")


def _names_module(line: str, module: str, path: str) -> bool:
    """True if ``line`` only restates the module's name (``requests.sessions``, ``sessions.py`` …)."""
    s = line.strip().strip("`*:'\"").strip()
    if not s:
        return False
    names = {module, module.split(".")[-1] if module else "", path, path.rsplit("/", 1)[-1],
             path.rsplit("/", 1)[-1][:-3] if path.endswith(".py") else ""}
    return s in {n for n in names if n}


def clean_docstring(doc: str, module: str = "", path: str = "") -> str:
    """First meaningful paragraph of a module docstring, as one line.

    Drops title underline lines (``~~~``, ``===``, ``---``) and a leading line that only
    repeats the module name, so Requests-style headers do not become the description.
    """
    lines = [ln for ln in (doc or "").strip().splitlines() if not _UNDERLINE.match(ln)]
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and _names_module(lines[0], module, path):
        lines.pop(0)
    para = []
    for ln in lines:
        if not ln.strip():
            if para:
                break
            continue
        para.append(ln.strip())
    return " ".join(" ".join(para).split())[:240]


def description_line(f: FileInfo) -> str:
    return clean_docstring(f.doc_full, f.module, f.path) if f.doc_full else f.doc


def heuristic_file_summary(f: FileInfo) -> str:
    if f.parse_error:
        return f"Could not be parsed: {f.parse_error}."
    doc = description_line(f)
    if doc:
        s = doc.rstrip(".") + "."
        return s[0].upper() + s[1:]
    classes = [s.name for s in f.symbols if s.kind == "class"]
    funcs = [s.name for s in f.symbols if s.kind == "function" and not s.name.startswith("_")]
    bits = []
    if classes:
        bits.append(f"{len(classes)} class{'es' if len(classes) > 1 else ''} ({', '.join(classes[:4])}"
                    f"{', …' if len(classes) > 4 else ''})")
    if funcs:
        bits.append(f"{len(funcs)} public function{'s' if len(funcs) > 1 else ''} ({', '.join(funcs[:4])}"
                    f"{', …' if len(funcs) > 4 else ''})")
    kind = "Test module" if f.is_test else ("Package initializer" if f.is_package else "Module")
    if not bits:
        return f"{kind} with no top-level definitions."
    return f"{kind} defining " + " and ".join(bits) + "."


def heuristic_community_summary(members: list[FileInfo], hub: FileInfo, n_children: int) -> str:
    tests = sum(1 for m in members if m.is_test)
    top = [m.path for m in members[:3]]
    s = (f"{len(members)} file{'s' if len(members) != 1 else ''} centred on `{hub.path}`"
         f"{f' ({tests} test file' + ('s' if tests != 1 else '') + ')' if tests else ''}. Most central: " + ", ".join(f"`{p}`" for p in top) + ".")
    hub_doc = description_line(hub)
    if hub_doc:
        s += f" Hub purpose: {hub_doc.rstrip('.')}."
    if n_children:
        s += f" Split into {n_children} components."
    return s


class LLMSummarizer:
    """Minimal Anthropic Messages API client (stdlib only)."""

    def __init__(self, model: str | None = None):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.model = model or os.environ.get("RHIZOME_MODEL", "claude-haiku-4-5-20251001")

    def _ask(self, prompt: str, max_tokens: int = 160) -> str:
        body = json.dumps({
            "model": self.model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body, method="POST",
            headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return " ".join(b.get("text", "") for b in data.get("content", [])).strip()

    def file_summary(self, f: FileInfo, source: str) -> str:
        prompt = (
            "Describe what this source file is responsible for in ONE sentence (max 30 words). "
            "No preamble.\n\n"
            f"Path: {f.path}\n```\n{source[:12000]}\n```")
        return self._ask(prompt)

    def community_summary(self, name: str, member_lines: list[str]) -> str:
        prompt = (
            "These files form one tightly coupled subsystem of a codebase (found by community "
            "detection on the import graph). In 2 sentences, say what the subsystem does and "
            "its main responsibility. No preamble.\n\n" + "\n".join(member_lines[:60]))
        return self._ask(prompt, max_tokens=200)
