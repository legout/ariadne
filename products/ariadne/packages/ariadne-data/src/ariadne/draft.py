"""The one active Draft: a project-wide compare-and-set slot (spec 0040 §3.3).

``.ariadne/draft.json`` holds ``{generation, proposal, candidate_revision,
base_served_revision}`` under the project lock. The CLI, the MCP authoring tools
and ``migrate`` all mutate through this module; the proposal engine
(:mod:`ariadne.proposals`) stays underneath as the internal one-proposal-per-
generation machinery, and proposal IDs never appear in the arguments here.

Rules enforced here:

- **First write.** ``expected=None`` means "no active draft": the call creates the
  slot and refuses with a stale message if one exists. Two concurrent first writes
  produce exactly one draft.
- **Every mutation states what it read.** ``expected`` is the ``(generation,
  candidate_revision)`` the caller read; a mismatch refuses before anything is
  written. A refused first write leaves no slot, worktree or branch behind.
- **Discard** retires the slot (the generation number is never reused), moves the
  branch to ``ariadne/discarded/<generation>`` and removes the worktree. A write that
  still names the discarded generation refuses; only an ``expected=None`` first write
  opens a NEW generation.
- **Stale drafts.** The draft is stale once the served revision moved past
  ``base_served_revision``; ``validate`` refuses until :func:`rebase` succeeds.
- **Rebase** is a real ``git rebase`` of the clean draft in its worktree. On conflict
  it aborts and the draft is exactly as before.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ariadne import proposals

DRAFT_REL = proposals.ARIADNE_STATE_DIR / "draft.json"
DISCARDED_BRANCH_PREFIX = "ariadne/discarded/"

# (generation, candidate_revision) the caller read; ``None`` = "no active draft".
Expected = tuple[int, str] | None


# ------------------------------------------------------------------ slot file


def _load_slot(project: Path) -> dict | None:
    """The slot file ({} shape when never created → None). Operator-owned state:
    non-regular, unreadable or malformed content is a human-resolution failure."""
    path = project / DRAFT_REL
    entry = proposals._lstat(path)
    if entry is None:
        return None
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(f"{path}: refusing a non-regular draft slot — inspect it by hand")
    try:
        slot = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path}: unreadable draft slot ({exc}) — this needs human resolution"
        ) from None
    if (
        not isinstance(slot, dict)
        or not isinstance(slot.get("generation"), int)
        or slot.get("state") not in ("active", "retired")
    ):
        raise ValueError(f"{path}: malformed draft slot — this needs human resolution")
    if slot["state"] == "active":
        if not (
            isinstance(slot.get("proposal"), str)
            and isinstance(slot.get("candidate_revision"), str)
            and "base_served_revision" in slot
        ):
            raise ValueError(f"{path}: malformed draft slot — this needs human resolution")
        # The proposal record is authoritative for the candidate: refresh, finalize and
        # reconcile commits move it outside this module, so the slot follows it.
        slot["candidate_revision"] = proposals._load_record(project, slot["proposal"])[
            "candidate_revision"
        ]
    return slot


def _store_slot(project: Path, slot: dict) -> None:
    path = project / DRAFT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(slot, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    proposals._fsync_path(path.parent)


BASELINE_REL = proposals.ARIADNE_STATE_DIR / "source_baseline.json"


def set_source_baseline(project: Path, commit: str) -> None:
    """Record the approved source baseline (spec 0040 §3.4.2.6): the commit holding the
    source declarations a source approval consumed. The next draft starts on it."""
    _store_json(project / BASELINE_REL, {"commit": commit})


def _store_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    proposals._fsync_path(path.parent)


def _is_ancestor(project: Path, ancestor: str, revision: str) -> bool:
    return (
        proposals._git(
            ["merge-base", "--is-ancestor", ancestor, revision], project, check=False
        ).returncode
        == 0
    )


def _default_base(project: Path) -> str | None:
    """The approved source baseline when it still builds on the base a new draft would
    otherwise take (served revision, else HEAD); otherwise None (the engine default)."""
    path = project / BASELINE_REL
    if not path.is_file():
        return None
    try:
        commit = json.loads(path.read_text(encoding="utf-8"))["commit"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(commit, str) or not proposals._COMMIT_RE.fullmatch(commit):
        return None
    if proposals._git(["cat-file", "-e", f"{commit}^{{commit}}"], project, check=False).returncode:
        return None
    parent = _served_revision(project) or proposals._current_head(project)
    if parent is None or parent == commit or not _is_ancestor(project, parent, commit):
        return None
    return commit


def first_write_base(project: str | Path) -> str | None:
    """The revision the NEXT first write would build on: the approved source baseline when
    it still descends from the served revision, else the served revision, else HEAD (None for
    a repository without commits). Callers that read before writing pin THIS value and pass it
    as ``expect_base``; ``mutate`` re-derives it under the project lock and refuses a move."""
    project = Path(project).resolve()
    return _default_base(project) or _served_revision(project) or proposals._current_head(project)


def _served_revision(project: Path) -> str | None:
    from ariadne import admission  # lazy: admission imports proposals at load

    current = admission.load_current(project)
    return None if current is None else current["commit"]


def _view(project: Path, slot: dict | None) -> dict | None:
    if slot is None or slot["state"] != "active":
        return None
    served = _served_revision(project)
    from ariadne import proposals as _p

    evidence = None
    try:
        evidence = _p.load_validation(project, slot["proposal"], slot["candidate_revision"])
    except ValueError:
        evidence = None
    return {
        "validation": (
            "unvalidated"
            if evidence is None
            else ("validated" if evidence.get("ok") else "invalid")
        ),
        "generation": slot["generation"],
        "candidate_revision": slot["candidate_revision"],
        "base_served_revision": slot["base_served_revision"],
        "served_revision": served,
        "stale": served != slot["base_served_revision"],
    }


def status_readonly(project: str | Path) -> dict | None:
    """The active draft's view WITHOUT recovery, locks or any write (diagnosis only): raises
    :class:`UnconfirmedSourceApproval` when a journal or marker exists (never retries, never
    removes). An absent state directory has no draft."""
    project = Path(project).resolve()
    if not (project / proposals.ARIADNE_STATE_DIR).is_dir():
        return None
    if source_txn_pending(project):
        raise UnconfirmedSourceApproval(
            "a source approval is pending recovery — run 'ariadne draft status' to recover it"
        )
    return _view(project, _load_slot(project))


def status(project: str | Path) -> dict | None:
    """The active draft's identity and staleness, or ``None`` without one. Reading first
    completes or undoes an interrupted approval (so a half-finished one never shows)."""
    project = Path(project).resolve()
    if (project / proposals.ARIADNE_STATE_DIR).is_dir():
        with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
            recover(project)
    return _view(project, _load_slot(project))


def proposal_of(project: str | Path, expected: Expected) -> str:
    """The active draft's proposal ID, verified against ``expected`` (internal: for
    callers that already hold the generation they read, e.g. approval)."""
    project = Path(project).resolve()
    slot = _check_expected(_load_slot(project), expected)
    assert slot is not None
    return slot["proposal"]


def _check_expected(slot: dict | None, expected: Expected) -> dict | None:
    """Compare-and-set precondition. Returns the active slot (``expected`` given) or
    ``None`` (first write allowed); raises a stale refusal otherwise."""
    active = slot if slot is not None and slot["state"] == "active" else None
    if expected is None:
        if active is not None:
            raise ValueError(
                f"stale: a draft already exists (generation {active['generation']}, "
                f"candidate {active['candidate_revision'][:12]}) — reread the draft "
                "and retry against it; nothing was written"
            )
        return None
    generation, revision = expected
    if active is None:
        retired = slot["generation"] if slot is not None else None
        raise ValueError(
            f"stale: no active draft (generation {generation} was "
            f"{'discarded' if retired == generation else 'never opened or was retired'}) "
            "— a later write never resurrects a discarded draft; nothing was written"
        )
    if active["generation"] != generation or active["candidate_revision"] != revision:
        raise ValueError(
            f"stale revision: the draft is at generation {active['generation']}, candidate "
            f"{active['candidate_revision'][:12]}; the call read generation {generation}, "
            f"candidate {revision[:12]} — reread and retry; nothing was written"
        )
    return active


def _coherent(project: Path, slot: dict) -> dict:
    """The slot and its proposal record must name the same candidate; otherwise an
    interrupted transition needs human resolution."""
    record = proposals._load_record(project, slot["proposal"])
    if record["candidate_revision"] != slot["candidate_revision"]:
        raise ValueError(
            f"the draft slot names candidate {slot['candidate_revision'][:12]} but its "
            f"proposal record names {record['candidate_revision'][:12]}"
            + proposals._HUMAN_RESOLUTION
        )
    return record


def _preflight(project: Path) -> None:
    proposals._require_repo(project)
    proposals.refuse_unsupported_project(project)
    proposals._refuse_symlinked_component(project, proposals.ARIADNE_STATE_DIR)


# ------------------------------------------------------------------- mutation


def _abandon(project: Path, proposal: str, previous: bytes | None) -> None:
    """Undo a draft this very call created (its first write refused): nothing a
    refused first write opened survives."""
    record = proposals._load_record(project, proposal)
    worktree = project / proposals.WORKTREES_REL / proposal
    proposals._git(["worktree", "remove", "--force", str(worktree)], project, check=False)
    proposals._git(["branch", "-D", record["branch"]], project, check=False)
    (project / proposals.PROPOSALS_REL / f"{proposal}.json").unlink(missing_ok=True)
    path = project / DRAFT_REL
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(previous)


def mutate(
    project: str | Path,
    expected: Expected,
    op: Callable[[str, str], Any],
    *,
    needs_fresh=False,
    base_revision: str | None = None,
    expect_base: str | None = None,
) -> tuple[Any, dict]:
    """Run ``op(proposal, candidate_revision)`` against the draft under the project
    lock, compare-and-set on ``expected``. ``expected=None`` creates the draft first
    (and removes it again when ``op`` refuses). Afterwards the slot's candidate
    revision follows the proposal record (finalize and refresh commits move it).
    Returns ``(op result, draft view)``."""
    project = Path(project).resolve()
    _preflight(project)
    proposals._require_git_identity(project)
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        recover(project)
        slot_before = _load_slot(project)
        previous = (project / DRAFT_REL).read_bytes() if (project / DRAFT_REL).is_file() else None
        if slot_before is not None and slot_before["state"] == "active":
            # an interrupted transition refuses for human resolution BEFORE any
            # revision comparison, whatever the caller read
            proposals._check_coherent(project, _coherent(project, slot_before))
        active = _check_expected(slot_before, expected)
        created: str | None = None
        if active is None:
            # ONE snapshot under the lock: the slot (read above) and the effective base are
            # captured together, and the draft opens on EXACTLY the commit verified here —
            # never on a HEAD read that a native Git commit (no Ariadne lock) may have moved
            base = base_revision or first_write_base(project)
            if expect_base is not None and base != expect_base:
                raise ValueError(
                    "the base this write was prepared against is no longer the base a new draft "
                    "would build on (a release or source approval landed meanwhile) — nothing "
                    "was written; repeat the operation"
                )
            started = proposals.start_proposal(project, base_revision=base, _lock_held=True)
            created = started["proposal"]
            generation = (slot_before["generation"] if slot_before else 0) + 1
            active = {
                "state": "active",
                "generation": generation,
                "proposal": created,
                "candidate_revision": started["candidate_revision"],
                "base_served_revision": _served_revision(project),
            }
            _store_slot(project, active)
        try:
            record = _coherent(project, active)
            if needs_fresh and _view(project, active)["stale"]:  # type: ignore[index]
                raise ValueError(
                    "the draft is stale: the served revision moved past the draft's "
                    "base — run 'draft rebase' first; nothing was written"
                )
            result = op(active["proposal"], active["candidate_revision"])
        except BaseException:
            if created is not None:
                _abandon(project, created, previous)
            raise
        record = proposals._load_record(project, active["proposal"])
        if record["candidate_revision"] != active["candidate_revision"]:
            active = {**active, "candidate_revision": record["candidate_revision"]}
            _store_slot(project, active)
        return result, _view(project, active)  # type: ignore[return-value]


def open_draft(project: str | Path, *, base_revision: str | None = None) -> dict:
    """Open the draft without editing it (the first write with a no-op body)."""
    _result, view = mutate(project, None, lambda _p, _r: None, base_revision=base_revision)
    return view


def active_expected(project: str | Path, proposal: str, expected_revision: str) -> Expected:
    """The compare-and-set precondition for a caller that names the draft's proposal
    and the candidate revision it read: the slot supplies the generation, and a
    proposal that is not the ACTIVE draft's (discarded, retired or never active)
    refuses. Library entry for the proposal-addressed API; CLI and MCP never carry IDs."""
    project = Path(project).resolve()
    slot = _load_slot(project)
    if slot is None or slot["state"] != "active" or slot["proposal"] != proposal:
        raise ValueError(
            f"stale: proposal {proposal} is not the active draft — only one draft is "
            "open at a time and a discarded draft is never resurrected; nothing was written"
        )
    return (slot["generation"], expected_revision)


def edit_artifact(
    project: str | Path, expected: Expected, rel: str, content: str, *, core_generated=False
) -> dict:
    """One complete artifact edit into the draft (the typed edit kinds resolve ``rel``
    in :mod:`ariadne.authoring_edits`)."""
    project = Path(project).resolve()
    result, view = mutate(
        project,
        expected,
        lambda proposal, revision: proposals.edit_proposal(
            project, proposal, revision, rel, content, core_generated=core_generated
        ),
    )
    return {**result, "draft": view}


def edit_pages(
    project: str | Path, expected: Expected, pages: list, *, expect_base: str | None = None
) -> dict:
    """One complete native knowledge-page batch into the draft."""
    project = Path(project).resolve()
    result, view = mutate(
        project,
        expected,
        lambda proposal, revision: proposals.edit_page_batch(project, proposal, revision, pages),
        expect_base=expect_base,
    )
    return {**result, "draft": view}


def apply_migration(
    project: str | Path,
    expected: Expected,
    writes: dict[str, str],
    deletes: tuple[str, ...],
    *,
    expect_base: str | None = None,
) -> dict:
    """The migration commit (spec 0039 §7) written into the active draft."""
    project = Path(project).resolve()
    proposals.check_migration_set(writes, deletes)  # boundary before any state exists
    result, view = mutate(
        project,
        expected,
        lambda proposal, revision: proposals.migration_commit(
            project, proposal, revision, writes, deletes
        ),
        expect_base=expect_base,
    )
    return {**result, "draft": view}


def validate(project: str | Path, expected: Expected) -> dict:
    """Validate the draft at its current generation (refuses a stale draft)."""
    from ariadne import authoring

    project = Path(project).resolve()
    if expected is None:
        raise ValueError("validate needs an existing draft: nothing to validate")
    result, view = mutate(
        project,
        expected,
        lambda proposal, revision: authoring.validate_proposal(project, proposal, revision),
        needs_fresh=True,
    )
    return {**result, "draft": view}


# --------------------------------------------------------------- discard, rebase


def discard(project: str | Path, expected: Expected) -> dict:
    """Retire the draft: the slot is written FIRST (so a crash can never leave a live
    discarded draft), then the branch moves to ``ariadne/discarded/<generation>``
    and the worktree goes. The generation number is never reused."""
    project = Path(project).resolve()
    if expected is None:
        raise ValueError("discard needs the draft's generation and candidate revision")
    _preflight(project)
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        recover(project)
        slot = _check_expected(_load_slot(project), expected)
        assert slot is not None
        record = proposals._load_record(project, slot["proposal"])
        branch = f"{DISCARDED_BRANCH_PREFIX}{slot['generation']}"
        _store_slot(
            project,
            {
                "state": "retired",
                "generation": slot["generation"],
                "discarded_branch": branch,
                "discarded_candidate": slot["candidate_revision"],
            },
        )
        worktree = project / proposals.WORKTREES_REL / slot["proposal"]
        proposals._git(["branch", "-m", record["branch"], branch], project)
        proposals._git(["worktree", "remove", "--force", str(worktree)], project, check=False)
    return {"discarded": True, "generation": slot["generation"], "branch": branch}


@contextmanager
def pinned(project: str | Path, expected: Expected):
    """Hold the project lock and verify the draft is still exactly ``expected`` (generation
    and candidate revision). Bounded reads happen BEFORE this; only the commit (a page write
    or a retained receipt) runs inside, so a concurrent ``discard``/edit makes it refuse
    instead of racing (spec 0040 §3.3.1)."""
    project = Path(project).resolve()
    if expected is None:
        raise ValueError("a pinned commit needs the draft's generation and candidate revision")
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        recover(project)
        _check_expected(_load_slot(project), expected)
        yield


# ------------------------------------------------ approval transaction + recovery

TXN_REL = proposals.ARIADNE_STATE_DIR / "source_txn.json"  # the journal
TXN_COMMITTED_REL = proposals.ARIADNE_STATE_DIR / "source_txn.committed"  # the commit marker
GRANTS_REL = proposals.ARIADNE_STATE_DIR / "source_grants.json"
GRANTS_LOCK_REL = proposals.LOCKS_REL / "grants.lock"


def grants_lock(project: str | Path):
    """The short-lived exclusive lock that orders a source approval against grant readers.
    Order: ``project.lock`` first, then this one; a reader holds it only for the journal check
    and the grants read. ``_file_lock`` is not re-entrant: never take it twice in one chain."""
    return proposals._file_lock(Path(project) / GRANTS_LOCK_REL)


def source_txn_pending(project: str | Path) -> bool:
    """True while a source-approval journal OR committed marker exists: a reader must refuse
    (item 7 and the pending rule of §3.4.2.5) and never fall back to the grants file."""
    project = Path(project)
    return (project / TXN_REL).exists() or (project / TXN_COMMITTED_REL).exists()


class UnresolvedSourceTxn(ValueError):
    """A previous source approval is unresolved (journal or marker present): it must be
    recovered first; a journal is never replaced."""


class CommitSyncPending(OSError):
    """The commit rename happened but its directory sync failed or was interrupted: the
    approval is PENDING until confirmed (spec 0040 §3.4.2.5): no rollback, marker kept, readers
    refused, the next project-lock holder retries the sync."""


class UnconfirmedSourceApproval(ValueError):
    """A source approval's commit marker exists and the directory sync could not be confirmed:
    the approval is PENDING (spec 0040 §3.4.2.5). Draft lookups report it and every draft
    mutation refuses: the baseline and slot are not yet confirmed as approved."""

    command = "ariadne draft status"


class RollbackCleanup(OSError):
    """All three files were restored and the journal is gone; only the cleanup sync after the
    removal failed or was interrupted: a failed approval with a cleanup note."""


class JournalRemnant(OSError):
    """All three files were restored and synced, but the journal could not be removed: the
    approval failed; reads stay refused until the remnant is removed."""


def _read_bytes(path: Path) -> str | None:
    """The file's exact bytes as base64 (the journal round-trips bytes, never normalized text)."""
    return base64.b64encode(path.read_bytes()).decode("ascii") if path.is_file() else None


def begin_source_txn(project: Path) -> None:
    """Journal a source approval BEFORE its three state changes. The journal keeps the
    previous BYTES of the grants, the source baseline and the draft slot. The caller holds the
    project lock AND ``grants.lock`` until the commit or the rollback is complete, and has run
    :func:`recover` first: an unresolved journal or marker is never replaced (refused here)."""
    if source_txn_pending(project):
        raise UnresolvedSourceTxn(
            "a previous source approval is unresolved — run 'ariadne draft status' to recover "
            "it first; nothing was changed"
        )
    _store_json(
        project / TXN_REL,
        {
            "grants": _read_bytes(project / GRANTS_REL),
            "baseline": _read_bytes(project / BASELINE_REL),
            "slot": _read_bytes(project / DRAFT_REL),
        },
    )


def commit_source_txn(project: Path) -> None:
    """THE commit point: rename the journal to the committed marker, then sync the directory.
    A failure of the rename is before the commit point (the caller rolls back). A failed or
    interrupted directory sync leaves the approval PENDING: the marker stays, nothing is rolled
    back or swallowed, and :class:`CommitSyncPending` is raised."""
    os.replace(project / TXN_REL, project / TXN_COMMITTED_REL)
    try:
        proposals._fsync_path((project / TXN_REL).parent)
    except BaseException as exc:  # an interruption takes the same pending path
        raise CommitSyncPending(f"the commit directory sync did not complete: {exc!r}") from exc


def end_source_txn(project: Path) -> None:
    """Post-commit cleanup: remove the committed marker, then sync (best effort)."""
    (project / TXN_COMMITTED_REL).unlink(missing_ok=True)
    try:
        proposals._fsync_path((project / TXN_COMMITTED_REL).parent)
    except OSError:
        pass


def _confirm_committed(project: Path) -> None:
    """Recovery of a committed marker (caller holds both locks): retry the directory sync. A
    FAILED confirmation raises :class:`UnconfirmedSourceApproval` (the approval stays pending:
    marker kept, reads and draft mutations refused). After a SUCCESSFUL confirmation the marker
    removal is cleanup only: its errors are swallowed and a later operation retries it."""
    try:
        proposals._fsync_path((project / TXN_COMMITTED_REL).parent)
    except OSError as exc:
        raise UnconfirmedSourceApproval(
            "a source approval is pending: its commit could not be confirmed (the directory "
            f"sync failed: {exc}); no draft operation can proceed until it is — fix the "
            "cause and run 'ariadne draft status' to retry; nothing was changed"
        ) from exc
    try:
        end_source_txn(project)
    except OSError:
        pass


def _restore(path: Path, data: bytes | None) -> None:
    if data is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)


def rollback_source_txn(project: Path) -> None:
    """Restore the grants, the baseline and the slot to the journaled bytes (identical bytes:
    idempotent), then remove the journal. The caller holds the project lock and ``grants.lock``.
    A failure leaves the journal in place so the next project-lock holder finishes the job; a
    failure only of the journal's own removal is :class:`JournalRemnant` (restoration durable)."""
    journal = project / TXN_REL
    if not journal.is_file():
        return
    try:
        txn = json.loads(journal.read_text(encoding="utf-8"))
        previous = {
            k: (None if txn[k] is None else base64.b64decode(txn[k]))
            for k in ("grants", "baseline", "slot")
        }
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(
            f"{journal}: unreadable approval journal — this needs human resolution"
        ) from None
    _restore(project / GRANTS_REL, previous["grants"])
    _restore(project / BASELINE_REL, previous["baseline"])
    _restore(project / DRAFT_REL, previous["slot"])
    proposals._fsync_path(journal.parent)  # the three restored states are durable here
    try:
        journal.unlink()
    except OSError as exc:
        raise JournalRemnant(f"the journal could not be removed: {exc}") from exc
    try:
        proposals._fsync_path(journal.parent)  # deletion cleanup only
    except BaseException as exc:  # an interruption here is still only cleanup of a done rollback
        raise RollbackCleanup(
            f"the cleanup sync after the journal removal failed: {exc!r}"
        ) from exc


def recover(project: Path) -> None:
    """Complete or undo an interrupted approval. The caller holds the project lock.

    - A source-approval journal (``source_txn.json``) means the approval never committed: the
      grants, baseline and slot return to their journaled bytes and the journal is removed. A
      ``source_txn.committed`` marker: the directory sync is retried; on success the marker is
      removed (the grant stays effective), on failure the approval stays pending.
    - A calculation approval whose release is already serving but whose generation was never
      retired (a failure after ``current.json`` was published) retires it now."""
    from ariadne import admission  # lazy: admission imports this module

    if source_txn_pending(project):
        with grants_lock(project):  # project.lock (held by the caller) first, then grants.lock
            if (project / TXN_REL).exists():
                rollback_source_txn(project)  # uncommitted: undo all three files
            elif (project / TXN_COMMITTED_REL).exists():
                _confirm_committed(project)  # committed: retry the sync; success admits readers
    slot = _load_slot(project)
    if slot is not None and slot["state"] == "active":
        served = admission.load_current(project)
        if (
            served is not None
            and served["proposal"] == slot["proposal"]
            and served["commit"] == slot["candidate_revision"]
        ):
            consume(project, slot["proposal"])


def consume(project: Path, proposal: str) -> None:
    """Retire the slot after its generation was approved (spec 0040 §3.4.2.6). The
    CALLER holds the project lock (approval activation does). Only the named
    proposal's own active slot retires; the proposal branch stays as history."""
    slot = _load_slot(project)
    if slot is not None and slot["state"] == "active" and slot["proposal"] == proposal:
        _store_slot(
            project,
            {
                "state": "retired",
                "generation": slot["generation"],
                "consumed_candidate": slot["candidate_revision"],
            },
        )


def rebase(project: str | Path, expected: Expected) -> dict:
    """Rebase the clean draft onto the served revision (spec 0040 §3.3.4). On success
    the new candidate and base are recorded, the generation increments and every
    validation of the old revision stops binding. On conflict the rebase is aborted
    and the draft, its branch and its slot stay exactly as before; the conflicting
    files are named. Conflicts are never auto-resolved."""
    from ariadne import admission

    project = Path(project).resolve()
    if expected is None:
        raise ValueError("rebase needs the draft's generation and candidate revision")
    _preflight(project)
    proposals._require_git_identity(project)
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        recover(project)
        slot = _check_expected(_load_slot(project), expected)
        assert slot is not None
        record = _coherent(project, slot)
        proposals._check_coherent(project, record)  # clean worktree on the recorded branch
        served = _served_revision(project)
        if served is None or served == slot["base_served_revision"]:
            raise ValueError("the draft is not stale: nothing to rebase onto")
        worktree = project / proposals.WORKTREES_REL / slot["proposal"]
        proc = proposals._git(["rebase", served], worktree, check=False)
        if proc.returncode != 0:
            files = proposals._git(
                ["diff", "--name-only", "--diff-filter=U"], worktree, check=False
            ).stdout.split()
            proposals._git(["rebase", "--abort"], worktree, check=False)
            raise ValueError(
                "rebase conflict — the draft is unchanged; resolve by editing the "
                f"draft: conflicting files: {', '.join(sorted(files)) or '(unknown)'}"
            )
        head = proposals._git(["rev-parse", "HEAD"], worktree).stdout.strip()
        admission.reconcile(project, slot["proposal"], slot["candidate_revision"], head)
        new = {
            **slot,
            "generation": slot["generation"] + 1,
            "candidate_revision": head,
            "base_served_revision": served,
        }
        _store_slot(project, new)
        return {"rebased": True, "draft": _view(project, new)}
