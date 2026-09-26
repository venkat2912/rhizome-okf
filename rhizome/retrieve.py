"""Consumer: category-aware context retrieval over an OKF code bundle.

Reads only the published markdown bundle (never the scanner's internal state), which
demonstrates producer/consumer independence: any OKF-conformant code bundle works.

Pipeline: lexical entry points (BM25 over concept text) -> graph expansion whose shape
depends on the task category -> ranked, budgeted context pack.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

from . import okf

STOP = set("""a an the and or of to in on for with from by is are be this that it as at into
when then than via use uses using add new fix bug make should must can will not no all any each
code file files function method class module""".split())

CATEGORIES = ("feature", "bug", "security", "refactor")


@dataclass(frozen=True)
class RetrievalConfig:
    """Switches for every v0.2 retrieval change, so each can be ablated.

    The defaults are the v0.2 behaviour; ``RetrievalConfig.v01()`` reproduces v0.1 rankings exactly.
    """
    # #6: v0.1 kept test files for the `bug` category even when include_tests was False.
    respect_include_tests: bool = True

    @classmethod
    def v01(cls) -> "RetrievalConfig":
        return cls(respect_include_tests=False)


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
    def __init__(self, path: str):
        self.path = path
        self.concepts: dict[str, Concept] = {}
        for rel, text in okf.iter_concepts(path):
            fm, body = okf.split(text)
            secs = okf.sections(body)
            links = {name: [t for _, t in okf.LINK.findall(content)] for name, content in secs.items()}
            self.concepts[rel] = Concept(rel, fm, body, secs, links)
        self.files = {r: c for r, c in self.concepts.items() if c.type == "Source File"}
        self._build_index()

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

    def search(self, query: str, k: int = 5, types: tuple[str, ...] = ("Source File", "Requirement"),
               boost=None, config: "RetrievalConfig | None" = None) -> list[tuple[str, float]]:
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
    hits = bundle.search(query, k=k_entry * 2, boost=boost)
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
