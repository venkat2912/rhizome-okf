"""Producer: scan a repository and emit / update an OKF code-knowledge bundle."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import okf
from .graph import Community, build_graph, hierarchy, membership, pagerank, undirected
from .parse_python import FileInfo, area_tags, iter_python_files, parse_file
from .summarize import LLMSummarizer, heuristic_community_summary, heuristic_file_summary

STATE_REL = ".rhizome/state.json"
GENERIC_STEMS = {"utils", "util", "base", "core", "main", "init", "test", "tests", "types", "common",
                 "helpers", "config", "settings", "models", "setup", "conftest", "compat", "constants"}


@dataclass
class ScanResult:
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    log_entry: str = ""
    stale_sources: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers

def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _git(repo: str, *args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                              check=True, timeout=30).stdout.strip()
    except Exception:
        return None


def _remote_base(repo: str) -> str | None:
    url = _git(repo, "config", "--get", "remote.origin.url")
    if not url:
        return None
    url = re.sub(r"\.git$", "", url)
    m = re.match(r"git@([^:]+):(.+)", url)
    if m:
        url = f"https://{m.group(1)}/{m.group(2)}"
    return url if url.startswith("http") else None


def _resource(remote: str | None, path: str) -> str:
    return f"{remote}/blob/HEAD/{path}" if remote else f"repo://{path}"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "doc"


def _read_state(out: str) -> dict:
    try:
        with open(os.path.join(out, STATE_REL), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _ctitle(c: Community) -> str:
    members = c.members
    dirs = [p.split("/")[:-1] for p in members]
    common = []
    for parts in zip(*dirs):
        if all(x == parts[0] for x in parts):
            common.append(parts[0])
        else:
            break
    where = "/".join(common)
    if c.unlinked:
        return f"Unlinked files in {where or 'repository root'}"
    if where:
        return f"{where} · {c.hub.split('/')[-1]}"
    return f"{c.hub} cluster"


def _n(k: int, word: str = "file") -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def _rlink(r: dict) -> str:
    return okf.link(r["title"], "/requirements/" + r["slug"] + ".md")


def _cpath(c: Community) -> str:
    return f"/subsystems/{c.parent}/{c.slug}.md" if c.level == 2 else f"/subsystems/{c.slug}.md"


# ------------------------------------------------------------------ requirements

def _load_requirements(repo: str, docs_dir: str | None, files: dict[str, FileInfo]):
    reqs = []
    if not docs_dir:
        return reqs
    base = os.path.join(repo, docs_dir)
    if not os.path.isdir(base):
        return reqs
    # candidate names -> file paths
    by_symbol: dict[str, set[str]] = defaultdict(set)
    by_stem: dict[str, set[str]] = defaultdict(set)
    for f in files.values():
        if f.is_test:
            continue
        for s in f.symbols:
            if len(s.name) >= 4 and not s.name.startswith("_"):
                by_symbol[s.name].add(f.path)
        stem = f.path.split("/")[-1][:-3]
        if len(stem) >= 5 and stem not in GENERIC_STEMS:
            by_stem[stem].add(f.path)
    for dirpath, _, fns in os.walk(base):
        for fn in sorted(fns):
            if not fn.endswith((".md", ".txt")):
                continue
            full = os.path.join(dirpath, fn)
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(full, repo).replace(os.sep, "/")
            m = re.search(r"^#\s+(.+)$", text, re.M)
            title = m.group(1).strip() if m else fn.rsplit(".", 1)[0]
            hits: dict[str, set[str]] = defaultdict(set)
            for f in files.values():
                if f.is_test:
                    continue
                if f.path in text or (f.module and len(f.module.split(".")) > 1 and f.module in text):
                    hits[f.path].add("path")
            words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text))
            for w in words:
                for p in by_symbol.get(w, ()):
                    hits[p].add(f"`{w}`")
                for p in by_stem.get(w, ()):
                    hits[p].add("file name")
            reqs.append({"slug": _slug(fn.rsplit(".", 1)[0]), "title": title, "source": rel,
                         "text": text.strip(), "links": {p: sorted(r) for p, r in hits.items()}})
    return reqs


# ------------------------------------------------------------------ scan

def scan(repo: str, out: str | None = None, docs: str | None = None, llm: bool = False,
         max_size: int | None = None, seed: int | None = None, exclude: list[str] | None = None,
         dry_run: bool = False) -> ScanResult:
    t0 = time.time()
    repo = os.path.abspath(repo)
    out = os.path.abspath(out or os.path.join(repo, ".knowledge"))
    state = _read_state(out)
    # options default to those recorded by the previous scan, so `check` reproduces it exactly
    opts = state.get("options", {})
    docs = docs if docs is not None else opts.get("docs")
    max_size = max_size if max_size is not None else opts.get("max_size", 15)
    seed = seed if seed is not None else opts.get("seed", 42)
    exclude = exclude if exclude else opts.get("exclude", [])
    prev_files = state.get("files", {})
    remote = _remote_base(repo)
    repo_name = remote.rstrip("/").split("/")[-1] if remote else os.path.basename(repo)
    now = _now()

    excl = list(exclude or [])
    rel_out = os.path.relpath(out, repo).replace(os.sep, "/")
    if not rel_out.startswith(".."):
        excl.append(rel_out)
    files = {p: parse_file(repo, p) for p in iter_python_files(repo, excl)}
    t_parse = time.time()
    G = build_graph(files)
    comms = hierarchy(G, max_size=max_size, seed=seed, previous=state.get("communities"))
    t_graph = time.time()
    member_of = membership(comms)
    pr = pagerank(G)
    U = undirected(G)

    summarizer = None
    if llm and not dry_run:
        summarizer = LLMSummarizer()

    # ---- file summaries (cached by content hash)
    summaries: dict[str, tuple[str, str]] = {}
    llm_calls = 0
    for p, f in files.items():
        prev = prev_files.get(p)
        if prev and prev.get("hash") == f.sha and prev.get("summary_source") == "llm":
            summaries[p] = (prev["summary"], "llm")   # only LLM output is cached; heuristics are cheap
            continue
        if summarizer and not f.parse_error:
            with open(os.path.join(repo, p), encoding="utf-8", errors="replace") as fh:
                summaries[p] = (summarizer.file_summary(f, fh.read()), "llm")
            llm_calls += 1
        else:
            summaries[p] = (heuristic_file_summary(f), "heuristic")

    # ---- community summaries (cached by member-hash key)
    prev_comms = state.get("communities", {})
    csum: dict[str, tuple[str, str]] = {}
    for slug, c in comms.items():
        key = hashlib.sha256("|".join(f"{m}:{files[m].sha}" for m in sorted(c.members)).encode()).hexdigest()[:16]
        pc = prev_comms.get(slug, {})
        if pc.get("key") == key and pc.get("summary_source") == "llm":
            csum[slug] = (pc["summary"], "llm", key)
            continue
        if summarizer and not c.unlinked:
            lines = [f"- {m}: {summaries[m][0]}" for m in c.members]
            csum[slug] = (summarizer.community_summary(slug, lines), "llm", key)
            llm_calls += 1
        else:
            csum[slug] = (heuristic_community_summary([files[m] for m in c.members], files[c.hub],
                                                      len(c.children)), "heuristic", key)

    reqs = _load_requirements(repo, docs, files)
    req_by_file: dict[str, list[dict]] = defaultdict(list)
    for r in reqs:
        for p in r["links"]:
            req_by_file[p].append(r)

    docs_out: dict[str, tuple[dict, str]] = {}

    # ---- source file concepts
    for p, f in files.items():
        l1 = member_of[p].get(1)
        l2 = member_of[p].get(2)
        sec_rules = sorted({s.rule for s in f.security if s.severity != "info"})
        tags = ["python"] + (["test"] if f.is_test else []) + [f"subsystem:{l1}"] + area_tags(f) \
            + [f"security:{r}" for r in sec_rules]
        fm = {"type": "Source File", "title": p, "description": summaries[p][0],
              "resource": _resource(remote, p), "tags": tags, "timestamp": None,
              "language": "python", "content_hash": f.sha, "subsystem": l1}
        if l2:
            fm["component"] = l2
        fm.update({"loc": f.loc, "fan_in": G.in_degree(p), "fan_out": G.out_degree(p),
                   "centrality": round(pr.get(p, 0.0), 5)})
        b = [f"# Summary\n\n{summaries[p][0]}"]
        c1 = comms[l1]
        sub_line = f"Part of {okf.link(_ctitle(c1), _cpath(c1))}"
        if l2:
            sub_line += f", component {okf.link(_ctitle(comms[l2]), _cpath(comms[l2]))}"
        b.append(f"# Subsystem\n\n{sub_line}.")
        sym = []
        for s in f.symbols:
            head = f"- `class {s.name}`" if s.kind == "class" else f"- `def {s.name}()`"
            sym.append(f"{head} (L{s.line})" + (f": {s.doc}" if s.doc else ""))
            if s.methods:
                sym.append("  - methods: " + ", ".join(f"`{m}`" for m in s.methods[:25])
                           + (" …" if len(s.methods) > 25 else ""))
        if sym:
            b.append("# Symbols\n\n" + "\n".join(sym))
        deps = sorted(G.successors(p), key=lambda t: -G[p][t]["weight"])
        b.append("# Depends on\n\n" + ("\n".join(
            f"- {okf.link(t, okf.concept_path_for_file(t))}: uses "
            + ", ".join(f"`{n}`" for n in G[p][t]["names"][:8]) for t in deps) or "None."))
        users = sorted(G.predecessors(p), key=lambda s: -G[s][p]["weight"])
        b.append("# Used by\n\n" + ("\n".join(
            f"- {okf.link(s, okf.concept_path_for_file(s))}: uses "
            + ", ".join(f"`{n}`" for n in G[s][p]["names"][:8]) for s in users) or "None."))
        if f.external_imports:
            b.append("# External dependencies\n\n" + ", ".join(f"`{e}`" for e in f.external_imports))
        if f.security:
            b.append("# Security notes\n\n" + "\n".join(
                f"- L{s.line} · **{s.severity}** · {s.rule}: {s.detail}" for s in f.security))
        if req_by_file.get(p):
            b.append("# Requirements\n\n" + "\n".join(
                f"- {_rlink(r)}" for r in req_by_file[p]))
        docs_out[okf.concept_path_for_file(p)] = (fm, "\n\n".join(b))

    # ---- subsystem / component concepts
    def edges_between(a: set[str], b: set[str]):
        w, n = 0.0, 0
        for x in a:
            for y in G.successors(x):
                if y in b:
                    w += G[x][y]["weight"]
                    n += 1
        return n, w

    level1 = [c for c in comms.values() if c.level == 1]
    for c in comms.values():
        mem = set(c.members)
        peers = level1 if c.level == 1 else [comms[s] for s in comms[c.parent].children]
        out_deps, in_deps = [], []
        for o in peers:
            if o.slug == c.slug:
                continue
            n, w = edges_between(mem, set(o.members))
            if n:
                out_deps.append((w, n, o))
            n, w = edges_between(set(o.members), mem)
            if n:
                in_deps.append((w, n, o))
        sec = Counter()
        sec_files = defaultdict(set)
        for m in c.members:
            for s in files[m].security:
                if s.severity != "info":
                    sec[s.rule] += 1
                    sec_files[s.rule].add(m)
        tags = ["subsystem" if c.level == 1 else "component"] + (["unlinked"] if c.unlinked else []) \
            + [f"security:{r}" for r in sorted(sec)]
        fm = {"type": "Subsystem" if c.level == 1 else "Component", "title": _ctitle(c),
              "description": csum[c.slug][0], "tags": tags, "timestamp": None,
              "level": c.level, "size": len(c.members), "hub": c.hub,
              "grouping": "directory (no internal imports)" if c.unlinked else "leiden",
              "cohesion": c.cohesion, "connected": c.connected}
        if c.parent:
            fm["parent"] = c.parent
        b = [f"# Summary\n\n{csum[c.slug][0]}"]
        if c.parent:
            b.append(f"# Parent\n\n{okf.link(_ctitle(comms[c.parent]), _cpath(comms[c.parent]))}")
        if c.children:
            b.append("# Components\n\n" + "\n".join(
                f"- {okf.link(_ctitle(comms[s]), _cpath(comms[s]))} ({_n(len(comms[s].members))}): "
                f"{csum[s][0]}" for s in c.children))
        b.append("# Members\n\nRanked by centrality in the dependency graph.\n\n" + "\n".join(
            f"- {okf.link(m, okf.concept_path_for_file(m))}: {summaries[m][0]}" for m in c.members))
        label = "subsystems" if c.level == 1 else "sibling components"
        b.append(f"# Depends on {label}\n\n" + ("\n".join(
            f"- {okf.link(_ctitle(o), _cpath(o))}: {n} import edges (weight {w:.0f})"
            for w, n, o in sorted(out_deps, key=lambda x: -x[0])) or "None."))
        b.append(f"# Used by {label}\n\n" + ("\n".join(
            f"- {okf.link(_ctitle(o), _cpath(o))}: {n} import edges (weight {w:.0f})"
            for w, n, o in sorted(in_deps, key=lambda x: -x[0])) or "None."))
        if sec:
            b.append("# Security notes\n\n" + "\n".join(
                f"- {r} ×{k}: " + ", ".join(okf.link(m, okf.concept_path_for_file(m)) for m in sorted(sec_files[r]))
                for r, k in sec.most_common()))
        linked_reqs = {r["slug"]: r for m in c.members for r in req_by_file.get(m, [])}
        if linked_reqs:
            b.append("# Requirements\n\n" + "\n".join(
                f"- {_rlink(r)}" for s, r in sorted(linked_reqs.items())))
        docs_out[_cpath(c)] = (fm, "\n\n".join(b))

    # ---- requirement concepts
    for r in reqs:
        fm = {"type": "Requirement", "title": r["title"],
              "description": " ".join(re.sub(r"^#.*$", "", r["text"], flags=re.M).split())[:200],
              "resource": _resource(remote, r["source"]), "tags": ["requirement"], "timestamp": None}
        impl = sorted(r["links"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        b = [f"# Implemented by\n\n" + ("\n".join(
            f"- {okf.link(p, okf.concept_path_for_file(p))} (matched: {', '.join(why)})" for p, why in impl)
            or "No code matched yet."),
             "# Text\n\n" + re.sub(r"^(#+)", r"#\1", r["text"], flags=re.M)]
        docs_out[f"/requirements/{r['slug']}.md"] = (fm, "\n\n".join(b))

    # ---- indexes (progressive disclosure)
    l1_sorted = sorted(level1, key=lambda c: (c.unlinked, -len(c.members)))
    docs_out["/subsystems/index.md"] = ({"type": "Index", "title": "Subsystems",
        "description": f"{len(level1)} subsystems found by Leiden community detection on the import graph.",
        "timestamp": None}, "# Subsystems\n\n" + "\n".join(
        f"- {okf.link(_ctitle(c), _cpath(c))} ({_n(len(c.members))}, cohesion {c.cohesion}): {csum[c.slug][0]}"
        for c in l1_sorted))
    for c in level1:
        if c.children:
            docs_out[f"/subsystems/{c.slug}/index.md"] = ({"type": "Index", "title": f"Components of {_ctitle(c)}",
                "description": f"{len(c.children)} components of subsystem {c.slug}.", "timestamp": None},
                "# Components\n\n" + "\n".join(
                    f"- {okf.link(_ctitle(comms[s]), _cpath(comms[s]))} ({_n(len(comms[s].members))}): {csum[s][0]}"
                    for s in c.children) + f"\n\nParent: {okf.link(_ctitle(c), _cpath(c))}")

    dir_children: dict[str, set[str]] = defaultdict(set)
    for p in files:
        parts = p.split("/")
        for i in range(len(parts)):
            parent = "/".join(parts[:i])
            dir_children[parent].add("/".join(parts[: i + 1]))
    for d, kids in dir_children.items():
        lines = []
        for k in sorted(kids):
            if k in files:
                lines.append(f"- {okf.link(k.split('/')[-1], okf.concept_path_for_file(k))}: {summaries[k][0]}")
            else:
                lines.append(f"- {okf.link(k.split('/')[-1] + '/', f'/files/{k}/index.md')}")
        rel = f"/files/{d}/index.md" if d else "/files/index.md"
        docs_out[rel] = ({"type": "Index", "title": f"Files in {d or '/'}",
                          "description": f"Source files under {d or 'the repository root'}.", "timestamp": None},
                         "# Contents\n\n" + "\n".join(lines))
    if reqs:
        docs_out["/requirements/index.md"] = ({"type": "Index", "title": "Requirements",
            "description": f"{len(reqs)} requirement documents linked to code.", "timestamp": None},
            "# Requirements\n\n" + "\n".join(
                f"- {_rlink(r)}: {len(r['links'])} linked files" for r in reqs))

    digest = hashlib.sha256("".join(f"{p}{files[p].sha}" for p in sorted(files)).encode()).hexdigest()[:16]
    hot = sorted(files.values(), key=lambda f: -sum(1 for s in f.security if s.severity == "high"))
    hot = [f for f in hot if any(s.severity == "high" for s in f.security)][:8]
    root_body = [
        f"# Overview\n\n`{repo_name}`: {len(files)} Python files, {G.number_of_edges()} internal import edges, "
        f"{len(level1)} subsystems ({sum(1 for c in comms.values() if c.level == 2)} components). "
        f"Subsystems are communities found by the Leiden algorithm on the weighted import graph, so they "
        f"reflect how code is actually coupled rather than how folders are laid out.",
        "# How to navigate\n\n1. Read the subsystem list below and pick the relevant one.\n"
        "2. Open its concept for members, cross-subsystem dependencies and security notes.\n"
        "3. Open individual file concepts and follow *Depends on* / *Used by* links.\n"
        f"4. {okf.link('All files', '/files/index.md')} · {okf.link('Change log', '/log.md')}"
        + (f" · {okf.link('Requirements', '/requirements/index.md')}" if reqs else ""),
        "# Subsystems\n\n" + "\n".join(
            f"- {okf.link(_ctitle(c), _cpath(c))} ({_n(len(c.members))}): {csum[c.slug][0]}" for c in l1_sorted),
    ]
    if hot:
        root_body.append("# Security hotspots\n\n" + "\n".join(
            f"- {okf.link(f.path, okf.concept_path_for_file(f.path))}: "
            + ", ".join(sorted({s.rule for s in f.security if s.severity == 'high'})) for f in hot))
    docs_out["/index.md"] = ({"type": "Index", "title": repo_name,
        "description": f"Code knowledge bundle for {repo_name}: subsystems, files, dependencies, security notes.",
        "resource": remote or f"repo://{repo_name}", "timestamp": None, "source_digest": digest,
        "profile": "okf-code/0.1"}, "\n\n".join(root_body))

    # ---- timestamps: time the document's content last changed
    prev_docs = state.get("docs", {})
    rendered: dict[str, str] = {}
    new_doc_state = {}
    for rel, (fm, body) in docs_out.items():
        h = hashlib.sha256(okf.render(fm, body).encode()).hexdigest()[:16]
        pd = prev_docs.get(rel, {})
        ts = pd["timestamp"] if pd.get("hash") == h and pd.get("timestamp") else now
        fm["timestamp"] = ts
        rendered[rel] = okf.render(fm, body)
        new_doc_state[rel] = {"hash": h, "timestamp": ts}

    # ---- change detection
    result = ScanResult()
    added = sorted(set(files) - set(prev_files))
    removed = sorted(set(prev_files) - set(files))
    modified = sorted(p for p in files if p in prev_files and prev_files[p]["hash"] != files[p].sha)
    result.stale_sources = added + removed + modified
    for rel, content in rendered.items():
        if okf.write_if_changed(out, rel, content, dry_run=dry_run):
            result.changed.append(rel)
    for rel in sorted(set(prev_docs) - set(rendered)):
        if rel == "/log.md":
            continue
        result.deleted.append(rel)
        if not dry_run:
            try:
                os.remove(os.path.join(out, rel.lstrip("/")))
            except FileNotFoundError:
                pass

    prev_member = {m: slug for slug, v in prev_comms.items() if v.get("level") == 1 for m in v["members"]}
    moved = sorted(p for p in files if p in prev_member and prev_member[p] != member_of[p].get(1))
    new_slugs = sorted(s for s in comms if s not in prev_comms)
    gone_slugs = sorted(s for s in prev_comms if s not in comms)

    if result.changed or result.deleted:
        head = _git(repo, "rev-parse", "--short", "HEAD") or "no-git"
        lines = [f"## {now} (scanned at {head})", ""]
        if not state:
            lines.append(f"- Initial scan: {len(files)} files, {len(level1)} subsystems.")
        for label, items in (("Added", added), ("Modified", modified), ("Removed", removed)):
            if items and state:
                lines.append(f"- {label}: " + ", ".join(f"`{p}`" for p in items[:30])
                    + (" …" if len(items) > 30 else ""))
        if state and moved:
            lines.append("- Moved between subsystems: " + ", ".join(
                f"`{p}` ({prev_member[p]} → {member_of[p][1]})" for p in moved[:20]))
        if state and new_slugs:
            lines.append("- New communities: " + ", ".join(f"`{s}`" for s in new_slugs))
        if state and gone_slugs:
            lines.append("- Dissolved communities: " + ", ".join(f"`{s}`" for s in gone_slugs))
        if state and not (added or modified or removed or moved or new_slugs or gone_slugs):
            lines.append(f"- Regenerated {len(result.changed)} documents (no source changes).")
        result.log_entry = "\n".join(lines)
        if not dry_run:
            log_path = os.path.join(out, "log.md")
            try:
                with open(log_path, encoding="utf-8") as fh:
                    _, old_body = okf.split(fh.read())
            except FileNotFoundError:
                old_body = "# Change log\n\nChronological history of knowledge updates."
            log_doc = okf.render({"type": "Log", "title": "Change log",
                                  "description": "Chronological history of scans and knowledge updates.",
                                  "timestamp": now}, old_body.rstrip() + "\n\n" + result.log_entry)
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(log_doc)

    t_end = time.time()
    result.stats = {
        "files": len(files), "parse_errors": sum(1 for f in files.values() if f.parse_error),
        "edges": G.number_of_edges(), "subsystems": len(level1),
        "components": sum(1 for c in comms.values() if c.level == 2),
        "unlinked_groups": sum(1 for c in level1 if c.unlinked),
        "disconnected_communities": sum(1 for c in comms.values() if not c.connected),
        "documents": len(rendered) + 1, "changed_documents": len(result.changed),
        "llm_calls": llm_calls, "requirements": len(reqs),
        "security_findings": sum(1 for f in files.values() for s in f.security if s.severity != "info"),
        "seconds_parse": round(t_parse - t0, 3), "seconds_graph": round(t_graph - t_parse, 3),
        "seconds_total": round(t_end - t0, 3),
    }

    if not dry_run:
        new_state = {
            "version": 1, "scanned_at": now, "source_digest": digest,
            "options": {"docs": docs, "max_size": max_size, "seed": seed, "exclude": list(exclude or [])},
            "files": {p: {"hash": files[p].sha, "summary": summaries[p][0], "summary_source": summaries[p][1]}
                      for p in files},
            "communities": {s: {"level": c.level, "parent": c.parent, "members": c.members,
                                "summary": csum[s][0], "summary_source": csum[s][1], "key": csum[s][2]}
                            for s, c in comms.items()},
            "docs": new_doc_state,
        }
        os.makedirs(os.path.join(out, ".rhizome"), exist_ok=True)
        with open(os.path.join(out, STATE_REL), "w", encoding="utf-8") as fh:
            json.dump(new_state, fh, indent=1, sort_keys=True)
    return result
