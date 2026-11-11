"""Database profiler: DuckDB SUMMARIZE + PK/FK heuristics over the source registry (ticket #3).

Reads every source of the ADR-0010 registry (``ariadne.yaml``) — or the legacy
single SQLite file (``--db``) — read-only through the shared execution owner
(:class:`ariadne.execution.DuckDBExecution` over :mod:`ariadne.sources`'
connection builder), profiles every table, and emits a JSON-serializable
dict. This output is the input contract of the authoring agent
(``ariadne.author``, ticket #4), which combines it with ``examples/retail-demo/seed_notes.md``;
the profiler surfaces statistics only — business rules live in the seed notes,
never here.

Output shape: the legacy single-sqlite call keeps the historical contract
(``profile(db_path) -> dict``, also written by the CLI)::

    {
      "db_path": "examples/retail-demo/data/demo.db",
      "dialect": "sqlite",
      "tables": {
        "<table>": {
          "row_count": 500,
          "primary_key_candidates": ["order_id"],
          "foreign_key_candidates": [
            {
              "column": "customer_id",
              "references_table": "customers",
              "references_column": "id",
              "match_ratio": 1.0
            }
          ],
          "columns": {
            "<column>": {
              "type": "BIGINT",
              "null_count": 0,
              "null_ratio": 0.0,
              "distinct_count": 500,
              "unique_ratio": 1.0,
              "approx_unique": 520,
              "min": "1", "max": "500",
              "avg": "250.5", "std": "144.48",
              "q25": "126", "q50": "250", "q75": "376",
              "top_values": [{"value": "USD", "count": 435}],
              "top_value_share": 0.87,
              "pk_candidate": true
            }
          }
        }
      }
    }

A registry run (``profile(sources_path=...)``) returns the same per-table shape
per source: ``{"sources_path": ..., "sources": [{"name", "type", "tables"}]}``.

Field notes for consumers:

- every table value additionally carries the explicit identity tuple
  ``source``/``catalog``/``schema``/``table`` plus the canonical ``resource``
  (spec 0010 §4/plan §2); dictionary keys keep the legacy unambiguous table
  names, and a same-source name collision (same table name in distinct
  schemas) keys those tables by their canonical resource instead — consumers
  use the identity fields, never parse display names or keys.

- ``min/max/avg/std/q25/q50/q75`` come from DuckDB ``SUMMARIZE``; some render
  as strings, and avg/std/quantiles are ``null`` for non-numeric columns.
- ``top_values``/``top_value_share`` appear only when ``1 < distinct_count <=
  20`` — the low-cardinality distribution view. A dominant ``top_value_share``
  (e.g. ``orders.currency`` ≈ 87% USD vs a 2-row
  ``currency_conversion_rate`` lookup) is the distribution spike the authoring
  agent cross-reads against the seed notes; ``null_count``/
  ``null_ratio`` are the corresponding null-spike surface (ratio 0–1,
  normalized from SUMMARIZE's 0–100 ``null_percentage``).
- Heuristics: PK candidate = no nulls and ``distinct_count == row_count``.
  FK candidate = ``*_id`` name-match to another table (singular/plural) +
  compatible type + a verified ``match_ratio`` (share of values found in the
  target's primary-key candidate; 0.0-ratio guesses are dropped). A table's
  own PK candidate is never an FK candidate.
- Table/column order is deterministic; ``top_values`` is sorted by count desc.

All queries are built through DuckDB's relation API (``con.table`` /
``rel.select`` / ``rel.aggregate``), which escapes identifiers internally, so
no SQL text is ever assembled from data; the one ``SUMMARIZE`` statement
interpolates only allowlisted catalog identifiers.

CLI::

    python -m ariadne.profiler --db DB   # prints JSON + writes profile.json
    python -m ariadne.profiler --db examples/retail-demo/data/demo.db --out other.json
    python -m ariadne.profiler --db examples/retail-demo/data/demo.db --no-out        # stdout only
    python -m ariadne.profiler --sources ariadne.yaml --no-out   # every registry source
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.execution import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    DuckDBExecution,
)
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    Registry,
    default_registry_path,
    implicit_registry,
    load_registry,
)

TOP_VALUES_MAX_CARDINALITY = 20
TOP_VALUES_LIMIT = 10


class ProfilingPayloadExceeded(ValueError):
    """The measured profile exceeds the operator's profiling payload ceiling
    (spec0035 §8): nothing was returned as complete, no value was clipped and
    no required field omitted — narrow the selector, reduce cardinality or
    request an explicit smaller sample."""


class PayloadBound:
    """One operator payload ceiling over the COMPLETE serialized profile
    value (spec0035 §8): variable-size statistics are guarded BEFORE any
    unrestricted transfer into Python, measured fragments are accounted
    incrementally so oversize refuses early, and one exact final measurement
    covers the complete value in its actual JSON/UTF-8 representation and
    escaping. Refusal is explicit — never clipping, omission, or a prefix
    called complete."""

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(
                f"the profiling payload bound must be a positive integer, got {limit!r}"
            )
        self.limit = limit
        self.used = 0

    @staticmethod
    def _size(value) -> int:
        # The ACTUAL existing serialization escaping (spec0035 §8): the
        # authoring CLI prints the inputs result with json.dumps DEFAULTS
        # (ensure_ascii=True, authoring_cli.py) — accounting must match that
        # representation, never a smaller encoding.
        return len(json.dumps(value).encode("utf-8"))

    def guard_stat(self, size: int | None, what: str) -> None:
        """Pre-transfer guard: one variable-size statistic serialized longer
        than the WHOLE ceiling can never fit — refuse before it transfers.
        A VARCHAR character length undercounts escaped UTF-8 bytes, so this
        is a conservative pre-check against gross transfers; the exact final
        measurement below still governs."""
        if size is not None and size > self.limit:
            raise ProfilingPayloadExceeded(
                f"a {what} statistic serializes to {size} characters, over the whole "
                f"{self.limit}-byte profiling payload ceiling (spec0035 §8) — narrow "
                "the selector, reduce column cardinality, or request an explicit "
                "sample; nothing was returned as complete"
            )

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def guard_remaining(self, lower_bound_bytes: int) -> None:
        """Pre-fetch bound against the REMAINING shared budget: the table's
        min/max character lengths are a guaranteed LOWER bound of their
        escaped serialized size (escaping never shrinks a string), so
        exceeding the remaining budget here means the complete value can
        never fit — refuse before any variable-size statistic transfers.
        A lower bound can never reject a fitting profile; the exact final
        measurement still governs."""
        if self.used + lower_bound_bytes > self.limit:
            raise ProfilingPayloadExceeded(
                f"the table's variable-size statistics need at least {lower_bound_bytes} "
                f"serialized bytes but only {self.remaining} remain of the "
                f"{self.limit}-byte profiling payload ceiling (spec0035 §8) — narrow "
                "the selector or request an explicit sample; nothing was transferred"
            )

    def add(self, fragment) -> None:
        """Account one measured fragment incrementally (early refusal): the
        fragment sum undercounts container overhead, so a fragment-based
        refusal implies the complete value is over the ceiling too."""
        self.used += self._size(fragment)
        if self.used > self.limit:
            raise ProfilingPayloadExceeded(
                f"the measured profile exceeded the {self.limit}-byte profiling payload "
                "ceiling (spec0035 §8) while collecting statistics — narrow the "
                "selector or request an explicit sample; nothing was returned as "
                "complete"
            )

    def check_complete(self, value) -> None:
        """The authoritative exact measurement of the COMPLETE profile value."""
        size = self._size(value)
        if size > self.limit:
            raise ProfilingPayloadExceeded(
                f"the complete profile payload is {size} bytes, over the "
                f"{self.limit}-byte profiling ceiling (spec0035 §8) — narrow the "
                "selector or request an explicit sample; nothing was returned as "
                "complete"
            )


def _guard(budget, con):
    """The budget's per-statement interrupt guard, or a no-op context when no
    budget is set (the trusted operator CLI route keeps its exact contract)."""
    return budget.guard(con) if budget is not None else nullcontext()

# SQLite storage classes surface as these types through the scanner; keys may
# reference across the numeric family (INTEGER <-> BIGINT etc.).
_NUMERIC_TYPES = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "FLOAT",
        "DOUBLE",
        "REAL",
        "DECIMAL",
    }
)


def _jsonable(value):
    """Make SUMMARIZE's heterogeneous scalars JSON-safe (Decimals, dates, blobs)."""
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value)


def _q(identifier: str) -> str:
    """Quote a SQL identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def _sql_ref(ref: str) -> str:
    """The builder's plain dotted ``ref`` as a SQL-qualified prefix. The
    builder emits ``<alias>.<schema>`` for attaches (schema-only for file
    views); the alias is everything before the FIRST dot — a schema may
    itself contain dots and is quoted as ONE identifier, so
    ``warehouse.sales.west`` renders ``"warehouse"."sales.west"`` (the
    table name is quoted separately by the caller)."""
    alias, dot, schema = ref.partition(".")
    return f"{_q(alias)}.{_q(schema)}" if dot else _q(ref)


def _numeric(type_name: str) -> bool:
    return type_name.split("(")[0].upper() in _NUMERIC_TYPES


# Integer and binary-float families (K3 issue #43): exact-name equality and
# widening WITHIN a family compare without lossy coercion; anything across
# families (VARCHAR vs numeric, numeric vs timestamp, ...) does not.
_INTEGER_TYPES = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
    }
)
_FLOAT_TYPES = frozenset({"FLOAT", "DOUBLE", "REAL"})


def types_compatible(left: str, right: str) -> bool:
    """Whether two column types may be compared as identifiers WITHOUT lossy
    coercion (spec 0010 §7, plan §2): exact type names, or a widening within
    the integer/binary-float family. A string column beside a numeric column
    is NEVER compatible — string identifier equivalence is not inferred from
    numeric casts."""
    left, right = left.split("(")[0].upper(), right.split("(")[0].upper()
    if left == right:
        return True
    if left in _INTEGER_TYPES and right in _INTEGER_TYPES:
        return True
    return left in _FLOAT_TYPES and right in _FLOAT_TYPES


def _allowlisted(cols_by_table: dict[str, list[tuple[str, str]]]) -> set[str]:
    """Every table and column name the source actually contains (from the
    builder's catalog — DuckDB cannot parameterize identifiers, so membership
    in this set is asserted before any name is used). The set carries the
    real table names AND the profile display keys (a same-source name
    collision keys those tables by their canonical resource, plan §2), so
    both spellings pass the membership assertion."""
    names = set(cols_by_table)
    for cols in cols_by_table.values():
        names.update(name for name, _ in cols)
    return names


def _table_rel(con: duckdb.DuckDBPyConnection, ref: str, table: str, allowed: set[str]):
    if table not in allowed:
        raise ValueError(f"identifier not present in the catalog: {table!r}")
    # con.table() cannot bind schema-qualified views; a plain SELECT through
    # con.sql resolves identically for attaches and views (read-only relation).
    return con.sql(f"SELECT * FROM {_sql_ref(ref)}.{_q(table)}")


def _column_rel(rel, column: str, allowed: set[str]):
    """One column projected onto a fixed alias so every downstream expression
    string is a static literal."""
    if column not in allowed:
        raise ValueError(f"identifier not present in the catalog: {column!r}")
    return rel.select(_q(column) + " AS __profile_value")


def _profile_table(
    con: duckdb.DuckDBPyConnection,
    ref: str,
    table: str,
    cols: list[tuple[str, str]],
    allowed: set[str],
    sampled: bool = False,
    budget=None,
    payload: PayloadBound | None = None,
) -> tuple[int, list[str], dict]:
    """Return (row_count, pk_candidates, column profiles); ``cols`` comes from
    the builder's catalog (name, type) pairs in ordinal order. With a K3
    ``budget`` every statement runs under the shared interrupt watchdog
    (spec0035 §8); with a ``payload`` bound, variable-size statistics are
    guarded server-side BEFORE transfer and the measured table fragment is
    accounted incrementally — oversize refuses, never clips."""
    names = [c[0] for c in cols]
    rel = _table_rel(con, ref, table, allowed)

    with _guard(budget, con):
        row_count = rel.aggregate("COUNT(*) AS n").fetchall()[0][0]
    counts: dict[str, tuple[int, int]] = {}
    for name in names:
        with _guard(budget, con):
            row = (
                _column_rel(rel, name, allowed)
                .aggregate("COUNT(__profile_value) AS nn, COUNT(DISTINCT __profile_value) AS d")
                .fetchall()
            )
        counts[name] = (row[0][0], row[0][1])  # (non_null, distinct)

    pk_candidates = (
        []
        if sampled
        else [
            name
            for name in names
            if row_count > 0 and counts[name][0] == row_count and counts[name][1] == row_count
        ]
    )

    # SUMMARIZE re-executes per fetch: with a payload bound, the guard's
    # length aggregate runs server-side FIRST on the SAME summarize relation
    # (two integers transfer, never the values themselves) so oversized
    # min/max statistics refuse before any unrestricted transfer (spec0035
    # §8) — the relation is then fetched as before; both executions stay
    # under the shared time budget.
    summarize_rel = con.sql(f"SUMMARIZE {_sql_ref(ref)}.{_q(table)}")
    with _guard(budget, con):
        if payload is not None:
            # Per-stat maxima bound single huge stats; the table-wide SUM is
            # a guaranteed LOWER bound of the whole min/max materialization
            # and is checked against the REMAINING shared budget BEFORE the
            # fetch — an entire wide table's statistics refuse before any of
            # them transfer (spec0035 §8), never only after collecting.
            lengths = summarize_rel.aggregate(
                "max(length(CAST(min AS VARCHAR))) AS __profile_min_len, "
                "max(length(CAST(max AS VARCHAR))) AS __profile_max_len, "
                "sum(length(CAST(min AS VARCHAR))) AS __profile_min_sum, "
                "sum(length(CAST(max AS VARCHAR))) AS __profile_max_sum"
            ).fetchall()[0]
            payload.guard_stat(lengths[0], "min")
            payload.guard_stat(lengths[1], "max")
            payload.guard_remaining(int(lengths[2] or 0) + int(lengths[3] or 0))
        fields = [d[0] for d in summarize_rel.description]
        summarize = {
            row[0]: dict(zip(fields, row, strict=True)) for row in summarize_rel.fetchall()
        }

    columns: dict[str, dict] = {}
    for name, type_name in cols:
        s = summarize[name]
        non_null, distinct = counts[name]
        # SUMMARIZE reports null_percentage None over an EMPTY table (no rows
        # to measure): the paired counts are both 0, so the ratio is 0.0 —
        # never a crash on the missing aggregate (issue #41 fixture regression)
        null_percentage = s["null_percentage"]
        entry = {
            "type": type_name,
            "null_count": row_count - non_null,
            "null_ratio": (float(null_percentage) / 100.0) if null_percentage is not None else 0.0,
            "distinct_count": distinct,
            "unique_ratio": (distinct / row_count) if row_count else 0.0,
            "approx_unique": s["approx_unique"],
            "min": _jsonable(s["min"]),
            "max": _jsonable(s["max"]),
            "avg": _jsonable(s["avg"]),
            "std": _jsonable(s["std"]),
            "q25": _jsonable(s["q25"]),
            "q50": _jsonable(s["q50"]),
            "q75": _jsonable(s["q75"]),
            "pk_candidate": name in pk_candidates,
        }
        if 1 < distinct <= TOP_VALUES_MAX_CARDINALITY and row_count > 0:
            with _guard(budget, con):
                if payload is not None:  # pre-transfer value-size guard (spec0035 §8)
                    biggest = _column_rel(rel, name, allowed).aggregate(
                        "max(length(CAST(__profile_value AS VARCHAR))) AS __profile_vlen"
                    ).fetchall()[0][0]
                    payload.guard_stat(biggest, f"top value of {name!r}")
                    payload.guard_remaining(int(biggest or 0))
                top = (
                    _column_rel(rel, name, allowed)
                    .aggregate("__profile_value, COUNT(*) AS __profile_c")
                    .order("__profile_c DESC")
                    .limit(TOP_VALUES_LIMIT)
                    .fetchall()
                )
            entry["top_values"] = [
                {"value": _jsonable(value), "count": count} for value, count in top
            ]
            entry["top_value_share"] = top[0][1] / row_count
        columns[name] = entry
    return row_count, pk_candidates, columns


def _fk_candidates(
    con: duckdb.DuckDBPyConnection,
    ref: str,
    table: str,
    cols: list[tuple[str, str]],
    non_null: dict[str, int],
    pk_candidates: list[str],
    targets_by_name: dict[str, list[dict]],
    allowed: set[str],
    budget=None,
) -> list[dict]:
    """``*_id`` columns whose name resolves to another table's PK, type-checked
    and verified by containment (``match_ratio``). A candidate target name
    resolves through the catalog entry's EXPLICIT identities to the target's
    OWN qualified ref — never the originating table's (``b.orders.customer_id``
    must not look for ``customers`` under ``b``): a name matching no table or
    SEVERAL tables (same name in distinct schemas) is skipped, never guessed
    (issue #41)."""
    table_rel = _table_rel(con, ref, table, allowed)
    candidates: list[dict] = []
    for name, type_name in cols:
        if name in pk_candidates or not name.endswith("_id") or len(name) <= 3:
            continue
        base = name[:-3]
        for target_table in (base, base + "s", base + "es"):
            resolutions = targets_by_name.get(target_table) or []
            if len(resolutions) != 1:
                continue  # nonexistent or ambiguous target name: never guessed
            target = resolutions[0]
            target_pks = target["pks"]
            if not target_pks:
                continue
            # Prefer the conventional "id", then a same-named column, then the first.
            target_col = min(target_pks, key=lambda c: (c != "id", c != name))
            if target_table == table and target_col == name:
                continue  # a column referencing itself is its own PK, not an FK
            target_type = [(c, t) for c, t in target["cols"] or [] if c == target_col]
            if not target_type:
                continue
            target_is_numeric = _numeric(type_name) and _numeric(target_type[0][1])
            if not target_is_numeric and type_name != target_type[0][1]:
                continue
            src = _column_rel(table_rel, name, allowed).set_alias("s")
            tgt_rel = _table_rel(con, target["ref"], target_table, allowed)
            tgt = _column_rel(tgt_rel, target_col, allowed).set_alias("t")
            with _guard(budget, con):
                orphans = (
                    src.join(tgt, "s.__profile_value = t.__profile_value", "left")
                    .aggregate(
                        "COUNT(*) FILTER (WHERE t.__profile_value IS NULL"
                        " AND s.__profile_value IS NOT NULL)"
                    )
                    .fetchall()[0][0]
                )
            n = non_null[name]
            if n == 0:
                continue
            match_ratio = 1.0 - orphans / n
            if match_ratio <= 0.0:
                continue  # unverifiable name coincidence
            candidates.append(
                {
                    "column": name,
                    "references_table": target_table,
                    "references_column": target_col,
                    "match_ratio": match_ratio,
                }
            )
    candidates.sort(key=lambda fk: (-fk["match_ratio"], fk["column"], fk["references_table"]))
    return candidates


def _profile_source(
    con: duckdb.DuckDBPyConnection, entry: dict, *, sample_rows: int | None = None,
    budget=None, payload: PayloadBound | None = None,
) -> dict:
    """Profile every table of one builder-catalog source: attaches address
    tables as ``<catalog>.<schema>.<table>``, file views as
    ``<schema>.<table>`` — both are the per-table ``ref`` the builder emits.
    Profile dictionary keys keep the legacy unambiguous table names; a
    same-source name collision (same table name in distinct schemas) keys
    those tables by their canonical ``resource`` instead, and every table
    value carries the explicit identity tuple plus resource (plan §2) so
    consumers never parse display names."""
    counts = Counter(table["name"] for table in entry["tables"])
    cols_by_table: dict[str, list[tuple[str, str]]] = {}
    refs: dict[str, str] = {}
    identity: dict[str, dict] = {}
    for table in entry["tables"]:
        key = table["resource"] if counts[table["name"]] > 1 else table["name"]
        cols_by_table[key] = [(col["name"], col["type"]) for col in table["columns"]]
        refs[key] = table.get("ref") or entry["name"]
        identity[key] = {
            "source": table.get("source"),
            "catalog": table.get("catalog"),
            "schema": table.get("schema"),
            "table": table["name"],
            "resource": table.get("resource"),
        }
    allowed = _allowlisted(cols_by_table) | {
        identity[key]["table"] for key in cols_by_table
    }  # real table names too: a same-name collision keys the profile by resource
    tables: dict[str, dict] = {}
    pk_by_table: dict[str, list[str]] = {}
    for key in cols_by_table:  # builder catalog order == information_schema order
        cols = cols_by_table[key]
        row_count, pk_candidates, columns = _profile_table(
            con,
            refs[key],
            identity[key]["table"],
            cols,
            allowed,
            sampled=sample_rows is not None,
            budget=budget,
            payload=payload,
        )
        pk_by_table[key] = pk_candidates
        # DEBIT each table's measured statistics AS COLLECTED (spec0035 §8):
        # first-pass statistics never accumulate across the source outside
        # the shared payload budget — the debit happens before the NEXT
        # table is measured. PK metadata stays available for the FK phase
        # below; FK fragments are debited separately so nothing double
        # counts and a fitting profile is never rejected.
        tables[key] = {
            "row_count": row_count,
            "primary_key_candidates": pk_candidates,
            "columns": columns,
            **identity[key],
        }
        if sample_rows is not None:
            tables[key].update(sampled=True, sample_limit=sample_rows)
        if payload is not None:
            payload.add(tables[key])
    # FK candidate targets resolve BY NAME through the entry's explicit
    # identities — each resolution carries the target's OWN qualified ref
    # (issue #41): a name held by no table or several tables (same name in
    # distinct schemas) is never guessed
    targets_by_name: dict[str, list[dict]] = {}
    for key in cols_by_table:
        targets_by_name.setdefault(identity[key]["table"], []).append(
            {"ref": refs[key], "pks": pk_by_table[key] or [], "cols": cols_by_table[key]}
        )
    for key in cols_by_table:
        cols = cols_by_table[key]
        columns = tables[key]["columns"]
        row_count = tables[key]["row_count"]
        non_null = {n: row_count - col["null_count"] for n, col in columns.items()}
        # the FK fragment is the only later addition: debited separately, so
        # stats + FK fragments sum to the complete value without double
        # counting (spec0035 §8 incremental accounting)
        tables[key]["foreign_key_candidates"] = (
            []
            if sample_rows is not None
            else _fk_candidates(
                con,
                refs[key],
                identity[key]["table"],
                cols,
                non_null,
                pk_by_table[key],
                targets_by_name,
                allowed,
                budget=budget,
            )
        )
        if payload is not None:
            payload.add(tables[key]["foreign_key_candidates"])
    return {"name": entry["name"], "type": entry["type"], "tables": tables}


def profile(
    db_path: str | Path | None = None,
    *,
    sources_path: str | Path | None = None,
    registry: Registry | None = None,
    sample_rows: int | None = None,
    selector: tuple[str, str] | None = None,
    budget=None,
    payload_bytes: int | None = None,
) -> dict:
    """Profile every table of every source, or one exact ``(source, table)``
    selector (shapes documented in the module docstring): the legacy
    single-sqlite call via ``db_path``, the full registry via ``sources_path``
    (ADR-0010, shared connection builder), or an already-validated
    :class:`ariadne.sources.Registry` via ``registry`` (the Git authoring
    route's APPROVED resolved identity, issue #35/G3 — no registry file exists
    for a candidate commit). Exactly one of the three.

    With a K3 :class:`ariadne.execution.DeadlineBudget` as ``budget``, the
    approved connection/catalog setup, sample materialization, statistics and
    FK statements all draw down ONE shared interruptible time budget
    (spec0035 §8); expiry is an explicit :class:`DeadlineExhausted` refusal —
    never a partial profile claimed complete. With ``payload_bytes``, the
    complete serialized profile value must fit the operator ceiling:
    variable-size statistics are guarded before transfer, fragments accounted
    incrementally, and oversize raises :class:`ProfilingPayloadExceeded`
    without clipping. Both default to None — the trusted operator CLI keeps
    its exact historical unbounded contract."""
    if sample_rows is not None and (not isinstance(sample_rows, int) or sample_rows < 1):
        raise ValueError("sample_rows must be a positive integer")
    if budget is not None and not (hasattr(budget, "guard") and hasattr(budget, "remaining")):
        raise ValueError("budget must be an ariadne.execution.DeadlineBudget")
    payload = PayloadBound(payload_bytes) if payload_bytes is not None else None
    if selector is not None and (
        not isinstance(selector, tuple)
        or len(selector) != 2
        or any(not isinstance(value, str) or not value for value in selector)
    ):
        raise ValueError("selector must be an exact (source, table) pair")
    if registry is not None:
        if sources_path is not None or db_path is not None:
            raise ValueError("profile takes one of db_path, sources_path or registry")
        reg = registry
    elif sources_path is not None:
        reg = load_registry(sources_path)
    elif db_path is not None:
        reg = implicit_registry(db_path)
        if not Path(db_path).is_file():
            raise FileNotFoundError(f"database not found: {db_path}")
    else:
        raise ValueError("profile requires db_path, sources_path or registry")
    if selector is not None and selector[0] not in {source.name for source in reg.sources}:
        raise ValueError("selector source is not present in the approved registry")
    execution = DuckDBExecution(reg, budget=budget)
    con, catalog = execution.con, execution.catalog
    try:
        if selector is not None:
            matches = [
                (entry, table)
                for entry in catalog
                if entry["name"] == selector[0]
                for table in entry["tables"]
                if table["name"] == selector[1]
            ]
            if len(matches) != 1:
                raise ValueError("selector must identify exactly one approved table")
            entry, table = matches[0]
            catalog = [{**entry, "tables": [table]}]
        if sample_rows is not None:
            sample_index = 0
            for entry in catalog:
                for table in entry["tables"]:
                    # one sample schema PER TABLE: same-named tables in
                    # distinct schemas would collide inside one schema
                    schema = f"__ariadne_sample_{entry['name']}_{sample_index}"
                    sample_index += 1
                    name = _q(table["name"])
                    with _guard(budget, con):
                        con.execute(f"CREATE SCHEMA {schema}")
                        con.execute(
                            f"CREATE TABLE {schema}.{name} AS SELECT * FROM "
                            f"{_sql_ref(table['ref'])}.{name} LIMIT {sample_rows}"
                        )
                    table["ref"] = schema
        sources = [
            _profile_source(con, entry, sample_rows=sample_rows, budget=budget, payload=payload)
            for entry in catalog
        ]
    finally:
        execution.close()
    if registry is not None:
        result: dict = {"sources": sources}  # the approved identity has no registry file
    elif sources_path is not None:
        result = {"sources_path": str(sources_path), "sources": sources}
    else:
        (only,) = sources  # the legacy shape: one sqlite source, historical keys
        result = {"db_path": str(db_path), "dialect": "sqlite", "tables": only["tables"]}
    if payload is not None:  # the COMPLETE profile value must fit (spec0035 §8)
        payload.check_complete(result)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.profiler",
        description="Profile a database for the authoring agent (writes profile.json).",
    )
    parser.add_argument("--db", default=None, help="path to the SQLite database")
    parser.add_argument(
        "--sources",
        default=None,
        help="source registry YAML (ADR-0010; default: ./ariadne.yaml only when "
        "neither --sources nor --db is given)",
    )
    parser.add_argument("--out", default="profile.json", help="output path (default: profile.json)")
    parser.add_argument("--no-out", action="store_true", help="print to stdout only, write no file")
    args = parser.parse_args(argv)

    sources_path = default_registry_path(args.sources, args.db)
    if args.db is None and sources_path is None:
        parser.error("one of --db or --sources is required")
    text = json.dumps(profile(args.db, sources_path=sources_path), indent=2)
    print(text)
    if not args.no_out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
