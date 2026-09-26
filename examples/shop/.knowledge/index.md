---
type: Index
title: Rizhome
description: 'Code knowledge bundle for Rizhome: subsystems, files, dependencies, security notes.'
resource: https://github.com/venkat2912/Rizhome
timestamp: '2026-09-26T10:23:34+00:00'
source_digest: 0fd647343992eac2
profile: okf-code/0.1
---

# Overview

`Rizhome`: 9 Python files, 7 internal import edges, 4 subsystems (0 components). Subsystems are communities found by the Leiden algorithm on the weighted import graph, so they reflect how code is actually coupled rather than how folders are laid out.

# How to navigate

1. Read the subsystem list below and pick the relevant one.
2. Open its concept for members, cross-subsystem dependencies and security notes.
3. Open individual file concepts and follow *Depends on* / *Used by* links.
4. [All files](/files/index.md) · [Change log](/log.md) · [Requirements](/requirements/index.md)

# Subsystems

- [shop/api.py cluster](/subsystems/api.md) (4 files): 4 files centred on `shop/api.py` (1 test file). Most central: `shop/api.py`, `shop/db.py`, `shop/auth.py`. Hub purpose: HTTP handlers.
- [shop/payments · refunds.py](/subsystems/payments-refunds.md) (2 files): 2 files centred on `shop/payments/refunds.py`. Most central: `shop/payments/refunds.py`, `shop/payments/gateway.py`. Hub purpose: Refund workflow: validates the order then calls the gateway.
- [Unlinked files in shop](/subsystems/unlinked-shop.md) (2 files): 2 files centred on `shop/__init__.py`. Most central: `shop/__init__.py`, `shop/payments/__init__.py`. Hub purpose: Toy e-commerce backend used as a test fixture.
- [Unlinked files in scripts](/subsystems/unlinked-scripts.md) (1 file): 1 file centred on `scripts/cleanup.py`. Most central: `scripts/cleanup.py`.

# Security hotspots

- [scripts/cleanup.py](/files/scripts/cleanup.py.md): shell-exec
- [shop/auth.py](/files/shop/auth.py.md): hardcoded-secret
- [shop/db.py](/files/shop/db.py.md): sql-string-building
- [shop/payments/gateway.py](/files/shop/payments/gateway.py.md): tls-verify-disabled
