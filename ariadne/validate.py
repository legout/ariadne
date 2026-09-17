"""Deterministic validation of staged OSI models (ticket #4; ADR-0008 since rev 7).

``validate(staging_dir)`` validates every model under
``<staging>/semantic_layer/models/`` through the own sqlglot compiler
(:mod:`ariadne.render`, ADR-0008): an envelope schema check (required fields:
version, model name, dataset name/source/fields, metric name/expression), then
a full ``render()`` of every model — a malformed envelope or unrenderable
construct fails with the compiler's verbatim reason. There is no datus import
anywhere in the pipeline.

With ``db_path`` (``--db``, passed by the author loop), the rendered SQL also
passes an EXPLAIN bind-check on a read-only DuckDB attach of the SQLite database
(a column missing from the source only surfaces at bind time — nothing executes),
and then the post-compile GRAIN AUDIT
runs per ADR-0006 §5 (docs/adr/0006-grain-governance-multi-cardinality-joins.md):
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
    python -m ariadne.validate staging/ --db data/demo.db   # + bind check + grain audit
"""

from __future__ import annotations

import argparse
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
    render,
)

# sqlglot exposes its AST node module lazily (sqlglot.exp is a real module but not
# statically exported), so resolve it at runtime like serve.py does.
_exp = getattr(sqlglot, "exp")

_GRAIN_ADR = "docs/adr/0006-grain-governance-multi-cardinality-joins.md"
_ADR_TOLERANCE = 1e-9


def _wrap_source(source: str) -> str:
    """The dataset source as a FROM-able subquery (a bare table ref needs a SELECT)."""
    if re.match(r"(?is)\s*(select|with)\b", source):
        return f"({source})"
    return f"(SELECT * FROM {source})"


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


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
                (str(name) if name else path.stem,
                 {"version": doc.get("version"), "semantic_model": [model]})
            )
    return entries


def _schema_errors(envelope: dict) -> list[str]:
    """Envelope required fields: version, model name, and per dataset name, source,
    fields (name + expression dialects) and per metric name + expression dialects.
    primary_key presence is governed by the grain audit stage (ADR-0006 rule of
    single declared grain — it owns that error's contract, incl. compile-only
    validate passing pk-less models)."""
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
    if not isinstance(metrics, list) or not metrics:
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


def _bind_check(rendered: list[tuple[str, str]], db_path: str | Path) -> list[str]:
    """EXPLAIN the rendered SQL on a read-only attach of the SQLite database:
    the plan is bound without executing it, so a column missing from the source
    surfaces here — verbatim binder text, nothing executed."""
    errors: list[str] = []
    con = duckdb.connect()
    try:
        # db_path is the author loop's own --db (trusted input; spec §6 accepted
        # boundary) and DuckDB's ATTACH takes no bind parameters — a formatter.
        con.execute(f"ATTACH '{Path(db_path)}' AS demo (TYPE SQLITE, READ_ONLY)")  # nosemgrep
        for name, sql in rendered:
            try:
                con.execute(f"EXPLAIN {sql}")  # nosemgrep — sql is render() output
            except Exception as exc:
                errors.append(
                    f"model '{name}' failed the bind check: {type(exc).__name__}: {exc}"
                )
    finally:
        con.close()
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


def _grain_audit(staging_dir: str | Path, db_path: str | Path) -> list[str]:
    """ADR-0006 §5 pre-flight protocol over the staged models: Assertion 1 (grain
    uniqueness) then Assertion 2 (parent aggregate invariance), executed on a
    read-only DuckDB attach of the SQLite database (spec §6)."""
    datasets = _datasets(staging_dir)
    if not datasets:
        return []
    errors: list[str] = []
    con = duckdb.connect()
    try:
        # db_path is the author loop's own --db (trusted input; spec §6 accepted
        # boundary) and DuckDB's ATTACH takes no bind parameters — a formatter.
        con.execute(f"ATTACH '{Path(db_path)}' AS demo (TYPE SQLITE, READ_ONLY)")  # nosemgrep
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
    finally:
        con.close()
    return errors


def validate(staging_dir: str | Path, db_path: str | Path | None = None) -> ValidationResult:
    """Schema-check and render the staged OSI models (ADR-0008); with ``db_path``,
    additionally EXPLAIN-bind the rendered SQL and run the ADR-0006 §5 grain audit."""
    models_dir = _models_dir(staging_dir)
    if not models_dir.is_dir():
        return ValidationResult(False, [f"no semantic models under {models_dir}"])
    try:
        entries = _model_entries(staging_dir)
    except Exception as exc:
        return ValidationResult(False, [f"{type(exc).__name__}: {exc}"])
    if not entries:
        return ValidationResult(False, [f"no semantic models under {models_dir}"])

    errors: list[str] = []
    rendered: list[tuple[str, str]] = []
    for name, envelope in entries:
        errors.extend(_schema_errors(envelope))
        try:
            rendered.append((name, render(envelope)))
        except RenderError as exc:  # the compiler's verbatim reason (spec §7)
            errors.append(f"model '{name}' failed to compile: {exc}")
        except Exception as exc:
            errors.append(f"model '{name}' failed to compile: {type(exc).__name__}: {exc}")
    if not errors and db_path is not None:  # bind check + audit only what compiles
        errors.extend(_bind_check(rendered, db_path))
        try:
            errors.extend(_grain_audit(staging_dir, db_path))
        except Exception as exc:
            errors = [f"grain audit failed: {type(exc).__name__}: {exc}"]
    return ValidationResult(not errors, errors)


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
    args = parser.parse_args(argv)
    result = validate(args.staging_dir, db_path=args.db)
    if result.ok:
        audited = " and pass the grain audit (ADR-0006 §5)" if args.db else ""
        print(f"ok: staged OSI models under {args.staging_dir} compile{audited}")
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
