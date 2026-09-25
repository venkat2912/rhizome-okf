---
type: Index
title: Subsystems
description: 4 subsystems found by Leiden community detection on the import graph.
timestamp: '2026-09-25T20:35:11+00:00'
---

# Subsystems

- [shop/api.py cluster](/subsystems/api.md) (4 files, cohesion 0.667): 4 files centred on `shop/api.py` (1 test file). Most central: `shop/api.py`, `shop/db.py`, `shop/auth.py`. Hub purpose: HTTP handlers.
- [shop/payments · refunds.py](/subsystems/payments-refunds.md) (2 files, cohesion 0.333): 2 files centred on `shop/payments/refunds.py`. Most central: `shop/payments/refunds.py`, `shop/payments/gateway.py`. Hub purpose: Refund workflow: validates the order then calls the gateway.
- [Unlinked files in shop](/subsystems/unlinked-shop.md) (2 files, cohesion 0.0): 2 files centred on `shop/__init__.py`. Most central: `shop/__init__.py`, `shop/payments/__init__.py`. Hub purpose: Toy e-commerce backend used as a test fixture.
- [Unlinked files in scripts](/subsystems/unlinked-scripts.md) (1 file, cohesion 0.0): 1 file centred on `scripts/cleanup.py`. Most central: `scripts/cleanup.py`.
