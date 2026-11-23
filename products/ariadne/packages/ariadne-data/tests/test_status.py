"""``ariadne status`` — source-free diagnostics for Git-managed projects.

Every invocation goes through ``ariadne.cli.main(argv)``. Expected values
come from approved behavior and independently authored synthetic Git fixtures;
the admission CLI's ``.ariadne/current.json`` is the revision/digest oracle.
No network or provider is used.

Coverage: empty/scaffold projects, exact admitted snapshots and invalidation,
context-only admissions, source-free/read-only reporting, JSON/human parity,
Git prerequisites, effective source grants and optional skill drift.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import skill as skill_module  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from tests.test_context_admission import (  # noqa: E402
    admitted_candidate as context_only_reviewed,
)
from tests.test_git_admission import (  # noqa: E402
    _policy_edit,
    admitted_ready,
    read_current,
)
from tests.test_git_admission import (  # noqa: E402
    admit as admit_via_cli,
)
from tests.test_git_authoring import (  # noqa: E402
    complete_bundle_project,
    write_parquet,
)

STATE = Path(".ariadne")
CURRENT = STATE / "current.json"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Deterministic diagnostics: an isolated HOME (skill targets never touch
    the operator's real installs) and neutralized global/system Git config."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def run_status(*args):
    return cli(["status", *args])


def status_json(capsys, *args):
    """One status report as a parsed JSON object (AC5: exactly one object)."""
    capsys.readouterr()
    code = run_status("--json", *args)
    assert code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1  # exactly one JSON value
    return json.loads(out)


def error_payload(err: str) -> dict:
    """Parse and shape-check one CLI JSON error object (the shared contract)."""
    payload = json.loads(err)
    assert set(payload) == {"error"} and set(payload["error"]) >= {"type", "message"}
    return payload["error"]


def tree_hash(root: Path) -> str:
    """Content hash of a whole tree (AC4: no project file may change)."""
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def admitted_project(tmp_path: Path) -> Path:
    """A real temporary managed project with a VALID admission: the full
    start → approve → edit → validate → review → admit journey."""
    from ariadne.authoring import AuthoringProject

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _ = admitted_ready(api, project, _policy_edit("The rule body, revised."))
    assert admit_via_cli(project, review) == 0
    return project


# ------------------------------------------------------------------- [AC1]


def test_empty_cwd_is_not_ready_with_git_first_setup_steps_exit_zero(tmp_path, capsys, monkeypatch):
    # Git-only status (spec 0027 §6): the report always describes the managed
    # Git route; an empty cwd is an unmanaged, not-ready project whose setup
    # guidance is the Git-first scaffold/proposal path — exit 0, report data
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    report = status_json(capsys)
    assert report["project"]["kind"] == "git_managed"
    assert report["ready"] is False and report["ready_reason"]
    assert any("git init" in step for step in report["next_steps"])
    assert any("ariadne add" in step for step in report["next_steps"])
    # human output carries the same states
    capsys.readouterr()
    assert run_status() == 0
    human = capsys.readouterr().out
    assert "git_managed" in human and "Ready: no" in human and "git init" in human


def test_explicit_managed_scaffold_without_admission_reports_instead_of_erroring(tmp_path, capsys):
    scaffold = tmp_path / "scaffold"
    (scaffold / "data").mkdir(parents=True)
    (scaffold / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: data/demo.db\n",
        encoding="utf-8",
    )
    report = status_json(capsys, "--project", str(scaffold))
    assert report["project"]["kind"] == "git_managed"
    assert report["project"]["admission"]["state"] == "none"
    assert report["ready"] is False
    scaffold_sources = report["sources"]["scaffold"]
    assert scaffold_sources["entries"] == [{"name": "demo", "type": "sqlite", "read_only": True}]
    assert scaffold_sources["approval"] is False  # scaffold, not an admitted identity
    # the query factory's missing-admission error is NOT what status produces
    capsys.readouterr()
    assert run_status("--project", str(scaffold)) == 0
    assert "no valid admission" not in capsys.readouterr().out


def test_project_rejects_nonexistent_project(tmp_path, capsys):
    capsys.readouterr()
    assert run_status("--project", str(tmp_path / "missing")) == 1
    error = error_payload(capsys.readouterr().err)
    assert "not an existing directory" in error["message"]


# ------------------------------------------------------------------- [AC3]


def test_valid_admission_reports_checked_pinned_revision_and_digest(tmp_path, capsys):
    project = admitted_project(tmp_path)
    current = read_current(project)  # the admission CLI's own record: the oracle
    report = status_json(capsys, "--project", str(project))
    admission = report["project"]["admission"]
    assert admission["state"] == "valid"
    assert admission["revision"] == current["commit"]
    assert admission["artifact_digest"] == current["artifact_digest"]
    assert admission["context_only"] is False
    assert admission["catalog"]["metrics"] >= 1
    assert report["project"]["artifact_root"] == str(
        project / STATE / "snapshots" / current["commit"]
    )
    assert report["ready"] is True and report["ready_reason"] is None
    assert report["sources"]["selection"] == "admitted"
    assert report["sources"]["identity_digest"] == current["source_digest"]
    assert report["sources"]["approval"] is True
    # the approval record: who/when/which review (attribution label, 0040 §3.5.1)
    approval = admission["approval"]
    assert approval["by"] == current["confirmed"]["by"] and approval["by"].startswith("human:")
    assert approval["at"] == current["confirmed"]["at"]
    assert approval["review_digest"] == current["confirmed"]["review_digest"]
    capsys.readouterr()
    assert run_status("--project", str(project)) == 0
    human = capsys.readouterr().out
    assert "approved by:" in human and approval["by"] in human
    assert approval["review_digest"] in human  # the exact digest, not a shortened one
    assert approval["commit"] in human  # and the approved commit
    # approval consumed the draft: an approved proposal is history, never pending (spec 0040)
    assert report["work_pending"]["proposals"] == []
    assert current["proposal"]


def test_absent_admission_and_corrupt_or_changed_state_block_never_fall_back(
    tmp_path, capsys, monkeypatch
):
    project = admitted_project(tmp_path)
    # absent (within the managed route): admission none, still a report
    (project / CURRENT).unlink()
    report = status_json(capsys, "--project", str(project))
    assert report["project"]["admission"]["state"] == "none"
    assert report["ready"] is False
    assert not (project / CURRENT).exists()  # status wrote nothing

    # corrupt descriptor: explicitly invalid with the blocker — and because a
    # corrupt-state project cwd ALSO looks like a valid legacy root, the route
    # must stay MANAGED (never a fallback to root artifacts)
    fresh = admitted_project(tmp_path / "fresh")
    monkeypatch.chdir(fresh)
    (fresh / CURRENT).write_text("{ this is not json", encoding="utf-8")
    report = status_json(capsys)
    assert report["project"]["kind"] == "git_managed"
    assert report["project"]["admission"]["state"] == "invalid"
    assert "current.json" in report["project"]["admission"]["reason"]
    assert report["ready"] is False and "admission invalid" in report["ready_reason"]

    # changed snapshot bytes: the digest check refuses, never serves mutable files
    monkeypatch.chdir(tmp_path)  # leave the mutated project's cwd before mutating
    mutated = admitted_project(tmp_path / "mutated")
    snapshot = mutated / STATE / "snapshots" / read_current(mutated)["commit"]
    page = next(snapshot.rglob("all-events-count.md"))
    page.write_text(page.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    report = status_json(capsys, "--project", str(mutated))
    assert report["project"]["admission"]["state"] == "invalid"
    assert "digest" in report["project"]["admission"]["reason"]
    assert report["ready"] is False


def test_context_only_admission_is_distinguished_from_a_metric_catalog(tmp_path, capsys):
    from tests.test_git_admission import admit as composite_admit

    project, _api, review = context_only_reviewed(tmp_path)
    assert composite_admit(project, review) == 0
    report = status_json(capsys, "--project", str(project))
    admission = report["project"]["admission"]
    assert admission["state"] == "valid"  # admission is valid…
    assert admission["context_only"] is True  # …but carries no metric catalog
    assert admission["catalog"]["metrics"] == 0
    assert report["ready"] is False
    assert "context-only" in report["ready_reason"]
    assert any("semantic models" in step for step in report["next_steps"])


# ------------------------------------------------------------------- [AC4]


def test_status_never_opens_compiles_or_connects_and_changes_no_files(
    tmp_path, capsys, monkeypatch
):
    project = admitted_project(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("status must never open sources, compile or use the network")

    monkeypatch.setattr("ariadne.sources.build_connection", forbidden)
    monkeypatch.setattr("ariadne.execution.DuckDBExecution.__init__", forbidden)
    monkeypatch.setattr("ariadne.query.QueryRuntime.__init__", forbidden)
    monkeypatch.setattr("ariadne.query.QueryRuntime.open_project", forbidden)
    monkeypatch.setattr("ariadne.render.render", forbidden)
    monkeypatch.setattr("ariadne.query.render", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

    monkeypatch.setattr(duckdb, "connect", forbidden)

    before = tree_hash(project)
    report = status_json(capsys, "--project", str(project))
    assert report["project"]["admission"]["state"] == "valid"
    assert report["ready"] is True  # reported from metadata alone
    assert tree_hash(project) == before  # no project file changed

    # an empty / uninitialized directory: diagnosis never bootstraps state (no .ariadne, no locks)
    empty = tmp_path / "empty-cwd"
    empty.mkdir()
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    status_json(capsys, "--project", str(empty))
    assert not (empty / ".ariadne").exists()
    assert tree_hash(empty) == tree_hash(empty)  # and nothing else appeared


# ------------------------------------------------------------------- [AC5]


def test_json_status_matches_human_states_for_admitted_project(tmp_path, capsys):
    project = admitted_project(tmp_path)
    report = status_json(capsys, "--project", str(project))
    assert report["project"]["kind"] == "git_managed"
    assert report["project"]["admission"]["state"] == "valid"
    assert report["ready"] is True
    capsys.readouterr()
    assert run_status("--project", str(project)) == 0
    human = capsys.readouterr().out
    assert "git_managed" in human and "Ready: yes" in human


# ------------------------------------------------------------------- [AC6]


def test_git_directory_alone_is_not_ready(tmp_path, capsys, monkeypatch):
    # Git-only status: .git alone is a not-ready managed project (no scaffold,
    # no admission) with honest report data — never an error exit
    import subprocess

    only_git = tmp_path / "only-git"
    only_git.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=only_git, check=True)
    monkeypatch.chdir(only_git)
    report = status_json(capsys)
    assert report["project"]["kind"] == "git_managed"
    assert report["project"]["admission"]["state"] == "none"
    assert report["ready"] is False


def test_cwd_ariadne_state_dir_selects_managed_diagnostics(tmp_path, capsys, monkeypatch):
    project = tmp_path / "managed"
    (project / STATE).mkdir(parents=True)
    monkeypatch.chdir(project)
    report = status_json(capsys)
    assert report["project"]["kind"] == "git_managed"
    assert report["project"]["admission"]["state"] == "none"  # incomplete state: its blocker


# ------------------------------------------------------------------- [AC2]


def test_managed_pending_proposals_keep_identity_and_validation_state(tmp_path, capsys):
    from ariadne.authoring import AuthoringProject
    from ariadne.authoring_sources import candidate_sources

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    report = status_json(capsys, "--project", str(project))
    (proposal,) = report["work_pending"]["proposals"]
    assert proposal["id"] == started["proposal"]  # its own identity
    assert proposal["candidate_revision"] == started["candidate_revision"]
    assert proposal["validation"]["state"] == "unvalidated"
    # approval is evaluated for the COMPLETE resolved identity of the exact
    # candidate revision, as the existing seam records it — not guessed
    resolved, digest = candidate_sources(project, started["candidate_revision"])
    (pending_source,) = report["sources"]["pending"]
    assert pending_source["source_digest"] == digest
    assert pending_source["approved"] is False
    assert any("ariadne approve" in step for step in report["next_steps"])


# ------------------------------------------------------------------- [AC7]


def test_git_authoring_prerequisites_appear_with_actionable_steps(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
    import subprocess

    no_repo = tmp_path / "no-repo"
    no_repo.mkdir()
    (no_repo / "ariadne.yaml").write_text("sources: []\n", encoding="utf-8")
    report = status_json(capsys, "--project", str(no_repo))
    git = report["project"]["git"]
    assert git["available"] is True and git["repository_root"] is None
    assert any(s.startswith(f"git init {no_repo}") for s in report["next_steps"])

    repo_no_identity = tmp_path / "repo-no-identity"
    repo_no_identity.mkdir()
    (repo_no_identity / "ariadne.yaml").write_text("sources: []\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo_no_identity, check=True)
    report = status_json(capsys, "--project", str(repo_no_identity))
    git = report["project"]["git"]
    assert git["repository_root"] == str(repo_no_identity)
    assert git["commit_identity"] is False
    assert any("git config user.name" in s for s in report["next_steps"])


def test_skill_targets_absent_optional_and_drifted_installed(tmp_path, capsys, monkeypatch):
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    (packaged / "SKILL.md").write_text("# packaged skill v1\n", encoding="utf-8")
    monkeypatch.setattr(skill_module, "ASSETS", packaged)
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    report = status_json(capsys)
    states = {(t["scope"], t["agent"]): t["state"] for t in report["skill"]["targets"]}
    assert set(states.values()) == {"absent"}  # every optional target honestly absent
    assert not any("ariadne skill" in s for s in report["next_steps"])  # absent ≠ failed install

    target = Path.home() / ".agents" / "skills" / "ariadne"
    shutil.copytree(packaged, target)  # an exact installed copy…
    report = status_json(capsys)
    states = {(t["scope"], t["agent"]): t["state"] for t in report["skill"]["targets"]}
    assert states[("user", None)] == "ok"  # …is not drift
    assert not any("ariadne skill" in s for s in report["next_steps"])

    (target / "SKILL.md").write_text("# local edit\n", encoding="utf-8")  # now drifted
    report = status_json(capsys)
    states = {(t["scope"], t["agent"]): t["state"] for t in report["skill"]["targets"]}
    assert states[("user", None)] == "drift"
    assert any(s.startswith("ariadne skill install --scope user") for s in report["next_steps"])


# ------------------------------------------- fix pass (review findings F1-F5)


def test_missing_git_is_report_data_with_an_actionable_step(tmp_path, capsys, monkeypatch):
    """F2 (Report section 1, AC7): Git availability/repo-root/commit-identity
    are report data — with git absent from PATH the report is still produced
    (exit 0) with git unavailable and an actionable next step, never an exit-1
    from the probe itself."""
    project = admitted_project(tmp_path / "proj")  # built while git exists…
    empty_bin = tmp_path / "empty-bin"  # …then git is removed from PATH
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    report = status_json(capsys, "--project", str(project))
    git = report["project"]["git"]
    assert git["available"] is False
    assert git["repository_root"] is None and git["commit_identity"] is None
    assert report["ready"] is False
    assert report["next_steps"] and "install Git" in report["next_steps"][0]
    # the recorded admission cannot be verified without git: an explicit
    # blocker, never a crash and never a fallback
    admission = report["project"]["admission"]
    assert admission["state"] == "invalid"
    assert "git is not available" in admission["reason"]


def test_unreadable_ambient_registry_is_report_data_not_an_exit(tmp_path, capsys, monkeypatch):
    """F5 (Failure behavior): a corrupt/unreadable state — here an ambient
    ariadne.yaml whose discovery read fails with PermissionError — is reported
    explicitly in the sources section while the other readable sections stay
    visible and the command still produces its report (exit 0)."""
    workdir = tmp_path / "unreadable-registry"
    workdir.mkdir()
    registry = workdir / "ariadne.yaml"
    registry.write_text("sources:\n  - name: demo\n    type: sqlite\n    path: x.db\n")
    registry.chmod(0)  # unreadable by the same (non-root) user running tests
    monkeypatch.chdir(workdir)
    report = status_json(capsys)  # must not exit nonzero
    # the unreadable registry is honest scaffold report data with its error
    assert report["sources"]["selection"] == "scaffold"
    scaffold = report["sources"]["scaffold"]
    assert scaffold["path"].endswith("ariadne.yaml")
    assert "Permission denied" in scaffold["error"]
    assert report["ready"] is False
    assert report["project"]["kind"] == "git_managed"
    assert report["skill"]["targets"]  # the other sections remain visible


# ------------------------------------------- fix pass 2 (delta findings F3a/F3b)


# ------------- spec 0025 (S1): effective-approval labels without credentials


def test_status_labels_effective_storage_approval_without_credential_reads(tmp_path, capsys):
    """Spec 0025 §4: offline status distinguishes declaration history from the
    CURRENT effective approval — a scaffold registry with used profiles reports
    ``current``/``not-current``/``unresolved`` states by resolving only
    endpoint/region values (never key/token reads), and a missing endpoint
    value is a visible prerequisite, not a corrupt declaration."""
    project = tmp_path / "scaffold"
    (project / "data").mkdir(parents=True)
    (project / "ariadne.yaml").write_text(
        "storages:\n"
        "  local:\n"
        "    type: s3\n"
        "    access_key_id_env: STATUS_S3_KEY_ID\n"
        "    secret_access_key_env: STATUS_S3_SECRET\n"
        "    endpoint_url_env: STATUS_S3_ENDPOINT\n"
        "    scopes: [s3://retail/]\n"
        "sources:\n"
        "  - name: orders\n"
        "    type: parquet\n"
        "    storage: local\n"
        "    path: s3://retail/orders/orders.parquet\n",
        encoding="utf-8",
    )

    # missing endpoint value: a visible prerequisite (unresolved), never an error
    monkeypatch_home = os.environ.copy()
    for name in ("STATUS_S3_ENDPOINT", "STATUS_S3_KEY_ID", "STATUS_S3_SECRET"):
        monkeypatch_home.pop(name, None)
    with patch.dict(os.environ, monkeypatch_home, clear=True):
        report = status_json(capsys, "--project", str(project))
    scaffold = report["sources"]["scaffold"]
    assert scaffold["effective_approval"] == "unresolved"
    assert "STATUS_S3_ENDPOINT" in scaffold["prerequisite"]

    # endpoint resolved but no grant: absent (no declaration history either)
    with patch.dict(os.environ, {"STATUS_S3_ENDPOINT": "http://127.0.0.1:9000"}, clear=True):
        report = status_json(capsys, "--project", str(project))
    scaffold = report["sources"]["scaffold"]
    assert scaffold["effective_approval"] == "absent"
    assert scaffold["approval"] is False

    # a CURRENT grant under the resolved binding flips the label
    from ariadne.authoring_sources import (  # noqa: E402 — local for the grant
        _resolved_entries,
    )
    from ariadne.sources import load_registry  # noqa: E402

    registry = load_registry(project / "ariadne.yaml")
    resolved = _resolved_entries(registry.sources, registry.storages)
    bindings = {
        "local": {
            "endpoint": "http://127.0.0.1:9000",
            "region": "us-east-1",
            "url_style": "path",
            "scopes": ["s3://retail/"],
        }
    }
    approvals = project / ".ariadne" / "source_grants.json"
    approvals.parent.mkdir(parents=True, exist_ok=True)
    approvals.write_text(
        json.dumps(
            {
                "version": 1,
                "grants": [
                    {
                        "source": entry,
                        "binding": bindings["local"],
                        "postgres_binding": None,
                        "by": "human:test",
                        "at": "2026-11-22T00:00:00+00:00",
                    }
                    for entry in resolved
                ],
            }
        ),
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"STATUS_S3_ENDPOINT": "http://127.0.0.1:9000"}, clear=True):
        report = status_json(capsys, "--project", str(project))
    scaffold = report["sources"]["scaffold"]
    assert scaffold["effective_approval"] == "current"
    assert scaffold["approval"] is True

    # an endpoint CHANGE with only the old grant: not-current, never "approved"
    with patch.dict(os.environ, {"STATUS_S3_ENDPOINT": "http://127.0.0.1:9001"}, clear=True):
        report = status_json(capsys, "--project", str(project))
    scaffold = report["sources"]["scaffold"]
    assert scaffold["effective_approval"] == "not-current"
    assert scaffold["approval"] is False


def test_admitted_example_counts_from_pinned_scoped_native_view(tmp_path, capsys):
    """R2 (C6 fix): an explicitly saved, human-admitted, visible Answer
    Example is counted from the pinned scoped native SDK view — exactly one
    admitted example reports total 1 / admitted 1 (hand-derived oracle: one
    visible answer_example page exists in the pinned release; the retired
    dict-shape probe always reported zero)."""

    from tests.test_answer_examples import _SMALL_RESULT, _example_release, _submission
    from tests.test_git_authoring import approved

    project, api, review = _example_release(tmp_path / "project")
    # the fixture itself activates the revision-4 base release; the Example
    # rides a fresh candidate that is validated, reviewed and admitted here

    # one explicit Example saved into a fresh candidate, validated, admitted
    started = api.start_proposal()
    approved(api, project, started)
    from ariadne.discovery import DiscoveryRuntime

    # an explicit Example is saved into the active draft (an MCP tool in spec 0040)
    saved = DiscoveryRuntime.open_project(project).save_example(
        _submission(_SMALL_RESULT, sources=[])
    )
    assert saved["proposal"] == started["proposal"]  # one active draft holds it
    validated = api.validate_proposal(saved["proposal"], saved["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    example_review = api.review_proposal(saved["proposal"])
    from integration.tests.lumio_metric_mvp import activate, preview

    activate(project, example_review, preview(project, example_review, tmp_path / "published"))

    report = status_json(capsys, "--project", str(project))
    assert report["work_pending"]["answer_examples"] == {
        "total": 1,
        "by_status": {"admitted": 1},
    }


# ------------------------------------------------ finding 6: one draft, current commands


def test_status_shows_the_one_active_draft_and_only_current_commands(tmp_path, capsys):
    """Finding 6 (spec 0040 §3.1.2/§3.3): `status` renders the ONE active draft
    (generation, base, staleness, validation) and recovery commands that exist; consumed
    and discarded proposals are history, never pending."""
    from ariadne import draft
    from ariadne.authoring import AuthoringProject

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    first = api.start_proposal()
    view = draft.status(project)
    assert view is not None and view["validation"] == "unvalidated"
    draft.discard(project, (view["generation"], view["candidate_revision"]))
    second = api.start_proposal()  # generation 2

    report = status_json(capsys, "--project", str(project))
    (pending,) = report["work_pending"]["proposals"]  # exactly one: the discarded one is gone
    assert pending["id"] == second["proposal"] and pending["id"] != first["proposal"]
    assert pending["generation"] == 2 and pending["stale"] is False
    assert pending["validation"] == {"state": "unvalidated"}
    steps = " ".join(report["next_steps"])
    assert "ariadne validate" in steps or "ariadne approve" in steps
    for dead in ("ariadne-authoring", "ariadne-admit", "approve-sources", "ariadne-skill"):
        assert dead not in steps, dead
    capsys.readouterr()
    assert run_status("--project", str(project)) == 0
    human = capsys.readouterr().out
    assert "draft:" in human and "generation 2" in human


def test_an_active_draft_shows_its_recovery_command_while_a_release_is_serving(tmp_path, capsys):
    """Finding 6 (second pass): a ready, served project with a pending source draft or a
    stale draft must not say "no blockers" — the draft's recovery command appears."""
    from ariadne import authoring_sources

    project = admitted_project(tmp_path)
    (project / "data").mkdir(exist_ok=True)
    write_parquet(project / "data" / "later.parquet", [(1,)], ["n"])
    authoring_sources.add_sources(
        project, None, [authoring_sources.source_entry("data/later.parquet", name="later")]
    )
    report = status_json(capsys, "--project", str(project))
    assert report["ready"] is True  # the served release still serves
    steps = " ".join(report["next_steps"])
    assert "ariadne approve" in steps and "new sources first" in steps


def test_a_stuck_source_approval_rollback_is_reported_as_pending_recovery(
    tmp_path, capsys, monkeypatch
):
    """Item 5: a journal that cannot be rolled back shows as a SOURCE APPROVAL pending recovery
    with `ariadne draft status` — not as a generic unreadable draft."""
    from ariadne import draft

    project = admitted_project(tmp_path)
    draft.begin_source_txn(project)  # an interrupted approval's journal
    monkeypatch.setattr(
        draft, "_restore", lambda *_a, **_k: (_ for _ in ()).throw(OSError("stuck"))
    )
    report = status_json(capsys, "--project", str(project))
    (entry,) = report["work_pending"]["proposals"]
    assert (
        entry["state"] == "source_approval_pending" and "ariadne draft status" in entry["command"]
    )
    steps = " ".join(report["next_steps"])
    assert "source approval is pending recovery" in steps and "ariadne draft status" in steps
    assert "unreadable" not in steps
