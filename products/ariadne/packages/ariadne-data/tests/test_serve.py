"""MCP adapter boundaries and the governed native-session contract tests.

The governed seam is one admitted native retail demo project (the S2
journey); the standalone ad-hoc ``define_metric`` guards keep the sanctioned
private numerical session (models + demo DB, no admission). Numerical
expectations come from ``tests/fixtures/expected_metrics.json`` or
independent SQL; public project admission is exercised in the Git lifecycle
tests.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_AREA = Path(__file__).resolve().parents[3]  # Ariadne product area (spec 0031 §2)
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.query import _QueryRuntimeSession as Facade  # noqa: E402

GOTCHA_1 = "CANCELLED and RETURNED orders are not revenue"
GOTCHA_2 = "multiply both figures by rate_to_usd"

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
        "ariadne_seed_db", PRODUCT_AREA / "examples" / "retail-demo" / "seed_db.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.seed(db_path)
    return db_path


# Passage coordinates below are hand-counted from this native Reference (spec0002).
PASSAGE_PAGE = """---
id: "entity:passage-demo"
title: "Passage demo"
entity_types:
  - reference
tags: [passage]
summary: "revenue rules summary with a xylophone marker"
lifecycle: approved
visibility: public
sources:
  - id: seed-notes
    title: Seed notes
ariadne_profile:
  version: 1
  kind: reference
  native:
    type: reference
    title: Passage demo
    description: revenue rules summary
    tags:
      - passage
    sources:
      - id: seed-notes
        title: Seed notes
---

# Real heading above

Revenue rules live in this paragraph.

```
# Fenced not a heading
```

The zebra clause applies after the fence.

# Later heading

Ignored trailing body.

## Code corner

```
# Fake fenced heading
quokka lives only inside this fenced block
```

~~~
# Tilde fake heading
wombat drafts inside a tilde fence
~~~

Yacc paragraph after the tilde fence.

## Outer heading

~~~~
~~~
# Fake nested-tilde heading
pangolin note inside the four-tilde fence
~~~~

Okapi paragraph after the four-tilde fence.
"""


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """One admitted native retail demo (the S2 journey) plus one second
    admitted proposal adding the passage-demo Reference page — the governed
    seam; the demo DB backs independent SQL."""
    from ariadne.authoring import AuthoringProject
    from tests.test_cli import create_git_demo_project
    from tests.test_git_admission import admit
    from tests.test_git_authoring import approved

    project, db = create_git_demo_project(tmp_path_factory.mktemp("demo") / "project")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    paged = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        [{"path": "knowledge/references/passage-demo.md", "content": PASSAGE_PAGE}],
    )
    validated = api.validate_proposal(started["proposal"], paged["revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    return project, db


@pytest.fixture(scope="module")
def facade(served):
    from ariadne.query import QueryRuntime

    project, _db = served
    return QueryRuntime.open_project(project)


@pytest.fixture(scope="module")
def private(tmp_path_factory):
    """The sanctioned private numerical session (models + demo DB, no
    admission): the standalone ad-hoc ``define_metric`` route's seam."""
    tmp = tmp_path_factory.mktemp("adhoc-fixture")
    db = seed_demo_db(tmp / "demo.db")
    models = tmp / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
    (tmp / "context_layer").mkdir()
    return Facade(tmp / "semantic_layer", tmp / "context_layer", db), db


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


def test_range_filters_on_primary_date_dimension(facade):
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
    from ariadne.query import QueryRuntime
    from ariadne.serve import build_app

    project, _db = served
    app = build_app(QueryRuntime, project=str(project))
    desc = {tool.name: tool.description or "" for tool in asyncio.run(app.list_tools())}
    assert "no governed metric answers" in desc["define_metric"]
    assert "define_metric" in desc["list_datasets"]
    assert "dimensions" in desc["list_metrics"]


def test_http_body_bound_is_independent_of_document_uploads():
    """Retiring uploads preserves the existing fixed MCP request-body ceiling."""
    from ariadne.serve import build_http_app

    class FakeMCPServer:
        options: dict

        def streamable_http_app(self, **options):
            self.options = options
            return object()

    server = FakeMCPServer()
    build_http_app(server, "synthetic-token")
    assert server.options["max_request_body_size"] == (5 * 1024 * 1024 * 4 // 3) + 65_536


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
    source-approval, Git Review Admission or example-review tool (ADR-0013/#20:
    review is human-only; the surfaces are tool-surface separation, spec §6)."""
    from ariadne.query import QueryRuntime
    from ariadne.serve import build_app

    project, _db = served
    app = build_app(QueryRuntime, project=str(project))
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
        "authoring_validate_proposal",
        "authoring_refresh_schema",
        "authoring_resolve_term",
        "authoring_inspect_mapping",
        "authoring_review_proposal",
    }
    assert not [tool for tool in tools if "approve" in tool.name or "promot" in tool.name]


# --- Ad-hoc query layer (spec revision 3, §8.8-8.11) -------------------------


def test_list_datasets_returns_demo_tables_with_columns(facade):
    datasets = {d["name"]: d for d in asyncio.run(facade.list_datasets())}
    assert set(datasets) == {"demo.orders", "demo.customers", "demo.currency_conversion_rate"}
    order_columns = {c["name"]: c["type"] for c in datasets["demo.orders"]["columns"]}
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
    """The governed response carries the full metric page AND the full bodies
    of both policies its closure requires (gross_margin requires
    order-status-billing and emea-currency-cutover)."""
    result = asyncio.run(facade.get_metric("gross_margin", ["region"]))
    context = result["context"]
    assert GOTCHA_1 in context["metric_page"]  # the metric page itself, full text
    assert GOTCHA_2 in context["metric_page"]
    assert len(context["policies"]) == 2
    bodies = context["policies"]  # closure order is not part of the contract
    assert any(GOTCHA_1 in body for body in bodies)  # order-status-billing body
    assert any(GOTCHA_2 in body for body in bodies)  # emea-currency-cutover body


def test_adhoc_define_metric_carries_context_null(private):
    """Ad-hoc metrics have no served page: context is exactly null."""
    session, _db = private
    result = asyncio.run(
        session.define_metric(
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


# C6 fallback retirement: native write, browsing and pinned-digest guards replace raw reads.


def test_missing_required_policy_refuses_at_the_write_gate(tmp_path):
    """The retired collapse-and-continue fallback is gone: a metric page
    citing a missing Policy refuses at the native batch-write gate — before
    validation, admission, compile or any SQL execution."""
    from lumio_wiki.git_authoring import GitAuthoringError

    from ariadne.authoring import AuthoringProject
    from tests import test_git_authoring

    project = test_git_authoring.complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    dangling = test_git_authoring.NATIVE_METRIC_PAGE.replace(
        "policies/all-events-count.md", "policies/missing-policy.md"
    ).replace("entity:all-events-count", "entity:missing-policy")
    with pytest.raises(
        GitAuthoringError,
        match="required policy entity 'entity:missing-policy' does not exist",
    ):
        api.edit_pages_batch(
            started["proposal"],
            started["candidate_revision"],
            [{"path": test_git_authoring.NATIVE_METRIC_REL, "content": dangling}],
        )


def test_get_metric_discloses_expired_and_deprecated_policy_signals(tmp_path):
    """Spec0011 §§5/8: advisory Policy states preserve the retail golden,
    baseline rows/SQL/governance and full rules; assessment changes no bytes."""
    from datetime import date

    import yaml

    from ariadne.authoring import AuthoringProject
    from ariadne.query import QueryRuntime
    from tests.test_cli import NAMESPACE, create_git_demo_project
    from tests.test_git_admission import admit, read_current
    from tests.test_git_authoring import approved, run_git

    project, _db = create_git_demo_project(tmp_path / "project")
    admitted_base = read_current(project)["commit"]
    run_git(project, "merge", "--ff-only", admitted_base)
    assert run_git(project, "rev-parse", "HEAD").strip() == admitted_base
    baseline = asyncio.run(
        QueryRuntime.open_project(project).get_metric("gross_margin", ["region"])
    )
    policy_paths = (
        "knowledge/policies/order-status-billing.md",
        "knowledge/policies/emea-currency-cutover.md",
    )
    edits = []
    for relative, changes in (
        (policy_paths[0], {"stale_after": date(2020, 1, 1)}),
        (policy_paths[1], {"status": "deprecated"}),
        (
            "knowledge/metrics/gross_margin.md",
            {
                "status": "review_needed",
                "stale_after": date(2030, 1, 1),
                "verified": [],
                "generated": {"by": "ariadne-author"},
            },
        ),
    ):
        _opening, front, body = (project / relative).read_text(encoding="utf-8").split("---", 2)
        meta = yaml.safe_load(front)
        meta["ariadne_profile"]["native"].update(changes)
        edits.append(
            {"path": relative, "content": f"---\n{yaml.safe_dump(meta, sort_keys=False)}---{body}"}
        )
    # Historical system-owned metadata belongs in the human base, not an agent edit.
    for edit in edits:
        (project / edit["path"]).write_text(edit["content"], encoding="utf-8")
    run_git(project, "add", "--", *(edit["path"] for edit in edits))
    run_git(project, "commit", "-q", "-m", "human: inherited advisory metadata")
    human_base = run_git(project, "rev-parse", "HEAD").strip()
    api = AuthoringProject(project)
    started = api.start_proposal(base_revision=human_base)
    assert started["base_revision"] == human_base
    approved(api, project, started)
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    record = read_current(project)
    snapshot = project / record["snapshot"]
    before = {snapshot / path: (snapshot / path).read_bytes() for path in policy_paths}

    result = asyncio.run(QueryRuntime.open_project(project).get_metric("gross_margin", ["region"]))
    assert sorted(result["rows"], key=lambda row: row["region"]) == sorted(
        baseline["rows"], key=lambda row: row["region"]
    )
    assert result["sql"] == baseline["sql"]
    assert result["governed"] == baseline["governed"] is True
    assert_matches_fixture(rows_by_region(result, "gross_margin"), "gross_margin")
    assert GOTCHA_1 in result["context"]["metric_page"]
    assert GOTCHA_2 in result["context"]["metric_page"]
    assert any(GOTCHA_1 in body for body in result["context"]["policies"])
    assert any(GOTCHA_2 in body for body in result["context"]["policies"])

    cited_pages = (
        ("metrics/gross_margin.md", "entity:gross-margin"),
        ("policies/order-status-billing.md", "entity:order-status-billing"),
        ("policies/emea-currency-cutover.md", "entity:emea-currency-cutover"),
    )
    # Exact page/release identities stay in the citations block ...
    assert {c["citation"] for c in result["context"]["citations"]} >= {
        f"{NAMESPACE} {entity} v{record['commit']} {path}" for path, entity in cited_pages
    }
    # ... while signals identify each page by its bundle-relative path (spec0011 §4).
    expected_citations = {
        path: path for path in (*(p for p, _ in cited_pages), "computations/gross_margin.md")
    }
    signals = result["context"]["context_signals"]
    views = {page["path"]: page for page in signals["pages"]}
    assert len(signals["pages"]) == 4
    assert set(views) == set(expected_citations.values())
    expected_warnings = [
        {"code": "context_stale", "path": expected_citations["policies/order-status-billing.md"]},
        {
            "code": "context_deprecated",
            "path": expected_citations["policies/emea-currency-cutover.md"],
        },
    ]
    assert sorted(signals["warnings"], key=lambda warning: warning["path"]) == sorted(
        expected_warnings, key=lambda warning: warning["path"]
    )
    metric_view = views[expected_citations["metrics/gross_margin.md"]]
    assert metric_view["status"] == "review_needed"
    assert metric_view["verification_tier"] == "unverified" and metric_view["verified"] == []
    assert metric_view["generated"] == {"by": "ariadne-author"}
    assert metric_view["freshness"] == {"stale_after": "2030-01-01", "state": "current"}
    assert views[expected_citations["policies/order-status-billing.md"]]["freshness"] == {
        "stale_after": "2020-01-01",
        "state": "stale",
    }
    assert views[expected_citations["policies/emea-currency-cutover.md"]]["status"] == "deprecated"
    assert views[expected_citations["computations/gross_margin.md"]]["status"] == "draft"
    assert {page: page.read_bytes() for page in before} == before


_JOIN_SOURCE = (
    "SELECT o.customer_id, c.name AS customer_name, o.amount, o.status "
    "FROM orders o JOIN customers c ON o.customer_id = c.id"
)
_MEAN_EXPR = "AVG(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount END)"


def test_define_metric_adhoc_mean_per_customer(private):
    """§8.8: ephemeral agent-authored join source, fixture-checked."""
    session, db = private
    result = asyncio.run(
        session.define_metric(
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


def test_define_metric_nonexistent_column_refuses(private):
    session, _db = private
    with pytest.raises(ValueError, match="nonexistent_col"):
        asyncio.run(
            session.define_metric(
                {
                    "name": "broken_metric",
                    "description": "references a column that does not exist",
                    "source": "orders",
                    "expression": "SUM(nonexistent_col)",
                    "dimensions": [],
                }
            )
        )


def test_define_metric_compile_error_surfaced_verbatim(private):
    session, _db = private
    """A definition rejected by the compiler surfaces its error verbatim."""
    with pytest.raises(ValueError, match="could not parse expression"):
        asyncio.run(
            session.define_metric(
                {
                    "name": "syntax_error_metric",
                    "description": "malformed aggregate",
                    "source": "orders",
                    "expression": "SUM((",
                    "dimensions": [],
                }
            )
        )


def test_define_metric_rejects_unsane_name(private):
    session, _db = private
    with pytest.raises(ValueError, match="lowercase snake_case"):
        asyncio.run(
            session.define_metric(
                {
                    "name": "Bad Name!",
                    "description": "not a slug",
                    "source": "orders",
                    "expression": "SUM(amount)",
                }
            )
        )


def test_define_metric_repeated_calls_are_ephemeral(private):
    session, _db = private
    definition = {
        "name": "collision_probe_metric",
        "description": "same name twice",
        "source": "orders",
        "expression": "SUM(amount)",
        "dimensions": [],
    }
    first = asyncio.run(session.define_metric(dict(definition)))
    second = asyncio.run(session.define_metric(dict(definition)))
    assert first["rows"] == second["rows"]
    assert first["persistence"] == second["persistence"] == {"status": "not_saved"}
    assert "staged_as" not in first and "staged_context_as" not in first
    assert "staged_as" not in second and "staged_context_as" not in second


def test_define_metric_does_not_create_a_context_draft(facade):
    description = "probe for an unsaved ad-hoc definition"
    result = asyncio.run(
        facade.define_metric(
            {
                "name": "page_probe_metric",
                "description": description,
                "source": "demo.main.orders",  # the catalog's exact identity
                "expression": "SUM(amount)",
                "dimensions": ["status"],
            }
        )
    )
    assert result["persistence"] == {"status": "not_saved"}
    assert "staged_as" not in result and "staged_context_as" not in result
    hits = asyncio.run(facade.search_context(description))
    assert not any(hit["path"] == "metrics/page_probe_metric.md" for hit in hits)


_INJECTION_SOURCE = "orders) ; CREATE TEMP TABLE pwned(x int); SELECT * FROM (SELECT 1"


def test_define_metric_rejects_multi_statement_compiled_sql(private):
    session, _db = private
    """A crafted multi-statement source is rejected before any DuckDB call."""
    with pytest.raises(ValueError, match="exactly one statement"):
        asyncio.run(
            session.define_metric(
                {
                    "name": "pwned_metric",
                    "description": "injection probe",
                    "source": _INJECTION_SOURCE,
                    "expression": "SUM(amount)",
                    "dimensions": [],
                }
            )
        )
    tables = {
        row[0] for row in session.con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
    }
    assert "pwned" not in tables  # the smuggled DDL never ran


def test_define_metric_allows_semicolon_inside_string_literal(private):
    session, _db = private
    """Parser correctness: a quoted semicolon in the compiled SQL must not trip
    the single-statement guard — the definition still compiles and executes."""
    result = asyncio.run(
        session.define_metric(
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


def test_define_metric_rejects_fanned_out_join_source(private):
    session, _db = private
    """A non-unique join key violates the grain-preservation guard."""
    with pytest.raises(ValueError, match="grain-preservation invariant.*pivot"):
        asyncio.run(
            session.define_metric(
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


def test_grain_guidance_names_the_adr_0006_rubric():
    """Spec rev 6: the rejection guidance names the ADR-0006 resolution rubric by
    pattern (pivot / child-grain fact model / fact weight allocation) instead of
    the bare GROUP BY phrasing — end-to-end through a real define_metric
    rejection and in the shared constant the tool description derives from."""
    from ariadne.serve import GRAIN_GUIDANCE

    for pattern in ("pivot", "child-grain fact model", "weight allocation", "ADR-0006"):
        assert pattern in GRAIN_GUIDANCE
    assert "GROUP BY" not in GRAIN_GUIDANCE  # rubric names replaced the bare phrasing


def test_define_metric_rejects_cross_join_source(private):
    session, _db = private
    """§13 grain guard: a CROSS (or comma) join has no key to prove unique —
    unbounded row multiplication is rejected outright."""
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            session.define_metric(
                {
                    "name": "cross_metric",
                    "description": "cross join fans out unboundedly",
                    "source": "SELECT o.order_id, c.name FROM orders o CROSS JOIN customers c",
                    "expression": "SUM(o.amount)",
                    "dimensions": [],
                }
            )
        )


def test_define_metric_rejects_on_true_cartesian_source(private):
    session, _db = private
    """§13 grain guard correction: `ON TRUE` has zero equality keys — the old
    per-key loop never ran, so the cartesian product passed the guard and
    executed, returning inflated aggregates. Fail closed before compile."""
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            session.define_metric(
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


def test_define_metric_rejects_non_equality_join_predicate(private):
    session, _db = private
    """§13 grain guard correction: an ON with only a non-equality predicate has
    no attributable equality key to prove — the guard cannot establish grain
    preservation, so it fails closed with the grain guidance."""
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            session.define_metric(
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


def test_define_metric_allows_grain_preserving_join(private):
    session, _db = private
    """§13 grain guard upside: the many-to-one direction (orders ⋈ customers on
    the customers primary key) stays legitimate — same shape as the ad-hoc
    acceptance definition; the guard must not reject it."""
    result = asyncio.run(
        session.define_metric(
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
    assert result["persistence"] == {"status": "not_saved"}


def test_serve_facade_is_the_runtime_class():
    """Ticket #7: ariadne.serve.Facade is the exact runtime class — a plain
    alias, never a subclass or wrapper that could diverge."""
    import ariadne.runtime
    import ariadne.serve

    assert ariadne.serve.Facade is ariadne.runtime.AriadneRuntime


def test_startup_fails_fast_without_models(tmp_path):
    with pytest.raises(RuntimeError, match="no semantic models"):
        Facade(tmp_path / "semantic_layer", tmp_path / "context_layer", tmp_path / "demo.db")


# --- Measured Context Layer retrieval (spec 2026-09-23-0002, issue #10) -------


RETRIEVAL_CORPUS = json.loads(
    (REPO_ROOT / "tests" / "evals" / "context_retrieval.json").read_text(encoding="utf-8")
)


def test_context_retrieval_corpus_recall_at_five(served):
    """The checked-in corpus retrieves from the admitted Context only."""
    from ariadne.query import QueryRuntime

    project, _db = served
    facade = QueryRuntime.open_project(project)
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


def test_search_context_passage_coordinates_and_sections(served):
    """AC3/AC4: each hit carries a bounded verbatim excerpt with inclusive 1-based
    line coordinates and the containing heading — frontmatter-only matches have
    no invented section, headings inside fenced code (backtick or tilde) never
    name a section, a body match is preferred over a frontmatter match, and a
    query matching an actual heading line names that heading itself. A page
    whose only match is inside a fenced code block stays a hit (every Markdown
    category remains searchable) and resolves to the surrounding real heading.
    The passage page is the admitted demo's native Reference page; every
    asserted coordinate is hand-counted from PASSAGE_PAGE's exact text."""
    from ariadne.query import QueryRuntime

    project, _db = served
    facade = QueryRuntime.open_project(project)

    def hit_for(query):
        # Isolate passage evidence; the corpus test owns global top-five ranking.
        hits = asyncio.run(facade.search_context(query, limit=20))
        return next(hit for hit in hits if hit["path"] == "references/passage-demo.md")

    # Body match after a fenced block: the fence's fake heading is skipped, the
    # real heading above names the section.
    hit = hit_for("zebra")
    assert hit["path"] == "references/passage-demo.md" and hit["draft"] is False
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
    assert hit["line_start"] == 7  # the authored canonical summary, inside the frontmatter
    assert hit["section"] is None

    # Fenced-only match: the page stays searchable (it is still a hit) and its
    # passage sits on the fenced line — the fence's own fake heading never names
    # the section; the real heading surrounding the fence does.
    hit = hit_for("quokka")
    assert hit["path"] == "references/passage-demo.md"
    assert "quokka" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == hit["line_end"] == 45  # the fenced quokka line
    assert hit["section"] == "Code corner"

    # Tilde fences behave exactly like backtick fences: a fenced-only match
    # stays searchable, and the tilde block's fake heading neither names its own
    # passage nor establishes a section for subsequent passages.
    hit = hit_for("wombat")
    assert hit["path"] == "references/passage-demo.md"
    assert "wombat" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == hit["line_end"] == 50  # the tilde-fenced wombat line
    assert hit["section"] == "Code corner"
    assert hit_for("yacc")["section"] == "Code corner"

    # A closing fence needs the same marker at least as long as the opener: a
    # ~~~ line inside a ~~~~ fence stays literal, so the fence's fake heading
    # neither names its own passage nor establishes a section for the passage
    # after the real ~~~~ close.
    hit = hit_for("pangolin")
    assert hit["path"] == "references/passage-demo.md"
    assert "pangolin" in hit["excerpt"] and hit["excerpt"] in hit["content"]
    assert hit["line_start"] == hit["line_end"] == 60  # still inside the ~~~~ fence
    assert hit["section"] == "Outer heading"
    assert hit_for("okapi")["section"] == "Outer heading"  # after the real close

    # Failure shape: empty query and nonpositive limits return no hits.
    assert asyncio.run(facade.search_context("")) == []
    assert asyncio.run(facade.search_context("zebra", limit=0)) == []
    assert asyncio.run(facade.search_context("zebra", limit=-3)) == []


def test_serve_main_anchors_tools_to_explicit_project(tmp_path, monkeypatch):
    import ariadne.serve as serve_module

    project = tmp_path / "project"
    project.mkdir()
    built = []

    class FakeApp:
        def __init__(self, facade, **kwargs):
            built.append((facade, Path.cwd()))

        def run(self):
            pass

    monkeypatch.setattr(serve_module, "build_app", FakeApp)
    code = serve_module.main(["--project", str(project), "--toolset", "authoring"])
    assert code == 0
    assert built and built[0][1] == project


def test_serve_main_without_http_flag_stays_stdio_only(tmp_path, monkeypatch):
    """Without --http, the adapter runs over stdio and does not import uvicorn."""
    import sys

    import ariadne.serve as serve_module

    project = tmp_path / "project"
    project.mkdir()
    served: list = []

    class FakeApp:
        def __init__(self, facade, **kwargs):
            served.append(facade)

        def run(self):
            served.append("stdio-run")

    monkeypatch.setattr(serve_module, "build_app", FakeApp)
    # any attempt to import uvicorn (the HTTP listener path) fails loudly
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    code = serve_module.main(["--project", str(project), "--toolset", "authoring"])
    assert code == 0
    assert served[-1] == "stdio-run" and len(served) == 2  # built, then stdio-run
