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

from ariadne import approve, authoring_sources, draft, proposals  # noqa: E402
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


def test_a_late_failure_during_source_approval_leaves_no_grant_and_the_draft_active(
    tmp_path, monkeypatch
):
    """Finding 1: grant, baseline and draft retirement are one recoverable transaction.
    A failure after the live checks (baseline write) preserves grants, baseline and draft."""
    project, _api, result = _project_with_new_source(tmp_path)
    slot_before = (project / draft.DRAFT_REL).read_bytes()

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(draft, "set_source_baseline", boom)
    with pytest.raises(OSError, match="disk full"):
        _run(project, Tty())
    monkeypatch.undo()

    assert not (project / GRANTS).exists()  # no effective grant
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["approved"] is False
    assert (project / draft.DRAFT_REL).read_bytes() == slot_before  # the draft is still active
    assert not (project / draft.BASELINE_REL).exists()
    assert not (project / draft.TXN_REL).exists()  # the journal is closed


def test_a_failure_writing_the_slot_during_source_approval_rolls_back_the_baseline(
    tmp_path, monkeypatch
):
    project, _api, _result = _project_with_new_source(tmp_path)
    slot_before = (project / draft.DRAFT_REL).read_bytes()
    monkeypatch.setattr(draft, "consume", lambda *_a, **_k: (_ for _ in ()).throw(OSError("io")))
    with pytest.raises(OSError):
        _run(project, Tty())
    monkeypatch.undo()
    assert not (project / GRANTS).exists()
    assert not (project / draft.BASELINE_REL).exists()
    assert (project / draft.DRAFT_REL).read_bytes() == slot_before


def test_a_crash_after_the_grant_commit_rolls_forward_on_the_next_draft_operation(
    tmp_path, monkeypatch
):
    """Only a committed grant authorizes reads; a journal left behind AFTER the grant was
    written is dropped, not rolled back (the grant stays effective)."""
    project, _api, result = _project_with_new_source(tmp_path)
    monkeypatch.setattr(draft, "end_source_txn", lambda *_a, **_k: None)  # crash before close
    outcome, _shown = _run(project, Tty())
    monkeypatch.undo()
    assert outcome["approved"] == "sources" and (project / draft.TXN_REL).exists()
    assert draft.status(project) is None  # recovery under the lock; the grant survives
    assert not (project / draft.TXN_REL).exists()
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["approved"] is True


def test_a_failure_after_activation_reports_success_and_the_slot_self_heals(tmp_path, monkeypatch):
    """Finding 1: once current.json is published, a failing `draft.consume` is
    post-activation cleanup: the release is serving, the call reports success and the next
    draft operation retires the consumed generation."""
    from ariadne import admission
    from tests.test_git_admission import _policy_edit, admitted_ready

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Healed body."))
    real_consume = draft.consume
    monkeypatch.setattr(draft, "consume", lambda *_a, **_k: (_ for _ in ()).throw(OSError("io")))
    composite = admission.overall_review(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        destination=tmp_path / "published",
        expected_current="none",
    )
    out = admission.admit_revision(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        confirmed_by="human:test",
        overall_preview=composite,
        confirmed_overall_digest=composite["digest"],
    )
    monkeypatch.setattr(draft, "consume", real_consume)
    assert out["commit"] == review["revision"]  # success is reported; the release is serving
    served = admission.load_current(project)
    assert served is not None and served["commit"] == review["revision"]
    assert draft.status(project) is None  # self-healed: the consumed generation is retired


# ------------------------------------------------ finding 3: what the prompt shows


def test_add_refuses_a_source_path_with_a_control_character(tmp_path):
    """Finding 3 (security): a control character (ESC, CR) in a source path could disguise
    the consent target on the terminal — refused at entry validation."""
    for bad in ("data/ok.parquet\x1b[2K\rdata/evil.parquet", "data/a\rb.parquet"):
        with pytest.raises(ValueError, match="control character"):
            authoring_sources.add_sources(
                complete_bundle_project(tmp_path / str(abs(hash(bad)))),
                None,
                [{"name": "x", "type": "parquet", "path": bad}],
            )


def test_the_display_escapes_control_characters_in_every_untrusted_field():
    assert approve.esc("a\x1b[31mb\rc\u0085d") == "a\\x1b[31mb\\x0dc\\x85d"


def test_the_source_prompt_shows_the_new_identity_and_the_grant_delta(tmp_path):
    project, _api, _result = _project_with_new_source(tmp_path)
    _outcome, shown = _run(project, Tty())
    assert "NEW source" in shown and "extra" in shown and "extra.parquet" in shown
    assert "Grant delta: 3 source(s)" in shown and "read-only" in shown  # events, labels, extra


def test_a_changed_source_shows_the_old_and_the_new_identity(tmp_path):
    project, _api, _result = _project_with_new_source(tmp_path)
    _run(project, Tty())  # grant all three sources first
    write_parquet(project / "data" / "extra2.parquet", [(1,)], ["n"])
    # a new draft changes the path of the granted source "extra" (a registry edit)
    first = draft.edit_artifact(project, None, "data/seed_notes.md", "x\n")["draft"]
    import yaml

    doc = yaml.safe_load(
        proposals.read_artifact(project, draft_proposal(project), "ariadne.yaml")["content"]
    )
    for entry in doc["sources"]:
        if entry["name"] == "extra":
            entry["path"] = "data/extra2.parquet"
    draft.edit_artifact(
        project,
        (first["generation"], draft.status(project)["candidate_revision"]),
        "ariadne.yaml",
        yaml.safe_dump(doc, sort_keys=False),
    )
    # the seed-notes edit is not a source change: remove it so the draft is sources-only
    view = draft.status(project)
    draft.edit_artifact(
        project,
        (view["generation"], view["candidate_revision"]),
        "data/seed_notes.md",
        (project / "data" / "seed_notes.md").read_text(encoding="utf-8"),
    )
    _outcome, shown = _run(project, Tty())
    assert "CHANGED source extra" in shown
    assert "    - extra: parquet" in shown and "extra.parquet" in shown
    assert "    + extra: parquet" in shown and "extra2.parquet" in shown


def draft_proposal(project):
    view = draft.status(project)
    return draft.proposal_of(project, (view["generation"], view["candidate_revision"]))


def test_an_unreachable_source_times_out_within_the_host_deadline_not_the_lock(
    tmp_path, monkeypatch
):
    """Finding 3: the live checks draw the host-owned deadline, so an unreachable remote
    cannot hold the project lock indefinitely."""
    seen = {}
    real = approve.execution.DuckDBExecution

    class Spy(real):
        def __init__(self, registry, **kwargs):
            seen["budget"] = kwargs.get("budget")
            super().__init__(registry, **kwargs)

    monkeypatch.setattr(approve.execution, "DuckDBExecution", Spy)
    project, _api, _result = _project_with_new_source(tmp_path)
    _run(project, Tty())
    assert seen["budget"] is not None and seen["budget"].seconds > 0
