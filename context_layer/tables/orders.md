---
type: table
status: draft
title: Orders
description: One row per placed order.
tags:
- table
- orders
sources:
- id: demo.main.orders
  resource: examples/retail-demo/data/demo.db
  title: Orders
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

# Orders

Join hints: customer_id -> customers.id (N:1).
