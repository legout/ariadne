from __future__ import annotations

import hashlib
import importlib
import json
import re
import shlex
import shutil
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import pytest
from ariadne import admission, authoring_sources, draft, execution
from ariadne import sources as native_sources
from ariadne.authoring import AuthoringProject
from lumio_wiki.ariadne_context import SnapshotUnavailableError
from lumio_wiki.artifact_store import (
    ArtifactUnavailable,
    LocalDirectoryArtifactStore,
    S3ArtifactStore,
    retain_artifact,
)
from lumio_wiki.git_authoring import (
    PRIVATE_OPERATIONS_DIR,
    ConfirmationRefused,
    GitAuthoringError,
    preview_publication,
    publish_revision,
    rollback_publication,
)
from lumio_wiki.location import VERSIONS_DIR_NAME, PublishedFilesystemLocation
from lumio_wiki.private_profile import load_private_profile, resolve_private_profile
from lumio_wiki.source_inspection import (
    SourceInspectionError,
    read_local_published_bindings,
)
from lumio_wiki.source_registry import SourceRegistry
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
from lumio_workspace.analytics import AnalyticsError, AnalyticsService
from lumio_workspace.contributions import ContributionService
from lumio_workspace.intake import IntakeService
from lumio_workspace.operations import OperationsError, quiesced_backup, restore
from lumio_workspace.operations import main as operations_main
from lumio_workspace.review import ReviewError, ReviewService
from lumio_workspace.setup import current_attachment_digest
from starlette.testclient import TestClient

_analytics_fixtures = importlib.import_module(
    "products.lumio.packages.lumio-workspace.tests.test_workspace_analytics"
)
_review = importlib.import_module(
    "products.lumio.packages.lumio-workspace.tests.test_workspace_review"
)
_call_tool = _review._call_tool
_confirm_setup = _review._confirm_setup
_contribute = _review._contribute
_decision = _review._decision
_digest = _review._digest
_fixture = _review._fixture
_git = _review._git
_login = _review._login
_prepare = _review._prepare
_upload = _review._upload

TITLE_A = "Operations Runbook"
TITLE_B = "Operations Followup"
ADDITION_A = "Version A: quiesce, back up, and restore before swapping the data root."
ADDITION_B = "Version B stays pending until a fresh review."
# Independent oracle: the admitted body is exactly the reviewed page markdown.
EXPECTED_A_BODY = (
    "# Operations Runbook\n\nStop the old worker.\n\n<unsafe>&review\n\n"
    "Version A: quiesce, back up, and restore before swapping the data root."
)

# --- R4/#106 oracle: authored bytes, hashes, records (never implementation output).
ALPHA_TITLE = "Recovery Alpha"
BETA_TITLE = "Recovery Beta"
GAMMA_TITLE = "Recovery Gamma"
ALPHA_SOURCE = "recovery-alpha-source"
BETA_SOURCE = "recovery-beta-source"
GAMMA_SOURCE = "recovery-gamma-source"
DELTA_SOURCE = "recovery-delta-source"
UNRETAINED_SOURCE = "recovery-unretained-source"
ALPHA_ADDITION = "Alpha addition: retained original bytes must survive recovery."
BETA_ADDITION = "Beta addition: a second exact version with its own binding."
GAMMA_ADDITION = "Gamma addition: the first contribution published after restore."
DELTA_ADDITION = "Delta addition: pending before the backup; its old action must never activate."
ALPHA_ORIGINAL = b"# Recovery Alpha original\r\n\r\nFirst retained version bytes.\r\n"
BETA_ORIGINAL = b"# Recovery Beta original\r\n\r\nSecond retained version bytes.\r\n"
GAMMA_ORIGINAL = b"# Recovery Gamma original\r\n\r\nPost-restore contribution bytes.\r\n"
DELTA_ORIGINAL = b"# Recovery Delta original\r\n\r\nPending candidate bytes.\r\n"
# Authored but never stored anywhere: the backup must record it as unretained.
UNRETAINED_ORIGINAL = b"# draft bytes that no artifact store ever retained"
ALPHA_HASH = hashlib.sha256(ALPHA_ORIGINAL).hexdigest()
BETA_HASH = hashlib.sha256(BETA_ORIGINAL).hexdigest()
GAMMA_HASH = hashlib.sha256(GAMMA_ORIGINAL).hexdigest()
DELTA_HASH = hashlib.sha256(DELTA_ORIGINAL).hexdigest()
UNRETAINED_HASH = hashlib.sha256(UNRETAINED_ORIGINAL).hexdigest()
EXPECTED_ALPHA_BODY = (
    "# Recovery Alpha\n\nStop the old worker.\n\n<unsafe>&review\n\n" + ALPHA_ADDITION
)
# Planted private record categories (the metadata-store role of the same
# adapter): opaque authored bytes replayed verbatim by backup and restore.
PUBLICATION_RECORD = b'{"kind":"workspace-fixture publication record"}'
ACTIVATION_RECEIPT = b'{"kind":"workspace-fixture activation receipt"}'


def _s3_profile(config, monkeypatch) -> Path:
    """Rebind the fixture profile to the private S3 artifact store.

    Credentials are declared environment-variable NAMES with synthetic
    values; the endpoint is never contacted because the store construction
    seam is injected below.
    """
    profile = json.loads(config.private_profile_path.read_text(encoding="utf-8"))
    profile["artifact_store"] = {
        "kind": "s3",
        "bucket": "workspace-originals",
        "prefix": "originals",
        "endpoint": "http://127.0.0.1:1",
        "region": "us-east-1",
        "url_style": "path",
        "credentials": {
            "access_key_id_env": "LUMIO_TEST_S3_ACCESS_KEY",
            "secret_access_key_env": "LUMIO_TEST_S3_SECRET_KEY",
        },
    }
    config.private_profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setenv("LUMIO_TEST_S3_ACCESS_KEY", "synthetic-access-key")
    monkeypatch.setenv("LUMIO_TEST_S3_SECRET_KEY", "synthetic-secret-key")
    return Path(profile["source_registry"])


def _contribute_bytes(
    client: TestClient, fixture, *, retry_key, title, addition, source_id, raw, request_id
) -> dict:
    uploaded = _upload(client, fixture.contributor_api, raw, retry_key, source_id)
    assert uploaded.status_code == 200, uploaded.text
    prepared = _prepare(
        client,
        fixture.contributor_api,
        retry_key=retry_key,
        upload_id=uploaded.json()["upload_id"],
        title=title,
        addition=addition,
        source_id=source_id,
        filename="recovery-original.md",
        request_id=request_id,
    )
    result = prepared.json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


def _approve(reviewer: TestClient, fixture, task_id: str) -> str:
    digest = _digest(reviewer.get(f"/review/{task_id}").text)
    approved = _decision(reviewer, task_id, digest, "approve")
    assert approved.status_code == 200, approved.text
    return digest


def _tree_digest(root: Path) -> str:
    """Content digest of every persisted file under one directory."""
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_remote_original_backup_restores_without_remote_store(tmp_path: Path, monkeypatch) -> None:
    """AC26: an S3-backed workspace survives fresh-root restore self-contained.

    The private S3 artifact store is the real adapter over a synthetic
    obstore MemoryStore injected at the one construction seam the profile
    resolver uses — backup/restore itself runs unmocked. Authored v1/v2
    bytes and hashes, planted private records, and one honestly unretained
    version form the oracle; the remote store is emptied after backup so the
    restored workspace must serve everything from its new local store.
    """
    import obstore

    fixture = _fixture(tmp_path, monkeypatch)
    config = fixture.config
    registry_root = _s3_profile(config, monkeypatch)
    # Synthetic network driver at the real external I/O seam: every S3 client
    # the profile resolver constructs is this shared MemoryStore.
    remote = obstore.store.MemoryStore()
    monkeypatch.setattr(
        obstore.store,
        "S3Store",
        lambda *args, **kwargs: remote,
    )
    remote_store = S3ArtifactStore(remote, "originals")
    # The reviewer may inspect historical originals through /original only
    # with the separate grant; it is provisioned before the backup travels.
    fixture.state.grant(config.workspace_id, fixture.reviewer, "inspect_source")

    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
    ):
        _confirm_setup(owner, fixture)
        task_alpha = _contribute_bytes(
            contributor,
            fixture,
            retry_key="recovery-alpha",
            title=ALPHA_TITLE,
            addition=ALPHA_ADDITION,
            source_id=ALPHA_SOURCE,
            raw=ALPHA_ORIGINAL,
            request_id=1,
        )
        _login(reviewer, fixture.reviewer_browser)
        _approve(reviewer, fixture, task_alpha["task_id"])
        version_a = PublishedFilesystemLocation(config.published_path).read_pointer()
        assert version_a is not None
        assert version_a == task_alpha["native_candidate"]
        task_beta = _contribute_bytes(
            contributor,
            fixture,
            retry_key="recovery-beta",
            title=BETA_TITLE,
            addition=BETA_ADDITION,
            source_id=BETA_SOURCE,
            raw=BETA_ORIGINAL,
            request_id=2,
        )
        _approve(reviewer, fixture, task_beta["task_id"])
        version_b = PublishedFilesystemLocation(config.published_path).read_pointer()
        assert version_b is not None
        assert version_b == task_beta["native_candidate"]
        # A pending candidate prepared before the backup: its outstanding
        # browser action must never activate after the restore.
        task_delta = _contribute_bytes(
            contributor,
            fixture,
            retry_key="recovery-delta",
            title="Recovery Delta",
            addition=DELTA_ADDITION,
            source_id=DELTA_SOURCE,
            raw=DELTA_ORIGINAL,
            request_id=3,
        )
        outstanding = _digest(reviewer.get(f"/review/{task_delta['task_id']}").text)

    # Supported store APIs, written by the same adapter role that S3
    # publication uses for private record categories (bound to v1).
    remote_store.put_publication_record(version_a, PUBLICATION_RECORD)
    remote_store.put_activation_receipt(version_a, ACTIVATION_RECEIPT)
    # An intentionally unretained version: registered metadata only, never
    # bytes (the exact registry import seam for metadata-only versions).
    registry = SourceRegistry(registry_root)
    registry.register_version_metadata(
        UNRETAINED_SOURCE, UNRETAINED_HASH, size=len(UNRETAINED_ORIGINAL), filename="draft.md"
    )

    # A required retained version whose bytes are unreadable aborts the
    # backup before any final manifest exists.
    assert remote_store.delete_artifact(source_id=ALPHA_SOURCE, content_hash=ALPHA_HASH)
    with pytest.raises(OperationsError, match="could not be copied"):
        quiesced_backup(config, tmp_path / "failed-backup")
    assert not (tmp_path / "failed-backup").exists()
    # Recover the store state through the idempotent retention saga.
    retain_artifact(
        remote_store,
        registry,
        source_id=ALPHA_SOURCE,
        raw_bytes=ALPHA_ORIGINAL,
        content_type=None,
        filename="recovery-original.md",
    )
    assert remote_store.get_artifact(source_id=ALPHA_SOURCE, content_hash=ALPHA_HASH) == (
        ALPHA_ORIGINAL
    )

    backup_root = quiesced_backup(config, tmp_path / "workspace-backup")
    manifest = json.loads((backup_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["workspace_id"] == config.workspace_id
    retained = {
        (entry["source_id"], entry["content_hash"]): entry
        for entry in manifest["retained_source_artifacts"]
    }
    assert set(retained) == {
        (ALPHA_SOURCE, ALPHA_HASH),
        (BETA_SOURCE, BETA_HASH),
        (DELTA_SOURCE, DELTA_HASH),
    }
    assert retained[(ALPHA_SOURCE, ALPHA_HASH)]["size"] == len(ALPHA_ORIGINAL)
    assert manifest["unretained_source_versions"] == [
        {"source_id": UNRETAINED_SOURCE, "content_hash": UNRETAINED_HASH}
    ]
    assert manifest["store_versions"] == [
        {
            "version": version,
            "publication_record": version == version_a,
            "activation_receipt": version == version_a,
        }
        for version in sorted((version_a, version_b))
    ]

    # The remote endpoint goes away entirely: nothing may serve from it.
    for batch in obstore.list(remote):
        for obj in batch:
            obstore.delete(remote, obj["path"])
    assert [obj for batch in obstore.list(remote) for obj in batch] == []

    second_root = tmp_path / "restored-data-root"
    restored = restore(backup_root, second_root, replace(config, published_version=None))
    assert restored.authoring_path is not None
    assert restored.state_path == second_root / "state.sqlite3"
    assert restored.private_root == second_root / "private"
    assert restored.authoring_path == second_root / "authoring-repo" / "kb"
    assert restored.published_path == second_root / "published"
    assert restored.private_profile_path == second_root / "profile.json"
    # The restored profile materializes a NEW LOCAL store; the remote
    # connection is deliberately not copied into the mutable configuration.
    restored_profile_path = restored.private_profile_path
    assert restored_profile_path is not None
    restored_profile = json.loads(restored_profile_path.read_text(encoding="utf-8"))
    assert restored_profile["artifact_store"] == {
        "kind": "local",
        "root": str(second_root / "artifacts"),
    }
    restored_store = LocalDirectoryArtifactStore(second_root / "artifacts")
    # Exact authored bytes come back digest-verified, with the remote gone.
    assert restored_store.get_artifact(source_id=ALPHA_SOURCE, content_hash=ALPHA_HASH) == (
        ALPHA_ORIGINAL
    )
    assert restored_store.get_artifact(source_id=BETA_SOURCE, content_hash=BETA_HASH) == (
        BETA_ORIGINAL
    )
    # Planted private record categories replayed verbatim.
    assert restored_store.get_publication_record(version_a) == PUBLICATION_RECORD
    assert restored_store.get_activation_receipt(version_a) == ACTIVATION_RECEIPT
    # Unretained stays honestly unavailable — absence, not corruption.
    with pytest.raises(ArtifactUnavailable):
        restored_store.get_artifact(source_id=UNRETAINED_SOURCE, content_hash=UNRETAINED_HASH)
    assert (
        restored_store.artifact_exists(source_id=UNRETAINED_SOURCE, content_hash=UNRETAINED_HASH)
        is False
    )
    restored_registry = SourceRegistry(second_root / "registry")
    assert restored_registry.get(UNRETAINED_SOURCE).versions[-1].artifact_available is False

    # Exact target binding: a copied tree carries its marker, but the marker
    # authorizes exactly the original resolved destination — the copy gets
    # strict destination checks and refuses.
    copied_published = tmp_path / "copied-published"
    shutil.copytree(restored.published_path, copied_published)
    with pytest.raises(SourceInspectionError):
        read_local_published_bindings(copied_published, version_a)
    # Exact import binding: a swapped receipt is an altered import and gains
    # no tolerance either.
    swapped_published = tmp_path / "swapped-published"
    shutil.copytree(restored.published_path, swapped_published)
    receipts_dir = swapped_published / ".lumio-publication" / "receipts"
    (receipts_dir / f"{version_a}.json").write_bytes(
        (receipts_dir / f"{version_b}.json").read_bytes()
    )
    with pytest.raises(SourceInspectionError):
        read_local_published_bindings(swapped_published, version_a)

    # SDK boundary, replayed OLD-target confirmations at the restored
    # destination refuse without moving the pointer or touching the imported
    # receipt. The publication retry guard fires while the pointer still
    # names the imported version; the separate rollback path refuses the
    # old confirmation because its recomputed current-target review digest
    # can no longer match.
    assert restored_profile_path is not None
    restored_resources = resolve_private_profile(
        load_private_profile(restored_profile_path, kb_root=restored.authoring_path),
        kb_root=restored.authoring_path,
        needs=frozenset({"registry", "artifacts"}),
    )
    imported_before = read_local_published_bindings(restored.published_path, version_b)
    # The old confirmation being replayed is the one recorded in the copied
    # (imported) admission receipt itself — exactly what an operator retry
    # of the pre-restore publication would carry.
    old_beta_confirmation = imported_before[0].review_digest
    old_alpha_confirmation = read_local_published_bindings(restored.published_path, version_a)[
        0
    ].review_digest
    with pytest.raises(
        ConfirmationRefused, match="restored target requires a fresh reviewed confirmation"
    ):
        publish_revision(
            restored.authoring_path,
            version_b,
            restored.published_path,
            version_b,
            old_beta_confirmation,
            source_registry=restored_resources.source_registry,
            artifact_store=restored_resources.artifact_store,
            retention_required=True,
        )
    with pytest.raises(ConfirmationRefused, match="no longer matches the recomputed"):
        rollback_publication(
            restored.published_path,
            version_a,
            version_b,
            old_alpha_confirmation,
        )
    assert read_local_published_bindings(restored.published_path, version_b) == imported_before
    assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_b

    # F1 (review finding 1): a FRESH preview/confirm of the ACTIVE imported
    # revision (B, pointer-equal) refuses BEFORE any sealed/store/receipt
    # mutation — sealed bytes, imported receipt, store binding, and pointer
    # stay exactly as restored, and historical reads keep working.
    fresh_review = preview_publication(
        restored.authoring_path,
        version_b,
        restored.published_path,
        version_b,
        source_registry=restored_resources.source_registry,
        artifact_store=restored_resources.artifact_store,
        retention_required=True,
    )
    assert fresh_review.review_digest != old_beta_confirmation
    imported_before_fresh = read_local_published_bindings(restored.published_path, version_b)
    store_binding_before = restored_store.get_binding_manifest(version_b)
    with pytest.raises(GitAuthoringError, match="outside the bounded restore disposition"):
        publish_revision(
            restored.authoring_path,
            version_b,
            restored.published_path,
            version_b,
            fresh_review.review_digest,
            source_registry=restored_resources.source_registry,
            artifact_store=restored_resources.artifact_store,
            retention_required=True,
        )
    assert read_local_published_bindings(restored.published_path, version_b) == (
        imported_before_fresh
    )
    assert restored_store.get_binding_manifest(version_b) == store_binding_before
    assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_b

    with (
        TestClient(create_app(restored), base_url="https://workspace.test") as owner2,
        TestClient(create_app(restored), base_url="https://workspace.test") as contributor2,
        TestClient(create_app(restored), base_url="https://workspace.test") as reviewer2,
    ):
        # Admitted v1 stays readable; the current publication cites the
        # current pointer (v2 carries the alpha page), and the exact
        # historical version reread still cites v1.
        admitted = _call_tool(
            contributor2, fixture.contributor_api, "read_knowledge", {"title": ALPHA_TITLE}, 20
        ).json()["result"]
        assert admitted["isError"] is False, admitted
        assert admitted["structuredContent"]["markdown"].strip() == EXPECTED_ALPHA_BODY
        assert admitted["structuredContent"]["citation"]["published_version"] == version_b
        historical = _call_tool(
            contributor2,
            fixture.contributor_api,
            "read_knowledge",
            {"title": ALPHA_TITLE, "published_version": version_a},
            22,
        ).json()["result"]
        assert historical["isError"] is False, historical
        assert historical["structuredContent"]["citation"]["published_version"] == version_a
        _login(reviewer2, fixture.reviewer_browser)
        for version, entity, source_id, raw in (
            (version_a, "entity:recovery-alpha-runbook", ALPHA_SOURCE, ALPHA_ORIGINAL),
            (version_b, "entity:recovery-beta-runbook", BETA_SOURCE, BETA_ORIGINAL),
        ):
            original = reviewer2.get(
                f"/original/{quote(version)}/{quote(entity)}/{quote(source_id)}"
            )
            assert original.status_code == 200, original.text
            assert original.content == raw

        # The pre-restore outstanding action cannot activate anything.
        stale = _decision(reviewer2, task_delta["task_id"], outstanding, "approve")
        assert stale.status_code == 409
        assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_b

        # The moved root changes the setup attachment identity: the owner
        # reconfirms the restored target before new writes are accepted.
        _confirm_setup(owner2, fixture)

        # One fresh standalone contribution is human-reviewed and published
        # on the restored workspace, retained into the new local store.
        task_gamma = _contribute_bytes(
            contributor2,
            fixture,
            retry_key="recovery-gamma",
            title=GAMMA_TITLE,
            addition=GAMMA_ADDITION,
            source_id=GAMMA_SOURCE,
            raw=GAMMA_ORIGINAL,
            request_id=21,
        )
        _approve(reviewer2, fixture, task_gamma["task_id"])
        version_c = PublishedFilesystemLocation(restored.published_path).read_pointer()
        assert version_c is not None
        assert version_c == task_gamma["native_candidate"]
        assert restored_store.get_artifact(source_id=GAMMA_SOURCE, content_hash=GAMMA_HASH) == (
            GAMMA_ORIGINAL
        )

    # Historical immutable identities are unchanged by the new publication.
    assert (
        restored_store.get_binding_manifest(version_a)
        == (backup_root / "store" / "bindings" / f"{version_a}.json").read_bytes()
    )
    assert (
        restored_store.get_binding_manifest(version_b)
        == (backup_root / "store" / "bindings" / f"{version_b}.json").read_bytes()
    )
    assert restored_store.get_publication_record(version_a) == PUBLICATION_RECORD
    assert restored_store.get_activation_receipt(version_a) == ACTIVATION_RECEIPT
    assert [version.content_hash for version in restored_registry.get(ALPHA_SOURCE).versions] == [
        ALPHA_HASH
    ]
    assert restored_registry.get(ALPHA_SOURCE).versions[0].artifact_available is True

    # A manifest this restore does not understand refuses explicitly.
    bogus = tmp_path / "bogus-backup"
    bogus.mkdir()
    (bogus / "manifest.json").write_text(
        json.dumps({"schema_version": 99, "workspace_id": config.workspace_id}),
        encoding="utf-8",
    )
    with pytest.raises(OperationsError, match="unsupported backup format"):
        restore(bogus, tmp_path / "bogus-target", config)


def test_restore_and_revocation_preserve_admitted_only_access(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    config = fixture.config
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
    ):
        _confirm_setup(owner, fixture)
        task_a = _contribute(
            contributor,
            fixture,
            retry_key="operations-version-a",
            title=TITLE_A,
            addition=ADDITION_A,
            source_id="operations-runbook-source",
            filename="operations-runbook.md",
            request_id=1,
        )
        task_b = _contribute(
            contributor,
            fixture,
            retry_key="operations-version-b",
            title=TITLE_B,
            addition=ADDITION_B,
            source_id="operations-followup-source",
            filename="operations-followup.md",
            # Chains from A's candidate, so B stays reviewable after A is admitted.
            continuation_task_id=task_a["task_id"],
            request_id=2,
        )
        _login(reviewer, fixture.reviewer_browser)
        digest_a = _digest(reviewer.get(f"/review/{task_a['task_id']}").text)
        approved_a = _decision(reviewer, task_a["task_id"], digest_a, "approve")
        assert approved_a.status_code == 200, approved_a.text
        version_a = PublishedFilesystemLocation(config.published_path).read_pointer()
        assert version_a is not None
        assert version_a == task_a["native_candidate"]
        # An outstanding browser review action exists for the pending candidate B.
        outstanding = _digest(reviewer.get(f"/review/{task_b['task_id']}").text)

    # Quiesced offline backup, then restore into a second data directory. The
    # restored service resolves the current pointer instead of the old pin.
    backup_root = quiesced_backup(config, tmp_path / "workspace-backup")
    second_root = tmp_path / "second-data-root"
    restored = restore(backup_root, second_root, replace(config, published_version=None))
    assert restored.authoring_path is not None
    assert restored.state_path == second_root / "state.sqlite3"
    assert restored.private_root == second_root / "private"
    assert restored.authoring_path == second_root / "authoring-repo" / "kb"
    assert restored.published_path == second_root / "published"
    assert restored.private_profile_path == second_root / "profile.json"

    with (
        TestClient(create_app(restored), base_url="https://workspace.test") as owner2,
        TestClient(create_app(restored), base_url="https://workspace.test") as contributor2,
        TestClient(create_app(restored), base_url="https://workspace.test") as reviewer2,
    ):
        # Admitted A remains the sole readable version after the restore.
        result_a = _call_tool(
            contributor2, fixture.contributor_api, "read_knowledge", {"title": TITLE_A}, 10
        ).json()["result"]
        assert result_a["isError"] is False, result_a
        read_a = result_a["structuredContent"]
        assert read_a["markdown"].strip() == EXPECTED_A_BODY
        assert read_a["citation"]["published_version"] == version_a
        hidden_b = _call_tool(
            contributor2, fixture.contributor_api, "read_knowledge", {"title": TITLE_B}, 11
        ).json()["result"]
        assert hidden_b["isError"] is False, hidden_b
        assert hidden_b["structuredContent"] == {"found": False}
        pending_b = _call_tool(
            contributor2, fixture.contributor_api, "get_task", {"task_id": task_b["task_id"]}, 12
        ).json()["result"]["structuredContent"]
        assert pending_b["status"] == "pending_review"
        assert pending_b["published"] is False

        # The moved data root changes the setup attachment identity by design;
        # the owner re-confirms the restored target before new writes are accepted.
        _login(owner2, fixture.owner_browser)
        setup_confirm = owner2.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(owner2.get("/setup").text)},
        )
        assert setup_confirm.status_code == 200, setup_confirm.text

        # Restore dropped browser sessions; the reviewer signs in again with the
        # unchanged operator-issued credential, re-established outside content.
        _login(reviewer2, fixture.reviewer_browser)
        fresh_page = reviewer2.get(f"/review/{task_b['task_id']}")
        assert fresh_page.status_code == 200, fresh_page.text
        fresh_digest = _digest(fresh_page.text)
        assert fresh_digest != outstanding
        assert reviewer2.get("/membership").status_code == 403

        # The pre-backup review action cannot activate anything after the restore.
        stale = _decision(reviewer2, task_b["task_id"], outstanding, "approve")
        assert stale.status_code == 409
        assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_a

        # The owner assigns and then removes the reviewer through the browser
        # membership surface; original/source/data access stays off this page.
        listing = owner2.get("/membership")
        assert listing.status_code == 200, listing.text
        assert "reviewer" in listing.text

        def membership_post(**data):
            return owner2.post(
                "/membership", headers={"Origin": "https://workspace.test"}, data=data
            )

        granted = membership_post(user_id="reviewer", capability="read", action="grant")
        assert granted.status_code == 200, granted.text
        assert granted.json()["capabilities"] == ["read", "review"]
        revoked_read = membership_post(user_id="reviewer", capability="read", action="revoke")
        assert revoked_read.status_code == 200, revoked_read.text
        assert revoked_read.json()["capabilities"] == ["review"]
        refused = membership_post(user_id="reviewer", capability="inspect_source", action="grant")
        assert refused.status_code == 400
        revoked_review = membership_post(user_id="reviewer", capability="review", action="revoke")
        assert revoked_review.status_code == 200, revoked_review.text
        assert revoked_review.json()["capabilities"] == []

        # The removed member is denied on both routes despite valid credentials
        # and a fresh session; the API denial follows this page's own grant.
        assert reviewer2.get(f"/review/{task_b['task_id']}").status_code == 403
        assert _decision(reviewer2, task_b["task_id"], fresh_digest, "approve").status_code == 403
        denied_status = _call_tool(
            reviewer2, fixture.reviewer_api, "workspace_status", {}, 13
        ).json()["result"]
        assert denied_status["isError"] is True

        # Nothing activated: A stays the sole readable version and B stays pending.
        assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_a
        still_pending = _call_tool(
            contributor2, fixture.contributor_api, "get_task", {"task_id": task_b["task_id"]}, 14
        ).json()["result"]["structuredContent"]
        assert still_pending["status"] == "pending_review"
        assert still_pending["published"] is False

    # A minimal configured-analytics layout travels with backup/restore.
    analytics_project = tmp_path / "analytics-project"
    analytics_project.mkdir()
    _git(analytics_project, "init", "-q")
    _git(analytics_project, "config", "user.name", "Fixture")
    _git(analytics_project, "config", "user.email", "fixture@example.invalid")
    _git(analytics_project, "commit", "--allow-empty", "-qm", "analytics base")
    proposal_id = "p-0123456789abcd-012345"
    _git(
        analytics_project,
        "worktree",
        "add",
        "-b",
        f"ariadne/proposal/{proposal_id}",
        str(analytics_project / ".ariadne" / "worktrees" / proposal_id),
    )
    analytics_bindings = tmp_path / "analytics-bindings.json"
    analytics_bindings.write_text('{"storages": {}}', encoding="utf-8")
    analytics_config = replace(
        config,
        analytics_project_id="fixture-project",
        analytics_project_path=analytics_project,
        analytics_source_bindings_path=analytics_bindings,
    )
    analytics_backup = quiesced_backup(analytics_config, tmp_path / "analytics-backup")

    # A relative restore target is rejected before anything is copied.
    with pytest.raises(OperationsError, match="absolute path"):
        restore(analytics_backup, Path("relative-data-root"), analytics_config)

    analytics_second = tmp_path / "analytics-second-root"
    analytics_restored = restore(analytics_backup, analytics_second, analytics_config)
    assert analytics_restored.analytics_project_path == analytics_second / "analytics-project"
    assert analytics_restored.analytics_source_bindings_path == (
        analytics_second / "analytics-bindings.json"
    )
    relinked = analytics_second / "analytics-project" / ".ariadne" / "worktrees" / proposal_id
    assert _git(relinked, "rev-parse", "--abbrev-ref", "HEAD") == (
        f"ariadne/proposal/{proposal_id}"
    )

    monkeypatch.setenv("LUMIO_WORKSPACE_AUTH_MODE", "local-token")
    monkeypatch.setenv("LUMIO_WORKSPACE_EXTERNAL_URL", "https://workspace.test")
    monkeypatch.setenv("LUMIO_WORKSPACE_PUBLISHED_PATH", str(config.published_path))
    monkeypatch.setenv("LUMIO_WORKSPACE_ANALYTICS_PROJECT_ID", "fixture-project")
    monkeypatch.setenv("LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH", str(analytics_project))
    monkeypatch.setenv("LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS", str(analytics_bindings))
    analytics_cli_root = tmp_path / "analytics-cli-root"
    arguments = [
        "restore",
        "--backup-root",
        str(analytics_backup),
        "--target-root",
        str(analytics_cli_root),
    ]
    assert operations_main(arguments) == 0
    output = capsys.readouterr().out
    assert (
        f"export LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH={analytics_cli_root / 'analytics-project'}"
        in output
    )
    assert (
        f"export LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS="
        f"{analytics_cli_root / 'analytics-bindings.json'}" in output
    )

    # A whitespace restore target still yields shell-safe assignments whose
    # value evaluates to the full rebased path, plus EnvironmentFile lines.
    analytics_space_root = tmp_path / "workspace new"
    space_arguments = [
        "restore",
        "--backup-root",
        str(analytics_backup),
        "--target-root",
        str(analytics_space_root),
    ]
    assert operations_main(space_arguments) == 0
    space_output = capsys.readouterr().out
    space_project = analytics_space_root / "analytics-project"
    space_bindings = analytics_space_root / "analytics-bindings.json"
    export_line = "export LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH=" + shlex.quote(str(space_project))
    assert export_line in space_output
    assert shlex.split(export_line[len("export ") :]) == [
        f"LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH={space_project}"
    ]
    assert (
        "export LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS=" + shlex.quote(str(space_bindings))
        in space_output
    )
    assert f'LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH="{space_project}"' in space_output
    assert f'LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS="{space_bindings}"' in space_output

    # A target containing a double quote and a backslash produces escaped
    # EnvironmentFile lines that systemd's documented rule parses back exactly.
    analytics_escaped_root = tmp_path / 'workspace"new\\root'
    escaped_arguments = [
        "restore",
        "--backup-root",
        str(analytics_backup),
        "--target-root",
        str(analytics_escaped_root),
    ]
    assert operations_main(escaped_arguments) == 0
    escaped_output = capsys.readouterr().out
    escaped_project = analytics_escaped_root / "analytics-project"
    escaped_bindings = analytics_escaped_root / "analytics-bindings.json"

    def systemd_escape(value) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def systemd_parse(line: str) -> str:
        inner = line.split("=", 1)[1]
        assert inner[0] == '"' and inner[-1] == '"'
        return re.sub(r'\\(["\\])', r"\1", inner[1:-1])

    project_line = f'LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH="{systemd_escape(escaped_project)}"'
    assert project_line in escaped_output
    assert systemd_parse(project_line) == str(escaped_project)
    bindings_line = (
        f'LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS="{systemd_escape(escaped_bindings)}"'
    )
    assert bindings_line in escaped_output
    assert systemd_parse(bindings_line) == str(escaped_bindings)


def test_integrated_restore_preserves_shared_repo_and_resumes_after_admission(
    tmp_path: Path, monkeypatch
) -> None:
    """AC15: one shared authoring/analytics repository restores ONCE and
    resumes only after fresh native admission.

    The knowledge authoring working tree and the Ariadne analytics project
    are the SAME physical Git working tree (spec0035 §2), so backup/restore
    must materialize one repository with both worktree roles relinked, and
    dependent writes/queries must refuse with actionable prerequisites until
    the owner reconfirms setup AND a fresh reviewed contribution is admitted
    on the restored destination. Reading old pages — or the strict SDK
    verifying the old root that is deliberately still present on this host —
    never substitutes for that admission (spec0035 §5 recovery; hand oracle:
    orders rows 10 + 20 = 30, see c5/c5-report.md).
    """
    fixtures = _analytics_fixtures
    project, api, started, _revision = fixtures._native_baseline(tmp_path / "baseline")
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    native_review = api.review_proposal(started["proposal"])
    destination = tmp_path / "published"
    private = tmp_path / "private"
    registry = private / "registry"
    artifacts = private / "artifacts"
    registry.mkdir(parents=True)
    artifacts.mkdir()
    profile = private / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": fixtures.NAMESPACE,
                "source_registry": str(registry),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(artifacts)},
            }
        ),
        encoding="utf-8",
    )
    fixtures._retain_model(profile)
    overall = admission.overall_review(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        destination=destination,
        expected_current="none",
        private_profile=profile,
        scope=("internal",),
    )
    admission.admit_revision(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        confirmed_by="human:synthetic-baseline-owner",
        overall_preview=overall,
        confirmed_overall_digest=overall["digest"],
        private_profile=profile,
    )

    baseline_authoring = project / "knowledge"
    bindings = tmp_path / "analytics-bindings.json"
    bindings.write_text(
        json.dumps(
            {
                "orders_sqlite": [
                    {"name": "orders_sqlite", "type": "sqlite", "path": "data/orders.sqlite"}
                ]
            }
        ),
        encoding="utf-8",
    )
    fixtures._sqlite(
        project / "data" / "orders.sqlite", [(1, 10, "completed"), (2, 20, "completed")]
    )
    config = WorkspaceConfig(
        workspace_id="workspace-c5-restore",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=native_review["revision"],
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=baseline_authoring,
        private_profile_path=profile,
        private_root=tmp_path / "operations",
        namespace=fixtures.NAMESPACE,
        analytics_project_id="retail",
        analytics_project_path=project,
        analytics_source_bindings_path=bindings,
    )
    contributor = Actor(tenant_id="local", object_id="contributor")
    reviewer = Actor(tenant_id="local", object_id="reviewer")
    owner = Actor(tenant_id="local", object_id="owner")
    state = WorkspaceState(config.state_path)
    for actor in (contributor, reviewer, owner):
        state.create_local_user(actor.object_id)
        state.grant(config.workspace_id, actor)
    state.grant(config.workspace_id, contributor, "contribute")
    state.grant(config.workspace_id, reviewer, "review")
    state.grant(config.workspace_id, owner, "setup")
    state.record_setup(
        config.workspace_id,
        owner,
        "c5-baseline-setup",
        kind="existing",
        target=baseline_authoring,
        namespace=fixtures.NAMESPACE,
        base_revision=native_review["revision"],
        attachment_digest=current_attachment_digest(
            target=baseline_authoring, profile_path=profile
        ),
    )
    state.save_browser_session("c5-restore-session", {"member": "reviewer"}, expires_at=2**31)
    intake = IntakeService(state, config.operational_root)
    analytics = AnalyticsService(config, state, intake)
    review = ReviewService(
        state,
        workspace_id=config.workspace_id,
        authoring_path=baseline_authoring,
        profile_path=profile,
        private_root=config.operational_root,
        destination=destination,
        analytics=analytics,
    )

    # An ordinary pending knowledge contribution BEFORE the backup: this
    # public flow registers the AUTHORING task-worktree role
    # (private/worktrees/<task>) in the shared repository.
    knowledge_service = ContributionService(
        state,
        intake,
        workspace_id=config.workspace_id,
        external_url=config.external_url,
        authoring_path=baseline_authoring,
        profile_path=profile,
        destination=destination,
        analytics_enabled=True,
    )
    policy_bytes = b"# Cancelled Orders\n\nOnly completed orders enter EUR revenue.\n"
    guide_bytes = b"# Restore Runbook original\n\nRestart the worker safely.\n"
    guide_upload = intake.save(
        config.workspace_id,
        contributor,
        "restore-runbook-source",
        "restore-runbook.md",
        "c5-guide-pre",
        guide_bytes,
    )
    guide = knowledge_service.prepare(
        contributor,
        retry_key="c5-guide-pre",
        sources=[{"upload_id": guide_upload["upload_id"], "intent": "new"}],
        pages=[
            {
                "filename": "restore-runbook.md",
                "markdown": _review._attributed_page(
                    "Restore Runbook", ["restore-runbook-source"]
                ).replace(
                    # the shared-root baseline control file configures
                    # 'policies'/'metrics' categories only
                    "category: procedures",
                    "category: policies",
                ),
            }
        ],
    )
    guide_task_id = guide["task_id"]

    # A pending analytics contribution prepared BEFORE the backup registers
    # the analytics proposal-worktree role and leaves an outstanding review
    # action that must die.
    prepared = analytics.prepare_data_source(
        contributor,
        retry_key="c5-orders-pre",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["What is completed revenue in EUR?"],
    )
    source_task = prepared["task_id"]
    assert prepared["status"] == "pending_source_approval"
    approval_stage = review.get(reviewer, source_task)
    review.decide(reviewer, source_task, approval_stage.action_digest, "approve")
    grant_stage = review.get(reviewer, source_task)
    granted = review.decide(reviewer, source_task, grant_stage.action_digest, "approve")
    assert granted["status"] == "data_granted"
    analytics.profile_data_source(contributor, source_task)
    uploaded = intake.save(
        config.workspace_id,
        contributor,
        "human-cancellation-rule",
        "cancelled-orders.md",
        "c5-policy-pre",
        policy_bytes,
    )
    _record, snapshot = admission.resolve_admission(project)
    model = (snapshot / "semantic_layer/models/retail_sales.yml").read_text(encoding="utf-8")
    changed_model = model.replace("orders.main.orders", "orders_sqlite.main.entries").replace(
        "SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)",
        fixtures.FILTER_EXPRESSION,
    )
    pending = analytics.prepare_contribution(
        contributor,
        retry_key="c5-resume-pre",
        source_task_id=source_task,
        sources=[{"upload_id": uploaded["upload_id"], "intent": "new"}],
        pages=[
            {
                "filename": "cancelled-orders.md",
                "markdown": fixtures.WORKSPACE_POLICY.replace(
                    "Cancelled orders are excluded.", fixtures.POLICY_ADDITION
                ),
            }
        ],
        core_edits=[{"kind": "model", "name": "retail_sales", "content": changed_model}],
    )
    contribution_task = pending["task_id"]
    review.get(reviewer, contribution_task)
    outstanding_guide = review.get(reviewer, guide_task_id).action_digest

    # Immutability captures: exact receipt/admission/approval state before
    # the backup travels.
    baseline_revision = native_review["revision"]
    baseline_receipt = (
        destination / PRIVATE_OPERATIONS_DIR / "receipts" / f"{baseline_revision}.json"
    ).read_bytes()
    baseline_record = admission.load_current(project)
    assert baseline_record is not None
    baseline_resolved, baseline_digest = authoring_sources.candidate_sources(
        project, started["candidate_revision"]
    )
    baseline_approval = authoring_sources.approval_state(
        project, baseline_resolved, baseline_digest
    )
    assert baseline_approval.get("approved") is True
    baseline_head = _git(project, "rev-parse", "HEAD")

    backup_root = quiesced_backup(config, tmp_path / "workspace-backup")
    manifest = json.loads((backup_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["shared_analytics_root"] is True

    second_root = tmp_path / "restored-data-root"
    restored = restore(backup_root, second_root, replace(config, published_version=None))
    assert restored.authoring_path is not None
    # The analytics project must resolve INTO the single restored repository
    # — never into a second materialized copy that advances independently.
    assert restored.analytics_project_path == second_root / "authoring-repo"
    assert (second_root / "analytics-project").exists() is False
    assert restored.authoring_path == second_root / "authoring-repo" / "knowledge"
    assert restored.authoring_path is not None
    restored_authoring = restored.authoring_path
    assert restored.private_profile_path is not None
    restored_profile = restored.private_profile_path
    assert _git(second_root / "authoring-repo", "rev-parse", "HEAD") == baseline_head
    registered = sorted(
        entry
        for entry in (second_root / "authoring-repo" / ".git" / "worktrees").iterdir()
        if entry.is_dir()
    )
    assert registered
    relinked_private = 0
    relinked_analytics = 0
    for entry in registered:
        gitdir = Path((entry / "gitdir").read_text(encoding="utf-8").strip())
        assert gitdir.exists(), f"registration {entry.name} lost its worktree"
        if gitdir.parent.parent == second_root / "private" / "worktrees":
            relinked_private += 1
        elif gitdir.parent.parent == (second_root / "authoring-repo" / ".ariadne" / "worktrees"):
            relinked_analytics += 1
    assert relinked_private >= 1  # authoring task-worktree role preserved
    assert relinked_analytics >= 1  # analytics proposal-worktree role preserved

    # the pending request's draft is retired by the restore; a new one can open
    assert draft.status(second_root / "authoring-repo") is None
    restored_draft = AuthoringProject(second_root / "authoring-repo").start_proposal()
    assert restored_draft["proposal"]
    draft.discard(
        second_root / "authoring-repo",
        draft.active_expected(
            second_root / "authoring-repo",
            restored_draft["proposal"],
            restored_draft["candidate_revision"],
        ),
    )

    restored_state = WorkspaceState(restored.state_path)
    assert restored_state.load_browser_session("c5-restore-session") is None
    restored_intake = IntakeService(restored_state, restored.operational_root)
    restored_analytics = AnalyticsService(restored, restored_state, restored_intake)
    restored_review = ReviewService(
        restored_state,
        workspace_id=restored.workspace_id,
        authoring_path=restored_authoring,
        profile_path=restored_profile,
        private_root=restored.operational_root,
        destination=restored.published_path,
        analytics=restored_analytics,
    )

    # Boundary sentinel over the REAL execution builder: every pre-admission
    # query leg must refuse before any source is opened.
    opened: list[list] = []
    real_builder = execution.build_connection

    def spy(registry_, **kwargs):
        opened.append([source.path for source in registry_.sources])
        return real_builder(registry_, **kwargs)

    monkeypatch.setattr(execution, "build_connection", spy)
    monkeypatch.setattr(native_sources, "build_connection", spy)

    # Before the owner reconfirms the restored target, dependent writes and
    # queries refuse with actionable prerequisites — before any SQL.
    with pytest.raises(ReviewError, match="owner setup"):
        restored_review.get(reviewer, guide_task_id)
    with pytest.raises(AnalyticsError, match="need owner setup"):
        restored_analytics.prepare_contribution(
            contributor,
            retry_key="c5-resume-blocked",
            source_task_id=source_task,
            sources=[{"upload_id": uploaded["upload_id"], "intent": "new"}],
            pages=[],
            core_edits=[],
        )
    with pytest.raises(AnalyticsError, match="need owner setup"):
        restored_analytics.query_data(
            contributor, "retail", source_task, "get_metric", {"name": "revenue"}
        )
    assert opened == []

    # After owner reconfirmation but BEFORE a fresh admission, the old
    # association must STILL refuse — even though the original root is still
    # present on this host and the strict SDK would verify it there.
    restored_state.record_setup(
        restored.workspace_id,
        owner,
        "c5-restored-attach",
        kind="existing",
        target=restored_authoring,
        namespace=fixtures.NAMESPACE,
        base_revision=baseline_head,
        attachment_digest=current_attachment_digest(
            target=restored_authoring, profile_path=restored_profile
        ),
    )
    with pytest.raises(AnalyticsError, match="fresh reviewed contribution"):
        restored_analytics.query_data(
            contributor, "retail", source_task, "get_metric", {"name": "revenue"}
        )
    assert opened == []

    # Source identity is revalidated against the restored repo — bytes are
    # content-identical, but the resolved identity embeds the restored
    # absolute paths, so the revalidation honestly reports the old approval
    # ABSENT: no silent reuse. The resumed contribution below therefore
    # obtains a REAL native Source Approval on the restored root through the
    # existing review surface before any dependent write or query resumes.
    restored_resolved, restored_digest = authoring_sources.candidate_sources(
        restored_analytics.project, started["candidate_revision"]
    )
    restored_approval = authoring_sources.approval_state(
        restored_analytics.project, restored_resolved, restored_digest
    )
    assert restored_approval.get("approved") is False
    assert restored_approval.get("state") == "absent"

    # The pre-restore ANALYTICS contribution proposal belongs to the
    # ORIGINAL project root: ariadne's project-identity guard refuses to
    # resume it on the restored repository — old pre-restore work must be
    # redone as a fresh reviewed contribution, never silently continued.
    with pytest.raises(ValueError, match="no proposal"):
        restored_review.get(reviewer, contribution_task)

    # The pending knowledge contribution resolves through the RELINKED
    # authoring worktree, and its pre-restore review action can never
    # activate: restored action rows are gone, so the outstanding digest
    # refuses while the recomputed context carries a fresh digest.
    replay = restored_review.get(reviewer, guide_task_id)
    assert replay.action_digest != outstanding_guide
    with pytest.raises(ReviewError):
        restored_review.decide(reviewer, guide_task_id, outstanding_guide, "approve")

    # While the original publication is still available, the imported
    # historical admission fully validates; its persisted bytes are then
    # compared unchanged after the whole resume (F2: the unavailable old
    # publication must never alter historical admission artifacts).
    admission.validate_admission_record(restored_analytics.project, baseline_record)
    historical_snapshot = restored_analytics.project / baseline_record["snapshot"]
    historical_before = _tree_digest(historical_snapshot)

    # The ORIGINAL published tree goes away entirely (actual rename in the
    # temp fixture — no mock): readiness decisions and the whole fresh
    # resume below must never depend on the old publication being online.
    destination.rename(tmp_path / "published-taken-away")
    assert not destination.exists()
    with pytest.raises(AnalyticsError, match="fresh reviewed contribution"):
        restored_analytics.query_data(
            contributor, "retail", source_task, "get_metric", {"name": "revenue"}
        )
    assert opened == []

    # Resume: a genuinely new source gets REAL native Source Approval and a
    # fresh data grant through the existing review surface.
    prepared2 = restored_analytics.prepare_data_source(
        contributor,
        retry_key="c5-orders-post",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["What is completed revenue in EUR?"],
    )
    task2 = prepared2["task_id"]
    assert prepared2["status"] == "pending_source_approval"
    approval2 = restored_review.get(reviewer, task2)
    restored_review.decide(reviewer, task2, approval2.action_digest, "approve")
    grant2 = restored_review.get(reviewer, task2)
    decided2 = restored_review.decide(reviewer, task2, grant2.action_digest, "approve")
    assert decided2["status"] == "data_granted"
    restored_analytics.profile_data_source(contributor, task2)
    uploaded2 = restored_intake.save(
        restored.workspace_id,
        contributor,
        "human-cancellation-rule",
        "cancelled-orders.md",
        "c5-policy-post",
        policy_bytes,
    )
    restored_current = admission.load_current(restored_analytics.project)
    assert restored_current is not None
    snapshot2 = restored_analytics.project / restored_current["snapshot"]
    model2 = (snapshot2 / "semantic_layer/models/retail_sales.yml").read_text(encoding="utf-8")
    changed2 = model2.replace("orders.main.orders", "orders_sqlite.main.entries").replace(
        "SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)",
        fixtures.FILTER_EXPRESSION,
    )
    candidate2 = restored_analytics.prepare_contribution(
        contributor,
        retry_key="c5-resume-post",
        source_task_id=task2,
        sources=[{"upload_id": uploaded2["upload_id"], "intent": "new"}],
        pages=[
            {
                "filename": "cancelled-orders.md",
                "markdown": fixtures.WORKSPACE_POLICY.replace(
                    "Cancelled orders are excluded.", fixtures.POLICY_ADDITION
                ),
            }
        ],
        core_edits=[{"kind": "model", "name": "retail_sales", "content": changed2}],
    )
    submission = restored_review.get(reviewer, candidate2["task_id"])
    submitted = restored_review.decide(
        reviewer, candidate2["task_id"], submission.action_digest, "approve"
    )
    assert submitted["status"] == "pending_publication"
    assert submitted["validation"]["ok"] is True
    publication_context = restored_review.get(reviewer, candidate2["task_id"])
    published = restored_review.decide(
        reviewer, candidate2["task_id"], publication_context.action_digest, "approve"
    )
    assert published["status"] == "published"
    assert published["publication_outcome"] == "activated"

    # The resumed query uses the EXACT new knowledge/analytics association:
    # hand oracle 10 + 20 = 30 (c5/c5-report.md), pinned to the new record.
    result = restored_analytics.query_data(
        contributor, "retail", task2, "get_metric", {"name": "revenue"}
    )
    assert result["rows"] == [{"revenue": 30.0}]
    assert result["pinned"]["commit"] == published["native_candidate"]
    assert result["context"]["bound_release"] == published["bound_release"]
    new_record, _snapshot3 = admission.resolve_admission(restored_analytics.project)
    assert new_record["commit"] == published["native_candidate"]
    assert (
        Path(new_record["bound_release"]["destination"]).resolve()
        == restored.published_path.resolve()
    )
    assert (
        PublishedFilesystemLocation(restored.published_path).read_pointer()
        == (published["native_candidate"])
    )

    # Historical admissions and receipts are untouched by the new publication.
    assert (
        restored.published_path / PRIVATE_OPERATIONS_DIR / "receipts" / f"{baseline_revision}.json"
    ).read_bytes() == baseline_receipt
    assert _tree_digest(historical_snapshot) == historical_before

    # F2-R1: the persistent restore marker does NOT swallow corruption of the
    # CURRENT publication. The restored workspace is now readmitted to THIS
    # destination, so the exact same canonical size/digest mismatch predicate
    # as the ordinary corruption test must still propagate the real SDK
    # failure — recovery selection is only for an imported LOCAL destination
    # DIFFERENT from this restored destination (the offline ORIGINAL case).
    current_pointer = PublishedFilesystemLocation(restored.published_path).read_pointer()
    assert current_pointer is not None
    assert current_pointer == published["native_candidate"]
    current_manifest = json.loads(
        (restored.published_path / VERSIONS_DIR_NAME / current_pointer / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    current_target = next(
        entry for entry in current_manifest["files"] if entry["path"].endswith(".md")
    )
    current_canonical = (
        restored.published_path / VERSIONS_DIR_NAME / current_pointer / current_target["path"]
    )
    with current_canonical.open("ab") as handle:
        handle.write(b" corruption")
    with pytest.raises(SnapshotUnavailableError, match="could not be resolved and verified"):
        restored_analytics.prepare_data_source(
            contributor,
            retry_key="c5-orders-post-corrupt",
            project="retail",
            source="orders_sqlite",
            table="entries",
            business_questions=["What is completed revenue in EUR?"],
        )


def test_native_admitted_query_does_not_require_authoring_attachment(
    tmp_path: Path, monkeypatch
) -> None:
    """F1: an ordinary native admitted workspace queries WITHOUT any W
    authoring-setup attachment.

    The public query contract is: existing native admission + exact native
    Source Approval + the caller's data grant (A docs how-to-shared-workspace-data
    §5; W public query tool). No owner ever confirmed a W authoring setup in
    this workspace, and no restore happened — so no restoration-specific
    readiness requirement may leak into the query (spec0035 §5 recovery is
    restoration-scoped; AC15 governs only restored roots).
    Hand oracle: baseline orders rows 100 + 50 completed (25 cancelled
    excluded by the metric expression) = 150.
    """
    fixtures = _analytics_fixtures
    project, api, started, _revision = fixtures._native_baseline(tmp_path / "baseline")
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    native_review = api.review_proposal(started["proposal"])
    destination = tmp_path / "published"
    private = tmp_path / "private"
    (private / "registry").mkdir(parents=True)
    (private / "artifacts").mkdir()
    profile = private / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": fixtures.NAMESPACE,
                "source_registry": str(private / "registry"),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(private / "artifacts")},
            }
        ),
        encoding="utf-8",
    )
    fixtures._retain_model(profile)
    overall = admission.overall_review(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        destination=destination,
        expected_current="none",
        private_profile=profile,
        scope=("internal",),
    )
    admission.admit_revision(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        confirmed_by="human:synthetic-baseline-owner",
        overall_preview=overall,
        confirmed_overall_digest=overall["digest"],
        private_profile=profile,
    )
    bindings = tmp_path / "analytics-bindings.json"
    bindings.write_text(
        json.dumps(
            {"orders": [{"name": "orders", "type": "sqlite", "path": "data/baseline.sqlite"}]}
        ),
        encoding="utf-8",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-native-query",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=native_review["revision"],
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=project / "knowledge",
        private_profile_path=profile,
        private_root=tmp_path / "operations",
        namespace=fixtures.NAMESPACE,
        analytics_project_id="retail",
        analytics_project_path=project,
        analytics_source_bindings_path=bindings,
    )
    contributor = Actor(tenant_id="local", object_id="contributor")
    reviewer = Actor(tenant_id="local", object_id="reviewer")
    state = WorkspaceState(config.state_path)
    for actor in (contributor, reviewer):
        state.create_local_user(actor.object_id)
        state.grant(config.workspace_id, actor)
    state.grant(config.workspace_id, contributor, "contribute")
    state.grant(config.workspace_id, reviewer, "review")
    # Deliberately NO state.record_setup: the workspace has never confirmed a
    # W authoring attachment (the F1 subject).
    intake = IntakeService(state, config.operational_root)
    analytics = AnalyticsService(config, state, intake)
    review = ReviewService(
        state,
        workspace_id=config.workspace_id,
        authoring_path=project / "knowledge",
        profile_path=profile,
        private_root=config.operational_root,
        destination=destination,
        analytics=analytics,
    )
    prepared = analytics.prepare_data_source(
        contributor,
        retry_key="f1-orders",
        project="retail",
        source="orders",
        table="orders",
        business_questions=["What is completed revenue in EUR?"],
    )
    task = prepared["task_id"]
    # The baseline fixture already holds the EXACT native Source Approval for
    # the admitted declaration, so preparation goes straight to the caller's
    # data grant (existing reuse contract) — no second source approval.
    assert prepared["status"] == "pending_data_grant"
    grant_stage = review.get(reviewer, task)
    granted = review.decide(reviewer, task, grant_stage.action_digest, "approve")
    assert granted["status"] == "data_granted"

    opened: list[list] = []
    real_builder = execution.build_connection

    def spy(registry_, **kwargs):
        opened.append([source.path for source in registry_.sources])
        return real_builder(registry_, **kwargs)

    monkeypatch.setattr(execution, "build_connection", spy)
    monkeypatch.setattr(native_sources, "build_connection", spy)

    result = analytics.query_data(contributor, "retail", task, "get_metric", {"name": "revenue"})
    assert result["rows"] == [{"revenue": 150.0}]  # 100 + 50 completed; cancelled excluded
    assert result["pinned"]["commit"] == native_review["revision"]
    assert len(opened) == 1  # exactly the sanctioned source resolution


def test_native_source_preparation_preserves_publication_corruption(
    tmp_path: Path, monkeypatch
) -> None:
    """F2-R1: corrupt published canonical bytes stay a hard failure.

    A real natively admitted, never-restored workspace with the exact native
    Source Approval prepares normally (control leg). After ONE canonical file
    in the published version is actually corrupted against its manifest
    (size and digest mismatch), the public prepare_data_source must PROPAGATE
    the real SDK SnapshotUnavailableError from the written integrity contract
    (PublishedFilesystemLocation.materialize verifies size and sha-256 per
    manifest entry) — never swallow it into the fresh-authoring path or
    return pending_source_approval. SnapshotUnavailableError is not an
    availability-only discriminator: ariadne_context wraps location.resolve
    corruption there, so only the offline ORIGINAL-publication recovery case
    may select fresh authoring (spec0035 §5 recovery boundary).
    """
    fixtures = _analytics_fixtures
    project, api, started, _revision = fixtures._native_baseline(tmp_path / "baseline")
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    native_review = api.review_proposal(started["proposal"])
    destination = tmp_path / "published"
    private = tmp_path / "private"
    (private / "registry").mkdir(parents=True)
    (private / "artifacts").mkdir()
    profile = private / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": fixtures.NAMESPACE,
                "source_registry": str(private / "registry"),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(private / "artifacts")},
            }
        ),
        encoding="utf-8",
    )
    fixtures._retain_model(profile)
    overall = admission.overall_review(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        destination=destination,
        expected_current="none",
        private_profile=profile,
        scope=("internal",),
    )
    admission.admit_revision(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        confirmed_by="human:synthetic-baseline-owner",
        overall_preview=overall,
        confirmed_overall_digest=overall["digest"],
        private_profile=profile,
    )
    bindings = tmp_path / "analytics-bindings.json"
    bindings.write_text(
        json.dumps(
            {"orders": [{"name": "orders", "type": "sqlite", "path": "data/baseline.sqlite"}]}
        ),
        encoding="utf-8",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-native-corruption",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=native_review["revision"],
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=project / "knowledge",
        private_profile_path=profile,
        private_root=tmp_path / "operations",
        namespace=fixtures.NAMESPACE,
        analytics_project_id="retail",
        analytics_project_path=project,
        analytics_source_bindings_path=bindings,
    )
    contributor = Actor(tenant_id="local", object_id="contributor")
    state = WorkspaceState(config.state_path)
    state.create_local_user(contributor.object_id)
    state.grant(config.workspace_id, contributor)
    state.grant(config.workspace_id, contributor, "contribute")
    intake = IntakeService(state, config.operational_root)
    analytics = AnalyticsService(config, state, intake)

    # Valid control first: preparation against the intact admission reuses
    # the existing native declaration (exact native Source Approval is in
    # the baseline fixture) and reaches the caller's data grant.
    prepared = analytics.prepare_data_source(
        contributor,
        retry_key="f2r1-orders-control",
        project="retail",
        source="orders",
        table="orders",
        business_questions=["What is completed revenue in EUR?"],
    )
    assert prepared["status"] == "pending_data_grant"

    # Corrupt ONE actual published canonical file (append bytes): the real
    # SDK size/digest verification failure becomes SnapshotUnavailableError.
    pointer = PublishedFilesystemLocation(destination).read_pointer()
    assert pointer is not None
    assert pointer == native_review["revision"]
    manifest = json.loads(
        (destination / VERSIONS_DIR_NAME / pointer / "manifest.json").read_text(encoding="utf-8")
    )
    target = next(entry for entry in manifest["files"] if entry["path"].endswith(".md"))
    canonical = destination / VERSIONS_DIR_NAME / pointer / target["path"]
    with canonical.open("ab") as handle:
        handle.write(b" corruption")

    # The integrity refusal must propagate: preparation must NOT convert the
    # corrupt publication into a fresh successful pending_source_approval
    # workflow (F2-R1 defect), and the operation must not report reuse.
    with pytest.raises(SnapshotUnavailableError, match="could not be resolved and verified"):
        analytics.prepare_data_source(
            contributor,
            retry_key="f2r1-orders-corrupt",
            project="retail",
            source="orders",
            table="orders",
            business_questions=["What is completed revenue in EUR?"],
        )
