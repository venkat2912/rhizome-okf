import os
import textwrap

import pytest

SHOP = {
    "shop/__init__.py": '"""Toy e-commerce backend used as a test fixture."""\n',
    "shop/db.py": '''
        """Database access helpers."""
        import sqlite3

        def connect(path):
            return sqlite3.connect(path)

        def find_user(conn, name):
            return conn.execute(f"SELECT * FROM users WHERE name = '{name}'").fetchone()

        def save_order(conn, order):
            conn.execute("INSERT INTO orders VALUES (?)", (order,))
        ''',
    "shop/auth.py": '''
        """Password hashing and session tokens."""
        import hashlib
        from .db import find_user

        SECRET_KEY = "s3cr3t-value-123"

        def hash_password(pw):
            return hashlib.md5(pw.encode()).hexdigest()

        def login(conn, name, pw):
            user = find_user(conn, name)
            return user and user[1] == hash_password(pw)
        ''',
    "shop/api.py": '''
        """HTTP handlers."""
        from shop.auth import login
        from shop import db
        from shop.payments.refunds import refund_order

        def handle_login(conn, req):
            return login(conn, req["name"], req["pw"])

        def handle_order(conn, req):
            db.save_order(conn, req["order"])
            return True

        def handle_refund(conn, req):
            return refund_order(conn, req["order"])
        ''',
    "shop/payments/__init__.py": "",
    "shop/payments/gateway.py": '''
        """Talks to the external payment provider."""
        import requests

        def charge(amount):
            return requests.post("https://pay.example.com/charge", json={"amount": amount}, verify=False)

        def refund(charge_id):
            return requests.post("https://pay.example.com/refund", json={"id": charge_id})
        ''',
    "shop/payments/refunds.py": '''
        """Refund workflow: validates the order then calls the gateway."""
        from .gateway import refund
        from ..db import save_order

        class RefundPolicy:
            """Decides whether an order is refundable."""
            def allowed(self, order):
                return True

        def refund_order(conn, order):
            if RefundPolicy().allowed(order):
                save_order(conn, order)
                return refund(order)
        ''',
    "scripts/cleanup.py": '''
        import os

        def run():
            os.system("rm -rf /tmp/shop-cache")
        ''',
    "tests/test_api.py": '''
        from shop.api import handle_login

        def test_login():
            assert handle_login is not None
        ''',
    "docs/requirements/refunds.md": '''
        # Partial refunds

        Customers must be able to request a partial refund. Extend `refund_order` and the
        RefundPolicy so that only part of the amount is returned through the gateway.
        ''',
}


def write_repo(root, files=SHOP):
    for rel, content in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(textwrap.dedent(content).lstrip("\n"))
    return root


@pytest.fixture
def shop_repo(tmp_path):
    return write_repo(str(tmp_path / "shop_repo"))
