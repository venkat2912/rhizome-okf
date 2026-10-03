---
type: Source File
title: shop/api.py
description: HTTP handlers.
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/shop/api.py
tags: [python, 'subsystem:api', 'area:auth']
timestamp: '2026-10-03T17:13:18+00:00'
language: python
content_hash: sha256:d4dc5e6ccc6f08ce
subsystem: api
parser: ast
loc: 11
fan_in: 1
fan_out: 3
centrality: 0.25456
---

# Summary

HTTP handlers.

# Subsystem

Part of [shop/api.py cluster](/subsystems/api.md).

# Symbols

- `def handle_login()` (L6)
- `def handle_order()` (L9)
- `def handle_refund()` (L13)

# Functions

- `handle_login` (L6-L7)
  - calls: [shop/auth.py::login](/files/shop/auth.py.md)
- `handle_order` (L9-L11)
  - calls: [shop/db.py::save_order](/files/shop/db.py.md)
- `handle_refund` (L13-L14)
  - calls: [shop/payments/refunds.py::refund_order](/files/shop/payments/refunds.py.md)

# Depends on

- [shop/auth.py](/files/shop/auth.py.md): uses `login` (weight 2)
- [shop/db.py](/files/shop/db.py.md): uses `db` (weight 2)
- [shop/payments/refunds.py](/files/shop/payments/refunds.py.md): uses `refund_order` (weight 2)

# Used by

- [tests/test_api.py](/files/tests/test_api.py.md): uses `handle_login` (weight 2)
