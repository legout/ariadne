"""A2 Authoring session over the native authoring service (issue #24, spec
2026-09-29-0006).

Deterministic and offline: a scripted ``tau_ai.fake.FakeProvider`` drives the
real ``tau_agent.AgentHarness`` loop, the real Authoring tool wrappers, and
the real ``ariadne.authoring`` service over an empty-project fixture built
from the root suite's own helpers (``tests/test_authoring.py`` — no second
service oracle here). The operator's source approval is simulated by the TEST
HARNESS calling ``approve_sources`` directly: approval is human-only and
outside the agent, so no test path may route it through a tool.

Real regressions named by the ticket:

(a) Authoring cannot start before Promotion, or exposes approval/Promotion
    somewhere — covered by opening Authoring on projects where Analyst raises
    the missing-catalog error, and by asserting the registered tool surface
    contains no approval/Promotion tool (and no runtime is constructed);
(b) reads a model-selected path outside a trusted skill root (``../`` escape)
    — covered by the bounded reference reader refusing traversal while a
    declared reference under a host-declared root stays readable;
(c) duplicates a submission after cancellation — covered by cancelling the
    turn AFTER a completed ``submit_bundle`` and proving the persisted
    proposal state shows exactly one attempt, one revision, unchanged.
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest
from tau_agent.messages import AssistantMessage, TextContent, ToolCall
from tau_ai.events import AssistantDoneEvent
from tau_ai.fake import FakeProvider

from ariadne_agent import (
    ROLES,
    AssistantText,
    RunCompleted,
    SessionError,
    ToolActivity,
    open_session,
)
from ariadne_agent import session as session_module

AGENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_DIR.parent
if str(REPO_ROOT) not in sys.path:  # reuse the root suite's fixtures and oracle
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.skill import ASSETS  # noqa: E402

from tests.test_authoring import (  # noqa: E402 — the shared service fixtures; no second oracle here
    approved_project,
    bundle_submission,
    scaffold_project,
    write_parquet,
)

AUTHORING_TOOLS = {
    "propose_sources",
    "harness_inputs",
    "store_upload",
    "submit_bundle",
    "review_bundle",
    "read_skill_reference",
}

SPEC_CONTENT = "# Spec\n\nAll events count; label is not a key.\n"

ANSWER_WAITING = """\
Source proposal staged inert under staging/authoring/source-proposal.yaml
with the exact digest reported above. profile: null — nothing is measurable
until approval. I am stopping here: the operator approves the exact proposed
digest outside this session; I have no tool that approves, and none exists.
"""

ANSWER_REVIEWED = """\
The complete bundle is staged and validated — nothing is served. The exact
reviewed-content digest is the one review_bundle returned above; I report it
and stop. Promotion is human-only and happens outside this session; staging
never serves.
"""


# --- scripted fake model (the A1 pattern) -------------------------------------


def turn(*, text: str | None = None, calls: list[tuple[str, dict]] | None = None) -> list:
    """One scripted assistant response: tool calls, final text, or both."""
    calls = calls or []
    content: list = [TextContent(text=text)] if text else []
    content += [
        ToolCall(id=f"call_{index}", name=name, arguments=dict(args))
        for index, (name, args) in enumerate(calls)
    ]
    stop = "toolUse" if calls else "stop"
    message = AssistantMessage(model="fake-authoring", content=content, stop_reason=stop)
    return [AssistantDoneEvent(reason=stop, message=message)]


async def drive(session, text: str) -> list:
    """Consume one send() to completion, returning the typed events."""
    return [event async for event in session.send(text)]


class SubmitThenIdleProvider(FakeProvider):
    """First response replays the scripted submission (it executes and
    completes); the SECOND response is an async-generator stream that idles
    (bounded) until the run is cancelled — a deterministic in-flight turn
    right after a completed submission. Later responses come from the queued
    scripted streams."""

    def __init__(self, first: list, later: list[list]) -> None:
        super().__init__(later)
        self._first = first
        self._second = True

    def stream_response(
        self, *, model, system, messages, tools, signal=None, session_id=None
    ):
        if self._first is not None:
            first, self._first = self._first, None
            self.calls.append((model, system, list(messages), list(tools)))
            self.session_ids.append(session_id)

            async def replay():
                for event in first:
                    if signal is not None and signal.is_cancelled():
                        return
                    yield event

            return replay()
        if self._second:
            self._second = False
            self.calls.append((model, system, list(messages), list(tools)))
            self.session_ids.append(session_id)

            async def idle():
                for _ in range(2_000):  # bounded: ~10s, never a hang
                    if signal is None or signal.is_cancelled():
                        return
                    await asyncio.sleep(0.005)
                return
                yield  # unreachable: makes idle an async generator

            return idle()
        return super().stream_response(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            signal=signal,
            session_id=session_id,
        )


# --- the ticket's scripted flows ----------------------------------------------


def test_authoring_opens_where_analyst_cannot_before_any_promotion(tmp_path):
    """Acceptance 2, first half: an Authoring session opens on an empty
    project — even one with NO registry at all — while Analyst's missing-
    catalog error stays session-local and never blocks the open."""
    empty = tmp_path / "empty-project"
    empty.mkdir()

    with pytest.raises(RuntimeError, match="promote|configure"):
        open_session(
            role="analyst", project=empty, model="fake-authoring", provider=FakeProvider([])
        )

    session = open_session(
        role="authoring",
        project=empty,
        model="fake-authoring",
        provider=FakeProvider([turn(text="ready to author")]),
    )
    try:
        assert session.role == "authoring" and "authoring" in ROLES
        events = asyncio.run(drive(session, "can you work here?"))
    finally:
        session.close()
    assert any(isinstance(event, AssistantText) for event in events)
    assert isinstance(events[-1], RunCompleted)


def test_authoring_flow_stops_at_every_human_gate(tmp_path):
    """The ticket's flow end to end on an empty project: inert source
    proposal -> `profile: null` BEFORE operator approval (the approval runs
    in this test harness, outside the agent) -> bounded measured inputs after
    approval -> staged submit of the exact content -> review reports the
    exact staged digest -> stop WITHOUT Promotion."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(project / "data" / "events.parquet")
    proposal = {"sources": [{"name": "events", "type": "parquet", "path": str(parquet)}]}
    submission = dict(bundle_submission())
    submission["documents"] = ["spec.md"]

    session = open_session(
        role="authoring",
        project=project,
        model="fake-authoring",
        provider=FakeProvider(
            [
                turn(calls=[("propose_sources", dict(proposal))]),
                turn(calls=[("harness_inputs", {})]),
                turn(text=ANSWER_WAITING),
                turn(calls=[("store_upload", {"name": "spec.md", "content": SPEC_CONTENT})]),
                turn(calls=[("harness_inputs", {"documents": ["spec.md"]})]),
                turn(calls=[("submit_bundle", {"submission": submission})]),
                turn(calls=[("review_bundle", {})]),
                turn(text=ANSWER_REVIEWED),
            ]
        ),
    )
    try:
        events = asyncio.run(drive(session, "set up the events source"))
        # OPERATOR approval, outside the agent, between the two runs.
        from ariadne import authoring as authoring_service

        propose = json.loads(
            next(
                event.result
                for event in events
                if isinstance(event, ToolActivity) and event.tool == "propose_sources"
            )
        )
        authoring_service.approve_sources(propose["digest"], project=project)
        events += asyncio.run(drive(session, "approved; author and stage the bundle"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == [
        "propose_sources",
        "harness_inputs",
        "store_upload",
        "harness_inputs",
        "submit_bundle",
        "review_bundle",
    ]
    assert all(event.is_error is False for event in activity)
    _propose, pre_inputs, upload, post_inputs, submit, review = (
        json.loads(event.result) for event in activity
    )

    # Inert before approval: nothing profileable, nothing opened.
    assert pre_inputs["profile"] is None, "pre-approval inputs must report profile: null"
    # Bounded measured inputs after approval: the profile is the approved
    # registry's, and the document evidence binds the upload's exact digest.
    assert post_inputs["profile"]["sources"][0]["name"] == "events"
    upload_digest = hashlib.sha256(SPEC_CONTENT.encode("utf-8")).hexdigest()
    assert upload["digest"] == upload_digest
    assert post_inputs["documents"][0]["digest"] == upload_digest
    assert post_inputs["documents"][0]["complete"] is True

    # Staged submit of the exact content; review reports the exact staged
    # digest (never a signoff), and the citation rides the staged identity.
    assert submit["status"] == "validated"
    assert len(submit["review_digest"]) == 64
    assert submit["documents"][0]["digest"] == upload_digest
    assert review["digest"] == submit["review_digest"]
    assert review["status"] == "validated"

    # Stop WITHOUT Promotion: nothing served, the proposal never 'promoted'.
    assert not (project / "context_layer").exists()
    assert not (project / "semantic_layer").exists()
    state = json.loads(
        (project / "staging" / "authoring" / "bundle-state.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "validated"

    waiting = next(e.text for e in events if isinstance(e, AssistantText))
    assert "outside this session" in waiting, "the agent must stop at the approval gate"
    answer = [e.text for e in events if isinstance(e, AssistantText)][-1]
    lowered = answer.lower()
    assert "digest" in lowered and "promotion" in lowered and "human" in lowered


def test_cancel_after_submission_never_replays_the_submission(tmp_path):
    """Regression (c): cancelling the turn AFTER a completed submission
    neither duplicates nor replays it — exactly one submit executed, the
    persisted proposal state still shows one attempt/one revision, and the
    session stays usable for a follow-up run that submits nothing."""

    project = approved_project(tmp_path)
    provider = SubmitThenIdleProvider(
        turn(calls=[("submit_bundle", {"submission": dict(bundle_submission())})]),
        [turn(text="staged exactly once; stopped")],
    )
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )

    async def scenario() -> list:
        events = []
        async for event in session.send("submit the bundle, then summarize"):
            events.append(event)
            if isinstance(event, ToolActivity) and event.tool == "submit_bundle":
                session.cancel()  # after the completed submission, mid next turn
        return events

    try:
        events = asyncio.run(asyncio.wait_for(scenario(), timeout=60))

        submits = [
            event
            for event in events
            if isinstance(event, ToolActivity) and event.tool == "submit_bundle"
        ]
        assert len(submits) == 1 and submits[0].is_error is False, (
            "cancellation must not duplicate or replay the submission"
        )
        state_path = project / "staging" / "authoring" / "bundle-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert (
            state["attempts"] == 1 and state["revision"] == 1 and state["status"] == "validated"
        )
        assert any(isinstance(event, SessionError) for event in events), (
            "the cancelled turn ends with a typed error, not silence"
        )
        assert isinstance(events[-1], RunCompleted)

        # The session stays usable and still submits nothing new.
        follow = asyncio.run(drive(session, "status?"))
        assert any(isinstance(event, AssistantText) for event in follow)
        assert not any(isinstance(event, ToolActivity) for event in follow)
        assert json.loads(state_path.read_text(encoding="utf-8")) == state
        assert provider._first is None and provider._second is False
    finally:
        session.close()


def test_authoring_surface_has_no_approval_or_promotion_and_no_runtime(
    tmp_path, monkeypatch
):
    """Regression (a): the Authoring tool surface is exactly the five authoring
    service operations plus the bounded reference reader — no approval, no
    Promotion, anywhere in the registered tools — and opening the session
    constructs NO AriadneRuntime (Authoring needs no query runtime)."""

    def no_runtime(*args, **kwargs):  # pragma: no cover - fails the test if called
        raise AssertionError("Authoring must not construct AriadneRuntime")

    monkeypatch.setattr(session_module, "_open_runtime", no_runtime)
    project = scaffold_project(tmp_path)
    provider = FakeProvider([turn(text="ok")])
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )
    events = asyncio.run(drive(session, "hello"))
    session.close()

    model, system, _messages, tools = provider.calls[0]
    assert model == "fake-authoring"
    names = {tool.name for tool in tools}
    assert names == AUTHORING_TOOLS, "the Authoring role gets the authoring service ops"
    assert not any("approve" in name or "promote" in name for name in names), (
        "no registered tool may approve sources or Promote"
    )
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    assert skill.strip() in system, "the version-matched packaged skill must be the guidance"
    rubric = (ASSETS / "references" / "grain-rubric.md").read_text(encoding="utf-8")
    assert rubric.strip() in system, "the grain rubric reference rides the guidance"
    assert all(name in system for name in AUTHORING_TOOLS), (
        "the guidance must map the skill's workflow onto the native tools"
    )
    assert any(isinstance(event, AssistantText) for event in events)


def test_skill_reference_reads_stay_inside_trusted_roots(tmp_path):
    """Regression (b): a declared reference under the packaged skill and under
    a host-declared trusted root IS readable; a model-selected ``../`` escape
    and a non-.md script under the root are refused — no scan, no execution."""
    project = scaffold_project(tmp_path)
    root = tmp_path / "trusted-skill-root"
    (root / "references").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "SKILL.md").write_text("# Host skill\n", encoding="utf-8")
    (root / "references" / "rubric.md").write_text("# Host rubric\n", encoding="utf-8")
    (root / "scripts" / "helper.py").write_text("print('never run')\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# outside every trusted root\n", encoding="utf-8")

    session = open_session(
        role="authoring",
        project=project,
        model="fake-authoring",
        skill_roots=[root],
        provider=FakeProvider(
            [
                turn(
                    calls=[
                        ("read_skill_reference", {"reference": "references/grain-rubric.md"}),
                        ("read_skill_reference", {"reference": "references/rubric.md"}),
                        ("read_skill_reference", {"reference": "../outside.md"}),
                        ("read_skill_reference", {"reference": "scripts/helper.py"}),
                    ]
                ),
                turn(text="references read; escapes refused"),
            ]
        ),
    )
    try:
        events = asyncio.run(drive(session, "read the rubric"))
    finally:
        session.close()

    by_reference = {
        event.args["reference"]: event
        for event in events
        if isinstance(event, ToolActivity) and event.tool == "read_skill_reference"
    }
    assert len(by_reference) == 4, "every requested reference produced one activity"

    packaged = by_reference["references/grain-rubric.md"]
    assert packaged.is_error is False
    assert "Grain rubric" in json.loads(packaged.result)["content"]
    host = by_reference["references/rubric.md"]
    assert host.is_error is False
    assert json.loads(host.result)["content"] == "# Host rubric\n"

    escape = by_reference["../outside.md"]
    assert escape.is_error is True, "a ../ escape must be refused"
    assert "outside every trusted root" not in escape.result, "refused content never leaks"
    assert "refused" in escape.result.lower() or "traversal" in escape.result.lower()

    script = by_reference["scripts/helper.py"]
    assert script.is_error is True, "scripts are never readable or executable"
    assert "never run" not in script.result
    assert "refused" in script.result.lower()

    assert outside.read_text(encoding="utf-8") == "# outside every trusted root\n"
