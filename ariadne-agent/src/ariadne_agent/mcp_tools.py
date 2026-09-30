"""Role-restricted stdio MCP for one agent session (issue #25, ADR-0014).

Each session owns ONE ``tau_mcp.registry.ServerRegistry`` whose frozen
per-instance allowlist is the ROLE's operator-supplied qualified tool names
(``<server>__<tool>``). The host supplies the validated server entries, the
cache root and the per-role allowlist — never a user message or model text —
and no ``~/.tau/mcp.json`` or other ambient configuration is loaded here. The
registry's allowlist governs discovery (``search`` returns only permitted
names) AND dispatch (``call_tool_with_added`` re-checks the qualified name
before any spawn or call), so a forbidden name the model supplies through the
proxy is rejected by that final-hop check with the server never seeing it,
and one server's failure cannot make an unauthorized fallback tool available.

``tau_mcp.proxy`` is deliberately not imported: it is the Tau-extension
flavor and transitively imports ``tau_coding``, which this package must never
load at runtime (spec 2026-09-29-0006 acceptance 5). The tool below drives
the same accepted registry core — the same restricted search/call/shutdown
path — as this package's single native proxy tool; direct MCP registration
stays a Tau extension and is not offered in Ariadne v1.

The registry is pinned to one dedicated loop because its asyncio children
(stdio transports, reader tasks, locks) bind to the loop that spawned them,
while a session may be driven through a fresh ``asyncio.run`` per ``send``.
Every registry operation crosses to that loop; ``shutdown`` is synchronous,
bounded, and reaps every spawned child process. A call already executing when
the session closes finishes or times out under the MCP client's bounded
request timeout — immediate interruption is not promised.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult
from tau_agent.types import JSONValue
from tau_mcp.cache import CacheStore
from tau_mcp.client import JsonValue as McpJsonValue
from tau_mcp.client import McpError, ToolCallResult
from tau_mcp.config import McpConfig, ServerConfig
from tau_mcp.registry import ServerRegistry, StaleRegistryError

_OUTPUT_LIMIT = 256 * 1024  # the same bound tau-mcp applies to tool output
_INIT_TIMEOUT = 15.0  # loop-readiness and eager-start bound (handshake is 10s)

_PROXY_PARAMETERS: Mapping[str, JSONValue] = {
    "type": "object",
    "properties": {
        "search": {"type": "string", "description": "Search cached MCP tool metadata."},
        "tool": {"type": "string", "description": "Call server__tool."},
        "args": {
            "description": "Tool arguments as an object or JSON string.",
            "anyOf": [{"type": "object"}, {"type": "string"}],
        },
        "connect": {"type": "string", "description": "Connect and refresh one server."},
        "disconnect": {"type": "string", "description": "Disconnect one server."},
    },
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class McpSettings:
    """Host-supplied MCP configuration (spec 2026-09-29-0006): validated
    server entries, a cache root, and each role's operator-approved qualified
    tool names. Constructed by the operator outside user messages and
    data-project artifacts; a model request can never alter it."""

    servers: Mapping[str, ServerConfig]
    cache_root: Path
    role_tools: Mapping[str, Sequence[str]]


class SessionMcp:
    """One session's role-restricted registry plus the loop it is pinned to.

    ``proxy_tool`` returns the single MCP proxy for the harness (``None`` when
    the role's allowlist is empty — no MCP surface at all); ``shutdown`` reaps
    every MCP child the session spawned."""

    def __init__(self, settings: McpSettings, role: str) -> None:
        # A role absent from the operator map is deny-all (empty allowlist),
        # never unrestricted: only an explicit None allowlist would be that,
        # and this package never constructs one.
        self._allowed = frozenset(settings.role_tools.get(role, ()))
        self._registry = ServerRegistry(
            McpConfig(servers=dict(settings.servers)),
            CacheStore(Path(settings.cache_root)),
            allowed_tools=self._allowed,
        )
        self._eager_error: str | None = None
        self._loop = asyncio.new_event_loop()
        # Thread.start() returns at the thread bootstrap, not at loop
        # readiness: the readiness signal is scheduled as the loop's FIRST
        # callback, so __init__ can only proceed once run_forever is actually
        # executing callbacks — an immediate first proxy call can never
        # observe a not-yet-running loop and trip a spurious
        # StaleRegistryError while the session is open (issue #25 P2).
        ready = threading.Event()

        def _serve() -> None:
            self._loop.call_soon(ready.set)
            self._loop.run_forever()

        self._thread = threading.Thread(target=_serve, name=f"ariadne-mcp-{role}", daemon=True)
        self._thread.start()
        if not ready.wait(_INIT_TIMEOUT):
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(_INIT_TIMEOUT)
            self._loop.close()
            raise RuntimeError(
                f"MCP loop for role {role!r} did not become ready within "
                f"{_INIT_TIMEOUT}s — the session cannot open"
            )
        # Eager servers are part of session setup: the operator selected
        # eager startup, and the registry's dispatch path never spawns an
        # eager server itself (issue #25 P1), so they connect HERE on the
        # pinned loop. A failed or hung eager start surfaces as a named
        # error on the proxy's first use instead of a silent later
        # "disconnected; call connect" — it does not crash session open.
        eager = asyncio.run_coroutine_threadsafe(self._registry.start(), self._loop)
        try:
            eager.result(_INIT_TIMEOUT)
        except TimeoutError:
            # Name the still-starting server(s): the dependency contract
            # requires a *named* error for a permitted-but-unavailable
            # server, not a generic timeout (issue #25 recheck P2).
            eager_names = {
                name for name, cfg in settings.servers.items()
                if cfg.lifecycle == "eager"
            }
            not_ready = {
                status.name for status in self._registry.statuses()
                if status.state != "ready"
            }
            pending = ", ".join(sorted((eager_names & not_ready) or eager_names))
            self._eager_error = (
                f"eager start did not finish within {_INIT_TIMEOUT}s "
                f"(still starting: {pending or 'unknown eager server'})"
            )
        except Exception as exc:
            self._eager_error = f"{type(exc).__name__}: {exc}"

    @property
    def allowed_tools(self) -> frozenset[str]:
        """This session's frozen operator-supplied qualified tool names."""
        return self._allowed

    def proxy_tool(self) -> AgentTool | None:
        """The one MCP proxy tool for this session's harness, or ``None`` when
        the role's operator allowlist approves no MCP tool."""
        if not self._allowed:
            return None

        async def execute(
            tool_call_id: str, arguments: dict, signal=None, on_update=None
        ) -> AgentToolResult:
            del tool_call_id, signal, on_update
            return await self._execute_proxy(arguments)

        return AgentTool(
            name="mcp",
            label="MCP",
            description=(
                "Search cached MCP tools or route a call by server__tool name. "
                "Only this session's operator-approved tools are discoverable "
                "or callable; eager-configured servers connect at session open, "
                "others on first connect or call."
            ),
            parameters=_PROXY_PARAMETERS,
            execute_fn=execute,
            execution_mode="sequential",
        )

    def shutdown(self, timeout: float = 30.0) -> None:
        """Invalidate the registry and reap every spawned MCP child (bounded
        by ``timeout``); a call already executing finishes or times out under
        the MCP client's bounded request timeout — it is not interrupted."""
        if not self._thread.is_alive():
            return
        pending = asyncio.run_coroutine_threadsafe(self._registry.shutdown(), self._loop)
        try:
            pending.result(timeout)
        except TimeoutError as exc:
            raise RuntimeError(
                f"MCP child shutdown did not finish within {timeout}s — "
                "children may still be running"
            ) from exc
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout)
            self._loop.close()

    async def _run(self, coroutine):
        """Run one registry operation on the registry's pinned loop and await
        its result from the caller's loop."""
        if not self._loop.is_running():
            raise StaleRegistryError("MCP registry is stale after session shutdown")
        return await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        )

    async def _execute_proxy(self, arguments: Mapping[str, JSONValue]) -> AgentToolResult:
        if self._eager_error is not None and "connect" not in arguments:
            # A failed eager start is reported honestly exactly once, as a
            # bounded tool result; connect stays open as the retry path.
            # The stored text can carry a server's verbatim exception, so it
            # passes the same 256 KiB output bound as every other result
            # (issue #25 recheck P1).
            error = self._eager_error
            self._eager_error = None
            return _text(_truncate(
                f"MCP eager-server startup failed at session open ({error}). "
                "Other operations now proceed; connect(<server>) retries a "
                "failed server."
            ))
        if "search" in arguments:
            query = arguments["search"]
            if not isinstance(query, str):
                return _text("`search` must be a string.")
            # Cache-only and allowlist-restricted inside the registry: no
            # server is contacted, no forbidden name is ever advertised.
            results = self._registry.search(query)
            lines: list[str] = []
            if results:
                noun = "tool" if len(results) == 1 else "tools"
                lines.append(f'Found {len(results)} {noun} matching "{query}":')
                for result in results:
                    lines.append(
                        f"{result.qualified_name}\n"
                        f"  {_one_line(result.description) or '(no description)'}\n"
                        f"  Parameters:\n"
                        f"    {json.dumps(dict(result.parameters), sort_keys=True)}"
                    )
            cold = [
                server.name
                for server in self._registry.servers
                if self._registry.server_allowed(server.name)
                and self._registry.cache.read(server) is None
            ]
            lines.extend(
                f'{name}: no metadata yet — call connect("{name}")' for name in cold
            )
            if not lines:
                return _text(f'No tools matching "{query}"')
            return _text("\n\n".join(lines))
        if "connect" in arguments:
            name = arguments["connect"]
            if not isinstance(name, str):
                return _text("`connect` must be a server name string.")
            try:
                await self._run(self._registry.connect_with_added(name))
            except McpError as exc:
                return _text(str(exc))
            return _text(f'MCP server "{name}" connected and metadata refreshed.')
        if "disconnect" in arguments:
            name = arguments["disconnect"]
            if not isinstance(name, str):
                return _text("`disconnect` must be a server name string.")
            try:
                await self._run(self._registry.disconnect(name))
            except McpError as exc:
                return _text(str(exc))
            return _text(f'MCP server "{name}" disconnected.')
        if "tool" in arguments:
            target = arguments["tool"]
            if not isinstance(target, str):
                return _text("`tool` must be a server__tool name string.")
            parsed = _tool_arguments(arguments.get("args", {}))
            if isinstance(parsed, str):
                return _text(parsed)
            try:
                # The registry's final-hop allowlist check runs before any
                # spawn or call: a forbidden name never reaches a server.
                result, _added = await self._run(
                    self._registry.call_tool_with_added(target, parsed)
                )
            except McpError as exc:
                return _text(str(exc))
            return _tool_result(result)
        return _text("Provide one of: search, tool, connect, or disconnect.")


def _text(message: str) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=message)])


def _tool_result(result: ToolCallResult) -> AgentToolResult:
    texts = [
        item["text"]
        for item in result.content
        if item.get("type") == "text" and isinstance(item.get("text"), str)
    ]
    return _text(_truncate("\n".join(texts) or "MCP tool returned no text content."))


def _truncate(value: str) -> str:
    encoded = value.encode()
    if len(encoded) <= _OUTPUT_LIMIT:
        return value
    note = (
        f"\n\n[truncated MCP output: original {len(encoded)} bytes; "
        f"limit {_OUTPUT_LIMIT} bytes]"
    )
    budget = _OUTPUT_LIMIT - len(note.encode())
    return encoded[:budget].decode(errors="ignore") + note


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _tool_arguments(value: JSONValue) -> Mapping[str, McpJsonValue] | str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return "`args` must be a JSON object or a string containing one JSON object."
    if not isinstance(value, dict):
        return "`args` must be a JSON object or a string containing one JSON object."
    return value
