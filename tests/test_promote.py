"""Mechanical promotion gate (spec rev 6 §8.16): merge-only promotion bookkeeping.

Exercises ariadne.promote (the logic behind ``ariadne-promote`` / the
``scripts/promote.py`` shim) against fixture staging/served trees: verified
append + status flip, index regeneration, log.md entries, idempotency, and the
merge-never-wipes invariant. The staged pages mirror the real author output
shape so the frontmatter round-trip is exercised for real.
"""

from pathlib import Path

import pytest
import yaml

from ariadne.promote import Change, _index_for, main, promote

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
    resource: data/seed_notes.md
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
    resource: data/demo.db
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


def test_promote_cli_yes(tmp_path):
    staging, served = make_staging(tmp_path / "staging"), tmp_path / "served"
    code = main(["--yes", "--staging", str(staging), "--served", str(served), "--by", BY])
    assert code == 0
    assert (served / "context_layer" / "metrics" / "index.md").is_file()
    meta = front(served / "context_layer" / "metrics" / "gross_margin.md")
    assert meta["verified"] == [{"by": BY, "at": meta["verified"][0]["at"]}]  # one entry
    assert meta["verified"][0]["at"]  # stamped with the promotion time
