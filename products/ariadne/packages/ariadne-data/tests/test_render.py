"""Renderer unit tests per metric kind (spec rev 7 §8.18, ADR-0008; Ossie 0.3 per spec 0039).

ariadne/render.py is the compile engine replacing datus-semantic-osi: aggregate
metrics in one inner GROUP BY, derived metrics resolved recursively (N levels)
with cycle detection, time_range predicates on the is_time field, and the
verbatim-error contract (RenderError is a ValueError). Every rendered SQL is
re-parsed (round-trip self-check); the N-level test additionally EXECUTES the
rendered SQL on DuckDB to pin the values, not just the shape.
"""

import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.render import render  # noqa: E402  # pyright: ignore[reportMissingImports]


def _field(name: str, expression: str, dimension: dict | None = None) -> dict:
    spec: dict = {"name": name, "expression": {"sql": expression}}
    if dimension is not None:
        spec["dimension"] = dimension
    return spec


def _metric(name: str, expression: str) -> dict:
    """A dataset-scoped metric: fields unqualified, source columns as source.<col>."""
    return {"name": name, "expression": {"sql": expression}}


def _model(
    metrics: list[dict],
    fields: list[dict],
    source: str = "demo.main.orders",
    derived: list[dict] | None = None,
) -> dict:
    """One Ossie 0.3 document: dataset ``orders`` owning ``metrics``; ``derived``
    are model-scoped AGG(orders.<metric>) compositions."""
    doc: dict = {
        "version": "0.3.0.dev0",
        "name": "orders",
        "description": "test model",
        "datasets": [
            {
                "name": "orders",
                "source": source,
                "primary_key": ["order_id"],
                "fields": [_field("order_id", "order_id"), *fields],
                "metrics": metrics,
            }
        ],
    }
    if derived:
        doc["metrics"] = derived
    return doc


GOLDEN_FIELDS = [
    _field("order_date", "CAST(order_timestamp AS DATE)", {"is_time": True}),
    _field("status", "status", {}),
    _field("region", "region_code", {}),
    _field("amount", "amount"),
    _field("fx_rate", "fx_rate"),
]
GOLDEN_METRICS = [
    _metric(
        "gross_revenue",
        "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount * fx_rate ELSE 0 END)",
    ),
    _metric(
        "cogs",
        "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') "
        "THEN source.product_cost * fx_rate ELSE 0 END)",
    ),
]
GOLDEN_DERIVED = [
    {
        "name": "gross_margin",
        "expression": {
            "sql": "(AGG(orders.gross_revenue) - AGG(orders.cogs)) / "
            "NULLIF(AGG(orders.gross_revenue), 0)"
        },
    }
]
GOLDEN_MODEL = _model(GOLDEN_METRICS, GOLDEN_FIELDS, derived=GOLDEN_DERIVED)


# --- Aggregate metrics --------------------------------------------------------


def test_aggregate_metric_renders_inner_group_by():
    sql = render(GOLDEN_MODEL, ["region"], metric="gross_revenue")
    assert sql.upper().startswith("SELECT")
    assert "AS gross_revenue" in sql
    assert "FROM (SELECT * FROM demo.main.orders)" in sql  # bare source wrapped
    assert "GROUP BY region" in sql
    assert sql.count("(") == sql.count(")")  # balanced — it is one statement


def test_field_expression_is_the_dimension_and_inlined_into_dataset_metrics():
    """A dimension groups on its field expression (region -> region_code) and a
    dataset-scoped metric referencing the field `region` inlines that expression."""
    model = _model(
        [_metric("emea_count", "SUM(CASE WHEN region = 'EMEA' THEN 1 ELSE 0 END)")],
        GOLDEN_FIELDS,
    )
    sql = render(model, ["region"])
    assert "region_code AS region" in sql
    assert "CASE WHEN region_code = 'EMEA' THEN 1 ELSE 0 END" in sql


def test_a_substituted_field_expression_keeps_its_grouping():
    """price = a + b, units = 2 over (a, b) = (5, 3): SUM(price * units) is
    (5 + 3) * 2 = 16 — in a dataset-scoped and in a model-scoped metric."""
    model = _model(
        [_metric("scoped", "SUM(price * units)")],
        [_field("price", "a + b"), _field("units", "units")],
        source="t",
    )
    model["metrics"] = [
        {"name": "model_scoped", "expression": {"sql": "SUM(orders.price * orders.units)"}}
    ]
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t AS SELECT 1 AS order_id, 5 AS a, 3 AS b, 2 AS units")
        sql = render(model, [])
        assert con.sql(sql).fetchall() == [(16, 16)]  # sql is render() compile output
    finally:
        con.close()


def test_a_metric_named_like_a_source_column_is_not_its_own_dependency(tmp_path):
    """`total = SUM(source.total)` has no field `total`: it is a plain measure.
    The served catalog loads, the metric compiles and answers 2 + 3 = 5, and a
    sibling metric still answers (row count 2)."""
    from ariadne.query import _QueryRuntimeSession

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "vals.csv").write_text("total\n2\n3\n", encoding="utf-8")
    models = tmp_path / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "m.yml").write_text(
        "version: 0.3.0.dev0\nname: m\ndatasets:\n- name: vals\n  source: vals.vals\n"
        "  fields:\n  - name: n\n    expression:\n      sql: total\n"
        "  metrics:\n  - name: total\n    expression:\n      sql: SUM(source.total)\n"
        "  - name: rows\n    expression:\n      sql: COUNT(*)\n",
        encoding="utf-8",
    )
    (tmp_path / "context_layer").mkdir()
    registry = tmp_path / "ariadne.yaml"
    registry.write_text(
        f"sources:\n  - name: vals\n    type: csv\n    path: {tmp_path / 'data' / 'vals.csv'}\n",
        encoding="utf-8",
    )
    runtime = _QueryRuntimeSession(
        models.parent, tmp_path / "context_layer", None, sources=str(registry)
    )
    try:
        spec, _alias = runtime._metric_slice("m::vals.total")
        cursor = runtime.con.sql(render(spec))  # sql is render() output
        row = dict(zip(cursor.columns, cursor.fetchall()[0]))
        assert row == {"rows": 2, "total": 5}
    finally:
        runtime.con.close()


def test_a_field_referencing_another_field_is_refused():
    """Ossie 0.3 (spec 0039 §5.3.1): a field expression names source columns only."""
    model = _model(
        [_metric("total", "SUM(alias2)")],
        [_field("alias1", "x"), _field("alias2", "alias1", {})],
        source="t",
    )
    with pytest.raises(ValueError, match="references field 'alias1'"):
        render(model, [])


@pytest.mark.parametrize(
    "dimensions,time_range,expected",
    [
        ([], {}, [(6,)]),
        (["alias2"], {}, [(1, 1), (2, 2), (3, 3)]),
        ([], {"start": "2025-01-02", "end": "2025-01-03"}, [(5,)]),
    ],
)
def test_fields_resolve_from_source_columns_in_all_clauses(dimensions, time_range, expected):
    # the table's alias1/day1 columns are decoys (100 / 1999): fields name SOURCE columns
    model = _model(
        [_metric("total", "SUM(alias2)")],
        [
            _field("alias2", "x", {}),
            _field("day2", "CAST(occurred AS DATE)", {"is_time": True}),
        ],
        source="t",
    )
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE t AS SELECT * FROM (VALUES "
            "(1, 100, DATE '2025-01-01', DATE '1999-01-01'), "
            "(2, 100, DATE '2025-01-02', DATE '1999-01-01'), "
            "(3, 100, DATE '2025-01-03', DATE '1999-01-01')) "
            "v(x, alias1, occurred, day1)"
        )
        rows = con.sql(render(model, dimensions, time_range, metric="total")).fetchall()
        assert sorted(rows) == expected


def test_source_column_reference_lowers_to_a_bare_column():
    """`source.amount` names the source column (spec metric scoping rule 2)."""
    model = _model([_metric("total", "SUM(source.amount)")], GOLDEN_FIELDS)
    assert "SUM(amount) AS total" in render(model, [])


# --- Derived metrics (model-scoped AGG compositions) -----------------------------


def test_derived_metric_nests_one_level():
    """A model-scoped AGG composition is an outer SELECT over the inner aggregates."""
    sql = render(GOLDEN_MODEL, ["region"], metric="gross_margin")
    assert 'NULLIF("gross_revenue", 0) AS gross_margin' in sql
    assert "AS gross_revenue" in sql and "AS cogs" in sql  # inputs computed inner
    # source wrapper + inner aggregate + derived outer = 3 SELECT statements
    assert sql.upper().count("SELECT") == 3


def test_derived_metric_composes_aggregates_and_executes():
    """(SUM(x) + 1) * 2 over x = 1, 2, 3 is (6 + 1) * 2 = 14."""
    model = _model(
        [_metric("a", "SUM(x)")],
        [_field("x", "x")],
        source="t",
        derived=[{"name": "c", "expression": {"sql": "(AGG(orders.a) + 1) * 2"}}],
    )
    sql = render(model, [], metric="c")
    assert sql.upper().count("SELECT") == 3
    con = duckdb.connect()
    try:
        con.execute("CREATE OR REPLACE TABLE t AS SELECT * FROM (VALUES (1), (2), (3)) v(x)")
        row = (con.sql(sql).fetchall() or [None])[0]  # sql is render() compile output (spec §6)
        assert row is not None
        assert row[0] == 14
    finally:
        con.close()


def test_governed_arithmetic_divides_truly_and_rounds_half_away_from_zero():
    """AC5, hand-worked: a = 2, 3 and b = 1, 1 give SUM(a) / SUM(b) = 5 / 2 = 2.5
    (true division of integer sums); ROUND(-2.5) = -3 and ROUND(2.5) = 3."""
    model = _model(
        [
            _metric("ratio", "SUM(a) / SUM(b)"),
            _metric("rounded_neg", "ROUND(SUM(n))"),
            _metric("rounded_pos", "ROUND(SUM(p))"),
        ],
        [_field("a", "a"), _field("b", "b"), _field("n", "n"), _field("p", "p")],
        source="t",
    )
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE t AS SELECT * FROM (VALUES (1, 2, 1, -2.5, 2.5), (2, 3, 1, 0.0, 0.0))"
            " v(order_id, a, b, n, p)"
        )
        sql = render(model, [])
        row = con.sql(sql).fetchall()[0]  # sql is render() compile output
        columns = [c[0] for c in con.sql(sql).description]
        assert dict(zip(columns, row)) == {"ratio": 2.5, "rounded_neg": -3.0, "rounded_pos": 3.0}
    finally:
        con.close()


def test_derived_metric_reusing_one_measure_twice_keeps_it_once():
    model = _model(
        [_metric("base", "SUM(x)")],
        [_field("x", "x")],
        source="t",
        derived=[
            {
                "name": "triple_base",
                "expression": {"sql": "AGG(orders.base) * 2 + AGG(orders.base)"},
            }
        ],
    )
    with duckdb.connect() as con:
        con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1), (2), (3)) v(x)")
        result = con.sql(render(model, metric="triple_base"))
        assert result.columns == ["triple_base"]
        assert result.fetchall() == [(18,)]  # (1 + 2 + 3) * 2 + (1 + 2 + 3)


def test_a_model_scoped_metric_cannot_reference_another_model_scoped_metric():
    """Metric -> metric other than AGG(dataset.metric) is refused (spec 0039 §5.3.5)."""
    model = _model(
        [_metric("a", "SUM(x)")],
        [_field("x", "x")],
        derived=[
            {"name": "b", "expression": {"sql": "AGG(orders.a) + 1"}},
            {"name": "c", "expression": {"sql": "b + 1"}},
        ],
    )
    with pytest.raises(ValueError, match="dataset.field"):
        render(model, [])


def test_unknown_metric_and_dimension_errors():
    with pytest.raises(ValueError, match="unknown metric 'nope'; available metrics"):
        render(GOLDEN_MODEL, [], metric="nope")
    with pytest.raises(ValueError, match="unknown dimension 'currency'; available dimensions"):
        render(GOLDEN_MODEL, ["currency"])


def test_unparsable_expression_carries_the_verbatim_reason():
    model = _model([_metric("broken", "SUM((")], GOLDEN_FIELDS)
    with pytest.raises(ValueError, match="could not parse expression"):
        render(model, [])


def test_a_field_without_an_expression_violates_the_pinned_schema():
    broken = _model([_metric("m", "COUNT(*)")], [{"name": "x", "expression": {}}])
    with pytest.raises(ValueError, match="violates the pinned Ossie 0.3.0.dev0 schema"):
        render(broken, [])


# --- time_range ----------------------------------------------------------------


def test_time_range_predicate_on_the_is_time_field():
    sql = render(
        GOLDEN_MODEL,
        ["region"],
        {"start": "2025-01-01", "end": "2025-06-30"},
        metric="gross_revenue",
    )
    assert "CAST(order_timestamp AS DATE) >= '2025-01-01'" in sql
    assert "CAST(order_timestamp AS DATE) <= '2025-06-30'" in sql
    assert "GROUP BY region" in sql  # predicate applies to the inner aggregate


def test_time_range_without_is_time_field_is_an_error():
    fields = [_field("region", "region_code", {}), _field("amount", "amount")]
    model = _model([_metric("total", "SUM(amount)")], fields)
    with pytest.raises(ValueError, match="time_range requires a field with dimension.is_time"):
        render(model, [], {"start": "2025-01-01"})


# --- Round-trip self-check ------------------------------------------------------


@pytest.mark.parametrize("metric", ["gross_revenue", "gross_margin", None])
def test_rendered_sql_round_trips_through_the_parser(metric):
    sql = render(GOLDEN_MODEL, ["region"], metric=metric)
    parsed = sqlglot.parse_one(sql)  # the renderer's own self-check, pinned here
    assert parsed is not None
    assert sqlglot.parse_one(sql).sql(dialect="duckdb")  # stable under re-render
