from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import pytest
from lumio_wiki.artifact_store import LocalDirectoryArtifactStore
from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
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
        serialize_source_reference_manifest(
            SourceReferenceManifest(version=1, namespace=NAMESPACE)
        )
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
    base: str,
    upload_id: str,
    intent: str,
    source_id: str = "runbook-source",
    edited: bool = False,
    request_id: int,
):
    return _call_tool(
        client,
        token,
        "prepare_contribution",
        {
            "retry_key": retry_key,
            "base_revision": base,
            "sources": [{"upload_id": upload_id, "intent": intent}],
            "pages": [
                {
                    "filename": "restart-worker.md",
                    "markdown": _page(source_id, edited=edited),
                }
            ],
        },
        request_id,
    )


def test_exact_upload_retry_preserves_source_and_pending_visibility(
    tmp_path: Path, monkeypatch
) -> None:
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
    assert main(
        ["local-membership", "grant", "--user-id", "contributor", "--capability", "contribute"]
    ) == 0
    assert state.capabilities(config.workspace_id, owner) == ("setup",)
    assert state.capabilities(config.workspace_id, contributor) == ("contribute", "read")
    _, owner_api = state.issue_local_credential("owner", "api", expires_at=expires)
    _, owner_browser = state.issue_local_credential("owner", "browser", expires_at=expires)
    _, contributor_api = state.issue_local_credential("contributor", "api", expires_at=expires)
    _, contributor_browser = state.issue_local_credential(
        "contributor", "browser", expires_at=expires
    )

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
        assert store.get_artifact(
            source_id="runbook-source", content_hash=EXPECTED_SHA256
        ) == ORIGINAL

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
            base=first_candidate,
            upload_id=edited_upload.json()["upload_id"],
            intent="update",
            edited=True,
            request_id=5,
        )
        assert second.status_code == 200, second.text
        second_task = second.json()["result"]["structuredContent"]
        assert second_task["status"] == "pending_review"
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
