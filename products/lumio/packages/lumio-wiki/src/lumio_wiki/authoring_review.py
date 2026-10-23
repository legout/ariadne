"""Readable review of one staged authoring candidate and exact-commit checks.

Spec 0010 §4 (plan 0010 J2): :func:`review_authoring_candidate` inspects the
STAGED candidate against one explicit full base commit and returns stateless
evidence — never a persisted proposal, never a human-approval claim.
:func:`review_knowledge_changes` returns the same Knowledge-Base-scoped facts
for Core composition; it discloses changes outside the selected subtree but
can never authorize whole-repository submission. The standalone wrapper
refuses any submitted change outside the selected Knowledge Base.
:func:`check_authoring_commit` verifies the WHOLE resulting commit against
the reviewed base/candidate; only the exact reviewed candidate passes.

All body and semantic facts derive from immutable captured Git bytes: the
base side is captured through :func:`lumio_wiki.git_authoring.capture_revision`,
and the candidate side is captured from one immutable tree identity. When no
``candidate_tree`` is supplied, the staged tree is materialized in PRIVATE
TEMPORARY storage only — a byte copy of the selected index plus temporary
object storage with the repository objects as read-only alternates — so the
user's index, worktree and repository object database are never touched and
no commit is created. Unstaged and untracked work is disclosed as excluded
paths (no bytes), never mixed into the reviewed snapshot. Reports carry no
private original bytes, credentials or absolute private paths; the review
digest binds every reported fact, and the report round-trips through JSON
for :func:`check_authoring_commit`.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import msgspec

from lumio_wiki.git_authoring import (
    _CONTROL_BASENAME,
    _TRACKED_PRIVATE_PREFIX,
    CapturedRevision,
    GitAuthoringError,
    capture_revision,
    resolve_full_commit,
    resolve_repository,
)
from lumio_wiki.ingest import ClaimChange, compute_claim_changes
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    parse_source_reference_manifest,
)

__all__ = [
    "AUTHORING_REVIEW_SCHEMA_VERSION",
    "AUTHORING_REVIEW_VALIDATOR_CONTRACT",
    "AuthoringReview",
    "AuthoringReviewError",
    "CommitCheck",
    "KnowledgeChangeReview",
    "OntologyReviewChange",
    "PageReviewChange",
    "PathIdentity",
    "SemanticFieldChange",
    "check_authoring_commit",
    "load_authoring_review_report",
    "review_authoring_candidate",
    "review_knowledge_changes",
]

#: Identifies the validator/format contract bound into every review digest.
AUTHORING_REVIEW_VALIDATOR_CONTRACT = "lumio-wiki/authoring-review/1"

AUTHORING_REVIEW_SCHEMA_VERSION = 1

_MISSING_OID = "0" * 40

#: One exact immutable tree identity: 40 lowercase hex characters, never a
#: movable rev expression (F6).
_FULL_TREE_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class AuthoringReviewError(Exception):
    """One bounded review/check refusal with a stable machine ``code``."""

    def __init__(self, message: str, *, code: str = "authoring_review_error") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Read-only Git plumbing (private temporary storage for staged capture).
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    """Run one read-only Git command, optionally with a subprocess-local env."""
    command = ["git", "--no-optional-locks", "-C", str(repo_root), *args]
    run_env = None
    if env is not None:
        run_env = {**os.environ, **env}
    try:
        result = subprocess.run(command, capture_output=True, check=False, env=run_env)
    except FileNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise AuthoringReviewError(
            "the Git executable is required for authoring review but was not found"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise AuthoringReviewError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


@contextmanager
def _private_object_store(repo_root: Path) -> Iterator[dict[str, str]]:
    """A private index copy plus temporary object storage over read-only repo objects.

    The selected index (honoring ``GIT_INDEX_FILE``) is byte-copied and tree
    objects are prepared ONLY in the temporary directory, with the actual
    worktree object store as a read-only alternate. Nothing writes the user's
    index or the repository object database, and the temporary state vanishes
    on exit — captured identities and bytes survive without it.
    """
    lines = (
        _git(repo_root, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
        .decode()
        .strip()
        .splitlines()
    )
    if len(lines) != 2:  # pragma: no cover - rev-parse contract
        raise AuthoringReviewError("could not resolve the repository's Git directories")
    git_dir, common_dir = (Path(line.strip()) for line in lines)
    objects_dir = common_dir / "objects"
    selected_index = Path(os.environ.get("GIT_INDEX_FILE") or (git_dir / "index"))
    if not selected_index.is_file():
        raise AuthoringReviewError(
            "the selected Git index does not exist; stage the intended candidate "
            "paths with native Git before review",
            code="staged_tree_unavailable",
        )
    alternates = [str(objects_dir)]
    existing = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
    if existing:
        alternates.append(existing)
    with tempfile.TemporaryDirectory(prefix="lumio-authoring-review-") as tmp:
        tmp_objects = Path(tmp) / "objects"
        tmp_objects.mkdir()
        tmp_index = Path(tmp) / "index"
        shutil.copyfile(selected_index, tmp_index)
        yield {
            "GIT_INDEX_FILE": str(tmp_index),
            "GIT_OBJECT_DIRECTORY": str(tmp_objects),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.pathsep.join(alternates),
        }


def _staged_tree(repo_root: Path, env: dict[str, str]) -> str:
    """The complete submitted tree identity of the staged index."""
    return _git(repo_root, "write-tree", env=env).decode().strip()


def _tree_diff(
    repo_root: Path, base_tree: str, new_tree: str, *, env: dict[str, str] | None = None
) -> list[tuple[str, str, str | None, str | None]]:
    """``(status, repo_relative_path, base_blob, new_blob)`` for every changed path.

    ``base_blob``/``new_blob`` are ``None`` on the missing side of an
    addition/removal. Repository-wide: callers scope the result.
    """
    raw = _git(
        repo_root,
        "diff-tree",
        "-r",
        "--raw",
        "-z",
        "--no-renames",
        base_tree,
        new_tree,
        env=env,
    )
    entries: list[tuple[str, str, str | None, str | None]] = []
    records = raw.split(b"\0")
    index = 0
    while index < len(records):
        meta = records[index]
        if not meta:
            index += 1
            continue
        path = records[index + 1].decode("utf-8")
        parts = meta.decode("utf-8").split(" ")
        # :oldmode newmode oldoid newoid status
        status = parts[-1]
        old_oid = parts[-3]
        new_oid = parts[-2]
        entries.append(
            (
                status,
                path,
                None if old_oid == _MISSING_OID else old_oid,
                None if new_oid == _MISSING_OID else new_oid,
            )
        )
        index += 2
    return sorted(entries, key=lambda entry: entry[1])


def _capture_tree_files(
    repo_root: Path, tree: str, subtree: str, *, env: dict[str, str] | None = None
) -> tuple[dict[str, bytes], bytes]:
    """Capture one tree's canonical Knowledge Base bytes (immutable view).

    Mirrors :func:`lumio_wiki.git_authoring.capture_revision`'s canonical-file
    rules for a tree identity: only regular ``.md``/``lumio.yaml``/manifest
    blobs are captured, a tracked private ingest store is refused, and the
    Source Reference Manifest must be present.
    """
    prefix = f"{subtree}/" if subtree else ""
    raw_entries = _git(
        repo_root,
        "ls-tree",
        "-r",
        "-z",
        tree,
        "--",
        prefix or ".",
        env=env,
    )
    files: dict[str, bytes] = {}
    manifest_raw: bytes | None = None
    for record in raw_entries.split(b"\0"):
        if not record:
            continue
        try:
            meta, path_bytes = record.split(b"\t", 1)
            mode, object_type, oid = meta.decode().split(" ")
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuthoringReviewError(f"could not parse Git tree entry: {exc}") from exc
        if subtree and not path.startswith(prefix):
            continue
        rel = path[len(prefix) :]
        if rel.startswith(_TRACKED_PRIVATE_PREFIX):
            raise AuthoringReviewError(
                f"the private ingest store '{_TRACKED_PRIVATE_PREFIX}' is Git-tracked "
                f"in the submitted candidate; raw/registry paths must stay out of Git"
            )
        is_canonical = rel.lower().endswith(".md") or rel == _CONTROL_BASENAME
        if not is_canonical and rel != SOURCE_REFERENCE_MANIFEST_BASENAME:
            continue
        if mode != "100644" or object_type != "blob":
            raise AuthoringReviewError(
                f"'{rel}' in the submitted candidate is not a regular file "
                f"(mode {mode}, {object_type}); symlinks and submodules are never "
                f"reviewed as Knowledge Base content"
            )
        blob = _git(repo_root, "cat-file", "blob", oid, env=env)
        if rel == SOURCE_REFERENCE_MANIFEST_BASENAME:
            manifest_raw = blob
        else:
            files[rel] = blob
    if manifest_raw is None:
        raise AuthoringReviewError(
            f"the submitted candidate carries no {SOURCE_REFERENCE_MANIFEST_BASENAME}; "
            "adopt Git authoring before requesting a review"
        )
    return files, manifest_raw


def _captured_tree_revision(
    kb_root: Path, repo_root: Path, subtree: str, tree: str, *, env: dict[str, str] | None = None
) -> CapturedRevision:
    files, manifest_raw = _capture_tree_files(repo_root, tree, subtree, env=env)
    try:
        return CapturedRevision(
            repo_root=repo_root,
            kb_root=kb_root,
            revision=tree,
            subtree=subtree,
            files=files,
            manifest_raw=manifest_raw,
        )
    except GitAuthoringError as exc:
        raise AuthoringReviewError(str(exc)) from exc


def _head_revision(repo_root: Path) -> str:
    head = _git(repo_root, "rev-parse", "HEAD").decode().strip()
    return resolve_full_commit(repo_root, head)


def _excluded_work(repo_root: Path) -> tuple[list[str], list[str]]:
    """Repository-relative unstaged and untracked paths (no bytes).

    Excluded work is worktree state that did NOT enter the submission: any
    tracked path whose worktree bytes differ from the index, plus untracked
    files. Ignored files are not disclosed changes.
    """
    raw = _git(repo_root, "status", "--porcelain", "-z")
    unstaged: list[str] = []
    untracked: list[str] = []
    records = raw.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        status = record[:2].decode("utf-8", "replace")
        path = record[3:].decode("utf-8", "replace")
        index += 1
        if status[0] in {"R", "C"}:
            index += 1  # the original path follows rename/copy entries
        if status == "??":
            untracked.append(path)
        elif status.startswith("!"):
            continue
        elif status[1] != " ":
            unstaged.append(path)
    return sorted(set(unstaged)), sorted(set(untracked))


# ---------------------------------------------------------------------------
# Review records.
# ---------------------------------------------------------------------------


class PathIdentity(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """One changed Knowledge Base path and its exact base/candidate blobs."""

    path: str
    change: str  # added | updated | removed
    base_blob: str | None
    candidate_blob: str | None


class SemanticFieldChange(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """One readable before/after semantic value a human must inspect (F3).

    ``field`` names the changed semantic fact (for example ``summary``,
    ``source.url:<id>``, ``claim.confidence:<claim id>``); ``before``/``after``
    are readable renderings (``none`` for absent), never raw YAML.
    """

    field: str
    before: str
    after: str


class PageReviewChange(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """One page's readable body change plus its structured semantics.

    ``body_diff`` is a unified Markdown-body diff (YAML frontmatter is hidden
    from the ordinary review); ``frontmatter_only`` marks a file whose body is
    unchanged while its frontmatter semantics (Claims, lifecycle, visibility,
    Entity types, source support) changed.
    """

    path: str
    title: str | None
    change: str  # added | updated | removed
    body_changed: bool
    frontmatter_only: bool
    body_diff: str
    lifecycle: str = ""
    visibility: str = ""
    entity_types: list[str] = msgspec.field(default_factory=list)
    sources: list[str] = msgspec.field(default_factory=list)
    claims: list[ClaimChange] = msgspec.field(default_factory=list)
    semantic_changes: list[SemanticFieldChange] = msgspec.field(default_factory=list)


class OntologyReviewChange(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """One parsed-semantic ontology edit in the Control File.

    ``before``/``after`` carry readable old/new definitions (domain, range,
    literal kind, description) so a changed predicate never collapses into a
    generic "differs" marker.
    """

    change: str
    name: str
    detail: str = ""
    before: str = ""
    after: str = ""


class KnowledgeChangeReview(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """The Knowledge-Base-scoped review facts for Core composition.

    Scoped evidence only: ``changes_outside_kb`` is a disclosure of submitted
    paths outside the selected subtree — this result can never authorize a
    whole-repository submission, and the standalone wrapper refuses them.
    """

    schema_version: int
    validator_contract: str
    namespace: str
    kb_subtree: str
    base_revision: str
    head_revision: str
    candidate_tree: str
    path_identities: list[PathIdentity]
    changes_outside_kb: list[str]
    unreviewed_paths: list[str]
    kb_valid: bool
    validation_issues: list[str]
    exact_source_verification: str
    manifest_changes: list[str]
    control_updated: bool
    control_changes: list[SemanticFieldChange]
    ontology_changes: list[OntologyReviewChange]
    pages: list[PageReviewChange]
    review_digest: str


class AuthoringReview(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """The standalone review of one staged candidate against an explicit base.

    Stateless evidence for the external skill and native Git: it records the
    complete submitted tree identity, the captured HEAD, the excluded
    unstaged/untracked work and the scoped knowledge review. It authenticates
    no human and authorizes no submission.
    """

    schema_version: int
    validator_contract: str
    namespace: str
    kb_subtree: str
    base_revision: str
    head_revision: str
    base_tree: str
    submitted_tree: str
    excluded_unstaged: list[str]
    excluded_untracked: list[str]
    knowledge: KnowledgeChangeReview
    review_digest: str


class CommitCheck(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """The whole-commit comparison of one resulting commit with its review."""

    schema_version: int
    validator_contract: str
    base_revision: str
    commit: str
    commit_tree: str
    reviewed_tree: str
    matches_reviewed_candidate: bool
    mismatches: list[str]


# ---------------------------------------------------------------------------
# Semantic comparison (all facts from captured immutable bytes).
# ---------------------------------------------------------------------------


def _render(value: Any) -> str:
    """One readable semantic rendering; ``none`` for absent values."""
    return "none" if value is None else str(value)


def _transition(before: str | None, after: str | None) -> str:
    if before == after:
        return ""
    return f"{before or 'none'} -> {after or 'none'}"


def _body_diff(path: str, before: str | None, after: str | None) -> str:
    before_lines = (before or "").splitlines(keepends=True)
    after_lines = (after or "").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(before_lines, after_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    )


_CLAIM_ATTRIBUTES = (
    "value",
    "value_type",
    "object",
    "status",
    "confidence",
    "valid_from",
    "valid_to",
    "origin",
)


def _semantic_field_changes(
    base_page: Any | None, candidate_page: Any | None
) -> list[SemanticFieldChange]:
    """Readable before/after facts for changed authored semantic fields (F3).

    Covers summary, title, same-ID Source metadata (title/URL) and same-ID
    Claim attributes including confidence and validity bounds — the values a
    human must inspect, supplementing the narrower shared ClaimChange
    summaries with the exact old/new facts.
    """
    if base_page is None or candidate_page is None:
        return []
    changes: list[SemanticFieldChange] = []
    if base_page.summary != candidate_page.summary:
        changes.append(
            SemanticFieldChange(
                field="summary",
                before=_render(base_page.summary),
                after=_render(candidate_page.summary),
            )
        )
    if base_page.title != candidate_page.title:
        changes.append(
            SemanticFieldChange(
                field="title",
                before=_render(base_page.title),
                after=_render(candidate_page.title),
            )
        )
    base_sources = {source.id: source for source in base_page.sources}
    candidate_sources = {source.id: source for source in candidate_page.sources}
    for source_id in sorted(set(base_sources) & set(candidate_sources)):
        before, after = base_sources[source_id], candidate_sources[source_id]
        if before.title != after.title:
            changes.append(
                SemanticFieldChange(
                    field=f"source.title:{source_id}",
                    before=_render(before.title),
                    after=_render(after.title),
                )
            )
        if before.url != after.url:
            changes.append(
                SemanticFieldChange(
                    field=f"source.url:{source_id}",
                    before=_render(before.url),
                    after=_render(after.url),
                )
            )
    base_claims = {claim.id: claim for claim in base_page.claims}
    candidate_claims = {claim.id: claim for claim in candidate_page.claims}
    for claim_id in sorted(set(base_claims) & set(candidate_claims)):
        before, after = base_claims[claim_id], candidate_claims[claim_id]
        for attribute in _CLAIM_ATTRIBUTES:
            before_value = getattr(before, attribute)
            after_value = getattr(after, attribute)
            if before_value != after_value:
                changes.append(
                    SemanticFieldChange(
                        field=f"claim.{attribute}:{claim_id}",
                        before=_render(before_value),
                        after=_render(after_value),
                    )
                )
        if len(before.evidence) != len(after.evidence):
            changes.append(
                SemanticFieldChange(
                    field=f"claim.evidence:{claim_id}",
                    before=_render(len(before.evidence)),
                    after=_render(len(after.evidence)),
                )
            )
    return changes


def _page_review_change(
    path: str,
    change: str,
    base_page: Any | None,
    candidate_page: Any | None,
) -> PageReviewChange:
    base_body = base_page.body if base_page is not None else None
    candidate_body = candidate_page.body if candidate_page is not None else None
    body_changed = base_body != candidate_body
    representative = candidate_page or base_page
    page_title = representative.title if representative is not None else ""
    claims = compute_claim_changes(
        list(candidate_page.claims) if candidate_page is not None else [],
        list(base_page.claims) if base_page is not None else [],
        page_title,
    )
    base_types = set(base_page.entity_types) if base_page is not None else set()
    candidate_types = set(candidate_page.entity_types) if candidate_page is not None else set()
    base_sources = {source.id for source in base_page.sources} if base_page is not None else set()
    candidate_sources = (
        {source.id for source in candidate_page.sources} if candidate_page is not None else set()
    )
    return PageReviewChange(
        path=path,
        title=page_title or None,
        change=change,
        body_changed=body_changed,
        frontmatter_only=change == "updated" and not body_changed,
        body_diff=_body_diff(path, base_body, candidate_body),
        lifecycle=_transition(
            base_page.lifecycle if base_page is not None else None,
            candidate_page.lifecycle if candidate_page is not None else None,
        ),
        visibility=_transition(
            base_page.visibility if base_page is not None else None,
            candidate_page.visibility if candidate_page is not None else None,
        ),
        entity_types=sorted(
            {f"- {name}" for name in base_types - candidate_types}
            | {f"+ {name}" for name in candidate_types - base_types}
        ),
        sources=sorted(
            {f"- {source_id}" for source_id in base_sources - candidate_sources}
            | {f"+ {source_id}" for source_id in candidate_sources - base_sources}
        ),
        claims=claims,
        semantic_changes=_semantic_field_changes(base_page, candidate_page),
    )


def _parse_ontology(raw: bytes | None) -> dict[str, dict[str, Any]] | None:
    """The parsed ontology section, or ``None`` when it cannot be safely reviewed.

    A present-but-malformed Control File (decode failure, non-mapping root,
    non-mapping ontology/entity-types/predicates) never reaches unchecked
    attribute calls: the caller refuses boundedly instead (F10).
    """
    if raw is None:
        return {"entity_types": {}, "predicates": {}}
    try:
        data = msgspec.yaml.decode(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    section = data.get("ontology")
    if section is None:
        return {"entity_types": {}, "predicates": {}}
    if not isinstance(section, dict):
        return None
    entity_types = section.get("entity_types")
    predicates = section.get("predicates")
    if entity_types is None:
        entity_types = {}
    if predicates is None:
        predicates = {}
    if not isinstance(entity_types, dict) or not isinstance(predicates, dict):
        return None
    return {"entity_types": entity_types, "predicates": predicates}


def _render_definition(definition: Any) -> str:
    """One readable ontology definition rendering (domain, range, literal)."""
    if not isinstance(definition, dict) or not definition:
        return "defined"
    parts: list[str] = []
    if "subject_types" in definition:
        parts.append("subjects: " + ", ".join(str(item) for item in definition["subject_types"]))
    if "object_types" in definition:
        parts.append("objects: " + ", ".join(str(item) for item in definition["object_types"]))
    if "literal_kind" in definition:
        parts.append("literal: " + str(definition["literal_kind"]))
    if "description" in definition:
        parts.append("description: " + str(definition["description"]))
    return "; ".join(parts) or "defined"


def _ontology_review_changes(
    base_control: bytes | None, candidate_control: bytes | None
) -> list[OntologyReviewChange]:
    """Parsed-semantic ontology diff with readable old/new definitions."""
    base = _parse_ontology(base_control)
    candidate = _parse_ontology(candidate_control)
    if base is None or candidate is None:
        raise AuthoringReviewError(
            "the "
            + ("candidate" if candidate is None else "base")
            + " Control File cannot be parsed into a reviewable ontology; the "
            "captured validation diagnostics remain authoritative and the "
            "semantic comparison is refused rather than guessed",
            code="invalid_staged_control",
        )
    changes: list[OntologyReviewChange] = []
    for kind, label in (("entity_types", "entity_type"), ("predicates", "predicate")):
        before = base[kind]
        after = candidate[kind]
        for name in sorted(set(before) - set(after)):
            changes.append(
                OntologyReviewChange(
                    change=f"{label}_removed",
                    name=name,
                    before=_render_definition(before[name]),
                )
            )
        for name in sorted(set(after) - set(before)):
            changes.append(
                OntologyReviewChange(
                    change=f"{label}_added",
                    name=name,
                    after=_render_definition(after[name]),
                )
            )
        for name in sorted(set(before) & set(after)):
            if before[name] != after[name]:
                changes.append(
                    OntologyReviewChange(
                        change=f"{label}_changed",
                        name=name,
                        detail="parsed definition differs",
                        before=_render_definition(before[name]),
                        after=_render_definition(after[name]),
                    )
                )
    return changes


def _control_review_changes(
    base_control: bytes | None, candidate_control: bytes | None
) -> list[SemanticFieldChange]:
    """Meaningful Control File changes outside the ontology never disappear."""

    def document(raw: bytes | None) -> dict[str, Any]:
        parsed = _parse_ontology(raw)
        if parsed is None or raw is None:
            return {}
        try:
            data = msgspec.yaml.decode(raw)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    base = document(base_control)
    candidate = document(candidate_control)
    base.pop("ontology", None)
    candidate.pop("ontology", None)
    changes: list[SemanticFieldChange] = []
    for key in sorted(set(base) | set(candidate)):
        before, after = base.get(key), candidate.get(key)
        if before != after:
            changes.append(
                SemanticFieldChange(
                    field=f"control.{key}",
                    before=json.dumps(before, sort_keys=True, default=str),
                    after=json.dumps(after, sort_keys=True, default=str),
                )
            )
    return changes


def _manifest_review_changes(base_manifest: Any, candidate_manifest: Any) -> list[str]:
    """Human-readable exact manifest binding/lifecycle changes."""
    changes: list[str] = []
    base_sources = dict(base_manifest.sources)
    candidate_sources = dict(candidate_manifest.sources)
    for source_id in sorted(set(base_sources) - set(candidate_sources)):
        changes.append(f"source removed: {source_id}")
    for source_id in sorted(set(candidate_sources) - set(base_sources)):
        changes.append(f"source added: {source_id} ({candidate_sources[source_id]})")
    for source_id in sorted(set(base_sources) & set(candidate_sources)):
        if base_sources[source_id] != candidate_sources[source_id]:
            changes.append(
                f"source status: {source_id} "
                f"{base_sources[source_id]} -> {candidate_sources[source_id]}"
            )
    for entity_id in sorted(set(base_manifest.bindings) - set(candidate_manifest.bindings)):
        changes.append(f"binding removed: {entity_id}")
    for entity_id in sorted(set(candidate_manifest.bindings) - set(base_manifest.bindings)):
        for source_id, digest in sorted(candidate_manifest.bindings[entity_id].items()):
            changes.append(f"binding added: {entity_id} -> {source_id}@{digest}")
    for entity_id in sorted(set(base_manifest.bindings) & set(candidate_manifest.bindings)):
        before = dict(base_manifest.bindings[entity_id])
        after = dict(candidate_manifest.bindings[entity_id])
        if before != after:
            for source_id in sorted(set(after) - set(before)):
                changes.append(f"binding changed: {entity_id} + {source_id}@{after[source_id]}")
            for source_id in sorted(set(before) - set(after)):
                changes.append(f"binding changed: {entity_id} - {source_id}")
            for source_id in sorted(set(before) & set(after)):
                if before[source_id] != after[source_id]:
                    changes.append(
                        f"binding changed: {entity_id} {source_id} "
                        f"{before[source_id]} -> {after[source_id]}"
                    )
    return changes


def _record_digest(record: Any, digest_field: str) -> str:
    """Canonical digest over EVERY field of one review record but its digest.

    Unambiguous structured serialization (``msgspec.json.encode`` of the
    record's builtins) instead of hand-picked delimiter-joined strings, so
    every reported fact — page titles, complete Claim facts, semantic
    before/after values, path identities, disclosures — is bound (F1).
    """
    data = msgspec.to_builtins(record)
    data.pop(digest_field, None)
    return hashlib.sha256(msgspec.json.encode(data)).hexdigest()


# ---------------------------------------------------------------------------
# Public review operations.
# ---------------------------------------------------------------------------


def review_knowledge_changes(
    kb_root: str | Path,
    base_revision: str,
    *,
    source_registry=None,
    candidate_tree: str | None = None,
) -> KnowledgeChangeReview:
    """Review the Knowledge-Base-scoped changes of one candidate against its base.

    The candidate is one immutable tree identity: ``candidate_tree`` names an
    existing immutable tree in the same repository (Core composition), and its
    absence captures the STAGED tree in private temporary storage. Every body
    and semantic fact derives from those captured bytes — never the mutable
    worktree. ``source_registry`` optionally resolves exact Source Versions;
    without it, exact-source verification is disclosed as unavailable.
    """
    kb_path = Path(kb_root).resolve()
    repo_root, subtree = resolve_repository(kb_path)
    try:
        base = capture_revision(kb_path, base_revision)
    except GitAuthoringError as exc:
        raise AuthoringReviewError(str(exc), code="invalid_base_revision") from exc
    head = _head_revision(repo_root)
    base_tree = _git(repo_root, "rev-parse", f"{base.revision}^{{tree}}").decode().strip()
    prefix = f"{subtree}/" if subtree else ""

    if candidate_tree is not None:
        if not _FULL_TREE_PATTERN.match(candidate_tree) or (
            _git(repo_root, "cat-file", "-t", candidate_tree).decode().strip() != "tree"
        ):
            raise AuthoringReviewError(
                f"candidate_tree {candidate_tree!r} must be one exact full tree object id "
                "(40 lowercase hex characters) naming a tree in this repository; "
                "movable expressions such as rev^{tree} are refused — supply the "
                "immutable tree identity itself",
                code="invalid_candidate_tree",
            )
        candidate = _captured_tree_revision(kb_path, repo_root, subtree, candidate_tree)
        changed = _tree_diff(repo_root, base_tree, candidate_tree)
    else:
        # Everything reading the staged tree must run inside the private
        # object store: its tree objects vanish with the temporary directory.
        with _private_object_store(repo_root) as env:
            tree = _staged_tree(repo_root, env)
            candidate = _captured_tree_revision(kb_path, repo_root, subtree, tree, env=env)
            changed = _tree_diff(repo_root, base_tree, tree, env=env)

    outside = [path for _status, path, _b, _n in changed if prefix and not path.startswith(prefix)]
    inside = [
        (status, path[len(prefix) :] if prefix else path, base_blob, new_blob)
        for status, path, base_blob, new_blob in changed
        if not prefix or path.startswith(prefix)
    ]

    namespace = candidate.manifest.namespace
    validation_issues = [
        f"{issue.file}: {issue.field}: {issue.message}" for issue in candidate.report.issues
    ]
    kb_valid = candidate.report.is_valid
    if namespace != base.manifest.namespace:
        validation_issues.append(
            f"the candidate namespace {namespace} differs from the base namespace "
            f"{base.manifest.namespace}; a Knowledge Base namespace cannot change "
            "in a successor"
        )
        kb_valid = False
    exact_source_verification = "registry" if source_registry is not None else "unavailable"
    # F5: structural Source Reference Manifest consistency is always validated;
    # only exact private version resolution depends on a selected registry.
    from lumio_wiki.source_references import validate_source_references

    reference_issues = validate_source_references(
        candidate.manifest, candidate.kb, registry=source_registry
    )
    if reference_issues:
        validation_issues.extend(reference_issues)
        kb_valid = False

    path_identities = [
        PathIdentity(
            path=path,
            change={"A": "added", "M": "updated", "D": "removed"}[status],
            base_blob=base_blob,
            candidate_blob=new_blob,
        )
        for status, path, base_blob, new_blob in inside
    ]

    base_pages = {page.path: page for page in base.kb.pages}
    candidate_pages = {page.path: page for page in candidate.kb.pages}
    page_changes: list[PageReviewChange] = []
    for path in sorted(set(base_pages) | set(candidate_pages)):
        if path in base_pages and path in candidate_pages:
            # Full parsed-page equality: a frontmatter-only edit (summary,
            # tags, lifecycle, ...) or a same-ID Claim edit is a real change.
            if base_pages[path] == candidate_pages[path]:
                continue
            change = "updated"
        elif path in candidate_pages:
            change = "added"
        else:
            change = "removed"
        page_changes.append(
            _page_review_change(path, change, base_pages.get(path), candidate_pages.get(path))
        )

    # F2: every changed path under the selected subtree must have supported
    # readable review facts (a displayed page, the Control File or the Source
    # Reference Manifest); anything else — unsupported file kinds and valid
    # marked derived artifacts excluded from pages — is disclosed and never
    # silently claimed as reviewed knowledge.
    displayed_paths = set(base_pages) | set(candidate_pages)
    supported_fixed_paths = {_CONTROL_BASENAME, SOURCE_REFERENCE_MANIFEST_BASENAME}
    unreviewed_paths = sorted(
        {
            path
            for _status, path, _base_blob, _new_blob in inside
            if path not in displayed_paths and path not in supported_fixed_paths
        }
    )

    base_control = base.content.get(_CONTROL_BASENAME)
    candidate_control = candidate.content.get(_CONTROL_BASENAME)
    ontology_changes = _ontology_review_changes(base_control, candidate_control)
    control_changes = _control_review_changes(base_control, candidate_control)

    review = KnowledgeChangeReview(
        schema_version=AUTHORING_REVIEW_SCHEMA_VERSION,
        validator_contract=AUTHORING_REVIEW_VALIDATOR_CONTRACT,
        namespace=namespace,
        kb_subtree=subtree,
        base_revision=base.revision,
        head_revision=head,
        candidate_tree=candidate.revision,
        path_identities=path_identities,
        changes_outside_kb=sorted(set(outside)),
        unreviewed_paths=unreviewed_paths,
        kb_valid=kb_valid,
        validation_issues=sorted(set(validation_issues)),
        exact_source_verification=exact_source_verification,
        manifest_changes=_manifest_review_changes(base.manifest, candidate.manifest),
        control_updated=base_control != candidate_control,
        control_changes=control_changes,
        ontology_changes=ontology_changes,
        pages=page_changes,
        review_digest="",
    )
    object.__setattr__(review, "review_digest", _record_digest(review, "review_digest"))
    return review


def review_authoring_candidate(
    kb_root: str | Path,
    base_revision: str,
    *,
    source_registry=None,
) -> AuthoringReview:
    """Review one staged standalone candidate against an explicit full base commit.

    The complete submitted tree identity and HEAD are captured first; the
    Knowledge-Base-scoped facts come from :func:`review_knowledge_changes`.
    Any submitted change OUTSIDE the selected Knowledge Base is refused — a
    standalone submission carries only selected-KB changes; other repository
    work needs its own review. Unstaged and untracked work is disclosed as
    excluded paths, never submitted. This report authorizes nothing.
    """
    knowledge = review_knowledge_changes(
        kb_root, base_revision, source_registry=source_registry, candidate_tree=None
    )
    kb_path = Path(kb_root).resolve()
    repo_root, subtree = resolve_repository(kb_path)
    if knowledge.changes_outside_kb:
        raise AuthoringReviewError(
            "the staged submission contains changes outside the selected Knowledge "
            f"Base subtree {knowledge.kb_subtree or '/'!r}: "
            f"{', '.join(knowledge.changes_outside_kb)}; a standalone candidate "
            "carries only selected-KB changes — unstage them or review them "
            "separately",
            code="changes_outside_kb",
        )
    if knowledge.unreviewed_paths:
        raise AuthoringReviewError(
            "the staged submission contains changed paths with no supported review "
            f"display inside the Knowledge Base: {', '.join(knowledge.unreviewed_paths)}; "
            "a standalone review never submits unreviewed content — remove them or "
            "review them through their own supported operation",
            code="incomplete_review_scope",
        )
    unstaged, untracked = _excluded_work(repo_root)
    review = AuthoringReview(
        schema_version=AUTHORING_REVIEW_SCHEMA_VERSION,
        validator_contract=AUTHORING_REVIEW_VALIDATOR_CONTRACT,
        namespace=knowledge.namespace,
        kb_subtree=knowledge.kb_subtree,
        base_revision=knowledge.base_revision,
        head_revision=knowledge.head_revision,
        base_tree=_git(repo_root, "rev-parse", f"{knowledge.base_revision}^{{tree}}")
        .decode()
        .strip(),
        submitted_tree=knowledge.candidate_tree,
        excluded_unstaged=unstaged,
        excluded_untracked=untracked,
        knowledge=knowledge,
        review_digest="",
    )
    object.__setattr__(review, "review_digest", _record_digest(review, "review_digest"))
    return review


def load_authoring_review_report(path: str | Path) -> AuthoringReview:
    """Load and validate one review report file (the public JSON round-trip).

    Accepts the CLI success envelope; duplicate keys, unknown keys in the
    OWNED review records (which forbid unknown fields), wrong schema versions
    and a review digest that does not match the report's own facts refuse
    boundedly. Embedded shared records (for example the Claim changes from
    :mod:`lumio_wiki.ingest`) keep their existing decoding contract. A valid
    report is intact evidence — it is not authenticated human approval.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthoringReviewError(
            f"the review report could not be read: {exc}", code="invalid_review_report"
        ) from exc

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthoringReviewError(
                    f"the review report contains duplicate key {key!r}",
                    code="invalid_review_report",
                )
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise AuthoringReviewError(
            f"the review report is not valid JSON: {exc}", code="invalid_review_report"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthoringReviewError(
            "the review report must be a JSON object", code="invalid_review_report"
        )
    payload.pop("ok", None)
    try:
        review = msgspec.json.decode(json.dumps(payload), type=AuthoringReview)
    except (msgspec.ValidationError, msgspec.DecodeError) as exc:
        raise AuthoringReviewError(
            f"the review report does not match the v1 review schema: {exc}",
            code="invalid_review_report",
        ) from exc
    _validate_review_record(review)
    return review


def _validate_review_record(review: AuthoringReview) -> None:
    """One coherent integrity seam for imported review records (F1).

    Verifies schema and validator facts, recomputes the EMBEDDED knowledge
    digest from every reported scoped fact (page titles and complete Claim
    facts included) and the outer digest from every wrapper fact, and
    requires the duplicated scope/revision/tree identities to agree. The
    same seam guards the public loader and :func:`check_authoring_commit`,
    so a changed record cannot clear one boundary through the other. This
    validates integrity of evidence — it authenticates no human.
    """
    if review.schema_version != AUTHORING_REVIEW_SCHEMA_VERSION:
        raise AuthoringReviewError(
            f"unsupported review report schema_version {review.schema_version}",
            code="invalid_review_report",
        )
    if review.validator_contract != AUTHORING_REVIEW_VALIDATOR_CONTRACT:
        raise AuthoringReviewError(
            f"unsupported review report validator contract {review.validator_contract!r}",
            code="invalid_review_report",
        )
    knowledge = review.knowledge
    if knowledge.schema_version != AUTHORING_REVIEW_SCHEMA_VERSION or (
        knowledge.validator_contract != AUTHORING_REVIEW_VALIDATOR_CONTRACT
    ):
        raise AuthoringReviewError(
            "the embedded knowledge review does not match the v1 review schema",
            code="invalid_review_report",
        )
    if _record_digest(knowledge, "review_digest") != knowledge.review_digest:
        raise AuthoringReviewError(
            "the embedded knowledge review digest does not match its reported "
            "facts; the report was modified after the review",
            code="invalid_review_report",
        )
    if _record_digest(review, "review_digest") != review.review_digest:
        raise AuthoringReviewError(
            "the review report's digest does not match its own facts; the report "
            "was modified after the review",
            code="invalid_review_report",
        )
    if (
        review.namespace,
        review.kb_subtree,
        review.base_revision,
        review.head_revision,
    ) != (
        knowledge.namespace,
        knowledge.kb_subtree,
        knowledge.base_revision,
        knowledge.head_revision,
    ):
        raise AuthoringReviewError(
            "the outer and embedded scope/revision identities disagree",
            code="invalid_review_report",
        )
    if review.submitted_tree != knowledge.candidate_tree:
        raise AuthoringReviewError(
            "the submitted tree identity disagrees with the embedded candidate tree",
            code="invalid_review_report",
        )


def check_authoring_commit(
    kb_root: str | Path,
    review: AuthoringReview,
    revision: str,
) -> CommitCheck:
    """Verify one whole resulting commit against the reviewed base/candidate.

    Compares the complete commit tree identity with the reviewed submitted
    tree — never just a body or Knowledge-Base fingerprint — and verifies the
    reviewed base is an ancestor. Any difference (a hook or concurrent edit
    changing content, an unreviewed path riding along) is a named mismatch;
    only the exact reviewed candidate matches. No recovery, no reset, no
    human-approval claim.
    """
    repo_root, subtree = resolve_repository(Path(kb_root).resolve())
    _validate_review_record(review)
    mismatches: list[str] = []
    # F4: the check binds the SELECTED Knowledge Base, not just the
    # repository — the selected subtree must be the reviewed subtree, and the
    # commit must carry that subtree's reviewed namespace (read from the
    # commit's own manifest bytes, never the mutable worktree).
    if subtree != review.kb_subtree:
        mismatches.append(
            f"the selected Knowledge Base subtree {subtree or '/'!r} was not the "
            f"reviewed subtree {review.kb_subtree or '/'!r}"
        )
    try:
        commit = resolve_full_commit(repo_root, revision)
        base_revision = resolve_full_commit(repo_root, review.base_revision)
    except GitAuthoringError as exc:
        raise AuthoringReviewError(str(exc), code="invalid_revision") from exc
    manifest_spec = (
        f"{commit}:{subtree + '/' if subtree else ''}{SOURCE_REFERENCE_MANIFEST_BASENAME}"
    )
    if _git_exit_status(repo_root, "cat-file", "-e", f"{manifest_spec}") != 0:
        mismatches.append(
            f"the commit carries no {SOURCE_REFERENCE_MANIFEST_BASENAME} for the "
            f"selected Knowledge Base subtree {subtree or '/'!r}"
        )
    else:
        try:
            commit_namespace = parse_source_reference_manifest(
                _git(repo_root, "cat-file", "blob", manifest_spec)
            ).namespace
        except Exception:
            commit_namespace = None
        if commit_namespace != review.namespace:
            mismatches.append(
                f"the commit's Knowledge Base namespace {commit_namespace!r} for the "
                f"selected subtree is not the reviewed namespace {review.namespace!r}"
            )
    base_tree = _git(repo_root, "rev-parse", f"{base_revision}^{{tree}}").decode().strip()
    if base_tree != review.base_tree:
        mismatches.append(
            f"the reviewed base commit {review.base_revision} now resolves to tree "
            f"{base_tree}, not the reviewed base tree {review.base_tree}"
        )
    if _git_exit_status(repo_root, "merge-base", "--is-ancestor", base_revision, commit) != 0:
        mismatches.append(
            f"commit {commit} does not descend from the reviewed base {review.base_revision}"
        )
    commit_tree = _git(repo_root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if commit_tree != review.submitted_tree:
        mismatches.append(
            f"the commit tree {commit_tree} differs from the reviewed submitted "
            f"tree {review.submitted_tree}"
        )
        reviewed_paths = {
            (
                f"{review.kb_subtree}/{identity.path}" if review.kb_subtree else identity.path
            ): identity
            for identity in review.knowledge.path_identities
        }
        commit_diff = _tree_diff(repo_root, base_tree, commit_tree)
        changed_paths = {path for _status, path, _b, _n in commit_diff}
        for status, path, _base_blob, commit_blob in commit_diff:
            identity = reviewed_paths.get(path)
            if identity is None:
                mismatches.append(f"unreviewed change in commit: {path} ({status})")
            elif identity.candidate_blob != commit_blob:
                mismatches.append(f"changed after review: {path}")
        for path in sorted(set(reviewed_paths) - changed_paths):
            mismatches.append(f"reviewed change missing from commit: {path}")
    return CommitCheck(
        schema_version=AUTHORING_REVIEW_SCHEMA_VERSION,
        validator_contract=AUTHORING_REVIEW_VALIDATOR_CONTRACT,
        base_revision=review.base_revision,
        commit=commit,
        commit_tree=commit_tree,
        reviewed_tree=review.submitted_tree,
        matches_reviewed_candidate=not mismatches,
        mismatches=mismatches,
    )


def _git_exit_status(repo_root: Path, *args: str) -> int:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repo_root), *args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise AuthoringReviewError(
            "the Git executable is required for authoring review but was not found"
        ) from exc
    return result.returncode
