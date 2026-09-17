"""Declarative source registry + the shared DuckDB connection builder (ADR-0010;
spec rev 9 §8.20).

``ariadne.yaml`` (scaffolded by ``ariadne-init``) declares every source in one
``sources:`` block; :func:`build_connection` produces THE DuckDB session for
serve/author/validate/profiler, so every source is addressable as
``<source>.<table>`` and the compiler, grain guard, and audit operate unchanged
over the unified connection.

Types (``type:``):

- ``sqlite``   — ``ATTACH path AS name (TYPE SQLITE, READ_ONLY)``
- ``csv`` / ``json`` / ``parquet`` — one view ``name.<table>`` over
  ``read_csv_auto`` / ``read_json_auto`` / ``read_parquet(path)``; globs become
  one view per registry entry (name it with ``table:``); remote ``https://`` /
  ``s3://`` paths load the ``httpfs`` extension first
- ``delta``    — ``LOAD delta`` + view over ``delta_scan(path)``
- ``iceberg``  — ``LOAD iceberg`` + view over ``iceberg_scan(path)``
- ``ducklake`` — ``LOAD ducklake`` + ``ATTACH path AS name (TYPE DUCKLAKE, READ_ONLY)``
- ``postgres`` — ``LOAD postgres`` + ``ATTACH <dsn> AS name (TYPE POSTGRES, READ_ONLY)``

Credentials are env-var references only (``connection_env: <NAME>``), resolved
at runtime and never committed; a registry carrying an inline connection string
is a validation error naming ADR-0010. The legacy ``--db <file>`` argument is
the single-sqlite shorthand wrapped by :func:`implicit_registry` (catalog
``demo`` — the authoring contract's catalog name).

The statement sequence is deterministic: :func:`plan` emits the extension
``LOAD`` statements first (deduplicated, in registry order) followed by the
per-source DDL, and :func:`build_connection` executes exactly that sequence,
then reads each source's tables/columns from ``information_schema`` into a
catalog (cheap enumeration only — no profiling here).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

# Slug: lowercase, starts with a letter; used verbatim as catalog/schema name.
NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Strict entry schema: no freestyle keys — a typo'd or smuggled key (dsn:,
# connection_string:, ...) must fail loudly instead of passing silently.
SOURCE_KEYS = frozenset({"name", "type", "path", "connection_env", "table", "read_only"})
# A connection string is a credential (ADR-0010): rejected under ANY key.
DSN_RE = re.compile(r"postgres(?:ql)?://")
# URI-scheme prefix (ducklake:, https://, s3://, ...): never cwd-relative.
_URI_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")
# scheme://user:password@host — the password NEVER survives into an error.
_DSN_PASSWORD_RE = re.compile(r"(//[^\s/@:]+:)([^\s/@]+)(@)")

SOURCE_TYPES = (
    "sqlite",
    "csv",
    "json",
    "parquet",
    "delta",
    "iceberg",
    "ducklake",
    "postgres",
)
ATTACH_TYPES = frozenset({"sqlite", "ducklake", "postgres"})
FILE_TYPES = frozenset({"csv", "json", "parquet"})
GLOB_CHARS = frozenset("*?[")
REMOTE_PREFIXES = ("http://", "https://", "s3://", "s3a://", "s3n://")
READER = {"csv": "read_csv_auto", "json": "read_json_auto", "parquet": "read_parquet"}

# Legacy default resolution (all commands): ./ariadne.yaml when present.
DEFAULT_PATH = "ariadne.yaml"


@dataclass
class Source:
    """One validated registry entry."""

    name: str
    type: str
    path: str | None = None
    connection_env: str | None = None
    table: str | None = None
    read_only: bool = True


@dataclass
class Registry:
    """Validated registry: the sources plus where they came from.

    ``path`` is ``None`` for the implicit ``--db`` shorthand (single sqlite
    attach under the authoring contract's catalog name ``demo``)."""

    sources: list[Source]
    path: str | None = None


def default_registry_path(
    explicit: str | Path | None = None, db: str | Path | None = None
) -> Path | None:
    """``--sources``/``--db`` resolution shared by every command. An explicit
    flag ALWAYS wins: ``--sources`` selects that registry; ``--db`` selects the
    legacy single-sqlite shorthand and the ambient registry is IGNORED. The
    ambient ``./ariadne.yaml`` applies only when NEITHER flag is given. The
    scaffolded template (all comments, no ``sources:``) counts as absent, so
    ``--db`` keeps working for fresh projects; an UNPARSABLE registry is
    returned as-is so :func:`load_registry` raises the real error instead of
    hiding it."""
    if explicit:
        return Path(explicit)
    if db:
        return None
    candidate = Path(DEFAULT_PATH)
    if candidate.is_file():
        try:
            doc = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return candidate
        if doc.get("sources"):
            return candidate
    return None


def load_registry(path: str | Path = DEFAULT_PATH) -> Registry:
    """Parse and validate a source registry (ADR-0010). Raises ``ValueError``
    naming the offending entry for: a non-slug name, an unknown type, a missing
    ``path`` (file/attach types) or ``connection_env`` (postgres), an inline
    connection string (ADR-0010), a glob without an explicit ``table:``, or
    duplicate source names."""
    registry_path = Path(path)
    try:
        doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{registry_path}: not valid YAML: {exc}") from exc
    entries = doc.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError(
            f"{registry_path}: no 'sources:' entries (a commented template counts "
            "as absent — declare sources or use --db)"
        )
    sources: list[Source] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        sources.append(_source(registry_path, index, entry, seen))
    base = registry_path.parent.resolve()
    for src in sources:  # init.py's promise: paths are relative to THIS file
        if src.path:
            src.path = _resolve_against(base, src.path)
    return Registry(sources=sources, path=str(registry_path))


def implicit_registry(db_path: str | Path) -> Registry:
    """The legacy ``--db`` shorthand as a one-source registry (catalog ``demo``)."""
    return Registry(sources=[Source(name="demo", type="sqlite", path=str(db_path))])


def _source(path: Path, index: int, entry: object, seen: set[str]) -> Source:
    where = f"{path}: sources[{index}]"
    if not isinstance(entry, dict):
        raise ValueError(f"{where}: entry is not a mapping")
    name = entry.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError(
            f"{where}: name {name!r} must be a lowercase slug (letters, digits, "
            "underscores; starting with a letter)"
        )
    if name in seen:
        raise ValueError(f"{where}: duplicate source name {name!r}")
    seen.add(name)
    source_type = entry.get("type")
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            f"{where}: unknown type {source_type!r}; expected one of {list(SOURCE_TYPES)}"
        )
    if "connection" in entry:  # ADR-0010: credentials never live in the registry
        raise ValueError(
            f"{where}: inline connection strings are rejected (ADR-0010): "
            "reference an environment variable with connection_env: <NAME>"
        )
    for key, value in entry.items():  # under ANY key, not just ``connection``
        if isinstance(value, str) and DSN_RE.match(value):
            raise ValueError(
                f"{where}: {key} carries an inline connection string (ADR-0010): "
                "reference an environment variable with connection_env: <NAME>"
            )
    unknown = sorted(set(entry) - SOURCE_KEYS)
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {unknown}; allowed: {sorted(SOURCE_KEYS)}"
        )
    connection_env = entry.get("connection_env")
    if source_type == "postgres":
        if not isinstance(connection_env, str) or not connection_env.strip():
            raise ValueError(
                f"{where}: type postgres requires connection_env: <NAME> (ADR-0010: "
                "credentials are environment-variable references, never inline)"
            )
        if "://" in connection_env or "=" in connection_env:
            raise ValueError(
                f"{where}: connection_env looks like an inline connection string "
                "(ADR-0010): give the NAME of the environment variable holding the DSN"
            )
        if entry.get("path"):
            raise ValueError(f"{where}: type postgres takes connection_env, not path")
        source = Source(
            name=name,
            type=source_type,
            connection_env=connection_env,
            read_only=_read_only(path, index, entry),
        )
    else:
        source_path = entry.get("path")
        if not isinstance(source_path, str) or not source_path.strip():
            raise ValueError(f"{where}: type {source_type} requires path")
        table = entry.get("table")
        if table is not None and (
            not isinstance(table, str) or not IDENTIFIER_RE.fullmatch(table)
        ):
            raise ValueError(f"{where}: table must be a plain identifier")
        if any(ch in source_path for ch in GLOB_CHARS):
            if source_type not in FILE_TYPES:
                raise ValueError(
                    f"{where}: glob paths are only valid for {sorted(FILE_TYPES)}"
                )
            if not table:
                raise ValueError(
                    f"{where}: a glob path needs an explicit table: name "
                    "(one view over the whole glob)"
                )
        source = Source(
            name=name,
            type=source_type,
            path=source_path,
            table=table,
            read_only=_read_only(path, index, entry),
        )
    return source


def _read_only(path: Path, index: int, entry: dict) -> bool:
    value = entry.get("read_only", True)
    if not isinstance(value, bool):
        raise ValueError(f"{path}: sources[{index}]: read_only must be a boolean")
    return value


def plan(registry: Registry, read_only: bool = True) -> tuple[list[str], list[str]]:
    """The exact statement sequence the builder executes, as pure text:
    ``(loads, statements)`` — extension ``LOAD``s first (deduplicated, registry
    order), then the per-source ATTACH/CREATE SCHEMA/CREATE VIEW DDL. This is
    the statement-construction test surface (ADR-0010 tiering): the builder
    adds nothing beyond executing these strings in order."""
    loads: list[str] = []
    statements: list[str] = []
    for src in registry.sources:
        suffix = ", READ_ONLY" if src.read_only and read_only else ""
        if src.type == "sqlite":
            statements.append(
                f"ATTACH '{_noquotes(_path(src))}' AS {src.name} (TYPE SQLITE{suffix})"
            )
        elif src.type == "ducklake":
            _want(loads, "ducklake")
            statements.append(
                f"ATTACH '{_noquotes(_path(src))}' AS {src.name} (TYPE DUCKLAKE{suffix})"
            )
        elif src.type == "postgres":
            _want(loads, "postgres")
            statements.append(
                f"ATTACH '{_noquotes(_resolve_dsn(src))}' AS {src.name} (TYPE POSTGRES{suffix})"
            )
        elif src.type == "delta":
            _want(loads, "delta")
            if _is_remote(src.path):
                _want(loads, "httpfs")
            statements.extend(_view_statements(src, "delta_scan"))
        elif src.type == "iceberg":
            _want(loads, "iceberg")
            if _is_remote(src.path):
                _want(loads, "httpfs")
            statements.extend(_view_statements(src, "iceberg_scan"))
        else:  # csv / json / parquet
            if _is_remote(src.path):
                _want(loads, "httpfs")
            statements.extend(_view_statements(src, READER[src.type]))
    return loads, statements


def build_connection(
    registry: Registry, read_only: bool = True
) -> tuple[duckdb.DuckDBPyConnection, list[dict]]:
    """The one DuckDB session for all commands (ADR-0010): executes
    :func:`plan` verbatim and returns ``(connection, catalog)``. The catalog
    lists, per source, its tables with columns where cheaply enumerable —
    ``information_schema`` for attaches, the same catalog for file views.
    Execution errors are re-raised with any postgres DSN redacted (DuckDB
    echoes the SQL text, so a failed ATTACH would leak credentials)."""
    loads, statements = plan(registry, read_only=read_only)
    secrets = [_resolve_dsn(src) for src in registry.sources if src.type == "postgres"]
    con = duckdb.connect()
    for extension in loads:
        con.execute(f"LOAD {extension}")
    for statement in statements:
        try:
            con.execute(statement)  # nosemgrep — plan() output, validated-registry inputs only
        except Exception as exc:
            exc.args = (_redact_all(str(exc), secrets),)
            raise
    return con, [_catalog_entry(con, src) for src in registry.sources]


def _redact(dsn: str) -> str:
    """``scheme://user:password@host/...`` -> ``scheme://user:***@host/...``
    (user and host may surface; the password never does)."""
    return _DSN_PASSWORD_RE.sub(r"\1***\3", dsn)


def _redact_all(message: str, secrets: list[str]) -> str:
    """Every known DSN redacted, plus a generic pass so no credentialed URL in
    a builder-raised error message ever carries a password."""
    for dsn in secrets:
        message = message.replace(dsn, _redact(dsn))
    return _DSN_PASSWORD_RE.sub(r"\1***\3", message)


def _want(loads: list[str], extension: str) -> None:
    """Extension LOADs happen once, idempotently, in registry order."""
    if extension not in loads:
        loads.append(extension)


def _noquotes(value: str) -> str:
    """ATTACH/scan literals take no bind parameters; a quote-bearing path is
    rejected outright instead of escaped into SQL text (profiler precedent).
    The value is never echoed — it may be a DSN carrying credentials."""
    if "'" in value:
        raise ValueError(
            "path/connection contains a quote character — rejected outright "
            "(ATTACH/scan literals take no bind parameters)"
        )
    return value


def _resolve_against(base: Path, raw: str) -> str:
    """Registry-relative paths resolve against the registry file's directory
    (the scaffold template's promise); absolute and URI-scheme paths
    (``https://``, ``s3://``, ``ducklake:``) pass through untouched."""
    if Path(raw).is_absolute() or _URI_SCHEME_RE.match(raw):
        return raw
    return str(base / raw)


def _path(src: Source) -> str:
    """The entry's path, narrowed (load_registry already validated presence —
    this guard keeps the type checker and any direct plan() caller honest)."""
    if not src.path:
        raise ValueError(f"source {src.name!r}: type {src.type} requires path")
    return src.path


def _is_remote(path: str | None) -> bool:
    return bool(path) and path.startswith(REMOTE_PREFIXES)


def _resolve_dsn(src: Source) -> str:
    """Resolve ``connection_env`` at runtime (ADR-0010); missing -> actionable
    error naming the variable."""
    if not src.connection_env:
        raise ValueError(f"source {src.name!r}: type postgres requires connection_env")
    dsn = os.environ.get(src.connection_env)
    if not dsn:
        raise ValueError(
            f"source {src.name!r}: environment variable {src.connection_env} is not "
            f"set (ADR-0010: postgres credentials resolve from the environment at "
            f"runtime) — export {src.connection_env}='<dsn>' and retry"
        )
    return dsn


def _table_name(src: Source) -> str:
    """Explicit ``table:`` name, else the file/directory stem (the default view
    name for single paths; globs are required to carry an explicit name)."""
    if src.table:
        return src.table
    stem = Path(_path(src)).stem
    if not IDENTIFIER_RE.fullmatch(stem):
        raise ValueError(
            f"source {src.name!r}: cannot derive a table name from {src.path!r} — "
            "set table: <name>"
        )
    return stem


def _view_statements(src: Source, scan: str) -> list[str]:
    table = _table_name(src)
    return [
        f"CREATE SCHEMA {src.name}",
        f"CREATE VIEW {src.name}.{table} AS SELECT * FROM {scan}('{_noquotes(_path(src))}')",
    ]


def _catalog_entry(con: duckdb.DuckDBPyConnection, src: Source) -> dict:
    """Per-source catalog entry: tables with columns, from information_schema
    (attaches expose catalog ``<name>``; file views live in schema ``<name>``
    of the in-memory catalog). ``ref`` is the qualified prefix the profiler
    addresses the table with (``<catalog>.<schema>`` for attaches, the schema
    for views)."""
    rows = con.execute(
        "SELECT table_name, column_name, data_type, table_schema "
        "FROM information_schema.columns "
        "WHERE (table_catalog = ? AND table_schema NOT IN "
        "('information_schema', 'pg_catalog')) OR table_schema = ? "
        "ORDER BY table_catalog, table_schema, table_name, ordinal_position",
        [src.name, src.name],
    ).fetchall()
    tables: dict[str, dict] = {}
    for table, column, data_type, schema in rows:
        # Attaches qualify as <catalog>.<schema>; file views live in schema
        # <name> of the in-memory catalog, so the schema alone qualifies them.
        ref = f"{src.name}.{schema}" if src.type in ATTACH_TYPES else src.name
        entry = tables.setdefault(table, {"name": table, "columns": [], "ref": ref})
        entry["columns"].append({"name": column, "type": data_type})
    return {"name": src.name, "type": src.type, "tables": list(tables.values())}
