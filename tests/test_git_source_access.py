"""Git-aware source access and measured inputs (issue #35 / G3; spec
2026-10-02-0009 §5 "Source approval and artifact admission", AC5/6/8; plan §2
"Project storage and authority" + "Authoring call contract" rows
propose_sources/inputs/upload_document).

Source approval and artifact admission are distinct decisions: a source entry
committed in a proposal's candidate registry never opens anything until the
separate HUMAN-ONLY approve-sources records the exact RESOLVED identity in the
operator-owned ``.ariadne/source-approvals.json`` (outside Git artifacts).
The canary spies on the REAL shared connection builder
(``ariadne.sources.build_connection``, the one chokepoint
:class:`ariadne.execution.DuckDBExecution` resolves through its module) to
prove no unapproved identity is ever handed to DuckDB. Source paths resolve
against the HOST project root — never a temporary worktree — so decoys planted
at the same relative path inside either worktree are never consulted. Real
temporary Git repositories (repo-local identity only), real parquet files, no
network, no provider.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.sources  # noqa: E402
from ariadne import proposals  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402

SEED_NOTES = "# Seed notes\n\nAll events count.\n"


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture
def connection_spy(monkeypatch):
    """Record every registry handed to THE shared connection builder — the
    single chokepoint execution/profiler/validation share. Patching
    ``ariadne.sources.build_connection`` suffices: DuckDBExecution resolves the
    builder through its module, so every Git-mode open is seen here."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    return opened


def run_git(cwd: Path, *argv: str) -> str:
    """Real git for test-side scaffolding (the seam under test never sees it)."""
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


def write_parquet(path: Path, rows: int = 3) -> Path:
    """A real local parquet file (DuckDB-written) with ``rows`` rows — the row
    count distinguishes the host-root file from any decoy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(f"({i}, 'row{i}')" for i in range(1, rows + 1))
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) t(id, label)) TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def git_project(tmp_path: Path) -> Path:
    """A real temporary Git data project with the human's initial artifact
    commit (commented registry template + Seed Notes). Repo-local identity."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


def worktree_of(project: Path, proposal: str) -> Path:
    return project / ".ariadne" / "worktrees" / proposal


def branch_of(project: Path, proposal: str) -> str:
    return run_git(worktree_of(project, proposal), "rev-parse", "HEAD").strip()


def tracked_dirty(project: Path, proposal: str) -> str:
    """Tracked-file status of the proposal worktree (untracked scratch is the
    tolerated case — decoys are untracked by construction)."""
    return run_git(worktree_of(project, proposal), "status", "--porcelain", "--untracked-files=no")


EVENTS_ENTRY = {"name": "events", "type": "parquet", "path": "data/events.parquet"}


# ------------------------------------------------------- the first red seam


def test_committed_registry_cannot_open_source_until_operator_approval(
    tmp_path, capsys, connection_spy
):
    """Issue #35 [1], the red seam: a source entry committed in the candidate
    registry (TWO worktrees, one RELATIVE source path) opens nothing until the
    human approve-sources records the exact resolved identity outside Git —
    then both proposals read the approved HOST-root identity only, and the
    decoys planted at the same relative path inside each worktree are never
    consulted."""
    project = git_project(tmp_path)
    parquet = write_parquet(project / "data" / "events.parquet", rows=3)
    api = AuthoringProject(project)
    a = api.start_proposal()
    b = api.start_proposal()
    assert a["proposal"] != b["proposal"]
    # decoys at the SAME relative path inside BOTH worktrees: a worktree-
    # relative resolution would open one of these instead (9 rows, so the
    # profile's row count tells them apart)
    for started in (a, b):
        write_parquet(worktree_of(project, started["proposal"]) / "data" / "events.parquet", rows=9)

    proposed_a = api.propose_sources(a["proposal"], a["candidate_revision"], [EVENTS_ENTRY])
    proposed_b = api.propose_sources(b["proposal"], b["candidate_revision"], [dict(EVENTS_ENTRY)])
    assert proposed_a["source_digest"] == proposed_b["source_digest"]  # one resolved identity
    assert len(proposed_a["source_digest"]) == 64
    # the resolved identity is the HOST project root's file, never a worktree
    assert proposed_a["sources"][0]["path"] == str(parquet)
    # the registry edit is committed IN the candidate
    assert proposed_a["revision"] != a["candidate_revision"]
    registry = proposals.read_artifact(project, a["proposal"], "ariadne.yaml")
    assert "events.parquet" in registry["content"]

    # before approval NOTHING opens: inputs is an explicit error in BOTH
    # worktrees, and the shared builder is never called
    for started in (a, b):
        with pytest.raises(ValueError, match="approval"):
            api.inputs(started["proposal"])
    assert connection_spy == []

    # the human-only CLI records the exact resolved identity outside Git
    assert (
        authoring_cli(
            [
                "approve-sources",
                "--proposal",
                a["proposal"],
                "--revision",
                proposed_a["revision"],
                "--source-digest",
                proposed_a["source_digest"],
                "--project",
                str(project),
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["source_digest"] == proposed_a["source_digest"]
    approvals = json.loads(
        (project / ".ariadne" / "source-approvals.json").read_text(encoding="utf-8")
    )
    (record,) = approvals.values()
    assert record["sources"][0]["path"] == str(parquet)
    # approval edited NO Git artifact: the candidate revision is unchanged
    assert branch_of(project, a["proposal"]) == proposed_a["revision"]
    assert tracked_dirty(project, a["proposal"]) == ""

    # after approval BOTH proposals read the HOST identity (identity-keyed
    # grant, shared by the concurrent proposal — never a worktree decoy)
    for started in (a, b):
        result = api.inputs(started["proposal"])
        (source,) = result["profile"]["sources"]
        assert source["name"] == "events"
        assert source["tables"]["events"]["row_count"] == 3  # the HOST file
        assert result["revision"] == branch_of(project, started["proposal"])
    assert connection_spy == [[str(parquet)], [str(parquet)]]


# ----------------------------------------------- [5]: changed source / widened config


def test_changed_source_entry_after_approval_cannot_grant_access(tmp_path, connection_spy):
    """Issue #35 [5]: after an identity is approved, ANY registry change — here
    a second proposed source — resolves to a DIFFERENT identity: the old grant
    opens nothing, inputs is an explicit error naming the new digest, and the
    operator's fresh approval of the exact new identity restores access (no
    automatic revocation of the earlier record, no silent reuse)."""
    project = git_project(tmp_path)
    events = write_parquet(project / "data" / "events.parquet", rows=3)
    other = write_parquet(project / "data" / "other.parquet", rows=7)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"], started["candidate_revision"], [EVENTS_ENTRY]
    )
    api.approve_sources(started["proposal"], proposed["revision"], proposed["source_digest"])
    assert api.inputs(started["proposal"])["profile"]["sources"][0]["name"] == "events"
    assert connection_spy == [[str(events)]]

    # a changed registry (a second appended source) is a different identity:
    # the earlier approval grants nothing, nothing is opened
    changed = api.propose_sources(
        started["proposal"],
        proposed["revision"],
        [{"name": "other", "type": "parquet", "path": "data/other.parquet"}],
    )
    assert changed["source_digest"] != proposed["source_digest"]
    with pytest.raises(ValueError, match="NO operator approval") as excinfo:
        api.inputs(started["proposal"])
    assert changed["source_digest"] in str(excinfo.value)  # the error names the new identity
    assert connection_spy == [[str(events)]]  # nothing new was opened

    # the earlier record is still there (no revocation); approving the exact
    # new identity restores access through the approved registry only
    api.approve_sources(started["proposal"], changed["revision"], changed["source_digest"])
    approvals = json.loads(
        (project / ".ariadne" / "source-approvals.json").read_text(encoding="utf-8")
    )
    assert set(approvals) == {proposed["source_digest"], changed["source_digest"]}
    profile = api.inputs(started["proposal"])["profile"]["sources"]
    assert {s["name"] for s in profile} == {"events", "other"}
    assert profile[1]["tables"]["other"]["row_count"] == 7
    assert connection_spy[-1] == [str(events), str(other)]


def test_proposed_widened_document_configuration_cannot_widen_input_roots(tmp_path, connection_spy):
    """Issue #35 [5]: a document-root setting COMMITTED in the candidate is
    inert data. The operator's HOST project root carries the wider roots when
    the base is created, then narrows them in the working tree; the proposal
    still inherits the widened ``documents:`` section in its candidate, but
    document reads follow the operator's CURRENT host configuration only — a
    reference the committed setting would allow is refused, and neither the
    changed source nor the widened config ever reaches a reader unapproved."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    # the operator's base: a WIDER documents configuration (data/docs + data/extra)
    (project / "ariadne.yaml").write_text(
        "documents:\n  roots:\n    - data/docs\n    - data/extra\n",
        encoding="utf-8",
    )
    (project / "data").mkdir()
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (project / "data" / "docs").mkdir(parents=True)
    (project / "data" / "docs" / "inside.md").write_text("# inside\n", encoding="utf-8")
    (project / "data" / "extra").mkdir(parents=True)
    (project / "data" / "extra" / "wide.md").write_text("# widened\n", encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: wider roots")
    parquet = write_parquet(project / "data" / "events.parquet", rows=3)

    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"], started["candidate_revision"], [EVENTS_ENTRY]
    )
    # the candidate registry indeed carries the widened committed section
    candidate_registry = proposals.read_artifact(project, started["proposal"], "ariadne.yaml")[
        "content"
    ]
    assert "data/extra" in candidate_registry

    # the operator NARROWS the host working configuration (uncommitted,
    # operator-owned): only data/docs remains allowed
    (project / "ariadne.yaml").write_text(
        "documents:\n  roots:\n    - data/docs\n", encoding="utf-8"
    )

    # pre-approval: the changed/unapproved source never reaches the reader
    with pytest.raises(ValueError, match="NO operator approval"):
        api.inputs(started["proposal"], documents=["../extra/wide.md"])
    assert connection_spy == []

    api.approve_sources(started["proposal"], proposed["revision"], proposed["source_digest"])
    # the committed (widened) setting granted nothing: the escaping reference
    # is refused against the operator's CURRENT roots — after approval too
    with pytest.raises(ValueError, match="escapes the operator-configured input roots"):
        api.inputs(started["proposal"], documents=["../extra/wide.md"])
    result = api.inputs(started["proposal"], documents=["inside.md"])
    # only the approved HOST-root source was ever opened, once per measured call
    assert connection_spy == [[str(parquet)], [str(parquet)]]
    assert result["documents"][0]["title"] == "inside.md"
    assert result["documents"][0]["complete"] is True


def test_git_approve_sources_binds_the_exact_candidate_and_digest(tmp_path):
    """Git-mode approval is exact: a stale revision, a digest mismatch, a
    non-digest argument and an unknown proposal all refuse BEFORE any record
    is written — and approval never edits the host root's registry or the
    already-committed candidate."""
    project = git_project(tmp_path)
    write_parquet(project / "data" / "events.parquet")
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"], started["candidate_revision"], [EVENTS_ENTRY]
    )
    for bad in (
        lambda: api.approve_sources(
            started["proposal"], started["candidate_revision"], proposed["source_digest"]
        ),  # stale: the candidate moved with the registry edit
        lambda: api.approve_sources(
            started["proposal"], proposed["revision"], "0" * 64
        ),  # wrong digest
        lambda: api.approve_sources(started["proposal"], proposed["revision"], "not-a-digest"),
        lambda: api.approve_sources(
            "p-00000000000000-000000", proposed["revision"], proposed["source_digest"]
        ),
    ):
        with pytest.raises(ValueError):
            bad()
    assert not (project / ".ariadne" / "source-approvals.json").exists()
    assert (project / "ariadne.yaml").read_text(encoding="utf-8") == "# registry template\n"
    assert branch_of(project, started["proposal"]) == proposed["revision"]
    # the exact arguments record the permission
    approved = api.approve_sources(
        started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved["source_digest"] == proposed["source_digest"]


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "pg", "type": "postgres", "connection": "postgresql://u:p@h/db"},
        {"name": "cdn", "type": "parquet", "path": "https://ro:s3cret@cdn.example.com/e.parquet"},
        {"name": "events", "type": "fancy", "path": "data/events.parquet"},
    ],
    ids=["inline-dsn", "credentialed-url", "unknown-type"],
)
def test_git_propose_sources_reuses_the_registry_validation(tmp_path, entry):
    """The ADR-0010 registry rules apply verbatim to Git-mode proposals: a
    credential-bearing or invalid entry is refused before anything is written
    to the candidate (the matched value is never echoed)."""
    project = git_project(tmp_path)
    write_parquet(project / "data" / "events.parquet")
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError, match="ADR-0010|unknown type") as excinfo:
        api.propose_sources(started["proposal"], started["candidate_revision"], [entry])
    assert "s3cret" not in str(excinfo.value) and "u:p@h" not in str(excinfo.value)
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    registry = proposals.read_artifact(project, started["proposal"], "ariadne.yaml")
    assert "events" not in registry["content"]


def test_git_propose_sources_refuses_duplicate_names_and_stale_revisions(tmp_path):
    """A source proposal appends, never overwrites, and requires the current
    candidate revision exactly like an artifact edit."""
    project = git_project(tmp_path)
    write_parquet(project / "data" / "events.parquet")
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"], started["candidate_revision"], [EVENTS_ENTRY]
    )
    with pytest.raises(ValueError, match="never overwrites"):
        api.propose_sources(started["proposal"], proposed["revision"], [dict(EVENTS_ENTRY)])
    with pytest.raises(ValueError, match="stale"):
        api.propose_sources(
            started["proposal"],
            started["candidate_revision"],
            [{"name": "other", "type": "parquet", "path": "data/events.parquet"}],
        )
    assert branch_of(project, started["proposal"]) == proposed["revision"]


# ------------------------------------- onboarding inputs + uploads outside Git


def test_inputs_without_sources_and_uploads_never_become_git_artifacts(tmp_path, connection_spy):
    """AC5 onboarding: a candidate with no registry sources measures NOTHING
    (profile None, no error — a missing catalog never blocks the flow), uploads
    land in the operator input area with stable evidence digests, and neither
    is ever committed to Git."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()

    empty = api.inputs(started["proposal"])
    assert empty["profile"] is None and empty["sources_digest"] is None
    assert empty["seed_notes"]["digest"] == hashlib.sha256(SEED_NOTES.encode()).hexdigest()
    assert empty["documents"] == []
    assert connection_spy == []

    upload = api.upload_document("notes.md", b"# uploaded policy\n")
    assert upload["resource"] == str(project / "data" / "docs" / "notes.md")
    measured = api.inputs(started["proposal"], documents=["notes.md"])
    assert measured["documents"][0]["digest"] == upload["digest"]
    assert measured["documents"][0]["complete"] is True
    # digests are stable across calls (same bytes, same digest)
    assert (
        api.inputs(started["proposal"], documents=["notes.md"])["documents"][0]["digest"]
        == upload["digest"]
    )
    assert measured["seed_notes"] == empty["seed_notes"]
    # the operator input area is never staged or committed by any edit
    assert run_git(project, "ls-files", "--", "data/docs") == ""
    assert run_git(project, "status", "--porcelain", "--", "data/docs").strip().startswith("??")


def test_cli_git_mode_propose_approve_and_inputs_roundtrip(tmp_path, capsys):
    """The Git-aware CLI surface: propose-sources commits into the candidate
    and returns the resolved digest; approve-sources records the permission;
    inputs measures the approved identity plus operator-bound documents — one
    JSON value per call, and the pre-approval refusal is one JSON error."""
    project = git_project(tmp_path)
    write_parquet(project / "data" / "events.parquet")
    (project / "data" / "docs").mkdir()
    (project / "data" / "docs" / "policy.md").write_text("# Policy\n", encoding="utf-8")
    intake = tmp_path / "proposed.yaml"
    intake.write_text(
        yaml.safe_dump({"sources": [EVENTS_ENTRY]}, sort_keys=False), encoding="utf-8"
    )

    assert authoring_cli(["start", "--project", str(project)]) == 0
    started = json.loads(capsys.readouterr().out)

    assert (
        authoring_cli(
            [
                "propose-sources",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--file",
                str(intake),
                "--project",
                str(project),
            ]
        )
        == 0
    )
    proposed = json.loads(capsys.readouterr().out)
    assert proposed["source_digest"] and proposed["revision"] != started["candidate_revision"]

    assert (
        authoring_cli(
            [
                "inputs",
                "--proposal",
                started["proposal"],
                "--document",
                "policy.md",
                "--project",
                str(project),
            ]
        )
        == 1
    )  # unapproved: one JSON error object
    error = json.loads(capsys.readouterr().err)["error"]
    assert "approval" in error["message"]

    assert (
        authoring_cli(
            [
                "approve-sources",
                "--proposal",
                started["proposal"],
                "--revision",
                proposed["revision"],
                "--source-digest",
                proposed["source_digest"],
                "--project",
                str(project),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["source_digest"] == proposed["source_digest"]

    assert (
        authoring_cli(
            [
                "inputs",
                "--proposal",
                started["proposal"],
                "--document",
                "policy.md",
                "--sample-rows",
                "2",
                "--project",
                str(project),
            ]
        )
        == 0
    )
    measured = json.loads(capsys.readouterr().out)
    table = measured["profile"]["sources"][0]["tables"]["events"]
    assert table["row_count"] == 2 and table["sampled"] is True
    assert measured["documents"][0]["title"] == "policy.md"
