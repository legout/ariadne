from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

import pytest
from lumio_wiki.artifact_store import ArtifactStoreError, LocalDirectoryArtifactStore
from lumio_wiki.authoring_journey import (
    AuthoringJourneyError,
    CandidateRequest,
    CandidateSourceRecord,
    ingest_candidate,
)
from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.knowledge_base import (
    document_first_control_file,
    load_control_file,
    seeded_control_file,
    write_control_file,
)
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
from lumio_workspace import contributions as contribution_module
from lumio_workspace.__main__ import main
from lumio_workspace.setup import SetupError, preview_setup
from starlette.testclient import TestClient

NAMESPACE = "urn:uuid:6c6e21ec-98a4-4c0b-9153-c2eb5d3c2210"
SENTINEL = "The published sentinel must remain exactly unchanged."
ORIGINAL = b"# Restart worker\r\n\r\nStop the old worker.\r\nThen start it."
EXPECTED_SHA256 = hashlib.sha256(ORIGINAL).hexdigest()
EDITED = ORIGINAL + b"\r\nVerify the worker is ready."
EDITED_SHA256 = hashlib.sha256(EDITED).hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _published_sentinel(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "published-repo"
    kb = repo / "kb"
    kb.mkdir(parents=True)
    (kb / "runbook.md").write_text(
        "---\n"
        'title: "Published Runbook"\n'
        'tags:\n  - "operations"\n'
        'summary: "Already admitted synthetic page."\n'
        'lifecycle: "approved"\n'
        'visibility: "internal"\n'
        'sources:\n  - id: "published-source"\n    title: "Synthetic fixture"\n'
        "---\n\n"
        f"{SENTINEL}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "add", "kb")
    _git(repo, "commit", "-qm", "synthetic published input")
    revision = _git(repo, "rev-parse", "HEAD")
    destination = tmp_path / "published"
    review = preview_publication(kb, revision, destination, "none")
    assert review.blocking_diagnostics == []
    receipt = publish_revision(kb, revision, destination, "none", review.review_digest)
    assert receipt.activated is True
    return destination, revision


def _page(source_id: str, *, edited: bool = False, title: str = "Restart Worker") -> str:
    entity = title.lower().replace(" ", "-")
    final_line = "Verify the worker is ready." if edited else "Then start it."
    return (
        "---\n"
        f'id: "entity:{entity}-runbook"\n'
        f'title: "{title}"\n'
        'entity_types: ["knowledge-artifact"]\n'
        "category: procedures\n"
        'type: "runbook"\n'
        'durability_rationale: "The source runbook permanently supports this procedure."\n'
        'tags: ["operations"]\n'
        'summary: "Restart the worker safely."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        '    title: "Restart worker runbook"\n'
        "claims: []\n"
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "Stop the old worker.\n\n"
        f"{final_line}\n"
    )


def _call_tool(client: TestClient, token: str, name: str, arguments: dict, request_id: int):
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def _upload(
    client: TestClient,
    token: str,
    raw: bytes,
    *,
    source_id: str = "runbook-source",
    filename: str = "runbook.md",
    retry_key: str,
):
    return client.post(
        "/uploads",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "X-Lumio-Source-ID": source_id,
            "X-Lumio-Filename": filename,
            "X-Lumio-Retry-Key": retry_key,
        },
        content=raw,
    )


def _login(client: TestClient, token: str) -> None:
    response = client.post(
        "/auth/login",
        headers={"Origin": "https://workspace.test"},
        data={"token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _digest(html: str) -> str:
    match = re.search(r'name="digest" value="([0-9a-f]{64})"', html)
    assert match is not None
    return match.group(1)


def _prepare(
    client: TestClient,
    token: str,
    *,
    retry_key: str,
    upload_id: str,
    intent: str,
    base: str | None = None,
    continuation_task_id: str | None = None,
    source_id: str = "runbook-source",
    edited: bool = False,
    request_id: int,
):
    arguments = {
        "retry_key": retry_key,
        "sources": [{"upload_id": upload_id, "intent": intent}],
        "pages": [
            {
                "filename": "restart-worker.md",
                "markdown": _page(source_id, edited=edited),
            }
        ],
    }
    if base is not None:
        arguments["base_revision"] = base
    if continuation_task_id is not None:
        arguments["continuation_task_id"] = continuation_task_id
    return _call_tool(
        client,
        token,
        "prepare_contribution",
        arguments,
        request_id,
    )


@dataclass
class WorkspaceFixture:
    config: WorkspaceConfig
    state: WorkspaceState
    owner: Actor
    contributor: Actor
    owner_api: str
    owner_browser: str
    contributor_api: str
    contributor_browser: str
    registry_path: Path
    artifact_path: Path
    published_revision: str


def _workspace_fixture(tmp_path: Path, monkeypatch) -> WorkspaceFixture:
    monkeypatch.setenv("LUMIO_WORKSPACE_ID", "workspace-fixture")
    monkeypatch.setenv("LUMIO_WORKSPACE_STATE_PATH", str(tmp_path / "state.sqlite3"))
    published_path, published_revision = _published_sentinel(tmp_path)
    authoring_repo = tmp_path / "authoring-repo"
    authoring_kb = authoring_repo / "kb"
    authoring_repo.mkdir()
    _git(authoring_repo, "init", "-q")
    _git(authoring_repo, "config", "user.name", "Fixture")
    _git(authoring_repo, "config", "user.email", "fixture@example.invalid")
    private = tmp_path / "profile-private"
    private.mkdir()
    profile_path = private / "profile.json"
    registry_path = private / "registry"
    artifact_path = private / "artifacts"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(registry_path),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(artifact_path)},
            }
        ),
        encoding="utf-8",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=published_path,
        published_version=published_revision,
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=authoring_kb,
        private_profile_path=profile_path,
        private_root=tmp_path / "operations",
        namespace=NAMESPACE,
    )
    state = WorkspaceState(config.state_path)
    expires = int(time.time()) + 3600
    for user in ("owner", "contributor"):
        state.create_local_user(user)
    owner = Actor(tenant_id="local", object_id="owner")
    contributor = Actor(tenant_id="local", object_id="contributor")
    assert main(["local-membership", "grant", "--user-id", "owner", "--capability", "setup"]) == 0
    assert main(["local-membership", "grant", "--user-id", "contributor"]) == 0
    assert (
        main(
            ["local-membership", "grant", "--user-id", "contributor", "--capability", "contribute"]
        )
        == 0
    )
    _, owner_api = state.issue_local_credential("owner", "api", expires_at=expires)
    _, owner_browser = state.issue_local_credential("owner", "browser", expires_at=expires)
    _, contributor_api = state.issue_local_credential("contributor", "api", expires_at=expires)
    _, contributor_browser = state.issue_local_credential(
        "contributor", "browser", expires_at=expires
    )
    return WorkspaceFixture(
        config,
        state,
        owner,
        contributor,
        owner_api,
        owner_browser,
        contributor_api,
        contributor_browser,
        registry_path,
        artifact_path,
        published_revision,
    )


def _owner_setup(client: TestClient, fixture: WorkspaceFixture):
    _login(client, fixture.owner_browser)
    preview = client.get("/setup")
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        "/setup",
        headers={"Origin": "https://workspace.test"},
        data={"digest": _digest(preview.text)},
    )
    assert confirmed.status_code == 200, confirmed.text
    return preview, confirmed


def _adopt_without_setup(fixture: WorkspaceFixture) -> str:
    kb = fixture.config.authoring_path
    assert kb is not None
    kb.mkdir()
    write_control_file(kb, seeded_control_file())
    (kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    repo = kb.parent
    _git(repo, "add", "kb")
    _git(repo, "commit", "-qm", "independently adopted fixture")
    return _git(repo, "rev-parse", "HEAD")


def _snapshot(root: Path) -> dict[str, bytes] | None:
    if not root.exists():
        return None
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_exact_upload_retry_preserves_source_and_pending_visibility(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    config = fixture.config
    state = fixture.state
    owner = fixture.owner
    contributor = fixture.contributor
    owner_api = fixture.owner_api
    owner_browser = fixture.owner_browser
    contributor_api = fixture.contributor_api
    contributor_browser = fixture.contributor_browser
    registry_path = fixture.registry_path
    artifact_path = fixture.artifact_path
    authoring_kb = config.authoring_path
    profile_path = config.private_profile_path
    assert authoring_kb is not None
    assert profile_path is not None
    authoring_repo = authoring_kb.parent
    assert state.capabilities(config.workspace_id, owner) == ("setup",)
    assert state.capabilities(config.workspace_id, contributor) == ("contribute", "read")

    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        assert client.get("/setup", follow_redirects=False).status_code == 303
        _login(client, contributor_browser)
        assert client.get("/setup").status_code == 403
        assert not authoring_kb.exists()

        api_only = TestClient(create_app(config), base_url="https://workspace.test")
        api_only.headers["Authorization"] = f"Bearer {contributor_api}"
        refused = api_only.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": "0" * 64},
        )
        assert refused.status_code == 401
        assert not authoring_kb.exists()

        _login(client, owner_browser)
        preview = client.get("/setup")
        assert preview.status_code == 200, preview.text
        setup_digest = _digest(preview.text)
        assert not authoring_kb.exists()
        assert not (tmp_path / "operations" / "setup").exists()
        stale = client.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": "0" * 64},
        )
        assert stale.status_code == 409
        assert not authoring_kb.exists()
        confirmed = client.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": setup_digest},
        )
        assert confirmed.status_code == 200, confirmed.text
        base_revision = confirmed.json()["base_revision"]
        assert _git(authoring_repo, "rev-parse", "HEAD") == base_revision
        manifest_bytes = (authoring_kb / ".lumio-authoring.yaml").read_bytes()

        adopted_preview = client.get("/setup")
        assert adopted_preview.status_code == 200
        assert "adopted" in adopted_preview.text
        adopted_digest = _digest(adopted_preview.text)
        adopted = client.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": adopted_digest},
        )
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["kind"] == "adopted"
        assert _git(authoring_repo, "rev-parse", "HEAD") == base_revision
        assert (authoring_kb / ".lumio-authoring.yaml").read_bytes() == manifest_bytes

        published = _call_tool(
            client,
            contributor_api,
            "read_knowledge",
            {"title": "Published Runbook"},
            1,
        )
        assert published.status_code == 200
        assert published.json()["result"]["structuredContent"]["markdown"].strip() == SENTINEL
        owner_upload = _upload(client, owner_api, ORIGINAL, retry_key="owner-not-contributor")
        assert owner_upload.status_code == 403
        escape = _upload(
            client,
            contributor_api,
            ORIGINAL,
            filename="../escape.md",
            retry_key="path-escape",
        )
        assert escape.status_code == 400
        assert escape.json()["code"] == "unsafe_path"
        uploaded = _upload(client, contributor_api, ORIGINAL, retry_key="retry-original")
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["sha256"] == EXPECTED_SHA256
        assert uploaded.json()["size"] == len(ORIGINAL)
        upload_id = uploaded.json()["upload_id"]
        retried = _upload(client, contributor_api, ORIGINAL, retry_key="retry-original")
        assert retried.status_code == 200
        assert retried.json()["upload_id"] == upload_id
        assert retried.json()["reused"] is True
        conflict = _upload(client, contributor_api, EDITED, retry_key="retry-original")
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "retry_conflict"

        material = _call_tool(
            client,
            contributor_api,
            "read_source_material",
            {"upload_id": upload_id},
            2,
        )
        assert material.status_code == 200
        normalized = material.json()["result"]["structuredContent"]
        assert normalized["sha256"] == EXPECTED_SHA256
        assert normalized["processor"] == "markdown"
        assert "Stop the old worker." in normalized["text"]

        first = _prepare(
            client,
            contributor_api,
            retry_key="prepare-original",
            base=base_revision,
            upload_id=upload_id,
            intent="new",
            request_id=3,
        )
        assert first.status_code == 200, first.text
        first_result = first.json()["result"]
        assert first_result["isError"] is False, first_result
        first_task = first_result["structuredContent"]
        assert first_task["status"] == "pending_review"
        assert first_task["published"] is False
        assert first_task["conversion"][0]["sha256"] == EXPECTED_SHA256
        first_candidate = first_task["native_candidate"]
        assert first_task["native_review"]
        versions = SourceRegistry(registry_path).get("runbook-source").versions
        assert [version.content_hash for version in versions] == [EXPECTED_SHA256]
        store = LocalDirectoryArtifactStore(artifact_path)
        assert (
            store.get_artifact(source_id="runbook-source", content_hash=EXPECTED_SHA256) == ORIGINAL
        )

        repeated = _prepare(
            client,
            contributor_api,
            retry_key="prepare-original",
            base=base_revision,
            upload_id=upload_id,
            intent="new",
            request_id=4,
        )
        assert repeated.json()["result"]["structuredContent"]["task_id"] == first_task["task_id"]
        assert len(SourceRegistry(registry_path).get("runbook-source").versions) == 1

        edited_upload = _upload(client, contributor_api, EDITED, retry_key="retry-edit")
        assert edited_upload.status_code == 200
        assert edited_upload.json()["sha256"] == EDITED_SHA256
        second = _prepare(
            client,
            contributor_api,
            retry_key="prepare-edit",
            continuation_task_id=first_task["task_id"],
            upload_id=edited_upload.json()["upload_id"],
            intent="update",
            edited=True,
            request_id=5,
        )
        assert second.status_code == 200, second.text
        second_task = second.json()["result"]["structuredContent"]
        assert second_task["status"] == "pending_review"
        assert second_task["native_base"] == first_candidate
        assert second_task["published"] is False
        versions = SourceRegistry(registry_path).get("runbook-source").versions
        assert [version.content_hash for version in versions] == [EXPECTED_SHA256, EDITED_SHA256]
        assert store.get_artifact(source_id="runbook-source", content_hash=EDITED_SHA256) == EDITED
        reader = _call_tool(
            client,
            contributor_api,
            "read_knowledge",
            {"title": "Restart Worker"},
            6,
        )
        assert reader.json()["result"]["structuredContent"] == {"found": False}
        unchanged = _call_tool(
            client,
            contributor_api,
            "read_knowledge",
            {"title": "Published Runbook"},
            7,
        )
        assert unchanged.json()["result"]["structuredContent"]["markdown"].strip() == SENTINEL

    with TestClient(create_app(config), base_url="https://workspace.test") as reconnected:
        task = _call_tool(
            reconnected,
            contributor_api,
            "get_task",
            {"task_id": second_task["task_id"]},
            8,
        )
        assert task.status_code == 200
        resumed = task.json()["result"]["structuredContent"]
        assert resumed["status"] == "pending_review"
        assert resumed["native_candidate"] == second_task["native_candidate"]
        assert resumed["native_review"] == second_task["native_review"]
        assert resumed["published"] is False

    unadopted_repo = tmp_path / "unadopted-repo"
    unadopted_kb = unadopted_repo / "kb"
    unadopted_kb.mkdir(parents=True)
    (unadopted_kb / "existing.md").write_text("# Existing unadopted content\n", encoding="utf-8")
    _git(unadopted_repo, "init", "-q")
    _git(unadopted_repo, "config", "user.name", "Fixture")
    _git(unadopted_repo, "config", "user.email", "fixture@example.invalid")
    _git(unadopted_repo, "add", "kb")
    _git(unadopted_repo, "commit", "-qm", "unadopted")
    unadopted_head = _git(unadopted_repo, "rev-parse", "HEAD")
    existing_bytes = (unadopted_kb / "existing.md").read_bytes()
    with pytest.raises(SetupError) as refusal:
        preview_setup(
            workspace_id=config.workspace_id,
            authoring_path=unadopted_kb,
            profile_path=profile_path,
            private_root=config.operational_root,
            namespace=NAMESPACE,
        )
    assert refusal.value.code == "adoption_required"
    assert _git(unadopted_repo, "rev-parse", "HEAD") == unadopted_head
    assert (unadopted_kb / "existing.md").read_bytes() == existing_bytes
    assert not (unadopted_kb / ".lumio-authoring.yaml").exists()


def test_prepare_requires_current_owner_attachment(tmp_path: Path, monkeypatch) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None
    assert config.private_profile_path is not None
    base = _adopt_without_setup(fixture)

    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        uploaded = _upload(client, fixture.contributor_api, ORIGINAL, retry_key="attach-upload")
        assert uploaded.status_code == 200
        upload_id = uploaded.json()["upload_id"]
        operations = config.operational_root
        before_operations = _snapshot(operations)
        before_private = _snapshot(tmp_path / "profile-private")

        refused = _prepare(
            client,
            fixture.contributor_api,
            retry_key="attach-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=101,
        )
        assert refused.json()["result"]["isError"] is True
        assert _snapshot(operations) == before_operations
        assert _snapshot(tmp_path / "profile-private") == before_private
        assert not fixture.registry_path.exists()
        assert not fixture.artifact_path.exists()
        assert not (operations / "worktrees").exists()
        assert not (operations / "authored").exists()

        _owner_setup(client, fixture)
        approved = _prepare(
            client,
            fixture.contributor_api,
            retry_key="attach-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=102,
        )
        approved_result = approved.json()["result"]
        assert approved_result["isError"] is False, approved_result
        assert approved_result["structuredContent"]["native_base"] == base

        changed_registry = tmp_path / "changed-registry"
        changed_artifacts = tmp_path / "changed-artifacts"
        profile = json.loads(config.private_profile_path.read_text(encoding="utf-8"))
        profile["source_registry"] = str(changed_registry)
        profile["artifact_store"]["root"] = str(changed_artifacts)
        config.private_profile_path.write_text(json.dumps(profile), encoding="utf-8")
        changed_upload = _upload(
            client,
            fixture.contributor_api,
            ORIGINAL,
            source_id="changed-source",
            retry_key="changed-upload",
        )
        assert changed_upload.status_code == 200
        before_changed_operations = _snapshot(operations)
        mismatch = _prepare(
            client,
            fixture.contributor_api,
            retry_key="changed-prepare",
            base=base,
            upload_id=changed_upload.json()["upload_id"],
            intent="new",
            source_id="changed-source",
            request_id=103,
        )
        assert mismatch.json()["result"]["isError"] is True
        assert _snapshot(operations) == before_changed_operations
        assert not changed_registry.exists()
        assert not changed_artifacts.exists()


def test_setup_commit_preserves_unrelated_index_and_rechecks_base(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None
    repo = config.authoring_path.parent
    unrelated = repo / "operator-notes.txt"
    unrelated_bytes = b"Independent staged operator work; never include or reset this.\n"
    unrelated.write_bytes(unrelated_bytes)
    _git(repo, "add", "--", unrelated.name)

    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        preview, confirmed = _owner_setup(client, fixture)
        committed = set(_git(repo, "show", "--pretty=format:", "--name-only", "HEAD").splitlines())
        assert committed == {"kb/lumio.yaml", "kb/.lumio-authoring.yaml"}
        assert unrelated.read_bytes() == unrelated_bytes
        assert _git(repo, "diff", "--cached", "--name-only") == unrelated.name
        assert _git(repo, "show", f":{unrelated.name}") == unrelated_bytes.decode().strip()
        assert "Initialize workspace knowledge base" in preview.text
        assert confirmed.json()["base_revision"] == _git(repo, "rev-parse", "HEAD")

    late = _workspace_fixture(tmp_path / "late", monkeypatch)
    assert late.config.authoring_path is not None
    late_repo = late.config.authoring_path.parent
    with TestClient(create_app(late.config), base_url="https://workspace.test") as client:
        _login(client, late.owner_browser)
        preview = client.get("/setup")
        assert preview.status_code == 200
        digest = _digest(preview.text)
        late_file = late_repo / "late-base.txt"
        late_file.write_bytes(b"Advance the base after the owner preview.\n")
        _git(late_repo, "add", "--", late_file.name)
        _git(late_repo, "commit", "-qm", "late independent base")
        late_head = _git(late_repo, "rev-parse", "HEAD")
        refused = client.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": digest},
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "setup_target_changed"
        assert _git(late_repo, "rev-parse", "HEAD") == late_head
        assert late_file.read_bytes() == b"Advance the base after the owner preview.\n"
        assert not late.config.authoring_path.exists()


def test_concurrent_retry_never_removes_active_native_work(tmp_path: Path, monkeypatch) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None
    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        _owner_setup(client, fixture)
        uploaded = _upload(client, fixture.contributor_api, ORIGINAL, retry_key="race-upload")
        assert uploaded.status_code == 200
        upload_id = uploaded.json()["upload_id"]
    base = _git(config.authoring_path.parent, "rev-parse", "HEAD")

    real_ingest = contribution_module.ingest_candidate
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    calls_lock = threading.Lock()

    def gated_ingest(*args, **kwargs):
        with calls_lock:
            calls.append(1)
            call_number = len(calls)
        if call_number == 1:
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test barrier timed out")
        return real_ingest(*args, **kwargs)

    monkeypatch.setattr(contribution_module, "ingest_candidate", gated_ingest)
    first_responses = []
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as first_client,
        TestClient(create_app(config), base_url="https://workspace.test") as second_client,
    ):

        def call_first() -> None:
            first_responses.append(
                _prepare(
                    first_client,
                    fixture.contributor_api,
                    retry_key="shared-prepare",
                    base=base,
                    upload_id=upload_id,
                    intent="new",
                    request_id=201,
                )
            )

        first_thread = threading.Thread(target=call_first)
        first_thread.start()
        try:
            assert entered.wait(5)
            worktrees = config.operational_root / "worktrees"
            task_paths = list(worktrees.iterdir())
            assert len(task_paths) == 1
            task_path = task_paths[0]
            second = _prepare(
                second_client,
                fixture.contributor_api,
                retry_key="shared-prepare",
                base=base,
                upload_id=upload_id,
                intent="new",
                request_id=202,
            )
        finally:
            release.set()
            first_thread.join(10)

        assert not first_thread.is_alive()
        assert len(first_responses) == 1
        first_result = first_responses[0].json()["result"]
        assert first_result["isError"] is False, first_result
        first_task = first_result["structuredContent"]
        second_result = second.json()["result"]
        assert second_result["isError"] is False, second_result
        second_task = second_result["structuredContent"]
        assert second_task["task_id"] == first_task["task_id"]
        assert second_task["status"] == "pending"
        assert task_path.exists()
        assert len(calls) == 1
        assert _git(task_path / "kb", "rev-parse", "HEAD") == first_task["native_candidate"]
        assert len(SourceRegistry(fixture.registry_path).get("runbook-source").versions) == 1

        replayed = _prepare(
            second_client,
            fixture.contributor_api,
            retry_key="shared-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=203,
        )
        replay = replayed.json()["result"]["structuredContent"]
        assert replay["native_candidate"] == first_task["native_candidate"]
        status = _call_tool(
            second_client,
            fixture.contributor_api,
            "get_task",
            {"task_id": first_task["task_id"]},
            204,
        )
        current = status.json()["result"]["structuredContent"]
        assert current["status"] == "pending_review"
        assert current["native_review"] == first_task["native_review"]


def test_contributor_uses_server_base_and_opaque_continuation(tmp_path: Path, monkeypatch) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None
    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        _owner_setup(client, fixture)
        authoring_head = _git(config.authoring_path.parent, "rev-parse", "HEAD")
        assert authoring_head != fixture.published_revision
        uploaded = _upload(client, fixture.contributor_api, ORIGINAL, retry_key="fresh-upload")
        assert uploaded.status_code == 200
        upload_id = uploaded.json()["upload_id"]

        first = _prepare(
            client,
            fixture.contributor_api,
            retry_key="fresh-prepare",
            upload_id=upload_id,
            intent="new",
            request_id=301,
        )
        first_result = first.json()["result"]
        assert first_result["isError"] is False, first_result
        first_task = first_result["structuredContent"]
        assert first_task["native_base"] == authoring_head

        repeated = _prepare(
            client,
            fixture.contributor_api,
            retry_key="fresh-prepare",
            upload_id=upload_id,
            intent="new",
            request_id=302,
        )
        repeated_task = repeated.json()["result"]["structuredContent"]
        assert repeated_task["native_candidate"] == first_task["native_candidate"]
        assert repeated_task["native_base"] == authoring_head

        edited_upload = _upload(
            client,
            fixture.contributor_api,
            EDITED,
            retry_key="fresh-edit-upload",
        )
        assert edited_upload.status_code == 200
        second = _prepare(
            client,
            fixture.contributor_api,
            retry_key="fresh-edit",
            continuation_task_id=first_task["task_id"],
            upload_id=edited_upload.json()["upload_id"],
            intent="update",
            edited=True,
            request_id=303,
        )
        second_result = second.json()["result"]
        assert second_result["isError"] is False, second_result
        second_task = second_result["structuredContent"]
        assert second_task["native_base"] == first_task["native_candidate"]

        foreign = _prepare(
            client,
            fixture.contributor_api,
            retry_key="foreign-base",
            base=fixture.published_revision,
            upload_id=upload_id,
            intent="new",
            request_id=304,
        )
        assert foreign.json()["result"]["isError"] is True
        published = _call_tool(
            client,
            fixture.contributor_api,
            "read_knowledge",
            {"title": "Published Runbook"},
            305,
        )
        published_page = published.json()["result"]["structuredContent"]
        assert published_page["markdown"].strip() == SENTINEL
        assert published_page["citation"]["published_version"] == fixture.published_revision


def test_interrupted_prepare_recovers_exact_registered_task_ref(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None
    repo = config.authoring_path.parent
    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        _owner_setup(client, fixture)
        uploaded = _upload(
            client, fixture.contributor_api, ORIGINAL, retry_key="interrupted-upload"
        )
        assert uploaded.status_code == 200
        upload_id = uploaded.json()["upload_id"]
    base = _git(repo, "rev-parse", "HEAD")
    manifest_before = (config.authoring_path / ".lumio-authoring.yaml").read_bytes()
    _git(repo, "branch", "operator-keep", base)

    real_ingest = contribution_module.ingest_candidate

    def interrupted_ingest(*args, **kwargs):
        raise RuntimeError("simulated interruption after native worktree creation")

    monkeypatch.setattr(contribution_module, "ingest_candidate", interrupted_ingest)
    with TestClient(create_app(config), base_url="https://workspace.test") as interrupted:
        interrupted_response = _prepare(
            interrupted,
            fixture.contributor_api,
            retry_key="interrupted-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=401,
        )
        assert interrupted_response.json()["result"]["isError"] is True

    task_paths = list((config.operational_root / "worktrees").iterdir())
    assert len(task_paths) == 1
    task_path = task_paths[0]
    task_id = task_path.name
    branch = f"lumio-workspace/{task_id}"
    registered = _git(repo, "worktree", "list", "--porcelain")
    assert f"worktree {task_path}" in registered
    assert _git(repo, "rev-parse", f"refs/heads/{branch}") == base
    monkeypatch.setattr(contribution_module, "ingest_candidate", real_ingest)

    with TestClient(create_app(config), base_url="https://workspace.test") as reconnected:
        pending = _call_tool(
            reconnected,
            fixture.contributor_api,
            "get_task",
            {"task_id": task_id},
            402,
        )
        pending_task = pending.json()["result"]["structuredContent"]
        assert pending_task["status"] == "pending"
        assert pending_task["native_base"] == base

        recovered = _prepare(
            reconnected,
            fixture.contributor_api,
            retry_key="interrupted-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=403,
        )
        recovered_result = recovered.json()["result"]
        assert recovered_result["isError"] is False, recovered_result
        recovered_task = recovered_result["structuredContent"]
        assert recovered_task["task_id"] == task_id
        assert recovered_task["status"] == "pending_review"
        assert recovered_task["native_base"] == base
        assert recovered_task["published"] is False

        status = _call_tool(
            reconnected,
            fixture.contributor_api,
            "get_task",
            {"task_id": task_id},
            404,
        )
        current = status.json()["result"]["structuredContent"]
        assert current["native_candidate"] == recovered_task["native_candidate"]
        assert current["native_review"] == recovered_task["native_review"]
        reader = _call_tool(
            reconnected,
            fixture.contributor_api,
            "read_knowledge",
            {"title": "Published Runbook"},
            405,
        )
        published = reader.json()["result"]["structuredContent"]
        assert published["markdown"].strip() == SENTINEL

    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "rev-parse", "refs/heads/operator-keep") == base
    assert _git(repo, "rev-parse", f"refs/heads/{branch}") == recovered_task["native_candidate"]
    assert (config.authoring_path / ".lumio-authoring.yaml").read_bytes() == manifest_before
    versions = SourceRegistry(fixture.registry_path).get("runbook-source").versions
    assert [version.content_hash for version in versions] == [EXPECTED_SHA256]
    store = LocalDirectoryArtifactStore(fixture.artifact_path)
    assert store.get_artifact(source_id="runbook-source", content_hash=EXPECTED_SHA256) == ORIGINAL


def test_moved_profile_requires_matching_owner_confirmation(tmp_path: Path, monkeypatch) -> None:
    fixture = _workspace_fixture(tmp_path, monkeypatch)
    old_config = fixture.config
    assert old_config.authoring_path is not None
    assert old_config.private_profile_path is not None
    base = _adopt_without_setup(fixture)
    repo = old_config.authoring_path.parent
    history_before = _git(repo, "log", "--format=%H")
    manifest_before = (old_config.authoring_path / ".lumio-authoring.yaml").read_bytes()
    control_before = (old_config.authoring_path / "lumio.yaml").read_bytes()

    with TestClient(create_app(old_config), base_url="https://workspace.test") as client:
        _owner_setup(client, fixture)
        uploaded = _upload(
            client, fixture.contributor_api, ORIGINAL, retry_key="moved-profile-upload"
        )
        assert uploaded.status_code == 200
        upload_id = uploaded.json()["upload_id"]

    old_profile = old_config.private_profile_path
    moved_profile = old_profile.parent / "moved" / "profile.json"
    moved_profile.parent.mkdir()
    profile_bytes = old_profile.read_bytes()
    old_profile.rename(moved_profile)
    assert moved_profile.read_bytes() == profile_bytes
    moved_config = replace(old_config, private_profile_path=moved_profile)

    with TestClient(create_app(moved_config), base_url="https://workspace.test") as client:
        refused = _prepare(
            client,
            fixture.contributor_api,
            retry_key="moved-profile-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=501,
        )
        refused_result = refused.json()["result"]
        assert refused_result["isError"] is True
        assert "owner must confirm setup" in refused_result["content"][0]["text"]

        _login(client, fixture.owner_browser)
        old_confirmation = client.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(client.get("/setup").text)},
        )
        assert old_confirmation.status_code == 200, old_confirmation.text
        assert old_confirmation.json()["ready"] is True

        approved = _prepare(
            client,
            fixture.contributor_api,
            retry_key="moved-profile-prepare",
            base=base,
            upload_id=upload_id,
            intent="new",
            request_id=502,
        )
        approved_result = approved.json()["result"]
        assert approved_result["isError"] is False, approved_result
        approved_task = approved_result["structuredContent"]
        assert approved_task["status"] == "pending_review"
        assert approved_task["native_base"] == base
        assert approved_task["published"] is False

    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "log", "--format=%H") == history_before
    assert (old_config.authoring_path / ".lumio-authoring.yaml").read_bytes() == manifest_before
    assert (old_config.authoring_path / "lumio.yaml").read_bytes() == control_before
    versions = SourceRegistry(fixture.registry_path).get("runbook-source").versions
    assert [version.content_hash for version in versions] == [EXPECTED_SHA256]


@dataclass
class RetentionFixture:
    config: WorkspaceConfig
    solo_api: str
    solo_browser: str
    registry_path: Path
    artifact_path: Path
    profile_path: Path
    base: str
    published_revision: str


def _retention_fixture(tmp_path: Path, monkeypatch, *, policy: str) -> RetentionFixture:
    """Standalone workspace adopted at an admitted synthetic baseline.

    The owner profile declares `policy` retention. Adoption is the owner
    route for a disabled profile: the managed empty setup refuses
    non-required retention (spec0010 §2.1/§2.2). The admitted baseline is
    native admission of this actual history, so the destination pointer
    resolves inside the authoring repository for complete reviews.
    """
    monkeypatch.setenv("LUMIO_WORKSPACE_ID", "workspace-fixture")
    monkeypatch.setenv("LUMIO_WORKSPACE_STATE_PATH", str(tmp_path / "state.sqlite3"))
    authoring_repo = tmp_path / "authoring-repo"
    authoring_kb = authoring_repo / "kb"
    authoring_kb.mkdir(parents=True)
    published_path = tmp_path / "published"
    write_control_file(authoring_kb, document_first_control_file(seeded_control_file()))
    (authoring_kb / "published.md").write_text(
        "---\n"
        'id: "entity:published-runbook"\n'
        'title: "Published Runbook"\n'
        'entity_types: ["knowledge-artifact"]\n'
        "category: procedures\n"
        'type: "runbook"\n'
        'durability_rationale: "The synthetic fixture is permanent."\n'
        'tags: ["operations"]\n'
        'summary: "Synthetic fixture."\n'
        'lifecycle: "approved"\n'
        'visibility: "internal"\n'
        'sources:\n  - id: "public-fixture"\n    title: "Synthetic fixture"\n'
        "claims: []\n"
        "synthetic: true\n"
        "---\n\n"
        f"{SENTINEL}\n",
        encoding="utf-8",
    )
    (authoring_kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    _git(authoring_repo, "init", "-q")
    _git(authoring_repo, "config", "user.name", "Fixture")
    _git(authoring_repo, "config", "user.email", "fixture@example.invalid")
    _git(authoring_repo, "add", "kb")
    _git(authoring_repo, "commit", "-qm", "adopted synthetic base")
    base = _git(authoring_repo, "rev-parse", "HEAD")
    admission_review = preview_publication(authoring_kb, base, published_path, "none")
    assert admission_review.blocking_diagnostics == []
    assert publish_revision(
        authoring_kb, base, published_path, "none", admission_review.review_digest
    ).activated
    private = tmp_path / "profile-private"
    private.mkdir()
    profile_path = private / "profile.json"
    registry_path = private / "registry"
    artifact_path = private / "artifacts"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(registry_path),
                "retention": policy,
                "artifact_store": {"kind": "local", "root": str(artifact_path)},
            }
        ),
        encoding="utf-8",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=published_path,
        published_version=base,
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=authoring_kb,
        private_profile_path=profile_path,
        private_root=tmp_path / "operations",
        namespace=NAMESPACE,
    )
    state = WorkspaceState(config.state_path)
    state.create_local_user("solo")
    solo = Actor(tenant_id="local", object_id="solo")
    for capability in ("read", "setup", "contribute", "review"):
        state.grant(config.workspace_id, solo, capability)
    expires = int(time.time()) + 3600
    _, solo_api = state.issue_local_credential("solo", "api", expires_at=expires)
    _, solo_browser = state.issue_local_credential("solo", "browser", expires_at=expires)
    return RetentionFixture(
        config,
        solo_api,
        solo_browser,
        registry_path,
        artifact_path,
        profile_path,
        base,
        base,
    )


@pytest.mark.parametrize("policy", ["required", "disabled"])
def test_retention_exception_requires_owner_and_preserves_default_gates(
    tmp_path: Path, monkeypatch, policy: str
) -> None:
    """AC25 oracle: default refusal, owner-confirmed standalone exception.

    Expected values come from spec0034 §12.4/AC25 and the fixture identities
    (ORIGINAL/EXPECTED_SHA256), never from implementation output.
    """
    fixture = _retention_fixture(tmp_path, monkeypatch, policy=policy)
    config = fixture.config
    authoring_kb = config.authoring_path
    assert authoring_kb is not None

    # Gate 1 (both policies): the existing default-native call — exactly what
    # the independent CLI passes with no store selected, and the shape every
    # unmodified caller keeps — refuses omission BEFORE registration/writes.
    original_path = tmp_path / "original.md"
    original_path.write_bytes(ORIGINAL)
    page_path = tmp_path / "working" / "restart-worker.md"
    page_path.parent.mkdir()
    page_path.write_text(_page("runbook-source"), encoding="utf-8")
    # The same complete request the managed caller assembles: the adopted
    # KB's document-first Control File, working files outside the repository.
    control_path = write_control_file(
        page_path.parent,
        document_first_control_file(load_control_file(authoring_kb)),
    )
    with pytest.raises(AuthoringJourneyError) as default_refusal:
        ingest_candidate(
            authoring_kb,
            CandidateRequest(
                schema_version=1,
                base_revision=fixture.base,
                sources=[
                    CandidateSourceRecord(
                        source_id="runbook-source",
                        original_path=str(original_path),
                        expected_digest=EXPECTED_SHA256,
                        intent="new",
                    )
                ],
                pages=[str(page_path)],
                control=str(control_path),
            ),
            source_registry=SourceRegistry(fixture.registry_path),
        )
    assert default_refusal.value.code == "retention_required"
    assert SourceRegistry(fixture.registry_path).list() == []
    assert (authoring_kb / ".lumio-authoring.yaml").read_bytes() == (
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )

    with TestClient(create_app(config), base_url="https://workspace.test") as client:
        _login(client, fixture.solo_browser)
        preview = client.get("/setup")
        assert preview.status_code == 200, preview.text
        assert f"<dd>{policy}</dd>" in preview.text
        if policy == "disabled":
            assert "does not promise a durable original copy" in preview.text
        confirmed = client.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(preview.text)},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["kind"] == "adopted"

        uploaded = _upload(client, fixture.solo_api, ORIGINAL, retry_key="retention-upload")
        assert uploaded.status_code == 200, uploaded.text
        upload_id = uploaded.json()["upload_id"]

        pointer = PublishedFilesystemLocation(config.published_path).read_pointer()
        assert pointer == fixture.published_revision

        if policy == "required":
            # Gate 2a: default retention treats a failed store as an error,
            # never as permission to omit originals: no activation, no bytes.
            def failing_put(self, **_kwargs):
                raise ArtifactStoreError("simulated store outage")

            real_put = LocalDirectoryArtifactStore.put_artifact
            monkeypatch.setattr(LocalDirectoryArtifactStore, "put_artifact", failing_put)
            failed = _prepare(
                client,
                fixture.solo_api,
                retry_key="retention-prepare",
                upload_id=upload_id,
                intent="new",
                request_id=10,
            )
            failed_result = failed.json()["result"]
            assert failed_result["isError"] is True
            assert "Source Artifact retention failed" in failed_result["content"][0]["text"]
            assert PublishedFilesystemLocation(config.published_path).read_pointer() == pointer
            assert not (fixture.artifact_path / "artifacts").exists()

            # Same-input retry preserves the recorded task identity.
            replay = _prepare(
                client,
                fixture.solo_api,
                retry_key="retention-prepare",
                upload_id=upload_id,
                intent="new",
                request_id=11,
            )
            replay_task = replay.json()["result"]["structuredContent"]
            assert replay_task["status"] == "failed"
            assert replay_task["code"] == "retention_failed"
            assert replay_task["task_id"]

            # The retained route itself still works once the store recovers.
            monkeypatch.setattr(LocalDirectoryArtifactStore, "put_artifact", real_put)
            recovered = _prepare(
                client,
                fixture.solo_api,
                retry_key="retention-prepare-recovered",
                upload_id=upload_id,
                intent="new",
                request_id=12,
            )
            recovered_result = recovered.json()["result"]
            assert recovered_result["isError"] is False, recovered_result
            assert recovered_result["structuredContent"]["status"] == "pending_review"
            assert (
                LocalDirectoryArtifactStore(fixture.artifact_path).get_artifact(
                    source_id="runbook-source", content_hash=EXPECTED_SHA256
                )
                == ORIGINAL
            )
            candidate = recovered_result["structuredContent"]["native_candidate"]
        else:
            # Gate 2b: the owner-confirmed standalone exception admits the
            # document WITHOUT durable bytes and without any store probe,
            # while identity/hash/binding stay exact and source-backed.
            prepared = _prepare(
                client,
                fixture.solo_api,
                retry_key="retention-prepare",
                upload_id=upload_id,
                intent="new",
                request_id=10,
            )
            prepared_result = prepared.json()["result"]
            assert prepared_result["isError"] is False, prepared_result
            task = prepared_result["structuredContent"]
            assert task["status"] == "pending_review"
            binding = task["candidate"]["bindings"][0]
            assert binding["content_hash"] == EXPECTED_SHA256
            assert binding["registered"] is True
            assert binding["retained"] is False
            versions = SourceRegistry(fixture.registry_path).get("runbook-source").versions
            assert [version.content_hash for version in versions] == [EXPECTED_SHA256]
            assert not fixture.artifact_path.exists()

            replay = _prepare(
                client,
                fixture.solo_api,
                retry_key="retention-prepare",
                upload_id=upload_id,
                intent="new",
                request_id=11,
            )
            replay_task = replay.json()["result"]["structuredContent"]
            assert replay_task["task_id"] == task["task_id"]
            assert replay_task["native_candidate"] == task["native_candidate"]
            assert len(SourceRegistry(fixture.registry_path).get("runbook-source").versions) == 1

            # Gate 3: reviewable publication — disclosed policy, source-backed
            # page, real binding records, and no retained-original claim. The
            # pre-flip review first proves the pending standalone task is
            # reviewable in its own context before the mode transition below.
            candidate = task["native_candidate"]
            standalone_review = client.get(f"/review/{task['task_id']}")
            assert standalone_review.status_code == 200, standalone_review.text
            assert "<dd>disabled</dd>" in standalone_review.text
            # review-only member: one static state, no original claim (spec0035 §3)
            assert "source inspection requires separate authorization" in standalone_review.text
            assert "verified retained original" not in standalone_review.text
            pre_flip_digest = _digest(standalone_review.text)

            # F1 mode transition (named integrated negative): the operator
            # enables the complete analytics configuration on the SAME
            # workspace/KB/state while the legitimate standalone no-original
            # document is still pending. The retention exception cannot follow
            # the workspace into integrated context (spec0035 §3/AC12, AC25).
            # The artifact store is AVAILABLE: the refusals below are policy,
            # not a missing backend.
            analytics_project = tmp_path / "analytics-project"
            analytics_project.mkdir()
            (analytics_project / "ariadne.yaml").write_text("sources: []\n", encoding="utf-8")
            bindings_path = tmp_path / "analytics-bindings.json"
            bindings_path.write_text("{}", encoding="utf-8")
            integrated_config = replace(
                config,
                analytics_project_id="retail",
                analytics_project_path=analytics_project,
                analytics_source_bindings_path=bindings_path,
            )
            fixture.artifact_path.mkdir()
            sentinel_receipt = (
                config.published_path
                / ".lumio-publication"
                / "receipts"
                / f"{fixture.published_revision}.json"
            )
            assert sentinel_receipt.exists()
            with TestClient(
                create_app(integrated_config), base_url="https://workspace.test"
            ) as integrated:
                _login(integrated, fixture.solo_browser)
                integrated_setup = integrated.get("/setup")
                assert integrated_setup.status_code == 409, integrated_setup.text
                assert integrated_setup.json()["code"] == "retention_context_incompatible"

                blocked_review = integrated.get(f"/review/{task['task_id']}")
                assert blocked_review.status_code == 409, blocked_review.text
                assert blocked_review.json()["code"] == "retention_context_incompatible"
                assert PublishedFilesystemLocation(config.published_path).read_pointer() == pointer
                assert (
                    len(SourceRegistry(fixture.registry_path).get("runbook-source").versions) == 1
                )

                stale_action = integrated.post(
                    f"/review/{task['task_id']}",
                    headers={"Origin": "https://workspace.test"},
                    data={"digest": pre_flip_digest, "decision": "approve"},
                )
                assert stale_action.status_code == 409, stale_action.text
                assert stale_action.json()["code"] == "retention_context_incompatible"
                assert PublishedFilesystemLocation(config.published_path).read_pointer() == pointer

                from ariadne import proposals as native_proposals

                head_before = _git(authoring_kb.parent, "rev-parse", "HEAD")
                blocked_prepare = _call_tool(
                    integrated,
                    fixture.solo_api,
                    "prepare_contribution",
                    {
                        "retry_key": "integrated-negative",
                        "source_task_id": "missing-grant",
                        "sources": [{"upload_id": upload_id, "intent": "new"}],
                        "pages": [
                            {
                                "filename": "integrated.md",
                                "markdown": _page("runbook-source"),
                            }
                        ],
                    },
                    20,
                )
                blocked_result = blocked_prepare.json()["result"]
                assert blocked_result["isError"] is True
                assert (
                    "requires required original retention" in blocked_result["content"][0]["text"]
                )
                assert _git(authoring_kb.parent, "rev-parse", "HEAD") == head_before
                versions = SourceRegistry(fixture.registry_path).get("runbook-source").versions
                assert len(versions) == 1
                assert PublishedFilesystemLocation(config.published_path).read_pointer() == pointer
                assert not (analytics_project / native_proposals.WORKTREES_REL).exists()

            # Genuinely standalone again (analytics removed from the config):
            # the owner-confirmed exception remains allowed and the pending
            # document still reviewably publishes without originals.
            with TestClient(create_app(config), base_url="https://workspace.test") as standalone:
                _login(standalone, fixture.solo_browser)
                review = standalone.get(f"/review/{task['task_id']}")
                assert review.status_code == 200, review.text
                assert "<dd>disabled</dd>" in review.text
                # review-only member: one static state, no original claim (spec0035 §3)
                assert "source inspection requires separate authorization" in review.text
                assert "verified retained original" not in review.text
                decided = standalone.post(
                    f"/review/{task['task_id']}",
                    headers={"Origin": "https://workspace.test"},
                    data={"digest": _digest(review.text), "decision": "approve"},
                )
            assert decided.status_code == 200, decided.text
            publication = decided.json()
            assert publication["status"] == "published"
            assert publication["published"] is True
            receipt = publication["publication"]
            assert receipt["activated"] is True
            assert receipt["retention"] == "disabled"
            assert PublishedFilesystemLocation(config.published_path).read_pointer() == candidate

            sealed = json.loads(
                (
                    config.published_path / ".lumio-publication" / "bindings" / f"{candidate}.json"
                ).read_bytes()
            )
            assert sealed["sources"] == {"runbook-source": "active"}
            assert sealed["bindings"][binding["entity_id"]]["runbook-source"] == EXPECTED_SHA256
            # The store stayed available-but-unused by the exception: no
            # original bytes were ever retained into it.
            assert not (fixture.artifact_path / "artifacts").exists()

            # A reader without the fixture's version pin follows the live
            # pointer; the qualified follow-up serves exactly the new version.
            with TestClient(
                create_app(replace(config, published_version=None)),
                base_url="https://workspace.test",
            ) as reader_client:
                reader = _call_tool(
                    reader_client,
                    fixture.solo_api,
                    "read_knowledge",
                    {"title": "Restart Worker", "published_version": candidate},
                    12,
                )
            page_view = reader.json()["result"]["structuredContent"]
            assert page_view["found"] is True
            assert "Stop the old worker." in page_view["markdown"]
            assert page_view["citation"]["published_version"] == candidate
            assert page_view["entity_id"] == binding["entity_id"]
            assert [source["id"] for source in page_view["sources"]] == ["runbook-source"]
            assert page_view["sources"][0]["reference"] == (
                f"/original/{candidate}/{quote(binding['entity_id'])}/runbook-source"
            )

        # Gate 4 (both policies): changing the effective retention policy
        # invalidates the recorded owner consent — including a change toward
        # the exception — and nothing new registers or activates.
        profile = json.loads(fixture.profile_path.read_text(encoding="utf-8"))
        profile["retention"] = "required" if policy == "disabled" else "disabled"
        fixture.profile_path.write_text(json.dumps(profile), encoding="utf-8")
        changed_upload = _upload(
            client,
            fixture.solo_api,
            EDITED,
            source_id="changed-source",
            retry_key="retention-changed-upload",
        )
        assert changed_upload.status_code == 200
        stale = _prepare(
            client,
            fixture.solo_api,
            retry_key="retention-changed",
            upload_id=changed_upload.json()["upload_id"],
            intent="new",
            source_id="changed-source",
            request_id=13,
        )
        stale_result = stale.json()["result"]
        assert stale_result["isError"] is True
        assert "owner must confirm setup" in stale_result["content"][0]["text"]
        expected_pointer = candidate if policy == "disabled" else fixture.published_revision
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == expected_pointer
