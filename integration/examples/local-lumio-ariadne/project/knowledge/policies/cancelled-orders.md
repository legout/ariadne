---
id: entity:cancelled-orders
title: Cancelled Orders
entity_types: [policy]
tags: [retail, revenue]
summary: Cancelled orders do not count as recognized revenue or completed orders.
lifecycle: approved
visibility: public
sources:
  - id: example-owner
    title: Authored synthetic example rule
ariadne_profile:
  version: 1
  kind: policy
  required_policies: []
  native:
    type: policy
    status: stable
    title: Cancelled Orders
    description: Cancelled orders do not count as recognized revenue or completed orders.
    tags: [policy, retail]
    sources:
      - id: cancelled-orders
        resource: policies/cancelled-orders.md
        title: Cancelled Orders
---

# Cancelled Orders

Exclude orders whose status is cancelled from recognized revenue and the
completed-order count. Revenue is expressed in EUR. Returns and taxes are
outside this synthetic example. Keep this full rule with both results.
