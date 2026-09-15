"""MCP facade (ticket #5): three governed tools; the money test lane.

The served tree is produced offline by running the real author loop with the
mocked-OpenAI fixture machinery from tests/test_author.py (a deterministic
golden LLM response encoding both seed-note gotchas) and the REAL Datus
compile as the validation gate — then the facade is pointed at that promoted
tree. Execution happens on the facade-owned DuckDB connection over the
deterministic demo.db (scripts/seed_db.py), so every number below is checked
against tests/fixtures/expected_metrics.json — hand-computed, never derived
from seed/SQL logic. No network anywhere.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.author import author  # noqa: E402
from ariadne.serve import Facade  # noqa: E402
from ariadne.validate import validate  # noqa: E402
from tests.test_author import (  # noqa: E402
    GOTCHA_1,
    GOTCHA_2,
    fake_complete,
    make_notes,
)

FIXTURE = json.loads((REPO_ROOT / "tests" / "fixtures" / "expected_metrics.json").read_text())

# Golden model expressions (the author prompt's reference, execution-verified
# against expected_metrics.json) — kept as constants to keep lines short.
_REV = "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount * fx_rate ELSE 0 END)"
_COGS = (
    "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN product_cost * fx_rate ELSE 0 END)"  # noqa: E501
)
_COUNT = "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN 1 ELSE 0 END)"

# Golden LLM response: the author prompt's reference structure (execution-
# verified against expected_metrics.json) plus an OKF page carrying both gotchas.
GOLDEN_OSI = (
    """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: >-
          SELECT o.order_id, o.customer_id, o.order_timestamp, o.status, o.region_code,
                 o.currency, o.amount, o.product_cost,
                 CASE WHEN o.region_code = 'EMEA' AND o.order_timestamp < '2024-01-01'
                      THEN COALESCE(r.rate_to_usd, 1.0) ELSE 1.0 END AS fx_rate
          FROM demo.main.orders o
          LEFT JOIN demo.main.currency_conversion_rate r ON r.currency = o.currency
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: order_date
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: CAST(order_timestamp AS DATE)
            dimension:
              is_time: true
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
            dimension: {}
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region_code
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
          - name: product_cost
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: product_cost
          - name: fx_rate
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: fx_rate
    metrics:
      - name: gross_revenue
        description: Billed revenue in USD excluding non-billable statuses
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: @REV@
      - name: cogs
        description: Direct cost of goods in USD excluding non-billable statuses
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: @COGS@
      - name: gross_margin
        description: Ratio of sums, not an average of per-row margins
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: (gross_revenue - cogs) / NULLIF(gross_revenue, 0)
        custom_extensions:
          - vendor_name: DATUS
            data: '{"metric_kind":"derived","inputs":["gross_revenue","cogs"]}'
      - name: order_count
        description: Count of billable orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: @COUNT@
""".replace("@REV@", _REV)
    .replace("@COGS@", _COGS)
    .replace("@COUNT@", _COUNT)
)

GOLDEN_OKF = f"""\
---
type: metric
status: draft
sources:
  - orders
  - currency_conversion_rate
---

# Gross margin

Governed definition: ratio of sums, not an average of per-row margins.

Business rules from the seed notes (the author MUST restate every one):
1. {GOTCHA_1}: exclude status CANCELLED and RETURNED from revenue, cost, and order count.
2. Pre-2024 EMEA rows are unconverted local currency (EUR/GBP): {GOTCHA_2}
   for both amount and product_cost before aggregating.
"""

GOLDEN_RESPONSE = json.dumps(
    {
        "files": [
            {"path": "context_layer/metrics/gross_margin.md", "content": GOLDEN_OKF},
            {"path": "semantic_layer/models/orders.yml", "content": GOLDEN_OSI},
        ]
    }
)


def seed_demo_db(db_path: Path) -> Path:
    """Deterministic demo.db via scripts/seed_db.py (loaded by path, no pkg)."""
    spec = importlib.util.spec_from_file_location(
        "ariadne_seed_db", REPO_ROOT / "scripts" / "seed_db.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.seed(db_path)
    return db_path


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """Author loop (mocked LLM, REAL Datus compile) -> promoted served tree + db."""
    tmp = tmp_path_factory.mktemp("served")
    db = seed_demo_db(tmp / "demo.db")
    notes = make_notes(tmp)
    complete, _ = fake_complete([GOLDEN_RESPONSE])
    served = tmp / "served"
    author(db, notes, staging_dir=served, complete=complete, validate_fn=validate)
    assert (served / "semantic_layer" / "models" / "orders.yml").is_file(), (
        "golden model must pass the real compile gate"
    )
    return served, db


@pytest.fixture(scope="module")
def facade(served):
    served_dir, db = served
    return Facade(served_dir / "semantic_layer", served_dir / "context_layer", db)


def rows_by_region(result, column):
    return {row["region"]: row[column] for row in result["rows"]}


def assert_matches_fixture(rows, metric):
    """Round per the fixture's hand-computed precision, then compare exactly."""
    precision = FIXTURE["_meta"]["precision"][metric]
    actual = {
        region: round(value, precision) if isinstance(precision, int) else int(value)
        for region, value in rows.items()
    }
    assert actual == FIXTURE[metric]


def test_get_metric_gross_margin_by_region_matches_fixture(facade):
    result = asyncio.run(facade.get_metric("gross_margin", ["region"]))
    assert_matches_fixture(rows_by_region(result, "gross_margin"), "gross_margin")


def test_get_metric_order_count_by_region_matches_fixture(facade):
    result = asyncio.run(facade.get_metric("order_count", ["region"]))
    assert_matches_fixture(rows_by_region(result, "order_count"), "order_count")


def test_get_metric_returns_compiled_sql_provenance(facade):
    result = asyncio.run(facade.get_metric("gross_margin", ["region"]))
    sql = result["sql"]
    assert sql and "SELECT" in sql.upper()
    assert "CANCELLED" in sql and "RETURNED" in sql  # the exclusion gotcha is visible provenance


def test_get_metric_accepts_no_raw_sql(facade):
    # spec §6/§7: a SQL string is just an unknown name — rejected, never executed
    with pytest.raises(ValueError, match="unknown metric.*available metrics"):
        asyncio.run(facade.get_metric("SELECT * FROM orders"))


def test_list_metrics_returns_both_with_descriptions(facade):
    metrics = asyncio.run(facade.list_metrics())
    by_name = {m["name"]: m for m in metrics}
    assert {"gross_margin", "order_count"} <= set(by_name)
    assert by_name["gross_margin"]["description"]
    assert by_name["order_count"]["description"]


def test_search_context_returns_gotchas_page(facade):
    hits = asyncio.run(facade.search_context("gross margin"))
    assert hits, "the OKF page must match"
    top = hits[0]
    assert top["path"] == "metrics/gross_margin.md"
    body = top["content"]
    assert GOTCHA_1 in body and GOTCHA_2 in body  # both seed-note gotchas carried


def test_unknown_metric_errors_listing_available(facade):
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(facade.get_metric("nonexistent"))
    message = str(excinfo.value)
    assert "gross_margin" in message and "order_count" in message


def test_range_filters_on_primary_date_dimension(facade, served):
    _, db = served
    full = asyncio.run(facade.get_metric("order_count", ["region"]))
    ranged = asyncio.run(
        facade.get_metric("order_count", ["region"], range={"start": "2025-01-01"})
    )
    assert "2025-01-01" in ranged["sql"]  # filter compiled onto the primary time dimension
    full_total = sum(rows_by_region(full, "order_count").values())
    ranged_total = sum(rows_by_region(ranged, "order_count").values())
    assert 0 < ranged_total < full_total


def test_server_registers_exactly_three_tools(served):
    from ariadne.serve import build_app

    served_dir, db = served
    app = build_app(Facade(served_dir / "semantic_layer", served_dir / "context_layer", db))
    tools = asyncio.run(app.list_tools())
    assert {tool.name for tool in tools} == {"list_metrics", "search_context", "get_metric"}


def test_startup_fails_fast_without_models(tmp_path):
    with pytest.raises(RuntimeError, match="promote staging"):
        Facade(tmp_path / "semantic_layer", tmp_path / "context_layer", tmp_path / "demo.db")


def test_startup_fails_fast_when_datus_absent(tmp_path, monkeypatch):
    import ariadne.serve as serve_module

    monkeypatch.setattr(serve_module, "_DATUS_IMPORT_ERROR", ImportError("no datus"))
    with pytest.raises(RuntimeError, match="datus-semantic-osi"):
        Facade(tmp_path / "semantic_layer", tmp_path / "context_layer", tmp_path / "demo.db")


def test_serve_cli_fails_fast_with_hint_when_datus_missing(tmp_path):
    """Spec §7 for real: in a fresh interpreter with the datus imports blocked,
    the module must still import and the CLI must exit 1 with INSTALL_HINT —
    not abort with a raw ImportError."""
    import os
    import subprocess

    code = "\n".join(
        [
            "import sys",
            "sys.modules['datus_semantic_osi'] = None",
            "sys.modules['datus_semantic_osi.adapter'] = None",
            "sys.modules['datus_semantic_osi.config'] = None",
            "import ariadne.serve  # must not raise",
            "sys.exit(ariadne.serve.main(['--semantic', 'x', '--context', 'y', '--db', 'z']))",
        ]
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, env=env, timeout=120, check=False
    )
    assert proc.returncode == 1  # fail-fast exit, not a traceback
    assert b"datus-semantic-osi is required" in proc.stderr
    assert b"Traceback" not in proc.stderr
