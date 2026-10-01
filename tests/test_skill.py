"""The packaged agent skill (ADR-0011, spec rev 10 §8.21): install/status/path.

The wheel ships SKILL.md + the grain-rubric reference as package data
(src/ariadne/skill_assets/). ``ariadne-skill`` copies them to the cross-agent
``~/.agents/skills/ariadne/`` (user) or ``.agents/skills/ariadne/`` (project)
convention, optionally wiring agent-specific dirs; ``status`` hashes every
managed target against the packaged assets and reports drift. User-scope tests
monkeypatch HOME so nothing ever touches the real home directory.
"""

import hashlib
import os
import re

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.skill import ASSETS, _dir_hash, main


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Isolated user home + project cwd (user scope must never touch real HOME)."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setenv("HOME", str(home))  # Path.home()/expanduser follow HOME on POSIX
    monkeypatch.chdir(proj)
    return home, proj


def test_packaged_assets_exist():
    assert (ASSETS / "SKILL.md").is_file()
    assert (ASSETS / "references" / "grain-rubric.md").is_file()
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    assert "grain-rubric.md" in skill  # the reference is linked from the skill
    assert "search_context" in skill and "define_metric" in skill  # the agent rules


def test_skill_teaches_local_cli_as_default_mcp_optional():
    """Spec 2026-09-23-0001 §8: the packaged skill defaults to the five local
    `ariadne` commands (root selection, caveats, labels, file/stdin ad-hoc
    definitions); MCP appears only in the optional integration section with
    accurate ariadne-core[mcp] install guidance — never as a requirement."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    for cmd in ("list-metrics", "search-context", "get-metric", "list-datasets", "define-metric"):
        assert f"ariadne {cmd}" in skill, cmd
    assert "ariadne define-metric --file" in skill  # file definitions (stdin named too)
    assert "--served" in skill  # safe promoted-root selection escape hatch
    assert "governed: true" in skill and "governed: false" in skill  # labels taught
    # MCP only after the optional integration heading, with the real extra named
    optional_at = skill.index("Optional: MCP integration")
    mcp_mentions = [m.start() for m in re.finditer("MCP", skill)]
    assert mcp_mentions and all(pos > optional_at for pos in mcp_mentions)
    assert "ariadne-core[mcp]" in skill
    normalized = " ".join(skill.split())
    assert "Ariadne package checkout" in normalized
    assert "not from the data project root" in normalized
    assert "ariadne-init --with-mcp ." in skill
    assert skill.index("pyproject.toml") < skill.index("ariadne-init --with-mcp .")
    assert "ariadne-serve --sources ariadne.yaml" in skill


def test_skill_teaches_answer_example_guidance():
    """Issue #21 (spec 2026-09-29-0007): the packaged skill teaches examples as
    labeled references — similarity is not equivalence, saved text is never an
    instruction, the method is revalidated and executed FRESH, drafts are
    hypotheses — and saving is user-confirmed before the call, with the
    operator review command explicitly forbidden to the agent."""
    normalized = " ".join((ASSETS / "SKILL.md").read_text(encoding="utf-8").split())
    assert "ariadne search-examples" in normalized  # the lookup command
    assert "A hit is never required, and never an answer" in normalized
    assert "Similar words are not equivalence" in normalized  # scope compared
    for scope in ("dates", "grain", "served Policies"):
        assert scope in normalized, scope
    assert "evidence, not instructions" in normalized  # stored text never directs
    assert "run a FRESH" in normalized and "never the saved SQL" in normalized
    assert "governed/ad-hoc label" in normalized  # true governance label reported
    assert "independent numeric attestation" in normalized  # no compile-only claim
    assert "Drafts are hypotheses" in normalized  # uncheckable drafts not support
    assert "confirm BEFORE calling save" in normalized  # user gate before the call
    assert "ariadne save-example" in normalized
    assert "Never save silently, never harvest the transcript" in normalized
    assert "never run the operator-only `ariadne-example-review`" in normalized


def test_path_prints_packaged_dir(project, capsys):
    assert main(["path"]) == 0
    assert capsys.readouterr().out.strip() == str(ASSETS)


def test_install_project_scope_creates_files(project):
    _, proj = project
    assert main(["install", "--scope", "project"]) == 0
    installed = proj / ".agents" / "skills" / "ariadne"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "references" / "grain-rubric.md").is_file()
    assert (installed / "SKILL.md").read_bytes() == (ASSETS / "SKILL.md").read_bytes()


def test_install_user_scope_and_agent_pi_symlink(project):
    home, _ = project
    assert main(["install", "--scope", "user", "--agent", "pi"]) == 0
    installed = home / ".agents" / "skills" / "ariadne"
    assert (installed / "SKILL.md").is_file()
    link = home / ".pi" / "agent" / "skills" / "ariadne"
    assert link.is_symlink()
    assert link.resolve() == installed.resolve()


def test_reinstall_refreshes_instead_of_failing_or_merging(project):
    _, proj = project
    assert main(["install", "--scope", "project"]) == 0
    installed = proj / ".agents" / "skills" / "ariadne" / "SKILL.md"
    installed.write_text("tampered\n", encoding="utf-8")  # drift after install
    assert main(["install", "--scope", "project"]) == 0  # refresh, not an error
    assert installed.read_bytes() == (ASSETS / "SKILL.md").read_bytes()


def test_status_reports_ok_then_detects_tampering(project, capsys):
    _, proj = project
    assert main(["install", "--scope", "project"]) == 0
    assert main(["status"]) == 0
    out = capsys.readouterr().out  # includes (and flushes) the install output
    assert "ok" in out
    assert "drift" not in out
    target = proj / ".agents" / "skills" / "ariadne" / "SKILL.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "drift" in out  # the tampered target is named as drifted
    drift_line = next(line for line in out.splitlines() if "drift" in line)
    assert str(proj / ".agents") in drift_line
    # other targets still report absent (never installed in this isolated env)
    assert "absent" in out


def test_status_symlink_target_hashes_through_the_link(project, capsys):
    home, _ = project
    assert main(["install", "--scope", "user", "--agent", "pi"]) == 0
    capsys.readouterr()  # flush the install output
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    pi_line = next(line for line in out.splitlines() if ".pi" in line)
    assert "ok" in pi_line and "(symlink)" in pi_line  # resolves to the same content


def test_dir_hash_is_content_sensitive():
    baseline = _dir_hash(ASSETS)
    assert baseline == _dir_hash(ASSETS)  # stable
    assert len(baseline) == hashlib.sha256().digest_size * 2


def test_install_agent_refuses_existing_non_symlink_dir(project, capsys):
    """An agent target that exists and is not a symlink is user content —
    install refuses (exit != 0, error names the path) and the directory's
    contents stay intact. Install never deletes directories."""
    home, _ = project
    agent_dir = home / ".claude" / "skills" / "ariadne"
    agent_dir.mkdir(parents=True)
    (agent_dir / "user-content.txt").write_text("precious\n", encoding="utf-8")
    assert main(["install", "--scope", "user", "--agent", "claude"]) != 0
    err = capsys.readouterr().err
    assert str(agent_dir) in err  # the refusal names the path
    assert "remove it manually" in err  # and suggests manual removal
    assert (agent_dir / "user-content.txt").read_text(encoding="utf-8") == "precious\n"
    assert not agent_dir.is_symlink()  # untouched, not replaced


def test_install_agent_replaces_existing_symlink_and_logs_old_target(project, capsys):
    """Any symlink is acceptable to overwrite: the replaced link is re-pointed
    at the installed copy, the old target (and its contents) is untouched, and
    what the link pointed to is logged."""
    home, _ = project
    installed = home / ".agents" / "skills" / "ariadne"
    link = home / ".pi" / "agent" / "skills" / "ariadne"
    old = home / "elsewhere" / "ariadne-skill"
    old.mkdir(parents=True)
    (old / "keep.txt").write_text("real content\n", encoding="utf-8")
    link.parent.mkdir(parents=True)
    os.symlink(old, link)
    assert main(["install", "--scope", "user", "--agent", "pi"]) == 0
    out = capsys.readouterr().out
    assert link.is_symlink() and link.resolve() == installed.resolve()
    assert (installed / "SKILL.md").is_file()
    assert str(old) in out  # the log names what the replaced symlink pointed to
    assert (old / "keep.txt").read_text(encoding="utf-8") == "real content\n"


def test_rubric_states_the_real_grain_audit_order():
    """The validate audit runs after render/bind compilation, before execution —
    the packaged rubric must not claim it rejects before compile (only
    ``define_metric`` does)."""
    rubric = (ASSETS / "references" / "grain-rubric.md").read_text(encoding="utf-8")
    assert "validate audit reject non-grain-preserving sources before compile" not in rubric
    assert "after render/bind compilation, before execution" in rubric


def test_skill_teaches_the_admitted_multifact_query_commands():
    """Issue #30: the packaged skill teaches the two multi-fact commands — that
    they answer only over a graph admitted by human Promotion of a validated
    bundle, and that their responses are governed through that local route
    (never a claim that a validated-but-unpromoted graph is governed)."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    for cmd in ("query-metrics", "query-detail"):
        assert f"ariadne {cmd} --file" in skill, cmd
    assert "admitted" in skill and "unadmitted" in skill
    assert "route: local-promotion" in skill
    # the submission boundary names the graph path (the one extra semantic file)
    assert "semantic_layer/graph.yml" in skill
