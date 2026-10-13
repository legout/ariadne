"""MCP facade (ticket #5): five tools (governed + ad-hoc); the money test lane.

The served tree is produced offline by running the real author loop with the
mocked-OpenAI fixture machinery from tests/test_author.py (a deterministic
golden LLM response encoding both seed-note gotchas) and the REAL Datus
compile as the validation gate — then the facade is pointed at that promoted
tree. Execution happens on the facade-owned DuckDB connection over the
deterministic demo.db (examples/retail-demo/seed_db.py), so every number below is checked
against tests/fixtures/expected_metrics.json — hand-computed, never derived
from seed/SQL logic. No network anywhere.
"""

import asyncio
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.author import author  # noqa: E402
from ariadne.serve import Facade  # noqa: E402
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

# Golden OKF page: cites both governing policies (spec rev 10 §8.21 — the
# context field resolves policies/order-status-billing.md and
# policies/emea-currency-cutover.md against the served context dir).
GOLDEN_OKF = f"""\
---
type: metric
status: draft
sources:
  - orders
  - currency_conversion_rate
  - {{id: order-status-billing, resource: policies/order-status-billing.md}}
  - {{id: emea-currency-cutover, resource: policies/emea-currency-cutover.md}}
---

# Gross margin

Governed definition: ratio of sums, not an average of per-row margins.

Business rules from the seed notes (the author MUST restate every one):
1. {GOTCHA_1}: exclude status CANCELLED and RETURNED from revenue, cost, and order count.
2. Pre-2024 EMEA rows are unconverted local currency (EUR/GBP): {GOTCHA_2}
   for both amount and product_cost before aggregating.
"""

GOLDEN_POLICY_STATUS = f"""\
---
type: policy
status: draft
title: Order status billing
description: Cancelled and returned orders are not revenue.
tags: [policy, billing]
sources:
  - id: seed-notes
    resource: data/seed_notes.md
    title: Seed notes
---

# Order status billing

{GOTCHA_1}: rows with status IN ('CANCELLED', 'RETURNED') are excluded from
every revenue, cost, and order-count number.
"""

GOLDEN_POLICY_EMEA = f"""\
---
type: policy
status: draft
title: EMEA currency cutover
description: Pre-2024 EMEA rows are unconverted local currency.
tags: [policy, currency]
sources:
  - id: seed-notes
    resource: data/seed_notes.md
    title: Seed notes
---

# EMEA currency cutover

{GOTCHA_2}: pre-2024 EMEA rows carry unconverted local currency (EUR/GBP) and
must be converted with the fx_rate join before aggregating.
"""

GOLDEN_RESPONSE = json.dumps(
    {
        "files": [
            {"path": "context_layer/metrics/gross_margin.md", "content": GOLDEN_OKF},
            {
                "path": "context_layer/policies/order-status-billing.md",
                "content": GOLDEN_POLICY_STATUS,
            },
            {
                "path": "context_layer/policies/emea-currency-cutover.md",
                "content": GOLDEN_POLICY_EMEA,
            },
            {"path": "semantic_layer/models/orders.yml", "content": GOLDEN_OSI},
        ]
    }
)


def seed_demo_db(db_path: Path) -> Path:
    """Deterministic demo.db via examples/retail-demo/seed_db.py (loaded by path, no pkg)."""
    spec = importlib.util.spec_from_file_location(
        "ariadne_seed_db", REPO_ROOT / "examples" / "retail-demo" / "seed_db.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.seed(db_path)
    return db_path


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """Author loop (mocked LLM, default gate: real Datus compile + ADR-0006 §5
    grain audit over the demo db) -> promoted served tree + db."""
    tmp = tmp_path_factory.mktemp("served")
    db = seed_demo_db(tmp / "demo.db")
    notes = make_notes(tmp)
    complete, _ = fake_complete([GOLDEN_RESPONSE])
    served = tmp / "served"
    author(db, notes, staging_dir=served, complete=complete)
    assert (served / "semantic_layer" / "models" / "orders.yml").is_file(), (
        "golden model must pass the real compile + grain-audit gate"
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


def test_server_registers_five_query_and_five_authoring_tools(served):
    """Spec 2026-09-23-0001 §4 keeps exactly the five legacy query/ad-hoc tools;
    spec 2026-09-24-0005 adds the authoring registration (issue #16); issue #21
    adds exactly the two answer-example tools over the shared runtime; issue #30
    adds exactly the two admitted multi-fact query tools (query_metrics/
    query_detail, thin adapters over the same transport-neutral runtime the
    local CLI calls); issue #38/G6 REPLACES the legacy complete-bundle authoring
    wrappers with the plan §2 Git authoring contract (eight
    ``authoring_``-prefixed tools over AuthoringProject), issue #41/K1 adds
    exactly one more — ``authoring_refresh_schema`` (the explicit physical
    schema refresh) — and issue #42/K2 adds exactly one on each side
    (``resolve_term`` over the served context and
    ``authoring_resolve_term`` over an explicitly selected proposal); issue
    #43/K3 adds exactly one more — ``authoring_inspect_mapping`` (the bounded
    mapping inspection with authentic retained receipts); issue #57/S2 adds
    exactly one more — ``query_records`` (the bounded Ad-hoc Record Query over
    one known catalog table, spec 0014 §3); spec 0015/issue #60 adds exactly
    two more — ``list_context_pages`` and ``read_context_page`` (the token-free
    Context Layer page listing and path-addressed reading, ADR-0020); never a
    source-approval, Promotion, admission or example-review tool (ADR-0013/#20:
    review is human-only; the surfaces are tool-surface separation, spec §6)."""
    from ariadne.serve import build_app

    served_dir, db = served
    app = build_app(Facade(served_dir / "semantic_layer", served_dir / "context_layer", db))
    tools = asyncio.run(app.list_tools())
    assert {tool.name for tool in tools} == {
        "list_metrics",
        "search_context",
        "list_context_pages",
        "read_context_page",
        "discover",
        "get_metric",
        "list_datasets",
        "define_metric",
        "query_metrics",
        "query_detail",
        "query_records",
        "save_example",
        "search_examples",
        "resolve_term",
        "authoring_start_proposal",
        "authoring_read_artifact",
        "authoring_edit_proposal",
        "authoring_propose_sources",
        "authoring_inputs",
        "authoring_upload_document",
        "authoring_validate_proposal",
        "authoring_refresh_schema",
        "authoring_resolve_term",
        "authoring_inspect_mapping",
        "authoring_review_proposal",
    }
    assert not [tool for tool in tools if "approve" in tool.name or "promot" in tool.name]


def test_mcp_example_tools_parity_with_local_transport(served, tmp_path):
    """Issue #21 (spec 2026-09-29-0007 §interfaces, AC6): the optional MCP tools
    save_example/search_examples are thin adapters over the SAME transport-neutral
    runtime the local JSON CLI calls — a draft saved over one transport is
    immediately searchable over the other with the same ID/status — and the
    example-review command is never registered as a tool (operator-only, #20)."""
    from ariadne.serve import build_app

    def _json(result_blocks) -> Any:
        """FastMCP (mcp<2) emits one text block per element for list returns
        and wraps those in a (blocks, structured) tuple (see
        tests/test_authoring_mcp._payload): one block IS the value, several
        blocks are the list elements."""

        if isinstance(result_blocks, tuple):
            result_blocks = result_blocks[0]

        def _element(block):
            try:
                return json.loads(block.text)
            except ValueError:
                return block.text

        if len(result_blocks) == 1:
            return _element(result_blocks[0])
        return [_element(block) for block in result_blocks]

    served_dir, db = served
    local = Facade(
        served_dir / "semantic_layer",
        served_dir / "context_layer",
        db,
        staging_dir=tmp_path / "staging",
    )
    app = build_app(local)

    # Registration seam: exactly the two example tools, never a review tool.
    names = {tool.name for tool in asyncio.run(app.list_tools())}
    assert {name for name in names if "example" in name} == {"save_example", "search_examples"}

    submission = {
        "question": "What is the gross margin ratio by region?",
        "interpretation": "Ratio of sums over billable orders, EMEA cutover applied",
        "parameters": {"dimensions": ["region"], "grain": "one row per region"},
        "method": {
            "operation": "get_metric",
            "arguments": {"name": "gross_margin", "dimensions": ["region"]},
        },
        "result": {
            "metric": "gross_margin",
            "columns": ["region", "gross_margin"],
            "rows": [{"region": "EMEA", "gross_margin": 0.5}],
            "sql": "SELECT region, 0.5 AS gross_margin",
            "governed": True,
        },
        "submitter": "expert:dana",
        "attestation": "The saved interpretation states the business meaning I intended.",
        "sources": ["context_layer/metrics/gross_margin.md"],
    }

    # Save over MCP -> immediately searchable from a SECOND runtime over the
    # same checkout (the exact object the local CLI constructs), same ID/status.
    saved = _json(asyncio.run(app.call_tool("save_example", {"submission": submission})))
    assert saved["status"] == "draft"
    other = Facade(
        served_dir / "semantic_layer",
        served_dir / "context_layer",
        db,
        staging_dir=tmp_path / "staging",
    )
    hits = asyncio.run(other.search_examples("gross margin region"))
    assert hits and hits[0]["id"] == saved["id"] and hits[0]["status"] == "draft"

    # And the reverse direction: save over the local runtime, search over MCP.
    saved_local = asyncio.run(
        other.save_example({**submission, "question": "What is the order count by region?"})
    )
    assert saved_local["status"] == "draft"
    hits_mcp = _json(asyncio.run(app.call_tool("search_examples", {"query": "order count"})))
    if isinstance(hits_mcp, dict):  # one hit arrives as one content block
        hits_mcp = [hits_mcp]
    assert hits_mcp and hits_mcp[0]["id"] == saved_local["id"]
    assert hits_mcp[0]["status"] == "draft"

    # Issue #68 (spec 0023 §3): opt-in SQL retrieval is transport-neutral too.
    # Default MCP search adds no SQL field or availability marker; include_sql
    # over MCP returns exactly what the local runtime returns, including the
    # result-derived sql_provenance mapping.
    assert all("sql" not in hit["provenance"] for hit in hits_mcp)
    mcp_sql = _json(
        asyncio.run(
            app.call_tool("search_examples", {"query": "gross margin", "include_sql": True})
        )
    )
    if isinstance(mcp_sql, dict):  # one hit arrives as one content block
        mcp_sql = [mcp_sql]
    local_sql = asyncio.run(other.search_examples("gross margin", include_sql=True))
    assert mcp_sql == local_sql
    assert mcp_sql[0]["id"] == saved["id"]
    assert mcp_sql[0]["provenance"]["sql"] == {
        "source": "submitted_result.sql",
        "text": submission["result"]["sql"],
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


# --- Context-carrying answers (spec rev 10 §8.21, ADR-0011) ------------------


def test_governed_get_metric_carries_context_with_policy_bodies(facade):
    """The governed response carries the full metric page AND the full bodies of
    both policies its sources[] cites (gross_margin cites order-status-billing
    and emea-currency-cutover)."""
    result = asyncio.run(facade.get_metric("gross_margin", ["region"]))
    context = result["context"]
    assert GOTCHA_1 in context["metric_page"]  # the metric page itself, full text
    assert len(context["policies"]) == 2
    assert GOTCHA_1 in context["policies"][0]  # order-status-billing body
    assert GOTCHA_2 in context["policies"][1]  # emea-currency-cutover body


def test_adhoc_define_metric_carries_context_null(facade):
    """Ad-hoc metrics have no served page: context is exactly null."""
    result = asyncio.run(
        facade.define_metric(
            {
                "name": "context_probe_metric",
                "description": "ad-hoc answers carry no served context",
                "source": "orders",
                "expression": "SUM(amount)",
                "dimensions": [],
            }
        )
    )
    assert result["governed"] is False
    assert result["context"] is None


def test_missing_metric_page_collapses_context_without_failing(served, tmp_path):
    """A served tree whose context dir lacks the metric page still answers:
    the fallback is the null form, never a query error — now also disclosing
    the §5 context_unavailable warning for exactly that metric page path
    (spec 0011 §5: its undiscoverable Policy dependencies are not claimed to
    have been assessed)."""
    served_dir, db = served
    naked = Facade(served_dir / "semantic_layer", tmp_path, db, staging_dir=tmp_path / "staging")
    result = asyncio.run(naked.get_metric("gross_margin", ["region"]))
    assert result["governed"] is True
    assert result["rows"]
    assert result["context"]["metric_page"] is None  # the old payload semantics
    assert result["context"]["policies"] == []
    assert result["context"]["context_signals"] == {
        "pages": [],
        "warnings": [{"code": "context_unavailable", "path": "metrics/gross_margin.md"}],
    }


def test_unresolvable_policy_reference_collapses_context_without_failing(served, tmp_path):
    """A metric page citing a policies/ path that does not resolve collapses the
    whole context to the null form (spec rev 10: one fallback shape, no failure,
    nothing logged)."""
    served_dir, db = served
    context_dir = tmp_path / "context_layer"
    (context_dir / "metrics").mkdir(parents=True)
    (context_dir / "metrics" / "gross_margin.md").write_text(
        "---\ntype: metric\nstatus: stable\nsources:\n"
        "  - {id: gone, resource: policies/missing-policy.md}\n---\n\n# Gross margin\n",
        encoding="utf-8",
    )
    facade = Facade(
        served_dir / "semantic_layer", context_dir, db, staging_dir=tmp_path / "staging"
    )
    result = asyncio.run(facade.get_metric("gross_margin", ["region"]))
    assert result["governed"] is True
    assert result["context"]["metric_page"] is None
    assert result["context"]["policies"] == []
    assert result["context"]["context_signals"] == {
        "pages": [],
        "warnings": [{"code": "context_unavailable", "path": "policies/missing-policy.md"}],
    }


def test_metric_page_name_traversal_collapses_context_without_reading_outside(served, tmp_path):
    """Containment: a served metric name that escapes the context dir (a model
    YAML is not fully trusted) never reads outside context_layer/ — the page
    collapses to the null form and the external file's content is absent."""
    served_dir, db = served
    secret = served_dir / "secret.md"  # context_layer/metrics/../../secret.md lands here
    secret.write_text("TOP_SECRET_TRAVERSAL_PAYLOAD", encoding="utf-8")
    facade = Facade(
        served_dir / "semantic_layer",
        served_dir / "context_layer",
        db,
        staging_dir=tmp_path / "staging",
    )
    context = facade._metric_context("../../secret")
    assert context["metric_page"] is None and context["policies"] == []
    assert context["context_signals"]["warnings"] == [
        {"code": "context_unavailable", "path": "metrics/../../secret.md"}
    ]
    assert "TOP_SECRET_TRAVERSAL_PAYLOAD" not in json.dumps(context)


def test_policy_ref_traversal_collapses_context_without_reading_dotenv(served, tmp_path):
    """Containment: a cited policy ``policies/../../.env`` must resolve under
    ``policies/`` — it does not, so the whole context collapses to the null form
    while the query itself still answers, and the .env content never leaks."""
    served_dir, db = served
    context_dir = tmp_path / "context_layer"
    (context_dir / "metrics").mkdir(parents=True)
    (context_dir / "metrics" / "gross_margin.md").write_text(
        "---\ntype: metric\nstatus: stable\nsources:\n"
        "  - {id: theft, resource: policies/../../.env}\n---\n\n# Gross margin\n",
        encoding="utf-8",
    )
    dotenv = tmp_path / ".env"  # context_layer/policies/../../.env resolves here
    dotenv.write_text("OPENAI_API_KEY=sk-traversal-secret\n", encoding="utf-8")
    facade = Facade(
        served_dir / "semantic_layer", context_dir, db, staging_dir=tmp_path / "staging"
    )
    result = asyncio.run(facade.get_metric("gross_margin", ["region"]))
    assert result["governed"] is True and result["rows"]  # the query never fails
    context = result["context"]
    assert context["metric_page"] is None and context["policies"] == []
    assert context["context_signals"]["warnings"] == [
        {"code": "context_unavailable", "path": "policies/../../.env"}
    ]
    assert "sk-traversal-secret" not in json.dumps(result)


def test_get_metric_discloses_expired_and_deprecated_policy_signals(served, tmp_path):
    """Spec 0011 §5/§8 AC3 — the focused core regression: a metric consuming an
    expired and a deprecated Policy returns the SAME rows/SQL/governed label
    (pinned here against the hand-computed fixture AND the unmodified tree),
    keeps the full authored rule bodies, and the advisory envelope names both
    Policy paths with the §5 codes. Expectations derive from §5: a reached
    supported expiry is context_stale, an explicitly declared deprecated
    status is context_deprecated — nothing else changes."""
    served_dir, db = served
    context_dir = tmp_path / "context_layer"
    shutil.copytree(served_dir / "context_layer", context_dir)
    expired = context_dir / "policies" / "order-status-billing.md"
    expired.write_text(
        re.sub(r"^stale_after: .*$", "stale_after: 2020-01-01", expired.read_text(), flags=re.M),
        encoding="utf-8",
    )
    deprecated = context_dir / "policies" / "emea-currency-cutover.md"
    deprecated.write_text(
        deprecated.read_text().replace("status: review_needed", "status: deprecated", 1),
        encoding="utf-8",
    )
    before = {page: page.read_bytes() for page in (expired, deprecated)}
    warned = Facade(served_dir / "semantic_layer", context_dir, db, staging_dir=tmp_path / "warned")
    baseline = asyncio.run(
        Facade(
            served_dir / "semantic_layer",
            served_dir / "context_layer",
            db,
            staging_dir=tmp_path / "baseline",
        ).get_metric("gross_margin", ["region"])
    )
    result = asyncio.run(warned.get_metric("gross_margin", ["region"]))

    # numeric invariance: identical to the unmodified tree AND the independent
    # hand-computed oracle (tests/fixtures/expected_metrics.json); row order is
    # not part of the contract (no ORDER BY in the compiled SQL)
    assert sorted(result["rows"], key=lambda row: row["region"]) == sorted(
        baseline["rows"], key=lambda row: row["region"]
    )
    assert result["sql"] == baseline["sql"]
    assert result["governed"] == baseline["governed"] is True
    assert_matches_fixture(rows_by_region(result, "gross_margin"), "gross_margin")

    # full authored rule bodies stay the payload (ADR-0011)
    assert GOTCHA_1 in result["context"]["metric_page"]
    assert GOTCHA_2 in result["context"]["metric_page"]
    assert GOTCHA_1 in result["context"]["policies"][0]
    assert GOTCHA_2 in result["context"]["policies"][1]

    signals = result["context"]["context_signals"]
    assert [page["path"] for page in signals["pages"]] == [
        "metrics/gross_margin.md",
        "policies/order-status-billing.md",
        "policies/emea-currency-cutover.md",
        "computations/gross_margin.md",
    ]
    assert signals["warnings"] == [
        {"code": "context_stale", "path": "policies/order-status-billing.md"},
        {"code": "context_deprecated", "path": "policies/emea-currency-cutover.md"},
    ]
    # the metric page itself: its declared review_needed state is preserved
    # (§4: page status is not staged/admitted identity and never warns), the
    # stamped empty verification list stays unverified, and its own future
    # stamp stays current without a warning
    metric_view = signals["pages"][0]
    assert metric_view["status"] == "review_needed"
    assert metric_view["verification_tier"] == "unverified" and metric_view["verified"] == []
    assert metric_view["generated"]["by"] == "ariadne-author"
    assert metric_view["freshness"]["state"] == "current"
    assert signals["pages"][3]["status"] == "review_needed"  # the computation page too
    # the expired Policy's YAML-native date discloses as an ISO string (§3)
    assert signals["pages"][1]["freshness"] == {
        "stale_after": "2020-01-01",
        "state": "stale",
    }
    assert signals["pages"][2]["status"] == "deprecated"
    # §8 AC9: the assessment is read-only — the warned pages are byte-identical
    assert {page: page.read_bytes() for page in (expired, deprecated)} == before


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
    with pytest.raises(ValueError, match="grain-preservation invariant.*pivot"):
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


def test_grain_guidance_names_the_adr_0006_rubric():
    """Spec rev 6: the rejection guidance names the ADR-0006 resolution rubric by
    pattern (pivot / child-grain fact model / fact weight allocation) instead of
    the bare GROUP BY phrasing — end-to-end through a real define_metric
    rejection and in the shared constant the tool description derives from."""
    from ariadne.serve import GRAIN_GUIDANCE

    for pattern in ("pivot", "child-grain fact model", "weight allocation", "ADR-0006"):
        assert pattern in GRAIN_GUIDANCE
    assert "GROUP BY" not in GRAIN_GUIDANCE  # rubric names replaced the bare phrasing


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


def test_define_metric_rejects_on_true_cartesian_source(facade):
    """§13 grain guard correction: `ON TRUE` has zero equality keys — the old
    per-key loop never ran, so the cartesian product passed the guard and
    executed, returning inflated aggregates. Fail closed before compile."""
    adhoc, before = _adhoc_dir(facade)
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "on_true_metric",
                    "description": "ON TRUE fans out unboundedly",
                    "source": (
                        "SELECT o.order_id, l.line_amount FROM orders o JOIN customers l ON TRUE"
                    ),
                    "expression": "SUM(o.amount)",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before  # nothing staged
    assert not (adhoc / "on_true_metric.yml").exists()


def test_define_metric_rejects_non_equality_join_predicate(facade):
    """§13 grain guard correction: an ON with only a non-equality predicate has
    no attributable equality key to prove — the guard cannot establish grain
    preservation, so it fails closed with the grain guidance."""
    adhoc, before = _adhoc_dir(facade)
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            facade.define_metric(
                {
                    "name": "inequality_metric",
                    "description": "inequality ON fans out without a provable key",
                    "source": (
                        "SELECT o.order_id, l.line_amount "
                        "FROM orders o JOIN customers l ON l.customer_id > o.customer_id"
                    ),
                    "expression": "SUM(o.amount)",
                    "dimensions": [],
                }
            )
        )
    assert _adhoc_dir(facade)[1] == before  # nothing staged
    assert not (adhoc / "inequality_metric.yml").exists()


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


def test_serve_facade_is_the_runtime_class():
    """Ticket #7: ariadne.serve.Facade is the exact runtime class — a plain
    alias, never a subclass or wrapper that could diverge."""
    import ariadne.runtime
    import ariadne.serve

    assert ariadne.serve.Facade is ariadne.runtime.AriadneRuntime


def test_startup_fails_fast_without_models(tmp_path):
    with pytest.raises(RuntimeError, match="promote staging"):
        Facade(tmp_path / "semantic_layer", tmp_path / "context_layer", tmp_path / "demo.db")


def test_startup_fails_fast_when_datus_absent(tmp_path, monkeypatch):
    import ariadne.query as query_module

    monkeypatch.setattr(query_module, "_DATUS_IMPORT_ERROR", ImportError("no datus"))
    with pytest.raises(RuntimeError, match="datus-semantic-osi"):
        Facade(tmp_path / "semantic_layer", tmp_path / "context_layer", tmp_path / "demo.db")


def test_serve_cli_fails_fast_with_hint_when_datus_missing(tmp_path):
    """Spec §7 for real: in a fresh interpreter with the datus imports blocked,
    the module must still import and the Analyst CLI must exit 1 with
    INSTALL_HINT — not abort with a raw ImportError. (The Combined default
    no longer fails fast here: a missing datus engine is a query-side
    failure, so its authoring surface still boots and query tools surface
    this same error per call — issue #38 criterion 2, the G6 review fix.)"""
    import os
    import subprocess

    code = "\n".join(
        [
            "import sys",
            "sys.modules['datus_semantic_osi'] = None",
            "sys.modules['datus_semantic_osi.adapter'] = None",
            "sys.modules['datus_semantic_osi.config'] = None",
            "import ariadne.serve  # must not raise",
            "sys.exit(ariadne.serve.main(['--toolset', 'analyst',",
            "                                  '--semantic', 'x', '--context', 'y', '--db', 'z']))",
        ]
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, env=env, timeout=120, check=False
    )
    assert proc.returncode == 1  # fail-fast exit, not a traceback
    assert b"datus-semantic-osi is required" in proc.stderr
    assert b"Traceback" not in proc.stderr


# --- Measured Context Layer retrieval (spec 2026-09-23-0002, issue #10) -------


RETRIEVAL_CORPUS = json.loads(
    (REPO_ROOT / "tests" / "evals" / "context_retrieval.json").read_text(encoding="utf-8")
)


def test_context_retrieval_corpus_recall_at_five(served, tmp_path):
    """AC1/AC2: the checked-in natural-language corpus over the demo served tree.
    Every positive expectation lands within the first five distinct (path, draft)
    hits; the missing-term question returns no hits; the same-path staged draft
    and served page stay distinct; editing the staged text is visible on the very
    next search without implying promotion."""
    served_dir, db = served
    staging = tmp_path / "staging"
    facade = Facade(
        served_dir / "semantic_layer", served_dir / "context_layer", db, staging_dir=staging
    )
    staged_files = {}
    for entry in RETRIEVAL_CORPUS["entries"]:  # one deterministic world state
        for staged in entry.get("staged", []):
            page = staging / "context_layer" / staged["path"]
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(staged["content"], encoding="utf-8")
            staged_files[staged["path"]] = page
    top_k = RETRIEVAL_CORPUS["_meta"]["top_k"]
    for entry in RETRIEVAL_CORPUS["entries"]:
        hits = asyncio.run(facade.search_context(entry["question"]))
        distinct = list(dict.fromkeys((hit["path"], hit["draft"]) for hit in hits))
        if entry["expect"]:
            for expected in entry["expect"]:
                assert (expected["path"], expected["draft"]) in distinct[:top_k], (
                    entry["question"],
                    distinct[:top_k],
                )
        else:
            assert hits == [], entry["question"]

    # AC2: revise the staged draft — the next search reflects the new text (the
    # withdrawn terms stop matching, the new wording is discoverable), while the
    # served twin keeps its own content.
    revision = (
        "---\ntype: policy\nstatus: draft\ntitle: Order status billing\n---\n\n"
        "# Order status billing\n\nRevision withdrawn; no special-casing remains.\n"
    )
    staged_files["policies/order-status-billing.md"].write_text(revision, encoding="utf-8")
    assert asyncio.run(facade.search_context("charity gift")) == []
    revised = asyncio.run(facade.search_context("withdrawn special-casing"))
    assert [(hit["path"], hit["draft"]) for hit in revised] == [
        ("policies/order-status-billing.md", True)
    ]
    hits = asyncio.run(facade.search_context("order-count number"))
    served_twin = next(
        hit
        for hit in hits
        if hit["path"] == "policies/order-status-billing.md" and not hit["draft"]
    )
    assert "Revision withdrawn" not in served_twin["content"]  # promotion stays human


def test_search_context_passage_coordinates_and_sections(served, tmp_path):
    """AC3/AC4: each hit carries a bounded verbatim excerpt with inclusive 1-based
    line coordinates and the containing heading — frontmatter-only matches have
    no invented section, headings inside fenced code (backtick or tilde) never
    name a section, a body match is preferred over a frontmatter match, and a
    query matching an actual heading line names that heading itself. A page
    whose only match is inside a fenced code block stays a hit (every Markdown
    category remains searchable) and resolves to the surrounding real heading."""
    served_dir, db = served
    context = tmp_path / "context_layer"
    (context / "policies").mkdir(parents=True)
    page = (
        "---\n"
        "type: policy\n"
        "title: Passage demo\n"
        "description: revenue rules summary with a xylophone marker\n"
        "---\n"
        "\n"
        "# Real heading above\n"
        "\n"
        "Revenue rules live in this paragraph.\n"
        "\n"
        "```\n"
        "# Fenced not a heading\n"
        "```\n"
        "\n"
        "The zebra clause applies after the fence.\n"
        "\n"
        "# Later heading\n"
        "\n"
        "Ignored trailing body.\n"
        "\n"
        "## Code corner\n"
        "\n"
        "```\n"
        "# Fake fenced heading\n"
        "quokka lives only inside this fenced block\n"
        "```\n"
        "\n"
        "~~~\n"
        "# Tilde fake heading\n"
        "wombat drafts inside a tilde fence\n"
        "~~~\n"
        "\n"
        "Yacc paragraph after the tilde fence.\n"
        "\n"
        "## Outer heading\n"
        "\n"
        "~~~~\n"
        "~~~\n"
        "# Fake nested-tilde heading\n"
        "pangolin note inside the four-tilde fence\n"
        "~~~~\n"
        "\n"
        "Okapi paragraph after the four-tilde fence.\n"
    )
    (context / "policies" / "passage-demo.md").write_text(page, encoding="utf-8")
    facade = Facade(served_dir / "semantic_layer", context, db, staging_dir=tmp_path / "staging")

    def hit_for(query):
        return asyncio.run(facade.search_context(query))[0]

    # Body match after a fenced block: the fence's fake heading is skipped, the
    # real heading above names the section.
    hit = hit_for("zebra")
    assert hit["path"] == "policies/passage-demo.md" and hit["draft"] is False
    assert "zebra" in hit["excerpt"]
    assert hit["excerpt"] in hit["content"]  # bounded verbatim substring
    lines = hit["content"].split("\n")
    assert 1 <= hit["line_start"] <= hit["line_end"] <= len(lines)
    assert hit["excerpt"] in "\n".join(lines[hit["line_start"] - 1 : hit["line_end"]])
    assert hit["section"] == "Real heading above"

    # A match below a later real heading resolves to that heading.
    assert hit_for("trailing")["section"] == "Later heading"

    # A query matching an actual heading line names that heading itself, not
    # the preceding one.
    hit = hit_for("later")
    assert "Later heading" in hit["excerpt"]
    assert hit["section"] == "Later heading"

    # Body match preferred over the frontmatter line that also matches.
    hit = hit_for("revenue")
    assert hit["excerpt"].startswith("Revenue rules")
    assert hit["section"] == "Real heading above"

    # Frontmatter-only match: coordinates land inside the frontmatter block and
    # no body section is fabricated.
    hit = hit_for("xylophone")
    assert "xylophone" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == 4  # the description line, inside the frontmatter
    assert hit["section"] is None

    # Fenced-only match: the page stays searchable (it is still a hit) and its
    # passage sits on the fenced line — the fence's own fake heading never names
    # the section; the real heading surrounding the fence does.
    hit = hit_for("quokka")
    assert hit["path"] == "policies/passage-demo.md"
    assert "quokka" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == hit["line_end"] == 25  # the fenced quokka line
    assert hit["section"] == "Code corner"

    # Tilde fences behave exactly like backtick fences: a fenced-only match
    # stays searchable, and the tilde block's fake heading neither names its own
    # passage nor establishes a section for subsequent passages.
    hit = hit_for("wombat")
    assert hit["path"] == "policies/passage-demo.md"
    assert "wombat" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == hit["line_end"] == 30  # the tilde-fenced wombat line
    assert hit["section"] == "Code corner"
    assert hit_for("yacc")["section"] == "Code corner"

    # A closing fence needs the same marker at least as long as the opener: a
    # ~~~ line inside a ~~~~ fence stays literal, so the fence's fake heading
    # neither names its own passage nor establishes a section for the passage
    # after the real ~~~~ close.
    hit = hit_for("pangolin")
    assert hit["path"] == "policies/passage-demo.md"
    assert "pangolin" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == hit["line_end"] == 40  # still inside the ~~~~ fence
    assert hit["section"] == "Outer heading"
    assert hit_for("okapi")["section"] == "Outer heading"  # after the real close

    # Failure shape: empty query and nonpositive limits return no hits.
    assert asyncio.run(facade.search_context("")) == []
    assert asyncio.run(facade.search_context("zebra", limit=0)) == []
    assert asyncio.run(facade.search_context("zebra", limit=-3)) == []


def test_serve_main_explicit_db_beats_ambient_registry(tmp_path, monkeypatch):
    """With an ambient ./ariadne.yaml present, an explicit --db still selects
    the legacy single-sqlite shorthand (registry only when neither is given)."""
    import ariadne.serve as serve_module

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: missing.db\n",
        encoding="utf-8",
    )
    served = tmp_path / "semantic_layer" / "models"
    served.mkdir(parents=True)
    (served / "orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
    db = seed_demo_db(tmp_path / "demo.db")
    built: list = []

    class FakeApp:
        def __init__(self, facade, **kwargs):
            built.append(facade)

        def run(self):
            pass

    monkeypatch.setattr(serve_module, "build_app", FakeApp)
    code = serve_module.main(
        [
            "--semantic",
            str(tmp_path / "semantic_layer"),
            "--context",
            str(tmp_path / "context_layer"),
            "--db",
            str(db),
            "--staging",
            str(tmp_path / "staging"),
        ]
    )
    assert code == 0
    assert built and built[0]._qualified is False  # legacy --db shorthand won


def test_serve_main_without_http_flag_stays_stdio_only(tmp_path, monkeypatch):
    """Issue #18 LOCAL-ONLY: without the explicit --http flag nothing listens —
    the same build_app is served over stdio only, and the uvicorn import path
    is never even taken (token env absent or present, it is inert)."""
    import sys

    import ariadne.serve as serve_module

    monkeypatch.chdir(tmp_path)
    served: list = []

    class FakeApp:
        def __init__(self, facade, **kwargs):
            served.append(facade)

        def run(self):
            served.append("stdio-run")

    monkeypatch.setattr(serve_module, "build_app", FakeApp)
    # any attempt to import uvicorn (the HTTP listener path) fails loudly
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    code = serve_module.main([])
    assert code == 0
    assert served[-1] == "stdio-run" and len(served) == 2  # built, then stdio-run
