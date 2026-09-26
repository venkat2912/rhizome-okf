---
type: Source File
title: shop/db.py
description: Database access helpers.
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/shop/db.py
tags: [python, 'subsystem:api', 'security:sql-string-building']
timestamp: '2026-09-26T10:23:34+00:00'
language: python
content_hash: sha256:630727b132f3e17b
subsystem: api
loc: 8
fan_in: 3
fan_out: 0
centrality: 0.18927
---

# Summary

Database access helpers.

# Subsystem

Part of [shop/api.py cluster](/subsystems/api.md).

# Symbols

- `def connect()` (L4)
- `def find_user()` (L7)
- `def save_order()` (L10)

# Depends on

None.

# Used by

- [shop/api.py](/files/shop/api.py.md): uses `db`
- [shop/auth.py](/files/shop/auth.py.md): uses `find_user`
- [shop/payments/refunds.py](/files/shop/payments/refunds.py.md): uses `save_order`

# External dependencies

`sqlite3`

# Security notes

- L8 · **high** · sql-string-building: query passed to `.execute()` is built by string formatting
