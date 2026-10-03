"""A2 Authoring session over the native Git authoring contract (issue #24,
migrated to the Git proposals of issue #38/G6; spec 2026-09-29-0006 over
spec 2026-10-02-0009 §§3–4, plan §2's Authoring call contract).

Deterministic and offline: a scripted ``tau_ai.fake.FakeProvider`` drives the
real ``tau_agent.AgentHarness`` loop, the real Authoring tool wrappers, and
the real :class:`ariadne.authoring.AuthoringProject` over the root suite's
complete-bundle Git fixture (``tests/test_git_authoring.py`` — no second
service oracle here). The operator's source approval is simulated by the TEST
HARNESS calling ``approve_sources`` directly: approval is human-only and
outside the agent, so no test path may route it through a tool.

Real regressions named by the tickets:

(a) Authoring cannot start before admission, or exposes approval/admission
    somewhere — covered by opening Authoring on projects where Analyst raises
    the missing-catalog/admission error, and by asserting the registered tool
    surface contains no approval/admission/Promotion tool (and no runtime is
    constructed);
(b) reads a model-selected path outside a trusted skill root (``../`` escape)
    — covered by the bounded reference reader refusing traversal while a
    declared reference under a host-declared root stays readable;
(c) duplicates a proposal edit after cancellation — covered by cancelling the
    turn AFTER a completed ``edit_proposal`` and proving the persisted
    proposal record shows exactly that candidate revision once, unchanged;
(d) G6: the native flow drives a Git page AND model edit plus revision review
    through the native tools with verbatim envelopes, stopping at every human
    gate (source approval, admission).
"""

import asyncio
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest
from tau_agent.messages import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
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

from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.skill import ASSETS  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402 — the shared Git fixtures; no second oracle
    MODEL_YML,
    POLICY_PAGE,
    approved,
    complete_bundle_project,
    record_of,
)

from tests.test_authoring import scaffold_project  # noqa: E402 — legacy-route fixture

AUTHORING_TOOLS = {
    "start_proposal",
    "read_artifact",
    "edit_proposal",
    "propose_sources",
    "inputs",
    "upload_document",
    "validate_proposal",
    "refresh_schema",
    "inspect_mapping",  # K3 (issue #43): bounded mapping inspection + receipts
    "resolve_term",  # K2 (issue #42): read-only candidate term resolution
    "review_proposal",
    "read_skill_reference",
}

SPEC_CONTENT = "# Spec\n\nAll events count; label is not a key.\n"

ANSWER_WAITING = """\
Source proposal committed into the candidate registry with the exact resolved
digest reported above. Nothing is measurable until approval. I am stopping
here: the operator approves the exact resolved digest outside this session; I
have no tool that approves, and none exists.
"""

ANSWER_REVIEWED = """\
The proposal is validated at its exact final revision — nothing is admitted.
The exact revision and review digest are the ones review_proposal returned
above; I report them and stop. Admission is human-only (ariadne-admit) and
happens outside this session; authoring never serves.
"""

ANSWER_SAVED = """\
The bounded prefix inspection returned its receipt, and I saved the labeled
hypothesis `local-to-global-prefix` (claim: hypothesis, receipt cited) through
the revision-checked page edit automatically — a labeled finding needs no
per-save prompt; only unresolved meaning goes to the owner. The candidate
validated at the exact final revision above and the review digest is exact: I
report both and stop. Admission is human-only (ariadne-admit) and happens
outside this session; nothing here confirms the mapping.
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


def result_of(events: list, tool: str) -> dict:
    """The verbatim JSON payload of the first activity of one tool."""
    return json.loads(
        next(
            event.result
            for event in events
            if isinstance(event, ToolActivity) and event.tool == tool
        )
    )


class FlowProvider(FakeProvider):
    """Scripted turns pulled from a queue: the test scripts each next turn
    AFTER seeing the previous tool results (proposal IDs and revisions are
    runtime data the tools return), still driving the real harness loop. A
    scripted entry may also be a CALLABLE of the harness transcript: the turn
    is then built from the tool results the provider actually received — how
    a real model cites runtime data (a receipt id, the current expected
    revision) it just read."""

    def __init__(self) -> None:
        super().__init__([])
        self._turns: list[list | Callable[[list], list]] = []

    def script(self, stream: list | Callable[[list], list]) -> None:
        self._turns.append(stream)

    def stream_response(
        self, *, model, system, messages, tools, signal=None, session_id=None
    ):
        if not self._turns:
            raise AssertionError("the scripted flow ran out of turns")
        stream = self._turns.pop(0)
        if callable(stream):
            stream = stream(list(messages))
        self.calls.append((model, system, list(messages), list(tools)))
        self.session_ids.append(session_id)

        async def replay():
            for event in stream:
                if signal is not None and signal.is_cancelled():
                    return
                yield event

        return replay()


def last_result(messages: list, tool: str) -> dict:
    """The verbatim JSON payload of the NEWEST result of one tool in the
    transcript the harness hands the provider."""
    for message in reversed(messages):
        if isinstance(message, ToolResultMessage) and message.tool_name == tool:
            return json.loads(message.text)
    raise AssertionError(f"no {tool} result reached the provider yet")


class EditThenIdleProvider(FakeProvider):
    """First response replays the scripted edit turn (it executes and
    completes); the SECOND response is an async-generator stream that idles
    (bounded) until the run is cancelled — a deterministic in-flight turn
    right after a completed proposal edit. Later responses come from the
    queued scripted streams."""

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


def _extra_parquet(project: Path) -> Path:
    """One additional real parquet source the proposal appends to the registry
    (the root fixtures' writer)."""
    path = project / "data" / "extra_notes.parquet"
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1, 'n1')) t(id, note)) "
        f"TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


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


def test_authoring_git_flow_stops_at_every_human_gate(tmp_path):
    """(d) The G6 migration's own regression: the fake-provider path drives a
    Git PAGE and MODEL edit plus revision review through the native tools —
    the complete-bundle submission is gone — retaining verbatim envelopes and
    stopping at the source-approval and admission gates. The operator's
    approval runs in this test harness between the runs, outside the agent."""
    project = complete_bundle_project(tmp_path / "proj")
    extra_parquet = _extra_parquet(project)
    api = AuthoringProject(project)
    provider = FlowProvider()
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )
    try:
        # Run 1: start the proposal and upload the evidence document.
        provider.script(turn(calls=[("start_proposal", {})]))
        provider.script(
            turn(calls=[("upload_document", {"name": "spec.md", "content": SPEC_CONTENT})])
        )
        provider.script(turn(text="proposal started; ready to propose sources"))
        events = asyncio.run(drive(session, "set up a proposal with the extra source"))
        started = result_of(events, "start_proposal")
        upload = result_of(events, "upload_document")
        proposal = started["proposal"]
        assert set(started) == {"proposal", "base_revision", "candidate_revision"}

        # Propose the extra source — then STOP: the operator approves the
        # exact resolved digest outside this session.
        provider.script(
            turn(
                calls=[
                    (
                        "propose_sources",
                        {
                            "proposal": proposal,
                            "expected_revision": started["candidate_revision"],
                            "sources": [
                                {
                                    "name": "extra_notes",
                                    "type": "parquet",
                                    "path": str(extra_parquet),
                                }
                            ],
                        },
                    )
                ]
            )
        )
        provider.script(turn(text=ANSWER_WAITING))
        events += asyncio.run(drive(session, "now propose the extra source"))
        proposed = result_of(events, "propose_sources")

        # OPERATOR approval, outside the agent, between the two runs — of the
        # CURRENT candidate revision (the registry edit advanced it).
        approved(api, project, {"proposal": proposal, "candidate_revision": proposed["revision"]})

        # Run 2: measured inputs, the page and model edits, validation at the
        # exact final revision, review — then stop WITHOUT admission.
        provider.script(
            turn(calls=[("inputs", {"proposal": proposal, "documents": ["spec.md"]})])
        )
        provider.script(
            turn(
                calls=[
                    (
                        "edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": proposed["revision"],
                            "edit": {
                                "kind": "page",
                                "section": "policies",
                                "name": "all-events-count",
                                "content": POLICY_PAGE.replace(
                                    "The rule body.", "The rule body, agent-revised."
                                ),
                            },
                        },
                    )
                ]
            )
        )
        provider.script(turn(text="page revised; model next"))
        events += asyncio.run(drive(session, "measure the inputs and revise the policy page"))
        inputs = result_of(events, "inputs")
        page = result_of(events, "edit_proposal")

        provider.script(
            turn(
                calls=[
                    (
                        "edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": page["revision"],
                            "edit": {
                                "kind": "model",
                                "name": "events",
                                "content": MODEL_YML.replace(
                                    "Events model", "Events model, agent-revised"
                                ),
                            },
                        },
                    )
                ]
            )
        )
        provider.script(turn(text="model revised; validate next"))
        events += asyncio.run(drive(session, "now revise the model"))
        edits = [
            event
            for event in events
            if isinstance(event, ToolActivity) and event.tool == "edit_proposal"
        ]
        model = json.loads(edits[-1].result)

        provider.script(
            turn(
                calls=[
                    (
                        "validate_proposal",
                        {"proposal": proposal, "expected_revision": model["revision"]},
                    )
                ]
            )
        )
        provider.script(turn(calls=[("review_proposal", {"proposal": proposal})]))
        provider.script(turn(text=ANSWER_REVIEWED))
        events += asyncio.run(drive(session, "validate and review the candidate"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == [
        "start_proposal",
        "upload_document",
        "propose_sources",
        "inputs",
        "edit_proposal",
        "edit_proposal",
        "validate_proposal",
        "review_proposal",
    ]
    assert all(event.is_error is False for event in activity)
    _start, _upload, _propose, _inputs, _page, _model, validate, review = (
        json.loads(event.result) for event in activity
    )

    # verbatim service envelopes: the typed source proposal, the bounded
    # measured inputs, revision-checked page and model edits
    assert proposed["changed"] is True and proposed["revision"] != started["candidate_revision"]
    assert len(proposed["source_digest"]) == 64
    assert "extra_notes" in {entry["name"] for entry in proposed["sources"]}
    assert inputs["profile"]["sources"][0]["name"] == "events"  # the approved registry
    assert inputs["documents"][0]["digest"] == upload["digest"]
    assert (
        inputs["documents"][0]["digest"]
        == hashlib.sha256(SPEC_CONTENT.encode("utf-8")).hexdigest()
    )
    assert inputs["seed_notes"]["complete"] is True
    assert page["changed"] is True and model["changed"] is True
    assert page["revision"] != started["candidate_revision"]
    assert model["revision"] != page["revision"]  # two distinct candidate revisions

    # validation at the exact final revision (the finalize commit may
    # advance it — the EXACT final commit is what validates); review binds it
    assert validate["ok"] is True and validate["errors"] == []
    assert record_of(project, proposal)["candidate_revision"] == validate["revision"]
    assert review == api.review_proposal(proposal)  # the verbatim review envelope
    assert review["revision"] == validate["revision"]
    assert review["report"]["ok"] is True

    # stop WITHOUT admission: no admission descriptor, no served snapshot
    assert not (project / ".ariadne" / "current.json").exists()
    assert not (project / ".ariadne" / "snapshots").exists()

    texts = [e.text for e in events if isinstance(e, AssistantText)]
    waiting = texts[1]  # the stop-after-propose answer
    assert "outside this session" in waiting, "the agent must stop at the approval gate"
    answer = texts[-1]
    lowered = answer.lower()
    assert "revision" in lowered and "admission" in lowered and "human" in lowered


def test_cancel_after_edit_never_replays_it(tmp_path):
    """Regression (c): cancelling the turn AFTER a completed proposal edit
    neither duplicates nor replays it — exactly one edit executed, the
    persisted proposal record still shows that candidate revision — and the
    session stays usable for a follow-up run that edits nothing."""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    started = api.start_proposal()
    edit = {
        "kind": "page",
        "section": "policies",
        "name": "all-events-count",
        "content": POLICY_PAGE.replace("The rule body.", "The rule body, once."),
    }
    provider = EditThenIdleProvider(
        turn(
            calls=[
                (
                    "edit_proposal",
                    {
                        "proposal": started["proposal"],
                        "expected_revision": started["candidate_revision"],
                        "edit": edit,
                    },
                )
            ]
        ),
        [turn(text="edited exactly once; stopped")],
    )
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )

    async def scenario() -> list:
        events = []
        async for event in session.send("edit the policy page, then summarize"):
            events.append(event)
            if isinstance(event, ToolActivity) and event.tool == "edit_proposal":
                session.cancel()  # after the completed edit, mid next turn
        return events

    try:
        events = asyncio.run(asyncio.wait_for(scenario(), timeout=60))

        edits = [
            event
            for event in events
            if isinstance(event, ToolActivity) and event.tool == "edit_proposal"
        ]
        assert len(edits) == 1 and edits[0].is_error is False, (
            "cancellation must not duplicate or replay the edit"
        )
        edited = json.loads(edits[0].result)
        assert edited["changed"] is True
        record = record_of(project, started["proposal"])
        assert record["candidate_revision"] == edited["revision"], (
            "the persisted proposal shows exactly the one edit's revision"
        )
        assert any(isinstance(event, SessionError) for event in events), (
            "the cancelled turn ends with a typed error, not silence"
        )
        assert isinstance(events[-1], RunCompleted)

        # The session stays usable and still edits nothing new.
        follow = asyncio.run(drive(session, "status?"))
        assert any(isinstance(event, AssistantText) for event in follow)
        assert not any(isinstance(event, ToolActivity) for event in follow)
        assert record_of(project, started["proposal"]) == record
        assert provider._first is None and provider._second is False
    finally:
        session.close()


def test_authoring_surface_has_no_approval_or_admission_and_no_runtime(
    tmp_path, monkeypatch
):
    """Regression (a): the Authoring tool surface is exactly the AuthoringProject
    Git contract plus the bounded reference reader — no approval, no
    admission, no Promotion anywhere in the registered tools — and opening the
    session constructs NO AriadneRuntime (Authoring needs no query runtime)."""

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
    assert names == AUTHORING_TOOLS, "the Authoring role gets the Git contract ops"
    assert not any(
        marker in name for name in names for marker in ("approve", "promot", "admit", "reconcil")
    ), "no registered tool may approve sources, admit or Promote"
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


def test_native_resolve_term_reads_the_selected_candidate(tmp_path):
    """K2 (issue #42): the native ``resolve_term`` tool resolves the EXPLICITLY
    selected proposal's candidate revision (read-only, candidate identity
    visible) over the same core envelope as every other surface — the
    structured Reference the model authored through ``edit_proposal`` resolves
    with its exact bindings and an unconfirmed hypothesis."""
    events_resource = (
        "ariadne://table/WyJldmVudHMiLG51bGwsImV2ZW50cyIsImV2ZW50cyJd"  # events.events
    )
    reference = (
        "---\n"
        "type: reference\n"
        "title: Order number\n"
        "description: The shared order-number concept.\n"
        "tags: [reference, term]\n"
        "sources:\n"
        "  - id: seed-notes\n"
        "    resource: data/seed_notes.md\n"
        "ariadne:\n"
        "  version: 1\n"
        "  reference_role: term\n"
        "  representations:\n"
        "    - id: local-order-number\n"
        "      aliases: [order number, local order number]\n"
        "      fields:\n"
        f"        - resource: {events_resource}\n"
        "          column: id\n"
        "      scope: []\n"
        "    - id: global-order-number\n"
        "      aliases: [order number, global order number]\n"
        "      fields:\n"
        f"        - resource: {events_resource}\n"
        "          column: label\n"
        "      scope: []\n"
        "  mappings:\n"
        "    - id: local-to-global-prefix\n"
        "      family: prefix\n"
        "      from: local-order-number\n"
        "      to: global-order-number\n"
        "      claim: hypothesis\n"
        "      source_ids: [seed-notes]\n"
        "      receipt_ids: []\n"
        "---\n\n"
        "# Order number\n"
    )
    project = complete_bundle_project(tmp_path / "proj")
    provider = FlowProvider()
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )
    try:
        provider.script(turn(calls=[("start_proposal", {})]))
        provider.script(turn(text="proposal started"))
        events = asyncio.run(drive(session, "start a proposal"))
        started = result_of(events, "start_proposal")
        proposal = started["proposal"]

        provider.script(
            turn(
                calls=[
                    (
                        "edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": started["candidate_revision"],
                            "edit": {
                                "kind": "page",
                                "section": "references",
                                "name": "order-number",
                                "content": reference,
                            },
                        },
                    )
                ]
            )
        )
        provider.script(turn(text="reference page authored"))
        events = asyncio.run(drive(session, "author the order-number term reference"))
        edited = result_of(events, "edit_proposal")
        assert edited["changed"] is True

        provider.script(
            turn(
                calls=[
                    (
                        "resolve_term",
                        {"proposal": proposal, "request": "order number"},
                    )
                ]
            )
        )
        provider.script(turn(text="representations resolved; hypothesis unconfirmed"))
        events = asyncio.run(drive(session, "resolve the order number term"))
        resolved = result_of(events, "resolve_term")
        assert resolved["candidate"] is True
        assert resolved["revision"] == edited["revision"]
        assert [match["representation"] for match in resolved["matches"]] == [
            "local-order-number",
            "global-order-number",
        ]
        local = resolved["matches"][0]
        assert local["fields"][0]["column"] == "id"
        [mapping] = local["mappings"]
        assert mapping["claim"] == "hypothesis"
        assert mapping["confirmation"] == "unconfirmed"
    finally:
        session.close()


def test_native_refresh_schema_reports_flags_and_noops_on_identical_retry(tmp_path):
    """K1 (issue #41): the native ``refresh_schema`` tool drives the core
    operation with its verbatim envelope — generated page identities and
    schema-change flags over the operator-approved identity — and the model's
    identical retry observes the deterministic no-op (the revision does not
    move). No approval, admission or query tool is involved."""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    provider = FlowProvider()
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )
    asset = {"source": "events", "catalog": None, "schema": "events", "table": "events"}
    try:
        provider.script(turn(calls=[("start_proposal", {})]))
        provider.script(turn(text="proposal started"))
        events = asyncio.run(drive(session, "start a proposal"))
        started = result_of(events, "start_proposal")
        proposal = started["proposal"]
        # the OPERATOR's approval runs in the harness, outside the agent
        approved(api, project, started)

        provider.script(
            turn(
                calls=[
                    (
                        "refresh_schema",
                        {
                            "proposal": proposal,
                            "expected_revision": started["candidate_revision"],
                            "assets": [asset],
                        },
                    )
                ]
            )
        )
        provider.script(turn(text="schema pages generated; flags reported"))
        events = asyncio.run(drive(session, "refresh the events schema"))
        first = result_of(events, "refresh_schema")
        assert first["changed"] is True
        assert {page["kind"] for page in first["pages"]} == {"table", "dataset"}

        provider.script(
            turn(
                calls=[
                    (
                        "refresh_schema",
                        {
                            "proposal": proposal,
                            "expected_revision": first["revision"],
                            "assets": [asset],
                        },
                    )
                ]
            )
        )
        provider.script(turn(text="identical refresh was a no-op"))
        events = asyncio.run(drive(session, "refresh the same schema again"))
        second = result_of(events, "refresh_schema")
        assert second["changed"] is False and second["revision"] == first["revision"]
    finally:
        session.close()


def test_native_inspect_mapping_returns_the_core_receipt(tmp_path):
    """K3 (issue #43): the native ``inspect_mapping`` tool drives the shared
    core over the operator-approved sources and returns its verbatim receipt
    envelope — honest counts under the lowered sample bound, no raw
    identifier examples without the operator's sample permission — with no
    page edit, approval or confirmation anywhere in the flow (hypothesis
    capture stays K5)."""
    from tests.test_mapping_inspection import approved_project, prefix_candidate

    project, api, started = approved_project(tmp_path / "native")
    provider = FlowProvider()
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )
    try:
        provider.script(
            turn(
                calls=[
                    (
                        "inspect_mapping",
                        {
                            "proposal": started["proposal"],
                            "expected_revision": started["candidate_revision"],
                            "candidate": prefix_candidate(),
                            "limits": {"sample_rows": 3},
                        },
                    )
                ]
            )
        )
        provider.script(turn(text="receipt retained; reporting the honest counts"))
        events = asyncio.run(drive(session, "inspect the prefix mapping candidate"))
    finally:
        session.close()

    result = result_of(events, "inspect_mapping")
    twin = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        prefix_candidate(),
        limits={"sample_rows": 3},
    )
    receipt = result["receipt"]
    assert result["proposal"] == started["proposal"]
    assert receipt["counts"] == twin["receipt"]["counts"]
    assert receipt["coverage"] == twin["receipt"]["coverage"]
    assert receipt["unknown_lookup_count"] == 1
    assert receipt["comparison_basis"] == "containment-only"
    assert receipt["designation"] == "sampled"
    assert receipt["receipt_id"].startswith("mr-")
    assert Path(result["evidence"]).is_file()
    assert "examples" not in receipt  # no sample permission was granted
    assert "123123" not in json.dumps(result)


def test_mapping_hypothesis_is_saved_without_prompt_and_reused_after_session_restart(
    tmp_path,
):
    """K5 (issue #45), the red seam: ONE scripted run over a real temporary
    Git proposal requests the bounded inspection, then AUTOMATICALLY saves
    the labeled hypothesis through the existing complete-page edit at the
    current expected revision — no per-save prompt anywhere in the run —
    validates and stops at review; a SECOND session (a restart: a new harness
    with NO chat memory) reads the saved mapping AND its retained receipt
    through ``resolve_term`` without rediscovery, the identical re-save of the
    same stable mapping identity is a no-op, and a stale expected revision is
    refused without a blind write replay or any evidence/repair reset (spec
    0010 §8, §10 AC7; the predecessor stale/concurrent/interrupted-transition
    checks stay in their own suites — reused, not duplicated here)."""
    from tests.test_mapping_inspection import (
        REFERENCE_EDIT,
        approved_project,
        prefix_candidate,
        reference_page,
    )

    project, api, started = approved_project(tmp_path / "restart")
    proposal = started["proposal"]
    provider = FlowProvider()
    session = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider
    )
    try:
        # ONE user run: inspect -> automatic save -> validate -> review -> stop.
        # The save/validate turns are built FROM the transcript (callable
        # turns): the receipt id and the current expected revision are runtime
        # data the earlier tools returned — the capture needs no permission
        # turn between the inspection and the save.
        provider.script(
            turn(
                calls=[
                    (
                        "inspect_mapping",
                        {
                            "proposal": proposal,
                            "expected_revision": started["candidate_revision"],
                            "candidate": prefix_candidate(),
                            "limits": {"sample_rows": 3},
                        },
                    )
                ]
            )
        )
        provider.script(
            lambda messages: turn(
                calls=[
                    (
                        "edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": last_result(
                                messages, "inspect_mapping"
                            )["revision"],
                            "edit": {
                                **REFERENCE_EDIT,
                                "content": reference_page(
                                    last_result(messages, "inspect_mapping")["receipt"][
                                        "candidate"
                                    ],
                                    [last_result(messages, "inspect_mapping")["receipt_id"]],
                                ),
                            },
                        },
                    )
                ]
            )
        )
        provider.script(
            lambda messages: turn(
                calls=[
                    (
                        "validate_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": last_result(messages, "edit_proposal")[
                                "revision"
                            ],
                        },
                    )
                ]
            )
        )
        provider.script(turn(calls=[("review_proposal", {"proposal": proposal})]))
        provider.script(turn(text=ANSWER_SAVED))
        events = asyncio.run(
            drive(
                session,
                "does the local order number construct the global order number? "
                "investigate, record the finding, then validate and review",
            )
        )
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == [
        "inspect_mapping",
        "edit_proposal",
        "validate_proposal",
        "review_proposal",
    ]
    assert all(event.is_error is False for event in activity)
    inspected, edited, validate, review = (json.loads(e.result) for e in activity)

    # verbatim envelopes: the retained receipt of the bounded inspection, the
    # revision-checked automatic save, validation at the exact final revision
    receipt = inspected["receipt"]
    assert receipt["receipt_id"].startswith("mr-")
    assert receipt["designation"] == "sampled" and receipt["sample_rows"] == 3
    assert edited["changed"] is True
    assert edited["revision"] != started["candidate_revision"]
    assert validate["ok"] is True and validate["errors"] == []
    assert record_of(project, proposal)["candidate_revision"] == validate["revision"]
    assert review["revision"] == validate["revision"]
    assert review["report"]["ok"] is True
    evidence_path = Path(inspected["evidence"])  # the retained receipt
    assert evidence_path.is_file()  # ...outlives the session that measured it
    assert not (project / ".ariadne" / "current.json").exists()  # no admission
    answer = " ".join(
        [e.text for e in events if isinstance(e, AssistantText)][-1].split()
    )
    assert "no per-save prompt" in answer and "automatically" in answer

    # ---------------- the restart: a SECOND session, NO chat memory ---------
    provider2 = FlowProvider()
    session2 = open_session(
        role="authoring", project=project, model="fake-authoring", provider=provider2
    )
    assert session2.messages == ()  # chat memory is never durable
    try:
        # reads the saved mapping/receipt — resolve_term only, no re-inspection
        provider2.script(
            turn(
                calls=[
                    (
                        "resolve_term",
                        {"proposal": proposal, "request": "local order number"},
                    )
                ]
            )
        )
        provider2.script(
            turn(text="the saved hypothesis and its cited receipt are already there")
        )
        events2 = asyncio.run(
            drive(session2, "what do we already know about the order numbers?")
        )

        # identical rediscovery: read the saved page, re-save it unchanged
        provider2.script(
            turn(calls=[("read_artifact", {"proposal": proposal, **REFERENCE_EDIT})])
        )
        provider2.script(
            lambda messages: turn(
                calls=[
                    (
                        "edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": last_result(messages, "read_artifact")[
                                "revision"
                            ],
                            "edit": {
                                **REFERENCE_EDIT,
                                "content": last_result(messages, "read_artifact")[
                                    "content"
                                ],
                            },
                        },
                    )
                ]
            )
        )
        provider2.script(
            turn(text="identical re-save: a no-op on the same mapping identity")
        )
        events2 += asyncio.run(
            drive(session2, "re-record the same finding to be sure it sticks")
        )

        # stale-revision refusal: the pre-save revision is long stale by now
        read_result = next(
            json.loads(event.result)
            for event in events2
            if isinstance(event, ToolActivity) and event.tool == "read_artifact"
        )
        provider2.script(
            turn(
                calls=[
                    (
                        "edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": started["candidate_revision"],
                            "edit": {
                                **REFERENCE_EDIT,
                                "content": read_result["content"],
                            },
                        },
                    )
                ]
            )
        )
        provider2.script(
            turn(text="refused: stale revision — I re-read instead of replaying the write")
        )
        events2 += asyncio.run(
            drive(session2, "and save it once more at the original revision")
        )
    finally:
        session2.close()

    tools2 = [e.tool for e in events2 if isinstance(e, ToolActivity)]
    assert "inspect_mapping" not in tools2, "the restart must not rediscover"
    assert tools2 == ["resolve_term", "read_artifact", "edit_proposal", "edit_proposal"]
    by_tool: dict[str, list[ToolActivity]] = {}
    for event in events2:
        if isinstance(event, ToolActivity):
            by_tool.setdefault(event.tool, []).append(event)

    # the saved mapping AND its receipt, read back from Git/evidence state
    resolved = json.loads(by_tool["resolve_term"][0].result)
    assert resolved["candidate"] is True
    assert resolved["revision"] == validate["revision"]
    [match] = resolved["matches"]
    assert match["representation"] == "local-order-number"
    [mapping] = match["mappings"]
    assert mapping["id"] == "local-to-global-prefix"  # the SAME stable identity
    assert mapping["claim"] == "hypothesis"
    assert mapping["confirmation"] == "unconfirmed"  # never relabeled
    assert mapping["receipt_ids"] == [receipt["receipt_id"]]
    [view] = mapping["evidence"]  # the verified summary of the retained receipt
    assert view["id"] == receipt["receipt_id"]
    assert view["designation"] == "sampled" and view["outcome"] == "complete"
    assert view["freshness"]["state"] == "as_of"

    assert read_result["path"] == "context_layer/references/order-number.md"
    assert read_result["complete"] is True
    assert "ariadne_evidence" in read_result["content"]  # the attached summary
    resave = json.loads(by_tool["edit_proposal"][0].result)
    assert resave["changed"] is False and resave["revision"] == validate["revision"]

    stale = by_tool["edit_proposal"][1]
    assert stale.is_error is True
    assert "stale revision" in stale.result and "nothing was written" in stale.result

    record = record_of(project, proposal)
    assert record["candidate_revision"] == validate["revision"]  # no blind replay
    assert record["repair"] == {"attempts": 1, "status": "open"}  # never reset
    assert evidence_path.is_file()  # the evidence survives the refused replay

    # the loop TEACHES the capture behavior (the guidance IS the agent loop):
    # read-first, automatic save without a per-save prompt, stable IDs with a
    # no-op retry, honest retention, stale-revision stop, restart honesty.
    _model, system2, _messages, _tools = provider2.calls[0]
    flat = " ".join(system2.split())
    for phrase in (
        "before drafting",  # read existing knowledge FIRST
        "Do not rediscover a rule a saved hypothesis already records",
        "no per-save prompt",
        "identical retry is a no-op",
        "never relabel",
        "stale revision",
        "raw fact-to-fact join",
        "unresolved meaning",
        "chat memory",  # restart reads Git/evidence state, never chat memory
    ):
        assert phrase in flat, f"the Authoring guidance must teach: {phrase!r}"
