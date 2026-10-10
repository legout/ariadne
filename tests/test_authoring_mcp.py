"""Local stdio authoring MCP (issue #16's boundary, migrated to the Git
authoring contract by issue #38/G6; spec 2026-10-02-0009 §6, plan §2's
Authoring call contract; ADR-0013), plus issue #18's opt-in LOCAL-ONLY
Streamable HTTP transport (bearer-token gate, loopback binding only).

Real MCP sessions against ``python -m ariadne.serve --project DIR``
launched in temporary projects: the ``authoring_``-prefixed tools are one-line
delegations over the SAME :class:`ariadne.authoring.AuthoringProject` the
``ariadne-authoring`` CLI calls (identical checks and response contracts), no
tool offers source approval, admission or Promotion, the project root is fixed
at server launch (never a tool argument), and no bearer token is involved
locally. The legacy complete-bundle wrappers (``authoring_submit_bundle``/
``authoring_review_bundle``) are gone from every surface; their explicit
replacement is start_proposal + per-artifact edit_proposal +
validate_proposal / review_proposal (see ariadne.serve's migration note). The
legacy staged-bundle route itself keeps serving through the local CLI and
through Promotion exactly as before.

The HTTP tests (issue #18, LOCAL-ONLY mode per the owner decision 2026-10-03)
launch the REAL ``--http`` server process on a loopback port and talk to it
with the SDK's real ``streamable_http_client`` — the same contract surface as
stdio, behind a bearer token read from the server environment only.
"""

import asyncio
import base64
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

from mcp import ClientSession  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
from mcp.client.stdio import (  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
    StdioServerParameters,
    stdio_client,
)
from mcp.client.streamable_http import (  # noqa: E402  # pyright: ignore[reportMissingImports] — [mcp] extra
    streamable_http_client,
)

from ariadne import authoring  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_inputs import MAX_UPLOAD_BYTES  # noqa: E402
from ariadne.promote import promote_bundle  # noqa: E402
from tests.test_authoring import (  # noqa: E402
    bundle_submission,
    scaffold_project,
    write_parquet,
    write_proposal,
)
from tests.test_git_authoring import (  # noqa: E402 — the shared Git fixtures; no second oracle here
    POLICY_PAGE,
    approved,
    complete_bundle_project,
)

# The G6 Authoring registration (spec §6): the plan §2 contract, prefixed —
# plus the K1 explicit schema refresh (issue #41).
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
    "authoring_review_proposal",
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
    """S4 red anchor, G6 surface: in a fresh EMPTY project (no promotion ever)
    the stdio server starts, offers the eight Git authoring operations beside
    the unchanged query tools, never a source approval, admission or Promotion
    tool, and no tool takes a project root or credential argument."""
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
    assert not [name for name in tools if any(marker in name for marker in HUMAN_OPERATION_MARKERS)]
    for name, tool in tools.items():  # the project root is server-selected only
        assert "project" not in tool.inputSchema.get("properties", {}), name
        assert not {"token", "credential", "credentials", "password"} & set(
            tool.inputSchema.get("properties", {})
        ), name


def test_stdio_git_journey_matches_core_contracts(tmp_path):
    """The prefixed Git authoring tools over real stdio return EXACTLY what
    the shared AuthoringProject returns to the local CLI — inputs/review by
    full-dict equality, upload against its retained-identity contract —
    including the bounded upload refusal; the proposal stays staged (no
    admission) while the same session's query tools keep the managed route's
    missing-admission error."""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    policy = "# Revision notes\n\nDrafted over stdio.\n"

    async def run() -> dict:
        out: dict = {}
        async with _launch(project) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["started"] = _payload(await session.call_tool("authoring_start_proposal", {}))
                proposal = out["started"]["proposal"]
                revision = out["started"]["candidate_revision"]
                # the OPERATOR approves the candidate's resolved source identity
                # (the human seam; no MCP tool can) — before the first edit, so
                # the approval binds the revision it names
                approved(api, project, out["started"])
                out["edited"] = _payload(
                    await session.call_tool(
                        "authoring_edit_proposal",
                        {
                            "proposal": proposal,
                            "expected_revision": revision,
                            "edit": {
                                "kind": "page",
                                "section": "policies",
                                "name": "all-events-count",
                                "content": POLICY_PAGE.replace(
                                    "The rule body.", "The rule body, over stdio."
                                ),
                            },
                        },
                    )
                )
                out["upload"] = _payload(
                    await session.call_tool(
                        "authoring_upload_document",
                        {
                            "name": "revision-notes.md",
                            "content_b64": base64.b64encode(policy.encode()).decode(),
                        },
                    )
                )
                out["inputs"] = _payload(
                    await session.call_tool(
                        "authoring_inputs",
                        {
                            "proposal": proposal,
                            "documents": ["revision-notes.md"],
                            "sample_rows": 1,
                        },
                    )
                )
                # the CLI twin AT THE SAME candidate state (before validation
                # advances the revision): full-contract parity
                out["inputs_twin"] = api.inputs(
                    proposal,
                    documents=["revision-notes.md"],
                    part=1,
                    sample_rows=1,
                )
                out["validated"] = _payload(
                    await session.call_tool(
                        "authoring_validate_proposal",
                        {"proposal": proposal, "expected_revision": out["edited"]["revision"]},
                    )
                )
                out["review"] = _payload(
                    await session.call_tool("authoring_review_proposal", {"proposal": proposal})
                )
                out["oversize"] = await session.call_tool(
                    "authoring_upload_document",
                    {
                        "name": "big.md",
                        "content_b64": base64.b64encode(b"x" * (MAX_UPLOAD_BYTES + 1)).decode(),
                    },
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
    started = out["started"]
    assert set(started) == {"proposal", "base_revision", "candidate_revision"}
    assert out["edited"]["changed"] is True
    assert out["edited"]["revision"] != started["candidate_revision"]

    # same contracts as the CLI: the upload's retained identity, the bounded
    # sampled profile, and the full review envelope
    assert out["upload"] == {
        "resource": str((project / "data" / "docs" / "revision-notes.md").resolve()),
        "digest": hashlib.sha256(policy.encode()).hexdigest(),
    }
    twin = out["inputs_twin"]
    assert out["inputs"]["proposal"] == twin["proposal"]
    assert out["inputs"]["revision"] == twin["revision"]
    assert out["inputs"]["sources_digest"] == twin["sources_digest"]
    assert out["inputs"]["seed_notes"] == twin["seed_notes"]
    assert out["inputs"]["documents"] == twin["documents"]
    assert _stable_profile(out["inputs"]["profile"]) == _stable_profile(twin["profile"])
    assert out["inputs"]["profile"] is not None  # the approved source profile
    table = out["inputs"]["profile"]["sources"][0]["tables"]["events"]
    assert table["sampled"] is True and table["sample_limit"] == 1
    assert out["inputs"]["documents"][0]["resource"] == out["upload"]["resource"]
    validated = out["validated"]
    assert validated["ok"] is True and validated["errors"] == []
    assert out["review"] == api.review_proposal(started["proposal"])  # full-dict equality
    assert out["review"]["revision"] == validated["revision"]
    assert out["review"]["report"]["ok"] is True

    # nothing admitted by authoring or review: the managed route still refuses
    # queries, and no admission descriptor exists
    assert out["queries"].isError and "no valid admission" in _text(out["queries"])
    assert not (project / ".ariadne" / "current.json").exists()

    # the upload bound holds over stdio: refused before any write
    assert out["oversize"].isError and "over the" in _text(out["oversize"])
    assert sorted(p.name for p in (project / "data" / "docs").iterdir()) == [
        "notes.md",
        "revision-notes.md",
    ]


def test_stdio_legacy_promoted_project_keeps_serving_queries(tmp_path):
    """Green clause (G6 keeps the legacy route): a LEGACY staged-bundle
    project — promoted by the OPERATOR through the unchanged human seam, never
    an MCP tool — still serves the combined facade's query tools normally
    after relaunch; the Git toolset markers never touched this project."""
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
                started = _payload(await session.call_tool("authoring_start_proposal", {}))
                proposal = started["proposal"]
                approved(api, project, started)
                out["first"] = _payload(
                    await session.call_tool(
                        "authoring_refresh_schema",
                        {
                            "proposal": proposal,
                            "expected_revision": started["candidate_revision"],
                            "assets": [asset],
                        },
                    )
                )
                out["second"] = _payload(
                    await session.call_tool(
                        "authoring_refresh_schema",
                        {
                            "proposal": proposal,
                            "expected_revision": out["first"]["revision"],
                            "assets": [asset],
                        },
                    )
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
                        {
                            "proposal": started["proposal"],
                            "expected_revision": started["candidate_revision"],
                            "candidate": prefix_candidate(),
                            "limits": limits,
                        },
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
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    headers.update(extra_headers or {})
    async with httpx.AsyncClient(
        headers=headers, timeout=httpx.Timeout(60.0, read=120.0)
    ) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
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
    import httpx

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
        assert ("authoring_start_proposal" in tools) == (toolset != "analyst")
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
    """S6 red anchor: at the actual HTTP seam an absent or wrong bearer token
    cannot list tools, read, upload, submit or dispatch — including in an
    empty project before any Promotion — and the failures disclose no
    project data (fixed 401 body, no path or tool names)."""
    import httpx

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
    upload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "authoring_upload_document",
            "arguments": {"name": "notes.md", "content_b64": base64.b64encode(b"x").decode()},
        },
    }

    async def probe(url: str) -> list[tuple[str, httpx.Response]]:
        results: list[tuple[str, httpx.Response]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            cases = [
                ("initialize without token", {"headers": {}}),
                ("initialize wrong token", {"headers": {"Authorization": "Bearer wrong"}}),
                ("upload dispatch without token", {"headers": {}}),
                ("upload dispatch wrong token", {"headers": {"Authorization": "Bearer nope"}}),
            ]
            for label, kw in cases:
                body = upload if "dispatch" in label else initialize
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
        assert "401" in _describe(caught.value)

    async def sdk_wrong_token(url: str) -> None:
        with pytest.raises(BaseException) as caught:
            async with _http_exit(url, "wrong-token") as session:
                await session.initialize()
        assert "401" in _describe(caught.value)

    with _launch_http(project, token=HTTP_TOKEN) as url:
        responses = asyncio.run(probe(url))
        asyncio.run(sdk_without_token(url))
        asyncio.run(sdk_wrong_token(url))

    for label, response in responses:
        assert response.status_code == 401, label
        assert response.json() == {"error": "unauthorized"}, label
        assert str(project) not in response.text, label
    # the refused upload dispatch wrote nothing to the project's input area
    assert not (project / "data" / "docs").exists()


def test_http_authenticated_journey_matches_stdio_contracts(tmp_path):
    """S6 green: authenticated HTTP serves the SAME build_app toolsets and
    contracts as stdio — the full Git authoring journey in a project with no
    admission yet (operator approval stays outside the tools), the bounded
    upload refusal, and the managed route's missing-admission query error."""
    project = complete_bundle_project(tmp_path / "proj")
    api = AuthoringProject(project)
    policy = "# Revision notes\n\nDrafted over HTTP.\n"

    async def run(url: str) -> dict:
        out: dict = {}
        async with _http_exit(url, HTTP_TOKEN) as session:
            await session.initialize()
            out["tools"] = {tool.name for tool in (await session.list_tools()).tools}
            out["started"] = _payload(await session.call_tool("authoring_start_proposal", {}))
            proposal = out["started"]["proposal"]
            revision = out["started"]["candidate_revision"]
            # the OPERATOR approves the resolved source identity (the human
            # seam; no MCP tool can) — before the first edit, exactly as stdio
            approved(api, project, out["started"])
            out["edited"] = _payload(
                await session.call_tool(
                    "authoring_edit_proposal",
                    {
                        "proposal": proposal,
                        "expected_revision": revision,
                        "edit": {
                            "kind": "page",
                            "section": "policies",
                            "name": "all-events-count",
                            "content": POLICY_PAGE.replace(
                                "The rule body.", "The rule body, over HTTP."
                            ),
                        },
                    },
                )
            )
            out["upload"] = _payload(
                await session.call_tool(
                    "authoring_upload_document",
                    {
                        "name": "revision-notes.md",
                        "content_b64": base64.b64encode(policy.encode()).decode(),
                    },
                )
            )
            out["inputs"] = _payload(
                await session.call_tool(
                    "authoring_inputs",
                    {"proposal": proposal, "documents": ["revision-notes.md"], "sample_rows": 1},
                )
            )
            out["inputs_twin"] = api.inputs(
                proposal, documents=["revision-notes.md"], part=1, sample_rows=1
            )
            out["validated"] = _payload(
                await session.call_tool(
                    "authoring_validate_proposal",
                    {"proposal": proposal, "expected_revision": out["edited"]["revision"]},
                )
            )
            out["review"] = _payload(
                await session.call_tool("authoring_review_proposal", {"proposal": proposal})
            )
            out["oversize"] = await session.call_tool(
                "authoring_upload_document",
                {
                    "name": "big.md",
                    "content_b64": base64.b64encode(b"x" * (MAX_UPLOAD_BYTES + 1)).decode(),
                },
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
    assert set(out["started"]) == {"proposal", "base_revision", "candidate_revision"}
    assert out["edited"]["changed"] is True
    # identical contracts to the local CLI over the same core
    assert out["upload"] == {
        "resource": str((project / "data" / "docs" / "revision-notes.md").resolve()),
        "digest": hashlib.sha256(policy.encode()).hexdigest(),
    }
    twin = out["inputs_twin"]
    assert out["inputs"]["revision"] == twin["revision"]
    assert out["inputs"]["seed_notes"] == twin["seed_notes"]
    assert out["inputs"]["documents"] == twin["documents"]
    assert _stable_profile(out["inputs"]["profile"]) == _stable_profile(twin["profile"])
    assert out["validated"]["ok"] is True and out["validated"]["errors"] == []
    assert out["review"] == api.review_proposal(out["started"]["proposal"])
    # the upload bound holds over HTTP: refused before any write
    assert out["oversize"].isError and "over the" in _text(out["oversize"])
    assert sorted(p.name for p in (project / "data" / "docs").iterdir()) == [
        "notes.md",
        "revision-notes.md",
    ]
    # nothing admitted: the managed route still refuses queries
    assert out["queries"].isError and "no valid admission" in _text(out["queries"])
    assert not (project / ".ariadne" / "current.json").exists()


def test_http_legacy_promoted_project_keeps_serving_queries(tmp_path):
    """S6 green: after the OPERATOR's Promotion (the unchanged human seam) the
    authenticated HTTP surface serves the same query tools as stdio."""
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

    async def run(url: str) -> dict:
        import httpx

        async with httpx.AsyncClient() as client:
            ready = await client.get(
                url.removesuffix("/mcp") + "/readyz",
                headers={"Authorization": f"Bearer {HTTP_TOKEN}"},
            )
            assert ready.status_code == 200
            assert ready.json() == {"status": "ready"}
        async with _http_exit(url, HTTP_TOKEN) as session:
            await session.initialize()
            listed = _payload(await session.call_tool("list_metrics", {}))
            metric = _payload(
                await session.call_tool(
                    "get_metric", {"name": "event_count", "dimensions": ["label"]}
                )
            )
            return {"listed": listed, "metric": metric}

    with _launch_http(project, token=HTTP_TOKEN) as url:
        out = asyncio.run(run(url))

    names = [entry.get("name") for entry in out["listed"] if isinstance(entry, dict)]
    assert "event_count" in names
    assert out["metric"]["governed"] is True
    assert out["metric"]["rows"]


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
    assert "authoring_start_proposal" in tools
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0  # no listener materialized
