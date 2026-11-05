from __future__ import annotations

import subprocess
import time
from pathlib import Path

from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_workspace import WorkspaceConfig, WorkspaceState, create_app
from lumio_workspace.__main__ import main
from starlette.testclient import TestClient

SENTINEL = "The local credential boundary protects this synthetic page."


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _published_sentinel(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    kb = repo / "kb"
    kb.mkdir(parents=True)
    # Independent oracle: the expected admitted bytes are authored before the service runs.
    (kb / "runbook.md").write_text(
        "---\n"
        'title: "Team Runbook"\n'
        'tags:\n  - "operations"\n'
        'summary: "Synthetic operations runbook."\n'
        'lifecycle: "approved"\n'
        'visibility: "internal"\n'
        'sources:\n  - id: "synthetic-source"\n    title: "Synthetic fixture"\n'
        "---\n\n"
        f"{SENTINEL}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace="urn:uuid:6c6e21ec-98a4-4c0b-9153-c2eb5d3c2210",
            )
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


def _call_tool(client: TestClient, token: str, title: str = "Team Runbook"):
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_knowledge", "arguments": {"title": title}},
        },
    )


def _issue(capsys, user_id: str, purpose: str, expires_at: int) -> tuple[str, str]:
    assert main(
        [
            "local-token",
            "issue",
            "--user-id",
            user_id,
            "--purpose",
            purpose,
            "--expires-at",
            str(expires_at),
        ]
    ) == 0
    output = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    return output["credential_id"], output["token"]


def _login(client: TestClient, token: str, *, origin: str = "https://workspace.test"):
    return client.post(
        "/auth/login",
        headers={"Origin": origin},
        data={"token": token},
        follow_redirects=False,
    )


def _read_success(response) -> None:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["markdown"].strip() == SENTINEL


def _membership_refusal(response) -> None:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"].endswith(": workspace access is not available")
    assert SENTINEL not in response.text


def test_local_credential_and_browser_session_lifecycle(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    destination, revision = _published_sentinel(tmp_path)
    state_path = tmp_path / "state.sqlite3"
    monkeypatch.setenv("LUMIO_WORKSPACE_AUTH_MODE", "local-token")
    monkeypatch.setenv("LUMIO_WORKSPACE_ID", "workspace-fixture")
    monkeypatch.setenv("LUMIO_WORKSPACE_EXTERNAL_URL", "https://workspace.test")
    monkeypatch.setenv("LUMIO_WORKSPACE_PUBLISHED_PATH", str(destination))
    monkeypatch.setenv("LUMIO_WORKSPACE_PUBLISHED_VERSION", revision)
    monkeypatch.setenv("LUMIO_WORKSPACE_STATE_PATH", str(state_path))
    for name in (
        "LUMIO_WORKSPACE_TENANT_ID",
        "LUMIO_WORKSPACE_API_AUDIENCE",
        "LUMIO_WORKSPACE_PI_CLIENT_ID",
        "LUMIO_WORKSPACE_BROWSER_CLIENT_ID",
        "LUMIO_WORKSPACE_BROWSER_CLIENT_SECRET",
        "LUMIO_WORKSPACE_BROWSER_REDIRECT_URI",
    ):
        monkeypatch.delenv(name, raising=False)

    # Local mode must construct without any Entra settings.
    config = WorkspaceConfig.from_env()
    state = WorkspaceState(state_path)
    for user_id in ("alice", "bob"):
        assert main(["local-user", "create", "--user-id", user_id]) == 0
    assert main(["local-membership", "grant", "--user-id", "alice"]) == 0

    clock = {"now": int(time.time())}
    monkeypatch.setattr("lumio_workspace.state.time.time", lambda: clock["now"])
    alice_api_id, alice_api = _issue(capsys, "alice", "api", clock["now"] + 3600)
    alice_browser_id, alice_browser = _issue(
        capsys, "alice", "browser", clock["now"] + 3600
    )
    _, bob_api = _issue(capsys, "bob", "api", clock["now"] + 3600)
    with state._connect() as connection:
        stored_hash = connection.execute(
            "SELECT token_hash FROM local_credentials WHERE credential_id = ?",
            (alice_api_id,),
        ).fetchone()[0]
    assert len(stored_hash) == 64
    assert alice_api not in stored_hash

    app = create_app(config)
    with TestClient(app, base_url="https://workspace.test") as client:
        _read_success(_call_tool(client, alice_api))

        # Bob's valid credential does not supply the independently required membership.
        _membership_refusal(_call_tool(client, bob_api))
        assert _call_tool(client, alice_browser).status_code == 401
        assert _call_tool(client, "unknown-credential").status_code == 401

        # API credentials never enter the browser session exchange.
        assert _login(client, alice_api).status_code == 401
        assert _login(client, alice_browser, origin="https://attacker.invalid").status_code == 403
        signed_in = _login(client, alice_browser)
        assert signed_in.status_code == 303
        cookie = client.cookies.get("lumio_workspace_session")
        assert cookie and alice_browser not in cookie
        assert state.load_browser_session(cookie) == {
            "actor": {"tenant_id": "local", "object_id": "alice"},
            "local_credential_id": alice_browser_id,
        }
        assert client.get("/workspace").status_code == 200

        # Revoking one purpose leaves the other purpose independent.
        assert main(["local-token", "revoke", "--credential-id", alice_api_id]) == 0
        assert _call_tool(client, alice_api).status_code == 401
        assert client.get("/workspace").status_code == 200
        _, alice_api_two = _issue(capsys, "alice", "api", clock["now"] + 3600)
        _read_success(_call_tool(client, alice_api_two))
        assert main(["local-token", "revoke", "--credential-id", alice_browser_id]) == 0
        assert client.get("/workspace", follow_redirects=False).status_code == 303
        _read_success(_call_tool(client, alice_api_two))

        # Advance an independent clock beyond both source credentials, not the cookie lifetime.
        _, expiring_api = _issue(capsys, "alice", "api", clock["now"] + 10)
        _, expiring_browser = _issue(capsys, "alice", "browser", clock["now"] + 10)
        assert _login(client, expiring_browser).status_code == 303
        assert client.get("/workspace").status_code == 200
        clock["now"] += 11
        assert _call_tool(client, expiring_api).status_code == 401
        assert client.get("/workspace", follow_redirects=False).status_code == 303
        _read_success(_call_tool(client, alice_api_two))

        # Disable blocks existing sessions and API credentials without deleting their records.
        _, long_browser = _issue(capsys, "alice", "browser", clock["now"] + 3600)
        assert _login(client, long_browser).status_code == 303
        assert client.get("/workspace").status_code == 200
        assert main(["local-user", "disable", "--user-id", "alice"]) == 0
        assert _call_tool(client, alice_api_two).status_code == 401
        assert client.get("/workspace", follow_redirects=False).status_code == 303

        # Membership removal is independent of still-valid credentials on both routes.
        assert main(["local-membership", "grant", "--user-id", "bob"]) == 0
        _read_success(_call_tool(client, bob_api))
        _, bob_browser = _issue(capsys, "bob", "browser", clock["now"] + 3600)
        assert _login(client, bob_browser).status_code == 303
        assert client.get("/workspace").status_code == 200
        assert main(["local-membership", "revoke", "--user-id", "bob"]) == 0
        _membership_refusal(_call_tool(client, bob_api))
        denied = client.get("/workspace")
        assert denied.status_code == 403
        assert denied.json() == {"error": "workspace access is not available"}
