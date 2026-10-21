---
id: entity:recognized-revenue
title: Recognized Revenue
entity_types: [metric]
tags: [retail]
summary: Recognized revenue in EUR, excluding cancelled orders.
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
    metric: revenue
  required_policies:
    - namespace: urn:example:local-retail
      entity_id: entity:cancelled-orders
  native:
    type: metric
    status: stable
    title: Recognized Revenue
    description: Recognized revenue in EUR, excluding cancelled orders.
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

# Recognized Revenue

Recognized revenue in EUR, excluding cancelled orders. Read the full Cancelled Orders policy with this metric. Ariadne owns
the executable definition in semantic_layer/models/retail_sales.yml.
