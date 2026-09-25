import os

from rhizome import okf
from rhizome.graph import build_graph, hierarchy, undirected
from rhizome.parse_python import iter_python_files, parse_file
from rhizome.retrieve import Bundle, context_json, context_pack
from rhizome.scanner import scan


def _files(repo):
    return {p: parse_file(repo, p) for p in iter_python_files(repo)}


def test_module_names_and_relative_imports(shop_repo):
    f = _files(shop_repo)
    assert f["shop/payments/refunds.py"].module == "shop.payments.refunds"
    mods = {i.module for i in f["shop/payments/refunds.py"].imports}
    assert "shop.payments.gateway" in mods and "shop.db" in mods


def test_security_rules(shop_repo):
    f = _files(shop_repo)
    rules = lambda p: {s.rule for s in f[p].security}
    assert "sql-string-building" in rules("shop/db.py")
    assert {"weak-hash", "hardcoded-secret"} <= rules("shop/auth.py")
    assert "tls-verify-disabled" in rules("shop/payments/gateway.py")
    assert "shell-exec" in rules("scripts/cleanup.py")


def test_graph_edges(shop_repo):
    G = build_graph(_files(shop_repo))
    assert G.has_edge("shop/api.py", "shop/auth.py")
    assert G.has_edge("shop/api.py", "shop/db.py")           # "from shop import db" resolves to module
    assert G.has_edge("shop/payments/refunds.py", "shop/payments/gateway.py")
    assert G.has_edge("tests/test_api.py", "shop/api.py")
    assert not G.has_edge("shop/db.py", "shop/api.py")


def test_communities_are_connected_and_cover_all_files(shop_repo):
    files = _files(shop_repo)
    G = build_graph(files)
    comms = hierarchy(G, max_size=3)
    covered = {m for c in comms.values() if c.level == 1 for m in c.members}
    assert covered == set(files)
    assert all(c.connected for c in comms.values())
    assert any(c.unlinked for c in comms.values())             # scripts/cleanup.py has no internal edges


def test_scan_produces_conformant_bundle(shop_repo):
    res = scan(shop_repo, docs="docs/requirements")
    out = os.path.join(shop_repo, ".knowledge")
    v = okf.validate(out)
    assert v["ok"], v
    assert res.stats["files"] == 9 and res.stats["requirements"] == 1
    fm, body = okf.split(open(os.path.join(out, "files/shop/api.py.md")).read())
    assert fm["type"] == "Source File" and fm["content_hash"].startswith("sha256:")
    assert "/files/shop/auth.py.md" in body
    req = open(os.path.join(out, "requirements/refunds.md")).read()
    assert "/files/shop/payments/refunds.py.md" in req


def test_incremental_scan_and_check(shop_repo):
    scan(shop_repo)
    out = os.path.join(shop_repo, ".knowledge")
    assert scan(shop_repo, dry_run=True).changed == []           # idempotent
    with open(os.path.join(shop_repo, "shop/payments/gateway.py"), "a") as fh:
        fh.write("\n\ndef void(charge_id):\n    return charge_id\n")
    stale = scan(shop_repo, dry_run=True)
    assert "/files/shop/payments/gateway.py.md" in stale.changed
    assert "shop/payments/gateway.py" in stale.stale_sources
    res = scan(shop_repo)
    assert "/files/shop/db.py.md" not in res.changed               # untouched concept not rewritten
    log = open(os.path.join(out, "log.md")).read()
    assert "Modified: `shop/payments/gateway.py`" in log
    assert scan(shop_repo, dry_run=True).changed == []


def test_timestamps_stable_for_unchanged_concepts(shop_repo):
    scan(shop_repo)
    out = os.path.join(shop_repo, ".knowledge")
    before = okf.split(open(os.path.join(out, "files/shop/db.py.md")).read())[0]["timestamp"]
    with open(os.path.join(shop_repo, "scripts/cleanup.py"), "a") as fh:
        fh.write("\n# touched\n")
    scan(shop_repo)
    after = okf.split(open(os.path.join(out, "files/shop/db.py.md")).read())[0]["timestamp"]
    assert before == after


def test_context_categories(shop_repo):
    scan(shop_repo, docs="docs/requirements")
    b = Bundle(os.path.join(shop_repo, ".knowledge"))
    sec = context_json(b, "password hashing login", "security")
    paths = [i["path"] for i in sec["items"]]
    assert "shop/auth.py" in paths and "shop/api.py" in paths    # caller exposure path
    ref = context_json(b, "database save_order", "refactor")
    paths = [i["path"] for i in ref["items"]]
    assert {"shop/db.py", "shop/api.py", "shop/payments/refunds.py"} <= set(paths)
    feat = context_json(b, "partial refund", "feature")
    assert feat["entry_points"][0] == "/files/shop/payments/refunds.py.md"
    pack = context_pack(b, "partial refund", "feature", budget_chars=4000)
    assert pack.startswith("# Context pack") and len(pack) < 6000


def test_file_deletion_removes_concept(shop_repo):
    scan(shop_repo)
    out = os.path.join(shop_repo, ".knowledge")
    os.remove(os.path.join(shop_repo, "scripts/cleanup.py"))
    res = scan(shop_repo)
    assert "/files/scripts/cleanup.py.md" in res.deleted
    assert not os.path.exists(os.path.join(out, "files/scripts/cleanup.py.md"))
    assert okf.validate(out)["ok"]


def test_deterministic_across_hash_seeds(tmp_path):
    """Two processes with different PYTHONHASHSEED must produce identical bundles."""
    import subprocess
    import sys
    from conftest import write_repo
    outs = []
    for hs in ("1", "2"):
        repo = write_repo(str(tmp_path / f"run{hs}" / "repo"))
        code = f"from rhizome.scanner import scan; scan({repo!r}, max_size=3)"
        subprocess.run([sys.executable, "-c", code], check=True, env=dict(os.environ, PYTHONHASHSEED=hs))
        outs.append(os.path.join(repo, ".knowledge"))
    def content(root):  # every document, minus the scan-time timestamp line
        docs = {}
        for rel, text in okf.iter_concepts(root):
            if rel != "/log.md":
                docs[rel] = "\n".join(ln for ln in text.splitlines() if not ln.startswith("timestamp:"))
        return docs
    assert content(outs[0]) == content(outs[1])
