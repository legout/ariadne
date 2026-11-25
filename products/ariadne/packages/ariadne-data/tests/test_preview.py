"""`ariadne preview` (spec 0040 §3.6; AC1, AC9): a metric from the active draft over exactly
granted identities, governed:false. Real temporary Git repositories; expected values are
hand-worked from the fixture (events ids 1..3, labels a,b,c)."""

import json
import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import authoring_sources, draft  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from tests.test_git_admission import _policy_edit, admitted_ready  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    MODEL_YML,
    admit_library,
    complete_bundle_project,
    write_parquet,
)

MODEL_REL = "semantic_layer/models/events.yml"
EDITED = MODEL_YML.replace("COUNT(*)", "SUM(id)")  # ids 1+2+3 = 6, the served count is 3
PEEK = MODEL_YML.replace("source: events.events", "source: peek.peek")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture
def served(tmp_path):
    """A project serving release A (event_count = COUNT(*) = 3)."""
    project = complete_bundle_project(tmp_path)
    review, _ = admitted_ready(AuthoringProject(project), project, _policy_edit("Rule A."))
    assert admit_library(project, review, destination=tmp_path / "published") == 0
    return project


def _pin(project):
    view = draft.status(project)
    return (view["generation"], view["candidate_revision"])


def _edit(project, content, expected=None):
    return draft.edit_artifact(project, expected, MODEL_REL, content)


def _validate(project):
    result = draft.validate(project, _pin(project))
    assert result["ok"] is True, result["errors"]


def _run(argv, capsys):
    code = cli(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_preview_returns_the_draft_result_while_query_serves_the_old_definition(served, capsys):
    _edit(served, EDITED)
    _validate(served)
    base = ["--json", "--project", str(served)]

    code, out, _ = _run(["preview", "event_count", *base], capsys)
    result = json.loads(out)
    assert code == 0
    assert result["rows"] == [{"event_count": 6}]
    assert result["governed"] is False
    view = draft.status(served)
    assert result["draft_generation"] == view["generation"]
    assert result["draft_revision"] == view["candidate_revision"]
    assert result["served_revision"] == view["served_revision"] is not None

    code, out, _ = _run(["query", "event_count", *base], capsys)
    assert code == 0 and json.loads(out)["rows"] == [{"event_count": 3}]


def test_a_new_source_refuses_before_its_grant_and_previews_after_the_exact_grant(served, capsys):
    write_parquet(served / "data" / "peek.parquet", [(7, "p"), (8, "q")], ["id", "label"])
    entry = authoring_sources.source_entry("data/peek.parquet", name="peek")
    authoring_sources.add_sources(served, None, [entry])
    _edit(served, PEEK, _pin(served))
    argv = ["preview", "event_count", "--json", "--project", str(served)]

    code, out, err = _run(argv, capsys)  # no grant: refused by name, nothing read
    assert code == 1 and out == ""
    assert "peek" in json.loads(err)["error"]["message"]

    view = draft.status(served)
    resolved, digest = authoring_sources.candidate_sources(served, view["candidate_revision"])
    authoring_sources.grant_candidate(
        served,
        draft.proposal_of(served, _pin(served)),
        view["candidate_revision"],
        digest,
        by="human:test",
    )
    _validate(served)  # before any calculation approval
    code, out, _ = _run(argv, capsys)
    assert code == 0
    assert json.loads(out)["rows"] == [{"event_count": 2}]  # the new source's two rows
    assert draft.status(served) is not None  # nothing was approved or served


def test_a_changed_identity_is_refused_and_an_older_binding_is_never_substituted(served, capsys):
    """`events` is served; repointing it at another file is a new identity, not the old one."""
    write_parquet(served / "data" / "other.parquet", [(9, "z")], ["id", "label"])
    doc = yaml.safe_load((served / "ariadne.yaml").read_text(encoding="utf-8"))
    for entry in doc["sources"]:
        if entry["name"] == "events":
            entry["path"] = "data/other.parquet"
    draft.edit_artifact(served, None, "ariadne.yaml", yaml.safe_dump(doc, sort_keys=False))
    code, out, err = _run(["preview", "event_count", "--json", "--project", str(served)], capsys)
    assert code == 1 and out == ""
    assert "events" in json.loads(err)["error"]["message"]


def test_a_stale_or_unvalidated_draft_is_refused(served, capsys, monkeypatch):
    argv = ["preview", "event_count", "--json", "--project", str(served)]
    code, _, err = _run(argv, capsys)  # no draft
    assert code == 1 and "no active draft" in err

    _edit(served, EDITED)
    code, _, err = _run(argv, capsys)  # edited, never validated
    assert code == 1 and "validate" in json.loads(err)["error"]["message"]

    _validate(served)
    monkeypatch.setattr(draft, "_served_revision", lambda _project: "f" * 40)
    code, _, err = _run(argv, capsys)  # the served state advanced
    assert code == 1 and "stale" in json.loads(err)["error"]["message"]


def test_the_compiled_sql_is_authorized_before_binding(served, capsys, monkeypatch):
    from ariadne import authoring, preview

    seen = []
    real = authoring._authorize_statement
    monkeypatch.setattr(
        preview.authoring,
        "_authorize_statement",
        lambda name, sql, approved: (seen.append((sql, set(approved))), real(name, sql, approved)),
    )
    _edit(served, EDITED)
    _validate(served)
    seen.clear()  # validation authorizes too; keep only preview's calls
    assert _run(["preview", "event_count", "--project", str(served), "--json"], capsys)[0] == 0
    assert seen[-1][0] == "SELECT SUM(id) AS event_count FROM (SELECT * FROM events.events)"
    assert seen[-1][1] == {"events", "labels"}

    def refuse(*_a):
        raise ValueError("outside the approved registry")

    monkeypatch.setattr(preview.authoring, "_authorize_statement", refuse)
    code, out, err = _run(["preview", "event_count", "--project", str(served), "--json"], capsys)
    assert code == 1 and out == "" and "approved registry" in err


def test_an_identity_under_a_pending_source_approval_is_refused_before_it_is_read(
    served, capsys, monkeypatch
):
    write_parquet(served / "data" / "peek.parquet", [(7, "p")], ["id", "label"])
    authoring_sources.add_sources(
        served, None, [authoring_sources.source_entry("data/peek.parquet", name="peek")]
    )
    _edit(served, PEEK, _pin(served))
    view = draft.status(served)
    _, digest = authoring_sources.candidate_sources(served, view["candidate_revision"])
    authoring_sources.grant_candidate(
        served,
        draft.proposal_of(served, _pin(served)),
        view["candidate_revision"],
        digest,
        by="human:test",
    )
    _validate(served)
    # the grant exists, but its approval is unfinished: it authorizes nothing (§3.4.2.5)
    monkeypatch.setattr(draft, "source_txn_pending", lambda _project: True)
    monkeypatch.setattr(draft, "recover", lambda _project: None)
    opened = []
    monkeypatch.setattr("ariadne.preview.DuckDBExecution", lambda *a, **k: opened.append(a) or None)
    code, out, err = _run(["preview", "event_count", "--json", "--project", str(served)], capsys)
    assert code == 1 and out == ""
    message = json.loads(err)["error"]["message"]
    assert "in progress or was interrupted" in message and "'peek'" in message
    assert opened == []  # nothing was opened


def _mcp_preview(project, **arguments):
    from tests.mcp_inproc import call

    return call(project, "preview", {"metric": "event_count", **arguments})


def test_an_mcp_predicate_filter_changes_the_aggregate(served):
    _edit(served, EDITED)
    _validate(served)
    label_a = [{"field": "label", "op": "=", "value": "a"}]  # only id 1
    is_error, out = _mcp_preview(served, filters=label_a)
    assert not is_error, out
    assert out["rows"] == [{"events::events.event_count": 1}]  # unfiltered SUM(id) is 6


def _set_mcp_cap(served, cap):
    registry = served / "ariadne.yaml"
    doc = yaml.safe_load(registry.read_text(encoding="utf-8"))
    doc["query"] = {"mcp_response_bytes": cap}
    registry.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def _preview_wire(project, **arguments):
    """The real CallToolResult of one preview call and its wire bytes."""
    import asyncio

    from ariadne.serve import _wire_bytes
    from tests.mcp_inproc import build

    result = asyncio.run(
        build(project).call_tool("preview", {"metric": "event_count", **arguments})
    )
    return result, _wire_bytes(result)


def test_an_mcp_preview_over_the_transport_cap_is_refused(served):
    from ariadne import query_results
    from ariadne.serve import _refusal_envelope_bytes

    cap = max(_refusal_envelope_bytes(f) for f in query_results.refusal_forms())  # smallest usable
    _set_mcp_cap(served, cap)
    many = [(i, f"label-{i:04d}") for i in range(1, 400)]  # one group each: > cap bytes
    write_parquet(served / "data" / "events.parquet", many, ["id", "label"])
    _edit(served, EDITED)
    _validate(served)
    result, size = _preview_wire(served, dimensions=["label"])
    assert result.is_error and size <= cap, (size, cap)
    assert result.structured_content["error"]["exhausted_bound"] == {"mcp_response_bytes": cap}
    # a planner error echoing a long agent-supplied op is bounded by the same cap
    bad = [{"field": "label", "op": "x" * 5000, "value": "a"}]
    result, size = _preview_wire(served, filters=bad)
    assert result.is_error and size <= cap, (size, cap)
    assert result.structured_content["error"]["code"] == "result_byte_limit"


def test_an_mcp_preview_with_an_unrepresentable_cap_is_a_configuration_error(served):
    _set_mcp_cap(served, 700)  # below the largest refusal form on this transport
    _edit(served, EDITED)
    _validate(served)
    is_error, out = _mcp_preview(served, dimensions=["label"])
    assert is_error and "cannot represent every refusal form" in out, out


def test_a_budget_spent_after_the_fetch_refuses(served, capsys, monkeypatch):
    from ariadne import preview, query_results

    now = [0.0]
    real = preview.DeadlineBudget
    monkeypatch.setattr(preview, "DeadlineBudget", lambda s: real(s, clock=lambda: now[0]))
    finalize = query_results.finalize_response

    def slow_finalize(*a, **k):
        finalize(*a, **k)
        now[0] += 10_000  # cleanup/serialization overran the deadline

    monkeypatch.setattr(query_results, "finalize_response", slow_finalize)
    _edit(served, EDITED)
    _validate(served)
    code, out, err = _run(["preview", "event_count", "--json", "--project", str(served)], capsys)
    assert code == 1 and out == ""
    assert json.loads(err)["error"]["code"] == "execution_deadline"
