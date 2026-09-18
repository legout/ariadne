"""The packaged agent skill (ADR-0011, spec rev 10 §8.21): install/status/path.

The wheel ships SKILL.md + the grain-rubric reference as package data
(src/ariadne/skill_assets/). ``ariadne-skill`` copies them to the cross-agent
``~/.agents/skills/ariadne/`` (user) or ``.agents/skills/ariadne/`` (project)
convention, optionally wiring agent-specific dirs; ``status`` hashes every
managed target against the packaged assets and reports drift. User-scope tests
monkeypatch HOME so nothing ever touches the real home directory.
"""

import hashlib

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
    target.write_text(
        target.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8"
    )
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
