"""``approve`` (spec 0040 §3.4–3.5; AC2, AC3, AC7, AC10): the source-first gate, the
no-TTY refusal, edits during the prompt and the sources-only guarantee that the served
release is untouched. Real temporary Git repositories; expected values are hand-worked
from the spec. Fake terminals stand in for the pty (the real pty path is verified at V)."""

import io
import json
import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import approve, authoring_sources, draft  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from tests.test_git_authoring import complete_bundle_project, write_parquet  # noqa: E402

CURRENT = Path(".ariadne/current.json")
GRANTS = Path(".ariadne/source_grants.json")


class Tty(io.StringIO):
    """A terminal double: ``isatty`` is true; ``before_answer`` runs when the prompt is
    answered (to model an edit between display and "yes")."""

    def __init__(self, answer="yes\n", before_answer=None, tty=True):
        super().__init__(answer)
        self._tty, self._hook = tty, before_answer

    def isatty(self):
        return self._tty

    def readline(self, *args):
        if self._hook:
            self._hook()
        return super().readline(*args)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _project_with_new_source(tmp_path, name="extra", rows=2):
    project = complete_bundle_project(tmp_path)
    write_parquet(project / "data" / f"{name}.parquet", [(i,) for i in range(rows)], ["n"])
    # the fixture's own two sources are part of the base; grant them as the baseline
    api = AuthoringProject(project)
    entry = authoring_sources.source_entry(f"data/{name}.parquet", name=name)
    result = authoring_sources.add_sources(project, None, [entry])
    return project, api, result


def _run(project, stdin, *, out_tty=True, **kw):
    out = io.StringIO()
    out.isatty = lambda: out_tty  # type: ignore[method-assign]
    return approve.approve(project, stdin=stdin, stdout=out, **kw), out.getvalue()


def test_approve_without_a_terminal_refuses_and_changes_nothing(tmp_path):
    project, _api, _result = _project_with_new_source(tmp_path)
    before = (project / draft.DRAFT_REL).read_bytes()
    with pytest.raises(approve.ApprovalRefused, match="interactive terminal"):
        _run(project, Tty(tty=False))
    with pytest.raises(approve.ApprovalRefused, match="interactive terminal"):
        _run(project, Tty(), out_tty=False)
    assert (project / draft.DRAFT_REL).read_bytes() == before
    assert not (project / GRANTS).exists()


def test_a_sources_only_approval_grants_without_touching_the_served_release(tmp_path):
    project, _api, result = _project_with_new_source(tmp_path)
    served_before = (project / CURRENT).read_bytes() if (project / CURRENT).exists() else None

    outcome, shown = _run(project, Tty())

    assert outcome["approved"] == "sources"
    assert "extra" in outcome["sources"]
    assert "no source has been read" in shown  # offline display precedes consent
    grants = json.loads((project / GRANTS).read_text(encoding="utf-8"))["grants"]
    assert "extra" in {g["source"]["name"] for g in grants}
    assert {g["by"] for g in grants} == {"human:Ariadne Tests <tests@ariadne.local>"}
    # the served state is byte-identical; the generation is consumed (no active draft)
    served_after = (project / CURRENT).read_bytes() if (project / CURRENT).exists() else None
    assert served_after == served_before
    assert draft.status(project) is None
    # a calculation draft now sees the granted source as already approved
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["approved"] is True


def test_a_refused_prompt_leaves_no_grant_and_the_draft_open(tmp_path):
    project, _api, _result = _project_with_new_source(tmp_path)
    with pytest.raises(approve.ApprovalRefused, match="no grant was written"):
        _run(project, Tty("no\n"))
    assert not (project / GRANTS).exists()
    assert draft.status(project) is not None


def test_a_failed_live_check_after_yes_writes_no_grant(tmp_path):
    project = complete_bundle_project(tmp_path)
    entry = authoring_sources.source_entry("data/missing.parquet", name="missing")
    authoring_sources.add_sources(project, None, [entry])  # declared; the file does not exist
    with pytest.raises(Exception):  # the bounded live check fails inside the transaction
        _run(project, Tty())
    assert not (project / GRANTS).exists()  # AC2: no grant from a failed approval
    assert draft.status(project) is not None  # the draft is not consumed


def test_a_draft_that_adds_a_source_and_a_model_edit_is_refused_as_mixed(tmp_path):
    project, _api, _result = _project_with_new_source(tmp_path)
    view = draft.status(project)
    assert view is not None
    draft.edit_artifact(
        project, (view["generation"], view["candidate_revision"]), "data/seed_notes.md", "x\n"
    )
    with pytest.raises(approve.ApprovalRefused, match="approve the sources first"):
        _run(project, Tty())
    assert not (project / GRANTS).exists()


def test_an_edit_during_the_prompt_makes_the_approval_refuse(tmp_path):
    project, _api, _result = _project_with_new_source(tmp_path)

    def edit_now():
        view = draft.status(project)
        assert view is not None
        draft.edit_artifact(
            project, (view["generation"], view["candidate_revision"]), "data/seed_notes.md", "y\n"
        )

    with pytest.raises(approve.ApprovalRefused, match="changed during the prompt"):
        _run(project, Tty(before_answer=edit_now))
    assert not (project / GRANTS).exists()
