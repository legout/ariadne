# Seed notes — demo database (`data/demo.db`)

Notes from the data owner. This is the business documentation that statistics
cannot derive: profile the schema all you like, but the rules below are the
reason the numbers come out right. If a generated metric contradicts a rule
here, the metric is wrong, not the rule.

## What this database is

A synthetic e-commerce transaction extract, 2022-01-01 through 2025-06-30.
Three regions (`NA`, `EMEA`, `APAC`), 30 customers, 500 orders. Small enough
to eyeball, messy enough to be honest.

## Tables

### `orders` — one row per placed order

| column           | meaning |
| :--------------- | :------ |
| `order_id`       | Primary key. |
| `customer_id`    | FK to `customers.id`. |
| `order_timestamp`| When the order was placed, ISO-8601 text (`YYYY-MM-DD HH:MM:SS`). |
| `status`         | One of `COMPLETED`, `CANCELLED`, `RETURNED`. |
| `region_code`    | Sales region of the order: `NA`, `EMEA`, or `APAC`. |
| `currency`       | Currency the row's money figures are denominated in. |
| `amount`         | Billed revenue for the order. |
| `product_cost`   | Direct cost of goods for the order. |

### `customers` — one row per customer

| column    | meaning |
| :-------- | :------ |
| `id`      | Primary key. |
| `name`    | Display name. |
| `country` | Country of registration. |

### `currency_conversion_rate` — lookup, not a fact table

| column        | meaning |
| :------------ | :------ |
| `currency`    | Currency code (`EUR`, `GBP`). |
| `rate_to_usd` | Multiply a local-currency amount by this to get US dollars. |

## Rules you must follow (the gotchas)

1. **Cancelled and returned orders are not revenue.** Rows with
   `status IN ('CANCELLED', 'RETURNED')` must be excluded from every revenue,
   margin, and billed-order-count number. They stay in the table because the
   operations team needs cancellation rates — that is their only use here.

2. **Pre-2024 EMEA rows are in local currency, unconverted.** Every EMEA order
   placed before 2024-01-01 has `amount` **and** `product_cost` stored in the
   local currency given by its `currency` column (`EUR` or `GBP`). Before
   aggregating, multiply both figures by `rate_to_usd` from
   `currency_conversion_rate` joined on `currency`.
   Everything else is already USD: EMEA rows from 2024 onward were migrated to
   USD at cutover, and NA/APAC were always USD — do **not** convert those, or
   you will silently deflate them.

## Metric definitions

- **Gross margin** by region: over non-cancelled, non-returned orders,
  `(sum(amount_converted) - sum(product_cost_converted)) / sum(amount_converted)`,
  where `*_converted` applies rule 2. This is a ratio of sums, not an average
  of per-row margins.
- **Order count** by region: count of non-cancelled, non-returned orders.

The reference answers live in `tests/fixtures/expected_metrics.json`; if a
computed metric disagrees with that fixture, the computation is wrong.

## What profiling will not tell you

- That `CANCELLED`/`RETURNED` rows must be excluded — the column looks like an
  ordinary low-cardinality string.
- That the currency cutover happened at exactly 2024-01-01 and only for EMEA —
  nothing in the row data marks the boundary; `currency` is the only visible
  trace, and assuming "convert any non-USD row" happens to coincide with the
  rule today but is not the rule.
- That `product_cost` needs the same conversion as `amount`.
