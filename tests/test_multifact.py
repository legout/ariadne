"""Multi-fact core task 1: normalized OSI layouts + graph validation (issue #26).

Spec rev 1 "Authoring contract and normalized graph": the domain layout (one
multi-dataset OSI file) and the source layout (per-source OSI files plus
``semantic_layer/graph.yml``) normalize to ONE ``SemanticGraph``; contradictory
declarations and ambiguous metric ownership fail at the ``load_graph`` /
``validate`` seam — BEFORE any SELECT is compiled. The fixture is a registered
SQLite source (source-backed, not an in-memory dict); live relationship-target
audits are task 2 (#27) and must surface as not-run, never as a pass.
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import (  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
    exp,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import admission  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.grain import relationship_target_audit  # noqa: E402
from ariadne.planner import PlannerError, plan_query  # noqa: E402
from ariadne.semantic_graph import GraphError, load_graph  # noqa: E402
from ariadne.sources import build_connection, load_registry  # noqa: E402
from ariadne.validate import validate  # noqa: E402
from tests.test_git_admission import admit  # noqa: E402
from tests.test_git_authoring import approved, run_git  # noqa: E402

# (order_id, region, amount, customer_id) / (line_id, order_id, region,
# line_amount): the per-order line sums equal the order amounts, and each line
# carries its order's region — the conformed business key is real on both facts.
# customer_id adds the task 3 lookup chain orders -> customers (tier), making
# tier a TWO-hop dimension from the order_lines branch.
ORDERS = [(1, "NA", 100.0, 1), (2, "NA", 200.0, 2), (3, "EMEA", 400.0, 1)]
CUSTOMERS = [(1, "gold"), (2, "standard")]
LINES = [
    (11, 1, "NA", 60.0),
    (12, 1, "NA", 30.0),
    (13, 1, "NA", 10.0),
    (21, 2, "NA", 150.0),
    (22, 2, "NA", 50.0),
    (31, 3, "EMEA", 400.0),
]
# Task 2 (issue #27): a third fact carrying one otherwise-unmatched APAC group
# and one NULL-key group (spec rev 1 acceptance 2), plus a mutable lookup pair
# whose target key can drift (acceptance 3) — owners has NO sqlite PK so the
# duplicate/NULL inserts below are possible.
SHIPMENTS = [(1, "APAC", 5.0), (2, "APAC", 7.0), (3, None, 9.0)]
EVENTS = [(1, 10, 3.0), (2, 10, 4.0), (3, 20, 5.0)]
OWNERS = [(10, "ada"), (20, "bob")]
# Fix pass F2 (review c90ca081): a composite target key whose COMPONENTS repeat
# while every TUPLE is unique — valid for the exact tuple audit, wrongly refused
# by the legacy per-column grain guard when it was pointed at generated joins.
TASKS = [(1, 1, 1, 3.0), (2, 1, 2, 4.0), (3, 2, 1, 5.0)]
TEAMS = [(1, 1, "alpha"), (1, 2, "beta"), (2, 1, "gamma")]


# Task 4 (issue #29): a time-conformance fact pair whose business dates are
# DIFFERENTLY NAMED (orders.ordered_on, day grain; order lines shipped_on,
# month grain) — conformance is by declaration, never by column name. The
# line for order 4 ships one month later than its order, so March is an
# orders-only month and April a lines-only month: the aligned keys union must
# keep both unmatched groups.
DATED_ORDERS = [
    (1, "NA", "2026-01-10", 100.0, 1),
    (2, "NA", "2026-01-20", 200.0, 2),
    (3, "EMEA", "2026-02-05", 400.0, 1),
    (4, "EMEA", "2026-03-15", 50.0, 2),
]
DATED_LINES = [
    (11, 1, "NA", "2026-01-01", 60.0),
    (12, 1, "NA", "2026-01-01", 30.0),
    (13, 1, "NA", "2026-01-01", 10.0),
    (21, 2, "NA", "2026-01-01", 150.0),
    (22, 2, "NA", "2026-01-01", 50.0),
    (31, 3, "EMEA", "2026-02-01", 250.0),
    (41, 4, "EMEA", "2026-04-01", 75.0),
]
DATED_CUSTOMERS = [(1, "gold"), (2, "standard")]


def build_source_fixture(root: Path) -> Path:
    """The registered SQLite source (``ariadne.yaml`` + ``mf.db``); returns the
    registry path — the sanctioned source-backed audit connection."""
    root.mkdir(parents=True, exist_ok=True)
    db = root / "mf.db"
    con = sqlite3.connect(db)
    try:
        con.executescript(
            """
            CREATE TABLE orders (
                order_id    INTEGER PRIMARY KEY,
                region      TEXT NOT NULL,
                amount      REAL NOT NULL,
                customer_id INTEGER NOT NULL REFERENCES customers (customer_id)
            );
            CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY,
                tier        TEXT NOT NULL
            );
            CREATE TABLE order_lines (
                line_id     INTEGER PRIMARY KEY,
                order_id    INTEGER NOT NULL REFERENCES orders (order_id),
                region      TEXT NOT NULL,
                line_amount REAL NOT NULL
            );
            CREATE TABLE shipments (
                shipment_id INTEGER PRIMARY KEY,
                region      TEXT,
                shipped_qty REAL NOT NULL
            );
            CREATE TABLE events (
                event_id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                amount  REAL NOT NULL
            );
            CREATE TABLE owners (
                owner_id   INTEGER,
                owner_name TEXT NOT NULL
            );
            CREATE TABLE tasks (
                task_id INTEGER PRIMARY KEY,
                team_a  INTEGER NOT NULL,
                team_b  INTEGER NOT NULL,
                hours   REAL NOT NULL
            );
            CREATE TABLE teams (
                team_a    INTEGER NOT NULL,
                team_b    INTEGER NOT NULL,
                team_name TEXT NOT NULL
            );
            CREATE TABLE dated_orders (
                order_id    INTEGER PRIMARY KEY,
                region      TEXT NOT NULL,
                ordered_on  DATE NOT NULL,
                amount      REAL NOT NULL,
                customer_id INTEGER NOT NULL REFERENCES dated_customers (customer_id)
            );
            CREATE TABLE dated_customers (
                customer_id INTEGER PRIMARY KEY,
                tier        TEXT NOT NULL
            );
            CREATE TABLE dated_lines (
                line_id     INTEGER PRIMARY KEY,
                order_id    INTEGER NOT NULL REFERENCES dated_orders (order_id),
                region      TEXT NOT NULL,
                shipped_on  DATE NOT NULL,
                line_amount REAL NOT NULL
            );
            """
        )
        # static literal SQL with ?-bound parameters; rows are module constants
        for statement, rows in (
            ("INSERT INTO orders VALUES (?, ?, ?, ?)", ORDERS),
            ("INSERT INTO customers VALUES (?, ?)", CUSTOMERS),
            ("INSERT INTO order_lines VALUES (?, ?, ?, ?)", LINES),
            ("INSERT INTO shipments VALUES (?, ?, ?)", SHIPMENTS),
            ("INSERT INTO events VALUES (?, ?, ?)", EVENTS),
            ("INSERT INTO owners VALUES (?, ?)", OWNERS),
            ("INSERT INTO tasks VALUES (?, ?, ?, ?)", TASKS),
            ("INSERT INTO teams VALUES (?, ?, ?)", TEAMS),
            ("INSERT INTO dated_orders VALUES (?, ?, ?, ?, ?)", DATED_ORDERS),
            ("INSERT INTO dated_customers VALUES (?, ?)", DATED_CUSTOMERS),
            ("INSERT INTO dated_lines VALUES (?, ?, ?, ?, ?)", DATED_LINES),
        ):
            con.executemany(statement, rows)  # pi-lens-ignore: python-sql-injection
        con.commit()
    finally:
        con.close()
    registry = root / "ariadne.yaml"
    registry.write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: mf.db\n", encoding="utf-8"
    )
    return registry


# --- Layout (a): one domain OSI file, several datasets + inline graph ---------

DOMAIN_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: sales
    description: Two-fact sales domain (spec rev 1 domain layout)
    requires: ["ariadne.conformed_dimensions@1"]
    datasets:
      - name: orders
        source: demo.main.orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
      - name: order_lines
        source: demo.main.order_lines
        primary_key: [line_id]
        fields:
          - name: line_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_id
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    relationships:
      - name: line_to_order
        cardinality: many_to_one
        from_dataset: order_lines
        from_fields: [order_id]
        to_dataset: orders
        to_fields: [order_id]
    conformed_dimensions:
      - name: region
        members:
          - dataset: orders
            field: region
          - dataset: order_lines
            field: region
    metrics:
      - name: orders_total
        dataset: orders
        description: Sum of order amounts at order grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: lines_total
        dataset: order_lines
        description: Sum of line amounts at line grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
      - name: order_count
        dataset: orders
        description: Count of orders (explicit owner for COUNT(*))
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

# --- Layout (b): per-source OSI files + cross-file graph.yml ------------------

ORDERS_SOURCE_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders fact (source layout)
    datasets:
      - name: orders
        source: demo.main.orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    metrics:
      - name: orders_total
        description: Sum of order amounts at order grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: order_count
        description: Count of orders (single-dataset model resolves COUNT(*))
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

LINES_SOURCE_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: order_lines
    description: Order lines fact (source layout)
    datasets:
      - name: order_lines
        source: demo.main.order_lines
        primary_key: [line_id]
        fields:
          - name: line_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_id
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    metrics:
      - name: lines_total
        description: Sum of line amounts at line grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""

GRAPH_YML = """\
version: 1
relationships:
  - name: line_to_order
    cardinality: many_to_one
    from_dataset: order_lines
    from_fields: [order_id]
    to_dataset: orders
    to_fields: [order_id]
conformed_dimensions:
  - name: region
    members:
      - dataset: orders
        field: region
      - dataset: order_lines
        field: region
"""

# Same endpoints as the inline relationship, opposite cardinality — the
# contradictory inline-vs-cross-file mapping the spec rejects before any SELECT.
CONTRADICTING_GRAPH_YML = GRAPH_YML.replace("cardinality: many_to_one", "cardinality: one_to_one")


def _staging(root: Path, models: dict[str, str], graph_yml: str | None = None) -> Path:
    """Write a staging tree (semantic_layer/models/*.yml + optional graph.yml)."""
    models_dir = root / "semantic_layer" / "models"
    models_dir.mkdir(parents=True)
    for name, yml in models.items():
        (models_dir / name).write_text(yml, encoding="utf-8")
    if graph_yml is not None:
        (root / "semantic_layer" / "graph.yml").write_text(graph_yml, encoding="utf-8")
    return root


def _normalized(graph):
    """The layout-independent graph identity: datasets, metric index, edges."""
    return (
        {n: (d.source, d.primary_key, d.fields) for n, d in graph.datasets.items()},
        {n: (m.owner, m.expression, m.derived) for n, m in graph.metrics.items()},
        graph.relationships,
        graph.conformed_dimensions,
    )


def _domain_staging(root: Path) -> Path:
    return _staging(root, {"sales.yml": DOMAIN_YML})


def _split_staging(root: Path) -> Path:
    return _staging(
        root, {"orders.yml": ORDERS_SOURCE_YML, "order_lines.yml": LINES_SOURCE_YML}, GRAPH_YML
    )


# --- Failure mode 1: layout divergence ----------------------------------------


def test_both_layouts_normalize_to_the_same_graph(tmp_path):
    domain = _domain_staging(tmp_path / "domain")
    split = _split_staging(tmp_path / "split")
    a = load_graph(domain / "semantic_layer")
    b = load_graph(split / "semantic_layer")
    assert _normalized(a) == _normalized(b)

    assert set(a.datasets) == {"orders", "order_lines"}  # declared grains carried
    assert a.datasets["orders"].primary_key == ("order_id",)
    assert a.datasets["order_lines"].primary_key == ("line_id",)

    # one project-wide metric index, each metric with exactly one owning dataset
    # (the domain layout declares owners explicitly; the source layout resolves
    # them — including COUNT(*) on a single-dataset model)
    assert {n: m.owner for n, m in a.metrics.items()} == {
        "orders_total": "orders",
        "lines_total": "order_lines",
        "order_count": "orders",
    }

    (edge,) = a.relationships
    assert edge.cardinality == "many_to_one"
    assert (edge.from_dataset, edge.to_dataset) == ("order_lines", "orders")
    assert edge.from_fields == ("order_id",) and edge.to_fields == ("order_id",)

    (conformed,) = a.conformed_dimensions
    assert conformed.members == (("orders", "region"), ("order_lines", "region"))


def test_both_layouts_validate_ok_with_live_relationship_audit(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    for staging in (_domain_staging(tmp_path / "domain"), _split_staging(tmp_path / "split")):
        result = validate(staging, sources_path=registry)
        assert result.ok, f"{staging.name}: {result.errors}"
        report = result.report
        assert report is not None
        assert report.scope == "structural+bind+grain"
        assert report.outcome("structural") == "passed"
        assert report.outcome("bind") == "passed"
        assert report.outcome("grain") == "passed"
        # issue #27: the live stage audits every declared relationship's target
        # key (composite tuple uniqueness + non-NULL); the planner rechecks the
        # participating subset per request. Never a silently-claimed pass.
        assert report.outcome("relationship_audit") == "passed"
        relationship = next(c for c in report.checks if c.name == "relationship_audit")
        assert "line_to_order" in relationship.detail
        assert report.registry_digest  # the audit is bound to the registry identity
        assert report.validator_version


# --- Failure mode 2: invalid graph fails before any SELECT ---------------------


def test_contradictory_edge_fails_before_any_select(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "st", {"sales.yml": DOMAIN_YML}, CONTRADICTING_GRAPH_YML)
    with pytest.raises(GraphError, match="contradictory"):
        load_graph(staging / "semantic_layer")
    result = validate(staging, sources_path=registry)
    assert not result.ok
    assert any("contradictory" in error for error in result.errors)
    # the failure is structural: nothing compiled, bound or audited afterwards
    report = result.report
    assert report is not None
    assert report.outcome("structural") == "failed"
    assert report.outcome("bind") == "not-run"
    assert report.outcome("grain") == "not-run"


def test_count_star_without_owning_dataset_fails(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    bad = DOMAIN_YML.replace(
        "      - name: order_count\n        dataset: orders\n", "      - name: order_count\n"
    )
    staging = _staging(tmp_path / "st", {"sales.yml": bad})
    with pytest.raises(GraphError, match="order_count.*dataset"):
        load_graph(staging / "semantic_layer")
    result = validate(staging, sources_path=registry)
    assert not result.ok
    assert any("order_count" in error for error in result.errors)


def test_duplicate_metric_names_fail_rather_than_overwrite(tmp_path):
    # same metric name on a DIFFERENT model/dataset — the project-wide index
    # must reject it instead of the old last-file-wins
    dup = ORDERS_SOURCE_YML.replace("  - name: orders\n", "  - name: orders_backup\n").replace(
        "      - name: orders\n        source:", "      - name: orders_backup\n        source:"
    )
    staging = _staging(tmp_path / "st", {"orders.yml": ORDERS_SOURCE_YML, "orders_copy.yml": dup})
    with pytest.raises(GraphError, match="duplicate metric 'orders_total'"):
        load_graph(staging / "semantic_layer")


def test_unsupported_requires_extension_key_fails(tmp_path):
    bad = DOMAIN_YML.replace(
        'requires: ["ariadne.conformed_dimensions@1"]',
        'requires: ["ktx.magic@9"]',
    )
    staging = _staging(tmp_path / "st", {"sales.yml": bad})
    with pytest.raises(GraphError, match="unsupported requires extension key"):
        load_graph(staging / "semantic_layer")


# --- Digest-bound report -------------------------------------------------------


def test_report_digest_binds_the_consumed_bytes(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    staging = _domain_staging(tmp_path / "domain")
    first = validate(staging, sources_path=registry)
    assert first.ok, first.errors
    assert first.report is not None
    digest = first.report.digest
    again = validate(staging, sources_path=registry)
    assert again.report is not None
    assert again.report.digest == digest  # deterministic
    model = staging / "semantic_layer" / "models" / "sales.yml"
    model.write_text(model.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    second = validate(staging, sources_path=registry)
    assert second.ok, second.errors
    assert second.report is not None
    assert second.report.digest != digest  # changed bytes invalidate the label


# --- Fix pass (review 71ba4026): the nine accepted findings F2–F10 ----------------


def test_f2_explicit_owner_must_agree_with_field_references(tmp_path):
    # F2: a non-derived metric with 'dataset: orders' whose expression also
    # references order_lines fields must fail at load — after qualifier
    # stripping it would compile wrong SQL against the orders source.
    bad = DOMAIN_YML.replace(
        "expression: SUM(amount)",
        "expression: SUM(orders.order_id + order_lines.order_id)",
    )
    staging = _staging(tmp_path / "st", {"sales.yml": bad})
    with pytest.raises(GraphError, match="owner"):
        load_graph(staging / "semantic_layer")
    result = validate(staging)
    assert not result.ok
    assert any("order_lines" in error for error in result.errors)


def test_f3_mixed_stage_derived_metric_with_bare_field_fails(tmp_path):
    # F3: derived metric with cross-fact metric dependencies PLUS a bare
    # row-grain field — only one FIELD owner exists, so the mixed-grain guard
    # passed; spec rev 1 §5 rejects mixed-grain/mixed-stage expressions.
    mixed = DOMAIN_YML + (
        "      - name: mixed_ratio\n"
        "        description: Mixed-stage derived metric (cross-fact deps + bare field)\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: orders_total / lines_total + orders.amount\n"
    )
    staging = _staging(tmp_path / "st", {"sales.yml": mixed})
    with pytest.raises(GraphError, match="mixed"):
        load_graph(staging / "semantic_layer")


def _mf_field(name: str) -> str:
    return (
        f"          - name: {name}\n"
        "            expression:\n"
        "              dialects:\n"
        "                - dialect: ANSI_SQL\n"
        f"                  expression: {name}\n"
    )


def _mf_dataset(name: str, *fields: str) -> str:
    return (
        f"      - name: {name}\n"
        f"        source: demo.main.{name}\n"
        f"        primary_key: [{fields[0]}]\n"
        "        fields:\n" + "".join(_mf_field(f) for f in fields)
    )


def _mf_edge(name: str, frm: str, to: str, field: str) -> str:
    return (
        f"      - name: {name}\n"
        "        cardinality: many_to_one\n"
        f"        from_dataset: {frm}\n"
        f"        from_fields: [{field}]\n"
        f"        to_dataset: {to}\n"
        f"        to_fields: [{field}]\n"
    )


def _four_fact_staging(root: Path, relationships: str) -> Path:
    """Four fact datasets sharing a join field — topology only varies by edges."""
    model = (
        "version: 0.2.0.dev0\n"
        "semantic_model:\n"
        "  - name: topology\n"
        "    datasets:\n"
        + _mf_dataset("alpha", "alpha_id", "node_id")
        + _mf_dataset("beta", "beta_id", "node_id")
        + _mf_dataset("gamma", "gamma_id", "node_id")
        + _mf_dataset("delta", "delta_id", "node_id")
        + "    relationships:\n"
        + relationships
        + "    metrics:\n"
        "      - name: alpha_count\n"
        "        dataset: alpha\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: COUNT(*)\n"
    )
    return _staging(root, {"topology.yml": model})


def test_f4_relationship_topology_cycle_and_diamond_fail(tmp_path):
    # F4: individually well-formed edges must still form a bounded, acyclic,
    # unambiguous join graph (spec rev 1 §3) — a reverse edge (cycle) and a
    # diamond (two paths alpha->delta) are both rejected.
    cycle = _four_fact_staging(
        tmp_path / "cycle",
        _mf_edge("a_to_b", "alpha", "beta", "node_id")
        + _mf_edge("b_to_a", "beta", "alpha", "node_id"),
    )
    with pytest.raises(GraphError, match="cycle"):
        load_graph(cycle / "semantic_layer")

    diamond = _four_fact_staging(
        tmp_path / "diamond",
        _mf_edge("a_to_b", "alpha", "beta", "node_id")
        + _mf_edge("a_to_c", "alpha", "gamma", "node_id")
        + _mf_edge("b_to_d", "beta", "delta", "node_id")
        + _mf_edge("c_to_d", "gamma", "delta", "node_id"),
    )
    with pytest.raises(GraphError, match="ambiguous"):
        load_graph(diamond / "semantic_layer")

    chain = _four_fact_staging(
        tmp_path / "chain",
        _mf_edge("a_to_b", "alpha", "beta", "node_id")
        + _mf_edge("b_to_c", "beta", "gamma", "node_id")
        + _mf_edge("c_to_d", "gamma", "delta", "node_id"),
    )
    load_graph(chain / "semantic_layer")  # one bounded path per pair: fine


def test_f5_conformed_value_type_compatibility(tmp_path):
    # F5: only the boolean time role was compared — conformed members with
    # CONTRADICTING value-type evidence (LENGTH(region) is numeric vs
    # UPPER(region) text) must fail; absent evidence is disclosed, never
    # silently treated as established compatibility.
    mismatch = DOMAIN_YML.replace("expression: region", "expression: LENGTH(region)", 1).replace(
        "expression: region", "expression: UPPER(region)", 1
    )
    staging = _staging(tmp_path / "st", {"sales.yml": mismatch})
    with pytest.raises(GraphError, match="incompatible value types"):
        load_graph(staging / "semantic_layer")

    # no type evidence (bare source columns): accepted, but disclosed as
    # unverified rather than reported as a passed compatibility check
    bare = _domain_staging(tmp_path / "bare")
    result = validate(bare)
    assert result.ok, result.errors
    report = result.report
    assert report is not None
    assert report.outcome("conformance") == "not-run"
    conformance = next(c for c in report.checks if c.name == "conformance")
    assert "unverified" in conformance.detail and "region" in conformance.detail

    agreeing = _staging(
        tmp_path / "agree",
        {"sales.yml": DOMAIN_YML.replace("expression: region", "expression: UPPER(region)")},
    )
    result = validate(agreeing)
    assert result.ok, result.errors
    assert result.report is not None
    assert result.report.outcome("conformance") == "passed"


def test_f6_unassigned_dataset_structure_still_validated(tmp_path):
    # F6: order_lines carries no metrics (reachable only via relationship +
    # conformance) — its unparsable field expression must still fail validate
    # instead of bypassing every schema/render check.
    bad = DOMAIN_YML.replace(
        "      - name: lines_total\n"
        "        dataset: order_lines\n"
        "        description: Sum of line amounts at line grain\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: SUM(line_amount)\n",
        "",
    ).replace("expression: line_amount", "expression: SUM(((")
    staging = _staging(tmp_path / "st", {"sales.yml": bad})
    result = validate(staging)
    assert not result.ok
    assert any("line_amount" in error for error in result.errors)


def test_f7_compile_failures_get_a_truthful_compile_outcome(tmp_path):
    # F7: a render failure (field reference cycle region -> amount -> region)
    # extended the error list while the report stayed structurally 'passed' —
    # schema/compile failures need their own truthful outcome with diagnostics.
    bad = DOMAIN_YML.replace(
        "                  expression: region\n            dimension: {}\n          - name: amount",
        "                  expression: amount\n            dimension: {}\n          - name: amount",
    ).replace(
        "                  expression: amount\n      - name: order_lines",
        "                  expression: region\n      - name: order_lines",
    )
    staging = _staging(tmp_path / "st", {"sales.yml": bad})
    result = validate(staging)
    assert not result.ok
    assert any("cycle" in error for error in result.errors)
    report = result.report
    assert report is not None
    assert report.outcome("compile") == "failed"
    compile_check = next(c for c in report.checks if c.name == "compile")
    assert "cycle" in compile_check.detail


def test_f7_compile_pass_is_scoped_when_derived_definitions_are_skipped(tmp_path):
    # Recheck finding 1: a graph with a skipped cross-fact derived metric must
    # not report a bare passed compile outcome — the compile outcome itself
    # exposes what was and was not compiled (task 2 owns derived compilation).
    with_ratio = DOMAIN_YML + (
        "      - name: order_line_ratio\n"
        "        description: Derived ratio across both facts\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: orders_total / lines_total\n"
    )
    staging = _staging(tmp_path / "st", {"sales.yml": with_ratio})
    result = validate(staging)
    assert result.ok, result.errors
    report = result.report
    assert report is not None
    compile_check = next(c for c in report.checks if c.name == "compile")
    assert compile_check.outcome == "passed"
    assert "order_line_ratio" in compile_check.detail
    assert "not compiled" in compile_check.detail


def test_f8_empty_model_inventory_refused(tmp_path):
    # F8: an empty semantic_layer/models tree loaded as an empty graph and
    # validated ok — the former validator refused an empty inventory.
    staging = tmp_path / "st"
    (staging / "semantic_layer" / "models").mkdir(parents=True)
    with pytest.raises(GraphError, match="no semantic models"):
        load_graph(staging / "semantic_layer")
    result = validate(staging)
    assert not result.ok
    assert result.report is not None
    assert result.report.outcome("structural") == "failed"


def test_f9_report_refused_when_files_change_during_validation(tmp_path, monkeypatch):
    # F9: the digest hashed at report-build time, AFTER the grain audit reread
    # the models — a concurrent edit yielded a digest attesting unchecked
    # bytes. Bytes are captured at first read; drift refuses the report.
    registry = build_source_fixture(tmp_path / "src")
    staging = _domain_staging(tmp_path / "domain")
    model = staging / "semantic_layer" / "models" / "sales.yml"

    def edit_mid_audit(staging_dir, con):
        model.write_text(
            model.read_text(encoding="utf-8") + "\n# concurrent edit\n", encoding="utf-8"
        )
        return []

    monkeypatch.setattr("ariadne.validate._grain_audit", edit_mid_audit)
    result = validate(staging, sources_path=registry)
    assert not result.ok
    assert any("changed during validation" in error for error in result.errors)
    assert result.report is None  # no digest may attest the unchecked bytes


def test_f10_malformed_collections_raise_grapherror_not_typeerror(tmp_path):
    # F10: 'relationships: 42', 'to_dataset: []' and a conformed member with a
    # non-string dataset all raised bare TypeErrors — the public load_graph()
    # seam must raise GraphError for malformed declarations.
    not_a_list = DOMAIN_YML.replace(
        "    relationships:\n"
        "      - name: line_to_order\n"
        "        cardinality: many_to_one\n"
        "        from_dataset: order_lines\n"
        "        from_fields: [order_id]\n"
        "        to_dataset: orders\n"
        "        to_fields: [order_id]\n",
        "    relationships: 42\n",
    )
    staging = _staging(tmp_path / "a", {"sales.yml": not_a_list})
    with pytest.raises(GraphError, match="relationships"):
        load_graph(staging / "semantic_layer")

    unhashable_target = DOMAIN_YML.replace(
        "        to_dataset: orders\n", "        to_dataset: []\n"
    )
    staging = _staging(tmp_path / "b", {"sales.yml": unhashable_target})
    with pytest.raises(GraphError, match="to_dataset"):
        load_graph(staging / "semantic_layer")

    bad_member = DOMAIN_YML.replace(
        "          - dataset: orders\n            field: region\n",
        "          - dataset: []\n            field: region\n",
    )
    staging = _staging(tmp_path / "c", {"sales.yml": bad_member})
    with pytest.raises(GraphError, match="member"):
        load_graph(staging / "semantic_layer")

    # recheck finding 2: a list-valued field name passed the truthiness guard
    # and hit the F5 evidence index with an unhashable key — same contract.
    list_name = DOMAIN_YML.replace(
        "          - name: order_id\n", "          - name: [order_id]\n", 1
    )
    staging = _staging(tmp_path / "d", {"sales.yml": list_name})
    with pytest.raises(GraphError, match="field name"):
        load_graph(staging / "semantic_layer")


def test_compile_only_scope_is_visibly_partial(tmp_path):
    staging = _domain_staging(tmp_path / "domain")
    result = validate(staging)  # no --db/--sources: compile-only
    assert result.ok, result.errors
    report = result.report
    assert report is not None
    assert "compile-only" in report.scope
    assert report.outcome("structural") == "passed"
    assert report.outcome("bind") == "not-run"
    assert report.outcome("grain") == "not-run"
    # a compile-only report never claims a live relationship audit (issue #27:
    # the outcome becomes real only where the audit actually runs)
    assert report.outcome("relationship_audit") == "not-run"
    assert report.registry_digest is None  # no source identity is bound


# --- Task 2 (issue #27): aggregate fact branches before alignment ------------


def _duck_connection(registry: Path):
    """The configured DuckDB session over the registered source fixture."""
    con, _catalog = build_connection(load_registry(registry))
    return con


def test_plan_query_aggregates_fact_branches_before_alignment(tmp_path):
    # The fan-out trap (spec rev 1 acceptance 1). Expected values derived by
    # hand from the fixture rows, never from the implementation: NA orders
    # 100 + 200 = 300 with lines 60+30+10+150+50 = 300; EMEA 400 / 400. The
    # naive orders-join-lines aggregation would inflate NA orders to 700
    # (order 1 fanned x3, order 2 x2) and must never be emitted.
    registry = build_source_fixture(tmp_path / "src")
    graph = load_graph(_domain_staging(tmp_path / "domain") / "semantic_layer")
    con = _duck_connection(registry)

    plan = plan_query(
        graph, {"metrics": ["orders_total", "lines_total"], "dimensions": ["region"]}, con
    )

    assert plan.metrics == ("orders_total", "lines_total")
    assert plan.dimensions == ("region",)
    assert sorted(branch.dataset for branch in plan.branches) == ["order_lines", "orders"]
    assert plan.conformed_keys == ("region",)
    rows = {region: (total, lines) for region, total, lines in con.execute(plan.sql).fetchall()}
    assert rows == {"NA": (300.0, 300.0), "EMEA": (400.0, 400.0)}

    # ONE guarded SELECT: a single statement whose only joins are the null-safe
    # LEFT JOINs of aligned aggregate branches — never a raw fact-to-fact join.
    statements = sqlglot.parse(plan.sql)
    assert len(statements) == 1
    assert statements[0] is not None
    joins = list(statements[0].find_all(exp.Join))
    assert joins, "expected branch-alignment joins over aggregate CTEs"
    assert all(join.side == "LEFT" for join in joins)

    # no dimensions: one aggregate row (hand-derived 300+400=700 each fact)
    totals = plan_query(graph, {"metrics": ["orders_total", "lines_total"]}, con)
    assert con.execute(totals.sql).fetchall() == [(700.0, 700.0)]

    # a compile-only plan (no connection) performs no live relationship audit
    compile_only = plan_query(graph, {"metrics": ["orders_total"], "dimensions": ["region"]})
    assert compile_only.relationship_audit == "not-run"


# Three-fact alignment fixture (spec rev 1 acceptance 2): shipments carries an
# otherwise-unmatched APAC group and a NULL-key group alongside orders/lines.
SHIPMENTS_DATASET = """\
      - name: shipments
        source: demo.main.shipments
        primary_key: [shipment_id]
        fields:
          - name: shipment_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: shipment_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: shipped_qty
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: shipped_qty
"""
SHIPMENT_METRICS = """\
      - name: shipment_count
        dataset: shipments
        description: Count of shipments at shipment grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
      - name: shipped_total
        dataset: shipments
        description: Sum of shipped quantities at shipment grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(shipped_qty)
"""
ALIGN_YML = (
    DOMAIN_YML.replace("    relationships:", SHIPMENTS_DATASET + "    relationships:").replace(
        "          - dataset: order_lines\n            field: region\n",
        "          - dataset: order_lines\n            field: region\n"
        "          - dataset: shipments\n            field: region\n",
    )
    + SHIPMENT_METRICS
)

# Mutable-lookup drift fixture (spec rev 1 acceptance 3): owners has no sqlite
# PK, so its owner_id target key can drift under the live connection.
DRIFT_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: ops
    description: Mutable-lookup drift fixture (spec rev 1 acceptance 3)
    datasets:
      - name: events
        source: demo.main.events
        primary_key: [event_id]
        fields:
          - name: event_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: event_id
          - name: owner_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: owner_id
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
      - name: owners
        source: demo.main.owners
        primary_key: [owner_id]
        fields:
          - name: owner_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: owner_id
          - name: owner_name
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: owner_name
            dimension: {}
    relationships:
      - name: event_owner
        cardinality: many_to_one
        from_dataset: events
        from_fields: [owner_id]
        to_dataset: owners
        to_fields: [owner_id]
    metrics:
      - name: events_total
        dataset: events
        description: Sum of event amounts at event grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
"""


def test_plan_query_alignment_preserves_unmatched_and_null_groups(tmp_path):
    # Hand-derived from the fixture rows: shipments APAC 5+7=12 over 2 rows and
    # NULL 9 over 1 row; orders/lines have no APAC or NULL group, so their SUMs
    # read NULL there while the bare COUNTs read 0; NA/EMEA keep 300/300 and
    # 400/400. The unmatched and NULL groups each appear exactly once.
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "align", {"sales.yml": ALIGN_YML})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(
        graph,
        {
            "metrics": [
                "orders_total",
                "order_count",
                "lines_total",
                "shipment_count",
                "shipped_total",
            ],
            "dimensions": ["region"],
        },
        con,
    )
    rows = {region: tuple(values) for region, *values in con.execute(plan.sql).fetchall()}
    assert rows["NA"] == (300.0, 2, 300.0, 0, None)  # missing COUNT 0, missing SUM NULL
    assert rows["EMEA"] == (400.0, 1, 400.0, 0, None)
    assert rows["APAC"] == (None, 0, None, 2, 12.0)  # unmatched group, once
    assert rows[None] == (None, 0, None, 1, 9.0)  # NULL-key group, once
    assert len(rows) == 4


def test_plan_query_rechecks_relationship_keys_on_each_request(tmp_path):
    # The first request plans (owner_name reached through the proven
    # event_owner many_to_one path; hand-derived ada 3+4=7, bob 5). A newly
    # duplicate joined-side key refuses the NEXT query before any result
    # SELECT; a NULL key component refuses likewise (per-request recheck).
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "drift", {"ops.yml": DRIFT_YML})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    request = {"metrics": ["events_total"], "dimensions": ["owner_name"]}
    plan = plan_query(graph, request, con)
    assert plan.relationship_audit == "passed"
    (branch,) = plan.branches
    assert branch.dataset == "events"
    assert branch.joins == ("event_owner",)
    assert dict(con.execute(plan.sql).fetchall()) == {"ada": 7.0, "bob": 5.0}

    db = tmp_path / "src" / "mf.db"
    with sqlite3.connect(db) as source:
        source.execute("INSERT INTO owners VALUES (10, 'ada2')")  # duplicate target key
        source.commit()
    with pytest.raises(PlannerError) as duplicate:
        plan_query(graph, request, con)
    assert duplicate.value.code == "relationship_key_duplicate"
    assert "event_owner" in str(duplicate.value)

    with sqlite3.connect(db) as source:
        source.execute("DELETE FROM owners WHERE owner_name = 'ada2'")
        source.execute("INSERT INTO owners VALUES (NULL, 'nil')")  # NULL key component
        source.commit()
    with pytest.raises(PlannerError) as null_key:
        plan_query(graph, request, con)
    assert null_key.value.code == "relationship_key_null"


def test_plan_query_refusals_are_structured(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    graph = load_graph(_domain_staging(tmp_path / "domain") / "semantic_layer")
    con = _duck_connection(registry)

    with pytest.raises(PlannerError) as unknown_metric:
        plan_query(graph, {"metrics": ["revenue"]}, con)
    assert unknown_metric.value.code == "unknown_metric"
    assert "orders_total" in unknown_metric.value.candidates

    with pytest.raises(PlannerError) as unknown_dimension:
        plan_query(graph, {"metrics": ["orders_total"], "dimensions": ["planet"]}, con)
    assert unknown_dimension.value.code == "unknown_dimension"
    assert "region" in unknown_dimension.value.candidates

    # no silent narrowing of the request shape itself
    with pytest.raises(PlannerError) as bad_request:
        plan_query(graph, {"metrics": ["orders_total"], "where": "1=1"}, con)
    assert bad_request.value.code == "request_invalid"

    # cross-fact derived metrics compute after branch alignment (task 4, #29):
    # the ratio resolves over the aligned outputs — hand-derived 700 / 700
    with_ratio = DOMAIN_YML + (
        "      - name: order_line_ratio\n"
        "        description: Derived ratio across both facts\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: orders_total / lines_total\n"
    )
    ratio_graph = load_graph(
        _staging(tmp_path / "ratio", {"sales.yml": with_ratio}) / "semantic_layer"
    )
    ratio = plan_query(ratio_graph, {"metrics": ["order_line_ratio"]}, con)
    assert con.execute(ratio.sql).fetchall() == [(1.0,)]


# --- Fix pass (review c90ca081): the five accepted findings F1–F5 ------------

# F1 (P0): a model-authored relationship target field name is graph-validated
# only as a nonempty string, so a quote-bearing name must never be interpolated
# into the audit statement as raw text (the review's repro payload, executed by
# the parent through a plain duckdb connection).
INJECTED_FIELD = (
    'owner_id")) FROM (SELECT 1 AS owner_id) x; '
    "CREATE TABLE audit_injected AS SELECT 42 AS marker; SELECT 1,1,0; --"
)


def test_f1_quote_bearing_target_key_cannot_execute_statements(tmp_path):
    # The audit seam itself: with correct identifier quoting the payload becomes
    # one quoted identifier naming no physical column — fail closed, and NOTHING
    # executes besides the one audit SELECT (no created table, ever).
    con = duckdb.connect()
    con.execute("CREATE TABLE owners AS SELECT 1 AS owner_id, 'ada' AS owner_name")
    with pytest.raises(ValueError):  # fail closed: the payload cannot become a statement
        relationship_target_audit(con, "owners", (INJECTED_FIELD,))
    tables = con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
    assert ("audit_injected",) not in tables  # no side effects, ever


def test_f1_planner_refuses_quote_bearing_target_field_structured(tmp_path):
    # The validation path: a target field whose name carries the payload and
    # whose declaration carries no usable expression cannot be lowered to a
    # physical key, so the request is refused BEFORE any audit or result
    # SELECT — and nothing executes besides the planner's own statements.
    registry = build_source_fixture(tmp_path / "src")
    owners_key = (
        "      - name: owners\n"
        "        source: demo.main.owners\n"
        "        primary_key: [owner_id]\n"
        "        fields:\n"
        "          - name: owner_id\n"
        "            expression:\n"
        "              dialects:\n"
        "                - dialect: ANSI_SQL\n"
        "                  expression: owner_id\n"
    )
    evil = DRIFT_YML.replace(
        owners_key,
        "      - name: owners\n"
        "        source: demo.main.owners\n"
        "        primary_key: [owner_id]\n"
        "        fields:\n"
        f"          - name: {INJECTED_FIELD!r}\n",
    ).replace("        to_fields: [owner_id]\n", f"        to_fields: [{INJECTED_FIELD!r}]\n")
    assert evil != DRIFT_YML
    graph = load_graph(_staging(tmp_path / "evil", {"ops.yml": evil}) / "semantic_layer")
    con = _duck_connection(registry)
    with pytest.raises(PlannerError) as refused:
        plan_query(graph, {"metrics": ["events_total"], "dimensions": ["owner_name"]}, con)
    assert refused.value.code == "compile_failed"
    tables = con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
    assert not any("audit_injected" in name for (name,) in tables)  # no side effects, ever


# F2: composite lookup whose target-key tuples are unique while the COMPONENTS
# repeat — the exact tuple audit accepts it, so the legacy per-column guard must
# not be applied to the planner's generated relationship joins (only authored
# sources embed pre-joined tables). Hand-derived: alpha 3, beta 4, gamma 5.
COMPOSITE_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: workload
    description: Composite-key lookup fixture (fix pass F2)
    datasets:
      - name: tasks
        source: demo.main.tasks
        primary_key: [task_id]
        fields:
          - name: task_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: task_id
          - name: team_a
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: team_a
          - name: team_b
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: team_b
          - name: hours
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: hours
      - name: teams
        source: demo.main.teams
        primary_key: [team_a, team_b]
        fields:
          - name: team_a
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: team_a
          - name: team_b
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: team_b
          - name: team_name
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: team_name
            dimension: {}
    relationships:
      - name: task_team
        cardinality: many_to_one
        from_dataset: tasks
        from_fields: [team_a, team_b]
        to_dataset: teams
        to_fields: [team_a, team_b]
    metrics:
      - name: task_hours
        dataset: tasks
        description: Sum of task hours at task grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(hours)
"""


def test_f2_valid_composite_relationship_key_plans_and_executes(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "composite", {"workload.yml": COMPOSITE_YML})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(graph, {"metrics": ["task_hours"], "dimensions": ["team_name"]}, con)
    assert plan.relationship_audit == "passed"
    assert dict(con.execute(plan.sql).fetchall()) == {"alpha": 3.0, "beta": 4.0, "gamma": 5.0}


# F3(a): a metric that scopes a shared column to its declared dataset — both
# branch sources expose owner_id, so an unqualified COUNT(DISTINCT owner_id)
# cannot bind. Hand-derived: ada 2 events, bob 1.
SCOPED_METRIC = """\
      - name: owner_events
        dataset: events
        description: Distinct event owners per group, scoped to events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(DISTINCT events.owner_id)
"""

# F3(b): a relationship target field whose name differs from the physical key
# column it declares (owner_key -> expression owner_id) — joins and audits must
# use the declared expression, not the alias as a physical column.
ALIASED_YML = DRIFT_YML.replace(
    "      - name: owners\n"
    "        source: demo.main.owners\n"
    "        primary_key: [owner_id]\n"
    "        fields:\n"
    "          - name: owner_id\n",
    "      - name: owners\n"
    "        source: demo.main.owners\n"
    "        primary_key: [owner_id]\n"
    "        fields:\n"
    "          - name: owner_key\n"
    "            expression:\n"
    "              dialects:\n"
    "                - dialect: ANSI_SQL\n"
    "                  expression: owner_id\n"
    "          - name: owner_id\n",
).replace("        to_fields: [owner_id]\n", "        to_fields: [owner_key]\n")


def test_f3_scoped_shared_column_and_aliased_key_resolve_per_dataset(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    scoped = _staging(tmp_path / "scoped", {"ops.yml": DRIFT_YML + SCOPED_METRIC})
    graph = load_graph(scoped / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(
        graph, {"metrics": ["events_total", "owner_events"], "dimensions": ["owner_name"]}, con
    )
    assert dict(map(lambda row: (row[0], (row[1], row[2])), con.execute(plan.sql).fetchall())) == {
        "ada": (7.0, 1),
        "bob": (5.0, 1),
    }

    aliased = _staging(tmp_path / "aliased", {"ops.yml": ALIASED_YML})
    graph = load_graph(aliased / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(graph, {"metrics": ["events_total"], "dimensions": ["owner_name"]}, con)
    assert plan.relationship_audit == "passed"
    assert dict(con.execute(plan.sql).fetchall()) == {"ada": 7.0, "bob": 5.0}
    # the admission-time audit resolves the same declared key expression
    result = validate(aliased, sources_path=registry)
    assert result.ok, result.errors
    assert result.report is not None
    assert result.report.outcome("relationship_audit") == "passed"


def test_f3_audit_and_join_share_one_resolved_target_key(tmp_path):
    # Delta-recheck surviving finding (runtime-confirmed by the parent): the
    # audit resolved only ONE level of field substitution while join lowering
    # resolves recursively — the audit proved uniqueness of the DECLARED key
    # (owner_ref + 0 → 10,20) while the join used the RESOLVED key
    # (owner_id % 10 + 0 → 0,0) and fanned every event across both owners
    # (ada/bob 12.0 instead of 7.0/5.0). One shared resolution must refuse.
    registry = build_source_fixture(tmp_path / "src")
    doc = yaml.safe_load(DRIFT_YML)
    model = doc["semantic_model"][0]
    datasets = {d["name"]: d for d in model["datasets"]}
    datasets["events"]["fields"].append(
        {
            "name": "owner_match",
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": "owner_id % 10"}]},
        }
    )
    datasets["owners"]["source"] = (
        "SELECT owner_id, owner_id AS owner_ref, owner_name FROM demo.main.owners"
    )
    datasets["owners"]["fields"] += [
        {
            "name": "owner_ref",
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": "owner_id % 10"}]},
        },
        {
            "name": "owner_key",
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": "owner_ref + 0"}]},
        },
    ]
    relationship = model["relationships"][0]
    relationship["from_fields"] = ["owner_match"]
    relationship["to_fields"] = ["owner_key"]
    staging = _staging(tmp_path / "split", {"split.yml": yaml.safe_dump(doc, sort_keys=False)})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    with pytest.raises(PlannerError, match="is not unique") as refusal:
        plan_query(graph, {"metrics": ["events_total"], "dimensions": ["owner_name"]}, con)
    assert refusal.value.code == "relationship_key_duplicate"


# F4: the conformed key 'region' maps to a differently named native member
# (order_lines.sales_region) on the branch that ALSO traverses a lookup for
# another dimension — the joined branch must expose the key under the name the
# alignment references, for both branch kinds. Hand-derived per order: NA/100,
# NA/200, EMEA/400 with equal order and line sums.
CONFORMED_ALIAS_YML = DOMAIN_YML.replace(
    "          - name: region\n"
    "            expression:\n"
    "              dialects:\n"
    "                - dialect: ANSI_SQL\n"
    "                  expression: region\n"
    "            dimension: {}\n"
    "          - name: line_amount\n",
    "          - name: sales_region\n"
    "            expression:\n"
    "              dialects:\n"
    "                - dialect: ANSI_SQL\n"
    "                  expression: region\n"
    "            dimension: {}\n"
    "          - name: line_amount\n",
).replace(
    "          - dataset: order_lines\n            field: region\n",
    "          - dataset: order_lines\n            field: sales_region\n",
)


def test_f4_conformed_key_aligns_with_lookup_dimensions(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "conformed", {"sales.yml": CONFORMED_ALIAS_YML})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(
        graph,
        {"metrics": ["orders_total", "lines_total"], "dimensions": ["region", "amount"]},
        con,
    )
    executed = con.execute(plan.sql).fetchall()
    rows = {(region, amount): (total, lines) for region, amount, total, lines in executed}
    assert rows == {
        ("NA", 100.0): (100.0, 100.0),
        ("NA", 200.0): (200.0, 200.0),
        ("EMEA", 400.0): (400.0, 400.0),
    }


# F5: a base metric requested together with a same-fact derived metric built on
# it — the branch must expose BOTH outputs (total 700, double 1400).
DERIVED_YML = (
    DOMAIN_YML
    + """\
      - name: double_total
        description: Derived twice the orders total (same fact)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total * 2
"""
)


def test_f5_base_and_same_fact_derived_metric_both_return(tmp_path):
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "derived", {"sales.yml": DERIVED_YML})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(graph, {"metrics": ["orders_total", "double_total"]}, con)
    assert con.execute(plan.sql).fetchall() == [(700.0, 1400.0)]
    # each metric alone keeps its own single-output shape
    alone = plan_query(graph, {"metrics": ["double_total"]}, con)
    assert con.execute(alone.sql).fetchall() == [(1400.0,)]


# --- Task 3 (issue #28): scoped filters, parameters, segments, detail -------

# Task 3 fixture model: customers adds the orders -> customers lookup so `tier`
# is a TWO-hop dimension from the order_lines branch (line_to_order ->
# order_customer) and a one-hop dimension from orders. events deliberately has
# NO member of the conformed `region` dimension — the unpaired-filter refusal.
# amount exists on orders AND events, so those metrics qualify their fields.
TASK3_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: sales_t3
    description: Task 3 fixture (two-hop lookup + fact without the conformed member)
    requires: ["ariadne.conformed_dimensions@1"]
    datasets:
      - name: customers
        source: demo.main.customers
        primary_key: [customer_id]
        fields:
          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: customer_id
          - name: tier
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: tier
            dimension: {}
      - name: orders
        source: demo.main.orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: customer_id
      - name: order_lines
        source: demo.main.order_lines
        primary_key: [line_id]
        fields:
          - name: line_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_id
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
      - name: events
        source: demo.main.events
        primary_key: [event_id]
        fields:
          - name: event_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: event_id
          - name: owner_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: owner_id
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    relationships:
      - name: line_to_order
        cardinality: many_to_one
        from_dataset: order_lines
        from_fields: [order_id]
        to_dataset: orders
        to_fields: [order_id]
      - name: order_customer
        cardinality: many_to_one
        from_dataset: orders
        from_fields: [customer_id]
        to_dataset: customers
        to_fields: [customer_id]
    conformed_dimensions:
      - name: region
        members:
          - dataset: orders
            field: region
          - dataset: order_lines
            field: region
    metrics:
      - name: orders_total
        dataset: orders
        description: Sum of order amounts at order grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(orders.amount)
      - name: lines_total
        dataset: order_lines
        description: Sum of line amounts at line grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
      - name: events_total
        dataset: events
        description: Sum of event amounts at event grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(events.amount)
"""


def _t3_graph(root: Path):
    """The task 3 graph over the registered source fixture."""
    registry = build_source_fixture(root / "src")
    staging = _staging(root / "t3", {"sales_t3.yml": TASK3_YML})
    return load_graph(staging / "semantic_layer"), _duck_connection(registry)


# mf-t3 review F2: an orders field whose declared expression is an AGGREGATE —
# accepted by graph validation while unused, but projecting it in detail would
# collapse the root grain to one row (spec rev 1, acceptance 5).
AGG_FIELD_YML = TASK3_YML.replace(
    """          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: customer_id
      - name: order_lines
""",
    """          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: customer_id
          - name: collapsed
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: SUM(amount)
      - name: order_lines
""",
)


def _agg_field_graph(root: Path):
    """The task 3 graph plus the aggregate declared field on orders."""
    registry = build_source_fixture(root / "src")
    staging = _staging(root / "t3agg", {"sales_agg.yml": AGG_FIELD_YML})
    return load_graph(staging / "semantic_layer"), _duck_connection(registry)


def test_t3_two_hop_dimension_and_typed_segment_filter_both_facts(tmp_path):
    # Hand-derived from the fixture rows: gold is customer 1 (orders 1 NA/100
    # and 3 EMEA/400; their lines 60+30+10 and 400); standard is customer 2
    # (order 2 NA/200; its lines 150+50). `tier` is a customers field — ONE hop
    # from the orders branch, TWO hops from the lines branch — and the named
    # segment's typed parameter narrows BOTH branch populations independently.
    graph, con = _t3_graph(tmp_path)
    request = {
        "metrics": ["orders_total", "lines_total"],
        "dimensions": ["tier"],
        "segments": [
            {
                "name": "gold_tier",
                "filters": [{"field": "tier", "op": "=", "value": {"param": "tier"}}],
            }
        ],
        "parameters": {"tier": {"type": "string", "value": "gold", "max_length": 16}},
    }
    plan = plan_query(graph, request, con)
    rows = {tier: (total, lines) for tier, total, lines in con.execute(plan.sql).fetchall()}
    assert rows == {"gold": (500.0, 500.0)}  # the segment narrows BOTH facts to gold

    # each branch traversed its OWN lookup chain for the same dimension and
    # routed the segment predicate (bounded lineage)
    joins = {branch.dataset: branch.joins for branch in plan.branches}
    assert joins["orders"] == ("order_customer",)
    assert joins["order_lines"] == ("line_to_order", "order_customer")
    routed = {branch.dataset: branch.filters for branch in plan.branches}
    assert routed == {"orders": ("tier",), "order_lines": ("tier",)}

    # the typed parameter drives the population: swapping it swaps the result
    swapped = plan_query(
        graph,
        {**request, "parameters": {"tier": {"type": "string", "value": "standard"}}},
        con,
    )
    assert con.execute(swapped.sql).fetchall() == [("standard", 200.0, 200.0)]


def test_t3_unpaired_filter_refuses_before_execution(tmp_path):
    # events has no member of the conformed `region` dimension: a row filter on
    # region in a request spanning orders + events is UNPAIRED — it must refuse
    # before any result SELECT instead of silently narrowing one fact (spec rev
    # 1 "Query and result contract"; acceptance 2).
    graph, con = _t3_graph(tmp_path)
    with pytest.raises(PlannerError) as refused:
        plan_query(
            graph,
            {
                "metrics": ["orders_total", "events_total"],
                "filters": [{"field": "region", "op": "=", "value": "NA"}],
            },
            con,
        )
    assert refused.value.code == "unpaired_filter"
    assert "region" in str(refused.value)


def test_t3_child_side_detail_traversal_refuses_before_execution(tmp_path):
    # line_amount lives on order_lines — the CHILD side of line_to_order. A
    # detail rooted at orders that projected it would multiply the root grain;
    # the traversal refuses before execution (spec rev 1, acceptance 5).
    from ariadne.planner import plan_detail  # lazy import: the task 3 seam

    graph, con = _t3_graph(tmp_path)
    with pytest.raises(PlannerError) as refused:
        plan_detail(graph, {"dataset": "orders", "fields": ["line_amount"]}, con)
    assert refused.value.code == "detail_child_side"
    assert "line_to_order" in str(refused.value)


def test_t3_filter_values_cannot_inject_sql(tmp_path):
    # Typed binding: a filter value (direct or parameter) becomes ONE quoted
    # string literal in the AST — quotes double, nothing concatenates — so a
    # payload naming a second statement can neither execute nor broaden the
    # predicate (completion criterion: predicates cannot smuggle a statement).
    graph, con = _t3_graph(tmp_path)
    payload = "gold' OR '1'='1; DROP TABLE customers; --"
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total"],
            "dimensions": ["region"],
            "filters": [{"field": "tier", "op": "=", "value": payload}],
        },
        con,
    )
    assert len(sqlglot.parse(plan.sql)) == 1
    assert "'gold'' OR ''1''=''1; DROP TABLE customers; --'" in plan.sql
    assert con.execute(plan.sql).fetchall() == []  # no tier equals the payload
    assert con.execute("SELECT COUNT(*) FROM demo.main.customers").fetchone() == (2,)

    parameterized = plan_query(
        graph,
        {
            "metrics": ["orders_total"],
            "dimensions": ["region"],
            "filters": [{"field": "tier", "op": "=", "value": {"param": "tier"}}],
            "parameters": {"tier": {"type": "string", "value": payload, "max_length": 128}},
        },
        con,
    )
    assert len(sqlglot.parse(parameterized.sql)) == 1
    assert "'gold'' OR ''1''=''1; DROP TABLE customers; --'" in parameterized.sql
    assert con.execute(parameterized.sql).fetchall() == []
    assert con.execute("SELECT COUNT(*) FROM demo.main.customers").fetchone() == (2,)


def test_t3_result_filter_orders_and_limits_after_grouping(tmp_path):
    # Aggregate/result filters run AFTER grouping on the aligned output, then
    # declared ordering and the bounded limit. Hand-derived: NA 300/300,
    # EMEA 400/400 — orders_total > 300 keeps only EMEA; ordering by
    # orders_total desc with limit 1 keeps the EMEA row.
    graph, con = _t3_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total", "lines_total"],
            "dimensions": ["region"],
            "filters": [{"field": "orders_total", "op": ">", "value": 300}],
            "order": [{"field": "orders_total", "direction": "desc"}],
            "limit": 1,
        },
        con,
    )
    assert plan.segments == ()
    assert con.execute(plan.sql).fetchall() == [("EMEA", 400.0, 400.0)]

    # ordering and limiting WITHOUT a result filter: both regions, EMEA first
    both = plan_query(
        graph,
        {
            "metrics": ["orders_total", "lines_total"],
            "dimensions": ["region"],
            "order": [{"field": "region"}],
            "limit": 5,
        },
        con,
    )
    assert con.execute(both.sql).fetchall() == [("EMEA", 400.0, 400.0), ("NA", 300.0, 300.0)]

    # an IN list binds as one bounded predicate: both tiers keep all orders
    # (no declared ordering: compare unordered)
    tiers = plan_query(
        graph,
        {
            "metrics": ["orders_total"],
            "dimensions": ["region"],
            "filters": [{"field": "tier", "op": "in", "value": ["gold", "standard"]}],
        },
        con,
    )
    assert sorted(con.execute(tiers.sql).fetchall()) == [("EMEA", 400.0), ("NA", 300.0)]

    # bounded limits and output-column ordering refuse structurally
    for bad_limit in (0, -1, 10001, "5"):
        with pytest.raises(PlannerError) as refused:
            plan_query(
                graph,
                {"metrics": ["orders_total"], "limit": bad_limit},
                con,
            )
        assert refused.value.code == "limit_invalid"
    with pytest.raises(PlannerError) as bad_order:
        plan_query(
            graph,
            {"metrics": ["orders_total"], "order": [{"field": "tier"}]},
            con,
        )
    assert bad_order.value.code == "order_invalid"
    assert "orders_total" in bad_order.value.candidates  # output columns offered


def test_t3_segment_with_metric_predicate_refuses(tmp_path):
    # F4 (mf-t3 review): named segments expand to validated ROW predicates
    # (spec rev 1 "Query and result contract"). A segment containing
    # orders_total > 300 used to route silently into the post-grouping result
    # filter and drop NA; it must refuse instead — direct result filters stay
    # supported (test_t3_result_filter_orders_and_limits_after_grouping).
    graph, con = _t3_graph(tmp_path)
    with pytest.raises(PlannerError) as refused:
        plan_query(
            graph,
            {
                "metrics": ["orders_total", "lines_total"],
                "dimensions": ["region"],
                "segments": [
                    {
                        "name": "big_orders",
                        "filters": [{"field": "orders_total", "op": ">", "value": 300}],
                    }
                ],
            },
            con,
        )
    assert refused.value.code == "filter_invalid"
    assert "big_orders" in str(refused.value)

    # the same refusal for a segment naming a declared metric NOT in the
    # request — routing it through 'add it to metrics' advice would land in
    # the same unsupported segment position
    with pytest.raises(PlannerError) as unrequested:
        plan_query(
            graph,
            {
                "metrics": ["orders_total"],
                "segments": [
                    {
                        "name": "lines_over",
                        "filters": [{"field": "lines_total", "op": ">", "value": 100}],
                    }
                ],
            },
            con,
        )
    assert unrequested.value.code == "filter_invalid"
    assert "lines_over" in str(unrequested.value)


def test_t3_parameter_refusals_are_structured(tmp_path):
    graph, con = _t3_graph(tmp_path)
    filter_on_tier = {"field": "tier", "op": "=", "value": {"param": "tier"}}

    def request(parameters):
        return {
            "metrics": ["orders_total"],
            "dimensions": ["region"],
            "filters": [filter_on_tier],
            "parameters": parameters,
        }

    # untyped, mistyped and oversized declarations refuse; a type is declared
    for parameters in (
        {"tier": "gold"},  # untyped: no declaration
        {"tier": {"value": "gold"}},  # no 'type'
        {"tier": {"type": "string", "value": "gold", "max_length": 3}},  # oversized
        {"tier": {"type": "int", "value": "gold"}},  # mistyped
        {"tier": {"type": "float", "value": 5, "min": 10}},  # below declared bound
        {"tier": {"type": "date", "value": "2026-13-40"}},  # not an ISO date
        {"tier": {"type": "string", "value": "x" * 5000}},  # over the hard ceiling
    ):
        with pytest.raises(PlannerError) as refused:
            plan_query(graph, request(parameters), con)
        assert refused.value.code == "parameter_invalid"

    # a filter referencing an undeclared parameter names it and its candidates
    with pytest.raises(PlannerError) as missing:
        plan_query(
            graph,
            {
                "metrics": ["orders_total"],
                "filters": [{"field": "tier", "op": "=", "value": {"param": "nope"}}],
                "parameters": {"tier": {"type": "string", "value": "gold"}},
            },
            con,
        )
    assert missing.value.code == "unknown_parameter"
    assert "tier" in missing.value.candidates

    # a date parameter binds as a CAST literal, not a fragment
    dated = plan_query(
        graph,
        {
            "metrics": ["orders_total"],
            "filters": [{"field": "tier", "op": "=", "value": {"param": "day"}}],
            "parameters": {"day": {"type": "date", "value": "2026-09-30"}},
        },
        con,
    )
    assert "CAST('2026-09-30' AS DATE)" in dated.sql


def test_t3_malformed_discriminators_refuse_structured(tmp_path):
    # F3 (mf-t3 review): malformed JSON discriminators — "op": [], "type": []
    # — reach hash-based membership checks and raised raw TypeError. They are
    # user/model-supplied values and must surface as the SAME structured
    # refusal codes as any other invalid filter/parameter (spec rev 1
    # "Failure and compatibility behavior": error codes are stable API).
    graph, con = _t3_graph(tmp_path)
    with pytest.raises(PlannerError) as bad_op:
        plan_query(
            graph,
            {
                "metrics": ["orders_total"],
                "filters": [{"field": "region", "op": [], "value": "NA"}],
            },
            con,
        )
    assert bad_op.value.code == "filter_invalid"
    assert "op" in str(bad_op.value)

    with pytest.raises(PlannerError) as bad_type:
        plan_query(
            graph,
            {"metrics": ["orders_total"], "parameters": {"tier": {"type": [], "value": "gold"}}},
            con,
        )
    assert bad_type.value.code == "parameter_invalid"
    assert "type" in str(bad_type.value)


def test_t3_fact_local_filter_changes_only_its_fact_population(tmp_path):
    # line_amount lives on order_lines only: the predicate routes to the LINES
    # branch alone (disclosed in its lineage) and leaves the orders population
    # untouched. Hand-derived: lines > 100 keep 150 (o2, NA) and 400 (o3, EMEA)
    # -> lines NA=150/EMEA=400 while orders keep NA=300/EMEA=400.
    graph, con = _t3_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total", "lines_total"],
            "dimensions": ["region"],
            "filters": [{"field": "line_amount", "op": ">", "value": 100}],
        },
        con,
    )
    rows = {region: (total, lines) for region, total, lines in con.execute(plan.sql).fetchall()}
    assert rows == {"NA": (300.0, 150.0), "EMEA": (400.0, 400.0)}
    routed = {branch.dataset: branch.filters for branch in plan.branches}
    assert routed == {"orders": (), "order_lines": ("line_amount",)}

    # an ambiguous filter field (amount on orders AND events in one model)
    # refuses instead of inferring equivalence from identical names
    with pytest.raises(PlannerError) as refused:
        plan_query(
            graph,
            {"metrics": ["orders_total"], "filters": [{"field": "amount", "op": ">", "value": 1}]},
            con,
        )
    assert refused.value.code == "ambiguous_filter"

    # a filter naming an unrequested metric is not a result filter
    with pytest.raises(PlannerError) as not_requested:
        plan_query(
            graph,
            {
                "metrics": ["orders_total"],
                "dimensions": ["region"],
                "filters": [{"field": "lines_total", "op": ">", "value": 100}],
            },
            con,
        )
    assert not_requested.value.code == "unknown_filter"
    assert "orders_total" in not_requested.value.candidates


def test_t3_row_filters_do_not_persist_into_subsequent_requests(tmp_path):
    # F1 (mf-t3 review): one graph, filtered request then unfiltered request —
    # the second must return BOTH regions. A row filter narrows its request's
    # branch population only; it must not overwrite the graph's dataset source
    # (spec rev 1 "Query and result contract": querying a metric must not
    # change its definition).
    graph, con = _t3_graph(tmp_path)
    filtered = plan_query(
        graph,
        {
            "metrics": ["orders_total"],
            "dimensions": ["region"],
            "filters": [{"field": "region", "op": "=", "value": "NA"}],
        },
        con,
    )
    assert con.execute(filtered.sql).fetchall() == [("NA", 300.0)]

    # the SAME graph, no filters: EMEA must be back
    plain = plan_query(graph, {"metrics": ["orders_total"], "dimensions": ["region"]}, con)
    assert sorted(con.execute(plain.sql).fetchall()) == [
        ("EMEA", 400.0),
        ("NA", 300.0),
    ]


def test_t3_detail_multi_hop_projection_preserves_root_grain(tmp_path):
    # Hand-derived: orders detail over (order_id, region, tier) is one row per
    # order with its customer's tier through the ONE-hop order_customer lookup;
    # lines detail over (line_id, tier) reaches tier through TWO hops and still
    # returns exactly one row per line — six rows, no fan-out, no aggregates.
    from ariadne.planner import plan_detail  # lazy import: the task 3 seam

    graph, con = _t3_graph(tmp_path)
    plan = plan_detail(graph, {"dataset": "orders", "fields": ["order_id", "region", "tier"]}, con)
    assert plan.relationship_audit == "passed"
    assert plan.joins == ("order_customer",)
    assert [(field.name, field.dataset, field.path) for field in plan.fields] == [
        ("order_id", "orders", ()),
        ("region", "orders", ()),
        ("tier", "customers", ("order_customer",)),
    ]
    assert sorted(con.execute(plan.sql).fetchall()) == [
        (1, "NA", "gold"),
        (2, "NA", "standard"),
        (3, "EMEA", "gold"),
    ]

    two_hop = plan_detail(graph, {"dataset": "order_lines", "fields": ["line_id", "tier"]}, con)
    assert two_hop.joins == ("line_to_order", "order_customer")
    rows = sorted(con.execute(two_hop.sql).fetchall())
    assert len(rows) == 6  # one row per root line key: the grain is preserved
    assert {line_id: tier for line_id, tier in rows} == {
        11: "gold",
        12: "gold",
        13: "gold",
        21: "standard",
        22: "standard",
        31: "gold",
    }

    # detail requests stay strict: no ad-hoc keys, no unknown datasets/fields,
    # and an ambiguous field name (customer_id on orders AND customers) refuses
    with pytest.raises(PlannerError) as bad_key:
        plan_detail(graph, {"dataset": "orders", "fields": ["order_id"], "filters": []}, con)
    assert bad_key.value.code == "request_invalid"
    with pytest.raises(PlannerError) as bad_dataset:
        plan_detail(graph, {"dataset": "nope", "fields": ["order_id"]}, con)
    assert bad_dataset.value.code == "unknown_dataset"
    with pytest.raises(PlannerError) as bad_field:
        plan_detail(graph, {"dataset": "orders", "fields": ["nope"]}, con)
    assert bad_field.value.code == "unknown_field"
    assert "order_id" in bad_field.value.candidates
    with pytest.raises(PlannerError) as ambiguous:
        plan_detail(graph, {"dataset": "customers", "fields": ["region"]}, con)
    assert ambiguous.value.code == "ambiguous_field"

    # a compile-only detail plan performs no live relationship audit
    compile_only = plan_detail(graph, {"dataset": "orders", "fields": ["tier"]})
    assert compile_only.relationship_audit == "not-run"


def test_t3_detail_aggregate_field_refuses_before_execution(tmp_path):
    # F2 (mf-t3 review): a declared field whose resolved expression aggregates
    # (collapsed = SUM(amount)) is a metric in field clothing — projecting it in
    # detail would emit an aggregate SELECT returning ONE row instead of one
    # row per root key. The refusal must come before audits/execution (spec rev
    # 1, acceptance 5: detail has no aggregates or fan-out).
    from ariadne.planner import plan_detail  # lazy import: the task 3 seam

    graph, con = _agg_field_graph(tmp_path)
    with pytest.raises(PlannerError) as refused:
        plan_detail(graph, {"dataset": "orders", "fields": ["collapsed"]}, con)
    assert refused.value.code == "detail_field_aggregate"
    assert "collapsed" in str(refused.value)

    # the aggregate smuggle refuses even mixed with safe fields, and the safe
    # projection on the same graph still works
    with pytest.raises(PlannerError) as mixed:
        plan_detail(graph, {"dataset": "orders", "fields": ["order_id", "collapsed"]}, con)
    assert mixed.value.code == "detail_field_aggregate"
    assert sorted(
        con.execute(
            plan_detail(graph, {"dataset": "orders", "fields": ["order_id"]}, con).sql
        ).fetchall()
    ) == [(1,), (2,), (3,)]


def test_t3_detail_nonaggregating_analytic_field_projects_one_row_per_key(tmp_path):
    # Recheck micro-fix finding: sqlglot types LAG/LEAD/rank-family functions
    # as AggFunc SUBCLASSES, so the blanket F2 guard refused grain-preserving
    # per-row analytics. LAG(amount) OVER (ORDER BY order_id) leaves one row
    # per root key and must project; a true aggregate window (SUM OVER) and a
    # nested aggregate (LAG(SUM(x))) must still refuse.
    import yaml

    from ariadne.planner import plan_detail

    doc = yaml.safe_load(DOMAIN_YML)
    for model in doc["semantic_model"]:
        for dataset in model["datasets"]:
            if dataset["name"] == "orders":
                dataset["fields"].append(
                    {
                        "name": "previous_amount",
                        "expression": {
                            "dialects": [
                                {
                                    "dialect": "ANSI_SQL",
                                    "expression": "LAG(amount) OVER (ORDER BY order_id)",
                                }
                            ]
                        },
                    }
                )
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "lag", {"lag.yml": yaml.safe_dump(doc, sort_keys=False)})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)

    plan = plan_detail(graph, {"dataset": "orders", "fields": ["order_id", "previous_amount"]}, con)
    # hand-derived: orders 1,2,3 carry amounts 100,200,400 → LAG yields NULL,100,200
    assert sorted(
        (row[0], row[1]) if row[1] is None else row for row in con.execute(plan.sql).fetchall()
    ) == [(1, None), (2, 100.0), (3, 200.0)]

    for index, bad in enumerate(
        (
            "SUM(amount) OVER (ORDER BY order_id)",
            "LAG(SUM(amount)) OVER (ORDER BY order_id)",
        )
    ):
        evil = yaml.safe_load(DOMAIN_YML)
        for model in evil["semantic_model"]:
            for dataset in model["datasets"]:
                if dataset["name"] == "orders":
                    dataset["fields"].append(
                        {
                            "name": "previous_amount",
                            "expression": {
                                "dialects": [{"dialect": "ANSI_SQL", "expression": bad}]
                            },
                        }
                    )
        bad_graph = load_graph(
            _staging(tmp_path / f"bad{index}", {"bad.yml": yaml.safe_dump(evil, sort_keys=False)})
            / "semantic_layer"
        )
        with pytest.raises(PlannerError) as refused:
            plan_detail(bad_graph, {"dataset": "orders", "fields": ["previous_amount"]}, con)
        assert refused.value.code == "detail_field_aggregate"


# --- Task 4 (issue #29): conformed business time + post-aggregate windows ----

# The two facts pair their DIFFERENTLY NAMED business dates explicitly through
# the declared conformed primary business time (native grains included), never
# through identical column names. lines_total declares an explicit fill: 0 —
# output only, never a hidden ratio denominator. The five window metrics cover
# every declared window form (spec rev 1 "Query and result contract").
TIME_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: sales_time
    description: Task 4 fixture (differently named business dates)
    requires: ["ariadne.conformed_dimensions@1"]
    datasets:
      - name: dated_orders
        source: demo.main.dated_orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: ordered_on
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: ordered_on
            dimension:
              is_time: true
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: customer_id
      - name: dated_customers
        source: demo.main.dated_customers
        primary_key: [customer_id]
        fields:
          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: customer_id
          - name: tier
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: tier
            dimension: {}
      - name: dated_lines
        source: demo.main.dated_lines
        primary_key: [line_id]
        fields:
          - name: line_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_id
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: shipped_on
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: shipped_on
            dimension:
              is_time: true
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    relationships:
      - name: order_dated_customer
        cardinality: many_to_one
        from_dataset: dated_orders
        from_fields: [customer_id]
        to_dataset: dated_customers
        to_fields: [customer_id]
    conformed_dimensions:
      - name: region
        members:
          - dataset: dated_orders
            field: region
          - dataset: dated_lines
            field: region
      - name: business_date
        members:
          - dataset: dated_orders
            field: ordered_on
            native_grain: day
          - dataset: dated_lines
            field: shipped_on
            native_grain: month
    metrics:
      - name: orders_total
        dataset: dated_orders
        description: Sum of order amounts at order grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: lines_total
        dataset: dated_lines
        description: Sum of line amounts, filled with 0 on output only
        fill: 0
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
      - name: order_line_ratio
        description: Derived ratio across both facts (resolves after merge)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total / lines_total
      - name: orders_rolling_3
        description: Rolling 3-group sum of orders_total
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total
        window:
          kind: rolling
          size: 3
          function: sum
      - name: orders_cumulative
        description: Cumulative sum of orders_total
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total
        window:
          kind: cumulative
          function: sum
      - name: orders_prior
        description: Preceding-period orders_total
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total
        window:
          kind: prior_period
      - name: orders_rank
        description: Rank of the group by orders_total, descending
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total
        window:
          kind: ranking
          direction: desc
      - name: orders_value_1m
        description: Value-window sum of orders_total, one grain period back
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total
        window:
          kind: value_window
          size: 1
          function: sum
"""


def _t4_graph(root: Path):
    """The task 4 graph over the registered source fixture."""
    registry = build_source_fixture(root / "src")
    staging = _staging(root / "t4", {"sales_time.yml": TIME_YML})
    return load_graph(staging / "semantic_layer"), _duck_connection(registry)


def _month(value) -> str:
    """One grouped time key as 'YYYY-MM' (grain-independent label)."""
    return str(value)[:7]


def test_t4_differently_named_dates_align_monthly_with_ratio_and_fill(tmp_path):
    # Hand-derived from the fixture rows, monthly over [2026-01-01, 2026-05-01):
    # Jan orders 100+200=300 vs lines 60+30+10+150+50=300 -> ratio 1.0; Feb
    # 400 vs 250 -> 1.6; March is orders-only (50, lines NULL -> ratio NULL,
    # filled output 0 — the fill never reaches the hidden denominator); April
    # is lines-only (75, orders NULL -> ratio NULL). Both unmatched groups
    # survive: the time filter never drops another fact's groups.
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total", "lines_total", "order_line_ratio"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-01",
                "end": "2026-05-01",
            },
        },
        con,
    )
    assert plan.time_dimension == "business_date"
    assert plan.time_grain == "month"
    assert sorted(branch.dataset for branch in plan.branches) == ["dated_lines", "dated_orders"]
    rows = {_month(month): tuple(values) for month, *values in con.execute(plan.sql).fetchall()}
    assert rows == {
        "2026-01": (300.0, 300.0, 1.0),
        "2026-02": (400.0, 250.0, 1.6),
        "2026-03": (50.0, 0, None),
        "2026-04": (None, 75.0, None),
    }
    assert len(sqlglot.parse(plan.sql)) == 1  # still one guarded SELECT

    # the range is HALF-OPEN: the line shipped exactly on 2026-04-01 falls
    # outside [.., 2026-04-01) and April disappears from the displayed groups
    clipped = plan_query(
        graph,
        {
            "metrics": ["orders_total", "lines_total"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    assert sorted(_month(row[0]) for row in con.execute(clipped.sql).fetchall()) == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        # rolling 3 groups over the month rows 300, 400, 50
        ("orders_rolling_3", {"2026-01": 300.0, "2026-02": 700.0, "2026-03": 750.0}),
        ("orders_cumulative", {"2026-01": 300.0, "2026-02": 700.0, "2026-03": 750.0}),
        ("orders_prior", {"2026-01": None, "2026-02": 300.0, "2026-03": 400.0}),
        # rank by value desc: Feb 400 -> 1, Jan 300 -> 2, Mar 50 -> 3
        ("orders_rank", {"2026-01": 2, "2026-02": 1, "2026-03": 3}),
        # RANGE frame one grain period back: Feb sums Jan+Feb, Mar sums Feb+Mar
        ("orders_value_1m", {"2026-01": 300.0, "2026-02": 700.0, "2026-03": 450.0}),
    ],
)
def test_t4_each_declared_window_form_computes_post_aggregate(tmp_path, metric, expected):
    # One focused parameterized check per declared window form (completion
    # criterion), monthly over Jan..Mar where every month exists on the orders
    # fact. Expected values hand-derived from the month totals 300/400/50.
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": [metric],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    assert plan.windows == (metric,)
    rows = {_month(month): value for month, value in con.execute(plan.sql).fetchall()}
    assert rows == expected
    assert len(sqlglot.parse(plan.sql)) == 1


def test_t4_lookback_precedes_the_displayed_range_trim(tmp_path):
    # The displayed range starts AFTER the lookback: exactly one displayed row,
    # whose preceding-period value (Feb 400) and rolling 3-group total
    # (Jan 300 + Feb 400 + Mar 50 = 750) need the preceding groups fetched
    # BEFORE the trim (spec rev 1 "Query and result contract").
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total", "orders_prior", "orders_rolling_3"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-03-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    rows = con.execute(plan.sql).fetchall()
    assert len(rows) == 1  # the lookback groups are fetched, then trimmed away
    assert _month(rows[0][0]) == "2026-03"
    assert tuple(rows[0][1:]) == (50.0, 400.0, 750.0)

    # cumulative windows need EVERY preceding group: the fetch start opens up
    # while the displayed range still trims to March
    cumulative = plan_query(
        graph,
        {
            "metrics": ["orders_cumulative"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-03-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    assert [_month(row[0]) for row in con.execute(cumulative.sql).fetchall()] == ["2026-03"]
    assert con.execute(cumulative.sql).fetchall()[0][1] == 750.0


def test_t4_windows_partition_by_non_time_dimensions_through_lookups(tmp_path):
    # tier reaches the orders branch through the order_dated_customer lookup,
    # so the branch compiles through the in-branch join builder while grouping
    # by its truncated native time — and the window PARTITIONS by tier. No
    # implicit spine: standard has no February row, so March's preceding period
    # is January (200), not an invented February. Hand-derived: gold Jan 100 /
    # Feb 400; standard Jan 200 / Mar 50.
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total", "orders_prior"],
            "dimensions": ["tier"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    (branch,) = plan.branches
    assert branch.joins == ("order_dated_customer",)
    rows = {
        (tier, _month(month)): tuple(values)
        for tier, month, *values in con.execute(plan.sql).fetchall()
    }
    assert rows == {
        ("gold", "2026-01"): (100.0, None),
        ("gold", "2026-02"): (400.0, 100.0),
        ("standard", "2026-01"): (200.0, None),
        ("standard", "2026-03"): (50.0, 200.0),
    }


def test_t4_sparse_group_lookback_fetches_the_preceding_actual_group(tmp_path):
    # The lookback needs preceding ACTUAL groups, not calendar periods:
    # standard tier has no February row, so March's preceding group is January
    # (200). Displaying March only must still fetch January — a calendar-shifted
    # fetch start would drop it and leave the LAG (and any ROWS frame) reading
    # sparse history as if it were contiguous (candidate review C1).
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total", "orders_prior"],
            "dimensions": ["tier"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-03-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    rows = con.execute(plan.sql).fetchall()
    assert [(tier, _month(month)) for tier, month, *_ in rows] == [("standard", "2026-03")]
    assert rows[0][2:] == (50.0, 200.0)  # the preceding ACTUAL group is January


def test_t4_mid_month_range_keeps_the_overlapping_start_bucket(tmp_path):
    # The display range [2026-01-15, 2026-02-01) at month grain: the January
    # bucket OVERLAPS the range start (the Jan 20 order qualifies on native
    # time), so it stays displayed with its in-range population (200) — the
    # Jan 10 order falls outside the half-open native population. A trim that
    # compares the grouped key (Jan 1) against Jan 15 deletes the whole bucket
    # (candidate review C2).
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_total"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-15",
                "end": "2026-02-01",
            },
        },
        con,
    )
    rows = con.execute(plan.sql).fetchall()
    assert [(_month(month), value) for month, value in rows] == [("2026-01", 200.0)]


def test_t4_declared_fill_applies_without_time_or_derived_stage(tmp_path):
    # lines_total declares fill: 0. Requested ALONE, with no time alignment
    # and no derived metric, filtered to an absent region: the empty-population
    # aggregate reads 0, not NULL — the fill projection must not depend on
    # unrelated request features (candidate review C3).
    graph, con = _t4_graph(tmp_path)
    plan = plan_query(
        graph,
        {
            "metrics": ["lines_total"],
            "filters": [{"field": "region", "op": "=", "value": "APAC"}],
        },
        con,
    )
    assert con.execute(plan.sql).fetchall() == [(0,)]


def test_t4_windowed_base_metric_keeps_its_fact_branch(tmp_path):
    # A BASE aggregate declaring a window directly (SUM(amount), not a
    # windowed derived metric), queried alone with conformed time: it keeps
    # its home fact branch — the aggregate computes in-branch, the cumulative
    # window applies post-alignment over the aligned column (candidate review
    # C4). Hand-derived from the month totals 300/400/50.
    windowed_base = TIME_YML + (
        "      - name: orders_base_cumulative\n"
        "        dataset: dated_orders\n"
        "        description: Cumulative sum of the base order aggregate\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: SUM(amount)\n"
        "        window:\n"
        "          kind: cumulative\n"
        "          function: sum\n"
    )
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "wb", {"windowed_base.yml": windowed_base})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_base_cumulative"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    assert [branch.dataset for branch in plan.branches] == ["dated_orders"]
    assert plan.windows == ("orders_base_cumulative",)
    rows = {_month(month): value for month, value in con.execute(plan.sql).fetchall()}
    assert rows == {"2026-01": 300.0, "2026-02": 700.0, "2026-03": 750.0}


def test_t4_finer_than_native_grain_refuses(tmp_path):
    # dated_lines declares a month native grain: a day request is finer than a
    # declared native grain and refuses BEFORE any SELECT executes, naming the
    # offending member (spec rev 1 acceptance 4). The request spans BOTH
    # facts, so both members' native grains gate the grain.
    graph, con = _t4_graph(tmp_path)
    with pytest.raises(PlannerError) as refused:
        plan_query(
            graph,
            {
                "metrics": ["orders_total", "lines_total"],
                "time": {
                    "dimension": "business_date",
                    "grain": "day",
                    "start": "2026-01-01",
                    "end": "2026-01-31",
                },
            },
            con,
        )
    assert refused.value.code == "time_grain_too_fine"
    assert "dated_lines" in str(refused.value) and "month" in str(refused.value)


def test_t4_cyclic_derivation_fails_at_load(tmp_path):
    # metric_a -> metric_b -> metric_a: dependency cycles are rejected at load,
    # before any branch, alignment or window stage is compiled (spec rev 1 §5).
    cyclic = TIME_YML + (
        "      - name: metric_a\n"
        "        description: cyclic pair a\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: metric_b + 1\n"
        "      - name: metric_b\n"
        "        description: cyclic pair b\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: metric_a + 1\n"
    )
    build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "cyclic", {"cyclic.yml": cyclic})
    with pytest.raises(GraphError, match="cycle"):
        load_graph(staging / "semantic_layer")


def test_t4_time_and_window_refusals_are_structured(tmp_path):
    graph, con = _t4_graph(tmp_path)
    month_time = {"dimension": "business_date", "grain": "month"}

    # a time-frame window needs the declared conformed business time
    with pytest.raises(PlannerError) as no_time:
        plan_query(graph, {"metrics": ["orders_rolling_3"]}, con)
    assert no_time.value.code == "window_requires_time"
    assert "orders_rolling_3" in str(no_time.value)

    # the time dimension must be a declared conformed TIME dimension
    with pytest.raises(PlannerError) as not_time:
        plan_query(
            graph,
            {"metrics": ["orders_total"], "time": month_time | {"dimension": "region"}},
            con,
        )
    assert not_time.value.code == "time_dimension_invalid"
    assert "business_date" in not_time.value.candidates

    # unknown grain and malformed declarations refuse
    with pytest.raises(PlannerError) as bad_grain:
        plan_query(
            graph,
            {
                "metrics": ["orders_total"],
                "time": {"dimension": "business_date", "grain": "fortnight"},
            },
            con,
        )
    assert bad_grain.value.code == "time_grain_invalid"

    for bad_time in (
        {"dimension": "business_date", "grain": "month", "start": "January"},  # not ISO
        {
            "dimension": "business_date",
            "grain": "month",
            "start": "2026-03-01",
            "end": "2026-01-01",
        },
        {"dimension": "business_date"},  # no grain
        "monthly",  # not a mapping
        {"dimension": "business_date", "grain": "month", "quarter": 1},  # unknown key
    ):
        with pytest.raises(PlannerError) as malformed:
            plan_query(graph, {"metrics": ["orders_total"], "time": bad_time}, con)
        assert malformed.value.code == "time_invalid"

    # the time dimension may not also be a requested dimension
    with pytest.raises(PlannerError) as duplicated:
        plan_query(
            graph,
            {"metrics": ["orders_total"], "dimensions": ["business_date"], "time": month_time},
            con,
        )
    assert duplicated.value.code == "time_invalid"


# --- Task 5 (issue #30): admit local models and expose CLI/MCP queries -------
#
# The public submission/runtime seam: a validated source-layout graph proposal
# (one dataset per model + semantic_layer/graph.yml + cited OKF context) is
# admitted through Git Review Admission, and the SAME rows/context come back
# through the runtime, local JSON CLI and MCP tools. Unadmitted graphs never
# serve as governed; post-admission candidate edits cannot change the snapshot;
# a new multi-fact admission without cited context is refused.

# One dataset per model (the b09f649 source-boundary shape), the cross-file
# graph supplying the relationship and the conformed dimension.
T5_ORDERS_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders fact (task 5 source layout)
    datasets:
      - name: orders
        source: demo.main.orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    metrics:
      - name: orders_total
        dataset: orders
        description: Sum of order amounts at order grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
"""

T5_LINES_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: order_lines
    description: Order lines fact (task 5 source layout)
    datasets:
      - name: order_lines
        source: demo.main.order_lines
        primary_key: [line_id]
        fields:
          - name: line_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_id
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    metrics:
      - name: lines_total
        dataset: order_lines
        description: Sum of line amounts at line grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""


def _t5_page(page_type: str, title: str, *, status: str | None = None, sources: str = "") -> str:
    """One minimal gate-clean OKF page of ``page_type`` (ADR-0007 frontmatter)."""
    front = (
        f"type: {page_type}\ntitle: {title}\n"
        f"description: One {page_type} page.\ntags: [{page_type}]\n"
    )
    if status:
        front += f"status: {status}\n"
    front += (
        "sources:\n  - id: seed-notes\n    resource: data/seed_notes.md\n    title: Seed notes\n"
    )
    return f"---\n{front}---\n\n# {title}\n" + sources


def _t5_metric_page(name: str, policy: str = "policies/region-rollup.md") -> str:
    """A metric page whose ``sources`` cite one governing Policy page."""
    front = (
        f"type: metric\nstatus: draft\ntitle: {name}\n"
        f"description: The {name} metric.\ntags: [metric]\n"
        "sources:\n"
        "  - id: region-rollup\n"
        f"    resource: {policy}\n"
        "    title: Region rollup policy\n"
    )
    return f"---\n{front}---\n\n# {name}\n"


def _t5_bundle(
    *,
    lines_page: str | None = "default",
    orders_policy: str = "policies/region-rollup.md",
) -> dict:
    """One complete source-layout graph bundle: Seed Notes, one dataset per
    model, the cross-file graph, and the six OKF sections (computations are
    generated). ``lines_page=None`` drops the lines_total metric page (the
    missing-cited-context case); ``orders_policy`` points the orders_total
    citation at a Policy path (the broken-citation case)."""
    files = [
        {
            "path": "data/seed_notes.md",
            "content": "# Seed notes\n\nEach fact aggregates at its own grain.\n",
        },
        {"path": "semantic_layer/models/orders.yml", "content": T5_ORDERS_YML},
        {"path": "semantic_layer/models/order_lines.yml", "content": T5_LINES_YML},
        {"path": "semantic_layer/graph.yml", "content": GRAPH_YML},
        {
            "path": "context_layer/tables/orders.md",
            "content": (
                "---\ntype: table\ntitle: Orders\ndescription: One row per order.\n"
                "tags: [table]\nsources:\n  - id: orders\n    resource: demo.main.orders\n"
                "    title: orders\ngrain:\n  primary_key: [order_id]\n"
                "  cardinality_enforcement: STRICT_1_TO_1\n---\n\n# Orders\n"
            ),
        },
        {
            "path": "context_layer/references/joins/orders--order-lines.md",
            "content": _t5_page("reference", "orders to order lines"),
        },
        {
            "path": "context_layer/policies/region-rollup.md",
            "content": _t5_page("policy", "Region rollup", status="draft"),
        },
        {
            "path": "context_layer/metrics/orders_total.md",
            "content": _t5_metric_page("orders_total", orders_policy),
        },
        {
            "path": "context_layer/skills/query-multi-fact.md",
            "content": _t5_page("skill", "query multi fact"),
        },
    ]
    if lines_page is not None:
        content = _t5_metric_page("lines_total") if lines_page == "default" else lines_page
        files.append({"path": "context_layer/metrics/lines_total.md", "content": content})
    return {"files": files}


def _t5_candidate(tmp_path: Path, bundle: dict | None = None):
    """Create the graph fixture as a revision-bound Authoring candidate."""

    project = tmp_path / "proj"
    build_source_fixture(project)  # project/ariadne.yaml + project/mf.db (approved registry)
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml")
    run_git(
        project,
        "commit",
        "-q",
        "-m",
        "human: synthetic source registry",
        "--",
        "ariadne.yaml",
    )
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = started["candidate_revision"]
    for artifact in (bundle if bundle is not None else _t5_bundle())["files"]:
        parts = Path(artifact["path"]).parts
        if parts == ("data", "seed_notes.md"):
            edit = {"kind": "seed_notes", "content": artifact["content"]}
        elif parts[:2] == ("semantic_layer", "models"):
            edit = {
                "kind": "model",
                "name": Path(parts[-1]).stem,
                "content": artifact["content"],
            }
        elif parts == ("semantic_layer", "graph.yml"):
            edit = {"kind": "graph", "content": artifact["content"]}
        elif parts[:1] == ("context_layer",):
            section = "joins" if parts[1:3] == ("references", "joins") else parts[1]
            edit = {
                "kind": "page",
                "section": section,
                "name": Path(parts[-1]).stem,
                "content": artifact["content"],
            }
        else:
            raise AssertionError(f"unsupported synthetic artifact path: {artifact['path']}")
        edited = api.edit_proposal(started["proposal"], revision, edit)
        revision = edited["revision"]

    return project, api, started, revision


def _t5_admitted(tmp_path: Path, bundle: dict | None = None) -> tuple[Path, dict]:
    project, api, started, revision = _t5_candidate(tmp_path, bundle)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == validated["revision"] and review["report"]["ok"] is True
    assert admit(project, review) == 0
    return project, review


def _t5_runtime(project: Path):
    from ariadne.query import QueryRuntime

    return QueryRuntime.open_project(project)


def test_t5_admitted_graph_returns_same_rows_and_context_over_runtime_cli_and_mcp(tmp_path, capsys):
    # Spec rev 1 acceptance 1/AC6-local at the public seam: the hand-derived
    # trap values (NA 300/300, EMEA 400/400) come back governed through the
    # runtime, the local JSON CLI, and the MCP tool — one implementation.
    import io

    from ariadne.cli import main as cli_main
    from ariadne.serve import build_app

    project, view = _t5_admitted(tmp_path)
    runtime = _t5_runtime(project)
    request = {"metrics": ["orders_total", "lines_total"], "dimensions": ["region"]}

    result = asyncio.run(runtime.query_metrics(request))
    assert result["governed"] is True
    assert result["metrics"] == ["orders_total", "lines_total"]
    rows = {row["region"]: (row["orders_total"], row["lines_total"]) for row in result["rows"]}
    assert rows == {"NA": (300.0, 300.0), "EMEA": (400.0, 400.0)}
    assert result["sql"] and len(sqlglot.parse(result["sql"])) == 1  # one guarded SELECT
    # the bounded lineage names both fact branches and the conformed key
    assert sorted(branch["dataset"] for branch in result["plan"]["branches"]) == [
        "order_lines",
        "orders",
    ]
    assert result["plan"]["conformed_keys"] == ["region"]
    # Admission provenance binds the exact reviewed Git revision and its
    # independent validation evidence; it does not mutate artifact metadata.
    admission_view = result["admission"]
    assert admission_view["route"] == "git-review-admission"
    assert admission_view["revision"] == view["revision"]
    assert admission_view["review_digest"] == view["review_digest"]
    assert admission_view["artifact_digest"]
    assert admission_view["validation"]["ok"] is True
    assert admission_view["validation"]["performed_checks"]
    # per-metric cited context: the served metric page plus the cited Policy
    # body, the honest pending attestation state (ADR-0013), and the advisory
    # signals envelope over exactly the consumed pages (spec 0011 §§4–5)
    for name in ("orders_total", "lines_total"):
        context = result["context"][name]
        assert f"# {name}" in context["metric_page"]
        assert context["policies"] and "Region rollup" in context["policies"][0]
        assert context["attestation"] == "pending"
        signals = context["context_signals"]
        assert [page["path"] for page in signals["pages"]] == [
            f"metrics/{name}.md",
            "policies/region-rollup.md",
            f"computations/{name}.md",
        ]
        assert signals["warnings"] == []
        policy_view = signals["pages"][1]
        assert policy_view["status"] == "draft"
        assert policy_view["verification_tier"] == "unverified"
        assert policy_view["freshness"]["state"] == "unknown"

    # the local JSON CLI returns the SAME value over its own runtime instance
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    capsys.readouterr()  # drop the admission receipt: the CLI writes exactly one JSON value
    code = cli_main(
        ["query-metrics", "--project", str(project), "--file", str(request_file)],
        io.StringIO(""),
    )
    assert code == 0

    def _normalized(response: dict) -> dict:
        # without an explicit `order`, the aligned keys-UNION row order is not
        # part of the contract — parity is over the value, not the sequencing.
        # The advisory data_signals view likewise carries the assessment
        # instant of ITS OWN execution (issue #54: every read is a fresh pure
        # assessment) — normalized out here exactly as the get-metric CLI
        # parity test does, everything else compared exactly.
        normalized = {**response, "rows": sorted(response["rows"], key=lambda row: row["region"])}
        if "data_signals" in normalized:
            normalized["data_signals"] = {
                **normalized["data_signals"],
                "assessed_at": "<assessed_at>",
            }
        return normalized

    cli_result = json.loads(capsys.readouterr().out)
    assert _normalized(cli_result) == _normalized(result)

    # the MCP tool is a thin adapter over the same runtime method
    app = build_app(runtime)

    def _payload(outcome) -> Any:
        # mcp 2.x call_tool returns one CallToolResult; mcp<2 returned a
        # (blocks, structured) tuple or a bare block list — handle both shapes
        if isinstance(outcome, tuple):
            outcome = outcome[0]
        blocks = list(getattr(outcome, "content", outcome))
        parsed = [json.loads(block.text) for block in blocks]
        return parsed[0] if len(parsed) == 1 else parsed

    mcp_result = _payload(asyncio.run(app.call_tool("query_metrics", {"request": request})))
    assert _normalized(mcp_result) == _normalized(result)


def test_t5_query_metrics_captures_one_assessment_instant_across_metrics(tmp_path, monkeypatch):
    # Spec 0011 §2: one operation captures ONE aware clock value for all its
    # assessments. The shared Policy carries an explicit date-only
    # expiry stamp; §3 keeps it current throughout its named UTC date and
    # stale at the next midnight. Ticks land either side of that boundary: a
    # single shared instant keeps BOTH metrics' assessments current, while
    # per-metric captures would flip whichever context is assessed second to
    # stale.
    from datetime import UTC, date, datetime, timedelta

    from ariadne import context as context_module

    bundle = _t5_bundle()
    stamped = date.today() + timedelta(days=1)
    policy = next(
        artifact
        for artifact in bundle["files"]
        if artifact["path"] == "context_layer/policies/region-rollup.md"
    )
    policy["content"] = policy["content"].replace(
        "sources:\n", f"stale_after: {stamped.isoformat()}\nsources:\n", 1
    )
    project, _view = _t5_admitted(tmp_path, bundle)
    _, snapshot = admission.resolve_admission(project)
    served_policy = snapshot / "context_layer" / "policies" / "region-rollup.md"
    frontmatter = yaml.safe_load(served_policy.read_text(encoding="utf-8").split("---")[1])
    assert frontmatter["stale_after"] == stamped.isoformat()
    midnight = datetime(stamped.year, stamped.month, stamped.day, tzinfo=UTC)
    runtime = _t5_runtime(project)
    ticks = iter([midnight + timedelta(hours=10), midnight + timedelta(days=1)])
    monkeypatch.setattr(context_module, "_assessment_now", lambda: next(ticks))
    result = asyncio.run(
        runtime.query_metrics(
            {"metrics": ["orders_total", "lines_total"], "dimensions": ["region"]}
        )
    )
    for name in ("orders_total", "lines_total"):
        signals = result["context"][name]["context_signals"]
        policy_view = next(
            page for page in signals["pages"] if page["path"] == "policies/region-rollup.md"
        )
        assert policy_view["freshness"] == {
            "stale_after": stamped.isoformat(),
            "state": "current",
        }
        assert signals["warnings"] == []


def test_t5_query_detail_projects_through_the_admitted_graph(tmp_path):
    # Spec rev 1 acceptance 5 (safe detail): the root keeps its grain and a
    # parent field arrives through the proven many-to-one path — hand-derived
    # line -> order amounts from the fixture rows.
    project, _view = _t5_admitted(tmp_path)
    runtime = _t5_runtime(project)
    result = asyncio.run(
        runtime.query_detail({"dataset": "order_lines", "fields": ["line_id", "amount"]})
    )
    assert result["governed"] is True
    assert result["dataset"] == "order_lines"
    amounts = {row["line_id"]: row["amount"] for row in result["rows"]}
    assert amounts == {11: 100.0, 12: 100.0, 13: 100.0, 21: 200.0, 22: 200.0, 31: 400.0}
    assert result["admission"]["route"] == "git-review-admission"


def test_t5_later_candidate_and_changed_registry_cannot_change_admitted_query(tmp_path):
    # A later authored model/graph/Policy stays outside the admitted snapshot;
    # changing the operator registry invalidates construction instead.
    project, view = _t5_admitted(tmp_path)
    runtime = _t5_runtime(project)
    request = {"metrics": ["orders_total", "lines_total"], "dimensions": ["region"]}
    before = asyncio.run(runtime.query_metrics(request))

    api = AuthoringProject(project)
    later = api.start_proposal()
    edits = (
        {
            "kind": "model",
            "name": "orders",
            "content": T5_ORDERS_YML.replace("SUM(amount)", "SUM(amount) + 0"),
        },
        {"kind": "graph", "content": GRAPH_YML + "# touched\n"},
        {
            "kind": "page",
            "section": "policies",
            "name": "region-rollup",
            "content": _t5_page("policy", "Region rollup", status="draft") + "changed\n",
        },
    )
    revision = later["candidate_revision"]
    for edit in edits:
        revision = api.edit_proposal(later["proposal"], revision, edit)["revision"]

    after = asyncio.run(_t5_runtime(project).query_metrics(request))
    assert after["rows"] == before["rows"]
    assert after["admission"]["revision"] == view["revision"]

    registry = project / "ariadne.yaml"
    original = registry.read_bytes()
    registry.write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: mf.db\n  - name: other\n"
        "    type: sqlite\n    path: mf.db\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(ValueError, match="source"):
            _t5_runtime(project)
    finally:
        registry.write_bytes(original)
    runtime.con.close()


def test_t5_missing_cited_context_refuses_new_multifact_admission(tmp_path):
    # A newly reviewed multi-fact candidate requires the cited metric and Policy
    # pages to resolve inside the candidate; missing evidence is not admitted.
    for index, (bundle, fragment) in enumerate(
        (
            (_t5_bundle(lines_page=None), "lines_total"),
            (_t5_bundle(orders_policy="policies/no-such-policy.md"), "no-such-policy"),
        )
    ):
        project, api, started, revision = _t5_candidate(tmp_path / f"case{index}", bundle)
        validation = api.validate_proposal(started["proposal"], revision)
        assert validation["ok"] is False, validation
        assert any(fragment in error for error in validation["errors"]), validation["errors"]


def test_t5_citation_escape_outside_the_policy_directory_refuses_admission(tmp_path):
    # A path that escapes context_layer/policies/ cannot satisfy a metric's
    # citation, even when the target exists elsewhere in the same candidate.
    bundle = _t5_bundle(orders_policy="policies/../skills/query-multi-fact.md")
    project, api, started, revision = _t5_candidate(tmp_path, bundle)
    validation = api.validate_proposal(started["proposal"], revision)
    assert validation["ok"] is False, validation
    assert any(
        "does not resolve inside context_layer/policies/" in error for error in validation["errors"]
    ), validation["errors"]


def test_t5_cli_query_metrics_error_keeps_the_planner_code_and_candidates(tmp_path, capsys):
    # mf-t5 fix F4: the CLI error envelope keeps the planner's stable failure
    # fields (spec rev 1: error codes and candidate/retry information are API
    # fields, message prose is not) — an unknown metric reports code
    # unknown_metric plus the real candidates over the admitted graph.
    import io

    from ariadne.cli import main as cli_main

    project, _view = _t5_admitted(tmp_path)
    request_file = tmp_path / "bad-request.json"
    request_file.write_text(json.dumps({"metrics": ["no_such_metric"]}), encoding="utf-8")
    capsys.readouterr()  # drop the admission receipt: the CLI writes one JSON error
    code = cli_main(
        ["query-metrics", "--project", str(project), "--file", str(request_file)],
        io.StringIO(""),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["type"] == "PlannerError"
    assert error["code"] == "unknown_metric"
    assert "orders_total" in error["candidates"]
    assert "lines_total" in error["candidates"]


def test_t4_windowed_base_alongside_a_derived_window_computes(tmp_path):
    # C4 recheck residual: requesting the windowed BASE aggregate together
    # with a derived window metric re-applied the base's SUM(amount) in the
    # derived-expression layer, where raw columns no longer exist — a bind
    # failure for a valid combined request. The base's aligned column is
    # reused; only its window applies post-alignment. Hand-derived: months
    # 300/400/50 → cumulative 300/700/750 and prior NULL/300/400.
    windowed_base = TIME_YML + (
        "      - name: orders_base_cumulative\n"
        "        dataset: dated_orders\n"
        "        description: Cumulative sum of the base order aggregate\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: SUM(amount)\n"
        "        window:\n"
        "          kind: cumulative\n"
        "          function: sum\n"
    )
    registry = build_source_fixture(tmp_path / "src")
    staging = _staging(tmp_path / "wb2", {"windowed_base.yml": windowed_base})
    graph = load_graph(staging / "semantic_layer")
    con = _duck_connection(registry)
    plan = plan_query(
        graph,
        {
            "metrics": ["orders_base_cumulative", "orders_prior"],
            "time": {
                "dimension": "business_date",
                "grain": "month",
                "start": "2026-01-01",
                "end": "2026-04-01",
            },
        },
        con,
    )
    rows = {
        _month(month): (cumulative, prior)
        for month, cumulative, prior in con.execute(plan.sql).fetchall()
    }
    assert rows == {
        "2026-01": (300.0, None),
        "2026-02": (700.0, 300.0),
        "2026-03": (750.0, 400.0),
    }
