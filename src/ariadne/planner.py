"""Governed multi-fact query planner (issue #27/#28; spec rev 1 "Query and
result contract"; ADR-0006 — one grain per dataset, independent fact branches).

``plan_query(graph, request, connection)`` compiles a validated semantic graph
(task 1) plus a named-metric/dimension request into ONE guarded SELECT with
bounded plan metadata:

- **one branch per owning fact**, aggregated at its own grain. A no-join branch
  compiles through the single-dataset renderer; a branch that must reach a
  dimension field on another dataset joins it INSIDE the branch through proven
  ``many_to_one``/``one_to_one`` relationship edges only (LEFT joins onto the
  unique target, so unmatched fact rows keep their aggregate under a NULL key
  instead of being silently dropped).
- **aggregate outputs** are aligned on null-safe equality (``IS NOT DISTINCT
  FROM``) over the UNION of branch group keys — never a raw fact-to-fact row
  join. Groups occurring in only one branch survive; NULL-key groups coalesce
  once. With no dimensions the plan cross-joins the single-row aggregates.
  A missing bare ``COUNT`` reads 0; every other missing measure stays NULL.
- **per-request live audits** on the configured DuckDB connection (mutable
  sources have no proven immutable snapshot identity, so NOTHING is cached
  between requests): exact composite target-key uniqueness + non-NULL key
  components for each participating relationship
  (:func:`ariadne.grain.relationship_target_audit`), the shared structural
  grain guard :func:`ariadne.grain.check_grain_preserving` on every
  participating AUTHORED dataset source (embedded/pre-joined sources cannot
  bypass it; the generated relationship joins themselves are proven by the
  exact tuple audit), and an EXPLAIN bind
  check of the final statement — nothing that failed a gate is executed. A
  plan compiled without a connection stays compile-only and reports the
  relationship audit as not-run.

Refusals are structured: :class:`PlannerError` carries a stable ``code`` plus
candidate names; message prose is not API (spec rev 1, "Failure and
compatibility behavior"). There is no unchecked-SQL fallback: the planner only
assembles sqlglot ASTs it derived itself. Served operations are task 5 (#30).

Task 4 (issue #29) adds conformed business time and the post-aggregate stage:

- a declared **conformed primary business time** (time-field members carrying
  declared native grains) maps the half-open ``[start, end)`` request range
  onto EACH fact's own native time field and groups at the requested
  ``day/week/month/quarter/year`` grain — differently named date columns align
  by declaration, never by column name. A requested grain finer than a
  member's declared native grain refuses; there is no implicit calendar spine
  (only groups occurring in some branch exist).
- **post-aggregate metrics** resolve AFTER the branches merge: cross-fact
  derived metrics (and every metric declaring a window) compute level by level
  over the aligned output columns, with every division guarded — a zero or
  missing denominator yields NULL. An explicit metric ``fill`` applies to the
  OUTPUT projection only, never to a hidden denominator.
- **declared window forms** — rolling, cumulative, prior-period, ranking and
  value windows — run at that stage, ordered by the conformed time key and
  partitioned by the non-time dimensions. Window lookback (preceding groups,
  or all of them for a cumulative frame) is fetched BEFORE the displayed
  range trims; ranking orders the displayed rows, so it runs after the trim.

Task 3 (issue #28) adds the scoped request surface on the same contract:

- **row filters and named segments** are parsed predicates over DECLARED fields
  (``{"field", "op", "value"}``, never SQL text), routed to each ELIGIBLE fact
  branch through the same conformance/lookup resolution as dimensions. A
  conformed field must pair EVERY affected branch or refuse as
  ``unpaired_filter`` — never silently narrow one fact; a fact-local field
  routes only to the branches that can reach it (disclosed in branch lineage).
- **typed bounded parameters** (string/int/float/date, optional ``max_length``
  /``min``/``max``) become bound AST literals — untyped, mistyped or oversized
  values refuse; nothing is ever concatenated into SQL.
- **result filters** name a REQUESTED metric and apply AFTER grouping, on the
  aligned output; **declared ordering and bounded limits** apply after that.
- :func:`plan_detail` fixes ONE root dataset and projects its fields through
  proven many-to_one/one_to_one multi-hop paths only — LEFT joins onto unique
  targets preserve the root grain (one row per root key, no aggregates); a
  child-side traversal refuses before execution.
"""

from __future__ import annotations

import calendar
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import (  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
    exp,  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
)

from ariadne.grain import (  # pyright: ignore[reportMissingImports] — drift
    check_grain_preserving,
    relationship_target_audit,
)
from ariadne.query_results import (  # pyright: ignore[reportMissingImports] — drift
    classify_output_type,
)
from ariadne.render import (  # pyright: ignore[reportMissingImports] — drift
    RenderError,
    _parse,
    _resolve_fields,
    _source_subquery,
    _strip_qualifiers,
    render,
)
from ariadne.semantic_graph import (  # pyright: ignore[reportMissingImports] — drift
    TIME_GRAINS,
    RelationshipEdge,
    SemanticGraph,
    WindowDecl,
)

_REQUEST_KEYS = frozenset(
    {"metrics", "dimensions", "filters", "segments", "parameters", "order", "limit", "time"}
)
_DETAIL_REQUEST_KEYS = frozenset({"dataset", "fields"})
_FILTER_KEYS = frozenset({"field", "op", "value"})
_SEGMENT_KEYS = frozenset({"name", "filters"})
_PARAMETER_KEYS = frozenset({"type", "value", "min", "max", "max_length"})
_ORDER_KEYS = frozenset({"field", "direction"})
_TIME_KEYS = frozenset({"dimension", "grain", "start", "end"})
_COMPARISONS = {"=": exp.EQ, "!=": exp.NEQ, "<": exp.LT, "<=": exp.LTE, ">": exp.GT, ">=": exp.GTE}
PARAMETER_TYPES = frozenset({"string", "int", "float", "date"})
MAX_PARAMETER_LENGTH = 4096  # hard ceiling even without a declared max_length
MAX_LIMIT = 10_000  # bounded result limits
MAX_IN_VALUES = 100  # bounded IN lists

# finest-first grain order: a requested grain finer than a declared native one
# refuses (spec rev 1 "Query and result contract")
_GRAIN_RANK = {grain: rank for rank, grain in enumerate(TIME_GRAINS)}
# a value-window RANGE frame over the time axis, expressed in calendar units
_INTERVAL_UNIT = {
    "day": ("DAY", 1),
    "week": ("DAY", 7),
    "month": ("MONTH", 1),
    "quarter": ("MONTH", 3),
    "year": ("YEAR", 1),
}
_WINDOW_FUNCTIONS = {
    "sum": exp.Sum,
    "avg": exp.Avg,
    "min": exp.Min,
    "max": exp.Max,
    "count": exp.Count,
}
# window forms whose frame needs the time axis (ranking ranks displayed rows
# by value and needs neither the axis nor preceding groups)
_TIME_FRAME_KINDS = frozenset({"rolling", "cumulative", "prior_period", "value_window"})


class PlannerError(ValueError):
    """Structured planning refusal; ``code`` is a stable API field, message
    prose is not (spec rev 1, "Failure and compatibility behavior")."""

    def __init__(self, code: str, message: str, candidates: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.candidates = candidates


@dataclass(frozen=True)
class BranchPlan:
    """Bounded lineage for one fact branch: its dataset, the metrics it
    aggregates, the relationship edges it traverses (in order), the (canonical
    dimension, native column) keys it groups by, and the row-filter fields
    routed into it (fact-local filters are disclosed here, never silent)."""

    dataset: str
    metrics: tuple[str, ...]
    joins: tuple[str, ...]
    keys: tuple[tuple[str, str], ...]
    filters: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditRecord:
    """One performed live check and its outcome (plan evidence, issue #27)."""

    name: str
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class QueryPlan:
    """The guarded SELECT plus bounded plan metadata (SQL, fact branches,
    conformed keys, applied segments, performed audits, and the declared
    conformed business time / windowed-metric lineage of issue #29)."""

    sql: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    branches: tuple[BranchPlan, ...]
    conformed_keys: tuple[str, ...]
    audits: tuple[AuditRecord, ...]
    relationship_audit: str  # passed | not-run (never silently passed)
    segments: tuple[str, ...] = ()
    time_dimension: str | None = None  # the conformed primary business time
    time_grain: str | None = None  # its requested grouping grain
    windows: tuple[str, ...] = ()  # requested metrics with a declared window
    # the mechanically CONSUMED half-open native fetch range of the request
    # (issue #54 W1 fix3): window lookback precedes the display trim, so this
    # is ``None`` without a time request and otherwise ``(fetch_start,
    # fetch_end)`` — either side may be ``None`` (unbounded). ``query_metrics``
    # derives its advisory period fact from THIS, never from the display
    # range: a report consumed through the lookback extension is material.
    fetch_bounds: tuple[date | None, date | None] | None = None


@dataclass(frozen=True)
class _Predicate:
    """One parsed row/result predicate: field, operator, and a value that is
    either a scalar/list of scalars or a ``('param', name)`` reference to a
    declared parameter (never SQL text)."""

    field: str
    op: str
    value: Any  # scalar | list[scalar] | ("param", name)
    origin: str  # "filters" or the declaring segment's name


def _parse_value(raw: Any, context: str) -> Any:
    """One filter value: a scalar, a bounded list of scalars, or a parameter
    reference ``{'param': name}`` (typed parameters become AST/bound values,
    never SQL fragments — spec rev 1, "Query and result contract")."""
    if isinstance(raw, dict):
        if set(raw) != {"param"} or not isinstance(raw["param"], str):
            raise PlannerError(
                "filter_invalid",
                f"{context}: a parameter reference is exactly {{'param': <name>}}",
            )
        return ("param", raw["param"])
    if isinstance(raw, list):
        if not raw or len(raw) > MAX_IN_VALUES:
            raise PlannerError(
                "filter_invalid",
                f"{context}: an IN list needs 1..{MAX_IN_VALUES} values",
            )
        return [_parse_value(item, context) for item in raw]
    if isinstance(raw, (str, int, float, bool)) or raw is None:
        return raw
    raise PlannerError("filter_invalid", f"{context}: unsupported filter value {raw!r}")


def _parse_predicate(entry: Any, context: str) -> _Predicate:
    """``{'field', 'op', 'value'}`` with a declared comparison operator."""
    if not isinstance(entry, dict) or set(entry) != _FILTER_KEYS:
        raise PlannerError(
            "filter_invalid",
            f"{context}: a predicate is exactly {{'field', 'op', 'value'}}",
        )
    field, op = entry["field"], entry["op"]
    if not isinstance(field, str) or not field.strip():
        raise PlannerError("filter_invalid", f"{context}: 'field' must be a field name")
    value = _parse_value(entry["value"], context)
    if op == "in":
        if not isinstance(value, list):
            raise PlannerError(
                "filter_invalid", f"{context}: op 'in' takes a literal list of values"
            )
    elif isinstance(op, str) and op in _COMPARISONS:
        # mf-t3 review F3: a malformed "op" (e.g. a list) must fall through to
        # the structured refusal, not hit the hash-based membership check
        if isinstance(value, list):
            raise PlannerError("filter_invalid", f"{context}: op {op!r} takes exactly one value")
    else:
        raise PlannerError(
            "filter_invalid",
            f"{context}: unsupported op {op!r}; allowed: {sorted((*_COMPARISONS, 'in'))}",
        )
    origin = "filters" if context.startswith("'filters'") else context
    return _Predicate(field=field, op=op, value=value, origin=origin)


def _parse_predicates(request: dict) -> tuple[list[_Predicate], tuple[str, ...]]:
    """Direct row/result filters plus named segments (each a declared,
    nonempty composition of row predicates — spec rev 1, "Query and result
    contract"). Returns the predicate list and the applied segment names."""
    out: list[_Predicate] = []
    segment_names: list[str] = []
    filters = request.get("filters")
    if filters is not None:
        if not isinstance(filters, list):
            raise PlannerError("filter_invalid", "'filters' must be a list of predicates")
        out.extend(_parse_predicate(entry, "'filters'") for entry in filters)
    segments = request.get("segments")
    if segments is not None:
        if not isinstance(segments, list):
            raise PlannerError("filter_invalid", "'segments' must be a list of named definitions")
        for entry in segments:
            if not isinstance(entry, dict) or set(entry) != _SEGMENT_KEYS:
                raise PlannerError(
                    "filter_invalid",
                    "a segment is exactly {'name': ..., 'filters': [predicates]}",
                )
            name = entry["name"]
            if not isinstance(name, str) or not name.strip():
                raise PlannerError("filter_invalid", "a segment needs a nonempty 'name'")
            if name in segment_names:
                raise PlannerError("filter_invalid", f"duplicate segment name {name!r}")
            body = entry["filters"]
            if not isinstance(body, list) or not body:
                raise PlannerError(
                    "filter_invalid",
                    f"segment {name!r} composes at least one predicate — an empty "
                    "segment is a mistake, not a no-op",
                )
            out.extend(_parse_predicate(item, f"segment {name!r}") for item in body)
            segment_names.append(name)
    return out, tuple(segment_names)


def _parse_parameters(raw: Any) -> dict[str, tuple[str, Any]]:
    """``name -> (declared type, bound value)`` for typed bounded parameters.
    Untyped, mistyped, malformed or oversized declarations refuse; a type is
    declared, never guessed (spec rev 1: string/int/float/date as declared)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PlannerError("parameter_invalid", "'parameters' must be name -> declaration")
    bound: dict[str, tuple[str, Any]] = {}
    for name, declaration in raw.items():
        if not isinstance(name, str) or not isinstance(declaration, dict):
            raise PlannerError("parameter_invalid", "'parameters' maps names to declarations")
        unknown = sorted(set(declaration) - _PARAMETER_KEYS)
        if unknown:
            raise PlannerError(
                "parameter_invalid",
                f"parameter {name!r}: unknown key(s) {unknown}; allowed: {sorted(_PARAMETER_KEYS)}",
            )
        kind = declaration.get("type")
        value = declaration.get("value")
        where = f"parameter {name!r}"
        if not isinstance(kind, str) or kind not in PARAMETER_TYPES:
            # mf-t3 review F3: a malformed "type" (e.g. a list) refuses here
            # instead of hitting the hash-based membership check
            raise PlannerError(
                "parameter_invalid",
                f"{where}: 'type' must be one of {sorted(PARAMETER_TYPES)}, got "
                f"{kind!r} — untyped parameters are refused",
            )
        if kind == "string":
            if not isinstance(value, str):
                raise PlannerError(
                    "parameter_invalid", f"{where}: a string parameter takes a string value"
                )
            declared = declaration.get("max_length")
            if declared is not None and (
                isinstance(declared, bool) or not isinstance(declared, int) or declared < 1
            ):
                raise PlannerError(
                    "parameter_invalid", f"{where}: 'max_length' must be a positive integer"
                )
            limit = min(declared or MAX_PARAMETER_LENGTH, MAX_PARAMETER_LENGTH)
            if len(value) > limit:
                raise PlannerError(
                    "parameter_invalid",
                    f"{where}: value of {len(value)} character(s) exceeds the bound of {limit}",
                )
        elif kind in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PlannerError(
                    "parameter_invalid", f"{where}: a {kind} parameter takes a number"
                )
            if kind == "int" and not isinstance(value, int):
                raise PlannerError(
                    "parameter_invalid", f"{where}: an int parameter takes an integer"
                )
            low, high = declaration.get("min"), declaration.get("max")
            for key, edge in (("min", low), ("max", high)):
                if edge is not None and (
                    isinstance(edge, bool) or not isinstance(edge, (int, float))
                ):
                    raise PlannerError("parameter_invalid", f"{where}: '{key}' must be a number")
            if (low is not None and value < low) or (high is not None and value > high):
                raise PlannerError(
                    "parameter_invalid",
                    f"{where}: value {value!r} is outside the declared bounds [{low!r}, {high!r}]",
                )
        else:  # date
            if not isinstance(value, str):
                raise PlannerError(
                    "parameter_invalid", f"{where}: a date parameter takes an ISO string"
                )
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise PlannerError(
                    "parameter_invalid", f"{where}: {value!r} is not an ISO 8601 date"
                ) from exc
        bound[name] = (kind, value)
    return bound


def _bound_literal(kind: str, value: Any) -> exp.Expression:
    """One typed parameter value as a bound AST node — string quotes double
    inside literals, dates cast explicitly; nothing is ever SQL text."""
    if kind == "string":
        return exp.Literal.string(value)
    if kind == "int":
        return exp.Literal.number(value)
    if kind == "float":
        return exp.Literal.number(float(value))
    return exp.Cast(this=exp.Literal.string(value), to=exp.DataType.build("DATE"))


def _direct_literal(raw: Any, context: str) -> exp.Expression:
    if isinstance(raw, str):
        return exp.Literal.string(raw)
    if isinstance(raw, bool):
        return exp.Boolean(this=raw)
    if isinstance(raw, (int, float)):
        return exp.Literal.number(raw)
    if raw is None:
        return exp.Null()
    raise PlannerError("filter_invalid", f"{context}: unsupported value {raw!r}")


def _predicate_ast(
    column: exp.Expression, predicate: _Predicate, parameters: dict[str, tuple[str, Any]]
) -> exp.Expression:
    """``<column> <op> <bound literal>`` as a planner-built AST — the value
    binds as a literal node (quotes doubled for strings), so a payload naming a
    second statement can neither execute nor broaden the predicate."""
    context = f"filter on {predicate.field!r}"
    raw = predicate.value
    if isinstance(raw, tuple):  # ('param', name) — parser-constructed only
        name = raw[1]
        if name not in parameters:
            raise PlannerError(
                "unknown_parameter",
                f"{context} ({predicate.origin}): references undeclared parameter {name!r}",
                candidates=tuple(sorted(parameters)),
            )
        kind, bound = parameters[name]
        return _COMPARISONS[predicate.op](this=column, expression=_bound_literal(kind, bound))
    if isinstance(raw, list):
        return exp.In(this=column, expressions=[_direct_literal(item, context) for item in raw])
    return _COMPARISONS[predicate.op](this=column, expression=_direct_literal(raw, context))


def _parse_order_limit(request: dict) -> tuple[list[tuple[str, bool]], int | None]:
    """Declared result ordering (output columns, asc/desc) and a bounded
    limit — both applied after grouping/window evaluation."""
    raw_order = request.get("order")
    order: list[tuple[str, bool]] = []
    if raw_order is not None:
        if not isinstance(raw_order, list):
            raise PlannerError(
                "order_invalid",
                "'order' must be a list of {'field': ..., 'direction': 'asc'|'desc'}",
            )
        for entry in raw_order:
            if not isinstance(entry, dict) or set(entry) - _ORDER_KEYS or "field" not in entry:
                raise PlannerError(
                    "order_invalid",
                    "an order entry is {'field': <output column>} plus optional 'direction'",
                )
            field = entry["field"]
            direction = entry.get("direction", "asc")
            if not isinstance(field, str) or not field.strip():
                raise PlannerError("order_invalid", "order 'field' must be a column name")
            if direction not in ("asc", "desc"):
                raise PlannerError(
                    "order_invalid",
                    f"order direction must be 'asc' or 'desc', got {direction!r}",
                )
            order.append((field, direction == "desc"))
    raw_limit = request.get("limit")
    if raw_limit is None:
        return order, None
    if (
        isinstance(raw_limit, bool)
        or not isinstance(raw_limit, int)
        or not 1 <= raw_limit <= MAX_LIMIT
    ):
        raise PlannerError(
            "limit_invalid",
            f"'limit' must be an integer in 1..{MAX_LIMIT}, got {raw_limit!r}",
        )
    return order, raw_limit


@dataclass(frozen=True)
class _TimeRequest:
    """One declared conformed primary business time request (issue #29): the
    conformed dimension, the requested grouping grain and the half-open
    ``[start, end)`` display range (spec rev 1 "Query and result contract")."""

    dimension: str
    grain: str
    start: date | None
    end: date | None


def _parse_time(raw: Any) -> _TimeRequest:
    """``{'dimension', 'grain', 'start'?, 'end'?}`` — the conformed primary
    business time to align on, its grouping grain and the half-open display
    range. Strict keys; dates are ISO 8601; the grain must be one of the five
    declared grains."""
    if not isinstance(raw, dict):
        raise PlannerError(
            "time_invalid",
            "'time' must be a mapping {'dimension': ..., 'grain': ..., 'start': ..., 'end': ...}",
        )
    unknown = sorted(set(raw) - _TIME_KEYS)
    if unknown:
        raise PlannerError(
            "time_invalid", f"unknown time key(s) {unknown}; allowed: {sorted(_TIME_KEYS)}"
        )
    dimension = raw.get("dimension")
    grain = raw.get("grain")
    if not isinstance(dimension, str) or not dimension.strip():
        raise PlannerError(
            "time_invalid",
            "'time.dimension' must name the declared conformed primary business time",
        )
    if not isinstance(grain, str) or not grain.strip():
        raise PlannerError("time_invalid", "'time.grain' must declare one of the grouping grains")
    if grain not in TIME_GRAINS:
        raise PlannerError(
            "time_grain_invalid",
            f"'time.grain' must be one of {list(TIME_GRAINS)}, got {grain!r}",
        )
    bounds: dict[str, date] = {}
    for key in ("start", "end"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise PlannerError("time_invalid", f"'time.{key}' must be an ISO 8601 date string")
        try:
            bounds[key] = date.fromisoformat(value)
        except ValueError as exc:
            raise PlannerError(
                "time_invalid", f"'time.{key}': {value!r} is not an ISO 8601 date"
            ) from exc
    start, end = bounds.get("start"), bounds.get("end")
    if start is not None and end is not None and start >= end:
        raise PlannerError(
            "time_invalid",
            f"the half-open range [start, end) requires start < end, got [{start}, {end})",
        )
    return _TimeRequest(dimension=dimension, grain=grain, start=start, end=end)


def _truncate(grain: str, value: date) -> date:
    """The grain-period start of ``value`` (mirrors SQL ``DATE_TRUNC``; DuckDB
    weeks start Monday)."""
    if grain == "day":
        return value
    if grain == "week":
        return value - timedelta(days=value.weekday())
    if grain == "month":
        return date(value.year, value.month, 1)
    if grain == "quarter":
        return date(value.year, 3 * ((value.month - 1) // 3) + 1, 1)
    return date(value.year, 1, 1)


def _shift_months(value: date, months: int) -> date:
    """``value`` shifted by whole months, clamped to the target month's last
    day (2026-03-31 - 1 month -> 2026-02-28)."""
    total = value.year * 12 + (value.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last))


def _shift_periods(grain: str, value: date, periods: int) -> date:
    """``value`` shifted by whole grain periods (lookback arithmetic)."""
    if grain == "day":
        return value + timedelta(days=periods)
    if grain == "week":
        return value + timedelta(weeks=periods)
    if grain == "month":
        return _shift_months(value, periods)
    if grain == "quarter":
        return _shift_months(value, 3 * periods)
    return _shift_months(value, 12 * periods)


def _lookback_groups(window: WindowDecl) -> int | None:
    """Preceding groups a window form needs before the display range (spec rev
    1: lookback includes the necessary preceding groups). ``None`` means EVERY
    preceding group: the cumulative frame, and the ACTUAL-group forms (ROWS
    frames, LAG) whose inputs are data-dependent under sparse history — the
    group preceding March may be January, never an invented February, so the
    fetch start cannot be a calendar shift for them."""
    if window.kind == "rolling":
        return None  # a ROWS frame counts actual groups across sparse history
    if window.kind == "prior_period":
        return None  # LAG reads the preceding ACTUAL group
    if window.kind == "value_window":
        return window.size
    if window.kind == "ranking":
        return 0  # ranking orders displayed rows by value: no preceding groups
    return None  # cumulative


def _date_literal(value: date) -> exp.Expression:
    """One ISO date as a bound CAST literal — never SQL text."""
    return exp.Cast(this=exp.Literal.string(value.isoformat()), to=exp.DataType.build("DATE"))


def _fill_literal(value: Any) -> exp.Expression:
    """One declared fill value as a bound literal (output projection only)."""
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(value)
    return exp.Literal.string(str(value))


def _parse_request(request: Any) -> tuple[list[str], list[str]]:
    """``{'metrics': [...], 'dimensions': [...]}`` — strict keys (an unknown key
    is an explicit error, never a silently ignored narrowing)."""
    if not isinstance(request, dict):
        raise PlannerError(
            "request_invalid", "request must be a mapping {'metrics': [...], 'dimensions': [...]}"
        )
    unknown = sorted(set(request) - _REQUEST_KEYS)
    if unknown:
        raise PlannerError(
            "request_invalid",
            f"unknown request key(s) {unknown}; allowed: {sorted(_REQUEST_KEYS)}",
        )
    metrics = request.get("metrics")
    if (
        not isinstance(metrics, list)
        or not metrics
        or not all(isinstance(name, str) for name in metrics)
    ):
        raise PlannerError("request_invalid", "'metrics' must be a non-empty list of metric names")
    dimensions = request.get("dimensions", [])
    if not isinstance(dimensions, list) or not all(isinstance(name, str) for name in dimensions):
        raise PlannerError("request_invalid", "'dimensions' must be a list of dimension names")
    return list(dict.fromkeys(metrics)), list(dict.fromkeys(dimensions))


def _resolve_owner(graph: SemanticGraph, name: str, memo: dict[str, str | None]) -> str | None:
    """The dataset a metric compiles against: base metrics carry it on the
    node; a derived metric compiles against the single dataset owning its whole
    dependency closure, else ``None`` (cross-fact — post-alignment, #29)."""
    node = graph.metrics[name]
    if not node.derived:
        return node.owner
    if name not in memo:
        owners = {_resolve_owner(graph, dep, memo) for dep in node.deps}
        memo[name] = owners.pop() if len(owners) == 1 else None
    return memo[name]


def _closure(graph: SemanticGraph, name: str) -> list[str]:
    """The metric plus its transitive metric dependencies (acyclic by load)."""
    out: list[str] = []
    frontier = [name]
    while frontier:
        current = frontier.pop()
        if current in out:
            continue
        out.append(current)
        frontier.extend(graph.metrics[current].deps)
    return out


def _lookup_path(
    graph: SemanticGraph, start: str, home: str
) -> tuple[RelationshipEdge, ...] | None:
    """The unique forward edge path ``start -> home`` (BFS; task 1's topology
    guarantees at most one bounded, acyclic path per dataset pair). Reverse
    traversal is not attempted — an edge's declared direction names its unique
    target side."""
    if start == home:
        return ()
    queue: list[tuple[str, tuple[RelationshipEdge, ...]]] = [(start, ())]
    seen = {start}
    while queue:
        dataset, path = queue.pop(0)
        for edge in graph.relationships:
            if edge.from_dataset != dataset or edge.to_dataset in seen:
                continue
            extended = (*path, edge)
            if edge.to_dataset == home:
                return extended
            seen.add(edge.to_dataset)
            queue.append((edge.to_dataset, extended))
    return None


@dataclass(frozen=True)
class _DimKey:
    """One resolved requested dimension: the canonical name, each branch's
    native member field, the lookup edges each branch traverses for it, and
    the conformed-dimension name when alignment relies on conformance.

    A conformed primary business time key additionally carries the requested
    grain: branches group by ``DATE_TRUNC(grain, member)`` and project it under
    a per-branch output column distinct from the native field (``outputs``),
    while ``members`` keeps naming the native business time field for lineage
    and the range predicate (issue #29)."""

    dimension: str
    members: dict[str, str]  # branch dataset -> native field
    paths: dict[str, tuple[RelationshipEdge, ...]]  # branch dataset -> edges
    conformed: str | None
    outputs: dict[str, str] | None = None  # branch output column (time keys)
    grain: str | None = None  # requested time grain (time keys only)

    def output(self, dataset: str) -> str:
        """The branch's output column for this key (the native member name,
        except for time keys whose group expression is a truncation)."""
        return self.members[dataset] if self.outputs is None else self.outputs[dataset]

    def group_expression(self, column: exp.Expression) -> exp.Expression:
        """The branch group expression over the native member column."""
        if self.grain is None:
            return column
        return exp.DateTrunc(unit=exp.Literal.string(self.grain), this=column)


def _resolve_field_key(
    graph: SemanticGraph,
    name: str,
    branch_datasets: list[str],
    conformed_by_name: dict[str, Any],
    kind: str,
) -> _DimKey:
    """Resolve a requested dimension or row-filter field to per-branch members
    and lookup paths; ``kind`` ('dimension' | 'filter') names the error codes.
    Dimensions must resolve in EVERY branch. A row filter routes to each
    ELIGIBLE branch: a conformed field still must pair EVERY affected branch
    (never silently narrow one fact), while a fact-local field routes only to
    the branches that can reach its home — disclosed in branch lineage."""
    edge = conformed_by_name.get(name)
    if edge is not None:
        members: dict[str, str] = {}
        missing: list[str] = []
        for dataset in branch_datasets:
            field_name = next((field for member, field in edge.members if member == dataset), None)
            if field_name is None:
                missing.append(dataset)
            else:
                members[dataset] = field_name
        if missing:
            raise PlannerError(
                f"unpaired_{kind}",
                f"conformed {kind} '{name}' has no member on fact branch(es) "
                f"{sorted(missing)} — it must resolve safely in EVERY affected "
                "branch, never silently narrow one (spec rev 1)",
            )
        return _DimKey(name, members, {dataset: () for dataset in branch_datasets}, name)
    owners = sorted(ds for ds, node in graph.datasets.items() if name in node.fields)
    if not owners:
        candidates = tuple(
            sorted(
                set(conformed_by_name)
                | {field for node in graph.datasets.values() for field in node.fields}
            )
        )
        raise PlannerError(
            f"unknown_{kind}",
            f"unknown {kind} {name!r}",
            candidates=candidates,
        )
    if len(owners) > 1:
        raise PlannerError(
            f"ambiguous_{kind}",
            f"field '{name}' exists on datasets {owners} — no equivalence is inferred "
            "from identical column names (spec rev 1 §3); declare a conformed dimension",
        )
    home = owners[0]
    members = {}
    paths: dict[str, tuple[RelationshipEdge, ...]] = {}
    for dataset in branch_datasets:
        path = _lookup_path(graph, dataset, home)
        if path is None:
            if kind == "dimension":
                raise PlannerError(
                    "unreachable_dimension",
                    f"dimension '{name}' (field of dataset '{home}') is not reachable "
                    f"from fact branch '{dataset}' through proven "
                    "many_to_one/one_to_one relationship paths",
                )
            continue  # a fact-local filter skips branches that cannot reach it
        members[dataset] = name
        paths[dataset] = path
    if not members:
        raise PlannerError(
            f"unreachable_{kind}",
            f"{kind} '{name}' (field of dataset '{home}') is not reachable from any "
            "fact branch through proven many_to_one/one_to_one relationship paths",
        )
    return _DimKey(name, members, paths, None)


@dataclass(frozen=True)
class _PostMetric:
    """One post-aggregate metric computation (issue #29): the metric's declared
    expression resolved over the ALIGNED output columns (cross-fact derived
    metrics and windowed derived metrics land here — never inside a branch),
    plus its declared window form when it has one. A windowed BASE aggregate
    (``base``) skips the expression layer — its home branch already produced
    the aligned column — and only its window applies here (C4)."""

    name: str
    expression: str
    level: int  # dependency level among post-aggregate metrics
    window: WindowDecl | None
    base: bool = False  # the aggregate column comes from a home branch


def _resolve_time_key(
    graph: SemanticGraph,
    request: _TimeRequest,
    branch_datasets: list[str],
    conformed_by_name: dict[str, Any],
) -> _DimKey:
    """The conformed primary business time as one alignment key: it must be a
    declared conformed dimension whose members are time fields carrying native
    grains, it must pair every branch, and the requested grain may not be finer
    than any member's declared native grain (spec rev 1 "Query and result
    contract", acceptance 4)."""
    edge = conformed_by_name.get(request.dimension)
    if edge is None or not edge.native_grains:
        raise PlannerError(
            "time_dimension_invalid",
            f"time dimension {request.dimension!r} is not a declared conformed primary "
            "business time (time-field members with declared native grains)",
            candidates=tuple(
                sorted(name for name, other in conformed_by_name.items() if other.native_grains)
            ),
        )
    key = _resolve_field_key(
        graph, request.dimension, branch_datasets, conformed_by_name, "time_dimension"
    )
    for dataset in sorted(key.members):
        native = edge.native_grains[dataset]
        if _GRAIN_RANK[request.grain] < _GRAIN_RANK[native]:
            raise PlannerError(
                "time_grain_too_fine",
                f"requested grain {request.grain!r} is finer than the declared native "
                f"grain {native!r} of dataset '{dataset}' — no implicit time spine and "
                "no finer-than-native grouping (spec rev 1, acceptance 4)",
            )
    outputs: dict[str, str] = {}
    for dataset in key.members:
        # the branch output column names the canonical time key; it must not
        # collide with the dataset's own fields (the branch groups by a
        # truncation of the native member, projected under this name)
        column = request.dimension
        while column in graph.datasets[dataset].fields:
            column += "_"
        outputs[dataset] = column
    return _DimKey(
        dimension=request.dimension,
        members=key.members,
        paths=key.paths,
        conformed=request.dimension,
        outputs=outputs,
        grain=request.grain,
    )


def _submodel(
    graph: SemanticGraph,
    dataset: str,
    metric_names: list[str],
    time_key: _DimKey | None = None,
) -> dict:
    """The dataset's single-dataset envelope slice (one dataset + exactly the
    metrics the branch aggregates) — the render() input shape. A conformed
    business time key injects ONE synthetic field grouping by the truncation of
    the dataset's native time member: the single-dataset renderer groups by
    field name, so the truncated key projects under the time key's output
    column while the native field keeps feeding the range predicate."""
    node = graph.datasets[dataset]
    envelope = graph.models[node.model]
    model = envelope["semantic_model"][0]
    raw_metrics = {
        metric.get("name"): metric
        for metric in model.get("metrics") or []
        if isinstance(metric, dict)
    }
    entry = next(
        candidate
        for candidate in model.get("datasets") or []
        if isinstance(candidate, dict) and candidate.get("name") == dataset
    )
    fields = list(entry.get("fields") or [])
    if time_key is not None and time_key.grain is not None:
        native = time_key.members[dataset]
        fields.append(
            {
                "name": time_key.output(dataset),
                "expression": {
                    "dialects": [
                        {
                            "dialect": "ANSI_SQL",
                            "expression": f"DATE_TRUNC('{time_key.grain}', {native})",
                        }
                    ]
                },
                "dimension": {},
            }
        )
    return {
        "version": envelope.get("version"),
        "semantic_model": [
            {
                "name": node.model,
                # a COPY of the dataset entry: the plain-filter path below
                # overwrites this mapping's 'source' with filtered SQL, and the
                # graph's own declaration must not change with any one request
                # (mf-t3 review F1)
                "datasets": [{**entry, "fields": fields}],
                "metrics": [raw_metrics[name] for name in sorted(metric_names)],
            }
        ],
    }


def _ordered_edges(
    graph: SemanticGraph, dataset: str, collected: dict[str, RelationshipEdge]
) -> list[RelationshipEdge]:
    """The collected target edges in branch-outward BFS order (a later edge's
    ``from_dataset`` is always already on the chain)."""
    order: list[RelationshipEdge] = []
    frontier = [dataset]
    seen = {dataset}
    while frontier:
        current = frontier.pop(0)
        for target, edge in sorted(collected.items()):
            if edge.from_dataset == current and target not in seen:
                seen.add(target)
                order.append(edge)
                frontier.append(target)
    return order


def resolved_target_keys(graph: SemanticGraph, edge: RelationshipEdge) -> tuple[str, ...]:
    """The edge's target key as FULLY RESOLVED field expressions (fix pass
    F3 + delta-recheck micro-fix): field substitution recurses exactly like
    join lowering's ``lower()`` — a target field ``owner_key`` declaring
    ``owner_ref + 0`` where ``owner_ref`` declares ``owner_id % 10`` keys on
    ``owner_id % 10 + 0``. Joins and both live audits (planner recheck,
    validate admission) use this one resolution, so the audit proves
    uniqueness of the SAME expression the generated join compares."""
    expressions = graph.datasets[edge.to_dataset].expressions
    field_asts = {
        name: _strip_qualifiers(_parse(sql, f"field {name!r} of dataset '{edge.to_dataset}'"))
        for name, sql in expressions.items()
    }
    resolved = []
    for field in edge.to_fields:
        tree = field_asts.get(field)
        if tree is None:
            # no usable dialect declaration: the physical column itself
            resolved.append(field)
            continue
        resolved.append(_resolve_fields(tree.copy(), field_asts, set()).sql(dialect="duckdb"))
    return tuple(resolved)


def _joined_branch_sql(
    graph: SemanticGraph,
    dataset: str,
    dim_keys: list[_DimKey],
    metric_names: list[str],
    row_preds: Sequence[tuple[_Predicate, _DimKey]] = (),
    parameters: dict[str, tuple[str, Any]] | None = None,
    fetch_bounds: tuple[date | None, date | None] = (None, None),
) -> tuple[str, list[RelationshipEdge]]:
    """A branch that reaches dimension or filter fields through relationship
    lookup paths: LEFT joins onto each proven unique target INSIDE the branch,
    keys and base aggregates projected over the joined output, GROUP BY the key
    expressions, and row predicates applied INSIDE the branch (before its
    aggregation — a filter that reaches a lookup field filters that branch's
    population). Every field resolves against the dataset that declares it
    and each source-column reference carries that dataset's branch alias, so
    dataset scope survives the lowering (fix pass F3). A conformed business
    time key groups by its truncation of the native member (issue #29); the
    half-open fetch range (lookback already included) predicates the native
    member before aggregation."""
    node = graph.datasets[dataset]
    collected: dict[str, RelationshipEdge] = {}
    for key in dim_keys:
        for edge in key.paths[dataset]:
            collected.setdefault(edge.to_dataset, edge)
    for _predicate, key in row_preds:
        for edge in key.paths[dataset]:
            collected.setdefault(edge.to_dataset, edge)
    order = _ordered_edges(graph, dataset, collected)

    # per-dataset field declarations: several datasets share one FROM clause,
    # so an unqualified name would bind ambiguously — resolve per dataset and
    # qualify with the branch alias instead of stripping the qualifier.
    hops = (dataset, *(edge.to_dataset for edge in order))
    fields_of: dict[str, dict[str, Any]] = {
        hop: {
            name: _strip_qualifiers(_parse(sql, f"field {name!r} of dataset '{hop}'"))
            for name, sql in graph.datasets[hop].expressions.items()
        }
        for hop in hops
    }
    aliases = {dataset: "s0"}

    def lower(tree: Any, home: str, context: str):
        """Resolve one authored expression against per-dataset field
        declarations, then qualify every source-column reference with its
        dataset's branch alias (a ``dataset.column`` qualifier names the
        dataset; unknown qualifiers bind to the declaring ``home`` dataset,
        like the single-dataset renderer)."""
        lowered = tree
        for column in list(tree.find_all(exp.Column)):
            hop = column.table if column.table in fields_of else home
            declared = fields_of[hop]
            if column.name not in declared:
                raise PlannerError(
                    "compile_failed",
                    f"{context}: column '{column.name}' is not a declared field of "
                    f"dataset '{hop}' in branch '{dataset}'",
                )
            resolved = _resolve_fields(declared[column.name].copy(), declared, set())
            for inner in resolved.find_all(exp.Column):
                inner.set("table", exp.to_identifier(aliases[hop]))
            if column is tree:
                lowered = resolved  # the expression IS one column: replace the root
            else:
                column.replace(resolved)
        return lowered

    select = exp.Select().from_(
        exp.alias_(_source_subquery(node.source, f"dataset '{dataset}' source"), aliases[dataset])
    )
    for index, edge in enumerate(order, start=1):
        target_alias = f"s{index}"
        aliases[edge.to_dataset] = target_alias
        target = exp.alias_(
            _source_subquery(
                graph.datasets[edge.to_dataset].source, f"dataset '{edge.to_dataset}' source"
            ),
            target_alias,
        )
        on = None
        for from_field, to_field in zip(edge.from_fields, edge.to_fields):
            condition = exp.EQ(
                this=lower(
                    exp.column(from_field),
                    edge.from_dataset,
                    f"relationship '{edge.name}' from key",
                ),
                expression=lower(
                    exp.column(to_field),
                    edge.to_dataset,
                    f"relationship '{edge.name}' to key",
                ),
            )
            on = condition if on is None else exp.And(this=on, expression=condition)
        # LEFT onto the unique target: unmatched fact rows keep their aggregate
        # under a NULL key instead of being silently dropped
        select = select.join(target, join_type="left", on=on)

    group_exprs = []
    for key in dim_keys:
        path = key.paths[dataset]
        home = path[-1].to_dataset if path else dataset
        native = lower(exp.column(key.members[dataset]), home, f"dimension '{key.dimension}'")
        expression = key.group_expression(native)
        group_exprs.append(expression)
        # F4: project under the branch's OUTPUT column — the alignment layer
        # (keys CTE, LEFT JOIN) references key.output(dataset) for BOTH branch
        # kinds, and a conformed key's native member may differ from the
        # canonical name (a time key's truncation differs from the raw member).
        select = select.select(exp.alias_(expression, key.output(dataset), quoted=True))
    for metric_name in sorted(metric_names):
        metric_node = graph.metrics[metric_name]
        if metric_node.derived:
            # a single-fact derived metric whose branch needs a lookup join: its
            # single-dataset layering cannot run here and it carries no window
            # declaration that would move it to the post-aggregate stage
            raise PlannerError(
                "derived_lookup_unsupported",
                f"metric '{metric_name}' is a single-fact derived metric and branch "
                f"'{dataset}' traverses a relationship lookup path — request it "
                "without the lookup dimension, or compute it post-aggregate with a "
                "window declaration",
            )
        tree = _parse(metric_node.expression, f"metric {metric_name!r}")
        tree = lower(tree, dataset, f"metric {metric_name!r}")
        select = select.select(exp.alias_(tree, metric_name, quoted=True))
    # row filters: routed predicates apply inside the branch, before grouping
    where = None
    for predicate, key in row_preds:
        path = key.paths[dataset]
        home = path[-1].to_dataset if path else dataset
        column = lower(exp.column(key.members[dataset]), home, f"filter on '{predicate.field}'")
        condition = _predicate_ast(column, predicate, parameters or {})
        where = condition if where is None else exp.And(this=where, expression=condition)
    # the conformed business time fetch range (half-open, lookback already
    # included) predicates this branch's NATIVE time member
    time_key = next((key for key in dim_keys if key.grain is not None), None)
    if time_key is not None:
        member = time_key.members[dataset]
        column = lower(exp.column(member), dataset, f"time range on '{member}'")
        for bound, comparison in (
            (fetch_bounds[0], exp.GTE),
            (fetch_bounds[1], exp.LT),
        ):
            if bound is None:
                continue
            condition = comparison(this=column.copy(), expression=_date_literal(bound))
            where = condition if where is None else exp.And(this=where, expression=condition)
    if where is not None:
        select = select.where(where)
    if group_exprs:
        select = select.group_by(*group_exprs)
    return select.sql(dialect="duckdb"), order


def _plain_predicates(
    graph: SemanticGraph,
    dataset: str,
    row_preds: Sequence[tuple[_Predicate, _DimKey]],
    parameters: dict[str, tuple[str, Any]],
) -> list[exp.Expression]:
    """Row predicates for a no-lookup branch, lowered UNQUALIFIED against the
    branch dataset's own field declarations — they pre-filter the branch
    source, so the single-dataset renderer (not planner-owned to extend)
    aggregates over the filtered population."""
    field_asts = {
        name: _strip_qualifiers(_parse(sql, f"field {name!r} of dataset '{dataset}'"))
        for name, sql in graph.datasets[dataset].expressions.items()
    }
    out: list[exp.Expression] = []
    for predicate, key in row_preds:
        member = key.members[dataset]
        tree = field_asts.get(member)
        column = (
            _resolve_fields(tree.copy(), field_asts, set())
            if tree is not None
            else exp.column(member)  # no usable dialect declaration: the column itself
        )
        out.append(_predicate_ast(column, predicate, parameters))
    return out


def _time_fetch_predicate(
    graph: SemanticGraph,
    dataset: str,
    time_key: _DimKey,
    bounds: tuple[date | None, date | None],
) -> exp.Expression | None:
    """The half-open fetch range on this branch's NATIVE time member, lowered
    unqualified against the branch dataset's own field declarations (lookback
    already folded into the start bound by the caller)."""
    member = time_key.members[dataset]
    field_asts = {
        name: _strip_qualifiers(_parse(sql, f"field {name!r} of dataset '{dataset}'"))
        for name, sql in graph.datasets[dataset].expressions.items()
    }
    tree = field_asts.get(member)
    column = (
        _resolve_fields(tree.copy(), field_asts, set())
        if tree is not None
        else exp.column(member)  # no usable dialect declaration: the column itself
    )
    where = None
    for bound, comparison in ((bounds[0], exp.GTE), (bounds[1], exp.LT)):
        if bound is None:
            continue
        condition = comparison(this=column.copy(), expression=_date_literal(bound))
        where = condition if where is None else exp.And(this=where, expression=condition)
    return where


def _branch_sql(
    graph: SemanticGraph,
    dataset: str,
    dim_keys: list[_DimKey],
    metric_names: list[str],
    requested: list[str],
    row_preds: Sequence[tuple[_Predicate, _DimKey]] = (),
    parameters: dict[str, tuple[str, Any]] | None = None,
    fetch_bounds: tuple[date | None, date | None] = (None, None),
) -> tuple[str, list[RelationshipEdge]]:
    """The branch SELECT (group keys in requested order, then its metrics).
    Branches whose dimensions OR routed row filters need a lookup path compile
    through the in-branch join builder; branches with no lookup path compile
    through the single-dataset renderer — including single-dataset derived
    layering — so both authoring layouts and legacy models share one compiler
    (ADR-0008), with row predicates pre-filtering the branch source. A
    conformed business time key groups every branch by the truncation of its
    native member under the key's output column, and the half-open fetch range
    (lookback included) predicates the native member before aggregation.
    ``requested`` are the metrics whose outputs the branch must keep through
    any derived layer (F5 — a base metric requested together with a same-fact
    derived metric on top of it needs both columns)."""
    if any(key.paths[dataset] for key in dim_keys) or any(
        key.paths[dataset] for _predicate, key in row_preds
    ):
        return _joined_branch_sql(
            graph, dataset, dim_keys, metric_names, row_preds, parameters, fetch_bounds
        )
    time_key = next((key for key in dim_keys if key.grain is not None), None)
    sub = _submodel(graph, dataset, metric_names, time_key)
    plain = _plain_predicates(graph, dataset, row_preds, parameters or {})
    if time_key is not None:
        fetch = _time_fetch_predicate(graph, dataset, time_key, fetch_bounds)
        if fetch is not None:
            plain.append(fetch)
    if plain:
        filtered = (
            exp.Select()
            .select("*")
            .from_(_source_subquery(graph.datasets[dataset].source, f"dataset '{dataset}' source"))
        )
        where = None
        for condition in plain:
            where = condition if where is None else exp.And(this=where, expression=condition)
        filtered = filtered.where(where)
        sub["semantic_model"][0]["datasets"][0]["source"] = filtered.sql(dialect="duckdb")
    try:
        return (
            render(
                sub,
                dimensions=[key.output(dataset) for key in dim_keys],
                carry=[name for name in requested if name in metric_names],
            ),
            [],
        )
    except RenderError as exc:
        raise PlannerError("compile_failed", str(exc)) from exc


def _is_bare_count(expression: str) -> bool:
    """A top-level COUNT aggregate — the one measure whose absence reads 0
    instead of NULL (spec rev 1, "Query and result contract")."""
    try:
        tree = _parse(expression, "metric")
    except RenderError:
        return False
    return isinstance(tree, exp.Count)


@dataclass(frozen=True)
class _PostStage:
    """The declared post-alignment computation (issue #29): cross-fact derived
    metrics and windowed metrics in dependency level order, the aligned output
    projection with explicit fills, and the display trim over the conformed
    time column. Derived arithmetic and rolling, cumulative, prior-period,
    ranking and value windows operate HERE — after the branches merge, never
    inside a fact branch (spec rev 1 "Query and result contract")."""

    metrics: tuple[_PostMetric, ...]  # level-ordered, deps before dependents
    time_column: str | None  # the aligned conformed time key, when declared
    grain: str | None  # the requested time grain (value-window RANGE frames)
    trim: tuple[date | None, date | None]  # half-open display range
    partition: tuple[str, ...]  # non-time dimensions (window PARTITION BY)
    output: tuple[str, ...]  # final output columns: dims, time, requested metrics
    fills: dict[str, Any]  # metric -> explicit output fill (never a denominator)


def _post_expression(sql: str, context: str) -> exp.Expression:
    """One declared post-aggregate expression over aligned metric columns,
    with every division guarded: a zero or missing denominator yields NULL,
    never an error or an infinity (spec rev 1 "Query and result contract")."""
    try:
        tree = _strip_qualifiers(_parse(sql, context))
    except RenderError as exc:
        raise PlannerError("compile_failed", str(exc)) from exc
    for div in list(tree.find_all(exp.Div)):
        div.set(
            "expression",
            exp.Nullif(this=div.expression, expression=exp.Literal.number(0)),
        )
    return tree


def _window_expression(name: str, window: WindowDecl, stage: _PostStage) -> exp.Expression:
    """The declared window form over the metric's own aligned column: ordered
    by the conformed time key and partitioned by the non-time dimensions, so a
    window never leaks across dimension groups."""
    column = exp.column(name, quoted=True)
    partition = [exp.column(member, quoted=True) for member in stage.partition] or None
    if window.kind == "prior_period":
        return exp.Window(
            this=exp.Lag(this=column),
            partition_by=partition,
            order=exp.Order(
                expressions=[exp.Ordered(this=exp.column(stage.time_column or "", quoted=True))]
            ),
        )
    if window.kind == "ranking":
        # ranking orders the DISPLAYED rows by value: it runs after the trim
        return exp.Window(
            this=exp.Rank(),
            partition_by=partition,
            order=exp.Order(
                expressions=[exp.Ordered(this=column, desc=window.direction == "desc")]
            ),
        )
    order = exp.Order(
        expressions=[exp.Ordered(this=exp.column(stage.time_column or "", quoted=True))]
    )
    if window.kind == "rolling":
        size = window.size or 1  # a rolling window always carries a size (load)
        spec = exp.WindowSpec(kind="ROWS", start=f"{size - 1} PRECEDING", end="CURRENT ROW")
    elif window.kind == "cumulative":
        spec = exp.WindowSpec(kind="ROWS", start="UNBOUNDED PRECEDING", end="CURRENT ROW")
    else:  # value_window: a RANGE frame over the time axis by grain periods
        unit, per = _INTERVAL_UNIT[stage.grain or "day"]
        size = window.size or 1
        spec = exp.WindowSpec(
            kind="RANGE",
            start=f"INTERVAL {size * per} {unit} PRECEDING",
            end="CURRENT ROW",
        )
    return exp.Window(
        this=_WINDOW_FUNCTIONS[window.function](this=column),
        partition_by=partition,
        order=order,
        spec=spec,
    )


def _layer(
    tree: exp.Expression, columns: list[str], additions: Sequence[tuple[str, exp.Expression]]
) -> tuple[exp.Select, list[str]]:
    """One projection layer above ``tree``: carries ``columns``, computes each
    addition over the INPUT columns (a replaced column keeps its position, a
    new one is appended) — the same one-level-at-a-time shape as the
    single-dataset renderer's derived layering."""
    added = dict(additions)
    select = exp.Select()
    for name in columns:
        expression = added.pop(name, None)
        if expression is None:
            expression = exp.column(name, quoted=True)
        select = select.select(exp.alias_(expression, name, quoted=True))
    for name, expression in added.items():
        select = select.select(exp.alias_(expression, name, quoted=True))
        columns.append(name)
    return select.from_(exp.Subquery(this=tree)), columns


def _final_sql(
    branch_sqls: list[str],
    branch_keys: list[list[tuple[str, str]]],  # per branch: (canonical, output col)
    columns: list[tuple[str, int, str, bool]],  # (metric, branch idx, col, bare count)
    result_filters: Sequence[_Predicate] = (),
    order: Sequence[tuple[str, bool]] = (),
    limit: int | None = None,
    parameters: dict[str, tuple[str, Any]] | None = None,
    stage: _PostStage | None = None,
) -> str:
    """The ONE guarded SELECT: CTE per branch, a keys CTE unioning the branch
    group keys (UNION dedupes, NULL-inclusive), and an outer SELECT aligning
    aggregate outputs with null-safe equality. No-dimension plans cross-join
    the single-row aggregates instead. Above the aligned output the declared
    post-aggregate stage runs in order (issue #29): derived metrics level by
    level (division guarded against zero/missing denominators), time-frame
    windows, the display trim, ranking windows, then the output projection
    with explicit fills. Aggregate/RESULT filters, declared ordering and the
    bounded limit apply AFTER all of that, on a wrapper SELECT over the final
    output (its WHERE/ORDER BY reference real subquery columns, never select
    aliases — spec rev 1, "Query and result")."""
    names = [f"b{index}" for index in range(len(branch_sqls))]
    outer = exp.Select()
    for canonical, _output in branch_keys[0] if branch_keys else []:
        outer = outer.select(
            exp.alias_(exp.column(canonical, table="keys", quoted=True), canonical, quoted=True)
        )
    for metric, index, column, bare_count in columns:
        expression = exp.column(column, table=names[index], quoted=True)
        if bare_count:
            expression = exp.Coalesce(this=expression, expressions=[exp.Literal.number(0)])
        outer = outer.select(exp.alias_(expression, metric, quoted=True))
    if branch_keys[0]:
        outer = outer.from_("keys")
        for index, name in enumerate(names):
            on = None
            for canonical, native in branch_keys[index]:
                condition = exp.NullSafeEQ(
                    this=exp.column(canonical, table="keys", quoted=True),
                    expression=exp.column(native, table=name, quoted=True),
                )
                on = condition if on is None else exp.And(this=on, expression=condition)
            outer = outer.join(name, join_type="left", on=on)
    else:
        outer = outer.from_(names[0])
        for name in names[1:]:
            outer = outer.join(name, join_type="cross")
    tree = outer
    for name, sql in zip(names, branch_sqls):
        tree = tree.with_(name, as_=sqlglot.parse_one(sql), copy=False)
    if branch_keys[0]:
        projections = []
        for index, name in enumerate(names):
            projection = exp.Select()
            for canonical, native in branch_keys[index]:
                projection = projection.select(
                    exp.alias_(exp.column(native, table=name, quoted=True), canonical, quoted=True)
                )
            projections.append(projection.from_(name))
        union = projections[0]
        for projection in projections[1:]:
            union = exp.union(union, projection)
        tree = tree.with_("keys", as_=union, copy=False)
    current = [*([canonical for canonical, _output in branch_keys[0]] if branch_keys else [])]
    current.extend(metric for metric, _index, _column, _bare in columns)
    if stage is not None:
        # derived metrics, one level per dependency level — a windowed BASE
        # aggregate skips the expression layer: its branch already produced
        # the aligned column, only its window applies below (C4)
        for level in sorted({metric.level for metric in stage.metrics if not metric.base}):
            tree, current = _layer(
                tree,
                current,
                [
                    (metric.name, _post_expression(metric.expression, f"metric {metric.name!r}"))
                    for metric in stage.metrics
                    # a windowed BASE already produced its aligned column in
                    # its branch; re-applying its aggregate expression here
                    # would reference raw columns that no longer exist above
                    # the alignment (C4 recheck residual)
                    if metric.level == level and not metric.base
                ],
            )
        # time-frame windows run over the fetched range, BEFORE the trim
        for metric in stage.metrics:
            window = metric.window
            if window is None or window.kind not in _TIME_FRAME_KINDS:
                continue
            tree, current = _layer(
                tree,
                current,
                [(metric.name, _window_expression(metric.name, window, stage))],
            )
        # the displayed range trims the fetched lookback away. A bucket whose
        # period OVERLAPS the display start stays displayed (the January group
        # of a [2026-01-15, ...) range): grouped keys are period starts, so the
        # start bound compares one grain period back, keeping every bucket
        # whose period reaches past the display start (C2, candidate review)
        if stage.time_column is not None and any(bound is not None for bound in stage.trim):
            column = exp.column(stage.time_column, quoted=True)
            trim = None
            if stage.trim[0] is not None:
                trim = exp.GT(
                    this=column.copy(),
                    expression=_date_literal(
                        _shift_periods(stage.grain or "day", stage.trim[0], -1)
                    ),
                )
            if stage.trim[1] is not None:
                condition = exp.LT(this=column.copy(), expression=_date_literal(stage.trim[1]))
                trim = condition if trim is None else exp.And(this=trim, expression=condition)
            tree = exp.Select().select("*").from_(exp.Subquery(this=tree)).where(trim)
        # ranking windows order the DISPLAYED rows, so they run after the trim
        for metric in stage.metrics:
            window = metric.window
            if window is None or window.kind != "ranking":
                continue
            tree, current = _layer(
                tree,
                current,
                [(metric.name, _window_expression(metric.name, window, stage))],
            )
        # the output projection: requested columns only, explicit fills applied
        # here and nowhere earlier (never a hidden denominator)
        if stage.fills or list(stage.output) != current:
            projection = exp.Select()
            for name in stage.output:
                expression = exp.column(name, quoted=True)
                if name in stage.fills:
                    expression = exp.Coalesce(
                        this=expression, expressions=[_fill_literal(stage.fills[name])]
                    )
                projection = projection.select(exp.alias_(expression, name, quoted=True))
            tree = projection.from_(exp.Subquery(this=tree))
    if result_filters or order or limit:
        wrapper = exp.Select().select("*").from_(exp.Subquery(this=tree))
        where = None
        for predicate in result_filters:
            condition = _predicate_ast(
                exp.column(predicate.field, quoted=True), predicate, parameters or {}
            )
            where = condition if where is None else exp.And(this=where, expression=condition)
        if where is not None:
            wrapper = wrapper.where(where)
        for field, descending in order:
            wrapper = wrapper.order_by(
                exp.Ordered(this=exp.column(field, quoted=True), desc=descending)
            )
        if limit is not None:
            wrapper = wrapper.limit(limit)
        tree = wrapper
    return tree.sql(dialect="duckdb")


def _run_live_audits(
    connection: Any,
    sql: str,
    graph: SemanticGraph,
    participating: dict[str, RelationshipEdge],
    guarded: set[str],
) -> tuple[list[AuditRecord], str, str]:
    """The per-request live audits shared by both planners: exact target-key
    recheck per participating relationship, the structural grain guard on every
    participating AUTHORED source, and an EXPLAIN bind of the final statement.
    Raises :class:`PlannerError` (before any result SELECT could execute) on
    any failure; returns the audit records plus the relationship-audit
    outcome/detail."""
    audits: list[AuditRecord] = []
    for edge in sorted(participating.values(), key=lambda e: e.name):
        source = graph.datasets[edge.to_dataset].source
        try:
            audit = relationship_target_audit(connection, source, resolved_target_keys(graph, edge))
        except Exception as exc:
            raise PlannerError(
                "relationship_audit_failed",
                f"relationship '{edge.name}': target-key audit did not bind: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        if audit.duplicates:
            raise PlannerError(
                "relationship_key_duplicate",
                f"relationship '{edge.name}': target key {list(edge.to_fields)} on "
                f"dataset '{edge.to_dataset}' is not unique — {audit.duplicates} "
                f"duplicate key tuple(s) over {audit.rows} rows (per-request recheck "
                "on the mutable source; refusing before any result SELECT executes)",
            )
        if audit.null_rows:
            raise PlannerError(
                "relationship_key_null",
                f"relationship '{edge.name}': target key {list(edge.to_fields)} on "
                f"dataset '{edge.to_dataset}' has {audit.null_rows} row(s) with a "
                "NULL key component (per-request recheck; refusing before any "
                "result SELECT executes)",
            )
        audits.append(
            AuditRecord(
                f"relationship:{edge.name}",
                "passed",
                f"target key {list(edge.to_fields)} unique and non-NULL over {audit.rows} rows",
            )
        )
    if participating:
        outcome = "passed"
        detail = f"{len(participating)} participating relationship(s) rechecked on this request"
    else:
        outcome, detail = "not-run", "no relationship traversal participates in this request"
    # F2: the legacy per-column guard belongs to AUTHORED sources — an
    # embedded or pre-joined table inside a declared source cannot bypass
    # it. The planner's GENERATED relationship joins are proven by the exact
    # tuple audit above, which accepts composite keys whose components
    # repeat while every tuple stays unique; re-judging them per column
    # would refuse valid composite lookups (review c90ca081 F2).
    for name in sorted(guarded):
        try:
            check_grain_preserving(connection, graph.datasets[name].source)
        except ValueError as exc:  # GRAIN_GUIDANCE verbatim
            raise PlannerError("grain_not_preserving", str(exc)) from exc
        audits.append(AuditRecord(f"grain:{name}", "passed"))
    try:
        # nosemgrep — planner-generated sqlglot AST output, re-parsed by the
        # caller; EXPLAIN binds without executing (no-unvalidated-execution
        # invariant). pi-lens-ignore: python-sql-injection — `sql` is the
        # planner's own AST render, never caller text; requests carry names only
        connection.execute(f"EXPLAIN {sql}")  # nosemgrep
    except Exception as exc:
        raise PlannerError(
            "bind_failed",
            f"compiled plan failed the EXPLAIN bind check: {type(exc).__name__}: {exc}",
        ) from exc
    return audits, outcome, detail


def plan_query(
    graph: SemanticGraph,
    request: dict,
    connection: Any = None,
) -> QueryPlan:
    """Compile a validated graph plus a named-metric/dimension request into one
    guarded SELECT plus bounded plan metadata. With ``connection`` (the
    project's configured DuckDB session) the plan performs the per-request
    live audits; without it the plan is compile-only and the relationship
    audit reports not-run. Refusals raise :class:`PlannerError` BEFORE any
    result SELECT could execute."""
    metric_names, dimension_names = _parse_request(request)
    unknown = [name for name in metric_names if name not in graph.metrics]
    if unknown:
        raise PlannerError(
            "unknown_metric",
            f"unknown metric(s) {unknown}",
            candidates=tuple(sorted(graph.metrics)),
        )
    collisions = sorted(set(metric_names) & set(dimension_names))
    if collisions:
        raise PlannerError(
            "name_collision",
            f"name(s) {collisions} requested as both metric and dimension — output "
            "columns must stay unambiguous",
        )

    memo: dict[str, str | None] = {}
    # Stage classification (issue #29): a metric aggregates INSIDE its fact
    # branch unless it is a cross-fact derived metric (no single owning
    # dataset — it resolves after the branches merge) or a windowed DERIVED
    # metric (its declared window moves the computation to the post-aggregate
    # stage). A windowed BASE aggregate keeps its home branch (C4): the branch
    # exposes the aggregate column and the declared window applies
    # post-alignment over it — never inside the branch.
    owner_of: dict[str, str | None] = {}
    closures = {name: _closure(graph, name) for name in metric_names}
    for name in sorted({member for closure in closures.values() for member in closure}):
        node = graph.metrics[name]
        owner_of[name] = (
            None if node.window is not None and node.derived else _resolve_owner(graph, name, memo)
        )

    branch_datasets = sorted({owner for owner in owner_of.values() if owner is not None})
    branch_metrics: dict[str, list[str]] = {dataset: [] for dataset in branch_datasets}
    for name in metric_names:
        for member in closures[name]:
            owner = owner_of[member]
            if (
                owner is not None
                and owner in branch_metrics
                and member not in branch_metrics[owner]
            ):
                branch_metrics[owner].append(member)

    conformed_by_name = {edge.name: edge for edge in graph.conformed_dimensions}
    time_request = _parse_time(request["time"]) if request.get("time") is not None else None
    if time_request is not None:
        if time_request.dimension in dimension_names:
            raise PlannerError(
                "time_invalid",
                f"the time dimension {time_request.dimension!r} may not also be a "
                "requested dimension — the aligned time key is one output column",
            )
        if time_request.dimension in metric_names:
            raise PlannerError(
                "name_collision",
                f"{time_request.dimension!r} names both the requested time dimension and "
                "a metric — output columns must stay unambiguous",
            )

    # every requested windowed metric names its declared form; a time-frame
    # window needs the declared conformed business time as its ordering axis
    windowed = [name for name in metric_names if graph.metrics[name].window is not None]
    time_frame = [
        name
        for name in windowed
        if graph.metrics[name].window.kind in _TIME_FRAME_KINDS  # pyright: ignore[reportOptionalMemberAccess]
    ]
    if time_frame and time_request is None:
        raise PlannerError(
            "window_requires_time",
            f"metric(s) {time_frame} declare a time-frame window but the request "
            "declares no conformed primary business time — declare 'time' with the "
            "window's ordering axis",
            candidates=tuple(sorted(metric_names)),
        )

    dim_keys = [
        _resolve_field_key(graph, name, branch_datasets, conformed_by_name, "dimension")
        for name in dimension_names
    ]
    time_key = (
        _resolve_time_key(graph, time_request, branch_datasets, conformed_by_name)
        if time_request is not None
        else None
    )
    if time_key is not None:
        dim_keys.append(time_key)

    # the fetch range: lookback precedes the trim (spec rev 1 "Query and result
    # contract"). A cumulative frame needs EVERY preceding group, so its fetch
    # start opens up while the displayed range still trims.
    fetch_start = fetch_end = None
    if time_request is not None:
        lookbacks: list[int] = []
        unbounded = False
        for name in windowed:
            window = graph.metrics[name].window
            if window is None:
                continue
            lookback = _lookback_groups(window)
            if lookback is None:
                unbounded = True  # a cumulative frame needs every preceding group
            else:
                lookbacks.append(lookback)
        fetch_end = time_request.end
        needed = max(lookbacks, default=0)
        if time_request.start is not None and not unbounded:
            # the native population is the half-open range on each fact's
            # NATIVE time; a bounded lookback (value windows) extends it back
            # by whole grain periods from the display start's period
            fetch_start = (
                _shift_periods(
                    time_request.grain,
                    _truncate(time_request.grain, time_request.start),
                    -needed,
                )
                if needed > 0
                else time_request.start
            )
    fetch_bounds = (fetch_start, fetch_end)

    parameters = _parse_parameters(request.get("parameters"))
    predicates, segment_names = _parse_predicates(request)
    order, limit = _parse_order_limit(request)
    output_columns = set(metric_names) | set(dimension_names)
    if time_request is not None:
        output_columns.add(time_request.dimension)
    for field, _descending in order:
        if field not in output_columns:
            raise PlannerError(
                "order_invalid",
                f"order field {field!r} is not an output column of this request",
                candidates=tuple(sorted(output_columns)),
            )

    row_filters: list[tuple[_Predicate, _DimKey]] = []
    result_filters: list[_Predicate] = []
    for predicate in predicates:
        # mf-t3 review F4: segments expand to validated ROW predicates — a
        # predicate naming a metric inside a segment is a result-stage filter
        # and refuses instead of silently routing past grouping (spec rev 1,
        # "Query and result contract"); DIRECT result filters stay supported
        if predicate.origin != "filters" and (
            predicate.field in metric_names or predicate.field in graph.metrics
        ):
            raise PlannerError(
                "filter_invalid",
                f"{predicate.origin}: predicate on metric '{predicate.field}' is a "
                "result-stage filter — segments expand to row predicates only; use a "
                "direct result filter",
            )
        is_field = predicate.field in conformed_by_name or any(
            predicate.field in node.fields for node in graph.datasets.values()
        )
        if predicate.field in metric_names:
            if is_field:
                raise PlannerError(
                    "ambiguous_filter",
                    f"filter field {predicate.field!r} names both a declared field and a "
                    "requested metric — a result filter must name a metric unambiguously",
                )
            result_filters.append(predicate)  # on a selected aggregate: AFTER grouping
            continue
        if predicate.field in graph.metrics:
            raise PlannerError(
                "unknown_filter",
                f"filter field {predicate.field!r} names a declared metric that is not "
                "part of this request — add it to 'metrics' to filter its aggregate",
                candidates=tuple(metric_names),
            )
        row_filters.append(
            (
                predicate,
                _resolve_field_key(
                    graph, predicate.field, branch_datasets, conformed_by_name, "filter"
                ),
            )
        )

    # the aligned projection carries the requested branch metrics plus every
    # branch metric a post-aggregate metric consumes (its expression resolves
    # over the ALIGNED columns, so the branches must expose the dependencies)
    # plus every windowed metric — a windowed BASE aggregate rides the stage
    # for its window alone, its column already aggregated in-branch (C4)
    post_needed: list[str] = []
    for name in metric_names:
        for member in closures[name]:
            if (
                owner_of[member] is None or graph.metrics[member].window is not None
            ) and member not in post_needed:
                post_needed.append(member)
    has_post = bool(post_needed)
    branch_sqls: list[str] = []
    branch_plans: list[BranchPlan] = []
    branch_keys: list[list[tuple[str, str]]] = []
    participating: dict[str, RelationshipEdge] = {}
    for dataset in branch_datasets:
        routed = [(predicate, key) for predicate, key in row_filters if dataset in key.members]
        sql, edges = _branch_sql(
            graph,
            dataset,
            dim_keys,
            branch_metrics[dataset],
            # without post-aggregate metrics the branch keeps exactly the
            # requested outputs; with them it also exposes their dependencies
            [name for name in branch_metrics[dataset] if has_post or name in metric_names],
            routed,
            parameters,
            fetch_bounds,
        )
        branch_sqls.append(sql)
        branch_plans.append(
            BranchPlan(
                dataset=dataset,
                metrics=tuple(sorted(branch_metrics[dataset])),
                joins=tuple(edge.name for edge in edges),
                keys=tuple((key.dimension, key.members[dataset]) for key in dim_keys),
                filters=tuple(dict.fromkeys(predicate.field for predicate, _key in routed)),
            )
        )
        branch_keys.append([(key.dimension, key.output(dataset)) for key in dim_keys])
        for edge in edges:
            participating[edge.name] = edge

    aligned_metrics = [name for name in metric_names if owner_of[name] is not None]
    if has_post:
        # the branches exposed their post-aggregate dependencies as outputs
        for dataset in branch_datasets:
            for name in branch_metrics[dataset]:
                if name not in aligned_metrics:
                    aligned_metrics.append(name)
    columns: list[tuple[str, int, str, bool]] = []
    for name in aligned_metrics:
        owner = owner_of[name]
        if owner is None:
            continue  # a post-aggregate metric: no branch column of its own
        columns.append(
            (
                name,
                branch_datasets.index(owner),
                name,
                _is_bare_count(graph.metrics[name].expression),
            )
        )

    # the post-aggregate stage: derived metrics level by level (deps first),
    # each windowed metric windowed over its own column, fills on the OUTPUT
    def post_level(name: str) -> int:
        deps = [dep for dep in graph.metrics[name].deps if owner_of.get(dep) is None]
        return 0 if not deps else 1 + max(post_level(dep) for dep in deps)

    post_metrics = tuple(
        _PostMetric(
            name=name,
            expression=graph.metrics[name].expression,
            level=post_level(name),
            window=graph.metrics[name].window,
            base=owner_of[name] is not None,
        )
        for name in post_needed
    )
    # a declared fill is an output-stage obligation of its own: the projection
    # runs whenever a requested metric declares one, never only because an
    # unrelated request feature (a derived metric, time) built the stage (C3)
    fills = {
        name: graph.metrics[name].fill
        for name in metric_names
        if graph.metrics[name].fill is not None
    }
    stage = (
        _PostStage(
            metrics=post_metrics,
            time_column=time_request.dimension if time_request is not None else None,
            grain=time_request.grain if time_request is not None else None,
            trim=(
                (time_request.start, time_request.end) if time_request is not None else (None, None)
            ),
            partition=tuple(dimension_names),
            output=(
                (*dimension_names, time_request.dimension, *metric_names)
                if time_request is not None
                else (*dimension_names, *metric_names)
            ),
            fills=fills,
        )
        if (has_post or time_request is not None or fills)
        else None
    )
    sql = _final_sql(
        branch_sqls,
        branch_keys,
        columns,
        result_filters,
        order,
        limit,
        parameters,
        stage,
    )
    statements = sqlglot.parse(sql)
    if len(statements) != 1:  # self-check: the guarded SELECT is one statement
        raise PlannerError(
            "not_one_statement",
            f"compiled plan is {len(statements)} statements, not one "
            "(no-unvalidated-execution invariant, spec §6)",
        )

    if connection is not None:
        guarded = sorted(set(branch_datasets) | {e.to_dataset for e in participating.values()})
        audits, relationship_outcome, relationship_detail = _run_live_audits(
            connection, sql, graph, participating, set(guarded)
        )
    else:
        audits = []
        relationship_outcome = "not-run"
        relationship_detail = "compile-only plan — no connection, no live relationship audit"
    audits.append(AuditRecord("relationship_audit", relationship_outcome, relationship_detail))
    return QueryPlan(
        sql=sql,
        metrics=tuple(metric_names),
        dimensions=tuple(dimension_names),
        branches=tuple(branch_plans),
        conformed_keys=tuple(key.conformed for key in dim_keys if key.conformed is not None),
        audits=tuple(audits),
        relationship_audit=relationship_outcome,
        segments=segment_names,
        time_dimension=time_request.dimension if time_request is not None else None,
        time_grain=time_request.grain if time_request is not None else None,
        windows=tuple(name for name in metric_names if graph.metrics[name].window is not None),
        fetch_bounds=(fetch_start, fetch_end) if time_request is not None else None,
    )


# --- Detail planner (issue #28) -----------------------------------------------


@dataclass(frozen=True)
class DetailField:
    """One projected detail field and its PROVEN path from the root dataset
    (relationship names, root outward). Bounded lineage per field."""

    name: str
    dataset: str  # the declaring dataset (root or a many_to_one lookup target)
    path: tuple[str, ...]


@dataclass(frozen=True)
class DetailPlan:
    """One guarded detail SELECT plus bounded plan metadata: the fixed root
    dataset, the projected fields with their proven paths, the traversed
    relationships, and the performed audits."""

    sql: str
    dataset: str
    fields: tuple[DetailField, ...]
    joins: tuple[str, ...]
    audits: tuple[AuditRecord, ...]
    relationship_audit: str  # passed | not-run (never silently passed)


def _child_side_chain(graph: SemanticGraph, root: str, home: str) -> tuple[str, ...] | None:
    """The relationship chain ``root -> home`` traversed BACKWARDS along edge
    directions — root on the unique-target side reaching its CHILD datasets.
    That is the fan-out side: a detail traversal onto it would multiply the
    root grain, so the planner names it and refuses (spec rev 1, acceptance 5).
    """
    if root == home:
        return ()
    queue: list[tuple[str, tuple[str, ...]]] = [(root, ())]
    seen = {root}
    while queue:
        dataset, chain = queue.pop(0)
        for edge in graph.relationships:
            if edge.to_dataset != dataset or edge.from_dataset in seen:
                continue
            extended = (*chain, edge.name)
            if edge.from_dataset == home:
                return extended
            seen.add(edge.from_dataset)
            queue.append((edge.from_dataset, extended))
    return None


def plan_detail(
    graph: SemanticGraph,
    request: dict,
    connection: Any = None,
) -> DetailPlan:
    """Compile ONE guarded detail SELECT (issue #28): a fixed, declared root
    dataset whose fields project directly, and other fields only through
    proven ``many_to_one``/``one_to_one`` multi-hop lookup paths — LEFT joins
    onto unique targets, so the output keeps exactly ONE row per root key: no
    aggregates, no fan-out. A child-side traversal (root on the target side of
    a relationship reaching its many side) refuses BEFORE execution, as do
    unknown/ambiguous/unreachable fields. With ``connection`` the plan performs
    the same per-request live audits as :func:`plan_query`; without it the plan
    is compile-only and the relationship audit reports not-run."""
    if not isinstance(request, dict):
        raise PlannerError(
            "request_invalid", "detail request must be a mapping {'dataset': ..., 'fields': [...]}"
        )
    unknown = sorted(set(request) - _DETAIL_REQUEST_KEYS)
    if unknown:
        raise PlannerError(
            "request_invalid",
            f"unknown detail request key(s) {unknown}; allowed: {sorted(_DETAIL_REQUEST_KEYS)}",
        )
    dataset = request.get("dataset")
    if not isinstance(dataset, str) or dataset not in graph.datasets:
        raise PlannerError(
            "unknown_dataset",
            f"unknown root dataset {dataset!r}",
            candidates=tuple(sorted(graph.datasets)),
        )
    fields = request.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(name, str) for name in fields)
    ):
        raise PlannerError("request_invalid", "'fields' must be a non-empty list of field names")
    fields = list(dict.fromkeys(fields))

    resolved: list[DetailField] = []
    collected: dict[str, RelationshipEdge] = {}
    for field in fields:
        # the root is FIXED: its own field is the unambiguous root-grain
        # projection — no cross-dataset equivalence is inferred (spec rev 1 §3)
        if field in graph.datasets[dataset].fields:
            resolved.append(DetailField(name=field, dataset=dataset, path=()))
            continue
        owners = sorted(name for name, node in graph.datasets.items() if field in node.fields)
        if not owners:
            raise PlannerError(
                "unknown_field",
                f"unknown detail field {field!r}",
                candidates=tuple(sorted(graph.datasets[dataset].fields)),
            )
        if len(owners) > 1:
            raise PlannerError(
                "ambiguous_field",
                f"field '{field}' exists on datasets {owners} — no equivalence is "
                "inferred from identical column names (spec rev 1 §3)",
            )
        home = owners[0]
        path = _lookup_path(graph, dataset, home)
        if path is None:
            child = _child_side_chain(graph, dataset, home)
            if child is not None:
                raise PlannerError(
                    "detail_child_side",
                    f"field '{field}' lives on dataset '{home}', reachable from root "
                    f"'{dataset}' only through the CHILD side "
                    f"({' -> '.join(child) if child else 'the root itself'}) — that "
                    "traversal multiplies the root grain and refuses before execution "
                    "(spec rev 1, acceptance 5)",
                    candidates=child or (),
                )
            raise PlannerError(
                "unreachable_field",
                f"field '{field}' (dataset '{home}') is not reachable from root "
                f"'{dataset}' through proven many_to_one/one_to_one paths",
            )
        resolved.append(
            DetailField(name=field, dataset=home, path=tuple(edge.name for edge in path))
        )
        for edge in path:
            collected.setdefault(edge.to_dataset, edge)

    order = _ordered_edges(graph, dataset, collected)
    # the same per-dataset lowering as the metric branches: field expressions
    # resolve against the declaring dataset and carry its branch alias
    hops = (dataset, *(edge.to_dataset for edge in order))
    fields_of: dict[str, dict[str, Any]] = {
        hop: {
            name: _strip_qualifiers(_parse(sql, f"field {name!r} of dataset '{hop}'"))
            for name, sql in graph.datasets[hop].expressions.items()
        }
        for hop in hops
    }
    aliases = {dataset: "s0"}

    def lower(tree: Any, home: str, context: str):
        lowered = tree
        for column in list(tree.find_all(exp.Column)):
            hop = column.table if column.table in fields_of else home
            declared = fields_of[hop]
            if column.name not in declared:
                raise PlannerError(
                    "compile_failed",
                    f"{context}: column '{column.name}' is not a declared field of "
                    f"dataset '{hop}' in the detail projection",
                )
            resolved_tree = _resolve_fields(declared[column.name].copy(), declared, set())
            for inner in resolved_tree.find_all(exp.Column):
                inner.set("table", exp.to_identifier(aliases[hop]))
            if column is tree:
                lowered = resolved_tree
            else:
                column.replace(resolved_tree)
        return lowered

    select = exp.Select().from_(
        exp.alias_(
            _source_subquery(graph.datasets[dataset].source, f"dataset '{dataset}' source"),
            aliases[dataset],
        )
    )
    for index, edge in enumerate(order, start=1):
        target_alias = f"s{index}"
        aliases[edge.to_dataset] = target_alias
        target = exp.alias_(
            _source_subquery(
                graph.datasets[edge.to_dataset].source,
                f"dataset '{edge.to_dataset}' source",
            ),
            target_alias,
        )
        on = None
        for from_field, to_field in zip(edge.from_fields, edge.to_fields):
            condition = exp.EQ(
                this=lower(
                    exp.column(from_field),
                    edge.from_dataset,
                    f"relationship '{edge.name}' from key",
                ),
                expression=lower(
                    exp.column(to_field),
                    edge.to_dataset,
                    f"relationship '{edge.name}' to key",
                ),
            )
            on = condition if on is None else exp.And(this=on, expression=condition)
        # LEFT onto the proven unique target: one row per root key, no fan-out
        select = select.join(target, join_type="left", on=on)
    for field_info in resolved:
        expression = lower(
            exp.column(field_info.name), field_info.dataset, f"detail field {field_info.name!r}"
        )
        # mf-t3 review F2 (+ recheck micro-fix): a declared field whose RESOLVED
        # expression aggregates (or otherwise expands rows) would turn the detail
        # projection into an aggregate SELECT — one row instead of one row per
        # root key. Refused before audits/execution (spec rev 1, acceptance 5).
        # Non-aggregating analytic functions (LAG/LEAD/rank family) preserve the
        # row count and stay projectable — sqlglot types them as AggFunc
        # subclasses, so the guard classifies each node instead of blanket-
        # refusing; a true aggregate nested inside one is still caught as its
        # own node (e.g. LAG(SUM(x))).
        _analytic_ok = (
            exp.Lag,
            exp.Lead,
            exp.FirstValue,
            exp.LastValue,
            exp.NthValue,
            exp.Rank,
            exp.DenseRank,
            exp.CumeDist,
            exp.PercentRank,
        )
        if any(
            not isinstance(node, _analytic_ok) for node in expression.find_all(exp.AggFunc)
        ) or any(expression.find_all(exp.Unnest)):
            raise PlannerError(
                "detail_field_aggregate",
                f"detail field {field_info.name!r} resolves to an aggregate or "
                "row-expanding expression — detail projects one row per root key "
                "with no aggregates or fan-out (spec rev 1, acceptance 5)",
            )
        select = select.select(exp.alias_(expression, field_info.name, quoted=True))
    sql = select.sql(dialect="duckdb")
    statements = sqlglot.parse(sql)
    if len(statements) != 1:  # self-check: the guarded SELECT is one statement
        raise PlannerError(
            "not_one_statement",
            f"compiled detail plan is {len(statements)} statements, not one "
            "(no-unvalidated-execution invariant, spec §6)",
        )

    participating = {edge.to_dataset: edge for edge in order}
    if connection is not None:
        guarded = {dataset} | set(participating)
        audits, relationship_outcome, _detail = _run_live_audits(
            connection, sql, graph, participating, guarded
        )
    else:
        audits = []
        relationship_outcome = "not-run"
    audits.append(
        AuditRecord(
            "relationship_audit",
            relationship_outcome,
            (
                f"{len(participating)} participating relationship(s) rechecked on this request"
                if connection is not None and participating
                else "no relationship traversal participates in this request"
                if connection is not None
                else "compile-only plan — no connection, no live relationship audit"
            ),
        )
    )
    return DetailPlan(
        sql=sql,
        dataset=dataset,
        fields=tuple(resolved),
        joins=tuple(edge.name for edge in order),
        audits=tuple(audits),
        relationship_audit=relationship_outcome,
    )


# ------------------------- the bounded record plan (spec 0014 §3, issue #57/S2)

_RECORD_REQUEST_KEYS = frozenset({"dataset", "fields", "filters", "timestamp", "order", "limit"})
_RECORD_FILTER_KEYS = frozenset({"field", "op", "value"})
_RECORD_TIMESTAMP_KEYS = frozenset({"field", "format", "timezone"})
_RECORD_ORDER_KEYS = frozenset({"field", "direction"})
_RECORD_OPS = frozenset({*_COMPARISONS, "in", "is_null", "is_not_null", "regex"})
# spec 0014 §3 revision 1: exactly the one documented text encoding is
# supported — its strict canonical shape (zero-padded) is fixed alongside it
# because DuckDB's strptime accepts non-padded fields.
_RECORD_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_RECORD_TIMESTAMP_SHAPE = "\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}"
_RECORD_TEXT_TYPES = frozenset({"VARCHAR", "CHAR", "BPCHAR", "TEXT", "STRING"})
MAX_RECORD_LIMIT = 1000  # spec 0014 §3: the requested top-N hard ceiling
DEFAULT_RECORD_LIMIT = 10
# preferred execution-only helper names: every helper identity a plan uses
# is ALLOCATED against the dataset's known physical column names (suffix
# allocation on collision — fix pass 1, finding 2): a physical column named
# like a helper is an ordinary value column and can never be shadowed by,
# nor shadow, an execution-only helper
_RECORD_TS = "__ariadne_record_ts"
_RECORD_RN = "__ariadne_record_rn"
RECORD_HAS_MORE = "__ariadne_record_has_more"
_RECORD_BASE = "__ariadne_record_base"
_RECORD_TOPN = "__ariadne_record_topn"


def _allocate_helper(preferred: str, taken: set[str]) -> str:
    """One collision-free execution-only helper identity: the dataset's
    physical column names are caller data, so a helper never shares a name
    with one (nor with an already-allocated helper). Comparison is on the
    UPPERCASED forms — DuckDB resolves identifiers case-insensitively, so a
    physical ``__ARIADNE_RECORD_RN`` collides with the lowercase helper just
    as much as an exactly-matched name (fix pass 2); ``taken`` carries
    uppercase forms and receives the allocated name's uppercase."""
    name = preferred
    counter = 2
    while name.upper() in taken:
        name = f"{preferred}_{counter}"
        counter += 1
    taken.add(name.upper())
    return name


# the row-level timestamp refusal: the fixed marker the guarded SQL raises
# through DuckDB's error() and the runtime converts into this stable code —
# the message identifies field and interpretation, never the source value
TIMESTAMP_MARKER = "ariadne timestamp interpretation:"
TIMESTAMP_REFUSAL_CODE = "timestamp_interpretation"


@dataclass(frozen=True)
class RecordPlan:
    """One bounded record selection plan (spec 0014 §3): the LOGICAL top-N
    SELECT (the caller-visible provenance) plus the ACTUAL executed statement
    (the same selection wrapped in the execution-only same-execution lookahead
    indicator), the resolved catalog identity, the applied request echo and
    the disclosed deterministic tie order."""

    sql: str  # the logical top-N selection
    executed_sql: str  # the actual compiled execution statement
    dataset: str  # the resolved qualified catalog identity
    resource: str  # the canonical credential-free resource URI
    fields: tuple[str, ...]
    filters: tuple[dict, ...]
    order: tuple[dict, ...]
    tie_order: tuple[str, ...]
    timestamp: dict | None  # the declared interpretation disclosure
    limit: int
    has_more_column: str  # the allocated same-execution lookahead column
    # the TRAILING execution-only columns of executed_sql (the lookahead
    # indicator, plus the declared timestamp's normalized instant when it
    # is not otherwise consumed): the runtime strips them POSITIONALLY —
    # the association is structural, never a guessable name (fix pass 1,
    # finding 2)
    execution_only_columns: tuple[str, ...]


def _record_column(entry: dict, name: str) -> dict | None:
    for column in entry["columns"]:
        if column["name"] == name:
            return column
    return None


def _resolve_record_dataset(catalog: list, dataset: Any) -> dict:
    """Resolve one exact known catalog dataset/resource (spec 0014 §3):
    the qualified catalog identity, the ``<source>.<table>`` display name, the
    bare table name and the canonical resource URI are the accepted forms;
    caller text never reaches a FROM clause — only a built catalog entry does.
    A name matching several distinct tables refuses as ambiguous (the request
    then names the canonical resource), an unknown name refuses with the
    known identities as candidates."""
    if not isinstance(dataset, str) or not dataset.strip():
        raise PlannerError("request_invalid", "'dataset' must be a non-empty string")
    forms: dict[str, list[dict]] = {}
    for source in catalog:
        for table in source["tables"]:
            qualified = f"{table['ref']}.{table['name']}"
            for form in (
                qualified,
                f"{source['name']}.{table['name']}",
                table["name"],
                table["resource"],
            ):
                forms.setdefault(form, []).append(table)
    matches = forms.get(dataset, [])
    unique = {id(table): table for table in matches}
    if not unique:
        raise PlannerError(
            "unknown_dataset",
            f"unknown dataset {dataset!r}; pass one exact known catalog dataset "
            "(see list_datasets) or its canonical resource",
            candidates=tuple(sorted(forms)),
        )
    if len(unique) > 1:
        raise PlannerError(
            "ambiguous_dataset",
            f"dataset name {dataset!r} matches {len(unique)} tables — pass the "
            "canonical resource of the intended one",
            candidates=tuple(sorted(table["resource"] for table in unique.values())),
        )
    return next(iter(unique.values()))


def _record_instant(value: str, zone: ZoneInfo, field: str) -> datetime:
    """Normalize one caller-supplied wall-time literal under the declared
    clock to a naive UTC instant (the planner-side mirror of the guarded SQL
    interpretation): the canonical zero-padded shape, then a strict parse, then
    the two DST rejections — an ambiguous fall-back or nonexistent
    spring-forward wall time refuses explicitly, never a fold/offset guess."""
    if not isinstance(value, str) or not re.fullmatch(_RECORD_TIMESTAMP_SHAPE, value):
        raise PlannerError(
            TIMESTAMP_REFUSAL_CODE,
            f"filter value for the declared timestamp field '{field}' does not "
            f"carry the documented encoding {_RECORD_TIMESTAMP_FORMAT!r}",
        )
    try:
        wall = datetime.strptime(value, _RECORD_TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise PlannerError(
            TIMESTAMP_REFUSAL_CODE,
            f"filter value for the declared timestamp field '{field}' is not a "
            f"valid {_RECORD_TIMESTAMP_FORMAT!r} time",
        ) from exc
    fold0 = wall.replace(tzinfo=zone)
    fold1 = wall.replace(tzinfo=zone, fold=1)
    if fold0.utcoffset() != fold1.utcoffset():
        if fold0.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == wall:
            raise PlannerError(
                TIMESTAMP_REFUSAL_CODE,
                f"filter value for the declared timestamp field '{field}' is an "
                "ambiguous fall-back wall time — no fold is guessed",
            )
        raise PlannerError(
            TIMESTAMP_REFUSAL_CODE,
            f"filter value for the declared timestamp field '{field}' is a "
            "nonexistent spring-forward wall time — no offset is guessed",
        )
    return fold0.astimezone(UTC).replace(tzinfo=None)


@lru_cache(maxsize=64)
def _zone_offsets(zone: ZoneInfo) -> tuple[int, ...]:
    """The zone's distinct UTC offsets in seconds (fix pass 1, finding 5):
    the pre-transition LMT, every offset in effect across a dense grid of
    the tz database's transition span, and the recurring tail rule's
    alternation. These embedded computed constants are the guarded fold/gap
    predicate's candidate offsets: a wall time's instants are exactly the
    candidates ``wall - offset`` that round-trip back to the wall time, for
    ANY transition width (Berlin's ±1 hour and Lord Howe's 30 minutes
    alike — plan 0014 §1's zoneinfo prerequisite)."""

    def offset(day: datetime) -> int:
        return int((day.replace(tzinfo=zone).utcoffset() or timedelta(0)).total_seconds())

    found = {offset(datetime.min), offset(datetime.max)}
    day = datetime(1830, 1, 1)
    while day.year <= 2040:
        found.add(offset(day))
        day += timedelta(days=10)
    return tuple(sorted(found))


def _record_ts_expression(column: exp.Expression, field: str, zone: ZoneInfo) -> exp.Expression:
    """The guarded per-row normalization of the declared timestamp field: a
    CASE that keeps NULL as NULL and otherwise yields the wall time's UTC
    instant, raising the fixed marker (never the source value) for malformed,
    nonexistent and ambiguous values. DuckDB's strptime accepts non-padded
    fields, so the canonical shape is enforced first. Existence and
    ambiguity follow the zone's OWN transition semantics instead of a fixed
    ±1-hour assumption: a wall time's instants are exactly the candidates
    ``wall - offset`` — one per distinct offset of the zone (embedded as
    computed constants from ``zoneinfo``) — whose round-trip back to the
    zone's wall clock equals the wall time; zero candidates is a nonexistent
    spring-forward time, two or more an ambiguous fall-back time, whatever
    the fold's width (probed against the ICU backend, plan 0014 §1 — both
    Berlin DST examples of spec §7 V1 refuse through exactly these checks,
    so a missing timezone backend is a refusal, never a guess)."""
    zone_name = zone.key
    shape = exp.Literal.string(_RECORD_TIMESTAMP_SHAPE)
    fmt = exp.Literal.string(_RECORD_TIMESTAMP_FORMAT)
    where = f"field '{field[:64]}'"  # a known catalog name, bounded regardless

    def marker(reason: str) -> exp.Expression:
        return exp.Anonymous(
            this="error",
            expressions=[
                exp.Literal.string(
                    f"{TIMESTAMP_MARKER} {reason} (declared for {where} as "
                    f"{_RECORD_TIMESTAMP_FORMAT} in {zone_name})"
                )
            ],
        )

    def wall() -> exp.Expression:
        return exp.Anonymous(this="try_strptime", expressions=[column.copy(), fmt.copy()])

    def instant() -> exp.Expression:  # wall time -> instant in the declared zone
        return exp.Anonymous(
            this="timezone",
            expressions=[exp.Literal.string(zone_name), wall()],
        )

    def utc() -> exp.Expression:  # instant -> naive UTC wall clock (order basis)
        return exp.Anonymous(
            this="timezone",
            expressions=[exp.Literal.string("UTC"), instant()],
        )

    def back(expr: exp.Expression) -> exp.Expression:  # instant -> zone wall clock
        return exp.Anonymous(
            this="timezone",
            expressions=[exp.Literal.string(zone_name), expr],
        )

    def candidate(offset_seconds: int) -> exp.Expression:
        # the parsed wall time minus the offset as an instant, taken back to
        # the zone's wall clock (evaluated only after the shape/parse checks)
        shifted = exp.Sub(
            this=wall(),
            expression=exp.Anonymous(
                this="to_seconds", expressions=[exp.Literal.number(offset_seconds)]
            ),
        )
        tagged = exp.Anonymous(this="timezone", expressions=[exp.Literal.string("UTC"), shifted])
        return exp.EQ(this=back(tagged), expression=wall())

    malformed = marker("a malformed non-null value")
    shape_ok = exp.Anonymous(this="regexp_full_match", expressions=[column.copy(), shape])
    preimages = None  # the wall time's instant count, however wide the fold
    for offset_seconds in _zone_offsets(zone):
        vote = exp.Cast(this=candidate(offset_seconds), to=exp.DataType.build("INTEGER"))
        preimages = vote if preimages is None else exp.Add(this=preimages, expression=vote)
    case = (
        exp.Case()
        .when(exp.Is(this=column.copy(), expression=exp.Null()), exp.Null())
        .when(exp.Not(this=shape_ok), malformed)
        .when(exp.Is(this=wall(), expression=exp.Null()), malformed)
        .when(
            exp.EQ(this=preimages, expression=exp.Literal.number(0)),
            marker("a nonexistent spring-forward wall time"),
        )
        .when(
            exp.GTE(this=preimages, expression=exp.Literal.number(2)),
            marker("an ambiguous fall-back wall time"),
        )
        .else_(utc())
    )
    return case


def _parse_record_filters(
    raw: Any, entry: dict, timestamp_field: str | None
) -> tuple[list[tuple[str, str, Any]], list[tuple[str, str, Any]]]:
    """Parse the optional AND-combined record predicates (spec 0014 §3,
    reusing the metric request's value/literal builders): comparisons and IN
    share the established parsing and ceilings; ``is_null``/``is_not_null``
    carry no value; ``regex`` is one bounded literal whose PATTERN VALIDITY
    is the execution engine's RE2 judgement, probed on the request's
    connection by :func:`plan_records` (fix pass 1, finding 4). Returns
    (non-temporal, temporal) — the temporal comparisons on the declared
    timestamp field are applied after its interpretation."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        raise PlannerError("filter_invalid", "'filters' must be a list of predicates")
    non_temporal: list[tuple[str, str, Any]] = []
    temporal: list[tuple[str, str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - _RECORD_FILTER_KEYS or "field" not in item:
            raise PlannerError(
                "filter_invalid",
                f"a record predicate is exactly {{'field', 'op'('value')}}; allowed "
                f"keys {sorted(_RECORD_FILTER_KEYS)}",
            )
        field, op = item["field"], item["op"]
        if not isinstance(field, str) or not field.strip():
            raise PlannerError("filter_invalid", "a record predicate needs a non-empty 'field'")
        if _record_column(entry, field) is None:
            raise PlannerError(
                "unknown_field",
                f"unknown filter field {field!r}",
                candidates=tuple(column["name"] for column in entry["columns"]),
            )
        if not isinstance(op, str) or op not in _RECORD_OPS:
            raise PlannerError(
                "filter_invalid",
                f"unsupported op {op!r}; allowed: {sorted(_RECORD_OPS)}",
            )
        has_value = "value" in item
        value = item.get("value")
        where = f"filter on {field!r}"
        if op in ("is_null", "is_not_null"):
            if has_value:
                raise PlannerError("filter_invalid", f"{where}: op {op!r} takes no value")
        elif not has_value:
            raise PlannerError("filter_invalid", f"{where}: op {op!r} requires a value")
        elif op == "regex":
            if not isinstance(value, str):
                raise PlannerError(
                    "filter_invalid", f"{where}: a regex predicate takes a string pattern"
                )
            if len(value) > MAX_PARAMETER_LENGTH:
                raise PlannerError(
                    "filter_invalid",
                    f"{where}: pattern of {len(value)} character(s) exceeds the bound "
                    f"of {MAX_PARAMETER_LENGTH}",
                )
        elif op == "in":
            if not isinstance(value, list):
                raise PlannerError(
                    "filter_invalid", f"{where}: op 'in' takes a literal list of values"
                )
            if not 1 <= len(value) <= MAX_IN_VALUES:
                raise PlannerError(
                    "filter_invalid",
                    f"{where}: an IN list needs 1..{MAX_IN_VALUES} values",
                )
            for element in value:
                if element is None or isinstance(element, dict):
                    raise PlannerError(
                        "filter_invalid",
                        f"{where}: IN list elements are scalars (use is_null for nulls)",
                    )
                if isinstance(element, str) and len(element) > MAX_PARAMETER_LENGTH:
                    raise PlannerError(
                        "filter_invalid",
                        f"{where}: a string value of {len(element)} character(s) exceeds "
                        f"the bound of {MAX_PARAMETER_LENGTH}",
                    )
                if isinstance(element, float) and not math.isfinite(element):
                    raise PlannerError(
                        "filter_invalid", f"{where}: non-finite numbers are rejected"
                    )
        else:  # a comparison
            if value is None:
                raise PlannerError(
                    "filter_invalid",
                    f"{where}: null is tested with is_null/is_not_null, not a comparison",
                )
            if isinstance(value, (dict, list)):
                raise PlannerError(
                    "filter_invalid", f"{where}: op {op!r} takes exactly one scalar value"
                )
            if isinstance(value, str) and len(value) > MAX_PARAMETER_LENGTH:
                raise PlannerError(
                    "filter_invalid",
                    f"{where}: a string value of {len(value)} character(s) exceeds the "
                    f"bound of {MAX_PARAMETER_LENGTH}",
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise PlannerError("filter_invalid", f"{where}: non-finite numbers are rejected")
        bucket = (
            temporal
            if (timestamp_field is not None and field == timestamp_field and op in _COMPARISONS)
            else non_temporal
        )
        bucket.append((field, op, value))
    return non_temporal, temporal


def _validate_regex(connection: Any, pattern: str, field: str) -> None:
    """Validate one regex predicate with the engine that will run it (fix
    pass 1, finding 4): the advertised semantics are DuckDB's RE2 — Python
    ``re`` both refuses RE2-valid constructs (Unicode classes like ``\\p{L}``)
    and accepts RE2-invalid ones (lookaheads) — so validity is probed as a
    constant ``regexp_matches`` on the request's connection, which raises on
    invalid RE2 patterns before result execution."""
    try:
        connection.execute("SELECT regexp_matches('probe', ?)", [pattern])
    except Exception as exc:
        raise PlannerError(
            "filter_invalid", f"filter on {field!r}: invalid regular expression: {exc}"
        ) from exc


def plan_records(
    catalog: list,
    request: dict,
    connection: Any = None,
    *,
    row_ceiling: int = MAX_RECORD_LIMIT,
) -> RecordPlan:
    """Compile ONE bounded single-dataset record selection (spec 0014 §3,
    issue #57/S2): strict known fields/request keys, AND-combined typed
    predicates, one optional declared timestamp interpretation (mandatory
    semantics apply wherever the request orders that field), a required
    deterministic order with explicit NULLS LAST and the selected-value tie
    tuple, and a requested top-N within the ceilings. The plan's executed
    statement carries the SAME-execution lookahead indicator — ``ROW_NUMBER``
    over the deterministic order plus a ``LEAD`` existence boolean on the last
    returned row — so the extra row never transfers payload cells and no
    second mutable-source query or COUNT runs. No relationship traversal, no
    aggregates, no caller SQL: the FROM identity is a built catalog entry and
    every value binds as a planner-built literal (``connection`` is accepted
    for the shared plan interface; a record selection runs no live audits).
    Regex pattern validity is DuckDB's RE2 judgement, probed on
    ``connection`` when supplied — the runtime always supplies its
    connection, so the guaranteed validation point is covered; a
    connection-less plan defers an invalid pattern to execution's own bind
    refusal."""
    if not isinstance(request, dict):
        raise PlannerError(
            "request_invalid",
            "record request must be a mapping {dataset, fields, filters?, "
            "timestamp?, order, limit?}",
        )
    unknown = sorted(set(request) - _RECORD_REQUEST_KEYS)
    if unknown:
        raise PlannerError(
            "request_invalid",
            f"unknown record request key(s) {unknown}; allowed: {sorted(_RECORD_REQUEST_KEYS)}",
        )
    entry = _resolve_record_dataset(catalog, request.get("dataset"))

    fields = request.get("fields")
    if not isinstance(fields, list) or not fields:
        raise PlannerError("request_invalid", "'fields' must be a non-empty list of field names")
    checked: list[str] = []
    for name in fields:
        if not isinstance(name, str):
            raise PlannerError(
                "request_invalid", "'fields' must be a non-empty list of field names"
            )
        checked.append(name)
    fields = list(dict.fromkeys(checked))  # duplicates removed, first kept
    column_types = {column["name"]: str(column["type"]) for column in entry["columns"]}
    for field in fields:
        if _record_column(entry, field) is None:
            raise PlannerError(
                "unknown_field",
                f"unknown field {field!r}",
                candidates=tuple(column["name"] for column in entry["columns"]),
            )

    timestamp = request.get("timestamp")
    zone = None
    zone_name: str | None = None
    timestamp_field = None
    if timestamp is not None:
        if not isinstance(timestamp, dict) or set(timestamp) != _RECORD_TIMESTAMP_KEYS:
            raise PlannerError(
                "timestamp_invalid",
                f"'timestamp' is exactly {sorted(_RECORD_TIMESTAMP_KEYS)}",
            )
        timestamp_field = timestamp.get("field")
        ts_column = (
            _record_column(entry, timestamp_field) if isinstance(timestamp_field, str) else None
        )
        if ts_column is None:
            raise PlannerError(
                "unknown_field",
                f"unknown timestamp field {timestamp_field!r}",
                candidates=tuple(column["name"] for column in entry["columns"]),
            )
        declared_type = str(ts_column["type"]).split("(")[0].strip().upper()
        if declared_type not in _RECORD_TEXT_TYPES:
            raise PlannerError(
                "timestamp_invalid",
                f"the declared timestamp field '{timestamp_field}' has type "
                f"{declared_type!r}, which does not carry the documented "
                f"{_RECORD_TIMESTAMP_FORMAT!r} text encoding",
            )
        if timestamp.get("format") != _RECORD_TIMESTAMP_FORMAT:
            raise PlannerError(
                "timestamp_invalid",
                f"revision 1 supports exactly the documented "
                f"{_RECORD_TIMESTAMP_FORMAT!r} encoding, got {timestamp.get('format')!r}",
            )
        zone_name = timestamp.get("timezone")
        if not isinstance(zone_name, str) or not zone_name.strip():
            raise PlannerError("timestamp_invalid", "'timezone' must be an IANA timezone name")
        try:
            zone = ZoneInfo(zone_name)
        except Exception as exc:
            raise PlannerError(
                "timestamp_invalid",
                f"timezone {zone_name!r} is not an available IANA zone",
            ) from exc

    non_temporal, temporal = _parse_record_filters(request.get("filters"), entry, timestamp_field)
    if connection is not None:  # the runtime always supplies its connection
        for field, op, value in non_temporal + temporal:
            if op == "regex":
                _validate_regex(connection, value, field)

    raw_order = request.get("order")
    if not isinstance(raw_order, list) or not raw_order:
        raise PlannerError(
            "order_invalid", "'order' is required: a non-empty list of {field, direction?}"
        )
    order: list[dict] = []
    for item in raw_order:
        if not isinstance(item, dict) or set(item) - _RECORD_ORDER_KEYS or "field" not in item:
            raise PlannerError(
                "order_invalid",
                "an order entry is {'field': <column>} plus optional 'direction'",
            )
        field = item["field"]
        direction = item.get("direction", "asc")
        if not isinstance(field, str) or not field.strip():
            raise PlannerError("order_invalid", "order 'field' must be a column name")
        if _record_column(entry, field) is None:
            raise PlannerError(
                "unknown_field",
                f"unknown order field {field!r}",
                candidates=tuple(column["name"] for column in entry["columns"]),
            )
        if direction not in ("asc", "desc"):
            raise PlannerError(
                "order_invalid",
                f"order direction must be 'asc' or 'desc', got {direction!r}",
            )
        order.append({"field": field, "direction": direction})

    raw_limit = request.get("limit", DEFAULT_RECORD_LIMIT)
    if (
        isinstance(raw_limit, bool)
        or not isinstance(raw_limit, int)
        or not 1 <= raw_limit <= min(MAX_RECORD_LIMIT, row_ceiling)
    ):
        raise PlannerError(
            "limit_invalid",
            f"'limit' must be a positive integer of at most "
            f"{min(MAX_RECORD_LIMIT, row_ceiling)} (booleans are not integers)",
        )

    # ---- the deterministic order: requested keys, then the remaining selected
    # sortable scalar columns ascending NULLS LAST (ties disclosed in the plan)
    tie_fields = [
        field
        for field in fields
        if field not in {item["field"] for item in order}
        and classify_output_type(column_types[field]) != "unsupported"
    ]

    def col(name: str) -> exp.Expression:
        return exp.column(exp.to_identifier(name, quoted=True))

    # fix pass 1, finding 2 + fix pass 2: helper identities are allocated
    # against the dataset's known physical column names under DuckDB's
    # case-insensitive identifier equivalence — a physical column named like
    # a helper (exact or uppercased) stays an ordinary value column
    taken = {column["name"].upper() for column in entry["columns"]}
    ts_helper = _allocate_helper(_RECORD_TS, taken) if timestamp_field is not None else None
    rn_helper = _allocate_helper(_RECORD_RN, taken)
    has_more_helper = _allocate_helper(RECORD_HAS_MORE, taken)
    base_alias = _allocate_helper(_RECORD_BASE, taken)
    topn_alias = _allocate_helper(_RECORD_TOPN, taken)

    def order_key(name: str) -> exp.Expression:
        # ordering on the declared timestamp field uses its normalized instant
        # (ts_helper is allocated exactly when a timestamp is declared)
        helper = ts_helper if name == timestamp_field else None
        return col(helper) if helper is not None else col(name)

    def ordered(name: str, direction: str) -> exp.Ordered:
        return exp.Ordered(this=order_key(name), desc=direction == "desc", nulls_first=False)

    def window_order() -> exp.Order:
        keys = [ordered(item["field"], item["direction"]) for item in order]
        keys += [ordered(field, "asc") for field in tie_fields]
        return exp.Order(expressions=keys)

    def predicate_ast(field: str, op: str, value: Any) -> exp.Expression:
        column = col(field)
        context = f"filter on {field!r}"
        if op == "is_null":
            return exp.Is(this=column, expression=exp.Null())
        if op == "is_not_null":
            return exp.Not(this=exp.Is(this=column, expression=exp.Null()))
        if op == "regex":
            return exp.RegexpLike(this=column, expression=_direct_literal(value, context))
        if op == "in":
            return exp.In(
                this=column, expressions=[_direct_literal(element, context) for element in value]
            )
        helper = ts_helper if field == timestamp_field else None
        if helper is not None and zone is not None:
            instant = _record_instant(value, zone, field)
            literal = exp.Cast(
                this=exp.Literal.string(instant.strftime(_RECORD_TIMESTAMP_FORMAT)),
                to=exp.DataType.build("TIMESTAMP"),
            )
            return _COMPARISONS[op](this=col(helper), expression=literal)
        return _COMPARISONS[op](this=column, expression=_direct_literal(value, context))

    parts = [part for part in entry["ref"].split(".") if part] + [entry["name"]]
    table = exp.Table(
        **{
            key: exp.to_identifier(part, quoted=True)
            for key, part in zip(("catalog", "db", "this"), [None] * (3 - len(parts)) + parts)
        }
    )
    needed: list[str] = list(fields)
    for field, _op, _value in non_temporal + temporal:
        if field not in needed:
            needed.append(field)
    for item in order:
        if item["field"] not in needed:
            needed.append(item["field"])
    if timestamp_field is not None and timestamp_field not in needed:
        needed.append(timestamp_field)

    base = exp.Select().from_(table)
    for name in needed:
        base = base.select(exp.alias_(col(name), name, quoted=True))
    base_with_ts = base
    if timestamp_field is not None and ts_helper is not None and zone is not None:
        ts_expression = _record_ts_expression(col(timestamp_field), timestamp_field, zone)
        base_with_ts = base.select(exp.alias_(ts_expression, ts_helper, quoted=True))
    for field, op, value in non_temporal:
        base_with_ts = base_with_ts.where(predicate_ast(field, op, value))

    record_base = exp.Subquery(
        this=base_with_ts,
        alias=exp.TableAlias(this=exp.to_identifier(base_alias, quoted=True)),
    )
    windowed = (
        exp.Select()
        .from_(record_base)
        .select(*[exp.alias_(col(name), name, quoted=True) for name in fields])
    )
    if ts_helper is not None:
        windowed = windowed.select(exp.alias_(col(ts_helper), ts_helper, quoted=True))
    windowed = windowed.select(
        exp.alias_(
            exp.Window(this=exp.RowNumber(), order=window_order()),
            rn_helper,
            quoted=True,
        )
    ).select(
        exp.alias_(
            exp.Not(
                this=exp.Is(
                    this=exp.Window(
                        this=exp.Lead(this=exp.Literal.number(1)), order=window_order()
                    ),
                    expression=exp.Null(),
                )
            ),
            has_more_helper,
            quoted=True,
        )
    )
    for field, op, value in temporal:
        windowed = windowed.where(predicate_ast(field, op, value))

    executed = (
        exp.Select()
        .from_(
            exp.Subquery(
                this=windowed,
                alias=exp.TableAlias(this=exp.to_identifier(topn_alias, quoted=True)),
            )
        )
        .select(*[exp.alias_(col(name), name, quoted=True) for name in fields])
        .select(exp.alias_(col(has_more_helper), has_more_helper, quoted=True))
        .where(exp.LTE(this=col(rn_helper), expression=exp.Literal.number(raw_limit)))
        .order_by(exp.Ordered(this=col(rn_helper), nulls_first=False))
    )
    if ts_helper is not None:
        # fix pass 1, finding 3: the declared interpretation stays evaluated
        # on every ELIGIBLE row even when nothing else consumes the normalized
        # instant — it rides as a trailing execution-only column (stripped
        # before assembly) so no projection pruning can silence a malformed,
        # nonexistent or ambiguous value below the top-N boundary
        executed = executed.select(exp.alias_(col(ts_helper), ts_helper, quoted=True))

    logical = exp.Select().from_(table)
    for name in fields:
        logical = logical.select(exp.alias_(col(name), name, quoted=True))
    for field, op, value in non_temporal + temporal:
        logical = logical.where(predicate_ast(field, op, value))
    logical = logical.order_by(window_order()).limit(raw_limit)

    executed_sql = executed.sql(dialect="duckdb")
    sql = logical.sql(dialect="duckdb")
    for statement, what in ((executed_sql, "executed"), (sql, "logical")):
        if len(sqlglot.parse(statement)) != 1:  # self-check, the spec §6 invariant
            raise PlannerError(
                "not_one_statement",
                f"compiled {what} record plan is not exactly one statement "
                "(no-unvalidated-execution invariant, spec §6)",
            )
    return RecordPlan(
        sql=sql,
        executed_sql=executed_sql,
        dataset=f"{entry['ref']}.{entry['name']}",
        resource=entry["resource"],
        fields=tuple(fields),
        filters=tuple(
            {"field": field, "op": op, **({"value": value} if value is not None else {})}
            for field, op, value in non_temporal + temporal
        ),
        order=tuple(order),
        tie_order=tuple(tie_fields),
        timestamp=(
            {
                "field": timestamp_field,
                "format": _RECORD_TIMESTAMP_FORMAT,
                "timezone": zone_name,
                "interpretation": (
                    f"wall times in {zone_name} normalized to UTC instants "
                    f"({_RECORD_TIMESTAMP_FORMAT}); malformed, nonexistent and ambiguous "
                    "values refuse; rows keep the original selected value"
                ),
            }
            if timestamp_field is not None
            else None
        ),
        limit=raw_limit,
        has_more_column=has_more_helper,
        execution_only_columns=(
            (has_more_helper, ts_helper) if ts_helper is not None else (has_more_helper,)
        ),
    )
