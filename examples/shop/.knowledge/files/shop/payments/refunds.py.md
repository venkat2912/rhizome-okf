---
type: Source File
title: shop/payments/refunds.py
description: 'Refund workflow: validates the order then calls the gateway.'
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/shop/payments/refunds.py
tags: [python, 'subsystem:payments-refunds']
timestamp: '2026-10-03T17:13:18+00:00'
language: python
content_hash: sha256:bc3f967a70e15816
subsystem: payments-refunds
parser: ast
loc: 11
fan_in: 1
fan_out: 2
centrality: 0.19856
---

# Summary

Refund workflow: validates the order then calls the gateway.

# Subsystem

Part of [shop/payments · refunds.py](/subsystems/payments-refunds.md).

# Symbols

- `class RefundPolicy` (L5): Decides whether an order is refundable.
  - methods: `allowed`
- `def refund_order()` (L10)

# Functions

- `RefundPolicy.allowed` (L7-L8)
- `refund_order` (L10-L13)
  - calls: [shop/db.py::save_order](/files/shop/db.py.md), [shop/payments/gateway.py::refund](/files/shop/payments/gateway.py.md)
  - called by: [shop/api.py::handle_refund](/files/shop/api.py.md)
  - name-only calls: `allowed`

# Depends on

- [shop/payments/gateway.py](/files/shop/payments/gateway.py.md): uses `refund` (weight 2)
- [shop/db.py](/files/shop/db.py.md): uses `save_order` (weight 2)

# Used by

- [shop/api.py](/files/shop/api.py.md): uses `refund_order` (weight 2)

# Requirements

- [Partial refunds](/requirements/refunds.md)
