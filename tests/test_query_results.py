"""Spec 0014 §7 V2/V3 validation (issue #56/S1): the shared complete-output
safeguards and the shared execution deadline over the four existing result
operations, at the public Query seam.

Every expectation below is specified by the contract INDEPENDENTLY of the
encoder/compiler under test:

- a serialized JSON string cell is its characters plus two quote characters
  (``'x' * 15`` serializes to 17 bytes; ``'z' * 14`` to 16);
- JSON escaping replaces one non-ASCII character with the six characters
  ``\\uXXXX`` (``'é' * 5``: 5 characters, 10 UTF-8 bytes, 32 serialized bytes);
- 10 + 20 + 30 = 60, and a safety row ceiling can never act as an input LIMIT;
- three groups under a row ceiling of two refuse with an observed lower bound
  of 3 and stage nothing;
- the deadline is exercised through the existing deterministic clock seam
  (``ariadne.execution._deadline_clock``), never a wall-clock race or sleep.

Ceilings are lowered per case instead of using large payloads; the collection
boundary is observed directly only where the contract demands proof that no
oversized cell or continuing read crosses it.
"""

import asyncio
import io
import json
import sqlite3
import threading
import time
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import (
    execution,
    query_results,  # pyright: ignore[reportAttributeAccessIssue] — drift: analyzer binds the venv copy lacking this lane's new module
)
from ariadne.execution import DeadlineBudget
from ariadne.query import QueryRuntime
from ariadne.query_results import QueryResultError  # pyright: ignore[reportMissingImports] — drift

REPO_ROOT = Path(__file__).resolve().parents[1]

_HUGE = "x" * 1000

_MODELS = """version: 0.2.0.dev0
semantic_model:
  - name: groups
    description: three-group probe
    datasets:
      - name: groups3
        source: groups3
        fields:
          - name: grp
            expression: {dialects: [{dialect: ANSI_SQL, expression: grp}]}
            dimension: {}
          - name: val
            expression: {dialects: [{dialect: ANSI_SQL, expression: val}]}
    metrics:
      - name: total
        description: sum val
        expression: {dialects: [{dialect: ANSI_SQL, expression: "SUM(val)"}]}
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
  - name: cellprobe
    description: oversized-cell probe
    datasets:
      - name: cells
        source: cells
        fields:
          - name: txt
            expression: {dialects: [{dialect: ANSI_SQL, expression: txt}]}
            dimension: {}
    metrics:
      - name: n
        description: count by txt
        expression: {dialects: [{dialect: ANSI_SQL, expression: "COUNT(*)"}]}
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
  - name: collisionprobe
    description: flag-namespace collision probe
    datasets:
      - name: tricky
        source: tricky
        fields:
          - name: __ariadne_cell_overflow_0
            expression: {dialects: [{dialect: ANSI_SQL, expression: __ariadne_cell_overflow_0}]}
            dimension: {}
          - name: id
            expression: {dialects: [{dialect: ANSI_SQL, expression: id}]}
    metrics:
      - name: t
        description: count by the colliding column
        expression: {dialects: [{dialect: ANSI_SQL, expression: "COUNT(*)"}]}
  - name: enumprobe
    description: enum-label probe
    datasets:
      - name: enums
        source: enums
        fields:
          - name: label
            expression: {dialects: [{dialect: ANSI_SQL, expression: label}]}
            dimension: {}
    metrics:
      - name: e
        description: count by enum label
        expression: {dialects: [{dialect: ANSI_SQL, expression: "COUNT(*)"}]}
"""

# (every metric expression uses the same one-level dialects shape the served
# envelope dialect defines)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """One tiny real local served tree + SQLite attach: three groups, an
    ungrouped 10/20/30 population, oversized/unicode cell tables and a large
    cited metric page for the metadata-overflow case."""
    root = tmp_path_factory.mktemp("s1_served")
    models = root / "semantic_layer" / "models"
    models.mkdir(parents=True)
    models.joinpath("probe.yml").write_text(_MODELS, encoding="utf-8")
    context = root / "context_layer" / "metrics"
    context.mkdir(parents=True)
    # a served metric page large enough to overflow a lowered total budget
    context.joinpath("total.md").write_text(
        "# total\n\n" + ("required policy guidance body. " * 160), encoding="utf-8"
    )
    db = root / "probe.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE groups3 (grp TEXT, val DOUBLE)")
    con.executemany("INSERT INTO groups3 VALUES (?, ?)", [("aa", 10.0), ("bb", 20.0), ("cc", 30.0)])
    con.execute("CREATE TABLE plain (val DOUBLE)")
    con.executemany("INSERT INTO plain VALUES (?)", [(10.0,), (20.0,), (30.0,)])
    con.execute("CREATE TABLE cells (id INTEGER, txt TEXT)")
    con.executemany("INSERT INTO cells VALUES (?, ?)", [(1, "x" * 15), (2, _HUGE)])
    con.execute("CREATE TABLE uni (id INTEGER, txt TEXT)")
    con.executemany("INSERT INTO uni VALUES (?, ?)", [(1, "é" * 5), (2, "z" * 14)])
    # FIX 4 control: a physical column colliding with the generated flag
    # namespace (created BEFORE any runtime construction: deterministic attach)
    con.execute('CREATE TABLE tricky (id INTEGER, "__ariadne_cell_overflow_0" TEXT)')
    con.execute("INSERT INTO tricky VALUES (1, 'a-real-value')")
    # FIX 3 control: enum labels, one oversized
    con.execute("CREATE TABLE enums (id INTEGER, label TEXT)")
    con.executemany("INSERT INTO enums VALUES (?, ?)", [(1, "ok"), (2, "l" * 40)])
    con.commit()
    con.close()
    return root, db


def make_runtime(served, staging, **limits):
    root, db = served
    return QueryRuntime(
        root / "semantic_layer",
        root / "context_layer",
        db,
        staging_dir=staging,
        query_limits=limits or None,
    )


def staged_files(staging: Path) -> list[Path]:
    return sorted(p for p in staging.rglob("*") if p.is_file()) if staging.exists() else []


class _SpyConnection:
    """Targeted observation of the collection boundary (spec 0014 §7 V2):
    counts ``fetchmany`` rows — the bounded cursor reads — while forwarding
    everything else to the owned DuckDB connection."""

    def __init__(self, con) -> None:
        self._con = con
        self.fetched_rows = 0

    def fetchmany(self, size):
        batch = self._con.fetchmany(size)
        self.fetched_rows += len(batch)
        return batch

    def __getattr__(self, name):
        return getattr(self._con, name)


def _jumped_clock():
    """A clock whose every read advances 10,000s: the budget is spent at once
    (the same deterministic seam tests/test_mapping_inspection.py uses)."""
    real = time.monotonic
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return real() + 10_000 * ticks["n"]

    return clock


def _stepped_clock(jump_after: int):
    """A clock that reads normally for the first ``jump_after`` reads, then
    advances 10,000s on every further read — deterministic expiry part-way
    through an operation, never a sleep or a large query."""
    real = time.monotonic
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return real() + (10_000 if ticks["n"] > jump_after else 0)

    return clock


# ------------------------------------------- V2: collection/output limits


@pytest.mark.parametrize(
    "case",
    [
        "three_groups_refuse_at_row_ceiling_two",
        "input_rows_never_limited_sum_is_60",
        "seventeen_byte_serialized_cell_refuses",
        "raw_oversized_cells_cross_as_markers_not_values",
        "unicode_serialized_bytes_differ_from_characters",
        "nested_output_column_refuses_before_materialization",
        "parameterized_nested_types_refuse_before_transfer",
        "type_classification_matrix",
        "enum_labels_are_raw_guarded_as_variable",
        "flag_namespace_collision_is_positional",
        "oversized_cell_on_lookahead_row_keeps_fitting_top_n",
        "rows_fit_but_metadata_overflows",
        "metadata_accounting_stops_at_the_first_oversized_component",
        "mcp_envelope_only_overflow_refuses",
        "mcp_measure_installed_at_build_app_for_instance_and_factory",
        "framing_reserve_covers_worst_case_ids",
        "refusal_forms_and_identifiers_are_bounded",
        "cli_replaces_oversized_error_representations",
        "definitions_are_ephemeral_after_refusal_and_retry",
        "refusal_payloads_are_bounded",
        "host_config_section_validation",
        "host_config_file_tightens_the_cli",
        "fixed_size_array_seam",
        "unicode_identifiers_are_ascii_bounded_in_refusals",
        "mcp_error_envelope_matches_the_actual_form",
    ],
)
def test_query_result_limits(case, served, tmp_path, monkeypatch, capsys):
    root, db = served
    if case == "three_groups_refuse_at_row_ceiling_two":
        staging = tmp_path / "staging"
        rt = make_runtime(served, staging, max_rows=2)
        spy = _SpyConnection(rt._execution.con)
        monkeypatch.setattr(rt._execution, "con", spy)
        monkeypatch.setattr(rt, "con", spy)
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(
                rt.define_metric(
                    {
                        "name": "probe_metric",
                        "description": "three groups",
                        "source": "groups3",
                        "expression": "SUM(val)",
                        "dimensions": ["grp"],
                    }
                )
            )
        refusal = raised.value
        assert refusal.code == "result_row_limit"
        assert refusal.observed["rows_lower_bound"] == 3  # 3 groups observed
        assert spy.fetched_rows <= 3  # ceiling + ONE indicator row, never drained
        body = refusal.refusal()
        assert body["result"] == {
            "status": "refused",
            "complete": False,
            "returned_rows": 0,
        }
        assert body["rows"] == [] and body["persistence"] == {"status": "not_saved"}
        assert staged_files(staging) == []  # refusal stages NOTHING

    elif case == "input_rows_never_limited_sum_is_60":
        rt = make_runtime(served, tmp_path / "staging", max_rows=2)
        result = asyncio.run(rt.get_metric("plain_total"))
        # 10 + 20 + 30 = 60 over three INPUT rows; the row ceiling of two must
        # never act as an input LIMIT (which would wrongly yield 30).
        assert result["rows"] == [{"plain_total": 60.0}]
        assert result["result"]["complete"] is True
        assert result["result"]["scope"] == "requested_query"
        assert result["result"]["returned_rows"] == 1

    elif case == "seventeen_byte_serialized_cell_refuses":
        rt = make_runtime(served, tmp_path / "staging", cell_bytes=16)
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.get_metric("n", ["txt"]))
        # 'x' * 15 passes the 16-byte raw guard but serializes to 17 bytes
        # (15 characters + 2 quotes) — the exact post-transfer check refuses.
        assert raised.value.code == "result_cell_limit"
        assert raised.value.observed["columns"] == ["txt"]

    elif case == "raw_oversized_cells_cross_as_markers_not_values":
        rt = make_runtime(served, tmp_path / "staging", cell_bytes=16)
        budget = DeadlineBudget(20)
        bounded = rt._execution.fetch_bounded(
            "SELECT txt FROM cells ORDER BY id", rt._limits, budget
        )
        assert bounded.cell_overflow == ["txt"]
        assert bounded.rows[1]["txt"] is None  # the 1000-char value: marker, not value
        for row in bounded.rows:  # no oversized raw value ever crossed the boundary
            for value in row.values():
                assert not (isinstance(value, str) and len(value.encode("utf-8")) > 16)

    elif case == "unicode_serialized_bytes_differ_from_characters":
        refusing = make_runtime(served, tmp_path / "s1", cell_bytes=16)
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(refusing.get_metric("u", ["txt"]))
        assert raised.value.code == "result_cell_limit"
        # 'é' * 5 is 5 characters and 10 UTF-8 bytes — both under 16 — but JSON
        # escaping serializes each as \uXXXX: 5*6 + 2 quotes = 32 > 16. The
        # control with a 32-byte ceiling returns the value unchanged.
        fitting = make_runtime(served, tmp_path / "s2", cell_bytes=32)
        result = asyncio.run(fitting.get_metric("u", ["txt"]))
        values = {row["txt"] for row in result["rows"]}
        assert values == {"é" * 5, "z" * 14}

    elif case == "nested_output_column_refuses_before_materialization":
        rt = make_runtime(served, tmp_path / "staging")
        spy = _SpyConnection(rt._execution.con)
        monkeypatch.setattr(rt._execution, "con", spy)
        monkeypatch.setattr(rt, "con", spy)
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(
                rt.define_metric(
                    {
                        "name": "nested_probe",
                        "description": "nested output",
                        "source": "groups3",
                        "expression": "list(val)",
                        "dimensions": [],
                    }
                )
            )
        assert raised.value.code == "result_type_unsupported"
        assert raised.value.observed["columns"] == ["nested_probe"]
        assert spy.fetched_rows == 0  # nothing was materialized to discover size
        assert staged_files(tmp_path / "staging") == []

    elif case == "parameterized_nested_types_refuse_before_transfer":
        rt = make_runtime(served, tmp_path / "staging")
        for expression in (
            "list(CAST(val AS DECIMAL(12,2)))",  # DECIMAL(12,2)[]: nested AFTER the parameter list
            "map([grp], [val])",  # MAP(...)
            '{"a": val}',  # STRUCT(a DOUBLE)
        ):
            with pytest.raises(QueryResultError) as raised:
                asyncio.run(
                    rt.define_metric(
                        {
                            "name": "nested_param_probe",
                            "description": "d",
                            "source": "groups3",
                            "expression": expression,
                            "dimensions": [],
                        }
                    )
                )
            assert raised.value.code == "result_type_unsupported", expression

    elif case == "type_classification_matrix":
        # expectations derive from the spec's guard-order rules, not the code
        classify = query_results.classify_output_type
        for nested in (
            "INTEGER[]",
            "DECIMAL(12,2)[]",
            "INTEGER[3]",  # fixed-size array suffix (fix pass 2, finding 3)
            "DECIMAL(12,2)[2]",  # parameterized element + fixed size
            "STRUCT(a DECIMAL(10,2))[]",
            "STRUCT(a INTEGER)",
            "MAP(INTEGER, VARCHAR)",
            "UNION(a INTEGER)",
            "JSON",
            "INTERVAL",
            "WEIRDTYPE",
        ):
            assert classify(nested) == "unsupported", nested
        for variable in (
            "VARCHAR",
            "CHAR(10)",
            "BLOB",
            "VARBINARY",
            "ENUM('a', 'bb')",  # labels arrive as Python strings — must be raw-guarded
        ):
            assert classify(variable) == "variable", variable
        for fixed in ("BIGINT", "DECIMAL(18,3)", "DATE", "TIMESTAMP WITH TIME ZONE", "UUID"):
            assert classify(fixed) == "fixed", fixed

    elif case == "enum_labels_are_raw_guarded_as_variable":
        # a 40-byte enum label under a 16-byte ceiling: the in-DuckDB marker
        # guard fires (the value itself never crosses into Python)
        rt = make_runtime(served, tmp_path / "staging", cell_bytes=16)
        budget = DeadlineBudget(20)
        long_label = "l" * 40
        sql = f"SELECT CAST(label AS ENUM('ok', '{long_label}')) AS label FROM enums ORDER BY id"
        bounded = rt._execution.fetch_bounded(sql, rt._limits, budget)
        assert bounded.cell_overflow == ["label"]
        assert bounded.rows[1]["label"] is None  # marker, not the oversized label
        assert bounded.rows[0]["label"] == "ok"

    elif case == "flag_namespace_collision_is_positional":
        # a PHYSICAL column named like a generated flag is a value column:
        # positional association never swallows or misreads it
        rt = make_runtime(served, tmp_path / "staging")
        budget = DeadlineBudget(20)
        bounded = rt._execution.fetch_bounded(
            'SELECT id, "__ariadne_cell_overflow_0" FROM tricky ORDER BY id',
            rt._limits,
            budget,
        )
        assert bounded.rows == [{"id": 1, "__ariadne_cell_overflow_0": "a-real-value"}]
        assert bounded.cell_overflow == []
        result = asyncio.run(rt.get_metric("t", ["__ariadne_cell_overflow_0"]))
        assert result["rows"] == [{"__ariadne_cell_overflow_0": "a-real-value", "t": 1}]

    elif case == "oversized_cell_on_lookahead_row_keeps_fitting_top_n":
        # S2 (spec 0014 §3 + §7 V2-7, issue #57): an oversized cell ONLY on
        # the top-N lookahead row must not refuse an otherwise fitting top-N —
        # the same-execution existence indicator rides the last returned row,
        # so the extra row's payload cells never transfer. The enums fixture:
        # row id 1 ('ok') fits a 16-byte cell ceiling; the next row's 40-byte
        # label would flag cell_overflow if it transferred — it does not.
        rt = make_runtime(served, tmp_path / "staging", cell_bytes=16)
        result = asyncio.run(
            rt.query_records(
                {
                    "dataset": "enums",
                    "fields": ["id", "label"],
                    "order": [{"field": "id"}],
                    "limit": 1,
                }
            )
        )
        assert result["rows"] == [{"id": 1, "label": "ok"}]
        assert result["result"]["complete"] is True
        assert result["result"]["scope"] == "requested_top_n"
        assert result["result"]["has_more_matching"] is True

    elif case == "rows_fit_but_metadata_overflows":
        # 2000 clears the refusal-form floor (every refusable representation
        # must fit) while the required cited page (~4.6KB) still overflows it
        rt = make_runtime(served, tmp_path / "staging", response_bytes=2000)
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.get_metric("total"))
        assert raised.value.code == "result_byte_limit"
        # the single aggregate row fits; the required cited page does not —
        # refusal, never a dropped Policy body.
        assert raised.value.observed["rows_lower_bound"] == 0

    elif case == "metadata_accounting_stops_at_the_first_oversized_component":
        import ariadne.query_results as qr

        dumped: list[str] = []
        real_dumps = qr.json.dumps

        def spy_dumps(value, *args, **kwargs):
            dumped.append(value if isinstance(value, str) else real_dumps(value, *args, **kwargs))
            return dumped[-1]

        marker = "NEVER-SERIALIZED-COMPONENT"
        envelope = {"context": "x" * 3000, "later": marker}
        limits = {**query_results.DEFAULT_QUERY_LIMITS, "response_bytes": 1000}
        monkeypatch.setattr(qr.json, "dumps", spy_dumps)
        with pytest.raises(QueryResultError) as raised:
            query_results.account_rows(limits, envelope, [])
        assert raised.value.code == "result_byte_limit"
        # the oversized component stopped accounting: the LATER component was
        # never serialized merely to count the envelope
        assert not any(marker in payload for payload in dumped), dumped

    elif case == "mcp_envelope_only_overflow_refuses":
        from ariadne.serve import _mcp_result_bytes

        refusing = make_runtime(
            served, tmp_path / "s1", response_bytes=65536, mcp_response_bytes=1500
        )
        refusing._measure = _mcp_result_bytes  # the adapter-supplied preflight
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(refusing.get_metric("total"))
        assert raised.value.code == "result_byte_limit"
        assert raised.value.exhausted == {"mcp_response_bytes": 1500}
        # the core dict fits (same limits without the transport measure succeed)
        control = make_runtime(served, tmp_path / "s2", response_bytes=65536)
        assert asyncio.run(control.get_metric("total"))["rows"] == [{"total": 60.0}]

    elif case == "mcp_measure_installed_at_build_app_for_instance_and_factory":
        from ariadne.serve import _mcp_result_bytes, build_app

        instance = make_runtime(served, tmp_path / "s1")
        assert instance._measure is None  # not yet: direct construction has no transport
        app = build_app(instance, toolset="analyst")
        result = asyncio.run(app.call_tool("get_metric", {"name": "plain_total"}))
        from mcp.types import CallToolResult  # pyright: ignore[reportMissingImports] — [mcp] extra

        assert isinstance(result, CallToolResult) and not result.is_error
        assert json.loads(result.content[0].text)["rows"] == [{"plain_total": 60.0}]
        assert instance._measure is _mcp_result_bytes  # installed at the seam
        factory_built = make_runtime(served, tmp_path / "s2")
        app2 = build_app(lambda: factory_built, toolset="analyst")
        asyncio.run(app2.call_tool("get_metric", {"name": "plain_total"}))
        assert factory_built._measure is _mcp_result_bytes  # factory callers too
        explicit = make_runtime(served, tmp_path / "s3")
        explicit._measure = lambda result: 1  # an explicit measure still overrides
        app3 = build_app(explicit, toolset="analyst")
        asyncio.run(app3.call_tool("get_metric", {"name": "plain_total"}))
        assert explicit._measure is not _mcp_result_bytes

    elif case == "framing_reserve_covers_worst_case_ids":
        import pydantic_core  # pyright: ignore[reportMissingImports] — the [mcp] extra ships it
        from mcp.types import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
            SERVER_INFO_META_KEY,
            CallToolResult,
            JSONRPCResponse,
            TextContent,
        )

        from ariadne.serve import _RESERVED_REQUEST_ID, _mcp_result_bytes

        value = {"metric": "m", "rows": [{"a": 1}]}
        text = pydantic_core.to_json(value, fallback=str, indent=2).decode()
        call_result = CallToolResult(content=[TextContent(type="text", text=text)], is_error=False)

        def wire(request_id):
            # the mcp 2.2.0 MODERN-wire form the measure models: the kernel
            # dumps the result model exclude_none (resultType included), the
            # modern sieve keeps it and stamps the serverInfo _meta, and the
            # stdio/SSE writers serialize the response exclude_unset
            result = call_result.model_dump(by_alias=True, mode="json", exclude_none=True)
            result["_meta"] = {SERVER_INFO_META_KEY: {"name": "ariadne", "version": ""}}
            response = JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result)
            return len(response.model_dump_json(by_alias=True, exclude_unset=True).encode())

        assert _mcp_result_bytes(value) == wire(_RESERVED_REQUEST_ID)
        # the reserve is a bounded worst case: a UUID-length quoted string id is
        # 37 bytes larger than the minimal integer id the SDK would accept
        assert wire(_RESERVED_REQUEST_ID) - wire(1) == 37

    elif case == "refusal_forms_and_identifiers_are_bounded":
        from ariadne.serve import _refusal_envelope_bytes

        for form in query_results.refusal_forms():
            assert query_results.result_json_bytes(form) <= 65536  # every core form fits
            assert _refusal_envelope_bytes(form) <= 131072  # and its MCP representation
        # identifiers in refusal text are truncated, lists capped (no
        # unrestricted caller-supplied string rides in a refusal)
        long_column = "c" * 300
        refusal = query_results.cell_limit_refusal(16, [long_column] * 20)
        body = refusal.refusal()
        message = body["error"]["message"]
        assert "c" * 65 not in message  # truncated at the 64-char bound
        assert query_results.result_json_bytes(body) < 2000
        assert body["error"]["observed"]["columns"][-1] == "+12 more"  # capped list

    elif case == "definitions_are_ephemeral_after_refusal_and_retry":
        staging = tmp_path / "staging"
        rt = make_runtime(served, staging, max_rows=2)
        definition = {
            "name": "staging_probe",
            "description": "staging sequence",
            "source": "groups3",
            "expression": "SUM(val)",
            "dimensions": ["grp"],
        }
        with pytest.raises(QueryResultError):
            asyncio.run(rt.define_metric(dict(definition)))
        assert staged_files(staging) == []
        # A fitting narrowed retry executes anew and remains ephemeral.
        narrowed = {**definition, "dimensions": []}
        first = asyncio.run(rt.define_metric(dict(narrowed)))
        assert first["rows"] == [{"staging_probe": 60.0}]
        assert first["persistence"] == {"status": "not_saved"}
        assert "staged_as" not in first and "staged_context_as" not in first
        second = asyncio.run(rt.define_metric(dict(narrowed)))
        assert second["rows"] == first["rows"]
        assert second["persistence"] == {"status": "not_saved"}
        assert staged_files(staging) == []

    elif case == "cli_replaces_oversized_error_representations":
        from ariadne import cli

        async def exploding(self, name, dimensions=None, range=None):
            raise ValueError("E" * 200_000)  # an unrestricted exception dump

        monkeypatch.setattr(QueryRuntime, "get_metric", exploding)
        capsys.readouterr()
        code = cli.main(
            ["get-metric", "total", "--served", str(root), "--db", str(db)],
            stdin=io.StringIO(""),
        )
        captured = capsys.readouterr()
        assert code == 1
        payload = captured.err.encode("utf-8")
        assert len(payload) <= 65_536 + 64  # bounded — never the unrestricted dump
        error = json.loads(captured.err)["error"]
        assert error["type"] == "ValueError"
        assert error["code"] == "result_byte_limit"  # the bounded explicit refusal
        assert "withheld" in error["message"]

        # a FITTING error keeps its verbatim message
        async def fitting_failure(self, name, dimensions=None, range=None):
            raise ValueError("small verbatim failure")

        monkeypatch.setattr(QueryRuntime, "get_metric", fitting_failure)
        capsys.readouterr()
        code = cli.main(
            ["get-metric", "total", "--served", str(root), "--db", str(db)],
            stdin=io.StringIO(""),
        )
        assert code == 1
        assert json.loads(capsys.readouterr().err)["error"]["message"] == "small verbatim failure"

    elif case == "refusal_payloads_are_bounded":
        rt = make_runtime(served, tmp_path / "staging", response_bytes=2000, max_rows=2)
        refusals = []
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.get_metric("total", ["grp"]))
        refusals.append(raised.value)
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(
                rt.define_metric(
                    {
                        "name": "bounded_refusal_probe",
                        "description": "d",
                        "source": "groups3",
                        "expression": "SUM(val)",
                        "dimensions": ["grp"],
                    }
                )
            )
        refusals.append(raised.value)
        for refusal in refusals:
            payload = json.dumps(refusal.refusal(), default=str).encode("utf-8")
            assert len(payload) <= 2000  # the refusal itself fits its bounds

    elif case == "host_config_section_validation":
        for bad in (
            {"max_rows": True},
            {"max_rows": 0},
            {"max_rows": -1},
            {"max_rows": 1001},
            {"response_bytes": 64},  # cannot carry even the compact refusal
            {"execution_seconds": float("nan")},
            {"execution_seconds": 0},
            {"execution_seconds": 21},
            {"unexpected": 5},
            "not-a-mapping",
        ):
            with pytest.raises(ValueError):
                # (the str entry is deliberately invalid input — that is the check)
                query_results.effective_limits(bad)  # pyright: ignore[reportArgumentType]
        tightened = query_results.effective_limits({"max_rows": 5, "execution_seconds": 2.5})
        assert tightened["max_rows"] == 5 and tightened["execution_seconds"] == 2.5
        assert tightened["response_bytes"] == 65536  # untouched keys keep defaults
        with pytest.raises(ValueError):
            make_runtime(served, tmp_path / "never", response_bytes=64)

    elif case == "host_config_file_tightens_the_cli":
        from ariadne import cli

        host = tmp_path / "host"
        host.mkdir()
        (host / "ariadne.yaml").write_text("query:\n  max_rows: 2\n", encoding="utf-8")
        monkeypatch.chdir(host)
        capsys.readouterr()
        code = cli.main(
            ["get-metric", "total", "--dimension", "grp", "--served", str(root), "--db", str(db)],
            stdin=io.StringIO(""),
        )
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""  # never a successful partial on stdout
        refusal = json.loads(captured.err)
        assert refusal["error"]["code"] == "result_row_limit"
        assert refusal["result"] == {
            "status": "refused",
            "complete": False,
            "returned_rows": 0,
        }
        # without the host section the same call fits and succeeds
        plain_host = tmp_path / "plain-host"
        plain_host.mkdir()
        monkeypatch.chdir(plain_host)
        capsys.readouterr()
        code = cli.main(
            ["get-metric", "total", "--served", str(root), "--db", str(db)], stdin=io.StringIO("")
        )
        assert code == 0
        assert json.loads(capsys.readouterr().out)["rows"] == [{"total": 60.0}]

    elif case == "fixed_size_array_seam":
        rt = make_runtime(served, tmp_path / "staging")
        budget = DeadlineBudget(20)
        with pytest.raises(QueryResultError) as raised:
            rt._execution.fetch_bounded(
                "SELECT CAST([1.5, 2.5] AS DECIMAL(12,2)[2]) AS fixed_arr",
                rt._limits,
                budget,
            )
        assert raised.value.code == "result_type_unsupported"
        assert raised.value.observed["columns"] == ["fixed_arr"]

    elif case == "unicode_identifiers_are_ascii_bounded_in_refusals":
        # the identifier FORM is known-ASCII and at most 64 characters, so its
        # serialized size can never exceed the ASCII worst case the
        # refusal-form battery validates (JSON \uXXXX escaping costs 6x)
        bounded_name = query_results._bound_name("\u00e9" * 300)
        assert bounded_name.isascii() and len(bounded_name) <= 64
        unicode_form = query_results.cell_limit_refusal(16, ["\u00e9" * 300]).refusal()
        worst = max(query_results.result_json_bytes(form) for form in query_results.refusal_forms())
        assert query_results.result_json_bytes(unicode_form) <= worst
        # fix pass 4: the WHITELIST adversarial corpus — backslashes, quotes,
        # tabs, newlines, every ASCII control (\x00-\x1f), DEL, non-ASCII and
        # mixed content. Each must reduce to the safe set (printable ASCII
        # minus backslash/quote: exactly 1 serialized byte per character —
        # pre-fix failing-first: \x01*64 serialized to 386 bytes, tab/newline
        # to 130, and the worst-case refusal hit 3491 vs the 1501 floor), and
        # the worst-case refusal stays within the sampled floor.
        expanding = [
            "\\" * 64,
            '"' * 64,
            "\t" * 64,
            "\n" * 64,
            "".join(chr(code) for code in range(0x00, 0x20)) * 4,  # every control char
            "\x7f" * 64,  # DEL
            "\u00e9" * 300,
            'a\\b"c\td\ne\x01\x7f \u00e9' * 8,  # mixed
        ] * 2
        for raw in expanding:
            bounded = query_results._bound_name(raw)
            assert bounded.isascii() and len(bounded) <= 64
            assert len(json.dumps(bounded).encode("utf-8")) == len(bounded) + 2  # 1B/char
        expanding_form = query_results.cell_limit_refusal(16, expanding).refusal()
        cell_floor = max(
            query_results.result_json_bytes(form)
            for form in query_results.refusal_forms()
            if form["error"]["code"] == "result_cell_limit"
        )
        assert query_results.result_json_bytes(expanding_form) <= cell_floor
        for name in expanding_form["error"]["observed"]["columns"]:
            assert name.isascii() and "\\" not in name and '"' not in name

    elif case == "mcp_error_envelope_matches_the_actual_form":
        from mcp.types import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
            CallToolResult,
            TextContent,
        )

        from ariadne.serve import _mcp_error_envelope_bytes, _wire_bytes

        exc = ValueError("boom " * 400)
        actual = _wire_bytes(
            CallToolResult(
                content=[TextContent(type="text", text=f"Error executing tool get_metric: {exc}")],
                is_error=True,
            )
        )
        assert _mcp_error_envelope_bytes("get_metric", exc) == actual
        # near-ceiling generic errors cannot pass preflight then overflow:
        # the modeled form is the one the SDK emits (probe-confirmed shape)


# ------------------------------------------- V3: deadlines and staging


@pytest.mark.parametrize(
    "case",
    [
        "setup_exhaustion_refuses_before_the_source_opens",
        "operation_exhaustion_refuses_with_no_complete_answer",
        "expiry_between_phases_never_returns_success",
        "request_budget_spans_construction_and_first_operation",
        "cli_threads_one_request_budget_through_construction",
        "expiry_after_collection_refuses_without_persistence",
        "non_result_request_discards_the_request_budget",
        "interrupted_collection_refuses",
        "fresh_budget_no_inherited_cancellation",
    ],
)
def test_query_deadline_contract(case, served, tmp_path, monkeypatch, capsys):
    if case == "setup_exhaustion_refuses_before_the_source_opens":
        monkeypatch.setattr(execution, "_deadline_clock", _jumped_clock())
        with pytest.raises(ValueError, match="deadline"):
            make_runtime(served, tmp_path / "staging", execution_seconds=1)

    elif case == "operation_exhaustion_refuses_with_no_complete_answer":
        staging = tmp_path / "staging"
        rt = make_runtime(served, staging)
        real = execution._deadline_clock
        monkeypatch.setattr(execution, "_deadline_clock", _jumped_clock())
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.get_metric("total"))
        assert raised.value.code == "execution_deadline"
        assert raised.value.refusal()["result"]["complete"] is False
        with pytest.raises(QueryResultError):
            asyncio.run(
                rt.define_metric(
                    {
                        "name": "deadline_probe",
                        "description": "d",
                        "source": "groups3",
                        "expression": "SUM(val)",
                        "dimensions": [],
                    }
                )
            )
        assert staged_files(staging) == []  # exhaustion before staging stages nothing
        monkeypatch.setattr(execution, "_deadline_clock", real)

    elif case == "expiry_between_phases_never_returns_success":
        rt = make_runtime(served, tmp_path / "staging")
        for jump_after in (2, 4, 6):  # deterministic expiry at varying phase points
            monkeypatch.setattr(execution, "_deadline_clock", _stepped_clock(jump_after))
            with pytest.raises(QueryResultError) as raised:
                asyncio.run(rt.get_metric("total"))
            assert raised.value.code == "execution_deadline"

    elif case == "request_budget_spans_construction_and_first_operation":
        real = time.monotonic
        offset = {"s": 0.0}
        monkeypatch.setattr(execution, "_deadline_clock", lambda: real() + offset["s"])
        budget = DeadlineBudget(20)
        rt = QueryRuntime(
            served[0] / "semantic_layer",
            served[0] / "context_layer",
            served[1],
            staging_dir=tmp_path / "staging",
            deadline_budget=budget,  # request-lifecycle construction: ONE budget
        )
        # construction alone consumed more than the 20s deadline: the FIRST
        # operation draws from the SAME remaining-seconds budget and refuses —
        # never a fresh 20s allowance on top of the spent construction
        offset["s"] = 25.0
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.get_metric("total"))
        assert raised.value.code == "execution_deadline"
        # the SECOND operation starts a FRESH budget (reused session)
        offset["s"] = 0.0
        result = asyncio.run(rt.get_metric("total"))
        assert result["rows"] == [{"total": 60.0}] and result["result"]["complete"] is True

    elif case == "cli_threads_one_request_budget_through_construction":
        from ariadne import cli

        host = tmp_path / "host"
        host.mkdir()
        monkeypatch.chdir(host)
        # construction consumes reads 1-2; the stepped clock jumps afterwards,
        # so the SHARED request budget refuses the operation — while a fresh
        # per-operation budget (the ~2x bug) would start at the jumped instant
        # and happily succeed
        monkeypatch.setattr(execution, "_deadline_clock", _stepped_clock(3))
        code = cli.main(
            [
                "get-metric",
                "total",
                "--served",
                str(served[0]),
                "--db",
                str(served[1]),
            ],
            stdin=io.StringIO(""),
        )
        assert code == 1
        refusal = json.loads(capsys.readouterr().err)
        assert refusal["error"]["code"] == "execution_deadline"
        assert refusal["result"]["complete"] is False

    elif case == "expiry_after_collection_refuses_without_persistence":
        staging = tmp_path / "staging"
        rt = make_runtime(served, staging)
        # The final response check refuses when the deadline expires there.
        monkeypatch.setattr(execution, "_deadline_clock", _stepped_clock(8))
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(
                rt.define_metric(
                    {
                        "name": "post_stage_probe",
                        "description": "d",
                        "source": "groups3",
                        "expression": "SUM(val)",
                        "dimensions": [],
                    }
                )
            )
        assert raised.value.code == "execution_deadline"
        body = raised.value.refusal()
        assert body["result"]["complete"] is False
        assert body["persistence"] == {"status": "not_saved"}
        assert staged_files(staging) == []

    elif case == "non_result_request_discards_the_request_budget":
        real = time.monotonic
        offset = {"s": 0.0}
        monkeypatch.setattr(execution, "_deadline_clock", lambda: real() + offset["s"])
        budget = DeadlineBudget(20)
        rt = QueryRuntime(
            served[0] / "semantic_layer",
            served[0] / "context_layer",
            served[1],
            staging_dir=tmp_path / "staging",
            deadline_budget=budget,
        )
        asyncio.run(rt.list_metrics())  # the non-result call that "constructed"
        offset["s"] = 25.0  # that request is long over
        result = asyncio.run(rt.get_metric("total"))  # must NOT inherit it
        assert result["result"]["complete"] is True

    elif case == "interrupted_collection_refuses":
        rt = make_runtime(served, tmp_path / "staging")
        clock = {"now": 0.0}
        budget = DeadlineBudget(100, clock=lambda: clock["now"])
        con = rt._execution.con

        class _InterruptedConnection:
            """A connection whose guarded statement is interrupted by the
            watchdog mid-read (the mapping-inspection seam pattern)."""

            def __init__(self, wrapped):
                self._wrapped = wrapped
                self.interrupted = False

            def interrupt(self):
                self.interrupted = True

            def execute(self, sql):
                self.interrupted = True
                clock["now"] = 200.0  # the budget is spent as the interruption lands
                raise duckdb.InterruptException("interrupted mid-read")

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

        spy = _InterruptedConnection(con)
        with pytest.raises(execution.DeadlineExhausted):
            with budget.guard(spy):
                monkeypatch.setattr(rt._execution, "con", spy)
                try:
                    rt._execution.fetch_bounded("SELECT grp FROM groups3", rt._limits, budget)
                finally:
                    rt._execution.con = con
        assert spy.interrupted

    elif case == "fresh_budget_no_inherited_cancellation":
        rt = make_runtime(served, tmp_path / "staging")
        timers_before = threading.active_count()
        real = execution._deadline_clock
        monkeypatch.setattr(execution, "_deadline_clock", _jumped_clock())
        with pytest.raises(QueryResultError):
            asyncio.run(rt.get_metric("total"))
        monkeypatch.setattr(execution, "_deadline_clock", real)
        # a new invocation starts a fresh budget: no inherited cancellation,
        # no lingering armed watchdog from the refused operation
        for thread in list(threading.enumerate()):
            if isinstance(thread, threading.Timer):
                thread.join(1.0)
        assert not any(
            isinstance(t, threading.Timer) and t.is_alive() for t in threading.enumerate()
        )
        assert threading.active_count() <= timers_before + 1
        result = asyncio.run(rt.get_metric("total"))
        assert result["rows"] == [{"total": 60.0}]
        assert result["result"]["complete"] is True
