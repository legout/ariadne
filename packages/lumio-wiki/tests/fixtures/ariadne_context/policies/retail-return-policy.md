---
id: "entity:retail-return-policy"
title: "Retail Return Policy"
entity_types:
  - policy
tags:
  - retail
  - returns
summary: "Normative rules for accepting and refunding customer returns in the retail channel."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "src-returns-handbook"
    title: "Returns Handbook, 2026 edition"
ariadne_profile:
  version: 1
  kind: policy
  required_policies: []
  native:
    type: policy
    title: "Retail Return Policy"
    description: "Normative rules for accepting and refunding customer returns."
    tags:
      - policy
      - returns
    status: stable
    stale_after: 2027-06-30
    verified:
      - by: "human:owner@retail.example"
        on: 2026-10-01
    sources:
      - id: "okf-policy-return"
        title: "Returns policy page"
        resource: "policies/retail-return-policy.md"
---

# Retail Return Policy

## Scope

This policy governs every customer return in the retail channel, in stores and
in the web shop, for articles sold under the retail trading name. It binds all
sales, service and finance processes that recognize revenue or issue refunds.

## Rules

1. A customer may return any unused article within 30 days of purchase. The
   30-day window starts on the purchase date printed on the receipt.
2. Returns are only accepted with a valid receipt or a verifiable order
   number. An order number is verifiable when it resolves in the order system
   of the selling channel.
3. Refunds are always issued to the original payment method. Store credit is
   issued only when the original payment method is provably unavailable, for
   example a expired card; the reason is recorded on the refund record.
4. Returned articles are inspected before a refund is recognized. Articles
   that fail inspection are returned to the customer at the company's expense
   and no refund is recognized for them.
5. Revenue is reduced by recognized refunds in the calendar month in which the
   refund is recognized, not in the month of the original sale.

## Responsibilities

Store managers approve in-store returns up to 500 EUR per receipt. The
customer service team approves web-shop returns and every return above that
limit. Finance owns the recognition rules and this policy text.
