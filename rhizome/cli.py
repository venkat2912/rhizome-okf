"""Command-line interface: ``rhizome scan | check | validate | context | stats``."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, okf
from .graph import build_graph, disconnected_count, leiden, louvain, undirected
from .parse_python import iter_python_files, parse_file
from .retrieve import CATEGORIES, Bundle, context_json, context_pack
from .scanner import scan


def _cmd_scan(a):
    res = scan(a.repo, out=a.out, docs=a.docs, llm=a.llm, max_size=a.max_community, seed=a.seed,
               exclude=a.exclude)
    s = res.stats
    print(f"Scanned {s['files']} files · {s['edges']} import edges · {s['subsystems']} subsystems "
          f"({s['components']} components) · {s['security_findings']} security findings")
    print(f"Documents: {s['documents']} total, {len(res.changed)} written, {len(res.deleted)} removed "
          f"· LLM calls: {s['llm_calls']} · {s['seconds_total']}s")
    if a.json:
        print(json.dumps(s, indent=2))
    return 0


def _cmd_check(a):
    res = scan(a.repo, out=a.out, docs=a.docs, max_size=a.max_community, seed=a.seed,
               exclude=a.exclude, dry_run=True)
    if res.changed or res.deleted:
        print("Knowledge bundle is STALE. Run `rhizome scan` and commit the bundle with your change.")
        for r in (res.changed + res.deleted)[:40]:
            print(f"  out of date: {r}")
        return 1
    print("Knowledge bundle is up to date.")
    return 0


def _cmd_validate(a):
    r = okf.validate(a.bundle)
    print(f"{r['documents']} documents · missing type: {len(r['missing_type'])} · "
          f"broken links: {len(r['broken_links'])} · {'CONFORMANT' if r['ok'] else 'NOT CONFORMANT'}")
    for p in r["missing_type"][:20]:
        print(f"  missing type: {p}")
    for src, tgt in r["broken_links"][:20]:
        print(f"  broken link: {src} -> {tgt}")
    return 0 if r["ok"] else 1


def _cmd_context(a):
    b = Bundle(a.bundle)
    if a.json:
        print(json.dumps(context_json(b, a.query, a.category, a.tests), indent=2))
    else:
        print(context_pack(b, a.query, a.category, a.budget, a.tests))
    return 0


def _cmd_stats(a):
    files = {p: parse_file(a.repo, p) for p in iter_python_files(a.repo, a.exclude)}
    G = build_graph(files)
    U = undirected(G)
    linked = U.subgraph([n for n in U if U.degree(n)]).copy()
    rows = []
    for seed in range(a.seeds):
        le, lo = leiden(linked, seed=seed), louvain(linked, seed=seed)
        rows.append((len(le), disconnected_count(linked, le), len(lo), disconnected_count(linked, lo)))
    print(f"files={len(files)} edges={G.number_of_edges()} linked_nodes={linked.number_of_nodes()}")
    print("seed  leiden_comms  leiden_disconnected  louvain_comms  louvain_disconnected")
    for i, r in enumerate(rows):
        print(f"{i:>4}  {r[0]:>12}  {r[1]:>19}  {r[2]:>13}  {r[3]:>20}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rhizome", description="Repository scanner that publishes code "
                                "knowledge as an Open Knowledge Format (OKF) bundle.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("repo", help="repository root")
        sp.add_argument("--out", help="bundle directory (default: <repo>/.knowledge)")
        sp.add_argument("--docs", help="directory of requirement docs (markdown) to link to code")
        sp.add_argument("--max-community", type=int, default=None,
                        help="split subsystems larger than this into components (default 15)")
        sp.add_argument("--seed", type=int, default=None)
        sp.add_argument("--exclude", action="append", default=[], help="path prefix to skip (repeatable)")

    sp = sub.add_parser("scan", help="scan a repo and write/update the OKF bundle")
    common(sp)
    sp.add_argument("--llm", action="store_true", help="LLM descriptions (needs ANTHROPIC_API_KEY)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=_cmd_scan)

    sp = sub.add_parser("check", help="exit 1 if the bundle is stale (use in CI / pre-commit)")
    common(sp)
    sp.set_defaults(fn=_cmd_check)

    sp = sub.add_parser("validate", help="check OKF conformance of a bundle")
    sp.add_argument("bundle")
    sp.set_defaults(fn=_cmd_validate)

    sp = sub.add_parser("context", help="build a category-aware context pack for a task")
    sp.add_argument("bundle")
    sp.add_argument("query")
    sp.add_argument("--category", choices=CATEGORIES, required=True)
    sp.add_argument("--budget", type=int, default=16000, help="character budget (default 16000)")
    sp.add_argument("--tests", action="store_true", help="include test files")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=_cmd_context)

    sp = sub.add_parser("stats", help="compare Leiden and Louvain connectivity on the import graph")
    sp.add_argument("repo")
    sp.add_argument("--seeds", type=int, default=10)
    sp.add_argument("--exclude", action="append", default=[])
    sp.set_defaults(fn=_cmd_stats)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
