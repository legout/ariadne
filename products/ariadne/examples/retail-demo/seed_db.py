#!/usr/bin/env python3
"""Seed the synthetic demo database (products/ariadne/examples/retail-demo/data/demo.db).

Deterministic by construction: seeded RNG, fixed row counts, fixed currency
rates. Re-running the script onto an existing database drops and rebuilds the
tables, converging to identical content (idempotent).

Designed-in gotchas (documented in the sibling ``seed_notes.md``, consumed by the
authoring agent):
  1. orders contains CANCELLED and RETURNED rows that revenue metrics must
     exclude.
  2. EMEA orders placed before 2024-01-01 are stored in local currency
     (EUR/GBP) WITHOUT conversion — both ``amount`` and ``product_cost`` —
     and must be joined to ``currency_conversion_rate``.

Usage:
    python products/ariadne/examples/retail-demo/seed_db.py [output_db_path]
    # default: products/ariadne/examples/retail-demo/data/demo.db
"""

import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "demo.db"

SEED = 42
CUSTOMER_COUNT = 30
ORDER_COUNT = 500

FIRST_ORDER_DAY = date(2022, 1, 1)
LAST_ORDER_DAY = date(2025, 6, 30)

STATUSES = ("COMPLETED", "CANCELLED", "RETURNED")
STATUS_WEIGHTS = (80, 10, 10)
REGIONS = ("NA", "EMEA", "APAC")
REGION_WEIGHTS = (40, 35, 25)
LOCAL_CURRENCIES = ("EUR", "GBP")  # used only for pre-2024 EMEA rows

# Static, never random: the conversion table is part of the fixture contract.
CONVERSION_RATES = (("EUR", 1.10), ("GBP", 1.27))

COUNTRIES = (
    "United States",
    "Germany",
    "United Kingdom",
    "France",
    "Japan",
    "Canada",
    "Australia",
    "Netherlands",
    "Spain",
    "Sweden",
)

SCHEMA = """
CREATE TABLE customers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE orders (
    order_id        INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers (id),
    order_timestamp TEXT NOT NULL,  -- ISO-8601 'YYYY-MM-DD HH:MM:SS'
    status          TEXT NOT NULL
        CHECK (status IN ('COMPLETED', 'CANCELLED', 'RETURNED')),
    region_code     TEXT NOT NULL CHECK (region_code IN ('NA', 'EMEA', 'APAC')),
    currency        TEXT NOT NULL,
    amount          REAL NOT NULL,
    product_cost    REAL NOT NULL
);

CREATE TABLE currency_conversion_rate (
    currency    TEXT PRIMARY KEY,
    rate_to_usd REAL NOT NULL
);
"""


def random_timestamp(rng: random.Random) -> str:
    day = FIRST_ORDER_DAY + timedelta(days=rng.randint(0, (LAST_ORDER_DAY - FIRST_ORDER_DAY).days))
    moment = datetime(
        day.year,
        day.month,
        day.day,
        rng.randint(0, 23),
        rng.randint(0, 59),
        rng.randint(0, 59),
    )
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def build_customers() -> list[tuple[int, str, str]]:
    return [
        (i, f"Customer {i:03d}", COUNTRIES[i % len(COUNTRIES)])
        for i in range(1, CUSTOMER_COUNT + 1)
    ]


def build_orders(rng: random.Random) -> list[tuple]:
    orders = []
    for order_id in range(1, ORDER_COUNT + 1):
        customer_id = rng.randint(1, CUSTOMER_COUNT)
        order_timestamp = random_timestamp(rng)
        status = rng.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0]
        region = rng.choices(REGIONS, weights=REGION_WEIGHTS, k=1)[0]

        # Gotcha 2: only pre-2024 EMEA rows live in local currency.
        in_local_currency = region == "EMEA" and order_timestamp < "2024-01-01"
        currency = rng.choice(LOCAL_CURRENCIES) if in_local_currency else "USD"

        amount = round(rng.uniform(50.0, 1500.0), 2)
        product_cost = round(amount * rng.uniform(0.50, 0.75), 2)
        orders.append(
            (
                order_id,
                customer_id,
                order_timestamp,
                status,
                region,
                currency,
                amount,
                product_cost,
            )
        )
    return orders


def seed(db_path: Path) -> None:
    rng = random.Random(SEED)
    customers = build_customers()
    orders = build_orders(rng)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            DROP TABLE IF EXISTS orders;
            DROP TABLE IF EXISTS customers;
            DROP TABLE IF EXISTS currency_conversion_rate;
            """
        )
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?, ?, ?)", customers)
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", orders)
        con.executemany("INSERT INTO currency_conversion_rate VALUES (?, ?)", CONVERSION_RATES)
        con.commit()
    finally:
        con.close()


def summarize(db_path: Path) -> str:
    con = sqlite3.connect(db_path)
    try:
        customers = con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        orders = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        cancelled = con.execute(
            "SELECT COUNT(*) FROM orders WHERE status = 'CANCELLED'"
        ).fetchone()[0]
        returned = con.execute("SELECT COUNT(*) FROM orders WHERE status = 'RETURNED'").fetchone()[
            0
        ]
        emea_local = con.execute(
            "SELECT COUNT(*) FROM orders"
            " WHERE region_code = 'EMEA' AND order_timestamp < '2024-01-01'"
        ).fetchone()[0]
        rates = con.execute("SELECT COUNT(*) FROM currency_conversion_rate").fetchone()[0]
    finally:
        con.close()
    return (
        f"Seeded {db_path}\n"
        f"  customers: {customers}\n"
        f"  orders: {orders} (CANCELLED: {cancelled}, RETURNED: {returned})\n"
        f"  pre-2024 EMEA rows in local currency: {emea_local}\n"
        f"  currency_conversion_rate: {rates}"
    )


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    seed(db_path)
    print(summarize(db_path))


if __name__ == "__main__":
    main()
