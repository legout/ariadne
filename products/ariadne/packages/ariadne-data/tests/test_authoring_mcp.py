"""Local stdio authoring MCP (issue #16's boundary, migrated to the Git
authoring contract by issue #38/G6; spec 2026-10-02-0009 §6, plan §2's
Authoring call contract; ADR-0013), plus issue #18's opt-in LOCAL-ONLY
Streamable HTTP transport (bearer-token gate, loopback binding only).

Real MCP sessions against ``python -m ariadne.serve --project DIR``
launched in temporary projects: the ``authoring_``-prefixed tools are one-line
delegations over the SAME :class:`ariadne.authoring.AuthoringProject` the
``ariadne-authoring`` CLI calls (identical checks and response contracts), no
tool offers source approval or Git Review Admission, the project root is fixed
at server launch (never a tool argument), and no bearer token is involved
locally. The legacy complete-bundle wrappers (``authoring_submit_bundle``/
``authoring_review_bundle``) are gone from every surface; their explicit
replacement is start_proposal + per-artifact edit_proposal +
validate_proposal / review_proposal (see ariadne.serve's migration note). The
staged-bundle and separate Example-review routes are retired.

The HTTP tests (issue #18, LOCAL-ONLY mode per the owner decision 2026-10-03)
launch the REAL ``--http`` server process on a loopback port and talk to it
with the SDK's real ``streamable_http_client`` — the same contract surface as
stdio, behind a bearer token read from the server environment only.
"""

import asyncio
import contextlib
import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402  # pyright: ignore[reportMissingImports] — analysis env
from mcp import ClientSession  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
from mcp.client.stdio import (  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
    StdioServerParameters,
    stdio_client,
)
from mcp.client.streamable_http import (  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
    streamable_http_client,
)

from ariadne.authoring import AuthoringProject  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402 — the shared Git fixtures; no second oracle here
    SEED_NOTES,
    approved,
    complete_bundle_project,
)

# The G6 Authoring registration (spec §6): the plan §2 contract, prefixed —
# plus the K1 explicit schema refresh (issue #41).
AUTHORING_TOOLS = {
    "authoring_read_artifact",
    "authoring_edit_proposal",
    "authoring_inputs",
    "authoring_refresh_schema",
    "authoring_inspect_mapping",
    "authoring_resolve_term",
    "draft_status",
}
QUERY_TOOLS = {
    "list_metrics",
    "search_context",
    "get_metric",
    "list_datasets",
    "define_metric",
}
HUMAN_OPERATION_MARKERS = ("approve", "promot", "admit", "reconcil")


def _launch(project: Path, toolset: str = "combined"):
    """A REAL stdio MCP server process for one fixed local project (issue #16:
    the launch, never a tool argument, selects the project; no token anywhere)."""
    return stdio_client(
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "ariadne.serve", "--project", str(project), "--toolset", toolset],
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
    )


def _payload(result) -> Any:
    """The tool's JSON payload (the CLI's one-JSON-value contract). MCPServer
    (mcp 2.x) emits one content block per element for list returns —
    reassemble the list; a single block is the value itself. A string element
    arrives as raw text, so a non-JSON block IS the string element."""

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


def test_stdio_tool_boundary_authoring_without_approval_or_admission(tmp_path):
    """G6 surface: in a fresh project the stdio server offers Git Authoring
    beside the query tools, but no source-approval or admission tool; no tool
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
    assert "authoring_upload_document" not in tools  # originals stay operator-owned
    assert not [name for name in tools if any(marker in name for marker in HUMAN_OPERATION_MARKERS)]
    for name, tool in tools.items():  # the project root is server-selected only
        assert "project" not in tool.input_schema.get("properties", {}), name
        assert not {"token", "credential", "credentials", "password"} & set(
            tool.input_schema.get("properties", {})
        ), name


def test_stdio_git_journey_matches_core_contracts(tmp_path):
    """Real stdio authoring on the ACTIVE DRAFT (spec 0040 §3.1.3): the first edit opens
    the draft (no start, no proposal ID), a typed source declaration goes through the
    same edit tool, the operator's source grant is the human seam, and operator-placed
    documents are read by reference."""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    policy = "# Revision notes\n\nDrafted over stdio.\n"
    document = project / "data" / "docs" / "revision-notes.md"
    document.write_text(policy, encoding="utf-8")

    async def run() -> dict:
        out: dict = {}
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["no_draft"] = _payload(await session.call_tool("draft_status", {}))
                out["edited"] = _payload(
                    await session.call_tool(
                        "authoring_edit_proposal",
                        {
                            "edit": {
                                "kind": "seed_notes",
                                "content": SEED_NOTES.replace(
                                    "All events count.", "All events count, over stdio."
                                ),
                            }
                        },
                    )
                )
                out["status"] = _payload(await session.call_tool("draft_status", {}))
                # the OPERATOR grants the candidate's resolved source identity (the
                # human seam; no MCP tool can)
                approved(
                    api,
                    project,
                    {
                        "proposal": out["edited"]["proposal"],
                        "candidate_revision": out["edited"]["revision"],
                    },
                )
                out["inputs"] = _payload(
                    await session.call_tool(
                        "authoring_inputs",
                        {"documents": ["revision-notes.md"], "sample_rows": 1},
                    )
                )
                # the library twin AT THE SAME candidate state: full-contract parity
                out["inputs_twin"] = api.inputs(
                    out["edited"]["proposal"],
                    documents=["revision-notes.md"],
                    part=1,
                    sample_rows=1,
                )
        # a session launched AFTER the project became Git-managed pins the
        # managed route: no admission yet, so queries refuse while authoring
        # keeps working (the launch-time route is pinned per process)
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["queries"] = await session.call_tool("list_metrics", {})
        return out

    out = asyncio.run(run())
    assert out["no_draft"] == {"draft": None}
    assert out["edited"]["changed"] is True
    assert out["edited"]["draft"]["generation"] == 1
    assert out["status"]["candidate_revision"] == out["edited"]["revision"]
    assert out["status"]["stale"] is False and out["status"]["validation"] == "unvalidated"

    # same contracts as the library: external document evidence and sampled profile
    assert out["inputs"]["documents"][0]["resource"] == str(document.resolve())
    assert out["inputs"]["documents"][0]["digest"] == hashlib.sha256(policy.encode()).hexdigest()
    assert document.read_text(encoding="utf-8") == policy
    assert not (project / "data" / "object-store").exists()
    twin = out["inputs_twin"]
    assert out["inputs"]["proposal"] == twin["proposal"]
    assert out["inputs"]["revision"] == twin["revision"]
    assert out["inputs"]["sources_digest"] == twin["sources_digest"]
    assert out["inputs"]["seed_notes"] == twin["seed_notes"]
    assert out["inputs"]["documents"] == twin["documents"]
    assert _stable_profile(out["inputs"]["profile"]) == _stable_profile(twin["profile"])
    assert out["inputs"]["profile"] is not None  # the granted source profile
    table = out["inputs"]["profile"]["sources"][0]["tables"]["events"]
    assert table["sampled"] is True and table["sample_limit"] == 1

    # nothing admitted by authoring: the managed route still refuses queries, and no
    # admission descriptor exists
    assert out["queries"].is_error and "no valid admission" in _text(out["queries"])
    assert not (project / ".ariadne" / "current.json").exists()

    assert sorted(p.name for p in (project / "data" / "docs").iterdir()) == [
        "notes.md",
        "revision-notes.md",
    ]


def test_stdio_refresh_schema_matches_core_and_noops_on_identical_retry(tmp_path):
    """K1 (issue #41): the explicit schema refresh is wired through the
    Authoring/Combined MCP registrations with the same envelope the core
    returns — generated page identities, schema-change flags, distinct
    same-named assets — and the identical retry over stdio is a no-op whose
    revision does not move. (The Analyst registration never carries it; the
    toolset parity test pins that surface.)"""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    asset = {"source": "events", "catalog": None, "schema": "events", "table": "events"}

    async def run() -> dict:
        out: dict = {}
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                started = api.start_proposal()  # the draft the operator opened
                approved(api, project, started)
                out["first"] = _payload(
                    await session.call_tool("authoring_refresh_schema", {"assets": [asset]})
                )
                out["second"] = _payload(
                    await session.call_tool("authoring_refresh_schema", {"assets": [asset]})
                )
        return out

    out = asyncio.run(run())
    first = out["first"]
    assert first["changed"] is True
    kinds = {page["kind"] for page in first["pages"]}
    assert kinds == {"table", "dataset"}
    table = next(page for page in first["pages"] if page["kind"] == "table")
    assert table["resource"].startswith("ariadne://table/")
    # a first refresh on a never-documented table reports every column added
    assert table["changes"] == {"added": ["id", "label"], "removed": [], "type_changed": []}
    # the identical retry over stdio is the deterministic no-op
    assert out["second"]["changed"] is False
    assert out["second"]["revision"] == first["revision"]
    retried = next(page for page in out["second"]["pages"] if page["resource"] == table["resource"])
    assert retried["changes"] == {"added": [], "removed": [], "type_changed": []}


def test_stdio_inspect_mapping_returns_the_core_receipt_envelope(tmp_path):
    """K3 (issue #43): the bounded mapping inspection is wired through the
    Authoring/Combined MCP registration with the same receipt envelope the
    core returns to the local CLI — honest counts under the lowered sample
    bound, no raw identifier examples without the operator's sample
    permission, and the retained receipt under the project's evidence area.
    (The Analyst registration never carries it; the toolset parity test pins
    that surface.)"""
    from tests.test_mapping_inspection import approved_project, prefix_candidate

    project, api, started = approved_project(tmp_path / "mcp")
    limits = {"sample_rows": 3}

    async def run() -> dict:
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _payload(
                    await session.call_tool(
                        "authoring_inspect_mapping",
                        {"candidate": prefix_candidate(), "limits": limits},
                    )
                )

    out = asyncio.run(run())
    twin = api.inspect_mapping(
        started["proposal"], started["candidate_revision"], prefix_candidate(), limits=limits
    )
    receipt, twin_receipt = out["receipt"], twin["receipt"]
    assert out["receipt_id"] == receipt["receipt_id"]
    assert receipt["counts"] == twin_receipt["counts"]
    assert receipt["coverage"] == twin_receipt["coverage"]
    assert receipt["unknown_lookup_count"] == twin_receipt["unknown_lookup_count"] == 1
    assert receipt["multiplicity"] == twin_receipt["multiplicity"]
    assert receipt["comparison_basis"] == "containment-only"
    assert receipt["designation"] == "sampled"
    assert out["evidence"] == twin["evidence"] or Path(out["evidence"]).is_file()
    assert "examples" not in receipt  # no sample permission granted
    assert "123123" not in json.dumps(out)


# ------------------- the opt-in LOCAL-ONLY HTTP transport (issue #18) ------
# Owner decision 2026-10-03: implement and test the bearer-token-enforced
# Streamable HTTP transport locally; NEVER expose it. These tests launch the
# REAL ``--http`` server process (loopback only) and speak the SDK's real
# streamable-http client — deployment/exposure and the remote HTTPS smoke
# remain separately owner-approved and are reported UNVERIFIED.

HTTP_TOKEN = "test-bearer-token-0123456789abcdef"
HTTP_TOKEN_ENV = "ARIADNE_HTTP_TOKEN"


def _free_port() -> int:
    """A free loopback TCP port for one test server."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def _launch_http(project: Path, *, token: str | None, extra_args: list[str] | None = None):
    """The REAL opt-in HTTP MCP server process (issue #18): one fixed project,
    loopback-bound, token from the SERVER environment only."""
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    if token is not None:
        env[HTTP_TOKEN_ENV] = token
    else:
        env.pop(HTTP_TOKEN_ENV, None)
    proc = subprocess.Popen(  # noqa: S603 — the repo's own server, fixed argv
        [
            sys.executable,
            "-m",
            "ariadne.serve",
            "--project",
            str(project),
            "--http",
            "--http-port",
            str(port),
            *(extra_args or []),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise AssertionError(
                    f"HTTP server exited rc={proc.returncode}\nstdout: {out}\nstderr: {err}"
                )
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("HTTP server never opened its loopback port")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        assert proc.stdout is not None and proc.stderr is not None
        proc.stdout.close()
        proc.stderr.close()


@contextlib.asynccontextmanager
async def _http_exit(url: str, token: str | None, *, extra_headers: dict | None = None):
    """An SDK streamable-http client with one fixed bearer token (or none)."""
    import httpx2 as httpx  # pyright: ignore[reportMissingImports] — mcp 2.2.0 ships httpx2 (same client API)

    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    headers.update(extra_headers or {})
    async with httpx.AsyncClient(
        headers=headers, timeout=httpx.Timeout(60.0, read=120.0)
    ) as client:
        async with streamable_http_client(url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                yield session


def _describe(exc: BaseException) -> str:
    """Every message in an exception tree (anyio may wrap one in a group)."""
    parts = [f"{type(exc).__name__}: {exc}"]
    if isinstance(exc, BaseExceptionGroup):
        parts.extend(_describe(sub) for sub in exc.exceptions)
    return " | ".join(parts)


def test_http_opt_in_requires_token_and_loopback(tmp_path):
    """S6 red anchor: the HTTP entry point is strictly opt-in — no token in
    the server environment means NO listener (exit 1 with guidance), and the
    local-only mode refuses every non-loopback bind before opening a port."""
    project = tmp_path / "empty"
    project.mkdir()

    # no token: fail fast, no port ever opens
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    env.pop(HTTP_TOKEN_ENV, None)
    proc = subprocess.Popen(  # noqa: S603 — the repo's own server, fixed argv
        [
            sys.executable,
            "-m",
            "ariadne.serve",
            "--project",
            str(project),
            "--http",
            "--http-port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 1
    assert HTTP_TOKEN_ENV in err
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0  # nothing is listening

    # a non-loopback bind is refused: local-only mode, never a public interface
    proc = subprocess.Popen(  # noqa: S603 — the repo's own server, fixed argv
        [
            sys.executable,
            "-m",
            "ariadne.serve",
            "--project",
            str(project),
            "--http",
            "--http-port",
            str(_free_port()),
            "--http-host",
            "0.0.0.0",
        ],
        env={**os.environ, HTTP_TOKEN_ENV: HTTP_TOKEN, "PYTHONPATH": str(REPO_ROOT / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 1
    assert "local-only" in err or "loopback" in err


@pytest.mark.parametrize(
    "toolset,ready_status", [("authoring", 200), ("analyst", 503), ("combined", 503)]
)
def test_container_http_authenticated_health_and_readiness(tmp_path, toolset, ready_status):
    """Compose bind is explicit; probes keep auth and distinguish empty query projects."""
    import httpx2 as httpx  # pyright: ignore[reportMissingImports] — mcp 2.2.0 ships httpx2 (same client API)

    project = tmp_path / "private-empty-project"
    project.mkdir()
    # Managed projects start discovery/authoring before the first admission.
    (project / ".ariadne").mkdir()

    async def discover(url):
        async with _http_exit(
            url,
            HTTP_TOKEN,
            extra_headers={"Host": "ariadne:8000", "Origin": "https://mcp.example.org"},
        ) as session:
            await session.initialize()
            return {tool.name for tool in (await session.list_tools()).tools}

    with _launch_http(
        project,
        token=HTTP_TOKEN,
        extra_args=[
            "--http-container",
            "--http-host",
            "0.0.0.0",
            "--toolset",
            toolset,
            "--http-allowed-host",
            "ariadne:8000",
            "--http-allowed-origin",
            "https://mcp.example.org",
        ],
    ) as url:
        tools = asyncio.run(discover(url))
        assert ("get_metric" in tools) == (toolset != "authoring")
        assert ("authoring_edit_proposal" in tools) == (toolset != "analyst")
        root = url.removesuffix("/mcp")
        with httpx.Client() as client:
            for headers, rejection in (
                ({"Host": "unapproved.example.org"}, 421),
                ({"Origin": "https://unapproved.example.org"}, 403),
            ):
                response = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {HTTP_TOKEN}",
                        "Accept": "application/json, text/event-stream",
                        **headers,
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "rejected-origin-probe", "version": "0"},
                        },
                    },
                )
                assert response.status_code == rejection
            for endpoint, status, body in [
                ("/healthz", 200, {"status": "ok"}),
                (
                    "/readyz",
                    ready_status,
                    {"status": "ready" if ready_status == 200 else "not_ready"},
                ),
            ]:
                for headers in ({}, {"Authorization": "Bearer wrong"}):
                    response = client.get(root + endpoint, headers=headers)
                    assert response.status_code == 401
                    assert response.json() == {"error": "unauthorized"}
                response = client.get(
                    root + endpoint, headers={"Authorization": f"Bearer {HTTP_TOKEN}"}
                )
                assert response.status_code == status
                assert response.json() == body
                assert str(project) not in response.text
    assert not (project / "staging").exists()


def test_http_bearer_gate_refuses_every_request_before_dispatch(tmp_path):
    """Absent/wrong bearer tokens refuse before dispatch with no project data."""
    import httpx2 as httpx  # pyright: ignore[reportMissingImports] — mcp 2.2.0 ships httpx2 (same client API)

    project = tmp_path / "empty"
    project.mkdir()

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"},
        },
    }
    retired_operation = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "authoring_upload_document", "arguments": {}},
    }

    async def probe(url: str) -> list[tuple[str, httpx.Response]]:
        results: list[tuple[str, httpx.Response]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            cases = [
                ("initialize without token", {"headers": {}}),
                ("initialize wrong token", {"headers": {"Authorization": "Bearer wrong"}}),
                ("retired tool without token", {"headers": {}}),
                ("retired tool with wrong token", {"headers": {"Authorization": "Bearer nope"}}),
            ]
            for label, kw in cases:
                body = retired_operation if "retired tool" in label else initialize
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    **kw["headers"],
                }
                response = await client.post(url, json=body, headers=headers)
                results.append((label, response))
            response = await client.get(url, headers={"Accept": "text/event-stream"})
            results.append(("GET stream without token", response))
        return results

    async def sdk_without_token(url: str) -> None:
        with pytest.raises(BaseException) as caught:
            async with _http_exit(url, None) as session:
                await session.initialize()
                await session.list_tools()
        # mcp 2.2.0's client wraps the gate's 401 in a generic MCPError (the
        # HTTP status no longer reaches the exception text); the raw probes
        # above pin the exact 401 status and the fixed rejection body
        assert "MCPError" in _describe(caught.value)

    async def sdk_wrong_token(url: str) -> None:
        with pytest.raises(BaseException) as caught:
            async with _http_exit(url, "wrong-token") as session:
                await session.initialize()
        assert "MCPError" in _describe(caught.value)

    with _launch_http(project, token=HTTP_TOKEN) as url:
        responses = asyncio.run(probe(url))
        asyncio.run(sdk_without_token(url))
        asyncio.run(sdk_wrong_token(url))

    for label, response in responses:
        assert response.status_code == 401, label
        assert response.json() == {"error": "unauthorized"}, label
        assert str(project) not in response.text, label
    # the refused retired-tool dispatch wrote nothing to the project
    assert not (project / "data" / "docs").exists()


def test_http_authenticated_journey_matches_stdio_contracts(tmp_path):
    """Authenticated HTTP mirrors stdio and reads external originals by reference."""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    policy = "# Revision notes\n\nDrafted over HTTP.\n"
    document = project / "data" / "docs" / "revision-notes.md"
    document.write_text(policy, encoding="utf-8")

    async def run(url: str) -> dict:
        out: dict = {}
        async with _http_exit(url, HTTP_TOKEN) as session:
            await session.initialize()
            out["tools"] = {tool.name for tool in (await session.list_tools()).tools}
            out["edited"] = _payload(
                await session.call_tool(
                    "authoring_edit_proposal",
                    {
                        "edit": {
                            "kind": "seed_notes",
                            "content": SEED_NOTES.replace(
                                "All events count.", "All events count, over HTTP."
                            ),
                        }
                    },
                )
            )
            # the OPERATOR grants the resolved source identity (the human seam)
            approved(
                api,
                project,
                {
                    "proposal": out["edited"]["proposal"],
                    "candidate_revision": out["edited"]["revision"],
                },
            )
            out["inputs"] = _payload(
                await session.call_tool(
                    "authoring_inputs",
                    {"documents": ["revision-notes.md"], "sample_rows": 1},
                )
            )
            out["inputs_twin"] = api.inputs(
                out["edited"]["proposal"], documents=["revision-notes.md"], part=1, sample_rows=1
            )
        return out

    with _launch_http(project, token=HTTP_TOKEN) as url:
        out = asyncio.run(run(url))

    # a server relaunched AFTER the project became Git-managed pins the managed
    # route: no admission yet, so queries refuse while authoring keeps working
    # — the launch-time route is pinned per process, exactly as the stdio twin
    async def relaunched() -> Any:
        async with _http_exit(url, HTTP_TOKEN) as session:
            await session.initialize()
            return await session.call_tool("list_metrics", {})

    with _launch_http(project, token=HTTP_TOKEN) as url:
        out["queries"] = asyncio.run(relaunched())

    # the SAME combined surface as stdio — and still no human-only operation
    assert AUTHORING_TOOLS <= out["tools"]
    assert QUERY_TOOLS <= out["tools"]
    assert not [
        name for name in out["tools"] if any(marker in name for marker in HUMAN_OPERATION_MARKERS)
    ]
    assert out["edited"]["changed"] is True
    # identical contracts to the library over the same core
    assert out["inputs"]["documents"][0]["resource"] == str(document.resolve())
    assert out["inputs"]["documents"][0]["digest"] == hashlib.sha256(policy.encode()).hexdigest()
    assert document.read_text(encoding="utf-8") == policy
    assert not (project / "data" / "object-store").exists()
    twin = out["inputs_twin"]
    assert out["inputs"]["revision"] == twin["revision"]
    assert out["inputs"]["seed_notes"] == twin["seed_notes"]
    assert out["inputs"]["documents"] == twin["documents"]
    assert _stable_profile(out["inputs"]["profile"]) == _stable_profile(twin["profile"])
    assert sorted(p.name for p in (project / "data" / "docs").iterdir()) == [
        "notes.md",
        "revision-notes.md",
    ]
    # nothing admitted: the managed route still refuses queries
    assert out["queries"].is_error and "no valid admission" in _text(out["queries"])
    assert not (project / ".ariadne" / "current.json").exists()


def test_stdio_needs_no_token_even_when_http_env_is_set(tmp_path):
    """#18 unchanged-local clause: the token env var is inert without the
    explicit --http flag — stdio initializes and serves with no Authorization
    anywhere (its transport has none)."""
    project = tmp_path / "empty"
    project.mkdir()
    port = _free_port()  # prove the HTTP entry point was NOT taken
    env = {**os.environ, HTTP_TOKEN_ENV: HTTP_TOKEN, "PYTHONPATH": str(REPO_ROOT / "src")}
    server = stdio_client(
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "ariadne.serve", "--project", str(project)],
            env=env,
        )
    )

    async def run() -> list[str]:
        async with server as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return [tool.name for tool in (await session.list_tools()).tools]

    tools = asyncio.run(run())
    assert "authoring_edit_proposal" in tools
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0  # no listener materialized


# --------------------------- spec 0025 (S1): storages forwarding over stdio


def test_stdio_typed_source_edit_forwards_storage_profiles(tmp_path):
    """Spec 0025 §5 / spec 0040 §3.1.3: a typed source declaration goes through
    ``authoring_edit_proposal`` (``authoring_propose_sources`` is removed); the optional
    ``storages`` definitions ride beside the entries and the result equals what the
    shared library returns. Inert data: nothing is granted."""
    project = complete_bundle_project(tmp_path / "proj")
    profiles = {
        "local": {
            "type": "s3",
            "access_key_id_env": "MCP_S3_KEY_ID",
            "secret_access_key_env": "MCP_S3_SECRET",
            "endpoint_url_env": "MCP_S3_ENDPOINT",
            "scopes": ["s3://retail/"],
        }
    }
    entries = [
        {
            "name": "orders",
            "type": "parquet",
            "storage": "local",
            "path": "s3://retail/orders/orders.parquet",
        }
    ]

    async def run() -> dict:
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _payload(
                    await session.call_tool(
                        "authoring_edit_proposal",
                        {"edit": {"kind": "sources", "entries": entries, "storages": profiles}},
                    )
                )

    over_stdio = asyncio.run(run())
    # the library twin: a second project with the identical base resolves identically
    twin_project = complete_bundle_project(tmp_path / "twin")
    from ariadne import authoring_sources

    twin = authoring_sources.add_sources(twin_project, None, entries, profiles)
    assert over_stdio["source_digest"] and over_stdio["draft"]["generation"] == 1
    assert [e["name"] for e in over_stdio["sources"]] == [e["name"] for e in twin["sources"]]
    doc = yaml.safe_load(
        (project / ".ariadne" / "worktrees" / over_stdio["proposal"] / "ariadne.yaml").read_text()
    )
    assert doc["storages"]["local"]["access_key_id_env"] == "MCP_S3_KEY_ID"
    assert doc["sources"][-1]["storage"] == "local"
    assert not (project / ".ariadne" / "source_grants.json").exists()  # nothing granted


def test_the_tool_list_of_every_toolset_has_no_forbidden_tool(tmp_path):
    """AC5 (spec 0040 §3.1.3): no approve, discard, grant, mapping-confirmation,
    propose-sources, validate, review or start tool exists on ANY toolset; B1 added
    `draft_status`."""
    from ariadne.serve import build_app

    forbidden_markers = ("approve", "discard", "grant", "confirm", "admit", "reconcil", "promot")
    removed = {
        "authoring_propose_sources",
        "authoring_start_proposal",
        "authoring_validate_proposal",
        "authoring_review_proposal",
    }
    for toolset in ("combined", "analyst", "authoring"):
        app = build_app(lambda: pytest.fail("registration constructed a runtime"), toolset=toolset)
        tools = {tool.name for tool in asyncio.run(app.list_tools())}
        assert not [t for t in tools if any(m in t for m in forbidden_markers)], toolset
        assert not tools & removed, toolset
        assert ("draft_status" in tools) == (toolset != "analyst")


def test_stdio_draft_status_forwards_the_cleanup_guidance_of_a_journal_remnant(tmp_path):
    """The real stdio MCP `draft_status` forwards the SAME shared message as the CLI. A journal is
    left by an interrupted approval whose three files were never changed (so the restore is a
    no-op); the project's .ariadne directory is read-only, so the journal removal fails and the
    journal remains: the tool error must say what is already safe, what stays refused and why, and
    how to retry."""
    from ariadne import draft, proposals

    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    project = complete_bundle_project(tmp_path / "proj")
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        pass  # the lock files exist beforehand, so a read-only directory can still open them
    with draft.grants_lock(project):
        pass
    draft.begin_source_txn(project)
    state_dir = project / ".ariadne"

    async def run() -> str:
        os.chmod(state_dir, 0o500)  # search + read, no write: the unlink fails, the stat works
        try:
            async with _launch(project) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("draft_status", {})
        finally:
            os.chmod(state_dir, 0o755)
        assert result.is_error, result
        return "".join(getattr(block, "text", "") for block in result.content)

    message = asyncio.run(run())
    assert "durably restored" in message and "no new grant is effective" in message
    assert "grant-backed reads" in message and "journal remains" in message
    assert "ariadne draft status" in message
    assert draft.source_txn_pending(project)  # the remnant is still there; a retry removes it
    assert draft.status(project) is None and not draft.source_txn_pending(project)


_SIGINT_LAUNCHER = """
import os, signal, sys, time
from ariadne import draft
marker = os.environ["ARIADNE_TEST_MARKER"]
want = int(os.environ["ARIADNE_TEST_SIGINTS"])
wait = float(os.environ["ARIADNE_TEST_WAIT"])
pause = float(os.environ["ARIADNE_TEST_PAUSE"])
hold = float(os.environ["ARIADNE_TEST_HOLD"])
pre = float(os.environ["ARIADNE_TEST_PRE"])
keep = os.environ.get("ARIADNE_TEST_NO_RESTORE") == "1"  # a wrapper that outlives the window
nofinally = os.environ.get("ARIADNE_TEST_NO_FINALLY") == "1"  # an unwind that skips the restore
deaf = os.environ.get("ARIADNE_TEST_DEAF") == "1"  # observation never armed: no receipt can exist
state = {"fired": False, "in_window": False, "received": 0, "previous": None, "wrapper": None,
         "closed": False}

def note(name, text=None):
    with open(marker + "." + name, "a") as fh:
        fh.write((name if text is None else text) + chr(10))

def publish(name, text):
    # a result is published EXACTLY once: O_EXCL makes a second publication impossible
    try:
        fd = os.open(marker + "." + name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return
    with os.fdopen(fd, "w") as fh:
        fh.write(text + chr(10))

def restore():
    # idempotent: hand the registration back only if the wrapper is still the installed handler
    if not keep and signal.getsignal(signal.SIGINT) is state["wrapper"]:
        signal.signal(signal.SIGINT, state["previous"])

def close_window():
    if state["closed"]:
        return
    state["closed"] = True
    state["in_window"] = False  # 1. from here nothing counts: a delivery is LATE
    publish("rendezvous", "ok" if state["received"] >= want else "timeout")  # 2. one result
    time.sleep(hold)  # (test hook: a delivery between the result and the disarm)
    note("closed")  # 3. the window is visibly closed ...
    restore()  # 4. ... and only then is the previous handler restored

def arm():
    previous = signal.getsignal(signal.SIGINT)
    state["previous"] = previous
    def wrapper(signum, frame):
        if not state["in_window"]:
            note("late")  # a receipt outside the cleanup window never counts
        else:
            state["received"] += 1
            note("received")
        if callable(previous):
            return previous(signum, frame)  # the server's own handler runs as usual (may raise)
    state["wrapper"] = wrapper
    state["in_window"] = True
    if not deaf:
        signal.signal(signal.SIGINT, wrapper)

def body():
    with open(marker, "w") as fh:  # 2. ... then publish readiness (the pid) ...
        fh.write(str(os.getpid()) + chr(10))
    time.sleep(pause)  # (the former gap: a pause here must not lose a signal)
    deadline = time.monotonic() + wait  # 3. ... then wait
    while time.monotonic() < deadline and state["received"] < want:
        time.sleep(0.02)

def rendezvous():
    if pre:
        note("pre", str(os.getpid()))  # readiness for a signal BEFORE the observation is armed
        time.sleep(pre)
    arm()  # 1. arm the observation ...
    if nofinally:
        body()
        close_window()
    else:
        try:
            body()
        finally:
            close_window()  # on EVERY unwind (also when the Runner raises on a 2nd SIGINT)

def tracer(frame, event, arg):
    if frame.f_code.co_filename != draft.__file__:
        return None
    def local(frame, event, arg):
        if event == "line" and frame.f_code.co_name == "_finish_rollback" and not state["fired"]:
            if frame.f_lineno == int(os.environ["ARIADNE_TEST_LINE"]):
                state["fired"] = True
                rendezvous()
        return local
    return local

sys.settrace(tracer)
import threading; threading.settrace(tracer)
from ariadne import serve
try:
    code = serve.main(["--project", sys.argv[1], "--toolset", "combined"])
finally:
    now = signal.getsignal(signal.SIGINT)
    note("final", "default" if now is signal.default_int_handler else "other:" + repr(now))
raise SystemExit(code)
"""

_FAILING_LAUNCHER = "raise SystemExit(50)"  # a launcher that fails: no server at all


def _restore_sync_line() -> int:
    import ast
    import inspect
    import textwrap

    from ariadne import draft

    src, start = inspect.getsourcelines(draft._finish_rollback)
    tree = ast.parse(textwrap.dedent("".join(src)))
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_fsync_path"
    )
    return call.lineno + start - 1


def _journaled_state(project: Path) -> dict:
    from ariadne import draft

    return {
        rel.name: (project / rel).read_bytes() if (project / rel).exists() else None
        for rel in (draft.GRANTS_REL, draft.BASELINE_REL, draft.DRAFT_REL)
    }


def _disposition(project: Path) -> str:
    """The transaction artifacts on disk: ``"marker"`` (a committed marker), ``"journal"`` (an
    uncommitted journal) or ``"none"``."""
    from ariadne import draft

    if os.path.lexists(project / draft.TXN_COMMITTED_REL):
        return "marker"
    return "journal" if os.path.lexists(project / draft.TXN_REL) else "none"


def _witness(marker: Path, name: str) -> list[str]:
    path = Path(str(marker) + "." + name)
    return path.read_text().split() if path.exists() else []


def _drive_stdio(
    tmp_path: Path,
    sigints: int,
    launcher: str = _SIGINT_LAUNCHER,
    send: str = "now",
    wait: float = 6,
    pause: float = 0,
    hold: float = 0,
    pre: float = 0,
    flags: tuple = (),
) -> dict:
    """Run the REAL stdio server once and return what BOTH sides observed (no oracle here).
    The child ARMS its observation (a wrapper around the server's own SIGINT handler, which is
    still called), THEN publishes readiness (its pid), then waits. The PARENT sends the real
    SIGINT(s). ``send``: ``now`` (inside the window), ``skip``, ``late`` (only after the child
    closed its window), ``cross`` (checks the window is open, is then paused until it closed, then
    sends), ``between`` (after the child published its result, before it disarmed), or ``preinside``
    (one SIGINT before the observation is armed, the rest inside)."""
    import signal

    from ariadne import authoring_sources, draft

    project = complete_bundle_project(tmp_path / "proj")
    before = _journaled_state(project)
    draft.begin_source_txn(project)  # an interrupted approval's journal (the previous bytes)
    # ... which then CHANGED all three journaled files: the rollback has something to restore
    authoring_sources._store_grants(project, [{"source": {"name": "x"}, "by": "human:t", "seq": 1}])
    draft.set_source_baseline(project, "0" * 40)
    (project / draft.DRAFT_REL).write_text(
        json.dumps({"state": "retired", "generation": 99}), encoding="utf-8"
    )
    changed = _journaled_state(project)
    assert all(changed[name] != before[name] for name in before), "the seed must differ"
    marker = tmp_path / "sigint-witness"
    closed, result, pre_marker = (Path(f"{marker}.{n}") for n in ("closed", "rendezvous", "pre"))
    seen: dict = {"initialized": False, "sent": 0, "crossed": False}

    async def until(path: Path, tries: int = 1200) -> bool:
        for _ in range(tries):
            if path.exists() and path.read_text().strip():
                return True
            await asyncio.sleep(0.05)
        return False

    async def kill(pid: int, counted: bool = True) -> None:
        """Send one real SIGINT, then classify from what the PARENT sees afterwards: if the window
        is closed and no in-window receipt covers this send, the send CROSSED the close (it is
        late — not a missing receipt, whatever the earlier open check said)."""
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            seen["gone"] = True
            return
        if not counted:
            return
        seen["sent"] += 1
        await asyncio.sleep(0.3)  # let the child's handler observe it
        if closed.exists() and len(_witness(marker, "received")) < seen["sent"]:
            seen["crossed"] = True

    async def parent_sends() -> None:
        if send == "preinside" and await until(pre_marker):
            await kill(int(pre_marker.read_text().split()[0]), counted=False)  # BEFORE arming
        if not await until(marker):
            return
        pid = int(marker.read_text().split()[0])
        if send == "skip":
            return
        if send == "late":  # sent only once the window has CLOSED
            await until(closed)
        if send == "cross":  # the open check passes, then the parent is paused past the close
            assert not closed.exists(), "the open check must pass before the pause"
            await until(closed)
        if send == "between":  # after the child published its result, before it disarmed
            await until(result)
        for _ in range(sigints - (1 if send == "preinside" else 0)):
            await kill(pid)

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", launcher, str(project)],
            env={
                **os.environ,
                "PYTHONPATH": str(REPO_ROOT / "src"),
                "ARIADNE_TEST_SIGINTS": str(sigints),
                "ARIADNE_TEST_LINE": str(_restore_sync_line()),
                "ARIADNE_TEST_MARKER": str(marker),
                "ARIADNE_TEST_WAIT": str(wait),
                "ARIADNE_TEST_PAUSE": str(pause),
                "ARIADNE_TEST_HOLD": str(hold),
                "ARIADNE_TEST_PRE": str(pre),
                "ARIADNE_TEST_NO_RESTORE": "1" if "no_restore" in flags else "0",
                "ARIADNE_TEST_NO_FINALLY": "1" if "no_finally" in flags else "0",
                "ARIADNE_TEST_DEAF": "1" if "deaf" in flags else "0",
            },
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=60)
                    seen["initialized"] = True  # a precondition of the test
                    sender = asyncio.create_task(parent_sends())
                    try:
                        await asyncio.wait_for(session.call_tool("draft_status", {}), timeout=30)
                    except BaseException:  # the reply MAY be lost: the server was shut down
                        pass
                    finally:
                        await asyncio.wait_for(sender, timeout=60)
        except BaseException:  # the server going away may surface as a closed stream
            pass

    asyncio.run(run())
    return {
        **seen,
        "project": project,
        "before": before,
        "wait": wait,
        "sigints": sigints,
        "marker_exists": marker.exists() and bool(marker.read_text().strip()),
        "rendezvous": _witness(marker, "rendezvous"),
        "received": _witness(marker, "received"),
        "late": _witness(marker, "late"),
        "final": _witness(marker, "final"),
        "after": _journaled_state(project),  # BEFORE any fresh `draft status` could recover
        "pre_disposition": _disposition(project),
    }


def _assert_stdio_observations(obs: dict) -> dict:
    """The oracle. It classifies from what BOTH sides observed, and names the reason: a signal the
    child received outside the window, or a send after which the parent found the window closed
    without an in-window receipt for it, is LATE; a missing receipt is reported only when the
    parent sent inside the window and the child received nothing; a rendezvous that timed out with
    nothing sent is a timeout. Each rendezvous published exactly one result."""
    sigints, wait = obs["sigints"], obs["wait"]
    assert obs["initialized"], "the MCP session must initialize"
    assert obs["marker_exists"], "the child must reach the window"
    assert not (obs["late"] or obs["crossed"]), (
        "the signal was sent LATE: it arrived outside the cleanup window "
        f"(child saw {len(obs['late'])} outside the window, parent crossed the close: "
        f"{obs['crossed']}); this is not a missing receipt"
    )
    assert not obs["final"] or obs["final"] == ["default"], (
        f"the receipt wrapper outlived the window: after serve.main unwound the installed SIGINT "
        f"handler is {obs['final']}, not the default a no-wrapper control leaves"
    )
    assert len(obs["rendezvous"]) == 1, f"a rendezvous must publish ONE result: {obs['rendezvous']}"
    if obs["rendezvous"] == ["timeout"]:
        if obs["sent"] == 0:
            raise AssertionError(
                f"the rendezvous timed out after {wait:g}s waiting for {sigints} receipt(s): "
                "no signal was sent"
            )
        raise AssertionError(
            f"missing receipt: the parent sent {obs['sent']} signal(s) inside the window and the "
            f"child received {len(obs['received'])} (the rendezvous timed out after {wait:g}s)"
        )
    assert obs["rendezvous"] == ["ok"], f"the rendezvous did not complete ({obs['rendezvous']})"
    assert obs["sent"] == sigints, "the parent must have sent the real SIGINT(s)"
    assert obs["received"] == ["received"] * sigints, (
        f"receipts inside the window: {obs['received']}"
    )
    assert obs["final"] == ["default"], (
        f"the receipt wrapper outlived the window: after serve.main unwound the installed SIGINT "
        f"handler is {obs['final']}, not the default a no-wrapper control leaves"
    )
    assert obs["after"] == obs["before"], (
        "the three files must hold their previous (journaled) bytes"
    )
    return {"project": obs["project"], "pre": obs["pre_disposition"]}


def _run_stdio_sigint_case(tmp_path: Path, sigints: int, launcher: str = _SIGINT_LAUNCHER, **kw):
    """Drive the real stdio server and assert the oracle. Nothing is asserted about the interrupted
    tool's reply or about the server's exit (owner decisions)."""
    return _assert_stdio_observations(_drive_stdio(tmp_path, sigints, launcher, **kw))


def _fresh_status(project: Path):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ariadne.cli",
            "draft",
            "status",
            "--json",
            "--project",
            str(project),
        ],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _valid_retry(command: str) -> bool:
    """A retry command validated AS A COMMAND, not as a substring: ``ariadne draft status`` with
    nothing else but an optional ``--project DIR`` whose operand is a path, never another option
    (the CLI rejects ``--project --json``: "expected one argument")."""
    import shlex

    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if parts[:3] != ["ariadne", "draft", "status"]:
        return False
    rest = parts[3:]
    return rest == [] or (len(rest) == 2 and rest[0] == "--project" and not rest[1].startswith("-"))


def _retry_commands(message: str) -> list[str]:
    import re

    return re.findall(r"'(ariadne [^']*)'", message)


_RETAINED_TYPES = ("JournalRemnant", "RestoreUnconfirmed")
_REMOVAL_CLAIMS = ("took effect", "removed", "is gone", "journal is gone")


def _assert_fresh_status(project: Path, done, pre: str) -> None:
    """The fresh `ariadne draft status` reports the REAL outcome, consistent with the pre-retry
    disposition ``pre`` ("none" | "journal" | "marker") AND the actual post-retry artifacts (the
    journal file, the marker file):
    - success (exit 0): the fixture's clean payload ``{"draft": null}``; no journal and no marker
      afterwards;
    - an uncommitted journal retained: a non-zero exit and a truthful retained-rollback result.
      The pending-source-approval JSON needs a NON-EMPTY message that states the pending approval
      or recovery and never claims removal ("took effect", "removed", "journal is gone"), never
      the commit-confirmation phrase, a valid retry command, and the journal on disk.
      ``JournalRemnant``/``RestoreUnconfirmed`` report the journal kept (it must be on disk);
      ``RemovalUnconfirmed`` could not determine which, so it is truthful whether the journal is
      absent or present afterwards; ``RollbackCleanup`` claims removal and is only truthful when
      the journal is really gone. Every retry command in the message must be valid;
    - a committed marker retained: the commit-confirmation JSON with a valid retry command; a
      commit marker for a rollback result is forbidden.
    An unrelated error is not accepted in any state."""
    post = _disposition(project)
    if done.returncode == 0:
        assert json.loads(done.stdout) == {"draft": None}, done.stdout
        assert post == "none", f"a clean result while the artifacts are {post!r}"
        return
    assert pre in ("journal", "marker"), f"an error with nothing pending ({pre!r}): {done.stderr}"
    if done.stdout.strip():
        payload = json.loads(done.stdout)
        assert payload.get("source_approval_pending") is True, done.stdout
        message, command = payload.get("message", ""), payload.get("command", "")
        assert _valid_retry(command), f"not a valid retry command: {command!r}"
        confirmation = "commit could not be confirmed" in message
        if pre == "marker":
            assert confirmation and post == "marker", (pre, post, message)
            return
        # an uncommitted journal: affirmative, state-appropriate pending guidance
        assert not confirmation, "the commit confirmation is forbidden for an uncommitted journal"
        assert post == "journal", f"pending guidance but the journal is {post!r}"
        assert message.strip(), "the pending guidance must not be empty"
        assert "pending" in message.lower() or "recover" in message.lower(), (
            f"the message does not state the pending approval or recovery: {message!r}"
        )
        assert not any(claim in message.lower() for claim in _REMOVAL_CLAIMS), (
            f"pending guidance must not claim removal: {message!r}"
        )
        return
    error = json.loads(done.stderr).get("error", {})
    kind, message = error.get("type"), error.get("message", "")
    assert pre == "journal", f"a rollback result for a {pre!r} state"
    commands = _retry_commands(message)
    assert commands and all(_valid_retry(c) for c in commands), f"retry guidance: {commands}"
    assert "commit could not be confirmed" not in message, "a commit marker for a rollback result"
    if kind == "RollbackCleanup":  # claims the journal was removed: only truthful if it is gone
        assert post == "none", "RollbackCleanup claims removal while the journal is on disk"
    elif kind == "RemovalUnconfirmed":  # could not determine which: truthful both ways
        assert post in ("none", "journal"), f"RemovalUnconfirmed with {post!r}"
    else:
        assert kind in _RETAINED_TYPES, f"not a recovery result: {kind!r}"
        assert post == "journal", f"{kind} reports the journal kept, but it is {post!r}"


@pytest.mark.parametrize("sigints", [1, 2])
def test_stdio_server_sigint_in_the_cleanup_window_leaves_a_consistent_state(tmp_path, sigints):
    """The narrowed MCP-server guarantee (spec 0040 §3.4.2.5): in the real `ariadne serve` stdio
    process a real SIGINT — or two — SENT BY THE PARENT while the child sits in the cleanup window
    reaches the server's OWN handler (Ariadne does not take it over): the server stops serving,
    the reply MAY be lost, but the state is consistent — the three files hold their journaled
    bytes and the journal is removed or kept according to the point reached — and a later
    `ariadne draft status` in a FRESH process reports the real outcome for that state."""
    case = _run_stdio_sigint_case(tmp_path, sigints)
    _assert_fresh_status(case["project"], _fresh_status(case["project"]), case["pre"])


@pytest.mark.parametrize("sigints", [1, 2])
def test_a_child_paused_right_after_readiness_still_receives_the_signal(tmp_path, sigints):
    """The former gap: readiness is published only once observation is armed, so a child paused
    right after publishing it (the old gap before the wrapper existed) still counts the signal."""
    case = _run_stdio_sigint_case(tmp_path, sigints, pause=0.4)
    _assert_fresh_status(case["project"], _fresh_status(case["project"]), case["pre"])


@pytest.mark.parametrize(
    ("what", "launcher", "kwargs", "failure"),
    [
        ("a launcher that fails", _FAILING_LAUNCHER, {}, "MCP session must initialize"),
        (
            "a rendezvous that times out (the signal is skipped although the window is reached)",
            _SIGINT_LAUNCHER,
            {"send": "skip", "wait": 1},
            "rendezvous timed out after 1s .* no signal was sent",
        ),
        (
            "a missing receipt: the parent sent inside the window and the child received nothing",
            _SIGINT_LAUNCHER,
            {"flags": ("deaf",), "wait": 1},
            "missing receipt: the parent sent 1 signal.*received 0",
        ),
        (
            "a sender delayed until after the cleanup",
            _SIGINT_LAUNCHER,
            {"send": "late", "wait": 1},
            "sent LATE",
        ),
        (
            "a sender paused after the parent's open check until .closed exists",
            _SIGINT_LAUNCHER,
            {"send": "cross", "wait": 1},
            "sent LATE",  # not a timeout, not a missing receipt
        ),
        (
            "a delivery between the child's timeout and its disarm",
            _SIGINT_LAUNCHER,
            {"send": "between", "wait": 1, "hold": 1.5},
            "sent LATE",
        ),
        (
            "a wrapper that outlives the window",
            _SIGINT_LAUNCHER,
            {"flags": ("no_restore",)},
            "wrapper outlived the window",
        ),
        (
            "a second SIGINT before the receipt target and no restore on unwind",
            _SIGINT_LAUNCHER,
            {"send": "preinside", "pre": 1.0, "flags": ("no_finally",)},
            "wrapper outlived the window",
        ),
    ],
)
def test_the_stdio_regression_test_cannot_pass_without_a_server_and_a_signal(
    tmp_path, what, launcher, kwargs, failure
):
    """Fail-before of the test itself, each for its OWN named reason: a late or crossing send is
    LATE, a missing receipt is reported only when the parent sent inside the window, a timeout
    with nothing sent is a timeout, and the wrapper must not outlive the window."""
    sigints = 2 if kwargs.get("send") == "preinside" else 1
    with pytest.raises(AssertionError, match=failure):
        _run_stdio_sigint_case(tmp_path, sigints, launcher, **kwargs)


def test_a_delivery_between_the_timeout_and_the_disarm_yields_one_outcome(tmp_path):
    """A delivery after the child published `timeout` but before it disarmed must not produce a
    second result (`ok`) or a counted receipt: exactly ONE outcome, and the named reason."""
    obs = _drive_stdio(tmp_path, 1, send="between", wait=1, hold=1.5)
    assert obs["rendezvous"] == ["timeout"], obs["rendezvous"]  # one outcome, never timeout + ok
    assert obs["received"] == [] and len(obs["late"]) == 1  # the delivery is LATE, uncounted
    with pytest.raises(AssertionError, match="sent LATE"):
        _assert_stdio_observations(obs)


def test_one_sigint_before_arming_and_one_inside_gives_one_receipt_and_the_default_handler(
    tmp_path,
):
    """The handler is restored on EVERY unwind of the rendezvous (a `finally`): one real SIGINT
    before the observation is armed and one inside give ONE receipt, the Runner raises on its
    second SIGINT before the receipt target (two) is met, and the final witness is still
    `default` — not the wrapper. The exception itself propagates as it would without the wrapper."""
    obs = _drive_stdio(tmp_path, 2, send="preinside", pre=1.0)
    assert obs["received"] == ["received"], obs["received"]  # one receipt, in the window
    assert obs["final"] == ["default"], obs["final"]  # restored on the unwind
    assert obs["marker_exists"] and not obs["late"]


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _error(kind: str, message: str) -> str:
    return json.dumps({"error": {"type": kind, "message": message}})


def test_the_fresh_status_check_agrees_with_the_journal(tmp_path, monkeypatch, capsys):
    """The assertion compares the pre-retry disposition with the actual post-retry artifacts and
    requires the outcome and VALID guidance that fit: it rejects the wrong claims and accepts the
    real envelopes."""
    from ariadne import draft, proposals
    from ariadne.cli import main as cli

    def project_with(kind: str, name: str) -> Path:
        project = complete_bundle_project(tmp_path / name)
        if kind in ("journal", "marker"):
            draft.begin_source_txn(project)
        if kind == "marker":
            draft.commit_source_txn(project)
        return project

    journal = project_with("journal", "journal")
    marker = project_with("marker", "marker")
    none = project_with("none", "none")
    retry = "run 'ariadne draft status' in that project"
    confirmation = {
        "source_approval_pending": True,
        "message": "a source approval is pending: its commit could not be confirmed",
        "command": "ariadne draft status",
    }

    # unrelated errors and false claims are rejected
    unrelated = _completed(1, stderr=_error("ValueError", "unrelated"))
    for project, pre in ((journal, "journal"), (marker, "marker"), (none, "none")):
        with pytest.raises(AssertionError):
            _assert_fresh_status(project, unrelated, pre)
    removed = _completed(
        1, stderr=_error("RollbackCleanup", f"the journal removal took effect; {retry}")
    )
    with pytest.raises(AssertionError, match="claims removal"):  # journal removed, but on disk
        _assert_fresh_status(journal, removed, "journal")
    bad_command = dict(confirmation, command="ariadne draft statusX")
    with pytest.raises(AssertionError, match="valid retry command"):
        _assert_fresh_status(marker, _completed(1, json.dumps(bad_command)), "marker")
    with pytest.raises(AssertionError):  # the commit-confirmation JSON for an UNCOMMITTED journal
        _assert_fresh_status(journal, _completed(1, json.dumps(confirmation)), "journal")
    with pytest.raises(AssertionError):  # a clean result while the journal remained
        _assert_fresh_status(journal, _completed(0, '{"draft": null}'), "journal")
    with pytest.raises(AssertionError):  # exit 0 without the clean payload
        _assert_fresh_status(none, _completed(0, "{}"), "none")

    # the right results are accepted
    _assert_fresh_status(none, _completed(0, '{"draft": null}'), "none")
    _assert_fresh_status(marker, _completed(1, json.dumps(confirmation)), "marker")
    pending = dict(confirmation, message="a source approval is pending recovery")
    _assert_fresh_status(journal, _completed(1, json.dumps(pending)), "journal")

    # affirmative, state-appropriate pending guidance for an uncommitted journal on disk
    for message in ("", "   ", "the journal removal took effect", "the journal is gone"):
        with pytest.raises(AssertionError):
            _assert_fresh_status(
                journal,
                _completed(1, json.dumps(dict(confirmation, message=message))),
                "journal",
            )
    # `--project` needs a usable operand (the CLI rejects `--project --json`)
    for command in (
        "ariadne draft status --project --json",
        "ariadne draft status --project",
        "ariadne draft status --json",
    ):
        with pytest.raises(AssertionError, match="valid retry command"):
            _assert_fresh_status(
                marker, _completed(1, json.dumps(dict(confirmation, command=command))), "marker"
            )
    _assert_fresh_status(
        marker,
        _completed(1, json.dumps(dict(confirmation, command="ariadne draft status --project /p"))),
        "marker",
    )
    with pytest.raises(AssertionError):  # a commit marker for a rollback result stays forbidden
        _assert_fresh_status(
            journal,
            _completed(
                1, stderr=_error("RemovalUnconfirmed", f"commit could not be confirmed; {retry}")
            ),
            "journal",
        )

    # a REAL RestoreUnconfirmed envelope (restore sync EIO) with the journal retained is accepted
    real_sync = proposals._fsync_path

    def failing(path):
        if os.path.lexists(journal / draft.TXN_REL):
            raise OSError(5, "restore sync failed")
        return real_sync(path)

    monkeypatch.setattr(proposals, "_fsync_path", failing)
    capsys.readouterr()
    code = cli(["draft", "status", "--json", "--project", str(journal)])
    monkeypatch.undo()
    envelope = capsys.readouterr().err
    assert code == 1 and json.loads(envelope)["error"]["type"] == "RestoreUnconfirmed"
    assert _disposition(journal) == "journal"
    _assert_fresh_status(journal, _completed(1, stderr=envelope), "journal")


def test_a_real_removal_unconfirmed_envelope_is_accepted_with_the_journal_absent_and_retained(
    tmp_path, monkeypatch, capsys
):
    """`RemovalUnconfirmed` could not determine whether the journal is still there: it is truthful
    when the journal is absent afterwards (a successful unlink, a failed removal sync, a failed
    inspection) and when it is retained (a failed unlink and a failed inspection)."""
    from ariadne import draft, proposals
    from ariadne.cli import main as cli

    real_unlink, real_sync, real_lstat = Path.unlink, proposals._fsync_path, os.lstat

    def envelope_for(name: str, unlink_works: bool):
        project = complete_bundle_project(tmp_path / name)
        draft.begin_source_txn(project)
        state = {"unlinked": False}

        def unlink(self, *a, **k):
            if self.name == "source_txn.json" and not unlink_works:
                raise OSError("unlink refused")
            out = real_unlink(self, *a, **k)
            state["unlinked"] = state["unlinked"] or self.name == "source_txn.json"
            return out

        def sync(path):
            if state["unlinked"]:
                raise OSError(5, "removal sync failed")
            return real_sync(path)

        def lstat(path, *a, **k):
            if str(path).endswith("source_txn.json"):
                raise PermissionError(13, "inspection refused")
            return real_lstat(path, *a, **k)

        monkeypatch.setattr(Path, "unlink", unlink)
        monkeypatch.setattr(proposals, "_fsync_path", sync)
        monkeypatch.setattr(os, "lstat", lstat)
        capsys.readouterr()
        code = cli(["draft", "status", "--json", "--project", str(project)])
        monkeypatch.undo()
        err = capsys.readouterr().err
        assert code == 1 and json.loads(err)["error"]["type"] == "RemovalUnconfirmed"
        return project, err

    absent, err = envelope_for("absent", unlink_works=True)
    assert _disposition(absent) == "none"
    _assert_fresh_status(absent, _completed(1, stderr=err), "journal")
    retained, err = envelope_for("retained", unlink_works=False)
    assert _disposition(retained) == "journal"
    _assert_fresh_status(retained, _completed(1, stderr=err), "journal")
