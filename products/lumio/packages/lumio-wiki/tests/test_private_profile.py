"""Explicit private source profile selection (spec 0010 §2.1, plan 0010 JP).

Independent oracle: the approved §2.1 contract plus hand-authored fixtures —
a fixed namespace, fixed local directories, a fixed S3 endpoint/region and
distinct credential environment variable names. Expected bindings and
digests are computed in the test from the approved canonical-JSON SHA-256
rule; nothing is copied from implementation output. S3 checks stop at
explicit client construction (existing adapter transport behavior); no S3
I/O is performed or duplicated here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from lumio_wiki.artifact_store import LocalDirectoryArtifactStore, S3ArtifactStore
from lumio_wiki.cli import main
from lumio_wiki.private_profile import (
    PrivateProfileError,
    ResolvedS3Exchange,
    load_private_profile,
    resolve_private_profile,
)
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry

NAMESPACE = "urn:uuid:7d4448a4-1111-4b2c-8f0e-0f6f0e3e1a2b"
ACCESS_KEY_ENV = "JP_TEST_ACCESS_KEY_ID"
SECRET_KEY_ENV = "JP_TEST_SECRET_ACCESS_KEY"

RAW_MANUAL = b"Press the green button for exactly three seconds."
RAW_MANUAL_DIGEST = hashlib.sha256(RAW_MANUAL).hexdigest()

CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    press:
      description: "A machine that presses materials."
    material: {}
  predicates:
    presses:
      subject_types:
        - press
      object_types:
        - material
    rated-at:
      subject_types:
        - press
      literal_kind: string
"""

_PRESS_CLAIM = """\
claims:
  - id: claim:base-presses
    predicate: presses
    object: "entity:steel-blank"
    status: accepted
    evidence:
      - section: "Overview"
"""


def _base_page(title: str, entity_id: str, entity_type: str, slug: str, *, claims: str) -> str:
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        f"entity_types:\n  - {entity_type}\n"
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        f'  - id: "src-{slug}"\n    title: "{title} Source"\n'
        f"{claims}"
        "---\n\n"
        f"# {title}\n\n## Overview\n\nOverview paragraph.\n"
    )


COMPILED_PAGE = """\
---
id: "entity:workbench-press"
title: "Workbench Press"
entity_types:
  - press
category: concepts
type: "machine page"
durability_rationale: "The workshop manual documents this machine permanently."
tags:
  - "workshop"
summary: "The workbench press described by the operator manual."
lifecycle: "draft"
visibility: "internal"
sources:
  - id: "operator-manual"
    title: "Operator manual"
claims:
  - id: claim:workbench-rated
    predicate: rated-at
    value: "5 tons"
    value_type: string
    status: accepted
    evidence:
      - section: "Overview"
synthetic: false
---

# Workbench Press

## Overview

Rated at five tons per the operator manual.
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "author@example.test")
    _git(repo, "config", "user.name", "Profile Test Author")
    return repo


def _write_kb(repo: Path) -> Path:
    """An adopted, committed authoring KB with the fixed test namespace."""
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _base_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            "press",
            "hydraulic-press",
            claims=_PRESS_CLAIM,
        )
    )
    (kb / "concepts" / "steel-blank.md").write_text(
        _base_page("Steel Blank", "entity:steel-blank", "material", "steel-blank", claims="")
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline authoring revision")
    return kb


def _subdir(tmp_path: Path, name: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    return directory


def _profile_dict(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "namespace": NAMESPACE,
        "source_registry": str(tmp_path / "private" / "registry"),
        "retention": "required",
        "artifact_store": {
            "kind": "local",
            "root": str(tmp_path / "private" / "artifacts"),
        },
        "exchange": {
            "kind": "s3",
            "bucket": "jp-test-exchange",
            "prefix": "transfers",
            "endpoint": "http://127.0.0.1:9000",
            "region": "us-east-1",
            "url_style": "path",
            "credentials": {
                "access_key_id_env": ACCESS_KEY_ENV,
                "secret_access_key_env": SECRET_KEY_ENV,
            },
        },
    }


def _write_profile(directory: Path, profile: dict) -> Path:
    path = directory / "jp-profile.json"
    path.write_text(json.dumps(profile, indent=2))
    return path


def _load(tmp_path: Path, name: str, profile: dict, kb: Path):
    return load_private_profile(_write_profile(_subdir(tmp_path, name), profile), kb_root=kb)


def _canonical_digest(record: dict) -> str:
    """The approved digest rule: canonical JSON (sorted keys, compact
    separators, UTF-8) SHA-256 — computed here as the independent oracle."""
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_profile_selection_is_explicit_and_operation_scoped(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    profile = _load(tmp_path, "profiles", _profile_dict(tmp_path), kb)

    registry_root = (tmp_path / "private" / "registry").resolve()
    artifacts_root = (tmp_path / "private" / "artifacts").resolve()
    assert profile.source_registry == registry_root
    assert profile.artifact_store.root == artifacts_root
    assert profile.retention == "required"
    assert profile.exchange is not None and profile.exchange.bucket == "jp-test-exchange"

    # Registry-only bootstrap: no artifact/exchange access, so unavailable S3
    # credentials cannot matter (§2.1 "resolve only connections needed").
    registry_only = resolve_private_profile(
        profile, kb_root=kb, needs=frozenset({"registry"}), environ={}
    )
    assert isinstance(registry_only.source_registry, SourceRegistry)
    assert registry_only.source_registry.root == registry_root
    assert registry_only.artifact_store is None
    assert registry_only.exchange is None
    assert registry_only.retention_required is True
    expected_registry_binding = {
        "schema_version": 1,
        "namespace": NAMESPACE,
        "retention": "required",
        "source_registry": {"kind": "local", "root": str(registry_root)},
    }
    assert registry_only.binding == expected_registry_binding
    assert registry_only.binding_digest == _canonical_digest(expected_registry_binding)

    # Requested local artifacts resolve to the exact selected path without
    # any credential environment.
    with_artifacts = resolve_private_profile(
        profile, kb_root=kb, needs=frozenset({"registry", "artifacts"}), environ={}
    )
    assert isinstance(with_artifacts.artifact_store, LocalDirectoryArtifactStore)
    assert with_artifacts.artifact_store.root == artifacts_root
    expected_artifacts_binding = dict(expected_registry_binding)
    expected_artifacts_binding["artifact_store"] = {"kind": "local", "root": str(artifacts_root)}
    assert with_artifacts.binding == expected_artifacts_binding
    assert with_artifacts.binding_digest == _canonical_digest(expected_artifacts_binding)

    # Exchange resolution constructs the existing adapter from declared
    # variables only; rotating the credential VALUES never changes the
    # binding digest, a different endpoint always does.
    credentials_one = {ACCESS_KEY_ENV: "key-one", SECRET_KEY_ENV: "secret-one"}
    credentials_two = {ACCESS_KEY_ENV: "key-two", SECRET_KEY_ENV: "secret-two"}
    exchange_one = resolve_private_profile(
        profile, kb_root=kb, needs=frozenset({"exchange"}), environ=credentials_one
    )
    assert isinstance(exchange_one.exchange, ResolvedS3Exchange)
    assert exchange_one.exchange.prefix == "transfers"
    exchange_two = resolve_private_profile(
        profile, kb_root=kb, needs=frozenset({"exchange"}), environ=credentials_two
    )
    assert exchange_two.binding_digest == exchange_one.binding_digest
    expected_exchange_binding = {
        "schema_version": 1,
        "namespace": NAMESPACE,
        "retention": "required",
        "exchange": {
            "kind": "s3",
            "bucket": "jp-test-exchange",
            "prefix": "transfers",
            "endpoint": "http://127.0.0.1:9000",
            "region": "us-east-1",
            "url_style": "path",
            "credentials": {
                "access_key_id_env": ACCESS_KEY_ENV,
                "secret_access_key_env": SECRET_KEY_ENV,
            },
        },
    }
    assert exchange_one.binding == expected_exchange_binding
    assert exchange_one.binding_digest == _canonical_digest(expected_exchange_binding)

    other_endpoint = _profile_dict(tmp_path)
    assert other_endpoint["exchange"] is not None
    other_endpoint["exchange"]["endpoint"] = "https://s3-other.example.test"
    other = resolve_private_profile(
        _load(tmp_path, "other", other_endpoint, kb),
        kb_root=kb,
        needs=frozenset({"exchange"}),
        environ=credentials_one,
    )
    assert other.binding_digest != exchange_one.binding_digest

    # Missing declared credentials refuse — safely: the error names the
    # declared variables, never a credential value.
    with pytest.raises(PrivateProfileError) as missing_exchange:
        resolve_private_profile(profile, kb_root=kb, needs=frozenset({"exchange"}), environ={})
    message = str(missing_exchange.value)
    assert ACCESS_KEY_ENV in message and SECRET_KEY_ENV in message
    assert "key-one" not in message and "secret-one" not in message

    s3_store = _profile_dict(tmp_path)
    s3_store["artifact_store"] = dict(s3_store["exchange"])
    s3_store_profile = _load(tmp_path, "s3store", s3_store, kb)
    with pytest.raises(PrivateProfileError) as missing_store:
        resolve_private_profile(
            s3_store_profile, kb_root=kb, needs=frozenset({"artifacts"}), environ={}
        )
    assert ACCESS_KEY_ENV in str(missing_store.value)
    resolved_s3_store = resolve_private_profile(
        s3_store_profile, kb_root=kb, needs=frozenset({"artifacts"}), environ=credentials_one
    )
    assert isinstance(resolved_s3_store.artifact_store, S3ArtifactStore)

    # An operation needing an exchange the profile does not declare refuses.
    manual_only = _profile_dict(tmp_path)
    del manual_only["exchange"]
    manual_profile = _load(tmp_path, "manual", manual_only, kb)
    with pytest.raises(PrivateProfileError):
        resolve_private_profile(
            manual_profile, kb_root=kb, needs=frozenset({"exchange"}), environ=credentials_one
        )


def _set_exchange_endpoint(url: str):
    def mutate(profile: dict) -> None:
        assert profile["exchange"] is not None
        profile["exchange"]["endpoint"] = url

    return mutate


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        pytest.param(lambda p: p.update(schema_version=2), "schema_version", id="unknown-version"),
        pytest.param(
            lambda p: p.update(schema_version="1"), "schema_version", id="version-wrong-type"
        ),
        pytest.param(
            lambda p: p.update(source_exchange="s3://example/transfer"),
            "unknown private profile field",
            id="unknown-field",
        ),
        pytest.param(
            lambda p: p.update(namespace="urn:uuid:00000000-0000-0000-0000-000000000000"),
            "does not match",
            id="namespace-mismatch",
        ),
        pytest.param(
            lambda p: p.update(namespace=[]),
            "namespace must be a non-empty string",
            id="namespace-wrong-type",
        ),
        pytest.param(
            lambda p: p["exchange"]["credentials"].update(access_key_id="AKIAEXAMPLE"),
            "inline credential values",
            id="inline-credential",
        ),
        pytest.param(
            _set_exchange_endpoint("https://akid:secret@s3.example.test"),
            "must not carry credentials",
            id="credential-bearing-url",
        ),
        pytest.param(
            _set_exchange_endpoint("https://s3.example.test?X-Amz-Credential=abc"),
            "must not carry credentials",
            id="endpoint-query",
        ),
        pytest.param(
            lambda p: p.update(source_registry="private/registry"),
            "absolute directory path",
            id="relative-registry",
        ),
        pytest.param(
            lambda p: p["artifact_store"].update(root="artifacts"),
            "absolute directory path",
            id="relative-store-root",
        ),
        pytest.param(
            lambda p: p.update(retention="optional"), "retention must be one of", id="retention"
        ),
        pytest.param(
            lambda p: p.update(exchange={"kind": "local", "root": str(p["source_registry"])}),
            "exchange",
            id="exchange-local-kind",
        ),
        pytest.param(
            lambda p: p["artifact_store"].update(signature_version="s3v4"),
            "unknown artifact_store field",
            id="unknown-s3-field",
        ),
    ],
)
def test_private_profile_rejects_malformed_cases(tmp_path, mutate, fragment):
    """Named §2.1 refusals, parameterized from the contract, not the parser."""
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    profile = _profile_dict(tmp_path)
    mutate(profile)
    with pytest.raises(PrivateProfileError) as excinfo:
        load_private_profile(_write_profile(_subdir(tmp_path, "case"), profile), kb_root=kb)
    assert fragment in str(excinfo.value)


def test_private_profile_rejects_duplicate_json_keys(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    path = _subdir(tmp_path, "case") / "jp-profile.json"
    text = json.dumps(_profile_dict(tmp_path))
    path.write_text(text[:-1] + ', "retention": "disabled"}')
    with pytest.raises(PrivateProfileError) as excinfo:
        load_private_profile(path, kb_root=kb)
    assert "duplicate private profile key" in str(excinfo.value)


def test_private_profile_registry_must_stay_outside_the_repository(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    inside = _profile_dict(tmp_path)
    inside["source_registry"] = str(repo / "ignored-registry")
    with pytest.raises(PrivateProfileError) as excinfo:
        _load(tmp_path, "inside", inside, kb)
    assert "OUTSIDE the content repository" in str(excinfo.value)

    # A relative-looking selection that RESOLVES outside the repository is
    # legitimate (§2.1: resolve local paths before containment checks).
    escaping = _profile_dict(tmp_path)
    escaping["source_registry"] = str(repo / ".." / "escaped-registry")
    profile = _load(tmp_path, "escaped", escaping, kb)
    assert profile.source_registry == (tmp_path / "escaped-registry").resolve()

    # The profile FILE itself stays outside the Content Repository — even an
    # ignored location inside it is refused before its contents are read.
    inside_dir = repo / ".local"
    inside_dir.mkdir()
    (repo / ".gitignore").write_text(".local/\n")
    inside_file = inside_dir / "jp-profile.json"
    inside_file.write_text(json.dumps(_profile_dict(tmp_path)))

    def refuse(profile_file: Path) -> None:
        with pytest.raises(PrivateProfileError) as excinfo:
            load_private_profile(profile_file, kb_root=kb)
        assert "OUTSIDE the content repository" in str(excinfo.value)

    refuse(inside_file)
    # A symlink stored inside the repository that resolves inside it is the
    # same placement, refused through the resolved path.
    link = repo / "jp-profile-link.json"
    link.symlink_to(inside_file)
    refuse(link)
    # Refusal precedes any registry/store creation (nothing was read or made).
    assert not (tmp_path / "private" / "registry").exists()
    assert not (tmp_path / "private" / "artifacts").exists()


def _clear_private_env(monkeypatch):
    for variable in ("LUMIO_SOURCE_REGISTRY", "LUMIO_SOURCE_STORE", "LUMIO_ARTIFACT_RETENTION"):
        monkeypatch.delenv(variable, raising=False)


def test_private_profile_inspect_reports_capabilities_safely(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    profile_path = _write_profile(_subdir(tmp_path, "profiles"), _profile_dict(tmp_path))
    monkeypatch.chdir(tmp_path)
    _clear_private_env(monkeypatch)

    exit_code = main(["private-profile", "inspect", str(profile_path), "--kb", str(kb), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["valid"] is True
    assert payload["namespace"] == NAMESPACE
    assert payload["retention"] == "required"
    assert payload["artifact_store"] == "local"
    assert payload["exchange"] == "s3"

    exit_code = main(["private-profile", "inspect", str(profile_path), "--kb", str(kb)])
    assert exit_code == 0
    human = capsys.readouterr().out
    assert NAMESPACE in human and "required" in human

    combined = human + json.dumps(payload)
    for secret_sentinel in (
        str(tmp_path / "private" / "registry"),
        str(tmp_path / "private" / "artifacts"),
        "jp-test-exchange",
        "127.0.0.1:9000",
        ACCESS_KEY_ENV,
        SECRET_KEY_ENV,
    ):
        assert secret_sentinel not in combined
    # Inspection creates nothing: the declared private paths stay absent.
    assert not (tmp_path / "private" / "registry").exists()
    assert not (tmp_path / "private" / "artifacts").exists()

    invalid = _profile_dict(tmp_path)
    invalid["retention"] = "sometimes"
    invalid_path = _write_profile(_subdir(tmp_path, "invalid"), invalid)
    exit_code = main(["private-profile", "inspect", str(invalid_path), "--kb", str(kb), "--json"])
    assert exit_code == 2
    error_payload = json.loads(capsys.readouterr().out)
    assert error_payload["ok"] is False
    assert error_payload["error"]["code"] == "invalid_private_profile"


def test_cli_profile_mode_rejects_competing_selections(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    monkeypatch.chdir(tmp_path)
    _clear_private_env(monkeypatch)
    profile_path = _write_profile(_subdir(tmp_path, "profiles"), _profile_dict(tmp_path))
    raw = tmp_path / "operator-manual.md"
    raw.write_bytes(RAW_MANUAL)
    page = tmp_path / "workbench-press.md"
    page.write_text(COMPILED_PAGE)
    managed_tail = ["--compiled-page", str(page), "--source-id", "operator-manual"]

    def run(argv: list[str]) -> str:
        capsys.readouterr()
        code = main(argv)
        captured = capsys.readouterr()
        assert code == 2, (code, captured.err)
        assert "private profile selection is exclusive" in captured.err
        return captured.err

    competing_flag = [
        "ingest",
        str(kb),
        str(raw),
        *managed_tail,
        "--private-profile",
        str(profile_path),
        "--source-registry",
        str(tmp_path / "other-registry"),
    ]
    run(competing_flag)
    monkeypatch.setenv("LUMIO_SOURCE_REGISTRY", str(tmp_path / "other-registry"))
    assert "LUMIO_SOURCE_REGISTRY" in run(
        ["ingest", str(kb), str(raw), *managed_tail, "--private-profile", str(profile_path)]
    )
    monkeypatch.delenv("LUMIO_SOURCE_REGISTRY")
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "other-store"))
    assert "LUMIO_SOURCE_STORE" in run(
        ["ingest", str(kb), str(raw), *managed_tail, "--private-profile", str(profile_path)]
    )
    monkeypatch.delenv("LUMIO_SOURCE_STORE")
    monkeypatch.setenv("LUMIO_ARTIFACT_RETENTION", "disabled")
    assert "LUMIO_ARTIFACT_RETENTION" in run(
        ["ingest", str(kb), str(raw), *managed_tail, "--private-profile", str(profile_path)]
    )
    monkeypatch.delenv("LUMIO_ARTIFACT_RETENTION")

    # Profile selection applies to managed ingest/publication routes only.
    capsys.readouterr()
    code = main(["ingest", str(kb), str(raw), "--private-profile", str(profile_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "managed ingest" in captured.err

    # Exclusive selection alone drives the managed route end to end: the
    # profile's registry receives the exact registration (SHA-256 oracle) and
    # the authored page lands in the authoring worktree.
    capsys.readouterr()
    code = main(
        ["ingest", str(kb), str(raw), *managed_tail, "--private-profile", str(profile_path)]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    selected_registry = SourceRegistry((tmp_path / "private" / "registry").resolve())
    version = selected_registry.find_version("operator-manual", RAW_MANUAL_DIGEST)
    assert version is not None
    assert (kb / "concepts" / "workbench_press.md").is_file()
