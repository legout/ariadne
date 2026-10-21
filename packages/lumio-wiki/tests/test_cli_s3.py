"""CLI S3 Knowledge Base Location support (issue #120, ADR-0013).

Retains URI/configuration validation and in-memory publication, conflict,
rollback, and cleanup journeys. Live reader operation is covered by the
optional S3-compatible integration suites.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from lumio_wiki import cli
from lumio_wiki.artifact_store import InMemoryArtifactStore
from lumio_wiki.s3_location import S3Location
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "lumio" / "fixtures"


# ---------------------------------------------------------------------------
# URI detection and environment config.
# ---------------------------------------------------------------------------


def test_is_object_store_uri_detects_s3_and_rejects_local_paths():
    assert cli._is_object_store_uri("s3://bucket/kb")
    assert cli._is_object_store_uri("s3a://bucket/kb")
    assert not cli._is_object_store_uri("/local/path")
    assert not cli._is_object_store_uri("relative/path")
    assert not cli._is_object_store_uri(Path("/local/path"))


def test_s3_config_from_env_reads_lumio_and_aws_vars(monkeypatch):
    for var in list(os.environ):
        if var.startswith(("LUMIO_S3_", "AWS_")):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LUMIO_S3_REGION", "eu-west-1")
    monkeypatch.setenv("LUMIO_S3_ENDPOINT", "http://localhost:8333")
    monkeypatch.setenv("LUMIO_S3_ACCESS_KEY_ID", "local-access")
    monkeypatch.setenv("LUMIO_S3_SECRET_ACCESS_KEY", "local-secret")
    config, client_options = cli._s3_config_from_env()
    assert config["aws_region"] == "eu-west-1"
    assert config["aws_endpoint"] == "http://localhost:8333"
    assert config["aws_access_key_id"] == "local-access"
    assert config["aws_secret_access_key"] == "local-secret"
    # An HTTP endpoint opts in to allow_http on the client.
    assert client_options == {"allow_http": True}


@pytest.mark.parametrize(
    "uri, secret",
    [
        ("s3://user:secret@bucket/kb", "user:secret"),
        ("s3://bucket/kb?token=secret", "token=secret"),
        ("s3://bucket/kb#peek", "#peek"),
    ],
)
def test_build_publish_store_rejects_uri_credentials(uri, secret):
    """The shared writer/store seam refuses unsafe URI metadata without echoing."""
    with pytest.raises(cli.CliError, match="must not include credentials") as excinfo:
        cli._build_publish_store(uri)
    assert secret not in str(excinfo.value)


def test_build_publish_store_accepts_credential_free_uri():
    pytest.importorskip("obstore")
    store, prefix = cli._build_publish_store("s3://bucket/kb")
    assert prefix == "kb"


@pytest.mark.parametrize(
    "argv, secret",
    [
        (["validate", "s3://user:secret@bucket/kb"], "user:secret"),
        (["status", "s3://user:secret@bucket/kb"], "user:secret"),
        (["validate", "s3://bucket/kb?token=secret"], "token=secret"),
        (["status", "s3://bucket/kb#peek"], "#peek"),
    ],
)
def test_read_and_status_paths_never_echo_uri_credentials(
    argv, secret, tmp_path, monkeypatch, capsys
):
    """Read/status wrappers must not repeat userinfo/query/fragment after refusal."""
    monkeypatch.chdir(tmp_path)
    for var in list(os.environ):
        if var.startswith(("LUMIO_", "AWS_")):
            monkeypatch.delenv(var, raising=False)
    rc = cli.main(argv)
    assert rc == 2
    captured = capsys.readouterr()
    assert "must not include credentials" in captured.err
    assert secret not in captured.err + captured.out
    # The location is echoed but redacted: scheme, host, and path only.
    assert "s3://bucket/kb" in captured.err


def test_is_object_store_uri_rejects_non_store_schemes():
    assert not cli._is_object_store_uri("https://example.com/path")
    assert not cli._is_object_store_uri("file:///local/path")


def test_s3_config_from_env_falls_back_to_aws_vars(monkeypatch):
    for var in list(os.environ):
        if var.startswith(("LUMIO_S3_", "AWS_")):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    config, _ = cli._s3_config_from_env()
    assert config == {"aws_region": "us-east-2"}


def test_s3_config_from_env_empty_when_unset(monkeypatch):
    for var in list(os.environ):
        if var.startswith(("LUMIO_S3_", "AWS_")):
            monkeypatch.delenv(var, raising=False)
    config, client_options = cli._s3_config_from_env()
    assert config == {}
    assert client_options == {}


# ---------------------------------------------------------------------------
# publish-s3: publish a local Knowledge Base to an object store (issue #121).
# ---------------------------------------------------------------------------

obstore = pytest.importorskip("obstore", reason="obstore required for publish-s3 CLI")


def _init_git_kb(tmp_path: Path):
    root = tmp_path / "git-kb"
    shutil.copytree(FIXTURES / "valid", root)
    (root / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace="urn:uuid:0f6f0e3e-1d9a-4b2e-9d47-6c1f0f5f4f3e",
            )
        )
    )
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test Author"], check=True)
    return root, _commit_git_kb(root, "initial candidate"), SourceRegistry(tmp_path / "registry")


def _commit_git_kb(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-qm", message], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _next_git_revision(root: Path, label: str) -> str:
    page = root / "overview.md"
    page.write_text(page.read_text(encoding="utf-8") + f"\n<!-- {label} -->\n", encoding="utf-8")
    return _commit_git_kb(root, label)


def _publish_git_revision(root, revision, expected_current, registry, capsys, *, retrieval=None):
    args = [
        "publish-s3",
        str(root),
        "s3://bucket/kb",
        "--revision",
        revision,
        "--expected-current",
        expected_current,
        "--source-registry",
        str(registry.root),
        "--json",
    ]
    if retrieval is not None:
        args.extend(["--retrieval", retrieval])
    rc = cli.main(args)
    preview = capsys.readouterr()
    assert rc == 0, preview.err
    review = json.loads(preview.out)
    rc = cli.main([*args, "--confirm", review["review_digest"]])
    confirmed = capsys.readouterr()
    return rc, confirmed


def _rollback_git_revision(version, expected_current, capsys):
    args = [
        "rollback-s3",
        "s3://bucket/kb",
        "--version",
        version,
        "--expected-current",
        expected_current,
        "--json",
    ]
    rc = cli.main(args)
    preview = capsys.readouterr()
    assert rc == 0, preview.err
    review = json.loads(preview.out)
    rc = cli.main([*args, "--confirm", review["review_digest"]])
    return rc, capsys.readouterr()


def test_cli_publish_s3_writes_an_immutable_version_and_advances_the_pointer(
    tmp_path, monkeypatch, capsys
):
    """S3 publication admits one exact reviewed Git revision offline."""
    import msgspec
    from lumio_wiki.graph_state import GRAPH_ARTIFACT_FILENAME
    from lumio_wiki.s3_location import (
        CURRENT_POINTER_OBJECT,
        DERIVED_DIR,
        MANIFEST_OBJECT,
        S3Pointer,
    )

    store = _fake_store(monkeypatch)
    root, revision, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    rc, confirmed = _publish_git_revision(root, revision, "none", registry, capsys)
    assert rc == 0, confirmed.err
    receipt = json.loads(confirmed.out)
    assert receipt["revision"] == receipt["version"] == revision
    assert receipt["activated"] is True
    pointer = msgspec.json.decode(
        bytes(obstore.get(store, f"kb/{CURRENT_POINTER_OBJECT}").bytes()), type=S3Pointer
    )
    assert pointer.version == revision
    objects = _list(store, "kb/")
    assert f"kb/{revision}/{MANIFEST_OBJECT}" in objects
    assert f"kb/{revision}/{DERIVED_DIR}/{GRAPH_ARTIFACT_FILENAME}" in objects


def test_cli_publish_s3_reports_a_pointer_conflict(tmp_path, monkeypatch, capsys):
    """A stale expected-current conflicts before a second revision is activated."""
    store = _fake_store(monkeypatch)
    root, revision_a, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    rc, confirmed = _publish_git_revision(root, revision_a, "none", registry, capsys)
    assert rc == 0, confirmed.err
    revision_b = _next_git_revision(root, "successor candidate")
    args = [
        "publish-s3",
        str(root),
        "s3://bucket/kb",
        "--revision",
        revision_b,
        "--expected-current",
        "does-not-exist",
        "--source-registry",
        str(registry.root),
    ]
    rc = cli.main(args)
    captured = capsys.readouterr()
    assert rc == 1
    assert "expected the active version" in captured.err
    assert "re-review against the actual current state" in captured.err
    assert msgspec_pointer(store) == revision_a


def test_cli_s3_reconciles_post_activation_receipt_failure_before_retry(
    tmp_path, monkeypatch, capsys
):
    import lumio_wiki.git_authoring as git_authoring

    store = _fake_store(monkeypatch)
    root, revision_a, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    monkeypatch.delenv("LUMIO_ARTIFACT_RETENTION", raising=False)
    rc, confirmed = _publish_git_revision(root, revision_a, "none", registry, capsys)
    assert rc == 0, confirmed.err

    revision_b = _next_git_revision(root, "receipt failure candidate")
    args = [
        "publish-s3",
        str(root),
        "s3://bucket/kb",
        "--revision",
        revision_b,
        "--expected-current",
        revision_a,
        "--source-registry",
        str(registry.root),
        "--json",
    ]
    assert cli.main(args) == 0
    review = json.loads(capsys.readouterr().out)
    persist_activation = git_authoring._persist_s3_activation
    failed = []

    def fail_after_activation(metadata_store, receipt):
        if receipt.version == revision_b and not failed:
            failed.append(receipt.version)
            raise OSError("activation receipt bookkeeping failure")
        persist_activation(metadata_store, receipt)

    monkeypatch.setattr(git_authoring, "_persist_s3_activation", fail_after_activation)
    confirm_args = [arg for arg in args if arg != "--json"]
    assert cli.main([*confirm_args, "--confirm", review["review_digest"]]) == 1
    assert "activation receipt bookkeeping failure" in capsys.readouterr().err
    assert msgspec_pointer(store) == revision_b

    rc, rolled_back = _rollback_git_revision(revision_a, revision_b, capsys)
    assert rc == 0, rolled_back.err
    assert msgspec_pointer(store) == revision_a

    assert cli.main([*args, "--confirm", review["review_digest"]]) == 0
    retry = json.loads(capsys.readouterr().out)
    assert retry["activated"] is True
    assert msgspec_pointer(store) == revision_a


def _list(store, prefix):
    paths = []
    for batch in obstore.list(store, prefix=prefix):
        for obj in batch:
            paths.append(obj["path"])
    return sorted(paths)


# ---------------------------------------------------------------------------
# publish-s3 --retrieval lancedb / rollback-s3 / cleanup-s3 (issue #163).
# ---------------------------------------------------------------------------


def _fake_store(monkeypatch, prefix="kb"):
    store = obstore.store.MemoryStore()
    location = S3Location(store, prefix, store_uri="s3://bucket")
    metadata_store = InMemoryArtifactStore()
    monkeypatch.setattr(cli, "_build_publish_store", lambda uri: (store, prefix))
    monkeypatch.setattr(
        cli,
        "_build_publish_location",
        lambda uri: (location, location.effective_target_identity),
    )
    monkeypatch.setattr(cli, "_publication_metadata_store_for_s3", lambda uri: metadata_store)
    return store


def _publish_initial(tmp_path, monkeypatch, capsys):
    store = _fake_store(monkeypatch)
    root, revision, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    monkeypatch.delenv("LUMIO_ARTIFACT_RETENTION", raising=False)
    rc, confirmed = _publish_git_revision(root, revision, "none", registry, capsys)
    assert rc == 0, confirmed.err
    return store, root, revision, registry


class _RecordingBuilder:
    """A stub IndexBuilder: records the call, writes a marker sidecar."""

    def __init__(self, exc=None):
        self.exc = exc
        self.calls = []

    def __call__(self, *, store, sidecar_prefix, pages, fingerprint, kb=None):
        self.calls.append((sidecar_prefix, len(pages), fingerprint.digest))
        if self.exc is not None:
            raise self.exc
        obstore.put(
            store,
            f"{sidecar_prefix}/tables/evidence.lance/data",
            b"indexed evidence table",
            mode="create",
        )

        from lumio_wiki.s3_publish import RemoteIndexCompletion

        return RemoteIndexCompletion(
            fingerprint=fingerprint.digest, model=None, tables={"evidence": 3, "pages": 3}
        )


def test_cli_publish_s3_retrieval_lancedb_builds_before_activation(tmp_path, monkeypatch, capsys):
    store = _fake_store(monkeypatch)
    root, revision, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    builder = _RecordingBuilder()
    monkeypatch.setattr(cli, "_publication_index_builder", lambda dest: builder)

    rc, confirmed = _publish_git_revision(
        root, revision, "none", registry, capsys, retrieval="lancedb"
    )
    assert rc == 0, confirmed.err
    assert builder.calls[0][0] == f"kb/{revision}/derived/lance"
    assert f"kb/{revision}/derived/lance/completion.json" in _list(store, "kb/")


def test_cli_rollback_s3_refuses_missing_requested_lancedb_object(tmp_path, monkeypatch, capsys):
    store = _fake_store(monkeypatch)
    root, revision_a, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    builder = _RecordingBuilder()
    monkeypatch.setattr(cli, "_publication_index_builder", lambda dest: builder)
    rc, confirmed = _publish_git_revision(
        root, revision_a, "none", registry, capsys, retrieval="lancedb"
    )
    assert rc == 0, confirmed.err

    revision_b = _next_git_revision(root, "successor without index")
    rc, confirmed = _publish_git_revision(root, revision_b, revision_a, registry, capsys)
    assert rc == 0, confirmed.err
    object_key = f"kb/{revision_a}/derived/lance/tables/evidence.lance/data"
    assert object_key in _list(store, "kb/")

    args = [
        "rollback-s3",
        "s3://bucket/kb",
        "--version",
        revision_a,
        "--expected-current",
        revision_b,
        "--json",
    ]
    assert cli.main(args) == 0
    review = json.loads(capsys.readouterr().out)
    obstore.delete(store, object_key)

    confirm_args = [arg for arg in args if arg != "--json"]
    assert cli.main([*confirm_args, "--confirm", review["review_digest"]]) == 1
    failure = capsys.readouterr()
    assert "missing" in failure.err.lower()
    assert msgspec_pointer(store) == revision_b


def test_cli_publish_s3_retrieval_lancedb_failure_blocks_activation(tmp_path, monkeypatch, capsys):
    store = _fake_store(monkeypatch)
    root, revision, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    builder = _RecordingBuilder(exc=RuntimeError("lance unavailable"))
    monkeypatch.setattr(cli, "_publication_index_builder", lambda dest: builder)

    rc, confirmed = _publish_git_revision(
        root, revision, "none", registry, capsys, retrieval="lancedb"
    )
    assert rc == 1
    assert len(builder.calls) == 1
    error = json.loads(confirmed.out)
    assert error["ok"] is False
    assert error["error"]["code"] == "cli_error"
    assert confirmed.err == ""
    assert "kb/current.json" not in _list(store, "kb/")
    assert f"kb/{revision}/manifest.json" not in _list(store, "kb/")


def test_cli_rollback_s3_activates_a_prior_complete_version(tmp_path, monkeypatch, capsys):
    store = _fake_store(monkeypatch)
    root, revision_a, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    rc, confirmed = _publish_git_revision(root, revision_a, "none", registry, capsys)
    assert rc == 0, confirmed.err
    revision_b = _next_git_revision(root, "successor candidate")
    rc, confirmed = _publish_git_revision(root, revision_b, revision_a, registry, capsys)
    assert rc == 0, confirmed.err

    rc, confirmed = _rollback_git_revision(revision_a, revision_b, capsys)
    assert rc == 0, confirmed.err
    assert json.loads(confirmed.out)["version"] == revision_a
    assert msgspec_pointer(store) == revision_a


def test_cli_rollback_s3_recovers_from_a_damaged_active_index(tmp_path, monkeypatch, capsys):
    """D2: outgoing index health never blocks rollback to a verified target."""
    store = _fake_store(monkeypatch)
    root, revision_a, registry = _init_git_kb(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "source-store"))
    builder = _RecordingBuilder()
    monkeypatch.setattr(cli, "_publication_index_builder", lambda dest: builder)
    rc, confirmed = _publish_git_revision(
        root, revision_a, "none", registry, capsys, retrieval="lancedb"
    )
    assert rc == 0, confirmed.err
    revision_b = _next_git_revision(root, "successor whose index gets damaged")
    rc, confirmed = _publish_git_revision(
        root, revision_b, revision_a, registry, capsys, retrieval="lancedb"
    )
    assert rc == 0, confirmed.err

    args = [
        "rollback-s3",
        "s3://bucket/kb",
        "--version",
        revision_a,
        "--expected-current",
        revision_b,
        "--json",
    ]
    assert cli.main(args) == 0
    review = json.loads(capsys.readouterr().out)

    # Damage only the OUTGOING active version's index object; the healthy
    # target keeps its complete inventory. Target strictness is pinned by
    # test_cli_rollback_s3_refuses_missing_requested_lancedb_object.
    damaged_key = f"kb/{revision_b}/derived/lance/tables/evidence.lance/data"
    assert damaged_key in _list(store, "kb/")
    obstore.delete(store, damaged_key)

    assert cli.main([*args, "--confirm", review["review_digest"]]) == 0
    confirmed = capsys.readouterr()
    assert json.loads(confirmed.out)["version"] == revision_a
    assert msgspec_pointer(store) == revision_a


def _legacy_indexed_adoption_fixture(
    tmp_path, monkeypatch, *, embedded_version="v-legacy", embedded_fingerprint=None
):
    """D1 fixture: a legacy indexed S3 active version plus a native candidate.

    The exact legacy binding manifest is stored under the ``v-legacy`` key of
    the configured private Source Artifact Store; ``embedded_version`` /
    ``embedded_fingerprint`` override the manifest's own identity fields for
    the D1-A mismatched-identity negative cases.
    """
    import hashlib
    from types import SimpleNamespace

    import msgspec
    from lumio_wiki.artifact_store import (
        LocalDirectoryArtifactStore,
        SourceBindingEntry,
        SourceBindingManifest,
    )
    from lumio_wiki.s3_location import S3ManifestFile
    from lumio_wiki.s3_publish import _publish_s3_working_tree

    control = """\
version: 2
mode: categorized
categories:
  - name: concepts
ontology:
  entity_types:
    press: {}
  predicates:
    presses:
      subject_types: [press]
      object_types: [press]
"""
    press_page = """\
---
id: "entity:press"
title: "Press"
entity_types:
  - press
tags: [test]
summary: "Press summary."
lifecycle: approved
visibility: public
sources:
  - id: operator-manual
    title: "Operator Manual"
---

# Press

The captured source supports this page.
"""

    legacy_kb = tmp_path / "legacy-kb"
    (legacy_kb / "concepts").mkdir(parents=True)
    (legacy_kb / "lumio.yaml").write_text(control)
    (legacy_kb / "concepts" / "press.md").write_text(press_page)
    store = _fake_store(monkeypatch)
    legacy_manifest = _publish_s3_working_tree(
        store, "kb", source_root=legacy_kb, version="v-legacy"
    )
    # Legacy LanceDB completion metadata predates the object inventory (old
    # shape: no ``objects`` key), yet is digest-consistent with its manifest.
    legacy_completion = json.dumps(
        {"fingerprint": legacy_manifest.fingerprint, "tables": {"evidence": 2}}
    ).encode()
    completion_rel = "derived/lance/completion.json"
    obstore.put(store, "kb/v-legacy/" + completion_rel, legacy_completion)
    patched_manifest = msgspec.structs.replace(
        legacy_manifest,
        derived_files=[
            *legacy_manifest.derived_files,
            S3ManifestFile(
                path=completion_rel,
                size=len(legacy_completion),
                digest=hashlib.sha256(legacy_completion).hexdigest(),
            ),
        ],
    )
    obstore.put(store, "kb/v-legacy/manifest.json", msgspec.json.encode(patched_manifest))
    assert msgspec_pointer(store) == "v-legacy"

    source_a = b"legacy retained operator manual bytes"
    digest_a = hashlib.sha256(source_a).hexdigest()
    source_b = b"successor operator manual bytes"
    digest_b = hashlib.sha256(source_b).hexdigest()
    legacy_store = LocalDirectoryArtifactStore(tmp_path / "legacy-source-store")
    binding_manifest = SourceBindingManifest(
        published_version=embedded_version,
        fingerprint=embedded_fingerprint or legacy_manifest.fingerprint,
        created_at="2025-12-01T00:00:00Z",
        entries=[
            SourceBindingEntry(
                entity_id="entity:press",
                page_title="Press",
                source_id="operator-manual",
                content_hash=digest_a,
                content_type="text/plain",
                filename="manual.txt",
                size=len(source_a),
            )
        ],
    )
    legacy_store.put_binding_manifest("v-legacy", msgspec.json.encode(binding_manifest))
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(tmp_path / "legacy-source-store"))

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test Author"], check=True)
    root = repo / "kb"
    shutil.copytree(legacy_kb, root)
    (root / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace="urn:uuid:0f6f0e3e-1d9a-4b2e-9d47-6c1f0f5f4f3e",
                sources={"operator-manual": "active"},
                bindings={"entity:press": {"operator-manual": digest_b}},
            )
        )
    )
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_source(
        "operator-manual", source_b, filename="manual-b.txt", content_type="text/plain"
    )
    subprocess.run(["git", "-C", str(repo), "add", "kb"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "native successor"], check=True)
    revision = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    args = [
        "publish-s3",
        str(root),
        "s3://bucket/kb",
        "--revision",
        revision,
        "--expected-current",
        "v-legacy",
        "--source-registry",
        str(registry.root),
        "--json",
    ]
    return SimpleNamespace(
        store=store, args=args, revision=revision, digest_a=digest_a, digest_b=digest_b
    )


def test_cli_publish_s3_adopts_legacy_indexed_version_from_legacy_store(
    tmp_path, monkeypatch, capsys
):
    """D1+D2: first native adoption over a legacy indexed S3 version whose
    exact binding manifest lives only in the configured legacy private store."""
    fixture = _legacy_indexed_adoption_fixture(tmp_path, monkeypatch)

    assert cli.main(fixture.args) == 0
    review = json.loads(capsys.readouterr().out)
    assert "adopt legacy Published Version 'v-legacy'" in review["adoption"]
    replacements = [
        impact
        for impact in review["source_impact"]
        if impact["source_id"] == "operator-manual"
        and impact["change"] == "replaced legacy binding"
    ]
    assert (
        replacements and replacements[0]["support"] == f"{fixture.digest_a} -> {fixture.digest_b}"
    )
    assert replacements[0]["entity_id"] == "entity:press"

    assert cli.main([*fixture.args, "--confirm", review["review_digest"]]) == 0
    confirmed = capsys.readouterr()
    assert json.loads(confirmed.out)["activated"] is True
    assert msgspec_pointer(fixture.store) == fixture.revision


@pytest.mark.parametrize(
    "mismatch",
    [
        pytest.param({"embedded_version": "v-other"}, id="published-version"),
        pytest.param({"embedded_fingerprint": "0" * 64}, id="fingerprint"),
    ],
)
def test_cli_publish_s3_refuses_mismatched_legacy_binding_identity(
    tmp_path, monkeypatch, capsys, mismatch
):
    """D1-A: a legacy binding manifest whose embedded identity does not match
    the observed active public manifest blocks adoption with an explicit
    repair diagnostic — never an absent/latest baseline."""
    fixture = _legacy_indexed_adoption_fixture(tmp_path, monkeypatch, **mismatch)
    preview_args = [arg for arg in fixture.args if arg != "--json"]

    assert cli.main(preview_args) == 1
    failure = capsys.readouterr()
    assert "the legacy S3 Source Binding Manifest for 'v-legacy' does not match" in failure.err
    assert "repair" in failure.err
    assert msgspec_pointer(fixture.store) == "v-legacy"


def test_cli_rollback_s3_reports_conflicts(tmp_path, monkeypatch, capsys):
    store, _root, revision, _registry = _publish_initial(tmp_path, monkeypatch, capsys)
    rc = cli.main(
        [
            "rollback-s3",
            "s3://bucket/kb",
            "--version",
            revision,
            "--expected-current",
            "nope",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "expected the active version" in captured.err
    assert "re-review against the actual current state" in captured.err
    assert msgspec_pointer(store) == revision


def test_cli_rollback_s3_names_cleanup_candidates_on_incomplete_targets(
    tmp_path, monkeypatch, capsys
):
    store, root, active, _registry = _publish_initial(tmp_path, monkeypatch, capsys)
    incomplete_revision = _next_git_revision(root, "interrupted successor")
    obstore.put(store, f"kb/{incomplete_revision}/overview.md", b"partial", mode="create")
    rc = cli.main(
        [
            "rollback-s3",
            "s3://bucket/kb",
            "--version",
            incomplete_revision,
            "--expected-current",
            active,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert incomplete_revision in captured.err
    assert "cleanup candidate" in captured.err
    assert msgspec_pointer(store) == active


def test_cli_cleanup_s3_reports_candidates_without_deleting(tmp_path, monkeypatch, capsys):
    store, _root, _revision, _registry = _publish_initial(tmp_path, monkeypatch, capsys)
    obstore.put(store, "kb/v2/overview.md", b"partial", mode="create")

    rc = cli.main(["cleanup-s3", "s3://bucket/kb"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "v2" in out
    assert "nothing is deleted" in out.lower()
    assert "kb/v2/overview.md" in _list(store, "kb")


def test_cli_cleanup_s3_with_no_candidates(tmp_path, monkeypatch, capsys):
    _publish_initial(tmp_path, monkeypatch, capsys)
    rc = cli.main(["cleanup-s3", "s3://bucket/kb"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No cleanup candidates" in out


def msgspec_pointer(store) -> str:
    import msgspec
    from lumio_wiki.s3_location import CURRENT_POINTER_OBJECT, S3Pointer

    raw = obstore.get(store, f"kb/{CURRENT_POINTER_OBJECT}")
    return msgspec.json.decode(bytes(raw.bytes()), type=S3Pointer).version


# ---------------------------------------------------------------------------
# --retrieval lancedb resolves its S3 endpoint/region like the obstore path
# (#161 setup wrote them to .env; #163's builder must read them there too).
# ---------------------------------------------------------------------------


def test_lance_storage_options_read_project_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in (
        "LUMIO_S3_REGION",
        "LUMIO_S3_ENDPOINT",
        "LUMIO_S3_ACCESS_KEY_ID",
        "LUMIO_S3_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_ENDPOINT_URL_S3",
        "AWS_ACCESS_KEY_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "LUMIO_S3_REGION=us-east-1\n"
        "LUMIO_S3_ENDPOINT=http://localhost:9000\n"
        "AWS_ACCESS_KEY_ID=file-never-wins\n",
        encoding="utf-8",
    )

    options = cli._lance_storage_options_from_env()

    assert options["region"] == "us-east-1"
    assert options["endpoint"] == "http://localhost:9000"
    assert options["allow_http"] == "true"
    # Setup never writes credentials to .env and they never load from there.
    assert "access_key_id" not in options

    monkeypatch.setenv("LUMIO_S3_ENDPOINT", "https://exported.example")
    assert cli._lance_storage_options_from_env()["endpoint"] == "https://exported.example"
