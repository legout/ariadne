"""#81/spec0029 r2: real local native admission, strict profiles and 150 oracle.

Golden producer bytes remain untouched; test candidates use explicit Git edits.
All sources, publications, receipts and operator confirmations are synthetic/local.
"""

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — qualified test env is external
from lumio_wiki.ariadne_context import (  # pyright: ignore[reportMissingImports]
    inspect_ariadne_candidate,
)
from lumio_wiki.source_references import (  # pyright: ignore[reportMissingImports]
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)

from ariadne.authoring import AuthoringProject
from tests.test_contracts import (
    ORDERS_BINDINGS,
    ORDERS_CONTRACT,
    contract_project,
    contracted,
    write_native_db,
)
from tests.test_git_authoring import approved, run_git, worktree_of

BASELINE = Path(__file__).parent / "fixtures" / "lumio_context_baseline"
NAMESPACE = "urn:demo:retail"
CONTROL = """version: 2
mode: categorized
categories:
  - name: policies
  - name: references
  - name: metrics
ontology:
  entity_types:
    policy: {}
    reference: {}
    metric: {}
"""
SELECTOR = """version: 1
mode: integrated
subtree: knowledge
namespace: urn:demo:retail
profile: ariadne-context/1
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


def content_project(root):
    """One native DuckDB source: completed100+50, cancelled25 => 150."""
    project = contract_project(root)
    write_native_db(
        project / "data" / "orders.duckdb",
        "orders",
        {"id": "INTEGER", "amount": "DOUBLE", "status": "VARCHAR"},
        [(1, 100.0, "completed"), (2, 50.0, "completed"), (3, 25.0, "cancelled")],
    )
    model = project / "semantic_layer" / "models" / "orders.yml"
    model.write_text(
        model.read_text()
        .replace("name: orders\n    description", "name: retail_sales\n    description")
        .replace("region", "status")
        .replace("order_count", "revenue")
        .replace("COUNT(*)", "SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)")
    )
    metric = project / "context_layer" / "metrics" / "order_count.md"
    metric.with_name("revenue.md").write_text(metric.read_text().replace("order_count", "revenue"))
    metric.unlink()
    (project / "data" / "seed_notes.md").write_text(
        "# Seed notes\n\nExclude cancelled orders from recognized revenue.\n"
    )
    kb = project / "knowledge"
    for rel in (
        "metrics/retail-revenue.md",
        "policies/retail-return-policy.md",
        "references/order-number.md",
    ):
        target = kb / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((BASELINE / rel).read_bytes())
    (kb / "lumio.yaml").write_text(CONTROL)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    (project / "context_integration.yaml").write_text(SELECTOR)
    run_git(
        project,
        "add",
        "--",
        "semantic_layer",
        "context_layer",
        "data/seed_notes.md",
        "knowledge",
        "context_integration.yaml",
    )
    run_git(project, "commit", "-q", "-m", "human: joint synthetic orders and original SDK inputs")
    return project


def native_candidate(root):
    project = content_project(root)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    contract = ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175")
    bindings = ORDERS_BINDINGS.replace("region", "status").replace(
        "model: orders", "model: retail_sales"
    )
    revision = contracted(api, started, contract=contract, bindings=bindings)
    return project, api, started, revision


def test_unsupported_ariadne_profile_refuses_before_publication(tmp_path):
    """The SDK-valid, unreferenced Reference must not be silently ignored."""
    project, api, started, revision = native_candidate(tmp_path)
    inspection = inspect_ariadne_candidate(
        str(worktree_of(project, started["proposal"]) / "knowledge"),
        revision,
        namespace=NAMESPACE,
    )
    assert inspection.diagnostics == (), "SDK input must be genuinely native-valid"
    validated = api.validate_proposal(started["proposal"], revision)
    other_errors = [error for error in validated["errors"] if "unsupported" not in error.lower()]
    assert other_errors == [], "An unrelated native contract/setup failure is not the expected red"
    assert not validated["ok"] and any(
        "unsupported" in error.lower() and "reference" in error.lower()
        for error in validated["errors"]
    ), "M1 must refuse the unsupported Reference profile before publication"
    assert not (project / ".ariadne" / "current.json").exists()
