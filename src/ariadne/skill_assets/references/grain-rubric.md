# Grain rubric — resolving multi-cardinality joins (ADR-0006)

The compiler aggregates at joined-row grain and does NOT prevent fan-out
(Datus-ai/Datus-agent#1426): a naive 1:N join silently inflates parent-grain
sums. Before any join enters a metric source, verify each join key is unique on
the joined side; if it is not, resolve the relationship with one of the five
patterns below. In ariadne this is enforced, not advisory: `define_metric` and
the validate audit reject non-grain-preserving sources before compile.

## 1. Upstream conditional pivot

- **Trigger:** 1:N child rows that are discrete, bounded attributes of the
  parent (EAV logs, status milestones, standardized test runs).
- **Fix:** pivot the child into dedicated columns with conditional aggregation
  `GROUP BY parent_pk`; dedupe re-runs with
  `ROW_NUMBER() OVER (PARTITION BY entity_id, key ORDER BY ts DESC) = 1`;
  join the parent to the pivoted view 1:1; register at the parent grain.
- **Example:** orders → milestones (`PLACED`/`SHIPPED`/`DELIVERED`) becomes
  `placed_at`, `shipped_at`, `delivered_at` columns — one row per `order_id`.

## 2. Child-grain fact model

- **Trigger:** 1:N children with unbounded, heterogeneous, or dynamic keys —
  pivoting into fixed columns is not viable.
- **Fix:** model strictly at the child grain; denormalize parent attributes
  down as dimensions only; parent-level additive measures (`SUM`) are banned —
  count parents with `COUNT(DISTINCT parent_id)`.
- **Example:** model at `order_item_id` grain: `SUM(line_amount)` is fine,
  `SUM(order_shipping_fee)` is forbidden (it multiplies by items per order).

## 3. Array / set rollup

- **Trigger:** N:M bridge that only LABELS entity A (tags, categories, error
  codes, certifications) — no measures of its own.
- **Fix:** do not join the bridge; upstream, roll the labels into an array or
  delimited string per A's key (`ARRAY_AGG`/`STRING_AGG ... GROUP BY a_id`);
  register at A's grain; filter downstream with array containment.
- **Example:** products ↔ tags becomes a `tags` array column per `product_id`;
  `SUM(inventory_value)` stays uncorrupted.

## 4. Bridge interaction grain

- **Trigger:** N:M where the pair itself is the event and carries its own
  measures (sessions, assignments, engagements).
- **Fix:** register at the bridge key (`pair_id` or `(a_id, b_id)`); attributes
  from both sides become dimensions; `SUM` only on interaction-native numbers;
  count the entities themselves with `COUNT(DISTINCT)`.
- **Example:** campaign × customer engagements at `(campaign_id, customer_id)`:
  `SUM(interaction_duration_seconds)` is fine, `SUM(customer_lifetime_value)`
  is forbidden.

## 5. Fact weight allocation

- **Trigger:** a parent-grain additive metric must be carried across a 1:N or
  N:M relationship without inflating its total.
- **Fix:** allocate upstream with an analytic coefficient:
  `weight = 1.0 / COUNT(*) OVER (PARTITION BY parent_id)`; register
  `SUM(raw_value * weight)` as the certified metric.
- **Example:** order shipping cost split over line items:
  `line_shipping_share = shipping_cost * line_price / order_total`.

## In ariadne

`define_metric` sources and authored dataset models must satisfy the guard: a
joined key that is not unique on the joined side, a cross/`ON TRUE` join, or an
unprovable predicate is rejected before compile. Pre-aggregate the many side to
the fact grain inside `source` (patterns 1–5), then resubmit.
