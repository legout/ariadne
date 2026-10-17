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

import threading
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import sources
from ariadne.query_results import (  # pyright: ignore[reportMissingImports] — drift
    cell_json_bytes,
    classify_output_type,
    encode_scalar,
    type_unsupported_refusal,
)
from ariadne.render import output_guard  # pyright: ignore[reportMissingImports] — drift
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    Registry,
    build_connection,  # noqa: F401 — re-export: the historical patch seam stays importable
)

# The deadline seam's clock (K3 issue #43): a module attribute so a caller's
# tests can control timeout behavior DETERMINISTICALLY (a patched clock, never
# a wall-clock race or a hosted service).
_deadline_clock = time.monotonic

DEADLINE_MESSAGE = (
    "the inspection deadline ({budget}s total across source setup, catalog reads "
    "and inspection statements) was exhausted before the measurement could "
    "complete — every statement was interrupted and nothing was claimed "
    "complete; re-inspect with a narrower candidate or scope"
)


class DeadlineExhausted(ValueError):
    """The deadline refusal raised by :meth:`DeadlineBudget.guard` and the
    bounded setup (spec 0014 §6 reuses the K3 mechanism for query
    operations). A ValueError subclass so the existing inspection callers
    and tests keep their exact behavior; the query runtime converts it into
    the structured ``execution_deadline`` refusal."""


UNCANCELLABLE_MESSAGE = (
    "the owned connection exposes no interruptible execution for this backend "
    "— an inspection whose execution cannot be bounded and cancelled is an "
    "explicit refusal, never a fake passing check (spec 0010 §7)"
)


class DeadlineBudget:
    """One shared wall-clock budget across EVERY phase of a bounded operation
    (K3 issue #43, plan §2): source setup, catalog reads and each inspection
    statement draw down the same budget, and each guarded statement arms the
    owned connection's interrupt so an over-budget backend read STOPS — the
    deadline is never claimed to have stopped a query that is still running."""

    def __init__(self, seconds: float, *, clock=None) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
            raise ValueError(f"the execution deadline must be a positive number, got {seconds!r}")
        self.seconds = float(seconds)
        self._clock = clock or _deadline_clock
        self._start = self._clock()

    def remaining(self) -> float:
        return max(self.seconds - (self._clock() - self._start), 0.0)

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    @contextmanager
    def guard(self, con):
        """Run one guarded phase: refuse immediately when the budget is spent,
        arm the connection's interrupt for the remaining budget, and convert an
        interruption that fired at/after expiry into the explicit deadline
        refusal (never a partial result)."""
        if self.expired():
            raise DeadlineExhausted(DEADLINE_MESSAGE.format(budget=self.seconds))
        if not hasattr(con, "interrupt"):
            raise ValueError(UNCANCELLABLE_MESSAGE)
        timer = threading.Timer(max(self.remaining(), 1e-6), con.interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield
        except duckdb.Error:
            if self.expired():
                raise DeadlineExhausted(DEADLINE_MESSAGE.format(budget=self.seconds)) from None
            raise
        finally:
            timer.cancel()  # the phase ended: no background read keeps running
        # K3 fix pass (finding 9): a SUCCESSFUL phase that finished beyond the
        # budget is exhaustion too — its result escaped the deadline and is
        # never returned as a completed measurement.
        if self.expired():
            raise DeadlineExhausted(DEADLINE_MESSAGE.format(budget=self.seconds))


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


class BoundedCollection:
    """One compiled query's bounded collection result (spec 0014 §4):
    the logical output columns, the collected rows as scalar-encoded dicts,
    and the overflow facts — ``row_overflow`` is True exactly when the row
    ceiling plus its one indicator row was reached; ``cell_overflow`` names
    the logical columns whose values were oversized in raw bytes (DuckDB
    markers — the value never transferred) or in serialized form (exact
    post-transfer check: escaped form can exceed raw size)."""

    def __init__(
        self, columns: list[str], rows: list[dict], row_overflow: bool, cell_overflow: list[str]
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.row_overflow = row_overflow
        self.cell_overflow = cell_overflow


class DuckDBExecution:
    """The concrete DuckDB execution owner: connection, catalog, bind, result
    collection and close — moved intact from the query runtime (issue #33);
    every guarded operation is the historical one, in the historical order."""

    def __init__(self, registry: Registry, *, budget=None, selected_assets=None) -> None:
        """The one DuckDB session over the registry sources (ADR-0010):
        :func:`ariadne.sources.build_connection` executes its deterministic
        statement plan verbatim and returns the connection plus the per-source
        catalog (cheap enumeration only — no profiling here). The call resolves
        through the :mod:`ariadne.sources` module, so the builder stays ONE
        shared chokepoint every caller (and test canary) sees (issue #35/G3).
        With a K3 :class:`DeadlineBudget`, the source SETUP (extension loads,
        attaches, catalog reads) runs under the same interrupt watchdog as the
        guarded statements — an over-budget setup stops and reports the
        deadline, never a partial session."""
        deadline = budget.remaining() if budget is not None else None
        selection = {"selected_assets": selected_assets} if selected_assets is not None else {}
        if deadline is not None:
            self.con, self.catalog = sources.build_connection(
                registry, deadline=deadline, **selection
            )
        else:
            self.con, self.catalog = sources.build_connection(registry, **selection)
        if budget is not None and budget.expired():
            self.close()
            raise DeadlineExhausted(DEADLINE_MESSAGE.format(budget=budget.seconds))

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
        output and nothing else (spec §6) — returns (columns, row dicts).
        The historical unbounded collection, kept for the trusted internal
        callers (profiling/validation); the four Query result operations use
        :meth:`fetch_bounded` (spec 0014 §4)."""
        relation = self.con.sql(sql)
        columns = list(relation.columns)
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return columns, rows

    def fetch_bounded(self, sql: str, limits: dict, budget: DeadlineBudget) -> BoundedCollection:
        """Bounded collection of one compiled query's result (spec 0014 §4,
        issue #56/S1): sql is the compile step's output and nothing else
        (spec §6). The output types are inspected and nested/complex types
        refuse BEFORE any execution; the compiler-owned output guard then
        caps materialized rows at the ceiling plus ONE overflow indicator
        row and raw-guards variable-size cells inside DuckDB (oversized
        values become NULL plus a flag — the value never crosses into
        Python); collection uses bounded cursor reads (``fetchmany``), never
        ``fetchall()`` followed by slicing; and every collected cell is
        encoded and exactly byte-checked (escaped form can exceed raw
        size). The guarded execution runs under the shared deadline budget;
        the cursor is drained only up to the indicator row and never past
        it — counting stops rather than scanning the rejected remainder.
        The flag↔column association is POSITIONAL against the guarded layout
        this method derives from the same classification the guard used
        (fix pass 1, finding 4): a physical output column whose name
        collides with the ``__ariadne_cell_overflow_`` namespace is still a
        value column — never swallowed or misread as a marker."""
        relation = self.con.sql(sql)  # bind-only: schema without execution
        columns = list(relation.columns)
        types = [str(t) for t in relation.types]
        unsupported = [
            name
            for name, type_name in zip(columns, types)
            if classify_output_type(type_name) == "unsupported"
        ]
        if unsupported:
            raise type_unsupported_refusal(unsupported)
        guarded = output_guard(
            sql, columns, types, cell_bytes=limits["cell_bytes"], max_rows=limits["max_rows"]
        )
        # the guarded SELECT's positional layout, derived from the SAME
        # classification the guard used: one value slot per logical column,
        # plus one flag slot immediately after each guarded (variable) column
        layout: list[tuple[str, int]] = []
        for index, type_name in enumerate(types):
            layout.append(("value", index))
            if classify_output_type(type_name) == "variable":
                layout.append(("flag", index))
        raw: list[tuple] = []
        with budget.guard(self.con):
            # nosemgrep — the compiler-built output guard over compile-step
            # output only (spec §6): render()/planner SQL, never caller text.
            self.con.execute(guarded)
            remaining = limits["max_rows"] + 1
            while remaining > 0:
                batch = self.con.fetchmany(min(remaining, 256))
                if not batch:
                    break
                raw.extend(batch)
                remaining -= len(batch)
        row_overflow = len(raw) > limits["max_rows"]
        if row_overflow:
            raw = raw[: limits["max_rows"] + 1]  # the indicator row: stop counting here
        rows: list[dict] = []
        cell_overflow: list[str] = []
        for row in raw:
            entry: dict = {}
            for value, (kind, index) in zip(row, layout, strict=True):
                if kind == "flag":  # positional marker slot: no name parsing
                    if value:
                        cell_overflow.append(columns[index])
                    continue
                entry[columns[index]] = encode_scalar(value)
            rows.append(entry)
        if not row_overflow:  # exact serialized-cell check on the bounded values
            for entry in rows:
                for name, value in entry.items():
                    if cell_json_bytes(value) > limits["cell_bytes"]:
                        cell_overflow.append(name)
        return BoundedCollection(columns, rows, row_overflow, list(dict.fromkeys(cell_overflow)))

    def close(self) -> None:
        """Close the owned connection (the single owner closes it)."""
        self.con.close()
