"""OKF (Open Knowledge Format v0.1) reading and writing helpers.

A bundle is a directory of markdown files with YAML frontmatter. Every concept carries
``type``; this project also uses the recommended fields (title, description, resource,
tags, timestamp) plus the code-profile extensions documented in docs/okf-code-profile.md.
Links between concepts are ordinary markdown links rooted at the bundle root.
"""
from __future__ import annotations

import os
import re

import yaml

LINK = re.compile(r"\[([^\]]+)\]\((/[^)\s]+\.md)\)")


def concept_path_for_file(src_path: str) -> str:
    return f"/files/{src_path}.md"


def link(title: str, target: str) -> str:
    return f"[{title}]({target})"


class _Dumper(yaml.SafeDumper):
    """Block-style mappings with flow-style lists, e.g. ``tags: [a, b]`` as in the OKF examples."""


_Dumper.add_representer(list, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))


def render(frontmatter: dict, body: str) -> str:
    fm = yaml.dump(frontmatter, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10_000,
                   default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def split(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4:].lstrip("\n")
    return (fm if isinstance(fm, dict) else {}), body


def sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current = "_preamble"
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("# "):
            out[current] = "\n".join(buf).strip()
            current, buf = line[2:].strip(), []
        else:
            buf.append(line)
    out[current] = "\n".join(buf).strip()
    return out


def write_if_changed(bundle: str, rel: str, content: str, dry_run: bool = False) -> bool:
    """Write ``content`` to ``bundle/rel``; return True if the file changed."""
    full = os.path.join(bundle, rel.lstrip("/"))
    try:
        with open(full, encoding="utf-8") as fh:
            if fh.read() == content:
                return False
    except FileNotFoundError:
        pass
    if not dry_run:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    return True


def iter_concepts(bundle: str):
    for dirpath, dirnames, filenames in os.walk(bundle):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.endswith(".md"):
                full = os.path.join(dirpath, fn)
                rel = "/" + os.path.relpath(full, bundle).replace(os.sep, "/")
                with open(full, encoding="utf-8") as fh:
                    yield rel, fh.read()


def validate(bundle: str) -> dict:
    """Conformance check: frontmatter with ``type`` on every document, links resolve."""
    docs = dict(iter_concepts(bundle))
    missing_type, broken = [], []
    for rel, text in docs.items():
        fm, body = split(text)
        if not fm.get("type"):
            missing_type.append(rel)
        for _, target in LINK.findall(body):
            if target not in docs:
                broken.append((rel, target))
    return {"documents": len(docs), "missing_type": missing_type, "broken_links": broken,
            "ok": not missing_type and not broken}
