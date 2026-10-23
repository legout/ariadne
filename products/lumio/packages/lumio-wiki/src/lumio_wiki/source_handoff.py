"""Private source transfer kinds (spec 0010 §5/§5.1) — baseline operations.

J0 delivers the metadata-only **Source Baseline Snapshot**: a distinct,
versioned artifact kind carrying the exact Source Version metadata referenced
by one selected Git base revision — never original or extracted bytes, store
keys, credentials, local paths, availability flags or lifecycle intent. The
full Source Handoff Bundle (J3) later extends this module; both kinds share
strict archive and metadata parsing with explicit bounds.

Integrity model (spec 0010 §5.1): the archive's SHA-256 digest is supplied
out-of-band (maintainer-approved project setup or direct operator selection)
and proves transfer integrity; matching Git bindings prove identity
alignment. Neither establishes that the receiver verified source bytes or
their factual content, and import can never mark an artifact available —
only retained, verified bytes do that.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any

import msgspec

from lumio_wiki.git_authoring import capture_revision
from lumio_wiki.mutation import atomic_write_bytes
from lumio_wiki.private_provenance import write_baseline_origin_record
from lumio_wiki.source_registry import (
    SAFE_FILENAME_MAX_LENGTH,
    SourceRegistry,
    SourceRegistryError,
    SourceVersion,
    _validate_source_id,
)

__all__ = [
    "BASELINE_KIND",
    "BASELINE_SCHEMA_VERSION",
    "MANIFEST_MAX_BYTES",
    "MAX_BINDING_RECORDS",
    "MAX_VERSION_RECORDS",
    "BaselineExport",
    "BaselineImport",
    "BaselinePreview",
    "SourceBaselineError",
    "export_source_baseline",
    "import_source_baseline",
    "inspect_source_baseline",
]

#: The single supported baseline schema version and its distinct artifact kind.
BASELINE_SCHEMA_VERSION = 1
BASELINE_KIND = "source-baseline"

#: The manifest-only archive member and its fixed bounds (plan 0010, transfer
#: formats v1). Lower deployment limits are a deployment concern; exceeding a
#: bound is an explicit refusal, never partial bootstrap.
MANIFEST_MEMBER = "manifest.json"
MANIFEST_MAX_BYTES = 4 * 1024 * 1024
MAX_VERSION_RECORDS = 10_000
MAX_BINDING_RECORDS = 50_000
#: Uncompressed-tar container slack (blocking factor plus headers) tolerated
#: around one bounded manifest member.
_ARCHIVE_OVERHEAD_MAX_BYTES = 1024 * 1024
#: One bounded streaming read unit for archive verification (j0-review F1):
#: the container is hashed and read in bounded chunks, never one allocation.
_ARCHIVE_READ_CHUNK_BYTES = 1024 * 1024

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


class SourceBaselineError(ValueError):
    """A Source Baseline Snapshot operation violated the §5.1 contract."""


class BaselineExport(msgspec.Struct, frozen=True):
    """The result of one baseline snapshot export (safe, no private paths)."""

    schema_version: int
    kind: str
    transfer_id: str
    namespace: str
    kb_subtree: str
    revision: str
    source_manifest_digest: str
    binding_count: int
    version_count: int
    snapshot_sha256: str
    output_path: str


class BaselinePreview(msgspec.Struct, frozen=True):
    """A read-only baseline import preview: readiness and blockers, not approval."""

    schema_version: int
    kind: str
    ready: bool
    namespace: str
    kb_subtree: str
    revision: str
    source_manifest_digest: str
    transfer_id: str
    snapshot_sha256: str
    binding_count: int
    version_count: int
    versions_to_add: int
    versions_to_reuse: int
    blockers: list[str]
    confirmation_digest: str


class BaselineImport(msgspec.Struct, frozen=True):
    """The result of a baseline import request (``status``: preview|imported)."""

    schema_version: int
    kind: str
    status: str
    namespace: str
    revision: str
    transfer_id: str
    snapshot_sha256: str
    confirmation_digest: str | None
    versions_added: int
    versions_reused: int
    provenance_records: int
    blockers: list[str]


class _BaselineBinding(msgspec.Struct, frozen=True):
    entity_id: str
    source_id: str
    content_hash: str


class _BaselineVersion(msgspec.Struct, frozen=True):
    source_id: str
    content_hash: str
    size: int
    content_type: str | None
    filename: str | None
    origin_created_at: str


class _ParsedBaseline(msgspec.Struct, frozen=True):
    transfer_id: str
    namespace: str
    kb_subtree: str
    revision: str
    source_manifest_digest: str
    bindings: list[_BaselineBinding]
    versions: list[_BaselineVersion]


# ---------------------------------------------------------------------------
# Strict v1 manifest parsing (hand-rolled: generic decoders accept duplicates).
# ---------------------------------------------------------------------------

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "transfer_id",
        "namespace",
        "kb_subtree",
        "revision",
        "source_manifest_digest",
        "bindings",
        "versions",
    }
)
_BINDING_KEYS = frozenset({"entity_id", "source_id", "content_hash"})
_VERSION_KEYS = frozenset(
    {
        "source_id",
        "content_hash",
        "size",
        "content_type",
        "filename",
        "origin_created_at",
    }
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceBaselineError(f"duplicate JSON key {key!r} in the baseline manifest")
        result[key] = value
    return result


def _require_text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceBaselineError(f"baseline manifest field {what} must be a non-empty string")
    return value


def _require_hex(value: Any, what: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise SourceBaselineError(
            f"baseline manifest field {what} must match {pattern.pattern[1:-1]!r}"
        )
    return value


def _require_object_list(value: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SourceBaselineError(f"baseline manifest field {what} must be a list of objects")
    for item in value:
        if not isinstance(item, dict):
            raise SourceBaselineError(f"baseline manifest field {what} must be a list of objects")
    return value


def _check_keys(item: dict[str, Any], keys: frozenset[str], what: str) -> None:
    unknown = sorted(set(item) - keys)
    if unknown:
        raise SourceBaselineError(
            f"baseline manifest {what} carries unknown field(s): {', '.join(unknown)}"
        )
    missing = sorted(keys - set(item))
    if missing:
        raise SourceBaselineError(
            f"baseline manifest {what} is missing required field(s): {', '.join(missing)}"
        )


def _require_safe_filename(value: Any, what: str) -> str | None:
    if value is None:
        return None
    filename = _require_text(value, what)
    if "/" in filename or "\\" in filename or "\x00" in filename or filename in {".", ".."}:
        raise SourceBaselineError(f"baseline manifest field {what} must be a safe basename")
    if len(filename) > SAFE_FILENAME_MAX_LENGTH:
        raise SourceBaselineError(
            f"baseline manifest field {what} exceeds the safe filename length "
            f"({SAFE_FILENAME_MAX_LENGTH} characters)"
        )
    return filename


def _parse_baseline_manifest(payload: bytes) -> _ParsedBaseline:
    """Parse and fully validate one source-baseline manifest v1 against the contract."""
    if len(payload) > MANIFEST_MAX_BYTES:
        raise SourceBaselineError(
            f"the baseline manifest exceeds the 4 MiB ceiling ({len(payload)} bytes); "
            "an explicit refusal, never partial bootstrap"
        )
    try:
        manifest = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceBaselineError(f"the baseline manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SourceBaselineError("the baseline manifest must be a JSON object")
    _check_keys(manifest, _MANIFEST_KEYS, "manifest")
    schema_version = manifest["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != BASELINE_SCHEMA_VERSION
    ):
        raise SourceBaselineError(
            f"unsupported baseline manifest schema_version: {schema_version!r}"
        )
    if manifest["kind"] != BASELINE_KIND:
        raise SourceBaselineError(
            f"wrong artifact kind {manifest['kind']!r}: the baseline importer accepts only "
            f"{BASELINE_KIND!r} snapshots; a full-source bundle cannot bootstrap a baseline"
        )
    transfer_id = _require_hex(manifest["transfer_id"], "transfer_id", _HEX64)
    namespace = _require_text(manifest["namespace"], "namespace")
    kb_subtree = manifest["kb_subtree"]
    if not isinstance(kb_subtree, str) or kb_subtree.startswith("/") or ".." in kb_subtree:
        raise SourceBaselineError("baseline manifest field kb_subtree must be a KB-relative path")
    revision = _require_hex(manifest["revision"], "revision", _HEX40)
    source_manifest_digest = _require_hex(
        manifest["source_manifest_digest"], "source_manifest_digest", _HEX64
    )

    raw_bindings = _require_object_list(manifest["bindings"], "bindings")
    if len(raw_bindings) > MAX_BINDING_RECORDS:
        raise SourceBaselineError(
            f"the baseline manifest exceeds the binding-record limit "
            f"({len(raw_bindings)} > {MAX_BINDING_RECORDS}); an explicit refusal, "
            "never partial bootstrap"
        )
    bindings: list[_BaselineBinding] = []
    seen_bindings: set[tuple[str, str]] = set()
    for item in raw_bindings:
        _check_keys(item, _BINDING_KEYS, "binding record")
        binding = _BaselineBinding(
            entity_id=_require_text(item["entity_id"], "bindings[].entity_id"),
            source_id=_validate_source_id(item["source_id"]),
            content_hash=_require_hex(item["content_hash"], "bindings[].content_hash", _HEX64),
        )
        key = (binding.entity_id, binding.source_id)
        if key in seen_bindings:
            raise SourceBaselineError(
                f"duplicate baseline binding record for entity {binding.entity_id!r} "
                f"and source {binding.source_id!r}"
            )
        seen_bindings.add(key)
        bindings.append(binding)

    raw_versions = _require_object_list(manifest["versions"], "versions")
    if len(raw_versions) > MAX_VERSION_RECORDS:
        raise SourceBaselineError(
            f"the baseline manifest exceeds the version-record limit "
            f"({len(raw_versions)} > {MAX_VERSION_RECORDS}); an explicit refusal, "
            "never partial bootstrap"
        )
    versions: list[_BaselineVersion] = []
    seen_versions: set[tuple[str, str]] = set()
    for item in raw_versions:
        _check_keys(item, _VERSION_KEYS, "version record")
        size = item["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SourceBaselineError("versions[].size must be a non-negative integer")
        content_type = item["content_type"]
        if content_type is not None and (not isinstance(content_type, str) or not content_type):
            raise SourceBaselineError("versions[].content_type must be a non-empty string or null")
        version = _BaselineVersion(
            source_id=_validate_source_id(item["source_id"]),
            content_hash=_require_hex(item["content_hash"], "versions[].content_hash", _HEX64),
            size=size,
            content_type=content_type,
            filename=_require_safe_filename(item["filename"], "versions[].filename"),
            origin_created_at=_require_text(
                item["origin_created_at"], "versions[].origin_created_at"
            ),
        )
        key = (version.source_id, version.content_hash)
        if key in seen_versions:
            raise SourceBaselineError(
                f"duplicate baseline version record for {version.source_id!r}"
                f"@{version.content_hash}"
            )
        seen_versions.add(key)
        versions.append(version)

    referenced = {(binding.source_id, binding.content_hash) for binding in bindings}
    unreferenced = sorted(seen_versions - referenced)
    if unreferenced:
        raise SourceBaselineError(
            "the baseline manifest carries version record(s) not referenced by any "
            f"binding: {unreferenced[0][0]!r}@{unreferenced[0][1]}"
        )
    missing = sorted(referenced - seen_versions)
    if missing:
        raise SourceBaselineError(
            f"the baseline manifest binds {missing[0][0]!r}@{missing[0][1]} to no version record"
        )
    return _ParsedBaseline(
        transfer_id=transfer_id,
        namespace=namespace,
        kb_subtree=kb_subtree,
        revision=revision,
        source_manifest_digest=source_manifest_digest,
        bindings=sorted(bindings, key=lambda b: (b.entity_id, b.source_id)),
        versions=sorted(versions, key=lambda v: (v.source_id, v.content_hash)),
    )


def _canonical_json(value: Any) -> bytes:
    """Canonical JSON bytes (sorted keys, compact separators, UTF-8)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _binding_dicts(bindings: list[_BaselineBinding]) -> list[dict[str, str]]:
    return [
        {
            "entity_id": binding.entity_id,
            "source_id": binding.source_id,
            "content_hash": binding.content_hash,
        }
        for binding in sorted(bindings, key=lambda b: (b.entity_id, b.source_id))
    ]


def _version_dicts(versions: list[_BaselineVersion]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": version.source_id,
            "content_hash": version.content_hash,
            "size": version.size,
            "content_type": version.content_type,
            "filename": version.filename,
            "origin_created_at": version.origin_created_at,
        }
        for version in sorted(versions, key=lambda v: (v.source_id, v.content_hash))
    ]


# ---------------------------------------------------------------------------
# Manifest-only normalized tar container.
# ---------------------------------------------------------------------------


def _write_snapshot_archive(payload: bytes, output_path: Path) -> str:
    """Write one uncompressed, normalized, manifest-only tar; return its SHA-256."""
    info = tarfile.TarInfo(MANIFEST_MEMBER)
    info.size = len(payload)
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.type = tarfile.REGTYPE
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        tar.addfile(info, io.BytesIO(payload))
    data = buffer.getvalue()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(output_path, data)
    return hashlib.sha256(data).hexdigest()


def _read_verified_archive(snapshot_path: Path, expected_digest: str) -> tuple[bytes, str]:
    """Bounded-read and hash-verify the archive; return the exact verified bytes.

    A hard cumulative budget over the opened stream enforces the container
    ceiling even when the transfer file grows or is replaced after the early
    stat optimization: at most ``budget + 1`` bytes are ever requested, and
    the first byte beyond the ceiling refuses BEFORE that chunk is hashed or
    appended (spec 0010 transfer formats v1; j0-review F1 and its delta).
    The parser consumes these same verified bytes — never a second path read.
    """
    if not isinstance(expected_digest, str) or not _HEX64.match(expected_digest):
        raise SourceBaselineError(
            "the expected snapshot digest must be exactly 64 lowercase hex characters"
        )
    budget = MANIFEST_MAX_BYTES + _ARCHIVE_OVERHEAD_MAX_BYTES
    size = snapshot_path.stat().st_size
    if size > budget:
        raise SourceBaselineError(
            f"the baseline snapshot archive exceeds the container bound ({size} bytes); "
            "an explicit refusal, never partial bootstrap"
        )
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    consumed = 0
    with open(snapshot_path, "rb") as handle:
        while True:
            # Never request more than the remaining budget plus one probing
            # byte, so a grown or replaced file cannot be consumed unbounded.
            chunk = handle.read(min(_ARCHIVE_READ_CHUNK_BYTES, budget - consumed + 1))
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > budget:
                raise SourceBaselineError(
                    f"the baseline snapshot archive exceeds the container bound "
                    f"({consumed} bytes consumed from a changed transfer file); "
                    "an explicit refusal, never partial bootstrap"
                )
            digest.update(chunk)
            chunks.append(chunk)
    data = b"".join(chunks)
    actual = digest.hexdigest()
    if actual != expected_digest:
        raise SourceBaselineError(
            f"snapshot digest mismatch: expected {expected_digest}, the archive hashes to "
            f"{actual}; obtain the correct artifact or expected digest from the maintainer"
        )
    return data, actual


def _read_snapshot_manifest(data: bytes) -> bytes:
    """Return the single regular ``manifest.json`` member of the verified bytes."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            members = tar.getmembers()
            if len(members) != 1:
                raise SourceBaselineError(
                    "a source-baseline archive must contain exactly one "
                    f"{MANIFEST_MEMBER!r} entry; found {len(members)} entries"
                )
            member = members[0]
            if member.name != MANIFEST_MEMBER or not member.isreg():
                raise SourceBaselineError(
                    f"a source-baseline archive must carry one regular {MANIFEST_MEMBER!r} "
                    "entry: links, directories and unexpected payload entries are refused"
                )
            if member.size > MANIFEST_MAX_BYTES:
                raise SourceBaselineError(
                    f"the baseline manifest exceeds the 4 MiB ceiling ({member.size} bytes); "
                    "an explicit refusal, never partial bootstrap"
                )
            stream = tar.extractfile(member)
            if stream is None:
                raise SourceBaselineError(
                    f"a source-baseline archive must carry one regular {MANIFEST_MEMBER!r} entry"
                )
            return stream.read()
    except tarfile.TarError as exc:
        raise SourceBaselineError(
            f"the snapshot is not a valid uncompressed tar archive: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Export (maintainer side).
# ---------------------------------------------------------------------------


def export_source_baseline(
    kb_root: str | Path,
    revision: str,
    *,
    source_registry: SourceRegistry,
    output_path: str | Path,
) -> BaselineExport:
    """Export one metadata-only Source Baseline Snapshot for an exact Git base.

    The snapshot carries only the exact Source Version metadata referenced by
    the selected revision's Source Reference Manifest, read from the selected
    private registry. No original or extracted bytes, availability flags,
    store keys, credentials or local paths are transferred. A referenced
    version missing from the registry (or missing required metadata) blocks
    a complete export.
    """
    captured = capture_revision(kb_root, revision)
    bindings = sorted(
        (
            _BaselineBinding(
                entity_id=entity_id,
                source_id=source_id,
                content_hash=content_hash,
            )
            for entity_id, per_source in captured.manifest.bindings.items()
            for source_id, content_hash in per_source.items()
        ),
        key=lambda binding: (binding.entity_id, binding.source_id),
    )
    if len(bindings) > MAX_BINDING_RECORDS:
        raise SourceBaselineError(
            f"the selected base exceeds the binding-record limit ({len(bindings)} > "
            f"{MAX_BINDING_RECORDS}); an explicit refusal, never partial bootstrap"
        )
    lookup_keys: list[tuple[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    for binding in bindings:
        key = (binding.source_id, binding.content_hash)
        if key not in seen_keys:
            seen_keys.add(key)
            lookup_keys.append(key)
    # One locked, read-only registry view (j0-review F4): the namespace scope
    # and the exact version metadata are captured consistently, and export
    # never assigns or migrates a registry namespace.
    assigned_namespace, found_versions = source_registry.metadata_view(lookup_keys)
    if assigned_namespace is not None and assigned_namespace != captured.manifest.namespace:
        raise SourceBaselineError(
            "the selected registry is explicitly assigned to namespace "
            f"{assigned_namespace!r} and cannot export metadata for "
            f"{captured.manifest.namespace!r}; select the registry for this namespace"
        )
    versions_by_key: dict[tuple[str, str], SourceVersion] = {}
    for key, version in zip(lookup_keys, found_versions, strict=True):
        if version is None:
            raise SourceBaselineError(
                f"the selected base binds {key[0]!r}@{key[1]} to no "
                "exact version in the selected registry; a complete snapshot cannot be exported"
            )
        if version.size is None:
            raise SourceBaselineError(
                f"version {key[0]!r}@{key[1]} lacks the required size "
                "metadata; a complete snapshot cannot be exported"
            )
        versions_by_key[key] = version
    versions = [
        _BaselineVersion(
            source_id=source_id,
            content_hash=content_hash,
            size=version.size,
            content_type=version.content_type,
            filename=version.filename,
            origin_created_at=version.created_at,
        )
        for (source_id, content_hash), version in sorted(versions_by_key.items())
    ]
    if len(versions) > MAX_VERSION_RECORDS:
        raise SourceBaselineError(
            f"the selected base exceeds the version-record limit ({len(versions)} > "
            f"{MAX_VERSION_RECORDS}); an explicit refusal, never partial bootstrap"
        )
    core: dict[str, Any] = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "kind": BASELINE_KIND,
        "namespace": captured.manifest.namespace,
        "kb_subtree": captured.subtree,
        "revision": captured.revision,
        "source_manifest_digest": captured.manifest_digest,
        "bindings": _binding_dicts(bindings),
        "versions": _version_dicts(versions),
    }
    # Deterministic transfer identity: repeated export of the same captured
    # facts is byte-identical, so the same digest legitimately re-verifies.
    transfer_id = hashlib.sha256(_canonical_json(core)).hexdigest()
    payload = _canonical_json({**core, "transfer_id": transfer_id})
    # The exported artifact must satisfy the same strict import parser.
    parsed = _parse_baseline_manifest(payload)
    snapshot_sha256 = _write_snapshot_archive(payload, Path(output_path))
    return BaselineExport(
        schema_version=BASELINE_SCHEMA_VERSION,
        kind=BASELINE_KIND,
        transfer_id=parsed.transfer_id,
        namespace=parsed.namespace,
        kb_subtree=parsed.kb_subtree,
        revision=parsed.revision,
        source_manifest_digest=parsed.source_manifest_digest,
        binding_count=len(parsed.bindings),
        version_count=len(parsed.versions),
        snapshot_sha256=snapshot_sha256,
        output_path=str(Path(output_path)),
    )


# ---------------------------------------------------------------------------
# Inspect/import (contributor side): full validation before any mutation.
# ---------------------------------------------------------------------------


class _ValidatedBaseline:
    """One fully validated snapshot aligned to the selected Git base."""

    def __init__(
        self,
        *,
        parsed: _ParsedBaseline,
        archive_digest: str,
        blockers: list[str],
        versions_to_add: int,
        versions_to_reuse: int,
        confirmation_digest: str,
    ) -> None:
        self.parsed = parsed
        self.archive_digest = archive_digest
        self.blockers = blockers
        self.versions_to_add = versions_to_add
        self.versions_to_reuse = versions_to_reuse
        self.confirmation_digest = confirmation_digest


def _confirmation_digest(parsed: _ParsedBaseline, archive_digest: str) -> str:
    """Bind the exact preview: snapshot bytes, base revision and full coverage."""
    return hashlib.sha256(
        _canonical_json(
            {
                "schema_version": BASELINE_SCHEMA_VERSION,
                "kind": BASELINE_KIND,
                "snapshot_sha256": archive_digest,
                "namespace": parsed.namespace,
                "kb_subtree": parsed.kb_subtree,
                "revision": parsed.revision,
                "source_manifest_digest": parsed.source_manifest_digest,
                "bindings": _binding_dicts(parsed.bindings),
                "versions": _version_dicts(parsed.versions),
            }
        )
    ).hexdigest()


def _validate_baseline(
    kb_root: str | Path,
    snapshot_path: str | Path,
    revision: str,
    *,
    expected_digest: str,
    source_registry: SourceRegistry,
) -> _ValidatedBaseline:
    """Validate a snapshot completely against the selected base before mutation.

    Hard mismatches (digest, format, kind, namespace, subtree, revision,
    source-manifest digest, binding coverage) always raise: the snapshot does
    not describe this base. Registry-dependent conflicts are returned as
    import blockers so a preview can report them without mutating.
    """
    snapshot = Path(snapshot_path)
    if not snapshot.is_file():
        raise SourceBaselineError(f"snapshot file not found: {snapshot}")
    data, archive_digest = _read_verified_archive(snapshot, expected_digest)
    parsed = _parse_baseline_manifest(_read_snapshot_manifest(data))
    captured = capture_revision(kb_root, revision)
    if parsed.namespace != captured.manifest.namespace:
        raise SourceBaselineError(
            f"the snapshot is bound to namespace {parsed.namespace!r}; the selected Knowledge "
            f"Base uses {captured.manifest.namespace!r} — a snapshot cannot cross namespaces"
        )
    if parsed.kb_subtree != captured.subtree:
        raise SourceBaselineError(
            f"the snapshot is bound to KB subtree {parsed.kb_subtree!r}; the selected "
            "Knowledge Base lives at "
            f"{captured.subtree or '<repository root>'!r}"
        )
    if parsed.revision != captured.revision:
        raise SourceBaselineError(
            f"the snapshot is bound to revision {parsed.revision}; it cannot bootstrap base "
            f"{captured.revision} — obtain a snapshot exported for the selected base"
        )
    if parsed.source_manifest_digest != captured.manifest_digest:
        raise SourceBaselineError(
            "the snapshot's source-reference manifest digest does not match the selected "
            "base's manifest; the bases differ"
        )
    expected_bindings = {
        (entity_id, source_id, content_hash)
        for entity_id, per_source in captured.manifest.bindings.items()
        for source_id, content_hash in per_source.items()
    }
    snapshot_bindings = {
        (binding.entity_id, binding.source_id, binding.content_hash) for binding in parsed.bindings
    }
    missing = sorted(expected_bindings - snapshot_bindings)
    if missing:
        entity_id, source_id, content_hash = missing[0]
        raise SourceBaselineError(
            f"incomplete binding coverage: the selected base binds entity {entity_id!r} to "
            f"{source_id!r}@{content_hash}, which the snapshot does not carry"
        )
    extra = sorted(snapshot_bindings - expected_bindings)
    if extra:
        entity_id, source_id, content_hash = extra[0]
        raise SourceBaselineError(
            f"the snapshot carries a binding outside the selected base: entity {entity_id!r} "
            f"to {source_id!r}@{content_hash}"
        )
    blockers: list[str] = []
    assigned = source_registry.assigned_namespace()
    if assigned is not None and assigned != parsed.namespace:
        blockers.append(
            f"the selected registry is already assigned to namespace {assigned!r}; a registry "
            "cannot be silently re-scoped — select the registry for this namespace"
        )
    versions_to_add = 0
    versions_to_reuse = 0
    for version in parsed.versions:
        existing = source_registry.find_version(version.source_id, version.content_hash)
        if existing is None:
            versions_to_add += 1
            continue
        versions_to_reuse += 1
        for field, incoming in (
            ("size", version.size),
            ("filename", version.filename),
            ("content_type", version.content_type),
        ):
            current = getattr(existing, field)
            if incoming is not None and current is not None and incoming != current:
                blockers.append(
                    f"immutable metadata conflict for {version.source_id!r}@"
                    f"{version.content_hash}: {field} is recorded locally as {current!r}, the "
                    f"snapshot carries {incoming!r}; resolve the conflict explicitly"
                )
    return _ValidatedBaseline(
        parsed=parsed,
        archive_digest=archive_digest,
        blockers=blockers,
        versions_to_add=versions_to_add,
        versions_to_reuse=versions_to_reuse,
        confirmation_digest=_confirmation_digest(parsed, archive_digest),
    )


def inspect_source_baseline(
    kb_root: str | Path,
    snapshot_path: str | Path,
    revision: str,
    *,
    expected_digest: str,
    source_registry: SourceRegistry,
) -> BaselinePreview:
    """Preview one baseline import read-only: readiness and blockers, no mutation."""
    validated = _validate_baseline(
        kb_root,
        snapshot_path,
        revision,
        expected_digest=expected_digest,
        source_registry=source_registry,
    )
    parsed = validated.parsed
    return BaselinePreview(
        schema_version=BASELINE_SCHEMA_VERSION,
        kind=BASELINE_KIND,
        ready=not validated.blockers,
        namespace=parsed.namespace,
        kb_subtree=parsed.kb_subtree,
        revision=parsed.revision,
        source_manifest_digest=parsed.source_manifest_digest,
        transfer_id=parsed.transfer_id,
        snapshot_sha256=validated.archive_digest,
        binding_count=len(parsed.bindings),
        version_count=len(parsed.versions),
        versions_to_add=validated.versions_to_add,
        versions_to_reuse=validated.versions_to_reuse,
        blockers=validated.blockers,
        confirmation_digest=validated.confirmation_digest,
    )


def import_source_baseline(
    kb_root: str | Path,
    snapshot_path: str | Path,
    revision: str,
    *,
    expected_digest: str,
    source_registry: SourceRegistry,
    confirmation: str | None = None,
) -> BaselineImport:
    """Import one baseline snapshot; without ``confirmation`` this is a preview.

    With ``confirmation`` (the exact preview digest) the complete input is
    revalidated — a changed snapshot or stale preview refuses — before the
    additive, namespace-scoped registry mutation. New records are created
    ``artifact_available=False``; existing exact versions, locally verified
    availability and unrelated history are never modified. Each imported
    version receives a private origin record binding the snapshot digest and
    base revision; the sender's ``origin_created_at`` is preserved there as
    labeled provenance, never falsified as a local timestamp. Interruptions
    leave only converging immutable residue and refuse as incomplete.
    """
    validated = _validate_baseline(
        kb_root,
        snapshot_path,
        revision,
        expected_digest=expected_digest,
        source_registry=source_registry,
    )
    parsed = validated.parsed
    if confirmation is None:
        return BaselineImport(
            schema_version=BASELINE_SCHEMA_VERSION,
            kind=BASELINE_KIND,
            status="preview",
            namespace=parsed.namespace,
            revision=parsed.revision,
            transfer_id=parsed.transfer_id,
            snapshot_sha256=validated.archive_digest,
            confirmation_digest=validated.confirmation_digest,
            versions_added=0,
            versions_reused=0,
            provenance_records=0,
            blockers=validated.blockers,
        )
    if not isinstance(confirmation, str) or not _HEX64.match(confirmation):
        raise SourceBaselineError(
            "the confirmation must be exactly 64 lowercase hex characters (the preview digest)"
        )
    if confirmation != validated.confirmation_digest:
        raise SourceBaselineError(
            "the confirmation does not bind this exact preview (snapshot digest, revision and "
            "coverage); re-inspect the snapshot and confirm its current preview digest"
        )
    if validated.blockers:
        raise SourceBaselineError(
            "the baseline import is blocked: " + "; ".join(validated.blockers)
        )
    versions_added = 0
    versions_reused = 0
    provenance_records = 0
    entries = [
        (
            version.source_id,
            version.content_hash,
            version.size,
            version.filename,
            version.content_type,
        )
        for version in parsed.versions
    ]
    try:
        # One locked batch validates the complete input and commits once: a
        # conflict or namespace scope refusal mutates nothing (j0-review F3).
        results = source_registry.register_version_metadata_batch(
            entries, namespace=parsed.namespace
        )
    except SourceRegistryError:
        raise
    except OSError as exc:
        raise SourceBaselineError(
            f"the baseline import stopped incomplete before committing (retry is safe; "
            f"immutable residue converges): {exc}"
        ) from exc
    for _, action in results:
        if action == "registered":
            versions_added += 1
        else:
            versions_reused += 1
    try:
        # Origin records follow the committed batch, so a validation conflict
        # never creates purported-import provenance (j0-review F3).
        for version in parsed.versions:
            write_baseline_origin_record(
                source_registry.root,
                namespace=parsed.namespace,
                snapshot_digest=validated.archive_digest,
                revision=parsed.revision,
                source_id=version.source_id,
                content_hash=version.content_hash,
                origin_created_at=version.origin_created_at,
            )
            provenance_records += 1
    except (OSError, RuntimeError, ValueError) as exc:
        raise SourceBaselineError(
            f"the baseline import committed its registry metadata but stopped before "
            f"completing its private origin records (retry converges; a conflicting "
            f"provenance record must be resolved explicitly): {exc}"
        ) from exc
    return BaselineImport(
        schema_version=BASELINE_SCHEMA_VERSION,
        kind=BASELINE_KIND,
        status="imported",
        namespace=parsed.namespace,
        revision=parsed.revision,
        transfer_id=parsed.transfer_id,
        snapshot_sha256=validated.archive_digest,
        confirmation_digest=validated.confirmation_digest,
        versions_added=versions_added,
        versions_reused=versions_reused,
        provenance_records=provenance_records,
        blockers=[],
    )
