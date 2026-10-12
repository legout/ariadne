"""Analyst role tools: QueryRuntime's public operations as native tools.

Thin wrappers only (spec 2026-09-29-0006 session/role interface): compilation,
grain checks, read-only execution, context attachment, proposal staging and
terminology resolution all live in ``ariadneai``; nothing is reimplemented
here. The tool set is DELIMITED to Ariadne's baseline query operations plus
``resolve_term`` (issue #42/K2: shared terminology resolution over the pinned
admitted context — read-only, no inspection/edit authority) and the two
Context Layer browsing operations ``list_context_pages``/``read_context_page``
(issue #60, spec 0015/ADR-0020: token-free listing and path-addressed reading
of served and staged pages — read-only, draft-labeled): the wider Query
surface that ariadneai's MCP registrations expose (query_metrics/
query_detail, Answer Examples) does NOT silently expand this session's
permissions (issue #38/G6 — registrations are tool-surface separation).
Which runtime the session wraps — a managed Git project's pinned admission through
``QueryRuntime.open_project``, or an explicit legacy artifact root — is
resolved once at session open by :func:`ariadne_agent.session._open_runtime`.
Each tool's payload is the runtime's verbatim JSON envelope — values, served
metric page, full Policy bodies and citations, staging paths, lifecycle
``context_signals`` envelopes, and ``governed`` labels are never stripped or
summarized. Runtime failures
propagate with their verbatim message and are reported to the model as tool
errors. No CLI, no shell, no server, no raw SQL, no source-approval,
admission or Promotion tool.
"""

import json
from collections.abc import Mapping

from ariadne.query import QueryRuntime
from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult, ToolExecutor

TOOL_NAMES = (
    "list_metrics",
    "search_context",
    "get_metric",
    "list_datasets",
    "define_metric",
    "resolve_term",  # K2 (issue #42): alongside the five baseline tools
    "list_context_pages",  # spec 0015 (issue #60): token-free page listing
    "read_context_page",  # spec 0015 (issue #60): path-addressed page reading
)


def _payload(value: object) -> AgentToolResult:
    """One verbatim JSON payload — the runtime envelope is the whole contract."""
    return AgentToolResult(content=[TextContent(text=json.dumps(value, default=str))])


def analyst_tools(runtime: QueryRuntime) -> list[AgentTool]:
    """The Analyst tool set: Ariadne's five baseline query operations plus the
    K2 read-only term resolver (issue #42) — nothing else."""

    # Each wrapper mirrors the runtime's own signature and the routing language
    # the ariadneai MCP facade uses (spec rev 4 §8.12: fresh consuming agents
    # discover the ad-hoc path through the facade itself).
    async def list_metrics(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.list_metrics())

    async def search_context(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        limit = arguments.get("limit", 10)
        return _payload(await runtime.search_context(arguments["query"], limit))

    async def get_metric(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            await runtime.get_metric(
                arguments["name"], arguments.get("dimensions"), arguments.get("range")
            )
        )

    async def list_datasets(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.list_datasets())

    async def define_metric(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.define_metric(arguments["definition"]))

    async def resolve_term(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            await runtime.resolve_term(arguments["request"], part=arguments.get("part", 1))
        )

    async def list_context_pages(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.list_context_pages())

    async def read_context_page(
        tool_call_id: str, arguments: Mapping, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            await runtime.read_context_page(arguments["path"], draft=arguments.get("draft", False))
        )

    executor: dict[str, ToolExecutor] = {
        "list_metrics": list_metrics,
        "search_context": search_context,
        "get_metric": get_metric,
        "list_datasets": list_datasets,
        "define_metric": define_metric,
        "resolve_term": resolve_term,
        "list_context_pages": list_context_pages,
        "read_context_page": read_context_page,
    }
    descriptions = {
        "list_metrics": (
            "Governed metrics with descriptions and available dimensions; the list "
            "ends with the explicit routing hint to the ad-hoc path. Start every "
            "question here: if a governed metric answers it, query it governed."
        ),
        "search_context": (
            "Search the Context Layer (OKF pages) for business rules; ranked "
            "matches, each with its full page body. Search before any novel "
            "question — the rule you are about to rediscover is probably already "
            "a policy page. Includes auto-staged ad-hoc drafts, marked draft: true. "
            "Each hit carries its page's context_signals advisory view (lifecycle "
            "status, freshness, verification tier; a context_stale/context_deprecated "
            "warning names that page)."
        ),
        "get_metric": (
            "Rows plus compiled SQL for a named governed metric — never raw SQL. "
            "The response carries a context field: the full served OKF metric "
            "page plus the full bodies of every policy it cites. Report those "
            "caveats and paths with every number. The context also carries a "
            "context_signals advisory envelope whose warnings — context_stale "
            "(reached expiry), context_deprecated (deprecated page), "
            "context_unavailable (required metric/Policy context missing or "
            "unreadable) — name consumed pages with lifecycle problems: when "
            "the answer relies on warned context, add one brief caveat naming "
            "the affected Policy/page. Absent optional expiry/verification "
            "metadata is not a warning and needs no caveat; warnings never "
            "change values, labels or permissions. The response also carries "
            "a `data_signals` advisory view of SUPPLIED source-quality reports "
            "on the metric's directly cited table pages (per-asset coverage; "
            "per-report age/applicability/limitations, reported checks and "
            "optional watermark; warnings such as data_report_failed/"
            "data_report_expired): when the answer relies on an asset a "
            "failed/expired report warning names, add ONE brief caveat naming "
            "the report id and its as-of scope (reported outcome + report/"
            "validity time). A supplied report is a claim reported as of its "
            "observation/report time — never independent validation, execution "
            "attestation or live source health; unknown applicability/partial "
            "coverage stays unknown (a scope/version mismatch is never a "
            "matching pass) and an event-time watermark is an event boundary, "
            "not completeness or currency. Unrelated or absent optional "
            "reports demand no caveat; data warnings never change values, "
            "labels or permissions."
        ),
        "list_datasets": (
            "List every queryable table in the attached sources with its columns "
            "and types. Pairs with define_metric: pick tables here, then define "
            "an ad-hoc metric for any question no governed metric answers. "
            "Bounded RECORD selection (the latest N raw rows of one table, no "
            "aggregation) is a separate operation this fixed toolset does not "
            "expose — report such questions unsupported rather than aggregating "
            "records away; ariadneai's CLI/MCP facade serves it as query_records."
        ),
        "define_metric": (
            "Define an ad-hoc metric for a question no governed metric answers: "
            "compiled, executed read-only, auto-staged for human promotion. The "
            "definition runs through the same compile/grain gate; success returns "
            "rows, the compiled SQL, governed: false, and the staging paths of "
            "the auto-staged proposal. Joins must be grain-preserving. This is an "
            "AGGREGATION tool: a bounded record request (the latest N raw rows of "
            "one table) is not a metric definition, and this fixed toolset has no "
            "record operation — report record questions unsupported instead of "
            "silently aggregating them; ariadneai's CLI/MCP facade serves them as "
            "query_records (governed: false, never staged)."
        ),
        "resolve_term": (
            "Resolve a shared business term or an exact {resource, column} field "
            "lookup against the admitted context: bounded concept/representation "
            "matches with their exact field bindings, required scope, ambiguity "
            "and claim/confirmation status (a mapping is confirmed ONLY by "
            "recorded human admission evidence bound to the exact reviewed "
            "assertion — hypotheses stay unconfirmed leads), plus the AS-OF "
            "evidence freshness and page/source citations to report. Whole "
            "aliases/phrases match case-insensitively, never substrings. "
            "Read-only: a language alias never authorizes a join or "
            "a transform."
        ),
        "list_context_pages": (
            "List every Context Layer page — served and staged — without query "
            "tokens: path, draft flag, title and each page's context_signals "
            "advisory view, served before staged. Metadata only, never bodies. "
            "The token-free discovery view for orientation and onboarding; "
            "pair with read_context_page for full rule text."
        ),
        "read_context_page": (
            "Read one exact Context Layer page by its bundle-relative POSIX path: "
            "full content plus draft flag and context_signals. Follow "
            "cross-references and known paths directly; staged drafts require "
            "draft: true and are never verified guidance. An absolute, "
            "escaping, non-markdown or unknown path is refused naming the path."
        ),
    }
    schemas = {
        "list_metrics": {"type": "object", "properties": {}, "additionalProperties": False},
        "search_context": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "get_metric": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "list_datasets": {"type": "object", "properties": {}, "additionalProperties": False},
        "define_metric": {
            "type": "object",
            "properties": {
                "definition": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "source": {"type": "string"},
                        "expression": {"type": "string"},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "time_field": {"type": "string"},
                    },
                    "required": ["name", "description", "source", "expression"],
                }
            },
            "required": ["definition"],
            "additionalProperties": False,
        },
        "resolve_term": {
            "type": "object",
            "properties": {
                "request": {
                    "anyOf": [
                        {"type": "string", "minLength": 1},
                        {
                            "type": "object",
                            "properties": {
                                "resource": {"type": "string", "minLength": 1},
                                "column": {"type": "string", "minLength": 1},
                            },
                            "required": ["resource", "column"],
                            "additionalProperties": False,
                        },
                    ]
                },
                "part": {"type": "integer", "minimum": 1},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
        "list_context_pages": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "read_context_page": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "draft": {"type": "boolean"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    }
    return [
        AgentTool(
            name=name,
            label=name.replace("_", " ").title(),
            description=descriptions[name],
            parameters=schemas[name],
            execute_fn=executor[name],
        )
        for name in TOOL_NAMES
    ]
