"""``ariadne migrate`` (spec 0039 §7, AC8/AC3): the retired Ossie 0.2 envelope is
converted through an Authoring Proposal; the admitted result answers the joint
example's hand-worked values (100 + 50 completed = 150 EUR; cancelled 25 excluded);
a second run is a no-op; an unconvertible project is left unchanged with a per-file
report. The legacy envelope below is the pre-0.3 fixture shape, written out as the
migration input."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

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


def _legacy_project(root: Path, model_text: str) -> Path:
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
    project = _legacy_project(tmp_path, LEGACY_RETAIL_SALES)

    result = migrate.migrate_project(project)
    assert result["status"] == "proposal"
    assert "semantic_layer/models/retail_sales.yml" in result["files"]
    assert "knowledge/metrics/retail-revenue.md" in result["files"]
    assert "context_integration.yaml" in result["files"]

    api = AuthoringProject(project)
    started = {"proposal": result["proposal"], "candidate_revision": result["revision"]}
    approved(api, project, started)
    contract = ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175")
    bindings = ORDERS_BINDINGS.replace("region", "status").replace(
        "model: orders", "model: retail_sales"
    )
    revision = contracted(api, started, contract=contract, bindings=bindings)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
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


def _proposal_branch(project: Path) -> str:
    refs = _git(project, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    return next(ref for ref in refs if ref.startswith("ariadne/proposal/"))
