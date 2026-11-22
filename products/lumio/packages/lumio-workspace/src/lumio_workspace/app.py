"""Authenticated read-only Lumio workspace ASGI application."""

from __future__ import annotations

import hashlib
import html
import os
import secrets
import time
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from lumio_wiki.git_authoring import GitAuthoringError
from lumio_wiki.knowledge_base import KnowledgeBaseError
from lumio_wiki.location import PublishedFilesystemLocation, open_knowledge_base
from lumio_wiki.page_search import normalize_search_query
from lumio_wiki.private_profile import PrivateProfileError
from lumio_wiki.records import CompiledPage, SourceFileDigest, SourceFingerprint
from lumio_wiki.retrieval import default_retrieval_adapter
from lumio_wiki.source_inspection import (
    SourceInspectionError,
    fetch_verified_artifact,
    read_local_published_bindings,
    resolve_local_published_binding,
    validate_published_version,
)
from lumio_wiki.source_registry import SAFE_FILENAME_MAX_LENGTH, safe_artifact_filename
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
from .contributions import ContributionError, ContributionService
from .enrichment import EnrichmentService
from .intake import IntakeService, UploadError
from .publication import PublicationService
from .review import ReviewError, ReviewService, render_review, render_source
from .setup import SetupError, apply_setup, preview_setup, render_setup
from .state import LOCAL_TENANT_ID, Actor, RetryConflict, WorkspaceState, local_actor


class WorkspaceError(ToolError):
    pass


# The shared audience: explicitly public and internal admitted
# pages. ``restricted`` and absent/unknown Visibility are unavailable through
# every ordinary workspace read, search, and Evidence path, before any lookup,
# match, rank, count, or snippet.
_SHARED_AUDIENCE = frozenset({"public", "internal"})

#: Maximum returned Evidence-text characters per retrieve_knowledge call.
MAX_EVIDENCE_TEXT_CHARS = 16000


# The owner browser surface assigns only membership and reviewer work;
# inspect_source and setup stay separate explicit operator grants.
_MEMBERSHIP_CAPABILITIES = ("read", "contribute", "review")

#: Originals whose exact bound metadata positively establishes a supported
#: text form keep the UTF-8 inspection view. Everything else — binary
#: originals, names truncated by the registry's safe-filename cap, or
#: unknown names — is conservatively delivered as verified bytes, never
#: silently UTF-8 decoded (spec0034 §12.3).
_TEXT_ORIGINAL_SUFFIXES = frozenset({".txt", ".md", ".markdown"})
_TEXT_CONTENT_TYPES = frozenset({"text/plain", "text/markdown"})

#: Distinct truthful outcomes for a failed original resolution or fetch, shown
#: only to an authorized inspector and never substituted with other content
#: or registry-latest bytes (spec0034 §12.3).
_INSPECTION_FAILURES = {
    "access-denied": (403, "backend access to the retained original was denied"),
    "absent-binding": (404, "this original reference is not retained at this workspace"),
    "unavailable-artifact": (404, "the retained original is temporarily unavailable"),
    "corruption": (409, "the retained original failed verification"),
    "historical-version-mismatch": (
        404,
        "no exact original binding exists for this published version",
    ),
    "ambiguous-binding": (404, "this original reference is not available at this workspace"),
    "signing-unsupported": (409, "this original does not support the requested retrieval"),
}


def _is_text_original(filename: str | None, content_type: str | None) -> bool:
    """True only when exact bound metadata positively establishes text.

    The workspace candidate path registers no content_type, so the exact
    bound filename decides; a native text content-type is honored only when
    registration actually supplied one.
    """
    # Capped display names can retain a misleading text suffix.
    if filename and len(filename) >= SAFE_FILENAME_MAX_LENGTH:
        return False
    if content_type is not None:
        base_type = content_type.split(";")[0].strip().lower()
        if base_type in _TEXT_CONTENT_TYPES:
            return True
    return Path(filename or "").suffix.lower() in _TEXT_ORIGINAL_SUFFIXES


def _inspection_failure(exc: SourceInspectionError) -> JSONResponse:
    status, message = _INSPECTION_FAILURES.get(
        exc.outcome, (404, "this original reference is not available at this workspace")
    )
    return JSONResponse(
        {"error": message, "code": exc.outcome.replace("-", "_")}, status_code=status
    )


def _safe_attachment(raw: bytes, filename: str | None, source_id: str) -> Response:
    """Verified bytes as a download-only safe attachment, never inline HTML.

    The name is the registry's sanitized safe basename; the generic media type
    plus ``nosniff`` prevent active rendering, and no signed or otherwise
    bearer-capable URL is produced.
    """
    name = safe_artifact_filename(filename) or f"{source_id}.bin"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        content=raw,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


def _source_references(version: str | None, page: Any) -> list[dict[str, Any]]:
    """All authored source attributions with a version-qualified action.

    Attribution facts (id, title, external URL) come only from the published
    page itself. The reference action names the exact Published Version,
    Entity, and Source ID and conveys no bearer access: opening it re-checks
    browser authentication, current membership, the separate inspect_source
    grant, and the exact admitted binding. No availability, filename, size, or
    digest is disclosed and no private store is probed to build it
    (spec0034 §12.3).
    """
    entries = []
    for source in page.sources:
        reference = (
            f"/original/{quote(version)}/{quote(page.id)}/{quote(source.id)}"
            if version and page.id and source.id
            else None
        )
        entries.append(
            {
                "id": source.id,
                "title": source.title or None,
                "url": source.url,
                "reference": reference,
            }
        )
    return entries


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
    retrieval_backend: str = "zero-index"

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
            retrieval_backend=os.environ.get("LUMIO_WORKSPACE_RETRIEVAL_BACKEND") or "zero-index",
        )

    def __post_init__(self) -> None:
        if not self.workspace_id or not self.external_url.startswith("https://"):
            raise ValueError("workspace ID and an HTTPS external URL are required")
        if self.auth_mode not in {"local-token", "entra"}:
            raise ValueError("authentication mode must be local-token or entra")
        if self.auth_mode == "entra" and self.identity is None:
            raise ValueError("Entra mode requires identity configuration")
        if self.retrieval_backend not in {"zero-index", "bm25"}:
            raise ValueError("retrieval backend must be zero-index or bm25")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"missing required configuration: {name}")
    return value


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _analytics_configured(config: WorkspaceConfig) -> bool:
    """True when any Ariadne analytics integration is configured (integrated mode)."""
    return any(
        (
            config.analytics_project_id,
            config.analytics_project_path,
            config.analytics_source_bindings_path,
        )
    )


def _authorized_pages(resolved: Any) -> list[CompiledPage]:
    """The one server-side authorized view: the shared-audience admitted pages.

    Every ordinary workspace read, search, and Evidence path filters to this
    candidate set before any lookup, match, rank, count, or snippet, so a
    hidden page cannot influence visible results and a hidden title, alias, or
    ID is indistinguishable from a missing one.
    """
    return [page for page in resolved.pages if (page.visibility or "") in _SHARED_AUDIENCE]


def _view_fingerprint(resolved: Any, authorized: list[CompiledPage]) -> SourceFingerprint:
    """Fingerprint the exact admitted publication plus its visible captured content.

    This is the derived-cache binding: publication version, visible-set
    identity, and captured page content. It is deliberately narrower than the
    publication fingerprint so an index built over the authorized view is
    never mistaken for one built over a broader set.
    """

    def page_digest(page: CompiledPage) -> str:
        material = "\x1f".join(
            (
                page.path,
                page.visibility or "",
                page.title,
                *sorted(page.aliases),
                *sorted(page.tags),
                page.summary or "",
                page.body,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    ordered = sorted(authorized, key=lambda page: page.path)
    digest = hashlib.sha256(
        "\n".join(
            [resolved.published_version or "", *(f"{p.path}\x1f{page_digest(p)}" for p in ordered)]
        ).encode("utf-8")
    ).hexdigest()
    return SourceFingerprint(
        digest=digest,
        sources=[SourceFileDigest(path=page.path, digest=page_digest(page)) for page in ordered],
    )


def _retrieval_cache_dir(config: WorkspaceConfig, version: str | None) -> Path:
    """The private derived-cache path for one Published Version.

    Always under the operational root, never inside an immutable published
    tree; the version label binds the cache to one publication.
    """
    label = validate_published_version(version or "")
    return config.operational_root / "retrieval-cache" / label


def prepare_retrieval_cache(config: WorkspaceConfig) -> str:
    """Operator-only preparation of the optional authorized BM25 retrieval cache.

    Builds the derived index over the authorized shared view of the configured
    admitted publication into the private operational cache. It never activates
    content, never writes a published tree, and never calls an embedding
    service or the network. Readers never build the cache; a missing or stale
    cache falls back truthfully to lexical retrieval over the same view.
    """
    if _analytics_configured(config):
        raise WorkspaceError(
            "standalone retrieval preparation is not available in an integrated workspace; "
            "integrated knowledge remains on its pinned governed release"
        )
    if config.retrieval_backend != "bm25":
        raise WorkspaceError(
            "retrieval preparation requires LUMIO_WORKSPACE_RETRIEVAL_BACKEND=bm25"
        )
    try:
        from lumio_lancedb.index import LanceDBRetrievalAdapter
    except ImportError as exc:
        raise WorkspaceError(
            "the optional retrieval dependency is missing; install lumio-workspace[retrieval]"
        ) from exc
    resolved = open_knowledge_base(
        PublishedFilesystemLocation(config.published_path, version=config.published_version)
    )
    if not resolved.validation_report.is_valid:
        raise WorkspaceError("published knowledge is unavailable")
    authorized = _authorized_pages(resolved)
    cache_dir = _retrieval_cache_dir(config, resolved.published_version)
    LanceDBRetrievalAdapter().build_index(
        authorized, cache_dir, fingerprint=_view_fingerprint(resolved, authorized)
    )
    return (
        f"prepared BM25 retrieval cache for Published Version {resolved.published_version}: "
        f"{len(authorized)} authorized pages at {cache_dir}"
    )


def _search_entry(result: Any) -> dict[str, Any]:
    """One bounded search result, preserving the existing response fields.

    The stable Entity ID is additive native metadata; Legacy
    Flat Mode pages declare none, so the key stays absent rather than deriving
    an ID from the title.
    """
    entry: dict[str, Any] = {
        "title": result.page.title,
        "citation": {"title": result.page.title, "path": result.page.path},
        "passage": result.snippet,
    }
    if result.page.id:
        entry["entity_id"] = result.page.id
    return entry


def _retrieve_evidence(
    config: WorkspaceConfig,
    normalized: str,
    limit: int,
    resolved: Any,
    authorized: list[CompiledPage],
) -> tuple[list[Any], dict[str, Any]]:
    """Retrieve Evidence over the authorized view and disclose the effective backend.

    Default is the existing zero-index lexical adapter; an owner-configured
    optional BM25 cache is read through the existing LanceDB adapter, never
    built by a reader, and never selects semantic/Hybrid retrieval or an
    embedding/network call. A missing, stale, or unhealthy cache falls back
    truthfully to lexical over the same authorized view.
    """
    if config.retrieval_backend != "bm25":
        results = default_retrieval_adapter().retrieve(
            authorized, normalized, limit=limit, mode="lexical", eligible_pages=authorized
        )
        return results, {"backend": "zero-index", "fallback": None}
    try:
        from lumio_lancedb.index import LanceDBRetrievalAdapter
        from lumio_lancedb.location import LocalIndexLocation
    except ImportError:
        results = default_retrieval_adapter().retrieve(
            authorized, normalized, limit=limit, mode="lexical", eligible_pages=authorized
        )
        return results, {
            "backend": "zero-index",
            "fallback": (
                "the optional retrieval dependency is unavailable; "
                "lexical fallback over the authorized view"
            ),
        }
    cache_dir = _retrieval_cache_dir(config, resolved.published_version)
    adapter = LanceDBRetrievalAdapter(index_location=LocalIndexLocation(cache_dir))
    results = adapter.retrieve(
        authorized,
        normalized,
        limit=limit,
        index_dir=cache_dir,
        mode="lexical",
        eligible_pages=authorized,
        expected_fingerprint=_view_fingerprint(resolved, authorized),
    )
    detail = adapter.last_fallback_detail
    backend = "zero-index" if detail is not None else "lancedb-bm25"
    return results, {"backend": backend, "fallback": detail}


def _bounded_evidence_response(
    resolved: Any,
    authorized: list[CompiledPage],
    results: list[Any],
    retrieval: dict[str, Any],
) -> dict[str, Any]:
    """Bound retrieved Evidence to the per-call text budget with truthful disclosure.

    Oversized indivisible Evidence units are omitted — never returned with
    false complete spans — and their exact coordinates are disclosed without
    their text. Each result carries every authored source
    attribution of its page with the non-bearer reference actions of the
    served Published Version.
    """
    entity_ids = {page.path: (page.id or None) for page in authorized}
    pages_by_path = {page.path: page for page in authorized}
    included: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    remaining = MAX_EVIDENCE_TEXT_CHARS
    for result in results:
        evidence = result.evidence
        if len(evidence.text) > remaining:
            omitted.append(
                {
                    "page_title": evidence.page_title,
                    "page_path": evidence.page_path,
                    "section_title": evidence.section_title,
                    "line_start": evidence.line_start,
                    "line_end": evidence.line_end,
                    "reason": "evidence text exceeds the remaining per-call character budget",
                }
            )
            continue
        remaining -= len(evidence.text)
        included.append(
            {
                "entity_id": entity_ids.get(evidence.page_path),
                "evidence": {
                    "id": evidence.id,
                    "page_title": evidence.page_title,
                    "page_path": evidence.page_path,
                    "section_title": evidence.section_title,
                    "line_start": evidence.line_start,
                    "line_end": evidence.line_end,
                    "text": evidence.text,
                },
                "citation": {
                    "title": result.citation.page_title,
                    "path": result.citation.relative_path,
                    "source": result.citation.source,
                    "line_start": result.citation.line_start,
                    "line_end": result.citation.line_end,
                    "section_title": result.citation.section_title,
                },
                "sources": _source_references(
                    resolved.published_version, pages_by_path.get(evidence.page_path)
                ),
                "snippet": result.snippet,
                "score": result.score,
                "trace": {
                    "stages": [
                        {"name": stage.name, "detail": stage.detail}
                        for stage in result.trace.stages
                    ],
                    "candidates_seen": result.trace.candidates_seen,
                    "results_returned": result.trace.results_returned,
                    "results_dropped": result.trace.results_dropped,
                },
            }
        )
    return {
        "published_version": resolved.published_version,
        "retrieval": retrieval,
        "results": included,
        "omitted": omitted,
        "text_characters": MAX_EVIDENCE_TEXT_CHARS - remaining,
    }


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


def _membership_rows(
    state: WorkspaceState, config: WorkspaceConfig
) -> list[tuple[str, bool, tuple[str, ...]]]:
    # Read-only listing through the state's own connection; state.py is not
    # part of this surface's owned files.
    with state._connect() as connection:
        users = connection.execute(
            "SELECT user_id, enabled FROM local_users ORDER BY user_id"
        ).fetchall()
        grants = connection.execute(
            "SELECT object_id, capability FROM memberships "
            "WHERE workspace_id = ? AND tenant_id = ? ORDER BY object_id, capability",
            (config.workspace_id, LOCAL_TENANT_ID),
        ).fetchall()
    capabilities: dict[str, list[str]] = {user: [] for user, _enabled in users}
    for object_id, capability in grants:
        capabilities.setdefault(object_id, []).append(capability)
    return [(user, bool(enabled), tuple(capabilities.get(user, ()))) for user, enabled in users]


def _render_membership(workspace: str, rows: list[tuple[str, bool, tuple[str, ...]]]) -> str:
    body_rows = "\n".join(
        "<tr>"
        f"<td><code>{html.escape(user)}</code></td>"
        f"<td>{'enabled' if enabled else 'disabled'}</td>"
        f"<td>{html.escape(', '.join(capabilities) or 'none')}</td>"
        "</tr>"
        for user, enabled, capabilities in rows
    )
    options = "\n".join(
        f'<option value="{capability}">{capability}</option>'
        for capability in _MEMBERSHIP_CAPABILITIES
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Workspace membership</title></head><body><main>"
        "<h1>Workspace membership</h1>"
        f"<p>Owner surface for {html.escape(workspace)}: assign or revoke member, "
        "contributor, and reviewer capabilities. Original/source/data inspection "
        "(<code>inspect_source</code>) and owner setup remain separate explicit "
        "operator grants outside this page.</p>"
        "<table><thead><tr><th>User</th><th>State</th><th>Capabilities</th></tr>"
        f"</thead><tbody>\n{body_rows}\n</tbody></table>"
        '<form method="post" action="/membership">'
        '<label>Local user <input name="user_id" required autocomplete="off"></label> '
        f'<select name="capability">\n{options}\n</select> '
        '<select name="action"><option value="grant">grant</option>'
        '<option value="revoke">revoke</option></select> '
        '<button type="submit">Apply</button></form>'
        "</main></body></html>"
    )


def create_app(config: WorkspaceConfig, *, token_verifier: TokenVerifier | None = None) -> Any:
    state = WorkspaceState(config.state_path)
    intake = IntakeService(state, config.operational_root)
    setup_previews: dict[str, tuple[Actor, Any]] = {}
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

    def snapshot(requested_version: str | None = None) -> Any:
        actor = _actor()
        if not state.permits(config.workspace_id, actor):
            raise WorkspaceError("workspace access is not available")
        try:
            resolved = open_knowledge_base(read_location(requested_version))
        except KnowledgeBaseError as exc:
            if requested_version is None:
                raise
            raise WorkspaceError(
                "requested Published Version is not available at this workspace"
            ) from exc
        if not resolved.validation_report.is_valid:
            raise WorkspaceError("published knowledge is unavailable")
        return actor, resolved, _authorized_pages(resolved)

    def read_location(requested_version: str | None) -> PublishedFilesystemLocation:
        """Resolve one version of the configured publication for an ordinary read.

        Historical reads stay on admitted history at the configured destination
        under current authorization; an explicit reader pin
        serves exactly that version and nothing else.
        """
        if requested_version is None:
            return PublishedFilesystemLocation(
                config.published_path, version=config.published_version
            )
        if config.published_version is not None and requested_version != config.published_version:
            raise WorkspaceError(
                "this workspace is pinned to one Published Version; another is not available"
            )
        try:
            validate_published_version(requested_version)
        except ValueError as exc:
            raise WorkspaceError(
                "requested Published Version is not available at this workspace"
            ) from exc
        verify_admitted_version(requested_version)
        return PublishedFilesystemLocation(config.published_path, version=requested_version)

    def verify_admitted_version(version: str) -> None:
        """Gate a caller-selected version on verified native admission.

        A complete manifest is not admission: the version's
        admission receipt must verify against the configured destination and
        be activated, or the destination's current pointer must name it
        (native activation reconciliation). Interrupted publication residue —
        a complete version directory or a preactivation receipt with an older
        pointer — never becomes ordinary historical Evidence, and every
        refusal is the same generic unavailable response, never an existence
        disclosure. This reads admission provenance only; it never inspects
        originals or the private source store.
        """
        try:
            receipt, _sealed = read_local_published_bindings(config.published_path, version)
        except (GitAuthoringError, KnowledgeBaseError, SourceInspectionError) as exc:
            raise WorkspaceError(
                "requested Published Version is not available at this workspace"
            ) from exc
        if receipt.activated:
            return
        if PublishedFilesystemLocation(config.published_path).read_pointer() != version:
            raise WorkspaceError("requested Published Version is not available at this workspace")

    @server.tool()
    def workspace_status() -> dict[str, Any]:
        """Return ready state and current capabilities, without configuration secrets."""
        actor, resolved, _authorized = snapshot()
        return {
            "workspace": config.workspace_id,
            "ready": True,
            "capabilities": list(state.capabilities(config.workspace_id, actor)),
            "published_version": resolved.published_version,
        }

    @server.tool()
    def read_knowledge(title: str, published_version: str | None = None) -> dict[str, Any]:
        """Read one admitted Compiled Page by Canonical Page Title or alias.

        ``published_version`` re-reads cited content from that exact admitted
        publication at the configured destination (version-aware follow-up);
        omitted, the configured current publication is served.
        """
        _, resolved, authorized = snapshot(published_version)
        # Match only authorized pages, with canonical titles before aliases.
        pages = [page for page in authorized if page.title == title]
        if not pages:
            pages = [page for page in authorized if title in page.aliases]
        if not pages:
            return {"found": False}
        page = pages[0]
        return {
            "found": True,
            "title": page.title,
            "summary": page.summary,
            "markdown": page.body,
            "entity_id": page.id or None,
            "sources": _source_references(resolved.published_version, page),
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
        _, resolved, authorized = snapshot()
        return {
            "published_version": resolved.published_version,
            "results": [
                _search_entry(result)
                for result in resolved.search_pages(query, limit=limit, pages=authorized)
            ],
        }

    @server.tool()
    def retrieve_knowledge(
        query: str, limit: int = 5, published_version: str | None = None
    ) -> dict[str, Any]:
        """Retrieve bounded citation-ready Evidence from the admitted shared view.

        Standalone knowledge only: an integrated workspace refuses this tool
        instead of silently changing its governed knowledge view (spec0034
        §12.2, AC28). ``published_version`` pins the exact admitted publication
        for a cited-version reread.
        """
        if _analytics_configured(config):
            raise WorkspaceError(
                "standalone Evidence retrieval is not available in an integrated workspace; "
                "integrated knowledge remains on its pinned governed release"
            )
        if not 1 <= limit <= 20:
            raise WorkspaceError("limit must be between 1 and 20")
        try:
            normalized = normalize_search_query(query)
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc
        _, resolved, authorized = snapshot(published_version)
        results, retrieval = _retrieve_evidence(config, normalized, limit, resolved, authorized)
        return _bounded_evidence_response(resolved, authorized, results, retrieval)

    def analytics_service(*, required: bool = True) -> Any:
        if not _analytics_configured(config):
            if required:
                raise WorkspaceError(
                    "analytics is not enabled; the owner must configure the exact project "
                    "and operator source bindings"
                )
            return None
        if (
            not (
                config.analytics_project_id
                and config.analytics_project_path
                and config.analytics_source_bindings_path
            )
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
            analytics_enabled=_analytics_configured(config),
        )

    def enrichment_service() -> EnrichmentService:
        return EnrichmentService(contribution_service(), destination=config.published_path)

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
            if source_task_id is not None or core_edits:
                # Explicit data/Core change requests keep the grant and joint
                # whole-change review route; analytics configuration alone
                # must not capture ordinary knowledge contributions.
                analytics = analytics_service(required=False)
                if analytics is None:
                    raise WorkspaceError(
                        "analytics source tasks and Core edits require explicit "
                        "analytics enablement"
                    )
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
                analytics_enabled=_analytics_configured(config),
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
            binding, raw = review_service().inspect_source(
                actor,
                request.path_params["task_id"],
                request.path_params["source_id"],
                request.path_params["entity_id"],
            )
        except ReviewError as exc:
            return JSONResponse({"error": str(exc), "code": exc.code}, status_code=exc.status)
        if _is_text_original(binding.filename, binding.content_type):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return JSONResponse(
                    {
                        "error": "the retained original failed text verification",
                        "code": "corruption",
                    },
                    status_code=409,
                )
            return HTMLResponse(
                render_source(
                    request.path_params["task_id"],
                    binding.filename or request.path_params["source_id"],
                    text,
                )
            )
        # The bound metadata does not positively establish text (binary
        # original, extension lost to the safe-filename cap, or unknown name):
        # deliver the exact verified bytes as a safe attachment — never a
        # UTF-8 decode of unknown content.
        return _safe_attachment(raw, binding.filename, request.path_params["source_id"])

    @server.custom_route(
        "/original/{published_version}/{entity_id}/{source_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def original_reference(request: Request) -> Response:
        """Deliver one admitted publication's exact original as a safe attachment.

        Browser-authenticated and independent of any pending review. Current
        membership and the separate ``inspect_source`` grant are re-checked on
        the request before any private store probe or availability, filename,
        size, or digest disclosure; only then does the reference resolve the
        exact admitted configured page/source/version binding through the
        native sealed record — never a caller-supplied object key, filesystem
        path, hash, or registry-latest substitute.
        """
        actor = _browser_actor(request)
        if actor is None:
            return RedirectResponse("/auth/login", status_code=303)
        if request.url.scheme != "https":
            return JSONResponse({"error": "HTTPS required"}, status_code=403)
        # Current membership (any capability) AND the separate inspection grant
        # precede every private probe: no availability, filename, size, or
        # digest fact is disclosed to a caller lacking either (spec0034 §12.3:
        # only current members with separate inspect_source may download; a
        # review-only member holding that grant qualifies).
        if not state.capabilities(config.workspace_id, actor):
            return JSONResponse({"error": "workspace access is not available"}, status_code=403)
        if not state.permits(config.workspace_id, actor, "inspect_source"):
            return JSONResponse(
                {"error": "source inspection requires its separate capability"},
                status_code=403,
            )
        version = request.path_params["published_version"]
        entity_id = request.path_params["entity_id"]
        source_id = request.path_params["source_id"]
        unavailable = JSONResponse(
            {"error": "this original reference is not available at this workspace"},
            status_code=404,
        )
        if config.published_version is not None and version != config.published_version:
            return unavailable
        try:
            validate_published_version(version)
            verify_admitted_version(version)
            resolved = open_knowledge_base(
                PublishedFilesystemLocation(config.published_path, version=version)
            )
        except (
            ValueError,
            GitAuthoringError,
            KnowledgeBaseError,
            SourceInspectionError,
            WorkspaceError,
        ):
            return unavailable
        if not resolved.validation_report.is_valid:
            return unavailable
        pages = [page for page in _authorized_pages(resolved) if page.id == entity_id]
        if not pages or source_id not in {source.id for source in pages[0].sources}:
            # A hidden or unknown reference is indistinguishable from a missing
            # one; no binding detail is disclosed either way.
            return unavailable
        if config.authoring_path is None or config.private_profile_path is None:
            return JSONResponse(
                {
                    "error": "the private source resources are unavailable",
                    "code": "unavailable_artifact",
                },
                status_code=404,
            )
        try:
            resources = PublicationService(
                authoring_path=config.authoring_path,
                profile_path=config.private_profile_path,
                destination=config.published_path,
            ).resources()
        except PrivateProfileError:
            return JSONResponse(
                {
                    "error": "the private source resources are unavailable",
                    "code": "unavailable_artifact",
                },
                status_code=404,
            )
        if resources.artifact_store is None:
            return JSONResponse(
                {
                    "error": "the private source resources are unavailable",
                    "code": "unavailable_artifact",
                },
                status_code=404,
            )
        try:
            binding = resolve_local_published_binding(
                config.published_path, version, source_id, entity_id=entity_id
            )
            raw = fetch_verified_artifact(resources.artifact_store, binding)
        except SourceInspectionError as exc:
            return _inspection_failure(exc)
        return _safe_attachment(raw, binding.filename, source_id)

    @server.custom_route("/membership", methods=["GET", "POST"], include_in_schema=False)
    async def membership(request: Request) -> Response:
        actor = _browser_actor(request)
        if actor is None:
            if request.method == "GET":
                return RedirectResponse("/auth/login", status_code=303)
            return JSONResponse({"error": "browser authentication required"}, status_code=401)
        if not state.permits(config.workspace_id, actor, "setup"):
            return JSONResponse(
                {"error": "workspace membership management is not available"}, status_code=403
            )
        if request.method == "GET":
            return HTMLResponse(
                _render_membership(config.workspace_id, _membership_rows(state, config))
            )
        if request.url.scheme != "https" or request.headers.get("origin") != config.external_url:
            return JSONResponse({"error": "same-origin HTTPS POST required"}, status_code=403)
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            return JSONResponse({"error": "form POST required"}, status_code=415)
        try:
            body = await request.body()
            if len(body) > 8192:
                raise ValueError("membership form too large")
            fields = parse_qs(
                body.decode(),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=3,
            )
        except (UnicodeDecodeError, ValueError):
            return JSONResponse({"error": "invalid membership form"}, status_code=400)
        users = fields.get("user_id", [])
        capabilities = fields.get("capability", [])
        actions = fields.get("action", [])
        if len(fields) != 3 or len(users) != 1 or len(capabilities) != 1 or len(actions) != 1:
            return JSONResponse(
                {"error": "one user, capability, and action are required"}, status_code=400
            )
        user_id, capability, action = users[0], capabilities[0], actions[0]
        if user_id.strip() != user_id or not user_id:
            return JSONResponse({"error": "invalid local user ID"}, status_code=400)
        if capability not in _MEMBERSHIP_CAPABILITIES:
            return JSONResponse(
                {
                    "error": "this page assigns only read, contribute, and review; "
                    "original/source/data access stays a separate explicit operator grant"
                },
                status_code=400,
            )
        target_actor = local_actor(user_id)
        try:
            if action == "grant":
                state.grant(config.workspace_id, target_actor, capability)
            elif action == "revoke":
                state.revoke(config.workspace_id, target_actor, capability)
            else:
                return JSONResponse({"error": "unknown membership action"}, status_code=400)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "user_id": user_id,
                "capability": capability,
                "action": action,
                "capabilities": list(state.capabilities(config.workspace_id, target_actor)),
            }
        )

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
