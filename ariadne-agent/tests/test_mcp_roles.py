"""A3 role-restricted stdio MCP through the proxy (issue #25, spec 2026-09-29-0006).

Deterministic and offline: a minimal local fake stdio MCP server (the tau-mcp
test-fixture pattern — ``--pid-file``/``--event-file``, driven through
``ServerConfig(command=sys.executable)``) exposes one query tool and one
authoring tool, and BOTH roles drive the SAME host-supplied settings through
the PROXY path only — direct MCP registration does not exist in this build.

Real regression named by the ticket: an Analyst would reach an authoring-only
MCP tool through the proxy if its session received an unrestricted registry —
despite never seeing a direct registration. Covered by requiring the
forbidden name to be rejected by the registry's final-hop allowlist check
BEFORE any spawn (no pid file, empty server event log), by search never
advertising it, and by the server-side log never containing its call.
"""

import asyncio
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tau_ai.fake import FakeProvider
from tau_mcp.config import ServerConfig

from ariadne_agent import AssistantText, ToolActivity, open_session
from ariadne_agent.mcp_tools import McpSettings

AGENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_DIR.parent
if str(REPO_ROOT) not in sys.path:  # reuse the agent suite's helpers/oracle
    sys.path.insert(0, str(REPO_ROOT))

from test_analyst import ANALYST_TOOLS, drive, turn  # noqa: E402
from tests.test_evals import resolve_served  # noqa: E402 — the root suite's golden project builder
from tests.test_seed import run_seed  # noqa: E402
from tests.test_serve import GOLDEN_POLICY_EMEA, GOLDEN_POLICY_STATUS  # noqa: E402

from tests.test_authoring import scaffold_project  # noqa: E402 — shared service fixture

# --- the fake stdio server (one query tool, one authoring tool) ----------------

_FAKE_SERVER = '''\
"""Minimal stdio MCP fixture: pid + event log, one query and one authoring tool."""
import argparse
import json
import os
import sys
from pathlib import Path

TOOLS = [
    {
        "name": "query_orders",
        "description": "Query retail orders",
        "inputSchema": {
            "type": "object",
            "properties": {"region": {"type": "string"}},
            "required": ["region"],
        },
    },
    {
        "name": "submit_notes",
        "description": "Submit authored Seed Notes",
        "inputSchema": {
            "type": "object",
            "properties": {"notes": {"type": "string"}},
            "required": ["notes"],
        },
    },
]


def send(message):
    print(json.dumps(message, separators=(",", ":")), flush=True)


def record(path, event):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(event + "\\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--event-file", type=Path, required=True)
    args = parser.parse_args()
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)
    args.event_file.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.write_text(f"{os.getpid()}\\n", encoding="utf-8")
    record(args.event_file, "spawned")
    initialized = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-ariadne", "version": "1"},
            }})
        elif method == "notifications/initialized":
            initialized = True
            record(args.event_file, "initialized")
        elif not initialized:
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32002, "message": "not initialized"}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = message.get("params", {})
            name = params.get("name") if isinstance(params, dict) else None
            record(args.event_file, f"call:{name}")
            arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
            if name == "query_orders":
                text = f"orders for {arguments.get('region')}"
            elif name == "submit_notes":
                text = f"notes received: {arguments.get('notes')}"
            else:
                send({"jsonrpc": "2.0", "id": request_id,
                      "error": {"code": -32602, "message": f"unknown tool: {name}"}})
                continue
            send({"jsonrpc": "2.0", "id": request_id,
                  "result": {"content": [{"type": "text", "text": text}], "isError": False}})


if __name__ == "__main__":
    main()
'''


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """One configured Analyst project, built exactly as the A1 suite's own
    fixture (served layers + the two golden Policy pages + demo.db)."""
    root = resolve_served(tmp_path_factory.mktemp("a3-project"))
    policies = root / "context_layer" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    for name, body in (
        ("order-status-billing.md", GOLDEN_POLICY_STATUS),
        ("emea-currency-cutover.md", GOLDEN_POLICY_EMEA),
    ):
        page = policies / name
        if not page.exists():
            page.write_text(body, encoding="utf-8")
    run_seed(root / "demo.db")
    return root


@pytest.fixture
def mcp(tmp_path):
    """Host-supplied MCP settings plus the fake server's observation points:
    ``pid_file`` proves whether a spawn happened, ``event_file`` records every
    call the server actually received."""
    server = tmp_path / "fake_mcp_server.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    pid_file = tmp_path / "obs" / "server.pid"
    event_file = tmp_path / "obs" / "events.log"

    def settings(*, lifecycle: str = "lazy") -> McpSettings:
        return McpSettings(
            servers={
                "demo": ServerConfig(
                    name="demo",
                    command=sys.executable,
                    args=(
                        str(server),
                        "--pid-file",
                        str(pid_file),
                        "--event-file",
                        str(event_file),
                    ),
                    request_timeout_ms=5000,
                    lifecycle=lifecycle,
                )
            },
            cache_root=tmp_path / "mcp-cache",
            role_tools={
                "analyst": ("demo__query_orders",),
                "authoring": ("demo__submit_notes",),
            },
        )

    return SimpleNamespace(settings=settings, pid_file=pid_file, event_file=event_file)


def _tool_events(events: list) -> list[ToolActivity]:
    return [event for event in events if isinstance(event, ToolActivity)]


def _server_log(mcp) -> list[str]:
    if not mcp.event_file.exists():
        return []
    return mcp.event_file.read_text(encoding="utf-8").splitlines()


def _process_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


# --- the ticket's real regression ----------------------------------------------


def test_analyst_cannot_reach_authoring_tool_through_proxy(mcp, project):
    """A model-supplied authoring-only name is rejected by the registry's
    final-hop allowlist check BEFORE any spawn or call — no pid file appears
    and the server's event log stays empty — even though the model reached
    the proxy tool itself."""
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"tool": "demo__submit_notes", "args": {"notes": "ghost"}})]),
            turn(text="denied"),
        ]
    )
    session = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=provider,
        mcp_settings=mcp.settings(),
    )
    try:
        events = asyncio.run(drive(session, "submit my notes through MCP"))
    finally:
        session.close()

    activity = _tool_events(events)
    assert [event.tool for event in activity] == ["mcp"]
    denial = activity[0]
    assert denial.is_error is False, "the denial is a tool result, not a failed call"
    assert "demo__submit_notes" in denial.result
    assert "Unknown MCP tool" in denial.result, "the registry, not the server, denied it"
    assert not mcp.pid_file.exists(), "the forbidden name was rejected before any spawn"
    assert _server_log(mcp) == [], "the server never received any request at all"


def test_analyst_proxy_runs_only_the_approved_tool_and_hides_the_rest(mcp, project):
    """The approved tool runs and returns its result through the proxy; search
    advertises only allowlisted names; the server-side log contains only the
    permitted call. The model's tool surface is the five native operations
    plus exactly one MCP proxy."""
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"tool": "demo__query_orders", "args": {"region": "EMEA"}})]),
            turn(calls=[("mcp", {"search": "notes orders"})]),
            turn(text="done"),
        ]
    )
    session = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=provider,
        mcp_settings=mcp.settings(),
    )
    try:
        events = asyncio.run(drive(session, "orders in EMEA over MCP, and what else is there?"))
    finally:
        session.close()

    activity = _tool_events(events)
    assert [event.tool for event in activity] == ["mcp", "mcp"]
    allowed, search = activity
    assert allowed.is_error is False
    assert "orders for EMEA" in allowed.result, "the approved tool's result rides the proxy"
    assert "demo__query_orders" in search.result
    assert "demo__submit_notes" not in search.result, (
        "search must never advertise a name outside this role's allowlist"
    )
    assert any(isinstance(event, AssistantText) for event in events)

    _model, _system, _messages, tools = provider.calls[0]
    assert {tool.name for tool in tools} == ANALYST_TOOLS | {"mcp"}, (
        "the native Analyst surface is unchanged, with exactly one proxy added"
    )
    log = _server_log(mcp)
    assert "call:query_orders" in log
    assert not any("submit_notes" in line for line in log), (
        "the server must never see a call for a forbidden tool"
    )


def test_authoring_allowlist_is_symmetric_and_denies_the_query_tool(mcp, tmp_path):
    """The Authoring role's allowlist denies the query tool through the same
    proxy: the forbidden name is denied, search advertises only the authoring
    tool, and the approved authoring call runs."""
    project_root = scaffold_project(tmp_path)
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"tool": "demo__query_orders", "args": {"region": "EMEA"}})]),
            turn(calls=[("mcp", {"tool": "demo__submit_notes", "args": {"notes": "n1"}})]),
            turn(calls=[("mcp", {"search": "notes orders"})]),
            turn(text="done"),
        ]
    )
    session = open_session(
        role="authoring",
        project=project_root,
        model="fake-authoring",
        provider=provider,
        mcp_settings=mcp.settings(),
    )
    try:
        events = asyncio.run(drive(session, "query orders, then submit notes, over MCP"))
    finally:
        session.close()

    activity = _tool_events(events)
    assert [event.tool for event in activity] == ["mcp", "mcp", "mcp"]
    denied, allowed, search = activity
    assert "Unknown MCP tool" in denied.result
    assert "demo__query_orders" in denied.result
    assert "demo__submit_notes" in search.result
    assert "demo__query_orders" not in search.result
    assert allowed.is_error is False
    assert "notes received: n1" in allowed.result
    log = _server_log(mcp)
    assert "call:submit_notes" in log
    assert not any("call:query_orders" in line for line in log)


def test_close_reaps_the_spawned_mcp_child_process(mcp, tmp_path):
    """An approved call spawns the server child; ``close()`` reaps it (the pid
    is gone) and a second close is a no-op. An in-flight call may finish or
    time out under the client's bounded timeout — this test only promises
    reaping of the spawned child."""
    project_root = scaffold_project(tmp_path)
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"tool": "demo__submit_notes", "args": {"notes": "n"}})]),
            turn(text="done"),
        ]
    )
    session = open_session(
        role="authoring",
        project=project_root,
        model="fake-authoring",
        provider=provider,
        mcp_settings=mcp.settings(),
    )
    asyncio.run(drive(session, "submit notes over MCP"))
    pid = int(mcp.pid_file.read_text(encoding="utf-8").strip())
    os.kill(pid, 0)  # the child is alive while the session is open

    session.close()
    assert _process_gone(pid), f"MCP child {pid} must be reaped by session close"
    session.close()  # idempotent
    with pytest.raises(RuntimeError):
        session.send("after close")


# --- the two accepted follow-up findings on session-open initialization --------


def test_eager_server_is_connected_at_open_without_manual_connect(mcp, project):
    """P1: an operator-selected eager lifecycle must not be silently ignored.
    The registry's dispatch path refuses to spawn an eager server itself, so
    the eager start must happen during session open: the first permitted call
    succeeds straight away, with no connect anywhere in the turn. (Pre-fix
    this fails red: the call returns "disconnected; call connect".)"""
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"tool": "demo__query_orders", "args": {"region": "EMEA"}})]),
            turn(text="done"),
        ]
    )
    session = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=provider,
        mcp_settings=mcp.settings(lifecycle="eager"),
    )
    try:
        events = asyncio.run(drive(session, "orders in EMEA over MCP"))
    finally:
        session.close()

    activity = _tool_events(events)
    assert [event.tool for event in activity] == ["mcp"]
    first = activity[0]
    assert first.is_error is False
    assert "orders for EMEA" in first.result, (
        "an eager server must already be connected when the session opens"
    )
    assert "disconnected" not in first.result


def test_first_call_survives_delayed_loop_startup(mcp, project, monkeypatch):
    """P2: ``Thread.start()`` returns at thread bootstrap, not when
    ``run_forever`` is running. With loop entry deliberately delayed,
    initialization may only return AFTER the pinned loop is actually running
    (timestamp order), and the first authorized call still succeeds — it can
    never observe a not-yet-running loop."""
    entered: dict[str, float] = {}
    original = asyncio.BaseEventLoop.run_forever

    def delayed_run_forever(self):
        time.sleep(0.3)  # deterministic slow bootstrap of the MCP loop thread
        entered["at"] = time.monotonic()
        original(self)

    monkeypatch.setattr(asyncio.BaseEventLoop, "run_forever", delayed_run_forever)
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"tool": "demo__query_orders", "args": {"region": "EMEA"}})]),
            turn(text="done"),
        ]
    )
    session = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=provider,
        mcp_settings=mcp.settings(),
    )
    returned = time.monotonic()
    try:
        assert "at" in entered and entered["at"] <= returned, (
            "session open may only return after the MCP loop is running"
        )
        events = asyncio.run(drive(session, "orders in EMEA over MCP"))
    finally:
        session.close()

    activity = _tool_events(events)
    assert [event.tool for event in activity] == ["mcp"]
    assert activity[0].is_error is False
    assert "orders for EMEA" in activity[0].result, (
        "the first call must not observe a not-yet-running loop"
    )


def test_failed_eager_start_surfaces_as_a_named_tool_error(mcp, project):
    """The P1 error contract: a failed eager start is neither swallowed nor
    allowed to crash session open — it surfaces by name on the proxy's first
    use, and later operations (including a connect retry) proceed."""
    base = mcp.settings(lifecycle="eager")
    broken = McpSettings(
        servers={"demo": replace(base.servers["demo"], command="/nonexistent/mcp-binary")},
        cache_root=base.cache_root,
        role_tools=base.role_tools,
    )
    provider = FakeProvider(
        [
            turn(calls=[("mcp", {"search": "orders"})]),
            turn(calls=[("mcp", {"search": "orders"})]),
            turn(text="done"),
        ]
    )
    session = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=provider,
        mcp_settings=broken,
    )  # session open survives the failed eager start
    try:
        events = asyncio.run(drive(session, "what MCP tools are there?"))
    finally:
        session.close()

    activity = _tool_events(events)
    assert [event.tool for event in activity] == ["mcp", "mcp"]
    surfaced, following = activity
    assert surfaced.is_error is False, "a setup error is a tool result, not a crash"
    assert "eager" in surfaced.result.lower() and "/nonexistent/mcp-binary" in (surfaced.result), (
        "the error is named: which startup failed and why"
    )
    assert surfaced.result != following.result, (
        "the error surfaces once; the next operation proceeds normally"
    )
