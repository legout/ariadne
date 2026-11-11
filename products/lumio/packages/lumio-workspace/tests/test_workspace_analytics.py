"""D1/VD1: exact source grants, combined review, and a pinned native SQLite query."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import zipfile
from html import unescape
from pathlib import Path, PurePosixPath

import duckdb
import pytest
from ariadne import admission, authoring_sources, execution
from ariadne import sources as native_sources
from ariadne.authoring import AuthoringProject
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
from lumio_workspace.analytics import AnalyticsError, AnalyticsService
from lumio_workspace.intake import IntakeService
from lumio_workspace.review import ReviewError, ReviewService, render_review
from lumio_workspace.setup import current_attachment_digest
from starlette.testclient import TestClient

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


def _write_workbook(path: Path) -> bytes:
    """Hand-authored minimal OOXML: one 'Orders' sheet with three stored rows."""

    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:C4"/><sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>id</t></is></c>
      <c r="B1" t="inlineStr"><is><t>amount</t></is></c>
      <c r="C1" t="inlineStr"><is><t>status</t></is></c>
    </row>
    <row r="2">
      <c r="A2"><v>1</v></c><c r="B2"><v>100</v></c>
      <c r="C2" t="inlineStr"><is><t>completed</t></is></c>
    </row>
    <row r="3">
      <c r="A3"><v>2</v></c><c r="B3"><v>50</v></c>
      <c r="C3" t="inlineStr"><is><t>completed</t></is></c>
    </row>
    <row r="4">
      <c r="A4"><v>3</v></c><c r="B4"><v>25</v></c>
      <c r="C4" t="inlineStr"><is><t>cancelled</t></is></c>
    </row>
  </sheetData>
</worksheet>"""
    entries = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Orders" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": sheet,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return path.read_bytes()


def _xlsx_service(tmp_path: Path, project: Path):
    """Minimal source-task harness over the real admitted-baseline project."""

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
    bindings = private / "source-bindings.json"
    bindings.write_text("{}", encoding="utf-8")
    config = WorkspaceConfig(
        workspace_id="workspace-xlsx-gate",
        external_url="https://workspace.test",
        published_path=tmp_path / "published",
        published_version=None,
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
    state = WorkspaceState(config.state_path)
    contributor = Actor(tenant_id="local", object_id="contributor")
    reviewer = Actor(tenant_id="local", object_id="reviewer")
    for actor in (contributor, reviewer):
        state.create_local_user(actor.object_id)
        state.grant(config.workspace_id, actor)
    state.grant(config.workspace_id, contributor, "contribute")
    state.grant(config.workspace_id, reviewer, "review")
    intake = IntakeService(state, config.operational_root)
    analytics = AnalyticsService(config, state, intake)
    review = ReviewService(
        state,
        workspace_id=config.workspace_id,
        authoring_path=config.authoring_path,
        profile_path=profile,
        private_root=config.operational_root,
        destination=config.published_path,
        analytics=analytics,
    )
    return analytics, review, contributor, reviewer, state, config, intake


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
    assert not authoring_sources.approval_state(project, rejected_sources, rejected_digest).get(
        "approved"
    )
    assert opened == []

    approved = _decide(review, reviewer, source_task)
    assert approved["status"] == "pending_data_grant"
    with pytest.raises(AnalyticsError, match="data authorization"):
        analytics.profile_data_source(contributor, source_task)
    assert opened == []

    real_finish_grant = state.finish_review_task

    def fail_data_grant(workspace_id, task_id, status, response, **kwargs):
        if task_id == source_task and status == "data_granted":
            raise RuntimeError("synthetic interrupted data grant")
        return real_finish_grant(workspace_id, task_id, status, response, **kwargs)

    monkeypatch.setattr(state, "finish_review_task", fail_data_grant)
    with pytest.raises(ReviewError, match="interrupted data grant"):
        _decide(review, reviewer, source_task)
    monkeypatch.setattr(state, "finish_review_task", real_finish_grant)
    assert review.reconcile_task(source_task) is None
    pending_grant = state.get_operation(
        config.workspace_id, contributor, "prepare_data_source", source_task
    )
    assert pending_grant is not None
    assert pending_grant.status == "pending_review"
    assert pending_grant.response["stage"] == "data_grant"

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
    assert len(resolved_commits) == 1
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
        review.decide(reviewer, reused_contribution_task, reused_context.action_digest, "approve")
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

    mismatch = analytics.prepare_data_source(
        contributor,
        retry_key="request-revision-mismatch",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["The expected revision must be checked before profiling."],
    )
    mismatch_task = mismatch["task_id"]
    assert _decide(review, reviewer, mismatch_task)["status"] == "data_granted"
    moved = api.edit_proposal(
        mismatch["native_proposal"],
        mismatch["native_candidate"],
        {"kind": "seed_notes", "content": "# Moved proposal\n"},
    )
    assert moved["revision"] != mismatch["native_candidate"]
    opened.clear()
    with pytest.raises(AnalyticsError, match="stale revision"):
        analytics.profile_data_source(contributor, mismatch_task)
    assert opened == []

    _current, stale_snapshot = admission.resolve_admission(project)
    stale_model = stale_snapshot / "semantic_layer/models/retail_sales.yml"
    original_model = stale_model.read_bytes()
    stale_model.write_bytes(original_model + b"# no longer the admitted bytes\n")
    try:
        fresh = analytics.prepare_data_source(
            contributor,
            retry_key="request-fresh-after-unresolvable-admission",
            project="retail",
            source="orders_sqlite",
            table="entries",
            business_questions=["Stage a fresh Source Approval without opening the old source."],
        )
    finally:
        stale_model.write_bytes(original_model)
    assert fresh["status"] == "pending_source_approval"
    assert fresh["stage"] == "source_approval"
    assert fresh["reused_source_declaration"] is False
    assert opened == []


def test_xlsx_conversion_requires_approved_source_and_caller_grant(tmp_path, monkeypatch):
    """spec0035 §3.1/AC3: workbook interpretation waits for both exact grants.

    Conversion (reading workbook sheets/cells and creating the derived DuckDB
    artifact) must not happen during prepare_data_source or the source-approval
    stage; only authorized profiling after native Source Approval AND the
    caller's separate data grant may interpret. Expected stored values are
    hand-derived from the authored cells and the documented sheet-name
    normalization, never from implementation output."""

    project, _api, _started, _revision = _native_baseline(tmp_path / "baseline")
    analytics, review, contributor, reviewer, _state, config, intake = _xlsx_service(
        tmp_path, project
    )
    import ariadne.spreadsheet_import as spreadsheet_import

    conversion_calls: list[str] = []
    real_import_workbook = spreadsheet_import.import_workbook

    def counting_workbook(source, *, sheets, output):
        conversion_calls.append(str(source))
        return real_import_workbook(source, sheets=sheets, output=output)

    monkeypatch.setattr(spreadsheet_import, "import_workbook", counting_workbook)

    opened: list[list[str]] = []
    real_builder = execution.build_connection

    def spy(registry, **kwargs):
        opened.append([source.path for source in registry.sources])
        return real_builder(registry, **kwargs)

    monkeypatch.setattr(execution, "build_connection", spy)
    monkeypatch.setattr(native_sources, "build_connection", spy)

    workbook_bytes = _write_workbook(tmp_path / "orders.xlsx")
    upload = intake.save(
        config.workspace_id,
        contributor,
        "orders-workbook",
        "orders.xlsx",
        "xlsx-upload-one",
        workbook_bytes,
    )
    prepared = analytics.prepare_data_source(
        contributor,
        retry_key="xlsx-request-one",
        project="retail",
        source="orders-workbook",
        table="orders",
        business_questions=["Which orders count as completed revenue?"],
        upload_id=upload["upload_id"],
        sheets=["Orders"],
    )
    source_task = prepared["task_id"]
    # Preparation stages the declaration without workbook interpretation or a
    # derived artifact: only retained-byte facts and the explicit selection.
    assert prepared["status"] == "pending_source_approval"
    assert conversion_calls == []
    assert not (project / ".ariadne" / "managed-sources").exists()
    staged = prepared["conversion"][0]
    assert staged["conversion_status"] == "staged_pending_approval"
    assert staged["selected_sheets"] == ["Orders"]
    assert staged["source_type"] == "xlsx"
    assert staged["sha256"] == hashlib.sha256(workbook_bytes).hexdigest()
    assert "artifact_sha256" not in staged
    assert "sheets" not in staged
    declaration = prepared["native_entries"][0]
    assert declaration["type"] == "duckdb"
    declared_path = PurePosixPath(declaration["path"])
    assert declared_path.parts[-1] == "data.duckdb"
    assert declared_path.parts[-2] == staged["selection_identity"]
    assert declared_path.parts[-3] == "workbook"

    with pytest.raises(AnalyticsError, match="Source Approval"):
        analytics.profile_data_source(contributor, source_task)
    assert conversion_calls == []
    assert opened == []

    approved = _decide(review, reviewer, source_task)
    assert approved["status"] == "pending_data_grant"
    with pytest.raises(AnalyticsError, match="data authorization"):
        analytics.profile_data_source(contributor, source_task)
    assert conversion_calls == []
    assert opened == []

    granted = _decide(review, reviewer, source_task)
    assert granted["status"] == "data_granted"
    try:
        profiled = analytics.profile_data_source(contributor, source_task)
    except AnalyticsError as exc:
        # The designated shared runtime lacks the optional ariadne-data[spreadsheets]
        # extra (openpyxl): the authorized conversion truthfully discloses that and
        # opens no backend instead of substituting invented rows. The stored-value
        # assertions in the other branch need that optional extra in the runtime.
        assert "ariadne-data[spreadsheets]" in str(exc)
    else:
        sources = {source["name"]: source for source in profiled["profile"]["sources"]}
        orders = sources[prepared["native_source"]]["tables"]["orders"]
        # Authored cells: (1, 100, completed), (2, 50, completed), (3, 25, cancelled).
        # The public stored row-lineage column keeps original worksheet row numbers.
        assert orders["row_count"] == 3
        columns = {name: column["type"] for name, column in orders["columns"].items()}
        assert columns == {
            "__ariadne_source_row": "BIGINT",
            "id": "BIGINT",
            "amount": "BIGINT",
            "status": "VARCHAR",
        }
        # Read the derived artifact identified by the approved declaration,
        # read-only: stored values stay the authored cells with their original
        # worksheet rows (header row 1; lineage column pinned by Core's own
        # test_workbook_stored_values_and_refresh_are_truthful oracle).
        stored = analytics.get(contributor, source_task)
        artifact = project / stored["conversion"][0]["derived_source"]["registry_path"]
        connection = duckdb.connect(str(artifact), read_only=True)
        try:
            artifact_rows = connection.execute(
                "SELECT __ariadne_source_row, id, amount, status FROM \"orders\" "
                "ORDER BY __ariadne_source_row"
            ).fetchall()
        finally:
            connection.close()
        assert artifact_rows == [
            (2, 1, 100, "completed"),
            (3, 2, 50, "completed"),
            (4, 3, 25, "cancelled"),
        ]
        assert opened
        # Same-input retry reuses the verified artifact without a second conversion.
        again = analytics.profile_data_source(contributor, source_task)
        assert again["profile"] == profiled["profile"]
        assert stored["conversion"][0]["conversion_status"] == "converted_authorized"
    assert len(conversion_calls) == 1


def test_knowledge_only_contribution_needs_no_data_grant(tmp_path, monkeypatch):
    """AC12/spec0035 §2: with analytics configured, a knowledge contributor
    without an unrelated analytics data grant submits an authored runbook
    through the native knowledge route; a separate human publishes it; no
    analytical connection opens and the prior Bound Release stays unchanged.
    An executable/Core-edit variant cannot take the knowledge-only route, and
    the integrated context refuses the standalone retention waiver before any
    conversion or private-store setup (spec0034 §12.4)."""

    project, api, _started, _revision = _native_baseline(tmp_path / "baseline")
    # The fixture's own admitted baseline gains a 'procedures' routing entry
    # so the runbook routes honestly; the shared CONTROL stays untouched.
    control = project / "knowledge" / "lumio.yaml"
    control.write_text(
        CONTROL.replace(
            "categories:\n  - name: policies\n  - name: metrics\n",
            "categories:\n  - name: policies\n  - name: metrics\n  - name: procedures\n",
        ).replace(
            "ontology:\n  entity_types:\n    policy: {}\n    metric: {}\n",
            "ontology:\n  entity_types:\n    policy: {}\n    metric: {}\n"
            "    knowledge-artifact:\n      description: \"A document, record, or other knowledge "
            "artifact. Its referent is the artifact itself, not a person, organization, "
            "service, or business object mentioned in it.\"\n"
            "  predicates:\n    documented-by:\n"
            "      subject_types:\n        - knowledge-artifact\n",
        ),
        encoding="utf-8",
    )
    _git(project, "add", "knowledge/lumio.yaml")
    _git(project, "commit", "-q", "-m", "fixture: procedures category")
    proposal = api.start_proposal()
    resolved, digest = authoring_sources.candidate_sources(project, proposal["candidate_revision"])
    assert resolved is not None and digest is not None
    api.approve_sources(proposal["proposal"], proposal["candidate_revision"], digest)
    validated = api.validate_proposal(proposal["proposal"], proposal["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    native_review = api.review_proposal(proposal["proposal"])
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
        proposal["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        destination=destination,
        expected_current="none",
        private_profile=profile,
        scope=("internal",),
    )
    admission.admit_revision(
        project,
        proposal["proposal"],
        native_review["revision"],
        native_review["review_digest"],
        confirmed_by="human:synthetic-baseline-owner",
        overall_preview=overall,
        confirmed_overall_digest=overall["digest"],
        private_profile=profile,
    )
    admitted_before = admission.load_current(project)
    assert admitted_before is not None
    bound_release_commit = admitted_before["commit"]

    bindings = private / "source-bindings.json"
    bindings.write_text("{}", encoding="utf-8")
    config = WorkspaceConfig(
        workspace_id="workspace-knowledge-only",
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
    state = WorkspaceState(config.state_path)
    contributor = Actor(tenant_id="local", object_id="contributor")
    reviewer = Actor(tenant_id="local", object_id="reviewer")
    owner = Actor(tenant_id="local", object_id="owner")
    for actor in (contributor, reviewer, owner):
        state.create_local_user(actor.object_id)
        state.grant(config.workspace_id, actor)
    state.grant(config.workspace_id, contributor, "contribute")
    state.grant(config.workspace_id, reviewer, "review")
    state.grant(config.workspace_id, owner, "setup")
    attachment = current_attachment_digest(target=config.authoring_path, profile_path=profile)
    state.record_setup(
        config.workspace_id,
        owner,
        "synthetic-knowledge-setup",
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
    expires = 1_800_000_000
    contributor_token = state.issue_local_credential("contributor", "api", expires_at=expires)[1]

    opened: list[list[str]] = []
    real_builder = execution.build_connection

    def spy(registry_arg, **kwargs):
        opened.append([source.path for source in registry_arg.sources])
        return real_builder(registry_arg, **kwargs)

    monkeypatch.setattr(execution, "build_connection", spy)
    monkeypatch.setattr(native_sources, "build_connection", spy)

    def call_contribution(http_client, token: str, arguments: dict) -> dict:
        response = http_client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "prepare_contribution", "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    runbook_original = (
        b"# Team Runbook\n\nDeploy the retail report: open the dashboard, filter to "
        b"completed orders, export EUR revenue.\n"
    )
    upload = intake.save(
        config.workspace_id,
        contributor,
        "team-runbook-original",
        "team-runbook.md",
        "runbook-upload-one",
        runbook_original,
    )
    runbook_page = (
        "---\n"
        "id: entity:team-runbook\n"
        "title: Team Runbook\n"
        "entity_types: [knowledge-artifact]\n"
        "tags: [operations]\n"
        "summary: How the retail report is produced and shared.\n"
        "category: procedures\n"
        "type: runbook\n"
        "durability_rationale: Report production steps stay binding until tooling changes.\n"
        "lifecycle: approved\n"
        "visibility: internal\n"
        "sources:\n  - id: team-runbook-original\n    title: Team runbook original\n"
        "---\n\n"
        "# Team Runbook\n\nProduce the retail report from the dashboard.\n\n"
        "Cancelled orders never enter the report: see [[Cancelled Orders]].\n"
        "Where this fits: [[Team Report Overview]].\n"
    )
    overview_page = (
        "---\n"
        "id: entity:team-report-overview\n"
        "title: Team Report Overview\n"
        "entity_types: [knowledge-artifact]\n"
        "tags: [operations]\n"
        "summary: Where the recurring retail report production is documented.\n"
        "category: procedures\n"
        "type: overview\n"
        "durability_rationale: Teams keep navigating to the production steps.\n"
        "lifecycle: approved\n"
        "visibility: internal\n"
        "synthetic: true\n"
        "claims:\n"
        "  - id: claim:team-report-overview-runbook\n"
        "    predicate: documented-by\n"
        "    status: accepted\n"
        "    object: entity:team-runbook\n"
        "    evidence:\n      - section: Overview\n"
        "---\n\n"
        "# Team Report Overview\n\n## Overview\n\nThe production steps: [[Team Runbook]].\n"
    )

    app = create_app(config)
    with TestClient(app, base_url="https://workspace.test") as client:
        # Knowledge-only request: no source task, no Core edits. Analytics is
        # configured, but an unrelated data grant must not be required.
        result = call_contribution(
            client,
            contributor_token,
            {
                "retry_key": "knowledge-only-runbook-one",
                "sources": [{"upload_id": upload["upload_id"], "intent": "new"}],
                "pages": [
                    {"filename": "team-runbook.md", "markdown": runbook_page},
                    {"filename": "team-report-overview.md", "markdown": overview_page},
                ],
            },
        )
        assert result["isError"] is False, result
        prepared = result["structuredContent"]
        assert prepared["status"] == "pending_review"
        assert prepared["native_base"] == native_review["revision"]
        assert "native_proposal" not in prepared
        task_id = prepared["task_id"]

        # A different human approves and natively publishes the candidate.
        context = review.get(reviewer, task_id)
        published = review.decide(reviewer, task_id, context.action_digest, "approve")
        assert published["status"] == "published"
        assert published["publication_outcome"] == "activated"

        published_pages = list(destination.rglob("team_runbook.md"))
        assert published_pages, "the runbook page is missing from the published tree"
        assert "Produce the retail report" in published_pages[0].read_text(encoding="utf-8")

        # No analytical connection ever opened.
        assert opened == []
        # The prior Core admission is byte/state unchanged; no blank release.
        admitted_after = admission.load_current(project)
        assert admitted_after is not None
        assert admitted_after["commit"] == bound_release_commit

        # An executable edit cannot ride the knowledge-only route: it keeps
        # the analytics grant route and is refused without an exact grant.
        refused = call_contribution(
            client,
            contributor_token,
            {
                "retry_key": "executable-variant-one",
                "sources": [{"upload_id": upload["upload_id"], "intent": "new"}],
                "pages": [{"filename": "team-runbook.md", "markdown": runbook_page}],
                "core_edits": [{"kind": "model", "name": "retail_sales", "content": MODEL}],
            },
        )
        assert refused["isError"] is True
        assert refused["content"][0]["text"].endswith(
            "integrated analytics contribution requires an exact source-task grant"
        )
        assert (
            state.get_operation(
                config.workspace_id,
                contributor,
                "prepare_contribution",
                "executable-variant-one",
            )
            is None
        )

    # The same integrated context refuses the standalone retention waiver
    # BEFORE any conversion, upload processing, or private-store setup.
    guard_private = tmp_path / "guard-private"
    guard_profile = guard_private / "profile.json"
    guard_profile.parent.mkdir(parents=True)
    guard_profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(guard_private / "registry"),
                "retention": "disabled",
                "artifact_store": {"kind": "local", "root": str(guard_private / "artifacts")},
            }
        ),
        encoding="utf-8",
    )
    guard_bindings = guard_private / "source-bindings.json"
    guard_bindings.write_text("{}", encoding="utf-8")
    guard_config = WorkspaceConfig(
        workspace_id="workspace-knowledge-guard",
        external_url="https://workspace.test",
        published_path=tmp_path / "published-guard",
        published_version=None,
        state_path=tmp_path / "guard-state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=project / "knowledge",
        private_profile_path=guard_profile,
        private_root=tmp_path / "guard-operations",
        namespace=NAMESPACE,
        analytics_project_id="retail",
        analytics_project_path=project,
        analytics_source_bindings_path=guard_bindings,
    )
    guard_state = WorkspaceState(guard_config.state_path)
    guard_contributor = Actor(tenant_id="local", object_id="contributor")
    guard_owner = Actor(tenant_id="local", object_id="owner")
    for actor in (guard_contributor, guard_owner):
        guard_state.create_local_user(actor.object_id)
        guard_state.grant(guard_config.workspace_id, actor)
    guard_state.grant(guard_config.workspace_id, guard_contributor, "contribute")
    guard_state.grant(guard_config.workspace_id, guard_owner, "setup")
    guard_attachment = current_attachment_digest(
        target=guard_config.authoring_path, profile_path=guard_profile
    )
    guard_state.record_setup(
        guard_config.workspace_id,
        guard_owner,
        "synthetic-guard-setup",
        kind="existing",
        target=guard_config.authoring_path,
        namespace=NAMESPACE,
        base_revision=native_review["revision"],
        attachment_digest=guard_attachment,
    )
    guard_token = guard_state.issue_local_credential("contributor", "api", expires_at=expires)[1]
    guard_app = create_app(guard_config)
    with TestClient(guard_app, base_url="https://workspace.test") as guard_client:
        guard_result = call_contribution(
            guard_client,
            guard_token,
            {
                "retry_key": "retention-guard-one",
                "sources": [{"upload_id": "never-loaded-upload", "intent": "new"}],
                "pages": [{"filename": "team-runbook.md", "markdown": runbook_page}],
            },
        )
        assert guard_result["isError"] is True
        assert "standalone-only exception" in guard_result["content"][0]["text"]
        # The guard fired before any upload load/conversion or store setup.
        assert not (guard_private / "artifacts").exists()
        assert not (guard_private / "registry").exists()
        assert not (guard_config.operational_root / "extractions").exists()
        assert (
            guard_state.get_operation(
                guard_config.workspace_id,
                guard_contributor,
                "prepare_contribution",
                "retention-guard-one",
            )
            is None
        )
    assert opened == []
