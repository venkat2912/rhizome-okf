---
type: Source File
title: shop/payments/gateway.py
description: Talks to the external payment provider.
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/shop/payments/gateway.py
tags: [python, 'subsystem:payments-refunds', 'security:tls-verify-disabled']
timestamp: '2026-10-03T17:13:18+00:00'
language: python
content_hash: sha256:6e0e0bb7effa6391
subsystem: payments-refunds
parser: ast
loc: 6
fan_in: 1
fan_out: 0
centrality: 0.07952
---

# Summary

Talks to the external payment provider.

# Subsystem

Part of [shop/payments · refunds.py](/subsystems/payments-refunds.md).

# Symbols

- `def charge()` (L4)
- `def refund()` (L7)

# Functions

- `charge` (L4-L5)
- `refund` (L7-L8)
  - called by: [shop/payments/refunds.py::refund_order](/files/shop/payments/refunds.py.md)

# Depends on

None.

# Used by

- [shop/payments/refunds.py](/files/shop/payments/refunds.py.md): uses `refund` (weight 2)

# External dependencies

`requests`

# Security notes

- L5 · **high** · tls-verify-disabled: `requests.post(..., verify=False)`

# Requirements

- [Partial refunds](/requirements/refunds.md)
