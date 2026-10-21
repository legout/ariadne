---
id: entity:completed-orders
title: Completed Orders
entity_types: [metric]
tags: [retail]
summary: Count of orders not cancelled.
lifecycle: approved
visibility: public
sources:
  - id: example-owner
    title: Authored synthetic example rule
ariadne_profile:
  version: 1
  kind: metric
  metric_ref:
    model: retail_sales
    metric: completed_orders
  required_policies:
    - namespace: urn:example:local-retail
      entity_id: entity:cancelled-orders
  native:
    type: metric
    status: stable
    title: Completed Orders
    description: Count of orders not cancelled.
    tags: [metric, retail]
    sources:
      - id: cancelled-orders
        resource: policies/cancelled-orders.md
        title: Cancelled Orders
    governed_by: policies/cancelled-orders.md
    dimensions: [status]
    grain:
      primary_key: [id]
      cardinality_enforcement: strict_1_to_1
---

# Completed Orders

Count of orders not cancelled. Read the full Cancelled Orders policy with this metric. Ariadne owns
the executable definition in semantic_layer/models/retail_sales.yml.
