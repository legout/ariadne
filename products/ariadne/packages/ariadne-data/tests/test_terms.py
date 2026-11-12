"""Context knowledge K2: structured References and scoped term resolution
(issue #42 / spec 2026-10-02-0010 §§3/5/6, §10 AC4/AC9-resolver/AC10-ingestion;
plan §2 "Structured References, authority and freshness" + the
``resolve_term``/``authoring_resolve_term`` rows and "Natural-language
matching"; ADR-0017).

A Reference page carries the versioned ``ariadne`` frontmatter extension
(integer version 1): a reference-role discriminator, ordered representations
with stable slug IDs, aliases, exact ``{resource, column}`` field bindings
and required scope, and mappings with family/endpoint/claim classification.
Legacy References without the extension stay readable; malformed supported
declarations and author-fabricated approval/measurement claims are rejected
by the shared per-type gate. ``resolve_term`` is the shared, read-only
resolver: deterministic casefolded whole-alias/phrase matching (never
substring), exact case-sensitive field identity, all eligible ambiguities
before the 20-match bound with explicit truncation/part continuation, actual
page/source citations, and hypotheses reported unconfirmed even when their
page is admitted (confirmation is K4). The same core envelopes serve the
local CLIs, the Analyst/Authoring/Combined MCP registrations and the native
role tools.

Real temporary Git repositories, real local parquet sources, real stdio MCP
sessions over the same launch the operator uses, fake providers for the
native role tools; no network, no live connector.
"""

import asyncio
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from ariadne.context import (  # noqa: E402
    RESOLVE_TERM_LIMIT,
    RESOLVE_TERM_MAX_BYTES,
    resolve_term,
)
from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.sources import table_resource  # noqa: E402
from tests.test_git_admission import admit  # noqa: E402 — the human-only G5 journey
from tests.test_git_authoring import approved  # noqa: E402 — the operator's G3 step

# One store-scoped order identity: (ABC, 123123) -> ABC123123 and
# (XYZ, 123123) -> XYZ123123 — the owner's illustrative example (spec §5),
# never a rule installed in every project.
ORDER_ROWS = [
    ("ABC", "123123", "ABC123123"),
    ("XYZ", "123123", "XYZ123123"),
]

MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: orders.orders
        primary_key: [store_id, local_order_number]
        fields:
          - name: store_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: store_id
            dimension: {}
          - name: local_order_number
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: local_order_number
            dimension: {}
          - name: global_order_number
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: global_order_number
            dimension: {}
    metrics:
      - name: order_number_count
        description: Count of order number pairs
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""


def _page(page_type: str, title: str, body: str, *, status: bool = False, sources=None) -> str:
    meta = {
        "type": page_type,
        "title": title,
        "description": f"The {title.lower()} page.",
        "tags": [page_type],
        "sources": sources or [{"id": "seed-notes", "resource": "data/seed_notes.md"}],
    }
    if status:
        meta["status"] = "draft"
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body}\n"


def orders_project(tmp_path: Path) -> Path:
    """A real temporary Git data project whose human-created initial artifact
    revision is a COMPLETE existing bundle over one parquet orders source: the
    model, one page of every legacy section the ADR-0007 gate checks (a legacy
    join Reference WITHOUT the extension among them) and the Seed Notes."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "data").mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('{store}', '{local}', '{global_id}')" for store, local, global_id in ORDER_ROWS
    )
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) "
        "t(store_id, local_order_number, global_order_number)) "
        f"TO '{project / 'data' / 'orders.parquet'}' (FORMAT PARQUET)"
    ).close()
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: orders\n    type: parquet\n    path: data/orders.parquet\n",
        encoding="utf-8",
    )
    (project / "data" / "seed_notes.md").write_text(
        "# Seed notes\n\nOrder numbers concatenate the store prefix and the local number.\n",
        encoding="utf-8",
    )
    models = project / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "orders.yml").write_text(MODEL_YML, encoding="utf-8")
    # C6 (spec0035 §6): the native authoring surface — knowledge/ KB plus the
    # revision-2 integrated selector whose authored §10.1 inventory binds the
    # governed metric and its generated computation to the narrative Policy
    # (enforcement null); the classic pages stay inert fixture payload.
    kb = project / "knowledge"
    (kb / "lumio.yaml").write_text(
        "version: 2\n"
        'mode: "categorized"\n'
        "categories:\n"
        "  - name: references\n"
        "  - name: policies\n"
        "  - name: metrics\n"
        "  - name: computations\n"
        "ontology:\n"
        "  entity_types:\n"
        "    reference: {}\n"
        "    policy: {}\n"
        "    metric: {}\n"
        "    computation: {}\n"
        "  predicates: {}\n"
        "  redirects: {}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_text(
        'version: 1\nnamespace: "urn:uuid:terms-fixture"\nsources: {}\nbindings: {}\n',
        encoding="utf-8",
    )
    (kb / "policies").mkdir(parents=True, exist_ok=True)
    (kb / "metrics").mkdir(parents=True, exist_ok=True)
    (kb / "policies" / "order-number-format.md").write_text(
        "---\n"
        'id: "entity:order-number-format"\n'
        'title: "Order number format"\n'
        "entity_types:\n  - policy\n"
        "tags:\n  - policy\n"
        'summary: "A global order number is the store prefix concatenated with'
        ' the local order number."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        "  - id: seed-notes\n"
        "    title: Seed notes\n"
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: policy\n"
        "  required_policies: []\n"
        "  native:\n"
        "    type: policy\n"
        "    title: Order number format\n"
        "    description: A global order number is the store prefix concatenated"
        " with the local order number.\n"
        "    tags:\n      - policy\n"
        "    status: draft\n"
        "    sources:\n"
        "      - id: seed-notes\n"
        "        title: Seed notes\n"
        "        resource: data/seed_notes.md\n"
        "---\n\n"
        "# Order number format\n",
        encoding="utf-8",
    )
    (kb / "metrics" / "order-number-count.md").write_text(
        "---\n"
        'id: "entity:order-number-count"\n'
        'title: "order_number_count"\n'
        "entity_types:\n  - metric\n"
        "tags:\n  - metric\n"
        'summary: "Count of orders."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        "  - id: order-number-format\n"
        "    title: Order number format\n"
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: metric\n"
        "  metric_ref:\n"
        "    model: orders\n"
        "    metric: order_number_count\n"
        "  required_policies:\n"
        '    - namespace: "urn:uuid:terms-fixture"\n'
        '      entity_id: "entity:order-number-format"\n'
        "  native:\n"
        "    type: metric\n"
        "    title: order_number_count\n"
        "    description: Count of orders.\n"
        "    tags:\n      - metric\n"
        "    status: draft\n"
        "    sources:\n"
        "      - id: order-number-format\n"
        "        title: Order number format\n"
        "        resource: policies/order-number-format.md\n"
        "    governed_by: policies/order-number-format.md\n"
        "---\n\n"
        "# order_number_count\n"
    )
    (project / "context_integration.yaml").write_text(
        "version: 1\n"
        "mode: integrated\n"
        "subtree: knowledge\n"
        "namespace: urn:uuid:terms-fixture\n"
        "profile: ariadne-context/1\n"
        "support_revision: 2\n"
        "policy_bindings:\n"
        "  version: 1\n"
        "  bindings:\n"
        "    - subject: {kind: metric, identity: orders::order_number_count}\n"
        "      policy: {namespace: urn:uuid:terms-fixture,"
        " entity_id: entity:order-number-format}\n"
        "      operations: [get_metric, query_metrics]\n"
        "      enforcement: null\n"
        "    - subject: {kind: computation, identity: orders::order_number_count}\n"
        "      policy: {namespace: urn:uuid:terms-fixture,"
        " entity_id: entity:order-number-format}\n"
        "      operations: [get_metric, query_metrics]\n"
        "      enforcement: null\n",
        encoding="utf-8",
    )
    pages = {
        "context_layer/tables/orders.md": _page(
            "table", "orders", "# Orders\n\nOne row per store-scoped order.\n"
        ),
        # a LEGACY join Reference: no ariadne extension, still readable
        "context_layer/references/joins/orders--orders.md": _page(
            "reference", "orders identity", "# orders identity\n"
        ),
        "context_layer/policies/order-number-format.md": _page(
            "policy",
            "Order number format",
            "# Order number format\n\nA global order number is the store prefix "
            "concatenated with the local order number.\n",
            status=True,
        ),
        "context_layer/metrics/order_number_count.md": _page(
            "metric",
            "order_number_count",
            "# order_number_count\n",
            status=True,
            sources=[
                {
                    "id": "order-number-format",
                    "resource": "policies/order-number-format.md",
                    "title": "Order number format",
                }
            ],
        ),
        "context_layer/skills/run-the-demo.md": _page("skill", "run the demo", "# run the demo\n"),
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
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


def run_git(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config (the Git-suite
    fixture): repo-local identity only."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def orders_resource() -> str:
    """The canonical credential-free resource of the orders table asset."""
    return table_resource("orders", None, "orders", "orders")


def order_reference_page(orders: str | None = None) -> str:
    """One structured Term Reference: the umbrella concept carries a local
    (store-scoped composite) and a global (concatenated) representation plus
    one unconfirmed prefix-mapping hypothesis citing the actual Seed Notes
    footnote."""
    orders = orders or orders_resource()
    native = {
        "type": "reference",
        "title": "Order number",
        "description": "The shared order-number concept of the orders store.",
        "tags": ["reference", "term"],
        "sources": [{"id": "seed-notes", "title": "Seed notes", "resource": "data/seed_notes.md"}],
        "aliases": ["order number concept"],
        "ariadne": {
            "version": 1,
            "reference_role": "term",
            "representations": [
                {
                    "id": "local-order-number",
                    "aliases": ["order number", "local order number", "store order number"],
                    "fields": [
                        {"resource": orders, "column": "local_order_number"},
                        {"resource": orders, "column": "store_id"},
                    ],
                    "scope": [{"resource": orders, "column": "store_id"}],
                },
                {
                    "id": "global-order-number",
                    "aliases": ["order number", "global order number"],
                    "fields": [{"resource": orders, "column": "global_order_number"}],
                    "scope": [],
                },
            ],
            "mappings": [
                {
                    "id": "local-to-global-prefix",
                    "family": "prefix",
                    "from": "local-order-number",
                    "to": "global-order-number",
                    "claim": "hypothesis",
                    "source_ids": ["seed-notes"],
                    "receipt_ids": [],
                }
            ],
        },
    }
    meta = {
        "id": "entity:order-number",
        "title": "Order number",
        "entity_types": ["reference"],
        "tags": ["reference", "term"],
        "summary": "The shared order-number concept of the orders store.",
        "lifecycle": "approved",
        "visibility": "public",
        "aliases": ["order number concept"],
        "sources": [{"id": "seed-notes", "title": "Seed notes", "resource": "data/seed_notes.md"}],
        "ariadne_profile": {
            "version": 1,
            "kind": "reference",
            "native": native,
        },
    }
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = (
        "# Order number\n\n"
        "The shared order-number concept. The local representation is the\n"
        "store-scoped composite; the global representation is the concatenated\n"
        "identity. The mapping between them is an unconfirmed hypothesis.\n"
    )
    return f"---\n{front}\n---\n\n{body}\n"


REFERENCE_PAGE_REL = "knowledge/references/order-number.md"


def reference_edit(content: str) -> list[dict]:
    """The Reference page as one native page-batch object."""
    return [{"path": REFERENCE_PAGE_REL, "content": content}]


def candidate_with_reference(tmp_path: Path) -> tuple[Path, AuthoringProject, dict]:
    """A real Git proposal whose candidate carries the structured Reference:
    start, operator approval, one revision-checked page edit."""
    project = orders_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        reference_edit(order_reference_page()),
    )
    return project, api, {"proposal": started["proposal"], "revision": edited["revision"]}


def admitted_with_reference(tmp_path: Path) -> tuple[Path, dict]:
    """An ADMITTED full-bundle project carrying the structured Reference: the
    complete human-only journey (approve, edit, validate, review,
    ``ariadne-admit --confirm``) performed outside every agent surface."""
    project = orders_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        reference_edit(order_reference_page()),
    )
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert validated["ok"] is True and validated["errors"] == []
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    return project, review


# ---------------------------------------------------------- [1] the red seam


def test_order_number_resolves_alternatives_with_exact_bindings_and_unconfirmed_mappings(
    tmp_path,
):
    """Issue #42 [1], the red seam: the umbrella alias returns the local/global
    ALTERNATIVES with their exact bindings and scope; the exact phrase and the
    exact qualified field identify the documented representation without
    applying a transform; the mapping hypothesis is reported UNCONFIRMED even
    though its page is admitted; the candidate side keeps the proposal's
    identity visible."""
    project, api, candidate = candidate_with_reference(tmp_path / "cand")
    orders = orders_resource()

    result = api.resolve_term(candidate["proposal"], "order number")
    assert result["proposal"] == candidate["proposal"]
    assert result["revision"] == candidate["revision"]
    assert result["candidate"] is True
    assert [match["representation"] for match in result["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert result["total_matches"] == 2
    assert result["ambiguous"] is True  # the alternatives stay alternatives
    assert result["truncated"] is False and result["complete"] is True
    local, global_order = result["matches"]
    assert local["level"] == "representation"
    assert local["page"] == "references/order-number.md"  # the actual page citation
    assert local["draft"] is False
    assert local["fields"] == [
        {"resource": orders, "column": "local_order_number"},
        {"resource": orders, "column": "store_id"},
    ]
    assert local["scope"] == [{"resource": orders, "column": "store_id"}]
    assert local["reference_role"] == "term"
    assert local["sources"] == [{"id": "seed-notes", "resource": "data/seed_notes.md"}]
    # the resolver never applies a transform, rewrites SQL or authorizes a join
    assert not ({"sql", "transform", "join"} & set(local))
    [mapping] = local["mappings"]
    assert mapping["id"] == "local-to-global-prefix"
    assert mapping["family"] == "prefix"
    assert mapping["claim"] == "hypothesis"
    assert mapping["confirmation"] == "unconfirmed"  # admission never confirms (K4)
    assert mapping["source_ids"] == ["seed-notes"]  # actual page footnotes
    assert mapping["receipt_ids"] == []  # allowlisting is not proof; receipts are K3
    assert global_order["fields"] == [{"resource": orders, "column": "global_order_number"}]

    # the exact phrase identifies one documented representation (casefolded)
    exact = api.resolve_term(candidate["proposal"], "GLOBAL Order Number")
    assert [match["representation"] for match in exact["matches"]] == ["global-order-number"]
    assert exact["ambiguous"] is False and exact["total_matches"] == 1

    # the exact qualified field identifies it too — exact identity, no casefolding
    field = api.resolve_term(
        candidate["proposal"], {"resource": orders, "column": "global_order_number"}
    )
    assert [match["representation"] for match in field["matches"]] == ["global-order-number"]
    miss = api.resolve_term(
        candidate["proposal"], {"resource": orders, "column": "GLOBAL_ORDER_NUMBER"}
    )
    assert miss["matches"] == [] and miss["total_matches"] == 0  # never case-folded

    # a substring is NEVER a match: whole aliases/phrases only
    partial = api.resolve_term(candidate["proposal"], "order")
    assert partial["matches"] == [] and partial["total_matches"] == 0

    # the admitted full-bundle side: Query serves the PINNED admitted revision
    admitted, review = admitted_with_reference(tmp_path / "admitted")
    runtime = QueryRuntime.open_project(admitted)
    served = asyncio.run(runtime.resolve_term("order number"))
    assert [match["representation"] for match in served["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert served["admission"]["revision"] == review["revision"]
    assert served["admission"]["route"] == "git-review-admission"
    admitted_mapping = served["matches"][1]["mappings"][0]
    assert admitted_mapping["claim"] == "hypothesis"
    # unconfirmed EVEN THOUGH the page is admitted (human confirmation is K4)
    assert admitted_mapping["confirmation"] == "unconfirmed"


# [2] the extension-v1 validation surface - DELETED with its exclusively
# retired surface (C6 G3, spec0035 section 6): the classic per-type OKF
# page-contract gate (`_reference_errors` staging a context_layer page) is
# removed from production. The LIVE native invariants of that surface are
# enforced at the producer envelope/ariadne-block validation (closed keys,
# exact version, resolvable structure) inside the public page batch and the
# candidate validation - asserted by the real-candidate tests below
# (fabricated-confirmation refusal, authored-extension acceptance) and by the
# resolver journeys.


def test_git_validation_rejects_fabricated_confirmation_in_a_real_candidate(tmp_path):
    """The shared gate rides the REAL Git validation journey: an edit seam
    accepts an invalid draft (validation owns structural failures), and
    validate_proposal reports the fabricated confirmation as a page-contract
    error instead of admitting the claim."""
    project = orders_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    page = yaml.safe_load(order_reference_page().split("---")[1])
    page["ariadne_profile"]["native"]["ariadne"]["mappings"][0]["confirmed"] = True
    front = yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()
    forged = f"---\n{front}\n---\n\n# Order number\n"
    edited = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        reference_edit(forged),
    )
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert validated["ok"] is False
    assert any("unsupported field(s) ['confirmed']" in error for error in validated["errors"])
    assert any(
        check["name"] == "page_contract" and check["outcome"] == "failed"
        for check in validated["report"]["checks"]
    )


def test_reference_extension_edits_are_authored_not_forged_claims(tmp_path):
    """The ``ariadne`` block of a REFERENCE page is the authored extension:
    a later edit may extend its aliases/bindings at the revision-checked seam
    (unlike a generated table page's core-owned ``ariadne`` facts)."""
    project, api, candidate = candidate_with_reference(tmp_path)
    page = yaml.safe_load(order_reference_page().split("---")[1])
    page["ariadne_profile"]["native"]["ariadne"]["representations"][1]["aliases"].append(
        "master order number"
    )
    front = yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()
    edited = api.edit_pages_batch(
        candidate["proposal"],
        candidate["revision"],
        reference_edit(f"---\n{front}\n---\n\n# Order number\n"),
    )
    assert edited["changed"] is True
    resolved = api.resolve_term(candidate["proposal"], "master order number")
    assert [match["representation"] for match in resolved["matches"]] == ["global-order-number"]


# ------------------------------------- [3] resolver determinism and bounds


def _context_root(tmp_path: Path, pages: dict[str, str]) -> Path:
    root = tmp_path / "context_layer"
    for rel, text in pages.items():
        page = root / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text, encoding="utf-8")
    return root


def test_resolver_bounds_matches_with_explicit_truncation_and_continuation(tmp_path):
    """All eligible ambiguities are visible BEFORE the bound: 25 matching
    representations return exactly the 20-match first part with the total and
    explicit truncation, part 2 completes the list, and uniqueness is never
    declared from a truncated result."""
    pages = {}
    for index in range(1, 26):
        page = yaml.safe_load(order_reference_page().split("---")[1])
        page["ariadne"]["representations"] = [
            {
                "id": f"rep-{index:02d}",
                "aliases": ["shared term"],
                "fields": [{"resource": orders_resource(), "column": "c"}],
                "scope": [],
            }
        ]
        page["ariadne_profile"]["native"]["ariadne"]["mappings"] = []
        pages[f"references/term-{index:02d}.md"] = (
            f"---\n{yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()}"
            "\n---\n\n# term\n"
        )
    root = _context_root(tmp_path, pages)

    first = resolve_term([(root, False)], "shared term")
    assert RESOLVE_TERM_LIMIT == 20
    assert first["total_matches"] == 25  # ambiguity counts every eligible match
    assert first["ambiguous"] is True
    assert len(first["matches"]) == 20
    assert first["truncated"] is True
    assert first["complete"] is False
    assert first["part"] == 1 and first["parts"] == 2

    second = resolve_term([(root, False)], "shared term", part=2)
    assert len(second["matches"]) == 5
    assert second["complete"] is True
    assert second["truncated"] is True  # the full result spans more than this part

    beyond = resolve_term([(root, False)], "shared term", part=3)
    assert beyond["matches"] == [] and beyond["complete"] is False
    assert beyond["exhausted"] is True

    # stable page/representation order: part boundaries are deterministic
    ids = [match["representation"] for match in first["matches"]]
    assert ids == sorted(ids)
    assert [match["representation"] for match in second["matches"]][0] == "rep-21"


def test_resolver_response_parts_stay_under_the_64kib_ceiling(tmp_path):
    """Plan §2: the resolver shares the operator's 64 KiB serialized-response
    ceiling. A match whose serialized form alone cannot fit a whole part is
    DISCLOSED bounded — identity intact, its long fields cut with an explicit
    elision marker naming what was omitted — never silently dropped nor
    overflowed; ambiguity totals stay honest and byte-bounded continuation
    still works."""
    huge = yaml.safe_load(order_reference_page().split("---")[1])
    huge["description"] = "A documented order-number concept. " + "detail " * 10_000
    # oversized OPTIONAL metadata rides the same entry: its elision must be
    # named explicitly (spec 0011 §4) — a bounded disclosure never poses as a
    # complete warning-free assessment
    huge["sources"] = [
        {"id": "seed-notes", "resource": "data/seed_notes.md", "title": "note " * 40},
        *[
            {"id": f"seed-{i}", "resource": f"data/seed_notes_{i}.md", "title": "note " * 40}
            for i in range(11)
        ],
    ]
    root = _context_root(
        tmp_path,
        {
            "references/huge.md": (
                f"---\n{yaml.safe_dump(huge, default_flow_style=False, sort_keys=False).strip()}"
                "\n---\n\n# Order number\n"
            )
        },
    )
    first = resolve_term([(root, False)], "order number")
    assert len(json.dumps(first).encode("utf-8")) < RESOLVE_TERM_MAX_BYTES
    assert first["total_matches"] == 2 and first["ambiguous"] is True
    assert [match["representation"] for match in first["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    for match in first["matches"]:  # disclosed bounded, never silently dropped
        assert match["elided"] and any("description" in marker for marker in match["elided"])
        assert len(match["description"]) < 2_000  # the field itself is bounded
        # the advisory envelope rides the match, and its cut metadata is named
        # in the elided list — an omitted warning list is never readable as a
        # complete warning-free assessment (spec 0011 §4)
        assert match["context_signals"]["pages"][0]["path"] == "references/huge.md"
        assert any(
            marker.startswith("context_signals.pages[0].sources") for marker in match["elided"]
        ) or any("more elisions" in marker for marker in match["elided"])
    assert first["truncated"] is False and first["complete"] is True

    # byte-bounded continuation: matches that fit alone but not together split
    # across parts with honest totals and stable page/representation order
    medium = {}
    for index in range(1, 6):
        page = yaml.safe_load(order_reference_page().split("---")[1])
        page["description"] = f"Medium concept {index}. " + "detail " * 2_000
        page["ariadne"]["representations"] = [
            {
                "id": f"rep-{index:02d}",
                "aliases": ["shared term"],
                "fields": [{"resource": orders_resource(), "column": "c"}],
                "scope": [],
            }
        ]
        page["ariadne_profile"]["native"]["ariadne"]["mappings"] = []
        medium[f"references/term-{index:02d}.md"] = (
            f"---\n{yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()}"
            "\n---\n\n# term\n"
        )
    spread = _context_root(tmp_path / "medium", medium)
    part_one = resolve_term([(spread, False)], "shared term")
    assert len(part_one["matches"]) < 5  # the byte ceiling, not the count limit, bound this part
    assert len(json.dumps(part_one).encode("utf-8")) < RESOLVE_TERM_MAX_BYTES
    assert part_one["total_matches"] == 5 and part_one["truncated"] is True
    part_two = resolve_term([(spread, False)], "shared term", part=2)
    assert len(json.dumps(part_two).encode("utf-8")) < RESOLVE_TERM_MAX_BYTES
    assert part_two["complete"] is True
    ids = [m["representation"] for m in part_one["matches"] + part_two["matches"]]
    assert ids == sorted(ids) and len(ids) == 5  # stable order, nothing dropped


def test_resolver_reports_concept_matches_with_all_representations(tmp_path):
    """A page-level alias names the CONCEPT: matching it returns a concept-level
    entry carrying every representation identity, while representation aliases
    stay representation-level matches."""
    root = _context_root(tmp_path, {"references/order-number.md": order_reference_page()})
    concept = resolve_term([(root, False)], "Order Number Concept")
    assert [match["level"] for match in concept["matches"]] == ["concept"]
    entry = concept["matches"][0]
    assert entry["representation"] is None
    assert [rep["id"] for rep in entry["representations"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert entry["mappings"] and entry["mappings"][0]["id"] == "local-to-global-prefix"
    rep_match = resolve_term([(root, False)], "local order number")
    assert rep_match["matches"][0]["level"] == "representation"
    assert rep_match["matches"][0]["representation"] == "local-order-number"


def test_resolver_fails_explicitly_on_malformed_pages_and_requests(tmp_path):
    """A malformed supported Reference fails the resolution explicitly (named
    page and error), and malformed requests are actionable errors — never a
    silent empty result."""
    malformed = order_reference_page().replace("version: 1", "version: 2")
    root = _context_root(tmp_path, {"references/broken.md": malformed})
    with pytest.raises(ValueError, match="references/broken.md.*unsupported ariadne"):
        resolve_term([(root, False)], "order number")
    with pytest.raises(ValueError, match="non-empty term"):
        resolve_term([(root, False)], "   ")
    with pytest.raises(ValueError, match="exactly \\{resource, column\\}"):
        resolve_term([(root, False)], {"resource": orders_resource()})
    with pytest.raises(ValueError, match="canonical resource"):
        resolve_term([(root, False)], {"resource": "orders", "column": "id"})
    with pytest.raises(ValueError, match="positive integer"):
        resolve_term([(root, False)], "order number", part=0)
    # a page the resolver does not own (non-reference/legacy) is skipped
    quiet = _context_root(
        tmp_path / "quiet",
        {"references/legacy.md": _page("reference", "legacy", "# legacy\n")},
    )
    assert resolve_term([(quiet, False)], "order number")["matches"] == []


# ------------------------------------- [5] the shared adapters, one core


def test_local_cli_serves_resolve_term_over_the_pinned_admission(tmp_path, capsys):
    """``ariadne resolve-term`` (managed route) and ``ariadne-authoring
    resolve-term`` (explicitly selected proposal) print the SAME core envelope
    as the Python surface: one JSON value on success, one error object on a
    malformed request."""
    project, review = admitted_with_reference(tmp_path / "admitted")
    capsys.readouterr()  # the admission journey prints; clear before the CLI calls
    code = cli(["resolve-term", "order number", "--project", str(project)])
    assert code == 0
    served = json.loads(capsys.readouterr().out)
    assert [match["representation"] for match in served["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert served["admission"]["revision"] == review["revision"]

    # the exact-field form through --file (stdin convention of the other
    # request-carrying commands)
    request = tmp_path / "field.json"
    request.write_text(
        json.dumps({"resource": orders_resource(), "column": "global_order_number"}),
        encoding="utf-8",
    )
    code = cli(["resolve-term", "--project", str(project), "--file", str(request)])
    assert code == 0
    field = json.loads(capsys.readouterr().out)
    assert [match["representation"] for match in field["matches"]] == ["global-order-number"]

    code = cli(["resolve-term", "--project", str(project), "--file", "-"], stdin=io.StringIO("{}"))
    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert "error" in error

    # the Authoring CLI resolves an explicitly selected proposal (read-only)
    cand_project, _api, candidate = candidate_with_reference(tmp_path / "cand")
    capsys.readouterr()  # clear the candidate journey's own output
    code = authoring_cli(
        [
            "resolve-term",
            "--proposal",
            candidate["proposal"],
            "--project",
            str(cand_project),
            "order number",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate"] is True
    assert payload["revision"] == candidate["revision"]
    assert payload["total_matches"] == 2

    code = authoring_cli(
        ["resolve-term", "--proposal", "p-nonexistent", "--project", str(cand_project), "x"]
    )
    assert code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_mcp_resolve_term_routes_share_the_core(tmp_path):
    """Three applicable MCP routes over ONE core: Analyst ``resolve_term``
    serves the pinned admitted revision; Authoring
    ``authoring_resolve_term`` resolves an explicitly selected proposal with
    the candidate identity visible (the Combined registration carries both —
    its exact toolset is asserted in tests/test_mcp_toolsets.py)."""
    from mcp import (  # noqa: E402 — [mcp] extra  # pyright: ignore[reportMissingImports]
        ClientSession,
    )

    from tests.test_mcp_toolsets import (  # noqa: E402
        _launch,
        _text,
    )

    project, review = admitted_with_reference(tmp_path / "admitted")

    async def run() -> dict:
        out = {}
        async with _launch(project, "analyst") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["analyst"] = json.loads(
                    _text(await session.call_tool("resolve_term", {"request": "order number"}))
                )
                refused = await session.call_tool("authoring_resolve_term", {})
                out["analyst_refused"] = refused.is_error
        async with _launch(project, "authoring") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                started = json.loads(_text(await session.call_tool("authoring_start_proposal", {})))
                out["started"] = started
                out["authoring"] = json.loads(
                    _text(
                        await session.call_tool(
                            "authoring_resolve_term",
                            {
                                "proposal": started["proposal"],
                                "request": "global order number",
                            },
                        )
                    )
                )
                refused = await session.call_tool("resolve_term", {})
                out["authoring_refused"] = refused.is_error
        return out

    out = asyncio.run(run())

    analyst = out["analyst"]
    assert [match["representation"] for match in analyst["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert analyst["admission"]["revision"] == review["revision"]
    authoring = out["authoring"]
    assert authoring["candidate"] is True
    assert authoring["revision"] == out["started"]["candidate_revision"]
    assert [match["representation"] for match in authoring["matches"]] == ["global-order-number"]
    # each registration is its own surface: the other role's tool is refused
    assert out["analyst_refused"] is True
    assert out["authoring_refused"] is True


# ------------------------------------- [6] preserved retrieval behavior


def test_term_resolution_preserves_search_context_and_metric_context(tmp_path):
    """The resolver adds a surface; it does not retune retrieval: the lexical
    ``search_context`` ranking, passage pointers and full metric/Policy bodies
    keep their exact shapes beside the new Reference page."""
    project, _review = admitted_with_reference(tmp_path / "admitted")
    runtime = QueryRuntime.open_project(project)
    hits = asyncio.run(runtime.search_context("order number"))
    assert hits, "the reference and policy pages stay lexically discoverable"
    for hit in hits:
        assert {"excerpt", "line_start", "line_end", "section", "content"} <= set(hit)
    answer = asyncio.run(runtime.get_metric("order_number_count"))
    assert answer["governed"] is True
    assert "order_number_count" in answer["context"]["metric_page"]
    assert answer["context"]["policies"], "the full cited Policy body still rides along"
