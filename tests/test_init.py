"""Git-only project scaffolding and Core console-script entry points.

A fresh scaffold writes operator inputs, Git-ignore rules and an AGENTS.md
pointer; authored layers arrive through proposals and no staging tree is made.
MCP remains opt-in and project-bound. Existing user files are never overwritten.
"""

import json
from importlib.metadata import entry_points

from ariadne.init import main

CONSOLE_SCRIPTS = (
    "ariadne",
    "ariadne-ingest",
    "ariadne-validate",
    "ariadne-serve",
    "ariadne-analyst-mcp",
    "ariadne-authoring-mcp",
    "ariadne-init",
    "ariadne-skill",
    "ariadne-profiler",
    "ariadne-authoring",
    "ariadne-admit",
)

GITIGNORE_LINES = (
    "data/*",
    "!data/seed_notes.md",
    ".env",
    "__pycache__/",
    ".venv/",
    ".ariadne/",
)


def test_scaffold_creates_expected_inputs(tmp_path):
    """Default scaffold (spec §7): local-first — .mcp.json is NOT created."""
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    for rel in ("data/seed_notes.md", "ariadne.yaml", "AGENTS.md", ".env.example", ".gitignore"):
        assert (target / rel).is_file(), rel
    assert not (target / ".mcp.json").exists()  # default omits MCP config
    assert (target / "data").is_dir()

    notes = (target / "data" / "seed_notes.md").read_text(encoding="utf-8")
    assert "TODO" in notes  # the placeholder the human fills in
    assert "revenue" in notes  # a human-voice example rule, not schema documentation

    env = (target / ".env.example").read_text(encoding="utf-8")
    assert "Point ARIADNE_ENV at this file" in env
    assert "Never commit credentials" in env

    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in gitignore, line


def test_scaffold_with_mcp_creates_registry_aware_config(tmp_path):
    """--with-mcp (spec §7): the opt-in server is bound to this project."""
    target = tmp_path / "proj"
    assert main([str(target), "--with-mcp"]) == 0
    for rel in ("data/seed_notes.md", ".gitignore"):
        assert (target / rel).is_file(), rel
    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))  # parses as JSON
    server = mcp["mcpServers"]["ariadne"]
    assert server["command"] == "ariadne-serve"
    assert server["args"] == ["--project", "."]


def test_existing_mcp_json_is_never_removed_or_overwritten(tmp_path):
    """Spec §7: an existing .mcp.json survives the default run AND --with-mcp."""
    target = tmp_path / "proj"
    target.mkdir()
    user_config = '{"mcpServers": {"user": {"command": "keep-me"}}}\n'
    (target / ".mcp.json").write_text(user_config, encoding="utf-8")
    assert main([str(target)]) == 0  # default run: file not in the write set at all
    assert (target / ".mcp.json").read_text(encoding="utf-8") == user_config
    assert main([str(target), "--with-mcp"]) == 0  # opt-in still refuses to overwrite
    assert (target / ".mcp.json").read_text(encoding="utf-8") == user_config


def test_agents_md_is_pointer_page_not_workflow(tmp_path):
    """AGENTS.md is a facts/skill pointer with the Git Admission boundary."""
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "Load the ariadne skill (`ariadne-skill install` if absent)" in agents
    assert "TODO" in agents  # project facts the owner fills in
    assert "`context_layer/`" in agents and "`.ariadne/`" in agents
    assert "Admission gate" in agents and "source permission" in agents
    assert "human-admitted Git revision" in agents  # governed = the admitted snapshot
    assert "profile" not in agents.lower()  # the loop prose lives in the skill


def test_agents_md_names_the_real_skill_command(tmp_path):
    """The packaged CLI is ``ariadne-skill`` — no generated input may reference
    the absent ``ariadne skill`` command form (there is no umbrella CLI)."""
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "ariadne-skill install" in agents
    assert "ariadne skill install" not in agents


def test_layout_names_the_full_okf_bundle_sections(tmp_path):
    """K6 (issue #46, spec 0010 §3): the scaffolded layout table describes the
    context layer by its APPLICABLE sections (datasets, tables, references
    alongside policies/metrics/computations) — never the obsolete
    mandatory-category story."""
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "tables, references, policies, metrics, computations" in agents


def test_git_pointer_page_separates_source_permission_and_admission(tmp_path):
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    normalized = " ".join(agents.split())  # line-wrapped prose compares normalized
    assert "source permission and Admission remain separate human decisions" in normalized
    assert "`ariadne-authoring`" in agents
    assert "Original documents stay outside the authored artifact snapshot" in normalized
    assert "staging/" not in agents and "ariadne-promote" not in agents


def test_second_run_is_idempotent(tmp_path, capsys):
    target = tmp_path / "proj"
    main([str(target)])
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}

    assert main([str(target)]) == 0
    out = capsys.readouterr().out
    after = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert before == after  # byte-identical tree: nothing rewritten
    skipped = [line for line in out.splitlines() if "skipped (exists)" in line]
    assert len(skipped) == 5  # every default input file reported skipped, none rewritten

    # --with-mcp adds exactly the MCP config: first opt-in run creates it (5
    # skipped + 1 created), the next reports all 6 skipped
    assert main([str(target), "--with-mcp"]) == 0
    out = capsys.readouterr().out
    assert len([line for line in out.splitlines() if "skipped (exists)" in line]) == 5
    assert main([str(target), "--with-mcp"]) == 0
    out = capsys.readouterr().out
    skipped = [line for line in out.splitlines() if "skipped (exists)" in line]
    assert len(skipped) == 6
    assert (target / ".mcp.json").is_file()  # created once, then stable


def test_existing_gitignore_is_not_overwritten(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    assert main([str(target)]) == 0
    assert (target / ".gitignore").read_text(encoding="utf-8") == "*.tmp\n"


def test_git_scaffold_tracks_artifact_layers_and_ignores_state_and_inputs(tmp_path):
    """A fresh scaffold tracks authored layers and ignores private inputs/state."""
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in gitignore, line
    assert "context_layer" not in gitignore and "semantic_layer" not in gitignore
    for rel in ("data/seed_notes.md", "ariadne.yaml", "AGENTS.md", ".env.example"):
        assert (target / rel).is_file(), rel
    assert not (target / "context_layer").exists()
    assert not (target / "semantic_layer").exists()
    assert not (target / "staging").exists()
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "Admission gate" in agents and "`.ariadne/`" in agents
    assert "ariadne-promote" not in agents
    assert "profile" not in agents.lower()


def test_git_scaffold_keeps_existing_files_and_ignore_rules(tmp_path, capsys):
    """Scaffolding never overwrites existing user files or ignore rules."""
    target = tmp_path / "existing"
    target.mkdir()
    (target / ".gitignore").write_text("*.tmp\ncontext_layer/\nsemantic_layer/\n", encoding="utf-8")
    (target / "data").mkdir()
    (target / "data" / "seed_notes.md").write_text("# my notes\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("# my project\n", encoding="utf-8")
    assert main([str(target)]) == 0
    assert (target / ".gitignore").read_text(encoding="utf-8") == (
        "*.tmp\ncontext_layer/\nsemantic_layer/\n"
    )  # existing rules are NOT rewritten
    assert (target / "data" / "seed_notes.md").read_text(encoding="utf-8") == "# my notes\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# my project\n"
    assert not (target / ".mcp.json").exists()  # still opt-in only


def test_git_scaffold_ignores_supported_input_locations_but_keeps_seed_notes(tmp_path):
    """The Git-only ignore template covers supported private INPUT locations
    (databases, parquet/csv/json/delta datasets under data/, and
    documents under data/docs/), so ordinary ``git add`` never picks up local
    inputs — while ``data/seed_notes.md`` stays trackable (the artifact the
    allowlisted ``-f`` literal-pathspec seam commits)."""
    import subprocess

    target = tmp_path / "proj"
    assert main([str(target)]) == 0

    def git(*argv: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", *argv], cwd=target, capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
        return proc

    git("init", "-q")
    git("config", "user.name", "Ariadne Tests")
    git("config", "user.email", "tests@ariadne.local")
    (target / "data" / "events.parquet").write_bytes(b"PAR1\n")
    (target / "data" / "lake").mkdir()
    (target / "data" / "lake" / "part-0.parquet").write_bytes(b"PAR1\n")
    (target / "data" / "docs").mkdir()  # operator-placed inputs (spec 0027 §5)
    (target / "data" / "docs" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (target / "data" / "demo.db").write_bytes(b"sqlite bytes\n")

    git("add", "-A")  # ordinary staging: local inputs never ride along
    staged = git("status", "--porcelain").stdout
    assert "events.parquet" not in staged
    assert "part-0.parquet" not in staged
    assert "docs/notes.md" not in staged
    assert "demo.db" not in staged

    git("add", "--", "data/seed_notes.md")  # plainly trackable, -f unneeded
    staged = git("status", "--porcelain").stdout
    assert "data/seed_notes.md" in staged


def test_refuses_ariadne_checkout_unless_force(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text('[project]\nname = "ariadne"\n', encoding="utf-8")
    assert main([str(target)]) == 1  # refuses: this looks like the ariadne repo
    assert not (target / ".env.example").exists()  # nothing was written
    assert main([str(target), "--force"]) == 0  # explicit override scaffolds
    assert (target / ".env.example").is_file()


def test_refuses_ariadne_project_with_quirky_toml_formatting(tmp_path):
    # Detected by parsing, not substring matching: single quotes, odd whitespace.
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        "# a comment\n[project]   \n  name = 'ariadne'  # trailing\n",
        encoding="utf-8",
    )
    assert main([str(target)]) == 1
    assert not (target / ".env.example").exists()


def test_non_ariadne_pyproject_scaffolds_normally(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")
    assert main([str(target)]) == 0
    assert (target / ".env.example").is_file()


def test_refuses_unparsable_pyproject_unless_force(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text("[project\nname = ", encoding="utf-8")
    assert main([str(target)]) == 1  # ambiguous project: refuse
    assert "not valid TOML" in capsys.readouterr().err
    assert not (target / ".env.example").exists()
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
