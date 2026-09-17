"""Database profiler: DuckDB SUMMARIZE + PK/FK heuristics over the source registry (ticket #3).

Reads every source of the ADR-0010 registry (``ariadne.yaml``) — or the legacy
single SQLite file (``--db``) — read-only through the shared connection builder
(:mod:`ariadne.sources`), profiles every table, and emits a JSON-serializable
dict. This output is the input contract of the authoring agent
(``ariadne.author``, ticket #4), which combines it with ``data/seed_notes.md``;
the profiler surfaces statistics only — business rules live in the seed notes,
never here.

Output shape: the legacy single-sqlite call keeps the historical contract
(``profile(db_path) -> dict``, also written by the CLI)::

    {
      "db_path": "data/demo.db",
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

    python -m ariadne.profiler --db data/demo.db                 # prints JSON + writes profile.json
    python -m ariadne.profiler --db data/demo.db --out other.json
    python -m ariadne.profiler --db data/demo.db --no-out        # stdout only
    python -m ariadne.profiler --sources ariadne.yaml --no-out   # every registry source
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    build_connection,
    default_registry_path,
    implicit_registry,
    load_registry,
)

TOP_VALUES_MAX_CARDINALITY = 20
TOP_VALUES_LIMIT = 10

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


def _numeric(type_name: str) -> bool:
    return type_name.split("(")[0].upper() in _NUMERIC_TYPES


def _allowlisted(cols_by_table: dict[str, list[tuple[str, str]]]) -> set[str]:
    """Every table and column name the source actually contains (from the
    builder's catalog — DuckDB cannot parameterize identifiers, so membership
    in this set is asserted before any name is used)."""
    return set(cols_by_table) | {name for cols in cols_by_table.values() for name, _ in cols}


def _table_rel(con: duckdb.DuckDBPyConnection, ref: str, table: str, allowed: set[str]):
    if table not in allowed:
        raise ValueError(f"identifier not present in the catalog: {table!r}")
    # con.table() cannot bind schema-qualified views; a plain SELECT through
    # con.sql resolves identically for attaches and views (read-only relation).
    return con.sql(f"SELECT * FROM {ref}.{_q(table)}")


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
) -> tuple[int, list[str], dict]:
    """Return (row_count, pk_candidates, column profiles); ``cols`` comes from
    the builder's catalog (name, type) pairs in ordinal order."""
    names = [c[0] for c in cols]
    rel = _table_rel(con, ref, table, allowed)

    row_count = rel.aggregate("COUNT(*) AS n").fetchall()[0][0]
    counts: dict[str, tuple[int, int]] = {}
    for name in names:
        row = _column_rel(rel, name, allowed).aggregate(
            "COUNT(__profile_value) AS nn, COUNT(DISTINCT __profile_value) AS d"
        ).fetchall()
        counts[name] = (row[0][0], row[0][1])  # (non_null, distinct)

    pk_candidates = [
        name
        for name in names
        if row_count > 0 and counts[name][0] == row_count and counts[name][1] == row_count
    ]

    cur = con.sql(f"SUMMARIZE {ref}.{_q(table)}")
    fields = [d[0] for d in cur.description]
    summarize = {row[0]: dict(zip(fields, row, strict=True)) for row in cur.fetchall()}

    columns: dict[str, dict] = {}
    for name, type_name in cols:
        s = summarize[name]
        non_null, distinct = counts[name]
        entry = {
            "type": type_name,
            "null_count": row_count - non_null,
            "null_ratio": float(s["null_percentage"]) / 100.0,
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
    pk_by_table: dict[str, list[str]],
    allowed: set[str],
    cols_by_table: dict[str, list[tuple[str, str]]],
) -> list[dict]:
    """``*_id`` columns whose name resolves to another table's PK, type-checked
    and verified by containment (``match_ratio``)."""
    table_rel = _table_rel(con, ref, table, allowed)
    candidates: list[dict] = []
    for name, type_name in cols:
        if name in pk_candidates or not name.endswith("_id") or len(name) <= 3:
            continue
        base = name[:-3]
        for target_table in (base, base + "s", base + "es"):
            target_pks = pk_by_table.get(target_table)
            if not target_pks:
                continue
            # Prefer the conventional "id", then a same-named column, then the first.
            target_col = min(target_pks, key=lambda c: (c != "id", c != name))
            if target_table == table and target_col == name:
                continue  # a column referencing itself is its own PK, not an FK
            target_type = [
                (c, t) for c, t in cols_by_table.get(target_table) or [] if c == target_col
            ]
            if not target_type:
                continue
            target_is_numeric = _numeric(type_name) and _numeric(target_type[0][1])
            if not target_is_numeric and type_name != target_type[0][1]:
                continue
            src = _column_rel(table_rel, name, allowed).set_alias("s")
            tgt_rel = _table_rel(con, ref, target_table, allowed)
            tgt = _column_rel(tgt_rel, target_col, allowed).set_alias("t")
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


def _profile_source(con: duckdb.DuckDBPyConnection, entry: dict) -> dict:
    """Profile every table of one builder-catalog source: attaches address
    tables as ``<catalog>.<schema>.<table>``, file views as
    ``<schema>.<table>`` — both are the per-table ``ref`` the builder emits."""
    cols_by_table = {
        table["name"]: [(col["name"], col["type"]) for col in table["columns"]]
        for table in entry["tables"]
    }
    refs = {table["name"]: table.get("ref") or entry["name"] for table in entry["tables"]}
    allowed = _allowlisted(cols_by_table)
    tables: dict[str, dict] = {}
    pk_by_table: dict[str, list[str]] = {}
    profiles: dict[str, tuple] = {}
    for name in cols_by_table:  # builder catalog order == information_schema order
        cols = cols_by_table[name]
        row_count, pk_candidates, columns = _profile_table(
            con, refs[name], name, cols, allowed
        )
        profiles[name] = (cols, row_count, pk_candidates, columns)
        pk_by_table[name] = pk_candidates
    for name, (cols, row_count, pk_candidates, columns) in profiles.items():
        non_null = {n: row_count - col["null_count"] for n, col in columns.items()}
        tables[name] = {
            "row_count": row_count,
            "primary_key_candidates": pk_candidates,
            "foreign_key_candidates": _fk_candidates(
                con,
                refs[name],
                name,
                cols,
                non_null,
                pk_candidates,
                pk_by_table,
                allowed,
                cols_by_table,
            ),
            "columns": columns,
        }
    return {"name": entry["name"], "type": entry["type"], "tables": tables}


def profile(db_path: str | Path | None = None, *, sources_path: str | Path | None = None) -> dict:
    """Profile every table of every source (shapes documented in the module
    docstring): the legacy single-sqlite call via ``db_path``, the full
    registry via ``sources_path`` (ADR-0010, shared connection builder)."""
    if sources_path is not None:
        registry = load_registry(sources_path)
    elif db_path is not None:
        registry = implicit_registry(db_path)
        if not Path(db_path).is_file():
            raise FileNotFoundError(f"database not found: {db_path}")
    else:
        raise ValueError("profile requires db_path or sources_path")
    con, catalog = build_connection(registry)
    try:
        sources = [_profile_source(con, entry) for entry in catalog]
    finally:
        con.close()
    if sources_path is not None:
        return {"sources_path": str(sources_path), "sources": sources}
    (only,) = sources  # the legacy shape: one sqlite source, historical keys
    return {"db_path": str(db_path), "dialect": "sqlite", "tables": only["tables"]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.profiler",
        description="Profile a database for the authoring agent (writes profile.json).",
    )
    parser.add_argument("--db", default=None, help="path to the SQLite database")
    parser.add_argument(
        "--sources",
        default=None,
        help="source registry YAML (ADR-0010; default: ./ariadne.yaml when it "
        "declares sources, else --db)",
    )
    parser.add_argument("--out", default="profile.json", help="output path (default: profile.json)")
    parser.add_argument("--no-out", action="store_true", help="print to stdout only, write no file")
    args = parser.parse_args(argv)

    sources_path = default_registry_path(args.sources)
    if args.db is None and sources_path is None:
        parser.error("one of --db or --sources is required")
    text = json.dumps(profile(args.db, sources_path=sources_path), indent=2)
    print(text)
    if not args.no_out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
