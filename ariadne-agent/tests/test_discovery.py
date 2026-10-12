"""Spec 0018: embedded analyst startup and grouped discovery stay artifact-only."""

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.discovery import DiscoveryRuntime  # noqa: E402
from tau_agent.messages import AssistantMessage, ToolCall  # noqa: E402
from tau_ai.events import AssistantDoneEvent  # noqa: E402
from tau_ai.fake import FakeProvider  # noqa: E402

from ariadne_agent import ToolActivity, open_session  # noqa: E402
from tests.test_discovery import artifacts, source_free  # noqa: E402, F401


def test_embedded_discover_startup_schema_payload_and_no_writes(request):
    root, staging = request.getfixturevalue("artifacts")
    request.getfixturevalue("source_free")
    # The legacy host requires a declared db location, not readable source bytes.
    (root / "demo.db").write_bytes(b"offline source")
    # Embedded sessions anchor staging at the project root.
    staging.rename(root / "staging")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    provider = FakeProvider(
        [
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        stop_reason="toolUse",
                        content=[
                            ToolCall(
                                id="discover-1",
                                name="discover",
                                arguments={
                                    "query": "order number",
                                    "limit": 1,
                                },
                            )
                        ],
                    ),
                )
            ],
            [
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        stop_reason="stop",
                        content=[],
                    ),
                )
            ],
        ]
    )
    session = open_session(role="analyst", project=root, model="fake", provider=provider)
    try:
        tools = {tool.name: tool for tool in session._harness.config.tools}
        assert "discover" in tools
        schema = tools["discover"].parameters
        properties = schema["properties"]
        assert isinstance(properties, dict)
        assert set(properties) == {"query", "limit"}
        assert schema["required"] == ["query"]
        limit = properties["limit"]
        assert isinstance(limit, dict) and limit["default"] == 5

        async def drive():
            return [event async for event in session.send("Discover order number guidance")]

        activities = [event for event in asyncio.run(drive()) if isinstance(event, ToolActivity)]
        assert len(activities) == 1 and not activities[0].is_error
        payload = json.loads(activities[0].result)
        native = DiscoveryRuntime(
            root / "semantic_layer",
            root / "context_layer",
            root / "demo.db",
            staging_dir=root / "staging",
        )
        assert payload == asyncio.run(native.discover("order number", limit=1))
        assert payload["groups"]["metrics"]["items"][0]["name"] == "order_count"
        assert len(payload["groups"]["terms"]["result"]["matches"]) == 2
    finally:
        session.close()  # must not open execution just to close an unused connection
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_deferred_embedded_query_does_not_reselect_its_startup_route(tmp_path, monkeypatch):
    import os

    from ariadne.authoring import AuthoringProject
    from tests.test_git_authoring import complete_bundle_project

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    project = complete_bundle_project(tmp_path)
    session = open_session(
        role="analyst", project=project, model="fake", provider=FakeProvider([])
    )
    try:
        assert not (project / ".ariadne").exists()
        # Another role starting authoring must not silently reroute this already-open Analyst.
        AuthoringProject(project).start_proposal()
        assert (project / ".ariadne").exists()
        assert session._runtime is not None
        result = asyncio.run(session._runtime.get_metric("event_count"))
        assert result["rows"] == [{"event_count": 3}]  # the three independent fixture events
        assert "admission" not in result  # the session remains explicit legacy, not Git-admitted
    finally:
        session.close()
