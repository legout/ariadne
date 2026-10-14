"""Declarative source registry + the shared DuckDB connection builder (ADR-0010;
spec rev 9 §8.20).

``ariadne.yaml`` (scaffolded by ``ariadne-init``) declares every source in one
``sources:`` block; :func:`build_connection` produces THE DuckDB session behind
:class:`ariadne.execution.DuckDBExecution` for query/profiler/validate/author,
so every source is addressable as
``<source>.<table>`` and the compiler, grain guard, and audit operate unchanged
over the unified connection.

Types (``type:``):

- ``sqlite``   — ``ATTACH path AS name (TYPE SQLITE, READ_ONLY)``
- ``duckdb``   — ``ATTACH path AS name (READ_ONLY)`` — a native DuckDB database
  (spec 0022): no scanner, catalog identity is the registered alias; remote
  ``https://`` / ``s3://`` catalogs load ``httpfs`` first and attach READ_ONLY
  only — a writable remote attach is an explicit refusal, never a fallback
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

import base64
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

# Slug: lowercase, starts with a letter; used verbatim as catalog/schema name.
NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# An environment-VARIABLE NAME (a storage-profile reference, spec 0025 §2):
# identifiers only — never a substitution, connection string or assignment.
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# One literal S3 scope prefix (spec 0025 §2): ``s3://bucket/`` or a
# directory-prefix URI, always slash-terminated; no globs, credentials,
# query, fragment or empty/dot segments ("."/".." are refused separately).
S3_SCOPE_RE = re.compile(r"s3://[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*/\Z")

# Strict entry schema: no freestyle keys — a typo'd or smuggled key (dsn:,
# connection_string:, ...) must fail loudly instead of passing silently.
SOURCE_KEYS = frozenset({"name", "type", "path", "connection_env", "table", "read_only", "storage"})
# Storage-profile fields (spec 0025 §2): strict, credential-free declarations.
PROFILE_KEYS = frozenset(
    {
        "type",
        "access_key_id_env",
        "secret_access_key_env",
        "endpoint_url_env",
        "region_env",
        "session_token_env",
        "url_style",
        "scopes",
    }
)
PROFILE_REQUIRED_ENV = ("access_key_id_env", "secret_access_key_env", "endpoint_url_env")
# A connection string is a credential (ADR-0010): rejected under ANY key.
DSN_RE = re.compile(r"postgres(?:ql)?://")
# URI-scheme prefix (ducklake:, https://, s3://, ...): never cwd-relative.
_URI_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")
# scheme://user:password@host (also empty user) — never echo a password.
_DSN_PASSWORD_RE = re.compile(r"(//[^\s/@:]*:)([^\s/@]+)(@)")

SOURCE_TYPES = (
    "sqlite",
    "duckdb",
    "csv",
    "json",
    "parquet",
    "delta",
    "iceberg",
    "ducklake",
    "postgres",
)
ATTACH_TYPES = frozenset({"sqlite", "duckdb", "ducklake", "postgres"})
FILE_TYPES = frozenset({"csv", "json", "parquet"})
GLOB_CHARS = frozenset("*?[")
REMOTE_PREFIXES = ("http://", "https://", "s3://", "s3a://", "s3n://")
READER = {"csv": "read_csv_auto", "json": "read_json_auto", "parquet": "read_parquet"}
# The source types that may select a named storage profile (spec 0025 §2 —
# the seven file/native/Lakehouse readers; sqlite/postgres never take one).
STORAGE_SOURCE_TYPES = frozenset(
    {"csv", "json", "parquet", "duckdb", "delta", "iceberg", "ducklake"}
)

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
    storage: str | None = None  # a named storage-profile reference (spec 0025)


@dataclass(frozen=True)
class StorageProfile:
    """One validated credential-free S3 storage-profile declaration (spec
    0025 §2): environment-variable NAMES plus literal scopes — the host
    process supplies the values; nothing here is a secret."""

    name: str
    access_key_id_env: str
    secret_access_key_env: str
    endpoint_url_env: str
    region_env: str | None = None
    session_token_env: str | None = None
    url_style: str = "path"
    scopes: tuple[str, ...] = ()

    def identity(self) -> dict:
        """The deterministic canonical declaration (YAML key ordering never
        changes identity; only referenced profiles ride source identities)."""
        payload: dict = {"type": "s3"}
        for key in PROFILE_REQUIRED_ENV:
            payload[key] = getattr(self, key)
        if self.region_env is not None:
            payload["region_env"] = self.region_env
        if self.session_token_env is not None:
            payload["session_token_env"] = self.session_token_env
        payload["url_style"] = self.url_style
        payload["scopes"] = list(self.scopes)
        return payload


@dataclass(frozen=True)
class StorageBinding:
    """The resolved NON-SECRET effective identity of one used profile (spec
    0025 §§3–4): canonical endpoint, SSL, region, URL style and scopes. Never
    a key ID, secret key or session token."""

    name: str
    endpoint: str
    hostport: str
    use_ssl: bool
    region: str
    url_style: str
    scopes: tuple[str, ...]

    def record(self) -> dict:
        """The credential-free ``storage_bindings`` entry (spec 0025 §4)."""
        return {
            "endpoint": self.endpoint,
            "region": self.region,
            "url_style": self.url_style,
            "scopes": list(self.scopes),
        }


def profile_from_identity(name: str, payload: dict) -> StorageProfile:
    """Rebuild one profile from its canonical identity dict (an approved
    record's embedded declaration); malformed records refuse explicitly."""
    try:
        return StorageProfile(
            name=name,
            access_key_id_env=payload["access_key_id_env"],
            secret_access_key_env=payload["secret_access_key_env"],
            endpoint_url_env=payload["endpoint_url_env"],
            region_env=payload.get("region_env"),
            session_token_env=payload.get("session_token_env"),
            url_style=payload.get("url_style", "path"),
            scopes=tuple(payload.get("scopes") or ()),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"storage profile {name!r}: malformed stored declaration ({exc}) — "
            "this needs human resolution, never a silent reset"
        ) from None


def binding_from_record(name: str, record: dict) -> StorageBinding:
    """Rebuild one FROZEN binding from its credential-free record (an
    approval/admission's pinned effective identity, spec 0025 §4)."""
    endpoint, hostport, use_ssl = canonical_endpoint(str(record.get("endpoint") or ""), name)
    return StorageBinding(
        name=name,
        endpoint=endpoint,
        hostport=hostport,
        use_ssl=use_ssl,
        region=str(record.get("region") or ""),
        url_style=str(record.get("url_style") or "path"),
        scopes=tuple(record.get("scopes") or ()),
    )


@dataclass
class Registry:
    """Validated registry: the sources plus where they came from.

    ``path`` is ``None`` for the implicit ``--db`` shorthand (single sqlite
    attach under the authoring contract's catalog name ``demo``).
    ``storages`` carries the validated named profile declarations (spec 0025);
    ``bindings`` optionally FREEZES the resolved non-secret effective identity
    of the used profiles (an approval's pinned binding) so the connection
    opens exactly the checked endpoint instead of re-resolving the
    environment after the check (spec 0025 §4)."""

    sources: list[Source]
    path: str | None = None
    storages: dict[str, StorageProfile] | None = None
    bindings: dict[str, StorageBinding] | None = None


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


def validate_entries(
    entries: object,
    where: str | Path,
    base: Path,
    storages: dict[str, StorageProfile] | None = None,
) -> list[Source]:
    """Validate one raw ``sources:`` list with the load_registry rules
    (ADR-0010: slugs, known types, inline-credential rejection, duplicates;
    spec 0025 §2: optional ``storage:`` references into ``storages``) and
    resolve relative paths against ``base`` — the shared entry validation
    behind :func:`load_registry` and the Git authoring source proposals
    (issue #35/G3, which resolve against the configured data-project root
    instead of a registry file's directory). ``where`` names the entries'
    origin in errors."""
    if not isinstance(entries, list) or not entries:
        raise ValueError(
            f"{where}: no 'sources:' entries (a commented template counts "
            "as absent — declare sources or use --db)"
        )
    prefix = Path(where)
    validated: list[Source] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        validated.append(_source(prefix, index, entry, seen))
    _validate_storage_usage(validated, storages or {}, prefix)
    for src in validated:  # init.py's promise: paths are relative to the registry
        if src.path:
            src.path = _resolve_against(base, src.path)
    return validated


def validate_storages(raw: object, where: str | Path) -> dict[str, StorageProfile]:
    """Validate one raw ``storages:`` mapping of named S3 storage-profile
    declarations (spec 0025 §2): strict keys, environment-variable NAMES,
    literal slash-terminated scopes — no values are read and nothing opens.
    Returns the validated profiles keyed by name."""
    if raw is None or raw == {}:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{where}: 'storages:' must be a nonempty mapping of named storage "
            "profile declarations (spec 0025 §2)"
        )
    profiles: dict[str, StorageProfile] = {}
    for name, definition in raw.items():
        label = f"{where}: storages[{name!r}]"
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ValueError(
                f"{label}: profile name must be a lowercase slug (letters, digits, "
                "underscores; starting with a letter)"
            )
        if not isinstance(definition, dict):
            raise ValueError(f"{label}: definition must be a mapping")
        unknown = sorted(set(definition) - PROFILE_KEYS)
        if unknown:
            raise ValueError(f"{label}: unknown key(s) {unknown}; allowed: {sorted(PROFILE_KEYS)}")
        if definition.get("type") != "s3":
            raise ValueError(f"{label}: type must be exactly 's3' (spec 0025 §2)")
        for key in PROFILE_REQUIRED_ENV:
            value = definition.get(key)
            if not isinstance(value, str) or not ENV_NAME_RE.fullmatch(value):
                raise ValueError(
                    f"{label}: {key} must be an environment-variable NAME "
                    "(an identifier — never a substitution, connection string "
                    "or assignment)"
                )
        region_env = definition.get("region_env")
        if region_env is not None and (
            not isinstance(region_env, str) or not ENV_NAME_RE.fullmatch(region_env)
        ):
            raise ValueError(f"{label}: region_env must be an environment-variable NAME")
        session_token_env = definition.get("session_token_env")
        if session_token_env is not None and (
            not isinstance(session_token_env, str) or not ENV_NAME_RE.fullmatch(session_token_env)
        ):
            raise ValueError(f"{label}: session_token_env must be an environment-variable NAME")
        url_style = definition.get("url_style", "path")
        if url_style not in ("path", "vhost"):
            raise ValueError(f"{label}: url_style must be 'path' or 'vhost'")
        scopes_raw = definition.get("scopes")
        if not isinstance(scopes_raw, list) or not scopes_raw:
            raise ValueError(
                f"{label}: scopes must be a nonempty list of literal "
                "'s3://bucket/…/' URI prefixes (spec 0025 §2)"
            )
        scopes: list[str] = []
        for scope in scopes_raw:
            if not isinstance(scope, str) or not S3_SCOPE_RE.fullmatch(scope):
                raise ValueError(
                    f"{label}: scope {scope!r} is not a literal slash-terminated "
                    "'s3://bucket/…/' URI prefix (no globs, query, fragment, "
                    "credentials or dot-segment navigation)"
                )
            if any(part in (".", "..") for part in scope[len("s3://") :].split("/")):
                raise ValueError(f"{label}: scope {scope!r} must not contain '.' or '..' segments")
            scopes.append(scope)
        if len(set(scopes)) != len(scopes):
            raise ValueError(f"{label}: scopes must be unique")
        profiles[name] = StorageProfile(
            name=name,
            access_key_id_env=definition["access_key_id_env"],
            secret_access_key_env=definition["secret_access_key_env"],
            endpoint_url_env=definition["endpoint_url_env"],
            region_env=region_env,
            session_token_env=session_token_env,
            url_style=url_style,
            scopes=tuple(scopes),
        )
    return profiles


def validate_registry_doc(
    doc: object, where: str | Path, base: Path
) -> tuple[list[Source], dict[str, StorageProfile]]:
    """Validate one complete registry document (``sources:`` plus the
    optional ``storages:`` block, spec 0025 §2) — the whole-candidate seam
    Git proposal merges validate before committing. Returns the validated
    sources and profile declarations."""
    if not isinstance(doc, dict):
        raise ValueError(f"{where}: top level is not a mapping")
    storages = validate_storages(doc.get("storages"), where)
    sources_list = validate_entries(doc.get("sources"), where, base, storages=storages)
    return sources_list, storages


def load_registry(path: str | Path = DEFAULT_PATH) -> Registry:
    """Parse and validate a source registry (ADR-0010). Raises ``ValueError``
    naming the offending entry for: a non-slug name, an unknown type, a missing
    ``path`` (file/attach types) or ``connection_env`` (postgres), an inline
    connection string or credentialed URL (ADR-0010), a glob without an
    explicit ``table:``, or duplicate source names."""
    registry_path = Path(path)
    try:
        doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{registry_path}: not valid YAML: {exc}") from exc
    sources_list, storages = validate_registry_doc(
        doc, registry_path, registry_path.parent.resolve()
    )
    return Registry(
        sources=sources_list,
        path=str(registry_path),
        storages=storages or None,
    )


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
        if isinstance(value, str) and _DSN_PASSWORD_RE.search(value):
            raise ValueError(
                f"{where}: {key} carries inline URL credentials (ADR-0010): "
                "remove the user:password userinfo — credentials live in the "
                "environment, never in the registry"
            )
    unknown = sorted(set(entry) - SOURCE_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; allowed: {sorted(SOURCE_KEYS)}")
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
        if entry.get("storage") is not None:
            raise ValueError(f"{where}: type postgres cannot take a storage profile (spec 0025 §2)")
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
        if table is not None and (not isinstance(table, str) or not IDENTIFIER_RE.fullmatch(table)):
            raise ValueError(f"{where}: table must be a plain identifier")
        if any(ch in source_path for ch in GLOB_CHARS):
            if source_type not in FILE_TYPES:
                raise ValueError(f"{where}: glob paths are only valid for {sorted(FILE_TYPES)}")
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
            storage=_storage_reference(where, entry),
        )
    return source


def _storage_reference(where: str, entry: dict) -> str | None:
    """The optional ``storage:`` reference (spec 0025 §2): a profile NAME —
    resolution and per-type eligibility are the whole-registry check's job."""
    value = entry.get("storage")
    if value is None:
        return None
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ValueError(f"{where}: storage must be a storage profile NAME (a lowercase slug)")
    return value


def _read_only(path: Path, index: int, entry: dict) -> bool:
    value = entry.get("read_only", True)
    if not isinstance(value, bool):
        raise ValueError(f"{path}: sources[{index}]: read_only must be a boolean")
    return value


def _validate_storage_usage(
    validated: list[Source], storages: dict[str, StorageProfile], where: Path
) -> None:
    """The spec 0025 §2 cross-entry rules: a ``storage:`` reference resolves
    and only the seven supported reader types take one; a directly declared
    S3 path of a profile-based source uses ``s3://`` and falls inside a scope
    of its selected profile (local metadata/catalog paths keep their own
    resolution); USED profiles carry non-intersecting scopes; and a
    profile-free direct S3 path that would fall under an installed profile's
    scope refuses instead of silently inheriting the named secret."""
    used: dict[str, StorageProfile] = {}
    for src in validated:
        if src.storage is None:
            continue
        if src.type not in STORAGE_SOURCE_TYPES:
            raise ValueError(
                f"{where}: sources[{src.name!r}]: type {src.type} cannot take a "
                "storage profile — only the file/native/Lakehouse readers "
                f"{sorted(STORAGE_SOURCE_TYPES)} may (spec 0025 §2)"
            )
        profile = storages.get(src.storage)
        if profile is None:
            raise ValueError(
                f"{where}: sources[{src.name!r}]: references undeclared storage "
                f"profile {src.storage!r} — declare it under 'storages:' (spec 0025 §2)"
            )
        used[src.storage] = profile
        if src.path:
            if src.path.startswith(("s3a://", "s3n://")):
                raise ValueError(
                    f"{where}: sources[{src.name!r}]: a profile-based S3 source "
                    "must use s3:// — refusing s3a/s3n alias behavior (spec 0025 §2)"
                )
            if src.path.startswith("s3://") and not any(
                src.path.startswith(scope) for scope in profile.scopes
            ):
                raise ValueError(
                    f"{where}: sources[{src.name!r}]: path {src.path!r} falls "
                    f"outside every scope of storage profile {src.storage!r} "
                    f"({list(profile.scopes)}) — explicit scopes select the "
                    "credential (spec 0025 §2)"
                )
    names = sorted(used)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            for left in used[first].scopes:
                for right in used[second].scopes:
                    if left == right or left.startswith(right) or right.startswith(left):
                        raise ValueError(
                            f"{where}: storage profiles {first!r} and {second!r} "
                            f"declare intersecting scopes ({left!r}, {right!r}) — "
                            "used profiles must not overlap so credential "
                            "selection stays deterministic (spec 0025 §2)"
                        )
    for src in validated:
        if src.storage is not None or not (src.path and src.path.startswith("s3://")):
            continue
        for name in names:
            for scope in used[name].scopes:
                if src.path.startswith(scope):
                    raise ValueError(
                        f"{where}: sources[{src.name!r}]: profile-free S3 path "
                        f"{src.path!r} falls under the installed profile {name!r} "
                        f"scope {scope!r} and would silently inherit its named "
                        "secret — select that storage profile explicitly "
                        "(spec 0025 §2)"
                    )


def canonical_endpoint(raw: str, profile: str = "") -> tuple[str, str, bool]:
    """Validate and canonicalize one endpoint URL (spec 0025 §3): absolute
    ``http://``/``https://`` with a host and optional valid port, empty/root
    path only — userinfo, query, fragment and non-root base paths refuse.
    Returns ``(canonical_url, host_port, use_ssl)`` with the scheme/host
    canonicalized and equivalent default ports elided (the DuckDB ``ENDPOINT``
    takes host[:port]; ``USE_SSL`` follows the scheme)."""
    where = f"storage profile {profile!r} " if profile else ""
    text = raw.strip()
    try:
        parts = urlsplit(text)
        port = parts.port  # None or 1-65535; raises for invalid ports
    except ValueError as exc:
        raise ValueError(f"{where}endpoint URL is invalid: {exc}") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"{where}endpoint URL must be absolute http:// or https://, got {text!r}")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{where}endpoint URL must not carry userinfo (credentials)")
    if parts.query or parts.fragment:
        raise ValueError(f"{where}endpoint URL must not carry a query or fragment")
    host = (parts.hostname or "").lower()
    if not host or any(character.isspace() for character in host):
        raise ValueError(f"{where}endpoint URL requires a host, got {text!r}")
    if parts.path not in ("", "/"):
        raise ValueError(f"{where}endpoint URL takes an empty/root path only, got {parts.path!r}")
    default_port = 443 if scheme == "https" else 80
    hostport = (
        (f"[{host}]" if ":" in host else host)
        if port in (None, default_port)
        else (f"[{host}]:{port}" if ":" in host else f"{host}:{port}")
    )
    return f"{scheme}://{hostport}", hostport, scheme == "https"


def resolve_binding(profile: StorageProfile) -> StorageBinding:
    """Resolve one used profile's NON-SECRET effective identity from the
    executing process (spec 0025 §§3–4): the endpoint URL and optional region
    variable values only — never a key/token read, never a network call. A
    declared-but-unset region variable refuses; an omitted one uses the
    explicit ``us-east-1`` without inheriting another profile or a global."""
    endpoint_raw = _env_value(profile.endpoint_url_env, profile, "endpoint URL")
    endpoint, hostport, use_ssl = canonical_endpoint(endpoint_raw, profile.name)
    if profile.region_env is not None:
        region = _env_value(profile.region_env, profile, "region")
    else:
        region = "us-east-1"
    return StorageBinding(
        name=profile.name,
        endpoint=endpoint,
        hostport=hostport,
        use_ssl=use_ssl,
        region=region,
        url_style=profile.url_style,
        scopes=profile.scopes,
    )


def _env_value(variable: str, profile: StorageProfile, what: str) -> str:
    """One required non-blank environment value, refusing by variable and
    profile identity — the value itself may be a secret and is never echoed."""
    value = os.environ.get(variable)
    if value is None or not value.strip():
        raise ValueError(
            f"storage profile {profile.name!r}: environment variable {variable} "
            f"({what}) is not set — the executing host process supplies storage "
            f"profile values; export {variable} and retry (no credential "
            "fallback, spec 0025 §3)"
        )
    return value


def used_profiles(registry: Registry) -> dict[str, StorageProfile]:
    """The profiles actually referenced by the registry's sources (spec 0025
    §2: unused definitions are never resolved or installed)."""
    storages = registry.storages or {}
    used: dict[str, StorageProfile] = {}
    for src in registry.sources:
        if src.storage is None:
            continue
        profile = storages.get(src.storage)
        if profile is None:
            raise ValueError(
                f"source {src.name!r} references undeclared storage profile "
                f"{src.storage!r} — the registry must be validated first"
            )
        used[src.storage] = profile
    return used


def plan(registry: Registry, read_only: bool = True) -> tuple[list[str], list[str]]:
    """The exact statement sequence the builder executes, as pure text:
    ``(loads, statements)`` — extension ``LOAD``s first (deduplicated, registry
    order), then the per-source ATTACH/CREATE SCHEMA/CREATE VIEW DDL. This is
    the statement-construction test surface (ADR-0010 tiering): the builder
    adds nothing beyond executing these strings in order. Storage-profile
    secrets (spec 0025 §3) are deliberately NOT part of this plan: they are
    created by :func:`build_connection` only, so public plans stay
    credential-free extension/source-DDL text."""
    loads: list[str] = []
    statements: list[str] = []
    if used_profiles(registry):
        # spec 0025 §3: a used profile means S3 object access (scopes are
        # s3:// — including remote backing files behind a LOCAL metadata or
        # catalog path), so httpfs loads before any source binding.
        _want(loads, "httpfs")
    for src in registry.sources:
        suffix = ", READ_ONLY" if src.read_only and read_only else ""
        if src.type == "sqlite":
            statements.append(
                f"ATTACH '{_noquotes(_path(src))}' AS {src.name} (TYPE SQLITE{suffix})"
            )
        elif src.type == "duckdb":
            # Native attach (spec 0022): no scanner, and remote catalogs are
            # READ_ONLY only — a writable remote build refuses before any
            # connection is opened, never a fallback (spec 0022 §2).
            if _is_remote(src.path) and not (src.read_only and read_only):
                raise ValueError(
                    f"source {src.name!r}: remote duckdb catalogs attach READ_ONLY "
                    "only — a writable remote attach is an explicit refusal, not a "
                    "fallback (spec 0022 §2)"
                )
            if _is_remote(src.path):
                _want(loads, "httpfs")
            statements.append(
                f"ATTACH '{_noquotes(_path(src))}' AS {src.name}{' (READ_ONLY)' if suffix else ''}"
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


def _setup_error(exc: BaseException, timer, deadline, secrets: list[str]) -> BaseException:
    """Classify one setup failure: an interruption that fired after the setup
    budget elapsed becomes the explicit deadline refusal (never a partial
    session); every other error keeps its message with any DSN redacted."""
    if (
        timer is not None
        and deadline is not None
        and not timer.is_alive()
        and isinstance(exc, duckdb.Error)
    ):
        return ValueError(
            f"the inspection deadline was exhausted during source setup "
            f"(budget {deadline:.3f}s) — the setup was interrupted and nothing "
            "was opened further (spec 0010 §7); no result is claimed"
        )
    if secrets and isinstance(exc, Exception):
        exc.args = (_redact_all(str(exc), secrets),)
    return exc


def build_connection(
    registry: Registry, read_only: bool = True, *, deadline: float | None = None
) -> tuple[duckdb.DuckDBPyConnection, list[dict]]:
    """The one DuckDB session for all commands (ADR-0010): executes
    :func:`plan` verbatim and returns ``(connection, catalog)``. The catalog
    lists, per source, its tables with columns where cheaply enumerable —
    ``information_schema`` for attaches, the same catalog for file views.
    Execution errors are re-raised with any postgres DSN redacted (DuckDB
    echoes the SQL text, so a failed ATTACH would leak credentials).

    With ``deadline`` (K3 issue #43: a remaining-seconds budget covering the
    whole setup), the extension loads, per-source DDL and catalog reads run
    under the connection's interrupt watchdog: an over-budget setup is
    interrupted and reported as the explicit deadline refusal — never a
    "stopped" claim with a read still running, never an unbounded setup."""
    loads, statements = plan(registry, read_only=read_only)
    secrets = [_resolve_dsn(src) for src in registry.sources if src.type == "postgres"]
    cert = os.getenv("SSL_CERT_FILE")
    con = duckdb.connect(config={"ca_cert_file": cert} if cert else {})
    timer = None
    if deadline is not None:
        if not hasattr(con, "interrupt"):
            con.close()
            raise ValueError(
                "this DuckDB build exposes no interruptible connection — a source "
                "setup/execution that cannot be bounded and cancelled is an "
                "explicit refusal, never a fake passing check (spec 0010 §7)"
            )
        timer = threading.Timer(max(float(deadline), 1e-6), con.interrupt)
        timer.daemon = True
        timer.start()
    try:
        for extension in loads:
            # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            con.execute(f"LOAD {extension}")
        # spec 0025 §3: temporary explicit-provider secrets for the USED
        # profiles are created in this shared builder — before any source
        # ATTACH/view binding, once per profile, never in public plans. The
        # redaction list is filled IN PLACE, before any secret SQL executes,
        # so a CREATE SECRET failure that echoes its statement is redacted
        # too (AC4: values never reach a returned/chained error).
        _install_storage_secrets(con, registry, secrets)
        for statement in statements:
            try:
                con.execute(statement)  # nosemgrep — plan() output, validated-registry inputs only
            except Exception as exc:
                raise _setup_error(exc, timer, deadline, secrets)
        catalog = [_catalog_entry(con, src) for src in registry.sources]
    except Exception as exc:
        # K3 fix pass (finding 9): a failing setup CLOSES the connection it
        # opened — no leaked session/read survives the refused setup (the
        # connection owner is never constructed when setup raises).
        try:
            con.close()
        except Exception:  # pragma: no cover - a failing close must not mask the cause
            pass
        raise _setup_error(exc, timer, deadline, secrets)
    finally:
        if timer is not None:
            timer.cancel()  # setup ended: no background interrupt keeps running
    return con, catalog


def _redact(dsn: str) -> str:
    """``scheme://user:password@host/...`` -> ``scheme://user:***@host/...``
    (user and host may surface; the password never does)."""
    return _DSN_PASSWORD_RE.sub(r"\1***\3", dsn)


def _redact_all(message: str, secrets: list[str]) -> str:
    """Every known DSN or storage-profile key/token value redacted — in RAW
    form AND in the SQL-escaped form the engine actually echoes (a quote in a
    secret is doubled inside the CREATE SECRET literal, so the escaped text
    would otherwise remain recoverable) — plus a generic pass so no
    credentialed URL in a builder-raised error message ever carries a
    password (spec 0025 §3/AC4: report variable/profile identity, never
    secret contents, including library errors that echo SQL)."""
    for dsn in secrets:
        message = (
            message.replace(dsn, _redact(dsn))
            if "://" in dsn and _DSN_PASSWORD_RE.search(dsn)
            else message.replace(dsn, "***")
        )
        escaped = dsn.replace("'", "''")
        if escaped != dsn:
            message = message.replace(escaped, "***")
    return _DSN_PASSWORD_RE.sub(r"\1***\3", message)


def _sql_literal(value: str) -> str:
    """One single-quoted SQL string literal with embedded quotes doubled —
    DuckDB takes no bind parameters in CREATE SECRET, and a legitimate
    key/token value may contain quotes (spec 0025 §3: proper literal
    handling; the value is never echoed in errors)."""
    return "'" + value.replace("'", "''") + "'"


def _install_storage_secrets(
    con: duckdb.DuckDBPyConnection, registry: Registry, redactions: list[str] | None = None
) -> list[str]:
    """Create one temporary ``TYPE S3, PROVIDER CONFIG`` secret per USED
    storage profile, inside this shared connection, before any source
    binding (spec 0025 §3). Endpoint/region come from the registry's FROZEN
    binding when the registry carries one (an approval's pinned effective
    identity) and from the environment otherwise; key/token values always
    come from the environment. Every secret VALUE is appended to
    ``redactions`` (and returned) BEFORE its CREATE SECRET executes, so a
    failing creation that echoes the statement is redacted — the SQL itself
    never leaves this function."""
    used = used_profiles(registry)
    if not used:
        return []
    values: list[str] = redactions if redactions is not None else []
    created: set[str] = set()
    frozen = registry.bindings or {}
    for name in sorted(used):
        profile = used[name]
        binding = frozen.get(name) or resolve_binding(profile)
        key_id = _env_value(profile.access_key_id_env, profile, "access key ID")
        secret_key = _env_value(profile.secret_access_key_env, profile, "secret access key")
        session_token = (
            _env_value(profile.session_token_env, profile, "session token")
            if profile.session_token_env
            else None
        )
        values.extend(value for value in (key_id, secret_key, session_token) if value)
        options = [
            "TYPE S3",
            "PROVIDER CONFIG",
            f"KEY_ID {_sql_literal(key_id)}",
            f"SECRET {_sql_literal(secret_key)}",
        ]
        if session_token is not None:
            options.append(f"SESSION_TOKEN {_sql_literal(session_token)}")
        options.extend(
            [
                f"REGION {_sql_literal(binding.region)}",
                f"ENDPOINT {_sql_literal(binding.hostport)}",
                f"USE_SSL {'true' if binding.use_ssl else 'false'}",
                f"URL_STYLE {_sql_literal(binding.url_style)}",
                "SCOPE [" + ", ".join(_sql_literal(scope) for scope in binding.scopes) + "]",
            ]
        )
        # nosemgrep — builder-generated options over validated declarations
        # and host-environment values only; literals are quote-escaped.
        con.execute(f"CREATE SECRET ariadne_{name} ({', '.join(options)})")
        created.add(f"ariadne_{name}")
    _refuse_shadowed_scopes(con, created, used)
    return values


def _refuse_shadowed_scopes(
    con: duckdb.DuckDBPyConnection, created: set[str], used: dict[str, StorageProfile]
) -> None:
    """The effective-binding invariant (spec 0025 §3): after installing the
    named profile secrets, verify the session's actual secret selection —
    another secret (a persistent/ambient one) whose scope equals or is MORE
    SPECIFIC than one of ours would win DuckDB's longest-prefix match and
    open an unapproved endpoint. Refuse BEFORE any source request; never
    touch operator state."""
    rows = con.execute(
        "SELECT name, scope FROM duckdb_secrets()"
    ).fetchall()  # non-secret secret-manager metadata
    foreign = [
        (str(name), [scope for scope in (scopes or []) if isinstance(scope, str)])
        for name, scopes in rows
        if str(name) not in created
    ]
    for name in sorted(used):
        for scope in used[name].scopes:
            for secret_name, scopes in foreign:
                for other in scopes:
                    if other == scope or other.startswith(scope):
                        raise ValueError(
                            f"refusing to open source data under {scope}: the "
                            f"session secret {secret_name!r} covers the "
                            f"equal-or-more-specific scope {other!r} and would "
                            f"override storage profile {name!r}'s approved "
                            "binding (spec 0025 §3) — remove or rescope the "
                            "conflicting secret so the named profile is the "
                            "credential actually used; no source was accessed"
                        )


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
            f"source {src.name!r}: cannot derive a table name from {src.path!r} — set table: <name>"
        )
    return stem


def _view_statements(src: Source, scan: str) -> list[str]:
    table = _table_name(src)
    return [
        f"CREATE SCHEMA {src.name}",
        f"CREATE VIEW {src.name}.{table} AS SELECT * FROM {scan}('{_noquotes(_path(src))}')",
    ]


def _resource_payload(parts: list[str | None]) -> str:
    """The canonical credential-free resource payload (spec 0010 §4, plan
    §2): a JSON array serialized UTF-8 with compact separators and no ASCII
    escaping, encoded as unpadded URL-safe base64. The payload carries ONLY
    registry/catalog identifiers — never a resolved file path, DSN, credential
    or worktree location."""
    canonical = json.dumps(parts, separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(canonical.encode("utf-8")).decode("ascii").rstrip("=")


def table_resource(source: str, catalog: str | None, schema: str, table: str) -> str:
    """``ariadne://table/<payload>`` for the complete catalog asset tuple
    ``[source, catalog, schema, table]`` (exact case-sensitive identifiers;
    ``catalog`` is ``None`` for file views, the stable attach name for
    attached sources)."""
    return f"ariadne://table/{_resource_payload([source, catalog, schema, table])}"


def collection_resource(source: str, catalog: str | None, schema: str) -> str:
    """``ariadne://collection/<payload>`` for one physical collection
    ``[source, catalog, schema]``."""
    return f"ariadne://collection/{_resource_payload([source, catalog, schema])}"


def parse_resource(uri: object) -> tuple[str, list]:
    """Decode one canonical resource URI back to ``(kind, parts)`` — the
    identity consumers read instead of parsing display names. ``kind`` is
    ``table`` or ``collection``; ``parts`` is the identifier array
    (``[source, catalog, schema(, table)]``). Malformed URIs raise
    ``ValueError``."""
    if not isinstance(uri, str):
        raise ValueError(f"resource must be a string, got {uri!r}")
    prefix = "ariadne://"
    if not uri.startswith(prefix):
        raise ValueError(f"resource {uri!r} is not a canonical ariadne:// URI")
    kind, _, payload = uri[len(prefix) :].partition("/")
    if kind not in ("table", "collection") or not payload:
        raise ValueError(
            f"resource {uri!r} must be ariadne://table/<payload> or ariadne://collection/<payload>"
        )
    padded = payload + "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        parts = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(
            f"resource {uri!r} does not decode to a canonical payload: {exc}"
        ) from None
    expected = 4 if kind == "table" else 3
    if (
        not isinstance(parts, list)
        or len(parts) != expected
        or not all(part is None or isinstance(part, str) for part in parts)
        or not isinstance(parts[0], str)
        or not parts[0]
        or parts[2] is None
    ):
        raise ValueError(
            f"resource {uri!r} payload must be [{expected} identifiers: source, "
            "catalog (or null), schema(, table)]"
        )
    return kind, parts


def _catalog_entry(con: duckdb.DuckDBPyConnection, src: Source) -> dict:
    """Per-source catalog entry: tables with columns, from information_schema
    (attaches expose catalog ``<name>``; file views live in schema ``<name>``
    of the in-memory catalog). ``ref`` is the qualified prefix the profiler
    addresses the table with (``<catalog>.<schema>`` for attaches, the schema
    for views). Tables are enumerated by the COMPLETE tuple
    ``(table_catalog, table_schema, table_name)`` — never the table name alone
    (spec 0010 §4/plan §2: same-named tables in distinct schemas stay distinct
    assets): each table entry additionally carries the explicit identity
    fields (``source``/``catalog``/``schema`` plus the canonical ``resource``;
    a file view's ``catalog`` is ``None``, not DuckDB's temp in-memory catalog
    name) so consumers need never parse display names.

    Selection is by exact inventory identity (spec 0022 §3): an attached
    source enumerates ONLY its own catalog (the attach alias), and a file-view
    source ONLY its actual in-memory catalog/schema pair — a native schema
    that merely shares another source's name never bleeds into that
    inventory."""
    attached = src.type in ATTACH_TYPES
    if attached:
        rows = con.execute(
            "SELECT table_catalog, table_schema, table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_catalog = ? AND table_schema NOT IN "
            "('information_schema', 'pg_catalog') "
            "ORDER BY table_catalog, table_schema, table_name, ordinal_position",
            [src.name],
        ).fetchall()
    else:
        row = con.execute("SELECT current_database()").fetchone()
        assert row is not None  # current_database() always returns exactly one row
        (database,) = row
        rows = con.execute(
            "SELECT table_catalog, table_schema, table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_catalog = ? AND table_schema = ? "
            "ORDER BY table_catalog, table_schema, table_name, ordinal_position",
            [database, src.name],
        ).fetchall()
    tables: dict[tuple[str, str, str], dict] = {}
    for catalog, schema, table, column, data_type in rows:
        entry = tables.setdefault(
            (catalog, schema, table),
            {"name": table, "columns": [], "catalog": catalog if attached else None},
        )
        entry["columns"].append({"name": column, "type": data_type})
    table_list: list[dict] = []
    for (catalog, schema, table), entry in tables.items():
        # Attaches qualify as <catalog>.<schema>; file views live in schema
        # <name> of the in-memory catalog, so the schema alone qualifies them.
        entry["ref"] = f"{src.name}.{schema}" if attached else src.name
        entry["schema"] = schema
        entry["source"] = src.name
        entry["resource"] = table_resource(src.name, entry["catalog"], schema, table)
        table_list.append(entry)
    if src.type == "duckdb":
        _bind_native_views(con, src)  # required view binding inside bounded setup
    return {"name": src.name, "type": src.type, "tables": table_list}


def _bind_native_views(con: duckdb.DuckDBPyConnection, src: Source) -> None:
    """Bind every view of a native catalog inside the SAME bounded setup
    (spec 0022 §2): information_schema reports a view's STORED columns without
    binding it, so one cheap ``DESCRIBE`` per view (bind-only — no data scan,
    no transitive dependency analysis) makes a missing backing file/URL fail
    the setup here and close the connection, instead of returning a partial
    ready session whose first query would fail later."""
    views = con.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_catalog = ? AND table_type = 'VIEW' AND table_schema NOT IN "
        "('information_schema', 'pg_catalog')",
        [src.name],
    ).fetchall()
    for schema, view in views:
        con.execute(
            f"DESCRIBE {_qualified(src.name, schema, view)}"
        ).fetchall()  # identifiers came from the catalog itself, quoted verbatim


def _qualified(*identifiers: str) -> str:
    """One dotted, double-quoted SQL reference (embedded quotes doubled) for
    identifiers that came out of the catalog and must go back in verbatim."""
    return ".".join('"' + part.replace('"', '""') + '"' for part in identifiers)
