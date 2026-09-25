---
type: Requirement
title: Partial refunds
description: Customers must be able to request a partial refund. Extend `refund_order` and the RefundPolicy so that only part of the amount is returned through the gateway.
resource: repo://docs/requirements/refunds.md
tags: [requirement]
timestamp: '2026-09-25T20:35:11+00:00'
---

# Implemented by

- [shop/payments/refunds.py](/files/shop/payments/refunds.py.md) (matched: `RefundPolicy`, `refund_order`, file name)
- [shop/payments/gateway.py](/files/shop/payments/gateway.py.md) (matched: `refund`, file name)

# Text

## Partial refunds

Customers must be able to request a partial refund. Extend `refund_order` and the
RefundPolicy so that only part of the amount is returned through the gateway.
