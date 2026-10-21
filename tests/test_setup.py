"""Git-only setup CLI checks with synthetic projects and no source access.
The wheel walkthrough remains a separately bounded packaging check.
"""

import hashlib
import io
import json
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

from ariadne import admission, authoring, authoring_sources, init, proposals, skill
from ariadne.authoring import AuthoringProject
from ariadne.cli import main as cli


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("setup invoked a human-only operation or network/source access")

    for module, names in (
        (authoring_sources, ("approve_sources",)),
        (authoring.AuthoringProject, ("approve_sources",)),
        (admission, ("admit_revision", "reconcile")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    from ariadne import execution, query, sources

    monkeypatch.setattr(query.QueryRuntime, "__init__", forbidden)
    monkeypatch.setattr(sources, "build_connection", forbidden)
    monkeypatch.setattr(execution.DuckDBExecution, "__init__", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)


def run_setup(project, answers="", *flags, tty=True):
    stdin = Terminal(answers) if tty else io.StringIO(answers)
    with patch.object(sys.stdout, "isatty", return_value=True):
        return cli(["setup", "--project", str(project), *flags], stdin=stdin)


def prepare_git(project, identity=True):
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    if identity:
        for key, value in (("user.name", "Operator"), ("user.email", "operator@example.test")):
            subprocess.run(["git", "-C", str(project), "config", key, value], check=True)


def records(project):
    return [json.loads(p.read_text()) for p in (project / ".ariadne/proposals").glob("*.json")]


def test_new_managed_scaffold_reports_gates_without_git_mutation(tmp_path, capsys, monkeypatch):
    project = tmp_path / "new"
    real_git = proposals._git
    commands = []

    def git(argv, *args, **kwargs):
        commands.append(argv)
        assert argv[0] != "init"
        assert argv[0] != "config" or argv[1] == "--get"
        return real_git(argv, *args, **kwargs)

    monkeypatch.setattr(proposals, "_git", git)
    assert run_setup(project, "", "--no-input") == 0
    output = capsys.readouterr().out
    assert "git_managed" in output and "Ready: no" in output
    assert "admission:" in output  # the diagnostic status block names the gate state
    assert "Human gates remain" in output and "Git Review Admission" in output
    assert "git init" in output and "config user.name" in output and "config user.email" in output
    assert ".ariadne/" in (project / ".gitignore").read_text()
    assert not (project / ".git").exists() and not records(project)
    assert commands


@pytest.mark.parametrize("kind", ["no_git", "no_identity", "parent_repo"])
def test_missing_git_prerequisites_pause_declarations(tmp_path, capsys, monkeypatch, kind):
    project = tmp_path / "new"
    if kind == "no_git":
        from ariadne import status

        monkeypatch.setattr(status, "_git_available", lambda: False)
    elif kind == "parent_repo":
        prepare_git(tmp_path)
    else:
        prepare_git(project, identity=False)
    assert run_setup(project, "unused\n") == 0
    assert "Proposal preparation paused" in capsys.readouterr().out
    assert not records(project)


def test_managed_typed_declaration_exact_handoff_and_idempotent_resume(tmp_path, capsys):
    project = tmp_path / "managed"
    init.main([str(project)])
    (project / "data/events.parquet").write_bytes(b"not opened or parsed")
    prepare_git(project)
    original = (project / "ariadne.yaml").read_bytes()
    capsys.readouterr()
    assert run_setup(project, "accept\n\nyes\n") == 0
    output = capsys.readouterr().out
    (record,) = records(project)
    revision = record["candidate_revision"]
    identities = [
        {
            "name": "events",
            "type": "parquet",
            "read_only": True,
            "path": str(project / "data/events.parquet"),
        }
    ]
    digest = hashlib.sha256(
        json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected = shlex.join(
        [
            "ariadne-authoring",
            "approve-sources",
            "--project",
            str(project),
            "--proposal",
            record["id"],
            "--revision",
            revision,
            "--source-digest",
            digest,
        ]
    )
    assert expected in output
    assert "NOT source approval" in output and "Source approval pending" in output
    assert "Resolved source digest: " + digest in output
    assert (project / "ariadne.yaml").read_bytes() == original
    assert not (project / ".ariadne/source-approvals.json").exists()
    assert run_setup(project, "accept\n\nyes\n") == 0
    assert records(project) == [record]  # same proposal and candidate, no replacement commit
    candidate = subprocess.check_output(
        ["git", "show", f"{revision}:ariadne.yaml"], cwd=project, text=True
    )
    assert yaml.safe_load(candidate)["sources"] == [
        {"name": "events", "type": "parquet", "path": "data/events.parquet"}
    ]
    assert "identical declaration already present" in capsys.readouterr().out


def test_conflicting_identity_never_overwrites_or_replaces_pending_proposal(tmp_path, capsys):
    project = tmp_path / "managed"
    init.main([str(project)])
    prepare_git(project)
    api = authoring.AuthoringProject(project)
    started = api.start_proposal()
    api.propose_sources(
        started["proposal"],
        started["candidate_revision"],
        [{"name": "events", "type": "csv", "path": "original.csv"}],
    )
    before = records(project)
    answer = '{"name":"events","type":"csv","path":"other.csv"}\n\nyes\n'
    assert run_setup(project, answer) == 1
    assert "conflicting source identity" in capsys.readouterr().err
    assert records(project) == before


def test_existing_registry_is_preserved_without_route_choice(tmp_path, capsys):
    project = tmp_path / "existing"
    project.mkdir()
    registry = b"# operator-owned registry\n"
    (project / "ariadne.yaml").write_bytes(registry)
    assert run_setup(project, "", "--no-input") == 0
    output = capsys.readouterr().out
    assert "git_managed" in output and "Route choice required" not in output
    assert (project / "ariadne.yaml").read_bytes() == registry
    assert "## Admission gate" in (project / "AGENTS.md").read_text()


@pytest.mark.parametrize(
    "target,relative",
    [
        ("pi", ".pi/skills/ariadne"),
        ("claude", ".claude/skills/ariadne"),
        ("hermes", ".hermes/skills/ariadne"),
        ("universal", None),
    ],
)
def test_real_target_wiring_inside_project_from_outside_cwd(tmp_path, capsys, target, relative):
    project = tmp_path / "project"
    caller = Path.cwd()
    assert run_setup(project, "", "--no-input", "--agents", "--agent", target) == 0
    installed = project / ".agents/skills/ariadne"
    assert skill._dir_hash(installed) == skill._dir_hash(skill.ASSETS)
    if relative:
        link = project / relative
        assert link.resolve() == installed
        assert skill._dir_hash(link) == skill._dir_hash(skill.ASSETS)
    else:
        assert "Universal-only" in capsys.readouterr().out
    for unselected in {".pi/skills/ariadne", ".claude/skills/ariadne", ".hermes/skills/ariadne"} - {
        relative
    }:
        assert not (project / unselected).exists()
    assert not (caller / ".agents").exists() and Path.cwd() == caller


def test_user_scope_requires_explicit_flag_and_target_selection(tmp_path, capsys):
    project = tmp_path / "project"
    assert run_setup(project, "", "--no-input", "--agents") == 0
    assert "Skill target selection required" in capsys.readouterr().out
    assert not (project / ".agents").exists()
    assert run_setup(project, "", "--no-input", "--agents", "--agent", "pi", "--scope", "user") == 0
    canonical = Path.home() / ".agents/skills/ariadne"
    assert (Path.home() / ".pi/agent/skills/ariadne").resolve() == canonical
    assert not (project / ".agents").exists()


@pytest.mark.parametrize("no_input,tty", [(True, True), (False, False)])
def test_noninteractive_detects_filenames_never_accepts_sources_or_runs_author(
    tmp_path, monkeypatch, capsys, no_input, tty
):
    project = tmp_path / "project"
    init.main([str(project)])
    prepare_git(project)
    for relative in (
        "data/a.db",
        "data/b.sqlite",
        "data/c.csv",
        "data/d.json",
        "data/e.parquet",
        "data/f.duckdb",
        ".hidden/h.csv",
        "venv/v.csv",
        ".venv/v.csv",
        "node_modules/n.csv",
        "staging/s.csv",
        ".ariadne/private/p.csv",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"secret source contents")
    real_open = Path.open

    def metadata_only(path, *args, **kwargs):
        if (
            path.suffix in (".db", ".sqlite", ".csv", ".parquet", ".duckdb")
            or path.name == "d.json"
        ):
            pytest.fail(f"source content opened: {path}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    capsys.readouterr()
    flags = ("--no-input",) if no_input else ()
    assert run_setup(project, "accept\nyes\n", *flags, tty=tty) == 0
    output = capsys.readouterr().out
    assert "Detected 6 file(s)" in output and "secret source contents" not in output
    # the inert .duckdb hint is typed from the FILENAME only, and the existing
    # .db/.sqlite hints keep their meanings (spec 0022 §5)
    assert '"path": "data/f.duckdb"' in output and '"type": "duckdb"' in output
    assert '"path": "data/a.db"' in output and '"type": "sqlite"' in output
    assert "Declarations skipped" in output and not records(project)


def test_postgres_uses_env_name_and_never_emits_or_stores_credential_value(
    tmp_path, capsys, monkeypatch
):
    project = tmp_path / "project"
    init.main([str(project)])
    prepare_git(project)
    secret = "postgresql://operator:secret-password@host/database"
    monkeypatch.setenv("ARIADNE_PG_DSN", secret)
    answers = '{"name":"warehouse","type":"postgres","connection_env":"ARIADNE_PG_DSN"}\n\nyes\n'
    assert run_setup(project, answers) == 0
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    (record,) = records(project)
    blob = subprocess.check_output(
        ["git", "show", f"{record['candidate_revision']}:ariadne.yaml"], cwd=project, text=True
    )
    assert "connection_env: ARIADNE_PG_DSN" in blob and secret not in blob


def test_inline_credential_refused_without_echo_or_declaration(tmp_path, capsys):
    project = tmp_path / "project"
    init.main([str(project)])
    prepare_git(project)
    secret = "postgresql://operator:secret-password@host/database"
    assert (
        run_setup(
            project,
            json.dumps({"name": "warehouse", "type": "postgres", "connection_env": secret}) + "\n",
        )
        == 1
    )
    output = capsys.readouterr()
    assert secret not in output.out + output.err and not records(project)


def test_rejected_confirmation_and_nonterminal_output_never_declare(tmp_path, capsys):
    project = tmp_path / "project"
    init.main([str(project)])
    prepare_git(project)
    (project / "data/events.csv").write_text("id\n1\n")
    assert run_setup(project, "accept\n\nno\n") == 0
    assert not records(project)
    with patch.object(sys.stdout, "isatty", return_value=False):
        assert cli(["setup", "--project", str(project)], stdin=Terminal("accept\n\nyes\n")) == 0
    assert not records(project)
    assert "Declarations skipped" in capsys.readouterr().out


def test_interrupted_intake_reports_completed_steps_and_still_installs_selected_skill(
    tmp_path, capsys
):
    project = tmp_path / "project"
    init.main([str(project)])
    prepare_git(project)
    (project / "data/events.csv").write_text("id\n1\n")
    assert run_setup(project, "accept\n", "--agents", "--agent", "pi") == 1
    output = capsys.readouterr()
    assert "completed scaffold/proposal steps remain" in output.err
    assert "Finish:" in output.out and "Ready: no" in output.out
    assert (project / ".pi/skills/ariadne").is_symlink() and not records(project)


def test_existing_proposal_operator_selection_reuses_only_chosen_id(tmp_path, capsys):
    project = tmp_path / "managed"
    init.main([str(project)])
    prepare_git(project)
    api = authoring.AuthoringProject(project)
    first, second = api.start_proposal(), api.start_proposal()
    answer = '{"name":"events","type":"csv","path":"events.csv"}\n\nyes\n'
    assert run_setup(project, answer + second["proposal"] + "\n") == 0
    entries = {r["id"]: r for r in records(project)}
    assert len(entries) == 2
    assert entries[first["proposal"]]["candidate_revision"] == first["candidate_revision"]
    assert entries[second["proposal"]]["candidate_revision"] != second["candidate_revision"]


def test_filename_scan_skips_links_reports_unreadable_metadata_and_is_bounded(
    tmp_path, capsys, monkeypatch
):
    import ariadne.setup as setup  # pyright: ignore[reportMissingImports] — new-module resolver drift

    project = tmp_path / "scan"
    project.mkdir()
    (project / "events.csv").write_text("secret content")
    (project / "linked.csv").symlink_to(project / "events.csv")
    (project / "blocked").mkdir()
    real_scan = os.scandir

    def scan(path):
        if Path(path).name == "blocked":
            raise PermissionError("metadata denied")
        return real_scan(path)

    monkeypatch.setattr(os, "scandir", scan)
    assert setup.detect_files(project) == [{"name": "events", "type": "csv", "path": "events.csv"}]
    assert "unreadable directory metadata" in capsys.readouterr().out
    monkeypatch.setattr(setup, "_SCAN_LIMIT", 1)
    setup.detect_files(project)
    assert "Detection bounded" in capsys.readouterr().out


def test_status_internal_skill_selection_preserves_default_and_scopes_steps(
    tmp_path, monkeypatch, capsys
):
    from ariadne import status
    from ariadne.cli import build_parser

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert skill.main(["install", "--scope", "user", "--agent", "hermes"]) == 0
    assert skill.main(["install", "--scope", "project", "--agent", "pi"]) == 0
    for canonical in (Path.home() / ".agents/skills/ariadne", project / ".agents/skills/ariadne"):
        (canonical / "SKILL.md").write_text("operator edit: drift\n")
    args = build_parser().parse_args(["status", "--project", str(project)])
    default = status.build_report(args)
    pairs = {(target["scope"], target["agent"]) for target in default["skill"]["targets"]}
    assert pairs == {
        ("user", None),
        ("project", None),
        ("user", "pi"),
        ("project", "pi"),
        ("user", "claude"),
        ("project", "claude"),
        ("user", "hermes"),
        ("project", "hermes"),
    }
    assert any("--scope user --agent hermes" in step for step in default["next_steps"])
    real_hash = skill._dir_hash

    def selected_hash(path):
        assert Path.home() not in path.parents  # scoped checks never hash unrelated user installs
        return real_hash(path)

    monkeypatch.setattr(skill, "_dir_hash", selected_hash)
    selected = status.build_report(args, skill_targets={("project", None), ("project", "pi")})
    assert {(t["scope"], t["agent"]) for t in selected["skill"]["targets"]} == {
        ("project", None),
        ("project", "pi"),
    }
    skill_steps = [step for step in selected["next_steps"] if "ariadne-skill install" in step]
    assert len(skill_steps) == 2 and all("--scope project" in step for step in skill_steps)
    assert any("--agent pi" in step for step in skill_steps)
    assert not any("hermes" in step or "claude" in step for step in selected["next_steps"])
    capsys.readouterr()
    assert run_setup(project, "", "--no-input", "--agents", "--agent", "pi") == 0
    output = capsys.readouterr().out
    assert "project/pi:" in output and "user/hermes:" not in output


def test_filename_detection_skips_custom_virtualenvs_without_opening_config_or_sources(
    tmp_path, monkeypatch
):
    import ariadne.setup as setup  # pyright: ignore[reportMissingImports] — new-module resolver drift

    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    (project / "data/events.csv").write_text("id\n1\n")
    virtualenvs = [project / "python-env", project / "data/custom-runtime"]
    for venv in virtualenvs:
        (venv / "lib/site-packages").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = fixture Python\n")
        (venv / "lib/site-packages/metadata.json").write_text('{"package":"not data"}')
    real_scan = os.scandir

    def metadata_only_scan(path):
        assert not any(Path(path) == venv or venv in Path(path).parents for venv in virtualenvs)
        return real_scan(path)

    def no_content(*args, **kwargs):
        pytest.fail("filename detection opened virtualenv config or source content")

    monkeypatch.setattr(os, "scandir", metadata_only_scan)
    monkeypatch.setattr(Path, "open", no_content)
    assert setup.detect_files(project) == [
        {"name": "events", "type": "csv", "path": "data/events.csv"}
    ]


def test_skill_and_release_docs_operator_rules_and_distribution():
    text = (skill.ASSETS / "SKILL.md").read_text()
    normalized = " ".join(text.split())  # line-wrapped prose compares normalized
    # setup stays operator-facing; agents pass the exact commands to the human
    assert "`ariadne setup` is operator-facing" in normalized
    assert "agents do not initialize/configure Git" in normalized
    assert "Pass exact operator commands and blockers to the human" in normalized
    assert "ariadne review" in text and "operator-only" in text
    for path in (".pi/skills/ariadne", ".claude/skills/ariadne", ".hermes/skills/ariadne"):
        assert path in text
    assert "universal-only" in text
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "0.6.0" in readme  # selected Core release; historical notes stay unchanged
    assert "Source development" in readme  # checkout entry point stays discoverable
    tutorial = (Path(__file__).parents[1] / "docs" / "tutorials" / "getting-started.md").read_text()
    for phrase in (
        "uv tool install ariadne-data",
        "ariadne setup",
        "--agent pi",
        "git config",
        "ariadne-admit",
        "get-metric",
    ):
        assert phrase in tutorial  # operator onboarding path moved to the tutorial
    how_to = (Path(__file__).parents[1] / "docs" / "how-to" / "git-authoring.md").read_text()
    assert "approve-sources" in how_to  # the human-only gate stays in the procedure guide
    cli = (Path(__file__).parents[1] / "docs" / "reference" / "cli.md").read_text()
    # hosts/adapters stay optional installs that change no governance gate
    # (the ariadne-agent conversational host is out of the Git-only Core docs)
    assert "Installing an adapter does not change the human governance gates" in cli
    explanation = (
        Path(__file__).parents[1] / "docs" / "explanations" / "how-ariadne-works.md"
    ).read_text()
    assert "independently attested" in explanation  # governed is not value-attested


# ------------------ spec 0025 (S1): setup understands existing profiles


def test_setup_declaration_references_an_existing_candidate_profile(tmp_path, capsys):
    """Spec 0025 §5: setup's inert declaration validation understands
    references to profiles ALREADY declared in the candidate registry — a
    ``storage:`` reference to an existing definition proposes cleanly (no
    wizard, no new credential tooling), and the approve handoff names the
    declaration digest exactly as before."""
    project = tmp_path / "managed"
    init.main([str(project)])
    (project / "data/events.parquet").write_bytes(b"not opened or parsed")
    prepare_git(project)
    api = AuthoringProject(project)
    started = api.start_proposal()
    revision = started["candidate_revision"]
    # the candidate already declares the profile (with its first source)
    api.propose_sources(
        started["proposal"],
        revision,
        [
            {
                "name": "orders",
                "type": "parquet",
                "storage": "local",
                "path": "s3://retail/orders/orders.parquet",
            }
        ],
        {
            "local": {
                "type": "s3",
                "access_key_id_env": "SETUP_S3_KEY_ID",
                "secret_access_key_env": "SETUP_S3_SECRET",
                "endpoint_url_env": "SETUP_S3_ENDPOINT",
                "scopes": ["s3://retail/"],
            }
        },
    )
    # a MANUAL setup declaration referencing the EXISTING profile validates
    # against the candidate's storages and proposes through the managed seam
    entry = json.dumps(
        {
            "name": "archive",
            "type": "parquet",
            "storage": "local",
            "path": "s3://retail/archive/a.parquet",
        }
    )
    capsys.readouterr()
    assert run_setup(project, f"skip\n{entry}\n\nyes\n") == 0
    output = capsys.readouterr().out
    assert "Source approval pending" in output
    assert "approve-sources" in output
    (record,) = records(project)
    candidate = subprocess.check_output(
        ["git", "show", f"{record['candidate_revision']}:ariadne.yaml"], cwd=project, text=True
    )
    doc = yaml.safe_load(candidate)
    assert doc["storages"]["local"]["access_key_id_env"] == "SETUP_S3_KEY_ID"
    assert {source["name"] for source in doc["sources"]} == {"orders", "archive"}
    assert all(source["storage"] == "local" for source in doc["sources"])
