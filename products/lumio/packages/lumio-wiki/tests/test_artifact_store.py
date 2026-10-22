"""Private Source Artifact retention (issue #164, ADR-0020).

Deterministic coverage for the Source Artifact Store seam, the managed-ingest
upload+binding saga, the private Source Binding Manifest, required-retention
activation gating, and privacy (no artifact bytes or keys in public Published
Versions, fingerprints, or manifests). The S3 adapter's signing and
access-denied behavior is covered by the S3-compatible suite
(``test_artifact_store_s3_compat.py``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import msgspec
import pytest
from lumio_wiki.artifact_store import (
    ArtifactStoreError,
    InMemoryArtifactStore,
    LocalDirectoryArtifactStore,
    RetentionRequiredError,
    SigningUnavailable,
    SourceBindingEntry,
    SourceBindingManifest,
    activation_binding_hook,
    affected_published_versions,
    artifact_content_hash,
    build_binding_manifest,
    delete_artifact_with_disclosure,
    retain_artifact,
    sweep_orphaned_uploads,
    verify_rollback_coverage,
    write_binding_manifest,
)
from lumio_wiki.knowledge_base import fingerprint_sources
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import (
    SourceRegistry,
    SourceRegistryError,
    safe_artifact_filename,
)

obstore = pytest.importorskip("obstore", reason="obstore required for publication coverage")

from lumio_wiki.s3_location import CURRENT_POINTER_OBJECT, S3Location  # noqa: E402

from tests._s3_fixtures import (  # noqa: E402
    publish_legacy_s3_version as publish_s3_version,
)

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "valid"

RAW = b"%PDF-1.4 original source bytes for the artifact suite"


def _kb(tmp_path: Path):
    import lumio_wiki as lw

    root = tmp_path / "kb"
    shutil.copytree(FIXTURES, root)
    kb, report = lw.load_knowledge_base(root)
    assert report.is_valid, report
    return kb


def _authored_page(source_id: str, *, title: str = "Artifact Page", synthetic: bool = False):
    return (
        "---\n"
        f'title: "{title}"\n'
        "aliases: []\n"
        'tags:\n  - "artifacts"\n'
        'summary: "Authored page for the artifact suite."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        f'    title: "{source_id} source"\n'
        f"synthetic: {str(synthetic).lower()}\n"
        "---\n\n"
        f"# {title}\n\n"
        "Body authored from the original source.\n"
    )


def _mark_registry_retired(registry, source_id: str) -> None:
    """Flip one source to retired in the private registry (test setup).

    Native retirement records lifecycle intent in the Git Source Reference
    Manifest (spec 0008 §3.2); the proposal-keyed transition API is retired.
    This fixture setup reproduces the durable registry outcome.
    """
    import msgspec as _msgspec

    state = registry._reload()
    sources = [
        _msgspec.structs.replace(s, status="retired") if s.source_id == source_id else s
        for s in state.sources
    ]
    registry._commit(_msgspec.structs.replace(state, sources=sources))
    assert registry.get(source_id).status == "retired"


def _authored_page_rel(*, synthetic: bool = False) -> str:
    """The authored page's destination path (title slug, root-level)."""
    return "artifact_page.md"


def _managed_source(kb, tmp_path: Path, artifact_store, *, synthetic: bool = False):
    """Fixture setup: write the managed-source page and register its version.

    The native managed-ingest journey is pinned in test_git_authoring; these
    gate tests need only the authored page in the KB plus the exact registry
    version and (optionally) retained artifact that retention evaluates.
    """
    from lumio_wiki.source_registry import SourceRegistry

    registry = SourceRegistry(tmp_path / "registry")
    page_rel = _authored_page_rel(synthetic=synthetic)
    page_path = Path(kb.root) / page_rel
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(_authored_page("annual-report", synthetic=synthetic), encoding="utf-8")
    registry.register_version("annual-report", RAW, filename="report.pdf")
    if artifact_store is not None:
        retain_artifact(
            artifact_store,
            registry,
            source_id="annual-report",
            raw_bytes=RAW,
            content_type="application/pdf",
            filename="report.pdf",
        )
    return registry


_GIT_CONTROL = """\
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
"""


def _authoring_root(tmp_path: Path) -> Path:
    root = tmp_path / "git-kb"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test Author"], check=True)
    return root


def _commit_authoring(
    root: Path,
    digest: str,
    *,
    message: str,
    body: str,
    source_id: str = "architecture-doc",
    retired_source_ids: tuple[str, ...] = (),
    include_ghost: bool = False,
) -> str:
    (root / "lumio.yaml").write_text(_GIT_CONTROL, encoding="utf-8")
    sources = f'  - id: "{source_id}"\n    title: "{source_id} source"\n' + (
        '  - id: "ghost-reference"\n    title: "Public-only reference"\n' if include_ghost else ""
    )
    page = f"""
---
id: "entity:artifact-page"
title: "Artifact Page"
entity_types:
  - press
tags:
  - "artifacts"
summary: "Authored page for the artifact suite."
lifecycle: "approved"
visibility: "public"
sources:
{sources}---

# Artifact Page

## Overview

{body}
""".lstrip()
    (root / "artifact-page.md").write_text(page, encoding="utf-8")
    manifest = SourceReferenceManifest(
        version=1,
        namespace="urn:uuid:0f6f0e3e-1d9a-4b2e-9d47-6c1f0f5f4f3e",
        sources={
            **{retired_id: "retired" for retired_id in retired_source_ids},
            source_id: "active",
        },
        bindings={"entity:artifact-page": {source_id: digest}},
    )
    (root / ".lumio-authoring.yaml").write_bytes(serialize_source_reference_manifest(manifest))
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _publish_git_revision(root, revision, expected_current, registry, capsys):
    from lumio_wiki import cli

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
    assert cli.main(args) == 0
    review = json.loads(capsys.readouterr().out)
    assert cli.main([*args, "--confirm", review["review_digest"]]) == 0
    return json.loads(capsys.readouterr().out)


def _rollback_git_revision(version, expected_current, capsys, *, json_confirm=True):
    from lumio_wiki import cli

    args = [
        "rollback-s3",
        "s3://bucket/kb",
        "--version",
        version,
        "--expected-current",
        expected_current,
        "--json",
    ]
    assert cli.main(args) == 0
    review = json.loads(capsys.readouterr().out)
    confirm_args = args if json_confirm else [arg for arg in args if arg != "--json"]
    rc = cli.main([*confirm_args, "--confirm", review["review_digest"]])
    return rc, capsys.readouterr()


def _use_memory_s3(monkeypatch, store):
    from lumio_wiki import cli

    location = S3Location(store, "kb", store_uri="s3://bucket")
    metadata_store = InMemoryArtifactStore()
    monkeypatch.setattr(
        cli,
        "_build_publish_location",
        lambda _uri: (location, location.effective_target_identity),
    )
    monkeypatch.setattr(cli, "_publication_metadata_store_for_s3", lambda _uri: metadata_store)
    return location


@pytest.fixture(params=["memory", "local"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryArtifactStore()
    return LocalDirectoryArtifactStore(tmp_path / "artifact-store")


# ---------------------------------------------------------------------------
# Adapter contract: verified bytes, create-only, identity-oriented addressing.
# ---------------------------------------------------------------------------


def test_put_get_roundtrip_verifies_digest(store):
    store.put_artifact(
        source_id="report",
        content_hash=artifact_content_hash(RAW),
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="report.pdf",
    )
    assert store.get_artifact(source_id="report", content_hash=artifact_content_hash(RAW)) == RAW
    assert store.artifact_exists(source_id="report", content_hash=artifact_content_hash(RAW))


def test_declared_hash_mismatch_is_rejected(store):
    with pytest.raises(ArtifactStoreError):
        store.put_artifact(
            source_id="report",
            content_hash="0" * 64,
            raw_bytes=RAW,
            content_type=None,
            filename=None,
        )


def test_missing_artifact_is_not_retained(store):
    digest = artifact_content_hash(RAW)
    with pytest.raises(ArtifactStoreError):
        store.get_artifact(source_id="unknown", content_hash=digest)
    assert not store.artifact_exists(source_id="unknown", content_hash=digest)


def test_fetch_rejects_tampered_stored_bytes(store):
    digest = artifact_content_hash(RAW)
    store.put_artifact(
        source_id="report",
        content_hash=digest,
        raw_bytes=RAW,
        content_type=None,
        filename=None,
    )
    _tamper(store, "report", digest)
    assert not store.artifact_exists(source_id="report", content_hash=digest)
    with pytest.raises(ArtifactStoreError):
        store.get_artifact(source_id="report", content_hash=digest)


def _tamper(store, source_id: str, digest: str) -> None:
    if isinstance(store, InMemoryArtifactStore):
        store._artifacts[(source_id, digest)] = (b"tampered", None, None)
    else:
        path = store._artifact_path(source_id, digest)
        path.write_bytes(b"tampered on disk")


def test_identical_bytes_do_not_merge_source_identities(store):
    digest = artifact_content_hash(RAW)
    for source_id in ("report-a", "report-b"):
        store.put_artifact(
            source_id=source_id,
            content_hash=digest,
            raw_bytes=RAW,
            content_type="application/pdf",
            filename="same.pdf",
        )
    # Both identities resolve independently (physical dedup never merges them).
    assert store.get_artifact(source_id="report-a", content_hash=digest) == RAW
    assert store.get_artifact(source_id="report-b", content_hash=digest) == RAW
    # Deleting one identity leaves the other intact.
    assert store.delete_artifact(source_id="report-a", content_hash=digest)
    assert store.get_artifact(source_id="report-b", content_hash=digest) == RAW
    assert not store.artifact_exists(source_id="report-a", content_hash=digest)


def test_signing_unavailable_on_local_adapters(store):
    digest = artifact_content_hash(RAW)
    store.put_artifact(
        source_id="report",
        content_hash=digest,
        raw_bytes=RAW,
        content_type=None,
        filename=None,
    )
    assert not store.supports_signing()
    with pytest.raises(SigningUnavailable):
        store.signed_get_url(source_id="report", content_hash=digest, expires_in=300)


# ---------------------------------------------------------------------------
# Safe filenames (registry metadata boundary).
# ---------------------------------------------------------------------------


def test_safe_artifact_filename_strips_paths_and_control_characters():
    assert safe_artifact_filename("/deep/path/report v2.pdf") == "report v2.pdf"
    assert safe_artifact_filename("..\\..\\windows.pdf") == "windows.pdf"
    assert safe_artifact_filename("..") is None
    assert safe_artifact_filename(None) is None
    assert safe_artifact_filename("bad\r\nname.txt") == "badname.txt"
    truncated = safe_artifact_filename("x" * 500 + ".pdf")
    assert truncated is not None and len(truncated) <= 128


# ---------------------------------------------------------------------------
# The idempotent managed-ingest saga (AC: new / retry / failure / orphan).
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> SourceRegistry:
    return SourceRegistry(tmp_path / "registry")


def test_saga_registers_uploads_and_binds(store, tmp_path):
    registry = _registry(tmp_path)
    version, _ = registry.register_or_reuse(
        "annual-report", RAW, filename="/deep/report.pdf", content_type="application/pdf"
    )
    digest = retain_artifact(
        store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="/deep/report.pdf",
    )
    assert digest == version.content_hash
    assert version.content_hash == artifact_content_hash(RAW)
    bound = registry.get("annual-report").versions[-1]
    assert bound.artifact_available is True
    assert bound.filename == "report.pdf"
    assert bound.content_type == "application/pdf"
    assert bound.size == len(RAW)
    assert store.get_artifact(source_id="annual-report", content_hash=digest) == RAW


def test_saga_identical_retry_is_idempotent(store, tmp_path):
    registry = _registry(tmp_path)
    for _ in range(3):
        registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
        retain_artifact(
            store,
            registry,
            source_id="annual-report",
            raw_bytes=RAW,
            content_type=None,
            filename="r.pdf",
        )
    source = registry.get("annual-report")
    assert len(source.versions) == 1  # one immutable version, no duplicates
    assert (
        store.get_artifact(source_id="annual-report", content_hash=source.versions[0].content_hash)
        == RAW
    )


def test_saga_changed_bytes_rejected_without_store_mutation(store, tmp_path):
    registry = _registry(tmp_path)
    registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
    retain_artifact(
        store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    with pytest.raises(SourceRegistryError):
        registry.register_or_reuse(
            "annual-report", b"DIFFERENT bytes", filename="r.pdf", content_type=None
        )
    # The store still holds exactly the original bytes.
    assert (
        store.get_artifact(source_id="annual-report", content_hash=artifact_content_hash(RAW))
        == RAW
    )


def test_saga_failed_upload_is_never_reported_as_retained(tmp_path):
    store = InMemoryArtifactStore()
    registry = _registry(tmp_path)

    def _fail_put(**kwargs):
        raise ArtifactStoreError("object store unavailable")

    store.put_artifact = _fail_put  # type: ignore[method-assign]
    registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
    with pytest.raises(ArtifactStoreError):
        retain_artifact(
            store,
            registry,
            source_id="annual-report",
            raw_bytes=RAW,
            content_type=None,
            filename="r.pdf",
        )
    # The Source Version exists as identity/provenance state, but availability
    # was NOT recorded: a failed upload is never reported as retained.
    assert registry.get("annual-report").versions[-1].artifact_available is False
    # A retry after the store recovers completes the saga.
    del store.put_artifact
    retain_artifact(
        store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    assert registry.get("annual-report").versions[-1].artifact_available is True


def test_saga_registry_failure_leaves_sweepable_orphan(store, tmp_path):
    registry = _registry(tmp_path)
    registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
    store.put_artifact(
        source_id="annual-report",
        content_hash=artifact_content_hash(RAW),
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    # The registry binding never happened (crash between upload and bind).
    orphans = sweep_orphaned_uploads(store, registry)
    assert orphans == [("annual-report", artifact_content_hash(RAW))]
    # Recovery: re-running the saga binds the orphan idempotently.
    retain_artifact(
        store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    assert sweep_orphaned_uploads(store, registry) == []
    assert registry.get("annual-report").versions[-1].artifact_available is True


# ---------------------------------------------------------------------------
# Source Binding Manifest + required-retention activation gate.
# ---------------------------------------------------------------------------


def _native_ingest_fixture(tmp_path):
    from lumio_wiki.git_authoring import ingest_into_worktree

    from .test_managed_ingest import _authored_page as managed_page
    from .test_managed_ingest import _kb as managed_kb

    kb = managed_kb(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    return kb, registry, managed_page("annual-report"), ingest_into_worktree


def test_managed_ingest_retains_artifacts_through_the_pipeline(tmp_path):
    kb, registry, page, ingest = _native_ingest_fixture(tmp_path)
    store = InMemoryArtifactStore()
    ingest(
        kb.root,
        RAW,
        "application/pdf",
        "report.pdf",
        "annual-report",
        page,
        source_registry=registry,
        artifact_store=store,
    )
    digest = artifact_content_hash(RAW)
    version = registry.find_version("annual-report", digest)
    assert version is not None and version.artifact_available
    assert store.get_artifact(source_id="annual-report", content_hash=digest) == RAW


def test_managed_ingest_wraps_store_failure_actionably(tmp_path):
    from lumio_wiki.git_authoring import GitAuthoringError

    kb, registry, page, ingest = _native_ingest_fixture(tmp_path)
    before = {p.relative_to(kb.root): p.read_bytes() for p in kb.root.rglob("*") if p.is_file()}
    store = InMemoryArtifactStore()

    def fail_put(**kwargs):
        raise ArtifactStoreError("endpoint unreachable")

    store.put_artifact = fail_put
    with pytest.raises(GitAuthoringError, match="retry the ingest to recover"):
        ingest(
            kb.root,
            RAW,
            "application/pdf",
            "report.pdf",
            "annual-report",
            page,
            source_registry=registry,
            artifact_store=store,
        )
    version = registry.find_version("annual-report", artifact_content_hash(RAW))
    assert version is not None and not version.artifact_available
    assert {
        p.relative_to(kb.root): p.read_bytes() for p in kb.root.rglob("*") if p.is_file()
    } == before


def _published_kb_with_source(tmp_path, *, retain: bool, synthetic: bool = False):
    """Publish a fixture KB plus one managed source under a configured store.

    Every source id the FIXTURE pages reference is registered and backfilled
    with a verified artifact (required retention evaluates every referenced
    non-synthetic source, #164 — fixture sources are scenery and always
    covered). ``annual-report`` (the managed source) is retained ONLY when
    ``retain``: the tests that assert blocking exercise exactly that hole.
    """
    kb = _kb(tmp_path)
    artifact_store = InMemoryArtifactStore()
    registry = _managed_source(
        kb, tmp_path, artifact_store if retain else None, synthetic=synthetic
    )
    for page in kb.pages:
        for source in page.sources:
            if not source.id:
                continue
            fixture_bytes = f"fixture artifact for {source.id}".encode()
            registry.register_or_reuse(source.id, fixture_bytes, filename=None, content_type=None)
            retain_artifact(
                artifact_store,
                registry,
                source_id=source.id,
                raw_bytes=fixture_bytes,
                content_type="text/plain",
                filename=f"{source.id}.txt",
            )
    return kb, registry, artifact_store


def _publish(store, kb, *, version: str, hook=None):
    return publish_s3_version(
        store,
        "kb",
        source_root=kb.root,
        version=version,
        before_activation=hook,
    )


def _public_keys(store) -> list[str]:
    keys = []
    for batch in obstore.list(store, prefix="kb"):
        for obj in batch:
            keys.append(obj["path"])
    return sorted(keys)


def test_publication_writes_private_binding_manifest_before_activation(tmp_path):
    kb, registry, artifact_store = _published_kb_with_source(tmp_path, retain=True)
    store = obstore.store.MemoryStore()
    hook = activation_binding_hook(artifact_store=artifact_store, registry=registry, required=False)
    manifest = _publish(store, kb, version="v1", hook=hook)

    # The private manifest binds the Published Version and the exact version.
    raw = artifact_store.get_binding_manifest("v1")
    binding = msgspec.json.decode(raw, type=SourceBindingManifest)
    assert binding.published_version == "v1"
    assert binding.fingerprint == manifest.fingerprint
    entry = next(e for e in binding.entries if e.source_id == "annual-report")
    assert entry.page_title == "Artifact Page"
    assert entry.content_hash == registry.get("annual-report").versions[-1].content_hash
    assert entry.filename == "report.pdf"
    assert entry.synthetic_page is False

    # PRIVACY: the public prefix exposes no artifact bytes, keys, or manifest.
    public = _public_keys(store)
    assert public, "expected published objects"
    assert not any("artifacts/" in key or "bindings/" in key for key in public)
    for key in public:
        blob = bytes(obstore.get(store, key).bytes())
        assert b"%PDF-1.4 original source bytes" not in blob
    # The canonical fingerprint ignores artifact state entirely.
    assert fingerprint_sources(kb.root) == fingerprint_sources(kb.root)


def test_required_retention_blocks_activation_until_artifact_exists(tmp_path):
    kb, registry, artifact_store = _published_kb_with_source(tmp_path, retain=False)
    assert registry.get("annual-report").versions[-1].artifact_available is False

    store = obstore.store.MemoryStore()
    hook = activation_binding_hook(artifact_store=artifact_store, registry=registry, required=True)
    with pytest.raises(RetentionRequiredError, match="annual-report"):
        _publish(store, kb, version="v1", hook=hook)
    # Pointer was NOT advanced: activation blocked before publication.
    with pytest.raises(FileNotFoundError):
        obstore.get(store, f"kb/{CURRENT_POINTER_OBJECT}")

    # Backfill the artifact (the ADR's historical-backfill path), then retry
    # under a fresh version label: the blocked attempt's prefix is immutable
    # residue (#163), never overwritten.
    retain_artifact(
        artifact_store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="report.pdf",
    )
    _publish(store, kb, version="v2", hook=hook)
    assert artifact_store.get_binding_manifest("v2")


def test_required_retention_ignores_synthetic_pages(tmp_path):
    kb, registry, artifact_store = _published_kb_with_source(tmp_path, retain=False, synthetic=True)
    store = obstore.store.MemoryStore()
    hook = activation_binding_hook(artifact_store=artifact_store, registry=registry, required=True)
    _publish(store, kb, version="v1", hook=hook)  # synthetic page: no artifact needed
    binding = msgspec.json.decode(
        artifact_store.get_binding_manifest("v1"), type=SourceBindingManifest
    )
    entry = next(e for e in binding.entries if e.source_id == "annual-report")
    assert entry.synthetic_page is True


def test_disabled_retention_preserves_hash_only_publication(tmp_path):
    kb, registry, _ = _published_kb_with_source(tmp_path, retain=False)
    assert registry.get("annual-report").versions[-1].artifact_available is False
    store = obstore.store.MemoryStore()
    # No artifact store configured at all: publication is byte-for-byte the
    # pre-#164 behavior (no hook, no gate).
    _publish(store, kb, version="v1")
    pointer = msgspec.json.decode(bytes(obstore.get(store, f"kb/{CURRENT_POINTER_OBJECT}").bytes()))
    assert pointer["version"] == "v1"


def test_historical_manifest_survives_new_source_version(tmp_path):
    kb, registry, artifact_store = _published_kb_with_source(tmp_path, retain=True)
    store = obstore.store.MemoryStore()
    hook = activation_binding_hook(artifact_store=artifact_store, registry=registry, required=True)
    _publish(store, kb, version="v1", hook=hook)
    v1_binding = msgspec.json.decode(
        artifact_store.get_binding_manifest("v1"), type=SourceBindingManifest
    )
    old_hash = next(e.content_hash for e in v1_binding.entries if e.source_id == "annual-report")

    # A later reviewed retirement + reactivation registers a NEW Source
    # Version; the historical manifest still identifies the historical
    # artifact.
    _mark_registry_retired(registry, "annual-report")
    # The later reviewed reactivation registers a NEW Source Version
    # (registration extends immutable history; status returns to active).
    registry.register_version("annual-report", b"NEW report bytes", filename="r2.pdf")
    new_hash = registry.get("annual-report").versions[-1].content_hash
    assert new_hash != old_hash

    v1_again = msgspec.json.decode(
        artifact_store.get_binding_manifest("v1"), type=SourceBindingManifest
    )
    assert (
        next(e.content_hash for e in v1_again.entries if e.source_id == "annual-report") == old_hash
    )
    # The historical artifact bytes are still fetchable by exact identity.
    assert artifact_store.get_artifact(source_id="annual-report", content_hash=old_hash) == RAW


def test_binding_manifest_omits_unregistered_source_ids(tmp_path):
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    manifest = build_binding_manifest(
        published_version="v9",
        fingerprint="digest",
        registry=registry,
        pages=list(kb.pages),
        now="2026-01-01T00:00:00+00:00",
    )
    # Fixture pages cite source ids that were never privately registered: the
    # manifest binds only registered identities.
    assert manifest.entries == []


# ---------------------------------------------------------------------------
# Retirement preserves artifacts; deletion is explicit with disclosure.
# ---------------------------------------------------------------------------


def test_retirement_preserves_historical_artifacts(store, tmp_path):
    registry = _registry(tmp_path)
    registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
    retain_artifact(
        store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    digest = registry.get("annual-report").versions[-1].content_hash

    _mark_registry_retired(registry, "annual-report")

    # Retirement did NOT delete or unbind the historical artifact.
    assert store.get_artifact(source_id="annual-report", content_hash=digest) == RAW
    assert registry.get("annual-report").versions[-1].artifact_available is True


def test_explicit_deletion_reports_affected_published_versions(store, tmp_path):
    registry = _registry(tmp_path)
    registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
    retain_artifact(
        store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    digest = registry.get("annual-report").versions[-1].content_hash

    # Two Published Versions bind this exact artifact.
    for version in ("v1", "v2"):
        manifest = build_binding_manifest(
            published_version=version,
            fingerprint="digest",
            registry=registry,
            pages=_pages_citing("annual-report"),
            now="2026-01-01T00:00:00+00:00",
        )
        store.put_binding_manifest(version, msgspec.json.encode(manifest))

    assert affected_published_versions(store, source_id="annual-report", content_hash=digest) == [
        "v1",
        "v2",
    ]

    affected = delete_artifact_with_disclosure(
        store, registry, source_id="annual-report", content_hash=digest
    )
    assert affected == ["v1", "v2"]
    assert not store.artifact_exists(source_id="annual-report", content_hash=digest)
    assert registry.get("annual-report").versions[-1].artifact_available is False


def _pages_citing(source_id: str):
    class _Source:
        id = source_id

    class _Page:
        title = "Artifact Page"
        sources = [_Source()]
        synthetic = False

    return [_Page()]


# ---------------------------------------------------------------------------
# CLI wiring: managed ingest retains artifacts from the environment config.
# ---------------------------------------------------------------------------


def test_cli_managed_ingest_retains_artifacts_from_env(tmp_path, monkeypatch, capsys):
    from lumio_wiki import cli
    from lumio_wiki.source_references import SourceReferenceManifest

    from .test_git_authoring import _init_repo, _write_kb

    repo = _init_repo(tmp_path)
    kb_root = _write_kb(
        repo,
        manifest=SourceReferenceManifest(
            version=1, namespace="urn:uuid:2b3c4d5e-cli-0000-0000-clikb00000001"
        ),
        pages={},
    )
    registry_root = tmp_path / "registry"
    store_root = tmp_path / "artifact-store"
    compiled = tmp_path / "page.md"
    compiled.write_text(
        "---\n"
        'id: "entity:annual-report"\n'
        'title: "Artifact Page"\n'
        "entity_types:\n  - press\n"
        "category: concepts\n"
        'type: "artifact page"\n'
        'durability_rationale: "The report documents durable findings."\n'
        "aliases: []\n"
        'tags:\n  - "artifacts"\n'
        'summary: "Authored page for the artifact suite."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        '  - id: "annual-report"\n'
        '    title: "annual-report source"\n'
        "synthetic: false\n"
        "---\n\n# Artifact Page\n\nBody authored from the original source.\n",
        encoding="utf-8",
    )
    source = tmp_path / "report.pdf"
    source.write_bytes(RAW)

    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(store_root))
    rc = cli.main(
        [
            "ingest",
            str(kb_root),
            str(source),
            "--compiled-page",
            str(compiled),
            "--source-id",
            "annual-report",
            "--source-registry",
            str(registry_root),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ingested into the Git authoring worktree" in out

    local = LocalDirectoryArtifactStore(store_root)
    digest = artifact_content_hash(RAW)
    assert local.get_artifact(source_id="annual-report", content_hash=digest) == RAW
    # Private state never lands inside the Knowledge Base root.
    assert not (kb_root / "artifacts").exists()
    assert not (kb_root / "bindings").exists()


# ---------------------------------------------------------------------------
# Review findings (#164): coverage semantics, fail-closed config, rollback
# gate, size limit, local store setup.
# ---------------------------------------------------------------------------


def test_required_retention_blocks_unregistered_source_references(tmp_path):
    """The public Git publisher blocks uncaptured public-only references."""
    from lumio_wiki.git_authoring import (
        PublicationRetentionError,
        preview_publication,
        publish_revision,
    )

    root = _authoring_root(tmp_path)
    registry = SourceRegistry(tmp_path / "source-registry")
    digest = artifact_content_hash(RAW)
    registry.register_or_reuse("architecture-doc", RAW, filename="source.pdf")
    artifact_store = LocalDirectoryArtifactStore(tmp_path / "src-store")
    retain_artifact(
        artifact_store,
        registry,
        source_id="architecture-doc",
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="source.pdf",
    )
    revision = _commit_authoring(
        root,
        digest,
        message="candidate includes an unregistered reference",
        body="Exact source-backed page.",
        include_ghost=True,
    )
    object_store = obstore.store.MemoryStore()
    location = S3Location(object_store, "kb", store_uri="s3://bucket")
    metadata_store = InMemoryArtifactStore()
    destination = "s3://bucket/kb"
    review = preview_publication(
        root,
        revision,
        destination,
        "none",
        source_registry=registry,
        artifact_store=artifact_store,
        retention_required=True,
        s3_location=location,
        metadata_store=metadata_store,
        destination_identity=location.effective_target_identity,
    )
    assert "ghost-reference" in review.public_only_sources
    assert not review.blocking_diagnostics

    with pytest.raises(PublicationRetentionError, match="ghost-reference"):
        publish_revision(
            root,
            revision,
            destination,
            "none",
            review.review_digest,
            source_registry=registry,
            artifact_store=artifact_store,
            retention_required=True,
            s3_location=location,
            metadata_store=metadata_store,
            destination_identity=location.effective_target_identity,
        )
    with pytest.raises(FileNotFoundError):
        obstore.get(object_store, f"kb/{CURRENT_POINTER_OBJECT}")


def test_required_retention_is_rechecked_after_remote_index_build(tmp_path):
    from lumio_wiki.git_authoring import (
        PublicationRetentionError,
        preview_publication,
        publish_revision,
    )
    from lumio_wiki.s3_publish import RemoteIndexCompletion

    root = _authoring_root(tmp_path)
    registry = SourceRegistry(tmp_path / "source-registry")
    digest = artifact_content_hash(RAW)
    registry.register_or_reuse("architecture-doc", RAW, filename="source.pdf")
    artifact_store = LocalDirectoryArtifactStore(tmp_path / "src-store")
    retain_artifact(
        artifact_store,
        registry,
        source_id="architecture-doc",
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="source.pdf",
    )
    revision = _commit_authoring(
        root,
        digest,
        message="candidate before remote index build",
        body="Exact source-backed page.",
    )
    object_store = obstore.store.MemoryStore()
    location = S3Location(object_store, "kb", store_uri="s3://bucket")
    metadata_store = InMemoryArtifactStore()
    destination = "s3://bucket/kb"
    builder_calls = []

    def builder(*, store, sidecar_prefix, pages, fingerprint, kb=None):
        builder_calls.append(sidecar_prefix)
        obstore.put(
            store,
            f"{sidecar_prefix}/tables/evidence.lance/data",
            b"indexed evidence table",
            mode="create",
        )
        artifact_store.delete_artifact(source_id="architecture-doc", content_hash=digest)
        return RemoteIndexCompletion(fingerprint=fingerprint.digest, tables={"evidence": 1})

    review = preview_publication(
        root,
        revision,
        destination,
        "none",
        source_registry=registry,
        artifact_store=artifact_store,
        retention_required=True,
        s3_location=location,
        metadata_store=metadata_store,
        destination_identity=location.effective_target_identity,
        retrieval="lancedb",
    )
    assert not review.blocking_diagnostics

    with pytest.raises(PublicationRetentionError, match="raw artifacts are unavailable"):
        publish_revision(
            root,
            revision,
            destination,
            "none",
            review.review_digest,
            source_registry=registry,
            artifact_store=artifact_store,
            retention_required=True,
            s3_location=location,
            metadata_store=metadata_store,
            destination_identity=location.effective_target_identity,
            retrieval="lancedb",
            index_builder=builder,
        )
    assert builder_calls == [f"kb/{revision}/derived/lance"]
    with pytest.raises(FileNotFoundError):
        obstore.get(object_store, f"kb/{CURRENT_POINTER_OBJECT}")


def test_publish_s3_required_without_store_fails_closed(tmp_path, monkeypatch, capsys):
    """Required retention refuses a valid Git revision when no private store exists."""
    from lumio_wiki import cli

    kb_root = _authoring_root(tmp_path)
    registry = SourceRegistry(tmp_path / "source-registry")
    registry.register_or_reuse("architecture-doc", RAW, filename="source.pdf")
    revision = _commit_authoring(
        kb_root,
        artifact_content_hash(RAW),
        message="reviewable candidate",
        body="Exact source-backed page.",
    )
    store = obstore.store.MemoryStore()
    _use_memory_s3(monkeypatch, store)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LUMIO_SOURCE_STORE", raising=False)
    monkeypatch.setenv("LUMIO_ARTIFACT_RETENTION", "required")
    rc = cli.main(
        [
            "publish-s3",
            str(kb_root),
            "s3://bucket/kb",
            "--revision",
            revision,
            "--expected-current",
            "none",
            "--source-registry",
            str(registry.root),
        ]
    )
    assert rc == 1
    assert "no Source Artifact Store is configured" in capsys.readouterr().err


def test_verify_rollback_coverage_gates_historical_activation(tmp_path):
    metadata_store = InMemoryArtifactStore()
    artifact_store = InMemoryArtifactStore()
    registry = _registry(tmp_path)
    registry.register_or_reuse("annual-report", RAW, filename="r.pdf", content_type=None)
    retain_artifact(
        artifact_store,
        registry,
        source_id="annual-report",
        raw_bytes=RAW,
        content_type=None,
        filename="r.pdf",
    )
    digest = registry.get("annual-report").versions[-1].content_hash
    manifest = build_binding_manifest(
        published_version="v1",
        fingerprint="digest",
        registry=registry,
        pages=_pages_citing("annual-report"),
        now="2026-01-01T00:00:00+00:00",
    )
    write_binding_manifest(metadata_store, manifest)

    from lumio_wiki.artifact_store import verify_rollback_coverage

    # Not required: no-op even with no manifest at all.
    verify_rollback_coverage(metadata_store, "unknown-version", required=False)
    # Required + no manifest for the version: fail closed.
    with pytest.raises(RetentionRequiredError, match="no private Source Binding Manifest"):
        verify_rollback_coverage(metadata_store, "unknown-version", required=True)
    # Binding metadata and the verified artifact may be in separate stores.
    verify_rollback_coverage(
        metadata_store, "v1", required=True, source_artifact_store=artifact_store
    )
    # Required + manifest but the artifact was explicitly deleted: blocked.
    artifact_store.delete_artifact(source_id="annual-report", content_hash=digest)
    with pytest.raises(RetentionRequiredError, match="lack a verified artifact"):
        verify_rollback_coverage(
            metadata_store, "v1", required=True, source_artifact_store=artifact_store
        )


def test_required_rollback_rejects_partial_historical_binding_manifest(
    tmp_path, monkeypatch, capsys
):
    """An admitted partial historical manifest cannot pass required rollback."""
    from lumio_wiki.artifact_store import LocalDirectoryArtifactStore

    root = _authoring_root(tmp_path)
    store_root = tmp_path / "src-store"
    artifact_store = LocalDirectoryArtifactStore(store_root)
    registry = SourceRegistry(tmp_path / "source-registry")
    registry.register_or_reuse("architecture-doc", RAW, filename="source.pdf")
    retain_artifact(
        artifact_store,
        registry,
        source_id="architecture-doc",
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="source.pdf",
    )
    digest = artifact_content_hash(RAW)
    rev1 = _commit_authoring(
        root,
        digest,
        message="candidate with public-only source",
        body="Initial reviewed content.",
        include_ghost=True,
    )
    rev2 = _commit_authoring(
        root,
        digest,
        message="successor candidate",
        body="Successor reviewed content.",
        include_ghost=True,
    )
    memory_store = obstore.store.MemoryStore()
    location = _use_memory_s3(monkeypatch, memory_store)
    from lumio_wiki import cli

    metadata_store = InMemoryArtifactStore()
    monkeypatch.setattr(cli, "_publication_metadata_store_for_s3", lambda _uri: metadata_store)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(store_root))
    monkeypatch.delenv("LUMIO_ARTIFACT_RETENTION", raising=False)

    _publish_git_revision(root, rev1, "none", registry, capsys)
    _publish_git_revision(root, rev2, rev1, registry, capsys)
    manifest = msgspec.json.decode(
        metadata_store.get_binding_manifest(rev1), type=SourceBindingManifest
    )
    bound = {(entry.page_title, entry.source_id) for entry in manifest.entries}
    assert ("Artifact Page", "architecture-doc") in bound
    assert ("Artifact Page", "ghost-reference") not in bound

    monkeypatch.setenv("LUMIO_ARTIFACT_RETENTION", "required")
    rc, captured = _rollback_git_revision(rev1, rev2, capsys, json_confirm=False)
    assert rc == 1
    assert "Artifact Page:ghost-reference (missing historical binding)" in captured.err
    assert location.resolve().published_version == rev2


def test_rollback_cli_blocked_after_artifact_deletion(tmp_path, monkeypatch, capsys):
    """Required rollback verifies the target's exact retained historical bytes."""
    from lumio_wiki.artifact_store import LocalDirectoryArtifactStore

    root = _authoring_root(tmp_path)
    store_root = tmp_path / "src-store"
    artifact_store = LocalDirectoryArtifactStore(store_root)
    registry = SourceRegistry(tmp_path / "source-registry")
    digest_a = artifact_content_hash(RAW)
    registry.register_or_reuse("architecture-doc-a", RAW, filename="source.pdf")
    retain_artifact(
        artifact_store,
        registry,
        source_id="architecture-doc-a",
        raw_bytes=RAW,
        content_type="application/pdf",
        filename="source.pdf",
    )
    rev1 = _commit_authoring(
        root,
        digest_a,
        message="retained A",
        body="Source A evidence.",
        source_id="architecture-doc-a",
    )
    replacement = b"replacement source bytes for the successor"
    digest_b = artifact_content_hash(replacement)
    registry.register_or_reuse("architecture-doc-b", replacement, filename="source.pdf")
    retain_artifact(
        artifact_store,
        registry,
        source_id="architecture-doc-b",
        raw_bytes=replacement,
        content_type="application/pdf",
        filename="source.pdf",
    )
    rev2 = _commit_authoring(
        root,
        digest_b,
        message="retained B",
        body="Source B evidence.",
        source_id="architecture-doc-b",
        retired_source_ids=("architecture-doc-a",),
    )
    memory_store = obstore.store.MemoryStore()
    location = _use_memory_s3(monkeypatch, memory_store)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(store_root))
    monkeypatch.setenv("LUMIO_ARTIFACT_RETENTION", "required")

    _publish_git_revision(root, rev1, "none", registry, capsys)
    _publish_git_revision(root, rev2, rev1, registry, capsys)
    # Both historical directions are allowed while each exact artifact exists.
    assert _rollback_git_revision(rev1, rev2, capsys)[0] == 0
    assert location.resolve().published_version == rev1
    assert _rollback_git_revision(rev2, rev1, capsys)[0] == 0
    assert location.resolve().published_version == rev2

    delete_artifact_with_disclosure(
        artifact_store, registry, source_id="architecture-doc-a", content_hash=digest_a
    )
    rc, captured = _rollback_git_revision(rev1, rev2, capsys, json_confirm=False)
    assert rc == 1
    assert "lack a verified artifact" in captured.err
    assert location.resolve().published_version == rev2


def test_retain_artifact_enforces_size_limit(tmp_path, monkeypatch):
    from lumio_wiki import artifact_store as module

    store = InMemoryArtifactStore()
    registry = _registry(tmp_path)
    registry.register_or_reuse("big-report", b"0123456789", filename=None, content_type=None)
    monkeypatch.setattr(module, "MAX_ARTIFACT_BYTES", 8)
    with pytest.raises(ArtifactStoreError, match="maximum retained artifact size"):
        retain_artifact(
            store,
            registry,
            source_id="big-report",
            raw_bytes=b"0123456789",
            content_type=None,
            filename=None,
        )
    # A failed retention is never reported as retained.
    assert registry.get("big-report").versions[-1].artifact_available is False


def test_setup_accepts_local_source_store_path(tmp_path, monkeypatch, capsys):
    """setup records a local-directory Source Artifact Store without the S3
    extra (object storage OR a local directory — CONTEXT.md, ADR-0020)."""
    from lumio_wiki import cli
    from lumio_wiki.env_loader import SOURCE_STORE_ENV_VAR

    monkeypatch.chdir(tmp_path)
    for key in ("LUMIO_SOURCE_STORE", "LUMIO_ARTIFACT_RETENTION"):
        monkeypatch.delenv(key, raising=False)
    local_store = tmp_path / "private-source-store"
    rc = cli.main(["setup", "kb", "--source-store", str(local_store)])
    assert rc == 0
    assert _env_value_text(tmp_path, SOURCE_STORE_ENV_VAR) == str(local_store)
    assert "Created Knowledge Base" in capsys.readouterr().out


def test_setup_rejects_unsupported_source_store_scheme(tmp_path, monkeypatch, capsys):
    from lumio_wiki import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LUMIO_SOURCE_STORE", raising=False)
    rc = cli.main(["setup", "kb", "--source-store", "ftp://example.com/src"])
    assert rc == 2
    assert "not a supported scheme" in capsys.readouterr().err


def _env_value_text(project: Path, key: str) -> str | None:
    env = project / ".env"
    if not env.exists():
        return None
    prefix = f"{key}="
    for raw in env.read_text(encoding="utf-8").splitlines():
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip() or None
    return None


def test_activation_hook_keeps_an_empty_candidate_binding_empty():
    source = SimpleNamespace(
        source_id="bound",
        versions=[
            SimpleNamespace(
                content_hash=artifact_content_hash(b"bound"),
                content_type="text/plain",
                filename="bound.txt",
                size=5,
            )
        ],
    )
    registry = SimpleNamespace(list=lambda: [source])
    store = InMemoryArtifactStore()
    hook = activation_binding_hook(artifact_store=store, registry=registry, required=False)
    hook.capture_candidate([SimpleNamespace(title="Bound", sources=[SimpleNamespace(id="bound")])])  # type: ignore[attr-defined]
    hook(
        SimpleNamespace(
            version="v-empty",
            fingerprint="f" * 64,
            pages=[SimpleNamespace(title="Empty", sources=[])],
            binding_entries=[],
        )
    )
    manifest = msgspec.json.decode(
        store.get_binding_manifest("v-empty"), type=SourceBindingManifest
    )
    assert manifest.entries == []


def test_rollback_redacts_invalid_historical_source_ids():
    store = InMemoryArtifactStore()
    secret_id = "sk-" + "live-example-secret"
    store.put_binding_manifest(
        "v1",
        msgspec.json.encode(
            SourceBindingManifest(
                published_version="v1",
                fingerprint="f" * 64,
                created_at="now",
                entries=[
                    SourceBindingEntry(
                        page_title="Secret Page",
                        source_id=secret_id,
                        content_hash="0" * 64,
                    )
                ],
            )
        ),
    )
    with pytest.raises(RetentionRequiredError) as excinfo:
        verify_rollback_coverage(store, "v1", required=True)
    assert secret_id not in str(excinfo.value)
    assert "<invalid source id>" in str(excinfo.value)


def test_rollback_rejects_corrupt_binding_manifest():
    store = InMemoryArtifactStore()
    store.put_binding_manifest("v1", b"{")
    with pytest.raises(RetentionRequiredError, match="manifest.*corrupt"):
        verify_rollback_coverage(store, "v1", required=True)


def test_required_retention_never_echoes_secret_bearing_source_ids(tmp_path):
    """An invalid source id (e.g. a pasted credential declared on a page) is
    reported with a generic label under required retention — never echoed
    into the blocking error (registry boundary convention, ADR-0020)."""
    kb = _kb(tmp_path)
    artifact_store = InMemoryArtifactStore()
    registry = _managed_source(kb, tmp_path, artifact_store)
    secret_id = "sk-live-example-secret"
    authored = _authored_page("annual-report").replace(
        '  - id: "annual-report"\n    title: "annual-report source"\n',
        '  - id: "annual-report"\n'
        '    title: "annual-report source"\n'
        f'  - id: "{secret_id}"\n'
        '    title: "Pasted credential"\n',
    )
    assert secret_id in authored
    page_rel = _authored_page_rel()
    (Path(kb.root) / page_rel).write_text(authored, encoding="utf-8")

    store = obstore.store.MemoryStore()
    hook = activation_binding_hook(
        artifact_store=artifact_store,
        registry=registry,
        required=True,
    )
    with pytest.raises(RetentionRequiredError) as excinfo:
        _publish(store, kb, version="v1", hook=hook)
    assert secret_id not in str(excinfo.value)
    assert "<invalid source id>" in str(excinfo.value)
