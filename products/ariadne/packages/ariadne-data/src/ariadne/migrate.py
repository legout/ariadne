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
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml
from sqlglot import exp  # pyright: ignore[reportMissingImports]
from sqlglot.errors import SqlglotError  # pyright: ignore[reportMissingImports]

from ariadne import ossie  # pyright: ignore[reportMissingImports] — resolver drift

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
                others = sorted(referenced - {explicit})
                if others:
                    self.fail(
                        f"metric {name!r} is owned by dataset {explicit!r} but references "
                        f"{others}; Ossie 0.3 refuses a multi-dataset raw aggregate — split it "
                        "into dataset-scoped metrics combined with AGG"
                    )
                    continue
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


def is_migrated(sources: dict[str, str]) -> bool:
    """True when every model document of ``{path: text}`` is already Ossie 0.3
    (and at least one exists)."""
    docs = [
        text
        for path, text in sources.items()
        if Path(path).parent.name == "models" and Path(path).suffix in (".yml", ".yaml")
    ]
    if not docs:
        return False
    for text in docs:
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            return False
        if _is_old(doc) or not isinstance(doc, dict) or doc.get("version") != ossie.OSSIE_VERSION:
            return False
    return True


def convert_documents(files: dict[str, str]) -> Conversion:
    """Convert ``{relative path: text}`` of one semantic layer
    (``semantic_layer/models/*.yml`` and ``semantic_layer/graph.yml``). Paths
    keep their exact names and suffixes; a multi-model file is split (the first
    model keeps the file, the others become ``<model><suffix>`` where nothing
    collides, else the file is reported)."""
    conv = Conversion()
    models: list[_Model] = []
    graph_text: str | None = None
    taken = {Path(p).name for p in files}  # exact names; a stem collides under either suffix
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
                suffix = Path(path).suffix
                target = str(Path(path).with_name(f"{entry['name']}{suffix}"))
                if any(f"{entry['name']}{s}" in taken for s in (".yml", ".yaml")):
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
    """The selector with every Policy Binding metric identity mapped exactly
    (``subject.identity``, ``enforcement.definition``/``dependencies``) from the old
    ``model::metric`` to the new ``model::key``; parsed, never text-replaced. Returns
    ``text`` unchanged when nothing maps."""
    mapping = {f"{m}::{old}": f"{m}::{key}" for (m, old), key in conv.metric_keys.items()}
    doc = yaml.safe_load(text)
    bindings = (doc.get("policy_bindings") or {}).get("bindings") if isinstance(doc, dict) else None
    changed = False

    def remap(holder: dict, field_name: str) -> None:
        nonlocal changed
        value = holder.get(field_name)
        if isinstance(value, str) and mapping.get(value, value) != value:
            holder[field_name], changed = mapping[value], True

    for binding in bindings or []:
        if not isinstance(binding, dict):
            continue
        if isinstance(binding.get("subject"), dict):
            remap(binding["subject"], "identity")
        enforcement = binding.get("enforcement")
        if isinstance(enforcement, dict):
            remap(enforcement, "definition")
            deps = enforcement.get("dependencies")
            if isinstance(deps, list):
                for i, dep in enumerate(deps):
                    if mapping.get(dep, dep) != dep:
                        deps[i], changed = mapping[dep], True
    return _dump(doc) if changed else text


def _read_revision(root: Path, revision: str) -> dict[str, str]:
    """The migratable artifacts of ``revision``: model documents, ``graph.yml``,
    knowledge pages and the selector — read from Git, never the checkout."""
    from ariadne import proposals  # pyright: ignore[reportMissingImports] — resolver drift

    listing = proposals._git(
        [
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            revision,
            "--",
            "semantic_layer",
            "knowledge",
            "context_integration.yaml",
        ],  # fmt: skip
        root,
    ).stdout
    out: dict[str, str] = {}
    for rel in filter(None, listing.split("\0")):
        pure = Path(rel)
        wanted = (
            # the normal loader reads direct children of semantic_layer/models only
            (
                len(pure.parts) == 3
                and pure.parts[:2] == ("semantic_layer", "models")
                and pure.suffix in (".yml", ".yaml")
            )
            or rel == "semantic_layer/graph.yml"
            or (pure.parts[0] == "knowledge" and pure.suffix == ".md")
            or rel == "context_integration.yaml"
        )
        blob = proposals._read_blob(root, revision, rel) if wanted else None
        if blob is not None:
            out[rel] = blob.decode("utf-8")
    return out


def _page(text: str, rel: str):
    """``(frontmatter, body)`` of a Lumio page through the SDK parser; ``None``
    for a file the SDK does not read as a page."""
    from lumio_wiki import parse_frontmatter  # pyright: ignore[reportMissingImports]
    from lumio_wiki.knowledge_base import FrontmatterError  # pyright: ignore[reportMissingImports]

    try:
        meta, body, _line = parse_frontmatter(text, Path(rel))
    except FrontmatterError:
        return None
    return meta, body


def _render_page(meta: dict, body: str) -> str:
    """The page with changed frontmatter, written like the other core page
    writers (``yaml.safe_dump``); the body is carried over byte for byte."""
    front = yaml.safe_dump(
        meta, default_flow_style=False, sort_keys=False, allow_unicode=True
    ).strip()
    return f"---\n{front}\n---{body}"


def _example_problems(rel: str, meta: dict, identities: dict[str, tuple[str, str]]) -> list[str]:
    """An Answer Example is historical provenance and is never rewritten: its
    recorded metric name must still resolve (spec 0039 §6.4) against the
    migrated metric set — exactly or by a unique short name."""
    native = (meta.get("ariadne_profile") or {}).get("native") or {}
    method = native.get("method")
    if not isinstance(method, dict) or method.get("operation") != "get_metric":
        return []
    name = (method.get("arguments") or {}).get("name")
    if not isinstance(name, str):
        return []
    if "::" in name:
        return [] if name in identities else [f"{rel}: recorded metric {name!r} no longer exists"]
    matches = sorted(i for i, (short, key) in identities.items() if name in (short, key))
    if len(matches) == 1:
        return []
    if matches:
        return [f"{rel}: recorded metric name {name!r} becomes ambiguous: {', '.join(matches)}"]
    return [f"{rel}: recorded metric name {name!r} no longer resolves"]


def _context_rewrites(
    files: dict[str, str], conv: Conversion, admitted: bool
) -> tuple[dict[str, str], list[str]]:
    """Preflight of the Context half: every page rewrite and generated-page
    deletion, with every problem collected into ``conv`` (nothing is written)."""
    from ariadne import context  # pyright: ignore[reportMissingImports] — resolver drift

    writes: dict[str, str] = {}
    deletes: list[str] = []
    attested: list[tuple[str, dict, str, str, str, str]] = []
    cited: dict[str, list[str]] = {}  # Example page -> pages it cites
    identities = {f"{m}::{k}": (old, k) for (m, old), k in conv.metric_keys.items()}
    for rel, text in sorted(files.items()):
        if not (rel.startswith("knowledge/") and rel.endswith(".md")):
            continue
        parsed = _page(text, rel)
        if parsed is None:
            continue
        meta, body = parsed
        profile = meta.get("ariadne_profile")
        if not isinstance(profile, dict):
            continue
        kind = profile.get("kind")
        if kind == "answer_example":
            for reason in _example_problems(rel, meta, identities):
                conv.problem(rel, reason)
            ex_native = profile.get("native")
            cited[rel] = [
                f"knowledge/{c['path']}"
                for c in (ex_native.get("citations") if isinstance(ex_native, dict) else None) or []
                if isinstance(c, dict) and isinstance(c.get("path"), str)
            ]
        elif kind == "metric" and isinstance(profile.get("metric_ref"), dict):
            ref = profile["metric_ref"]
            new = conv.metric_keys.get((ref.get("model"), ref.get("metric")))
            if new is not None and new != ref["metric"]:
                ref["metric"] = new
                writes[rel] = _render_page(meta, body)
        elif kind == "computation" and isinstance(profile.get("core_ref"), dict):
            core = profile["core_ref"]
            model, sep, old = str(core.get("id")).partition("::")
            key = conv.metric_keys.get((model, old)) if sep else None
            if core.get("kind") != "semantic" or key is None:
                continue
            raw_native = profile.get("native")
            native: dict = raw_native if isinstance(raw_native, dict) else {}
            claims = "attester" in native or native.get("attestation") not in (None, "pending")
            generated = any(
                isinstance(s, dict) and s.get("id") == f"model-{model}"
                for s in native.get("sources") or []
            )
            if generated:
                if key != old:
                    deletes.append(rel)  # regenerated under the new identity, whatever it retained
            elif claims:
                attested.append((rel, meta, body, model, old, key))
            elif key != old:
                core["id"] = f"{model}::{key}"
                writes[rel] = _render_page(meta, body)
    if attested:
        with tempfile.TemporaryDirectory(prefix="ariadne-migrate-") as tmp:
            for rel, text in conv.files.items():
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / rel).write_text(text, encoding="utf-8")
            index, _ok = context._model_index(Path(tmp))
            sanctioned = context.sanctioned_sql(Path(tmp), index)
        for rel, meta, body, model, old, key in attested:
            identity = f"{model}::{key}"
            meta["ariadne_profile"]["core_ref"]["id"] = identity
            page = _render_page(meta, body)
            sql = sanctioned.get(identity)
            if identity not in index or sql is None:
                refusal = (
                    "the metric no longer resolves"
                    if identity not in index
                    else "no sanctioned SQL can be computed for it (a cross-fact composition)"
                )
            else:
                state, refusal = context._native_computation_state(page, key, index[identity], sql)
                if refusal is None and state == "stale":
                    refusal = "sanctioned SQL differs"
            if refusal is not None:
                conv.problem(
                    rel,
                    f"attested Computation page for {model}::{old} cannot be proven against "
                    f"{identity} under Ossie 0.3 — it needs re-attestation ({refusal})",
                )
            elif key != old:
                writes[rel] = page
    if not admitted:
        # an admitted baseline skips the historical citation check for unchanged
        # Examples; without one, a citation of a rewritten page can never verify
        for rel, paths in cited.items():
            changed = sorted(p for p in paths if p in writes or p in deletes)
            if changed:
                conv.problem(
                    rel,
                    f"cites {changed}, which this migration rewrites, and no admitted baseline "
                    "exists to keep the Example's historical citation check from running",
                )
    return writes, deletes


def migrate_project(project: str | Path) -> dict:
    """Convert a project atomically into ONE Authoring Proposal revision.

    Everything is read from the pinned revision the proposal opens from (the
    admitted commit when one exists, else ``HEAD``) and fully preflighted —
    models, graph, metric pages, Computation pages, the selector and Answer
    Examples. Only when no problem remains is the proposal started and one
    commit written; any problem raises :class:`MigrationError` with the
    per-file report and writes nothing. Returns ``{"status": "already"}`` for
    a migrated revision, else ``{"status": "proposal", ...}``. Admission stays a
    separate, human-only step."""
    from ariadne import (  # pyright: ignore[reportMissingImports] — resolver drift
        admission,
        proposals,
    )

    root = Path(project).resolve()
    current = admission.load_current(root)
    revision = current["commit"] if current is not None else proposals._current_head(root)
    if revision is None:
        raise MigrationError(f"{root}: no commits to migrate from")
    files = _read_revision(root, revision)
    sources = {r: t for r, t in files.items() if r.startswith("semantic_layer/")}
    if is_migrated(sources):
        return {"status": "already", "message": ALREADY}
    if not sources:
        raise MigrationError(f"{root}: no semantic_layer/models documents to migrate")
    conv = convert_documents(sources)
    writes: dict[str, str] = dict(conv.files)
    deletes: list[str] = []
    if not conv.problems:
        pages, deletes = _context_rewrites(files, conv, current is not None)
        writes.update(pages)
        selector = files.get("context_integration.yaml")
        if selector is not None and rewrite_identities(selector, conv) != selector:
            writes["context_integration.yaml"] = rewrite_identities(selector, conv)
    if conv.problems:
        report = "; ".join(f"{f}: {'; '.join(r)}" for f, r in sorted(conv.problems.items()))
        raise MigrationError(f"project left unchanged — unconvertible construct(s): {report}")
    # the complete write and delete set is verified before any proposal state exists
    proposals.check_migration_set(writes, tuple(deletes))
    started = proposals.start_proposal(root, base_revision=revision)
    result = proposals.migration_commit(
        root, started["proposal"], started["candidate_revision"], writes, tuple(deletes)
    )
    return {
        "status": "proposal",
        "proposal": started["proposal"],
        "revision": result["revision"],
        "files": sorted(writes),
        "deleted": sorted(deletes),
        "notes": conv.notes,
    }
