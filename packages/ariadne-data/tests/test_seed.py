"""Seed determinism + fixture correctness (spec §8.1, §8.3).

These tests own the contract consumed by the profiler (#3) and the governed-metric
money test (#5 — exercised through the local `ariadne` CLI and, with the extra
installed, the MCP facade): a deterministic ``examples/retail-demo/data/demo.db``
and a hand-computed ``tests/fixtures/expected_metrics.json``.

Fixture verification is deliberately independent of seed logic: expected
values are checked against one hand-written SQL query (the two OKF rules —
status exclusion and pre-2024 EMEA currency conversion — spelled out inline),
never by re-deriving them the way the seeder does.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = REPO_ROOT / "examples" / "retail-demo" / "seed_db.py"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "expected_metrics.json"

# Fixed row-count contract (spec §8.1: "asserted row counts").
EXPECTED_TABLE_COUNTS = {
    "orders": 500,
    "customers": 30,
    "currency_conversion_rate": 2,
}

REGIONS = {"NA", "EMEA", "APAC"}


def run_seed(db_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SEED_SCRIPT), str(db_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def table_names(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    return [name for (name,) in rows]


def db_content_hash(db_path: Path) -> str:
    """Stable logical hash: schema + sorted rows of every table.

    Uses the stdlib sqlite3 reader only, so it never shares code with the
    seeder.
    """
    digest = hashlib.sha256()
    with sqlite3.connect(db_path) as con:
        for table in table_names(db_path):
            digest.update(f"table:{table}\n".encode())
            columns = con.execute(f"PRAGMA table_info({table})").fetchall()
            digest.update(f"columns:{columns!r}\n".encode())
            rows = con.execute(f"SELECT * FROM {table}").fetchall()
            for row in sorted(rows, key=repr):
                digest.update(f"row:{row!r}\n".encode())
    return digest.hexdigest()


def row_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as con:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in table_names(db_path)
        }


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("seed") / "demo.db"
    run_seed(db_path)
    return db_path


def test_retail_demo_registry_paths_are_relative_to_its_file():
    from ariadne.sources import load_registry

    registry_path = REPO_ROOT / "examples" / "retail-demo" / "ariadne.yaml"
    sources = {source.name: source for source in load_registry(registry_path).sources}
    assert sources["demo"].path == str(registry_path.parent / "data" / "demo.db")
    assert sources["support"].path == str(
        registry_path.parent / "data" / "support_tickets" / "*.parquet"
    )


def test_row_counts_deterministic_across_two_seed_runs(tmp_path):
    """Two seed runs produce identical, contract-fixed row counts."""
    first, second = tmp_path / "a.db", tmp_path / "b.db"
    run_seed(first)
    run_seed(second)

    assert row_counts(first) == EXPECTED_TABLE_COUNTS
    assert row_counts(first) == row_counts(second)


def test_db_gotchas_are_present(seeded_db):
    """The two designed gotchas must actually exist in the data."""
    with sqlite3.connect(seeded_db) as con:
        cancelled, returned = con.execute(
            "SELECT SUM(status = 'CANCELLED'), SUM(status = 'RETURNED') FROM orders"
        ).fetchone()
        assert cancelled > 0 and returned > 0, "status-exclusion gotcha not seeded"

        # Pre-2024 EMEA rows: local currency (EUR/GBP), i.e. NOT USD.
        local_rows, currencies = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT currency) FROM orders"
            " WHERE region_code = 'EMEA'"
            "   AND order_timestamp < '2024-01-01'"
        ).fetchone()
        assert local_rows > 0, "pre-2024 EMEA gotcha not seeded"
        assert currencies == 2

        # Local currency may only appear inside the pre-2024 EMEA population;
        # everything else (post-2024 EMEA, all non-EMEA) is already USD.
        stray_local = con.execute(
            "SELECT COUNT(*) FROM orders"
            " WHERE currency IN ('EUR', 'GBP')"
            "   AND NOT (region_code = 'EMEA' AND order_timestamp < '2024-01-01')"
        ).fetchone()[0]
        assert stray_local == 0, "local-currency rows outside pre-2024 EMEA"

        unconverted = con.execute(
            "SELECT COUNT(*) FROM orders"
            " WHERE region_code = 'EMEA' AND order_timestamp < '2024-01-01'"
            "   AND currency = 'USD'"
        ).fetchone()[0]
        assert unconverted == 0, "pre-2024 EMEA rows must be in local currency"


def test_idempotent_rerun_stable_content_hash(tmp_path):
    """Re-running the seeder onto an existing DB converges to identical content."""
    db_path = tmp_path / "demo.db"
    run_seed(db_path)
    first_hash = db_content_hash(db_path)

    run_seed(db_path)
    assert db_content_hash(db_path) == first_hash


def test_expected_metrics_fixture_matches_independent_sql(seeded_db):
    """Hand-computed fixture vs. one independent hand-written SQL query.

    The query encodes both OKF rules directly:
      1. exclude CANCELLED / RETURNED orders;
      2. pre-2024 EMEA rows are in local currency — multiply amount and
         product_cost by currency_conversion_rate.rate_to_usd.
    """
    fixture = json.loads(FIXTURE_PATH.read_text())

    sql = """
    WITH converted AS (
        SELECT
            o.region_code AS region,
            CASE
                WHEN o.region_code = 'EMEA'
                     AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                    THEN o.amount * r.rate_to_usd
                ELSE o.amount
            END AS amount_usd,
            CASE
                WHEN o.region_code = 'EMEA'
                     AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                    THEN o.product_cost * r.rate_to_usd
                ELSE o.product_cost
            END AS cost_usd
        FROM demo.orders o
        LEFT JOIN demo.currency_conversion_rate r ON r.currency = o.currency
        WHERE o.status NOT IN ('CANCELLED', 'RETURNED')
    )
    SELECT
        region,
        COUNT(*) AS order_count,
        SUM(amount_usd) AS gross_revenue,
        SUM(cost_usd) AS cogs,
        (SUM(amount_usd) - SUM(cost_usd)) / NULLIF(SUM(amount_usd), 0)
            AS gross_margin
    FROM converted
    GROUP BY region
    ORDER BY region
    """

    con = duckdb.connect()
    con.execute(f"ATTACH '{seeded_db}' AS demo (TYPE SQLITE)")
    order_rows = con.execute("SELECT COUNT(*) FROM demo.orders").fetchone()
    assert order_rows is not None and order_rows[0] > 0  # attach sanity
    actual = {
        region: {"order_count": n, "gross_revenue": rev, "cogs": cogs, "gross_margin": gm}
        for region, n, rev, cogs, gm in con.execute(sql).fetchall()
    }
    con.close()

    assert REGIONS <= set(actual), f"SQL missing regions: {REGIONS - set(actual)}"
    assert REGIONS <= set(fixture["gross_margin"]), "fixture missing regions"
    assert REGIONS <= set(fixture["order_count"]), "fixture missing regions"

    for region in sorted(REGIONS):
        expected = actual[region]
        assert fixture["order_count"][region] == expected["order_count"], region
        assert fixture["gross_margin"][region] == pytest.approx(
            expected["gross_margin"], abs=1e-6
        ), region
        # Supporting values the money test (#5) may also assert on.
        assert fixture["gross_revenue"][region] == pytest.approx(
            expected["gross_revenue"], abs=0.01
        ), region
        assert fixture["cogs"][region] == pytest.approx(expected["cogs"], abs=0.01), region
