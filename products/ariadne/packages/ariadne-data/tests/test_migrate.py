"""``ariadne migrate`` (spec 0039 §7, AC8/AC3): the retired Ossie 0.2 envelope is
converted through an Authoring Proposal; the admitted result answers the joint
example's hand-worked values (100 + 50 completed = 150 EUR; cancelled 25 excluded);
a second run is a no-op; an unconvertible project is left unchanged with a per-file
report. The legacy envelope below is the pre-0.3 fixture shape, written out as the
migration input."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import migrate  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402

LEGACY_RETAIL_SALES = """\
version: 0.2.0.dev0
semantic_model:
  - name: retail_sales
    description: Synthetic local retail orders
    datasets:
      - name: orders
        source: orders.main.orders
        primary_key: [id]
        fields:
          - name: id
            expression: {dialects: [{dialect: ANSI_SQL, expression: id}]}
          - name: amount
            expression: {dialects: [{dialect: ANSI_SQL, expression: amount}]}
          - name: status
            expression: {dialects: [{dialect: ANSI_SQL, expression: status}]}
            dimension: {}
    metrics:
      - name: revenue
        description: Recognized revenue in EUR, excluding cancelled orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)
      - name: completed_orders
        description: Count of orders not cancelled
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN status <> 'cancelled' THEN 1 ELSE 0 END)
"""

# the same model plus a metric with no expression: no mechanical conversion exists
# (spec 0039 §7.3), so the whole project must be left unchanged
UNCONVERTIBLE = LEGACY_RETAIL_SALES + (
    "      - name: no_expression\n        description: declares no expression at all\n"
)


# the baseline Policy page the joint fixture already carries (no new Policy is invented)
_RETURN_POLICY = (
    "required_policies:\n    - namespace: urn:demo:retail\n"
    "      entity_id: entity:retail-return-policy"
)


def _git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=project, check=True, capture_output=True, text=True
    ).stdout


def _add_context(project: Path, *, example_name: str = "revenue") -> None:
    """Existing Context a migration must carry: a block-YAML `metric_ref` whose `metric`
    precedes `model`, a system-generated Computation page under the old identity, and an
    Answer Example recording the old short metric name (citing a Policy page, which the
    migration does not touch)."""
    import hashlib

    from integration.tests.lumio_metric_mvp import (  # pyright: ignore[reportMissingImports] — needs PYTHONPATH=<repo root>
        page_parts,
        write_page,
    )

    from ariadne import answer_examples, context

    page = project / "knowledge" / "metrics" / "retail-revenue.md"
    page.write_text(
        page.read_text().replace(
            '    model: "retail_sales"\n    metric: "revenue"\n',
            '    metric: "revenue"\n    model: "retail_sales"\n',
        ),
        encoding="utf-8",
    )
    control = project / "knowledge" / "lumio.yaml"
    control.write_text(
        control.read_text()
        .replace("  - name: metrics\n", "  - name: metrics\n  - name: answer-examples\n")
        .replace("    metric: {}\n", "    metric: {}\n    answer-example: {}\n"),
        encoding="utf-8",
    )
    selector = project / "context_integration.yaml"  # Example pages need support_revision 4
    selector.write_text(
        selector.read_text().replace("support_revision: 2", "support_revision: 4"), encoding="utf-8"
    )
    computation = project / "knowledge" / "computations" / "revenue.md"
    computation.parent.mkdir(exist_ok=True)
    computation.write_text(
        context._build_native_computation_page(
            "revenue",
            {"model": "retail_sales", "dataset_sources": ["orders.main.orders"]},
            "SELECT 1",
        ),
        encoding="utf-8",
    )
    policy = (project / "knowledge" / "policies" / "retail-return-policy.md").read_bytes()
    result_json = (
        '{"columns":["revenue"],"governed":true,"metric":"revenue","rows":[{"revenue":150}]}'
    )
    record = {
        "question": "What was revenue?",
        "interpretation": "Recognized revenue.",
        "method": {"operation": "get_metric", "arguments": {"name": example_name}},
        "sql_provenance": {"source": answer_examples.SQL_PROVENANCE_SOURCE, "text": "SELECT 1"},
        "submitter": {"identity": "expert:dana", "attestation": "confirmed"},
        "citations": [
            {
                "path": "policies/retail-return-policy.md",
                "sha256": hashlib.sha256(policy).hexdigest(),
            }
        ],
        "answer": {
            "captured": "2026-11-01T00:00:00+00:00",
            "excerpt": result_json,
            "result_digest": "0" * 64,
        },
    }
    example = project / "knowledge" / "answer-examples" / "revenue-example.md"
    example.parent.mkdir(exist_ok=True)
    example.write_bytes(answer_examples._page_markdown(record, "revenue-example"))
    del page_parts, write_page  # imported only to fail early when the fixture module moves


def _legacy_project(root: Path, model_text: str, *, context: bool = False) -> Path:
    """The joint example's project in its pre-0.3 shape, committed to Git."""
    from integration.tests.lumio_local_context import KB_COMPLETED
    from integration.tests.lumio_metric_mvp import content_project, page_parts, write_page

    project = content_project(root)
    models = project / "semantic_layer" / "models"
    (models / "retail_sales.yml").write_text(model_text, encoding="utf-8")
    page = project / "knowledge" / "metrics" / "retail-revenue.md"
    page.write_text(page.read_text().replace('"orders.revenue"', '"revenue"'), encoding="utf-8")
    selector = project / "context_integration.yaml"
    selector.write_text(
        selector.read_text().replace("retail_sales::orders.revenue", "retail_sales::revenue")
    )
    (project / "knowledge" / "metrics" / "completed-orders.md").write_text(
        KB_COMPLETED.replace('"orders.completed_orders"', '"completed_orders"')
        .replace("required_policies: []", _RETURN_POLICY)
        .replace("policies/cancelled-orders.md", "policies/retail-return-policy.md"),
        encoding="utf-8",
    )
    selector.write_text(
        selector.read_text()
        + "    - subject: {kind: metric, identity: retail_sales::completed_orders}\n"
        "      policy: {namespace: urn:demo:retail, entity_id: entity:retail-return-policy}\n"
        "      operations: [get_metric, query_metrics]\n"
        "      enforcement: null\n"
    )
    # the joint fixture's glossary page cites a catalog source outside this registry;
    # the joint journeys strip that profile as a visible edit (supported_candidate)
    reference = project / "knowledge" / "references" / "order-number.md"
    meta, body = page_parts(reference)
    del meta["ariadne_profile"]
    write_page(reference, meta, body)
    if context:
        _add_context(project)
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "human: pre-0.3 semantic layer")
    return project


def test_migrate_converts_the_joint_example_and_the_admitted_result_answers(tmp_path, monkeypatch):
    from integration.tests.lumio_metric_mvp import (
        ORDERS_BINDINGS,
        ORDERS_CONTRACT,
        activate,
        preview,
    )

    from tests.test_contracts import contracted
    from tests.test_git_authoring import approved

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES, context=True)

    result = migrate.migrate_project(project)
    assert result["status"] == "draft"
    assert "semantic_layer/models/retail_sales.yml" in result["files"]
    assert "knowledge/metrics/retail-revenue.md" in result["files"]
    assert "context_integration.yaml" in result["files"]

    api = AuthoringProject(project)
    started = {
        "proposal": json.loads((project / ".ariadne" / "draft.json").read_text(encoding="utf-8"))[
            "proposal"
        ],
        "candidate_revision": result["revision"],
    }
    approved(api, project, started)
    contract = ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175")
    bindings = ORDERS_BINDINGS.replace("region", "status").replace(
        "model: orders", "model: retail_sales"
    )
    revision = contracted(api, started, contract=contract, bindings=bindings)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]  # the Example still validates
    # the generated Computation page was deleted by the migration and regenerated by the
    # finalize pass under the NEW identity; the old one is gone
    tree = _git(project, "ls-tree", "-r", "--name-only", validated["revision"], "knowledge")
    assert "knowledge/computations/retail_sales--orders-2erevenue.md" in tree.split()
    assert "knowledge/computations/revenue.md" not in tree.split()
    regenerated = _git(
        project,
        "show",
        f"{validated['revision']}:knowledge/computations/retail_sales--orders-2erevenue.md",
    )
    assert "retail_sales::orders.revenue" in regenerated
    # Answer Examples are historical provenance: byte-identical
    example = "knowledge/answer-examples/revenue-example.md"
    assert _git(project, "show", f"{validated['revision']}:{example}") == _git(
        project, "show", f"HEAD:{example}"
    )
    review = api.review_proposal(started["proposal"])
    activate(project, review, preview(project, review, tmp_path / "published"))

    runtime = QueryRuntime.open_project(project)
    try:
        answer = asyncio.run(runtime.get_metric("retail_sales::orders.revenue"))
        assert answer["rows"] == [{"revenue": 150.0}]  # 100 + 50; cancelled 25 excluded
        by_short_name = asyncio.run(runtime.get_metric("revenue"))
        assert by_short_name["rows"] == [{"revenue": 150.0}]
        completed = asyncio.run(runtime.get_metric("completed_orders"))
        assert completed["rows"] == [{"completed_orders": 2}]  # orders 1 and 2; 3 is cancelled
    finally:
        runtime.con.close()

    # admitted through the normal route and NOT merged into the checkout: the checkout
    # still holds the legacy files, the pinned revision does not — a second run reads
    # the pinned revision and reports the project converted
    assert "semantic_model" in _git(project, "show", "HEAD:semantic_layer/models/retail_sales.yml")
    assert migrate.migrate_project(project) == {"status": "already", "message": "already Ossie 0.3"}


def test_migrate_twice_is_a_noop_and_an_unconvertible_project_is_left_unchanged(tmp_path):
    migrated = _legacy_project(tmp_path / "ok", LEGACY_RETAIL_SALES)
    migrate.migrate_project(migrated)
    # the proposal holds the conversion; apply it to the working tree as a human merge
    # would, then the second run reports the project already converted
    _git(migrated, "merge", "-q", "--ff-only", _proposal_branch(migrated))
    assert migrate.migrate_project(migrated) == {
        "status": "already",
        "message": "already Ossie 0.3",
    }

    broken = _legacy_project(tmp_path / "bad", UNCONVERTIBLE)
    before = _git(broken, "rev-parse", "HEAD"), _git(broken, "status", "--porcelain")
    with pytest.raises(migrate.MigrationError, match=r"project left unchanged.*retail_sales\.yml"):
        migrate.migrate_project(broken)
    assert (_git(broken, "rev-parse", "HEAD"), _git(broken, "status", "--porcelain")) == before


def test_a_metric_owned_by_one_dataset_but_referencing_another_is_unconvertible():
    """`dataset: orders` with SUM(orders.amount + customers.amount) would silently become
    SUM(source.amount + source.amount) on orders: it is reported, with the file named."""
    text = LEGACY_RETAIL_SALES.replace(
        "    metrics:\n",
        "      - name: customers\n        source: customers.main.customers\n"
        "        fields:\n          - name: amount\n"
        "            expression: {dialects: [{dialect: ANSI_SQL, expression: amount}]}\n"
        "    metrics:\n      - name: mixed\n        dataset: orders\n        expression:\n"
        "          dialects:\n            - dialect: ANSI_SQL\n"
        "              expression: SUM(orders.amount + customers.amount)\n",
        1,
    )
    conv = migrate.convert_documents({"semantic_layer/models/retail_sales.yml": text})
    assert conv.files == {}
    assert "owned by dataset 'orders'" in "; ".join(conv.problems["retail_sales.yml"])


def test_a_lone_yaml_suffix_model_is_migrated_in_place(tmp_path):
    """sales.yaml is rewritten at the same path; no stray .yml appears beside it."""
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES)
    _git(
        project, "mv", "semantic_layer/models/retail_sales.yml", "semantic_layer/models/sales.yaml"
    )
    _git(project, "commit", "-q", "-m", "human: .yaml suffix")
    result = migrate.migrate_project(project)
    assert "semantic_layer/models/sales.yaml" in result["files"]
    tree = _git(project, "ls-tree", "-r", "--name-only", result["revision"], "semantic_layer")
    assert sorted(tree.split()) == ["semantic_layer/models/sales.yaml"]
    migrated = _git(project, "show", f"{result['revision']}:semantic_layer/models/sales.yaml")
    assert "version: 0.3.0.dev0" in migrated and "semantic_model" not in migrated


def _unchanged(project: Path) -> tuple:
    return (
        _git(project, "rev-parse", "HEAD"),
        _git(project, "status", "--porcelain"),
        _git(project, "for-each-ref", "refs/heads"),
    )


def test_an_example_whose_short_name_becomes_ambiguous_refuses_and_writes_nothing(tmp_path):
    """`revenue` names one metric before the migration; afterwards `orders.revenue`
    (short name revenue) and a second dataset's `revenue` both match, so the recorded name
    no longer resolves uniquely (spec 0039 §6.4): the project is unconvertible."""
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES, context=True)
    model = project / "semantic_layer" / "models" / "retail_sales.yml"
    twin = LEGACY_RETAIL_SALES.replace("retail_sales", "twin_sales").replace(
        "name: orders", "name: twin_orders"
    )
    (project / "semantic_layer" / "models" / "twin_sales.yml").write_text(twin, encoding="utf-8")
    del model
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "human: a second model with the same short names")
    before = _unchanged(project)
    with pytest.raises(migrate.MigrationError, match=r"revenue-example\.md.*ambiguous"):
        migrate.migrate_project(project)
    assert _unchanged(project) == before


def test_an_attested_computation_page_whose_sql_changes_refuses_and_writes_nothing(tmp_path):
    """An authored page claiming an attestation for the old SQL does not bind the
    sanctioned SQL of the new identity: reported for re-attestation, nothing written."""
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES, context=True)
    page = project / "knowledge" / "computations" / "revenue.md"
    text = page.read_text()
    text = text.replace("attestation: pending", "attestation: verified\n    attester: expert:dana")
    text = text.replace("model-retail_sales", "authored-note")
    page.write_text(text, encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "human: an attested computation")
    before = _unchanged(project)
    with pytest.raises(migrate.MigrationError, match=r"revenue\.md.*re-attestation"):
        migrate.migrate_project(project)
    assert _unchanged(project) == before


def _proposal_branch(project: Path) -> str:
    refs = _git(project, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    return next(ref for ref in refs if ref.startswith("ariadne/proposal/"))


def test_policy_binding_identities_are_mapped_exactly_not_by_prefix():
    """`sales` (on orders) and `sales-net` (on returns) become `retail::orders.sales` and
    `retail::returns.sales-net`; a prefix replacement would turn the second into
    `retail::orders.sales-net`."""
    conv = migrate.Conversion(
        metric_keys={
            ("retail", "sales"): "orders.sales",
            ("retail", "sales-net"): "returns.sales-net",
        }
    )
    selector = (
        "version: 1\nsupport_revision: 2\npolicy_bindings:\n  version: 1\n  bindings:\n"
        "    - subject: {kind: metric, identity: 'retail::sales'}\n"
        "      policy: {namespace: urn:x, entity_id: 'entity:p'}\n"
        "      operations: [get_metric]\n      enforcement: null\n"
        "    - subject: {kind: metric, identity: 'retail::sales-net'}\n"
        "      policy: {namespace: urn:x, entity_id: 'entity:p'}\n"
        "      operations: [get_metric]\n"
        "      enforcement: {check: c, definition: 'retail::sales-net',\n"
        "        dependencies: ['retail::sales']}\n"
    )
    out = yaml.safe_load(migrate.rewrite_identities(selector, conv))
    first, second = out["policy_bindings"]["bindings"]
    assert first["subject"]["identity"] == "retail::orders.sales"
    assert second["subject"]["identity"] == "retail::returns.sales-net"
    assert second["enforcement"] == {
        "check": "c",
        "definition": "retail::returns.sales-net",
        "dependencies": ["retail::orders.sales"],
    }


def test_a_selector_subject_shared_through_a_yaml_anchor_maps_once():
    """Two bindings share one `retail::sales` subject through an anchor; a third
    names the dotted legacy metric `retail::orders.sales`. With sales ->
    orders.sales and orders.sales -> returns.orders.sales, the shared subject is
    `retail::orders.sales` in BOTH bindings (mapped once) and the third becomes
    `retail::returns.orders.sales`."""
    conv = migrate.Conversion(
        metric_keys={
            ("retail", "sales"): "orders.sales",
            ("retail", "orders.sales"): "returns.orders.sales",
        }
    )
    selector = (
        "version: 1\nsupport_revision: 2\npolicy_bindings:\n  version: 1\n  bindings:\n"
        "    - subject: &shared {kind: metric, identity: 'retail::sales'}\n"
        "      policy: {namespace: urn:x, entity_id: 'entity:p'}\n"
        "      operations: [get_metric]\n"
        "    - subject: *shared\n"
        "      policy: {namespace: urn:x, entity_id: 'entity:q'}\n"
        "      operations: [get_metric]\n"
        "    - subject: {kind: metric, identity: 'retail::orders.sales'}\n"
        "      policy: {namespace: urn:x, entity_id: 'entity:p'}\n"
        "      operations: [get_metric]\n"
    )
    out = yaml.safe_load(migrate.rewrite_identities(selector, conv))
    identities = [b["subject"]["identity"] for b in out["policy_bindings"]["bindings"]]
    assert identities == [
        "retail::orders.sales",
        "retail::orders.sales",
        "retail::returns.orders.sales",
    ]


def _attested(project: Path, name: str, info: dict, sql: str, *, generated: bool) -> Path:
    """A Computation page under the old identity carrying an independent attestation."""
    from ariadne import context

    page = project / "knowledge" / "computations" / f"{name}.md"
    page.parent.mkdir(exist_ok=True)
    text = context._build_native_computation_page(name, info, sql)
    text = text.replace("attestation: pending", "attestation: verified\n    attester: expert:dana")
    if not generated:
        text = text.replace(f"model-{info['model']}", "authored-note")
    page.write_text(text, encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "human: an attested computation")
    return page


def test_a_generated_page_with_a_retained_check_is_deleted_for_regeneration(tmp_path):
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES)
    info = {"model": "retail_sales", "dataset_sources": ["orders.main.orders"]}
    _attested(project, "revenue", info, "SELECT 1", generated=True)
    result = migrate.migrate_project(project)
    assert result["deleted"] == ["knowledge/computations/revenue.md"]


def _cross_fact_legacy_model() -> str:
    cross = LEGACY_RETAIL_SALES.replace(
        "    metrics:\n",
        "      - name: returns\n        source: orders.main.returns\n        primary_key: [id]\n"
        "        fields:\n          - name: id\n"
        "            expression: {dialects: [{dialect: ANSI_SQL, expression: id}]}\n"
        "          - name: refunded\n"
        "            expression: {dialects: [{dialect: ANSI_SQL, expression: refunded}]}\n"
        "    metrics:\n      - name: refunds\n        dataset: returns\n        expression:\n"
        "          dialects:\n            - dialect: ANSI_SQL\n"
        "              expression: SUM(returns.refunded)\n"
        "      - name: net\n        expression:\n          dialects:\n"
        "            - dialect: ANSI_SQL\n              expression: revenue - refunds\n",
        1,
    )
    return cross


def test_a_same_identity_generated_page_with_a_check_is_retired_and_not_regenerated(tmp_path):
    """`net` keeps its key but becomes a model-scoped cross-fact AGG composition: no
    sanctioned SQL exists, so the generated page and its retained check are deleted,
    not regenerated, and the notes say why."""
    project = _legacy_project(tmp_path, _cross_fact_legacy_model())
    info = {"model": "retail_sales", "dataset_sources": ["orders.main.orders"]}
    _attested(project, "net", info, "SELECT 1", generated=True)
    result = migrate.migrate_project(project)
    assert result["deleted"] == ["knowledge/computations/net.md"]
    assert any(
        "computations/net.md" in note and "cross-fact" in note and "not regenerated" in note
        for note in result["notes"]
    ), result["notes"]
    tree = _git(project, "ls-tree", "-r", "--name-only", result["revision"], "knowledge")
    assert "knowledge/computations/net.md" not in tree.split()


def test_an_authored_attested_page_on_a_cross_fact_metric_is_refused(tmp_path):
    """No sanctioned SQL exists for a cross-fact composition, so an authored attestation
    cannot be proven against it: the project is refused, nothing written."""
    cross = _cross_fact_legacy_model()
    project = _legacy_project(tmp_path, cross)
    info = {"model": "retail_sales", "dataset_sources": ["orders.main.orders"]}
    _attested(project, "net", info, "SELECT 1", generated=False)
    before = _unchanged(project)
    with pytest.raises(migrate.MigrationError, match=r"net\.md.*re-attestation"):
        migrate.migrate_project(project)
    assert _unchanged(project) == before


def test_an_attested_page_is_proven_against_its_own_models_sql_not_a_namesake(tmp_path):
    """Two models share the metric key `revenue`; the twin (sorted later) defines it
    differently. The page attests model A's exact sanctioned SQL, so it is kept and
    rewritten to `retail_sales::orders.revenue`; a bare-key lookup would compare it with
    the twin's SQL and refuse it."""
    from ariadne import context

    twin = (
        LEGACY_RETAIL_SALES.replace("retail_sales", "twin_sales")
        .replace("name: orders", "name: twin_orders")
        .replace("status <> 'cancelled' THEN amount", "status = 'shipped' THEN amount")
    )
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES)
    (project / "semantic_layer" / "models" / "twin_sales.yml").write_text(twin, encoding="utf-8")
    files = {
        "semantic_layer/models/retail_sales.yml": LEGACY_RETAIL_SALES,
        "semantic_layer/models/twin_sales.yml": twin,
    }
    conv = migrate.convert_documents(files)
    scratch = tmp_path / "scratch"
    for rel, text in conv.files.items():
        (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
        (scratch / rel).write_text(text, encoding="utf-8")
    index, _ok = context._model_index(scratch)
    sql_a = context.sanctioned_sql(scratch, index)["retail_sales::orders.revenue"]
    assert sql_a != context.sanctioned_sql(scratch, index)["twin_sales::twin_orders.revenue"]
    info = {"model": "retail_sales", "dataset_sources": ["orders.main.orders"]}
    _attested(project, "revenue", info, sql_a, generated=False)
    result = migrate.migrate_project(project)
    assert "knowledge/computations/revenue.md" in result["files"]


def test_a_nested_model_copy_is_neither_read_nor_written_and_leaves_no_proposal(tmp_path):
    """The normal loader reads direct children of semantic_layer/models only: a tracked
    `models/archive/retail.yaml` is ignored, so the migration neither converts nor
    refuses it, and the proposal holds exactly the direct-child files."""
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES)
    nested = project / "semantic_layer" / "models" / "archive"
    nested.mkdir()
    (nested / "retail.yaml").write_text(LEGACY_RETAIL_SALES, encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "human: an archived legacy copy")
    result = migrate.migrate_project(project)
    assert all("archive" not in path for path in result["files"])
    archived = _git(
        project, "show", f"{result['revision']}:semantic_layer/models/archive/retail.yaml"
    )
    assert "semantic_model" in archived  # untouched


def test_a_legacy_model_with_an_inline_credential_is_refused_and_creates_no_proposal(tmp_path):
    secret = LEGACY_RETAIL_SALES.replace(
        "source: orders.main.orders", "source: postgres://svc:hunter2pass@db.example/orders"
    )
    project = _legacy_project(tmp_path, secret)
    before = _unchanged(project)
    with pytest.raises(ValueError, match="inline URL credentials"):
        migrate.migrate_project(project)
    assert _unchanged(project) == before
    assert not (project / ".ariadne").exists() or not any(
        (project / ".ariadne").rglob("proposals/*")
    )
