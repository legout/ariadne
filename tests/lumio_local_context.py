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
    (tree / "context_layer" / GLOSSARY_PATH).write_text(LEGACY_GLOSSARY_MD)
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

    def _text_json(result):
        blocks = [
            block
            for block in getattr(result, "content", ())
            if getattr(block, "type", None) == "text"
        ]
        assert len(blocks) == 1, "typed tool result must carry its JSON text content"
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
    listed = _text_json(results["list"])
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
    # mcp func_metadata.convert_result wraps a typed list return as {"result": ...}
    assert results["list"].structured_content == {"result": listed}

    # read: the full canonical SDK page; the legacy same-path body never wins.
    page = _text_json(results["read"])
    for key, value in identity.items():
        assert page.get(key) == value, key
    assert page["content"] == GLOSSARY_MD
    assert page["context_signals"]["warnings"] == []
    assert results["read"].structured_content == page  # typed dict stays unwrapped

    # search: one native hit with the verbatim hand-counted passage.
    hits = _text_json(results["search"])
    assert len(hits) == 1
    for key, value in hit_oracle.items():
        assert hits[0].get(key) == value, key
    assert hits[0]["context_signals"]["warnings"] == []
    assert results["search"].structured_content == {"result": hits}

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
    report = _text_json(results["discover"])
    assert results["discover"].structured_content == report
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
