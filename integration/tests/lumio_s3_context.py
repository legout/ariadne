"""#79 Core S3 admission and pinned session (spec0029 r6, plan0029 r29).

One coherent journey over the parent-owned labelled synthetic SeaweedFS
service: a declared Knowledge-only S3 Storage Profile is explicitly selected
on the existing human overall-admission surface, the release is published
natively to S3 with its private local admission records, activated last as
the Core descriptor, and served source-free through the public CLI and MCP
navigation. The independent numeric oracle is the shared authored fixture:
completed orders 100 + 50 and cancelled 25 imply revenue 150 and completed
count 2. Expected identities, passages and byte equality are authored here
or come from the golden fixture/git — never from implementation output.

Missing service prerequisites FAIL this module (no skip/importorskip): it
runs only under the approved disposable synthetic service overlay.
"""

import asyncio
import inspect
import json
import os
import shutil
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — qualified test env is external
from ariadne import admission, lumio_context  # pyright: ignore[reportAttributeAccessIssue]
from ariadne.admission import main as admission_main
from ariadne.authoring import AuthoringProject
from ariadne.cli import main as cli
from ariadne.query import QueryRuntime
from ariadne.sources import canonical_endpoint
from lumio_wiki.ariadne_context import UnadmittedInputError
from lumio_wiki.git_authoring import GitAuthoringError
from tests.test_contracts import ORDERS_BINDINGS, ORDERS_CONTRACT, contracted
from tests.test_discovery import _source_free_guards
from tests.test_git_authoring import approved, run_git, worktree_of

from integration.tests.lumio_local_context import (
    COMPLETED_METRIC,
    GRAPH,
    KB_COMPLETED,
    OKF_COMPLETED,
)
from integration.tests.lumio_metric_mvp import (
    BASELINE,
    CANCELLATION,
    NAMESPACE,
    activate,
    content_project,
    page_parts,
    reconcile_knowledge,
    write_page,
)

# Parent-provided synthetic service fixture INPUTS: the runner (or CI)
# scrubs inherited AWS_/LUMIO_ values and overlays the labelled synthetic
# bindings. This tracked test never bakes a machine-run endpoint or port:
# it accepts only a labelled loopback http endpoint with the allow_http
# test flag set, derives the expected canonical binding endpoint from that
# input through the native canonicalization, and takes the bucket from the
# labelled fixture input. The Knowledge profile grants no analytical
# source access; real service setup remains parent-owned.
REQUIRED_SYNTHETIC = (
    "LUMIO_S3_ENDPOINT",
    "LUMIO_S3_TEST_BUCKET",
    "LUMIO_S3_ACCESS_KEY_ID",
    "LUMIO_S3_SECRET_ACCESS_KEY",
    "LUMIO_S3_REGION",
    "LUMIO_S3_ALLOW_HTTP",
)

# The credential-free Knowledge Storage Profile declared in Git (project
# ariadne.yaml). Only environment-variable NAMES live here; the scopes
# contain BOTH complete publication prefixes this journey uses (the main
# Knowledge destination and the controlled-failure destination).
PROFILE_NAME = "knowledge_store"
MAIN_PREFIX = "ariadne-s3/knowledge"
FAULT_PREFIX = "ariadne-s3/fault"


def _bucket() -> str:
    bucket = os.environ["LUMIO_S3_TEST_BUCKET"].strip()
    assert bucket, "the labelled synthetic bucket fixture input is required"
    return bucket


def _destination() -> str:
    return f"s3://{_bucket()}/{MAIN_PREFIX}"


def _fault_destination() -> str:
    return f"s3://{_bucket()}/{FAULT_PREFIX}"


def _declared_scopes() -> list[str]:
    return [f"{_destination()}/", f"{_fault_destination()}/"]


def _storages_block() -> str:
    return (
        "storages:\n"
        f"  {PROFILE_NAME}:\n"
        "    type: s3\n"
        "    access_key_id_env: LUMIO_S3_ACCESS_KEY_ID\n"
        "    secret_access_key_env: LUMIO_S3_SECRET_ACCESS_KEY\n"
        "    endpoint_url_env: LUMIO_S3_ENDPOINT\n"
        "    region_env: LUMIO_S3_REGION\n"
        "    url_style: path\n"
        "    scopes:\n" + "".join(f"      - {scope}\n" for scope in _declared_scopes())
    )


# Hand-authored ordinary visible page (independent version oracle). The
# unique token 'kestrel' occurs exactly twice, on hand-counted canonical
# body lines 21-22 (frontmatter lines 1-15, closing delimiter line 15, body
# from line 17); no other visible page carries it in any searched field.
JOURNEY_PATH = "references/ordering-notes.md"
KESTREL_LINE_21 = "The morning ordering window is internally called the kestrel window. Only"
JOURNEY_MD = (
    "---\n"
    'id: "entity:ordering-notes"\n'
    'title: "Ordering Notes"\n'
    "entity_types:\n"
    "  - reference\n"
    "tags:\n"
    "  - retail\n"
    "  - operations\n"
    'summary: "Authored ordering vocabulary for the bound S3 release journey."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "src-ordering-notes"\n'
    '    title: "Ordering notes, 2026-10-21"\n'
    "---\n"
    "\n"
    "# Ordering Notes\n"
    "\n"
    "## Ordering vocabulary\n"
    "\n"
    "The morning ordering window is internally called the kestrel window. Only\n"
    "the visible kestrel note in this page is published ordering context.\n"
)
# The operator's B amendment: one authored appendix paragraph carrying a
# third kestrel occurrence; A/B page bytes differ by exactly this text.
JOURNEY_B_APPENDIX = (
    "\n## Later ordering window\n\nThe kestrel window closes during the equinox handover.\n"
)

# Visible pages of this release, SDK-sorted by exact relative path.
VISIBLE_PATHS = [
    "metrics/completed-orders.md",
    "metrics/retail-revenue.md",
    "policies/cancelled-orders.md",
    "policies/retail-return-policy.md",
    "references/order-number.md",
    "references/ordering-notes.md",
]


@pytest.fixture(autouse=True)
def synthetic_s3_environment(tmp_path, monkeypatch):
    """Isolated host state with ONLY the labelled synthetic bindings kept.

    The parent runner scrubs inherited AWS_/LUMIO_ values and overlays the
    labelled synthetic-service bindings; this fixture keeps exactly those
    six and fails loudly when they are absent — never skip or fallback.
    """
    missing = [name for name in REQUIRED_SYNTHETIC if not os.environ.get(name, "").strip()]
    assert not missing, (
        "the S3-bound release journey requires the parent-owned labelled "
        f"synthetic SeaweedFS bindings; missing {missing} — "
        "this test fails instead of skipping"
    )
    from urllib.parse import urlsplit

    parts = urlsplit(os.environ["LUMIO_S3_ENDPOINT"])
    assert parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1"), (
        "the synthetic journey accepts only a labelled loopback http endpoint, "
        f"got {os.environ['LUMIO_S3_ENDPOINT']!r}"
    )
    assert os.environ["LUMIO_S3_ALLOW_HTTP"] == "1"
    assert os.environ["LUMIO_S3_TEST_BUCKET"].strip()
    # Each invocation owns fresh publication prefixes; failed native publication
    # residue stays intact and cannot affect a later expected-current=none oracle.
    monkeypatch.setitem(globals(), "MAIN_PREFIX", f"ariadne-s3/{tmp_path.parent.name}/knowledge")
    monkeypatch.setitem(globals(), "FAULT_PREFIX", f"ariadne-s3/{tmp_path.parent.name}/fault")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".state"))  # private metadata root
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for name in list(os.environ):
        if name.startswith(("LUMIO_", "AWS_")) and name not in REQUIRED_SYNTHETIC:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def _s3_store():
    import obstore  # pyright: ignore[reportMissingImports] — qualified env only

    config = {
        "aws_region": os.environ["LUMIO_S3_REGION"],
        "aws_endpoint": os.environ["LUMIO_S3_ENDPOINT"],
        "aws_access_key_id": os.environ["LUMIO_S3_ACCESS_KEY_ID"],
        "aws_secret_access_key": os.environ["LUMIO_S3_SECRET_ACCESS_KEY"],
    }
    client_options = {"allow_http": os.environ["LUMIO_S3_ENDPOINT"].startswith("http://")}
    return obstore.store.from_url(f"s3://{_bucket()}", config=config, client_options=client_options)


def _s3_preview(project, review, expected_current, destination=None):
    # Approved future surface (plan0029 r29): the existing human overall
    # admission gains an explicit storage-profile selection alongside the
    # s3:// destination; no second admission command or schema.
    return admission.overall_review(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        destination=_destination() if destination is None else destination,
        expected_current=expected_current,
        scope=("public",),
        storage_profile=PROFILE_NAME,
    )


def _no_secret_material(dumped: str) -> None:
    for name in ("LUMIO_S3_ACCESS_KEY_ID", "LUMIO_S3_SECRET_ACCESS_KEY"):
        assert f'"{os.environ[name]}"' not in dumped, name


def _bound_release(root: Path):
    """The shared two-metric candidate fixture plus the declared Knowledge
    S3 Storage Profile and the authored journey page (one validation round
    inside ``ready``-equivalent native validation; no extra loops)."""
    project = content_project(root)
    (project / "ariadne.yaml").write_text(
        (project / "ariadne.yaml").read_text() + _storages_block()
    )
    model = project / "semantic_layer" / "models" / "retail_sales.yml"
    model.write_text(model.read_text() + COMPLETED_METRIC)
    (project / "semantic_layer" / "graph.yml").write_text(GRAPH)
    (project / "context_layer" / "metrics" / "completed_orders.md").write_text(OKF_COMPLETED)
    (project / "knowledge" / "metrics" / "completed-orders.md").write_text(KB_COMPLETED)
    (project / "knowledge" / JOURNEY_PATH).write_text(JOURNEY_MD)
    run_git(
        project,
        "add",
        "--",
        "ariadne.yaml",
        "semantic_layer/graph.yml",
        "semantic_layer/models/retail_sales.yml",
        "context_layer/metrics/completed_orders.md",
        "knowledge",
    )
    run_git(project, "commit", "-q", "-m", "human: declare Knowledge S3 profile, second metric")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = contracted(
        api,
        started,
        contract=ORDERS_CONTRACT.replace("region", "status").replace("mustBe: 60", "mustBe: 175"),
        bindings=ORDERS_BINDINGS.replace("region", "status").replace(
            "model: orders", "model: retail_sales"
        ),
    )
    tree = worktree_of(project, started["proposal"])
    reference = tree / "knowledge/references/order-number.md"
    meta, body = page_parts(reference)
    del meta["ariadne_profile"]  # visible Git candidate edit, never an input conversion
    write_page(reference, meta, body)
    (tree / "knowledge/policies/cancelled-orders.md").write_text(CANCELLATION)
    for name in ("retail-revenue", "completed-orders"):
        page = tree / "knowledge/metrics" / f"{name}.md"
        meta, body = page_parts(page)
        meta["ariadne_profile"]["required_policies"].append(
            {"namespace": NAMESPACE, "entity_id": "entity:cancelled-orders"}
        )
        write_page(page, meta, body)
    revision = reconcile_knowledge(project, started["proposal"], revision)
    return project, api, started, revision


def _typed_list(result):
    # Installed-SDK contract: a list return emits ONE JSON-object text block
    # PER ITEM, the typed structured output wraps it as {"result": [...]}.
    assert not getattr(result, "is_error", False)
    assert result.structured_content.keys() == {"result"}
    wrapped = result.structured_content["result"]
    assert isinstance(wrapped, list)
    blocks = list(getattr(result, "content", ()))
    assert blocks and all(block.type == "text" for block in blocks)
    assert [json.loads(block.text) for block in blocks] == wrapped
    return wrapped


def _typed_dict(result):
    # A plain dict return is exactly one JSON text block, no structured wrapper.
    assert not getattr(result, "is_error", False)
    assert result.structured_content is None
    blocks = list(getattr(result, "content", ()))
    assert len(blocks) == 1 and blocks[0].type == "text"
    return json.loads(blocks[0].text)


def test_s3_bound_release_preserves_admission_and_session_pin(tmp_path, monkeypatch, capsys):
    """The approved #79 observables in one journey: explicit profile-bound S3
    admission activating the Core descriptor last, source-free pinned
    navigation over the public CLI/MCP, A-pinning across B publication and
    admission, controlled-failure residue with a byte-identical descriptor,
    and endpoint/private-admission refusals before SQL."""
    from ariadne import serve
    from ariadne.discovery import DiscoveryRuntime
    from lumio_wiki import ariadne_context as sdk_navigation

    # --- The frozen SDK pair really carries the approved navigation keyword
    # (r4); an older local-only SDK generation must refuse S3 admission via
    # the capability seam instead of being advertised S3-capable.
    for function in (
        sdk_navigation.list_published_context_pages,
        sdk_navigation.read_published_context_page,
        sdk_navigation.search_published_context_pages,
    ):
        parameter = inspect.signature(function).parameters.get("metadata_store")
        assert parameter is not None and parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def _legacy_list(location, expected):
        raise AssertionError("legacy SDK twin must never serve")

    def _legacy_read(location, expected, path):
        raise AssertionError("legacy SDK twin must never serve")

    def _legacy_search(location, expected, query, *, limit=10):
        raise AssertionError("legacy SDK twin must never serve")

    project, api, started, revision = _bound_release(tmp_path)
    # Authored candidate INPUT oracle: _bound_release removes the reference
    # page's ariadne_profile through a visible Git edit, so the candidate's
    # committed bytes — captured here, before any publication — are the
    # expected served content (the untouched golden fixture differs).
    golden_edited = (
        worktree_of(project, started["proposal"]) / "knowledge/references/order-number.md"
    ).read_text()
    checked = api.validate_proposal(started["proposal"], revision)  # native round 1 of 3
    assert checked["ok"] is True, checked["errors"]
    review = api.review_proposal(started["proposal"])
    a_rev = review["revision"]
    with monkeypatch.context() as legacy:
        legacy.setattr(sdk_navigation, "list_published_context_pages", _legacy_list)
        legacy.setattr(sdk_navigation, "read_published_context_page", _legacy_read)
        legacy.setattr(sdk_navigation, "search_published_context_pages", _legacy_search)
        # Expected refusal per approved plan r29: the documented Core
        # preview ValueError family (unsupported admission input); the
        # never-called twins plus this refusal are the oracle.
        with pytest.raises(ValueError):
            _s3_preview(project, review, "none")

    # --- Composite consent freezes the credential-free S3 target identity.
    composite_a = _s3_preview(project, review, "none")
    manifest_a = composite_a["manifest"]
    assert manifest_a["destination"] == _destination()
    assert manifest_a["storage_profile"] == PROFILE_NAME
    binding = manifest_a["storage_binding"]
    # Expected endpoint derived from the labelled fixture INPUT through the
    # native canonicalization (localhost vs 127.0.0.1 stays as supplied).
    expected_endpoint, _hostport, _use_ssl = canonical_endpoint(
        os.environ["LUMIO_S3_ENDPOINT"], PROFILE_NAME
    )
    assert binding["endpoint"] == expected_endpoint
    assert binding["region"] == os.environ["LUMIO_S3_REGION"]
    assert binding["url_style"] == "path"
    # Scopes are semantically order-insensitive: exact multiset equality.
    assert sorted(binding["scopes"]) == sorted(_declared_scopes())
    assert manifest_a["knowledge"]["published_version"] == a_rev
    _no_secret_material(json.dumps(composite_a))
    assert not (project / ".ariadne" / "current.json").exists()

    # --- The existing human CLI surface carries the explicit selection.
    assert (
        admission_main(
            [
                "--project",
                str(project),
                "--proposal",
                review["proposal"],
                "--revision",
                a_rev,
                "--reviewed-digest",
                review["review_digest"],
                "--context-destination",
                _destination(),
                "--context-storage-profile",
                PROFILE_NAME,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["digest"] == composite_a["digest"]

    # --- Real native S3 publication, private receipt verification, then the
    # Core descriptor LAST.
    activate(project, review, composite_a)
    descriptor_a = (project / ".ariadne" / "current.json").read_bytes()
    record = json.loads(descriptor_a)
    assert record["native_publication"]["activated"] is True
    assert record["native_publication"]["destination"] == _destination()
    assert record["bound_release"] == manifest_a
    _no_secret_material(descriptor_a.decode())

    import obstore
    from lumio_wiki.s3_publish import observe_current_pointer

    store = _s3_store()
    assert observe_current_pointer(store, MAIN_PREFIX).version == a_rev
    # Private native admission records live in the LOCAL state store keyed by
    # the effective destination — never as public Knowledge objects.
    private_root = Path(os.environ["XDG_STATE_HOME"]) / "lumio-wiki" / "publications"
    assert private_root.is_dir()
    public_objects = [
        obj["path"] for batch in obstore.list(store, prefix=MAIN_PREFIX) for obj in batch
    ]
    assert public_objects and not any(
        "receipt" in path or "binding" in path for path in public_objects
    ), "private receipts must never ride the public Knowledge prefix"

    # --- Governed SQL over the local synthetic source with S3-served context:
    # the independent 100+50 completed / 25 cancelled => 150 / 2 oracle.
    runtime = QueryRuntime.open_project(project)
    result = asyncio.run(runtime.query_metrics({"metrics": ["revenue", "completed_orders"]}))
    assert result["rows"] == [{"revenue": 150.0, "completed_orders": 2}]
    assert result["governed"] is True
    assert result["admission"]["revision"] == a_rev
    revenue_context = result["context"]["revenue"]
    completed_context = result["context"]["completed_orders"]
    for context in (revenue_context, completed_context):
        assert CANCELLATION in context["policies"]
        assert all(c["published_version"] == a_rev for c in context["citations"])
    # Q2 authored fixture: only the revenue binding requires the golden
    # return policy; completed-orders declares Cancelled Orders alone.
    baseline_policy = (BASELINE / "policies/retail-return-policy.md").read_text()
    assert baseline_policy in revenue_context["policies"]
    assert baseline_policy not in completed_context["policies"]
    assert {c["entity_id"] for c in revenue_context["citations"]} == {
        "entity:retail-revenue",
        "entity:retail-return-policy",
        "entity:cancelled-orders",
    }
    assert {c["entity_id"] for c in completed_context["citations"]} == {
        "entity:completed-orders",
        "entity:cancelled-orders",
    }
    # The Knowledge profile granted no analytical source access.
    datasets = asyncio.run(runtime.list_datasets())
    assert {dataset["source"] for dataset in datasets} == {"orders"}

    # --- Source-free pinned navigation through the public CLI and MCP.
    session_a = DiscoveryRuntime.open_project(project)

    async def _call(app, tool, payload):
        return await app.call_tool(tool, payload)

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        app = serve.build_app(QueryRuntime, project=str(project))
        listed = _typed_list(asyncio.run(_call(app, "list_context_pages", {})))
        assert [entry["path"] for entry in listed] == VISIBLE_PATHS
        assert all(not hasattr(entry, "content") and "content" not in entry for entry in listed)
        journey_page = _typed_dict(
            asyncio.run(_call(app, "read_context_page", {"path": JOURNEY_PATH}))
        )
        assert journey_page["content"] == JOURNEY_MD
        assert journey_page["published_version"] == a_rev
        assert journey_page["bound_release"] == manifest_a["digest"]
        golden_page = _typed_dict(
            asyncio.run(_call(app, "read_context_page", {"path": "references/order-number.md"}))
        )
        assert golden_page["content"] == golden_edited
        hits = _typed_list(asyncio.run(_call(app, "search_context", {"query": "kestrel"})))
        assert len(hits) == 1
        (hit,) = hits
        assert hit["path"] == JOURNEY_PATH  # approved A2 §1.3 flat hit shape
        assert hit["excerpt"] == KESTREL_LINE_21  # hand-counted canonical line 21
        assert (hit["line_start"], hit["line_end"]) == (21, 21)
        assert hit["section"] == "Ordering vocabulary"
        assert hit["matched_fields"] == ["body"] and hit["matched_terms"] == ["kestrel"]
        assert hit["candidates_seen"] == 1 and hit["results_dropped"] == 0
        report = _typed_dict(asyncio.run(_call(app, "discover", {"query": "kestrel"})))
        assert report["bound_release"] == manifest_a["digest"]
        assert report["groups"]["pages"]["items"] == hits
        assert {
            "search_context",
            "list_context_pages",
            "read_context_page",
        } <= set(report["support"]["operations"])
        assert cli(["search-context", "kestrel", "--project", str(project)]) == 0
        assert json.loads(capsys.readouterr().out) == hits

    # --- B: publication plus complete Core admission; A stays pinned.
    tree = worktree_of(project, review["proposal"])
    (tree / "knowledge" / JOURNEY_PATH).write_text(JOURNEY_MD + JOURNEY_B_APPENDIX)
    candidate_b = reconcile_knowledge(project, review["proposal"], a_rev)
    checked_b = api.validate_proposal(review["proposal"], candidate_b)  # native round 2 of 3
    assert checked_b["ok"] is True, checked_b["errors"]
    b_rev = checked_b["revision"]  # native finalization owns the final commit
    review_b = api.review_proposal(review["proposal"])
    assert review_b["revision"] == b_rev
    composite_b = _s3_preview(project, review_b, a_rev)
    manifest_b = composite_b["manifest"]
    assert manifest_b["knowledge"]["published_version"] == b_rev
    activate(project, review_b, composite_b)
    descriptor_b = (project / ".ariadne" / "current.json").read_bytes()
    assert descriptor_b != descriptor_a
    assert observe_current_pointer(store, MAIN_PREFIX).version == b_rev
    # The immutable v1 public object keeps the authored A bytes.
    v1_object = obstore.get(store, f"{MAIN_PREFIX}/{a_rev}/references/ordering-notes.md").bytes()
    assert v1_object == JOURNEY_MD.encode()

    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        still_a = asyncio.run(session_a.read_context_page(JOURNEY_PATH))
        assert still_a["content"] == JOURNEY_MD  # session A keeps its pinned release
        assert still_a["bound_release"] == manifest_a["digest"]
        session_b = DiscoveryRuntime.open_project(project)
        served_b = asyncio.run(session_b.read_context_page(JOURNEY_PATH))
        assert served_b["content"] == JOURNEY_MD + JOURNEY_B_APPENDIX
        assert served_b["bound_release"] == manifest_b["digest"]

    try:
        again = asyncio.run(runtime.query_metrics({"metrics": ["revenue", "completed_orders"]}))
        assert again["rows"] == [{"revenue": 150.0, "completed_orders": 2}]
        assert all(
            c["published_version"] == a_rev
            for metric in ("revenue", "completed_orders")
            for c in again["context"][metric]["citations"]
        ), "the already-open governed runtime stays pinned to A"
        runtime_b = QueryRuntime.open_project(project)
        fresh = asyncio.run(runtime_b.query_metrics({"metrics": ["revenue"]}))
        assert fresh["rows"] == [{"revenue": 150.0}]
        assert all(
            c["published_version"] == b_rev for c in fresh["context"]["revenue"]["citations"]
        )
        runtime_b.con.close()
    finally:
        runtime.con.close()

    # --- Stale/mismatched state cannot activate: the A-era composite and a
    # wrong expected-current preview refuse; the B descriptor is untouched.
    with pytest.raises(ValueError):
        activate(project, review_b, composite_a)
    assert (project / ".ariadne" / "current.json").read_bytes() == descriptor_b
    # Activation changes baseline-dependent review facts for the same revision.
    # Refresh before both the wrong-current check and the later fault preview.
    review_b = api.review_proposal(review["proposal"])
    assert review_b["revision"] == b_rev
    # Blocked expected state: the finite documented family is Core's
    # preview ValueError or the direct native GitAuthoringError guard; the
    # refused operation and the byte-identical descriptor are the oracle.
    with pytest.raises((ValueError, GitAuthoringError)):
        _s3_preview(project, review_b, "none")
    assert (project / ".ariadne" / "current.json").read_bytes() == descriptor_b

    # --- One controlled required-write/persistence failure at the Core
    # descriptor leaf: the native S3 publication REALLY completes (residue is
    # observed, not mocked) while the previous descriptor stays byte-identical.
    composite_fault = _s3_preview(project, review_b, "none", destination=_fault_destination())
    assert composite_fault["manifest"]["destination"] == _fault_destination()

    def _descriptor_persistence_fault(*args, **kwargs):
        raise OSError("assigned Core-descriptor persistence fault")

    with monkeypatch.context() as faulted:
        faulted.setattr(admission, "_publish_current", _descriptor_persistence_fault)
        with pytest.raises(lumio_context.OverallAdmissionError) as caught:
            activate(project, review_b, composite_fault)
    outcome = caught.value.outcome
    assert outcome["integrated_activated"] is False
    assert outcome["publication_receipt"]["activated"] is True
    assert outcome["publication_receipt"]["version"] == b_rev
    assert (
        outcome["publication_receipt"]["manifest_digest"]
        == composite_fault["manifest"]["knowledge"]["source_reference_digest"]
    )
    assert observe_current_pointer(store, FAULT_PREFIX).version == b_rev  # real native residue
    assert (project / ".ariadne" / "current.json").read_bytes() == descriptor_b
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        recovered = DiscoveryRuntime.open_project(project)
        assert (
            asyncio.run(recovered.read_context_page(JOURNEY_PATH))["bound_release"]
            == (manifest_b["digest"])
        ), "serving still follows the intact B descriptor"

    # --- Endpoint drift refuses on a fresh session before any SQL or socket:
    # the documented Core ValueError family for a frozen-binding mismatch.
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        with monkeypatch.context() as drifted:
            drifted.setenv("LUMIO_S3_ENDPOINT", "http://127.0.0.1:1")
            with pytest.raises(ValueError):
                DiscoveryRuntime.open_project(project)

    # --- Unavailable private admission refuses (public objects alone never
    # satisfy admission); restoring the local private records serves again.
    publications = Path(os.environ["XDG_STATE_HOME"]) / "lumio-wiki" / "publications"
    rescued = tmp_path / "rescued-private-records"
    shutil.move(publications, rescued)
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        # The unchanged shared verifier's documented refusal type for
        # missing/foreign private native admission records.
        with pytest.raises(UnadmittedInputError):
            DiscoveryRuntime.open_project(project)
    shutil.move(rescued, publications)
    with monkeypatch.context() as guarded:
        _source_free_guards(guarded)
        final = DiscoveryRuntime.open_project(project)
        served_final = asyncio.run(final.read_context_page(JOURNEY_PATH))
        assert served_final["bound_release"] == manifest_b["digest"]
        assert served_final["content"] == JOURNEY_MD + JOURNEY_B_APPENDIX
    assert (project / ".ariadne" / "current.json").read_bytes() == descriptor_b


def test_s3_destination_refusal_never_echoes_inline_credentials(tmp_path, capsys):
    """spec0029 r6: accidental inline credentials never enter CLI diagnostics."""
    project, api, started, revision = _bound_release(tmp_path)
    checked = api.validate_proposal(started["proposal"], revision)
    assert checked["ok"] is True, checked["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == checked["revision"]
    # Authored synthetic input markers, not observed product output or real credentials.
    inline_user = "synthetic-inline-access"
    inline_secret = "synthetic-inline-secret-never-print"
    rejected = _destination().replace("s3://", f"s3://{inline_user}:{inline_secret}@", 1)
    capsys.readouterr()
    assert admission_main(
        [
            "--project", str(project),
            "--proposal", review["proposal"],
            "--revision", review["revision"],
            "--reviewed-digest", review["review_digest"],
            "--context-destination", rejected,
            "--context-storage-profile", PROFILE_NAME,
        ]
    ) == 1
    diagnostic = capsys.readouterr()
    assert diagnostic.out == ""
    assert json.loads(diagnostic.err)["error"]["type"] == "ValueError"
    assert inline_secret not in diagnostic.err
    assert inline_user not in diagnostic.err
    assert rejected not in diagnostic.err
    assert not (project / ".ariadne" / "current.json").exists()
