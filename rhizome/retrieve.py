"""Consumer: category-aware context retrieval over an OKF code bundle.

Reads only the published markdown bundle (never the scanner's internal state), which
demonstrates producer/consumer independence: any OKF-conformant code bundle works.

Pipeline: lexical entry points (BM25 over concept text) -> graph expansion whose shape
depends on the task category -> ranked, budgeted context pack.
"""
from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

from . import okf

log = logging.getLogger("rhizome")

STOP = set("""a an the and or of to in on for with from by is are be this that it as at into
when then than via use uses using add new fix bug make should must can will not no all any each
code file files function method class module""".split())

CATEGORIES = ("feature", "bug", "security", "refactor")


@dataclass(frozen=True)
class RetrievalConfig:
    """Switches for every v0.2 retrieval change, so each can be ablated.

    The defaults are the v0.2 behaviour; ``RetrievalConfig.v01()`` reproduces v0.1 rankings exactly.
    """
    # #1: field-weighted full-text search (BM25F) when source text is available; v0.1 indexed metadata only.
    bm25f: bool = True
    # #6: v0.1 kept test files for the `bug` category even when include_tests was False.
    respect_include_tests: bool = True

    @classmethod
    def v01(cls) -> "RetrievalConfig":
        return cls(bm25f=False, respect_include_tests=False)


# BM25F (Robertson & Zaragoza, 2009). k1 and b are the textbook defaults, not tuned.
BM25_K1, BM25_B = 1.2, 0.75
# Field weights: an identifier or path match is the most specific evidence (3); prose written about the file
# (descriptions, docstrings, tags) says what it is for but is looser (2); the full body has the most text and
# the most incidental matches (1). Chosen from these priorities, not fitted to any benchmark.
FIELD_WEIGHTS = {"name": 3.0, "doc": 2.0, "body": 1.0}
SYMBOL_NAME = re.compile(r"`(?:class |def )?([A-Za-z_][A-Za-z0-9_]*)(?:\(\))?`")
SYMBOL_DOC = re.compile(r"\(L\d+\): (.*)$", re.M)


def tokens(text: str) -> list[str]:
    raw = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", text)
    out = []
    for t in raw:
        t = t.lower()
        if len(t) < 2 or t in STOP:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


@dataclass
class Concept:
    rel: str
    fm: dict
    body: str
    sections: dict[str, str]
    links: dict[str, list[str]] = field(default_factory=dict)   # section -> [targets]

    @property
    def type(self) -> str:
        return str(self.fm.get("type", ""))


class Bundle:
    """A loaded OKF code bundle. ``repo`` (the repository root) enables full-text search over file bodies."""

    def __init__(self, path: str, repo: str | None = None):
        self.path = path
        self.repo = repo
        self.concepts: dict[str, Concept] = {}
        for rel, text in okf.iter_concepts(path):
            fm, body = okf.split(text)
            secs = okf.sections(body)
            links = {name: [t for _, t in okf.LINK.findall(content)] for name, content in secs.items()}
            self.concepts[rel] = Concept(rel, fm, body, secs, links)
        self.files = {r: c for r, c in self.concepts.items() if c.type == "Source File"}
        self._build_index()
        self._bm25f = None          # built lazily on first full-text search
        self._warned = False

    # ---- lexical index (BM25) over file and requirement concepts
    def _doc_text(self, c: Concept) -> str:
        parts = [c.fm.get("title", ""), c.fm.get("description", ""), " ".join(c.fm.get("tags", []) or [])]
        parts += [c.sections.get("Symbols", ""), c.sections.get("Text", "")[:4000]]
        return " ".join(str(p) for p in parts)

    def _build_index(self):
        self.searchable = [r for r, c in self.concepts.items() if c.type in ("Source File", "Requirement")]
        self.tf = {r: Counter(tokens(self._doc_text(self.concepts[r]))) for r in self.searchable}
        self.dl = {r: sum(v.values()) for r, v in self.tf.items()}
        self.avgdl = (sum(self.dl.values()) / len(self.dl)) if self.dl else 1.0
        df = Counter()
        for v in self.tf.values():
            df.update(v.keys())
        n = len(self.tf) or 1
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    # ---- #1 field-weighted full-text index (BM25F)
    def _fields(self, c: Concept) -> dict[str, str]:
        if c.type == "Requirement":
            return {"name": str(c.fm.get("title", "")), "doc": str(c.fm.get("description", "")),
                    "body": c.sections.get("Text", "")}
        sym = c.sections.get("Symbols", "")
        name = " ".join([str(c.fm.get("title", ""))] + SYMBOL_NAME.findall(sym))
        doc = " ".join([str(c.fm.get("description", "")), " ".join(map(str, c.fm.get("tags", []) or []))]
                       + SYMBOL_DOC.findall(sym))
        return {"name": name, "doc": doc, "body": self._source(c)}

    def _source(self, c: Concept) -> str:
        try:
            with open(os.path.join(self.repo, *str(c.fm.get("title", "")).split("/")),
                      encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    def _build_bm25f(self):
        field_tf = {r: {f: Counter(tokens(s)) for f, s in self._fields(self.concepts[r]).items()}
                    for r in self.searchable}
        avg = {f: (sum(sum(d[f].values()) for d in field_tf.values()) / len(field_tf)) or 1.0 if field_tf else 1.0
               for f in FIELD_WEIGHTS}
        post: dict[str, dict[str, float]] = defaultdict(dict)   # term -> {doc: length-normalised weighted tf}
        for r, fields in field_tf.items():
            acc: dict[str, float] = defaultdict(float)
            for f, tf in fields.items():
                norm = 1 - BM25_B + BM25_B * sum(tf.values()) / avg[f]
                for term, n in tf.items():
                    acc[term] += FIELD_WEIGHTS[f] * n / norm
            for term, v in acc.items():
                post[term][r] = v
        n = len(field_tf) or 1
        idf = {term: math.log(1 + (n - len(d) + 0.5) / (len(d) + 0.5)) for term, d in post.items()}
        self._bm25f = (post, idf)

    def full_text(self) -> bool:
        return self.repo is not None

    def search(self, query: str, k: int = 5, types: tuple[str, ...] = ("Source File", "Requirement"),
               boost=None, config: "RetrievalConfig | None" = None) -> list[tuple[str, float]]:
        cfg = config or RetrievalConfig()
        if cfg.bm25f:
            if self.full_text():
                return self._search_bm25f(query, k, types, boost)
            if not self._warned:
                log.warning("no repository given: full-text search unavailable, using metadata-only search (v0.1)")
                self._warned = True
        q = tokens(query)
        scores = {}
        for r in self.searchable:
            if self.concepts[r].type not in types:
                continue
            tf, s = self.tf[r], 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    s += self.idf.get(t, 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * self.dl[r] / self.avgdl))
            if boost:
                s *= boost(self.concepts[r])
            if s > 0:
                scores[r] = s
        return sorted(scores.items(), key=lambda x: -x[1])[:k]

    def _search_bm25f(self, query, k, types, boost) -> list[tuple[str, float]]:
        if self._bm25f is None:
            self._build_bm25f()
        post, idf = self._bm25f
        scores: dict[str, float] = defaultdict(float)
        for term in tokens(query):          # repeated query terms count again, as in v0.1
            for r, v in post.get(term, {}).items():
                scores[r] += idf[term] * v / (BM25_K1 + v)
        out = {}
        for r, s in scores.items():
            c = self.concepts[r]
            if c.type not in types:
                continue
            if boost:
                s *= boost(c)
            if s > 0:
                out[r] = s
        return sorted(out.items(), key=lambda x: (-x[1], x[0]))[:k]

    # ---- graph helpers
    def deps(self, rel: str) -> list[str]:
        return [t for t in self.concepts[rel].links.get("Depends on", []) if t in self.files]

    def users(self, rel: str) -> list[str]:
        return [t for t in self.concepts[rel].links.get("Used by", []) if t in self.files]

    def subsystem_of(self, rel: str) -> str | None:
        for t in self.concepts[rel].links.get("Subsystem", []):
            if self.concepts.get(t, None) and self.concepts[t].type == "Subsystem":
                return t
        return None

    def bfs(self, starts: list[str], step, depth: int) -> dict[str, int]:
        seen = {s: 0 for s in starts}
        dq = deque(starts)
        while dq:
            cur = dq.popleft()
            if seen[cur] >= depth:
                continue
            for nxt in step(cur):
                if nxt not in seen:
                    seen[nxt] = seen[cur] + 1
                    dq.append(nxt)
        return seen


@dataclass
class Item:
    rel: str
    score: float
    reason: str


def _is_test(c: Concept) -> bool:
    return "test" in (c.fm.get("tags") or [])


def _security_tags(c: Concept) -> list[str]:
    return [t for t in (c.fm.get("tags") or []) if str(t).startswith("security:")]


def gather(bundle: Bundle, query: str, category: str, k_entry: int = 4, include_tests: bool = False,
           config: RetrievalConfig | None = None):
    """Return (entry points, ranked context items, subsystem concepts) for a task."""
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    cfg = config or RetrievalConfig()
    items: dict[str, Item] = {}
    # v0.1 exempted `bug` from the test filter; v0.2 honours include_tests for every category
    drop_tests = not include_tests and (cfg.respect_include_tests or category != "bug")

    def add(rel, score, reason):
        c = bundle.concepts.get(rel)
        if c is None or (drop_tests and _is_test(c)):
            return
        if rel not in items or items[rel].score < score:
            items[rel] = Item(rel, score, reason)

    boost = None
    if category == "security":
        boost = lambda c: 1.0 + 0.6 * bool(_security_tags(c)) + 0.4 * ("area:auth" in (c.fm.get("tags") or []))
    if drop_tests:
        base = boost or (lambda c: 1.0)
        boost = lambda c, _b=base: 0.0 if _is_test(c) else _b(c)
    hits = bundle.search(query, k=k_entry * 2, boost=boost, config=cfg)
    entries: list[str] = []
    for rel, s in hits:
        c = bundle.concepts[rel]
        if c.type == "Requirement":
            for t in c.links.get("Implemented by", []):
                if t in bundle.files and t not in entries:
                    entries.append(t)
                    add(t, 100 + s, f"implements requirement “{c.fm.get('title')}”")
        elif rel not in entries:
            entries.append(rel)
            add(rel, 100 + s, f"entry point (lexical score {s:.1f})")
        if len(entries) >= k_entry:
            break
    entries = entries[:k_entry]

    if category == "feature":
        # pick the dominant subsystem among entry points; present it top-down
        votes = Counter(bundle.subsystem_of(e) for e in entries if bundle.subsystem_of(e))
        for sub, _ in votes.most_common(2):
            members = [t for t in bundle.concepts[sub].links.get("Members", []) if t in bundle.files]
            for i, m in enumerate(members[:8]):
                add(m, 50 - i, f"central member of subsystem {sub}")
        for e in entries:
            for d in bundle.deps(e):
                add(d, 40, f"dependency of {e}")
    elif category == "bug":
        dist = bundle.bfs(entries, bundle.deps, 2)
        for r, d in dist.items():
            if d:
                add(r, 60 - 10 * d, f"dependency at distance {d} from an entry point")
        for e in entries:
            for u in bundle.users(e):
                if _is_test(bundle.concepts[u]):
                    add(u, 45, f"test exercising {e}")
    elif category == "security":
        dist = bundle.bfs(entries, bundle.users, 2)
        for r, d in dist.items():
            if d:
                add(r, 70 - 10 * d, f"caller at distance {d} (exposure path)")
        for e in entries:
            sub = bundle.subsystem_of(e)
            if sub:
                for m in bundle.concepts[sub].links.get("Members", []):
                    if m in bundle.files and _security_tags(bundle.concepts[m]):
                        add(m, 55, "security-flagged file in same subsystem: "
                            + ", ".join(t.split(':', 1)[1] for t in _security_tags(bundle.concepts[m])))
            for d in bundle.deps(e):
                if _security_tags(bundle.concepts[d]):
                    add(d, 50, "security-flagged dependency")
    elif category == "refactor":
        dist = bundle.bfs(entries, bundle.users, 3)
        for r, d in dist.items():
            if d:
                add(r, 80 - 10 * d, f"blast radius: depends on the change at distance {d}")
    subs = []
    for e in entries:
        s = bundle.subsystem_of(e)
        if s and s not in subs:
            subs.append(s)
    ranked = sorted(items.values(), key=lambda it: -it.score)
    return entries, ranked, subs


def context_pack(bundle: Bundle, query: str, category: str, budget_chars: int = 16000,
                 include_tests: bool = False, config: RetrievalConfig | None = None) -> str:
    entries, ranked, subs = gather(bundle, query, category, include_tests=include_tests, config=config)
    root = bundle.concepts.get("/index.md")
    out = [f"# Context pack\n\n- Task category: **{category}**\n- Query: {query}\n"
           f"- Entry points: {len(entries)} · context items: {len(ranked)}\n"]
    if root:
        out.append("## Orientation\n\n" + root.sections.get("Overview", "").strip())
    for s in subs:
        c = bundle.concepts[s]
        out.append(f"## Subsystem: {c.fm.get('title')} (`{s}`)\n\n{c.fm.get('description', '')}")
    out.append("## Relevant files")
    used = sum(len(x) for x in out)
    dropped = 0
    for it in ranked:
        c = bundle.concepts[it.rel]
        block = [f"### {c.fm.get('title')}  \n*{it.reason}*", str(c.fm.get("description", ""))]
        if category == "security" and c.sections.get("Security notes"):
            block.append("Security notes:\n" + c.sections["Security notes"])
        sym = c.sections.get("Symbols", "")
        if sym:
            block.append("Symbols:\n" + "\n".join(sym.splitlines()[:10]))
        text = "\n\n".join(block)
        if used + len(text) > budget_chars:
            dropped += 1
            continue
        out.append(text)
        used += len(text)
    if dropped:
        out.append(f"_{dropped} lower-ranked items omitted to fit the budget._")
    return "\n\n".join(out) + "\n"


def context_json(bundle: Bundle, query: str, category: str, include_tests: bool = False,
                 config: RetrievalConfig | None = None) -> dict:
    entries, ranked, subs = gather(bundle, query, category, include_tests=include_tests, config=config)
    return {"category": category, "query": query, "entry_points": entries, "subsystems": subs,
            "items": [{"concept": it.rel, "path": bundle.concepts[it.rel].fm.get("title"),
                       "score": round(it.score, 2), "reason": it.reason} for it in ranked]}
