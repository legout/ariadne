from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import lumio_wiki.git_authoring as native_authoring
from lumio_wiki.location import PublishedFilesystemLocation, published_pointer_path
from lumio_wiki.private_profile import load_private_profile, resolve_private_profile
from lumio_workspace import WorkspaceState, create_app
from starlette.testclient import TestClient

_review = importlib.import_module(
    "products.lumio.packages.lumio-workspace.tests.test_workspace_review"
)
ORIGINAL = _review.ORIGINAL
_call_tool = _review._call_tool
_confirm_setup = _review._confirm_setup
_contribute = _review._contribute
_decision = _review._decision
_digest = _review._digest
_fixture = _review._fixture
_login = _review._login
_page = _review._page
_upload = _review._upload

EXPECTED_A_BODY = (
    "# Recovery Runbook\n\nStop the old worker.\n\n<unsafe>&review\n\n"
    "Version A: drain the queue before starting the replacement."
)
EXPECTED_B_BODY = (
    "# Recovery Runbook\n\nStop the old worker.\n\n<unsafe>&review\n\n"
    "Version B: verify the replacement before closing the runbook."
)
EXPECTED_PATH = "procedures/recovery_runbook.md"
RUNBOOK_SOURCE = "recovery-runbook-source"
EDITED_ORIGINAL = ORIGINAL + b"\r\nVersion B source bytes."

_CHILD = r"""
import json
import os
import sys
from pathlib import Path

from lumio_workspace import WorkspaceConfig, create_app
from starlette.testclient import TestClient

payload = json.loads(sys.argv[1])
config = WorkspaceConfig(
    workspace_id=payload["workspace_id"],
    external_url="https://workspace.test",
    published_path=Path(payload["published_path"]),
    published_version=None,
    state_path=Path(payload["state_path"]),
    identity=None,
    auth_mode="local-token",
    authoring_path=Path(payload["authoring_path"]),
    private_profile_path=Path(payload["private_profile_path"]),
    private_root=Path(payload["private_root"]),
    namespace=payload["namespace"],
)


def call(client, token, name, arguments, request_id):
    response = client.post(
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
    assert response.status_code == 200, response.text
    return response.json()["result"]


with TestClient(create_app(config), base_url="https://workspace.test") as client:
    denied = call(
        client,
        payload["reviewer_api"],
        "get_task",
        {"task_id": payload["task_a"]},
        1,
    )
    assert denied["isError"] is True, denied
    assert "publication" not in denied.get("structuredContent", {})

    first = call(
        client,
        payload["contributor_api"],
        "get_task",
        {"task_id": payload["task_a"]},
        2,
    )
    assert first["isError"] is False, first
    recovered_a = first["structuredContent"]
    repeated = call(
        client,
        payload["contributor_api"],
        "get_task",
        {"task_id": payload["task_a"]},
        3,
    )
    assert repeated["structuredContent"] == recovered_a

    prepared = call(
        client,
        payload["contributor_api"],
        "get_task",
        {"task_id": payload["task_prepared"]},
        4,
    )
    assert prepared["isError"] is False, prepared
    status = call(client, payload["contributor_api"], "workspace_status", {}, 5)
    current = call(
        client,
        payload["contributor_api"],
        "read_knowledge",
        {"title": "Recovery Runbook"},
        6,
    )

print(
    json.dumps(
        {
            "pid": os.getpid(),
            "recovered_a": recovered_a,
            "prepared": prepared["structuredContent"],
            "status": status["structuredContent"],
            "current": current["structuredContent"],
        }
    )
)
"""


def test_restart_reconciles_publication_without_replaying_stale_approval(
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
            retry_key="recovery-prepared",
            title="Prepared Recovery",
            addition="A prepared receipt is not permission to activate after restart.",
            source_id="recovery-prepared-source",
            filename="prepared-recovery.md",
            request_id=1,
        )
        _login(reviewer, fixture.reviewer_browser)
        prepared_digest = _digest(reviewer.get(f"/review/{prepared['task_id']}").text)

        original_atomic_write = native_authoring.atomic_write_bytes

        def interrupt_pointer(path, data):
            if Path(path) == published_pointer_path(config.published_path):
                raise OSError("injected interruption before pointer activation")
            return original_atomic_write(path, data)

        monkeypatch.setattr(native_authoring, "atomic_write_bytes", interrupt_pointer)
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

        task_a = _contribute(
            contributor,
            fixture,
            retry_key="recovery-version-a",
            title="Recovery Runbook",
            addition="Version A: drain the queue before starting the replacement.",
            source_id=RUNBOOK_SOURCE,
            filename="recovery-runbook.md",
            request_id=2,
        )
        version_a = task_a["native_candidate"]
        digest_a = _digest(reviewer.get(f"/review/{task_a['task_id']}").text)
        original_finish = WorkspaceState.finish_review_task

        def interrupt_bookkeeping(*args, **kwargs):
            raise RuntimeError("injected interruption after native activation")

        monkeypatch.setattr(WorkspaceState, "finish_review_task", interrupt_bookkeeping)
        interrupted = _decision(reviewer, task_a["task_id"], digest_a, "approve")
        assert interrupted.status_code == 409
        monkeypatch.setattr(WorkspaceState, "finish_review_task", original_finish)
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == version_a

        uploaded_b = _upload(
            contributor,
            fixture.contributor_api,
            EDITED_ORIGINAL,
            "recovery-version-b",
            RUNBOOK_SOURCE,
        )
        assert uploaded_b.status_code == 200, uploaded_b.text
        response_b = _call_tool(
            contributor,
            fixture.contributor_api,
            "prepare_contribution",
            {
                "retry_key": "recovery-version-b",
                "sources": [
                    {"upload_id": uploaded_b.json()["upload_id"], "intent": "update"}
                ],
                "pages": [
                    {
                        "filename": "recovery-runbook.md",
                        "markdown": _page(
                            "Recovery Runbook",
                            "Version B: verify the replacement before closing the runbook.",
                            RUNBOOK_SOURCE,
                        ),
                    }
                ],
                "continuation_task_id": task_a["task_id"],
            },
            3,
        )
        result_b = response_b.json()["result"]
        assert result_b["isError"] is False, result_b
        task_b = result_b["structuredContent"]
        version_b = task_b["native_candidate"]
        assert version_b != version_a and task_b["native_base"] == version_a
        digest_b = _digest(reviewer.get(f"/review/{task_b['task_id']}").text)
        approved_b = _decision(reviewer, task_b["task_id"], digest_b, "approve")
        assert approved_b.status_code == 200, approved_b.text
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == version_b

    child_payload = {
        "workspace_id": config.workspace_id,
        "published_path": str(config.published_path),
        "state_path": str(config.state_path),
        "authoring_path": str(config.authoring_path),
        "private_profile_path": str(config.private_profile_path),
        "private_root": str(config.operational_root),
        "namespace": config.namespace,
        "contributor_api": fixture.contributor_api,
        "reviewer_api": fixture.reviewer_api,
        "task_a": task_a["task_id"],
        "task_prepared": prepared["task_id"],
    }
    receipts_path = config.published_path / ".lumio-publication" / "receipts"
    receipts_before = {path.name: path.read_bytes() for path in receipts_path.glob("*.json")}
    versions_before = {path.name for path in (config.published_path / "versions").iterdir()}
    with fixture.state._connect() as connection:
        operations_before = connection.execute(
            "SELECT action, COUNT(*) FROM operations GROUP BY action"
        ).fetchall()

    restarted = subprocess.run(
        [sys.executable, "-c", _CHILD, json.dumps(child_payload)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert restarted.returncode == 0, (restarted.stdout, restarted.stderr)
    observed = json.loads(restarted.stdout)
    assert observed["pid"] != os.getpid()

    recovered_a = observed["recovered_a"]
    assert recovered_a["status"] == "published"
    assert recovered_a["published"] is True
    assert recovered_a["publication_outcome"] == "activated"
    assert recovered_a["publication"]["version"] == version_a
    assert recovered_a["publication"]["activated"] is True
    assert recovered_a["citations"] == [
        {"title": "Recovery Runbook", "path": EXPECTED_PATH, "published_version": version_a}
    ]
    historical_a = PublishedFilesystemLocation(config.published_path, version=version_a).resolve()
    assert historical_a.lookup_by_title("Recovery Runbook")[0].body.strip() == EXPECTED_A_BODY

    recovered_prepared = observed["prepared"]
    assert recovered_prepared["status"] == "pending_review"
    assert recovered_prepared["published"] is False
    assert recovered_prepared["publication_outcome"] == "indeterminate"
    assert recovered_prepared["publication"]["activated"] is False
    assert observed["status"]["published_version"] == version_b
    assert observed["current"]["markdown"].strip() == EXPECTED_B_BODY
    assert observed["current"]["citation"]["published_version"] == version_b
    assert PublishedFilesystemLocation(config.published_path).read_pointer() == version_b
    actual_receipt_a = json.loads((receipts_path / f"{version_a}.json").read_text(encoding="utf-8"))
    assert actual_receipt_a["version"] == version_a and actual_receipt_a["activated"] is True

    with TestClient(create_app(config), base_url="https://workspace.test") as reviewer:
        _login(reviewer, fixture.reviewer_browser)
        stale = _decision(reviewer, task_a["task_id"], digest_a, "approve")
        assert stale.status_code == 409
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == version_b

        expired_credential = fixture.reviewer_browser.split(".", 1)[0]
        with fixture.state._connect() as connection:
            connection.execute(
                "UPDATE local_credentials SET expires_at = ? WHERE credential_id = ?",
                (int(time.time()) - 1, expired_credential),
            )
        expired = _decision(reviewer, prepared["task_id"], prepared_digest, "approve")
        assert expired.status_code == 401
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == version_b

        revoked_credential, revoked_browser = fixture.state.issue_local_credential(
            "reviewer", "browser", expires_at=int(time.time()) + 3600
        )
        _login(reviewer, revoked_browser)
        fixture.state.revoke_local_credential(revoked_credential)
        revoked = _decision(reviewer, prepared["task_id"], prepared_digest, "approve")
        assert revoked.status_code == 401
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == version_b

    receipts_after = {path.name: path.read_bytes() for path in receipts_path.glob("*.json")}
    assert receipts_after == receipts_before
    assert {path.name for path in (config.published_path / "versions").iterdir()} == versions_before
    with fixture.state._connect() as connection:
        assert (
            connection.execute("SELECT action, COUNT(*) FROM operations GROUP BY action").fetchall()
            == operations_before
        )

    profile = load_private_profile(config.private_profile_path, kb_root=config.authoring_path)
    native = resolve_private_profile(
        profile, kb_root=config.authoring_path, needs=frozenset({"registry", "artifacts"})
    )
    assert native.source_registry is not None
    expected_digest = hashlib.sha256(ORIGINAL).hexdigest()
    versions = native.source_registry.get("recovery-prepared-source").versions
    assert len(versions) == 1 and versions[0].content_hash == expected_digest
    versions = native.source_registry.get(RUNBOOK_SOURCE).versions
    assert [version.content_hash for version in versions] == [
        expected_digest,
        hashlib.sha256(EDITED_ORIGINAL).hexdigest(),
    ]
