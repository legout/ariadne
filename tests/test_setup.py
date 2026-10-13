"""Spec 0017 AC1–7: public CLI seams, real local repos, no network/provider.
AC8 additionally runs tests/setup_wheel_walkthrough.py against a fresh wheel venv.
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

from ariadne import admission, author, authoring, authoring_sources, init, proposals, skill
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
        (authoring, ("approve_sources",)),
        (authoring_sources, ("approve_sources",)),
        (authoring.AuthoringProject, ("approve_sources",)),
        (admission, ("admit_revision", "reconcile")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    from ariadne import execution, promote, query, sources

    monkeypatch.setattr(promote, "main", forbidden)
    monkeypatch.setattr(query.QueryRuntime, "__init__", forbidden)
    monkeypatch.setattr(sources, "build_connection", forbidden)
    monkeypatch.setattr(execution.DuckDBExecution, "__init__", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(author, "main", forbidden)


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
    assert "admission:" in output and "no admission recorded" in output
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
    init.main([str(project), "--git"])
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
    init.main([str(project), "--git"])
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


def test_existing_legacy_and_explicit_legacy_preserve_files_and_inert_pending_proposal(
    tmp_path, capsys
):
    project = tmp_path / "legacy"
    assert run_setup(project, "", "--legacy", "--no-input") == 0
    (project / "data/orders.csv").write_bytes(b"never read")
    (project / "data/seed_notes.md").write_text("Operator rules\n")
    original = (project / "ariadne.yaml").read_bytes()
    capsys.readouterr()
    assert run_setup(project, "accept\n\nyes\n") == 0
    output = capsys.readouterr().out
    assert "Scaffold/resume: legacy" in output
    assert "ariadne-authoring approve-sources --project" in output and "--digest" in output
    stored = project / authoring.PROPOSAL_REL
    proposal = stored.read_bytes()
    assert (project / "ariadne.yaml").read_bytes() == original
    assert (project / "data/seed_notes.md").read_text() == "Operator rules\n"
    assert not (project / ".git").exists() and "Authoring paused" not in output
    assert run_setup(project, "accept\n\nyes\n") == 0
    assert stored.read_bytes() == proposal  # does not replace the pending declaration


def test_ambiguous_scaffold_requires_operator_route_choice(tmp_path, capsys):
    project = tmp_path / "ambiguous"
    project.mkdir()
    (project / "ariadne.yaml").write_text("# operator scaffold\n")
    assert run_setup(project, "", "--no-input") == 0
    assert "Route choice required" in capsys.readouterr().out
    assert not (project / "AGENTS.md").exists()
    assert run_setup(project, "managed\n\n") == 0
    assert "## Admission gate" in (project / "AGENTS.md").read_text()


def test_managed_route_cannot_be_changed_by_legacy_flag(tmp_path, capsys):
    project = tmp_path / "managed"
    init.main([str(project), "--git"])
    before = (project / "AGENTS.md").read_bytes()
    assert run_setup(project, "", "--legacy", "--no-input") == 1
    assert "never migrates" in capsys.readouterr().err
    assert (project / "AGENTS.md").read_bytes() == before


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
    init.main([str(project), "--git"])
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
    init.main([str(project), "--git"])
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
    init.main([str(project), "--git"])
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


def test_only_explicit_legacy_authoring_run_has_disclosed_access(tmp_path, capsys, monkeypatch):
    project = tmp_path / "legacy"
    init.main([str(project)])
    (project / "ariadne.yaml").write_text(
        "sources:\n- name: events\n  type: csv\n  path: events.csv\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "not-printed")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    calls = []

    def delegated(argv):
        assert "network/data egress" in capsys.readouterr().out
        assert Path.cwd() == project
        calls.append(argv)
        return 0

    monkeypatch.setattr(author, "main", delegated)
    # manual source intake done (blank), then explicit selection of the existing author
    assert run_setup(project, "\nyes\n") == 0
    assert calls == [["--sources", "ariadne.yaml", "--notes", "data/seed_notes.md"]]


def test_rejected_confirmation_and_nonterminal_output_never_declare(tmp_path, capsys):
    project = tmp_path / "project"
    init.main([str(project), "--git"])
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
    init.main([str(project), "--git"])
    prepare_git(project)
    (project / "data/events.csv").write_text("id\n1\n")
    assert run_setup(project, "accept\n", "--agents", "--agent", "pi") == 1
    output = capsys.readouterr()
    assert "completed scaffold/proposal steps remain" in output.err
    assert "Finish:" in output.out and "Ready: no" in output.out
    assert (project / ".pi/skills/ariadne").is_symlink() and not records(project)


def test_noninteractive_legacy_resume_prints_exact_pending_approval_without_writes(
    tmp_path, capsys
):
    project = tmp_path / "legacy"
    init.main([str(project)])
    intake = tmp_path / "intake.yaml"
    intake.write_text("sources:\n- name: events\n  type: csv\n  path: events.csv\n")
    proposed = authoring.propose_sources(intake, project=project)
    stored = (project / authoring.PROPOSAL_REL).read_bytes()
    registry = (project / "ariadne.yaml").read_bytes()
    assert run_setup(project, "", "--no-input") == 0
    output = capsys.readouterr().out
    assert (
        shlex.join(
            [
                "ariadne-authoring",
                "approve-sources",
                "--project",
                str(project),
                "--digest",
                proposed["digest"],
            ]
        )
        in output
    )
    assert (project / authoring.PROPOSAL_REL).read_bytes() == stored
    assert (project / "ariadne.yaml").read_bytes() == registry


def test_existing_proposal_operator_selection_reuses_only_chosen_id(tmp_path, capsys):
    project = tmp_path / "managed"
    init.main([str(project), "--git"])
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


def test_managed_scaffold_route_survives_empty_staging_before_proposals(tmp_path, capsys):
    project = tmp_path / "managed"
    assert init.main([str(project), "--git"]) == 0
    assert not (project / ".ariadne").exists()
    (project / "staging").mkdir()
    originals = {
        name: (project / name).read_bytes() for name in ("AGENTS.md", ".gitignore", "ariadne.yaml")
    }
    capsys.readouterr()
    assert run_setup(project, "", "--no-input") == 0
    output = capsys.readouterr().out
    assert "Scaffold/resume: managed" in output and "git_managed" in output
    assert "Proposal preparation paused" in output and "git init" in output
    assert not (project / ".git").exists() and not records(project)
    assert {name: (project / name).read_bytes() for name in originals} == originals
    assert run_setup(project, "", "--legacy", "--no-input") == 1
    assert "never migrates" in capsys.readouterr().err


def test_completed_legacy_source_approval_allows_next_declaration_but_preserves_pending(
    tmp_path, capsys
):
    project = tmp_path / "legacy"
    assert init.main([str(project)]) == 0
    intake = tmp_path / "first.yaml"
    intake.write_text("sources:\n- name: first\n  type: csv\n  path: first.csv\n")
    first = authoring.propose_sources(intake, project=project)
    # The fixture's operator approves outside setup; setup's human-call guards remain active.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ariadne.authoring_cli",
            "approve-sources",
            "--project",
            str(project),
            "--digest",
            first["digest"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    registry = (project / "ariadne.yaml").read_bytes()
    stored = project / authoring.PROPOSAL_REL
    assert stored.exists()  # approval intentionally retains this completed proposal
    capsys.readouterr()
    second = '{"name":"second","type":"csv","path":"second.csv"}\n\nyes\n'
    assert run_setup(project, second) == 0
    output = capsys.readouterr().out
    pending = stored.read_bytes()
    assert yaml.safe_load(pending)["sources"] == [
        {"name": "second", "type": "csv", "path": str(project / "second.csv")}
    ]
    assert (project / "ariadne.yaml").read_bytes() == registry
    assert "Source approval pending" in output and "Authoring paused" in output
    assert run_setup(project, second) == 0
    assert stored.read_bytes() == pending  # identical pending entries are not duplicated
    third = '{"name":"third","type":"csv","path":"third.csv"}\n\nyes\n'
    assert run_setup(project, third) == 1
    assert "a source proposal is already pending" in capsys.readouterr().err
    assert stored.read_bytes() == pending and (project / "ariadne.yaml").read_bytes() == registry


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
    assert "ariadne setup --no-input" in text
    assert "never satisfy prompts" in text.lower()
    assert "ariadne review" in text and "operator-only" in text
    for path in (".pi/skills/ariadne", ".claude/skills/ariadne", ".hermes/skills/ariadne"):
        assert path in text
    assert "universal-only" in text
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    quickstart = readme.split("## Quickstart", 1)[1].split("### Harness-led", 1)[0]
    for phrase in (
        "uv tool install ariadne-data",
        "ariadne-agent",
        "0.2.0",
        "unreleased",
        "ariadne setup",
        "git config",
        "approve-sources",
        "ariadne-admit",
        "get-metric",
        "value-attested",
        "--agent pi",
        "Source development",
    ):
        assert phrase in quickstart
