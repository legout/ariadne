"""``ariadne init`` (spec 0040 §3.2; AC1, AC11): repository, identity, private profile
pair, selector and native KB as one commit holding only init's own files."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import init, lumio_context, profile_pair  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"):
        monkeypatch.delenv(key, raising=False)


def git(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


class Terminal:
    def __init__(self, answers=""):
        self._lines = iter(answers.splitlines(keepends=True))

    def isatty(self):
        return True

    def readline(self):
        return next(self._lines, "")

    def write(self, _text):
        pass

    def flush(self):
        pass


def identity(project: Path):
    git(project, "config", "user.name", "Init Tests")
    git(project, "config", "user.email", "init@ariadne.local")


def test_init_in_an_empty_directory_creates_one_commit_with_the_profile_pair(tmp_path):
    project = tmp_path / "proj"
    out = init.init_project(
        project, stdin=Terminal("Init Tests\ninit@ariadne.local\n"), stdout=Terminal()
    )

    assert out["initialized"] is True
    assert out["namespace"].startswith("urn:uuid:")
    # one commit; it holds exactly init's tracked files (spec §3.2.4)
    assert git(project, "rev-list", "--count", "HEAD").strip() == "1"
    committed = set(git(project, "show", "--name-only", "--format=", "HEAD").split())
    assert {
        "context_integration.yaml",
        "ariadne.yaml",
        "data/seed_notes.md",
        ".gitignore",
    } <= committed
    assert "knowledge/lumio.yaml" in committed
    assert not any(rel.startswith(".ariadne/") for rel in committed)
    assert git(project, "status", "--porcelain", "--untracked-files=all").strip() == ""
    # the selector sits at the highest supported revision with empty bindings
    selector = (project / "context_integration.yaml").read_text(encoding="utf-8")
    assert f"support_revision: {max(lumio_context.IMPLEMENTED_PROFILE_REVISIONS)}" in selector
    assert "bindings: []" in selector
    # both private files are 0600 and the pair is recorded
    uuid_name = out["namespace"].removeprefix("urn:uuid:")
    lumio = profile_pair.config_dir() / f"{uuid_name}.json"
    sibling = profile_pair.sibling_path(lumio)
    for path in (lumio, sibling):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    settings = profile_pair.load(project)
    assert settings["visibility_scope"] == ["public"]
    assert settings["run_log"] == {"enabled": True, "retention_days": 90}
    assert settings["publication_destination"].endswith(f"/published/{uuid_name}")


def test_init_in_an_existing_repository_commits_only_its_own_files(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    identity(project)
    (project / "notes.txt").write_text("tracked\n")
    git(project, "add", "notes.txt")
    git(project, "commit", "-q", "-m", "user: first")
    (project / "notes.txt").write_text("unstaged edit\n")  # unstaged work
    (project / "staged.txt").write_text("staged\n")
    git(project, "add", "staged.txt")  # staged work

    init.init_project(project)

    committed = set(git(project, "show", "--name-only", "--format=", "HEAD").split())
    assert "staged.txt" not in committed and "notes.txt" not in committed
    assert "context_integration.yaml" in committed
    # the user's staged and unstaged work is exactly as it was
    assert git(project, "diff", "--cached", "--name-only").split() == ["staged.txt"]
    assert git(project, "diff", "--name-only").split() == ["notes.txt"]
    assert (project / "notes.txt").read_text() == "unstaged edit\n"


def test_init_refuses_a_conflicting_existing_file_and_writes_nothing(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    identity(project)
    (project / "ariadne.yaml").write_text("sources: []  # mine\n")
    before = sorted(p.name for p in project.iterdir())
    with pytest.raises(ValueError, match="ariadne.yaml"):
        init.init_project(project)
    assert sorted(p.name for p in project.iterdir()) == before
    assert not (profile_pair.config_dir()).exists()  # no profile pair either


def test_rerunning_init_is_a_noop(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    identity(project)
    init.init_project(project)
    head = git(project, "rev-parse", "HEAD")
    files = sorted(p.name for p in profile_pair.config_dir().iterdir())

    again = init.init_project(project)

    assert again["initialized"] is False
    assert git(project, "rev-parse", "HEAD") == head
    assert sorted(p.name for p in profile_pair.config_dir().iterdir()) == files


def test_init_without_a_git_identity_and_with_yes_refuses_naming_the_git_config_commands(tmp_path):
    with pytest.raises(ValueError, match="git -C .* config user.name"):
        init.init_project(tmp_path / "proj", assume_yes=True)


def test_a_missing_or_invalid_sibling_refuses_naming_the_file(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    identity(project)
    out = init.init_project(project)
    sibling = profile_pair.sibling_path(
        profile_pair.config_dir() / f"{out['namespace'].removeprefix('urn:uuid:')}.json"
    )
    doc = json.loads(sibling.read_text())
    sibling.write_text(json.dumps({**doc, "surprise": 1}))
    with pytest.raises(profile_pair.ProfileError, match=r"\.ariadne\.json"):
        profile_pair.load(project)
    sibling.unlink()
    with pytest.raises(profile_pair.ProfileError, match="missing"):
        profile_pair.load(project)


def test_init_refuses_any_differing_scaffold_target_and_names_it(tmp_path):
    """Finding 5: every target file is preflighted; a differing .gitignore (or any other
    target) refuses BEFORE anything is created, naming the file. Unrelated files are fine."""
    for rel in (".gitignore", ".env.example"):
        project = tmp_path / rel.strip(".")
        project.mkdir()
        git(project, "init", "-q")
        identity(project)
        (project / rel).write_text("my own rules\n")
        (project / "unrelated.txt").write_text("fine\n")
        with pytest.raises(ValueError, match=rf"{rel}.*different content"):
            init.init_project(project)
        assert not (project / "knowledge").exists()
        assert not (project / ".ariadne").exists()
        assert not profile_pair.config_dir().exists() or not any(
            profile_pair.config_dir().iterdir()
        )


def test_the_sibling_profile_is_published_atomically_and_never_replaced(tmp_path):
    target = tmp_path / "private" / "x.ariadne.json"
    profile_pair.write_private(target, '{"a": 1}\n')
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        profile_pair.write_private(target, '{"a": 2}\n')
    assert target.read_text() == '{"a": 1}\n'
    assert [p.name for p in target.parent.iterdir()] == ["x.ariadne.json"]  # no temp left


def test_init_does_not_replace_an_existing_local_profile_record(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    identity(project)
    (project / ".ariadne").mkdir()
    (project / ".ariadne" / "profile.json").write_text("{}")
    with pytest.raises(ValueError, match="already records a private profile"):
        init.init_project(project)
    assert (project / ".ariadne" / "profile.json").read_text() == "{}"


def test_the_generated_agents_page_names_only_current_commands(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    identity(project)
    init.init_project(project)
    text = (project / "AGENTS.md").read_text()
    assert "ariadne approve" in text and "ariadne draft edit" in text
    assert "ariadne-skill" not in text and "ariadne-authoring" not in text
