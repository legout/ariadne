"""ODCS contract consumer: pin, Git journey, drift, authority, quality
semantics and evidence gates (issue #77 / C1; spec 2028 §§2–7, AC1–AC7).

Real temporary Git repositories (repo-local identity), real native DuckDB
catalog sources (the approved profile's native fixture; a legacy parquet
file-view variant serves the non-native-source guard case), the packaged
official schema pin and exact upstream official fixture bytes. Expected
values are hand-derived from the pinned sources and the fixture rows
(IDs 1/2/3, amounts 10/20/30 → COUNT 3, SUM 60.0, zero NULLs, zero negative
amounts) or asserted against the byte identities the spec records — never
copied from implementation output.
"""

import asyncio
import hashlib
import json
import os
import socket
import sys
from datetime import UTC, datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.sources  # noqa: E402
from ariadne import (  # noqa: E402 — after the sys.path bootstrap, like the sibling imports
    contract_inspection,  # pyright: ignore[reportAttributeAccessIssue] — new module, stale analysis index
    contracts,  # pyright: ignore[reportAttributeAccessIssue] — same
    proposals,
)
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.discovery import DiscoveryRuntime  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from tests.test_git_admission import admit, read_current  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    approved,
    branch_of,
    run_git,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SEED_NOTES = "# Seed notes\n\nAll orders count.\n"

# Byte identities recorded independently from the pinned sources (spec 0028
# §2 and the upstream commit f0bdad9): the packaged schema pin and the two
# official fixture documents. Byte pins are explicit reviewed changes — never
# regenerated from whatever a loader produces.
SCHEMA_SHA256 = "edb41f33ec46e84780e99872ab2bd67f074959d2bf3e9c9fc54e61f8982b0d93"
SCHEMA_BYTES = 110505
OFFICIAL_VALID_SHA256 = "da549b51a2887ee3ac95772a169004e9db455fc47c6795eaa0b9e73b906b9676"
OFFICIAL_FULL_SHA256 = "7a82af5da8d18962031c3a01b2706b6991dce7bd111e5fb9e0a3b214739e1031"

# The synthetic bundle: one orders parquet with hand-worked rows
# (1, 10.0, EMEA), (2, 20.0, AMER), (3, 30.0, EMEA) — COUNT 3, SUM 60.0,
# zero NULLs — plus a second labels table as an in-registry join temptation.
MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
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
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
    metrics:
      - name: order_count
        description: Count of all orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

TABLES_PAGE = (
    "---\n"
    "type: table\n"
    "title: Orders\n"
    "description: One row per order.\n"
    "tags: [table]\n"
    "sources:\n"
    "  - id: orders\n"
    "    resource: orders.main.orders\n"
    "    title: orders\n"
    "grain:\n"
    "  primary_key: [id]\n"
    "  cardinality_enforcement: STRICT_1_TO_1\n"
    "---\n\n"
    "# Orders\n"
)

REFERENCE_PAGE = (
    "---\n"
    "type: reference\n"
    "title: orders identity\n"
    "description: One reference page.\n"
    "tags: [reference]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# orders identity\n"
)

POLICY_PAGE = (
    "---\n"
    "type: policy\n"
    "status: draft\n"
    "title: All orders count\n"
    "description: The counting rule.\n"
    "tags: [policy]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# All orders count\n\n"
    "The rule body.\n"
)

METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "status: draft\n"
    "title: order_count\n"
    "description: Count of all orders.\n"
    "tags: [metric]\n"
    "sources:\n"
    "  - id: all-orders-count\n"
    "    resource: policies/all-orders-count.md\n"
    "    title: All orders count\n"
    "---\n\n"
    "# order_count\n"
)

SKILLS_PAGE = (
    "---\n"
    "type: skill\n"
    "title: run the demo\n"
    "description: One skill page.\n"
    "tags: [skill]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# run the demo\n"
)

# The producer contract over the hand-worked fixture: three properties
# (integer id required, number amount required, string region), physicalTypes
# only where the original type is reliably observable (int and double match
# the observed NATIVE catalog types after alias normalization), and two
# SQL-quality rules with hand-derived expectations (0 negative amounts;
# SUM 60). The duckdb server entry carries the official schema's required
# `database` property — inert producer metadata; the approved native source
# identity, never the server block, controls what opens.
ORDERS_CONTRACT = """\
apiVersion: v3.2.0
kind: DataContract
id: orders-contract
version: 1.0.0
name: orders
servers:
  - server: orders-duckdb
    type: duckdb
    database: orders
schema:
  - id: orders_object
    name: orders
    physicalType: table
    properties:
      - id: order_id
        name: id
        logicalType: integer
        physicalType: int
        required: true
      - id: order_amount
        name: amount
        logicalType: number
        physicalType: double
        required: true
      - id: order_region
        name: region
        logicalType: string
    quality:
      - type: sql
        query: SELECT COUNT(*) FROM {object} WHERE amount < 0
        mustBe: 0
        dimension: accuracy
      - type: sql
        query: SELECT SUM(amount) FROM {object}
        mustBe: 60
        dimension: accuracy
"""

ORDERS_BINDINGS = """\
version: 1
bindings:
  - id: orders-local
    contract_id: orders-contract
    contract_version: 1.0.0
    object_id: orders_object
    asset: {source: orders, catalog: orders, schema: main, table: orders}
    model: orders
    dataset: orders
    properties: {order_id: id, order_amount: amount, order_region: region}
    server_id: orders-duckdb
"""

# The file-view asset spelling for the non-native-source guard case (a
# duckdb-labelled contract bound to an approved PARQUET source).
PARQUET_BINDINGS = ORDERS_BINDINGS.replace(
    "asset: {source: orders, catalog: orders, schema: main, table: orders}",
    "asset: {source: orders, catalog: null, schema: orders, table: orders}",
)

# A four-field, schema-less ODCS document: document-valid, and by design
# never a source-compliance claim (spec 0028 §2 / AC1).
FOUR_FIELD_DOC = "apiVersion: v3.2.0\nkind: DataContract\nid: bare\nversion: 1.0.0\n"


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _insert_sql(table: str, arity: int) -> str:
    """One fully STATIC parameterized INSERT statement per arity (2–4
    fixture columns): no interpolation ever reaches the executor."""
    statements = {
        2: f"INSERT INTO {table} VALUES (?, ?)",
        3: f"INSERT INTO {table} VALUES (?, ?, ?)",
        4: f"INSERT INTO {table} VALUES (?, ?, ?, ?)",
    }
    return statements[arity]


def write_orders_parquet(path: Path, rows: list[tuple], columns: dict[str, str]) -> Path:
    """A real parquet file with explicit column types (NULLs expressible)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(columns)
    con = duckdb.connect()
    # test-fixture DDL over test-local column constants
    ddl = ", ".join(f"{name} {columns[name]}" for name in names)
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.execute(f"CREATE TABLE t({ddl})")
    # static statement from the arity map; row values ride as bound parameters
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.executemany(_insert_sql("t", len(names)), rows)
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    con.close()
    return path


def write_native_db(path: Path, table: str, columns: dict[str, str], rows: list[tuple]) -> Path:
    """A real native DuckDB catalog file whose table carries the exact
    ORIGINAL column types (the approved profile's native source; NULLs
    expressible through bound parameters)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)  # a rewrite replaces the catalog wholesale
    names = list(columns)
    con = duckdb.connect(str(path))
    # test-fixture DDL over test-local column constants
    ddl = ", ".join(f"{name} {columns[name]}" for name in names)
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.execute(f'CREATE TABLE main."{table}"({ddl})')
    # static statement from the arity map; row values ride as bound parameters
    # pi-lens-ignore: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
    con.executemany(_insert_sql(f'main."{table}"', len(names)), rows)
    con.close()
    return path


def contract_project(root: Path, *, native: bool = True, with_labels: bool = False) -> Path:
    """A real temporary Git data project whose human-created initial artifact
    revision is a complete existing bundle. The default fixture is the
    approved profile's NATIVE DuckDB source (a real catalog file with exact
    original types); ``native=False`` keeps the legacy parquet file-view
    variant for the non-native-source guard case."""
    project = root / "proj"
    project.mkdir(parents=True, exist_ok=True)
    rows = [(1, 10.0, "EMEA"), (2, 20.0, "AMER"), (3, 30.0, "EMEA")]
    columns = {"id": "INTEGER", "amount": "DOUBLE", "region": "VARCHAR"}
    if native:
        write_native_db(project / "data" / "orders.duckdb", "orders", columns, rows)
        registry = "sources:\n  - name: orders\n    type: duckdb\n    path: data/orders.duckdb\n"
        model_source = "orders.main.orders"
    else:
        write_orders_parquet(project / "data" / "orders.parquet", rows, columns)
        registry = "sources:\n  - name: orders\n    type: parquet\n    path: data/orders.parquet\n"
        model_source = "orders.orders"
    if with_labels:  # an in-registry join temptation for the authority checks
        write_native_db(
            project / "data" / "labels.duckdb",
            "labels",
            {"event_id": "INTEGER", "tag": "VARCHAR"},
            [(1, "x"), (1, "y"), (2, "z")],
        )
        registry += "  - name: labels\n    type: duckdb\n    path: data/labels.duckdb\n"
    (project / "ariadne.yaml").write_text(registry, encoding="utf-8")
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (project / "semantic_layer" / "models").mkdir(parents=True, exist_ok=True)
    model = MODEL_YML.replace("source: orders.main.orders", f"source: {model_source}")
    (project / "semantic_layer" / "models" / "orders.yml").write_text(model, encoding="utf-8")
    pages = {
        "context_layer/tables/orders.md": TABLES_PAGE,
        "context_layer/references/joins/orders--orders.md": REFERENCE_PAGE,
        "context_layer/policies/all-orders-count.md": POLICY_PAGE,
        "context_layer/metrics/order_count.md": METRIC_PAGE,
        "context_layer/skills/run-the-demo.md": SKILLS_PAGE,
    }
    for rel, content in pages.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    scope = ["ariadne.yaml", "data/seed_notes.md", "semantic_layer/models/orders.yml", *pages]
    run_git(project, "add", "--", *scope)
    run_git(project, "commit", "-q", "-m", "human: complete existing bundle", "--", *scope)
    return project


def contracted(
    api: AuthoringProject,
    started: dict,
    contract: str | None = ORDERS_CONTRACT,
    bindings: str = ORDERS_BINDINGS,
) -> str:
    """Submit the contract document and binding file as typed edits; returns
    the revision to validate against."""
    revision = started["candidate_revision"]
    if contract is not None:
        edited = api.edit_proposal(
            started["proposal"],
            revision,
            {"kind": "contract", "name": "orders-contract", "content": contract},
        )
        revision = edited["revision"]
    bound = api.edit_proposal(
        started["proposal"],
        revision,
        {"kind": "contract_bindings", "content": bindings},
    )
    return bound["revision"]


# ------------------------------------------------------- [1] the standard pin


def test_pinned_document_validation_is_offline_and_version_exact(tmp_path, monkeypatch):
    """AC1: the packaged pin is exactly the recorded official bytes; official
    fixtures validate deterministically offline; a different apiVersion, a
    malformed document, duplicate scoped IDs and dangling internal references
    each fail their DISTINCT checks; the schema-less four-field case is
    document-valid but never source-compliant."""
    packaged = (
        resources.files("ariadne")
        .joinpath("schemas")
        .joinpath("odcs")
        .joinpath("odcs-json-schema-v3.2.0.json")
        .read_bytes()
    )
    assert len(packaged) == SCHEMA_BYTES
    assert hashlib.sha256(packaged).hexdigest() == SCHEMA_SHA256

    # offline: any socket construction fails loudly — source-free validation
    # needs no network, credentials or live database (spec 0028 §2)
    def no_network(*args, **kwargs):
        raise AssertionError("network access during source-free contract validation")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    official = (FIXTURES / "official-authoritative-definitions.odcs").read_text(encoding="utf-8")
    assert hashlib.sha256(official.encode("utf-8")).hexdigest() == OFFICIAL_VALID_SHA256
    document, result = contracts.validate_document(official, "official.odcs.yaml")
    assert result.valid is True and result.supported_version is True
    assert result.api_version == "v3.2.0"
    assert document is not None
    assert document["id"] == result.contract_id  # preserved producer identity
    # determinism: the same bytes validate to the same result
    again = contracts.validate_document(official, "official.odcs.yaml")[1]
    assert (again.valid, again.errors) == (result.valid, result.errors)

    # an OLDER apiVersion label is schema-accepted but refused by the explicit
    # consumer dispatch — visibly, offline
    older = official.replace("apiVersion: v3.2.0", "apiVersion: v3.1.0")
    result_older = contracts.validate_document(older, "older.odcs.yaml")[1]
    assert result_older.valid is False and result_older.supported_version is False
    assert any("outside the supported profile" in error for error in result_older.errors)

    # a malformed document fails the pinned schema with its own diagnostic
    malformed = official + "inventedMetric: 1\n"
    result_bad = contracts.validate_document(malformed, "malformed.odcs.yaml")[1]
    assert result_bad.valid is False
    assert any("inventedMetric" in error for error in result_bad.errors)

    # duplicate scoped IDs fail the DISTINCT semantic check beyond the schema
    duplicate_ids = (
        FOUR_FIELD_DOC + "schema:\n  - id: same\n    name: a\n  - id: same\n    name: b\n"
    )
    result_dup = contracts.validate_document(duplicate_ids, "dup.odcs.yaml")[1]
    assert result_dup.valid is False
    assert any("duplicate scoped id" in error for error in result_dup.errors)

    # dangling internal references fail their distinct check — pinned on the
    # official full example, whose receiver_types.type_code names an object
    # the document itself does not declare
    full = (FIXTURES / "official-full-example.odcs").read_text(encoding="utf-8")
    assert hashlib.sha256(full.encode("utf-8")).hexdigest() == OFFICIAL_FULL_SHA256
    result_full = contracts.validate_document(full, "full.odcs.yaml")[1]
    assert result_full.valid is False
    assert any(
        "dangling internal reference" in error and "receiver_types.type_code" in error
        for error in result_full.errors
    )

    # the pinned schema's combined-operator rejection retains its diagnostic
    # (upstream documentation says the two forms are equivalent; the pinned
    # oneOf refuses the combination — followed, not patched)
    combined = (
        FOUR_FIELD_DOC
        + "schema:\n"
        + "  - name: orders\n"
        + "    quality:\n"
        + "      - type: sql\n"
        + "        query: SELECT 1\n"
        + "        mustBeGreaterThan: 0\n"
        + "        mustBeLessThan: 100\n"
    )
    result_combined = contracts.validate_document(combined, "combined.odcs.yaml")[1]
    assert result_combined.valid is False
    assert any("mustBeGreaterThan" in error for error in result_combined.errors)

    # the four-field case is document-valid, and a stable binding against it
    # is explicitly unsupported — never a source-compliance claim
    result_bare = contracts.validate_document(FOUR_FIELD_DOC, "bare.odcs.yaml")[1]
    assert result_bare.valid is True and result_bare.supported_version is True
    for malformed_shape in ("schema: 1\n", "servers: 1\n", "schema: {name: orders}\n"):
        invalid = contracts.validate_document(FOUR_FIELD_DOC + malformed_shape, "shape.yaml")[1]
        assert invalid.valid is False and any("schema:" in error for error in invalid.errors)
    for malformed_binding in (
        "version: true\nbindings: []\n",
        "version: 1\n",
        "version: 1\nbindings: 0\n",
        "version: 1\nbindings: {}\n",
    ):
        assert contracts.validate_bindings_document(malformed_binding, "contract_bindings.yaml")[1]
    duplicate_servers = (
        FOUR_FIELD_DOC
        + "servers:\n"
        + "".join(
            f"  - id: duplicate\n    server: {name}\n    type: duckdb\n    database: orders\n"
            for name in ("one", "two")
        )
    )
    assert any(
        "duplicate scoped id" in error
        for error in contracts.validate_document(duplicate_servers, "servers.yaml")[1].errors
    )
    vendor = FOUR_FIELD_DOC + (
        "customProperties:\n  - property: vendor\n    value: [{id: same}, {id: same}]\n"
    )
    assert contracts.validate_document(vendor, "vendor.yaml")[1].valid is True
    arity = ORDERS_CONTRACT.replace(
        "    physicalType: table",
        "    relationships:\n"
        "      - from: [orders.id, orders.amount]\n"
        "        to: [orders.id]\n    physicalType: table",
    )
    assert any(
        "matching arity" in error
        for error in contracts.validate_document(arity, "arity.yaml")[1].errors
    )
    tree = tmp_path / "bundle"
    (tree / "contracts").mkdir(parents=True)
    (tree / "contracts" / "bare.odcs.yaml").write_text(FOUR_FIELD_DOC, encoding="utf-8")
    (tree / "contract_bindings.yaml").write_text(
        ORDERS_BINDINGS.replace("orders-contract", "bare").replace("orders_object", "ghost"),
        encoding="utf-8",
    )
    _evidence, errors = contract_inspection.static_contract_checks(tree)
    assert any(
        "no schema object with id 'ghost'" in error or "no valid contract document" in error
        for error in errors
    )


# ------------------------------------------- [2] the Git contract journey


def test_git_contract_journey_preserves_producer_and_requires_live_evidence(tmp_path, capsys):
    """AC2/AC6: the producer contract and native binding ride one complete Git
    candidate; the exact submitted bytes survive validation, review and
    admission; complete passing live evidence plus the human action admits;
    drifted proof and document-only retention behave distinctly."""
    project = contract_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(api, started)

    result = api.validate_proposal(started["proposal"], revision)
    assert result["ok"] is True and result["errors"] == []
    assert "contracts" in result["performed_checks"]
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    assert outcomes["contracts"] == "passed"
    evidence = result["contracts"]
    assert evidence["documents"][0]["id"] == "orders-contract"
    assert evidence["documents"][0]["version"] == "1.0.0"
    assert evidence["documents"][0]["ownership"] == "undeclared"  # not inferred
    (observation,) = evidence["observations"]
    assert observation["binding"] == "orders-local" and observation["outcome"] == "passed"
    kinds = {(req["kind"], req["outcome"]) for req in observation["requirements"]}
    assert ("field_required", "passed") in kinds  # zero NULLs, full dataset
    assert ("field_logical_type", "passed") in kinds
    assert ("quality_sql", "passed") in kinds

    # the producer's exact submitted bytes: reading the candidate and the
    # final commit returns them verbatim — observations never rewrote them
    read = proposals.read_artifact(project, started["proposal"], "contracts/orders-contract.yaml")
    assert read["content"] == ORDERS_CONTRACT
    assert branch_of(project, started["proposal"]) == result["revision"]

    review = api.review_proposal(started["proposal"])
    changed = {change["path"] for change in review["changes"]}
    assert {"contracts/orders-contract.yaml", "contract_bindings.yaml"} <= changed
    assert review["validation_stale"] is False

    # pre-admission discovery is source-free and honestly reports the absence
    pre = DiscoveryRuntime.open_project(project)
    pre_group = asyncio.run(pre.discover("orders"))["groups"]["contracts"]
    assert pre_group["status"] == "unavailable"

    assert admit(project, review) == 0
    _activated = json.loads(capsys.readouterr().out)
    current = read_current(project)
    view = current["contracts"]
    assert view["bindings"][0]["contract_id"] == "orders-contract"
    assert view["observations"][0]["observed_at"] == observation["observed_at"]
    snapshot = project / ".ariadne" / "snapshots" / current["commit"]
    assert (snapshot / "contracts" / "orders-contract.yaml").read_text(encoding="utf-8") == (
        ORDERS_CONTRACT
    )
    assert branch_of(project, started["proposal"]) == result["revision"]  # bytes unchanged

    # discovery serves ONLY the pinned snapshot's contract and as-of evidence
    discovery = DiscoveryRuntime.open_project(project)
    group = asyncio.run(discovery.discover("orders"))["groups"]["contracts"]
    assert group["status"] == "available"
    (item,) = group["items"]
    assert item["contract"] == {"id": "orders-contract", "version": "1.0.0"}
    assert item["binding"] == "orders-local"
    assert item["observation"]["observed_at"] == observation["observed_at"]
    assert item["observation"]["eligibility"] == "eligible"

    # list_datasets keeps its live catalog and annotates from the snapshot only
    runtime = QueryRuntime.open_project(project)
    datasets = asyncio.run(runtime.list_datasets())
    entry = next(d for d in datasets if d["source"] == "orders" and d["table"] == "orders")
    assert entry["contract"]["id"] == "orders-contract"
    assert entry["contract"]["observation"]["observed_at"] == observation["observed_at"]

    # drifted proof cannot admit: a type-mismatched contract fails validation
    # and the admission CLI refuses naming the contract observation
    drift_project = contract_project(tmp_path / "drift")
    drift_api = AuthoringProject(drift_project)
    drift_started = drift_api.start_proposal()
    approved(drift_api, drift_project, drift_started)
    drifted = contract_inspection_static_contract(drift_api, drift_started)
    assert drifted["ok"] is False
    assert any("field_logical_type" in error and "drift" in error for error in drifted["errors"])
    drift_review = drift_api.review_proposal(drift_started["proposal"])
    assert admit(drift_project, drift_review) == 1
    refused = json.loads(capsys.readouterr().err)
    assert "passing report" in refused["error"]["message"]

    # valid UNBOUND contracts are retained as documents without a
    # conformance claim and without inventing dependencies for other models
    unbound_project = contract_project(tmp_path / "unbound")
    unbound_api = AuthoringProject(unbound_project)
    docs_only = unbound_api.start_proposal()
    approved(unbound_api, unbound_project, docs_only)
    edited = unbound_api.edit_proposal(
        docs_only["proposal"],
        docs_only["candidate_revision"],
        {"kind": "contract", "name": "orders-contract", "content": ORDERS_CONTRACT},
    )
    unbound_result = unbound_api.validate_proposal(docs_only["proposal"], edited["revision"])
    assert unbound_result["ok"] is True
    assert unbound_result["contracts"]["bindings"] == []
    assert unbound_result["contracts"]["documents"][0]["valid"] is True
    unbound_review = unbound_api.review_proposal(docs_only["proposal"])
    assert admit(unbound_project, unbound_review) == 0
    assert read_current(unbound_project)["contracts"]["bindings"] == []
    unbound_discovery = DiscoveryRuntime.open_project(unbound_project)
    (document_only,) = asyncio.run(unbound_discovery.discover("orders"))["groups"]["contracts"][
        "items"
    ]
    assert document_only["binding"] is None and document_only["observation"] is None
    bounded = asyncio.run(unbound_discovery.discover("orders", limit=0))["groups"]["contracts"]
    assert bounded["items"] == [] and bounded["complete"] is False
    assert (
        asyncio.run(unbound_discovery.discover("unmatched"))["groups"]["contracts"]["items"] == []
    )

    # Initial inventory in an already initialized, unborn Git repo includes
    # both suffixes and the fixed binding; typed reads/edits retain .yml.
    initial = tmp_path / "initial"
    (initial / "contracts").mkdir(parents=True)
    (initial / "contracts" / "orders.yml").write_text(ORDERS_CONTRACT)
    (initial / "contracts" / "bare.yaml").write_text(FOUR_FIELD_DOC)
    (initial / "contract_bindings.yaml").write_text("version: 1\nbindings: []\n")
    run_git(initial, "init", "-q")
    run_git(initial, "config", "user.name", "Ariadne Tests")
    run_git(initial, "config", "user.email", "tests@ariadne.local")
    initial_api = AuthoringProject(initial)
    inherited = initial_api.start_proposal()
    assert {rel for rel, _ in proposals.scope_blobs(initial, inherited["candidate_revision"])} == {
        "contracts/orders.yml",
        "contracts/bare.yaml",
        "contract_bindings.yaml",
    }
    for name in ("orders", "orders.yml"):
        assert (
            initial_api.read_artifact(inherited["proposal"], {"kind": "contract", "name": name})[
                "content"
            ]
            == ORDERS_CONTRACT
        )
    edited_yml = initial_api.edit_proposal(
        inherited["proposal"],
        inherited["candidate_revision"],
        {
            "kind": "contract",
            "name": "orders",
            "content": ORDERS_CONTRACT + "description: preserved suffix\n",
        },
    )
    assert edited_yml["path"] == "contracts/orders.yml"
    with pytest.raises(ValueError, match="collision"):
        initial_api.edit_proposal(
            inherited["proposal"],
            edited_yml["revision"],
            {"kind": "contract", "name": "orders.yaml", "content": ORDERS_CONTRACT},
        )


def contract_inspection_static_contract(api: AuthoringProject, started: dict) -> dict:
    """Submit a type-mismatched producer contract (region declared integer)
    and validate: the failed envelope."""
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace(
            "      - id: order_region\n        name: region\n        logicalType: string",
            "      - id: order_region\n        name: region\n        logicalType: integer",
        ),
    )
    return api.validate_proposal(started["proposal"], revision)


# ------------------------------------------------------ [3] schema drift


def test_bound_schema_and_required_null_drift_are_explicit(tmp_path):
    """AC3: the independently declared fixture passes; a removed column, an
    integer→string change and a NULL in a required column are actionable
    drift naming the contract; unverifiable physical metadata never passes."""
    assert contracts.logical_type_matches("number", "DECIMAL(12,2)[]")[0] != "passed"
    for native in ("TIMESTAMP_S", "TIMESTAMP_MS", "TIMESTAMP_NS", "TIMESTAMP WITH TIME ZONE"):
        assert contracts.logical_type_matches("timestamp", native)[0] == "passed"
    assert contracts.compare_physical_type("TIMESTAMP_MS", "TIMESTAMP_NS")[0] == "drift"
    project = contract_project(tmp_path)
    api = AuthoringProject(project)

    # the passing baseline: IDs 1/2/3, amounts 10/20/30, zero NULLs
    started = api.start_proposal()
    approved(api, project, started)
    result = api.validate_proposal(started["proposal"], contracted(api, started))
    assert result["ok"] is True

    orders_db = project / "data" / "orders.duckdb"

    # A one-table transformed projection is not the same physical dataset.
    tree = project / proposals.WORKTREES_REL / started["proposal"]
    model = tree / "semantic_layer" / "models" / "orders.yml"
    original = model.read_text()
    model.write_text(
        original.replace(
            "source: orders.main.orders",
            "source: SELECT id, -amount AS amount, region FROM orders.main.orders",
        )
    )
    assert any(
        "unsupported" in error for error in contract_inspection.static_contract_checks(tree)[1]
    )
    model.write_text(original)

    # a required column removed from the source: contract drift names it
    write_native_db(
        orders_db,
        "orders",
        {"id": "INTEGER", "region": "VARCHAR"},
        [(1, "EMEA"), (2, "AMER"), (3, "EMEA")],
    )
    removed = api.start_proposal()
    approved(api, project, removed)
    removed_result = api.validate_proposal(removed["proposal"], contracted(api, removed))
    assert removed_result["ok"] is False
    assert any(
        "field_presence" in error and "drift" in error and "'amount'" in error
        for error in removed_result["errors"]
    )
    # observations never rewrite the contract — the submitted bytes stand
    assert (
        proposals.read_artifact(project, removed["proposal"], "contracts/orders-contract.yaml")[
            "content"
        ]
        == ORDERS_CONTRACT
    )

    # an integer column changed to a string: type drift, not coercion
    write_native_db(
        orders_db,
        "orders",
        {"id": "VARCHAR", "amount": "DOUBLE", "region": "VARCHAR"},
        [("1", 10.0, "EMEA"), ("2", 20.0, "AMER"), ("3", 30.0, "EMEA")],
    )
    retyped = api.start_proposal()
    approved(api, project, retyped)
    retyped_result = api.validate_proposal(retyped["proposal"], contracted(api, retyped))
    assert retyped_result["ok"] is False
    assert any(
        "field_logical_type" in error
        and "drift" in error
        and "integer" in error
        and "VARCHAR" in error
        for error in retyped_result["errors"]
    )

    # a NULL in a required column: full-dataset NULL count is drift
    write_native_db(
        orders_db,
        "orders",
        {"id": "INTEGER", "amount": "DOUBLE", "region": "VARCHAR"},
        [(1, 10.0, "EMEA"), (2, None, "AMER"), (3, 30.0, "EMEA")],
    )
    nulled = api.start_proposal()
    approved(api, project, nulled)
    nulled_result = api.validate_proposal(nulled["proposal"], contracted(api, nulled))
    assert nulled_result["ok"] is False
    assert any(
        "field_required" in error and "drift" in error and "1 NULL row" in error
        for error in nulled_result["errors"]
    )

    # unverifiable physical metadata (a declared width the observation cannot
    # confirm) is unsupported — never a coerced pass
    width_project = contract_project(tmp_path / "width")
    width_api = AuthoringProject(width_project)
    width_started = width_api.start_proposal()
    approved(width_api, width_project, width_started)
    width_result = width_api.validate_proposal(
        width_started["proposal"],
        contracted(
            width_api,
            width_started,
            contract=ORDERS_CONTRACT.replace(
                "      - id: order_region\n        name: region\n        logicalType: string",
                "      - id: order_region\n        name: region\n        logicalType: string\n"
                "        physicalType: varchar(2)",
            ),
        ),
    )
    assert width_result["ok"] is False
    assert any(
        "field_physical_type" in error and "unsupported" in error
        for error in width_result["errors"]
    )


# --------------------------- [4] permission, unavailability and SQL authority


@pytest.fixture
def connection_spy(monkeypatch):
    """Record every registry handed to THE shared connection builder."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True, deadline=None, **selection):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only, deadline=deadline, **selection)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    return opened


def test_contract_source_and_sql_authority_precedes_execution(tmp_path, connection_spy):
    """AC4/AC5: a contract/server/binding alone opens nothing — missing
    permission refuses before inspection, the declared server address is
    never a connection instruction, out-of-profile SQL is refused BEFORE
    execution, and unavailable ≠ refused."""
    project = contract_project(tmp_path, with_labels=True)
    api = AuthoringProject(project)
    started = api.start_proposal()

    # missing permission refuses BEFORE inspection: nothing opens at all
    revision = contracted(api, started)
    with pytest.raises(ValueError, match="NO operator approval"):
        api.validate_proposal(started["proposal"], revision)
    assert connection_spy == []

    # approval binds the CURRENT candidate revision (the contract edits moved
    # it past `started`) — the same helper contract as the other journeys
    approved(api, project, {**started, "candidate_revision": revision})
    result = api.validate_proposal(started["proposal"], revision)
    assert result["ok"] is True
    # only the APPROVED registry identity ever reached the builder: the
    # contract's duckdb server declaration opened nothing of its own
    approved_paths = {Path(entry).name for call in connection_spy for entry in call}
    assert approved_paths == {"orders.duckdb", "labels.duckdb"}
    assert [Path(path).name for path in connection_spy[-1]] == ["orders.duckdb"]
    opens_with_contracts = len(connection_spy)

    # out-of-profile SQL is refused BEFORE execution: joins over other
    # datasets, table functions, metadata catalogs and multi-statements
    # never run; each refusal names the authority boundary, and no new
    # source/endpoint is ever opened for them
    out_of_profile = [
        # a foreign relation join (labels lives in the same registry)
        "SELECT COUNT(*) FROM {object} o JOIN labels.main.labels l ON o.id = l.event_id",
        "SELECT COUNT(*) FROM {object} a JOIN {object} b ON a.id = b.id",
        "SELECT 60",
        "WITH unused AS (SELECT * FROM {object}) SELECT 60",
        # a raw file scan through a table function
        "SELECT COUNT(*) FROM read_csv('data/orders.duckdb')",
        # a metadata catalog read
        "SELECT COUNT(*) FROM information_schema.columns",
        # multiple statements
        "SELECT 1; SELECT 2",
    ]
    for query in out_of_profile:
        refused_project = contract_project(tmp_path / f"refused-{abs(hash(query)) % 9973}")
        refused_api = AuthoringProject(refused_project)
        refused_started = refused_api.start_proposal()
        approved(refused_api, refused_project, refused_started)
        refused_result = refused_api.validate_proposal(
            refused_started["proposal"],
            contracted(
                refused_api,
                refused_started,
                contract=quality_contract([(query, "mustBe", 0)]),
            ),
        )
        assert refused_result["ok"] is False, query
        assert any(
            "quality_sql" in error and "refused" in error for error in refused_result["errors"]
        ), query
    # the refusals never opened anything beyond the approved identity —
    # every later builder call still carries exactly the approved registry
    assert connection_spy, "each refused validation still only opened approved identity"
    for call in connection_spy[opens_with_contracts:]:
        assert {Path(entry).name for entry in call} <= approved_paths

    # a non-DuckDB producer server is dialect-unsupported, never transpiled
    # or opened: the contract's postgres address is inert metadata (the
    # official schema's PostgresServer required fields make the document
    # structurally valid — the refusal is the DIALECT, not the document)
    postgres_project = contract_project(tmp_path / "postgres")
    postgres_api = AuthoringProject(postgres_project)
    postgres_started = postgres_api.start_proposal()
    approved(postgres_api, postgres_project, postgres_started)
    postgres_contract = quality_contract(
        [("SELECT COUNT(*) FROM {object}", "mustBe", 3)], server_type="postgresql"
    )
    postgres_result = postgres_api.validate_proposal(
        postgres_started["proposal"], contracted(postgres_api, postgres_started, postgres_contract)
    )
    assert postgres_result["ok"] is False
    assert any(
        "unsupported" in error and "postgresql" in error for error in postgres_result["errors"]
    )

    # a duckdb-LABELLED contract over an approved NON-NATIVE source: the
    # producer server says duckdb and the document is fully schema-valid,
    # but the bound approved source is a parquet file view — SQL-quality
    # rules are unsupported (spec 0028 §5), while the schema-only checks on
    # that source keep their ordinary supported outcomes
    parquet_project = contract_project(tmp_path / "parquet", native=False)
    parquet_api = AuthoringProject(parquet_project)
    parquet_started = parquet_api.start_proposal()
    approved(parquet_api, parquet_project, parquet_started)
    parquet_result = parquet_api.validate_proposal(
        parquet_started["proposal"],
        contracted(parquet_api, parquet_started, bindings=PARQUET_BINDINGS),
    )
    assert parquet_result["ok"] is False
    assert any(
        "quality_sql" in error
        and "unsupported" in error
        and "parquet" in error
        and "NATIVE DuckDB" in error
        for error in parquet_result["errors"]
    )
    # Projected adapter types cannot prove ORIGINAL physical types. Logical
    # families and full-dataset NULL checks remain independently supported.
    assert any(
        "field_physical_type" in error and "unsupported" in error
        for error in parquet_result["errors"]
    )
    (parquet_observation,) = parquet_result["contracts"]["observations"]
    field_outcomes = {
        req["outcome"]
        for req in parquet_observation["requirements"]
        if req["kind"] in ("field_logical_type", "field_required")
    }
    assert field_outcomes == {"passed"}

    # unavailable, never compliant: the operator's tightened execution ceiling
    # stops the contract observation — an honest unavailable outcome, distinct
    # from the permission refusal above
    tight_project = contract_project(tmp_path / "tight")
    registry = tight_project / "ariadne.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8") + "inspection:\n  execution_seconds: 0.0001\n",
        encoding="utf-8",
    )
    run_git(tight_project, "add", "--", "ariadne.yaml")
    run_git(
        tight_project,
        "commit",
        "-q",
        "-m",
        "human: tighten inspection ceiling",
        "--",
        "ariadne.yaml",
    )
    tight_api = AuthoringProject(tight_project)
    tight_started = tight_api.start_proposal()
    approved(tight_api, tight_project, tight_started)
    tight_result = tight_api.validate_proposal(
        tight_started["proposal"], contracted(tight_api, tight_started)
    )
    assert tight_result["ok"] is False
    assert any("unavailable" in error for error in tight_result["errors"])
    (tight_observation,) = tight_result["contracts"]["observations"]
    assert tight_observation["outcome"] == "incomplete"
    assert tight_observation["requirements"][0]["outcome"] == "unavailable"


def quality_contract(rules: list[tuple[str, str, object]], server_type: str = "duckdb") -> str:
    """A producer contract whose object maps ALL bound properties (static
    completeness holds) and carries exactly the given SQL rules. The server
    entries satisfy the official schema's per-type required fields
    (DuckdbServer: database; PostgresServer: host/port/database/schema) —
    inert producer metadata, never connection instructions."""
    server_fields = {
        "duckdb": "    database: orders",
        "postgresql": (
            "    host: inert-producer-metadata.example\n"
            "    port: 5432\n"
            "    database: orders\n"
            "    schema: public"
        ),
    }[server_type]
    lines = [
        "apiVersion: v3.2.0",
        "kind: DataContract",
        "id: orders-contract",
        "version: 1.0.0",
        "servers:",
        f"  - server: orders-duckdb\n    type: {server_type}\n{server_fields}",
        "schema:",
        "  - id: orders_object",
        "    name: orders",
        "    properties:",
        "      - id: order_id",
        "        name: id",
        "        logicalType: integer",
        "      - id: order_amount",
        "        name: amount",
        "        logicalType: number",
        "      - id: order_region",
        "        name: region",
        "        logicalType: string",
        "    quality:",
    ]
    for query, operator, operand in rules:
        rendered = repr(operand) if isinstance(operand, bool) else str(operand)
        lines += [
            f"      - type: sql\n        query: {json.dumps(query)}",
            f"        {operator}: {rendered}",
        ]
    return "\n".join(lines) + "\n"


# ------------------------------------------- [5] scalar quality semantics


def test_scalar_quality_obeys_pinned_comparison_and_result_semantics(tmp_path):
    """AC5: hand-worked expectations over amounts 10/20/30 (COUNT 3, SUM 60);
    strict comparisons and OPEN interval endpoints from the pinned quality
    documentation; bool/numeric, NULL, cardinality and shape rules."""
    project = contract_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    contract = quality_contract(
        [
            ("SELECT SUM(amount) FROM {object}", "mustBe", 60),  # 10+20+30
            ("SELECT SUM(amount) FROM {object}", "mustBe", 61),  # drift
            ("SELECT SUM(amount) FROM {object}", "mustBeGreaterThan", 59),
            # strict '>': 60 is NOT greater than 60 (pinned documentation)
            ("SELECT SUM(amount) FROM {object}", "mustBeGreaterThan", 60),
            ("SELECT SUM(amount) FROM {object}", "mustBeGreaterOrEqualTo", 60),
            ("SELECT SUM(amount) FROM {object}", "mustBeLessThan", 61),
            ("SELECT SUM(amount) FROM {object}", "mustBeLessOrEqualTo", 59),
            # pinned documentation: mustBeBetween [a, b] ≡ > a and < b — OPEN
            # endpoints: SUM 60 is NOT inside [10, 60], and its complement holds
            ("SELECT SUM(amount) FROM {object}", "mustBeBetween", [10, 60]),
            ("SELECT SUM(amount) FROM {object}", "mustBeBetween", [9, 61]),
            ("SELECT SUM(amount) FROM {object}", "mustNotBeBetween", [10, 60]),
            ("SELECT SUM(amount) FROM {object}", "mustNotBeBetween", [61, 100]),
            # bounds must be increasing — refused, never sorted or repaired
            ("SELECT SUM(amount) FROM {object}", "mustBeBetween", [100, 10]),
            # boolean results support same-type equality only
            ("SELECT COUNT(*) = 0 FROM {object} WHERE amount < 0", "mustBe", True),
            ("SELECT COUNT(*) = 0 FROM {object} WHERE amount < 0", "mustBe", 0),
            # NULL and wrong cardinality are evaluation errors
            ("SELECT SUM(amount) FROM {object} WHERE id > 100", "mustBe", 0),
            ("SELECT amount FROM {object}", "mustBe", 10),
            ("SELECT SUM(CAST(amount AS DECIMAL(18,2))) FROM {object}", "mustBe", 60),
            ("SELECT SUM(amount) FROM {object}", "mustBe", Decimal("60.000000000000001")),
            ("SELECT region FROM {object}", "mustBe", 0),
        ]
    )
    result = api.validate_proposal(started["proposal"], contracted(api, started, contract))
    assert result["ok"] is False  # the failing rules fail the candidate
    (observation,) = result["contracts"]["observations"]
    by_query = {}
    for req in observation["requirements"]:
        if req["kind"] == "quality_sql":
            by_query[(req["query"], _operator_of(req))] = req["outcome"]
    expected = {
        # (query, operator): hand-derived outcome over SUM 60
        ("SELECT SUM(amount) FROM {object}", "mustBe:60"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustBe:61"): "drift",
        ("SELECT SUM(amount) FROM {object}", "mustBeGreaterThan:59"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustBeGreaterThan:60"): "drift",
        ("SELECT SUM(amount) FROM {object}", "mustBeGreaterOrEqualTo:60"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustBeLessThan:61"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustBeLessOrEqualTo:59"): "drift",
        ("SELECT SUM(amount) FROM {object}", "mustBeBetween:[10, 60]"): "drift",
        ("SELECT SUM(amount) FROM {object}", "mustBeBetween:[9, 61]"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustNotBeBetween:[10, 60]"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustNotBeBetween:[61, 100]"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustBeBetween:[100, 10]"): "error",
        ("SELECT COUNT(*) = 0 FROM {object} WHERE amount < 0", "mustBe:true"): "passed",
        ("SELECT COUNT(*) = 0 FROM {object} WHERE amount < 0", "mustBe:0"): "unsupported",
        ("SELECT SUM(amount) FROM {object} WHERE id > 100", "mustBe:0"): "error",
        ("SELECT amount FROM {object}", "mustBe:10"): "error",
        ("SELECT SUM(CAST(amount AS DECIMAL(18,2))) FROM {object}", "mustBe:60"): "passed",
        ("SELECT SUM(amount) FROM {object}", "mustBe:60.000000000000001"): "drift",
        ("SELECT region FROM {object}", "mustBe:0"): "error",
    }
    for key, outcome in expected.items():
        assert by_query.get(key) == outcome, (key, outcome, by_query)

    # the {property} placeholder rides its exact checked binding: a
    # PROPERTY-level rule whose {property} is the mapped column
    placeholder_project = contract_project(tmp_path / "placeholder")
    placeholder_api = AuthoringProject(placeholder_project)
    placeholder_started = placeholder_api.start_proposal()
    approved(placeholder_api, placeholder_project, placeholder_started)
    placeholder_contract = ORDERS_CONTRACT.replace(
        "      - id: order_amount\n"
        "        name: amount\n"
        "        logicalType: number\n"
        "        physicalType: double\n"
        "        required: true",
        "      - id: order_amount\n"
        "        name: amount\n"
        "        logicalType: number\n"
        "        physicalType: double\n"
        "        quality:\n"
        "          - type: sql\n"
        "            query: SELECT COUNT(*) FROM {object} WHERE {property} IS NULL\n"
        "            mustBe: 0",
    )
    placeholder_result = placeholder_api.validate_proposal(
        placeholder_started["proposal"],
        contracted(placeholder_api, placeholder_started, placeholder_contract),
    )
    assert placeholder_result["ok"] is True, placeholder_result["errors"]
    (placeholder_observation,) = placeholder_result["contracts"]["observations"]
    property_rules = [
        req for req in placeholder_observation["requirements"] if req["kind"] == "quality_sql"
    ]
    assert len(property_rules) == 3  # object negative-count and SUM, property NULLs
    assert all(req["outcome"] == "passed" for req in property_rules)
    # an object-level rule using {property} is explicitly unsupported
    object_placeholder_project = contract_project(tmp_path / "object-placeholder")
    object_placeholder_api = AuthoringProject(object_placeholder_project)
    object_placeholder_started = object_placeholder_api.start_proposal()
    approved(object_placeholder_api, object_placeholder_project, object_placeholder_started)
    object_placeholder_contract = ORDERS_CONTRACT.replace(
        "    quality:\n",
        "    quality:\n"
        "      - type: sql\n"
        "        query: SELECT COUNT(*) FROM {object} WHERE {property} IS NULL\n"
        "        mustBe: 0\n",
    )
    object_placeholder_result = object_placeholder_api.validate_proposal(
        object_placeholder_started["proposal"],
        contracted(object_placeholder_api, object_placeholder_started, object_placeholder_contract),
    )
    assert object_placeholder_result["ok"] is False
    assert any(
        "{property} placeholder appears in an object-level rule" in error
        for error in object_placeholder_result["errors"]
    )


def _operator_of(requirement: dict) -> str:
    """The declared comparison of one quality requirement as a canonical
    ``operator:operand`` key (test-side derivation from the submitted rule,
    independent of the implementation's comparison)."""
    rule = requirement.get("rule") or {}
    for operator in contracts.QUALITY_OPERATORS:
        if operator in rule:
            operand = rule[operator]
            if isinstance(operand, bool):
                return f"{operator}:{str(operand).lower()}"
            return f"{operator}:{operand}"
    return "?"


# --------------------------------------------- [6] evidence dependency/age


def test_contract_evidence_dependency_and_age_gate(tmp_path, monkeypatch, capsys):
    """AC6: reuse retains the ORIGINAL observation time; a changed contract
    dependency or an expired observation re-observes; tightened budgets and
    unsupported required constraints can never become passed evidence; an
    expired observation blocks admission."""
    fixed = {"now": datetime.now(UTC)}
    monkeypatch.setattr(contract_inspection, "_observation_clock", lambda: fixed["now"])

    project = contract_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    first = api.validate_proposal(started["proposal"], contracted(api, started))
    assert first["ok"] is True
    observed_at = first["contracts"]["observations"][0]["observed_at"]
    assert observed_at == fixed["now"].isoformat(timespec="seconds")

    # an unrelated candidate change reuses the still-applicable observation
    # with its ORIGINAL time (no restamp, no repeated scan)
    page = api.edit_proposal(
        started["proposal"],
        first["revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "all-orders-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        },
    )
    second = api.validate_proposal(started["proposal"], page["revision"])
    assert second["ok"] is True
    (reused,) = second["contracts"]["observations"]
    assert reused["observed_at"] == observed_at
    assert reused.get("reused") is True

    # a changed contract dependency re-observes (never restamps): the clock
    # sits far in the past so the fresh measurement is deterministically OLD
    fixed["now"] = expired_time = datetime(2020, 1, 1, tzinfo=UTC)
    changed = api.edit_proposal(
        started["proposal"],
        second["revision"],
        {
            "kind": "contract",
            "name": "orders-contract",
            "content": ORDERS_CONTRACT + "description: {purpose: revised producer metadata}\n",
        },
    )
    third = api.validate_proposal(started["proposal"], changed["revision"])
    assert third["ok"] is True
    (fresh,) = third["contracts"]["observations"]
    assert fresh["observed_at"] == expired_time.isoformat(timespec="seconds")
    assert "reused" not in fresh

    # Expiry uses its own real proposal: no fourth changed-candidate round,
    # no reset/raise of MAX_ROUNDS. An identical stored report must remeasure.
    age_project = contract_project(tmp_path / "age")
    age_api = AuthoringProject(age_project)
    age_started = age_api.start_proposal()
    approved(age_api, age_project, age_started)
    old = age_api.validate_proposal(age_started["proposal"], contracted(age_api, age_started))
    assert old["ok"] is True
    fixed["now"] = datetime.now(UTC)
    renewed_result = age_api.validate_proposal(age_started["proposal"], old["revision"])
    assert renewed_result["ok"] is True
    (renewed_observation,) = renewed_result["contracts"]["observations"]
    assert renewed_observation["observed_at"] != expired_time.isoformat(timespec="seconds")
    assert "reused" not in renewed_observation

    # Source identity changes cannot transfer an old passing measurement to
    # a separately approved source with the same columns but failing data.
    moved_project = contract_project(tmp_path / "moved")
    moved_api = AuthoringProject(moved_project)
    moved = moved_api.start_proposal()
    approved(moved_api, moved_project, moved)
    before_move = moved_api.validate_proposal(moved["proposal"], contracted(moved_api, moved))
    assert before_move["ok"] is True
    write_native_db(
        moved_project / "data" / "replacement.duckdb",
        "orders",
        {"id": "INTEGER", "amount": "DOUBLE", "region": "VARCHAR"},
        [(1, 10.0, "EMEA"), (2, 20.0, "AMER"), (3, -30.0, "EMEA")],
    )
    moved_revision = proposals.edit_proposal(
        moved_project,
        moved["proposal"],
        before_move["revision"],
        "ariadne.yaml",
        "sources:\n  - name: orders\n    type: duckdb\n    path: data/replacement.duckdb\n",
    )["revision"]
    approved(moved_api, moved_project, {**moved, "candidate_revision": moved_revision})
    after_move = moved_api.validate_proposal(moved["proposal"], moved_revision)
    assert after_move["ok"] is False
    (moved_observation,) = after_move["contracts"]["observations"]
    assert "reused" not in moved_observation
    assert any(
        req["kind"] == "quality_sql" and req["outcome"] == "drift"
        for req in moved_observation["requirements"]
    )

    # A tighter execution budget does not invalidate completed historical
    # full-scope proof. A tighter OUTPUT ceiling still caps stored responses.
    bounds_project = contract_project(tmp_path / "bounds")
    bounds_api = AuthoringProject(bounds_project)
    bounds = bounds_api.start_proposal()
    approved(bounds_api, bounds_project, bounds)
    full = bounds_api.validate_proposal(bounds["proposal"], contracted(bounds_api, bounds))
    assert full["ok"] is True
    config = bounds_project / "ariadne.yaml"
    config.write_text(config.read_text() + "inspection:\n  execution_seconds: 0.0001\n")
    history = bounds_api.validate_proposal(bounds["proposal"], full["revision"])
    assert history["ok"] is True and history["idempotent"] is True
    assert (
        history["contracts"]["observations"][0]["observed_at"]
        == full["contracts"]["observations"][0]["observed_at"]
    )
    config.write_text(config.read_text() + "  response_bytes: 1\n")
    capped = bounds_api.validate_proposal(bounds["proposal"], full["revision"])
    assert capped["ok"] is False and "contracts" not in capped
    assert Path(capped["evidence"]).is_file()

    # Fresh oversized content is refused too, not merely labelled failed
    # while returning the full >64KiB quality-rule description.
    large_project = contract_project(tmp_path / "large")
    large_api = AuthoringProject(large_project)
    large = large_api.start_proposal()
    approved(large_api, large_project, large)
    long_rule = ORDERS_CONTRACT.replace(
        "        dimension: accuracy", "        description: " + "x" * 70000, 1
    )
    oversized = large_api.validate_proposal(
        large["proposal"], contracted(large_api, large, long_rule)
    )
    assert oversized["ok"] is False
    assert oversized["contracts"]["complete"] is False
    assert len(json.dumps(oversized["contracts"]).encode()) <= 64 * 1024
    assert Path(oversized["evidence"]).is_file()

    # Schema-valid string operands are unsupported, and their diagnostics
    # count toward §6's 64KiB ceiling too, including stored review responses.
    operand_project = contract_project(tmp_path / "large-operand")
    operand_api = AuthoringProject(operand_project)
    operand_started = operand_api.start_proposal()
    approved(operand_api, operand_project, operand_started)
    long_operand = "x" * 70000
    operand_contract = ORDERS_CONTRACT.replace(
        "mustBe: 0", f"mustBe: {json.dumps(long_operand)}", 1
    )
    operand_result = operand_api.validate_proposal(
        operand_started["proposal"],
        contracted(operand_api, operand_started, operand_contract),
    )
    stored = json.loads(Path(operand_result["evidence"]).read_text())
    assert any(long_operand in error and "unsupported" in error for error in stored["errors"])
    assert any(
        check["name"] == "contracts" and long_operand in check["detail"]
        for check in stored["report"]["checks"]
    )
    stored_review = operand_api.review_proposal(operand_started["proposal"])["report"]
    reused_result = operand_api.validate_proposal(
        operand_started["proposal"], operand_result["revision"]
    )
    for response in (operand_result, stored_review, reused_result):
        assert len(json.dumps(response).encode()) <= 64 * 1024
        assert response["ok"] is False and response["status"] == "invalid"
        assert any("truncated; see evidence reference" in error for error in response["errors"])
        assert Path(response["evidence"]).is_file()
        assert any(
            check["name"] == "contracts"
            and check["outcome"] == "failed"
            and "truncated; see evidence reference" in check["detail"]
            for check in response["report"]["checks"]
        )

    # an unsupported required constraint (enum) can never pass: the declared
    # requirement blocks validation instead of being silently dropped
    enum_project = contract_project(tmp_path / "enum")
    enum_api = AuthoringProject(enum_project)
    enum_started = enum_api.start_proposal()
    approved(enum_api, enum_project, enum_started)
    enum_result = enum_api.validate_proposal(
        enum_started["proposal"],
        contracted(
            enum_api,
            enum_started,
            contract=ORDERS_CONTRACT.replace(
                "      - id: order_region\n        name: region\n        logicalType: string",
                "      - id: order_region\n        name: region\n        logicalType: string\n"
                "        enum: [{value: EMEA}, {value: AMER}]",
            ).replace(
                "        logicalType: integer",
                "        logicalType: integer\n        unique: true",
                1,
            ),
        ),
    )
    assert enum_result["ok"] is False
    assert any("field_enum" in error and "unsupported" in error for error in enum_result["errors"])
    assert any(
        "field_unique" in error and "unsupported" in error for error in enum_result["errors"]
    )

    # an EXPIRED passing observation blocks admission under the operator's
    # 24h evidence-age budget, even though its revision validated
    fixed["now"] = datetime(2020, 1, 1, tzinfo=UTC)
    admission_project = contract_project(tmp_path / "admission")
    admission_api = AuthoringProject(admission_project)
    admission_started = admission_api.start_proposal()
    approved(admission_api, admission_project, admission_started)
    admission_result = admission_api.validate_proposal(
        admission_started["proposal"], contracted(admission_api, admission_started)
    )
    assert admission_result["ok"] is True  # the validation itself passed
    admission_review = admission_api.review_proposal(admission_started["proposal"])
    assert admit(admission_project, admission_review) == 1
    refused = json.loads(capsys.readouterr().err)
    assert "evidence-age budget" in refused["error"]["message"]
