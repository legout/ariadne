"""Shared Proposals: local Git authoring identities plus the compiled ad-hoc
staging operation (spec 2026-10-02-0009 §2 "Shared Proposals"/§4, ADR-0016,
plan §2 "Project storage and authority").

Two responsibilities live here so Authoring (:mod:`ariadne.authoring`) and
Query (:mod:`ariadne.query`) share ONE implementation:

- the local Git proposal lifecycle over the DATA PROJECT's repository: one
  fixed project, system-generated proposal IDs/branches
  (``ariadne/proposal/<id>``), one worktree per active writer under the
  ignored operator-owned ``.ariadne/`` state dir (``worktrees/<id>/``,
  ``proposals/<id>.json`` records), revision-checked complete-artifact edits,
  and the shared pre-write content boundary (bounds + credential classes) the
  legacy bundle submission also uses;
- :func:`stage_ad_hoc`, the existing compiled ad-hoc staging/label operation
  moved INTACT out of the Query runtime (issue #34/G2) so Query stages ad-hoc
  definitions through this shared module without importing Authoring and
  without touching any Git proposal store (spec §2: staged ad-hoc definitions
  keep their own legacy staging contract — they never become Git proposals).

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

# The auto-staged draft page lives in the shared Context module (moved intact).
from ariadne.context import _build_adhoc_page, _load
from ariadne.ingest import _SECRET_PATTERNS
from ariadne.sources import _DSN_PASSWORD_RE

# Operator-owned project state, ignored via the repo-LOCAL exclude file: the
# caller never provides (nor sees) worktree paths or operational state files —
# locations derive from the fixed project and the system-generated proposal ID.
ARIADNE_STATE_DIR = Path(".ariadne")
PROPOSALS_REL = ARIADNE_STATE_DIR / "proposals"  # <id>.json records
WORKTREES_REL = ARIADNE_STATE_DIR / "worktrees"  # <id>/ per active writer
LOCKS_REL = ARIADNE_STATE_DIR / "locks"  # <id>.lock per proposal + project.lock
PROPOSAL_BRANCH_PREFIX = "ariadne/proposal/"  # ariadne/proposal/<id>

# A generated proposal ID: lowercase slug, never option-shaped (no leading '-').
_PROPOSAL_ID_RE = re.compile(r"p-[0-9a-f]{14}-[0-9a-f]{6}")
# Commit revisions cross the API (base/expected/candidate): hex SHAs only.
_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")

# One complete artifact edit is bounded exactly like the legacy bundle
# submission (authoring.MAX_BUNDLE_BYTES); reads arrive in bounded parts the
# same way the legacy review bodies do (authoring.EVIDENCE_PART_CHARS).
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
READ_PART_CHARS = 20_000

# The OKF page sections a proposal may edit; computations/index.md/log.md are
# system-generated (ADR-0007/ADR-0013: attestation is service-owned).
_OKF_PAGE_SECTIONS = ("tables", "references", "policies", "metrics", "skills")
_GENERATED_FILES = frozenset({"index.md", "log.md"})

# Named env-style credential assignments the URL-password rule misses (the
# value is never echoed; the same-line ``=`` keeps prose that merely MENTIONS
# the variable from matching). Shared with the legacy bundle submission.
_AWS_ASSIGNMENT_RE = re.compile(
    r"\b(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)[ \t]*=[ \t]*\S+"
)

# The fail-closed instruction for an interrupted Git proposal transition
# (spec §4): name the evidence, forbid any agent reset or deletion.
_HUMAN_RESOLUTION = (
    " — interrupted Git proposal transition, human resolution required: KEEP the "
    "worktree under .ariadne/worktrees/, the branch ariadne/proposal/<id> and "
    ".ariadne/proposals/<id>.json exactly as they are, compare them, and resolve by "
    "hand; no agent command resets, deletes or merges them"
)


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


def _refuse_symlinked_component(root: Path, rel: Path) -> None:
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
            f"{path}: malformed proposal record — this needs human resolution, not an "
            "agent reset"
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
        raise ValueError(
            f"the {payload.get('kind')!r} edit is missing required field(s) {missing}"
        )
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
    artifacts at the staging gate. Names are converted to allowed artifact
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
# finalize and promotion passes stamp mechanically — verified history,
# generated/stale_after — plus the attestation/approval words of the edit
# envelope's smuggling rule): an edit may only RETAIN a claim inherited
# verbatim from the base revision, never introduce or change one (spec §4).
_SYSTEM_CLAIM_KEYS = frozenset(
    {"verified", "generated", "stale_after", "attester", "approved", "attested", "validated"}
)


def check_artifact_content(where: str, content: str) -> None:
    """The shared pre-write content boundary (the credential/payload half of
    the legacy ``_check_submission`` family, shared verbatim with it): an
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
    allowed."""
    claims = _claim_map(rel, content)
    if not claims:
        return
    base = (
        _claim_map(rel, base_content.decode("utf-8", "replace"))
        if base_content is not None
        else {}
    )
    forged = sorted(
        key
        for key in _SYSTEM_CLAIM_KEYS & claims.keys()
        if key not in base or base[key] != claims[key]
    )
    if forged:
        raise ValueError(
            f"the edit of {rel!r} introduces or changes system-owned trust "
            f"claim(s) {forged} — approval and attestation are stamped by the "
            "deterministic finalize/promotion passes, never authored in a "
            "proposal; claims inherited unchanged from the base revision are "
            "allowed, remove the claim and retry"
        )


# ------------------------------------------------------ allowed artifact scope

_MODEL_SUFFIXES = (".yml", ".yaml")


def _assert_scope(rel: str) -> None:
    """Defense in depth behind the layer resolvers: every artifact identity
    that reaches Git must be one of the allowed candidate paths (plan §2
    candidate scope), explicitly staged — never a directory, never a traversal,
    never a generated artifact."""
    pure = PurePosixPath(rel)
    if (
        not isinstance(rel, str)
        or not rel
        or pure.is_absolute()
        or "\\" in rel
        or rel.startswith("-")
        or any(part in ("", ".", "..") for part in pure.parts)
    ):
        raise ValueError(f"artifact path {rel!r} is not an allowed relative artifact path")
    parts = pure.parts
    if rel in ("ariadne.yaml", "data/seed_notes.md", "semantic_layer/graph.yml"):
        refuse_generated(rel)
        return
    if (
        len(parts) == 3
        and parts[:2] == ("semantic_layer", "models")
        and pure.suffix in _MODEL_SUFFIXES
    ):
        refuse_generated(rel)
        return
    if (
        parts[0] == "context_layer"
        and len(parts) >= 3
        and parts[1] in _OKF_PAGE_SECTIONS
        and pure.suffix == ".md"
    ):
        if parts[1] == "references" and (len(parts) != 4 or parts[2] != "joins"):
            raise ValueError(
                f"{rel}: reference pages are .md files directly under "
                "context_layer/references/joins/ (the checked bundle layout)"
            )
        refuse_generated(rel)
        return
    raise ValueError(
        f"artifact path {rel!r} is outside the proposal artifact scope (ariadne.yaml, "
        "data/seed_notes.md, semantic_layer/models/*.yml, semantic_layer/graph.yml, "
        "context_layer/{tables,references/joins,policies,metrics,skills}/*.md)"
    )


def _scope_files(project: Path) -> list[str]:
    """The concrete EXISTING files inside the allowed candidate scope — the
    human-created initial artifact revision commits exactly these, never an
    unrelated user file and never ``git add .`` (plan §2)."""
    rels: list[str] = []
    for rel in ("ariadne.yaml", "data/seed_notes.md", "semantic_layer/graph.yml"):
        if (project / rel).is_file():
            rels.append(rel)
    models = project / "semantic_layer" / "models"
    if models.is_dir():
        rels.extend(
            path.relative_to(project).as_posix()
            for path in sorted(models.iterdir())
            if path.is_file() and path.suffix in _MODEL_SUFFIXES
        )
    for section in _OKF_PAGE_SECTIONS:
        root = project / "context_layer" / section
        if root.is_dir():
            rels.extend(
                path.relative_to(project).as_posix()
                for path in sorted(root.rglob("*.md"))
                if path.is_file()
            )
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


def start_proposal(project: str | Path, *, base_revision: str | None = None) -> dict:
    """Start ONE isolated authoring proposal in the fixed data project: a
    system-generated ID, its branch ``ariadne/proposal/<id>`` and its dedicated
    worktree under the ignored ``.ariadne/worktrees/<id>/`` — every location
    derived, never caller-supplied. The base is the optional known revision or
    the current HEAD; a repository with no commits yet gets its human-created
    initial artifact revision first (allowed scope only). Returns the proposal
    ID with its base and candidate revisions (equal until the first edit)."""
    project = Path(project).resolve()
    _require_repo(project)
    _refuse_symlinked_component(project, ARIADNE_STATE_DIR)
    _require_git_identity(project)
    with _file_lock(project / LOCKS_REL / "project.lock"):
        _ensure_state_ignored(project)  # inside the lock: concurrent starts
        # never interleave their exclude-file append
        head = _current_head(project)
        if head is None:
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
            "branch": branch,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _store_record(project, record)
    return {
        "proposal": proposal,
        "base_revision": base,
        "candidate_revision": base,
    }


def read_artifact(
    project: str | Path, proposal: str, rel: str, *, part: int = 1
) -> dict:
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


def _blob_equals(project: Path, revision: str, rel: str, content: str) -> bool:
    """True when ``rel`` at ``revision`` already holds exactly ``content`` (the
    identical-edit no-op check, spec §4: repeating an identical edit against
    its still-current revision must not create another distinct candidate)."""
    blob = _read_blob(project, revision, rel)
    return blob is not None and blob == content.encode("utf-8")


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


def _refuse_untracked_new_artifact(
    project: Path, worktree: Path, rel: str, candidate: str
) -> None:
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
) -> dict:
    """Apply ONE complete artifact edit to the proposal's candidate: the
    expected candidate revision is required and checked BEFORE any write
    (stale or competing writers are refused without overwriting), an identical
    edit at the current revision is a no-op returning the unchanged candidate,
    and a real edit stages EXACTLY the named artifact identity (never ``git
    add .``), commits on the proposal branch and persists the new candidate
    revision durably. An interrupted commit/store leaves the evidence for human
    resolution and blocks further mutations."""
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
        if _blob_equals(project, current, rel, content):
            return {
                "proposal": proposal,
                "revision": current,
                "changed": False,
                "path": rel,
            }  # identical edit: no commit, candidate unchanged
        _refuse_forged_claims(
            rel, content, _read_blob(project, current, rel)
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


# -------------------------------------------- the shared ad-hoc staging operation


def _stage_atomic(directory: Path, stem: str, ext: str, payload: bytes) -> Path:
    """Auto-stage one proposal artifact after successful execution (ADR-0003:
    promotion stays human). Numeric suffix on collision — never overwrites
    (spec §8.11): the O_CREAT|O_EXCL claim is atomic, so racing facade
    processes suffix off each other instead of overwriting (no
    exists()-then-write TOCTOU). Same discipline for the model (.yml) and
    the context page (.md) — spec rev 4 §4. (Moved intact from the Query
    runtime, issue #34/G2.)"""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{ext}"
    suffix = 2
    while True:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            candidate = directory / f"{stem}-{suffix}{ext}"
            suffix += 1
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        return candidate


def stage_ad_hoc(
    staging_dir: str | Path, name: str, envelope: dict, params: dict
) -> tuple[Path, Path]:
    """Stage the COMPILED ad-hoc definition (ADR-0005/spec §6, moved intact
    from the Query runtime): the ephemeral OSI model under
    ``staging/semantic_layer/models/adhoc/`` plus the minimal ``status: draft``
    OKF page under ``staging/context_layer/metrics/`` so ``search_context``
    can discover it — ungoverned, awaiting human promotion, never a Git
    proposal and never an admitted artifact. Query calls exactly this shared
    operation; its legacy staging store and review meaning are unchanged."""
    staging_dir = Path(staging_dir)
    model = _stage_atomic(
        staging_dir / "semantic_layer" / "models" / "adhoc",
        name,
        ".yml",
        yaml.safe_dump(envelope, sort_keys=False).encode("utf-8"),
    )
    page = _stage_atomic(
        staging_dir / "context_layer" / "metrics", name, ".md", _build_adhoc_page(params)
    )
    return model, page
