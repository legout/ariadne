"""Q2 (spec0029 §1.2): local multi-metric analysis over one integrated release.

The fixture is authored independently of the implementation: completed orders
100 + 50 and cancelled 25 imply revenue 150 and completed-order count 2. The
full native candidate/validation/consent/admission chain is real — no mocked
SDK, no fake approval. The combined mandatory-context budget refusal is proven
to precede the planner and any live bind/SELECT by spy guards.
"""

import asyncio
import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — qualified test env is external
from ariadne import query_results  # pyright: ignore[reportAttributeAccessIssue]
from ariadne.authoring import AuthoringProject
from ariadne.query import QueryRuntime
from tests.test_contracts import ORDERS_BINDINGS, ORDERS_CONTRACT, contracted
from tests.test_git_authoring import approved, run_git, worktree_of

from integration.tests.lumio_metric_mvp import (
    CANCELLATION,
    NAMESPACE,
    activate,
    content_project,
    page_parts,
    preview,
    reconcile_knowledge,
    write_page,
)

COMPLETED_METRIC = """\
      - name: completed_orders
        description: Count of orders not cancelled
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN status <> 'cancelled' THEN 1 ELSE 0 END)
"""

GRAPH = """\
version: 1
relationships: []
conformed_dimensions: []
"""

OKF_COMPLETED = (
    "---\n"
    "type: metric\n"
    "status: draft\n"
    "title: completed_orders\n"
    "description: Count of orders not cancelled.\n"
    "tags: [metric]\n"
    "sources:\n"
    "  - id: all-orders-count\n"
    "    resource: policies/all-orders-count.md\n"
    "    title: All orders count\n"
    "---\n\n"
    "# completed_orders\n"
)

KB_COMPLETED = """\
---
id: "entity:completed-orders"
title: "Completed Orders (Metric)"
entity_types:
  - metric
tags:
  - retail
  - operations
summary: "Count of recognized completed orders, excluding cancelled ones."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "src-ops-model"
    title: "Operations model review, 2026-10-05"
ariadne_profile:
  version: 1
  kind: metric
  metric_ref:
    model: "retail_sales"
    metric: "completed_orders"
  required_policies: []
  native:
    type: metric
    status: stable
    title: "Completed orders"
    description: "Count of orders not cancelled, per the Cancelled Orders policy."
    tags:
      - operations
    stale_after: 2027-06-30
    sources:
      - id: "pol-cancelled"
        title: "Governing policy"
        resource: "policies/cancelled-orders.md"
    governed_by: "policies/cancelled-orders.md"
    dimensions:
      - status
    grain:
      primary_key:
        - id
      cardinality_enforcement: "strict_1_to_1"
---

# Completed Orders (Metric)

Completed orders count every order whose status is not cancelled. Completed
orders 1 (100) and 2 (50) count; cancelled order 3 does not. The executable
exclusion is owned by the Ariadne semantic layer; this page curates the
business meaning and the mandatory policy context only.
"""


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for name in list(os.environ):
        if name.startswith(("LUMIO_", "AWS_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def multi_metric_release(root: Path):
    """One admitted integrated release whose graph serves two predefined
    metrics over the same orders fact: revenue and completed_orders."""
    project = content_project(root)
    model = project / "semantic_layer" / "models" / "retail_sales.yml"
    model.write_text(model.read_text() + COMPLETED_METRIC)
    (project / "semantic_layer" / "graph.yml").write_text(GRAPH)
    (project / "context_layer" / "metrics" / "completed_orders.md").write_text(OKF_COMPLETED)
    (project / "knowledge" / "metrics" / "completed-orders.md").write_text(KB_COMPLETED)
    run_git(
        project,
        "add",
        "--",
        "semantic_layer/graph.yml",
        "semantic_layer/models/retail_sales.yml",
        "context_layer/metrics/completed_orders.md",
        "knowledge/metrics/completed-orders.md",
    )
    run_git(project, "commit", "-q", "-m", "human: add completed-orders metric and graph")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    # the supported-shape candidate edits: drop the unsupported Reference
    # profile and bind BOTH metric pages to the shared Cancelled Orders policy
    tree = worktree_of(project, started["proposal"])
    reference = tree / "knowledge/references/order-number.md"
    meta, body = page_parts(reference)
    del meta["ariadne_profile"]  # visible Git candidate edit, never an input conversion
    write_page(reference, meta, body)
    (tree / "knowledge/policies/cancelled-orders.md").write_text(CANCELLATION)
    for name in ("retail-revenue", "completed-orders"):
        page = tree / "knowledge/metrics" / f"{name}.md"
        meta, body = page_parts(page)
        meta["ariadne_profile"]["required_policies"].append(
            {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
        )
        write_page(page, meta, body)
    revision = reconcile_knowledge(project, started["proposal"], revision)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    activate(project, review, preview(project, review, root / "published"))
    return project, review


def test_multi_metric_context_precedes_execution(tmp_path, monkeypatch):
    project, review = multi_metric_release(tmp_path)
    runtime = QueryRuntime.open_project(project)
    try:
        manifest = runtime._managed["bound_release"]
        result = asyncio.run(runtime.query_metrics({"metrics": ["revenue", "completed_orders"]}))
        # independent oracle: 100 + 50 completed imply 150 and count 2
        assert result["rows"] == [{"revenue": 150.0, "completed_orders": 2}]
        assert result["governed"] is True
        assert result["admission"]["revision"] == review["revision"]
        # per-metric COMPLETE SDK context with exact version-qualified citations
        assert set(result["context"]) == {"revenue", "completed_orders"}
        revenue_context = result["context"]["revenue"]
        completed_context = result["context"]["completed_orders"]
        assert "# Retail Revenue (Metric)" in revenue_context["metric_page"]
        assert "# Completed Orders (Metric)" in completed_context["metric_page"]
        assert CANCELLATION in revenue_context["policies"]
        assert CANCELLATION in completed_context["policies"]  # shared Policy, both associations
        assert revenue_context["bound_release"] == manifest["digest"]
        assert completed_context["bound_release"] == manifest["digest"]
        assert {c["entity_id"] for c in revenue_context["citations"]} == {
            "entity:retail-revenue",
            "entity:retail-return-policy",
            "entity:cancelled-orders",
        }
        assert {c["entity_id"] for c in completed_context["citations"]} == {
            "entity:completed-orders",
            "entity:cancelled-orders",
        }
        for context in (revenue_context, completed_context):
            assert all(c["published_version"] == review["revision"] for c in context["citations"])

        # a host budget that carries EITHER metric's context alone must refuse
        # the COMBINED context before planner/audit/bind/SELECT: the budget is
        # placed from BOTH independently serialized single-metric envelopes, so
        # each one fits while the combined mandatory context cannot
        singles = [
            query_results.result_json_bytes({"context": {"revenue": revenue_context}}),
            query_results.result_json_bytes({"context": {"completed_orders": completed_context}}),
        ]
        combined = query_results.result_json_bytes(
            {"context": {"revenue": revenue_context, "completed_orders": completed_context}}
        )
        largest_single = max(singles)
        assert largest_single < combined
        budget = largest_single + (combined - largest_single) // 2
        assert all(size <= budget for size in singles) and budget < combined
        import ariadne.query as query_module

        def no_live(*args, **kwargs):
            raise AssertionError("combined-context overflow reached the planner/live path")

        old_limits = runtime._limits
        runtime._limits = {**old_limits, "response_bytes": budget}
        with monkeypatch.context() as m:
            m.setattr(query_module, "plan_query", no_live)
            m.setattr(runtime._execution, "bind", no_live)
            with pytest.raises(query_results.QueryResultError):
                asyncio.run(runtime.query_metrics({"metrics": ["revenue", "completed_orders"]}))
        runtime._limits = old_limits
    finally:
        runtime.con.close()


# --------------------------------------------- A2 navigation (spec0029 §1.3)

# Hand-authored oracle, independent of the implementation. The visible
# ordinary (unprofiled) page carries the search token "meridian" exactly
# twice, on hand-counted canonical lines 21-22 (frontmatter = lines 1-15,
# closing delimiter line 15, body from line 16). No other visible page has
# the token in title/aliases/tags/summary/body, so native search (body
# weight 20, occurrences capped at 3) scores this page exactly 40.0 as the
# single visible hit under "## Routing vocabulary" (line 19).
GLOSSARY_PATH = "references/fulfilment-glossary.md"
GLOSSARY_EXCERPT = "The morning consolidation batch is internally called Meridian. Only the"

# Deterministic canonical bulk (A2 budget correction): ~24 KiB of authored
# token-free register notes, so the REQUIRED pages output alone cannot fit a
# tightened Core bound while the shrunken missing-pages report still does.
# No "meridian" occurrence joins the page: the 40.0 single-hit oracle (body
# weight 20 x capped occurrences) and every hand-counted line above stay
# exactly as authored.
GLOSSARY_REGISTER = "".join(
    f"Register note {index:03d}: packaging stations confirm the canonical\n"
    f"fulfilment vocabulary line {index:03d} for routing desks, courier\n"
    "handover points, consolidation windows and packaging stations.\n\n"
    for index in range(1, 135)
)

GLOSSARY_MD = (
    "---\n"
    'id: "entity:fulfilment-glossary"\n'
    'title: "Fulfilment Glossary"\n'
    "entity_types:\n"
    "  - reference\n"
    "tags:\n"
    "  - retail\n"
    "  - operations\n"
    'summary: "Shared wording for the retail fulfilment channel."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "src-ops-vocabulary"\n'
    '    title: "Operations vocabulary, 2026-10-05"\n'
    "---\n"
    "\n"
    "# Fulfilment Glossary\n"
    "\n"
    "## Routing vocabulary\n"
    "\n"
    "The morning consolidation batch is internally called Meridian. Only the\n"
    "visible Meridian note in this glossary is published context for routing.\n"
    "\n"
    "## Canonical register\n"
    "\n"
    + GLOSSARY_REGISTER
)

# A valid hidden page sharing the token (title+summary+body would score 160
# and outrank the glossary if the operator Visibility Scope "public" were
# bypassed): the single 40.0 hit with candidates_seen == 1 proves the hidden
# page never entered selection, ranking or completeness counting.
HIDDEN_PATH = "references/meridian-internal.md"
HIDDEN_MD = (
    "---\n"
    'id: "entity:meridian-internal"\n'
    'title: "Meridian Internal Routing"\n'
    "entity_types:\n"
    "  - reference\n"
    "tags:\n"
    "  - retail\n"
    "  - internal\n"
    'summary: "Restricted Meridian routing table for the fulfilment batch."\n'
    'lifecycle: "approved"\n'
    'visibility: "restricted"\n'
    "sources:\n"
    '  - id: "src-ops-internal"\n'
    '    title: "Operations internal memo, 2026-10-06"\n'
    "---\n"
    "\n"
    "# Meridian Internal Routing\n"
    "\n"
    "The restricted Meridian routing table lists every store lane and cutoff.\n"
)

# The deliberately different LEGACY page at the SAME context path: a valid
# ADR0007 context_layer Reference (the existing REFERENCE_PAGE source-citation
# idiom, no Ariadne technical extension or mappings) whose body differs from
# the published SDK page. Legacy context_layer reads must never surface
# through integrated navigation.
LEGACY_GLOSSARY_MD = (
    "---\n"
    "type: reference\n"
    "title: Legacy Fulfilment Glossary\n"
    "description: Superseded legacy wording for the fulfilment batch.\n"
    "tags: [reference]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# Legacy Fulfilment Glossary\n\n"
    "LEGACY meridian draft: this superseded legacy context page spells the\n"
    "consolidation batch wording differently from the published knowledge.\n"
)


def navigation_release(root: Path):
    """One admitted integrated release whose published KB adds the visible
    ordinary glossary page and the hidden same-token page, while the admitted
    context_layer carries a deliberately different legacy page at the same
    path. Knowledge and the legacy context edit are committed as ONE synthetic
    revision before ``admission.reconcile`` (``reconcile_knowledge`` stages the
    KB subtree only, so the shared revision is staged explicitly here)."""
    from ariadne import admission

    project = content_project(root)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    tree = worktree_of(project, started["proposal"])
    reference = tree / "knowledge/references/order-number.md"
    meta, body = page_parts(reference)
    del meta["ariadne_profile"]  # visible Git candidate edit, never an input conversion
    write_page(reference, meta, body)
    (tree / "knowledge" / GLOSSARY_PATH).write_text(GLOSSARY_MD)
    (tree / "knowledge" / HIDDEN_PATH).write_text(HIDDEN_MD)
    legacy = tree / "context_layer" / GLOSSARY_PATH
    legacy.parent.mkdir(parents=True, exist_ok=True)  # references/ is new in the candidate
    legacy.write_text(LEGACY_GLOSSARY_MD)
    run_git(tree, "add", "-f", "--", "knowledge")
    run_git(tree, "add", "--", f"context_layer/{GLOSSARY_PATH}")
    run_git(tree, "commit", "-q", "-m", "human: add glossary navigation candidate pages")
    knowledge_revision = run_git(tree, "rev-parse", "HEAD").strip()
    admission.reconcile(project, started["proposal"], revision, knowledge_revision)
    validated = api.validate_proposal(started["proposal"], knowledge_revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    activate(project, review, preview(project, review, root / "published"))
    return project, review


def test_context_navigation_uses_sdk_without_legacy_or_sources(tmp_path, monkeypatch, capsys):
    """A2 (spec0029 §1.3): admitted integrated navigation serves the pinned SDK
    pages — never the legacy same-path context_layer body, never hidden
    same-token content, never a source connection — through the real CLI and
    the in-process MCP tools, and refuses whole when the required output
    cannot fit the host response budget."""
    import json

    import yaml
    from ariadne import serve
    from ariadne.cli import main as cli
    from tests.test_discovery import _source_free_guards

    project, review = navigation_release(tmp_path)
    manifest = json.loads((project / ".ariadne" / "current.json").read_text())["bound_release"]
    identity = {
        "path": GLOSSARY_PATH,
        "kind": "unprofiled",
        "namespace": NAMESPACE,
        "entity_id": "entity:fulfilment-glossary",
        "published_version": review["revision"],
        "citation": f"{NAMESPACE} entity:fulfilment-glossary v{review['revision']} {GLOSSARY_PATH}",
        "draft": False,
        "bound_release": manifest["digest"],
    }
    hit_oracle = {
        **identity,
        "score": 40.0,
        "content": GLOSSARY_MD,
        "excerpt": GLOSSARY_EXCERPT,
        "line_start": 21,
        "line_end": 21,
        "section": "Routing vocabulary",
        "matched_fields": ["body"],
        "matched_terms": ["meridian"],
        "candidates_seen": 1,
        "results_dropped": 0,
    }

    # Native validation/admission above legitimately used live validation;
    # from here the whole journey is source-free: any Source/runtime/duckdb/
    # network construction refuses the scenario.
    _source_free_guards(monkeypatch)

    def _typed_list(result):
        # Installed-SDK contract (func_metadata._convert_to_content): a list
        # return emits ONE JSON-object text block PER ITEM, while the typed
        # structured output wraps the list as {"result": [...]}. Strict shape:
        # exactly that wrapper, a list value, no error, all blocks text, and
        # the per-item texts equal the wrapped list.
        assert not getattr(result, "is_error", False)
        assert result.structured_content.keys() == {"result"}
        wrapped = result.structured_content["result"]
        assert isinstance(wrapped, list)
        blocks = list(getattr(result, "content", ()))
        assert blocks and all(block.type == "text" for block in blocks)
        assert [json.loads(block.text) for block in blocks] == wrapped
        return wrapped

    def _typed_dict(result):
        # A plain dict return is exactly one JSON text block: the installed
        # SDK generates no output model (and so no structured_content) for a
        # bare dict annotation — the observed native form, not a wrapper.
        assert not getattr(result, "is_error", False)
        assert result.structured_content is None
        blocks = list(getattr(result, "content", ()))
        assert len(blocks) == 1 and blocks[0].type == "text"
        return json.loads(blocks[0].text)

    async def _journey(app):
        return {
            "list": await app.call_tool("list_context_pages", {}),
            "read": await app.call_tool("read_context_page", {"path": GLOSSARY_PATH}),
            "search": await app.call_tool("search_context", {"query": "meridian"}),
            "discover": await app.call_tool("discover", {"query": "meridian"}),
        }

    app = serve.build_app(QueryRuntime, project=str(project))
    results = asyncio.run(_journey(app))

    # list: every visible page, SDK-sorted by exact path; metadata only.
    listed = _typed_list(results["list"])
    assert [entry["path"] for entry in listed] == [
        "metrics/retail-revenue.md",
        "policies/retail-return-policy.md",
        "references/fulfilment-glossary.md",
        "references/order-number.md",
    ]
    glossary = next(entry for entry in listed if entry["path"] == GLOSSARY_PATH)
    for key, value in {**identity, "title": "Fulfilment Glossary"}.items():
        assert glossary.get(key) == value, key
    assert "content" not in glossary  # no page body in list results
    assert glossary["context_signals"]["warnings"] == []  # no fabricated advisories

    # read: the full canonical SDK page; the legacy same-path body never wins.
    page = _typed_dict(results["read"])
    for key, value in identity.items():
        assert page.get(key) == value, key
    assert page["content"] == GLOSSARY_MD
    assert page["context_signals"]["warnings"] == []

    # search: one native hit with the verbatim hand-counted passage.
    hits = _typed_list(results["search"])
    assert len(hits) == 1
    for key, value in hit_oracle.items():
        assert hits[0].get(key) == value, key
    assert hits[0]["context_signals"]["warnings"] == []

    # hidden and unknown paths refuse identically: the complete documented
    # ToolError messages (mcp.server.mcpserver.exceptions, per installed
    # server.call_tool) are equal after normalizing only the input path, and
    # neither discloses a hidden title, Entity identity or body.
    from mcp.server.mcpserver.exceptions import (  # pyright: ignore[reportMissingImports] — qualified env
        ToolError,
    )

    refusals = []
    for refused in (HIDDEN_PATH, "references/does-not-exist.md"):
        with pytest.raises(ToolError) as caught:
            asyncio.run(app.call_tool("read_context_page", {"path": refused}))
        refusals.append(str(caught.value))
    assert refusals[0].replace(HIDDEN_PATH, "<path>") == refusals[1].replace(
        "references/does-not-exist.md", "<path>"
    )

    # discover: the pages group uses the same SDK hits; still-deferred groups
    # stay honestly unavailable and served support says what is enabled.
    report = _typed_dict(results["discover"])
    assert report["bound_release"] == manifest["digest"]
    support = report["support"]
    enabled = {"search_context", "list_context_pages", "read_context_page"}
    assert enabled <= set(support["operations"])
    assert not enabled & set(support["unsupported"])
    assert "resolve_term" in support["operations"]  # T2 (spec0029 §1.5)
    assert report["groups"]["pages"] == {
        "status": "available",
        "items": hits,
        "completeness": "unknown",
    }
    # T2 (spec0029 §1.5): resolve_term now serves on integrated admissions —
    # this release carries no structured References, so the group is honestly
    # available and empty
    assert report["groups"]["terms"]["status"] == "available"
    assert report["groups"]["terms"]["result"]["total_matches"] == 0
    assert report["groups"]["examples"]["status"] == "unavailable"

    # the same navigation over the actual CLI, still under the source guards.
    assert cli(["search-context", "meridian", "--project", str(project)]) == 0
    cli_hits = json.loads(capsys.readouterr().out)
    assert cli_hits == hits
    assert cli(["search", "meridian", "--json", "--project", str(project)]) == 0
    cli_report = json.loads(capsys.readouterr().out)
    assert cli_report["groups"]["pages"]["items"] == hits

    # no legacy or hidden content ever surfaced through any surface above,
    # including the two refusal messages themselves.
    everything = json.dumps([listed, page, hits, report, cli_report, refusals])
    for marker in (
        "Legacy Fulfilment Glossary",
        "LEGACY meridian draft",
        "Meridian Internal Routing",
        "restricted Meridian routing table",
        "store lane and cutoff",
        "entity:meridian-internal",
    ):
        assert marker not in everything, marker

    # required content refuses whole at the real host bound: no elision.
    config = project / "ariadne.yaml"
    original = config.read_text()
    full = query_results.result_json_bytes(hits)
    floor = max(query_results.result_json_bytes(form) for form in query_results.refusal_forms())
    assert floor < full  # the canonical page dominates the compact refusal forms
    tightened = floor + (full - floor) // 2
    document = yaml.safe_load(original)
    document["query"] = {"response_bytes": tightened}
    config.write_text(yaml.safe_dump(document, sort_keys=False))
    code = cli(["search-context", "meridian", "--project", str(project)])
    failure = capsys.readouterr()
    assert code == 1 and not failure.out
    refused = json.loads(failure.err)
    assert refused["error"]["code"] == "result_byte_limit"
    assert refused["error"]["exhausted_bound"]["response_bytes"] == tightened
    config.write_text(original)
    assert cli(["search-context", "meridian", "--project", str(project)]) == 0
    capsys.readouterr()

    # A2 budget correction (plan0029r20): both accepted defects are observed
    # through this same journey BEFORE the strict checks. (1) A Core-only
    # 8 KiB bound the REQUIRED SDK page cannot fit must refuse the whole CLI
    # search report and MCP discover operation — never substitute an
    # unavailable pages group for required content. (2) An MCP-only ceiling
    # of 1 byte — below every refusal envelope on the wire — must be rejected
    # BEFORE navigation, never answered with an over-budget isError refusal.
    required = query_results.result_json_bytes(hits)  # hits == the hand oracle above
    without_pages = query_results.result_json_bytes(
        {**report, "groups": {k: v for k, v in report["groups"].items() if k != "pages"}}
    )
    # 1024 bytes cover one refusal reason string: refusal representations
    # are small by construction (fixed messages, counts only — spec 0014 §5).
    assert without_pages + 1024 < 8192 < required

    document["query"] = {"response_bytes": 8192}
    config.write_text(yaml.safe_dump(document, sort_keys=False))
    search_code = cli(["search", "meridian", "--json", "--project", str(project)])
    search_failure = capsys.readouterr()
    oversize_result = None
    oversize_refusal = None
    try:
        oversize_result = asyncio.run(app.call_tool("discover", {"query": "meridian"}))
    except ToolError as exc:  # the documented mcp 2.2.0 tool-error surface
        oversize_refusal = str(exc)
    config.write_text(original)

    def _no_query_runtime(*args, **kwargs):
        raise AssertionError("the MCP ceiling rejection must not construct QueryRuntime")

    monkeypatch.setattr(QueryRuntime, "open_project", _no_query_runtime)
    document["query"] = {"mcp_response_bytes": 1}
    config.write_text(yaml.safe_dump(document, sort_keys=False))
    ceiling_result = None
    ceiling_rejection = None
    try:
        ceiling_result = asyncio.run(app.call_tool("discover", {"query": "meridian"}))
    except ToolError as exc:  # the documented mcp 2.2.0 tool-error surface
        ceiling_rejection = str(exc)
    config.write_text(original)

    # (1) whole-operation refusal on both surfaces (spec 0014 §5: one bounded
    # refusal, never a successful partial with required pages silently
    # dropped)
    ceiling_wire = serve._wire_bytes(ceiling_result) if ceiling_result is not None else None
    assert search_code == 1 and not search_failure.out, (
        f"exit={search_code} stdout={len(search_failure.out)}B"
        f" core_mcp_success={oversize_result is not None}"
        f" core_mcp_refusal={oversize_refusal}"
        f" ceiling_returned={ceiling_result is not None}"
        f" ceiling_error={ceiling_rejection}"
        f" ceiling_wire_bytes={ceiling_wire}"
    )
    cli_refusal = json.loads(search_failure.err)
    assert cli_refusal["error"]["code"] == "result_byte_limit"
    assert cli_refusal["error"]["exhausted_bound"]["response_bytes"] == 8192
    # the MCP whole-operation refusal keeps the documented ToolError surface
    # with the stable Core byte-refusal message — no new MCP output shape
    assert oversize_result is None, "MCP discover returned a successful partial"
    assert oversize_refusal is not None, "MCP discover did not refuse whole"
    assert "exceeds its byte ceiling" in oversize_refusal
    # (2) configuration rejection BEFORE navigation, not an oversized refusal
    assert ceiling_result is None, "discover answered under a 1-byte MCP ceiling"
    assert ceiling_rejection is not None, "no configuration rejection was raised"
    assert "mcp_response_bytes" in ceiling_rejection


# ------------------------------------------- G2 Git/local sync (spec0029 §1.4)

# Hand-authored oracle bytes: admitted revision A publishes the candidate page
# exactly as committed; operator revision B appends one visible sentence. The
# served page body therefore identifies the active release without a query,
# and every expected identity below comes from these authored bytes, git
# rev-parse and the exact .ariadne/current.json descriptor — never from
# product status output.
G2_PAGE = "references/order-number.md"
G2_B_APPENDIX = "\nOperator B: amended fulfilment wording for the sync journey.\n"


def test_sync_does_not_activate_context(tmp_path, monkeypatch, capsys):
    """G2 (spec0029 §1.4): a plain local Git sync moves the operator checkout
    from the admitted revision A to B while the verified admission descriptor,
    its Bound Release and an already-open session stay pinned to A. Only the
    ordinary reconciled/validated/reviewed/confirmed B admission repoints
    serving. ``ariadne status`` additively discloses the local HEAD separately
    from the verified admission without destination or source data; malformed
    and missing admissions never masquerade as a valid bound release."""
    import json

    from ariadne import admission
    from ariadne.cli import main as cli
    from ariadne.discovery import DiscoveryRuntime
    from tests.test_discovery import _source_free_guards

    from integration.tests.lumio_metric_mvp import current_bytes, ready

    # admitted A through the real native chain: contract, synthetic source
    # approval, candidate edits, validation, review, preview, confirmation
    project, api, review = ready(tmp_path)
    destination = tmp_path / "published"
    activate(project, review, preview(project, review, destination))
    a_rev = review["revision"]
    descriptor_a_bytes = current_bytes(project)
    descriptor_a = json.loads(descriptor_a_bytes)
    manifest_a = descriptor_a["bound_release"]
    digest_a = manifest_a["digest"]
    assert manifest_a["knowledge"]["published_version"] == a_rev

    # the pre-existing session is opened and proven under source-free guards
    # immediately after the A activation — BEFORE any local Git sync — and
    # that exact object must survive both later transitions below
    a_bytes = (worktree_of(project, review["proposal"]) / "knowledge" / G2_PAGE).read_bytes()
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        session_a = DiscoveryRuntime.open_project(project)
        served = asyncio.run(session_a.read_context_page(G2_PAGE))
        assert served["content"] == a_bytes.decode()
        assert served["bound_release"] == digest_a

    # the operator checkout explicitly points at the admitted candidate
    # revision A; a disposable bare remote and a peer clone then carry one
    # authored B amendment — real local push/clone/commit/fetch/fast-forward
    run_git(project, "checkout", "-q", a_rev)
    page = project / "knowledge" / G2_PAGE
    assert page.read_bytes() == a_bytes  # the checkout materializes revision A
    b_bytes = a_bytes + G2_B_APPENDIX.encode()
    bare = tmp_path / "disposable-origin.git"
    run_git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    run_git(project, "push", "-q", str(bare), f"{a_rev}:refs/heads/main")
    peer = tmp_path / "peer"
    run_git(tmp_path, "clone", "-q", str(bare), str(peer))
    # the clone shares no repo-local identity with the project (globals are
    # disabled in the isolated environment), so the peer sets its own
    run_git(peer, "config", "user.name", "synthetic-peer-operator")
    run_git(peer, "config", "user.email", "peer-operator@example.invalid")
    (peer / "knowledge" / G2_PAGE).write_bytes(b_bytes)
    run_git(peer, "add", "--", "knowledge")
    run_git(peer, "commit", "-q", "-m", "human: operator amends order-number wording")
    run_git(peer, "push", "-q", "origin", "main")
    b_rev = run_git(peer, "rev-parse", "HEAD").strip()
    run_git(project, "fetch", "-q", str(bare), "main")
    run_git(project, "merge", "-q", "--ff-only", "FETCH_HEAD")
    assert run_git(project, "rev-parse", "HEAD").strip() == b_rev
    assert page.read_bytes() == b_bytes  # the checkout really moved to B

    # the sync changed neither the descriptor bytes nor what is served
    assert current_bytes(project) == descriptor_a_bytes
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        # the pre-existing session still serves the admitted A after the sync
        still_synced = asyncio.run(session_a.read_context_page(G2_PAGE))
        assert still_synced["content"] == a_bytes.decode()  # serves A, not HEAD B
        assert still_synced["bound_release"] == digest_a
        assert cli(["status", "--json", "--project", str(project)]) == 0
        synced = json.loads(capsys.readouterr().out)
        # local HEAD B is disclosed separately from the admitted A
        assert synced["project"]["git"]["head_revision"] == b_rev
        # the bound release comes from the verified A descriptor only
        assert synced["project"]["admission"]["bound_release"] == {
            "digest": digest_a,
            "published_version": a_rev,
            "supported_operations": manifest_a["support"]["operations"],
        }
        assert synced["ready"] is True  # a plain sync never invalidates

    # B activates only through the ordinary native chain: the proposal
    # worktree fast-forwards to the operator's commit, reconcile records
    # that human-created HEAD, then validation, review, preview, confirm
    tree = worktree_of(project, review["proposal"])
    run_git(tree, "merge", "-q", "--ff-only", b_rev)
    admission.reconcile(project, review["proposal"], a_rev, b_rev)
    validated = api.validate_proposal(review["proposal"], b_rev)
    assert validated["ok"] is True, validated["errors"]
    later = api.review_proposal(review["proposal"])
    assert later["revision"] == b_rev
    activate(project, later, preview(project, later, destination, a_rev))

    descriptor_b_bytes = current_bytes(project)
    assert descriptor_b_bytes != descriptor_a_bytes  # activation, not sync
    descriptor_b = json.loads(descriptor_b_bytes)
    manifest_b = descriptor_b["bound_release"]
    digest_b = manifest_b["digest"]
    assert descriptor_b["commit"] == b_rev
    assert manifest_b["knowledge"]["published_version"] == b_rev

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        # the already-open session keeps its pinned A record and still
        # serves A; only a NEW session observes the activated B
        still_a = asyncio.run(session_a.read_context_page(G2_PAGE))
        assert still_a["content"] == a_bytes.decode()
        assert still_a["bound_release"] == digest_a
        session_b = DiscoveryRuntime.open_project(project)
        served_b = asyncio.run(session_b.read_context_page(G2_PAGE))
        assert served_b["content"] == b_bytes.decode()  # a NEW session sees B
        assert served_b["bound_release"] == digest_b
        assert cli(["status", "--json", "--project", str(project)]) == 0
        activated = json.loads(capsys.readouterr().out)
        assert activated["project"]["git"]["head_revision"] == b_rev
        # minimal verified view: digest, published version, operations —
        # no destination, registry or source data can hide in it
        assert activated["project"]["admission"]["bound_release"] == {
            "digest": digest_b,
            "published_version": b_rev,
            "supported_operations": manifest_b["support"]["operations"],
        }
        assert activated["ready"] is True

    # malformed and missing admissions stay distinct diagnostics and can
    # never masquerade as a valid bound release (same coherent journey)
    descriptor = project / ".ariadne" / "current.json"
    descriptor.write_bytes(b"{ not a descriptor")
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        assert cli(["status", "--json", "--project", str(project)]) == 0
        invalid = json.loads(capsys.readouterr().out)
    assert invalid["project"]["admission"]["state"] == "invalid"
    assert "reason" in invalid["project"]["admission"]
    assert "bound_release" not in invalid["project"]["admission"]
    assert invalid["project"]["git"]["head_revision"] == b_rev
    assert invalid["ready"] is False
    descriptor.unlink()
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        assert cli(["status", "--json", "--project", str(project)]) == 0
        missing = json.loads(capsys.readouterr().out)
    assert missing["project"]["admission"] == {"state": "none"}
    assert missing["project"]["git"]["head_revision"] == b_rev
    assert missing["ready"] is False


# --------------------------- T2 technical Reference (spec0029 §1.5)

# Hand-authored oracle data for the extra order_numbers table in the SAME
# approved native DuckDB catalog: the global number is the store prefix
# concatenated with the local number on ALL FOUR rows (including the retained
# leading-zero example). The asserted mapping is therefore NOT contradicted by
# its own verified evidence — spec0010/K4 counterevidence rules refuse an
# asserted claim with any mismatch. Every expected count below is hand-worked
# from these rows and the authored table definition, never taken from output.
T2_ORDER_ROWS = [
    ("ABC", "123123", "ABC123123"),
    ("XYZ", "123123", "XYZ123123"),
    ("ABC", "00123", "ABC00123"),
    ("QQQ", "999999", "QQQ999999"),
]
T2_REFERENCE_PAGE = "references/order-number.md"
T2_MAPPING = "store-prefix-composition"
T2_SELECTION = f"order-number:{T2_MAPPING}"
T2_CITATION_PATH = "references/order-number.md"
# The SDK-authored evidence digest in the submitted golden page (sha256 of
# empty bytes): disclosure only — it must never surface as verified authority.
T2_DUMMY_EVIDENCE_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
# Hand-copied from the submitted golden page (tests/fixtures/lumio_context_
# baseline/references/order-number.md): the FULL authored native metadata must
# survive serving (F3 fix pass, spec0029 §1.5 + spec0011) — a lossy projection
# that turns the authored description/stale_after into unknown is a defect.
T2_GOLDEN_DESCRIPTION = (
    "The shared order-number concept: a globally unique composite order "
    "number and the store-local number it is built from."
)
T2_GOLDEN_STALE_AFTER = "2027-09-30"


def t2_reference_candidate(root: Path):
    """One integrated single-metric candidate that explicitly ADAPTS the
    submitted golden Reference inside the synthetic proposal: the curated
    Entity/title/body/profile identity is preserved except the declared field
    bindings, which are realigned to the actually authored order_numbers table
    in the MEASURED DECLARED order (candidate left store_id then
    local_order_number), and one common umbrella alias ``order number`` is
    authored on BOTH representations so the native whole-alias matcher has a
    genuine shared term. The mapping's MEASURABLE candidate — including the
    explicit scope predicate honoring the local representation's required
    store_id scope, with every authored store listed so all four rows stay
    eligible — is authored BEFORE the first reconcile so native dependency
    capture can see it. The remaining edits are the accepted single-metric
    policy closure of the MVP candidate."""
    import yaml
    from ariadne.sources import table_resource

    from integration.tests.lumio_metric_mvp import CONTROL

    project = content_project(root)
    import duckdb  # pyright: ignore[reportMissingImports] — qualified test env is external

    con = duckdb.connect(str(project / "data" / "orders.duckdb"))
    # test-fixture DDL over test-local column constants
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.execute(
        'CREATE TABLE main."order_numbers"('
        "store_id VARCHAR, local_order_number VARCHAR, global_order_number VARCHAR)"
    )
    # parameterized test-fixture insert (bound parameters only)
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.executemany('INSERT INTO main."order_numbers" VALUES (?, ?, ?)', T2_ORDER_ROWS)
    con.close()
    resource = table_resource("orders", "orders", "main", "order_numbers")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    tree = worktree_of(project, started["proposal"])
    reference = tree / "knowledge" / T2_REFERENCE_PAGE
    meta, body = page_parts(reference)
    extension = meta["ariadne_profile"]["native"]["ariadne"]
    for representation in extension["representations"]:
        # the golden declaration order (global THEN local) is preserved
        if representation["id"] == "global-order-number":
            representation["fields"] = [{"resource": resource, "column": "global_order_number"}]
        else:
            representation["fields"] = [
                {"resource": resource, "column": "store_id"},
                {"resource": resource, "column": "local_order_number"},
            ]
            representation["scope"] = [{"resource": resource, "column": "store_id"}]
        representation["aliases"].append("order number")  # authored shared umbrella alias
    declared_candidate = {
        "family": "prefix",
        "left": [
            {"resource": resource, "column": "store_id"},
            {"resource": resource, "column": "local_order_number"},
        ],
        "right": [{"resource": resource, "column": "global_order_number"}],
        "separator": "",
        "scope": [
            {
                "resource": resource,
                "column": "store_id",
                "op": "in",
                "value": ["ABC", "XYZ", "QQQ"],
            }
        ],
    }
    extension["mappings"][0]["candidate"] = declared_candidate
    # plan25 (r25): the Reference's cited source now names the EXISTING
    # authored KB Policy page (already valid and committed in this candidate
    # — never a legacy fallback), keeping the mapping's source_ids bound to
    # that id; the receipt's Policy dependency is therefore real
    for source in meta["ariadne_profile"]["native"]["sources"]:
        if source.get("id") == "src-owner-rule":
            source["resource"] = "policies/retail-return-policy.md"
    write_page(reference, meta, body)
    (tree / "knowledge/policies/cancelled-orders.md").write_text(CANCELLATION)
    metric = tree / "knowledge/metrics/retail-revenue.md"
    meta, body = page_parts(metric)
    profile = meta["ariadne_profile"]
    profile["required_policies"].append(
        {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
    )
    profile["native"]["sources"].append(
        {"id": "cancelled-orders", "resource": "policies/cancelled-orders.md"}
    )
    profile["ontology_refs"] = [
        {"namespace": "urn:demo:catalog", "identifier": "retail-hierarchy", "revision": "r7"}
    ]
    write_page(metric, meta, body)
    (tree / "knowledge/lumio.yaml").write_text(
        CONTROL
        + yaml.safe_dump(
            {
                "ariadne_context": {
                    "version": 1,
                    "ontology_catalog": {"urn:demo:catalog": {"retail-hierarchy": "r7"}},
                }
            }
        )
    )
    revision = reconcile_knowledge(project, started["proposal"], revision)
    return project, api, started["proposal"], revision, resource, declared_candidate


def test_reference_term_resolution_requires_real_evidence_and_confirmation(
    tmp_path, monkeypatch, capsys
):
    """T2 (spec0029 §1.5): the adapted golden Reference resolves through the
    pinned SDK release on real operator-approved data. A fully validated
    admission without selections serves the asserted mapping UNCONFIRMED; the
    exact existing human selection goes through the native overall preview and
    confirmation (the composite digest binds it) and serves CONFIRMED; after a
    fresh remeasure plus explicit final candidate edit and a new admission
    WITHOUT a new selection, the changed authentic receipt dependency makes
    the old confirmation not current. Only authentic Core receipts carry
    evidence authority — the SDK-authored ariadne_evidence digest is
    disclosure. Exact Resource/column identity, the SDK version-qualified
    citation, Bound Release identity, pinned scope and no-join-authority
    semantics hold throughout; serving is source-free, measurement is not.
    The fix-pass legs pin full native metadata retention (F3), the COMPLETE
    response budget including admission provenance (F4) and global support
    across hidden unreferenced KB pages (F2)."""
    import json

    from ariadne import admission, serve
    from ariadne.cli import main as cli
    from ariadne.discovery import DiscoveryRuntime
    from tests.test_discovery import _source_free_guards

    from integration.tests.lumio_metric_mvp import current_bytes

    project, api, proposal, revision, resource, candidate = t2_reference_candidate(tmp_path)

    # REAL native measurement of the DECLARED candidate against the
    # operator-approved synthetic source (guards are OFF for measurement)
    envelope = api.inspect_mapping(proposal, revision, candidate)
    receipt = envelope["receipt"]
    retained = json.loads(Path(envelope["evidence"]).read_text())
    assert retained == receipt  # the retained evidence file IS the returned receipt
    counts = receipt["counts"]
    assert counts["eligible_left"] == 4  # every composite is non-null and in scope
    assert counts["eligible_right"] == 4  # every global is non-null
    assert counts["tested_left"] == 4  # default 1000-row ceiling covers all rows
    assert receipt["coverage"]["left_in_right"]["matched"] == 4  # all four compose
    assert receipt["mismatch_count"] == 0  # no counterevidence for the asserted claim
    assert [column["name"] for column in receipt["dependencies"]["assets"][0]["columns"]] == [
        "store_id",
        "local_order_number",
        "global_order_number",
    ]  # the authored table definition order
    # plan25 (r25): the receipt's cited-Policy dependency names the
    # repository-qualified knowledge path of the EXISTING authored KB Policy
    # and the sha256 of the actual committed candidate-input bytes —
    # input-derived, never output-derived. Intended RED: capture currently
    # stores the unqualified resource path (the measurement itself stays
    # authentic and otherwise intact).
    import hashlib

    policy_input = (
        worktree_of(project, proposal) / "knowledge" / "policies" / "retail-return-policy.md"
    ).read_bytes()
    [policy_dependency] = receipt["dependencies"]["policy_osi"]
    assert policy_dependency["resource"] == "knowledge/policies/retail-return-policy.md"
    assert policy_dependency["digest"] == hashlib.sha256(policy_input).hexdigest()

    # the operator's explicit later candidate edit attaches the AUTHENTIC
    # receipt id to the declared mapping
    def _attach(receipt_id: str, previous: str) -> str:
        tree = worktree_of(project, proposal)
        page = tree / "knowledge" / T2_REFERENCE_PAGE
        meta, body = page_parts(page)
        mapping = meta["ariadne_profile"]["native"]["ariadne"]["mappings"][0]
        assert mapping["id"] == T2_MAPPING and mapping["claim"] == "asserted"
        mapping["receipt_ids"] = [receipt_id]
        write_page(page, meta, body)
        return reconcile_knowledge(project, proposal, previous)

    revision = _attach(receipt["receipt_id"], revision)
    validated = api.validate_proposal(proposal, revision)
    assert validated["ok"] is True, validated["errors"]
    # validation finalizes generated evidence in a NEW final commit: every
    # later operation uses that actual revision, never the input commit
    revision = validated["revision"]
    review = api.review_proposal(proposal)
    assert review["revision"] == revision
    [assertion] = review["mapping_assertions"]
    assert assertion["reference"] == "order-number"
    assert assertion["mapping"] == T2_MAPPING
    assert assertion["claim"] == "asserted" and assertion["confirmable"] is True
    # the reviewed Core-owned summary carries id/digest of the actual receipt
    assert [item["id"] for item in assertion["receipts"]] == [receipt["receipt_id"]]
    assert [item["digest"] for item in assertion["receipts"]] == [receipt["integrity_digest"]]

    destination = tmp_path / "published"

    # [1] first overall admission WITHOUT selections: unconfirmed serving
    activate(project, review, preview(project, review, destination))
    record = json.loads(current_bytes(project))
    assert record["confirmed_mappings"] == []
    digest_a = record["bound_release"]["digest"]
    citation = f"{NAMESPACE} entity:order-number v{revision} {T2_CITATION_PATH}"

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        session = DiscoveryRuntime.open_project(project)
        served = asyncio.run(session.resolve_term("order number"))
        assert served["total_matches"] == 2 and served["ambiguous"] is True
        assert served["truncated"] is False and served["complete"] is True
        # stable native order follows the declaration order: global THEN local
        assert [match["representation"] for match in served["matches"]] == [
            "global-order-number",
            "local-order-number",
        ]
        for match in served["matches"]:
            assert match["page"] == T2_REFERENCE_PAGE
            assert match["entity_id"] == "entity:order-number"
            assert match["published_version"] == revision
            assert match["bound_release"] == digest_a
            assert match["citation"] == citation  # the SDK version-qualified citation
            assert not ({"sql", "transform", "join"} & set(match))
        # the local representation is located BY identity, not destructured order
        local = next(
            match for match in served["matches"] if match["representation"] == "local-order-number"
        )
        assert local["level"] == "representation" and local["draft"] is False
        # exact Resource+column identity in the MEASURED DECLARED order
        assert local["fields"] == [
            {"resource": resource, "column": "store_id"},
            {"resource": resource, "column": "local_order_number"},
        ]
        assert local["scope"] == [{"resource": resource, "column": "store_id"}]
        [mapping_view] = local["mappings"]
        assert mapping_view["id"] == T2_MAPPING
        assert mapping_view["family"] == "prefix"
        assert mapping_view["claim"] == "asserted"
        assert mapping_view["confirmation"] == "unconfirmed"  # admission is not K4
        assert mapping_view["receipt_ids"] == [receipt["receipt_id"]]
        assert {view["digest"] for view in mapping_view["evidence"]} == {
            receipt["integrity_digest"]
        }
        assert all(view["freshness"]["state"] == "as_of" for view in mapping_view["evidence"])
        assert T2_DUMMY_EVIDENCE_DIGEST not in {
            view["digest"] for view in mapping_view["evidence"]
        }  # the SDK-authored digest never poses as authority
        # F3 (fix pass): the existing match fields retain the authored golden
        # description and expiry; full input metadata must not be projected
        # away to unknown or replaced by a new duplicate output schema.
        assert local["description"] == T2_GOLDEN_DESCRIPTION
        assert local["freshness"]["stale_after"] == T2_GOLDEN_STALE_AFTER
        # native matcher semantics: exact phrase, exact qualified field,
        # never case-folded fields, whole aliases only
        exact = asyncio.run(session.resolve_term("GLOBAL Order Number"))
        assert [match["representation"] for match in exact["matches"]] == ["global-order-number"]
        assert exact["ambiguous"] is False and exact["total_matches"] == 1
        field = asyncio.run(
            session.resolve_term({"resource": resource, "column": "global_order_number"})
        )
        assert [match["representation"] for match in field["matches"]] == ["global-order-number"]
        missed = asyncio.run(
            session.resolve_term({"resource": resource, "column": "GLOBAL_ORDER_NUMBER"})
        )
        assert missed["total_matches"] == 0
        assert asyncio.run(session.resolve_term("order"))["total_matches"] == 0
        # one real CLI resolution on the same admitted Reference (JSON default)
        assert cli(["resolve-term", "order number", "--project", str(project)]) == 0
        cli_result = json.loads(capsys.readouterr().out)
        assert [match["representation"] for match in cli_result["matches"]] == [
            "global-order-number",
            "local-order-number",
        ]
        cli_local = next(
            match
            for match in cli_result["matches"]
            if match["representation"] == "local-order-number"
        )
        assert cli_local["mappings"][0]["confirmation"] == "unconfirmed"

    # [2] the ordinary human selection through native preview + confirmation:
    # the composite digest binds the exact selection on BOTH calls
    review = api.review_proposal(proposal)
    composite = admission.overall_review(
        project,
        proposal,
        review["revision"],
        review["review_digest"],
        destination=destination,
        expected_current=review["revision"],
        confirm_mappings=[T2_SELECTION],
    )
    assert composite["mapping_selections"] == [T2_SELECTION]
    admission.admit_revision(
        project,
        proposal,
        review["revision"],
        review["review_digest"],
        confirmed_by="human:synthetic-operator",
        confirm_mappings=[T2_SELECTION],
        overall_preview=composite,
        confirmed_overall_digest=composite["digest"],
    )
    confirmed = json.loads(current_bytes(project))
    [entry] = confirmed["confirmed_mappings"]
    assert entry["page"] == T2_REFERENCE_PAGE and entry["mapping"] == T2_MAPPING
    assert [item["digest"] for item in entry["receipts"]] == [receipt["integrity_digest"]]

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        session = DiscoveryRuntime.open_project(project)
        served = asyncio.run(session.resolve_term("order number"))
        local = next(
            match for match in served["matches"] if match["representation"] == "local-order-number"
        )
        [mapping_view] = local["mappings"]
        assert mapping_view["confirmation"] == "confirmed"  # exact recorded selection
        assert all(view["freshness"]["state"] == "as_of" for view in mapping_view["evidence"])
        # one real MCP resolution on the same admitted Reference: the
        # documented bare-dict tool form — exactly one JSON text block
        app = serve.build_app(QueryRuntime, project=str(project))
        mcp = asyncio.run(app.call_tool("resolve_term", {"request": "order number"}))
        assert not getattr(mcp, "is_error", False)
        assert mcp.structured_content is None
        blocks = list(mcp.content)
        assert len(blocks) == 1 and blocks[0].type == "text"
        mcp_result = json.loads(blocks[0].text)
        assert [match["representation"] for match in mcp_result["matches"]] == [
            "global-order-number",
            "local-order-number",
        ]
        mcp_local = next(
            match
            for match in mcp_result["matches"]
            if match["representation"] == "local-order-number"
        )
        assert mcp_local["mappings"][0]["confirmation"] == "confirmed"

    # [3] a fresh remeasure of the SAME valid data is the changed dependency
    # (a new authentic receipt id and integrity digest — the native
    # remeasure-breaks-inheritance rule), then the explicit final candidate
    # edit re-attaches it and the new admission carries NO new selection
    remeasured = api.inspect_mapping(proposal, revision, candidate)
    receipt_b = remeasured["receipt"]
    assert receipt_b["receipt_id"] != receipt["receipt_id"]
    assert receipt_b["integrity_digest"] != receipt["integrity_digest"]
    assert receipt_b["mismatch_count"] == 0  # the data still composes completely
    assert receipt_b["coverage"]["left_in_right"]["matched"] == 4
    revision_b = _attach(receipt_b["receipt_id"], revision)
    validated_b = api.validate_proposal(proposal, revision_b)
    assert validated_b["ok"] is True, validated_b["errors"]
    revision_b = validated_b["revision"]
    review_b = api.review_proposal(proposal)
    assert review_b["revision"] == revision_b
    activate(project, review_b, preview(project, review_b, destination, review["revision"]))

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        session = DiscoveryRuntime.open_project(project)
        served = asyncio.run(session.resolve_term("order number"))
        local = next(
            match for match in served["matches"] if match["representation"] == "local-order-number"
        )
        [mapping_view] = local["mappings"]
        assert mapping_view["confirmation"] == "unconfirmed"  # the old one is not current
        assert mapping_view["receipt_ids"] == [receipt_b["receipt_id"]]
        assert {view["digest"] for view in mapping_view["evidence"]} == {
            receipt_b["integrity_digest"]
        }

    # F4 (fix pass): the COMPLETE final response — admission provenance
    # included — must respect the host response budget. A ceiling between the
    # serialized result without admission and the complete result refuses the
    # whole CLI operation, still source-free; only the boundary is derived,
    # from the independently serialized mandatory envelopes (never expected
    # semantics from output), and the host config is restored afterwards.
    import yaml

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        config = project / "ariadne.yaml"
        original = config.read_text()
        session = DiscoveryRuntime.open_project(project)
        complete = asyncio.run(session.resolve_term("order number"))
        without_admission = {key: value for key, value in complete.items() if key != "admission"}
        floor = max(query_results.result_json_bytes(form) for form in query_results.refusal_forms())
        under = query_results.result_json_bytes(without_admission)
        full = query_results.result_json_bytes(complete)
        assert floor < under < full  # a real window exists for the boundary
        document = yaml.safe_load(original)
        document["query"] = {"response_bytes": under}
        config.write_text(yaml.safe_dump(document, sort_keys=False))
        code = cli(["resolve-term", "order number", "--project", str(project)])
        failure = capsys.readouterr()
        assert code == 1 and not failure.out
        refused = json.loads(failure.err)
        assert refused["error"]["code"] == "result_byte_limit"
        config.write_text(original)
        assert cli(["resolve-term", "order number", "--project", str(project)]) == 0
        capsys.readouterr()

    # F2 (fix pass): support is GLOBAL across the whole captured KB — a
    # producer-valid hidden Reference with no mappings and no fabricated
    # evidence, whose representation names a canonical URI of a synthetic
    # UNAPPROVED source, must fail native validation naming the knowledge
    # path and the unapproved source; the already active descriptor stays
    # byte-identical (validation is not admission)
    from ariadne.sources import table_resource

    descriptor_before = current_bytes(project)
    tree = worktree_of(project, proposal)
    unapproved = table_resource("unapproved-source", None, "main", "orders")
    # The operator-owned document is outside the captured candidate. A relative
    # path escaping the KB must never be classified as frozen bundle evidence.
    outside = tmp_path / "uncaptured-reference-evidence.md"
    outside.write_text("Author-owned evidence outside the captured release.\n")
    escape_resource = "../" * 32 + outside.as_posix().lstrip("/")
    hidden = tree / "knowledge/references/internal-identifiers.md"
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text(
        "---\n"
        'id: "entity:internal-identifiers"\n'
        'title: "Internal Identifiers"\n'
        "entity_types:\n"
        "  - reference\n"
        "tags:\n"
        "  - internal\n"
        'summary: "Hidden internal identifier representations."\n'
        'lifecycle: "approved"\n'
        'visibility: "restricted"\n'
        "sources:\n"
        '  - id: "src-internal-memo"\n'
        '    title: "Internal memo, 2026-10-01"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: reference\n"
        "  native:\n"
        "    type: reference\n"
        '    title: "Internal Identifiers"\n'
        '    description: "Hidden internal identifier representations."\n'
        "    tags:\n"
        "      - internal\n"
        "    stale_after: 2027-12-31\n"
        "    sources:\n"
        '      - id: "src-internal-memo"\n'
        '        title: "Internal memo, 2026-10-01"\n'
        f'        resource: "{escape_resource}"\n'
        "    ariadne:\n"
        "      version: 1\n"
        "      reference_role: identifier\n"
        "      representations:\n"
        "        - id: internal-order-id\n"
        "          aliases:\n"
        "            - internal order id\n"
        "          fields:\n"
        f'            - resource: "{unapproved}"\n'
        '              column: "id"\n'
        "          scope: []\n"
        "      mappings: []\n"
        "---\n\n"
        "# Internal Identifiers\n\n"
        "Hidden internal identifier representations.\n"
    )
    # plan25 (r25): immediate native dependency invalidation — an explicit
    # candidate edit to the CITED KB Policy breaks the retained receipt's
    # bound Policy digest; validation refuses without any new inspection,
    # alongside the hidden-reference refusal in the existing third native
    # validation round; the active descriptor stays unchanged
    policy_page = worktree_of(project, proposal) / "knowledge/policies/retail-return-policy.md"
    policy_meta, policy_body = page_parts(policy_page)
    write_page(
        policy_page,
        policy_meta,
        policy_body + "\nRevised return-policy wording (dependency mutation).\n",
    )

    hidden_revision = reconcile_knowledge(project, proposal, revision_b)
    refused = api.validate_proposal(proposal, hidden_revision)
    assert refused["ok"] is False
    diagnostics = "; ".join(refused["errors"])
    assert "knowledge/references/internal-identifiers.md" in diagnostics
    assert "unapproved-source" in diagnostics
    assert escape_resource in diagnostics  # escaping evidence is explicitly refused
    assert current_bytes(project) == descriptor_before  # validation ≠ activation

    assert "retail-return-policy" in diagnostics
    assert "whose content changed since the measurement" in diagnostics


# ------------------------- P1 technical profiles (spec0032 §§5–6, §10.1–§10.3)

# Hand-authored oracle data, independent of the implementation (#83 prep;
# spec0032 §8: expected values come from authored inputs and these contracts,
# never from implementation output). The same approved synthetic DuckDB
# catalog gains one lookup collection so the governed query path has a REAL
# proven relationship: every order's status resolves to exactly one curated
# label (hand-worked join over the authored rows), completed 100 + 50 imply
# revenue 150 for "Completed order" and the sanctioned exclusion leaves the
# "Cancelled order" group at 0.0 — never a fabricated numeric check.
P1_STATUS_ROWS = [("completed", "Completed order"), ("cancelled", "Cancelled order")]
P1_ORDERS_ASSET = {"source": "orders", "catalog": "orders", "schema": "main", "table": "orders"}
P1_STATUS_ASSET = {
    "source": "orders",
    "catalog": "orders",
    "schema": "main",
    "table": "order_status",
}
# Authored DDL facts (the independent schema oracle): exact column identity
# and type in ordinal order, hand-copied from the fixture DDL below.
P1_ORDERS_COLUMNS = [("id", "INTEGER"), ("amount", "DOUBLE"), ("status", "VARCHAR")]
P1_STATUS_COLUMNS = [("status", "VARCHAR"), ("label", "VARCHAR")]
# Hand-counted observations over the authored rows (never profiler output):
# 3 order rows, each column NULL-free; id/amount distinct 3, status distinct
# 2; 2 lookup rows, both columns distinct 2, NULL-free.
P1_ORDERS_COUNTS = {"row_count": 3, "id": (0, 3), "amount": (0, 3), "status": (0, 2)}
P1_STATUS_COUNTS = {"row_count": 2, "status": (0, 2), "label": (0, 2)}
P1_QUERY_OPS = ("query_detail", "query_records", "define_metric")
P1_NINE_OPERATIONS = [
    "get_metric",
    "discover",
    "list_metrics",
    "query_metrics",
    "list_datasets",
    "list_context_pages",
    "read_context_page",
    "search_context",
    "resolve_term",
]
P1_REV1_PROFILES = ["metric", "policy", "reference"]
P1_REV2_PROFILES = ["metric", "policy", "reference", "dataset", "table", "computation"]
P1_CURATED_MARKER = "CURATED-MARKER status wording is owned by the retail desk"

# Parent-dispositioned fixture layout: one dataset per model — the written
# source-approval boundary refuses multi-dataset models, and a metrics-less
# model cannot render — so the lookup lives in its own single-dataset model
# with one trivial COUNT(*) metric (unambiguous in a single-dataset model).
P1_LOOKUP_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: status_lookup
    description: Order status lookup model
    datasets:
      - name: order_status
        source: orders.main.order_status
        primary_key: [status]
        fields:
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
          - name: status_label
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: label
            dimension: {}
    metrics:
      - name: label_count
        description: Count of curated status labels
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

# The lookup model's inert KB Metric page: exact metric_ref, producer-valid
# native base metadata and an EMPTY typed required_policies closure — no
# binding classification is consumed for it and no journey value depends on
# it (scaffolding only, per the parent's bounded correction grant).
P1_LOOKUP_METRIC_PAGE = (
    "---\n"
    'id: "entity:label-count"\n'
    "entity_types:\n"
    "  - metric\n"
    "tags:\n"
    "  - retail\n"
    "  - operations\n"
    'title: "Curated Status Labels (Metric)"\n'
    'summary: "Count of curated order status labels; scaffolding for the lookup model."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "src-ops-lookup"\n'
    '    title: "Operations lookup review, 2026-10-22"\n'
    "ariadne_profile:\n"
    "  version: 1\n"
    "  kind: metric\n"
    "  metric_ref:\n"
    '    model: "status_lookup"\n'
    '    metric: "label_count"\n'
    "  required_policies: []\n"
    "  native:\n"
    "    type: metric\n"
    '    status: "stable"\n'
    '    title: "Curated status labels"\n'
    '    description: "Count of curated order status labels."\n'
    "    tags:\n"
    "      - operations\n"
    "    stale_after: 2027-06-30\n"
    "    sources:\n"
    '      - id: "src-ops-lookup"\n'
    '        title: "Operations lookup review, 2026-10-22"\n'
    # parent-dispositioned: the established native metadata vocabulary for a
    # semantic-definition provenance string (context._attach_metric_metadata);
    # non-policy, so the EMPTY typed closure stays consistent
    '    governed_by: "semantic_layer status_lookup::label_count"\n'
    "    dimensions:\n"
    "      - status_label\n"
    "    grain:\n"
    "      primary_key:\n"
    "        - status\n"
    '      cardinality_enforcement: "strict_1_to_1"\n'
    "---\n"
    "\n"
    "# Curated Status Labels (Metric)\n"
    "\n"
    "Fixture scaffolding metric for the lookup model: it counts the curated\n"
    "status labels, carries an empty Policy closure and participates in no\n"
    "governed journey expectation.\n"
)

# The classic OKF graph-admission page for the lookup metric (issue #30:
# every graph metric requires a cited context_layer metric page citing a
# CONTAINED policy). Explicit human-authored compatibility scaffolding for
# the unchanged graph admission — NOT a KB-content mirror, not an SDK Policy
# edge, and it value-attests nothing.
P1_LOOKUP_OKF_METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "status: draft\n"
    "title: label_count\n"
    "description: Count of curated status labels; classic graph-admission page.\n"
    "tags: [metric]\n"
    "sources:\n"
    "  - id: all-orders-count\n"
    "    resource: policies/all-orders-count.md\n"
    "    title: All orders count\n"
    "---\n\n"
    "# label_count\n"
)

# F3 (#83 review fix, spec0032 §10.2): a real DERIVED metric in the same
# valid single-dataset retail_sales model — the expression names the metric
# revenue, so the graph derives deps=(revenue,) while the model keeps exactly
# one dataset. The +1 oracle is hand-worked from the authored 150.0/0.0
# revenue result, never from any product output.
P1_DERIVED_METRIC = """\
      - name: revenue_plus_one
        description: Derived recognized revenue plus one
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: revenue + 1
"""

# The derived metric's classic graph-admission page (issue #30: every graph
# metric needs a context_layer metric page citing an EXISTING contained
# policy — explicit human-authored compatibility input, not a KB mirror).
P1_DERIVED_OKF_METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "status: draft\n"
    "title: revenue_plus_one\n"
    "description: Derived recognized revenue plus one; classic graph-admission page.\n"
    "tags: [metric]\n"
    "sources:\n"
    "  - id: all-orders-count\n"
    "    resource: policies/all-orders-count.md\n"
    "    title: All orders count\n"
    "---\n\n"
    "# revenue_plus_one\n"
)

# The derived metric's inert KB Metric page (native completeness requires
# one Context Binding per model metric): empty typed closure — no binding
# classification is consumed for it, and governed_by names the semantic
# layer, never a policies/ path.
P1_DERIVED_METRIC_PAGE = (
    "---\n"
    'id: "entity:revenue-plus-one"\n'
    "entity_types:\n"
    "  - metric\n"
    "tags:\n"
    "  - retail\n"
    "  - finance\n"
    'title: "Recognized Revenue Plus One (Metric)"\n'
    'summary: "Derived recognized revenue plus one; scaffolding for the bound model metric."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "src-ops-derived"\n'
    '    title: "Operations derived-metric review, 2026-10-22"\n'
    "ariadne_profile:\n"
    "  version: 1\n"
    "  kind: metric\n"
    "  metric_ref:\n"
    '    model: "retail_sales"\n'
    '    metric: "revenue_plus_one"\n'
    "  required_policies: []\n"
    "  native:\n"
    "    type: metric\n"
    '    status: "stable"\n'
    '    title: "Recognized revenue plus one"\n'
    '    description: "Derived recognized revenue plus one."\n'
    "    tags:\n"
    "      - finance\n"
    "    stale_after: 2027-06-30\n"
    "    sources:\n"
    '      - id: "src-ops-derived"\n'
    '        title: "Operations derived-metric review, 2026-10-22"\n'
    '    governed_by: "semantic_layer retail_sales::revenue_plus_one"\n'
    "    dimensions:\n"
    "      - status\n"
    "    grain:\n"
    "      primary_key:\n"
    "        - id\n"
    '      cardinality_enforcement: "strict_1_to_1"\n'
    "---\n"
    "\n"
    "# Recognized Revenue Plus One (Metric)\n"
    "\n"
    "Fixture scaffolding metric for the derived closure: it adds one to the\n"
    "sanctioned revenue exclusion, carries an empty Policy closure and\n"
    "participates in no binding classification.\n"
)

# D3 (#83 delta review): one UNUSED later-loaded single-dataset model over
# the EXACT same physical orders source — legitimate semantic reuse of a
# physical table (semantic_graph checks dataset-NAME uniqueness, never
# source uniqueness). It is never requested anywhere; every existing
# admission/derived-only/refusal/serving invariant must hold unchanged,
# proving unrelated catalog content cannot replace a consumed subject's
# actual plan lineage. Explicit independent compatibility scaffolding, not
# a maintained KB mirror.
P1_UNUSED_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: zz_unused_orders
    description: Unused later-loaded alias over the same physical orders source
    datasets:
      - name: unused_orders
        source: orders.main.orders
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
            dimension: {}
    metrics:
      - name: unused_order_count
        description: Count of all order rows through the unused alias
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

# The unused alias metric's classic graph-admission page (cites an EXISTING
# contained policy — the unchanged issue #30 compatibility rule).
P1_UNUSED_OKF_METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "status: draft\n"
    "title: unused_order_count\n"
    "description: Unused-alias order count; classic graph-admission page.\n"
    "tags: [metric]\n"
    "sources:\n"
    "  - id: all-orders-count\n"
    "    resource: policies/all-orders-count.md\n"
    "    title: All orders count\n"
    "---\n\n"
    "# unused_order_count\n"
)

# The unused alias metric's inert KB Context Binding: empty typed closure,
# semantic-layer governed_by, valid slug IDs — requested nowhere.
P1_UNUSED_METRIC_PAGE = (
    "---\n"
    'id: "entity:unused-order-count"\n'
    "entity_types:\n"
    "  - metric\n"
    "tags:\n"
    "  - retail\n"
    'title: "Unused Order Count (Metric)"\n'
    'summary: "Count of all order rows through the unused later-loaded alias."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "src-ops-unused"\n'
    '    title: "Operations unused-alias review, 2026-10-22"\n'
    "ariadne_profile:\n"
    "  version: 1\n"
    "  kind: metric\n"
    "  metric_ref:\n"
    '    model: "zz_unused_orders"\n'
    '    metric: "unused_order_count"\n'
    "  required_policies: []\n"
    "  native:\n"
    "    type: metric\n"
    '    status: "stable"\n'
    '    title: "Unused order count"\n'
    '    description: "Count of all order rows through the unused alias."\n'
    "    tags:\n"
    "      - operations\n"
    "    stale_after: 2027-06-30\n"
    "    sources:\n"
    '      - id: "src-ops-unused"\n'
    '        title: "Operations unused-alias review, 2026-10-22"\n'
    '    governed_by: "semantic_layer zz_unused_orders::unused_order_count"\n'
    "    dimensions:\n"
    "      - id\n"
    "    grain:\n"
    "      primary_key:\n"
    "        - id\n"
    '      cardinality_enforcement: "strict_1_to_1"\n'
    "---\n"
    "\n"
    "# Unused Order Count (Metric)\n"
    "\n"
    "Fixture scaffolding metric for the unused physical-source alias: it is\n"
    "never requested and exists only so an unrelated semantic dataset shares\n"
    "the physical orders resource.\n"
)

P1_GRAPH = """\
version: 1
relationships:
  - name: order_status_lookup
    cardinality: many_to_one
    from_dataset: orders
    from_fields: [status]
    to_dataset: order_status
    to_fields: [status]
conformed_dimensions: []
"""

# An existing, producer-valid Policy page that NO consumed subject requires:
# only an invented-obligation binding may ever name it (§10.1).
P1_HYGIENE_POLICY = """\
---
id: entity:order-label-hygiene
entity_types: [policy]
tags: [policy]
title: Order Label Hygiene
summary: Advisory wording rules for order status labels, never required by a subject.
visibility: public
lifecycle: approved
sources:
  - id: human-label-hygiene
    title: Synthetic operator rule
ariadne_profile:
  version: 1
  kind: policy
  required_policies: []
  native:
    type: policy
    title: Order Label Hygiene
    description: Advisory wording rules for order status labels.
    status: stable
    tags: [policy]
    stale_after: 2027-06-30
    sources:
      - id: human-label-hygiene
        title: Synthetic operator rule
---

# Order Label Hygiene

Advisory wording rules for order status labels. No consumed calculation or
source requires this policy; it exists so an invented obligation can name a
genuinely existing Policy page.
"""


def _p1_selector_text(bindings: dict) -> str:
    """The revision-2 integrated selector: the five existing keys unchanged
    plus exactly the two optional §10.1 keys (support_revision, the authored
    policy_bindings block of version 1)."""
    import yaml

    return (
        "version: 1\n"
        "mode: integrated\n"
        "subtree: knowledge\n"
        f"namespace: {NAMESPACE}\n"
        "profile: ariadne-context/1\n"
        + yaml.safe_dump({"support_revision": 2, "policy_bindings": bindings}, sort_keys=False)
    )


def _p1_bindings(orders_resource: str, status_resource: str) -> dict:
    """The authored §10.1 binding inventory (spec0032 §10.2 identities): the
    metric subject's complete closure is exactly classified — the Return
    Policy explanatory for the governed operations, the sanctioned Cancelled
    Orders exclusion executable for query_metrics through the one catalog
    check that actually executes there — and the Computation page's own
    closure is classified explanatory. Every identity string comes from the
    authored constants, never from implementation output. The executable
    binding's dependencies are the metric subject's OWN static inventory:
    the revenue expression reads only the orders table; order_status is a
    request-selected lookup (§10.2 binds the subject inventory, never every
    graph-reachable source — lookup coverage stays a #84 request-inventory
    concern)."""
    return {
        "version": 1,
        "bindings": [
            {
                "subject": {"kind": "metric", "identity": "retail_sales::revenue"},
                "policy": {"namespace": NAMESPACE, "entity_id": "entity:retail-return-policy"},
                "operations": ["get_metric", "query_metrics"],
                "enforcement": None,
            },
            {
                "subject": {"kind": "metric", "identity": "retail_sales::revenue"},
                "policy": {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"},
                "operations": ["query_metrics"],
                "enforcement": {
                    "check": "graph.relationship_audit",
                    "definition": "retail_sales::revenue",
                    "dependencies": [orders_resource],
                },
            },
            {
                "subject": {"kind": "computation", "identity": "retail_sales::revenue"},
                "policy": {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"},
                "operations": ["get_metric", "query_metrics"],
                "enforcement": None,
            },
        ],
    }


def _p1_computation_page() -> str:
    """A producer-valid Computation page with the honest attestation: pending
    state and no attester (spec0032 §5): authored verified/attester values
    grant no authority, so the page claims none."""
    return (
        "---\n"
        'id: "entity:revenue-computation"\n'
        "entity_types:\n"
        "  - computation\n"
        "tags:\n"
        "  - finance\n"
        'title: "Recognized Revenue Computation"\n'
        'summary: "The sanctioned revenue exclusion, curated for review."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        '  - id: "src-computation-review"\n'
        '    title: "Computation review, 2026-10-22"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: computation\n"
        "  core_ref:\n"
        "    kind: semantic\n"
        '    id: "retail_sales::revenue"\n'
        "  required_policies:\n"
        f'    - namespace: "{NAMESPACE}"\n'
        '      entity_id: "entity:cancelled-orders"\n'
        "  native:\n"
        "    type: computation\n"
        '    status: "stable"\n'
        '    title: "Recognized revenue computation"\n'
        '    description: "The sanctioned revenue exclusion, curated for review."\n'
        "    tags:\n"
        "      - finance\n"
        "    stale_after: 2020-01-01\n"
        "    attestation: pending\n"
        "    sources:\n"
        '      - id: "src-computation-review"\n'
        '        title: "Computation review, 2026-10-22"\n'
        "---\n"
        "\n"
        "# Recognized Revenue Computation\n"
        "\n"
        "CURATED-MARKER the sanctioned expression excludes cancelled orders; this\n"
        "page curates the business meaning only and claims no independent\n"
        "numerical validation.\n"
    )


def _p1_hidden_table_page(resource: str) -> str:
    """A hidden (restricted), otherwise producer-valid Table page whose
    core_ref names a canonical table of a synthetic UNAPPROVED source: the
    whole-KB technical-profile validation must refuse naming it (§3)."""
    return (
        "---\n"
        'id: "entity:internal-orders-table"\n'
        "entity_types:\n"
        "  - table\n"
        "tags:\n"
        "  - internal\n"
        'title: "Internal Orders Table"\n'
        'summary: "Hidden internal binding for an unapproved source."\n'
        'lifecycle: "approved"\n'
        'visibility: "restricted"\n'
        "sources:\n"
        '  - id: "src-internal-catalog"\n'
        '    title: "Internal catalog memo, 2026-10-22"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: table\n"
        "  core_ref:\n"
        "    kind: resource\n"
        f'    id: "{resource}"\n'
        "  native:\n"
        "    type: table\n"
        '    title: "Internal Orders Table"\n'
        '    description: "Hidden internal binding for an unapproved source."\n'
        "    tags:\n"
        "      - internal\n"
        "    stale_after: 2027-12-31\n"
        "    sources:\n"
        '      - id: "src-internal-catalog"\n'
        '        title: "Internal catalog memo, 2026-10-22"\n'
        "---\n"
        "\n"
        "# Internal Orders Table\n"
        "\n"
        "Hidden internal binding for an unapproved source.\n"
    )


def _p1_control() -> str:
    """The KB control extended for the technical categories and ontology
    entity types (the established category/ontology extension idiom)."""
    from integration.tests.lumio_metric_mvp import CONTROL

    return CONTROL.replace(
        "  - name: metrics\n",
        "  - name: metrics\n  - name: datasets\n  - name: tables\n  - name: computations\n",
    ).replace(
        "    metric: {}\n",
        "    metric: {}\n    dataset: {}\n    table: {}\n    computation: {}\n",
    )


def _p1_project(root: Path, bindings: dict, unused_alias: bool = False):
    """The shared P1 baseline: the proven synthetic catalog plus the authored
    order_status lookup collection (real DDL + curated rows), the model's
    lookup dataset, the proven many-to-one graph edge and the revision-2
    selector carrying the authored policy_bindings block. ``unused_alias``
    additionally commits the D3 unused later-loaded model over the SAME
    physical orders source (admission case only)."""
    import duckdb  # pyright: ignore[reportMissingImports] — qualified test env is external

    project = content_project(root)
    con = duckdb.connect(str(project / "data" / "orders.duckdb"))
    # test-fixture DDL over test-local column constants
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.execute('CREATE TABLE main."order_status"(status VARCHAR, label VARCHAR)')
    # parameterized test-fixture insert (bound parameters only)
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.executemany('INSERT INTO main."order_status" VALUES (?, ?)', P1_STATUS_ROWS)
    con.close()
    # parent-dispositioned fixture layout: retail_sales keeps its existing
    # single orders dataset and the revenue metric — the qualified predicate
    # stays the authored fact that the expression reads only orders — and the
    # lookup collection lives in its own single-dataset status_lookup model.
    model = project / "semantic_layer" / "models" / "retail_sales.yml"
    model.write_text(
        model.read_text().replace("WHEN status <> 'cancelled'", "WHEN orders.status <> 'cancelled'")
        + P1_DERIVED_METRIC
    )
    (project / "semantic_layer" / "models" / "status_lookup.yml").write_text(P1_LOOKUP_MODEL)
    (project / "semantic_layer" / "graph.yml").write_text(P1_GRAPH)
    (project / "context_layer" / "metrics" / "label_count.md").write_text(P1_LOOKUP_OKF_METRIC_PAGE)
    (project / "context_layer" / "metrics" / "revenue_plus_one.md").write_text(
        P1_DERIVED_OKF_METRIC_PAGE
    )
    unused_files: list[str] = []
    if unused_alias:
        (project / "semantic_layer" / "models" / "zz_unused_orders.yml").write_text(P1_UNUSED_MODEL)
        (project / "context_layer" / "metrics" / "unused_order_count.md").write_text(
            P1_UNUSED_OKF_METRIC_PAGE
        )
        unused_files = [
            "semantic_layer/models/zz_unused_orders.yml",
            "context_layer/metrics/unused_order_count.md",
        ]
    (project / "context_integration.yaml").write_text(_p1_selector_text(bindings))
    run_git(
        project,
        "add",
        "--",
        "semantic_layer/graph.yml",
        "semantic_layer/models/retail_sales.yml",
        "semantic_layer/models/status_lookup.yml",
        "context_layer/metrics/label_count.md",
        "context_layer/metrics/revenue_plus_one.md",
        "context_integration.yaml",
        *unused_files,
    )
    run_git(project, "commit", "-q", "-m", "human: lookup collection, graph, revision-2 selector")
    return project


def _p1_kb_candidate(
    project: Path, api: AuthoringProject, started: dict, revision: str, unused_alias: bool = False
):
    """The shared supported-shape candidate edits: the metric's complete
    typed closure (Return Policy + Cancelled Orders), the Cancelled Orders
    Policy page, the unreferenced Hygiene Policy (invented-obligation bait),
    the technical control file, the hand-authored Computation page and —
    with ``unused_alias`` — the D3 unused-alias KB Context Binding."""
    tree = worktree_of(project, started["proposal"])
    reference = tree / "knowledge/references/order-number.md"
    meta, body = page_parts(reference)
    del meta["ariadne_profile"]  # visible Git candidate edit, never an input conversion
    write_page(reference, meta, body)
    (tree / "knowledge/policies/cancelled-orders.md").write_text(CANCELLATION)
    (tree / "knowledge/policies/order-label-hygiene.md").write_text(P1_HYGIENE_POLICY)
    (tree / "knowledge/metrics/label-count.md").write_text(P1_LOOKUP_METRIC_PAGE)
    (tree / "knowledge/metrics/revenue-plus-one.md").write_text(P1_DERIVED_METRIC_PAGE)
    if unused_alias:
        (tree / "knowledge/metrics/unused-order-count.md").write_text(P1_UNUSED_METRIC_PAGE)
    metric = tree / "knowledge/metrics/retail-revenue.md"
    meta, body = page_parts(metric)
    meta["ariadne_profile"]["required_policies"].append(
        {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
    )
    write_page(metric, meta, body)
    (tree / "knowledge/computations").mkdir(parents=True, exist_ok=True)
    (tree / "knowledge/computations/revenue.md").write_text(_p1_computation_page())
    (tree / "knowledge/lumio.yaml").write_text(_p1_control())
    return reconcile_knowledge(project, started["proposal"], revision)


def _p1_generated_table_page(tree: Path, resource: str) -> Path:
    """Locate the candidate's generated native Table page BY core_ref Resource
    identity (never by generated filename)."""
    for path in sorted((tree / "knowledge" / "tables").glob("*.md")):
        meta, _body = page_parts(path)
        profile = meta.get("ariadne_profile") or {}
        core_ref = profile.get("core_ref") or {}
        if core_ref.get("id") == resource:
            return path
    raise AssertionError(f"no generated Table page binds {resource}")


def _p1_refusal_bindings(case: str, bindings: dict) -> dict:
    """The five declared §10.1/§10.2 refusal mutations, each authored from
    the exact contract text (never from product message guesses)."""
    import copy

    mutated = copy.deepcopy(bindings)
    if case == "unknown-check":
        mutated["bindings"][1]["enforcement"]["check"] = "planner.sql_predicate"
    elif case == "check-not-executed":
        # §10.2: adhoc.static_io_authority executes only for define_metric —
        # a revision-2 admission can never serve it for query_metrics.
        mutated["bindings"][1]["enforcement"]["check"] = "adhoc.static_io_authority"
    elif case == "missing-classification":
        # the metric subject's closure policy entity:cancelled-orders keeps
        # no matching record (the computation-subject record does not
        # classify the metric subject's closure)
        del mutated["bindings"][1]
    elif case == "invented-obligation":
        mutated["bindings"].append(
            {
                "subject": {"kind": "metric", "identity": "retail_sales::revenue"},
                "policy": {
                    "namespace": NAMESPACE,
                    "entity_id": "entity:order-label-hygiene",
                },
                "operations": ["get_metric"],
                "enforcement": None,
            }
        )
    elif case == "wrong-revision-operation":
        mutated["bindings"][0]["operations"] = ["get_metric", "query_detail"]
    else:  # pragma: no cover - the case table is closed
        raise AssertionError(case)
    return mutated


# The #83 review-fix refusal cases (parent-dispositioned F1/F2 plus the
# delta-review D2/D4): unlike the five binding mutations above, these keep
# the authored §10.1 inventory VALID and add exactly ONE producer-valid KB
# page whose defect is visible only to the Core consumer contract.
P1_PAGE_REFUSAL_CASES = frozenset(
    {
        "table-identity-contradiction",
        "computation-unknown-semantic",
        "native-source-unapproved",
        "native-source-escape",
        "native-source-unapproved-scalar",
        "native-source-escape-scalar",
        "table-core-ref-wrong-kind",
    }
)


def _p1_refusal_extra_page(
    case: str, tree: Path, tmp_path: Path, orders_resource: str, status_resource: str
) -> str | None:
    """Write the one offending review-fix page into the candidate's knowledge
    subtree. Every page is PRODUCER-VALID (the caller's inspect guard proves
    it): F1 — a table page whose core_ref and native.resource name two
    DIFFERENT approved physical tables, and a hidden computation whose
    semantic core_ref no admitted metric carries; F2 — a table page whose
    retained native provenance (a canonical resource of an unapproved
    source; a relative citation that RESOLVES to a real file outside the
    captured KB but inside tmp_path) escapes the approved-source/containment
    gates. The escape file is created here and its placement asserted, so
    the case tests CONTAINMENT, never missing-file behavior. Returns the
    authored escape citation for the refusal-token assertion, else None."""
    from ariadne.sources import table_resource

    knowledge = tree / "knowledge"
    # the negative cases never refresh, so the tables/ category does not
    # exist yet in these disposable candidates — create it before the writes
    (knowledge / "tables").mkdir(parents=True, exist_ok=True)
    if case == "table-identity-contradiction":
        (knowledge / "tables/contradictory-binding.md").write_text(
            "---\n"
            'id: "entity:contradictory-binding"\n'
            "entity_types:\n"
            "  - table\n"
            "tags:\n"
            "  - internal\n"
            'title: "Contradictory Binding"\n'
            'summary: "Table page whose two physical identities disagree."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            "sources:\n"
            '  - id: "src-contradiction"\n'
            '    title: "Synthetic catalog memo, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: table\n"
            "  core_ref:\n"
            "    kind: resource\n"
            f'    id: "{orders_resource}"\n'
            "  native:\n"
            "    type: table\n"
            '    title: "Contradictory Binding"\n'
            '    description: "Table page whose two physical identities disagree."\n'
            "    tags:\n"
            "      - internal\n"
            "    stale_after: 2027-12-31\n"
            "    sources:\n"
            '      - id: "src-contradiction"\n'
            '        title: "Synthetic catalog memo, 2026-10-22"\n'
            f'    resource: "{status_resource}"\n'
            "---\n"
            "\n"
            "# Contradictory Binding\n"
            "\n"
            "A producer-valid table page binding two different approved\n"
            "physical tables: core_ref names the orders table while the native\n"
            "resource names the status table.\n"
        )
        return None
    if case == "computation-unknown-semantic":
        (knowledge / "computations/ghost-revenue.md").write_text(
            "---\n"
            'id: "entity:ghost-revenue-computation"\n'
            "entity_types:\n"
            "  - computation\n"
            "tags:\n"
            "  - finance\n"
            'title: "Ghost Revenue Computation"\n'
            'summary: "Hidden computation naming a semantic identity no metric carries."\n'
            'lifecycle: "approved"\n'
            'visibility: "restricted"\n'
            "sources:\n"
            '  - id: "src-ghost-review"\n'
            '    title: "Ghost computation review, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: computation\n"
            "  core_ref:\n"
            "    kind: semantic\n"
            '    id: "retail_sales::ghost_revenue"\n'
            "  native:\n"
            "    type: computation\n"
            '    status: "stable"\n'
            '    title: "Ghost revenue computation"\n'
            '    description: "Names a semantic identity no admitted metric carries."\n'
            "    tags:\n"
            "      - finance\n"
            "    stale_after: 2020-01-01\n"
            "    attestation: pending\n"
            "    sources:\n"
            '      - id: "src-ghost-review"\n'
            '        title: "Ghost computation review, 2026-10-22"\n'
            "---\n"
            "\n"
            "# Ghost Revenue Computation\n"
            "\n"
            "Hidden, unreferenced computation page whose semantic core\n"
            "reference resolves to no sanctioned definition.\n"
        )
        return None
    if case == "native-source-unapproved":
        unapproved = table_resource("unapproved-source", None, "main", "orders")
        (knowledge / "tables/shadow-sourced.md").write_text(
            "---\n"
            'id: "entity:shadow-sourced"\n'
            "entity_types:\n"
            "  - table\n"
            "tags:\n"
            "  - retail\n"
            'title: "Shadow Sourced"\n'
            'summary: "Table page whose native provenance names an unapproved source."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            "sources:\n"
            '  - id: "src-shadow-catalog"\n'
            '    title: "Synthetic shadow catalog memo, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: table\n"
            "  core_ref:\n"
            "    kind: resource\n"
            f'    id: "{orders_resource}"\n'
            "  native:\n"
            "    type: table\n"
            '    title: "Shadow Sourced"\n'
            '    description: "Native provenance naming an unapproved source."\n'
            "    tags:\n"
            "      - retail\n"
            "    stale_after: 2027-12-31\n"
            "    sources:\n"
            '      - id: "src-shadow-catalog"\n'
            '        title: "Synthetic shadow catalog memo, 2026-10-22"\n'
            f'        resource: "{unapproved}"\n'
            f'    resource: "{orders_resource}"\n'
            "---\n"
            "\n"
            "# Shadow Sourced\n"
            "\n"
            "A producer-valid table page whose retained native source entry\n"
            "names a canonical resource of an unapproved source.\n"
        )
        return None
    if case == "native-source-escape":
        outside = tmp_path / "uncaptured-table-evidence.md"
        outside.write_text("Author-owned table evidence outside the captured release.\n")
        escape = Path(os.path.relpath(outside.resolve(), knowledge.resolve())).as_posix()
        assert escape.startswith("../") and "://" not in escape  # producer-relative form
        resolved = (knowledge / escape).resolve()
        assert resolved == outside.resolve() and outside.is_file()
        assert resolved.is_relative_to(tmp_path.resolve())  # really inside tmp_path
        assert not resolved.is_relative_to(knowledge.resolve())  # really outside the KB
        (knowledge / "tables/escaped-source.md").write_text(
            "---\n"
            'id: "entity:escaped-source"\n'
            "entity_types:\n"
            "  - table\n"
            "tags:\n"
            "  - retail\n"
            'title: "Escaped Source"\n'
            'summary: "Table page whose native citation escapes the captured KB."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            "sources:\n"
            '  - id: "src-escaped-evidence"\n'
            '    title: "Synthetic escaped evidence memo, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: table\n"
            "  core_ref:\n"
            "    kind: resource\n"
            f'    id: "{orders_resource}"\n'
            "  native:\n"
            "    type: table\n"
            '    title: "Escaped Source"\n'
            '    description: "Native citation escaping the captured KB subtree."\n'
            "    tags:\n"
            "      - retail\n"
            "    stale_after: 2027-12-31\n"
            "    sources:\n"
            '      - id: "src-escaped-evidence"\n'
            '        title: "Synthetic escaped evidence memo, 2026-10-22"\n'
            f'        resource: "{escape}"\n'
            f'    resource: "{orders_resource}"\n'
            "---\n"
            "\n"
            "# Escaped Source\n"
            "\n"
            "A producer-valid table page whose native source citation\n"
            "resolves to a real file outside the captured knowledge subtree.\n"
        )
        return escape
    if case == "native-source-unapproved-scalar":
        # D2 (#83 delta review): the SAME unapproved canonical provenance as
        # the structured case, authored in the producer's supported SCALAR
        # native source form — a bare identity string, not a mapping
        unapproved = table_resource("unapproved-source", None, "main", "orders")
        (knowledge / "tables/shadow-sourced-scalar.md").write_text(
            "---\n"
            'id: "entity:shadow-sourced-scalar"\n'
            "entity_types:\n"
            "  - table\n"
            "tags:\n"
            "  - retail\n"
            'title: "Shadow Sourced Scalar"\n'
            'summary: "Table page whose scalar native source names an unapproved source."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            "sources:\n"
            '  - id: "src-shadow-scalar"\n'
            '    title: "Synthetic shadow scalar memo, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: table\n"
            "  core_ref:\n"
            "    kind: resource\n"
            f'    id: "{orders_resource}"\n'
            "  native:\n"
            "    type: table\n"
            '    title: "Shadow Sourced Scalar"\n'
            '    description: "Scalar native provenance naming an unapproved source."\n'
            "    tags:\n"
            "      - retail\n"
            "    stale_after: 2027-12-31\n"
            "    sources:\n"
            f'      - "{unapproved}"\n'
            f'    resource: "{orders_resource}"\n'
            "---\n"
            "\n"
            "# Shadow Sourced Scalar\n"
            "\n"
            "A producer-valid table page whose scalar native source entry\n"
            "names a canonical resource of an unapproved source.\n"
        )
        return None
    if case == "native-source-escape-scalar":
        # D2: the containment case of the same scalar form — the citation
        # still RESOLVES to a real authored file outside the captured KB
        outside = tmp_path / "uncaptured-table-evidence.md"
        outside.write_text("Author-owned table evidence outside the captured release.\n")
        escape = Path(os.path.relpath(outside.resolve(), knowledge.resolve())).as_posix()
        assert escape.startswith("../") and "://" not in escape  # producer-relative form
        resolved = (knowledge / escape).resolve()
        assert resolved == outside.resolve() and outside.is_file()
        assert resolved.is_relative_to(tmp_path.resolve())  # really inside tmp_path
        assert not resolved.is_relative_to(knowledge.resolve())  # really outside the KB
        (knowledge / "tables/escaped-source-scalar.md").write_text(
            "---\n"
            'id: "entity:escaped-source-scalar"\n'
            "entity_types:\n"
            "  - table\n"
            "tags:\n"
            "  - retail\n"
            'title: "Escaped Source Scalar"\n'
            'summary: "Table page whose scalar native citation escapes the captured KB."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            "sources:\n"
            '  - id: "src-escaped-scalar"\n'
            '    title: "Synthetic escaped scalar memo, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: table\n"
            "  core_ref:\n"
            "    kind: resource\n"
            f'    id: "{orders_resource}"\n'
            "  native:\n"
            "    type: table\n"
            '    title: "Escaped Source Scalar"\n'
            '    description: "Scalar native citation escaping the captured KB subtree."\n'
            "    tags:\n"
            "      - retail\n"
            "    stale_after: 2027-12-31\n"
            "    sources:\n"
            f'      - "{escape}"\n'
            f'    resource: "{orders_resource}"\n'
            "---\n"
            "\n"
            "# Escaped Source Scalar\n"
            "\n"
            "A producer-valid table page whose scalar native source citation\n"
            "resolves to a real file outside the captured knowledge subtree.\n"
        )
        return escape
    if case == "table-core-ref-wrong-kind":
        # D4 (#83 delta review): an otherwise correct Table profile whose
        # core_ref carries its canonical table URI but the WRONG typed
        # discriminator (kind: semantic) with an agreeing native.resource —
        # the owning validator must reject the authored discriminator before
        # ID resolution, never relabel it, with no other identity defect to
        # mask the type error
        (knowledge / "tables/semantic-typed-table.md").write_text(
            "---\n"
            'id: "entity:semantic-typed-table"\n'
            "entity_types:\n"
            "  - table\n"
            "tags:\n"
            "  - retail\n"
            'title: "Semantic Typed Table"\n'
            'summary: "Table page whose core_ref uses the wrong typed discriminator."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            "sources:\n"
            '  - id: "src-typed-table"\n'
            '    title: "Synthetic typed-table memo, 2026-10-22"\n'
            "ariadne_profile:\n"
            "  version: 1\n"
            "  kind: table\n"
            "  core_ref:\n"
            "    kind: semantic\n"
            f'    id: "{orders_resource}"\n'
            "  native:\n"
            "    type: table\n"
            '    title: "Semantic Typed Table"\n'
            '    description: "Table identity typed with the wrong core_ref discriminator."\n'
            "    tags:\n"
            "      - retail\n"
            "    stale_after: 2027-12-31\n"
            "    sources:\n"
            '      - id: "src-typed-table"\n'
            '        title: "Synthetic typed-table memo, 2026-10-22"\n'
            f'    resource: "{orders_resource}"\n'
            "---\n"
            "\n"
            "# Semantic Typed Table\n"
            "\n"
            "A producer-valid table page whose physical core reference is\n"
            "authored with the semantic discriminator.\n"
        )
        return None
    raise AssertionError(case)  # pragma: no cover - the case table is closed


def _p1_bound_table_page(resource: str, source_binding: str) -> str:
    """A producer-valid native Table page with complete measured observations
    (hand-counted over the authored orders rows: 3 rows, id/amount distinct 3,
    status distinct 2, no nulls) stamped with the given effective endpoint
    binding — a fixture INPUT for the endpoint-provenance gate; the authored
    stamp asserts no measurement or admission authority of its own."""
    return (
        "---\n"
        'id: "entity:bound-observations"\n'
        "entity_types:\n"
        "  - table\n"
        "tags:\n"
        "  - retail\n"
        'title: "Bound Observations"\n'
        'summary: "Native table observations stamped with an effective binding."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        '  - id: "src-bound-catalog"\n'
        '    title: "Synthetic bound catalog memo, 2026-10-22"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: table\n"
        "  core_ref:\n"
        "    kind: resource\n"
        f'    id: "{resource}"\n'
        "  native:\n"
        "    type: table\n"
        '    title: "Bound Observations"\n'
        '    description: "Native table observations stamped with an effective binding."\n'
        "    tags:\n"
        "      - retail\n"
        "    stale_after: 2027-06-30\n"
        "    sources:\n"
        '      - id: "src-bound-catalog"\n'
        '        title: "Synthetic bound catalog memo, 2026-10-22"\n'
        f'    resource: "{resource}"\n'
        "    ariadne:\n"
        "      schema:\n"
        "        - column: id\n"
        "          type: INTEGER\n"
        "          nullable: true\n"
        "          default: null\n"
        "          comment: unknown\n"
        "        - column: amount\n"
        "          type: DOUBLE\n"
        "          nullable: true\n"
        "          default: null\n"
        "          comment: unknown\n"
        "        - column: status\n"
        "          type: VARCHAR\n"
        "          nullable: true\n"
        "          default: null\n"
        "          comment: unknown\n"
        "      observations:\n"
        '        observed_at: "2026-10-22T12:00:00+00:00"\n'
        "        scope: full\n"
        "        row_count: 3\n"
        "        candidate_keys: [id]\n"
        "        columns:\n"
        "          id: {null_count: 0, distinct_count: 3}\n"
        "          amount: {null_count: 0, distinct_count: 3}\n"
        "          status: {null_count: 0, distinct_count: 2}\n"
        f'        citation: "{resource}"\n'
        f'        source_binding: "{source_binding}"\n'
        "---\n"
        "\n"
        "# Bound Observations\n"
        "\n"
        "Fixture page carrying measured observations under an explicit\n"
        "effective endpoint binding stamp.\n"
    )


# The one focused case family: the real positive admission journey plus
# exactly the five declared §10.1/§10.2 binding refusal cases and the seven
# parent-dispositioned page refusal cases (#83 fix F1/F2 + delta D2/D4) as
# finite parameters (plan0032 shared verification, P1 assignment).
P1_CASES = [
    pytest.param("admission", id="admission"),
    pytest.param("unknown-check", id="refusal-unknown-check"),
    pytest.param("check-not-executed", id="refusal-check-not-executed"),
    pytest.param("missing-classification", id="refusal-missing-classification"),
    pytest.param("invented-obligation", id="refusal-invented-obligation"),
    pytest.param("wrong-revision-operation", id="refusal-wrong-revision-operation"),
    pytest.param("table-identity-contradiction", id="refusal-table-identity-contradiction"),
    pytest.param("computation-unknown-semantic", id="refusal-computation-unknown-semantic"),
    pytest.param("native-source-unapproved", id="refusal-native-source-unapproved"),
    pytest.param("native-source-escape", id="refusal-native-source-escape"),
    pytest.param("native-source-unapproved-scalar", id="refusal-native-source-unapproved-scalar"),
    pytest.param("native-source-escape-scalar", id="refusal-native-source-escape-scalar"),
    pytest.param("table-core-ref-wrong-kind", id="refusal-table-core-ref-wrong-kind"),
]
# Each refusal must name its §10 identifier: the unknown check id, the known
# check id that never executes for the bound operation (with the operation),
# the unclassified closure policy, the invented policy, the revision-2
# operation id.
P1_REFUSAL_TOKENS = {
    "unknown-check": ("planner.sql_predicate",),
    "check-not-executed": ("adhoc.static_io_authority", "query_metrics"),
    "missing-classification": ("entity:cancelled-orders",),
    "invented-obligation": ("entity:order-label-hygiene",),
    "wrong-revision-operation": ("query_detail",),
}


@pytest.mark.parametrize("case", P1_CASES)
def test_integrated_technical_profiles_preserve_evidence_and_curated_content(
    tmp_path, monkeypatch, case
):
    """P1 (#83, spec0032 §§5–6, §10.1–§10.3): one revision-2 admission over a
    real approved synthetic source and producer-valid native KB profiles.
    An explicit refresh_schema regenerates the core-owned schema facts of the
    authored assets as revision-checked candidate edits into knowledge/ (no
    maintained context_layer mirror, no Core KB YAML parse); curated text and
    authored evidence flags never become authority; the admission captures
    support_revision 2 with the authored binding inventory; the three
    revision-3 query operations keep refusing through the existing documented
    gate while a legacy revision-1 admission under the SAME candidate build
    keeps its own frozen capability table; each declared closed-validation
    refusal names its §10 identifier through the established public
    validation seam; and the parent-dispositioned review-fix refusals name
    their offending physical/semantic/provenance identities from producer-
    valid pages only."""
    import hashlib
    import json

    import duckdb  # pyright: ignore[reportMissingImports] — qualified test env is external
    from ariadne.planner import PlannerError
    from ariadne.sources import collection_resource, parse_resource, table_resource
    from lumio_wiki.ariadne_context import (  # pyright: ignore[reportMissingImports]
        inspect_ariadne_candidate,
    )

    orders_resource = table_resource(**P1_ORDERS_ASSET)
    status_resource = table_resource(**P1_STATUS_ASSET)
    collection = collection_resource("orders", "orders", "main")
    authored = _p1_bindings(orders_resource, status_resource)

    if case != "admission":
        # independent disposable candidates: one project/proposal and ONE
        # validation per refusal case (the native round guard stays intact)
        bindings = (
            authored if case in P1_PAGE_REFUSAL_CASES else _p1_refusal_bindings(case, authored)
        )
        project = _p1_project(tmp_path, bindings)
        api = AuthoringProject(project)
        started = api.start_proposal()
        approved(api, project, started)
        revision = contracted(
            api,
            started,
            contract=ORDERS_CONTRACT.replace("region", "status").replace(
                "mustBe: 60", "mustBe: 175"
            ),
            bindings=ORDERS_BINDINGS.replace("region", "status").replace(
                "model: orders", "model: retail_sales"
            ),
        )
        tree = worktree_of(project, started["proposal"])
        revision = _p1_kb_candidate(project, api, started, revision)
        escape_citation = None
        if case in P1_PAGE_REFUSAL_CASES:
            # the authored §10.1 inventory stays VALID: the refusal comes from
            # exactly one producer-valid page the Core consumer contract refuses
            escape_citation = _p1_refusal_extra_page(
                case, tree, tmp_path, orders_resource, status_resource
            )
            revision = reconcile_knowledge(project, started["proposal"], revision)
        assert (
            inspect_ariadne_candidate(
                str(tree / "knowledge"),
                revision,
                namespace=NAMESPACE,
            ).diagnostics
            == ()
        ), "the refusal must come from the consumer binding contract, not producer malformation"
        refused = api.validate_proposal(started["proposal"], revision)
        assert refused["ok"] is False, case
        diagnostics = "; ".join(refused["errors"])
        if case in P1_PAGE_REFUSAL_CASES:
            # frozen oracles (parent disposition): the page path plus BOTH
            # authored physical identities (F1), the qualified semantic id,
            # the unapproved source name, and the authored escape citation
            tokens = {
                "table-identity-contradiction": (
                    "knowledge/tables/contradictory-binding.md",
                    orders_resource,
                    status_resource,
                ),
                "computation-unknown-semantic": (
                    "knowledge/computations/ghost-revenue.md",
                    "retail_sales::ghost_revenue",
                ),
                "native-source-unapproved": (
                    "knowledge/tables/shadow-sourced.md",
                    "unapproved-source",
                ),
                "native-source-escape": (
                    "knowledge/tables/escaped-source.md",
                    escape_citation,
                ),
                "native-source-unapproved-scalar": (
                    "knowledge/tables/shadow-sourced-scalar.md",
                    "unapproved-source",
                ),
                "native-source-escape-scalar": (
                    "knowledge/tables/escaped-source-scalar.md",
                    escape_citation,
                ),
                "table-core-ref-wrong-kind": (
                    "knowledge/tables/semantic-typed-table.md",
                    "semantic",
                    orders_resource,
                ),
            }[case]
        else:
            tokens = P1_REFUSAL_TOKENS[case]
        for token in tokens:
            assert token in diagnostics, (case, token, diagnostics)
        assert not (project / ".ariadne" / "current.json").exists()
        return

    # ---------------- the one real positive journey (revision 2)
    # D3 (#83 delta review): the admission model set additionally carries the
    # UNUSED later-loaded zz_unused_orders alias over the SAME physical
    # orders source — unrelated legitimate catalog reuse must never replace
    # a consumed subject's actual lineage, so every original oracle below
    # (traversal 0.0/150.0, direct/derived-only refusals, serving) stays the
    # unchanged pin while the alias is requested nowhere
    project = _p1_project(tmp_path, authored, unused_alias=True)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    tree = worktree_of(project, started["proposal"])
    context_mirror = tree / "context_layer" / "tables" / "orders.md"
    mirror_before = context_mirror.read_bytes()

    revision = _p1_kb_candidate(project, api, started, revision, unused_alias=True)

    # explicit operator-authorized physical schema refresh (the existing
    # public signature) over the real approved catalog: the two authored
    # assets regenerate as revision-checked candidate edits
    refreshed = api.refresh_schema(
        started["proposal"], revision, [P1_ORDERS_ASSET, P1_STATUS_ASSET]
    )
    assert refreshed["revision"] != revision
    revision = refreshed["revision"]
    generated = {(page["resource"], page["kind"]) for page in refreshed["pages"]}
    assert generated == {
        (orders_resource, "table"),
        (status_resource, "table"),
        (collection, "dataset"),
    }
    for resource, kind in generated:
        assert parse_resource(resource)[0] == ("collection" if kind == "dataset" else kind)
    # the native pages live in knowledge/, bound by exact core_ref identity,
    # and carry the authored DDL facts and hand-counted observations
    schema_oracle = {
        orders_resource: (P1_ORDERS_COLUMNS, P1_ORDERS_COUNTS),
        status_resource: (P1_STATUS_COLUMNS, P1_STATUS_COUNTS),
    }
    table_pages = {}
    for resource in (orders_resource, status_resource):
        page = _p1_generated_table_page(tree, resource)
        table_pages[resource] = page
        meta, body = page_parts(page)
        profile = meta["ariadne_profile"]
        assert profile["kind"] == "table"
        assert profile["core_ref"] == {"kind": "resource", "id": resource}
        native = profile["native"]
        columns, counts = schema_oracle[resource]
        assert [(row["column"], row["type"]) for row in native["ariadne"]["schema"]] == columns
        observations = native["ariadne"]["observations"]
        assert observations["row_count"] == counts["row_count"]
        assert {
            name: (stats["null_count"], stats["distinct_count"])
            for name, stats in observations["columns"].items()
        } == {name: counts[name] for name, _type in columns}
        assert "CURATED-MARKER" not in body  # generated, not yet curated
    dataset_pages = [
        path
        for path in sorted((tree / "knowledge" / "datasets").glob("*.md"))
        if (page_parts(path)[0].get("ariadne_profile") or {}).get("core_ref", {}).get("id")
        == collection
    ]
    assert len(dataset_pages) == 1
    dataset_native = page_parts(dataset_pages[0])[0]["ariadne_profile"]["native"]
    assert sorted(dataset_native["ariadne"]["tables"]) == sorted([orders_resource, status_resource])
    # no maintained context_layer mirror: the pre-existing OKF page bytes are
    # untouched and refresh added no context_layer page
    assert context_mirror.read_bytes() == mirror_before
    assert not (tree / "context_layer" / "datasets").exists()

    # the handwritten curated marker survives a real second inspection
    # (authored summary/meaning preservation, §6) — and the #83 review-fix
    # legs ride the SAME second refresh: F4 (spec0024 §3) authors the
    # selected-value declaration and F5 (spec0010 §4) changes the approved
    # source's DECLARED DDL facts (nullability/default) without any
    # name/type change, so the refreshed page must carry real measured value
    # evidence and the INSPECTED declared facts, never stale prior rows
    orders_page = table_pages[orders_resource]
    meta, body = page_parts(orders_page)
    meta["ariadne_profile"]["native"]["description"] = (
        "One row per retail order; " + P1_CURATED_MARKER + "."
    )
    meta["ariadne_profile"]["native"]["observed_value_columns"] = {"status": "VARCHAR"}
    write_page(orders_page, meta, body + f"\n{P1_CURATED_MARKER}\n")
    connection = duckdb.connect(str(project / "data" / "orders.duckdb"))
    # test-fixture DDL: declared-constraint change, no identity/type change
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    connection.execute("ALTER TABLE main.orders ALTER COLUMN status SET NOT NULL")
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    connection.execute("ALTER TABLE main.orders ALTER COLUMN amount SET DEFAULT 7")
    connection.close()
    revision = reconcile_knowledge(project, started["proposal"], revision)
    retained = api.refresh_schema(started["proposal"], revision, [P1_ORDERS_ASSET, P1_STATUS_ASSET])
    revision = retained["revision"]
    meta, body = page_parts(_p1_generated_table_page(tree, orders_resource))
    native = meta["ariadne_profile"]["native"]
    assert P1_CURATED_MARKER in native["description"]
    assert P1_CURATED_MARKER in body
    schema_rows = {row["column"]: row for row in native["ariadne"]["schema"]}
    assert [
        (row["column"], row["type"]) for row in native["ariadne"]["schema"]
    ] == P1_ORDERS_COLUMNS
    # F5 oracle from the authored DDL: status is NOT NULL and keeps no
    # default, amount carries DEFAULT 7, untouched id stays nullable with no
    # default, and no comment source exists (unknown stays unknown)
    assert schema_rows["status"]["nullable"] is False
    assert schema_rows["status"]["default"] is None
    assert schema_rows["amount"]["nullable"] is True
    assert schema_rows["amount"]["default"] == "7"
    assert schema_rows["id"]["nullable"] is True
    assert schema_rows["id"]["default"] is None
    assert all(row["comment"] == "unknown" for row in schema_rows.values())
    # F4 oracle from the authored rows (completed 2, cancelled 1): the
    # authored selection is fulfilled by the REAL measured profile in the
    # contract's count-descending canonical order, and the declaration
    # itself survives as the authored native selection
    assert native["observed_value_columns"] == {"status": "VARCHAR"}
    assert native["ariadne"]["observations"]["value_evidence"]["status"] == {
        "state": "observed",
        "top_values": [
            {"value": "completed", "count": 2},
            {"value": "cancelled", "count": 1},
        ],
    }

    # authored evidence flags are honest disclosure, never authority (§5): a
    # plausible forgery claims the executed check and a verification stamp
    meta, body = page_parts(orders_page)
    meta["ariadne_profile"]["native"]["generated"] = {
        "check": "graph.relationship_audit",
        "executed": True,
    }
    meta["ariadne_profile"]["native"]["verified"] = [{"by": "ariadne:relationship_audit"}]
    meta["ariadne_profile"]["native"]["stale_after"] = "2027-12-31"
    write_page(orders_page, meta, body)
    revision = reconcile_knowledge(project, started["proposal"], revision)

    # a hidden, unreferenced invalid technical profile participates in
    # whole-KB validation (§3): restricted visibility changes nothing
    unapproved = table_resource("unapproved-source", None, "main", "orders")
    (tree / "knowledge/tables").mkdir(parents=True, exist_ok=True)
    (tree / "knowledge/tables/internal-orders.md").write_text(_p1_hidden_table_page(unapproved))
    revision = reconcile_knowledge(project, started["proposal"], revision)
    hidden_refused = api.validate_proposal(started["proposal"], revision)
    assert hidden_refused["ok"] is False
    hidden_diagnostic = "; ".join(hidden_refused["errors"])
    assert "knowledge/tables/internal-orders.md" in hidden_diagnostic
    assert "unapproved-source" in hidden_diagnostic
    assert not (project / ".ariadne" / "current.json").exists()  # validation ≠ activation
    # the finalizing validation advanced the candidate even on refusal —
    # every later step continues from the ACTUAL final Content Commit
    revision = hidden_refused["revision"]

    # the ordinary repair: remove the invalid page, then the final validation
    (tree / "knowledge/tables/internal-orders.md").unlink()
    revision = reconcile_knowledge(project, started["proposal"], revision)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    revision = validated["revision"]  # the successful finalization's actual commit
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == revision
    knowledge_paths = {item["resource"] for item in review["files"]}
    assert {"context_integration.yaml", "knowledge/computations/revenue.md"} <= knowledge_paths
    assert any(path.startswith("knowledge/tables/") for path in knowledge_paths)
    assert any(path.startswith("knowledge/datasets/") for path in knowledge_paths)

    # final Content Commit -> overall confirmation -> descriptor-last native
    # local publication
    destination = tmp_path / "published"
    activate(project, review, preview(project, review, destination))
    manifest = json.loads((project / ".ariadne" / "current.json").read_text())["bound_release"]
    assert manifest["support_revision"] == 2
    assert manifest["policy_bindings"] == authored
    assert manifest["selector"] == {
        "version": 1,
        "mode": "integrated",
        "subtree": "knowledge",
        "namespace": NAMESPACE,
        "profile": "ariadne-context/1",
        "support_revision": 2,
        "policy_bindings": authored,
    }
    assert sorted(manifest["support"]["profiles"]) == sorted(P1_REV2_PROFILES)
    assert sorted(manifest["support"]["operations"]) == sorted(P1_NINE_OPERATIONS)
    assert not set(P1_QUERY_OPS) & set(manifest["support"]["operations"])
    assert set(P1_QUERY_OPS) <= set(manifest["support"]["unsupported"])

    # legacy and expanded admissions under the SAME candidate build keep
    # their respective frozen capability tables (§10.3: a legacy manifest is
    # revision 1 without rewriting its bytes; no automatic upgrade)
    from integration.tests.lumio_metric_mvp import ready

    legacy_project, _legacy_api, legacy_review = ready(tmp_path / "legacy")
    activate(
        legacy_project, legacy_review, preview(legacy_project, legacy_review, tmp_path / "legacy-p")
    )
    legacy_manifest = json.loads((legacy_project / ".ariadne" / "current.json").read_text())[
        "bound_release"
    ]
    assert "support_revision" not in legacy_manifest
    assert "policy_bindings" not in legacy_manifest
    assert sorted(legacy_manifest["support"]["profiles"]) == sorted(P1_REV1_PROFILES)
    assert legacy_manifest["execution"] == manifest["execution"]
    assert sorted(legacy_manifest["support"]["operations"]) == sorted(
        manifest["support"]["operations"]
    )

    runtime = QueryRuntime.open_project(project)
    try:
        # the governed request that actually traverses the proven lookup: the
        # executable binding is attested by the REAL plan audit (§10.2), with
        # the hand-worked join oracle — never a duplicated numeric replay;
        # D3: this exact oracle also pins that the unused same-source alias
        # cannot replace the consumed revenue lineage
        traversed = asyncio.run(
            runtime.query_metrics({"metrics": ["revenue"], "dimensions": ["status_label"]})
        )
        assert sorted(traversed["rows"], key=lambda row: row["status_label"]) == [
            {"status_label": "Cancelled order", "revenue": 0.0},
            {"status_label": "Completed order", "revenue": 150.0},
        ]
        assert traversed["governed"] is True
        assert traversed["plan"]["relationship_audit"] == "passed"
        assert any(
            audit["name"] == "relationship:order_status_lookup" and audit["outcome"] == "passed"
            for audit in traversed["plan"]["audits"]
        )

        # F3 (#83 review fix, spec0032 §10.2): a plain single-fact derived
        # metric cannot compose with a lookup traversal — the existing
        # planner contract (the issue #29 post-aggregate design) refuses the
        # exact request with the STABLE PlannerError code before any result
        # SQL; only window-declared post-aggregate metrics take that shape.
        # The derived metric still consumes retail_sales::revenue, so the
        # binding obligation itself is exercised by the derived-only leg below
        with pytest.raises(PlannerError) as caught:
            asyncio.run(
                runtime.query_metrics(
                    {"metrics": ["revenue_plus_one"], "dimensions": ["status_label"]}
                )
            )
        assert caught.value.code == "derived_lookup_unsupported"

        # a request no relationship participates in reports the audit not-run:
        # the authored generated/verified flags cannot attest it, so the
        # operation refuses instead of labeling the narrative enforced (§10.2)
        with pytest.raises(PlannerError, match="graph.relationship_audit"):
            asyncio.run(runtime.query_metrics({"metrics": ["revenue"]}))

        # F3: the derived-only request carries no executable binding of its
        # own, but it CONSUMES retail_sales::revenue — the obligation must be
        # attested for the consumed dependency even though the requested
        # name alone appears nowhere in the binding inventory, refusing
        # before any result SQL while the audit is not-run
        with pytest.raises(PlannerError, match="graph.relationship_audit"):
            asyncio.run(runtime.query_metrics({"metrics": ["revenue_plus_one"]}))

        # get_metric keeps its explanatory contract on this admission: the
        # executable binding (query_metrics-only) never gates it, and the
        # Computation page stays honestly attestation: pending
        explained = asyncio.run(runtime.get_metric("revenue"))
        assert explained["rows"] == [{"revenue": 150.0}]
        assert explained["governed"] is True
        assert explained["context"]["attestation"] == "pending"
        assert "not independently value-attested" in explained["context"]["governed_note"]
        assert CANCELLATION in explained["context"]["policies"]
        assert all(
            citation["published_version"] == revision
            for citation in explained["context"]["citations"]
        )

        # the three revision-3 operations still refuse through the existing
        # documented gate, before any execution
        for name, request in (
            ("query_detail", {"dataset": "orders", "fields": ["id"]}),
            (
                "query_records",
                {
                    "dataset": "orders.main.orders",
                    "fields": ["id"],
                    "order": [{"field": "id", "direction": "asc"}],
                },
            ),
            (
                "define_metric",
                {
                    "name": "test_value",
                    "source": "orders.main.orders",
                    "expression": "SUM(amount)",
                    "description": "Temporary value",
                },
            ),
        ):
            with pytest.raises(ValueError, match=f"unsupported integrated MVP operation: {name}"):
                asyncio.run(getattr(runtime, name)(request))
    finally:
        runtime.con.close()

    # pinned public SDK/discovery reads are source-free (guards only AFTER
    # the legitimate inspection/validation/publication above) and cause no
    # new measurements or writes (§6)
    from ariadne.discovery import DiscoveryRuntime
    from tests.test_discovery import _source_free_guards

    from integration.tests.lumio_metric_mvp import current_bytes

    descriptor_before = current_bytes(project)
    knowledge_before = {
        path.relative_to(tree).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((tree / "knowledge").rglob("*"))
        if path.is_file()
    }
    published_before = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        session = DiscoveryRuntime.open_project(project)
        listed = asyncio.run(session.list_context_pages())
        by_kind = {}
        for entry in listed:
            by_kind.setdefault(entry["kind"], []).append(entry)
        assert set(by_kind) >= {"dataset", "table", "computation", "metric", "policy"}
        technical = {
            entry["path"]: entry
            for entry in listed
            if entry["kind"] in {"dataset", "table", "computation"}
        }
        assert len(technical) >= 4  # two tables, one dataset, one computation
        for entry in technical.values():
            assert entry["bound_release"] == manifest["digest"]
            assert entry["published_version"] == revision
            assert entry["draft"] is False
            assert entry["namespace"] == NAMESPACE
            assert "content" not in entry

        # exact KB content, citations and native advisories survive serving
        # (served paths are KB-relative — no knowledge/ prefix, per the SDK)
        orders_rel = orders_page.relative_to(tree / "knowledge").as_posix()
        served = asyncio.run(session.read_context_page(orders_rel))
        assert served["content"] == orders_page.read_text()
        assert served["citation"] == (f"{NAMESPACE} {served['entity_id']} v{revision} {orders_rel}")
        assert served["context_signals"]["warnings"] == []  # authored fresh stale_after
        curated = asyncio.run(session.read_context_page("computations/revenue.md"))
        assert curated["content"] == _p1_computation_page()  # exact curated body preserved
        assert curated["context_signals"]["warnings"] != []  # authored advisory staleness

        report = asyncio.run(session.discover("revenue"))
        assert report["bound_release"] == manifest["digest"]
        assert set(P1_QUERY_OPS) <= set(report["support"]["unsupported"])
        assert not set(P1_QUERY_OPS) & set(report["support"]["operations"])
        assert set(P1_NINE_OPERATIONS) == set(report["support"]["operations"])

    # serving wrote nothing: descriptor, candidate knowledge and the native
    # publication are byte-identical after the guarded reads
    assert current_bytes(project) == descriptor_before
    assert {
        path.relative_to(tree).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((tree / "knowledge").rglob("*"))
        if path.is_file()
    } == knowledge_before
    assert (
        sorted(
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        )
        == published_before
    )


@pytest.mark.parametrize("category", ["tables", "references"], ids=["tables", "references"])
def test_native_table_endpoint_binding_scopes_measured_observations(tmp_path, category):
    """F2 (#83 review fix, spec 0025 §4 through spec0032 §§5–6): a KB Table
    page's measured observations carry their effective endpoint provenance;
    the candidate refuses while those observations stay bound to a DIFFERENT
    effective storage identity, and stays valid under the identical one. The
    exercised comparison/enumeration is the real validate caller's own gate
    (``_stale_schema_binding_errors``, invoked by ``validate_proposal`` with
    the CURRENT effective approval digest); the authored A/B stamps are
    fixture inputs asserting no measurement or admission authority of their
    own — a missing optional stamp proves nothing and is not tested here.
    D1 (#83 delta review): the same producer-valid Table profile is admitted
    from EACH declared KB category (tables and references) — the native kind
    is an envelope field, so the page's directory never waives A/B
    invalidation."""
    from ariadne.authoring import _stale_schema_binding_errors
    from ariadne.sources import table_resource
    from lumio_wiki.ariadne_context import (  # pyright: ignore[reportMissingImports]
        inspect_ariadne_candidate,
    )

    orders_resource = table_resource(**P1_ORDERS_ASSET)
    status_resource = table_resource(**P1_STATUS_ASSET)
    binding_kept = "a" * 64
    binding_switched = "b" * 64
    project = _p1_project(tmp_path, _p1_bindings(orders_resource, status_resource))
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    tree = worktree_of(project, started["proposal"])
    revision = _p1_kb_candidate(project, api, started, revision)
    # no refresh runs here either: create the declared category directory
    # before the write (D1: the category placement is an authored input)
    category_dir = tree / "knowledge" / category
    category_dir.mkdir(parents=True, exist_ok=True)
    (category_dir / "bound-observations.md").write_text(
        _p1_bound_table_page(orders_resource, binding_kept)
    )
    revision = reconcile_knowledge(project, started["proposal"], revision)
    assert (
        inspect_ariadne_candidate(
            str(tree / "knowledge"),
            revision,
            namespace=NAMESPACE,
        ).diagnostics
        == ()
    ), "the fixture page is producer-valid; only the Core endpoint gate refuses"
    # identical binding: the stamped observations stay valid at this seam
    assert _stale_schema_binding_errors(tree, binding_kept) == []
    # switched endpoint: the same measured observations are stale provenance
    stale = _stale_schema_binding_errors(tree, binding_switched)
    assert stale and any(f"knowledge/{category}/bound-observations.md" in error for error in stale)
    assert not (project / ".ariadne" / "current.json").exists()  # validation ≠ activation


def test_selector_file_version_requires_exact_integer():
    """F6 (#83 review fix, spec0032 §10.1; spec0029 §2): the closed authored
    selector's file ``version`` is the EXACT integer 1 — the refactor's
    equality-only check newly admitted ``version: true`` and ``version: 1.0``
    (both compare equal to 1), a concrete relaxation of the closed admission
    carrier including legacy revision-1 inputs. Independently authored
    closed carrier inputs; the original five-key contract is unchanged."""
    from ariadne.lumio_context import validated_selector

    def carrier(version):
        return {
            "version": version,
            "mode": "integrated",
            "subtree": "knowledge",
            "namespace": NAMESPACE,
            "profile": "ariadne-context/1",
        }

    # the exact integer keeps the original five-key contract
    assert validated_selector(carrier(1)) == carrier(1)
    for malformed in (True, 1.0):
        with pytest.raises(ValueError):
            validated_selector(carrier(malformed))


# ------------------ Q1 integrated query operations (spec0032 §§2–4, §10.3–§10.5)

# The planned future nodes of issue #84 (plan0032 Q1 assignment). The
# product currently implements support revisions 1–2 and refuses the three
# query operations, so these tests encode the APPROVED spec0032 contracts
# over the real admission lifecycle — every expected value below is a
# hand-worked oracle over the authored inputs (orders 100 + 50 completed,
# 25 cancelled; curated status labels), never implementation output.

# The curated marker appended to the orders Table page for the shared A/B
# release-B leg: authored input, visible in the published page bytes only
# through a complete new human admission.
Q1_RELEASE_B_MARKER = "RELEASE-B curated orders wording."


def _q1_selector_text(bindings: dict) -> str:
    """The revision-3 selector (spec0032 §10.3): the five existing keys plus
    the two §10.1 opt-in keys, now declaring the query-expanded revision."""
    import yaml

    return (
        "version: 1\n"
        "mode: integrated\n"
        "subtree: knowledge\n"
        f"namespace: {NAMESPACE}\n"
        "profile: ariadne-context/1\n"
        + yaml.safe_dump({"support_revision": 3, "policy_bindings": bindings}, sort_keys=False)
    )


def _q1_bindings(orders_resource: str, status_resource: str) -> dict:
    """The authored revision-3 binding inventory: the accepted P1 bindings
    unchanged (the metric closure's Return Policy explanatory for the
    governed operations, the sanctioned Cancelled Orders exclusion executable
    for query_metrics through the one check that executes there, the
    Computation closure explanatory) PLUS exactly one §4 source-level
    association: the orders Table page's authored typed closure classified
    EXPLANATORY for query_records. That binding is the scoped-policy input —
    the cancellation Policy stays applicable to the record operation only as
    explicit explanatory prose, never as an executable filter (no §10.2
    check executes for query_records), while the calculation keeps its own
    executable query_metrics obligation. Identities come from the authored
    constants, never implementation output."""
    import copy

    inventory = copy.deepcopy(_p1_bindings(orders_resource, status_resource))
    inventory["bindings"].append(
        {
            "subject": {"kind": "table", "identity": orders_resource},
            "policy": {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"},
            "operations": ["query_records"],
            "enforcement": None,
        }
    )
    return inventory


def _q1_status_closure_bindings(bindings: dict, status_resource: str) -> dict:
    """The final-review F2 fixture input: the status Table subject's typed
    closure classified for define_metric by an EXECUTABLE binding naming the
    one catalog check that executes there (§10.2 — check adhoc.grain_preserving,
    definition == the subject's own canonical identity, dependencies == the
    table subject's own static inventory). Every identity comes from the
    authored constants; producer-valid and fully admitted before any query."""
    import copy

    extended = copy.deepcopy(bindings)
    extended["bindings"].append(
        {
            "subject": {"kind": "table", "identity": status_resource},
            "policy": {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"},
            "operations": ["define_metric"],
            "enforcement": {
                "check": "adhoc.grain_preserving",
                "definition": status_resource,
                "dependencies": [status_resource],
            },
        }
    )
    return extended


def _q1_release(root: Path, *, status_context: bool = True, status_closure: bool = False):
    """The shared revision-3 release: the real P1 baseline project and KB
    candidate, the real refresh inspection of the consumed physical tables,
    one authored table-closure association (§4's explicit source-level
    applicability) and the real validation → review → preview → admission
    lifecycle — no fake evidence, admission or Context mocks. With
    ``status_context=False`` the order_status Table page is never generated:
    the admission itself stays valid (Context coverage is per-request, §3)
    so a leg can prove the missing nested/lookup Context refusal. With
    ``status_closure=True`` (requires the default full ``status_context``)
    the status Table page additionally gains its authored typed closure and
    the selector carries the F2 executable define_metric binding over the
    status resource — both authored BEFORE the native validate/review/admit,
    producer-valid, and admitted for real; the default configuration is
    byte-for-byte the original three tests' and the S3 adapter's input."""
    from ariadne.sources import table_resource

    orders_resource = table_resource(**P1_ORDERS_ASSET)
    status_resource = table_resource(**P1_STATUS_ASSET)
    bindings = _q1_bindings(orders_resource, status_resource)
    if status_closure:
        bindings = _q1_status_closure_bindings(bindings, status_resource)
    project = _p1_project(root, bindings)
    (project / "context_integration.yaml").write_text(_q1_selector_text(bindings))
    run_git(project, "add", "--", "context_integration.yaml")
    run_git(project, "commit", "-q", "-m", "human: revision-3 query-expanded selector")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    revision = _p1_kb_candidate(project, api, started, revision)
    assets = [P1_ORDERS_ASSET, P1_STATUS_ASSET] if status_context else [P1_ORDERS_ASSET]
    revision = api.refresh_schema(started["proposal"], revision, assets)["revision"]
    # the orders Table page gains the authored typed closure so the table
    # binding classifies a REAL association (§10.1: a binding naming a policy
    # outside the subject's closure is an invented obligation)
    tree = worktree_of(project, started["proposal"])
    orders_page = _p1_generated_table_page(tree, orders_resource)
    meta, body = page_parts(orders_page)
    meta["ariadne_profile"]["required_policies"] = [
        {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
    ]
    write_page(orders_page, meta, body)
    if status_closure:
        # the F2 fixture's typed status closure: the executable define_metric
        # binding above classifies a REAL authored association
        status_page = _p1_generated_table_page(tree, status_resource)
        meta, body = page_parts(status_page)
        meta["ariadne_profile"]["required_policies"] = [
            {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
        ]
        write_page(status_page, meta, body)
    revision = reconcile_knowledge(project, started["proposal"], revision)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    activate(project, review, preview(project, review, root / "published"))
    return project, review


def _q1_assert_input_context(context: dict, digest_value: str, version: str) -> None:
    """The shared §10.4 envelope oracle: the additive exact schema — bound
    release digest, immutable Published Version, canonical resources, the
    applicable-Policy inventory, native context signals and evidence caveats —
    with no private operational data and no parallel page schema."""
    assert set(context) == {
        "bound_release",
        "published_version",
        "resources",
        "policies",
        "context_signals",
        "evidence_caveats",
    }
    assert context["bound_release"] == digest_value
    assert context["published_version"] == version
    assert set(context["context_signals"]) == {"pages", "warnings"}
    assert isinstance(context["context_signals"]["pages"], list)
    assert isinstance(context["context_signals"]["warnings"], list)
    assert isinstance(context["evidence_caveats"], list)


def _q1_assert_page_view(
    view: dict,
    digest_value: str,
    version: str,
    *,
    kind: str,
    path: str,
    entity_id: str,
    content: str,
) -> None:
    """The shared §10.4 published page-view oracle: the full SDK
    PublishedContextPage contract (spec 0009 — identity, advisory metadata,
    byte-exact canonical content, the parsed body with its exact body-start
    line, full disclosed native metadata and public Source provenance) plus
    the Core envelope facts. The extended fields' expected values come from
    the AUTHORED canonical content parsed through the producer's public
    parse_frontmatter and disclose_native — an independent producer-contract
    oracle over authored input, never Core result-derived. A required-subset
    check keeps the facade additive (§10.4 adds no parallel page schema and
    freezes no closed field set): future SDK fields never fail this oracle,
    but a citation-only entry, a dropped mandatory field or private metadata
    in place of the full native disclosure does."""
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — qualified test env is external
        disclose_native,
        parse_frontmatter,
    )

    assert {
        "path",
        "draft",
        "kind",
        "namespace",
        "entity_id",
        "published_version",
        "citation",
        "bound_release",
        "content",
        "context_signals",
        "title",
        "lifecycle",
        "review_after",
        "body",
        "body_start_line",
        "native",
        "sources",
    } <= set(view)
    assert view["path"] == path
    assert view["draft"] is False
    assert view["kind"] == kind
    assert view["namespace"] == NAMESPACE
    assert view["entity_id"] == entity_id
    assert view["published_version"] == version
    assert view["citation"] == f"{NAMESPACE} {entity_id} v{version} {path}"
    assert view["bound_release"] == digest_value
    assert view["content"] == content
    assert isinstance(view["context_signals"], dict)
    # the extended full-page fields, from the authored canonical content
    # through the producer's own public contract parsing: exact body and
    # body-start line, authored advisory metadata, and the FULL disclosed
    # native envelope — a bound Table/Policy view can never degrade to a
    # citation-only entry or private metadata (§10.4)
    meta, body, body_start_line = parse_frontmatter(content, Path(path))
    assert view["title"] == meta["title"]
    assert view["lifecycle"] == meta.get("lifecycle")
    assert view["review_after"] == meta.get("review_after")
    assert view["body"] == body
    assert view["body_start_line"] == body_start_line
    assert view["native"] == disclose_native(meta["ariadne_profile"]["native"])
    # the public Source provenance survives as the disclosed list of the
    # authored sources (Source's own id/title identity fields — no new wire
    # shape is guessed here)
    disclosed_sources = disclose_native(view["sources"])
    assert isinstance(disclosed_sources, list)
    assert len(disclosed_sources) == len(meta["sources"])
    for disclosed, authored in zip(disclosed_sources, meta["sources"], strict=True):
        assert disclosed["id"] == authored["id"]
        assert disclosed["title"] == authored["title"]


def test_integrated_detail_requires_complete_input_context(tmp_path, monkeypatch):
    """Q1 detail leg (#84, spec0032 §§2–3, §10.3–§10.5; acceptance §8.2–§8.3,
    §8.8): on one revision-3 admission the legal root/lookup projection
    returns the exact hand-worked rows with governed truth and the complete
    pinned input_context covering BOTH physical dependencies (root table and
    proven lookup table) with full published page views; an unproved
    child-side path refuses regardless of the KB's textual status wording;
    the shared complete-Context budget leg refuses BEFORE the planner, live
    audits, bind or any SELECT; and an otherwise identical release without
    the lookup Table Context refuses before any planner work."""
    import re

    import ariadne.query as query_module
    from ariadne.planner import PlannerError
    from ariadne.sources import table_resource

    orders_resource = table_resource(**P1_ORDERS_ASSET)
    status_resource = table_resource(**P1_STATUS_ASSET)
    project, review = _q1_release(tmp_path)
    tree = worktree_of(project, review["proposal"])
    table_pages = {
        resource: _p1_generated_table_page(tree, resource)
        for resource in (orders_resource, status_resource)
    }

    def no_live(*args, **kwargs):
        raise AssertionError("a pre-execution refusal reached the planner/live path")

    runtime = QueryRuntime.open_project(project)
    try:
        manifest = runtime._managed["bound_release"]
        assert manifest["support_revision"] == 3
        assert manifest["policy_bindings"] == _q1_bindings(orders_resource, status_resource)
        assert set(P1_QUERY_OPS) <= set(manifest["support"]["operations"])

        request = {"dataset": "orders", "fields": ["id", "status_label"]}
        result = asyncio.run(runtime.query_detail(request))
        # hand-worked join over the authored rows: every order's status
        # resolves to exactly one curated label (100 + 50 completed,
        # 25 cancelled), so the projection keeps one row per root order
        assert sorted(result["rows"], key=lambda row: row["id"]) == [
            {"id": 1, "status_label": "Completed order"},
            {"id": 2, "status_label": "Completed order"},
            {"id": 3, "status_label": "Cancelled order"},
        ]
        assert result["governed"] is True
        assert result["admission"]["revision"] == review["revision"]
        assert result["plan"]["relationship_audit"] == "passed"
        assert any(
            audit["name"] == "relationship:order_status_lookup" and audit["outcome"] == "passed"
            for audit in result["plan"]["audits"]
        )

        # §10.4 input_context: both §10.5 physical dependencies (the root
        # table AND the request-selected lookup) in canonical order, with
        # full published Table page views — and no applicable Policy for
        # this operation in this admission's inventory
        context = result["input_context"]
        _q1_assert_input_context(context, manifest["digest"], review["revision"])
        assert [entry["resource"] for entry in context["resources"]] == sorted(
            [orders_resource, status_resource]
        )
        views = {entry["resource"]: entry for entry in context["resources"]}
        for resource, page in table_pages.items():
            entry = views[resource]
            assert set(entry) == {"resource", "table", "dataset"}
            meta, _body = page_parts(page)
            _q1_assert_page_view(
                entry["table"],
                manifest["digest"],
                review["revision"],
                kind="table",
                path=page.relative_to(tree / "knowledge").as_posix(),
                entity_id=meta["id"],
                content=page.read_text(),
            )
            # §3/§10.4: a Dataset Overview view appears only when the
            # collection itself is consumed or referenced — this request
            # consumes two tables, never the collection
            assert entry["dataset"] is None
        assert context["policies"] == []

        # the unproved lookup path (acceptance §8.3): amount lives on orders,
        # so from the order_status root it is reachable only through the
        # CHILD side — a fan-out. The pinned KB carries the Cancelled Orders
        # narrative naming both status sides and the ordinary order-number
        # mapping page; neither textual mapping nor confirmed Identifier
        # Mappings ever make a join admissible (§3).
        with pytest.raises(PlannerError) as caught:
            asyncio.run(runtime.query_detail({"dataset": "order_status", "fields": ["amount"]}))
        assert caught.value.code == "detail_child_side"

        # the shared complete-Context budget leg (acceptance §8.8): a host
        # ceiling the mandatory input_context ALONE cannot fit refuses
        # before the planner, live audits, bind or any SELECT — never a
        # partial answer and never dropped required Context
        context_bytes = query_results.result_json_bytes({"input_context": context})
        old_limits = runtime._limits
        runtime._limits = {**old_limits, "response_bytes": context_bytes - 1}
        with monkeypatch.context() as m:
            m.setattr(query_module, "plan_detail", no_live)
            m.setattr(runtime._execution, "bind", no_live)
            with pytest.raises(query_results.QueryResultError):
                asyncio.run(runtime.query_detail(request))
        runtime._limits = old_limits
    finally:
        runtime.con.close()

    # the missing-Context leg (acceptance §8.2) on a second, otherwise
    # identical release whose order_status Table page was never generated:
    # the proven lookup consumes a physical source without bound Context and
    # refuses BEFORE the planner and any live audit, bind or SELECT (§10.5
    # stage 4), naming the unbound physical identity
    bare_project, _bare_review = _q1_release(tmp_path / "bare", status_context=False)
    bare = QueryRuntime.open_project(bare_project)
    try:
        with monkeypatch.context() as m:
            m.setattr(query_module, "plan_detail", no_live)
            m.setattr(bare._execution, "bind", no_live)
            with pytest.raises(ValueError, match=re.escape(status_resource)):
                asyncio.run(bare.query_detail({"dataset": "orders", "fields": ["status_label"]}))
    finally:
        bare.con.close()


def test_integrated_records_keep_calculation_policies_scoped(tmp_path):
    """Q1 records leg (#84, spec0032 §§2, §4, §7, §10.4; acceptance §8.1,
    §8.7): the sanctioned revenue definition excludes cancelled orders, yet
    a Record Query explicitly selecting them still returns the authored
    cancelled row 25 with governed: false — the cancellation Policy is bound
    to the calculation (query_metrics, executable) and to the consumed table
    only as an EXPLICIT explanatory association for query_records, so prose
    never becomes a universal source filter. The pinned input_context carries
    the full Table page view and that one applicable Policy page view with
    its inventory; the shared A/B session leg proves the old session keeps
    its complete release-A pin while a new session sees release B only after
    its complete human admission."""
    import json

    from ariadne.sources import table_resource

    orders_resource = table_resource(**P1_ORDERS_ASSET)
    project, review = _q1_release(tmp_path)
    tree = worktree_of(project, review["proposal"])
    orders_page = _p1_generated_table_page(tree, orders_resource)
    request = {
        "dataset": "orders.main.orders",
        "fields": ["id", "amount", "status"],
        "order": [{"field": "id", "direction": "asc"}],
        "limit": 10,
    }
    runtime = QueryRuntime.open_project(project)
    try:
        manifest = runtime._managed["bound_release"]
        result = asyncio.run(runtime.query_records(request))
        # independent oracle over the authored rows: the explicitly selected
        # cancelled order O3 = 25 stays selectable — the calculation-only
        # cancellation exclusion never filters records (§4, §8.1)
        assert result["rows"] == [
            {"id": 1, "amount": 100.0, "status": "completed"},
            {"id": 2, "amount": 50.0, "status": "completed"},
            {"id": 3, "amount": 25.0, "status": "cancelled"},
        ]
        assert result["governed"] is False
        assert result["result"]["complete"] is True
        assert result["result"]["has_more_matching"] is False
        # no new source permission: the answer rides the pinned admission
        assert result["provenance"]["admission"]["revision"] == review["revision"]

        context = result["input_context"]
        _q1_assert_input_context(context, manifest["digest"], review["revision"])
        assert [entry["resource"] for entry in context["resources"]] == [orders_resource]
        entry = context["resources"][0]
        assert set(entry) == {"resource", "table", "dataset"}
        meta, _body = page_parts(orders_page)
        _q1_assert_page_view(
            entry["table"],
            manifest["digest"],
            review["revision"],
            kind="table",
            path=orders_page.relative_to(tree / "knowledge").as_posix(),
            entity_id=meta["id"],
            content=orders_page.read_text(),
        )
        assert entry["dataset"] is None  # §3/§10.4: only the table is consumed
        # the ONE applicable Policy (§10.4): the table closure's explicit
        # explanatory association for query_records — subject, association,
        # operations and enforcement mirror the admitted inventory, and the
        # page view is the full published Policy page, never citation-only
        assert len(context["policies"]) == 1
        policy = context["policies"][0]
        assert set(policy) == {"subject", "association", "operations", "enforcement", "page"}
        assert policy["subject"] == {"kind": "table", "identity": orders_resource}
        assert policy["association"] == {
            "namespace": NAMESPACE,
            "entity_id": "entity:cancelled-orders",
        }
        assert policy["operations"] == ["query_records"]
        assert policy["enforcement"] is None  # explanatory prose, never a filter
        policy_page = tree / "knowledge" / "policies" / "cancelled-orders.md"
        _q1_assert_page_view(
            policy["page"],
            manifest["digest"],
            review["revision"],
            kind="policy",
            path="policies/cancelled-orders.md",
            entity_id="entity:cancelled-orders",
            content=policy_page.read_text(),
        )

        # ---- the shared A/B pinned-session/new-session leg (§6, §8.7):
        # release B changes only the orders Table page's curated body
        api = AuthoringProject(project)
        meta, body = page_parts(orders_page)
        write_page(orders_page, meta, body + f"\n{Q1_RELEASE_B_MARKER}\n")
        revised = reconcile_knowledge(project, review["proposal"], review["revision"])
        checked = api.validate_proposal(review["proposal"], revised)
        assert checked["ok"] is True, checked["errors"]
        later = api.review_proposal(review["proposal"])
        activate(
            project, later, preview(project, later, tmp_path / "published", review["revision"])
        )
        # the EXISTING session keeps its complete release-A pin: same digest,
        # same pinned page bytes, and the cancelled row stays selectable
        pinned = asyncio.run(runtime.query_records(request))
        assert pinned["input_context"]["bound_release"] == manifest["digest"]
        assert (
            Q1_RELEASE_B_MARKER not in pinned["input_context"]["resources"][0]["table"]["content"]
        )
        assert pinned["rows"] == result["rows"]
        # only a NEW session sees release B, under its own complete admission
        fresh = QueryRuntime.open_project(project)
        try:
            activated = json.loads((project / ".ariadne" / "current.json").read_text())[
                "bound_release"
            ]
            assert activated["support_revision"] == 3  # no silent capability change
            assert activated["digest"] != manifest["digest"]
            assert fresh._managed["bound_release"]["digest"] == activated["digest"]
            served = asyncio.run(fresh.query_records(request))
            assert served["input_context"]["bound_release"] == activated["digest"]
            assert (
                Q1_RELEASE_B_MARKER in served["input_context"]["resources"][0]["table"]["content"]
            )
            # B changed Context only: same authored rows, same scoping truth
            assert served["rows"] == result["rows"]
            assert served["governed"] is False
        finally:
            fresh.con.close()
    finally:
        runtime.con.close()


def test_integrated_ad_hoc_metric_is_unsaved_and_context_bound(tmp_path, monkeypatch):
    """Q1 Ad-hoc leg (#84, spec0032 §§2, §7, §10.4–§10.5; acceptance §8.2,
    §8.9): an explicit all-orders request no applicable source obligation
    forbids independently implies SUM(amount) = 175 over the authored rows,
    while the sanctioned governed exclusion still returns 150 for the
    completed group on the same release. The answer reports governed: false,
    context: null and a SEPARATE complete pinned input_context; it creates no
    proposal, Computation page or saved definition and mutates nothing; the
    static IO-authority boundary still precedes any data read; and an
    allowed nested source whose physical table lacks bound Context refuses
    before the grain guard or any execution, naming the unbound identity."""
    import hashlib
    import re

    import ariadne.query as query_module
    from ariadne.sources import table_resource

    orders_resource = table_resource(**P1_ORDERS_ASSET)
    status_resource = table_resource(**P1_STATUS_ASSET)
    project, review = _q1_release(tmp_path)
    tree = worktree_of(project, review["proposal"])
    orders_page = _p1_generated_table_page(tree, orders_resource)

    def no_live(*args, **kwargs):
        raise AssertionError("a static refusal reached live work")

    runtime = QueryRuntime.open_project(project)
    try:
        manifest = runtime._managed["bound_release"]
        knowledge_before = {
            path.relative_to(tree).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((tree / "knowledge").rglob("*"))
            if path.is_file()
        }
        descriptor_before = (project / ".ariadne" / "current.json").read_bytes()

        result = asyncio.run(
            runtime.define_metric(
                {
                    "name": "all_orders_value",
                    "source": "orders.main.orders",
                    "expression": "SUM(amount)",
                    "description": "Temporary value over every authored order",
                }
            )
        )
        # independent oracle: 100 + 50 + 25 = 175 for the explicit all-orders
        # request — the sanctioned completed-only exclusion stays 150 (below)
        assert result["rows"] == [{"all_orders_value": 175.0}]
        assert result["governed"] is False
        assert result["context"] is None  # §7: no admitted metric Context exists
        assert result["persistence"] == {"status": "not_saved"}
        # §7: the bound source Context is disclosed SEPARATELY as the pinned
        # input_context, never through a metric-context field
        context = result["input_context"]
        _q1_assert_input_context(context, manifest["digest"], review["revision"])
        assert [entry["resource"] for entry in context["resources"]] == [orders_resource]
        entry = context["resources"][0]
        assert set(entry) == {"resource", "table", "dataset"}
        meta, _body = page_parts(orders_page)
        _q1_assert_page_view(
            entry["table"],
            manifest["digest"],
            review["revision"],
            kind="table",
            path=orders_page.relative_to(tree / "knowledge").as_posix(),
            entity_id=meta["id"],
            content=orders_page.read_text(),
        )
        assert entry["dataset"] is None
        assert context["policies"] == []  # no binding names define_metric here

        # the sanctioned contrast, exactly once: the governed traversal keeps
        # the completed-group exclusion — the ad-hoc result never weakens or
        # rewrites the sanctioned definition (§4)
        sanctioned = asyncio.run(
            runtime.query_metrics({"metrics": ["revenue"], "dimensions": ["status_label"]})
        )
        assert sorted(sanctioned["rows"], key=lambda row: row["status_label"]) == [
            {"status_label": "Cancelled order", "revenue": 0.0},
            {"status_label": "Completed order", "revenue": 150.0},
        ]
        assert sanctioned["governed"] is True

        # the static IO-authority boundary still precedes every data read
        # (§10.5 stage 3, before stage 4's Context preflight and stage 5):
        # a relation outside the approved catalog refuses statically, before
        # the grain guard, bind or collection
        with monkeypatch.context() as m:
            m.setattr(query_module, "check_grain_preserving", no_live)
            m.setattr(runtime._execution, "bind", no_live)
            with pytest.raises(ValueError, match="may read only the registered catalog"):
                asyncio.run(
                    runtime.define_metric(
                        {
                            "name": "ghost_value",
                            "source": (
                                "orders.main.orders o JOIN orders.main.ghost g ON o.id = g.id"
                            ),
                            "expression": "SUM(o.amount)",
                            "description": "Temporary value over an unregistered relation",
                        }
                    )
                )

        # nothing was authored, staged or mutated: no candidate model, no
        # Computation page, no knowledge bytes, no descriptor change (§2, §6)
        assert {
            path.relative_to(tree).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((tree / "knowledge").rglob("*"))
            if path.is_file()
        } == knowledge_before
        assert (project / ".ariadne" / "current.json").read_bytes() == descriptor_before
    finally:
        runtime.con.close()

    # the missing nested-source Context leg (acceptance §8.2): on a second,
    # otherwise identical release without the order_status Table page, an
    # allowed nested join source statically parses to BOTH physical tables
    # — and the unbound one refuses BEFORE the grain guard (a data read) or
    # any execution, naming the exact unbound physical identity (§10.5)
    bare_project, _bare_review = _q1_release(tmp_path / "bare", status_context=False)
    bare = QueryRuntime.open_project(bare_project)
    try:
        with monkeypatch.context() as m:
            m.setattr(query_module, "check_grain_preserving", no_live)
            m.setattr(bare._execution, "bind", no_live)
            with pytest.raises(ValueError, match=re.escape(status_resource)):
                asyncio.run(
                    bare.define_metric(
                        {
                            "name": "joined_value",
                            "source": (
                                "orders.main.orders o JOIN orders.main.order_status s"
                                " ON o.status = s.status"
                            ),
                            "expression": "SUM(o.amount)",
                            "description": "Temporary value over a nested join",
                        }
                    )
                )
        # the parent-dispositioned expression-coverage leg (spec0032 §3):
        # EVERY physical dependency — the expression's scalar subquery reads
        # order_status too — so the same unbound status Resource refuses by
        # its exact authored identity BEFORE the grain guard or bind even
        # though the SOURCE alone is fully bound (static-authority-approved
        # SUM/COUNT only; no numeric oracle — the early refusal is the
        # expectation)
        with monkeypatch.context() as m:
            m.setattr(query_module, "check_grain_preserving", no_live)
            m.setattr(bare._execution, "bind", no_live)
            with pytest.raises(ValueError, match=re.escape(status_resource)):
                asyncio.run(
                    bare.define_metric(
                        {
                            "name": "expression_borrowed_count",
                            "source": "orders.main.orders",
                            "expression": (
                                "SUM(amount) + (SELECT COUNT(*) FROM"
                                " orders.main.order_status)"
                            ),
                            "description": "Temporary value borrowing a nested count",
                        }
                    )
                )
    finally:
        bare.con.close()


# --------------------- Q1 final review refusals (spec0032 §§3–4, §10.2, §10.5 stage 1)

# The parent-dispositioned fix-first findings F1–F3, each an independently
# authored expectation from the written contracts (never product output):
# F1 — SQLGlot's Scope keeps SEMI/ANTI right-hand tables OUT of
# selected_sources (optimizer/scope.py: the separate _semi_anti_join_tables
# set), so the revision-3 static inventory must still enumerate those
# physical reads; a membership-filtered source whose RHS table lacks bound
# Context refuses by its exact canonical identity BEFORE the grain guard or
# bind. F2 — an executable Policy binding is established only by the check
# that actually executes for its declared target: when the whole expression
# reads a table the source-only grain check never receives, the obligation
# cannot be attested and the operation refuses before live work, naming the
# check id AND the unattested target identity (§10.2 attestation — never a
# label on an unrelated passing call, never a new check). F3 — the native
# structured malformed-request errors keep ownership ahead of dependency /
# Context preflight: type checks precede hashing and the planner's own
# request_invalid/unknown_dataset codes survive (§7, §10.5 stage 1).
Q1_REVIEW_CASES = [
    pytest.param("semi-context", id="semi-context"),
    pytest.param("anti-context", id="anti-context"),
    pytest.param("grain-expression-target", id="grain-expression-target"),
    pytest.param("detail-fields-shape", id="detail-fields-shape"),
    pytest.param("detail-dataset-shape", id="detail-dataset-shape"),
    pytest.param("records-fields-shape", id="records-fields-shape"),
    pytest.param("records-order-shape", id="records-order-shape"),
    pytest.param("records-timestamp-literal", id="records-timestamp-literal"),
    pytest.param("records-in-list-literal", id="records-in-list-literal"),
]


@pytest.mark.parametrize("case", Q1_REVIEW_CASES)
def test_integrated_query_review_refusals(case, tmp_path, monkeypatch):
    """Six finite refusal nodes of the final independent review (fix-first
    F1–F3), each over a real native rev-3 admission built per case with one
    validation: SEMI/ANTI membership-filtered sources must not lose their
    right-hand physical dependency's mandatory Context; an executable
    adhoc.grain_preserving binding whose target the actual source-only check
    cannot establish refuses before grain/bind instead of executing with an
    unattested obligation; and the public malformed-request shapes keep the
    native PlannerError codes (request_invalid / unknown_dataset) instead of
    TypeError or a misleading Context error."""
    import re

    import ariadne.query as query_module
    from ariadne.planner import PlannerError
    from ariadne.sources import table_resource

    status_resource = table_resource(**P1_STATUS_ASSET)

    def no_live(*args, **kwargs):
        raise AssertionError("a pre-execution refusal reached the live path")

    if case in ("semi-context", "anti-context"):
        # F1: both relations approved and the release validly admitted — the
        # refusal must be the MISSING status Table Context, never an IO
        # permission failure masking it
        join = "SEMI" if case == "semi-context" else "ANTI"
        project, _review = _q1_release(tmp_path, status_context=False)
        runtime = QueryRuntime.open_project(project)
        try:
            with monkeypatch.context() as m:
                m.setattr(query_module, "check_grain_preserving", no_live)
                m.setattr(runtime._execution, "bind", no_live)
                with pytest.raises(ValueError, match=re.escape(status_resource)):
                    asyncio.run(
                        runtime.define_metric(
                            {
                                "name": "membership_value",
                                "source": (
                                    "SELECT o.* FROM orders.main.orders AS o"
                                    f" {join} JOIN orders.main.order_status AS s"
                                    " ON o.status = s.status"
                                ),
                                "expression": "SUM(amount)",
                                "description": "Temporary membership-filtered value",
                            }
                        )
                    )
        finally:
            runtime.con.close()
        return

    if case == "grain-expression-target":
        # F2: the status Table's typed closure and executable define_metric
        # binding are authored inputs admitted for real; the plain-orders
        # request's expression reads the status table (CROSS JOIN self-join)
        # that the actual source-only grain check never receives — the
        # obligation cannot be attested, so the operation refuses before
        # grain/bind naming the check id AND the unattested target
        project, review = _q1_release(tmp_path, status_closure=True)
        from lumio_wiki.ariadne_context import (  # pyright: ignore[reportMissingImports] — qualified test env is external
            inspect_ariadne_candidate,
        )

        tree = worktree_of(project, review["proposal"])
        assert (
            inspect_ariadne_candidate(
                str(tree / "knowledge"), review["revision"], namespace=NAMESPACE
            ).diagnostics
            == ()
        ), "the fixture must be producer-valid; only the consumer attestation contract refuses"
        runtime = QueryRuntime.open_project(project)
        try:
            manifest = runtime._managed["bound_release"]
            admitted = [
                binding
                for binding in manifest["policy_bindings"]["bindings"]
                if binding["subject"]["identity"] == status_resource
                and (binding.get("enforcement") or {}).get("check") == "adhoc.grain_preserving"
            ]
            assert admitted, "the executable status binding must be part of the real admission"
            with monkeypatch.context() as m:
                m.setattr(query_module, "check_grain_preserving", no_live)
                m.setattr(runtime._execution, "bind", no_live)
                with pytest.raises(ValueError) as refused:
                    asyncio.run(
                        runtime.define_metric(
                            {
                                "name": "borrowed_status_count",
                                "source": "orders.main.orders",
                                "expression": (
                                    "SUM(amount) + (SELECT COUNT(*) FROM"
                                    " orders.main.order_status AS s CROSS JOIN"
                                    " orders.main.order_status AS t)"
                                ),
                                "description": "Temporary value over an unattested status read",
                            }
                        )
                    )
            message = str(refused.value)
            assert "adhoc.grain_preserving" in message
            assert status_resource in message
        finally:
            runtime.con.close()
        return

    if case == "detail-fields-shape":
        # F3: the native planner's structured request validation owns the
        # malformed shape — request_invalid, never a TypeError from the
        # static dependency seam's hashing
        project, _review = _q1_release(tmp_path)
        runtime = QueryRuntime.open_project(project)
        try:
            with pytest.raises(PlannerError) as caught:
                asyncio.run(runtime.query_detail({"dataset": "orders", "fields": [{}]}))
            assert caught.value.code == "request_invalid"
        finally:
            runtime.con.close()
        return

    if case == "detail-dataset-shape":
        # F3: an unhashable dataset name keeps the native unknown_dataset
        # refusal — the type check precedes any dictionary membership
        project, _review = _q1_release(tmp_path)
        runtime = QueryRuntime.open_project(project)
        try:
            with pytest.raises(PlannerError) as caught:
                asyncio.run(runtime.query_detail({"dataset": {}, "fields": ["id"]}))
            assert caught.value.code == "unknown_dataset"
        finally:
            runtime.con.close()
        return

    if case == "records-order-shape":
        # F3 follow-up (owner-approved bounded unit): the native STATIC order
        # contract — plan_records' own "'order' is required: a non-empty
        # list" refusal — owns the malformed request BEFORE the integrated
        # Context preflight: the known status dataset's deliberately absent
        # Table Context must not turn a request-shape error into a
        # Context-preparation refusal (spec0032 §7, §10.5 stage 1; spec0014
        # order contract). Nothing in this request needs a live engine to
        # establish the native error (no filters, no regex, no timestamp)
        project, _review = _q1_release(tmp_path, status_context=False)
        runtime = QueryRuntime.open_project(project)
        try:
            with pytest.raises(PlannerError) as caught:
                asyncio.run(
                    runtime.query_records(
                        {
                            "dataset": "orders.main.order_status",
                            "fields": ["status"],
                            "order": [],
                            "limit": 10,
                        }
                    )
                )
            assert caught.value.code == "order_invalid"
        finally:
            runtime.con.close()
        return

    if case == "records-timestamp-literal":
        # F3 temporal-literal follow-up (owner-approved bounded unit): the
        # native PURE temporal comparison-literal validator — _record_instant's
        # encoding/type rule (planner.py:2328-2363) — owns the mistyped CALLER
        # literal BEFORE the integrated Context preflight: comparing the
        # declared VARCHAR timestamp carrier under Europe/Berlin against 42
        # is a caller-value error that no source row, connection or live RE2
        # judgement is needed to establish (spec0032 §7, §10.5 stage 1;
        # spec0014 §3's typed interpretation — the planner-side mirror of the
        # guarded SQL interpretation). The deliberately absent status Table
        # Context must not turn it into a Context-preparation refusal
        project, _review = _q1_release(tmp_path, status_context=False)
        runtime = QueryRuntime.open_project(project)
        try:
            with pytest.raises(PlannerError) as caught:
                asyncio.run(
                    runtime.query_records(
                        {
                            "dataset": "orders.main.order_status",
                            "fields": ["status"],
                            "timestamp": {
                                "field": "status",
                                "format": "%Y-%m-%d %H:%M:%S",
                                "timezone": "Europe/Berlin",
                            },
                            "filters": [{"field": "status", "op": ">=", "value": 42}],
                            "order": [{"field": "status", "direction": "asc"}],
                            "limit": 10,
                        }
                    )
                )
            assert caught.value.code == "timestamp_interpretation"
        finally:
            runtime.con.close()
        return

    if case == "records-in-list-literal":
        # IN-list follow-up (owner-approved bounded unit): the native
        # scalar-only IN contract (spec0014 §3 — an IN predicate takes a
        # literal list of SCALAR values) owns the nested-list element BEFORE
        # the missing status Table Context: _direct_literal's filter_invalid
        # rejection of a list element currently fires only during SQL
        # predicate construction, after Context (spec0032 §7, §10.5 stage 1:
        # pure caller-literal validation precedes the Context preflight). No
        # SQL, connection or live RE2 judgement is needed to establish it
        project, _review = _q1_release(tmp_path, status_context=False)
        runtime = QueryRuntime.open_project(project)
        try:
            with pytest.raises(PlannerError) as caught:
                asyncio.run(
                    runtime.query_records(
                        {
                            "dataset": "orders.main.order_status",
                            "fields": ["status"],
                            "filters": [
                                {"field": "status", "op": "in", "value": [["completed"]]}
                            ],
                            "order": [{"field": "status", "direction": "asc"}],
                            "limit": 10,
                        }
                    )
                )
            assert caught.value.code == "filter_invalid"
        finally:
            runtime.con.close()
        return

    # case == "records-fields-shape": F3 — the native plan_records shape
    # validation (non-empty fields) owns the refusal BEFORE the Context
    # lookup: the status dataset's Table Context is deliberately absent and
    # must NOT turn a malformed request into a Context error
    project, _review = _q1_release(tmp_path, status_context=False)
    runtime = QueryRuntime.open_project(project)
    try:
        with pytest.raises(PlannerError) as caught:
            asyncio.run(
                runtime.query_records(
                    {
                        "dataset": "orders.main.order_status",
                        "fields": [],
                        "order": [{"field": "status", "direction": "asc"}],
                        "limit": 10,
                    }
                )
            )
        assert caught.value.code == "request_invalid"
    finally:
        runtime.con.close()
