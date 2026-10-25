"""Confirmed empty managed-KB creation (spec 0010 §2.2/AC12, plan 0010 J5a/V5a).

Two compact families at the public setup CLI seam plus one narrow I/O-failure
injection. Oracles are hand-authored facts: the fixture namespace and topology,
native Git state, strict re-parsing of the created manifest, the public
``validate`` command and exact before/after directory snapshots including
absent parent directories — never values copied from implementation output.
"""

from __future__ import annotations

import io
import json
import os
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
from lumio_wiki.skill import SKILL_FILENAME, install_skill, skill_status
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceError,
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


# ---------------------------------------------------------------------------
# Review regression families (R1–R6, parent disposition 2026-10-25).
# ---------------------------------------------------------------------------


def _tree_snapshot(root: Path) -> dict[str, bytes | str]:
    """Files by bytes PLUS directory and symlink identity, so absence of
    parent directories and unchanged symlink targets are provable."""
    state: dict[str, bytes | str] = {}
    for entry in sorted(root.rglob("*")):
        relative = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            state[relative] = "symlink:" + os.readlink(entry)
        elif entry.is_dir():
            state[relative] = "dir"
        elif entry.is_file():
            state[relative] = entry.read_bytes()
    return state


def _interactive(monkeypatch, answers: dict[str, str]) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    def answer(prompt: str) -> str:
        for marker, value in answers.items():
            if marker in prompt:
                return value
        return ""

    monkeypatch.setattr("builtins.input", lambda prompt="": answer(prompt))


@pytest.mark.parametrize("case", ["missing-inside-path", "dangling-inside-symlink"])
def test_empty_setup_new_profile_location_is_validated_before_writes(
    case, tmp_path: Path, monkeypatch, capsys
):
    """R1: a NEW interactive profile destination inside the content
    repository is refused before ANY write — parent directories included —
    independent of the apply answer; symlink/operator bytes untouched."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    # A real existing OUTSIDE registry/store pair; the interactive selection
    # proposes a NEW profile at an inside-repository destination.
    outside_registry = tmp_path / "outside-registry"
    outside_store = tmp_path / "outside-store"
    if case == "missing-inside-path":
        selected: Path = repo / "private" / "new-profile.json"
        assert not selected.parent.exists()
    else:
        inside = repo / "inside" / "new-profile.json"
        selected = tmp_path / "link-to-inside.json"
        os.symlink(str(inside), str(selected))
        assert not inside.parent.exists()
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    _interactive(
        monkeypatch,
        {
            "Private Source Registry directory": str(outside_registry),
            "Private artifact store directory": str(outside_store),
            "Apply exactly this setup": "y",  # refusal must not depend on cancel
        },
    )
    argv = [
        "setup",
        str(target),
        "--journey",
        "--create-empty",
        "--namespace",
        NAMESPACE,
        "--private-profile",
        str(selected),
    ]
    before = _tree_snapshot(tmp_path)
    rc = cli.main(argv)
    captured = capsys.readouterr()
    assert rc == 2
    combined = captured.out + captured.err
    assert "outside" in combined or "content repository" in combined
    # Bounded refusal BEFORE any setup write: no created parents, no KB, no
    # project configuration anywhere.
    assert _tree_snapshot(tmp_path) == before
    if case == "dangling-inside-symlink":
        inside_link = str(repo / "inside" / "new-profile.json")
        assert selected.is_symlink() and os.readlink(selected) == inside_link


@pytest.mark.parametrize(
    "case",
    [
        "skill-modified-after-overwrite-preview",
        "overwrite-added-at-confirmation",
        "agent-pi-destination-preview",
    ],
)
def test_empty_setup_skill_confirmation_binds_selection_and_state(
    case, tmp_path: Path, monkeypatch, capsys
):
    """R2: the selected skill action is bound to the preview — intervening
    skill-byte changes or a confirmation-time --overwrite addition refuse
    before writes; an agent destination preview names the real target."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    if case == "agent-pi-destination-preview":
        pi_target = install_skill(agent="pi", home=home)  # real native target
        skill_file = pi_target / SKILL_FILENAME
        argv = [
            "setup",
            str(target),
            "--journey",
            "--create-empty",
            "--namespace",
            NAMESPACE,
            "--private-profile",
            str(profile),
            "--agent",
            "pi",
        ]
        before = _tree_snapshot(tmp_path)
        rc = cli.main(argv)
        assert rc == 0
        out = capsys.readouterr().out
        # The preview must identify the ACTUAL destination, not the project dir.
        assert str(pi_target) in out
        # Destination preview writes nothing and fabricates no expected bytes.
        assert _tree_snapshot(tmp_path) == before
        return
    skill_target = install_skill(scope="user", home=home)
    skill_file = skill_target / SKILL_FILENAME
    base_argv = [
        "setup",
        str(target),
        "--journey",
        "--create-empty",
        "--namespace",
        NAMESPACE,
        "--private-profile",
        str(profile),
        "--skill-scope",
        "user",
    ]
    if case == "skill-modified-after-overwrite-preview":
        assert cli.main([*base_argv, "--overwrite", "--json"]) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        # The operator edits the installed skill AFTER seeing the preview.
        marker = b"\n# local operator edit after preview R2\n"
        skill_file.write_bytes(skill_file.read_bytes() + marker)
        modified_bytes = skill_file.read_bytes()
        rc = cli.main([*base_argv, "--overwrite", "--confirm", digest, "--json"])
    else:
        marker = b"\n# local operator edit before preview R2\n"
        skill_file.write_bytes(skill_file.read_bytes() + marker)
        modified_bytes = skill_file.read_bytes()
        assert cli.main([*base_argv, "--json"]) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        # --overwrite appears only on the confirmation invocation.
        rc = cli.main([*base_argv, "--overwrite", "--confirm", digest, "--json"])
    assert rc == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["ok"] is False
    assert refused["error"]["code"] in ("setup_target_changed", "setup_confirmation_mismatch")
    # Refusal happened before writes: the changed local skill bytes survive
    # (independent read-back, not package bytes) and the target KB stays absent.
    assert skill_file.read_bytes() == modified_bytes
    assert not target.exists()
    assert not (repo / ".env").exists()
    assert not (repo / "AGENTS.md").exists()


@pytest.mark.parametrize("case", ["default-agents-at-kb-root", "project-skill-inside-kb"])
def test_empty_setup_refuses_guidance_inside_kb(case, tmp_path: Path, monkeypatch, capsys):
    """R3: planning refuses project guidance/skill destinations that land
    inside the selected repository-root KB, before any write, with an
    actionable alternate-location/flag remedy (§2.2 root topology)."""
    repo = _init_repo(tmp_path / "project")  # repository-root target, .git only
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    monkeypatch.chdir(repo)  # the normal same-directory invocation
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    argv = [
        "setup",
        str(repo),
        "--journey",
        "--create-empty",
        "--namespace",
        NAMESPACE,
        "--private-profile",
        str(profile),
    ]
    if case == "project-skill-inside-kb":
        argv += ["--no-agents-md", "--skill-scope", "project"]
    before = _tree_snapshot(tmp_path)
    rc = cli.main(argv)
    assert rc == 2
    err = capsys.readouterr().err
    if case == "default-agents-at-kb-root":
        assert "AGENTS.md" in err
        assert "--no-agents-md" in err or "outside" in err
    else:
        assert "skill" in err.lower()
        assert "--skill-scope" in err or "outside" in err.lower() or "--no-agents-md" in err
    # Refused before writes: the .git-only repository root stays .git-only.
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("destination", ["env", "agents-md"])
def test_empty_setup_preserves_existing_configuration_on_write_failure(
    destination, tmp_path: Path, monkeypatch, capsys
):
    """R4: a partial write failure on an EXISTING configuration file leaves
    its prior operator bytes identical (real I/O seam; content-triggered so
    same-dir temporary writes stay covered)."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    if destination == "env":
        config_path = repo / ".env"
        operator_bytes = b"OPERATOR_KEEP=marker-7f3a-unrelated\n"
        # Unique fixture content in the NEW .env write: the KB location line.
        unique_marker = (KB_PATH_ENV_VAR + "=").encode()
    else:
        config_path = repo / "AGENTS.md"
        operator_bytes = b"# operator notes - unrelated pre-existing content\n"
        # Unique fixture content in the NEW AGENTS write: the settled section marker.
        unique_marker = b"<!-- lumio-wiki-kb -->"
    config_path.write_bytes(operator_bytes)
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    argv = _setup_argv(target, profile) + ["--json"]
    assert cli.main(argv) == 0
    digest = json.loads(capsys.readouterr().out)["setup_digest"]

    # Delegating io.open wrapper: every real write delegates, except content
    # carrying the unique fixture marker — that write flushes a short prefix
    # through the real stream, then fails. Handles str/bytes, close/context.
    fired: list[bool] = []
    real_open = io.open

    class _PartialHandle:
        def __init__(self, handle) -> None:
            self._handle = handle

        def write(self, data):
            blob = (
                bytes(data)
                if isinstance(data, (bytes, bytearray, memoryview))
                else data.encode("utf-8", "replace")
            )
            if unique_marker in blob:
                fired.append(True)
                prefix = data[:4]
                self._handle.write(prefix)
                self._handle.flush()
                raise OSError(28, "No space left on device")
            return self._handle.write(data)

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()
            return False

    def partial_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if any(flag in mode for flag in ("w", "a", "x")):
            return _PartialHandle(handle)
        return handle

    monkeypatch.setattr(io, "open", partial_open)
    rc = cli.main([*_setup_argv(target, profile), "--confirm", digest])
    monkeypatch.setattr(io, "open", real_open)
    assert fired, "injection did not fire; the unique fixture content was not written"
    assert rc == 2
    assert "I/O failure" in capsys.readouterr().err
    # The pre-existing operator configuration survived the failed write.
    assert config_path.read_bytes() == operator_bytes


def test_empty_setup_malformed_manifest_retry_is_bounded(tmp_path: Path, monkeypatch, capsys):
    """R5: a real incomplete target with a malformed .lumio-authoring.yaml
    gets the bounded versioned refusal with recovery guidance on preview AND
    retry — never a raw parser exception — and nothing changes on disk."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    target.mkdir(parents=True)
    malformed = b"version: two\nnamespace: [[unterminated\nnot-a-manifest: {{{\n"
    (target / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(malformed)
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    before = _tree_snapshot(tmp_path)
    for _attempt in ("preview", "retry"):
        rc = cli.main(_setup_argv(target, profile) + ["--json"])
        captured = capsys.readouterr()
        assert rc == 2
        refused = json.loads(captured.out)
        assert refused["ok"] is False
        assert refused["error"]["code"] in ("invalid_empty_setup", "adoption_required")
        assert "SourceReferenceError" not in captured.out + captured.err
        assert (
            "recover" in captured.err.lower()
            or "adoption" in captured.err.lower()
            or "recovery" in refused["error"].get("message", "").lower()
        )
    assert _tree_snapshot(tmp_path) == before


def test_empty_setup_json_failure_discloses_actual_residue(tmp_path: Path, monkeypatch, capsys):
    """R6: a --json confirmation whose manifest write fails after real
    partial bytes emits the single bounded setup_incomplete envelope while
    stderr discloses the ACTUAL owned residue: the partial manifest file and
    operation-created parent directories (independent filesystem facts)."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "deep" / "nest" / "kb"  # initially absent nested parents
    assert not target.parent.parent.exists()
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    operator_file = repo / "operator-notes.txt"
    operator_bytes = b"operator content - must survive\n"
    operator_file.write_bytes(operator_bytes)
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    argv = _setup_argv(target, profile) + ["--json"]
    assert cli.main(argv) == 0
    digest = json.loads(capsys.readouterr().out)["setup_digest"]

    # Thin actual-I/O wrapper: the manifest write persists a real 16-byte
    # prefix, then fails.
    real_write_bytes = Path.write_bytes

    def partial_write_bytes(self, data):
        if self.name == SOURCE_REFERENCE_MANIFEST_BASENAME:
            real_write_bytes(self, data[:16])
            raise OSError(28, "No space left on device")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", partial_write_bytes)
    rc = cli.main([*_setup_argv(target, profile), "--confirm", digest, "--json"])
    monkeypatch.setattr(Path, "write_bytes", real_write_bytes)
    assert rc == 2
    captured = capsys.readouterr()
    # Exactly one bounded JSON error; the frozen envelope is unchanged.
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "setup_incomplete"
    # Independent filesystem facts: the partial manifest really exists as a
    # short non-parseable prefix, and the operation created the parents.
    partial_manifest = target / SOURCE_REFERENCE_MANIFEST_BASENAME
    assert partial_manifest.is_file()
    partial_bytes = partial_manifest.read_bytes()
    assert 0 < len(partial_bytes) < 64
    with pytest.raises(SourceReferenceError):
        parse_source_reference_manifest(partial_bytes)
    assert target.parent.is_dir() and target.parent.parent.is_dir()
    # The disclosed residue names the partial manifest and the created tree.
    assert str(partial_manifest) in captured.err
    assert str(target.parent) in captured.err
    # Operator content preserved byte-for-byte.
    assert operator_file.read_bytes() == operator_bytes


# ---------------------------------------------------------------------------
# Second delta-review regression families (owner-authorized, R1/R2/R4/R6).
# ---------------------------------------------------------------------------


def _inventory_segment(stderr: str, label: str) -> list[str]:
    """Exact discrete entries of one labeled residue segment (no prefix
    matching: each listed path must stand alone between separators). The
    literal 'none' placeholder the product prints for an EMPTY segment is
    not a path."""
    marker = f"{label}:"
    assert marker in stderr, f"missing labeled inventory segment '{marker}' in:\n{stderr}"
    segment = stderr.split(marker, 1)[1].split(";", 1)[0]
    return [
        entry.strip() for entry in segment.split(",") if entry.strip() and entry.strip() != "none"
    ]


def test_empty_setup_rechecks_profile_destination_before_writes(
    tmp_path: Path, monkeypatch, capsys
):
    """R1 delta: a destination occupied by a DIRECTORY during the open
    confirmation prompt refuses BEFORE any setup write; the operator's
    directory survives and absent-vs-occupied is never conflated."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    selected = tmp_path / "outside-choice" / "new-profile.json"  # absent, outside
    assert not selected.parent.exists()
    outside_registry = tmp_path / "registry"
    outside_store = tmp_path / "store"
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    operator_snapshot: dict = {}

    def answer(prompt: str) -> str:
        if "Apply exactly this setup" in prompt:
            # The operator creates a DIRECTORY at the proposed destination
            # while the confirmation prompt is open — deliberately not a
            # file, so unreadable-vs-absent conflation is exercised.
            selected.mkdir(parents=True)
            assert selected.is_dir()
            operator_snapshot["tree"] = _tree_snapshot(tmp_path)
            return "y"
        if "Private Source Registry directory" in prompt:
            return str(outside_registry)
        if "Private artifact store directory" in prompt:
            return str(outside_store)
        return ""

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": answer(prompt))
    rc = cli.main(
        [
            "setup",
            str(target),
            "--journey",
            "--create-empty",
            "--namespace",
            NAMESPACE,
            "--private-profile",
            str(selected),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "changed after the preview" in err
    # Bounded refusal BEFORE any setup write: the tree is identical to the
    # operator's own post-action state (directory preserved, no KB, no
    # project configuration, no created parents).
    assert _tree_snapshot(tmp_path) == operator_snapshot["tree"]
    assert selected.is_dir() and list(selected.iterdir()) == []


def test_empty_setup_binds_installed_skill_bundle_bytes(tmp_path: Path, monkeypatch, capsys):
    """R2 delta: installed bundle contents subject to replacement
    (PROTOCOL.md here, not just SKILL.md or the coarse status) are bound — a
    second distinct protocol edit during confirmation refuses before any
    write and the exact new operator bytes survive."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    skill_target = install_skill(scope="user", home=home)
    protocol = skill_target / "PROTOCOL.md"
    skill_file = skill_target / SKILL_FILENAME
    assert protocol.is_file() and skill_file.is_file()
    # First local edit: bundle no longer current (fixture guard).
    protocol.write_bytes(protocol.read_bytes() + b"\n# operator protocol edit A\n")
    status_before = skill_status(scope="user", home=home).state
    assert status_before != "current"
    skill_bytes = skill_file.read_bytes()
    base_argv = [
        "setup",
        str(target),
        "--journey",
        "--create-empty",
        "--namespace",
        NAMESPACE,
        "--private-profile",
        str(profile),
        "--skill-scope",
        "user",
        "--overwrite",
    ]
    assert cli.main([*base_argv, "--json"]) == 0
    digest = json.loads(capsys.readouterr().out)["setup_digest"]
    # Second DISTINCT protocol edit while the coarse status is unchanged.
    operator_bytes = protocol.read_bytes() + b"\n# operator protocol edit B (distinct)\n"
    protocol.write_bytes(operator_bytes)
    assert skill_status(scope="user", home=home).state == status_before
    assert skill_file.read_bytes() == skill_bytes  # SKILL.md untouched guard
    rc = cli.main([*base_argv, "--confirm", digest, "--json"])
    assert rc == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["ok"] is False
    assert refused["error"]["code"] in ("setup_target_changed", "setup_confirmation_mismatch")
    # The refusal preceded every write: the exact new operator bytes and the
    # untouched SKILL.md survive, and no setup target/config was created.
    assert protocol.read_bytes() == operator_bytes
    assert skill_file.read_bytes() == skill_bytes
    assert not target.exists()
    assert not (repo / ".env").exists()
    assert not (repo / "AGENTS.md").exists()


def test_empty_setup_preserves_env_after_atomic_publication(tmp_path: Path, monkeypatch, capsys):
    """R4 delta: after the confirmed .env bytes are published atomically, no
    later direct destination rewrite may truncate the file — unrelated
    operator facts survive complete, and the atomic publication is observed.
    On repaired code the redundant rewrite is absent; the injection firing
    is recorded but never required."""
    repo = _init_repo(tmp_path / "project")
    target = repo / "kb"
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    env_path = repo / ".env"
    env_path.write_bytes(b"OPERATOR_TOKEN=keep-123\nOPERATOR_NAME=acme\n")
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    argv = _setup_argv(target, profile) + ["--json"]
    assert cli.main(argv) == 0
    digest = json.loads(capsys.readouterr().out)["setup_digest"]

    # PATH-triggered at the real io.open seam: only a DIRECT destination
    # write of .env fails after a short real prefix; the atomic publication
    # writes through a same-dir temporary path and never trips this.
    fired: list[bool] = []
    real_open = io.open

    class _PrefixThenFail:
        def __init__(self, handle) -> None:
            self._handle = handle

        def write(self, data):
            fired.append(True)
            blob = bytes(data) if not isinstance(data, str) else data
            self._handle.write(blob[:4])
            self._handle.flush()
            raise OSError(28, "No space left on device")

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()
            return False

    def destination_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if (
            any(flag in mode for flag in ("w", "a", "x"))
            and isinstance(file, (str, os.PathLike))
            and Path(file) == env_path
        ):
            return _PrefixThenFail(handle)
        return handle

    monkeypatch.setattr(io, "open", destination_open)
    rc = cli.main([*_setup_argv(target, profile), "--confirm", digest, "--json"])
    monkeypatch.setattr(io, "open", real_open)
    assert rc in (0, 2)
    env_now = env_path.read_bytes()
    # Unrelated operator facts survive COMPLETE in every honest outcome.
    assert b"OPERATOR_TOKEN=keep-123" in env_now
    assert b"OPERATOR_NAME=acme" in env_now
    if rc == 0:
        # The atomic publication of the confirmed bytes is independently
        # observed: the intended values are present, complete.
        assert str(target).encode() in env_now
        assert KB_PATH_ENV_VAR.encode() + b"=" in env_now


@pytest.mark.parametrize(
    "case",
    [
        "deep-ancestors-manifest-failure",
        "partial-mkdir-failure",
        "updated-then-failed",
    ],
)
def test_empty_setup_reports_discrete_owned_residue(case, tmp_path, monkeypatch, capsys):
    """R6 delta: residue reporting distinguishes operation-CREATED paths
    (each absent ancestor listed discretely), UPDATED pre-existing operator
    files, and the possibly-partial failing path — fixed JSON envelope, safe
    local stderr, no prefix-matched pseudo-disclosure."""
    repo = _init_repo(tmp_path / "project")
    private = tmp_path / "private"
    profile = _write_profile(private / "profile.json", namespace=NAMESPACE, registry=private / "r1")
    monkeypatch.chdir(repo)
    _clean_lumio_env(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    env_path = repo / ".env"
    agents_path = repo / "AGENTS.md"
    if case == "deep-ancestors-manifest-failure":
        target = repo / "deep" / "nest" / "kb"
        deep = repo / "deep"
        nest = repo / "deep" / "nest"
        assert not deep.exists()  # pre-call absence facts
        argv = _setup_argv(target, profile) + ["--json"]
        assert cli.main(argv) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        real_write_bytes = Path.write_bytes

        def failing_write_bytes(self, data):
            if self.name == SOURCE_REFERENCE_MANIFEST_BASENAME:
                raise OSError(28, "No space left on device")
            return real_write_bytes(self, data)

        monkeypatch.setattr(Path, "write_bytes", failing_write_bytes)
        rc = cli.main([*_setup_argv(target, profile), "--confirm", digest, "--json"])
        monkeypatch.setattr(Path, "write_bytes", real_write_bytes)
        assert rc == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out)["error"]["code"] == "setup_incomplete"
        created = _inventory_segment(captured.err, "operation-created paths")
        # Every absent ancestor is listed as its OWN discrete entry.
        for created_path in (deep, nest, target, target / "lumio.yaml"):
            assert str(created_path) in created
        partial = _inventory_segment(captured.err, "possibly-partial path")
        assert str(target / SOURCE_REFERENCE_MANIFEST_BASENAME) in partial
        assert _inventory_segment(captured.err, "updated pre-existing operator files") == []
    elif case == "partial-mkdir-failure":
        target = repo / "deep2" / "nest2" / "kb"
        deep = repo / "deep2"
        nest = repo / "deep2" / "nest2"
        assert not deep.exists()
        argv = _setup_argv(target, profile) + ["--json"]
        assert cli.main(argv) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        real_mkdir = Path.mkdir

        def partial_mkdir(self, mode=0o777, parents=False, exist_ok=False):
            if parents and self == target:
                # Real creation of only the FIRST missing ancestor, then fail
                # (partial recursive directory creation).
                probe = target
                shallowest = target
                while not probe.exists() and probe != probe.parent:
                    shallowest = probe
                    probe = probe.parent
                real_mkdir(shallowest, parents=True, exist_ok=True)
                raise OSError(28, "No space left on device")
            return real_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

        monkeypatch.setattr(Path, "mkdir", partial_mkdir)
        rc = cli.main([*_setup_argv(target, profile), "--confirm", digest, "--json"])
        monkeypatch.setattr(Path, "mkdir", real_mkdir)
        assert rc == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out)["error"]["code"] == "setup_incomplete"
        # Observed filesystem facts: the first ancestor exists, deeper ones
        # were never created.
        assert deep.is_dir()
        assert not nest.exists() and not target.exists()
        created = _inventory_segment(captured.err, "operation-created paths")
        assert str(deep) in created
        assert str(nest) not in created and str(target) not in created
        partial = _inventory_segment(captured.err, "possibly-partial path")
        assert str(target) in partial
        assert _inventory_segment(captured.err, "updated pre-existing operator files") == []
    else:
        target = repo / "kb"
        env_bytes = b"OPERATOR_KEEP=marker-4c\n"
        agents_bytes = b"# operator notes 4c\n"
        env_path.write_bytes(env_bytes)
        agents_path.write_bytes(agents_bytes)
        argv = _setup_argv(target, profile) + ["--json"]
        assert cli.main(argv) == 0
        digest = json.loads(capsys.readouterr().out)["setup_digest"]
        real_open = io.open
        fired: list[bool] = []

        class _FailOnAgents:
            def __init__(self, handle) -> None:
                self._handle = handle

            def write(self, data):
                blob = (
                    bytes(data)
                    if isinstance(data, (bytes, bytearray, memoryview))
                    else data.encode("utf-8", "replace")
                )
                if b"<!-- lumio-wiki-kb -->" in blob:
                    fired.append(True)
                    prefix = data[:4]
                    self._handle.write(prefix)
                    self._handle.flush()
                    raise OSError(28, "No space left on device")
                return self._handle.write(data)

            def __getattr__(self, name):
                return getattr(self._handle, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                self._handle.close()
                return False

        def agents_content_open(file, mode="r", *args, **kwargs):
            handle = real_open(file, mode, *args, **kwargs)
            if any(flag in mode for flag in ("w", "a", "x")):
                return _FailOnAgents(handle)
            return handle

        monkeypatch.setattr(io, "open", agents_content_open)
        rc = cli.main([*_setup_argv(target, profile), "--confirm", digest, "--json"])
        monkeypatch.setattr(io, "open", real_open)
        assert fired
        assert rc == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out)["error"]["code"] == "setup_incomplete"
        created = _inventory_segment(captured.err, "operation-created paths")
        for created_path in (
            target,
            target / "lumio.yaml",
            target / SOURCE_REFERENCE_MANIFEST_BASENAME,
        ):
            assert str(created_path) in created
        updated = _inventory_segment(captured.err, "updated pre-existing operator files")
        assert str(env_path) in updated  # pre-existing, successfully updated
        assert str(agents_path) not in updated  # it failed, not updated
        partial = _inventory_segment(captured.err, "possibly-partial path")
        assert str(agents_path) in partial
        # The updated .env holds the complete intended values plus operator
        # facts; the failed AGENTS destination keeps its operator bytes.
        assert b"OPERATOR_KEEP=marker-4c" in env_path.read_bytes()
        assert str(target).encode() in env_path.read_bytes()
        assert agents_path.read_bytes() == agents_bytes
