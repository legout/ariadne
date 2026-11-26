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

from ariadne import authoring_sources, draft, proposals  # noqa: E402
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
    assert view is not None
    return (view["generation"], view["candidate_revision"])


def _edit(project, content, expected=None):
    return draft.edit_artifact(project, expected, MODEL_REL, content)


def _validate(project):
    result = draft.validate(project, _pin(project))
    assert result["ok"] is True, "\n".join(result["errors"])


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
    assert view is not None
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
    assert view is not None
    resolved, digest = authoring_sources.candidate_sources(served, view["candidate_revision"])
    assert digest is not None
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


def _source_change_cli(project, tmp_path, capsys, changes, name="events"):
    edit = tmp_path / "change.json"
    edit.write_text(json.dumps({"kind": "source_change", "name": name, "changes": changes}))
    return _run(["draft", "edit", str(edit), "--json", "--project", str(project)], capsys)


def _candidate_registry(project):
    view = draft.status(project)
    assert view is not None
    proposal = draft.proposal_of(project, (view["generation"], view["candidate_revision"]))
    return yaml.safe_load(proposals.read_artifact(project, proposal, "ariadne.yaml")["content"])


@pytest.mark.parametrize("surface", ["cli", "mcp"])
def test_source_change_stages_only_events_and_refuses_ungranted_preview(
    served, tmp_path, capsys, monkeypatch, surface
):
    from tests.mcp_inproc import call

    target = served / "data" / "b" / "events.parquet"
    target.parent.mkdir(parents=True)
    write_parquet(target, [(9, "z")], ["id", "label"])
    before = yaml.safe_load((served / "ariadne.yaml").read_text())
    edit = {"kind": "source_change", "name": "events", "changes": {"path": "data/b/events.parquet"}}
    if surface == "cli":
        code, out, err = _source_change_cli(served, tmp_path, capsys, edit["changes"])
        assert code == 0, out + err
    else:
        is_error, out = call(served, "authoring_edit_proposal", {"edit": edit})
        assert not is_error, out
    after = _candidate_registry(served)
    expected = yaml.safe_load(yaml.safe_dump(before))
    next(s for s in expected["sources"] if s["name"] == "events")["path"] = "data/b/events.parquet"
    assert after == expected
    opened = []
    monkeypatch.setattr("ariadne.preview.DuckDBExecution", lambda *a, **k: opened.append(a))
    code, out, err = _run(["preview", "event_count", "--json", "--project", str(served)], capsys)
    assert code == 1 and out == "" and "events" in json.loads(err)["error"]["message"]
    assert not opened
    code, out, err = _run(["query", "event_count", "--json", "--project", str(served)], capsys)
    assert code == 0, err
    assert json.loads(out)["rows"] == [{"event_count": 3}]


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize(
    ("name", "changes", "reason"),
    [
        ("missing", {"path": "data/b/events.parquet"}, r"(?i)(unknown|no such|not found)"),
        ("events", {}, r"(?i)(empty|no change)"),
        ("events", {"path": "data/events.parquet"}, r"(?i)(unchanged|no change)"),
        *[
            (
                "events",
                {key: value},
                rf"(?i)({key}).*(disallow|unknown|invalid|not allowed)"
                rf"|(?i:disallow|unknown|invalid|not allowed).*{key}",
            )
            for key, value in [
                ("type", "parquet"),
                ("name", "other"),
                ("approved", True),
                ("table", "other"),
                ("read_only", False),
            ]
        ],
        (
            "events",
            {"path": "s3://user:secret@example.com/events.parquet"},
            r"(?i)(credential|secret|password|userinfo)",
        ),
        *[
            ("signed", {"path": url}, r"(?i)credential")
            for url in [
                "https://acct.blob.core.windows.net/c/events.parquet"
                "?sv=2022-11-02&se=2026-12-01&sig=SECRETSIG",
                "https://b.s3.amazonaws.com/events.parquet?X-Amz-Credential=AKIA"
                "&X-Amz-Signature=SECRETSIG",
                "https://storage.googleapis.com/b/events.parquet?GoogleAccessId=a"
                "&X-Goog-Signature=SECRETSIG",
                "https://example.com/events.parquet?access_token=SECRETSIG",
                "https://example.com/events.parquet?token=SECRETSIG",
                "https://example.com/events.parquet?signature=SECRETSIG",
            ]
        ],
        ("sqlite", {"path": "data/other.db", "storage": None}, r"(?i)storage.*not allowed"),
    ],
)
def test_source_change_refusals_leave_state_untouched(
    served, tmp_path, capsys, name, changes, reason, active
):
    import re

    if active:
        _edit(served, EDITED)
    view_before = draft.status(served)
    registry_before = _candidate_registry(served) if active else None
    paths = [draft.DRAFT_REL, Path(".ariadne/source_grants.json"), Path(".ariadne/current.json")]
    before = {p: (served / p).read_bytes() if (served / p).exists() else None for p in paths}
    extra = {  # a declared source of the type the case changes
        "sqlite": {"name": "sqlite", "type": "sqlite", "path": "data/x.db"},
        "signed": {"name": "signed", "type": "parquet", "path": "data/x.parquet", "table": "t"},
    }.get(name)
    if extra:
        doc = yaml.safe_load((served / "ariadne.yaml").read_text(encoding="utf-8"))
        doc["sources"].append(extra)
        draft.edit_artifact(
            served,
            _pin(served) if active else None,
            "ariadne.yaml",
            yaml.safe_dump(doc, sort_keys=False),
        )
        view_before = draft.status(served)
        registry_before = _candidate_registry(served)
        before = {p: (served / p).read_bytes() if (served / p).exists() else None for p in paths}
    code, out, err = _source_change_cli(served, tmp_path, capsys, changes, name)
    assert code == 1 and not out
    assert re.search(reason, json.loads(err)["error"]["message"]), err
    assert "SECRETSIG" not in err
    after = {p: (served / p).read_bytes() if (served / p).exists() else None for p in paths}
    assert after == before
    assert draft.status(served) == view_before
    if active or extra:
        assert _candidate_registry(served) == registry_before


def test_a_changed_source_with_an_unresolvable_profile_refuses_naming_the_source(
    served, capsys, monkeypatch
):
    """Spec 0040 §3.4: the refusal names the owning source and keeps the profile reason."""
    monkeypatch.delenv("ARCHIVE_ENDPOINT", raising=False)
    doc = yaml.safe_load((served / "ariadne.yaml").read_text(encoding="utf-8"))
    doc["storages"] = {
        "archive": {
            "type": "s3",
            "access_key_id_env": "ARCHIVE_KEY_ID",
            "secret_access_key_env": "ARCHIVE_SECRET",
            "endpoint_url_env": "ARCHIVE_ENDPOINT",
            "scopes": ["s3://archive/"],
        }
    }
    for entry in doc["sources"]:
        if entry["name"] == "events":
            entry.update(path="s3://archive/events.parquet", storage="archive")
    draft.edit_artifact(served, None, "ariadne.yaml", yaml.safe_dump(doc, sort_keys=False))
    code, out, err = _run(["preview", "event_count", "--json", "--project", str(served)], capsys)
    message = json.loads(err)["error"]["message"]
    assert code == 1 and out == ""
    assert "events" in message and "archive" in message and "ARCHIVE_ENDPOINT" in message


def test_source_change_approval_keeps_query_on_a_until_calculation_approval(
    served, tmp_path, capsys, monkeypatch
):
    import tests.test_approve as approval_tests

    target = served / "data" / "b" / "events.parquet"
    target.parent.mkdir(parents=True)
    write_parquet(target, [(9, "z")], ["id", "label"])
    current = served / ".ariadne/current.json"
    original = current.read_bytes()
    code, out, err = _source_change_cli(served, tmp_path, capsys, {"path": "data/b/events.parquet"})
    assert code == 0, out + err
    outcome, shown = approval_tests._run(served, approval_tests.Tty())
    assert outcome["approved"] == "sources"
    assert "CHANGED source events" in shown and "events.parquet" in shown and "data/b/" in shown
    assert current.read_bytes() == original
    # Open a calculation draft and validate against the new, granted baseline.
    approval_tests._profile_pair(served, tmp_path, monkeypatch)
    api = AuthoringProject(served)
    started = api.start_proposal()
    api.edit_pages_batch(
        started["proposal"], started["candidate_revision"], _policy_edit("Rule B.")
    )
    _validate(served)
    base = ["--json", "--project", str(served)]
    code, out, err = _run(["preview", "event_count", *base], capsys)
    assert code == 0, err
    assert json.loads(out)["rows"] == [{"event_count": 1}] and json.loads(out)["governed"] is False
    code, out, err = _run(["query", "event_count", *base], capsys)
    assert code == 0, err
    assert json.loads(out)["rows"] == [{"event_count": 3}]
    outcome, _ = approval_tests._run(served, approval_tests.Tty())
    assert outcome["approved"] == "calculation"
    code, out, err = _run(["query", "event_count", *base], capsys)
    assert code == 0, err
    assert json.loads(out)["rows"] == [{"event_count": 1}] and json.loads(out)["governed"] is True

    code, out, err = _run(["profile", *base], capsys)
    assert code == 0, err
    events = [source for source in json.loads(out)["sources"] if source["name"] == "events"]
    assert len(events) == 1
    assert list(events[0]["tables"]) == ["events"]
    assert events[0]["tables"]["events"]["row_count"] == 1


@pytest.mark.parametrize("surface", ["add", "sources"])
def test_source_change_duplicate_add_still_refuses(served, tmp_path, capsys, surface):
    current = (served / ".ariadne/current.json").read_bytes()
    base = ["--json", "--project", str(served)]
    if surface == "add":
        argv = ["add", "data/b/events.parquet", "--name", "events", *base]
    else:
        edit = tmp_path / "add.json"
        edit.write_text(
            json.dumps(
                {
                    "kind": "sources",
                    "storages": {},
                    "entries": [
                        {"name": "events", "type": "parquet", "path": "data/b/events.parquet"}
                    ],
                }
            )
        )
        argv = ["draft", "edit", str(edit), *base]
    code, out, err = _run(argv, capsys)
    assert code == 1 and not out
    message = json.loads(err)["error"]["message"].lower()
    assert "events" in message and ("duplicate" in message or "already" in message)
    assert draft.status(served) is None
    assert (served / ".ariadne/current.json").read_bytes() == current


def test_source_change_losing_a_race_refuses_stale(served, tmp_path, capsys, monkeypatch):
    from tests.mcp_inproc import call

    _edit(served, EDITED)
    real_status = draft.status
    winner = []

    def competing_status(project):
        view = real_status(project)
        if not winner:
            winner.append(None)
            error, result = call(
                project,
                "authoring_edit_proposal",
                {
                    "edit": {
                        "kind": "seed_notes",
                        "content": "# winner\n",
                    }
                },
            )
            assert not error, result
            winner[0] = real_status(project)
        return view

    monkeypatch.setattr(draft, "status", competing_status)
    code, out, err = _source_change_cli(served, tmp_path, capsys, {"path": "data/b/events.parquet"})
    assert code == 1 and not out and "stale" in json.loads(err)["error"]["message"].lower()
    assert real_status(served) == winner[0]


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
    assert view is not None
    _, digest = authoring_sources.candidate_sources(served, view["candidate_revision"])
    assert digest is not None
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
    assert isinstance(out, dict)
    assert out["rows"] == [{"events::events.event_count": 1}]  # unfiltered SUM(id) is 6


def test_a_cli_filter_field_op_value_changes_the_preview_aggregate(served, capsys):
    _edit(served, EDITED)
    _validate(served)
    base = ["--json", "--project", str(served)]

    code, out, _ = _run(["preview", "event_count", "--filter", "label = a", *base], capsys)
    assert code == 0, out
    assert list(json.loads(out)["rows"][0].values()) == [1]  # unfiltered SUM(id) is 6


def test_a_cli_filter_changes_the_query_aggregate(tmp_path, capsys):
    from tests.test_data_signals import _admit_multifact_project

    _runtime, project, *_ = _admit_multifact_project(tmp_path, quality=False)
    base = ["--json", "--project", str(project)]
    code, out, _ = _run(["query", "live_orders_total", *base], capsys)
    assert code == 0, out
    assert list(json.loads(out)["rows"][0].values()) == [700.0]  # NA 300 + EMEA 400

    code, out, err = _run(["query", "live_orders_total", "--filter", "region = NA", *base], capsys)
    assert code == 0, out + err
    assert list(json.loads(out)["rows"][0].values()) == [300.0]


def test_an_unfiltered_cross_fact_metric_answers_through_the_cli_query(tmp_path, capsys):
    from tests.test_data_signals import _admit_multifact_project

    _runtime, project, *_ = _admit_multifact_project(tmp_path, quality=False)
    base = ["--json", "--project", str(project)]
    code, out, err = _run(["query", "combined_orders_total", *base], capsys)
    assert code == 0, out + err
    assert list(json.loads(out)["rows"][0].values()) == [2000.0]  # live 700 + archive 1300


CROSS_FACT = (
    EDITED
    + """\
- name: twin
  source: events.events
  primary_key:
  - id
  fields:
  - name: id
    expression:
      sql: id
  metrics:
  - name: twin_count
    expression:
      sql: COUNT(*)
metrics:
- name: event_ratio
  expression:
    sql: AGG(events.event_count) / AGG(twin.twin_count)
"""
)


def test_an_unfiltered_cross_fact_preview_answers(served, capsys):
    from tests.test_git_authoring import NATIVE_METRIC_PAGE

    _edit(served, CROSS_FACT)
    selector = (served / "context_integration.yaml").read_text(encoding="utf-8")
    one = selector.split("  bindings:\n")[1]
    for name, ref in (("event_ratio", "event_ratio"), ("twin_count", "twin.twin_count")):
        slug = name.replace("_", "-")
        page = (
            NATIVE_METRIC_PAGE.replace("entity:event-count", f"entity:{slug}")
            .replace('title: "event_count"', f'title: "{name}"')
            .replace("title: event_count", f"title: {name}")
            .replace("events.event_count", ref)
        )
        draft.edit_artifact(served, _pin(served), f"knowledge/metrics/{slug}.md", page)
        selector += one.replace("events::events.event_count", f"events::{ref}")
    draft.edit_artifact(served, _pin(served), "context_integration.yaml", selector)
    _validate(served)
    code, out, err = _run(["preview", "event_ratio", "--json", "--project", str(served)], capsys)
    assert code == 0, out + err
    assert list(json.loads(out)["rows"][0].values()) == [2.0]  # SUM(id) 6 / COUNT(*) 3


def test_a_malformed_cli_query_filter_is_refused_before_the_project_opens(tmp_path, capsys):
    argv = ["query", "m", "--filter", "label ~ a", "--json", "--project", str(tmp_path / "nope")]
    code, out, err = _run(argv, capsys)
    assert code != 0
    assert "filter_invalid" in out + err


@pytest.mark.parametrize(
    ("spec", "op", "value"),
    [
        ("n = 3", "=", 3),
        ("n = 2.5", "=", 2.5),
        ("b = true", "=", True),
        ("z = null", "=", None),
        ('label = "a b"', "=", "a b"),
        ("y = [2024]", "=", "[2024]"),
        ("y = NaN", "=", "NaN"),
        ("y = Infinity", "=", "Infinity"),
        ('y = {"a": 1}', "=", '{"a": 1}'),
        ("label in a, 2", "in", ["a", 2]),
        ('label in "Paris, TX",London', "in", ["Paris, TX", "London"]),
        ('label in "null",active', "in", ["null", "active"]),
        ('label in "ACME \\"West, Inc.\\"",London', "in", ['ACME "West, Inc."', "London"]),
        ("n in 1,2.5,x", "in", [1, 2.5, "x"]),
    ],
)
def test_cli_filter_values_are_typed_per_the_spec(spec, op, value):
    from ariadne.cli import _filters

    (predicate,) = _filters([spec])
    assert (predicate["op"], predicate["value"]) == (op, value)


@pytest.mark.parametrize("bad", ["label ~ a", "label=a", "= a", "label ="])
def test_a_malformed_cli_filter_is_refused_as_filter_invalid(served, capsys, bad):
    argv = ["preview", "event_count", "--filter", bad, "--json", "--project", str(served)]
    code, out, err = _run(argv, capsys)
    assert code != 0
    assert "filter_invalid" in out + err


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
    from mcp.types import CallToolResult

    from ariadne import query_results
    from ariadne.serve import _refusal_envelope_bytes

    cap = max(_refusal_envelope_bytes(f) for f in query_results.refusal_forms())  # smallest usable
    _set_mcp_cap(served, cap)
    many = [(i, f"label-{i:04d}") for i in range(1, 400)]  # one group each: > cap bytes
    write_parquet(served / "data" / "events.parquet", many, ["id", "label"])
    _edit(served, EDITED)
    _validate(served)
    result, size = _preview_wire(served, dimensions=["label"])
    assert isinstance(result, CallToolResult)
    assert result.is_error and size <= cap, (size, cap)
    assert result.structured_content["error"]["exhausted_bound"] == {"mcp_response_bytes": cap}
    # a planner error echoing a long agent-supplied op is bounded by the same cap
    bad = [{"field": "label", "op": "x" * 5000, "value": "a"}]
    result, size = _preview_wire(served, filters=bad)
    assert isinstance(result, CallToolResult)
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
