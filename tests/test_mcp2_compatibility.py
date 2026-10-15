"""The mcp 2.2.0 actual-wire framing check (spec 0026 §5 AC3, plan's
``new-test`` obligation).

The oracle is the CAPTURED transport frame — raw JSON-RPC lines read from a
real ``python -m ariadne.serve`` stdio process — plus spec 0014's approved
bound semantics, never the adapter's own ``_wire_bytes`` helper as its own
expected value: every assertion below reconstructs the SDK result model FROM
the captured frame and requires the adapter's serialization chain to
reproduce the frame's exact byte length, so any change in escaping, alias or
field-inclusion policy (mcp 2.2.0 serializes the outer message
``exclude_unset`` after the kernel dumped the result ``exclude_none`` — see
``ServerRunner._dump_result`` and the stdio/SSE writers) breaks the
accounting, not just the helper.

Covered: success, structured refusal and generic tool-error frames; Unicode
payloads; the supported request-ID reserve (a UUID string id is exactly 37
bytes larger than the minimal integer id); and the lowered near-envelope
ceiling where the inner dict fits but its MCP envelope does not (bounded
``isError`` refusal, no staged artifact, fitting narrowed retry executes
afresh with the full result). HTTP carries the same envelope (the streamable
writer serializes messages with the identical call — asserted in the SDK
source; the HTTP boundary behavior itself is pinned by
tests/test_authoring_mcp.py and tests/test_docker_mcp.py).
"""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.query_results import (  # noqa: E402
    cell_limit_refusal,
)  # pyright: ignore[reportMissingImports] — drift

PROTOCOL_VERSION = "2025-06-18"

# One served model over two tables: plain (10/20/30 -> plain_total == 60, the
# hand-computed oracle) and uni (non-ASCII é*5 / z*14 cells for wire escaping).
_MODELS = """version: 0.2.0.dev0
semantic_model:
  - name: plain
    description: ungrouped probe
    datasets:
      - name: plain
        source: plain
        fields:
          - name: val
            expression: {dialects: [{dialect: ANSI_SQL, expression: val}]}
    metrics:
      - name: plain_total
        description: sum of all val
        expression: {dialects: [{dialect: ANSI_SQL, expression: "SUM(val)"}]}
  - name: uniprobe
    description: unicode-cell probe
    datasets:
      - name: uni
        source: uni
        fields:
          - name: txt
            expression: {dialects: [{dialect: ANSI_SQL, expression: txt}]}
            dimension: {}
    metrics:
      - name: u
        description: count by txt
        expression: {dialects: [{dialect: ANSI_SQL, expression: "COUNT(*)"}]}
"""


def _project(root: Path, *, lowered: dict | None = None) -> tuple[Path, Path]:
    models = root / "semantic_layer" / "models"
    models.mkdir(parents=True)
    models.joinpath("probe.yml").write_text(_MODELS, encoding="utf-8")
    (root / "context_layer").mkdir()
    db = root / "probe.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE plain (val DOUBLE)")
    con.executemany("INSERT INTO plain VALUES (?)", [(10.0,), (20.0,), (30.0,)])
    con.execute("CREATE TABLE uni (id INTEGER, txt TEXT)")
    con.executemany("INSERT INTO uni VALUES (?, ?)", [(1, "é" * 5), (2, "z" * 14)])
    con.commit()
    con.close()
    if lowered is not None:
        query = "\n".join(f"  {key}: {value}" for key, value in lowered.items())
        (root / "ariadne.yaml").write_text(f"query:\n{query}\n", encoding="utf-8")
    return root, db


class _StdioServer:
    """A real ``ariadne.serve`` stdio subprocess driven by RAW JSON-RPC lines,
    so the frames asserted below are the bytes the SDK actually emits."""

    def __init__(self, project: Path, db: Path):
        self.proc = subprocess.Popen(  # noqa: S603 — the repo's own server, fixed argv
            [
                sys.executable,
                "-m",
                "ariadne.serve",
                "--project",
                str(project),
                "--db",
                str(db),
                "--semantic",
                "semantic_layer",
                "--context",
                "context_layer",
            ],
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


def test_actual_stdio_framing_success_refusal_and_generic_error(tmp_path, served):
    """Success, structured-refusal and generic-error frames captured from a
    real server: each re-serializes through the adapter's accounting chain to
    the frame's exact byte length, the request-ID reserve holds on the wire,
    and the public payload/error semantics are unchanged."""
    from ariadne.serve import _RESERVED_REQUEST_ID, _mcp_result_bytes

    project, db = served
    # a SECOND project whose served model does not compile: the generic-error
    # frame is the SDK's verbatim error path with the original message kept
    # (the compile failure fires before any source is opened, so this db —
    # whose schema merely exists — is never queried)
    broken = _project(tmp_path / "broken")[0]
    model = broken / "semantic_layer" / "models" / "probe.yml"
    model.write_text(model.read_text(encoding="utf-8").replace("COUNT(*)", "COUNT("))

    uuid_id = "11111111-2222-3333-4444-555555555555"
    with _StdioServer(project, db) as ok_server:
        ok_server.initialize(0)

        # --- success: the hand-computed 10+20+30 oracle rides the wire ------
        raw, frame = ok_server.call_tool(1, "get_metric", {"name": "plain_total"})
        result = frame["result"]
        # the handshake wire: the modern resultType/_meta extras are sieved away
        assert result["isError"] is False and "resultType" not in result
        payload = json.loads(result["content"][0]["text"])
        assert payload["rows"] == [{"plain_total": 60.0}]
        assert len(raw.encode("utf-8")) == _frame_bytes(_captured_result_model(frame), 1)
        assert _mcp_result_bytes(payload) >= len(raw.encode("utf-8"))  # int-id reserve

        # --- the same success with a UUID string id: +37 bytes on the wire --
        raw_uuid, frame_uuid = ok_server.call_tool(
            uuid_id, "get_metric", {"name": "plain_total"}
        )
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
            2, "get_metric", {"name": "u", "dimensions": ["txt"]}
        )
        uni_payload = json.loads(frame_uni["result"]["content"][0]["text"])
        assert {row["txt"] for row in uni_payload["rows"]} == {"é" * 5, "z" * 14}
        assert len(raw_uni.encode("utf-8")) == _frame_bytes(
            _captured_result_model(frame_uni), 2
        )
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
                    "dataset": "uni",
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
        assert len(raw_ref.encode("utf-8")) == _frame_bytes(
            _captured_result_model(frame_ref), 3
        )

    with _StdioServer(broken, db) as err_server:
        err_server.initialize(0)
        raw_err, frame_err = err_server.call_tool(4, "list_metrics", {})
        error = frame_err["result"]
        assert error["isError"] is True
        text = error["content"][0]["text"]
        # the 1.x public semantics: the SDK's verbatim error prefix PLUS the
        # original message (mcp 2.2.0 alone would drop a bare exception's text)
        assert text.startswith("Error executing tool list_metrics: ")
        assert "do not compile" in text
        assert len(raw_err.encode("utf-8")) == _frame_bytes(
            _captured_result_model(frame_err), 4
        )


def test_lowered_envelope_refuses_without_staging_and_narrowed_retry_fits(tmp_path):
    """The near-boundary case: the inner dict fits the core byte ceiling while
    its actual MCP envelope does not — a bounded isError refusal (never a
    partial success), nothing staged, and a fitting narrowed retry executes
    afresh with the complete result. The lowered ceiling is chosen ABOVE the
    refusal-representability floor (every refusal form must stay emittable —
    a lower ceiling would make runtime construction itself refuse) and BELOW
    the full answer's envelope."""
    import sqlite3

    from mcp.types import CallToolResult, TextContent  # pyright: ignore[reportMissingImports]

    from ariadne.query_results import refusal_forms
    from ariadne.serve import _mcp_result_bytes

    # widen the payload so the envelope clears the refusal floor with margin


    root, db = _project(tmp_path / "plain")
    con = sqlite3.connect(db)
    con.executemany(
        "INSERT INTO uni VALUES (?, ?)",
        [(i, f"payload-{i:02d}-" + "t" * 52) for i in range(3, 25)],
    )
    con.commit()
    con.close()

    full_request = {
        "request": {
            "dataset": "uni",
            "fields": ["id", "txt"],
            "order": [{"field": "id"}],
            "limit": 24,
        }
    }
    fitting_core = QueryRuntime(
        root / "semantic_layer",
        root / "context_layer",
        db,
        staging_dir=tmp_path / "core-staging",
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

    # the SAME project now carries the lowered host ceiling for the server
    (root / "ariadne.yaml").write_text(f"query:\n  mcp_response_bytes: {ceiling}\n")
    staging = root / "staging"
    with _StdioServer(root, db) as server:
        server.initialize(0)
        raw_ref, frame_ref = server.call_tool(1, "query_records", full_request)
        assert frame_ref["result"]["isError"] is True
        body = frame_ref["result"]["structuredContent"]
        assert body["error"]["code"] == "result_byte_limit"
        assert body["result"] == {"status": "refused", "complete": False, "returned_rows": 0}
        assert len(raw_ref.encode("utf-8")) <= ceiling

        # an output-refused ad-hoc definition stages NOTHING
        raw_def, frame_def = server.call_tool(
            2,
            "define_metric",
            {
                "definition": {
                    "name": "envelope_probe",
                    "description": "d",
                    "source": "uni",
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
                    "dataset": "uni",
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

    # refusal staged nothing: the staging skeleton (empty dirs the runtime
    # pre-creates) may exist, but no staged artifact FILE (the established
    # staged_files semantics of tests/test_query_results.py)
    assert not [p for p in staging.rglob("*") if p.is_file()]


def test_refusal_frames_stay_bounded_under_the_default_ceiling(served):
    """Spec 0014 §5: the refusal representation itself is bounded — every
    emitted isError frame in this run stays under the default transport
    ceiling even with adversarial identifier content, and the all-or-nothing
    refusal body (never a partial success) is what rides the wire."""
    from ariadne.query_results import DEFAULT_QUERY_LIMITS

    project, db = served
    ceiling = DEFAULT_QUERY_LIMITS["mcp_response_bytes"]
    assert cell_limit_refusal(16, ["col"]).refusal()["result"] == {
        "status": "refused",
        "complete": False,
        "returned_rows": 0,
    }
    with _StdioServer(project, db) as server:
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
