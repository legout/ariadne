"""Spec 0018: grouped CLI discovery and source-free adapter construction."""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.answer_examples import search_examples  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from ariadne.context import resolve_term, search_pages  # noqa: E402
from tests.test_context_admission import (  # noqa: E402
    admit,
    admitted_candidate,
    order_reference_page,
)
from tests.test_serve import GOLDEN_OSI  # noqa: E402


@pytest.fixture
def artifacts(tmp_path):
    root = tmp_path / "served"
    models = root / "semantic_layer" / "models"
    models.mkdir(parents=True)
    models.joinpath("orders.yml").write_text(
        GOLDEN_OSI.replace("Count of billable orders", "Count of billable order number pairs")
    )
    refs = root / "context_layer" / "references"
    refs.mkdir(parents=True)
    refs.joinpath("order-number.md").write_text(order_reference_page(asserted=False))
    staging = tmp_path / "staging"
    drafts = staging / "context_layer"
    drafts.mkdir(parents=True)
    drafts.joinpath("proposal.md").write_text("# Order number\n\nOrder number draft guidance.\n")
    examples = staging / "answer_examples"
    examples.mkdir()
    examples.joinpath("order-number.md").write_text(
        "---\ntype: answer_example\nquestion: Order number\n"
        "interpretation: Count order number pairs\nstatus: draft\n"
        "method: {operation: get_metric, arguments: {name: order_count}}\n---\n"
    )
    return root, staging


@pytest.fixture
def source_free(monkeypatch):
    import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

    import ariadne.execution as execution
    import ariadne.query as query
    import ariadne.render as render
    import ariadne.validate as validate

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery must not connect, render, execute, or use network")

    monkeypatch.setattr(duckdb, "connect", forbidden)
    monkeypatch.setattr(execution.DuckDBExecution, "__init__", forbidden)
    monkeypatch.setattr(query, "render", forbidden)
    monkeypatch.setattr(render, "render", forbidden)
    monkeypatch.setattr(validate, "render", forbidden)
    monkeypatch.setattr(query.QueryRuntime, "__init__", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def run_search(artifacts, capsys, query, *options):
    root, staging = artifacts
    code = cli(
        [
            "search",
            query,
            "--json",
            "--served",
            str(root),
            "--staging",
            str(staging),
            "--db",
            str(root / "offline.db"),
            *options,
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert not captured.err
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def test_search_native_payloads_and_draft_labels(artifacts, capsys, source_free):
    root, staging = artifacts
    before = {p: p.read_bytes() for base in artifacts for p in base.rglob("*") if p.is_file()}
    report = run_search(artifacts, capsys, "order number")
    groups = report["groups"]
    assert list(groups) == ["metrics", "pages", "terms", "examples"]
    assert groups["metrics"]["items"] == [
        {
            "name": "order_count",
            "description": "Count of billable order number pairs",
            "dimensions": ["order_date", "region", "status"],
        }
    ]
    assert "define_metric" in groups["metrics"]["routing_hint"]
    assert groups["metrics"]["complete"] is True
    assert groups["pages"]["items"] == search_pages(
        "order number", 5, [(root / "context_layer", False), (staging / "context_layer", True)]
    )
    assert any(hit["draft"] for hit in groups["pages"]["items"])
    assert groups["pages"]["completeness"] == "unknown"
    assert groups["terms"]["result"] == resolve_term(
        [(root / "context_layer", False)], "order number"
    )
    terms = groups["terms"]["result"]
    assert len(terms["matches"]) == 2 and terms["ambiguous"]
    assert terms["complete"] and terms["part"] == 1
    assert groups["examples"]["items"] == search_examples(root, staging, "order number", 5)
    assert groups["examples"]["items"][0]["status"] == "draft"
    assert groups["examples"]["completeness"] == "unknown"
    after = {p: p.read_bytes() for base in artifacts for p in base.rglob("*") if p.is_file()}
    assert before == after


def test_search_metric_whole_tokens_order_limit_and_followup(artifacts, capsys, source_free):
    groups = run_search(artifacts, capsys, "USD", "--limit", "1")["groups"]
    # GOLDEN_OSI defines gross_revenue then cogs as USD metrics.
    assert [m["name"] for m in groups["metrics"]["items"]] == ["gross_revenue"]
    assert groups["metrics"]["total_matches"] == 2
    assert groups["metrics"]["complete"] is False
    assert groups["metrics"]["follow_up"] == ["ariadne get-metric gross_revenue"]
    assert run_search(artifacts, capsys, "reven")["groups"]["metrics"]["items"] == []
    assert run_search(artifacts, capsys, "!!!")["groups"]["metrics"]["items"] == []


def test_search_no_matches_missing_optional_examples(artifacts, capsys, source_free):
    for p in (artifacts[1] / "answer_examples").iterdir():
        p.unlink()
    (artifacts[1] / "answer_examples").rmdir()
    groups = run_search(artifacts, capsys, "quux")["groups"]
    assert all(group["status"] == "available" for group in groups.values())
    assert all(groups[k]["items"] == [] for k in ("metrics", "pages", "examples"))
    assert groups["terms"]["result"]["matches"] == []
    assert groups["terms"]["result"]["complete"] is True


def test_search_page_read_failure_is_local(artifacts, capsys, source_free, monkeypatch):
    original = Path.read_text

    def fail_page(path, *args, **kwargs):
        if path.name == "proposal.md":
            raise OSError("selected draft is unreadable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_page)
    groups = run_search(artifacts, capsys, "order number")["groups"]
    assert groups["pages"] == {"status": "unavailable", "reason": "selected draft is unreadable"}
    assert all(groups[k]["status"] == "available" for k in ("metrics", "terms", "examples"))


def test_search_catalog_read_failure_is_local(artifacts, capsys, source_free, monkeypatch):
    root, _ = artifacts
    model = root / "semantic_layer" / "models" / "orders.yml"
    original = Path.read_text

    def fail_model(path, *args, **kwargs):
        if path == model:
            raise PermissionError("fixture denies model YAML")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_model)
    groups = run_search(artifacts, capsys, "order number")["groups"]
    assert list(groups) == ["metrics", "pages", "terms", "examples"]
    assert groups["metrics"]["status"] == "unavailable"
    assert str(model) in groups["metrics"]["reason"]
    assert "fixture denies model YAML" in groups["metrics"]["reason"]
    assert all(groups[k]["status"] == "available" for k in ("pages", "terms", "examples"))
    assert groups["pages"]["items"]
    assert len(groups["terms"]["result"]["matches"]) == 2
    assert len(groups["examples"]["items"]) == 1


def test_search_full_bounded_term_first_part(artifacts, capsys, source_free):
    root, _ = artifacts
    reference = (root / "context_layer" / "references" / "order-number.md").read_text()
    for n in range(11):
        (root / "context_layer" / "references" / f"copy-{n}.md").write_text(reference)
    group = run_search(artifacts, capsys, "order number", "--limit", "1")["groups"]["terms"]
    assert group["result"] == resolve_term([(root / "context_layer", False)], "order number")
    assert len(group["result"]["matches"]) == 20
    assert group["result"]["total_matches"] == 24
    assert group["result"]["truncated"] and not group["result"]["complete"]
    assert group["follow_up"] == "ariadne resolve-term 'order number' --part 2"


def test_search_invalid_or_ambiguous_roots_globally_refuse(
    artifacts, capsys, source_free, monkeypatch
):
    root, _ = artifacts
    monkeypatch.chdir(root)
    inner = root / "served"
    (inner / "context_layer").mkdir(parents=True)
    (inner / "semantic_layer" / "models").mkdir(parents=True)
    assert cli(["search", "order", "--json", "--db", "offline.db"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "ambiguous" in json.loads(captured.err)["error"]["message"]
    assert cli(["search", "order", "--json", "--served", "missing", "--db", "offline.db"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "not a promoted root" in captured.err


def test_managed_context_only_pinned_discovery_and_global_refusals(
    tmp_path, capsys, request, monkeypatch
):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    project, _, review = admitted_candidate(tmp_path, asserted=False)
    assert admit(project, review) == 0
    capsys.readouterr()
    # Mutable root and staging context are not part of managed discovery.
    (project / "context_layer").mkdir(exist_ok=True)
    (project / "context_layer" / "root-draft.md").write_text("# Order number mutable root\n")
    staging = project / "staging" / "context_layer"
    staging.mkdir(parents=True)
    (staging / "draft.md").write_text("# Order number staged draft\n")
    (project / "data" / "orders.parquet").unlink()  # admitted identity is readable, source offline
    request.getfixturevalue("source_free")
    from ariadne.discovery import DiscoveryRuntime

    runtime = DiscoveryRuntime.open_project(project)
    native = asyncio.run(runtime.resolve_term("order number"))
    assert cli(["search", "order number", "--json", "--project", str(project)]) == 0
    groups = json.loads(capsys.readouterr().out)["groups"]
    assert groups["metrics"]["status"] == "unavailable"
    assert "no governed metric catalog" in groups["metrics"]["reason"]
    assert groups["terms"]["result"] == native
    assert native["admission"]["revision"] == review["revision"]
    paths = [hit["path"] for hit in groups["pages"]["items"]]
    assert "root-draft.md" not in paths and "draft.md" not in paths
    assert all(not hit["draft"] for hit in groups["pages"]["items"])
    assert groups["examples"]["items"] == []
    # Admission is a global boundary, including rechecks on a long-lived discovery session.
    runtime.context_dir.joinpath("tampered.md").write_text("# hand-edited snapshot\n")
    with pytest.raises(ValueError, match="pinned snapshot changed"):
        asyncio.run(runtime.discover("order number"))
    assert cli(["search", "order number", "--json", "--project", str(project)]) == 1
    failure = capsys.readouterr()
    assert not failure.out and "snapshot" in failure.err
    assert cli(["search", "order number", "--json", "--project", str(tmp_path / "missing")]) == 1
    failure = capsys.readouterr()
    assert not failure.out and "error" in json.loads(failure.err)


@pytest.mark.parametrize("toolset", ["analyst", "combined", "authoring"])
def test_mcp_registration_startup_and_discover_are_source_free(
    artifacts, source_free, monkeypatch, toolset
):
    from ariadne import serve
    from ariadne.discovery import DiscoveryRuntime

    root, staging = artifacts
    monkeypatch.chdir(root)
    build_app = serve.build_app
    observed = []
    before = {p: p.read_bytes() for base in artifacts for p in base.rglob("*") if p.is_file()}

    class RunningApp:
        def __init__(self, facade, **kwargs):
            self.app = build_app(facade, **kwargs)

        def run(self):
            async def probe():
                tools = {tool.name: tool for tool in await self.app.list_tools()}
                observed.append(tools)
                if toolset != "authoring":
                    observed.append(await self.app.call_tool("discover", {"query": "order number"}))

            asyncio.run(probe())

    monkeypatch.setattr(serve, "build_app", RunningApp)
    assert (
        serve.main(
            [
                "--project",
                str(root),
                "--toolset",
                toolset,
                "--db",
                str(root / "offline.db"),
                "--staging",
                str(staging),
            ]
        )
        == 0
    )
    assert ("discover" in observed[0]) == (toolset != "authoring")
    if toolset != "authoring":
        schema = observed[0]["discover"].input_schema
        assert set(schema["properties"]) == {"query", "limit"}
        assert schema["required"] == ["query"]
        assert schema["properties"]["limit"]["default"] == 5
        # mcp 2.x call_tool returns one CallToolResult; mcp<2 returned a
        # (blocks, structured) tuple or bare block list — handle both shapes
        outcome = observed[1]
        blocks = outcome[0] if isinstance(outcome, tuple) else outcome
        blocks = list(getattr(blocks, "content", blocks))
        result = json.loads(blocks[0].text)
        native = DiscoveryRuntime(
            root / "semantic_layer",
            root / "context_layer",
            root / "offline.db",
            staging_dir=staging,
        )
        assert result == asyncio.run(native.discover("order number"))
    after = {p: p.read_bytes() for base in artifacts for p in base.rglob("*") if p.is_file()}
    assert before == after


def test_search_human_output_keeps_native_labels(artifacts, capsys, source_free):
    root, staging = artifacts
    assert (
        cli(
            [
                "search",
                "order number",
                "--served",
                str(root),
                "--db",
                "offline.db",
                "--staging",
                str(staging),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    headings = [f"{kind} — available" for kind in ("Metrics", "Pages", "Terms", "Examples")]
    positions = [output.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert '"draft": true' in output and '"status": "draft"' in output
    assert '"complete": true' in output and '"context_signals"' in output


def test_deferred_managed_query_keeps_startup_admission_and_refuses_tampering(
    tmp_path, capsys, monkeypatch
):
    from ariadne import serve
    from ariadne.authoring import AuthoringProject
    from ariadne.planner import PlannerError
    from ariadne.query import DeferredQueryRuntime, QueryRuntime
    from tests.test_git_admission import admit as admit_metric
    from tests.test_git_admission import admitted_ready
    from tests.test_mcp_toolsets import _admitted_project

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    project, first = _admitted_project(tmp_path)
    monkeypatch.chdir(project)
    seen = []

    class RunningApp:
        def __init__(self, facade, **kwargs):
            self.facade = facade  # the real serve.main deferred factory

        def run(self):
            facade = self.facade
            assert isinstance(facade, DeferredQueryRuntime)
            discovery = facade.discovery
            assert discovery._managed["commit"] == first["revision"]
            assert asyncio.run(facade.discover("event"))["groups"]["metrics"]["items"]
            # B changes only the admitted expression: the three fixture events now count twice.
            api = AuthoringProject(project)
            content = (project / "semantic_layer" / "models" / "events.yml").read_text()
            second, _ = admitted_ready(
                api,
                project,
                {
                    "kind": "model",
                    "name": "events",
                    "content": content.replace("COUNT(*)", "COUNT(*) * 2"),
                },
            )
            assert admit_metric(project, second) == 0
            assert second["revision"] != first["revision"]
            later = QueryRuntime.open_project(project)
            try:
                fresh = asyncio.run(later.get_metric("event_count"))
                assert fresh["rows"] == [{"event_count": 6}]
                assert fresh["admission"]["revision"] == second["revision"]
            finally:
                later.con.close()
            # The FIRST execution construction in this adapter session still uses A.
            try:
                pinned = asyncio.run(facade.get_metric("event_count"))
                assert pinned["rows"] == [{"event_count": 3}]
                assert pinned["admission"]["revision"] == first["revision"]
                discovery.context_dir.joinpath("tampered.md").write_text("# hand edited A\n")
                with pytest.raises(PlannerError) as refusal:
                    asyncio.run(facade.get_metric("event_count"))
                assert refusal.value.code == "admission_stale"
                # A deferred session that has not opened execution refuses the same changed A.
                unopened = DeferredQueryRuntime(
                    lambda: QueryRuntime.open_project(project, discovery=discovery), discovery
                )
                with pytest.raises(PlannerError) as refusal:
                    asyncio.run(unopened.get_metric("event_count"))
                assert refusal.value.code == "admission_stale"
                unopened.close()
                seen.append(True)
            finally:
                facade.close()

    monkeypatch.setattr(serve, "build_app", RunningApp)
    assert serve.main(["--project", str(project), "--toolset", "analyst"]) == 0
    assert seen == [True]
    capsys.readouterr()  # human admission outputs are fixture setup, not discovery output
