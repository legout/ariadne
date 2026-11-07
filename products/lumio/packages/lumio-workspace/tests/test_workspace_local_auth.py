from __future__ import annotations

import asyncio
import base64
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from authlib.jose import JsonWebKey
from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_workspace import (
    Actor,
    EntraTokenVerifier,
    IdentityConfig,
    WorkspaceConfig,
    WorkspaceState,
    create_app,
)
from lumio_workspace.__main__ import main
from lumio_workspace.auth import EntraBrowserAuth
from starlette.responses import RedirectResponse
from starlette.testclient import TestClient

SENTINEL = "The local credential boundary protects this synthetic page."


def _entra_identity() -> IdentityConfig:
    tenant = "tenant-fixture"
    issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
    return IdentityConfig(
        tenant_id=tenant,
        issuer=issuer,
        metadata_url=f"{issuer}/.well-known/openid-configuration",
        audience="0f2d6a2f-8f3b-4f5e-9d6c-123456789abc",
        pi_client_id="pi-public-client-fixture",
        browser_client_id="browser-client-fixture",
        browser_client_secret="synthetic-browser-secret",
        browser_redirect_uri="https://workspace.test/auth/callback",
    )


def _browser_outcome(response) -> str:
    if response.status_code == 200:
        return "allowed"
    if response.status_code in {401, 403}:
        return "refused"
    if response.status_code in {302, 303} and response.headers.get("location") == "/auth/login":
        return "refused"
    return f"unexpected:{response.status_code}"


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
    assert (
        main(
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
        )
        == 0
    )
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


@pytest.mark.parametrize("use_sys_argv", [False, True], ids=["explicit", "sys-argv"])
def test_revoke_legacy_leading_minus_credential_id(
    tmp_path: Path, monkeypatch, use_sys_argv: bool
) -> None:
    now = 1_800_000_000
    state_path = tmp_path / "state.sqlite3"
    monkeypatch.setenv("LUMIO_WORKSPACE_ID", "workspace-fixture")
    monkeypatch.setenv("LUMIO_WORKSPACE_STATE_PATH", str(state_path))
    monkeypatch.setattr("lumio_workspace.state.time.time", lambda: now)
    monkeypatch.setattr(
        "lumio_workspace.state.secrets.token_bytes", lambda size: b"\xfb" + bytes(size - 1)
    )
    state = WorkspaceState(state_path)
    state.create_local_user("alice")
    credential_id, token = state.issue_local_credential("alice", "browser", expires_at=now + 3600)
    expected_id = base64.urlsafe_b64encode(b"\xfb" + bytes(11)).rstrip(b"=").decode("ascii")
    assert expected_id.startswith("-")
    assert credential_id == expected_id
    assert state.authenticate_local_credential(token, purpose="browser") is not None

    arguments = ["local-token", "revoke", "--credential-id", credential_id]
    if use_sys_argv:
        monkeypatch.setattr(sys, "argv", ["lumio-workspace", *arguments])
        assert main(None) == 0
    else:
        assert main(arguments) == 0
    assert arguments == ["local-token", "revoke", "--credential-id", credential_id]

    with state._connect() as connection:
        revoked_at = connection.execute(
            "SELECT revoked_at FROM local_credentials WHERE credential_id = ?",
            (credential_id,),
        ).fetchone()[0]
    assert revoked_at == now
    assert state.authenticate_local_credential(token, purpose="browser") is None


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
    alice_browser_id, alice_browser = _issue(capsys, "alice", "browser", clock["now"] + 3600)
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


def test_delayed_local_login_cannot_replace_newer_browser_session(
    tmp_path: Path, monkeypatch
) -> None:
    clock = {"now": int(time.time())}
    monkeypatch.setattr("lumio_workspace.state.time.time", lambda: clock["now"])
    monkeypatch.setattr("lumio_workspace.app.time.time", lambda: clock["now"])
    config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=tmp_path,
        published_version=None,
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
    )
    state = WorkspaceState(config.state_path)
    credentials = {}
    for user_id in ("alice", "bob", "carol"):
        state.create_local_user(user_id)
        credentials[user_id] = state.issue_local_credential(
            user_id, "browser", expires_at=clock["now"] + 7200
        )
    state.grant(config.workspace_id, Actor(tenant_id="local", object_id="bob"))

    arrival_started = asyncio.Event()
    finish_arrival = asyncio.Event()
    delay_arrival = False
    app = create_app(config)

    async def gated_app(scope, receive, send):
        nonlocal delay_arrival
        if (
            delay_arrival
            and scope["type"] == "http"
            and scope["path"] == "/auth/login"
            and scope["method"] == "POST"
        ):
            delay_arrival = False
            arrival_started.set()
            await finish_arrival.wait()
        await app(scope, receive, send)

    async def scenario() -> None:
        nonlocal delay_arrival
        transport = httpx.ASGITransport(app=gated_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://workspace.test"
        ) as browser:

            async def login(user_id: str):
                return await browser.post(
                    "/auth/login",
                    headers={"Origin": "https://workspace.test"},
                    data={"token": credentials[user_id][1]},
                    follow_redirects=False,
                )

            # A real clean-browser login establishes cookie A before either racing POST.
            assert (await login("alice")).status_code == 303
            old_cookie = browser.cookies.get("lumio_workspace_session")
            assert old_cookie

            # Hold Carol's older valid POST before middleware, while the same jar carries A.
            delay_arrival = True
            older_request = asyncio.create_task(login("carol"))
            await arrival_started.wait()
            # Bob rotates A while it is still valid, giving B a fresh cookie lifetime.
            clock["now"] += 3598
            newer_response = await login("bob")
            new_cookie = newer_response.cookies.get("lumio_workspace_session")
            assert newer_response.status_code == 303
            assert new_cookie and new_cookie != old_cookie
            assert browser.cookies.get("lumio_workspace_session") == new_cookie

            # Release Carol's older POST only after A expires; B remains valid.
            clock["now"] += 3
            finish_arrival.set()
            older_response = await older_request

            assert older_response.status_code == 303
            assert older_response.cookies.get("lumio_workspace_session") is None
            assert browser.cookies.get("lumio_workspace_session") == new_cookie
            assert state.load_browser_session(old_cookie) is None
            assert state.load_browser_session(new_cookie) == {
                "actor": {"tenant_id": "local", "object_id": "bob"},
                "local_credential_id": credentials["bob"][0],
            }
            # Only Bob has membership, so this independently proves the browser actor.
            assert (await browser.get("/workspace")).status_code == 200

            # Ordinary expiry is not rotation: an expired unrotated cookie permits login.
            expired_unrotated = "expired-unrotated-browser-session"
            state.save_browser_session(
                expired_unrotated,
                {
                    "actor": {"tenant_id": "local", "object_id": "alice"},
                    "local_credential_id": credentials["alice"][0],
                },
                expires_at=clock["now"] - 1,
            )
            browser.cookies.set(
                "lumio_workspace_session", expired_unrotated, domain="workspace.test"
            )
            recovered_response = await login("alice")
            recovered_cookie = browser.cookies.get("lumio_workspace_session")
            assert recovered_response.status_code == 303
            assert recovered_cookie and recovered_cookie not in {new_cookie, expired_unrotated}
            assert state.load_browser_session(expired_unrotated) is None
            assert state.load_browser_session(recovered_cookie) == {
                "actor": {"tenant_id": "local", "object_id": "alice"},
                "local_credential_id": credentials["alice"][0],
            }

    asyncio.run(scenario())


def test_browser_sessions_follow_selected_authentication_mode(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.sqlite3"
    local_config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=tmp_path,
        published_version=None,
        state_path=state_path,
        identity=None,
        auth_mode="local-token",
    )
    entra_identity = _entra_identity()
    entra_config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=tmp_path,
        published_version=None,
        state_path=state_path,
        identity=entra_identity,
        auth_mode="entra",
    )
    state = WorkspaceState(state_path)
    local_actor = Actor(tenant_id="local", object_id="alice")
    entra_actor = Actor(tenant_id="tenant-fixture", object_id="person-object-123")
    state.create_local_user(local_actor.object_id)
    state.grant(local_config.workspace_id, local_actor)
    state.grant(local_config.workspace_id, entra_actor)
    _, local_browser = state.issue_local_credential(
        local_actor.object_id, "browser", expires_at=int(time.time()) + 3600
    )

    # Existing synthetic Entra fixture boundary; no tenant or network call is made.
    async def entra_login(_self, request):
        request.session["_state_entra"] = {
            "state": "oauth-state-fixture",
            "code_verifier": "pkce-verifier-fixture",
        }
        return RedirectResponse("https://login.microsoftonline.com/authorize", status_code=303)

    async def entra_callback(_self, _request):
        return entra_actor

    monkeypatch.setattr(EntraBrowserAuth, "login", entra_login)
    monkeypatch.setattr(EntraBrowserAuth, "authenticate_callback", entra_callback)
    local_app = create_app(local_config)
    entra_app = create_app(
        entra_config,
        token_verifier=EntraTokenVerifier(
            entra_identity, key_set=JsonWebKey.import_key_set({"keys": []})
        ),
    )
    active_app = local_app

    async def switching_app(scope, receive, send):
        await active_app(scope, receive, send)

    async def scenario() -> None:
        nonlocal active_app
        transport = httpx.ASGITransport(app=switching_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://workspace.test"
        ) as browser:
            local_login = await browser.post(
                "/auth/login",
                headers={"Origin": "https://workspace.test"},
                data={"token": local_browser},
                follow_redirects=False,
            )
            assert local_login.status_code == 303
            local_cookie = browser.cookies.get("lumio_workspace_session")
            assert local_cookie
            assert (await browser.get("/workspace")).status_code == 200

            active_app = entra_app
            local_under_entra = await browser.get("/workspace", follow_redirects=False)
            local_cookie_after_refusal = browser.cookies.get("lumio_workspace_session")
            local_session_after_refusal = state.load_browser_session(local_cookie) is not None
            assert (await browser.get("/auth/login", follow_redirects=False)).status_code == 303
            entra_callback_response = await browser.get("/auth/callback", follow_redirects=False)
            assert entra_callback_response.status_code == 303
            entra_cookie = browser.cookies.get("lumio_workspace_session")
            assert entra_cookie and entra_cookie != local_cookie
            assert (await browser.get("/workspace")).status_code == 200

            active_app = local_app
            entra_under_local = await browser.get("/workspace", follow_redirects=False)
            entra_cookie_after_refusal = browser.cookies.get("lumio_workspace_session")
            entra_session_after_refusal = state.load_browser_session(entra_cookie) is not None
            fresh_local = await browser.post(
                "/auth/login",
                headers={"Origin": "https://workspace.test"},
                data={"token": local_browser},
                follow_redirects=False,
            )
            assert fresh_local.status_code == 303
            assert browser.cookies.get("lumio_workspace_session") != entra_cookie
            assert (await browser.get("/workspace")).status_code == 200

            assert {
                "local_under_entra": _browser_outcome(local_under_entra),
                "entra_under_local": _browser_outcome(entra_under_local),
                "local_cookie_unchanged": local_cookie_after_refusal == local_cookie,
                "entra_cookie_unchanged": entra_cookie_after_refusal == entra_cookie,
                "local_session_preserved": local_session_after_refusal,
                "entra_session_preserved": entra_session_after_refusal,
                "local_membership": state.capabilities(local_config.workspace_id, local_actor),
                "entra_membership": state.capabilities(local_config.workspace_id, entra_actor),
            } == {
                "local_under_entra": "refused",
                "entra_under_local": "refused",
                "local_cookie_unchanged": True,
                "entra_cookie_unchanged": True,
                "local_session_preserved": True,
                "entra_session_preserved": True,
                "local_membership": ("read",),
                "entra_membership": ("read",),
            }

    asyncio.run(scenario())
