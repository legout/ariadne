"""Local command surface for project-bound Git authoring.

The harness edits one explicit proposal by exact revision. Source declarations
are inert until a human approves the resolved identity; validation and review
never admit. Document originals stay operator-managed and external to Git.

``ariadne-authoring`` exposes proposal start/read/edit, source propose/approve,
measured inputs, validate/review, schema refresh, bounded mapping inspection,
term resolution and human-only local reconciliation. It has no staged bundle,
Promotion, legacy import/enrichment, direct root write or source-opening
fallback route.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.admission import reconcile
from ariadne.authoring import AuthoringProject


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
        "--proposal", required=True, help="append entries to this proposal's candidate registry"
    )
    propose.add_argument(
        "--expected-revision", required=True, help="the CURRENT candidate revision"
    )
    propose.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    approve = sub.add_parser(
        "approve-sources",
        help="record permission for an exact proposal identity (HUMAN-ONLY, server host)",
    )
    approve.add_argument(
        "--proposal",
        required=True,
        help="the proposal whose candidate registry is approved "
        "(requires --revision and --source-digest; records the permission in "
        ".ariadne/source-approvals.json without editing the candidate)",
    )
    approve.add_argument(
        "--revision",
        default=None,
        help="Git mode: the proposal's CURRENT candidate revision",
    )
    approve.add_argument(
        "--source-digest",
        default=None,
        help="Git mode: the resolved source digest propose-sources returned",
    )
    approve.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    inputs = sub.add_parser(
        "inputs",
        help="measured harness inputs (harness-invocable, no model): approved-source "
        "profile, source-linked converted document evidence, optional Seed Notes",
    )
    inputs.add_argument(
        "--proposal",
        required=True,
        help="measure this proposal's candidate — the profile opens only "
        "the operator-APPROVED resolved source identity (issue #35/G3)",
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

    review_cmd = sub.add_parser(
        "review",
        help="review a Git proposal's effective candidate — readable, never a signoff",
    )
    review_cmd.add_argument(
        "--proposal",
        required=True,
        help="proposal ID; review exact revisions, changes, citations and validation evidence — "
        "revisions, change inventory, bounded bodies, citations, the validation "
        "report, the structured mapping assertions with their assertion digests "
        "and confirmation eligibility (K4/issue #44: what a human may select "
        "with ariadne-admit --confirm-mapping), and a review digest (issue "
        "#36/G4; read-only, never a signoff)",
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
        choices=["model", "graph", "page", "seed_notes", "contract", "contract_bindings"],
        help="the typed artifact identity's kind",
    )
    read_cmd.add_argument("--name", default=None, help="artifact name (model/page)")
    read_cmd.add_argument("--section", default=None, help="OKF page section (page)")
    read_cmd.add_argument("--part", type=int, default=1, help="which bounded part (default: 1)")
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

    validate_cmd = sub.add_parser(
        "validate",
        help="validate one Git proposal's effective candidate at its EXACT final "
        "revision: finalize generated artifacts, commit any generated changes, "
        "run the complete check stack against the approved source identity and "
        "return that revision with its report/errors (issue #36/G4; never a signoff)",
    )
    validate_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    validate_cmd.add_argument(
        "--expected-revision",
        required=True,
        help="the CURRENT candidate revision the validation is based on (the "
        "response returns the FINAL revision after the finalize commit)",
    )
    validate_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    refresh_cmd = sub.add_parser(
        "refresh-schema",
        help="regenerate the core-owned physical schema facts of an explicit catalog "
        "asset list inside the proposal (issue #41): reads only the operator-approved "
        "resolved source identity, preserves authored meaning for identical columns, "
        "keeps changed columns' old meaning as reviewable history, an identical "
        "refresh is a no-op — never admission",
    )
    refresh_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    refresh_cmd.add_argument(
        "--expected-revision",
        required=True,
        help="the CURRENT candidate revision the refresh is based on",
    )
    refresh_cmd.add_argument(
        "--file",
        required=True,
        help="the explicit catalog asset list as JSON: either a bare list "
        "[{source, catalog, schema, table}, ...] or the object form "
        '{"assets": [...]} ("-" reads stdin)',
    )
    refresh_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    inspect_cmd = sub.add_parser(
        "inspect-mapping",
        help="measure one structured mapping-inspection candidate (equality/prefix/"
        "lookup families) under the operator's finite ceilings and retain the core "
        "receipt in the project evidence area (issue #43): reads only the "
        "operator-approved resolved source identity; never a page edit, approval "
        "or admission",
    )
    inspect_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    inspect_cmd.add_argument(
        "--expected-revision",
        required=True,
        help="the CURRENT candidate revision the inspection is based on",
    )
    inspect_cmd.add_argument(
        "--file",
        required=True,
        help='the inspection request as JSON ("-" reads stdin): the discriminated '
        'candidate object itself, or {"candidate": ..., "limits": {...}} with '
        "request-lowered limits",
    )
    inspect_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    resolve_cmd = sub.add_parser(
        "resolve-term",
        help="resolve a shared business term or an exact field lookup against the "
        "EXPLICITLY selected proposal's current candidate revision (issue #42; "
        "read-only, candidate identity visible; never admission)",
    )
    resolve_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    resolve_cmd.add_argument(
        "term",
        nargs="?",
        help="the term to resolve (whole aliases/phrases, case-insensitive)",
    )
    resolve_cmd.add_argument(
        "--file",
        help='resolve request JSON ("-" reads stdin): {"term": ...} or the exact '
        'field form {"resource": ..., "column": ...}',
    )
    resolve_cmd.add_argument(
        "--part", type=int, default=1, help="which bounded part of the matches (default 1)"
    )
    resolve_cmd.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    reconcile_cmd = sub.add_parser(
        "reconcile",
        help="record the clean new HEAD a human created by a local rebase/merge after "
        "the admitted baseline advanced (HUMAN-ONLY; requires the current admitted "
        "revision in the new revision's ancestry, invalidates old validation/review, "
        "never merges automatically)",
    )
    reconcile_cmd.add_argument("--proposal", required=True, help="the proposal ID")
    reconcile_cmd.add_argument(
        "--expected-revision",
        required=True,
        help="the proposal's CURRENT recorded candidate revision (the branch state "
        "before the human rebase/merge)",
    )
    reconcile_cmd.add_argument(
        "--revision",
        required=True,
        help="the clean new HEAD the human created in the proposal worktree",
    )
    reconcile_cmd.add_argument(
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


def _read_asset_list(file: str) -> list[dict]:
    """The explicit catalog asset list of a refresh-schema request from
    ``--file`` (or stdin with ``-``): a bare JSON list of identity tuples or
    the object form ``{"assets": [...]}`` — adapter input only, never a
    filesystem destination. Malformed JSON is a UsageError so the
    one-JSON-error-object contract still holds."""
    raw = sys.stdin.read() if file == "-" else Path(file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise UsageError(f"{file}: asset list is not valid JSON: {exc}") from None
    if isinstance(data, dict):
        data = data.get("assets")
    if not isinstance(data, list) or not data:
        raise UsageError(
            f"{file}: the asset list must be a non-empty JSON list of "
            '{source, catalog, schema, table} objects (or {{"assets": [...]}})'
        )
    return data


def _read_inspection_request(file: str) -> tuple[object, object]:
    """The inspection request from ``--file`` (or stdin with ``-``): the
    discriminated candidate object itself, or the object form
    ``{"candidate": ..., "limits": {...}}`` — adapter input only, never a
    filesystem destination. Malformed JSON is a UsageError so the
    one-JSON-error-object contract still holds."""
    raw = sys.stdin.read() if file == "-" else Path(file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise UsageError(f"{file}: inspection request is not valid JSON: {exc}") from None
    if isinstance(data, dict) and "candidate" in data and "family" not in data:
        return data["candidate"], data.get("limits")
    return data, None


def _read_source_entries(file: str) -> list[dict]:
    """The typed source entries of a registry-shaped Git proposal intake
    document: its ``sources:`` list."""
    return _read_source_intake(file)[0]


def _read_source_intake(file: str) -> tuple[list[dict], dict | None]:
    """The registry-shaped intake document's ``sources:`` list plus its
    optional ``storages:`` block (spec 0025 §5 — the CLI's existing
    registry-shaped input carries both top-level blocks)."""
    try:
        doc = yaml.safe_load(Path(file).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise UsageError(f"{file}: not valid YAML: {exc}") from None
    entries = doc.get("sources") if isinstance(doc, dict) else None
    if not isinstance(entries, list) or not entries:
        raise UsageError(f"{file}: no 'sources:' entries — declare the proposed sources")
    storages = doc.get("storages") if isinstance(doc, dict) else None
    if storages is not None and not isinstance(storages, dict):
        raise UsageError(f"{file}: 'storages:' is not a mapping")
    return entries, storages


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "propose-sources":
            entries, storages = _read_source_intake(args.file)
            result: Any = AuthoringProject(args.project).propose_sources(
                args.proposal, args.expected_revision, entries, storages
            )
        elif args.command == "inputs":
            result = AuthoringProject(args.project).inputs(
                args.proposal,
                documents=args.documents,
                part=args.part,
                sample_rows=args.sample_rows,
            )
        elif args.command == "review":
            result = AuthoringProject(args.project).review_proposal(args.proposal, part=args.part)
        elif args.command == "validate":
            result = AuthoringProject(args.project).validate_proposal(
                args.proposal, args.expected_revision
            )
        elif args.command == "refresh-schema":
            result = AuthoringProject(args.project).refresh_schema(
                args.proposal, args.expected_revision, _read_asset_list(args.file)
            )
        elif args.command == "inspect-mapping":
            candidate, limits = _read_inspection_request(args.file)
            result = AuthoringProject(args.project).inspect_mapping(
                args.proposal, args.expected_revision, candidate, limits=limits
            )
        elif args.command == "resolve-term":
            if args.file is not None:
                raw = (
                    sys.stdin.read()
                    if args.file == "-"
                    else Path(args.file).read_text(encoding="utf-8")
                )
                data = json.loads(raw)
                if isinstance(data, dict) and "term" in data:
                    request = data["term"]
                else:
                    request = data
            elif args.term is not None:
                request = args.term
            else:
                raise UsageError(
                    "resolve-term needs a TERM argument or --file with the request JSON"
                )
            result = AuthoringProject(args.project).resolve_term(
                args.proposal, request, part=args.part
            )
        elif args.command == "reconcile":
            # HUMAN-ONLY (issue #37/G5): records a local rebase/merge; never an
            # MCP/Agent tool and never an automatic merge.
            result = reconcile(args.project, args.proposal, args.expected_revision, args.revision)
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
        else:  # approve-sources is the human-only exact Git source permission
            result = AuthoringProject(args.project).approve_sources(
                args.proposal, args.revision, args.source_digest
            )
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
