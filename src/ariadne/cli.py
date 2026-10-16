"""Local JSON CLI: the five Ariadne operations as flat subcommands (spec
2026-09-23-0001 §4, ADR-0012).

A thin adapter over :class:`ariadne.query.QueryRuntime` — this module owns
argument parsing, project selection, and the JSON wire contract only; all
query behavior (compilation, execution, context and grain) stays in the runtime:

    ariadne list-metrics
    ariadne list-datasets
    ariadne search-context QUERY [--limit N]
    ariadne get-metric NAME [--dimension NAME ...] [--start VALUE] [--end VALUE]
    ariadne define-metric [--file PATH]        (stdin when --file is absent)
    ariadne query-metrics [--file PATH]        (the admitted multi-fact graph,
                                               issue #30; stdin when absent)
    ariadne query-detail [--file PATH]         (root-dataset projection, no fan-out)
    ariadne query-records [--file PATH]        (bounded record selection over one
                                               known table, spec 0014 §3; stdin
                                               when absent; governed: false,
                                               no durable write)
    ariadne save-example [--file PATH]          (stdin when absent; issue #19 —
                                               explicit answer-example submission)
    ariadne search-examples QUERY [--limit N] [--include-history]
                                               [--include-sql] (issue #68: opt-in "
                                               "sql_provenance per hit, spec 0023)
    ariadne resolve-term [TERM] [--file PATH] [--part N]   (issue #42: shared
                                               terminology resolution; the exact
                                               {resource, column} field form
                                               arrives through --file)
    ariadne status [--json]                   (spec 0016: read-only project
                                               readiness diagnostics — human-
                                               first text, one JSON object with
                                               --json; never constructs the
                                               query runtime)

Every successful invocation writes exactly one JSON value plus a newline to
stdout and nothing else; temporal values serialize as ISO-8601 strings and
decimal values as strings (no precision loss). Every failed invocation writes
exactly one ``{"error": {"type", "message"}}`` object to stderr, exits nonzero,
and writes no success value to stdout — runtime messages stay verbatim.

The optional MCP transport (``ariadne-serve`` and its fixed-toolset aliases
``ariadne-analyst-mcp``/``ariadne-authoring-mcp``, issue #38/G6) registers
these same QueryRuntime operations as tools; this local CLI needs no MCP
installation and its behavior is unchanged by the toolset split.

Every public operation is bound to the current Git project (``--project DIR``,
default ``.``). Governed queries require its exact valid human admission; no
plain artifact-root or mutable-candidate fallback exists. Request payloads are
parsed before the admitted runtime opens a source (spec §9).
"""

import argparse
import asyncio
import json
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

from ariadne import (
    query_results,  # pyright: ignore[reportAttributeAccessIssue] — drift: analyzer binds the venv copy
)
from ariadne.discovery import DiscoveryRuntime, _DiscoverySession
from ariadne.execution import DeadlineBudget  # pyright: ignore[reportMissingImports] — drift
from ariadne.planner import PlannerError
from ariadne.query import QueryRuntime  # pyright: ignore[reportMissingImports] — drift
from ariadne.query_results import QueryResultError  # pyright: ignore[reportMissingImports] — drift


class UsageError(ValueError):
    """An invocation the CLI itself rejects (argparse-level) — reported through
    the same one-JSON-error-object contract as runtime failures."""


class _Parser(argparse.ArgumentParser):
    """argparse that fails through UsageError instead of exiting with usage
    text, so a malformed invocation still writes exactly one JSON error object
    to stderr (spec §4)."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _json_default(value: Any) -> Any:
    """Spec §4 serialization: temporal -> ISO-8601 strings, Decimal -> strings."""
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")


def _read_definition(file: str | None, stdin: Any, what: str = "definition") -> dict:
    """One JSON object from --file PATH or stdin (spec §4). Parsed before the
    runtime is constructed, so malformed input prevents source opening or execution
    (spec §9)."""
    try:
        text = Path(file).read_text(encoding="utf-8") if file else stdin.read()
    except OSError as exc:
        raise ValueError(f"cannot read {what}: {exc}") from exc
    # pi-lens-ignore: unchecked-throwing-call-python
    return json.loads(text)


def build_parser() -> _Parser:
    common = _Parser(add_help=False)
    common.add_argument(
        "--project",
        default=".",
        help="Git data project; governed calls use its exact human-admitted snapshot (default: .)",
    )
    parser = _Parser(
        prog="ariadne",
        description="Local JSON interface to the Ariadne governed-metric runtime.",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    sub.add_parser("list-metrics", parents=[common], help="list governed metrics")
    sub.add_parser("list-datasets", parents=[common], help="list queryable tables")

    discover = sub.add_parser(
        "search", parents=[common], help="discover metrics, pages, terms and examples (read-only)"
    )
    discover.add_argument("query")
    discover.add_argument("--limit", type=int, default=5)
    discover.add_argument("--json", action="store_true", help="emit one grouped report object")

    search = sub.add_parser("search-context", parents=[common], help="search OKF pages")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    get = sub.add_parser("get-metric", parents=[common], help="query a governed metric")
    get.add_argument("name")
    get.add_argument("--dimension", action="append", help="repeatable group-by dimension")
    get.add_argument("--start", help="range start on the primary date dimension")
    get.add_argument("--end", help="range end on the primary date dimension")

    define = sub.add_parser("define-metric", parents=[common], help="run an unsaved ad-hoc metric")
    define.add_argument("--file", help="JSON definition file (stdin when absent)")

    metrics = sub.add_parser(
        "query-metrics", parents=[common], help="query the admitted multi-fact graph"
    )
    metrics.add_argument("--file", help="JSON request file (stdin when absent)")

    detail = sub.add_parser(
        "query-detail",
        parents=[common],
        help="project one root dataset's fields through safe lookup paths",
    )
    detail.add_argument("--file", help="JSON request file (stdin when absent)")

    records = sub.add_parser(
        "query-records",
        parents=[common],
        help="bounded record selection over one known table: {dataset, fields, "
        "filters?, timestamp?, order, limit?} — no aggregation, no staging, "
        "governed: false (spec 0014 §3)",
    )
    records.add_argument("--file", help="JSON record request file (stdin when absent)")

    save = sub.add_parser(
        "save-example",
        parents=[common],
        help="save an explicit answer-example draft (issue #19)",
    )
    save.add_argument("--file", help="JSON submission file (stdin when absent)")
    save.add_argument("--proposal", help="existing Git authoring proposal ID")
    save.add_argument("--expected-revision", help="current candidate revision for --proposal")

    examples = sub.add_parser(
        "search-examples", parents=[common], help="search saved answer examples"
    )
    examples.add_argument("query")
    examples.add_argument("--limit", type=int, default=10)
    examples.add_argument(
        "--include-history",
        action="store_true",
        help="include stale/superseded/rejected records as labeled history",
    )
    examples.add_argument(
        "--include-sql",
        action="store_true",
        help="include each hit's stored sql_provenance as provenance.sql — the exact "
        "submitted result SQL as historical evidence (null when the record has no "
        "stored SQL); never executed, never a ranking input",
    )
    examples.add_argument("--proposal", help="explicitly browse one Git authoring proposal")
    examples.add_argument("--revision", help="recorded current candidate revision for --proposal")
    resolve = sub.add_parser(
        "resolve-term",
        parents=[common],
        help="resolve a shared business term or an exact field lookup against the "
        "served context (issue #42: bounded matches with exact bindings, scope, "
        "ambiguity and claim status; issue #44: confirmed only with recorded "
        "human admission evidence — a context-only admitted project serves this "
        "without a metric catalog; read-only)",
    )
    resolve.add_argument(
        "term",
        nargs="?",
        help="the term to resolve (whole aliases/phrases, case-insensitive)",
    )
    resolve.add_argument(
        "--file",
        help="resolve request JSON from a file or stdin ('-'): the exact field "
        "form of the request; a positional TERM is the plain term form",
    )
    resolve.add_argument(
        "--part", type=int, default=1, help="which bounded part of the matches (default 1)"
    )
    status_cmd = sub.add_parser(
        "status",
        parents=[common],
        help=(
            "read-only Git project readiness, proposal and admission diagnostics — "
            "no source connection"
        ),
    )
    status_cmd.add_argument(
        "--json",
        action="store_true",
        help="emit exactly one structured report object instead of human text "
        "(the spec-0001 usability amendment, this command only)",
    )
    review_cmd = sub.add_parser("review", help="operator-only review walkthrough for Git proposals")
    review_cmd.add_argument("--project", default=".", help="Git project root")
    review_cmd.add_argument(
        "--proposal", default=None, help="one proposal; default lists pending proposals"
    )
    setup_cmd = sub.add_parser(
        "setup", help="operator onboarding wizard (human gates are handoffs)"
    )
    setup_cmd.add_argument("--project", default=".", help="directory to scaffold or resume")
    setup_cmd.add_argument("--no-input", action="store_true", help="scaffold/detect/report only")
    setup_cmd.add_argument(
        "--agents", action="store_true", help="install the selected packaged skill"
    )
    setup_cmd.add_argument("--agent", choices=("universal", "pi", "claude", "hermes"))
    setup_cmd.add_argument("--scope", choices=("project", "user"), default="project")
    return parser


def _dispatch(args: argparse.Namespace, stdin: Any) -> int:
    # Parse selectors and payloads before constructing an admitted runtime, which
    # is the only public path that opens a source connection.
    if args.command == "review":
        from ariadne import review

        return review.run(args, stdin)
    if args.command == "setup":
        from ariadne import setup

        return setup.run(args, stdin)
    if args.command == "status":
        from ariadne import status as status_module

        return status_module.run(args)
    if args.command == "save-example" and (args.proposal is None) != (
        args.expected_revision is None
    ):
        raise ValueError("--proposal and --expected-revision are required together")
    if args.command == "search-examples" and (args.proposal is None) != (args.revision is None):
        raise ValueError("--proposal and --revision are required together")
    if args.command == "search-examples" and args.proposal is not None:
        from ariadne import answer_examples

        result = answer_examples.search_candidate(
            args.project,
            args.query,
            proposal=args.proposal,
            revision=args.revision,
            limit=args.limit,
            include_history=args.include_history,
            include_sql=args.include_sql,
        )
        print(json.dumps(result, default=_json_default))
        return 0

    definition = None
    if args.command in (
        "define-metric",
        "save-example",
        "query-metrics",
        "query-detail",
        "query-records",
    ):
        definition = _read_definition(
            args.file,
            stdin,
            "submission" if args.command == "save-example" else "request",
        )
    resolve_request = None
    if args.command == "resolve-term":
        if args.file is not None:
            data = _read_definition(
                args.file if args.file != "-" else None, stdin, "resolve-term request"
            )
            resolve_request = data["term"] if isinstance(data, dict) and "term" in data else data
        elif args.term is not None:
            resolve_request = args.term
        else:
            raise ValueError("resolve-term needs a TERM argument or --file with the request JSON")

    if args.command == "search":
        return _print_discovery(DiscoveryRuntime.open_project(args.project), args)
    limits = query_results.load_host_query_limits(args.project)
    runtime = QueryRuntime.open_project(
        args.project,
        deadline_budget=DeadlineBudget(limits["execution_seconds"]),
    )
    if args.command == "list-metrics":
        result = asyncio.run(runtime.list_metrics())
    elif args.command == "list-datasets":
        result = asyncio.run(runtime.list_datasets())
    elif args.command == "search-context":
        result = asyncio.run(runtime.search_context(args.query, limit=args.limit))
    elif args.command == "resolve-term":
        assert resolve_request is not None
        result = asyncio.run(runtime.resolve_term(resolve_request, part=args.part))
    elif args.command == "get-metric":
        time_range = {
            key: value
            for key, value in (("start", args.start), ("end", args.end))
            if value is not None
        }
        result = asyncio.run(runtime.get_metric(args.name, args.dimension, time_range or None))
    elif args.command == "save-example":
        assert definition is not None
        result = asyncio.run(
            runtime.save_example(
                definition, proposal=args.proposal, expected_revision=args.expected_revision
            )
        )
    elif args.command == "search-examples":
        result = asyncio.run(
            runtime.search_examples(
                args.query,
                limit=args.limit,
                include_history=args.include_history,
                include_sql=args.include_sql,
            )
        )
    elif args.command == "query-metrics":
        assert definition is not None
        result = asyncio.run(runtime.query_metrics(definition))
    elif args.command == "query-detail":
        assert definition is not None
        result = asyncio.run(runtime.query_detail(definition))
    elif args.command == "query-records":
        assert definition is not None
        result = asyncio.run(runtime.query_records(definition))
    else:
        assert definition is not None
        result = asyncio.run(runtime.define_metric(definition))
    print(json.dumps(result, default=_json_default))
    return 0


def _print_discovery(runtime: _DiscoverySession, args: argparse.Namespace) -> int:
    report = asyncio.run(runtime.discover(args.query, limit=args.limit))
    if args.json:
        print(json.dumps(report, default=_json_default))
    else:
        print("Discovery only — use --json for full native payloads; no answer is executed.")
        for kind, group in report["groups"].items():
            print(f"{kind.title()} — {group['status']}")
            summary = group
            if kind == "pages" and group["status"] == "available":
                # Summarize passages without substituting them for the full rule bodies.
                summary = {
                    **group,
                    "items": [
                        {key: value for key, value in hit.items() if key != "content"}
                        for hit in group["items"]
                    ],
                }
            print(json.dumps(summary, default=_json_default, indent=2))
    return 0


def _effective_error_budget(args: argparse.Namespace | None) -> float:
    """The EFFECTIVE host response budget for bounding generic CLI errors
    (fix pass 2, finding 2a): the route the invocation selected — the managed
    --project root (the CLI's current-directory default) — with the built-in default
    when no invocation was parsed or the host config itself is unusable."""
    try:
        root = args.project if args is not None and args.project is not None else Path.cwd()
        return query_results.load_host_query_limits(root)["response_bytes"]
    except Exception:
        return query_results.DEFAULT_QUERY_LIMITS["response_bytes"]


def main(argv: list[str] | None = None, stdin: Any = None) -> int:
    """Console-script entry point. Returns the process exit code: 0 on success,
    1 after writing exactly one JSON error object to stderr."""
    args = None
    try:
        args = build_parser().parse_args(argv)
        return _dispatch(args, sys.stdin if stdin is None else stdin)
    except QueryResultError as exc:
        # Issue #56/S1 (spec 0014 §5): one bounded structured refusal on
        # stderr with a nonzero exit — never a successful partial on stdout.
        # The refusal body is fixed-size by construction and was validated to
        # fit the effective bounds when the host ceilings were loaded.
        print(json.dumps(exc.refusal(), default=_json_default), file=sys.stderr)
        return 1
    except Exception as exc:  # one JSON error object, message verbatim (spec §4)
        # Fix pass 2, finding 2a (spec 0014 §5): a FITTING error keeps its
        # verbatim fields; an oversized error representation is replaced by
        # the bounded explicit refusal under the EFFECTIVE host budgets —
        # every appended field (stable code, planner candidates) accounted.
        error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, PlannerError):
            # mf-t5 fix F4 (spec rev 1 "Failure and compatibility behavior"):
            # the planner's stable failure fields ride the envelope for the new
            # query-metrics/query-detail operations — code, plus candidates
            # when the refusal carries retry guidance. Legacy commands raise
            # plain errors and keep the {type, message} shape unchanged.
            error["code"] = exc.code
            if exc.candidates:
                error["candidates"] = list(exc.candidates)
        error = query_results.bounded_error_object(error, _effective_error_budget(args))
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
