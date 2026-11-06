"""Plan0033 A2/VA2: complete staged-tree review and native commit verification.

The fixture uses real local Git and synthetic Core/Lumio content. Live source
validation is deliberately unavailable; expected disclosures are hand-authored.
"""

import json
import os
from datetime import date
from pathlib import Path

import pytest
from ariadne import (
    admission,
    context,
    execution,
    query,
    sources,
)
from ariadne.authoring_cli import main as authoring_cli
from ariadne.contribution_review import (
    check_contribution_commit,
    review_contribution,
)
from tests.test_git_authoring import run_git, worktree_of

from integration.tests.lumio_metric_mvp import page_parts, supported_candidate, write_page

POLICY_BODY_ADDITION = (
    "\nOnly completed orders with an amount above 25 enter the reviewed revenue calculation.\n"
)
ORIGINAL_SUMMARY = (
    "The shared order-number concept across store-local and global representations."
)
REVISED_SUMMARY = "Shared order-number meaning reviewed for the filtered recognized-revenue metric."
FILTER_EXPRESSION = "SUM(amount) FILTER (WHERE status = 'completed' AND amount > 25)"
UNSTAGED_MARKER = "UNSTAGED-AND-EXCLUDED-FROM-REVIEW"
SYNTHETIC_POLICY = f"""---
id: entity:contribution-policy
entity_types: [policy]
tags: [policy]
title: Contribution Policy
summary: Synthetic Policy for complete contribution review.
visibility: public
lifecycle: approved
sources:
  - id: human-contribution-rule
    title: Synthetic operator rule
ariadne_profile:
  version: 1
  kind: policy
  required_policies: []
  native:
    type: policy
    title: Contribution Policy
    description: Synthetic Policy for complete contribution review.
    status: stable
    tags: [policy]
    stale_after: \"2027-01-01\"
    sources:
      - id: human-contribution-rule
        title: Synthetic operator rule
---

# Contribution Policy
{POLICY_BODY_ADDITION}
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


def _staged_contribution(tmp_path):
    project, _api, started, revision = supported_candidate(tmp_path / "project")
    proposal = started["proposal"]
    tree = worktree_of(project, proposal)

    # Finalize generated metadata without native live validation or source access.
    context.finalize_candidate(tree)
    run_git(tree, "add", "-f", "--", "context_layer")
    run_git(tree, "commit", "-q", "-m", "human: deterministic fixture finalization")
    finalized = run_git(tree, "rev-parse", "HEAD").strip()
    admission.reconcile(project, proposal, revision, finalized)

    order_reference = tree / "knowledge/references/order-number.md"
    metadata, body = page_parts(order_reference)
    assert metadata["summary"] == ORIGINAL_SUMMARY
    metadata["summary"] = REVISED_SUMMARY
    write_page(order_reference, metadata, body)

    policy = tree / "knowledge/policies/contribution-policy.md"
    policy.write_text(SYNTHETIC_POLICY)

    model = tree / "semantic_layer/models/retail_sales.yml"
    original_expression = "SUM(CASE WHEN status <> 'cancelled' THEN amount ELSE 0 END)"
    assert original_expression in model.read_text()
    model.write_text(model.read_text().replace(original_expression, FILTER_EXPRESSION))

    changed = [
        "knowledge/policies/cancelled-orders.md",
        "knowledge/policies/contribution-policy.md",
        "knowledge/references/order-number.md",
        "knowledge/metrics/retail-revenue.md",
        "semantic_layer/models/retail_sales.yml",
    ]
    run_git(tree, "add", "-f", "--", *changed)

    # These bytes are not part of the selected staged snapshot.
    policy.write_text(policy.read_text() + f"\n{UNSTAGED_MARKER}\n")
    (tree / "contributor-note.txt").write_text("Excluded untracked contributor note.\n")
    return project, proposal, tree, started["base_revision"]


def _commit_after_review(case, tree):
    if case == "added_staged_file":
        seed = tree / "data/seed_notes.md"
        seed.write_text(seed.read_text() + "\nAdded only after the review.\n")
        run_git(tree, "add", "-f", "--", "data/seed_notes.md")
    elif case == "modifying_commit_hook":
        git_dir = Path(
            run_git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        )
        hook = git_dir / "hooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            "#!/bin/sh\n"
            "printf '\\nCommitted by the hook after review.\\n' >> data/seed_notes.md\n"
            "git add -f -- data/seed_notes.md\n"
        )
        hook.chmod(0o755)
    run_git(tree, "commit", "-q", "-m", "human: explicit reviewed contribution")
    return run_git(tree, "rev-parse", "HEAD").strip()


@pytest.mark.parametrize(
    "case",
    [
        "matching_commit",
        "added_staged_file",
        "modifying_commit_hook",
        "existing_candidate_staged_addition",
    ],
)
def test_contribution_review_covers_document_and_metric(case, tmp_path, monkeypatch, capsys):
    project, proposal, tree, base = _staged_contribution(tmp_path)

    if case == "existing_candidate_staged_addition":
        run_git(tree, "commit", "-q", "-m", "human: existing reviewed candidate")

    def forbidden(*args, **kwargs):
        pytest.fail("static contribution review/check opened a live source or runtime")

    for module, name in (
        (query.QueryRuntime, "open_project"),
        (sources, "build_connection"),
        (execution, "build_connection"),
        (execution.DuckDBExecution, "__init__"),
    ):
        monkeypatch.setattr(module, name, forbidden)

    review = review_contribution(project, proposal, base_revision=base)
    assert review["schema_version"] == 1
    assert review["proposal"] == proposal
    assert review["base_revision"] == base
    assert review["head_revision"] == run_git(tree, "rev-parse", "HEAD").strip()
    assert review["candidate_tree"] == run_git(tree, "write-tree").strip()
    assert review["excluded_unstaged"] == ["knowledge/policies/contribution-policy.md"]
    assert review["excluded_untracked"] == ["contributor-note.txt"]
    assert UNSTAGED_MARKER not in json.dumps(review)

    changed_paths = {entry["path"] for entry in review["changes"]}
    assert {
        "knowledge/policies/cancelled-orders.md",
        "knowledge/policies/contribution-policy.md",
        "knowledge/metrics/retail-revenue.md",
        "knowledge/lumio.yaml",
        "knowledge/references/order-number.md",
        "semantic_layer/models/retail_sales.yml",
        "contracts/orders-contract.yaml",
        "contract_bindings.yaml",
    } <= changed_paths
    assert review["unknown_paths"] == []
    for entry in review["changes"]:
        assert entry["candidate_blob"] and entry["candidate_mode"] == "100644"
        if entry["change"] == "A":
            assert entry["base_blob"] is None and entry["base_mode"] is None
        else:
            assert entry["base_blob"] and entry["base_mode"] == "100644"

    core = {entry["path"]: entry for entry in review["core_changes"]}
    model_change = core["semantic_layer/models/retail_sales.yml"]
    assert FILTER_EXPRESSION in model_change["body_diff"]
    assert "row eligibility and calculation meaning can change" in model_change["consequence"]
    assert (
        "Static review cannot determine business correctness or numerical effects."
        in model_change["consequence"]
    )
    contract_change = core["contracts/orders-contract.yaml"]
    assert "mustBe" in contract_change["body_diff"]
    assert "validation and governed eligibility can change" in contract_change["consequence"]
    assert "Static review cannot determine live-data compliance" in contract_change["consequence"]
    assert "model: retail_sales" in core["contract_bindings.yaml"]["body_diff"]
    pages = {entry["path"]: entry for entry in review["knowledge"]["pages"]}
    from lumio_wiki.knowledge_base import load_knowledge_base

    loaded, load_report = load_knowledge_base(tree / "knowledge")
    assert load_report.is_valid
    cancellation = next(
        page for page in loaded.pages if page.path == "policies/cancelled-orders.md"
    )
    expected_verified = [{"by": "human:synthetic-owner", True: date(2020, 1, 1)}]
    assert cancellation.ariadne_profile.native["verified"] == expected_verified
    cancellation_review = next(
        change
        for change in pages["policies/cancelled-orders.md"]["semantic_changes"]
        if change["field"] == "ariadne_profile"
    )
    assert cancellation_review["before"] == "none"
    for fact in ("verified", "human:synthetic-owner", repr(date(2020, 1, 1)), "True:"):
        assert fact in cancellation_review["after"]

    policy = pages["policies/contribution-policy.md"]
    assert policy["body_changed"] is True
    assert POLICY_BODY_ADDITION.strip() in policy["body_diff"]
    frontmatter = pages["references/order-number.md"]
    assert frontmatter["frontmatter_only"] is True
    assert frontmatter["body_changed"] is False
    summary = next(
        change for change in frontmatter["semantic_changes"] if change["field"] == "summary"
    )
    assert summary["before"] == ORIGINAL_SUMMARY
    assert summary["after"] == REVISED_SUMMARY
    assert "summary:" not in json.dumps(frontmatter)
    assert "ariadne_profile:" not in json.dumps(frontmatter)

    assert review["knowledge"]["kb_valid"] is True
    assert review["knowledge"]["exact_source_verification"] == "unavailable"
    assert review["validation"]["static"]["ok"] is True, review["validation"]["static"]["errors"]
    assert review["validation"]["live"]["status"] == "pending"
    assert review["validation"]["admission_ready"] is False

    if case == "matching_commit":
        # Exercise the external review against the same captured HEAD/tree.
        assert authoring_cli(
            [
                "contribution-review",
                "--project",
                str(project),
                "--proposal",
                proposal,
                "--base",
                base,
            ]
        ) == 0
        assert json.loads(capsys.readouterr().out) == review

    if case == "existing_candidate_staged_addition":
        revision = run_git(tree, "rev-parse", "HEAD").strip()
        before_staging = check_contribution_commit(project, proposal, review, revision)
        assert before_staging["matches_reviewed_candidate"] is True
        assert before_staging["mismatches"] == []
        seed = tree / "data/seed_notes.md"
        seed.write_text(seed.read_text() + "\nStaged after reviewing an existing commit.\n")
        run_git(tree, "add", "-f", "--", "data/seed_notes.md")
    else:
        revision = _commit_after_review(case, tree)

    checked = check_contribution_commit(project, proposal, review, revision)
    assert checked["commit"] == revision
    expected_parent = (
        None if case == "existing_candidate_staged_addition" else review["head_revision"]
    )
    assert checked["parent"] == expected_parent
    assert checked["matches_reviewed_candidate"] is (case == "matching_commit")
    if case == "matching_commit":
        assert checked["mismatches"] == []

        # The private review round-trips through the external commit check.
        review_path = tmp_path / "private-contribution-review.json"
        review_path.write_text(json.dumps(review))
        assert authoring_cli(
            [
                "contribution-check",
                "--project",
                str(project),
                "--proposal",
                proposal,
                "--review",
                str(review_path),
                "--revision",
                revision,
            ]
        ) == 0
        assert json.loads(capsys.readouterr().out) == checked
    else:
        assert any(
            "tree" in mismatch or "changed" in mismatch for mismatch in checked["mismatches"]
        )
