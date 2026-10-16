"""Source-free discovery is project-bound and reads admitted Git snapshots only."""

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

from ariadne.cli import main as cli  # noqa: E402
from ariadne.discovery import DiscoveryRuntime  # noqa: E402
from tests.test_context_admission import admitted_candidate  # noqa: E402
from tests.test_git_authoring import complete_bundle_project  # noqa: E402


def _source_free_guards(monkeypatch):
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
    monkeypatch.setattr(query._QueryRuntimeSession, "__init__", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def test_discovery_refuses_unadmitted_roots_and_ignores_mutable_candidates(
    tmp_path, capsys, monkeypatch
):
    project = complete_bundle_project(tmp_path)
    candidate = project / "staging" / "context_layer"
    candidate.mkdir(parents=True)
    unadmitted = candidate / "unadmitted.md"
    unadmitted.write_text("# NeedleQuartz unadmitted\n", encoding="utf-8")
    (project / "context_layer").mkdir(exist_ok=True)
    mutable_root = project / "context_layer" / "mutable-root.md"
    mutable_root.write_text("# NeedleQuartz mutable root\n", encoding="utf-8")
    unadmitted_bytes = unadmitted.read_bytes()
    mutable_bytes = mutable_root.read_bytes()
    _source_free_guards(monkeypatch)

    discovery = DiscoveryRuntime.open_project(project)
    report = asyncio.run(discovery.discover("NeedleQuartz"))
    assert report["groups"]["pages"]["items"] == []
    assert report["groups"]["examples"]["items"] == []
    assert report["groups"]["metrics"]["status"] == "unavailable"
    assert "no admitted snapshot" in report["groups"]["metrics"]["reason"]
    with pytest.raises(ValueError, match="admission"):
        from ariadne.query import QueryRuntime

        QueryRuntime.open_project(project)

    assert cli(["search", "NeedleQuartz", "--json", "--project", str(project)]) == 0
    groups = json.loads(capsys.readouterr().out)["groups"]
    assert groups["pages"]["items"] == []
    assert unadmitted.read_bytes() == unadmitted_bytes
    assert mutable_root.read_bytes() == mutable_bytes
    with pytest.raises(TypeError, match="DiscoveryRuntime.open_project"):
        DiscoveryRuntime.__new__(
            DiscoveryRuntime, project / "semantic_layer", project / "context_layer", None
        )


def test_admitted_context_only_discovery_pins_snapshot_and_never_reads_sources(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    project, _, review = admitted_candidate(tmp_path, asserted=False)
    from tests.test_context_admission import admit

    assert admit(project, review) == 0
    capsys.readouterr()

    (project / "context_layer").mkdir(exist_ok=True)
    (project / "context_layer" / "root-draft.md").write_text("# Order number mutable root\n")
    staging = project / "staging" / "context_layer"
    staging.mkdir(parents=True)
    (staging / "draft.md").write_text("# Order number staged draft\n")
    (project / "data" / "orders.parquet").unlink()
    _source_free_guards(monkeypatch)

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
    assert groups["examples"]["items"] == []

    runtime.context_dir.joinpath("tampered.md").write_text("# hand-edited snapshot\n")
    with pytest.raises(ValueError, match="pinned snapshot changed"):
        asyncio.run(runtime.discover("order number"))
    assert cli(["search", "order number", "--json", "--project", str(project)]) == 1
    failure = capsys.readouterr()
    assert not failure.out and "snapshot" in failure.err


def test_mcp_discovery_starts_source_free_for_every_registration(tmp_path, monkeypatch):
    from ariadne import serve

    project = complete_bundle_project(tmp_path)
    monkeypatch.chdir(project)
    _source_free_guards(monkeypatch)
    build_app = serve.build_app
    observed = []

    class RunningApp:
        def __init__(self, facade, **kwargs):
            self.app = build_app(facade, **kwargs)

        def run(self):
            async def probe():
                tools = {tool.name: tool for tool in await self.app.list_tools()}
                observed.append(tools)
                if "discover" in tools:
                    result = await self.app.call_tool("discover", {"query": "event"})
                    blocks = list(getattr(result, "content", result))
                    observed.append(json.loads(blocks[0].text))

            asyncio.run(probe())

    monkeypatch.setattr(serve, "build_app", RunningApp)
    for toolset in ("analyst", "combined", "authoring"):
        assert serve.main(["--project", str(project), "--toolset", toolset]) == 0
        tools = observed[-2] if toolset != "authoring" else observed[-1]
        assert ("discover" in tools) == (toolset != "authoring")
        if toolset != "authoring":
            report = observed[-1]
            assert report["groups"]["pages"]["items"] == []
            assert report["groups"]["examples"]["items"] == []
