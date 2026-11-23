"""Git-backed Answer Example input, provenance and size boundaries (spec 0027)."""

import json
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))


from tests.test_cli import create_git_demo_project, error_payload  # noqa: E402
from tests.test_git_authoring import run_git, worktree_of  # noqa: E402


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return create_git_demo_project(tmp_path_factory.mktemp("answer-examples") / "project")


from tests.mcp_inproc import run as _tool  # noqa: E402


def mcp_save(root, submission):
    return _tool(root, "save_example", {"submission": submission})


def mcp_search(root, query, *, include_sql=False, include_history=False):
    return _tool(
        root,
        "search_examples",
        {"query": query, "include_sql": include_sql, "include_history": include_history},
    )


def _submission(result, /, **overrides):
    result = overrides.pop("result", result)  # parametrized whole-result overrides
    submission = {
        "question": "What is the gross margin ratio by region?",
        "interpretation": "Margin as ratio of sums over billable orders.",
        "parameters": {"dimensions": ["region"], "grain": "one row per region"},
        "method": {
            "operation": "get_metric",
            "arguments": {"name": "gross_margin", "dimensions": ["region"]},
        },
        "result": result,
        "submitter": "expert:dana",
        "attestation": "I confirmed this against the observed result.",
        "sources": [
            "metrics/gross_margin.md",
            "policies/order-status-billing.md",
            "policies/emea-currency-cutover.md",
        ],
    }
    submission.update(overrides)
    return submission


_SMALL_RESULT = {
    "metric": "gross_margin",
    "columns": ["region", "gross_margin"],
    "rows": [{"region": "EMEA", "gross_margin": 0.25}],
    "sql": "SELECT region, SUM(amount) FROM demo.main.orders GROUP BY region",
    "governed": True,
}
_EXACT_SQL = " \nSELECT region, COUNT(*) AS n\nFROM orders\nGROUP BY region\t "


def _refs(project):
    root, _db = project
    return run_git(root, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads")


def _candidate_page(project, saved):
    root, _db = project
    return worktree_of(root, saved["proposal"]) / saved["path"]


def _restart_draft(api, project):
    """One active draft per project (spec 0040): retire the current draft, then start."""
    from ariadne import draft

    active = draft.status(project)
    if active is not None:
        draft.discard(project, (active["generation"], active["candidate_revision"]))
    return api.start_proposal()


def _record_revision(project, proposal):
    from ariadne import proposals

    return proposals._load_record(project, proposal)["candidate_revision"]


def _example_release(root):
    """One admitted revision-4 integrated release carrying the retail metric,
    both Policies, the finalize computations category and the answer-examples
    category/entity type — the shared native Example baseline (extracted
    owned-fixture helper; expectations stay independently authored constants)."""
    import yaml
    from integration.tests.lumio_metric_mvp import (
        CONTROL,
        NAMESPACE,
        activate,
        content_project,
        page_parts,
        preview,
        write_page,
    )

    from ariadne import admission
    from ariadne.authoring import AuthoringProject
    from tests.test_git_authoring import approved, run_git, worktree_of

    project = content_project(root)
    # The revision-4 integrated selector validates the WHOLE candidate under
    # the producer contract: the scaffolded classic context_layer bundle is
    # retired — the same pure-native base the proven revision-2/3 journeys use.
    run_git(project, "rm", "-q", "-r", "--", "context_layer")
    run_git(
        project,
        "commit",
        "-q",
        "-m",
        "human: pure native knowledge baseline",
        "--",
        "context_layer",
    )
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    tree = worktree_of(project, started["proposal"])
    # The proven candidate edit: the reference page's typed profile cites a
    # catalog resource outside this project's approved registry — strip the
    # profile as a visible Git candidate edit (an ordinary page thereafter),
    # never an input conversion.
    reference = tree / "knowledge/references/order-number.md"
    ref_meta, ref_body = page_parts(reference)
    del ref_meta["ariadne_profile"]
    write_page(reference, ref_meta, ref_body)
    control = tree / "knowledge" / "lumio.yaml"
    control.write_text(
        # CONTROL already declares the computations category/entity type (the
        # C6 continuation control fix); only the answer-examples additions ride
        # this fixture's replacement — a duplicate category is invalid control
        CONTROL.replace(
            "  - name: metrics\n", "  - name: metrics\n  - name: answer-examples\n"
        ).replace("    metric: {}\n", "    metric: {}\n    answer-example: {}\n")
    )
    bindings = {
        "version": 1,
        "bindings": [
            {
                "subject": {"kind": "metric", "identity": "retail_sales::orders.revenue"},
                "policy": {"namespace": NAMESPACE, "entity_id": "entity:retail-return-policy"},
                "operations": ["get_metric"],
                "enforcement": None,
            }
        ],
    }
    (tree / "context_integration.yaml").write_text(
        "version: 1\nmode: integrated\nsubtree: knowledge\n"
        f"namespace: {NAMESPACE}\nprofile: ariadne-context/1\n"
        + yaml.safe_dump({"support_revision": 4, "policy_bindings": bindings}, sort_keys=False)
    )
    previous = _record_revision(project, started["proposal"])
    run_git(tree, "add", "-f", "--", "knowledge")
    run_git(tree, "add", "--", "context_integration.yaml")
    run_git(tree, "commit", "-q", "-m", "human: revision-4 answer-example candidate")
    revision = run_git(tree, "rev-parse", "HEAD").strip()
    admission.reconcile(project, started["proposal"], previous, revision)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    activate(project, review, preview(project, review, Path(root) / "published"))
    return project, api, review


def test_exact_sql_provenance_is_git_candidate_only_and_never_executed(tmp_path, capsys):
    """The exact submitted SQL is opt-in historical evidence, not executable input

    spec0035 C4 native journey: one revision-4 integrated release admits the
    retail knowledge (metric + Policies + the answer-examples category); an
    explicit CLI save authors ONE native knowledge/answer-examples page
    through the shared candidate writer; ordinary search stays admitted-only;
    the explicit candidate preview labels the draft; opt-in returns the exact
    submitted SQL verbatim; and no step ever opens the DuckDB source."""
    import hashlib
    import json

    import yaml
    from integration.tests.lumio_metric_mvp import activate, preview

    from tests.test_git_authoring import worktree_of

    project, api, review = _example_release(tmp_path / "project")

    db_path = project / "data" / "orders.duckdb"
    db_before = db_path.read_bytes()
    result = {**_SMALL_RESULT, "sql": _EXACT_SQL}
    submission = _submission(result)
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]
    assert mcp_save(project, submission) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "draft"
    assert saved["path"] == f"knowledge/answer-examples/{saved['id']}.md"

    page = worktree_of(project, saved["proposal"]) / saved["path"]
    front = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert front["ariadne_profile"]["kind"] == "answer_example"
    assert front["entity_types"] == ["answer-example"]
    assert front["id"] == f"entity:{saved['id']}"
    native = front["ariadne_profile"]["native"]
    assert native["sql_provenance"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }
    assert (
        native["answer"]["result_digest"]
        == hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )

    # Search reads the served release PLUS the active draft's own Example, labeled draft.
    assert mcp_search(project, "gross margin region") == 0
    default = json.loads(capsys.readouterr().out)
    assert len(default) == 1 and default[0]["status"] == "draft"
    assert "rows" not in default[0] and "sql" not in default[0]["provenance"]

    assert mcp_search(project, "gross margin region", include_sql=True) == 0
    opted_in = json.loads(capsys.readouterr().out)
    assert opted_in[0]["provenance"]["sql"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }
    assert db_path.read_bytes() == db_before
    assert not (project / "staging").exists()

    # Mandatory human admission of the Example candidate — save never auto-publishes.
    validated = api.validate_proposal(saved["proposal"], saved["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    example_review = api.review_proposal(saved["proposal"])
    activate(
        project,
        example_review,
        preview(
            project,
            example_review,
            tmp_path / "project" / "published",
            review["revision"],
        ),
    )

    assert mcp_search(project, "gross margin region") == 0
    admitted = json.loads(capsys.readouterr().out)
    assert len(admitted) == 1 and admitted[0]["status"] == "stable"
    hit = admitted[0]
    # the admitted Example pins the NEW active Bound Release (post-admission manifest)
    manifest = json.loads((project / ".ariadne" / "current.json").read_text())["bound_release"]
    assert hit["entity_id"] == f"entity:{saved['id']}"
    assert hit["published_version"] == example_review["revision"]
    assert hit["bound_release"] == manifest["digest"]
    assert hit["stale"] is False
    assert "sql" not in hit["provenance"]
    assert "rows" not in hit
    assert mcp_search(project, "gross margin region", include_sql=True) == 0
    admitted_sql = json.loads(capsys.readouterr().out)
    assert admitted_sql[0]["provenance"]["sql"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }
    assert db_path.read_bytes() == db_before
    assert not (project / "staging").exists()


def test_oversize_excerpt_and_sql_refuse_before_creating_a_candidate(project, capsys):
    refs_before = _refs(project)
    too_many_rows = {**_SMALL_RESULT, "rows": [{"value": "x" * 9000}]}
    assert mcp_save(project[0], _submission(too_many_rows)) == 1
    assert "8192" in error_payload(capsys.readouterr().err)["message"]
    assert _refs(project) == refs_before

    oversized_sql = {**_SMALL_RESULT, "sql": f"-- {'x' * 70_000}"}
    assert mcp_save(project[0], _submission(oversized_sql)) == 1
    assert "65536" in error_payload(capsys.readouterr().err)["message"]
    assert _refs(project) == refs_before

    oversized_record = _submission(_SMALL_RESULT, interpretation="x" * 65_000)
    assert mcp_save(project[0], oversized_record) == 1
    message = error_payload(capsys.readouterr().err)["message"]
    assert "encoded example record" in message and "65536" in message
    assert _refs(project) == refs_before


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sources": ["../../../../etc/passwd"]}, "escapes"),
        ({"sources": ["semantic_layer/models/orders.yml"]}, "knowledge page"),
        ({"sources": False}, "sources"),
        ({"sources": {}}, "sources"),
        (
            {
                "method": {
                    "operation": "get_metric",
                    "arguments": {"sql": "SELECT 1"},
                }
            },
            "name",
        ),
        ({"result": {**_SMALL_RESULT, "sql": " \n\t "}}, "result.sql"),
        ({"sql_provenance": {"source": "handwritten", "text": "SELECT 1"}}, "reserved"),
    ],
)
def test_invalid_citations_and_method_or_sql_provenance_refuse_without_refs(
    project, capsys, overrides, message
):
    refs_before = _refs(project)
    submission = _submission(_SMALL_RESULT, **overrides)
    assert mcp_save(project[0], submission) == 1
    assert message.lower() in error_payload(capsys.readouterr().err)["message"].lower()
    assert _refs(project) == refs_before


def test_candidate_sql_provenance_absence_and_malformed_refusal(tmp_path, capsys):
    """Spec 0023 §§3–4 on the NATIVE Example journey: a record WITHOUT
    sql_provenance is the honest legacy form (search discloses sql: null,
    never backfilled or excluded); PRESENT-but-malformed provenance is invalid
    data that fails the search with the named error. The variants are authored
    as native answer_example pages through the public page batch."""
    from tests.test_git_authoring import approved

    project, api, _review = _example_release(tmp_path / "project")
    started = api.start_proposal()
    approved(api, project, started)
    capsys.readouterr()
    assert mcp_save(project, _submission(_SMALL_RESULT, sources=[])) == 0  # into the active draft
    saved = json.loads(capsys.readouterr().out)
    assert saved["proposal"] == started["proposal"]
    root = project
    valid_page = (worktree_of(project, saved["proposal"]) / saved["path"]).read_text("utf-8")
    question = yaml.safe_load(valid_page.split("---")[1])["ariadne_profile"]["native"]["question"]

    def variant_page(new_id: str, *, without_provenance: bool = False, malformed: bool = False):
        """One authored native variant of the saved Example: a distinct page
        identity carrying the same record with the provenance under test."""
        front = yaml.safe_load(valid_page.split("---")[1])
        front["id"] = f"entity:{new_id}"  # the page-id form of saved native Examples
        front["title"] = f"{question} ({new_id})"
        native = front["ariadne_profile"]["native"]
        if without_provenance:
            native.pop("sql_provenance", None)
        if malformed:
            native["sql_provenance"] = {**native["sql_provenance"], "source": "handwritten"}
        dumped = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
        # author under the ACTUAL declared catalog category — the same
        # category the real saved page occupies (derive it, never guess a
        # new namespace)
        category_dir = saved["path"].rsplit("/", 1)[0]
        return f"{category_dir}/{new_id}.md", f"---\n{dumped}\n---\n"

    from ariadne import proposals

    no_sql_path, no_sql_content = variant_page("legacy-without-sql", without_provenance=True)
    no_sql = proposals.edit_page_batch(
        root,
        saved["proposal"],
        saved["candidate_revision"],
        [{"path": no_sql_path, "content": no_sql_content}],
    )
    assert no_sql["revision"]
    assert mcp_search(project, "gross margin region", include_sql=True) == 0
    hits = json.loads(capsys.readouterr().out)
    assert (
        next(hit for hit in hits if hit["id"] == "entity:legacy-without-sql")["provenance"]["sql"]
        is None
    )

    # PRESENT-but-malformed provenance is invalid data: the producer page
    # gate refuses it at the PUBLIC BATCH seam — before any byte is written,
    # the named diagnostic — so the malformed record can never even enter a
    # candidate (the earlier honest boundary; the same named refusal search
    # keeps for anything arriving by other means)
    import pytest
    from lumio_wiki.git_authoring import GitAuthoringError

    malformed_path, malformed_content = variant_page("malformed-provenance", malformed=True)
    with pytest.raises(
        GitAuthoringError, match="sql_provenance.source must be the fixed descriptor"
    ):
        proposals.edit_page_batch(
            root,
            saved["proposal"],
            no_sql["revision"],
            [{"path": malformed_path, "content": malformed_content}],
        )
    # the refusal wrote nothing: the candidate revision never moved
    from tests.test_git_authoring import branch_of

    assert branch_of(root, saved["proposal"]) == no_sql["revision"]


def test_define_metric_examples_retain_only_the_actual_operation_arguments(project, capsys):
    submission = _submission(
        _SMALL_RESULT,
        method={
            "operation": "define_metric",
            "arguments": {
                "name": "margin_ratio",
                "description": "margin as ratio of sums",
                "source": "demo.main.orders",
                "expression": "SUM(amount)",
                "dimensions": ["region"],
            },
        },
    )
    assert mcp_save(project[0], submission) == 0
    saved = json.loads(capsys.readouterr().out)
    page = _candidate_page(project, saved)
    metadata = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    method = metadata["ariadne_profile"]["native"]["method"]
    assert method["operation"] == "define_metric"
    assert method["arguments"]["source"] == "demo.main.orders"


def test_native_example_save_search_never_opens_sources(tmp_path, monkeypatch, capsys):
    """F1: an actual CLI save, CLI admitted/candidate search and the MCP save
    tool never construct the source builder — a boundary sentinel on
    ``DuckDBExecution`` trips on any construction (the sentinel is boundary
    proof, not a mock of the code under test). The boundary is restored
    before the human admission, which legitimately needs validation."""
    import asyncio
    import json
    from datetime import UTC, datetime

    from ariadne import answer_examples, execution, serve
    from ariadne.query import QueryRuntime

    project, api, review = _example_release(tmp_path / "project")
    db_path = project / "data" / "orders.duckdb"
    db_before = db_path.read_bytes()

    def _sentinel(self, *args, **kwargs):
        raise AssertionError("the source builder was constructed during Example save/search")

    monkeypatch.setattr(execution.DuckDBExecution, "__init__", _sentinel)

    submission = _submission({**_SMALL_RESULT, "sql": _EXACT_SQL})
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]

    # F6 repro: identical-instant peer saves can't see each other; spec0007 demands distinct drafts.
    fixed_instant = datetime(2031, 2, 3, 4, 5, 6, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_instant

    with monkeypatch.context() as clock:  # clock scoped to the save seam only
        clock.setattr(answer_examples, "datetime", _FrozenDatetime)
        assert mcp_save(project, submission) == 0
        saved = json.loads(capsys.readouterr().out)

        assert mcp_search(project, "gross margin region") == 0
        hits = json.loads(capsys.readouterr().out)
        assert len(hits) == 1 and hits[0]["status"] == "draft"

        app = serve.build_app(QueryRuntime, project=str(project))

        async def _mcp_save():
            return await app.call_tool("save_example", {"submission": submission})

        def _payload(result):
            # a plain dict return is exactly one JSON text block: no structured
            # content wrapper (the observed native form, per the proven journey)
            assert not getattr(result, "is_error", False)
            blocks = list(getattr(result, "content", ()))
            assert len(blocks) == 1 and blocks[0].type == "text"
            return json.loads(blocks[0].text)

        mcp_saved = _payload(asyncio.run(_mcp_save()))

    assert mcp_saved["status"] == "draft" and mcp_saved["id"] != saved["id"]
    assert mcp_saved["path"] != saved["path"]  # two page paths, never one aliased page
    assert mcp_saved["proposal"] == saved["proposal"]  # one active draft holds both (spec 0040)

    def _persisted(record):
        page = worktree_of(project, record["proposal"]) / record["path"]
        return yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])

    cli_page, mcp_page = _persisted(saved), _persisted(mcp_saved)
    assert cli_page["id"] != mcp_page["id"]  # two distinct Entity identities
    assert cli_page["title"] != mcp_page["title"]
    assert (
        cli_page["ariadne_profile"]["native"]["question"]
        == mcp_page["ariadne_profile"]["native"]["question"]
        == submission["question"]  # exact original question bytes in BOTH drafts
    )
    assert db_path.read_bytes() == db_before

    monkeypatch.undo()  # restore the boundary: human admission legitimately validates
    validated = api.validate_proposal(saved["proposal"], mcp_saved["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]


def test_native_example_repeated_question_creates_distinct_drafts(tmp_path, capsys):
    """F2: the same question saved into the same candidate revision and again
    after admission creates distinct drafts — the generated identity suffixes
    the Entity id and the canonical title, the writer's identity guard holds,
    and the original native question bytes are preserved verbatim in every
    persisted record; nothing is overwritten."""
    import json

    import yaml
    from integration.tests.lumio_metric_mvp import activate, preview

    from tests.test_git_authoring import worktree_of

    project, api, review = _example_release(tmp_path / "project")
    submission = _submission({**_SMALL_RESULT, "sql": _EXACT_SQL})
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]

    assert mcp_save(project, submission) == 0
    first = json.loads(capsys.readouterr().out)
    assert mcp_save(project, submission) == 0  # the active draft takes a second Example
    second = json.loads(capsys.readouterr().out)
    assert second["id"] != first["id"]
    assert second["proposal"] == first["proposal"]

    def _persisted(saved):
        page = worktree_of(project, saved["proposal"]) / saved["path"]
        front = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
        native = front["ariadne_profile"]["native"]
        return front["title"], native["question"]

    title1, question1 = _persisted(first)
    title2, question2 = _persisted(second)
    assert title1 != title2  # unique canonical titles carry the generated identity
    assert first["id"] in title1 and second["id"] in title2
    assert question1 == question2 == submission["question"]  # exact original bytes

    # after admission: the next same-question save is a fresh draft, still no overwrite
    current = _record_revision(project, first["proposal"])
    validated = api.validate_proposal(first["proposal"], current)
    assert validated["ok"] is True, validated["errors"]
    example_review = api.review_proposal(first["proposal"])
    activate(
        project,
        example_review,
        preview(
            project,
            example_review,
            tmp_path / "project" / "published",
            review["revision"],
        ),
    )
    assert mcp_save(project, submission) == 0
    third = json.loads(capsys.readouterr().out)
    assert third["id"] not in (first["id"], second["id"])
    assert third["proposal"] != first["proposal"]
    title3, _question3 = _persisted(third)
    assert title3 not in (title1, title2)


def test_native_example_candidate_preview_uses_persisted_identity(tmp_path):
    """F3: the explicit candidate preview selects parsed producer kinds
    through the public SDK capture — a valid answer_example page under ANOTHER
    declared category, whose persisted Entity id differs from its filename
    stem and whose native block carries no type key, is found by identity,
    never by path/filename/type matching."""
    import hashlib
    import json

    from ariadne import answer_examples, proposals
    from tests.test_git_authoring import approved

    project, api, review = _example_release(tmp_path / "project")
    result_literal = {
        "metric": "revenue",
        "governed": True,
        "columns": ["region"],
        "rows": [{"region": "EMEA"}],
    }
    captured_text = json.dumps(result_literal, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(captured_text.encode()).hexdigest()
    started = api.start_proposal()
    approved(api, project, started)
    revision = _record_revision(project, started["proposal"])
    front = {
        "id": "entity:persisted-example-identity",
        "title": "Saved order example",
        "entity_types": ["answer-example"],
        "tags": ["answer-example"],
        "summary": "Persisted identity probe.",
        "lifecycle": "draft",
        "visibility": "public",
        "sources": [{"id": "src-explicit-submission", "title": "Explicit user submission"}],
        "ariadne_profile": {
            "version": 1,
            "kind": "answer_example",
            "native": {
                "title": "Saved order example",
                "description": "Persisted identity probe.",
                "tags": ["answer-example"],
                "sources": [],
                "question": "What is the order number format?",
                "interpretation": "A composite globally unique order number.",
                "method": {"operation": "get_metric", "arguments": {"name": "revenue"}},
                "submitter": {
                    "identity": "expert:dana",
                    "attestation": "Confirmed against the observed result.",
                },
                "citations": [],
                "answer": {
                    "captured": "2026-11-11T00:00:00+00:00",
                    "excerpt": captured_text,
                    "result_digest": digest,
                },
            },
        },
    }
    import yaml

    body = (
        "# What is the order number format?\n\n"
        "Historical evidence only — never a cached answer.\n\n"
        f"Captured answer excerpt (2026-11-11T00:00:00+00:00; full structured-result "
        f"digest `{digest}`):\n\n````json\n{captured_text}\n````\n"
    )
    page = "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---" + body
    proposals.edit_page_batch(
        project,
        started["proposal"],
        revision,
        [{"path": "knowledge/references/saved-order-example.md", "content": page}],
    )
    new_revision = _record_revision(project, started["proposal"])
    hits = answer_examples.search_candidate(
        project,
        "order number format",
        proposal=started["proposal"],
        revision=new_revision,
    )
    assert len(hits) == 1
    hit = hits[0]
    assert hit["entity_id"] == "entity:persisted-example-identity"  # persisted, not filename
    assert hit["id"] == "entity:persisted-example-identity"
    assert hit["path"] == "knowledge/references/saved-order-example.md"  # another declared category
    assert hit["status"] == "draft"
    assert hit["proposal"] == started["proposal"] and hit["revision"] == new_revision
    assert "sql" not in hit["provenance"]
    assert "rows" not in hit


def test_native_example_edits_keep_core_validation(tmp_path):
    """F4: generic native page edits cannot smuggle invalid Example records
    past candidate validation — a record missing its required structured
    argument, an oversize encoded page, and a changed citation with a forged
    digest each refuse BEFORE admission on the same candidate boundary; a
    forged system-owned claim already refuses at the write gate."""
    import copy
    import hashlib
    import json

    import pytest
    import yaml
    from lumio_wiki.git_authoring import GitAuthoringError

    from ariadne import proposals
    from tests.test_git_authoring import approved

    project, api, review = _example_release(tmp_path / "project")
    result_literal = {
        "metric": "revenue",
        "governed": True,
        "columns": ["region"],
        "rows": [{"region": "EMEA"}],
    }
    captured_text = json.dumps(result_literal, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(captured_text.encode()).hexdigest()
    base_native = {
        "type": "answer_example",
        "title": "Validation probe",
        "description": "Candidate validation probe.",
        "tags": ["answer-example"],
        "sources": [{"id": "src-explicit-submission", "title": "Explicit user submission"}],
        "question": "What is the order number format?",
        "interpretation": "A composite globally unique order number.",
        "method": {"operation": "get_metric", "arguments": {"name": "revenue"}},
        "submitter": {
            "identity": "expert:dana",
            "attestation": "Confirmed against the observed result.",
        },
        "citations": [{"path": "metrics/retail-revenue.md", "sha256": digest}],
        "answer": {
            "captured": "2026-11-11T00:00:00+00:00",
            "excerpt": captured_text,
            "result_digest": digest,
        },
    }

    def _probe_page(native):
        front = {
            "id": "entity:validation-probe",
            "title": "Validation probe",
            "entity_types": ["answer-example"],
            "tags": ["answer-example"],
            "summary": "Candidate validation probe.",
            "lifecycle": "draft",
            "visibility": "public",
            "sources": [{"id": "src-explicit-submission", "title": "Explicit user submission"}],
            "ariadne_profile": {
                "version": 1,
                "kind": "answer_example",
                "native": native,
            },
        }
        body = (
            "# Validation probe\n\n"
            "Historical evidence only — never a cached answer.\n\n"
            f"Captured answer excerpt ({native['answer']['captured']}; full "
            f"structured-result digest `{native['answer']['result_digest']}`):\n\n"
            f"````json\n{native['answer']['excerpt']}\n````\n"
        )
        return "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---" + body

    def _fresh():
        started = _restart_draft(api, project)
        approved(api, project, started)
        return started, _record_revision(project, started["proposal"])

    def _edit(started, revision, native, name):
        return proposals.edit_page_batch(
            project,
            started["proposal"],
            revision,
            [{"path": f"knowledge/answer-examples/{name}.md", "content": _probe_page(native)}],
        )

    # (a) missing required structured argument: the edit lands (structurally
    # valid), candidate validation refuses before any admission
    started, revision = _fresh()
    broken = copy.deepcopy(base_native)
    # non-empty structured arguments that miss the operation's REQUIRED key:
    # the SDK structural gate passes them, Core candidate validation refuses
    broken["method"]["arguments"] = {"dimensions": ["region"]}
    _edit(started, revision, broken, "probe-a")
    new_revision = _record_revision(project, started["proposal"])
    validated = api.validate_proposal(started["proposal"], new_revision)
    assert validated["ok"] is False
    assert any("missing structured arguments" in e for e in validated["errors"]), validated

    # (b) an oversize encoded record (>64 KiB SQL) refuses before admission
    started, revision = _fresh()
    broken = copy.deepcopy(base_native)
    broken["sql_provenance"] = {"source": "submitted_result.sql", "text": "-- " + "x" * 70_000}
    try:
        _edit(started, revision, broken, "probe-b")
        new_revision = _record_revision(project, started["proposal"])
        validated = api.validate_proposal(started["proposal"], new_revision)
        assert validated["ok"] is False
        assert any("65536-byte bound" in e for e in validated["errors"]), validated
    except GitAuthoringError as exc:
        assert "content" in str(exc)  # the shared pre-write content boundary

    # (c) a changed citation with a forged digest refuses before admission
    started, revision = _fresh()
    broken = copy.deepcopy(base_native)
    broken["citations"] = [{"path": "metrics/retail-revenue.md", "sha256": "0" * 64}]
    _edit(started, revision, broken, "probe-c")
    new_revision = _record_revision(project, started["proposal"])
    validated = api.validate_proposal(started["proposal"], new_revision)
    assert validated["ok"] is False
    assert any("does not match this candidate's bytes" in e for e in validated["errors"]), validated

    # (d) a forged system-owned claim refuses at the write gate: the frozen
    # answer_example structural schema names the forged field (verified) and
    # no validated page ever reaches admission
    started, revision = _fresh()
    broken = copy.deepcopy(base_native)
    broken["verified"] = [{"by": "someone"}]
    with pytest.raises(GitAuthoringError, match="unsupported answer_example field"):
        _edit(started, revision, broken, "probe-d")


def test_native_example_history_deletion_refuses(tmp_path, capsys):
    """F4 history (owner completion): a previously admitted native Example
    cannot vanish from a subsequent candidate — page removal is refused by
    public Core validation with a named diagnostic carrying the persisted
    identity and baseline path (identity-keyed via the public SDK capture,
    never a filename guess, never a floating HEAD)."""
    import json

    from integration.tests.lumio_metric_mvp import activate, preview, reconcile_knowledge

    from tests.test_git_authoring import approved, worktree_of

    project, api, review = _example_release(tmp_path / "project")
    submission = _submission({**_SMALL_RESULT, "sql": _EXACT_SQL})
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]
    assert mcp_save(project, submission) == 0
    saved = json.loads(capsys.readouterr().out)
    current = _record_revision(project, saved["proposal"])
    validated = api.validate_proposal(saved["proposal"], current)
    assert validated["ok"] is True, validated["errors"]
    example_review = api.review_proposal(saved["proposal"])
    activate(
        project,
        example_review,
        preview(
            project,
            example_review,
            tmp_path / "project" / "published",
            review["revision"],
        ),
    )

    # a subsequent Git candidate removes the admitted Example page
    started = api.start_proposal()
    approved(api, project, started)
    tree = worktree_of(project, started["proposal"])
    (tree / saved["path"]).unlink()
    revision = reconcile_knowledge(
        project, started["proposal"], _record_revision(project, started["proposal"])
    )
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is False
    assert any(
        "history may not be removed" in e and f"entity:{saved['id']}" in e
        for e in validated["errors"]
    ), validated["errors"]


def test_native_example_body_excerpt_keeps_presence_and_byte_bound(tmp_path, capsys):
    """F4 body (owner completion): the fenced JSON excerpt in the page BODY is
    required and stays within the 8 KiB UTF-8 bound — independent of the
    caption line, of the structured native.answer.excerpt and of the 64 KiB
    whole-page bound. A valid control validates cleanly BEFORE any malformed
    body, so the named refusals are attributable."""
    import json
    import re

    from ariadne import proposals
    from tests.test_git_authoring import approved, worktree_of

    project, api, review = _example_release(tmp_path / "project")
    submission = _submission({**_SMALL_RESULT, "sql": _EXACT_SQL})
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]

    # valid control: the CLI save validates cleanly before any malformed body
    assert mcp_save(project, submission) == 0
    saved = json.loads(capsys.readouterr().out)
    current = _record_revision(project, saved["proposal"])
    control = api.validate_proposal(saved["proposal"], current)
    assert control["ok"] is True, control["errors"]

    base_text = (worktree_of(project, saved["proposal"]) / saved["path"]).read_text(
        encoding="utf-8"
    )
    oversize_excerpt = "é" * 5000  # 10000 UTF-8 bytes, 5000 characters (<8192 chars)
    variant_missing = base_text.split("````json")[0]  # caption retained, fence removed
    variant_oversize = re.sub(
        r"````json\n.*?\n````",
        "````json\n" + oversize_excerpt + "\n````",
        base_text,
        flags=re.DOTALL,
    )
    assert variant_missing != base_text and variant_oversize != base_text
    assert (
        "Captured answer excerpt" in variant_missing
        and "Captured answer excerpt" in variant_oversize
    )
    assert len(oversize_excerpt.encode("utf-8")) > 8192 and len(oversize_excerpt) < 8192
    assert len(variant_oversize.encode("utf-8")) < 65536

    # (a) a missing fenced excerpt refuses even with the caption retained
    started = _restart_draft(api, project)
    approved(api, project, started)
    revision = _record_revision(project, started["proposal"])
    proposals.edit_page_batch(
        project,
        started["proposal"],
        revision,
        [{"path": saved["path"], "content": variant_missing}],
    )
    new_revision = _record_revision(project, started["proposal"])
    validated = api.validate_proposal(started["proposal"], new_revision)
    assert validated["ok"] is False
    assert any("answer excerpt block is missing" in e for e in validated["errors"]), validated
    assert not any("missing structured arguments" in e for e in validated["errors"])

    # (b) a body excerpt over the 8 KiB UTF-8 bound refuses even with a small
    # native.answer.excerpt and a whole page under the 64 KiB record bound
    started_b = _restart_draft(api, project)
    approved(api, project, started_b)
    revision_b = _record_revision(project, started_b["proposal"])
    proposals.edit_page_batch(
        project,
        started_b["proposal"],
        revision_b,
        [{"path": saved["path"], "content": variant_oversize}],
    )
    new_revision_b = _record_revision(project, started_b["proposal"])
    validated_b = api.validate_proposal(started_b["proposal"], new_revision_b)
    assert validated_b["ok"] is False
    assert any("8192-byte bound" in e for e in validated_b["errors"]), validated_b
    assert not any("missing structured arguments" in e for e in validated_b["errors"])


def test_a_save_prepared_against_one_base_refuses_when_the_first_write_base_moves(
    tmp_path, monkeypatch, capsys
):
    """Finding 4 (second pass): with no active draft the save pins the first-write base it
    checked citations against; if another approval moves it before the write, the save
    refuses instead of writing into the newer base."""
    from ariadne import answer_examples, draft

    root, _api, _review = _example_release(tmp_path / "project")
    assert draft.status(root) is None
    real = answer_examples._verify_citation
    moved = {"done": False}

    def verify_then_move(proj, revision, ref):
        out = real(proj, revision, ref)
        if not moved["done"]:
            moved["done"] = True
            monkeypatch.setattr(draft, "first_write_base", lambda *_a, **_k: "0" * 40)
        return out

    monkeypatch.setattr(answer_examples, "_verify_citation", verify_then_move)
    submission = _submission(_SMALL_RESULT)
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]
    capsys.readouterr()
    assert mcp_save(root, submission) == 1
    monkeypatch.undo()
    assert "no longer the base" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert draft.status(root) is None  # nothing was written
