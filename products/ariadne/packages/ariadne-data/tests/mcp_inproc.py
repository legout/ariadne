"""In-process driver for the REAL MCP tools of one project (no subprocess, no CLI): the app
is assembled exactly as ``ariadne.serve.main`` assembles it (deferred runtime + discovery),
so tests exercise the actual tool registration, argument schemas and error mapping."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ariadne import query_results
from ariadne.discovery import DiscoveryRuntime
from ariadne.execution import DeadlineBudget
from ariadne.query import DeferredQueryRuntime, QueryRuntime
from ariadne.serve import build_app


def build(project: Path, toolset: str = "combined"):
    project = Path(project).resolve()

    def runtime():
        seconds = query_results.load_host_query_limits(project)["execution_seconds"]
        discovery = DiscoveryRuntime.open_project(project)
        return QueryRuntime.open_project(
            project,
            deadline_budget=DeadlineBudget(seconds),
            discovery=discovery if discovery._managed is not None else None,
        )

    facade = DeferredQueryRuntime(runtime, lambda: DiscoveryRuntime.open_project(project))
    return build_app(facade, project=project, toolset=toolset)


def payload(result):
    """The tool's JSON payload (list returns arrive as one block per element)."""
    blocks = list(getattr(result, "content", None) or [])
    texts = [block.text for block in blocks]

    def element(text: str):
        try:
            return json.loads(text)
        except ValueError:
            return text

    if len(texts) == 1:
        return element(texts[0])
    return [element(text) for text in texts]


def call(project: Path, tool: str, arguments: dict | None = None, toolset: str = "combined"):
    """Call one MCP tool. Returns ``(is_error, payload_or_message)``."""
    app = build(project, toolset)
    try:
        result = asyncio.run(app.call_tool(tool, arguments or {}))
    except Exception as exc:  # a ToolError surfaces its message verbatim
        return True, str(exc)
    if getattr(result, "is_error", False):
        return True, payload(result)
    return False, payload(result)


def run(root: Path, tool: str, arguments: dict | None = None) -> int:
    """Call one real MCP tool and report it CLI-shaped for the assertions: the payload as
    one JSON value on stdout (exit 0), or one ``{"error": {...}}`` object on stderr (exit 1)."""
    import sys

    is_error, out = call(root, tool, arguments)
    if tool in ("search_examples", "search_context") and not is_error:
        out = out if isinstance(out, list) else ([] if out in ("", None) else [out])
    if is_error:
        message = out if isinstance(out, str) else json.dumps(out)
        message = message.removeprefix(f"Error executing tool {tool}: ")
        print(json.dumps({"error": {"type": "ToolError", "message": message}}), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0
