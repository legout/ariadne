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
    assert "resolve_term" in support["unsupported"]
    assert report["groups"]["pages"] == {
        "status": "available",
        "items": hits,
        "completeness": "unknown",
    }
    assert report["groups"]["terms"]["status"] == "unavailable"
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
