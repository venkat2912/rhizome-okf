"""Natural-language descriptions for concepts.

Default: deterministic summaries built from docstrings and symbol names (no network,
reproducible). Optional: an LLM writes the description (``--llm``); results are cached
by content hash so only changed files are ever re-summarized.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .parse_python import FileInfo


def heuristic_file_summary(f: FileInfo) -> str:
    if f.parse_error:
        return f"Could not be parsed: {f.parse_error}."
    if f.doc:
        s = f.doc.rstrip(".") + "."
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
    if hub.doc:
        s += f" Hub purpose: {hub.doc.rstrip('.')}."
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
