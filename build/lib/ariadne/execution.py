"""DuckDB Execution: the shared connection owner for Query, profiling and
validation (spec 2026-10-02-0009 §2 "Module ownership", ADR-0016).

:class:`DuckDBExecution` owns the long-lived DuckDB session built by the shared
source-registry builder (:mod:`ariadne.sources`, ADR-0010), its catalog, the
EXPLAIN bind operation, the compiled-query statement guard and result
collection, and close. Query (:mod:`ariadne.query`), the profiler
(:mod:`ariadne.profiler`) and the validation audit (:mod:`ariadne.validate`)
perform their guarded database operations through this one owner — internal
trusted callers may use ``con`` directly for their existing trusted operations
(audit SELECTs, information_schema reads), but no external tool ever receives
the connection (spec §6: Execution is not an ``execute_sql`` tool).

The no-unvalidated-execution invariant (spec 2026-09-23-0001 §6) is unchanged:
:func:`assert_single_statement` and :meth:`DuckDBExecution.bind` only ever
receive SQL returned by a compile step (:mod:`ariadne.render` or the multi-fact
planner) — there is no code path from tool arguments to ``duckdb.execute`` that
bypasses the compiler, and no second compiler exists here. This module imports
no workflow module (spec §2).
"""

from __future__ import annotations

from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import sources
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    Registry,
    build_connection,  # noqa: F401 — re-export: the historical patch seam stays importable
)


def assert_single_statement(sql: str) -> None:
    """Spec §6 no-unvalidated-execution invariant: the executor receives exactly
    one statement. Uses duckdb's own parser (extract_statements), so semicolons
    inside string literals cannot false-positive; an unparseable compiled SQL is
    likewise rejected — nothing reaches a duckdb call un-parsed. Runs on the
    compiled SQL after the Datus gate and BEFORE any duckdb call (EXPLAIN or
    execution): both paths share this choke point, so no future code path can
    reintroduce multi-statement SQL. Rejection: nothing staged, nothing executed."""
    try:
        count = len(duckdb.extract_statements(sql))
    except Exception as exc:  # parse error — the SQL can never be one valid statement
        raise ValueError(f"{type(exc).__name__}: {exc}") from exc
    if count != 1:
        raise ValueError(
            f"compiled SQL must be exactly one statement, got {count} "
            "(no-unvalidated-execution invariant, spec §6); nothing staged, nothing executed"
        )


class DuckDBExecution:
    """The concrete DuckDB execution owner: connection, catalog, bind, result
    collection and close — moved intact from the query runtime (issue #33);
    every guarded operation is the historical one, in the historical order."""

    def __init__(self, registry: Registry) -> None:
        """The one DuckDB session over the registry sources (ADR-0010):
        :func:`ariadne.sources.build_connection` executes its deterministic
        statement plan verbatim and returns the connection plus the per-source
        catalog (cheap enumeration only — no profiling here). The call resolves
        through the :mod:`ariadne.sources` module, so the builder stays ONE
        shared chokepoint every caller (and test canary) sees (issue #35/G3)."""
        self.con, self.catalog = sources.build_connection(registry)

    @classmethod
    def legacy_sqlite(cls, db_path: str | Path) -> DuckDBExecution:
        """The legacy ``--db`` audit attach, moved verbatim from the validation
        audit's connection builder: one plain read-only sqlite ATTACH as catalog
        ``demo`` (the authoring contract's catalog name), no registry
        enumeration. db_path is the author loop's own --db (trusted input;
        spec §6 accepted boundary) and DuckDB's ATTACH takes no bind
        parameters — a formatter."""
        con = duckdb.connect()
        con.execute(f"ATTACH '{Path(db_path)}' AS demo (TYPE SQLITE, READ_ONLY)")  # nosemgrep
        execution = cls.__new__(cls)
        execution.con = con
        execution.catalog = []
        return execution

    def bind(self, sql: str) -> None:
        """EXPLAIN the compiled SQL: the plan is bound without executing it, so
        a column missing from the source surfaces here — the binder's text,
        verbatim, nothing executed (spec §8.9). sql is always a compile step's
        output (render() or planner), never caller text (spec §6)."""
        try:
            # nosemgrep — compiled output only (spec §6): render()/planner SQL.
            self.con.execute(f"EXPLAIN {sql}")
        except Exception as exc:
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc

    def fetch(self, sql: str) -> tuple[list[str], list[dict]]:
        """Collect one compiled query's result: sql is the compile step's
        output and nothing else (spec §6) — returns (columns, row dicts)."""
        relation = self.con.sql(sql)
        columns = list(relation.columns)
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return columns, rows

    def close(self) -> None:
        """Close the owned connection (the single owner closes it)."""
        self.con.close()
