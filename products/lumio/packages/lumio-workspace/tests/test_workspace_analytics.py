"""D1/VD1: exact source grants, combined review, and a pinned native SQLite query."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path, PurePosixPath
from threading import Barrier, BrokenBarrierError

import duckdb
import pytest
from ariadne import admission, authoring_edits, authoring_sources, draft, execution, proposals
from ariadne import sources as native_sources
from ariadne.authoring import AuthoringProject
from lumio_wiki.artifact_store import LocalDirectoryArtifactStore, retain_artifact
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry
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
  - name: computations
ontology:
  entity_types:
    policy: {}
    metric: {}
    computation: {}
"""
SELECTOR = """version: 1
mode: integrated
subtree: knowledge
namespace: urn:demo:retail
profile: ariadne-context/1
support_revision: 2
policy_bindings:
  version: 1
  bindings:
    - subject: {kind: metric, identity: retail_sales::orders.revenue}
      policy: {namespace: urn:demo:retail, entity_id: entity:retail-return-policy}
      operations: [get_metric, query_metrics]
      enforcement: null
    - subject: {kind: metric, identity: retail_sales::orders.revenue}
      policy: {namespace: urn:demo:retail, entity_id: entity:cancelled-orders}
      operations: [get_metric, query_metrics]
      enforcement: null
"""
MODEL = """version: 0.3.0.dev0
name: retail_sales
description: Orders model
datasets:
- name: orders
  source: orders.main.orders
  primary_key:
  - id
  fields:
  - name: id
    expression:
      sql: id
  - name: amount
    expression:
      sql: amount
  - name: status
    expression:
      sql: status
    dimension: {}
  metrics:
  - name: revenue
    expression:
      sql: SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)
    description: Completed revenue in EUR
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
    metric: orders.revenue
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


MODEL_SOURCE = "model-retail_sales"
COMPUTATION_ENTITY = "entity:retail-sales-orders-revenue-computation"
MODEL_DIGEST = hashlib.sha256(MODEL.encode("utf-8")).hexdigest()


def _retain_model(profile: Path) -> None:
    """Register and retain the model original in the profile's registry/store."""
    settings = json.loads(profile.read_text(encoding="utf-8"))
    registry = SourceRegistry(Path(settings["source_registry"]))
    registry.register_version(MODEL_SOURCE, MODEL.encode("utf-8"))
    store = LocalDirectoryArtifactStore(Path(settings["artifact_store"]["root"]))
    retained = retain_artifact(
        store,
        registry,
        source_id=MODEL_SOURCE,
        raw_bytes=MODEL.encode("utf-8"),
        content_type="text/plain",
        filename=f"{MODEL_SOURCE}.txt",
    )
    assert retained == MODEL_DIGEST


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
    # The Core-generated Computation cites the OSI model; integrated retention
    # requires that original bound here and retained (see _retain_model).
    manifest.write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={MODEL_SOURCE: "active"},
                bindings={COMPUTATION_ENTITY: {MODEL_SOURCE: MODEL_DIGEST}},
            )
        )
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
    authoring_sources.grant_candidate(
        project,
        started["proposal"],
        started["candidate_revision"],
        digest,
        by="human:test-operator",
    )
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


@pytest.mark.parametrize(
    "lifecycle_case",
    [
        "journey",
        "joiner_reject",
        "busy_reuse",
        "creator_submission",
        "creator_publication",
        "creator_rebased",
        "creator_interrupted",
        "creator_reconnect",
        "concurrent_claim",
        "failed_joined_contribution",
        "failed_stale_grant",
        "failed_invalid_edit",
        "failed_cleanup_interrupted",
        "failed_moved_candidate",
    ],
)
def test_source_grant_and_combined_review_gate_pinned_query(tmp_path, monkeypatch, lifecycle_case):
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
    _retain_model(profile)
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

    rejected = analytics.prepare_data_source(
        contributor,
        retry_key="request-rejected-sqlite",
        project="retail",
        source="orders_sqlite",
        table="entries",
        business_questions=["This declaration must not be approved by a rejected task."],
    )
    with pytest.raises(AnalyticsError, match="stale"):  # one active draft until decided
        analytics.prepare_data_source(
            contributor,
            retry_key="request-concurrent-sqlite",
            project="retail",
            source="orders_sqlite",
            table="entries",
            business_questions=["A concurrent request is refused while one is pending."],
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

    if lifecycle_case == "concurrent_claim":
        before = draft.status(project)
        barrier = Barrier(2)
        joined = AnalyticsService._joined_draft

        def overlap(self, *args, **kwargs):
            result = joined(self, *args, **kwargs)
            try:
                barrier.wait(timeout=3)
            except BrokenBarrierError:
                pass  # A serialized claimant can finish before the other enters.
            return result

        monkeypatch.setattr(AnalyticsService, "_joined_draft", overlap)
        token = state.issue_local_credential("contributor", "api", expires_at=1_800_000_000)[1]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }

        def call(key):
            with TestClient(create_app(config), base_url="https://workspace.test") as client:
                response = client.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "prepare_data_source",
                            "arguments": {
                                "retry_key": key,
                                "project": "retail",
                                "source": "orders_sqlite",
                                "table": "entries",
                                "business_questions": ["Same draft?"],
                            },
                        },
                    },
                )
                assert response.status_code == 200, response.text
                return response.json()["result"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(call, ["events-B", "events-C"]))
        successes = [result for result in results if not result["isError"]]
        failures = [result for result in results if result["isError"]]
        assert len(successes) == len(failures) == 1, results
        assert successes[0]["structuredContent"]["status"] == "pending_source_approval"
        review.get(reviewer, successes[0]["structuredContent"]["task_id"])
        assert "stale" in json.dumps(failures[0]).lower()
        assert draft.status(project) == before
        winner = "events-B" if results[0] is successes[0] else "events-C"
        replay = call(winner)
        assert (
            replay["structuredContent"]["task_id"] == (successes[0]["structuredContent"]["task_id"])
        )
        return

    # Draft rule v3: the granted draft is idle, but a request adding a declaration
    # that is not in it refuses as stale instead of joining.
    with pytest.raises(AnalyticsError, match="stale"):
        analytics.prepare_data_source(
            contributor,
            retry_key="request-adds-private",
            project="retail",
            source="private",
            table="entries",
            business_questions=["A new declaration cannot join granted work."],
        )

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
    if lifecycle_case == "failed_joined_contribution":
        before = draft.status(project)
        assert before is not None
        with pytest.raises(AnalyticsError):
            analytics.prepare_contribution(
                contributor,
                retry_key="failed-joined-contribution",
                source_task_id=source_task,
                sources=[{"upload_id": uploaded["upload_id"], "intent": "new"}],
                pages=[{"filename": "cancelled-orders.md", "markdown": WORKSPACE_POLICY}],
                core_edits=[{"kind": "invalid-edit-kind"}],
            )
        assert draft.status(project) == before

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
    if lifecycle_case == "failed_joined_contribution":
        review.get(reviewer, contribution_task)
        return
    if lifecycle_case == "joiner_reject":
        before = draft.status(project)
        context = review.get(reviewer, contribution_task)
        rejected = review.decide(reviewer, contribution_task, context.action_digest, "reject")
        assert rejected["status"] == "rejected"
        assert draft.status(project) == before
        return
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
    failed_cases = {
        "failed_stale_grant",
        "failed_invalid_edit",
        "failed_cleanup_interrupted",
        "failed_moved_candidate",
    }
    if lifecycle_case in failed_cases:
        assert draft.status(project) is None
        original_bindings = bindings.read_text(encoding="utf-8")
        if lifecycle_case == "failed_stale_grant":
            bindings.write_text(
                original_bindings.replace('"name": "orders_sqlite"', '"name": "new_orders"'),
                encoding="utf-8",
            )
        failing = {
            "retry_key": f"{lifecycle_case}-first",
            "source_task_id": reused_task,
            "sources": [{"upload_id": reused_upload["upload_id"], "intent": "update"}],
            "pages": [{"filename": "cancelled-orders.md", "markdown": WORKSPACE_POLICY}],
            "core_edits": [
                {"kind": "model", "name": "retail_sales", "content": changed_model}
                if lifecycle_case == "failed_stale_grant"
                else {"kind": "invalid-edit-kind"}
            ],
        }
        error = (
            "Source Approval|data authorization"
            if lifecycle_case == "failed_stale_grant"
            else "invalid-edit-kind"
        )
        if lifecycle_case == "failed_moved_candidate":
            # An operator's `ariadne draft edit` (Core's lock, not the workspace
            # project lock) advances the candidate while the prepare is in flight
            # (§3.7 rules 2-3): the cleanup must leave that edited draft active.
            real_edit = AuthoringProject.edit_proposal
            moved = {}

            def operator_edit_first(self, proposal, revision, edit):
                active = draft.status(project)
                assert active is not None
                operator_model = changed_model + "# operator edit\n"
                rel, _ = authoring_edits.resolve_edit(
                    {"kind": "model", "name": "retail_sales", "content": operator_model},
                    project=project,
                    proposal=proposal,
                )
                draft.edit_artifact(
                    project,
                    (active["generation"], active["candidate_revision"]),
                    rel,
                    operator_model,
                )
                moved["before"] = active["candidate_revision"]
                moved["status"] = draft.status(project)
                return real_edit(self, proposal, revision, edit)

            monkeypatch.setattr(AuthoringProject, "edit_proposal", operator_edit_first)
            with pytest.raises(AnalyticsError, match=error):
                analytics.prepare_contribution(contributor, **failing)
            assert moved["status"]["candidate_revision"] != moved["before"]
            assert draft.status(project) == moved["status"]
            return
        if lifecycle_case == "failed_cleanup_interrupted":
            # The worker stops at the cleanup boundary, before the terminal failure is
            # recorded (spec 0034 §10): reconnecting must not need an operator discard.
            real_finish_operation = state.finish_operation

            def fail_failed(workspace_id, actor, operation, status, response):
                if status == "failed":
                    raise RuntimeError("synthetic failure-bookkeeping crash")
                return real_finish_operation(workspace_id, actor, operation, status, response)

            real_discard = draft.discard

            def fail_discard(*args, **kwargs):
                raise RuntimeError("synthetic crash before the slot release")

            # First stop: inside the release itself, so the slot is still claimed and
            # only the persisted creator pin can finish the cleanup on replay.
            monkeypatch.setattr(draft, "discard", fail_discard)
            with pytest.raises(RuntimeError, match="before the slot release"):
                analytics.prepare_contribution(contributor, **failing)
            monkeypatch.setattr(draft, "discard", real_discard)
            assert draft.status(project) is not None
            # Second stop (same-key replay): after the release, before the failure row.
            monkeypatch.setattr(state, "finish_operation", fail_failed)
            with pytest.raises(RuntimeError, match="failure-bookkeeping crash"):
                analytics.prepare_contribution(contributor, **failing)
            monkeypatch.setattr(state, "finish_operation", real_finish_operation)
            assert draft.status(project) is None
        try:
            with pytest.raises(AnalyticsError, match=error):
                analytics.prepare_contribution(contributor, **failing)
        finally:
            bindings.write_text(original_bindings, encoding="utf-8")
        assert draft.status(project) is None

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
    if lifecycle_case in failed_cases:
        assert reused_candidate["status"] == "pending_submission"
        review.get(reviewer, reused_contribution_task)
        return
    if lifecycle_case == "busy_reuse":
        with pytest.raises(AnalyticsError, match="stale"):
            analytics.prepare_data_source(
                contributor,
                retry_key="reuse-while-contribution-pending",
                project="retail",
                source="orders_sqlite",
                table="entries",
                business_questions=["Still busy?"],
            )
        return
    if lifecycle_case == "creator_rebased":
        # A rebase keeps the proposal and may keep HEAD but opens a new generation the
        # reject never reviewed (spec 0040 §3.3, §3.7 rule 4): the draft survives.
        slot = draft._load_slot(Path(project))
        assert slot is not None
        draft._store_slot(Path(project), {**slot, "generation": slot["generation"] + 1})
        moved = draft.status(project)
        context = review.get(reviewer, reused_contribution_task)
        rejected = review.decide(
            reviewer, reused_contribution_task, context.action_digest, "reject"
        )
        assert rejected["status"] == "rejected"
        assert draft.status(project) == moved
        return
    if lifecycle_case in {"creator_interrupted", "creator_reconnect"}:
        # The worker stops after the discard but before the outcome commits (spec 0034
        # §10): reconciling finishes the one-use reject from its pinned evidence.
        real_finish_reject = state.finish_review_task
        real_discard = draft.discard
        discards = []

        def discard_spy(*args, **kwargs):
            discards.append(args)
            return real_discard(*args, **kwargs)

        def fail_rejected(workspace_id, task_id, status, response, **kwargs):
            if task_id == reused_contribution_task and status == "rejected":
                raise RuntimeError("synthetic post-discard bookkeeping failure")
            return real_finish_reject(workspace_id, task_id, status, response, **kwargs)

        monkeypatch.setattr(draft, "discard", discard_spy)
        monkeypatch.setattr(state, "finish_review_task", fail_rejected)
        context = review.get(reviewer, reused_contribution_task)
        with pytest.raises(ReviewError, match="post-discard bookkeeping failure"):
            review.decide(reviewer, reused_contribution_task, context.action_digest, "reject")
        monkeypatch.setattr(state, "finish_review_task", real_finish_reject)
        # A later slot whose admission activated but was never retired (interrupted):
        # reconciling the old reject must not run Core recovery on it.
        retired = draft._load_slot(Path(project))
        assert retired is not None and retired["state"] == "retired"
        served = admission.load_current(project)
        assert served is not None
        later = {
            "state": "active",
            "generation": retired["generation"] + 1,
            "proposal": served["proposal"],
            "candidate_revision": served["commit"],
            "base_served_revision": served["commit"],
        }
        draft._store_slot(Path(project), later)
        if lifecycle_case == "creator_reconnect":
            # The contributor reconnects and polls over MCP: the stored pending_review
            # row, not the overlaid pending_submission, triggers the recovery.
            token = state.issue_local_credential("contributor", "api", expires_at=1_800_000_000)[1]
            with TestClient(create_app(config), base_url="https://workspace.test") as client:
                response = client.post(
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
                        "params": {
                            "name": "get_task",
                            "arguments": {"task_id": reused_contribution_task},
                        },
                    },
                )
            assert response.status_code == 200, response.text
            polled = response.json()["result"]
            assert not polled["isError"], polled
            assert polled["structuredContent"]["status"] == "rejected"
            assert draft._load_slot(Path(project)) == later
            assert len(discards) == 1
            return
        recovered = review.reconcile_task(reused_contribution_task)
        assert draft._load_slot(Path(project)) == later
        assert recovered is not None and recovered["status"] == "rejected"
        assert analytics.get(contributor, reused_contribution_task)["status"] == "rejected"
        assert draft.status(project) is None
        assert len(discards) == 1
        return
    if lifecycle_case in {"creator_submission", "creator_publication"}:
        admitted_before = admission.load_current(project)
        assert draft.status(project) is not None
        if lifecycle_case == "creator_publication":
            submitted = _decide(review, reviewer, reused_contribution_task)
            assert submitted["status"] == "pending_publication"
        context = review.get(reviewer, reused_contribution_task)
        rejected = review.decide(
            reviewer, reused_contribution_task, context.action_digest, "reject"
        )
        assert rejected["status"] == "rejected"
        assert draft.status(project) is None
        assert admission.load_current(project) == admitted_before
        fresh = analytics.prepare_data_source(
            contributor,
            retry_key="reuse-after-reject",
            project="retail",
            source="orders_sqlite",
            table="entries",
            business_questions=["Reuse after rejection?"],
        )
        assert fresh["status"] == "pending_data_grant"
        assert draft.status(project) is None
        return
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
    # A reused admitted declaration holds no draft, so the only way its recorded
    # candidate moves is a changed proposal record: move it to a real new revision.
    opened_draft = api.start_proposal()
    moved = api.edit_proposal(
        opened_draft["proposal"],
        opened_draft["candidate_revision"],
        {"kind": "seed_notes", "content": "# Moved proposal\n"},
    )
    assert moved["revision"] != mismatch["native_candidate"]
    draft.discard(
        project, draft.active_expected(project, opened_draft["proposal"], moved["revision"])
    )
    record = proposals._load_record(project.resolve(), mismatch["native_proposal"])
    proposals._store_record(project.resolve(), {**record, "candidate_revision": moved["revision"]})
    opened.clear()
    with pytest.raises(AnalyticsError, match="stale revision"):
        analytics.profile_data_source(contributor, mismatch_task)
    proposals._store_record(project.resolve(), record)
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
    draft.discard(project, draft.active_expected(project, _started["proposal"], _revision))
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
                'SELECT __ariadne_source_row, id, amount, status FROM "orders" '
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
    draft.discard(project, draft.active_expected(project, _started["proposal"], _revision))
    # The fixture's own admitted baseline gains a 'procedures' routing entry
    # so the runbook routes honestly; the shared CONTROL stays untouched.
    control = project / "knowledge" / "lumio.yaml"
    control.write_text(
        CONTROL.replace(
            "  - name: metrics\n",
            "  - name: metrics\n  - name: procedures\n",
        ).replace(
            "    computation: {}\n",
            "    computation: {}\n"
            '    knowledge-artifact:\n      description: "A document, record, or other knowledge '
            "artifact. Its referent is the artifact itself, not a person, organization, "
            'service, or business object mentioned in it."\n'
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
    authoring_sources.grant_candidate(
        project,
        proposal["proposal"],
        proposal["candidate_revision"],
        digest,
        by="human:test-operator",
    )
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
    _retain_model(profile)
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


def test_verbatim_contribution_preserves_exact_converted_body(tmp_path, monkeypatch):
    """AC5/spec0010 §3.1: explicit verbatim documents publish their exact
    converted bodies — leading/trailing blank lines, LF/CRLF form and literal
    page-break markers inside fenced code — while the distilled default stays
    unchanged; mismatch, incomplete extraction and ambiguous binding refuse
    without a partial authored candidate."""

    from lumio_wiki.authoring_journey import AuthoringJourneyError, load_candidate_request

    project, api, _started, _revision = _native_baseline(tmp_path / "baseline")
    draft.discard(project, draft.active_expected(project, _started["proposal"], _revision))
    control = project / "knowledge" / "lumio.yaml"
    control.write_text(
        CONTROL.replace(
            "  - name: metrics\n",
            "  - name: metrics\n  - name: procedures\n",
        ).replace(
            "    computation: {}\n",
            "    computation: {}\n"
            '    knowledge-artifact:\n      description: "A document, record, or other knowledge '
            "artifact. Its referent is the artifact itself, not a person, organization, "
            'service, or business object mentioned in it."\n',
        ),
        encoding="utf-8",
    )
    _git(project, "add", "knowledge/lumio.yaml")
    _git(project, "commit", "-q", "-m", "fixture: procedures category")
    proposal = api.start_proposal()
    resolved, digest = authoring_sources.candidate_sources(project, proposal["candidate_revision"])
    assert resolved is not None and digest is not None
    authoring_sources.grant_candidate(
        project,
        proposal["proposal"],
        proposal["candidate_revision"],
        digest,
        by="human:test-operator",
    )
    validated = api.validate_proposal(proposal["proposal"], proposal["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    native_review = api.review_proposal(proposal["proposal"])
    destination = tmp_path / "published"
    private = tmp_path / "private"
    (private / "registry").mkdir(parents=True)
    (private / "artifacts").mkdir()
    profile = private / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(private / "registry"),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(private / "artifacts")},
            }
        ),
        encoding="utf-8",
    )
    _retain_model(profile)
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
        workspace_id="workspace-verbatim",
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
    assert config.authoring_path is not None and config.private_profile_path is not None
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
        "synthetic-verbatim-setup",
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

    def call_contribution(http_client, token, arguments):
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

    # Independently authored originals: leading/trailing blank lines, a literal
    # page-break marker inside a fenced code block, and a CRLF document.
    doc_lf_text = (
        "\n\nRunbook with an exact body.\n\n```text\n"
        "<!-- lumio: page-break -->\n```\n\nTrailing example.\n\n"
    )
    doc_crlf_text = "Windows runbook.\r\n\r\nSecond line.\r\n\r\n"
    upload_lf = intake.save(
        config.workspace_id,
        contributor,
        "verbatim-lf",
        "verbatim-lf.md",
        "verbatim-upload-lf",
        doc_lf_text.encode("utf-8"),
    )
    upload_crlf = intake.save(
        config.workspace_id,
        contributor,
        "verbatim-crlf",
        "verbatim-crlf.md",
        "verbatim-upload-crlf",
        doc_crlf_text.encode("utf-8"),
    )

    def verbatim_page(entity_id, title, source_id, text, extra_sources=""):
        return (
            "---\n"
            f"id: {entity_id}\n"
            f"title: {title}\n"
            "entity_types: [knowledge-artifact]\n"
            "tags: [operations]\n"
            "summary: Exact verbatim conversion.\n"
            "category: procedures\n"
            "type: runbook\n"
            "durability_rationale: Exact converted bodies stay binding.\n"
            "lifecycle: approved\n"
            "visibility: internal\n"
            f"sources:\n  - id: {source_id}\n    title: {source_id} original\n"
            f"{extra_sources}"
            "---\n" + text
        )

    lf_page = verbatim_page("entity:verbatim-lf", "Verbatim LF Runbook", "verbatim-lf", doc_lf_text)
    crlf_page = verbatim_page(
        "entity:verbatim-crlf", "Verbatim CRLF Runbook", "verbatim-crlf", doc_crlf_text
    )

    # The strict public JSON loader learns the new optional fields (validated
    # after the managed journey below so the failing-first red surfaces the
    # actual body mangling first, not only the missing loader contract).

    app = create_app(config)
    with TestClient(app, base_url="https://workspace.test") as client:
        # Body mismatch: the authored body differs from the actual native
        # extraction record text — refuse before any operation is created.
        mismatch_upload = intake.save(
            config.workspace_id,
            contributor,
            "verbatim-mismatch",
            "verbatim-mismatch.md",
            "verbatim-upload-mismatch",
            doc_lf_text.encode("utf-8"),
        )
        mismatch_page = verbatim_page(
            "entity:verbatim-mismatch",
            "Verbatim Mismatch",
            "verbatim-mismatch",
            doc_lf_text + "tampered\n",
        )
        mismatch = call_contribution(
            client,
            contributor_token,
            {
                "retry_key": "verbatim-mismatch-one",
                "sources": [
                    {"upload_id": mismatch_upload["upload_id"], "intent": "new", "verbatim": True}
                ],
                "pages": [{"filename": "verbatim-mismatch.md", "markdown": mismatch_page}],
            },
        )
        assert mismatch["isError"] is True
        assert (
            state.get_operation(
                config.workspace_id, contributor, "prepare_contribution", "verbatim-mismatch-one"
            )
            is None
        )

        # Incomplete (bounded) extraction refuses verbatim intake entirely.
        huge_text = "A" * 201_000
        huge_upload = intake.save(
            config.workspace_id,
            contributor,
            "verbatim-huge",
            "verbatim-huge.md",
            "verbatim-upload-huge",
            huge_text.encode("utf-8"),
        )
        huge_page = verbatim_page(
            "entity:verbatim-huge", "Verbatim Huge", "verbatim-huge", huge_text
        )
        huge = call_contribution(
            client,
            contributor_token,
            {
                "retry_key": "verbatim-huge-one",
                "sources": [
                    {"upload_id": huge_upload["upload_id"], "intent": "new", "verbatim": True}
                ],
                "pages": [{"filename": "verbatim-huge.md", "markdown": huge_page}],
            },
        )
        assert huge["isError"] is True
        assert (
            state.get_operation(
                config.workspace_id, contributor, "prepare_contribution", "verbatim-huge-one"
            )
            is None
        )

        # Ambiguous binding: one page claimed by two verbatim sources refuses.
        amb_upload_a = intake.save(
            config.workspace_id,
            contributor,
            "amb-a",
            "amb-a.md",
            "verbatim-upload-amb-a",
            doc_lf_text.encode("utf-8"),
        )
        amb_upload_b = intake.save(
            config.workspace_id,
            contributor,
            "amb-b",
            "amb-b.md",
            "verbatim-upload-amb-b",
            doc_lf_text.encode("utf-8"),
        )
        amb_page = verbatim_page(
            "entity:verbatim-amb",
            "Verbatim Ambiguous",
            "amb-a",
            doc_lf_text,
            extra_sources="  - id: amb-b\n    title: amb-b original\n",
        )
        ambiguous = call_contribution(
            client,
            contributor_token,
            {
                "retry_key": "verbatim-ambiguous-one",
                "sources": [
                    {"upload_id": amb_upload_a["upload_id"], "intent": "new", "verbatim": True},
                    {"upload_id": amb_upload_b["upload_id"], "intent": "new", "verbatim": True},
                ],
                "pages": [{"filename": "verbatim-amb.md", "markdown": amb_page}],
            },
        )
        assert ambiguous["isError"] is True
        assert (
            state.get_operation(
                config.workspace_id, contributor, "prepare_contribution", "verbatim-ambiguous-one"
            )
            is None
        )

        # Mixed candidate: two verbatim documents plus one ordinary distilled
        # page, reviewed by a separate human and published natively.
        distilled_page = (
            "---\n"
            "id: entity:distilled-notes\n"
            "title: Distilled Notes\n"
            "entity_types: [knowledge-artifact]\n"
            "tags: [operations]\n"
            "summary: Distilled conversion notes.\n"
            "category: procedures\n"
            "type: notes\n"
            "durability_rationale: Distilled notes need no exact preservation.\n"
            "lifecycle: approved\n"
            "visibility: internal\n"
            "synthetic: true\n"
            "---\n\n"
            "Distilled notes body.\n\n"
        )
        result = call_contribution(
            client,
            contributor_token,
            {
                "retry_key": "verbatim-two-docs",
                "sources": [
                    {"upload_id": upload_lf["upload_id"], "intent": "new", "verbatim": True},
                    {"upload_id": upload_crlf["upload_id"], "intent": "new", "verbatim": True},
                ],
                "pages": [
                    {"filename": "verbatim-lf.md", "markdown": lf_page},
                    {"filename": "verbatim-crlf.md", "markdown": crlf_page},
                    {"filename": "distilled-notes.md", "markdown": distilled_page},
                ],
            },
        )
        assert result["isError"] is False, result
        prepared = result["structuredContent"]
        assert prepared["status"] == "pending_review"
        assert "native_proposal" not in prepared
        task_id = prepared["task_id"]

        context = review.get(reviewer, task_id)
        published = review.decide(reviewer, task_id, context.action_digest, "approve")
        assert published["status"] == "published"
        assert published["publication_outcome"] == "activated"

        # Byte-exact published bodies: leading/trailing blank lines, CRLF form
        # and the literal fenced marker all survive.
        for filename, expected_text in (
            ("verbatim_lf_runbook.md", doc_lf_text),
            ("verbatim_crlf_runbook.md", doc_crlf_text),
        ):
            files = list(destination.rglob(filename))
            assert files, f"{filename} missing from the published tree"
            raw = files[0].read_bytes().decode("utf-8")
            end = raw.find("\n---", 3)
            assert end != -1
            assert raw[end + 4 :] == "\n" + expected_text
        lf_published = next(iter(destination.rglob("verbatim_lf_runbook.md")))
        assert "<!-- lumio: page-break -->" in lf_published.read_bytes().decode("utf-8")

        # The distilled default keeps its documented trimming transform.
        distilled_files = list(destination.rglob("distilled_notes.md"))
        assert distilled_files, "distilled page missing from the published tree"
        distilled_raw = distilled_files[0].read_bytes().decode("utf-8")
        assert distilled_raw.endswith("Distilled notes body.")
        assert not distilled_raw.endswith("\n")

        assert opened == []
        admitted_after = admission.load_current(project)
        assert admitted_after is not None
        assert admitted_after["commit"] == bound_release_commit

        # The strict public JSON loader learns the new optional fields: valid
        # roundtrip, invalid digest shape and unknown keys still refuse.
        request_payload = {
            "schema_version": 1,
            "base_revision": "0" * 40,
            "sources": [
                {
                    "source_id": "s",
                    "original_path": "/tmp/x.md",
                    "expected_digest": "a" * 64,
                    "intent": "new",
                    "verbatim_page": "p.md",
                    "expected_text_digest": "b" * 64,
                }
            ],
            "pages": ["p.md"],
        }
        request_path = tmp_path / "request.json"
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")
        loaded = load_candidate_request(request_path)
        assert loaded.sources[0].verbatim_page == "p.md"
        assert loaded.sources[0].expected_text_digest == "b" * 64
        bad_digest = json.loads(json.dumps(request_payload))
        bad_digest["sources"][0]["expected_text_digest"] = "Z" * 64
        request_path.write_text(json.dumps(bad_digest), encoding="utf-8")
        with pytest.raises(AuthoringJourneyError):
            load_candidate_request(request_path)
        unknown_key = json.loads(json.dumps(request_payload))
        unknown_key["sources"][0]["bogus"] = 1
        request_path.write_text(json.dumps(unknown_key), encoding="utf-8")
        with pytest.raises(AuthoringJourneyError):
            load_candidate_request(request_path)

    # Direct public structured-SDK regression (spec0010 §3.1): repeated Source
    # ID across distinct verbatim records refuses BEFORE any registration,
    # retention or authored write — the first original is never quietly lost
    # to a last-wins originals mapping.
    import shutil

    from lumio_wiki.authoring_journey import CandidateRequest, CandidateSourceRecord
    from lumio_wiki.authoring_journey import ingest_candidate as sdk_ingest_candidate
    from lumio_wiki.private_profile import load_private_profile, resolve_private_profile

    sdk_kb_root = tmp_path / "sdk-kb"
    shutil.copytree(project, sdk_kb_root)
    sdk_private = tmp_path / "sdk-private"
    (sdk_private / "registry").mkdir(parents=True)
    (sdk_private / "artifacts").mkdir()
    sdk_profile = sdk_private / "profile.json"
    sdk_profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(sdk_private / "registry"),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(sdk_private / "artifacts")},
            }
        ),
        encoding="utf-8",
    )
    sdk_resources = resolve_private_profile(
        load_private_profile(sdk_profile, kb_root=sdk_kb_root / "knowledge"),
        kb_root=sdk_kb_root / "knowledge",
        needs=frozenset({"registry", "artifacts"}),
    )
    registry_before = sorted(
        str(p.relative_to(sdk_private)) for p in sdk_private.rglob("*") if p.is_file()
    )
    sdk_status_before = _git(sdk_kb_root, "status", "--porcelain")
    shared_id = "verbatim-shared"
    sdk_original_a = tmp_path / "sdk-original-a.md"
    sdk_original_a.write_bytes(doc_lf_text.encode("utf-8"))
    sdk_original_b = tmp_path / "sdk-original-b.md"
    sdk_original_b.write_bytes(doc_crlf_text.encode("utf-8"))
    sdk_authored = tmp_path / "sdk-authored"
    sdk_authored.mkdir()
    sdk_page_a = sdk_authored / "sdk-page-a.md"
    sdk_page_a.write_text(
        verbatim_page("entity:sdk-page-a", "SDK Page A", shared_id, doc_lf_text),
        encoding="utf-8",
    )
    sdk_page_b = sdk_authored / "sdk-page-b.md"
    sdk_page_b.write_text(
        verbatim_page("entity:sdk-page-b", "SDK Page B", shared_id, doc_crlf_text),
        encoding="utf-8",
    )
    duplicate_request = CandidateRequest(
        schema_version=1,
        base_revision=native_review["revision"],
        sources=[
            CandidateSourceRecord(
                source_id=shared_id,
                original_path=str(sdk_original_a),
                expected_digest=hashlib.sha256(doc_lf_text.encode("utf-8")).hexdigest(),
                intent="new",
                verbatim_page="sdk-page-a.md",
                expected_text_digest=hashlib.sha256(doc_lf_text.encode("utf-8")).hexdigest(),
            ),
            CandidateSourceRecord(
                source_id=shared_id,
                original_path=str(sdk_original_b),
                expected_digest=hashlib.sha256(doc_crlf_text.encode("utf-8")).hexdigest(),
                intent="new",
                verbatim_page="sdk-page-b.md",
                expected_text_digest=hashlib.sha256(doc_crlf_text.encode("utf-8")).hexdigest(),
            ),
        ],
        pages=[str(sdk_page_a), str(sdk_page_b)],
    )
    with pytest.raises(AuthoringJourneyError, match="duplicate source record"):
        sdk_ingest_candidate(
            sdk_kb_root / "knowledge",
            duplicate_request,
            source_registry=sdk_resources.source_registry,
            artifact_store=sdk_resources.artifact_store,
        )
    registry_after = sorted(
        str(p.relative_to(sdk_private)) for p in sdk_private.rglob("*") if p.is_file()
    )
    assert registry_after == registry_before, "the refused candidate registered originals"
    assert _git(sdk_kb_root, "status", "--porcelain") == sdk_status_before, (
        "the refused candidate wrote authored content"
    )
