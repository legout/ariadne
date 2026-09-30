"""Mechanical promotion gate (spec rev 6 §8.16): merge-only promotion bookkeeping.

Exercises ariadne.promote (the logic behind ``ariadne-promote`` / the
``ariadne-promote`` shim) against fixture staging/served trees: verified
append + status flip, index regeneration, log.md entries, idempotency, and the
merge-never-wipes invariant. The staged pages mirror the real author output
shape so the frontmatter round-trip is exercised for real.

The issue #15 block exercises the HUMAN-ONLY exact-digest Promotion of a
harness-led bundle proposal (spec 2026-09-24-0005, ADR-0003/0013) end to end
through the real submission service — the same journey the local CLI offers.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

from ariadne import promote as promote_module
from ariadne.promote import Change, _index_for, main, promote, promote_bundle

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_authoring import (  # noqa: E402
    _submit_captured,
    _wait_for,
    approved_project,
    bundle_submission,
    write_submission,
)

BY = "human:tester"
AT = "2026-09-16T12:00:00+00:00"

STAGED_METRIC = """---
type: metric
title: Gross Margin
description: Ratio of gross profit to gross revenue over billable orders.
tags: [metric, margin]
status: draft
sources:
  - id: order-status-billing
    resource: policies/order-status-billing.md
    title: Order status billing
---

# Gross margin

Rules live in the cited policies.
"""

STAGED_POLICY = """---
type: policy
title: Order status billing
description: Cancelled and returned orders are not revenue.
tags: [policy, billing]
status: draft
sources:
  - id: seed-notes
    resource: examples/retail-demo/seed_notes.md
    title: Seed notes
---

# Order status billing

Rows with status IN ('CANCELLED', 'RETURNED') are excluded from revenue.
"""

STAGED_TABLE = """---
type: table
title: Orders
description: One row per placed order.
tags: [table, orders]
sources:
  - id: demo.main.orders
    resource: examples/retail-demo/data/demo.db
    title: Orders
grain:
  primary_key: [order_id]
  cardinality_enforcement: STRICT_1_TO_1
---

# Orders

Join hints: customer_id -> customers.id (N:1).
"""

STAGED_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    datasets:
      - name: orders
        source: demo.main.orders
        primary_key: [order_id]
"""


def make_staging(staging: Path) -> Path:
    """Fixture staging tree mirroring the author bundle shape."""
    for rel, content in [
        ("context_layer/metrics/gross_margin.md", STAGED_METRIC),
        ("context_layer/policies/order-status-billing.md", STAGED_POLICY),
        ("semantic_layer/models/orders.yml", STAGED_MODEL),
    ]:
        path = staging / rel
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    return staging


def front(page: Path) -> dict:
    return yaml.safe_load(page.read_text(encoding="utf-8").split("---")[1])


def tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def run_promote(staging: Path, served: Path, **kwargs) -> list[Change]:
    return promote(staging, served, by=BY, at=AT, assume_yes=True, **kwargs)


def test_promote_appends_verified_and_flips_status(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    run_promote(staging, served)

    page = served / "context_layer" / "metrics" / "gross_margin.md"
    meta = front(page)
    assert meta["status"] == "stable"  # draft -> stable
    assert meta["verified"] == [{"by": BY, "at": AT}]


def test_promote_regenerates_indexes_content_and_format(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    run_promote(staging, served)

    metrics_index = (served / "context_layer" / "metrics" / "index.md").read_text()
    assert metrics_index.startswith("# Metric\n")
    assert (
        "* [Gross Margin](gross_margin.md) - Ratio of gross profit to gross revenue "
        "over billable orders.\n" in metrics_index
    )
    root_index = (served / "context_layer" / "index.md").read_text()
    assert root_index.startswith("# Context Layer\n")
    assert "* [Metrics](metrics/) - Governed metrics" in root_index
    assert "* [Policies](policies/) - Human-owned business rules" in root_index
    # only folders holding pages get a section; semantic_layer is not the bundle
    assert "semantic_layer" not in root_index


def test_index_links_use_frontmatter_title_and_description(tmp_path):
    served = tmp_path / "served" / "context_layer"
    (served / "metrics").mkdir(parents=True)
    (served / "metrics" / "order_count.md").write_text(
        "---\ntype: metric\ntitle: Order Count\ndescription: Billable orders.\n---\n\n# body\n",
        encoding="utf-8",
    )
    index = _index_for(served / "metrics", served)
    assert index == "# Metric\n\n* [Order Count](order_count.md) - Billable orders.\n"


def test_promote_appends_log_entries(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    run_promote(staging, served)

    log = (served / "context_layer" / "log.md").read_text()
    assert log.startswith("# Directory Update Log\n")
    assert f"**Creation**: context_layer/metrics/gross_margin.md — verified {BY}" in log
    assert f"**Creation**: context_layer/policies/order-status-billing.md — verified {BY}" in log
    # semantic_layer files merge raw; the bundle log covers the context bundle
    assert "orders.yml" not in log


def test_promote_is_idempotent(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    run_promote(staging, served)
    first = tree(served)

    changes = run_promote(staging, served)  # second run: nothing changed
    assert changes == []
    assert tree(served) == first  # byte-identical tree, no extra verified entry
    meta = front(served / "context_layer" / "metrics" / "gross_margin.md")
    assert meta["verified"] == [{"by": BY, "at": AT}]  # not appended twice


def test_promoting_changed_content_appends_verified(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    run_promote(staging, served)
    page = staging / "context_layer" / "policies" / "order-status-billing.md"
    page.write_text(
        STAGED_POLICY.replace("excluded from revenue.", "excluded from revenue and margin."),
        encoding="utf-8",
    )

    changes = run_promote(staging, served)
    assert [c.action for c in changes] == ["updated"]
    meta = front(served / "context_layer" / "policies" / "order-status-billing.md")
    assert len(meta["verified"]) == 2  # appended onto the served history
    assert meta["verified"][1]["by"] == BY
    assert "revenue and margin" in (  # the update landed
        (served / "context_layer" / "policies" / "order-status-billing.md").read_text()
    )
    log = (served / "context_layer" / "log.md").read_text()
    assert f"**Update**: context_layer/policies/order-status-billing.md — verified {BY}" in log


def test_promote_merges_never_wipes(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    served_context = served / "context_layer"
    (served_context / "metrics").mkdir(parents=True)
    (served_context / "models_old").mkdir()
    legacy = served_context / "metrics" / "legacy_metric.md"
    legacy.write_text(
        "---\ntype: metric\ntitle: Legacy\ndescription: Promoted long ago.\n---\n\n# legacy\n",
        encoding="utf-8",
    )
    legacy_model = served / "semantic_layer" / "models" / "customers.yml"
    legacy_model.parent.mkdir(parents=True)
    legacy_model.write_text("version: 0.2.0.dev0\nsemantic_model: []\n", encoding="utf-8")

    run_promote(staging, served)

    # nothing pre-existing was wiped ...
    assert legacy.is_file()
    assert legacy_model.is_file()
    assert (served_context / "models_old").is_dir()
    # ... and the regenerated index includes the survivor
    metrics_index = (served_context / "metrics" / "index.md").read_text()
    assert "* [Legacy](legacy_metric.md) - Promoted long ago." in metrics_index
    # staged files merged in alongside
    assert (served_context / "metrics" / "gross_margin.md").is_file()
    assert (served / "semantic_layer" / "models" / "orders.yml").is_file()


def test_promote_raw_merges_semantic_models_without_bookkeeping(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    run_promote(staging, served)

    model = (served / "semantic_layer" / "models" / "orders.yml").read_text()
    assert model == STAGED_MODEL  # byte-identical: no frontmatter rewriting on YAML


def test_promote_refuses_review_needed(tmp_path, capsys):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    page = staging / "context_layer" / "metrics" / "gross_margin.md"
    page.write_text(
        STAGED_METRIC.replace("status: draft", "status: review_needed"), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        run_promote(staging, served)
    assert excinfo.value.code == 1
    assert "review_needed" in capsys.readouterr().err
    assert not served.exists() or tree(served) == {}  # nothing was served


def test_promote_refuses_review_needed_semantic_yaml(tmp_path, capsys):
    """The author marks failed OSI YAML with a `# status: review_needed` comment
    (the schema rejects unknown keys), and such YAML raw-merges into the served
    semantic layer. The scan covers the whole staging tree; nothing is merged."""
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    model = staging / "semantic_layer" / "models" / "orders.yml"
    model.write_text("# status: review_needed\n" + STAGED_MODEL, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        run_promote(staging, served)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "semantic_layer/models/orders.yml" in err  # the offending file is listed
    assert not served.exists() or tree(served) == {}  # nothing from the tree was served


# ------------- issue #20: staged answer examples never block or join promotion -------------


def test_promote_ignores_staging_answer_examples_but_refuses_layer_markers(tmp_path, capsys):
    """ADR-0015 acceptance 7: an unreviewed (even review_needed-marked) staged
    answer example neither blocks nor joins an unrelated Context Layer/OSI
    promotion, while a marked Context Layer artifact is still refused."""
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    examples = staging / "answer_examples"
    examples.mkdir()
    (examples / "unreviewed-example.md").write_text(
        "---\n"
        "type: answer_example\n"
        "status: review_needed\n"
        "question: gross margin by region\n"
        "---\n\n# gross margin by region\n",
        encoding="utf-8",
    )

    changes = run_promote(staging, served)  # the unrelated promotion succeeds
    assert [c.rel for c in changes] == [
        "context_layer/metrics/gross_margin.md",
        "context_layer/policies/order-status-billing.md",
        "semantic_layer/models/orders.yml",
    ]
    assert not (served / "answer_examples").exists()  # examples never merge
    assert not (served / "staging").exists()

    # A marked Context Layer artifact still refuses — and the refusal names it.
    (staging / "context_layer" / "metrics" / "gross_margin.md").write_text(
        STAGED_METRIC.replace("status: draft", "status: review_needed"), encoding="utf-8"
    )
    with pytest.raises(SystemExit) as excinfo:
        run_promote(staging, served)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "context_layer/metrics/gross_margin.md" in err
    assert "answer_examples" not in err


def test_promote_cli_yes(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    code = main(["--yes", "--staging", str(staging), "--served", str(served), "--by", BY])
    assert code == 0
    assert (served / "context_layer" / "metrics" / "index.md").is_file()
    meta = front(served / "context_layer" / "metrics" / "gross_margin.md")
    assert meta["verified"] == [{"by": BY, "at": meta["verified"][0]["at"]}]  # one entry
    assert meta["verified"][0]["at"]  # stamped with the promotion time


def test_promote_cli_fresh_project_defaults_to_project_root(tmp_path, monkeypatch):
    """Spec rev 10 §8.21: with no --served and no ./context_layer, promotion
    defaults the served root to the project root — the first promotion creates
    context_layer/ + semantic_layer/ THERE instead of reporting "nothing to
    promote" against a package-relative guess. Staging defaults to ./staging
    (the ariadne-author convention)."""
    project = tmp_path / "fresh"
    make_staging(project / "staging")
    monkeypatch.chdir(project)
    assert main(["--yes", "--by", BY]) == 0
    meta = front(project / "context_layer" / "metrics" / "gross_margin.md")
    assert meta["status"] == "stable"
    assert meta["verified"] == [{"by": BY, "at": meta["verified"][0]["at"]}]
    assert (project / "semantic_layer" / "models" / "orders.yml").is_file()
    assert (project / "context_layer" / "index.md").is_file()


# ------------- issue #15: human-only exact-digest bundle Promotion (ADR-0013) -------------


class _Capture:
    """Minimal capsys stand-in so the shared submission helper works here."""

    def __init__(self, capsys):
        self._capsys = capsys

    def readouterr(self):
        return self._capsys.readouterr()


def validated_project(tmp_path, capsys) -> tuple[Path, str]:
    """A project holding ONE validated harness-led bundle proposal + the exact
    reviewed digest a human would take from ``ariadne-authoring review``."""
    project = approved_project(tmp_path)
    out = json.loads(_submit_captured(project, bundle_submission(), _Capture(capsys)))
    assert out["status"] == "validated"
    return project, out["review_digest"]


def test_exact_digest_promotion_serves_seed_notes_and_artifacts_together(tmp_path, capsys):
    """The human gate, green path: with the EXACT reviewed digest the proposed
    Seed Notes and OSI/OKF are accepted TOGETHER through the ordinary
    merge-only bookkeeping — and only then does anything get served."""
    project, digest = validated_project(tmp_path, capsys)
    assert not (project / "context_layer").exists()  # nothing served before the gate

    code = main(
        [
            "--yes",
            "--by",
            BY,
            "--digest",
            digest,
            "--staging",
            str(project / "staging"),
            "--served",
            str(project),
        ]
    )
    assert code == 0
    # Seed Notes merged (the reviewed proposal, now the project's approved notes)
    assert (
        (project / "data" / "seed_notes.md").read_text(encoding="utf-8").startswith("# Seed notes")
    )
    # OSI/OKF merged with the ordinary verified/index/log bookkeeping
    meta = front(project / "context_layer" / "metrics" / "event_count.md")
    assert meta["status"] == "stable" and meta["verified"][0]["by"] == BY
    assert (project / "semantic_layer" / "models" / "events.yml").is_file()
    assert (project / "context_layer" / "metrics" / "index.md").is_file()
    assert "event_count" in (project / "context_layer" / "log.md").read_text(encoding="utf-8")
    # the pending attestation survives promotion verbatim (ADR-0013)
    comp = (project / "context_layer" / "computations" / "event_count.md").read_text(
        encoding="utf-8"
    )
    assert "attestation: pending" in comp and "tests/test_evals.py" not in comp

    # the promoted proposal is recorded; re-promoting the same digest is a no-op
    state = json.loads(
        (project / "staging" / "authoring" / "bundle-state.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "promoted"
    assert (
        main(
            [
                "--yes",
                "--by",
                BY,
                "--digest",
                digest,
                "--staging",
                str(project / "staging"),
                "--served",
                str(project),
            ]
        )
        == 0
    )


def test_governed_query_carries_the_pending_attestation_caveat(tmp_path, capsys):
    """Spec acceptance 5: after Promotion, ``governed: true`` means Promoted —
    the governed context states that an un-attested computation is pending, and
    never presents the demo evals as its oracle."""
    from ariadne.runtime import AriadneRuntime

    project, digest = validated_project(tmp_path, capsys)
    assert (
        main(
            [
                "--yes",
                "--by",
                BY,
                "--digest",
                digest,
                "--staging",
                str(project / "staging"),
                "--served",
                str(project),
            ]
        )
        == 0
    )
    runtime = AriadneRuntime(
        project / "semantic_layer",
        project / "context_layer",
        db_path=project / "ariadne.yaml",
        staging_dir=project / "staging",
        sources=project / "ariadne.yaml",
    )
    result = asyncio.run(runtime.get_metric("event_count"))
    assert result["governed"] is True
    context = result["context"]
    assert context["attestation"] == "pending"
    assert context["governed_note"] == (
        "governed: true means Promoted, not independently value-attested"
    )


def test_digest_promotion_refuses_changed_staged_content(tmp_path, capsys):
    """The exact-content rule: staging edited after the review (same digest)
    refuses promotion before any served write."""
    project, digest = validated_project(tmp_path, capsys)
    metrics_page = (
        project
        / "staging"
        / "authoring"
        / "bundle"
        / "context_layer"
        / "metrics"
        / "event_count.md"
    )
    page = metrics_page
    page.write_text(page.read_text(encoding="utf-8") + "\nsneaked line\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after the review"):
        promote_bundle(
            digest,
            staging_root=project / "staging",
            served_root=project,
            by=BY,
            assume_yes=True,
            at=AT,
        )
    assert not (project / "context_layer").exists()


def test_digest_promotion_refuses_invalid_and_review_needed_proposals(tmp_path, capsys):
    """Only a proposal that passed every deterministic check is promotable:
    an ``invalid`` (failed round) and an exhausted ``review_needed`` proposal
    both refuse before any served write."""
    from ariadne.authoring import submit_bundle

    project = approved_project(tmp_path)
    file = write_submission(project, bundle_submission(pk="label"))
    submit_bundle(file, project=project)  # invalid: grain audit failure
    state_path = project / "staging" / "authoring" / "bundle-state.json"
    bad_digest = json.loads(state_path.read_text(encoding="utf-8"))["digest"]
    with pytest.raises(ValueError, match="'invalid'"):
        promote_bundle(
            bad_digest,
            staging_root=project / "staging",
            served_root=project,
            by=BY,
            assume_yes=True,
        )
    assert not (project / "context_layer").exists()


def test_digest_promotion_refuses_a_changed_source_registry(tmp_path, capsys):
    """The approved source identity must still be what the proposal was checked
    against: a registry change after the review refuses promotion."""
    project, digest = validated_project(tmp_path, capsys)
    doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    doc["sources"][0]["path"] = str(project / "data" / "moved.parquet")
    (project / "ariadne.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="source registry changed"):
        promote_bundle(
            digest,
            staging_root=project / "staging",
            served_root=project,
            by=BY,
            assume_yes=True,
            at=AT,
        )
    assert not (project / "context_layer").exists()


def test_digest_promotion_requires_an_explicit_served_root(tmp_path, capsys):
    """Spec: the human command names the project's staging and served roots
    explicitly — a digest promotion without --served refuses."""
    project, digest = validated_project(tmp_path, capsys)
    assert main(["--yes", "--digest", digest, "--staging", str(project / "staging")]) == 1
    assert not (project / "context_layer").exists()


def test_digest_promotion_without_a_proposal_is_an_actionable_error(tmp_path, capsys, monkeypatch):
    """No active bundle proposal: the human gate reports it and serves nothing."""
    monkeypatch.chdir(tmp_path)
    assert main(["--yes", "--digest", "0" * 64, "--served", str(tmp_path)]) == 1
    assert not (tmp_path / "context_layer").exists()


_PROMOTE_RACE_WRITER = """\
import json, sys
from pathlib import Path

from ariadne import authoring

project, submission_file, base_digest, outcome = sys.argv[1:5]
try:
    result = authoring.submit_bundle(
        submission_file, project=project, base_digest=base_digest
    )
    Path(outcome).write_text(
        json.dumps({"ok": True, "digest": result["digest"]}), encoding="utf-8"
    )
except ValueError as exc:
    Path(outcome).write_text(
        json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8"
    )
"""


def test_promotion_serves_only_the_reviewed_digest_when_a_writer_races(
    tmp_path, capsys, monkeypatch
):
    """Review finding P1, the promotion crossing: a competing writer submitting
    while the human Promotion is between its digest check and the served writes
    can never split the reviewed digest from the bytes served — either the
    promotion completes on the reviewed content and the writer fails, or the
    writer lands first and the promotion refuses. Promotion parks (via _apply)
    exactly in that window, giving a real submit_bundle process the chance to
    interleave; without serialization it serves the unreviewed replacement."""
    project, digest = validated_project(tmp_path, capsys)
    state = json.loads(
        (project / "staging" / "authoring" / "bundle-state.json").read_text(encoding="utf-8")
    )
    replacement = write_submission(
        project, bundle_submission(seed_notes="# competing writer\n"), name="race.json"
    )
    started, release, outcome_file = project / "APPLY", project / "RELEASE", project / "WRITER"
    real_apply = promote_module._apply

    def parked_apply(staging, served_root, by, at):
        started.write_text("", encoding="utf-8")  # past every digest check
        deadline = time.monotonic() + 30
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.01)  # parked between the digest check and the served writes
        return real_apply(staging, served_root, by, at)

    monkeypatch.setattr(promote_module, "_apply", parked_apply)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _PROMOTE_RACE_WRITER,
            str(project),
            str(replacement),
            state["submission_digest"],
            str(outcome_file),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    errors: list[BaseException] = []

    def run_promotion():
        try:
            promote_bundle(
                digest,
                staging_root=project / "staging",
                served_root=project,
                by=BY,
                assume_yes=True,
            )
        except BaseException as exc:  # surfaced by the join assertion below
            errors.append(exc)

    thread = threading.Thread(target=run_promotion)
    try:
        thread.start()
        _wait_for(started)
        # Bounded window: an unserialized writer lands its swap mid-promotion
        # (test red); a serialized one is still blocked on the project lock.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not outcome_file.exists():
            time.sleep(0.05)
        release.write_text("", encoding="utf-8")
        thread.join(timeout=60)
        assert not thread.is_alive() and not errors
        child.wait(timeout=120)
    finally:
        if thread.is_alive():  # pragma: no cover - failure path only
            thread.join(timeout=10)
        if child.poll() is None:  # pragma: no cover - failure path only
            child.kill()

    writer = json.loads(outcome_file.read_text(encoding="utf-8"))
    served = (project / "data" / "seed_notes.md").read_text(encoding="utf-8")
    assert served.startswith("# Seed notes")  # the REVIEWED bytes, never the writer's
    assert writer["ok"] is False  # the racing writer replaced nothing mid-promotion
