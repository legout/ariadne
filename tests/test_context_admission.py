"""Context knowledge K4: context-only admission and exact-assertion human
confirmation/freshness (issue #44 / spec 2026-10-02-0010 §§3/5/6/8/9 + §10
AC3/4/6/8; plan §2 "Admission and automatic capture"; ADR-0017).

A human-admitted context-only Git revision (schemas/References, no metrics)
opens for discovery and term resolution while every metric request keeps its
SPECIFIC missing-catalog error (spec §6/§9): validation reports APPLICABLE
checks with explicit ``not_applicable`` reasons — semantic compile/bind/Grain
are omitted ONLY when no effective semantic declaration requires them, and an
inherited unsafe semantic declaration still refuses a page-only candidate.
Asserted mappings become confirmed ONLY through the human
``--confirm-mapping <reference-slug>:<mapping-id>`` selection plus explicit
``--confirm`` on the exact reviewed revision: review reading never grants
confirmation, an author-fabricated page flag never does, and a hypothesis can
never be selected as a confirmed assertion. Unchanged assertions retain prior
human evidence only with unchanged verified dependencies; changed, stale or
conflicting assertions cannot inherit confirmation.

Real temporary Git repositories (repo-local identity only), real parquet
sources, no network, no provider. Independent expected values are hand-written
from the fixture rows, never derived from runtime output.
"""

import asyncio
import io
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import context as context_module  # noqa: E402
from ariadne import proposals  # noqa: E402
from ariadne.admission import main as admit_cli  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from ariadne.context import (  # noqa: E402
    _canonical_digest,
    confirmation_binding_digest,
)
from ariadne.planner import PlannerError  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.sources import table_resource  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    METRIC_PAGE,
    POLICY_PAGE,
    UNSAFE_GRAIN_MODEL_YML,
    approved,
    branch_of,
    complete_bundle_project,
    run_git,
    write_parquet,
)

STATE = proposals.ARIADNE_STATE_DIR
CURRENT = STATE / "current.json"
SNAPSHOTS = STATE / "snapshots"

# The owner's illustrative scoped-identity rows (spec 0010 §5): ABC and XYZ
# share the local number 123123 as TWO identities; the leading zero survives.
ORDER_ROWS = [
    # store_id, local_order_number, global_order_number
    ("ABC", "123123", "ABC123123"),
    ("XYZ", "123123", "XYZ123123"),
    ("ABC", "00123", "ABC00123"),
]

SEED_NOTES = (
    "# Seed notes\n\nA global order number is the store prefix concatenated "
    "with the local order number; leading zeros are retained.\n"
)

# The SPECIFIC missing-catalog error a metric request keeps on an admitted
# context-only snapshot (spec 0010 §6: discovery/resolution work, metric
# operations refuse, no absent model ever triggers a raw-SQL fallback).
MISSING_CATALOG_MARK = "no governed metric catalog"


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def orders_resource() -> str:
    """The canonical credential-free resource of the orders table asset."""
    return table_resource("orders", None, "orders", "orders")


def read_current(project: Path) -> dict:
    return json.loads((project / CURRENT).read_text(encoding="utf-8"))


def blobs_of(project: Path, revision: str) -> dict[str, bytes]:
    return {rel: blob for rel, blob in proposals.scope_blobs(project, revision)}


def context_only_project(tmp_path: Path) -> Path:
    """A real temporary Git data project whose human-created initial artifact
    revision is CONTEXT-ONLY: registry + Seed Notes over one parquet orders
    source, NO semantic layer at all — the project documents its schema and
    shared terminology before the first metric exists (spec 0010 §9)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_parquet(
        project / "data" / "orders.parquet",
        ORDER_ROWS,
        ["store_id", "local_order_number", "global_order_number"],
    )
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: orders\n    type: parquet\n    path: data/orders.parquet\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: context-only base")
    return project


def table_page() -> str:
    """One authored physical-table page citing the catalog asset."""
    meta = {
        "type": "table",
        "title": "orders",
        "description": "One row per store-scoped order.",
        "tags": ["table"],
        "sources": [
            {"id": "orders-catalog", "resource": orders_resource(), "title": "orders catalog"}
        ],
    }
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n# orders\n\nOne row per store-scoped order.\n"


def order_reference_page(orders: str | None = None, *, asserted: bool = True) -> str:
    """One structured Term Reference: the umbrella concept with a local
    (store-scoped composite) and a global (concatenated) representation, one
    prefix-mapping HYPOTHESIS and — optionally — one ASSERTED mapping citing
    the actual Seed Notes footnote (spec 0010 §5: an asserted mapping is
    presented for human review, never confirmed by being written)."""
    orders = orders or orders_resource()
    mappings = [
        {
            "id": "local-to-global-prefix",
            "family": "prefix",
            "from": "local-order-number",
            "to": "global-order-number",
            "claim": "hypothesis",
            "source_ids": ["seed-notes"],
            "receipt_ids": [],
        }
    ]
    if asserted:
        mappings.append(
            {
                "id": "global-order-concatenation",
                "family": "prefix",
                "from": "local-order-number",
                "to": "global-order-number",
                "claim": "asserted",
                "source_ids": ["seed-notes"],
                "receipt_ids": [],
            }
        )
    meta = {
        "type": "reference",
        "title": "Order number",
        "description": "The shared order-number concept of the orders store.",
        "tags": ["reference", "term"],
        "sources": [{"id": "seed-notes", "resource": "data/seed_notes.md", "title": "Seed notes"}],
        "aliases": ["order number concept"],
        "ariadne": {
            "version": 1,
            "reference_role": "term",
            "representations": [
                {
                    "id": "local-order-number",
                    "aliases": ["order number", "local order number", "store order number"],
                    "fields": [
                        {"resource": orders, "column": "store_id"},
                        {"resource": orders, "column": "local_order_number"},
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
            "mappings": mappings,
        },
    }
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = (
        "# Order number\n\n"
        "The shared order-number concept. The local representation is the\n"
        "store-scoped composite; the global representation is the concatenated\n"
        "identity. The prefix mapping is carried as a hypothesis; the asserted\n"
        "concatenation rule awaits human confirmation.\n"
    )
    return f"---\n{front}\n---\n\n{body}\n"


TABLE_EDIT = {"kind": "page", "section": "tables", "name": "orders"}
REFERENCE_EDIT = {"kind": "page", "section": "references", "name": "order-number"}


def context_only_candidate(
    tmp_path: Path, *, asserted: bool = True
) -> tuple[Path, AuthoringProject, dict]:
    """The started+approved context-only proposal carrying the schema page and
    the structured Reference: (project, api, {proposal, revision})."""
    project = context_only_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {**REFERENCE_EDIT, "content": order_reference_page(asserted=asserted)},
    )
    edited = api.edit_proposal(
        started["proposal"],
        edited["revision"],
        {**TABLE_EDIT, "content": table_page()},
    )
    return project, api, {"proposal": started["proposal"], "revision": edited["revision"]}


def admit(
    project: Path, review: dict, *, confirm: bool = True, confirm_mapping: list[str] = ()
) -> int:
    argv = [
        "--project",
        str(project),
        "--proposal",
        review["proposal"],
        "--revision",
        review["revision"],
        "--reviewed-digest",
        review["review_digest"],
        *(f"--confirm-mapping={selection}" for selection in confirm_mapping),
    ]
    if confirm:
        argv.append("--confirm")
    return admit_cli(argv)


def mapping_view(result: dict, representation: str, mapping_id: str) -> dict:
    """One mapping view of a resolve_term result, addressed by representation
    and mapping id (fail loudly when the fixture page drifts)."""
    for match in result["matches"]:
        if match["representation"] != representation:
            continue
        for mapping in match["mappings"]:
            if mapping["id"] == mapping_id:
                return mapping
    raise AssertionError(f"no mapping view {mapping_id!r} under {representation!r}")


# ---------------------------------------------------------- [1] the red seam


def test_context_only_admission_resolves_hypotheses_without_confirming_them_or_creating_metrics(
    tmp_path,
):
    """Issue #44 [1], the red seam: approve the sources, then drive the exact
    schema/Reference-only revision through the whole human seam — validate
    with an APPLICABILITY report, review, ``ariadne-admit --confirm`` — and
    the admitted project resolves its terminology (hypothesis AND unselected
    assertion stay unconfirmed) while every metric request returns the
    SPECIFIC missing-catalog error: a context-only snapshot opens for
    discovery/resolution without eagerly requiring metrics, and no absent
    model ever triggers a raw-SQL fallback."""
    project, api, candidate = context_only_candidate(tmp_path / "proj")
    revision = candidate["revision"]

    # validation: every effective page/source/citation/evidence check runs;
    # semantic compile/bind/Grain are not_applicable WITH reasons
    validated = api.validate_proposal(candidate["proposal"], revision)
    assert validated["ok"] is True and validated["errors"] == []
    checks = {check["name"]: check for check in validated["report"]["checks"]}
    for name in ("structural", "compile", "conformance", "bind", "grain", "relationship_audit"):
        assert checks[name]["outcome"] == "not_applicable", name
        assert checks[name]["detail"], f"{name} carries no not_applicable reason"
    assert "no semantic declarations" in checks["compile"]["detail"]
    assert "no semantic declarations" in checks["grain"]["detail"]
    for name in ("source_boundary", "page_contract", "citations", "mapping_evidence"):
        assert checks[name]["outcome"] == "passed", name
    # no metric was invented to satisfy a presence rule
    assert not [rel for rel in validated["artifact_files"] if "metrics/" in rel]

    # review, then the human admission of the EXACT reviewed revision
    review = api.review_proposal(candidate["proposal"])
    assert review["revision"] == validated["revision"]
    assert review["report"]["ok"] is True
    assert admit(project, review) == 0
    current = read_current(project)
    assert current["commit"] == review["revision"]
    assert current["confirmed_mappings"] == []  # no selection = no confirmation
    snapshot = project / SNAPSHOTS / current["commit"]
    assert not (snapshot / "semantic_layer" / "models").exists()  # context-only served

    # the managed runtime opens the context-only snapshot for discovery
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("order number"))
    assert [match["representation"] for match in served["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert served["admission"]["revision"] == review["revision"]
    assert served["admission"]["route"] == "git-review-admission"
    hypothesis = mapping_view(served, "local-order-number", "local-to-global-prefix")
    assert hypothesis["claim"] == "hypothesis"
    assert hypothesis["confirmation"] == "unconfirmed"  # admission never confirms
    assertion = mapping_view(served, "local-order-number", "global-order-concatenation")
    assert assertion["claim"] == "asserted"
    assert assertion["confirmation"] == "unconfirmed"  # no human selection happened
    hits = asyncio.run(runtime.search_context("order number"))
    assert hits and not any(hit["draft"] for hit in hits)
    datasets = asyncio.run(runtime.list_datasets())
    assert [entry["table"] for entry in datasets] == ["orders"]

    # every metric request keeps the SPECIFIC missing-catalog error — no
    # fallback raw SQL anywhere
    with pytest.raises(ValueError, match=MISSING_CATALOG_MARK):
        asyncio.run(runtime.list_metrics())
    with pytest.raises(ValueError, match=MISSING_CATALOG_MARK):
        asyncio.run(runtime.get_metric("order_number_count"))
    with pytest.raises(PlannerError, match=MISSING_CATALOG_MARK):
        asyncio.run(runtime.query_metrics({"metrics": ["order_number_count"]}))
    with pytest.raises(PlannerError, match=MISSING_CATALOG_MARK):
        asyncio.run(runtime.query_detail({"dataset": "orders", "fields": ["store_id"]}))


# ----------------------- [2] the applicability decision and inherited gates


@pytest.mark.parametrize(
    "variant",
    ["unsafe-grain", "broken-policy"],
    ids=["unsafe-inherited-grain", "broken-governing-policy"],
)
def test_semantic_checks_stay_full_for_inherited_declarations(tmp_path, variant):
    """Issue #44 [2]: a page-only change never bypasses the inherited semantic
    gates — an unsafe inherited Grain (the labels join fans out the events
    grain) or a broken governing Policy citation refuses validation with the
    semantic/citation check FAILED, never not_applicable, even though the
    edit itself touched not one semantic byte (spec 0010 §9: existing
    inherited semantic artifacts still undergo their applicable checks)."""
    project = complete_bundle_project(tmp_path / "proj")
    if variant == "unsafe-grain":
        (project / "semantic_layer" / "models" / "events.yml").write_text(
            UNSAFE_GRAIN_MODEL_YML, encoding="utf-8"
        )
        run_git(project, "add", "--", "semantic_layer/models/events.yml")
        run_git(
            project,
            "commit",
            "-q",
            "-m",
            "human: unsafe inherited model",
            "--",
            "semantic_layer/models/events.yml",
        )
        edit = {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        }
        failing = "grain"
    else:  # broken governing Policy: the metric page cites an unresolvable page
        (project / "context_layer" / "metrics" / "event_count.md").write_text(
            METRIC_PAGE.replace("policies/all-events-count.md", "policies/missing.md"),
            encoding="utf-8",
        )
        run_git(project, "add", "--", "context_layer/metrics/event_count.md")
        run_git(
            project,
            "commit",
            "-q",
            "-m",
            "human: broken policy citation",
            "--",
            "context_layer/metrics/event_count.md",
        )
        edit = {
            "kind": "page",
            "section": "skills",
            "name": "run-the-demo",
            "content": (project / "context_layer" / "skills" / "run-the-demo.md")
            .read_text(encoding="utf-8")
            .replace("One skill page.", "One skill page, revised."),
        }
        failing = "citations"

    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(started["proposal"], started["candidate_revision"], edit)
    result = api.validate_proposal(started["proposal"], edited["revision"])
    assert result["ok"] is False
    checks = {check["name"]: check for check in result["report"]["checks"]}
    assert checks[failing]["outcome"] == "failed", failing
    # the semantic checks ran — they are never not_applicable while the
    # inherited OSI/metric/Policy declarations are effective
    for name in ("structural", "compile", "bind", "grain"):
        assert checks[name]["outcome"] != "not_applicable", name
    assert not (project / proposals.ARIADNE_STATE_DIR / "current.json").exists()


# --------------------- [3] the review surface and the human selection flow


def admitted_candidate(tmp_path, *, asserted=True, edit=None):
    """The validated+reviewed (not yet admitted) context-only candidate, with
    an optional extra page edit applied after the Reference."""
    project, api, candidate = context_only_candidate(tmp_path, asserted=asserted)
    revision = candidate["revision"]
    if edit is not None:
        revision = api.edit_proposal(candidate["proposal"], revision, edit)["revision"]
    validated = api.validate_proposal(candidate["proposal"], revision)
    assert validated["ok"] is True and validated["errors"] == []
    review = api.review_proposal(candidate["proposal"])
    assert review["revision"] == validated["revision"]
    return project, api, review


def test_review_exposes_assertion_identity_and_confirmation_eligibility(tmp_path):
    """Issue #44 [3]: the review lists each structured mapping's page
    resource, mapping ID, assertion digest, dependencies/evidence and
    confirmation eligibility — the asserted mapping is confirmable, the
    hypothesis is listed but never selectable, and reading this surface
    confirms nothing."""
    project, _api, review = admitted_candidate(tmp_path / "proj")

    by_id = {entry["mapping"]: entry for entry in review["mapping_assertions"]}
    assert set(by_id) == {"local-to-global-prefix", "global-order-concatenation"}
    hypothesis, assertion = by_id["local-to-global-prefix"], by_id["global-order-concatenation"]
    assert hypothesis["page"] == "references/order-number.md"
    assert hypothesis["reference"] == "order-number"
    assert hypothesis["claim"] == "hypothesis" and hypothesis["confirmable"] is False
    assert "hypothesis" in hypothesis["confirmation_note"]
    assert assertion["claim"] == "asserted" and assertion["confirmable"] is True
    # the assertion identity a confirmation binds is the declaration PLUS its
    # endpoint representations' normalized correspondence (K4 fix pass,
    # finding 2) — the exact page's meta decides it
    page = yaml.safe_load(order_reference_page().split("---", 2)[1])
    [declared] = [
        mapping
        for mapping in page["ariadne"]["mappings"]
        if mapping["id"] == "global-order-concatenation"
    ]
    assert assertion["assertion_digest"] == confirmation_binding_digest(page, declared)
    assert assertion["source_ids"] == ["seed-notes"]  # the actual dependencies
    assert assertion["receipts"] == []  # no receipts cited
    # reading the review confirmed nothing: no admission exists
    assert not (project / CURRENT).exists()


def test_confirmation_flow_selects_displays_and_confirms_exactly_one_assertion(tmp_path, capsys):
    """Issue #44 [3]+[4]: the assertion variant — NO selection leaves the
    asserted mapping unconfirmed; a matching human selection confirms EXACTLY
    that assertion (bound to the exact reviewed revision, recorded as
    operational evidence) without changing one candidate byte. The display
    step shows the selection's exact assertion content first, and nothing is
    confirmed by displaying it."""
    project, _api, review = admitted_candidate(tmp_path / "proj")
    selection = "order-number:global-order-concatenation"

    # the display step resolves the selection and shows the exact assertion
    assert admit(project, review, confirm=False, confirm_mapping=[selection]) == 0
    displayed = json.loads(capsys.readouterr().out)
    [shown] = displayed["mapping_selections"]
    assert shown["selection"] == selection
    assert shown["assertion"]["declaration"]["claim"] == "asserted"
    assert shown["assertion"]["assertion_digest"] == confirmation_binding_digest(
        yaml.safe_load(order_reference_page().split("---", 2)[1]),
        shown["assertion"]["declaration"],
    )
    assert "never sign-off" in displayed["confirmation_required"]
    assert not (project / CURRENT).exists()  # displaying confirms nothing

    # the assertion variant with NO selection: admitted, still unconfirmed
    assert admit(project, review) == 0
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["confirmed_mappings"] == []
    assert read_current(project)["confirmed_mappings"] == []
    runtime = QueryRuntime.open_project(project)
    result = asyncio.run(runtime.resolve_term("global order number"))
    mapping = mapping_view(result, "global-order-number", "global-order-concatenation")
    assert mapping["confirmation"] == "unconfirmed"  # no selection happened

    # a new revision of the same proposal: select the assertion and confirm
    api = AuthoringProject(project)
    moved = api.edit_proposal(
        review["proposal"],
        branch_of(project, review["proposal"]),
        {
            "kind": "page",
            "section": "tables",
            "name": "orders",
            "content": table_page().replace(
                "One row per store-scoped order.", "One row per store order; revised."
            ),
        },
    )
    validated = api.validate_proposal(review["proposal"], moved["revision"])
    assert validated["ok"] is True
    second = api.review_proposal(review["proposal"])
    pre_blobs = blobs_of(project, second["revision"])
    assert admit(project, second, confirm_mapping=[selection]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    [recorded] = confirmed["confirmed_mappings"]
    assert recorded["selection"] == selection
    descriptor = read_current(project)
    assert descriptor["commit"] == second["revision"]
    [entry] = descriptor["confirmed_mappings"]
    assert entry["mapping"] == "global-order-concatenation"
    assert entry["claim"] == "asserted"
    page = yaml.safe_load(order_reference_page().split("---", 2)[1])
    [declared] = [
        mapping
        for mapping in page["ariadne"]["mappings"]
        if mapping["id"] == "global-order-concatenation"
    ]
    assert entry["assertion_digest"] == confirmation_binding_digest(page, declared)
    assert entry["by"] and entry["at"]  # the operational human evidence

    # admission changed no candidate byte
    assert branch_of(project, review["proposal"]) == second["revision"]
    assert blobs_of(project, second["revision"]) == pre_blobs

    # resolution now reports EXACTLY that assertion confirmed; the hypothesis
    # on the same page stays unconfirmed
    fresh = QueryRuntime.open_project(project)
    served = asyncio.run(fresh.resolve_term("order number"))
    confirmed_view = mapping_view(served, "local-order-number", "global-order-concatenation")
    assert confirmed_view["confirmation"] == "confirmed"
    hypothesis_view = mapping_view(served, "local-order-number", "local-to-global-prefix")
    assert hypothesis_view["confirmation"] == "unconfirmed"
    assert hypothesis_view["claim"] == "hypothesis"


def test_selections_of_hypotheses_unknown_targets_and_page_flags_never_confirm(tmp_path, capsys):
    """Issue #44 [3]: a hypothesis selection refuses (investigative knowledge
    is never a confirmed assertion); an unknown reference or mapping refuses;
    an author-fabricated ``confirmed`` page flag fails the page contract long
    before any admission; and a --confirm-mapping typo never activates
    anything."""
    project, _api, review = admitted_candidate(tmp_path / "proj")

    for bad in (
        "order-number:local-to-global-prefix",
        "nope:global-order-concatenation",
        "order-number:nope",
        "not-a-selection",
    ):
        assert admit(project, review, confirm_mapping=[bad]) == 1, bad
        error = json.loads(capsys.readouterr().err)
        assert "error" in error, bad
        assert not (project / CURRENT).exists()

    # the hypothesis refusal names the classification rule
    assert admit(project, review, confirm_mapping=["order-number:local-to-global-prefix"]) == 1
    message = json.loads(capsys.readouterr().err)["error"]["message"]
    assert "hypothesis" in message and "asserted" in message

    # an author-fabricated confirmation flag is not authority: the page gate
    # refuses the unsupported field before validation could pass
    api = AuthoringProject(project)
    forged = yaml.safe_load(order_reference_page().split("---")[1])
    forged["ariadne"]["mappings"][1]["confirmed"] = True
    front = yaml.safe_dump(forged, default_flow_style=False, sort_keys=False).strip()
    edited = api.edit_proposal(
        review["proposal"],
        branch_of(project, review["proposal"]),
        {
            **REFERENCE_EDIT,
            "content": f"---\n{front}\n---\n\n# Order number\n",
        },
    )
    result = api.validate_proposal(review["proposal"], edited["revision"])
    assert result["ok"] is False
    assert any("unsupported field" in error for error in result["errors"])
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    assert outcomes["page_contract"] == "failed"


# --------------- [4] honest counterevidence and unsupported/conflicting claims


def prefix_candidate(*, separator: str = "") -> dict:
    """A measurable prefix candidate over the orders asset: the composite
    (store_id, local_order_number) constructing the global identity. The
    empty separator is the true rule; any other separator measures honest
    COUNTEREVIDENCE (mismatches) for the same declaration shape."""
    orders = orders_resource()
    return {
        "family": "prefix",
        "left": [
            {"resource": orders, "column": "store_id"},
            {"resource": orders, "column": "local_order_number"},
        ],
        "right": [{"resource": orders, "column": "global_order_number"}],
        "separator": separator,
        "scope": [],
    }


def receipt_reference_page(
    candidate: dict, receipt_ids: list[str], *, claim: str, mapping_id: str = "measured-mapping"
) -> str:
    """A structured Reference whose single mapping declares the measured
    candidate and cites measured receipts under the given claim — the
    endpoint representations mirror the candidate's measured sides (the K3
    correspondence evidence verification enforces)."""
    meta = {
        "type": "reference",
        "title": "Order number",
        "description": "The store-scoped and global order-number identities.",
        "tags": ["reference", "identifier"],
        "sources": [{"id": "seed-notes", "resource": "data/seed_notes.md", "title": "Seed notes"}],
        "ariadne": {
            "version": 1,
            "reference_role": "identifier",
            "representations": [
                {
                    "id": "local-order-number",
                    "aliases": ["local order number"],
                    "fields": candidate["left"],
                    "scope": [],
                },
                {
                    "id": "global-order-number",
                    "aliases": ["global order number"],
                    "fields": candidate["right"],
                    "scope": [],
                },
            ],
            "mappings": [
                {
                    "id": mapping_id,
                    "family": candidate["family"],
                    "from": "local-order-number",
                    "to": "global-order-number",
                    "claim": claim,
                    "source_ids": ["seed-notes"],
                    "candidate": candidate,
                    "receipt_ids": receipt_ids,
                }
            ],
        },
    }
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n# Order number\n\nThe measured mapping.\n"


def measured_context_only_candidate(
    tmp_path, *, separator="", claim="hypothesis", mapping_id="measured-mapping"
):
    """A context-only proposal whose Reference cites one MEASURED receipt:
    (project, api, {proposal, revision}, measured envelope)."""
    project = context_only_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    candidate = prefix_candidate(separator=separator)
    measured = api.inspect_mapping(started["proposal"], started["candidate_revision"], candidate)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            **REFERENCE_EDIT,
            "content": receipt_reference_page(
                candidate, [measured["receipt_id"]], claim=claim, mapping_id=mapping_id
            ),
        },
    )
    return (
        project,
        api,
        {"proposal": started["proposal"], "revision": edited["revision"]},
        measured,
        candidate,
    )


def test_admitted_hypothesis_keeps_honest_counterevidence_and_stays_unconfirmed(tmp_path):
    """Issue #44 [4]: an admitted investigative hypothesis may carry honest
    COUNTEREVIDENCE — a measured receipt whose mismatches disprove the
    declared construction survives validation, admission and resolution as a
    labeled, unconfirmed lead with its AS-OF measurement visible."""
    # the wrong separator measures mismatches: ABC-123123 != ABC123123
    project, api, candidate, measured, _decl = measured_context_only_candidate(
        tmp_path / "proj", separator="-", claim="hypothesis"
    )
    assert measured["receipt"]["mismatch_count"] > 0  # honest counterevidence

    validated = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert validated["ok"] is True and validated["errors"] == []
    review = api.review_proposal(candidate["proposal"])
    [assertion] = review["mapping_assertions"]
    assert assertion["claim"] == "hypothesis" and assertion["confirmable"] is False
    assert assertion["receipts"][0]["outcome"] == "complete"  # completed, mismatching

    assert admit(project, review) == 0
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("local order number"))
    view = mapping_view(served, "local-order-number", "measured-mapping")
    assert view["claim"] == "hypothesis"
    assert view["confirmation"] == "unconfirmed"  # counterevidence never confirms
    [evidence] = view["evidence"]
    assert evidence["mismatch_count"] > 0  # the honest counterevidence rides along
    assert evidence["observed_at"] and evidence["designation"]  # explicitly as-of


@pytest.mark.parametrize(
    "variant",
    ["unsupported", "conflicting", "fabricated-receipt", "stale-receipt"],
)
def test_unsupported_conflicting_or_fabricated_asserted_claims_refuse(tmp_path, variant, capsys):
    """Issue #44 [4]: asserted claims that are unsupported (no cited domain
    evidence), conflicting (two asserted declarations over the same
    relationship), fabricated (a receipt id that resolves to no core
    evidence) or stale (aged past the operator budget) refuse validation —
    the admission gate never sees them."""
    if variant == "unsupported":
        project = context_only_project(tmp_path)
        api = AuthoringProject(project)
        started = api.start_proposal()
        approved(api, project, started)
        page = order_reference_page()
        forged = yaml.safe_load(page.split("---")[1])
        forged["ariadne"]["mappings"][1]["source_ids"] = []
        front = yaml.safe_dump(forged, default_flow_style=False, sort_keys=False).strip()
        edited = api.edit_proposal(
            started["proposal"],
            started["candidate_revision"],
            {**REFERENCE_EDIT, "content": f"---\n{front}\n---\n\n# Order number\n"},
        )
        result = api.validate_proposal(started["proposal"], edited["revision"])
        assert any("asserted mapping without evidence" in error for error in result["errors"])
        outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
        assert outcomes["page_contract"] == "failed"
        return

    if variant == "conflicting":
        project, api, candidate, _measured, declared = measured_context_only_candidate(
            tmp_path / "proj", claim="asserted"
        )
        page = yaml.safe_load(
            receipt_reference_page(declared, [], claim="asserted").split("---")[1]
        )
        rival = json.loads(json.dumps(declared))  # a DIFFERENT declaration of the
        rival["separator"] = "-"  # same relationship: conflicting asserted claims
        page["ariadne"]["mappings"].append(
            {
                "id": "rival-assertion",
                "family": "prefix",
                "from": "local-order-number",
                "to": "global-order-number",
                "claim": "asserted",
                "source_ids": ["seed-notes"],
                "candidate": rival,
                "receipt_ids": [],
            }
        )
        front = yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()
        edited = api.edit_proposal(
            candidate["proposal"],
            branch_of(project, candidate["proposal"]),
            {**REFERENCE_EDIT, "content": f"---\n{front}\n---\n\n# Order number\n"},
        )
        result = api.validate_proposal(candidate["proposal"], edited["revision"])
        assert any("conflicting asserted claims" in error for error in result["errors"])
        outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
        assert outcomes["mapping_evidence"] == "failed"
        return

    if variant == "fabricated-receipt":
        project = context_only_project(tmp_path)
        api = AuthoringProject(project)
        started = api.start_proposal()
        approved(api, project, started)
        declared = prefix_candidate()
        edited = api.edit_proposal(
            started["proposal"],
            started["candidate_revision"],
            {
                **REFERENCE_EDIT,
                "content": receipt_reference_page(
                    declared, ["mr-0000000000000000"], claim="asserted"
                ),
            },
        )
        result = api.validate_proposal(started["proposal"], edited["revision"])
        assert any("receipt" in error for error in result["errors"])
        outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
        assert outcomes["mapping_evidence"] == "failed"
        return

    # stale receipt: measured, saved, then aged past the 24h operator budget
    project, api, candidate, measured, _decl = measured_context_only_candidate(
        tmp_path / "proj", claim="asserted"
    )
    first = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert first["ok"] is True
    path = Path(measured["evidence"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored.pop("integrity_digest")
    aged = (datetime.now(UTC) - timedelta(hours=25)).isoformat(timespec="seconds")
    stored["observed_at"] = aged
    stored["version_signal"]["observed_at"] = aged
    stored["integrity_digest"] = _canonical_digest(stored)
    path.write_text(json.dumps(stored, sort_keys=True) + "\n", encoding="utf-8")
    notes = api.read_artifact(candidate["proposal"], {"kind": "seed_notes"})
    moved = api.edit_proposal(
        candidate["proposal"],
        first["revision"],
        {"kind": "seed_notes", "content": notes["content"] + "\nAged evidence.\n"},
    )
    result = api.validate_proposal(candidate["proposal"], moved["revision"])
    assert any("age budget" in error for error in result["errors"])
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    capsys.readouterr()


# ------------------------------ [5] confirmation inheritance and freshness


def test_unchanged_assertion_retains_prior_human_evidence_until_it_changes(tmp_path, capsys):
    """Issue #44 [5]: unchanged assertions retain matching prior human
    evidence WITHOUT a new selection (an unrelated page-only admission keeps
    the confirmation); a CHANGED assertion cannot inherit confirmation — it
    lapses until a fresh human selection confirms the new declaration."""
    project, _api, review = admitted_candidate(tmp_path / "proj")
    proposal = review["proposal"]
    selection = "order-number:global-order-concatenation"

    # admit with the selection: the assertion is confirmed
    assert admit(project, review, confirm_mapping=[selection]) == 0
    capsys.readouterr()
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("order number"))
    assert (
        mapping_view(served, "local-order-number", "global-order-concatenation")["confirmation"]
        == "confirmed"
    )

    # an unrelated page-only change: the assertion is byte-identical, so the
    # prior human evidence RETAINS without a new selection
    api = AuthoringProject(project)
    unrelated = api.edit_proposal(
        proposal,
        branch_of(project, proposal),
        {
            **TABLE_EDIT,
            "content": table_page().replace(
                "One row per store-scoped order.", "One row per store order; unrelated edit."
            ),
        },
    )
    validated = api.validate_proposal(proposal, unrelated["revision"])
    assert validated["ok"] is True
    second = api.review_proposal(proposal)
    assert admit(project, second) == 0  # NO selection
    outcome = json.loads(capsys.readouterr().out)
    [retained] = outcome["retained_confirmations"]
    assert retained["selection"] == selection
    assert retained["retained_from"] == review["revision"]
    assert outcome["lapsed_confirmations"] == []
    fresh = QueryRuntime.open_project(project)
    served = asyncio.run(fresh.resolve_term("order number"))
    assert (
        mapping_view(served, "local-order-number", "global-order-concatenation")["confirmation"]
        == "confirmed"
    )

    # a CHANGED assertion (different cited evidence → different digest): the
    # prior confirmation cannot inherit and lapses without a new selection
    changed_page = yaml.safe_load(order_reference_page().split("---")[1])
    changed_page["sources"].append(
        {"id": "orders-catalog", "resource": orders_resource(), "title": "orders catalog"}
    )
    changed_page["ariadne"]["mappings"][1]["source_ids"] = ["orders-catalog"]
    front = yaml.safe_dump(changed_page, default_flow_style=False, sort_keys=False).strip()
    changed = api.edit_proposal(
        proposal,
        branch_of(project, proposal),
        {**REFERENCE_EDIT, "content": f"---\n{front}\n---\n\n# Order number\n"},
    )
    validated = api.validate_proposal(proposal, changed["revision"])
    assert validated["ok"] is True
    third = api.review_proposal(proposal)
    assert admit(project, third) == 0  # still no selection
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["retained_confirmations"] == []
    [lapsed] = outcome["lapsed_confirmations"]
    assert lapsed["mapping"] == "global-order-concatenation"
    assert "changed" in lapsed["reason"]
    lapsed_runtime = QueryRuntime.open_project(project)
    served = asyncio.run(lapsed_runtime.resolve_term("order number"))
    assert (
        mapping_view(served, "local-order-number", "global-order-concatenation")["confirmation"]
        == "unconfirmed"
    )

    # a fresh selection of the CHANGED assertion confirms the new declaration
    fourth = api.review_proposal(proposal)
    assert admit(project, fourth, confirm_mapping=[selection]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    [recorded] = confirmed["confirmed_mappings"]
    assert recorded["selection"] == selection
    reconfirmed = QueryRuntime.open_project(project)
    served = asyncio.run(reconfirmed.resolve_term("order number"))
    assert (
        mapping_view(served, "local-order-number", "global-order-concatenation")["confirmation"]
        == "confirmed"
    )


def test_remeasured_evidence_breaks_inheritance_until_reconfirmed(tmp_path, capsys):
    """Issue #44 [5]: the confirmation binds the assertion's VERIFIED evidence
    dependencies too — a re-measured receipt (new integrity digest) is a
    changed dependency, so an unchanged declaration whose evidence moved on
    cannot inherit the prior confirmation without a fresh selection."""
    project, api, candidate, measured, declared = measured_context_only_candidate(
        tmp_path / "proj", claim="asserted", mapping_id="measured-assertion"
    )
    validated = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert validated["ok"] is True
    first = api.review_proposal(candidate["proposal"])
    selection = "order-number:measured-assertion"
    assert admit(project, first, confirm_mapping=[selection]) == 0
    capsys.readouterr()

    # re-measure the same declaration: a fresh receipt (different observed_at
    # → different integrity digest), cited by an edited page that carries the
    # attached evidence block unchanged until the core re-finalizes it
    fresh = api.inspect_mapping(
        candidate["proposal"], branch_of(project, candidate["proposal"]), declared
    )
    assert fresh["receipt_id"] != measured["receipt_id"]
    page = yaml.safe_load(
        api.read_artifact(candidate["proposal"], REFERENCE_EDIT)["content"].split("---", 2)[1]
    )
    page["ariadne"]["mappings"][0]["receipt_ids"] = [fresh["receipt_id"]]
    front = yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()
    body = api.read_artifact(candidate["proposal"], REFERENCE_EDIT)["content"].split("---", 2)[2]
    edited = api.edit_proposal(
        candidate["proposal"],
        branch_of(project, candidate["proposal"]),
        {**REFERENCE_EDIT, "content": f"---\n{front}\n---{body}"},
    )
    validated = api.validate_proposal(candidate["proposal"], edited["revision"])
    assert validated["ok"] is True
    second = api.review_proposal(candidate["proposal"])
    assert admit(project, second) == 0  # no selection: the dependency changed
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["retained_confirmations"] == []
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("local order number"))
    view = mapping_view(served, "local-order-number", "measured-assertion")
    assert view["claim"] == "asserted"
    assert view["confirmation"] == "unconfirmed"  # stale confirmation cannot inherit

    # the fresh selection re-binds the re-measured evidence
    third = api.review_proposal(candidate["proposal"])
    assert admit(project, third, confirm_mapping=[selection]) == 0
    rebound = QueryRuntime.open_project(project)
    served = asyncio.run(rebound.resolve_term("local order number"))
    assert (
        mapping_view(served, "local-order-number", "measured-assertion")["confirmation"]
        == "confirmed"
    )


# ------------------------------- [7] local adapter parity over one core


def test_local_cli_serves_the_context_only_project(tmp_path, capsys):
    """Issue #44 [7]: the local ``ariadne`` CLI serves the SAME core envelopes
    on a context-only admitted project — resolve-term works over the pinned
    admission while every metric request writes the SPECIFIC missing-catalog
    error object (one JSON value/error, exit codes intact)."""
    project, _api, review = admitted_candidate(tmp_path)
    assert admit(project, review) == 0  # the human admission of the exact revision
    capsys.readouterr()  # the journey prints; clear before the CLI calls

    code = cli(["resolve-term", "order number", "--project", str(project)])
    assert code == 0
    served = json.loads(capsys.readouterr().out)
    assert [match["representation"] for match in served["matches"]] == [
        "local-order-number",
        "global-order-number",
    ]
    assert served["admission"]["revision"] == review["revision"]

    code = cli(["search-context", "order number", "--project", str(project), "--limit", "5"])
    assert code == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits and all(not hit["draft"] for hit in hits)

    for argv in (
        ["list-metrics", "--project", str(project)],
        ["get-metric", "order_number_count", "--project", str(project)],
    ):
        assert cli(argv) == 1, argv
        error = json.loads(capsys.readouterr().err)
        assert MISSING_CATALOG_MARK in error["error"]["message"], argv

    code = cli(["query-metrics", "--project", str(project)], stdin=io.StringIO("{}"))
    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert MISSING_CATALOG_MARK in error["error"]["message"]
    assert error["error"]["code"] == "missing_catalog"


# ------------------ K4 fix pass: the three review findings (issue #44)


def test_asserted_claim_contradicted_by_its_own_cited_receipt_refuses(tmp_path, capsys):
    """K4 fix pass (finding 1): an ASSERTED mapping whose own verified receipt
    shows honest counterevidence — the reproduced separator='-' mismatch in
    the cited receipt — is UNSUPPORTED (spec 0010 §§8–9/AC4): validation fails
    the mapping_evidence check with a named error citing the counterevidence,
    review lists the assertion with confirmable:False and a note naming it,
    and a selection for it refuses. The SAME receipt under a hypothesis claim
    stays valid and admissible as labeled investigative knowledge."""
    # the wrong separator measures mismatches: ABC-123123 != ABC-123123
    project, api, candidate, measured, _decl = measured_context_only_candidate(
        tmp_path / "proj", separator="-", claim="asserted", mapping_id="contradicted"
    )
    assert measured["receipt"]["mismatch_count"] > 0  # honest counterevidence

    result = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert result["ok"] is False
    assert any(
        "counterevidence" in error and "contradicted" in error for error in result["errors"]
    )
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"

    # review: the contradicted assertion is listed NOT confirmable with a
    # note naming the counterevidence (reading is never confirmation, and a
    # selection for a non-confirmable assertion refuses)
    review = api.review_proposal(candidate["proposal"])
    [assertion] = review["mapping_assertions"]
    assert assertion["claim"] == "asserted"
    assert assertion["confirmable"] is False
    assert "counterevidence" in assertion["confirmation_note"]
    assert admit(
        project, review, confirm=False, confirm_mapping=["order-number:contradicted"]
    ) == 1
    message = json.loads(capsys.readouterr().err)["error"]["message"]
    assert "not eligible" in message and "counterevidence" in message

    # the SAME receipt under a hypothesis claim stays valid and admissible —
    # honest counterevidence on investigative knowledge is the kept contract
    hproject, hapi, hcandidate, _hmeasured, _hdecl = measured_context_only_candidate(
        tmp_path / "proj-hypothesis", separator="-", claim="hypothesis"
    )
    hvalidated = hapi.validate_proposal(hcandidate["proposal"], hcandidate["revision"])
    assert hvalidated["ok"] is True and hvalidated["errors"] == []
    hreview = hapi.review_proposal(hcandidate["proposal"])
    [hassertion] = hreview["mapping_assertions"]
    assert hassertion["claim"] == "hypothesis" and hassertion["confirmable"] is False
    assert admit(hproject, hreview) == 0


def test_retargeted_representation_meaning_lapses_prior_confirmation(tmp_path, capsys):
    """K4 fix pass (finding 2): confirmation binds the declaration's EFFECTIVE
    identity — the mapping PLUS its endpoint representations' field/scope
    correspondence. The reproduced receipt-free case: a confirmed mapping
    whose global representation is RETARGETED by a read-modify-write (mapping
    bytes unchanged, no receipts → no correspondence re-check) must LAPSE —
    review binds a different assertion digest, admission without a selection
    reports it lapsed, and the resolver never inherits the prior
    confirmation."""
    project, _api, review = admitted_candidate(tmp_path / "proj")
    selection = "order-number:global-order-concatenation"
    assert admit(project, review, confirm_mapping=[selection]) == 0
    capsys.readouterr()
    [recorded] = read_current(project)["confirmed_mappings"]
    prior_digest = recorded["assertion_digest"]
    [prior_assertion] = [
        entry
        for entry in review["mapping_assertions"]
        if entry["mapping"] == "global-order-concatenation"
    ]

    # read-modify-write: retarget the global representation's field binding
    # (store_id joins the global identity) — the MAPPING bytes stay identical
    api = AuthoringProject(project)
    content = api.read_artifact(review["proposal"], REFERENCE_EDIT)["content"]
    page = yaml.safe_load(content.split("---", 2)[1])
    page["ariadne"]["representations"][1]["fields"].insert(
        0, {"resource": orders_resource(), "column": "store_id"}
    )
    front = yaml.safe_dump(page, default_flow_style=False, sort_keys=False).strip()
    body = content.split("---", 2)[2]
    retargeted = api.edit_proposal(
        review["proposal"],
        branch_of(project, review["proposal"]),
        {**REFERENCE_EDIT, "content": f"---\n{front}\n---{body}"},
    )
    validated = api.validate_proposal(review["proposal"], retargeted["revision"])
    assert validated["ok"] is True  # no receipts cited: nothing re-verifies
    second = api.review_proposal(review["proposal"])
    [assertion] = [
        entry
        for entry in second["mapping_assertions"]
        if entry["mapping"] == "global-order-concatenation"
    ]
    # the MAPPING bytes are identical; only the endpoint representation moved
    assert assertion["declaration"] == prior_assertion["declaration"]
    assert assertion["assertion_digest"] != prior_digest  # effective identity moved

    assert admit(project, second) == 0  # NO selection: it must not inherit
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["retained_confirmations"] == []
    [lapsed] = outcome["lapsed_confirmations"]
    assert lapsed["mapping"] == "global-order-concatenation"
    assert read_current(project)["confirmed_mappings"] == []
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("order number"))
    assert (
        mapping_view(served, "local-order-number", "global-order-concatenation")[
            "confirmation"
        ]
        == "unconfirmed"
    )


def aged_context_clock(monkeypatch, hours: float):
    """K4 fix pass (finding 3): freeze the shared evidence-freshness clock
    `hours` ahead — every ``datetime.now(UTC)`` inside :mod:`ariadne.context`
    (the freshness state the resolver AND the admission retention check read)
    runs ahead of the wall clock, so recorded ``observed_at`` values stay put
    and age past the operator budget without one query-time write."""
    real = datetime

    class _Aged(real):
        @classmethod
        def now(cls, tz=None):
            moment = real.now(UTC) + timedelta(hours=hours)
            return moment if tz is UTC else real.now(tz)

    monkeypatch.setattr(context_module, "datetime", _Aged)
    return _Aged


def snapshot_bytes(project: Path, commit: str) -> dict[str, bytes]:
    """The pinned snapshot's exact bytes (write-detection for the read-only
    resolver: resolving a stale confirmation writes nothing)."""
    root = project / SNAPSHOTS / commit
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_expired_evidence_never_serves_as_current_confirmed_guidance(tmp_path, capsys, monkeypatch):
    """K4 fix pass (finding 3): a confirmed mapping whose verified evidence
    aged past the operator budget (the same inspection.receipt_max_age_hours
    config) never serves as CURRENT confirmed guidance — the resolver exposes
    the explicit freshness state and surfaces the confirmation as
    needs-revalidation with the human confirmation disclosed as history.
    Within the budget, as_of evidence + confirmed guidance stand."""
    project, api, candidate, measured, _decl = measured_context_only_candidate(
        tmp_path / "proj", claim="asserted", mapping_id="measured-assertion"
    )
    validated = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert validated["ok"] is True
    review = api.review_proposal(candidate["proposal"])
    assert admit(project, review, confirm_mapping=["order-number:measured-assertion"]) == 0
    capsys.readouterr()
    commit = read_current(project)["commit"]

    # within the budget: explicit as_of evidence, confirmed guidance stands
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("local order number"))
    view = mapping_view(served, "local-order-number", "measured-assertion")
    assert view["confirmation"] == "confirmed"
    assert [item["freshness"]["state"] for item in view["evidence"]] == ["as_of"]
    assert view["evidence_freshness"]["state"] == "as_of"
    assert "confirmation_history" not in view  # nothing withheld while current

    # clock-advance past the 24h budget: the SAME admitted bytes stay pinned,
    # but expired evidence is never silently current confirmed guidance
    before = snapshot_bytes(project, commit)
    aged_context_clock(monkeypatch, 26)
    aged = QueryRuntime.open_project(project)
    stale = asyncio.run(aged.resolve_term("local order number"))
    view = mapping_view(stale, "local-order-number", "measured-assertion")
    assert view["confirmation"] == "needs-revalidation"  # withheld, not current
    [history] = view["confirmation_history"]
    assert history["by"] and history["at"]  # the human confirmation as history
    [item] = view["evidence"]
    assert item["freshness"]["state"] == "stale"
    assert item["freshness"]["max_age_hours"] == 24.0  # the operator budget
    assert view["evidence_freshness"]["state"] == "stale"
    # resolving wrote nothing (no query-time write anywhere)
    assert snapshot_bytes(project, commit) == before
    assert read_current(project)["confirmed_mappings"]  # descriptor unchanged


def test_expired_prior_evidence_cannot_retain_confirmation_at_admission(
    tmp_path, capsys, monkeypatch
):
    """K4 fix pass (finding 3): a confirmation cannot be RETAINED when the
    prior evidence is past expiry at the new admission — an already-stored
    validation of a later candidate (validated while the evidence was fresh)
    keeps no stale confirmation alive; it lapses with the expiry named."""
    project, api, candidate, measured, _decl = measured_context_only_candidate(
        tmp_path / "proj", claim="asserted", mapping_id="measured-assertion"
    )
    first = api.validate_proposal(candidate["proposal"], candidate["revision"])
    assert first["ok"] is True
    review = api.review_proposal(candidate["proposal"])
    assert admit(project, review, confirm_mapping=["order-number:measured-assertion"]) == 0
    capsys.readouterr()

    # a later candidate of the same proposal, validated while fresh: the
    # stored evidence returns idempotently, so the expiry can only be caught
    # at the retention decision of the new admission
    moved = api.edit_proposal(
        review["proposal"],
        branch_of(project, review["proposal"]),
        {
            **TABLE_EDIT,
            "content": table_page().replace(
                "One row per store-scoped order.", "One row per store order; later."
            ),
        },
    )
    validated = api.validate_proposal(review["proposal"], moved["revision"])
    assert validated["ok"] is True

    aged_context_clock(monkeypatch, 26)  # past the budget BEFORE admitting
    second = api.review_proposal(review["proposal"])
    assert admit(project, second) == 0  # NO selection: nothing may retain
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["retained_confirmations"] == []
    [lapsed] = outcome["lapsed_confirmations"]
    assert lapsed["mapping"] == "measured-assertion"
    assert "budget" in lapsed["reason"]
    assert read_current(project)["confirmed_mappings"] == []
    runtime = QueryRuntime.open_project(project)
    served = asyncio.run(runtime.resolve_term("local order number"))
    assert (
        mapping_view(served, "local-order-number", "measured-assertion")["confirmation"]
        == "unconfirmed"
    )
