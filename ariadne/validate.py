"""Deterministic validation: real Datus compile of staged OSI models (ticket #4).

``validate(staging_dir)`` compiles every model under
``<staging>/semantic_layer/models/`` with the datus-semantic-osi adapter
(mechanism per docs/research/datus-spike.md §5: Python import, compile-only,
no db_config) and returns a :class:`ValidationResult`. Severity ``warning``
issues are pass-through (spike §3.2 — the intended gotcha pattern
``CASE WHEN <dimension> ...`` triggers an advisory lint); only ``error``
severity, load/schema exceptions, or a failed SQL dry-run of a listed metric
count as compile failures. The returned error messages are the feedback the
author loop replays into the next LLM round.

With ``db_path`` (``--db``, passed by the author loop), a post-compile GRAIN AUDIT
runs per ADR-0006 §5 (docs/adr/0006-grain-governance-multi-cardinality-joins.md):
Assertion 1 — the declared ``primary_key`` is unique over the compiled dataset
source; Assertion 2 — parent aggregate invariance: for dataset sources containing
JOINs, additive parent-table columns must sum identically over the raw parent table
and the joined source (fan-out inflation -> fail, remediation names the ADR-0006
rubric patterns). The audit executes the authored source SQL on a read-only DuckDB
attach of the SQLite database — the sanctioned staged-authoring path (serve.py's
``_check_grain_preserving`` is the separate facade-side guard for ad-hoc tool input).
Without ``db_path``, validate compiles only.

CLI::

    python -m ariadne.validate staging/               # exit 0 = compiles
    python -m ariadne.validate staging/ --db data/demo.db   # compile + grain audit
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

# sqlglot exposes its AST node module lazily (sqlglot.exp is a real module but not
# statically exported), so resolve it at runtime like serve.py does.
_exp = getattr(sqlglot, "exp")

_GRAIN_ADR = "docs/adr/0006-grain-governance-multi-cardinality-joins.md"
_NUMERIC_TYPES = ("INT", "DECIMAL", "NUMERIC", "REAL", "FLOAT", "DOUBLE", "HUGEINT")
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


def _assertion_2(
    con: duckdb.DuckDBPyConnection, model: str, dataset: str, source: str
) -> list[str]:
    """ADR-0006 §5 Assertion 2: parent aggregate invariance. For a joined dataset
    source, every projected column originating from the FROM (parent) table must
    sum identically over the raw parent table and the joined source — a divergence
    is fan-out inflation of the parent grain. Remediation: the ADR-0006 rubric
    (pivot / child-grain model / weight allocation).

    ponytail: projected-parent-column heuristic — measures are detected via the
    source's SELECT list (qualified parent columns), not by resolving each metric
    expression; subquery FROMs (no raw parent to baseline) and star projections
    are skipped fail-safe to the compile gate. Widen if models stop projecting
    their measured columns."""
    try:
        statements = sqlglot.parse(source, dialect="duckdb")
    except Exception:
        return []  # not parseable — the compile gate owns that error verbatim
    if len(statements) != 1 or not isinstance(statements[0], _exp.Select):
        return []  # multi-statement or non-SELECT sources never reach the audit executor
    tree = statements[0]
    joins = list(tree.find_all(_exp.Join))
    if not joins:  # Assertion 2 applies only to sources that join
        return []
    from_node = tree.find(_exp.From)
    parent = from_node.this if from_node is not None else None
    if parent is None or not isinstance(parent, _exp.Table):
        return []  # subquery FROM: no raw parent table to baseline against
    parent_sql = parent.sql(dialect="duckdb")
    alias = parent.alias_or_name
    columns = sorted(
        {
            col.name
            for col in tree.selects
            if isinstance(col, _exp.Column) and col.table == alias
        }
    )
    if not columns:
        return []
    numeric = {
        row[0]
        for row in con.execute(f"DESCRIBE SELECT * FROM {parent_sql}").fetchall()  # nosemgrep
        if any(t in str(row[1]).upper() for t in _NUMERIC_TYPES)
    }
    errors: list[str] = []
    wrapped = _wrap_source(source)
    for column in columns:
        if column not in numeric:  # additive aggregates only exist over numeric columns
            continue
        baseline, modeled = con.execute(
            f"SELECT (SELECT SUM({column}) FROM {parent_sql}), "
            f"(SELECT SUM({column}) FROM {wrapped} _a)"  # nosemgrep — read-only attach,
            # source is the staged authored file gated to one SELECT above (spec §6)
        ).fetchone() or (None, None)
        if baseline is None and modeled is None:
            continue
        if baseline is not None and modeled is not None:
            if abs(modeled - baseline) <= _ADR_TOLERANCE:
                continue
        divergence = "n/a" if baseline is None or modeled is None else repr(modeled - baseline)
        errors.append(
            f"grain audit failed for model '{model}' dataset '{dataset}' "
            f"(ADR-0006 Assertion 2, parent aggregate invariance): "
            f"SUM({column}) over the joined source = {modeled!r} vs SUM over the raw "
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
            if pk:
                error = _assertion_1(con, model, dataset, source, pk)
                if error:
                    errors.append(error)
            errors.extend(_assertion_2(con, model, dataset, source))
    finally:
        con.close()
    return errors


def validate(staging_dir: str | Path, db_path: str | Path | None = None) -> ValidationResult:
    """Compile the staged OSI models (warnings pass through, errors are captured);
    with ``db_path``, additionally run the ADR-0006 §5 grain audit post-compile."""
    try:
        from datus_semantic_osi.adapter import (  # pyright: ignore[reportMissingImports]
            DatusOSIAdapter,
        )
        from datus_semantic_osi.config import (  # pyright: ignore[reportMissingImports]
            DatusOSIConfig,
        )
    except ImportError as exc:  # keep the failure actionable for the author loop
        return ValidationResult(
            False,
            [
                "datus-semantic-osi is not importable "
                "(install 'datus-semantic-osi[metricflow]' on Python 3.12): "
                f"{exc}"
            ],
        )

    async def _compile():
        adapter = DatusOSIAdapter(
            DatusOSIConfig(semantic_models_path=str(_models_dir(staging_dir)))
        )
        result = await adapter.validate_semantic()
        errors = [
            issue.message
            for issue in result.issues
            if getattr(issue, "severity", "error") == "error"
        ]
        if not result.valid and not errors:  # failed without a graded issue: keep everything
            errors = [issue.message for issue in result.issues]
        if not errors:
            # Lowering check: validate_semantic can pass a model whose metrics
            # still fail to lower to SQL; compile each one for real.
            for metric in await adapter.list_metrics():
                await adapter.query_metrics(
                    metrics=[metric.name], dimensions=[], dry_run=True
                )
        return errors

    try:
        errors = asyncio.run(_compile())
    except Exception as exc:
        return ValidationResult(False, [f"compile failed: {type(exc).__name__}: {exc}"])
    if not errors and db_path is not None:  # audit only what already compiles
        try:
            errors.extend(_grain_audit(staging_dir, db_path))
        except Exception as exc:
            errors = [f"grain audit failed: {type(exc).__name__}: {exc}"]
    return ValidationResult(not errors, errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.validate",
        description="Compile staged OSI semantic models with Datus (exit 0/1); "
        "with --db, also run the ADR-0006 §5 grain audit.",
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
