"""Shared Proposals: local Git authoring identities (spec 2026-10-02-0009 §2
"Shared Proposals"/§4, ADR-0016, plan §2 "Project storage and authority").

Two responsibilities live here so Authoring (:mod:`ariadne.authoring`) and
Query (:mod:`ariadne.query`) share ONE implementation:

- the local Git proposal lifecycle over the DATA PROJECT's repository: one
  fixed project, system-generated proposal IDs/branches
  (``ariadne/proposal/<id>``), one worktree per active writer under the
  ignored operator-owned ``.ariadne/`` state dir (``worktrees/<id>/``,
  ``proposals/<id>.json`` records), revision-checked complete-artifact edits,
  the finalize pass's generated-artifact commit (issue #36/G4), the COMPLETE
  candidate-scope snapshot walker behind exact-final-commit
  validation/review, and the separately stored validation evidence
  (``validation/<id>/<commit>.json`` — operator-owned, never committed) plus
  the shared pre-write content boundary (payload bounds + credential classes);

Git discipline (plan §2): fixed argv through :mod:`subprocess`, never a shell,
never model-supplied Git commands; IDs, commit revisions and artifact names are
validated BEFORE dispatch so paths/refs can never become options; the
``--`` separator is always used; missing Git, missing operator Git identity,
dirty/inconsistent worktrees and command failures are explicit errors; global
Git configuration is never altered (the repo-LOCAL ``.git/info/exclude``
records the ignored state dir); no network operation exists here. State
transitions persist durably (tmp + fsync + atomic rename) and an interrupted
transition — a worktree/branch that no longer matches its recorded candidate —
blocks every further mutation for HUMAN resolution: evidence (worktree, branch,
record) is preserved, never auto-reset (spec §4).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.context import _load, _quality_profile_errors, core_body_sections
from ariadne.ingest import _SECRET_PATTERNS
from ariadne.lumio_context import knowledge_path  # pyright: ignore[reportMissingImports]
from ariadne.sources import _DSN_PASSWORD_RE

# Operator-owned project state, ignored via the repo-LOCAL exclude file: the
# caller never provides (nor sees) worktree paths or operational state files —
# locations derive from the fixed project and the system-generated proposal ID.
ARIADNE_STATE_DIR = Path(".ariadne")
PROPOSALS_REL = ARIADNE_STATE_DIR / "proposals"  # <id>.json records
WORKTREES_REL = ARIADNE_STATE_DIR / "worktrees"  # <id>/ per active writer
LOCKS_REL = ARIADNE_STATE_DIR / "locks"  # <id>.lock per proposal + project.lock
VALIDATION_REL = ARIADNE_STATE_DIR / "validation"  # <id>/<commit>.json evidence
PROPOSAL_BRANCH_PREFIX = "ariadne/proposal/"  # ariadne/proposal/<id>

# A generated proposal ID: lowercase slug, never option-shaped (no leading '-').
_PROPOSAL_ID_RE = re.compile(r"p-[0-9a-f]{14}-[0-9a-f]{6}")
# Commit revisions cross the API (base/expected/candidate): hex SHAs only.
_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")

# Complete artifact edits and revision-specific reads have explicit bounds.
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
READ_PART_CHARS = 20_000

_GENERATED_FILES = frozenset({"index.md", "log.md"})

# Named env-style credential assignments the URL-password rule misses (the
# value is never echoed; the same-line ``=`` keeps prose that merely MENTIONS
# the variable from matching). Shared with proposal artifact edits.
_AWS_ASSIGNMENT_RE = re.compile(
    r"\b(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)[ \t]*=[ \t]*\S+"
)

# The fresh-setup guidance for a retired-format project (spec0035 §6/AC10):
# the new release supports only the native knowledge/ contract — an old
# standalone project refuses before any mutation and is never reset or
# converted; its files and snapshots stay untouched.
_UNSUPPORTED_PROJECT_GUIDANCE = (
    "This release supports only the native knowledge/ contract (spec0035): the "
    "retired standalone context_layer/ path is not supported and is never "
    "converted, activated or reset. Create a FRESH project with 'ariadne-init "
    "<target> --namespace <namespace> --private-profile <profile>' (explicit "
    "selections; Git must already exist) and deliberately re-onboard the "
    "needed content into it through normal authoring and review; old approvals "
    "do not transfer. Nothing was read, written or modified here."
)

# The fail-closed instruction for an interrupted Git proposal transition
# (spec §4): name the evidence, forbid any agent reset or deletion.
_HUMAN_RESOLUTION = (
    " — interrupted Git proposal transition, human resolution required: KEEP the "
    "worktree under .ariadne/worktrees/, the branch ariadne/proposal/<id> and "
    ".ariadne/proposals/<id>.json exactly as they are, compare them, and resolve by "
    "hand; no agent command resets, deletes or merges them"
)

# Every core-authored transition commit (the edit seam, the finalize pass, the
# onboarding initial revision) carries this fixed message prefix. The proposal
# record — written AFTER the commit — is the only authority that a core
# transition COMPLETED: a core-authored commit the record never saw is the
# signature of an interrupted transition.
_CORE_COMMIT_PREFIX = "ariadne: "


class GitError(RuntimeError):
    """A Git-level blocker (missing git, missing identity, failed command) —
    actionable text, never a silent fallback (spec §4: report the actual
    blocker and preserve evidence and prior state)."""


# ------------------------------------------------------------- git plumbing


def _git(
    argv: list[str], cwd: Path, *, check: bool = True, text: bool = True
) -> subprocess.CompletedProcess:
    """Run ONE fixed-argv git command in ``cwd`` — no shell, no network
    subcommand is ever dispatched from here. Missing git and command failures
    are explicit errors carrying git's own stderr."""
    try:
        proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=text)
    except FileNotFoundError:
        raise GitError(
            "git is not available — Git-backed authoring proposals require a local "
            "git executable on PATH (local Git only; no network operations exist)"
        ) from None
    if check and proc.returncode != 0:
        raw = (proc.stderr or b"").decode("utf-8", "replace") if not text else proc.stderr
        raise GitError(f"git {' '.join(argv)} failed in {cwd}: {raw.strip()}")
    return proc


def _require_repo(project: Path) -> None:
    """The fixed data project must already be a Git repository (the human
    owns ``git init``; Ariadne never creates or reinitializes one), and it must
    BE that repository's top-level working directory: a mere subdirectory of
    an enclosing repository would carry proposal worktrees/branches of the
    ENCLOSING repo while identities resolve from its root — refused before any
    state exists."""
    proc = _git(["rev-parse", "--show-toplevel"], project, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise GitError(
            f"{project} is not a Git repository — Git-backed authoring proposals "
            "use the data project's own repository (run git init there first)"
        )
    if Path(proc.stdout.strip()).resolve() != project.resolve():
        raise GitError(
            f"{project} is not the top-level working directory of its Git repository "
            f"(git resolves it to {proc.stdout.strip()}) — Git-backed authoring "
            "proposals operate on the data project's own repository root; start "
            "from the repository's top-level directory instead of a subdirectory"
        )


def _require_git_identity(project: Path) -> None:
    """A commit needs an operator Git identity. Repo-local or the standard
    GIT_AUTHOR_* environment overrides are honoured; a missing identity is an
    explicit error, and this tool NEVER writes Git configuration itself
    (global config is untouchable here by construction)."""
    if os.environ.get("GIT_AUTHOR_NAME") and os.environ.get("GIT_AUTHOR_EMAIL"):
        return
    for key in ("user.name", "user.email"):
        proc = _git(["config", "--get", key], project, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise GitError(
                f"no operator Git identity: 'git config {key}' is unset in {project} — "
                "set a repo-local identity (git config user.name/user.email, or export "
                "GIT_AUTHOR_NAME/GIT_AUTHOR_EMAIL); ariadne never writes Git "
                "configuration itself"
            )


def _ensure_state_ignored(project: Path) -> None:
    """Record ``.ariadne/`` in the repo-LOCAL exclude file (never global
    config, never a tracked .gitignore write): operator-owned state must never
    become candidate content (plan §2)."""
    git_dir = _git(["rev-parse", "--absolute-git-dir"], project).stdout.strip()
    exclude = Path(git_dir) / "info" / "exclude"
    marker = f"/{ARIADNE_STATE_DIR.as_posix()}/"
    if exclude.is_file():
        if any(line.strip() == marker for line in exclude.read_text(encoding="utf-8").splitlines()):
            return
        text = exclude.read_text(encoding="utf-8")
    else:
        text = ""
    exclude.parent.mkdir(parents=True, exist_ok=True)
    suffix = "" if (not text or text.endswith("\n")) else "\n"
    exclude.write_text(f"{text}{suffix}{marker}\n", encoding="utf-8")


def _current_head(project: Path) -> str | None:
    """The repository's HEAD commit (None while the initial revision does not
    exist yet — the empty-project onboarding case, spec §3)."""
    proc = _git(["rev-parse", "--verify", "HEAD"], project, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _validate_revision(project: Path, revision: str) -> str:
    """Validate one caller-supplied commit revision BEFORE any dispatch
    (hex SHA only — it can never become a git option) and resolve it to the
    full SHA; an unknown revision is an explicit error."""
    if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
        raise ValueError(
            f"invalid revision {revision!r}: a commit SHA (7–40 hex characters) is required"
        )
    proc = _git(["rev-parse", "--verify", f"{revision}^{{commit}}"], project, check=False)
    if proc.returncode != 0:
        raise ValueError(
            f"revision {revision} is not a commit in this repository — name a base "
            "revision from the project's own history"
        )
    return proc.stdout.strip()


def _lstat(path: Path) -> os.stat_result | None:
    """The entry's own status, symlinks NOT followed (None = nothing claims
    the name, unlike Path.exists which follows — a dangling link claims it)."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _refuse_symlinked_component(root: Path, rel: Path | PurePosixPath) -> None:
    """Refuse before any write when a component of an operator-state path is a
    symlink (a pre-planted link must never redirect state or artifact writes)."""
    path = root
    for part in rel.parts:
        path = path / part
        entry = _lstat(path)
        if entry is not None and stat.S_ISLNK(entry.st_mode):
            raise ValueError(
                f"{path}: refusing a symlinked ariadne state component — the "
                "operator-owned state dir stays a plain project directory"
            )


@contextmanager
def _file_lock(lock_path: Path):
    """ONE interprocess flock per file (the authoring bundle-lock discipline):
    competing writers serialize on it instead of corrupting proposal state; a
    crashed holder releases with its process. Symlinked lock files are refused."""
    entry = _lstat(lock_path)
    if entry is not None and stat.S_ISLNK(entry.st_mode):
        raise ValueError(
            f"{lock_path}: refusing a symlinked proposal lock file — the proposal "
            "lock stays a plain state file"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _fsync_path(path: Path) -> None:
    """Sync one file or directory entry to stable storage; any OSError
    propagates so the transition fails closed (authoring._fsync_path)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _store_record(project: Path, record: dict) -> None:
    """Persist one proposal record atomically (tmp + os.replace) and DURABLY:
    file data synced before the rename, the directory entry after — an
    interrupted store can never leave an empty record next to the worktree it
    must describe (authoring._store_bundle_state discipline)."""
    path = project / PROPOSALS_REL / f"{record['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_path(path.parent)


def _load_record(project: Path, proposal: str) -> dict:
    """The persisted proposal record. The ID's system-generated grammar is
    enforced BEFORE it ever reaches a filesystem path or a lock name (it can
    never traverse or become an option); an unknown ID, a record from ANOTHER
    project, or a corrupt record is an explicit identity error — never a guess."""
    if not isinstance(proposal, str) or not _PROPOSAL_ID_RE.fullmatch(proposal):
        raise ValueError(
            f"invalid proposal ID {proposal!r}: proposal IDs are system-generated "
            "(p-<timestamp>-<hex>, returned by start_proposal) — start one first"
        )
    path = project / PROPOSALS_REL / f"{proposal}.json"
    entry = _lstat(path)
    if entry is None:
        raise ValueError(
            f"no proposal {proposal!r} in this project ({project}) — the ID is unknown "
            "here or belongs to another project; nothing was read or written"
        )
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"{path}: refusing a non-regular proposal record — this needs human "
            "resolution, not an agent reset"
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path}: unreadable proposal record ({exc}) — this needs human resolution, "
            "not an agent reset"
        ) from None
    required = {"id", "project", "base_revision", "candidate_revision", "branch"}
    if not isinstance(record, dict) or not required <= set(record):
        raise ValueError(
            f"{path}: malformed proposal record — this needs human resolution, not an agent reset"
        )
    if record["id"] != proposal or record["project"] != str(project):
        raise ValueError(
            f"no proposal {proposal!r} in this project ({project}) — the record "
            f"belongs to {record.get('project')!r}; nothing was read or written"
        )
    return record


# ------------------------------------------------- the shared content boundary


def check_edit_keys(payload: dict, allowed: frozenset[str]) -> None:
    """The discriminated-edit shape: exactly the documented fields. A missing
    field is an actionable error; an EXTRA field is a smuggled claim — approval
    and attestation are system-owned, so callers can never add them (spec §4:
    agents cannot author system-owned approval or attestation claims)."""
    if not isinstance(payload, dict):
        raise ValueError(f"an edit/identity must be a JSON object, got {type(payload).__name__}")
    missing = sorted(allowed - set(payload))
    if missing:
        raise ValueError(f"the {payload.get('kind')!r} edit is missing required field(s) {missing}")
    extra = sorted(set(payload) - allowed)
    if extra:
        raise ValueError(
            f"the {payload.get('kind')!r} edit carries unsupported field(s) {extra} — "
            "approval/attestation claims and arbitrary metadata are system-owned; an "
            "edit carries only its documented fields"
        )


# Git pathspec magic an artifact name must never carry: the fnmatch
# wildcards (* ? [) would let one "name" match OTHER artifacts as a pathspec,
# ':' is the pathspec-magic prefix (and the revision:path separator used by
# reads). Rejected centrally so a name can never regain pathspec semantics.
_PATHSPEC_MAGIC_CHARS = "*?[:"


def check_artifact_name(name: object, *, what: str) -> str:
    """One artifact name (model/page file stem) validated BEFORE any Git
    dispatch: a plain POSIX filename that cannot traverse (no '/', '..', NUL),
    be absolute, become a git option (leading '-'), hide a generated name, or
    carry pathspec magic (*, ?, [, :) — a wildcard "name" would match other
    artifacts at the candidate gate. Names are converted to allowed artifact
    paths only by the layer resolvers."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"{what} must be a non-empty string, got {name!r}")
    if (
        name in (".", "..")
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or name.startswith("-")
        or name.startswith(".")
        or PurePosixPath(name).name != name
        or any(ch in name for ch in _PATHSPEC_MAGIC_CHARS)
    ):
        raise ValueError(
            f"{what} {name!r} is not a plain artifact filename — escaping, hidden, "
            "option-shaped and wildcard/pathspec-magic names are refused before "
            "any Git operation"
        )
    return name


# The native-profile trust/generated claim families (spec0029 §1.5 native
# metadata, mirrored onto ariadne_profile.native): stamped verification,
# attestation/attester facts, core-attached receipt summaries, the canonical
# resource binding and the generated ``ariadne`` schema/observations block
# are system-owned under the SAME inherited-verbatim rule as the outer
# frontmatter; the ``ariadne`` reference extension is the authored exception
# (the exact existing authored-Reference exception, mirrored at the kind).
_NATIVE_SYSTEM_CLAIM_KEYS = frozenset(
    {
        "verified",
        "generated",
        "stale_after",
        "attestation",
        "attester",
        "ariadne_evidence",
        "resource",
        "ariadne",
    }
)


def _literal(rel: str) -> str:
    """One artifact path as a LITERAL Git pathspec: the magic prefix pins
    exact-name semantics at the dispatch seam, so a validated path can never
    regain wildcard meaning even if a future validator regressed."""
    return f":(literal){rel}"


def refuse_generated(rel: str) -> None:
    """System-generated artifacts are never user-editable (spec §2: generated
    pages/indexes/log are service-owned; ADR-0013: attestation is owned by the
    deterministic finalize pass, never a caller)."""
    if PurePosixPath(rel).name in _GENERATED_FILES or "/computations/" in f"/{rel}":
        raise ValueError(
            f"{rel}: index.md, log.md and computations pages are system-generated "
            "(attestation is service-owned) — they are never user-editable in a proposal"
        )


# System-owned trust/lifecycle claim keys (ADR-0007 trust frontmatter the
# finalize pass stamps mechanically — verified history,
# generated/stale_after — plus the attestation/approval words of the edit
# envelope's smuggling rule): an edit may only RETAIN a claim inherited
# verbatim from the base revision, never introduce, change or remove one
# (spec §4). K1 (issue #41) extends the same seam to the CORE-OWNED generated
# facts of schema pages: the ``ariadne`` schema/observation block, the
# canonical ``resource`` binding AND the rendered core-owned body sections
# (the generated Schema/Observations/Schema history blocks) are regenerated
# by refresh_schema only — a complete page edit may carry them unchanged,
# never forge, change or drop them.
_SYSTEM_CLAIM_KEYS = frozenset(
    {
        "verified",
        "generated",
        "stale_after",
        "attester",
        "approved",
        "attested",
        "validated",
        "ariadne",
        "ariadne_evidence",  # core-attached verified receipt summaries
        "resource",
    }
)


def check_artifact_content(where: str, content: str) -> None:
    """The shared pre-write content boundary for Git proposal edits: an
    over-limit payload, an inline URL credential, a known secret-shape, or a
    named AWS assignment is refused BEFORE anything is written — the matched
    value is never echoed. Invalid/incomplete DRAFT content is allowed: artifact
    validation is a later gate (spec §3), identity and credentials are not."""
    if not isinstance(content, str):
        raise ValueError(f"{where} content must be a string")
    total = len(content.encode("utf-8"))
    if total > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"{where} is {total} bytes, over the {MAX_ARTIFACT_BYTES}-byte bound — "
            "reference evidence by resource instead of inlining it"
        )
    if match := _DSN_PASSWORD_RE.search(content):  # ADR-0010 credential shape
        raise ValueError(
            f"{where} carries inline URL credentials "
            f"({match.group(1)}***{match.group(3)}) — credentials never live in a "
            "proposed artifact"
        )
    for label, pattern in _SECRET_PATTERNS:  # ingest's classes, reused verbatim
        if pattern.search(content):
            raise ValueError(
                f"{where} appears to carry a {label} credential — credential-free "
                "artifacts only; the matched value is never echoed, remove it and retry"
            )
    if _AWS_ASSIGNMENT_RE.search(content):
        raise ValueError(
            f"{where} carries a named AWS credential assignment "
            "(AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN = value) — "
            "credential-free artifacts only; the matched value is never echoed"
        )


def _claim_map(rel: str, content: str) -> dict | None:
    """The STRUCTURED top-level claim mapping of one artifact body: the YAML
    frontmatter mapping of an OKF page, the top-level mapping of a ``.yml``
    artifact. None when the body carries no parseable mapping — invalid or
    incomplete DRAFT content stays allowed at this seam (spec §3)."""
    try:
        if PurePosixPath(rel).suffix == ".md":
            meta, _body = _load(content)
            return meta if isinstance(meta, dict) else None
        doc = yaml.safe_load(content)
        return doc if isinstance(doc, dict) else None
    except yaml.YAMLError:
        return None


def _refuse_forged_claims(rel: str, content: str, base_content: bytes | None) -> None:
    """The content half of the system-owned-claim boundary (spec §4: agents
    cannot author approval or attestation claims): structured trust claims the
    edit INTRODUCES or CHANGES versus the current candidate's bytes are
    refused BEFORE any write; claims inherited identically from the base stay
    allowed — and REMOVING claims, dropping the frontmatter entirely
    included, is the same forgery, never a bypass. K1 (issue #41) extends the
    same boundary to the RENDERED facts of an inherited generated page: its
    core-owned body sections (the generated Schema/Observations/Schema
    history blocks) may be carried unchanged, never changed, dropped or
    added; authored sections outside them stay editable. K2 (issue #42): the
    ``ariadne`` block of a REFERENCE page is the AUTHORED structured
    extension (aliases, exact bindings, mappings — spec 0010 §5), not a
    core-generated claim, so reference edits may author it; its shape and its
    refusal of approval/measurement claims belong to the shared per-type
    gate."""
    base_text = base_content.decode("utf-8", "replace") if base_content is not None else ""
    base = _claim_map(rel, base_text) or {}
    claims = _claim_map(rel, content) or {}
    system_keys = _SYSTEM_CLAIM_KEYS
    forged = sorted(
        key for key in system_keys & claims.keys() if key not in base or base[key] != claims[key]
    )
    # REMOVING a system-owned claim the base carried is the same forgery:
    # silently dropping the generated facts (issue #41 — a page whose
    # ``ariadne`` block or ``resource`` binding is stripped would fall out of
    # the refresh's resource identity)
    forged = sorted(set(forged) | (system_keys & base.keys() - claims.keys()))
    if forged:
        raise ValueError(
            f"the edit of {rel!r} introduces, changes or removes system-owned trust "
            f"claim(s) {forged} — approval and attestation are stamped by the "
            "deterministic finalize pass, and generated schema facts are "
            "regenerated by refresh_schema; never authored in a proposal — claims "
            "inherited unchanged from the base revision are allowed, remove the "
            "claim and retry"
        )
    # spec0035 C1 fix (F2): the producer-owned native profile carries the SAME
    # system-owned trust/generated claims under ``ariadne_profile.native`` —
    # the identical inherited-verbatim rule applies there, with the exact
    # existing authored-Reference exception mirrored at the native kind (the
    # ``ariadne`` reference extension stays caller-authorable). The SDK stays
    # independent: this is Core's own authorship boundary over its profile.
    native_system = _NATIVE_SYSTEM_CLAIM_KEYS
    proposed_profile = claims.get("ariadne_profile")
    base_profile = base.get("ariadne_profile")
    inherited_kind = None
    inherited_slot: dict = {}
    base_has_generated_block = False
    if isinstance(base_profile, dict):
        inherited_kind = base_profile.get("kind")
        base_native = base_profile.get("native")
        if isinstance(base_native, dict):
            inherited_slot = base_native
            base_has_generated_block = inherited_kind != "reference" and "ariadne" in base_native
    # The generated rendered BODY of an inherited native generated page is
    # core-owned exactly like the outer generated pages: altering, dropping or
    # adding the rendered Schema/Observations sections refuses even when every
    # metadata claim compares equal (F2 completion — core_body_sections is the
    # existing comparison).
    if PurePosixPath(rel).suffix == ".md" and (
        {"ariadne", "resource"} & base.keys() or base_has_generated_block
    ):
        base_sections = core_body_sections(base_text)
        sections = core_body_sections(content)
        body_forged = sorted(
            {name for name in base_sections if sections.get(name) != base_sections[name]}
            | (set(sections) - set(base_sections))
        )
        if body_forged:
            raise ValueError(
                f"the edit of {rel!r} changes, drops or adds the core-generated "
                f"section(s) {body_forged} of a generated page — the Schema, "
                "Observations and Schema history sections are regenerated by "
                "refresh_schema, never authored in a proposal; carry them "
                "unchanged and edit the authored sections only"
            )
    if isinstance(proposed_profile, dict) or isinstance(base_profile, dict):
        proposed = proposed_profile if isinstance(proposed_profile, dict) else {}
        # Only edits that remain authored References may change this extension.
        if proposed.get("kind") == "reference" and inherited_kind in (None, "reference"):
            native_system = native_system - {"ariadne"}  # the authored extension
        slot = proposed.get("native")
        if not isinstance(slot, dict):
            slot = {}
        forged_native = sorted(
            key
            for key in native_system & slot.keys()
            if key not in inherited_slot or inherited_slot[key] != slot[key]
        )
        # REMOVING a stamped native claim the base carried is the same forgery
        forged_native = sorted(
            set(forged_native) | (native_system & inherited_slot.keys() - slot.keys())
        )
        if forged_native:
            raise ValueError(
                f"the edit of {rel!r} introduces, changes or removes the native "
                f"trust/generated claim(s) {forged_native} under ariadne_profile.native "
                "— verification, attestation and generated schema facts are stamped "
                "by the system (the authored Reference ariadne extension excepted, "
                "like the retired context_layer exception); never authored or "
                "dropped in a proposal — inherit them unchanged from the base "
                "revision"
            )


# ------------------------------------------------------ allowed artifact scope

_MODEL_SUFFIXES = (".yml", ".yaml")


def _assert_scope(rel: str) -> None:
    """Defense in depth behind the layer resolvers: every artifact identity
    that reaches Git must be one of the allowed candidate paths (plan §2
    candidate scope), explicitly selected as a file — never a directory, never a traversal,
    never a generated artifact."""
    if not _in_user_scope(rel):
        raise ValueError(
            f"artifact path {rel!r} is outside the proposal artifact scope (ariadne.yaml, "
            "data/seed_notes.md, semantic_layer/models/*.yml, semantic_layer/graph.yml, "
            "contracts/*.ya?ml, contract_bindings.yaml, context_integration.yaml, "
            "knowledge/**/*.md native knowledge pages)"
        )
    refuse_generated(rel)  # generated artifacts are never USER-editable


def _in_user_scope(rel: str) -> bool:
    """True when ``rel`` matches the allowed USER-editable candidate path
    grammar (the predicate behind :func:`_assert_scope`; generated artifacts
    inside the scope return True here and are refused separately)."""
    pure = PurePosixPath(rel)
    if (
        not isinstance(rel, str)
        or not rel
        or pure.is_absolute()
        or "\\" in rel
        or rel.startswith("-")
        or any(part in ("", ".", "..") for part in pure.parts)
    ):
        return False
    parts = pure.parts
    if rel == "context_integration.yaml" or knowledge_path(rel):
        return True
    if rel in (
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/graph.yml",
        "contract_bindings.yaml",
    ):
        return True  # spec 0028 §3: the fixed native binding document is a typed root
    if (
        len(parts) == 3
        and parts[:2] == ("semantic_layer", "models")
        and pure.suffix in _MODEL_SUFFIXES
    ):
        return True
    if len(parts) == 2 and parts[0] == "contracts" and pure.suffix in _MODEL_SUFFIXES:
        return True  # spec 0028 §3: producer contract documents (flat)
    # the retired standalone context_layer/ scope is gone —
    # user-editable Context pages live only in the native knowledge/ subtree
    # (knowledge_path, already accepted above).
    return False


def _in_snapshot(rel: str) -> bool:
    """True when ``rel`` is inside the COMPLETE candidate snapshot scope
    (issue #36/G4): the user-editable paths above PLUS the system-generated
    artifacts the finalize pass owns — computation pages and the bookkeeping
    index trees — because the complete artifact digest and the review walk the
    whole candidate identity, never just the user-editable half."""
    pure = PurePosixPath(rel)
    parts = pure.parts
    if (
        not isinstance(rel, str)
        or not rel
        or pure.is_absolute()
        or "\\" in rel
        or rel.startswith("-")
        or any(part in ("", ".", "..") for part in parts)
    ):
        return False
    if rel == "context_integration.yaml" or knowledge_path(rel):
        return True
    if rel in (
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/graph.yml",
        "contract_bindings.yaml",
    ):
        return True
    if (
        len(parts) == 3
        and parts[:2] == ("semantic_layer", "models")
        and pure.suffix in _MODEL_SUFFIXES
    ):
        return True
    if len(parts) == 2 and parts[0] == "contracts" and pure.suffix in _MODEL_SUFFIXES:
        return True  # spec 0028 §3: producer contract documents (flat)
    return (parts[0] == "context_layer" and pure.suffix == ".md") or (
        len(parts) == 2
        and parts[0] == "answer_examples"
        and pure.suffix == ".md"
        and pure.name != "log.md"
    )


def _scope_files(project: Path) -> list[str]:
    """The concrete EXISTING files inside the allowed candidate scope — the
    human-created initial artifact revision commits exactly these, never an
    unrelated user file and never ``git add .`` (plan §2). The
    system-generated bookkeeping (``index.md``/``log.md``) is EXCLUDED: the
    finalize pass owns and regenerates it."""
    rels: list[str] = []
    knowledge = project / "knowledge"
    if (project / "context_integration.yaml").is_file():
        if knowledge.is_symlink():
            raise GitError("initial knowledge directory must not be a symlink")
        if knowledge.is_dir():
            rels.extend(
                p.relative_to(project).as_posix()
                for p in sorted(knowledge.rglob("*"))
                if p.is_file() and knowledge_path(p.relative_to(project).as_posix())
            )
    for rel in (
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/graph.yml",
        "contract_bindings.yaml",
        "context_integration.yaml",
    ):
        if (
            rel in ("contract_bindings.yaml", "context_integration.yaml")
            and (project / rel).is_symlink()
        ):
            raise GitError(f"initial artifact {rel!r} must not be a symlink")
        if (project / rel).is_file():
            rels.append(rel)
    models = project / "semantic_layer" / "models"
    if models.is_dir():
        rels.extend(
            path.relative_to(project).as_posix()
            for path in sorted(models.iterdir())
            if path.is_file() and path.suffix in _MODEL_SUFFIXES
        )
    contracts = project / "contracts"
    if contracts.is_symlink():
        raise GitError("initial contracts directory must not be a symlink")
    if contracts.is_dir():
        for path in sorted(contracts.iterdir()):
            if path.suffix not in _MODEL_SUFFIXES:
                continue
            if path.is_symlink():
                raise GitError(f"initial contract {path.name!r} must not be a symlink")
            if path.is_file():
                rels.append(path.relative_to(project).as_posix())
    for rel in (
        sorted(
            path
            for path in sorted(contracts.iterdir())
            if path.is_file() and path.suffix in _MODEL_SUFFIXES
        )
        if contracts.is_dir()
        else []
    ):
        rels.append(rel.relative_to(project).as_posix())
    # the retired standalone context_layer/ and
    # answer_examples/ initial-revision walks are gone — the native contract's
    # initial artifact revision commits the registry, Seed Notes, OSI models,
    # graph, contracts and the native knowledge/ subtree only (a legacy
    # project refuses at the shared project gate before any proposal exists).
    return rels


def _staged_changes(project: Path) -> list[str]:
    """Index entries Git already carries staged (porcelain column 1: added,
    modified, deleted, renamed) — including a repository with no commits yet;
    untracked files are not staged."""
    staged: list[str] = []
    for line in _git(["status", "--porcelain"], project).stdout.splitlines():
        if line and not line.startswith(("??", " ")):
            staged.append(line[3:].rsplit(" -> ", 1)[-1])
    return staged


def _create_initial_revision(project: Path) -> str:
    """The empty-project onboarding path (spec §3): a repository with no
    commits yet gets its HUMAN-CREATED initial artifact revision — the existing
    artifact files committed once, only within the allowed scope (an empty
    commit when nothing exists yet, so a proposal branch always has a base)."""
    paths = _scope_files(project)
    if paths:
        # The shared pre-write content boundary applies to the human-created
        # initial artifacts too (issue #34 review): every artifact is checked
        # BEFORE anything is staged — a credential-bearing initial file refuses
        # with the index and history untouched.
        for rel in paths:
            if (project / rel).is_symlink():
                raise GitError(f"initial artifact {rel!r} must not be a symlink")
            with open(project / rel, "rb") as fh:  # bounded read, like the seam
                raw = fh.read(MAX_ARTIFACT_BYTES + 1)
            check_artifact_content(f"initial artifact {rel!r}", raw.decode("utf-8", "replace"))
        # ``-f`` because the scaffolded project .gitignore ignores the served
        # layers: the explicitly enumerated allowed identities — never ``git
        # add .`` — establish the human-created baseline (plan §2). Every path
        # is pinned as a LITERAL pathspec: a human-created filename carrying a
        # wildcard can never match other files.
        literal = [_literal(rel) for rel in paths]
        _git(["add", "-f", "--", *literal], project)
        _git(["commit", "-m", "ariadne: initial artifact revision", "--", *literal], project)
    else:
        # An empty commit still commits the existing INDEX: an operator's
        # pre-staged changes must never ride the onboarding commit. Refuse and
        # preserve them exactly as they are — the human resolves the index.
        staged = _staged_changes(project)
        if staged:
            raise GitError(
                f"the Git index of {project} already carries staged changes "
                f"({', '.join(staged)}) — the empty project's initial artifact "
                "revision must not commit them; commit or unstage them by hand, "
                "then start again (the index is preserved untouched)"
            )
        _git(["commit", "--allow-empty", "-m", "ariadne: initial artifact revision"], project)
    return _current_head(project) or ""


# ------------------------------------------------------- the proposal lifecycle


def _new_proposal_id() -> str:
    """A system-generated proposal identity (callers never supply one):
    timestamped plus random hex, a plain ref-safe slug that can never become a
    git option or a traversal."""
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"p-{stamp}-{secrets.token_hex(3)}"


def _check_coherent(project: Path, record: dict) -> None:
    """The worktree/branch/record coherence gate (spec §4): the proposal's
    worktree must exist, sit on its recorded branch, at exactly the recorded
    candidate revision, with NOTHING uncommitted. Any disagreement marks an
    interrupted transition or human tampering — refuse for human resolution
    and preserve every copy."""
    proposal = record["id"]
    worktree = project / WORKTREES_REL / proposal
    if not worktree.is_dir():
        raise ValueError(
            f"the worktree of proposal {proposal} is missing ({worktree})" + _HUMAN_RESOLUTION
        )
    head = _git(["rev-parse", "HEAD"], worktree).stdout.strip()
    if head != record["candidate_revision"]:
        raise ValueError(
            f"proposal {proposal}'s branch is at {head} but its record names candidate "
            f"{record['candidate_revision']}" + _HUMAN_RESOLUTION
        )
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], worktree).stdout.strip()
    if branch != record["branch"]:
        raise ValueError(
            f"proposal {proposal}'s worktree is on branch {branch!r}, not its recorded "
            f"{record['branch']!r}" + _HUMAN_RESOLUTION
        )
    # Uncommitted changes to TRACKED artifacts mark an interrupted edit or
    # tampering — refuse for human resolution. (Untracked files are tolerated:
    # edits stage exactly one validated artifact identity, so an unrelated
    # scratch file can never ride into a commit; it simply stays untracked.)
    if _git(["status", "--porcelain", "--untracked-files=no"], worktree).stdout.strip():
        raise ValueError(
            f"the worktree of proposal {proposal} carries uncommitted changes — they "
            "are visible drafts pending human resolution, and further mutations are "
            "refused" + _HUMAN_RESOLUTION
        )


def _admitted_baseline(project: Path) -> str | None:
    """The project's CURRENT admitted revision (None with no admission) — the
    default proposal base and the recorded expected admitted baseline (plan
    §2). :mod:`ariadne.admission` imports this module, so its descriptor
    reader is resolved lazily at call time (both modules are loaded then); a
    malformed descriptor is the same human-resolution failure
    :func:`ariadne.admission.load_current` reports."""
    from ariadne import admission  # lazy: admission imports proposals at load

    current = admission.load_current(project)
    return None if current is None else current["commit"]


def refuse_unsupported_project(project: str | Path) -> None:
    """Refuse an unsupported retired project/admission BEFORE any mutation
    (AC10, spec0035 §6): the gate validates the ACTUAL native project format —
    served ``context_layer/`` pages without a valid ``knowledge/`` Knowledge
    Base (Control File + Source Reference Manifest), a dummy/placeholder
    ``knowledge/`` directory without that state, or a pinned admission whose
    snapshot serves retired Context pages without the native KB state — with
    fresh-setup guidance and no conversion, reset or filesystem change. The
    shared project-open path (proposals, discovery and the query runtime)
    calls this so runtime rejection never lives only in the scaffolder.
    Projects carrying the real native KB state (including mixed intermediate
    candidates on the migration line) and plain onboarding-empty projects are
    supported here."""
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        load_control_file,
        load_source_reference_manifest,
    )
    from lumio_wiki.knowledge_base import (  # pyright: ignore[reportMissingImports]
        ControlFileError,
    )
    from lumio_wiki.source_references import (  # pyright: ignore[reportMissingImports]
        SourceReferenceError,
    )

    project = Path(project)

    def _native_kb_state(kb_dir: Path) -> bool:
        """Producer-parse the ACTUAL KB identity (F4 completion): Control File
        and Source Reference Manifest must load and validate. Presence of the
        files alone never establishes support, and page validity is NEVER
        consulted here (AC7: unrelated mutable working-copy drafts cannot
        block a valid pinned admission)."""
        if not kb_dir.is_dir():
            return False
        try:
            manifest = load_source_reference_manifest(kb_dir)
            control = load_control_file(kb_dir)
        except ControlFileError, SourceReferenceError:
            return False
        return manifest is not None and control is not None

    knowledge = project / "knowledge"
    native_kb = _native_kb_state(knowledge)
    context_layer = project / "context_layer"
    retired_pages = context_layer.is_dir() and any(context_layer.rglob("*.md"))
    unsupported = (retired_pages and not native_kb) or (knowledge.is_dir() and not native_kb)
    if not unsupported:
        # A pinned admission must ALSO be the native contract: its snapshot
        # serving retired Context pages without the native KB state is the
        # legacy admitted format — never silently re-opened or re-validated.
        from ariadne import admission  # lazy: admission imports proposals at load

        record = admission.load_current(project)
        if record is not None:
            admission.refuse_unsupported_admission_snapshot(project, record)
    if unsupported:
        raise ValueError(
            f"{project} uses the retired standalone Context layout or carries a "
            "knowledge/ directory without the native Knowledge Base state (Control "
            "File + Source Reference Manifest); " + _UNSUPPORTED_PROJECT_GUIDANCE
        )


def start_proposal(project: str | Path, *, base_revision: str | None = None) -> dict:
    """Start ONE isolated authoring proposal in the fixed data project: a
    system-generated ID, its branch ``ariadne/proposal/<id>`` and its dedicated
    worktree under the ignored ``.ariadne/worktrees/<id>/`` — every location
    derived, never caller-supplied. The base is the optional known revision or
    the CURRENT ADMITTED revision (plan §2: a new proposal builds on the served
    state, never an unserved checkout); with no admission, the current HEAD —
    and a repository with no commits yet gets its human-created initial
    artifact revision first (allowed scope only). The record persists the
    expected admitted baseline at start time — the binding admission compares
    it. Returns the proposal ID with its base and candidate
    revisions (equal until the first edit)."""
    project = Path(project).resolve()
    _require_repo(project)
    refuse_unsupported_project(project)  # before any state exists
    _refuse_symlinked_component(project, ARIADNE_STATE_DIR)
    _require_git_identity(project)
    with _file_lock(project / LOCKS_REL / "project.lock"):
        _ensure_state_ignored(project)  # inside the lock: concurrent starts
        # never interleave their exclude-file append
        baseline = _admitted_baseline(project)
        head = _current_head(project)
        if baseline is not None:
            base = (
                _validate_revision(project, base_revision)
                if base_revision is not None
                else _validate_revision(project, baseline)
            )
        elif head is None:
            if base_revision is not None:
                raise ValueError(
                    "the project repository has no commits yet — start without "
                    "--base-revision to establish the human-created initial artifact "
                    "revision first"
                )
            base = _create_initial_revision(project)
        else:
            base = _validate_revision(project, base_revision) if base_revision else head
        proposal = _new_proposal_id()
        worktree = project / WORKTREES_REL / proposal
        if _lstat(worktree) is not None:
            raise GitError(
                f"worktree location {worktree} already exists — this needs human "
                "resolution, not an agent reset"
            )
        _refuse_symlinked_component(project, WORKTREES_REL / proposal)
        branch = f"{PROPOSAL_BRANCH_PREFIX}{proposal}"
        _git(["worktree", "add", "-q", "-b", branch, str(worktree), base], project)
        record = {
            "id": proposal,
            "project": str(project),
            "base_revision": base,
            "candidate_revision": base,
            "expected_baseline": baseline,
            "branch": branch,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _store_record(project, record)
    return {
        "proposal": proposal,
        "base_revision": base,
        "candidate_revision": base,
    }


def read_artifact(project: str | Path, proposal: str, rel: str, *, part: int = 1) -> dict:
    """Read ONE artifact of the proposal's CURRENT candidate revision —
    inherited from the base when never edited — in bounded parts (a part is
    ``complete`` only when it IS the whole artifact). Reading is pinned to the
    recorded candidate commit, so it can never report a mutable worktree
    draft; a missing artifact is a specific error, never a silent empty body."""
    project = Path(project).resolve()
    _assert_scope(rel)
    record = _load_record(project, proposal)
    revision = record["candidate_revision"]
    blob = f"{revision}:{rel}"
    if _git(["cat-file", "-e", blob], project, check=False).returncode != 0:
        raise ValueError(
            f"no artifact {rel} in proposal {proposal} at revision {revision[:12]} — "
            "it is not part of the candidate or its inherited base"
        )
    data = _git(["show", blob], project, text=False).stdout
    text = data.decode("utf-8", errors="replace")
    parts = max(1, -(-len(text) // READ_PART_CHARS))
    if not 1 <= part <= parts:
        raise ValueError(f"part {part} is out of range (1..{parts}) for {rel}")
    return {
        "proposal": proposal,
        "revision": revision,
        "path": rel,
        "chars": len(text),
        "part": part,
        "parts": parts,
        "complete": parts == 1,
        "content": text[(part - 1) * READ_PART_CHARS : part * READ_PART_CHARS],
    }


def _read_blob(project: Path, revision: str, rel: str) -> bytes | None:
    """One artifact's exact bytes at ``revision`` (None when absent) — the
    shared read behind the identical-edit no-op check and the inherited-claim
    comparison."""
    if _git(["cat-file", "-e", f"{revision}:{rel}"], project, check=False).returncode != 0:
        return None
    return _git(["show", f"{revision}:{rel}"], project, text=False).stdout


def _safe_write(worktree: Path, rel: str, content: str) -> None:
    """Write one artifact body inside the proposal worktree, refusing a
    symlinked parent or target first (a planted link must never redirect an
    artifact write out of the worktree)."""
    path = worktree.joinpath(*PurePosixPath(rel).parts)
    current = worktree
    for part in PurePosixPath(rel).parts[:-1]:
        current = current / part
        entry = _lstat(current)
        if entry is not None and stat.S_ISLNK(entry.st_mode):
            raise ValueError(
                f"{current}: refusing a symlinked artifact directory — proposal "
                "artifacts are plain worktree files"
            )
    entry = _lstat(path)
    if entry is not None and stat.S_ISLNK(entry.st_mode):
        raise ValueError(
            f"{path}: refusing a symlinked artifact file — proposal artifacts are "
            "plain worktree files"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _refuse_untracked_new_artifact(project: Path, worktree: Path, rel: str, candidate: str) -> None:
    """An edit target that exists in the worktree but is NOT part of the
    recorded candidate revision is an interrupted creation's draft (the
    coherence gate tolerates untracked files) — refuse for human resolution
    and preserve the bytes; overwriting them would destroy evidence (spec §4)."""
    target = worktree.joinpath(*PurePosixPath(rel).parts)
    if _lstat(target) is None:
        return  # the normal case: nothing claims the name yet
    if _git(["cat-file", "-e", f"{candidate}:{rel}"], project, check=False).returncode == 0:
        return  # tracked at the candidate: the ordinary edit path
    raise ValueError(
        f"{target} exists in the worktree but {rel} is not part of the recorded "
        f"candidate revision {candidate[:12]} — an interrupted artifact creation "
        "left that draft as evidence" + _HUMAN_RESOLUTION
    )


def edit_proposal(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    rel: str,
    content: str,
    *,
    core_generated: bool = False,
) -> dict:
    """Apply ONE complete artifact edit to the proposal's candidate: the
    expected candidate revision is required and checked BEFORE any write
    (stale or competing writers are refused without overwriting), an identical
    edit at the current revision is a no-op returning the unchanged candidate,
    and a real edit stages EXACTLY the named artifact identity (never ``git
    add .``), commits on the proposal branch and persists the new candidate
    revision durably. An interrupted commit/store leaves the evidence for human
    resolution and blocks further mutations.

    ``core_generated=True`` is the CORE-AUTHORED regeneration seam of the
    explicit schema refresh (issue #41): the deterministic refresh may change
    the system-owned generated facts (``ariadne`` blocks, ``resource``) because
    it regenerates them against the operator-approved inputs — no
    caller-facing surface ever passes it."""
    project = Path(project).resolve()
    _assert_scope(rel)
    check_artifact_content(f"edit {rel!r}", content)
    _load_record(project, proposal)  # identity/belonging errors surface early
    worktree_root = project / WORKTREES_REL / proposal
    with _file_lock(project / LOCKS_REL / f"{proposal}.lock"):
        record = _load_record(project, proposal)  # authoritative under the lock
        _check_coherent(project, record)
        current = record["candidate_revision"]
        if expected_revision != current:
            raise ValueError(
                f"stale revision: proposal {proposal} is at candidate {current}, the "
                f"edit expected {expected_revision} — re-read the artifact and retry "
                "with the current candidate revision; nothing was written"
            )
        base_content = _read_blob(project, current, rel)
        if base_content is not None and base_content == content.encode("utf-8"):
            return {
                "proposal": proposal,
                "revision": current,
                "changed": False,
                "path": rel,
            }  # identical edit: no commit, candidate unchanged
        if not core_generated:
            _refuse_forged_claims(
                rel, content, base_content
            )  # spec §4: system-owned claims, content half
        _require_git_identity(project)
        _refuse_untracked_new_artifact(project, worktree_root, rel, current)
        _safe_write(worktree_root, rel, content)
        # Stage EXACTLY the named artifact identity (with -f: the scaffolded
        # .gitignore ignores the served layers, and this one validated path is
        # an explicitly allowed artifact) — never ``git add .``/``-A``: an
        # untracked scratch file in the worktree can never ride along. The
        # LITERAL pathspec pins exact-name semantics at the seam.
        _git(["add", "-f", "--", _literal(rel)], worktree_root)
        _git(["commit", "-m", f"ariadne: edit {rel}", "--", _literal(rel)], worktree_root)
        new_revision = _git(["rev-parse", "HEAD"], worktree_root).stdout.strip()
        record["candidate_revision"] = new_revision
        _store_record(project, record)
    return {"proposal": proposal, "revision": new_revision, "changed": True, "path": rel}


# ------------------------------------------------- native KB page batches

# One knowledge-page edit of a complete batch: exactly the documented fields.
_PAGE_EDIT_KEYS = frozenset({"path", "content"})


def check_page_batch(pages: object) -> list[tuple[str, str]]:
    """Validate one complete knowledge-page batch BEFORE any write: a non-empty
    list of objects carrying exactly ``{path, content}``, every ``path`` a
    native KB page identity (``knowledge/…​.md`` — generated bookkeeping and
    non-page files are refused) and every ``content`` within the shared
    content boundary. Returns ``(rel, content)`` pairs; a repeated path is a
    duplicate-target conflict, never last-writer-wins."""
    if not isinstance(pages, list) or not pages:
        raise ValueError(
            "a page batch is a non-empty JSON list of {path, content} objects — "
            "one coherent candidate revision or no accepted batch"
        )
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != _PAGE_EDIT_KEYS:
            raise ValueError(
                f"pages[{index}] must be an object with exactly the fields "
                "['content', 'path'] — approval/attestation claims and arbitrary "
                "metadata are system-owned"
            )
        rel = page["path"]
        if not isinstance(rel, str) or not knowledge_path(rel) or not rel.endswith(".md"):
            raise ValueError(
                f"pages[{index}].path {rel!r} is not a knowledge/ Compiled Page "
                "identity — only native knowledge pages route through the "
                "complete-batch writer (index.md/log.md are system-owned)"
            )
        if PurePosixPath(rel).name in _GENERATED_FILES:
            refuse_generated(rel)
        if rel in seen:
            raise ValueError(
                f"the batch carries {rel!r} twice — two writes for one page are "
                "a duplicate-target conflict, never last-writer-wins"
            )
        seen.add(rel)
        content = page["content"]
        check_artifact_content(f"page {rel!r}", content)
        pairs.append((rel, content))
    return pairs


def edit_page_batch(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    pages: list,
    *,
    core_generated: bool = False,
) -> dict:
    """Apply ONE complete knowledge-page batch through the PUBLIC native
    writer inside the existing proposal lock/revision discipline (AC4,
    spec0035 §2): the whole batch is validated as one candidate by the SDK
    (``write_pages_into_worktree`` — new and revised pages together, never
    sequential single-page writes) before any byte is written, so mutually
    linked pages are accepted together and a dangling reference or invalid
    metadata rejects the batch without accepting a partial page set. Core
    then stages ONLY the writer's returned intended paths, commits on the
    proposal branch and updates the recorded candidate revision AFTER the
    commit; an interrupted transition stays human-resolution evidence.

    Preserved guards: the stale-expected-revision refusal, the identical-batch
    no-op, the shared pre-write content boundary, the forged system-owned
    claim boundary per page and the untracked-draft refusal. OSI/model draft
    edits keep their separate :func:`edit_proposal` handling — this seam is
    only for ``knowledge/`` pages.

    ``core_generated=True`` is the CORE-AUTHORED regeneration seam of the
    explicit schema refresh and the revision-2 native finalize (spec0035 §6):
    deterministic Core generation may change the system-owned claims
    (``ariadne_profile`` native families, ``core_ref``) it derives against
    operator-approved inputs. It is never caller-facing — the public
    ``AuthoringProject.edit_pages_batch`` surface never forwards it."""
    project = Path(project).resolve()
    pairs = check_page_batch(pages)
    if not core_generated:
        for rel, _content in pairs:
            refuse_generated(rel)
    _load_record(project, proposal)  # identity/belonging errors surface early
    worktree_root = project / WORKTREES_REL / proposal
    with _file_lock(project / LOCKS_REL / f"{proposal}.lock"):
        record = _load_record(project, proposal)  # authoritative under the lock
        _check_coherent(project, record)
        current = record["candidate_revision"]
        if expected_revision != current:
            raise ValueError(
                f"stale revision: proposal {proposal} is at candidate {current}, the "
                f"batch expected {expected_revision} — re-read the candidate and retry "
                "with the current candidate revision; nothing was written"
            )
        return _edit_page_batch_locked(
            project,
            proposal,
            record,
            current,
            worktree_root,
            pairs,
            core_generated=core_generated,
        )


def _edit_page_batch_locked(
    project: Path,
    proposal: str,
    record: dict,
    current: str,
    worktree_root: Path,
    pairs: list[tuple[str, str]],
    *,
    core_generated: bool = False,
) -> dict:
    """The lock-held body of :func:`edit_page_batch`. Callers that ALREADY
    hold the proposal lock — the revision-2 finalize pass inside
    ``validate_proposal`` — submit their generated batch through here with
    their authoritative record and revision; the lock is never re-acquired
    (a non-reentrant re-lock inside the finalize would deadlock)."""
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        load_knowledge_base,
        parse_frontmatter,
    )
    from lumio_wiki.git_authoring import (  # pyright: ignore[reportMissingImports]
        GitAuthoringError,
        write_pages_into_worktree,
    )
    from lumio_wiki.ingest import ProposedPage  # pyright: ignore[reportMissingImports]
    from lumio_wiki.knowledge_base import FrontmatterError

    # spec0035 C1 fix (F3): the producer-owned page identity decides where
    # a title actually lives. A path-addressed batch entry whose declared
    # canonical title/alias resolves to a DIFFERENT recorded page (an
    # identity mix-up would otherwise write the wrong page while staging
    # the addressed one) refuses BEFORE any write or claim check — the
    # addressed path and the native destination must be the same page.
    kb, kb_report = load_knowledge_base(worktree_root / "knowledge")
    by_title: dict = {}
    by_alias: dict = {}
    by_path: dict = {}
    if kb_report.is_valid:
        for page in kb.pages:
            if not page.path:
                continue
            by_title[page.title] = page
            by_path[page.path] = page
            for alias in page.aliases:
                by_alias[alias] = page
    identical = True
    proposed: list = []
    for rel, content in pairs:
        base_content = _read_blob(project, current, rel)
        if base_content is not None and base_content == content.encode("utf-8"):
            continue  # an identical page edit contributes no change
        identical = False
        if not (worktree_root / rel).exists():
            _refuse_untracked_new_artifact(project, worktree_root, rel, current)
        try:
            meta, _body, _line = parse_frontmatter(content, PurePosixPath(rel).name)
        except FrontmatterError as exc:
            raise GitAuthoringError(f"{rel}: {exc}") from exc
        title = meta.get("title") if isinstance(meta, dict) else None
        if not isinstance(title, str) or not title.strip():
            raise ValueError(
                f"page {rel!r} carries no non-empty canonical title — the "
                "native writer addresses every page by its declared title"
            )
        # the retained Core
        # authoring gate over the PRODUCER-PARSED flat native metadata — a
        # table page carrying ariadne_quality passes K's structural check
        # inside the batch writer AND Core's meaning/edit validation here,
        # BEFORE any byte is written (the classic edit path lost this gate
        # when the classic bundle retired; quality stays advisory metadata,
        # never a query permission input).
        profile = meta.get("ariadne_profile") if isinstance(meta, dict) else None
        native = profile.get("native") if isinstance(profile, dict) else None
        kind = profile.get("kind") if isinstance(profile, dict) else None
        if (
            isinstance(native, dict)
            and "ariadne_quality" in native
            and (kind == "table" or native.get("type") == "table")
        ):
            quality_errors = _quality_profile_errors(rel, native)
            if quality_errors:
                raise ValueError("; ".join(quality_errors))
        kb_rel = PurePosixPath(rel).relative_to("knowledge").as_posix()
        recorded = by_title.get(title) or by_alias.get(title)
        occupant = by_path.get(kb_rel)
        if recorded is not None and recorded.path != kb_rel:
            raise ValueError(
                f"page {rel!r} declares canonical title {title!r}, which resolves "
                f"to the recorded page knowledge/{recorded.path} — a path-addressed "
                "batch cannot redirect or relabel a page (aliases resolve the same "
                "way): address its recorded identity or author the change through "
                "review; nothing was written"
            )
        if recorded is None and occupant is not None and occupant.title != title:
            raise ValueError(
                f"page {rel!r} is the recorded page of {occupant.title!r} but the "
                f"batch declares {title!r} — a path-addressed batch cannot relabel "
                "a page to a different identity: address the recorded title or "
                "author the change through review; nothing was written"
            )
        if not core_generated:
            _refuse_forged_claims(rel, content, base_content)
        proposed.append(ProposedPage(relative_path=kb_rel, title=title, markdown=content))
    if identical:
        return {
            "proposal": proposal,
            "revision": current,
            "changed": False,
            "paths": [rel for rel, _content in pairs],
            "count": len(pairs),
        }  # identical batch: no commit, candidate unchanged
    # The complete candidate validates as ONE batch before any byte: a
    # dangling reference or invalid metadata refuses with the worktree,
    # branch and record untouched (the writer restores any partial state).
    try:
        result = write_pages_into_worktree(
            worktree_root / "knowledge",
            proposed,
            operation="ariadne candidate page batch",
        )
    except GitAuthoringError:
        raise
    _require_git_identity(project)
    # Stage ONLY the returned intended paths (literal pathspecs), then
    # commit; the recorded candidate revision updates AFTER the commit —
    # a core-authored commit the record never saw is the interrupted
    # transition signature the coherence gate refuses for the human.
    intended = [f"knowledge/{kb_path}" for kb_path in result.written]
    literal = [_literal(rel) for rel in intended]
    _git(["add", "-f", "--", *literal], worktree_root)
    _git(
        ["commit", "-m", f"ariadne: page batch ({len(intended)} pages)", "--", *literal],
        worktree_root,
    )
    new_revision = _git(["rev-parse", "HEAD"], worktree_root).stdout.strip()
    record["candidate_revision"] = new_revision
    _store_record(project, record)
    return {
        "proposal": proposal,
        "revision": new_revision,
        "changed": True,
        "paths": intended,
        "count": len(intended),
    }


def scope_blobs(project: Path, revision: str) -> list[tuple[str, bytes]]:
    """The COMPLETE candidate-scope artifact bytes at one exact revision
    (issue #36/G4): every tracked path inside the snapshot scope — registry,
    Seed Notes, models, graph and ALL context_layer pages including the
    system-generated computations and bookkeeping — read from the commit
    blob store, never a mutable worktree. This is the materialization behind
    exact-final-commit validation and review."""
    tracked = _git(["ls-tree", "-r", "--name-only", revision], project).stdout.split("\n")
    blobs: list[tuple[str, bytes]] = []
    integrated = "context_integration.yaml" in tracked
    for rel in sorted(path for path in tracked if _in_snapshot(path)):
        if knowledge_path(rel) and not integrated:
            continue
        blob = _read_blob(project, revision, rel)
        if blob is not None:  # pragma: no cover - ls-tree paths always resolve
            blobs.append((rel, blob))
    return blobs


def refuse_untracked_scope(project: Path, record: dict) -> None:
    """Refuse before the finalize pass when an UNTRACKED file sits inside the
    candidate artifact scope: it is the preserved evidence of an interrupted
    artifact creation (the edit seam writes before it stages), and the
    finalize pass reads pages from disk — indexing an untracked page while it
    never enters the commit would split the effective bundle from the
    candidate. Human resolution, bytes preserved (spec §4). Untracked files
    OUTSIDE the artifact scope stay tolerated scratch."""
    proposal = record["id"]
    worktree = project / WORKTREES_REL / proposal
    for line in _git(
        ["status", "--porcelain", "--untracked-files=all"], worktree
    ).stdout.splitlines():
        if line.startswith("??"):
            rel = line[3:].rsplit(" -> ", 1)[-1]
            if _in_snapshot(rel) and (
                not knowledge_path(rel) or (worktree / "context_integration.yaml").is_file()
            ):
                raise ValueError(
                    f"the worktree of proposal {proposal} carries the untracked artifact "
                    f"draft {rel!r} — an interrupted artifact creation left it as "
                    "evidence" + _HUMAN_RESOLUTION
                )


def _validation_path(project: Path, proposal: str, revision: str) -> Path:
    """Where one exact candidate revision's validation evidence lives."""
    return project / VALIDATION_REL / proposal / f"{revision}.json"


def store_validation(project: Path, evidence: dict) -> Path:
    """Persist one validation evidence record atomically and durably (the
    proposal-record discipline) under the operator-owned ignored
    ``.ariadne/validation/<proposal>/<commit>.json`` — SEPARATE from the
    committed artifact content, so evidence never changes the revision it
    describes (spec §4, plan §2)."""
    path = _validation_path(project, evidence["proposal"], evidence["commit"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_path(path.parent)
    return path


def load_validation(project: Path, proposal: str, revision: str) -> dict | None:
    """The stored validation evidence of one EXACT candidate revision (None
    when that revision was never validated). A non-regular, unreadable or
    malformed record is operator-owned state needing human resolution — never
    a silent reset."""
    path = _validation_path(project, proposal, revision)
    entry = _lstat(path)
    if entry is None:
        return None
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"{path}: refusing a non-regular validation record — operator-owned "
            "state, inspect it by hand"
        )
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path}: unreadable validation evidence ({exc}) — this needs human "
            "resolution, not an agent reset"
        ) from None
    if (
        not isinstance(evidence, dict)
        or evidence.get("commit") != revision
        or evidence.get("proposal") != proposal
    ):
        raise ValueError(
            f"{path}: malformed validation evidence — this needs human resolution, "
            "not an agent reset"
        )
    return evidence
