"""A1 Analyst session over native Ariadne tools (issue #23, spec 2026-09-29-0006;
migrated to the Git-only core, issue #73: sessions are admission-bound through
the project factories — DiscoveryRuntime.open_project/QueryRuntime.open_project
— following the core serve.py DeferredQueryRuntime pattern).

Deterministic and offline: a scripted ``tau_ai.fake.FakeProvider`` drives the
real ``tau_agent.AgentHarness`` loop, the real Analyst tool wrappers, and a
real ADMITTED temporary Git data project built from the retail-demo golden
models/pages (``tests/test_evals.py``/``tests/test_serve.py`` golden text) —
the same fixtures the root suite's oracle uses. Numbers use the SAME
independent-SQL oracle as the root suite (imported from
``tests/test_evals.py``); no second numeric oracle exists in this file.

Real regressions named by the ticket:

(a) ``get_metric`` returns numeric rows but loses Policy context — covered by
    requiring the governed tool payload to carry the admitted metric page and
    the full bodies of every cited Policy, and the answer to state the caveats
    and cite only Policy paths the tool actually returned;
(b) an unmodeled answer presents ad-hoc output as governed — covered by
    requiring ``governed: false``, the not-saved persistence status, and
    citations drawn from the actual ``search_context`` result in the unmodeled
    answer.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime
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

AGENT_DIR = Path(__file__).resolve().parents[1]
PRODUCT_AREA = AGENT_DIR.parents[1]  # products/ariadne (spec 0031 §2)
CORE_MEMBER = AGENT_DIR.parent / "ariadne-data"  # the sibling Core member
if str(CORE_MEMBER) not in sys.path:  # reuse the Core member suite's fixtures and oracle
    sys.path.insert(0, str(CORE_MEMBER))

from ariadne.skill import ASSETS  # noqa: E402
from ariadne.sources import table_resource  # noqa: E402
from tests.test_evals import (  # noqa: E402 — the shared oracle; no second one here
    _JOIN_SOURCE,
    _MEAN_EXPR,
    ADHOC_ENTRY,
    CUSTOMERS_MODEL,
    TOLERANCE,
    independent_adhoc_means,
    independent_expected,
)
from tests.test_git_admission import admit, admitted_ready  # noqa: E402 — the G5 human journey
from tests.test_git_authoring import (  # noqa: E402 — the shared Git fixtures
    POLICY_PAGE,
    approved,
    complete_bundle_project,
    run_git,
)
from tests.test_seed import run_seed  # noqa: E402
from tests.test_serve import (  # noqa: E402 — the recorded golden OKF pages
    GOLDEN_OKF,
    GOLDEN_OSI,
    GOLDEN_POLICY_EMEA,
    GOLDEN_POLICY_STATUS,
)

ANALYST_TOOLS = {
    "list_metrics",
    "search_context",
    "get_metric",
    "list_datasets",
    "define_metric",
    "resolve_term",  # K2 (issue #42): alongside the five baseline tools
    "list_context_pages",  # spec 0015 (issue #60): token-free page listing
    "read_context_page",  # spec 0015 (issue #60): path-addressed page reading
    "discover",  # spec 0018 (issue #64): grouped artifact-only discovery
}

ANSWER_GOVERNED = """\
Governed answer (governed: true): gross margin by region from the admitted
catalog. Caveats, from the admitted context actually returned: CANCELLED and
RETURNED orders are excluded from revenue, cost and order count
(policies/order-status-billing.md), and pre-2024 EMEA orders are converted
to USD with rate_to_usd before aggregating
(policies/emea-currency-cutover.md); admitted metric page
context_layer/metrics/gross_margin.md.
"""

ADHOC_DEFINITION = {
    "name": ADHOC_ENTRY["metric"],
    "description": "Mean billable order amount per customer in USD",
    # The admitted registry qualifies the sqlite relations (demo.main.*): the
    # ad-hoc IO-authority boundary reads only registered catalog relations.
    "source": _JOIN_SOURCE.replace("FROM orders o", "FROM demo.main.orders o").replace(
        "LEFT JOIN currency_conversion_rate r", "LEFT JOIN demo.main.currency_conversion_rate r"
    ),
    "expression": _MEAN_EXPR,
    "dimensions": ADHOC_ENTRY["dimensions"],
}

ANSWER_UNMODELED = """\
No governed metric answers this, so I searched the admitted context first
(search_context), inspected the registered tables (list_datasets), and defined
an ad-hoc metric through the compile gate (define_metric). Policy guidance
actually returned by the search: CANCELLED and RETURNED orders are not revenue
(policies/order-status-billing.md). governed: false — the result is ephemeral
(persistence: not_saved, nothing was written anywhere); retaining the
definition is a separate human Git authoring step, and it is not a governed
metric.
"""


# --- scripted fake model ------------------------------------------------------


def turn(*, text: str | None = None, calls: list[tuple[str, dict]] | None = None) -> list:
    """One scripted assistant response: tool calls, final text, or both."""
    calls = calls or []
    content: list = [TextContent(text=text)] if text else []
    content += [
        ToolCall(id=f"call_{index}", name=name, arguments=dict(args))
        for index, (name, args) in enumerate(calls)
    ]
    stop = "toolUse" if calls else "stop"
    message = AssistantMessage(model="fake-analyst", content=content, stop_reason=stop)
    return [AssistantDoneEvent(reason=stop, message=message)]


async def drive(session, text: str) -> list:
    """Consume one send() to completion, returning the typed events."""
    return [event async for event in session.send(text)]


async def consume(stream) -> list:
    """Consume an already-reserved send() stream (e.g. after cancel/close)."""
    return [event async for event in stream]


class GatedProvider(FakeProvider):
    """First response is an async-generator stream that idles until the run is
    cancelled — a deterministic in-flight run (an empty stream ends the turn as
    a provider error, exactly like a real cancelled response)."""

    def __init__(self) -> None:
        super().__init__([])
        self._first = True

    def stream_response(self, *, model, system, messages, tools, signal=None, session_id=None):
        if not self._first:
            return super().stream_response(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                signal=signal,
                session_id=session_id,
            )
        self._first = False
        self.calls.append((model, system, list(messages), list(tools)))
        self.session_ids.append(session_id)

        async def idle():
            while signal is not None and not signal.is_cancelled():
                await asyncio.sleep(0.005)
            return
            yield  # unreachable: makes idle an async generator, never a coroutine

        return idle()


# --- the host-configured project (retail-demo golden set, oracle-shared) ------


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config (the root Git
    suites' rule): repo-local identity only."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def admitted_retail_project(root: Path, *, reference: str | None = None) -> Path:
    """One real temporary ADMITTED Git data project carrying the retail-demo
    golden bundle: the recorded reference orders/customers models, the golden
    metric page citing both governing policies, and the deterministic seeded
    demo.db as the registered ``demo`` sqlite source — then the full human Git
    journey (commit the human-created initial artifact revision, start a
    proposal, approve the exact resolved source identity, validate, review,
    admit). ``reference`` optionally adds one more committed context page
    (e.g. the structured order-number Term Reference) BEFORE the journey, so
    it rides the admitted snapshot. The golden page text is extended with the
    ADR-0007 bundle-contract frontmatter and cites the registered source
    identity ``demo`` (the sqlite attach) instead of the retired bare table
    names; body text — the actual oracle content — is untouched."""
    from ariadne.authoring import AuthoringProject

    project = root / "proj"
    project.mkdir(parents=True, exist_ok=True)
    run_seed(project / "data" / "demo.db")
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: data/demo.db\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(
        (PRODUCT_AREA / "examples" / "retail-demo" / "seed_notes.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    models = project / "semantic_layer" / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
    (models / "customers.yml").write_text(CUSTOMERS_MODEL, encoding="utf-8")
    metric_page = GOLDEN_OKF.replace(
        "sources:\n  - orders\n  - currency_conversion_rate\n",
        "sources:\n  - demo\n",
    ).replace(
        "type: metric\nstatus: draft\n",
        "type: metric\nstatus: draft\ntitle: gross_margin\n"
        "description: Ratio of sums, not an average of per-row margins\n"
        "tags: [metric]\n",
    )
    pages = {
        "context_layer/metrics/gross_margin.md": metric_page,
        "context_layer/policies/order-status-billing.md": GOLDEN_POLICY_STATUS,
        "context_layer/policies/emea-currency-cutover.md": GOLDEN_POLICY_EMEA,
    }
    if reference is not None:
        pages["context_layer/references/order-number.md"] = reference
    for rel, content in pages.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    scope = [
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/models/orders.yml",
        "semantic_layer/models/customers.yml",
        *pages,
    ]
    run_git(project, "add", "--", *scope)
    run_git(project, "commit", "-q", "-m", "human: complete retail bundle", "--", *scope)

    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)  # the operator's approval, outside the agent
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == validated["revision"]
    assert admit(project, review) == 0  # the human Git Review Admission
    return project


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """One admitted project: the golden retail bundle with its seeded demo.db
    source, admitted through the human Git journey."""
    return admitted_retail_project(tmp_path_factory.mktemp("a1-project"))


def _policy_paths(text: str) -> set[str]:
    return set(re.findall(r"policies/[a-z0-9-]+\.md", text))


# Issue #48 (spec 0011): expectations for the additive ``context_signals``
# envelope are derived from §§3–5 and the fixture pages' own frontmatter,
# never from implementation output. The golden served pages declare
# ``status: draft`` and no expiry/verification metadata.
SEED_NOTES_SOURCE = {"id": "seed-notes", "resource": "data/seed_notes.md"}
GOLDEN_SOURCED_SEED_NOTES = {**SEED_NOTES_SOURCE, "title": "Seed notes"}
_GOLDEN_METRIC_SOURCES = [
    "demo",  # the registered sqlite source the admitted page cites
    {"id": "order-status-billing", "resource": "policies/order-status-billing.md"},
    {"id": "emea-currency-cutover", "resource": "policies/emea-currency-cutover.md"},
]


def _unverified_page_view(path: str, *, status: str, sources: list) -> dict:
    """One spec-0011-§4 advisory view of a fixture page declaring no expiry
    and no document verification: the declared lifecycle status (or OKF's
    ``stable`` default when absent — §4), §3's unknown freshness with a null
    expiry, §4's ``unverified`` tier, explicitly absent optional evidence,
    and the page's ACTUAL source identities."""
    return {
        "path": path,
        "status": status,
        "freshness": {"stale_after": None, "state": "unknown"},
        "verification_tier": "unverified",
        "generated": None,
        "verified": None,
        "sources": sources,
    }


def _golden_page_view(path: str) -> dict:
    """The expected §4 view of one golden authored page (issue #48): draft
    lifecycle preserved, unknown freshness, unverified tier, actual sources."""
    sources = (
        _GOLDEN_METRIC_SOURCES if path == "metrics/gross_margin.md" else [GOLDEN_SOURCED_SEED_NOTES]
    )
    return _unverified_page_view(path, status="draft", sources=sources)


def _computation_page_view(metric: str, model: str) -> dict:
    """The expected §4/§5 view of one finalize-generated computation page
    (spec 0011 §5 item 3, spec 0027 §2): generated draft lifecycle, unknown
    freshness, unverified tier, and the single OSI-model citation the core's
    computation writer attaches — derived from the finalize contract, the
    same independently written shape the root managed-admission suite
    pins for its own fixture."""
    return _unverified_page_view(
        f"computations/{metric}.md",
        status="draft",
        sources=[
            {
                "id": f"model-{model}",
                "resource": f"../../semantic_layer/models/{model}.yml",
                "title": f"{model} OSI model",
            }
        ],
    )


# --- the ticket's scripted flows ----------------------------------------------


def test_governed_route_returns_values_with_full_context(project):
    """Discovery -> get_metric: values match the independent-SQL oracle AND the
    admitted Policy context survives the tool boundary into the answer."""
    provider = FakeProvider(
        [
            turn(calls=[("list_metrics", {})]),
            turn(calls=[("get_metric", {"name": "gross_margin", "dimensions": ["region"]})]),
            turn(text=ANSWER_GOVERNED),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "gross margin by region?"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == ["list_metrics", "get_metric"], (
        "the governed route must discover before querying"
    )
    get = activity[1]
    assert get.is_error is False
    payload = json.loads(get.result)
    assert payload["governed"] is True and payload["metric"] == "gross_margin"

    # Regression (a): numeric rows alone are not the contract — the admitted
    # metric page and the FULL bodies of every cited Policy ride along.
    context = payload["context"]
    assert "policies/order-status-billing.md" in context["metric_page"]
    assert "policies/emea-currency-cutover.md" in context["metric_page"]
    assert len(context["policies"]) == 2, "every cited Policy body must be returned verbatim"
    assert any(
        "CANCELLED and RETURNED orders are not revenue" in body for body in context["policies"]
    )
    assert any("rate_to_usd" in body for body in context["policies"])

    # Issue #48 (spec 0011 §§4–§5): the governed context additionally carries
    # the additive ``context_signals`` envelope over exactly the consumed set
    # — the metric page and both cited Policies (this bundle has no
    # computation page, and an absent optional computation never warns). The
    # golden pages declare draft status and no expiry/verification: §5 forbids
    # warnings for absent optional metadata, and a draft never warns either.
    signals = context["context_signals"]
    assert set(signals) == {"pages", "warnings"}
    expected_views = [
        _golden_page_view("metrics/gross_margin.md"),
        _golden_page_view("policies/order-status-billing.md"),
        _golden_page_view("policies/emea-currency-cutover.md"),
        _computation_page_view("gross_margin", "orders"),
    ]
    assert len(signals["pages"]) == len(expected_views)
    for view in expected_views:
        assert view in signals["pages"]
    assert signals["warnings"] == []

    observed = {row["region"]: row["gross_margin"] for row in payload["rows"]}
    expected = independent_expected(project / "data" / "demo.db", "gross_margin", ["region"])
    assert set(observed) == set(expected)
    for region, value in observed.items():
        assert abs(value - expected[region]) <= TOLERANCE, f"governed {region}: {value}"

    # Issue #54 (spec 0013 §4, plan 0013 §2) — the native get-metric
    # passthrough: the additive advisory ``data_signals`` view crosses the
    # tool boundary with its CLOSED key set and honest unknowns. Expectations
    # derive from the contract, never from the tool: the golden admitted set
    # declares no ``ariadne_quality`` profile, so every identified dependency
    # keeps unknown coverage with NO report and NO warning invented for the
    # optional profile's absence, and nothing was elided.
    signals = payload["data_signals"]
    assert set(signals) == {
        "version",
        "assessed_at",
        "metrics",
        "assets",
        "warnings",
        "truncated",
        "omitted",
    }
    assert signals["version"] == 1 and datetime.fromisoformat(signals["assessed_at"])
    assert [entry["name"] for entry in signals["metrics"]] == ["gross_margin"]
    assert signals["metrics"][0]["coverage"] == "unknown"
    assert signals["assets"], "the executed query's direct dependencies are identified"
    for asset in signals["assets"]:
        assert asset["coverage"] == "unknown" and asset["reports"] == []
        assert asset["page"] is None  # no profile, no citation: pageless unknown
    assert signals["warnings"] == []
    assert signals["truncated"] is False
    assert signals["omitted"] == {"metrics": 0, "assets": 0, "pages": 0, "reports": 0}

    # The answer states the caveats and cites only Policy paths the tool
    # actually returned (never invented ones).
    answer = next(event.text for event in events if isinstance(event, AssistantText))
    lowered = answer.lower()
    assert "governed: true" in lowered
    assert "cancelled" in lowered and "returned" in lowered
    assert "emea" in lowered and "pre-2024" in lowered and "conver" in lowered
    cited = _policy_paths(answer)
    supported = _policy_paths(get.result)
    assert cited and cited <= supported, (
        f"answer cites Policy paths the tool did not return: {sorted(cited - supported)}"
    )
    assert isinstance(events[-1], RunCompleted) and events[-1].stop_reason == "stop"


def test_unmodeled_route_reports_ephemeral_ungoverned_result(project):
    """search_context -> list_datasets -> define_metric: the returned Policy
    guidance is cited, the result stays `governed: false` with the honest
    not-saved persistence status and nothing written — never presented as
    governed."""
    provider = FakeProvider(
        [
            turn(calls=[("search_context", {"query": "mean order amount per customer"})]),
            turn(calls=[("list_datasets", {})]),
            turn(calls=[("define_metric", {"definition": dict(ADHOC_DEFINITION)})]),
            turn(text=ANSWER_UNMODELED),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "mean order amount per customer?"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == [
        "search_context",
        "list_datasets",
        "define_metric",
    ], "the unmodeled route must search context before defining"
    search, _datasets, define = activity
    assert search.is_error is False and define.is_error is False

    # The search result carries the admitted Policy page (path + full body).
    hits = json.loads(search.result)
    returned_paths = {hit["path"] for hit in hits}
    assert "policies/order-status-billing.md" in returned_paths

    # Issue #48 (spec 0011 §4): EVERY search hit carries the envelope of ITS
    # returned page — exactly one assessed page per hit, on the hit's own
    # path — and §5 keeps the metadata-less golden pages warning-free. The
    # full view is pinned for the AUTHORED golden pages (their frontmatter is
    # the independent oracle); generated computation/index pages only owe the
    # path binding and warning-free shape, never a hardcoded body.
    for hit in hits:
        hit_signals = hit["context_signals"]
        assert set(hit_signals) == {"pages", "warnings"}
        assert [page["path"] for page in hit_signals["pages"]] == [hit["path"]]
        assert hit_signals["warnings"] == []
    by_path = {hit["path"]: hit for hit in hits}
    assert by_path["policies/order-status-billing.md"]["context_signals"]["pages"] == [
        _golden_page_view("policies/order-status-billing.md")
    ]

    payload = json.loads(define.result)
    # Regression (b): ad-hoc output is labeled ungoverned, and really
    # ephemeral — the not-saved persistence status, no staged paths, and no
    # durable artifact anywhere in the project.
    assert payload["governed"] is False
    assert payload["persistence"] == {"status": "not_saved"}
    assert "staged_as" not in payload and "staged_context_as" not in payload
    assert not (project / "staging").exists()

    # Spec 0011 §4: an ad-hoc result legitimately carries no signals — its
    # ``context`` stays exactly the pre-envelope ``null``.
    assert payload["context"] is None
    assert "context_signals" not in payload

    oracle = independent_adhoc_means(project / "data" / "demo.db")
    observed = {row["customer_id"]: row[ADHOC_ENTRY["metric"]] for row in payload["rows"]}
    assert set(observed) == set(oracle["per_customer"])
    for customer_id, value in observed.items():
        assert abs(value - oracle["per_customer"][customer_id]) <= TOLERANCE, (
            f"ad-hoc mean for {customer_id}: {value}"
        )

    answer = next(event.text for event in events if isinstance(event, AssistantText))
    lowered = answer.lower()
    assert "governed: false" in lowered
    assert "governed: true" not in lowered, "an ad-hoc result must never be presented as governed"
    assert "not_saved" in lowered or "not saved" in lowered or "not-saved" in lowered
    assert "staged" not in lowered and "promotion" not in lowered
    cited = _policy_paths(answer)
    assert cited and cited <= _policy_paths(search.result), (
        f"answer must cite Policy guidance the search actually returned: {sorted(cited)}"
    )
    assert isinstance(events[-1], RunCompleted)


def test_analyst_tool_surface_is_the_five_native_operations(project):
    """Tools are constructed for the role (not just described): exactly the
    five Ariadne baseline query operations plus the K2 read-only term resolver
    (issue #42), packaged-skill guidance in the system, and no tau_coding
    module ever loaded by the in-process run."""
    provider = FakeProvider([turn(text="ok")])
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    asyncio.run(drive(session, "hello"))
    model, system, _messages, tools = provider.calls[0]
    assert model == "fake-analyst"
    assert {tool.name for tool in tools} == ANALYST_TOOLS, (
        "the Analyst role gets exactly Ariadne's five baseline query "
        "operations plus resolve_term (issue #42) — nothing else"
    )
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    assert skill.strip() in system, "the version-matched packaged skill must be the guidance"
    assert all(name in system for name in ANALYST_TOOLS), (
        "the guidance must map the skill's CLI workflow onto the native tools"
    )
    assert not any(
        name == "tau_coding" or name.startswith("tau_coding.") for name in sys.modules
    ), "no tau_coding runtime module may be loaded"


# The structured Term Reference riding the ADMITTED snapshot: two
# representations bound to the registered demo orders table (canonical
# resource URIs), one prefix-mapping HYPOTHESIS citing the seed notes.
ORDER_TERM_REFERENCE = (
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
    f"        - resource: {table_resource('demo', 'demo', 'main', 'orders')}\n"
    "          column: order_id\n"
    "      scope: []\n"
    "    - id: global-order-number\n"
    "      aliases: [order number, global order number]\n"
    "      fields:\n"
    f"        - resource: {table_resource('demo', 'demo', 'main', 'orders')}\n"
    "          column: customer_id\n"
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


def test_analyst_resolve_term_reports_alternatives_and_unconfirmed_claims(tmp_path):
    """K2 (issue #42): the native ``resolve_term`` tool drives the shared core
    resolver over the admitted context — the umbrella alias returns the
    local/global alternatives with their exact bindings and the mapping
    hypothesis stays UNCONFIRMED — and the answer reports the page citation,
    never a join or transform authority. The reference page rides an ADMITTED
    snapshot (a mutable-root page would be invisible to the pinned runtime)."""
    own = admitted_retail_project(tmp_path, reference=ORDER_TERM_REFERENCE)
    provider = FakeProvider(
        [
            turn(calls=[("resolve_term", {"request": "order number"})]),
            turn(
                text=(
                    '"order number" is ambiguous on purpose (two documented '
                    "representations, references/order-number.md): the local "
                    "store-scoped number and the concatenated global identity. "
                    "Their mapping is an UNCONFIRMED hypothesis — not a rule to "
                    "join on."
                )
            ),
        ]
    )
    session = open_session(role="analyst", project=own, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "what is an order number?"))
    finally:
        session.close()

    activity = next(
        event
        for event in events
        if isinstance(event, ToolActivity) and event.tool == "resolve_term"
    )
    assert activity.is_error is False
    payload = json.loads(activity.result)
    assert [match["representation"] for match in payload["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert payload["ambiguous"] is True and payload["total_matches"] == 2
    local = payload["matches"][0]
    assert local["fields"][0]["column"] == "order_id"  # the authored binding
    assert local["page"] == "references/order-number.md"
    assert not ({"sql", "transform", "join"} & set(local))
    [mapping] = local["mappings"]
    assert mapping["claim"] == "hypothesis"
    assert mapping["confirmation"] == "unconfirmed"

    # Issue #48 (spec 0011 §4): every term-resolution match carries the
    # envelope for its matched Reference. The page declares no lifecycle
    # status — a readable concept gets OKF's ``stable`` default — and no
    # expiry/verification: unknown freshness, unverified tier, the page's
    # actual sources, and no warnings (§5).
    for match in payload["matches"]:
        match_signals = match["context_signals"]
        assert set(match_signals) == {"pages", "warnings"}
        assert match_signals["pages"] == [
            _unverified_page_view(
                "references/order-number.md",
                status="stable",
                sources=[SEED_NOTES_SOURCE],
            )
        ]
        assert match_signals["warnings"] == []

    answer = next(event.text for event in events if isinstance(event, AssistantText))
    assert "references/order-number.md" in answer
    assert "unconfirmed" in answer.lower()


def test_one_active_run_per_session_and_lifecycle(project):
    provider = GatedProvider()
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    assert session.role == "analyst" and session.role in ROLES

    async def scenario() -> list:
        run = asyncio.create_task(drive(session, "slow question"))
        # bounded wait: the run must become (and stay) active
        for _ in range(10_000):
            if session.is_running:
                break
            await asyncio.sleep(0.001)
        assert session.is_running, "the run must become active"
        with pytest.raises(RuntimeError, match="active run"):
            session.send("impatient second question")
        session.cancel()
        return await asyncio.wait_for(run, timeout=30)

    events = asyncio.run(scenario())
    assert session.is_running is False
    assert any(isinstance(event, SessionError) for event in events), (
        "a cancelled run ends with an error event, not silence"
    )
    assert isinstance(events[-1], RunCompleted)

    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.send("after close")
    session.cancel()  # idempotent: cancelling an idle session is a no-op


def test_missing_admission_is_actionable_and_isolates_sessions(project, tmp_path):
    """An unadmitted project opens the session (discovery stays available)
    but the FIRST query tool call surfaces the core's honest no-admission
    refusal as session-local guidance naming the human Git Review Admission
    step — never a mutable-root fallback, never "promote" — and the failed
    query stays session-local: nothing global blocks a later admitted
    session."""
    empty = tmp_path / "empty-project"
    empty.mkdir()
    provider = FakeProvider(
        [
            turn(calls=[("get_metric", {"name": "gross_margin"})]),
            turn(text="refused: needs human admission"),
        ]
    )
    session = open_session(role="analyst", project=empty, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "gross margin by region?"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == ["get_metric"]
    refusal = activity[0]
    assert refusal.is_error is True
    message = refusal.result
    assert "no valid admission" in message
    assert "ariadne-admit" in message and "human" in message.lower(), (
        f"the refusal must name the human admission step: {message!r}"
    )
    assert "promote" not in message.lower() and "staging" not in message.lower()
    assert "never falls back" in message  # the core's honest no-fallback refusal

    # The failed query is session-local: nothing global blocks a later
    # session on an admitted project (an Authoring session in A2 opens
    # through the same per-session rule).
    later = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=FakeProvider([turn(text="ok")]),
    )
    events = asyncio.run(drive(later, "still here?"))
    assert any(isinstance(event, AssistantText) for event in events)


def test_analyst_managed_project_resolves_through_pinned_admission(tmp_path, monkeypatch):
    """G6/issue #38 [4]: a MANAGED Git data project resolves through
    QueryRuntime.open_project — the session queries the PINNED admitted
    snapshot (hand-computed value; admission provenance in the envelope), and
    the tool surface stays the five query operations (the wider MCP Query
    registration never silently expands this session's permissions)."""
    import os

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    from ariadne.authoring import AuthoringProject

    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    review, _journey = admitted_ready(
        api,
        project,
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, admitted."),
        },
    )
    assert admit(project, review) == 0

    provider = FakeProvider(
        [
            turn(calls=[("get_metric", {"name": "event_count"})]),
            turn(text="event_count is 3, governed from the pinned admission"),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "how many events are there?"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == ["get_metric"]
    assert activity[0].is_error is False
    payload = json.loads(activity[0].result)
    assert payload["governed"] is True
    assert payload["rows"] == [{"event_count": 3}]  # the fixture's rows, hand-counted
    assert payload["admission"]["route"] == "git-review-admission"
    assert payload["admission"]["revision"] == review["revision"]

    # Issue #48 (spec 0011 §§4–§5): the managed route's governed context
    # carries the same envelope over its consumed set — the event_count
    # metric page, its single cited Policy, and the computation page the
    # admission finalize generates (spec 0011 §5 item 3: consumed when the
    # existing computation-context path reads it — here it also drives the
    # ``attestation: pending`` caveat). All three declare draft status and no
    # expiry/verification: absent optionals never warn (§5).
    managed_signals = payload["context"]["context_signals"]
    assert set(managed_signals) == {"pages", "warnings"}
    managed_views = [
        _unverified_page_view(
            "metrics/event_count.md",
            status="draft",
            sources=[
                {
                    "id": "all-events-count",
                    "resource": "policies/all-events-count.md",
                    "title": "All events count",
                }
            ],
        ),
        _unverified_page_view(
            "policies/all-events-count.md",
            status="draft",
            sources=[
                GOLDEN_SOURCED_SEED_NOTES,
                {"id": "rule-notes", "resource": "notes.md", "title": "Rule notes"},
            ],
        ),
        _unverified_page_view(
            "computations/event_count.md",
            status="draft",
            sources=[
                {
                    "id": "model-events",
                    "resource": "../../semantic_layer/models/events.yml",
                    "title": "events OSI model",
                }
            ],
        ),
    ]
    assert len(managed_signals["pages"]) == len(managed_views)
    for view in managed_views:
        assert view in managed_signals["pages"]
    assert managed_signals["warnings"] == []

    # the managed route never widened the native surface: still exactly five
    _model, _system, _messages, tools = provider.calls[0]
    assert {tool.name for tool in tools} == ANALYST_TOOLS


def test_analyst_serves_a_context_only_admitted_project(tmp_path, monkeypatch):
    """K4 (issue #44, spec 0010 §6/§9): a CONTEXT-ONLY admitted project
    (schemas/References, no metrics yet) still opens the Analyst session over
    its pinned admission — resolve_term serves the admitted terminology with
    every mapping unconfirmed, and the metric tool surfaces the SPECIFIC
    missing-catalog error. The native surface never widens: no confirmation or
    admission tool exists on it (human-only, ariadne-admit --confirm-mapping)."""
    import os

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    from tests.test_context_admission import (
        MISSING_CATALOG_MARK,
        context_only_candidate,
    )
    from tests.test_context_admission import admit as admit_context_only

    project, api, candidate = context_only_candidate(tmp_path / "proj")
    validated = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert validated["ok"] is True
    review = api.review_proposal(candidate["proposal"])
    assert admit_context_only(project, review) == 0

    provider = FakeProvider(
        [
            turn(
                calls=[
                    ("resolve_term", {"request": "order number"}),
                    ("get_metric", {"name": "order_number_count"}),
                ]
            ),
            turn(
                text="No governed metric catalog exists yet (context-only "
                "admission); the order-number hypothesis and assertion are "
                "unconfirmed leads pending human confirmation."
            ),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "what do we know about order numbers?"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == ["resolve_term", "get_metric"]
    resolved = json.loads(activity[0].result)
    assert activity[0].is_error is False
    assert [match["representation"] for match in resolved["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert all(
        mapping["confirmation"] == "unconfirmed"
        for match in resolved["matches"]
        for mapping in match["mappings"]
    )

    # Issue #48 (spec 0011 §4): the admitted context-only resolver surfaces
    # the same per-match envelope — ``stable`` default (no declared status),
    # unknown freshness, unverified tier, actual sources, no warnings (§5).
    for match in resolved["matches"]:
        match_signals = match["context_signals"]
        assert set(match_signals) == {"pages", "warnings"}
        assert match_signals["pages"] == [
            _unverified_page_view(
                "references/order-number.md",
                status="stable",
                sources=[GOLDEN_SOURCED_SEED_NOTES],
            )
        ]
        assert match_signals["warnings"] == []

    assert activity[1].is_error is True
    assert MISSING_CATALOG_MARK in activity[1].result

    # the managed context-only route never widened the native surface
    _model, _system, _messages, tools = provider.calls[0]
    assert {tool.name for tool in tools} == ANALYST_TOOLS
    assert not [
        name
        for name in (tool.name for tool in tools)
        if any(marker in name for marker in ("confirm", "admit", "approve"))
    ]


def test_analyst_managed_project_without_admission_is_actionable(tmp_path, monkeypatch):
    """A managed Git project with proposals but NO admission opens the
    Analyst session (discovery stays available) while its first query tool
    call refuses with the human-only admission step — never a fallback to
    the mutable project files — and the error stays session-local (an
    Authoring session on the same project opens fine)."""
    import os

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    from ariadne.authoring import AuthoringProject

    project = complete_bundle_project(tmp_path / "proj")
    AuthoringProject(project).start_proposal()  # managed state, no admission

    provider = FakeProvider(
        [
            turn(calls=[("get_metric", {"name": "event_count"})]),
            turn(text="refused: admission is human-only"),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    try:
        events = asyncio.run(drive(session, "how many events are there?"))
    finally:
        session.close()

    activity = [event for event in events if isinstance(event, ToolActivity)]
    assert [event.tool for event in activity] == ["get_metric"]
    message = activity[0].result
    assert activity[0].is_error is True
    assert "no valid admission" in message
    assert "ariadne-admit" in message and "human" in message.lower(), (
        f"the refusal must name the human admission step: {message!r}"
    )

    authoring = open_session(
        role="authoring",
        project=project,
        model="fake-analyst",
        provider=FakeProvider([turn(text="ready")]),
    )
    authoring.close()


def test_role_and_project_are_fixed_per_session(project):
    first = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=FakeProvider([turn(text="one")]),
    )
    asyncio.run(drive(first, "first question"))
    assert first.role == "analyst"
    assert first.project == project.resolve()
    with pytest.raises(AttributeError):
        first.role = "authoring"  # type: ignore[misc]

    # A different role or a fresh session never inherits the transcript.
    second = open_session(
        role="analyst",
        project=project,
        model="fake-analyst",
        provider=FakeProvider([turn(text="two")]),
    )
    assert second.role == "analyst"
    assert len(second.messages) == 0, "no silent transcript transfer into a new session"
    assert not hasattr(second, "resume"), "restart loses messages; no fake resume operation"


def test_cancel_and_close_between_send_and_first_consumption_are_not_lost(project):
    """Regression (issue #23 follow-up): cancel()/close() between send() and
    the first consumption are honoured — send() returns a lazy stream and the
    harness cancellation token does not exist until consumption, so a lost
    request would still run model turns and execute tools."""
    # (1) cancel() between send() and the first consumption.
    provider = FakeProvider(
        [
            turn(calls=[("list_metrics", {})]),  # must never run
            turn(text="still here"),
        ]
    )
    session = open_session(role="analyst", project=project, model="fake-analyst", provider=provider)
    stream = session.send("cancel before I start")
    session.cancel()  # BEFORE the host consumes the event iterator

    events = asyncio.run(consume(stream))
    assert provider.calls == [], "cancel-before-start must not start a model turn"
    assert not any(isinstance(event, ToolActivity) for event in events)
    assert isinstance(events[-2], SessionError), "the cancelled stream reports a typed error"
    assert isinstance(events[-1], RunCompleted) and events[-1].stop_reason == "aborted"
    assert session.is_running is False, "the cancelled reserved run releases the flag"

    # The session stays usable and closes out per the existing contract.
    follow_up = asyncio.run(drive(session, "still here?"))
    assert any(isinstance(event, AssistantText) for event in follow_up)
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.send("after close")

    # (2) close() between send() and the first consumption.
    closed_provider = FakeProvider([turn(text="never started")])
    closed_session = open_session(
        role="analyst", project=project, model="fake-analyst", provider=closed_provider
    )
    closed_stream = closed_session.send("close before I start")
    closed_session.close()  # BEFORE the host consumes the event iterator

    closed_events = asyncio.run(consume(closed_stream))
    assert closed_provider.calls == [], "close-before-start must not start a model turn"
    assert isinstance(closed_events[-2], SessionError)
    assert isinstance(closed_events[-1], RunCompleted)
    assert closed_session.is_running is False


def test_installed_startup_loads_no_tau_coding_and_launches_no_server():
    """Installed-package startup (a fresh interpreter importing the package)
    must load no tau_coding runtime module and no Ariadne server."""
    code = (
        "import sys\n"
        "import ariadne_agent\n"
        "leaked = [name for name in sys.modules"
        " if name == 'tau_coding' or name.startswith('tau_coding.')"
        " or name == 'ariadne.serve']\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", (
        f"package import leaked runtime modules: {result.stdout.strip()!r}"
    )
