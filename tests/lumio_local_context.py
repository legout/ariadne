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
from tests.lumio_metric_mvp import (
    CANCELLATION,
    NAMESPACE,
    activate,
    content_project,
    page_parts,
    preview,
    reconcile_knowledge,
    write_page,
)
from tests.test_contracts import ORDERS_BINDINGS, ORDERS_CONTRACT, contracted
from tests.test_git_authoring import approved, run_git, worktree_of

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
    from tests.lumio_metric_mvp import current_bytes, ready
    from tests.test_discovery import _source_free_guards

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
    from tests.lumio_metric_mvp import CONTROL

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
    from tests.lumio_metric_mvp import current_bytes
    from tests.test_discovery import _source_free_guards

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
    assert current_bytes(project) == descriptor_before  # validation ≠ activation

    assert "retail-return-policy" in diagnostics
    assert "whose content changed since the measurement" in diagnostics
