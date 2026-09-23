"""MCP adapter: registers the five AriadneRuntime operations as stdio tools.

All behavior — compilation, execution, context attachment, grain checks,
proposal staging — lives in :class:`ariadne.runtime.AriadneRuntime`
(spec 2026-09-23-0001 §3, ADR-0012); this module only registers exactly five
MCP tools (spec §4) over one runtime instance and parses the server arguments.
``Facade`` remains import-compatible here as a plain alias of the runtime
class — never a subclass or wrapper that could diverge.

Routing contract (spec rev 4 §8.12): fresh consuming agents discover the ad-hoc
path through the facade itself — the tool descriptions carry the same routing
language ``list_metrics`` and the unknown-metric error use (the MCP registry is
the agent's map).

Usage::

    python -m ariadne.serve --db examples/retail-demo/data/demo.db \\
        --semantic semantic_layer --context context_layer
"""

import argparse
import sys

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


def build_app(facade: AriadneRuntime):
    """Wire the runtime onto an MCP stdio server: exactly five tools (spec §4)."""
    from mcp.server.fastmcp import (  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
        FastMCP,  # mcp<2 (pinned) exports FastMCP; the 2.x shim renames it
    )

    app: FastMCP = FastMCP("ariadne")

    @app.tool()
    async def list_metrics() -> list[dict | str]:
        """List served governed metrics with descriptions and available dimensions.

        The response ends with a routing hint: questions no listed metric answers
        go to list_datasets() + define_metric (the ad-hoc path).
        """
        return await facade.list_metrics()

    @app.tool()
    async def search_context(query: str) -> list[dict]:
        """Search the Context Layer (OKF pages) for business rules; ranked matches.

        Includes auto-staged ad-hoc proposals awaiting promotion; those hits are
        marked draft: true (served pages are draft: false).
        """
        return await facade.search_context(query)

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
        return await facade.get_metric(name, dimensions, range)

    @app.tool()
    async def list_datasets() -> list[dict]:
        """List every table in the attached database with its columns and types.

        Pairs with define_metric: pick tables here, then define an ad-hoc metric
        for any question no governed metric answers.
        """
        return await facade.list_datasets()

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
        return await facade.define_metric(definition)

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
        import mcp  # noqa: F401
    except ImportError:
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.serve",
        description="MCP stdio facade over the served context and semantic layers.",
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

    # Explicit --db/--sources always win over the ambient ./ariadne.yaml
    # (shared resolution, ADR-0010); the legacy default fills in only when
    # --db is not given (unused by the runtime whenever a registry applies).
    sources_path = default_registry_path(args.sources, args.db)
    db = args.db or "examples/retail-demo/data/demo.db"
    try:
        facade = AriadneRuntime(
            args.semantic,
            args.context,
            db,
            staging_dir=args.staging,
            sources=sources_path,
        )
    except Exception as exc:  # fail fast before any MCP traffic
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        app = build_app(facade)
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
