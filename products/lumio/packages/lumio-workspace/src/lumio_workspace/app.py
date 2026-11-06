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

from lumio_wiki.location import (  # pyright: ignore[reportMissingImports]
    PublishedFilesystemLocation,
    open_knowledge_base,
)
from mcp.server.auth.middleware.auth_context import (  # pyright: ignore
    get_access_token,
)
from mcp.server.auth.provider import TokenVerifier  # pyright: ignore[reportMissingImports]
from mcp.server.auth.settings import AuthSettings  # pyright: ignore[reportMissingImports]
from mcp.server.mcpserver import MCPServer  # pyright: ignore[reportMissingImports]
from mcp.server.mcpserver.exceptions import ToolError  # pyright: ignore[reportMissingImports]
from mcp.server.transport_security import (  # pyright: ignore
    TransportSecuritySettings,
)
from pydantic import AnyHttpUrl  # pyright: ignore[reportMissingImports]
from starlette.datastructures import (  # pyright: ignore[reportMissingImports]
    Headers,
    MutableHeaders,
)
from starlette.requests import Request  # pyright: ignore[reportMissingImports]
from starlette.responses import (  # pyright: ignore[reportMissingImports]
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from .auth import (
    AuthenticationError,
    EntraBrowserAuth,
    EntraTokenVerifier,
    IdentityConfig,
    LocalTokenVerifier,
)
from .contributions import ContributionError, ContributionService
from .enrichment import EnrichmentService
from .intake import IntakeService, UploadError
from .review import ReviewError, ReviewService, render_review, render_source
from .setup import SetupError, apply_setup, preview_setup, render_setup
from .state import Actor, RetryConflict, WorkspaceState


class WorkspaceError(ToolError):
    pass


class _BrowserSession(dict):
    cleared = False

    def clear(self) -> None:
        super().clear()
        self.cleared = True


class BrowserSessionMiddleware:
    def __init__(
        self, app: Any, state: WorkspaceState, *, auth_mode: str, max_age: int = 3600
    ) -> None:
        self.app = app
        self.state = state
        self.auth_mode = auth_mode
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
        if data is not None and ("local_credential_id" in data) != (
            self.auth_mode == "local-token"
        ):
            data = None
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
                        if supplied_id and self.state.browser_session_was_rotated(supplied_id):
                            session_id = None
                        else:
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
    authoring_path: Path | None = None
    private_profile_path: Path | None = None
    private_root: Path | None = None
    namespace: str | None = None
    analytics_project_id: str | None = None
    analytics_project_path: Path | None = None
    analytics_source_bindings_path: Path | None = None

    @property
    def operational_root(self) -> Path:
        return self.private_root or self.state_path.parent / "private"

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
            authoring_path=_optional_path("LUMIO_WORKSPACE_AUTHORING_PATH"),
            private_profile_path=_optional_path("LUMIO_WORKSPACE_PRIVATE_PROFILE"),
            private_root=_optional_path("LUMIO_WORKSPACE_PRIVATE_ROOT"),
            namespace=os.environ.get("LUMIO_WORKSPACE_NAMESPACE") or None,
            analytics_project_id=os.environ.get("LUMIO_WORKSPACE_ANALYTICS_PROJECT_ID") or None,
            analytics_project_path=_optional_path("LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH"),
            analytics_source_bindings_path=_optional_path(
                "LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS"
            ),
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


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _actor() -> Actor:
    token = get_access_token()
    claims = token.claims if token else None
    if not claims or not claims.get("tid") or not claims.get("oid"):
        raise WorkspaceError("workspace access is not available")
    return Actor(tenant_id=claims["tid"], object_id=claims["oid"])


def _browser_actor(request: Request) -> Actor | None:
    raw = request.session.get("actor")
    if not isinstance(raw, dict):
        return None
    return Actor(
        tenant_id=str(raw.get("tenant_id", "")),
        object_id=str(raw.get("object_id", "")),
    )


def create_app(config: WorkspaceConfig, *, token_verifier: TokenVerifier | None = None) -> Any:
    state = WorkspaceState(config.state_path)
    intake = IntakeService(state, config.operational_root)
    setup_previews: dict[str, tuple[Actor, Any]] = {}
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
        instructions=(
            "Read admitted knowledge and prepare pending contributions only after current "
            "workspace permission is verified."
        ),
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

    def analytics_service(*, required: bool = True) -> Any:
        selected = (
            config.analytics_project_id,
            config.analytics_project_path,
            config.analytics_source_bindings_path,
        )
        if not any(selected):
            if required:
                raise WorkspaceError(
                    "analytics is not enabled; the owner must configure the exact project "
                    "and operator source bindings"
                )
            return None
        if (
            not all(selected)
            or config.authoring_path is None
            or config.private_profile_path is None
        ):
            raise WorkspaceError(
                "analytics configuration is incomplete; the owner must set the project handle, "
                "project path, source bindings, authoring path, and private profile"
            )
        try:
            from .analytics import AnalyticsService
        except ImportError as exc:
            raise WorkspaceError(
                "analytics Core is unavailable or incompatible; install the same-candidate "
                "analytics producer rather than using the base service as a query fallback"
            ) from exc
        return AnalyticsService(config, state, intake)

    def contribution_service() -> ContributionService:
        if config.authoring_path is None or config.private_profile_path is None:
            raise WorkspaceError("workspace contribution is not configured")
        return ContributionService(
            state,
            intake,
            workspace_id=config.workspace_id,
            external_url=config.external_url,
            authoring_path=config.authoring_path,
            profile_path=config.private_profile_path,
            destination=config.published_path,
        )

    def enrichment_service() -> EnrichmentService:
        return EnrichmentService(
            contribution_service(), destination=config.published_path
        )

    def review_service() -> ReviewService:
        if config.authoring_path is None or config.private_profile_path is None:
            raise WorkspaceError("workspace review is not configured")
        return ReviewService(
            state,
            workspace_id=config.workspace_id,
            authoring_path=config.authoring_path,
            profile_path=config.private_profile_path,
            private_root=config.operational_root,
            destination=config.published_path,
            analytics=analytics_service(required=False),
        )

    @server.tool()
    def read_source_material(upload_id: str) -> dict[str, Any]:
        """Return permitted normalized text and conversion facts for one exact upload."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor, "contribute"):
            raise WorkspaceError("workspace contribution is not available")
        try:
            material, _facts = intake.extract(config.workspace_id, actor, upload_id)
        except UploadError as exc:
            raise WorkspaceError(str(exc)) from exc
        return material

    @server.tool()
    def prepare_data_source(
        retry_key: str,
        project: str,
        source: str,
        table: str,
        business_questions: list[str],
        upload_id: str | None = None,
        sheets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Stage an operator-bound or privately uploaded source without opening data."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor, "contribute"):
            raise WorkspaceError("workspace contribution is not available")
        try:
            return analytics_service().prepare_data_source(
                actor,
                retry_key=retry_key,
                project=project,
                source=source,
                table=table,
                business_questions=business_questions,
                upload_id=upload_id,
                sheets=sheets,
            )
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc

    @server.tool()
    def profile_data_source(task_id: str) -> dict[str, Any]:
        """Profile only a currently source-approved and caller-authorized exact source set."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor):
            raise WorkspaceError("workspace access is not available")
        try:
            return analytics_service().profile_data_source(actor, task_id)
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc

    @server.tool()
    def query_data(
        project: str,
        source_task_id: str,
        operation: str,
        request: dict,
    ) -> dict[str, Any]:
        """Query a pinned native release after checking the caller's complete source-set grant."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor):
            raise WorkspaceError("workspace access is not available")
        try:
            return analytics_service().query_data(
                actor, project, source_task_id, operation, request
            )
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc

    @server.tool()
    def prepare_enrichment(
        workspace_id: str,
        page_ids: list[str],
        expected_version: str,
        request_key: str,
    ) -> dict[str, Any]:
        """Select exact admitted input for bounded agent-authored enrichment."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor) or not state.permits(
            config.workspace_id, actor, "contribute"
        ):
            raise WorkspaceError("workspace enrichment is not available")
        try:
            return enrichment_service().prepare(
                actor,
                workspace_id=workspace_id,
                page_ids=page_ids,
                expected_version=expected_version,
                request_key=request_key,
            )
        except (ContributionError, RetryConflict, ValueError) as exc:
            raise WorkspaceError(str(exc)) from exc

    @server.tool()
    def prepare_contribution(
        retry_key: str,
        sources: list[dict],
        pages: list[dict],
        base_revision: str | None = None,
        continuation_task_id: str | None = None,
        source_task_id: str | None = None,
        core_edits: list[dict] | None = None,
        enrichment_task_id: str | None = None,
        control: str | None = None,
    ) -> dict[str, Any]:
        """Prepare a native candidate from a server-selected base or task continuation."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor, "contribute"):
            raise WorkspaceError("workspace contribution is not available")
        try:
            if enrichment_task_id is not None:
                if (
                    sources
                    or base_revision is not None
                    or continuation_task_id is not None
                    or source_task_id is not None
                    or core_edits
                ):
                    raise WorkspaceError(
                        "enrichment uses only its persisted selection, complete pages, and control"
                    )
                return contribution_service().prepare_enrichment(
                    actor,
                    task_id=enrichment_task_id,
                    retry_key=retry_key,
                    pages=pages,
                    control=control,
                )
            if control is not None:
                raise WorkspaceError("a complete control candidate requires enrichment_task_id")
            analytics = analytics_service(required=False)
            if analytics is not None:
                if source_task_id is None:
                    raise WorkspaceError(
                        "integrated analytics contribution requires an exact source-task grant"
                    )
                return analytics.prepare_contribution(
                    actor,
                    retry_key=retry_key,
                    source_task_id=source_task_id,
                    sources=sources,
                    pages=pages,
                    core_edits=core_edits or [],
                )
            if source_task_id is not None or core_edits:
                raise WorkspaceError(
                    "analytics source tasks and Core edits require explicit analytics enablement"
                )
            return contribution_service().prepare(
                actor,
                retry_key=retry_key,
                base_revision=base_revision,
                continuation_task_id=continuation_task_id,
                sources=sources,
                pages=pages,
            )
        except (ContributionError, RetryConflict, ValueError) as exc:
            raise WorkspaceError(str(exc)) from exc

    @server.tool()
    def get_task(task_id: str) -> dict[str, Any]:
        """Return actual actor-scoped native task state after reconnect."""
        actor = _actor()
        if not state.permits(config.workspace_id, actor, "contribute"):
            raise WorkspaceError("workspace contribution is not available")
        try:
            source = state.get_operation(config.workspace_id, actor, "prepare_data_source", task_id)
            if source is not None:
                if source.status == "pending_review":
                    recovered = review_service().reconcile_task(task_id)
                    if recovered is not None:
                        return {"task_id": task_id, **recovered}
                return analytics_service().get(actor, task_id)
            current = contribution_service().get(actor, task_id)
            if current["status"] == "pending_review":
                recovered = review_service().reconcile_task(task_id)
                if recovered is not None:
                    return {"task_id": task_id, **recovered}
            return current
        except (ContributionError, ReviewError) as exc:
            raise WorkspaceError(str(exc)) from exc

    @server.custom_route("/uploads", methods=["POST"], include_in_schema=False)
    async def upload(request: Request) -> Response:
        if request.url.scheme != "https":
            return JSONResponse({"error": "HTTPS required"}, status_code=403)
        try:
            actor = _actor()
        except WorkspaceError:
            return JSONResponse({"error": "API authentication required"}, status_code=401)
        if not state.permits(config.workspace_id, actor, "contribute"):
            return JSONResponse(
                {"error": "workspace contribution is not available"}, status_code=403
            )
        if request.headers.get("content-type", "").split(";", 1)[0] != ("application/octet-stream"):
            return JSONResponse({"error": "exact-byte stream required"}, status_code=415)
        try:
            raw = await intake.read_bounded(request.stream())
            result = intake.save(
                config.workspace_id,
                actor,
                request.headers.get("x-lumio-source-id", ""),
                request.headers.get("x-lumio-filename", ""),
                request.headers.get("x-lumio-retry-key", ""),
                raw,
            )
        except RetryConflict as exc:
            return JSONResponse({"error": str(exc), "code": "retry_conflict"}, status_code=409)
        except UploadError as exc:
            status = {
                "source_too_large": 413,
                "unsupported_original": 415,
                "unsafe_path": 400,
                "upload_not_found": 404,
            }.get(exc.code, 400)
            return JSONResponse({"error": str(exc), "code": exc.code}, status_code=status)
        return JSONResponse(result)

    @server.custom_route("/setup", methods=["GET", "POST"], include_in_schema=False)
    async def setup(request: Request) -> Response:
        actor = _browser_actor(request)
        if actor is None:
            if request.method == "GET":
                return RedirectResponse("/auth/login", status_code=303)
            return JSONResponse({"error": "browser authentication required"}, status_code=401)
        if not state.permits(config.workspace_id, actor, "setup"):
            return JSONResponse({"error": "workspace setup is not available"}, status_code=403)
        if config.authoring_path is None or config.private_profile_path is None:
            return JSONResponse({"error": "workspace setup is not configured"}, status_code=503)
        if request.method == "POST":
            if (
                request.url.scheme != "https"
                or request.headers.get("origin") != config.external_url
            ):
                return JSONResponse({"error": "same-origin HTTPS POST required"}, status_code=403)
            if request.headers.get("content-type", "").split(";", 1)[0] != (
                "application/x-www-form-urlencoded"
            ):
                return JSONResponse({"error": "form POST required"}, status_code=415)
            try:
                body = await request.body()
                if len(body) > 8192:
                    raise ValueError("setup form too large")
                fields = parse_qs(
                    body.decode(),
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=2,
                )
            except (UnicodeDecodeError, ValueError):
                return JSONResponse({"error": "invalid setup form"}, status_code=400)
            digests = fields.get("digest", [])
            if len(fields) != 1 or len(digests) != 1:
                return JSONResponse({"error": "one setup digest is required"}, status_code=400)
            selected = setup_previews.get(digests[0])
            if selected is None or selected[0] != actor:
                return JSONResponse(
                    {"error": "a fresh owner setup preview is required"},
                    status_code=409,
                )
            try:
                result = apply_setup(state, actor, selected[1])
            except SetupError as exc:
                return JSONResponse(
                    {"error": str(exc), "code": exc.code},
                    status_code=409,
                )
            setup_previews.pop(digests[0], None)
            return JSONResponse(result)
        try:
            preview = preview_setup(
                workspace_id=config.workspace_id,
                authoring_path=config.authoring_path,
                profile_path=config.private_profile_path,
                private_root=config.operational_root,
                namespace=config.namespace,
            )
        except SetupError as exc:
            return JSONResponse({"error": str(exc), "code": exc.code}, status_code=409)
        setup_previews[preview.digest] = (actor, preview)
        return HTMLResponse(render_setup(preview))

    @server.custom_route("/review/{task_id}", methods=["GET", "POST"], include_in_schema=False)
    async def review(request: Request) -> Response:
        task_id = request.path_params["task_id"]
        actor = _browser_actor(request)
        if actor is None:
            if request.method == "GET":
                return RedirectResponse("/auth/login", status_code=303)
            return JSONResponse({"error": "browser authentication required"}, status_code=401)
        if request.url.scheme != "https":
            return JSONResponse({"error": "HTTPS required"}, status_code=403)
        if not state.permits(config.workspace_id, actor, "review"):
            return JSONResponse({"error": "workspace review is not available"}, status_code=403)
        if request.method == "GET":
            try:
                context = review_service().get(actor, task_id)
            except ReviewError as exc:
                return JSONResponse({"error": str(exc), "code": exc.code}, status_code=exc.status)
            return HTMLResponse(render_review(context, config.published_version))
        if request.headers.get("origin") != config.external_url:
            return JSONResponse({"error": "same-origin HTTPS POST required"}, status_code=403)
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            return JSONResponse({"error": "form POST required"}, status_code=415)
        try:
            body = await request.body()
            if len(body) > 8192:
                raise ValueError("review form too large")
            fields = parse_qs(
                body.decode(),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=2,
            )
        except (UnicodeDecodeError, ValueError):
            return JSONResponse({"error": "invalid review form"}, status_code=400)
        digests = fields.get("digest", [])
        decisions = fields.get("decision", [])
        if len(fields) != 2 or len(digests) != 1 or len(decisions) != 1:
            return JSONResponse({"error": "one digest and decision are required"}, status_code=400)
        try:
            result = review_service().decide(actor, task_id, digests[0], decisions[0])
        except ReviewError as exc:
            return JSONResponse({"error": str(exc), "code": exc.code}, status_code=exc.status)
        return JSONResponse(result)

    @server.custom_route(
        "/review/{task_id}/source/{source_id}/{entity_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def review_source(request: Request) -> Response:
        actor = _browser_actor(request)
        if actor is None:
            return RedirectResponse("/auth/login", status_code=303)
        if request.url.scheme != "https":
            return JSONResponse({"error": "HTTPS required"}, status_code=403)
        if not state.permits(config.workspace_id, actor, "review"):
            return JSONResponse({"error": "workspace review is not available"}, status_code=403)
        try:
            filename, text = review_service().inspect_source(
                actor,
                request.path_params["task_id"],
                request.path_params["source_id"],
                request.path_params["entity_id"],
            )
        except ReviewError as exc:
            return JSONResponse({"error": str(exc), "code": exc.code}, status_code=exc.status)
        return HTMLResponse(render_source(request.path_params["task_id"], filename, text))

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
        actor = _browser_actor(request)
        if actor is None:
            return RedirectResponse("/auth/login", status_code=303)
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
    return BrowserSessionMiddleware(mcp_app, state, auth_mode=config.auth_mode)
