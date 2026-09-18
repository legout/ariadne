---
type: computation
title: "sanctioned SQL \u2014 orders::gross_margin"
description: 'Sanctioned computation: SQL, runtime, attester.'
tags:
- computation
status: draft
governed_by: semantic_layer orders::gross_margin
runtime: duckdb
attester: tests/test_evals.py
sources:
- id: model-orders
  resource: ../../semantic_layer/models/orders.yml
  title: orders OSI model
generated:
  by: ariadne-author
  at: '2026-09-18T12:06:35+00:00'
verified: []
stale_after: '2026-12-17'
---

# Sanctioned computation

Sanctioned SQL (ANSI_SQL, `semantic_layer/models/orders.yml`); compile gate `ariadne.validate`; execution DuckDB via `ariadne.serve`; attestation `tests/test_evals.py` golden values. Business rules: cited metric page.

```sql
(gross_revenue - cogs) / NULLIF(gross_revenue, 0)
```
