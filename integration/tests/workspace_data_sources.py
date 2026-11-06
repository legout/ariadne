"""D3/VD3a: managed named-S3 selection binds the exact effective target.

The two loopback endpoints serve the same declared URI with independently
specified, distinct rows. The installed workspace adapter and native
approval/admission/query seams are real; no source opens before the matching
native Source Approval and caller data grant.
"""

from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path

import pytest
from ariadne import admission, execution
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
from lumio_workspace.review import ReviewService, render_review

# integration/tests/conftest.py supplies Core's native test-helper namespace.
fx = import_module("tests.s3_fixture")
run_git = import_module("tests.test_git_authoring").run_git
s3_git_project = import_module("tests.test_s3_storage_access").s3_git_project

S3_MODEL = """version: 0.2.0.dev0
semantic_model:
  - name: events
    description: Events model
    datasets:
      - name: events
        source: events.events
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
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
    metrics:
      - name: event_count
        description: Count of all events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""


def _endpoint_pair(root: Path):
    a = fx.S3Endpoint(root, "retail", "retailkey001", "retailsecret001", None).start()
    try:
        b = fx.S3Endpoint(
            root,
            "retailb",
            "retailbkey01",
            "retailbsecret01",
            None,
            rotated_key="retailbkey02",
            rotated_secret="retailbsecret02",
        ).start()
    except BaseException:
        a.stop()
        raise
    try:
        a.put_parquet("retail/orders/events.parquet", fx.ORACLE_A_ROWS, ("id", "amount", "region"))
        b.put_parquet("retail/orders/events.parquet", fx.ORACLE_B_ROWS, ("id", "amount", "region"))
    except BaseException:
        fx.stop_pair(a, b)
        raise
    return a, b


def _set_endpoint(monkeypatch, endpoint, *, rotated: bool = False) -> None:
    monkeypatch.setenv(
        "ARIADE_S1_LOCAL_KEY_ID", endpoint.rotated_key if rotated else endpoint.access_key
    )
    monkeypatch.setenv(
        "ARIADE_S1_LOCAL_SECRET", endpoint.rotated_secret if rotated else endpoint.secret_key
    )
    monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", endpoint.endpoint_url)


def _service(tmp_path: Path, project: Path, bindings: Path):
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
                "namespace": "urn:demo:retail",
                "source_registry": str(registry),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(artifacts)},
            }
        ),
        encoding="utf-8",
    )
    authoring_path = project / "knowledge"
    authoring_path.mkdir(exist_ok=True)
    config = WorkspaceConfig(
        workspace_id="workspace-data-sources",
        external_url="https://workspace.test",
        published_path=tmp_path / "published",
        published_version=None,
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=authoring_path,
        private_profile_path=profile,
        private_root=tmp_path / "operations",
        namespace="urn:demo:retail",
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
    analytics = AnalyticsService(config, state, IntakeService(state, config.operational_root))
    review = ReviewService(
        state,
        workspace_id=config.workspace_id,
        authoring_path=authoring_path,
        profile_path=profile,
        private_root=config.operational_root,
        destination=config.published_path,
        analytics=analytics,
    )
    return analytics, review, contributor, reviewer


def test_managed_s3_selection_binds_effective_target(tmp_path, monkeypatch):
    fx.require_docker()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAGLOBALWRONG")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "globalwrongsecret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    a, b = _endpoint_pair(tmp_path / "fixture")
    try:
        project = s3_git_project(tmp_path / "project")
        model = project / "semantic_layer/models/events.yml"
        model.write_text(S3_MODEL, encoding="utf-8")
        knowledge = project / "knowledge"
        knowledge.mkdir()
        (knowledge / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
            serialize_source_reference_manifest(
                SourceReferenceManifest(
                    version=1,
                    namespace="urn:demo:retail",
                    sources={},
                    bindings={},
                )
            )
        )
        run_git(
            project,
            "add",
            "--",
            "semantic_layer/models/events.yml",
            f"knowledge/{SOURCE_REFERENCE_MANIFEST_BASENAME}",
        )
        run_git(project, "commit", "-q", "-m", "human: model the independent S3 rows")
        api = AuthoringProject(project)
        bindings = tmp_path / "source-bindings.json"
        bindings.write_text(
            json.dumps(
                {
                    "storages": {
                        "local": {
                            "type": "s3",
                            "access_key_id_env": "ARIADE_S1_LOCAL_KEY_ID",
                            "secret_access_key_env": "ARIADE_S1_LOCAL_SECRET",
                            "endpoint_url_env": "ARIADE_S1_LOCAL_ENDPOINT",
                            "url_style": "path",
                            "scopes": ["s3://retail/"],
                        }
                    },
                    "events_s3": [
                        {
                            "name": "events",
                            "type": "parquet",
                            "storage": "local",
                            "path": "s3://retail/orders/events.parquet",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        analytics, review, contributor, reviewer = _service(tmp_path, project, bindings)
        opened = []
        real_builder = execution.build_connection

        def builder_spy(registry, **kwargs):
            opened.append(registry)
            return real_builder(registry, **kwargs)

        monkeypatch.setattr(execution, "build_connection", builder_spy)
        monkeypatch.setattr(native_sources, "build_connection", builder_spy)
        _set_endpoint(monkeypatch, a)
        prepared = analytics.prepare_data_source(
            contributor,
            retry_key="request-managed-s3",
            project="retail",
            source="events_s3",
            table="events",
            business_questions=["Which explicitly selected S3 rows are available?"],
        )
        task_id = prepared["task_id"]
        assert prepared["status"] == "pending_source_approval"
        assert admission.load_current(project) is None
        assert opened == []

        context_a = review.get(reviewer, task_id)
        rendered_a = render_review(context_a, None)
        assert a.endpoint_url in rendered_a
        assert "s3://retail/" in rendered_a
        credential_values = [
            a.access_key,
            a.secret_key,
            b.access_key,
            b.secret_key,
            b.rotated_key,
            b.rotated_secret,
        ]
        assert not any(value in rendered_a for value in credential_values if value)
        approved_a = review.decide(reviewer, task_id, context_a.action_digest, "approve")
        grant_context_a = review.get(reviewer, task_id)
        granted_a = review.decide(reviewer, task_id, grant_context_a.action_digest, "approve")
        assert granted_a["status"] == "data_granted"
        assert admission.load_current(project) is None
        assert opened == []

        # The declaration is unchanged, but endpoint B has no native grant.
        _set_endpoint(monkeypatch, b)
        with pytest.raises(AnalyticsError, match="Source Approval"):
            analytics.profile_data_source(contributor, task_id)
        assert admission.load_current(project) is None
        assert opened == []
        prepared_b = analytics.prepare_data_source(
            contributor,
            retry_key="request-managed-s3-b",
            project="retail",
            source="events_s3",
            table="events",
            business_questions=["Grant the changed effective S3 target exactly."],
        )
        assert prepared_b["status"] == "pending_source_approval"
        assert prepared_b["native_candidate"] == prepared["native_candidate"]
        task_id = prepared_b["task_id"]
        context_b = review.get(reviewer, task_id)
        approved_b = review.decide(reviewer, task_id, context_b.action_digest, "approve")
        assert approved_b["approval_digest"] != approved_a["approval_digest"]
        grant_context_b = review.get(reviewer, task_id)
        granted_b = review.decide(reviewer, task_id, grant_context_b.action_digest, "approve")
        assert granted_b["approval_digest"] == approved_b["approval_digest"]
        profiled = analytics.profile_data_source(contributor, task_id)
        source_profile = next(
            source for source in profiled["profile"]["sources"] if source["name"] == "events"
        )
        assert set(source_profile["tables"]) == {"events"}
        assert source_profile["tables"]["events"]["row_count"] == len(fx.ORACLE_B_ROWS)
        assert source_profile["tables"]["events"]["sample_limit"] == 100

        # A second valid identity at the unchanged endpoint retains the exact
        # native approval while validation, admission, and query use B's rows.
        _set_endpoint(monkeypatch, b, rotated=True)
        validated = api.validate_proposal(prepared["native_proposal"], prepared["native_candidate"])
        assert validated["ok"] is True, validated["errors"]
        assert validated["approval_digest"] == approved_b["approval_digest"]
        native_review = api.review_proposal(prepared["native_proposal"])
        admitted = admission.admit_revision(
            project,
            prepared["native_proposal"],
            native_review["revision"],
            native_review["review_digest"],
            confirmed_by="human:synthetic-operator",
        )
        assert admitted["source_digest"] == approved_b["approval_digest"]
        assert admitted["storage_bindings"]["local"]["endpoint"] == b.endpoint_url
        result = analytics.query_data(
            contributor,
            "retail",
            task_id,
            "query_records",
            {
                "dataset": "events.events",
                "fields": ["id", "amount", "region"],
                "order": [{"field": "id", "direction": "asc"}],
                "limit": 10,
            },
        )
        assert result["rows"] == [
            {"id": row[0], "amount": row[1], "region": row[2]} for row in fx.ORACLE_B_ROWS
        ]
        assert result["governed"] is False  # every native bounded record query
        assert result["pinned"]["source_digest"] == approved_b["approval_digest"]
        assert not any(value in json.dumps(result) for value in credential_values if value)

        # Unrelated operator profiles are outside this selection and cannot
        # invalidate or duplicate-reject the admitted source's exact reuse.
        binding_document = json.loads(bindings.read_text(encoding="utf-8"))
        binding_document["storages"]["unrelated"] = {
            "type": "s3",
            "access_key_id_env": "UNRELATED_ACCESS_KEY_ID",
            "secret_access_key_env": "UNRELATED_SECRET_ACCESS_KEY",
            "endpoint_url_env": "UNRELATED_ENDPOINT",
            "scopes": ["s3://unrelated/"],
        }
        bindings.write_text(json.dumps(binding_document), encoding="utf-8")
        reused_unrelated = analytics.prepare_data_source(
            contributor,
            retry_key="request-managed-s3-reuse-unrelated",
            project="retail",
            source="events_s3",
            table="events",
            business_questions=["Reuse the admitted selection, not an unrelated profile."],
        )
        assert reused_unrelated["status"] == "pending_data_grant"
        assert reused_unrelated["reused_source_declaration"] is True
        assert reused_unrelated["native_candidate"] == native_review["revision"]

        # Omitted url_style is the same canonical declaration as default path.
        binding_document["storages"]["local"].pop("url_style")
        bindings.write_text(json.dumps(binding_document), encoding="utf-8")
        reused_default = analytics.prepare_data_source(
            contributor,
            retry_key="request-managed-s3-reuse-default",
            project="retail",
            source="events_s3",
            table="events",
            business_questions=["Reuse the canonical default-path declaration."],
        )
        assert reused_default["status"] == "pending_data_grant"
        assert reused_default["reused_source_declaration"] is True
        assert reused_default["native_candidate"] == native_review["revision"]
    finally:
        fx.stop_pair(a, b)
