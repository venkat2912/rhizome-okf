"""Query analysis: pull precise location hints out of a bug report.

Bug reports often name the code they are about: traceback frames, file paths, dotted module
paths, exception classes, quoted error messages and identifiers in backticks. ``analyze``
extracts these literally; ``rhizome.retrieve`` resolves them against the bundle and turns exact
matches into high-priority entry points.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FRAME = re.compile(r'File "([^"\n]+)", line (\d+)(?:, in ([A-Za-z_<>][\w<>.]*))?')
PATH = re.compile(r"(?<![\w.-])((?:[A-Za-z]:)?[\w./\\-]*?[\w-]+\.py)(?![\w])")
DOTTED = re.compile(r"(?<![\w./:-])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)(?![\w/])")
EXCEPTION = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception|Warning))\b")
# Quoted strings shorter than 8 characters ("id", 'utf-8') occur in too many files to locate anything.
QUOTED = re.compile(r'"([^"\n]{8,200})"|\'([^\'\n]{8,200})\'')
BACKTICK = re.compile(r"`([^`\n]{2,120})`")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class Frame:
    path: str
    line: int
    func: str | None


@dataclass
class QueryAnalysis:
    frames: list[Frame] = field(default_factory=list)        # in traceback order (outermost first)
    paths: list[str] = field(default_factory=list)           # `path/to/file.py` mentions outside frames
    modules: list[str] = field(default_factory=list)         # dotted names, e.g. django.db.models.query
    exceptions: list[str] = field(default_factory=list)      # exception class names
    quoted: list[str] = field(default_factory=list)          # quoted strings (error messages)
    identifiers: list[str] = field(default_factory=list)     # identifiers in backticks

    def empty(self) -> bool:
        return not (self.frames or self.paths or self.modules or self.exceptions or self.quoted
                    or self.identifiers)


def _add(seq: list, item):
    if item and item not in seq:
        seq.append(item)


def normalise_path(p: str) -> str:
    return p.replace("\\", "/").strip()


def analyze(text: str) -> QueryAnalysis:
    qa = QueryAnalysis()
    framed = set()
    for m in FRAME.finditer(text):
        path = normalise_path(m.group(1))
        qa.frames.append(Frame(path, int(m.group(2)), m.group(3)))
        framed.add(path)
    for m in PATH.finditer(text):
        p = normalise_path(m.group(1)).lstrip("./")
        if p and p not in framed and not any(f.endswith("/" + p) for f in framed):
            _add(qa.paths, p)
    for m in DOTTED.finditer(text):
        d = m.group(1)
        if not d.endswith(".py"):
            _add(qa.modules, d)
    for m in EXCEPTION.finditer(text):
        _add(qa.exceptions, m.group(1))
    for m in QUOTED.finditer(text):
        s = (m.group(1) or m.group(2)).strip()
        if len(s) >= 8 and not s.endswith(".py"):
            _add(qa.quoted, s)
    for m in BACKTICK.finditer(text):
        inner = m.group(1).strip()
        dotted = re.sub(r"\(.*\)$", "", inner)
        if re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*", dotted):
            if "." in dotted:
                _add(qa.modules, dotted)
            for part in dotted.split("."):
                if len(part) >= 3:
                    _add(qa.identifiers, part)
    return qa
