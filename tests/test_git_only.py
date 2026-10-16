"""Core Git-only authoring acceptance tests for approved spec 0027."""

import asyncio

from ariadne.authoring import AuthoringProject
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


def test_ad_hoc_is_ephemeral_and_explicit_authoring_retains_definition(
    tmp_path, capsys
):
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
    assert run_git(
        project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads"
    ).splitlines() == refs_before
    assert sorted(
        path.name for path in (project / ".ariadne" / "proposals").glob("*.json")
    ) == proposal_records_before
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
        worktree_of(project, started["proposal"])
        / "semantic_layer"
        / "models"
        / "events.yml"
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
