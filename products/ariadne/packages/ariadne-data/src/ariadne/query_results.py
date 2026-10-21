"""Shared complete-output safeguards for Query result operations (spec 0014
§4–§6, issue #56/S1): host-owned limit validation, the existing-compatible
scalar JSON encoding and its exact byte accounting, and the bounded structured
refusal every result operation refuses through.

This helper is today's four result operations (``get_metric``,
``define_metric``, ``query_metrics``, ``query_detail``) plus their CLI/MCP
adapters — not a generic response framework. It imports no MCP or workflow
module (plan 0014 §2): the MCP adapter supplies its own actual-representation
measure; the core only calls it.

The ceilings (spec 0014 §4) are operator-owned, never request fields:

===========  ============================================  =====================
Key          Bound                                          Built-in ceiling
===========  ============================================  =====================
max_rows     Returned result rows                           1,000
response_bytes  Complete serialized core response            65,536
cell_bytes   One serialized result cell                      16,384
mcp_response_bytes  Complete MCP tool-result envelope        131,072
execution_seconds  Shared execution deadline                20 s
===========  ============================================  =====================

An optional ``query:`` section in the host project's ``ariadne.yaml`` may only
TIGHTEN them (integers for rows/bytes, finite positive seconds; booleans,
zero, negatives, NaN/inf, unknown keys and attempted increases are rejected),
and a budget unable to represent the compact refusal is rejected before use
(spec 0014 §5).
"""

from __future__ import annotations

import base64
import json
import math
import re
import uuid
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

DEFAULT_QUERY_LIMITS: dict[str, float | int] = {
    "max_rows": 1000,
    "response_bytes": 65536,
    "cell_bytes": 16384,
    "mcp_response_bytes": 131072,
    "execution_seconds": 20.0,
}
QUERY_LIMIT_KEYS = frozenset(DEFAULT_QUERY_LIMITS)
_INT_LIMIT_KEYS = ("max_rows", "response_bytes", "cell_bytes", "mcp_response_bytes")

# Stable refusal codes (spec 0014 §5).
RESULT_ROW_LIMIT = "result_row_limit"
RESULT_BYTE_LIMIT = "result_byte_limit"
RESULT_CELL_LIMIT = "result_cell_limit"
RESULT_TYPE_UNSUPPORTED = "result_type_unsupported"
EXECUTION_DEADLINE = "execution_deadline"

_ROW_MESSAGE = (
    "the complete answer exceeds the host ceiling of {max_rows} returned result "
    "rows ({observed}+ observed) — narrow the result grouping or population; no "
    "partial rows are returned as a complete answer"
)
_BYTE_MESSAGE = (
    "the complete serialized answer exceeds its byte ceiling — narrow the request "
    "or the selected fields; required content is never dropped to fit"
)
_MCP_BYTE_MESSAGE = (
    "the complete answer exceeds the selected transport's tool-result envelope "
    "ceiling even though the core response fits — narrow the request or the "
    "selected fields; a successful prefix is never sent"
)
_CELL_MESSAGE = (
    "a serialized result cell exceeds the host ceiling of {cell_bytes} bytes in "
    "column(s) {columns} — select or narrow the oversized column(s); no clipped "
    "cell is returned"
)
_TYPE_MESSAGE = (
    "output column(s) {columns} have nested/complex types whose size cannot be "
    "bounded before transfer — project scalar columns instead; unsupported "
    "output is never materialized to discover its size"
)
_DEADLINE_MESSAGE = (
    "the shared execution deadline of {seconds}s was exhausted before the answer "
    "completed — narrow the request or the selected fields; no complete answer is "
    "returned after expiry"
)

# DuckDB output types by pre-transfer boundability (spec 0014 §4 guards 2–3):
# fixed-width scalars pass through; variable-size text/blob values are raw-
# guarded inside DuckDB before Python transfer; everything else (lists, structs,
# maps, unions, JSON, intervals, unknown types) refuses up front.
_FIXED_SCALAR_TYPES = frozenset(
    {
        "BOOLEAN",
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "FLOAT",
        "DOUBLE",
        "REAL",
        "DECIMAL",
        "DATE",
        "TIME",
        "TIMESTAMP",
        "TIMESTAMP_S",
        "TIMESTAMP_MS",
        "TIMESTAMP_NS",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMPTZ",
        "DATETIME",
        "UUID",
    }
)
# ENUM is deliberately NOT fixed: Python receives the enum's label as a
# str whose length is bounded only by the label, so the in-DuckDB raw guard
# must apply (via CAST to VARCHAR — fix pass 1, finding 3).
_VARIABLE_SCALAR_TYPES = frozenset(
    {"VARCHAR", "CHAR", "BPCHAR", "TEXT", "STRING", "BLOB", "VARBINARY"}
)

FLAG_PREFIX = "__ariadne_cell_overflow_"

# Refusal text never embeds unrestricted caller-influenced strings (fix pass
# 1, finding 2d): identifiers are truncated, lists capped — every refusal
# representation is bounded by construction.
_MAX_IDENTIFIER_CHARS = 64
_MAX_IDENTIFIER_COLUMNS = 8
# The whitelist (fix pass 4): the ONLY characters a bounded identifier form
# may carry — printable ASCII excluding the backslash and the double quote,
# i.e. exactly the characters that JSON-serialize to ONE byte each under the
# canonical codec. Every other character (controls, DEL, non-ASCII, and the
# two escaping ASCII punctuation marks) maps to '?'.
_SAFE_IDENTIFIER_CHARS = frozenset(
    chr(code)
    for code in range(0x20, 0x7F)
    if code not in (0x22, 0x5C)  # exclude the double quote and the backslash
)


def _bound_name(name: str) -> str:
    """A known-safe, at most 64-character identifier form. Invariant: every
    character of a bounded identifier form serializes to exactly 1 byte
    under the canonical codec — the whitelist keeps only printable ASCII
    minus backslash and double quote, and maps everything else (ASCII
    control characters and DEL, which backslashreplace passes through RAW
    because they are ASCII-encodable; non-ASCII, which it escapes with the
    2-byte backslash itself) to '?'. The refusal-form battery's ``c``-based
    sample is therefore the true worst case for ALL inputs."""
    original = str(name)
    text = original[:_MAX_IDENTIFIER_CHARS]
    ascii_form = text.encode("ascii", "backslashreplace").decode("ascii")
    ascii_form = "".join(
        character if character in _SAFE_IDENTIFIER_CHARS else "?" for character in ascii_form
    )
    if not ascii_form:
        ascii_form = "?"  # an empty name still leaves a bounded marker
    if len(ascii_form) > _MAX_IDENTIFIER_CHARS or len(original) > _MAX_IDENTIFIER_CHARS:
        return ascii_form[: _MAX_IDENTIFIER_CHARS - 3] + "..."
    return ascii_form


def _bound_columns(columns: list[str]) -> list[str]:
    bounded = [_bound_name(column) for column in columns[:_MAX_IDENTIFIER_COLUMNS]]
    if len(columns) > _MAX_IDENTIFIER_COLUMNS:
        bounded.append(f"+{len(columns) - _MAX_IDENTIFIER_COLUMNS} more")
    return bounded


class QueryResultError(ValueError):
    """The all-or-nothing refusal (spec 0014 §5): no result rows,
    ``complete: false``, a stable code, the exhausted bound and observed
    lower bounds. The refusal representation itself is small by construction
    (fixed messages, counts only — the rejected remainder is never scanned or
    serialized to produce an exact total)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exhausted: dict | None = None,
        observed: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.exhausted = dict(exhausted or {})
        self.observed = dict(observed or {})

    def refusal(self) -> dict:
        """The transport-neutral structured refusal body (spec 0014 §5).
        Result refusals never save an authored artifact.
        """
        return {
            "error": {
                "code": self.code,
                "message": str(self),
                "exhausted_bound": self.exhausted,
                "observed": self.observed,
            },
            "result": {"status": "refused", "complete": False, "returned_rows": 0},
            "rows": [],
            "persistence": {"status": "not_saved"},
        }


def row_limit_refusal(max_rows: int, rows_lower_bound: int) -> QueryResultError:
    return QueryResultError(
        RESULT_ROW_LIMIT,
        _ROW_MESSAGE.format(max_rows=max_rows, observed=rows_lower_bound),
        exhausted={"max_rows": max_rows},
        observed={"rows_lower_bound": rows_lower_bound},
    )


def byte_limit_refusal(response_bytes: int, observed: dict | None = None) -> QueryResultError:
    return QueryResultError(
        RESULT_BYTE_LIMIT,
        _BYTE_MESSAGE,
        exhausted={"response_bytes": response_bytes},
        observed=observed,
    )


def mcp_byte_limit_refusal(
    mcp_response_bytes: int, observed: dict | None = None
) -> QueryResultError:
    return QueryResultError(
        RESULT_BYTE_LIMIT,
        _MCP_BYTE_MESSAGE,
        exhausted={"mcp_response_bytes": mcp_response_bytes},
        observed=observed,
    )


def cell_limit_refusal(cell_bytes: int, columns: list[str]) -> QueryResultError:
    bounded = _bound_columns(columns)
    return QueryResultError(
        RESULT_CELL_LIMIT,
        _CELL_MESSAGE.format(cell_bytes=cell_bytes, columns=", ".join(bounded)),
        exhausted={"cell_bytes": cell_bytes},
        observed={"columns": bounded},
    )


def type_unsupported_refusal(columns: list[str]) -> QueryResultError:
    bounded = _bound_columns(columns)
    return QueryResultError(
        RESULT_TYPE_UNSUPPORTED,
        _TYPE_MESSAGE.format(columns=", ".join(bounded)),
        observed={"columns": bounded},
    )


def deadline_refusal(execution_seconds: float) -> QueryResultError:
    return QueryResultError(
        EXECUTION_DEADLINE,
        _DEADLINE_MESSAGE.format(seconds=execution_seconds),
        exhausted={"execution_seconds": execution_seconds},
    )


# --------------------------------------------- the shared scalar JSON encoding


def json_default(value: Any) -> Any:
    """The established scalar serialization (spec §4: ISO temporal values,
    precision-preserving decimal strings) — byte-identical to the CLI's
    success print, so core accounting measures the representation the local
    transport actually emits. Bytes (BLOB cells) and UUIDs gain a defined
    scalar form (base64 / canonical text); they previously failed JSON
    serialization entirely."""
    if isinstance(value, (date, time)):  # datetime is a date subclass
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")


def encode_scalar(value: Any) -> Any:
    """Convert one collected DuckDB cell to its JSON-ready scalar at the
    execution/Python boundary — both transports then serialize the same
    values (existing fitting formats preserved verbatim)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return json_default(value)


def cell_json_bytes(value: Any) -> int:
    """Exact serialized size of one already-encoded cell: UTF-8 bytes after
    the actual serializer's escaping (quotes included) — never the character
    count or an estimate of the raw size (spec 0014 §4)."""
    return len(json.dumps(value).encode("utf-8"))


def result_json_bytes(value: Any) -> int:
    """Exact serialized size of one complete response under the canonical
    core codec (the CLI's ``json.dumps(result, default=...)`` form)."""
    return len(json.dumps(value, default=json_default).encode("utf-8"))


def classify_output_type(type_name: str) -> str:
    """``fixed`` / ``variable`` / ``unsupported`` for one DuckDB output type.
    Array/nested/struct markers are detected on the FULL type string BEFORE
    any parameter stripping (fix pass 1, finding 3): ``DECIMAL(12,2)[]`` is
    an array, not a fixed decimal — splitting at ``(`` first would classify
    it fixed and transfer an unrestricted Python list. Variable-size
    text/blob/enum columns get the in-DuckDB raw guard (ENUM labels arrive
    as Python strings — guarded via CAST); everything else refuses up front."""
    text = type_name.strip()
    if re.search(r"\[\d*\]", text):
        # arrays anywhere on the FULL string — unbounded ``[]`` lists AND
        # fixed-size ``[N]`` suffixes, including parameterized elements like
        # DECIMAL(12,2)[2] (fix pass 2, finding 3: splitting at ``(`` first
        # classified that as a fixed decimal and transferred a raw Python
        # tuple). Fixed-size arrays take the same initial-refusal stance as
        # lists: N is unbounded in the type grammar and elements may nest, so
        # no pre-transfer size bound is established here.
        return "unsupported"
    base = text.split("(")[0].strip().upper()
    if base in _FIXED_SCALAR_TYPES:
        return "fixed"
    if base in _VARIABLE_SCALAR_TYPES or base == "ENUM":
        return "variable"
    return "unsupported"


# ------------------------------------------------------- host limit ownership


def effective_limits(section: dict | None) -> dict:
    """Validate one ``query:``-section-shaped mapping against the built-in
    ceilings (tightening-only) and return the effective limits. ``None`` is
    the built-in default. Rejects unknown keys, booleans, zero, negatives,
    NaN/inf and attempted increases; then rejects a byte budget too small to
    carry even the compact refusal before it is ever used (spec 0014 §5)."""
    limits = dict(DEFAULT_QUERY_LIMITS)
    if section is None:
        return limits
    if not isinstance(section, dict):
        allowed = sorted(QUERY_LIMIT_KEYS)
        raise ValueError(f"query limits must be a mapping with the optional keys {allowed}")
    unknown = sorted(set(section) - QUERY_LIMIT_KEYS)
    if unknown:
        allowed = sorted(QUERY_LIMIT_KEYS)
        raise ValueError(f"query limits carry unsupported key(s) {unknown}; allowed: {allowed}")
    for key in _INT_LIMIT_KEYS:
        if key not in section:
            continue
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(
                f"query.{key} must be a positive integer (booleans, zero, negatives "
                f"and non-integers are rejected), got {value!r}"
            )
        if value > DEFAULT_QUERY_LIMITS[key]:
            raise ValueError(
                f"query.{key}={value} would RAISE the built-in ceiling "
                f"{DEFAULT_QUERY_LIMITS[key]} — the operator config may only tighten "
                "the query limits (spec 0014 §4)"
            )
        limits[key] = value
    seconds = section.get("execution_seconds")
    if seconds is not None:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            raise ValueError(
                f"query.execution_seconds must be a finite positive number, got {seconds!r}"
            )
        if seconds > DEFAULT_QUERY_LIMITS["execution_seconds"]:
            raise ValueError(
                f"query.execution_seconds={seconds} would RAISE the built-in ceiling "
                f"{DEFAULT_QUERY_LIMITS['execution_seconds']} — the operator config may "
                "only tighten the query limits (spec 0014 §4)"
            )
        limits["execution_seconds"] = float(seconds)
    assert_refusal_representable(limits)
    return limits


def load_host_query_limits(root: str | Path) -> dict:
    """The effective query ceilings of one HOST project root: the built-in
    defaults tightened by the working tree's optional ``ariadne.yaml``
    ``query:`` section (plan 0014 §2 — the LOGICAL host configuration, never
    a pinned candidate/snapshot's inert copy). An invalid or raising section
    is an explicit error naming the field."""
    registry_path = Path(root) / "ariadne.yaml"
    if not registry_path.is_file():
        return dict(DEFAULT_QUERY_LIMITS)
    try:
        doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{registry_path}: not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    section = doc.get("query")
    if section is None:
        return dict(DEFAULT_QUERY_LIMITS)
    try:
        return effective_limits(section)
    except ValueError as exc:
        raise ValueError(f"{registry_path}: {exc}") from None


def refusal_forms() -> list[dict]:
    """Representative refusal bodies for EVERY stable code the operations can
    emit (fix pass 1, finding 2a): each is the worst case under the bounded-by-
    construction rules — maximal fixed message, truncated-identifier samples
    at the cap, worst-case compact numbers — so a budget that carries these
    carries every refusal the runtime can produce."""
    longest = "c" * _MAX_IDENTIFIER_CHARS
    columns = [longest] * _MAX_IDENTIFIER_COLUMNS + [f"+{10**6} more"]
    huge = 10**12  # a worst-case compact observed count/lower bound
    return [
        row_limit_refusal(1000, 1001).refusal(),
        byte_limit_refusal(
            huge, observed={"response_bytes_lower_bound": huge, "rows_lower_bound": huge}
        ).refusal(),
        mcp_byte_limit_refusal(huge, observed={"transport_bytes_lower_bound": huge}).refusal(),
        cell_limit_refusal(huge, columns).refusal(),
        type_unsupported_refusal(columns).refusal(),
        deadline_refusal(20.0).refusal(),
    ]


def assert_refusal_representable(limits: dict) -> None:
    """A byte budget that cannot carry even the compact refusals is rejected
    before use (spec 0014 §5: refusal representations must fit their
    effective bounds). Every emittable refusal form — not just one — must
    fit the core budget (fix pass 1, finding 2a)."""
    for form in refusal_forms():
        size = result_json_bytes(form)
        if size > limits["response_bytes"]:
            raise ValueError(
                f"query.response_bytes={limits['response_bytes']} cannot represent "
                f"every refusal form (largest {size} bytes) — nothing could ever "
                "be answered or refused within it"
            )


def oversized_error_refusal() -> QueryResultError:
    """The bounded explicit refusal that REPLACES an oversized generic error
    representation (spec 0014 §5, fix pass 1 finding 2b/2c): fitting errors
    keep their verbatim codes/messages; an exception dump too large for its
    transport is never sent as-is."""
    return QueryResultError(
        RESULT_BYTE_LIMIT,
        "the error representation exceeded the response byte ceiling and was "
        "withheld — this bounded refusal replaces it; narrow the request or "
        "selected fields",
    )


def bounded_error_object(error: dict, budget: float) -> dict:
    """One ASSEMBLED error object (every field the caller appended — message,
    stable codes, planner candidates) that is guaranteed to fit ``budget``
    bytes serialized (fix pass 2, finding 2a: the effective host budget, and
    every appended field is accounted): a fitting error keeps its verbatim
    content; an oversized representation is replaced wholesale by the bounded
    explicit refusal (spec 0014 §5)."""
    if len(json.dumps({"error": error}, default=json_default).encode("utf-8")) <= budget:
        return error
    bounded = oversized_error_refusal()
    return {"type": error.get("type"), "message": str(bounded), "code": bounded.code}


# ---------------------------------------------------- accounting and preflight


def completeness(returned_rows: int) -> dict:
    """The additive fitting-answer metadata (spec 0014 §5): complete for the
    caller's full logical request (``scope: requested_query``), including any
    explicit post-aggregate limit — not all source rows."""
    return {
        "status": "complete",
        "complete": True,
        "scope": "requested_query",
        "returned_rows": returned_rows,
    }


def account_rows(limits: dict, envelope: dict, rows: list[dict]) -> None:
    """Incremental full-envelope accounting (spec 0014 §4 guard 4, fix pass
    1 finding 5): every NON-ROW metadata component is serialized per-
    component into a running total — never the whole envelope at once — and
    each row's exact serialized size is added one at a time; accounting STOP
    at the ceiling, so an oversized answer is refused without building the
    complete unrestricted JSON. The final exact whole-envelope check
    (:func:`finalize_response`) runs only after these parts already fit, so
    it is bounded work on an already-fitting answer."""
    budget = limits["response_bytes"]
    total = 2  # the outer braces
    for key, value in envelope.items():
        if key == "rows":
            continue
        total += len(json.dumps(key).encode("utf-8")) + 2
        total += len(json.dumps(value, default=json_default).encode("utf-8")) + 2
        if total > budget:
            raise byte_limit_refusal(
                budget, observed={"response_bytes_lower_bound": total, "rows_lower_bound": 0}
            )
    for index, row in enumerate(rows):
        total += len(json.dumps(row, default=json_default).encode("utf-8")) + 2
        if total > budget:
            raise byte_limit_refusal(
                budget,
                observed={"response_bytes_lower_bound": total, "rows_lower_bound": index + 1},
            )


def finalize_response(limits: dict, result: dict, *, response_measure=None) -> None:
    """The final exact gates before an answer may be returned or staged: the
    complete core envelope under the canonical codec, then the ACTUAL selected
    transport representation when the adapter supplied a measure (spec 0014
    §4 guard 5) — the MCP measure counts the SDK's escaped text, not just the
    inner dict."""
    size = result_json_bytes(result)
    if size > limits["response_bytes"]:
        raise byte_limit_refusal(
            limits["response_bytes"],
            observed={
                "response_bytes_lower_bound": size,
                "rows_lower_bound": len(result.get("rows") or []),
            },
        )
    if response_measure is not None:
        size = int(response_measure(result))
        if size > limits["mcp_response_bytes"]:
            raise mcp_byte_limit_refusal(
                limits["mcp_response_bytes"],
                observed={"transport_bytes_lower_bound": size},
            )
