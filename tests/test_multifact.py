"""Multi-fact core task 1: normalized OSI layouts + graph validation (issue #26).

Spec rev 1 "Authoring contract and normalized graph": the domain layout (one
multi-dataset OSI file) and the source layout (per-source OSI files plus
``semantic_layer/graph.yml``) normalize to ONE ``SemanticGraph``; contradictory
declarations and ambiguous metric ownership fail at the ``load_graph`` /
``validate`` seam — BEFORE any SELECT is compiled. The fixture is a registered
SQLite source (source-backed, not an in-memory dict); live relationship-target
audits are task 2 (#27) and must surface as not-run, never as a pass.
"""

import sqlite3
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import (
    exp,  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.grain import relationship_target_audit  # noqa: E402
from ariadne.planner import PlannerError, plan_query  # noqa: E402
from ariadne.semantic_graph import GraphError, load_graph  # noqa: E402
from ariadne.sources import build_connection, load_registry  # noqa: E402
from ariadne.validate import validate  # noqa: E402

# (order_id, region, amount) / (line_id, order_id, region, line_amount): the
# per-order line sums equal the order amounts, and each line carries its order's
# region — the conformed business key is real on both facts.
ORDERS = [(1, "NA", 100.0), (2, "NA", 200.0), (3, "EMEA", 400.0)]
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
                order_id INTEGER PRIMARY KEY,
                region   TEXT NOT NULL,
                amount   REAL NOT NULL
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
            """
        )
        # static literal SQL with ?-bound parameters; rows are module constants
        for statement, rows in (
            ("INSERT INTO orders VALUES (?, ?, ?)", ORDERS),
            ("INSERT INTO order_lines VALUES (?, ?, ?, ?)", LINES),
            ("INSERT INTO shipments VALUES (?, ?, ?)", SHIPMENTS),
            ("INSERT INTO events VALUES (?, ?, ?)", EVENTS),
            ("INSERT INTO owners VALUES (?, ?)", OWNERS),
            ("INSERT INTO tasks VALUES (?, ?, ?, ?)", TASKS),
            ("INSERT INTO teams VALUES (?, ?, ?)", TEAMS),
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
        plan_query(graph, {"metrics": ["orders_total"], "filters": []}, con)
    assert bad_request.value.code == "request_invalid"

    # cross-fact derived metrics compute after branch alignment (task 4, #29):
    # the request is refused instead of silently narrowed to one fact
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
    with pytest.raises(PlannerError) as cross_fact:
        plan_query(ratio_graph, {"metrics": ["order_line_ratio"]}, con)
    assert cross_fact.value.code == "derived_cross_fact_unsupported"


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
            "expression": {
                "dialects": [{"dialect": "ANSI_SQL", "expression": "owner_id % 10"}]
            },
        }
    )
    datasets["owners"]["source"] = (
        "SELECT owner_id, owner_id AS owner_ref, owner_name FROM demo.main.owners"
    )
    datasets["owners"]["fields"] += [
        {
            "name": "owner_ref",
            "expression": {
                "dialects": [{"dialect": "ANSI_SQL", "expression": "owner_id % 10"}]
            },
        },
        {
            "name": "owner_key",
            "expression": {
                "dialects": [{"dialect": "ANSI_SQL", "expression": "owner_ref + 0"}]
            },
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
CONFORMED_ALIAS_YML = (
    DOMAIN_YML.replace(
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
DERIVED_YML = DOMAIN_YML + """\
      - name: double_total
        description: Derived twice the orders total (same fact)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total * 2
"""


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
