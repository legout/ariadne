"""The one ``ariadne`` CLI (spec 0040 §3.1). The command table below is exhaustive:
there are no aliases for removed executables or flags. Every command prints text by
default and exactly one JSON value with ``--json``; every failure writes one
``{"error": {"type", "message"}}`` object to stderr and exits 1.

This module owns argument parsing and output only. Behavior lives in the library
modules it reuses (``query``, ``discovery``, ``draft``, ``approve``, ``init``,
``status``, ``skill``, ``migrate``, ``profiler``, ``serve``). Approval and discard are
interactive human commands: they require a terminal and no flag skips the prompt.
"""

from __future__ import annotations

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


class UsageError(ValueError):
    """An invocation the CLI itself rejects (argparse-level)."""


class _Parser(argparse.ArgumentParser):
    """argparse that fails through UsageError, so a malformed invocation still writes
    exactly one JSON error object to stderr."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")


def _text(value: Any, indent: int = 0) -> str:
    """A small human rendering of a JSON-shaped result."""
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.append(_text(item, indent + 1))
            else:
                lines.append(f"{pad}{key}: {_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_text(item, indent + 1))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_scalar(value)}"


def _scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=_json_default)
    return "null" if value is None else str(value)


def _emit(result: Any, args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        print(json.dumps(result, default=_json_default))
    else:
        print(_text(result))
    return 0


def _read_json(file: str | None, stdin: Any, what: str) -> Any:
    try:
        text = Path(file).read_text(encoding="utf-8") if file else stdin.read()
    except OSError as exc:
        raise ValueError(f"cannot read {what}: {exc}") from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{what} is not valid JSON: {exc}") from exc


def build_parser() -> _Parser:
    common = _Parser(add_help=False)
    common.add_argument("--project", default=".", help="the project directory (default: .)")
    common.add_argument("--json", action="store_true", help="print one JSON value")
    json_only = _Parser(add_help=False)
    json_only.add_argument("--json", action="store_true", help="print one JSON value")
    parser = _Parser(prog="ariadne", description="Governed metrics for agents and people.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    p = sub.add_parser("init", parents=[common], help="create a project in DIR (default: .)")
    p.add_argument("dir", nargs="?", default=None)
    p.add_argument(
        "--yes", action="store_true", help="never prompt (refuse without a Git identity)"
    )

    p = sub.add_parser("add", parents=[common], help="declare a source in the active draft")
    p.add_argument(
        "target", help="a file path, URL, or (postgres) the env variable NAME of the DSN"
    )
    p.add_argument("--name")
    p.add_argument("--type")
    p.add_argument("--storage", help="a declared storage profile name")

    draft_cmd = sub.add_parser("draft", help="the active draft")
    draft_sub = draft_cmd.add_subparsers(dest="draft_command", required=True, parser_class=_Parser)
    draft_sub.add_parser("status", parents=[common], help="the active draft's state")
    p = draft_sub.add_parser("edit", parents=[common], help="apply one typed edit file")
    p.add_argument("file", help="JSON edit file ('-' for stdin)")
    draft_sub.add_parser("rebase", parents=[common], help="rebase the draft onto the served state")
    p = draft_sub.add_parser("discard", parents=[common], help="discard the active draft")
    p.add_argument("--yes", action="store_true", help="skip the confirmation (not for approve)")

    sub.add_parser("validate", parents=[common], help="validate the active draft")
    p = sub.add_parser("diff", parents=[common], help="the draft against the served state")
    p.add_argument("--full", action="store_true", help="include the complete escaped content diff")
    p = sub.add_parser("approve", parents=[common], help="approve the draft (interactive)")
    p.add_argument("--confirm-mapping", action="append", default=[], metavar="SEL")
    sub.add_parser("status", parents=[common], help="served revision, approval, draft state")

    p = sub.add_parser("query", parents=[common], help="governed metric query")
    p.add_argument("metric")
    p.add_argument("--by", action="append", default=[], metavar="DIM")
    p.add_argument("--filter", action="append", default=[], metavar="F")
    p = sub.add_parser("detail", parents=[common], help="governed detail query (JSON request)")
    p.add_argument("--file", help="request JSON file (stdin when absent)")

    sub.add_parser("metrics", parents=[common], help="list governed metrics")
    sub.add_parser("datasets", parents=[common], help="list queryable datasets")
    p = sub.add_parser("search", parents=[common], help="discover metrics, pages, terms, examples")
    p.add_argument("text")
    p.add_argument("--limit", type=int, default=5)
    p = sub.add_parser("page", parents=[common], help="read one context page")
    p.add_argument("path")

    p = sub.add_parser("serve", help="the MCP server (optional extra)")
    p.add_argument("--toolset", choices=("analyst", "authoring", "combined"), default="combined")
    p.add_argument("--project", default=".")
    p.add_argument("--http", action="store_true")
    p.add_argument("--http-host", default="127.0.0.1")
    p.add_argument("--http-port", type=int, default=8000)
    p.add_argument("--http-container", action="store_true")
    p.add_argument("--http-allowed-host", action="append", default=[])
    p.add_argument("--http-allowed-origin", action="append", default=[])

    skill_cmd = sub.add_parser("skill", help="the packaged agent skill")
    skill_sub = skill_cmd.add_subparsers(dest="skill_command", required=True, parser_class=_Parser)
    skill_sub.add_parser("path", parents=[json_only])
    p = skill_sub.add_parser("install", parents=[json_only])
    p.add_argument("--scope", choices=("user", "project"), default="user")
    p.add_argument("--agent", default=None)
    skill_sub.add_parser("status", parents=[json_only])

    sub.add_parser("profile", parents=[common], help="profile the approved served sources")
    sub.add_parser("migrate", parents=[common], help="Ossie 0.2 -> 0.3 into the active draft")
    return parser


def _expected(project: Path) -> tuple[int, str] | None:
    from ariadne import draft

    view = draft.status(project)
    return None if view is None else (view["generation"], view["candidate_revision"])


def _draft_commands(args: argparse.Namespace, stdin: Any) -> int:
    from ariadne import draft
    from ariadne.authoring import AuthoringProject

    project = Path(args.project).resolve()
    if args.draft_command == "status":
        try:
            view = draft.status(project)
        except draft.UnconfirmedSourceApproval as exc:
            _emit(
                {
                    "source_approval_pending": True,
                    "message": str(exc),
                    "command": exc.command,
                },
                args,
            )
            return 1  # pending is not a clean state
        return _emit(view if view is not None else {"draft": None}, args)
    if args.draft_command == "edit":
        edit = _read_json(None if args.file == "-" else args.file, stdin, "the edit file")
        result = AuthoringProject(project).apply_edit(edit)
        return _emit(result, args)
    expected = _expected(project)
    if expected is None:
        raise ValueError("there is no active draft")
    if args.draft_command == "rebase":
        return _emit(draft.rebase(project, expected), args)
    if not args.yes:
        from ariadne import approve

        approve.require_tty(sys.stdin, sys.stdout)
        prompt_to = sys.stderr if args.json else sys.stdout  # JSON: stdout is the result only
        if not approve.ask(sys.stdin, prompt_to, "Discard the active draft?"):
            raise ValueError("refused at the prompt — nothing was changed")
    return _emit(draft.discard(project, expected), args)


def _diff(project: Path, full: bool = False) -> dict:
    from ariadne import approve, authoring, draft, proposals

    view = draft.status(project)
    if view is None:
        raise ValueError("there is no active draft")
    record = proposals._load_record(project, draft.proposal_of(project, _pair(view)))
    review = authoring.review_proposal(project, record["id"])
    kind = approve.classify(project, view, record)["kind"] if not view["stale"] else "stale"
    result = {
        "approval_kind": kind,
        "draft": view,
        "changes": review["changes"],
        "validation": (review["report"] or {}).get("status", "unvalidated"),
        "validation_stale": review["validation_stale"],
    }
    if full:  # the complete content the prompt may have cut off, control characters escaped
        result["content_diff"] = [
            approve.esc(line)
            for line in approve.diff_records(project, record["base_revision"], review["revision"])
        ]
    return result


def _pair(view: dict) -> tuple[int, str]:
    return (view["generation"], view["candidate_revision"])


def _query(args: argparse.Namespace) -> dict:
    limits = query_results.load_host_query_limits(args.project)
    discovery = DiscoveryRuntime.open_project(args.project)
    discovery._refuse_unsupported("get_metric")
    runtime = QueryRuntime.open_project(
        args.project,
        deadline_budget=DeadlineBudget(limits["execution_seconds"]),
        discovery=discovery if discovery._managed is not None else None,
    )
    if args.filter:
        request = {"metrics": [args.metric], "dimensions": args.by, "filters": args.filter}
        return asyncio.run(runtime.query_metrics(request))
    return asyncio.run(runtime.get_metric(args.metric, args.by or None))


def _dispatch(args: argparse.Namespace, stdin: Any) -> int:
    command = args.command
    if command == "serve":
        from ariadne import serve

        argv = ["--project", args.project, "--toolset", args.toolset]
        if args.http:
            argv += ["--http", "--http-host", args.http_host, "--http-port", str(args.http_port)]
            argv += ["--http-container"] if args.http_container else []
            for host in args.http_allowed_host:
                argv += ["--http-allowed-host", host]
            for origin in args.http_allowed_origin:
                argv += ["--http-allowed-origin", origin]
        return serve.main(argv)
    if command == "skill":
        import contextlib
        import io

        from ariadne import skill

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured if args.json else sys.stdout):
            code = skill.run(
                args.skill_command,
                getattr(args, "scope", "user"),
                getattr(args, "agent", None),
            )
        if args.json:
            print(json.dumps({"ok": code == 0, "output": captured.getvalue().splitlines()}))
        return code
    if command == "init":
        from ariadne import init

        result = init.init_project(
            args.dir or args.project,
            assume_yes=args.yes,
            stdin=stdin,
            stdout=sys.stdout,  # the terminal check stays on the original streams
            prompt=sys.stderr if args.json else None,  # JSON: only the prompt text moves
        )
        return _emit(result, args)
    project = Path(args.project).resolve()
    if command == "add":
        from ariadne import authoring_sources

        entry = authoring_sources.source_entry(
            args.target, name=args.name, type=args.type, storage=args.storage
        )
        active = _expected(project)
        result = authoring_sources.add_sources(project, active, [entry])
        return _emit({k: v for k, v in result.items() if k != "sources"}, args)
    if command == "draft":
        return _draft_commands(args, stdin)
    if command == "validate":
        from ariadne import draft

        expected = _expected(project)
        if expected is None:
            raise ValueError("there is no active draft to validate")
        result = draft.validate(project, expected)
        return _emit({k: result[k] for k in ("ok", "status", "errors", "revision", "draft")}, args)
    if command == "diff":
        return _emit(_diff(project, full=args.full), args)
    if command == "approve":
        from ariadne import approve

        return _emit(
            approve.approve(
                project,
                confirm_mappings=args.confirm_mapping,
                stdin=sys.stdin,
                stdout=sys.stdout,
                display=sys.stderr if args.json else None,  # JSON: stdout carries only the result
            ),
            args,
        )
    if command == "status":
        from ariadne import status as status_module

        return status_module.run(args)
    if command == "migrate":
        from ariadne import migrate

        return _emit(migrate.migrate_project(project), args)
    if command == "profile":
        from ariadne import profiler

        return _emit(profiler.profile_served(project), args)
    # read side: governed queries and discovery
    if command == "query":
        return _emit(_query(args), args)
    if command == "detail":
        request = _read_json(args.file, stdin, "the detail request")
        limits = query_results.load_host_query_limits(args.project)
        discovery = DiscoveryRuntime.open_project(args.project)
        discovery._refuse_unsupported("query_detail")
        runtime = QueryRuntime.open_project(
            args.project,
            deadline_budget=DeadlineBudget(limits["execution_seconds"]),
            discovery=discovery if discovery._managed is not None else None,
        )
        return _emit(asyncio.run(runtime.query_detail(request)), args)
    discovery = DiscoveryRuntime.open_project(args.project)
    if command == "metrics":
        return _emit(asyncio.run(discovery.list_metrics()), args)
    if command == "datasets":
        limits = query_results.load_host_query_limits(args.project)
        runtime = QueryRuntime.open_project(
            args.project,
            deadline_budget=DeadlineBudget(limits["execution_seconds"]),
            discovery=discovery if discovery._managed is not None else None,
        )
        return _emit(asyncio.run(runtime.list_datasets()), args)
    if command == "search":
        report = asyncio.run(discovery.discover(args.text, limit=args.limit))
        if args.json:
            return _emit(report, args)
        print("Discovery only — use --json for full native payloads; no answer is executed.")
        for kind, group in report["groups"].items():
            print(f"{kind.title()} — {group['status']}")
            print(json.dumps(group, default=_json_default, indent=2))
        return 0
    if command == "page":
        return _emit(asyncio.run(discovery.read_context_page(args.path)), args)
    raise UsageError(f"unknown command {command!r}")


def _effective_error_budget(args: argparse.Namespace | None) -> float:
    try:
        root = args.project if args is not None and getattr(args, "project", None) else Path.cwd()
        return query_results.load_host_query_limits(root)["response_bytes"]
    except Exception:
        return query_results.DEFAULT_QUERY_LIMITS["response_bytes"]


def main(argv: list[str] | None = None, stdin: Any = None) -> int:
    """Console-script entry point: 0 on success, 1 after one JSON error object on stderr."""
    args = None
    try:
        args = build_parser().parse_args(argv)
        return _dispatch(args, sys.stdin if stdin is None else stdin)
    except QueryResultError as exc:
        print(json.dumps(exc.refusal(), default=_json_default), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # an interruption of a draft command (e.g. in the cleanup region of a recovery) stays in
        # the error envelope: one JSON error object, non-zero exit
        print(
            json.dumps(
                {
                    "error": {
                        "type": "KeyboardInterrupt",
                        "message": "interrupted — rerun the command; "
                        "'ariadne draft status' finishes any pending recovery",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 130
    except Exception as exc:  # one JSON error object, message verbatim
        error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, PlannerError):
            error["code"] = exc.code
            if exc.candidates:
                error["candidates"] = list(exc.candidates)
        error = query_results.bounded_error_object(error, _effective_error_budget(args))
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
