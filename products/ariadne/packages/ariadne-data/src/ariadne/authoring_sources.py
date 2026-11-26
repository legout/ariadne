"""Git-aware source access for the active draft (issue #35/G3, spec 0040 §3.4).

Source declaration and source consent are distinct: a declared or committed
``ariadne.yaml`` entry NEVER grants permission to connect. :func:`add_sources`
appends validated, credential-free, registry-shaped entries to the active draft's
``ariadne.yaml`` and returns the digest of the RESOLVED identity, opening nothing.
The operator's consent is a **source grant** (:func:`record_grants`), recorded
append-only under the project lock in the operator-owned ignored
``.ariadne/source_grants.json`` — human-only, never an agent surface. A grant is
not a release activation: it authorizes bounded reads for authoring (profiling,
inspection, schema refresh, preview, validation) only.

The effective grant set is the served release's bound identities plus the grants
(:func:`_effective_grant`). Identity is host-root based: the candidate's registry
entries are read from the RECORDED candidate revision (never a mutable worktree
checkout) and resolved against the configured data-project root, so a changed
entry or endpoint, or a committed document-root setting, can never grant access —
:func:`inputs` compares the actual resolved identity with the grant BEFORE any
source access, and the shared connection builder is never called for an
ungranted one.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import authoring_inputs, draft, execution, profiler, proposals, sources
from ariadne.sources import Registry, Source

# Operator-owned source grants (spec 0040 §3.4), ignored via the repo-LOCAL exclude
# file: outside every candidate commit, never staged. Append-only, project-locked.
SOURCE_GRANTS_REL = proposals.ARIADNE_STATE_DIR / "source_grants.json"

# The resolved-identity digest propose_sources returns and approve-sources
# binds: sha256 hex.
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def resolved_digest(entries: object) -> str:
    """sha256 over the canonical form of (resolved) source entries: identity
    is the exact content — whitespace and key order do not matter, any changed
    entry (location, type, table, read-only, complete referenced storage
    profile definition) changes the digest. This is the proposal's source-
    identity digest."""
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_digest(source_digest: str, storage_bindings: dict | None) -> str:
    """The EFFECTIVE source identity digest: the declared
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
    identity from the environment: endpoint/region variable
    values for used profiles, and the effective destination for postgres
    sources (the narrow repair, spec0035 §8 disposition) — no key/token
    reads, no network. S3 profile bindings keep their profile-name keys and
    record shape byte-for-byte; postgres bindings live under the collision-
    free ``postgres:<source-name>`` keys (colons cannot occur in either
    namespace: both are ``[a-z][a-z0-9_]*`` slugs). An unset connection_env
    is a visible prerequisite, never a corrupt declaration."""
    bindings: dict[str, dict] = {}
    for entry in resolved or []:
        if entry.get("type") == "postgres" and isinstance(entry.get("connection_env"), str):
            name = entry["name"]
            dsn = sources._resolve_dsn(
                Source(name=name, type="postgres", connection_env=entry["connection_env"])
            )
            bindings[f"postgres:{name}"] = sources.postgres_binding(
                name, dsn, entry["connection_env"]
            )
            continue
        storage = entry.get("storage")
        if not isinstance(storage, dict) or isinstance(storage.get("name"), str) is False:
            continue
        name = storage["name"]
        if name in bindings:
            continue
        try:
            profile = sources.profile_from_identity(name, storage)
            bindings[name] = sources.resolve_binding(profile).record()
        except ValueError as exc:  # spec 0040 §3.4: name the owning source
            raise ValueError(f"source {entry.get('name')!r}: {exc}") from None
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


def identity_registry(resolved: list[dict], bindings: dict | None = None) -> Registry:
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
    # Frozen postgres destinations route by their namespaced key (spec 0025
    # §4 disposition in spec0035 §8): the approval/admission record's
    # ``postgres:<source-name>`` entries pin each source's effective target
    # so plan() verifies-and-attaches exactly the checked destination. S3
    # profile keys and records pass through untouched.
    pg_frozen: dict[str, dict] = {}
    for entry in resolved:
        if entry.get("type") == "postgres" and entry.get("connection_env"):
            record = (bindings or {}).get(f"postgres:{entry['name']}")
            if record is not None:
                pg_frozen[entry["name"]] = record
    return Registry(
        sources=objects,
        path=None,
        storages=storages or None,
        bindings=frozen or None,
        connection_bindings=pg_frozen or None,
    )


# ------------------------------------------------------------- Git-mode propose


def source_entry(
    target: str,
    *,
    name: str | None = None,
    type: str | None = None,  # noqa: A002 — the CLI flag name
    storage: str | None = None,
    table: str | None = None,
) -> dict:
    """One registry-shaped source entry for ``add <path|url|dsn>`` (spec 0040 §3.1.2).
    Credential-free by construction: an inline connection string — with or without
    credentials — is refused, naming the ``connection_env`` form (ADR-0010). For a
    ``--type postgres`` source the target is the NAME of the environment variable
    that holds the DSN."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("add needs a path, URL or (for postgres) an environment variable name")
    if sources.DSN_RE.match(target) or sources._DSN_PASSWORD_RE.search(target):
        raise ValueError(
            "add never accepts an inline connection string: declare a postgres source "
            "with --type postgres and the NAME of the environment variable that holds "
            "the DSN (connection_env, ADR-0010); the DSN itself stays in the environment"
        )
    if type is None:
        suffix = Path(target.split("?", 1)[0]).suffix.lower().lstrip(".")
        type = {"db": "sqlite", "sqlite3": "sqlite", "ddb": "duckdb"}.get(suffix, suffix)
        if type not in sources.SOURCE_TYPES:
            raise ValueError(
                f"cannot infer a source type from {target!r} — pass --type "
                f"({', '.join(sources.SOURCE_TYPES)})"
            )
    if name is None:
        stem = re.sub(r"[^a-z0-9_]+", "_", Path(target).stem.lower()).strip("_") or "source"
        name = stem if stem[0].isalpha() else f"s_{stem}"
    entry: dict = {"name": name, "type": type}
    if type == "postgres":
        entry["connection_env"] = target
    else:
        entry["path"] = target
    if table is not None:
        entry["table"] = table
    if storage is not None:
        entry["storage"] = storage
    return entry


def add_sources(
    project: str | Path,
    expected: draft.Expected,
    sources_entries: list[dict] | tuple[dict, ...],
    storages: dict | None = None,
) -> dict:
    """Append validated typed source entries — plus optional named storage
    profile definitions — to the ACTIVE DRAFT's registry (``ariadne.yaml``) and
    return the digest of the candidate's full RESOLVED identity plus its precise
    resolved locations — never opening anything. ``expected=None`` is the first
    write that creates the draft (and leaves nothing behind when it refuses).
    Entries and profiles are credential-free data validated by the shared registry
    rules — the WHOLE merged candidate is validated before anything is committed.
    A name already in the candidate registry is refused (append, never overwrite).
    New profiles append; an identical existing profile is reused; a conflicting
    replacement refuses, leaving the candidate untouched. Nothing here approves:
    the candidate cannot grant itself access, and the grant is the human-only
    approval (spec 0040 §3.4)."""
    project = Path(project).resolve()
    if not isinstance(sources_entries, (list, tuple)):
        raise ValueError("typed source entries must be a list of registry-shaped mappings")
    entries: list[dict] = []
    for entry in sources_entries:
        if not isinstance(entry, dict):
            raise ValueError(f"a typed source entry must be a mapping, got {type(entry).__name__}")
        entries.append(dict(entry))
    new_profiles = sources.validate_storages(storages, "the source proposal")

    def op(proposal: str, current: str) -> dict:
        blob = proposals._read_blob(project, current, "ariadne.yaml")
        if blob is None:
            doc: dict = {}
        else:
            doc = yaml.safe_load(blob.decode("utf-8")) or {}
            if not isinstance(doc, dict):
                raise ValueError(f"the draft's ariadne.yaml at {current[:12]} is not a mapping")
        existing = doc.get("sources") or []
        if not isinstance(existing, list):
            raise ValueError("the draft's ariadne.yaml 'sources' is not a list")
        taken = {entry.get("name") for entry in existing if isinstance(entry, dict)}
        clashes = sorted(
            cast(str, entry["name"]) for entry in entries if entry.get("name") in taken
        )
        if clashes:
            raise ValueError(
                f"source name(s) {clashes} already exist in the draft registry — a "
                "source proposal appends, it never overwrites an existing entry"
            )
        merged_storages = dict(doc.get("storages") or {})
        for storage_name, profile in new_profiles.items():
            declared = merged_storages.get(storage_name)
            if declared is not None and declared != profile.identity():
                raise ValueError(
                    f"storage profile {storage_name!r} already exists in the draft registry "
                    "with a DIFFERENT definition — a conflicting replacement is "
                    "refused; propose a new name or resend the identical definition "
                    "(spec 0025 §5); nothing was written"
                )
            merged_storages[storage_name] = profile.identity()
        doc["sources"] = [*existing, *entries]
        if merged_storages:
            doc["storages"] = merged_storages
        # The WHOLE merged candidate validates BEFORE the revision-checked edit
        # commits anything.
        sources.validate_registry_doc(doc, "the source proposal", project)
        return proposals.edit_proposal(
            project, proposal, current, "ariadne.yaml", yaml.safe_dump(doc, sort_keys=False)
        )

    edited, view = draft.mutate(project, expected, op)
    resolved_identity, digest = candidate_sources(project, edited["revision"])
    if resolved_identity is None:  # unreachable: the merge just added entries
        raise ValueError("the registry edit committed no source entries")
    return {
        "proposal": edited["proposal"],
        "revision": edited["revision"],
        "changed": edited["changed"],
        "source_digest": digest,
        "sources": resolved_identity,
        "draft": view,
    }


# spec 0040 §3.1 "Changing one declared source": the only settable fields, per type.
_CHANGE_FIELDS = {"postgres": frozenset({"connection_env"})}


def change_source(
    project: str | Path, expected: draft.Expected, name: object, changes: object
) -> dict:
    """Change ONE existing source's declaration in the active draft (spec 0040 §3.1):
    set only the supplied ``path``/``connection_env``/``storage`` fields valid for its
    type (``storage: null`` removes the binding); everything else stays. Same pin,
    whole-registry validation and commit as :func:`add_sources`; opens and grants
    nothing. Refuses an unknown source, an empty or no-op change and disallowed
    fields, leaving no edit and no newly opened draft."""
    project = Path(project).resolve()
    if not isinstance(name, str) or not name:
        raise ValueError("source_change needs the name of an existing source")
    if not isinstance(changes, dict):
        raise ValueError("source_change 'changes' must be a mapping of fields to set")
    if not changes:
        raise ValueError(f"source_change for {name!r} is empty: no change requested")

    def op(proposal: str, current: str) -> dict:
        blob = proposals._read_blob(project, current, "ariadne.yaml")
        doc = (yaml.safe_load(blob.decode("utf-8")) or {}) if blob is not None else {}
        if not isinstance(doc, dict):
            raise ValueError(f"the draft's ariadne.yaml at {current[:12]} is not a mapping")
        existing = doc.get("sources") or []
        if not isinstance(existing, list):
            raise ValueError("the draft's ariadne.yaml 'sources' is not a list")
        index = next(
            (i for i, e in enumerate(existing) if isinstance(e, dict) and e.get("name") == name),
            None,
        )
        if index is None:
            raise ValueError(f"no such source {name!r} in the draft registry — nothing was written")
        entry = dict(existing[index])
        kind = str(entry.get("type"))
        allowed = _CHANGE_FIELDS.get(
            kind,
            frozenset({"path", "storage"} if kind in sources.STORAGE_SOURCE_TYPES else {"path"}),
        )
        disallowed = sorted(set(changes) - allowed)
        if disallowed:
            raise ValueError(
                f"source_change field(s) {disallowed} not allowed for {entry.get('type')} "
                f"source {name!r}; allowed: {sorted(allowed)} — nothing was written"
            )
        for key, value in changes.items():
            if key == "storage" and value is None:
                entry.pop("storage", None)
            else:
                entry[key] = value
        before = _resolved_entries(
            *sources.validate_registry_doc(doc, "the draft registry", project)
        )
        doc["sources"] = [*existing[:index], entry, *existing[index + 1 :]]
        after = _resolved_entries(*sources.validate_registry_doc(doc, "the source change", project))
        if after == before:
            raise ValueError(
                f"source_change leaves {name!r} unchanged: no change to its resolved "
                "declaration — nothing was written"
            )
        return proposals.edit_proposal(
            project, proposal, current, "ariadne.yaml", yaml.safe_dump(doc, sort_keys=False)
        )

    edited, view = draft.mutate(project, expected, op)
    resolved_identity, digest = candidate_sources(project, edited["revision"])
    return {
        "proposal": edited["proposal"],
        "revision": edited["revision"],
        "changed": edited["changed"],
        "source_digest": digest,
        "sources": resolved_identity,
        "draft": view,
    }


def propose_sources(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    sources_entries: list[dict] | tuple[dict, ...],
    storages: dict | None = None,
) -> dict:
    """The proposal-addressed form of :func:`add_sources` for the library callers
    that already hold the draft's proposal and candidate revision (the workspace
    adapter, setup). The proposal must be the ACTIVE draft's."""
    expected = draft.active_expected(project, proposal, expected_revision)
    result = add_sources(project, expected, sources_entries, storages)
    result.pop("draft")
    return result


# ----------------------------------------------- operator-owned source grants


# Read-only diagnosis (``ariadne status``): a grants read must not create the lock file. Set only
# by status; when set and no lock file exists yet, no writer has ever run (a writer creates it
# before any journal), so the journal check and the read need no lock.
DIAGNOSIS = contextvars.ContextVar("ariadne_grants_diagnosis", default=False)


class SourceApprovalPending(ValueError):
    """A source approval is unfinished or interrupted: grants authorize nothing until it
    finishes or is recovered (spec 0040 §3.4.2.5)."""


_PENDING_MESSAGE = (
    "a source approval is in progress or was interrupted — no grant authorizes a read until it "
    "finishes or is recovered; run any 'ariadne draft' command (e.g. 'ariadne draft status') "
    "to recover it, then retry; nothing was opened"
)


def _load_grants(project: Path, *, _held: bool = False) -> list[dict]:
    """The append-only grant list ([] when none exist). A reader takes ``grants.lock`` LAST,
    refuses while the source-approval journal exists (never falling back to the file) and holds
    the lock only for that check and the read. ``_held`` is for code that already holds
    ``grants.lock`` inside the approval transaction. A non-regular, unreadable or malformed
    file is a human-resolution failure — never silently reset."""
    project = Path(project)
    if _held:
        return _read_grants_file(project)
    if not (project / proposals.ARIADNE_STATE_DIR).is_dir():
        return []  # an absent state directory has no grants and no pending journal; diagnosis
        # never bootstraps state (no lock file is created)
    if DIAGNOSIS.get() and not (project / draft.GRANTS_LOCK_REL).exists():
        if draft.source_txn_pending(project):
            raise SourceApprovalPending(_PENDING_MESSAGE)
        grants = _read_grants_file(project)
        # re-sample AFTER the unlocked read: if the first lock appeared (a writer started) or a
        # journal/marker exists, the unlocked read may be an uncommitted grant — never call it
        # current; fall through to the normal locked path (which refuses while pending)
        if not (project / draft.GRANTS_LOCK_REL).exists() and not draft.source_txn_pending(project):
            return grants
    with draft.grants_lock(project):
        if draft.source_txn_pending(project):
            raise SourceApprovalPending(_PENDING_MESSAGE)
        return _read_grants_file(project)


def _read_grants_file(project: Path) -> list[dict]:
    path = project / SOURCE_GRANTS_REL
    entry = proposals._lstat(path)
    if entry is None:
        return []
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"{path}: refusing a non-regular source-grants file — operator-owned "
            "state, inspect it by hand"
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path}: unreadable source grants ({exc}) — this needs human "
            "resolution, not an agent reset"
        ) from None
    grants = doc.get("grants") if isinstance(doc, dict) else None
    if not isinstance(grants, list) or not all(
        isinstance(g, dict) and isinstance(g.get("source"), dict) for g in grants
    ):
        raise ValueError(
            f"{path}: malformed source grants — this needs human resolution, not an agent reset"
        )
    return grants


def _store_grants(project: Path, grants: list[dict]) -> None:
    """Persist the grant list atomically (tmp + os.replace) and durably. Inside a source
    approval the journal (not this function) owns rollback."""
    path = project / SOURCE_GRANTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "grants": grants}, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    proposals._fsync_path(path.parent)


def record_grants(
    project: str | Path,
    resolved: list[dict],
    source_digest: str,
    *,
    by: str,
    generation: int | None = None,
    _lock_held: bool = False,
    _grants_held: bool = False,
) -> dict:
    """HUMAN-ONLY library call (never an MCP/Agent tool; the approval command and the
    workspace's browser-reviewed source request call it): append one grant per
    source of the EXACT resolved identity, each carrying its credential-free
    effective binding (profile endpoint/region, postgres destination), attribution
    and time. Requires the 64-hex resolved digest the caller displayed (a mismatch
    refuses before any write). Missing endpoint/region values are a visible
    prerequisite — it refuses naming the variable, it never guesses. A grant is not
    a release activation: it authorizes bounded reads for authoring only."""
    project = Path(project).resolve()
    if not isinstance(source_digest, str) or not _HEX64_RE.fullmatch(source_digest):
        raise ValueError("the source digest must be the 64-hex sha256 of the resolved identity")
    if resolved_digest(resolved) != source_digest:
        raise ValueError(
            f"source digest mismatch: the identity resolves to {resolved_digest(resolved)}, "
            f"not {source_digest} — a grant binds the exact resolved identity"
        )
    if not isinstance(by, str) or not by.strip():
        raise ValueError("a source grant needs an attribution label")
    bindings = storage_bindings_from_identity(resolved)  # refuses before any write
    now = datetime.now(UTC).isoformat(timespec="seconds")
    new = []
    for entry in resolved:
        own = storage_bindings_from_identity([entry])
        storage = entry.get("storage")
        new.append(
            {
                "source": entry,
                "source_digest": resolved_digest([entry]),
                "binding": own.get(storage["name"]) if isinstance(storage, dict) else None,
                "postgres_binding": own.get(f"postgres:{entry['name']}"),
                "by": by.strip(),
                "at": now,
                "generation": generation,
            }
        )
    lock = (
        nullcontext()
        if _lock_held
        else proposals._file_lock(project / proposals.LOCKS_REL / "project.lock")
    )
    with lock:
        # the standalone (non-transactional) call serializes with readers on grants.lock; inside
        # the approval transaction the caller already holds it
        with nullcontext() if _grants_held else draft.grants_lock(project):
            grants = _load_grants(project, _held=True)
            if not _grants_held and draft.source_txn_pending(project):
                raise SourceApprovalPending(_PENDING_MESSAGE)
            for number, grant in enumerate(new, start=len(grants) + 1):
                grant["seq"] = number
            _store_grants(project, [*grants, *new])
    return {
        "source_digest": source_digest,
        "approval_digest": approval_digest(source_digest, bindings),
        "storage_bindings": bindings,
        "grants": len(new),
        "path": str(project / SOURCE_GRANTS_REL),
    }


def grant_candidate(
    project: str | Path, proposal: str, revision: str, source_digest: str, *, by: str
) -> dict:
    """HUMAN-ONLY library call: grant the EXACT resolved identity of the active
    draft's current candidate (the browser-reviewed workspace source request uses
    it after its reviewer capability and one-use action). Requires the exact
    candidate revision and the digest it resolves to."""
    project = Path(project).resolve()
    expected = draft.active_expected(project, proposal, revision)
    generation = expected[0] if expected is not None else None
    record = proposals._load_record(project, draft.proposal_of(project, expected))
    if record["candidate_revision"] != revision:
        raise ValueError(f"stale revision: the draft is at {record['candidate_revision']}")
    resolved, digest = candidate_sources(project, revision)
    if resolved is None:
        raise ValueError("the draft declares no source entries — there is nothing to grant")
    if digest != source_digest:
        raise ValueError(
            f"source digest mismatch: the candidate registry at {revision[:12]} resolves "
            f"to {digest}, not {source_digest} — a grant binds the exact resolved identity"
        )
    result = record_grants(project, resolved, source_digest, by=by, generation=generation)
    return {**result, "proposal": proposal, "revision": revision, "sources": resolved}


def _entry_bindings(entry: dict) -> dict:
    return storage_bindings_from_identity([entry])


def _covering(project: Path, entry: dict, bindings: dict) -> dict | None:
    """The record that grants ``entry`` under its CURRENT effective ``bindings``:
    the served release's bound identity, else the newest grant — or None."""
    from ariadne import admission  # lazy: admission imports proposals at load

    served = admission.load_current(project)
    if served is not None and entry in (served.get("sources") or []):
        recorded = served.get("storage_bindings") or {}
        if all(recorded.get(key) == value for key, value in bindings.items()):
            return {"at": served.get("admitted_at"), "by": "served release"}
    for grant in reversed(_load_grants(project)):
        if grant["source"] != entry:
            continue
        own = {}
        storage = entry.get("storage")
        if isinstance(storage, dict) and grant.get("binding") is not None:
            own[storage["name"]] = grant["binding"]
        if grant.get("postgres_binding") is not None:
            own[f"postgres:{entry['name']}"] = grant["postgres_binding"]
        if own == bindings:
            return grant
    return None


def _effective_grant(
    project: Path,
    resolved: list[dict] | None,
    digest: str | None,
    proposal: str,
    revision: str,
) -> dict:
    """The effective grant for the candidate's CURRENT identity (spec 0040 §3.4.4):
    every source must be bound by the served release or carry a source grant for
    its exact identity under the binding the environment resolves NOW (spec 0025
    §4: an endpoint change needs its own grant). Offline: no key/token reads, no
    network. The record carries the FROZEN bindings for reconstruction."""
    bindings = storage_bindings_from_identity(resolved)
    effective = approval_digest(digest or "", bindings) if digest else digest
    approved_at = ""
    missing = []
    for entry in resolved or []:
        try:
            covering = _covering(project, entry, _entry_bindings(entry))
        except SourceApprovalPending as exc:
            raise SourceApprovalPending(f"{exc} (checking source {entry['name']!r})") from exc
        if covering is None:
            missing.append(entry["name"])
        else:
            approved_at = max(approved_at, str(covering.get("at") or ""))
    if missing:
        raise ValueError(
            f"the draft's source registry (candidate {revision[:12]}) resolves to source "
            f"identity {digest} with effective storage binding {effective}; source(s) "
            f"{missing} carry NO grant for that exact identity — a new source or a "
            "changed path, endpoint or destination needs its own source approval "
            "(spec 0040 §3.4: run 'ariadne approve' on a sources-only draft); nothing "
            "was opened"
        )
    return {
        "sources": resolved,
        "source_digest": digest,
        "storage_bindings": bindings,
        "approval_digest": effective,
        "approved_at": approved_at,
    }


def approval_state(project: Path, resolved: list[dict] | None, digest: str | None) -> dict:
    """The OFFLINE effective grant state of one resolved identity (spec 0025 §4):
    ``current``: every source is granted under the binding the environment
    resolves now. ``not-current``: only a different binding of a declared source
    was ever granted. ``unresolved``: a required endpoint/region value is unset — a
    visible prerequisite, never a corrupt declaration. ``absent``: otherwise."""
    project = Path(project)
    try:
        bindings = storage_bindings_from_identity(resolved)
    except ValueError as exc:
        return {"state": "unresolved", "reason": str(exc), "approved": False}
    effective = approval_digest(digest or "", bindings) if digest else None
    entries = resolved or []
    try:
        return _approval_state_reading(project, entries, digest, effective, bindings)
    except SourceApprovalPending as exc:  # a display path reports; it never crashes or reads
        return {
            "state": "in-progress",
            "approved": False,
            "reason": str(exc),
            "approval_digest": effective,
            "storage_bindings": bindings,
        }


def _approval_state_reading(project, entries, digest, effective, bindings) -> dict:
    if effective is not None and all(
        _covering(project, entry, _entry_bindings(entry)) is not None for entry in entries
    ):
        return {
            "state": "current",
            "approved": True,
            "approval_digest": effective,
            "storage_bindings": bindings,
        }
    known = [g["source"] for g in _load_grants(project)]
    historical = bool(digest and any(entry in known for entry in entries))
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
    selector: tuple[str, str] | None = None,
    expected_revision: str | None = None,
) -> dict:
    """The measured inputs of one proposal (plan §2 ``inputs``): the profile
    of the APPROVED resolved registry identity — compared with the operator's
    approval BEFORE any source access, so an unapproved or changed entry is an
    explicit error and the shared connection builder is never called for it —
    plus source-linked converted evidence for the referenced documents (the
    operator's HOST-root document boundary; a candidate's committed
    ``documents:`` section is never consulted) and the candidate's Seed Notes
    evidence from the recorded candidate revision. Bounded by the shared
    input-evidence limits; the profiling run itself is bounded by the
    HOST-owned profiling ceilings: one total finite time budget
    across setup/sampling/statistics/FK and a complete-profile payload
    ceiling, with a request sample_rows never above the host ceiling.
    Digests are stable across calls (same bytes, same digest)."""
    project = Path(project).resolve()
    record = proposals._load_record(project, proposal)
    revision = record["candidate_revision"]
    if expected_revision is not None and revision != expected_revision:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {revision[:12]}, "
            f"expected {expected_revision[:12]}"
        )
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
        # the HOST-owned profiling ceilings govern every
        # agent-facing profiling run. Approval still precedes everything; the
        # request-ceiling check refuses BEFORE any source access, and the run
        # draws one total finite time budget under the complete-payload bound.
        limits = authoring_inputs.project_profiling_limits(project)
        if sample_rows is not None and sample_rows > limits["sample_rows"]:
            raise ValueError(
                f"sample_rows={sample_rows} exceeds the operator profiling ceiling "
                f"{limits['sample_rows']} — a request cannot exceed the host profiling "
                "ceilings (spec0035 §8); nothing was opened"
            )
        profile = profiler.profile(
            registry=identity_registry(approval["sources"], approval.get("storage_bindings")),
            sample_rows=sample_rows,
            selector=selector,
            budget=execution.DeadlineBudget(limits["execution_seconds"]),
            payload_bytes=limits["response_bytes"],
            locked=True,
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
