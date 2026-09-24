"""``ariadne-authoring`` — the local command surface of harness-led authoring
(spec 2026-09-24-0005 "Authoring interface and lifecycle"; issue #13 exposes
the source-proposal pair only, later slices add inputs/submit/review).

Follows the ``ariadne`` CLI's JSON contract: one JSON value on stdout for
success; one ``{"error": {"type", "message"}}`` object on stderr plus exit 1
for failure, message verbatim.

    ariadne-authoring propose-sources --file FILE [--project DIR]
    ariadne-authoring approve-sources --digest DIGEST [--project DIR]

``approve-sources`` is HUMAN-ONLY and runs on the server host (ADR-0013): the
packaged skill must never invoke it, and it is excluded from every MCP tool
surface. The ``--project`` default is the working directory — locally the
project root; remotely the server's single configured project, whose
filesystem root no client argument ever selects.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, NoReturn

from ariadne.authoring import approve_sources, propose_sources


class UsageError(ValueError):
    """An invocation the CLI itself rejects (argparse-level) — reported through
    the same one-JSON-error-object contract as failures (ariadne.cli pattern)."""


class _Parser(argparse.ArgumentParser):
    """argparse that fails through UsageError instead of exiting with usage
    text, so a malformed invocation still writes exactly one JSON error object
    to stderr."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> _Parser:
    parser = _Parser(
        prog="ariadne-authoring",
        description="Harness-led authoring: propose sources for operator approval.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    propose = sub.add_parser(
        "propose-sources",
        help="validate and store an inert source proposal (harness-invocable)",
    )
    propose.add_argument("--file", required=True, help="proposal YAML (registry-shaped)")
    propose.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    approve = sub.add_parser(
        "approve-sources",
        help="install the digest-matched pending proposal into ariadne.yaml "
        "(HUMAN-ONLY, server host; the skill never invokes this)",
    )
    approve.add_argument("--digest", required=True, help="the reviewed proposal digest")
    approve.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "propose-sources":
            result: Any = propose_sources(args.file, project=args.project)
        else:  # approve-sources
            result = approve_sources(args.digest, project=args.project)
    except Exception as exc:  # one JSON error object, message verbatim
        print(
            json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
