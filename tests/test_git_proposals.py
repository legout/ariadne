"""Isolated Git authoring proposals and complete artifact edits (issue #34 /
G2; spec 2026-10-02-0009 §§3–4, ADR-0016, plan §2 "Project storage and
authority" + "Authoring call contract").

Public-seam tests over ``ariadne.authoring.AuthoringProject`` and
``ariadne-authoring start/read/edit`` against REAL temporary Git repositories
(repo-local ``user.name``/``user.email`` only — never global config; global and
system config are pointed at /dev/null so the host's identity never leaks in).
No Git subprocess is mocked: every refusal is exercised against the real git
binary, and the crash variant interrupts the real state transition.
"""

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import proposals  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402

SEED_NOTES = "# Seed notes\n\nAll events count.\n"
MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: events
    description: Events model
    datasets:
      - name: events
        source: events.events
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
    metrics:
      - name: event_count
        description: Count of all events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def run_git(cwd: Path, *argv: str) -> str:
    """Real git for test-side scaffolding (the seam under test never sees it)."""
    proc = subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


def scaffold_artifacts(project: Path) -> None:
    """The human-created initial artifact files (allowed proposal scope)."""
    project.mkdir(parents=True, exist_ok=True)
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (project / "semantic_layer" / "models").mkdir(parents=True, exist_ok=True)
    (project / "semantic_layer" / "models" / "events.yml").write_text(
        MODEL_YML, encoding="utf-8"
    )


def git_project(tmp_path: Path, *, commit: bool = True) -> Path:
    """A real temporary Git data project with the human's initial artifact
    commit. The Git identity is REPO-LOCAL (never global)."""
    project = tmp_path / "proj"
    scaffold_artifacts(project)
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    if commit:
        run_git(
            project,
            "add",
            "--",
            "ariadne.yaml",
            "data/seed_notes.md",
            "semantic_layer/models/events.yml",
        )
        run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


def test_two_proposals_isolate_edits_and_reject_stale_revision(tmp_path):
    """Issue #34 red seam: two proposals from one base — editing A leaves B
    untouched at the base candidate, and an edit to A carrying A's now-stale
    expected revision is refused without overwriting the candidate."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    a = api.start_proposal()
    b = api.start_proposal()
    assert a["proposal"] != b["proposal"]
    assert a["base_revision"] == b["base_revision"]  # both from the same base
    assert a["candidate_revision"] == a["base_revision"]  # no edits yet

    edited = api.edit_proposal(
        a["proposal"],
        a["candidate_revision"],
        {"kind": "seed_notes", "content": "# Seed notes\n\nVersion 2.\n"},
    )
    assert edited["changed"] is True
    assert edited["revision"] != a["candidate_revision"]

    # B is isolated: its candidate still carries the inherited base bytes and
    # its branch never moved.
    inherited = api.read_artifact(b["proposal"], {"kind": "seed_notes"})
    assert inherited["revision"] == b["candidate_revision"] == b["base_revision"]
    assert inherited["content"] == SEED_NOTES

    # A's candidate moved: the stale expected revision is refused BEFORE any
    # write — the candidate keeps exactly the Version 2 bytes.
    with pytest.raises(ValueError, match="stale"):
        api.edit_proposal(
            a["proposal"],
            a["candidate_revision"],
            {"kind": "seed_notes", "content": "# Seed notes\n\nVersion 3.\n"},
        )
    still = api.read_artifact(a["proposal"], {"kind": "seed_notes"})
    assert still["revision"] == edited["revision"]
    assert still["content"] == "# Seed notes\n\nVersion 2.\n"


def worktree_of(project: Path, proposal: str) -> Path:
    return project / ".ariadne" / "worktrees" / proposal


def branch_of(project: Path, proposal: str) -> str:
    return run_git(worktree_of(project, proposal), "rev-parse", "HEAD").strip()


def dirty(project: Path, proposal: str) -> str:
    return run_git(worktree_of(project, proposal), "status", "--porcelain")


# ------------------------------------------ onboarding + the CLI start/read/edit seam


def test_cli_start_read_edit_on_a_fresh_initial_artifact_repository(tmp_path, capsys):
    """Issue #34 [6], the public CLI journey on a repo with NO commits yet:
    ``start`` establishes the human-created initial artifact revision (allowed
    scope only — the unrelated TODO.txt never rides along), ``edit`` applies a
    complete revision-checked edit, ``read`` returns the candidate's artifact."""
    project = tmp_path / "fresh"
    scaffold_artifacts(project)
    (project / "TODO.txt").write_text("operator notes, never an artifact\n", encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")

    assert authoring_cli(["start", "--project", str(project)]) == 0
    started = json.loads(capsys.readouterr().out)
    assert set(started) == {"proposal", "base_revision", "candidate_revision"}
    assert started["candidate_revision"] == started["base_revision"]

    # the initial artifact revision committed EXACTLY the allowed scope
    root_commit = run_git(project, "rev-list", "--max-parents=0", "HEAD").strip().splitlines()[-1]
    committed = set(
        run_git(project, "show", "--name-only", "--format=", root_commit).split()
    )
    assert committed == {"ariadne.yaml", "data/seed_notes.md", "semantic_layer/models/events.yml"}
    assert "TODO.txt" not in run_git(project, "ls-files")

    edit_file = tmp_path / "edit.json"
    edit_file.write_text(json.dumps({"kind": "seed_notes", "content": "# v2\n"}), encoding="utf-8")
    assert (
        authoring_cli(
            [
                "edit",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--file",
                str(edit_file),
                "--project",
                str(project),
            ]
        )
        == 0
    )
    edited = json.loads(capsys.readouterr().out)
    assert edited["changed"] is True and edited["revision"] != started["candidate_revision"]

    assert (
        authoring_cli(
            [
                "read",
                "--proposal",
                started["proposal"],
                "--kind",
                "seed_notes",
                "--project",
                str(project),
            ]
        )
        == 0
    )
    read = json.loads(capsys.readouterr().out)
    assert read["content"] == "# v2\n" and read["revision"] == edited["revision"]

    # the edit commit names ONLY the artifact — never the unrelated TODO.txt
    assert (
        set(run_git(project, "show", "--name-only", "--format=", edited["revision"]).split())
        == {"data/seed_notes.md"}
    )


def test_cli_edit_reads_stdin_and_keeps_the_one_json_error_contract(tmp_path, capsys, monkeypatch):
    """``--file -`` reads the edit from stdin; a stale revision writes exactly
    one JSON error object to stderr, exit 1, and no success value on stdout."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "seed_notes", "content": "# moved on\n"},
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"kind": "seed_notes", "content": "# stale writer\n"})),
    )
    assert (
        authoring_cli(
            [
                "edit",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--file",
                "-",
                "--project",
                str(project),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["type"] == "ValueError" and "stale" in error["message"]


def test_read_is_bounded_in_parts_and_reports_completeness(tmp_path):
    """Bounded read responses: a long artifact arrives in parts, a partial part
    is never claimed complete, and an out-of-range part is an error."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    long_notes = "# long notes\n\n" + ("policy line " * 4000)  # > one bounded part
    api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "seed_notes", "content": long_notes},
    )
    first = api.read_artifact(started["proposal"], {"kind": "seed_notes"})
    assert first["part"] == 1 and first["parts"] > 1 and first["complete"] is False
    bound = proposals.READ_PART_CHARS
    assert first["content"] == long_notes[:bound]
    last = api.read_artifact(started["proposal"], {"kind": "seed_notes"}, part=first["parts"])
    assert last["complete"] is False
    assert last["content"] == long_notes[(first["parts"] - 1) * bound :]
    with pytest.raises(ValueError, match="out of range"):
        api.read_artifact(started["proposal"], {"kind": "seed_notes"}, part=first["parts"] + 1)


def test_reading_a_missing_artifact_is_a_specific_error(tmp_path):
    """A typed identity that names nothing in the candidate or its inherited
    base is a specific missing-artifact error, never an empty body."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError, match="no artifact"):
        api.read_artifact(started["proposal"], {"kind": "model", "name": "never_created"})
    with pytest.raises(ValueError, match="no artifact"):
        api.read_artifact(
            started["proposal"], {"kind": "page", "section": "policies", "name": "none"}
        )


# ----------------------------------------------------- no-op + explicit staging


def test_identical_edit_at_the_current_revision_is_a_noop(tmp_path):
    """Spec §4: repeating an identical edit against its still-current revision
    creates no new candidate — same revision, no extra commit."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    edit = {
        "kind": "model",
        "name": "events",
        "content": "version: 0.2.0.dev0\nsemantic_model: []\n",
    }
    first = api.edit_proposal(started["proposal"], started["candidate_revision"], edit)
    assert first["changed"] is True
    again = api.edit_proposal(started["proposal"], first["revision"], edit)
    assert again["changed"] is False and again["revision"] == first["revision"]
    count = run_git(
        project, "rev-list", "--count", f"ariadne/proposal/{started['proposal']}"
    )
    assert count.strip() == "2"  # base + exactly one edit commit


def test_edits_stage_exactly_the_named_artifact_never_unrelated_files(tmp_path):
    """Explicit staging of allowed artifact identities only: an unrelated
    untracked file sitting in the worktree never rides into the commit."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    worktree = worktree_of(project, started["proposal"])
    (worktree / "scratch.txt").write_text("operator scratch, never an artifact\n", encoding="utf-8")
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "graph", "content": "metric_governance:\n  version: 1\n"},
    )
    assert (
        set(run_git(project, "show", "--name-only", "--format=", edited["revision"]).split())
        == {"semantic_layer/graph.yml"}
    )
    assert (worktree / "scratch.txt").exists()  # untouched, still untracked
    assert "scratch.txt" in dirty(project, started["proposal"])


# ------------------------------------------------------------- refusal variants


def test_empty_onboarding_refuses_preexisting_staged_changes(tmp_path):
    """Review fix 2: ``--allow-empty`` onboarding commits the existing index —
    a fresh repository with an operator-staged TODO.txt must refuse (naming
    the human resolution) and leave index and history unchanged."""
    project = tmp_path / "empty"
    project.mkdir()
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    (project / "TODO.txt").write_text("operator notes, staged by hand\n", encoding="utf-8")
    run_git(project, "add", "--", "TODO.txt")
    with pytest.raises(RuntimeError, match="staged changes"):
        AuthoringProject(project).start_proposal()
    # the index is preserved untouched and no commit or proposal state exists
    assert run_git(project, "status", "--porcelain").strip() == "A  TODO.txt"
    assert proposals._current_head(project) is None
    assert not (project / ".ariadne" / "worktrees").exists()
    assert not (project / ".ariadne" / "proposals").exists()


def test_wildcard_artifact_names_never_become_git_pathspecs(tmp_path):
    """Review fix 1: ``*``/``?``/``[`` are Git pathspec wildcards — a model
    named ``*`` would stage OTHER untracked .yml files as a pathspec match.
    Wildcard/magic characters are refused centrally before any Git dispatch,
    and nothing is staged or committed: the untracked draft stays untracked."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    worktree = worktree_of(project, started["proposal"])
    (worktree / "semantic_layer" / "models" / "other.yml").write_text(
        "untracked operator draft, never staged by a wildcard\n", encoding="utf-8"
    )
    for bad_name in ("*", "?", "[a]rd", "eve*"):
        with pytest.raises(ValueError, match="plain artifact filename"):
            api.edit_proposal(
                started["proposal"],
                started["candidate_revision"],
                {"kind": "model", "name": bad_name, "content": "x: 1\n"},
            )
    with pytest.raises(ValueError, match="plain artifact filename"):
        api.edit_proposal(
            started["proposal"],
            started["candidate_revision"],
            {"kind": "page", "section": "metrics", "name": "*", "content": "# p\n"},
        )
    # the wildcard never reached Git: no commit, nothing staged, the draft kept
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    assert "other.yml" not in run_git(worktree, "ls-files")
    assert dirty(project, started["proposal"]).strip() == "?? semantic_layer/models/other.yml"


def test_initial_artifacts_with_credentials_are_refused_before_staging(tmp_path):
    """Review fix 3: the human-created initial artifact revision must pass the
    shared pre-write content boundary too — a credential-bearing initial
    artifact refuses with nothing staged or committed (index/history unchanged,
    the matched value never echoed)."""
    project = tmp_path / "fresh"
    scaffold_artifacts(project)
    (project / "semantic_layer" / "models" / "events.yml").write_text(
        MODEL_YML + "# connection string with an inline credential\n"
        "# postgresql://admin:hunter2@db.internal:5432/events\n",
        encoding="utf-8",
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    with pytest.raises(ValueError, match="credential") as excinfo:
        AuthoringProject(project).start_proposal()
    assert "hunter2" not in str(excinfo.value)
    # nothing staged, no commit, no proposal state
    assert run_git(project, "status", "--porcelain", "--untracked-files=no").strip() == ""
    assert proposals._current_head(project) is None
    assert not (project / ".ariadne" / "worktrees").exists()


# A policy page whose base revision already carries a system-stamped verified
# entry (what the promotion gate appends): an edit may KEEP it verbatim, but
# may never introduce or change such a claim (spec §4).
_POLICY_WITH_VERIFIED = (
    "---\n"
    "type: policy\n"
    "status: admitted\n"
    "title: Rule\n"
    "description: A rule page\n"
    "tags: [policy]\n"
    "verified:\n"
    "  - by: operator\n"
    "    at: 2026-01-01T00:00:00Z\n"
    "---\n\n"
    "# Rule\n\n"
    "The rule body.\n"
)


def git_project_with_verified_page(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    scaffold_artifacts(project)
    (project / "context_layer" / "policies").mkdir(parents=True, exist_ok=True)
    (project / "context_layer" / "policies" / "rule.md").write_text(
        _POLICY_WITH_VERIFIED, encoding="utf-8"
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(
        project,
        "add",
        "--",
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/models/events.yml",
        "context_layer/policies/rule.md",
    )
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


def test_system_owned_trust_claims_inside_content_are_refused(tmp_path):
    """Review fix 4 (spec §4: agents cannot author system-owned approval or
    attestation claims): INTRODUCED or CHANGED structured trust claims in
    artifact content (frontmatter verified/attester and similar) are refused
    before any write; claims inherited IDENTICALLY from the base revision stay
    allowed."""
    project = git_project_with_verified_page(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    worktree = worktree_of(project, started["proposal"])

    # an edit that KEEPS the base's verified entry verbatim succeeds
    kept = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "rule",
            "content": _POLICY_WITH_VERIFIED.replace("The rule body.", "The rule body, edited."),
        },
    )
    assert kept["changed"] is True

    # an edit that CHANGES the verified claim is refused before any write
    changed = _POLICY_WITH_VERIFIED.replace("by: operator", "by: the-agent-itself").replace(
        "The rule body.", "Rewritten."
    )
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            started["proposal"],
            kept["revision"],
            {"kind": "page", "section": "policies", "name": "rule", "content": changed},
        )
    assert (worktree / "context_layer" / "policies" / "rule.md").read_text(
        encoding="utf-8"
    ) == _POLICY_WITH_VERIFIED.replace("The rule body.", "The rule body, edited.")
    assert branch_of(project, started["proposal"]) == kept["revision"]

    # INTRODUCING a verified/attester claim where the base has none is refused
    # before any write — the new page never even reaches the worktree
    for forged in (
        "---\ntype: metric\nstatus: draft\nverified:\n  - by: human\n---\n\n# m\n",
        "---\ntype: metric\nstatus: draft\nattester: the-agent-itself\n---\n\n# m\n",
    ):
        with pytest.raises(ValueError, match="system-owned"):
            api.edit_proposal(
                started["proposal"],
                kept["revision"],
                {"kind": "page", "section": "metrics", "name": "new", "content": forged},
            )
    assert not (worktree / "context_layer" / "metrics").exists()
    assert branch_of(project, started["proposal"]) == kept["revision"]

    # model YAML top-level trust claims are refused the same way
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            started["proposal"],
            kept["revision"],
            {
                "kind": "model",
                "name": "events",
                "content": MODEL_YML + "verified:\n  - by: human\n",
            },
        )
    assert dirty(project, started["proposal"]) == ""


@pytest.mark.parametrize(
    "edit",
    [
        {"kind": "model", "name": "../evil", "content": "x: 1\n"},
        {"kind": "model", "name": "/etc/passwd", "content": "x: 1\n"},
        {"kind": "model", "name": "-rf", "content": "x: 1\n"},
        {"kind": "model", "name": "a/b", "content": "x: 1\n"},
        {"kind": "model", "name": "..", "content": "x: 1\n"},
        {"kind": "model", "name": "", "content": "x: 1\n"},
        {"kind": "model", "name": "a\\b", "content": "x: 1\n"},
        {"kind": "page", "section": "../escape", "name": "p", "content": "# p\n"},
        {"kind": "page", "section": "tables", "name": "..", "content": "# p\n"},
        {"kind": "page", "section": "tables", "name": "-opt", "content": "# p\n"},
        {"kind": "page", "section": "tables", "name": "a/b", "content": "# p\n"},
    ],
    ids=lambda e: f"{e.get('kind')}-{e.get('name') or e.get('section')}",
)
def test_escaping_artifact_names_are_refused_before_any_git_write(tmp_path, edit):
    """Ticket [4]: escaping/traversal/option-shaped names and sections are
    refused centrally BEFORE any Git dispatch — the candidate, worktree and
    history are untouched."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError):
        api.edit_proposal(started["proposal"], started["candidate_revision"], edit)
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    assert dirty(project, started["proposal"]) == ""


def test_credential_bearing_edit_is_refused_before_any_write(tmp_path):
    """Ticket [4]: credential-bearing artifact content (inline URL credentials,
    named AWS assignments) never reaches the worktree or a commit; the matched
    value is never echoed."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    for content in (
        "notes\npostgresql://admin:hunter2@db.internal:5432/events\n",
        "notes\nAWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
    ):
        with pytest.raises(ValueError, match="credential") as excinfo:
            api.edit_proposal(
                started["proposal"],
                started["candidate_revision"],
                {"kind": "seed_notes", "content": content},
            )
        assert "hunter2" not in str(excinfo.value) and "wJalrXUtnFEMI" not in str(excinfo.value)
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    assert dirty(project, started["proposal"]) == ""


@pytest.mark.parametrize(
    "edit",
    [
        {"kind": "page", "section": "computations", "name": "event_count", "content": "# c\n"},
        {"kind": "page", "section": "metrics", "name": "index", "content": "# i\n"},
        {"kind": "page", "section": "policies", "name": "log", "content": "# l\n"},
        {"kind": "model", "name": "events", "content": "x: 1\n", "approved": True},
        {"kind": "graph", "content": "x: 1\n", "attester": "the-agent-itself"},
        {"kind": "seed_notes", "content": "x\n", "validated": True},
    ],
    ids=[
        "computations-section",
        "index-page",
        "log-page",
        "model-approval-claim",
        "graph-attester-claim",
        "seed-validated-claim",
    ],
)
def test_system_owned_artifacts_and_claim_smuggling_are_refused(tmp_path, edit):
    """Ticket [4]: generated artifacts (computations/index/log) are
    system-owned, and a caller cannot smuggle approval/attestation claims into
    an edit envelope — the discriminated contract is exact."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError):
        api.edit_proposal(started["proposal"], started["candidate_revision"], edit)
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    assert dirty(project, started["proposal"]) == ""


def test_a_project_subdirectory_inside_another_repository_is_refused(tmp_path):
    """Review fix 6: a project directory that is merely a SUBDIRECTORY of an
    enclosing repository would create the proposal worktree/branches against
    the enclosing repo while identities resolve from its root — refuse before
    any state is created: Git's resolved top-level working directory must BE
    the configured project directory."""
    outer = tmp_path / "outer"
    outer.mkdir()
    run_git(outer, "init", "-q")
    run_git(outer, "config", "user.name", "Ariadne Tests")
    run_git(outer, "config", "user.email", "tests@ariadne.local")
    project = outer / "proj"
    scaffold_artifacts(project)
    with pytest.raises(RuntimeError, match="top-level"):
        AuthoringProject(project).start_proposal()
    assert not (project / ".ariadne").exists()  # no state, no worktree
    assert not (outer / ".ariadne").exists()
    assert run_git(outer, "branch").strip() == ""  # no proposal branch leaked


def test_wrong_proposal_or_project_identity_is_refused(tmp_path):
    """Ticket [4]: an unknown proposal ID, a proposal ID that exists in a
    DIFFERENT project, and a non-generated/traversal-shaped ID are all refused
    without reading or writing anything."""
    project = git_project(tmp_path / "one")
    other = git_project(tmp_path / "two")
    api = AuthoringProject(project)
    other_api = AuthoringProject(other)
    foreign = other_api.start_proposal()
    with pytest.raises(ValueError, match="no proposal"):
        api.edit_proposal(
            "p-00000000000000-000000",  # well-formed but unknown here
            foreign["candidate_revision"],
            {"kind": "seed_notes", "content": "x\n"},
        )
    for bad in ("../evil", "-opt", "", "HEAD"):
        with pytest.raises(ValueError, match="invalid proposal ID"):
            api.read_artifact(bad, {"kind": "seed_notes"})
    with pytest.raises(ValueError, match="no proposal"):
        api.read_artifact(foreign["proposal"], {"kind": "seed_notes"})
    with pytest.raises(ValueError, match="no proposal"):
        api.edit_proposal(
            foreign["proposal"],
            foreign["candidate_revision"],
            {"kind": "seed_notes", "content": "x\n"},
        )


def test_unknown_base_revision_is_refused(tmp_path):
    """A named base revision must be an existing commit of THIS repository."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    with pytest.raises(ValueError, match="not a commit"):
        api.start_proposal("deadbeef")
    with pytest.raises(ValueError, match="commit SHA"):
        api.start_proposal("--force")  # never an option


def test_not_a_git_repository_is_an_actionable_error(tmp_path):
    """A project directory without a Git repository refuses before anything is
    created (the human owns ``git init``)."""
    project = tmp_path / "plain"
    scaffold_artifacts(project)
    with pytest.raises(RuntimeError, match="not a Git repository"):
        AuthoringProject(project).start_proposal()
    assert not (project / ".ariadne").exists()


def test_missing_git_is_an_actionable_error(tmp_path, monkeypatch):
    """Ticket [4]: unavailable Git is an explicit blocker, not a fallback."""
    project = git_project(tmp_path)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(RuntimeError, match="git is not available"):
        AuthoringProject(project).start_proposal()


def test_missing_operator_git_identity_is_an_actionable_error(tmp_path):
    """Ticket [4]: no repo-local operator identity (global config pointed at
    /dev/null by the fixture) — the error names the fix and never writes Git
    configuration itself."""
    project = git_project(tmp_path)
    run_git(project, "config", "--unset", "user.name")
    run_git(project, "config", "--unset", "user.email")
    with pytest.raises(RuntimeError, match="git config user.name"):
        AuthoringProject(project).start_proposal()


_RACE_CHILD = """\
import json, sys, time
from pathlib import Path

from ariadne.authoring import AuthoringProject

project, proposal, expected, content, ready, go = sys.argv[1:7]
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.time() + 60
while not Path(go).exists() and time.time() < deadline:
    time.sleep(0.01)
try:
    result = AuthoringProject(project).edit_proposal(
        proposal, expected, {"kind": "seed_notes", "content": content}
    )
    print(json.dumps({"ok": True, "revision": result["revision"]}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
"""


def test_same_worktree_competing_writers_cannot_both_win(tmp_path):
    """Ticket [4], the real race: two processes released by one barrier edit
    the SAME proposal with the SAME expected revision — exactly one wins, the
    other is refused as a stale/competing writer, and the candidate pairs with
    the winner's bytes (never a mix)."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    ready = [tmp_path / f"ready{i}" for i in "ab"]
    go = tmp_path / "GO"
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _RACE_CHILD,
                str(project),
                started["proposal"],
                started["candidate_revision"],
                content,
                str(signal_ready),
                str(go),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for content, signal_ready in (
            ("# writer A\n", ready[0]),
            ("# writer B\n", ready[1]),
        )
    ]
    try:
        for path in ready:
            deadline = time.monotonic() + 60
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert path.exists()
        go.write_text("go", encoding="utf-8")
        results = [json.loads(proc.communicate(timeout=120)[0]) for proc in procs]
    finally:
        for proc in procs:
            if proc.poll() is None:  # pragma: no cover - failure path only
                proc.kill()

    winners = [r for r in results if r["ok"]]
    losers = [r for r in results if not r["ok"]]
    assert len(winners) == 1 and len(losers) == 1
    assert "stale" in losers[0]["error"]
    assert api.read_artifact(started["proposal"], {"kind": "seed_notes"})["content"] in (
        "# writer A\n",
        "# writer B\n",
    )
    assert dirty(project, started["proposal"]) == ""


def test_dirty_worktree_refuses_edits_and_preserves_the_draft(tmp_path):
    """Ticket [4]/spec §4: uncommitted changes in the proposal worktree (an
    interrupted edit or human tampering) block further mutations for human
    resolution — the draft stays visible, nothing is reset."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    worktree = worktree_of(project, started["proposal"])
    (worktree / "data" / "seed_notes.md").write_text("# uncommitted draft\n", encoding="utf-8")
    with pytest.raises(ValueError, match="human resolution"):
        api.edit_proposal(
            started["proposal"],
            started["candidate_revision"],
            {"kind": "seed_notes", "content": "# v2\n"},
        )
    # evidence preserved: the draft bytes, the branch and the record all stay
    assert (worktree / "data" / "seed_notes.md").read_text() == "# uncommitted draft\n"
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    record = json.loads(
        (project / ".ariadne" / "proposals" / f"{started['proposal']}.json").read_text()
    )
    assert record["candidate_revision"] == started["candidate_revision"]
    # reads stay pinned to the recorded candidate — the draft never leaks in
    assert api.read_artifact(started["proposal"], {"kind": "seed_notes"})["content"] == SEED_NOTES
    assert proposals._lstat(worktree / "data" / "seed_notes.md") is not None


def test_interrupted_new_artifact_creation_blocks_edits_to_the_same_path(tmp_path):
    """Review fix 5: a crash between writing and staging a NEW artifact leaves
    an untracked draft the coherence gate cannot see — the next edit to the
    SAME path refuses for human resolution (the orphan bytes are preserved),
    while unrelated edits keep working."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    worktree = worktree_of(project, started["proposal"])
    # simulate the interrupted creation: a NEW artifact written, never staged
    orphan = worktree / "semantic_layer" / "models" / "orphan.yml"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("orphaned draft bytes, evidence to preserve\n", encoding="utf-8")
    with pytest.raises(ValueError, match="human resolution"):
        api.edit_proposal(
            started["proposal"],
            started["candidate_revision"],
            {"kind": "model", "name": "orphan", "content": "replacement bytes\n"},
        )
    # evidence preserved: the orphan bytes stay, nothing is committed or staged
    assert orphan.read_text(encoding="utf-8") == "orphaned draft bytes, evidence to preserve\n"
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    assert "orphan.yml" not in run_git(worktree, "ls-files")
    # an unrelated edit still works and never touches the orphan
    ok = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "seed_notes", "content": "# unrelated edit\n"},
    )
    assert ok["changed"] is True
    assert orphan.read_text(encoding="utf-8") == "orphaned draft bytes, evidence to preserve\n"


def test_interrupted_state_persistence_blocks_and_preserves_evidence(tmp_path, monkeypatch):
    """Ticket [4]: a crash AFTER the edit commit but BEFORE the record store
    leaves branch/record disagreement — every further mutation is refused for
    human resolution with the worktree, history and record preserved."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()

    def crash_after_commit(project, record):  # the interruption the ticket names
        raise RuntimeError("simulated crash: commit done, state not stored")

    monkeypatch.setattr(proposals, "_store_record", crash_after_commit)
    with pytest.raises(RuntimeError, match="simulated crash"):
        api.edit_proposal(
            started["proposal"],
            started["candidate_revision"],
            {"kind": "seed_notes", "content": "# orphaned commit\n"},
        )
    monkeypatch.undo()

    # evidence preserved: the committed-but-unrecorded bytes exist in the worktree
    assert (
        worktree_of(project, started["proposal"]) / "data" / "seed_notes.md"
    ).read_text() == "# orphaned commit\n"
    with pytest.raises(ValueError, match="human resolution"):
        api.edit_proposal(
            started["proposal"],
            _current_candidate(project, started["proposal"]),  # even with the REAL new revision
            {"kind": "seed_notes", "content": "# v3\n"},
        )
    record = json.loads(
        (project / ".ariadne" / "proposals" / f"{started['proposal']}.json").read_text()
    )
    assert record["candidate_revision"] == started["candidate_revision"]  # never advanced


def _current_candidate(project: Path, proposal: str) -> str:
    return branch_of(project, proposal)


# ------------------------------- Query routes ad-hoc staging through stage_ad_hoc


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """A minimal valid served tree + the deterministic demo db (the golden
    author fixtures; the runtime's own compile gate is the validator)."""
    from tests.test_serve import GOLDEN_OKF, GOLDEN_OSI, seed_demo_db

    tmp = tmp_path_factory.mktemp("adhoc")
    db = seed_demo_db(tmp / "demo.db")
    root = tmp / "served"
    (root / "semantic_layer" / "models").mkdir(parents=True)
    (root / "semantic_layer" / "models" / "orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
    (root / "context_layer" / "metrics").mkdir(parents=True)
    (root / "context_layer" / "metrics" / "gross_margin.md").write_text(
        GOLDEN_OKF, encoding="utf-8"
    )
    return root, db


def test_query_routes_ad_hoc_staging_through_the_shared_stage_ad_hoc(tmp_path, served, monkeypatch):
    """Plan §2 proof: Query stages the compiled ad-hoc definition through
    the shared ad-hoc staging owner in ariadne.proposals (patched target) —
    the reservation-based seam spec 0014 §5 added (issue #56/S1), still not a
    Query-local copy — and the staged model/page land in the legacy staging
    store, never in a Git proposal."""
    import asyncio

    from ariadne.query import QueryRuntime

    root, db = served
    staging = tmp_path / "staging"
    runtime = QueryRuntime(root / "semantic_layer", root / "context_layer", db, staging_dir=staging)
    calls: list[tuple] = []
    real = proposals.stage_reserved_ad_hoc

    def spy(reserved, envelope, params):
        calls.append((str(reserved[0].parents[3]), reserved[0].stem))
        return real(reserved, envelope, params)

    monkeypatch.setattr(proposals, "stage_reserved_ad_hoc", spy)
    result = asyncio.run(
        runtime.define_metric(
            {
                "name": "orders_total",
                "description": "Total amount of all orders",
                "source": "orders",
                "expression": "SUM(amount)",
                "dimensions": [],
            }
        )
    )
    assert calls == [(str(staging), "orders_total")]  # routed through the shared op
    assert result["governed"] is False  # ad-hoc stays ungoverned, unadmitted
    assert (staging / "semantic_layer" / "models" / "adhoc" / "orders_total.yml").is_file()
    assert (staging / "context_layer" / "metrics" / "orders_total.md").is_file()
    assert not (tmp_path / ".ariadne").exists()  # never a Git proposal store


def _generated_table_page(resource: str) -> str:
    """A committed generated-style table page: the core-owned ``resource``
    binding and ``ariadne`` schema/observations block, a catalog citation and
    authored summary only (no core-owned body sections in this minimal form)."""
    meta = {
        "type": "table",
        "title": "demo.main.orders",
        "description": "One row per order.",
        "tags": ["table"],
        "sources": [
            {
                "id": "catalog-demo-main-orders",
                "resource": resource,
                "title": "catalog and profile of demo.main.orders",
            }
        ],
        "resource": resource,
        "ariadne": {
            "schema": [
                {
                    "column": "order_id",
                    "type": "BIGINT",
                    "nullable": "unknown",
                    "default": "unknown",
                    "comment": "unknown",
                }
            ],
            "observations": {
                "observed_at": "2026-01-01T00:00:00+00:00",
                "scope": "full",
                "row_count": 3,
                "candidate_keys": ["order_id"],
                "columns": {"order_id": {"null_count": 0, "distinct_count": 3}},
                "citation": resource,
            },
        },
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n# Orders\n"


def _quality_block(resource: str, reported_at: str) -> dict:
    return {
        "version": 1,
        "reports": [
            {
                "id": "owner-completeness",
                "asset": resource,
                "source_ids": ["catalog-demo-main-orders"],
                "scope": {
                    "kind": "asset",
                    "description": "All rows of the orders table.",
                    "population": "every row of the physical table",
                    "period": None,
                },
                "reported_at": reported_at,
                "checks": [
                    {
                        "id": "completeness",
                        "kind": "completeness",
                        "outcome": "unknown",
                        "criterion": "every order placed is present",
                        "tested_population": "all orders",
                        "tested_period": None,
                    }
                ],
            }
        ],
    }


def git_project_with_generated_table_page(tmp_path: Path) -> tuple[Path, str]:
    """A real temporary Git data project whose initial commit carries one
    generated-style table page; returns (project, the canonical resource)."""
    import base64
    import json as _json

    payload = _json.dumps(["demo", "demo", "main", "orders"], separators=(",", ":"))
    resource = "ariadne://table/" + base64.urlsafe_b64encode(payload.encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")
    project = tmp_path / "proj"
    scaffold_artifacts(project)
    (project / "context_layer" / "tables").mkdir(parents=True, exist_ok=True)
    (project / "context_layer" / "tables" / "orders.md").write_text(
        _generated_table_page(resource), encoding="utf-8"
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(
        project,
        "add",
        "--",
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/models/events.yml",
        "context_layer/tables/orders.md",
    )
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project, resource


def test_table_page_edit_adds_supplied_quality_metadata_without_touching_core_claims(
    tmp_path,
):
    """Issue #53 (spec 0013 §2): ordinary page editing adds the supplied
    ``ariadne_quality`` profile without changing the protected
    resource/schema/observations — the authored extension is NOT a system
    claim (the edit seam accepts it), while the core-owned bindings stay
    unforgeable and a malformed declaration fails the shared authoring gate
    before any human admission."""
    from ariadne.context import _load_frontmatter_meta, _page_contract_errors

    project, resource = git_project_with_generated_table_page(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    worktree = worktree_of(project, started["proposal"])
    page = worktree / "context_layer" / "tables" / "orders.md"
    original = page.read_text(encoding="utf-8")

    def with_quality(reported_at: str) -> str:
        meta = _load_frontmatter_meta(original)
        meta["ariadne_quality"] = _quality_block(resource, reported_at)
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n# Orders\n"

    # the ordinary edit lands: authored metadata, not a system-owned claim
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            "kind": "page",
            "section": "tables",
            "name": "orders",
            "content": with_quality("2026-01-15T00:00:00+00:00"),
        },
    )
    assert edited["changed"] is True
    added = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
    assert added["resource"] == resource  # the core binding is untouched
    before = _load_frontmatter_meta(original)
    assert added["ariadne"] == before["ariadne"]  # schema/observations untouched
    assert added["sources"] == before["sources"]
    # the added profile passes the shared authoring gate
    assert _page_contract_errors(worktree, page, "table") == []

    # a malformed (naive-timestamp) declaration fails authoring validation —
    # BEFORE human admission, never as a query refusal (spec §5/§7 AC6)
    naive = api.edit_proposal(
        started["proposal"],
        edited["revision"],
        {
            "kind": "page",
            "section": "tables",
            "name": "orders",
            "content": with_quality("2026-01-15T00:00:00"),
        },
    )
    assert naive["changed"] is True  # the seam edits; the GATE owns the refusal
    errors = _page_contract_errors(worktree, page, "table")
    assert errors and "naive" in errors[0]

    # the protected resource binding itself stays unforgeable (unchanged seam)
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            started["proposal"],
            naive["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": "orders",
                "content": page.read_text(encoding="utf-8").replace(
                    resource, resource[:-4] + "XXXX"
                ),
            },
        )
