"""Own sqlglot compiler for one dataset of an Ossie ``0.3.0.dev0`` model.

Renders one dataset slice — its ``source``, its fields (each an expression over
SOURCE columns, Ossie 0.3 never chains fields) and the metrics lowered to that
source (:mod:`ariadne.ossie`) — to a single SQL SELECT:

- the dataset source becomes a wrapped subquery (a bare table name is wrapped in
  ``SELECT * FROM ...``, a SELECT/WITH passes through parenthesized);
- measures (dataset-scoped metrics, and model-scoped aggregates over one
  dataset) compile into one inner ``SELECT dims..., measure AS name ... FROM
  (source) GROUP BY dims``;
- derived metrics (model-scoped compositions of ``AGG(dataset.metric)``) are
  evaluated one level above their measures, N levels deep, with explicit cycle
  detection that names the cycle;
- ``time_range`` ``{start, end}`` becomes a predicate on the dataset's time
  field, applied to the inner aggregate.

Compile failures — malformed model, unknown metric or dimension, metric cycle,
unparsable expression — raise :class:`RenderError`, a ``ValueError`` subclass,
whose message is the compiler's verbatim reason (the spec §7 / mvp-2
verbatim-error contract). The result is re-parsed with ``sqlglot.parse_one`` as
a self-check before it is returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports]

from ariadne import ossie  # pyright: ignore[reportMissingImports] — new-module resolver drift
from ariadne.query_results import (  # pyright: ignore[reportMissingImports] — drift
    classify_output_type,
)


class RenderError(ValueError):
    """Compiler failure; the message is the verbatim reason (spec §7 contract)."""


def _parse(sql: str, context: str) -> Any:  # sqlglot exp node; untyped alias per house style
    """Parse one SQL fragment; failure is a RenderError with the parser's reason."""
    try:
        return sqlglot.parse_one(sql)
    except Exception as exc:
        raise RenderError(
            f"could not parse expression for {context}: {type(exc).__name__}: {exc}"
        ) from exc


def _strip_qualifiers(tree):  # sqlglot exp node (runtime alias — not a static type)
    """Strip table qualifiers from every column — the wrapped source subquery
    knows no scan aliases (datus lowering parity; served models legitimately use
    qualified refs against the raw source, e.g. ``orders.amount``)."""
    for column in tree.find_all(exp.Column):
        column.set("table", None)
    return tree


@dataclass(frozen=True)
class Slice:
    """The single-dataset compile input: everything already lowered to the
    dataset's source columns. ``fields`` maps a field name to its source-level
    expression SQL, ``dimensions`` names the fields requests may group by,
    ``time_fields`` the fields a ``time_range`` predicates (first wins) and
    ``metrics`` maps an output name to its SQL — a measure over source columns,
    or a derived metric whose ``AGG(...)`` terms were replaced by the quoted
    output names of the metrics they consume (see :func:`build_slice`)."""

    source: str
    fields: dict[str, str]
    dimensions: frozenset[str]
    time_fields: tuple[str, ...]
    metrics: dict[str, str]
    name: str = "model"


def _agg_columns(sql: str, aliases: dict[str, str], context: str) -> str:
    """A derived metric's SQL with every ``AGG(dataset.metric)`` replaced by the
    quoted output name of the metric it consumes."""
    tree = _parse(sql, context)
    for call in list(tree.find_all(exp.Agg)):
        try:
            dataset, metric = ossie.agg_target(call, context)
        except ossie.OssieError as exc:
            raise RenderError(str(exc)) from exc
        alias = aliases.get(f"{dataset}.{metric}")
        if alias is None:
            raise RenderError(f"{context}: AGG({dataset}.{metric}) is not part of this slice")
        replacement = exp.column(alias, quoted=True)
        if call is tree:
            tree = replacement
        else:
            call.replace(replacement)
    return tree.sql()


def build_slice(
    model: ossie.ParsedModel,
    dataset: str,
    keys: list[str],
    aliases: dict[str, str] | None = None,
    extra_fields: dict[str, str] | None = None,
) -> Slice:
    """The slice of ``dataset`` carrying the metrics ``keys`` of ``model``.
    ``aliases`` maps a metric key to its output name (default: the key);
    ``extra_fields`` adds synthetic dimension fields (conformed time keys)."""
    node = model.datasets[dataset]
    names = {key: (aliases or {}).get(key, key) for key in keys}
    metrics: dict[str, str] = {}
    for key in keys:
        metric = model.metrics[key]
        if metric.derived:
            metrics[names[key]] = _agg_columns(metric.expression, names, f"metric {key!r}")
        else:
            metrics[names[key]] = metric.expression
    fields = {name: f.sql for name, f in node.fields.items()}
    # every declared field can group a result (the compiler never required the
    # optional ``dimension`` marker); ``dimension`` only drives discovery listings
    dimensions = set(node.fields)
    for name, sql in (extra_fields or {}).items():
        fields[name] = sql
        dimensions.add(name)
    return Slice(
        source=node.source,
        fields=fields,
        dimensions=frozenset(dimensions),
        time_fields=tuple(name for name, f in node.fields.items() if f.is_time),
        metrics=metrics,
        name=model.name,
    )


def slice_of(model: Any) -> Slice:
    """The compile input of ``model``: a :class:`Slice`, or one Ossie document /
    parsed model with exactly one dataset (every metric of that dataset and the
    model-scoped metrics over it, keyed by their identity key)."""
    if isinstance(model, Slice):
        return model
    if isinstance(model, dict):
        try:
            model = ossie.parse_model(ossie.validate_document(model, "model"), "model")
        except ossie.OssieError as exc:
            raise RenderError(str(exc)) from exc
    if not isinstance(model, ossie.ParsedModel):
        raise RenderError("model must be an Ossie document (dict)")
    if len(model.datasets) != 1:
        raise RenderError(
            f"model {model.name!r}: render compiles exactly one dataset, got {len(model.datasets)}"
        )
    (dataset,) = model.datasets
    keys = [k for k, m in model.metrics.items() if m.owner in (dataset, None)]
    if not keys:
        raise RenderError(f"model {model.name!r}: no metrics to render")
    shorts = [model.metrics[k].name for k in keys]
    aliases = {k: model.metrics[k].name for k in keys if shorts.count(model.metrics[k].name) == 1}
    return build_slice(model, dataset, keys, aliases=aliases)


def _source_subquery(source: str, context: str) -> exp.Subquery:
    """The dataset source as a FROM-able wrapped subquery (same discipline as
    validate's audit wrapper: bare table refs get a SELECT, SELECT/WITH pass
    through parenthesized). Exactly ONE statement is accepted — a crafted source
    smuggling DDL past the parser is rejected here, before any execution
    (no-unvalidated-execution invariant)."""
    if re.match(r"(?is)\s*(select|with)\b", source):
        statements = sqlglot.parse(source)
    else:
        statements = sqlglot.parse(f"(SELECT * FROM {source})")
    if len(statements) != 1 or statements[0] is None:
        raise RenderError(
            f"{context} must be exactly one statement, got {len(statements)} "
            "(no-unvalidated-execution invariant, spec §6)"
        )
    node = statements[0]
    if isinstance(node, exp.Subquery):
        return node
    return exp.Subquery(this=node)


def _metric_references(tree, metric_names: set[str]) -> set[str]:
    """Metric names referenced by an expression (columns that name a metric)."""
    return {column.name for column in tree.find_all(exp.Column)} & metric_names


def _metric_levels(metric_sqls: dict[str, str]) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Dependency level per metric (0 = aggregate) plus the dependency map.
    Recursive resolution with explicit cycle detection naming the cycle."""
    parsed: dict[str, Any] = {
        name: _strip_qualifiers(_parse(sql, f"metric {name!r}"))
        for name, sql in metric_sqls.items()
    }
    metric_names = set(metric_sqls)
    deps = {name: _metric_references(tree, metric_names) for name, tree in parsed.items()}
    levels: dict[str, int] = {}

    def visit(name: str, stack: list[str]) -> int:
        if name in levels:
            return levels[name]
        if name in stack:
            cycle = stack[stack.index(name) :] + [name]
            raise RenderError(f"metric dependency cycle: {' -> '.join(cycle)}")
        stack.append(name)
        level = 0
        for dep in sorted(deps[name]):
            level = max(level, visit(dep, stack) + 1)
        stack.pop()
        levels[name] = level
        return level

    for name in sorted(metric_sqls):
        visit(name, [])
    return levels, deps


def _closure(name: str, deps: dict[str, set[str]]) -> set[str]:
    """The metric and its transitive metric dependencies."""
    needed: set[str] = set()
    frontier = [name]
    while frontier:
        current = frontier.pop()
        if current in needed:
            continue
        needed.add(current)
        frontier.extend(deps.get(current, ()))
    return needed


def _time_predicate(spec: Slice, time_range: dict) -> Any | None:
    """``{start, end}`` -> predicate on the dataset's time field (inclusive)."""
    start = time_range.get("start")
    end = time_range.get("end")
    if start is None and end is None:
        return None
    if not spec.time_fields:
        raise RenderError(
            "time_range requires a field with dimension.is_time: true on the model's dataset"
        )
    field_expr = _strip_qualifiers(_parse(spec.fields[spec.time_fields[0]], "time field"))
    conditions: list[Any] = []
    if start is not None:
        conditions.append(
            exp.GTE(this=field_expr.copy(), expression=exp.Literal.string(str(start)))
        )
    if end is not None:
        conditions.append(exp.LTE(this=field_expr.copy(), expression=exp.Literal.string(str(end))))
    predicate = conditions[0]
    for condition in conditions[1:]:
        predicate = exp.And(this=predicate, expression=condition)
    return predicate


def render(
    model: Any,
    dimensions: list[str] | None = None,
    time_range: dict | None = None,
    metric: str | None = None,
    carry: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Render one dataset slice to one SQL SELECT (DuckDB dialect).

    ``model`` is a :class:`Slice`, or one Ossie document / parsed model with a
    single dataset. ``metric`` selects one metric (with its dependency
    closure); ``None`` renders every metric — measures in the inner GROUP BY,
    each derived level nested above the previous. ``dimensions`` must name
    dimension fields of the dataset. ``carry`` names metrics whose outputs must
    survive every derived layer. The rendered SQL is re-parsed as a self-check.
    """
    spec = slice_of(model)
    source = spec.source
    field_exprs = {
        name: _strip_qualifiers(_parse(sql, f"field {name!r}")) for name, sql in spec.fields.items()
    }
    metric_sqls = spec.metrics
    dims = list(dimensions or [])
    for dim in dims:
        if dim not in spec.dimensions:
            available = ", ".join(sorted(spec.dimensions))
            raise RenderError(
                f"unknown dimension {dim!r}; available dimensions: {available or '(none)'}"
            )
    if metric is not None and metric not in metric_sqls:
        raise RenderError(
            f"unknown metric {metric!r}; available metrics: {', '.join(sorted(metric_sqls))}"
        )
    levels, deps = _metric_levels(metric_sqls)
    metric_names = set(metric_sqls)
    wanted = _closure(metric, deps) if metric is not None else metric_names
    carried = set(carry or ())
    unknown = sorted(carried - metric_names)
    if unknown:
        raise RenderError(
            f"unknown carried metric(s) {unknown}; available: {', '.join(sorted(metric_sqls))}"
        )
    stray = sorted(carried - wanted)
    if stray:
        raise RenderError(f"carried metric(s) {stray} are not part of the rendered set")
    # metrics arrive lowered to source columns (ossie.parse_model): no field
    # substitution happens here, only qualifier stripping for the wrapped source
    parsed = {
        name: _strip_qualifiers(_parse(sql, f"metric {name!r}"))
        for name, sql in metric_sqls.items()
    }

    # Inner aggregate: dims + every wanted level-0 metric over the wrapped source.
    select = exp.Select()
    for dim in dims:
        select = select.select(exp.alias_(field_exprs[dim].copy(), dim))
    for name in sorted(wanted):
        if levels[name] == 0:
            select = select.select(exp.alias_(parsed[name].copy(), name))
    select = select.from_(_source_subquery(source, "dataset source"))
    if time_range:
        predicate = _time_predicate(spec, time_range)
        if predicate is not None:
            select = select.where(predicate)
    if dims:
        select.set("group", exp.Group(expressions=[exp.column(dim) for dim in dims]))

    # Each derived level becomes one outer SELECT over the previous level.
    deepest = max((levels[name] for name in wanted), default=0)
    for level in range(1, deepest + 1):
        keep = carried | {dep for name in wanted if levels[name] > level for dep in deps[name]}
        outer = exp.Select()
        for dim in dims:
            outer = outer.select(exp.column(dim))
        for name in sorted(wanted):
            if levels[name] == level:
                outer = outer.select(exp.alias_(parsed[name].copy(), name))
            elif name in keep and levels[name] < level:
                outer = outer.select(exp.column(name))  # keep the lower output
        select = outer.from_(exp.Subquery(this=select))
    sql = select.sql(dialect="duckdb")
    try:  # self-check: the compiler's own output must round-trip through the parser
        sqlglot.parse_one(sql)
    except Exception as exc:
        raise RenderError(f"rendered SQL failed to re-parse: {type(exc).__name__}: {exc}") from exc
    return sql


def output_guard(
    sql: str,
    columns: list[str],
    types: list[str],
    *,
    cell_bytes: int,
    max_rows: int,
) -> str:
    """The compiler-owned OUTPUT guard over one already completed logical
    query (spec 0014 §4 guards 1–2): one outer SELECT around
    the logical aggregate/window/detail statement — never inside its inputs,
    lookback or fact branches — that (a) caps materialized rows at the row
    ceiling plus exactly one overflow indicator row via LIMIT, and (b) for
    variable-size text/blob output columns, replaces oversized raw values
    with NULL inside DuckDB and surfaces one boolean overflow flag per
    guarded column, so an oversized cell never crosses into Python. The
    flag↔column association is POSITIONAL (flag column i+1 ↔ logical column
    i) — a physical output column whose name collides with the generated
    flag namespace is still a value column, never swallowed or misread
    (fix pass 1, finding 4). The logical SQL/provenance stays the caller's
    statement; this is the actual guarded execution statement. Fixed-width
    scalar columns pass through unmodified (their serialized size is checked
    exactly after transfer)."""
    inner = sqlglot.parse_one(sql, dialect="duckdb")
    select = exp.Select().from_(
        exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier("__ariadne_guarded")))
    )
    for index, (name, type_name) in enumerate(zip(columns, types)):
        column = exp.column(exp.to_identifier(name, quoted=True))
        if classify_output_type(type_name) != "variable":
            select = select.select(exp.alias_(column, name, quoted=True))
            continue
        base = type_name.strip().split("(")[0].strip().upper()
        if base in ("BLOB", "VARBINARY"):
            size = exp.Anonymous(this="octet_length", expressions=[column.copy()])
        else:
            # UTF-8 byte length of text/enum: encode() first (CAST AS BLOB
            # rejects non-ASCII); ENUM labels arrive as strings and are
            # guarded through the same VARCHAR text form
            text_value = (
                exp.Cast(this=column.copy(), to=exp.DataType(this=exp.DataType.Type.VARCHAR))
                if base == "ENUM"
                else column.copy()
            )
            size = exp.Anonymous(
                this="octet_length",
                expressions=[exp.Anonymous(this="encode", expressions=[text_value])],
            )
        oversized = exp.GT(this=size.copy(), expression=exp.Literal.number(cell_bytes))
        guarded = exp.Case().when(oversized.copy(), exp.null()).else_(column.copy())
        select = select.select(exp.alias_(guarded, name, quoted=True))
        select = select.select(
            exp.alias_(oversized, f"__ariadne_cell_overflow_{index}", quoted=True)
        )
    select = select.limit(max_rows + 1)
    return select.sql(dialect="duckdb")
