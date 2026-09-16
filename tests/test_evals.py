"""Semantic-correctness eval harness (spec rev 5 §13): golden entries + fan-out trap.

Golden entries (``tests/evals/golden.json``) cover every currently served governed
metric. Expected values are derived at run time by INDEPENDENT hand-written SQL
(the two seed-note rules spelled out inline; plain customer-count SQL) — never
from the seeder, the fixture generator, or the facade. Each golden entry is
asserted three ways: baked golden.json values == independent SQL == facade
``get_metric`` rows (tolerance 1e-6), with ``governed: true``.

Served-set provenance: the eval snapshots ``semantic_layer/models`` and
``context_layer`` from the REPO WORKTREE COPY into tmp (never a live dir another
process could mutate). Both are gitignored and may be absent from a fresh
checkout — the sanctioned fallback reconstructs the served set from the recorded
rev-4 golden orders model (``tests/test_serve.py`` GOLDEN_OSI, execution-verified
against the hand-computed fixture) plus the verbatim promoted customers model
below, supplied by the orchestrator from the currently served tree (nothing in
git records it; the canonical ``tests/evals/served/`` reference copy lands in a
later lane). Documented in the lane report.

Ad-hoc round trip: the canonical rev-3 acceptance definition — "mean order
amount per customer" — through ``define_metric``: governed false, rows checked
against independent SQL, the proposal staged, staging cleaned up afterwards.

Fan-out disposition (spec rev 5 §13, upstream finding Datus-ai/Datus-agent#1426:
the compiler aggregates at joined-row grain and does NOT prevent fan-out):
three tests over the trap fixture (``tests/evals/build_trap_fixture.py``,
orders 1:N order_lines, deduplicated totals NA 300 / EMEA 400):

1. **Guard**: a naive fanned source through ``define_metric`` is REJECTED by the
   facade grain guard (grain-preservation invariant) — nothing staged, nothing
   compiled, nothing executed.
2. **Sanctioned shape**: pre-aggregating the many side to the fact grain inside
   source (``GROUP BY order_id``) passes the guard and returns the correct
   deduplicated totals.
3. **Sentinel**: the original compiler-grain mechanism assertion (the governed
   path must deduplicate) is kept as a STRICT xfail — an upstream fix would
   XPASS and fail the suite, forcing this disposition to be revisited.
"""

import asyncio
import contextlib
import json
import shutil
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.serve import Facade  # noqa: E402
from tests.test_seed import run_seed  # noqa: E402
from tests.test_serve import GOLDEN_OKF, GOLDEN_OSI  # noqa: E402

TOLERANCE = 1e-6
GOLDEN = json.loads((REPO_ROOT / "tests" / "evals" / "golden.json").read_text())

# Verbatim promoted customers model (semantic_layer/models/customers.yml as
# currently served; provided by the orchestrator). Values verified live on the
# real demo.db: customer_count = 30 overall, exactly 3 per country.
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
    uses for scripts/seed_db.py — no package machinery needed)."""
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
    file read-only as catalog ``demo`` (docs/research/datus-spike.md §4).
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
    """Snapshot the currently served layers from the worktree copy into tmp
    (never point the eval at a live dir another process could mutate). Fresh
    checkouts (gitignored, absent) reconstruct from the recorded rev-4 golden
    orders model + the verbatim promoted customers model — see module docstring."""
    models_dst = served / "semantic_layer" / "models"
    models_dst.mkdir(parents=True)
    (served / "context_layer").mkdir(parents=True)
    models_src = REPO_ROOT / "semantic_layer" / "models"
    context_src = REPO_ROOT / "context_layer"
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
    run_seed(db_path)  # scripts/seed_db.py into tmp (subprocess), as in test_seed
    return db_path


@pytest.fixture(scope="module")
def facade(tmp_path_factory, demo_db) -> Facade:
    served = resolve_served(tmp_path_factory.mktemp("served"))
    return Facade(
        served / "semantic_layer",
        served / "context_layer",
        demo_db,
        staging_dir=tmp_path_factory.mktemp("staging"),
    )


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


# --- Ad-hoc round trip (the canonical rev-3 acceptance definition) ------------

ADHOC_ENTRY = next(e for e in GOLDEN["entries"] if e.get("adhoc"))

_JOIN_SOURCE = (
    "SELECT o.customer_id, c.name AS customer_name, o.amount, o.status "
    "FROM orders o JOIN customers c ON o.customer_id = c.id"
)
_MEAN_EXPR = "AVG(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount END)"


def test_adhoc_round_trip_stages_proposal_then_cleans_up(facade, demo_db):
    definition = {
        "name": ADHOC_ENTRY["metric"],
        "description": "Mean order amount per customer over billable orders",
        "source": _JOIN_SOURCE,
        "expression": _MEAN_EXPR,
        "dimensions": ADHOC_ENTRY["dimensions"],
    }
    staged: list[Path] = []
    try:
        result = asyncio.run(facade.define_metric(dict(definition)))
        assert result["governed"] is False
        assert result["sql"]  # provenance SQL present
        assert result["definition"]["source"] == _JOIN_SOURCE  # echoed definition
        staged_model = Path(result["staged_as"])
        staged_page = Path(result["staged_context_as"])
        assert staged_model.is_file() and staged_model.parent.name == "adhoc"
        assert staged_page.is_file()
        staged = [staged_model, staged_page]

        with attached_demo(demo_db) as con:
            rows = con.execute(
                "SELECT c.name, AVG(o.amount) FROM demo.orders o"
                " JOIN demo.customers c ON o.customer_id = c.id"
                " WHERE o.status NOT IN ('CANCELLED', 'RETURNED')"
                " GROUP BY c.name"
            ).fetchall()
        expected = {name: avg for name, avg in rows}
        actual = {row["customer_name"]: row[ADHOC_ENTRY["metric"]] for row in result["rows"]}
        assert set(actual) == set(expected), "every customer with billable orders must appear"
        for name, value in actual.items():
            assert_close(value, expected[name], f"mean per customer {name}")
    finally:
        for path in staged:
            path.unlink(missing_ok=True)  # clean it up after (spec §13)
    adhoc = Path(facade.staging_dir) / "semantic_layer" / "models" / "adhoc"
    assert not adhoc.exists() or not any(adhoc.iterdir()), "staging left dirty"


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


@pytest.fixture()
def trap_facade(tmp_path):
    """A live facade over the trap fixture (orders 1:N order_lines, trap.db).
    Deduplicated ground truth: NA 300, EMEA 400; the naive join would inflate."""
    served = build_trap(tmp_path)
    return Facade(
        served / "semantic",
        served / "context",
        served / "trap.db",
        staging_dir=served / "staging",
    )


def _assert_staging_clean(facade):
    adhoc = Path(facade.staging_dir) / "semantic_layer" / "models" / "adhoc"
    assert not adhoc.exists() or not any(adhoc.iterdir()), "staging left dirty"


def test_define_metric_rejects_fanout_source(trap_facade, monkeypatch):
    """§13 disposition (guard): the naive fanned source is rejected with the
    grain-preservation guidance BEFORE compile — nothing staged, nothing
    compiled, nothing executed. The compiler itself would inflate (sentinel
    below): the facade owns the invariant (Datus-ai/Datus-agent#1426)."""

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
    _assert_staging_clean(trap_facade)


def test_define_metric_accepts_preaggregated_one_to_many(trap_facade):
    """§13 disposition (sanctioned shape): pre-aggregating the many side to the
    fact grain inside source (GROUP BY) passes the guard and returns the
    DEDUPLICATED totals — NA 300 / EMEA 400, never the inflated 700/400."""
    staged: list[Path] = []
    try:
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
        staged = [Path(result["staged_as"]), Path(result["staged_context_as"])]
        assert result["governed"] is False
        actual = {row["region"]: row["orders_total_preagg"] for row in result["rows"]}
        assert actual == pytest.approx({"NA": 300.0, "EMEA": 400.0})
    finally:
        for path in staged:
            path.unlink(missing_ok=True)  # clean it up after (spec §13)
    _assert_staging_clean(trap_facade)


@pytest.mark.xfail(
    strict=True, reason="Datus-ai/Datus-agent#1426 — compiler aggregates at joined-row grain"
)
def test_governed_compiler_dedupes_fanout(tmp_path):
    """§13 sentinel: the original trap assertion against the COMPILER itself.
    Strict xfail — if upstream ever deduplicates at fact grain, this XPASSes and
    fails the suite, forcing the guard disposition (spec §13, docs) to be
    revisited. Today it fails INFLATED: NA 700 (order 1 counted 3x, order 2 2x)."""
    served = build_trap(tmp_path)
    trap = Facade(
        served / "semantic",
        served / "context",
        served / "trap.db",
        staging_dir=served / "staging",
    )
    orders_total = asyncio.run(trap.get_metric("orders_total", ["region"]))
    assert orders_total["governed"] is True
    actual = {row["region"]: row["orders_total"] for row in orders_total["rows"]}
    assert actual == pytest.approx({"NA": 300.0, "EMEA": 400.0}), (
        f"FAN-OUT VERDICT: INFLATED — orders_total over the naive join is {actual}"
    )
    # The immune sibling: line sums are correct even under the naive join.
    lines_total = asyncio.run(trap.get_metric("lines_total", ["region"]))
    assert {row["region"]: row["lines_total"] for row in lines_total["rows"]} == pytest.approx(
        {"NA": 300.0, "EMEA": 400.0}
    )
