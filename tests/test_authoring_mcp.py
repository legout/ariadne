"""Local stdio authoring MCP (issue #16, validation unit S4; spec
2026-09-24-0005 "Authoring interface and lifecycle" — the LOCAL clauses;
ADR-0013).

Real stdio MCP sessions against ``python -m ariadne.serve --project DIR``
launched in a temp project: the five authoring operations ride the SAME
``ariadne.authoring`` service as ``ariadne-authoring`` (identical checks and
response contracts), no tool offers source approval or Promotion, the project
root is fixed at server launch (never a tool argument), and no bearer token is
involved locally. Query tools keep their existing missing-served-model error
before first Promotion and serve normally after the human promotes.
"""

import asyncio
import base64
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
from mcp.client.stdio import (  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
    StdioServerParameters,
    stdio_client,
)

from ariadne import authoring  # noqa: E402
from ariadne.promote import promote_bundle  # noqa: E402
from tests.test_authoring import (  # noqa: E402
    bundle_submission,
    scaffold_project,
    write_parquet,
    write_proposal,
)

AUTHORING_TOOLS = {
    "authoring_propose_sources",
    "authoring_inputs",
    "authoring_upload_document",
    "authoring_submit_bundle",
    "authoring_review_bundle",
}
QUERY_TOOLS = {
    "list_metrics",
    "search_context",
    "get_metric",
    "list_datasets",
    "define_metric",
}


def _launch(project: Path):
    """A REAL stdio MCP server process for one fixed local project (issue #16:
    the launch, never a tool argument, selects the project; no token anywhere)."""
    return stdio_client(
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "ariadne.serve", "--project", str(project)],
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
    )


def _payload(result) -> Any:
    """The tool's JSON payload (the CLI's one-JSON-value contract). FastMCP
    emits one content block per element for list returns — reassemble the
    list; a single block is the value itself. A string element arrives as raw
    text, so a non-JSON block IS the string element."""

    def _element(text: str) -> Any:
        try:
            return json.loads(text)
        except ValueError:
            return text

    texts = [block.text for block in result.content if hasattr(block, "text")]
    if len(texts) == 1:
        return _element(texts[0])
    return [_element(text) for text in texts]


def _text(result) -> str:
    return result.content[0].text


def _write_json(tmp_path: Path, doc: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _stable_profile(profile: dict) -> dict:
    """Normalize ``top_values`` tie order: equal-count values arrive in
    duckdb's non-deterministic order even between two DIRECT service calls, so
    the contract comparison sorts them."""
    normalized = copy.deepcopy(profile)
    for source in normalized.get("sources", []):
        for table in (source.get("tables") or {}).values():
            for column in (table.get("columns") or {}).values():
                if isinstance(column.get("top_values"), list):
                    column["top_values"] = sorted(
                        column["top_values"],
                        key=lambda entry: (entry.get("count", 0), str(entry.get("value"))),
                    )
    return normalized


def _events_proposal(project: Path) -> list[dict]:
    return [{"name": "events", "type": "parquet", "path": str(project / "data" / "events.parquet")}]


def _approved_project(tmp_path: Path) -> Path:
    """A fresh local project with one parquet source — proposal made, approval
    performed by the OPERATOR (the human seam, never an MCP tool)."""
    project = scaffold_project(tmp_path)
    write_parquet(project / "data" / "events.parquet")
    digest = authoring.propose_sources(
        write_proposal(tmp_path, _events_proposal(project)), project=project
    )["digest"]
    authoring.approve_sources(digest, project=project)
    return project


def test_stdio_tool_boundary_authoring_without_approval_or_promotion(tmp_path):
    """S4 red anchor: in a fresh EMPTY project (no promotion ever) the stdio
    server starts, offers the five authoring operations beside the unchanged
    five query tools, never a source approval or Promotion tool, and no tool
    takes a project root or credential argument."""
    project = tmp_path / "empty"
    project.mkdir()

    async def run() -> dict:
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return {tool.name: tool for tool in (await session.list_tools()).tools}

    tools = asyncio.run(run())
    assert AUTHORING_TOOLS <= set(tools)
    assert QUERY_TOOLS <= set(tools)
    assert not [name for name in tools if "approve" in name or "promot" in name]
    for name, tool in tools.items():  # the project root is server-selected only
        assert "project" not in tool.inputSchema.get("properties", {}), name
        assert not {"token", "credential", "credentials", "password"} & set(
            tool.inputSchema.get("properties", {})
        ), name


def test_stdio_authoring_inputs_supports_bounded_profile(tmp_path):
    """MCP harnesses can request the same sampled approved-source profile as
    the local CLI without claiming keys from an incomplete table."""
    project = _approved_project(tmp_path)

    async def run() -> dict:
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _payload(await session.call_tool("authoring_inputs", {"sample_rows": 1}))

    result = asyncio.run(run())
    table = result["profile"]["sources"][0]["tables"]["events"]
    assert table["row_count"] == 1
    assert table["sampled"] is True and table["sample_limit"] == 1
    assert table["primary_key_candidates"] == table["foreign_key_candidates"] == []


def test_stdio_authoring_journey_matches_cli_contracts(tmp_path):
    """The five authoring operations over real stdio return EXACTLY what the
    shared service returns to the local CLI — propose/inputs/submit/review by
    full-dict equality, upload against its retained-identity contract —
    including the upload bound and document-citation linkage; the reviewed
    bundle stays staged (nothing served before Promotion) while query tools
    keep their existing missing-served-model error."""
    project = scaffold_project(tmp_path)
    write_parquet(project / "data" / "events.parquet")
    proposal_yaml = write_proposal(tmp_path, _events_proposal(project)).read_text(encoding="utf-8")
    policy = "# Pricing policy\n\nUSD is the only billing currency.\n"
    submission = bundle_submission()

    async def run() -> dict:
        out = {}
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["propose"] = _payload(
                    await session.call_tool(
                        "authoring_propose_sources", {"proposal_yaml": proposal_yaml}
                    )
                )
                # the OPERATOR approves (human seam; no MCP tool can)
                authoring.approve_sources(out["propose"]["digest"], project=project)
                out["upload"] = _payload(
                    await session.call_tool(
                        "authoring_upload_document",
                        {
                            "name": "policy.md",
                            "content_b64": base64.b64encode(policy.encode()).decode(),
                        },
                    )
                )
                out["inputs"] = _payload(
                    await session.call_tool("authoring_inputs", {"documents": ["policy.md"]})
                )
                out["submit"] = _payload(
                    await session.call_tool(
                        "authoring_submit_bundle",
                        {"files": submission["files"], "documents": ["policy.md"]},
                    )
                )
                out["review"] = _payload(await session.call_tool("authoring_review_bundle", {}))
                out["queries"] = await session.call_tool("list_metrics", {})
                out["oversize"] = await session.call_tool(
                    "authoring_upload_document",
                    {
                        "name": "big.md",
                        "content_b64": base64.b64encode(
                            b"x" * (authoring.MAX_UPLOAD_BYTES + 1)
                        ).decode(),
                    },
                )
        return out

    out = asyncio.run(run())

    # same contracts as the CLI: full-dict equality with the shared service
    assert out["propose"] == authoring.propose_sources(
        write_proposal(tmp_path, _events_proposal(project), name="twin.yaml"), project=project
    )
    assert out["upload"] == {
        "resource": str((project / "data" / "docs" / "policy.md").resolve()),
        "digest": hashlib.sha256(policy.encode()).hexdigest(),
    }
    twin = authoring.harness_inputs(project=project, documents=["policy.md"])
    assert out["inputs"]["project"] == twin["project"]
    assert out["inputs"]["seed_notes"] == twin["seed_notes"]
    assert out["inputs"]["documents"] == twin["documents"]
    assert _stable_profile(out["inputs"]["profile"]) == _stable_profile(twin["profile"])
    assert out["inputs"]["profile"] is not None  # the approved source profile
    assert out["inputs"]["documents"][0]["resource"] == out["upload"]["resource"]
    # document-citation linkage: submit records the server-verified identity
    # inputs reported — never a client-supplied citation string
    assert out["submit"]["status"] == "validated"
    assert out["submit"]["documents"] == [
        {
            "resource": out["upload"]["resource"],
            "title": "policy.md",
            "digest": out["upload"]["digest"],
        }
    ]
    assert out["submit"] == authoring.submit_bundle(  # idempotent twin: same contract
        _write_json(
            tmp_path,
            {"files": submission["files"], "documents": ["policy.md"]},
            "twin.json",
        ),
        project=project,
    )
    assert out["review"] == authoring.review_bundle(project=project)
    assert out["review"]["digest"] == out["submit"]["review_digest"]
    resources = {entry["resource"] for entry in out["review"]["files"]}
    assert "data/seed_notes.md" in resources
    assert "citations.json" not in resources  # citations surface as `documents`

    # nothing served before Promotion; the bundle stays staged for review
    assert not (project / "semantic_layer").exists()
    assert not (project / "context_layer").exists()
    assert (project / "staging" / "authoring" / "bundle").is_dir()

    # query tools keep their existing missing-served-model behavior
    assert out["queries"].isError and "promote staging" in _text(out["queries"])

    # the upload bound holds over stdio: refused before any write
    assert out["oversize"].isError and "over the" in _text(out["oversize"])
    assert sorted(p.name for p in (project / "data" / "docs").iterdir()) == ["policy.md"]


def test_stdio_query_tools_serve_after_human_promotion(tmp_path):
    """Green clause: after the human promotes the reviewed bundle (the
    operator seam — never an MCP tool), a relaunched stdio server serves the
    original five query tools normally."""
    project = _approved_project(tmp_path)
    submitted = authoring.submit_bundle(
        _write_json(tmp_path, bundle_submission(), "bundle.json"), project=project
    )
    assert submitted["status"] == "validated"
    digest = authoring.review_bundle(project=project)["digest"]
    promote_bundle(
        digest,
        staging_root=project / "staging",
        served_root=project,
        by="human:tester",
        assume_yes=True,
    )

    async def run() -> dict:
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = _payload(await session.call_tool("list_metrics", {}))
                metric = _payload(
                    await session.call_tool(
                        "get_metric", {"name": "event_count", "dimensions": ["label"]}
                    )
                )
                return {"listed": listed, "metric": metric}

    out = asyncio.run(run())
    names = [entry.get("name") for entry in out["listed"] if isinstance(entry, dict)]
    assert "event_count" in names
    assert out["metric"]["governed"] is True
    assert out["metric"]["rows"]
