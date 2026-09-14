"""Deterministic validation via real Datus compile (ticket #4).

Compiles the spike-doc ``orders.yml`` variant adapted to OSI core per
docs/research/datus-spike.md §3.1: a valid model must pass (its one
authoring-quality lint is severity=warning, a pass-through), and a
deliberately broken model must fail with the compiler error captured for the
author loop's feedback. Requires datus-semantic-osi on Python 3.12.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.validate import main as validate_main  # noqa: E402
from ariadne.validate import validate  # noqa: E402

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
