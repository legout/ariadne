"""Guided journey setup and Git connection checks (spec 0010 §2/§2.1, plan J5/V5).

One compact family over independently authored facts: a real local Git remote
exercises the public ``check_git_connection``/``git-check`` route with push/PR
explicitly unverified; a controlled failed-auth response is injected only at
the subprocess dependency boundary; journey setup refuses invalid selections
before any write, requires confirmation before creating a private profile,
reports missing baseline metadata without importing, and keeps a locally
modified skill untouched until an explicit update.

Oracles are the fixtures themselves: hand-written manifests/profiles, known
digests, native Git state, and exact pre/post file bytes — never values
copied from implementation output.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import msgspec
import pytest
from lumio_wiki import cli
from lumio_wiki.env_loader import (
    GIT_REMOTE_ENV_VAR,
    GIT_TARGET_BRANCH_ENV_VAR,
    SUBMISSION_MODE_ENV_VAR,
)
from lumio_wiki.git_connection import GitConnectionReport, check_git_connection
from lumio_wiki.skill import SKILL_FILENAME, install_skill, skill_status
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)

NAMESPACE = "urn:uuid:5f9d1c0e-8b4a-4c2f-9d31-2e7a6b8c4d05"
SOURCE_ID = "j5-operator-manual"
ENTITY_ID = "entity:journey-press"
SOURCE_BYTES = b"Journey fixture: the original manual text for binding coverage."
SOURCE_DIGEST = hashlib.sha256(SOURCE_BYTES).hexdigest()
BRANCH = "main"
GIT_IDENTITY = {"user_name": "Test Author", "user_email": "test@example.com"}

CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
      literal_kind: string
"""

MANAGED_PAGE = """\
---
id: "entity:journey-press"
title: "Journey Press"
entity_types:
  - machine
category: concepts
type: "machine page"
durability_rationale: "The original document permanently supports this page."
tags:
  - "workshop"
summary: "Journey Press summary."
lifecycle: "draft"
visibility: "internal"
sources:
  - id: "j5-operator-manual"
    title: "Journey Press source"
claims:
  - id: claim:j5-press-documented
    predicate: documented-at
    value: "2026-10-01"
    value_type: string
    status: accepted
    evidence:
      - section: "Overview"
synthetic: false
---

# Journey Press

## Overview

Supported by the manual original.
"""


# ---------------------------------------------------------------------------
# Fixtures (local synthetic Git only; no network, no real credentials).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}")
    _git(path, "config", "user.email", GIT_IDENTITY["user_email"])
    _git(path, "config", "user.name", GIT_IDENTITY["user_name"])
    return path


def _adopted_kb(repo: Path) -> Path:
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL, encoding="utf-8")
    (kb / "concepts" / "journey-press.md").write_text(MANAGED_PAGE, encoding="utf-8")
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={SOURCE_ID: "active"},
                bindings={ENTITY_ID: {SOURCE_ID: SOURCE_DIGEST}},
            )
        )
    )
    return kb


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write_profile(
    path: Path, *, namespace: str, registry: Path, retention: str = "required"
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": namespace,
                "source_registry": str(registry),
                "retention": retention,
                "artifact_store": {
                    "kind": "local",
                    "root": str(path.parent / "artifacts"),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _clean_lumio_env(monkeypatch) -> None:
    """Remove exported Lumio configuration so only fixture state is visible."""
    for key in (
        "LUMIO_KB_PATH",
        "LUMIO_PUBLISH_TO",
        "LUMIO_SOURCE_STORE",
        "LUMIO_SOURCE_REGISTRY",
        "LUMIO_ARTIFACT_RETENTION",
        "LUMIO_SOURCE_EXCHANGE",
        SUBMISSION_MODE_ENV_VAR,
        GIT_REMOTE_ENV_VAR,
        GIT_TARGET_BRANCH_ENV_VAR,
        "LUMIO_RETRIEVAL_BACKEND",
        "LUMIO_RETRIEVAL_MODE",
        "LUMIO_S3_REGION",
        "LUMIO_S3_ENDPOINT",
    ):
        monkeypatch.delenv(key, raising=False)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _content_snapshot(root: Path) -> dict[str, bytes]:
    """Snapshot excluding ``.git`` internals (repository/config/store surface)."""
    return {rel: data for rel, data in _snapshot(root).items() if not rel.startswith(".git/")}


def _env_value(env_path: Path, key: str) -> str | None:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def _contributor_project(tmp_path: Path) -> tuple[Path, Path]:
    """A nonempty managed clone plus its private profile (the AC11 journey start)."""
    maintainer = _init_repo(tmp_path / "maintainer")
    _adopted_kb(maintainer)
    _commit(maintainer, "base")
    project = tmp_path / "contributor" / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(maintainer), str(project)],
        capture_output=True,
        check=True,
    )
    _git(project, "config", "user.email", "contributor@example.com")
    _git(project, "config", "user.name", "Contributor")
    clone_kb = project / "kb"
    assert (clone_kb / "lumio.yaml").is_file()
    return project, clone_kb


# ---------------------------------------------------------------------------
# V5: capabilities without mutation.
# ---------------------------------------------------------------------------


def test_journey_setup_reports_capabilities_without_mutation(tmp_path: Path, monkeypatch, capsys):
    """The contributor journey: git-check proves read access only, and setup
    writes exactly its explicitly selected actions — nothing else moves."""
    from lumio_wiki.env_loader import KB_PATH_ENV_VAR

    project, kb = _contributor_project(tmp_path)
    private = tmp_path / "private"
    profile = _write_profile(
        private / "profile.json", namespace=NAMESPACE, registry=private / "registry"
    )
    profile_bytes = profile.read_bytes()
    monkeypatch.chdir(project)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    # Public SDK route against the real local remote (the clone's origin):
    # read success with push/PR explicitly unverified, and zero mutation of
    # the whole project directory including .git.
    before = _snapshot(project)
    report = check_git_connection(project)
    assert isinstance(report, GitConnectionReport)
    assert report.schema_version == 1
    assert report.remote.name == "origin"
    assert report.remote.configured is True
    assert report.remote.read == "success"
    assert report.push_pr == "unverified"
    assert any("push" in line for line in report.guidance)
    assert _snapshot(project) == before

    # Journey setup on the nonempty managed clone.
    setup_before = _content_snapshot(project)
    rc = cli.main(["setup", str(kb), "--journey", "--private-profile", str(profile)])
    assert rc == 0
    out = capsys.readouterr().out
    setup_after = _content_snapshot(project)

    # Only the explicitly selected setup actions wrote (.env and AGENTS.md).
    assert set(setup_after) - set(setup_before) == {".env", "AGENTS.md"}
    for relative, content in setup_before.items():
        assert setup_after[relative] == content

    # Machine settings are the fixture facts: local-commit default, the
    # clone's configured 'origin', and its deterministic branch.
    env = project / ".env"
    assert _env_value(env, KB_PATH_ENV_VAR) == str(kb)
    assert _env_value(env, SUBMISSION_MODE_ENV_VAR) == "commit"
    assert _env_value(env, GIT_REMOTE_ENV_VAR) == "origin"
    assert _env_value(env, GIT_TARGET_BRANCH_ENV_VAR) == BRANCH

    # Capabilities are reported truthfully; no publication credentials needed.
    assert "Guided authoring journey" in out
    assert "no publication credentials" in out
    assert "exchange: not configured" in out
    assert "skill drift: not checked" in out

    # Missing baseline metadata is reported with trusted-digest guidance and
    # an explicit preview/confirm import path — setup imports nothing itself.
    assert "baseline metadata: MISSING" in out
    assert "source-bootstrap inspect" in out
    assert "--digest" in out
    assert "--confirm" in out
    assert not (private / "registry").exists()
    assert profile.read_bytes() == profile_bytes

    # Private paths never enter tracked content.
    agents_md = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert str(profile) not in agents_md
    assert str(private / "registry") not in agents_md


def test_git_check_cli_json_reports_read_success_and_field_contract(
    tmp_path: Path, monkeypatch, capsys
):
    """``git-check <project> --json`` emits the versioned report contract."""
    bare = tmp_path / "origin.git"
    bare.mkdir(parents=True)
    _git(bare, "init", "-q", "--bare")
    project = _init_repo(tmp_path / "project")
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    _commit(project, "initial")
    _git(project, "remote", "add", "origin", str(bare))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert cli.main(["git-check", str(project), "--json", "--remote", "origin"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == 1
    assert payload["tool"]["available"] is True
    assert str(payload["tool"]["version"]).startswith("git version")
    assert payload["identity"] == {"configured": True, **GIT_IDENTITY}
    assert payload["repository"] == {"is_repository": True, "branch": BRANCH, "clean": True}
    assert payload["remote"]["name"] == "origin"
    assert payload["remote"]["configured"] is True
    assert payload["remote"]["read"] == "success"
    assert payload["remote"]["url"] == str(bare)
    assert payload["push_pr"] == "unverified"
    assert payload["blockers"] == []


def test_git_check_redacts_credential_bearing_auth_failures(tmp_path: Path, monkeypatch):
    """A credential-bearing auth failure is classified, bounded and redacted;
    only the subprocess dependency boundary is injected — every other probe
    (version, identity, repository) runs the real runner."""
    from lumio_wiki import git_connection

    project = _init_repo(tmp_path / "project")
    _git(project, "remote", "add", "origin", "https://private.example/j5/repo.git")

    real_run = subprocess.run

    def failing_ls_remote(argv, **kwargs):
        if "ls-remote" in argv:
            return subprocess.CompletedProcess(
                argv,
                128,
                stdout="",
                stderr=(
                    "fatal: Authentication failed for "
                    "'https://ak:SECRETTOKEN@private.example/j5/repo.git/'"
                ),
            )
        return real_run(argv, **kwargs)

    monkeypatch.setattr(git_connection.subprocess, "run", failing_ls_remote)

    report = check_git_connection(project)

    # Non-remote probes delegated to the real runner.
    assert report.tool.available is True
    assert report.identity.configured is True
    assert report.repository.is_repository is True
    # The controlled failed-auth response: classified, redacted, unverified.
    assert report.remote.read == "failed"
    assert report.remote.failure_code == "authentication_failed"
    assert "SECRETTOKEN" not in report.remote.failure_message
    assert "[redacted]" in report.remote.failure_message
    assert "SECRETTOKEN" not in json.dumps(msgspec.to_builtins(report))
    assert report.push_pr == "unverified"
    assert report.blockers
    assert any("credential" in line for line in report.guidance)


def test_git_check_reports_missing_tool_timeout_and_absent_configuration(
    tmp_path: Path, monkeypatch
):
    """Missing Git, a probe timeout and absent configuration each produce a
    bounded report — never a traceback or an invented access proof."""
    from lumio_wiki import git_connection

    # Capture the real runner before any patch: the subprocess module
    # attribute patch below is process-wide, so every repository the test
    # itself creates must be prepared before or after with the real runner.
    real_run = subprocess.run
    project = _init_repo(tmp_path / "project2")
    _git(project, "remote", "add", "origin", str(tmp_path / "never-contacted"))

    # Missing executable: every probe fails at the subprocess boundary.
    def missing_executable(argv, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_connection.subprocess, "run", missing_executable)
    report = check_git_connection(tmp_path / "project")
    assert report.tool.available is False
    assert report.remote.read == "not-attempted"
    assert any("Git executable" in blocker for blocker in report.blockers)

    # Timeout on the remote probe only; local checks stay real.
    def timing_out(argv, **kwargs):
        if "ls-remote" in argv:
            raise subprocess.TimeoutExpired(argv, 30)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(git_connection.subprocess, "run", timing_out)
    report = check_git_connection(project)
    assert report.remote.read == "failed"
    assert report.remote.failure_code == "timeout"
    assert report.push_pr == "unverified"

    # Absent remote configuration with the real runner, restored before the
    # project3 fixture itself runs git.
    monkeypatch.setattr(git_connection.subprocess, "run", real_run)
    report = check_git_connection(_init_repo(tmp_path / "project3"))
    assert report.remote.configured is False
    assert report.remote.read == "not-attempted"
    assert any("origin" in blocker for blocker in report.blockers)

    # Missing project directory: bounded blocker, no exception.
    report = check_git_connection(tmp_path / "does-not-exist")
    assert report.schema_version == 1
    assert report.repository.is_repository is False
    assert any("not found" in blocker for blocker in report.blockers)


# ---------------------------------------------------------------------------
# V5: invalid selections refuse before any write.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "argv_tail", "env_override"),
    [
        ("journey_without_profile", ["--journey"], None),
        ("missing_profile_file", ["--journey", "--private-profile", "PROFILE"], None),
        (
            "competing_source_store_flag",
            [
                "--journey",
                "--private-profile",
                "PROFILE",
                "--source-store",
                "s3://bucket/store",
            ],
            None,
        ),
        (
            "competing_retention_env",
            ["--journey", "--private-profile", "PROFILE"],
            "LUMIO_ARTIFACT_RETENTION",
        ),
        ("retention_disabled_profile", ["--journey", "--private-profile", "PROFILE"], None),
    ],
)
def test_journey_setup_refuses_invalid_selections_before_writes(
    label, argv_tail, env_override, tmp_path: Path, monkeypatch, capsys
):
    project = _init_repo(tmp_path / "project")
    kb = _adopted_kb(project)
    _commit(project, "base")
    private = tmp_path / "private"
    profile = private / "profile.json"
    if label not in ("journey_without_profile", "missing_profile_file"):
        _write_profile(
            profile,
            namespace=NAMESPACE,
            registry=private / "registry",
            retention="disabled" if label == "retention_disabled_profile" else "required",
        )
    argv = [str(profile) if item == "PROFILE" else item for item in argv_tail]

    monkeypatch.chdir(project)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    if env_override is not None:
        monkeypatch.setenv(env_override, "disabled")

    before = _content_snapshot(project)
    rc = cli.main(["setup", str(kb), *argv])

    assert rc == 2
    assert _content_snapshot(project) == before
    assert not (project / ".env").exists()
    assert not (project / "AGENTS.md").exists()
    err = capsys.readouterr().err
    if label == "journey_without_profile":
        assert "--private-profile" in err
    elif label == "missing_profile_file":
        assert "does not exist" in err
        assert not profile.exists()
    elif label == "retention_disabled_profile":
        assert "retention" in err
    else:
        assert "exclusive" in err


def test_journey_profile_creation_requires_confirmation(tmp_path: Path, monkeypatch, capsys):
    """A new profile is previewed and written only after explicit
    confirmation; declining leaves the whole project untouched."""
    project = _init_repo(tmp_path / "project")
    kb = _adopted_kb(project)
    _commit(project, "base")
    monkeypatch.chdir(project)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    profile = tmp_path / "private" / "new-profile.json"
    home = tmp_path / "home"

    # Declining the confirmation: no profile, no .env, no AGENTS.md, and no
    # registry/store directories created anywhere.
    answers = iter(["", "", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = cli.main(["setup", str(kb), "--journey", "--private-profile", str(profile)])
    assert rc == 1
    assert not profile.exists()
    assert not (project / ".env").exists()
    assert not (project / "AGENTS.md").exists()
    assert "aborted" in capsys.readouterr().err
    assert not (home / ".lumio").exists()

    # Confirming writes exactly the previewed profile; the registry/store
    # directories themselves are still not created by setup.
    answers = iter(["", "", "y", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = cli.main(["setup", str(kb), "--journey", "--private-profile", str(profile)])
    assert rc == 0
    capsys.readouterr()
    payload = json.loads(profile.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["namespace"] == NAMESPACE
    assert payload["retention"] == "required"
    assert payload["source_registry"] == str(home / ".lumio" / "registries" / NAMESPACE)
    assert payload["artifact_store"] == {
        "kind": "local",
        "root": str(home / ".lumio" / "artifacts" / NAMESPACE),
    }
    assert not (home / ".lumio").exists()
    assert _env_value(project / ".env", SUBMISSION_MODE_ENV_VAR) == "commit"
    assert _env_value(project / ".env", GIT_REMOTE_ENV_VAR) == "origin"
    assert _env_value(project / ".env", GIT_TARGET_BRANCH_ENV_VAR) == BRANCH


def test_journey_setup_keeps_modified_skill_until_explicit_update(
    tmp_path: Path, monkeypatch, capsys
):
    """A locally modified skill copy survives journey setup untouched; setup
    reports the drift and the explicit update path with a restart notice."""
    project = _init_repo(tmp_path / "project")
    kb = _adopted_kb(project)
    _commit(project, "base")
    private = tmp_path / "private"
    profile = _write_profile(
        private / "profile.json", namespace=NAMESPACE, registry=private / "registry"
    )
    monkeypatch.chdir(project)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    target = install_skill(scope="user")
    skill_file = target / SKILL_FILENAME
    original = skill_file.read_bytes()
    modified = original + b"\nlocal modification\n"
    skill_file.write_bytes(modified)
    assert skill_status(scope="user").state != "current"

    rc = cli.main(
        [
            "setup",
            str(kb),
            "--journey",
            "--private-profile",
            str(profile),
            "--skill-scope",
            "user",
        ]
    )
    assert rc == 0
    # The locally modified copy is preserved exactly until an explicit update.
    assert skill_file.read_bytes() == modified
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "skill update" in combined
    assert "restart the agent or start a new session" in combined
