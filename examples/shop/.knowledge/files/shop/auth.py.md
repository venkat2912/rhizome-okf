---
type: Source File
title: shop/auth.py
description: Password hashing and session tokens.
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/shop/auth.py
tags: [python, 'subsystem:api', 'area:auth', 'security:hardcoded-secret', 'security:weak-hash']
timestamp: '2026-09-26T10:23:34+00:00'
language: python
content_hash: sha256:fcd9a5eb8f1562e4
subsystem: api
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

# Depends on

- [shop/db.py](/files/shop/db.py.md): uses `find_user`

# Used by

- [shop/api.py](/files/shop/api.py.md): uses `login`

# External dependencies

`hashlib`

# Security notes

- L5 · **high** · hardcoded-secret: string literal assigned to `SECRET_KEY`
- L8 · **medium** · weak-hash: `hashlib.md5()`
