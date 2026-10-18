---
id: "entity:order-number"
title: "Order Number"
entity_types:
  - reference
tags:
  - retail
  - identifiers
summary: "The shared order-number concept across store-local and global representations."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "src-owner-rule"
    title: "Owner clarification, 2026-09-28"
ariadne_profile:
  version: 1
  kind: reference
  native:
    type: reference
    title: "Order Number"
    description: >-
      The shared order-number concept: a globally unique composite order
      number and the store-local number it is built from.
    tags:
      - identifier
    aliases:
      - order no
    stale_after: 2027-09-30
    sources:
      - id: "okf-ref-order"
        title: "Order number reference page"
      - id: "src-owner-rule"
        title: "Owner clarification, 2026-09-28"
    ariadne:
      version: 1
      reference_role: identifier
      representations:
        - id: global-order-number
          aliases:
            - global order number
          fields:
            - resource: "retail.main/orders"
              column: "order_number"
          scope: []
          description: >-
            The globally unique composite order number, for example ABC123123.
        - id: local-order-number
          aliases:
            - local order number
          fields:
            - resource: "retail.main/orders"
              column: "store_id"
            - resource: "retail.main/orders"
              column: "local_order_number"
          scope:
            - resource: "retail.main/orders"
              column: "store_id"
          description: >-
            The store-local order number; unique only within one store.
      mappings:
        - id: store-prefix-composition
          family: prefix
          from: local-order-number
          to: global-order-number
          claim: asserted
          source_ids:
            - "src-owner-rule"
    ariadne_evidence:
      store-prefix-composition:
        - id: "mev:prefix-2026-09-28"
          digest: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
          family: prefix
          outcome: supported
          designation: sampled
          comparison_basis: containment
          tested_left: 1200
          tested_right: 3500
          eligible_left: 1200
          eligible_right: 3500
          matched_left_in_right: 1198
          matched_right_in_left: 1198
          mismatch_count: 2
          observed_at: "2026-09-28T14:05:00+02:00"
---

# Order Number

An order in the retail channel is identified twice: once locally in the store
that took it, and once globally across the whole company.

The owner confirmed the construction on 2026-09-28: the global order number is
the store prefix concatenated with the local order number.

```text
local identity: (store_id, local_order_number)
(ABC, 123123) -> ABC123123
(XYZ, 123123) -> XYZ123123
```

Both stores can carry the local number `123123`; the prefixed global numbers
`ABC123123` and `XYZ123123` remain two different orders. Local numbers are
never compared across stores, and a leading zero in a local number such as
`00123` is preserved as written.
