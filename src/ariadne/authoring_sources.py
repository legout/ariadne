"""Git-aware source access for authoring proposals (issue #35/G3; spec
2026-10-02-0009 §5 "Source approval and artifact admission", AC5/6/8; plan §2
"Project storage and authority" + "Authoring call contract").

Source approval and artifact admission are distinct decisions: a proposed or
committed ``ariadne.yaml`` entry NEVER grants permission to connect (spec §5).
The Git route keeps registry edits in the candidate — :func:`propose_sources`
appends validated, credential-free, registry-shaped entries to the candidate's
``ariadne.yaml`` through the revision-checked edit seam and returns the digest
of the RESOLVED identity, never opening anything — while the separate
human-only :func:`approve_sources` records the operator's permission OUTSIDE
Git artifacts, under the operator-owned ignored ``.ariadne/
source-approvals.json``, keyed by that resolved identity. Approval edits no
already-committed candidate bytes.

Identity is host-root based: the candidate's registry entries are read from
the RECORDED candidate revision (never a mutable worktree checkout) and
resolved against the configured data-project root, so a worktree checkout, a
changed entry, a committed document-root setting or a source digest mismatch
can never grant access — :func:`inputs` compares the actual resolved registry
identity with the operator-approved identity BEFORE any source access, and
the shared connection builder is never called for an unapproved one. Approval
records are keyed by resolved identity (not by proposal slot), so granting
access for a concurrent proposal never overwrites the active snapshot's grant,
and no new proposal revokes one. The LEGACY route
(:func:`ariadne.authoring.propose_sources` / ``approve_sources`` /
``harness_inputs``) is unchanged for legacy callers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import authoring_inputs, profiler, proposals, sources
from ariadne.sources import Registry, Source

# Operator-owned approval state, ignored via the repo-LOCAL exclude file G2
# already maintains: outside every candidate commit, never staged (plan §2).
SOURCE_APPROVALS_REL = proposals.ARIADNE_STATE_DIR / "source-approvals.json"

# The resolved-identity digest propose_sources returns and approve-sources
# binds: sha256 hex.
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def resolved_digest(entries: list[dict]) -> str:
    """sha256 over the canonical form of (resolved) source entries: identity
    is the exact content — whitespace and key order do not matter, any changed
    entry (location, type, table, read-only) changes the digest. Shared with
    the legacy route's entries digest."""
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolved_entries(validated: list[Source]) -> list[dict]:
    """The canonical resolved identity of each validated source: the ABSOLUTE
    resolved location (URI schemes untouched), plus the exact type/name/table
    and read-only flag. This is what the digest binds, the approval records,
    and the shared builder opens."""
    entries: list[dict] = []
    for src in validated:
        entry: dict = {"name": src.name, "type": src.type, "read_only": src.read_only}
        if src.path is not None:
            entry["path"] = (
                src.path
                if sources._URI_SCHEME_RE.match(src.path)
                else str(Path(src.path).resolve())
            )
        if src.connection_env is not None:
            entry["connection_env"] = src.connection_env
        if src.table is not None:
            entry["table"] = src.table
        entries.append(entry)
    return entries


def candidate_sources(project: Path, revision: str) -> tuple[list[dict], str] | tuple[None, None]:
    """The candidate registry's RESOLVED identity at ``revision``: entries are
    read from the recorded candidate commit's ``ariadne.yaml`` blob (never a
    mutable worktree), validated with the shared registry rules and resolved
    against the HOST project root. Returns ``(None, None)`` when the candidate
    declares no sources; malformed registries raise the registry validator's
    explicit errors."""
    blob = proposals._read_blob(project, revision, "ariadne.yaml")
    if blob is None:
        return None, None
    where = f"candidate ariadne.yaml at {revision[:12]}"
    try:
        doc = yaml.safe_load(blob.decode("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{where} is not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{where}: top level is not a mapping")
    if not doc.get("sources"):
        return None, None
    validated = sources.validate_entries(doc["sources"], where, project)
    resolved = _resolved_entries(validated)
    return resolved, resolved_digest(resolved)


def identity_registry(resolved: list[dict]) -> Registry:
    """The operator-APPROVED resolved identity as a registry: DuckDB opens
    exactly these resolved locations — the approval is the permission, the
    candidate's spelling of a path never reaches the builder."""
    return Registry(
        sources=[
            Source(
                name=entry["name"],
                type=entry["type"],
                path=entry.get("path"),
                connection_env=entry.get("connection_env"),
                table=entry.get("table"),
                read_only=entry.get("read_only", True),
            )
            for entry in resolved
        ],
        path=None,
    )


# ------------------------------------------------------------- Git-mode propose


def propose_sources(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    sources_entries: list[dict] | tuple[dict, ...],
) -> dict:
    """Append validated typed source entries to the candidate's registry
    (``ariadne.yaml``) through the revision-checked edit seam and return the
    digest of the candidate's full RESOLVED identity plus its precise resolved
    locations — never opening anything (plan §2 ``propose_sources``). Entries
    are credential-free data validated by the shared registry rules
    (ADR-0010); a name already in the candidate registry is refused (append,
    never overwrite). Relative paths are resolved against the HOST project
    root for the identity; the committed registry keeps the caller's
    spelling, and every later read re-resolves it against the same root.
    ``approve_sources``/``inputs`` re-derive this digest from the committed
    blob, so any later registry change is an identity mismatch."""
    project = Path(project).resolve()
    if not isinstance(sources_entries, (list, tuple)):
        raise ValueError("typed source entries must be a list of registry-shaped mappings")
    entries: list[dict] = []
    for entry in sources_entries:
        if not isinstance(entry, dict):
            raise ValueError(f"a typed source entry must be a mapping, got {type(entry).__name__}")
        entries.append(dict(entry))
    # the shared registry rules (ADR-0010) validate the typed entries — shape,
    # types, credentials, duplicates — BEFORE anything is written
    sources.validate_entries(entries, f"source proposal of proposal {proposal}", project)
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if expected_revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the "
            f"source proposal expected {expected_revision} — re-read the registry "
            "and retry with the current candidate revision; nothing was written"
        )
    blob = proposals._read_blob(project, current, "ariadne.yaml")
    if blob is None:
        doc: dict = {}
    else:
        doc = yaml.safe_load(blob.decode("utf-8")) or {}
        if not isinstance(doc, dict):
            raise ValueError(
                f"proposal {proposal}: candidate ariadne.yaml at {current[:12]} is not a mapping"
            )
    existing = doc.get("sources") or []
    if not isinstance(existing, list):
        raise ValueError(f"proposal {proposal}: candidate ariadne.yaml 'sources' is not a list")
    taken = {entry.get("name") for entry in existing if isinstance(entry, dict)}
    clashes = sorted(entry["name"] for entry in entries if entry["name"] in taken)
    if clashes:
        raise ValueError(
            f"source name(s) {clashes} already exist in the candidate registry — a "
            "source proposal appends, it never overwrites an existing entry"
        )
    doc["sources"] = [*existing, *entries]
    edited = proposals.edit_proposal(
        project,
        proposal,
        expected_revision,
        "ariadne.yaml",
        yaml.safe_dump(doc, sort_keys=False),
    )
    # The digest a human approves and every later read derives is the FULL
    # resolved identity of the resulting candidate registry (approve-sources
    # and inputs re-derive it from the committed blob): one coherent identity,
    # so any later change — appended, edited or removed — is a mismatch.
    resolved_identity, digest = candidate_sources(project, edited["revision"])
    if resolved_identity is None:  # unreachable: the merge just added entries
        raise ValueError(f"proposal {proposal}: the registry edit committed no source entries")
    return {
        "proposal": proposal,
        "revision": edited["revision"],
        "changed": edited["changed"],
        "source_digest": digest,
        "sources": resolved_identity,
    }


# ------------------------------------------------- operator-owned approval state


def _load_approvals(project: Path) -> dict:
    """The persisted approval records keyed by resolved identity ({} when none
    exist). A non-regular, unreadable or malformed file is a human-resolution
    failure — operator-owned state is never silently reset."""
    path = project / SOURCE_APPROVALS_REL
    entry = proposals._lstat(path)
    if entry is None:
        return {}
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"{path}: refusing a non-regular source-approvals file — operator-owned "
            "state, inspect it by hand"
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path}: unreadable source approvals ({exc}) — this needs human "
            "resolution, not an agent reset"
        ) from None
    if not isinstance(doc, dict) or not all(
        isinstance(key, str) and isinstance(value, dict) for key, value in doc.items()
    ):
        raise ValueError(
            f"{path}: malformed source approvals — this needs human resolution, not an agent reset"
        )
    return doc


def _store_approvals(project: Path, approvals: dict) -> None:
    """Persist the approval records atomically (tmp + os.replace) and durably
    (the proposal-record discipline: data synced before the rename, the
    directory entry after)."""
    path = project / SOURCE_APPROVALS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(approvals, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    proposals._fsync_path(path.parent)


def approve_sources(project: str | Path, proposal: str, revision: str, source_digest: str) -> dict:
    """HUMAN-ONLY (never an MCP/Agent tool): record the operator's permission
    for the EXACT resolved source identity of the proposal's current candidate
    revision, under the operator-owned ``.ariadne/source-approvals.json``
    keyed by that identity — WITHOUT editing the already-committed candidate.
    Requires the exact current candidate revision and the digest it resolves
    to (a stale revision or a digest mismatch refuses before any write).
    Records are identity-keyed, so approving for a concurrent proposal never
    overwrites another identity's grant, and nothing is ever revoked
    automatically."""
    project = Path(project).resolve()
    if not isinstance(source_digest, str) or not _HEX64_RE.fullmatch(source_digest):
        raise ValueError("the source digest must be the 64-hex sha256 returned by propose-sources")
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if revision != current:
        raise ValueError(
            f"revision {revision} is not proposal {proposal}'s current candidate "
            f"({current}) — approval binds the exact committed registry; re-review "
            "and approve the current revision"
        )
    resolved, digest = candidate_sources(project, current)
    if resolved is None:
        raise ValueError(
            f"proposal {proposal} declares no source entries in its candidate "
            f"registry at {current[:12]} — there is nothing to approve"
        )
    if digest != source_digest:
        raise ValueError(
            f"source digest mismatch: the candidate registry at {current[:12]} "
            f"resolves to {digest}, not {source_digest} — approval binds the exact "
            "resolved identity; review the current digest and retry"
        )
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        approvals = _load_approvals(project)
        approvals[digest] = {
            "sources": resolved,
            "proposal": proposal,
            "revision": current,
            "approved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _store_approvals(project, approvals)
    return {
        "source_digest": digest,
        "proposal": proposal,
        "revision": current,
        "sources": resolved,
        "approvals": str(project / SOURCE_APPROVALS_REL),
    }


def _approved_identity(project: Path, digest: str, proposal: str, revision: str) -> dict:
    """The operator's approval record for ``digest``, or an explicit error
    naming the human step — a committed or changed registry entry never grants
    access (spec §5, AC5)."""
    approval = _load_approvals(project).get(digest)
    if approval is None:
        raise ValueError(
            f"the source registry of proposal {proposal} (candidate {revision[:12]}) "
            f"resolves to source identity {digest} with NO operator approval — "
            "source approval is a separate human decision (spec §5): approve the "
            f"exact identity with ariadne-authoring approve-sources --proposal "
            f"{proposal} --revision {revision} --source-digest {digest}; "
            "nothing was opened"
        )
    return approval


# ----------------------------------------------------------- Git-mode inputs


def inputs(
    project: str | Path,
    proposal: str,
    *,
    documents: list[str] | tuple[str, ...] = (),
    part: int = 1,
    sample_rows: int | None = None,
) -> dict:
    """The measured inputs of one proposal (plan §2 ``inputs``): the profile
    of the APPROVED resolved registry identity — compared with the operator's
    approval BEFORE any source access, so an unapproved or changed entry is an
    explicit error and the shared connection builder is never called for it —
    plus source-linked converted evidence for the referenced documents (the
    operator's HOST-root document boundary; a candidate's committed
    ``documents:`` section is never consulted) and the candidate's Seed Notes
    evidence from the recorded candidate revision. Bounded exactly like the
    legacy harness inputs; digests are stable across calls (same bytes, same
    digest)."""
    project = Path(project).resolve()
    record = proposals._load_record(project, proposal)
    revision = record["candidate_revision"]
    documents = list(documents)
    if len(documents) > authoring_inputs.MAX_DOCUMENTS_PER_CALL:
        raise ValueError(
            f"{len(documents)} documents exceeds the per-call bound of "
            f"{authoring_inputs.MAX_DOCUMENTS_PER_CALL} — fetch document evidence "
            "in bounded batches (spec §3)"
        )
    resolved, digest = candidate_sources(project, revision)
    profile = None
    if resolved is not None:
        approval = _approved_identity(project, digest, proposal, revision)
        profile = profiler.profile(
            registry=identity_registry(approval["sources"]), sample_rows=sample_rows
        )
    seed_notes = None
    notes_blob = proposals._read_blob(project, revision, authoring_inputs.SEED_NOTES_REL.as_posix())
    if notes_blob is not None:
        seed_notes = authoring_inputs.bytes_evidence(
            f"{revision}:data/seed_notes.md",
            authoring_inputs.SEED_NOTES_REL.name,
            notes_blob,
            part=part,
        )
    return {
        "proposal": proposal,
        "revision": revision,
        "sources_digest": digest,
        "profile": profile,
        "documents": [
            authoring_inputs.document_evidence(reference, project=project, part=part)
            for reference in documents
        ],
        "seed_notes": seed_notes,
    }
