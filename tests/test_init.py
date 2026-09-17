"""Packaging: the ariadne-init scaffolder and the console-script entry points.

Scaffolding covers INPUTS only (seed notes, .env.example, .mcp.json, .gitignore,
empty data/) — the served layers are author+promote outputs and must never be
pre-seeded. Entry points assert the editable install registered all five
console scripts and that each import target resolves.
"""

import json
from importlib.metadata import entry_points

from ariadne.init import main

CONSOLE_SCRIPTS = (
    "ariadne-author",
    "ariadne-validate",
    "ariadne-serve",
    "ariadne-promote",
    "ariadne-init",
)

GITIGNORE_LINES = (
    "data/*.db",
    "staging/",
    "context_layer/",
    "semantic_layer/",
    ".env",
    "__pycache__/",
    ".venv/",
)


def test_scaffold_creates_expected_inputs(tmp_path):
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    for rel in ("data/seed_notes.md", ".env.example", ".mcp.json", ".gitignore"):
        assert (target / rel).is_file(), rel
    assert (target / "data").is_dir()

    notes = (target / "data" / "seed_notes.md").read_text(encoding="utf-8")
    assert "TODO" in notes  # the placeholder the human fills in
    assert "revenue" in notes  # a human-voice example rule, not schema documentation

    env = (target / ".env.example").read_text(encoding="utf-8")
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        assert var in env, var

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))  # parses as JSON
    server = mcp["mcpServers"]["ariadne"]
    assert server["command"] == "ariadne-serve"
    assert server["args"] == [
        "--db",
        "data/YOURDB.db",
        "--semantic",
        "semantic_layer",
        "--context",
        "context_layer",
    ]

    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in gitignore, line


def test_second_run_is_idempotent(tmp_path, capsys):
    target = tmp_path / "proj"
    main([str(target)])
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}

    assert main([str(target)]) == 0
    out = capsys.readouterr().out
    after = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert before == after  # byte-identical tree: nothing rewritten
    skipped = [line for line in out.splitlines() if "skipped (exists)" in line]
    assert len(skipped) == 4  # every input file reported skipped, none rewritten


def test_existing_gitignore_is_not_overwritten(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    assert main([str(target)]) == 0
    assert (target / ".gitignore").read_text(encoding="utf-8") == "*.tmp\n"


def test_refuses_ariadne_checkout_unless_force(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text('[project]\nname = "ariadne"\n', encoding="utf-8")
    assert main([str(target)]) == 1  # refuses: this looks like the ariadne repo
    assert not (target / ".mcp.json").exists()  # nothing was written
    assert main([str(target), "--force"]) == 0  # explicit override scaffolds
    assert (target / ".mcp.json").is_file()


def test_refuses_ariadne_project_with_quirky_toml_formatting(tmp_path):
    # Detected by parsing, not substring matching: single quotes, odd whitespace.
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        "# a comment\n[project]   \n  name = 'ariadne'  # trailing\n",
        encoding="utf-8",
    )
    assert main([str(target)]) == 1
    assert not (target / ".mcp.json").exists()


def test_non_ariadne_pyproject_scaffolds_normally(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")
    assert main([str(target)]) == 0
    assert (target / ".mcp.json").is_file()


def test_refuses_unparsable_pyproject_unless_force(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text("[project\nname = ", encoding="utf-8")
    assert main([str(target)]) == 1  # ambiguous project: refuse
    assert "not valid TOML" in capsys.readouterr().err
    assert not (target / ".mcp.json").exists()
    assert main([str(target), "--force"]) == 0  # explicit override scaffolds


def test_refuses_symlinked_data_dir(tmp_path):
    # data -> outside TARGET: scaffold must refuse, never write through the link.
    target = tmp_path / "proj"
    outside = tmp_path / "outside"
    outside.mkdir()
    target.mkdir()
    (target / "data").symlink_to(outside, target_is_directory=True)
    assert main([str(target)]) == 1
    assert not (outside / "seed_notes.md").exists()  # nothing landed outside TARGET
    assert not (target / ".env.example").exists()  # and nothing was scaffolded at all


def test_refuses_dangling_env_example_symlink(tmp_path):
    # Dangling link: exists() is False, so the old code would write through it.
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".env.example").symlink_to(tmp_path / "nope.txt")
    assert main([str(target)]) == 1
    assert not (tmp_path / "nope.txt").exists()


def test_console_scripts_registered():
    scripts = {ep.name: ep for ep in entry_points(group="console_scripts")}
    for name in CONSOLE_SCRIPTS:
        assert name in scripts, f"missing console script: {name}"
        scripts[name].load()  # the module:function target resolves
