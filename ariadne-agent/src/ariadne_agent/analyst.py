"""Analyst role tools: QueryRuntime's five public operations as native tools.

Thin wrappers only (spec 2026-09-29-0006 session/role interface): compilation,
grain checks, read-only execution, context attachment and proposal staging all
live in ``ariadne-core``; nothing is reimplemented here. Each tool's payload is
the runtime's verbatim JSON envelope — values, served metric page, full Policy
bodies and citations, staging paths, and ``governed`` labels are never stripped
or summarized. Runtime failures propagate with their verbatim message and are
reported to the model as tool errors. No CLI, no shell, no server, no raw SQL,
no source-approval or Promotion tool.
"""

import json

from ariadne.query import QueryRuntime
from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult, ToolExecutor

TOOL_NAMES = ("list_metrics", "search_context", "get_metric", "list_datasets", "define_metric")


def _payload(value: object) -> AgentToolResult:
    """One verbatim JSON payload — the runtime envelope is the whole contract."""
    return AgentToolResult(content=[TextContent(text=json.dumps(value, default=str))])


def analyst_tools(runtime: QueryRuntime) -> list[AgentTool]:
    """The Analyst tool set: exactly Ariadne's five query operations."""
    # Each wrapper mirrors the runtime's own signature and the routing language
    # the ariadne-core MCP facade uses (spec rev 4 §8.12: fresh consuming agents
    # discover the ad-hoc path through the facade itself).
    async def list_metrics(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.list_metrics())

    async def search_context(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        limit = arguments.get("limit", 10)
        return _payload(await runtime.search_context(arguments["query"], limit))

    async def get_metric(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            await runtime.get_metric(
                arguments["name"], arguments.get("dimensions"), arguments.get("range")
            )
        )

    async def list_datasets(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.list_datasets())

    async def define_metric(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(await runtime.define_metric(arguments["definition"]))

    executor: dict[str, ToolExecutor] = {
        "list_metrics": list_metrics,
        "search_context": search_context,
        "get_metric": get_metric,
        "list_datasets": list_datasets,
        "define_metric": define_metric,
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
            "a policy page. Includes auto-staged ad-hoc drafts, marked draft: true."
        ),
        "get_metric": (
            "Rows plus compiled SQL for a named governed metric — never raw SQL. "
            "The response carries a context field: the full served OKF metric "
            "page plus the full bodies of every policy it cites. Report those "
            "caveats and paths with every number."
        ),
        "list_datasets": (
            "List every queryable table in the attached sources with its columns "
            "and types. Pairs with define_metric: pick tables here, then define "
            "an ad-hoc metric for any question no governed metric answers."
        ),
        "define_metric": (
            "Define an ad-hoc metric for a question no governed metric answers: "
            "compiled, executed read-only, auto-staged for human promotion. The "
            "definition runs through the same compile/grain gate; success returns "
            "rows, the compiled SQL, governed: false, and the staging paths of "
            "the auto-staged proposal. Joins must be grain-preserving."
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
