"""Authenticated read-only Lumio workspace ASGI application."""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from lumio_wiki.location import PublishedFilesystemLocation, open_knowledge_base
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .auth import (
    AuthenticationError,
    EntraBrowserAuth,
    EntraTokenVerifier,
    IdentityConfig,
    LocalTokenVerifier,
)
from .state import Actor, WorkspaceState


class WorkspaceError(ToolError):
    pass


class _BrowserSession(dict):
    cleared = False

    def clear(self) -> None:
        super().clear()
        self.cleared = True


class BrowserSessionMiddleware:
    def __init__(self, app: Any, state: WorkspaceState, *, max_age: int = 3600) -> None:
        self.app = app
        self.state = state
        self.max_age = max_age

    def _cookie(self, value: str, max_age: int) -> str:
        return (
            f"lumio_workspace_session={value}; Path=/; Max-Age={max_age}; "
            "HttpOnly; Secure; SameSite=lax"
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cookies = SimpleCookie()
        try:
            cookies.load(Headers(scope=scope).get("cookie", ""))
        except CookieError:
            pass
        morsel = cookies.get("lumio_workspace_session")
        supplied_id = morsel.value if morsel else None
        data = self.state.load_browser_session(supplied_id) if supplied_id else None
        session_id = supplied_id if data is not None else None
        session = _BrowserSession(data or {})
        scope["session"] = session

        async def send_with_session(message) -> None:
            nonlocal session_id
            if message["type"] == "http.response.start":
                if not session:
                    if session_id:
                        self.state.delete_browser_session(session_id)
                    session_id = None
                else:
                    expires_at = int(time.time()) + self.max_age
                    if session.cleared and session_id:
                        new_session_id = secrets.token_urlsafe(32)
                        session_id = (
                            new_session_id
                            if self.state.rotate_browser_session(
                                session_id, new_session_id, dict(session), expires_at=expires_at
                            )
                            else None
                        )
                    elif session.cleared:
                        session_id = secrets.token_urlsafe(32)
                        self.state.save_browser_session(
                            session_id, dict(session), expires_at=expires_at
                        )
                    elif session_id:
                        if not self.state.update_browser_session(
                            session_id, dict(session), expires_at=expires_at
                        ):
                            session_id = None
                    else:
                        session_id = secrets.token_urlsafe(32)
                        self.state.save_browser_session(
                            session_id, dict(session), expires_at=expires_at
                        )
                headers = MutableHeaders(scope=message)
                # Passive responses never delete cookies: a late response
                # cannot know the browser's current credential.
                if session_id:
                    headers.append("set-cookie", self._cookie(session_id, self.max_age))
            await send(message)

        await self.app(scope, receive, send_with_session)


@dataclass(frozen=True)
class WorkspaceConfig:
    workspace_id: str
    external_url: str
    published_path: Path
    published_version: str | None
    state_path: Path
    identity: IdentityConfig | None
    auth_mode: str = "entra"

    @classmethod
    def from_env(cls) -> WorkspaceConfig:
        auth_mode = _required("LUMIO_WORKSPACE_AUTH_MODE")
        return cls(
            workspace_id=_required("LUMIO_WORKSPACE_ID"),
            external_url=_required("LUMIO_WORKSPACE_EXTERNAL_URL").rstrip("/"),
            published_path=Path(_required("LUMIO_WORKSPACE_PUBLISHED_PATH")),
            published_version=os.environ.get("LUMIO_WORKSPACE_PUBLISHED_VERSION") or None,
            state_path=Path(_required("LUMIO_WORKSPACE_STATE_PATH")),
            identity=IdentityConfig.from_env() if auth_mode == "entra" else None,
            auth_mode=auth_mode,
        )

    def __post_init__(self) -> None:
        if not self.workspace_id or not self.external_url.startswith("https://"):
            raise ValueError("workspace ID and an HTTPS external URL are required")
        if self.auth_mode not in {"local-token", "entra"}:
            raise ValueError("authentication mode must be local-token or entra")
        if self.auth_mode == "entra" and self.identity is None:
            raise ValueError("Entra mode requires identity configuration")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"missing required configuration: {name}")
    return value


def _actor() -> Actor:
    token = get_access_token()
    claims = token.claims if token else None
    if not claims or not claims.get("tid") or not claims.get("oid"):
        raise WorkspaceError("workspace access is not available")
    return Actor(tenant_id=claims["tid"], object_id=claims["oid"])


def create_app(config: WorkspaceConfig, *, token_verifier: TokenVerifier | None = None) -> Any:
    state = WorkspaceState(config.state_path)
    location = PublishedFilesystemLocation(config.published_path, version=config.published_version)
    browser_auth = None
    if config.auth_mode == "entra":
        assert config.identity is not None
        browser_auth = EntraBrowserAuth(config.identity)
        default_verifier: TokenVerifier = EntraTokenVerifier(config.identity)
        issuer = config.identity.issuer
    else:
        default_verifier = LocalTokenVerifier(state)
        issuer = config.external_url
    verifier = token_verifier or default_verifier
    server = MCPServer(
        "lumio-workspace",
        instructions="Read admitted knowledge only after current workspace membership is verified.",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(f"{config.external_url}/mcp"),
            required_scopes=["Knowledge.Read"],
            validate_token_resource=False,
        ),
    )

    def snapshot() -> Any:
        actor = _actor()
        if not state.permits(config.workspace_id, actor):
            raise WorkspaceError("workspace access is not available")
        resolved = open_knowledge_base(location)
        if not resolved.validation_report.is_valid:
            raise WorkspaceError("published knowledge is unavailable")
        return actor, resolved

    @server.tool()
    def workspace_status() -> dict[str, Any]:
        """Return ready state and current capabilities, without configuration secrets."""
        actor, resolved = snapshot()
        return {
            "workspace": config.workspace_id,
            "ready": True,
            "capabilities": list(state.capabilities(config.workspace_id, actor)),
            "published_version": resolved.published_version,
        }

    @server.tool()
    def read_knowledge(title: str) -> dict[str, Any]:
        """Read one admitted Compiled Page by Canonical Page Title or alias."""
        _, resolved = snapshot()
        pages = resolved.lookup_by_title(title) or resolved.lookup_by_alias(title)
        if not pages:
            return {"found": False}
        page = pages[0]
        return {
            "found": True,
            "title": page.title,
            "summary": page.summary,
            "markdown": page.body,
            "citation": {
                "title": page.title,
                "path": page.path,
                "published_version": resolved.published_version,
            },
        }

    @server.tool()
    def search_knowledge(query: str, limit: int = 20) -> dict[str, Any]:
        """Search admitted pages and return bounded citation-ready passages."""
        if not 1 <= limit <= 20:
            raise WorkspaceError("limit must be between 1 and 20")
        _, resolved = snapshot()
        return {
            "published_version": resolved.published_version,
            "results": [
                {
                    "title": result.page.title,
                    "citation": {"title": result.page.title, "path": result.page.path},
                    "passage": result.snippet,
                }
                for result in resolved.search_pages(query, limit=limit)
            ],
        }

    @server.custom_route("/auth/login", methods=["GET", "POST"], include_in_schema=False)
    async def login(request: Request) -> Response:
        if config.auth_mode == "entra":
            if request.method != "GET":
                return Response(status_code=405)
            assert browser_auth is not None
            return await browser_auth.login(request)
        if request.method == "GET":
            return HTMLResponse(
                "<!doctype html><title>Workspace sign in</title>"
                '<form method="post" action="/auth/login">'
                '<label>Browser sign-in token <input name="token" type="password" '
                'required autocomplete="off"></label>'
                '<button type="submit">Sign in</button></form>'
            )
        if request.url.scheme != "https" or request.headers.get("origin") != config.external_url:
            return JSONResponse({"error": "same-origin HTTPS POST required"}, status_code=403)
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            return JSONResponse({"error": "form POST required"}, status_code=415)
        try:
            body = await request.body()
            if len(body) > 4096:
                raise ValueError("login form too large")
            fields = parse_qs(
                body.decode(),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=4,
            )
        except (UnicodeDecodeError, ValueError):
            return JSONResponse({"error": "invalid login form"}, status_code=400)
        tokens = fields.get("token", [])
        if len(fields) != 1 or len(tokens) != 1:
            return JSONResponse({"error": "browser sign-in failed"}, status_code=401)
        credential = state.authenticate_local_credential(tokens[0], purpose="browser")
        if credential is None:
            return JSONResponse({"error": "browser sign-in failed"}, status_code=401)
        request.session.clear()
        request.session["actor"] = {
            "tenant_id": credential.actor.tenant_id,
            "object_id": credential.actor.object_id,
        }
        request.session["local_credential_id"] = credential.credential_id
        return RedirectResponse("/workspace", status_code=303)

    @server.custom_route("/auth/callback", methods=["GET"], include_in_schema=False)
    async def callback(request: Request) -> Response:
        if config.auth_mode != "entra":
            return Response(status_code=404)
        assert browser_auth is not None
        try:
            actor = await browser_auth.authenticate_callback(request)
        except AuthenticationError:
            return JSONResponse({"error": "browser sign-in failed"}, status_code=401)
        request.session.clear()
        request.session["actor"] = {"tenant_id": actor.tenant_id, "object_id": actor.object_id}
        return RedirectResponse("/workspace", status_code=303)

    @server.custom_route("/workspace", methods=["GET"], include_in_schema=False)
    async def browser_status(request: Request) -> Response:
        raw = request.session.get("actor")
        if not isinstance(raw, dict):
            return RedirectResponse("/auth/login", status_code=303)
        actor = Actor(
            tenant_id=str(raw.get("tenant_id", "")),
            object_id=str(raw.get("object_id", "")),
        )
        capabilities = state.capabilities(config.workspace_id, actor)
        if "read" not in capabilities:
            return JSONResponse({"error": "workspace access is not available"}, status_code=403)
        return JSONResponse(
            {"workspace": config.workspace_id, "ready": True, "capabilities": list(capabilities)}
        )

    external = urlsplit(config.external_url)
    mcp_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[external.netloc],
            allowed_origins=[config.external_url],
        ),
    )
    return BrowserSessionMiddleware(mcp_app, state)
