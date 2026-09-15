"""Authoring agent loop (ticket #4): profile + seed notes -> LLM draft -> staging/.

LLM responses are fixture-mocked (no network); validation is injected as a fake
so the loop, error feedback, staging-path safety, and review_needed marking are
tested in isolation. Real Datus compilation is covered by tests/test_validate.py.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.author import MAX_ROUNDS, author, main  # noqa: E402
from ariadne.validate import ValidationResult  # noqa: E402

GOTCHA_1 = "CANCELLED and RETURNED orders are not revenue"
GOTCHA_2 = "multiply both figures by rate_to_usd"

OKF_PAGE = f"""---
type: metric
status: draft
sources:
  - orders
  - currency_conversion_rate
---

# Gross margin

Rule 1: {GOTCHA_1}.
Rule 2: pre-2024 EMEA rows are local currency: {GOTCHA_2}.
"""

OSI_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders
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
    metrics:
      - name: gross_margin
        description: margin
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: (gross_revenue - cogs) / NULLIF(gross_revenue, 0)
        custom_extensions:
          - vendor_name: DATUS
            data: '{"metric_kind":"derived","inputs":["gross_revenue","cogs"]}'
      - name: order_count
        description: count
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN orders.status NOT IN ('CANCELLED', 'RETURNED')
                            THEN 1 ELSE 0 END)
"""


def make_demo_db(db_path: Path) -> Path:
    """Miniature demo.db: same schema as scripts/seed_db.py."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
                order_timestamp TEXT NOT NULL, status TEXT NOT NULL,
                region_code TEXT NOT NULL, currency TEXT NOT NULL,
                amount REAL NOT NULL, product_cost REAL NOT NULL);
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL);
            CREATE TABLE currency_conversion_rate (
                currency TEXT PRIMARY KEY, rate_to_usd REAL NOT NULL);
            INSERT INTO customers VALUES (1, 'C1', 'US'), (2, 'C2', 'DE');
            INSERT INTO currency_conversion_rate VALUES ('EUR', 1.10), ('GBP', 1.27);
            INSERT INTO orders VALUES
                (1, 1, '2023-05-01 10:00:00', 'COMPLETED', 'EMEA', 'EUR', 100.0, 60.0),
                (2, 2, '2024-05-01 10:00:00', 'COMPLETED', 'NA', 'USD', 200.0, 80.0),
                (3, 1, '2024-06-01 10:00:00', 'CANCELLED', 'APAC', 'USD', 300.0, 90.0);
            """
        )
        con.commit()
    finally:
        con.close()
    return db_path


def make_notes(tmp_path: Path) -> Path:
    notes = tmp_path / "seed_notes.md"
    notes.write_text(
        f"# Seed notes\n\n1. {GOTCHA_1}.\n"
        f"2. Pre-2024 EMEA rows are unconverted local currency: {GOTCHA_2}.\n",
        encoding="utf-8",
    )
    return notes


def llm_response() -> str:
    return json.dumps(
        {
            "files": [
                {"path": "context_layer/metrics/gross_margin.md", "content": OKF_PAGE},
                {"path": "semantic_layer/models/orders.yml", "content": OSI_MODEL},
            ]
        }
    )


def thinking_llm_response() -> str:
    """Reasoning models inline <think> blocks in content before the JSON."""
    return "<think>Let me draft the files...</think>" + llm_response()


def fake_complete(responses: list[str]):
    """Return (complete_fn, calls); complete_fn replays responses, last one repeats."""
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return responses[min(len(calls), len(responses)) - 1]

    return complete, calls


def fake_validate(results: list[ValidationResult]):
    """Return (validate_fn, calls); validate_fn replays results, last one repeats."""
    calls: list[Path] = []

    def validate(staging_dir):
        calls.append(Path(staging_dir))
        return results[min(len(calls), len(results)) - 1]

    return validate, calls


def staged(staging: Path) -> dict[str, Path]:
    return {str(p.relative_to(staging)): p for p in staging.rglob("*") if p.is_file()}


def run_author_rounds(tmp_path: Path, complete, validate_fn, *, staging=None, rounds=MAX_ROUNDS):
    staging = staging if staging is not None else tmp_path / "staging"
    return author(
        make_demo_db(tmp_path / "demo.db"),
        make_notes(tmp_path),
        staging_dir=staging,
        complete=complete,
        validate_fn=validate_fn,
        rounds=rounds,
    )


def run_author(tmp_path: Path, complete, validate_fn):
    staging = tmp_path / "staging"
    paths = run_author_rounds(tmp_path, complete, validate_fn, staging=staging)
    return staging, paths


def test_author_success_round1_writes_okf_and_osi(tmp_path):
    complete, complete_calls = fake_complete([llm_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging, paths = run_author(tmp_path, complete, validate_fn)

    files = staged(staging)
    md = files["context_layer/metrics/gross_margin.md"]
    yml = files["semantic_layer/models/orders.yml"]
    assert md in paths and yml in paths
    assert len(complete_calls) == 1  # passed on the first round

    front = yaml.safe_load(md.read_text().split("---")[1])
    assert front["type"] and front["status"] and front["sources"]
    body = md.read_text()
    assert GOTCHA_1 in body and GOTCHA_2 in body  # both seed-note gotchas carried

    model = yaml.safe_load(yml.read_text())
    assert model["version"] == "0.2.0.dev0"
    sm = model["semantic_model"][0]
    assert sm["name"] == "orders"
    assert sm["datasets"][0]["primary_key"] == ["order_id"]
    metrics = {m["name"] for m in sm["metrics"]}
    assert {"gross_margin", "order_count"} <= metrics


def test_author_parses_reasoning_model_response(tmp_path):
    complete, complete_calls = fake_complete([thinking_llm_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging, _ = run_author(tmp_path, complete, validate_fn)

    assert len(complete_calls) == 1
    assert "context_layer/metrics/gross_margin.md" in staged(staging)


def test_author_rejects_rounds_above_spec_cap(tmp_path):
    complete, complete_calls = fake_complete([llm_response()])
    validate_fn, validate_calls = fake_validate([ValidationResult(True, [])])
    with pytest.raises(ValueError, match="hard cap of 3"):
        run_author_rounds(tmp_path, complete, validate_fn, rounds=MAX_ROUNDS + 1)
    assert complete_calls == [] and validate_calls == []  # rejected before any round ran


def test_author_cli_rejects_rounds_above_spec_cap(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--db", str(tmp_path / "demo.db"), "--notes", "x", "--rounds", "4"])
    assert excinfo.value.code == 2
    assert "hard cap" in capsys.readouterr().err  # clear error, never silently clamped


def test_author_rejects_repo_root_as_staging(tmp_path):
    complete, complete_calls = fake_complete([llm_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    with pytest.raises(ValueError, match="repo root"):
        run_author_rounds(tmp_path, complete, validate_fn, staging=Path.cwd())
    assert complete_calls == []  # guard fires before any LLM call, nothing written


def test_author_rejects_served_layer_as_staging(tmp_path):
    db, notes = make_demo_db(tmp_path / "demo.db"), make_notes(tmp_path)
    complete, _ = fake_complete([llm_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    for layer in ("context_layer", "semantic_layer"):
        with pytest.raises(ValueError, match="served"):
            author(
                db, notes, staging_dir=tmp_path / layer, complete=complete, validate_fn=validate_fn
            )


def test_author_rejects_served_layer_descendant_as_staging(tmp_path):
    """Regression (review round 2): --staging context_layer/nested must be
    rejected — writing beneath a served root bypasses the promotion gate."""
    from ariadne.author import _REPO_ROOT

    db, notes = make_demo_db(tmp_path / "demo.db"), make_notes(tmp_path)
    complete, complete_calls = fake_complete([llm_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    for layer in ("context_layer", "semantic_layer"):
        with pytest.raises(ValueError, match="inside the served layer"):
            author(
                db,
                notes,
                staging_dir=_REPO_ROOT / layer / "nested",
                complete=complete,
                validate_fn=validate_fn,
            )
    assert complete_calls == []  # guard fires before any LLM call


def test_author_cli_rejects_repo_root_staging(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--db", "x", "--notes", "y", "--staging", "."])
    assert excinfo.value.code == 2
    assert "spec §6" in capsys.readouterr().err  # the invariant is named in the error


def test_author_never_writes_outside_staging(tmp_path):
    escape = json.dumps(
        {"files": [{"path": "../escape.md", "content": "no"}]}
    )
    complete, _ = fake_complete([escape])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    with pytest.raises(ValueError, match="staging"):
        run_author(tmp_path, complete, validate_fn)
    assert not (tmp_path / "escape.md").exists()
    assert staged(tmp_path / "staging") == {}


def test_author_error_feedback_marks_review_needed_after_three_rounds(tmp_path):
    complete, complete_calls = fake_complete([llm_response()])
    errors = ["error: Metric `gross_margin` references unknown column `nope`"]
    validate_fn, _ = fake_validate([ValidationResult(False, errors)])
    staging, _ = run_author(tmp_path, complete, validate_fn)

    assert len(complete_calls) == 3  # three failed rounds, then stop
    feedback = complete_calls[1][-1]["content"]
    assert "unknown column `nope`" in feedback  # compiler error fed back

    for path in staged(staging).values():
        text = path.read_text()
        assert "review_needed" in text
    front = yaml.safe_load(
        staged(staging)["context_layer/metrics/gross_margin.md"].read_text().split("---")[1]
    )
    assert front["status"] == "review_needed"
    assert any("nope" in e for e in front["review_errors"])


def test_author_second_round_recovers(tmp_path):
    complete, complete_calls = fake_complete([llm_response()])
    validate_fn, _ = fake_validate(
        [ValidationResult(False, ["boom"]), ValidationResult(True, [])]
    )
    staging, _ = run_author(tmp_path, complete, validate_fn)

    assert len(complete_calls) == 2
    front = yaml.safe_load(
        staged(staging)["context_layer/metrics/gross_margin.md"].read_text().split("---")[1]
    )
    assert front["status"] == "draft"  # recovered, not marked


def staged_page(staging: Path, status: str) -> Path:
    page = staging / "context_layer" / "metrics" / "gross_margin.md"
    page.parent.mkdir(parents=True)
    page.write_text(OKF_PAGE.replace("status: draft", f"status: {status}"), encoding="utf-8")
    return page


def test_main_exits_nonzero_when_staged_review_needed(tmp_path, monkeypatch):
    import ariadne.author as author_module

    page = staged_page(tmp_path / "staging", "review_needed")
    monkeypatch.setattr(author_module, "author", lambda *args, **kwargs: [page])
    code = author_module.main(["--db", "x", "--notes", "y", "--staging", str(tmp_path / "s")])
    assert code == 1  # spec §6/§7: review_needed artifacts must not look promotable


def test_main_exits_zero_when_staged_clean(tmp_path, monkeypatch):
    import ariadne.author as author_module

    page = staged_page(tmp_path / "staging", "draft")
    monkeypatch.setattr(author_module, "author", lambda *args, **kwargs: [page])
    code = author_module.main(["--db", "x", "--notes", "y", "--staging", str(tmp_path / "s")])
    assert code == 0
