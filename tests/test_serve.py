"""MCP facade (ticket #5): five tools (governed + ad-hoc); the money test lane.

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

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
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
def facade(served, tmp_path_factory):
    served_dir, db = served
    return Facade(
        served_dir / "semantic_layer",
        served_dir / "context_layer",
        db,
        staging_dir=tmp_path_factory.mktemp("staging"),
    )


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
    metrics = asyncio.run(facade.list_metrics())[:-1]  # trailing entry is the routing hint
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
    # spec rev 4 §7/§8.12: the error names the ad-hoc path for unmodeled questions
    assert "list_datasets" in message and "define_metric" in message


def test_list_metrics_includes_dimensions_and_routing_hint(facade):
    """Spec rev 4 §8.12: entries carry available dimensions; the response ends
    with the explicit routing hint to list_datasets() + define_metric."""
    result = asyncio.run(facade.list_metrics())
    hint = result[-1]
    assert isinstance(hint, str)
    assert "list_datasets" in hint and "define_metric" in hint
    by_name = {m["name"]: m for m in result[:-1]}
    assert "region" in by_name["gross_margin"]["dimensions"]
    assert "status" in by_name["order_count"]["dimensions"]


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


def test_tool_descriptions_carry_routing_language(served):
    """Spec rev 4: the MCP registry is the agent's map — descriptions must route
    unmodeled questions to the ad-hoc path."""
    from ariadne.serve import build_app

    served_dir, db = served
    app = build_app(Facade(served_dir / "semantic_layer", served_dir / "context_layer", db))
    desc = {tool.name: tool.description or "" for tool in asyncio.run(app.list_tools())}
    assert "no governed metric answers" in desc["define_metric"]
    assert "define_metric" in desc["list_datasets"]
    assert "dimensions" in desc["list_metrics"]


def test_server_registers_exactly_five_tools(served):
    from ariadne.serve import build_app

    served_dir, db = served
    app = build_app(Facade(served_dir / "semantic_layer", served_dir / "context_layer", db))
    tools = asyncio.run(app.list_tools())
    assert {tool.name for tool in tools} == {
        "list_metrics",
        "search_context",
        "get_metric",
        "list_datasets",
        "define_metric",
    }


# --- Ad-hoc query layer (spec revision 3, §8.8-8.11) -------------------------


def test_list_datasets_returns_demo_tables_with_columns(facade):
    datasets = {d["name"]: d for d in asyncio.run(facade.list_datasets())}
    assert set(datasets) == {"orders", "customers", "currency_conversion_rate"}
    order_columns = {c["name"]: c["type"] for c in datasets["orders"]["columns"]}
    assert {"order_id", "customer_id", "status", "amount"} <= set(order_columns)
    assert all(
        isinstance(c["type"], str) and c["type"] for d in datasets.values() for c in d["columns"]
    )


def test_get_metric_responses_carry_governed_true(facade):
    result = asyncio.run(facade.get_metric("order_count", ["region"]))
    assert result["governed"] is True
    assert "sql" in result


_JOIN_SOURCE = (
    "SELECT o.customer_id, c.name AS customer_name, o.amount, o.status "
    "FROM orders o JOIN customers c ON o.customer_id = c.id"
)
_MEAN_EXPR = "AVG(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount END)"


def test_define_metric_adhoc_mean_per_customer(facade, served):
    """§8.8: agent-authored join source, zero prior promotion, fixture-checked."""
    _, db = served
    result = asyncio.run(
        facade.define_metric(
            {
                "name": "mean_order_amount_per_customer",
                "description": "Mean order amount per customer over billable orders",
                "source": _JOIN_SOURCE,
                "expression": _MEAN_EXPR,
                "dimensions": ["customer_name"],
            }
        )
    )
    assert result["governed"] is False
    assert result["sql"].upper().count("SELECT") >= 1  # provenance SQL present
    assert "CANCELLED" in result["sql"]  # the definition's filter is visible provenance
    assert result["definition"]["source"] == _JOIN_SOURCE  # echoed params

    # Independently computed expectation: direct DuckDB SQL, no facade logic.
    con = duckdb.connect()
    con.execute(f"ATTACH '{db}' AS demo (TYPE SQLITE, READ_ONLY)")
    expected_rows = con.execute(
        "SELECT c.name, AVG(o.amount) FROM demo.main.orders o "
        "JOIN demo.main.customers c ON o.customer_id = c.id "
        "WHERE o.status NOT IN ('CANCELLED', 'RETURNED') GROUP BY c.name"
    ).fetchall()
    con.close()
    expected = {name: round(avg, 6) for name, avg in expected_rows}
    actual = {
        row["customer_name"]: round(row["mean_order_amount_per_customer"], 6)
        for row in result["rows"]
    }
    assert actual == expected


def _adhoc_dir(facade):
    adhoc = Path(facade.staging_dir) / "semantic_layer" / "models" / "adhoc"
    return adhoc, sorted(p.name for p in adhoc.iterdir()) if adhoc.is_dir() else []


def test_define_metric_nonexistent_column_errors_without_side_effects(facade):
    """§8.9: invalid definition -> error, staging/…/adhoc/ unchanged, no execution."""
    adhoc, before = _adhoc_dir(facade)
    pages = Path(facade.staging_dir) / "context_layer" / "metrics"
    pages_before = sorted(p.name for p in pages.iterdir()) if pages.is_dir() else []
    with pytest.raises(ValueError, match="nonexistent_col"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "broken_metric",
                    "description": "references a column that does not exist",
                    "source": "orders",
                    "expression": "SUM(nonexistent_col)",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before
    pages_after = sorted(p.name for p in pages.iterdir()) if pages.is_dir() else []
    assert pages_after == pages_before  # no context page either
    assert not (adhoc / "broken_metric.yml").exists()


def test_define_metric_compile_error_surfaced_verbatim(facade):
    """A definition the Datus compiler itself rejects: errors verbatim, nothing staged."""
    adhoc, before = _adhoc_dir(facade)
    with pytest.raises(ValueError, match="could not parse expression"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "syntax_error_metric",
                    "description": "malformed aggregate",
                    "source": "orders",
                    "expression": "SUM((",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before


def test_define_metric_rejects_unsane_name(facade):
    with pytest.raises(ValueError, match="lowercase snake_case"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "Bad Name!",
                    "description": "not a slug",
                    "source": "orders",
                    "expression": "SUM(amount)",
                }
            )
        )


def test_define_metric_name_collision_never_overwrites(facade):
    """§8.11: two successes with the same name -> two files, second suffixed."""
    definition = {
        "name": "collision_probe_metric",
        "description": "same name twice",
        "source": "orders",
        "expression": "SUM(amount)",
        "dimensions": [],
    }
    first = asyncio.run(facade.define_metric(dict(definition)))
    first_path = Path(first["staged_as"])
    assert first_path.name == "collision_probe_metric.yml"
    original_bytes = first_path.read_bytes()
    first_page = Path(first["staged_context_as"])
    assert first_page.name == "collision_probe_metric.md"
    first_page_bytes = first_page.read_bytes()

    second = asyncio.run(facade.define_metric(dict(definition)))
    second_path = Path(second["staged_as"])
    assert second_path.name == "collision_probe_metric-2.yml"
    assert first_path.exists() and second_path.exists()  # both files present
    assert first_path != second_path  # distinct names
    assert first_path.read_bytes() == original_bytes  # first proposal never overwritten
    # spec rev 4 §8.12: the collision suffixes the context page too — two pages,
    # distinct names, first draft untouched.
    second_page = Path(second["staged_context_as"])
    assert second_page.name == "collision_probe_metric-2.md"
    assert first_page.is_file() and second_page.is_file()
    assert first_page != second_page
    assert first_page.read_bytes() == first_page_bytes


def test_define_metric_stages_model_and_context_page(facade):
    """Spec rev 4 §4/§8.12: success leaves BOTH the OSI model proposal and a
    DISCOVERABLE OKF context-page draft — search_context surfaces the staged
    page (marked draft: true) before any promotion, while unrelated text never
    surfaces it and served pages stay draft: false."""
    description = "probe for the auto-staged OKF draft"
    result = asyncio.run(
        facade.define_metric(
            {
                "name": "page_probe_metric",
                "description": description,
                "source": "orders",
                "expression": "SUM(amount)",
                "dimensions": ["status"],
            }
        )
    )
    model = Path(result["staged_as"])
    page = Path(result["staged_context_as"])
    assert model.is_file() and model.parent.name == "adhoc"
    assert page.is_file()
    assert Path("context_layer", "metrics") == Path(*page.parts[-3:-1])
    text = page.read_text()
    assert "# page_probe_metric" in text  # H1 name
    assert description in text  # description
    assert "- status" in text  # dimensions list
    assert "auto-staged ad-hoc proposal awaiting promotion" in text.lower()  # marker
    assert "type: metric" in text and "status: draft" in text and "generated:" in text
    assert "- orders" in text  # sources from the definition's source tables

    # Discoverability (rev 4 §4): the description's own terms rank the staged
    # draft first, flagged as a draft — pre-promotion, never masquerading.
    top = asyncio.run(facade.search_context(description))[0]
    assert top["path"] == "metrics/page_probe_metric.md"
    assert top["draft"] is True
    assert description in top["content"]
    # The same response carries served pages, marked non-draft — distinguishable.
    hits = asyncio.run(facade.search_context(description))
    assert any(hit["path"] == "metrics/gross_margin.md" and hit["draft"] is False for hit in hits)
    # Unrelated text (served-page terms absent from the draft) never surfaces it.
    misses = asyncio.run(facade.search_context("gross margin"))
    assert not any("page_probe_metric" in hit["path"] for hit in misses)
    assert not any(hit["draft"] for hit in misses)  # only served pages match


_INJECTION_SOURCE = "orders) ; CREATE TEMP TABLE pwned(x int); SELECT * FROM (SELECT 1"


def test_define_metric_rejects_multi_statement_compiled_sql(facade):
    """§6 invariant: a crafted source compiles to multi-statement SQL (the CREATE
    TEMP TABLE would execute under the EXPLAIN bind-check). The parse-level guard
    must reject it before ANY duckdb call: error names the invariant, no temp
    table exists on the connection, nothing staged."""
    adhoc, before = _adhoc_dir(facade)
    with pytest.raises(ValueError, match="exactly one statement"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "pwned_metric",
                    "description": "injection probe",
                    "source": _INJECTION_SOURCE,
                    "expression": "SUM(amount)",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before  # nothing staged
    assert not (adhoc / "pwned_metric.yml").exists()
    tables = {
        row[0] for row in facade.con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
    }
    assert "pwned" not in tables  # the smuggled DDL never ran


def test_define_metric_allows_semicolon_inside_string_literal(facade):
    """Parser correctness: a quoted semicolon in the compiled SQL must not trip
    the single-statement guard — the definition still compiles and executes."""
    result = asyncio.run(
        facade.define_metric(
            {
                "name": "quoted_semicolon_metric",
                "description": "semicolon inside a string literal",
                "source": "orders",
                "expression": (
                    "SUM(CASE WHEN NOT status IN "
                    "('CANCELLED', 'RETURNED', 'no;match') THEN amount END)"
                ),
                "dimensions": [],
            }
        )
    )
    assert result["governed"] is False
    assert result["rows"]  # executed: SUM(amount) over billable orders is nonzero


def test_define_metric_rejects_fanned_out_join_source(facade):
    """Spec rev 5 §13 grain guard: a source whose join key is not unique on the
    joined side (orders self-joined on region_code — guaranteed duplicates) fans
    out the fact grain; the compiler would aggregate at joined-row grain
    (Datus-ai/Datus-agent#1426), so the facade rejects before compile. Nothing
    staged, nothing executed."""
    adhoc, before = _adhoc_dir(facade)
    with pytest.raises(ValueError, match="grain-preservation invariant.*GROUP BY"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "fanned_metric",
                    "description": "join key not unique on the joined side",
                    "source": (
                        "SELECT o.order_id, o.amount, x.order_id AS x_id "
                        "FROM orders o JOIN orders x ON x.region_code = o.region_code"
                    ),
                    "expression": "SUM(amount)",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before  # nothing staged
    assert not (adhoc / "fanned_metric.yml").exists()


def test_define_metric_rejects_cross_join_source(facade):
    """§13 grain guard: a CROSS (or comma) join has no key to prove unique —
    unbounded row multiplication is rejected outright."""
    adhoc, before = _adhoc_dir(facade)
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "cross_metric",
                    "description": "cross join fans out unboundedly",
                    "source": "SELECT o.order_id, c.name FROM orders o CROSS JOIN customers c",
                    "expression": "SUM(o.amount)",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before  # nothing staged
    assert not (adhoc / "cross_metric.yml").exists()


def test_define_metric_allows_grain_preserving_join(facade):
    """§13 grain guard upside: the many-to-one direction (orders ⋈ customers on
    the customers primary key) stays legitimate — same shape as the ad-hoc
    acceptance definition; the guard must not reject it."""
    result = asyncio.run(
        facade.define_metric(
            {
                "name": "guard_probe_metric",
                "description": "many-to-one join on the unique side",
                "source": (
                    "SELECT o.order_id, c.name AS customer_name, o.amount "
                    "FROM orders o JOIN customers c ON o.customer_id = c.id"
                ),
                "expression": "SUM(amount)",
                "dimensions": [],
            }
        )
    )
    assert result["governed"] is False
    Path(result["staged_as"]).unlink(missing_ok=True)
    Path(result["staged_context_as"]).unlink(missing_ok=True)


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
