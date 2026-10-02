"""``ariadne-authoring`` — the local command surface of harness-led authoring
(spec 2026-09-24-0005 "Authoring interface and lifecycle"; issue #13 exposes
the source-proposal pair, issue #14 adds inputs, issue #15 adds submit/review,
issue #34 adds the Git-backed proposal seam start/read/edit, issue #35 adds
the Git-aware propose-sources/approve-sources/inputs).

Follows the ``ariadne`` CLI's JSON contract: one JSON value on stdout for
success; one ``{"error": {"type", "message"}}`` object on stderr plus exit 1
for failure, message verbatim.

    ariadne-authoring propose-sources --file FILE [--project DIR]
    ariadne-authoring propose-sources --proposal ID --expected-revision REV
                                       --file FILE [--project DIR]
    ariadne-authoring approve-sources --digest DIGEST [--project DIR]
    ariadne-authoring approve-sources --proposal ID --revision REV
                                       --source-digest DIGEST [--project DIR]
    ariadne-authoring inputs [--document REF ...] [--part N] [--project DIR]
    ariadne-authoring inputs --proposal ID [--document REF ...] [--part N]
                             [--sample-rows N] [--project DIR]
    ariadne-authoring submit --file FILE [--base-digest DIGEST] [--project DIR]
    ariadne-authoring review [--part N] [--project DIR]
    ariadne-authoring review --proposal ID [--part N] [--project DIR]
    ariadne-authoring start [--base-revision REV] [--project DIR]
    ariadne-authoring read --proposal ID --kind KIND [--name N] [--section S]
                            [--part N] [--project DIR]
    ariadne-authoring edit --proposal ID --expected-revision REV --file FILE
                            [--project DIR]
    ariadne-authoring validate --proposal ID --expected-revision REV
                              [--project DIR]
    ariadne-authoring reconcile --proposal ID --expected-revision OLD
                                --revision NEW [--project DIR]
    ariadne-authoring import-legacy --from-root ROOT [--project DIR]   (HUMAN-ONLY)

``approve-sources`` is HUMAN-ONLY and runs on the server host (ADR-0013): the
packaged skill must never invoke it, and it is excluded from every MCP tool
surface. The legacy ``--digest`` route installs entries into the project's
``ariadne.yaml``; the Git mode (``--proposal``/``--revision``/
``--source-digest``) records the operator's permission for the proposal's
EXACT resolved source identity in the operator-owned
``.ariadne/source-approvals.json`` without editing the already-committed
candidate (issue #35/G3, spec §5). ``submit`` and ``review`` are
harness-invocable; they stage and expose proposals but NEVER approve,
promote, or serve anything — the exact-digest Promotion gate is the separate
human-only ``ariadne-promote --digest DIGEST`` (ADR-0003). The ``--project``
default is the working directory — locally the project root; remotely the
server's single configured project, whose filesystem root no client argument
ever selects.

MCP surface mapping (issue #38/G6, spec §6): the MCP registrations expose the
GIT contract above — ``authoring_start_proposal``/``authoring_read_artifact``/
``authoring_edit_proposal``/``authoring_propose_sources`` (Git mode:
``--proposal``/``--expected-revision`` + typed entries)/``authoring_inputs``
(Git mode: ``--proposal``)/``authoring_upload_document``/
``authoring_validate_proposal``/``authoring_review_proposal`` — with model
arguments carrying only proposal IDs, revisions and typed artifact
identities. A legacy complete-bundle ``submit``/``review`` payload composes as
``start`` + one ``edit`` per artifact + ``validate``/``review --proposal``
instead, and no MCP entry ever guesses a proposal for an old bundle payload
(the local legacy staged-bundle route is retained documented for its named
consumers — never an MCP surface).

``start``/``read``/``edit`` (issue #34/G2, spec 2026-10-02-0009 §§3–4) drive
isolated Git authoring proposals over the project's own Git repository:
``start`` derives the system-generated proposal ID, branch and worktree;
``edit`` applies one complete artifact edit revision-checked (``--file -``
reads the edit JSON from stdin); ``read`` returns one bounded artifact part of
the current candidate. Git-mode ``propose-sources``/``inputs`` (issue #35/G3)
address the same proposals: a typed source proposal commits into the candidate
registry and returns the resolved identity digest (never opening anything);
``inputs`` measures ONLY the operator-approved resolved identity plus the
operator-bound documents. ``validate`` (issue #36/G4) finalizes the generated
artifacts, commits any generated changes, validates the EXACT final commit
against the approved source identity and returns that revision with its
report/errors — never a signoff. ``review --proposal`` (issue #36/G4) is the
read-only Git-candidate review; ``review`` without ``--proposal`` keeps its
legacy staged-bundle meaning. ``reconcile`` (issue #37/G5) is HUMAN-ONLY like
``approve-sources`` and never an MCP/native Agent tool: after the human performs
a local rebase/merge (the admitted baseline advanced past the branch), it
records the clean new HEAD — requiring the current admitted revision in the
candidate's ancestry — and invalidates the old revision's validation/review; it
never merges automatically or clears an inconsistent interrupted transition or
exhausted repair state.

``import-legacy`` (issue #39/G7) is HUMAN-ONLY the same way: the explicit
legacy-artifact migration of :mod:`ariadne.migration` (spec §7/AC9), exposed
ONLY here — never an MCP or Agent tool. It copies a legacy project's selected
artifacts (registry, Seed Notes, models, graph, OKF pages) into a fresh
UNADMITTED Git proposal — or into the human-created initial artifact revision
when the project has none yet — preserving pending legacy staging byte-for-byte
and NEVER admitting: a Git commit of existing files is not human review. The
retained legacy ``submit``/``review`` staged-bundle route keeps its named
consumers (tests/test_authoring.py, tests/test_promote.py,
tests/test_multifact.py, tests/test_authoring_mcp.py and every legacy staged
project); see docs/how-to/git-authoring.md for the complete legacy → new
mapping.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.admission import reconcile
from ariadne.authoring import (
    AuthoringProject,
    approve_sources,
    harness_inputs,
    propose_sources,
    review_bundle,
    submit_bundle,
)
from ariadne.migration import import_legacy


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
        "--proposal",
        default=None,
        help="Git mode: append the entries to this proposal's candidate registry "
        "(requires --expected-revision); returns the resolved identity digest",
    )
    propose.add_argument(
        "--expected-revision",
        default=None,
        help="Git mode: the CURRENT candidate revision the proposal is based on",
    )
    propose.add_argument(
        "--project", default=".", help="project root holding ariadne.yaml (default: .)"
    )

    approve = sub.add_parser(
        "approve-sources",
        help="install the digest-matched pending proposal into ariadne.yaml "
        "(HUMAN-ONLY, server host; the skill never invokes this)",
    )
    approve.add_argument(
        "--digest",
        default=None,
        help="legacy route: the reviewed pending-proposal digest to install",
    )
    approve.add_argument(
        "--proposal",
        default=None,
        help="Git mode: the proposal whose candidate registry is approved "
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
        default=None,
        help="Git mode: measure this proposal's candidate — the profile opens only "
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
        "--proposal",
        default=None,
        help="Git mode: review this proposal's effective candidate — exact "
        "revisions, change inventory, bounded bodies, citations, the validation "
        "report and a review digest (issue #36/G4; read-only, never a signoff)",
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

    import_cmd = sub.add_parser(
        "import-legacy",
        help="HUMAN-ONLY: copy a legacy project's selected artifacts (registry, Seed "
        "Notes, models, graph, OKF pages) into a fresh UNADMITTED Git proposal — or "
        "the initial artifact revision when the project has none; never admission",
    )
    import_cmd.add_argument(
        "--from-root",
        required=True,
        help="the legacy project root to import from (its ariadne.yaml, seed notes, "
        "served semantic/context layers; pending staging is preserved untouched)",
    )
    import_cmd.add_argument(
        "--project", default=".", help="the managed Git data project (default: .)"
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


def _read_source_entries(file: str) -> list[dict]:
    """The typed source entries of a registry-shaped intake document (the
    same shape the legacy route validates): its ``sources:`` list."""
    try:
        doc = yaml.safe_load(Path(file).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise UsageError(f"{file}: not valid YAML: {exc}") from None
    entries = doc.get("sources") if isinstance(doc, dict) else None
    if not isinstance(entries, list) or not entries:
        raise UsageError(f"{file}: no 'sources:' entries — declare the proposed sources")
    return entries


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "propose-sources":
            if args.proposal is not None:
                if args.expected_revision is None:
                    raise UsageError(
                        "Git-mode propose-sources requires --expected-revision"
                    )
                result: Any = AuthoringProject(args.project).propose_sources(
                    args.proposal, args.expected_revision, _read_source_entries(args.file)
                )
            else:
                result = propose_sources(args.file, project=args.project)
        elif args.command == "inputs":
            if args.proposal is not None:
                result = AuthoringProject(args.project).inputs(
                    args.proposal,
                    documents=args.documents,
                    part=args.part,
                    sample_rows=args.sample_rows,
                )
            else:
                result = harness_inputs(
                    project=args.project,
                    documents=args.documents,
                    part=args.part,
                    sample_rows=args.sample_rows,
                )
        elif args.command == "submit":
            result = submit_bundle(args.file, project=args.project, base_digest=args.base_digest)
        elif args.command == "review":
            if args.proposal is not None:
                result = AuthoringProject(args.project).review_proposal(
                    args.proposal, part=args.part
                )
            else:
                result = review_bundle(project=args.project, part=args.part)
        elif args.command == "validate":
            result = AuthoringProject(args.project).validate_proposal(
                args.proposal, args.expected_revision
            )
        elif args.command == "reconcile":
            # HUMAN-ONLY (issue #37/G5): records a local rebase/merge; never an
            # MCP/Agent tool and never an automatic merge.
            result = reconcile(
                args.project, args.proposal, args.expected_revision, args.revision
            )
        elif args.command == "import-legacy":
            # HUMAN-ONLY (issue #39/G7): the explicit legacy-artifact migration —
            # never an MCP/Agent tool, never admission.
            result = import_legacy(project=args.project, from_root=args.from_root)
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
        else:  # approve-sources: legacy --digest, or Git-mode identity approval
            git_mode = (args.proposal, args.revision, args.source_digest)
            if any(flag is not None for flag in git_mode):
                if args.digest is not None:
                    raise UsageError(
                        "approve-sources takes either --digest (legacy) or "
                        "--proposal/--revision/--source-digest (Git mode), not both"
                    )
                if any(flag is None for flag in git_mode):
                    raise UsageError(
                        "Git-mode approve-sources requires --proposal, --revision "
                        "and --source-digest together"
                    )
                result = AuthoringProject(args.project).approve_sources(
                    args.proposal, args.revision, args.source_digest
                )
            else:
                if args.digest is None:
                    raise UsageError(
                        "approve-sources requires --digest DIGEST (legacy) or "
                        "--proposal/--revision/--source-digest (Git mode)"
                    )
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
