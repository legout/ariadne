"""Deterministic validation via real Datus compile (ticket #4).

Compiles the spike-doc ``orders.yml`` variant adapted to OSI core per
project/research/datus-spike.md §3.1: a valid model must pass (its one
authoring-quality lint is severity=warning, a pass-through), and a
deliberately broken model must fail with the compiler error captured for the
author loop's feedback. Requires datus-semantic-osi on Python 3.12.

Grain audit (spec rev 6 §8.14, ADR-0006 §5): with ``--db``, validate also runs
the two pre-flight assertions — a fanned dataset source fails Assertion 2 with
the divergence numbers, a non-unique declared grain fails Assertion 1, the
currently served models (orders with its many-to-one rate join, customers)
pass, and without ``--db`` compile-only behavior is unchanged.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.validate import main as validate_main  # noqa: E402
from ariadne.validate import validate  # noqa: E402
from tests.test_evals import CUSTOMERS_MODEL  # noqa: E402
from tests.test_serve import GOLDEN_OSI, seed_demo_db  # noqa: E402

EXCLUDE = "SUM(CASE WHEN orders.status NOT IN ('CANCELLED', 'RETURNED')"

ORDERS_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model (research S5B) adapted to OSI core per datus-spike.md S3.1
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
    metrics:
      - name: gross_revenue
        description: Billed revenue; excludes CANCELLED and RETURNED orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: @EXCLUDE@ THEN orders.amount ELSE 0 END)
      - name: cogs
        description: Direct cost of goods sold
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(orders.product_cost)
      - name: gross_margin
        description: (gross_revenue - cogs) / NULLIF(gross_revenue, 0)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: (gross_revenue - cogs) / NULLIF(gross_revenue, 0)
        custom_extensions:
          - vendor_name: DATUS
            data: '{"metric_kind":"derived","inputs":["gross_revenue","cogs"]}'
""".replace("@EXCLUDE@", EXCLUDE)


def make_staging(tmp_path: Path, yml: str) -> Path:
    models = tmp_path / "staging" / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "orders.yml").write_text(yml, encoding="utf-8")
    return tmp_path / "staging"


def _load_trap_builder():
    """Load tests/evals/build_trap_fixture.py by path (same pattern as
    tests/test_evals.py — no package machinery needed)."""
    path = REPO_ROOT / "tests" / "evals" / "build_trap_fixture.py"
    spec = importlib.util.spec_from_file_location("ariadne_test_validate_trap", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The 1:N fan-out fixture: orders⋈order_lines with the naive join in the dataset
# source (deduplicated ground truth NA 300 / EMEA 400, inflated 1100).
build_trap = _load_trap_builder().build
TRAP_MODEL = _load_trap_builder().TRAP_MODEL


# Non-unique declared grain WITHOUT a join (Assertion 1 in isolation): the
# order_lines table repeats order_id across lines, so declaring primary_key
# [order_id] over a plain lines projection violates grain uniqueness.
LINES_GRAIN_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: lines_grain
    description: Lines projection with a non-unique declared grain (audit trap)
    datasets:
      - name: lines
        source: >-
          SELECT line_id, order_id FROM demo.main.order_lines
        primary_key: [order_id]
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
    metrics:
      - name: line_count
        description: Count of lines
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""


def test_valid_orders_model_compiles(tmp_path):
    result = validate(make_staging(tmp_path, ORDERS_YML))
    assert result.ok, f"unexpected errors: {result.errors}"
    assert result.errors == []  # the authoring-quality lint is a warning, not an error


def test_broken_model_fails_with_captured_error(tmp_path):
    broken = ORDERS_YML.replace('"metric_kind"', '"v": "1", "metric_kind"')
    result = validate(make_staging(tmp_path, broken))
    assert not result.ok
    assert result.errors, "broken model must produce a captured error message"


def test_context_only_tree_and_graph_without_models(tmp_path):
    """K4 (issue #44, spec 0010 §9): a tree with NO semantic declarations at
    all is context-only — the semantic checks are explicitly not_applicable
    WITH reasons (a visibly partial scope, never a silent pass); a declared
    graph without models stays the structural failure it always was."""
    result = validate(tmp_path / "staging")
    assert result.ok and not result.errors
    assert result.report is not None
    assert result.report.scope == "context-only (no semantic declarations)"
    outcomes = {check.name: check for check in result.report.checks}
    for name in ("structural", "compile", "conformance", "bind", "grain", "relationship_audit"):
        assert outcomes[name].outcome == "not_applicable", name
        assert outcomes[name].detail, f"{name} needs its not_applicable reason"
    graph_root = tmp_path / "with-graph" / "semantic_layer"
    graph_root.mkdir(parents=True)
    (graph_root / "graph.yml").write_text("datasets: {}\n", encoding="utf-8")
    broken = validate(graph_root.parent)
    assert not broken.ok
    assert any("no semantic models" in error for error in broken.errors)


def test_cli_exit_codes(tmp_path, capsys, monkeypatch):
    # tmp cwd: the repo's own ariadne.yaml (which declares sources) must not
    # hijack these shorthand runs — the CLI's default-registry probe is cwd-based
    monkeypatch.chdir(tmp_path)
    good = make_staging(tmp_path, ORDERS_YML)
    assert validate_main([str(good)]) == 0
    bad_yml = ORDERS_YML.replace('"metric_kind"', '"v": "1", "metric_kind"')
    broken = make_staging(tmp_path / "b", bad_yml)
    assert validate_main([str(broken)]) == 1
    err = capsys.readouterr().err
    assert "error:" in err


# --- Grain audit (spec rev 6 §8.14, ADR-0006 §5) -----------------------------


def _write_model(staging: Path, name: str, yml: str) -> None:
    model = staging / "semantic_layer" / "models" / name
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(yml, encoding="utf-8")


# The reviewer's alias trap: every parent-origin measure is projected through an
# alias and the declared grain falls back to the child key, so a direct-column
# scan sees nothing parent-side and the audit passed while SUM(amount) inflated
# 700 (parent truth) to 1100 over the joined rows.
ALIAS_TRAP_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: trap_orders
    description: Aliased parent measures over the naive join (alias audit trap)
    datasets:
      - name: trap_join
        source: >-
          SELECT o.order_id AS order_id, o.region AS region, o.amount AS amount,
                 l.line_id, l.line_amount
          FROM demo.main.orders o
          JOIN demo.main.order_lines l ON l.order_id = o.order_id
        primary_key: [line_id]
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
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    metrics:
      - name: orders_total
        description: SUM of the aliased order amount over the naive join
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: lines_total
        description: SUM of the line amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""


def test_fanned_source_fails_assertion_2_with_divergence(tmp_path):
    """§8.14(a): the orders⋈order_lines trap source fans out the parent grain;
    the audit fails with the divergence numbers and the ADR-0006 rubric."""
    root = build_trap(tmp_path / "trap")
    staging = tmp_path / "staging"
    _write_model(staging, "trap.yml", TRAP_MODEL)
    result = validate(staging, db_path=root / "trap.db")
    assert not result.ok
    assertion_2 = [error for error in result.errors if "Assertion 2" in error]
    assert assertion_2, f"expected an Assertion 2 divergence, got: {result.errors}"
    message = assertion_2[0]
    assert "1100.0" in message and "700.0" in message and "400.0" in message
    assert "trap_orders" in message  # the offending model is named
    for pattern in ("pivot", "child-grain fact model", "weight allocation"):
        assert pattern in message  # ADR-0006 rubric patterns named in remediation


def test_injection_in_declared_grain_never_reaches_the_audit_connection(tmp_path):
    """A staged model's primary_key is AGENT-AUTHORED text reviewed only AFTER
    validation: a key entry carrying SQL (statement break-out + COPY) must be
    refused as a grain declaration error BEFORE the audit connection runs —
    never interpolated into the Assertion 1 statement (no file may appear)."""
    root = build_trap(tmp_path / "trap")
    staging = tmp_path / "staging"
    target = tmp_path / "pk-injection.txt"
    wrapped = "(SELECT * FROM demo.main.orders)"
    payload = (
        f"order_id FROM {wrapped}) _d) FROM {wrapped} _t; "
        f"COPY (SELECT 'PWNED') TO '{target}' (HEADER);--"
    )
    _write_model(
        staging,
        "evil.yml",
        ORDERS_YML.replace(
            "        primary_key: [order_id]\n",
            f'        primary_key: ["{payload}"]\n',
        ),
    )
    result = validate(staging, db_path=root / "trap.db")
    assert not result.ok
    grain_errors = [error for error in result.errors if "primary_key" in error]
    assert grain_errors, f"expected a primary_key refusal, got: {result.errors}"
    assert not target.exists(), "the injected COPY statement executed"


def test_undeclared_grain_fails_the_audit(tmp_path):
    """ADR-0006 rule of single declared grain: a model with NO declared
    primary_key has no verifiable grain and must FAIL the audit — never pass by
    skipping the assertions."""
    root = build_trap(tmp_path / "trap")
    staging = tmp_path / "staging"
    _write_model(staging, "nopk.yml", ORDERS_YML.replace("        primary_key: [order_id]\n", ""))
    result = validate(staging, db_path=root / "trap.db")
    assert not result.ok
    grain_errors = [error for error in result.errors if "no declared grain" in error]
    assert grain_errors, f"expected the no-declared-grain error, got: {result.errors}"
    message = grain_errors[0]
    assert "single declared grain" in message  # names the ADR-0006 rule
    assert "'orders'" in message  # the offending model is named
    assert "primary_key" in message  # remediation names the missing declaration
    assert validate(staging).ok  # compile-only mode (no --db) is unchanged


def test_aliased_parent_measures_fail_assertion_2(tmp_path):
    """Reviewer fixture: `o.amount AS amount` with a child-grain primary_key
    [line_id] used to pass the audit while SUM(amount) inflated 700 -> 1100.
    Select aliases must resolve to their underlying parent-origin expressions."""
    root = build_trap(tmp_path / "trap")
    staging = tmp_path / "staging"
    _write_model(staging, "alias_trap.yml", ALIAS_TRAP_YML)
    result = validate(staging, db_path=root / "trap.db")
    assert not result.ok
    amount_errors = [error for error in result.errors if "SUM(amount)" in error]
    assert amount_errors, f"expected an Assertion 2 divergence on amount, got: {result.errors}"
    message = amount_errors[0]
    assert "Assertion 2" in message
    assert "1100.0" in message and "700.0" in message  # inflated vs parent truth
    assert "400.0" in message  # the divergence itself
    assert not any("Assertion 1" in error for error in result.errors)  # line_id IS unique


CTE_TRAP_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: cte_trap
    description: Fan-out join hidden inside a CTE, outer SELECT reads the CTE
    datasets:
      - name: cte_join
        source: >-
          WITH joined AS (
            SELECT o.order_id, o.region AS region, o.amount AS amount,
                   l.line_id, l.line_amount
            FROM demo.main.orders o
            JOIN demo.main.order_lines l ON l.order_id = o.order_id
          )
          SELECT order_id, region, amount, line_id, line_amount FROM joined
        primary_key: [line_id]
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
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    metrics:
      - name: orders_total
        description: SUM of the aliased order amount over the CTE-joined rows
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: lines_total
        description: SUM of the line amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""


def test_cte_hidden_fanout_fails_structural_join_check(tmp_path):
    """Owner decision (mvp-5 round 2, structural guard reuse): a fan-out join
    hidden inside a CTE used to pass the whole audit — the outer SELECT reads
    the CTE, so Assertion 2 has no raw parent projection to trace and Assertion 1
    passes on the child key. The audit now applies the shared structural guard
    (the facade's join-uniqueness rule) to the authored source, so ANY join in
    the tree — CTEs included — whose ON key is not unique on the joined side
    fails the audit naming grain preservation, not just sum divergence."""
    root = build_trap(tmp_path / "trap")
    staging = tmp_path / "staging"
    _write_model(staging, "cte_trap.yml", CTE_TRAP_YML)
    result = validate(staging, db_path=root / "trap.db")
    assert not result.ok
    structural = [error for error in result.errors if "grain-preservation invariant" in error]
    assert structural, f"expected the structural grain failure, got: {result.errors}"
    message = structural[0]
    assert "cte_trap" in message and "cte_join" in message  # offending model + dataset
    assert "structural join check" in message  # the authoritative path, not a tracer
    for pattern in ("pivot", "child-grain fact model", "weight allocation"):
        assert pattern in message  # ADR-0006 rubric remediation carried
    assert not any("Assertion 1" in error for error in result.errors)  # line_id IS unique
    assert not any("Assertion 2" in error for error in result.errors)  # tracer bypassed;
    # the structural guard is what rejects — the sum check never even sees the join


def test_non_unique_declared_pk_fails_assertion_1(tmp_path):
    """§8.14(b): a declared primary_key that is not unique over the compiled
    source fails Assertion 1 — with no join in the source, in isolation."""
    root = build_trap(tmp_path / "trap")
    staging = tmp_path / "staging"
    _write_model(staging, "lines.yml", LINES_GRAIN_YML)
    result = validate(staging, db_path=root / "trap.db")
    assert not result.ok
    assertion_1 = [error for error in result.errors if "Assertion 1" in error]
    assert assertion_1, f"expected an Assertion 1 failure, got: {result.errors}"
    message = assertion_1[0]
    assert "6 rows vs 3 distinct" in message  # order_lines: 6 lines, 3 orders
    assert "Pattern 1" in message and "Pattern 2" in message
    assert not any("Assertion 2" in error for error in result.errors)  # no join -> n/a


def test_currently_served_models_pass_the_audit(tmp_path):
    """§8.14(c): the served tree as it stands — the orders model whose source has
    only the many-to-one rate join, plus the customers master-data model — must
    pass both assertions over the real demo.db."""
    db = seed_demo_db(tmp_path / "demo.db")
    staging = tmp_path / "staging"
    _write_model(staging, "orders.yml", GOLDEN_OSI)
    _write_model(staging, "customers.yml", CUSTOMERS_MODEL)
    result = validate(staging, db_path=db)
    assert result.ok, f"served models must pass the audit: {result.errors}"


def test_without_db_compile_only_unchanged(tmp_path):
    """§8.14(d): without --db the audit never runs — the fan-out trap COMPILES
    fine, so validate() passes (current behavior preserved)."""
    build_trap(tmp_path / "trap")  # planted-premise assert only; staging is ours
    staging = tmp_path / "staging"
    _write_model(staging, "trap.yml", TRAP_MODEL)
    result = validate(staging)
    assert result.ok, f"compile-only validate must pass: {result.errors}"


def test_cli_db_flag_runs_the_audit(tmp_path, capsys, monkeypatch):
    """The --db CLI flag wires the audit in: served models + demo.db -> exit 0
    naming the audit; the same audit run is what failed in §8.14(a) via validate()."""
    monkeypatch.chdir(tmp_path)  # the repo ariadne.yaml must not hijack --db
    db = seed_demo_db(tmp_path / "demo.db")
    staging = tmp_path / "staging"
    _write_model(staging, "orders.yml", GOLDEN_OSI)
    _write_model(staging, "customers.yml", CUSTOMERS_MODEL)
    assert validate_main([str(staging), "--db", str(db)]) == 0
    assert "grain audit" in capsys.readouterr().out


def test_cli_explicit_db_beats_ambient_registry(tmp_path, capsys, monkeypatch):
    """With an ambient ./ariadne.yaml present, an explicit --db still runs the
    audit on THAT database — the registry applies only when neither is given."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: missing.db\n",
        encoding="utf-8",
    )
    db = seed_demo_db(tmp_path / "demo.db")
    staging = tmp_path / "staging"
    _write_model(staging, "orders.yml", GOLDEN_OSI)
    _write_model(staging, "customers.yml", CUSTOMERS_MODEL)
    assert validate_main([str(staging), "--db", str(db)]) == 0
    assert "grain audit" in capsys.readouterr().out
