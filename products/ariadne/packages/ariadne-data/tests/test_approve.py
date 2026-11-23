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
        (first["generation"], _view(project)["candidate_revision"]),
        "ariadne.yaml",
        yaml.safe_dump(doc, sort_keys=False),
    )
    # the seed-notes edit is not a source change: remove it so the draft is sources-only
    view = _view(project)
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


def _view(project):
    view = draft.status(project)
    assert view is not None
    return view


def draft_proposal(project):
    view = _view(project)
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


# ------------------------------- the real `ariadne approve` on a pty (AC10, finding 3)


def _run_on_pty(project, answer, *, before_answer=None, extra=()):
    """Run ``python -m ariadne.cli approve`` on a REAL pty: wait for the prompt, run
    ``before_answer`` (an action between display and "yes"), then answer. Returns
    ``(exit_code, terminal_output)``."""
    import pty
    import select
    import subprocess

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-m", "ariadne.cli", "approve", "--project", str(project), *extra],
        env=os.environ.copy(),
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    output, answered = b"", False
    while True:
        ready, _, _ = select.select([master], [], [], 60)
        if not ready:
            proc.kill()
            raise AssertionError(f"pty timeout: {output.decode(errors='replace')}")
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if not answered and b"[yes/no]" in output:
            answered = True
            if before_answer:
                before_answer()
            os.write(master, answer.encode() + b"\n")
    code = proc.wait(timeout=60)
    os.close(master)
    return code, output.decode(errors="replace")


def _active(project):
    view = draft.status(project)
    assert view is not None, "an active draft is expected"
    return view


def _profile_pair(project, tmp_path, monkeypatch):
    """The private profile pair ``approve`` reads, written the supported way."""
    from ariadne import profile_pair

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lumio = tmp_path / "home" / "lumio-profile.json"
    lumio.parent.mkdir(parents=True, exist_ok=True)
    lumio.write_text("{}\n", encoding="utf-8")
    sibling = profile_pair.sibling_path(lumio)
    settings = profile_pair.default_sibling("pty")
    settings["publication_destination"] = str(tmp_path / "published")
    profile_pair.write_private(sibling, json.dumps(settings))
    profile_pair.record(project, lumio, sibling)


@pytest.fixture
def pty_project(tmp_path, monkeypatch):
    """A project with a served release A and a calculation draft on it."""
    from tests.test_git_admission import _policy_edit, admitted_ready
    from tests.test_git_authoring import admit_library

    project = complete_bundle_project(tmp_path)
    _profile_pair(project, tmp_path, monkeypatch)
    api = AuthoringProject(project)
    review_a, _ = admitted_ready(api, project, _policy_edit("Served rule A."))
    assert admit_library(project, review_a, destination=tmp_path / "published") == 0
    draft_b = api.start_proposal()
    api.edit_pages_batch(
        draft_b["proposal"],
        draft_b["candidate_revision"],
        _policy_edit("Draft rule B.\rCR-line\u0085NEL-line\x1b[31mESC"),
    )
    return project, review_a


def test_the_calculation_prompt_shows_the_change_and_approves_exactly_that_revision(pty_project):
    from ariadne import admission

    project, review_a = pty_project
    pinned = _active(project)["candidate_revision"]
    code, shown = _run_on_pty(project, "yes")
    assert code == 0, shown
    assert "Calculation approval of draft revision " + pinned[:12] in shown
    assert "Draft rule B." in shown and "Served rule A." in shown  # the changed content
    # control characters inside a page are escaped INSIDE their own diff record: no raw CR/NEL/ESC
    # reaches the terminal as a display line boundary or sequence
    assert "Draft rule B.\\x0dCR-line\\x85NEL-line\\x1b[31mESC" in shown
    assert "\x1b[31m" not in shown and "\x85" not in shown
    served = admission.load_current(project)
    assert served is not None and served["commit"] != review_a["revision"]
    assert served["commit"] == pinned  # exactly the revision the prompt displayed
    assert draft.status(project) is None


def test_an_edit_during_the_calculation_prompt_refuses_on_a_real_terminal(pty_project):
    from ariadne import admission
    from tests.test_git_admission import _policy_edit

    project, review_a = pty_project

    def edit_now():
        view = _active(project)
        draft.edit_pages(
            project,
            (view["generation"], view["candidate_revision"]),
            _policy_edit("Edited during the prompt."),
        )

    code, shown = _run_on_pty(project, "yes", before_answer=edit_now)
    assert code == 1 and "nothing" in shown
    served = admission.load_current(project)
    assert served is not None and served["commit"] == review_a["revision"]  # A still serves


def test_a_served_base_that_changes_between_display_and_yes_refuses(pty_project):
    from ariadne import admission
    from tests.test_git_authoring import admit_library

    project, _review_a = pty_project

    def another_operator_approves_the_same_draft():
        view = _active(project)
        proposal = draft.proposal_of(project, (view["generation"], view["candidate_revision"]))
        review = AuthoringProject(project).review_proposal(proposal)
        assert admit_library(project, review) == 0

    code, shown = _run_on_pty(
        project, "yes", before_answer=another_operator_approves_the_same_draft
    )
    assert code == 1 and "changed between display and confirmation" in shown, shown
    served = admission.load_current(project)
    assert served is not None  # the other approval's release serves; this one added nothing


def test_a_directory_sync_failure_after_grant_replacement_rolls_everything_back(
    tmp_path, monkeypatch
):
    """Finding 1 (second pass): one injected directory-sync error AFTER the grant file was
    replaced must leave the previous grants, the baseline and the active draft — never an
    effective grant behind a failed approval."""
    project, _api, result = _project_with_new_source(tmp_path)
    slot_before = (project / draft.DRAFT_REL).read_bytes()
    real_sync = proposals._fsync_path
    fired = {"done": False}

    def sync(path):
        # the directory sync right after the grant file was replaced
        if not fired["done"] and (project / GRANTS).exists():
            fired["done"] = True
            raise OSError("dir sync failed")
        return real_sync(path)

    monkeypatch.setattr(proposals, "_fsync_path", sync)
    with pytest.raises(OSError, match="dir sync failed"):
        _run(project, Tty())
    monkeypatch.undo()
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["approved"] is False
    assert not (project / GRANTS).exists()
    assert (project / draft.DRAFT_REL).read_bytes() == slot_before
    assert not (project / draft.BASELINE_REL).exists()
    assert not (project / draft.TXN_REL).exists()


def test_a_journal_cleanup_failure_after_the_grant_is_not_a_failed_approval(tmp_path, monkeypatch):
    project, _api, result = _project_with_new_source(tmp_path)

    def boom(*_a, **_k):
        raise OSError("unlink failed")

    monkeypatch.setattr(draft, "end_source_txn", boom)
    outcome, _shown = _run(project, Tty())
    monkeypatch.undo()
    assert outcome["approved"] == "sources"
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["approved"] is True
    assert draft.status(project) is None  # recovery drops the journal; the grant survives


def test_a_changed_endpoint_is_granted_then_reads_refuse_by_name_until_the_calculation_approval(
    tmp_path, monkeypatch, capsys
):
    """AC4 (amended 0040 §3.4.2.7) through the real CLI: the operator sees A served, grants B
    (same DSN variable, other destination) with `approve`, and `query`/`detail` then REFUSE
    naming the source and the pending calculation approval — they never read B, and the
    served state stays byte-identical. The offline fixture shapes the served record (a live
    Postgres admission cannot run offline; the binding values are hand-written from 0025 §4)."""
    from ariadne import admission
    from ariadne.cli import main as cli
    from tests.test_git_admission import _policy_edit, admitted_ready
    from tests.test_git_authoring import admit_library

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _ = admitted_ready(api, project, _policy_edit("Served rule A."))
    assert admit_library(project, review, destination=tmp_path / "published") == 0
    record = admission.load_current(project)
    assert record is not None
    env = "ARIADNE_TEST_PG_DSN"
    monkeypatch.setenv(env, "postgresql://owner:pw-a@db-a.internal:5432/app")
    entry = {"name": "pg", "type": "postgres", "connection_env": env, "read_only": True}
    binding_a = {
        "host": ["db-a.internal"],
        "hostaddr": [],
        "port": ["5432"],
        "dbname": "app",
        "user": "owner",
    }
    declared = record.get("source_declaration_digest") or record["source_digest"]
    shaped = {**record, "sources": [*record["sources"], entry]}
    shaped["storage_bindings"] = {"postgres:pg": binding_a}
    shaped["source_digest"] = authoring_sources.approval_digest(
        declared, {"postgres:pg": binding_a}
    )
    (project / CURRENT).write_text(json.dumps(shaped), encoding="utf-8")
    served_bytes = (project / CURRENT).read_bytes()

    # the environment now points the same variable at B; the operator declares and grants it
    monkeypatch.setenv(env, "postgresql://owner:pw-b@db-b.internal:5432/app")
    authoring_sources.add_sources(
        project, None, [authoring_sources.source_entry(env, name="pg", type="postgres")]
    )

    class NoRemote:  # the live check is the only network step; the approval offline-stubs it
        catalog: list = []

        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

    monkeypatch.setattr(approve.execution, "DuckDBExecution", NoRemote)
    outcome, _shown = _run(project, Tty())
    assert outcome["approved"] == "sources"

    request = tmp_path / "detail.json"
    request.write_text('{"dataset": "events", "fields": ["id"]}', encoding="utf-8")
    capsys.readouterr()
    for argv in (
        ["query", "event_count", "--json", "--project", str(project)],
        ["detail", "--project", str(project), "--file", str(request)],
    ):
        code = cli(argv)
        captured = capsys.readouterr()
        message = json.loads(captured.err)["error"]["message"]
        assert code == 1 and captured.out == "", argv
        assert "pg" in message and "calculation approval" in message, message
        assert "ariadne approve" in message, message
    assert (project / CURRENT).read_bytes() == served_bytes  # the served state never moved


def test_diff_full_gives_the_complete_escaped_content_the_prompt_may_cut_off(pty_project, capsys):
    from ariadne.cli import main as cli

    project, _review_a = pty_project
    capsys.readouterr()
    assert cli(["diff", "--full", "--json", "--project", str(project)]) == 0
    out = json.loads(capsys.readouterr().out)
    joined = "\n".join(out["content_diff"])
    assert "+" in joined and "Draft rule B.\\x0dCR-line" in joined and "\x1b" not in joined


def test_a_mapping_selection_shows_its_assertion_and_evidence_on_the_real_prompt(
    tmp_path, monkeypatch
):
    from ariadne import admission
    from tests.test_context_admission import admitted_candidate

    project, _api, review = admitted_candidate(tmp_path / "proj")
    _profile_pair(project, tmp_path, monkeypatch)
    selection = "order-number:global-order-concatenation"
    code, shown = _run_on_pty(project, "yes", extra=("--confirm-mapping", selection))
    assert code == 0, shown
    assert "Mapping confirmations" in shown and selection in shown and "claim=asserted" in shown
    assert "declaration:" in shown and "digest=" in shown
    served = admission.load_current(project)
    assert served is not None and [m["mapping"] for m in served["confirmed_mappings"]] == [
        "global-order-concatenation"
    ]


def test_a_changed_destination_under_the_same_variable_shows_both_bindings(tmp_path, monkeypatch):
    project = complete_bundle_project(tmp_path)
    env = "ARIADNE_TEST_PG_DSN_SHOW"
    monkeypatch.setenv(env, "postgresql://owner:pw-a@db-a.internal:5432/app")
    entry = authoring_sources.source_entry(env, name="pg", type="postgres")
    authoring_sources.add_sources(project, None, [entry])

    class NoRemote:
        catalog: list = []

        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

    monkeypatch.setattr(approve.execution, "DuckDBExecution", NoRemote)
    _run(project, Tty())  # grant A (and the fixture's own sources)
    monkeypatch.setenv(env, "postgresql://owner:pw-b@db-b.internal:5432/app")
    first = draft.edit_artifact(project, None, "data/seed_notes.md", "x\n")["draft"]
    view = _view(project)
    draft.edit_artifact(
        project,
        (first["generation"], view["candidate_revision"]),
        "data/seed_notes.md",
        (project / "data" / "seed_notes.md").read_text(encoding="utf-8"),
    )
    # re-declare the same variable under a changed entry so the draft is a source change
    doc_entry = {**entry, "read_only": False}
    import yaml

    doc = yaml.safe_load(
        proposals.read_artifact(project, draft_proposal(project), "ariadne.yaml")["content"]
    )
    for existing in doc["sources"]:
        if existing["name"] == "pg":
            existing.update(doc_entry)
    view = _view(project)
    draft.edit_artifact(
        project,
        (view["generation"], view["candidate_revision"]),
        "ariadne.yaml",
        yaml.safe_dump(doc, sort_keys=False),
    )
    _outcome, shown = _run(project, Tty())
    assert "CHANGED source pg" in shown
    assert "old binding:" in shown and "db-a.internal" in shown  # the frozen old destination
    assert "new binding:" in shown and "db-b.internal" in shown
    assert "pw-a" not in shown and "pw-b" not in shown  # credential-free


def test_an_unreachable_source_exhausts_the_deadline_and_leaves_slot_and_grant_unchanged(
    tmp_path, monkeypatch
):
    """The failure mode of finding 3: when the host-owned budget is spent the live check
    refuses inside the transaction; the slot, baseline and grants stay as they were."""
    project, _api, _result = _project_with_new_source(tmp_path)
    slot_before = (project / draft.DRAFT_REL).read_bytes()
    ticks = iter(range(0, 10_000, 1000))  # every clock read advances 1000 s
    monkeypatch.setattr(approve.execution, "_deadline_clock", lambda: next(ticks))
    with pytest.raises(Exception, match="deadline"):
        _run(project, Tty())
    monkeypatch.undo()
    assert not (project / GRANTS).exists()
    assert (project / draft.DRAFT_REL).read_bytes() == slot_before
    assert not (project / draft.BASELINE_REL).exists() and not (project / draft.TXN_REL).exists()
