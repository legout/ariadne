"""Profiler heuristics (ticket #3): SUMMARIZE + PK/FK heuristics over the demo schema.

Contract consumed by the authoring agent (#4): ``profile(db_path) -> dict`` and
the ``python -m ariadne.profiler --db ... --out profile.json`` CLI. The fixture
db below mirrors ``scripts/seed_db.py``'s schema and gotcha-2 currency
distribution in miniature so this lane validates standalone; one integration
test runs the real seeder once lane #2 merges.
"""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

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
    rows = [
        (1, 2, "2023-05-01 10:00:00", "COMPLETED", "EMEA", "GBP", 101.0, 61.0),
        (2, 3, "2023-05-01 10:00:00", "COMPLETED", "APAC", "EUR", 102.0, 62.0),
        (3, 1, "2023-05-01 10:00:00", "COMPLETED", "NA", "GBP", 103.0, 63.0),
        (4, 2, "2023-05-01 10:00:00", "CANCELLED", "EMEA", "EUR", 104.0, 64.0),
        (5, 3, "2023-05-01 10:00:00", "COMPLETED", "APAC", "USD", 105.0, 60.0),
        (6, 1, "2023-05-01 10:00:00", "COMPLETED", "NA", "USD", 106.0, 61.0),
        (7, 2, "2023-05-01 10:00:00", "COMPLETED", "EMEA", "USD", 107.0, 62.0),
        (8, 3, "2023-05-01 10:00:00", "CANCELLED", "APAC", "USD", 108.0, 63.0),
        (9, 1, "2023-05-01 10:00:00", "COMPLETED", "NA", "USD", 109.0, 64.0),
        (10, 2, "2023-05-01 10:00:00", "COMPLETED", "EMEA", "USD", 110.0, 60.0),
        (11, 3, "2023-05-01 10:00:00", "COMPLETED", "APAC", "USD", 111.0, 61.0),
        (12, 1, "2023-05-01 10:00:00", "CANCELLED", "NA", "USD", 112.0, 62.0),
        (13, 2, "2023-05-01 10:00:00", "COMPLETED", "EMEA", "USD", 113.0, 63.0),
        (14, 3, "2023-05-01 10:00:00", "COMPLETED", "APAC", "USD", 114.0, 64.0),
        (15, 1, "2023-05-01 10:00:00", "COMPLETED", "NA", "USD", 115.0, 60.0),
        (16, 2, "2023-05-01 10:00:00", "CANCELLED", "EMEA", "USD", 116.0, 61.0),
        (17, 3, "2023-05-01 10:00:00", "COMPLETED", "APAC", "USD", 117.0, 62.0),
        (18, 1, "2023-05-01 10:00:00", "COMPLETED", "NA", "USD", 118.0, 63.0),
        (19, 2, "2023-05-01 10:00:00", "COMPLETED", "EMEA", "USD", 119.0, 64.0),
        (20, 3, "2023-05-01 10:00:00", "CANCELLED", "APAC", "USD", 120.0, 60.0),
        (21, 1, "2023-05-01 10:00:00", "COMPLETED", "NA", "USD", 121.0, 61.0),
        (22, 2, "2023-05-01 10:00:00", "COMPLETED", "EMEA", "USD", 122.0, 62.0),
        (23, 3, "2023-05-01 10:00:00", "COMPLETED", "APAC", "USD", 123.0, 63.0),
        (24, 1, "2023-05-01 10:00:00", "CANCELLED", "NA", "USD", 124.0, 64.0),
    ]  # 20 USD / 2 EUR / 2 GBP (i <= 4: EUR when even, GBP when odd)
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
        con.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
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
    # cwd=tmp_path: the repo's own ariadne.yaml (which declares sources) must
    # not hijack an explicit --db run; PYTHONPATH keeps ariadne importable.
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "ariadne.profiler", "--db", str(demo_db), "--out", str(out)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    written = json.loads(out.read_text())
    assert json.loads(result.stdout) == written  # stdout and file agree
    assert written["tables"]["orders"]["columns"]["currency"]["top_value_share"] >= 0.8


def test_cli_explicit_db_beats_ambient_registry(tmp_path, demo_db, monkeypatch, capsys):
    """With an ambient ./ariadne.yaml present, an explicit --db still wins: the
    registry applies only when NEITHER --sources nor --db is given."""
    import ariadne.profiler as profiler_module

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: missing.db\n",
        encoding="utf-8",
    )
    profiler_module.main(
        ["--db", str(demo_db), "--out", str(tmp_path / "p.json"), "--no-out"]
    )
    out = json.loads(capsys.readouterr().out)
    assert out["db_path"] == str(demo_db)  # legacy shape: --db won, registry ignored


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


# --- rev 9 Lane B: registry profiling covers ALL sources (sqlite + parquet) ---


def make_support_parquet(tmp_path: Path) -> Path:
    """Miniature support-tickets parquet source, one shard per year (DuckDB-
    written, same shape as the demo fixture from scripts/make_parquet_fixture)."""
    support_dir = tmp_path / "support_tickets"
    support_dir.mkdir()
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE tickets (ticket_id INTEGER, customer_id INTEGER, "
            "status TEXT, severity TEXT, created_at TEXT, resolution_hours DOUBLE)"
        )
        con.executemany(
            "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, 1, "closed", "low", "2024-02-01 09:00:00", 30.0),
                (2, 2, "open", "high", "2024-03-01 10:00:00", None),
                (3, 1, "closed", "high", "2025-01-15 11:00:00", 5.0),
                (4, 3, "closed", "low", "2025-02-15 12:00:00", 48.0),
            ],
        )
        for year, predicate in (
            ("2024", "created_at < '2025-01-01'"),
            ("2025", "created_at >= '2025-01-01'"),
        ):
            con.execute(
                f"COPY (SELECT * FROM tickets WHERE {predicate}) "
                f"TO '{support_dir / f'tickets_{year}.parquet'}' (FORMAT PARQUET)"
            )
    finally:
        con.close()
    return support_dir


def make_registry(tmp_path: Path, db_path: Path, support_dir: Path) -> Path:
    """Two-source registry: the demo sqlite plus a parquet glob view."""
    registry = tmp_path / "ariadne.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {"name": "demo", "type": "sqlite", "path": str(db_path)},
                    {
                        "name": "support",
                        "type": "parquet",
                        "path": str(support_dir / "*.parquet"),
                        "table": "tickets",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return registry


def test_registry_profiles_both_sources_legacy_per_table_shape(tmp_path, demo_db):
    """A registry run covers BOTH sources' tables, and every per-table dict
    keeps the legacy contract's exact shape (the author's input)."""
    registry_path = make_registry(tmp_path, demo_db, make_support_parquet(tmp_path))
    result = profile(sources_path=registry_path)

    assert result["sources_path"] == str(registry_path)
    by_name = {source["name"]: source for source in result["sources"]}
    assert set(by_name) == {"demo", "support"}
    assert by_name["demo"]["type"] == "sqlite"
    assert by_name["support"]["type"] == "parquet"

    # the glob view profiles exactly like a table: full legacy per-table contract
    tickets = by_name["support"]["tables"]["tickets"]
    assert set(tickets) == {
        "row_count",
        "primary_key_candidates",
        "foreign_key_candidates",
        "columns",
    }
    assert tickets["row_count"] == 4  # both shards of the glob
    assert "ticket_id" in tickets["primary_key_candidates"]
    assert tickets["foreign_key_candidates"] == []  # heuristics unchanged: no targets here
    resolution = tickets["columns"]["resolution_hours"]
    assert resolution["null_count"] == 1  # the open ticket
    assert resolution["null_ratio"] == 0.25
    assert float(resolution["avg"]) == pytest.approx(83 / 3)  # NULLs excluded
    status = tickets["columns"]["status"]
    assert status["top_values"] == [{"value": "closed", "count": 3}, {"value": "open", "count": 1}]
    assert status["top_value_share"] == 0.75

    # per-table fields are IDENTICAL to the legacy single-sqlite shape
    legacy = profile(demo_db)
    for table, legacy_entry in legacy["tables"].items():
        registry_entry = by_name["demo"]["tables"][table]
        assert set(registry_entry) == set(legacy_entry)
        for column, legacy_col in legacy_entry["columns"].items():
            assert set(registry_entry["columns"][column]) == set(legacy_col)

    # sqlite PK/FK heuristics are unchanged under the registry connection
    orders = by_name["demo"]["tables"]["orders"]
    assert {
        "column": "customer_id",
        "references_table": "customers",
        "references_column": "id",
        "match_ratio": 1.0,
    } in orders["foreign_key_candidates"]
