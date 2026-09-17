"""Renderer unit tests per metric kind (spec rev 7 §8.18, ADR-0008).

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
    spec: dict = {
        "name": name,
        "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": expression}]},
    }
    if dimension is not None:
        spec["dimension"] = dimension
    return spec


def _metric(name: str, expression: str, datus_derived: bool = False) -> dict:
    spec: dict = {
        "name": name,
        "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": expression}]},
    }
    if datus_derived:  # the authoring contract's derived-metric marker (author.py)
        spec["custom_extensions"] = [
            {"vendor_name": "DATUS", "data": '{"metric_kind":"derived","inputs":[]}'}
        ]
    return spec


def _model(metrics: list[dict], fields: list[dict], source: str = "demo.main.orders") -> dict:
    return {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {
                "name": "orders",
                "description": "test model",
                "datasets": [
                    {"name": "orders", "source": source, "primary_key": ["order_id"],
                     "fields": fields}
                ],
                "metrics": metrics,
            }
        ],
    }


GOLDEN_FIELDS = [
    _field("order_date", "CAST(order_timestamp AS DATE)", {"is_time": True}),
    _field("status", "status", {}),
    _field("region", "region_code", {}),
    _field("amount", "amount"),
    _field("fx_rate", "fx_rate"),
]
GOLDEN_METRICS = [
    _metric("gross_revenue", "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') "
                             "THEN amount * fx_rate ELSE 0 END)"),
    _metric("cogs", "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') "
                    "THEN product_cost * fx_rate ELSE 0 END)"),
    _metric("gross_margin", "(gross_revenue - cogs) / NULLIF(gross_revenue, 0)",
            datus_derived=True),
]
GOLDEN_MODEL = _model(GOLDEN_METRICS, GOLDEN_FIELDS)


# --- Aggregate metrics --------------------------------------------------------


def test_aggregate_metric_renders_inner_group_by():
    sql = render(GOLDEN_MODEL, ["region"], metric="gross_revenue")
    assert sql.upper().startswith("SELECT")
    assert "AS gross_revenue" in sql
    assert "FROM (SELECT * FROM demo.main.orders)" in sql  # bare source wrapped
    assert "GROUP BY region" in sql
    assert sql.count("(") == sql.count(")")  # balanced — it is one statement


def test_field_alias_resolution_uses_the_field_expression():
    """Expressions referencing fields resolve through the dataset's alias ->
    expression mapping: the region dimension groups on region_code, and a metric
    expression referencing `region` inlines its field expression too."""
    fields = GOLDEN_FIELDS + [_field("amount", "amount")]
    model = _model([_metric("emea_count", "SUM(CASE WHEN region = 'EMEA' THEN 1 ELSE 0 END)")],
                   fields)
    sql = render(model, ["region"])
    assert "region_code AS region" in sql
    assert "CASE WHEN region_code = 'EMEA' THEN 1 ELSE 0 END" in sql


def test_qualified_column_refs_are_stripped():
    """The wrapped source knows no scan aliases — `orders.amount` must lower to a
    bare column (the datus lowering contract the served models rely on)."""
    model = _model([_metric("total", "SUM(orders.amount)")], GOLDEN_FIELDS)
    assert "SUM(amount) AS total" in render(model, [])


# --- Derived metrics ----------------------------------------------------------


def test_derived_metric_nests_one_level():
    """The DATUS-derived metric becomes an outer SELECT over the inner aggregate
    of its inputs (the golden served shape)."""
    sql = render(GOLDEN_MODEL, ["region"], metric="gross_margin")
    assert "(gross_revenue - cogs) / NULLIF(gross_revenue, 0) AS gross_margin" in sql
    assert "AS gross_revenue" in sql and "AS cogs" in sql  # inputs computed inner
    # source wrapper + inner aggregate + derived outer = 3 SELECT statements
    assert sql.upper().count("SELECT") == 3


def test_derived_metric_resolves_two_levels_recursively():
    """N-level resolution: c = b * 2, b = a + 1, a = SUM(x) -> three stacked
    SELECT statements, and EXECUTING the rendered SQL pins the values (14, not shape)."""
    model = _model(
        [
            _metric("a", "SUM(x)"),
            _metric("b", "a + 1", datus_derived=True),
            _metric("c", "b * 2", datus_derived=True),
        ],
        [_field("x", "x")],
        source="t",
    )
    sql = render(model, [], metric="c")
    # source wrapper + inner aggregate + two derived levels = 4 SELECT statements
    assert sql.upper().count("SELECT") == 4
    assert "AS a" in sql and "AS b" in sql and "AS c" in sql

    con = duckdb.connect()
    try:
        con.execute("CREATE OR REPLACE TABLE t AS SELECT * FROM (VALUES (1), (2), (3)) v(x)")
        row = con.sql(sql).fetchone()  # sql is render() compile output (spec §6)
        assert row is not None
        assert row[0] == 14  # (SUM(x) + 1) * 2 = (6 + 1) * 2 — resolved recursively
    finally:
        con.close()


def test_metric_cycle_is_detected_and_named():
    cycle_model = _model(
        [
            _metric("a", "b + 1"),
            _metric("b", "a + 1"),
        ],
        [_field("x", "x")],
    )
    with pytest.raises(ValueError, match="metric dependency cycle: a -> b -> a"):
        render(cycle_model, [])


def test_unknown_metric_and_dimension_errors():
    with pytest.raises(ValueError, match="unknown metric 'nope'; available metrics"):
        render(GOLDEN_MODEL, [], metric="nope")
    with pytest.raises(ValueError, match="unknown dimension 'currency'; available dimensions"):
        render(GOLDEN_MODEL, ["currency"])


def test_unparsable_expression_carries_the_verbatim_reason():
    model = _model([_metric("broken", "SUM((")], GOLDEN_FIELDS)
    with pytest.raises(ValueError, match="could not parse expression"):
        render(model, [])


def test_missing_source_and_field_expression_are_compile_errors():
    with pytest.raises(ValueError, match="missing source"):
        render(_model([_metric("m", "COUNT(*)")], GOLDEN_FIELDS, source="   "), [])
    broken = _model([_metric("m", "COUNT(*)")], [{"name": "x", "expression": {}}])
    with pytest.raises(ValueError, match="no usable dialect expression"):
        render(broken, [])


# --- DATUS extension hint (datus-spike.md §6.6 parity) ------------------------


def test_malformed_datus_extension_data_is_a_compile_error():
    model = _model([_metric("m", "COUNT(*)")], GOLDEN_FIELDS)
    model["semantic_model"][0]["metrics"][0]["custom_extensions"] = [
        {"vendor_name": "DATUS", "data": '{"metric_kind":broken}'}
    ]
    with pytest.raises(ValueError, match="not valid JSON"):
        render(model, [])


def test_stray_datus_extension_key_is_a_compile_error():
    model = _model([_metric("m", "COUNT(*)")], GOLDEN_FIELDS)
    model["semantic_model"][0]["metrics"][0]["custom_extensions"] = [
        {"vendor_name": "DATUS", "data": '{"v": "1", "metric_kind": "derived"}'}
    ]
    with pytest.raises(ValueError, match="unsupported DATUS extension hint keys: v"):
        render(model, [])


# --- time_range ----------------------------------------------------------------


def test_time_range_predicate_on_the_is_time_field():
    sql = render(GOLDEN_MODEL, ["region"], {"start": "2025-01-01", "end": "2025-06-30"},
                 metric="gross_revenue")
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
