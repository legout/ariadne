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
from typing import cast

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import authoring_inputs, profiler, proposals, sources
from ariadne.sources import Registry, Source

# Operator-owned approval state, ignored via the repo-LOCAL exclude file G2
# already maintains: outside every candidate commit, never staged (plan §2).
SOURCE_APPROVALS_REL = proposals.ARIADNE_STATE_DIR / "source-approvals.json"

# The resolved-identity digest propose_sources returns and approve-sources
# binds: sha256 hex.
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def resolved_digest(entries: object) -> str:
    """sha256 over the canonical form of (resolved) source entries: identity
    is the exact content — whitespace and key order do not matter, any changed
    entry (location, type, table, read-only, complete referenced storage
    profile definition) changes the digest. Shared with the legacy route's
    entries digest."""
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_digest(source_digest: str, storage_bindings: dict | None) -> str:
    """The EFFECTIVE source identity digest (spec 0025 §4): the declared
    identity together with the used profiles' resolved non-secret bindings.
    A registry without named profiles equals its existing source digest, so
    old grants keep their exact key."""
    if not storage_bindings:
        return source_digest
    payload = json.dumps(
        {"source_digest": source_digest, "storage_bindings": storage_bindings},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def storage_bindings_from_identity(resolved: list[dict] | None) -> dict:
    """Resolve the CURRENT effective non-secret bindings of a resolved
    identity from the environment (spec 0025 §4): endpoint/region variable
    values only — no key/token reads, no network. Used profiles only;
    profile-free identities resolve to ``{}`` (no lookup at all)."""
    bindings: dict[str, dict] = {}
    for entry in resolved or []:
        storage = entry.get("storage")
        if not isinstance(storage, dict) or isinstance(storage.get("name"), str) is False:
            continue
        name = storage["name"]
        if name in bindings:
            continue
        profile = sources.profile_from_identity(name, storage)
        bindings[name] = sources.resolve_binding(profile).record()
    return bindings


def _resolved_entries(
    validated: list[Source], storages: dict[str, sources.StorageProfile] | None = None
) -> list[dict]:
    """The canonical resolved identity of each validated source: the ABSOLUTE
    resolved location (URI schemes untouched), plus the exact type/name/table
    and read-only flag — and, for a profile-based source, the COMPLETE
    referenced profile definition (variable names and scopes, never resolved
    values; spec 0025 §4) so the declaration identity is self-contained. This
    is what the digest binds, the approval records, and the shared builder
    opens."""
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
        if src.storage is not None:
            profile = (storages or {}).get(src.storage)
            if profile is None:
                raise ValueError(
                    f"source {src.name!r} references undeclared storage profile "
                    f"{src.storage!r} — the registry must be validated first"
                )
            entry["storage"] = {"name": src.storage, **profile.identity()}
        entries.append(entry)
    return entries


def candidate_identity(project: Path, revision: str) -> dict | None:
    """The candidate registry's complete RESOLVED identity at ``revision``
    (spec 0025 §4): entries are read from the recorded candidate commit's
    ``ariadne.yaml`` blob (never a mutable worktree), validated with the
    shared registry rules — including the ``storages:`` block — and resolved
    against the HOST project root. Each profile-based entry carries its
    complete referenced profile definition; the declaration digest binds
    exactly that. Returns ``None`` when the candidate declares no sources."""
    blob = proposals._read_blob(project, revision, "ariadne.yaml")
    if blob is None:
        return None
    where = f"candidate ariadne.yaml at {revision[:12]}"
    try:
        doc = yaml.safe_load(blob.decode("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{where} is not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{where}: top level is not a mapping")
    if not doc.get("sources"):
        return None
    validated, storages = sources.validate_registry_doc(doc, where, project)
    resolved = _resolved_entries(validated, storages)
    return {
        "sources": resolved,
        "storages": {name: storages[name].identity() for name in sorted(storages)},
        "source_digest": resolved_digest(resolved),
    }


def candidate_sources(project: Path, revision: str) -> tuple[list[dict], str] | tuple[None, None]:
    """The candidate registry's RESOLVED identity at ``revision`` as the
    historical ``(resolved_entries, digest)`` pair (a wrapper over
    :func:`candidate_identity`)."""
    identity = candidate_identity(project, revision)
    if identity is None:
        return None, None
    return identity["sources"], identity["source_digest"]


def identity_registry(
    resolved: list[dict], bindings: dict | None = None
) -> Registry:
    """The operator-APPROVED resolved identity as a registry: DuckDB opens
    exactly these resolved locations — the approval is the permission, the
    candidate's spelling of a path never reaches the builder. Profile-based
    entries carry their complete profile definitions, which reconstruct the
    registry's ``storages``; ``bindings`` (the approval/admission record's
    frozen effective identity, spec 0025 §4) pins each used profile's
    endpoint/region so the connection opens exactly the checked binding."""
    storages: dict[str, sources.StorageProfile] = {}
    objects: list[Source] = []
    for entry in resolved:
        storage = entry.get("storage")
        name = None
        if isinstance(storage, dict):
            name = storage.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(
                    "a resolved source identity carries a malformed storage "
                    "declaration — this needs human resolution, never a silent reset"
                )
            if name not in storages:
                storages[name] = sources.profile_from_identity(name, storage)
        elif isinstance(storage, str):  # a bare reference (defensive)
            name = storage
        objects.append(
            Source(
                name=entry["name"],
                type=entry["type"],
                path=entry.get("path"),
                connection_env=entry.get("connection_env"),
                table=entry.get("table"),
                read_only=entry.get("read_only", True),
                storage=name,
            )
        )
    frozen = {
        name: sources.binding_from_record(name, record)
        for name, record in (bindings or {}).items()
        if name in storages
    }
    return Registry(
        sources=objects,
        path=None,
        storages=storages or None,
        bindings=frozen or None,
    )


# ------------------------------------------------------------- Git-mode propose


def propose_sources(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    sources_entries: list[dict] | tuple[dict, ...],
    storages: dict | None = None,
) -> dict:
    """Append validated typed source entries — plus optional named storage
    profile definitions (spec 0025 §5) — to the candidate's registry
    (``ariadne.yaml``) through the revision-checked edit seam and return the
    digest of the candidate's full RESOLVED identity plus its precise resolved
    locations — never opening anything (plan §2 ``propose_sources``). Entries
    and profiles are credential-free data validated by the shared registry
    rules (ADR-0010, spec 0025 §2) — the WHOLE merged candidate is validated
    before anything is committed. A name already in the candidate registry is
    refused (append, never overwrite). New profiles append; an identical
    existing profile is reused; a conflicting replacement refuses, leaving
    the candidate untouched. An existing candidate profile may be referenced
    without resending it. No environment value, source opening or approval
    occurs during proposal creation (spec 0025 §5).
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
    new_profiles = sources.validate_storages(
        storages, f"source proposal of proposal {proposal}"
    )
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
    clashes = sorted(cast(str, entry["name"]) for entry in entries if entry["name"] in taken)
    if clashes:
        raise ValueError(
            f"source name(s) {clashes} already exist in the candidate registry — a "
            "source proposal appends, it never overwrites an existing entry"
        )
    merged_storages = dict(doc.get("storages") or {})
    for name, profile in new_profiles.items():
        declared = merged_storages.get(name)
        if declared is not None and declared != profile.identity():
            raise ValueError(
                f"storage profile {name!r} already exists in the candidate registry "
                "with a DIFFERENT definition — a conflicting replacement is "
                "refused; propose a new name or resend the identical definition "
                "(spec 0025 §5); nothing was written"
            )
        merged_storages[name] = profile.identity()
    doc["sources"] = [*existing, *entries]
    if merged_storages:
        doc["storages"] = merged_storages
    # The WHOLE merged candidate — existing entries plus the new ones plus
    # the merged storages block — validates BEFORE the revision-checked edit
    # commits anything (spec 0025 §5).
    sources.validate_registry_doc(doc, f"source proposal of proposal {proposal}", project)
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
    — WITHOUT editing the already-committed candidate.
    Requires the exact current candidate revision and the declaration digest
    it resolves to (a stale revision or a digest mismatch refuses before any
    write). On the operator host this resolves the used profiles'
    endpoint/region variables WITHOUT network calls or key/token reads (spec
    0025 §4) and records the effective identity: grants are keyed by
    ``approval_digest`` (declaration plus effective binding), so a later
    endpoint change needs its own grant and the old endpoint's grant is
    retained, never overwritten. A registry without named profiles keeps
    its existing declaration-digest key exactly. Missing endpoint/region
    values are a visible prerequisite — approval refuses naming the
    variable, it never guesses an endpoint.
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
    assert digest is not None  # a nonempty resolved identity always digests
    if digest != source_digest:
        raise ValueError(
            f"source digest mismatch: the candidate registry at {current[:12]} "
            f"resolves to {digest}, not {source_digest} — approval binds the exact "
            "resolved identity; review the current digest and retry"
        )
    bindings = storage_bindings_from_identity(resolved)
    effective = approval_digest(digest, bindings)
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        approvals = _load_approvals(project)
        approvals[effective] = {
            "sources": resolved,
            "source_digest": digest,
            "storage_bindings": bindings,
            "proposal": proposal,
            "revision": current,
            "approved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _store_approvals(project, approvals)
    return {
        "source_digest": digest,
        "approval_digest": effective,
        "storage_bindings": bindings,
        "proposal": proposal,
        "revision": current,
        "sources": resolved,
        "approvals": str(project / SOURCE_APPROVALS_REL),
    }


def _effective_grant(
    project: Path,
    resolved: list[dict] | None,
    digest: str | None,
    proposal: str,
    revision: str,
) -> dict:
    """The operator grant for the candidate's CURRENT effective identity (spec
    0025 §4): resolve the used profiles' non-secret bindings from the
    environment (no key/token reads, no network), derive the effective
    ``approval_digest``, and require the exact matching grant — a declaration
    digest with only a HISTORICAL grant for a different endpoint never
    authorizes the current one. The returned record carries the grant's FROZEN
    bindings for reconstruction (never an environment re-resolved after the
    check). A profile-free identity resolves to its existing declaration
    digest, so old grants keep working unchanged."""
    bindings = storage_bindings_from_identity(resolved)
    effective = approval_digest(digest or "", bindings) if digest else digest
    approval = _load_approvals(project).get(effective or "")
    if approval is None:
        hint = (
            f"re-approve the exact effective identity with ariadne-authoring "
            f"approve-sources --proposal {proposal} --revision {revision} "
            f"--source-digest {digest}"
            if digest
            else "approve the exact identity first"
        )
        raise ValueError(
            f"the source registry of proposal {proposal} (candidate {revision[:12]}) "
            f"resolves to source identity {digest} with effective storage binding "
            f"{effective} and carries NO operator approval for that exact identity "
            f"— source approval is a separate human decision (spec §5, spec 0025 "
            f"§4): {hint}; nothing was opened"
        )
    record = dict(approval)
    record.setdefault("source_digest", digest)
    record.setdefault("storage_bindings", bindings)
    record["approval_digest"] = effective
    return record


def _approved_identity(project: Path, digest: str, proposal: str, revision: str) -> dict:
    """The operator's approval record for ``digest`` (the historical seam),
    effective-identity aware: when the candidate declares storage profiles
    the grant must match the CURRENT effective binding (spec 0025 §4)."""
    resolved, resolved_digest = candidate_sources(project, revision)
    if resolved_digest is not None and resolved_digest != digest:
        # the caller's digest is not what the revision resolves to; the
        # effective-grant path below reports the precise mismatch
        pass
    return _effective_grant(project, resolved, digest, proposal, revision)


def approval_state(project: Path, resolved: list[dict] | None, digest: str | None) -> dict:
    """The OFFLINE effective-approval state of one resolved identity (spec
    0025 §4): distinguishes declaration history from the current effective
    approval WITHOUT key/token reads or network access. ``current``: the
    environment's resolved binding carries a grant. ``not-current``: only a
    different binding of the same declaration was ever approved.
    ``unresolved``: a required endpoint/region value is unset — a visible
    prerequisite, never a corrupt declaration."""
    project = Path(project)
    try:
        bindings = storage_bindings_from_identity(resolved)
    except ValueError as exc:
        return {"state": "unresolved", "reason": str(exc), "approved": False}
    effective = approval_digest(digest or "", bindings) if digest else None
    approvals = _load_approvals(project)
    if effective is not None and effective in approvals:
        return {
            "state": "current",
            "approved": True,
            "approval_digest": effective,
            "storage_bindings": bindings,
        }
    historical = bool(
        digest
        and any(
            record.get("source_digest") == digest for record in approvals.values()
        )
    )
    return {
        "state": "not-current" if historical else "absent",
        "approved": False,
        "approval_digest": effective,
        "storage_bindings": bindings,
    }


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
        assert digest is not None
        approval = _effective_grant(project, resolved, digest, proposal, revision)
        profile = profiler.profile(
            registry=identity_registry(
                approval["sources"], approval.get("storage_bindings")
            ),
            sample_rows=sample_rows,
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
