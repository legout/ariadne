"""Spec 0018 over the Git-only core: embedded analyst startup and grouped
discovery stay artifact-only, admission-bound and pinned (issue #73)."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from tau_agent.messages import AssistantMessage, TextContent, ToolCall
from tau_ai.events import AssistantDoneEvent
from tau_ai.fake import FakeProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = Path(__file__).resolve().parents[1]
for extra in (str(REPO_ROOT), str(AGENT_DIR)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.discovery import DiscoveryRuntime  # noqa: E402
from test_analyst import (  # noqa: E402 — the shared admitted fixture (a sibling
    # module, like test_mcp_roles' import; pytest puts this directory on sys.path)
    ORDER_TERM_REFERENCE,
    admitted_retail_project,
)
from tests.test_git_authoring import approved  # noqa: E402 — the root suite's helper
from tests.test_serve import GOLDEN_POLICY_STATUS  # noqa: E402


def turn(*, text: str | None = None, calls: list[tuple[str, dict]] | None = None) -> list:
    calls = calls or []
    content: list = [TextContent(text=text)] if text else []
    content += [
        ToolCall(id=f"call_{index}", name=name, arguments=dict(args))
        for index, (name, args) in enumerate(calls)
    ]
    stop = "toolUse" if calls else "stop"
    message = AssistantMessage(model="fake", content=content, stop_reason=stop)
    return [AssistantDoneEvent(reason=stop, message=message)]


async def drive(session, text: str) -> list:
    return [event async for event in session.send(text)]


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _admit(project: Path) -> dict:
    """The human Git journey's admit step; returns the review envelope."""
    from tests.test_git_admission import admit

    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    return review


def test_embedded_discover_startup_schema_payload_and_no_writes(tmp_path):
    """The discover tool's schema is the artifact-only discovery contract, its
    payload is exactly the public factory's output over the ADMITTED snapshot,
    and the discover-only run writes nothing and never constructs the query
    runtime (not even while closing)."""
    from ariadne_agent import ToolActivity, open_session

    project = admitted_retail_project(tmp_path, reference=ORDER_TERM_REFERENCE)
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
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
                                arguments={"query": "order number", "limit": 1},
                            )
                        ],
                    ),
                )
            ],
            [
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="fake", stop_reason="stop", content=[]),
                )
            ],
        ]
    )
    session = open_session(role="analyst", project=project, model="fake", provider=provider)
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

        async def run() -> list:
            return [event async for event in session.send("Discover order number guidance")]

        activities = [event for event in asyncio.run(run()) if isinstance(event, ToolActivity)]
        assert len(activities) == 1 and not activities[0].is_error
        payload = json.loads(activities[0].result)
        native = DiscoveryRuntime.open_project(project)
        assert payload == asyncio.run(native.discover("order number", limit=1))
        # the admitted Term Reference resolves: both documented representations
        assert len(payload["groups"]["terms"]["result"]["matches"]) == 2
        # the metrics group serves the routing hint over the admitted catalog
        assert payload["groups"]["metrics"]["status"] == "available"
        assert "routing_hint" in payload["groups"]["metrics"]
        # discovery never opened execution: no query runtime was constructed
        assert session._runtime is not None and session._runtime._runtime is None
    finally:
        session.close()  # must not open execution just to close an unused connection
    assert before == {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}


def test_deferred_embedded_query_pins_its_resolved_admission(tmp_path):
    """The serve.py DeferredQueryRuntime pattern through the session: the
    query factory resolves the FIRST real admission, and an already-admitted
    session stays PINNED to it — a later second admission on the same project
    does not move the session — while a FRESH session resolves the new one.
    Another role starting authoring never reroutes an already-open Analyst."""
    from ariadne_agent import ToolActivity, open_session

    project = admitted_retail_project(tmp_path)
    first_review = _admit(project)
    revision_a = first_review["revision"]

    provider = FakeProvider(
        [
            turn(calls=[("get_metric", {"name": "gross_margin", "dimensions": ["region"]})]),
            turn(text="answered from the pinned admission"),
            turn(calls=[("get_metric", {"name": "gross_margin", "dimensions": ["region"]})]),
            turn(text="still the pinned admission"),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake", provider=provider)
    try:
        events = asyncio.run(drive(session, "gross margin by region?"))
        activity = [event for event in events if isinstance(event, ToolActivity)]
        assert [event.tool for event in activity] == ["get_metric"]
        assert activity[0].is_error is False
        payload = json.loads(activity[0].result)
        assert payload["governed"] is True
        assert payload["admission"]["revision"] == revision_a

        # Another role starting authoring must not silently reroute the
        # already-open Analyst; a SECOND human admission lands a new revision.
        AuthoringProject(project).start_proposal()
        second_review = _second_admission(project)
        assert second_review["revision"] != revision_a

        events = asyncio.run(drive(session, "gross margin by region again?"))
        activity = [event for event in events if isinstance(event, ToolActivity)]
        payload = json.loads(activity[0].result)
        assert payload["admission"]["revision"] == revision_a, (
            "an already-admitted session stays pinned to its first admission"
        )
    finally:
        session.close()

    # a FRESH session resolves the CURRENT admission
    provider2 = FakeProvider(
        [
            turn(calls=[("get_metric", {"name": "gross_margin", "dimensions": ["region"]})]),
            turn(text="fresh session, current admission"),
        ]
    )
    fresh = open_session(role="analyst", project=project, model="fake", provider=provider2)
    try:
        events = asyncio.run(drive(fresh, "gross margin, freshly?"))
        activity = [event for event in events if isinstance(event, ToolActivity)]
        payload = json.loads(activity[0].result)
        assert payload["admission"]["revision"] == second_review["revision"]
    finally:
        fresh.close()


def _second_admission(project: Path) -> dict:
    """One more human journey: a real page edit, validate, review, admit."""
    from tests.test_git_admission import admit

    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "order-status-billing",
            "content": GOLDEN_POLICY_STATUS.replace(
                "every revenue, cost, and order-count number.",
                "every revenue, cost, and order-count number. (clarified)",
            ),
        },
    )
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    return review
