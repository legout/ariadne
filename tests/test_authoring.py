"""Harness-led authoring, slice 1 (issue #13; spec 2026-09-24-0005 §Evidence
and source-access boundary, ADR-0013).

Public-seam tests over ``ariadne.authoring`` and ``ariadne.authoring_cli``:
a proposed registry entry is inert data until a digest-matched, human-operated
``approve-sources`` installs it into the project's ``ariadne.yaml`` — and only
then does it become profileable through the same shared connection
(``ariadne.sources.build_connection``) every existing command uses. The canary
in the first test spies on that one chokepoint to prove no proposed location is
ever opened before approval. No network, no LLM.
"""

import json
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.profiler  # noqa: E402
import ariadne.sources  # noqa: E402
from ariadne import authoring  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402

# ---------------------------------------------------------------- fixtures


def write_parquet(path: Path, rows: int = 3) -> Path:
    """A real local parquet file (DuckDB-written) the approved profile reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) t(id, label)) "
        f"TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def scaffold_project(tmp_path: Path) -> Path:
    """A fresh ariadne project: the commented ariadne.yaml template plus one
    unrelated real config key that approval must preserve."""
    (tmp_path / "ariadne.yaml").write_text(
        "# ariadne.yaml — declarative source registry (ADR-0010).\n"
        "# Sources arrive only via ariadne-authoring approve-sources (issue #13).\n"
        f"retention_days: {90}\n",
        encoding="utf-8",
    )
    return tmp_path


def write_proposal(tmp_path: Path, sources: list[dict], name: str = "proposed.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"sources": sources}, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def connection_spy(monkeypatch):
    """Record every registry handed to THE connection builder (the single
    chokepoint serve/author/validate/profiler all share) — the canary proving a
    proposed location is never opened."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    monkeypatch.setattr(ariadne.profiler, "build_connection", spy)
    return opened


# ------------------------------------------------------ the red/green seam


def test_proposed_source_is_inert_until_digest_matched_approval(
    tmp_path, monkeypatch, connection_spy
):
    """Issue #13 seam: propose -> (nothing opened) -> wrong digest refused ->
    matching digest installs exactly the approved entries, preserving unrelated
    config -> the source profiles through the same connection as every
    existing command."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    proposal = write_proposal(
        tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]
    )
    monkeypatch.chdir(project)

    # Propose: shape-checked, stored inert, digest reported — nothing opened.
    result = authoring.propose_sources(proposal, project=project)
    assert result["sources"][0]["path"] == str(parquet)  # the precise location
    digest = result["digest"]
    assert len(digest) == 64
    assert connection_spy == []
    stored = yaml.safe_load(
        (project / "staging" / "authoring" / "source-proposal.yaml").read_text(encoding="utf-8")
    )
    assert stored["digest"] == digest
    assert stored["sources"] == [{"name": "events", "type": "parquet", "path": str(parquet)}]

    # Before approval the project registry still holds no sources: the only
    # profile path there is refuses to open anything.
    with pytest.raises(ValueError, match="no 'sources:' entries"):
        ariadne.profiler.profile(sources_path=project / "ariadne.yaml")
    assert connection_spy == []  # the proposed parquet was never handed to DuckDB

    # A wrong digest approves nothing.
    with pytest.raises(ValueError, match="[Dd]igest"):
        authoring.approve_sources("0" * 64, project=project)
    registry_doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert "sources" not in registry_doc  # untouched
    assert connection_spy == []

    # The matching digest installs exactly the approved entries.
    installed = authoring.approve_sources(digest, project=project)
    assert installed["sources"] == [{"name": "events", "type": "parquet", "path": str(parquet)}]
    registry_doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert registry_doc["retention_days"] == 90  # unrelated config preserved
    assert registry_doc["sources"] == [
        {"name": "events", "type": "parquet", "path": str(parquet)}
    ]

    # Only now does the source profile — through the same shared connection.
    profile = ariadne.profiler.profile(sources_path=project / "ariadne.yaml")
    assert connection_spy == [[str(parquet)]]  # the approved path, once
    (source,) = profile["sources"]
    assert source["name"] == "events"
    assert source["tables"]["events"]["row_count"] == 3


def test_stale_digest_after_re_proposal_is_refused(tmp_path, connection_spy):
    """A re-proposed (changed) pending proposal invalidates the earlier digest:
    the operator's approval binds the exact content, not the slot."""
    project = scaffold_project(tmp_path)
    first = write_parquet(tmp_path / "a.parquet")
    second = write_parquet(tmp_path / "b.parquet")
    stale = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(first)}]),
        project=project,
    )["digest"]
    current = authoring.propose_sources(
        write_proposal(
            tmp_path,
            [{"name": "events", "type": "parquet", "path": str(second)}],
            name="proposed-2.yaml",
        ),
        project=project,
    )["digest"]
    assert stale != current
    with pytest.raises(ValueError, match="[Dd]igest"):
        authoring.approve_sources(stale, project=project)
    assert "sources" not in yaml.safe_load(
        (project / "ariadne.yaml").read_text(encoding="utf-8")
    )
    assert connection_spy == []


def test_credential_shaped_proposal_is_rejected_inertly(tmp_path, connection_spy):
    """The registry's ADR-0010 credential rules apply verbatim to proposals:
    an inline connection string never becomes a pending proposal."""
    project = scaffold_project(tmp_path)
    proposal = write_proposal(
        tmp_path,
        [{"name": "pg", "type": "postgres", "connection": "postgresql://u:p@h/db"}],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        authoring.propose_sources(proposal, project=project)
    assert not (project / "staging" / "authoring" / "source-proposal.yaml").exists()
    assert connection_spy == []


def test_relative_proposal_paths_bind_to_the_project_registry(tmp_path, connection_spy):
    """A relative path in a proposal means the same thing before and after
    approval: relative to the project's ariadne.yaml directory, never to the
    intake file's directory — the displayed location is the precise one the
    operator approves and the profiler opens (spec rev2 §1)."""
    intake = tmp_path / "intake"
    intake.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    scaffold_project(project)
    parquet = write_parquet(project / "data" / "events.parquet")
    write_parquet(intake / "data" / "events.parquet")  # same-named decoy under intake/
    proposal = write_proposal(
        intake, [{"name": "events", "type": "parquet", "path": "data/events.parquet"}]
    )
    result = authoring.propose_sources(proposal, project=project)
    assert result["sources"][0]["path"] == str(parquet)  # project-relative, not intake-relative
    stored = yaml.safe_load(
        (project / "staging" / "authoring" / "source-proposal.yaml").read_text(encoding="utf-8")
    )
    assert stored["sources"][0]["path"] == str(parquet)

    authoring.approve_sources(result["digest"], project=project)
    registry_doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert registry_doc["sources"][0]["path"] == str(parquet)
    profile = ariadne.profiler.profile(sources_path=project / "ariadne.yaml")
    assert connection_spy == [[str(parquet)]]  # the approved dataset, not the intake decoy
    assert profile["sources"][0]["tables"]["events"]["row_count"] == 3


def test_credentialed_url_proposal_is_rejected_inertly(tmp_path, connection_spy):
    """A URL with userinfo (https://user:password@...) is an inline credential
    (spec rev2 §1, ADR-0010): it never becomes a pending proposal."""
    project = scaffold_project(tmp_path)
    proposal = write_proposal(
        tmp_path,
        [
            {
                "name": "cdn",
                "type": "parquet",
                "path": "https://ro:s3cret@cdn.example.com/events.parquet",
            }
        ],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        authoring.propose_sources(proposal, project=project)
    assert not (project / "staging" / "authoring" / "source-proposal.yaml").exists()
    assert connection_spy == []


def test_approval_never_overwrites_existing_sources(tmp_path, connection_spy):
    """Installing a name that already exists in ariadne.yaml fails whole —
    existing registry entries and unrelated config are never overwritten."""
    project = tmp_path
    parquet = write_parquet(tmp_path / "events.parquet")
    (project / "ariadne.yaml").write_text(
        yaml.safe_dump(
            {
                "retention_days": 30,
                "sources": [{"name": "events", "type": "parquet", "path": "keep.parquet"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    with pytest.raises(ValueError, match="already exist"):
        authoring.approve_sources(digest, project=project)
    doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert doc == {
        "retention_days": 30,
        "sources": [{"name": "events", "type": "parquet", "path": "keep.parquet"}],
    }
    assert connection_spy == []


def test_approval_without_a_registry_fails_before_writing(tmp_path):
    """A project without ariadne.yaml cannot be approved into: the failure is
    actionable and writes nothing."""
    project = tmp_path
    digest = authoring.propose_sources(
        write_proposal(
            tmp_path, [{"name": "events", "type": "parquet", "path": "data/events.parquet"}]
        ),
        project=project,
    )["digest"]
    with pytest.raises(ValueError, match="ariadne.yaml"):
        authoring.approve_sources(digest, project=project)
    assert not (project / "ariadne.yaml").exists()


def test_approval_survives_an_edited_stored_proposal(tmp_path):
    """The stored proposal lives in agent-writable staging: approval re-derives
    the digest from the stored content, so a hand-edited file never installs
    under the operator's digest."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "a.parquet")
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    stored = project / "staging" / "authoring" / "source-proposal.yaml"
    doc = yaml.safe_load(stored.read_text(encoding="utf-8"))
    doc["sources"][0]["path"] = str(tmp_path / "sneaky.parquet")
    stored.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="[Dd]igest"):
        authoring.approve_sources(digest, project=project)
    assert "sources" not in yaml.safe_load(
        (project / "ariadne.yaml").read_text(encoding="utf-8")
    )


# ------------------------------------------------------------------- CLI


def test_cli_propose_then_wrong_digest_then_approval(tmp_path, capsys, monkeypatch):
    """The console-script seam: propose-sources emits one JSON value with the
    digest and precise locations; approve-sources with the wrong digest writes
    one JSON error object to stderr and exits 1 without touching the registry."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    proposal = write_proposal(
        tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]
    )
    assert (
        authoring_cli(["propose-sources", "--file", str(proposal), "--project", str(project)])
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["digest"] and out["sources"] == [
        {"name": "events", "type": "parquet", "path": str(parquet)}
    ]
    assert authoring_cli(["approve-sources", "--digest", "0" * 64, "--project", str(project)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err)["error"]["type"] == "ValueError"
    assert "sources" not in yaml.safe_load(
        (project / "ariadne.yaml").read_text(encoding="utf-8")
    )
    assert (
        authoring_cli(["approve-sources", "--digest", out["digest"], "--project", str(project)])
        == 0
    )
    installed = json.loads(capsys.readouterr().out)
    assert installed["sources"][0]["name"] == "events"


def test_cli_malformed_invocation_writes_one_json_error(tmp_path, capsys):
    """A malformed invocation (absent --digest) keeps the written JSON
    contract: exactly one {"error": ...} object on stderr and exit 1, never
    argparse usage text (the ariadne CLI's UsageError pattern)."""
    project = scaffold_project(tmp_path)
    assert authoring_cli(["approve-sources", "--project", str(project)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["type"] == "UsageError"
    assert "--digest" in error["message"]
    assert "retention_days: 90" in (project / "ariadne.yaml").read_text(encoding="utf-8")


def test_pyproject_exposes_ariadne_authoring():
    """The console script the spec names is installed."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ariadne-authoring = "ariadne.authoring_cli:main"' in text
