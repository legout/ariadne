"""Authoring agent loop (ticket #4): profile + seed notes -> LLM draft -> staging/.

LLM responses are fixture-mocked (no network); validation is injected as a fake
so the loop, error feedback, staging-path safety, and review_needed marking are
tested in isolation. Real Datus compilation is covered by tests/test_validate.py.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.author import (  # noqa: E402
    _SYSTEM_PROMPT,
    MAX_ROUNDS,
    _bundle_errors,
    _user_prompt,
    author,
    main,
)
from ariadne.validate import ValidationResult  # noqa: E402

GOTCHA_1 = "CANCELLED and RETURNED orders are not revenue"
GOTCHA_2 = "multiply both figures by rate_to_usd"

OKF_PAGE = f"""---
type: metric
status: draft
title: Gross margin
description: Gross margin over billable orders.
tags: [metric, margin]
sources:
  - orders
  - currency_conversion_rate
  - {{id: order-status-billing, resource: policies/order-status-billing.md}}
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
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
            dimension: {}
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
    """Miniature demo.db: same schema as examples/retail-demo/seed_db.py."""
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
    """Whole-bundle response: the ADR-0007 bundle gate rejects incomplete trees,
    so even the basic fixture carries all six content types (metrics page from
    OKF_PAGE, the rest from the bundle constants below)."""
    return json.dumps(
        {
            "files": [
                {"path": "context_layer/metrics/gross_margin.md", "content": OKF_PAGE},
                {"path": "semantic_layer/models/orders.yml", "content": OSI_MODEL},
                {"path": "context_layer/tables/orders.md", "content": BUNDLE_TABLE},
                {
                    "path": "context_layer/references/joins/orders--customers.md",
                    "content": BUNDLE_JOIN,
                },
                {
                    "path": "context_layer/policies/order-status-billing.md",
                    "content": BUNDLE_POLICY,
                },
                {"path": "context_layer/skills/run-the-demo.md", "content": BUNDLE_SKILL},
            ]
        }
    )


def partial_response() -> str:
    """Valid OSI but an INCOMPLETE context layer (one page, no tables/joins/
    policies/skills) — the shape that used to return silent success before the
    ADR-0007 bundle gate."""
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


BUNDLE_METRIC = """---
type: metric
status: draft
title: Gross Margin
description: Ratio of gross profit to gross revenue over billable orders.
tags: [metric, margin]
sources:
  - id: demo.main.orders
    resource: examples/retail-demo/data/demo.db
    title: Orders
  - id: order-status-billing
    resource: policies/order-status-billing.md
    title: Order status billing
  - id: emea-currency-cutover
    resource: policies/emea-currency-cutover.md
    title: EMEA currency cutover
---

# Gross margin

Rule 1: {GOTCHA_1}. Rule 2: {GOTCHA_2}.
"""

BUNDLE_TABLE = """---
type: table
status: draft
title: Orders
description: One row per placed order.
tags: [table, orders]
sources:
  - id: demo.main.orders
    resource: examples/retail-demo/data/demo.db
    title: Orders
grain:
  primary_key: [order_id]
  cardinality_enforcement: STRICT_1_TO_1
---

# Orders

Join hints: customer_id -> customers.id (N:1).
"""

BUNDLE_JOIN = """---
type: reference
status: draft
title: Orders to Customers
description: Many orders to one customer; the joined key is proven unique.
tags: [reference, join]
sources:
  - id: demo.main.customers
    resource: examples/retail-demo/data/demo.db
    title: Customers
---

# Orders <-> Customers

Grain-safety: many-to-one from the fact side, per ADR-0006 the join is
grain-preserving (joined side unique, no fan-out).
"""

BUNDLE_POLICY = """---
type: policy
status: draft
title: Order status billing
description: Cancelled and returned orders are not revenue.
tags: [policy, billing]
sources:
  - id: seed-notes
    resource: examples/retail-demo/seed_notes.md
    title: Seed notes
---

# Order status billing

{GOTCHA_1}.
"""

BUNDLE_SKILL = """---
type: skill
status: draft
title: Run the demo
description: End-to-end demo via examples/retail-demo/demo.sh.
tags: [skill, demo]
sources:
  - id: demo-script
    resource: examples/retail-demo/demo.sh
    title: demo.sh
---

# Run the demo

cd examples/retail-demo && python seed_db.py data/demo.db && ./demo.sh
"""


def bundle_response() -> str:
    """ONE mock LLM round producing the whole OKF bundle plus the models."""
    return json.dumps(
        {
            "files": [
                {"path": "context_layer/metrics/gross_margin.md", "content": BUNDLE_METRIC},
                {"path": "context_layer/tables/orders.md", "content": BUNDLE_TABLE},
                {
                    "path": "context_layer/references/joins/orders--customers.md",
                    "content": BUNDLE_JOIN,
                },
                {
                    "path": "context_layer/policies/order-status-billing.md",
                    "content": BUNDLE_POLICY,
                },
                {"path": "context_layer/skills/run-the-demo.md", "content": BUNDLE_SKILL},
                {"path": "semantic_layer/models/orders.yml", "content": OSI_MODEL},
            ]
        }
    )


def front_of(page: Path) -> dict:
    return yaml.safe_load(page.read_text().split("---")[1])


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
    escape = json.dumps({"files": [{"path": "../escape.md", "content": "no"}]})
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
    validate_fn, _ = fake_validate([ValidationResult(False, ["boom"]), ValidationResult(True, [])])
    staging, _ = run_author(tmp_path, complete, validate_fn)

    assert len(complete_calls) == 2
    front = yaml.safe_load(
        staged(staging)["context_layer/metrics/gross_margin.md"].read_text().split("---")[1]
    )
    assert front["status"] == "draft"  # recovered, not marked


def test_author_incomplete_bundle_never_succeeds(tmp_path):
    """ADR-0007 bundle hard gate: valid OSI plus a partial context layer (one
    metric page) must enter round feedback — never return silent success — and
    end in the spec §7 review_needed marking."""
    complete, complete_calls = fake_complete([partial_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging, _ = run_author(tmp_path, complete, validate_fn)

    assert len(complete_calls) == 3  # every round fed back; never a success
    feedback = complete_calls[1][-1]["content"]
    assert "authored bundle is incomplete" in feedback
    assert "skills" in feedback  # the missing content type is named
    for path in staged(staging).values():  # 3 failed rounds -> spec §7 marking
        assert "review_needed" in path.read_text()


def test_author_drops_index_and_log_from_llm_writes(tmp_path):
    """Code-level enforcement: an LLM round that adds index.md/log.md must have
    those writes dropped — bundle bookkeeping belongs to the promotion gate."""
    data = json.loads(llm_response())
    data["files"] = [
        {"path": "context_layer/index.md", "content": "# hijacked index"},
        {"path": "context_layer/log.md", "content": "# hijacked log"},
        *data["files"],
    ]
    complete, _ = fake_complete([json.dumps(data)])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging, _ = run_author(tmp_path, complete, validate_fn)

    assert not list(staging.rglob("index.md"))
    assert not list(staging.rglob("log.md"))
    assert "context_layer/metrics/gross_margin.md" in staged(staging)  # the rest landed


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


def test_main_explicit_db_beats_ambient_registry(tmp_path, monkeypatch):
    """With an ambient ./ariadne.yaml present, an explicit --db still wins: the
    registry applies only when NEITHER --sources nor --db is given."""
    import ariadne.author as author_module

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: missing.db\n",
        encoding="utf-8",
    )
    seen = {}

    def spy(db_path, notes, **kwargs):
        seen["db"] = db_path
        seen["sources_path"] = kwargs.get("sources_path")
        return []

    monkeypatch.setattr(author_module, "author", spy)
    code = author_module.main(["--db", "x.db", "--notes", "y", "--staging", str(tmp_path / "s")])
    assert code == 0
    assert seen == {"db": "x.db", "sources_path": None}


def test_author_invalid_page_frontmatter_feeds_back_then_recovers(tmp_path):
    """An LLM page whose frontmatter is not valid YAML (unquoted colon) must
    feed back through the loop — not crash the deterministic post-passes."""
    bad_response = bundle_response().replace(
        "title: Order status billing", "title: Policy: order status billing"
    )  # unquoted colon -> invalid YAML frontmatter
    good_complete, complete_calls = fake_complete([bad_response, bundle_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging = tmp_path / "staging"
    author(
        make_demo_db(tmp_path / "demo.db"),
        make_notes(tmp_path),
        staging_dir=staging,
        complete=good_complete,
        validate_fn=validate_fn,
    )
    assert len(complete_calls) == 2  # round 1 rejected, round 2 recovered
    front = front_of(staged(staging)["context_layer/policies/order-status-billing.md"])
    assert front["title"] == "Order status billing"  # round-2 page, stamped cleanly
    assert front["status"] == "draft"
    assert front["generated"]["by"] == "ariadne-author"


def run_bundle_author(tmp_path: Path):
    """Author with one mocked whole-bundle round (spec rev 6 §8.15)."""
    complete, complete_calls = fake_complete([bundle_response()])
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging, paths = run_author(tmp_path, complete, validate_fn)
    assert len(complete_calls) == 1  # the whole bundle passed in one round
    return staging, paths


# --- rev 9 Lane B: the author input carries the multi-source catalog ----------

TICKETS_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: tickets
    description: Support tickets model over the parquet source
    datasets:
      - name: tickets
        source: support.tickets
        primary_key: [ticket_id]
        fields:
          - name: ticket_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: ticket_id
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
            dimension: {}
          - name: severity
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: severity
            dimension: {}
          - name: resolution_hours
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: resolution_hours
    metrics:
      - name: ticket_count
        description: Number of support tickets
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
      - name: avg_resolution_hours
        description: Mean resolution hours over closed tickets (open are NULL)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: AVG(resolution_hours)
"""

SUPPORT_TABLE_PAGE = """\
---
type: table
status: draft
title: Support tickets
description: One row per support ticket (parquet source).
tags: [table, tickets, support]
sources:
  - id: support.tickets
    resource: examples/retail-demo/data/support_tickets
    title: Support tickets
grain:
  primary_key: [ticket_id]
  cardinality_enforcement: STRICT_1_TO_1
---

# Support tickets

One row per ticket; resolution_hours is NULL while status is open.
"""

SUPPORT_METRIC_PAGE = """\
---
type: metric
status: draft
title: {title}
description: {desc}
tags: [metric, support]
sources:
  - id: support.tickets
    resource: examples/retail-demo/data/support_tickets
    title: Support tickets
  - id: open-tickets-no-resolution
    resource: policies/open-tickets-no-resolution.md
    title: Open tickets have no resolution time
---

# {title}

Rule: open tickets have no resolution time.
"""

OPEN_TICKETS_POLICY = """\
---
type: policy
status: draft
title: Open tickets have no resolution time
description: resolution_hours is NULL while a ticket is open.
tags: [policy, support]
sources:
  - id: seed-notes
    resource: examples/retail-demo/seed_notes.md
    title: Seed notes
---

# Open tickets have no resolution time

Every average-resolution number excludes open tickets.
"""


MINIMAL_ORDERS_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model over the demo sqlite source
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
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
            dimension: {}
    metrics:
      - name: order_count
        description: Count of billable orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN 1 ELSE 0 END)
"""


def make_support_parquet(tmp_path: Path) -> Path:
    """Miniature support-tickets parquet source, one shard per year (rev 9)."""
    support_dir = tmp_path / "support_tickets"
    support_dir.mkdir()
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE tickets (ticket_id INTEGER, customer_id INTEGER, "
            "status TEXT, severity TEXT, created_at TEXT, resolution_hours DOUBLE)"
        )
        con.executemany(
            "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, 1, "closed", "low", "2024-02-01 09:00:00", 30.0),
                (2, 2, "open", "high", "2024-03-01 10:00:00", None),
                (3, 1, "closed", "high", "2025-01-15 11:00:00", 5.0),
                (4, 3, "closed", "low", "2025-02-15 12:00:00", 48.0),
            ],
        )
        for year, predicate in (
            ("2024", "created_at < '2025-01-01'"),
            ("2025", "created_at >= '2025-01-01'"),
        ):
            con.execute(
                f"COPY (SELECT * FROM tickets WHERE {predicate}) "
                f"TO '{support_dir / f'tickets_{year}.parquet'}' (FORMAT PARQUET)"
            )
    finally:
        con.close()
    return support_dir


def make_registry(tmp_path: Path, db_path: Path, support_dir: Path) -> Path:
    """Two-source registry: the demo sqlite plus a parquet glob view."""
    registry = tmp_path / "ariadne.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {"name": "demo", "type": "sqlite", "path": str(db_path)},
                    {
                        "name": "support",
                        "type": "parquet",
                        "path": str(support_dir / "*.parquet"),
                        "table": "tickets",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return registry


def run_multisource_author(tmp_path: Path, response: str, validate_fn=None):
    """One author run over the sqlite+parquet registry with a mocked LLM."""
    db = make_demo_db(tmp_path / "demo.db")
    registry = make_registry(tmp_path, db, make_support_parquet(tmp_path))
    complete, complete_calls = fake_complete([response])
    staging = tmp_path / "staging"
    paths = author(
        db,
        make_notes(tmp_path),
        staging_dir=staging,
        complete=complete,
        validate_fn=validate_fn,
        sources_path=registry,
    )
    return staging, paths, complete_calls


def test_author_prompt_carries_multisource_catalog(tmp_path):
    """With a registry, the prompt input lists BOTH sources' catalogs (source
    names, types, qualified tables) alongside profile and seed notes."""
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    complete_calls = run_multisource_author(tmp_path, bundle_response(), validate_fn=validate_fn)[2]

    system, prompt = complete_calls[0][0]["content"], complete_calls[0][1]["content"]
    assert "demo (sqlite)" in prompt
    assert "support (parquet)" in prompt
    assert "demo.main.orders" in prompt  # sqlite attaches keep the full qualifier
    assert "support.tickets" in prompt  # the glob view is addressable
    # the profile itself is the registry shape covering both sources
    assert '"sources"' in prompt and '"tickets"' in prompt
    # the binding instruction is catalog-driven, not hardcoded to demo.main
    assert "<source>.<table>" in system and "demo.main.orders" in system
    assert "Multi-source catalog" in prompt


def test_author_envelope_may_reference_parquet_source(tmp_path):
    """Envelopes may reference ANY catalog source: a model bound to
    support.tickets stages exactly like a demo.main one (fake gate)."""
    # prepend a tickets model to the bundle response (envelope bound to parquet)
    inject = json.dumps({"path": "semantic_layer/models/tickets.yml", "content": TICKETS_MODEL})
    response = bundle_response().replace('"files": [', '"files": [' + inject + ", ")
    validate_fn, _ = fake_validate([ValidationResult(True, [])])
    staging, _, complete_calls = run_multisource_author(tmp_path, response, validate_fn=validate_fn)

    assert len(complete_calls) == 1
    model = yaml.safe_load(staged(staging)["semantic_layer/models/tickets.yml"].read_text())
    assert model["semantic_model"][0]["datasets"][0]["source"] == "support.tickets"


def test_author_real_gate_accepts_envelopes_over_both_sources(tmp_path):
    """The DEFAULT gate (render + EXPLAIN bind + ADR-0006 grain audit) over the
    registry connection accepts a bundle whose models reference BOTH sources —
    governed metrics over a parquet glob view clear every deterministic gate."""
    response = json.dumps(
        {
            "files": [
                {"path": "semantic_layer/models/orders.yml", "content": MINIMAL_ORDERS_MODEL},
                {"path": "semantic_layer/models/tickets.yml", "content": TICKETS_MODEL},
                {"path": "context_layer/tables/orders.md", "content": BUNDLE_TABLE},
                {
                    "path": "context_layer/tables/tickets.md",
                    "content": SUPPORT_TABLE_PAGE,
                },
                {
                    "path": "context_layer/references/joins/orders--customers.md",
                    "content": BUNDLE_JOIN,
                },
                {
                    "path": "context_layer/policies/order-status-billing.md",
                    "content": BUNDLE_POLICY,
                },
                {
                    "path": "context_layer/policies/open-tickets-no-resolution.md",
                    "content": OPEN_TICKETS_POLICY,
                },
                {
                    "path": "context_layer/metrics/order_count.md",
                    "content": SUPPORT_METRIC_PAGE.format(
                        title="Order count", desc="Billable orders."
                    ),
                },
                {
                    "path": "context_layer/metrics/ticket_count.md",
                    "content": SUPPORT_METRIC_PAGE.format(
                        title="Ticket count", desc="All support tickets."
                    ),
                },
                {
                    "path": "context_layer/metrics/avg_resolution_hours.md",
                    "content": SUPPORT_METRIC_PAGE.format(
                        title="Average resolution hours",
                        desc="Mean resolution over closed tickets.",
                    ),
                },
                {
                    "path": "context_layer/skills/run-the-demo.md",
                    "content": BUNDLE_SKILL,
                },
            ]
        }
    )
    staging, paths, complete_calls = run_multisource_author(tmp_path, response)

    assert len(complete_calls) == 1, "the cross-source bundle must clear the gate"
    files = {path.relative_to(staging).as_posix() for path in paths}
    assert "semantic_layer/models/tickets.yml" in files
    # computations are generated for EVERY served metric, both sources included
    assert "context_layer/computations/ticket_count.md" in files
    assert "context_layer/computations/avg_resolution_hours.md" in files
    tickets_front = front_of(staged(staging)["context_layer/metrics/ticket_count.md"])
    assert tickets_front["governed_by"] == "semantic_layer tickets::ticket_count"
    assert tickets_front["dimensions"] == ["status", "severity"]  # sorted by serve order


def test_author_bundle_required_frontmatter_per_type(tmp_path):
    staging, _ = run_bundle_author(tmp_path)
    files = staged(staging)

    metric = front_of(files["context_layer/metrics/gross_margin.md"])
    for key in ("type", "status", "sources", "dimensions", "governed_by", "grain"):
        assert key in metric, f"metric frontmatter missing {key}"
    assert metric["type"] == "metric"
    # enriched mechanically FROM THE STAGED MODEL, not from the LLM response
    # (the fixture metric page carries none of these fields)
    assert metric["governed_by"] == "semantic_layer orders::gross_margin"
    assert metric["dimensions"] == ["status"]
    assert metric["grain"]["primary_key"] == ["order_id"]

    policy = front_of(files["context_layer/policies/order-status-billing.md"])
    for key in ("type", "status", "sources"):
        assert key in policy, f"policy frontmatter missing {key}"
    assert policy["type"] == "policy"

    table = front_of(files["context_layer/tables/orders.md"])
    assert table["grain"]["primary_key"] == ["order_id"]
    assert table["grain"]["cardinality_enforcement"] == "STRICT_1_TO_1"


def test_author_bundle_metric_sources_cite_policies(tmp_path):
    staging, _ = run_bundle_author(tmp_path)
    sources = front_of(staged(staging)["context_layer/metrics/gross_margin.md"])["sources"]
    cited = [str(s.get("resource")) for s in sources]
    assert any(r.startswith("policies/") for r in cited), "metrics must cite policy pages"


def test_author_generates_computations_per_served_metric(tmp_path):
    staging, _ = run_bundle_author(tmp_path)
    files = staged(staging)
    # one deterministic computation page per metric in the staged model
    assert "context_layer/computations/gross_margin.md" in files
    assert "context_layer/computations/order_count.md" in files
    comp = front_of(files["context_layer/computations/gross_margin.md"])
    assert comp["type"] == "computation"
    assert comp["governed_by"] == "semantic_layer orders::gross_margin"
    assert comp["runtime"] == "duckdb"
    assert comp["attester"] == "tests/test_evals.py"
    body = files["context_layer/computations/gross_margin.md"].read_text()
    assert "(gross_revenue - cogs) / NULLIF(gross_revenue, 0)" in body  # sanctioned SQL
    assert "ariadne get-metric" in body  # local-first execution pointer (#9, spec §8)
    assert "ariadne.serve" not in body  # no MCP-only operational wording


def test_authoring_contract_teaches_local_first_query_guide():
    """#9 (spec 2026-09-23-0001 §8): the authoring prompt drafts a local-first
    operational query guide citing the `ariadne` executable; MCP stays an
    optional extra and no authored bundle may claim it is required."""
    assert "query-artifacts" in _SYSTEM_PROMPT
    assert "query-via-mcp" not in _SYSTEM_PROMPT
    assert "local-first" in _SYSTEM_PROMPT
    user = _user_prompt({}, "seed notes", "- demo (sqlite): demo.main.orders")
    assert "ariadne list-metrics" in user and "ariadne get-metric" in user
    assert "ariadne define-metric --file" in user  # file/stdin ad-hoc definitions
    assert user.count("--sources examples/retail-demo/ariadne.yaml") == 6
    assert "--db examples/retail-demo/data/demo.db" not in user  # don't drop parquet sources
    assert (
        "ariadne search-context 'cancelled orders' --served examples/retail-demo "
        "--sources examples/retail-demo/ariadne.yaml "
        "--staging examples/retail-demo/staging"
    ) in user
    assert (
        "ariadne define-metric --file def.json --served examples/retail-demo "
        "--sources examples/retail-demo/ariadne.yaml "
        "--staging examples/retail-demo/staging"
    ) in user
    assert "--served examples/retail-demo" in user  # actual promoted-root location
    assert "--staging examples/retail-demo/staging --served examples/retail-demo" in user
    assert "--semantic examples/retail-demo/semantic_layer" in user
    assert "Optional MCP" in user and "ariadne-core[mcp]" in user  # accurate extra guidance


def test_author_stamps_lifecycle_frontmatter_and_never_indexes(tmp_path):
    staging, _ = run_bundle_author(tmp_path)
    for path in staged(staging).values():
        if path.suffix != ".md":
            continue
        front = front_of(path)
        assert front["generated"]["by"] == "ariadne-author"
        assert front["generated"]["at"]
        assert front["verified"] == []  # promotion appends the human verification
        assert front["stale_after"]
    # bundle bookkeeping belongs to promote.py — the author never writes them
    assert not list(staging.rglob("index.md"))
    assert not list(staging.rglob("log.md"))


# --- ADR-0007 bundle gate: every per-type required frontmatter field ----------

# A metric/computation page with the mechanically attached fields already in
# place (in the real loop _finalize_bundle stamps them before the gate runs).
GATED_METRIC_PAGE = """---
type: metric
status: draft
title: Gross Margin
description: Ratio of gross profit to gross revenue over billable orders.
tags: [metric, margin]
sources:
  - id: order-status-billing
    resource: policies/order-status-billing.md
    title: Order status billing
governed_by: semantic_layer orders::gross_margin
dimensions: [status]
grain:
  primary_key: [order_id]
  cardinality_enforcement: STRICT_1_TO_1
---

# Gross margin
"""

GATED_COMPUTATION_PAGE = """---
type: computation
status: draft
title: "sanctioned SQL — orders::gross_margin"
description: "Sanctioned computation: SQL, runtime, attester."
tags: [computation]
governed_by: semantic_layer orders::gross_margin
runtime: duckdb
attester: tests/test_evals.py
sources:
  - id: model-orders
    resource: ../../semantic_layer/models/orders.yml
    title: orders OSI model
---

# Sanctioned computation
"""

_COMPLETE_BUNDLE = {
    "tables": ("orders.md", BUNDLE_TABLE),
    "references/joins": ("orders--customers.md", BUNDLE_JOIN),
    "policies": ("order-status-billing.md", BUNDLE_POLICY),
    "metrics": ("gross_margin.md", GATED_METRIC_PAGE),
    "computations": ("gross_margin.md", GATED_COMPUTATION_PAGE),
    "skills": ("run-the-demo.md", BUNDLE_SKILL),
}


def write_complete_bundle(staging: Path) -> None:
    """A minimal gate-clean bundle: one complete page per ADR-0007 section."""
    for section, (name, content) in _COMPLETE_BUNDLE.items():
        page = staging / "context_layer" / section / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(content, encoding="utf-8")


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


def without_frontmatter_field(page: str, key: str) -> str:
    """The page with one top-level frontmatter field removed (gate test helper)."""
    match = _FRONTMATTER_RE.match(page)
    assert match, "fixture page must carry frontmatter"
    meta = yaml.safe_load(match.group(1))
    meta.pop(key, None)
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{match.group(2)}"


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("tables", "title"),
        ("tables", "description"),
        ("tables", "tags"),
        ("tables", "sources"),
        ("references/joins", "title"),
        ("references/joins", "description"),
        ("references/joins", "tags"),
        ("references/joins", "sources"),
        ("policies", "status"),
        ("policies", "title"),
        ("policies", "description"),
        ("policies", "tags"),
        ("policies", "sources"),
        ("metrics", "status"),
        ("metrics", "title"),
        ("metrics", "description"),
        ("metrics", "tags"),
        ("metrics", "sources"),
        ("metrics", "governed_by"),
        ("metrics", "dimensions"),
        ("metrics", "grain"),
        ("computations", "status"),
        ("computations", "title"),
        ("computations", "description"),
        ("computations", "tags"),
        ("computations", "sources"),
        ("computations", "governed_by"),
        ("computations", "runtime"),
        ("computations", "attester"),
        ("skills", "title"),
        ("skills", "description"),
        ("skills", "tags"),
        ("skills", "sources"),
    ],
)
def test_bundle_gate_rejects_each_missing_required_field(tmp_path, section, field):
    """mvp-5 round 2: the bundle gate enforces EVERY per-type required
    frontmatter field — a bundle missing exactly one required field on one page
    fails _bundle_errors with the missing field named (round feedback, never
    silent success)."""
    staging = tmp_path / "staging"
    write_complete_bundle(staging)
    assert _bundle_errors(staging) == []  # the complete bundle passes the gate

    page = next((staging / "context_layer" / section).glob("*.md"))
    page.write_text(
        without_frontmatter_field(page.read_text(encoding="utf-8"), field),
        encoding="utf-8",
    )
    errors = _bundle_errors(staging)
    assert errors, f"missing '{field}' on a {section} page must fail the bundle gate"
    assert any(f"'{field}'" in error for error in errors), errors
