"""Deterministic validation of staged OSI models (ticket #4; ADR-0008 since rev 7).

``validate(staging_dir)`` validates every model under
``<staging>/semantic_layer/models/`` through the own sqlglot compiler
(:mod:`ariadne.render`, ADR-0008): an envelope schema check (required fields:
version, model name, dataset name/source/fields, metric name/expression), then
a full ``render()`` of every model — a malformed envelope or unrenderable
construct fails with the compiler's verbatim reason. There is no datus import
anywhere in the pipeline.

Multi-fact (issue #26, spec rev 1): every staging tree first normalizes through
:func:`ariadne.semantic_graph.load_graph` — both OSI layouts (one domain
multi-dataset file, or per-source files plus ``semantic_layer/graph.yml``)
become one validated graph, and graph failures (duplicate metrics, ambiguous
``COUNT(*)`` ownership, contradictory edges, unsupported ``requires`` keys)
fail structurally BEFORE any SELECT is compiled. Domain models compile
per-owning-dataset through the same single-dataset ``render()``. The result
carries a digest-bound :class:`ValidationReport` (consumed model/graph/context
bytes, registry identity, validator version, distinct check outcomes); live
relationship-target audits are task 2 (#27) and always report not-run.

With ``db_path`` (``--db``, passed by the author loop), the rendered SQL also
passes an EXPLAIN bind-check on a read-only DuckDB attach of the SQLite database
(a column missing from the source only surfaces at bind time — nothing executes),
and then the post-compile GRAIN AUDIT
runs per ADR-0006 §5 (project/adr/0006-grain-governance-multi-cardinality-joins.md):
Assertion 1 — the declared ``primary_key`` is unique over the compiled dataset
source; Assertion 2 — parent aggregate invariance: for dataset sources containing
JOINs, additive parent-table columns must sum identically over the raw parent table
and the joined source (fan-out inflation -> fail, remediation names the ADR-0006
rubric patterns). mvp-5 round 2 (owner decision: structural guard reuse): the
audit's AUTHORITATIVE gate is the facade's shared structural guard
(:func:`ariadne.grain.check_grain_preserving`) applied to every authored dataset
source — any join ANYWHERE in the tree (CTEs included) whose ON key is not unique
on the joined side fails the audit; the sum-invariance assertion stays as
secondary defense in depth (a tracer bypass is no longer a blocker). The audit
executes the authored source SQL on a read-only DuckDB attach of the SQLite
database — the sanctioned staged-authoring path.
Without ``db_path``, validate checks schema and renderability only.

CLI::

    python -m ariadne.validate staging/               # exit 0 = compiles
    python -m ariadne.validate staging/ --db DB   # + bind check + grain audit
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

from ariadne.grain import check_grain_preserving
from ariadne.render import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    RenderError,
    _dialect_expression,
    _parse,
    render,
)
from ariadne.semantic_graph import (  # pyright: ignore[reportMissingImports] — drift
    GraphError,
    SemanticGraph,
    load_graph,
)
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    build_connection,
    default_registry_path,
    load_registry,
)

# sqlglot exposes its AST node module lazily (sqlglot.exp is a real module but not
# statically exported), so resolve it at runtime like serve.py does.
_exp = getattr(sqlglot, "exp")

_GRAIN_ADR = "project/adr/0006-grain-governance-multi-cardinality-joins.md"
_ADR_TOLERANCE = 1e-9

# The validator's own identity in the digest-bound report: bump when the checks
# performed change (spec rev 1, "Validation, admission, and labels").
VALIDATOR_VERSION = "ariadne-validate/2"  # 2: normalized graph + report (issue #26)


@dataclass(frozen=True)
class CheckOutcome:
    """One named check and its outcome: passed / failed / not-run."""

    name: str
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """Digest-bound validation report (spec rev 1, "Validation, admission, and
    labels"): the consumed model/graph/context bytes, source-registry identity,
    validator version and the distinct check outcomes. A compile-only report is
    visibly partial, never a full pass."""

    digest: str
    scope: str
    validator_version: str
    registry_digest: str | None
    registry_label: str | None
    files: tuple[str, ...]
    checks: tuple[CheckOutcome, ...]

    def outcome(self, name: str) -> str | None:
        """The outcome recorded for one named check, if present."""
        return next((check.outcome for check in self.checks if check.name == name), None)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    report: ValidationReport | None = None


def _wrap_source(source: str) -> str:
    """The dataset source as a FROM-able subquery (a bare table ref needs a SELECT)."""
    if re.match(r"(?is)\s*(select|with)\b", source):
        return f"({source})"
    return f"(SELECT * FROM {source})"


def _models_dir(staging_dir: str | Path) -> Path:
    return Path(staging_dir) / "semantic_layer" / "models"


def _model_entries(staging_dir: str | Path) -> list[tuple[str, dict]]:
    """(model_name, single-entry envelope) for every semantic_model entry across
    the staged YAML files. A file without a semantic_model list is a load error
    surfaced by the caller."""
    entries: list[tuple[str, dict]] = []
    for path in sorted(_models_dir(staging_dir).glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        models = doc.get("semantic_model")
        if not isinstance(models, list) or not models:
            raise ValueError(f"{path.name}: no semantic_model entries")
        for model in models:
            name = model.get("name") if isinstance(model, dict) else None
            entries.append(
                (
                    str(name) if name else path.stem,
                    {"version": doc.get("version"), "semantic_model": [model]},
                )
            )
    return entries


def _schema_errors(envelope: dict, require_metrics: bool = True) -> list[str]:
    """Envelope required fields: version, model name, and per dataset name, source,
    fields (name + expression dialects) and per metric name + expression dialects.
    primary_key presence is governed by the grain audit stage (ADR-0006 rule of
    single declared grain — it owns that error's contract, incl. compile-only
    validate passing pk-less models). ``require_metrics=False`` checks a
    dataset that owns no metrics (its structure is validated regardless —
    issue #26 fix pass F6)."""
    model = envelope["semantic_model"][0]
    if not isinstance(model, dict):
        return ["semantic_model entry is not a mapping"]
    name = model.get("name")
    errors: list[str] = []
    if not isinstance(envelope.get("version"), str) or not envelope["version"].strip():
        errors.append(f"model {name!r}: missing envelope 'version'")
    if not isinstance(name, str) or not name.strip():
        errors.append("semantic_model entry without a 'name'")
        name = "?"
    metrics = model.get("metrics")
    if require_metrics and (not isinstance(metrics, list) or not metrics):
        errors.append(f"model '{name}': no metrics")
    for metric in metrics or []:
        mname = metric.get("name") if isinstance(metric, dict) else None
        block = metric.get("expression") or {} if isinstance(metric, dict) else {}
        dialects = block.get("dialects") if isinstance(block, dict) else None
        if not mname or not isinstance(dialects, list) or not dialects:
            errors.append(
                f"model '{name}' metric {mname!r}: name and non-empty expression "
                "dialects are required"
            )
    datasets = model.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        errors.append(f"model '{name}': no datasets")
        return errors
    for dataset in datasets:
        if not isinstance(dataset, dict):
            errors.append(f"model '{name}': dataset entry is not a mapping")
            continue
        dname = dataset.get("name") or "?"
        source = dataset.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"model '{name}' dataset '{dname}': missing source")
        pk = dataset.get("primary_key")
        if pk is not None and (
            not isinstance(pk, list) or not all(isinstance(key, str) for key in pk)
        ):
            errors.append(
                f"model '{name}' dataset '{dname}': primary_key must be a list of field names"
            )
        for field_spec in dataset.get("fields") or []:
            fname = field_spec.get("name") if isinstance(field_spec, dict) else None
            block = field_spec.get("expression") or {} if isinstance(field_spec, dict) else {}
            dialects = block.get("dialects") if isinstance(block, dict) else None
            if not fname or not isinstance(dialects, list) or not dialects:
                errors.append(
                    f"model '{name}' dataset '{dname}' field {fname!r}: name and non-empty "
                    "expression dialects are required"
                )
    return errors


def _audit_connection(
    db_path: str | Path | None, sources_path: str | Path | None
) -> duckdb.DuckDBPyConnection:
    """The audit's DuckDB session via the shared registry builder (ADR-0010):
    a --sources registry connection when given, else the legacy read-only
    attach of the single SQLite database as catalog ``demo``."""
    if sources_path is not None:
        return build_connection(load_registry(sources_path))[0]
    if db_path is None:
        raise ValueError("audit connection requires --sources or --db")
    con = duckdb.connect()
    # db_path is the author loop's own --db (trusted input; spec §6 accepted
    # boundary) and DuckDB's ATTACH takes no bind parameters — a formatter.
    con.execute(f"ATTACH '{Path(db_path)}' AS demo (TYPE SQLITE, READ_ONLY)")  # nosemgrep
    return con


def _bind_check(rendered: list[tuple[str, str]], con: duckdb.DuckDBPyConnection) -> list[str]:
    """EXPLAIN the rendered SQL on the audit connection: the plan is bound
    without executing it, so a column missing from the source surfaces here —
    verbatim binder text, nothing executed."""
    errors: list[str] = []
    for name, sql in rendered:
        try:
            con.execute(f"EXPLAIN {sql}")  # nosemgrep — sql is render() output
        except Exception as exc:
            errors.append(f"model '{name}' failed the bind check: {type(exc).__name__}: {exc}")
    return errors


def _datasets(staging_dir: str | Path) -> list[tuple[str, str, str, list[str]]]:
    """(model_name, dataset_name, source, primary_key) from the staged OSI YAML."""
    found: list[tuple[str, str, str, list[str]]] = []
    for path in sorted(_models_dir(staging_dir).glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for model in doc.get("semantic_model") or []:
            for dataset in model.get("datasets") or []:
                source = dataset.get("source")
                if isinstance(source, str) and source.strip():
                    name = model.get("name") or dataset.get("name") or path.stem
                    key = [str(k) for k in dataset.get("primary_key") or []]
                    found.append((name, dataset.get("name") or "", source.strip(), key))
    return found


def _assertion_1(
    con: duckdb.DuckDBPyConnection, model: str, dataset: str, source: str, pk: list[str]
) -> str | None:
    """ADR-0006 §5 Assertion 1: the declared grain is strictly distinct over the
    compiled dataset source. Remediation: Pattern 1 (pivot) or Pattern 2 (child
    grain fallback)."""
    wrapped = _wrap_source(source)
    keys = ", ".join(pk)
    total, distinct = con.execute(
        f"SELECT COUNT(*), (SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM {wrapped}) _d) "
        f"FROM {wrapped} _t"  # nosemgrep — read-only attach; source is the staged authored file
    ).fetchone() or (0, 0)
    if total == distinct:
        return None
    return (
        f"grain audit failed for model '{model}' dataset '{dataset}' "
        f"(ADR-0006 Assertion 1, declared-grain uniqueness): declared primary_key "
        f"[{keys}] is not unique over the dataset source: {total} rows vs {distinct} "
        f"distinct keys. Apply the ADR-0006 rubric: upstream conditional pivot "
        f"(Pattern 1) or child-grain fact model (Pattern 2). See {_GRAIN_ADR}."
    )


def _structural_join_errors(
    con: duckdb.DuckDBPyConnection, model: str, dataset: str, source: str
) -> list[str]:
    """The audit's authoritative structural gate (mvp-5 round 2 owner decision:
    converge on the facade's join-uniqueness guard — one implementation, shared
    with serve.py via :mod:`ariadne.grain`): every join anywhere in the source
    tree (CTEs included) must be grain-preserving — each ON key unique on the
    joined side; cartesian / ``ON TRUE`` / inequality / OR'd joins fail closed.
    This closes the Assertion 2 bypass where a fan-out join hides inside a CTE
    the outer SELECT merely reads: no parent projection is directly traceable,
    so the sum-invariance tracer sees nothing while the join still fans out."""
    try:
        check_grain_preserving(con, source)
    except ValueError as exc:  # GRAIN_GUIDANCE: names the invariant + ADR-0006 rubric
        return [
            f"grain audit failed for model '{model}' dataset '{dataset}' "
            f"(structural join check, ADR-0006 grain preservation): {exc}"
        ]
    return []


def _unqualified(expr) -> str:  # _exp.* is a runtime module alias, not a static type
    """The expression's SQL with table qualifiers stripped — it is re-evaluated
    over the raw parent table, which knows no scan aliases."""
    bare = expr.copy()
    for column in bare.find_all(_exp.Column):
        column.set("table", None)
    return bare.sql(dialect="duckdb")


def _parent_projections(tree, alias) -> dict[str, str]:
    """parent-side SUM expression -> wrapped-side output reference, for every
    projection originating PURELY from the parent table: direct columns, aliased
    columns (``o.amount AS amount``), and aliased derivations (``o.a * o.b AS x``)
    all resolve to their underlying parent-origin expression, so the audit cannot
    be dodged by aliasing. Projections mixing in joined-table columns have no
    parent-only baseline and are skipped fail-safe to the compile gate."""
    refs: dict[str, str] = {}
    for projection in tree.selects:
        expr = projection.this if isinstance(projection, _exp.Alias) else projection
        columns = [expr] if isinstance(expr, _exp.Column) else list(expr.find_all(_exp.Column))
        if not columns:  # literal or star projection: nothing parent-origin to trace
            continue
        if any(column.table not in ("", alias) for column in columns):
            continue  # derivation over joined columns too: no parent-only baseline
        if isinstance(projection, _exp.Alias):
            wrapped_ref = projection.alias  # reference the wrapped output name
        elif isinstance(expr, _exp.Column):
            wrapped_ref = expr.name  # bare column: its output name is the column name
        else:
            continue  # unaliased derivation: no stable output name to reference
        refs[_unqualified(expr)] = wrapped_ref
    return refs


def _assertion_2(
    con: duckdb.DuckDBPyConnection, model: str, dataset: str, source: str
) -> list[str]:
    """ADR-0006 §5 Assertion 2: parent aggregate invariance. For a joined dataset
    source, every projection originating from the FROM (parent) table — direct,
    aliased, or derived — must sum identically over the raw parent table and the
    joined source; a divergence is fan-out inflation of the parent grain.
    Remediation: the ADR-0006 rubric (pivot / child-grain model / weight
    allocation).

    ponytail: projections are traced through the source's SELECT list, not by
    resolving each metric expression; subquery FROMs (no raw parent to baseline),
    star projections, mixed parent/joined derivations, and non-numeric or
    parent-absent references (the SUM raises) are skipped fail-safe to the
    compile gate. Widen if models stop projecting their measured columns."""
    try:
        statements = sqlglot.parse(source, dialect="duckdb")
    except Exception:
        return []  # not parseable — the compile gate owns that error verbatim
    tree = statements[0] if len(statements) == 1 else None
    if tree is None or not isinstance(tree, _exp.Select):
        return []  # multi-statement or non-SELECT sources never reach the audit executor
    joins = list(tree.find_all(_exp.Join))
    if not joins:  # Assertion 2 applies only to sources that join
        return []
    from_node = tree.find(_exp.From)
    parent = from_node.this if from_node is not None else None
    if parent is None or not isinstance(parent, _exp.Table):
        return []  # subquery FROM: no raw parent table to baseline against
    parent_sql = parent.sql(dialect="duckdb")
    refs = _parent_projections(tree, parent.alias_or_name)
    if not refs:
        return []
    errors: list[str] = []
    wrapped = _wrap_source(source)
    for parent_expr in sorted(refs):
        try:
            baseline, modeled = con.execute(
                f"SELECT (SELECT SUM({parent_expr}) FROM {parent_sql}), "
                f"(SELECT SUM({refs[parent_expr]}) FROM {wrapped} _a)"  # nosemgrep — read-only
                # attach; source is the staged authored file gated to one SELECT above
            ).fetchone() or (None, None)
        except duckdb.Error:
            continue  # non-numeric or not a parent column: the compile gate's domain
        if baseline is None and modeled is None:
            continue
        if baseline is not None and modeled is not None:
            if abs(modeled - baseline) <= _ADR_TOLERANCE:
                continue
        divergence = "n/a" if baseline is None or modeled is None else repr(modeled - baseline)
        errors.append(
            f"grain audit failed for model '{model}' dataset '{dataset}' "
            f"(ADR-0006 Assertion 2, parent aggregate invariance): "
            f"SUM({parent_expr}) over the joined source = {modeled!r} vs SUM over the raw "
            f"parent table {parent_sql} = {baseline!r} (divergence {divergence} != 0): "
            f"the source fans out the parent grain and inflates parent-side additive "
            f"measures. Apply the ADR-0006 rubric: upstream conditional pivot "
            f"(Pattern 1), child-grain fact model (Pattern 2), or fact weight "
            f"allocation (Pattern 5). See {_GRAIN_ADR}."
        )
    return errors


def _grain_audit(staging_dir: str | Path, con: duckdb.DuckDBPyConnection) -> list[str]:
    """ADR-0006 §5 pre-flight protocol over the staged models: Assertion 1 (grain
    uniqueness) then Assertion 2 (parent aggregate invariance), executed on the
    shared audit connection (spec §6)."""
    datasets = _datasets(staging_dir)
    if not datasets:
        return []
    errors: list[str] = []
    for model, dataset, source, pk in datasets:
        errors.extend(_structural_join_errors(con, model, dataset, source))
        if not pk:  # ADR-0006 rule of single declared grain: a model with no
            # declared primary_key has no verifiable grain — it must FAIL the
            # audit, never pass silently (spec rev 6 §8.14).
            errors.append(
                f"grain audit failed for model '{model}' dataset '{dataset}' "
                f"(ADR-0006 rule of single declared grain): no declared grain — "
                f"the dataset declares no primary_key, so its grain cannot be "
                f"verified for uniqueness or join safety. Declare exactly one "
                f"primary_key unique over the dataset source (Assertion 1) before "
                f"registration. See {_GRAIN_ADR}."
            )
        if pk:
            error = _assertion_1(con, model, dataset, source, pk)
            if error:
                errors.append(error)
        errors.extend(_assertion_2(con, model, dataset, source))
    return errors


def _consumed_files(staging_dir: Path) -> list[tuple[str, Path, bytes]]:
    """Every byte the validator consumes: the model YAMLs, the optional
    ``graph.yml`` and the cited-context corpus (``context_layer/``) — the report
    digest binds all of them (spec rev 1, "digest-bound validation report").
    Bytes are captured at first read so the digest can only ever attest the
    bytes validation started from; drift is detected before the report."""
    def _read(relative: str, path: Path) -> tuple[str, Path, bytes]:
        return relative, path, path.read_bytes()

    files: list[tuple[str, Path, bytes]] = [
        _read(f"semantic_layer/models/{path.name}", path)
        for path in sorted(_models_dir(staging_dir).glob("*.yml"))
    ]
    graph = staging_dir / "semantic_layer" / "graph.yml"
    if graph.is_file():
        files.append(_read("semantic_layer/graph.yml", graph))
    context = staging_dir / "context_layer"
    if context.is_dir():
        for path in sorted(p for p in context.rglob("*") if p.is_file()):
            files.append(_read(f"context_layer/{path.relative_to(context)}", path))
    return files


def _digest_files(files: list[tuple[str, Path, bytes]]) -> str:
    """Deterministic sha256 over the sorted (relative path, length, bytes) of
    every consumed file — over the CAPTURED bytes, not a later reread."""
    digest = hashlib.sha256()
    for relative, _path, data in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _registry_identity(
    db_path: str | Path | None, sources_path: str | Path | None
) -> tuple[str | None, str | None]:
    """``(digest, label)`` of the source identity the audit is bound to: the
    registry file (ADR-0010), or the ``--db`` file standing in for the implicit
    one-source registry. ``None`` when validation is compile-only."""
    if sources_path is not None:
        path = Path(sources_path)
    elif db_path is not None:
        path = Path(db_path)
    else:
        return None, None
    return hashlib.sha256(path.read_bytes()).hexdigest(), str(path)


def _compile_graph(graph: SemanticGraph) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Per-owner compilation through the single-dataset ``render()`` (ADR-0008):
    each dataset renders with the base metrics it owns plus the derived metrics
    whose whole dependency closure stays inside that one dataset — a
    domain-layout model compiles exactly like legacy single-dataset files.
    Cross-fact derived metrics (closure spanning datasets) are dependency-checked
    at load; compiling them is the planner's job (#27) and they are counted,
    never silently skipped."""
    rendered: list[tuple[str, str]] = []
    errors: list[str] = []
    skipped: list[str] = []
    for model_name, envelope in sorted(graph.models.items()):
        model = envelope["semantic_model"][0]
        raw = {
            metric.get("name"): metric
            for metric in model.get("metrics") or []
            if isinstance(metric, dict)
        }
        # metric name -> compiling dataset: base metrics by owner, derived by
        # fixed point over assigned dependencies (single dataset or not compiled).
        assigned: dict[str, str] = {
            name: node.owner
            for name, node in graph.metrics.items()
            if node.model == model_name and node.owner is not None
        }
        changed = True
        while changed:
            changed = False
            for name, node in sorted(graph.metrics.items()):
                if node.model != model_name or name in assigned or not node.deps:
                    continue
                if all(dep in assigned for dep in node.deps) and len(
                    {assigned[dep] for dep in node.deps}
                ) == 1:
                    assigned[name] = assigned[node.deps[0]]
                    changed = True
        skipped.extend(
            name
            for name, node in graph.metrics.items()
            if node.model == model_name and node.derived and name not in assigned
        )
        by_dataset: dict[str, list[str]] = {}
        for name, dataset in assigned.items():
            by_dataset.setdefault(dataset, []).append(name)
        for dataset, names in sorted(by_dataset.items()):
            sub = {
                "version": envelope.get("version"),
                "semantic_model": [
                    {
                        "name": model_name,
                        "datasets": [
                            entry
                            for entry in model.get("datasets") or []
                            if isinstance(entry, dict) and entry.get("name") == dataset
                        ],
                        "metrics": [raw[name] for name in sorted(names) if name in raw],
                    }
                ],
            }
            label = f"model '{model_name}' dataset '{dataset}'"
            errors.extend(_schema_errors(sub))
            try:
                rendered.append((model_name, render(sub)))
            except RenderError as exc:  # the compiler's verbatim reason (spec §7)
                errors.append(f"{label} failed to compile: {exc}")
            except Exception as exc:
                errors.append(f"{label} failed to compile: {type(exc).__name__}: {exc}")
        # Datasets owning no metrics (reachable only via relationships /
        # conformance) still get their structure and field expressions checked —
        # no dataset bypasses validation because no metric compiles against it.
        for entry in model.get("datasets") or []:
            if not isinstance(entry, dict) or entry.get("name") in by_dataset:
                continue
            label = f"model '{model_name}' dataset '{entry.get('name')}'"
            sub = {
                "version": envelope.get("version"),
                "semantic_model": [
                    {"name": model_name, "datasets": [entry], "metrics": []}
                ],
            }
            errors.extend(_schema_errors(sub, require_metrics=False))
            for field_spec in entry.get("fields") or []:
                fname = field_spec.get("name") if isinstance(field_spec, dict) else None
                context = f"field {fname!r}"
                try:
                    _parse(
                        _dialect_expression(field_spec.get("expression") or {}, context),
                        context,
                    )
                except RenderError as exc:
                    errors.append(f"{label}: {exc}")
    return rendered, errors, skipped


def validate(
    staging_dir: str | Path,
    db_path: str | Path | None = None,
    sources_path: str | Path | None = None,
) -> ValidationResult:
    """Normalize (issue #26), schema-check and render the staged OSI models
    (ADR-0008); with ``db_path`` or ``sources_path`` (ADR-0010), additionally
    EXPLAIN-bind the rendered SQL and run the ADR-0006 §5 grain audit over the
    shared audit connection. The result carries a digest-bound
    :class:`ValidationReport`; graph failures are structural and precede any
    SELECT compilation."""
    staging = Path(staging_dir)
    models_dir = _models_dir(staging)
    if not models_dir.is_dir():
        return ValidationResult(False, [f"no semantic models under {models_dir}"])
    files = _consumed_files(staging)
    registry_digest, registry_label = _registry_identity(db_path, sources_path)
    live = db_path is not None or sources_path is not None

    errors: list[str] = []
    structural_detail = ""
    graph: SemanticGraph | None = None
    try:
        graph = load_graph(staging / "semantic_layer")
    except GraphError as exc:
        errors.append(str(exc))
        structural_detail = str(exc)
    except Exception as exc:
        errors.append(f"graph load failed: {type(exc).__name__}: {exc}")
        structural_detail = errors[-1]

    rendered: list[tuple[str, str]] = []
    compile_errors: list[str] = []
    skipped_derived: list[str] = []
    compile_outcome = "not-run"
    compile_detail = ""
    if graph is not None:
        rendered, compile_errors, skipped_derived = _compile_graph(graph)
        errors.extend(compile_errors)
        # distinct truthful outcomes (the ticket's contract): schema/render
        # failures are recorded as a failed compile check with their
        # diagnostics, not silently under a passed structural check
        compile_outcome = "failed" if compile_errors else "passed"
        compile_detail = "; ".join(compile_errors)
        if skipped_derived and not compile_errors:
            # the passed outcome is scoped to the compiled definitions only —
            # skipped cross-fact derived metrics are named here, never a bare
            # complete-success signal (recheck finding 1)
            names = ", ".join(sorted(skipped_derived))
            compile_detail = (
                f"{len(skipped_derived)} cross-fact derived metric(s) not compiled "
                f"({names}); dependency-checked only; compilation is the "
                "planner's job (#27) — the passed outcome covers the compiled "
                "definitions only"
            )

    bind_outcome = grain_outcome = "not-run"
    if graph is not None and not errors and live:
        # bind check + audit only what compiles; one audit connection for both
        # (the shared registry builder, ADR-0010 — or the legacy demo attach).
        con = _audit_connection(db_path, sources_path)
        try:
            bind_errors = _bind_check(rendered, con)
            errors.extend(bind_errors)
            bind_outcome = "failed" if bind_errors else "passed"
            try:
                grain_errors = _grain_audit(staging_dir, con)
            except Exception as exc:
                errors = [f"grain audit failed: {type(exc).__name__}: {exc}"]
                grain_outcome = "failed"
            else:
                errors.extend(grain_errors)
                grain_outcome = "failed" if grain_errors else "passed"
        finally:
            con.close()

    # The digest may only attest bytes that were actually validated: a file
    # that changed while validation ran voids the report instead of being
    # hashed in after the fact (the grain audit rereads the models late).
    drifted = sorted(
        relative for relative, path, data in files if path.read_bytes() != data
    )
    if drifted:
        errors.append(
            f"semantic layer file(s) changed during validation: {', '.join(drifted)} "
            "— report refused (a digest would attest unchecked bytes)"
        )
        return ValidationResult(False, errors)

    conformance_outcome, conformance_detail = "not-run", ""
    if graph is not None:
        unverified = [edge.name for edge in graph.conformed_dimensions if not edge.type_verified]
        if unverified:
            # absent type evidence is disclosed, never treated as established
            # compatibility (spec rev 1 §3)
            conformance_detail = (
                "value-type compatibility unverified for conformed dimension(s) "
                f"{unverified}: members carry no type evidence (bare source columns)"
            )
        else:
            conformance_outcome = "passed"

    report = ValidationReport(
        digest=_digest_files(files),
        scope="structural+bind+grain" if live else "compile-only (structural)",
        validator_version=VALIDATOR_VERSION,
        registry_digest=registry_digest,
        registry_label=registry_label,
        files=tuple(relative for relative, _path, _data in files),
        checks=(
            CheckOutcome("structural", "failed" if graph is None else "passed", structural_detail),
            CheckOutcome("compile", compile_outcome, compile_detail),
            CheckOutcome("conformance", conformance_outcome, conformance_detail),
            CheckOutcome("bind", bind_outcome),
            CheckOutcome("grain", grain_outcome),
            CheckOutcome(
                "relationship_audit",
                "not-run",
                "live relationship-target audits land in task 2 (#27) — "
                "reported not-run, never as passed",
            ),
        ),
    )
    return ValidationResult(not errors, errors, report=report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.validate",
        description="Validate staged OSI semantic models with the own sqlglot renderer "
        "(ADR-0008; exit 0/1); with --db, also EXPLAIN-bind and run the ADR-0006 §5 grain audit.",
    )
    parser.add_argument("staging_dir", nargs="?", default="staging")
    parser.add_argument(
        "--db", default=None, help="SQLite database for the grain audit (read-only attach)"
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="source registry YAML for the audit connection (ADR-0010; default: "
        "./ariadne.yaml only when neither --sources nor --db is given)",
    )
    args = parser.parse_args(argv)
    sources_path = default_registry_path(args.sources, args.db)
    if sources_path is not None:
        args.db = None  # the registry connection replaces the single-sqlite attach
    result = validate(args.staging_dir, db_path=args.db, sources_path=sources_path)
    scope = f"scope: {result.report.scope}; relationship-audit: not-run" if result.report else ""
    if result.ok:
        audited = (
            " and pass the grain audit (ADR-0006 §5)"
            if args.db is not None or sources_path is not None
            else ""
        )
        print(f"ok: staged OSI models under {args.staging_dir} compile{audited}")
        if result.report:  # the digest-bound scope label (spec rev 1: a
            # compile-only report is visibly partial, never a full pass)
            print(scope)
            print(
                f"digest: {result.report.digest} "
                f"(validator {result.report.validator_version})"
            )
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    if scope:
        print(scope, file=sys.stderr)  # CI sees which checks the failure covers
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
