"""MCP 2.2.0 actual-wire framing over a synthetic Git-admitted project.

Captured JSON-RPC frames and spec 0014's bound semantics are independent
oracles for serialization and response ceilings. The fixture uses only
synthetic project and source data; HTTP boundary behavior is covered elsewhere.
"""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.admission import main as admit_main  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.query import _QueryRuntimeSession  # noqa: E402
from ariadne.query_results import (  # noqa: E402
    cell_limit_refusal,
)  # pyright: ignore[reportMissingImports] — drift
from tests.test_git_authoring import (  # noqa: E402
    approved,
    complete_bundle_project,
    run_git,
)

PROTOCOL_VERSION = "2025-06-18"


def _admit_project(project: Path) -> None:
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["report"]["ok"] is True
    assert (
        admit_main(
            [
                "--project",
                str(project),
                "--proposal",
                review["proposal"],
                "--revision",
                review["revision"],
                "--reviewed-digest",
                review["review_digest"],
                "--confirm",
            ]
        )
        == 0
    )


def _project(root: Path, *, row_count: int = 2, admit: bool = True) -> Path:
    project = complete_bundle_project(root)
    probe_db = project / "data" / "probe.db"
    with sqlite3.connect(probe_db) as con:
        con.execute("CREATE TABLE uni (id INTEGER, txt TEXT)")
        rows = [(1, "é" * 5), (2, "z" * 14)]
        rows.extend((i, f"payload-{i:02d}-" + "t" * 52) for i in range(3, row_count + 1))
        con.executemany("INSERT INTO uni VALUES (?, ?)", rows)

    registry_path = project / "ariadne.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["sources"].append({"name": "probe", "type": "sqlite", "path": "data/probe.db"})
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    run_git(project, "add", "--", "ariadne.yaml")
    run_git(project, "commit", "-q", "-m", "human: add synthetic MCP source", "--", "ariadne.yaml")
    if admit:
        _admit_project(project)
    return project


class _StdioServer:
    """A real ``ariadne.serve`` stdio subprocess driven by RAW JSON-RPC lines,
    so the frames asserted below are the bytes the SDK actually emits."""

    def __init__(self, project: Path):
        self.proc = subprocess.Popen(  # noqa: S603 — the repo's own server, fixed argv
            [sys.executable, "-m", "ariadne.serve", "--project", str(project)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
        self.proc.stdin.flush()

    def _read(self, want_id):
        assert self.proc.stdout is not None
        raw = self.proc.stdout.readline().decode("utf-8").rstrip("\n")
        assert raw, "server closed its stdout"
        frame = json.loads(raw)
        assert frame.get("id") == want_id, frame
        return raw, frame

    def initialize(self, request_id):
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "raw-frame-probe", "version": "0"},
                },
            }
        )
        raw, frame = self._read(request_id)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return raw, frame

    def call_tool(self, request_id, name: str, arguments: dict):
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return self._read(request_id)

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        assert self.proc.stdout is not None and self.proc.stderr is not None
        self.proc.stdout.close()
        self.proc.stderr.close()


def _frame_bytes(call_result, request_id) -> int:
    """The HANDSHAKE-wire serialization chain mcp 2.2.0 actually emits for
    SDK ``initialize`` clients (captured frames): the per-version sieve drops
    the modern ``resultType``/``_meta`` extras, leaving
    ``{content, isError(, structuredContent)}``; the stdio/SSE writers
    serialize the response ``model_dump_json(by_alias=True,
    exclude_unset=True)``. Reconstructing the SDK result model FROM the
    captured frame and re-dumping must reproduce the frame's exact byte
    length (member order differs, length cannot)."""
    from mcp.types import JSONRPCResponse  # pyright: ignore[reportMissingImports] — [mcp] extra

    response = JSONRPCResponse(
        jsonrpc="2.0",
        id=request_id,
        result=call_result.model_dump(by_alias=True, mode="json", exclude_unset=True),
    )
    return len(response.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8"))


def _captured_result_model(frame: dict):
    from mcp.types import CallToolResult  # pyright: ignore[reportMissingImports] — [mcp] extra

    return CallToolResult.model_validate(frame["result"], by_name=False)


@pytest.fixture
def served(tmp_path):
    return _project(tmp_path / "served")


def test_actual_stdio_framing_success_refusal_and_generic_error(served):
    """Success, structured-refusal and generic-error frames captured from a
    real server: each re-serializes through the adapter's accounting chain to
    the frame's exact byte length, the request-ID reserve holds on the wire,
    and the public payload/error semantics are unchanged."""
    from ariadne.serve import _RESERVED_REQUEST_ID, _mcp_result_bytes

    project = served
    uuid_id = "11111111-2222-3333-4444-555555555555"
    with _StdioServer(project) as ok_server:
        ok_server.initialize(0)

        # --- success: the admitted synthetic event count rides the wire ----
        raw, frame = ok_server.call_tool(1, "get_metric", {"name": "event_count"})
        result = frame["result"]
        # the handshake wire: the modern resultType/_meta extras are sieved away
        assert result["isError"] is False and "resultType" not in result
        payload = json.loads(result["content"][0]["text"])
        assert payload["rows"] == [{"event_count": 3}]
        assert len(raw.encode("utf-8")) == _frame_bytes(_captured_result_model(frame), 1)
        assert _mcp_result_bytes(payload) >= len(raw.encode("utf-8"))  # int-id reserve

        # --- the same success with a UUID string id: +37 bytes on the wire --
        raw_uuid, frame_uuid = ok_server.call_tool(uuid_id, "get_metric", {"name": "event_count"})
        assert len(raw_uuid.encode("utf-8")) - len(raw.encode("utf-8")) == 37
        assert len(raw_uuid.encode("utf-8")) == _frame_bytes(
            _captured_result_model(frame_uuid), uuid_id
        )
        # a UUID-string id is the reserved framing worst case: the adapter's
        # measure (the MODERN-era envelope incl. resultType/_meta stamp) is an
        # upper bound over both wires — never below the actual handshake frame
        assert _mcp_result_bytes(payload) >= len(raw_uuid.encode("utf-8"))
        assert _RESERVED_REQUEST_ID != uuid_id  # independent ids, same length class

        # --- unicode cells: escaping counted, never assumed ------------------
        raw_uni, frame_uni = ok_server.call_tool(
            2,
            "query_records",
            {
                "request": {
                    "dataset": "probe.uni",
                    "fields": ["id", "txt"],
                    "order": [{"field": "id"}],
                }
            },
        )
        uni_payload = json.loads(frame_uni["result"]["content"][0]["text"])
        assert [row["txt"] for row in uni_payload["rows"]] == ["é" * 5, "z" * 14]
        assert len(raw_uni.encode("utf-8")) == _frame_bytes(_captured_result_model(frame_uni), 2)
        assert _mcp_result_bytes(uni_payload) >= len(raw_uni.encode("utf-8"))

        # --- structured refusal: isError + BOTH text and structured content --
        # (a declared timestamp over malformed VARCHAR wall times refuses as a
        # QueryResultError — the adapter's structured refusal, not a generic
        # tool error; an unknown dataset instead rides the generic-error path)
        raw_ref, frame_ref = ok_server.call_tool(
            3,
            "query_records",
            {
                "request": {
                    "dataset": "probe.uni",
                    "fields": ["id"],
                    "order": [{"field": "id"}],
                    "timestamp": {
                        "field": "txt",
                        "format": "%Y-%m-%d %H:%M:%S",
                        "timezone": "Europe/Berlin",
                    },
                }
            },
        )
        refusal = frame_ref["result"]
        assert refusal["isError"] is True
        body = refusal["structuredContent"]
        assert body["error"]["code"] and body["result"]["status"] == "refused"
        assert json.loads(refusal["content"][0]["text"]) == body  # text is the same body
        assert len(raw_ref.encode("utf-8")) == _frame_bytes(_captured_result_model(frame_ref), 3)

    with _StdioServer(project) as err_server:
        err_server.initialize(0)
        raw_err, frame_err = err_server.call_tool(4, "get_metric", {"name": "not_a_metric"})
        error = frame_err["result"]
        assert error["isError"] is True
        text = error["content"][0]["text"]
        # the 1.x public semantics: the SDK's verbatim error prefix PLUS the
        # original message (mcp 2.2.0 alone would drop a bare exception's text)
        assert text.startswith("Error executing tool get_metric: ")
        assert "unknown metric" in text
        assert len(raw_err.encode("utf-8")) == _frame_bytes(_captured_result_model(frame_err), 4)


def test_lowered_envelope_refuses_without_writing_and_narrowed_retry_fits(tmp_path):
    """A lowered ceiling refuses whole MCP envelopes without project writes."""

    from mcp.types import CallToolResult, TextContent  # pyright: ignore[reportMissingImports]

    from ariadne.query_results import refusal_forms
    from ariadne.serve import _mcp_result_bytes

    # widen the payload so the envelope clears the refusal floor with margin

    root = _project(tmp_path / "plain", row_count=24, admit=False)

    full_request = {
        "request": {
            "dataset": "probe.uni",
            "fields": ["id", "txt"],
            "order": [{"field": "id"}],
            "limit": 24,
        }
    }
    fitting_core = _QueryRuntimeSession(
        root / "semantic_layer",
        root / "context_layer",
        None,
        sources=str(root / "ariadne.yaml"),
        query_limits={"response_bytes": 65536},
    )
    inner = asyncio.run(fitting_core.query_records(full_request["request"]))
    assert len(inner["rows"]) == 24  # the widened population rides the payload

    def _refusal_modern_bytes(form: dict) -> int:
        # the adapter's isError refusal representation (text + structured
        # duplication) in the MODERN-wire form the serve-side battery measures
        # (exclude_none keeps resultType; the modern sieve stamps serverInfo)
        from mcp.types import (  # pyright: ignore[reportMissingImports] — [mcp] extra
            SERVER_INFO_META_KEY,
            JSONRPCResponse,
        )

        result = CallToolResult(
            content=[TextContent(type="text", text=json.dumps(form, indent=2))],
            structured_content=form,
            is_error=True,
        ).model_dump(by_alias=True, mode="json", exclude_none=True)
        result["_meta"] = {SERVER_INFO_META_KEY: {"name": "ariadne", "version": ""}}
        response = JSONRPCResponse(jsonrpc="2.0", id=1, result=result)
        return len(response.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8"))

    refusal_floor = max(_refusal_modern_bytes(form) for form in refusal_forms())
    inner_bytes = _mcp_result_bytes(inner)
    inner_dict_bytes = len(json.dumps(inner).encode("utf-8"))
    assert inner_bytes > inner_dict_bytes  # the envelope duplication is real
    ceiling = max(refusal_floor + 64, (inner_dict_bytes + inner_bytes) // 2)
    assert inner_dict_bytes <= ceiling < inner_bytes  # inner fits, envelope cannot

    # Admit the exact project revision carrying the lowered host ceiling.
    registry_path = root / "ariadne.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["query"] = {"mcp_response_bytes": ceiling}
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    run_git(root, "add", "--", "ariadne.yaml")
    run_git(
        root,
        "commit",
        "-q",
        "-m",
        "human: lower synthetic response ceiling",
        "--",
        "ariadne.yaml",
    )
    _admit_project(root)
    head_before = run_git(root, "rev-parse", "HEAD").strip()
    status_before = run_git(root, "status", "--porcelain", "--untracked-files=all")
    with _StdioServer(root) as server:
        server.initialize(0)
        raw_ref, frame_ref = server.call_tool(1, "query_records", full_request)
        assert frame_ref["result"]["isError"] is True
        body = frame_ref["result"]["structuredContent"]
        assert body["error"]["code"] == "result_byte_limit"
        assert body["result"] == {"status": "refused", "complete": False, "returned_rows": 0}
        assert len(raw_ref.encode("utf-8")) <= ceiling

        # An output-refused ad-hoc definition leaves the project unchanged.
        raw_def, frame_def = server.call_tool(
            2,
            "define_metric",
            {
                "definition": {
                    "name": "envelope_probe",
                    "description": "d",
                    "source": "probe.uni",
                    "expression": "MAX(txt)",
                    "dimensions": ["txt"],
                }
            },
        )
        assert frame_def["result"]["isError"] is True
        assert (
            json.loads(frame_def["result"]["content"][0]["text"])["error"]["code"]
            == "result_byte_limit"
        )

        # a fitting narrowed retry executes afresh and returns the FULL result
        raw_fit, frame_fit = server.call_tool(
            3,
            "query_records",
            {
                "request": {
                    "dataset": "probe.uni",
                    "fields": ["id"],
                    "order": [{"field": "id"}],
                    "limit": 1,
                }
            },
        )
        assert frame_fit["result"]["isError"] is False
        fitted = json.loads(frame_fit["result"]["content"][0]["text"])
        assert fitted["rows"] == [{"id": 1}]
        assert fitted["result"]["complete"] is True

    assert run_git(root, "rev-parse", "HEAD").strip() == head_before
    assert run_git(root, "status", "--porcelain", "--untracked-files=all") == status_before


def test_refusal_frames_stay_bounded_under_the_default_ceiling(served):
    """Spec 0014 §5: the refusal representation itself is bounded — every
    emitted isError frame in this run stays under the default transport
    ceiling even with adversarial identifier content, and the all-or-nothing
    refusal body (never a partial success) is what rides the wire."""
    from ariadne.query_results import DEFAULT_QUERY_LIMITS

    project = served
    ceiling = DEFAULT_QUERY_LIMITS["mcp_response_bytes"]
    assert cell_limit_refusal(16, ["col"]).refusal()["result"] == {
        "status": "refused",
        "complete": False,
        "returned_rows": 0,
    }
    with _StdioServer(project) as server:
        server.initialize(0)
        for request_id, dataset in enumerate(
            ("no_such_table", "é" * 200, '"' + "x" * 300, "\\" + "y" * 300), start=1
        ):
            raw, frame = server.call_tool(
                request_id,
                "query_records",
                {"request": {"dataset": dataset, "fields": ["x"], "order": [{"field": "x"}]}},
            )
            assert frame["result"]["isError"] is True, dataset[:20]
            assert len(raw.encode("utf-8")) <= ceiling, dataset[:20]
            assert len(raw.encode("utf-8")) == _frame_bytes(
                _captured_result_model(frame), request_id
            )
