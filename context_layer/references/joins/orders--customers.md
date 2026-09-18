---
type: reference
status: draft
title: Orders to Customers
description: Many orders to one customer; the joined key is proven unique.
tags:
- reference
- join
sources:
- id: demo.main.customers
  resource: examples/retail-demo/data/demo.db
  title: Customers
generated:
  by: ariadne-author
  at: '2026-09-18T12:06:35+00:00'
verified: []
stale_after: '2026-12-17'
---

# Orders <-> Customers

Grain-safety: many-to-one from the fact side, per ADR-0006 the join is
grain-preserving (joined side unique, no fan-out).
