"""``ariadne-authoring`` — the local command surface of harness-led authoring
(spec 2026-09-24-0005 "Authoring interface and lifecycle"; issue #13 exposes
the source-proposal pair, issue #14 adds inputs, issue #15 adds submit/review,
issue #34 adds the Git-backed proposal seam start/read/edit).

Follows the ``ariadne`` CLI's JSON contract: one JSON value on stdout for
success; one ``{"error": {"type", "message"}}`` object on stderr plus exit 1
for failure, message verbatim.

    ariadne-authoring propose-sources --file FILE [--project DIR]
    ariadne-authoring approve-sources --digest DIGEST [--project DIR]
    ariadne-authoring inputs [--document REF ...] [--part N] [--project DIR]
    ariadne-authoring submit --file FILE [--base-digest DIGEST] [--project DIR]
    ariadne-authoring review [--part N] [--project DIR]
    ariadne-authoring start [--base-revision REV] [--project DIR]
    ariadne-authoring read --proposal ID --kind KIND [--name N] [--section S]
                            [--part N] [--project DIR]
    ariadne-authoring edit --proposal ID --expected-revision REV --file FILE
                            [--project DIR]

``approve-sources`` is HUMAN-ONLY and runs on the server host (ADR-0013): the
packaged skill must never invoke it, and it is excluded from every MCP tool
surface. ``submit`` and ``review`` are harness-invocable; they stage and expose
proposals but NEVER approve, promote, or serve anything — the exact-digest
Promotion gate is the separate human-only ``ariadne-promote --digest DIGEST``
(ADR-0003). The ``--project`` default is the working directory — locally the
project root; remotely the server's single configured project, whose
filesystem root no client argument ever selects.

``start``/``read``/``edit`` (issue #34/G2, spec 2026-10-02-0009 §§3–4) drive
isolated Git authoring proposals over the project's own Git repository:
``start`` derives the system-generated proposal ID, branch and worktree;
``edit`` applies one complete artifact edit revision-checked (``--file -``
reads the edit JSON from stdin); ``read`` returns one bounded artifact part of
the current candidate. Validation and review of a candidate are LATER
slices and have no command here yet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from ariadne.authoring import (
    AuthoringProject,
    approve_sources,
    harness_inputs,
    propose_sources,
    review_bundle,
    submit_bundle,
)


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

    inputs = sub.add_parser(
        "inputs",
        help="measured harness inputs (harness-invocable, no model): approved-source "
        "profile, source-linked converted document evidence, optional Seed Notes",
    )
    inputs.add_argument(
        "--document",
        action="append",
        default=[],
        dest="documents",
        help="document reference inside the project input area data/docs/ "
        "(repeatable; large documents arrive in bounded parts)",
    )
    inputs.add_argument(
        "--part",
        type=int,
        default=1,
        help="which bounded part of each document's converted text (default: 1)",
    )
    inputs.add_argument(
        "--sample-rows",
        type=int,
        default=None,
        help="profile only the first N rows per table; sample statistics are not full-table facts",
    )
    inputs.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    submit = sub.add_parser(
        "submit",
        help="submit the harness model's complete proposed bundle (Seed Notes + OSI "
        "+ OKF pages as relative paths/contents) for deterministic validation "
        "and staged review — never approval or promotion",
    )
    submit.add_argument(
        "--file",
        required=True,
        help='submission JSON: {"files": [{path, content}], "documents": '
        '[reference, ...], "base_digest": ...} — documents name input-area '
        "references whose citations the service verifies itself",
    )
    submit.add_argument(
        "--base-digest",
        default=None,
        help="the CURRENT submission digest (required to repair an active proposal)",
    )
    submit.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    review_cmd = sub.add_parser(
        "review",
        help="the staged bundle proposal: inventory, provenance, validation state, "
        "exact content digest, verified document citations, bounded bodies — "
        "readable, never a signoff",
    )
    review_cmd.add_argument(
        "--part",
        type=int,
        default=1,
        help="which bounded part of each proposed body (default: 1)",
    )
    review_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    start = sub.add_parser(
        "start",
        help="start one isolated Git authoring proposal: system-generated ID, branch "
        "and worktree, from the current or a named base artifact revision "
        "(issue #34; never approval, validation or admission)",
    )
    start.add_argument(
        "--base-revision",
        default=None,
        help="known base commit SHA (default: current HEAD; a repository with no "
        "commits yet gets its human-created initial artifact revision)",
    )
    start.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    read_cmd = sub.add_parser(
        "read",
        help="read one candidate artifact (bounded part) of a proposal — inherited "
        "from the base when never edited",
    )
    read_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    read_cmd.add_argument(
        "--kind",
        required=True,
        choices=["model", "graph", "page", "seed_notes"],
        help="the typed artifact identity's kind",
    )
    read_cmd.add_argument("--name", default=None, help="artifact name (model/page)")
    read_cmd.add_argument("--section", default=None, help="OKF page section (page)")
    read_cmd.add_argument(
        "--part", type=int, default=1, help="which bounded part (default: 1)"
    )
    read_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    edit_cmd = sub.add_parser(
        "edit",
        help="apply one complete artifact edit to a proposal, revision-checked: a "
        "stale expected revision or a competing writer is refused without "
        "overwriting the candidate",
    )
    edit_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    edit_cmd.add_argument(
        "--expected-revision",
        required=True,
        help="the CURRENT candidate revision the edit is based on",
    )
    edit_cmd.add_argument(
        "--file",
        required=True,
        help='edit JSON, e.g. {"kind": "model", "name": "events", "content": ...} '
        '("-" reads stdin)',
    )
    edit_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )
    return parser


def _read_edit_document(file: str) -> dict:
    """The edit JSON from ``--file`` (or stdin with ``-``): malformed JSON is a
    UsageError so the one-JSON-error-object contract still holds."""
    raw = sys.stdin.read() if file == "-" else Path(file).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise UsageError(f"{file}: edit is not valid JSON: {exc}") from None


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "propose-sources":
            result: Any = propose_sources(args.file, project=args.project)
        elif args.command == "inputs":
            result = harness_inputs(
                project=args.project,
                documents=args.documents,
                part=args.part,
                sample_rows=args.sample_rows,
            )
        elif args.command == "submit":
            result = submit_bundle(args.file, project=args.project, base_digest=args.base_digest)
        elif args.command == "review":
            result = review_bundle(project=args.project, part=args.part)
        elif args.command == "start":
            result = AuthoringProject(args.project).start_proposal(args.base_revision)
        elif args.command == "read":
            identity: dict[str, str] = {"kind": args.kind}
            if args.name is not None:
                identity["name"] = args.name
            if args.section is not None:
                identity["section"] = args.section
            result = AuthoringProject(args.project).read_artifact(
                args.proposal, identity, part=args.part
            )
        elif args.command == "edit":
            result = AuthoringProject(args.project).edit_proposal(
                args.proposal, args.expected_revision, _read_edit_document(args.file)
            )
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
