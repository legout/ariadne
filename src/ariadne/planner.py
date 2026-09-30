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
assembles sqlglot ASTs it derived itself. Cross-fact derived metrics compute
after alignment and land with task 4 (#29); served operations are task 5 (#30).

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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import (  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
    exp,  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
)

from ariadne.grain import (  # pyright: ignore[reportMissingImports] — drift
    check_grain_preserving,
    relationship_target_audit,
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
    RelationshipEdge,
    SemanticGraph,
)

_REQUEST_KEYS = frozenset(
    {"metrics", "dimensions", "filters", "segments", "parameters", "order", "limit"}
)
_DETAIL_REQUEST_KEYS = frozenset({"dataset", "fields"})
_FILTER_KEYS = frozenset({"field", "op", "value"})
_SEGMENT_KEYS = frozenset({"name", "filters"})
_PARAMETER_KEYS = frozenset({"type", "value", "min", "max", "max_length"})
_ORDER_KEYS = frozenset({"field", "direction"})
_COMPARISONS = {"=": exp.EQ, "!=": exp.NEQ, "<": exp.LT, "<=": exp.LTE, ">": exp.GT, ">=": exp.GTE}
PARAMETER_TYPES = frozenset({"string", "int", "float", "date"})
MAX_PARAMETER_LENGTH = 4096  # hard ceiling even without a declared max_length
MAX_LIMIT = 10_000  # bounded result limits
MAX_IN_VALUES = 100  # bounded IN lists


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
    conformed keys, applied segments, performed audits)."""

    sql: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    branches: tuple[BranchPlan, ...]
    conformed_keys: tuple[str, ...]
    audits: tuple[AuditRecord, ...]
    relationship_audit: str  # passed | not-run (never silently passed)
    segments: tuple[str, ...] = ()


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
            raise PlannerError(
                "filter_invalid", f"{context}: op {op!r} takes exactly one value"
            )
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
                raise PlannerError(
                    "filter_invalid", f"duplicate segment name {name!r}"
                )
            body = entry["filters"]
            if not isinstance(body, list) or not body:
                raise PlannerError(
                    "filter_invalid",
                    f"segment {name!r} composes at least one predicate — an empty "
                    "segment is a mistake, not a no-op",
                )
            out.extend(
                _parse_predicate(item, f"segment {name!r}") for item in body
            )
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
            raise PlannerError(
                "parameter_invalid", "'parameters' maps names to declarations"
            )
        unknown = sorted(set(declaration) - _PARAMETER_KEYS)
        if unknown:
            raise PlannerError(
                "parameter_invalid",
                f"parameter {name!r}: unknown key(s) {unknown}; "
                f"allowed: {sorted(_PARAMETER_KEYS)}",
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
                    f"{where}: value of {len(value)} character(s) exceeds the bound "
                    f"of {limit}",
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
                    raise PlannerError(
                        "parameter_invalid", f"{where}: '{key}' must be a number"
                    )
            if (low is not None and value < low) or (high is not None and value > high):
                raise PlannerError(
                    "parameter_invalid",
                    f"{where}: value {value!r} is outside the declared bounds "
                    f"[{low!r}, {high!r}]",
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
        return exp.In(
            this=column, expressions=[_direct_literal(item, context) for item in raw]
        )
    return _COMPARISONS[predicate.op](
        this=column, expression=_direct_literal(raw, context)
    )


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
                    "an order entry is {'field': <output column>} plus optional "
                    "'direction'",
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
        raise PlannerError(
            "request_invalid", "'metrics' must be a non-empty list of metric names"
        )
    dimensions = request.get("dimensions", [])
    if not isinstance(dimensions, list) or not all(
        isinstance(name, str) for name in dimensions
    ):
        raise PlannerError("request_invalid", "'dimensions' must be a list of dimension names")
    return list(dict.fromkeys(metrics)), list(dict.fromkeys(dimensions))


def _resolve_owner(
    graph: SemanticGraph, name: str, memo: dict[str, str | None]
) -> str | None:
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
    the conformed-dimension name when alignment relies on conformance."""

    dimension: str
    members: dict[str, str]  # branch dataset -> native field
    paths: dict[str, tuple[RelationshipEdge, ...]]  # branch dataset -> edges
    conformed: str | None


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
            field_name = next(
                (field for member, field in edge.members if member == dataset), None
            )
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


def _submodel(graph: SemanticGraph, dataset: str, metric_names: list[str]) -> dict:
    """The dataset's single-dataset envelope slice (one dataset + exactly the
    metrics the branch aggregates) — the render() input shape."""
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
    return {
        "version": envelope.get("version"),
        "semantic_model": [
            {
                "name": node.model,
                # a COPY of the dataset entry: the plain-filter path below
                # overwrites this mapping's 'source' with filtered SQL, and the
                # graph's own declaration must not change with any one request
                # (mf-t3 review F1)
                "datasets": [{**entry}],
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
        name: _strip_qualifiers(
            _parse(sql, f"field {name!r} of dataset '{edge.to_dataset}'")
        )
        for name, sql in expressions.items()
    }
    resolved = []
    for field in edge.to_fields:
        tree = field_asts.get(field)
        if tree is None:
            # no usable dialect declaration: the physical column itself
            resolved.append(field)
            continue
        resolved.append(
            _resolve_fields(tree.copy(), field_asts, set()).sql(dialect="duckdb")
        )
    return tuple(resolved)


def _joined_branch_sql(
    graph: SemanticGraph,
    dataset: str,
    dim_keys: list[_DimKey],
    metric_names: list[str],
    row_preds: Sequence[tuple[_Predicate, _DimKey]] = (),
    parameters: dict[str, tuple[str, Any]] | None = None,
) -> tuple[str, list[RelationshipEdge]]:
    """A branch that reaches dimension or filter fields through relationship
    lookup paths: LEFT joins onto each proven unique target INSIDE the branch,
    keys and base aggregates projected over the joined output, GROUP BY the key
    expressions, and row predicates applied INSIDE the branch (before its
    aggregation — a filter that reaches a lookup field filters that branch's
    population). Every field resolves against the dataset that declares it
    and each source-column reference carries that dataset's branch alias, so
    dataset scope survives the lowering (fix pass F3). Derived metrics over
    lookup branches land with #29."""
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
        expression = lower(
            exp.column(key.members[dataset]), home, f"dimension '{key.dimension}'"
        )
        group_exprs.append(expression)
        # F4: project under the NATIVE member name — the alignment layer (keys
        # CTE, LEFT JOIN) references key.members[dataset] for BOTH branch kinds,
        # and a conformed key's native member may differ from the canonical name.
        select = select.select(exp.alias_(expression, key.members[dataset], quoted=True))
    for metric_name in sorted(metric_names):
        metric_node = graph.metrics[metric_name]
        if metric_node.derived:
            raise PlannerError(
                "derived_lookup_unsupported",
                f"metric '{metric_name}' is derived and branch '{dataset}' traverses a "
                "relationship lookup path — derived metrics over lookup branches land "
                "with post-alignment derivation (#29)",
            )
        tree = _parse(metric_node.expression, f"metric {metric_name!r}")
        tree = lower(tree, dataset, f"metric {metric_name!r}")
        select = select.select(exp.alias_(tree, metric_name, quoted=True))
    # row filters: routed predicates apply inside the branch, before grouping
    where = None
    for predicate, key in row_preds:
        path = key.paths[dataset]
        home = path[-1].to_dataset if path else dataset
        column = lower(
            exp.column(key.members[dataset]), home, f"filter on '{predicate.field}'"
        )
        condition = _predicate_ast(column, predicate, parameters or {})
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


def _branch_sql(
    graph: SemanticGraph,
    dataset: str,
    dim_keys: list[_DimKey],
    metric_names: list[str],
    requested: list[str],
    row_preds: Sequence[tuple[_Predicate, _DimKey]] = (),
    parameters: dict[str, tuple[str, Any]] | None = None,
) -> tuple[str, list[RelationshipEdge]]:
    """The branch SELECT (group keys in requested order, then its metrics).
    Branches whose dimensions OR routed row filters need a lookup path compile
    through the in-branch join builder; branches with no lookup path compile
    through the single-dataset renderer — including single-dataset derived
    layering — so both authoring layouts and legacy models share one compiler
    (ADR-0008), with row predicates pre-filtering the branch source.
    ``requested`` are the metrics the request itself asks of this branch: the
    renderer must keep their outputs through any derived layer (F5 — a base
    metric requested together with a same-fact derived metric on top of it
    needs both columns)."""
    if any(key.paths[dataset] for key in dim_keys) or any(
        key.paths[dataset] for _predicate, key in row_preds
    ):
        return _joined_branch_sql(graph, dataset, dim_keys, metric_names, row_preds, parameters)
    sub = _submodel(graph, dataset, metric_names)
    plain = _plain_predicates(graph, dataset, row_preds, parameters or {})
    if plain:
        filtered = exp.Select().select("*").from_(
            _source_subquery(
                graph.datasets[dataset].source, f"dataset '{dataset}' source"
            )
        )
        where = None
        for condition in plain:
            where = condition if where is None else exp.And(this=where, expression=condition)
        filtered = filtered.where(where)
        sub["semantic_model"][0]["datasets"][0]["source"] = filtered.sql(
            dialect="duckdb"
        )
    try:
        return (
            render(
                sub,
                dimensions=[key.members[dataset] for key in dim_keys],
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


def _final_sql(
    branch_sqls: list[str],
    branch_keys: list[list[tuple[str, str]]],  # per branch: (canonical, native col)
    columns: list[tuple[str, int, str, bool]],  # (metric, branch idx, col, bare count)
    result_filters: Sequence[_Predicate] = (),
    order: Sequence[tuple[str, bool]] = (),
    limit: int | None = None,
    parameters: dict[str, tuple[str, Any]] | None = None,
) -> str:
    """The ONE guarded SELECT: CTE per branch, a keys CTE unioning the branch
    group keys (UNION dedupes, NULL-inclusive), and an outer SELECT aligning
    aggregate outputs with null-safe equality. No-dimension plans cross-join
    the single-row aggregates instead. Aggregate/RESULT filters, declared
    ordering and the bounded limit apply AFTER grouping, on a wrapper SELECT
    over the aligned output (its WHERE/ORDER BY reference real subquery
    columns, never select aliases — spec rev 1, "Query and result")."""
    names = [f"b{index}" for index in range(len(branch_sqls))]
    outer = exp.Select()
    for canonical, _native in branch_keys[0] if branch_keys else []:
        outer = outer.select(
            exp.alias_(
                exp.column(canonical, table="keys", quoted=True), canonical, quoted=True
            )
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
    if result_filters or order or limit:
        wrapper = exp.Select().select("*").from_(exp.Subquery(this=outer))
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
            audit = relationship_target_audit(
                connection, source, resolved_target_keys(graph, edge)
            )
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
                f"target key {list(edge.to_fields)} unique and non-NULL over "
                f"{audit.rows} rows",
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
    owner_of: dict[str, str] = {}
    for name in sorted(metric_names):
        owner = _resolve_owner(graph, name, memo)
        if owner is None:
            raise PlannerError(
                "derived_cross_fact_unsupported",
                f"metric '{name}' derives across fact datasets — cross-fact derived "
                "metrics compute after branch alignment (task 4, #29)",
                candidates=tuple(
                    sorted(
                        candidate
                        for candidate, node in graph.metrics.items()
                        if not (node.derived and _resolve_owner(graph, candidate, memo) is None)
                    )
                ),
            )
        owner_of[name] = owner

    branch_datasets = sorted(set(owner_of.values()))
    branch_metrics: dict[str, list[str]] = {dataset: [] for dataset in branch_datasets}
    for name in metric_names:
        for member in _closure(graph, name):
            owner = _resolve_owner(graph, member, memo)
            if (
                owner is not None
                and owner in branch_metrics
                and member not in branch_metrics[owner]
            ):
                branch_metrics[owner].append(member)

    conformed_by_name = {edge.name: edge for edge in graph.conformed_dimensions}
    dim_keys = [
        _resolve_field_key(graph, name, branch_datasets, conformed_by_name, "dimension")
        for name in dimension_names
    ]

    parameters = _parse_parameters(request.get("parameters"))
    predicates, segment_names = _parse_predicates(request)
    order, limit = _parse_order_limit(request)
    output_columns = set(metric_names) | set(dimension_names)
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

    branch_sqls: list[str] = []
    branch_plans: list[BranchPlan] = []
    branch_keys: list[list[tuple[str, str]]] = []
    participating: dict[str, RelationshipEdge] = {}
    for dataset in branch_datasets:
        routed = [
            (predicate, key) for predicate, key in row_filters if dataset in key.members
        ]
        sql, edges = _branch_sql(
            graph,
            dataset,
            dim_keys,
            branch_metrics[dataset],
            [name for name in metric_names if owner_of[name] == dataset],
            routed,
            parameters,
        )
        branch_sqls.append(sql)
        branch_plans.append(
            BranchPlan(
                dataset=dataset,
                metrics=tuple(sorted(branch_metrics[dataset])),
                joins=tuple(edge.name for edge in edges),
                keys=tuple((key.dimension, key.members[dataset]) for key in dim_keys),
                filters=tuple(
                    dict.fromkeys(predicate.field for predicate, _key in routed)
                ),
            )
        )
        branch_keys.append([(key.dimension, key.members[dataset]) for key in dim_keys])
        for edge in edges:
            participating[edge.name] = edge

    columns = [
        (
            name,
            branch_datasets.index(owner_of[name]),
            name,
            _is_bare_count(graph.metrics[name].expression),
        )
        for name in metric_names
    ]
    sql = _final_sql(
        branch_sqls,
        branch_keys,
        columns,
        result_filters,
        order,
        limit,
        parameters,
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
    audits.append(
        AuditRecord("relationship_audit", relationship_outcome, relationship_detail)
    )
    return QueryPlan(
        sql=sql,
        metrics=tuple(metric_names),
        dimensions=tuple(dimension_names),
        branches=tuple(branch_plans),
        conformed_keys=tuple(key.conformed for key in dim_keys if key.conformed is not None),
        audits=tuple(audits),
        relationship_audit=relationship_outcome,
        segments=segment_names,
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


def _child_side_chain(
    graph: SemanticGraph, root: str, home: str
) -> tuple[str, ...] | None:
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
        raise PlannerError(
            "request_invalid", "'fields' must be a non-empty list of field names"
        )
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
            _source_subquery(
                graph.datasets[dataset].source, f"dataset '{dataset}' source"
            ),
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
                f"{len(participating)} participating relationship(s) rechecked on this "
                "request"
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
