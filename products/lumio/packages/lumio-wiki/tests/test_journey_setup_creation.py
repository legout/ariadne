"""Confirmed empty managed-KB creation (spec 0010 §2.2/AC12, plan 0010 J5a/V5a).

Two compact families at the public setup CLI seam plus one narrow I/O-failure
injection. Oracles are hand-authored facts: the fixture namespace and topology,
native Git state, strict re-parsing of the created manifest, the public
``validate`` command and exact before/after directory snapshots including
absent parent directories — never values copied from implementation output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from lumio_wiki import cli
from lumio_wiki.env_loader import (
    GIT_REMOTE_ENV_VAR,
    GIT_TARGET_BRANCH_ENV_VAR,
    KB_PATH_ENV_VAR,
    SUBMISSION_MODE_ENV_VAR,
)
from lumio_wiki.knowledge_base import seeded_control_file, write_control_file
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    parse_source_reference_manifest,
    serialize_source_reference_manifest,
)

NAMESPACE = "urn:uuid:9a3e2b71-4c5d-4e8f-a0b1-6d2c7e9f4a55"
OTHER_NAMESPACE = "urn:uuid:1b2a3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
BRANCH = "main"


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


def _init_repo(path: Path, *, branch: str = BRANCH) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    _git(path, "config", "user.email", "setup-creator@example.com")
    _git(path, "config", "user.name", "Setup Creator")
    return path


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


def _env_value(env_path: Path, key: str) -> str | None:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def _setup_argv(target: Path, profile: Path, *, namespace: str | None = NAMESPACE) -> list[str]:
    argv = ["setup", str(target), "--journey", "--create-empty", "--private-profile", str(profile)]
    if namespace is not None:
        argv += ["--namespace", namespace]
    return argv


# ---------------------------------------------------------------------------
# V5a family 1: preview, confirm, retry — headless and interactive.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "location"),
    [
        ("headless", "unborn-subtree"),
        ("headless", "git-only-root"),
        ("headless", "committed-subtree"),
        ("interactive", "fresh-profile"),
    ],
)
def test_empty_journey_setup_preview_confirm_and_retry(
    mode, location, tmp_path: Path, monkeypatch, capsys
):
    """Preview writes nothing; confirmation creates exactly the previewed
    files whose manifest parses with the exact namespace and empty maps;
    retry never reinitializes; native Git still owns commits."""
    repo = _init_repo(tmp_path / "project")
    target = repo if location == "git-only-root" else repo / "kb"
    head_before: str | None = None
    preview: dict = {}
    argv: list[str] = []
    if location == "committed-subtree":
        (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        head_before = _commit(repo, "project base")
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")

    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    # A repository-root KB target would be polluted by project files if setup
    # ran from inside it; the operator runs it from a neutral work dir.
    work_dir = tmp_path / "work"
    if location == "git-only-root":
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)
    project_root = work_dir if location == "git-only-root" else repo
    if mode == "interactive":
        # The profile file is deliberately absent: the wizard collects its
        # declaration before the preview, and the file itself is written only
        # inside the confirmed apply.
        profile = private / "collected.json"
        assert not profile.exists()
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        answers = iter([NAMESPACE, "", "", "", "", "", "y"])

        def answer(prompt: str) -> str:
            if "Apply exactly this setup" in prompt:
                # Mid-flight oracle: the preview answered 'y' here wrote
                # nothing yet — no target, no .env, no profile file.
                assert not target.exists()
                assert not (repo / ".env").exists()
                assert not profile.exists()
                return "y"
            return next(answers)

        monkeypatch.setattr("builtins.input", lambda prompt="": answer(prompt))
        rc = cli.main(_setup_argv(target, profile, namespace=None))
        assert rc == 0
        out = capsys.readouterr().out
        assert "preview; nothing written yet" in out
        assert str(profile) in out  # the profile write is a previewed action
        # The collected declaration is written exactly once, on apply.
        payload = json.loads(profile.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["namespace"] == NAMESPACE
        assert payload["retention"] == "required"
        assert payload["source_registry"] == str(
            (home / ".lumio" / "registries" / NAMESPACE).resolve()
        )
        assert not (home / ".lumio").exists()  # no registry/store created
        agents_md = (repo / "AGENTS.md").read_text(encoding="utf-8")
        assert str(profile) not in agents_md
        assert str(home / ".lumio") not in agents_md
        assert _env_value(repo / ".env", GIT_REMOTE_ENV_VAR) == "origin"
        assert _env_value(repo / ".env", GIT_TARGET_BRANCH_ENV_VAR) is None
    else:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        argv = _setup_argv(target, profile) + ["--json"]
        before = _snapshot(tmp_path)
        rc = cli.main(argv)
        assert rc == 0
        preview = json.loads(capsys.readouterr().out)
        # The frozen creation-only envelope (plan J5a), from the plan fields.
        assert preview["schema_version"] == 1
        assert preview["ok"] is True
        assert preview["operation"] == "setup_empty"
        assert preview["phase"] == "preview"
        assert preview["ready"] is True
        assert preview["namespace"] == NAMESPACE
        assert preview["blockers"] == []
        assert preview["next_actions"]
        assert preview["authoring"]["repository_root"] == str(repo)
        assert preview["authoring"]["branch"] == BRANCH
        assert preview["authoring"]["subtree"] == ("" if location == "git-only-root" else "kb")
        if location == "committed-subtree":
            assert preview["authoring"]["unborn"] is False
            assert preview["authoring"]["current_commit"] == head_before
        else:
            assert preview["authoring"]["unborn"] is True
            assert preview["authoring"]["current_commit"] is None
        kinds = [action["kind"] for action in preview["actions"]]
        assert "create-control-file" in kinds
        assert "create-manifest" in kinds
        manifest_action = next(a for a in preview["actions"] if a["kind"] == "create-manifest")
        assert manifest_action["path"].endswith(SOURCE_REFERENCE_MANIFEST_BASENAME)
        assert manifest_action["content_sha256"]
        assert len(preview["setup_digest"]) == 64
        int(preview["setup_digest"], 16)  # digest is hexadecimal
        # The preview is read-only: byte-for-byte nothing changed.
        assert _snapshot(tmp_path) == before

        rc = cli.main([*argv, "--confirm", preview["setup_digest"]])
        assert rc == 0
        applied = json.loads(capsys.readouterr().out)
        assert applied["phase"] == "applied"
        assert applied["setup_digest"] == preview["setup_digest"]

    # Created content oracle: strict re-parse of the authored manifest bytes.
    manifest = parse_source_reference_manifest(
        (target / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
    )
    assert manifest.version == 1
    assert manifest.namespace == NAMESPACE
    assert manifest.sources == {}
    assert manifest.bindings == {}
    assert (target / "lumio.yaml").is_file()
    expected_entries = sorted(
        [".git", ".lumio-authoring.yaml", "lumio.yaml"]
        if location == "git-only-root"
        else [".lumio-authoring.yaml", "lumio.yaml"]
    )
    assert sorted(entry.name for entry in target.iterdir()) == expected_entries
    # Machine settings: the created KB is the project KB; local-commit default.
    env = project_root / ".env"
    assert _env_value(env, KB_PATH_ENV_VAR) == str(target)
    assert _env_value(env, SUBMISSION_MODE_ENV_VAR) == "commit"
    # Private history stays empty and outside.
    assert not (private / "r1").exists()
    # Normal KB validation passes (public oracle on the real artifact).
    assert cli.main(["validate", str(target)]) == 0
    capsys.readouterr()  # drain validate's human report before later JSON parses

    # Native Git owns commits: unborn stays unborn, HEAD never moves, and the
    # created files are plain untracked content — nothing staged or committed.
    if location == "committed-subtree":
        assert _git(repo, "rev-parse", "HEAD") == head_before
    else:
        head_probe = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True
        )
        assert head_probe.returncode != 0
    for line in _git(repo, "status", "--porcelain").splitlines():
        assert line.startswith("??"), line

    if preview:
        # Headless cells only (interactive confirms within its single run
        # above): retry with the same confirmation refuses over the created
        # KB and preserves it byte-for-byte (never reinitialized).
        snapshot_after = _snapshot(tmp_path)
        rc = cli.main([*argv, "--confirm", preview["setup_digest"]])
        assert rc == 2
        refused = json.loads(capsys.readouterr().out)
        assert refused["ok"] is False
        assert refused["error"]["code"] == "invalid_empty_setup"
        assert _snapshot(tmp_path) == snapshot_after
        if location == "unborn-subtree":
            # Selecting the matching existing managed KB continues ordinary
            # journey setup without touching the created content.
            manifest_bytes = (target / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
            control_bytes = (target / "lumio.yaml").read_bytes()
            rc = cli.main(["setup", str(target), "--journey", "--private-profile", str(profile)])
            assert rc == 0
            capsys.readouterr()
            assert (target / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes() == manifest_bytes
            assert (target / "lumio.yaml").read_bytes() == control_bytes
            assert not (private / "r1").exists()


# ---------------------------------------------------------------------------
# V5a family 2: invalid or stale selections refuse before any write.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "want_rc", "want_code"),
    [
        ("declined_confirmation", 1, None),
        ("missing_namespace", 2, "invalid_empty_setup"),
        ("blank_namespace", 2, "invalid_empty_setup"),
        ("profile_namespace_mismatch", 2, "invalid_private_profile"),
        ("profile_inside_repository", 2, "invalid_private_profile"),
        ("nonempty_target_stray_file", 2, "adoption_required"),
        ("pages_without_manifest", 2, "adoption_required"),
        ("stale_confirmation_changed_profile", 2, "setup_confirmation_mismatch"),
        ("newly_occupied_target", 2, "adoption_required"),
        ("existing_managed_namespace_conflict", 2, "invalid_empty_setup"),
        ("target_is_file", 2, "invalid_empty_setup"),
        ("detached_head", 2, "invalid_empty_setup"),
        ("bare_repository", 2, "invalid_empty_setup"),
        ("outside_repository", 2, "invalid_empty_setup"),
    ],
)
def test_empty_journey_setup_refuses_without_writes(
    case, want_rc, want_code, tmp_path: Path, monkeypatch, capsys
):
    """Every refusal leaves the whole tree byte-for-byte unchanged, including
    absent parent directories; expected results come from §2.2's rules and
    the pre-call fixture facts."""
    monkeypatch.chdir(tmp_path)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    argv = _setup_argv(target, profile) + ["--json"]
    digest: str | None = None

    if case == "declined_confirmation":
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        answers = iter(["", "", "", "n"])

        def answer(prompt: str) -> str:
            if "Apply exactly this setup" in prompt:
                return "n"
            return next(answers)

        monkeypatch.setattr("builtins.input", lambda prompt="": answer(prompt))
        argv = _setup_argv(target, profile)
    elif case == "missing_namespace":
        argv = _setup_argv(target, profile, namespace=None) + ["--json"]
    elif case == "blank_namespace":
        argv = _setup_argv(target, profile, namespace="   ") + ["--json"]
    elif case == "profile_namespace_mismatch":
        profile = _write_profile(
            private / "other.json", namespace=OTHER_NAMESPACE, registry=private / "r2"
        )
        argv = _setup_argv(target, profile) + ["--json"]
    elif case == "profile_inside_repository":
        inside = repo / "private-profile.json"
        _write_profile(inside, namespace=NAMESPACE, registry=private / "r3")
        argv = _setup_argv(target, inside) + ["--json"]
    elif case == "nonempty_target_stray_file":
        target.mkdir(parents=True)
        (target / "stray.txt").write_text("operator content\n", encoding="utf-8")
    elif case == "pages_without_manifest":
        (target / "concepts").mkdir(parents=True)
        (target / "concepts" / "page.md").write_text("---\ntitle: T\n---\nbody\n", encoding="utf-8")
    elif case == "stale_confirmation_changed_profile":
        assert cli.main(argv) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        # The operator re-selects a different (valid) registry after seeing
        # the preview: the stale confirmation no longer authorizes the state.
        _write_profile(profile, namespace=NAMESPACE, registry=private / "r4")
        argv = [*argv, "--confirm", digest]
    elif case == "newly_occupied_target":
        assert cli.main(argv) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        target.mkdir(parents=True)
        (target / "appeared.txt").write_text("appeared meanwhile\n", encoding="utf-8")
        argv = [*argv, "--confirm", digest]
    elif case == "existing_managed_namespace_conflict":
        target.mkdir(parents=True)
        write_control_file(target, seeded_control_file())
        (target / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
            serialize_source_reference_manifest(
                SourceReferenceManifest(version=1, namespace=OTHER_NAMESPACE)
            )
        )
    elif case == "target_is_file":
        target.write_text("a regular file\n", encoding="utf-8")
    elif case == "detached_head":
        (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        _commit(repo, "base")
        _git(repo, "checkout", "-q", "--detach")
    elif case == "bare_repository":
        bare = tmp_path / "origin.git"
        bare.mkdir()
        _git(bare, "init", "-q", "--bare")
        target = bare
        argv = _setup_argv(target, profile) + ["--json"]
    elif case == "outside_repository":
        target = tmp_path / "plain" / "kb"
        argv = _setup_argv(target, profile) + ["--json"]

    before = _snapshot(tmp_path)
    rc = cli.main(argv)
    assert rc == want_rc
    captured = capsys.readouterr()
    if want_code is not None:
        refused = json.loads(captured.out)
        assert refused["ok"] is False
        assert refused["error"]["code"] == want_code
    else:
        assert "nothing was written" in captured.err
    # No setup writes anywhere: identical bytes, absent parents stay absent.
    assert _snapshot(tmp_path) == before


# ---------------------------------------------------------------------------
# V5a: honest incomplete reporting at the actual filesystem I/O seam.
# ---------------------------------------------------------------------------


def test_empty_setup_io_failure_reports_incomplete_residue(tmp_path: Path, monkeypatch, capsys):
    """A write failure mid-apply reports the incomplete setup and its
    operation-owned residue; pre-existing operator content and the private
    profile are preserved byte-for-byte."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    operator_file = repo / "operator-notes.txt"
    operator_bytes = b"pre-existing operator content\n"
    operator_file.write_bytes(operator_bytes)
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    argv = _setup_argv(target, profile) + ["--json"]
    assert cli.main(argv) == 0
    digest = json.loads(capsys.readouterr().out)["setup_digest"]
    profile_bytes = profile.read_bytes()

    # One narrow injection at the real I/O seam: the manifest write fails
    # after the Control File was already written (honest residue to report).
    real_write_bytes = Path.write_bytes

    def failing_write_bytes(self, data):
        if self.name == SOURCE_REFERENCE_MANIFEST_BASENAME:
            raise OSError(28, "No space left on device")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write_bytes)
    rc = cli.main([*_setup_argv(target, profile), "--confirm", digest])
    monkeypatch.setattr(Path, "write_bytes", real_write_bytes)
    assert rc == 2
    err = capsys.readouterr().err
    assert "I/O failure" in err
    assert str(target / "lumio.yaml") in err  # the residue is named

    # Incomplete, never success: control file written, manifest absent, no
    # project configuration; operator content and profile untouched.
    assert (target / "lumio.yaml").is_file()
    assert not (target / SOURCE_REFERENCE_MANIFEST_BASENAME).exists()
    assert not (repo / ".env").exists()
    assert not (repo / "AGENTS.md").exists()
    assert operator_file.read_bytes() == operator_bytes
    assert profile.read_bytes() == profile_bytes
    # A retry never reinitializes: the occupied-incomplete target is refused
    # with recovery guidance rather than silently completed over.
    rc = cli.main([*_setup_argv(target, profile), "--confirm", digest, "--json"])
    assert rc == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["error"]["code"] == "adoption_required"
