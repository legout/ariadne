"""Named S3 storage profiles — LIVE signed routing, secret lifecycle and
effective-endpoint authority (issue #71/S1; spec 0025 §§7 AC2/AC4–AC6).

Real loopback S3-compatible endpoints (see ``tests/s3_fixture.py``): two
containers with DISTINCT synthetic credentials expose the independently
specified datasets — storage A (retail): count 3, sum 60, EMEA 40; storage B
(analytics): count 2, sum 200. Expected rows/arithmetic come from that
fixture, never from observed implementation output; wrong credentials are
rejected by the fixture itself. Global AWS_* values are deliberately WRONG so
they cannot hide missing profile configuration. No mock connection ever
substitutes for these proofs: everything runs through the real shared builder
(``ariadne.sources.build_connection``) and the real managed runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.sources  # noqa: E402
from ariadne import admission as admission_module  # noqa: E402
from ariadne.authoring import AuthoringProject, _verify_receipt  # noqa: E402
from ariadne.authoring_sources import (  # noqa: E402
    approval_digest,
    candidate_sources,
    storage_bindings_from_identity,
)
from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.sources import build_connection, load_registry  # noqa: E402
from tests import s3_fixture as fx  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    METRIC_PAGE,
    MODEL_YML,
    POLICY_PAGE,
    REFERENCE_PAGE,
    SEED_NOTES,
    SKILLS_PAGE,
    TABLES_PAGE,
    run_git,
)

STATE = admission_module.proposals.ARIADNE_STATE_DIR
CURRENT = STATE / "current.json"

# One governed metric over the retail source (the test_sources.py minimal-OSI
# pattern): SUM(amount) must come from storage A (60), never storage B (200).
ORDERS_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: orders.orders
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
    metrics:
      - name: total_amount
        description: Sum of order amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
"""


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture(autouse=True)
def clean_profile_environment(monkeypatch):
    for name in (
        "ARIADE_S1_LOCAL_KEY_ID",
        "ARIADE_S1_LOCAL_SECRET",
        "ARIADE_S1_LOCAL_ENDPOINT",
        "ARIADE_S1_REMOTE_KEY_ID",
        "ARIADE_S1_REMOTE_SECRET",
        "ARIADE_S1_REMOTE_ENDPOINT",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def builder_spy(monkeypatch):
    """Record every registry handed to the shared builder (the one chokepoint)."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True, *, deadline=None):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only, deadline=deadline)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    return opened


def registry_file(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "ariadne.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


# ------------------------------------------------------------- AC2 (live)


def test_two_profiles_route_distinct_signed_s3_data(tmp_path, monkeypatch):
    """One shared connection, two profiles, two endpoints with DISTINCT
    synthetic credentials: each registered source reads its own endpoint's
    independently specified dataset (60 never 200), a native DuckDB catalog
    attaches through the same profile, a normal compiled Ariadne metric
    answers 60, and deliberately WRONG global AWS values cannot hide missing
    profile configuration (spec 0025 §7 AC2)."""
    fx.require_docker()
    a, b = fx.storage_pair(tmp_path / "fixture")
    try:
        # the fixture itself rejects wrong credentials (authenticity oracle)
        assert a.request_rejected("GET", f"{a.endpoint_url}/retail/orders/orders.parquet")
        assert b.request_rejected("GET", f"{b.endpoint_url}/analytics/metrics/metrics.parquet")

        # the native DuckDB catalog rides storage A via SigV4 upload
        catalog_url = a.put_bytes(
            "retail/catalogs/native.duckdb", fx.native_catalog_bytes(fx.ORACLE_A_ROWS)
        )
        fx.export_environment(a, b, monkeypatch)
        registry_path = registry_file(
            tmp_path,
            {
                "storages": fx.profile_definitions(a, b),
                "sources": [
                    {
                        "name": "orders",
                        "type": "parquet",
                        "storage": "local",
                        "path": "s3://retail/orders/orders.parquet",
                    },
                    {
                        "name": "events",
                        "type": "parquet",
                        "storage": "remote",
                        "path": "s3://analytics/metrics/metrics.parquet",
                    },
                    {
                        "name": "catalog",
                        "type": "duckdb",
                        "storage": "local",
                        "path": catalog_url,
                    },
                ],
            },
        )
        registry = load_registry(registry_path)
        con, catalog = build_connection(registry)
        try:
            row = con.execute(
                "SELECT count(*), sum(amount), sum(amount) FILTER (WHERE region = 'EMEA') "
                "FROM orders.orders"
            ).fetchone()
            assert row == (
                fx.ORACLE_A["count"],
                fx.ORACLE_A["sum"],
                fx.ORACLE_A["emea_sum"],
            )
            row = con.execute("SELECT count(*), sum(amount) FROM events.metrics").fetchone()
            assert row == (fx.ORACLE_B["count"], fx.ORACLE_B["sum"])
            row = con.execute(
                "SELECT count(*), sum(amount) FROM catalog.main.orders"
            ).fetchone()
            assert row == (fx.ORACLE_A["count"], fx.ORACLE_A["sum"])
            names = {entry["name"] for entry in catalog}
            assert names == {"orders", "events", "catalog"}
        finally:
            con.close()

        # a normal compiled Ariadne metric over the shared registry: 60, not 200
        semantic = tmp_path / "semantic_layer" / "models"
        semantic.mkdir(parents=True)
        (semantic / "orders.yml").write_text(ORDERS_MODEL, encoding="utf-8")
        runtime = QueryRuntime(
            tmp_path / "semantic_layer",
            tmp_path / "context_layer",
            None,
            staging_dir=tmp_path / "staging",
            sources=registry_path,
        )
        try:
            result = asyncio.run(runtime.get_metric("total_amount"))
            assert result["governed"] is True
            assert result["rows"] == [{"total_amount": fx.ORACLE_A["sum"]}]
        finally:
            runtime.con.close()
    finally:
        fx.stop_pair(a, b)


# ------------------------------------------------------------- AC4 (live)


def test_secret_setup_failure_is_redacted_and_closes_connection(tmp_path, monkeypatch):
    """A deterministic setup failure with synthetic credentials and an error
    that echoes the failing statement: neither public plans, returned/chained
    errors nor persisted state reveal any key/token value; the refused setup
    leaves no persistent secret file and no usable connection (spec 0025 §7
    AC4). Missing variables and invalid endpoint values refuse explicitly."""
    fx.require_docker()
    home = tmp_path / "duckdb-home"
    (home / ".duckdb" / "extensions").mkdir(parents=True, exist_ok=True)
    real_extensions = Path.home() / ".duckdb" / "extensions"
    if real_extensions.is_dir():
        shutil.copytree(real_extensions, home / ".duckdb" / "extensions", dirs_exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    a, b = fx.storage_pair(tmp_path / "fixture")
    try:
        fx.export_environment(a, b, monkeypatch)
        registry_path = registry_file(
            tmp_path,
            {
                "storages": fx.profile_definitions(a, b),
                "sources": [
                    {
                        "name": "orders",
                        "type": "parquet",
                        "storage": "local",
                        "path": "s3://retail/orders/orders.parquet",
                    }
                ],
            },
        )
        registry = load_registry(registry_path)
        loads, statements = ariadne.sources.plan(registry)
        joined = "\n".join([*loads, *statements])
        assert "CREATE SECRET" not in joined  # public plans carry no secret SQL

        # WRONG key values: the fixture rejects the signed request, the view
        # binding fails, and the error echoes the statement — never the values
        wrong_key, wrong_secret = "wrongsynthetickey", "wrongsyntheticsecret"
        monkeypatch.setenv("ARIADE_S1_LOCAL_KEY_ID", wrong_key)
        monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", wrong_secret)
        with pytest.raises(Exception) as refused:
            build_connection(registry)
        message = str(refused.value)
        fx.assert_no_secret_values(message, [wrong_key, wrong_secret, a.secret_key])
        assert "orders" in message  # the failing source binding is named
        stored = home / ".duckdb" / "stored_secrets"
        assert not stored.exists() or not any(stored.iterdir())  # nothing persisted

        # a missing required variable refuses naming the variable identity
        monkeypatch.delenv("ARIADE_S1_LOCAL_SECRET", raising=False)
        with pytest.raises(ValueError, match="ARIADE_S1_LOCAL_SECRET"):
            build_connection(registry)

        # an invalid endpoint VALUE refuses during identity resolution
        monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", a.secret_key)
        monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", "http://127.0.0.1:1/base/path")
        with pytest.raises(ValueError, match="root path"):
            build_connection(registry)
    finally:
        fx.stop_pair(a, b)


# ---------------------------------------------------- AC5/AC6 (live, Git)


def s3_git_project(tmp_path: Path) -> Path:
    """A real temporary Git data project whose human baseline is a COMPLETE
    bundle over one S3 parquet source ``events.events`` — except the registry
    is the commented template: the sources AND storages arrive through the Git
    propose-sources seam (spec 0025 §5)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (project / "data" / "docs").mkdir(parents=True, exist_ok=True)
    (project / "data" / "docs" / "notes.md").write_text("# Rule notes\n", encoding="utf-8")
    (project / "semantic_layer" / "models").mkdir(parents=True, exist_ok=True)
    (project / "semantic_layer" / "models" / "events.yml").write_text(MODEL_YML, encoding="utf-8")
    pages = {
        "context_layer/tables/events.md": TABLES_PAGE,
        "context_layer/references/joins/events--events.md": REFERENCE_PAGE,
        "context_layer/policies/all-events-count.md": POLICY_PAGE,
        "context_layer/metrics/event_count.md": METRIC_PAGE,
        "context_layer/skills/run-the-demo.md": SKILLS_PAGE,
    }
    for rel, content in pages.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    scope = ["ariadne.yaml", "data/seed_notes.md", "semantic_layer/models/events.yml", *pages]
    run_git(project, "add", "--", *scope)
    message = "human: complete bundle, registry template"
    run_git(project, "commit", "-q", "-m " + message, "--", *scope)
    return project


def _endpoint_pair(tmp_path: Path):
    """Endpoint A (retail) carries a ROTATED second credential pair; endpoint
    B is a second, differently-credentialed storage of the same logical
    ``s3://retail/`` dataset — the endpoint A→B journey's other side."""
    a = fx.S3Endpoint(
        tmp_path, "retail", "retailkey001", "retailsecret001", None,
        rotated_key="retailkey002", rotated_secret="retailsecret002",
    ).start()
    try:
        b = fx.S3Endpoint(tmp_path, "retailb", "retailbkey01", "retailbsecret01", None).start()
    except BaseException:
        a.stop()
        raise
    try:
        rows = [(1, "a"), (2, "b"), (3, "c")]
        a.put_parquet("retail/orders/events.parquet", rows, ("id", "label"))
        b.put_parquet("retail/orders/events.parquet", rows, ("id", "label"))
    except BaseException:
        fx.stop_pair(a, b)
        raise
    return a, b


def _set_local(monkeypatch, endpoint) -> None:
    monkeypatch.setenv("ARIADE_S1_LOCAL_KEY_ID", endpoint.access_key)
    monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", endpoint.secret_key)
    monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", endpoint.endpoint_url)


def test_effective_endpoint_change_requires_new_approval_and_evidence(
    tmp_path, monkeypatch, builder_spy
):
    """The effective-authority journey over a REAL Git proposal and the two
    fixture endpoints (spec 0025 §§4–5, AC5/AC6): a valid proposal opens
    nothing; human approval binds the resolved endpoint without key values or
    network calls; switching the same profile's endpoint A→B with IDENTICAL
    candidate bytes keeps the declaration digest but changes the approval
    identity — no measured read before B's own grant, A's grant intact, fresh
    validation/admission required, receipts and a mutated stored binding
    refused, and key rotation at an unchanged binding needs no new approval."""
    fx.require_docker()
    a, b = _endpoint_pair(tmp_path / "fixture")
    try:
        project = s3_git_project(tmp_path)
        api = AuthoringProject(project)
        profiles = {
            "local": {
                "type": "s3",
                "access_key_id_env": "ARIADE_S1_LOCAL_KEY_ID",
                "secret_access_key_env": "ARIADE_S1_LOCAL_SECRET",
                "endpoint_url_env": "ARIADE_S1_LOCAL_ENDPOINT",
                "scopes": ["s3://retail/"],
            }
        }
        entries = [
            {
                "name": "events",
                "type": "parquet",
                "storage": "local",
                "path": "s3://retail/orders/events.parquet",
            }
        ]

        # [1] INERT PROPOSAL: no environment values, nothing opened
        _set_local(monkeypatch, a)
        monkeypatch.delenv("ARIADE_S1_LOCAL_KEY_ID", raising=False)
        monkeypatch.delenv("ARIADE_S1_LOCAL_SECRET", raising=False)
        started = api.start_proposal()
        revision = started["candidate_revision"]
        proposed = api.propose_sources(
            started["proposal"], revision, entries, profiles
        )
        declaration_digest = proposed["source_digest"]
        resolved, digest = candidate_sources(project, proposed["revision"])
        assert digest == declaration_digest

        # [2] APPROVAL binds the resolved endpoint WITHOUT key values: missing
        # key/token values do not block location approval (spec §4) — and no
        # connection is ever built for the approval itself
        spy_mark = len(builder_spy)
        approved_a = api.approve_sources(
            started["proposal"], proposed["revision"], declaration_digest
        )
        assert len(builder_spy) == spy_mark  # approval makes no network/connection call
        assert approved_a["source_digest"] == declaration_digest
        assert approved_a["storage_bindings"]["local"]["endpoint"] == a.endpoint_url
        assert approved_a["approval_digest"] != declaration_digest  # effective identity
        _set_local(monkeypatch, a)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAGLOBALWRONG")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "globalwrongsecret")

        # [3] MEASURED VALIDATION against endpoint A, then review + admission
        edited = api.edit_proposal(
            started["proposal"],
            proposed["revision"],
            {
                "kind": "page",
                "section": "policies",
                "name": "all-events-count",
                "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
            },
        )
        validated_a = api.validate_proposal(started["proposal"], edited["revision"])
        assert validated_a["ok"] is True
        assert validated_a["storage_bindings"]["local"]["endpoint"] == a.endpoint_url
        assert validated_a["approval_digest"] == approved_a["approval_digest"]
        review_a = api.review_proposal(started["proposal"])
        assert review_a["source_approved"] is True
        assert review_a["source_approval_state"] == "current"

        # a real mapping receipt measured against A's binding
        events_resource = ariadne.sources.table_resource("events", None, "events", "events")
        receipt = api.inspect_mapping(
            started["proposal"],
            review_a["revision"],
            {
                "family": "equality",
                "left": [{"resource": events_resource, "column": "id"}],
                "right": [{"resource": events_resource, "column": "id"}],
            },
        )
        assert receipt["receipt"]["storage_bindings"]["local"]["endpoint"] == a.endpoint_url

        admitted = admission_module.admit_revision(
            project,
            started["proposal"],
            review_a["revision"],
            review_a["review_digest"],
            confirmed_by="human:test",
        )
        assert admitted["source_digest"] == approved_a["approval_digest"]
        record = json.loads((project / CURRENT).read_text())
        assert record["storage_bindings"]["local"]["endpoint"] == a.endpoint_url
        runtime = QueryRuntime.open_project(project)
        try:
            assert asyncio.run(runtime.get_metric("event_count"))["rows"] == [{"event_count": 3}]
        finally:
            runtime.con.close()

        # [4] ENDPOINT CHANGE A→B with IDENTICAL candidate bytes
        _set_local(monkeypatch, b)
        resolved_b, digest_b = candidate_sources(project, review_a["revision"])
        assert digest_b == declaration_digest  # declaration identity unchanged
        bindings_b = storage_bindings_from_identity(resolved_b)
        assert bindings_b["local"]["endpoint"] == b.endpoint_url
        assert approval_digest(declaration_digest, bindings_b) != approved_a["approval_digest"]

        # no measured read before B's grant: validation/inputs/refresh refuse
        spy_mark = len(builder_spy)
        with pytest.raises(ValueError, match="NO operator approval"):
            api.validate_proposal(started["proposal"], review_a["revision"])
        with pytest.raises(ValueError, match="NO operator approval"):
            api.inputs(started["proposal"])
        assert len(builder_spy) == spy_mark

        # offline review labels the binding not-current (declaration history
        # exists; the CURRENT effective identity carries no grant)
        review_b_pending = api.review_proposal(started["proposal"])
        assert review_b_pending["source_approval_state"] == "not-current"
        assert review_b_pending["source_approved"] is False

        # A's measured receipt cannot verify against B's binding
        summary, error = _verify_receipt(
            receipt["receipt_id"],
            project,
            started["proposal"],
            declaration_digest=receipt["receipt"]["candidate_digest"],
            source_digest=declaration_digest,
            asset_columns={},
            storage_bindings=bindings_b,
        )
        assert summary is None
        assert error is not None and "different effective storage binding" in error

        # B's own grant: approval is identity-keyed, A's grant is retained
        approved_b = api.approve_sources(
            started["proposal"], review_a["revision"], declaration_digest
        )
        assert approved_b["approval_digest"] == approval_digest(declaration_digest, bindings_b)
        grants = json.loads(
            (project / admission_module.authoring_sources.SOURCE_APPROVALS_REL).read_text()
        )
        assert approved_a["approval_digest"] in grants  # A's grant intact
        assert approved_b["approval_digest"] in grants

        # fresh validation under B (a changed binding is NOT idempotent reuse)
        validated_b = api.validate_proposal(started["proposal"], review_a["revision"])
        assert validated_b["ok"] is True
        assert validated_b["storage_bindings"]["local"]["endpoint"] == b.endpoint_url
        assert validated_b["approval_digest"] == approved_b["approval_digest"]

        # re-admission under B; the pinned A admission cannot serve env-B
        review_b = api.review_proposal(started["proposal"])
        assert review_b["source_approval_state"] == "current"
        with pytest.raises(ValueError, match="different effective storage binding"):
            QueryRuntime.open_project(project)
        admission_module.admit_revision(
            project,
            started["proposal"],
            review_b["revision"],
            review_b["review_digest"],
            confirmed_by="human:test",
        )
        record_b = json.loads((project / CURRENT).read_text())
        assert record_b["storage_bindings"]["local"]["endpoint"] == b.endpoint_url
        assert record_b["source_digest"] == approved_b["approval_digest"]

        # a MUTATED stored binding with a claimed old digest refuses serving
        mutated = dict(record_b)
        mutated["storage_bindings"] = {
            "local": {**record_b["storage_bindings"]["local"], "endpoint": "http://127.0.0.1:9"}
        }
        (project / CURRENT).write_text(json.dumps(mutated), encoding="utf-8")
        with pytest.raises(ValueError, match="mutated binding"):
            QueryRuntime.open_project(project)
        (project / CURRENT).write_text(json.dumps(record_b), encoding="utf-8")

        # [5] KEY ROTATION at an UNCHANGED binding: the second synthetic
        # credential pair serves the same endpoint — no new approval needed,
        # a NEW connection reads with the rotated values
        _set_local(monkeypatch, b)  # the B-pinned admission's environment
        # the rotated pair (endpoint A's SECOND identity) with endpoint A: the
        # B-pinned admission must refuse the now-A environment
        monkeypatch.setenv("ARIADE_S1_LOCAL_KEY_ID", a.rotated_key)
        monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", a.rotated_secret)
        monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", a.endpoint_url)
        with pytest.raises(ValueError, match="different effective storage binding"):
            QueryRuntime.open_project(project)  # B-pinned admission, env now A
        # re-admit under A's grant (still on record, unchanged identity)
        approved_a2 = api.approve_sources(
            started["proposal"], review_b["revision"], declaration_digest
        )
        assert approved_a2["approval_digest"] == approved_a["approval_digest"]
        validated_a2 = api.validate_proposal(started["proposal"], review_b["revision"])
        assert validated_a2["ok"] is True
        review_a2 = api.review_proposal(started["proposal"])
        admission_module.admit_revision(
            project,
            started["proposal"],
            review_a2["revision"],
            review_a2["review_digest"],
            confirmed_by="human:test",
        )
        runtime = QueryRuntime.open_project(project)
        try:
            # served by the ROTATED credential pair of the unchanged endpoint A
            assert asyncio.run(runtime.get_metric("event_count"))["rows"] == [{"event_count": 3}]
        finally:
            runtime.con.close()
        grants_final = json.loads(
            (project / admission_module.authoring_sources.SOURCE_APPROVALS_REL).read_text()
        )
        assert set(grants_final) == {approved_a["approval_digest"], approved_b["approval_digest"]}
    finally:
        fx.stop_pair(a, b)
