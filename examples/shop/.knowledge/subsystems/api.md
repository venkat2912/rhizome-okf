---
type: Subsystem
title: shop/api.py cluster
description: '4 files centred on `shop/api.py` (1 test file). Most central: `shop/api.py`, `shop/db.py`, `shop/auth.py`. Hub purpose: HTTP handlers.'
tags: [subsystem, 'security:hardcoded-secret', 'security:sql-string-building', 'security:weak-hash']
timestamp: '2026-09-26T10:23:34+00:00'
level: 1
size: 4
hub: shop/api.py
grouping: leiden
cohesion: 0.667
connected: true
---

# Summary

4 files centred on `shop/api.py` (1 test file). Most central: `shop/api.py`, `shop/db.py`, `shop/auth.py`. Hub purpose: HTTP handlers.

# Members

Ranked by centrality in the dependency graph.

- [shop/api.py](/files/shop/api.py.md): HTTP handlers.
- [shop/db.py](/files/shop/db.py.md): Database access helpers.
- [shop/auth.py](/files/shop/auth.py.md): Password hashing and session tokens.
- [tests/test_api.py](/files/tests/test_api.py.md): Test module defining 1 public function (test_login).

# Depends on subsystems

- [shop/payments · refunds.py](/subsystems/payments-refunds.md): 1 import edges (weight 2)

# Used by subsystems

- [shop/payments · refunds.py](/subsystems/payments-refunds.md): 1 import edges (weight 2)

# Security notes

- sql-string-building ×1: [shop/db.py](/files/shop/db.py.md)
- hardcoded-secret ×1: [shop/auth.py](/files/shop/auth.py.md)
- weak-hash ×1: [shop/auth.py](/files/shop/auth.py.md)
