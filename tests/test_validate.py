"""Deterministic validation via real Datus compile (ticket #4).

Compiles the spike-doc ``orders.yml`` variant adapted to OSI core per
docs/research/datus-spike.md §3.1: a valid model must pass (its one
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


def test_missing_models_dir_is_an_error(tmp_path):
    result = validate(tmp_path / "staging")
    assert not result.ok
    assert result.errors


def test_cli_exit_codes(tmp_path, capsys, monkeypatch):
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


def test_cli_db_flag_runs_the_audit(tmp_path, capsys):
    """The --db CLI flag wires the audit in: served models + demo.db -> exit 0
    naming the audit; the same audit run is what failed in §8.14(a) via validate()."""
    db = seed_demo_db(tmp_path / "demo.db")
    staging = tmp_path / "staging"
    _write_model(staging, "orders.yml", GOLDEN_OSI)
    _write_model(staging, "customers.yml", CUSTOMERS_MODEL)
    assert validate_main([str(staging), "--db", str(db)]) == 0
    assert "grain audit" in capsys.readouterr().out
