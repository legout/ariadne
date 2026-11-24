"""The one active Draft slot (spec 0040 §3.3; AC6, AC7, AC8): project-wide
compare-and-set, discard, stale detection and rebase. Real temporary Git
repositories; expected values are hand-worked from the spec."""

import json
import os
import sys
import threading
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import admission, draft, proposals  # noqa: E402
from tests.test_git_authoring import complete_bundle_project, run_git  # noqa: E402

SEED_REL = "data/seed_notes.md"


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _read(project: Path) -> dict:
    return json.loads((project / draft.DRAFT_REL).read_text(encoding="utf-8"))


def _first_edit(project: Path, text: str = "first\n") -> dict:
    return draft.edit_artifact(project, None, SEED_REL, text)


def _serve(project: Path, monkeypatch, revision: str | None):
    """Stand in for an approval: the served revision the draft's staleness reads."""
    monkeypatch.setattr(draft, "_served_revision", lambda _project: revision)


def test_first_write_creates_exactly_one_draft_and_the_loser_refuses_stale(tmp_path):
    project = complete_bundle_project(tmp_path)
    results: list = []

    def attempt(text: str) -> None:
        try:
            results.append(("ok", draft.edit_artifact(project, None, SEED_REL, text)))
        except ValueError as exc:
            results.append(("refused", str(exc)))

    threads = [threading.Thread(target=attempt, args=(f"writer {i}\n",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(kind for kind, _ in results) == ["ok", "refused"]
    assert "stale" in next(value for kind, value in results if kind == "refused")
    assert _read(project)["generation"] == 1
    # exactly one proposal record and one worktree exist
    assert len(list((project / proposals.PROPOSALS_REL).glob("*.json"))) == 1
    assert len(list((project / proposals.WORKTREES_REL).iterdir())) == 1


def test_stale_generation_or_revision_refuses_and_writes_nothing(tmp_path):
    project = complete_bundle_project(tmp_path)
    first = _first_edit(project)["draft"]
    assert first["generation"] == 1
    head = run_git(project, "rev-parse", f"ariadne/proposal/{_read(project)['proposal']}").strip()

    with pytest.raises(ValueError, match="stale"):
        draft.edit_artifact(project, (2, first["candidate_revision"]), SEED_REL, "x\n")
    with pytest.raises(ValueError, match="stale"):
        draft.edit_artifact(project, (1, "0" * 40), SEED_REL, "x\n")
    assert (
        run_git(project, "rev-parse", f"ariadne/proposal/{_read(project)['proposal']}").strip()
        == head
    )

    moved = draft.edit_artifact(project, (1, first["candidate_revision"]), SEED_REL, "second\n")
    assert moved["changed"] is True
    assert moved["draft"]["candidate_revision"] != first["candidate_revision"]
    # the slot follows: the previous candidate is now stale
    with pytest.raises(ValueError, match="stale"):
        draft.edit_artifact(project, (1, first["candidate_revision"]), SEED_REL, "third\n")


def test_refused_first_write_leaves_no_draft_behind(tmp_path):
    project = complete_bundle_project(tmp_path)
    with pytest.raises(ValueError):
        draft.edit_artifact(project, None, "../escape.md", "x\n")
    assert not (project / draft.DRAFT_REL).exists()
    assert not (project / proposals.WORKTREES_REL).exists() or not any(
        (project / proposals.WORKTREES_REL).iterdir()
    )
    assert run_git(project, "branch", "--list", "ariadne/proposal/*").strip() == ""


def test_discard_keeps_branch_and_is_never_resurrected(tmp_path):
    project = complete_bundle_project(tmp_path)
    first = _first_edit(project)["draft"]
    proposal = _read(project)["proposal"]

    out = draft.discard(project, (1, first["candidate_revision"]))
    assert out["branch"] == "ariadne/discarded/1"
    assert draft.status(project) is None
    kept = run_git(project, "rev-parse", "ariadne/discarded/1").strip()
    assert kept == first["candidate_revision"]
    assert run_git(project, "branch", "--list", f"ariadne/proposal/{proposal}").strip() == ""

    # a write that still names the discarded generation refuses ...
    with pytest.raises(ValueError, match="never resurrects"):
        draft.edit_artifact(project, (1, first["candidate_revision"]), SEED_REL, "late\n")
    assert draft.status(project) is None
    # ... and only a first write opens a NEW generation
    again = _first_edit(project, "fresh\n")["draft"]
    assert again["generation"] == 2
    assert run_git(project, "rev-parse", "ariadne/discarded/1").strip() == kept


def test_retire_stale_retires_a_draft_whose_record_points_elsewhere(tmp_path):
    """A restored project's slot names a proposal record stamped with the old path:
    every slot read refuses, retire_stale still retires it without loading the record."""
    project = complete_bundle_project(tmp_path)
    first = _first_edit(project)["draft"]
    record_path = project / proposals.PROPOSALS_REL / f"{_read(project)['proposal']}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record_path.write_text(json.dumps({**record, "project": "/elsewhere"}), encoding="utf-8")
    # an interrupted source approval whose journal holds the old ACTIVE slot
    draft.begin_source_txn(project)
    with pytest.raises(ValueError, match="belongs to"):
        draft.status(project)

    assert draft.retire_stale(project)["state"] == "retired"
    assert not draft.source_txn_pending(project)  # the journal cannot resurrect the slot
    assert draft.retire_stale(project)["state"] == "retired"  # idempotent
    assert draft.status(project) is None
    with pytest.raises(ValueError, match="never resurrects"):
        draft.edit_artifact(project, (1, first["candidate_revision"]), SEED_REL, "late\n")
    assert _first_edit(project, "fresh\n")["draft"]["generation"] == 2


def test_stale_draft_refuses_validate_until_rebase(tmp_path, monkeypatch):
    project = complete_bundle_project(tmp_path)
    head = run_git(project, "rev-parse", "HEAD").strip()
    _serve(project, monkeypatch, head)
    first = _first_edit(project)["draft"]
    assert first["stale"] is False

    _serve(project, monkeypatch, "f" * 40)
    stale = draft.status(project)
    assert stale is not None and stale["stale"] is True
    with pytest.raises(ValueError, match="stale"):
        draft.validate(project, (1, first["candidate_revision"]))


def _advance_served(project: Path, monkeypatch, rel: str, text: str) -> str:
    """Land a commit on the project's main line and declare it the served revision."""
    (project / rel).write_text(text, encoding="utf-8")
    run_git(project, "add", "--", rel)
    run_git(project, "commit", "-q", "-m", "served change")
    served = run_git(project, "rev-parse", "HEAD").strip()
    _serve(project, monkeypatch, served)
    return served


def test_clean_rebase_moves_base_bumps_generation_and_drops_validation(tmp_path, monkeypatch):
    project = complete_bundle_project(tmp_path)
    base = run_git(project, "rev-parse", "HEAD").strip()
    _serve(project, monkeypatch, base)
    first = _first_edit(project)["draft"]
    proposal = _read(project)["proposal"]
    # stored validation evidence of the old revision
    proposals.store_validation(
        project,
        {"proposal": proposal, "commit": first["candidate_revision"], "status": "validated"},
    )
    served = _advance_served(project, monkeypatch, "data/docs/notes.md", "# Rule notes, served\n")

    out = draft.rebase(project, (1, first["candidate_revision"]))["draft"]
    assert out["generation"] == 2
    assert out["base_served_revision"] == served
    assert out["stale"] is False
    assert out["candidate_revision"] != first["candidate_revision"]
    # the draft now sits on the served commit and keeps its own edit
    assert run_git(project, "merge-base", "--is-ancestor", served, out["candidate_revision"]) == ""
    assert run_git(project, "show", f"{out['candidate_revision']}:{SEED_REL}") == "first\n"
    # the old revision's evidence no longer binds the new candidate
    assert proposals.load_validation(project, proposal, out["candidate_revision"]) is None
    assert admission  # imported for the reconcile contract


def test_conflicting_rebase_leaves_draft_exactly_as_before(tmp_path, monkeypatch):
    project = complete_bundle_project(tmp_path)
    base = run_git(project, "rev-parse", "HEAD").strip()
    _serve(project, monkeypatch, base)
    first = _first_edit(project, "draft side\n")["draft"]
    slot_before = (project / draft.DRAFT_REL).read_bytes()
    _advance_served(project, monkeypatch, SEED_REL, "served side\n")

    with pytest.raises(ValueError, match=r"conflict.*data/seed_notes\.md"):
        draft.rebase(project, (1, first["candidate_revision"]))

    assert (project / draft.DRAFT_REL).read_bytes() == slot_before
    proposal = _read(project)["proposal"]
    worktree = project / proposals.WORKTREES_REL / proposal
    assert run_git(worktree, "rev-parse", "HEAD").strip() == first["candidate_revision"]
    assert run_git(worktree, "status", "--porcelain", "--untracked-files=no") == ""
    assert not (worktree / ".git").is_dir()  # a worktree file, never a rebase-in-progress
    assert run_git(project, "rev-parse", "--git-dir").strip()
    assert (worktree / SEED_REL).read_text(encoding="utf-8") == "draft side\n"
