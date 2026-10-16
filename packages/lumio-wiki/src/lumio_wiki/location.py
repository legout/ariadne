"""Public Knowledge Base Location + immutable Snapshot seam (issue #119, ADR-0013).

A **Knowledge Base Location** resolves an immutable **Published Version** (a
**Snapshot**) from a local filesystem or — in a future capability — object
storage. The filesystem implementation here is the verified reference: it wraps
the *existing* filesystem loading, validation, fingerprinting, zero-index
retrieval, and Discovery Graph traversal, so every observable result matches the
path-based Core SDK behavior exactly. Native S3 Locations are the parent epic
(#118) and are intentionally out of scope for this module.

This seam preserves every existing filesystem workflow:

* The path-based entrypoint :func:`lumio_wiki.knowledge_base.load_knowledge_base`
  is retained unchanged and remains the shared loading core.
* New clients open, validate, search, retrieve, traverse the Discovery Graph,
  and cite a local Published Version through the Location/Snapshot seam without
  changing observable results.

See ADR-0013 (S3-native Knowledge Base Locations), ADR-0011 (Discovery Graph),
ADR-0010 (Core SDK / zero-index), and the ubiquitous language in CONTEXT.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import msgspec

from lumio_wiki.embeddings import DEFAULT_SEMANTIC_THRESHOLD, Embedder, RetrievalMode
from lumio_wiki.knowledge_base import (
    DEFAULT_GRAPH_MAX_DEPTH,
    DEFAULT_GRAPH_MAX_EDGES,
    DEFAULT_GRAPH_MAX_RESULTS,
    GRAPH_DIRECTION_OUTGOING,
    GRAPH_SCOPE_CANONICAL,
    GRAPH_SCOPE_DISCOVERY,
    ExtractionDiagnostic,
    KnowledgeBase,
    KnowledgeBaseError,
    _fingerprint_sources,
    _InMemoryKbSource,
    _load_and_validate,
    load_knowledge_base,
)
from lumio_wiki.records import (
    CompiledPage,
    ExtractedReference,
    KnowledgeBaseControlFile,
    PageSearchResult,
    RegistryEntry,
    Relationship,
    RetrievalResult,
    SourceFingerprint,
    ValidationReport,
)
from lumio_wiki.source_inspection import validate_published_version

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from lumio_wiki.s3_location import S3Manifest

# Stable identifier for the filesystem Location implementation. Future
# implementations (S3, etc.) declare their own ``kind`` so traces and
# diagnostics can name the resolved source without coupling to a class name.
FILESYSTEM_LOCATION_KIND = "filesystem"

#: The activation pointer basename at a publication root (shared layout with
#: the S3 capability, which re-exports these from here).
CURRENT_POINTER_OBJECT = "current.json"

#: The per-version manifest basename whose presence marks a complete version.
MANIFEST_OBJECT = "manifest.json"

#: Stable identifier for the local immutable Published Version Location.
LOCAL_PUBLISHED_LOCATION_KIND = "local-published"

#: Directory of immutable version directories under a local publication root.
VERSIONS_DIR_NAME = "versions"


def published_version_path(destination: str | Path, version: str) -> Path:
    """Return the immutable version directory for ``version`` at ``destination``."""
    return Path(destination) / VERSIONS_DIR_NAME / version


def published_pointer_path(destination: str | Path) -> Path:
    """Return the expected-current pointer file at a local publication root."""
    return Path(destination) / CURRENT_POINTER_OBJECT


__all__ = [
    "FILESYSTEM_LOCATION_KIND",
    "FilesystemLocation",
    "KnowledgeBaseLocation",
    "KnowledgeBaseSnapshot",
    "LOCAL_PUBLISHED_LOCATION_KIND",
    "PublishedFilesystemLocation",
    "RemoteDerivedIndex",
    "VERSIONS_DIR_NAME",
    "open_filesystem_knowledge_base",
    "open_knowledge_base",
    "published_pointer_path",
    "published_version_path",
]


class RemoteDerivedIndex(msgspec.Struct, frozen=True):
    """A dependency-neutral descriptor of a Snapshot's remote derived index.

    The record is in-memory binding data, never portable Knowledge Base
    content: ``store`` is the already-authenticated object store the Location
    reads through (opaque here), and no field ever carries a credential.
    """

    uri: str
    """The object-store URI a retrieval backend connects to (e.g. ``s3://bucket/kb/v1/derived/lance``)."""

    sidecar_prefix: str
    """Object-store key prefix of the index's freshness/model sidecars."""

    version: str
    """The immutable Published Version label the index belongs to."""

    fingerprint: SourceFingerprint
    """The Published Version fingerprint the index must match, else it is stale."""

    store: Any = None
    """The Location's object store for sidecar reads (an obstore ObjectStore)."""


@runtime_checkable
class KnowledgeBaseLocation(Protocol):
    """Resolve a Knowledge Base's Published Versions into immutable Snapshots.

    A Location is deployment or CLI configuration: it knows how to reach a
    Knowledge Base (a local directory today; an object-storage prefix in the S3
    capability) and how to resolve the current immutable Published Version into
    a :class:`KnowledgeBaseSnapshot`. Per ADR-0013 and the ubiquitous language,
    a Location's credentials are deployment configuration — they are never
    portable Knowledge Base content and never travel with the Published Version.

    The contract is verified through public behavior only: a Location has a
    stable :attr:`kind`, a secret-free :meth:`describe`, and a :meth:`resolve`
    that returns an immutable Snapshot. ``runtime_checkable`` lets clients
    assert conformance structurally without inheriting a base class.
    """

    @property
    def kind(self) -> str:
        """A short, stable identifier for the location implementation."""
        ...

    def describe(self) -> str:
        """Return a human-readable, secret-free description for diagnostics/traces.

        Implementations MUST NOT include credentials, tokens, or secrets.
        """
        ...

    def resolve(self) -> KnowledgeBaseSnapshot:
        """Resolve the current Published Version into an immutable Snapshot.

        Raises :class:`lumio_wiki.knowledge_base.KnowledgeBaseError` when the
        location cannot be resolved (e.g. a missing or non-directory path).
        """
        ...


class KnowledgeBaseSnapshot(msgspec.Struct, frozen=True):
    """An immutable Published Version view of a resolved Knowledge Base.

    A Snapshot is what a reader, the CLI, or a local agent holds after a
    Location resolves a Published Version. It is the read-only surface over the
    loaded Compiled Pages: validation, fingerprinting, search, zero-index
    retrieval, Discovery Graph traversal, Citations, and Retrieval Traces all
    delegate to the underlying :class:`KnowledgeBase` and match the filesystem
    behavior byte-for-byte.

    The Published Version fingerprint (:attr:`fingerprint`) is captured at
    resolve time and is part of the immutable contract — it identifies the exact
    version a reader synced to. A Snapshot never exposes write, build, or
    publish operations: those remain on :class:`KnowledgeBase` and the
    path-based publishing entrypoints.
    """

    knowledge_base: KnowledgeBase
    validation_report: ValidationReport
    fingerprint: SourceFingerprint
    location: KnowledgeBaseLocation
    remote_derived_index: RemoteDerivedIndex | None = None
    """This Published Version's remote derived index, when the Location knows one.

    A resolved S3 Snapshot exposes a dependency-neutral descriptor for its
    exact version's ``derived/lance/`` index (issue #162, ADR-0019) so a
    consumer binds the remote index without reconstructing object keys.
    ``None`` for filesystem Snapshots (and S3 Locations constructed without a
    container URI); retrieval then stays on the always-available zero-index
    path.
    """
    published_version: str | None = None
    """The exact immutable S3 Published Version resolved for this Snapshot.

    Filesystem Snapshots intentionally leave this unset: local content has no
    pointer/version indirection and copyable local actions remain version-free.
    """

    # ------------------------------------------------------------------
    # Immutable Published Version identity and provenance.
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        """The resolved Knowledge Base root for this Published Version."""
        return self.knowledge_base.root

    @property
    def pages(self) -> tuple[CompiledPage, ...]:
        """The Compiled Pages of this Published Version (immutable view).

        Returns a fresh immutable tuple so a caller cannot mutate the Snapshot's
        page collection (append/clear/sort). The CompiledPage records themselves
        are frozen, so the returned view is fully immutable.
        """
        return tuple(self.knowledge_base.pages)

    @property
    def control(self) -> KnowledgeBaseControlFile | None:
        """The Knowledge Base Control File, if this is a categorized Knowledge Base."""
        return self.knowledge_base.control

    @property
    def index_dir(self) -> Path | None:
        """The derived index directory bound to the underlying Knowledge Base, if any.

        A freshly resolved filesystem Snapshot has no bound index directory, so
        retrieval defaults to the always-available zero-index path.
        """
        return self.knowledge_base.index_dir

    # ------------------------------------------------------------------
    # Lookups and authorization selection.
    # ------------------------------------------------------------------

    def lookup_by_title(self, title: str) -> list[CompiledPage]:
        return self.knowledge_base.lookup_by_title(title)

    def lookup_by_alias(self, alias: str) -> list[CompiledPage]:
        return self.knowledge_base.lookup_by_alias(alias)

    def lookup_by_tag(self, tag: str) -> list[CompiledPage]:
        return self.knowledge_base.lookup_by_tag(tag)

    def lookup_by_source(self, source_id: str) -> list[CompiledPage]:
        return self.knowledge_base.lookup_by_source(source_id)

    def lookup_by_lifecycle(self, lifecycle: str) -> list[CompiledPage]:
        return self.knowledge_base.lookup_by_lifecycle(lifecycle)

    def public_pages(self) -> list[CompiledPage]:
        """Return the public Compiled Pages (the public export authorization scope)."""
        return self.knowledge_base.public_pages()

    def registry(self) -> list[RegistryEntry]:
        """Return a compact registry entry for every Compiled Page."""
        return self.knowledge_base.registry()

    # ------------------------------------------------------------------
    # Search, retrieval, Citations, and Retrieval Traces.
    # ------------------------------------------------------------------

    def search_pages(
        self,
        query: str,
        limit: int = 20,
        pages: Sequence[CompiledPage] | None = None,
    ) -> list[PageSearchResult]:
        """Search page metadata and body text with deterministic lexical ranking."""
        return self.knowledge_base.search_pages(query, limit=limit, pages=pages)

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        index_dir: str | Path | None = None,
        hints: Sequence[str] | None = None,
        *,
        mode: RetrievalMode = "lexical",
        embedder: Embedder | None = None,
        score_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
        graph_seed_titles: Sequence[str] | None = None,
        graph_scope: str = GRAPH_SCOPE_DISCOVERY,
        graph_direction: str = GRAPH_DIRECTION_OUTGOING,
        graph_max_depth: int = 2,
    ) -> list[RetrievalResult]:
        """Retrieve citation-ready Evidence for ``query`` over this Published Version.

        Defaults to the always-available zero-index lexical adapter; observable
        results, Citations, and Retrieval Traces match the path-based loader.
        """
        return self.knowledge_base.retrieve(
            query,
            limit=limit,
            index_dir=index_dir,
            hints=hints,
            mode=mode,
            embedder=embedder,
            score_threshold=score_threshold,
            graph_seed_titles=graph_seed_titles,
            graph_scope=graph_scope,
            graph_direction=graph_direction,
            graph_max_depth=graph_max_depth,
        )

    # ------------------------------------------------------------------
    # Discovery Graph traversal (ADR-0011).
    # ------------------------------------------------------------------

    def related_from(self, title: str, relationship_type: str | None = None) -> list[Relationship]:
        return self.knowledge_base.related_from(title, relationship_type)

    def graph_path(self, source_title: str, target_title: str) -> list[str] | None:
        return self.knowledge_base.graph_path(source_title, target_title)

    def related_pages(
        self,
        title: str,
        *,
        direction: str = GRAPH_DIRECTION_OUTGOING,
        scope: str = GRAPH_SCOPE_CANONICAL,
        candidate_titles: Iterable[str] | None = None,
        relationship_type: str | None = None,
        max_depth: int = 1,
        max_edges: int = DEFAULT_GRAPH_MAX_EDGES,
        max_results: int = DEFAULT_GRAPH_MAX_RESULTS,
    ) -> list[str]:
        return self.knowledge_base.related_pages(
            title,
            direction=direction,
            scope=scope,
            candidate_titles=candidate_titles,
            relationship_type=relationship_type,
            max_depth=max_depth,
            max_edges=max_edges,
            max_results=max_results,
        )

    def shortest_path(
        self,
        source_title: str,
        target_title: str,
        *,
        direction: str = GRAPH_DIRECTION_OUTGOING,
        scope: str = GRAPH_SCOPE_CANONICAL,
        candidate_titles: Iterable[str] | None = None,
        max_depth: int = DEFAULT_GRAPH_MAX_DEPTH,
        max_edges: int = DEFAULT_GRAPH_MAX_EDGES,
    ) -> list[str] | None:
        return self.knowledge_base.shortest_path(
            source_title,
            target_title,
            direction=direction,
            scope=scope,
            candidate_titles=candidate_titles,
            max_depth=max_depth,
            max_edges=max_edges,
        )

    def extracted_references(self, title: str) -> list[ExtractedReference]:
        return self.knowledge_base.extracted_references(title)

    def extraction_diagnostics(self) -> list[ExtractionDiagnostic]:
        return self.knowledge_base.extraction_diagnostics()


class FilesystemLocation:
    """The verified reference Location: a local filesystem Knowledge Base.

    Resolves the current content of a local directory into an immutable
    Snapshot by loading, validating, and fingerprinting it through the existing
    path-based Core SDK loader. This is the reference implementation every
    future Location (S3, etc.) must match in observable behavior.

    The path is not validated until :meth:`resolve` is called, so a
    ``FilesystemLocation`` can be constructed ahead of time as deployment
    configuration and resolved lazily.
    """

    kind = FILESYSTEM_LOCATION_KIND

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """The local filesystem path this Location resolves."""
        return self._path

    def describe(self) -> str:
        return f"filesystem:{self._path}"

    def resolve(self) -> KnowledgeBaseSnapshot:
        root = self._path.resolve()
        if not root.exists():
            raise KnowledgeBaseError(f"path does not exist: {root}")
        if not root.is_dir():
            raise KnowledgeBaseError(f"path is not a directory: {root}")
        kb, report = load_knowledge_base(root)
        if kb.source_fingerprint is None:  # pragma: no cover - loaded KBs capture identity
            raise KnowledgeBaseError("loaded Knowledge Base has no captured source identity")
        return KnowledgeBaseSnapshot(
            knowledge_base=kb,
            validation_report=report,
            fingerprint=kb.source_fingerprint,
            location=self,
        )


class PublishedFilesystemLocation:
    """A local immutable Published Version Location with a pointer layout.

    Resolves a local publication destination (written by Git-native
    publication, specification 0008) into an immutable Snapshot: the root's
    ``current.json`` pointer is read ONCE, the named immutable version's
    manifest is validated, every canonical file is materialized with its size
    and SHA-256 verified, and only that version is loaded — a missing or
    corrupt referenced version fails closed with a diagnostic instead of
    falling back to any working tree. Passing ``version`` pins the Location
    to one immutable version (rollback verification, historical reads); the
    pointer is then never consulted.

    Distinct from :class:`FilesystemLocation`: a plain directory load stays
    version-free and is never silently labelled admitted, while this Location
    always resolves exactly one admitted Published Version.
    """

    kind = LOCAL_PUBLISHED_LOCATION_KIND

    def __init__(self, path: str | Path, *, version: str | None = None) -> None:
        self._path = Path(path)
        self._pinned_version = validate_published_version(version) if version else None

    @property
    def path(self) -> Path:
        """The local publication destination this Location resolves."""
        return self._path

    @property
    def version(self) -> str | None:
        """The pinned immutable version, when this Location is pinned."""
        return self._pinned_version

    def describe(self) -> str:
        where = f"local-published:{self._path}"
        return f"{where}@{self._pinned_version}" if self._pinned_version else where

    def read_pointer(self) -> str | None:
        """Return the active version label, or ``None`` when no pointer exists."""
        from lumio_wiki.s3_location import S3Pointer

        pointer_file = published_pointer_path(self._path)
        try:
            raw = pointer_file.read_bytes()
        except FileNotFoundError:
            return None
        try:
            pointer = msgspec.json.decode(raw, type=S3Pointer)
        except msgspec.DecodeError as exc:
            raise KnowledgeBaseError(
                f"publication pointer {pointer_file} is malformed: {exc}"
            ) from exc
        return validate_published_version(pointer.version)

    def read_manifest(self, version: str) -> S3Manifest:
        """Load and validate one immutable version's manifest."""
        from lumio_wiki.s3_location import S3Manifest

        version = validate_published_version(version)
        manifest_file = published_version_path(self._path, version) / MANIFEST_OBJECT
        try:
            raw = manifest_file.read_bytes()
        except FileNotFoundError as exc:
            raise KnowledgeBaseError(
                f"Published Version {version!r} at {self._path} has no manifest — "
                "the version is absent or incomplete"
            ) from exc
        try:
            manifest = msgspec.json.decode(raw, type=S3Manifest)
        except msgspec.DecodeError as exc:
            raise KnowledgeBaseError(
                f"Published Version {version!r} manifest is malformed: {exc}"
            ) from exc
        if manifest.version != version:
            raise KnowledgeBaseError(
                f"Published Version {version!r} manifest names version {manifest.version!r}"
            )
        return manifest

    def materialize(self, version: str, manifest: S3Manifest) -> dict[str, bytes]:
        """Read every canonical file with size and digest verified."""
        import hashlib

        version_dir = published_version_path(self._path, version)
        content: dict[str, bytes] = {}
        for entry in manifest.files:
            path = version_dir / entry.path
            try:
                raw = path.read_bytes()
            except FileNotFoundError as exc:
                raise KnowledgeBaseError(
                    f"Published Version {version!r} is missing {entry.path!r}"
                ) from exc
            if len(raw) != entry.size:
                raise KnowledgeBaseError(
                    f"Published Version {version!r} file {entry.path!r} size "
                    f"{len(raw)} != manifest size {entry.size}"
                )
            actual = hashlib.sha256(raw).hexdigest()
            if actual != entry.digest:
                raise KnowledgeBaseError(
                    f"Published Version {version!r} file {entry.path!r} digest "
                    f"{actual} != manifest digest {entry.digest}"
                )
            content[entry.path] = raw
        return content

    def resolve(self) -> KnowledgeBaseSnapshot:
        """Resolve the pointer's (or pinned) immutable version into a Snapshot."""
        version = self._pinned_version or self.read_pointer()
        if version is None:
            raise KnowledgeBaseError(
                f"no published version pointer at {self._path}: nothing has been "
                "admitted at this destination yet"
            )
        manifest = self.read_manifest(version)
        content = self.materialize(version, manifest)
        root = published_version_path(self._path, version)
        source = _InMemoryKbSource(content, root=root)
        fingerprint = _fingerprint_sources(source)
        if fingerprint.digest != manifest.fingerprint:
            raise KnowledgeBaseError(
                f"Published Version {version!r} content fingerprint "
                f"{fingerprint.digest} != manifest fingerprint {manifest.fingerprint}"
            )
        kb, report = _load_and_validate(source, fingerprint=fingerprint)
        return KnowledgeBaseSnapshot(
            knowledge_base=kb,
            validation_report=report,
            fingerprint=fingerprint,
            location=self,
            published_version=version,
        )


def open_knowledge_base(location: KnowledgeBaseLocation) -> KnowledgeBaseSnapshot:
    """Open a Knowledge Base through the Location seam.

    The canonical Location-based entrypoint: resolves ``location``'s current
    Published Version into an immutable Snapshot. Equivalent to
    ``location.resolve()``; provided as a discoverable public function.
    """
    return location.resolve()


def open_filesystem_knowledge_base(path: str | Path) -> KnowledgeBaseSnapshot:
    """Open a local filesystem Knowledge Base as an immutable Snapshot.

    Convenience shorthand for ``FilesystemLocation(path).resolve()``. Clients
    migrating from the path-based :func:`load_knowledge_base` entrypoint can
    adopt this to receive the richer Snapshot (validation report, Published
    Version fingerprint, and provenance) while keeping identical observable
    results.
    """
    return FilesystemLocation(path).resolve()
