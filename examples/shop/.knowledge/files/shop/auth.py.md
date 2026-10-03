---
type: Source File
title: shop/auth.py
description: Password hashing and session tokens.
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/shop/auth.py
tags: [python, 'subsystem:api', 'area:auth', 'security:hardcoded-secret', 'security:weak-hash']
timestamp: '2026-10-03T17:13:18+00:00'
language: python
content_hash: sha256:fcd9a5eb8f1562e4
subsystem: api
parser: ast
loc: 9
fan_in: 1
fan_out: 1
centrality: 0.13098
---

# Summary

Password hashing and session tokens.

# Subsystem

Part of [shop/api.py cluster](/subsystems/api.md).

# Symbols

- `def hash_password()` (L7)
- `def login()` (L10)

# Functions

- `hash_password` (L7-L8)
  - called by: [shop/auth.py::login](/files/shop/auth.py.md)
- `login` (L10-L12)
  - calls: [shop/db.py::find_user](/files/shop/db.py.md), [shop/auth.py::hash_password](/files/shop/auth.py.md)
  - called by: [shop/api.py::handle_login](/files/shop/api.py.md)

# Depends on

- [shop/db.py](/files/shop/db.py.md): uses `find_user` (weight 2)

# Used by

- [shop/api.py](/files/shop/api.py.md): uses `login` (weight 2)

# External dependencies

`hashlib`

# Security notes

- L5 · **high** · hardcoded-secret: string literal assigned to `SECRET_KEY`
- L8 · **medium** · weak-hash: `hashlib.md5()`
