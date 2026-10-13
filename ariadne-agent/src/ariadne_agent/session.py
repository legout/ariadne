"""The in-memory agent session (spec 2026-09-29-0006, ADR-0014).

One session binds one configured project, one role, and one model for its
whole lifetime; another role or project requires a NEW session, with no silent
transfer of the prior transcript or tool access. Messages live only in this
process — a restart loses them, and no fake resume operation exists. The event
stream is typed for Python callers (a later UI adapter translates it): the
harness's own events never leak through this interface.

The host selects everything up front: the project root, the role, the model
name, and a fully configured provider (identity, endpoint and credentials are
constructed by the operator outside user messages and data-project artifacts).
No ambient working-directory selection, no user-message-selected project root,
no model-supplied credentials.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from ariadne.discovery import DiscoveryRuntime
from ariadne.query import DeferredQueryRuntime, QueryRuntime
from tau_agent.events import (
    AgentEndEvent,
    MessageEndEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from tau_agent.harness import AgentHarness, AgentHarnessConfig
from tau_agent.messages import AgentMessage, AssistantMessage
from tau_agent.provider import ModelProvider

from ariadne_agent.analyst import analyst_tools
from ariadne_agent.authoring import authoring_tools
from ariadne_agent.mcp_tools import McpSettings, SessionMcp
from ariadne_agent.skills import analyst_guidance, authoring_guidance

ROLES = ("analyst", "authoring")  # one more role per session contract (A2/#24)

# The Analyst flow, verbatim from the spec's role rules: discovery before
# routing, context before novelty, honest governed/ad-hoc labeling.
_ANALYST_RULES = """\

## Role: Ariadne Analyst

You answer questions about this one configured project through its native
tools only.

- Discover promoted metrics (`list_metrics`) before choosing a route; if a
  governed metric answers the question, query it governed (`get_metric`).
- For a novel business question, search the served Context Layer first
  (`search_context`) and restate the guidance it returns.
- Report governed values with the actual metric/Policy paths and every caveat
  the tool returned, including pending attestation when present. Say
  `governed: true` and mean Promoted, not independently value-attested.
- If no metric fits, inspect the registered datasets (`list_datasets`) and
  send a definition through the compile gate (`define_metric`). Report
  `governed: false` and the staged proposal status; never claim a Context
  Layer page alone makes an ad-hoc calculation governed.
- Resolve shared terminology before novel definitions (`resolve_term`): it
  returns the documented concept/representation alternatives with their exact
  field bindings, required scope and mapping claim/confirmation status — a
  mapping is confirmed ONLY by recorded human admission evidence, hypotheses
  stay unconfirmed leads — plus the page/source citations and AS-OF evidence
  freshness to report. Whole aliases/phrases match case-insensitively, never
  substrings; a language alias never authorizes a join or a transform.
- A context-only admitted project (schemas/References, no metrics yet) still
  serves discovery: search the context and resolve terms; metric tools then
  report the specific missing-catalog error. You cannot confirm mappings,
  approve sources, promote, bypass the compile gate, or run SQL yourself.
"""

# The Authoring flow over the Git proposal contract (spec 2026-10-02-0009
# §3–4, migrated in G6/issue #38): work before the first admission, human-only
# approval/admission outside the session.
_AUTHORING_RULES = """\

## Role: Ariadne Authoring

You author one data project through its Git authoring proposals, which may
have nothing admitted yet.

- Start a proposal (`start_proposal`), then propose inert source entries
  (`propose_sources`) and report the exact resolved digest the service
  returns, then STOP for sources: the operator approves the exact digest
  outside this session. You have no tool that approves, and none exists.
- After the operator approves, read the measured inputs in bounded parts
  (`inputs`); where evidence does not establish a business rule, ask the
  owner or mark the uncertainty — never invent a rule.
- Regenerate physical schema facts explicitly (`refresh_schema`) with the
  current expected revision and an explicit catalog asset list: it reads only
  the operator-approved resolved source identity, preserves authored meaning
  only for identical column identity/type, and reports schema-change flags.
  The generated Schema/Observations blocks are core-owned — author meaning
  around them, never inside them; an identical refresh is a no-op.
- Read the terminology that already exists before drafting (`resolve_term`
  over the selected proposal) and read the candidate's pages
  (`read_artifact`) FIRST: documented representations, schemas, mapping
  hypotheses with their claim status, cited receipts and freshness, and the
  cited domain evidence. Reuse a matching representation or mapping ID —
  never invent measured counts, receipts or confirmation states, and never
  treat an alias as join permission. Do not rediscover a rule a saved
  hypothesis already records.
- Measure bounded mapping candidates explicitly (`inspect_mapping`): a
  structured candidate object (equality/prefix/lookup), only after the
  operator approved the sources, only lowering the finite ceilings. Report
  the receipt's honest counts, coverage, collisions and limitations — a
  sampled match is never a business rule, raw identifier examples need the
  operator's explicit sample permission, and a failed or inconclusive result
  stays honest. Save the labeled hypothesis immediately and automatically
  through `edit_proposal` citing the receipt id — there is no per-save
  prompt; never fabricate a receipt, count or confirmation.
- Capture automatically and honestly (spec 0010 §8): a labeled finding saves
  itself through the revision-checked `edit_proposal` at the current expected
  revision; the owner answers unresolved meaning — business meaning, format,
  scope — never permission for a hypothesis save. Reuse the stable
  concept/representation/mapping IDs a repeated finding reproduces (an
  identical retry is a no-op; never mint suffixed duplicates); preserve
  failed, inconclusive and conflicting results as their own labeled
  hypotheses with their receipts — never relabel inconclusive or negative
  evidence asserted or confirmed. On a stale revision, stop and re-read the
  candidate: never replay a write blindly. Policy/OSI edits wait until the
  meaning and scope are established, and the existing compile/Grain/live
  gates still apply — never a local-number-only or raw fact-to-fact join from
  an alias or sample.
- A restart reads Git/evidence state, not chat memory: this transcript is
  in-memory only and never durable — a new session re-reads the proposal's
  pages, hypotheses and retained receipts (`resolve_term`, `read_artifact`)
  instead of relying on remembering anything.
- Edit artifacts independently (`edit_proposal`) with the expected candidate
  revision each time: one complete model, graph, page or Seed Notes edit —
  unchanged artifacts are inherited from the base, never resubmitted. A
  stale revision or a competing writer is refused; read the artifact first
  (`read_artifact`) when unsure.
- Validate the effective candidate (`validate_proposal`) and read its review
  (`review_proposal`); report the EXACT revision and review digest, and
  stop: admission is human-only (`ariadne-admit`) and happens outside this
  session. Validation and review are never a signoff; nothing you do serves
  the project.
- The grain rubric above governs every join: many-to-one on a key unique on
  the joined side, or one of its five resolution patterns.
"""


@dataclass(frozen=True, slots=True)
class AssistantText:
    """One assistant message's text (an event per assistant message)."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolActivity:
    """One completed tool execution with its verbatim JSON payload."""

    tool: str
    args: dict
    result: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class SessionError:
    """A failed or aborted model turn (a tool failure is ToolActivity)."""

    message: str


@dataclass(frozen=True, slots=True)
class RunCompleted:
    """The run finished (including after cancellation or an error turn)."""

    stop_reason: str


AgentSessionEvent = AssistantText | ToolActivity | SessionError | RunCompleted


def _missing_served_catalog(exc: BaseException) -> bool:
    """The runtime's promoted-catalog startup errors. The message text is owned
    by ariadne-data's query.py (QueryRuntime; formerly runtime.py).
    ariadne.serve holds the same predicate but is the optional server transport
    — importing it here would defeat this package's no-server guarantee, so the
    two substrings are restated."""
    message = str(exc)
    return "promote staging/semantic_layer/ first" in message or (
        "no governed metrics found under" in message
    )


def _open_runtime(
    project: Path,
    *,
    runtime_type: type[QueryRuntime] | type[DiscoveryRuntime] = QueryRuntime,
    discovery: DiscoveryRuntime | None = None,
) -> QueryRuntime | DiscoveryRuntime:
    """Build the session's runtime from the host-selected project root only.

    A MANAGED Git data project — one carrying Ariadne's operator state (the
    ignored ``.ariadne/`` directory its Git proposals/admissions create, plan
    §2; never mere ``.git`` presence, which a legacy checkout also has) —
    resolves through :meth:`QueryRuntime.open_project` (issue #38/G6): its
    pinned human-admitted snapshot and approved source identity, refusing a
    project with no valid admission instead of falling back to mutable
    files. An explicit legacy artifact-root project (no Ariadne state) keeps
    the legacy construction and its behavior exactly."""
    managed = (
        discovery._managed is not None if discovery is not None else (project / ".ariadne").exists()
    )
    if managed:
        try:
            if discovery is not None:
                return QueryRuntime.open_project(project, discovery=discovery)
            return runtime_type.open_project(project)
        except Exception as exc:
            raise RuntimeError(
                f"analyst session for {project} cannot query the managed Git "
                f"project — {exc}. Report this to the operator; admission is "
                "human-only and the Analyst cannot query, define, or admit its "
                "way past it."
            ) from exc
    registry = project / "ariadne.yaml"
    db = project / "demo.db"
    if not registry.is_file() and not db.is_file():
        raise RuntimeError(
            f"project {project} has neither {registry.name} nor {db.name} — the "
            "host must configure the project before opening a session"
        )
    try:
        return runtime_type(
            project / "semantic_layer",
            project / "context_layer",
            db,
            staging_dir=project / "staging",
            sources=registry if registry.is_file() else None,
        )
    except RuntimeError as exc:
        if _missing_served_catalog(exc):
            raise RuntimeError(
                f"analyst session for {project} has no promoted catalog to query "
                f"— {exc}. A human must promote the staged catalog; promotion is "
                "human-only and the Analyst cannot query, define, or promote its "
                "way past an empty catalog. Report this to the operator."
            ) from exc
        raise


class AgentSession:
    """One fixed-role, fixed-project, fixed-model conversation, in memory.

    ``send`` yields the run's typed events asynchronously; at most one run is
    active at a time. Messages survive only in this process; there is no
    resume — a restart starts a new, empty session. Cancelling ends the
    current model turn cooperatively; an in-flight tool call may still finish.
    """

    def __init__(
        self,
        *,
        role: str,
        project: Path,
        model: str,
        runtime: DeferredQueryRuntime | None = None,
        harness: AgentHarness,
        mcp: SessionMcp | None = None,
    ) -> None:
        self._role = role
        self._project = project
        self._model = model
        self._runtime = runtime
        self._harness = harness
        self._mcp = mcp
        self._active = False
        self._closed = False
        # cancel()/close() can arrive between send() and the first
        # consumption — before the harness creates its cancellation token.
        # The request is remembered here so _drive() honours it before any
        # model turn can start (send() clears it when reserving a new run).
        self._cancel_requested = False

    @property
    def role(self) -> str:
        return self._role

    @property
    def project(self) -> Path:
        return self._project

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_running(self) -> bool:
        return self._active

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """This session's in-memory transcript (empty in any new session)."""
        return self._harness.messages

    def send(self, text: str) -> AsyncIterator[AgentSessionEvent]:
        """Run one user message to completion, yielding typed events.

        Raises ``RuntimeError`` when the session is closed or a run is already
        active (one run per session; await it or ``cancel`` first)."""
        if self._closed:
            raise RuntimeError("session is closed — open a new session")
        if self._active:
            raise RuntimeError(
                "session already has an active run — one run per session; "
                "await the current send() or cancel() it first"
            )
        self._active = True
        self._cancel_requested = False
        return self._drive(text)

    async def _drive(self, text: str) -> AsyncIterator[AgentSessionEvent]:
        # Tool args live on the start event only (the end event carries the
        # result), so the in-flight call's args are carried across.
        pending_args: dict[str, dict] = {}
        try:
            if self._cancel_requested or self._closed:
                # The run was cancelled or the session closed between send()
                # and the first consumption, when the harness cancellation
                # token did not exist yet: terminate without starting any
                # model turn (a tool could otherwise still stage a proposal).
                message = (
                    "session closed before the run started"
                    if self._closed
                    else "run cancelled before it started"
                )
                yield SessionError(message=message)
                yield RunCompleted(stop_reason="aborted")
                return
            async for event in self._harness.prompt(text):
                if isinstance(event, ToolExecutionStartEvent):
                    pending_args[event.tool_call_id] = dict(event.args)
                    continue
                for typed in _translate(event, pending_args):
                    yield typed
        finally:
            self._active = False

    def cancel(self) -> None:
        """End the active run's subsequent model turns (cooperative). A run
        that was reserved but not yet consumed is never started at all."""
        if self._active:
            # The reserved run may not have reached the harness token yet.
            self._cancel_requested = True
        self._harness.cancel()

    def close(self) -> None:
        """Release the session's resources; the session refuses further sends.

        MCP children are reaped here; a call already executing finishes or
        times out under the MCP client's bounded request timeout — immediate
        interruption is not promised."""
        if self._closed:
            return
        self._closed = True
        self._harness.cancel()
        if self._mcp is not None:
            self._mcp.shutdown()
        if self._runtime is not None:  # Authoring sessions own no query runtime
            self._runtime.close()


def _translate(event: object, pending_args: dict[str, dict]) -> list[AgentSessionEvent]:
    """Map one harness event onto the typed session surface (deltas collapse
    into per-message events; tool activity carries the verbatim payload)."""
    if isinstance(event, MessageEndEvent) and isinstance(event.message, AssistantMessage):
        message = event.message
        if message.stop_reason in {"error", "aborted"}:
            return [SessionError(message=message.error_message or message.stop_reason)]
        if message.text:
            return [AssistantText(text=message.text)]
        return []
    if isinstance(event, ToolExecutionEndEvent):
        return [
            ToolActivity(
                tool=event.tool_name,
                args=pending_args.pop(event.tool_call_id, {}),
                result=event.result.text,
                is_error=event.is_error,
            )
        ]
    if isinstance(event, AgentEndEvent):
        stop_reason = "stop"
        for message in reversed(event.messages):
            if isinstance(message, AssistantMessage):
                stop_reason = message.stop_reason
                break
        return [RunCompleted(stop_reason=stop_reason)]
    return []


def _attach_mcp(mcp_settings: McpSettings | None, role: str, tools: list) -> SessionMcp | None:
    """Attach this session's role-restricted MCP proxy after the native tools.

    No MCP settings means exactly the native surface; a role with an empty
    operator allowlist gets no proxy tool at all (issue #25). The native
    Analyst/Authoring tool sets are never altered by this attachment."""
    if mcp_settings is None:
        return None
    session_mcp = SessionMcp(mcp_settings, role)
    proxy = session_mcp.proxy_tool()
    if proxy is not None:
        tools.append(proxy)
    return session_mcp


def open_session(
    *,
    role: str,
    project: str | Path,
    model: str,
    provider: ModelProvider,
    skill_roots: Sequence[str | Path] = (),
    mcp_settings: McpSettings | None = None,
) -> AgentSession:
    """Open one in-memory session for a role, a configured project, and a model.

    The host supplies the fully configured provider (identity, endpoint,
    credentials) outside any user message. A different role, project, or model
    requires a new session. ``skill_roots`` declares the role-scoped trusted
    skill roots a host adds alongside the packaged skill (Authoring reads
    bounded references through them); no global scan ever happens.
    ``mcp_settings`` optionally declares the host-validated stdio MCP servers,
    cache root and per-role qualified-tool allowlist — one restricted registry
    per session, absent by default so the native surface is unchanged
    (issue #25)."""
    if role not in ROLES:
        raise ValueError(
            f"unknown role {role!r}; this build serves {ROLES} — a different "
            "role needs a new session in a build that provides it"
        )
    root = Path(project).resolve()
    if role == "authoring":
        # Authoring works in a project with nothing Promoted yet and builds NO
        # query runtime (spec 2026-09-29-0006 acceptance 2): the Analyst's
        # missing-catalog failure is session-local and never blocks this open.
        roots = [Path(extra).resolve() for extra in skill_roots]
        tools = authoring_tools(root, roots)
        session_mcp = _attach_mcp(mcp_settings, role, tools)
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model=model,
                system=authoring_guidance() + _AUTHORING_RULES,
                tools=tools,
            )
        )
        return AgentSession(role=role, project=root, model=model, harness=harness, mcp=session_mcp)
    discovery = _open_runtime(root, runtime_type=DiscoveryRuntime)

    def query_runtime() -> QueryRuntime:
        runtime = _open_runtime(root, discovery=discovery)
        assert isinstance(runtime, QueryRuntime)
        return runtime

    runtime = DeferredQueryRuntime(query_runtime, discovery)
    system = analyst_guidance() + _ANALYST_RULES
    tools = analyst_tools(runtime)
    session_mcp = _attach_mcp(mcp_settings, role, tools)
    harness = AgentHarness(
        AgentHarnessConfig(
            provider=provider,
            model=model,
            system=system,
            tools=tools,
        )
    )
    return AgentSession(
        role=role,
        project=root,
        model=model,
        runtime=runtime,
        harness=harness,
        mcp=session_mcp,
    )
