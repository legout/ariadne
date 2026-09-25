"""MCP adapter: registers the five AriadneRuntime operations as stdio tools,
plus the five harness-led authoring tools (issue #16, spec 2026-09-24-0005
"Authoring interface and lifecycle" — local clauses).

All query behavior — compilation, execution, context attachment, grain checks,
proposal staging — lives in :class:`ariadne.runtime.AriadneRuntime`
(spec 2026-09-23-0001 §3, ADR-0012); this module only registers exactly five
query tools (spec §4) over one runtime instance and parses the server
arguments. All authoring behavior lives in :mod:`ariadne.authoring`
(:func:`propose_sources`, :func:`harness_inputs`, :func:`store_upload`,
:func:`submit_bundle`, :func:`review_bundle`); the adapter adds five stdio
tools with the SAME checks and response contracts as ``ariadne-authoring`` —
and never a source-approval or Promotion tool (those are human-only server
host commands, ADR-0013). ``Facade`` remains import-compatible here as a plain
alias of the runtime class — never a subclass or wrapper that could diverge.

The server is launched for ONE locally configured project (``--project DIR``):
the caller cannot select another project root or source credentials through
any tool argument, and stdio needs no bearer token (that is the #18 HTTP
transport's rule). An empty, not-yet-promoted project still starts: the
authoring tools work before the first Promotion, and query tool calls surface
the runtime's existing missing-served-model error instead of blocking startup.

Routing contract (spec rev 4 §8.12): fresh consuming agents discover the ad-hoc
path through the facade itself — the tool descriptions carry the same routing
language ``list_metrics`` and the unknown-metric error use (the MCP registry is
the agent's map).

Usage::

    python -m ariadne.serve --project /path/to/project
    python -m ariadne.serve --db examples/retail-demo/data/demo.db \\
        --semantic semantic_layer --context context_layer
"""

import argparse
import base64
import json
import os
import sys
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

# The transport-neutral authoring service (issues #13–#15): one import, the
# five tool bodies are one-line delegations with its verbatim contracts.
from ariadne import authoring

# The grain guidance constant lives in ariadne.grain; it stays importable from
# this module for backward compatibility (tests import it from here).
from ariadne.grain import GRAIN_GUIDANCE  # noqa: F401 — re-export
from ariadne.runtime import AriadneRuntime
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    default_registry_path,
)

# Back-compat alias (spec 2026-09-23-0001 §3): ariadne.serve.Facade IS the
# runtime class — a plain assignment, not a subclass or wrapper.
Facade = AriadneRuntime

# A live query runtime, or a zero-arg factory for a project with no promoted
# models yet (spec 2026-09-24-0005: the promoted-models requirement "cannot
# block startup of the authoring tools"; query calls re-attempt construction).
FacadeSource = AriadneRuntime | Callable[[], AriadneRuntime]


@contextmanager
def _intake(content: str, suffix: str):
    """One throwaway intake file so a tool call reuses the service's exact
    file-based CLI contract (same checks, same error messages) — removed right
    after the call; the service resolves any relative locations against the
    PROJECT root, never this file's directory."""
    handle, name = tempfile.mkstemp(suffix=suffix, text=True)
    os.close(handle)
    try:
        Path(name).write_text(content, encoding="utf-8")
        yield name
    finally:
        os.unlink(name)


def build_app(facade: FacadeSource, *, project: str | Path = "."):
    """Wire the runtime and the authoring service onto one MCP stdio server:
    exactly five query tools (spec §4) plus exactly five authoring tools
    (spec 2026-09-24-0005) — never source approval or Promotion.

    ``project`` is the ONE configured project root the authoring tools operate
    on; the default is the current directory because :func:`main` chdir'd into
    the ``--project`` root at launch (direct in-process callers pass theirs)."""
    from mcp.server.fastmcp import (  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
        FastMCP,  # mcp<2 (pinned) exports FastMCP; the 2.x shim renames it
    )

    app: FastMCP = FastMCP("ariadne")

    def _runtime() -> AriadneRuntime:
        """The query runtime — a live instance, or the launch-time factory
        (empty project: the authoring tools work, query calls surface the
        construction error)."""
        return facade() if callable(facade) else facade

    # --- the five query/ad-hoc tools (spec 2026-09-23-0001, unchanged) ---

    @app.tool()
    async def list_metrics() -> list[dict | str]:
        """List served governed metrics with descriptions and available dimensions.

        The response ends with a routing hint: questions no listed metric answers
        go to list_datasets() + define_metric (the ad-hoc path).
        """
        return await _runtime().list_metrics()

    @app.tool()
    async def search_context(query: str) -> list[dict]:
        """Search the Context Layer (OKF pages) for business rules; ranked matches.

        Includes auto-staged ad-hoc proposals awaiting promotion; those hits are
        marked draft: true (served pages are draft: false).
        """
        return await _runtime().search_context(query)

    @app.tool()
    async def get_metric(
        name: str, dimensions: list[str] | None = None, range: dict | None = None
    ) -> dict:
        """Rows plus compiled SQL for a named governed metric — never raw SQL.

        The response carries a context field: the full served OKF metric page
        plus the full bodies of every policy it cites. Report those caveats
        with every number (context is null-shaped when no page is served yet).

        Args:
            name: governed metric name (see list_metrics).
            dimensions: dimensions to group by (e.g. ["region"]).
            range: optional {"start", "end"} dates on the primary date dimension.
        """
        return await _runtime().get_metric(name, dimensions, range)

    @app.tool()
    async def list_datasets() -> list[dict]:
        """List every table in the attached database with its columns and types.

        Pairs with define_metric: pick tables here, then define an ad-hoc metric
        for any question no governed metric answers.
        """
        return await _runtime().list_datasets()

    @app.tool()
    async def define_metric(definition: dict) -> dict:
        """Define an ad-hoc metric for a question no governed metric answers:
        compiled, executed read-only, auto-staged for human promotion.

        Args:
            definition: {name, description, source, expression, dimensions?, time_field?}
                where name is a lowercase snake_case slug, source is a table name or a
                SELECT (joins allowed), expression is an aggregate SQL expression
                (any business filter belongs in it), and dimensions/time_field are
                column names of the source. Joins must be grain-preserving: every
                join key must be unique on the joined side — resolve one-to-many
                relationships per the ADR-0006 rubric (upstream conditional pivot,
                child-grain fact model, or fact weight allocation), i.e. pre-aggregate
                the many side to the fact grain inside source, or the definition is
                rejected. Invalid definitions return the compiler
                errors verbatim; nothing is staged or executed. Success returns rows,
                the compiled SQL (provenance), governed: false, the echoed definition,
                and the staging paths of the auto-staged proposal (OSI model under
                semantic_layer/models/adhoc/ plus an OKF draft under
                context_layer/metrics/ that search_context can find).
        """
        return await _runtime().define_metric(definition)

    # --- the five authoring tools (spec 2026-09-24-0005, issue #16) ---
    # The project root below was fixed at server launch (--project); no tool
    # argument ever selects a filesystem root or a credential.

    authoring_project = str(Path(project).resolve())

    @app.tool()
    async def authoring_propose_sources(proposal_yaml: str) -> dict:
        """Propose source registry entries (registry-shaped YAML text) for
        operator approval — inert DATA: nothing is opened or connected until a
        human runs the separate server-host ariadne-authoring approve-sources
        with the returned digest. Response: {digest, proposal, sources} naming
        the precise proposed locations (same contract as the local CLI).

        Args:
            proposal_yaml: a "sources:" YAML document (name/type/path or
                connection_env entries); invalid shapes and inline credentials
                are rejected before anything is stored.
        """
        with _intake(proposal_yaml, ".yaml") as file:
            return authoring.propose_sources(file, project=authoring_project)

    @app.tool()
    async def authoring_inputs(documents: list[str] | None = None, part: int = 1) -> dict:
        """The harness's measured inputs (no model anywhere): the deterministic
        profile of the APPROVED registry (null before operator source
        approval), source-linked converted evidence for referenced documents,
        and the optional already-approved Seed Notes — each in bounded parts
        (part 1 of N; complete only when N is 1). Same contract as the local
        CLI ``ariadne-authoring inputs``.

        Args:
            documents: input-area references (e.g. uploaded filenames); at most
                16 per call, each inside the operator-configured roots.
            part: which bounded part of each document's converted text.
        """
        return authoring.harness_inputs(
            project=authoring_project, documents=documents or [], part=part
        )

    @app.tool()
    async def authoring_upload_document(name: str, content_b64: str) -> dict:
        """Upload one bounded document (base64 bytes) into the project input
        area; its original bytes are retained under the name's stable identity
        {resource, digest}. Large documents belong in the operator input area
        or object storage instead (the bound is enforced before any write).

        Args:
            name: a plain filename (no directories).
            content_b64: the document's raw bytes, base64-encoded; at most
                5 MiB decoded.
        """
        try:
            data = base64.b64decode(content_b64, validate=True)
        except ValueError as exc:  # binascii.Error included
            raise ValueError(f"{name}: upload content is not valid base64: {exc}") from None
        return authoring.store_upload(name, data, project=authoring_project)

    @app.tool()
    async def authoring_submit_bundle(
        files: list[dict], documents: list[str] | None = None, base_digest: str | None = None
    ) -> dict:
        """Submit the harness model's complete proposed bundle — complete Seed
        Notes (data/seed_notes.md), OSI models, and OKF pages as relative
        paths + contents — for the SAME deterministic checks the author loop
        runs, staged for human review: never approval, never promotion, never
        a served write. Cited document references are verified against the
        operator's document boundary and recorded server-side. Errors identify
        the affected files and repair the SAME proposal; repairs need the
        current digest as base_digest. Same contract as the local CLI
        ``ariadne-authoring submit``.

        Args:
            files: [{path, content}] — documented bundle roots only.
            documents: input-area references the proposal cites (verified).
            base_digest: the CURRENT submission digest (required to repair).
        """
        submission: dict = {"files": files, "documents": documents or []}
        if base_digest is not None:
            submission["base_digest"] = base_digest
        with _intake(json.dumps(submission), ".json") as file:
            return authoring.submit_bundle(file, project=authoring_project)

    @app.tool()
    async def authoring_review_bundle(part: int = 1) -> dict:
        """The staged bundle proposal — inventory, source identities, the
        verified converted-document citations, provenance, validation state,
        the exact reviewed-content digest, and every proposed body in bounded
        parts. Readable by the harness and the human alike, but NEVER a
        signoff: promotion is the separate human-only ariadne-promote. Same
        contract as the local CLI ``ariadne-authoring review``.

        Args:
            part: which bounded part of each proposed body.
        """
        return authoring.review_bundle(project=authoring_project, part=part)

    return app


def _mcp_missing(exc: BaseException) -> bool:
    """True only when the MCP SDK itself is absent (spec §7): the failing
    import names the mcp package and ``import mcp`` genuinely fails. An
    internal mcp import failure or a missing mcp dependency surfaces itself —
    the hint never masks it."""
    if not isinstance(exc, ModuleNotFoundError):
        return False
    name = getattr(exc, "name", None)
    if name != "mcp" and not (isinstance(name, str) and name.startswith("mcp.")):
        return False
    try:
        import mcp  # noqa: F401  # pyright: ignore[reportMissingImports] — [mcp] extra
    except ImportError:
        return True
    return False


def _mcp_sdk_absent() -> bool:
    """True when the optional MCP SDK is genuinely not importable (the [mcp]
    extra, ADR-0012/spec §7) — the granularity :func:`_mcp_missing` probes."""
    try:
        import mcp  # noqa: F401  # pyright: ignore[reportMissingImports] — [mcp] extra
    except ImportError:
        return True
    return False


def _missing_served_models(exc: BaseException) -> bool:
    """True for the runtime's promoted-models startup errors (no semantic
    models directory yet / no governed metrics under it — the exact messages
    AriadneRuntime raises; runtime.py is outside this adapter's scope). Spec
    2026-09-24-0005: an empty project must not block MCP startup of the
    authoring tools, and query tool calls surface this same error."""
    message = str(exc)
    return "promote staging/semantic_layer/ first" in message or (
        "no governed metrics found under" in message
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.serve",
        description="MCP stdio facade over the served context and semantic layers.",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="the ONE locally configured project root (default: the working "
        "directory): anchors the authoring tools and every default below; no "
        "tool argument ever selects a project",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite database to attach read-only (default: examples/retail-demo/data/demo.db when "
        "no --sources/ariadne.yaml applies)",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="source registry YAML (ADR-0010; default: ./ariadne.yaml only when "
        "neither --sources nor --db is given)",
    )
    parser.add_argument("--semantic", default="semantic_layer", help="served OSI layer directory")
    parser.add_argument("--context", default="context_layer", help="served OKF layer directory")
    parser.add_argument(
        "--staging", default="staging", help="staging root for auto-staged ad-hoc proposals"
    )
    args = parser.parse_args(argv)

    # One project root anchors everything (issue #16: the server is launched
    # for one locally configured project): chdir so every existing
    # cwd-relative default — the ambient ./ariadne.yaml registry, the served
    # layer dirs, the staging root — resolves against it exactly as in a
    # project-root launch, whatever directory the server was started from.
    project = Path(args.project).resolve()
    try:
        os.chdir(project)
    except OSError as exc:
        print(f"error: --project {args.project}: {exc}", file=sys.stderr)
        return 1

    # Explicit --db/--sources always win over the ambient ./ariadne.yaml
    # (shared resolution, ADR-0010); the legacy default fills in only when
    # --db is not given (unused by the runtime whenever a registry applies).
    sources_path = default_registry_path(args.sources, args.db)
    db = args.db or "examples/retail-demo/data/demo.db"

    def _new_runtime() -> AriadneRuntime:
        return AriadneRuntime(
            args.semantic,
            args.context,
            db,
            staging_dir=args.staging,
            sources=sources_path,
        )

    facade: FacadeSource
    try:
        facade = _new_runtime()
    except RuntimeError as exc:  # fail fast before any MCP traffic
        if not _missing_served_models(exc):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if _mcp_sdk_absent():
            # Without the optional transport there is no authoring tool surface
            # to protect, and the local ariadne-authoring CLI still works — the
            # startup failure itself is the honest report (the install hint
            # never masks it; spec 2026-09-23-0001 §7).
            print(f"error: {exc}", file=sys.stderr)
            return 1
        # Empty, not-yet-promoted project: authoring still starts (spec
        # 2026-09-24-0005); the first query tool call re-attempts
        # construction — surfacing the same missing-served-model error
        # until the project is promoted, memoized once it succeeds.
        memo: list[AriadneRuntime] = []

        def lazy_facade() -> AriadneRuntime:
            if not memo:
                memo.append(_new_runtime())
            return memo[0]

        facade = lazy_facade
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        app = build_app(facade)  # project anchored by the launch chdir above
    except ModuleNotFoundError as exc:  # the optional transport is not installed
        if _mcp_missing(exc):
            print(
                f"error: {exc} — the MCP transport is an optional extra; "
                "install it with: pip install 'ariadne[mcp]'",
                file=sys.stderr,
            )
            return 1
        raise
    app.run()  # stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
