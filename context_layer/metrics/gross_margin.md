---
type: metric
status: draft
title: Gross margin
description: Gross margin over billable orders.
tags:
- metric
- margin
sources:
- orders
- currency_conversion_rate
- id: order-status-billing
  resource: policies/order-status-billing.md
governed_by: semantic_layer orders::gross_margin
dimensions:
- status
grain:
  primary_key:
  - order_id
  cardinality_enforcement: STRICT_1_TO_1
generated:
  by: ariadne-author
  at: '2026-09-18T12:06:35+00:00'
verified: []
stale_after: '2026-12-17'
---

# Gross margin

Rule 1: CANCELLED and RETURNED orders are not revenue.
Rule 2: pre-2024 EMEA rows are local currency: multiply both figures by rate_to_usd.
