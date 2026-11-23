"""Fresh project scaffolding through the native knowledge path (spec0035 §2,
plan 0035 C1): ``ariadne-init`` creates one Lumio Knowledge Base under
``knowledge/`` through the SDK's public confirmed empty-setup contract plus
the Core input files. The retired ``context_layer/`` layout is not asserted:
an old standalone project refuses with fresh-setup guidance and nothing is
written; an existing managed KB is never reinitialized. MCP remains opt-in
and project-bound; existing user files are never overwritten.
"""

import json
import os
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]
import yaml

from ariadne import init


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


CONSOLE_SCRIPTS = ("ariadne",)  # spec 0040 §3.1.1: ONE console script

GITIGNORE_LINES = (
    "data/*",
    "!data/seed_notes.md",
    ".env",
    "__pycache__/",
    ".venv/",
    ".ariadne/",
)


def git(cwd: Path, *argv: str) -> None:
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"


def scaffold(target: Path) -> int:
    """The REAL ``ariadne init`` path (``init.init_project``): 0 on success, 1 with the
    refusal on stderr (init raises ValueError before any write)."""
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        git(target, "init", "-q")
    git(target, "config", "user.name", "Ariadne Tests")
    git(target, "config", "user.email", "tests@ariadne.local")
    try:
        init.init_project(target, assume_yes=True)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def test_scaffold_creates_native_kb_and_expected_inputs(tmp_path):
    """The fresh setup creates a valid unadmitted knowledge/ KB (SDK empty
    setup: Control File + Source Reference Manifest bound to the explicit
    namespace) plus the Core input files; .mcp.json stays opt-in."""
    target = tmp_path / "proj"
    target.mkdir()
    assert scaffold(target) == 0
    for rel in (
        "knowledge/lumio.yaml",
        "knowledge/.lumio-authoring.yaml",
        "data/seed_notes.md",
        "ariadne.yaml",
        "AGENTS.md",
        ".env.example",
        ".gitignore",
    ):
        assert (target / rel).is_file(), rel
    assert not (target / ".mcp.json").exists()  # default omits MCP config
    assert (target / "data").is_dir()
    assert not (target / "context_layer").exists()  # the retired layout is gone
    # the profile stays machine-local: outside the repository, never tracked
    from ariadne import profile_pair

    settings = profile_pair.load(target)
    profile = Path(settings["lumio_profile"])
    assert profile.is_file() and target not in profile.parents
    declaration = json.loads(profile.read_text(encoding="utf-8"))
    NAMESPACE = declaration["namespace"]
    assert NAMESPACE.startswith("urn:uuid:")
    assert declaration["retention"] == "required"

    # the KB the SDK created validates and carries Core's declared vocabulary
    from lumio_wiki import load_knowledge_base
    from lumio_wiki.source_references import (
        load_source_reference_manifest,
    )

    kb, report = load_knowledge_base(target / "knowledge")
    assert report.is_valid, report
    control = yaml.safe_load((target / "knowledge" / "lumio.yaml").read_text(encoding="utf-8"))
    declared = set(control["ontology"]["entity_types"])
    assert {"metric", "policy", "reference", "dataset", "table", "computation"} <= declared
    # the public extension seam appends new categories as bare names (no
    # description — a reviewing Maintainer fills that in): both forms are
    # valid Control File content
    categories = {
        entry["name"] if isinstance(entry, dict) else entry for entry in control["categories"]
    }
    # finalize writes knowledge/computations/<metric>.md for the first governed metric
    assert {"metrics", "policies", "computations"} <= categories
    manifest = load_source_reference_manifest(target / "knowledge")  # the KB root
    assert manifest is not None
    assert manifest.namespace == NAMESPACE and manifest.sources == {}  # unadmitted

    notes = (target / "data" / "seed_notes.md").read_text(encoding="utf-8")
    assert "TODO" in notes  # the placeholder the human fills in
    assert "revenue" in notes  # a human-voice example rule, not schema documentation

    env = (target / ".env.example").read_text(encoding="utf-8")
    assert "process environment" in env
    assert "Never commit credentials" in env

    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in gitignore, line


def test_scaffold_records_the_kb_path_for_the_journey(tmp_path):
    """The SDK apply writes the guarded .env journey settings (gitignored)."""
    target = tmp_path / "proj"
    target.mkdir()
    assert scaffold(target) == 0
    env = (target / ".env").read_text(encoding="utf-8")
    assert f"LUMIO_KB_PATH={target / 'knowledge'}" in env


def test_agents_md_is_pointer_page_not_workflow(tmp_path):
    """AGENTS.md is a facts/skill pointer with the Git Admission boundary and
    the native knowledge layout."""
    target = tmp_path / "proj"
    target.mkdir()
    assert scaffold(target) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "Load the ariadne skill (`ariadne skill install` if absent)" in agents
    assert "TODO" in agents  # project facts the owner fills in
    assert "`knowledge/`" in agents and "`.ariadne/`" in agents
    assert "context_layer" not in agents  # the retired layout is never advertised
    assert "Admission gate" in agents and "sources first" in agents
    assert "human-approved Git revision" in agents  # governed = the admitted snapshot
    assert "profile" not in agents.lower()  # the loop prose lives in the skill


def test_agents_md_names_the_one_cli_skill_command(tmp_path):
    """Spec 0040 §3.1: the one `ariadne` CLI — no generated input may reference the removed
    `ariadne-skill` executable."""
    target = tmp_path / "proj"
    target.mkdir()
    assert scaffold(target) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "ariadne skill install" in agents
    assert "ariadne-skill" not in agents


def test_git_pointer_page_separates_source_permission_and_admission(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    assert scaffold(target) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    normalized = " ".join(agents.split())  # line-wrapped prose compares normalized
    assert (
        "only the human runs `ariadne approve` (sources first, then the calculation)" in normalized
    )
    assert "`ariadne draft edit`" in agents
    assert "Original documents stay outside the authored artifact snapshot" in normalized
    assert "staging/" not in agents and "ariadne-promote" not in agents


def test_existing_operator_files_and_symlinked_destinations_are_preserved(tmp_path, capsys):
    """F1: setup never overwrites existing operator AGENTS.md/.env content and
    never writes through a symlinked callback destination — the no-overwrite
    contract covers the SDK apply callbacks exactly like the plain scaffold
    files; nothing is written at all when an occupied destination refuses."""
    target = tmp_path / "proj"
    target.mkdir()
    (target / "AGENTS.md").write_text("# my project facts\n", encoding="utf-8")
    (target / ".env").write_text("MY_SETTING=keep-me\n", encoding="utf-8")
    assert scaffold(target) == 1
    err = capsys.readouterr().err
    assert "never overwrites operator files" in err
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# my project facts\n"
    assert (target / ".env").read_text(encoding="utf-8") == "MY_SETTING=keep-me\n"
    assert not (target / "knowledge").exists()  # nothing was written

    # a symlinked callback destination (dangling included) is refused before
    # any write; the link target is never created or followed
    linked = tmp_path / "proj2"
    linked.mkdir()
    (linked / "AGENTS.md").symlink_to(tmp_path / "outside-agents.md")
    assert scaffold(linked) == 1
    assert not (tmp_path / "outside-agents.md").exists()
    assert not (linked / "knowledge").exists()


def test_scaffold_refuses_a_retired_context_layer_project(tmp_path, capsys):
    """AC10: opening/scaffolding an unsupported legacy project refuses with
    fresh-setup guidance and does not alter its files — never a reset."""
    target = tmp_path / "legacy"
    (target / "context_layer" / "metrics").mkdir(parents=True)
    (target / "context_layer" / "metrics" / "old.md").write_text(
        "---\ntype: metric\ntitle: Old\n---\n\n# Old\n", encoding="utf-8"
    )
    git(target, "init", "-q")
    git(target, "config", "user.name", "Ariadne Tests")
    git(target, "config", "user.email", "tests@ariadne.local")
    result = scaffold(target)
    assert result == 1
    err = capsys.readouterr().err
    assert "retired standalone Context layout" in err
    assert "Nothing was" in err  # refuses with guidance; nothing written
    assert (
        (target / "context_layer" / "metrics" / "old.md")
        .read_text(encoding="utf-8")
        .startswith("---")
    )  # untouched
    assert not (target / "knowledge").exists()  # never converted


def test_a_differing_gitignore_refuses_and_is_never_overwritten(tmp_path, capsys):
    """Finding 5 (spec 0040 §3.2.4): a differing target file refuses before any write."""
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    assert scaffold(target) == 1
    assert ".gitignore" in capsys.readouterr().err
    assert (target / ".gitignore").read_text(encoding="utf-8") == "*.tmp\n"
    assert not (target / "knowledge").exists()


def test_git_scaffold_tracks_the_kb_and_ignores_state_and_inputs(tmp_path):
    """A fresh scaffold tracks the native KB and ignores private inputs/state."""
    target = tmp_path / "proj"
    target.mkdir()
    assert scaffold(target) == 0
    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in gitignore, line
    assert "context_layer" not in gitignore
    tracked = git_capture(target, "ls-files").splitlines()  # init committed its own files
    assert "knowledge/lumio.yaml" in tracked
    assert "knowledge/.lumio-authoring.yaml" in tracked
    assert "ariadne.yaml" in tracked and "AGENTS.md" in tracked
    # the journey env stays untracked (line-exact: .env.example is tracked)
    assert ".env" not in tracked
    assert not (target / "context_layer").exists()


def git_capture(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


def test_git_scaffold_refuses_differing_targets_and_keeps_unrelated_files(tmp_path, capsys):
    """Scaffolding never overwrites existing user files: a differing init target (here the
    ignore rules and seed notes) refuses and is named; an unrelated file is untouched."""
    target = tmp_path / "existing"
    (target / "data").mkdir(parents=True)
    (target / ".gitignore").write_text("*.tmp\ncontext_layer/\nsemantic_layer/\n", encoding="utf-8")
    (target / "data" / "seed_notes.md").write_text("# my notes\n", encoding="utf-8")
    (target / "unrelated.txt").write_text("keep\n", encoding="utf-8")
    assert scaffold(target) == 1
    err = capsys.readouterr().err
    assert "data/seed_notes.md" in err or ".gitignore" in err
    assert (target / "data" / "seed_notes.md").read_text(encoding="utf-8") == "# my notes\n"
    assert (target / "unrelated.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (target / ".mcp.json").exists()  # still opt-in only


def test_git_scaffold_ignores_supported_input_locations_but_keeps_seed_notes(tmp_path):
    """The Git-only ignore template covers supported private INPUT locations
    (databases, parquet/csv/json/delta datasets under data/, and documents
    under data/docs/), so ordinary ``git add`` never picks up local inputs —
    while ``data/seed_notes.md`` stays trackable."""
    target = tmp_path / "proj"
    assert scaffold(target) == 0

    git(target, "config", "user.name", "Ariadne Tests")
    git(target, "config", "user.email", "tests@ariadne.local")
    (target / "data" / "events.parquet").write_bytes(b"PAR1\n")
    (target / "data" / "lake").mkdir()
    (target / "data" / "lake" / "part-0.parquet").write_bytes(b"PAR1\n")
    (target / "data" / "docs").mkdir()  # operator-placed inputs (spec 0027 §5)
    (target / "data" / "docs" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (target / "data" / "demo.db").write_bytes(b"sqlite bytes\n")

    git(target, "add", "-A")  # ordinary staging: local inputs never ride along
    staged = git_capture(target, "status", "--porcelain")
    assert "events.parquet" not in staged
    assert "part-0.parquet" not in staged
    assert "docs/notes.md" not in staged
    assert "demo.db" not in staged

    assert "data/seed_notes.md" in git_capture(target, "ls-files").splitlines()  # trackable


def test_refuses_ariadne_checkout_unless_force(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text('[project]\nname = "ariadne"\n', encoding="utf-8")
    assert scaffold(target) == 1  # refuses: this looks like the ariadne repo
    assert not (target / ".env.example").exists()  # nothing was written


def test_refuses_ariadne_project_with_quirky_toml_formatting(tmp_path):
    # Detected by parsing, not substring matching: single quotes, odd whitespace.
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        "# a comment\n[project]   \n  name = 'ariadne'  # trailing\n",
        encoding="utf-8",
    )
    assert scaffold(target) == 1
    assert not (target / ".env.example").exists()


def test_non_ariadne_pyproject_scaffolds_normally(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")
    assert scaffold(target) == 0
    assert (target / ".env.example").is_file()


def test_refuses_unparsable_pyproject_unless_force(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text("[project\nname = ", encoding="utf-8")
    assert scaffold(target) == 1  # ambiguous project: refuse
    assert "not valid TOML" in capsys.readouterr().err
    assert not (target / ".env.example").exists()


def test_refuses_symlinked_data_dir(tmp_path):
    # data -> outside TARGET: scaffold must refuse, never write through the link.
    target = tmp_path / "proj"
    outside = tmp_path / "outside"
    outside.mkdir()
    target.mkdir()
    (target / "data").symlink_to(outside, target_is_directory=True)
    assert scaffold(target) == 1
    assert not (outside / "seed_notes.md").exists()  # nothing landed outside TARGET
    assert not (target / ".env.example").exists()  # and nothing was scaffolded at all


def test_refuses_dangling_env_example_symlink(tmp_path):
    # Dangling link: exists() is False, so a naive writer would write through it.
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".env.example").symlink_to(tmp_path / "nope.txt")
    assert scaffold(target) == 1
    assert not (tmp_path / "nope.txt").exists()


def test_console_scripts_registered():
    scripts = {
        ep.name: ep
        for ep in entry_points(group="console_scripts")
        if ep.value.startswith("ariadne.")
    }
    assert set(scripts) == set(CONSOLE_SCRIPTS)  # exactly one; no removed executable remains
    scripts["ariadne"].load()  # the module:function target resolves
