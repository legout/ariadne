"""Apache Ossie ``0.3.0.dev0`` documents (spec 0039 §5, ADR-0028).

One model document per file, the model at the root. This module owns:

- reading and validating one document against the pinned, vendored
  ``ossie-schema.json`` (no new dependency: ``jsonschema`` already ships);
- the ``ARIADNE`` ``nonportable_extensions`` entries (unknown keys refuse,
  other vendors' entries are preserved untouched);
- strict Ossie name resolution (spec §5.3): a field expression references
  source columns only, keys and relationship columns name fields, a
  dataset-scoped metric references fields or ``source.column``, a model-scoped
  metric references ``dataset.field`` or ``AGG(dataset.metric)``;
- ``expression.sql`` selection (spec §5.4) and the lowering of every metric to
  SQL over its dataset's source columns, done once so the compilers never
  resolve a name twice.

Everything raises :class:`OssieError`, a ``ValueError`` whose message is the
verbatim reason; the loaders re-raise it as their own error type.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml
from jsonschema import Draft202012Validator  # pyright: ignore[reportMissingImports]
from sqlglot import exp  # pyright: ignore[reportMissingImports]

OSSIE_VERSION = "0.3.0.dev0"
PRIMARY_DIALECT = "OSSIE_SQL_2026"
VENDOR = "ARIADNE"
MIGRATE_HINT = "run `ariadne migrate --project <project>` to convert it"
_TEMPORAL = frozenset({"Date", "Time", "DateTime", "DateTimeTz"})

# Allowed ``data`` keys of the ARIADNE extension per location (spec §5.2).
_EXTENSION_KEYS = {
    "model": frozenset({"conformed_dimensions"}),
    "relationship": frozenset({"cardinality"}),
    "metric": frozenset({"fill", "window"}),
    "dataset": frozenset(),
    "field": frozenset(),
}


class OssieError(ValueError):
    """Document, schema or name-resolution failure; the message is verbatim."""


# ----------------------------------------------------------------- documents


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    data = (
        resources.files("ariadne")
        .joinpath("schemas")
        .joinpath("ossie")
        .joinpath("ossie-schema.json")
        .read_bytes()
    )
    return Draft202012Validator(json.loads(data))


def _json_values(node: Any, path: str) -> None:
    """``data`` must be JSON-representable (spec: a date or non-finite float
    under ``data`` is a schema error)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                raise OssieError(f"{path}: non-string mapping key {key!r} is not JSON")
            _json_values(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _json_values(value, f"{path}[{index}]")
    elif isinstance(node, float):
        if node != node or node in (float("inf"), float("-inf")):
            raise OssieError(f"{path}: non-finite float is not a JSON value")
    elif node is not None and not isinstance(node, (str, int, bool)):
        raise OssieError(
            f"{path}: {type(node).__name__} value {node!r} is not JSON — quote it "
            "(dates and timestamps must be strings)"
        )


def read_document(path: Path) -> dict:
    """The validated Ossie document at ``path`` (YAML or JSON)."""
    name = path.name
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise OssieError(f"{name}: not valid YAML: {exc}") from exc
    return validate_document(doc, name)


def validate_document(doc: Any, name: str) -> dict:
    """Refuse anything that is not one valid Ossie ``0.3.0.dev0`` document."""
    if not isinstance(doc, dict):
        raise OssieError(f"{name}: top level is not a mapping")
    if "semantic_model" in doc:
        raise OssieError(
            f"{name}: the retired `semantic_model` envelope (Ossie 0.2.0.dev0) is no longer "
            f"read; {MIGRATE_HINT}"
        )
    if doc.get("version") != OSSIE_VERSION:
        raise OssieError(
            f"{name}: version must be {OSSIE_VERSION}, got {doc.get('version')!r}; {MIGRATE_HINT}"
        )
    errors = sorted(_validator().iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "(root)"
        more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
        raise OssieError(
            f"{name}: violates the pinned Ossie {OSSIE_VERSION} schema at {where}: "
            f"{first.message}{more}; {MIGRATE_HINT} if this is an older document"
        )
    return doc


def extension_data(entity: dict, kind: str, where: str) -> dict:
    """The ARIADNE extension ``data`` of one entity (``{}`` when absent).

    Unknown keys refuse; entries of other vendors are ignored here and stay in
    the document untouched (spec §5.2)."""
    entries = [
        item for item in entity.get("nonportable_extensions") or [] if item["vendor_name"] == VENDOR
    ]
    if not entries:
        return {}
    if len(entries) > 1:
        raise OssieError(f"{where}: more than one {VENDOR} nonportable_extensions entry")
    data = entries[0]["data"]
    _json_values(data, f"{where} {VENDOR}.data")
    allowed = _EXTENSION_KEYS[kind]
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise OssieError(
            f"{where}: unknown {VENDOR} extension key(s) {unknown}; a {kind} supports "
            f"{sorted(allowed) or 'no keys'}"
        )
    return data


def expression_sql(block: dict, context: str) -> str:
    """The ``OSSIE_SQL_2026`` text of one expression block (spec §5.4): the
    top-level ``sql`` is authoritative, else the ``OSSIE_SQL_2026`` dialect
    entry. Another dialect alone is opaque to Ariadne and refuses."""
    sql = (block or {}).get("sql")
    if isinstance(sql, str) and sql.strip():
        return sql
    for entry in (block or {}).get("dialects") or []:
        if entry.get("dialect") == PRIMARY_DIALECT:
            return entry["expression"]
    dialects = sorted({entry.get("dialect") for entry in (block or {}).get("dialects") or []})
    raise OssieError(
        f"{context}: the expression has no `sql` and no {PRIMARY_DIALECT} dialect entry "
        f"(only {dialects} present, which Ariadne cannot interpret)"
    )


def parse_sql(sql: str, context: str) -> Any:
    try:
        return sqlglot.parse_one(sql)
    except Exception as exc:
        raise OssieError(
            f"could not parse expression for {context}: {type(exc).__name__}: {exc}"
        ) from exc


def refuse_relations(tree: Any, context: str) -> None:
    """A field, metric or key expression is scalar/aggregate over its own row
    source: a subquery, ``EXISTS``, ``IN (SELECT ...)``, a table function or a
    table reference would read a relation the source authorization never sees."""
    found = tree.find(exp.Query, exp.Exists, exp.Table, exp.UDTF)
    if found is not None:
        raise OssieError(
            f"{context}: the expression contains a relational construct "
            f"({found.sql()[:60]!r}) — subqueries, EXISTS, IN (SELECT ...), table functions "
            "and table references are not allowed in a field or metric expression; read "
            "other relations through the dataset `source`"
        )


def agg_calls(tree: Any) -> list[Any]:
    """Every ``AGG(...)`` call node of an expression (sqlglot reads it as
    ``exp.Agg``)."""
    return list(tree.find_all(exp.Agg))


def agg_target(call: Any, context: str) -> tuple[str, str]:
    """``(dataset, metric)`` of one ``AGG(dataset.metric)`` call: the argument
    must be exactly one qualified reference and the call may not carry a
    ``FILTER (WHERE ...)`` clause (spec metric scoping rule 6)."""
    column = call.this
    if not isinstance(column, exp.Column) or not column.table:
        raise OssieError(
            f"{context}: AGG takes exactly one `dataset.metric` reference of a "
            "dataset-scoped metric"
        )
    if isinstance(call.parent, exp.Filter):
        raise OssieError(f"{context}: AGG(...) may not carry a FILTER (WHERE ...) clause")
    return column.table, column.name


def _grouped(tree: Any) -> Any:
    """A substituted field expression keeps its grouping: anything that is not
    self-delimiting is parenthesized (``price = a + b`` in ``price * units``)."""
    atomic = (exp.Column, exp.Literal, exp.Paren, exp.Func, exp.Null, exp.Boolean)
    return tree if isinstance(tree, atomic) else exp.Paren(this=tree)


def _strip_qualifiers(tree: Any) -> Any:
    for column in tree.find_all(exp.Column):
        column.set("table", None)
    return tree


# --------------------------------------------------------------- parsed model


@dataclass(frozen=True)
class ParsedField:
    name: str
    sql: str  # over the dataset's source columns, unqualified
    is_time: bool
    dimension: bool  # a ``dimension`` object is declared


@dataclass(frozen=True)
class ParsedDataset:
    name: str
    source: str
    primary_key: tuple[str, ...]
    unique_keys: tuple[tuple[str, ...], ...]
    fields: dict[str, ParsedField]


@dataclass(frozen=True)
class ParsedMetric:
    key: str  # ``name`` (model-scoped) or ``dataset.name`` (dataset-scoped)
    name: str
    scope: str  # dataset | model
    declared_on: str | None  # declaring dataset (dataset-scoped)
    owner: str | None  # the fact branch owning a measure; None for derived
    derived: bool
    expression: str  # measure: lowered SQL over source columns; derived: authored SQL with AGG
    deps: tuple[str, ...]  # derived: dataset-scoped metric keys referenced by AGG
    fill: Any = None
    window: Any = None
    description: str = ""


@dataclass(frozen=True)
class ParsedModel:
    name: str
    doc: dict
    datasets: dict[str, ParsedDataset]
    metrics: dict[str, ParsedMetric]
    relationships: tuple[dict, ...]  # Ossie keys + ``cardinality``
    conformed: tuple[Any, ...] = field(default_factory=tuple)


def _names_unique(items: list, label: str, where: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise OssieError(f"{where}: duplicate {label} '{item}'")
        seen.add(item)


def _lower_field(entry: dict, siblings: dict[str, tuple[str, Any]], where: str) -> ParsedField:
    """A field expression references source columns only (spec §5.3.1): a
    reference to another field of the dataset refuses. A passthrough field
    (``status: status``) names its own source column and is never a chain."""
    name = entry["name"]
    sql = expression_sql(entry["expression"], f"{where} field '{name}'")
    tree = parse_sql(sql, f"{where} field '{name}'")
    refuse_relations(tree, f"{where} field '{name}'")
    for column in tree.find_all(exp.Column):
        if column.table:
            continue  # a qualified source reference (e.g. a source alias)
        other = siblings.get(column.name)
        if other is None or column.name == name:
            continue
        other_sql, _ = other
        if other_sql.strip() == column.name:
            continue  # passthrough field: the name IS the source column
        raise OssieError(
            f"{where} field '{name}': references field '{column.name}'; a field expression "
            "may reference source columns only (Ossie 0.3 name resolution) — write the "
            f"source expression of '{column.name}' inline"
        )
    dimension = entry.get("dimension")
    if isinstance(dimension, dict) and "is_time" in dimension:
        is_time = bool(dimension["is_time"])
    else:
        is_time = entry.get("datatype") in _TEMPORAL
    return ParsedField(name, sql, is_time, isinstance(dimension, dict))


def _lower_dataset_metric(
    entry: dict, dataset: ParsedDataset, field_trees: dict[str, Any], where: str
) -> ParsedMetric:
    name = entry["name"]
    context = f"{where} metric '{dataset.name}.{name}'"
    sql = expression_sql(entry["expression"], context)
    tree = parse_sql(sql, context)
    refuse_relations(tree, context)
    if agg_calls(tree):
        raise OssieError(f"{context}: AGG is only valid in a model-scoped metric")
    source_is_field = "source" in dataset.fields
    for column in list(tree.find_all(exp.Column)):
        if column.table:
            if column.table.lower() == "source" and not source_is_field:
                replacement = exp.column(column.name)
            else:
                raise OssieError(
                    f"{context}: reference '{column.table}.{column.name}' — a dataset-scoped "
                    "metric uses declared fields unqualified, or source columns as "
                    "`source.<column>`; other datasets belong in a model-scoped metric"
                )
        elif column.name in field_trees:
            replacement = _grouped(field_trees[column.name].copy())
        else:
            raise OssieError(
                f"{context}: '{column.name}' is not a declared field of dataset "
                f"'{dataset.name}'; write source columns as `source.{column.name}`"
            )
        if column is tree:
            tree = replacement
        else:
            column.replace(replacement)
    return ParsedMetric(
        key=f"{dataset.name}.{name}",
        name=name,
        scope="dataset",
        declared_on=dataset.name,
        owner=dataset.name,
        derived=False,
        expression=tree.sql(),
        deps=(),
        description=entry.get("description") or "",
    )


def _lower_model_metric(
    entry: dict,
    datasets: dict[str, ParsedDataset],
    dataset_metrics: dict[str, ParsedMetric],
    field_trees: dict[str, dict[str, Any]],
    where: str,
) -> ParsedMetric:
    name = entry["name"]
    context = f"{where} metric '{name}'"
    sql = expression_sql(entry["expression"], context)
    tree = parse_sql(sql, context)
    refuse_relations(tree, context)
    calls = agg_calls(tree)
    if calls:
        deps: list[str] = []
        for call in calls:
            dataset, metric = agg_target(call, context)
            key = f"{dataset}.{metric}"
            if key not in dataset_metrics:
                raise OssieError(
                    f"{context}: AGG({key}) does not name a dataset-scoped metric of this model"
                )
            if key not in deps:
                deps.append(key)
        inside = {id(node) for call in calls for node in call.find_all(exp.Column)}
        stray = [column for column in tree.find_all(exp.Column) if id(column) not in inside]
        if stray:
            ref = ".".join(part for part in (stray[0].table, stray[0].name) if part)
            raise OssieError(
                f"{context}: '{ref}' is outside AGG(...); a model-scoped metric is either "
                "composed only of AGG(dataset.metric) terms and arithmetic, or aggregates "
                "the fields of one dataset — declare the aggregate as a dataset-scoped "
                "metric and combine it with AGG"
            )
        return ParsedMetric(
            key=name,
            name=name,
            scope="model",
            declared_on=None,
            owner=None,
            derived=True,
            expression=sql,
            deps=tuple(deps),
            description=entry.get("description") or "",
        )
    owners: list[str] = []
    for column in tree.find_all(exp.Column):
        if not column.table or column.table not in datasets:
            ref = ".".join(part for part in (column.table, column.name) if part)
            raise OssieError(
                f"{context}: '{ref}' must be a `dataset.field` reference of a dataset in this "
                "model (model-scoped metrics cannot use bare names or source columns)"
            )
        if column.name not in datasets[column.table].fields:
            raise OssieError(
                f"{context}: '{column.table}.{column.name}' is not a declared field of dataset "
                f"'{column.table}' (source columns are not visible to model-scoped metrics)"
            )
        if column.table not in owners:
            owners.append(column.table)
    if len(owners) > 1:
        raise OssieError(
            f"{context}: aggregates fields of several datasets {sorted(owners)}; this revision "
            "refuses that — declare a dataset-scoped metric on each dataset and combine them "
            "with AGG, e.g. AGG(orders.revenue) / AGG(customers.customer_count)"
        )
    if not owners:
        if len(datasets) != 1:
            raise OssieError(
                f"{context}: references no dataset field and the model has {len(datasets)} "
                "datasets — declare it as a dataset-scoped metric"
            )
        owners = list(datasets)
    owner = owners[0]
    for column in list(tree.find_all(exp.Column)):
        replacement = _grouped(field_trees[owner][column.name].copy())
        if column is tree:
            tree = replacement
        else:
            column.replace(replacement)
    return ParsedMetric(
        key=name,
        name=name,
        scope="model",
        declared_on=None,
        owner=owner,
        derived=False,
        expression=tree.sql(),
        deps=(),
        description=entry.get("description") or "",
    )


def parse_model(doc: dict, file: str) -> ParsedModel:
    """Resolve one validated document: names, scoping, extension data and the
    lowered SQL of every metric. Raises :class:`OssieError` on any violation."""
    model_name = doc["name"]
    where = f"{file} model '{model_name}'"
    datasets_raw = doc["datasets"]
    _names_unique([entry["name"] for entry in datasets_raw], "dataset", where)
    extension_data(doc, "model", where)
    datasets: dict[str, ParsedDataset] = {}
    field_trees: dict[str, dict[str, Any]] = {}
    for entry in datasets_raw:
        dname = entry["name"]
        dwhere = f"{where} dataset '{dname}'"
        extension_data(entry, "dataset", dwhere)
        fields_raw = entry.get("fields") or []
        metrics_raw = entry.get("metrics") or []
        _names_unique(
            [f["name"] for f in fields_raw] + [m["name"] for m in metrics_raw],
            "field/metric name (one namespace per dataset)",
            dwhere,
        )
        siblings = {f["name"]: (expression_sql(f["expression"], dwhere), f) for f in fields_raw}
        fields: dict[str, ParsedField] = {}
        for f in fields_raw:
            extension_data(f, "field", f"{dwhere} field '{f['name']}'")
            fields[f["name"]] = _lower_field(f, siblings, dwhere)
        keys = [list(entry.get("primary_key") or [])] + [
            list(k) for k in entry.get("unique_keys") or []
        ]
        for key in keys:
            for column in key:
                if column not in fields:
                    raise OssieError(
                        f"{dwhere}: primary_key/unique_keys column '{column}' is not a declared "
                        "field; keys name fields, not source columns — declare a field that "
                        "exposes it"
                    )
        datasets[dname] = ParsedDataset(
            name=dname,
            source=entry["source"].strip(),
            primary_key=tuple(entry.get("primary_key") or ()),
            unique_keys=tuple(tuple(k) for k in entry.get("unique_keys") or ()),
            fields=fields,
        )
        field_trees[dname] = {
            name: _strip_qualifiers(parse_sql(f.sql, f"{dwhere} field '{name}'"))
            for name, f in fields.items()
        }
    metrics: dict[str, ParsedMetric] = {}
    for entry in datasets_raw:
        dataset = datasets[entry["name"]]
        for m in entry.get("metrics") or []:
            mwhere = f"{where} metric '{dataset.name}.{m['name']}'"
            data = extension_data(m, "metric", mwhere)
            parsed = _lower_dataset_metric(m, dataset, field_trees[dataset.name], where)
            metrics[parsed.key] = _with_extension(parsed, data, mwhere)
    dataset_metrics = dict(metrics)
    model_names = [m["name"] for m in doc.get("metrics") or []]
    _names_unique(model_names, "model-scoped metric", where)
    for m in doc.get("metrics") or []:
        mwhere = f"{where} metric '{m['name']}'"
        data = extension_data(m, "metric", mwhere)
        parsed = _lower_model_metric(m, datasets, dataset_metrics, field_trees, where)
        metrics[parsed.key] = _with_extension(parsed, data, mwhere)
    relationships: list[dict] = []
    for rel in doc.get("relationships") or []:
        data = extension_data(rel, "relationship", f"{where} relationship '{rel['name']}'")
        cardinality = data.get("cardinality", "many_to_one")
        if cardinality not in ("many_to_one", "one_to_one"):
            raise OssieError(
                f"{where} relationship '{rel['name']}': {VENDOR} cardinality must be "
                f"`one_to_one` (the default is many-to-one), got {cardinality!r}"
            )
        relationships.append(
            {
                **{k: rel[k] for k in rel if k != "nonportable_extensions"},
                "cardinality": cardinality,
            }
        )
    conformed = extension_data(doc, "model", where).get("conformed_dimensions")
    if conformed is not None and not isinstance(conformed, list):
        raise OssieError(f"{where}: conformed_dimensions must be a list of member declarations")
    return ParsedModel(
        name=model_name,
        doc=doc,
        datasets=datasets,
        metrics=metrics,
        relationships=tuple(relationships),
        conformed=tuple(conformed or ()),
    )


def _with_extension(metric: ParsedMetric, data: dict, where: str) -> ParsedMetric:
    fill = data.get("fill")
    if fill is not None and not isinstance(fill, (str, int, float, bool)):
        raise OssieError(
            f"{where}: 'fill' must be a scalar output value (applies to the output only, "
            "never a hidden ratio denominator)"
        )
    from dataclasses import replace

    return replace(metric, fill=fill, window=data.get("window"))


def metric_identity(model: str, key: str) -> str:
    """``<model>::<metric>`` or ``<model>::<dataset>.<metric>`` (spec §6.1)."""
    return f"{model}::{key}"


def split_identity(identity: str) -> tuple[str, str] | None:
    """``(model, key)`` of a full metric identity; ``None`` for a bare name."""
    model, sep, key = identity.partition("::")
    if not sep or not model or not key:
        return None
    return model, key
