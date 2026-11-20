"""#81/spec0029 r2: real local native admission, strict profiles and 150 oracle.

Golden producer bytes remain untouched; test candidates use explicit Git edits.
All sources, publications, receipts and operator confirmations are synthetic/local.
"""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — qualified test env is external
import yaml
from ariadne import (  # pyright: ignore[reportAttributeAccessIssue] — editor resolves the baseline checkout
    admission,
    authoring_sources,
    lumio_context,
    query_results,
    status,
)
from ariadne.authoring import AuthoringProject
from ariadne.cli import main as cli
from ariadne.discovery import DiscoveryRuntime
from ariadne.query import DeferredQueryRuntime, QueryRuntime
from lumio_wiki.ariadne_context import (  # pyright: ignore[reportMissingImports]
    inspect_ariadne_candidate,
)
from lumio_wiki.source_references import (  # pyright: ignore[reportMissingImports]
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from tests.test_contracts import (
    METRIC_PAGE,
    ORDERS_BINDINGS,
    ORDERS_CONTRACT,
    POLICY_PAGE,
    REFERENCE_PAGE,
    SKILLS_PAGE,
    TABLES_PAGE,
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
  - name: computations
ontology:
  entity_types:
    policy: {}
    computation: {}
    reference: {}
    metric: {}
"""
# C6 (spec0035): the revision-2 integrated selector — the §10.1 capability
# opt-in plus the authored binding inventory classifying the baseline metric
# closure (supported_candidate extends it when the candidate adds the
# cancellation Policy to the required closure).
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
    # Historical inert canaries prove native reads and refresh never maintain a classic mirror.
    for rel, payload in {
        "tables/orders.md": TABLES_PAGE,
        "references/joins/orders--orders.md": REFERENCE_PAGE,
        "policies/all-orders-count.md": POLICY_PAGE,
        "metrics/order_count.md": METRIC_PAGE,
        "skills/run-the-demo.md": SKILLS_PAGE,
    }.items():
        path = project / "context_layer" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
    for rel in ("metrics/order-count.md", "policies/all-orders-count.md"):
        (project / "knowledge" / rel).unlink()
    write_native_db(
        project / "data" / "orders.duckdb",
        "orders",
        {"id": "INTEGER", "amount": "DOUBLE", "status": "VARCHAR"},
        [(1, 100.0, "completed"), (2, 50.0, "completed"), (3, 25.0, "cancelled")],
    )
    model = project / "semantic_layer" / "models" / "orders.yml"
    model.write_text(
        model.read_text()
        .replace("name: orders\ndescription", "name: retail_sales\ndescription")
        .replace("region", "status")
        .replace("order_count", "revenue")
        .replace("COUNT(*)", "SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)")
    )
    model.rename(model.with_name("retail_sales.yml"))
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


# T2 (spec0029 §1.5): the Reference kind became supported through complete
# native validation, so the still-unsupported oracle is a genuinely
# producer-VALID `skill` profile — native base (title/description/tags/
# sources) only, no required_policies/metric_ref/core_ref — never a malformed
# kind. The producer's kind set is {dataset, table, reference, policy, metric,
# computation, skill} with NATIVE_REQUIRED_FIELDS["skill"] = the base tuple.
SKILL_PROFILE_PAGE = """---
id: "entity:run-the-demo"
title: "Run the Demo"
entity_types:
  - skill
tags:
  - demo
summary: "Operator steps for the synthetic local demo run."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "src-demo-runbook"
    title: "Demo runbook, 2026-10-05"
ariadne_profile:
  version: 1
  kind: skill
  native:
    type: skill
    title: "Run the Demo"
    description: "Operator steps for the synthetic local demo run."
    tags:
      - demo
    stale_after: 2027-06-30
    sources:
      - id: "src-demo-runbook"
        title: "Demo runbook, 2026-10-05"
---

# Run the Demo

The packaged runbook for the synthetic local demo.
"""


def test_unsupported_ariadne_profile_refuses_before_publication(tmp_path):
    """The SDK-valid, unreferenced profile must not be silently ignored."""
    project, api, started, revision = supported_candidate(tmp_path)
    tree = worktree_of(project, started["proposal"])
    (tree / "knowledge/skills").mkdir(parents=True, exist_ok=True)
    (tree / "knowledge/skills/run-the-demo.md").write_text(SKILL_PROFILE_PAGE)
    # the disposable candidate's KB control file must DECLARE the new category
    # and ontology type (CONTROL covers policies/references/metrics only) —
    # extended while preserving the accepted ontology_catalog, so the skill
    # page is genuinely producer-valid, never a malformed-kind oracle
    (tree / "knowledge/lumio.yaml").write_text(
        CONTROL.replace("  - name: metrics\n", "  - name: metrics\n  - name: skills\n").replace(
            "    metric: {}\n", "    metric: {}\n    skill: {}\n"
        )
        + yaml.safe_dump(
            {
                "ariadne_context": {
                    "version": 1,
                    "ontology_catalog": {"urn:demo:catalog": {"retail-hierarchy": "r7"}},
                }
            }
        )
    )
    revision = reconcile_knowledge(project, started["proposal"], revision)
    inspection = inspect_ariadne_candidate(
        str(worktree_of(project, started["proposal"]) / "knowledge"),
        revision,
        namespace=NAMESPACE,
    )
    assert inspection.diagnostics == (), "SDK input must be genuinely native-valid"
    validated = api.validate_proposal(started["proposal"], revision)
    checks = {check["name"]: check for check in validated["report"]["checks"]}
    native_checks = {
        "source_boundary",
        "structural",
        "compile",
        "conformance",
        "bind",
        "grain",
        "relationship_audit",
        "page_contract",
        "answer_examples",
        "citations",
        "mapping_evidence",
        "contracts",
    }
    assert native_checks <= checks.keys(), "The native validation report must be complete"
    assert {name: checks[name]["outcome"] for name in native_checks} == dict.fromkeys(
        native_checks, "passed"
    ), "An unrelated failed native check is not the expected red"
    assert validated["ok"] is False, "M1 must refuse the unsupported skill profile"
    assert len(validated["errors"]) == 1, "Only the unsupported KB profile may fail"
    artifact, _, cause = validated["errors"][0].partition(": ")
    assert artifact == "knowledge/skills/run-the-demo.md"
    assert re.search(
        r"\bunsupported\s+(?:Ariadne\s+)?profile(?:\s+kind)?\s+['\"]?skill\b",
        cause,
        flags=re.IGNORECASE,
    ), "The KB diagnostic must identify the unsupported Ariadne skill profile"
    assert not (project / ".ariadne" / "current.json").exists()

    # A supported kind must not hide an unsupported execution annotation either.
    project2, api2, started2, revision2 = supported_candidate(tmp_path / "extension")
    tree2 = worktree_of(project2, started2["proposal"])
    metric = tree2 / "knowledge/metrics/retail-revenue.md"
    meta, body = page_parts(metric)
    meta["ariadne_profile"]["native"]["attester"] = "authored-not-a-Core-receipt"
    write_page(metric, meta, body)
    revision2 = reconcile_knowledge(project2, started2["proposal"], revision2)
    assert (
        inspect_ariadne_candidate(
            str(tree2 / "knowledge"), revision2, namespace=NAMESPACE
        ).diagnostics
        == ()
    )
    refused = api2.validate_proposal(started2["proposal"], revision2)
    assert refused["ok"] is False
    assert refused["errors"] == [
        "knowledge/metrics/retail-revenue.md: unsupported technical Ariadne profile extension"
    ]


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
    stale_after: 2020-01-01
    verified:
      - by: human:synthetic-owner
        on: 2020-01-01
    sources:
      - id: human-cancellation-rule
        title: Synthetic operator rule
---

# Cancelled Orders

Exclude every order whose status is cancelled from recognized revenue.
Completed orders 100 and 50 count; cancelled order 25 does not. The sanctioned
OSI expression performs this exclusion; this narrative is not a SQL compiler.
"""


def page_parts(path):
    _empty, frontmatter, body = path.read_text().split("---", 2)
    return yaml.safe_load(frontmatter), body


def write_page(path, meta, body):
    path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False) + "---" + body)


def reconcile_knowledge(project, proposal, previous):
    tree = worktree_of(project, proposal)
    run_git(tree, "add", "-f", "--", "knowledge", "context_integration.yaml")
    run_git(tree, "commit", "-q", "-m", "human: explicitly adapt joint candidate knowledge")
    revision = run_git(tree, "rev-parse", "HEAD").strip()
    admission.reconcile(project, proposal, previous, revision)
    return revision


def supported_candidate(root):
    project, api, started, revision = native_candidate(root)
    tree = worktree_of(project, started["proposal"])
    reference = tree / "knowledge/references/order-number.md"
    meta, body = page_parts(reference)
    del meta["ariadne_profile"]  # visible Git candidate edit, never an input conversion
    write_page(reference, meta, body)
    (tree / "knowledge/policies/cancelled-orders.md").write_text(CANCELLATION)
    metric = tree / "knowledge/metrics/retail-revenue.md"
    meta, body = page_parts(metric)
    profile = meta["ariadne_profile"]
    profile["required_policies"].append(
        {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
    )
    # C6: the selector's authored binding inventory must classify the
    # candidate's COMPLETE closure — extend it with the cancellation Policy
    # bindings for the metric and its generated computation subject.
    selector = yaml.safe_load((tree / "context_integration.yaml").read_text())
    selector["policy_bindings"]["bindings"].extend(
        [
            {
                "subject": {"kind": "metric", "identity": "retail_sales::orders.revenue"},
                "policy": {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"},
                "operations": ["get_metric", "query_metrics"],
                "enforcement": None,
            },
        ]
    )
    (tree / "context_integration.yaml").write_text(
        yaml.safe_dump(selector, sort_keys=False), encoding="utf-8"
    )
    profile["native"]["sources"].append(
        {"id": "cancelled-orders", "resource": "policies/cancelled-orders.md"}
    )
    profile["ontology_refs"] = [
        {"namespace": "urn:demo:catalog", "identifier": "retail-hierarchy", "revision": "r7"}
    ]
    write_page(metric, meta, body + "\nCancelled orders are excluded per Cancelled Orders.\n")
    (tree / "knowledge/lumio.yaml").write_text(
        CONTROL
        + yaml.safe_dump(
            {
                "ariadne_context": {
                    "version": 1,
                    "ontology_catalog": {"urn:demo:catalog": {"retail-hierarchy": "r7"}},
                }
            }
        )
    )
    revision = reconcile_knowledge(project, started["proposal"], revision)
    return project, api, started, revision


def ready(root):
    project, api, started, revision = supported_candidate(root)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    assert validated["contracts"]["observations"][0]["outcome"] == "passed"
    review = api.review_proposal(started["proposal"])
    assert review["source_approved"] is True
    paths = {item["resource"] for item in review["files"]}
    assert {
        "context_integration.yaml",
        "knowledge/lumio.yaml",
        "knowledge/policies/cancelled-orders.md",
        "contracts/orders-contract.yaml",
        "contract_bindings.yaml",
        "semantic_layer/models/retail_sales.yml",
    } <= paths
    return project, api, review


def preview(project, review, destination, expected="none", scope=("public",)):
    return admission.overall_review(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        destination=destination,
        expected_current=expected,
        scope=scope,
    )


def activate(project, review, composite):
    return admission.admit_revision(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        confirmed_by="human:synthetic-operator",
        overall_preview=composite,
        confirmed_overall_digest=composite["digest"],
    )


def current_bytes(project):
    return (project / ".ariadne/current.json").read_bytes()


def revenue(runtime):
    result = asyncio.run(runtime.get_metric("revenue"))
    assert result["rows"] == [{"revenue": 150.0}]
    assert result["governed"] is True
    return result


def test_local_revenue_release_and_later_policy_isolation(tmp_path):
    project, api, review = ready(tmp_path)
    destination = tmp_path / "published"
    composite = preview(project, review, destination)
    assert not (project / ".ariadne/current.json").exists()
    assert not destination.exists()
    with pytest.raises(ValueError, match="composite confirmation"):
        admission.admit_revision(
            project,
            review["proposal"],
            review["revision"],
            review["review_digest"],
            confirmed_by="human:operator",
        )
    admitted = activate(project, review, composite)
    record, snapshot = admission.resolve_admission(project)
    manifest = record["bound_release"]
    assert manifest == composite["manifest"] == admitted["bound_release"]
    assert (
        manifest["knowledge"]["publication_manifest_digest"]
        == hashlib.sha256(
            (destination / "versions" / review["revision"] / "manifest.json").read_bytes()
        ).hexdigest()
    )
    assert (
        record["native_publication"]["manifest_digest"]
        == manifest["knowledge"]["source_reference_digest"]
    )
    assert record["native_publication"]["activated"] is True
    assert record["overall_confirmation"]["digest"] == composite["digest"]
    runtime = QueryRuntime.open_project(project)
    try:
        result = revenue(runtime)
        context = result["context"]
        assert context["attestation"] == "pending"
        assert "not independently value-attested" in context["governed_note"]
        assert CANCELLATION in context["policies"]
        assert (BASELINE / "policies/retail-return-policy.md").read_text() in context["policies"]
        assert len(context["policies"]) == 2
        assert "context_stale" in {w["code"] for w in context["context_signals"]["warnings"]}
        assert {c["entity_id"] for c in context["citations"]} == {
            "entity:retail-revenue",
            "entity:retail-return-policy",
            "entity:cancelled-orders",
        }
        assert all(c["published_version"] == review["revision"] for c in context["citations"])
        assert "data_signals" in result and result["result"]["complete"] is True
        # Full context is checked before SQL, not silently omitted for a tighter host budget.
        old_limits = runtime._limits
        runtime._limits = {**old_limits, "response_bytes": 1000}
        with pytest.raises(query_results.QueryResultError):
            revenue(runtime)
        runtime._limits = old_limits
        tree = worktree_of(project, review["proposal"])
        policy = tree / "knowledge/policies/cancelled-orders.md"
        policy.write_text(CANCELLATION + "\nLater reviewed policy text.\n")
        revised = reconcile_knowledge(project, review["proposal"], review["revision"])
        checked = api.validate_proposal(review["proposal"], revised)
        assert checked["ok"] is True, checked["errors"]
        later = api.review_proposal(review["proposal"])
        activate(project, later, preview(project, later, destination, review["revision"]))
        assert revenue(runtime)["context"] == context
        assert "Later reviewed policy text." not in "".join(context["policies"])
        assert (snapshot / "knowledge/policies/cancelled-orders.md").read_text() == CANCELLATION
    finally:
        runtime.con.close()


def test_composite_consent_binds_scope_build_and_full_previous_release(tmp_path, monkeypatch):
    project, _api, review = ready(tmp_path)
    destination = tmp_path / "published"
    original = preview(project, review, destination)
    altered = copy.deepcopy(original)
    altered["manifest"]["visibility_scope"] = ["public", "internal"]
    with pytest.raises(ValueError, match="composite confirmation"):
        activate(project, review, altered)
    root = lumio_context._module_root
    temporary_code = tmp_path / "reader.py"
    temporary_code.write_text("identity_changed = True\n")
    with monkeypatch.context() as m:
        m.setattr(
            lumio_context,
            "_module_root",
            lambda name: temporary_code if name == "lumio_wiki" else root(name),
        )
        with pytest.raises(
            ValueError,
            match=(
                r"^(?:composite review changed; )?integrated validation build "
                r"(?:identity|content) (?:changed|mismatch|does not match)[;: ].*\brevalidat"
            ),
        ):
            activate(project, review, original)
    activate(project, review, original)
    review = AuthoringProject(project).review_proposal(review["proposal"])
    # Same content commit, genuinely distinct scope/native destination bindings.
    stale = preview(project, review, tmp_path / "stale", scope=("public",))
    widened = preview(project, review, tmp_path / "widened", scope=("public", "internal"))
    activate(project, review, widened)
    previous = current_bytes(project)
    assert json.loads(previous)["commit"] == review["revision"]
    with pytest.raises(ValueError, match="composite review changed"):
        activate(project, review, stale)
    assert current_bytes(project) == previous


def test_corrupt_missing_or_mixed_release_refuses_before_sql(tmp_path, monkeypatch):
    project, _api, review = ready(tmp_path / "a")
    destination = tmp_path / "published-a"
    activate(project, review, preview(project, review, destination))
    project_b, _api_b, review_b = ready(tmp_path / "b")
    activate(project_b, review_b, preview(project_b, review_b, tmp_path / "published-b"))
    descriptor_path = project / ".ariadne/current.json"
    original = current_bytes(project)
    record = json.loads(original)
    other = json.loads(current_bytes(project_b))
    broken = copy.deepcopy(record)
    del broken["bound_release"]
    damaged = copy.deepcopy(record)
    damaged["bound_release"]["content_commit"] = "0" * 40
    mixed = copy.deepcopy(record)
    mixed["bound_release"] = other["bound_release"]
    from ariadne.execution import DuckDBExecution

    def no_execution(*args, **kwargs):
        raise AssertionError("invalid binding reached source construction/SQL")

    with monkeypatch.context() as m:
        m.setattr(DuckDBExecution, "__init__", no_execution)
        for invalid in (broken, damaged, mixed):
            descriptor_path.write_text(json.dumps(invalid))
            with pytest.raises(ValueError):
                QueryRuntime.open_project(project)
        descriptor_path.write_bytes(original)
        version_policy = (
            destination / "versions" / review["revision"] / "policies/cancelled-orders.md"
        )
        version_policy.write_text("corrupt pinned KB")
        with pytest.raises(Exception, match="[Vv]ersion|[Cc]ontext|[Ss]napshot"):
            QueryRuntime.open_project(project)


def test_hidden_required_policy_cannot_activate(tmp_path):
    project, api, review = ready(tmp_path)
    destination = tmp_path / "published"
    activate(project, review, preview(project, review, destination))
    previous = current_bytes(project)
    runtime = QueryRuntime.open_project(project)
    try:
        tree = worktree_of(project, review["proposal"])
        hidden_text = CANCELLATION.replace("visibility: public", "visibility: restricted").replace(
            "title: Cancelled Orders", "title: Hidden Trade Secret"
        )
        (tree / "knowledge/policies/cancelled-orders.md").write_text(hidden_text)
        revised = reconcile_knowledge(project, review["proposal"], review["revision"])
        checked = api.validate_proposal(review["proposal"], revised)
        assert checked["ok"] is True, checked["errors"]
        hidden = api.review_proposal(review["proposal"])
        with pytest.raises(ValueError, match="Policy Closure") as refused:
            preview(project, hidden, destination, review["revision"])
        assert "Hidden Trade Secret" not in str(refused.value)
        assert current_bytes(project) == previous
        result = revenue(runtime)
        assert "Hidden Trade Secret" not in json.dumps(result)
        assert CANCELLATION in result["context"]["policies"]
    finally:
        runtime.con.close()


def test_validation_build_change_requires_revalidation_before_preview(tmp_path, monkeypatch):
    """Spec0029 §§4–5: preview B cannot confer B's identity on A's validation."""
    code = tmp_path / "temporary-consumer-build.py"
    code.write_text("validated_build = 'A'\n")
    module_root = lumio_context._module_root
    monkeypatch.setattr(
        lumio_context,
        "_module_root",
        lambda name: code if name == "ariadne" else module_root(name),
    )
    project, api, review_a = ready(tmp_path / "content")
    assert all(check["outcome"] == "passed" for check in review_a["report"]["report"]["checks"]), (
        "Build A must pass the genuine native checks before drift"
    )
    validation_path = Path(review_a["report"]["evidence"])
    evidence_a = validation_path.read_bytes()
    destination = tmp_path / "published"
    preview_a = preview(project, review_a, destination)
    assert preview_a["manifest"]["content_commit"] == review_a["revision"]
    assert validation_path.read_bytes() == evidence_a
    assert not destination.exists()

    # The sole change between A validation/preview and B preview is these code bytes.
    code.write_text("validated_build = 'B'\n")
    with pytest.raises(
        ValueError,
        match=(
            r"^(?:composite review changed; )?integrated validation build "
            r"(?:identity|content) (?:changed|mismatch|does not match)[;: ].*\brevalidat"
        ),
    ):
        preview(project, review_a, destination)
    assert validation_path.read_bytes() == evidence_a, "Preview must not rewrite A evidence"
    assert not destination.exists()

    # Genuine B revalidation, not an idempotent A reuse or a preview-time restamp.
    refreshed = api.validate_proposal(review_a["proposal"], review_a["revision"])
    assert refreshed["ok"] is True, refreshed["errors"]
    assert refreshed.get("idempotent") is not True
    assert refreshed["revision"] == review_a["revision"]
    assert refreshed["artifact_digest"] == review_a["report"]["artifact_digest"]
    assert refreshed["source_digest"] == review_a["report"]["source_digest"]
    assert all(check["outcome"] == "passed" for check in refreshed["report"]["checks"])
    assert Path(refreshed["evidence"]).read_bytes() != evidence_a
    review_b = api.review_proposal(review_a["proposal"])
    preview_b = preview(project, review_b, destination)
    assert preview_b["manifest"]["execution"] != preview_a["manifest"]["execution"]
    assert (
        preview_b["manifest"]["core"]["validation_digest"]
        != preview_a["manifest"]["core"]["validation_digest"]
    )
    assert not destination.exists()


def test_same_location_build_content_change_refuses(tmp_path, monkeypatch):
    code = tmp_path / "temporary-sdk.py"
    code.write_text("reader = 1\n")
    root = lumio_context._module_root
    monkeypatch.setattr(
        lumio_context, "_module_root", lambda name: code if name == "lumio_wiki" else root(name)
    )
    project, _api, review = ready(tmp_path)
    identity = lumio_context.execution_identity()
    assert identity == lumio_context.execution_identity()
    activate(project, review, preview(project, review, tmp_path / "published"))
    DiscoveryRuntime.open_project(project)
    code.write_text("reader = 2\n")
    assert identity != lumio_context.execution_identity()
    with pytest.raises(ValueError, match="execution identity"):
        DiscoveryRuntime.open_project(project)


def test_post_publication_failure_preserves_binding_and_reports_receipt(tmp_path, monkeypatch):
    from lumio_wiki.location import (  # pyright: ignore[reportMissingImports]
        PublishedFilesystemLocation,
    )

    for fault in ("reader", "descriptor"):
        project, _api, review = ready(tmp_path / fault)
        destination = tmp_path / (fault + "-published")
        activate(project, review, preview(project, review, destination))
        review = AuthoringProject(project).review_proposal(review["proposal"])
        previous = current_bytes(project)
        new_destination = tmp_path / (fault + "-residue")
        composite = preview(project, review, new_destination)

        def fail(*args, **kwargs):
            raise OSError("assigned post-publication fault")

        with monkeypatch.context() as m:
            if fault == "reader":
                m.setattr(lumio_context, "open_context", fail)
            else:
                m.setattr(admission, "_publish_current", fail)
            with pytest.raises(lumio_context.OverallAdmissionError) as caught:
                activate(project, review, composite)
        outcome = caught.value.outcome
        assert outcome["integrated_activated"] is False
        assert outcome["publication_receipt"]["activated"] is True
        assert outcome["publication_receipt"]["version"] == review["revision"]
        assert (
            outcome["publication_receipt"]["manifest_digest"]
            == composite["manifest"]["knowledge"]["source_reference_digest"]
        )
        assert "publication_receipt" in str(caught.value)
        assert PublishedFilesystemLocation(new_destination).read_pointer() == review["revision"]
        assert current_bytes(project) == previous
        runtime = QueryRuntime.open_project(project)
        try:
            revenue(runtime)
        finally:
            runtime.con.close()


def test_capability_refusals_and_source_free_catalog(tmp_path, monkeypatch, capsys):
    project, _api, review = ready(tmp_path)
    activate(project, review, preview(project, review, tmp_path / "published"))
    runtime = QueryRuntime.open_project(project)
    discovery = DiscoveryRuntime.open_project(project)
    observed_result = revenue(runtime)

    def no_execution(*args, **kwargs):
        raise AssertionError("catalog/unsupported operation opened execution")

    deferred = DeferredQueryRuntime(no_execution, discovery)
    calls = [
        ("query_detail", ({"dataset": "orders", "fields": ["id"]},)),
        (
            "query_records",
            (
                {
                    "dataset": "orders.main.orders",
                    "fields": ["id"],
                    "order": [{"field": "id", "direction": "asc"}],
                },
            ),
        ),
        (
            "define_metric",
            (
                {
                    "name": "test_value",
                    "source": "orders.main.orders",
                    "expression": "SUM(amount)",
                    "description": "Temporary value",
                },
            ),
        ),
        (
            "save_example",
            (
                {
                    "question": "Revenue?",
                    "interpretation": "Exclude cancelled orders.",
                    "method": {"operation": "get_metric", "arguments": {"name": "revenue"}},
                    "result": observed_result,
                    "submitter": "human:synthetic-operator",
                    "attestation": "Synthetic fixture meaning checked against the stated rule.",
                    "sources": ["context_layer/metrics/revenue.md"],
                },
            ),
        ),
        ("search_examples", ("revenue",)),
    ]
    # Q2 (spec0029 §1.2): query_metrics and list_datasets left the unsupported
    # set — the two superseded refusals become their native supported behavior.
    # A2 (spec0029 §1.3): search_context/list_context_pages/read_context_page
    # serve through the pinned scoped SDK. T2 (spec0029 §1.5) also moves
    # resolve_term out of the unsupported set on a fresh matching integrated
    # admission — the dedicated reference journey proves that serving; the
    # remaining refusals stand.
    from ariadne.execution import DuckDBExecution
    from ariadne.planner import PlannerError

    try:
        with monkeypatch.context() as m:
            m.setattr(runtime._execution, "bind", no_execution)
            m.setattr(DuckDBExecution, "__init__", no_execution)
            catalog = asyncio.run(discovery.list_metrics())
            assert isinstance(catalog, list) and isinstance(catalog[0], dict)
            assert catalog[0]["name"] == "retail_sales::orders.revenue"
            assert (
                catalog[0]["bound_release"]
                == json.loads(current_bytes(project))["bound_release"]["digest"]
            )
            assert "define_metric" not in catalog[-1]
            assert asyncio.run(deferred.list_metrics()) == catalog
            groups = asyncio.run(deferred.discover("revenue"))["groups"]
            assert groups["metrics"]["status"] == "available"
            assert groups["contracts"]["status"] == "available"
            assert groups["pages"]["status"] == "available"  # A2 SDK navigation serves
            # T2 (spec0029 §1.5): resolve_term serves on a fresh matching
            # integrated admission; THIS release carries no structured
            # References, so the served group is available and empty
            assert groups["terms"]["status"] == "available"
            assert groups["terms"]["result"]["total_matches"] == 0
            assert groups["examples"]["status"] == "unavailable"
            # the live catalog serves with its approvals — never source-free
            datasets = asyncio.run(runtime.list_datasets())
            orders = next(d for d in datasets if d["table"] == "orders")
            assert orders["source"] == "orders" and {c["name"] for c in orders["columns"]} >= {
                "id",
                "amount",
                "status",
            }
            for name, args in calls:
                with pytest.raises(
                    ValueError, match=f"unsupported integrated MVP operation: {name}"
                ):
                    asyncio.run(getattr(runtime, name)(*args))
                with pytest.raises(
                    ValueError, match=f"unsupported integrated MVP operation: {name}"
                ):
                    asyncio.run(getattr(deferred, name)(*args))
            assert cli(["list-metrics", "--project", str(project)]) == 0
            assert json.loads(capsys.readouterr().out)[0]["name"] == "retail_sales::orders.revenue"
        # Q2 (spec0029 §1.2): the superseded refusals serve natively where
        # their native admission exists. This fixture pins no multi-fact
        # graph, so query_metrics now keeps the GRAPH-specific refusal (never
        # the old unsupported-operation one) while the CLI's live catalog
        # serves its approved tables — outside the spy block, both natively
        # construct their runtime.
        with pytest.raises(PlannerError) as graphless:
            asyncio.run(runtime.query_metrics({"metrics": ["revenue"]}))
        assert graphless.value.code == "not_admitted"
        assert cli(["list-datasets", "--project", str(project)]) == 0
        listed = json.loads(capsys.readouterr().out)
        assert next(d for d in listed if d["table"] == "orders")["source"] == "orders"
    finally:
        runtime.con.close()


# Independently authored old-format fixture bytes (retired standalone OKF page
# contract): old ``type: metric`` frontmatter, no producer profile, no native
# Knowledge Base state. Never a working legacy backend — refusal evidence only.
_LEGACY_OKF_METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "name: legacy_orders\n"
    "description: An old standalone OKF metric page of the retired context_layer path.\n"
    "---\n"
    "\n"
    "# legacy_orders\n"
    "\n"
    "Legacy fixture body in the retired standalone format.\n"
)


def _owned_tree_manifest(root: Path) -> dict[str, str]:
    """sha256 over every project/admission/snapshot file, excluding Git internals
    (HEAD and porcelain are captured and asserted separately)."""
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or ".git" in rel.parts:
            continue
        manifest[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _git_state(root: Path) -> tuple[str, list[str]]:
    head = run_git(root, "rev-parse", "HEAD").strip()
    porcelain = [line for line in run_git(root, "status", "--porcelain").splitlines() if line]
    return head, porcelain


def _assert_fresh_setup_refusal(exc: ValueError) -> None:
    """The written AC10 contract: the refusal names fresh setup/re-onboarding
    (never silent activation or conversion)."""
    message = str(exc).lower()
    assert "fresh" in message and "re-onboard" in message


def test_legacy_project_refuses_without_mutation(tmp_path, monkeypatch, capsys):
    """AC10 (spec0035 §6), replacing the retired inverse optional-SDK test.
    (A) A genuinely old standalone project — context_layer bytes, no native
    Control File/Source Reference Manifest/selector — refuses the actual
    runtime open paths and the scaffolder CLI with fresh-setup/re-onboarding
    guidance. (B) A VALID new-format working tree whose current-admission
    record pins an old-format snapshot without the required native identity
    refuses at the ADMISSION guard (not the project guard) with the same
    guidance, BEFORE any source setup. Neither attempt opens a database or
    executes SQL (boundary sentinel), and neither mutates the project,
    admission or snapshot bytes (pre/post sha256 manifest, HEAD, porcelain)."""
    import duckdb

    original_connect = duckdb.connect

    def _no_sql(*_args, **_kwargs):
        raise AssertionError("the AC10 refusal path must never open a database or execute SQL")

    def _forbid_sql():
        monkeypatch.setattr(duckdb, "connect", _no_sql)

    # ---------- (A) retired standalone project bytes
    legacy = tmp_path / "legacy-project"
    legacy.mkdir()
    run_git(legacy, "init", "-q")
    run_git(legacy, "config", "user.name", "Ariadne Tests")
    run_git(legacy, "config", "user.email", "tests@ariadne.local")
    legacy_page = legacy / "context_layer" / "metrics" / "legacy_orders.md"
    legacy_page.parent.mkdir(parents=True)
    legacy_page.write_text(_LEGACY_OKF_METRIC_PAGE, encoding="utf-8")
    (legacy / "README.md").write_text("old standalone project\n", encoding="utf-8")
    run_git(legacy, "add", "-A")
    run_git(legacy, "commit", "-q", "-m", "human: legacy standalone snapshot")

    _forbid_sql()
    before_manifest = _owned_tree_manifest(legacy)
    before_head, before_porcelain = _git_state(legacy)
    with pytest.raises(ValueError) as discovery_exc:
        DiscoveryRuntime.open_project(legacy)
    _assert_fresh_setup_refusal(discovery_exc.value)
    with pytest.raises(ValueError) as query_exc:
        QueryRuntime.open_project(legacy)
    _assert_fresh_setup_refusal(query_exc.value)
    from ariadne.init import main as init_main

    profile = tmp_path / "legacy-profile.json"
    init_args = [
        str(legacy),
        "--namespace",
        "urn:uuid:legacy-refusal",
        "--private-profile",
        str(profile),
    ]
    assert init_main(init_args) == 1
    init_err = capsys.readouterr().err.lower()
    assert "fresh" in init_err and "re-onboard" in init_err
    assert _owned_tree_manifest(legacy) == before_manifest
    assert _git_state(legacy) == (before_head, before_porcelain)

    # ---------- (B) valid new-format tree, old-format pinned admission
    monkeypatch.setattr(duckdb, "connect", original_connect)  # fixture setup may use DuckDB
    project = content_project(tmp_path / "b")  # passes the project guard
    legacy_bytes = tmp_path / "legacy-page.md"
    legacy_bytes.write_text(_LEGACY_OKF_METRIC_PAGE, encoding="utf-8")
    blob = run_git(project, "hash-object", "-w", str(legacy_bytes)).strip()
    tree_metrics = subprocess.run(
        ["git", "mktree"],
        cwd=project,
        input=f"100644 blob {blob}\tlegacy_orders.md\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree_root = subprocess.run(
        ["git", "mktree"],
        cwd=project,
        input=f"040000 tree {tree_metrics}\tcontext_layer\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    commit = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Ariadne Tests",
            "-c",
            "user.email=tests@ariadne.local",
            "commit-tree",
            tree_root,
            "-m",
            "human: legacy admission snapshot",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    snapshot = project / ".ariadne" / "snapshots" / commit / "context_layer" / "metrics"
    snapshot.mkdir(parents=True)
    (snapshot / "legacy_orders.md").write_text(_LEGACY_OKF_METRIC_PAGE, encoding="utf-8")
    from ariadne.validate import candidate_scope_digest

    record = {
        "route": "git-review-admission",
        "proposal": "p-legacy-admission-fixture",
        "commit": commit,
        "snapshot": f".ariadne/snapshots/{commit}",
        "artifact_digest": candidate_scope_digest(project / ".ariadne" / "snapshots" / commit),
        "review_digest": "e" * 64,
        "source_digest": "0" * 64,
        "sources": [],
        "validation": {},
        "confirmed": {},
    }
    current = project / ".ariadne" / "current.json"
    current.write_text(json.dumps(record, indent=2), encoding="utf-8")

    _forbid_sql()
    before_manifest = _owned_tree_manifest(project)
    before_head, before_porcelain = _git_state(project)
    with pytest.raises(ValueError) as admission_exc:
        QueryRuntime.open_project(project)
    # the ADMISSION guard refused (names the pinned legacy snapshot commit),
    # not the project-layout guard the valid working tree passes
    assert commit[:12] in str(admission_exc.value)
    _assert_fresh_setup_refusal(admission_exc.value)
    with pytest.raises(ValueError) as discovery_exc:
        DiscoveryRuntime.open_project(project)
    assert commit[:12] in str(discovery_exc.value)
    _assert_fresh_setup_refusal(discovery_exc.value)
    assert _owned_tree_manifest(project) == before_manifest
    assert _git_state(project) == (before_head, before_porcelain)


def test_admission_binding_checks_carry_postgres_destinations(tmp_path, monkeypatch):
    """a2 fix pass, review finding 2 (spec 0025 §4 disposition in spec0035
    §8): the serve-side admission binding checks compare the COMPLETE
    binding set — ``postgres:<source>`` destinations under their namespaced
    keys as well as S3 profile names. A destination-unbound historical
    record refuses for fresh human approval without rewriting it, a drifted
    destination refuses before any SQL, and a complete unchanged identity
    passes the binding checks; status inherits the same comparison through
    admission resolution instead of reporting a drifted binding as current.

    The journey is a REAL native admitted release (ready → preview →
    activate). A live postgres journey cannot run offline (validation opens
    every declared source), so for the postgres scenarios the admitted
    RECORD is namespace-shaped per the spec 0025 §4 record contract
    (declaration digest + credential-free destination binding + sources
    entry); the binding values are hand-written from the contract, never
    derived from the implementation. The release wrapper deliberately stays
    the original admit-time one, so a shaped record that PASSES the binding
    checks surfaces the later, out-of-scope release mismatch — that late
    refusal is the observable proving the binding checks accepted the
    complete set (a real integrated PG admission computes the same core
    binding at its own admit time and serves)."""
    project, api, review = ready(tmp_path)
    destination = tmp_path / "published"
    composite = preview(project, review, destination)
    activate(project, review, composite)
    record, _snapshot = admission.resolve_admission(project)  # the real release serves
    before = current_bytes(project)

    pg_env = "ARIADNE_TEST_PG_DSN"
    monkeypatch.setenv(pg_env, "postgresql://owner:pgsecret-a@db-a.internal:5432/app")
    entry = {"name": "pg", "type": "postgres", "connection_env": pg_env, "read_only": True}
    # hand-written from the spec 0025 §4 binding contract: a credential-free
    # destination is the ordered host/hostaddr/port lists plus dbname/user
    binding = {
        "host": ["db-a.internal"],
        "hostaddr": [],
        "port": ["5432"],
        "dbname": "app",
        "user": "owner",
    }
    declared = record.get("source_declaration_digest") or record["source_digest"]
    bindings = {"postgres:pg": binding}
    shaped = dict(record)
    shaped["sources"] = [*record["sources"], entry]
    shaped["storage_bindings"] = bindings
    shaped["source_digest"] = authoring_sources.approval_digest(declared, bindings)

    approvals = authoring_sources._load_approvals(project)
    approvals[shaped["source_digest"]] = {"source_digest": shaped["source_digest"]}
    authoring_sources._store_approvals(project, approvals)

    # unchanged destination: the COMPLETE binding set passes the admission
    # binding checks — any refusal must come from the later release-wrapper
    # integrity (out of scope here), never from a binding refusal
    with pytest.raises(ValueError, match="Bound Release"):
        admission.validate_admission_record(project, shaped)

    # a destination change under the SAME connection_env name refuses at the
    # binding comparison — before the release wrapper, before any SQL
    monkeypatch.setenv(pg_env, "postgresql://owner:pgsecret-b@db-b.internal:5432/app")
    with pytest.raises(ValueError, match="different effective storage binding"):
        admission.validate_admission_record(project, shaped)

    # a destination-unbound historical record (the old namespace: declaration
    # digest only) refuses for fresh approval and never rewrites the record
    unbound = dict(record)
    unbound["sources"] = [*record["sources"], entry]
    unbound["storage_bindings"] = {}
    unbound["source_digest"] = declared
    with pytest.raises(ValueError, match="incomplete"):
        admission.validate_admission_record(project, unbound)
    assert current_bytes(project) == before

    # status inherits the same complete comparison: the drifted on-disk
    # record is reported invalid with the binding reason — never as a
    # current destination
    (project / ".ariadne" / "current.json").write_text(json.dumps(shaped))
    report = status.build_report(argparse.Namespace(project=str(project)))
    assert report["ready"] is False
    assert "different effective storage binding" in report["ready_reason"]
    assert report["sources"]["selection"] != "admitted"
