"""Normalized multi-fact semantic graph over Ossie ``0.3.0.dev0`` documents
(spec 0039 §5; originally issue #26).

Every ``semantic_layer/models/*.yml|yaml`` file is ONE Ossie model document
(:mod:`ariadne.ossie` owns schema validation, name resolution and the
``ARIADNE`` extension). The documents normalize into ONE :class:`SemanticGraph`;
relationships come from the models' ``relationships`` and from the optional
Ariadne-specific, non-portable ``semantic_layer/graph.yml`` (cross-model
``relationships`` with the same ``name``/``from``/``to``/``from_columns``/
``to_columns`` keys, an optional ``cardinality: one_to_one``, and
``conformed_dimensions``).

The graph is the gate ahead of the planner: duplicate model/dataset/metric
names, duplicate or contradictory relationship/conformance declarations and
metric dependencies outside ``AGG(dataset.metric)`` are :class:`GraphError`\\ s
raised BEFORE any SELECT is compiled. Live relationship-target/grain audits need
a connection and belong to the planner; this module never reports them as
passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlglot import (  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
    exp,
)
from sqlglot.optimizer.annotate_types import (  # pyright: ignore[reportMissingImports]
    annotate_types,
)

from ariadne import ossie  # pyright: ignore[reportMissingImports] — new-module resolver drift
from ariadne.render import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    RenderError,
    _parse,
)

# Typed relationship edges. Ossie's default is many-to-one; the ARIADNE
# extension (or graph.yml) may declare ``one_to_one`` (spec 0039 §5.2). A
# one_to_many traversal is a planner concern, not a declarable edge kind.
CARDINALITIES = ("many_to_one", "one_to_one")

GRAPH_VERSION = 1
_GRAPH_KEYS = frozenset({"version", "relationships", "conformed_dimensions"})
_RELATIONSHIP_KEYS = frozenset({"name", "cardinality", "from", "from_columns", "to", "to_columns"})
_CONFORMED_KEYS = frozenset({"name", "members"})
_MEMBER_KEYS = frozenset({"dataset", "field", "native_grain"})

# Declared time grains a conformed primary business time may group at, finest
# first (spec rev 1 "Query and result contract": day/week/month/quarter/year;
# a request finer than a declared native grain refuses).
TIME_GRAINS = ("day", "week", "month", "quarter", "year")

# Declared window forms (spec rev 1 "Query and result contract"): rolling,
# cumulative, prior-period, ranking and value windows all operate at their
# declared POST-aggregate stage over the aligned output — never inside a fact
# branch. ``size`` is whole groups for ``rolling`` and grain periods for
# ``value_window`` (a RANGE frame over the time axis).
WINDOW_KINDS = frozenset({"rolling", "cumulative", "prior_period", "ranking", "value_window"})
_WINDOW_KEYS = frozenset({"kind", "size", "function", "direction"})
_WINDOW_FUNCTIONS = frozenset({"sum", "avg", "min", "max", "count"})
_SIZED_KINDS = frozenset({"rolling", "value_window"})


class GraphError(ValueError):
    """Graph load/normalize failure — raised before any SELECT is compiled."""


@dataclass(frozen=True)
class DatasetNode:
    """One dataset with its declared grain (primary_key, a tuple of FIELD
    names) and field inventory."""

    name: str
    model: str
    source: str
    primary_key: tuple[str, ...]
    fields: tuple[str, ...]
    time_fields: frozenset[str]
    # field name -> expression SQL over the dataset's SOURCE columns (Ossie 0.3
    # field expressions never reference other fields)
    expressions: dict[str, str]
    unique_keys: tuple[tuple[str, ...], ...] = ()
    dimensions: frozenset[str] = frozenset()  # fields declaring a ``dimension`` object


@dataclass(frozen=True)
class RelationshipEdge:
    """A typed join edge: ``from_dataset`` (the many side of a many_to_one)
    reaches ``to_dataset`` through a unique target key."""

    name: str
    cardinality: str  # many_to_one | one_to_one
    from_dataset: str
    to_dataset: str
    from_fields: tuple[str, ...]
    to_fields: tuple[str, ...]


@dataclass(frozen=True)
class ConformedEdge:
    """Equivalent business group keys on multiple facts — never a raw join.

    ``native_grains`` carries each member's declared native time grain and is
    nonempty exactly for a conformed primary business time (all members are
    time fields; spec rev 1 "Query and result contract")."""

    name: str
    members: tuple[tuple[str, str], ...]  # (dataset, field)
    # True only when every member carried parseable type evidence that agreed;
    # absent evidence is disclosed by the validator, never treated as established
    type_verified: bool
    native_grains: dict[str, str] = field(default_factory=dict)  # dataset -> grain


@dataclass(frozen=True)
class WindowDecl:
    """One declared post-aggregate window (issue #29; spec rev 1 "Query and
    result contract"): the declared form operates over the ALIGNED output,
    after fact branches merge."""

    kind: str  # one of WINDOW_KINDS
    size: int | None = None  # rolling: groups; value_window: grain periods
    function: str = "sum"  # window aggregate (not prior_period/ranking)
    direction: str = "desc"  # ranking order only


@dataclass(frozen=True)
class MetricNode:
    """One entry of the project-wide metric index, keyed by its IDENTITY
    ``<model>::<key>`` (spec 0039 §6): ``key`` is ``<metric>`` for a
    model-scoped metric and ``<dataset>.<metric>`` for a dataset-scoped one.
    A measure carries exactly one owning dataset and its expression LOWERED to
    that dataset's source columns; a derived metric (a model-scoped composition
    of ``AGG(dataset.metric)`` terms) keeps its authored expression and names
    the identities of the dataset-scoped metrics it consumes in ``deps``.
    ``fill`` applies to the OUTPUT only, never to a hidden ratio denominator;
    ``window`` moves the metric to the post-aggregate window stage."""

    name: str  # the identity ``<model>::<key>``
    owner: str | None
    expression: str
    derived: bool
    model: str
    deps: tuple[str, ...]
    fill: Any = None
    window: WindowDecl | None = None
    key: str = ""  # ``<metric>`` or ``<dataset>.<metric>``
    short: str = ""  # the unqualified metric name
    description: str = ""

    @property
    def identity(self) -> str:
        return self.name


@dataclass(frozen=True)
class SemanticGraph:
    datasets: dict[str, DatasetNode]
    metrics: dict[str, MetricNode]
    relationships: tuple[RelationshipEdge, ...]
    conformed_dimensions: tuple[ConformedEdge, ...]
    models: dict[str, ossie.ParsedModel]  # model name -> resolved Ossie model
    files: tuple[str, ...]  # consumed model files + optional graph.yml


def load_graph(semantic_dir: str | Path) -> SemanticGraph:
    """Load and normalize ``semantic_dir`` (the ``semantic_layer/`` directory:
    ``models/*.yml|yaml`` Ossie documents + optional ``graph.yml``). Raises
    :class:`GraphError` on any structural failure, naming the file."""
    root = Path(semantic_dir)
    models_dir = root / "models"
    if not models_dir.is_dir():
        raise GraphError(f"no semantic models under {models_dir}")
    datasets: dict[str, DatasetNode] = {}
    models: dict[str, ossie.ParsedModel] = {}
    metrics: dict[str, MetricNode] = {}
    raw_relationships: list[tuple[object, str]] = []
    raw_conformed: list[tuple[object, str]] = []
    files: list[str] = []

    for path in sorted((*models_dir.glob("*.yml"), *models_dir.glob("*.yaml"))):
        files.append(f"models/{path.name}")
        try:
            parsed = ossie.parse_model(ossie.read_document(path), path.name)
        except ossie.OssieError as exc:
            raise GraphError(str(exc)) from exc
        name = parsed.name
        if name in models:
            raise GraphError(f"{path.name}: duplicate model '{name}'")
        models[name] = parsed
        where = f"{path.name} model '{name}'"
        for dataset in parsed.datasets.values():
            if dataset.name in datasets:
                raise GraphError(
                    f"{where}: duplicate dataset '{dataset.name}' (already declared "
                    f"by model '{datasets[dataset.name].model}')"
                )
            datasets[dataset.name] = DatasetNode(
                name=dataset.name,
                model=name,
                source=dataset.source,
                primary_key=dataset.primary_key,
                fields=tuple(dataset.fields),
                time_fields=frozenset(n for n, f in dataset.fields.items() if f.is_time),
                expressions={n: f.sql for n, f in dataset.fields.items()},
                unique_keys=dataset.unique_keys,
                dimensions=frozenset(n for n, f in dataset.fields.items() if f.dimension),
            )
        for metric in parsed.metrics.values():
            window = _parse_window(metric.window, f"{where} metric '{metric.key}'")
            identity = ossie.metric_identity(name, metric.key)
            metrics[identity] = MetricNode(
                name=identity,
                owner=metric.owner,
                expression=metric.expression,
                derived=metric.derived,
                model=name,
                deps=tuple(ossie.metric_identity(name, dep) for dep in metric.deps),
                fill=metric.fill,
                window=window,
                key=metric.key,
                short=metric.name,
                description=metric.description,
            )
        for entry in parsed.relationships:
            raw_relationships.append((entry, where))
        for entry in parsed.conformed:
            raw_conformed.append((entry, where))

    if not models:
        raise GraphError(f"no semantic models under {models_dir}")
    _assert_acyclic_windows(metrics)

    graph_path = root / "graph.yml"
    if graph_path.is_file():
        files.append("graph.yml")
        doc = _read_yaml(graph_path)
        unknown = sorted(set(doc) - _GRAPH_KEYS)
        if unknown:
            raise GraphError(f"graph.yml: unknown key(s) {unknown}; allowed: {sorted(_GRAPH_KEYS)}")
        if doc.get("version") != GRAPH_VERSION:
            raise GraphError(
                f"graph.yml: version must be {GRAPH_VERSION}, got {doc.get('version')!r}"
            )
        relationships = doc.get("relationships")
        if relationships is not None and not isinstance(relationships, list):
            raise GraphError("graph.yml: relationships must be a list of edge declarations")
        for entry in relationships or []:
            raw_relationships.append((entry, "graph.yml"))
        conformed = doc.get("conformed_dimensions")
        if conformed is not None and not isinstance(conformed, list):
            raise GraphError(
                "graph.yml: conformed_dimensions must be a list of member declarations"
            )
        for entry in conformed or []:
            raw_conformed.append((entry, "graph.yml"))

    return SemanticGraph(
        datasets=datasets,
        metrics=metrics,
        relationships=_resolve_relationships(raw_relationships, datasets),
        conformed_dimensions=_resolve_conformed(raw_conformed, datasets),
        models=models,
        files=tuple(files),
    )


def _assert_acyclic_windows(metrics: dict[str, MetricNode]) -> None:
    """A windowed output is terminal: a derived metric may not consume a
    windowed dataset-scoped metric (one declared post-aggregate stage per
    metric, issue #29)."""
    for node in metrics.values():
        for dep in node.deps:
            if metrics[dep].window is not None:
                raise GraphError(
                    f"model '{node.model}' metric '{node.name}': references windowed "
                    f"metric '{dep}' — a windowed metric is a terminal post-aggregate "
                    "output, not a dependency"
                )


def _read_yaml(path: Path) -> dict:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GraphError(f"{path.name}: not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise GraphError(f"{path.name}: top level is not a mapping")
    return doc


def _parse_window(raw: Any, where: str) -> WindowDecl | None:
    """One declared window form: strict keys, one of the five
    declared kinds, a positive integer size for the sized forms, an aggregate
    function for the aggregating forms and an order direction for ranking."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise GraphError(f"{where}: 'window' must be a mapping of window declarations")
    unknown = sorted(set(raw) - _WINDOW_KEYS)
    if unknown:
        raise GraphError(
            f"{where}: window unknown key(s) {unknown}; allowed: {sorted(_WINDOW_KEYS)}"
        )
    kind = raw.get("kind")
    if kind not in WINDOW_KINDS:
        raise GraphError(
            f"{where}: window 'kind' must be one of {sorted(WINDOW_KINDS)}, got {kind!r}"
        )
    size = raw.get("size")
    if kind in _SIZED_KINDS:
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise GraphError(f"{where}: a {kind} window needs a positive integer 'size'")
    elif size is not None:
        raise GraphError(f"{where}: a {kind} window takes no 'size'")
    function = raw.get("function", "sum")
    if kind in ("prior_period", "ranking"):
        if "function" in raw:
            raise GraphError(f"{where}: a {kind} window takes no 'function'")
    elif function not in _WINDOW_FUNCTIONS:
        raise GraphError(
            f"{where}: window 'function' must be one of {sorted(_WINDOW_FUNCTIONS)}, "
            f"got {function!r}"
        )
    direction = raw.get("direction", "desc")
    if kind != "ranking" and "direction" in raw:
        raise GraphError(f"{where}: only a ranking window declares 'direction'")
    if direction not in ("asc", "desc"):
        raise GraphError(f"{where}: window 'direction' must be 'asc' or 'desc', got {direction!r}")
    return WindowDecl(kind=kind, size=size, function=function, direction=direction)


def _resolve_relationships(
    raw: list[tuple[object, str]], datasets: dict[str, DatasetNode]
) -> tuple[RelationshipEdge, ...]:
    edges: list[RelationshipEdge] = []
    by_pair: dict[tuple[str, str], RelationshipEdge] = {}
    names: set[str] = set()
    for entry, where in raw:
        if not isinstance(entry, dict):
            raise GraphError(f"{where}: relationship entry is not a mapping")
        unknown = sorted(set(entry) - _RELATIONSHIP_KEYS)
        if unknown:
            raise GraphError(
                f"{where}: relationship unknown key(s) {unknown}; "
                f"allowed: {sorted(_RELATIONSHIP_KEYS)}"
            )
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise GraphError(f"{where}: relationship without a 'name'")
        cardinality = entry.get("cardinality", "many_to_one")
        if cardinality not in CARDINALITIES:
            raise GraphError(
                f"{where} relationship '{name}': cardinality must be one of "
                f"{list(CARDINALITIES)}, got {cardinality!r}"
            )
        endpoints = []
        for key in ("from", "to"):
            dataset = entry.get(key)
            # isinstance first: an unhashable value must fail as GraphError, not
            # as a TypeError from the dict lookup
            if not isinstance(dataset, str) or dataset not in datasets:
                raise GraphError(f"{where} relationship '{name}': unknown {key} {dataset!r}")
            endpoints.append(dataset)
        from_dataset, to_dataset = endpoints
        keys: list[tuple[str, list | None, str]] = [
            ("from_columns", entry.get("from_columns"), from_dataset),
            ("to_columns", entry.get("to_columns"), to_dataset),
        ]
        field_lists = []
        for label, fields, dataset in keys:
            if (
                not isinstance(fields, list)
                or not fields
                or not all(isinstance(f, str) for f in fields)
            ):
                raise GraphError(
                    f"{where} relationship '{name}': {label} must be a non-empty list "
                    "of field names"
                )
            for f in fields:
                if f not in datasets[dataset].fields:
                    raise GraphError(
                        f"{where} relationship '{name}': dataset '{dataset}' has no field '{f}'"
                    )
            field_lists.append(fields)
        if len(field_lists[0]) != len(field_lists[1]):
            raise GraphError(
                f"{where} relationship '{name}': from_columns and to_columns must have equal length"
            )
        edge = RelationshipEdge(
            name=name,
            cardinality=cardinality,
            from_dataset=from_dataset,
            to_dataset=to_dataset,
            from_fields=tuple(field_lists[0]),
            to_fields=tuple(field_lists[1]),
        )
        previous = by_pair.get((from_dataset, to_dataset))
        if previous is not None:
            kind = "duplicate edge" if previous == edge else "contradictory declaration"
            raise GraphError(
                f"{where} relationship '{name}': {kind} for {from_dataset} -> {to_dataset} "
                f"(already declared as '{previous.name}' {previous.cardinality})"
            )
        if name in names:
            raise GraphError(f"{where}: duplicate relationship name '{name}'")
        names.add(name)
        by_pair[(from_dataset, to_dataset)] = edge
        edges.append(edge)
    _assert_topology(edges)
    return tuple(edges)


def _assert_topology(edges: list[RelationshipEdge]) -> None:
    """the join graph must be bounded, acyclic and unambiguous —
    no directed cycles, and at most one simple path between any dataset pair (a
    diamond of individually well-formed edges leaves the join path ambiguous).
    Simple-path counting is exponential in pathological topologies; hand-authored
    join graphs are tiny."""
    graph: dict[str, list[str]] = {}
    for edge in edges:
        graph.setdefault(edge.from_dataset, []).append(edge.to_dataset)

    state: dict[str, str] = {}  # "visiting" | "done"

    def visit(node: str, stack: tuple[str, ...]) -> None:
        state[node] = "visiting"
        for nxt in graph.get(node, ()):
            if state.get(nxt) == "visiting":
                cycle = stack[stack.index(nxt) :] + (nxt,)
                raise GraphError(f"relationship cycle: {' -> '.join(cycle)}")
            if nxt not in state:
                visit(nxt, (*stack, nxt))
        state[node] = "done"

    for node in sorted(graph):
        if node not in state:
            visit(node, (node,))

    def count_paths(start: str) -> dict[str, int]:
        counts: dict[str, int] = {}

        def walk(node: str, seen: frozenset[str]) -> None:
            for nxt in graph.get(node, ()):
                if nxt in seen:
                    continue
                counts[nxt] = counts.get(nxt, 0) + 1
                walk(nxt, seen | {nxt})

        walk(start, frozenset({start}))
        return counts

    for start in sorted(graph):
        ambiguous = sorted(node for node, count in count_paths(start).items() if count > 1)
        if ambiguous:
            raise GraphError(
                f"ambiguous relationship paths from '{start}' to {ambiguous} — spec rev "
                "1 §3 requires one bounded, unambiguous path per dataset pair"
            )


def _value_type(sql: str | None, context: str) -> str | None:
    """Coarse value-type class of a field expression ('text' | 'number' |
    'time' | 'boolean') from sqlglot's type annotation of the parsed evidence.
    ``None`` when there is no evidence — a bare source column whose type only
    the live database knows, or an unparsable expression (those fail in the
    compile path instead, where every dataset's fields are checked)."""
    if sql is None:
        return None
    try:
        tree = annotate_types(_parse(sql, context))
    except RenderError:
        return None
    kind = tree.type.this
    if kind in exp.DataType.TEXT_TYPES:
        return "text"
    if kind in exp.DataType.NUMERIC_TYPES:
        return "number"
    if kind in exp.DataType.TEMPORAL_TYPES:
        return "time"
    if kind == exp.DataType.Type.BOOLEAN:
        return "boolean"
    return None


def _resolve_conformed(
    raw: list[tuple[object, str]], datasets: dict[str, DatasetNode]
) -> tuple[ConformedEdge, ...]:
    out: list[ConformedEdge] = []
    names: set[str] = set()
    for entry, where in raw:
        if not isinstance(entry, dict):
            raise GraphError(f"{where}: conformed dimension entry is not a mapping")
        unknown = sorted(set(entry) - _CONFORMED_KEYS)
        if unknown:
            raise GraphError(
                f"{where}: conformed dimension unknown key(s) {unknown}; "
                f"allowed: {sorted(_CONFORMED_KEYS)}"
            )
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise GraphError(f"{where}: conformed dimension without a 'name'")
        if name in names:
            raise GraphError(
                f"{where}: duplicate conformed dimension '{name}' — conflicting mappings "
                "fail rather than overwrite"
            )
        names.add(name)
        members_raw = entry.get("members")
        if not isinstance(members_raw, list) or len(members_raw) < 2:
            raise GraphError(f"{where} conformed dimension '{name}': needs at least 2 members")
        members: list[tuple[str, str]] = []
        member_types: list[str | None] = []
        seen: set[str] = set()
        time_roles: set[bool] = set()
        native_grains: dict[str, str] = {}
        for member in members_raw:
            if (
                not isinstance(member, dict)
                or set(member) - _MEMBER_KEYS
                or not {
                    "dataset",
                    "field",
                }
                <= set(member)
            ):
                raise GraphError(
                    f"{where} conformed dimension '{name}': each member is "
                    f"'dataset' + 'field' plus optional 'native_grain'; allowed: "
                    f"{sorted(_MEMBER_KEYS)}"
                )
            dataset, field_name = member["dataset"], member["field"]
            if not isinstance(dataset, str) or not isinstance(field_name, str):
                raise GraphError(
                    f"{where} conformed dimension '{name}': member 'dataset' and "
                    "'field' must be field names"
                )
            node = datasets.get(dataset)
            if node is None:
                raise GraphError(
                    f"{where} conformed dimension '{name}': unknown dataset {dataset!r}"
                )
            if field_name not in node.fields:
                raise GraphError(
                    f"{where} conformed dimension '{name}': dataset '{dataset}' has "
                    f"no field '{field_name}'"
                )
            if dataset in seen:
                raise GraphError(
                    f"{where} conformed dimension '{name}': dataset '{dataset}' supplies "
                    "two members — one dataset, one member per class"
                )
            seen.add(dataset)
            is_time = field_name in node.time_fields
            time_roles.add(is_time)
            grain = member.get("native_grain")
            if grain is not None:
                if not is_time:
                    raise GraphError(
                        f"{where} conformed dimension '{name}': member "
                        f"'{dataset}.{field_name}' declares native_grain but is not a "
                        "time field (dimension.is_time)"
                    )
                if grain not in TIME_GRAINS:
                    raise GraphError(
                        f"{where} conformed dimension '{name}': member "
                        f"'{dataset}.{field_name}' native_grain must be one of "
                        f"{list(TIME_GRAINS)}, got {grain!r}"
                    )
                native_grains[dataset] = grain
            member_types.append(
                _value_type(node.expressions.get(field_name), f"field {field_name!r}")
            )
            members.append((dataset, field_name))
        if len(time_roles) > 1:
            raise GraphError(
                f"{where} conformed dimension '{name}': incompatible time roles — "
                "members must all be time fields or none"
            )
        if time_roles == {True} and len(native_grains) != len(members):
            # a declared conformed primary business time carries its native
            # grain on every member — the planner refuses requests finer than
            # the coarsest of them
            missing = sorted(dataset for dataset, _field in members if dataset not in native_grains)
            raise GraphError(
                f"{where} conformed dimension '{name}': a conformed primary business "
                f"time declares 'native_grain' on EVERY member — missing on {missing}"
            )
        evidence = sorted({kind for kind in member_types if kind is not None})
        if len(evidence) > 1:
            raise GraphError(
                f"{where} conformed dimension '{name}': incompatible value types "
                f"{evidence} — members must be value-type compatible (spec rev 1 §3)"
            )
        out.append(
            ConformedEdge(
                name=name,
                members=tuple(members),
                type_verified=all(kind is not None for kind in member_types),
                native_grains=native_grains,
            )
        )
    return tuple(out)


def metric_owners(graph: SemanticGraph, name: str) -> set[str]:
    """The dataset-level owning-fact set of one metric (by IDENTITY): its own
    owner, or the union over the dataset-scoped metrics it composes."""
    node = graph.metrics.get(name)
    if node is None:
        return set()
    if node.owner is not None:
        return {node.owner}
    owners: set[str] = set()
    for dep in node.deps:
        owners |= metric_owners(graph, dep)
    return owners


def resolve_metric(graph: SemanticGraph, name: str) -> tuple[str | None, list[str]]:
    """``(identity, candidates)`` of a requested metric name (spec 0039 §6.4).

    A full identity (``model::key``) resolves exactly. A bare name matches the
    short metric name or the dataset-qualified key; it resolves when exactly
    one metric matches across the project. ``identity`` is ``None`` when the
    name is unknown (``candidates`` empty) or ambiguous (``candidates`` lists
    the matching full identities)."""
    if name in graph.metrics:
        return name, []
    if "::" in name:
        return None, []
    matches = sorted(
        identity for identity, node in graph.metrics.items() if name in (node.short, node.key)
    )
    if len(matches) == 1:
        return matches[0], []
    return None, matches
