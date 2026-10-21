"""Numerical semantic-correctness evals: golden entries + fan-out trap.

Golden entries (``tests/evals/golden.json``) cover the reference metrics in this
fixture. Expected values come from INDEPENDENT hand-written SQL (the two
seed-note rules are spelled out inline; plain customer-count SQL), never from
the seeder, fixture generator, or runtime. Each golden value is checked against
that SQL and private ``_QueryRuntimeSession.get_metric`` rows (tolerance 1e-6).
Public project admission is covered by the Git lifecycle tests, not this numeric
seam.

Artifact-fixture provenance: the eval snapshots ``semantic_layer/models`` and
``context_layer`` from the repo worktree copy into tmp, never a live directory
another process could mutate. Fresh checkouts may lack those gitignored files;
the fallback uses the recorded reference orders model plus the customers model
below. These are private numerical fixtures, not a public served-project claim.

Ad-hoc execution: "mean order amount per customer" under the revision-2
definition (spec 2026-09-23-0003): AVG of billable order amounts in USD per
``customer_id`` — CANCELLED/RETURNED excluded, pre-2024 EMEA amounts converted
via ``rate_to_usd`` — through ``define_metric``: governed false, every
customer ID checked against independent SQL, and no durable artifact created.

Fan-out disposition (spec rev 5 §13, upstream finding Datus-ai/Datus-agent#1426:
the datus compiler aggregated at joined-row grain and did NOT prevent fan-out;
spec rev 7 §8.18: our own sqlglot renderer keeps the joined-row-grain semantics
BY DESIGN and the facade owns the invariant through the grain guard):
three tests over the trap fixture (``tests/evals/build_trap_fixture.py``,
orders 1:N order_lines, deduplicated totals NA 300 / EMEA 400):

1. **Guard**: a naive fanned source through ``define_metric`` is REJECTED by the
facade grain guard (grain-preservation invariant) before compile or execution.
2. **Sanctioned shape**: pre-aggregating the many side to the fact grain inside
   source (``GROUP BY order_id``) passes the guard and returns the correct
   deduplicated totals.
3. **Renderer behavior (rev 7, ADR-0008)**: the own sqlglot compiler aggregates
   at joined-row grain BY DESIGN — executing the rendered trap SQL yields the
   INFLATED totals (NA 700 / EMEA 400), and the guard is what keeps that number
   unservable (rejection test 1). Replaces the rev 5 strict xfail sentinel.
"""

import asyncio
import contextlib
import json
import shutil
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports]
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MONOREPO_ROOT = Path(__file__).resolve().parents[3]  # examples/, ariadne-agent/ stay root-resident
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.query import _QueryRuntimeSession as Facade  # noqa: E402
from ariadne.render import render  # noqa: E402  # pyright: ignore[reportMissingImports]
from tests.test_seed import run_seed  # noqa: E402
from tests.test_serve import GOLDEN_OKF, GOLDEN_OSI  # noqa: E402

TOLERANCE = 1e-6
GOLDEN = json.loads((REPO_ROOT / "tests" / "evals" / "golden.json").read_text())

# Reference customers model used by the private numerical fixture. Values are
# independently verified on the synthetic demo.db: 30 overall, exactly 3 per country.
CUSTOMERS_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: customers
    description: Customers master data
    datasets:
      - name: customers
        source: >-
          SELECT id, name, country FROM demo.main.customers
        primary_key: [id]
        fields:
          - name: customer_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: customer_name
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: name
          - name: country
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: country
            dimension: {}
    metrics:
      - name: customer_count
        description: Count of customers in the master data
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

_REGION_METRICS = {"gross_margin", "gross_revenue", "cogs", "order_count"}


def _load_trap_builder():
    """Load tests/evals/build_trap_fixture.py by path (same pattern test_serve.py
    uses for examples/retail-demo/seed_db.py — no package machinery needed)."""
    import importlib.util

    path = Path(__file__).resolve().parent / "evals" / "build_trap_fixture.py"
    spec = importlib.util.spec_from_file_location("ariadne_evals_build_trap_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_trap = _load_trap_builder().build


@contextlib.contextmanager
def attached_demo(db_path: Path):
    """Fresh duckdb connection with the attach the facade mirrors: the SQLite
    file read-only as catalog ``demo`` (project/research/datus-spike.md §4).
    db_path is the test's own tmp path; ATTACH takes no bind parameters."""
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{db_path}' AS demo (TYPE SQLITE, READ_ONLY)")  # nosemgrep
        yield con
    finally:
        con.close()


def independent_expected(db_path: Path, metric: str, dimensions: list[str]) -> dict:
    """Expected values from INDEPENDENT hand-written SQL (the two OKF rules are
    spelled out inline below — the same discipline as tests/test_seed.py; the
    seeder's logic is never reused), keyed like the facade rows (dimension
    value, or "ALL" for the overall/no-dimensions shape)."""
    with attached_demo(db_path) as con:
        if metric == "customer_count" and not dimensions:
            row = con.execute("SELECT COUNT(*) FROM demo.customers").fetchone()
            assert row is not None
            return {"ALL": row[0]}
        if metric == "customer_count":  # by country
            rows = con.execute(
                "SELECT country, COUNT(*) FROM demo.customers GROUP BY country"
            ).fetchall()
            return {name: count for name, count in rows}
        if dimensions == ["region"] and metric in _REGION_METRICS:
            # Column order: region, order_count, gross_revenue, cogs, gross_margin.
            column = ["order_count", "gross_revenue", "cogs", "gross_margin"].index(metric)
            rows = con.execute(
                """
                WITH converted AS (
                    SELECT
                        o.region_code AS region,
                        CASE
                            WHEN o.region_code = 'EMEA'
                                 AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                                THEN o.amount * r.rate_to_usd
                            ELSE o.amount
                        END AS amount_usd,
                        CASE
                            WHEN o.region_code = 'EMEA'
                                 AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                                THEN o.product_cost * r.rate_to_usd
                            ELSE o.product_cost
                        END AS cost_usd
                    FROM demo.orders o
                    LEFT JOIN demo.currency_conversion_rate r ON r.currency = o.currency
                    WHERE o.status NOT IN ('CANCELLED', 'RETURNED')
                )
                SELECT
                    region,
                    COUNT(*) AS order_count,
                    SUM(amount_usd) AS gross_revenue,
                    SUM(cost_usd) AS cogs,
                    (SUM(amount_usd) - SUM(cost_usd)) / NULLIF(SUM(amount_usd), 0)
                        AS gross_margin
                FROM converted
                GROUP BY region
                ORDER BY region
                """
            ).fetchall()
            return {row[0]: row[1 + column] for row in rows}
    raise AssertionError(f"no independent SQL wired for {metric!r} by {dimensions!r}")


def assert_close(actual, expected, where: str) -> None:
    assert abs(actual - expected) <= TOLERANCE, f"{where}: {actual} != {expected}"


def resolve_served(served: Path) -> Path:
    """Snapshot the reference layers from the worktree copy into tmp (never
    point the numerical eval at a live directory another process could mutate).
    Fresh checkouts reconstruct the recorded reference orders and customers
    models — see module docstring."""
    models_dst = served / "semantic_layer" / "models"
    models_dst.mkdir(parents=True)
    (served / "context_layer").mkdir(parents=True)
    models_src = MONOREPO_ROOT / "examples" / "retail-demo" / "semantic_layer" / "models"
    context_src = MONOREPO_ROOT / "examples" / "retail-demo" / "context_layer"
    if models_src.is_dir():
        shutil.copytree(models_src, models_dst, dirs_exist_ok=True)
        if context_src.is_dir():
            shutil.copytree(context_src, served / "context_layer", dirs_exist_ok=True)
    else:
        models_dst.joinpath("orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
        models_dst.joinpath("customers.yml").write_text(CUSTOMERS_MODEL, encoding="utf-8")
        pages = served / "context_layer" / "metrics"
        pages.mkdir(parents=True)
        pages.joinpath("gross_margin.md").write_text(GOLDEN_OKF, encoding="utf-8")
    return served


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("evals") / "demo.db"
    run_seed(db_path)  # examples/retail-demo/seed_db.py into tmp (subprocess), as in test_seed
    return db_path


@pytest.fixture(scope="module")
def facade(tmp_path_factory, demo_db) -> Facade:
    served = resolve_served(tmp_path_factory.mktemp("served"))
    return Facade(served / "semantic_layer", served / "context_layer", demo_db)


@pytest.mark.parametrize(
    "entry",
    [e for e in GOLDEN["entries"] if not e.get("adhoc")],
    ids=lambda e: f"{e['metric']}:{'+'.join(e['dimensions']) or 'overall'}",
)
def test_golden_entry(entry, facade, demo_db):
    """Facade output == independent SQL == baked golden value; governed: true."""
    result = asyncio.run(facade.get_metric(entry["metric"], entry["dimensions"] or None))
    assert result["governed"] is True  # spec §8.10 symmetry
    assert result["sql"].strip().upper().startswith("SELECT")  # provenance present

    dimensions = entry["dimensions"]
    actual = {
        (row[dimensions[0]] if dimensions else "ALL"): row[result["metric"]]
        for row in result["rows"]
    }
    expected_sql = independent_expected(demo_db, entry["metric"], dimensions)
    expected_golden = entry["expected"] if dimensions else {"ALL": entry["expected"]}

    assert set(actual) == set(expected_sql) == set(expected_golden), (
        f"row keys mismatch: facade={sorted(actual)} sql={sorted(expected_sql)} "
        f"golden={sorted(expected_golden)}"
    )
    for name in actual:
        assert_close(actual[name], expected_sql[name], f"{entry['metric']}/{name} facade vs SQL")
        assert_close(
            expected_golden[name], expected_sql[name], f"{entry['metric']}/{name} golden vs SQL"
        )


# --- Ad-hoc round trip (spec 2026-09-23-0003 rev 2 USD/customer_id oracle) ----

ADHOC_ENTRY = next(e for e in GOLDEN["entries"] if e.get("adhoc"))

# The proposal under test (rev 2): source converts billable amounts to USD
# (seed-note rule 2), the expression averages them per customer_id — the
# definition an agent authors after list_datasets, not a served metric.
_JOIN_SOURCE = (
    "SELECT o.customer_id, o.status, "
    "CASE WHEN o.region_code = 'EMEA' AND o.order_timestamp::TIMESTAMP"
    " < TIMESTAMP '2024-01-01' THEN o.amount * r.rate_to_usd"
    " ELSE o.amount END AS amount_usd "
    "FROM orders o LEFT JOIN currency_conversion_rate r ON r.currency = o.currency"
)
_MEAN_EXPR = "AVG(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount_usd END)"


# --- Independent ad-hoc oracle (shared; spec 2026-09-23-0003 rev 2) ------------

# Seed-note rules 1+2 spelled out inline in a CTE — a different formulation than
# the proposal's CASE-in-AVG; never the seeder, the generator, the facade, or an
# observed run. The one numeric oracle for the ad-hoc mean anywhere (its former
# consumer, the recorded agent-trace check, was retired 2026-10-12 — real-world
# checks run manually). One statement returns both grains:
# one row per customer_id plus a NULL-keyed overall row.
_ADHOC_MEAN_SQL = """
WITH converted AS (
    SELECT
        o.customer_id AS customer_id,
        CASE
            WHEN o.region_code = 'EMEA'
                 AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                THEN o.amount * r.rate_to_usd
            ELSE o.amount
        END AS amount_usd
    FROM demo.orders o
    LEFT JOIN demo.currency_conversion_rate r ON r.currency = o.currency
    WHERE o.status NOT IN ('CANCELLED', 'RETURNED')
)
SELECT customer_id, AVG(amount_usd) AS mean_usd FROM converted GROUP BY customer_id
UNION ALL
SELECT NULL, AVG(amount_usd) FROM converted
"""


def independent_adhoc_means(db_path: Path) -> dict:
    """Rev-2 ad-hoc oracle: mean billable order amount in USD per customer_id,
    the same measure ungrouped, and every customer id in the master data."""
    per_customer: dict = {}
    overall = None
    with attached_demo(db_path) as con:
        # nosemgrep — module-level constant SQL, no interpolation or tool input
        for customer_id, mean_usd in con.execute(_ADHOC_MEAN_SQL).fetchall():
            if customer_id is None:
                overall = mean_usd
            else:
                per_customer[customer_id] = mean_usd
        ids = [r[0] for r in con.execute("SELECT id FROM demo.customers").fetchall()]
    assert overall is not None
    return {"per_customer": per_customer, "overall": overall, "customer_ids": ids}


def test_adhoc_evaluation_is_ephemeral(facade, demo_db):
    definition = {
        "name": ADHOC_ENTRY["metric"],
        "description": "Mean billable order amount per customer in USD",
        "source": _JOIN_SOURCE,
        "expression": _MEAN_EXPR,
        "dimensions": ADHOC_ENTRY["dimensions"],
    }
    result = asyncio.run(facade.define_metric(dict(definition)))
    assert result["governed"] is False
    assert result["sql"]  # provenance SQL present
    assert result["definition"]["source"] == _JOIN_SOURCE  # echoed definition
    assert result["persistence"] == {"status": "not_saved"}
    assert "staged_as" not in result and "staged_context_as" not in result

    oracle = independent_adhoc_means(demo_db)
    expected = oracle["per_customer"]
    actual = {row["customer_id"]: row[ADHOC_ENTRY["metric"]] for row in result["rows"]}
    assert set(actual) == set(expected) == set(oracle["customer_ids"]), (
        "every customer ID in the demo must appear with a billable-order mean"
    )
    for customer_id, value in actual.items():
        assert_close(value, expected[customer_id], f"mean per customer {customer_id}")


# --- Fan-out disposition (spec rev 5 §13, Datus-ai/Datus-agent#1426) ----------

# The trap source: orders 1:N order_lines, join key NOT unique on the joined side.
FANNED_SOURCE = (
    "SELECT o.order_id, o.region, o.amount, l.line_amount "
    "FROM orders o JOIN order_lines l ON l.order_id = o.order_id"
)
# The sanctioned shape: pre-aggregate the many side to the fact grain, THEN join.
PREAGG_SOURCE = (
    "SELECT o.order_id, o.region, o.amount, l.line_total "
    "FROM orders o JOIN "
    "(SELECT order_id, SUM(line_amount) AS line_total FROM order_lines GROUP BY order_id) l "
    "ON l.order_id = o.order_id"
)
# The many-to-one SERVED model: lines joined to orders on the orders PK — the
# sanctioned direction (join key unique on the joined side), the governed-path
# counterpart of PREAGG_SOURCE (same trap.db, both directions on one fixture).
LINES_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: lines_many_to_one
    description: Lines joined many-to-one to orders (sanctioned direction)
    datasets:
      - name: lines_join
        source: >-
          SELECT l.line_id, o.region, l.line_amount
          FROM demo.main.order_lines l
          JOIN demo.main.orders o ON o.order_id = l.order_id
        primary_key: [line_id]
        fields:
          - name: line_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_id
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
      - name: sanctioned_lines_total
        description: SUM of line amounts over the many-to-one join
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""


@pytest.fixture()
def trap_facade(tmp_path):
    """A live facade over the trap fixture (orders 1:N order_lines, trap.db).
    Deduplicated ground truth: NA 300, EMEA 400; the naive join would inflate."""
    served = build_trap(tmp_path)
    return Facade(served / "semantic", served / "context", served / "trap.db")


def test_define_metric_rejects_fanout_source(trap_facade, monkeypatch):
    """The naive fanned source is rejected before compile or execution."""

    async def _must_not_be_reached(*args, **kwargs):  # compile/execute never reached
        raise AssertionError("guard must reject before the compile gate")

    monkeypatch.setattr(Facade, "_compile_adhoc", _must_not_be_reached)
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            trap_facade.define_metric(
                {
                    "name": "orders_total_naive",
                    "description": "the trap: SUM over the naive join",
                    "source": FANNED_SOURCE,
                    "expression": "SUM(amount)",
                    "dimensions": ["region"],
                }
            )
        )


def test_define_metric_accepts_preaggregated_one_to_many(trap_facade):
    """§13 disposition (sanctioned shape): pre-aggregating the many side to the
    fact grain inside source (GROUP BY) passes the guard and returns the
    DEDUPLICATED totals — NA 300 / EMEA 400, never the inflated 700/400."""
    result = asyncio.run(
        trap_facade.define_metric(
            {
                "name": "orders_total_preagg",
                "description": "deduplicated order total via pre-aggregated lines",
                "source": PREAGG_SOURCE,
                "expression": "SUM(amount)",
                "dimensions": ["region"],
            }
        )
    )
    assert result["governed"] is False
    assert result["persistence"] == {"status": "not_saved"}
    actual = {row["region"]: row["orders_total_preagg"] for row in result["rows"]}
    assert actual == pytest.approx({"NA": 300.0, "EMEA": 400.0})


def test_renderer_aggregates_at_joined_row_grain_and_guard_rejects_fanout(tmp_path, trap_facade):
    """§8.18 renderer-behavior test (replaces the rev 5 strict xfail sentinel).
    Our own sqlglot compiler (ADR-0008) aggregates at JOINED-ROW grain BY DESIGN:
    over a fanned dataset source the rendered SQL returns the INFLATED totals
    (NA 700 / EMEA 400 — order 1 counted 3x, order 2 2x), never the deduplicated
    NA 300 / EMEA 400. This is the same mechanism upstream Datus exhibited
    (Datus-ai/Datus-agent#1426), now owned in-repo: the facade's grain guard
    rejects fanned sources BEFORE compile (spec rev 5 §13 disposition), so the
    inflated aggregate is unreachable through define_metric — asserted live on
    the trap facade below."""
    served = build_trap(tmp_path)
    envelope = yaml.safe_load(
        (served / "semantic" / "models" / "trap.yml").read_text(encoding="utf-8")
    )
    sql = render(envelope, ["region"], metric="orders_total")
    # BY DESIGN: the aggregate runs over the joined rows as-is — no compile-time
    # deduplication; the grain guard (not the compiler) owns that invariant.
    assert "SUM(amount)" in sql and "DISTINCT" not in sql.upper()
    with attached_demo(served / "trap.db") as con:
        rows = con.sql(sql).fetchall()  # sql is render() compile output (spec §6)
    assert {region: total for region, total in rows} == pytest.approx(
        {"NA": 700.0, "EMEA": 400.0}
    ), "renderer must aggregate at joined-row grain (INFLATED), by design — "
    "the grain guard keeps it unservable"

    # The same fanned source through the facade is rejected before compile.
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(
            trap_facade.define_metric(
                {
                    "name": "orders_total_naive",
                    "description": "the trap: SUM over the naive join",
                    "source": FANNED_SOURCE,
                    "expression": "SUM(amount)",
                    "dimensions": ["region"],
                }
            )
        )


def test_get_metric_rejects_served_model_with_fanned_source(trap_facade):
    """Correction-pass reachability (the reviewer's exact path): the governed
    get_metric gauntlet — render -> single-statement guard -> EXPLAIN bind-check
    -> grain guard — rejects a SERVED model whose dataset source bakes in the
    fan-out (trap.yml, orders ⋈ order_lines) with the grain guidance. The
    inflated joined-row total (NA 700) is unservable through the facade, not
    just through define_metric."""
    with pytest.raises(ValueError, match="grain-preservation invariant"):
        asyncio.run(trap_facade.get_metric("orders_total", ["region"]))


def test_get_metric_answers_served_model_with_many_to_one_source(tmp_path):
    """The governed gauntlet's upside: a served model whose source joins
    many-to-one (order_lines ⋈ orders on the orders PK — unique on the joined
    side) still answers through get_metric: the deduplicated line totals
    NA 300 / EMEA 400, with provenance SQL and governed: true."""
    served = build_trap(tmp_path)
    (served / "semantic" / "models" / "lines.yml").write_text(LINES_MODEL, encoding="utf-8")
    facade = Facade(served / "semantic", served / "context", served / "trap.db")
    result = asyncio.run(facade.get_metric("sanctioned_lines_total", ["region"]))
    assert result["governed"] is True
    assert result["sql"].strip().upper().startswith("SELECT")
    actual = {row["region"]: row["sanctioned_lines_total"] for row in result["rows"]}
    assert actual == pytest.approx({"NA": 300.0, "EMEA": 400.0})
