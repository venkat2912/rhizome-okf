"""Dependency graph construction and hierarchical Leiden community detection."""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import networkx as nx

from .parse_python import FileInfo


# --------------------------------------------------------------------------- graph

def module_index(files: dict[str, FileInfo]) -> dict[str, str]:
    """dotted module name -> file path (canonical names win over aliases)."""
    idx: dict[str, str] = {}
    for f in files.values():
        for a in f.aliases:
            idx.setdefault(a, f.path)
    for f in files.values():
        if f.module:
            idx[f.module] = f.path
    return idx


def _longest_prefix(mod: str, idx: dict[str, str]) -> str | None:
    parts = mod.split(".")
    for i in range(len(parts), 0, -1):
        p = ".".join(parts[:i])
        if p in idx:
            return p
    return None


def build_graph(files: dict[str, FileInfo]) -> nx.DiGraph:
    """Directed graph: edge A -> B means file A imports (depends on) file B.

    Edge attributes: ``weight`` (1 + references to imported names) and ``names``.
    """
    idx = module_index(files)
    G = nx.DiGraph()
    for f in files.values():
        G.add_node(f.path)
    for f in files.values():
        targets: dict[str, set[str]] = defaultdict(set)
        external: set[str] = set()
        for imp in f.imports:
            resolved_any = False
            if imp.names:
                for n in imp.names:
                    sub = f"{imp.module}.{n}"
                    if n != "*" and sub in idx:
                        targets[idx[sub]].add(n)
                        resolved_any = True
                    elif imp.module in idx:
                        targets[idx[imp.module]].add(n)
                        resolved_any = True
            else:
                p = _longest_prefix(imp.module, idx)
                if p:
                    local = imp.alias or imp.module.split(".")[-1]
                    targets[idx[p]].add(local)
                    resolved_any = True
            if not resolved_any:
                top = imp.module.split(".")[0]
                if top and _longest_prefix(imp.module, idx) is None:
                    external.add(top)
        f.external_imports = sorted(external)
        for tgt, names in targets.items():
            if tgt == f.path:
                continue
            refs = sum(f.name_refs.get(n, 0) for n in names if n != "*")
            G.add_edge(f.path, tgt, weight=1.0 + min(refs, 50), names=sorted(names))
    return G


def undirected(G: nx.DiGraph) -> nx.Graph:
    U = nx.Graph()
    U.add_nodes_from(G.nodes)
    for a, b, d in G.edges(data=True):
        w = d.get("weight", 1.0)
        if U.has_edge(a, b):
            U[a][b]["weight"] += w
        else:
            U.add_edge(a, b, weight=w)
    return U


# ---------------------------------------------------------------- community detection

def canonical(U: nx.Graph) -> nx.Graph:
    """Copy with sorted node and edge order.

    networkx subgraph views iterate their node *set*, whose order depends on Python's
    per-process hash seed; community detection is order-sensitive, so without this the
    same repository could be partitioned differently in two runs (and ``check`` would
    report a fresh bundle as stale).
    """
    C = nx.Graph()
    C.add_nodes_from(sorted(U.nodes))
    C.add_edges_from(sorted((min(a, b), max(a, b), d) for a, b, d in U.edges(data=True)))
    return C


def leiden(U: nx.Graph, resolution: float = 1.0, seed: int = 42) -> list[set[str]]:
    """Leiden (Traag et al., 2019) on a weighted undirected graph, iterated until stable."""
    import igraph as ig
    import leidenalg

    U = canonical(U)
    nodes = list(U.nodes)
    if not nodes:
        return []
    pos = {n: i for i, n in enumerate(nodes)}
    g = ig.Graph(n=len(nodes), edges=[(pos[a], pos[b]) for a, b in U.edges])
    g.es["weight"] = [d.get("weight", 1.0) for _, _, d in U.edges(data=True)]
    part = leidenalg.find_partition(
        g, leidenalg.RBConfigurationVertexPartition, weights="weight",
        resolution_parameter=resolution, seed=seed, n_iterations=-1,
    )
    return [set(nodes[i] for i in comm) for comm in part]


def louvain(U: nx.Graph, resolution: float = 1.0, seed: int = 42) -> list[set[str]]:
    U = canonical(U)
    return [set(c) for c in nx.community.louvain_communities(U, weight="weight",
                                                            resolution=resolution, seed=seed)]


def disconnected_count(U: nx.Graph, comms: list[set[str]]) -> int:
    return sum(1 for c in comms if len(c) > 1 and not nx.is_connected(U.subgraph(c)))


@dataclass
class Community:
    slug: str
    level: int
    members: list[str]
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    hub: str = ""
    unlinked: bool = False
    cohesion: float = 0.0
    connected: bool = True


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "misc"


def _common_dir(paths: list[str]) -> str:
    dirs = [p.split("/")[:-1] for p in paths]
    out = []
    for parts in zip(*dirs):
        if all(x == parts[0] for x in parts):
            out.append(parts[0])
        else:
            break
    return "/".join(out)


def _stem(path: str) -> str:
    base = path.split("/")[-1][:-3]
    if base == "__init__":
        base = path.split("/")[-2] if "/" in path else "root"
    return base


def _merge_singletons(U: nx.Graph, comms: list[set[str]]) -> list[set[str]]:
    big = [c for c in comms if len(c) > 1]
    singles = [c for c in comms if len(c) == 1]
    if not big:
        return comms
    for s in singles:
        (n,) = tuple(s)
        best, bw = None, 0.0
        for c in big:
            w = sum(U[n][m]["weight"] for m in U.neighbors(n) if m in c)
            if w > bw:
                best, bw = c, w
        (best or max(big, key=len)).add(n)
    return big


def hierarchy(G: nx.DiGraph, max_size: int = 15, seed: int = 42, resolution: float = 1.0,
              previous: dict | None = None) -> dict[str, Community]:
    """Two-level Leiden hierarchy with stable slugs.

    * Nodes with no internal dependency edges are grouped by top-level directory into
      ``unlinked`` communities instead of producing hundreds of singletons.
    * Level-1 communities larger than ``max_size`` are re-partitioned with Leiden on
      their induced subgraph to form level-2 components.
    * Slugs are matched to the previous scan (Jaccard >= 0.5) so identities stay stable.
    """
    U = undirected(G)
    pr = nx.pagerank(U, weight="weight") if U.number_of_edges() else {n: 1.0 for n in U}
    def rank(n):  # centrality first, path as a deterministic tie-breaker
        return (-round(pr.get(n, 0.0), 12), n)

    linked = [n for n in U if U.degree(n) > 0]
    isolated = [n for n in U if U.degree(n) == 0]

    level1: list[tuple[set[str], bool]] = []
    if linked:
        for c in leiden(U.subgraph(linked).copy(), resolution, seed):
            level1.append((c, False))
    by_dir: dict[str, set[str]] = defaultdict(set)
    for n in isolated:
        by_dir[n.split("/")[0] if "/" in n else "(root)"].add(n)
    for d, members in by_dir.items():
        level1.append((members, True))

    prev_l1 = {k: set(v["members"]) for k, v in (previous or {}).items() if v.get("level") == 1}
    prev_l2 = {k: set(v["members"]) for k, v in (previous or {}).items() if v.get("level") == 2}

    comms: dict[str, Community] = {}
    used: set[str] = set()

    def name_for(members: set[str], unlinked: bool, prev: dict[str, set[str]], prefix: str = "") -> str:
        best, bj = None, 0.5
        for slug, pm in prev.items():
            if slug in used:
                continue
            j = len(members & pm) / max(1, len(members | pm))
            if j >= bj:
                best, bj = slug, j
        if best:
            return best
        hub = min(members, key=rank)
        cdir = _common_dir(sorted(members)).split("/")[-1] if _common_dir(sorted(members)) else ""
        base = f"unlinked-{cdir or _stem(hub)}" if unlinked else (
            f"{cdir}-{_stem(hub)}" if cdir and cdir != _stem(hub) else _stem(hub))
        slug = _slugify(prefix + base)
        i, cand = 2, slug
        while cand in used:
            cand, i = f"{slug}-{i}", i + 1
        return cand

    for members, unlinked in sorted(level1, key=lambda x: (x[1], -len(x[0]), sorted(x[0])[0])):
        slug = name_for(members, unlinked, prev_l1)
        used.add(slug)
        c = Community(slug, 1, sorted(members, key=rank), unlinked=unlinked)
        c.hub = c.members[0]
        comms[slug] = c
        if not unlinked and len(members) > max_size:
            sub = U.subgraph(members).copy()
            parts = _merge_singletons(sub, leiden(sub, resolution, seed))
            if len(parts) > 1:
                for p in sorted(parts, key=lambda x: (-len(x), sorted(x)[0])):
                    cslug = name_for(p, False, prev_l2, prefix=f"{slug}--")
                    used.add(cslug)
                    child = Community(cslug, 2, sorted(p, key=rank), parent=slug)
                    child.hub = child.members[0]
                    comms[cslug] = child
                    c.children.append(cslug)

    for c in comms.values():
        mem = set(c.members)
        internal = sum(d["weight"] for a, b, d in U.subgraph(mem).edges(data=True))
        cut = sum(d["weight"] for a, b, d in U.edges(mem, data=True) if (a in mem) != (b in mem))
        c.cohesion = round(internal / (internal + cut), 3) if internal + cut else 0.0
        c.connected = c.unlinked or len(mem) == 1 or nx.is_connected(U.subgraph(mem))
    return comms


def membership(comms: dict[str, Community]) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = defaultdict(dict)
    for c in comms.values():
        for m in c.members:
            out[m][c.level] = c.slug
    return out


def pagerank(G: nx.DiGraph) -> dict[str, float]:
    U = undirected(G)
    return nx.pagerank(U, weight="weight") if U.number_of_edges() else {n: 1.0 for n in U}
