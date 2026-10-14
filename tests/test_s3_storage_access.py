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

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
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
from ariadne.promote import promote_bundle  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.sources import build_connection, load_registry  # noqa: E402
from tests import s3_fixture as fx  # noqa: E402
from tests.test_authoring import (  # noqa: E402 — legacy-route fixtures
    bundle_submission,
    scaffold_project,
    write_submission,
)
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

        # the native DuckDB catalog rides storage A via SigV4 upload; the
        # CSV/JSON file-reader families ride A and B with their own fixtures
        catalog_url = a.put_bytes(
            "retail/catalogs/native.duckdb", fx.native_catalog_bytes(fx.ORACLE_A_ROWS)
        )
        csv_url = a.put_csv(
            "retail/labels/labels.csv", [(1, "EMEA"), (2, "AMER")], ("order_id", "region")
        )
        # a native catalog whose VIEW reads S3 backing files — no credentials
        # inside the catalog; the shared session's profile serves its reads
        view_catalog_url = a.put_bytes(
            "retail/catalogs/views.duckdb",
            fx.native_view_catalog_bytes(a, "s3://retail/orders/orders.parquet"),
        )
        json_url = b.put_json(
            "analytics/events/events.json", fx.ORACLE_B_ROWS, ("id", "amount", "region")
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
                    {"name": "labels", "type": "csv", "storage": "local", "path": csv_url},
                    {"name": "happenings", "type": "json", "storage": "remote", "path": json_url},
                    {
                        "name": "viewcat",
                        "type": "duckdb",
                        "storage": "local",
                        "path": view_catalog_url,
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
            # the CSV/JSON reader families route through their own profiles
            row = con.execute(
                "SELECT count(*), count(*) FILTER (WHERE region = 'EMEA') FROM labels.labels"
            ).fetchone()
            assert row == (2, 1)  # the CSV fixture's own two rows
            # the native catalog's VIEW reads its S3 backing file THROUGH the
            # profile (blocker 3: the view's data reads must traverse it)
            row = con.execute(
                "SELECT count(*), sum(amount) FROM viewcat.main.backing_orders"
            ).fetchone()
            assert row == (fx.ORACLE_A["count"], fx.ORACLE_A["sum"])
            row = con.execute(
                "SELECT count(*), sum(amount) FROM happenings.events"
            ).fetchone()
            assert row == (fx.ORACLE_B["count"], fx.ORACLE_B["sum"])
            names = {entry["name"] for entry in catalog}
            assert names == {"orders", "events", "catalog", "labels", "happenings", "viewcat"}
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


# ---------------------------------------------- fix pass (finding 1, AC4)


def test_secret_creation_failure_redacts_echoed_statement(tmp_path, monkeypatch):
    """Fix finding 1 (spec 0025 §3/AC4): a failing CREATE SECRET whose error
    echoes the full statement — including the key/token literals — is
    redacted: the redaction values are collected BEFORE the secret SQL
    executes, so neither the returned nor a chained error ever carries a
    credential value. Deterministic injected failure on the real owned
    connection; no network is needed (creation fails first)."""
    import duckdb

    registry_path = registry_file(
        tmp_path,
        {
            "storages": {
                "local": {
                    "type": "s3",
                    "access_key_id_env": "F1_KEY_ID",
                    "secret_access_key_env": "F1_SECRET",
                    "endpoint_url_env": "F1_ENDPOINT",
                    "scopes": ["s3://retail/"],
                }
            },
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
    key_value, secret_value = "f1-synthetic-key", "f1's-synthetic-secret-with-quote"
    monkeypatch.setenv("F1_KEY_ID", key_value)
    monkeypatch.setenv("F1_SECRET", secret_value)
    monkeypatch.setenv("F1_ENDPOINT", "http://127.0.0.1:9")

    class EchoingFailure:
        """Proxy over the REAL owned connection: LOAD passes through, the
        first CREATE SECRET fails with an error that echoes its statement."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kwargs):
            if "CREATE SECRET" in sql:
                raise duckdb.IOException(f"Fake failure echoing statement: {sql}")
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_connect = duckdb.connect

    def connect(*args, **kwargs):
        return EchoingFailure(real_connect(*args, **kwargs))

    monkeypatch.setattr(duckdb, "connect", connect)
    registry = load_registry(registry_path)
    with pytest.raises(Exception) as refused:
        build_connection(registry)
    message = str(refused.value)
    assert "Fake failure echoing statement" in message  # the injected seam fired
    assert "CREATE SECRET ariadne_local" in message  # the statement WAS echoed
    # no recoverable credential material (spec 0025 §3/AC4): neither the RAW
    # value nor the SQL-DOUBLED-QUOTE form the echoed statement carries
    fx.assert_no_secret_values(message, [key_value, secret_value])
    assert secret_value.replace("'", "''") not in message  # the escaped form too
    assert key_value.replace("'", "''") not in message


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

        # fix finding 6 (spec 0025 §4): offline review with the endpoint
        # variable REMOVED reports the unresolved prerequisite explicitly —
        # never a crash, and the stored validation is not presented as current
        monkeypatch.delenv("ARIADE_S1_LOCAL_ENDPOINT", raising=False)
        unresolved_review = api.review_proposal(started["proposal"])
        assert unresolved_review["source_approval_state"] == "unresolved"
        assert unresolved_review["source_approved"] is False
        assert unresolved_review["validation_stale"] is True
        assert any("unresolved" in reason for reason in unresolved_review["stale_reasons"])
        monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", a.endpoint_url)

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
        # fix finding 3 (exact human authority, spec 0009 AC4 + spec 0025 §4):
        # identical candidate bytes, different effective endpoint — the review
        # digests differ, and A's reviewed digest can NEVER admit B
        assert review_b["review_digest"] != review_a["review_digest"]
        with pytest.raises(ValueError, match="review digest mismatch"):
            admission_module.admit_revision(
                project,
                started["proposal"],
                review_b["revision"],
                review_a["review_digest"],
                confirmed_by="human:test",
            )
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
        # fix finding 2 (spec 0025 §4/AC6): REMOVING the bindings block from a
        # profile-bearing admission is an incomplete pinned identity — it never
        # falls back to environment re-resolution at reconstruction
        stripped = dict(record_b)
        stripped.pop("storage_bindings")
        (project / CURRENT).write_text(json.dumps(stripped), encoding="utf-8")
        with pytest.raises(ValueError, match="incomplete"):
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


# ------------------------- fix pass (findings 4 and 5, spec 0025 §§4–5/AC6–7)


def test_stale_schema_observations_refuse_under_a_changed_endpoint(
    tmp_path, monkeypatch, builder_spy
):
    """Fix finding 4 (spec 0025 §4 measurement invalidation): schema/value
    observations refreshed under endpoint A carry A's effective-approval
    binding; after the endpoint changes to B (identical candidate bytes, B's
    own grant) validation REFUSES on the stale measurement provenance until
    the schema is refreshed under B. Real Git journey over the live fixture."""
    fx.require_docker()
    a, b = _endpoint_pair(tmp_path / "fixture")
    try:
        project = s3_git_project(tmp_path)
        api = AuthoringProject(project)
        _set_local(monkeypatch, a)
        profiles = {
            "local": {
                "type": "s3",
                "access_key_id_env": "ARIADE_S1_LOCAL_KEY_ID",
                "secret_access_key_env": "ARIADE_S1_LOCAL_SECRET",
                "endpoint_url_env": "ARIADE_S1_LOCAL_ENDPOINT",
                "scopes": ["s3://retail/"],
            }
        }
        started = api.start_proposal()
        revision = started["candidate_revision"]
        proposed = api.propose_sources(
            started["proposal"],
            revision,
            [
                {
                    "name": "events",
                    "type": "parquet",
                    "storage": "local",
                    "path": "s3://retail/orders/events.parquet",
                }
            ],
            profiles,
        )
        approved_a = api.approve_sources(
            started["proposal"], proposed["revision"], proposed["source_digest"]
        )
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
        # schema refreshed under A: the generated observations carry A's
        # effective-approval binding
        refreshed = api.refresh_schema(
            started["proposal"],
            edited["revision"],
            [{"source": "events", "catalog": None, "schema": "events", "table": "events"}],
        )
        assert refreshed["changed"] is True
        validated_a = api.validate_proposal(started["proposal"], refreshed["revision"])
        assert validated_a["ok"] is True
        assert validated_a["storage_bindings"]["local"]["endpoint"] == a.endpoint_url

        # endpoint change A→B with B's own grant and IDENTICAL candidate bytes
        _set_local(monkeypatch, b)
        api.approve_sources(
            started["proposal"], validated_a["revision"], proposed["source_digest"]
        )
        # approved_a binds the declaration under A — kept for the reader
        assert approved_a["storage_bindings"]["local"]["endpoint"] == a.endpoint_url
        stale = api.validate_proposal(started["proposal"], validated_a["revision"])
        assert stale["ok"] is False
        assert any(
            "bound to a different effective storage identity" in error
            and "refresh_schema" in error
            for error in stale["errors"]
        ), stale["errors"]

        # a fresh refresh under B rebinding the measurements clears the refusal
        refreshed_b = api.refresh_schema(
            started["proposal"],
            validated_a["revision"],
            [{"source": "events", "catalog": None, "schema": "events", "table": "events"}],
        )
        validated_b = api.validate_proposal(started["proposal"], refreshed_b["revision"])
        assert validated_b["ok"] is True, validated_b["errors"]
        assert validated_b["storage_bindings"]["local"]["endpoint"] == b.endpoint_url
    finally:
        fx.stop_pair(a, b)


def test_legacy_bundle_validation_binds_the_effective_endpoint(tmp_path, monkeypatch):
    """Fix finding 5 + blocker 2 (spec 0025 §§3-5/AC7): the LEGACY staged-bundle
    route binds its validation to the effective endpoint — a bundle validated
    under A never retries idempotently, reviews or Promotes after the
    environment resolves B — and validation MEASURES under the binding it
    records: an environment change between capture and audit cannot make the
    audit pass on B's valid grain while the state records A's duplicate grain.
    Real loopback S3 reads; the legacy human gates stay distinct."""
    from ariadne import authoring as legacy_authoring

    fx.require_docker()
    # BOTH endpoints share one credential set and one bucket name, so the SAME
    # URI resolves on either endpoint: the grain oracle distinguishes WHICH
    # endpoint validation measured, not merely whether some read failed.
    a = fx.S3Endpoint(tmp_path / "fixture", "retail", "legkey0001", "legsecret01", None).start()
    b = None
    try:
        b = fx.S3Endpoint(tmp_path / "fixture", "retail", "legkey0001", "legsecret01", None)
        b.start()
        unique_rows = [(1, "a"), (2, "b"), (3, "c")]
        duplicate_rows = [(1, "a"), (1, "a-duplicate"), (2, "b")]  # violates pk id
        a.put_parquet("retail/orders/events.parquet", unique_rows, ("id", "label"))
        b.put_parquet("retail/orders/events.parquet", unique_rows, ("id", "label"))
        profiles = {
            "local": {
                "type": "s3",
                "access_key_id_env": "LEGACY_F5_KEY_ID",
                "secret_access_key_env": "LEGACY_F5_SECRET",
                "endpoint_url_env": "LEGACY_F5_ENDPOINT",
                "scopes": ["s3://retail/"],
            }
        }

        def install_registry(project: Path) -> None:
            intake = project / "intake.yaml"
            intake.write_text(
                yaml.safe_dump(
                    {
                        "storages": profiles,
                        "sources": [
                            {
                                "name": "events",
                                "type": "parquet",
                                "storage": "local",
                                "path": "s3://retail/orders/events.parquet",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            installed = legacy_authoring.propose_sources(intake, project=project)
            legacy_authoring.approve_sources(installed["digest"], project=project)

        def set_env(endpoint) -> None:
            monkeypatch.setenv("LEGACY_F5_KEY_ID", endpoint.access_key)
            monkeypatch.setenv("LEGACY_F5_SECRET", endpoint.secret_key)
            monkeypatch.setenv("LEGACY_F5_ENDPOINT", endpoint.endpoint_url)

        # [phase 1] validated under A: the audit really read the S3 source
        set_env(a)
        (tmp_path / "phase1").mkdir(parents=True, exist_ok=True)
        project = scaffold_project(tmp_path / "phase1")
        install_registry(project)
        submission_file = write_submission(project, bundle_submission())
        submitted = legacy_authoring.submit_bundle(submission_file, project=project)
        assert submitted["status"] == "validated", submitted.get("errors")
        digest = legacy_authoring.review_bundle(project=project)["digest"]

        # the endpoint environment changes to B: identical retry, review and
        # Promotion all refuse the A-measured validation (no idempotent reuse)
        set_env(b)
        with pytest.raises(ValueError, match="effective storage binding changed"):
            legacy_authoring.submit_bundle(submission_file, project=project)
        with pytest.raises(ValueError, match="effective storage binding changed"):
            legacy_authoring.review_bundle(project=project)
        with pytest.raises(ValueError, match="effective storage binding changed"):
            promote_bundle(
                digest, staging_root=project / "staging", served_root=project, assume_yes=True
            )
        assert not any(project.glob("context_layer/metrics/*"))  # nothing was served

        # [phase 2] blocker 2: an environment change BETWEEN the state's
        # binding capture and the audit — A now carries DUPLICATE grain, B
        # valid grain. Validation must measure the RECORDED binding (A) and
        # fail on A's duplicates; it can never pass by measuring B.
        a.put_parquet("retail/orders/events.parquet", duplicate_rows, ("id", "label"))
        b.put_parquet("retail/orders/events.parquet", unique_rows, ("id", "label"))
        set_env(a)
        (tmp_path / "phase2").mkdir(parents=True, exist_ok=True)
        project2 = scaffold_project(tmp_path / "phase2")
        install_registry(project2)

        # B is readable with the very credentials the flip supplies: the same
        # URI there serves the UNIQUE-grain rows, so a validation that wrongly
        # re-resolves the environment would PASS on B instead of failing on
        # A's duplicates (the discriminating oracle).
        set_env(b)
        probe = duckdb.connect()
        try:
            b._fixture_secret(probe)
            assert probe.execute(
                "SELECT count(*), sum(id) FROM read_parquet('s3://retail/orders/events.parquet')"
            ).fetchone() == (3, 6)
        finally:
            probe.close()
        set_env(a)

        real_validate = legacy_authoring.validate  # the seam submit_bundle calls
        calls: list[int] = []

        def flip_env_then_validate(tree, *args, **kwargs):
            calls.append(1)
            set_env(b)
            return real_validate(tree, *args, **kwargs)

        monkeypatch.setattr(legacy_authoring, "validate", flip_env_then_validate)
        try:
            measured = legacy_authoring.submit_bundle(
                write_submission(project2, bundle_submission()), project=project2
            )
        finally:
            monkeypatch.setattr(legacy_authoring, "validate", real_validate)
            set_env(a)
        assert calls == [1], "the endpoint flip must run on the caller's validate seam"
        assert measured["status"] == "invalid", measured.get("errors")
        assert any(
            "grain" in str(error).lower() and "events" in str(error)
            for error in measured.get("errors") or []
        ), measured.get("errors")
        # nothing validated means nothing promotable under the recorded A
        digest2 = legacy_authoring.review_bundle(project=project2)["digest"]
        with pytest.raises(ValueError, match="'invalid'"):
            promote_bundle(
                digest2, staging_root=project2 / "staging", served_root=project2, assume_yes=True
            )
    finally:
        a.stop()
        if b is not None:
            b.stop()
