from __future__ import annotations

import subprocess
import time
from pathlib import Path

from authlib.jose import JsonWebKey, JsonWebToken, Key
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
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
from starlette.testclient import TestClient

TENANT = "tenant-fixture"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
AUDIENCE = "api://workspace-api-fixture"
PI_CLIENT = "pi-public-client-fixture"
PERSON = "person-object-123"
SENTINEL = "The blue orchard gate opens at dawn."


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _published_sentinel(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    kb = repo / "kb"
    kb.mkdir(parents=True)
    # Independent oracle: this hand-authored page and phrase are known before
    # the service runs; no expected value comes from service output.
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


def _signed_token(
    jwt: JsonWebToken,
    key: Key,
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    tenant: str = TENANT,
    client: str = PI_CLIENT,
    scope: str = "Knowledge.Read",
) -> str:
    now = int(time.time())
    return jwt.encode(
        {"alg": "RS256", "kid": "fixture-key"},
        {
            "iss": issuer,
            "aud": audience,
            "exp": now + 3600,
            "iat": now - 5,
            "nbf": now - 5,
            "tid": tenant,
            "oid": PERSON,
            "sub": PERSON,
            "azp": client,
            "scp": scope,
            "ver": "2.0",
        },
        key,
    ).decode()


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


def test_identity_and_membership_gate_published_reads(tmp_path: Path) -> None:
    destination, revision = _published_sentinel(tmp_path)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    signing_key = JsonWebKey.import_key(private_pem, {"kid": "fixture-key"})
    public_jwk = signing_key.as_dict(is_private=False, alg="RS256", use="sig")
    key_set = JsonWebKey.import_key_set({"keys": [public_jwk]})
    jwt = JsonWebToken(["RS256"])
    identity = IdentityConfig(
        tenant_id=TENANT,
        issuer=ISSUER,
        metadata_url=f"{ISSUER}/.well-known/openid-configuration",
        audience=AUDIENCE,
        pi_client_id=PI_CLIENT,
        browser_client_id="browser-client-fixture",
        browser_client_secret="synthetic-browser-secret",
        browser_redirect_uri="https://workspace.test/auth/callback",
        session_secret="synthetic-session-secret",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=revision,
        state_path=tmp_path / "state.sqlite3",
        identity=identity,
    )
    state = WorkspaceState(config.state_path)
    actor = Actor(tenant_id=TENANT, object_id=PERSON)
    state.grant(config.workspace_id, actor)
    app = create_app(config, token_verifier=EntraTokenVerifier(identity, key_set=key_set))
    token = _signed_token(jwt, signing_key)

    with TestClient(app, base_url="https://workspace.test") as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["authorization_servers"] == [ISSUER]
        assert metadata.json()["scopes_supported"] == ["Knowledge.Read"]

        unauthorized = _call_tool(
            client, "not-a-token", "read_knowledge", {"title": "Team Runbook"}, 1
        )
        assert unauthorized.status_code == 401
        assert SENTINEL not in unauthorized.text

        initialized = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "independent-fixture", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text

        read = _call_tool(client, token, "read_knowledge", {"title": "Team Runbook"}, 3)
        assert read.status_code == 200, read.text
        read_result = read.json()["result"]
        assert read_result["isError"] is False
        assert read_result["structuredContent"]["markdown"].strip() == SENTINEL
        assert read_result["structuredContent"]["citation"] == {
            "title": "Team Runbook",
            "path": "runbook.md",
            "published_version": revision,
        }

        search = _call_tool(
            client, token, "search_knowledge", {"query": "blue orchard", "limit": 5}, 4
        )
        assert search.status_code == 200, search.text
        assert search.json()["result"]["structuredContent"]["results"] == [
            {
                "title": "Team Runbook",
                "citation": {"title": "Team Runbook", "path": "runbook.md"},
                "passage": SENTINEL,
            }
        ]

        # An API bearer token never creates the separate browser session.
        browser = client.get(
            "/workspace", headers={"Authorization": f"Bearer {token}"}, follow_redirects=False
        )
        assert browser.status_code == 303
        assert browser.headers["location"] == "/auth/login"

        for request_id, bad_token in enumerate(
            (
                _signed_token(jwt, signing_key, tenant="other-tenant", issuer=f"{ISSUER}-other"),
                _signed_token(jwt, signing_key, audience="api://wrong-audience"),
                _signed_token(jwt, signing_key, client="unapproved-client"),
                _signed_token(
                    jwt,
                    signing_key,
                    audience="api://browser-client",
                    scope="openid profile",
                ),
            ),
            start=10,
        ):
            denied = _call_tool(
                client, bad_token, "read_knowledge", {"title": "Team Runbook"}, request_id
            )
            assert denied.status_code == 401
            assert SENTINEL not in denied.text
            assert "Team Runbook" not in denied.text

        state.revoke(config.workspace_id, actor)
        removed = _call_tool(client, token, "read_knowledge", {"title": "Team Runbook"}, 20)
        assert removed.status_code == 200, removed.text
        assert removed.json()["result"]["isError"] is True
        assert removed.json()["result"]["content"][0]["text"].endswith(
            ": workspace access is not available"
        )
        assert SENTINEL not in removed.text
        assert "Team Runbook" not in removed.text
