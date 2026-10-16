"""The three MCP tool registrations over one core (issue #38 / G6; spec
2026-10-02-0009 §6, AC7/AC5; ADR-0002's facade decision as amended by
ADR-0016: Analyst, Authoring and Combined registrations are tool-surface
separation, not new auth).

REAL stdio MCP sessions against ``python -m ariadne.serve --project DIR
--toolset analyst|authoring|combined`` launched in temporary Git data
projects: Analyst and Combined register the SAME Query operations (the
established names — governed and ad-hoc queries, multi-fact query/detail,
Answer Examples); Authoring and Combined register the SAME
``authoring_``-prefixed Git authoring contract (start/read/edit/propose
sources/inputs/upload/validate/review, plan §2's Authoring call contract).
Every surface is project-bound at launch: no tool takes a project root or a
credential, no surface registers source approval, artifact admission
(``ariadne-admit``), reconciliation (``ariadne-authoring reconcile``) or
Promotion (all human-only, spec §5/§6), and a direct call to a name the
toolset did not register is refused by the server. A fresh Git project with
no admission yet starts its Authoring/Combined surfaces fine (AC5) while
query tools surface the managed route's missing-admission error; an admitted
project serves Analyst/Combined queries from the pinned snapshot.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
from mcp.client.stdio import (  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
    StdioServerParameters,
    stdio_client,
)

from ariadne.authoring import AuthoringProject  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    POLICY_PAGE,
    complete_bundle_project,
)

# The Analyst registration: the QueryRuntime operations under their
# established names (spec §6 — including ad-hoc proposals and confirmed
# Answer Examples; never raw SQL execution, never admission).
QUERY_TOOLS = {
    "list_metrics",
    "search_context",
    "get_metric",
    "list_datasets",
    "define_metric",
    "query_metrics",
    "query_detail",
    "query_records",  # S2 (issue #57): the bounded Ad-hoc Record Query
    "save_example",
    "search_examples",
    "resolve_term",  # K2 (issue #42): shared terminology resolution
    "list_context_pages",  # spec 0015 (issue #60): token-free page listing
    "read_context_page",  # spec 0015 (issue #60): path-addressed page reading
    "discover",  # spec 0018 (issue #64): grouped artifact-only discovery
}

# The Authoring registration: the plan §2 Authoring call contract, exposed
# with one stable prefix over the same core (spec §6 "tool-surface
# separation"): proposal lifecycle, measured inputs, validation, the K1
# explicit schema refresh (issue #41), the K3 bounded mapping inspection
# (issue #43), review.
AUTHORING_TOOLS = {
    "authoring_start_proposal",
    "authoring_read_artifact",
    "authoring_edit_proposal",
    "authoring_propose_sources",
    "authoring_inputs",
    "authoring_upload_document",
    "authoring_validate_proposal",
    "authoring_refresh_schema",
    "authoring_inspect_mapping",  # K3 (issue #43): bounded inspection + receipts
    "authoring_resolve_term",  # K2 (issue #42): read-only candidate resolution
    "authoring_review_proposal",
}

# Never a tool on ANY surface (spec §5: admission, source approval,
# reconciliation and Promotion are human-only; the operator runs the local
# commands, ADR-0013). K4 (issue #44) adds the mapping-confirmation marker:
# exact-assertion confirmation rides the human-only ariadne-admit path.
HUMAN_OPERATION_MARKERS = ("approve", "promot", "admit", "reconcil", "confirm")


def _launch(project: Path, toolset: str):
    """A REAL stdio MCP server process for one fixed local project and one
    tool registration (issue #38: the launch selects project AND surface; no
    tool argument ever selects either)."""
    return stdio_client(
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "ariadne.serve", "--project", str(project), "--toolset", toolset],
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
    )


def _text(result) -> str:
    return result.content[0].text


def _payload(result):
    """The tool's JSON payload. MCPServer (mcp 2.x) emits one content block
    per element for list returns — reassemble the list (a string element
    arrives as raw text, so a non-JSON block IS the string element); a single
    block is the value itself. (The established tests/test_authoring_mcp.py
    convention.)"""

    def _element(text: str):
        try:
            return json.loads(text)
        except ValueError:
            return text

    texts = [block.text for block in result.content if hasattr(block, "text")]
    if len(texts) == 1:
        return _element(texts[0])
    return [_element(text) for text in texts]


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config (the established
    Git-suite fixture): repo-local identity only."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


# ------------------------------------------------------- [1] the red anchor


@pytest.mark.parametrize(
    "toolset, expected",
    [
        ("analyst", QUERY_TOOLS),
        ("authoring", AUTHORING_TOOLS),
        ("combined", QUERY_TOOLS | AUTHORING_TOOLS),
    ],
)
def test_stdio_toolsets_share_core_and_exclude_human_operations(tmp_path, toolset, expected):
    """Issue #38 [1]: three ACTUAL stdio sessions — each registration shares
    the same core (Analyst's names are Combined's names; Authoring's prefixed
    contract is Combined's too), each surface is exactly its registration,
    no human-only operation is registered anywhere, no tool argument selects
    a project root or credential, and a DIRECT call to a name the toolset did
    not register is refused by the server."""
    project = complete_bundle_project(tmp_path / "proj")

    async def run() -> dict:
        async with _launch(project, toolset) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                probes = sorted((QUERY_TOOLS | AUTHORING_TOOLS) - expected)[:2]
                refused = {name: await session.call_tool(name, {}) for name in probes}
                return {"tools": tools, "refused": refused}

    out = asyncio.run(run())

    # the registration IS the surface: exactly the toolset's operations
    tools = out["tools"]
    assert set(tools) == expected, (
        f"toolset {toolset!r} registered {sorted(set(tools) ^ expected)} off its surface"
    )

    # no human-only operation is reachable through any registration
    assert not [name for name in tools if any(marker in name for marker in HUMAN_OPERATION_MARKERS)]

    # project-bound: the launch fixed the project; no tool takes a root or a
    # credential argument (the same boundary the combined facade established)
    for name, tool in tools.items():
        properties = set(tool.input_schema.get("properties", {}))
        assert "project" not in properties, name
        assert not {"token", "credential", "credentials", "password"} & properties, name

    # a direct call to an unregistered name is refused by the server — an
    # indirect dispatcher cannot reach the other surface's operations
    for name, result in out["refused"].items():
        assert result.is_error, f"{toolset!r} accepted unregistered {name!r}"
        assert "Unknown tool" in _text(result), name


# ------------------------------------- [2] fresh onboarding vs admitted state


def _admitted_project(tmp_path: Path) -> tuple[Path, dict]:
    """One admitted managed project: the operator's human-only journey
    (approve the candidate's resolved source identity, validate, review,
    ``ariadne-admit --confirm``) performed OUTSIDE every agent surface, with
    the same helpers the G5 admission suite uses."""
    from tests.test_git_admission import admit, admitted_ready

    project = complete_bundle_project(tmp_path / "admitted")
    api = AuthoringProject(project)
    review, _journey = admitted_ready(
        api,
        project,
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, admitted."),
        },
    )
    assert admit(project, review) == 0
    return project, review


def test_stdio_fresh_onboarding_authoring_unblocked_by_missing_admission(tmp_path):
    """AC5 over the wire: a fresh Git project with NO admitted metrics — the
    Authoring registration onboards (starts a proposal, drafts an artifact),
    and on the Combined registration of the very same project the query tools
    return the managed route's missing-admission error WITHOUT blocking
    authoring on that same session."""
    project = complete_bundle_project(tmp_path / "fresh")

    async def run() -> dict:
        out = {}
        # onboarding starts through the Authoring registration: the first
        # Git proposal establishes the project's managed state
        async with _launch(project, "authoring") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["started"] = json.loads(
                    _text(await session.call_tool("authoring_start_proposal", {}))
                )
                out["edited"] = json.loads(
                    _text(
                        await session.call_tool(
                            "authoring_edit_proposal",
                            {
                                "proposal": out["started"]["proposal"],
                                "expected_revision": out["started"]["candidate_revision"],
                                "edit": {
                                    "kind": "page",
                                    "section": "policies",
                                    "name": "all-events-count",
                                    "content": POLICY_PAGE.replace(
                                        "The rule body.", "The rule body, drafted."
                                    ),
                                },
                            },
                        )
                    )
                )
        # the Combined registration of the same not-yet-admitted project:
        # queries refuse with the managed route's explicit error, authoring
        # keeps working beside them
        async with _launch(project, "combined") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["refused"] = await session.call_tool("list_metrics", {})
                out["started_again"] = json.loads(
                    _text(await session.call_tool("authoring_start_proposal", {}))
                )
        return out

    out = asyncio.run(run())

    # the onboarding flow works before any admission (never a governed catalog)
    started = out["started"]
    assert set(started) == {"proposal", "base_revision", "candidate_revision"}
    edited = out["edited"]
    assert edited["changed"] is True
    assert edited["revision"] != started["candidate_revision"]

    # queries refuse with the managed route's explicit missing-admission error
    assert out["refused"].is_error
    assert "no valid admission" in _text(out["refused"])

    # authoring on the SAME combined session is not blocked by that refusal
    assert set(out["started_again"]) == {"proposal", "base_revision", "candidate_revision"}
    assert out["started_again"]["proposal"] != started["proposal"]


def test_stdio_legacy_project_broken_served_model_never_blocks_combined_authoring(tmp_path):
    """Issue #38 criterion 2, the review G6 fix: on a LEGACY (non-managed)
    project a Query construction failure of ANY kind — here a served model
    that is present but does not compile (``COUNT(*)`` mangled to ``COUNT(``,
    the human-seeded draft case fresh onboarding actually hits) — is
    query-only on the Combined registration: the session boots, the query
    tool surfaces the compile error per call, and authoring works in the
    very same session. Spec 0018 revision 2 now requires BOTH query toolsets
    to boot artifact-only: discover succeeds without rendering, while the
    first query tool still returns the existing RuntimeError compile refusal."""
    project = complete_bundle_project(tmp_path / "broken")
    model = project / "semantic_layer" / "models" / "events.yml"
    model.write_text(
        model.read_text(encoding="utf-8").replace("COUNT(*)", "COUNT("),
        encoding="utf-8",
    )
    assert not (project / ".ariadne").exists()  # the legacy route: mutable files

    from ariadne.query import QueryRuntime

    # The unchanged execution constructor is the compile-error identity oracle.
    with pytest.raises(RuntimeError, match="served OSI models.*do not compile") as refusal:
        QueryRuntime(
            project / "semantic_layer",
            project / "context_layer",
            None,
            sources=project / "ariadne.yaml",
        )

    # The CLI launch uses its cwd-relative default rather than this absolute path.
    expected_refusal = str(refusal.value).replace(
        str(project / "semantic_layer" / "models"), "semantic_layer/models"
    )

    async def analyst() -> dict:
        async with _launch(project, "analyst") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                discovery = await session.call_tool("discover", {"query": "event"})
                first_query = await session.call_tool("list_metrics", {})
                return {"discovery": discovery, "refused": first_query}

    analyst_out = asyncio.run(analyst())
    assert not analyst_out["discovery"].is_error
    analyst_groups = json.loads(_text(analyst_out["discovery"]))["groups"]
    assert list(analyst_groups) == ["metrics", "pages", "terms", "examples"]
    assert analyst_groups["metrics"]["items"][0]["name"] == "event_count"
    assert analyst_out["refused"].is_error
    assert _text(analyst_out["refused"]) == f"Error executing tool list_metrics: {expected_refusal}"

    # Combined keeps the original authoring assertions beside the same refusal.
    async def run() -> dict:
        out = {}
        async with _launch(project, "combined") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["discovery"] = await session.call_tool("discover", {"query": "event"})
                out["refused"] = await session.call_tool("list_metrics", {})
                out["started"] = json.loads(
                    _text(await session.call_tool("authoring_start_proposal", {}))
                )
        return out

    out = asyncio.run(run())

    assert out["refused"].is_error
    assert "do not compile" in _text(out["refused"])
    assert set(out["started"]) == {"proposal", "base_revision", "candidate_revision"}
    assert _text(out["refused"]) == f"Error executing tool list_metrics: {expected_refusal}"
    assert not out["discovery"].is_error
    combined_groups = json.loads(_text(out["discovery"]))["groups"]
    assert list(combined_groups) == ["metrics", "pages", "terms", "examples"]


def test_stdio_admitted_project_serves_queries_and_keeps_authoring(tmp_path):
    """The admitted case: Analyst and Combined serve the PINNED admitted
    revision's governed metrics (never the mutable checkout), while the
    Authoring registration still starts new proposals against the same
    project."""
    project, review = _admitted_project(tmp_path)

    async def run() -> dict:
        out = {}
        async with _launch(project, "analyst") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["analyst_metric"] = json.loads(
                    _text(await session.call_tool("get_metric", {"name": "event_count"}))
                )
        async with _launch(project, "combined") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["listed"] = [
                    entry
                    for entry in _payload(await session.call_tool("list_metrics", {}))
                    if isinstance(entry, dict)
                ]
                out["combined_metric"] = json.loads(
                    _text(await session.call_tool("get_metric", {"name": "event_count"}))
                )
                out["started"] = json.loads(
                    _text(await session.call_tool("authoring_start_proposal", {}))
                )
                out["read"] = json.loads(
                    _text(
                        await session.call_tool(
                            "authoring_read_artifact",
                            {
                                "proposal": out["started"]["proposal"],
                                "kind": "page",
                                "section": "policies",
                                "name": "all-events-count",
                            },
                        )
                    )
                )
        return out

    out = asyncio.run(run())

    # both query registrations serve the pinned admitted revision (the hand-
    # computed events fixture value; never the later mutable checkout)
    for key in ("analyst_metric", "combined_metric"):
        assert out[key]["governed"] is True, key
        assert out[key]["rows"] == [{"event_count": 3}], key
        assert out[key]["admission"]["revision"] == review["revision"], key
        assert out[key]["admission"]["route"] == "git-review-admission", key
    assert "event_count" in {entry.get("name") for entry in out["listed"]}

    # the authoring registration still works beside the served state
    started = out["started"]
    assert started["base_revision"] == review["revision"]
    read = out["read"]
    assert read["revision"] == started["candidate_revision"]
    assert "The rule body, admitted." in read["content"]
    assert read["complete"] is True


def test_record_query_discovery(tmp_path):
    """V4-12 (spec 0014 §7, issue #57/S2): the Analyst/Combined registrations
    expose ``query_records`` with an explicit discoverable nested request
    schema — dataset/fields/filters/timestamp/order/limit with defaults,
    supported operators and the overflow policy — so discovery differentiates
    bounded record selection from metric aggregation and admitted detail; the
    Authoring registration gains no query operation. One bounded call over the
    admitted project proves the registered surface; the business cases live in
    ``tests/test_query_records.py`` (not repeated per transport)."""
    project, _review = _admitted_project(tmp_path)

    async def run() -> dict:
        out = {}
        for toolset in ("analyst", "combined", "authoring"):
            async with _launch(project, toolset) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    out[toolset] = {tool.name: tool for tool in (await session.list_tools()).tools}
                    if toolset == "analyst":
                        out["called"] = await session.call_tool(
                            "query_records",
                            {
                                "request": {
                                    "dataset": "events.events",
                                    "fields": ["id", "label"],
                                    "order": [{"field": "id"}],
                                    "limit": 2,
                                }
                            },
                        )
        return out

    out = asyncio.run(run())

    # Analyst and Combined register the tool; Authoring gains no query tool
    assert "query_records" in out["analyst"]
    assert "query_records" in out["combined"]
    assert "query_records" not in out["authoring"]

    # the explicit nested request schema is discoverable (same registration
    # on both query surfaces)
    schema = out["analyst"]["query_records"].input_schema
    assert schema == out["combined"]["query_records"].input_schema
    request_schema = schema["properties"]["request"]
    assert set(request_schema["properties"]) == {
        "dataset",
        "fields",
        "filters",
        "timestamp",
        "order",
        "limit",
    }
    assert request_schema["required"] == ["dataset", "fields", "order"]
    assert request_schema["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "default": 10,
        "description": request_schema["properties"]["limit"]["description"],
    }
    op_enum = request_schema["properties"]["filters"]["items"]["properties"]["op"]["enum"]
    for op in ("=", "!=", "in", "is_null", "is_not_null", "regex"):
        assert op in op_enum
    # ungoverned status and the overflow policy are discoverable in the prose
    prose = json.dumps(schema) + out["analyst"]["query_records"].description
    assert "governed: false" in prose
    assert "overflow" in prose.lower() or "all-or-nothing" in prose

    # one bounded call over the admitted project (its pinned snapshot's
    # events fixture: three rows (1,'a'),(2,'b'),(3,'c'))
    called = out["called"]
    assert not called.is_error
    payload = json.loads(_text(called))
    assert payload["governed"] is False  # a record answer, even on an admitted source
    assert payload["rows"] == [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}]
    assert payload["result"] == {
        "status": "complete",
        "complete": True,
        "scope": "requested_top_n",
        "requested_limit": 2,
        "returned_rows": 2,
        "has_more_matching": True,
    }
    assert payload["provenance"]["route"] == "managed-pinned-admission"


# ------------------------------------- the fixed-toolset console-script entries


def test_console_script_entries_fix_the_toolset(tmp_path, monkeypatch, capsys):
    """``ariadne-analyst-mcp``/``ariadne-authoring-mcp`` are the SAME adapter
    with the registration fixed at the entry point (pyproject console scripts;
    spec §6): the fixed toolset reaches build_app, ``ariadne-serve`` defaults to
    combined, and an explicit ``--toolset`` on a fixed entry is refused — the
    entry IS the choice."""
    import ariadne.serve as serve_module

    project, _review = _admitted_project(tmp_path)
    captured: list = []
    # serve.main chdirs into --project: anchor the process under monkeypatch so
    # the cwd is restored for later tests (the established pattern)
    monkeypatch.chdir(tmp_path)

    class FakeApp:
        def __init__(self, facade, **kwargs):
            captured.append(kwargs.get("toolset"))

        def run(self):
            pass

    monkeypatch.setattr(serve_module, "build_app", FakeApp)
    assert serve_module.main(["--project", str(project)]) == 0
    assert serve_module.analyst_main(["--project", str(project)]) == 0
    assert serve_module.authoring_main(["--project", str(project)]) == 0
    assert captured == ["combined", "analyst", "authoring"]

    for entry, flag in (
        (serve_module.analyst_main, ["--toolset", "authoring"]),
        (serve_module.authoring_main, ["--toolset=analyst"]),
    ):
        captured.clear()
        assert entry(["--project", str(project), *flag]) == 2
        assert captured == []
        assert "fixes --toolset" in capsys.readouterr().err
