"""Git-aware source access and measured inputs (issue #35 / G3; spec
2026-10-02-0009 §5 "Source approval and artifact admission", AC5/6/8; plan §2
"Project storage and authority" + "Authoring call contract" rows
propose_sources/inputs/reference-based document evidence).

Source approval and artifact admission are distinct decisions: a source entry
committed in a proposal's candidate registry never opens anything until the
separate HUMAN-ONLY approve-sources records the exact RESOLVED identity in the
operator-owned ``.ariadne/source_grants.json`` (outside Git artifacts).
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
import pwd
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
from ariadne import authoring_sources, proposals  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from tests.test_git_authoring import grant_sources  # noqa: E402

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

    def spy(registry, read_only=True, **kwargs):
        # **kwargs forwards the builder's optional deadline/selected_assets
        # (spec0035 §8 budgets) to the real builder; the canary records the
        # same registry identity either way
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only, **kwargs)

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


def write_native_catalog(path: Path) -> Path:
    """A real native DuckDB catalog (spec 0022's hand-specified rows: count 3,
    total 60.0 — inputs declared by the spec, never copied query output)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE main.orders (id INTEGER, amount DOUBLE, region VARCHAR)")
    con.executemany(
        "INSERT INTO main.orders VALUES (?, ?, ?)",
        [(1, 10.0, "EMEA"), (2, 20.0, "AMER"), (3, 30.0, "EMEA")],
    )
    con.close()
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
    # a decoy at the SAME relative path inside the draft worktree: a worktree-
    # relative resolution would open it instead (9 rows, so the profile's row
    # count tells them apart)
    write_parquet(worktree_of(project, a["proposal"]) / "data" / "events.parquet", rows=9)

    proposed_a = api.propose_sources(a["proposal"], a["candidate_revision"], [EVENTS_ENTRY])
    assert len(proposed_a["source_digest"]) == 64
    # the resolved identity is the HOST project root's file, never a worktree
    assert proposed_a["sources"][0]["path"] == str(parquet)
    # the registry edit is committed IN the candidate
    assert proposed_a["revision"] != a["candidate_revision"]
    registry = proposals.read_artifact(project, a["proposal"], "ariadne.yaml")
    assert "events.parquet" in registry["content"]

    # before approval NOTHING opens: inputs is an explicit error in BOTH
    # worktrees, and the shared builder is never called
    with pytest.raises(ValueError, match="approval"):
        api.inputs(a["proposal"])
    assert connection_spy == []

    # the human-only CLI records the exact resolved identity outside Git
    approved = grant_sources(
        api, a["proposal"], proposed_a["revision"], proposed_a["source_digest"]
    )
    assert approved["source_digest"] == proposed_a["source_digest"]
    grants = json.loads((project / ".ariadne" / "source_grants.json").read_text(encoding="utf-8"))
    (record,) = grants["grants"]
    assert record["source"]["path"] == str(parquet)
    assert record["by"] == "human:test-operator"
    # approval edited NO Git artifact: the candidate revision is unchanged
    assert branch_of(project, a["proposal"]) == proposed_a["revision"]
    assert tracked_dirty(project, a["proposal"]) == ""

    # after the grant the draft reads the HOST identity — never the worktree decoy
    result = api.inputs(a["proposal"])
    (source,) = result["profile"]["sources"]
    assert source["name"] == "events"
    assert source["tables"]["events"]["row_count"] == 3  # the HOST file
    assert result["revision"] == branch_of(project, a["proposal"])
    assert connection_spy == [[str(parquet)]]

    # a NATIVE catalog entry is the same human gate (spec 0022 AC6): the
    # proposal opens nothing until the operator approves the exact new identity
    native_db = write_native_catalog(project / "data" / "warehouse.duckdb")
    native_entry = {"name": "warehouse", "type": "duckdb", "path": "data/warehouse.duckdb"}
    reproposed = api.propose_sources(a["proposal"], proposed_a["revision"], [native_entry])
    assert reproposed["source_digest"] != proposed_a["source_digest"]
    with pytest.raises(ValueError, match="NO grant"):
        api.inputs(a["proposal"])
    assert connection_spy == [[str(parquet)]]  # still nothing new

    approved = grant_sources(
        api, a["proposal"], reproposed["revision"], reproposed["source_digest"]
    )
    capsys.readouterr()
    profile = api.inputs(a["proposal"])["profile"]["sources"]
    assert [source["name"] for source in profile] == ["events", "warehouse"]
    assert profile[1]["tables"]["orders"]["row_count"] == 3  # the native fixture rows
    assert connection_spy[-1] == [str(parquet), str(native_db)]  # host identity only


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
    grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])
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
    with pytest.raises(ValueError, match="NO grant") as excinfo:
        api.inputs(started["proposal"])
    assert changed["source_digest"] in str(excinfo.value)  # the error names the new identity
    assert connection_spy == [[str(events)]]  # nothing new was opened

    # the earlier record is still there (no revocation); approving the exact
    # new identity restores access through the approved registry only
    grant_sources(api, started["proposal"], changed["revision"], changed["source_digest"])
    grants = json.loads((project / ".ariadne" / "source_grants.json").read_text(encoding="utf-8"))
    assert [g["source"]["name"] for g in grants["grants"]] == ["events", "events", "other"]
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
    with pytest.raises(ValueError, match="NO grant"):
        api.inputs(started["proposal"], documents=["../extra/wide.md"])
    assert connection_spy == []

    grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])
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
        lambda: grant_sources(
            api, started["proposal"], started["candidate_revision"], proposed["source_digest"]
        ),  # stale: the candidate moved with the registry edit
        lambda: grant_sources(
            api, started["proposal"], proposed["revision"], "0" * 64
        ),  # wrong digest
        lambda: grant_sources(api, started["proposal"], proposed["revision"], "not-a-digest"),
        lambda: grant_sources(
            api, "p-00000000000000-000000", proposed["revision"], proposed["source_digest"]
        ),
    ):
        with pytest.raises(ValueError):
            bad()
    assert not (project / ".ariadne" / "source_grants.json").exists()
    assert (project / "ariadne.yaml").read_text(encoding="utf-8") == "# registry template\n"
    assert branch_of(project, started["proposal"]) == proposed["revision"]
    # the exact arguments record the permission
    approved = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
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


def test_inputs_without_sources_and_operator_documents_remain_external(tmp_path, connection_spy):
    """A source-free candidate does not open data; operator documents stay external."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()

    empty = api.inputs(started["proposal"])
    assert empty["profile"] is None and empty["sources_digest"] is None
    assert empty["seed_notes"]["digest"] == hashlib.sha256(SEED_NOTES.encode()).hexdigest()
    assert empty["documents"] == []
    assert connection_spy == []

    from ariadne.authoring_inputs import document_evidence

    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    raw = b"# operator-placed policy\n"
    (docs / "notes.md").write_bytes(raw)
    evidence = document_evidence("notes.md", project=project)
    assert evidence["resource"] == str(project / "data" / "docs" / "notes.md")
    assert evidence["digest"] == hashlib.sha256(raw).hexdigest()
    assert evidence["complete"] is True
    assert not (project / "data" / "object-store").exists()
    assert run_git(project, "ls-files", "--", "data/docs") == ""
    assert run_git(project, "status", "--porcelain", "--", "data/docs").strip().startswith("??")


def test_inputs_selected_table_is_bounded_and_approved(tmp_path):
    project = git_project(tmp_path)
    write_parquet(project / "data" / "events.parquet", rows=3)
    write_parquet(project / "data" / "other.parquet", rows=7)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"],
        started["candidate_revision"],
        [EVENTS_ENTRY, {"name": "other", "type": "parquet", "path": "data/other.parquet"}],
    )
    grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])

    measured = api.inputs(started["proposal"], selector=("events", "events"), sample_rows=2)

    (source,) = measured["profile"]["sources"]
    assert source["name"] == "events"
    assert set(source["tables"]) == {"events"}
    assert source["tables"]["events"]["row_count"] == 2
    assert source["tables"]["events"]["sample_limit"] == 2


def test_inputs_expected_revision_preflights_and_default_is_unchanged(tmp_path, connection_spy):
    project = git_project(tmp_path)
    write_parquet(project / "data" / "events.parquet", rows=3)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"], started["candidate_revision"], [EVENTS_ENTRY]
    )
    grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])

    baseline = api.inputs(started["proposal"])
    pinned = api.inputs(started["proposal"], expected_revision=proposed["revision"])

    def canonical_ties(document):
        for source in document["profile"]["sources"]:
            for table in source["tables"].values():
                for column in table["columns"].values():
                    if "top_values" in column:
                        column["top_values"] = sorted(
                            column["top_values"], key=lambda item: json.dumps(item, sort_keys=True)
                        )
        return document

    # Equal-count top values have no native ordering contract;
    # every other envelope fact compares exactly.
    assert canonical_ties(pinned) == canonical_ties(baseline)
    assert len(connection_spy) == 2
    with pytest.raises(ValueError, match="stale revision"):
        api.inputs(started["proposal"], expected_revision=started["candidate_revision"])
    assert len(connection_spy) == 2


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

    granted = grant_sources(
        AuthoringProject(project),
        started["proposal"],
        proposed["revision"],
        proposed["source_digest"],
    )
    assert granted["source_digest"] == proposed["source_digest"]

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


# ------------------------------------- postgres effective destination (issue #110)

_PG_ENV = "ARIADNE_TEST_PG_DSN"

# Supported DSN representations (libpq URI and keyword/value — the postgres
# extension takes a libpq connstring), each with its own synthetic DB-A /
# rotated-credential / DB-B values and an implicit-target connstring (host
# omitted; libpq resolves it from PGHOST). Expectations come from spec 0025
# §4, not from implementation output. ``plan_rotation_dsn`` is the DSN used
# at the ATTACH-reaching frozen-check step: quote-bearing connstrings refuse
# at ATTACH construction by the existing no-quotes rule (a separate contract,
# pre-existing), so the quoted forms here are pinned at the binding/approval
# level and their identical quote-free binding is used for that one step.
_PG_DSN_CASES = [
    pytest.param(
        "postgresql://owner:pgsecret-a@db-a.internal:5432/app",
        "postgresql://owner:pgsecret-rot@db-a.internal:5432/app",
        "postgresql://owner:pgsecret-b@db-b.internal:5432/app",
        "postgresql://owner:pgsecret-rot@db-a.internal:5432/app",
        "postgresql:///app",
        id="libpq-uri",
    ),
    pytest.param(
        "host=db-a.internal port=5432 dbname=app user=owner password=pgsecret-a",
        "host=db-a.internal port=5432 dbname=app user=owner password=pgsecret-rot",
        "host=db-b.internal port=5432 dbname=app user=owner password=pgsecret-b",
        "host=db-a.internal port=5432 dbname=app user=owner password=pgsecret-rot",
        "dbname=app",
        id="libpq-key-value",
    ),
    pytest.param(
        # last-wins quoting: decoy-then-authoritative values, quoted values
        # with spaces — the LAST host/user/password is the effective one.
        "host=decoy.internal host=db-a.internal dbname=app user=ghost user=owner"
        " password='decoy one' password='pgsecret a'",
        "host=decoy.internal host=db-a.internal dbname=app user=ghost user=owner"
        " password='decoy one' password='pgsecret rot'",
        "host=decoy.internal host=db-b.internal dbname=app user=ghost user=owner"
        " password='decoy one' password='pgsecret b'",
        "host=db-a.internal dbname=app user=owner password=pgsecret-rot",
        "dbname=app",
        id="kv-last-wins-quoting",
    ),
    pytest.param(
        # URI query override: an empty hierarchy with the target supplied as
        # named query parameters (libpq's documented alternative form).
        "postgresql:///app?host=db-a.internal&port=5432&user=owner&password=pgsecret-a",
        "postgresql:///app?host=db-a.internal&port=5432&user=owner&password=pgsecret-rot",
        "postgresql:///app?host=db-b.internal&port=5432&user=owner&password=pgsecret-b",
        "postgresql:///app?host=db-a.internal&port=5432&user=owner&password=pgsecret-rot",
        "postgresql:///app",
        id="uri-query-override",
    ),
    pytest.param(
        # libpq percent decoding: a literal ``+`` is NOT a space — ``app+blue``
        # and ``app%20blue`` are two DIFFERENT valid databases that must bind
        # differently (HTML-form decoding would collapse them).
        "postgresql://owner:pgsecret-a@db-a.internal:5432/?dbname=app+blue",
        "postgresql://owner:pgsecret-rot@db-a.internal:5432/?dbname=app+blue",
        "postgresql://owner:pgsecret-b@db-a.internal:5432/?dbname=app%20blue",
        "postgresql://owner:pgsecret-rot@db-a.internal:5432/?dbname=app+blue",
        "dbname=app",
        id="uri-percent-dbname",
    ),
    pytest.param(
        # URI path delimiter: exactly ONE leading slash is the separator —
        # ``//app`` names the database "/app", not ``app`` (no lossy
        # normalization of the target).
        "postgresql://owner:pgsecret-a@db-a.internal:5432//app",
        "postgresql://owner:pgsecret-rot@db-a.internal:5432//app",
        "postgresql://owner:pgsecret-b@db-a.internal:5432/app",
        "postgresql://owner:pgsecret-rot@db-a.internal:5432//app",
        "dbname=app",
        id="uri-path-slashes",
    ),
    pytest.param(
        # ordered multi-host: DB-B differs from DB-A ONLY by host ORDER — the
        # ordered list is part of the destination identity (failover order).
        "postgresql://owner:pgsecret-a@db-a.internal,db-c.internal:5433/app",
        "postgresql://owner:pgsecret-rot@db-a.internal,db-c.internal:5433/app",
        "postgresql://owner:pgsecret-b@db-c.internal,db-a.internal:5433/app",
        "postgresql://owner:pgsecret-rot@db-a.internal,db-c.internal:5433/app",
        "dbname=app",
        id="uri-multihost-ordered",
    ),
]


@pytest.mark.parametrize("dsn_a,dsn_rotated,dsn_b,plan_rotation_dsn,implicit_dsn", _PG_DSN_CASES)
def test_postgres_destination_change_under_same_env_name_needs_its_own_approval(
    tmp_path, monkeypatch, dsn_a, dsn_rotated, dsn_b, plan_rotation_dsn, implicit_dsn
):
    """A PostgreSQL destination change under an UNCHANGED ``connection_env``
    name is a changed effective source identity (spec 0025 §4 keyed grants;
    spec0035 §3/AC3; issue #110 source-boundary gate), never harmless secret
    rotation: DB-A's approval must refuse DB-B BEFORE any source open. The
    contract-derived expectations:

    1. approval binds the EFFECTIVE destination — the recorded grant carries
       the resolved non-secret destination, never a credential value;
    2. DB-B under the same variable name refuses with no builder call (the
       recorder IS the real builder boundary ``ariadne.sources
       .build_connection`` — profiler opens through it);
    3. rotating ONLY the credential at the same destination keeps the same
       effective approval identity (spec 0025 §4: rotation is not a
       destination change);
    4. the approved binding freezes through the builder seam: plan() refuses
       a re-resolved different destination (no check-A/open-B window) and
       accepts the rotated credential at the same destination.
    """
    opened: list[list[str | None]] = []

    def refusing_builder(registry, read_only=True):
        opened.append([src.connection_env for src in registry.sources])
        raise AssertionError(
            "the shared connection builder was handed an identity that must "
            "refuse at the approval gate — nothing may open here"
        )

    monkeypatch.setattr(ariadne.sources, "build_connection", refusing_builder)

    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"],
        started["candidate_revision"],
        [{"name": "pg", "type": "postgres", "connection_env": _PG_ENV}],
    )

    # DB-A: the operator approves under the CURRENT destination.
    monkeypatch.setenv(_PG_ENV, dsn_a)
    approved_a = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )

    # DB-B under the SAME env name: the historical DB-A grant must refuse
    # BEFORE any open — a changed destination is a changed effective identity.
    monkeypatch.setenv(_PG_ENV, dsn_b)
    with pytest.raises(ValueError, match="NO grant"):
        api.inputs(started["proposal"])
    assert opened == []  # the builder boundary was never reached

    # The grant binds the effective NON-SECRET destination, never a secret;
    # the binding key is the collision-free namespaced ``postgres:<name>``
    # (S3 profile keys stay plain slugs; colons occur in neither namespace).
    assert approved_a["approval_digest"] != approved_a["source_digest"]
    assert set(approved_a["storage_bindings"]) == {"postgres:pg"}
    record_text = (project / ".ariadne" / "source_grants.json").read_text(encoding="utf-8")
    assert "pgsecret" not in record_text  # no plaintext DSN/credential in the grant
    assert "db-a.internal" in record_text  # the destination itself is recorded

    # Credential rotation at the SAME destination: same effective approval
    # identity — no new destination grant is minted (spec 0025 §4).
    monkeypatch.setenv(_PG_ENV, dsn_rotated)
    approved_rotated = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_rotated["approval_digest"] == approved_a["approval_digest"]

    # The approved binding FREEZES through the builder seam: a re-resolved
    # different destination refuses at plan() (no check-A/open-B window);
    # the rotated credential at the SAME destination passes the frozen check.
    registry = authoring_sources.identity_registry(
        approved_a["sources"], approved_a["storage_bindings"]
    )
    monkeypatch.setenv(_PG_ENV, dsn_b)
    with pytest.raises(ValueError, match=_PG_ENV) as frozen_error:
        ariadne.sources.plan(registry)
    assert "pgsecret" not in str(frozen_error.value)  # no secret in the refusal
    monkeypatch.setenv(_PG_ENV, plan_rotation_dsn)
    loads, statements = ariadne.sources.plan(registry)
    assert any("TYPE POSTGRES" in statement for statement in statements)

    # Implicit-target ENV drift (one concrete case): a connstring that OMITS
    # the host resolves its target against the PG destination environment
    # (libpq defaults; DuckDB postgres ATTACH takes a libpq connstring), so a
    # PGHOST change A->B is a destination change even though the approved
    # variable VALUE never changed — it must refuse before any open.
    monkeypatch.setenv("PGHOST", "db-a.internal")
    monkeypatch.setenv(_PG_ENV, implicit_dsn)
    approved_implicit = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_implicit["approval_digest"] != approved_a["approval_digest"]
    monkeypatch.setenv("PGHOST", "db-b.internal")
    with pytest.raises(ValueError, match="NO grant"):
        api.inputs(started["proposal"])
    assert opened == []

    # Service-file indirection (service=) refuses at approval instead of
    # guessing the file-resolved target (owner-approved narrowing): the
    # refusal names the variable and the keyword, never the connection value.
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.setenv(_PG_ENV, "service=prod dbname=app")
    with pytest.raises(ValueError, match="service") as service_error:
        grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])
    assert _PG_ENV in str(service_error.value)
    assert "prod" not in str(service_error.value)  # never the service VALUE
    assert opened == []  # nothing was opened for the refused form either

    # An ACTIVE PGSERVICE environment selects the target through the service
    # file even WITHOUT service= in the connection string — the same refused
    # indirection, named by variable, never by its value.
    monkeypatch.setenv("PGSERVICE", "prod")
    monkeypatch.setenv(_PG_ENV, "dbname=app user=owner")
    with pytest.raises(ValueError, match="PGSERVICE") as env_service_error:
        grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])
    assert "prod" not in str(env_service_error.value)
    assert opened == []
    monkeypatch.delenv("PGSERVICE")

    # The libpq default user is the EFFECTIVE operating-system account —
    # never the LOGNAME/USER environment hints (independent oracle: the OS
    # account database itself). Naming that account via PGUSER afterwards is
    # a TARGET change, not a silent alias of the same identity.
    for hint in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.setenv(hint, "ariadne-decoy-user")
    effective_user = pwd.getpwuid(os.geteuid()).pw_name
    monkeypatch.setenv(_PG_ENV, "host=db-a.internal dbname=app")
    approved_os = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_os["storage_bindings"]["postgres:pg"]["user"] == effective_user
    monkeypatch.setenv("PGUSER", "ariadne-decoy-user")
    approved_pguser = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_pguser["approval_digest"] != approved_os["approval_digest"]
    monkeypatch.delenv("PGUSER")

    # Malformed URIs refuse through the sanitized parser boundary: a decoder
    # exception must never echo the connection string — this netloc carries
    # an NFKC-invalid fullwidth slash, so the raw parser error would surface
    # the password.
    monkeypatch.setenv(_PG_ENV, "postgresql://owner:pgsecret@db／a/app")
    with pytest.raises(ValueError, match="not a valid connection URI") as nfkc_error:
        grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])
    assert "pgsecret" not in str(nfkc_error.value)
    assert opened == []

    # Nonempty PG destination ENV values are significant VERBATIM (libpq
    # takes the getenv result as-is; only "" stays unset): a database or
    # role named with significant whitespace is a DIFFERENT valid target
    # than its trimmed form, so switching between them requires its own
    # approval and is recorded without trimming (spec 0025 §4 exact current
    # effective dbname/user binding).
    monkeypatch.setenv(_PG_ENV, "host=db-a.internal user=owner")
    monkeypatch.setenv("PGDATABASE", "app")
    approved_db = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_db["storage_bindings"]["postgres:pg"]["dbname"] == "app"
    monkeypatch.setenv("PGDATABASE", "app ")  # one significant trailing space
    with pytest.raises(ValueError, match="NO grant"):
        api.inputs(started["proposal"])  # the 'app' grant does not cover 'app '
    assert opened == []
    approved_db_ws = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_db_ws["storage_bindings"]["postgres:pg"]["dbname"] == "app "
    assert approved_db_ws["approval_digest"] != approved_db["approval_digest"]
    # same raw ENV branch for the role: PGUSER keeps significant characters;
    # the 'owner ' role is a different target than any approved role, so a
    # fresh approval records it verbatim and no earlier grant covers it
    monkeypatch.setenv(_PG_ENV, "host=db-a.internal dbname=app")
    monkeypatch.setenv("PGUSER", "owner ")
    approved_user_ws = grant_sources(
        api, started["proposal"], proposed["revision"], proposed["source_digest"]
    )
    assert approved_user_ws["storage_bindings"]["postgres:pg"]["user"] == "owner "
    monkeypatch.setenv("PGUSER", "other-role")
    with pytest.raises(ValueError, match="NO grant"):
        api.inputs(started["proposal"])  # no grant covers dbname 'app ' + 'other-role'
    assert opened == []


def test_authoring_profiling_limits_are_host_owned_and_complete(tmp_path, connection_spy):
    """spec0035 §8 "Source-boundary disposition: authoring profiling limits
    (2026-11-11)": the HOST-owned ``profiling:`` section governs every
    agent-facing profiling run — ``inputs`` AND schema refresh — with one
    total finite budget across approved setup, sampling, statistics and FK
    inspection, an explicit-sample row ceiling, and a complete-profile
    payload ceiling. Hand-known 3-row fixture values prove fitting full
    statistics stay exact and sampled markers stay honest; expiry refuses
    without partial profiles or refreshed writes; oversize refuses without
    clipping; operator raise/lower takes effect; and the candidate's own
    committed widened ``profiling:`` section is inert — the operator's
    current host configuration always wins. Deadline behavior rides the
    established deterministic deadline-clock seam (no sleeps, no live
    sources)."""
    import time as _time

    from ariadne import execution, profiler

    # the candidate inherits a WIDENED profiling section committed at base;
    # every assertion below runs against the narrowed CURRENT host file —
    # candidate config never widens host policy
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    (project / "ariadne.yaml").write_text(
        "profiling:\n"
        "  sample_rows: 1000000\n"
        "  execution_seconds: 999999.0\n"
        "  response_bytes: 1000000000\n",
        encoding="utf-8",
    )
    (project / "data").mkdir()
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    kb = project / "knowledge"
    kb.mkdir()
    (kb / "lumio.yaml").write_text(
        "version: 2\nmode: categorized\n"
        "categories:\n  - name: tables\n  - name: datasets\n"
        "ontology:\n  entity_types:\n    table: {}\n    dataset: {}\n"
        "  predicates: {}\n  redirects: {}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_text(
        "version: 1\nnamespace: urn:uuid:profiling-fixture\nsources: {}\nbindings: {}\n",
        encoding="utf-8",
    )
    (project / "context_integration.yaml").write_text(
        "version: 1\nmode: integrated\nsubtree: knowledge\n"
        "namespace: urn:uuid:profiling-fixture\nprofile: ariadne-context/1\n"
        "support_revision: 2\npolicy_bindings:\n  version: 1\n  bindings: []\n",
        encoding="utf-8",
    )
    run_git(
        project,
        "add",
        "--",
        "ariadne.yaml",
        "data/seed_notes.md",
        "knowledge",
        "context_integration.yaml",
    )
    run_git(project, "commit", "-q", "-m", "human: widened profiling section")
    parquet = write_parquet(project / "data" / "events.parquet", rows=3)

    api = AuthoringProject(project)
    started = api.start_proposal()
    proposed = api.propose_sources(
        started["proposal"], started["candidate_revision"], [EVENTS_ENTRY]
    )
    assert proposed["sources"][0]["path"] == str(parquet)  # the HOST-root identity
    candidate_registry = proposals.read_artifact(project, started["proposal"], "ariadne.yaml")[
        "content"
    ]
    assert "sample_rows: 1000000" in candidate_registry  # the widened candidate claim
    grant_sources(api, started["proposal"], proposed["revision"], proposed["source_digest"])

    # the operator narrows the host working config to NO profiling section:
    # built-in defaults govern from here on, never the candidate's claim
    (project / "ariadne.yaml").write_text(
        "# operator host config (no profiling section)\n", encoding="utf-8"
    )

    # --- fitting FULL statistics keep their exact hand-known values under
    # the default ceilings (3-row parquet: ids 1..3, labels row1..row3)
    measured = api.inputs(started["proposal"])
    (source,) = measured["profile"]["sources"]
    table = source["tables"]["events"]
    assert table["row_count"] == 3
    # both columns are null-free and fully distinct at 3 rows: both qualify
    # as PK candidates (existing heuristic), id first in catalog order
    assert table["primary_key_candidates"] == ["id", "label"]
    assert table["foreign_key_candidates"] == []
    assert table["columns"]["id"]["distinct_count"] == 3
    assert table["columns"]["id"]["null_count"] == 0
    assert table["columns"]["label"]["distinct_count"] == 3
    assert "sampled" not in table and "sample_limit" not in table
    asset = {
        "source": table["source"],
        "catalog": table["catalog"],
        "schema": table["schema"],
        "table": table["table"],
    }

    # --- EXPLICIT sample below the ceiling: honest sampled markers; the
    # sample_limit is the REQUEST, never the host ceiling
    sampled = api.inputs(started["proposal"], sample_rows=2)
    stable = sampled["profile"]["sources"][0]["tables"]["events"]
    assert stable["row_count"] == 2  # the materialized sample, labeled as such
    assert stable["sampled"] is True and stable["sample_limit"] == 2
    assert stable["primary_key_candidates"] == []
    assert stable["foreign_key_candidates"] == []

    # --- a request above the default host ceiling refuses BEFORE any open
    opens = len(connection_spy)
    with pytest.raises(ValueError, match="profiling ceiling"):
        api.inputs(started["proposal"], sample_rows=1001)
    assert len(connection_spy) == opens  # the shared builder was never called

    # --- operator RAISE takes effect (and still bounds: candidate 1000000 is inert)
    (project / "ariadne.yaml").write_text("profiling:\n  sample_rows: 5000\n", encoding="utf-8")
    raised = api.inputs(started["proposal"], sample_rows=5000)
    assert raised["profile"]["sources"][0]["tables"]["events"]["sample_limit"] == 5000
    with pytest.raises(ValueError, match="profiling ceiling"):
        api.inputs(started["proposal"], sample_rows=5001)

    # --- operator LOWER binds just the same
    (project / "ariadne.yaml").write_text("profiling:\n  sample_rows: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="profiling ceiling"):
        api.inputs(started["proposal"], sample_rows=3)
    lowered = api.inputs(started["proposal"], sample_rows=2)
    assert lowered["profile"]["sources"][0]["tables"]["events"]["sample_limit"] == 2

    # --- invalid host settings refuse actionably BEFORE source access
    opens = len(connection_spy)
    (project / "ariadne.yaml").write_text("profiling:\n  sample_rows: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a positive integer"):
        api.inputs(started["proposal"])
    (project / "ariadne.yaml").write_text("profiling:\n  execution_seconds: 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a finite positive number"):
        api.inputs(started["proposal"])
    assert len(connection_spy) == opens

    # --- fitting refresh under the same ceilings: pages are written (the
    # budget/payload wiring must not disturb the working refresh path)
    (project / "ariadne.yaml").write_text(
        "# operator host config (no profiling section)\n", encoding="utf-8"
    )
    refreshed = api.refresh_schema(started["proposal"], proposed["revision"], [asset])
    assert refreshed["changed"] is True
    assert refreshed["pages"]
    settled_revision = refreshed["revision"]

    # --- refresh oversize refuses the payload BEFORE any page is written
    (project / "ariadne.yaml").write_text("profiling:\n  response_bytes: 64\n", encoding="utf-8")
    with pytest.raises(profiler.ProfilingPayloadExceeded, match="payload"):
        api.refresh_schema(started["proposal"], settled_revision, [asset])
    assert branch_of(project, started["proposal"]) == settled_revision
    assert tracked_dirty(project, started["proposal"]) == ""

    # --- inputs oversize refuses without a partial or clipped profile
    with pytest.raises(profiler.ProfilingPayloadExceeded, match="payload"):
        api.inputs(started["proposal"])

    # --- pre-transfer guard: a SINGLE statistic longer than the whole ceiling
    # refuses before its value crosses into Python at all — the hand-known
    # label min/max are 4-char strings ('row1'..), so a 2-byte ceiling
    # cannot fit them and the guard fires before the SUMMARIZE fetch
    (project / "ariadne.yaml").write_text("profiling:\n  response_bytes: 2\n", encoding="utf-8")
    with pytest.raises(profiler.ProfilingPayloadExceeded, match="statistic serializes"):
        api.inputs(started["proposal"])

    # --- two further approved sources for the reviewer's concrete scenarios:
    # one CJK-statistic table (real CLI escaping) and one wide ASCII table
    # (bounded collection against the remaining shared budget)
    (project / "ariadne.yaml").write_text(
        "# operator host config (no profiling section)\n", encoding="utf-8"
    )
    cjk_con = duckdb.connect()
    cjk_con.execute("CREATE TABLE notes (id INTEGER, note VARCHAR)")
    cjk_con.executemany("INSERT INTO notes VALUES (?, ?)", [(1, "一" * 6000)])
    cjk_con.execute(f"COPY notes TO '{project / 'data' / 'cjk.parquet'}' (FORMAT PARQUET)")
    cjk_con.close()
    wide_con = duckdb.connect()
    wide_con.execute(
        "CREATE TABLE wide_t (c0 VARCHAR, c1 VARCHAR, c2 VARCHAR, c3 VARCHAR, "
        "c4 VARCHAR, c5 VARCHAR, c6 VARCHAR, c7 VARCHAR)"
    )
    wide_con.executemany(
        "INSERT INTO wide_t VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple("x" * 30_000 for _ in range(8))],
    )
    wide_con.execute(f"COPY wide_t TO '{project / 'data' / 'wide.parquet'}' (FORMAT PARQUET)")
    wide_con.close()
    reproposed = api.propose_sources(
        started["proposal"],
        settled_revision,
        [
            {"name": "cjk", "type": "parquet", "path": "data/cjk.parquet"},
            {"name": "wide", "type": "parquet", "path": "data/wide.parquet"},
        ],
    )
    grant_sources(api, started["proposal"], reproposed["revision"], reproposed["source_digest"])
    settled_revision = reproposed["revision"]

    # --- Unicode ACTUAL CLI accounting (independent oracle: authoring_cli.py
    # prints the inputs result with json.dumps DEFAULT escaping): 6,000
    # U+4E00 chars serialize as 72,000 bytes of \uXXXX escapes for min+max
    # alone — over the default 65,536 ceiling. Accounting that uses a
    # smaller encoding would return a successful over-ceiling profile.
    with pytest.raises(profiler.ProfilingPayloadExceeded, match="payload"):
        api.inputs(started["proposal"], selector=("cjk", "cjk"))

    # --- bounded collection BEFORE fetch: 8 columns x 30,000 ASCII chars
    # = 480,000 lower-bound serialized bytes, far over the default ceiling's
    # remaining budget. The refusal must fire before ANY min/max statistic
    # transfers ("nothing was transferred"), not after collecting the whole
    # table's stats into Python (an eventual refusal alone proves nothing).
    with pytest.raises(profiler.ProfilingPayloadExceeded, match="nothing was transferred"):
        api.inputs(started["proposal"], selector=("wide", "wide"))

    # --- refresh over an ATTACHED catalog whose declared-metadata SQL must
    # run under the SAME shared profiling budget (native duckdb attach, so
    # _declared_columns really executes information_schema SQL — parquet
    # file views skip it): expired budget refuses before any page write
    native_db = write_native_catalog(project / "data" / "warehouse.duckdb")
    nat = api.propose_sources(
        started["proposal"],
        settled_revision,
        [{"name": "warehouse", "type": "duckdb", "path": "data/warehouse.duckdb"}],
    )
    grant_sources(api, started["proposal"], nat["revision"], nat["source_digest"])
    settled_revision = nat["revision"]
    native_measured = api.inputs(started["proposal"], selector=("warehouse", "orders"))
    native_row = native_measured["profile"]["sources"][0]["tables"]["orders"]
    native_asset = {
        "source": native_row["source"],
        "catalog": native_row["catalog"],
        "schema": native_row["schema"],
        "table": native_row["table"],
    }
    assert (
        str(native_db) == native_measured["profile"]["sources"][0]["tables"]["orders"]["resource"]
        or native_row["source"] == "warehouse"
    )

    # --- expired budget on inputs: explicit deadline refusal, no partial
    real_clock = execution._deadline_clock
    opens_before_deadline = len(connection_spy)
    (project / "ariadne.yaml").write_text(
        "# operator host config (no profiling section)\n", encoding="utf-8"
    )

    def spent_clock(real_reads: int = 2):
        # deterministic, no sleeps: the first `real_reads` clock reads are
        # real time (budget creation, the setup deadline, and — with 3 —
        # the post-setup expiry check), every later read jumps 10,000s — the
        # budget expires mid-operation at the next guarded statement, never
        # a race
        reads = iter([_time.monotonic()] * real_reads)
        return lambda: next(reads, _time.monotonic() + 10_000)

    execution._deadline_clock = spent_clock()
    try:
        with pytest.raises(execution.DeadlineExhausted, match="deadline"):
            api.inputs(started["proposal"])

        # --- expired budget on refresh: refusal before ANY generated fact
        execution._deadline_clock = spent_clock()
        with pytest.raises(execution.DeadlineExhausted, match="deadline"):
            api.refresh_schema(started["proposal"], settled_revision, [asset])
        assert branch_of(project, started["proposal"]) == settled_revision
        assert tracked_dirty(project, started["proposal"]) == ""

        # --- attached-catalog refresh under an expired budget: the clock
        # stays real through budget creation, setup and the post-setup check
        # (three reads), then expires — the catalog metadata phase is the
        # next guarded statement under the SAME shared budget, and no page
        # is written
        execution._deadline_clock = spent_clock(real_reads=3)
        with pytest.raises(execution.DeadlineExhausted, match="deadline"):
            api.refresh_schema(started["proposal"], settled_revision, [native_asset])
        assert branch_of(project, started["proposal"]) == settled_revision
        assert tracked_dirty(project, started["proposal"]) == ""
    finally:
        execution._deadline_clock = real_clock

    # --- surviving-F1 bounded completion (owner-a3): top-values across
    # columns must consume the shared budget AS COLLECTED. Fixture: three
    # rows, eight VARCHAR columns, each column holding exactly a,
    # 'm' + 'x'*30000, z. Default ceilings: the min/max lower bound totals
    # 16 chars (passes); each column's largest top value is 30,001 chars
    # (per-stat passes); only TWO such columns fit the 65,536-byte shared
    # budget — the third must refuse BEFORE its values transfer. The proof
    # is a read-only observer wrapped around the REAL relation fetch (the
    # external I/O seam): it counts large strings that actually crossed into
    # Python — no fake stats, no budget/algorithm mocking, and the eventual
    # exception alone would NOT prove bounded collection.
    flat_con = duckdb.connect()
    flat_con.execute(
        "CREATE TABLE flat_t (c0 VARCHAR, c1 VARCHAR, c2 VARCHAR, c3 VARCHAR, "
        "c4 VARCHAR, c5 VARCHAR, c6 VARCHAR, c7 VARCHAR)"
    )
    big = "m" + "x" * 30_000
    flat_con.executemany(
        "INSERT INTO flat_t VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("a", "a", "a", "a", "a", "a", "a", "a"),
            (big, big, big, big, big, big, big, big),
            ("z", "z", "z", "z", "z", "z", "z", "z"),
        ],
    )
    flat_con.execute(f"COPY flat_t TO '{project / 'data' / 'flat.parquet'}' (FORMAT PARQUET)")
    flat_con.close()
    flat = api.propose_sources(
        started["proposal"],
        settled_revision,
        [{"name": "flat", "type": "parquet", "path": "data/flat.parquet"}],
    )
    grant_sources(api, started["proposal"], flat["revision"], flat["source_digest"])
    settled_revision = flat["revision"]

    class _TransferObserver:
        """Counts LARGE string values that REALLY crossed the fetch boundary
         into Python (read-only wrapper around the real DuckDBPyRelation
        .fetchall; the database does all the work)."""

        def __init__(self) -> None:
            self.large_transferred = 0
            self._real = duckdb.DuckDBPyRelation.fetchall

        def __enter__(self):
            observer = self

            def observing(relation):
                rows = self._real(relation)
                for row in rows:
                    for value in row:
                        if isinstance(value, str) and len(value) > 1000:
                            observer.large_transferred += 1
                return rows

            duckdb.DuckDBPyRelation.fetchall = observing
            return self

        def __exit__(self, *exc):
            duckdb.DuckDBPyRelation.fetchall = self._real
            return False

    with _TransferObserver() as observed:
        with pytest.raises(profiler.ProfilingPayloadExceeded):
            api.inputs(started["proposal"], selector=("flat", "flat"))
    # 2 x 30,001 <= 65,536 < 3 x 30,001: exactly two columns' worth of large
    # top values may transfer before the shared budget refuses the third
    assert observed.large_transferred == 2

    # each deadline refusal completed the APPROVED setup (one open each) and
    # refused before any profiling statement — never a partial measurement;
    # the earlier pre-open refusals (request over ceiling, invalid config)
    # opened nothing at all, asserted at their own checkpoints above; the
    # bounded-completion case above opened exactly once more
    assert len(connection_spy) == opens_before_deadline + 4
