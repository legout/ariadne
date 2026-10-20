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
