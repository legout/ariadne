"""Normalized multi-fact semantic graph (issue #26; spec rev 1, "Authoring
contract and normalized graph").

Both OSI authoring layouts normalize into ONE :class:`SemanticGraph`:

- **domain layout** — one ``semantic_model`` entry under ``semantic_layer/models/``
  carrying several datasets, inline ``relationships:`` and — behind the
  versioned, required ``ariadne.conformed_dimensions@1`` extension — inline
  ``conformed_dimensions:``;
- **source layout** — one single-dataset OSI file per source plus the optional
  cross-file ``semantic_layer/graph.yml`` (``relationships:`` and
  ``conformed_dimensions:``).

The graph is the gate ahead of the planner (#27+): duplicate model/dataset/
metric names, unsupported ``requires`` extension keys, duplicate or
contradictory relationship/conformance declarations, ambiguous ``COUNT(*)``
ownership, mixed-grain derived fields and metric dependency cycles are
:class:`GraphError`\\ s raised BEFORE any SELECT is compiled. Live
relationship-target/grain audits need a connection and belong to the next task;
this module never reports them as passed.
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

from ariadne.render import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    RenderError,
    _dialect_expression,
    _parse,
)

# Canonical extension keys, defined ONCE (spec rev 1 §Authoring contract 4: a
# versioned, required extension gates what OSI core cannot express — a future
# extension key is never silently assumed to work merely because the YAML parses).
SUPPORTED_REQUIRES = frozenset({"ariadne.conformed_dimensions@1"})
_CONFORMED_REQUIRES = "ariadne.conformed_dimensions@1"

# Typed relationship edges (spec rev 1 §Authoring contract 3). A one_to_many
# traversal is a planner concern, not a declarable edge kind.
CARDINALITIES = ("many_to_one", "one_to_one")

GRAPH_VERSION = 1
_GRAPH_KEYS = frozenset({"version", "relationships", "conformed_dimensions"})
_RELATIONSHIP_KEYS = frozenset(
    {"name", "cardinality", "from_dataset", "from_fields", "to_dataset", "to_fields"}
)
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
WINDOW_KINDS = frozenset(
    {"rolling", "cumulative", "prior_period", "ranking", "value_window"}
)
_WINDOW_KEYS = frozenset({"kind", "size", "function", "direction"})
_WINDOW_FUNCTIONS = frozenset({"sum", "avg", "min", "max", "count"})
_SIZED_KINDS = frozenset({"rolling", "value_window"})


class GraphError(ValueError):
    """Graph load/normalize failure — raised before any SELECT is compiled."""


@dataclass(frozen=True)
class DatasetNode:
    """One dataset with its declared grain (primary_key) and field inventory."""

    name: str
    model: str
    source: str
    primary_key: tuple[str, ...]
    fields: tuple[str, ...]
    time_fields: frozenset[str]
    # field name -> expression SQL where a usable dialect exists; type evidence
    # for conformance (absent entries fail in the schema/render path instead)
    expressions: dict[str, str]


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
    """One entry of the project-wide metric index. Base aggregates carry exactly
    one owning dataset; derived metrics (referencing other metrics) resolve
    ownership from their dependencies instead. ``fill`` (an explicit metric
    fill rule) applies to the OUTPUT only, never to a hidden ratio denominator;
    ``window`` moves the metric's declared expression to the post-aggregate
    window stage (issue #29)."""

    name: str
    owner: str | None
    expression: str
    derived: bool
    model: str
    deps: tuple[str, ...]
    fill: Any = None
    window: WindowDecl | None = None


@dataclass(frozen=True)
class SemanticGraph:
    datasets: dict[str, DatasetNode]
    metrics: dict[str, MetricNode]
    relationships: tuple[RelationshipEdge, ...]
    conformed_dimensions: tuple[ConformedEdge, ...]
    models: dict[str, dict]  # model name -> single-entry envelope (compile input)
    files: tuple[str, ...]  # consumed model files + optional graph.yml


def load_graph(semantic_dir: str | Path) -> SemanticGraph:
    """Load and normalize both authoring layouts from ``semantic_dir`` (the
    ``semantic_layer/`` directory: ``models/*.yml`` + optional ``graph.yml``).
    Raises :class:`GraphError` on any structural failure."""
    root = Path(semantic_dir)
    models_dir = root / "models"
    if not models_dir.is_dir():
        raise GraphError(f"no semantic models under {models_dir}")
    datasets: dict[str, DatasetNode] = {}
    envelopes: dict[str, dict] = {}
    # metric name -> (model, file, expression SQL, explicit owner | None, fill,
    # window declaration | None)
    raw_metrics: dict[str, tuple[str, str, str, str | None, Any, WindowDecl | None]] = {}
    raw_relationships: list[tuple[object, str]] = []
    raw_conformed: list[tuple[object, str]] = []
    files: list[str] = []

    for path in sorted(models_dir.glob("*.yml")):
        files.append(f"models/{path.name}")
        doc = _read_yaml(path)
        entries = doc.get("semantic_model")
        if not isinstance(entries, list) or not entries:
            raise GraphError(f"{path.name}: no semantic_model entries")
        for model in entries:
            if not isinstance(model, dict):
                raise GraphError(f"{path.name}: semantic_model entry is not a mapping")
            name = model.get("name")
            if not isinstance(name, str) or not name.strip():
                raise GraphError(f"{path.name}: semantic_model entry without a 'name'")
            if name in envelopes:
                raise GraphError(f"{path.name}: duplicate model '{name}'")
            _check_requires(model, name, path.name)
            envelopes[name] = {"version": doc.get("version"), "semantic_model": [model]}
            _load_datasets(model, name, path.name, datasets)
            _collect_metrics(model, name, path.name, raw_metrics)
            where = f"{path.name} model '{name}'"
            conformed = model.get("conformed_dimensions")
            if conformed is not None and _CONFORMED_REQUIRES not in (model.get("requires") or []):
                raise GraphError(
                    f"{where}: conformed_dimensions requires the versioned extension "
                    f"'{_CONFORMED_REQUIRES}' — declare requires: [\"{_CONFORMED_REQUIRES}\"]"
                )
            relationships = model.get("relationships")
            if relationships is not None and not isinstance(relationships, list):
                raise GraphError(
                    f"{where}: relationships must be a list of edge declarations"
                )
            for entry in relationships or []:
                raw_relationships.append((entry, where))
            if conformed is not None and not isinstance(conformed, list):
                raise GraphError(
                    f"{where}: conformed_dimensions must be a list of member declarations"
                )
            for entry in conformed or []:
                raw_conformed.append((entry, where))

    if not envelopes:
        raise GraphError(f"no semantic models under {models_dir}")

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
        metrics=_resolve_metrics(raw_metrics, datasets),
        relationships=_resolve_relationships(raw_relationships, datasets),
        conformed_dimensions=_resolve_conformed(raw_conformed, datasets),
        models=envelopes,
        files=tuple(files),
    )


def _read_yaml(path: Path) -> dict:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GraphError(f"{path.name}: not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise GraphError(f"{path.name}: top level is not a mapping")
    return doc


def _check_requires(model: dict, name: str, file: str) -> None:
    requires = model.get("requires")
    if requires is None:
        return
    if not isinstance(requires, list) or not all(isinstance(key, str) for key in requires):
        raise GraphError(f"{file} model '{name}': requires must be a list of extension keys")
    for key in requires:
        if key not in SUPPORTED_REQUIRES:
            raise GraphError(
                f"{file} model '{name}': unsupported requires extension key {key!r}; "
                f"supported: {sorted(SUPPORTED_REQUIRES)}"
            )


def _load_datasets(model: dict, model_name: str, file: str, datasets: dict[str, DatasetNode]):
    entries = model.get("datasets")
    if not isinstance(entries, list) or not entries:
        raise GraphError(f"{file} model '{model_name}': no datasets")
    for entry in entries:
        if not isinstance(entry, dict):
            raise GraphError(f"{file} model '{model_name}': dataset entry is not a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise GraphError(f"{file} model '{model_name}': dataset without a 'name'")
        if name in datasets:
            raise GraphError(
                f"{file} model '{model_name}': duplicate dataset '{name}' (already declared "
                f"by model '{datasets[name].model}')"
            )
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip():
            raise GraphError(f"{file} model '{model_name}' dataset '{name}': missing source")
        primary_key = entry.get("primary_key")
        if primary_key is not None and (
            not isinstance(primary_key, list)
            or not all(isinstance(key, str) for key in primary_key)
        ):
            raise GraphError(
                f"{file} model '{model_name}' dataset '{name}': "
                "primary_key must be a list of field names"
            )
        fields: list[str] = []
        expressions: dict[str, str] = {}
        time_fields: set[str] = set()
        for spec in entry.get("fields") or []:
            field_name = spec.get("name") if isinstance(spec, dict) else None
            if not isinstance(field_name, str) or not field_name.strip():
                raise GraphError(
                    f"{file} model '{model_name}' dataset '{name}': field name must "
                    "be a nonempty string"
                )
            if field_name in fields:
                raise GraphError(
                    f"{file} model '{model_name}' dataset '{name}': duplicate field "
                    f"'{field_name}'"
                )
            fields.append(field_name)
            try:
                expressions[field_name] = _dialect_expression(
                    spec.get("expression") or {}, f"field {field_name!r}"
                )
            except RenderError:
                pass  # missing/invalid dialects fail in the schema/render path
            if (spec.get("dimension") or {}).get("is_time"):
                time_fields.add(field_name)
        datasets[name] = DatasetNode(
            name=name,
            model=model_name,
            source=source.strip(),
            primary_key=tuple(primary_key or ()),
            fields=tuple(fields),
            time_fields=frozenset(time_fields),
            expressions=expressions,
        )


def _parse_window(raw: Any, where: str) -> WindowDecl | None:
    """One declared window form (issue #29): strict keys, one of the five
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
        raise GraphError(
            f"{where}: window 'direction' must be 'asc' or 'desc', got {direction!r}"
        )
    return WindowDecl(kind=kind, size=size, function=function, direction=direction)


def _collect_metrics(
    model: dict,
    model_name: str,
    file: str,
    raw: dict[str, tuple[str, str, str, str | None, Any, WindowDecl | None]],
) -> None:
    metrics = model.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise GraphError(f"{file} model '{model_name}': no metrics")
    for entry in metrics:
        if not isinstance(entry, dict):
            raise GraphError(f"{file} model '{model_name}': metric entry is not a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise GraphError(f"{file} model '{model_name}': metric without a 'name'")
        if name in raw:
            raise GraphError(
                f"{file} model '{model_name}': duplicate metric '{name}' (already declared "
                f"by model '{raw[name][0]}')"
            )
        try:
            expression = _dialect_expression(entry.get("expression") or {}, f"metric {name!r}")
        except RenderError as exc:
            raise GraphError(f"{file} model '{model_name}' metric '{name}': {exc}") from exc
        owner = entry.get("dataset")
        if owner is not None and not isinstance(owner, str):
            raise GraphError(
                f"{file} model '{model_name}' metric '{name}': dataset owner must be a name"
            )
        fill = entry.get("fill")
        if fill is not None and not isinstance(fill, (str, int, float, bool)):
            raise GraphError(
                f"{file} model '{model_name}' metric '{name}': 'fill' must be a scalar "
                "output value (applies to the output only, never a hidden ratio "
                "denominator)"
            )
        window = _parse_window(entry.get("window"), f"{file} model '{model_name}' metric '{name}'")
        raw[name] = (model_name, file, expression, owner, fill, window)


def _resolve_field_dataset(
    table: str, field_name: str, datasets: dict[str, DatasetNode], scope: list[str]
) -> str | None:
    """The dataset a ``(qualifier, field)`` reference resolves to, inside the
    metric's model's datasets (``scope``) — field names may repeat across models
    (legacy files share names like ``status``); only the model's own datasets
    are reachable from its expressions. Unknown references bind later (render's
    convention); a known-but-wrong qualifier or a field on several scoped
    datasets is an error — no silent choice."""
    if table:
        node = datasets.get(table)
        if node is not None:
            if field_name not in node.fields:
                raise GraphError(
                    f"field '{table}.{field_name}' does not exist on dataset '{table}'"
                )
            return table
    owners = [name for name in scope if field_name in datasets[name].fields]
    if len(owners) > 1:
        raise GraphError(
            f"field '{field_name}' exists on multiple datasets {sorted(owners)} — qualify it"
        )
    return owners[0] if owners else None


def _assert_acyclic(deps: dict[str, tuple[str, ...]]) -> None:
    """Metric dependency cycles fail at load, project-wide (spec rev 1 §5)."""
    done: set[str] = set()

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in done:
            return
        if name in stack:
            cycle = stack[stack.index(name) :] + (name,)
            raise GraphError(f"metric dependency cycle: {' -> '.join(cycle)}")
        for dep in deps.get(name, ()):
            visit(dep, (*stack, name))
        done.add(name)

    for name in sorted(deps):
        visit(name, ())


def _resolve_metrics(
    raw: dict[str, tuple[str, str, str, str | None, Any, WindowDecl | None]],
    datasets: dict[str, DatasetNode],
) -> dict[str, MetricNode]:
    names = set(raw)
    parsed: dict[str, tuple[list[tuple[str, str]], tuple[str, ...]]] = {}
    for name, (model_name, file, expression, _owner, _fill, _window) in raw.items():
        try:
            tree = _parse(expression, f"metric {name!r}")
        except RenderError as exc:
            raise GraphError(f"{file} metric '{name}': {exc}") from exc
        field_refs: list[tuple[str, str]] = []
        metric_refs: set[str] = set()
        for column in tree.find_all(exp.Column):
            if column.name in names:
                metric_refs.add(column.name)
            else:
                field_refs.append((column.table, column.name))
        parsed[name] = (field_refs, tuple(sorted(metric_refs)))
    _assert_acyclic({name: refs for name, (_fields, refs) in parsed.items()})

    def field_owners(name: str) -> set[str]:
        """Datasets the metric's bare field references resolve to."""
        model_name = raw[name][0]
        scope = [d.name for d in datasets.values() if d.model == model_name]
        owners: set[str] = set()
        for table, field_name in parsed[name][0]:
            resolved = _resolve_field_dataset(table, field_name, datasets, scope)
            if resolved is not None:
                owners.add(resolved)
        return owners

    # Base metrics first (derived metrics may depend on them in any file order):
    # explicit or field-resolved single-dataset ownership — and an explicit
    # 'dataset:' owner must AGREE with every resolved field reference, else the
    # expression would compile against the wrong dataset after qualifier
    # stripping.
    owner_of: dict[str, str] = {}
    for name, (model_name, file, expression, explicit, _fill, _window) in raw.items():
        if parsed[name][1]:
            continue  # derived: second pass below
        where = f"{file} model '{model_name}' metric '{name}'"
        model_datasets = [d.name for d in datasets.values() if d.model == model_name]
        owners = field_owners(name)
        if explicit is not None:
            if explicit not in datasets:
                raise GraphError(f"{where}: unknown dataset owner '{explicit}'")
            for resolved in sorted(owners - {explicit}):
                raise GraphError(
                    f"{where}: declared owner 'dataset: {explicit}' disagrees with field "
                    f"references resolving to dataset '{resolved}'"
                )
            owner_of[name] = explicit
        elif len(owners) == 1:
            owner_of[name] = owners.pop()
        elif not owners:
            # COUNT(*)-style aggregate with no column reference: only a
            # single-dataset model resolves it unambiguously (spec rev 1 §2).
            if len(model_datasets) != 1:
                raise GraphError(
                    f"{where}: expression references no dataset column and the model "
                    f"declares {len(model_datasets)} datasets — declare an explicit "
                    "'dataset:' owner"
                )
            owner_of[name] = model_datasets[0]
        else:
            raise GraphError(
                f"{where}: ambiguous ownership — field references span datasets "
                f"{sorted(owners)}; qualify the fields or declare 'dataset:'"
            )

    # Derived metrics inherit a single owning dataset when their whole
    # dependency closure stays inside it (the same fixed point compilation
    # applies); cross-fact chains compile with the planner (#27).
    changed = True
    while changed:
        changed = False
        for name in raw:
            deps = parsed[name][1]
            if not deps or name in owner_of or not all(dep in owner_of for dep in deps):
                continue
            dep_owners = {owner_of[dep] for dep in deps}
            if len(dep_owners) == 1:
                owner_of[name] = dep_owners.pop()
                changed = True

    metrics: dict[str, MetricNode] = {}
    for name, (model_name, file, expression, explicit, fill, window) in raw.items():
        deps = parsed[name][1]
        # a windowed output is terminal: a metric referencing one would nest a
        # window stage inside another expression (issue #29 — one declared
        # post-aggregate stage per metric)
        for dep in sorted(deps):
            if raw[dep][5] is not None:
                raise GraphError(
                    f"{file} model '{model_name}' metric '{name}': references windowed "
                    f"metric '{dep}' — a windowed metric is a terminal post-aggregate "
                    "output, not a dependency"
                )
        if not deps:
            metrics[name] = MetricNode(
                name=name,
                owner=owner_of[name],
                expression=expression,
                derived=False,
                model=model_name,
                deps=deps,
                fill=fill,
                window=window,
            )
            continue
        where = f"{file} model '{model_name}' metric '{name}'"
        if explicit is not None:
            raise GraphError(
                f"{where}: derived metrics take no explicit 'dataset:' owner — "
                "ownership follows the referenced metrics"
            )
        owners = field_owners(name)
        if len(owners) > 1:
            raise GraphError(
                f"{where}: mixed-grain field references span datasets {sorted(owners)}"
            )
        if owners:
            # Spec rev 1 §5 rejects mixed-grain/mixed-stage expressions: a bare
            # row-grain field may not ride alongside metric dependencies whose
            # owning datasets differ from (or span more than) the field's grain.
            grain = next(iter(owners))
            dep_owners = {owner_of.get(dep) for dep in deps}
            if dep_owners != {grain}:
                raise GraphError(
                    f"{where}: mixed-stage expression — bare field reference at "
                    f"'{grain}' grain alongside metric dependencies resolving to "
                    f"{sorted(owner for owner in dep_owners if owner is not None)}"
                )
        metrics[name] = MetricNode(
            name=name,
            owner=None,
            expression=expression,
            derived=True,
            model=model_name,
            deps=deps,
            fill=fill,
            window=window,
        )
    return metrics


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
        cardinality = entry.get("cardinality")
        if cardinality not in CARDINALITIES:
            raise GraphError(
                f"{where} relationship '{name}': cardinality must be one of "
                f"{list(CARDINALITIES)}, got {cardinality!r}"
            )
        endpoints = []
        for key in ("from_dataset", "to_dataset"):
            dataset = entry.get(key)
            # isinstance first: an unhashable value must fail as GraphError, not
            # as a TypeError from the dict lookup
            if not isinstance(dataset, str) or dataset not in datasets:
                raise GraphError(
                    f"{where} relationship '{name}': unknown {key} {dataset!r}"
                )
            endpoints.append(dataset)
        from_dataset, to_dataset = endpoints
        keys: list[tuple[str, list | None, str]] = [
            ("from_fields", entry.get("from_fields"), from_dataset),
            ("to_fields", entry.get("to_fields"), to_dataset),
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
                f"{where} relationship '{name}': from_fields and to_fields must have "
                "equal length"
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
    """Spec rev 1 §3: the join graph must be bounded, acyclic and unambiguous —
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
            if not isinstance(member, dict) or set(member) - _MEMBER_KEYS or not {
                "dataset",
                "field",
            } <= set(member):
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
            # the coarsest of them (issue #29)
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
