"""Git-native Knowledge Base authoring and local publication (spec 0008 §2–5).

An **Authoring Revision** is an exact Git commit plus its selected Knowledge
Base subtree. Preview, validation, admission, and publication all consume the
same captured Git object bytes — never a moving branch name and never a
subsequent filesystem read of the authoring worktree. Publication Review is
stateless; Publication Admission is the explicit confirmation of one exact
review digest; activation is one expected-current pointer advance over
immutable local version directories. Helpers edit an explicitly selected
authoring worktree but never commit implicitly: authors invoke Git themselves.

The private Source Reference Manifest digest stays distinct from the canonical
Compiled Page fingerprint: a source-only binding change can preserve the
fingerprint while producing a distinct Authoring Revision and Published
Version. Git owns diff, history, review, and reconciliation; nothing here
stashes, resets, checks out, rebases, merges, pushes, or deletes branches.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import msgspec

from lumio_wiki.artifact_store import (
    ArtifactStoreError,
    ArtifactUnavailable,
    SourceArtifactStore,
    SourceBindingEntry,
    SourceBindingManifest,
    build_binding_manifest,
    local_publication_metadata_store,
    required_coverage_missing,
    required_source_pairs,
    retain_artifact,
    verify_rollback_coverage,
)
from lumio_wiki.graph_state import GRAPH_ARTIFACT_FILENAME
from lumio_wiki.knowledge_base import (
    generate_hot_index,
    generate_navigation_indexes,
)
from lumio_wiki.location import (
    PublishedFilesystemLocation,
    published_pointer_path,
    published_version_path,
)
from lumio_wiki.mutation import (
    MutationBackup,
    MutationRollbackError,
    atomic_write_bytes,
    mutation_lock,
)
from lumio_wiki.publish import affected_mutation_paths, apply_proposed_pages
from lumio_wiki.s3_location import S3Location, S3ManifestFile, build_published_manifest
from lumio_wiki.s3_publish import (
    LANCE_COMPLETION_OBJECT,
    LANCE_DERIVED_DIR,
    IndexBuilder,
    RemoteIndexCompletion,
    S3PublicationConflict,
    _activate_existing_s3_version,
    _load_complete_version,
    _publish_s3_captured_revision,
    _rollback_s3_version,
    _serialize_graph_bytes,
    _validate_graph_state,
    _verify_and_encode_completion,
    _verify_lance_index_manifest,
    observe_current_pointer,
)
from lumio_wiki.source_inspection import validate_published_version
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceError,
    SourceReferenceManifest,
    load_source_reference_manifest,
    manifest_digest,
    parse_source_reference_manifest,
    serialize_source_reference_manifest,
    upsert_binding,
    validate_source_references,
)
from lumio_wiki.source_registry import SourceRegistry

__all__ = [
    "ConfirmationRefused",
    "DERIVED_GRAPH_ARTIFACT",
    "GitAuthoringError",
    "PublicationConflict",
    "PublicationReceipt",
    "PublicationRetentionError",
    "PublicationReview",
    "PublicationSourceImpact",
    "RollbackReview",
    "WorktreeIngestResult",
    "WorktreeMutationResult",
    "capture_revision",
    "import_graph_into_worktree",
    "ingest_into_worktree",
    "merge_entities_in_worktree",
    "preview_publication",
    "preview_rollback",
    "publish_revision",
    "remove_page_in_worktree",
    "rename_page_in_worktree",
    "resolve_full_commit",
    "resolve_repository",
    "retire_source_in_worktree",
    "revise_pages_in_worktree",
    "reactivate_source_in_worktree",
    "rollback_publication",
    "write_pages_into_worktree",
]

#: Identifies the validator/format contract bound into every review digest.
VALIDATOR_CONTRACT_ID = "lumio-wiki/git-authoring/1"

#: Private operational metadata under a local publication destination
#: (admission receipts and sealed source references; never Reader content).
PRIVATE_OPERATIONS_DIR = ".lumio-publication"

#: Derived artifacts generated for every local Published Version from the same
#: captured facts (spec 0008 §5). The Discovery Graph artifact mirrors the S3
#: layout; the Navigation/Hot Indexes are the generated derived surfaces.
DERIVED_DIR = "derived"
DERIVED_GRAPH_ARTIFACT = f"{DERIVED_DIR}/{GRAPH_ARTIFACT_FILENAME}"
DERIVED_NAVIGATION_INDEX = f"{DERIVED_DIR}/index.md"
DERIVED_HOT_INDEX = f"{DERIVED_DIR}/hot.md"

#: The default private ingest-store subtree that must never be Git-tracked
#: inside an authoring Knowledge Base (spec 0008 §3.2).
_TRACKED_PRIVATE_PREFIX = ".lumio/ingest/"

#: Canonical basenames the capture admits as regular blobs.
_CONTROL_BASENAME = "lumio.yaml"

_FULL_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

_EXPECTED_NONE = "none"


class GitAuthoringError(Exception):
    """A Git-native authoring or publication operation failed."""


class PublicationConflict(GitAuthoringError):
    """The expected-current baseline does not match the observed pointer.

    The previously active Published Version stays intact; the caller
    re-reviews against the now-active version instead of retrying blindly.
    """


class ConfirmationRefused(GitAuthoringError):
    """The confirmation no longer matches the recomputed review-bound facts."""


class PublicationRetentionError(GitAuthoringError):
    """Activation blocked: a bound exact Source Version lacks a verified artifact."""


# ---------------------------------------------------------------------------
# Read-only Git access.
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> bytes:
    """Run one read-only Git plumbing command and return its stdout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise GitAuthoringError(
            "the Git executable is required for Git-native authoring but was not found"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise GitAuthoringError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _git_exit(repo_root: Path, *args: str) -> int:
    """Run one read-only Git plumbing command and return only its exit code."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise GitAuthoringError(
            "the Git executable is required for Git-native authoring but was not found"
        ) from exc
    return result.returncode


def resolve_repository(kb_root: str | Path) -> tuple[Path, str]:
    """Return ``(repository_root, kb_subtree)`` for an authoring worktree.

    Refuses a bare repository and a path outside any repository — Git-native
    operations never guess a mutation target (spec 0008 §2).
    """
    root = Path(kb_root).resolve()
    if not root.is_dir():
        raise GitAuthoringError(f"Knowledge Base root is not a directory: {root}")
    bare = _git(root, "rev-parse", "--is-bare-repository").decode().strip()
    if bare == "true":
        raise GitAuthoringError(
            "a bare repository cannot be an authoring worktree; select a registered branch worktree"
        )
    toplevel = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip())
    if toplevel.resolve() != root and not root.is_relative_to(toplevel.resolve()):
        raise GitAuthoringError(
            f"Knowledge Base root {root} is outside its Git repository {toplevel}"
        )
    subtree = root.relative_to(toplevel.resolve()).as_posix()
    if subtree == ".":
        # A Knowledge Base selected at the repository root has an empty
        # subtree: Git tree paths are already root-relative (finding 12).
        subtree = ""
    return toplevel.resolve(), subtree


def resolve_full_commit(repo_root: str | Path, revision: str) -> str:
    """Return ``revision`` when it names an exact existing full commit id.

    Only a 40-character lowercase hexadecimal object id is accepted: branch
    names and abbreviations cannot float through review and confirmation
    (spec 0008 §4.1).
    """
    if not isinstance(revision, str) or not _FULL_COMMIT_PATTERN.match(revision):
        raise GitAuthoringError(
            "publication requires the FULL commit id (40 lowercase hex characters); "
            "resolve Git references before review — a branch name or abbreviation "
            "cannot be confirmed"
        )
    resolved = _git(Path(repo_root), "rev-parse", "--verify", f"{revision}^{{commit}}")
    resolved_text = resolved.decode().strip()
    if resolved_text != revision:
        raise GitAuthoringError(f"revision {revision!r} does not name that exact commit")
    return resolved_text


def _tree_entries(repo_root: Path, revision: str, subtree: str) -> list[tuple[str, str, str]]:
    """Return ``(mode, type, kb_relative_path)`` for every tree entry, sorted."""
    pathspec = f"{subtree}/" if subtree else "."
    raw = _git(repo_root, "ls-tree", "-r", "-z", revision, "--", pathspec)
    entries: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, path_bytes = record.split(b"\t", 1)
            mode, object_type, _oid = meta.decode().split(" ")
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitAuthoringError(f"could not parse Git tree entry: {exc}") from exc
        if subtree:
            prefix = f"{subtree}/"
            if not path.startswith(prefix):
                continue
            path = path[len(prefix) :]
        entries.append((mode, object_type, path))
    return sorted(entries, key=lambda entry: entry[2])


def _read_blob(repo_root: Path, revision: str, subtree: str, rel: str) -> bytes:
    spec = f"{revision}:{subtree}/{rel}" if subtree else f"{revision}:{rel}"
    return _git(repo_root, "cat-file", "blob", spec)


class CapturedRevision:
    """One exact Git commit's captured Knowledge Base bytes (immutable view)."""

    def __init__(
        self,
        *,
        repo_root: Path,
        kb_root: Path,
        revision: str,
        subtree: str,
        files: dict[str, bytes],
        manifest_raw: bytes,
    ) -> None:
        from lumio_wiki.knowledge_base import (
            _fingerprint_sources,
            _InMemoryKbSource,
            _load_and_validate,
            canonical_content,
        )

        self.repo_root = repo_root
        self.kb_root = kb_root
        self.revision = revision
        self.subtree = subtree
        self.manifest_raw = manifest_raw
        self.manifest = _parse_manifest_or_raise(manifest_raw)
        self.manifest_digest = manifest_digest(manifest_raw)
        self.source = _InMemoryKbSource(files, root=kb_root)
        self.fingerprint = _fingerprint_sources(self.source)
        self.kb, self.report = _load_and_validate(self.source, fingerprint=self.fingerprint)
        self.content = canonical_content(self.source)


def _parse_manifest_or_raise(raw: bytes) -> SourceReferenceManifest:
    try:
        return parse_source_reference_manifest(raw)
    except SourceReferenceError as exc:
        raise GitAuthoringError(
            f"the selected revision's {SOURCE_REFERENCE_MANIFEST_BASENAME} is invalid: {exc}"
        ) from exc


def capture_revision(kb_root: str | Path, revision: str) -> CapturedRevision:
    """Capture the exact Git blob bytes of one revision's KB subtree once.

    Only regular in-scope canonical files are captured: a symlink or submodule
    at a canonical position (any ``.md`` file, ``lumio.yaml``, or the Source
    Reference Manifest) is refused, never materialized as Reader knowledge,
    and unrelated repository content is ignored (spec 0008 §5). Repository
    hooks never execute: capture reads Git objects through plumbing only. A
    Git-tracked private ingest store inside the Knowledge Base is refused —
    raw/registry paths never belong in Git (§3.2).
    """
    root = Path(kb_root).resolve()
    repo_root, subtree = resolve_repository(root)
    revision = resolve_full_commit(repo_root, revision)
    entries = _tree_entries(repo_root, revision, subtree)

    files: dict[str, bytes] = {}
    manifest_raw: bytes | None = None
    for mode, object_type, rel in entries:
        if rel.startswith(_TRACKED_PRIVATE_PREFIX):
            raise GitAuthoringError(
                f"the private ingest store '{_TRACKED_PRIVATE_PREFIX}' is Git-tracked "
                f"in the Knowledge Base subtree; raw/registry paths must stay out of "
                f"Git — untrack them before publishing this revision"
            )
        is_canonical = (
            rel.lower().endswith(".md") or rel == _CONTROL_BASENAME
        ) or rel == SOURCE_REFERENCE_MANIFEST_BASENAME
        if not is_canonical:
            continue
        if mode != "100644" or object_type != "blob":
            raise GitAuthoringError(
                f"'{rel}' in revision {revision} is not a regular file "
                f"(mode {mode}, {object_type}); symlinks and submodules are never "
                f"materialized as Knowledge Base content — publish a regular blob"
            )
        raw = _read_blob(repo_root, revision, subtree, rel)
        if rel == SOURCE_REFERENCE_MANIFEST_BASENAME:
            manifest_raw = raw
        else:
            files[rel] = raw
    if manifest_raw is None:
        raise GitAuthoringError(
            f"revision {revision} carries no {SOURCE_REFERENCE_MANIFEST_BASENAME}; "
            "adopt Git authoring (assign a namespace and declare the manifest) "
            "before publishing"
        )
    return CapturedRevision(
        repo_root=repo_root,
        kb_root=root,
        revision=revision,
        subtree=subtree,
        files=files,
        manifest_raw=manifest_raw,
    )


# ---------------------------------------------------------------------------
# Private operational metadata (receipts and sealed source references).
# ---------------------------------------------------------------------------


class SealedSourceVersion(msgspec.Struct, frozen=True):
    """Exact registered Source Version inspection metadata, sealed privately.

    Spec 0008 §3.3: historical binding metadata retains the exact version's
    inspection facts — captured from the registry at publication time, never
    resolved from later registry state (finding 16).
    """

    source_id: str
    content_hash: str
    filename: str | None = None
    content_type: str | None = None
    size: int | None = None
    registered_at: str | None = None


class SealedSourceReferences(msgspec.Struct, frozen=True):
    """Private provenance sealed per publication, outside public snapshots."""

    published_version: str
    revision: str
    namespace: str
    fingerprint: str
    manifest_digest: str
    sources: dict[str, str]
    bindings: dict[str, dict[str, str]]
    created_at: str
    source_versions: list[SealedSourceVersion] = msgspec.field(default_factory=list)


class PublicationReceipt(msgspec.Struct, frozen=True):
    """One immutable private admission record (publication evidence)."""

    revision: str
    version: str
    subtree: str
    destination: str
    fingerprint: str
    manifest_digest: str
    source_references_digest: str
    review_digest: str
    expected_current: str
    validator_contract: str
    retention: str
    created_at: str
    activated: bool = False
    destination_identity: str = ""
    requested_artifacts: list[str] = msgspec.field(default_factory=list)
    adoption: str = ""


class S3PublicationRecord(msgspec.Struct, frozen=True):
    """Private, immutable authorization and exact binding for one S3 version."""

    receipt: PublicationReceipt
    sealed: SealedSourceReferences
    binding_manifest_digest: str


class S3ActivationReceipt(msgspec.Struct, frozen=True):
    """Write-once evidence that the private S3 admission became active."""

    version: str
    review_digest: str
    expected_current: str
    activated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _receipts_dir(destination: Path) -> Path:
    return destination / PRIVATE_OPERATIONS_DIR / "receipts"


def _sealed_dir(destination: Path) -> Path:
    return destination / PRIVATE_OPERATIONS_DIR / "bindings"


def _receipt_path(destination: Path, version: str) -> Path:
    return _receipts_dir(destination) / f"{version}.json"


def _sealed_path(destination: Path, version: str) -> Path:
    return _sealed_dir(destination) / f"{version}.json"


def _load_receipt(destination: Path, version: str) -> PublicationReceipt:
    path = _receipt_path(destination, version)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise GitAuthoringError(
            f"no admission receipt for Published Version {version!r} at {destination}"
        ) from exc
    try:
        return msgspec.json.decode(raw, type=PublicationReceipt)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(f"admission receipt for {version!r} is malformed: {exc}") from exc


def _load_sealed(destination: Path, version: str) -> SealedSourceReferences:
    path = _sealed_path(destination, version)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise GitAuthoringError(
            f"no sealed source references for Published Version {version!r} at "
            f"{destination}: every publication seals its exact bindings before "
            f"activation, so this destination state needs explicit repair"
        ) from exc
    try:
        return msgspec.json.decode(raw, type=SealedSourceReferences)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"sealed source references for {version!r} are malformed: {exc}"
        ) from exc


def _verify_written(path: Path, expected: bytes) -> None:
    if path.read_bytes() != expected:
        raise GitAuthoringError(f"verification failed after writing {path}")


def _sealed_source_versions(
    captured: CapturedRevision, registry: SourceRegistry | None
) -> list[SealedSourceVersion]:
    """Capture each bound exact Source Version's inspection metadata (F16).

    Resolved through the registry's EXACT version lookup at publication time
    and sealed privately so historical inspection never consults later
    registry state. Fail closed when a bound version cannot be resolved —
    validation already refused that candidate, so this is unreachable for a
    well-formed admission.
    """
    sealed_versions: dict[tuple[str, str], SealedSourceVersion] = {}
    for entity_bindings in captured.manifest.bindings.values():
        for source_id, digest in entity_bindings.items():
            if (source_id, digest) in sealed_versions:
                continue
            version = registry.find_version(source_id, digest) if registry is not None else None
            if version is None:
                raise GitAuthoringError(
                    f"bound Source Version {source_id} cannot be resolved for "
                    f"sealing; select the shared registry explicitly"
                )
            sealed_versions[(source_id, digest)] = SealedSourceVersion(
                source_id=source_id,
                content_hash=version.content_hash,
                filename=version.filename,
                content_type=version.content_type,
                size=version.size,
                registered_at=version.created_at,
            )
    return [sealed_versions[key] for key in sorted(sealed_versions)]


def _captured_binding_entries(
    captured: CapturedRevision, registry: SourceRegistry | None
) -> list[SourceBindingEntry]:
    if captured.manifest.bindings and registry is None:
        raise GitAuthoringError(
            "exact Source Binding Manifest entries require the selected private registry"
        )
    pages = {page.id: page for page in captured.kb.pages if getattr(page, "id", None)}
    entries: list[SourceBindingEntry] = []
    for entity_id, bindings in sorted(captured.manifest.bindings.items()):
        page = pages.get(entity_id)
        if page is None:
            raise GitAuthoringError(
                f"source binding refers to missing candidate entity {entity_id!r}"
            )
        for source_id, digest in sorted(bindings.items()):
            version = registry.find_version(source_id, digest) if registry is not None else None
            if version is None:
                raise GitAuthoringError(
                    f"bound Source Version {source_id!r}@{digest} cannot be resolved "
                    "for the private binding record"
                )
            if not any(source.id == source_id for source in page.sources):
                raise GitAuthoringError(
                    f"source binding {source_id!r} is not cited by candidate entity {entity_id!r}"
                )
            entries.append(
                SourceBindingEntry(
                    entity_id=entity_id,
                    page_title=page.title,
                    source_id=source_id,
                    content_hash=digest,
                    content_type=version.content_type,
                    filename=version.filename,
                    size=version.size,
                    synthetic_page=bool(getattr(page, "synthetic", False)),
                )
            )
    return entries


def _coverage_entries(
    pages: Sequence[Any], bindings_by_entity: dict[str, dict[str, str]]
) -> list[SourceBindingEntry]:
    """Build exact page/source pairs without requiring the private registry."""
    pages_by_id = {page.id: page for page in pages if getattr(page, "id", None)}
    entries: list[SourceBindingEntry] = []
    for entity_id, bindings in sorted(bindings_by_entity.items()):
        page = pages_by_id.get(entity_id)
        if page is None:
            raise GitAuthoringError(
                f"source binding refers to missing candidate entity {entity_id!r}"
            )
        for source_id, digest in sorted(bindings.items()):
            if not any(source.id == source_id for source in page.sources):
                raise GitAuthoringError(
                    f"source binding {source_id!r} is not cited by candidate entity {entity_id!r}"
                )
            entries.append(
                SourceBindingEntry(
                    entity_id=entity_id,
                    page_title=page.title,
                    source_id=source_id,
                    content_hash=digest,
                    synthetic_page=bool(getattr(page, "synthetic", False)),
                )
            )
    return entries


def _captured_coverage_entries(captured: CapturedRevision) -> list[SourceBindingEntry]:
    return _coverage_entries(captured.kb.pages, captured.manifest.bindings)


def _require_retained_coverage(
    artifact_store: SourceArtifactStore | None,
    pages: Sequence[Any],
    entries: list[SourceBindingEntry],
) -> None:
    if artifact_store is None:
        raise PublicationRetentionError(
            "artifact retention is required but no Source Artifact Store is configured"
        )
    missing = required_coverage_missing(artifact_store, None, list(pages), captured_entries=entries)
    if missing:
        raise PublicationRetentionError(
            "artifact retention is required but captured page/source coverage or "
            "raw artifacts are unavailable: " + ", ".join(missing)
        )


def _verify_sealed_state(destination: Path, receipt: PublicationReceipt) -> bytes:
    """Load and verify the sealed private record against its receipt (F8/F10).

    The sealed bytes must exist, decode, digest-match the receipt's recorded
    ``source_references_digest``, and identify exactly the receipt's version,
    revision, fingerprint, and Source Reference Manifest digest. A validly
    encoded record for another version — or a tampered digest — fails closed.
    """
    path = _sealed_path(destination, receipt.version)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise GitAuthoringError(
            f"the sealed source references for Published Version "
            f"{receipt.version!r} are missing from {destination}: private "
            f"binding completeness is required before activation or rollback, "
            f"so this destination state needs explicit repair"
        ) from exc
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != receipt.source_references_digest:
        raise GitAuthoringError(
            f"the sealed source references for {receipt.version!r} do not match "
            f"the admission receipt's recorded digest; historical private "
            f"provenance cannot be reinterpreted"
        )
    try:
        sealed = msgspec.json.decode(raw, type=SealedSourceReferences)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"the sealed source references for {receipt.version!r} are malformed: {exc}"
        ) from exc
    mismatches = [
        detail
        for detail, actual, expected in (
            ("published version", sealed.published_version, receipt.version),
            ("revision", sealed.revision, receipt.revision),
            ("fingerprint", sealed.fingerprint, receipt.fingerprint),
            ("source reference manifest digest", sealed.manifest_digest, receipt.manifest_digest),
        )
        if actual != expected
    ]
    if mismatches:
        raise GitAuthoringError(
            f"the sealed source references for {receipt.version!r} identify "
            f"different {', '.join(mismatches)} than its admission receipt; "
            f"refusing to activate or roll back over mismatched historical "
            f"provenance"
        )
    return raw


# ---------------------------------------------------------------------------
# Publication Review (stateless) and its deterministic digest.
# ---------------------------------------------------------------------------


class PublicationSourceImpact(msgspec.Struct, frozen=True):
    """One disclosed source-reference change between admitted and candidate."""

    source_id: str
    change: str
    entity_id: str = ""
    page_title: str = ""
    support: str = ""


class PublicationReview(msgspec.Struct, frozen=True):
    """The stateless disclosure of one exact revision's publication facts."""

    validator_contract: str
    kb_path: str
    repository: str
    subtree: str
    revision: str
    version: str
    namespace: str
    fingerprint: str
    manifest_digest: str
    source_refs: list[str]
    bindings: list[str]
    source_impact: list[PublicationSourceImpact]
    page_mutations: list[str]
    blocking_diagnostics: list[str]
    public_only_sources: list[str]
    requested_artifacts: list[str]
    destination: str
    expected_current: str
    observed_current: str | None
    adoption: str
    retention: str
    registry_consulted: bool
    destination_identity: str
    review_digest: str


def _refuse_destination_inside_worktree(kb_root: Path, destination: Path) -> None:
    """Refuse a publication destination inside the authoring Git worktree.

    Spec 0008 §5: local activation happens outside the authoring worktree, and
    adopting a plain filesystem Knowledge Base uses a separate destination —
    never an in-place replacement or relabelling of its working tree. A
    destination inside the repository would also mix immutable version copies,
    pointers, receipts, and private bindings into the authored tree.
    """
    repo_root, _subtree = resolve_repository(kb_root)
    resolved = destination.resolve()
    if resolved == repo_root or resolved.is_relative_to(repo_root):
        raise GitAuthoringError(
            f"the publication destination must live OUTSIDE the authoring Git "
            f"worktree ({repo_root}); {resolved} is inside it — publishing over "
            f"the authoring Knowledge Base in place is not allowed, choose a "
            f"separate destination directory"
        )


def _refuse_tracked_private_paths(repo_root: Path, label: str, *paths: Path | None) -> None:
    """Refuse private selections that are Git-tracked in the authoring repository.

    Spec 0008 §3.2: Git-tracked raw/registry paths are refused by managed
    operations — a ``.gitignore`` alone is not the guarantee. Paths outside
    this repository are not tracked here and stay allowed (explicit selection
    outside the Knowledge Base subtree remains supported).
    """
    for path in paths:
        if path is None:
            continue
        resolved = Path(path).resolve()
        if resolved != repo_root and not resolved.is_relative_to(repo_root):
            continue
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--", str(resolved)],
            capture_output=True,
            check=False,
        )
        if result.stdout.decode("utf-8", "replace").strip():
            raise GitAuthoringError(
                f"the selected private {label} is Git-tracked inside the "
                f"authoring repository ({resolved}); raw/registry paths must "
                f"stay out of Git — untrack it or select a location outside "
                f"the repository"
            )


def _refuse_unsafe_worktree_mutation(
    repo_root: Path,
    kb_path: Path,
    relative_paths: list[str],
    *,
    allow_untracked: frozenset[str] = frozenset(),
) -> None:
    """Refuse a mutation target that would overwrite uncommitted author work.

    Spec 0008 §2: operations refuse a detached/unselected mutation target,
    unresolved Git conflicts, and an operation that would overwrite unrelated
    uncommitted edits — there is no implicit stash. Every affected path must be
    clean in the worktree before the helper writes it (finding 1).
    """
    if _git_exit(repo_root, "symbolic-ref", "-q", "HEAD") != 0:
        raise GitAuthoringError(
            "refusing to mutate a detached HEAD; select a registered branch "
            "worktree for the authoring operation"
        )
    conflicted = _git(repo_root, "diff", "--name-only", "--diff-filter=U").decode().strip()
    if conflicted:
        paths = ", ".join(conflicted.splitlines()[:5])
        raise GitAuthoringError(
            f"refusing to mutate a worktree with unresolved Git conflicts: {paths}"
        )
    for relative in relative_paths:
        target = kb_path / relative
        status = _git(
            repo_root,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored=matching",
            "--",
            str(target),
        ).decode()
        if relative in allow_untracked and status.startswith("??"):
            continue
        if (
            status.strip()
            and not target.exists()
            and not target.is_symlink()
            and all(line.startswith("!! ") for line in status.splitlines())
        ):
            continue  # an ignored parent is not an existing destination collision
        if status.strip():
            raise GitAuthoringError(
                f"uncommitted author changes exist at {relative!r}; the ingest "
                f"would overwrite them — commit, stash, or remove them "
                f"explicitly first (no implicit stash)"
            )


def _refuse_private_selection_inside_tree(kb_root: Path, *paths: Path | None) -> None:
    """Refuse a private registry/store selection inside the authoring subtree.

    Spec 0008 §3.2: authoring worktrees use the explicitly configured private
    source history/store — never raw bytes copied into Git. A private state
    directory inside the Knowledge Base subtree would be committed with the
    next author commit, so selection fails closed here.
    """
    for path in paths:
        if path is None:
            continue
        resolved = Path(path).resolve()
        if resolved == kb_root or resolved.is_relative_to(kb_root):
            raise GitAuthoringError(
                f"the private source registry/store must live OUTSIDE the authoring "
                f"Knowledge Base subtree ({kb_root}); {resolved} is inside it and "
                f"would be copied into Git"
            )


def _registry_root(registry: SourceRegistry | None) -> Path | None:
    return Path(registry.root).resolve() if registry is not None else None


def _normalize_expected(expected_current: str | None) -> str:
    """Return the normalized explicit baseline; refuse an unchecked mode.

    Spec 0008 §4.1: ``none`` explicitly means an absent current pointer, never
    "ignore the current state". An omitted expectation is refused at the SDK
    boundary so every admission is bound to one exact reviewed baseline
    (finding 3) — there is no ``(any)`` mode.
    """
    if expected_current is None or not str(expected_current).strip():
        raise GitAuthoringError(
            "an explicit expected-current baseline is required: pass 'none' or "
            "the exact active Published Version label"
        )
    if expected_current == _EXPECTED_NONE:
        return _EXPECTED_NONE
    return validate_published_version(expected_current)


def _check_pointer_expectation(
    observed: str | None, expected_current: str | None, version: str
) -> None:
    """Fail closed when the explicit expected-current baseline cannot advance."""
    expected = _normalize_expected(expected_current)
    if expected == _EXPECTED_NONE:
        if observed is not None:
            raise PublicationConflict(
                f"cannot activate {version!r}: expected no current published version "
                f"(--expected-current none), but {observed!r} is active — review the "
                f"actual current state and confirm against it"
            )
        return
    if observed is None:
        raise PublicationConflict(
            f"cannot activate {version!r}: expected the active version to be "
            f"{expected!r}, but no published version exists yet at this destination"
        )
    if observed != expected:
        raise PublicationConflict(
            f"cannot activate {version!r}: expected the active version to be "
            f"{expected!r} but it is {observed!r} — re-review against the actual "
            f"current state"
        )


def _eligible_candidate_support(
    candidate: SourceReferenceManifest,
    entity_id: str,
    declared_sources: frozenset[str],
    source_registry: SourceRegistry | None,
    *,
    exclude: frozenset[str] = frozenset(),
) -> int:
    """Count active bindings declared on the Entity and pinned to registered versions."""
    return sum(
        1
        for source_id, digest in candidate.bindings.get(entity_id, {}).items()
        if source_id not in exclude
        and source_id in declared_sources
        and candidate.sources.get(source_id) == "active"
        and source_registry is not None
        and source_registry.find_version(source_id, digest) is not None
    )


def _source_impact(
    candidate: SourceReferenceManifest,
    admitted: SealedSourceReferences | None,
    page_sources: dict[str, frozenset[str]] | None = None,
    source_registry: SourceRegistry | None = None,
) -> list[PublicationSourceImpact]:
    """Compare admitted and candidate source references (spec 0008 §3.3).

    Source-lifecycle changes are disclosed per source; every binding change
    additionally discloses the affected Entity's support disposition computed
    from the candidate's ELIGIBLE references: ``still-supported`` when another
    eligible active binding remains, ``sole-source-lost`` when the entity loses
    its last eligible support, and ``page-removed`` when the entity itself is
    gone from the candidate (an explicit Page Removal). A digest change is a
    ``replaced`` binding whose exact new version still supports the page —
    distinct from a removed binding (finding 15).
    """
    page_sources = page_sources or {}
    page_entities = set(page_sources)
    impact: list[PublicationSourceImpact] = []
    if admitted is None:
        impact.extend(
            PublicationSourceImpact(source_id=source_id, change="added", support="newly-managed")
            for source_id in sorted(candidate.sources)
        )
        for entity_id, entity_bindings in sorted(candidate.bindings.items()):
            for source_id in sorted(entity_bindings):
                impact.append(
                    PublicationSourceImpact(
                        source_id=source_id,
                        change="bound",
                        entity_id=entity_id,
                        support="newly-supported",
                    )
                )
        return impact
    for source_id in sorted(set(admitted.sources) | set(candidate.sources)):
        before = admitted.sources.get(source_id)
        after = candidate.sources.get(source_id)
        if before == after:
            continue
        if before is None:
            impact.append(
                PublicationSourceImpact(
                    source_id=source_id, change="added", support="newly-managed"
                )
            )
        elif after is None:
            impact.append(
                PublicationSourceImpact(source_id=source_id, change="removed", support="unmanaged")
            )
        elif before == "active" and after == "retired":
            impact.append(
                PublicationSourceImpact(
                    source_id=source_id, change="retired", support="review-required"
                )
            )
        else:
            impact.append(
                PublicationSourceImpact(
                    source_id=source_id, change="reactivated", support="review-required"
                )
            )
    admitted_flat = {
        (entity_id, source_id): digest
        for entity_id, entity_bindings in admitted.bindings.items()
        for source_id, digest in entity_bindings.items()
    }
    candidate_flat = {
        (entity_id, source_id): digest
        for entity_id, entity_bindings in candidate.bindings.items()
        for source_id, digest in entity_bindings.items()
    }
    for key in sorted(set(admitted_flat) | set(candidate_flat)):
        before = admitted_flat.get(key)
        after = candidate_flat.get(key)
        if before == after:
            continue
        entity_id, source_id = key
        if after is None:
            # A REMOVED binding (not a replacement): the disposition comes
            # from the candidate's remaining eligible support (finding 15).
            if entity_id not in page_entities:
                support = "page-removed"
            elif _eligible_candidate_support(
                candidate,
                entity_id,
                page_sources.get(entity_id, frozenset()),
                source_registry,
                exclude=frozenset({source_id}),
            ):
                support = "still-supported"
            else:
                support = "sole-source-lost"
            impact.append(
                PublicationSourceImpact(
                    source_id=source_id,
                    change="unbound",
                    entity_id=entity_id,
                    support=support,
                )
            )
            continue
        change = "bound" if before is None else "replaced"
        support = "newly-supported" if before is None else "still-supported"
        impact.append(
            PublicationSourceImpact(
                source_id=source_id,
                change=change,
                entity_id=entity_id,
                support=support,
            )
        )
    return impact


def _page_mutations(candidate_content: dict[str, bytes], active_manifest: Any) -> list[str]:
    """Report path-level canonical mutations against the active version."""
    if active_manifest is None:
        return sorted(f"added: {path}" for path in candidate_content)
    active_files = {entry.path: entry.digest for entry in active_manifest.files}
    mutations: list[str] = []
    for path, raw in sorted(candidate_content.items()):
        digest = hashlib.sha256(raw).hexdigest()
        if path not in active_files:
            mutations.append(f"added: {path}")
        elif active_files[path] != digest:
            mutations.append(f"changed: {path}")
    mutations.extend(
        f"removed: {entry.path}"
        for entry in sorted(active_manifest.files, key=lambda e: e.path)
        if entry.path not in candidate_content
    )
    return sorted(mutations)


def _derived_content(captured: CapturedRevision) -> dict[str, bytes]:
    """Generate every requested derived artifact from the captured facts."""
    graph_bytes = _serialize_graph_bytes(captured.kb, captured.fingerprint)
    _validate_graph_state(graph_bytes, captured.fingerprint, captured.revision)
    derived: dict[str, bytes] = {DERIVED_GRAPH_ARTIFACT: graph_bytes}
    indexes = generate_navigation_indexes(captured.kb.pages)
    root_index = indexes.get("index.md")
    if root_index is not None:
        derived[DERIVED_NAVIGATION_INDEX] = root_index.encode("utf-8")
    if captured.kb.control is not None:
        hot = generate_hot_index(captured.kb.control, captured.kb.pages)
        if hot is not None:
            derived[DERIVED_HOT_INDEX] = hot.encode("utf-8")
    return derived


def _review_digest_payload(review: PublicationReview) -> bytes:
    """Canonical, order-stable serialization of every review-bound input."""
    payload = {
        "validator_contract": review.validator_contract,
        "revision": review.revision,
        "subtree": review.subtree,
        "version": review.version,
        "fingerprint": review.fingerprint,
        "manifest_digest": review.manifest_digest,
        "namespace": review.namespace,
        "source_refs": sorted(review.source_refs),
        "bindings": sorted(review.bindings),
        "source_impact": sorted(
            f"{item.source_id}|{item.change}|{item.entity_id}|{item.page_title}|{item.support}"
            for item in review.source_impact
        ),
        "page_mutations": sorted(review.page_mutations),
        "blocking_diagnostics": sorted(review.blocking_diagnostics),
        "requested_artifacts": sorted(review.requested_artifacts),
        "destination": review.destination,
        "destination_identity": review.destination_identity,
        "expected_current": review.expected_current,
        "adoption": review.adoption,
        "retention": review.retention,
    }
    return msgspec.json.encode(payload)


def preview_publication(
    kb_root: str | Path,
    revision: str,
    destination: str | Path,
    expected_current: str | None = None,
    *,
    source_registry: SourceRegistry | None = None,
    artifact_store: SourceArtifactStore | None = None,
    retention_required: bool = False,
    s3_location: S3Location | None = None,
    metadata_store: SourceArtifactStore | None = None,
    destination_identity: str | None = None,
    retrieval: str = "zero-index",
) -> PublicationReview:
    """Produce the stateless Publication Review for one exact revision.

    No raw upload, registration, source lifecycle change, version
    preparation, pointer mutation, or persistent pending admission occurs:
    the returned :class:`PublicationReview` (and its deterministic digest) is
    the only output. The digest binds the reviewed revision/subtree, canonical
    fingerprint, manifest digest and namespace, source references and impact,
    page mutations, blocking diagnostics, requested derived artifacts, the
    secret-free destination identity, the expected-current baseline, the
    retention policy, and the validator contract identity (spec 0008 §4.1).
    """
    kb_path = Path(kb_root).resolve()
    destination_path: Path | None = None
    if s3_location is None:
        if str(destination).startswith("s3://"):
            raise GitAuthoringError(
                "S3 publication requires an explicit S3Location and Git admission"
            )
        if retrieval not in {"zero-index", "lancedb"}:
            raise GitAuthoringError("retrieval must be 'zero-index' or 'lancedb'")
        destination_path = Path(destination).resolve()
        metadata_store = None
        target_identity = str(destination_path)
    else:
        if not str(destination).startswith("s3://"):
            raise GitAuthoringError("an S3Location requires a credential-free s3:// destination")
        if s3_location.destination_uri is None or (
            str(destination).rstrip("/") != s3_location.destination_uri.rstrip("/")
        ):
            raise GitAuthoringError("S3 destination URI does not match the selected S3Location")
        target_identity = destination_identity or s3_location.effective_target_identity or ""
        if destination_identity and s3_location.effective_target_identity not in {
            None,
            destination_identity,
        }:
            raise GitAuthoringError("S3 destination identity does not match the S3Location")
        if not target_identity:
            raise GitAuthoringError("an effective S3 destination identity is required")
        metadata_store = metadata_store or local_publication_metadata_store(target_identity)
    metadata_root = _local_store_root(metadata_store)
    _refuse_private_selection_inside_tree(
        kb_path,
        _registry_root(source_registry),
        _local_store_root(artifact_store),
        metadata_root,
    )
    captured = capture_revision(kb_path, revision)
    _refuse_tracked_private_paths(
        captured.repo_root,
        "source registry/store",
        _registry_root(source_registry),
        _local_store_root(artifact_store),
        metadata_root,
    )
    review = _review_from_capture(
        captured,
        destination_path if destination_path is not None else destination,
        expected_current,
        source_registry=source_registry,
        artifact_store=artifact_store,
        retention_required=retention_required,
        s3_location=s3_location,
        metadata_store=metadata_store,
        destination_identity=target_identity,
        retrieval=retrieval,
    )
    return review


def _local_store_root(artifact_store: SourceArtifactStore | None) -> Path | None:
    root = getattr(artifact_store, "root", None)
    return Path(root).resolve() if root is not None else None


def _load_s3_publication_record(
    store: SourceArtifactStore, version: str, manifest: Any
) -> S3PublicationRecord | None:
    try:
        raw = store.get_publication_record(version)
    except ArtifactUnavailable:
        return None
    try:
        record = msgspec.json.decode(raw, type=S3PublicationRecord)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"private Git admission record for S3 Published Version {version!r} is malformed"
        ) from exc
    receipt = record.receipt
    sealed_digest = hashlib.sha256(msgspec.json.encode(record.sealed)).hexdigest()
    if sealed_digest != receipt.source_references_digest:
        raise GitAuthoringError(
            f"private Source References for S3 Published Version {version!r} "
            "do not match the admission receipt"
        )
    if (
        receipt.version != version
        or receipt.revision != manifest.revision
        or receipt.subtree != manifest.subtree
        or receipt.fingerprint != manifest.fingerprint
        or receipt.manifest_digest != manifest.source_reference_digest
        or record.sealed.published_version != version
        or record.sealed.revision != receipt.revision
        or record.sealed.fingerprint != receipt.fingerprint
        or record.sealed.manifest_digest != receipt.manifest_digest
    ):
        raise GitAuthoringError(
            f"private Git admission record for S3 Published Version {version!r} "
            "does not match its public manifest"
        )
    try:
        binding_raw = store.get_binding_manifest(version)
    except ArtifactUnavailable as exc:
        raise GitAuthoringError(
            f"private Source Binding Manifest for S3 Published Version {version!r} is missing"
        ) from exc
    if hashlib.sha256(binding_raw).hexdigest() != record.binding_manifest_digest:
        raise GitAuthoringError(
            f"private Source Binding Manifest for S3 Published Version {version!r} "
            "does not match its admission record"
        )
    try:
        binding = msgspec.json.decode(binding_raw, type=SourceBindingManifest)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"private Source Binding Manifest for S3 Published Version {version!r} is malformed"
        ) from exc
    actual_bindings: dict[str, dict[str, str]] = {}
    for entry in binding.entries:
        entity_bindings = actual_bindings.setdefault(entry.entity_id, {})
        if entry.source_id in entity_bindings:
            raise GitAuthoringError(
                f"private Source Binding Manifest for {version!r} contains duplicate entries"
            )
        entity_bindings[entry.source_id] = entry.content_hash
    requested_artifacts = [DERIVED_GRAPH_ARTIFACT]
    if any(
        item.path == f"{LANCE_DERIVED_DIR}/{LANCE_COMPLETION_OBJECT}"
        for item in manifest.derived_files
    ):
        requested_artifacts.append("derived/lance")
    if (
        receipt.requested_artifacts != requested_artifacts
        or binding.published_version != version
        or binding.fingerprint != receipt.fingerprint
        or binding.revision != receipt.revision
        or binding.subtree != receipt.subtree
        or binding.source_reference_digest != receipt.manifest_digest
        or actual_bindings != record.sealed.bindings
    ):
        raise GitAuthoringError(
            f"private binding records for S3 Published Version {version!r} disagree"
        )
    return record


def _legacy_s3_source_impact(
    manifest: SourceReferenceManifest,
    bindings: SourceBindingManifest | None,
    historical_pages: list[Any],
    candidate_pages: list[Any],
    blocking: list[str],
) -> list[PublicationSourceImpact]:
    if bindings is None:
        return []

    def page_identity(page: Any) -> str:
        return getattr(page, "id", None) or page.title

    historical_by_id = {page_identity(page): page for page in historical_pages}
    historical_by_title: dict[str, list[Any]] = {}
    for page in historical_pages:
        historical_by_title.setdefault(page.title, []).append(page)
    current: dict[tuple[str, str], tuple[str, str]] = {}
    for page in candidate_pages:
        entity_id = page_identity(page)
        for source in getattr(page, "sources", ()):
            if source.id:
                current[(entity_id, source.id)] = (
                    page.title,
                    manifest.bindings.get(entity_id, {}).get(source.id, ""),
                )

    impacts: list[PublicationSourceImpact] = []
    for previous in bindings.entries:
        if previous.entity_id:
            historical_page = historical_by_id.get(previous.entity_id)
            if historical_page is None:
                blocking.append(
                    f"legacy S3 binding for {previous.source_id!r} refers to unknown "
                    f"historical Entity {previous.entity_id!r}; resolve its identity explicitly"
                )
                continue
        else:
            matches = historical_by_title.get(previous.page_title, [])
            if len(matches) != 1:
                blocking.append(
                    f"legacy S3 binding for {previous.source_id!r} has "
                    f"{'unknown' if not matches else 'ambiguous'} historical Page identity "
                    f"{previous.page_title!r}; resolve its identity explicitly"
                )
                continue
            historical_page = matches[0]

        entity_id = page_identity(historical_page)
        status = manifest.sources.get(previous.source_id)
        if status is None:
            blocking.append(
                f"legacy S3 binding for {previous.source_id!r} is absent from the candidate "
                "Source Reference Manifest; explicitly retain or retire it"
            )
            continue
        if status == "retired":
            impacts.append(
                PublicationSourceImpact(
                    source_id=previous.source_id,
                    change="retired from legacy S3 binding",
                    entity_id=entity_id,
                    page_title=historical_page.title,
                    support="the legacy binding was explicitly retired",
                )
            )
            continue

        candidate = current.get((entity_id, previous.source_id))
        if candidate is None:
            blocking.append(
                f"legacy S3 binding for active source {previous.source_id!r} has no candidate "
                f"Page support on historical Entity {entity_id!r}; resolve it before adoption"
            )
            continue
        title, digest = candidate
        if not digest:
            blocking.append(
                f"legacy S3 binding for active source {previous.source_id!r} has no exact "
                f"candidate binding on Entity {entity_id!r}; resolve it before adoption"
            )
            continue
        if digest != previous.content_hash:
            impacts.append(
                PublicationSourceImpact(
                    source_id=previous.source_id,
                    change="replaced legacy binding",
                    entity_id=entity_id,
                    page_title=title,
                    support=f"{previous.content_hash} -> {digest}",
                )
            )
    return impacts


def _review_from_capture(
    captured: CapturedRevision,
    destination: Path | str,
    expected_current: str | None,
    *,
    source_registry: SourceRegistry | None,
    artifact_store: SourceArtifactStore | None = None,
    retention_required: bool,
    s3_location: S3Location | None = None,
    metadata_store: SourceArtifactStore | None = None,
    destination_identity: str | None = None,
    retrieval: str = "zero-index",
) -> PublicationReview:
    """Build the review (and recompute its digest) from captured facts only."""
    manifest = captured.manifest
    blocking: list[str] = []
    if not captured.report.is_valid:
        blocking.extend(
            f"{issue.file}: {issue.field}: {issue.message}"
            for issue in captured.report.issues
            if issue.severity == "error"
        )
    blocking.extend(
        f"{issue.file}: {issue.field}: {issue.message}"
        for issue in captured.report.issues
        if issue.severity == "warning"
        and issue.field == "internal-links"
        and issue.message.startswith("broken internal link")
    )
    registry_consulted = source_registry is not None
    legacy_source_impact: list[PublicationSourceImpact] = []
    if manifest.bindings and source_registry is None:
        blocking.append(
            "the revision carries managed source bindings but no private source "
            "registry is selected; select the shared registry explicitly"
        )
    blocking.extend(validate_source_references(manifest, captured.kb, registry=source_registry))

    expected = _normalize_expected(expected_current)
    destination_path = Path(destination).resolve() if s3_location is None else None
    if s3_location is None:
        assert destination_path is not None
        location = PublishedFilesystemLocation(destination_path)
        observed = location.read_pointer()
        active_manifest = location.read_manifest(observed) if observed is not None else None
        admitted = _load_sealed(destination_path, observed) if observed is not None else None
        target_identity = str(destination_path)
    else:
        target_identity = destination_identity or s3_location.effective_target_identity
        if not target_identity:
            raise GitAuthoringError(
                "an effective, credential-free S3 destination identity is required"
            )
        metadata_store = metadata_store or local_publication_metadata_store(target_identity)
        observed = observe_current_pointer(s3_location.store, s3_location.prefix).version
        active_manifest = None
        admitted = None
        if observed is not None:
            active_manifest, _content = s3_location.published_version_content(observed)
            record = _load_s3_publication_record(metadata_store, observed, active_manifest)
            if active_manifest.revision:
                if record is None:
                    raise GitAuthoringError(
                        f"active S3 Published Version {observed!r} has Git provenance but no "
                        "private admission record; repair private metadata before publication"
                    )
                admitted = record.sealed
            else:
                try:
                    legacy_raw = metadata_store.get_binding_manifest(observed)
                except ArtifactUnavailable:
                    # First-native-adoption compatibility (D1): pre-Git S3
                    # publications sealed their exact Source Binding Manifests
                    # in the configured private Source Artifact Store; adoption
                    # still compares that exact history (spec 0008 §§3.3/§5).
                    legacy_raw = None
                    if artifact_store is not None:
                        try:
                            legacy_raw = artifact_store.get_binding_manifest(observed)
                        except ArtifactUnavailable:
                            legacy_raw = None
                if legacy_raw is None:
                    legacy_bindings = None
                else:
                    try:
                        legacy_bindings = msgspec.json.decode(
                            legacy_raw, type=SourceBindingManifest
                        )
                    except msgspec.DecodeError as exc:
                        raise GitAuthoringError(
                            f"legacy S3 Source Binding Manifest for {observed!r} is malformed"
                        ) from exc
                    if (
                        legacy_bindings.published_version != observed
                        or legacy_bindings.fingerprint != active_manifest.fingerprint
                    ):
                        # D1-A: a misplaced/restored manifest, or another KB's
                        # version under the same legacy label, is NOT this
                        # version's history — refuse with a repair diagnostic
                        # instead of comparing or treating it as absent.
                        raise GitAuthoringError(
                            f"the legacy S3 Source Binding Manifest for {observed!r} does "
                            "not match the active Published Version's identity "
                            "(published_version/fingerprint); repair the private "
                            "legacy store entry before adoption"
                        )
                if legacy_bindings is not None:
                    container_uri = s3_location.destination_uri
                    if container_uri is None:
                        raise GitAuthoringError("a credential-free S3 destination URI is required")
                    if s3_location.prefix:
                        container_uri = container_uri[: -(len(s3_location.prefix) + 1)]
                    historical_pages = (
                        S3Location(
                            s3_location.store,
                            s3_location.prefix,
                            version=observed,
                            store_uri=container_uri,
                        )
                        .resolve()
                        .pages
                    )
                    legacy_source_impact.extend(
                        _legacy_s3_source_impact(
                            manifest,
                            legacy_bindings,
                            list(historical_pages),
                            captured.kb.pages,
                            blocking,
                        )
                    )
        location = None
    _check_pointer_expectation(observed, expected_current, captured.revision)

    adoption: str
    if observed is None:
        adoption = (
            "first Git publication at this destination: no prior admitted Published "
            "Version ancestry exists here"
        )
    elif admitted is None:
        adoption = (
            f"adopt legacy Published Version {observed!r}: the exact active snapshot is shown "
            "below; no native Git ancestry or admission record is fabricated"
        )
    else:
        if admitted.namespace != manifest.namespace:
            raise GitAuthoringError(
                f"an admitted namespace cannot change in an ordinary successor "
                f"publication: destination admits {admitted.namespace!r}, the "
                f"candidate declares {manifest.namespace!r}"
            )
        admitted_revision = admitted.revision
        if not _FULL_COMMIT_PATTERN.match(admitted_revision):
            raise GitAuthoringError(
                f"the admitted Published Version {observed!r} does not record a native Git "
                "revision in its sealed provenance; explicit adoption or repair is required"
            )
        merge_base = (
            _git(captured.repo_root, "merge-base", admitted_revision, captured.revision)
            .decode()
            .strip()
        )
        if merge_base != admitted_revision:
            raise GitAuthoringError(
                f"the candidate revision {captured.revision} is not a descendant of the admitted "
                f"revision {admitted_revision}; reconcile the Git branch before publication"
            )
        adoption = f"successor to admitted Published Version {observed!r}"
        disappeared = sorted(set(admitted.sources) - set(manifest.sources))
        if disappeared:
            blocking.append(
                "managed source identities disappeared from the Source Reference Manifest: "
                + ", ".join(disappeared)
                + "; explicitly reclassify or remove supported Pages before publication"
            )

    derived = _derived_content(captured)
    source_refs = [
        f"{source_id}:{status}" for source_id, status in sorted(manifest.sources.items())
    ]
    bindings = [
        f"{entity_id} -> {source_id}:{digest}"
        for entity_id, values in sorted(manifest.bindings.items())
        for source_id, digest in sorted(values.items())
    ]
    public_only = sorted(
        {
            source.id
            for page in captured.kb.pages
            for source in page.sources
            if source.id and source.id not in manifest.sources
        }
    )
    page_sources = {
        page.id: frozenset(source.id for source in page.sources if source.id)
        for page in captured.kb.pages
        if getattr(page, "id", None)
    }
    requested = [DERIVED_GRAPH_ARTIFACT] if s3_location is not None else sorted(derived)
    if retrieval == "lancedb":
        requested.append("derived/lance")
        requested.sort()
    review = PublicationReview(
        validator_contract=VALIDATOR_CONTRACT_ID,
        kb_path=str(captured.kb_root),
        repository=str(captured.repo_root),
        subtree=captured.subtree,
        revision=captured.revision,
        version=captured.revision,
        namespace=manifest.namespace,
        fingerprint=captured.fingerprint.digest,
        manifest_digest=captured.manifest_digest,
        source_refs=source_refs,
        bindings=bindings,
        source_impact=(
            _source_impact(manifest, admitted, page_sources, source_registry) + legacy_source_impact
        ),
        page_mutations=_page_mutations(captured.content, active_manifest),
        blocking_diagnostics=sorted(blocking),
        public_only_sources=public_only,
        requested_artifacts=requested,
        destination=str(destination_path) if destination_path is not None else str(destination),
        expected_current=expected,
        observed_current=observed,
        adoption=adoption,
        retention="required" if retention_required else "disabled",
        registry_consulted=registry_consulted,
        destination_identity=target_identity,
        review_digest="",
    )
    digest = hashlib.sha256(_review_digest_payload(review)).hexdigest()
    return msgspec.structs.replace(review, review_digest=digest)


# ---------------------------------------------------------------------------
# Explicit confirmation, immutable versions, expected-current activation.
# ---------------------------------------------------------------------------


def _same_s3_binding_manifest(
    actual: SourceBindingManifest, expected: SourceBindingManifest
) -> bool:
    return (
        actual.published_version == expected.published_version
        and actual.fingerprint == expected.fingerprint
        and actual.entries == expected.entries
        and actual.revision == expected.revision
        and actual.subtree == expected.subtree
        and actual.source_reference_digest == expected.source_reference_digest
        and actual.validator_contract == expected.validator_contract
    )


def _persist_s3_binding_manifest(
    store: SourceArtifactStore, expected: SourceBindingManifest
) -> bytes:
    raw = msgspec.json.encode(expected)
    try:
        existing = store.get_binding_manifest(expected.published_version)
    except ArtifactUnavailable:
        try:
            store.put_binding_manifest(expected.published_version, raw)
            existing = store.get_binding_manifest(expected.published_version)
        except ArtifactStoreError:
            existing = store.get_binding_manifest(expected.published_version)
    try:
        decoded = msgspec.json.decode(existing, type=SourceBindingManifest)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"private Source Binding Manifest for {expected.published_version!r} is malformed"
        ) from exc
    if not _same_s3_binding_manifest(decoded, expected):
        raise GitAuthoringError(
            f"private Source Binding Manifest for {expected.published_version!r} "
            "already exists with different immutable bindings"
        )
    return existing


def _same_s3_publication_record(actual: S3PublicationRecord, expected: S3PublicationRecord) -> bool:
    return (
        msgspec.structs.replace(actual.receipt, created_at="")
        == msgspec.structs.replace(expected.receipt, created_at="")
        and msgspec.structs.replace(actual.sealed, created_at="")
        == msgspec.structs.replace(expected.sealed, created_at="")
        and actual.binding_manifest_digest == expected.binding_manifest_digest
    )


def _persist_s3_publication_record(
    store: SourceArtifactStore, expected: S3PublicationRecord
) -> S3PublicationRecord:
    version = expected.receipt.version
    try:
        raw = store.get_publication_record(version)
    except ArtifactUnavailable:
        try:
            store.put_publication_record(version, msgspec.json.encode(expected))
            raw = store.get_publication_record(version)
        except ArtifactStoreError:
            raw = store.get_publication_record(version)
    try:
        actual = msgspec.json.decode(raw, type=S3PublicationRecord)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"private Git admission record for {version!r} is malformed"
        ) from exc
    if not _same_s3_publication_record(actual, expected):
        raise GitAuthoringError(
            f"private Git admission record for {version!r} already binds a different review"
        )
    return actual


def _persist_s3_activation(
    store: SourceArtifactStore, receipt: PublicationReceipt
) -> S3ActivationReceipt:
    expected = S3ActivationReceipt(
        version=receipt.version,
        review_digest=receipt.review_digest,
        expected_current=receipt.expected_current,
        activated_at=_now(),
    )
    try:
        raw = store.get_activation_receipt(receipt.version)
    except ArtifactUnavailable:
        try:
            store.put_activation_receipt(receipt.version, msgspec.json.encode(expected))
            raw = store.get_activation_receipt(receipt.version)
        except ArtifactStoreError:
            raw = store.get_activation_receipt(receipt.version)
    try:
        actual = msgspec.json.decode(raw, type=S3ActivationReceipt)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"private activation receipt for {receipt.version!r} is malformed"
        ) from exc
    if (
        actual.version != receipt.version
        or actual.review_digest != receipt.review_digest
        or actual.expected_current != receipt.expected_current
    ):
        raise GitAuthoringError(
            f"private activation receipt for {receipt.version!r} binds a different review"
        )
    return actual


def _reconcile_active_s3_activation(
    location: S3Location, metadata_store: SourceArtifactStore
) -> None:
    """Record the verified outgoing Git activation before another pointer transition.

    Reconciliation proves admission/activation truth only: the outgoing
    version's manifest identity, its private admission record, and the
    activation receipt. Outgoing derived-artifact health is deliberately not
    re-required here — a damaged active index must not block recovery to an
    independently verified healthy target, and legacy versions predate the
    new inventory (D2). Every activation path still fully validates the
    TARGET version before CAS (spec 0008 §5).
    """
    active = observe_current_pointer(location.store, location.prefix).version
    if active is None:
        return
    manifest = location._read_manifest(active)
    if not manifest.revision:
        return  # legacy Published Versions have no Git activation receipt
    if manifest.format_identity != VALIDATOR_CONTRACT_ID:
        raise GitAuthoringError(
            f"active S3 Published Version {active!r} has incompatible Git provenance"
        )
    record = _load_s3_publication_record(metadata_store, active, manifest)
    if record is None:
        raise GitAuthoringError(
            f"active S3 Published Version {active!r} has Git provenance but no private "
            "admission record; refusing a pointer transition"
        )
    _persist_s3_activation(metadata_store, record.receipt)


def _expected_s3_pointer(expected_current: str) -> str:
    return expected_current


def _s3_manifest_matches_candidate(manifest: Any, captured: CapturedRevision) -> bool:
    return (
        manifest.version == captured.revision
        and manifest.fingerprint == captured.fingerprint.digest
        and manifest.revision == captured.revision
        and manifest.subtree == captured.subtree
        and manifest.source_reference_digest == captured.manifest_digest
        and manifest.format_identity == VALIDATOR_CONTRACT_ID
    )


def _retry_s3_publication(
    location: S3Location,
    captured: CapturedRevision,
    expected_current: str,
    confirm_digest: str,
    *,
    artifact_store: SourceArtifactStore | None,
    metadata_store: SourceArtifactStore,
    retention_required: bool,
    retrieval: str,
    destination_identity: str,
) -> PublicationReceipt | None:
    version = captured.revision
    try:
        raw = metadata_store.get_publication_record(version)
    except ArtifactUnavailable:
        return None
    try:
        record = msgspec.json.decode(raw, type=S3PublicationRecord)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(
            f"private Git admission record for {version!r} is malformed"
        ) from exc
    receipt = record.receipt
    if receipt.review_digest != confirm_digest:
        return None
    requested = [DERIVED_GRAPH_ARTIFACT]
    if retrieval == "lancedb":
        requested.append("derived/lance")
    if (
        receipt.version != version
        or receipt.revision != captured.revision
        or receipt.subtree != captured.subtree
        or receipt.fingerprint != captured.fingerprint.digest
        or receipt.manifest_digest != captured.manifest_digest
        or receipt.destination_identity != destination_identity
        or receipt.expected_current != expected_current
        or receipt.validator_contract != VALIDATOR_CONTRACT_ID
        or receipt.retention != ("required" if retention_required else "disabled")
        or receipt.requested_artifacts != requested
    ):
        raise ConfirmationRefused("stored S3 admission record binds different review inputs")
    if retention_required:
        _require_retained_coverage(
            artifact_store,
            captured.kb.pages,
            _captured_coverage_entries(captured),
        )
    import lumio_wiki.s3_publish as s3_publish

    manifest = _load_complete_version(
        s3_publish._require_obstore(), location.store, location.prefix, version
    )
    if not _s3_manifest_matches_candidate(manifest, captured):
        raise GitAuthoringError(
            f"S3 Published Version {version!r} does not match its captured Git candidate"
        )
    checked_record = _load_s3_publication_record(metadata_store, version, manifest)
    if checked_record is None or not _same_s3_publication_record(checked_record, record):
        raise GitAuthoringError(f"private S3 admission state for {version!r} changed")
    try:
        activation_raw = metadata_store.get_activation_receipt(version)
    except ArtifactUnavailable:
        activation_raw = None
    if activation_raw is not None:
        try:
            activation = msgspec.json.decode(activation_raw, type=S3ActivationReceipt)
        except msgspec.DecodeError as exc:
            raise GitAuthoringError(
                f"private activation receipt for {version!r} is malformed"
            ) from exc
        if (
            activation.version != version
            or activation.review_digest != receipt.review_digest
            or activation.expected_current != receipt.expected_current
        ):
            raise GitAuthoringError(
                f"private activation receipt for {version!r} binds a different review"
            )
        return msgspec.structs.replace(receipt, activated=True)

    observed = observe_current_pointer(location.store, location.prefix).version
    if observed == version:
        _persist_s3_activation(metadata_store, receipt)
        return msgspec.structs.replace(receipt, activated=True)
    expected_pointer = _expected_s3_pointer(expected_current)
    observed_baseline = None if expected_current == _EXPECTED_NONE else expected_current
    if observed != observed_baseline:
        raise S3PublicationConflict(
            f"cannot recover S3 publication {version!r}: active pointer moved from "
            f"{expected_current!r} to {observed!r}; it will not be reactivated"
        )
    _reconcile_active_s3_activation(location, metadata_store)
    if retention_required:
        _require_retained_coverage(
            artifact_store,
            captured.kb.pages,
            _captured_coverage_entries(captured),
        )
    _activate_existing_s3_version(location.store, location.prefix, version, expected_pointer)
    _persist_s3_activation(metadata_store, receipt)
    return msgspec.structs.replace(receipt, activated=True)


def _publish_s3_revision(
    kb_root: str | Path,
    revision: str,
    destination: str | Path,
    expected_current: str | None,
    confirm_digest: str,
    *,
    source_registry: SourceRegistry | None,
    artifact_store: SourceArtifactStore | None,
    retention_required: bool,
    s3_location: S3Location,
    metadata_store: SourceArtifactStore | None,
    destination_identity: str | None,
    retrieval: str,
    index_builder: IndexBuilder | None,
) -> PublicationReceipt:
    if retrieval not in {"zero-index", "lancedb"}:
        raise GitAuthoringError("retrieval must be 'zero-index' or 'lancedb'")
    if retrieval == "lancedb" and index_builder is None:
        raise GitAuthoringError("LanceDB retrieval requires a version-bound index builder")
    target_identity = destination_identity or s3_location.effective_target_identity
    if not target_identity:
        raise GitAuthoringError("an effective S3 destination identity is required")
    if destination_identity and s3_location.effective_target_identity not in {
        None,
        destination_identity,
    }:
        raise GitAuthoringError("S3 destination identity does not match the S3Location")
    if s3_location.destination_uri is None or (
        str(destination).rstrip("/") != s3_location.destination_uri.rstrip("/")
    ):
        raise GitAuthoringError("S3 destination URI does not match the selected S3Location")
    private_store = metadata_store or local_publication_metadata_store(target_identity)
    expected = _normalize_expected(expected_current)
    kb_path = Path(kb_root).resolve()
    roots = (
        _registry_root(source_registry),
        _local_store_root(artifact_store),
        _local_store_root(private_store),
    )
    _refuse_private_selection_inside_tree(kb_path, *roots)
    captured = capture_revision(kb_path, revision)
    _refuse_tracked_private_paths(captured.repo_root, "source registry/store", *roots)
    retried = _retry_s3_publication(
        s3_location,
        captured,
        expected,
        confirm_digest,
        artifact_store=artifact_store,
        metadata_store=private_store,
        retention_required=retention_required,
        retrieval=retrieval,
        destination_identity=target_identity,
    )
    if retried is not None:
        return retried
    review = _review_from_capture(
        captured,
        destination,
        expected_current,
        source_registry=source_registry,
        artifact_store=artifact_store,
        retention_required=retention_required,
        s3_location=s3_location,
        metadata_store=private_store,
        destination_identity=target_identity,
        retrieval=retrieval,
    )
    if review.review_digest != confirm_digest:
        raise ConfirmationRefused(
            "the confirmation no longer matches the recomputed S3 review; review the "
            "current target and confirm its new digest"
        )
    if review.blocking_diagnostics:
        raise GitAuthoringError(
            "the reviewed revision has blocking diagnostics and can never be admitted: "
            + "; ".join(review.blocking_diagnostics[:5])
        )
    if retention_required:
        if artifact_store is None:
            raise PublicationRetentionError(
                "artifact retention is required but no Source Artifact Store is configured"
            )
        _check_retention(artifact_store, captured.manifest)

    version = captured.revision
    sealed = SealedSourceReferences(
        published_version=version,
        revision=captured.revision,
        namespace=captured.manifest.namespace,
        fingerprint=captured.fingerprint.digest,
        manifest_digest=captured.manifest_digest,
        sources=dict(captured.manifest.sources),
        bindings={key: dict(value) for key, value in captured.manifest.bindings.items()},
        source_versions=_sealed_source_versions(captured, source_registry),
        created_at=_now(),
    )
    binding_entries = _captured_binding_entries(captured, source_registry)
    binding_manifest = build_binding_manifest(
        published_version=version,
        fingerprint=captured.fingerprint.digest,
        registry=source_registry,
        pages=captured.kb.pages,
        now=_now(),
        captured_entries=binding_entries,
        revision=captured.revision,
        subtree=captured.subtree,
        source_reference_digest=captured.manifest_digest,
        validator_contract=VALIDATOR_CONTRACT_ID,
    )
    receipt = PublicationReceipt(
        revision=captured.revision,
        version=version,
        subtree=captured.subtree,
        destination=str(destination),
        fingerprint=captured.fingerprint.digest,
        manifest_digest=captured.manifest_digest,
        source_references_digest=hashlib.sha256(msgspec.json.encode(sealed)).hexdigest(),
        review_digest=review.review_digest,
        expected_current=review.expected_current,
        validator_contract=VALIDATOR_CONTRACT_ID,
        retention=review.retention,
        created_at=_now(),
        destination_identity=target_identity,
        requested_artifacts=list(review.requested_artifacts),
        adoption=review.adoption,
    )

    def before_activation(prepared: Any) -> None:
        if (
            prepared.version != version
            or prepared.fingerprint != captured.fingerprint.digest
            or prepared.manifest.revision != captured.revision
            or prepared.manifest.source_reference_digest != captured.manifest_digest
        ):
            raise GitAuthoringError("S3 publisher changed the captured Git candidate")
        if retention_required:
            _require_retained_coverage(artifact_store, prepared.pages, prepared.binding_entries)
        _reconcile_active_s3_activation(s3_location, private_store)
        raw_binding = _persist_s3_binding_manifest(private_store, binding_manifest)
        record = S3PublicationRecord(
            receipt=receipt,
            sealed=sealed,
            binding_manifest_digest=hashlib.sha256(raw_binding).hexdigest(),
        )
        _persist_s3_publication_record(private_store, record)

    entries = _captured_binding_entries(captured, source_registry)

    def capture_candidate(_pages: list[Any]) -> list[SourceBindingEntry]:
        return list(entries)

    cast(Any, before_activation).capture_candidate = capture_candidate
    pointer_version = _expected_s3_pointer(review.expected_current)
    published_manifest = _publish_s3_captured_revision(
        s3_location.store,
        s3_location.prefix,
        captured=captured,
        expected_pointer_version=pointer_version,
        index_builder=index_builder if retrieval == "lancedb" else None,
        before_activation=before_activation,
    )
    if not _s3_manifest_matches_candidate(published_manifest, captured):
        raise GitAuthoringError("activated S3 manifest does not match the confirmed Git candidate")
    _persist_s3_activation(private_store, receipt)
    return msgspec.structs.replace(receipt, activated=True)


def publish_revision(
    kb_root: str | Path,
    revision: str,
    destination: str | Path,
    expected_current: str | None = None,
    confirm_digest: str = "",
    *,
    source_registry: SourceRegistry | None = None,
    artifact_store: SourceArtifactStore | None = None,
    retention_required: bool = False,
    s3_location: S3Location | None = None,
    metadata_store: SourceArtifactStore | None = None,
    destination_identity: str | None = None,
    retrieval: str = "zero-index",
    index_builder: IndexBuilder | None = None,
) -> PublicationReceipt:
    """Confirm the reviewed revision and activate one immutable local version.

    Recomputes every review-bound fact first: a changed commit, manifest,
    validator contract, requested artifact, destination, or active baseline
    refuses the old confirmation. Under the destination's mutation lock the
    immutable version directory is built from the captured Git bytes (the
    manifest is written last), verified by resolving it through the reader
    seam, the private source references are sealed and the admission receipt
    persisted and verified, and only then does exactly one expected-current
    pointer update activate the version. Retrying an already successful
    identical publication returns the existing verified receipt without
    rewriting immutable bytes or reactivating over an advanced pointer.
    """
    if not confirm_digest:
        raise ConfirmationRefused(
            "publication requires explicit confirmation of the displayed review "
            "digest (--confirm); passing validation or committing never admits "
            "automatically"
        )
    if s3_location is not None:
        return _publish_s3_revision(
            kb_root,
            revision,
            destination,
            expected_current,
            confirm_digest,
            source_registry=source_registry,
            artifact_store=artifact_store,
            retention_required=retention_required,
            s3_location=s3_location,
            metadata_store=metadata_store,
            destination_identity=destination_identity,
            retrieval=retrieval,
            index_builder=index_builder,
        )
    if str(destination).startswith("s3://"):
        raise GitAuthoringError(
            "S3 publication requires Git admission through an explicit S3Location"
        )
    if retrieval not in {"zero-index", "lancedb"}:
        raise GitAuthoringError("retrieval must be 'zero-index' or 'lancedb'")
    if retrieval == "lancedb" and index_builder is None:
        raise GitAuthoringError("LanceDB retrieval requires a version-bound index builder")
    if retrieval == "zero-index" and index_builder is not None:
        raise GitAuthoringError("an index builder requires retrieval='lancedb'")
    kb_path = Path(kb_root).resolve()
    destination_path = Path(destination).resolve()
    _refuse_private_selection_inside_tree(
        kb_path, _registry_root(source_registry), _local_store_root(artifact_store)
    )
    _refuse_destination_inside_worktree(kb_path, destination_path)
    captured = capture_revision(kb_path, revision)
    _refuse_tracked_private_paths(
        captured.repo_root,
        "source registry/store",
        _registry_root(source_registry),
        _local_store_root(artifact_store),
    )
    version = captured.revision

    # Idempotent fast path (spec 0008 §5): retrying an ALREADY attempted
    # identical publication — the admission receipt for this exact version
    # exists and the confirmation still matches its review digest — returns
    # the existing verified receipt AFTER re-enforcing the admission-bound
    # policy and verifying the complete version and private-binding state
    # (findings 8/9). Immutable version bytes are never rewritten, an
    # advanced pointer is never reactivated, and a receipt whose activation
    # never landed is completed only while the recorded expected baseline
    # still holds exactly.
    retried = _retry_admitted_publication(
        destination_path,
        captured,
        expected_current,
        confirm_digest,
        retention_required,
        artifact_store,
        retrieval,
    )
    if retried is not None:
        return retried

    review = _review_from_capture(
        captured,
        destination_path,
        expected_current,
        source_registry=source_registry,
        artifact_store=artifact_store,
        retention_required=retention_required,
        retrieval=retrieval,
    )
    if review.review_digest != confirm_digest:
        raise ConfirmationRefused(
            "the confirmation no longer matches the recomputed review: a "
            "review-bound input changed (commit, source references, validator "
            "contract, requested artifacts, destination, or active baseline); "
            "review the current state and confirm the new digest"
        )
    if review.blocking_diagnostics:
        raise GitAuthoringError(
            "the reviewed revision has blocking diagnostics and can never be "
            "admitted: " + "; ".join(review.blocking_diagnostics[:5])
        )
    # Required retention fails closed when it cannot be verified at all —
    # including a missing Source Artifact Store configuration (finding 4).
    if retention_required:
        if artifact_store is None:
            raise PublicationRetentionError(
                "artifact retention is required but no Source Artifact Store is "
                "configured; activation is refused until the exact bound "
                "artifacts can be verified"
            )
        _check_retention(artifact_store, captured.manifest)

    version = captured.revision
    binding_entries = _captured_binding_entries(captured, source_registry)
    derived = _derived_content(captured)
    manifest = build_published_manifest(
        version,
        captured.fingerprint.digest,
        captured.content,
        derived_content=derived,
        revision=captured.revision,
        subtree=captured.subtree,
        source_reference_digest=captured.manifest_digest,
        format_identity=VALIDATOR_CONTRACT_ID,
    )
    sealed = SealedSourceReferences(
        published_version=version,
        revision=captured.revision,
        namespace=captured.manifest.namespace,
        fingerprint=captured.fingerprint.digest,
        manifest_digest=captured.manifest_digest,
        sources=dict(captured.manifest.sources),
        bindings={k: dict(v) for k, v in captured.manifest.bindings.items()},
        source_versions=_sealed_source_versions(captured, source_registry),
        created_at=_now(),
    )
    sealed_raw = msgspec.json.encode(sealed)

    with mutation_lock(destination_path):
        location = PublishedFilesystemLocation(destination_path)
        observed = location.read_pointer()
        _check_pointer_expectation(observed, expected_current, version)
        _reconcile_active_receipt(destination_path, observed)
        version_dir = published_version_path(destination_path, version)
        receipt_path = _receipt_path(destination_path, version)
        locked_retry = _retry_admitted_publication(
            destination_path,
            captured,
            expected_current,
            confirm_digest,
            retention_required,
            artifact_store,
            retrieval,
        )
        if locked_retry is not None:
            return locked_retry
        if version_dir.exists():
            complete = (version_dir / "manifest.json").exists()
            if not complete:
                raise GitAuthoringError(
                    f"cannot publish {version!r}: an incomplete version directory "
                    f"already exists at {version_dir} (residue of an interrupted "
                    f"build); remove it explicitly before retrying"
                )
            _verify_existing_version(location, version, captured, retrieval)
        else:
            _write_version_directory(
                version_dir,
                captured.content,
                derived,
                manifest,
                captured=captured,
                index_builder=index_builder if retrieval == "lancedb" else None,
            )
        # Verify canonical and index inventories before anything private.
        version_manifest = location.read_manifest(version)
        _verify_local_version_files(version_dir, version, version_manifest)
        PublishedFilesystemLocation(destination_path, version=version).resolve()
        # Seal the private source references (even with raw retention
        # disabled) before activation, in private operational storage and —
        # when configured — the Source Artifact Store.
        sealed_dir = _sealed_dir(destination_path)
        sealed_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(_sealed_path(destination_path, version), sealed_raw)
        _verify_written(_sealed_path(destination_path, version), sealed_raw)
        if artifact_store is not None:
            artifact_store.put_binding_manifest(version, sealed_raw)
        receipt = PublicationReceipt(
            revision=captured.revision,
            version=version,
            subtree=captured.subtree,
            destination=str(destination_path),
            fingerprint=captured.fingerprint.digest,
            manifest_digest=captured.manifest_digest,
            source_references_digest=hashlib.sha256(sealed_raw).hexdigest(),
            review_digest=review.review_digest,
            expected_current=review.expected_current,
            validator_contract=VALIDATOR_CONTRACT_ID,
            retention=review.retention,
            created_at=_now(),
            destination_identity=review.destination_identity,
            requested_artifacts=list(review.requested_artifacts),
            adoption=review.adoption,
        )
        raw_receipt = msgspec.json.encode(receipt)
        _receipts_dir(destination_path).mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(receipt_path, raw_receipt)
        _verify_written(receipt_path, raw_receipt)
        # Retention is checked after the optional index build and immediately before CAS.
        if retention_required:
            _require_retained_coverage(artifact_store, captured.kb.pages, binding_entries)
        # Exactly one expected-current pointer update, atomically.
        atomic_write_bytes(published_pointer_path(destination_path), _pointer_bytes(version))
        activated_receipt = msgspec.structs.replace(receipt, activated=True)
        raw_activated = msgspec.json.encode(activated_receipt)
        atomic_write_bytes(receipt_path, raw_activated)
        return activated_receipt


def _check_retention(
    artifact_store: SourceArtifactStore,
    manifest: SourceReferenceManifest | SealedSourceReferences,
) -> None:
    """Required retention: every bound exact version needs a verified artifact."""
    missing = [
        f"{entity_id}:{source_id}"
        for entity_id, entity_bindings in sorted(manifest.bindings.items())
        for source_id, digest in sorted(entity_bindings.items())
        if not artifact_store.artifact_exists(source_id=source_id, content_hash=digest)
    ]
    if missing:
        raise PublicationRetentionError(
            "artifact retention is required but these bound Source Versions lack "
            "a verified artifact: " + ", ".join(missing)
        )


def _verify_receipt_identity(
    receipt: PublicationReceipt, captured: CapturedRevision, destination: Path
) -> None:
    if (
        receipt.version != captured.revision
        or receipt.revision != captured.revision
        or receipt.subtree != captured.subtree
        or receipt.fingerprint != captured.fingerprint.digest
        or receipt.manifest_digest != captured.manifest_digest
        or receipt.destination != str(destination)
    ):
        raise GitAuthoringError(
            f"the stored admission receipt for {receipt.version!r} does not match "
            f"this publication's identity; an immutable Published Version cannot "
            f"be reinterpreted"
        )


def _baseline_matches(expected: str, observed: str | None) -> bool:
    """Whether the recorded explicit expected baseline still holds exactly."""
    if expected == _EXPECTED_NONE:
        return observed is None
    return observed == expected


def _retry_admitted_publication(
    destination: Path,
    captured: CapturedRevision,
    expected_current: str | None,
    confirm_digest: str,
    retention_required: bool,
    artifact_store: SourceArtifactStore | None,
    retrieval: str,
) -> PublicationReceipt | None:
    """Return the verified receipt of an identical prior attempt, or ``None``.

    A stored admission receipt whose review digest equals this confirmation
    is an already-attempted identical publication (spec 0008 §5): the
    admission-bound policy and validator contract are re-enforced, the
    complete version and sealed private-binding state verified against the
    receipt, required retention re-verified, and only a genuinely
    never-activated receipt may complete against its exact recorded baseline
    (findings 8 and 9). ``None`` means no matching prior attempt exists — the
    ordinary preview/confirm path decides.
    """
    version = captured.revision
    if not _receipt_path(destination, version).exists():
        return None
    receipt = _load_receipt(destination, version)
    if confirm_digest != receipt.review_digest:
        return None
    _verify_receipt_identity(receipt, captured, destination)
    if _normalize_expected(expected_current) != receipt.expected_current:
        raise ConfirmationRefused(
            "the stored admission receipt was bound to a different expected-current "
            "baseline; review the current state and confirm again"
        )
    if receipt.validator_contract != VALIDATOR_CONTRACT_ID:
        raise ConfirmationRefused(
            "the stored admission receipt was bound to a different validator "
            "contract; review the current state and confirm again"
        )
    current_retention = "required" if retention_required else "disabled"
    if receipt.retention != current_retention:
        raise ConfirmationRefused(
            f"the stored admission receipt was bound to a {receipt.retention} "
            f"retention policy but retention is now {current_retention}; the "
            f"changed admission-bound policy requires a new review"
        )
    expected_artifacts = sorted(_derived_content(captured))
    if retrieval == "lancedb":
        expected_artifacts.append("derived/lance")
        expected_artifacts.sort()
    if receipt.requested_artifacts and receipt.requested_artifacts != expected_artifacts:
        raise ConfirmationRefused(
            "the stored admission receipt was bound to different retrieval artifacts"
        )
    if retrieval == "lancedb" and receipt.requested_artifacts != expected_artifacts:
        raise ConfirmationRefused(
            "the stored admission receipt has no version-bound LanceDB artifact"
        )
    _verify_sealed_state(destination, receipt)
    if retention_required:
        _require_retained_coverage(
            artifact_store,
            captured.kb.pages,
            _captured_coverage_entries(captured),
        )
    _manifest, verified_receipt, _sealed = _verify_version_complete(
        destination, version, captured.fingerprint.digest
    )
    if verified_receipt != receipt:
        raise GitAuthoringError(
            f"the verified admission receipt for {version!r} changed during retry"
        )
    before_activation: Callable[[], None] | None = None
    if retention_required:

        def check_retained_coverage() -> None:
            _require_retained_coverage(
                artifact_store,
                captured.kb.pages,
                _captured_coverage_entries(captured),
            )

        before_activation = check_retained_coverage
    return _reconcile_receipt_activation(destination, receipt, before_activation=before_activation)


def _reconcile_active_receipt(destination: Path, version: str | None) -> None:
    """Persist an already-observed activation before a later pointer transition."""
    if version is None:
        return
    receipt_path = _receipt_path(destination, version)
    if not receipt_path.exists():
        return  # legacy Published Versions have no Git-authoring receipt
    receipt = _load_receipt(destination, version)
    if receipt.version != version or receipt.destination != str(destination):
        raise GitAuthoringError(
            f"the active Published Version {version!r} does not match its admission receipt"
        )
    if receipt.activated:
        return
    if PublishedFilesystemLocation(destination).read_pointer() != version:
        raise PublicationConflict(
            f"the active Published Version changed while reconciling {version!r}"
        )
    receipt = msgspec.structs.replace(receipt, activated=True)
    raw = msgspec.json.encode(receipt)
    atomic_write_bytes(receipt_path, raw)
    _verify_written(receipt_path, raw)


def _reconcile_receipt_activation(
    destination: Path,
    receipt: PublicationReceipt,
    *,
    before_activation: Callable[[], None] | None = None,
) -> PublicationReceipt:
    """Complete or truthfully report an attempted publication's activation.

    Retry semantics (spec 0008 §5, findings 8/9): an ALREADY successful
    admission is immutable historical evidence — the receipt is returned as
    recorded and the pointer is never reactivated, even when its original
    baseline version happens to be active again after a later rollback. Only
    a genuinely never-activated receipt is completed, and only while its
    exact recorded expected baseline still holds; the mutable current
    activation state never rewrites the immutable admission fact.
    """
    if receipt.activated:
        return receipt
    with mutation_lock(destination):
        observed = PublishedFilesystemLocation(destination).read_pointer()
        activated = False
        if observed == receipt.version or _baseline_matches(receipt.expected_current, observed):
            if observed != receipt.version:
                if before_activation is not None:
                    before_activation()
                atomic_write_bytes(
                    published_pointer_path(destination), _pointer_bytes(receipt.version)
                )
            activated = True
        if activated:
            receipt = msgspec.structs.replace(receipt, activated=True)
            raw = msgspec.json.encode(receipt)
            atomic_write_bytes(_receipt_path(destination, receipt.version), raw)
            _verify_written(_receipt_path(destination, receipt.version), raw)
        return receipt


def _verify_existing_version(
    location: PublishedFilesystemLocation,
    version: str,
    captured: CapturedRevision,
    retrieval: str,
) -> None:
    """Verify a pre-existing complete version dir matches this publication."""
    manifest = location.read_manifest(version)
    if (
        manifest.fingerprint != captured.fingerprint.digest
        or manifest.revision != captured.revision
        or manifest.subtree != captured.subtree
        or manifest.source_reference_digest != captured.manifest_digest
        or manifest.format_identity != VALIDATOR_CONTRACT_ID
    ):
        raise GitAuthoringError(
            f"cannot publish {version!r}: the existing version directory has "
            "different captured Git identity — immutable versions cannot be overwritten"
        )
    completion_path = f"{LANCE_DERIVED_DIR}/{LANCE_COMPLETION_OBJECT}"
    has_index = any(item.path == completion_path for item in manifest.derived_files)
    if has_index != (retrieval == "lancedb"):
        raise GitAuthoringError(
            f"cannot reuse {version!r}: its requested LanceDB artifacts differ from this review"
        )
    # Verify the version's OWN directory (D3): _verify_local_version_files
    # resolves manifest-relative paths beneath the version dir, not the
    # publication destination root.
    _verify_local_version_files(published_version_path(location.path, version), version, manifest)


def _capture_local_index_files(version_dir: Path) -> list[S3ManifestFile]:
    index_dir = version_dir / LANCE_DERIVED_DIR
    if not index_dir.exists():
        return []
    entries: list[S3ManifestFile] = []
    for path in sorted(index_dir.rglob("*")):
        if path.is_symlink():
            raise GitAuthoringError(f"local LanceDB index contains a symlink: {path}")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        entries.append(
            S3ManifestFile(
                path=path.relative_to(version_dir).as_posix(),
                size=len(raw),
                digest=hashlib.sha256(raw).hexdigest(),
            )
        )
    return entries


def _verify_local_version_files(version_dir: Path, version: str, manifest: Any) -> None:
    for entry in [*manifest.files, *manifest.derived_files]:
        path = version_dir / entry.path
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise GitAuthoringError(
                f"Published Version {version!r} is missing {entry.path!r}"
            ) from exc
        if len(raw) != entry.size or hashlib.sha256(raw).hexdigest() != entry.digest:
            raise GitAuthoringError(
                f"Published Version {version!r} file {entry.path!r} fails its "
                "manifest size/digest verification"
            )
    index_dir = version_dir / LANCE_DERIVED_DIR
    actual_paths: set[str] = set()
    if index_dir.exists():
        for path in index_dir.rglob("*"):
            if path.is_symlink():
                raise GitAuthoringError(
                    f"Published Version {version!r} LanceDB index contains a symlink"
                )
            if path.is_file():
                actual_paths.add(path.relative_to(version_dir).as_posix())
    completion_path = version_dir / LANCE_DERIVED_DIR / LANCE_COMPLETION_OBJECT
    completion_raw = completion_path.read_bytes() if completion_path.is_file() else None
    _verify_lance_index_manifest(manifest, completion_raw, actual_paths)


def _write_version_directory(
    version_dir: Path,
    content: dict[str, bytes],
    derived: dict[str, bytes],
    manifest: Any,
    *,
    captured: CapturedRevision,
    index_builder: IndexBuilder | None,
) -> None:
    """Write canonical files, derived artifacts, and the manifest LAST."""
    version_dir.mkdir(parents=True, exist_ok=False)
    for rel, raw in sorted(content.items()):
        target = version_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for rel, raw in sorted(derived.items()):
        target = version_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    final_derived = dict(derived)
    if index_builder is not None:
        index_dir = version_dir / LANCE_DERIVED_DIR
        completion: RemoteIndexCompletion = index_builder(
            index_dir=index_dir,
            kb=captured.kb,
            pages=captured.kb.pages,
            fingerprint=captured.fingerprint,
        )
        index_files = _capture_local_index_files(version_dir)
        completion = msgspec.structs.replace(completion, objects=index_files)
        completion_raw = _verify_and_encode_completion(
            completion, captured.fingerprint, captured.revision
        )
        completion_rel = f"{LANCE_DERIVED_DIR}/{LANCE_COMPLETION_OBJECT}"
        (version_dir / completion_rel).write_bytes(completion_raw)
        final_derived[completion_rel] = completion_raw
        manifest = build_published_manifest(
            manifest.version,
            manifest.fingerprint,
            content,
            derived_content=final_derived,
            derived_manifest_files=index_files,
            revision=manifest.revision,
            subtree=manifest.subtree,
            source_reference_digest=manifest.source_reference_digest,
            format_identity=manifest.format_identity,
        )

    # The manifest is written last: its presence marks a complete version.
    atomic_write_bytes(version_dir / "manifest.json", msgspec.json.encode(manifest))


# ---------------------------------------------------------------------------
# Local rollback: explicit expected-current activation of a complete version.
# ---------------------------------------------------------------------------


class RollbackReview(msgspec.Struct, frozen=True):
    """The stateless disclosure of one exact historical rollback (spec §5)."""

    validator_contract: str
    destination: str
    destination_identity: str
    version: str
    revision: str
    fingerprint: str
    namespace: str
    source_reference_manifest_digest: str
    sealed_source_references_digest: str
    canonical_files: int
    derived_files: int
    expected_current: str
    observed_current: str | None
    retention: str
    review_digest: str


def _verify_version_complete(
    destination: Path, version: str, expected_fingerprint: str | None = None
) -> tuple[Any, PublicationReceipt, SealedSourceReferences]:
    """Verify one immutable version completely; return (manifest, receipt).

    Shared by rollback review/confirmation and receipt recovery (findings
    8/10): the manifest must decode and name the version, every canonical AND
    derived file must match its manifest size/digest, the Reader seam must
    resolve the pinned version, the admission receipt must exist and agree
    with the manifest fingerprint, and the sealed private record must digest-
    and identity-match that receipt.
    """
    location = PublishedFilesystemLocation(destination)
    manifest = location.read_manifest(version)
    if expected_fingerprint is not None and manifest.fingerprint != expected_fingerprint:
        raise GitAuthoringError(
            f"Published Version {version!r} has fingerprint {manifest.fingerprint!r} "
            f"but {expected_fingerprint!r} was expected"
        )
    version_dir = published_version_path(destination, version)
    _verify_local_version_files(version_dir, version, manifest)
    PublishedFilesystemLocation(destination, version=version).resolve()
    receipt = _load_receipt(destination, version)
    has_lance = any(
        entry.path == f"{LANCE_DERIVED_DIR}/{LANCE_COMPLETION_OBJECT}"
        for entry in manifest.derived_files
    )
    if has_lance != ("derived/lance" in receipt.requested_artifacts):
        raise GitAuthoringError(
            f"the admission receipt for {version!r} disagrees with its requested LanceDB index"
        )
    if (
        receipt.version != version
        or receipt.fingerprint != manifest.fingerprint
        or receipt.revision != manifest.revision
        or receipt.subtree != manifest.subtree
        or receipt.manifest_digest != manifest.source_reference_digest
        or receipt.validator_contract != manifest.format_identity
    ):
        raise GitAuthoringError(
            f"the admission receipt for {version!r} does not agree with its "
            f"published manifest; refusing over inconsistent records"
        )
    sealed = msgspec.json.decode(
        _verify_sealed_state(destination, receipt), type=SealedSourceReferences
    )
    return manifest, receipt, sealed


def _rollback_review(
    destination: Path,
    version: str,
    expected_current: str | None,
    *,
    retention_required: bool,
) -> RollbackReview:
    """Build the rollback review (and its digest) from verified facts only."""
    version = validate_published_version(version)
    manifest, receipt, sealed = _verify_version_complete(destination, version)
    expected = _normalize_expected(expected_current)
    observed = PublishedFilesystemLocation(destination).read_pointer()
    _check_pointer_expectation(observed, expected_current, version)
    review = RollbackReview(
        validator_contract=VALIDATOR_CONTRACT_ID,
        destination=str(destination),
        destination_identity=str(destination),
        version=version,
        revision=receipt.revision,
        fingerprint=manifest.fingerprint,
        namespace=sealed.namespace,
        source_reference_manifest_digest=receipt.manifest_digest,
        sealed_source_references_digest=receipt.source_references_digest,
        canonical_files=len(manifest.files),
        derived_files=len(manifest.derived_files),
        expected_current=expected,
        observed_current=observed,
        retention="required" if retention_required else "disabled",
        review_digest="",
    )
    payload = {
        "validator_contract": review.validator_contract,
        "destination": review.destination,
        "destination_identity": review.destination_identity,
        "version": review.version,
        "revision": review.revision,
        "fingerprint": review.fingerprint,
        "namespace": review.namespace,
        "source_reference_manifest_digest": review.source_reference_manifest_digest,
        "sealed_source_references_digest": review.sealed_source_references_digest,
        "canonical_files": review.canonical_files,
        "derived_files": review.derived_files,
        "expected_current": review.expected_current,
        "retention": review.retention,
    }
    digest = hashlib.sha256(msgspec.json.encode(payload)).hexdigest()
    return msgspec.structs.replace(review, review_digest=digest)


def _s3_rollback_review(
    location: S3Location,
    destination: str,
    version: str,
    expected_current: str | None,
    *,
    retention_required: bool,
    metadata_store: SourceArtifactStore,
    destination_identity: str,
) -> RollbackReview:
    version = validate_published_version(version)
    import lumio_wiki.s3_publish as s3_publish

    manifest = _load_complete_version(
        s3_publish._require_obstore(), location.store, location.prefix, version
    )
    if not manifest.revision or manifest.format_identity != VALIDATOR_CONTRACT_ID:
        raise GitAuthoringError(
            f"S3 Published Version {version!r} has no compatible Git admission; "
            "legacy versions remain readable but are not rollback targets"
        )
    record = _load_s3_publication_record(metadata_store, version, manifest)
    if record is None:
        raise GitAuthoringError(
            f"S3 Published Version {version!r} has no private Git admission record"
        )
    receipt = record.receipt
    try:
        activation_raw = metadata_store.get_activation_receipt(version)
    except ArtifactUnavailable as exc:
        raise GitAuthoringError(
            f"S3 Published Version {version!r} has no evidence of prior Git-admitted activation"
        ) from exc
    try:
        activation = msgspec.json.decode(activation_raw, type=S3ActivationReceipt)
    except msgspec.DecodeError as exc:
        raise GitAuthoringError(f"S3 activation receipt for {version!r} is malformed") from exc
    if (
        activation.version != version
        or activation.review_digest != receipt.review_digest
        or activation.expected_current != receipt.expected_current
    ):
        raise GitAuthoringError(
            f"S3 activation receipt for {version!r} disagrees with its Git admission"
        )
    expected = _normalize_expected(expected_current)
    observed = observe_current_pointer(location.store, location.prefix).version
    _check_pointer_expectation(observed, expected_current, version)
    review = RollbackReview(
        validator_contract=VALIDATOR_CONTRACT_ID,
        destination=destination,
        destination_identity=destination_identity,
        version=version,
        revision=receipt.revision,
        fingerprint=manifest.fingerprint,
        namespace=record.sealed.namespace,
        source_reference_manifest_digest=receipt.manifest_digest,
        sealed_source_references_digest=receipt.source_references_digest,
        canonical_files=len(manifest.files),
        derived_files=len(manifest.derived_files),
        expected_current=expected,
        observed_current=observed,
        retention="required" if retention_required else "disabled",
        review_digest="",
    )
    payload = {
        "validator_contract": review.validator_contract,
        "destination": review.destination,
        "destination_identity": review.destination_identity,
        "version": review.version,
        "revision": review.revision,
        "fingerprint": review.fingerprint,
        "namespace": review.namespace,
        "source_reference_manifest_digest": review.source_reference_manifest_digest,
        "sealed_source_references_digest": review.sealed_source_references_digest,
        "canonical_files": review.canonical_files,
        "derived_files": review.derived_files,
        "expected_current": review.expected_current,
        "retention": review.retention,
    }
    digest = hashlib.sha256(msgspec.json.encode(payload)).hexdigest()
    return msgspec.structs.replace(review, review_digest=digest)


def preview_rollback(
    destination: str | Path,
    version: str,
    expected_current: str | None = None,
    *,
    retention_required: bool = False,
    s3_location: S3Location | None = None,
    metadata_store: SourceArtifactStore | None = None,
    destination_identity: str | None = None,
) -> RollbackReview:
    """Produce the stateless rollback review; mutate nothing (spec §5, F6).

    Rollback is explicit review/confirmation plus expected-current
    activation: the preview verifies the complete target version, its
    admission receipt, and its sealed private provenance, discloses the
    expected/observed baseline, and returns the deterministic review digest
    whose explicit confirmation is the only path that may move the pointer.
    """
    if s3_location is not None:
        target_identity = destination_identity or s3_location.effective_target_identity
        if not target_identity or s3_location.destination_uri is None:
            raise GitAuthoringError(
                "an exact S3 URI and effective destination identity are required"
            )
        if str(destination).rstrip("/") != s3_location.destination_uri.rstrip("/"):
            raise GitAuthoringError("S3 destination URI does not match the selected S3Location")
        private_store = metadata_store or local_publication_metadata_store(target_identity)
        return _s3_rollback_review(
            s3_location,
            str(destination),
            version,
            expected_current,
            retention_required=retention_required,
            metadata_store=private_store,
            destination_identity=target_identity,
        )
    if str(destination).startswith("s3://"):
        raise GitAuthoringError("S3 rollback requires Git admission through an explicit S3Location")
    return _rollback_review(
        Path(destination).resolve(),
        version,
        expected_current,
        retention_required=retention_required,
    )


def rollback_publication(
    destination: str | Path,
    version: str,
    expected_current: str | None = None,
    confirm_digest: str = "",
    *,
    artifact_store: SourceArtifactStore | None = None,
    retention_required: bool = False,
    s3_location: S3Location | None = None,
    metadata_store: SourceArtifactStore | None = None,
    destination_identity: str | None = None,
) -> Any:
    """Confirm the reviewed rollback and expected-current-activate history.

    Spec 0008 §5, findings 6/10: the complete target (manifest, every
    canonical AND derived digest, Reader-seam resolution, receipt, and
    identity-verified sealed bindings) is re-verified before exactly one
    expected-current pointer update. Required retention fails closed —
    including a missing store. The target is never rebuilt or overwritten; a
    stale or unconfirmed rollback leaves the active version unchanged.
    """
    if not confirm_digest:
        raise ConfirmationRefused(
            "rollback requires explicit confirmation of the displayed rollback "
            "review digest (--confirm); merely requesting the review never "
            "activates historical knowledge"
        )
    if s3_location is not None:
        target_identity = destination_identity or s3_location.effective_target_identity
        if not target_identity or s3_location.destination_uri is None:
            raise GitAuthoringError(
                "an exact S3 URI and effective destination identity are required"
            )
        if str(destination).rstrip("/") != s3_location.destination_uri.rstrip("/"):
            raise GitAuthoringError("S3 destination URI does not match the selected S3Location")
        private_store = metadata_store or local_publication_metadata_store(target_identity)
        review = _s3_rollback_review(
            s3_location,
            str(destination),
            version,
            expected_current,
            retention_required=retention_required,
            metadata_store=private_store,
            destination_identity=target_identity,
        )
        if review.review_digest != confirm_digest:
            raise ConfirmationRefused(
                "the rollback confirmation no longer matches the recomputed S3 review"
            )
        if retention_required:
            if artifact_store is None:
                raise PublicationRetentionError(
                    "artifact retention is required but no Source Artifact Store is configured"
                )
            import lumio_wiki.s3_publish as s3_publish

            checked = _load_s3_publication_record(
                private_store,
                review.version,
                _load_complete_version(
                    s3_publish._require_obstore(),
                    s3_location.store,
                    s3_location.prefix,
                    review.version,
                ),
            )
            if checked is None:
                raise GitAuthoringError("S3 rollback admission record disappeared")
            container_uri = s3_location.destination_uri
            if s3_location.prefix:
                container_uri = container_uri[: -(len(s3_location.prefix) + 1)]
            snapshot = S3Location(
                s3_location.store,
                s3_location.prefix,
                version=review.version,
                store_uri=container_uri,
            ).resolve()
            verify_rollback_coverage(
                private_store,
                review.version,
                required=True,
                required_pairs=required_source_pairs(snapshot.pages),
                expected_fingerprint=review.fingerprint,
                source_artifact_store=artifact_store,
            )
        _reconcile_active_s3_activation(s3_location, private_store)
        manifest = _rollback_s3_version(
            s3_location.store,
            s3_location.prefix,
            version=review.version,
            expected_pointer_version=review.expected_current,
        )
        if manifest.version != review.version or manifest.revision != review.revision:
            raise GitAuthoringError("S3 rollback activated a different reviewed version")
        return manifest
    if str(destination).startswith("s3://"):
        raise GitAuthoringError("S3 rollback requires Git admission through an explicit S3Location")
    destination_path = Path(destination).resolve()
    with mutation_lock(destination_path):
        review = _rollback_review(
            destination_path, version, expected_current, retention_required=retention_required
        )
        if review.review_digest != confirm_digest:
            raise ConfirmationRefused(
                "the rollback confirmation no longer matches the recomputed "
                "review (target, baseline, or records changed); review the "
                "current state and confirm the new digest"
            )
        if retention_required:
            if artifact_store is None:
                raise PublicationRetentionError(
                    "artifact retention is required but no Source Artifact Store "
                    "is configured; rollback is refused until the exact bound "
                    "artifacts can be verified"
                )
            _manifest, _receipt, sealed = _verify_version_complete(destination_path, review.version)
            snapshot = PublishedFilesystemLocation(
                destination_path, version=review.version
            ).resolve()
            _require_retained_coverage(
                artifact_store,
                snapshot.pages,
                _coverage_entries(snapshot.pages, sealed.bindings),
            )
        active_version = PublishedFilesystemLocation(destination_path).read_pointer()
        _reconcile_active_receipt(destination_path, active_version)
        atomic_write_bytes(published_pointer_path(destination_path), _pointer_bytes(review.version))
        return PublishedFilesystemLocation(destination_path).read_manifest(review.version)


def _pointer_bytes(version: str) -> bytes:
    from lumio_wiki.s3_location import S3Pointer

    return msgspec.json.encode(S3Pointer(version=version))


# ---------------------------------------------------------------------------
# Managed ingest into an explicitly selected authoring worktree.
# ---------------------------------------------------------------------------


class WorktreeIngestResult(msgspec.Struct, frozen=True):
    """What one managed Git-route ingest wrote into the authoring worktree."""

    page_paths: list[str]
    page_title: str
    entity_id: str
    source_id: str
    content_hash: str
    registration: str
    manifest_path: str


def ingest_into_worktree(
    kb_root: str | Path,
    raw_bytes: bytes,
    content_type: str | None,
    filename: str | None,
    source_id: str,
    authored_markdown: str,
    *,
    source_registry: SourceRegistry,
    artifact_store: SourceArtifactStore | None = None,
    raw_source_path: str | Path | None = None,
    persist_observation=None,
) -> WorktreeIngestResult:
    """Register private provenance and write ordinary files into the worktree.

    The manifest-bearing managed ingest route (spec 0008 §7): the original
    bytes extend the explicitly selected private registry's immutable history
    (append-only, converging on identical bytes), the host-authored Compiled
    Page is written as an ordinary file through the checked destination
    resolution, and the Source Reference Manifest gains the exact
    ``(entity, source, digest)`` binding. Nothing is committed — authors
    invoke Git explicitly — and no proposal files are created. Every check
    worktree-safety and routing checks run before private registration or
    authoring-file writes, so a refused target preserves the author's files;
    a mid-write failure restores them through the mutation backup. The CLI
    supplies ``raw_source_path`` so tracked raw inputs are refused too.

    D6: ``persist_observation(source_id, content_hash)`` — the ONE shared
    native hook for required private observation records (URL/research/
    capture) — runs after the safety preflight and BEFORE the final worktree
    apply, so an unpersistable observation refuses the edit while the
    worktree is still untouched (the immutable registration may remain, as
    private append-only history). Storage failures map to a bounded error.
    """
    from lumio_wiki.ingest import (
        _authored_page_declares_source,
        _extract_page_records,
        _validate_page_routing,
    )
    from lumio_wiki.knowledge_base import load_knowledge_base

    kb_path = Path(kb_root).resolve()
    manifest = _load_authoring_manifest(kb_path)
    if manifest is None:
        raise GitAuthoringError(
            f"no {SOURCE_REFERENCE_MANIFEST_BASENAME} beside the Knowledge Base: "
            "managed Git authoring requires adopting the Source Reference Manifest "
            "first (the legacy proposal route stays selected by its own callers)"
        )
    repo_root, _subtree = resolve_repository(kb_path)
    _refuse_private_selection_inside_tree(
        kb_path, _registry_root(source_registry), _local_store_root(artifact_store)
    )
    _refuse_tracked_private_paths(
        repo_root,
        "raw input/source registry/store",
        Path(raw_source_path) if raw_source_path is not None else None,
        _registry_root(source_registry),
        _local_store_root(artifact_store),
    )
    kb, report = load_knowledge_base(kb_path)
    if not report.is_valid:
        raise GitAuthoringError(
            "the authoring worktree's Knowledge Base does not validate; refusing "
            "to ingest over invalid authored content: " + str(report)
        )
    _authored_page_declares_source(authored_markdown, source_id)
    pages = _extract_page_records(authored_markdown, filename, kb)
    routing_issues = [
        issue for issue in _validate_page_routing(pages, kb) if issue.severity == "error"
    ]
    if routing_issues:
        raise GitAuthoringError(
            "the authored page fails ingest routing validation: "
            + "; ".join(f"{issue.file}: {issue.message}" for issue in routing_issues)
        )
    if len(pages) != 1:
        raise GitAuthoringError(
            "managed Git ingest binds exactly one authored page per source; split "
            f"multi-page documents into separate ingests (got {len(pages)})"
        )
    page = pages[0]
    entity_id = _authored_entity_id(page.markdown)
    if not entity_id:
        raise GitAuthoringError(
            "the authored page carries no Entity ID; managed Git authoring binds "
            "sources to stable Entities (the v2 Entity contract)"
        )
    # F4 (spec 0008 §§2/6): the shared complete page/control/manifest
    # candidate gate. Every newly routed producer (capture/URL/research)
    # lands here, so there is no per-command validator fork: Claims,
    # Evidence anchors, ontology, lifecycle, and dangling references are
    # collected against the fully applied candidate BEFORE any private
    # registration or authoring-file write — an invalid page refuses
    # instead of returning success after writing it.
    from lumio_wiki.publish import validate_candidate_knowledge_base

    candidate_report = validate_candidate_knowledge_base(pages, kb_path)
    if not candidate_report.is_valid:
        raise GitAuthoringError(
            "the authored page candidate failed validation: " + str(candidate_report)
        )
    mutation_paths = [
        relative
        for relative in affected_mutation_paths(pages, kb_path)
        if relative != _CONTROL_BASENAME
    ]
    mutation_paths.append(SOURCE_REFERENCE_MANIFEST_BASENAME)
    _refuse_unsafe_worktree_mutation(
        repo_root,
        kb_path,
        mutation_paths,
        allow_untracked=frozenset({SOURCE_REFERENCE_MANIFEST_BASENAME}),
    )
    # The exact binding digest is computed from the supplied bytes up front
    # (registration converges on the same content-addressed version).
    digest = hashlib.sha256(raw_bytes).hexdigest()
    updated_manifest = upsert_binding(manifest, entity_id, source_id, digest)
    version, registration = source_registry.register_version(
        source_id, raw_bytes, filename=filename, content_type=content_type
    )
    if version.content_hash != digest:
        raise GitAuthoringError(
            "the selected Source Registry recorded a different content hash for "
            f"the {source_id!r} version than the manifest binding; refusing "
            "inconsistent provenance"
        )
    if artifact_store is not None:
        retain_artifact(
            artifact_store,
            source_registry,
            source_id=source_id,
            raw_bytes=raw_bytes,
            content_type=content_type,
            filename=filename,
        )
    # F1: the rewritten manifest is validated against the fully applied
    # candidate view (the new page included) with exact selected-registry
    # resolution, AFTER registration (the new binding resolves to the just
    # recorded version) and BEFORE any authoring-file write — a refused
    # ingest leaves only the convergent immutable history, no page bytes.
    _refuse_manifest_drift(
        updated_manifest,
        _candidate_pages_view(kb, pages),
        "managed ingest",
        registry=source_registry,
    )
    if persist_observation is not None:
        try:
            persist_observation(source_id, version.content_hash)
        except GitAuthoringError:
            raise
        except OSError as exc:
            raise GitAuthoringError(
                "the required private provenance observation for "
                f"{source_id!r} could not be persisted to the selected registry "
                f"before the worktree edit ({exc}); the authoring files were not "
                "written — the immutable registration may remain in private "
                "history and the ingest can be retried"
            ) from exc

    backup = MutationBackup("git-authoring-ingest")
    try:
        for relative in affected_mutation_paths(pages, kb_path):
            backup.capture_path(kb_path, relative)
        backup.capture_path(kb_path, SOURCE_REFERENCE_MANIFEST_BASENAME)
        apply_proposed_pages(pages, kb_path)
        manifest_file = kb_path / SOURCE_REFERENCE_MANIFEST_BASENAME
        atomic_write_bytes(manifest_file, serialize_source_reference_manifest(updated_manifest))
    except BaseException as exc:
        _restore_or_raise(backup, kb_path, exc)
        raise
    backup.cleanup()
    return WorktreeIngestResult(
        page_paths=[page.relative_path],
        page_title=page.title,
        entity_id=entity_id,
        source_id=source_id,
        content_hash=version.content_hash,
        registration=registration,
        manifest_path=str(kb_path / SOURCE_REFERENCE_MANIFEST_BASENAME),
    )


def _authored_entity_id(markdown: str) -> str | None:
    """Extract the authored page's stable Entity ID from its frontmatter."""
    from lumio_wiki.knowledge_base import _parse_frontmatter

    try:
        data, _body, _line = _parse_frontmatter(markdown, Path("authored.md"))
    except Exception:
        return None
    entity_id = data.get("id")
    return str(entity_id) if entity_id else None


# ---------------------------------------------------------------------------
# Native deterministic mutations (G3, spec 0008 §2/§6/§7): every retained
# producer edits ordinary files in the selected authoring worktree. No
# proposal objects, no persisted queues, no implicit Git commit — authors
# review the diff and commit explicitly; publication admits an exact commit.
# ---------------------------------------------------------------------------


class WorktreeMutationResult(msgspec.Struct, frozen=True):
    """What one native authoring mutation edited in the worktree (uncommitted)."""

    written: list[str]
    deleted: list[str]
    affected_titles: list[str]
    diagnostics: list[str]
    manifest_updated: bool


def _load_valid_authoring_kb(kb_path: Path):
    from lumio_wiki.knowledge_base import load_knowledge_base

    kb, report = load_knowledge_base(kb_path)
    if not report.is_valid:
        raise GitAuthoringError(
            "the authoring worktree's Knowledge Base does not validate; refusing "
            "to mutate over invalid authored content: " + str(report)
        )
    return kb


def _refuse_invalid_candidate(report, operation: str) -> None:
    """Refuse an invalid mutation candidate with its specific collected failures."""
    if not report.is_valid:
        raise GitAuthoringError(f"{operation} candidate failed validation: {report}")


def _candidate_page_record(page, existing_markdown: str | None = None):
    """A CompiledPage-like record parsed from one proposed page's markdown.

    ``validate_source_references`` reads only ``.pages`` with ``id``, ``title``,
    ``path``, and ``sources``; the candidate view must carry the PROPOSED
    page's declared identity, not the pre-edit tree's (F1: revised/new
    Entities are part of the fully applied candidate the manifest is
    validated against — only true deletions leave the view).

    D1 (spec 0008 §3.1/§6): for an explicitly compound revision the EFFECTIVE
    page content is the additive provenance merge — computed by the very
    function apply/validation use (``merge_compound_sources``) — so the
    manifest view sees the retained prior Sources together with the incoming
    ones. No parallel source-merge algorithm exists here.
    """
    from types import SimpleNamespace

    from lumio_wiki.knowledge_base import _as_sources as as_sources
    from lumio_wiki.knowledge_base import _parse_frontmatter
    from lumio_wiki.publish import merge_compound_sources

    effective_markdown = page.markdown
    if existing_markdown is not None and getattr(page, "compound_revision", False):
        effective_markdown = merge_compound_sources(page.markdown, existing_markdown)
    try:
        data, _body, _line = _parse_frontmatter(effective_markdown, Path(page.relative_path))
    except Exception as exc:
        raise GitAuthoringError(
            f"cannot parse the proposed page at {page.relative_path!r} for the "
            f"{SOURCE_REFERENCE_MANIFEST_BASENAME} cross-check: {exc}"
        ) from exc
    return SimpleNamespace(
        path=page.relative_path,
        title=page.title,
        id=str(data.get("id") or ""),
        sources=as_sources(data.get("sources")),
        synthetic=bool(data.get("synthetic")),
    )


def _candidate_pages_view(kb, candidate_pages=(), removed_titles=()):
    """The page view of the FULLY APPLIED candidate (F1, spec 0008 §2/§3.1).

    Proposed pages replace same-titled loaded pages (a ``rename_from`` title
    is superseded too); declared removals are excluded as the only true
    deletions; every other loaded page is kept unchanged. Manifest drift is
    judged against this view, never against the pre-edit tree minus the
    changed titles.
    """
    from types import SimpleNamespace

    superseded = {title for title in removed_titles if title}
    existing_by_title = {page.title: page for page in kb.pages if page.path}
    parsed = []
    for page in candidate_pages:
        superseded.add(page.title)
        rename_from = getattr(page, "rename_from", None)
        if rename_from:
            superseded.add(rename_from)
        existing = existing_by_title.get(page.title)
        existing_markdown = None
        if existing is not None:
            try:
                existing_markdown = (Path(kb.root) / existing.path).read_text(encoding="utf-8")
            except OSError:
                existing_markdown = None
        parsed.append(_candidate_page_record(page, existing_markdown=existing_markdown))
    kept = [page for page in kb.pages if page.title not in superseded]
    return SimpleNamespace(pages=[*kept, *parsed])


def _restore_or_raise(backup: MutationBackup, kb_path: Path, cause: BaseException) -> None:
    """Restore the captured state or raise the truthful recovery error (F7).

    Reuses the legacy publish rollback's contract: an incomplete restoration
    must never masquerade as success — the retained backup location and every
    failed path are reported through the existing ``MutationRollbackError``.
    """
    failures = backup.restore_all(kb_path)
    if failures:
        backup_dir = backup.directory
        location = (
            str(backup_dir) if backup_dir is not None else "<no backup directory was created>"
        )
        raise MutationRollbackError(
            "the Git authoring mutation failed and the automatic rollback could "
            "not fully restore the previous worktree state. The pre-mutation "
            f"backup is retained at {location} for manual recovery. Failed "
            f"paths: {'; '.join(failures)}.",
            backup_dir=backup_dir,
            failed_paths=failures,
        ) from cause


def _checked_manifest(manifest: SourceReferenceManifest) -> SourceReferenceManifest:
    """Round-trip a rewritten manifest through the strict v1 parser."""
    parse_source_reference_manifest(serialize_source_reference_manifest(manifest))
    return manifest


def _manifest_without_entities(
    manifest: SourceReferenceManifest, entity_ids: frozenset[str]
) -> SourceReferenceManifest | None:
    """Drop the removed/retired Entities' bindings (their keys would dangle)."""
    if not entity_ids or not any(entity_id in manifest.bindings for entity_id in entity_ids):
        return None
    bindings = {
        entity_id: bindings
        for entity_id, bindings in manifest.bindings.items()
        if entity_id not in entity_ids
    }
    return _checked_manifest(
        SourceReferenceManifest(
            version=manifest.version,
            namespace=manifest.namespace,
            sources=manifest.sources,
            bindings=bindings,
        )
    )


def _load_authoring_manifest(kb_path: Path) -> SourceReferenceManifest | None:
    """Load the Source Reference Manifest with bounded strict errors (D7).

    Spec 0008 §3.1: an unsupported/malformed manifest fails with a
    diagnostic rather than being ignored — at the native owner boundary
    that diagnostic is the bounded ``GitAuthoringError`` the CLI maps to
    its error contract, never an escaping ``SourceReferenceError``.
    """
    try:
        return load_source_reference_manifest(kb_path)
    except SourceReferenceError as exc:
        raise GitAuthoringError(
            f"the {SOURCE_REFERENCE_MANIFEST_BASENAME} beside the Knowledge Base "
            f"is invalid ({exc}); fix the manifest before this operation"
        ) from exc


def refuse_unsafe_private_selection(
    kb_root: str | Path, source_registry, *, raw_source_path: str | Path | None = None
) -> None:
    """The shared private-selection safety preflight for native writers (D4).

    Spec 0008 §3.2: Git-tracked raw inputs/registries and private state
    inside the Knowledge Base subtree are refused BEFORE any private byte
    is written — the same guards managed ingest and reactivation use,
    reused by the native source lifecycle writers
    (register/candidate/dismiss/confirm) instead of reimplemented.
    """
    kb_path = Path(kb_root).resolve()
    repo_root, _subtree = resolve_repository(kb_path)
    registry_root = _registry_root(source_registry)
    _refuse_private_selection_inside_tree(kb_path, registry_root)
    _refuse_tracked_private_paths(
        repo_root,
        "raw input/source registry",
        Path(raw_source_path) if raw_source_path is not None else None,
        registry_root,
    )


def _refuse_manifest_drift(
    manifest: SourceReferenceManifest,
    view,
    operation: str,
    *,
    registry=None,
) -> None:
    """Fail closed when the rewritten manifest disagrees with the candidate pages."""
    issues = validate_source_references(manifest, view, registry=registry)
    if issues:
        details = "; ".join(issues)
        raise GitAuthoringError(
            f"the {operation} would leave the {SOURCE_REFERENCE_MANIFEST_BASENAME} "
            f"inconsistent with the candidate Knowledge Base: {details}"
        )


def _apply_worktree_candidate(
    kb_path: Path,
    candidate_pages: list,
    *,
    removed_titles: list[str] | None = None,
    removed_paths: list[str] | None = None,
    control_file=None,
    manifest_rewrite: SourceReferenceManifest | None = None,
    allow_untracked_manifest: bool = False,
) -> tuple[list[str], list[str]]:
    """Refuse unsafe targets, then apply the checked edits atomically.

    The same destination checks publication uses (path collisions, escapes,
    overwrites) plus the worktree-safety refusals (detached HEAD, unresolved
    conflicts, unrelated uncommitted edits) run BEFORE any byte is written;
    an ordinary failure restores the complete prior state through the
    mutation backup. Nothing is committed.
    """
    repo_root, _subtree = resolve_repository(kb_path)
    mutation_paths = [
        relative
        for relative in affected_mutation_paths(
            candidate_pages, kb_path, removed_titles=removed_titles
        )
        if relative != _CONTROL_BASENAME
    ]
    if control_file is not None:
        mutation_paths.append(_CONTROL_BASENAME)
    allow_untracked = frozenset()
    if manifest_rewrite is not None:
        mutation_paths.append(SOURCE_REFERENCE_MANIFEST_BASENAME)
        if allow_untracked_manifest:
            allow_untracked = frozenset({SOURCE_REFERENCE_MANIFEST_BASENAME})
    _refuse_unsafe_worktree_mutation(
        repo_root, kb_path, mutation_paths, allow_untracked=allow_untracked
    )
    backup = MutationBackup("git-authoring-mutation")
    try:
        for relative in mutation_paths:
            backup.capture_path(kb_path, relative)
        apply_proposed_pages(
            candidate_pages,
            kb_path,
            removed_titles=removed_titles,
            control_file=control_file,
        )
        if manifest_rewrite is not None:
            atomic_write_bytes(
                kb_path / SOURCE_REFERENCE_MANIFEST_BASENAME,
                serialize_source_reference_manifest(manifest_rewrite),
            )
    except BaseException as exc:
        _restore_or_raise(backup, kb_path, exc)
        raise
    backup.cleanup()
    written = sorted({page.relative_path for page in candidate_pages})
    deleted = sorted(set(removed_paths or []))
    return written, deleted


def _mutation_diagnostics(report) -> list[str]:
    """Disclose non-blocking warnings (e.g. ambiguous body-link notes)."""
    return [
        f"{issue.file}: {issue.message}"
        for issue in getattr(report, "issues", [])
        if getattr(issue, "severity", "error") != "error"
    ]


def remove_page_in_worktree(
    kb_root: str | Path, title: str, *, reason: str = ""
) -> WorktreeMutationResult:
    """Remove one Compiled Page and repair its dependents as worktree edits.

    Spec 0008 §2/§6: an explicit, declared removal relative to the current
    tree — dependent Relationships drop, exactly-resolved body links unwrap,
    a stale Hot Index pin drops atomically, and the complete candidate
    (including the Control File and, when present, the Source Reference
    Manifest's bindings for the removed Entity) validates before anything is
    written. Ambiguous destinations are disclosed, never guessed.
    """
    from lumio_wiki.proposal_pipeline import (
        ProposalPipelineError,
        assemble_page_removal_candidate,
    )

    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    try:
        candidate = assemble_page_removal_candidate(kb, title, reason=reason)
    except ProposalPipelineError as exc:
        raise GitAuthoringError(str(exc)) from exc
    _refuse_invalid_candidate(candidate.validation_report, "page removal")
    excluded = frozenset(candidate.removed_titles)
    manifest = _load_authoring_manifest(kb_path)
    manifest_rewrite = None
    if manifest is not None:
        removed_ids = frozenset(page.id for page in kb.pages if page.title in excluded and page.id)
        manifest_rewrite = _manifest_without_entities(manifest, removed_ids)
        _refuse_manifest_drift(
            manifest_rewrite if manifest_rewrite is not None else manifest,
            _candidate_pages_view(kb, candidate.proposed_pages, candidate.removed_titles),
            "page removal",
        )
    written, deleted = _apply_worktree_candidate(
        kb_path,
        candidate.proposed_pages,
        removed_titles=candidate.removed_titles,
        removed_paths=candidate.removed_paths,
        control_file=candidate.control_file,
        manifest_rewrite=manifest_rewrite,
        allow_untracked_manifest=True,
    )
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted({page.title for page in candidate.proposed_pages} | excluded),
        diagnostics=_mutation_diagnostics(candidate.validation_report),
        manifest_updated=manifest_rewrite is not None,
    )


def merge_entities_in_worktree(
    kb_root: str | Path, retired_entity_id: str, surviving_entity_id: str, *, reason: str = ""
) -> WorktreeMutationResult:
    """Merge one Entity into another as ordinary worktree edits.

    Spec 0008 §6: the surviving Entity keeps its stable ID/page and absorbs
    the retired Entity's Claims; Claim objects and exactly-resolved body
    links retarget; the retired ID becomes an ontology redirect; the retired
    page is an explicit Git tree deletion; a stale Hot Index pin and the
    retired Entity's Source Reference Manifest bindings drop atomically with
    the merge. Ambiguous link repair refuses (never guessed).
    """
    from lumio_wiki.proposal_pipeline import (
        ProposalPipelineError,
        assemble_entity_merge_candidate,
    )

    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    try:
        candidate = assemble_entity_merge_candidate(
            kb, retired_entity_id, surviving_entity_id, reason=reason
        )
    except ProposalPipelineError as exc:
        raise GitAuthoringError(str(exc)) from exc
    _refuse_invalid_candidate(candidate.validation_report, "entity merge")
    excluded = frozenset(candidate.removed_titles)
    manifest = _load_authoring_manifest(kb_path)
    manifest_rewrite = None
    if manifest is not None:
        # F3 (spec 0008 §6): a merge transfers the retired Entity's exact
        # bindings to the survivor together with the migrated knowledge; a
        # Page Removal's drop policy does not apply here. Incompatible
        # same-source selected versions refuse — never pick or "latest".
        retired_bindings = dict(manifest.bindings.get(retired_entity_id, {}))
        survivor_bindings = dict(manifest.bindings.get(surviving_entity_id, {}))
        for sid, digest in sorted(retired_bindings.items()):
            existing = survivor_bindings.get(sid)
            if existing is not None and existing != digest:
                raise GitAuthoringError(
                    f"entity merge would migrate retired Entity "
                    f"{retired_entity_id!r}'s binding for source {sid!r} at "
                    f"version {digest} while surviving Entity "
                    f"{surviving_entity_id!r} selects {existing}; resolve the "
                    "conflicting selected versions explicitly before merging "
                    "(spec 0008 §6)"
                )
            survivor_bindings[sid] = digest
        bindings = {
            entity_id: entity_bindings
            for entity_id, entity_bindings in manifest.bindings.items()
            if entity_id != retired_entity_id
        }
        if survivor_bindings:
            bindings[surviving_entity_id] = survivor_bindings
        if retired_bindings:
            manifest_rewrite = _checked_manifest(
                SourceReferenceManifest(
                    version=manifest.version,
                    namespace=manifest.namespace,
                    sources=manifest.sources,
                    bindings=bindings,
                )
            )
        _refuse_manifest_drift(
            manifest_rewrite if manifest_rewrite is not None else manifest,
            _candidate_pages_view(kb, candidate.proposed_pages, candidate.removed_titles),
            "entity merge",
        )
    written, deleted = _apply_worktree_candidate(
        kb_path,
        candidate.proposed_pages,
        removed_titles=candidate.removed_titles,
        removed_paths=candidate.removed_paths,
        control_file=candidate.control_file,
        manifest_rewrite=manifest_rewrite,
        allow_untracked_manifest=True,
    )
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted({page.title for page in candidate.proposed_pages} | excluded),
        diagnostics=_mutation_diagnostics(candidate.validation_report),
        manifest_updated=manifest_rewrite is not None,
    )


def write_pages_into_worktree(
    kb_root: str | Path,
    proposed_pages: list,
    *,
    control_file=None,
    operation: str = "page write",
) -> WorktreeMutationResult:
    """Write proposed Compiled Pages into the worktree as ordinary files.

    The passthrough/graph/OKF/external-import producer (spec 0008 §7):
    destination checks, complete-candidate validation, and a fail-closed
    Source Reference Manifest cross-check precede any byte; a mid-write
    failure restores the prior state. No proposal, no commit. Source
    bindings are added by the managed ingest route, not inferred here.
    """
    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    from lumio_wiki.publish import validate_candidate_knowledge_base

    report = validate_candidate_knowledge_base(proposed_pages, kb_path, control_file=control_file)
    _refuse_invalid_candidate(report, operation)
    manifest = _load_authoring_manifest(kb_path)
    if manifest is not None:
        _refuse_manifest_drift(manifest, _candidate_pages_view(kb, proposed_pages), operation)
    written, deleted = _apply_worktree_candidate(kb_path, proposed_pages, control_file=control_file)
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted({page.title for page in proposed_pages}),
        diagnostics=[],
        manifest_updated=False,
    )


def revise_pages_in_worktree(
    kb_root: str | Path,
    revisions: Sequence[tuple[str, str]],
    *,
    operation: str = "page revision",
) -> WorktreeMutationResult:
    """Revise existing Compiled Pages in place through the checked apply.

    The maintenance/semantic explicit-apply producer (spec 0008 §6): link
    repairs and Dream Cycle findings edit the selected authoring worktree
    as ordinary files — never staged proposals. A Link repair never creates
    an accepted Claim; validation gates the complete candidate first.
    """
    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    page_by_path = {page.path: page for page in kb.pages if page.path}
    proposed = []
    for page_path, markdown in revisions:
        page = page_by_path.get(page_path)
        if page is None:
            raise GitAuthoringError(
                f"{operation} targets {page_path!r}, which is not a Compiled Page "
                "in the selected Knowledge Base"
            )
        from lumio_wiki.ingest import ProposedPage

        proposed.append(ProposedPage(relative_path=page.path, title=page.title, markdown=markdown))
    from lumio_wiki.publish import validate_candidate_knowledge_base

    report = validate_candidate_knowledge_base(proposed, kb_path)
    _refuse_invalid_candidate(report, operation)
    manifest = _load_authoring_manifest(kb_path)
    if manifest is not None:
        _refuse_manifest_drift(manifest, _candidate_pages_view(kb, proposed), operation)
    written, _deleted = _apply_worktree_candidate(kb_path, proposed)
    return WorktreeMutationResult(
        written=written,
        deleted=[],
        affected_titles=sorted({page.title for page in proposed}),
        diagnostics=[],
        manifest_updated=False,
    )


def import_graph_into_worktree(
    kb_root: str | Path, graph_path: str | Path
) -> WorktreeMutationResult:
    """Import stub Compiled Pages from a graph document as worktree edits.

    Spec 0008 §7 disposition for graph exchange: the deterministic stub-page
    and Control-File-extension computation is shared with the legacy staged
    route (:func:`lumio_wiki.graph_exchange.assemble_graph_import`); this
    native producer applies it as ordinary files. Broken edges stay
    disclosed diagnostics; edges never become Claims.
    """
    from lumio_wiki.graph_exchange import GraphImportError, assemble_graph_import

    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    try:
        candidate = assemble_graph_import(graph_path, kb)
    except GraphImportError as exc:
        raise GitAuthoringError(str(exc)) from exc
    _refuse_invalid_candidate(candidate.validation_report, "graph import")
    manifest = _load_authoring_manifest(kb_path)
    if manifest is not None:
        _refuse_manifest_drift(
            manifest, _candidate_pages_view(kb, candidate.proposed_pages), "graph import"
        )
    written, deleted = _apply_worktree_candidate(
        kb_path, candidate.proposed_pages, control_file=candidate.control_file
    )
    diagnostics = [
        f"{diagnostic.path}: {diagnostic.message}" for diagnostic in candidate.diagnostics
    ]
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted({page.title for page in candidate.proposed_pages}),
        diagnostics=diagnostics,
        manifest_updated=False,
    )


def retire_source_in_worktree(
    kb_root: str | Path, source_id: str, *, source_registry=None
) -> WorktreeMutationResult:
    """Retire one managed Knowledge Source through Git lifecycle intent.

    Spec 0008 §3.2/§3.3: retirement intent is reviewed in the Source
    Reference Manifest, never a proposal-keyed pending transition. The page
    impact is computed first and retirement REFUSES to write when any
    declaring page would be left sole-source-lost — leave eligible support,
    review a replacement/reclassification, or remove the page first. F2:
    remaining support is eligible only when it resolves to an exact
    registered Source Version in the explicitly selected private history —
    a declared-but-unregistered digest is not support. A retired source
    keeps its history and drops its supporting bindings in the same atomic
    manifest edit.
    """
    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    manifest = _load_authoring_manifest(kb_path)
    if manifest is None:
        raise GitAuthoringError(
            f"native source retirement requires adopting the "
            f"{SOURCE_REFERENCE_MANIFEST_BASENAME} first (lifecycle intent is "
            "reviewed in Git; the legacy proposal-keyed route stays selected by "
            "its own callers)"
        )
    if source_id not in manifest.sources:
        raise GitAuthoringError(
            f"Knowledge Source {source_id!r} is not declared in the "
            f"{SOURCE_REFERENCE_MANIFEST_BASENAME}; only managed sources carry "
            "Git lifecycle intent"
        )
    if manifest.sources[source_id] == "retired":
        raise GitAuthoringError(f"Knowledge Source {source_id!r} is already retired")
    if source_registry is None:
        raise GitAuthoringError(
            "native source retirement requires the explicitly selected private "
            "Source Registry to verify the remaining exact support (pass "
            "--source-registry <dir> or configure the environment selection)"
        )
    active = {sid for sid, status in manifest.sources.items() if status == "active"}
    impacts: list[tuple[str, str]] = []
    unsupported: list[str] = []
    for page in kb.pages:
        declared = {source.id for source in page.sources if source.id}
        if source_id not in declared:
            continue
        entity_bindings = manifest.bindings.get(page.id or "", {})
        unresolved = sorted(
            sid
            for sid in (declared - {source_id}) & active
            if entity_bindings.get(sid) is None
            or source_registry.find_version(sid, entity_bindings[sid]) is None
        )
        if unresolved:
            impacts.append((page.title, f"unresolved-support({','.join(unresolved)})"))
            unsupported.append(page.title)
        elif (declared - {source_id}) & active:
            impacts.append((page.title, "still-supported"))
        else:
            impacts.append((page.title, "sole-source-lost"))
            unsupported.append(page.title)
    if unsupported:
        detail = "; ".join(f"{title} ({status})" for title, status in sorted(impacts))
        raise GitAuthoringError(
            f"retiring {source_id!r} would leave page(s) without eligible support: "
            f"{', '.join(sorted(unsupported))} [{detail}]. Leave eligible support "
            "(declared, active, and resolved to an exact registered Source "
            "Version), review a replacement or reclassification, or remove the "
            "page first (spec 0008 §3.3)"
        )
    sources = dict(manifest.sources)
    sources[source_id] = "retired"
    bindings = {
        entity_id: {sid: digest for sid, digest in entity_bindings.items() if sid != source_id}
        for entity_id, entity_bindings in manifest.bindings.items()
    }
    bindings = {entity_id: kept for entity_id, kept in bindings.items() if kept}
    updated = _checked_manifest(
        SourceReferenceManifest(
            version=manifest.version,
            namespace=manifest.namespace,
            sources=sources,
            bindings=bindings,
        )
    )
    _refuse_manifest_drift(
        updated,
        _candidate_pages_view(kb),
        "source retirement",
        registry=source_registry,
    )
    written, deleted = _apply_worktree_candidate(
        kb_path, [], manifest_rewrite=updated, allow_untracked_manifest=True
    )
    diagnostics = [
        f"{status}: {title}" for title, status in sorted(impacts, key=lambda item: item[0])
    ]
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted(title for title, _status in impacts),
        diagnostics=diagnostics,
        manifest_updated=True,
    )


def reactivate_source_in_worktree(
    kb_root: str | Path,
    source_id: str,
    raw_bytes: bytes,
    *,
    entity_ids: Sequence[str] = (),
    content_type: str | None = None,
    filename: str | None = None,
    source_registry=None,
    raw_source_path: str | Path | None = None,
) -> WorktreeMutationResult:
    """Reactivate a retired managed Source with new bytes and Git intent.

    Spec 0008 §3.2/§3.3 (r3): the new bytes extend the explicitly selected
    private registry's immutable history; the explicit authoring manifest
    edit flips the source to active AND records exact pins for the Entities
    the operator explicitly selected — nothing is inferred from titles,
    filenames, or the latest version, and there is no implicit rebinding of
    all declaring Entities. Every page still declaring the source must be
    accounted for by exactly one selected stable Entity ID; unknown or
    missing IDs refuse with the computed declaring set. The full safety
    preflight runs BEFORE any private write, and the complete candidate
    (pages, Control File, manifest) validates with other exact support
    resolved in the selected registry. No commit, admission, or publication
    is implied.
    """
    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    manifest = _load_authoring_manifest(kb_path)
    if manifest is None:
        raise GitAuthoringError(
            f"native source reactivation requires adopting the "
            f"{SOURCE_REFERENCE_MANIFEST_BASENAME} first (lifecycle intent is "
            "reviewed in Git; the legacy proposal-keyed route stays selected by "
            "its own callers)"
        )
    if source_id not in manifest.sources:
        raise GitAuthoringError(
            f"Knowledge Source {source_id!r} is not declared in the "
            f"{SOURCE_REFERENCE_MANIFEST_BASENAME}; only managed sources carry "
            "Git lifecycle intent"
        )
    if manifest.sources[source_id] != "retired":
        raise GitAuthoringError(f"Knowledge Source {source_id!r} is not retired")
    if source_registry is None:
        raise GitAuthoringError(
            "native source reactivation requires the explicitly selected private "
            "Source Registry (the new bytes extend its immutable history)"
        )
    selected = [str(entity_id) for entity_id in entity_ids]
    duplicates = sorted({eid for eid in selected if selected.count(eid) > 1})
    declaring: list[tuple[str, str]] = sorted(
        (page.id or "", page.title)
        for page in kb.pages
        if source_id in {source.id for source in page.sources if source.id}
    )
    declaring_ids = {entity_id for entity_id, _title in declaring if entity_id}
    unknown = sorted(eid for eid in selected if eid not in declaring_ids)
    missing = sorted(declaring_ids.difference(selected))
    without_id = [title for entity_id, title in declaring if not entity_id]
    problems: list[str] = []
    if unknown:
        problems.append(
            f"unknown Entity ID(s) that do not declare {source_id!r}: {', '.join(unknown)}"
        )
    if missing:
        problems.append(
            f"still-declaring Entity ID(s) missing from the selection: {', '.join(missing)}"
        )
    if duplicates:
        problems.append(f"duplicate Entity ID(s) in the selection: {', '.join(duplicates)}")
    if without_id:
        problems.append("page(s) declaring the source carry no Entity ID: " + ", ".join(without_id))
    if problems:
        declaring_detail = (
            ", ".join(f"{entity_id} ({title})" for entity_id, title in declaring) or "(none)"
        )
        raise GitAuthoringError(
            "source reactivation requires an exact selection of the Entities "
            f"still declaring {source_id!r}; pages still declaring the source: "
            f"{declaring_detail}. "
            + " ".join(problems)
            + ". Re-select the affected Entities explicitly (never inferred "
            "from titles, filenames, or the latest version) or reclassify "
            "those pages first (spec 0008 §3.3)"
        )
    digest = hashlib.sha256(raw_bytes).hexdigest()
    sources = dict(manifest.sources)
    sources[source_id] = "active"
    bindings = {
        entity_id: dict(entity_bindings) for entity_id, entity_bindings in manifest.bindings.items()
    }
    for entity_id in selected:
        bindings.setdefault(entity_id, {})[source_id] = digest
    updated = _checked_manifest(
        SourceReferenceManifest(
            version=manifest.version,
            namespace=manifest.namespace,
            sources=sources,
            bindings={
                entity_id: entity_bindings
                for entity_id, entity_bindings in bindings.items()
                if entity_bindings
            },
        )
    )
    # F6 (spec 0008 §3.2): the complete safety preflight runs BEFORE any
    # private version/metadata write — a refused authoring mutation must
    # never have already extended the selected private history.
    refuse_unsafe_private_selection(kb_path, source_registry, raw_source_path=raw_source_path)
    repo_root, _subtree = resolve_repository(kb_path)
    _refuse_unsafe_worktree_mutation(
        repo_root,
        kb_path,
        [SOURCE_REFERENCE_MANIFEST_BASENAME],
        allow_untracked=frozenset({SOURCE_REFERENCE_MANIFEST_BASENAME}),
    )
    version, registration = source_registry.register_version(
        source_id, raw_bytes, filename=filename, content_type=content_type
    )
    if version.content_hash != digest:
        raise GitAuthoringError(
            "the selected Source Registry recorded a different content hash for "
            f"the new {source_id!r} version than the pinned digest; refusing to "
            "write inconsistent bindings"
        )
    # The complete-candidate check runs with other exact support resolved in
    # the selected registry AFTER registration (the new pins resolve to the
    # just-recorded version) and BEFORE any authoring-file write.
    _refuse_manifest_drift(
        updated,
        _candidate_pages_view(kb),
        "source reactivation",
        registry=source_registry,
    )
    written, deleted = _apply_worktree_candidate(
        kb_path, [], manifest_rewrite=updated, allow_untracked_manifest=True
    )
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted(title for _entity_id, title in declaring),
        diagnostics=[
            f"registered {source_id} version {digest} ({registration})",
            *(f"pinned {entity_id} -> {source_id} @ {digest}" for entity_id in sorted(selected)),
        ],
        manifest_updated=True,
    )


def rename_page_in_worktree(
    kb_root: str | Path,
    title: str,
    *,
    new_title: str | None = None,
    new_category: str | None = None,
    aliases: Sequence[str] | None = None,
    keep_old_title_alias: bool = False,
) -> WorktreeMutationResult:
    """Rename, recategorize, and/or re-alias one Compiled Page as worktree edits.

    Required G3 completion (spec 0008 §6, ADR-0016): the reviewed title
    rename primitive with optional Content Category move and an explicit
    alias choice; ``keep_old_title_alias`` keeps the old title reachable as
    an explicit ADR-0016 disposition. Stable Entity/Claim IDs, Sources, and
    provenance are preserved; exactly-resolved incoming body links retarget
    on renames AND moves; the moved page's outbound path-resolved links
    keep their pre-move targets; a stale Hot Index pin updates; ambiguous
    link repairs and path/alias collisions refuse; the complete candidate
    (pages, Control File, Source Reference Manifest) validates before
    anything is written.
    """
    from lumio_wiki.proposal_pipeline import (
        ProposalPipelineError,
        assemble_page_rename_candidate,
    )

    kb_path = Path(kb_root).resolve()
    kb = _load_valid_authoring_kb(kb_path)
    try:
        candidate = assemble_page_rename_candidate(
            kb,
            title,
            new_title=new_title,
            new_category=new_category,
            aliases=list(aliases) if aliases is not None else None,
            keep_old_title_alias=keep_old_title_alias,
        )
    except ProposalPipelineError as exc:
        raise GitAuthoringError(str(exc)) from exc
    _refuse_invalid_candidate(candidate.validation_report, "page rename")
    manifest = _load_authoring_manifest(kb_path)
    if manifest is not None:
        _refuse_manifest_drift(
            manifest, _candidate_pages_view(kb, candidate.proposed_pages), "page rename"
        )
    written, deleted = _apply_worktree_candidate(
        kb_path, candidate.proposed_pages, control_file=candidate.control_file
    )
    return WorktreeMutationResult(
        written=written,
        deleted=deleted,
        affected_titles=sorted({page.title for page in candidate.proposed_pages}),
        diagnostics=_mutation_diagnostics(candidate.validation_report),
        manifest_updated=False,
    )
