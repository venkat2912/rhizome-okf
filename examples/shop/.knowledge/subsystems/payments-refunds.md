---
type: Subsystem
title: shop/payments · refunds.py
description: '2 files centred on `shop/payments/refunds.py`. Most central: `shop/payments/refunds.py`, `shop/payments/gateway.py`. Hub purpose: Refund workflow: validates the order then calls the gateway.'
tags: [subsystem, 'security:tls-verify-disabled']
timestamp: '2026-09-25T20:35:11+00:00'
level: 1
size: 2
hub: shop/payments/refunds.py
grouping: leiden
cohesion: 0.333
connected: true
---

# Summary

2 files centred on `shop/payments/refunds.py`. Most central: `shop/payments/refunds.py`, `shop/payments/gateway.py`. Hub purpose: Refund workflow: validates the order then calls the gateway.

# Members

Ranked by centrality in the dependency graph.

- [shop/payments/refunds.py](/files/shop/payments/refunds.py.md): Refund workflow: validates the order then calls the gateway.
- [shop/payments/gateway.py](/files/shop/payments/gateway.py.md): Talks to the external payment provider.

# Depends on subsystems

- [shop/api.py cluster](/subsystems/api.md): 1 import edges (weight 2)

# Used by subsystems

- [shop/api.py cluster](/subsystems/api.md): 1 import edges (weight 2)

# Security notes

- tls-verify-disabled ×1: [shop/payments/gateway.py](/files/shop/payments/gateway.py.md)

# Requirements

- [Partial refunds](/requirements/refunds.md)
