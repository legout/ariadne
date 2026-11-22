"""MCP adapter: three tool registrations over one core (spec
2026-10-02-0009 §6, issue #38/G6; ADR-0002's facade decision as amended by
ADR-0016 — tool-surface separation, never a new account system).

All query behavior — compilation, execution, context attachment and grain
checks — lives in :class:`ariadne.query.QueryRuntime`; this module registers
tools over the project-bound runtime factory and parses server arguments.
Answer examples are proposal artifacts: ``save_example`` and
``search_examples`` use the same Git candidate and human admission as other
authored content, with no separate review store. Authoring behavior lives in
:class:`ariadne.authoring.AuthoringProject`; this adapter adds thin
``authoring_``-prefixed wrappers.

The three registrations:

- **analyst** — the Query operations under their established names:
  ``list_metrics``, ``search_context``, ``get_metric``, ``list_datasets``,
  ``define_metric`` (ad-hoc), ``query_metrics``/``query_detail``,
  ``save_example``/``search_examples``, ``resolve_term``
  (issue #42: shared terminology resolution over the pinned admitted
  context; issue #44/K4 reports claim/confirmation status and AS-OF evidence
  freshness, and serves a context-only admitted snapshot — no metrics yet —
  while metric tools surface the specific missing-catalog error),
  ``list_context_pages``/``read_context_page``: token-free listing and
  path-addressed reading of the admitted Context snapshot — read-only.
  No authoring operation.
- **authoring** — the draft authoring contract with one stable prefix, acting on the
  ONE active draft (spec 0040): ``authoring_read_artifact``,
  ``authoring_edit_proposal`` (typed artifact edits, native page batches and typed
  source declarations — no proposal or base IDs), ``authoring_inputs``,
  ``authoring_refresh_schema``, ``authoring_inspect_mapping``,
  ``authoring_resolve_term`` and ``draft_status``. No query operation; the
  registration starts without a governed catalog (AC5).
- **combined** (the ``ariadne-serve`` default) — their union.

No MCP tool approves, rejects, discards, grants a source or confirms a mapping;
validation, approval and discard are human CLI commands (``ariadne validate`` /
``approve`` / ``draft discard``). There is no complete-bundle submission, staged
project, or separate Example-review registration. Tool arguments never select a
project root, worktree path or credential.

The server is launched for ONE locally configured Git project (``--project
DIR``): tool arguments cannot select another project or source credentials,
and stdio needs no bearer token. Governed query operations use the project's
exact human-admitted snapshot. Without a valid admission, query calls refuse;
the Authoring/Combined surfaces remain available for proposal work.

The opt-in Streamable HTTP transport keeps loopback as the default.
``--http-container --http-host 0.0.0.0`` explicitly permits a container-network
bind (owner, 2026-10-10). Every HTTP request, including health/readiness probes,
requires the server-held ``ARIADNE_HTTP_TOKEN`` bearer token. Without ``--http``
nothing listens. Deployment and private HTTPS termination retain separate
approval; a container bind must not be published directly to the host.

Routing contract: fresh consuming agents discover the ad-hoc
path through the facade itself — the tool descriptions carry the same routing
language ``list_metrics`` and the unknown-metric error use (the MCP registry is
the agent's map).

Usage::

    python -m ariadne.serve --project /path/to/project            # combined
    python -m ariadne.serve --project DIR --toolset analyst       # Query only
    python -m ariadne.serve --project DIR --toolset authoring     # no queries
    ariadne-analyst-mcp --project DIR   # the same adapter, toolset fixed
    ariadne-authoring-mcp --project DIR
"""

import argparse
import functools
import hmac
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from ariadne import draft as draft_module

# The transport-neutral authoring service (plan §2's Authoring call contract):
# one import, the tool bodies are one-line delegations with its verbatim
# contracts.
from ariadne import (
    query_results,  # pyright: ignore[reportAttributeAccessIssue] — drift: analyzer binds the venv copy lacking this lane's new module
)
from ariadne.authoring import AuthoringProject
from ariadne.discovery import DiscoveryRuntime, _DiscoverySession
from ariadne.execution import DeadlineBudget  # pyright: ignore[reportMissingImports] — drift

# The grain guidance constant lives in ariadne.grain; it stays importable from
# this module for backward compatibility (tests import it from here).
from ariadne.grain import GRAIN_GUIDANCE  # noqa: F401 — re-export
from ariadne.query import (  # pyright: ignore[reportMissingImports] — drift
    DeferredQueryRuntime,
    QueryRuntime,
    _QueryRuntimeSession,
)
from ariadne.query_results import QueryResultError  # pyright: ignore[reportMissingImports] — drift

FacadeSource = (
    QueryRuntime | _QueryRuntimeSession | DeferredQueryRuntime | Callable[[], _QueryRuntimeSession]
)

# The three registrations: Query under its established names, the
# authoring contract under one stable prefix, and their union.
TOOLSETS = ("analyst", "authoring", "combined")

# The opt-in local-only HTTP transport: the operator's bearer
# token lives in the SERVER environment only — never in ariadne.yaml, a tool
# response or a log. Stdio never reads it.
HTTP_TOKEN_ENV = "ARIADNE_HTTP_TOKEN"

# Loopback remains the default; only explicit container mode permits 0.0.0.0.
HTTP_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# the explicit nested input schema of the
# query_records tool — discovery-grade JSON Schema for the record request
# contract (dataset/fields/filters/timestamp/order/limit with defaults,
# supported operators and the overflow policy), so Analyst/Combined clients
# can distinguish record selection from metric aggregation and admitted
# detail before calling. The core's strict validation remains the gate: this
# schema is documentation the adapter serves, not a transport filter.
_QUERY_RECORDS_REQUEST_SCHEMA: dict = {
    "type": "object",
    "description": (
        "One bounded record request (spec 0014 §3): a requested top-N selection "
        "of records from one known catalog dataset — never SQL, never a metric. "
        "Overflow policy: row/cell/byte/deadline guards refuse all-or-nothing "
        "(spec 0014 §§4–5); narrow the request or selected fields to fit."
    ),
    "properties": {
        "dataset": {
            "type": "string",
            "description": (
                "One exact known catalog dataset as listed by list_datasets() "
                "(or its canonical ariadne://table/ resource when a display name "
                "is ambiguous). Resolved to the built catalog; never SQL text."
            ),
        },
        "fields": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
            "description": (
                "Known physical columns of the dataset; duplicates are removed "
                "keeping the first occurrence. No *, expressions or traversal."
            ),
        },
        "filters": {
            "type": "array",
            "description": "Optional AND-combined predicates.",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "A known column."},
                    "op": {
                        "type": "string",
                        "enum": [
                            "=",
                            "!=",
                            "<",
                            "<=",
                            ">",
                            ">=",
                            "in",
                            "is_null",
                            "is_not_null",
                            "regex",
                        ],
                        "description": (
                            "comparison/in/regex require a value; is_null/"
                            "is_not_null take none. Strings are capped at 4,096 "
                            "characters, IN lists at 100 values. Regex uses "
                            "DuckDB's regexp_matches semantics (case-sensitive "
                            "unless the pattern syntax says otherwise), always "
                            "a literal."
                        ),
                    },
                    "value": {
                        "description": (
                            "The predicate value (omit for is_null/is_not_null); "
                            "a timestamp comparison on the declared timestamp "
                            "field is interpreted under its declared clock."
                        )
                    },
                },
                "required": ["field", "op"],
            },
        },
        "timestamp": {
            "type": "object",
            "description": (
                "Optional typed normalization of ONE identified temporal field; "
                "mandatory when ordering the documented VARCHAR as time. "
                "Revision 1 supports exactly the %Y-%m-%d %H:%M:%S encoding: "
                "wall times in the declared IANA timezone normalize to instants "
                "(rows keep the original selected value); malformed, nonexistent "
                "and ambiguous wall times refuse, never a fold/offset guess."
            ),
            "properties": {
                "field": {"type": "string", "description": "The temporal column."},
                "format": {
                    "type": "string",
                    "enum": ["%Y-%m-%d %H:%M:%S"],
                    "description": "Revision 1's one documented encoding.",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name, e.g. Europe/Berlin.",
                },
            },
            "required": ["field", "format", "timezone"],
        },
        "order": {
            "type": "array",
            "minItems": 1,
            "description": (
                "Required, nonempty; every key sorts NULLS LAST. Remaining "
                "selected sortable columns follow in field-list order as the "
                "disclosed deterministic tie order."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "A known column."},
                    "direction": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "default": "asc",
                    },
                },
                "required": ["field"],
            },
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 10,
            "description": (
                "The requested top-N; at most the effective host row ceiling. "
                "Booleans are not integers."
            ),
        },
    },
    "required": ["dataset", "fields", "order"],
    "additionalProperties": False,
}
_QUERY_RECORDS_INPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {"request": _QUERY_RECORDS_REQUEST_SCHEMA},
    "required": ["request"],
}


# ---- issue #56/S1: the MCP adapter's actual-representation
# preflight and structured tool refusal. The CORE never imports MCP; these
# helpers do, and only when the optional transport is in use.

# The framing id reserve: the measure frames every
# envelope with a QUOTED UUID-LENGTH STRING id (38 serialized bytes) instead
# of the 1-byte ``id=1`` — a bounded worst-case id representation. Any client
# id whose serialized form is at most a UUID string (every integer id up to
# 2^63 and every UUID-string id) is therefore fully counted; the reserve is
# a conservative headroom, and no request id of a supported shape can make
# the actual envelope LARGER than the measured one by more than nothing.
_RESERVED_REQUEST_ID = "00000000-0000-0000-0000-000000000000"


def _wire_bytes(call_result) -> int:
    """The exact serialized size of the JSON-RPC message the installed MCP
    SDK puts on the wire for one ``CallToolResult`` (mcp 2.2.0, verified
    against captured stdio/HTTP frames): the kernel dumps the result model
    ``call_result.model_dump(by_alias=True, mode="json", exclude_none=True)``
    into ``JSONRPCResponse``, and the stdio/SSE writers serialize the response
    through ``model_dump_json(by_alias=True, exclude_unset=True)``. The
    negotiated protocol era shapes the result dict: the handshake wire (every
    SDK ``initialize`` client) sieves away ``resultType`` and ``_meta``, while
    the 2026-07-28 modern sieve keeps ``resultType`` and stamps the
    ``serverInfo`` ``_meta`` (runner ``_serialize``/``_stamp_server_info``).
    The measure models the MODERN form — strictly the larger of the two — so
    a near-ceiling payload cannot overflow on either wire."""
    from mcp.types import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
        SERVER_INFO_META_KEY,
        JSONRPCResponse,
    )

    result = call_result.model_dump(by_alias=True, mode="json", exclude_none=True)
    # the modern-era stamp this server (MCPServer("ariadne"), version "") adds
    result["_meta"] = {SERVER_INFO_META_KEY: {"name": "ariadne", "version": ""}}
    response = JSONRPCResponse(
        jsonrpc="2.0",
        id=_RESERVED_REQUEST_ID,
        result=result,
    )
    return len(response.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8"))


def _mcp_result_bytes(result: dict) -> int:
    """The exact serialized size of the tool-result envelope the installed
    MCP SDK would put on the wire for this dict (spec 0014 §4 guard 5 / plan
    §1 blocking evidence): MCPServer converts a dict return (its output model
    is disabled on the measured tools) to one TextContent whose text is
    ``pydantic_core.to_json(result, fallback=str, indent=2)`` (mcp 2.2.0
    ``func_metadata._convert_to_content``, the retained 1.x conversion),
    and the result handler wraps it into ``CallToolResult`` — so the
    envelope duplicates the response as ESCAPED text inside the outer JSON,
    which is strictly larger than the inner dict. Measured on the SDK's own
    models; never re-serialized differently after preflight."""
    import pydantic_core  # pyright: ignore[reportMissingImports] — the [mcp] extra ships it
    from mcp.types import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
        CallToolResult,
        TextContent,
    )

    text = pydantic_core.to_json(result, fallback=str, indent=2).decode()
    call_result = CallToolResult(content=[TextContent(type="text", text=text)], is_error=False)
    return _wire_bytes(call_result)


def _mcp_refusal_result(exc: QueryResultError):
    """The structured MCP tool refusal: ``isError: true`` with
    the bounded refusal as BOTH escaped text and structured content — never a
    successful partial tool answer. MCPServer passes a returned
    ``CallToolResult`` through ``convert_result`` untouched (mcp 2.2.0), and
    the result handler wraps it verbatim."""
    return _refusal_call_result(exc.refusal())


def _refusal_call_result(refusal: dict):
    """The isError CallToolResult for one refusal body dict (fix pass 1,
    finding 2a: the refusal-form battery measures THIS shape — the text+
    structured duplication, not just the inner dict)."""
    from mcp.types import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
        CallToolResult,
        TextContent,
    )

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(refusal, indent=2))],
        structured_content=refusal,
        is_error=True,
    )


def _refusal_envelope_bytes(refusal: dict) -> int:
    """Wire bytes of one refusal body in its actual isError representation."""
    return _wire_bytes(_refusal_call_result(refusal))


def _mcp_error_envelope_bytes(tool_name: str, exc: BaseException) -> int:
    """Wire bytes of the tool-error result the installed SDK ACTUALLY emits
    for a raised exception: for a ``ToolError`` mcp
    2.2.0's result handler returns ``CallToolResult(content=[TextContent(
    text=str(exc))], is_error=True)`` — NOT a JSONRPCError — and the tool
    wrapper's message is ``Error executing tool {name}: {exc}``, serialized
    through the same ``JSONRPCResponse`` path as every result. The adapter
    re-raises fitting generic errors as ``ToolError(str(exc))`` because the
    2.x wrapper DROPS the text of bare crashes; the modeled form is the
    emitted one (probe-confirmed against captured frames)."""
    from mcp.types import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
        CallToolResult,
        TextContent,
    )

    call_result = CallToolResult(
        content=[TextContent(type="text", text=f"Error executing tool {tool_name}: {exc}")],
        is_error=True,
    )
    return _wire_bytes(call_result)


def _bounded_tool_error(tool_name: str, exc: BaseException, mcp_budget: float):
    """Fix pass 1, finding 2c: a FITTING generic error keeps
    the SDK's verbatim error path (return None to re-raise); an oversized
    error representation is replaced by the bounded explicit refusal."""
    if _mcp_error_envelope_bytes(tool_name, exc) <= mcp_budget:
        return None
    return _refusal(query_results.oversized_error_refusal())


def _refusal(exc: QueryResultError):
    """The four bounded query tools' shared refusal branch."""
    return _mcp_refusal_result(exc)


def _typed_navigation_result(tool, result, project):
    """A typed navigation tool's fitting/oversized outcome (A2, spec0029
    §1.3): the envelope is measured on the REAL SDK conversion — the
    registered Tool's native ``fn_metadata.convert_result`` CallToolResult
    through ``_wire_bytes`` (protocol stamp included) — never the dict-tool
    helper, which assumes ``structured_output=False``. Oversized required
    content refuses whole; the returned isError ``CallToolResult`` passes
    through ``convert_result`` untouched."""
    budget = query_results.load_host_query_limits(project)["mcp_response_bytes"]
    size = _wire_bytes(tool.fn_metadata.convert_result(result))
    if size > budget:
        return _refusal(
            query_results.mcp_byte_limit_refusal(
                budget, observed={"transport_bytes_lower_bound": size}
            )
        )
    return result


def _refuse_unrepresentable_mcp_ceiling(project):
    """The source-free navigation transport gate (A2, spec0029 §1.3 + spec
    0014 §5): the host's MCP envelope ceiling must represent every bounded
    refusal form BEFORE navigation runs — an unusably small
    mcp_response_bytes is a configuration error raised here, never answered
    with an over-budget refusal. The QueryRuntime registration seam performs
    the same check when a runtime exists; navigation constructs none."""
    budget = query_results.load_host_query_limits(project)["mcp_response_bytes"]
    for form in query_results.refusal_forms():
        size = _refusal_envelope_bytes(form)
        if size > budget:
            raise ValueError(
                "the host query limits' mcp_response_bytes="
                f"{budget} cannot represent every refusal form on this transport (largest {size} "
                "bytes) — nothing could ever be answered or refused"
            )


def build_app(facade: FacadeSource, *, project: str | Path = ".", toolset: str = "combined"):
    """Wire one tool registration of the shared core onto one MCP stdio
        server: ``analyst`` registers the Query operations, ``authoring``
        the ``authoring_``-prefixed Git authoring contract, ``combined`` (the
    default, the historic facade) their union — and never source approval,
    admission or reconciliation.

        ``project`` is the ONE configured project root the authoring tools operate
        on; the default is the current directory because :func:`main` chdir'd into
        the ``--project`` root at launch (direct in-process callers pass theirs).
        Model arguments carry only proposal/artifact identities, revisions and
        content — never paths, worktrees or credentials."""
    if toolset not in TOOLSETS:
        raise ValueError(f"unknown toolset {toolset!r}; this build serves {TOOLSETS}")
    from mcp.server.mcpserver import (  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
        MCPServer,  # mcp 2.x: FastMCP became mcp.server.mcpserver.MCPServer
    )
    from mcp.server.mcpserver.exceptions import (  # pyright: ignore[reportMissingImports] — [mcp] extra
        ToolError,
    )
    from mcp.server.mcpserver.tools import (  # pyright: ignore[reportMissingImports] — [mcp] extra
        Tool,  # explicit tool registration (the query_records nested schema)
    )
    from mcp.types import (  # pyright: ignore[reportMissingImports] — [mcp] extra
        CallToolResult,
    )

    app: MCPServer = MCPServer("ariadne")

    def _tool_errors(fn):
        """mcp 2.2.0's tool wrapper reports a BARE exception as a crash and
        DROPS its text from the client-visible error result; re-raising it as
        ToolError keeps the 1.x public semantics — the SDK's own verbatim
        error path then reads ``Error executing tool <name>: <message>``.
        Refusals are returned CallToolResult values, not exceptions, and pass
        through untouched (spec 0026 §3: exact public tool/error semantics)."""

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                raise ToolError(str(exc)) from exc

        return wrapped

    # ---------------------- the Query registration (analyst, combined) ------

    if toolset in ("analyst", "combined"):

        def _runtime() -> _QueryRuntimeSession:
            """The query runtime — a live instance, or the launch-time factory
            (empty project: the authoring tools work, query calls surface the
            construction error). Fix pass 1, finding 6: the DEFAULT MCP
            response measure is established HERE — at the registration seam —
            for BOTH instance and factory callers (a factory's runtimes get it
            as they are constructed), so every MCP result operation gets the
            envelope preflight however the app was built; an explicitly set
            measure still wins (this only fills a missing one, once per
            runtime, together with the one-time refusal-representability check
            on this transport)."""
            if facade is QueryRuntime:
                runtime: _QueryRuntimeSession = QueryRuntime.open_project(project)
            elif isinstance(facade, DeferredQueryRuntime):
                runtime = cast(DeferredQueryRuntime, facade).runtime()
            elif isinstance(facade, _QueryRuntimeSession):
                runtime = facade
            elif callable(facade):
                runtime = cast(Callable[[], _QueryRuntimeSession], facade)()
            else:
                raise TypeError("facade must be a Git-project query factory or runtime")
            if runtime._measure is None:
                runtime._measure = _mcp_result_bytes
                for form in query_results.refusal_forms():
                    size = _refusal_envelope_bytes(form)
                    if size > runtime._limits["mcp_response_bytes"]:
                        raise ValueError(
                            "the host query limits' mcp_response_bytes="
                            f"{runtime._limits['mcp_response_bytes']} cannot represent "
                            f"every refusal form on this transport (largest {size} "
                            "bytes) — nothing could ever be answered or refused"
                        )
            return runtime

        def _tool_mcp_budget() -> float:
            """The effective MCP envelope ceiling for bounding GENERIC tool
            errors: the live runtime's host limits
            when reachable — even mid-construction failure — else the built-in."""
            try:
                return _runtime()._limits["mcp_response_bytes"]
            except Exception:
                return query_results.DEFAULT_QUERY_LIMITS["mcp_response_bytes"]

        # --- the five query/ad-hoc tools (unchanged) ---

        @app.tool()
        @_tool_errors
        async def discover(query: str, limit: int = 5) -> dict:
            """Discover metrics, pages, terms, examples and contracts without opening sources.

            Five native groups, snapshot-bound as-of contract evidence and bounded
            term continuation; never executes an answer or authorizes a join.
            """
            _refuse_unrepresentable_mcp_ceiling(project)
            discovery = DiscoveryRuntime.open_project(project)
            result = await discovery.discover(query, limit=limit)
            # the assembled report (with its embedded SDK
            # pages) is a typed navigation result too — measured on its real
            # SDK conversion, refusing whole when it cannot fit.
            return _typed_navigation_result(app._tool_manager._tools["discover"], result, project)

        @app.tool()
        @_tool_errors
        async def list_metrics() -> list[dict | str]:
            """List served governed metrics with descriptions and available dimensions.

            The response ends with a routing hint: questions no listed metric answers
            go to list_datasets() + define_metric (the ad-hoc path).
            """
            return await _runtime().list_metrics()

        @app.tool()
        @_tool_errors
        async def search_context(query: str) -> list[dict]:
            """Search only Context pages from the admitted Git snapshot."""
            # source-free discovery, never the query
            # runtime; the typed result is measured on its real conversion.
            _refuse_unrepresentable_mcp_ceiling(project)
            discovery = DiscoveryRuntime.open_project(project)
            result = await discovery.search_context(query)
            return _typed_navigation_result(
                app._tool_manager._tools["search_context"], result, project
            )

        @app.tool()
        @_tool_errors
        async def list_context_pages() -> list[dict]:
            """List Context metadata from the admitted Git snapshot."""
            _refuse_unrepresentable_mcp_ceiling(project)
            discovery = DiscoveryRuntime.open_project(project)
            result = await discovery.list_context_pages()
            return _typed_navigation_result(
                app._tool_manager._tools["list_context_pages"], result, project
            )

        @app.tool()
        @_tool_errors
        async def read_context_page(path: str) -> dict:
            """Read one exact page from the admitted Context snapshot.

            Args:
                path: the exact relative .md path from list_context_pages or a
                    search_context hit (e.g. policies/emea-currency-cutover.md).
            """
            _refuse_unrepresentable_mcp_ceiling(project)
            discovery = DiscoveryRuntime.open_project(project)
            result = await discovery.read_context_page(path)
            return _typed_navigation_result(
                app._tool_manager._tools["read_context_page"], result, project
            )

        @app.tool(structured_output=False)
        @_tool_errors
        async def get_metric(
            name: str, dimensions: list[str] | None = None, range: dict | None = None
        ) -> dict | CallToolResult:
            """Rows plus compiled SQL for a named governed metric — never raw SQL.

            The response carries a context field: the full served OKF metric page
            plus the full bodies of every policy it cites. Report those caveats
            with every number (context is null-shaped when no page is served yet).

            Args:
                name: governed metric name (see list_metrics).
                dimensions: dimensions to group by (e.g. ["region"]).
                range: optional {"start", "end"} dates on the primary date dimension.
            """
            try:
                runtime = _runtime()
                return await runtime.get_metric(name, dimensions, range)
            except QueryResultError as exc:  # isError + refusal
                return _refusal(exc)
            except Exception as exc:  # fitting errors keep
                bounded = _bounded_tool_error(  # the SDK's verbatim error path; an
                    "get_metric",
                    exc,
                    _tool_mcp_budget(),  # oversized representation is replaced
                )
                if bounded is not None:
                    return bounded
                raise

        @app.tool()
        @_tool_errors
        async def list_datasets() -> list[dict]:
            """List the approved live catalog with its actual columns and types.

            Requires ordinary admission/source approval; this is not offline.
            Matching contract annotations come from the pinned snapshot without
            additional source reads or a second contract inspection.

            Pairs with define_metric: pick tables here, then define an ad-hoc metric
            for any question no governed metric answers. For bounded record
            selection over one table (no aggregation, no staging), pass the table
            to query_records instead.
            """
            return await _runtime().list_datasets()

        @app.tool(structured_output=False)
        @_tool_errors
        async def define_metric(definition: dict) -> dict | CallToolResult:
            """Define and execute an ad-hoc metric for a question no governed metric answers.
            It runs read-only and is not saved; explicit retention uses existing Authoring edits.

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
                    errors verbatim; nothing is saved or executed. Success returns rows,
                    the compiled SQL (provenance), governed: false, the echoed definition,
                    and persistence: {status: not_saved}. To retain a definition, use the
                    existing revision-checked Authoring workflow; no save flag is added.
            """
            try:
                runtime = _runtime()
                return await runtime.define_metric(definition)
            except QueryResultError as exc:  # refusal saves no authored artifact
                return _refusal(exc)
            except Exception as exc:  # fitting errors keep
                bounded = _bounded_tool_error(  # the SDK's verbatim error path; an
                    "define_metric",
                    exc,
                    _tool_mcp_budget(),  # oversized representation is replaced
                )
                if bounded is not None:
                    return bounded
                raise

        @app.tool(structured_output=False)
        @_tool_errors
        async def query_metrics(request: dict) -> dict | CallToolResult:
            """Query one or more governed metrics TOGETHER over the admitted multi-fact
            graph: each fact aggregates at its own grain and the branches align on
            conformed keys — a raw fact-to-fact join never executes. Same contract as
            ``ariadne query-metrics``. Only predefined metric names: never raw SQL.
            Requires the graph in the exact Git snapshot to be admitted by a human;
            an unadmitted or hand-edited graph refuses with that reason.

            The response carries rows, the compiled single-SELECT SQL, a bounded
            lineage plan (fact branches, joins, conformed keys, filters, windows,
            performed audits), per-metric OKF metric page + cited Policy bodies with
            the attestation state, and the local admission provenance. Report the
            caveats and the admission route with every number.

            Args:
                request: {metrics: [names], dimensions?: [names], filters?: [{field,
                    op, value}], segments?: [{name, filters}], parameters?: {name:
                    {type, value, min?, max?, max_length?}}, order?: [{field,
                    direction}], limit?: int, time?: {dimension, grain, start, end}}.
            """
            try:
                runtime = _runtime()
                return await runtime.query_metrics(request)
            except QueryResultError as exc:  # isError + refusal
                return _refusal(exc)
            except Exception as exc:  # fitting errors keep
                bounded = _bounded_tool_error(  # the SDK's verbatim error path; an
                    "query_metrics",
                    exc,
                    _tool_mcp_budget(),  # oversized representation is replaced
                )
                if bounded is not None:
                    return bounded
                raise

        @app.tool(structured_output=False)
        @_tool_errors
        async def query_detail(request: dict) -> dict | CallToolResult:
            """Project one declared root dataset's fields through safe
            many-to_one/one_to_one lookup paths — no aggregates, no fan-out: exactly
            one row per root key. Same contract as ``ariadne query-detail``, over the
            same admitted graph (an unadmitted graph refuses). For bounded record
            selection over one physical table with no aggregation or admission
            requirement, use query_records instead.

            Args:
                request: {dataset: the root dataset name, fields: [field names]} — a
                    field lives on the root directly or on a dataset reachable from
                    it through proven unique-target paths; child-side fields refuse.
            """
            try:
                runtime = _runtime()
                return await runtime.query_detail(request)
            except QueryResultError as exc:  # isError + refusal
                return _refusal(exc)
            except Exception as exc:  # fitting errors keep
                bounded = _bounded_tool_error(  # the SDK's verbatim error path; an
                    "query_detail",
                    exc,
                    _tool_mcp_budget(),  # oversized representation is replaced
                )
                if bounded is not None:
                    return bounded
                raise

        async def _query_records(request: dict) -> dict | CallToolResult:
            """Select a bounded top-N of records from ONE known catalog table —
            an Ad-hoc Record Query: no aggregation, no admitted
            graph, no staging, and every answer reports governed: false with
            truthful bounded provenance. Use query_metrics for governed metric
            aggregation over the admitted graph, query_detail for an admitted
            root-dataset projection through proven lookup paths. This tool's
            description prose never becomes WHERE/ORDER/LIMIT — the request
            contract below is the only filter surface.

            Args:
                request: the record request — dataset (one exact known catalog
                    dataset or its canonical ariadne://table/ resource, never SQL),
                    fields (nonempty known physical columns, no * or expressions),
                    optional filters (AND-combined: =, !=, <, <=, >, >=, in, is_null,
                    is_not_null, regex — comparison/in/regex need a value, strings
                    capped at 4,096 characters, IN at 100 values), optional
                    timestamp (one declared field's wall-time interpretation: the
                    documented %Y-%m-%d %H:%M:%S encoding plus an IANA timezone;
                    malformed, nonexistent and ambiguous values refuse), required
                    order (nonempty known columns, asc/desc default asc, every key
                    NULLS LAST, remaining selected columns appended as the
                    disclosed deterministic tie order), optional limit (default 10,
                    positive integer, at most 1,000 and the host row ceiling).
                    Overflow policy: row/cell/byte/deadline guards refuse the
                    whole answer all-or-nothing rather than returning a partial
                    prefix; narrow the request to fit.
            """
            try:
                runtime = _runtime()
                return await runtime.query_records(request)
            except QueryResultError as exc:  # isError + refusal
                return _refusal(exc)
            except Exception as exc:  # fitting errors keep
                bounded = _bounded_tool_error(  # the SDK's verbatim error path; an
                    "query_records",
                    exc,
                    _tool_mcp_budget(),  # oversized representation is replaced
                )
                if bounded is not None:
                    return bounded
                raise

        # Explicit discoverable nested request schema: the
        # docstring gives prose; this JSON Schema is what clients enumerate —
        # discovery-only. The tool keeps a plain dict parameter so transport
        # typing never coerces invalid numeric/boolean values or drops unknown
        # keys before the core's strict validation.
        record_tool = Tool.from_function(
            _tool_errors(_query_records), name="query_records", structured_output=False
        )
        record_tool.parameters = _QUERY_RECORDS_INPUT_SCHEMA
        app._tool_manager._tools["query_records"] = record_tool  # mcp 2.2.0 manager seam

        # --- the two answer-example tools ---
        # Thin adapters over the runtime's transport-neutral save/search (issue
        # #19): the local JSON CLI rides the exact same runtime methods, so a
        # draft saved over one transport is immediately searchable over the other;
        # Example artifacts share normal proposal review and Git Admission.

        @app.tool()
        @_tool_errors
        async def save_example(
            submission: dict,
            proposal: str | None = None,
            expected_revision: str | None = None,
        ) -> dict:
            """Save one explicit answer example as an unadmitted Git proposal draft —
            an EXPLICIT user-confirmed submission only:
            present the bounded record (result excerpt/digest, method/arguments,
            question/interpretation/parameters, the EXACT submitted result SQL
            text — the sql_provenance the save will retain verbatim, so the user
            can assess sensitive literals —, sources, submitter attestation)
            for user confirmation BEFORE calling this. Never a governed write or
            admission, and never transcript harvesting; nothing about the example changes
            the served catalog. Same contract as ``ariadne save-example``.

            Args:
                submission: {question, interpretation, parameters?, method:
                    {operation: get_metric|define_metric, arguments}, result: the
                    observed Ariadne envelope (metric/sql/columns/rows/governed),
                    submitter (self-declared), attestation, sources: cited admitted
                    metric/Policy paths}. Malformed input stores nothing.
                proposal: an existing candidate ID; omit to start a new proposal.
                expected_revision: the exact current candidate revision; required with proposal.
            """
            discovery = DiscoveryRuntime.open_project(project)
            # source-free authoring — the source builder is
            # never constructed for an Example save.
            return discovery.save_example(
                submission, proposal=proposal, expected_revision=expected_revision
            )

        @app.tool()
        @_tool_errors
        async def search_examples(
            query: str,
            limit: int = 10,
            include_history: bool = False,
            include_sql: bool = False,
            proposal: str | None = None,
            revision: str | None = None,
        ) -> list[dict]:
            """Search saved answer examples as labeled references (draft/stable,
            staleness, provenance, path) — historical evidence to check a METHOD
            against, never a cached answer. Similar words are not equivalence:
            compare dates, filters, grain, metric identity and served Policies,
            and rerun fresh. Never executes a query. Same contract as
            ``ariadne search-examples``; stale/closed records stay history unless
            include_history is set.

            Args:
                query: terms ranked against question/interpretation.
                limit: maximum records returned.
                proposal: explicitly select one Git authoring candidate; requires revision.
                revision: the proposal's exact current candidate commit.
                include_history: include stale/superseded/rejected records, labeled.
                include_sql: additionally return each hit's stored sql_provenance
                    as provenance.sql — the EXACT submitted result SQL as
                    historical evidence (null when no submitted SQL was recorded);
                    never executed, never a ranking input, never wider history.
            """
            if (proposal is None) != (revision is None):
                raise ValueError("proposal and revision must be supplied together")
            if proposal is not None:
                assert revision is not None
                from ariadne import answer_examples

                return answer_examples.search_candidate(
                    project,
                    query,
                    proposal=proposal,
                    revision=revision,
                    limit=limit,
                    include_history=include_history,
                    include_sql=include_sql,
                )
            discovery = DiscoveryRuntime.open_project(project)
            return await discovery.search_examples(
                query, limit=limit, include_history=include_history, include_sql=include_sql
            )

        @app.tool()
        @_tool_errors
        async def resolve_term(request: str | dict, part: int = 1) -> dict:
            """Resolve one shared business term or an exact {resource, column}
            field lookup against the served (pinned admitted) context: bounded
            concept/representation matches with their EXACT field bindings,
            required scope, ambiguity, claim/confirmation status, AS-OF
            evidence freshness and actual page/source citations. A mapping is
            confirmed ONLY by recorded human admission evidence bound to the
            exact reviewed assertion; hypotheses stay unconfirmed leads.
            Whole aliases/phrases match case-insensitively
            (never substrings); field identity is exact. Read-only: no transform,
            no SQL rewrite, no join authority — a language alias never authorizes
            a join. Serves a context-only admitted snapshot too (no metrics yet).
            Same contract as ``ariadne resolve-term``.

            Args:
                request: the term string, or the exact field lookup
                    {resource, column} with a canonical ariadne://table/ resource.
                part: which bounded part of the matches (default 1; the response
                    carries total_matches/parts/truncated for continuation).
            """
            # INTEGRATED term resolution is
            # source-free — the pinned discovery session serves it through
            # the typed-result refusal-budget seam; the query runtime (and
            # any source connection) is never constructed for it, and the
            # routing check never constructs one either. The standalone
            # route keeps the EXACT supplied-facade handler path.
            from ariadne import admission as _admission

            record = _admission.load_current(Path(project))
            if record is not None and isinstance(record.get("bound_release"), dict):
                _refuse_unrepresentable_mcp_ceiling(project)
                discovery = DiscoveryRuntime.open_project(project)
                result = await discovery.resolve_term(request, part=part)
                return _typed_navigation_result(
                    app._tool_manager._tools["resolve_term"], result, project
                )
            return await _runtime().resolve_term(request, part=part)

    # ------------------ the Authoring registration (authoring, combined) ----

    if toolset in ("authoring", "combined"):
        # The project root below was fixed at server launch (--project); every
        # tool argument carries only proposal IDs, revisions, typed identities
        # and content — never a filesystem root, worktree or credential.
        authoring_api = AuthoringProject(Path(project).resolve())

        @app.tool()
        @_tool_errors
        async def authoring_read_artifact(
            kind: str,
            name: str | None = None,
            section: str | None = None,
            part: int = 1,
        ) -> dict:
            """Read one artifact of the ACTIVE DRAFT's current candidate revision, in
            bounded parts. Returns {proposal, revision, path, content, part, parts,
            chars, complete} or a specific missing-artifact error. There is no proposal
            or base ID: the project has one active draft (a first edit opens it).

            Args:
                kind: one of model, graph, page, seed_notes, contract, contract_bindings.
                name: artifact name (model/page/contract).
                section: OKF page section (page).
                part: which bounded part (default 1).
            """
            identity: dict = {"kind": kind}
            if name is not None:
                identity["name"] = name
            if section is not None:
                identity["section"] = section
            return authoring_api.draft_read(identity, part=part)

        @app.tool()
        @_tool_errors
        async def authoring_edit_proposal(edit: dict) -> dict:
            """Apply ONE typed edit to the active draft (the first edit opens it).
            Competing writers are arbitrated by the draft's generation and candidate
            revision: the loser is refused as stale and nothing is written. No
            proposal or base ID is accepted. Never approval.

            Args:
                edit: one typed JSON object — {kind: model, name, content}, {kind:
                    graph, content}, {kind: seed_notes, content}, {kind: contract,
                    name, content}, {kind: contract_bindings, content}, {kind: pages,
                    pages: [{path, content}]} (native knowledge pages), or {kind:
                    sources, entries: [...registry-shaped...], storages?} — a typed
                    source declaration: inert DATA, nothing is opened, and it grants
                    nothing; the human approves sources outside this surface.
            """
            result = authoring_api.apply_edit(edit)
            return {key: value for key, value in result.items() if key != "sources"} | (
                {"sources": result["sources"]} if "sources" in result else {}
            )

        @app.tool()
        @_tool_errors
        async def authoring_inputs(
            documents: list[str] | None = None,
            part: int = 1,
            sample_rows: int | None = None,
        ) -> dict:
            """The active draft's measured inputs (no model anywhere): the
            deterministic profile of the GRANTED source identities (an ungranted or
            changed entry is an explicit error), source-linked converted evidence for
            the referenced documents, and the draft's Seed Notes — each in bounded
            parts.

            Args:
                documents: operator-placed input-area references; at most 16 per call,
                    each inside the operator-configured roots.
                part: which bounded part of each document's converted text.
                sample_rows: optional positive per-table profile row bound.
            """
            return authoring_api.draft_inputs(
                documents=documents or [], part=part, sample_rows=sample_rows
            )

        @app.tool()
        @_tool_errors
        async def authoring_refresh_schema(assets: list[dict]) -> dict:
            """Regenerate the core-owned physical schema facts and Dataset Overviews of
            an EXPLICIT catalog asset list inside the active draft (reads only granted
            source identities). Authored meaning survives only for identical column
            identity/type; an identical refresh is a no-op. Never approval.

            Args:
                assets: catalog identity tuples {source, catalog, schema, table}
                    (catalog null for file views).
            """
            return authoring_api.draft_refresh_schema(assets)

        @app.tool()
        @_tool_errors
        async def authoring_inspect_mapping(candidate: dict, limits: dict | None = None) -> dict:
            """Measure one structured mapping-inspection candidate over the GRANTED
            source identities and retain the core receipt in the project evidence area
            (guarded read-only statements, operator-owned finite ceilings; a request may
            only LOWER them). Never a page edit, approval or admission.

            Args:
                candidate: the discriminated candidate object (family, ordered
                    left/right {resource, column} bindings, scope predicates).
                limits: optional REQUEST-LOWERED bounds.
            """
            return authoring_api.draft_inspect_mapping(candidate, limits=limits)

        @app.tool()
        @_tool_errors
        async def authoring_resolve_term(request: str | dict, part: int = 1) -> dict:
            """Resolve one shared business term or an exact {resource, column} field
            lookup against the ACTIVE DRAFT's current candidate revision — read-only,
            with the candidate identity visible: representations, bindings, scope,
            ambiguity and UNCONFIRMED claim status. No proposal ID.

            Args:
                request: the term string, or {resource, column} with a canonical
                    ariadne://table/ resource.
                part: which bounded part of the matches (default 1).
            """
            return authoring_api.resolve_term_in_draft(request, part=part)

        @app.tool()
        @_tool_errors
        async def draft_status() -> dict:
            """The active draft: generation, candidate revision, the served revision it
            is based on and whether it is stale; {draft: null} when none is open. Also
            reports the validation state of the current candidate. Read-only."""
            view = draft_module.status(authoring_api.project)
            if view is None:
                return {"draft": None}
            review = authoring_api.draft_review()
            return {**view, "validation": (review["report"] or {}).get("status", "unvalidated")}

    from starlette.responses import (  # pyright: ignore[reportMissingImports] — [mcp] extra
        JSONResponse,
    )

    @app.custom_route("/healthz", methods=["GET", "HEAD"])
    async def healthz(request):
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    @app.custom_route("/readyz", methods=["GET", "HEAD"])
    async def readyz(request):
        if toolset != "authoring":
            try:
                # Catalog discovery reuses admission checks, not a metric/data query.
                await _runtime().list_metrics()
            except Exception:
                return JSONResponse(
                    {"status": "not_ready"},
                    status_code=503,
                    headers={"Cache-Control": "no-store"},
                )
        return JSONResponse({"status": "ready"}, headers={"Cache-Control": "no-store"})

    return app


# ----------------------- opt-in HTTP transport ----------------


class BearerTokenGate:
    """A minimal pure-ASGI bearer gate over the MCPServer streamable-http app.

    The installed MCP SDK's own request-auth seam on ``streamable_http_app()``
    (``TokenVerifier`` + ``RequireAuthMiddleware`` + scope/RFC 9728 metadata
    routes) is OAuth resource-server machinery; ADR-0013 selected a plain
    server-held bearer token over OAuth, so this wrapper enforces it at the
    outermost ASGI seam instead: EVERY request — session bootstrap, tool
    listing, reads and dispatch — must carry ``Authorization: Bearer <token>``
    matching the exact server-held token or it fails 401 BEFORE the MCP session
    manager, any tool dispatch, or any project operation.
    The constant-time comparison never logs the token; the fixed rejection
    body discloses no project data. Non-HTTP scopes (uvicorn's lifespan, which
    runs the SDK session manager) pass through untouched."""

    _REJECT_BODY = b'{"error": "unauthorized"}'

    def __init__(self, wrapped, token: str) -> None:
        self._wrapped = wrapped
        self._token = token.encode()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._wrapped(scope, receive, send)
            return
        authorization = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                authorization = value
                break
        if (
            authorization is None
            or not authorization[:7].lower() == b"bearer "
            or not hmac.compare_digest(authorization[7:], self._token)
        ):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": self._REJECT_BODY})
            return
        await self._wrapped(scope, receive, send)


# Preserve the fixed MCP request-body ceiling after retiring document uploads.
MAX_HTTP_BODY_BYTES = (5 * 1024 * 1024 * 4 // 3) + 65_536


def build_http_app(
    app,
    token: str,
    *,
    host: str = "127.0.0.1",
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
):
    """The opt-in HTTP adapter: the SAME MCPServer app ``build_app``
    returned, served through the SDK's ``streamable_http_app()`` and wrapped in
    :class:`BearerTokenGate` — identical toolsets and contracts to stdio, one
    server-configured project, no second business logic.

    mcp 2.2.0 moved the transport seams out of mutable ``Settings`` into
    ``streamable_http_app()`` arguments: the body limit and the
    DNS-rebinding protection — loopback defaults plus the launch's explicit
    Host/Origin additions, never a disabled safeguard — are passed here."""
    # Keep the existing framing/security ceiling independently of any artifact
    # tool contract; removing uploads must not disable or enlarge this bound.
    from mcp.server.transport_security import (  # pyright: ignore[reportMissingImports] — [mcp] extra
        TransportSecuritySettings,
    )

    return BearerTokenGate(
        app.streamable_http_app(
            max_request_body_size=MAX_HTTP_BODY_BYTES,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[
                    "127.0.0.1:*",
                    "localhost:*",
                    "[::1]:*",
                    *(allowed_hosts or []),
                ],
                allowed_origins=[
                    "http://127.0.0.1:*",
                    "http://localhost:*",
                    "http://[::1]:*",
                    *(allowed_origins or []),
                ],
            ),
            host=host,
        ),
        token,
    )


def _serve_http(
    app,
    *,
    host: str,
    port: int,
    container: bool = False,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> int:
    """Serve HTTP with explicit bind permission and a server-held bearer token."""
    if host not in HTTP_LOOPBACK_HOSTS and not (container and host == "0.0.0.0"):
        print(
            f"error: --http-host {host}: default mode binds a loopback interface "
            "only; use --http-container --http-host 0.0.0.0 inside a private "
            "container network, with no published Ariadne host port",
            file=sys.stderr,
        )
        return 1
    token = os.environ.get(HTTP_TOKEN_ENV, "")
    if not token:
        print(
            f"error: --http requires the {HTTP_TOKEN_ENV} server-environment "
            "bearer token (never ariadne.yaml, a tool response or a log); no "
            "listener was opened",
            file=sys.stderr,
        )
        return 1
    import asyncio

    import uvicorn  # pyright: ignore[reportMissingImports] — [mcp] extra ships it

    # SDK DNS-rebinding protection stays on with the loopback defaults; the
    # launch's explicit Host/Origin additions ride through build_http_app's
    # supported 2.2.0 seam (spec 0026 §4: never a disabled safeguard).
    server = uvicorn.Server(
        uvicorn.Config(
            build_http_app(
                app,
                token,
                host=host,
                allowed_hosts=allowed_hosts,
                allowed_origins=allowed_origins,
            ),
            host=host,
            port=port,
            # no access log: request lines never carry project data, and the
            # token never appears in any log either way
            log_level="warning",
        )
    )
    asyncio.run(server.serve())
    return 0


def _mcp_missing(exc: BaseException) -> bool:
    """True only when the MCP SDK itself is absent: the failing
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
        "--toolset",
        choices=TOOLSETS,
        default="combined",
        help="which registration this server exposes (spec 2026-10-02-0009 §6; "
        "default combined, the historic facade union): analyst = the Query "
        "operations only; authoring = the authoring_ Git authoring contract "
        "only; combined = their union",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="OPT-IN Streamable HTTP transport (issue #18): serve the "
        "same toolsets on a loopback interface at /mcp with a bearer token from "
        f"the {HTTP_TOKEN_ENV} server environment enforced on every request; "
        "without this flag nothing listens (stdio remains the transport)",
    )
    parser.add_argument(
        "--http-host",
        default="127.0.0.1",
        help="loopback interface for --http (local-only mode: localhost, "
        "127.0.0.1 or ::1; 0.0.0.0 requires --http-container)",
    )
    parser.add_argument("--http-port", type=int, default=8000, help="TCP port for --http")
    parser.add_argument(
        "--http-container",
        action="store_true",
        help="allow 0.0.0.0 inside a private container network; do not publish "
        "the Ariadne port to the host; external clients require private HTTPS",
    )
    parser.add_argument(
        "--http-allowed-host",
        action="append",
        default=[],
        help="additional accepted HTTP Host (repeatable, e.g. ariadne:8000 or mcp.example.org)",
    )
    parser.add_argument(
        "--http-allowed-origin",
        action="append",
        default=[],
        help="additional accepted Origin (repeatable, e.g. https://mcp.example.org)",
    )
    args = parser.parse_args(argv)
    if not args.http and (
        args.http_container or args.http_allowed_host or args.http_allowed_origin
    ):
        parser.error("container/Host/Origin HTTP options require --http")

    # One project root anchors every Git-only operation, regardless of the
    # directory from which the server was launched.
    project = Path(args.project).resolve()
    try:
        os.chdir(project)
    except OSError as exc:
        print(f"error: --project {args.project}: {exc}", file=sys.stderr)
        return 1

    def _new_runtime(budget: DeadlineBudget | None = None) -> _QueryRuntimeSession:
        discovery = (
            cast(DeferredQueryRuntime, facade).discovery
            if isinstance(facade, DeferredQueryRuntime)
            else None
        )
        if discovery is not None and discovery._managed is None:
            discovery = None
        runtime = QueryRuntime.open_project(
            project,
            deadline_budget=budget,
            discovery=discovery,
        )
        # The MCP response measure belongs to the transport adapter, not core.
        if not _mcp_sdk_absent():
            for form in query_results.refusal_forms():
                size = _refusal_envelope_bytes(form)
                if size > runtime._limits["mcp_response_bytes"]:
                    raise ValueError(
                        "the host query limits' mcp_response_bytes="
                        f"{runtime._limits['mcp_response_bytes']} cannot represent every "
                        f"refusal form on this transport (largest {size} bytes) — tighten "
                        "nothing further"
                    )
            runtime._measure = _mcp_result_bytes
        return runtime

    def _new_discovery() -> _DiscoverySession:
        return DiscoveryRuntime.open_project(project)

    def _deferred_runtime() -> _QueryRuntimeSession:
        seconds = query_results.load_host_query_limits(project)["execution_seconds"]
        return _new_runtime(DeadlineBudget(seconds))

    facade: FacadeSource
    if args.toolset == "authoring":
        # Authoring-only never constructs a query runtime.
        def _no_runtime() -> _QueryRuntimeSession:
            raise RuntimeError("the authoring toolset registers no query tool")

        facade = _no_runtime
    else:
        facade = DeferredQueryRuntime(_deferred_runtime, _new_discovery)
    try:
        app = build_app(facade, toolset=args.toolset)  # project anchored by the chdir
    except ModuleNotFoundError as exc:  # the optional transport is not installed
        if _mcp_missing(exc):
            print(
                f"error: {exc} — the MCP transport is an optional extra; "
                "install it with: pip install 'ariadne-data[mcp]'",
                file=sys.stderr,
            )
            return 1
        raise
    if args.http:  # the OPT-IN local-only route; stdio needs no token
        return _serve_http(
            app,
            host=args.http_host,
            port=args.http_port,
            container=args.http_container,
            allowed_hosts=args.http_allowed_host,
            allowed_origins=args.http_allowed_origin,
        )
    app.run()  # stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
