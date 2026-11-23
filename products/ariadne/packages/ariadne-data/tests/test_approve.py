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


def test_a_crash_after_the_commit_leaves_a_marker_that_the_next_operation_removes(
    tmp_path, monkeypatch
):
    """After the commit point everything is cleanup: a leftover `source_txn.committed` is
    removed by the next draft operation and the grant stays effective."""
    project, _api, result = _project_with_new_source(tmp_path)
    monkeypatch.setattr(draft, "end_source_txn", lambda *_a, **_k: None)  # crash before cleanup
    outcome, _shown = _run(project, Tty())
    monkeypatch.undo()
    assert outcome["approved"] == "sources" and (project / draft.TXN_COMMITTED_REL).exists()
    assert draft.status(project) is None  # recovery under the lock; the grant survives
    assert not (project / draft.TXN_COMMITTED_REL).exists()
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
    # the marker is still there: reads wait until the next operation retries the cleanup
    assert authoring_sources.approval_state(project, resolved, digest)["state"] == "in-progress"
    assert draft.status(project) is None  # recovery confirms and drops the marker
    assert not (project / draft.TXN_COMMITTED_REL).exists()
    assert authoring_sources.approval_state(project, resolved, digest)["approved"] is True


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


def test_a_retired_old_variable_still_renders_the_served_binding_and_asks_for_consent(
    tmp_path, monkeypatch
):
    """Finding 3 (third pass): the old binding comes from the served record, keyed by the old
    DECLARATION — the operator changed connection_env and retired the old variable, and the
    display must not resolve A (it used to raise before the prompt)."""
    import yaml

    from ariadne import admission
    from tests.test_git_admission import _policy_edit, admitted_ready
    from tests.test_git_authoring import admit_library

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _ = admitted_ready(api, project, _policy_edit("Served rule A."))
    assert admit_library(project, review, destination=tmp_path / "published") == 0
    record = admission.load_current(project)
    assert record is not None
    old_env, new_env = "ARIADNE_TEST_PG_OLD", "ARIADNE_TEST_PG_NEW"
    entry_a = {"name": "pg", "type": "postgres", "connection_env": old_env, "read_only": True}
    binding_a = {
        "host": ["db-a.internal"],
        "hostaddr": [],
        "port": ["5432"],
        "dbname": "app",
        "user": "owner",
    }
    declared = record.get("source_declaration_digest") or record["source_digest"]
    shaped = {**record, "sources": [*record["sources"], entry_a]}
    shaped["storage_bindings"] = {"postgres:pg": binding_a}
    shaped["source_digest"] = authoring_sources.approval_digest(
        declared, {"postgres:pg": binding_a}
    )
    (project / CURRENT).write_text(json.dumps(shaped), encoding="utf-8")
    monkeypatch.delenv(old_env, raising=False)  # the old variable is retired
    monkeypatch.setenv(new_env, "postgresql://owner:pw-b@db-b.internal:5432/app")

    # the draft re-points the SAME source at the new variable
    first = draft.edit_artifact(project, None, "data/seed_notes.md", "x\n")["draft"]
    view = _view(project)
    draft.edit_artifact(
        project,
        (first["generation"], view["candidate_revision"]),
        "data/seed_notes.md",
        (project / "data" / "seed_notes.md").read_text(encoding="utf-8"),
    )
    doc = yaml.safe_load(
        proposals.read_artifact(project, draft_proposal(project), "ariadne.yaml")["content"]
    )
    doc["sources"] = [e for e in doc["sources"] if e["name"] != "pg"] + [
        {"name": "pg", "type": "postgres", "connection_env": new_env}
    ]
    view = _view(project)
    draft.edit_artifact(
        project,
        (view["generation"], view["candidate_revision"]),
        "ariadne.yaml",
        yaml.safe_dump(doc, sort_keys=False),
    )

    class NoRemote:
        catalog: list = []

        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

    monkeypatch.setattr(approve.execution, "DuckDBExecution", NoRemote)
    outcome, shown = _run(project, Tty())
    assert "CHANGED source pg" in shown
    assert "old binding:" in shown and "db-a.internal" in shown  # frozen, never re-resolved
    assert "new binding:" in shown and "db-b.internal" in shown
    assert "[yes/no]" in shown and outcome["approved"] == "sources"


def test_diff_full_in_text_and_the_cut_off_prompt_points_at_it(pty_project, capsys, monkeypatch):
    """The human rendering of `diff --full`, and the calculation prompt whose content was cut
    off names it (a long draft exceeds the 120-line display bound)."""
    from ariadne.cli import main as cli
    from tests.test_git_admission import _policy_edit

    project, _review_a = pty_project
    view = _active(project)
    long_body = "\n".join(f"filler line {i}" for i in range(200))
    draft.edit_pages(
        project,
        (view["generation"], view["candidate_revision"]),
        _policy_edit(f"Draft rule C.\n{long_body}\nLAST-LINE-MARKER"),
    )
    capsys.readouterr()
    assert cli(["diff", "--full", "--project", str(project)]) == 0
    text = capsys.readouterr().out
    assert "LAST-LINE-MARKER" in text and "content_diff" in text  # complete, human rendering
    code, shown = _run_on_pty(project, "no")
    assert code == 1
    assert "more diff line(s)" in shown and "ariadne diff --full" in shown
    assert "LAST-LINE-MARKER" not in shown  # the prompt really was cut off


# --------------------------------- the one commit point of a source approval (0040 §3.4.2.5)


def _state_bytes(project):
    """The three journaled files, byte for byte (None when absent)."""

    def read(rel):
        return (project / rel).read_bytes() if (project / rel).exists() else None

    return {
        "grants": read(GRANTS),
        "baseline": read(draft.BASELINE_REL),
        "slot": read(draft.DRAFT_REL),
    }


def _granted(project, result):
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    return authoring_sources.approval_state(project, resolved, digest)["approved"]


def _fault(monkeypatch, project, boundary):
    """Inject ONE fault at ``boundary``."""
    real_replace, real_sync = os.replace, proposals._fsync_path

    def boom(msg):
        raise OSError(msg)

    if boundary == "journal write":
        fired = {"done": False}

        def jsync(path):
            # the journal store's own directory sync: the journal NAME is already installed
            if not fired["done"] and (project / draft.TXN_REL).exists():
                fired["done"] = True
                boom("journal sync")
            return real_sync(path)

        monkeypatch.setattr(proposals, "_fsync_path", jsync)
    elif boundary == "baseline write":
        monkeypatch.setattr(draft, "set_source_baseline", lambda *_a, **_k: boom("baseline"))
    elif boundary == "draft consume":
        monkeypatch.setattr(draft, "consume", lambda *_a, **_k: boom("consume"))
    elif boundary == "grants replace":
        monkeypatch.setattr(
            os,
            "replace",
            lambda src, dst: (
                boom("grants replace") if Path(dst) == project / GRANTS else real_replace(src, dst)
            ),
        )
    elif boundary == "grants directory sync":
        fired = {"done": False}

        def sync(path):
            if not fired["done"] and (project / GRANTS).exists():
                fired["done"] = True
                boom("grants sync")
            return real_sync(path)

        monkeypatch.setattr(proposals, "_fsync_path", sync)
    elif boundary == "commit rename":
        monkeypatch.setattr(
            os,
            "replace",
            lambda src, dst: (
                boom("commit rename")
                if Path(dst) == project / draft.TXN_COMMITTED_REL
                else real_replace(src, dst)
            ),
        )
    elif boundary == "commit directory sync":
        fired = {"done": False}

        def csync(path):
            if not fired["done"] and (project / draft.TXN_COMMITTED_REL).exists():
                fired["done"] = True
                boom("commit sync")
            return real_sync(path)

        monkeypatch.setattr(proposals, "_fsync_path", csync)
    elif boundary == "marker removal":
        monkeypatch.setattr(draft, "end_source_txn", lambda *_a, **_k: boom("marker removal"))


@pytest.mark.parametrize(
    "boundary",
    [
        "journal write",
        "baseline write",
        "draft consume",
        "grants replace",
        "grants directory sync",
        "commit rename",
    ],
)
def test_a_fault_before_the_commit_point_fails_and_restores_all_three_files(
    tmp_path, monkeypatch, boundary
):
    project, _api, result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    _fault(monkeypatch, project, boundary)
    with pytest.raises(OSError):
        _run(project, Tty())
    monkeypatch.undo()
    assert _state_bytes(project) == before  # grants, baseline and slot: previous bytes
    assert (
        not (project / draft.TXN_REL).exists() and not (project / draft.TXN_COMMITTED_REL).exists()
    )
    assert _granted(project, result) is False


def test_a_marker_removal_failure_after_the_commit_still_reports_success(tmp_path, monkeypatch):
    """After a SUCCESSFUL commit sync the marker removal is cleanup: success is reported; reads
    wait until the next operation retries the cleanup (owner rule, 0040 §3.4.2.5)."""
    project, _api, result = _project_with_new_source(tmp_path)
    _fault(monkeypatch, project, "marker removal")
    outcome, _shown = _run(project, Tty())
    monkeypatch.undo()
    assert outcome["approved"] == "sources" and (project / GRANTS).exists()
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["state"] == "in-progress"
    assert draft.status(project) is None and not (project / draft.TXN_COMMITTED_REL).exists()
    assert _granted(project, result) is True


@pytest.mark.parametrize("failure", [OSError("commit sync failed"), KeyboardInterrupt()])
def test_a_failed_or_interrupted_commit_sync_is_pending_until_the_next_holder_confirms_it(
    tmp_path, monkeypatch, capsys, failure
):
    """The owner rule: a failed (or interrupted) directory sync after the commit rename leaves the
    approval PENDING — marker kept, no rollback, readers refused; a failure exits non-zero through
    the real CLI with "recovery pending"; the next project-lock holder retries the sync: success
    confirms the approval, failure keeps it pending."""
    from ariadne.cli import main as cli

    project, _api, result = _project_with_new_source(tmp_path)
    real_sync = proposals._fsync_path
    state = {"fail": True, "first": True}

    def sync(path):
        if state["fail"] and (project / draft.TXN_COMMITTED_REL).exists():
            if state["first"]:  # the commit sync itself: failed or interrupted
                state["first"] = False
                raise failure
            raise OSError("sync still failing")  # the recovery retry: a plain failure
        return real_sync(path)

    monkeypatch.setattr(proposals, "_fsync_path", sync)
    if isinstance(failure, KeyboardInterrupt):
        # an interruption during the sync takes the same pending path (gate closed, no rollback)
        with pytest.raises(approve.ApprovalRefused, match="recovery pending"):
            _run(project, Tty())
    else:
        with monkeypatch.context() as m:
            m.setattr(sys, "stdin", Tty("yes\n"))
            out_tty = io.StringIO()
            out_tty.isatty = lambda: True  # type: ignore[method-assign]
            m.setattr(sys, "stdout", out_tty)
            err = io.StringIO()
            m.setattr(sys, "stderr", err)
            code = cli(["approve", "--project", str(project)])
        assert code == 1 and "recovery pending" in err.getvalue()
    assert (project / draft.TXN_COMMITTED_REL).exists()  # marker kept, no rollback
    assert (project / GRANTS).exists()
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    with pytest.raises(authoring_sources.SourceApprovalPending):  # a read is refused
        authoring_sources._effective_grant(project, resolved, digest, "p", result["revision"])

    with pytest.raises(draft.UnconfirmedSourceApproval):  # the retry fails again -> still pending
        draft.status(project)
    assert (project / draft.TXN_COMMITTED_REL).exists()
    assert authoring_sources.approval_state(project, resolved, digest)["state"] == "in-progress"

    state["fail"] = False
    draft.status(project)  # the retry succeeds: the approval stands, readers are admitted
    assert not (project / draft.TXN_COMMITTED_REL).exists()
    assert _granted(project, result) is True


def test_a_failing_rollback_reports_recovery_pending_refuses_reads_and_the_next_holder_recovers(
    tmp_path, monkeypatch
):
    project, _api, result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    _fault(monkeypatch, project, "draft consume")
    monkeypatch.setattr(
        draft, "_restore", lambda *_a, **_k: (_ for _ in ()).throw(OSError("restore failed"))
    )
    with pytest.raises(approve.ApprovalRefused, match="not approved; recovery pending"):
        _run(project, Tty())
    monkeypatch.undo()
    assert (project / draft.TXN_REL).exists()  # the journal stays
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    with pytest.raises(
        authoring_sources.SourceApprovalPending, match="in progress or was interrupted"
    ):
        authoring_sources._effective_grant(project, resolved, digest, "p", result["revision"])
    state = authoring_sources.approval_state(project, resolved, digest)
    assert state["approved"] is False and state["state"] == "in-progress"  # a display never crashes

    view = draft.status(project)  # the next project-lock holder finishes the rollback
    assert view is not None and not (project / draft.TXN_REL).exists()
    assert _state_bytes(project) == before
    with pytest.raises(ValueError, match="NO grant for that exact identity"):
        authoring_sources._effective_grant(project, resolved, digest, "p", result["revision"])


def test_a_reader_is_refused_while_the_journal_exists_and_authorized_after_the_commit(
    tmp_path, monkeypatch
):
    project, _api, result = _project_with_new_source(tmp_path)
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    # the writer is interrupted between the grants replace and the commit and its rollback is
    # stuck: the journal stays and the grants file is already replaced (the reader window)
    monkeypatch.setattr(
        draft, "commit_source_txn", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x"))
    )
    monkeypatch.setattr(
        draft, "rollback_source_txn", lambda *_a, **_k: (_ for _ in ()).throw(OSError("stuck"))
    )
    with pytest.raises(approve.ApprovalRefused):
        _run(project, Tty())
    monkeypatch.undo()
    assert (project / GRANTS).exists() and draft.source_txn_pending(project)  # in the window
    with pytest.raises(authoring_sources.SourceApprovalPending):
        authoring_sources._effective_grant(project, resolved, digest, "p", result["revision"])
    assert draft.status(project) is not None  # recovered (rolled back)
    outcome, _shown = _run(project, Tty())  # now the approval commits
    assert outcome["approved"] == "sources"
    authoring_sources._effective_grant(
        project, resolved, digest, "p", result["revision"]
    )  # authorized


def test_a_crash_with_the_grants_already_replaced_is_rolled_back_by_the_next_holder(
    tmp_path, monkeypatch
):
    project, _api, result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    # everything written, commit never reached, rollback never ran (a crash)
    monkeypatch.setattr(
        draft, "commit_source_txn", lambda *_a, **_k: (_ for _ in ()).throw(OSError("crash"))
    )
    monkeypatch.setattr(
        draft, "rollback_source_txn", lambda *_a, **_k: (_ for _ in ()).throw(OSError("crash"))
    )
    with pytest.raises(approve.ApprovalRefused):
        _run(project, Tty())
    monkeypatch.undo()
    assert (project / GRANTS).exists() and (project / draft.TXN_REL).exists()
    assert draft.status(project) is not None  # the next lock holder restores all three files
    assert _state_bytes(project) == before and not (project / draft.TXN_REL).exists()
    assert _granted(project, result) is False  # no grant is effective


# ------------------------------------- journal edges, second approver, bytes (r1fix5 items 2-4)


def test_a_journal_removal_failure_after_a_full_restore_is_a_failed_approval_not_pending(
    tmp_path, monkeypatch
):
    """Item 2: once the three files are restored and synced, a failure removing the journal is
    deletion cleanup: the approval is reported failed (never 'recovery pending') and reads stay
    refused until the remnant is removed."""
    project, _api, result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    _fault(monkeypatch, project, "draft consume")
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name == "source_txn.json":
            raise OSError("unlink refused")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(approve.ApprovalRefused, match="journal remnant") as raised:
        _run(project, Tty())
    assert "recovery pending" not in str(raised.value)
    assert _state_bytes(project)["grants"] == before["grants"]  # restored and durable
    assert _state_bytes(project)["slot"] == before["slot"]
    resolved, digest = authoring_sources.candidate_sources(project, result["revision"])
    with pytest.raises(authoring_sources.SourceApprovalPending):  # reads stay refused
        authoring_sources._effective_grant(project, resolved, digest, "p", result["revision"])
    monkeypatch.undo()
    assert draft.status(project) is not None and not (project / draft.TXN_REL).exists()


def test_an_unlink_error_on_a_committed_marker_never_breaks_draft_status(tmp_path, monkeypatch):
    """Item 2: post-commit garbage that cannot be removed does not make `draft status` (or an MCP
    draft lookup) fail and does not hide the draft state; a later operation retries it."""
    project, _api, result = _project_with_new_source(tmp_path)
    monkeypatch.setattr(draft, "end_source_txn", lambda *_a, **_k: None)  # leave the marker
    _run(project, Tty())
    monkeypatch.undo()
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name == "source_txn.committed":
            raise OSError("unlink refused")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert draft.status(project) is None  # no exception; the committed draft state is not hidden
    assert (project / draft.TXN_COMMITTED_REL).exists()
    monkeypatch.undo()
    assert draft.status(project) is None and not (project / draft.TXN_COMMITTED_REL).exists()
    assert _granted(project, result) is True


def test_a_second_approver_recovers_the_first_journal_and_never_takes_its_baseline(
    tmp_path, monkeypatch
):
    """Item 3 (prompt-race seam, no second process): operator 1 leaves an unresolved journal
    (baseline written, consume and rollback failed); operator 2, already at the prompt for the
    same generation, must recover it FIRST — never replace the only rollback journal — so when
    operator 2 also fails, the unapproved baseline of operator 1 is not left behind."""
    project, _api, _result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    _fault(monkeypatch, project, "draft consume")

    def operator_one_fails_and_leaves_a_journal():
        with monkeypatch.context() as m:
            m.setattr(draft, "_restore", lambda *_a, **_k: (_ for _ in ()).throw(OSError("stuck")))
            with pytest.raises(approve.ApprovalRefused, match="recovery pending"):
                _run(project, Tty())
        assert (project / draft.TXN_REL).exists() and (project / draft.BASELINE_REL).exists()

    with pytest.raises(OSError, match="consume"):
        _run(project, Tty(before_answer=operator_one_fails_and_leaves_a_journal))
    monkeypatch.undo()
    assert _state_bytes(project) == before  # no unapproved baseline survived
    assert not (project / draft.TXN_REL).exists()
    assert not (project / draft.BASELINE_REL).exists()


def test_the_journal_round_trips_bytes_including_crlf(tmp_path, monkeypatch):
    """Item 4: a rollback restores the grants and baseline files byte for byte — a CRLF file
    stays CRLF (the journal stores bytes, not normalized text)."""
    project, _api, _result = _project_with_new_source(tmp_path)
    head = proposals._current_head(project)
    (project / GRANTS).write_bytes(b'{"version": 1,\r\n "grants": []}\r\n')
    (project / draft.BASELINE_REL).write_bytes(f'{{"commit":\r\n "{head}"}}\r\n'.encode())
    before = _state_bytes(project)
    assert b"\r\n" in (before["grants"] or b"")
    assert b"\r\n" in (before["baseline"] or b"")
    _fault(monkeypatch, project, "draft consume")
    with pytest.raises(OSError, match="consume"):
        _run(project, Tty())
    monkeypatch.undo()
    assert _state_bytes(project) == before  # exact bytes, CRLF included


def test_a_journal_appearing_after_classification_refuses_before_any_consent(tmp_path, monkeypatch):
    """Blocker 4: through the approval entry point, with a PRIOR GRANT for a changed identity: a
    journal appears after classification and before the prior identities are read. The pending
    response is returned and consent is never requested (no prompt, nothing changed)."""
    import yaml

    project = complete_bundle_project(tmp_path)
    write_parquet(project / "data" / "later.parquet", [(1,)], ["n"])
    authoring_sources.add_sources(
        project, None, [authoring_sources.source_entry("data/later.parquet", name="later")]
    )
    _run(project, Tty())  # grant it: the prior identity
    write_parquet(project / "data" / "later2.parquet", [(1,)], ["n"])
    first = draft.edit_artifact(project, None, "data/seed_notes.md", "x\n")["draft"]
    view = _view(project)
    draft.edit_artifact(
        project,
        (first["generation"], view["candidate_revision"]),
        "data/seed_notes.md",
        (project / "data" / "seed_notes.md").read_text(encoding="utf-8"),
    )
    doc = yaml.safe_load(
        proposals.read_artifact(project, draft_proposal(project), "ariadne.yaml")["content"]
    )
    for entry in doc["sources"]:
        if entry["name"] == "later":
            entry["path"] = "data/later2.parquet"  # a CHANGED identity of a granted source
    view = _view(project)
    draft.edit_artifact(
        project,
        (view["generation"], view["candidate_revision"]),
        "ariadne.yaml",
        yaml.safe_dump(doc, sort_keys=False),
    )
    real = approve._previous_identities

    def journal_appears_first(proj, names):
        draft.begin_source_txn(proj)  # after classification, before the prior identities
        return real(proj, names)

    monkeypatch.setattr(approve, "_previous_identities", journal_appears_first)
    asked = {"n": 0}

    class Counting(Tty):
        def readline(self, *a):
            asked["n"] += 1
            return super().readline(*a)

    slot_before = (project / draft.DRAFT_REL).read_bytes()
    with pytest.raises(approve.ApprovalRefused, match="in progress or was interrupted"):
        _run(project, Counting())
    assert asked["n"] == 0  # consent was never requested
    assert (project / draft.DRAFT_REL).read_bytes() == slot_before  # nothing changed


def test_a_pending_approval_stops_every_draft_mutation_but_cleanup_alone_does_not(
    tmp_path, monkeypatch, capsys
):
    """Blocker 1: a marker whose confirmation sync still fails is PENDING: `draft status`
    reports it (non-zero, through the CLI) and every mutation refuses and changes nothing — the
    typed edit opens no generation. A marker whose sync succeeds but whose REMOVAL fails is
    cleanup only: lookups and mutations proceed."""
    from ariadne.authoring import AuthoringProject
    from ariadne.cli import main as cli

    project, _api, _result = _project_with_new_source(tmp_path)
    monkeypatch.setattr(draft, "end_source_txn", lambda *_a, **_k: None)  # leave the marker
    _run(project, Tty())
    monkeypatch.undo()
    assert (project / draft.TXN_COMMITTED_REL).exists()
    real_sync = proposals._fsync_path

    def failing(path):
        if (project / draft.TXN_COMMITTED_REL).exists():
            raise OSError("sync still failing")
        return real_sync(path)

    monkeypatch.setattr(proposals, "_fsync_path", failing)
    slot_before = (
        (project / draft.DRAFT_REL).read_bytes() if (project / draft.DRAFT_REL).exists() else None
    )
    capsys.readouterr()
    assert cli(["draft", "status", "--json", "--project", str(project)]) == 1
    reported = json.loads(capsys.readouterr().out)
    assert (
        reported["source_approval_pending"] is True
        and "ariadne draft status" in reported["command"]
    )
    for operation in (
        lambda: AuthoringProject(project).apply_edit(
            {"kind": "seed_notes", "content": "pending edit\n"}
        ),
        lambda: draft.open_draft(project),
        lambda: draft.edit_artifact(project, None, "data/seed_notes.md", "y\n"),
    ):
        with pytest.raises(draft.UnconfirmedSourceApproval):
            operation()
    after = (
        (project / draft.DRAFT_REL).read_bytes() if (project / draft.DRAFT_REL).exists() else None
    )
    assert after == slot_before  # no generation was opened
    assert (project / draft.TXN_COMMITTED_REL).exists()

    monkeypatch.undo()  # the sync succeeds now, but the marker REMOVAL fails: cleanup only
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name == "source_txn.committed":
            raise OSError("unlink refused")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert draft.status(project) is None  # lookups proceed
    view = draft.open_draft(project)  # and so do mutations
    assert view["generation"] >= 1


@pytest.mark.parametrize("region", ["post-commit cleanup", "rollback cleanup"])
def test_an_interruption_in_a_cleanup_region_keeps_the_phase_outcome(tmp_path, monkeypatch, region):
    """Blocker 3: Ctrl-C at the cleanup sync. After a successful commit it is still a SUCCESS (the
    grant is effective); after a full restore it is the failed approval with its cleanup note,
    not 'recovery pending'."""
    project, _api, result = _project_with_new_source(tmp_path)
    real_sync = proposals._fsync_path
    if region == "post-commit cleanup":

        def sync(path):
            if (
                not (project / draft.TXN_COMMITTED_REL).exists()
                and (project / GRANTS).exists()
                and not (project / draft.TXN_REL).exists()
            ):
                raise KeyboardInterrupt  # the cleanup sync after the marker removal
            return real_sync(path)

        monkeypatch.setattr(proposals, "_fsync_path", sync)
        outcome, _shown = _run(project, Tty())
        monkeypatch.undo()
        assert outcome["approved"] == "sources"
        assert _granted(project, result) is True
    else:
        _fault(monkeypatch, project, "draft consume")
        state = {"armed": False}

        def sync(path):
            # after the journal is gone the cleanup sync is interrupted
            if state["armed"] and not (project / draft.TXN_REL).exists():
                raise KeyboardInterrupt
            return real_sync(path)

        real_unlink = Path.unlink

        def unlink(self, *a, **k):
            out = real_unlink(self, *a, **k)
            if self.name == "source_txn.json":
                state["armed"] = True
            return out

        monkeypatch.setattr(Path, "unlink", unlink)
        monkeypatch.setattr(proposals, "_fsync_path", sync)
        with pytest.raises(approve.ApprovalRefused, match="cleanup sync") as raised:
            _run(project, Tty())
        monkeypatch.undo()
        assert "recovery pending" not in str(raised.value)
        assert not (project / draft.TXN_REL).exists()
        assert _granted(project, result) is False


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), OSError("unlink sync failed")])
def test_a_prior_journal_restored_then_interrupted_at_its_cleanup_is_cleanup_only(
    tmp_path, monkeypatch, failure
):
    """Blocker 3: operator A leaves a journal; operator B, already at the prompt, consents and
    recovers it. After A's journal was durably restored and removed, an interruption or an
    OSError at the cleanup sync is CLEANUP ONLY: B's approval stops with that distinct message
    (never "recovery pending"/"incomplete restore"), the journal is gone and no grant is
    effective."""
    project, _api, result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    _fault(monkeypatch, project, "draft consume")

    def operator_one_fails_and_leaves_a_journal():
        with monkeypatch.context() as m:
            m.setattr(draft, "_restore", lambda *_a, **_k: (_ for _ in ()).throw(OSError("stuck")))
            with pytest.raises(approve.ApprovalRefused, match="recovery pending"):
                _run(project, Tty())
        assert (project / draft.TXN_REL).exists()
        # B recovers A's journal after consent; the cleanup sync after its removal fails
        real_sync, real_unlink = proposals._fsync_path, Path.unlink
        state = {"armed": False}

        def unlink(self, *a, **k):
            out = real_unlink(self, *a, **k)
            if self.name == "source_txn.json":
                state["armed"] = True
            return out

        def sync(path):
            if state["armed"] and not (project / draft.TXN_REL).exists():
                state["armed"] = False
                raise failure
            return real_sync(path)

        monkeypatch.setattr(Path, "unlink", unlink)
        monkeypatch.setattr(proposals, "_fsync_path", sync)

    with pytest.raises(approve.ApprovalRefused, match="cleanup only") as raised:
        _run(project, Tty(before_answer=operator_one_fails_and_leaves_a_journal))
    monkeypatch.undo()
    assert "recovery pending" not in str(raised.value)
    assert "incomplete" not in str(raised.value)
    assert not (project / draft.TXN_REL).exists()  # the journal is gone
    assert _state_bytes(project) == before  # restored durably
    assert _granted(project, result) is False  # no grant is effective


def test_a_release_already_serving_leaves_no_pending_draft_in_status(tmp_path, monkeypatch, capsys):
    """Blocker 2: the failed-`draft.consume` journey (release serving, slot still active):
    the read-only `status` omits that already-activated slot — no stale draft, no rebase hint —
    exactly as the recovering lookup would, and writes nothing."""
    from ariadne import admission
    from ariadne.cli import main as cli
    from tests.test_git_admission import _policy_edit, admitted_ready

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Serving body."))
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
    admission.admit_revision(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        confirmed_by="human:test",
        overall_preview=composite,
        confirmed_overall_digest=composite["digest"],
    )
    monkeypatch.setattr(draft, "consume", real_consume)
    slot_before = (project / draft.DRAFT_REL).read_bytes()
    assert json.loads(slot_before)["state"] == "active"  # served, yet the slot is still active
    capsys.readouterr()
    assert cli(["status", "--json", "--project", str(project)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["work_pending"]["proposals"] == []  # no stale draft ...
    assert "rebase" not in " ".join(report["next_steps"])  # ... and no rebase hint
    assert (project / draft.DRAFT_REL).read_bytes() == slot_before  # status wrote nothing
    assert cli(["status", "--project", str(project)]) == 0
    assert "draft:" in capsys.readouterr().out


@pytest.mark.parametrize("when", ["before its effect", "after its effect"])
def test_a_prior_journal_interrupted_at_the_unlink_is_cleanup_only(tmp_path, monkeypatch, when):
    """Finding 2: operator A leaves a journal; B consents and recovers it. After the durable
    restore, Ctrl-C AT the journal unlink — before or after its filesystem effect — is cleanup
    only: B's report never says "recovery pending" or "incomplete restore"; a journal that
    remains is a remnant (reads stay refused), an unlink that took effect leaves it gone."""
    project, _api, result = _project_with_new_source(tmp_path)
    before = _state_bytes(project)
    _fault(monkeypatch, project, "draft consume")

    def operator_one_fails_and_leaves_a_journal():
        with monkeypatch.context() as m:
            m.setattr(draft, "_restore", lambda *_a, **_k: (_ for _ in ()).throw(OSError("stuck")))
            with pytest.raises(approve.ApprovalRefused, match="recovery pending"):
                _run(project, Tty())
        assert (project / draft.TXN_REL).exists()
        real_unlink = Path.unlink

        def unlink(self, *a, **k):
            if self.name == "source_txn.json":
                if when == "before its effect":
                    raise KeyboardInterrupt
                real_unlink(self, *a, **k)
                raise KeyboardInterrupt
            return real_unlink(self, *a, **k)

        monkeypatch.setattr(Path, "unlink", unlink)

    expected = "remnant" if when == "before its effect" else "cleanup only"
    with pytest.raises(approve.ApprovalRefused, match=expected) as raised:
        _run(project, Tty(before_answer=operator_one_fails_and_leaves_a_journal))
    monkeypatch.undo()
    assert "recovery pending" not in str(raised.value)
    assert "incomplete" not in str(raised.value)
    assert _state_bytes(project)["grants"] == before["grants"]  # restored durably
    assert _state_bytes(project)["slot"] == before["slot"]
    assert _granted(project, result) is False
    assert (project / draft.TXN_REL).exists() is (when == "before its effect")
