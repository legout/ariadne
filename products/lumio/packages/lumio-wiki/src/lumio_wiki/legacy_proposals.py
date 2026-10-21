"""Private original-wire inventory and operator-confirmed, unadmitted Git export.

This is a migration reader, never a live proposal store. Preview reads bytes and
Git objects only. Original records, raw artifacts and history stay private and
unchanged; the sole addition on confirmation is a historical export receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import msgspec

from lumio_wiki.git_authoring import (
    GitAuthoringError,
    _git,
    _git_exit,
    _refuse_tracked_private_paths,
    capture_revision,
    resolve_repository,
)
from lumio_wiki.ingest import (
    BlastRadius,
    BodyLinkRepairCandidate,
    EntityMerge,
    ProposedPage,
    SourceProvenance,
)
from lumio_wiki.knowledge_base import KnowledgeBaseControlFile, load_knowledge_base
from lumio_wiki.mutation import atomic_write_bytes, mutation_lock
from lumio_wiki.okf import OkfImportDiagnostic
from lumio_wiki.records import ValidationReport
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
    upsert_binding,
    validate_source_references,
)
from lumio_wiki.source_registry import SourceRegistryError, _RegistryState, _validate_source_id


class SourceChangeImpact(msgspec.Struct, frozen=True):
    """A page-level support result for a staged source lifecycle action."""

    page_title: str
    status: str


class SourceLifecycleChange(msgspec.Struct, frozen=True):
    """Private source action disclosed on an otherwise ordinary proposal."""

    action: str
    source_id: str
    trigger: str
    impacts: list[SourceChangeImpact] = msgspec.field(default_factory=list)


class PageRemoval(msgspec.Struct, frozen=True):
    """An explicit, reviewed removal of one Compiled Page (issue #135)."""

    title: str
    lost_support_reason: str = ""
    affected_claim_notes: list[str] = msgspec.field(default_factory=list)


class PathPrecondition(msgspec.Struct, frozen=True):
    """The persisted reviewed pre-mutation state of one affected path (P4)."""

    path: str
    role: str
    kind: str
    digest: str = ""


class IngestProposal(msgspec.Struct, frozen=True):
    """One persisted legacy proposal record (the retired wire format)."""

    id: str
    status: str
    created_at: str
    provenance: SourceProvenance
    proposed_pages: list[ProposedPage]
    affected_pages: list[str]
    diff: str
    validation_report: ValidationReport
    blocked: bool
    raw_source_path: str | None = None
    blast_radius: BlastRadius | None = None
    control_file: KnowledgeBaseControlFile | None = None
    okf_diagnostics: list[OkfImportDiagnostic] = msgspec.field(default_factory=list)
    source_change: SourceLifecycleChange | None = None
    removed_pages: list[PageRemoval] = msgspec.field(default_factory=list)
    body_link_repairs: list[BodyLinkRepairCandidate] = msgspec.field(default_factory=list)
    entity_merges: list[EntityMerge] = msgspec.field(default_factory=list)
    preconditions: list[PathPrecondition] | None = None
    reviewed_identity: str | None = None


TERMINAL_PROPOSAL_STATUSES = frozenset({"discarded", "published"})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class LegacyExportError(Exception):
    """A bounded migration failure."""


class LegacyExportBlockedError(LegacyExportError):
    """Incomplete or stale intent; originals remain unchanged."""


class LegacyExportConflictError(LegacyExportError):
    """An existing receipt/output or changed input does not match."""


@dataclass(frozen=True)
class LegacyRecordSummary:
    proposal_id: str
    status: str | None = None
    created_at: str | None = None
    blocked: bool | None = None
    affected_pages: tuple[str, ...] = ()
    record_sha256: str | None = None
    raw_file_count: int = 0
    source_action: str | None = None
    source_id: str | None = None
    decode_error: str | None = None

    @property
    def is_terminal(self):
        return self.status in TERMINAL_PROPOSAL_STATUSES

    @property
    def is_exportable(self):
        return self.decode_error is None and self.status == "staged"


@dataclass(frozen=True)
class LegacyPendingTransitionSummary:
    proposal_id: str
    action: str
    source_id: str
    version_sha256: str | None = None


@dataclass(frozen=True)
class LegacyStoreInventory:
    store_root: Path
    store_exists: bool
    records: tuple[LegacyRecordSummary, ...] = ()
    pending_transitions: tuple[LegacyPendingTransitionSummary, ...] = ()
    registry_decode_error: str | None = None
    source_versions: tuple[tuple[str, str, str], ...] = ()
    integrity_errors: tuple[str, ...] = ()

    @property
    def unreviewed(self):
        return tuple(r for r in self.records if r.is_exportable)

    @property
    def terminal(self):
        return tuple(r for r in self.records if r.is_terminal)

    @property
    def undecodable(self):
        return tuple(r for r in self.records if r.decode_error is not None)


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("expected a regular private artifact")
    return path.read_bytes()


def _artifacts(root):
    # Relative locations appear only in the PRIVATE receipt, never Git/output.
    return {
        p.relative_to(root).as_posix(): _sha256(_read_regular(p))
        for p in sorted(root.rglob("*"))
        if p.relative_to(root).parts[0] != "migration-receipts" and not p.is_dir()
    }


def _history(root):
    path = root / "source-registry" / "sources.json"
    state = (
        msgspec.json.decode(_read_regular(path), type=_RegistryState)
        if path.exists()
        else _RegistryState()
    )
    ids = [s.source_id for s in state.sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate private Source identities")
    for source in state.sources:
        _validate_source_id(source.source_id)
        if source.status not in {"active", "retired"}:
            raise ValueError("invalid historical Source lifecycle")
        digests = [v.content_hash for v in source.versions]
        if len(digests) != len(set(digests)):
            raise ValueError("ambiguous historical Source Versions")
        for version in source.versions:
            if version.source_id != source.source_id or not _DIGEST.fullmatch(version.content_hash):
                raise ValueError("invalid exact historical Source Version")
    pending_ids = [p.proposal_id for p in state.pending_transitions]
    if len(pending_ids) != len(set(pending_ids)):
        raise ValueError("ambiguous pending transition")
    for pending in state.pending_transitions:
        source = next((s for s in state.sources if s.source_id == pending.source_id), None)
        if source is None or pending.action not in {"retire", "reactivate"}:
            raise ValueError("pending transition has no matching Source/action")
        expected = "active" if pending.action == "retire" else "retired"
        if source.status != expected:
            raise ValueError("stale pending Source lifecycle")
        if pending.action == "reactivate":
            version = pending.version
            if (
                version is None
                or version.source_id != source.source_id
                or not _DIGEST.fullmatch(version.content_hash)
            ):
                raise ValueError("pending transition has no exact bound Source Version")
    return state


class _HistorySnapshot:
    """Exact read-only lookup, including the selected unreviewed transition."""

    def __init__(self, state, selected):
        self.versions = {
            (s.source_id, v.content_hash): v for s in state.sources for v in s.versions
        }
        for p in state.pending_transitions:
            if p.proposal_id == selected and p.version is not None:
                self.versions[(p.source_id, p.version.content_hash)] = p.version

    def find_version(self, source_id, digest):
        return self.versions.get((source_id, digest))


def inventory_legacy_store(store_root):
    root = Path(store_root)
    records = []
    errors = []
    for path in sorted((root / "proposals").glob("*.json")):
        digest = None
        try:
            raw = _read_regular(path)
            digest = _sha256(raw)
            record = msgspec.json.decode(raw, type=IngestProposal)
            if record.id != path.stem or record.status not in {
                "staged",
                *TERMINAL_PROPOSAL_STATUSES,
            }:
                raise ValueError("record identity/status mismatch")
            raw_digests = [_sha256(_read_regular(p)) for p in (root / "raw" / path.stem).glob("*")]
            if (
                raw_digests
                and record.provenance.source_hash
                and record.provenance.source_hash not in raw_digests
            ):
                errors.append(f"{path.stem}: retained raw digest mismatch")
            records.append(
                LegacyRecordSummary(
                    path.stem,
                    record.status,
                    record.created_at,
                    record.blocked,
                    tuple(record.affected_pages),
                    digest,
                    sum(p.is_file() for p in (root / "raw" / path.stem).glob("*")),
                    record.source_change.action if record.source_change else None,
                    record.source_change.source_id if record.source_change else None,
                )
            )
        except (OSError, ValueError):
            records.append(
                LegacyRecordSummary(
                    path.stem, record_sha256=digest, decode_error="record decode/integrity failed"
                )
            )
    registry_error = None
    pending = ()
    versions = ()
    try:
        state = _history(root)
        pending = tuple(
            LegacyPendingTransitionSummary(
                p.proposal_id,
                p.action,
                p.source_id,
                p.version.content_hash if p.version else None,
            )
            for p in state.pending_transitions
        )
        versions = tuple(
            (s.source_id, s.status, v.content_hash) for s in state.sources for v in s.versions
        )
    except (OSError, ValueError, SourceRegistryError):
        registry_error = "registry decode/integrity failed"
    try:
        _artifacts(root)
    except (OSError, ValueError):
        errors.append("private artifact read/integrity failed")
    return LegacyStoreInventory(
        root, root.is_dir(), tuple(records), pending, registry_error, versions, tuple(errors)
    )


@dataclass(frozen=True)
class LegacyExportPlan:
    proposal_id: str
    record_sha256: str
    baseline: str
    branch: str
    repository_root: str
    kb_subtree: str
    namespace: str
    source_action: str | None = None
    source_id: str | None = None
    binding_sha256: str | None = None
    written_pages: tuple[str, ...] = ()
    removed_titles: tuple[str, ...] = ()
    control_file_change: bool = False
    manifest_change: bool = False
    raw_file_count: int = 0
    pending_transition: bool = False
    blocking_diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyExportResult:
    plan: LegacyExportPlan
    branch: str
    commit: str
    tree: str
    receipt_path: Path
    recognized_retry: bool = False


def _record_identity(record):
    # Original P4 payload/JSON contract, not a new migration serialization.
    payload = {
        "affected_pages": list(record.affected_pages),
        "body_link_repairs": [msgspec.to_builtins(p) for p in record.body_link_repairs],
        "control_file": msgspec.to_builtins(record.control_file) if record.control_file else None,
        "entity_merges": [msgspec.to_builtins(p) for p in record.entity_merges],
        "proposed_pages": [msgspec.to_builtins(p) for p in record.proposed_pages],
        "removed_pages": [msgspec.to_builtins(p) for p in record.removed_pages],
        "source_change": msgspec.to_builtins(record.source_change)
        if record.source_change
        else None,
    }
    return _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    )


def _safe_path(path):
    rel = PurePosixPath(path)
    if not path or rel.is_absolute() or ".." in rel.parts or "\\" in path or rel.as_posix() != path:
        raise LegacyExportBlockedError("invalid original mutation path")
    return path


def _check_preconditions(record, captured):
    if record.preconditions is None or record.reviewed_identity != _record_identity(record):
        raise LegacyExportBlockedError(
            "missing or inconsistent original reviewed identity/preconditions"
        )
    expected = {"lumio.yaml": "control"}
    by_title = {p.title: p for p in captured.kb.pages}
    for page in record.proposed_pages:
        target = by_title.get(page.rename_from or page.title)
        destination = _safe_path(page.relative_path)
        if page.compound_revision and page.move_from_path:
            raise LegacyExportBlockedError("compound+move requires separate explicit edits")
        if page.move_from_path and page.move_from_path != destination:
            expected[_safe_path(page.move_from_path)] = "move-source"
            expected[destination] = "creation"
        else:
            expected[target.path if target else destination] = "revision" if target else "creation"
    for removal in record.removed_pages:
        if removal.title not in by_title:
            raise LegacyExportBlockedError("a removed Entity is absent from the selected baseline")
        expected[by_title[removal.title].path] = "removal"
    actual = {}
    for pre in record.preconditions:
        path = _safe_path(pre.path)
        if path in actual:
            raise LegacyExportBlockedError("duplicate original path precondition")
        actual[path] = pre.role
        try:
            raw = captured.source.read_bytes(path)
        except KeyError:
            raw = None
        if pre.kind == "absent":
            matches = raw is None
        elif pre.kind == "file":
            matches = raw is not None and pre.digest == _sha256(raw)
        else:
            matches = False
        if not matches:
            raise LegacyExportBlockedError("stale original reviewed path precondition: " + path)
    if actual != expected:
        raise LegacyExportBlockedError("original preconditions do not cover the complete mutation")


def _receipt_path(root, proposal_id):
    return root / "migration-receipts" / (proposal_id + ".json")


def _branch_commit(repo, branch):
    if _git_exit(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch):
        return None
    return _git(repo, "rev-parse", "refs/heads/" + branch).decode().strip()


def _export_input(store_root, proposal_id, kb_root, baseline, branch):
    root = Path(store_root).resolve()
    repo, subtree = resolve_repository(kb_root)
    diagnostics = []
    record = captured = None
    digest = ""
    namespace = ""
    binding = None
    transition = None
    state = _RegistryState()
    artifacts = {}
    resolved = baseline
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", proposal_id):
            raise LegacyExportBlockedError("invalid selected legacy record identifier")
        _refuse_tracked_private_paths(repo, "legacy store", root)
        if _git_exit(repo, "check-ref-format", "refs/heads/" + branch):
            raise LegacyExportBlockedError("invalid export branch")
        raw = _read_regular(root / "proposals" / (proposal_id + ".json"))
        digest = _sha256(raw)
        record = msgspec.json.decode(raw, type=IngestProposal)
        if record.id != proposal_id or record.status != "staged":
            raise LegacyExportBlockedError(
                "only the selected unreviewed record can be exported; "
                "terminal records stay archived"
            )
        resolved = _git(repo, "rev-parse", "--verify", baseline + "^{commit}").decode().strip()
        captured = capture_revision(kb_root, resolved)
        namespace = captured.manifest.namespace
        if not captured.report.is_valid:
            raise LegacyExportBlockedError("the selected baseline Knowledge Base is invalid")
        state = _history(root)
        artifacts = _artifacts(root)
        transition = next(
            (p for p in state.pending_transitions if p.proposal_id == proposal_id), None
        )
        if record.source_change:
            change = record.source_change
            if transition is None or (transition.action, transition.source_id) != (
                change.action,
                change.source_id,
            ):
                diagnostics.append(
                    "missing or inconsistent exact bound Source Version / pending transition"
                )
            elif change.action == "reactivate" and transition.version is not None:
                binding = transition.version.content_hash
        elif transition:
            diagnostics.append("pending source transition has no matching record intent")
        if record.provenance.source_id:
            source_id = record.provenance.source_id
            _validate_source_id(source_id)
            source_hash = record.provenance.source_hash
            if captured.manifest.sources.get(source_id) == "retired" and not (
                record.source_change
                and (record.source_change.action, record.source_change.source_id)
                == ("reactivate", source_id)
            ):
                diagnostics.append(
                    f"source {source_id!r} is retired in the selected baseline; "
                    "resolve the conflict with explicit verified reactivation intent"
                )
            exact = _HistorySnapshot(state, proposal_id).find_version(source_id, source_hash)
            if exact is None:
                diagnostics.append(
                    "the record has no exact bound Source Version in private history"
                )
            if binding and source_hash != binding:
                diagnostics.append("raw provenance and pending Source Version disagree")
            raw_digests = [
                v for k, v in artifacts.items() if k.startswith("raw/" + proposal_id + "/")
            ]
            if raw_digests and source_hash not in raw_digests:
                diagnostics.append(
                    "retained raw bytes do not match the original exact Source Version"
                )
        try:
            _check_preconditions(record, captured)
        except LegacyExportBlockedError as exc:
            diagnostics.append(str(exc))
    except (OSError, ValueError, SourceRegistryError, GitAuthoringError, LegacyExportError) as exc:
        diagnostics.append(
            str(exc)
            if isinstance(exc, (GitAuthoringError, LegacyExportError))
            else "legacy record/history decode or integrity failed"
        )
    plan = LegacyExportPlan(
        proposal_id,
        digest,
        resolved,
        branch,
        str(repo),
        subtree,
        namespace,
        record.source_change.action if record and record.source_change else None,
        record.source_change.source_id if record and record.source_change else None,
        binding,
        tuple(p.relative_path for p in record.proposed_pages) if record else (),
        tuple(p.title for p in record.removed_pages) if record else (),
        bool(record and record.control_file),
        True,
        sum(k.startswith("raw/" + proposal_id + "/") for k in artifacts),
        transition is not None,
        tuple(diagnostics),
    )
    identity = {
        "repository": str(repo),
        "common_git": _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        .decode()
        .strip(),
        "kb_subtree": subtree,
        "baseline": resolved,
        "branch": branch,
        "record_sha256": digest,
        "artifacts": artifacts,
        "namespace": namespace,
    }
    receipt = None
    receipt_path = _receipt_path(root, proposal_id)
    tip = _branch_commit(repo, branch)
    if receipt_path.exists():
        try:
            receipt = msgspec.json.decode(_read_regular(receipt_path))
            if not isinstance(receipt, dict) or any(
                receipt.get(k) != v for k, v in identity.items()
            ):
                raise ValueError("export identity changed")
            if tip != receipt.get("commit") or not tip:
                raise ValueError("export branch changed or missing")
            if _git(repo, "rev-parse", tip + "^{tree}").decode().strip() != receipt.get("tree"):
                raise ValueError("export tree changed")
        except (OSError, ValueError, GitAuthoringError):
            diagnostics.append(
                "migration receipt/output conflicts: refusing to overwrite or duplicate"
            )
    elif tip:
        diagnostics.append("export branch exists without a matching migration receipt")
    if tuple(diagnostics) != plan.blocking_diagnostics:
        from dataclasses import replace

        plan = replace(plan, blocking_diagnostics=tuple(diagnostics))
    return plan, record, captured, state, identity, receipt


def plan_legacy_export(store_root, proposal_id, *, kb_root, baseline, branch):
    return _export_input(store_root, proposal_id, kb_root, baseline, branch)[0]


def _candidate_manifest(record, captured, kb, state, plan):
    baseline = captured.manifest
    sources = dict(baseline.sources)
    bindings = {entity: dict(pins) for entity, pins in baseline.bindings.items()}
    original_ids = {p.id: p for p in captured.kb.pages}
    live_ids = {p.id for p in kb.pages}
    redirects = {r.from_id: r.to_id for r in kb.control.ontology.redirects} if kb.control else {}
    for merge in record.entity_merges:
        old = merge.retired_entity_id
        new = merge.surviving_entity_id
        if (
            old not in original_ids
            or new not in live_ids
            or old in live_ids
            or original_ids[old].title != merge.retired_title
            or redirects.get(old) != new
        ):
            raise LegacyExportBlockedError(
                "incomplete explicit Entity Merge/removal/redirect intent"
            )
        target = bindings.setdefault(new, {})
        for sid, digest in bindings.pop(old, {}).items():
            if sid in target and target[sid] != digest:
                raise LegacyExportBlockedError(
                    "conflicting exact Source Versions in explicit Entity Merge"
                )
            target[sid] = digest
    removed_ids = {p.id for p in captured.kb.pages if p.title in plan.removed_titles}
    for changed in record.proposed_pages:
        if changed.rename_from:
            before = next((p for p in captured.kb.pages if p.title == changed.rename_from), None)
            after = next((p for p in kb.pages if p.title == changed.title), None)
            if before is None or after is None or before.id != after.id:
                raise LegacyExportBlockedError(
                    "title rename cannot change or infer Entity identity"
                )
    for entity in removed_ids - live_ids:
        bindings.pop(entity, None)
    manifest = SourceReferenceManifest(
        version=1, namespace=baseline.namespace, sources=sources, bindings=bindings
    )
    if record.provenance.source_id:
        sid = record.provenance.source_id
        for page in kb.pages:
            if page.title in {p.title for p in record.proposed_pages} and any(
                s.id == sid for s in page.sources
            ):
                if not page.id:
                    raise LegacyExportBlockedError(
                        "managed export requires an explicit stable Entity ID"
                    )
                manifest = upsert_binding(manifest, page.id, sid, record.provenance.source_hash)
    if record.source_change:
        sid = record.source_change.source_id
        sources = dict(manifest.sources)
        sources[sid] = "retired" if record.source_change.action == "retire" else "active"
        bindings = {
            entity: {s: d for s, d in pins.items() if s != sid}
            for entity, pins in manifest.bindings.items()
        }
        manifest = SourceReferenceManifest(
            version=1,
            namespace=baseline.namespace,
            sources=sources,
            bindings={e: pins for e, pins in bindings.items() if pins},
        )
        if record.source_change.action == "reactivate":
            for page in kb.pages:
                if any(s.id == sid for s in page.sources):
                    manifest = upsert_binding(manifest, page.id, sid, plan.binding_sha256)
    findings = validate_source_references(manifest, kb, registry=_HistorySnapshot(state, record.id))
    if findings:
        raise LegacyExportBlockedError(
            "exact exported source bindings are invalid: " + "; ".join(findings)
        )
    return manifest


def export_legacy_proposal(store_root, proposal_id, *, kb_root, baseline, branch):
    """Explicit confirmation only. Create an unadmitted branch, never publish."""
    # Confirmation binds the displayed captured commit, not a ref that can move.
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise LegacyExportBlockedError(
            "confirmation requires the captured FULL baseline commit from preview; "
            "preview may resolve a ref, then confirm using plan.baseline"
        )
    # Serialize cooperative exports without ever locking during inventory/preview.
    root = Path(store_root).resolve()
    with mutation_lock(root):
        plan, record, captured, state, identity, receipt = _export_input(
            root, proposal_id, kb_root, baseline, branch
        )
        if plan.blocking_diagnostics:
            error = (
                LegacyExportConflictError
                if any(
                    "receipt" in d or "export branch exists" in d for d in plan.blocking_diagnostics
                )
                else LegacyExportBlockedError
            )
            raise error("; ".join(plan.blocking_diagnostics))
        if receipt is not None:
            return LegacyExportResult(
                plan,
                branch,
                receipt["commit"],
                receipt["tree"],
                _receipt_path(root, proposal_id),
                True,
            )
        repo = Path(plan.repository_root)
        created = None
        with tempfile.TemporaryDirectory(prefix="lumio-legacy-export-") as tmp:
            worktree = Path(tmp) / "baseline"
            _git(
                repo,
                "-c",
                "core.hooksPath=/dev/null",
                "worktree",
                "add",
                "--detach",
                str(worktree),
                plan.baseline,
            )
            try:
                from lumio_wiki.publish import apply_proposed_pages

                kb_path = worktree / plan.kb_subtree
                apply_proposed_pages(
                    record.proposed_pages,
                    kb_path,
                    removed_titles=list(plan.removed_titles) or None,
                    control_file=record.control_file,
                )
                kb, report = load_knowledge_base(kb_path)
                if not report.is_valid:
                    raise LegacyExportBlockedError(
                        "the exported candidate does not validate: " + str(report)
                    )
                manifest = _candidate_manifest(record, captured, kb, state, plan)
                (kb_path / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
                    serialize_source_reference_manifest(manifest)
                )
                # Detect changing original input before publishing a ref/receipt.
                if _artifacts(root) != identity["artifacts"]:
                    raise LegacyExportConflictError("private artifacts changed during export")
                _git(worktree, "add", "-A")
                required = [page.path for page in kb.pages] + [SOURCE_REFERENCE_MANIFEST_BASENAME]
                if (kb_path / "lumio.yaml").is_file():
                    required.append("lumio.yaml")
                for relative in required:
                    staged_path = (PurePosixPath(plan.kb_subtree) / relative).as_posix()
                    if _git_exit(
                        worktree,
                        "--literal-pathspecs",
                        "ls-files",
                        "--error-unmatch",
                        "--",
                        staged_path,
                    ):
                        raise LegacyExportBlockedError(
                            f"export destination {relative!r} is missing from the Git index; "
                            "review and adjust ignore rules before exporting"
                        )
                safe_origin = (
                    record.provenance.origin
                    if record.provenance.origin
                    in {"cross-linker", "semantic-dream", "graph-exchange", "capture"}
                    else None
                )
                message = (
                    "lumio: unadmitted legacy export\n\nRecord-SHA256: "
                    + plan.record_sha256
                    + "\nBaseline: "
                    + plan.baseline
                )
                if safe_origin:
                    message += "\nOrigin: " + safe_origin
                _git(
                    worktree,
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgSign=false",
                    "commit",
                    "--no-verify",
                    "-m",
                    message,
                )
                commit = _git(worktree, "rev-parse", "HEAD").decode().strip()
                tree = _git(worktree, "rev-parse", "HEAD^{tree}").decode().strip()
                _git(repo, "update-ref", "refs/heads/" + branch, commit, "0" * 40)
                created = commit
                receipt = dict(
                    identity,
                    schema=1,
                    proposal_id=proposal_id,
                    commit=commit,
                    tree=tree,
                    origin=record.provenance.origin,
                )
                path = _receipt_path(root, proposal_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(path, msgspec.json.encode(receipt))
            except BaseException:
                if created:
                    _git(repo, "update-ref", "-d", "refs/heads/" + branch, created)
                raise
            finally:
                _git(repo, "worktree", "remove", "--force", str(worktree))
        return LegacyExportResult(plan, branch, commit, tree, path)
