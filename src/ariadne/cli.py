"""Local JSON CLI: the five Ariadne operations as flat subcommands (spec
2026-09-23-0001 §4, ADR-0012).

A thin adapter over :class:`ariadne.query.QueryRuntime` — this module owns
argument parsing, promoted-root discovery, and the JSON wire contract only;
all governed behavior (compilation, execution, context, grain, staging) stays
in the runtime:

    ariadne list-metrics
    ariadne list-datasets
    ariadne search-context QUERY [--limit N]
    ariadne get-metric NAME [--dimension NAME ...] [--start VALUE] [--end VALUE]
    ariadne define-metric [--file PATH]        (stdin when --file is absent)
    ariadne query-metrics [--file PATH]        (the admitted multi-fact graph,
                                               issue #30; stdin when absent)
    ariadne query-detail [--file PATH]         (root-dataset projection, no fan-out)
    ariadne save-example [--file PATH]          (stdin when absent; issue #19 —
                                               explicit answer-example submission)
    ariadne search-examples QUERY [--limit N] [--include-history]
    ariadne resolve-term [TERM] [--file PATH] [--part N]   (issue #42: shared
                                               terminology resolution; the exact
                                               {resource, column} field form
                                               arrives through --file)

Every successful invocation writes exactly one JSON value plus a newline to
stdout and nothing else; temporal values serialize as ISO-8601 strings and
decimal values as strings (no precision loss). Every failed invocation writes
exactly one ``{"error": {"type", "message"}}`` object to stderr, exits nonzero,
and writes no success value to stdout — runtime messages stay verbatim.

The optional MCP transport (``ariadne-serve`` and its fixed-toolset aliases
``ariadne-analyst-mcp``/``ariadne-authoring-mcp``, issue #38/G6) registers
these same QueryRuntime operations as tools; this local CLI needs no MCP
installation and its behavior is unchanged by the toolset split.

Promoted-root discovery (spec §5): an explicit ``--served PATH`` wins and must
contain both ``context_layer/`` and ``semantic_layer/models/``; otherwise
exactly two candidates are examined — the working directory, then ``./served``
— and exactly one must be valid (zero -> actionable error naming both layouts,
two -> ambiguity error demanding ``--served``; the CLI never guesses). Root
selection fails before a source connection is opened, and a ``define-metric``
payload is parsed before the runtime executes or stages anything (spec §9).
"""

import argparse
import asyncio
import json
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

from ariadne.planner import PlannerError
from ariadne.query import QueryRuntime  # pyright: ignore[reportMissingImports] — drift
from ariadne.sources import default_registry_path


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


def _is_served_root(path: Path) -> bool:
    return (path / "context_layer").is_dir() and (path / "semantic_layer" / "models").is_dir()


def _resolve_served_root(explicit: str | None) -> Path:
    """Spec §5 root selection — runs before any source connection is opened."""
    if explicit is not None:
        if not explicit:
            raise ValueError("--served must be a non-empty promoted-root path")
        root = Path(explicit)
        if not _is_served_root(root):
            raise ValueError(
                f"--served {explicit} is not a promoted root: expected both "
                "context_layer/ and semantic_layer/models/ under it"
            )
        return root
    cwd = Path.cwd()
    candidates = [("the working directory", cwd), ("./served", cwd / "served")]
    valid = [(label, path) for label, path in candidates if _is_served_root(path)]
    if not valid:
        raise ValueError(
            "no promoted artifacts found: expected context_layer/ and "
            "semantic_layer/models/ in the working directory or under ./served "
            "(pass --served PATH to select a promoted root explicitly)"
        )
    if len(valid) == 2:
        raise ValueError(
            "ambiguous promoted roots: both the working directory and ./served "
            "contain context_layer/ and semantic_layer/models/ — pass --served "
            "PATH to select one"
        )
    return valid[0][1]


def _read_definition(file: str | None, stdin: Any, what: str = "definition") -> dict:
    """One JSON object from --file PATH or stdin (spec §4). Parsed before the
    runtime is constructed, so invalid JSON can execute and stage nothing
    (spec §9)."""
    try:
        text = Path(file).read_text(encoding="utf-8") if file else stdin.read()
    except OSError as exc:
        raise ValueError(f"cannot read {what}: {exc}") from exc
    # pi-lens-ignore: unchecked-throwing-call-python
    return json.loads(text)


def build_parser() -> _Parser:
    common = _Parser(add_help=False)
    group = common.add_mutually_exclusive_group()
    group.add_argument(
        "--sources",
        default=None,
        help="source registry YAML (ADR-0010; takes precedence over the ambient ./ariadne.yaml)",
    )
    group.add_argument(
        "--db",
        default=None,
        help="SQLite database to attach read-only (mutually exclusive with --sources; "
        "default: examples/retail-demo/data/demo.db when no --sources/ariadne.yaml "
        "applies)",
    )
    group.add_argument(
        "--project",
        default=None,
        help="managed Git data project: query its pinned human-admitted snapshot and "
        "approved source identity (issue #37/G5; mutually exclusive with --sources/--db "
        "and --served — a project without a valid admission is an error, never a "
        "fallback)",
    )
    common.add_argument(
        "--served",
        default=None,
        help="promoted artifact root (must contain context_layer/ and "
        "semantic_layer/models/; default: the working directory or ./served, "
        "unambiguously)",
    )
    common.add_argument(
        "--staging",
        default=None,
        help="staging root for auto-staged ad-hoc proposals (default: ./staging; an "
        "omitted --staging on the managed --project route stages under "
        "<project>/staging)",
    )
    parser = _Parser(
        prog="ariadne",
        description="Local JSON interface to the Ariadne governed-metric runtime.",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    sub.add_parser("list-metrics", parents=[common], help="list governed metrics")
    sub.add_parser("list-datasets", parents=[common], help="list queryable tables")

    search = sub.add_parser("search-context", parents=[common], help="search OKF pages")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    get = sub.add_parser("get-metric", parents=[common], help="query a governed metric")
    get.add_argument("name")
    get.add_argument("--dimension", action="append", help="repeatable group-by dimension")
    get.add_argument("--start", help="range start on the primary date dimension")
    get.add_argument("--end", help="range end on the primary date dimension")

    define = sub.add_parser("define-metric", parents=[common], help="define an ad-hoc metric")
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

    save = sub.add_parser(
        "save-example",
        parents=[common],
        help="save an explicit answer-example draft (issue #19)",
    )
    save.add_argument("--file", help="JSON submission file (stdin when absent)")

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
    return parser


def _dispatch(args: argparse.Namespace, stdin: Any) -> int:
    # Order (spec §9): root selection first, then input parsing, and only then
    # runtime construction — which is where the read-only source connection
    # opens. Every earlier failure therefore precedes any connection, execution,
    # or staging.
    if args.project is not None:
        # The managed Git route (issue #37/G5): the pinned admitted snapshot and
        # its approved source identity replace the explicit legacy roots; a
        # project without a valid admission is an explicit error, never a
        # fallback to proposal worktrees or mutable project files.
        if args.served is not None:
            raise ValueError(
                "--project (managed Git route) and --served (explicit legacy root) are "
                "mutually exclusive — pass one artifact root, not both"
            )
        root = None
    else:
        root = _resolve_served_root(args.served)
    definition = None
    if args.command in (  # parsed pre-runtime (spec §9)
        "define-metric",
        "save-example",
        "query-metrics",
        "query-detail",
    ):
        definition = _read_definition(
            args.file,
            stdin,
            "submission" if args.command == "save-example" else "request",
        )
    resolve_request = None
    if args.command == "resolve-term":  # adapter input, parsed pre-runtime
        if args.file is not None:
            data = _read_definition(
                args.file if args.file != "-" else None,
                stdin,
                "resolve-term request",
            )
            if isinstance(data, dict) and "term" in data:
                resolve_request = data["term"]
            else:
                resolve_request = data
        elif args.term is not None:
            resolve_request = args.term
        else:
            raise ValueError(
                "resolve-term needs a TERM argument or --file with the request JSON"
            )
    if root is None:
        # An omitted --staging (None) lets the managed factory apply its
        # project-owned default <project>/staging — the CLI's CWD-relative
        # legacy default must never pull staging outside the selected project
        # (issue #40 finding 1); an explicit path still wins.
        runtime = QueryRuntime.open_project(args.project, staging_dir=args.staging)
    else:
        sources_path = default_registry_path(args.sources, args.db)
        runtime = QueryRuntime(
            root / "semantic_layer",
            root / "context_layer",
            args.db or "examples/retail-demo/data/demo.db",
            staging_dir="staging" if args.staging is None else args.staging,
            sources=sources_path,
        )
    if args.command == "list-metrics":
        result = asyncio.run(runtime.list_metrics())
    elif args.command == "list-datasets":
        result = asyncio.run(runtime.list_datasets())
    elif args.command == "search-context":
        result = asyncio.run(runtime.search_context(args.query, limit=args.limit))
    elif args.command == "resolve-term":
        assert resolve_request is not None  # parsed pre-runtime above
        result = asyncio.run(runtime.resolve_term(resolve_request, part=args.part))
    elif args.command == "get-metric":
        time_range = {
            key: value
            for key, value in (("start", args.start), ("end", args.end))
            if value is not None
        }
        result = asyncio.run(runtime.get_metric(args.name, args.dimension, time_range or None))
    elif args.command == "save-example":
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.save_example(definition))
    elif args.command == "search-examples":
        result = asyncio.run(
            runtime.search_examples(
                args.query, limit=args.limit, include_history=args.include_history
            )
        )
    elif args.command == "query-metrics":
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.query_metrics(definition))
    elif args.command == "query-detail":
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.query_detail(definition))
    else:  # define-metric
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.define_metric(definition))
    print(json.dumps(result, default=_json_default))
    return 0


def main(argv: list[str] | None = None, stdin: Any = None) -> int:
    """Console-script entry point. Returns the process exit code: 0 on success,
    1 after writing exactly one JSON error object to stderr."""
    try:
        return _dispatch(build_parser().parse_args(argv), sys.stdin if stdin is None else stdin)
    except Exception as exc:  # one JSON error object, message verbatim (spec §4)
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
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
