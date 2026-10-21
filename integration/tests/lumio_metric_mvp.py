"""#81/spec0029 r2: real local native admission, strict profiles and 150 oracle.

Golden producer bytes remain untouched; test candidates use explicit Git edits.
All sources, publications, receipts and operator confirmations are synthetic/local.
"""

import asyncio
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — qualified test env is external
import yaml
from ariadne import (  # pyright: ignore[reportAttributeAccessIssue] — editor resolves the baseline checkout
    admission,
    lumio_context,
    query_results,
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
    run_git(tree, "add", "-f", "--", "knowledge")
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
        ("save_example", (
            {
                "question": "Revenue?",
                "interpretation": "Exclude cancelled orders.",
                "method": {"operation": "get_metric", "arguments": {"name": "revenue"}},
                "result": observed_result,
                "submitter": "human:synthetic-operator",
                "attestation": "Synthetic fixture meaning checked against the stated rule.",
                "sources": ["context_layer/metrics/revenue.md"],
            },
        )),
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
            assert catalog[0]["name"] == "revenue"
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
            assert json.loads(capsys.readouterr().out)[0]["name"] == "revenue"
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


def test_standalone_never_imports_optional_lumio(tmp_path):
    from tests.test_git_admission import admitted_ready
    from tests.test_git_authoring import POLICY_PAGE, complete_bundle_project

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(
        api,
        project,
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The standalone rule body."),
        },
    )
    admission.admit_revision(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        confirmed_by="human:standalone-operator",
    )
    script = """import asyncio, importlib.abc, sys
class NoLumio(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "lumio_wiki" or fullname.startswith("lumio_wiki."):
            raise AssertionError("standalone imported optional Lumio")
sys.meta_path.insert(0, NoLumio())
from ariadne.query import QueryRuntime
runtime = QueryRuntime.open_project(sys.argv[1])
try:
    result = asyncio.run(runtime.get_metric("event_count"))
    assert result["rows"] == [{"event_count": 3}]
finally:
    runtime.con.close()
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
