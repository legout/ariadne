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
    "RollbackReview",
    "WorktreeIngestResult",
    "capture_revision",
    "ingest_into_worktree",
    "preview_publication",
    "preview_rollback",
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
        status = _git(repo_root, "status", "--porcelain", "--", str(kb_path / relative)).decode()
        if relative in allow_untracked and status.startswith("??"):
            continue
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
    candidate: SourceReferenceManifest, entity_id: str, *, exclude: frozenset[str] = frozenset()
) -> int:
    """Count the Entity's eligible active support in the candidate manifest."""
    return sum(
        1
        for source_id in candidate.bindings.get(entity_id, {})
        if source_id not in exclude and candidate.sources.get(source_id) == "active"
    )


def _source_impact(
    candidate: SourceReferenceManifest,
    admitted: SealedSourceReferences | None,
    page_entities: set[str] | None = None,
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
    page_entities = page_entities or set()
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
            elif _eligible_candidate_support(candidate, entity_id, exclude=frozenset({source_id})):
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
    _refuse_tracked_private_paths(
        captured.repo_root,
        "source registry/store",
        _registry_root(source_registry),
        _local_store_root(artifact_store),
    )
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
        # Spec 0008 §2: a branch based on an obsolete admitted revision must
        # be reconciled using Git before ordinary admission — only a descendant
        # of the admitted native revision is an ordinary successor; deliberate
        # historical rollback is the separate rollback operation (finding 2).
        admitted_revision = admitted.revision
        if not _FULL_COMMIT_PATTERN.match(admitted_revision):
            raise GitAuthoringError(
                f"the admitted Published Version {observed!r} does not record a "
                f"native Git revision in its sealed provenance; explicit "
                f"adoption or repair is required before an ordinary successor "
                f"publication"
            )
        merge_base = (
            _git(captured.repo_root, "merge-base", admitted_revision, captured.revision)
            .decode()
            .strip()
        )
        # The admitted commit is the merge base exactly when it is an ancestor
        # of the candidate; divergence therefore requires Git reconciliation.
        if merge_base != admitted_revision:
            raise GitAuthoringError(
                f"the candidate revision {captured.revision} is not a descendant "
                f"of the admitted revision {admitted_revision}: a branch based "
                f"on an obsolete admitted revision must be reconciled using Git "
                f"(merge or rebase) before ordinary admission; deliberate "
                f"historical rollback is the separate rollback operation"
            )
        adoption = f"successor to admitted Published Version {observed!r}"
        # Spec 0008 §3.1: once admitted as managed, a source entry is retained
        # (possibly retired), never silently deleted to evade its support or
        # retirement checks (finding 5).
        disappeared = sorted(set(admitted.sources) - set(manifest.sources))
        if disappeared:
            blocking.append(
                "managed source identit"
                + ("y" if len(disappeared) == 1 else "ies")
                + " disappeared from the Source Reference Manifest: "
                + ", ".join(disappeared)
                + "; once admitted as managed, a source is retained (possibly "
                + "retired) — an explicit reviewed reclassification or Page "
                + "Removal is required"
            )

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
    page_entities = {page.id for page in captured.kb.pages if getattr(page, "id", None)}
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
        source_impact=_source_impact(manifest, admitted, page_entities),
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
    )
    if retried is not None:
        return retried

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
        version_dir = published_version_path(destination_path, version)
        receipt_path = _receipt_path(destination_path, version)
        locked_retry = _retry_admitted_publication(
            destination_path,
            captured,
            expected_current,
            confirm_digest,
            retention_required,
            artifact_store,
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
    _verify_sealed_state(destination, receipt)
    if retention_required:
        if artifact_store is None:
            raise PublicationRetentionError(
                "artifact retention is required but no Source Artifact Store is "
                "configured; recovering the recorded admission is refused until "
                "the exact bound artifacts can be verified"
            )
        _check_retention(artifact_store, captured.manifest)
    _manifest, verified_receipt, _sealed = _verify_version_complete(
        destination, version, captured.fingerprint.digest
    )
    if verified_receipt != receipt:
        raise GitAuthoringError(
            f"the verified admission receipt for {version!r} changed during retry"
        )
    return _reconcile_receipt_activation(destination, receipt)


def _reconcile_receipt_activation(
    destination: Path, receipt: PublicationReceipt
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


class RollbackReview(msgspec.Struct, frozen=True):
    """The stateless disclosure of one exact historical rollback (spec §5)."""

    validator_contract: str
    destination: str
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
                f"manifest size/digest verification"
            )
    PublishedFilesystemLocation(destination, version=version).resolve()
    receipt = _load_receipt(destination, version)
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
) -> RollbackReview:
    """Produce the stateless rollback review; mutate nothing (spec §5, F6).

    Rollback is explicit review/confirmation plus expected-current
    activation: the preview verifies the complete target version, its
    admission receipt, and its sealed private provenance, discloses the
    expected/observed baseline, and returns the deterministic review digest
    whose explicit confirmation is the only path that may move the pointer.
    """
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
            for entity_bindings in sealed.bindings.values():
                for source_id, digest in entity_bindings.items():
                    if not artifact_store.artifact_exists(source_id=source_id, content_hash=digest):
                        raise PublicationRetentionError(
                            f"artifact retention is required but the historical "
                            f"binding {source_id} for {review.version!r} lacks "
                            f"a verified artifact"
                        )
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
