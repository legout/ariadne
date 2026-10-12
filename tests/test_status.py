"""``ariadne status`` — read-only project readiness diagnostics (spec
2026-10-12-0016, ADR-0021, the spec-0001 usability amendment).

Public-seam tests: every invocation goes through ``ariadne.cli.main(argv)``
(the exact target of the ``ariadne`` console script). Expected values derive
from the spec's acceptance criteria and from independently written fixtures —
the admitted revision/digest oracle is the ``.ariadne/current.json`` the
admission CLI itself wrote, never status output. Real temporary Git
repositories and parquet sources; no network, no provider.

AC map (spec 0016 §"Acceptance criteria"):
1  kind:none + setup hint + exit 0; explicit scaffold reports (no query
   factory error);
2  legacy staging / managed proposals keep identities; ready survives
   optional stores and drafts; review_needed is directed to review;
3  valid admission names the checked pinned revision/digest; absent/corrupt/
   changed state is a blocker, never a fallback; context-only distinguished;
4  connection/compile/network entry points fail loudly if called; no file
   changes;
5  --json is exactly one object with the same states as human text; the
   existing query contract is untouched;
6  two valid legacy roots refuse naming --served; .git alone is not managed
   and query routing is unchanged;
7  Git prerequisites + per-target skill drift with actionable next steps;
   absent optional skill targets are never failed installs.
"""

import json
import os
import shutil
import socket
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import skill as skill_module  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from tests.test_context_admission import (  # noqa: E402
    admit as context_admit,
)
from tests.test_context_admission import (  # noqa: E402
    admitted_candidate as context_only_reviewed,
)
from tests.test_git_admission import (  # noqa: E402
    admit as admit_via_cli,
)
from tests.test_git_admission import (  # noqa: E402
    admitted_ready,
    read_current,
)
from tests.test_git_authoring import (  # noqa: E402
    POLICY_PAGE,
    complete_bundle_project,
)
from tests.test_serve import (  # noqa: E402
    GOLDEN_OKF,
    GOLDEN_OSI,
    seed_demo_db,
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


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """A valid promoted legacy root + the deterministic demo db (the test_cli
    fixture shape; the runtime's compile/grain gates are the validator)."""
    tmp = tmp_path_factory.mktemp("status")
    db = seed_demo_db(tmp / "demo.db")
    root = tmp / "served"
    (root / "semantic_layer" / "models").mkdir(parents=True)
    (root / "semantic_layer" / "models" / "orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
    (root / "context_layer" / "metrics").mkdir(parents=True)
    (root / "context_layer" / "metrics" / "gross_margin.md").write_text(
        GOLDEN_OKF, encoding="utf-8"
    )
    return root, db


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
    review, _ = admitted_ready(
        api,
        project,
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        },
    )
    assert admit_via_cli(project, review) == 0
    return project


# ------------------------------------------------------------------- [AC1]


def test_empty_cwd_is_kind_none_not_ready_with_setup_hint_exit_zero(tmp_path, capsys, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    report = status_json(capsys)
    assert report["project"]["kind"] == "none"
    assert report["ready"] is False and report["ready_reason"]
    assert any("ariadne-init" in step for step in report["next_steps"])  # setup hint
    # human output carries the same states
    capsys.readouterr()
    assert run_status() == 0
    human = capsys.readouterr().out
    assert "none" in human and "Ready: no" in human and "ariadne-init" in human


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


def test_project_rejects_conflicting_and_nonexistent_selectors(tmp_path, capsys):
    scaffold = tmp_path / "scaffold"
    scaffold.mkdir()
    capsys.readouterr()
    assert run_status("--project", str(scaffold), "--served", str(scaffold)) == 1
    error = error_payload(capsys.readouterr().err)
    assert "mutually exclusive" in error["message"] and "--served" in error["message"]
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
    # the admitted proposal keeps its own identity/state in the backlog (AC2)
    (proposal,) = report["work_pending"]["proposals"]
    assert proposal["id"] == current["proposal"]
    assert proposal["validation"]["state"] == "validated"


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
    project, _api, review = context_only_reviewed(tmp_path)
    assert context_admit(project, review) == 0
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


# ------------------------------------------------------------------- [AC5]


def test_json_is_one_object_with_human_states_and_query_contract_unchanged(
    served, tmp_path, capsys
):
    root, db = served
    staging = tmp_path / "staging"
    report = status_json(capsys, "--served", str(root), "--db", str(db), "--staging", str(staging))
    assert report["project"]["kind"] == "legacy_staged"
    assert report["project"]["artifact_state"] == "promoted"
    assert report["ready"] is True
    capsys.readouterr()
    assert run_status("--served", str(root), "--db", str(db), "--staging", str(staging)) == 0
    human = capsys.readouterr().out
    assert "legacy_staged" in human and "Ready: yes" in human  # same states as --json
    # the existing query contract is untouched: one JSON value on stdout
    capsys.readouterr()
    assert (
        cli(["list-metrics", "--served", str(root), "--db", str(db), "--staging", str(staging)])
        == 0
    )
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1
    names = [entry["name"] for entry in json.loads(out) if isinstance(entry, dict)]
    assert "gross_margin" in names  # the fixture's governed metric, unchanged


# ------------------------------------------------------------------- [AC6]


def test_two_valid_legacy_roots_refuse_naming_served(served, tmp_path, capsys, monkeypatch):
    root, db = served
    both = tmp_path / "both"
    both.mkdir()
    shutil.copytree(root, both / "served")  # ./served valid…
    shutil.copytree(root / "context_layer", both / "context_layer")  # …and cwd too
    shutil.copytree(root / "semantic_layer", both / "semantic_layer")
    monkeypatch.chdir(both)
    capsys.readouterr()
    assert run_status() == 1
    error = error_payload(capsys.readouterr().err)
    assert "ambiguous" in error["message"] and "--served" in error["message"]
    # explicit selection resolves the ambiguity
    report = status_json(capsys, "--served", str(both), "--db", str(db))
    assert report["project"]["kind"] == "legacy_staged"
    assert report["project"]["artifact_root"] == str(both)


def test_git_directory_alone_is_not_managed_and_query_routing_is_unchanged(
    tmp_path, capsys, monkeypatch
):
    import subprocess

    only_git = tmp_path / "only-git"
    only_git.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=only_git, check=True)
    monkeypatch.chdir(only_git)
    report = status_json(capsys)
    assert report["project"]["kind"] == "none"  # .git alone is no marker
    assert report["ready"] is False
    # status-only diagnostic detection does not alter query routing
    capsys.readouterr()
    assert cli(["list-metrics", "--db", str(tmp_path / "missing.db")]) == 1
    error = error_payload(capsys.readouterr().err)
    assert "no promoted artifacts found" in error["message"]


def test_cwd_ariadne_state_dir_selects_managed_diagnostics(tmp_path, capsys, monkeypatch):
    project = tmp_path / "managed"
    (project / STATE).mkdir(parents=True)
    monkeypatch.chdir(project)
    report = status_json(capsys)
    assert report["project"]["kind"] == "git_managed"
    assert report["project"]["admission"]["state"] == "none"  # incomplete state: its blocker


# ------------------------------------------------------------------- [AC2]


def test_ready_legacy_served_state_survives_optional_stores_and_pending_drafts(
    served, tmp_path, capsys
):
    root, db = served
    staging = tmp_path / "staging"
    (staging / "semantic_layer" / "models" / "adhoc").mkdir(parents=True)
    (staging / "semantic_layer" / "models" / "adhoc" / "probe.yml").write_text("version: 0.2\n")
    (staging / "context_layer" / "metrics").mkdir(parents=True)
    (staging / "context_layer" / "metrics" / "probe.md").write_text("# probe draft\n")
    (staging / "answer_examples").mkdir()
    (staging / "answer_examples" / "d1.md").write_text(
        "---\ntype: answer_example\nquestion: A draft example?\n---\nbody\n", encoding="utf-8"
    )
    (root / "answer_examples").mkdir()
    (root / "answer_examples" / "s1.md").write_text(
        "---\ntype: answer_example\nstatus: stable\nquestion: A stable example?\n---\nbody\n",
        encoding="utf-8",
    )
    report = status_json(capsys, "--served", str(root), "--db", str(db), "--staging", str(staging))
    assert report["ready"] is True  # optional stores/drafts never invalidate readiness
    staged = report["work_pending"]["staged_artifacts"]
    assert staged["count"] == 2 and staged["review_needed"] == []
    assert report["work_pending"]["answer_examples"]["by_status"] == {"draft": 1, "stable": 1}


def test_review_needed_work_is_directed_to_review_not_promotion(served, tmp_path, capsys):
    root, db = served
    staging = tmp_path / "staging"
    (staging / "context_layer" / "policies").mkdir(parents=True)
    (staging / "context_layer" / "policies" / "blocked.md").write_text(
        "---\nstatus: review_needed\n---\n# needs a human\n", encoding="utf-8"
    )
    report = status_json(capsys, "--served", str(root), "--db", str(db), "--staging", str(staging))
    assert report["work_pending"]["staged_artifacts"]["review_needed"] == [
        "context_layer/policies/blocked.md"
    ]
    review_steps = [s for s in report["next_steps"] if "review" in s]
    assert review_steps and "context_layer/policies/blocked.md" in review_steps[0]
    assert not any("ariadne-promote" in s for s in report["next_steps"])  # never unconditional


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
    assert any("approve-sources" in step for step in report["next_steps"])


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
    assert not any("ariadne-skill" in s for s in report["next_steps"])  # absent ≠ failed install

    target = Path.home() / ".agents" / "skills" / "ariadne"
    shutil.copytree(packaged, target)  # an exact installed copy…
    report = status_json(capsys)
    states = {(t["scope"], t["agent"]): t["state"] for t in report["skill"]["targets"]}
    assert states[("user", None)] == "ok"  # …is not drift
    assert not any("ariadne-skill" in s for s in report["next_steps"])

    (target / "SKILL.md").write_text("# local edit\n", encoding="utf-8")  # now drifted
    report = status_json(capsys)
    states = {(t["scope"], t["agent"]): t["state"] for t in report["skill"]["targets"]}
    assert states[("user", None)] == "drift"
    assert any(s.startswith("ariadne-skill install --scope user") for s in report["next_steps"])
