"""Profiler heuristics (ticket #3): SUMMARIZE + PK/FK heuristics over the demo schema.

Contract consumed by the authoring agent (#4): ``profile(db_path) -> dict`` and
the ``python -m ariadne.profiler --db ... --out profile.json`` CLI. The fixture
db below mirrors ``scripts/seed_db.py``'s schema and gotcha-2 currency
distribution in miniature so this lane validates standalone; one integration
test runs the real seeder once lane #2 merges.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # ariadne/ is not pip-installed until lane #2 lands
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.profiler import profile  # noqa: E402

EXPECTED_COLUMNS = {
    "orders": {
        "order_id",
        "customer_id",
        "order_timestamp",
        "status",
        "region_code",
        "currency",
        "amount",
        "product_cost",
    },
    "customers": {"id", "name", "country"},
    "currency_conversion_rate": {"currency", "rate_to_usd"},
}

def make_demo_db(db_path: Path) -> Path:
    """Miniature demo.db: same schema, same USD-dominant currency distribution."""
    rows = []
    for i in range(1, 25):
        currency = "USD" if i > 4 else ("EUR" if i % 2 == 0 else "GBP")  # 20 USD / 2 EUR / 2 GBP
        rows.append(
            (
                i,
                (i % 3) + 1,
                "2023-05-01 10:00:00",
                "COMPLETED" if i % 4 else "CANCELLED",
                ("NA", "EMEA", "APAC")[i % 3],
                currency,
                100.0 + i,
                60.0 + (i % 5),
            )
        )
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE customers (
                id      INTEGER PRIMARY KEY,
                name    TEXT NOT NULL,
                country TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE orders (
                order_id        INTEGER PRIMARY KEY,
                customer_id     INTEGER NOT NULL REFERENCES customers (id),
                order_timestamp TEXT NOT NULL,
                status          TEXT NOT NULL,
                region_code     TEXT NOT NULL,
                currency        TEXT NOT NULL,
                amount          REAL NOT NULL,
                product_cost    REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE currency_conversion_rate (
                currency    TEXT PRIMARY KEY,
                rate_to_usd REAL NOT NULL
            )
            """
        )
        con.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [(1, "A", "US"), (2, "B", "DE"), (3, "C", "JP")],
        )
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.executemany(
            "INSERT INTO currency_conversion_rate VALUES (?, ?)",
            [("EUR", 1.10), ("GBP", 1.27)],
        )
        con.commit()
    finally:
        con.close()
    return db_path


@pytest.fixture()
def demo_db(tmp_path):
    return make_demo_db(tmp_path / "demo.db")


def test_expected_columns_present(demo_db):
    tables = profile(demo_db)["tables"]
    assert set(tables) == set(EXPECTED_COLUMNS)
    for table, expected in EXPECTED_COLUMNS.items():
        assert set(tables[table]["columns"]) == expected


def test_pk_and_fk_heuristics(demo_db):
    tables = profile(demo_db)["tables"]
    assert "order_id" in tables["orders"]["primary_key_candidates"]
    assert "id" in tables["customers"]["primary_key_candidates"]
    assert tables["currency_conversion_rate"]["columns"]["currency"]["pk_candidate"] is True

    fks = tables["orders"]["foreign_key_candidates"]
    assert {
        "column": "customer_id",
        "references_table": "customers",
        "references_column": "id",
        "match_ratio": 1.0,
    } in fks
    flagged = {fk["column"] for fk in fks}
    assert "order_id" not in flagged  # a table's own PK is not an FK candidate


def test_currency_distribution_spike_detectable(demo_db):
    """Gotcha-2 signal: the profile must expose the distribution spike statistics.

    No business rules here — just the numbers the authoring agent (#4) combines
    with seed notes (currency column dominated by one value, tiny rate lookup).
    """
    tables = profile(demo_db)["tables"]
    currency = tables["orders"]["columns"]["currency"]
    assert currency["distinct_count"] == 3
    assert currency["top_values"][0] == {"value": "USD", "count": 20}
    assert currency["top_value_share"] >= 0.8
    # null-spike statistics are part of every column's profile
    assert currency["null_count"] == 0
    assert currency["null_ratio"] == 0.0
    assert tables["currency_conversion_rate"]["row_count"] == 2


def test_null_spike_surfaces(demo_db):
    """A column with nulls reports them; NOT NULL columns report zero."""
    con = sqlite3.connect(demo_db)
    con.execute("ALTER TABLE orders ADD COLUMN discount REAL")
    con.execute("UPDATE orders SET discount = NULL WHERE order_id % 2 = 0")
    con.execute("UPDATE orders SET discount = 5.0 WHERE order_id % 2 = 1")
    con.commit()
    con.close()

    col = profile(demo_db)["tables"]["orders"]["columns"]["discount"]
    assert col["null_count"] == 12
    assert col["null_ratio"] == 0.5


def test_cli_writes_profile_json(demo_db, tmp_path):
    out = tmp_path / "profile.json"
    result = subprocess.run(
        [sys.executable, "-m", "ariadne.profiler", "--db", str(demo_db), "--out", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    written = json.loads(out.read_text())
    assert json.loads(result.stdout) == written  # stdout and file agree
    assert written["tables"]["orders"]["columns"]["currency"]["top_value_share"] >= 0.8


def _seed_real_demo_db(tmp_path):
    seed = REPO_ROOT / "scripts" / "seed_db.py"
    if not seed.is_file():
        pytest.skip("scripts/seed_db.py arrives with lane #2")
    db = tmp_path / "demo.db"
    subprocess.run([sys.executable, str(seed), str(db)], check=True, capture_output=True)
    return db


def test_real_demo_db_contract(tmp_path):
    """Same contract against the genuine seeder once lane #2 lands."""
    tables = profile(_seed_real_demo_db(tmp_path))["tables"]
    for table, expected in EXPECTED_COLUMNS.items():
        assert set(tables[table]["columns"]) == expected
    assert {
        "column": "customer_id",
        "references_table": "customers",
        "references_column": "id",
        "match_ratio": 1.0,
    } in tables["orders"]["foreign_key_candidates"]
    currency = tables["orders"]["columns"]["currency"]
    assert currency["distinct_count"] == 3
    # Real cross-lane contract (scripts/seed_db.py, ticket #2): USD is a clear
    # majority; pre-2024 EMEA rows keep EUR/GBP as minority local currencies.
    # Asserted as properties of the seeder, not a calibrated share float.
    assert currency["top_values"][0]["value"] == "USD"
    assert currency["top_value_share"] > 0.5
    assert {"EUR", "GBP"} <= {
        entry["value"] for entry in currency["top_values"][1:]
    }
