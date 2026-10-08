"""Own sqlglot compiler for the self-defined OSI envelope (ADR-0008, spec rev 7).

Renders one model of the ``version: 0.2.0.dev0`` envelope — ``datasets`` (source,
primary_key, fields with expression + dimension/is_time) and ``metrics``
(expression, optionally the DATUS-derived ``custom_extensions`` marker) — to a
single SQL SELECT:

- the dataset source becomes a wrapped subquery (a bare table name is wrapped in
  ``SELECT * FROM ...``, a SELECT/WITH passes through parenthesized);
- aggregate metrics (expressions referencing no other metric) compile into one
  inner ``SELECT dims..., metric AS name ... FROM (source) GROUP BY dims``;
- derived metrics (expressions referencing other metrics; the DATUS
  ``custom_extensions`` hint is validated but advisory — the expression itself is
  authoritative) resolve RECURSIVELY: each dependency level becomes one outer
  ``SELECT`` over the previous level, N levels deep, with explicit cycle
  detection that names the cycle;
- fields referenced by expressions resolve through the dataset's field
  alias -> expression mapping (transitively, self-references exempt); table
  qualifiers are stripped everywhere — the wrapped source knows no scan aliases
  (the datus lowering contract, author prompt);
- ``time_range`` ``{start, end}`` becomes a predicate on the model's ``is_time``
  field, applied to the inner aggregate.

Compile failures — malformed envelope, missing field, unknown metric or
dimension, metric cycle, unparsable expression, DATUS extension data that is
not strict ``{metric_kind, inputs}`` JSON — raise :class:`RenderError`, a
``ValueError`` subclass, whose message is the compiler's verbatim reason (the
spec §7 / mvp-2 verbatim-error contract). The result is re-parsed with
``sqlglot.parse_one`` as a self-check before it is returned.
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports]

from ariadne.query_results import (  # pyright: ignore[reportMissingImports] — drift
    classify_output_type,
)

# The DATUS extension hint (authoring contract, datus-spike.md §6.6): strictly
# validated keys — a stray key must fail the compile, exactly like the datus
# gate it replaces (tests/test_validate.py pins this contract).
_DATUS_KEYS = {"metric_kind", "inputs"}


class RenderError(ValueError):
    """Compiler failure; the message is the verbatim reason (spec §7 contract)."""


def _dialect_expression(block: dict, context: str) -> str:
    """The expression SQL from an ``expression.dialects`` block (ANSI_SQL preferred)."""
    dialects = (block or {}).get("dialects") or []
    for entry in dialects:
        if entry.get("dialect") == "ANSI_SQL" and isinstance(entry.get("expression"), str):
            return entry["expression"]
    if dialects and isinstance(dialects[0].get("expression"), str):
        return dialects[0]["expression"]
    raise RenderError(f"{context}: expression block carries no usable dialect expression")


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


def _model_entry(model_dict: dict) -> dict:
    """The model entry from a full envelope (``semantic_model`` list, exactly one
    entry) or a bare model dict — both input shapes are accepted."""
    if not isinstance(model_dict, dict):
        raise RenderError("model must be a dict")
    if "semantic_model" not in model_dict:
        return model_dict
    models = model_dict.get("semantic_model")
    if not isinstance(models, list) or not models:
        raise RenderError("envelope must carry a non-empty semantic_model list")
    if len(models) > 1:
        raise RenderError(
            f"envelope carries {len(models)} semantic_model entries; render compiles one model"
        )
    return models[0]


def _validate_datus_extensions(metric: dict) -> None:
    """The DATUS custom_extensions hint must be strict JSON with known keys
    (datus-spike.md §6.6 parity: a stray key is a compile error)."""
    for extension in metric.get("custom_extensions") or []:
        if extension.get("vendor_name") != "DATUS":
            continue
        data = extension.get("data")
        if not isinstance(data, str):
            continue  # structured (non-string) payloads pass through untouched
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RenderError(
                f"metric {metric.get('name')!r}: DATUS custom_extensions data is not "
                f"valid JSON: {exc}"
            ) from exc
        if isinstance(parsed, dict):
            stray = sorted(set(parsed) - _DATUS_KEYS)
            if stray:
                raise RenderError(
                    f"metric {metric.get('name')!r}: unsupported DATUS extension "
                    f"hint keys: {', '.join(stray)}"
                )


def _model_parts(
    model_dict: dict,
) -> tuple[str, dict[str, Any], dict[str, str], dict[str, dict]]:
    """(source, field alias -> expression AST, metric name -> expression SQL,
    field name -> dimension flags) from the model entry — malformed envelopes
    fail here, reason verbatim."""
    model = _model_entry(model_dict)
    datasets = model.get("datasets") or []
    if len(datasets) != 1:
        raise RenderError(
            f"model {model.get('name')!r}: render compiles exactly one dataset, got {len(datasets)}"
        )
    dataset = datasets[0]
    source = dataset.get("source")
    if not isinstance(source, str) or not source.strip():
        raise RenderError(f"dataset {dataset.get('name')!r}: missing source")
    fields = dataset.get("fields") or []
    metrics = model.get("metrics") or []
    if not metrics:
        raise RenderError(f"model {model.get('name')!r}: no metrics to render")

    def context(name: Any) -> str:
        return f"field {name!r}"

    field_exprs = {
        field.get("name"): _strip_qualifiers(
            _parse(
                _dialect_expression(field.get("expression") or {}, context(field.get("name"))),
                context(field.get("name")),
            )
        )
        for field in fields
        if field.get("name")
    }
    for metric in metrics:
        _validate_datus_extensions(metric)
    metric_sqls = {
        metric.get("name"): _dialect_expression(
            metric.get("expression") or {}, f"metric {metric.get('name')!r}"
        )
        for metric in metrics
        if metric.get("name")
    }
    dimension_flags = {
        field.get("name"): (field.get("dimension") or {}) for field in fields if field.get("name")
    }
    return source.strip(), field_exprs, metric_sqls, dimension_flags


def _source_subquery(source: str, context: str) -> exp.Subquery:
    """The dataset source as a FROM-able wrapped subquery (same discipline as
    validate's audit wrapper: bare table refs get a SELECT, SELECT/WITH pass
    through parenthesized). Exactly ONE statement is accepted — a crafted source
    smuggling DDL past the parser is rejected here, before any execution
    (no-unvalidated-execution invariant, spec §6)."""
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


def _resolve_fields(
    tree,  # sqlglot exp node (runtime alias — not a static type)
    field_exprs: dict[str, Any],
    metric_names: set[str],
    stack: tuple[str, ...] = (),
):
    """Recursively substitute field references with the field's expression
    (alias -> expression mapping). Self-references are the source column and are
    exempt; anything else cycles -> RenderError naming the chain."""
    for column in list(tree.find_all(exp.Column)):
        name = column.name
        if name in metric_names or name not in field_exprs:
            continue  # metric refs are resolved by layering; unknown refs bind later
        if name in stack:
            if name == stack[-1]:
                continue  # self-reference: the field's expression IS the source column
            chain = " -> ".join((*stack, name))
            raise RenderError(f"field reference cycle: {chain}")
        replacement = _resolve_fields(
            field_exprs[name].copy(), field_exprs, metric_names, (*stack, name)
        )
        column.replace(replacement)
    return tree


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
    deps = {name: _metric_references(tree, set(metric_sqls)) for name, tree in parsed.items()}
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


def _time_predicate(
    field_exprs: dict[str, Any], dimension_flags: dict[str, dict], time_range: dict
) -> Any | None:
    """``{start, end}`` -> predicate on the model's is_time field (inclusive)."""
    start = time_range.get("start")
    end = time_range.get("end")
    if start is None and end is None:
        return None
    time_fields = [name for name, flag in dimension_flags.items() if flag.get("is_time")]
    if not time_fields:
        raise RenderError(
            "time_range requires a field with dimension.is_time: true on the model's dataset"
        )
    field = field_exprs[time_fields[0]]
    conditions: list[Any] = []
    if start is not None:
        conditions.append(exp.GTE(this=field.copy(), expression=exp.Literal.string(str(start))))
    if end is not None:
        conditions.append(exp.LTE(this=field.copy(), expression=exp.Literal.string(str(end))))
    predicate = conditions[0]
    for condition in conditions[1:]:
        predicate = exp.And(this=predicate, expression=condition)
    return predicate


def render(
    model_dict: dict,
    dimensions: list[str] | None = None,
    time_range: dict | None = None,
    metric: str | None = None,
    carry: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Render the model to one SQL SELECT (DuckDB dialect).

    ``metric`` selects one metric (with its dependency closure); ``None`` renders
    every metric of the model — aggregate metrics in the inner GROUP BY, each
    derived level nested above the previous. ``dimensions`` must name dimension
    fields of the model's dataset. ``carry`` names metrics whose outputs must
    survive every derived layer (a branch that aggregates a base metric AND a
    same-fact derived metric on top of it needs both, issue #27 fix pass F5);
    the default keeps each level's own single-output shape. The rendered SQL is
    re-parsed as a self-check.
    """
    source, field_exprs, metric_sqls, dimension_flags = _model_parts(model_dict)
    dims = list(dimensions or [])
    dimension_names = {name for name, flag in dimension_flags.items() if isinstance(flag, dict)}
    for dim in dims:
        if dim not in dimension_names:
            available = ", ".join(sorted(dimension_names))
            raise RenderError(
                f"unknown dimension {dim!r}; available dimensions: {available or '(none)'}"
            )
    if metric is not None and metric not in metric_sqls:
        raise RenderError(
            f"unknown metric {metric!r}; available metrics: {', '.join(sorted(metric_sqls))}"
        )
    levels, deps = _metric_levels(metric_sqls)
    wanted = _closure(metric, deps) if metric is not None else set(metric_sqls)
    carried = set(carry or ())
    unknown = sorted(carried - set(metric_sqls))
    if unknown:
        raise RenderError(
            f"unknown carried metric(s) {unknown}; "
            f"available: {', '.join(sorted(metric_sqls))}"
        )
    stray = sorted(carried - wanted)
    if stray:
        raise RenderError(f"carried metric(s) {stray} are not part of the rendered set")
    parsed = {
        name: _resolve_fields(
            _strip_qualifiers(_parse(sql, f"metric {name!r}")), field_exprs, set(metric_sqls)
        )
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
        predicate = _time_predicate(field_exprs, dimension_flags, time_range)
        if predicate is not None:
            select = select.where(predicate)
    if dims:
        select.set("group", exp.Group(expressions=[exp.column(dim) for dim in dims]))

    # Each derived level becomes one outer SELECT over the previous level.
    deepest = max((levels[name] for name in wanted), default=0)
    for level in range(1, deepest + 1):
        outer = exp.Select()
        for dim in dims:
            outer = outer.select(exp.column(dim))
        for name in sorted(wanted):
            if levels[name] == level:
                outer = outer.select(exp.alias_(parsed[name].copy(), name))
            elif name in carried and levels[name] < level:
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
    query (spec 0014 §4 guards 1–2, plan 0014 §2): one outer SELECT around
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
            # guarded through the same VARCHAR text form (fix pass 1, finding 3)
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
