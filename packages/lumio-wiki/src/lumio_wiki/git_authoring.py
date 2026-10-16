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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import msgspec

from lumio_wiki.artifact_store import SourceArtifactStore, retain_artifact
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
from lumio_wiki.mutation import MutationBackup, atomic_write_bytes, mutation_lock
from lumio_wiki.publish import affected_mutation_paths, apply_proposed_pages
from lumio_wiki.s3_location import build_published_manifest
from lumio_wiki.s3_publish import _serialize_graph_bytes, _validate_graph_state
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
    "WorktreeIngestResult",
    "capture_revision",
    "ingest_into_worktree",
    "preview_publication",
    "publish_revision",
    "resolve_full_commit",
    "resolve_repository",
    "rollback_publication",
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
    pathspec = f"{subtree}/" if subtree else ""
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
    review_digest: str


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
    if expected_current is None:
        return "(any)"
    if expected_current == _EXPECTED_NONE:
        return _EXPECTED_NONE
    return validate_published_version(expected_current)


def _check_pointer_expectation(
    observed: str | None, expected_current: str | None, version: str
) -> None:
    """Fail closed when the expected-current baseline cannot be advanced."""
    expected = _normalize_expected(expected_current)
    if expected == "(any)":
        return
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


def _source_impact(
    candidate: SourceReferenceManifest, admitted: SealedSourceReferences | None
) -> list[PublicationSourceImpact]:
    """Compare admitted and candidate source references (spec 0008 §3.3)."""
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
        impact.append(
            PublicationSourceImpact(
                source_id=source_id,
                change="bound" if before is None else "replaced",
                entity_id=entity_id,
                support="newly-supported" if before is None else "replaced-exact-version",
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
            f"{item.source_id}|{item.change}|{item.entity_id}|{item.support}"
            for item in review.source_impact
        ),
        "page_mutations": sorted(review.page_mutations),
        "blocking_diagnostics": sorted(review.blocking_diagnostics),
        "requested_artifacts": sorted(review.requested_artifacts),
        "destination": review.destination,
        "expected_current": review.expected_current,
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
    destination_path = Path(destination).resolve()
    _refuse_private_selection_inside_tree(
        kb_path, _registry_root(source_registry), _local_store_root(artifact_store)
    )
    captured = capture_revision(kb_path, revision)
    review = _review_from_capture(
        captured,
        destination_path,
        expected_current,
        source_registry=source_registry,
        retention_required=retention_required,
    )
    return review


def _local_store_root(artifact_store: SourceArtifactStore | None) -> Path | None:
    root = getattr(artifact_store, "root", None)
    return Path(root).resolve() if root is not None else None


def _review_from_capture(
    captured: CapturedRevision,
    destination: Path,
    expected_current: str | None,
    *,
    source_registry: SourceRegistry | None,
    retention_required: bool,
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
    # Spec 0008 §6: publication (unlike ordinary validation) rejects DANGLING
    # authored internal references in the selected candidate; ambiguous or
    # escaping references stay non-blocking diagnostics that are never
    # guessed repairs.
    blocking.extend(
        f"{issue.file}: {issue.field}: {issue.message}"
        for issue in captured.report.issues
        if issue.severity == "warning"
        and issue.field == "internal-links"
        and issue.message.startswith("broken internal link")
    )
    registry_consulted = source_registry is not None
    if manifest.bindings and source_registry is None:
        blocking.append(
            "the revision carries managed source bindings but no private source "
            "registry is selected; select the shared registry explicitly"
        )
    blocking.extend(validate_source_references(manifest, captured.kb, registry=source_registry))

    location = PublishedFilesystemLocation(destination)
    observed = location.read_pointer()
    expected = _normalize_expected(expected_current)
    _check_pointer_expectation(observed, expected_current, captured.revision)

    admitted: SealedSourceReferences | None = None
    active_manifest: Any = None
    adoption: str
    if observed is None:
        adoption = (
            "first Git publication at this destination: no prior admitted Published "
            "Version ancestry exists here"
        )
    else:
        active_manifest = location.read_manifest(observed)
        admitted = _load_sealed(destination, observed)
        if admitted.namespace != manifest.namespace:
            raise GitAuthoringError(
                f"an admitted namespace cannot change in an ordinary successor "
                f"publication: destination admits {admitted.namespace!r}, the "
                f"candidate declares {manifest.namespace!r}"
            )
        adoption = f"successor to admitted Published Version {observed!r}"

    derived = _derived_content(captured)
    source_refs = [
        f"{source_id}:{status}" for source_id, status in sorted(manifest.sources.items())
    ]
    bindings = [
        f"{entity_id} -> {source_id}:{digest}"
        for entity_id, entity_bindings in sorted(manifest.bindings.items())
        for source_id, digest in sorted(entity_bindings.items())
    ]
    public_only = sorted(
        {
            source.id
            for page in captured.kb.pages
            for source in page.sources
            if source.id and source.id not in manifest.sources
        }
    )
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
        source_impact=_source_impact(manifest, admitted),
        page_mutations=_page_mutations(captured.content, active_manifest),
        blocking_diagnostics=sorted(blocking),
        public_only_sources=public_only,
        requested_artifacts=sorted(derived),
        destination=str(destination),
        expected_current=expected,
        observed_current=observed,
        adoption=adoption,
        retention="required" if retention_required else "disabled",
        registry_consulted=registry_consulted,
        review_digest="",
    )
    digest = hashlib.sha256(_review_digest_payload(review)).hexdigest()
    return msgspec.structs.replace(review, review_digest=digest)


# ---------------------------------------------------------------------------
# Explicit confirmation, immutable versions, expected-current activation.
# ---------------------------------------------------------------------------


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
    kb_path = Path(kb_root).resolve()
    destination_path = Path(destination).resolve()
    _refuse_private_selection_inside_tree(
        kb_path, _registry_root(source_registry), _local_store_root(artifact_store)
    )
    captured = capture_revision(kb_path, revision)
    version = captured.revision

    # Idempotent fast path (spec 0008 §5): retrying an ALREADY attempted
    # identical publication — the admission receipt for this exact version
    # exists and the confirmation still matches its review digest — returns
    # the existing verified receipt. Immutable version bytes are never
    # rewritten, an advanced pointer is never reactivated, and a receipt
    # whose activation never landed is completed only while the recorded
    # expected baseline still holds exactly.
    receipt_path = _receipt_path(destination_path, version)
    if receipt_path.exists():
        existing = _load_receipt(destination_path, version)
        if confirm_digest == existing.review_digest:
            _verify_receipt_identity(existing, captured, destination_path)
            _verify_existing_version(
                PublishedFilesystemLocation(destination_path), version, captured
            )
            return _reconcile_receipt_activation(destination_path, existing)

    review = _review_from_capture(
        captured,
        destination_path,
        expected_current,
        source_registry=source_registry,
        retention_required=retention_required,
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
    if retention_required and artifact_store is not None:
        _check_retention(artifact_store, captured.manifest)

    version = captured.revision
    derived = _derived_content(captured)
    manifest = build_published_manifest(
        version,
        captured.fingerprint.digest,
        captured.content,
        derived_content=derived,
    )
    sealed = SealedSourceReferences(
        published_version=version,
        revision=captured.revision,
        namespace=captured.manifest.namespace,
        fingerprint=captured.fingerprint.digest,
        manifest_digest=captured.manifest_digest,
        sources=dict(captured.manifest.sources),
        bindings={k: dict(v) for k, v in captured.manifest.bindings.items()},
        created_at=_now(),
    )
    sealed_raw = msgspec.json.encode(sealed)

    with mutation_lock(destination_path):
        location = PublishedFilesystemLocation(destination_path)
        observed = location.read_pointer()
        _check_pointer_expectation(observed, expected_current, version)
        version_dir = published_version_path(destination_path, version)
        receipt_path = _receipt_path(destination_path, version)
        if receipt_path.exists():
            # An identical, already-attempted publication reached the locked
            # section first: never rewrite immutable version bytes.
            receipt = _load_receipt(destination_path, version)
            _verify_receipt_identity(receipt, captured, destination_path)
            _verify_existing_version(location, version, captured)
            return _reconcile_receipt_activation(destination_path, receipt)
        if version_dir.exists():
            complete = (version_dir / "manifest.json").exists()
            if not complete:
                raise GitAuthoringError(
                    f"cannot publish {version!r}: an incomplete version directory "
                    f"already exists at {version_dir} (residue of an interrupted "
                    f"build); remove it explicitly before retrying"
                )
            _verify_existing_version(location, version, captured)
        else:
            _write_version_directory(version_dir, captured.content, derived, manifest)
        # Verify completeness through the Reader seam before anything private.
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
        )
        raw_receipt = msgspec.json.encode(receipt)
        _receipts_dir(destination_path).mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(receipt_path, raw_receipt)
        _verify_written(receipt_path, raw_receipt)
        # Exactly one expected-current pointer update, atomically.
        atomic_write_bytes(published_pointer_path(destination_path), _pointer_bytes(version))
        activated_receipt = msgspec.structs.replace(receipt, activated=True)
        raw_activated = msgspec.json.encode(activated_receipt)
        atomic_write_bytes(receipt_path, raw_activated)
        return activated_receipt


def _check_retention(
    artifact_store: SourceArtifactStore, manifest: SourceReferenceManifest
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
        receipt.revision != captured.revision
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
    """Whether the recorded expected baseline still holds exactly.

    "(any)" never matches: completing an activation without an explicit
    baseline could reactivate an old version over an advanced pointer.
    """
    if expected == _EXPECTED_NONE:
        return observed is None
    return expected != "(any)" and observed == expected


def _reconcile_receipt_activation(
    destination: Path, receipt: PublicationReceipt
) -> PublicationReceipt:
    """Complete or truthfully report an attempted publication's activation.

    Retry semantics (spec 0008 §5): resolve the actual pointer and complete
    the receipt. When the confirmed activation never landed and the recorded
    expected baseline still holds exactly, the activation is completed now;
    when the pointer already names this version the receipt is marked
    activated; when another publication advanced the pointer, the receipt is
    returned unactivated and the pointer is never rewrittEN.
    """
    with mutation_lock(destination):
        observed = PublishedFilesystemLocation(destination).read_pointer()
        if observed == receipt.version:
            activated = True
        elif _baseline_matches(receipt.expected_current, observed):
            atomic_write_bytes(published_pointer_path(destination), _pointer_bytes(receipt.version))
            activated = True
        else:
            activated = False
        if receipt.activated != activated:
            receipt = msgspec.structs.replace(receipt, activated=activated)
            raw = msgspec.json.encode(receipt)
            atomic_write_bytes(_receipt_path(destination, receipt.version), raw)
            _verify_written(_receipt_path(destination, receipt.version), raw)
        return receipt


def _verify_existing_version(
    location: PublishedFilesystemLocation, version: str, captured: CapturedRevision
) -> None:
    """Verify a pre-existing complete version dir matches this publication."""
    manifest = location.read_manifest(version)
    if manifest.fingerprint != captured.fingerprint.digest:
        raise GitAuthoringError(
            f"cannot publish {version!r}: the existing version directory has a "
            f"different canonical fingerprint — immutable versions cannot be "
            f"overwritten"
        )
    location.materialize(version, manifest)


def _write_version_directory(
    version_dir: Path,
    content: dict[str, bytes],
    derived: dict[str, bytes],
    manifest: Any,
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
    # The manifest is written last: its presence marks a complete version.
    atomic_write_bytes(version_dir / "manifest.json", msgspec.json.encode(manifest))


# ---------------------------------------------------------------------------
# Local rollback: explicit expected-current activation of a complete version.
# ---------------------------------------------------------------------------


def rollback_publication(
    destination: str | Path,
    version: str,
    expected_current: str | None = None,
    *,
    artifact_store: SourceArtifactStore | None = None,
    retention_required: bool = False,
) -> Any:
    """CAS-activate an already complete immutable local Published Version.

    Rollback is explicit review plus expected-current activation: the target
    version is verified complete (manifest, every canonical AND derived
    digest, and resolution through the Reader seam) and its historical sealed
    source bindings are verified under the configured retention policy. The
    target is never rebuilt or overwritten; a stale rollback fails closed and
    leaves the active version unchanged (spec 0008 §5).
    """
    destination_path = Path(destination).resolve()
    version = validate_published_version(version)
    with mutation_lock(destination_path):
        location = PublishedFilesystemLocation(destination_path)
        observed = location.read_pointer()
        _check_pointer_expectation(observed, expected_current, version)
        manifest = location.read_manifest(version)
        version_dir = published_version_path(destination_path, version)
        for entry in [*manifest.files, *manifest.derived_files]:
            path = version_dir / entry.path
            try:
                raw = path.read_bytes()
            except FileNotFoundError as exc:
                raise GitAuthoringError(
                    f"cannot roll back to {version!r}: {entry.path!r} is missing"
                ) from exc
            if len(raw) != entry.size or hashlib.sha256(raw).hexdigest() != entry.digest:
                raise GitAuthoringError(
                    f"cannot roll back to {version!r}: {entry.path!r} fails its "
                    f"manifest size/digest verification"
                )
        PublishedFilesystemLocation(destination_path, version=version).resolve()
        sealed = _load_sealed(destination_path, version)
        if retention_required and artifact_store is not None:
            for entity_bindings in sealed.bindings.values():
                for source_id, digest in entity_bindings.items():
                    if not artifact_store.artifact_exists(source_id=source_id, content_hash=digest):
                        raise PublicationRetentionError(
                            f"artifact retention is required but the historical "
                            f"binding {source_id} for {version!r} lacks a verified "
                            f"artifact"
                        )
        atomic_write_bytes(published_pointer_path(destination_path), _pointer_bytes(version))
        return manifest


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
) -> WorktreeIngestResult:
    """Register private provenance and write ordinary files into the worktree.

    The manifest-bearing managed ingest route (spec 0008 §7): the original
    bytes extend the explicitly selected private registry's immutable history
    (append-only, converging on identical bytes), the host-authored Compiled
    Page is written as an ordinary file through the checked destination
    resolution, and the Source Reference Manifest gains the exact
    ``(entity, source, digest)`` binding. Nothing is committed — authors
    invoke Git explicitly — and no proposal files are created. Every check
    runs before the first byte is written, so a refused ingest preserves the
    author's files exactly; a mid-write failure restores them through the
    mutation backup.
    """
    from lumio_wiki.ingest import (
        _authored_page_declares_source,
        _extract_page_records,
        _validate_page_routing,
    )
    from lumio_wiki.knowledge_base import load_knowledge_base

    kb_path = Path(kb_root).resolve()
    manifest = load_source_reference_manifest(kb_path)
    if manifest is None:
        raise GitAuthoringError(
            f"no {SOURCE_REFERENCE_MANIFEST_BASENAME} beside the Knowledge Base: "
            "managed Git authoring requires adopting the Source Reference Manifest "
            "first (the legacy proposal route stays selected by its own callers)"
        )
    _refuse_private_selection_inside_tree(
        kb_path, _registry_root(source_registry), _local_store_root(artifact_store)
    )
    kb, report = load_knowledge_base(kb_path)
    if not report.is_valid:
        raise GitAuthoringError(
            "the authoring worktree's Knowledge Base does not validate; refusing "
            "to ingest over invalid authored content: " + str(report)
        )
    _authored_page_declares_source(authored_markdown, source_id)
    version, registration = source_registry.register_version(
        source_id, raw_bytes, filename=filename, content_type=content_type
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
    updated_manifest = upsert_binding(manifest, entity_id, source_id, version.content_hash)

    backup = MutationBackup("git-authoring-ingest")
    try:
        for relative in affected_mutation_paths(pages, kb_path):
            backup.capture_path(kb_path, relative)
        backup.capture_path(kb_path, SOURCE_REFERENCE_MANIFEST_BASENAME)
        apply_proposed_pages(pages, kb_path)
        manifest_file = kb_path / SOURCE_REFERENCE_MANIFEST_BASENAME
        atomic_write_bytes(manifest_file, serialize_source_reference_manifest(updated_manifest))
    except BaseException:
        backup.restore_all(kb_path)
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
