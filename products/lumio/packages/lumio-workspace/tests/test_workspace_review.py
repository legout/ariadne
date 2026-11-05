from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path

import lumio_wiki.git_authoring as native_authoring
from lumio_wiki.artifact_store import LocalDirectoryArtifactStore
from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.knowledge_base import (
    document_first_control_file,
    seeded_control_file,
    write_control_file,
)
from lumio_wiki.location import PublishedFilesystemLocation, published_pointer_path
from lumio_wiki.private_profile import load_private_profile, resolve_private_profile
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
from lumio_workspace.publication import PublicationService
from starlette.testclient import TestClient

NAMESPACE = "urn:uuid:6c6e21ec-98a4-4c0b-9153-c2eb5d3c2210"
SENTINEL = "The previously admitted sentinel remains pinned."
ORIGINAL = b"# Restart worker\r\n\r\nStop the old worker.\r\n<unsafe>&review\r\nThen start it."
EXPECTED_SHA256 = hashlib.sha256(ORIGINAL).hexdigest()
EXPECTED_BODY = "# Restart Worker\n\nStop the old worker.\n\n<unsafe>&review\n\nThen start it."
EXPECTED_PATH = "procedures/restart_worker.md"
ANCESTOR_BODY = "Ancestor page content must remain visible in the final review."
CONTINUATION_BODY = "Continuation page content must also be visible in the final review."


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _published_sentinel(authoring_repo: Path, destination: Path) -> str:
    kb = authoring_repo / "kb"
    kb.mkdir(parents=True)
    write_control_file(kb, document_first_control_file(seeded_control_file()))
    (kb / "published.md").write_text(
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
    (kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    _git(authoring_repo, "init", "-q")
    _git(authoring_repo, "config", "user.name", "Fixture")
    _git(authoring_repo, "config", "user.email", "fixture@example.invalid")
    _git(authoring_repo, "add", "kb")
    _git(authoring_repo, "commit", "-qm", "adopted synthetic base")
    revision = _git(authoring_repo, "rev-parse", "HEAD")
    review = preview_publication(kb, revision, destination, "none")
    assert review.blocking_diagnostics == []
    assert publish_revision(kb, revision, destination, "none", review.review_digest).activated
    return revision


def _page(title: str, addition: str, source_id: str) -> str:
    entity = title.lower().replace(" ", "-")
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
        "<unsafe>&review\n\n"
        f"{addition}\n"
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


def _upload(client: TestClient, token: str, raw: bytes, retry_key: str, source_id: str):
    return client.post(
        "/uploads",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "X-Lumio-Source-ID": source_id,
            "X-Lumio-Filename": "runbook.md",
            "X-Lumio-Retry-Key": retry_key,
        },
        content=raw,
    )


def _prepare(
    client: TestClient,
    token: str,
    *,
    retry_key: str,
    upload_id: str,
    title: str,
    addition: str,
    source_id: str,
    continuation_task_id: str | None = None,
    filename: str = "restart-worker.md",
    request_id: int,
):
    arguments = {
        "retry_key": retry_key,
        "sources": [{"upload_id": upload_id, "intent": "new"}],
        "pages": [
            {"filename": filename, "markdown": _page(title, addition, source_id)}
        ],
    }
    if continuation_task_id is not None:
        arguments["continuation_task_id"] = continuation_task_id
    return _call_tool(client, token, "prepare_contribution", arguments, request_id)


def _contribute(
    client: TestClient,
    fixture: Fixture,
    *,
    retry_key: str,
    title: str,
    addition: str,
    source_id: str,
    filename: str,
    continuation_task_id: str | None = None,
    request_id: int,
) -> dict:
    uploaded = _upload(client, fixture.contributor_api, ORIGINAL, retry_key, source_id)
    assert uploaded.status_code == 200, uploaded.text
    prepared = _prepare(
        client,
        fixture.contributor_api,
        retry_key=retry_key,
        upload_id=uploaded.json()["upload_id"],
        title=title,
        addition=addition,
        source_id=source_id,
        continuation_task_id=continuation_task_id,
        filename=filename,
        request_id=request_id,
    )
    result = prepared.json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


def _confirm_setup(client: TestClient, fixture: Fixture) -> None:
    _login(client, fixture.owner_browser)
    response = client.post(
        "/setup",
        headers={"Origin": "https://workspace.test"},
        data={"digest": _digest(client.get("/setup").text)},
    )
    assert response.status_code == 200, response.text


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


def _decision(client: TestClient, task_id: str, digest: str, decision: str):
    return client.post(
        f"/review/{task_id}",
        headers={"Origin": "https://workspace.test"},
        data={"digest": digest, "decision": decision},
    )


@dataclass
class Fixture:
    config: WorkspaceConfig
    state: WorkspaceState
    reviewer: Actor
    owner_browser: str
    contributor_api: str
    contributor_browser: str
    reviewer_api: str
    reviewer_browser: str
    published_revision: str
    artifact_path: Path


def _fixture(tmp_path: Path, monkeypatch, *, single_person: bool = False) -> Fixture:
    monkeypatch.setenv("LUMIO_WORKSPACE_ID", "workspace-fixture")
    monkeypatch.setenv("LUMIO_WORKSPACE_STATE_PATH", str(tmp_path / "state.sqlite3"))
    authoring_repo = tmp_path / "authoring-repo"
    authoring_kb = authoring_repo / "kb"
    authoring_repo.mkdir()
    published_path = tmp_path / "published"
    published_revision = _published_sentinel(authoring_repo, published_path)
    private = tmp_path / "profile-private"
    private.mkdir()
    profile_path = private / "profile.json"
    artifact_path = private / "artifacts"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(private / "registry"),
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
    if single_person:
        state.create_local_user("solo")
        owner = contributor = reviewer = Actor(tenant_id="local", object_id="solo")
        for capability in ("read", "setup", "contribute", "review"):
            state.grant(config.workspace_id, owner, capability)
        users = ("solo",)
    else:
        users = ("owner", "contributor", "reviewer")
        for user in users:
            state.create_local_user(user)
        owner = Actor(tenant_id="local", object_id="owner")
        contributor = Actor(tenant_id="local", object_id="contributor")
        reviewer = Actor(tenant_id="local", object_id="reviewer")
        state.grant(config.workspace_id, owner, "setup")
        state.grant(config.workspace_id, contributor)
        state.grant(config.workspace_id, contributor, "contribute")
        state.grant(config.workspace_id, reviewer, "review")
    owner_id = owner.object_id
    contributor_id = contributor.object_id
    reviewer_id = reviewer.object_id
    _, owner_browser = state.issue_local_credential(owner_id, "browser", expires_at=expires)
    contributor_api = state.issue_local_credential(contributor_id, "api", expires_at=expires)[1]
    contributor_browser = state.issue_local_credential(
        contributor_id, "browser", expires_at=expires
    )[1]
    reviewer_api = state.issue_local_credential(reviewer_id, "api", expires_at=expires)[1]
    reviewer_browser = state.issue_local_credential(reviewer_id, "browser", expires_at=expires)[1]
    return Fixture(
        config,
        state,
        reviewer,
        owner_browser,
        contributor_api,
        contributor_browser,
        reviewer_api,
        reviewer_browser,
        published_revision,
        artifact_path,
    )


def test_browser_review_is_required_and_binds_exact_candidate(tmp_path: Path, monkeypatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None and config.private_profile_path is not None
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
        TestClient(create_app(config), base_url="https://workspace.test") as api_only,
        TestClient(create_app(config), base_url="https://workspace.test") as pinned_reader,
        TestClient(
            create_app(replace(config, published_version=None)),
            base_url="https://workspace.test",
        ) as reader,
    ):
        _login(owner, fixture.owner_browser)
        setup = owner.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(owner.get("/setup").text)},
        )
        assert setup.status_code == 200, setup.text

        uploaded = _upload(
            contributor, fixture.contributor_api, ORIGINAL, "review-upload", "runbook-source"
        )
        assert uploaded.status_code == 200, uploaded.text
        first = _prepare(
            contributor,
            fixture.contributor_api,
            retry_key="review-prepare",
            upload_id=uploaded.json()["upload_id"],
            title="Restart Worker",
            addition="Then start it.",
            source_id="runbook-source",
            request_id=1,
        )
        first_result = first.json()["result"]
        assert first_result["isError"] is False, first_result
        task = first_result["structuredContent"]
        task_id = task["task_id"]
        candidate = task["native_candidate"]
        assert task["status"] == "pending_review"
        assert task["published"] is False

        concurrent_raw = ORIGINAL + b"\r\nConcurrent candidate."
        concurrent_upload = _upload(
            contributor,
            fixture.contributor_api,
            concurrent_raw,
            "concurrent-upload",
            "concurrent-source",
        )
        second = _prepare(
            contributor,
            fixture.contributor_api,
            retry_key="concurrent-prepare",
            upload_id=concurrent_upload.json()["upload_id"],
            title="Concurrent Worker",
            addition="Concurrent candidate.",
            source_id="concurrent-source",
            request_id=2,
        ).json()["result"]["structuredContent"]
        third_raw = ORIGINAL + b"\r\nFinal reviewed source."
        third_upload = _upload(
            contributor, fixture.contributor_api, third_raw, "third-upload", "final-source"
        )
        third = _prepare(
            contributor,
            fixture.contributor_api,
            retry_key="third-prepare",
            upload_id=third_upload.json()["upload_id"],
            title="Restart Worker",
            addition="Then start it.",
            source_id="final-source",
            continuation_task_id=second["task_id"],
            request_id=3,
        ).json()["result"]["structuredContent"]
        fourth_raw = third_raw + b"\r\nRejected candidate."
        fourth_upload = _upload(
            contributor, fixture.contributor_api, fourth_raw, "fourth-upload", "rejected-source"
        )
        fourth = _prepare(
            contributor,
            fixture.contributor_api,
            retry_key="fourth-prepare",
            upload_id=fourth_upload.json()["upload_id"],
            title="Rejected Worker",
            addition="Rejected candidate.",
            source_id="rejected-source",
            continuation_task_id=third["task_id"],
            request_id=30,
        ).json()["result"]["structuredContent"]
        fifth_raw = fourth_raw + b"\r\nChanges requested candidate."
        fifth_upload = _upload(
            contributor, fixture.contributor_api, fifth_raw, "fifth-upload", "changes-source"
        )
        fifth = _prepare(
            contributor,
            fixture.contributor_api,
            retry_key="fifth-prepare",
            upload_id=fifth_upload.json()["upload_id"],
            title="Changes Worker",
            addition="Changes requested candidate.",
            source_id="changes-source",
            continuation_task_id=fourth["task_id"],
            request_id=31,
        ).json()["result"]["structuredContent"]

        pending_read = _call_tool(
            reader, fixture.contributor_api, "read_knowledge", {"title": "Restart Worker"}, 4
        )
        assert pending_read.json()["result"]["structuredContent"] == {"found": False}

        _login(contributor, fixture.contributor_browser)
        assert contributor.get(f"/review/{task_id}").status_code == 403
        _login(reviewer, fixture.reviewer_browser)
        review = reviewer.get(f"/review/{task_id}")
        assert review.status_code == 200, review.text
        assert "&lt;unsafe&gt;&amp;review" in review.text
        assert "<unsafe>&review" not in review.text
        assert config.published_path.as_posix() in review.text
        assert candidate in review.text
        assert (
            f'href="/review/{task_id}/source/runbook-source/'
            'entity%3Arestart-worker-runbook"' in review.text
        )
        stale_digest = _digest(review.text)

        api_only.headers["Authorization"] = f"Bearer {fixture.reviewer_api}"
        assert _decision(api_only, task_id, stale_digest, "approve").status_code == 401
        cross_origin = reviewer.post(
            f"/review/{task_id}",
            headers={"Origin": "https://attacker.invalid"},
            data={"digest": stale_digest, "decision": "approve"},
        )
        assert cross_origin.status_code == 403
        assert _decision(reviewer, task_id, "0" * 64, "approve").status_code == 409
        with fixture.state._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM review_actions WHERE decision != ''"
            ).fetchone()[0] == 0

        source_url = (
            f"/review/{task_id}/source/runbook-source/entity:restart-worker-runbook"
        )
        denied_source = reviewer.get(source_url)
        assert denied_source.status_code == 403
        assert "Stop the old worker" not in denied_source.text
        fixture.state.grant(config.workspace_id, fixture.reviewer, "inspect_source")
        original = reviewer.get(source_url)
        assert original.status_code == 200, original.text
        assert "&lt;unsafe&gt;&amp;review" in original.text

        # A real native concurrent activation makes the first browser action stale.
        profile = load_private_profile(
            config.private_profile_path, kb_root=config.authoring_path
        )
        native = resolve_private_profile(
            profile, kb_root=config.authoring_path, needs=frozenset({"registry", "artifacts"})
        )
        concurrent_kb = config.operational_root / "worktrees" / second["task_id"] / "kb"
        concurrent = second["native_candidate"]
        concurrent_review = preview_publication(
            concurrent_kb,
            concurrent,
            config.published_path,
            fixture.published_revision,
            source_registry=native.source_registry,
            artifact_store=native.artifact_store,
            retention_required=True,
        )
        assert concurrent_review.blocking_diagnostics == []
        publish_revision(
            concurrent_kb,
            concurrent,
            config.published_path,
            fixture.published_revision,
            concurrent_review.review_digest,
            source_registry=native.source_registry,
            artifact_store=native.artifact_store,
            retention_required=True,
        )
        stale = _decision(reviewer, task_id, stale_digest, "approve")
        assert stale.status_code == 409
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == concurrent

        task_id = third["task_id"]
        candidate = third["native_candidate"]
        fresh_review = reviewer.get(f"/review/{task_id}")
        assert fresh_review.status_code == 200, fresh_review.text
        fresh_digest = _digest(fresh_review.text)
        assert fresh_digest != stale_digest
        approved = _decision(reviewer, task_id, fresh_digest, "approve")
        assert approved.status_code == 200, approved.text
        publication = approved.json()
        assert publication["status"] == "published"
        assert publication["published"] is True
        assert publication["publication"]["activated"] is True
        assert publication["publication"]["version"] == candidate
        assert publication["citations"] == [
            {"title": "Restart Worker", "path": EXPECTED_PATH, "published_version": candidate}
        ]
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == candidate
        assert _decision(reviewer, task_id, fresh_digest, "approve").status_code == 409
        with fixture.state._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM review_actions WHERE decision != ''"
            ).fetchone()[0] == 1

        status = _call_tool(
            contributor, fixture.contributor_api, "get_task", {"task_id": task_id}, 5
        )
        current = status.json()["result"]["structuredContent"]
        assert current["status"] == "published"
        assert current["publication"]["version"] == candidate
        assert current["citations"][0]["published_version"] == candidate

        admitted = _call_tool(
            reader, fixture.contributor_api, "read_knowledge", {"title": "Restart Worker"}, 6
        )
        page = admitted.json()["result"]["structuredContent"]
        assert page["markdown"].strip() == EXPECTED_BODY
        assert page["citation"] == {
            "title": "Restart Worker",
            "path": EXPECTED_PATH,
            "published_version": candidate,
        }
        resolved = PublishedFilesystemLocation(config.published_path).resolve()
        assert resolved.lookup_by_title("Restart Worker")[0].body.strip() == EXPECTED_BODY
        assert LocalDirectoryArtifactStore(fixture.artifact_path).get_artifact(
            source_id="runbook-source", content_hash=EXPECTED_SHA256
        ) == ORIGINAL

        pinned = _call_tool(
            pinned_reader,
            fixture.contributor_api,
            "read_knowledge",
            {"title": "Published Runbook"},
            7,
        )
        pinned_page = pinned.json()["result"]["structuredContent"]
        assert pinned_page["markdown"].strip() == SENTINEL
        assert pinned_page["citation"]["published_version"] == fixture.published_revision

        rejected_digest = _digest(reviewer.get(f"/review/{fourth['task_id']}").text)
        rejected = _decision(reviewer, fourth["task_id"], rejected_digest, "reject")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["published"] is False
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == candidate
        rejected_read = _call_tool(
            reader, fixture.contributor_api, "read_knowledge", {"title": "Rejected Worker"}, 8
        )
        assert rejected_read.json()["result"]["structuredContent"] == {"found": False}

        changes_digest = _digest(reviewer.get(f"/review/{fifth['task_id']}").text)
        changes = _decision(reviewer, fifth["task_id"], changes_digest, "request_changes")
        assert changes.status_code == 200, changes.text
        assert changes.json()["status"] == "pending_review"
        assert changes.json()["review_decision"] == "request_changes"
        assert changes.json()["published"] is False
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == candidate

        revoked_digest = _digest(reviewer.get(f"/review/{fifth['task_id']}").text)
        fixture.state.revoke(config.workspace_id, fixture.reviewer, "review")
        revoked = _decision(reviewer, fifth["task_id"], revoked_digest, "approve")
        assert revoked.status_code == 403
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == candidate


def test_continuation_review_shows_complete_effective_changes(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with (
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as owner,
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as reviewer,
    ):
        _confirm_setup(owner, fixture)
        ancestor = _contribute(
            contributor,
            fixture,
            retry_key="effective-ancestor",
            title="Effective Ancestor",
            addition=ANCESTOR_BODY,
            source_id="effective-ancestor-source",
            filename="effective-ancestor.md",
            request_id=1,
        )
        continuation = _contribute(
            contributor,
            fixture,
            retry_key="effective-continuation",
            title="Effective Continuation",
            addition=CONTINUATION_BODY,
            source_id="effective-continuation-source",
            filename="effective-continuation.md",
            continuation_task_id=ancestor["task_id"],
            request_id=2,
        )
        assert continuation["native_base"] == ancestor["native_candidate"]

        _login(reviewer, fixture.reviewer_browser)
        review = reviewer.get(f"/review/{continuation['task_id']}")
        assert review.status_code == 200, review.text
        assert ANCESTOR_BODY in review.text
        assert CONTINUATION_BODY in review.text
        assert fixture.published_revision in review.text
        assert continuation["native_base"] in review.text
        assert continuation["native_candidate"] in review.text
        assert (
            PublishedFilesystemLocation(fixture.config.published_path).read_pointer()
            == fixture.published_revision
        )


def test_approval_requires_another_person_unless_workspace_has_one_member(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture.state.grant(fixture.config.workspace_id, fixture.reviewer, "contribute")
    contributor = Actor(tenant_id="local", object_id="contributor")
    fixture.state.grant(fixture.config.workspace_id, contributor, "review")
    with (
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as owner,
        TestClient(
            create_app(fixture.config), base_url="https://workspace.test"
        ) as contributor_client,
        TestClient(
            create_app(fixture.config), base_url="https://workspace.test"
        ) as reviewer_client,
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as api_only,
    ):
        _confirm_setup(owner, fixture)
        task = _contribute(
            contributor_client,
            fixture,
            retry_key="different-person",
            title="Different Person",
            addition="A second person must approve this candidate.",
            source_id="different-person-source",
            filename="different-person.md",
            request_id=1,
        )
        _login(contributor_client, fixture.contributor_browser)
        digest = _digest(contributor_client.get(f"/review/{task['task_id']}").text)
        api_only.headers["Authorization"] = f"Bearer {fixture.contributor_api}"
        assert _decision(api_only, task["task_id"], digest, "approve").status_code == 401
        self_approved = _decision(contributor_client, task["task_id"], digest, "approve")
        assert self_approved.status_code == 403
        assert (
            PublishedFilesystemLocation(fixture.config.published_path).read_pointer()
            == fixture.published_revision
        )

        _login(reviewer_client, fixture.reviewer_browser)
        fresh = _digest(reviewer_client.get(f"/review/{task['task_id']}").text)
        approved = _decision(reviewer_client, task["task_id"], fresh, "approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "published"

    single_root = tmp_path / "single-person"
    single_root.mkdir()
    single = _fixture(single_root, monkeypatch, single_person=True)
    with (
        TestClient(create_app(single.config), base_url="https://workspace.test") as owner,
        TestClient(
            create_app(single.config), base_url="https://workspace.test"
        ) as contributor_client,
        TestClient(create_app(single.config), base_url="https://workspace.test") as reviewer_client,
        TestClient(create_app(single.config), base_url="https://workspace.test") as api_only,
    ):
        _confirm_setup(owner, single)
        task = _contribute(
            contributor_client,
            single,
            retry_key="single-person",
            title="Single Person",
            addition="The sole capable member explicitly approves the combined action.",
            source_id="single-person-source",
            filename="single-person.md",
            request_id=2,
        )
        _login(reviewer_client, single.reviewer_browser)
        digest = _digest(reviewer_client.get(f"/review/{task['task_id']}").text)
        api_only.headers["Authorization"] = f"Bearer {single.contributor_api}"
        assert _decision(api_only, task["task_id"], digest, "approve").status_code == 401
        approved = _decision(reviewer_client, task["task_id"], digest, "approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "published"


def test_fresh_browser_action_allows_reconsideration_and_pre_activation_retry(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with (
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as owner,
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(fixture.config), base_url="https://workspace.test") as reviewer,
    ):
        _confirm_setup(owner, fixture)
        task = _contribute(
            contributor,
            fixture,
            retry_key="fresh-actions",
            title="Fresh Actions",
            addition="A fresh browser decision can reconsider this unchanged candidate.",
            source_id="fresh-actions-source",
            filename="fresh-actions.md",
            request_id=1,
        )
        _login(reviewer, fixture.reviewer_browser)
        first = _digest(reviewer.get(f"/review/{task['task_id']}").text)
        overlapping = _digest(reviewer.get(f"/review/{task['task_id']}").text)
        assert overlapping != first
        changes = _decision(reviewer, task["task_id"], first, "request_changes")
        assert changes.status_code == 200, changes.text
        assert changes.json()["status"] == "pending_review"

        stale = _decision(reviewer, task["task_id"], overlapping, "approve")
        assert stale.status_code == 409, stale.text
        assert (
            PublishedFilesystemLocation(fixture.config.published_path).read_pointer()
            == fixture.published_revision
        )
        with fixture.state._connect() as connection:
            assert connection.execute(
                "SELECT decision FROM review_actions WHERE action_digest = ?", (overlapping,)
            ).fetchone() == ("",)
            assert connection.execute(
                "SELECT action_digest, decision FROM review_actions WHERE decision != ''"
            ).fetchall() == [(first, "request_changes")]

        second = _digest(reviewer.get(f"/review/{task['task_id']}").text)
        assert second not in {first, overlapping}
        assert _decision(reviewer, task["task_id"], first, "approve").status_code == 409

        original_publish = PublicationService.publish

        def fail_before_activation(*args, **kwargs):
            raise OSError("injected failure before native activation")

        monkeypatch.setattr(PublicationService, "publish", fail_before_activation)
        failed = _decision(reviewer, task["task_id"], second, "approve")
        assert failed.status_code == 409
        assert (
            PublishedFilesystemLocation(fixture.config.published_path).read_pointer()
            == fixture.published_revision
        )
        monkeypatch.setattr(PublicationService, "publish", original_publish)

        third = _digest(reviewer.get(f"/review/{task['task_id']}").text)
        assert third not in {first, second}
        assert _decision(reviewer, task["task_id"], second, "approve").status_code == 409
        approved = _decision(reviewer, task["task_id"], third, "approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["publication"]["version"] == task["native_candidate"]


def test_task_recovery_distinguishes_prepared_and_completed_native_activation(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    config = fixture.config
    assert config.authoring_path is not None and config.private_profile_path is not None
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
    ):
        _confirm_setup(owner, fixture)
        prepared = _contribute(
            contributor,
            fixture,
            retry_key="prepared-not-activated",
            title="Prepared Not Activated",
            addition="A prepared receipt alone must not report publication.",
            source_id="prepared-not-activated-source",
            filename="prepared-not-activated.md",
            request_id=1,
        )
        _login(reviewer, fixture.reviewer_browser)
        prepared_digest = _digest(reviewer.get(f"/review/{prepared['task_id']}").text)
        original_atomic_write = native_authoring.atomic_write_bytes

        def fail_pointer_activation(path, data):
            if Path(path) == published_pointer_path(config.published_path):
                raise OSError("injected interruption before pointer activation")
            return original_atomic_write(path, data)

        monkeypatch.setattr(native_authoring, "atomic_write_bytes", fail_pointer_activation)
        interrupted = _decision(reviewer, prepared["task_id"], prepared_digest, "approve")
        assert interrupted.status_code == 409
        monkeypatch.setattr(native_authoring, "atomic_write_bytes", original_atomic_write)
        prepared_receipt_path = (
            config.published_path
            / ".lumio-publication"
            / "receipts"
            / f"{prepared['native_candidate']}.json"
        )
        assert json.loads(prepared_receipt_path.read_text())["activated"] is False
        assert (
            PublishedFilesystemLocation(config.published_path).read_pointer()
            == fixture.published_revision
        )

        activated = _contribute(
            contributor,
            fixture,
            retry_key="activated-before-bookkeeping-failure",
            title="Activated After Interruption",
            addition="The verified native activation must survive SQLite interruption.",
            source_id="activated-after-interruption-source",
            filename="activated-after-interruption.md",
            request_id=2,
        )
        activated_digest = _digest(reviewer.get(f"/review/{activated['task_id']}").text)
        original_finish = WorkspaceState.finish_review_task

        def fail_task_bookkeeping(*args, **kwargs):
            raise RuntimeError("injected SQLite failure after native activation")

        monkeypatch.setattr(WorkspaceState, "finish_review_task", fail_task_bookkeeping)
        interrupted = _decision(reviewer, activated["task_id"], activated_digest, "approve")
        assert interrupted.status_code == 409
        monkeypatch.setattr(WorkspaceState, "finish_review_task", original_finish)
        assert (
            PublishedFilesystemLocation(config.published_path).read_pointer()
            == activated["native_candidate"]
        )
        unrelated = _contribute(
            contributor,
            fixture,
            retry_key="unrelated-later-publication",
            title="Unrelated Later Publication",
            addition="A later pointer must not erase the earlier verified publication.",
            source_id="unrelated-later-publication-source",
            filename="unrelated-later-publication.md",
            continuation_task_id=activated["task_id"],
            request_id=7,
        )

    with TestClient(
        create_app(replace(config, published_version=None)), base_url="https://workspace.test"
    ) as reconnected:
        prepared_status = _call_tool(
            reconnected,
            fixture.contributor_api,
            "get_task",
            {"task_id": prepared["task_id"]},
            3,
        ).json()["result"]["structuredContent"]
        assert prepared_status["status"] == "pending_review"
        assert prepared_status["published"] is False

        recovered = _call_tool(
            reconnected,
            fixture.contributor_api,
            "get_task",
            {"task_id": activated["task_id"]},
            4,
        ).json()["result"]["structuredContent"]
        assert recovered["status"] == "published"
        assert recovered["published"] is True
        assert recovered["publication"]["activated"] is True
        assert recovered["publication"]["version"] == activated["native_candidate"]
        assert recovered["citations"] == [
            {
                "title": "Activated After Interruption",
                "path": "procedures/activated_after_interruption.md",
                "published_version": activated["native_candidate"],
            }
        ]
        reader_status = _call_tool(
            reconnected, fixture.contributor_api, "workspace_status", {}, 5
        ).json()["result"]["structuredContent"]
        assert reader_status["published_version"] == activated["native_candidate"]

        activated_receipt_path = (
            config.published_path
            / ".lumio-publication"
            / "receipts"
            / f"{activated['native_candidate']}.json"
        )
        receipt_after_recovery = activated_receipt_path.read_bytes()
        with fixture.state._connect() as connection:
            task_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE action = 'prepare_contribution'"
            ).fetchone()[0]
        repeated = _call_tool(
            reconnected,
            fixture.contributor_api,
            "get_task",
            {"task_id": activated["task_id"]},
            6,
        ).json()["result"]["structuredContent"]
        assert repeated["publication"] == recovered["publication"]
        assert activated_receipt_path.read_bytes() == receipt_after_recovery
        with fixture.state._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE action = 'prepare_contribution'"
            ).fetchone()[0] == task_count

        profile = load_private_profile(config.private_profile_path, kb_root=config.authoring_path)
        native = resolve_private_profile(
            profile, kb_root=config.authoring_path, needs=frozenset({"registry", "artifacts"})
        )
        unrelated_kb = config.operational_root / "worktrees" / unrelated["task_id"] / "kb"
        unrelated_review = preview_publication(
            unrelated_kb,
            unrelated["native_candidate"],
            config.published_path,
            activated["native_candidate"],
            source_registry=native.source_registry,
            artifact_store=native.artifact_store,
            retention_required=True,
        )
        assert unrelated_review.blocking_diagnostics == []
        assert publish_revision(
            unrelated_kb,
            unrelated["native_candidate"],
            config.published_path,
            activated["native_candidate"],
            unrelated_review.review_digest,
            source_registry=native.source_registry,
            artifact_store=native.artifact_store,
            retention_required=True,
        ).activated
        historical = _call_tool(
            reconnected,
            fixture.contributor_api,
            "get_task",
            {"task_id": activated["task_id"]},
            8,
        ).json()["result"]["structuredContent"]
        assert historical["status"] == "published"
        assert historical["publication"]["version"] == activated["native_candidate"]
        assert historical["citations"] == recovered["citations"]
        reader_status = _call_tool(
            reconnected, fixture.contributor_api, "workspace_status", {}, 9
        ).json()["result"]["structuredContent"]
        assert reader_status["published_version"] == unrelated["native_candidate"]
