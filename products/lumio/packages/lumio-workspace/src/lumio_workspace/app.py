"""Authenticated read-only Lumio workspace ASGI application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lumio_wiki.location import PublishedFilesystemLocation, open_knowledge_base
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .auth import AuthenticationError, EntraBrowserAuth, EntraTokenVerifier, IdentityConfig
from .state import Actor, WorkspaceState


class WorkspaceError(ToolError):
    pass


@dataclass(frozen=True)
class WorkspaceConfig:
    workspace_id: str
    external_url: str
    published_path: Path
    published_version: str | None
    state_path: Path
    identity: IdentityConfig

    @classmethod
    def from_env(cls) -> WorkspaceConfig:
        return cls(
            workspace_id=_required("LUMIO_WORKSPACE_ID"),
            external_url=_required("LUMIO_WORKSPACE_EXTERNAL_URL").rstrip("/"),
            published_path=Path(_required("LUMIO_WORKSPACE_PUBLISHED_PATH")),
            published_version=os.environ.get("LUMIO_WORKSPACE_PUBLISHED_VERSION") or None,
            state_path=Path(_required("LUMIO_WORKSPACE_STATE_PATH")),
            identity=IdentityConfig.from_env(),
        )

    def __post_init__(self) -> None:
        if not self.workspace_id or not self.external_url.startswith("https://"):
            raise ValueError("workspace ID and an HTTPS external URL are required")


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
    browser_auth = EntraBrowserAuth(config.identity)
    verifier = token_verifier or EntraTokenVerifier(config.identity)
    server = MCPServer(
        "lumio-workspace",
        instructions="Read admitted knowledge only after current workspace membership is verified.",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(config.identity.issuer),
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

    @server.custom_route("/auth/login", methods=["GET"], include_in_schema=False)
    async def login(request: Request) -> Response:
        return await browser_auth.login(request)

    @server.custom_route("/auth/callback", methods=["GET"], include_in_schema=False)
    async def callback(request: Request) -> Response:
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
    return SessionMiddleware(
        mcp_app,
        secret_key=config.identity.session_secret,
        session_cookie="lumio_workspace_session",
        max_age=3600,
        https_only=True,
        same_site="lax",
    )
