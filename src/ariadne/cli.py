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
    ariadne query-records [--file PATH]        (bounded record selection over one
                                               known table, spec 0014 §3; stdin
                                               when absent; governed: false,
                                               nothing staged)
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

Promoted-root discovery (spec §5): an explicit ``--served PATH`` wins and must
contain both ``context_layer/`` and ``semantic_layer/models/``; otherwise
exactly two candidates are examined — the working directory, then ``./served``
— and exactly one must be valid (zero -> actionable error naming both layouts,
two -> ambiguity error demanding ``--served``; the CLI never guesses). Root
selection fails before a source connection is opened, and a ``define-metric``
payload is parsed before the runtime opens a source or executes it (spec §9).
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
from ariadne.discovery import DiscoveryRuntime
from ariadne.execution import DeadlineBudget  # pyright: ignore[reportMissingImports] — drift
from ariadne.planner import PlannerError
from ariadne.query import QueryRuntime  # pyright: ignore[reportMissingImports] — drift
from ariadne.query_results import QueryResultError  # pyright: ignore[reportMissingImports] — drift
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
        "required when no --sources/ariadne.yaml applies — the runtime never "
        "guesses a database)",
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
        help="legacy staging root for draft workflows (default: ./staging; an "
        "omitted --staging on the managed --project route uses <project>/staging)",
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
        "submitted result SQL as historical evidence (null for legacy records "
        "without it); never executed, never a ranking input",
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
        help="read-only project readiness diagnostics (spec 0016: kind, sources, "
        "governance state, backlog, skill drift, next steps — no source connection)",
    )
    status_cmd.add_argument(
        "--json",
        action="store_true",
        help="emit exactly one structured report object instead of human text "
        "(the spec-0001 usability amendment, this command only)",
    )
    review_cmd = sub.add_parser(
        "review", help="operator-only review walkthrough (unchanged human gates)"
    )
    review_roots = review_cmd.add_mutually_exclusive_group()
    review_roots.add_argument("--project", default=None, help="managed review before admission")
    review_roots.add_argument(
        "--served", default=None, help="legacy Promotion target, may be fresh"
    )
    review_cmd.add_argument("--proposal", default=None, help="one proposal; requires --project")
    review_cmd.add_argument(
        "--staging", default=None, help="legacy staging root (default: ./staging)"
    )
    setup_cmd = sub.add_parser(
        "setup", help="operator onboarding wizard (human gates are handoffs)"
    )
    setup_cmd.add_argument(
        "--legacy", action="store_true", help="new staged project, not a migration"
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
    # Order (spec §9): root selection first, then input parsing, and only then
    # runtime construction — which is where the read-only source connection
    # opens. Every earlier failure therefore precedes any connection, execution,
    # or staging.
    if args.command == "review":
        from ariadne import review

        return review.run(args, stdin)
    if args.command == "setup":
        from ariadne import (
            setup,  # pyright: ignore[reportAttributeAccessIssue] — new-module resolver drift
        )

        return setup.run(args, stdin)
    if args.command == "status":
        # spec 0016: status resolves its own DIAGNOSTIC route (a scaffold with
        # no admission is a report, never the missing-admission error) and must
        # never construct QueryRuntime — the lazy import keeps the query chain
        # above untouched and the composition seam explicit (ADR-0021).
        from ariadne import (
            status as status_module,  # pyright: ignore[reportAttributeAccessIssue] — drift: this lane's new module
        )

        return status_module.run(args)
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
    if args.command in ("save-example", "search-examples") and args.project is not None:
        if args.staging is not None:
            raise ValueError(
                "--staging does not select Git Examples; use proposal/revision selectors"
            )
    if args.command == "save-example":
        if (args.proposal is None) != (args.expected_revision is None):
            raise ValueError("--proposal and --expected-revision are required together")
        if args.proposal is not None and args.project is None:
            raise ValueError("Git proposal selectors require --project")
    if args.command == "search-examples":
        if (args.proposal is None) != (args.revision is None):
            raise ValueError("--proposal and --revision are required together")
        if args.proposal is not None and args.project is None:
            raise ValueError("candidate Example search requires --project")
        if args.proposal is not None:
            from ariadne import answer_examples

            assert args.project is not None and args.revision is not None
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
    if args.command in (  # parsed pre-runtime (spec §9)
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
            raise ValueError("resolve-term needs a TERM argument or --file with the request JSON")
    if root is None:
        if args.command == "search-examples":
            assert args.project is not None
            discovery = DiscoveryRuntime.open_project(args.project)
            result = asyncio.run(
                discovery.search_examples(
                    args.query,
                    limit=args.limit,
                    include_history=args.include_history,
                    include_sql=args.include_sql,
                )
            )
            print(json.dumps(result, default=_json_default))
            return 0
        if args.project is None:  # unreachable via the legacy-root detection, kept type-honest
            raise ValueError(
                "no project selected: pass --project DIR (managed) or --served PATH (legacy)"
            )
        # An omitted --staging (None) lets the managed factory apply its
        # project-owned default <project>/staging — the CLI's CWD-relative
        # legacy default must never pull staging outside the selected project
        # (issue #40 finding 1); an explicit path still wins. ONE request
        # budget covers the managed construction AND its operation (fix pass
        # 1, finding 1): a CLI invocation can never spend ~2x the deadline.
        if args.command == "search":
            discovery = DiscoveryRuntime.open_project(args.project, staging_dir=args.staging)
            return _print_discovery(discovery, args)
        limits = query_results.load_host_query_limits(args.project)
        runtime = QueryRuntime.open_project(
            args.project,
            staging_dir=args.staging,
            deadline_budget=DeadlineBudget(limits["execution_seconds"]),
        )
    else:
        sources_path = default_registry_path(args.sources, args.db)
        if sources_path is None and not args.db:
            raise ValueError(
                "no source configured: pass --sources REGISTRY or --db SQLITE, or "
                "declare sources in ./ariadne.yaml — the runtime never guesses a "
                "database to query"
            )
        # Issue #56/S1 (plan 0014 §2): legacy use reads the FIXED host CWD's
        # operator ``query:`` ceilings — an explicit --sources stays source
        # identity only, never a second implicit limit root. The same ONE
        # request budget bounds this construction and its operation.
        if args.command == "search":
            discovery = DiscoveryRuntime(
                root / "semantic_layer",
                root / "context_layer",
                args.db,
                staging_dir="staging" if args.staging is None else args.staging,
                sources=sources_path,
            )
            return _print_discovery(discovery, args)
        limits = query_results.load_host_query_limits(Path.cwd())
        runtime = QueryRuntime(
            root / "semantic_layer",
            root / "context_layer",
            args.db,
            staging_dir="staging" if args.staging is None else args.staging,
            sources=sources_path,
            query_limits=limits,
            deadline_budget=DeadlineBudget(limits["execution_seconds"]),
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
                proposal=args.proposal,
                revision=args.revision,
            )
        )
    elif args.command == "query-metrics":
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.query_metrics(definition))
    elif args.command == "query-detail":
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.query_detail(definition))
    elif args.command == "query-records":
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.query_records(definition))
    else:  # define-metric
        assert definition is not None  # _read_definition ran above
        result = asyncio.run(runtime.define_metric(definition))
    print(json.dumps(result, default=_json_default))
    return 0


def _print_discovery(runtime: DiscoveryRuntime, args: argparse.Namespace) -> int:
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
    --project root, else the fixed legacy host CWD — with the built-in default
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
