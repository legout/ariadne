"""Spec 0015 (issue #60): token-free Context Layer browsing at the shared
QueryRuntime seam — ``list_context_pages`` and ``read_context_page``.

Expectations derive from the specification and the fixture pages written
below (known paths, titles, bodies and draft identity), never from the
implementation: the listing is a metadata-only directory (served before
staged, then path, titles from frontmatter/heading/none), the read returns
exactly one full page with the right draft flag, and every invalid path is
a ValueError naming the rejected path. The managed-route pinned-tamper
refusal (AC4) lives with the Git admission fixtures in test_git_admission.
"""

import asyncio
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.query import QueryRuntime  # pyright: ignore[reportMissingImports] — drift

# One governed model over a declared CSV source so the runtime constructs and
# compiles exactly like every production route (the established fixture shape).
_MODES = """version: 0.2.0.dev0
semantic_model:
  - name: probe
    description: browsing probe
    datasets:
      - name: vals
        source: vals.vals
        fields:
          - name: v
            expression: {dialects: [{dialect: ANSI_SQL, expression: v}]}
    metrics:
      - name: total
        description: sum of the fixture values
        expression: {dialects: [{dialect: ANSI_SQL, expression: "SUM(v)"}]}
"""

SERVED_POLICY_BODY = (
    "---\ntype: policy\ntitle: Order status billing\n---\n\nOrders bill only in COMPLETED status.\n"
)
SERVED_METRIC_BODY = "# Total value\n\nSum over all rows.\n"
SERVED_GLOSSARY_BODY = "Billing period text without a title or heading.\n"
STAGED_POLICY_BODY = (
    "---\n"
    "type: policy\n"
    "title: Order status billing (draft)\n"
    "---\n"
    "\n"
    "DRAFT: proposes billing in any non-cancelled status.\n"
)


@pytest.fixture(scope="module")
def runtime(tmp_path_factory) -> QueryRuntime:
    root = tmp_path_factory.mktemp("browsing_project")
    (root / "data").mkdir()
    (root / "data" / "vals.csv").write_text("v\n2\n3\n", encoding="utf-8")
    (root / "semantic_layer" / "models").mkdir(parents=True)
    (root / "semantic_layer" / "models" / "probe.yml").write_text(_MODES, encoding="utf-8")
    context = root / "context_layer"
    (context / "policies").mkdir(parents=True)
    (context / "policies" / "order-status.md").write_text(SERVED_POLICY_BODY, encoding="utf-8")
    (context / "metrics").mkdir()
    (context / "metrics" / "total.md").write_text(SERVED_METRIC_BODY, encoding="utf-8")
    (context / "glossary").mkdir()
    (context / "glossary" / "billing-period.md").write_text(SERVED_GLOSSARY_BODY, encoding="utf-8")
    staging = root / "staging"
    (staging / "context_layer" / "policies").mkdir(parents=True)
    (staging / "context_layer" / "policies" / "order-status.md").write_text(
        STAGED_POLICY_BODY, encoding="utf-8"
    )
    registry = root / "ariadne.yaml"
    registry.write_text(
        f"sources:\n  - name: vals\n    type: csv\n    path: {root / 'data' / 'vals.csv'}\n",
        encoding="utf-8",
    )
    return QueryRuntime(
        root / "semantic_layer",
        context,
        None,  # the registry route: no legacy --db attach
        staging_dir=staging,
        sources=str(registry),
    )


def test_listing_is_a_metadata_directory_served_before_staged(runtime):
    """AC1: every served and staged page appears exactly once with path, draft,
    title and context_signals — never a body — served before staged, path order."""
    listing = asyncio.run(runtime.list_context_pages())
    assert [(entry["path"], entry["draft"]) for entry in listing] == [
        ("glossary/billing-period.md", False),
        ("metrics/total.md", False),
        ("policies/order-status.md", False),
        ("policies/order-status.md", True),  # the staged draft, same path, listed after
    ]
    titles = {entry["path"] + str(entry["draft"]): entry["title"] for entry in listing}
    assert titles["glossary/billing-period.mdFalse"] is None  # neither frontmatter nor heading
    assert titles["metrics/total.mdFalse"] == "Total value"  # first ATX heading
    assert titles["policies/order-status.mdFalse"] == "Order status billing"  # frontmatter
    assert titles["policies/order-status.mdTrue"] == "Order status billing (draft)"
    for entry in listing:
        assert "content" not in entry, "the listing never carries page bodies"
        signals = entry["context_signals"]
        assert signals["pages"][0]["path"] == entry["path"]


def test_read_returns_the_exact_served_and_staged_page(runtime):
    """AC2: one full page per exact path — served by default, staged with
    draft=true — each carrying the truthful draft flag."""
    served = asyncio.run(runtime.read_context_page("policies/order-status.md"))
    assert served == {
        "path": "policies/order-status.md",
        "draft": False,
        "content": SERVED_POLICY_BODY,
        "context_signals": served["context_signals"],  # envelope checked below
    }
    assert served["context_signals"]["pages"][0]["path"] == "policies/order-status.md"
    draft = asyncio.run(runtime.read_context_page("policies/order-status.md", draft=True))
    assert draft["draft"] is True
    assert draft["content"] == STAGED_POLICY_BODY
    assert draft["context_signals"]["pages"][0]["path"] == "policies/order-status.md"


def test_invalid_paths_refuse_naming_the_rejected_path(runtime, tmp_path):
    """AC3: absolute, escaping, backslashed, non-markdown, symlink-escaping and
    unknown paths each raise ValueError naming the path — nothing reads."""
    outside = tmp_path / "outside-secret.md"
    outside.write_text("secret", encoding="utf-8")
    secret = Path(runtime.context_dir) / "policies" / "secret.md"
    secret.symlink_to(outside)
    for bad in (
        "/etc/passwd.md",
        "../order-status.md",
        "policies\\order-status.md",
        "policies/order-status.txt",
        "policies/missing.md",
        "policies/secret.md",  # symlink out of the served root
        "",
    ):
        with pytest.raises(ValueError, match="unknown context page") as refusal:
            asyncio.run(runtime.read_context_page(bad))
        assert repr(bad) in str(refusal.value), "the refusal names the rejected path"
