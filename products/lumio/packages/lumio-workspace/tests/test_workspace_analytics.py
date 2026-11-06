"""D1/VD1: exact source grants, combined review, and a pinned native SQLite query."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from html import unescape
from pathlib import Path

import pytest
from ariadne import admission, authoring_sources, execution
from ariadne import sources as native_sources
from ariadne.authoring import AuthoringProject
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState
from lumio_workspace.analytics import AnalyticsError, AnalyticsService
from lumio_workspace.intake import IntakeService
from lumio_workspace.review import ReviewError, ReviewService, render_review
from lumio_workspace.setup import current_attachment_digest

NAMESPACE = "urn:demo:retail"
FILTER_EXPRESSION = "SUM(amount) FILTER (WHERE status = 'completed')"
POLICY_ADDITION = "Only completed orders enter the reviewed EUR revenue calculation."
SENTINEL = "PRIVATE-SENTINEL-NOT-FOR-THE-READER"
CONTROL = """version: 2
mode: categorized
categories:
  - name: policies
  - name: metrics
ontology:
  entity_types:
    policy: {}
    metric: {}
"""
SELECTOR = """version: 1
mode: integrated
subtree: knowledge
namespace: urn:demo:retail
profile: ariadne-context/1
"""
MODEL = """version: 0.2.0.dev0
semantic_model:
  - name: retail_sales
    description: Orders model
    datasets:
      - name: orders
        source: orders.main.orders
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
            dimension: {}
    metrics:
      - name: revenue
        description: Completed revenue in EUR
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)
"""
NATIVE_POLICY = """---
type: policy
status: stable
title: Recognized revenue
description: Completed orders enter recognized revenue.
tags: [policy]
sources:
  - id: seed-notes
    resource: data/seed_notes.md
    title: Seed notes
---

# Recognized revenue
"""
NATIVE_METRIC = """---
type: metric
status: stable
title: revenue
description: Completed revenue in EUR.
tags: [metric]
sources:
  - id: recognized-revenue
    resource: policies/recognized-revenue.md
    title: Recognized revenue
---

# revenue
"""
RETURN_POLICY = """---
id: entity:retail-return-policy
title: Retail Return Policy
entity_types: [policy]
tags: [retail, returns]
summary: Recognized refunds reduce revenue when recognized.
lifecycle: approved
visibility: internal
synthetic: true
sources:
  - id: src-returns-handbook
    title: Synthetic returns handbook
ariadne_profile:
  version: 1
  kind: policy
  required_policies: []
  native:
    type: policy
    title: Retail Return Policy
    description: Recognized refunds reduce revenue when recognized.
    tags: [policy, returns]
    status: stable
    stale_after: 2027-06-30
    verified:
      - by: human:synthetic-owner
        on: 2026-10-01
    sources:
      - id: okf-policy-return
        title: Returns policy page
        resource: policies/retail-return-policy.md
---

# Retail Return Policy

Revenue is reduced by recognized refunds in the month the refund is recognized.
"""
CANCELLATION = """---
id: entity:cancelled-orders
entity_types: [policy]
tags: [policy]
title: Cancelled Orders
summary: Cancelled orders are excluded from recognized revenue.
visibility: public
lifecycle: approved
sources:
  - id: human-cancellation-rule
    title: Synthetic operator rule
ariadne_profile:
  version: 1
  kind: policy
  required_policies: []
  native:
    type: policy
    title: Cancelled Orders
    description: Exclude cancelled orders from recognized revenue.
    status: stable
    tags: [policy]
    stale_after: 2027-06-30
    verified:
      - by: human:synthetic-owner
        on: 2026-10-01
    sources:
      - id: human-cancellation-rule
        title: Synthetic operator rule
---

# Cancelled Orders

Cancelled orders are excluded. Completed orders 100 and 50 count; cancelled
order 25 does not. The sanctioned OSI expression performs this exclusion.
"""
METRIC = """---
id: entity:retail-revenue
title: Retail Revenue (Metric)
entity_types: [metric]
tags: [retail, finance]
summary: Completed recognized retail revenue in EUR.
lifecycle: approved
visibility: internal
synthetic: true
sources:
  - id: src-finance-model
    title: Synthetic finance model review
ariadne_profile:
  version: 1
  kind: metric
  metric_ref:
    model: retail_sales
    metric: revenue
  required_policies:
    - namespace: urn:demo:retail
      entity_id: entity:retail-return-policy
    - namespace: urn:demo:retail
      entity_id: entity:cancelled-orders
  native:
    type: metric
    status: stable
    title: Retail revenue
    description: Completed recognized retail revenue in EUR.
    tags: [finance]
    stale_after: 2027-06-30
    sources:
      - id: pol-return
        title: Governing return policy
        resource: policies/retail-return-policy.md
      - id: cancelled-orders
        title: Governing cancellation policy
        resource: policies/cancelled-orders.md
    governed_by: policies/retail-return-policy.md
    dimensions: [status]
    grain:
      primary_key: [id]
      cardinality_enforcement: strict_1_to_1
---

# Retail Revenue (Metric)

Retail revenue is completed recognized sales in EUR, reduced by recognized refunds.
"""
WORKSPACE_POLICY = (
    CANCELLATION.replace("visibility: public", "visibility: internal")
    .replace("lifecycle: approved", "lifecycle: approved\nsynthetic: true")
    .replace(
        "entity_types: [policy]",
        "entity_types: [policy]\ncategory: policies\ntype: policy\n"
        "durability_rationale: Completed-order revenue rules remain binding.",
    )
)


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _sqlite(path: Path, rows: list[tuple], *, table: str = "entries") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE entries (id INTEGER, amount INTEGER, status VARCHAR);\n"
        "CREATE TABLE orders (id INTEGER, amount INTEGER, status VARCHAR);"
    )
    if table == "entries":
        for row in rows:
            connection.execute("INSERT INTO entries VALUES (?, ?, ?)", (*row,))
    elif table == "orders":
        for row in rows:
            connection.execute("INSERT INTO orders VALUES (?, ?, ?)", (*row,))
    else:
        raise ValueError("unknown synthetic SQLite table")
    connection.commit()
    connection.close()


def _git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"git {arguments} failed: {result.stderr}"
    return result.stdout.strip()


def _native_baseline(root: Path) -> tuple[Path, AuthoringProject, dict, str]:
    project = root / "proj"
    project.mkdir(parents=True)
    _sqlite(
        project / "data" / "baseline.sqlite",
        [(1, 100, "completed"), (2, 50, "completed"), (3, 25, "cancelled")],
        table="orders",
    )
    cancellation = CANCELLATION.replace("visibility: public", "visibility: internal").replace(
        "lifecycle: approved", "lifecycle: approved\nsynthetic: true"
    )
    files = {
        "ariadne.yaml": (
            "sources:\n  - name: orders\n    type: sqlite\n    path: data/baseline.sqlite\n"
        ),
        "data/seed_notes.md": "# Seed notes\n\nCompleted orders enter recognized revenue.\n",
        "semantic_layer/models/retail_sales.yml": MODEL,
        "context_layer/policies/recognized-revenue.md": NATIVE_POLICY,
        "context_layer/metrics/revenue.md": NATIVE_METRIC,
        "knowledge/lumio.yaml": CONTROL,
        "knowledge/metrics/retail-revenue.md": METRIC,
        "knowledge/policies/retail-return-policy.md": RETURN_POLICY,
        "knowledge/policies/cancelled-orders.md": cancellation,
        "context_integration.yaml": SELECTOR,
    }
    for relative, content in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest = project / "knowledge" / SOURCE_REFERENCE_MANIFEST_BASENAME
    manifest.write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    _git(project, "init", "-q")
    _git(project, "config", "user.name", "Synthetic Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    _git(project, "add", "--", *files, str(manifest.relative_to(project)))
    _git(project, "commit", "-q", "-m", "synthetic native baseline")
    api = AuthoringProject(project)
    started = api.start_proposal()
    resolved, digest = authoring_sources.candidate_sources(project, started["candidate_revision"])
    assert resolved is not None and digest is not None
    api.approve_sources(started["proposal"], started["candidate_revision"], digest)
    return project, api, started, started["candidate_revision"]


def _decide(review: ReviewService, reviewer: Actor, task_id: str) -> dict:
    context = review.get(reviewer, task_id)
    return review.decide(reviewer, task_id, context.action_digest, "approve")


def test_source_grant_and_combined_review_gate_pinned_query(tmp_path, monkeypatch):
    # A real integrated admitted baseline is fixture setup. The journey below
    # adds a new SQLite source through the service, never through fixture SQL.
    project, api, started, revision = _native_baseline(tmp_path / "baseline")
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    native_review = api.review_proposal(started["proposal"])
    destination = tmp_path / "published"
    private = tmp_path / "private"
    registry = private / "registry"
    artifacts = private / "artifacts"
    registry.mkdir(parents=True)
    artifacts.mkdir()
    profile = private / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(registry),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(artifacts)},
            }
        ),
        encoding="utf-8",
    )
    overall = admission.overall_review(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        destination=destination,
        expected_current="none",
        private_profile=profile,
        scope=("internal",),
    )
    admission.admit_revision(
        project,
        started["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        confirmed_by="human:synthetic-baseline-owner",
        overall_preview=overall,
        confirmed_overall_digest=overall["digest"],
        private_profile=profile,
    )

    _sqlite(
        project / "data" / "orders.sqlite",
        [(1, 10, "completed"), (2, 20, "completed")],
    )
    _sqlite(project / "data" / "private.sqlite", [(1, 0, SENTINEL)])
    bindings = private / "source-bindings.json"
    bindings.write_text(
        json.dumps(
            {
                "orders_sqlite": [
                    {"name": "orders_sqlite", "type": "sqlite", "path": "data/orders.sqlite"}
                ],
                "private": [{"name": "private", "type": "sqlite", "path": "data/private.sqlite"}],
            }
        ),
        encoding="utf-8",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-analytics",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=native_review["revision"],
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=project / "knowledge",
        private_profile_path=profile,
        private_root=tmp_path / "operations",
        namespace=NAMESPACE,
        analytics_project_id="retail",
        analytics_project_path=project,
        analytics_source_bindings_path=bindings,
    )
    assert config.authoring_path is not None
    state = WorkspaceState(config.state_path)
    contributor = Actor(tenant_id="local", object_id="contributor")
    reviewer = Actor(tenant_id="local", object_id="reviewer")
    reader = Actor(tenant_id="local", object_id="reader")
    owner = Actor(tenant_id="local", object_id="owner")
    for actor in (contributor, reviewer, reader, owner):
        state.create_local_user(actor.object_id)
        state.grant(config.workspace_id, actor)
    state.grant(config.workspace_id, contributor, "contribute")
    state.grant(config.workspace_id, reviewer, "review")
    state.grant(config.workspace_id, owner, "setup")
    attachment = current_attachment_digest(
        target=config.authoring_path,
        profile_path=profile,
    )
    state.record_setup(
        config.workspace_id,
        owner,
        "synthetic-analytics-setup",
        kind="existing",
        target=config.authoring_path,
        namespace=NAMESPACE,
        base_revision=native_review["revision"],
        attachment_digest=attachment,
    )
    intake = IntakeService(state, config.operational_root)
    analytics = AnalyticsService(config, state, intake)
    review = ReviewService(
        state,
        workspace_id=config.workspace_id,
        authoring_path=config.authoring_path,
        profile_path=profile,
        private_root=config.operational_root,
        destination=destination,
        analytics=analytics,
    )

    opened = []
    real_builder = execution.build_connection

    def spy(registry, **kwargs):
        opened.append([source.path for source in registry.sources])
        return real_builder(registry, **kwargs)

    monkeypatch.setattr(execution, "build_connection", spy)
    monkeypatch.setattr(native_sources, "build_connection", spy)

    prepared = analytics.prepare_data_source(
        contributor,
        retry_key="request-sqlite",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["What is completed revenue in EUR?"],
    )
    source_task = prepared["task_id"]
    assert prepared["status"] == "pending_source_approval"
    assert str(project) not in json.dumps(prepared)
    with pytest.raises(AnalyticsError, match="Source Approval"):
        analytics.profile_data_source(contributor, source_task)
    assert opened == []

    rejected = analytics.prepare_data_source(
        contributor,
        retry_key="request-rejected-sqlite",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["This declaration must not be approved by a rejected task."],
    )
    rejected_context = review.get(reviewer, rejected["task_id"])
    rejected_result = review.decide(
        reviewer, rejected["task_id"], rejected_context.action_digest, "reject"
    )
    assert rejected_result["status"] == "rejected"
    with pytest.raises(ReviewError, match="pending review"):
        review.get(reviewer, rejected["task_id"])
    rejected_sources, rejected_digest = authoring_sources.candidate_sources(
        project, rejected["native_candidate"]
    )
    assert not authoring_sources.approval_state(
        project, rejected_sources, rejected_digest
    ).get("approved")
    assert opened == []

    approved = _decide(review, reviewer, source_task)
    assert approved["status"] == "pending_data_grant"
    with pytest.raises(AnalyticsError, match="data authorization"):
        analytics.profile_data_source(contributor, source_task)
    assert opened == []

    granted = _decide(review, reviewer, source_task)
    assert granted["status"] == "data_granted"
    profiled = analytics.profile_data_source(contributor, source_task)
    sqlite_profile = next(
        source for source in profiled["profile"]["sources"] if source["name"] == "orders_sqlite"
    )
    assert [source["name"] for source in profiled["profile"]["sources"]] == ["orders_sqlite"]
    assert set(sqlite_profile["tables"]) == {"entries"}
    assert sqlite_profile["tables"]["entries"]["row_count"] == 2
    assert sqlite_profile["tables"]["entries"]["sample_limit"] == 100
    assert opened

    original = b"# Cancelled Orders\n\nOnly completed orders enter EUR revenue.\n"
    uploaded = intake.save(
        config.workspace_id,
        contributor,
        "human-cancellation-rule",
        "cancelled-orders.md",
        "policy-upload-one",
        original,
    )
    _, snapshot = admission.resolve_admission(project)
    model = (snapshot / "semantic_layer/models/retail_sales.yml").read_text(encoding="utf-8")
    changed_model = model.replace("orders.main.orders", "orders_sqlite.main.entries").replace(
        "SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)", FILTER_EXPRESSION
    )
    assert FILTER_EXPRESSION in changed_model
    candidate = analytics.prepare_contribution(
        contributor,
        retry_key="sqlite-policy-filter-one",
        source_task_id=source_task,
        sources=[{"upload_id": uploaded["upload_id"], "intent": "new"}],
        pages=[
            {
                "filename": "cancelled-orders.md",
                "markdown": WORKSPACE_POLICY.replace(
                    "Cancelled orders are excluded.", POLICY_ADDITION
                ),
            }
        ],
        core_edits=[{"kind": "model", "name": "retail_sales", "content": changed_model}],
    )
    contribution_task = candidate["task_id"]
    assert candidate["status"] == "pending_submission"
    submitted = _decide(review, reviewer, contribution_task)
    assert submitted["status"] == "pending_publication"
    assert submitted["validation"]["ok"] is True

    context = review.get(reviewer, contribution_task)
    html = render_review(context, config.published_version)
    rendered = unescape(html)
    assert FILTER_EXPRESSION in rendered
    assert POLICY_ADDITION in rendered
    proposal = candidate["native_proposal"]
    committed = submitted["native_candidate"]
    current_native_review = api.review_proposal(proposal)
    with pytest.raises(ValueError, match="integrated admission requires one exact composite"):
        admission.admit_revision(
            project,
            proposal,
            committed,
            current_native_review["review_digest"],
            confirmed_by="human:knowledge-only-consent-is-not-overall-consent",
            private_profile=profile,
        )
    published = review.decide(reviewer, contribution_task, context.action_digest, "approve")
    assert published["status"] == "published"
    assert published["publication_outcome"] == "activated"

    resolved_commits = []
    real_resolve = admission.resolve_admission

    def resolve_spy(project):
        resolved, snapshot = real_resolve(project)
        resolved_commits.append(resolved["commit"])
        return resolved, snapshot

    monkeypatch.setattr(admission, "resolve_admission", resolve_spy)
    resolved_commits.clear()
    result = analytics.query_data(
        contributor,
        "retail",
        source_task,
        "get_metric",
        {"name": "revenue"},
    )
    assert result["rows"] == [{"revenue": 30.0}]
    assert result["governed"] is True
    assert result["context"]["bound_release"] == published["bound_release"]
    assert {citation["entity_id"] for citation in result["context"]["citations"]} == {
        "entity:retail-revenue",
        "entity:retail-return-policy",
        "entity:cancelled-orders",
    }
    assert POLICY_ADDITION in "\n".join(result["context"]["policies"])
    assert result["result"]["complete"] is True
    assert "data_signals" in result
    assert result["pinned"]["commit"] == published["native_candidate"]
    assert len(resolved_commits) >= 3
    assert set(resolved_commits) == {published["native_candidate"]}
    assert SENTINEL not in json.dumps(result)

    reused = analytics.prepare_data_source(
        contributor,
        retry_key="request-sqlite-reuse",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["Reuse the identical admitted declaration and exact approval."],
    )
    reused_task = reused["task_id"]
    assert reused["status"] == "pending_data_grant"
    assert reused["reused_source_declaration"] is True
    assert reused["native_candidate"] == published["native_candidate"]
    assert _decide(review, reviewer, reused_task)["status"] == "data_granted"
    reused_upload = intake.save(
        config.workspace_id,
        contributor,
        "human-cancellation-rule",
        "cancelled-orders.md",
        "policy-upload-reuse",
        original + b"Review exact declaration reuse.\n",
    )
    reused_candidate = analytics.prepare_contribution(
        contributor,
        retry_key="sqlite-policy-filter-reuse",
        source_task_id=reused_task,
        sources=[{"upload_id": reused_upload["upload_id"], "intent": "update"}],
        pages=[
            {
                "filename": "cancelled-orders.md",
                "markdown": WORKSPACE_POLICY.replace(
                    "Cancelled orders are excluded.", POLICY_ADDITION + " Reuse the declaration."
                ),
            }
        ],
        core_edits=[{"kind": "model", "name": "retail_sales", "content": changed_model}],
    )
    reused_contribution_task = reused_candidate["task_id"]
    reused_submitted = _decide(review, reviewer, reused_contribution_task)
    assert reused_submitted["status"] == "pending_publication"
    reused_context = review.get(reviewer, reused_contribution_task)
    real_finish = state.finish_review_task
    real_publish = analytics.publication.publish_overall
    publish_calls = 0

    def publish_spy(*args, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        return real_publish(*args, **kwargs)

    def fail_published(workspace_id, task_id, status, response, **kwargs):
        if task_id == reused_contribution_task and status == "published":
            raise RuntimeError("synthetic post-admission bookkeeping failure")
        return real_finish(workspace_id, task_id, status, response, **kwargs)

    monkeypatch.setattr(analytics.publication, "publish_overall", publish_spy)
    monkeypatch.setattr(state, "finish_review_task", fail_published)
    with pytest.raises(ReviewError, match="post-admission bookkeeping failure"):
        review.decide(
            reviewer, reused_contribution_task, reused_context.action_digest, "approve"
        )
    monkeypatch.setattr(state, "finish_review_task", real_finish)
    recovered = review.reconcile_task(reused_contribution_task)
    assert recovered is not None and recovered["status"] == "published"
    assert recovered["publication_outcome"] == "activated"
    assert publish_calls == 1

    # A second admitted source set contains the private SQLite catalog. The
    # requester is authorized for it; a different workspace reader is not.
    second = analytics.prepare_data_source(
        contributor,
        retry_key="request-private-set",
        project="retail",
        source="private",
        table="entries",
        business_questions=["This set must be denied to an unauthorized reader."],
    )
    second_task = second["task_id"]
    _decide(review, reviewer, second_task)
    _decide(review, reviewer, second_task)
    second_upload = intake.save(
        config.workspace_id,
        contributor,
        "human-cancellation-rule",
        "cancelled-orders.md",
        "policy-upload-two",
        original + b"Review the complete source set.\n",
    )
    combined = analytics.prepare_contribution(
        contributor,
        retry_key="sqlite-policy-filter-two",
        source_task_id=second_task,
        sources=[{"upload_id": second_upload["upload_id"], "intent": "update"}],
        pages=[
            {
                "filename": "cancelled-orders.md",
                "markdown": WORKSPACE_POLICY.replace(
                    "Cancelled orders are excluded.", POLICY_ADDITION + " Recheck all sources."
                ),
            }
        ],
        core_edits=[{"kind": "model", "name": "retail_sales", "content": changed_model}],
    )
    current_before_revocation = admission.load_current(project)
    assert current_before_revocation is not None
    previous_commit = current_before_revocation["commit"]
    state.revoke(config.workspace_id, contributor, "contribute")
    with pytest.raises(ReviewError, match="submitter no longer has current"):
        _decide(review, reviewer, combined["task_id"])
    current_after_refusal = admission.load_current(project)
    assert current_after_refusal is not None
    assert current_after_refusal["commit"] == previous_commit
    state.grant(config.workspace_id, contributor, "contribute")

    _decide(review, reviewer, combined["task_id"])
    combined_context = review.get(reviewer, combined["task_id"])
    combined_published = review.decide(
        reviewer, combined["task_id"], combined_context.action_digest, "approve"
    )
    assert combined_published["status"] == "published"

    opened.clear()
    with pytest.raises(AnalyticsError, match="not available for this caller"):
        analytics.query_data(
            reader,
            "retail",
            second_task,
            "get_metric",
            {"name": "revenue"},
        )
    assert opened == []
    assert SENTINEL not in json.dumps(combined_published)
