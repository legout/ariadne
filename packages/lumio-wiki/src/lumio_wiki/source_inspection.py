"""Authorized Source Artifact inspection and fetch (issue #165, ADR-0020).

`lumio-wiki source inspect|fetch|link` resolve ONE exact Source Version for a
source id — either the latest registry version (local worktree behavior) or
the version bound by a private Source Binding Manifest (an S3 Knowledge Base
or an explicit ``--published-version``) — and then operate on it through the
public :class:`~lumio_wiki.artifact_store.SourceArtifactStore` seam. Resolution
is identity-oriented: there is no fetch-by-hash and no object-key interface,
and a binding that cannot be resolved NEVER silently substitutes the latest
Source Version.

Every failure is one of a fixed set of distinct actionable outcomes (issue
#165): access denied, absent binding, unavailable artifact, corruption,
historical-version mismatch, and signing unsupported. Messages are secret-free
by construction: no credentials, private object keys, secret-bearing URLs, or
invalid (possibly secret-bearing) source ids are ever echoed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import msgspec

from lumio_wiki.artifact_store import (
    ArtifactAccessDenied,
    ArtifactCorruption,
    ArtifactUnavailable,
    SourceArtifactStore,
    SourceBindingManifest,
)
from lumio_wiki.source_references import SourceReferenceManifest
from lumio_wiki.source_registry import SourceRegistry, SourceRegistryError

#: The caller is not authorized to read the private Source Artifact Store.
OUTCOME_ACCESS_DENIED = "access-denied"

#: The source id has no binding in the selected view (registry or manifest).
OUTCOME_ABSENT_BINDING = "absent-binding"

#: The binding resolves, but no artifact is retained for it.
OUTCOME_UNAVAILABLE = "unavailable-artifact"

#: Stored bytes (or the stored manifest) failed verification.
OUTCOME_CORRUPTION = "corruption"

#: The requested Published Version has no exact private binding.
OUTCOME_HISTORICAL_VERSION_MISMATCH = "historical-version-mismatch"

#: The source identity is bound to multiple exact versions in the selected view.
OUTCOME_AMBIGUOUS_BINDING = "ambiguous-binding"

#: The configured store cannot issue signed GET URLs.
OUTCOME_SIGNING_UNSUPPORTED = "signing-unsupported"


class SourceInspectionError(Exception):
    """A distinct, actionable Source Artifact inspection outcome (#165).

    ``outcome`` is one of the ``OUTCOME_*`` constants so callers (CLI,
    Workshop) can branch on the outcome — never on message text. The message
    is secret-free by construction.
    """

    def __init__(self, outcome: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(frozen=True)
class ResolvedSourceBinding:
    """The ONE exact Source Version an inspect/fetch/link operates on.

    Carries only secret-free inspection metadata recorded at the ingest
    boundary (#164): safe filename, media type, and size.
    """

    source_id: str
    content_hash: str
    filename: str | None
    content_type: str | None
    size: int | None
    #: The Published Version or Git revision whose exact manifest bound this hash.
    published_version: str | None


def resolve_registry_binding(
    registry: SourceRegistry,
    source_id: str,
    content_hash: str,
    *,
    published_version: str | None = None,
) -> ResolvedSourceBinding:
    """Resolve one exact pinned hash through append-only registry history."""
    try:
        registry.get(source_id)
        version = registry.find_version(source_id, content_hash)
    except SourceRegistryError as exc:
        raise SourceInspectionError(OUTCOME_ABSENT_BINDING, str(exc)) from exc
    if version is None:
        raise SourceInspectionError(
            OUTCOME_HISTORICAL_VERSION_MISMATCH,
            "the exact Source Version pinned by this manifest is absent from registry history",
        )
    return ResolvedSourceBinding(
        source_id=source_id,
        content_hash=version.content_hash,
        filename=version.filename,
        content_type=version.content_type,
        size=version.size,
        published_version=published_version,
    )


def resolve_source_reference_binding(
    registry: SourceRegistry,
    manifest: SourceReferenceManifest,
    source_id: str,
    *,
    entity_id: str | None = None,
    published_version: str | None = None,
) -> ResolvedSourceBinding:
    """Resolve a Git authoring pin, never the registry's latest version."""
    from lumio_wiki.source_registry import _validate_source_id

    try:
        _validate_source_id(source_id)
    except SourceRegistryError as exc:
        raise SourceInspectionError(OUTCOME_ABSENT_BINDING, str(exc)) from exc
    matches = [
        (page_id, digest)
        for page_id, bindings in manifest.bindings.items()
        for bound_id, digest in bindings.items()
        if bound_id == source_id and (entity_id is None or page_id == entity_id)
    ]
    if not matches:
        raise SourceInspectionError(
            OUTCOME_ABSENT_BINDING,
            "the selected authoring manifest does not bind this source id",
        )
    hashes = {digest for _, digest in matches}
    if len(hashes) != 1:
        raise SourceInspectionError(
            OUTCOME_AMBIGUOUS_BINDING,
            "the selected authoring manifest binds this source id to multiple exact "
            "Source Versions; resolve it from a specific Entity",
        )
    return resolve_registry_binding(
        registry, source_id, next(iter(hashes)), published_version=published_version
    )


def read_binding_manifest(
    artifact_store: SourceArtifactStore,
    version: str,
) -> SourceBindingManifest:
    """Read and decode ONE Published Version's private binding manifest.

    Maps store failures to the distinct #165 outcomes (access denied,
    historical-version mismatch, corruption) exactly as
    :func:`resolve_manifest_binding` does; callers that only need the entry
    set (e.g. ``source resolve`` known-ids, issue #176) share this seam
    instead of re-implementing the error mapping.
    """
    try:
        raw = artifact_store.get_binding_manifest(version)
    except ArtifactAccessDenied as exc:
        raise SourceInspectionError(OUTCOME_ACCESS_DENIED, str(exc)) from exc
    except ArtifactUnavailable as exc:
        raise SourceInspectionError(
            OUTCOME_HISTORICAL_VERSION_MISMATCH,
            f"no Source Binding Manifest for published version {version!r} — "
            "the version does not exist or predates Source Artifact retention; "
            "refusing to substitute the latest Source Version",
        ) from exc
    try:
        manifest = msgspec.json.decode(raw, type=SourceBindingManifest)
    except msgspec.DecodeError as exc:
        raise SourceInspectionError(
            OUTCOME_CORRUPTION,
            "the stored Source Binding Manifest is malformed",
        ) from exc
    # ADR-0020: the manifest binds the Published Version identity. A stored
    # manifest that names a different version than the one requested is
    # corruption (misplaced or tampered), never a usable binding.
    if manifest.published_version != version:
        raise SourceInspectionError(
            OUTCOME_CORRUPTION,
            "the stored Source Binding Manifest does not match the requested published version",
        )
    return manifest


def resolve_manifest_binding(
    artifact_store: SourceArtifactStore,
    version: str,
    source_id: str,
    *,
    entity_id: str | None = None,
) -> ResolvedSourceBinding:
    """Resolve a source id through ONE Published Version's binding manifest.

    Used when ``--published-version`` is explicit or when the Knowledge Base
    is an S3 Location whose active Published Version was resolved once. The
    manifest is read from the private Source Artifact Store, so no manifest
    means either the version does not exist or it predates artifact retention
    — both are the historical-version-mismatch outcome, and neither ever
    falls back to the registry's latest version (ADR-0020).
    """
    from lumio_wiki.source_registry import _validate_source_id

    # Boundary validation mirrors the registry: an invalid (possibly
    # secret-bearing) id is rejected generically and never echoed.
    try:
        _validate_source_id(source_id)
    except SourceRegistryError as exc:
        raise SourceInspectionError(OUTCOME_ABSENT_BINDING, str(exc)) from exc
    manifest = read_binding_manifest(artifact_store, version)
    entries = [entry for entry in manifest.entries if entry.source_id == source_id]
    if entity_id is not None and any(entry.entity_id for entry in entries):
        entries = [entry for entry in entries if entry.entity_id == entity_id]
    if not entries:
        raise SourceInspectionError(
            OUTCOME_ABSENT_BINDING,
            f"published version {version!r} does not bind this source id",
        )
    if len({entry.content_hash for entry in entries}) != 1:
        raise SourceInspectionError(
            OUTCOME_AMBIGUOUS_BINDING,
            "this Published Version binds the source id to multiple exact Source Versions; "
            "resolve it from a specific Entity",
        )
    identities = {(entry.filename, entry.content_type, entry.size) for entry in entries}
    if len(identities) != 1:
        raise SourceInspectionError(
            OUTCOME_CORRUPTION,
            "the stored Source Binding Manifest disagrees on exact source metadata",
        )
    entry = entries[0]
    return ResolvedSourceBinding(
        source_id=source_id,
        content_hash=entry.content_hash,
        filename=entry.filename,
        content_type=entry.content_type,
        size=entry.size,
        published_version=version,
    )


def read_local_published_bindings(destination: str | Path, version: str):
    """Read one fully verified local Git admission's private source bindings."""
    from lumio_wiki.git_authoring import GitAuthoringError, _verify_version_complete

    version = validate_published_version(version)
    try:
        _manifest, receipt, sealed = _verify_version_complete(Path(destination), version)
    except GitAuthoringError as exc:
        outcome = (
            OUTCOME_HISTORICAL_VERSION_MISMATCH
            if not (Path(destination) / "versions" / version).exists()
            else OUTCOME_CORRUPTION
        )
        raise SourceInspectionError(outcome, str(exc)) from exc
    return receipt, sealed


def resolve_local_published_binding(
    destination: str | Path,
    version: str,
    source_id: str,
    *,
    entity_id: str | None = None,
) -> ResolvedSourceBinding:
    """Resolve local historical metadata from its verified sealed record."""
    from lumio_wiki.source_registry import _validate_source_id

    try:
        _validate_source_id(source_id)
    except SourceRegistryError as exc:
        raise SourceInspectionError(OUTCOME_ABSENT_BINDING, str(exc)) from exc
    receipt, sealed = read_local_published_bindings(destination, version)
    matches = [
        digest
        for page_id, bindings in sealed.bindings.items()
        for bound_id, digest in bindings.items()
        if bound_id == source_id and (entity_id is None or page_id == entity_id)
    ]
    if not matches:
        raise SourceInspectionError(
            OUTCOME_ABSENT_BINDING,
            f"published version {version!r} does not bind this source id",
        )
    if len(set(matches)) != 1:
        raise SourceInspectionError(
            OUTCOME_AMBIGUOUS_BINDING,
            "this Published Version binds the source id to multiple exact Source Versions; "
            "resolve it from a specific Entity",
        )
    content_hash = matches[0]
    metadata = [
        item
        for item in sealed.source_versions
        if item.source_id == source_id and item.content_hash == content_hash
    ]
    if len(metadata) != 1:
        raise SourceInspectionError(
            OUTCOME_CORRUPTION,
            "the sealed historical record lacks unique exact inspection metadata",
        )
    item = metadata[0]
    if receipt.version != version:
        raise SourceInspectionError(
            OUTCOME_CORRUPTION,
            "the local admission receipt does not match the requested version",
        )
    return ResolvedSourceBinding(
        source_id=source_id,
        content_hash=content_hash,
        filename=item.filename,
        content_type=item.content_type,
        size=item.size,
        published_version=version,
    )


#: Signed-link expiry floor/ceiling (ADR-0020): default five minutes,
#: maximum one hour. A signed URL is a temporary bearer credential.
DEFAULT_LINK_EXPIRES = "5m"
MAX_LINK_EXPIRES = timedelta(hours=1)

_EXPIRES_PATTERN = re.compile(r"^(\d+)([smh]?)$")

#: A Published Version label: ASCII slug shapes only (the publisher's own
#: version strings), never a path, traversal, or secret-bearing free text.
_PUBLISHED_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_published_version(version: str) -> str:
    """Return ``version`` if it is a safe Published Version label.

    Raises a generic :class:`ValueError` (never echoing the value) for a
    label that could traverse a filesystem key, carry a secret, or smuggle
    a control character — the same boundary convention as source ids.
    """
    if not isinstance(version, str) or not _PUBLISHED_VERSION_PATTERN.match(version):
        raise ValueError("published version must be a simple label like 2026-08-21 or a uuid")
    return version


def parse_expires(value: str | None) -> timedelta:
    """Parse a ``--expires`` duration (``30s``/``5m``/``1h``; bare = minutes).

    Returns the :data:`DEFAULT_LINK_EXPIRES` duration for ``None``/empty and
    raises :class:`ValueError` for anything non-positive or above the
    one-hour ceiling.
    """
    text = (value or DEFAULT_LINK_EXPIRES).strip().lower()
    match = _EXPIRES_PATTERN.match(text)
    if match is None:
        raise ValueError(
            "invalid --expires value: use a duration like 30s, 5m, or 1h (bare numbers are minutes)"
        )
    unit = match.group(2) or "m"
    try:
        duration = timedelta(seconds=int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[unit])
    except OverflowError:
        # Arbitrarily long digit strings parse as huge ints; timedelta itself
        # overflows above ~8.64e13 seconds, so route that to the ceiling error.
        raise ValueError("--expires must not exceed one hour") from None
    if duration <= timedelta(0):
        raise ValueError("--expires must be greater than zero")
    if duration > MAX_LINK_EXPIRES:
        raise ValueError("--expires must not exceed one hour")
    return duration


def safe_fetch_destination(output: Path, binding: ResolvedSourceBinding) -> Path:
    """Return the exact fetch destination for ``--output``.

    An explicit file path is used verbatim. An existing directory receives the
    binding's safe filename (re-sanitized to a basename; never a local source
    path or traversal) with a conservative ``<source_id>.bin`` fallback.
    """
    from lumio_wiki.source_registry import safe_artifact_filename

    if output.is_dir():
        name = safe_artifact_filename(binding.filename) or f"{binding.source_id}.bin"
        return output / name
    return output


def fetch_verified_artifact(
    artifact_store: SourceArtifactStore, binding: ResolvedSourceBinding
) -> bytes:
    """Fetch the binding's exact bytes, re-verifying digest AND size.

    The store verifies the digest on read; the recorded size is checked here
    against what was actually returned so a truncated or padded object is
    rejected as corruption before anything is written to disk.
    """
    try:
        raw = artifact_store.get_artifact(
            source_id=binding.source_id, content_hash=binding.content_hash
        )
    except ArtifactAccessDenied as exc:
        raise SourceInspectionError(OUTCOME_ACCESS_DENIED, str(exc)) from exc
    except ArtifactUnavailable as exc:
        raise SourceInspectionError(OUTCOME_UNAVAILABLE, str(exc)) from exc
    except ArtifactCorruption as exc:
        raise SourceInspectionError(OUTCOME_CORRUPTION, str(exc)) from exc
    if binding.size is not None and len(raw) != binding.size:
        raise SourceInspectionError(
            OUTCOME_CORRUPTION,
            "stored artifact size does not match the recorded binding size",
        )
    return raw
