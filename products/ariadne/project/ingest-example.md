# Renewals sandbox — working notes (CS weekly, 2026-09-10)

Scratch notes on the `renewals` table in the sandbox warehouse. Keep with the
data dictionary until the renewal model is authored.

## What one row is

One row per account renewal event. Columns: `account_id`, `renewal_date`,
`arr_usd`, `term_months`, `status`, `owner_email`. An account can renew at
most once per day, so (`account_id`, `renewal_date`) is unique across the
table.

## Statuses

- `RENEWED` — contract renewed at the same or higher ARR.
- `EXPANDED` — renewal with an ARR uplift (seats or tier).
- `DOWNGRADED` — renewal at reduced ARR; still a booked renewal.
- `CHURNED` — the account declined; the row records the ARR that walked away.

## Policy (finance): churned ARR is not expansion

Finance counts expansion and retention only over `RENEWED`, `EXPANDED` and
`DOWNGRADED` renewals. `CHURNED` rows must never be summed into expansion,
net-retention or renewal-ARR totals — they record lost ARR, not booked ARR.
