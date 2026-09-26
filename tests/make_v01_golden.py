"""Regenerate tests/data/v01_golden.json. Must be run against Rhizome v0.1 code (commit c57a02f/f35f2d3).

The golden file pins v0.1 retrieval output on the shop fixture so that RetrievalConfig.v01() can be
checked to reproduce it exactly.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import write_repo  # noqa: E402
from rhizome.retrieve import Bundle, CATEGORIES, gather  # noqa: E402
from rhizome.scanner import scan  # noqa: E402

QUERIES = [
    "partial refund",
    "password hashing login",
    "database save_order",
    "sql injection in user lookup",
    "payment gateway charge fails with TLS error",
    'Traceback (most recent call last):\n  File "shop/api.py", line 12, in handle_refund\n'
    "    return refund_order(conn, req[\"order\"])\nKeyError: 'order'",
    "HTTP handlers return wrong status for login",
    "cleanup script deletes cache",
]


def golden():
    with tempfile.TemporaryDirectory() as tmp:
        repo = write_repo(os.path.join(tmp, "shop_repo"))
        scan(repo, docs="docs/requirements")
        b = Bundle(os.path.join(repo, ".knowledge"))
        out = {"search": {}, "gather": {}}
        for q in QUERIES:
            out["search"][q] = [[r, round(s, 6)] for r, s in b.search(q, k=50)]
            for cat in CATEGORIES:
                for tests in (False, True):
                    e, items, subs = gather(b, q, cat, include_tests=tests)
                    out["gather"][f"{cat}|{tests}|{q}"] = {
                        "entries": e, "subs": subs,
                        "items": [[i.rel, round(i.score, 6), i.reason] for i in items]}
        return out


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "v01_golden.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(golden(), fh, indent=1, ensure_ascii=False)
    print("wrote", path)
