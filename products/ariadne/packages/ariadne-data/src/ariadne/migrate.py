"""``ariadne migrate``: the one-time conversion from the retired Ossie
``0.2.0.dev0`` ``semantic_model`` envelope to Ossie ``0.3.0.dev0`` documents and
the new metric identities (spec 0039 §7).

:func:`convert_documents` is the pure conversion of one project's semantic
layer (model documents + optional ``graph.yml``): it returns the rewritten
files, the old-metric → new-key map, and a per-file report of constructs it
cannot convert mechanically. Nothing is written for an unconvertible project.
:func:`migrate_project` applies the result through the Git Authoring Proposal
route (``AuthoringProject``); it never edits an admitted snapshot in place.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml
from sqlglot import exp  # pyright: ignore[reportMissingImports]
from sqlglot.errors import SqlglotError  # pyright: ignore[reportMissingImports]

from ariadne import ossie

OLD_VERSION = "0.2.0.dev0"
ALREADY = "already Ossie 0.3"


class MigrationError(ValueError):
    """Unconvertible construct(s); the message is the per-file report."""


@dataclass
class Conversion:
    files: dict[str, str] = field(default_factory=dict)  # relative path -> new text
    metric_keys: dict[tuple[str, str], str] = field(default_factory=dict)  # (model, old) -> key
    notes: list[str] = field(default_factory=list)  # non-blocking (e.g. dropped DATUS hint)
    problems: dict[str, list[str]] = field(default_factory=dict)  # file -> reasons

    def problem(self, file: str, reason: str) -> None:
        self.problems.setdefault(file, []).append(reason)


class _Dumper(yaml.SafeDumper):
    """Multi-line strings (dataset sources) as reviewable literal blocks."""


def _str_representer(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def _dump(doc: dict) -> str:
    return yaml.dump(
        doc,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
        indent=2,
    )


def _old_sql(block: Any) -> tuple[str | None, list[dict]]:
    """``(primary SQL, remaining dialect entries)`` of an old expression block."""
    dialects = [d for d in (block or {}).get("dialects") or [] if isinstance(d, dict)]
    chosen = next((d for d in dialects if d.get("dialect") == "ANSI_SQL"), None)
    chosen = chosen or (dialects[0] if dialects else None)
    if chosen is None or not isinstance(chosen.get("expression"), str):
        return None, []
    rest = [
        {"dialect": d["dialect"], "expression": d["expression"]}
        for d in dialects
        if d is not chosen and isinstance(d.get("expression"), str) and d.get("dialect")
    ]
    return chosen["expression"], rest


def _expression(sql: str, rest: list[dict]) -> dict:
    out: dict = {"sql": sql}
    if rest:
        out["dialects"] = rest
    return out


def _parse(sql: str) -> Any:
    return sqlglot.parse_one(sql)


def _extensions(old: list | None, where: str, conv: Conversion, file: str) -> list[dict]:
    """``custom_extensions`` → ``nonportable_extensions``: DATUS hints are
    dropped (reported), every other entry keeps its vendor."""
    out: list[dict] = []
    for entry in old or []:
        if not isinstance(entry, dict):
            continue
        vendor = entry.get("vendor_name")
        if vendor == "DATUS":
            conv.notes.append(f"{file}: {where}: dropped the DATUS custom_extensions hint")
            continue
        data = entry.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {"value": data}
        if not isinstance(data, dict):
            data = {"value": data}
        out.append({"vendor_name": vendor, "data": data})
    return out


def _ariadne(data: dict) -> dict | None:
    data = {k: v for k, v in data.items() if v is not None}
    return {"vendor_name": ossie.VENDOR, "data": data} if data else None


def _expand_field(name: str, raw: dict[str, str], stack: tuple[str, ...], done: dict) -> str:
    """The SQL of field ``name`` over source columns: references to OTHER fields
    are substituted recursively; a reference to the field's own name is the
    source column of that name."""
    if name in done:
        return done[name]
    tree = _parse(raw[name])
    for column in list(tree.find_all(exp.Column)):
        ref = column.name
        if ref == name or ref not in raw:
            continue  # the source column of the same name
        if ref in stack:
            raise MigrationError(f"field reference cycle through {ref!r}")
        replacement = _parse(_expand_field(ref, raw, (*stack, name), done))
        if not isinstance(replacement, exp.Column):
            replacement = exp.Paren(this=replacement)
        if column is tree:
            tree = replacement
        else:
            column.replace(replacement)
    done[name] = tree.sql()
    return done[name]


class _Model:
    """One old model entry being converted."""

    def __init__(self, entry: dict, file: str, conv: Conversion):
        self.entry, self.file, self.conv = entry, file, conv
        self.target = file
        self.name: str = entry["name"]
        self.datasets: dict[str, dict] = {}
        self.field_sql: dict[str, dict[str, str]] = {}  # dataset -> field -> expanded SQL
        self.field_rest: dict[str, dict[str, list[dict]]] = {}
        self.new_fields: dict[str, dict[str, dict]] = {}  # dataset -> name -> new field

    def fail(self, reason: str) -> None:
        self.conv.problem(self.file, f"model {self.name!r}: {reason}")

    # -- fields -----------------------------------------------------------

    def expand_fields(self) -> None:
        """Field → field chains are expanded to source-column expressions."""
        for dataset in self.entry.get("datasets") or []:
            dname = dataset.get("name")
            self.datasets[dname] = dataset
            raw: dict[str, str] = {}
            rest: dict[str, list[dict]] = {}
            for f in dataset.get("fields") or []:
                sql, others = _old_sql(f.get("expression"))
                if sql is None:
                    self.fail(f"dataset {dname!r} field {f.get('name')!r} has no usable expression")
                    continue
                raw[f["name"]] = sql
                rest[f["name"]] = others
            expanded: dict[str, str] = {}
            for name in raw:
                try:
                    expanded[name] = _expand_field(name, raw, (), {})
                except (MigrationError, SqlglotError) as exc:
                    self.fail(f"dataset {dname!r} field {name!r}: {exc}")
            self.field_sql[dname] = expanded
            self.field_rest[dname] = rest

    def field_of(self, dataset: str, name: str) -> str:
        """The field exposing ``name``; a missing field is added, named after
        the source column (spec §7.2)."""
        fields = self.field_sql.setdefault(dataset, {})
        if name not in fields:
            fields[name] = name
            self.field_rest.setdefault(dataset, {})[name] = []
        return name

    # -- metrics ----------------------------------------------------------

    def convert_metrics(self) -> tuple[dict[str, list[dict]], list[dict]]:
        """``(dataset -> dataset-scoped metrics, model-scoped metrics)``."""
        old = {m["name"]: m for m in self.entry.get("metrics") or [] if isinstance(m, dict)}
        sql_of: dict[str, str] = {}
        rest_of: dict[str, list[dict]] = {}
        for name, m in old.items():
            sql, rest = _old_sql(m.get("expression"))
            if sql is None:
                self.fail(f"metric {name!r} has no usable expression")
                continue
            sql_of[name], rest_of[name] = sql, rest
        trees = {n: _parse(s) for n, s in sql_of.items()}
        derived = {
            n for n, t in trees.items() if {c.name for c in t.find_all(exp.Column)} & set(old)
        }
        names = set(old)
        owner: dict[str, str] = {}
        for name in old:
            if name in derived or name not in sql_of:
                continue
            explicit = old[name].get("dataset")
            referenced: set[str] = set()
            for column in trees[name].find_all(exp.Column):
                if column.table in self.datasets:
                    referenced.add(column.table)
                    continue
                homes = [d for d in self.datasets if column.name in self.field_sql.get(d, {})]
                if len(homes) == 1:
                    referenced.add(homes[0])
                elif len(homes) > 1:
                    self.fail(
                        f"metric {name!r}: field {column.name!r} exists on several datasets "
                        f"{sorted(homes)}"
                    )
            if explicit:
                owner[name] = explicit
            elif len(referenced) == 1:
                owner[name] = next(iter(referenced))
            elif not referenced and len(self.datasets) == 1:
                owner[name] = next(iter(self.datasets))
            else:
                self.fail(
                    f"metric {name!r} aggregates raw columns of several datasets "
                    f"{sorted(referenced)} or of none; Ossie 0.3 refuses a multi-dataset raw "
                    "aggregate — split it into dataset-scoped metrics combined with AGG"
                )
        by_dataset: dict[str, list[dict]] = {d: [] for d in self.datasets}
        for name, dataset in owner.items():
            tree = trees[name]
            for column in list(tree.find_all(exp.Column)):
                table = column.table
                if table and table not in self.datasets and table != dataset:
                    pass  # an unknown qualifier binds to the owning dataset (old renderer)
                ref = column.name
                if ref in self.field_sql.get(dataset, {}):
                    new = exp.column(ref)
                else:
                    new = exp.column(ref, table="source")
                if column is tree:
                    tree = new
                else:
                    column.replace(new)
            entry = {"name": name, "expression": _expression(tree.sql(), rest_of[name])}
            self._carry(entry, old[name])
            by_dataset[dataset].append(entry)
            self.conv.metric_keys[(self.name, name)] = f"{dataset}.{name}"
        model_scoped: list[dict] = []
        for name in sorted(derived):
            tree = self._derived(name, trees, owner, names, set())
            if tree is None:
                continue
            entry = {"name": name, "expression": _expression(tree.sql(), rest_of[name])}
            self._carry(entry, old[name])
            model_scoped.append(entry)
            self.conv.metric_keys[(self.name, name)] = name
        return by_dataset, model_scoped

    def _derived(self, name: str, trees: dict, owner: dict, names: set, stack: set) -> Any:
        """A derived metric as an ``AGG(dataset.metric)`` composition."""
        if name in stack:
            self.fail(f"metric dependency cycle through {name!r}")
            return None
        tree = trees[name].copy()
        for column in list(tree.find_all(exp.Column)):
            ref = column.name
            if ref not in names:
                self.fail(
                    f"derived metric {name!r} mixes the bare field {ref!r} with metric "
                    "references; Ossie 0.3 allows only AGG(dataset.metric) terms"
                )
                return None
            if ref in owner:
                replacement = exp.Agg(this=exp.column(ref, table=owner[ref]))
            else:  # another derived metric: expand it inline
                inner = self._derived(ref, trees, owner, names, {*stack, name})
                if inner is None:
                    return None
                replacement = exp.Paren(this=inner)
            if column is tree:
                tree = replacement
            else:
                column.replace(replacement)
        return tree

    def _carry(self, entry: dict, old: dict) -> None:
        if old.get("description"):
            entry["description"] = old["description"]
        extensions = _extensions(
            old.get("custom_extensions"), f"metric {old['name']!r}", self.conv, self.file
        )
        data = {"fill": old.get("fill"), "window": old.get("window")}
        ariadne = _ariadne(data)
        if ariadne:
            extensions.append(ariadne)
        if extensions:
            entry["nonportable_extensions"] = extensions

    # -- structure --------------------------------------------------------

    def relationship(self, old: dict, where: str) -> dict | None:
        out: dict = {"name": old.get("name")}
        try:
            from_ds, to_ds = old["from_dataset"], old["to_dataset"]
            out["from"], out["to"] = from_ds, to_ds
            out["from_columns"] = [self.field_of(from_ds, c) for c in old["from_fields"]]
            out["to_columns"] = [self.field_of(to_ds, c) for c in old["to_fields"]]
        except (KeyError, TypeError):
            self.fail(f"{where}: relationship {old.get('name')!r} is not convertible")
            return None
        if old.get("cardinality") == "one_to_one":
            out["nonportable_extensions"] = [_ariadne({"cardinality": "one_to_one"})]
        return out

    def document(self) -> dict | None:
        self.expand_fields()
        by_dataset, model_scoped = self.convert_metrics()
        for dname, dataset in self.datasets.items():
            for key in dataset.get("primary_key") or []:
                self.field_of(dname, key)
        relationships = [
            r
            for r in (self.relationship(r, "inline") for r in self.entry.get("relationships") or [])
            if r
        ]
        datasets = []
        for dname, dataset in self.datasets.items():
            old_fields = {f.get("name"): f for f in dataset.get("fields") or []}
            fields = []
            for fname, sql in self.field_sql.get(dname, {}).items():
                old = old_fields.get(fname) or {}
                new: dict = {
                    "name": fname,
                    "expression": _expression(sql, self.field_rest.get(dname, {}).get(fname, [])),
                }
                if isinstance(old.get("dimension"), dict):
                    new["dimension"] = old["dimension"]
                for key in ("description", "label", "datatype", "ai_context"):
                    if old.get(key) is not None:
                        new[key] = old[key]
                ext = _extensions(
                    old.get("custom_extensions"), f"field {fname!r}", self.conv, self.file
                )
                if ext:
                    new["nonportable_extensions"] = ext
                fields.append(new)
            entry: dict = {"name": dname, "source": dataset.get("source")}
            if dataset.get("description"):
                entry["description"] = dataset["description"]
            if dataset.get("primary_key"):
                entry["primary_key"] = list(dataset["primary_key"])
            if dataset.get("unique_keys"):
                entry["unique_keys"] = dataset["unique_keys"]
            if fields:
                entry["fields"] = fields
            if by_dataset.get(dname):
                entry["metrics"] = by_dataset[dname]
            ext = _extensions(
                dataset.get("custom_extensions"), f"dataset {dname!r}", self.conv, self.file
            )
            if ext:
                entry["nonportable_extensions"] = ext
            datasets.append(entry)
        doc: dict = {"version": ossie.OSSIE_VERSION, "name": self.name}
        if self.entry.get("description"):
            doc["description"] = self.entry["description"]
        doc["datasets"] = datasets
        if relationships:
            doc["relationships"] = relationships
        if model_scoped:
            doc["metrics"] = model_scoped
        extensions = _extensions(self.entry.get("custom_extensions"), "model", self.conv, self.file)
        ariadne = _ariadne({"conformed_dimensions": self.entry.get("conformed_dimensions")})
        if ariadne:
            extensions.append(ariadne)
        if extensions:
            doc["nonportable_extensions"] = extensions
        return doc


def _is_old(doc: Any) -> bool:
    return isinstance(doc, dict) and "semantic_model" in doc


def is_migrated(semantic_dir: Path) -> bool:
    """True when every model document is already Ossie 0.3 (and at least one exists)."""
    models = Path(semantic_dir) / "models"
    files = sorted((*models.glob("*.yml"), *models.glob("*.yaml"))) if models.is_dir() else []
    if not files:
        return False
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            return False
        if _is_old(doc) or not isinstance(doc, dict) or doc.get("version") != ossie.OSSIE_VERSION:
            return False
    return True


def convert_documents(files: dict[str, str]) -> Conversion:
    """Convert ``{relative path: text}`` of one semantic layer
    (``semantic_layer/models/*.yml`` and ``semantic_layer/graph.yml``). Paths
    keep their names; a multi-model file is split (the first model keeps the
    file, the others become ``<model>.yml``)."""
    conv = Conversion()
    models: list[_Model] = []
    graph_text: str | None = None
    taken = {Path(p).name for p in files}
    for path, text in sorted(files.items()):
        name = Path(path).name
        if name == "graph.yml":
            graph_text = text
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            conv.problem(name, f"not valid YAML: {exc}")
            continue
        if not _is_old(doc):
            conv.problem(name, "not a 0.2.0.dev0 `semantic_model` envelope")
            continue
        entries = doc.get("semantic_model")
        if not isinstance(entries, list) or not entries:
            conv.problem(name, "no semantic_model entries")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                conv.problem(name, f"semantic_model entry {index} has no name")
                continue
            if index == 0:
                target = path
            else:
                target = str(Path(path).with_name(f"{entry['name']}.yml"))
                if Path(target).name in taken:
                    conv.problem(name, f"cannot split model {entry['name']!r}: {target} exists")
                    continue
                taken.add(Path(target).name)
            model = _Model(entry, name, conv)
            model.target = target
            models.append(model)
    docs: dict[str, dict] = {}
    for model in models:
        try:
            doc = model.document()
        except SqlglotError as exc:
            conv.problem(model.file, f"model {model.name!r}: {type(exc).__name__}: {exc}")
            continue
        if doc is not None:
            docs[model.target] = doc
    if graph_text is not None:
        graph = _convert_graph(graph_text, models, conv)
        if graph is not None:
            conv.files[f"{Path(next(iter(files))).parent.parent}/graph.yml"] = graph
    if conv.problems:
        conv.files = {}
        return conv
    for model in models:
        doc = docs[model.target]
        # the converted documents must satisfy the pinned schema and the
        # strict name-resolution rules, else the conversion is incomplete
        try:
            ossie.parse_model(ossie.validate_document(doc, Path(model.target).name), model.target)
        except ossie.OssieError as exc:
            conv.problem(model.file, str(exc))
        conv.files[model.target] = _dump(doc)
    if conv.problems:
        conv.files = {}
    return conv


def _convert_graph(text: str, models: list[_Model], conv: Conversion) -> str | None:
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        conv.problem("graph.yml", f"not valid YAML: {exc}")
        return None
    owners = {d: m for m in models for d in m.datasets}
    out: dict = {k: v for k, v in doc.items() if k != "relationships"}
    relationships = []
    for old in doc.get("relationships") or []:
        src, dst = owners.get(old.get("from_dataset")), owners.get(old.get("to_dataset"))
        if src is None or dst is None:
            conv.problem("graph.yml", f"relationship {old.get('name')!r} names an unknown dataset")
            continue
        new: dict = {"name": old.get("name")}
        new["from"], new["to"] = old["from_dataset"], old["to_dataset"]
        new["from_columns"] = [src.field_of(old["from_dataset"], c) for c in old["from_fields"]]
        new["to_columns"] = [dst.field_of(old["to_dataset"], c) for c in old["to_fields"]]
        if old.get("cardinality") == "one_to_one":
            new["cardinality"] = "one_to_one"
        relationships.append(new)
    if relationships:
        out["relationships"] = relationships
    return _dump(out)


def rewrite_identities(text: str, conv: Conversion) -> str:
    """The new metric identities in one Lumio page or ``context_integration.yaml``:
    ``model::metric`` tokens (Policy Binding subjects and definitions,
    Computation ``core_ref``) and ``metric_ref`` pairs."""
    for (model, old), key in conv.metric_keys.items():
        if key == old:
            continue
        text = re.sub(rf"\b{re.escape(model)}::{re.escape(old)}(?![\w.])", f"{model}::{key}", text)
        pattern = (
            rf"(metric_ref:\s*\n(\s+)model:\s*['\"]?{re.escape(model)}['\"]?\s*\n"
            rf"\2metric:\s*)(['\"]?){re.escape(old)}\3(?=\s*\n)"
        )
        text = re.sub(pattern, rf"\g<1>\g<3>{key}\g<3>", text)
    return text


def migrate_project(project: str | Path) -> dict:
    """Open an Authoring Proposal holding the rewritten artifacts.

    Returns ``{"status": "already", ...}`` when the project is migrated,
    ``{"status": "proposal", "proposal": ..., "revision": ..., "files": [...]}``
    after writing, and raises :class:`MigrationError` (project unchanged) with
    the per-file report when a construct cannot be converted."""
    from ariadne.authoring import AuthoringProject  # local: authoring imports a lot

    root = Path(project)
    semantic = root / "semantic_layer"
    models = semantic / "models"
    if is_migrated(semantic):
        return {"status": "already", "message": ALREADY}
    sources: dict[str, str] = {}
    for path in sorted((*models.glob("*.yml"), *models.glob("*.yaml"))) if models.is_dir() else []:
        sources[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    if (semantic / "graph.yml").is_file():
        sources["semantic_layer/graph.yml"] = (semantic / "graph.yml").read_text(encoding="utf-8")
    if not sources:
        raise MigrationError(f"{root}: no semantic_layer/models documents to migrate")
    conv = convert_documents(sources)
    if conv.problems:
        report = "; ".join(f"{f}: {'; '.join(r)}" for f, r in sorted(conv.problems.items()))
        raise MigrationError(f"project left unchanged — unconvertible construct(s): {report}")
    pages: dict[str, str] = {}
    for base in ("knowledge", "context_integration.yaml"):
        target = root / base
        for path in [target] if target.is_file() else sorted(target.rglob("*.md")):
            old = path.read_text(encoding="utf-8")
            new = rewrite_identities(old, conv)
            if new != old:
                pages[str(path.relative_to(root))] = new
    api = AuthoringProject(root)
    started = api.start_proposal()
    revision = started["candidate_revision"]
    written: list[str] = []
    for rel, text in sorted(conv.files.items()):
        if rel == "semantic_layer/graph.yml":
            edit = {"kind": "graph", "content": text}
        else:
            edit = {"kind": "model", "name": Path(rel).stem, "content": text}
        result = api.edit_proposal(started["proposal"], revision, edit)
        revision = result["revision"]
        written.append(rel)
    batch = [
        {"path": rel.removeprefix("knowledge/"), "content": t}
        for rel, t in pages.items()
        if rel.startswith("knowledge/")
    ]
    if batch:
        revision = api.edit_pages_batch(started["proposal"], revision, batch)["revision"]
        written.extend(f"knowledge/{p['path']}" for p in batch)
    if "context_integration.yaml" in pages:
        result = api.edit_proposal(
            started["proposal"],
            revision,
            {"kind": "context_integration", "content": pages["context_integration.yaml"]},
        )
        revision = result["revision"]
        written.append("context_integration.yaml")
    return {
        "status": "proposal",
        "proposal": started["proposal"],
        "revision": revision,
        "files": written,
        "notes": conv.notes,
    }
