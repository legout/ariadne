"""Packaging: the ariadne-init scaffolder and the console-script entry points.

Scaffolding covers INPUTS only (seed notes, AGENTS.md pointer, .env.example,
.gitignore, empty data/) — the served layers are author+promote outputs and
must never be pre-seeded. `.mcp.json` is opt-in (spec 2026-09-23-0001 §7): the
default scaffold omits it — the local `ariadne` CLI needs no server config —
and `--with-mcp` creates the registry-aware MCP config without ever removing
an existing file. Entry points assert the editable install registered all
nine console scripts and that each import target resolves.
"""

import json
from importlib.metadata import entry_points

from ariadne.init import main

CONSOLE_SCRIPTS = (
    "ariadne",  # the local JSON CLI (spec 2026-09-23-0001 §4)
    "ariadne-author",
    "ariadne-validate",
    "ariadne-serve",
    "ariadne-promote",
    "ariadne-init",
    "ariadne-skill",
    "ariadne-profiler",
    "ariadne-ingest",
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

# The Git-mode scaffold (issue #39/G7): the artifact layers are TRACKED Git
# artifacts; the operator state dir, pending proposals, the supported input
# locations under data/ (except the Seed Notes artifact) and secrets stay
# ignored.
GIT_MODE_GITIGNORE_LINES = (
    "data/*",
    "!data/seed_notes.md",
    "staging/",
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
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        assert var in env, var

    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in gitignore, line


def test_scaffold_with_mcp_creates_registry_aware_config(tmp_path):
    """--with-mcp (spec §7): the opt-in .mcp.json keeps the registry-aware shape —
    --sources names the project's ariadne.yaml; the semantic/context paths are
    the project-root defaults promote creates on first promotion."""
    target = tmp_path / "proj"
    assert main([str(target), "--with-mcp"]) == 0
    for rel in ("data/seed_notes.md", ".gitignore"):
        assert (target / rel).is_file(), rel
    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))  # parses as JSON
    server = mcp["mcpServers"]["ariadne"]
    assert server["command"] == "ariadne-serve"
    assert server["args"] == [
        "--sources",
        "ariadne.yaml",
        "--semantic",
        "semantic_layer",
        "--context",
        "context_layer",
    ]


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
    """Rev 10 (ADR-0011): AGENTS.md = project facts + skill pointer + layout
    table + promotion-gate rule. The workflow prose belongs to the packaged
    skill and is NOT duplicated here."""
    target = tmp_path / "proj"
    assert main([str(target)]) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "Load the ariadne skill (`ariadne-skill install` if absent)" in agents
    assert "TODO" in agents  # project facts the owner fills in
    assert "`context_layer/`" in agents and "`staging/`" in agents  # layout table
    assert "ariadne-promote" in agents and "review_needed" in agents  # gate rule
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


def test_git_pointer_page_names_the_legacy_migration_human_seams(tmp_path):
    """K6 (issue #46, spec 0010 §9): the Git scaffold's gate rule names legacy
    migration (`import-legacy`, `enrich-legacy`) among the human-only
    operations — an agent never binds or imports legacy pages itself."""
    target = tmp_path / "proj"
    assert main([str(target), "--git"]) == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "import-legacy" in agents and "enrich-legacy" in agents
    assert "`approve-sources`" in agents and "`ariadne-admit`" in agents


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
    """Issue #39 [2]: ``--git`` scaffolds for the Git authoring workflow —
    the served artifact layers are TRACKED (not ignored), while ``.ariadne/``
    state, pending ``staging/`` and inputs/secrets stay ignored, and no
    output layer is pre-seeded."""
    target = tmp_path / "proj"
    assert main([str(target), "--git"]) == 0
    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    for line in GIT_MODE_GITIGNORE_LINES:
        assert line in gitignore, line
    assert "context_layer" not in gitignore and "semantic_layer" not in gitignore
    for rel in ("data/seed_notes.md", "ariadne.yaml", "AGENTS.md", ".env.example"):
        assert (target / rel).is_file(), rel
    # no pre-seeded outputs: the artifact layers arrive only through proposals
    assert not (target / "context_layer").exists()
    assert not (target / "semantic_layer").exists()
    assert not (target / "staging").exists()
    # the pointer page names the Git admission gate, not staging promotion
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "ariadne-admit" in agents and "`.ariadne/`" in agents
    assert "ariadne-promote" not in agents
    assert "profile" not in agents.lower()  # still a pointer page, no loop prose


def test_git_scaffold_keeps_existing_files_and_ignore_rules(tmp_path, capsys):
    """Issue #39 [2]/[3]: adopting Git over an existing legacy project keeps
    every existing file — including a legacy ``.gitignore`` whose rules still
    exclude the served layers (the proposal seams track chosen artifacts
    explicitly, so the old rules never block the migration)."""
    target = tmp_path / "legacy"
    target.mkdir()
    (target / ".gitignore").write_text("*.tmp\ncontext_layer/\nsemantic_layer/\n", encoding="utf-8")
    (target / "data").mkdir()
    (target / "data" / "seed_notes.md").write_text("# my notes\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("# my project\n", encoding="utf-8")
    assert main([str(target), "--git"]) == 0
    assert (target / ".gitignore").read_text(encoding="utf-8") == (
        "*.tmp\ncontext_layer/\nsemantic_layer/\n"
    )  # existing rules are NOT rewritten
    assert (target / "data" / "seed_notes.md").read_text(encoding="utf-8") == "# my notes\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# my project\n"
    assert not (target / ".mcp.json").exists()  # still opt-in only


def test_git_scaffold_ignores_supported_input_locations_but_keeps_seed_notes(tmp_path):
    """G7 fix pass F4: the --git ignore template covers the supported INPUT
    locations (databases, parquet/csv/json/delta datasets under data/, and
    documents under data/docs/), so ordinary ``git add`` never picks up local
    inputs — while ``data/seed_notes.md`` stays trackable (the artifact the
    allowlisted ``-f`` literal-pathspec seam commits)."""
    import subprocess

    target = tmp_path / "proj"
    assert main([str(target), "--git"]) == 0

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
