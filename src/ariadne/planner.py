"""Governed multi-fact query planner (issue #27; spec rev 1 "Query and result
contract"; ADR-0006 — one grain per dataset, independent fact branches).

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
"""

from __future__ import annotations

from dataclasses import dataclass
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

_REQUEST_KEYS = frozenset({"metrics", "dimensions"})


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
    aggregates, the relationship edges it traverses (in order) and the
    (canonical dimension, native column) keys it groups by."""

    dataset: str
    metrics: tuple[str, ...]
    joins: tuple[str, ...]
    keys: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class AuditRecord:
    """One performed live check and its outcome (plan evidence, issue #27)."""

    name: str
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class QueryPlan:
    """The guarded SELECT plus bounded plan metadata (SQL, fact branches,
    conformed keys, performed audits)."""

    sql: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    branches: tuple[BranchPlan, ...]
    conformed_keys: tuple[str, ...]
    audits: tuple[AuditRecord, ...]
    relationship_audit: str  # passed | not-run (never silently passed)


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


def _resolve_dimension(
    graph: SemanticGraph,
    name: str,
    branch_datasets: list[str],
    conformed_by_name: dict[str, Any],
) -> _DimKey:
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
                "unpaired_dimension",
                f"conformed dimension '{name}' has no member on fact branch(es) "
                f"{sorted(missing)} — a grouping key must resolve safely in EVERY "
                "affected branch, never silently narrow one (spec rev 1)",
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
            "unknown_dimension",
            f"unknown dimension {name!r}",
            candidates=candidates,
        )
    if len(owners) > 1:
        raise PlannerError(
            "ambiguous_dimension",
            f"field '{name}' exists on datasets {owners} — no equivalence is inferred "
            "from identical column names (spec rev 1 §3); declare a conformed dimension",
        )
    home = owners[0]
    members = {}
    paths: dict[str, tuple[RelationshipEdge, ...]] = {}
    for dataset in branch_datasets:
        path = _lookup_path(graph, dataset, home)
        if path is None:
            raise PlannerError(
                "unreachable_dimension",
                f"dimension '{name}' (field of dataset '{home}') is not reachable from "
                f"fact branch '{dataset}' through proven many_to_one/one_to_one "
                "relationship paths",
            )
        members[dataset] = name
        paths[dataset] = path
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
                "datasets": [entry],
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
) -> tuple[str, list[RelationshipEdge]]:
    """A branch that reaches dimension fields through relationship lookup
    paths: LEFT joins onto each proven unique target INSIDE the branch, keys
    and base aggregates projected over the joined output, GROUP BY the key
    expressions. Every field resolves against the dataset that declares it
    and each source-column reference carries that dataset's branch alias, so
    dataset scope survives the lowering (fix pass F3). Derived metrics over
    lookup branches land with #29."""
    node = graph.datasets[dataset]
    collected: dict[str, RelationshipEdge] = {}
    for key in dim_keys:
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
    if group_exprs:
        select = select.group_by(*group_exprs)
    return select.sql(dialect="duckdb"), order


def _branch_sql(
    graph: SemanticGraph,
    dataset: str,
    dim_keys: list[_DimKey],
    metric_names: list[str],
    requested: list[str],
) -> tuple[str, list[RelationshipEdge]]:
    """The branch SELECT (group keys in requested order, then its metrics).
    Branches with no lookup path compile through the single-dataset renderer —
    including single-dataset derived layering — so both authoring layouts and
    legacy models share one compiler (ADR-0008). ``requested`` are the metrics
    the request itself asks of this branch: the renderer must keep their
    outputs through any derived layer (F5 — a base metric requested together
    with a same-fact derived metric on top of it needs both columns)."""
    if any(key.paths[dataset] for key in dim_keys):
        return _joined_branch_sql(graph, dataset, dim_keys, metric_names)
    sub = _submodel(graph, dataset, metric_names)
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
) -> str:
    """The ONE guarded SELECT: CTE per branch, a keys CTE unioning the branch
    group keys (UNION dedupes, NULL-inclusive), and an outer SELECT aligning
    aggregate outputs with null-safe equality. No-dimension plans cross-join
    the single-row aggregates instead."""
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
    return tree.sql(dialect="duckdb")


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
        _resolve_dimension(graph, name, branch_datasets, conformed_by_name)
        for name in dimension_names
    ]

    branch_sqls: list[str] = []
    branch_plans: list[BranchPlan] = []
    branch_keys: list[list[tuple[str, str]]] = []
    participating: dict[str, RelationshipEdge] = {}
    for dataset in branch_datasets:
        sql, edges = _branch_sql(
            graph,
            dataset,
            dim_keys,
            branch_metrics[dataset],
            [name for name in metric_names if owner_of[name] == dataset],
        )
        branch_sqls.append(sql)
        branch_plans.append(
            BranchPlan(
                dataset=dataset,
                metrics=tuple(sorted(branch_metrics[dataset])),
                joins=tuple(edge.name for edge in edges),
                keys=tuple((key.dimension, key.members[dataset]) for key in dim_keys),
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
    sql = _final_sql(branch_sqls, branch_keys, columns)
    statements = sqlglot.parse(sql)
    if len(statements) != 1:  # self-check: the guarded SELECT is one statement
        raise PlannerError(
            "not_one_statement",
            f"compiled plan is {len(statements)} statements, not one "
            "(no-unvalidated-execution invariant, spec §6)",
        )

    audits: list[AuditRecord] = []
    relationship_outcome, relationship_detail = "not-run", (
        "compile-only plan — no connection, no live relationship audit"
    )
    if connection is not None:
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
            relationship_outcome = "passed"
            relationship_detail = (
                f"{len(participating)} participating relationship(s) rechecked on this request"
            )
        else:
            relationship_detail = "no relationship traversal participates in this request"
        # F2: the legacy per-column guard belongs to AUTHORED sources — an
        # embedded or pre-joined table inside a declared source cannot bypass
        # it. The planner's GENERATED relationship joins are proven by the exact
        # tuple audit above, which accepts composite keys whose components
        # repeat while every tuple stays unique; re-judging them per column
        # would refuse valid composite lookups (review c90ca081 F2).
        guarded = sorted(set(branch_datasets) | {e.to_dataset for e in participating.values()})
        for name in guarded:
            try:
                check_grain_preserving(connection, graph.datasets[name].source)
            except ValueError as exc:  # GRAIN_GUIDANCE verbatim
                raise PlannerError("grain_not_preserving", str(exc)) from exc
            audits.append(AuditRecord(f"grain:{name}", "passed"))
        try:
            # nosemgrep — planner-generated sqlglot AST output, re-parsed above;
            # EXPLAIN binds without executing (no-unvalidated-execution invariant).
            # pi-lens-ignore: python-sql-injection — `sql` is the planner's own
            # AST render, never caller text; requests carry names only
            connection.execute(f"EXPLAIN {sql}")  # nosemgrep
        except Exception as exc:
            raise PlannerError(
                "bind_failed",
                f"compiled plan failed the EXPLAIN bind check: {type(exc).__name__}: {exc}",
            ) from exc
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
    )
