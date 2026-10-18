---
id: "entity:retail-revenue"
title: "Retail Revenue (Metric)"
entity_types:
  - metric
tags:
  - retail
  - finance
summary: "Total recognized retail revenue after returns, bound to the Retail Return Policy."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "src-finance-model"
    title: "Finance model review, 2026-10-05"
ariadne_profile:
  version: 1
  kind: metric
  metric_ref:
    model: "retail_sales"
    metric: "revenue"
  required_policies:
    - namespace: "urn:demo:retail"
      entity_id: "entity:retail-return-policy"
  native:
    type: metric
    status: stable
    title: "Retail revenue"
    description: "Total recognized revenue after returns, per the Retail Return Policy."
    tags:
      - finance
    stale_after: 2027-06-30
    sources:
      - id: "pol-return"
        title: "Governing policy"
        resource: "policies/retail-return-policy.md"
    governed_by: "policies/retail-return-policy.md"
    dimensions:
      - store
      - product_category
      - order_date
    grain:
      primary_key:
        - order_number
      cardinality_enforcement: "strict_1_to_1"
---

# Retail Revenue (Metric)

Retail revenue is the total of recognized sales in the retail channel, reduced
by recognized refunds in the month the refund is recognized (Retail Return
Policy, rule 5). Every figure reported under this metric cites that policy.

The executable definition, its compilation and its independent numerical
validation are owned by the Ariadne semantic layer; this page curates the
business meaning and the mandatory policy context only.
