"""Private source transfer kinds (spec 0010 §5/§5.1): baseline and full handoff.

J0 delivers the metadata-only **Source Baseline Snapshot**: a distinct,
versioned artifact kind carrying the exact Source Version metadata referenced
by one selected Git base revision — never original or extracted bytes, store
keys, credentials, local paths, availability flags or lifecycle intent. J3
delivers the full **Source Handoff Bundle**: the exact Source Versions and
original bytes selected by new/changed source bindings between two explicit
commits, plus optional supplementary exact references. Both kinds share
strict archive and metadata parsing with explicit bounds; the full bundle is
streamed end to end and never loaded whole into memory.

Integrity model (spec 0010 §5/§5.1): the archive's SHA-256 digest is supplied
out-of-band (maintainer-approved project setup or direct operator selection)
and proves transfer integrity; matching Git bindings prove identity
alignment. Neither establishes that the receiver verified source bytes or
their factual content, and metadata import can never mark an artifact
available — only retained, verified bytes do that. A handoff confers no
content approval, lifecycle activation or Publication Admission.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import msgspec

from lumio_wiki.artifact_store import (
    ArtifactAccessDenied,
    ArtifactStoreError,
    SourceArtifactStore,
)
from lumio_wiki.git_authoring import capture_revision, resolve_repository
from lumio_wiki.mutation import atomic_write_bytes
from lumio_wiki.private_provenance import (
    write_baseline_origin_record,
    write_handoff_origin_record,
)
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
    "CONTAINER_OVERHEAD_MAX_BYTES",
    "HANDOFF_KIND",
    "HANDOFF_SCHEMA_VERSION",
    "MANIFEST_MAX_BYTES",
    "MAX_BINDING_RECORDS",
    "MAX_UNIQUE_PAYLOADS",
    "MAX_VERSION_RECORDS",
    "ORIGINAL_MAX_BYTES",
    "TOTAL_PAYLOAD_MAX_BYTES",
    "BaselineExport",
    "BaselineImport",
    "BaselinePreview",
    "HandoffExport",
    "HandoffImport",
    "HandoffPreview",
    "SourceBaselineError",
    "SourceHandoffError",
    "export_source_baseline",
    "export_source_handoff",
    "import_source_baseline",
    "import_source_handoff",
    "inspect_source_baseline",
    "inspect_source_handoff",
    "parse_reference_selection",
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


# ---------------------------------------------------------------------------
# Full Source Handoff Bundle (spec 0010 §5, plan 0010 J3).
# ---------------------------------------------------------------------------

#: The single supported full-handoff schema version and its distinct kind.
HANDOFF_SCHEMA_VERSION = 1
HANDOFF_KIND = "source-handoff"

#: Default transport ceilings (plan 0010, transfer formats v1). Deployments
#: may lower these module constants; exceeding a bound is always an explicit
#: refusal, never a truncated or silently partial handoff.
ORIGINAL_MAX_BYTES = 512 * 1024 * 1024
TOTAL_PAYLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_UNIQUE_PAYLOADS = 1000
CONTAINER_OVERHEAD_MAX_BYTES = 8 * 1024 * 1024

#: One bounded streaming unit for bundle reads, writes and payload staging.
_HANDOFF_STREAM_CHUNK_BYTES = 1024 * 1024

_HANDOFF_INTENTS = ("new", "update", "reuse")
_ARTIFACT_NAME = re.compile(r"^artifacts/([0-9a-f]{64})$")


class SourceHandoffError(ValueError):
    """A full Source Handoff Bundle operation violated the §5 contract."""


class HandoffExport(msgspec.Struct, frozen=True):
    """The result of one full handoff export (safe, no private paths)."""

    schema_version: int
    kind: str
    transfer_id: str
    namespace: str
    kb_subtree: str
    base_revision: str
    revision: str
    source_manifest_digest: str
    binding_count: int
    version_count: int
    payload_count: int
    bundle_sha256: str
    output_path: str


class HandoffPreview(msgspec.Struct, frozen=True):
    """A read-only full-handoff import preview: readiness, not approval."""

    schema_version: int
    kind: str
    ready: bool
    namespace: str
    kb_subtree: str
    base_revision: str
    revision: str
    source_manifest_digest: str
    transfer_id: str
    bundle_sha256: str
    binding_count: int
    version_count: int
    payload_count: int
    versions_to_add: int
    versions_to_reuse: int
    artifacts_to_retain: int
    blockers: list[str]
    confirmation_digest: str


class HandoffImport(msgspec.Struct, frozen=True):
    """The result of a full-handoff import request (``status``: preview|imported)."""

    schema_version: int
    kind: str
    status: str
    namespace: str
    base_revision: str
    revision: str
    transfer_id: str
    bundle_sha256: str
    confirmation_digest: str | None
    versions_added: int
    versions_reused: int
    artifacts_retained: int
    provenance_records: int
    blockers: list[str]


class _HandoffBinding(msgspec.Struct, frozen=True):
    entity_id: str
    source_id: str
    old_digest: str | None
    new_digest: str | None


class _HandoffVersion(msgspec.Struct, frozen=True):
    source_id: str
    content_hash: str
    size: int
    content_type: str | None
    filename: str | None
    origin_created_at: str
    intent: str


class _ParsedHandoff(msgspec.Struct, frozen=True):
    transfer_id: str
    namespace: str
    kb_subtree: str
    base_revision: str
    revision: str
    source_manifest_digest: str
    bindings: list[_HandoffBinding]
    versions: list[_HandoffVersion]


_HANDOFF_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "transfer_id",
        "namespace",
        "kb_subtree",
        "base_revision",
        "revision",
        "source_manifest_digest",
        "bindings",
        "versions",
    }
)
_HANDOFF_BINDING_KEYS = frozenset({"entity_id", "source_id", "old_digest", "new_digest"})
_HANDOFF_VERSION_KEYS = frozenset(
    {
        "source_id",
        "content_hash",
        "size",
        "content_type",
        "filename",
        "origin_created_at",
        "intent",
    }
)


def _handoff_source_id(value: Any) -> str:
    """Validate one manifest source id, converting to the handoff error type."""
    try:
        return _validate_source_id(value)
    except SourceRegistryError as exc:
        raise SourceHandoffError(str(exc)) from exc


def _require_hex64_or_null(value: Any, what: str) -> str | None:
    if value is None:
        return None
    return _require_hex(value, what, _HEX64)


def _as_handoff_error(exc: SourceBaselineError) -> SourceHandoffError:
    """Own shared strict-parser failures at the handoff boundary (review F2).

    The shared helpers keep raising their baseline error type with baseline
    semantics unchanged; the handoff contract translates them here.
    """
    return SourceHandoffError(str(exc).replace("baseline manifest", "handoff manifest"))


def _parse_handoff_manifest(payload: bytes) -> _ParsedHandoff:
    """Parse and fully validate one source-handoff manifest v1 against the contract.

    Shared baseline strictness helpers raise their own error type; the
    handoff boundary owns every validation failure here (review F2).
    """
    try:
        return _parse_handoff_manifest_impl(payload)
    except SourceBaselineError as exc:
        raise _as_handoff_error(exc) from exc


def _parse_handoff_manifest_impl(payload: bytes) -> _ParsedHandoff:
    """The strict v1 handoff-manifest parser implementation.

    Raises :class:`SourceHandoffError` for its own findings; shared helper
    failures surface as :class:`SourceBaselineError` and are translated by
    the public wrapper above.
    """
    if len(payload) > MANIFEST_MAX_BYTES:
        raise SourceHandoffError(
            f"the handoff manifest exceeds the 4 MiB ceiling ({len(payload)} bytes); "
            "an explicit refusal, never a partial handoff"
        )
    try:
        manifest = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceHandoffError(f"the handoff manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SourceHandoffError("the handoff manifest must be a JSON object")
    _check_keys(manifest, _HANDOFF_MANIFEST_KEYS, "manifest")
    schema_version = manifest["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != HANDOFF_SCHEMA_VERSION
    ):
        raise SourceHandoffError(f"unsupported handoff manifest schema_version: {schema_version!r}")
    if manifest["kind"] != HANDOFF_KIND:
        raise SourceHandoffError(
            f"wrong artifact kind {manifest['kind']!r}: the full-source importer accepts "
            f"only {HANDOFF_KIND!r} bundles; a metadata snapshot cannot transfer originals"
        )
    transfer_id = _require_hex(manifest["transfer_id"], "transfer_id", _HEX64)
    namespace = _require_text(manifest["namespace"], "namespace")
    kb_subtree = manifest["kb_subtree"]
    if not isinstance(kb_subtree, str) or kb_subtree.startswith("/") or ".." in kb_subtree:
        raise SourceHandoffError("handoff manifest field kb_subtree must be a KB-relative path")
    base_revision = _require_hex(manifest["base_revision"], "base_revision", _HEX40)
    revision = _require_hex(manifest["revision"], "revision", _HEX40)
    if base_revision == revision:
        raise SourceHandoffError(
            "the handoff manifest binds an empty Git range: base and contribution "
            "revisions are identical"
        )
    source_manifest_digest = _require_hex(
        manifest["source_manifest_digest"], "source_manifest_digest", _HEX64
    )

    raw_bindings = _require_object_list(manifest["bindings"], "bindings")
    if len(raw_bindings) > MAX_BINDING_RECORDS:
        raise SourceHandoffError(
            f"the handoff manifest exceeds the binding-record limit "
            f"({len(raw_bindings)} > {MAX_BINDING_RECORDS}); an explicit refusal, "
            "never a partial handoff"
        )
    bindings: list[_HandoffBinding] = []
    seen_bindings: set[tuple[str, str]] = set()
    for item in raw_bindings:
        _check_keys(item, _HANDOFF_BINDING_KEYS, "binding record")
        binding = _HandoffBinding(
            entity_id=_require_text(item["entity_id"], "bindings[].entity_id"),
            source_id=_handoff_source_id(item["source_id"]),
            old_digest=_require_hex64_or_null(item["old_digest"], "bindings[].old_digest"),
            new_digest=_require_hex64_or_null(item["new_digest"], "bindings[].new_digest"),
        )
        if binding.old_digest is None and binding.new_digest is None:
            raise SourceHandoffError(
                f"binding record for entity {binding.entity_id!r} and source "
                f"{binding.source_id!r} carries neither an old nor a new digest; "
                "unchanged bindings never enter a handoff"
            )
        if (
            binding.old_digest is not None
            and binding.new_digest is not None
            and binding.old_digest == binding.new_digest
        ):
            raise SourceHandoffError(
                f"binding record for entity {binding.entity_id!r} and source "
                f"{binding.source_id!r} carries one unchanged digest; only binding "
                "changes belong in a handoff"
            )
        key = (binding.entity_id, binding.source_id)
        if key in seen_bindings:
            raise SourceHandoffError(
                f"duplicate binding record for entity {binding.entity_id!r} and "
                f"source {binding.source_id!r}"
            )
        seen_bindings.add(key)
        bindings.append(binding)

    raw_versions = _require_object_list(manifest["versions"], "versions")
    if len(raw_versions) > MAX_VERSION_RECORDS:
        raise SourceHandoffError(
            f"the handoff manifest exceeds the version-record limit "
            f"({len(raw_versions)} > {MAX_VERSION_RECORDS}); an explicit refusal, "
            "never a partial handoff"
        )
    versions: list[_HandoffVersion] = []
    seen_versions: set[tuple[str, str]] = set()
    for item in raw_versions:
        _check_keys(item, _HANDOFF_VERSION_KEYS, "version record")
        size = item["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SourceHandoffError("versions[].size must be a non-negative integer")
        if size > ORIGINAL_MAX_BYTES:
            raise SourceHandoffError(
                f"version record exceeds the per-original size ceiling ({size} bytes); "
                "an explicit refusal, never a partial handoff"
            )
        content_type = item["content_type"]
        if content_type is not None and (not isinstance(content_type, str) or not content_type):
            raise SourceHandoffError("versions[].content_type must be a non-empty string or null")
        intent = item["intent"]
        if intent not in _HANDOFF_INTENTS:
            raise SourceHandoffError("versions[].intent must be one of 'new', 'update' or 'reuse'")
        version = _HandoffVersion(
            source_id=_handoff_source_id(item["source_id"]),
            content_hash=_require_hex(item["content_hash"], "versions[].content_hash", _HEX64),
            size=size,
            content_type=content_type,
            filename=_require_safe_filename(item["filename"], "versions[].filename"),
            origin_created_at=_require_text(
                item["origin_created_at"], "versions[].origin_created_at"
            ),
            intent=intent,
        )
        key = (version.source_id, version.content_hash)
        if key in seen_versions:
            raise SourceHandoffError(
                f"duplicate version record for {version.source_id!r}@{version.content_hash}"
            )
        seen_versions.add(key)
        versions.append(version)

    # Cross-consistency: every binding's new digest must carry a version
    # record, and every version must be justified — a new/update intent by a
    # selected binding change, a reuse intent by the supplementary-reference
    # rule (the exact version is already referenced somewhere).
    selected_new_digests = {
        (binding.source_id, binding.new_digest)
        for binding in bindings
        if binding.new_digest is not None
    }
    version_keys = {(version.source_id, version.content_hash) for version in versions}
    missing = sorted(selected_new_digests - version_keys)
    if missing:
        raise SourceHandoffError(
            f"the handoff manifest binds {missing[0][0]!r}@{missing[0][1]} to no version "
            "record; a changed binding requires its exact version and original bytes"
        )
    unjustified = sorted(
        (version.source_id, version.content_hash, version.intent)
        for version in versions
        if version.intent in ("new", "update")
        and (version.source_id, version.content_hash) not in selected_new_digests
    )
    if unjustified:
        source_id, content_hash, _ = unjustified[0]
        raise SourceHandoffError(
            f"the handoff manifest carries version record {source_id!r}@{content_hash} "
            "not selected by any binding change; a new or updated version must be part "
            "of the reviewed contribution change"
        )

    # One payload per unique digest: versions sharing a digest must agree on
    # its size, and the unique payloads obey their own count and total bounds.
    sizes_by_digest: dict[str, int] = {}
    for version in versions:
        recorded = sizes_by_digest.setdefault(version.content_hash, version.size)
        if recorded != version.size:
            raise SourceHandoffError(
                f"version records for digest {version.content_hash} disagree about size"
            )
    if len(sizes_by_digest) > MAX_UNIQUE_PAYLOADS:
        raise SourceHandoffError(
            f"the handoff manifest exceeds the unique-payload ceiling "
            f"({len(sizes_by_digest)} > {MAX_UNIQUE_PAYLOADS}); an explicit refusal, "
            "never a partial handoff"
        )
    if sum(sizes_by_digest.values()) > TOTAL_PAYLOAD_MAX_BYTES:
        raise SourceHandoffError(
            "the handoff manifest exceeds the total payload ceiling "
            f"({sum(sizes_by_digest.values())} bytes); an explicit refusal, "
            "never a partial handoff"
        )
    return _ParsedHandoff(
        transfer_id=transfer_id,
        namespace=namespace,
        kb_subtree=kb_subtree,
        base_revision=base_revision,
        revision=revision,
        source_manifest_digest=source_manifest_digest,
        bindings=sorted(bindings, key=lambda b: (b.entity_id, b.source_id)),
        versions=sorted(versions, key=lambda v: (v.source_id, v.content_hash)),
    )


def _handoff_binding_dicts(bindings: list[_HandoffBinding]) -> list[dict[str, Any]]:
    return [
        {
            "entity_id": binding.entity_id,
            "source_id": binding.source_id,
            "old_digest": binding.old_digest,
            "new_digest": binding.new_digest,
        }
        for binding in sorted(bindings, key=lambda b: (b.entity_id, b.source_id))
    ]


def _handoff_version_dicts(versions: list[_HandoffVersion]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": version.source_id,
            "content_hash": version.content_hash,
            "size": version.size,
            "content_type": version.content_type,
            "filename": version.filename,
            "origin_created_at": version.origin_created_at,
            "intent": version.intent,
        }
        for version in sorted(versions, key=lambda v: (v.source_id, v.content_hash))
    ]


# ---------------------------------------------------------------------------
# Supplementary exact references (plan 0010 §5/J3): a strict, explicit list.
# ---------------------------------------------------------------------------


def _normalize_reference_records(records: Any) -> list[tuple[str, str]]:
    """Validate explicit ``{"source_id", "content_hash"}`` reference records.

    Both the SDK ``references`` argument and the CLI ``--references`` file use
    the same record shape. Unknown fields, wrong types, invalid labels or
    digests and duplicate logical pairs refuse; there is never an implicit
    latest-version resolution.
    """
    if records is None:
        return []
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise SourceHandoffError("references must be a list of reference records")
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in records:
        if not isinstance(item, Mapping):
            raise SourceHandoffError("each reference record must be an object")
        keys = set(item)
        if keys != {"source_id", "content_hash"}:
            raise SourceHandoffError(
                "each reference record carries exactly 'source_id' and 'content_hash'"
            )
        content_hash = item["content_hash"]
        if not isinstance(content_hash, str) or not _HEX64.match(content_hash):
            raise SourceHandoffError(
                "references[].content_hash must be exactly 64 lowercase hex characters"
            )
        pair = (_handoff_source_id(item["source_id"]), content_hash)
        if pair in seen:
            raise SourceHandoffError(f"duplicate supplementary reference for {pair[0]!r}@{pair[1]}")
        seen.add(pair)
        pairs.append(pair)
    return pairs


def parse_reference_selection(raw: bytes) -> list[dict[str, str]]:
    """Parse one supplementary-reference selection file (strict JSON v1).

    The document is exactly ``{"schema_version": 1, "references":
    [{"source_id": ..., "content_hash": ...}, ...]}``. Duplicate JSON keys,
    unknown fields, wrong types and duplicate logical pairs refuse; every pair
    must resolve in the selected contribution revision's captured bindings.
    Returns the validated records in the SDK ``references`` record shape.
    """
    if not isinstance(raw, bytes):
        raise SourceHandoffError("the references selection must be read as bytes")

    def _reject_duplicate_selection_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        selected: dict[str, Any] = {}
        for key, value in pairs:
            if key in selected:
                raise SourceHandoffError(f"duplicate JSON key {key!r} in the references selection")
            selected[key] = value
        return selected

    try:
        document = json.loads(raw, object_pairs_hook=_reject_duplicate_selection_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceHandoffError(f"the references selection is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SourceHandoffError("the references selection must be a JSON object")
    # Handoff-owned key check (review F2): the shared helper raises the
    # baseline error type, and this document is not a manifest.
    selection_keys = {"schema_version", "references"}
    unknown = sorted(set(document) - selection_keys)
    if unknown:
        raise SourceHandoffError(
            f"the references selection carries unknown field(s): {', '.join(unknown)}"
        )
    missing = sorted(selection_keys - set(document))
    if missing:
        raise SourceHandoffError(
            f"the references selection is missing required field(s): {', '.join(missing)}"
        )
    schema_version = document["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != HANDOFF_SCHEMA_VERSION
    ):
        raise SourceHandoffError(
            f"unsupported references selection schema_version: {schema_version!r}"
        )
    pairs = _normalize_reference_records(document["references"])
    return [
        {"source_id": source_id, "content_hash": content_hash} for source_id, content_hash in pairs
    ]


# ---------------------------------------------------------------------------
# Git-derived selection: binding changes and version intent (plan 0010 J3).
# ---------------------------------------------------------------------------


def _captured_binding_pairs(manifest: Any) -> dict[tuple[str, str], str]:
    """``(entity_id, source_id) -> bound digest`` for one captured manifest."""
    return {
        (entity_id, source_id): digest
        for entity_id, per_source in manifest.bindings.items()
        for source_id, digest in per_source.items()
    }


def _binding_diff(base_manifest: Any, rev_manifest: Any) -> list[_HandoffBinding]:
    """The changed binding records between two captured manifests."""
    base_pairs = _captured_binding_pairs(base_manifest)
    rev_pairs = _captured_binding_pairs(rev_manifest)
    records: list[_HandoffBinding] = []
    for key in sorted(set(base_pairs) | set(rev_pairs)):
        old_digest = base_pairs.get(key)
        new_digest = rev_pairs.get(key)
        if old_digest != new_digest:
            records.append(
                _HandoffBinding(
                    entity_id=key[0], source_id=key[1], old_digest=old_digest, new_digest=new_digest
                )
            )
    return records


def _base_digests_by_source(base_manifest: Any) -> dict[str, set[str]]:
    digests: dict[str, set[str]] = {}
    for (_entity_id, source_id), digest in _captured_binding_pairs(base_manifest).items():
        digests.setdefault(source_id, set()).add(digest)
    return digests


def _derive_intent(
    source_id: str,
    content_hash: str,
    base_digests: Mapping[str, set[str]],
    selected_from_bindings: set[tuple[str, str]],
) -> str:
    """Derive one version's intent from the captured Git range, never the bundle.

    A source id absent from the base is ``new``; an exact version already
    referenced at the base is ``reuse`` (supplementary originals and new
    references to existing versions); a genuinely new digest under a base
    source id is ``update`` — and only when a selected binding change actually
    carries it: supplementary references never confer update intent.
    """
    if source_id not in base_digests:
        return "new"
    if content_hash in base_digests[source_id]:
        return "reuse"
    if (source_id, content_hash) not in selected_from_bindings:
        raise SourceHandoffError(
            f"references cannot confer update intent for {source_id!r}@{content_hash}: "
            "the digest is not a selected binding change of this Git range"
        )
    return "update"


# ---------------------------------------------------------------------------
# Streamed archive I/O with hard cumulative budgets (never whole-file reads).
# ---------------------------------------------------------------------------


class _BudgetedReader(io.RawIOBase):
    """Read-through SHA-256 accounting that refuses beyond the container budget.

    Every byte tarfile consumes — member data, padding and anything drained
    after the end-of-archive marker — passes through exactly once and is
    hashed exactly once. At most ``budget + 1`` bytes are ever requested, and
    the first byte beyond the ceiling refuses BEFORE that chunk is hashed.
    """

    def __init__(self, handle: Any, budget: int) -> None:
        super().__init__()
        self._handle = handle
        self._budget = budget
        self._digest = hashlib.sha256()
        self.consumed = 0
        #: Dynamic F4 ceiling set once the manifest is parsed: manifest bytes
        #: plus declared payload bytes plus the configured overhead limit.
        self.overhead_limit: int | None = None

    def readable(self) -> bool:  # pragma: no cover - io protocol surface
        return True

    def readinto(self, buffer: Any) -> int:
        remaining = self._budget - self.consumed + 1
        if remaining <= 0:
            raise SourceHandoffError(
                f"the source handoff bundle exceeds the container bound "
                f"({self.consumed} bytes consumed); an explicit refusal, never a "
                "partial handoff"
            )
        view = memoryview(buffer).cast("B")
        data = self._handle.read(min(len(view), remaining, _HANDOFF_STREAM_CHUNK_BYTES))
        if not data:
            # D2 (delta review): a terminal end of stream must not skip the
            # independent overhead invariant on bytes already consumed.
            self.enforce_overhead()
            return 0
        self.consumed += len(data)
        if self.consumed > self._budget:
            raise SourceHandoffError(
                f"the source handoff bundle exceeds the container bound "
                f"({self.consumed} bytes consumed from a changed transfer file); "
                "an explicit refusal, never a partial handoff"
            )
        # F4/D2: the ACTUAL container is bounded independently of the unused
        # maximum manifest/payload allowances — the excess refuses as it is
        # consumed, before it is hashed and long before EOF.
        self.enforce_overhead()
        self._digest.update(data)
        view[: len(data)] = data
        return len(data)

    def enforce_overhead(self) -> None:
        """D2/F4: the dynamic independent overhead invariant, enforced on
        already-consumed bytes at activation, on every consumed chunk and at
        EOF — a terminal end of stream can never skip it."""
        if self.overhead_limit is not None and self.consumed > self.overhead_limit:
            raise SourceHandoffError(
                f"the source handoff bundle exceeds the container bound: its "
                f"actual overhead ({self.consumed} bytes consumed against the "
                "manifest, the declared payloads and the configured "
                "container-overhead ceiling) exceeds the independent overhead "
                "limit; an explicit refusal, never a partial handoff"
            )

    def drain(self) -> None:
        while self.read(_HANDOFF_STREAM_CHUNK_BYTES):
            pass

    def close(self) -> None:
        try:
            self._handle.close()
        finally:
            super().close()

    @property
    def digest_hex(self) -> str:
        return self._digest.hexdigest()


class _RegularOnlyTarBlocks(io.RawIOBase):
    """Block-aware passthrough refusing non-regular physical tar records (F3).

    The transfer contract admits ONLY plain regular physical records
    (``manifest.json`` and ``artifacts/<sha256>``). GNU/PAX/sparse extension
    records and special members are refused at their own 512-byte header —
    BEFORE Python's tarfile can process or allocate their bodies — at EVERY
    physical header, not just the first. Serving is strictly single-pass:
    every physical byte read from the handle is handed upstream exactly once,
    so the accounting reader's digest and byte totals stay exact, and header
    reads never cross the 512-byte record boundary.
    """

    _BLOCK = 512

    def __init__(self, handle: Any) -> None:
        super().__init__()
        self._handle = handle
        self._serve = bytearray()
        self._pending_body = 0
        self._header = bytearray()
        self._records = 0
        self._finished = False

    def readable(self) -> bool:  # pragma: no cover - io protocol surface
        return True

    def _consume_header(self) -> None:
        block = bytes(self._header)
        self._header.clear()
        self._records += 1
        if block == b"\x00" * self._BLOCK:
            # End-of-archive marker: the second marker block, record padding
            # and any trailing bytes remain accounting-only and pass through
            # unvalidated, exactly as before.
            self._finished = True
            self._serve.extend(block)
            return
        typeflag = block[156:157]
        if typeflag not in (tarfile.REGTYPE, tarfile.AREGTYPE):
            raise SourceHandoffError(
                f"the bundle carries an unsupported tar extension record at "
                f"physical header {self._records}: type {typeflag!r} is not a "
                "regular file; only plain regular records are allowed, and "
                "forbidden records are refused before their bodies are processed"
            )
        # D1/E1 (delta reviews): take the numeric bytes only up to the FIRST
        # NUL — where tarfile's own numeric parsing also stops — then trim
        # OUTER ASCII spaces only and require the remaining bytes to be plain
        # octal digits (empty means zero). Interior spaces, GNU base-256 lead
        # bytes, signs and every other non-octal byte refuse as noncanonical
        # BEFORE a body span is chosen. This is intentionally STRICTER than
        # tarfile's lenient handling of odd encodings: every field the guard
        # admits yields the same extent tarfile computes, while ambiguous
        # encodings refuse here instead of being silently admitted.
        field = block[124:136]
        cut = field.find(b"\x00")
        text = field if cut == -1 else field[:cut]
        text = text.strip(b" ")
        if any(not 0x30 <= byte <= 0x37 for byte in text):
            raise SourceHandoffError(
                f"physical tar header {self._records} does not carry a plain "
                "octal size field; only plain USTAR regular records are supported"
            )
        size = int(text or b"0", 8)
        # The member's padded body region (data rounded up to the next block)
        # passes through as one region so the next header stays aligned.
        self._pending_body = -(-size // self._BLOCK) * self._BLOCK
        self._serve.extend(block)

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        if not view:
            return 0
        if self._serve:
            take = min(len(view), len(self._serve))
            view[:take] = self._serve[:take]
            del self._serve[:take]
            return take
        if self._finished:
            data = self._handle.read(min(len(view), _HANDOFF_STREAM_CHUNK_BYTES))
            if not data:
                return 0
            view[: len(data)] = data
            return len(data)
        if self._pending_body:
            take = min(len(view), self._pending_body, _HANDOFF_STREAM_CHUNK_BYTES)
            data = self._handle.read(take)
            if not data:
                return 0
            self._pending_body -= len(data)
            view[: len(data)] = data
            return len(data)
        # Header region: never read past the 512-byte header boundary, so an
        # unsupported record refuses after at most its own header block.
        need = self._BLOCK - len(self._header)
        data = self._handle.read(min(len(view), need))
        if not data:
            return 0
        self._header.extend(data)
        if len(self._header) < self._BLOCK:
            return len(data)
        self._consume_header()
        take = min(len(view), len(self._serve))
        view[:take] = self._serve[:take]
        del self._serve[:take]
        return take

    def close(self) -> None:
        try:
            self._handle.close()
        finally:
            super().close()


class _HashingWriter(io.RawIOBase):
    """Write-through SHA-256 accounting with a hard cumulative byte budget.

    NON-OWNING: the surrounding ``with`` block owns the underlying handle.
    This wrapper never closes that handle, and its flush is a no-op once the
    owner has closed it — so an explicit close, and finalization after the
    owning block exits, are both deterministic and can never raise on a
    closed handle. Closing is idempotent.
    """

    def __init__(self, handle: Any, budget: int) -> None:
        super().__init__()
        self._handle = handle
        self._budget = budget
        self._digest = hashlib.sha256()
        self.written = 0

    def writable(self) -> bool:  # pragma: no cover - io protocol surface
        return True

    def write(self, data: Any) -> int:
        if self.closed:
            raise ValueError("write to a closed handoff writer")
        view = memoryview(data).cast("B")
        written = self._handle.write(view)
        self._digest.update(view[:written])
        self.written += written
        if self.written > self._budget:
            raise SourceHandoffError(
                f"the exported handoff archive exceeds the container bound "
                f"({self.written} bytes); an explicit refusal, never a partial handoff"
            )
        return written

    def tell(self) -> int:
        return self._handle.tell()

    def flush(self) -> None:
        # Only flush the owner's handle while it is still open; once the
        # owning block has closed it, flushing is neither needed nor possible.
        if not self._handle.closed:
            self._handle.flush()

    def close(self) -> None:
        # Idempotent and non-owning: flush while the handle is open, then flip
        # the io closed flag WITHOUT closing the owner's handle.
        if self.closed:
            return
        self.flush()
        super().close()

    @property
    def digest_hex(self) -> str:
        return self._digest.hexdigest()


def _normalized_tar_info(name: str, size: int) -> tarfile.TarInfo:
    """One normalized regular-file header: deterministic byte-identical archives."""
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.type = tarfile.REGTYPE
    return info


def _container_budget() -> int:
    return MANIFEST_MAX_BYTES + TOTAL_PAYLOAD_MAX_BYTES + CONTAINER_OVERHEAD_MAX_BYTES


def _refuse_inside_repository(repo_root: Path, path: Path | str, what: str) -> None:
    """Refuse one private selection or transfer path inside the repo (F1)."""
    if Path(path).resolve().is_relative_to(repo_root):
        raise SourceHandoffError(
            f"the {what} must stay outside the content repository; private "
            "selections and transfer artifacts never enter Git (spec 0010 §1/§2.1)"
        )


def _guard_handoff_selections(
    kb_root: str | Path,
    *,
    source_registry: SourceRegistry,
    artifact_store: SourceArtifactStore,
    transfer_paths: Sequence[tuple[Path, str]],
) -> None:
    """F1 containment for every full-handoff operation, BEFORE private I/O.

    Selected registry and local-store roots and every transfer input/output
    path must resolve outside the entire Content Repository, symlinks
    included. Registry and store objects may already exist and their
    constructors do not enforce this boundary, so the roots are re-checked
    here; an S3-backed store exposes no local root and is never rejected by a
    fabricated path check. Profile validation stays as accepted, and legacy
    routes outside the new handoff operations are unchanged.
    """
    repo_root, _subtree = resolve_repository(kb_root)
    registry_root = getattr(source_registry, "root", None)
    if isinstance(registry_root, Path):
        _refuse_inside_repository(repo_root, registry_root, "selected Source Registry")
    store_root = getattr(artifact_store, "root", None)
    if isinstance(store_root, Path):
        _refuse_inside_repository(repo_root, store_root, "selected artifact store")
    for path, what in transfer_paths:
        _refuse_inside_repository(repo_root, path, what)


# ---------------------------------------------------------------------------
# Export (contributor side).
# ---------------------------------------------------------------------------


def export_source_handoff(
    kb_root: str | Path,
    base_revision: str,
    revision: str,
    *,
    source_registry: SourceRegistry,
    artifact_store: SourceArtifactStore,
    output_path: str | Path,
    references: Sequence[Mapping[str, str]] | None = None,
) -> HandoffExport:
    """Export one full Source Handoff Bundle for an explicit Git range.

    Selects the exact Source Versions required by new/changed source bindings
    between ``base_revision`` and ``revision`` — two commits of the SAME
    Knowledge Base namespace — plus explicit supplementary ``references``:
    a sequence of ``{"source_id": ..., "content_hash": ...}`` records, each of
    which must resolve in the selected contribution revision's captured
    bindings (there is never an implicit latest-version resolution). Version
    intent is derived from the captured Git range: ``new`` for a source id
    absent from the base, ``reuse`` for an exact version already referenced
    at the base, ``update`` only when a selected binding change carries the
    new digest. Deleted bindings travel as records with a null ``new_digest``
    and never invent payload.

    Original bytes are read from the selected artifact store one bounded
    original at a time, verified against their registered metadata, and
    streamed into a private temp archive that atomically becomes
    ``output_path`` only on complete success; a missing or corrupt original
    leaves no bundle behind. The output path must stay outside the content
    repository. The manifest carries safe identities, digests, sizes, media
    types and safe filenames only — never local paths, store keys,
    credentials, availability flags or lifecycle state. The bundle's complete
    SHA-256 is returned for out-of-band sharing; the random opaque
    ``transfer_id`` is created once for this artifact, and only a retry of
    this same file preserves it — an independently reconstructed bundle may
    legitimately carry a different identity and digest.
    """
    destination = Path(output_path)
    _guard_handoff_selections(
        kb_root,
        source_registry=source_registry,
        artifact_store=artifact_store,
        transfer_paths=[(destination, "handoff bundle output")],
    )
    base_captured = capture_revision(kb_root, base_revision)
    rev_captured = capture_revision(kb_root, revision)
    if base_captured.revision == rev_captured.revision:
        raise SourceHandoffError(
            "the handoff selects an empty Git range: base and contribution revisions are identical"
        )
    if base_captured.manifest.namespace != rev_captured.manifest.namespace:
        raise SourceHandoffError(
            "the selected base and contribution revisions declare namespaces "
            f"{base_captured.manifest.namespace!r} and "
            f"{rev_captured.manifest.namespace!r}; a handoff never crosses namespaces"
        )
    if base_captured.subtree != rev_captured.subtree:
        raise SourceHandoffError(
            "the selected base and contribution revisions select different Knowledge "
            "Base subtrees; a handoff covers one Knowledge Base"
        )

    reference_pairs = _normalize_reference_records(references)
    rev_pairs = {
        (source_id, digest)
        for (_entity_id, source_id), digest in _captured_binding_pairs(
            rev_captured.manifest
        ).items()
    }
    for pair in reference_pairs:
        if pair not in rev_pairs:
            raise SourceHandoffError(
                f"supplementary reference {pair[0]!r}@{pair[1]} does not resolve in the "
                "selected contribution revision's bindings"
            )

    diff = _binding_diff(base_captured.manifest, rev_captured.manifest)
    if len(diff) > MAX_BINDING_RECORDS:
        raise SourceHandoffError(
            f"the selected Git range exceeds the binding-record limit ({len(diff)} > "
            f"{MAX_BINDING_RECORDS}); an explicit refusal, never a partial handoff"
        )
    selected_from_bindings = {
        (binding.source_id, binding.new_digest)
        for binding in diff
        if binding.new_digest is not None
    }
    selected: list[tuple[str, str]] = []
    seen_selected: set[tuple[str, str]] = set()
    for pair in [*sorted(selected_from_bindings), *sorted(reference_pairs)]:
        if pair not in seen_selected:
            seen_selected.add(pair)
            selected.append(pair)

    # One locked, read-only registry view: namespace scope and the exact
    # version metadata are captured consistently; export never assigns or
    # migrates a registry namespace (j0-review F4 pattern).
    assigned_namespace, found_versions = source_registry.metadata_view(selected)
    if assigned_namespace is not None and assigned_namespace != rev_captured.manifest.namespace:
        raise SourceHandoffError(
            "the selected registry is explicitly assigned to namespace "
            f"{assigned_namespace!r} and cannot export a handoff for "
            f"{rev_captured.manifest.namespace!r}; select the registry for this namespace"
        )
    versions_by_key: dict[tuple[str, str], SourceVersion] = {}
    size_by_digest: dict[str, int] = {}
    for key, version in zip(selected, found_versions, strict=True):
        if version is None:
            raise SourceHandoffError(
                f"the selected contribution binds {key[0]!r}@{key[1]} to no exact "
                "version in the selected registry; a complete handoff cannot be exported"
            )
        if version.size is None:
            raise SourceHandoffError(
                f"version {key[0]!r}@{key[1]} lacks the required size metadata; "
                "a complete handoff cannot be exported"
            )
        versions_by_key[key] = version
        size_by_digest.setdefault(key[1], version.size)
    base_digests = _base_digests_by_source(base_captured.manifest)
    versions = [
        _HandoffVersion(
            source_id=source_id,
            content_hash=content_hash,
            size=versions_by_key[(source_id, content_hash)].size,
            content_type=versions_by_key[(source_id, content_hash)].content_type,
            filename=versions_by_key[(source_id, content_hash)].filename,
            origin_created_at=versions_by_key[(source_id, content_hash)].created_at,
            intent=_derive_intent(source_id, content_hash, base_digests, selected_from_bindings),
        )
        for source_id, content_hash in selected
    ]
    payload_digests = sorted({version.content_hash for version in versions})
    payload_total = sum(size_by_digest.values())
    if len(payload_digests) > MAX_UNIQUE_PAYLOADS:
        raise SourceHandoffError(
            f"the selected Git range exceeds the unique-payload ceiling "
            f"({len(payload_digests)} > {MAX_UNIQUE_PAYLOADS}); an explicit refusal, "
            "never a partial handoff"
        )
    if payload_total > TOTAL_PAYLOAD_MAX_BYTES:
        raise SourceHandoffError(
            f"the selected Git range exceeds the total payload ceiling "
            f"({payload_total} bytes); an explicit refusal, never a partial handoff"
        )

    transfer_id = secrets.token_hex(32)
    core: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "kind": HANDOFF_KIND,
        "transfer_id": transfer_id,
        "namespace": rev_captured.manifest.namespace,
        "kb_subtree": rev_captured.subtree,
        "base_revision": base_captured.revision,
        "revision": rev_captured.revision,
        "source_manifest_digest": rev_captured.manifest_digest,
        "bindings": _handoff_binding_dicts(diff),
        "versions": _handoff_version_dicts(versions),
    }
    payload = _canonical_json(core)
    if len(payload) > MANIFEST_MAX_BYTES:
        raise SourceHandoffError(
            f"the handoff manifest exceeds the 4 MiB ceiling ({len(payload)} bytes); "
            "an explicit refusal, never a partial handoff"
        )
    # The exported artifact must satisfy the same strict import parser.
    parsed = _parse_handoff_manifest(payload)

    representative: dict[str, tuple[str, int]] = {}
    for version in versions:
        representative.setdefault(version.content_hash, (version.source_id, version.size))

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            writer = _HashingWriter(
                handle, len(payload) + payload_total + CONTAINER_OVERHEAD_MAX_BYTES
            )
            try:
                with tarfile.open(fileobj=writer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                    manifest_info = _normalized_tar_info(MANIFEST_MEMBER, len(payload))
                    tar.addfile(manifest_info, io.BytesIO(payload))
                    for digest in payload_digests:
                        source_id, expected_size = representative[digest]
                        try:
                            raw = artifact_store.get_artifact(
                                source_id=source_id, content_hash=digest
                            )
                        except ArtifactStoreError as exc:
                            raise SourceHandoffError(
                                f"original bytes for {source_id!r}@{digest} are unavailable in "
                                f"the selected artifact store; a complete handoff cannot be "
                                f"exported: {exc}"
                            ) from exc
                        if len(raw) != expected_size:
                            raise SourceHandoffError(
                                f"original bytes for {source_id!r}@{digest} do not match the "
                                "recorded size metadata; a complete handoff cannot be exported"
                            )
                        tar.addfile(
                            _normalized_tar_info(f"artifacts/{digest}", len(raw)), io.BytesIO(raw)
                        )
                        del raw  # one bounded original in memory at a time
            finally:
                # Tar finalization (end blocks and record padding) runs through
                # the writer before the digest is ever read; the wrapper closes
                # deterministically here on success AND failure, and never owns
                # the underlying handle.
                writer.close()
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

    return HandoffExport(
        schema_version=HANDOFF_SCHEMA_VERSION,
        kind=HANDOFF_KIND,
        transfer_id=transfer_id,
        namespace=parsed.namespace,
        kb_subtree=parsed.kb_subtree,
        base_revision=parsed.base_revision,
        revision=parsed.revision,
        source_manifest_digest=parsed.source_manifest_digest,
        binding_count=len(parsed.bindings),
        version_count=len(parsed.versions),
        payload_count=len(payload_digests),
        bundle_sha256=writer.digest_hex,
        output_path=str(destination),
    )


# ---------------------------------------------------------------------------
# Inspect/import (maintainer side): complete streamed validation first.
# ---------------------------------------------------------------------------


class _ValidatedHandoff:
    """One fully validated handoff bundle aligned to the selected Git range."""

    def __init__(
        self,
        *,
        parsed: _ParsedHandoff,
        archive_digest: str,
        blockers: list[str],
        versions_to_add: int,
        versions_to_reuse: int,
        artifacts_to_retain: int,
        confirmation_digest: str,
        staging_dir: Path | None,
    ) -> None:
        self.parsed = parsed
        self.archive_digest = archive_digest
        self.blockers = blockers
        self.versions_to_add = versions_to_add
        self.versions_to_reuse = versions_to_reuse
        self.artifacts_to_retain = artifacts_to_retain
        self.confirmation_digest = confirmation_digest
        self.staging_dir = staging_dir


def _handoff_confirmation_digest(parsed: _ParsedHandoff, archive_digest: str) -> str:
    """Bind the exact preview: bundle bytes, Git range and complete selection."""
    return hashlib.sha256(
        _canonical_json(
            {
                "schema_version": HANDOFF_SCHEMA_VERSION,
                "kind": HANDOFF_KIND,
                "bundle_sha256": archive_digest,
                "namespace": parsed.namespace,
                "kb_subtree": parsed.kb_subtree,
                "base_revision": parsed.base_revision,
                "revision": parsed.revision,
                "source_manifest_digest": parsed.source_manifest_digest,
                "bindings": _handoff_binding_dicts(parsed.bindings),
                "versions": _handoff_version_dicts(parsed.versions),
                "payloads": sorted({version.content_hash for version in parsed.versions}),
            }
        )
    ).hexdigest()


def _stream_validate_handoff(
    bundle_path: Path,
    expected_digest: str,
    *,
    staging_dir: Path | None,
) -> tuple[_ParsedHandoff, str]:
    """Stream one bundle end to end: digest, inventory and every payload.

    The whole file — member data, tar padding and any trailing content — is
    consumed through one bounded reader and hashed exactly once; nothing is
    read a second time and no multi-source archive is ever loaded whole.
    Payloads are verified per member (declared size plus SHA-256 against the
    entry name) and, when ``staging_dir`` is given, staged to generated paths
    for a later import; without staging the bytes are simply discarded
    (preview creates no canonical state).
    """
    if not isinstance(expected_digest, str) or not _HEX64.match(expected_digest):
        raise SourceHandoffError(
            "the expected bundle digest must be exactly 64 lowercase hex characters"
        )
    if not bundle_path.is_file():
        raise SourceHandoffError(f"bundle file not found: {bundle_path}")
    budget = _container_budget()
    size = bundle_path.stat().st_size
    if size > budget:
        raise SourceHandoffError(
            f"the source handoff bundle exceeds the container bound ({size} bytes); "
            "an explicit refusal, never a partial handoff"
        )
    if staging_dir is not None:
        staging_dir.mkdir(parents=True, exist_ok=True)
    parsed: _ParsedHandoff | None = None
    expected_sizes: dict[str, int] = {}
    seen_payloads: set[str] = set()
    seen_names: set[str] = set()
    payload_total = 0
    try:
        handle = open(bundle_path, "rb")
    except OSError as exc:
        raise SourceHandoffError(f"the bundle could not be opened: {exc}") from exc
    with _BudgetedReader(_RegularOnlyTarBlocks(handle), budget) as reader:
        try:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                for member in tar:
                    if member.name == MANIFEST_MEMBER:
                        if parsed is not None:
                            raise SourceHandoffError(
                                "a source-handoff archive carries exactly one "
                                f"{MANIFEST_MEMBER!r} entry; a duplicate entry is refused"
                            )
                        if not member.isreg():
                            raise SourceHandoffError(
                                f"a source-handoff archive must carry one regular "
                                f"{MANIFEST_MEMBER!r} entry: links, directories and "
                                "devices are refused"
                            )
                        if member.size > MANIFEST_MAX_BYTES:
                            raise SourceHandoffError(
                                f"the handoff manifest exceeds the 4 MiB ceiling "
                                f"({member.size} bytes); an explicit refusal, never a "
                                "partial handoff"
                            )
                        stream = tar.extractfile(member)
                        if stream is None:  # pragma: no cover - isreg checked above
                            raise SourceHandoffError(
                                f"a source-handoff archive must carry one regular "
                                f"{MANIFEST_MEMBER!r} entry"
                            )
                        parsed = _parse_handoff_manifest(stream.read(MANIFEST_MAX_BYTES + 1))
                        expected_sizes = {
                            version.content_hash: version.size for version in parsed.versions
                        }
                        # F4: bound the ACTUAL container independently of the
                        # maximum manifest/payload allowances — everything
                        # beyond the manifest, the declared payloads and the
                        # configured overhead ceiling refuses as consumed,
                        # INCLUDING bytes already consumed at activation (D2).
                        reader.overhead_limit = (
                            member.size
                            + sum(expected_sizes.values())
                            + CONTAINER_OVERHEAD_MAX_BYTES
                        )
                        reader.enforce_overhead()
                        seen_names.add(member.name)
                        continue
                    if parsed is None:
                        raise SourceHandoffError(
                            f"a source-handoff archive must carry its {MANIFEST_MEMBER!r} "
                            "entry first; payload entries never precede the manifest"
                        )
                    match = _ARTIFACT_NAME.match(member.name)
                    if match is None:
                        raise SourceHandoffError(
                            f"unexpected archive entry {member.name!r}: only "
                            f"{MANIFEST_MEMBER!r} and 'artifacts/<sha256>' regular "
                            "entries are allowed"
                        )
                    digest = match.group(1)
                    if member.name in seen_names:
                        raise SourceHandoffError(f"duplicate archive entry {member.name!r}")
                    if not member.isreg():
                        raise SourceHandoffError(
                            f"the archive member {member.name!r} is not a regular file: "
                            "links, directories and devices are refused"
                        )
                    if digest not in expected_sizes:
                        raise SourceHandoffError(
                            f"the bundle carries artifact entry {member.name!r} that no "
                            "version record declares"
                        )
                    if member.size != expected_sizes[digest]:
                        raise SourceHandoffError(
                            f"artifact payload {digest} does not carry its declared size "
                            f"({member.size} bytes, the manifest declares "
                            f"{expected_sizes[digest]})"
                        )
                    seen_names.add(member.name)
                    seen_payloads.add(digest)
                    payload_total += member.size
                    if len(seen_payloads) > MAX_UNIQUE_PAYLOADS:
                        raise SourceHandoffError(
                            f"the bundle exceeds the unique-payload ceiling "
                            f"({len(seen_payloads)} > {MAX_UNIQUE_PAYLOADS}); an explicit "
                            "refusal, never a partial handoff"
                        )
                    if payload_total > TOTAL_PAYLOAD_MAX_BYTES:
                        raise SourceHandoffError(
                            f"the bundle exceeds the total payload ceiling "
                            f"({payload_total} bytes); an explicit refusal, never a "
                            "partial handoff"
                        )
                    stream = tar.extractfile(member)
                    if stream is None:  # pragma: no cover - isreg checked above
                        raise SourceHandoffError(
                            f"the archive member {member.name!r} is not readable as a regular file"
                        )
                    payload_digest = hashlib.sha256()
                    staged_path = (
                        staging_dir / f"{digest}.payload" if staging_dir is not None else None
                    )
                    staged_handle = open(staged_path, "wb") if staged_path is not None else None
                    actual = 0
                    try:
                        while True:
                            chunk = stream.read(_HANDOFF_STREAM_CHUNK_BYTES)
                            if not chunk:
                                break
                            actual += len(chunk)
                            payload_digest.update(chunk)
                            if staged_handle is not None:
                                staged_handle.write(chunk)
                    except OSError as exc:
                        raise SourceHandoffError(
                            f"private staging of payload {digest} failed: {exc}"
                        ) from exc
                    finally:
                        if staged_handle is not None:
                            staged_handle.close()
                    if actual != member.size:
                        raise SourceHandoffError(
                            f"artifact payload {digest} carries {actual} bytes, not the "
                            f"declared {member.size}"
                        )
                    if payload_digest.hexdigest() != digest:
                        raise SourceHandoffError(
                            f"artifact payload {digest} does not hash to its declared "
                            "digest: corrupt transfer bytes are refused"
                        )
        except tarfile.TarError as exc:
            raise SourceHandoffError(
                f"the bundle is not a valid uncompressed tar archive: {exc}"
            ) from exc
        if parsed is None:
            raise SourceHandoffError(
                f"a source-handoff archive must carry one regular {MANIFEST_MEMBER!r} entry first"
            )
        missing = sorted(set(expected_sizes) - seen_payloads)
        if missing:
            raise SourceHandoffError(
                f"the handoff manifest declares version payload {missing[0]} but the "
                "archive carries no such artifact entry: a missing entry is refused"
            )
        reader.drain()
        actual_digest = reader.digest_hex
    if actual_digest != expected_digest:
        raise SourceHandoffError(
            f"bundle digest mismatch: expected {expected_digest}, the archive hashes to "
            f"{actual_digest}; obtain the correct artifact or expected digest from the "
            "maintainer"
        )
    return parsed, actual_digest


def _validate_handoff(
    kb_root: str | Path,
    bundle_path: str | Path,
    revision: str,
    *,
    expected_digest: str,
    source_registry: SourceRegistry,
    artifact_store: SourceArtifactStore,
    staging_dir: Path | None = None,
) -> _ValidatedHandoff:
    """Validate one bundle completely against the selected Git range.

    Hard mismatches (digest, format, kind, namespace, subtree, revisions,
    source-manifest digest, binding changes, selected versions, derived
    intent) always raise: the bundle does not describe this contribution.
    Registry- and store-dependent conflicts are returned as import blockers
    so a preview can report them without mutating anything. The archive,
    every payload and every record is verified before any caller performs a
    canonical write. Containment (review F1) is enforced before any private
    read or write: the selected registry/store roots and the bundle path
    itself must resolve outside the entire Content Repository.
    """
    _guard_handoff_selections(
        kb_root,
        source_registry=source_registry,
        artifact_store=artifact_store,
        transfer_paths=[(Path(bundle_path), "handoff bundle")],
    )
    parsed, archive_digest = _stream_validate_handoff(
        Path(bundle_path), expected_digest, staging_dir=staging_dir
    )
    rev_captured = capture_revision(kb_root, revision)
    if parsed.revision != rev_captured.revision:
        raise SourceHandoffError(
            f"the bundle is bound to revision {parsed.revision}; it cannot be imported "
            f"against {rev_captured.revision} — obtain a bundle exported for the "
            "selected contribution"
        )
    if parsed.namespace != rev_captured.manifest.namespace:
        raise SourceHandoffError(
            f"the bundle is bound to namespace {parsed.namespace!r}; the selected "
            f"Knowledge Base uses {rev_captured.manifest.namespace!r} — a bundle "
            "cannot cross namespaces"
        )
    if parsed.kb_subtree != rev_captured.subtree:
        raise SourceHandoffError(
            f"the bundle is bound to KB subtree {parsed.kb_subtree!r}; the selected "
            "Knowledge Base lives at "
            f"{rev_captured.subtree or '<repository root>'!r}"
        )
    if parsed.source_manifest_digest != rev_captured.manifest_digest:
        raise SourceHandoffError(
            "the bundle's source-reference manifest digest does not match the selected "
            "contribution's manifest; the contributions differ"
        )
    base_captured = capture_revision(kb_root, parsed.base_revision)
    if (
        base_captured.manifest.namespace != rev_captured.manifest.namespace
        or base_captured.subtree != rev_captured.subtree
    ):
        raise SourceHandoffError(
            "the bundle's base and contribution revisions do not describe one "
            "Knowledge Base namespace and subtree"
        )
    recomputed = _binding_diff(base_captured.manifest, rev_captured.manifest)
    if [(b.entity_id, b.source_id, b.old_digest, b.new_digest) for b in recomputed] != [
        (b.entity_id, b.source_id, b.old_digest, b.new_digest) for b in parsed.bindings
    ]:
        raise SourceHandoffError(
            "the bundle's binding changes disagree with the selected Git range"
        )
    base_digests = _base_digests_by_source(base_captured.manifest)
    selected_from_bindings = {
        (binding.source_id, binding.new_digest)
        for binding in recomputed
        if binding.new_digest is not None
    }
    rev_pairs = {
        (source_id, digest)
        for (_entity_id, source_id), digest in _captured_binding_pairs(
            rev_captured.manifest
        ).items()
    }
    for version in parsed.versions:
        if (version.source_id, version.content_hash) not in rev_pairs:
            raise SourceHandoffError(
                f"version {version.source_id!r}@{version.content_hash} is not "
                "referenced by the selected contribution revision"
            )
        expected_intent = _derive_intent(
            version.source_id, version.content_hash, base_digests, selected_from_bindings
        )
        if version.intent != expected_intent:
            raise SourceHandoffError(
                f"version {version.source_id!r}@{version.content_hash} declares intent "
                f"{version.intent!r}; the reviewed Git change derives "
                f"{expected_intent!r}"
            )

    blockers: list[str] = []
    assigned = source_registry.assigned_namespace()
    if assigned is not None and assigned != parsed.namespace:
        blockers.append(
            f"the selected registry is already assigned to namespace {assigned!r}; a "
            "registry cannot be silently re-scoped — select the registry for this "
            "namespace"
        )
    sources = {source.source_id: source for source in source_registry.list()}
    versions_to_add = 0
    versions_to_reuse = 0
    artifacts_to_retain = 0
    for version in parsed.versions:
        source = sources.get(version.source_id)
        existing = None
        if source is not None:
            existing = next(
                (
                    recorded
                    for recorded in source.versions
                    if recorded.content_hash == version.content_hash
                ),
                None,
            )
        if existing is None:
            versions_to_add += 1
            if version.intent == "new" and source is not None:
                blockers.append(
                    f"ambiguous new source identity for {version.source_id!r}: the local "
                    "registry already knows this source; an update requires explicit "
                    "reviewed intent, not a new identity"
                )
        else:
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
                        f"{version.content_hash}: {field} is recorded locally as "
                        f"{current!r}, the bundle carries {incoming!r}; resolve the "
                        "conflict explicitly"
                    )
        try:
            retained = artifact_store.artifact_exists(
                source_id=version.source_id, content_hash=version.content_hash
            )
        except ArtifactAccessDenied:
            blockers.append(
                "the selected artifact store denied a coverage read; resolve access "
                "before importing"
            )
            continue
        if not retained:
            artifacts_to_retain += 1
    return _ValidatedHandoff(
        parsed=parsed,
        archive_digest=archive_digest,
        blockers=blockers,
        versions_to_add=versions_to_add,
        versions_to_reuse=versions_to_reuse,
        artifacts_to_retain=artifacts_to_retain,
        confirmation_digest=_handoff_confirmation_digest(parsed, archive_digest),
        staging_dir=staging_dir,
    )


def inspect_source_handoff(
    kb_root: str | Path,
    bundle_path: str | Path,
    revision: str,
    *,
    expected_digest: str,
    source_registry: SourceRegistry,
    artifact_store: SourceArtifactStore,
) -> HandoffPreview:
    """Preview one full-handoff import read-only: readiness and blockers.

    The complete bundle is streamed, hashed and verified against the selected
    contribution revision and the destination registry/store, but no
    canonical state is created: preview grants no approval and changes
    nothing.
    """
    validated = _validate_handoff(
        kb_root,
        bundle_path,
        revision,
        expected_digest=expected_digest,
        source_registry=source_registry,
        artifact_store=artifact_store,
    )
    parsed = validated.parsed
    return HandoffPreview(
        schema_version=HANDOFF_SCHEMA_VERSION,
        kind=HANDOFF_KIND,
        ready=not validated.blockers,
        namespace=parsed.namespace,
        kb_subtree=parsed.kb_subtree,
        base_revision=parsed.base_revision,
        revision=parsed.revision,
        source_manifest_digest=parsed.source_manifest_digest,
        transfer_id=parsed.transfer_id,
        bundle_sha256=validated.archive_digest,
        binding_count=len(parsed.bindings),
        version_count=len(parsed.versions),
        payload_count=len({version.content_hash for version in parsed.versions}),
        versions_to_add=validated.versions_to_add,
        versions_to_reuse=validated.versions_to_reuse,
        artifacts_to_retain=validated.artifacts_to_retain,
        blockers=validated.blockers,
        confirmation_digest=validated.confirmation_digest,
    )


def import_source_handoff(
    kb_root: str | Path,
    bundle_path: str | Path,
    revision: str,
    *,
    expected_digest: str,
    source_registry: SourceRegistry,
    artifact_store: SourceArtifactStore,
    confirmation: str | None = None,
) -> HandoffImport:
    """Import one full Source Handoff Bundle; without ``confirmation`` preview.

    The complete input — archive digest, every payload, inventory, Git
    alignment, derived intent and current canonical metadata — is revalidated
    before any canonical write, and ``confirmation`` must bind the exact
    reviewed preview. The import then commits the additive metadata batch
    (with the atomic new-source identity constraint), retains the verified
    staged bytes through create-only store operations, marks availability
    only after retained bytes verify, and records private origin provenance
    binding the bundle digest and the ORIGINAL handoff revisions with the
    sender's timestamp. A real post-validation I/O failure reports the import
    as incomplete and leaves only reusable immutable residue; retry converges
    without overwriting existing history. Import never changes authored
    pages, lifecycle state or publication.
    """
    staging_dir = Path(tempfile.mkdtemp(prefix="lumio-source-handoff-"))
    try:
        validated = _validate_handoff(
            kb_root,
            bundle_path,
            revision,
            expected_digest=expected_digest,
            source_registry=source_registry,
            artifact_store=artifact_store,
            staging_dir=staging_dir,
        )
        parsed = validated.parsed
        if confirmation is None:
            return HandoffImport(
                schema_version=HANDOFF_SCHEMA_VERSION,
                kind=HANDOFF_KIND,
                status="preview",
                namespace=parsed.namespace,
                base_revision=parsed.base_revision,
                revision=parsed.revision,
                transfer_id=parsed.transfer_id,
                bundle_sha256=validated.archive_digest,
                confirmation_digest=validated.confirmation_digest,
                versions_added=0,
                versions_reused=0,
                artifacts_retained=0,
                provenance_records=0,
                blockers=validated.blockers,
            )
        if not isinstance(confirmation, str) or not _HEX64.match(confirmation):
            raise SourceHandoffError(
                "the confirmation must be exactly 64 lowercase hex characters (the preview digest)"
            )
        if confirmation != validated.confirmation_digest:
            raise SourceHandoffError(
                "the confirmation does not bind this exact preview (bundle digest, Git "
                "range and selection); re-inspect the bundle and confirm its current "
                "preview digest"
            )
        if validated.blockers:
            raise SourceHandoffError(
                "the source handoff import is blocked: " + "; ".join(validated.blockers)
            )
        new_source_ids = sorted(
            {version.source_id for version in parsed.versions if version.intent == "new"}
        )
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
            # One locked additive batch with the atomic identity-intent
            # constraint: a new-intent source id a cooperating writer already
            # registered refuses under the same fresh state, before commit.
            results = source_registry.register_version_metadata_batch(
                entries,
                namespace=parsed.namespace,
                new_source_ids=new_source_ids or None,
            )
        except SourceRegistryError:
            raise
        except OSError as exc:
            raise SourceHandoffError(
                f"the handoff import stopped incomplete before committing (retry is "
                f"safe; immutable residue converges): {exc}"
            ) from exc
        versions_added = sum(1 for _, action in results if action == "registered")
        versions_reused = len(results) - versions_added
        try:
            # Retain the VERIFIED staged bytes — never a second unverified
            # mutable-path read — one bounded original at a time, create-only.
            for version in parsed.versions:
                raw = (staging_dir / f"{version.content_hash}.payload").read_bytes()
                artifact_store.put_artifact(
                    source_id=version.source_id,
                    content_hash=version.content_hash,
                    raw_bytes=raw,
                    content_type=version.content_type,
                    filename=version.filename,
                )
                del raw
            # Availability is marked only after the retained bytes verified.
            for version in parsed.versions:
                source_registry.record_artifact_binding(version.source_id, version.content_hash)
        except (ArtifactStoreError, SourceRegistryError, OSError) as exc:
            raise SourceHandoffError(
                f"the handoff import committed its registry metadata but stopped "
                f"before completing retained originals (retry converges; reusable "
                f"immutable residue is kept and never rolled back): {exc}"
            ) from exc
        provenance_records = 0
        try:
            for version in parsed.versions:
                write_handoff_origin_record(
                    source_registry.root,
                    namespace=parsed.namespace,
                    bundle_digest=validated.archive_digest,
                    base_revision=parsed.base_revision,
                    revision=parsed.revision,
                    source_id=version.source_id,
                    content_hash=version.content_hash,
                    origin_created_at=version.origin_created_at,
                )
                provenance_records += 1
        except (OSError, RuntimeError, ValueError) as exc:
            raise SourceHandoffError(
                f"the handoff import committed its registry metadata and retained "
                f"originals but stopped before completing its private origin records "
                f"(retry converges; a conflicting provenance record must be resolved "
                f"explicitly): {exc}"
            ) from exc
        return HandoffImport(
            schema_version=HANDOFF_SCHEMA_VERSION,
            kind=HANDOFF_KIND,
            status="imported",
            namespace=parsed.namespace,
            base_revision=parsed.base_revision,
            revision=parsed.revision,
            transfer_id=parsed.transfer_id,
            bundle_sha256=validated.archive_digest,
            confirmation_digest=validated.confirmation_digest,
            versions_added=versions_added,
            versions_reused=versions_reused,
            artifacts_retained=len(parsed.versions),
            provenance_records=provenance_records,
            blockers=[],
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
