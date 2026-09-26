---
type: Requirement
title: Partial refunds
description: Customers must be able to request a partial refund. Extend `refund_order` and the RefundPolicy so that only part of the amount is returned through the gateway.
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/docs/requirements/refunds.md
tags: [requirement]
timestamp: '2026-09-26T10:23:34+00:00'
---

# Implemented by

- [shop/payments/refunds.py](/files/shop/payments/refunds.py.md) (matched: `RefundPolicy`, `refund_order`, file name)
- [shop/payments/gateway.py](/files/shop/payments/gateway.py.md) (matched: `refund`, file name)

# Text

## Partial refunds

Customers must be able to request a partial refund. Extend `refund_order` and the
RefundPolicy so that only part of the amount is returned through the gateway.
