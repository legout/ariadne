"""Core Git-only authoring acceptance tests for approved spec 0027."""

import asyncio
import json

from ariadne import admission
from ariadne.authoring import AuthoringProject
from ariadne.cli import main as cli_main
from ariadne.query import QueryRuntime
from ariadne.query_results import QueryResultError
from tests.test_git_admission import _policy_edit, _validated_ready, admit
from tests.test_git_authoring import (
    MODEL_YML,
    POLICY_PAGE,
    branch_of,
    complete_bundle_project,
    run_git,
    worktree_of,
)


def test_ad_hoc_is_ephemeral_and_explicit_authoring_retains_definition(tmp_path, capsys):
    """Ad-hoc success/refusal write nothing; explicit Authoring retains a definition."""
    project = complete_bundle_project(tmp_path)
    authoring = AuthoringProject(project)
    review = _validated_ready(
        authoring,
        project,
        _policy_edit(POLICY_PAGE.replace("The rule body.", "The G1 fixture rule.")),
    )
    assert admit(project, review) == 0
    capsys.readouterr()

    runtime = QueryRuntime.open_project(project)
    runtime._limits["max_rows"] = 2
    staging = project / "staging"
    refs_before = run_git(
        project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads"
    ).splitlines()
    proposal_records_before = sorted(
        path.name for path in (project / ".ariadne" / "proposals").glob("*.json")
    )
    definition = {
        "name": "one_time_event_count",
        "description": "Count event rows once",
        "source": "events.events",
        "expression": "COUNT(id)",
    }

    # The admitted fixture contains exactly three event rows.
    result = asyncio.run(runtime.define_metric(definition))
    assert result["rows"] == [{"one_time_event_count": 3}]
    assert result["governed"] is False and result["context"] is None
    assert result["definition"]["name"] == definition["name"]
    assert "COUNT" in result["sql"].upper()
    assert result["result"]["complete"] is True
    assert result["persistence"] == {"status": "not_saved"}
    assert "staged_as" not in result and "staged_context_as" not in result

    # Three label groups exceed the independently configured two-row ceiling.
    try:
        asyncio.run(runtime.define_metric({**definition, "dimensions": ["label"]}))
    except QueryResultError as exc:
        refusal = exc.refusal()
    else:
        raise AssertionError("three label groups must exceed the two-row limit")
    assert refusal["error"]["code"] == "result_row_limit"
    assert refusal["result"] == {
        "status": "refused",
        "complete": False,
        "returned_rows": 0,
    }
    assert refusal["persistence"] == {"status": "not_saved"}
    assert "staging_status" not in refusal
    assert not staging.exists()
    assert (
        run_git(
            project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads"
        ).splitlines()
        == refs_before
    )
    assert (
        sorted(path.name for path in (project / ".ariadne" / "proposals").glob("*.json"))
        == proposal_records_before
    )
    runtime.con.close()

    # Retention is the existing typed, revision-checked Authoring edit—not a
    # define_metric option or a new persistence tool.
    started = authoring.start_proposal()
    retained_model = MODEL_YML.replace(
        "    metrics:\n",
        "    metrics:\n"
        "      - name: one_time_event_count\n"
        "        description: Count event rows once\n"
        "        expression:\n"
        "          dialects:\n"
        "            - dialect: ANSI_SQL\n"
        "              expression: COUNT(id)\n",
        1,
    )
    edited = authoring.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "model", "name": "events", "content": retained_model},
    )
    assert edited["changed"] is True
    assert branch_of(project, started["proposal"]) == edited["revision"]
    candidate_model = (
        worktree_of(project, started["proposal"]) / "semantic_layer" / "models" / "events.yml"
    ).read_text(encoding="utf-8")
    assert "one_time_event_count" in candidate_model and "COUNT(id)" in candidate_model

    # The still-admitted snapshot does not serve the unadmitted candidate metric.
    pinned = QueryRuntime.open_project(project)
    try:
        asyncio.run(pinned.get_metric("one_time_event_count"))
    except ValueError as exc:
        assert "unknown metric" in str(exc)
    else:
        raise AssertionError("unadmitted candidate metric must not be served")
    finally:
        pinned.con.close()
    assert not staging.exists()


def test_examples_share_git_admission_and_preserve_stale_history(tmp_path, capsys):
    """Explicit candidate discovery is source-free; admission controls Example status."""

    def expect_value_error(message, operation):
        try:
            operation()
        except ValueError as exc:
            assert message in str(exc).lower()
        else:
            raise AssertionError(f"operation should be refused with {message!r}")

    # Metadata-only candidate discovery works before any admission exists.
    fresh_project = complete_bundle_project(tmp_path / "fresh")
    fresh = AuthoringProject(fresh_project).start_proposal()
    assert admission.load_current(fresh_project) is None
    assert (
        cli_main(
            [
                "search-examples",
                "event count",
                "--project",
                str(fresh_project),
                "--proposal",
                fresh["proposal"],
                "--revision",
                fresh["candidate_revision"],
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == []

    project = complete_bundle_project(tmp_path / "admitted")
    authoring = AuthoringProject(project)
    review = _validated_ready(authoring, project, _policy_edit("The G2 fixture rule."))
    assert admit(project, review) == 0
    capsys.readouterr()
    runtime = QueryRuntime.open_project(project)
    metrics_before = asyncio.run(runtime.list_metrics())
    assert asyncio.run(runtime.search_examples("event count")) == []

    def submission(question):
        return {
            "question": question,
            "interpretation": "Count all admitted event rows.",
            "method": {"operation": "get_metric", "arguments": {"name": "event_count"}},
            "result": {
                "metric": "event_count",
                "sql": "SELECT COUNT(id) AS event_count FROM events.events",
                "columns": ["event_count"],
                "rows": [{"event_count": 3}],
                "governed": True,
            },
            "submitter": "Ariadne Tests",
            "attestation": "I confirmed this against the observed event_count result.",
            "sources": [
                "context_layer/metrics/event_count.md",
                "context_layer/policies/all-events-count.md",
            ],
        }

    example = submission("How many events are present?")
    refs_before = run_git(
        project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads"
    ).splitlines()
    expect_value_error(
        "reserved",
        lambda: asyncio.run(runtime.save_example({**example, "status": "stable"})),
    )
    assert (
        run_git(
            project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads"
        ).splitlines()
        == refs_before
    )
    saved = asyncio.run(runtime.save_example(example))
    assert saved["base_revision"] == review["revision"]
    assert saved["candidate_revision"] != saved["base_revision"]
    assert saved["status"] == "draft" and saved["path"].startswith("answer_examples/")
    from ariadne.serve import build_app
    from tests.test_authoring_mcp import _payload

    app = build_app(runtime, project=project)
    mcp_result = asyncio.run(
        app.call_tool(
            "search_examples",
            {
                "query": "event count",
                "proposal": saved["proposal"],
                "revision": saved["candidate_revision"],
            },
        )
    )
    structured = getattr(mcp_result, "structured_content", None)
    mcp_hits = (
        structured["result"]
        if isinstance(structured, dict) and set(structured) == {"result"}
        else _payload(mcp_result)
    )
    if isinstance(mcp_hits, dict):
        mcp_hits = [mcp_hits]
    assert mcp_hits[0]["proposal"] == saved["proposal"]
    assert mcp_hits[0]["revision"] == saved["candidate_revision"]
    assert not (project / "staging").exists()
    staged_page = project / "staging" / "context_layer" / "policies" / "unadmitted-g2-boundary.md"
    staged_page.parent.mkdir(parents=True)
    staged_page.write_text("# G2NeedleQuartzPhrase", encoding="utf-8")
    assert asyncio.run(runtime.search_context("g2needlequartzphrase")) == []
    assert not any(
        page["path"] == "policies/unadmitted-g2-boundary.md"
        for page in asyncio.run(runtime.list_context_pages())
    )
    expect_value_error(
        "managed projects",
        lambda: asyncio.run(
            runtime.read_context_page("policies/unadmitted-g2-boundary.md", draft=True)
        ),
    )
    assert asyncio.run(runtime.search_examples("event count")) == []

    # An explicit write to an existing candidate must use its current revision.
    expect_value_error(
        "stale revision",
        lambda: asyncio.run(
            runtime.save_example(
                submission("What is the total number of event rows?"),
                proposal=saved["proposal"],
                expected_revision=saved["base_revision"],
            )
        ),
    )
    second = asyncio.run(
        runtime.save_example(
            submission("What is the total number of event rows?"),
            proposal=saved["proposal"],
            expected_revision=saved["candidate_revision"],
        )
    )
    assert second["candidate_revision"] != saved["candidate_revision"]

    # Search resolves committed blobs, not mutable proposal worktree bytes.
    first_path = worktree_of(project, saved["proposal"]) / saved["path"]
    saved_bytes = first_path.read_bytes()
    first_path.write_text("worktree-only corruption", encoding="utf-8")
    preview = asyncio.run(
        runtime.search_examples(
            "event count",
            proposal=second["proposal"],
            revision=second["candidate_revision"],
        )
    )
    assert {hit["question"] for hit in preview} == {
        example["question"],
        "What is the total number of event rows?",
    }
    assert all(
        hit["status"] == "draft" and hit["revision"] == second["candidate_revision"]
        for hit in preview
    )
    assert all("rows" not in hit and "sql" not in hit.get("provenance", {}) for hit in preview)
    first_path.write_bytes(saved_bytes)
    expect_value_error(
        "candidate",
        lambda: asyncio.run(
            runtime.search_examples(
                "event count",
                proposal=second["proposal"],
                revision=saved["candidate_revision"],
            )
        ),
    )

    validation = authoring.validate_proposal(second["proposal"], second["candidate_revision"])
    assert validation["ok"] is True
    review = authoring.review_proposal(second["proposal"])
    assert review["revision"] == validation["revision"]
    assert admit(project, review) == 0
    capsys.readouterr()
    _, admitted_snapshot = admission.resolve_admission(project)
    saved_bytes = (admitted_snapshot / saved["path"]).read_bytes()
    assert b"status: draft" in saved_bytes and b"review:" not in saved_bytes
    assert example["question"] in (admitted_snapshot / "answer_examples" / "index.md").read_text()

    runtime.con.close()
    current = QueryRuntime.open_project(project)
    admitted_hits = asyncio.run(current.search_examples("event count"))
    assert {hit["question"] for hit in admitted_hits} == {
        example["question"],
        "What is the total number of event rows?",
    }
    assert all(hit["status"] == "stable" and hit["stale"] is False for hit in admitted_hits)
    assert asyncio.run(current.list_metrics()) == metrics_before

    changed = authoring.start_proposal()
    edited = authoring.edit_proposal(
        changed["proposal"],
        changed["candidate_revision"],
        _policy_edit("The G2 changed rule."),
    )
    historical = asyncio.run(
        current.search_examples(
            "event count",
            proposal=changed["proposal"],
            revision=edited["revision"],
            include_history=True,
        )
    )
    assert len(historical) == 2
    assert all(hit["status"] == "draft" and hit["stale"] is True for hit in historical)
    assert (
        asyncio.run(
            current.search_examples(
                "event count", proposal=changed["proposal"], revision=edited["revision"]
            )
        )
        == []
    )
    validation = authoring.validate_proposal(changed["proposal"], edited["revision"])
    assert validation["ok"] is True
    review = authoring.review_proposal(changed["proposal"])
    assert review["revision"] == validation["revision"]
    assert admit(project, review) == 0
    capsys.readouterr()

    # A result pinned to the old Policy cannot be saved into a newer candidate.
    latest_proposal = authoring.start_proposal()
    expect_value_error(
        "citation",
        lambda: asyncio.run(
            current.save_example(
                submission("An answer from the previous Policy."),
                proposal=latest_proposal["proposal"],
                expected_revision=latest_proposal["candidate_revision"],
            )
        ),
    )
    assert branch_of(project, latest_proposal["proposal"]) == latest_proposal["candidate_revision"]
    current.con.close()

    latest = QueryRuntime.open_project(project)
    assert asyncio.run(latest.search_examples("event count")) == []
    history = asyncio.run(latest.search_examples("event count", include_history=True))
    assert len(history) == 2
    assert all(hit["status"] == "stable" and hit["stale"] is True for hit in history)
    _, latest_snapshot = admission.resolve_admission(project)
    assert (latest_snapshot / saved["path"]).read_bytes() == saved_bytes
    latest.con.close()


def test_example_commit_failure_reports_unadmitted_worktree_state(tmp_path, capsys, monkeypatch):
    from ariadne import answer_examples, proposals

    project = complete_bundle_project(tmp_path)
    authoring = AuthoringProject(project)
    review = _validated_ready(authoring, project, _policy_edit("The G2 failure fixture."))
    assert admit(project, review) == 0
    capsys.readouterr()
    started = authoring.start_proposal()
    runtime = QueryRuntime.open_project(project)
    monkeypatch.setattr(answer_examples, "_example_id", lambda question, now: "partial-example")
    original_git = proposals._git

    def fail_example_commit(args, cwd, **kwargs):
        if args[:1] == ["commit"] and "ariadne: add answer example partial-example" in args:
            raise OSError("simulated commit failure")
        return original_git(args, cwd, **kwargs)

    monkeypatch.setattr(proposals, "_git", fail_example_commit)
    submission = {
        "question": "How many events are present?",
        "interpretation": "Count every admitted event row.",
        "method": {"operation": "get_metric", "arguments": {"name": "event_count"}},
        "result": {
            "metric": "event_count",
            "sql": "SELECT COUNT(id) AS event_count FROM events.events",
            "columns": ["event_count"],
            "rows": [{"event_count": 3}],
            "governed": True,
        },
        "submitter": "Ariadne Tests",
        "attestation": "I checked the Example's stated meaning.",
        "sources": [],
    }
    try:
        asyncio.run(
            runtime.save_example(
                submission,
                proposal=started["proposal"],
                expected_revision=started["candidate_revision"],
            )
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("failed Git commit must report the unadmitted candidate residue")
    assert f"Recorded candidate {started['candidate_revision']}" in message
    assert f"branch HEAD {started['candidate_revision']}" in message
    assert "A  answer_examples/partial-example.md" in message
    assert "simulated commit failure" in message
    runtime.con.close()
