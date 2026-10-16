"""Operator-only walkthrough for one explicit Git proposal.

A terminal is a UX condition, not identity or independent approval authority.
No agent/MCP surface imports this adapter.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

from ariadne import admission, authoring, status


def _ask(stdin: Any, prompt: str) -> bool:
    print(prompt + " [y/N] ", end="", flush=True)
    answer = stdin.readline()
    if not answer:
        raise EOFError("review input ended")
    return answer.strip().lower() in ("y", "yes")


def _post_state(project: Path) -> None:
    print("Admission did not complete successfully; do not assume rollback or retry.")
    try:
        current = admission.load_current(project)
        print("Current admitted revision: " + (current["commit"] if current else "none"))
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Admission descriptor inspection refused: {type(exc).__name__}: {exc}")
    print("Read-only admission-status inspection:")
    print(shlex.join(["ariadne", "status", "--project", str(project), "--json"]))


def _delegate(argv: list[str], stdin: Any, project: Path) -> int:
    previous = sys.stdin
    sys.stdin = stdin
    try:
        try:
            code = admission.main(argv)
        except (KeyboardInterrupt, EOFError) as exc:
            print(f"Delegated operation interrupted: {type(exc).__name__}", file=sys.stderr)
            code = 1
        except SystemExit as exc:
            code = int(exc.code or 0)
        except Exception:
            _post_state(project)
            raise
    finally:
        sys.stdin = previous
    if code:
        _post_state(project)
    return code


def _managed(project: Path, proposal: str | None, stdin: Any, interactive: bool) -> int:
    if proposal is None:
        pending = status._managed_proposals(project, None)
        if not pending:
            print("No pending proposals.")
        for entry in pending:
            print(json.dumps(entry, indent=2))
            print(
                shlex.join(
                    ["ariadne", "review", "--project", str(project), "--proposal", entry["id"]]
                )
            )
        return 0

    api = authoring.AuthoringProject(project)
    payload = api.review_proposal(proposal)
    print("Native ariadne-authoring review payload (reading is not admission):")
    print(json.dumps(payload, indent=2))
    parts = [payload]
    for part in range(2, max((f["parts"] for f in payload["files"]), default=1) + 1):
        more = api.review_proposal(proposal, part=part)
        if (more["revision"], more["review_digest"]) != (
            payload["revision"],
            payload["review_digest"],
        ):
            raise ValueError(
                "review changed during presentation — nothing invoked; review again explicitly"
            )
        print(json.dumps(more, indent=2))
        parts.append(more)
    print("Review digest: " + payload["review_digest"])
    selected = []
    for entry in payload["mapping_assertions"]:
        if entry["claim"] != "asserted" or not entry["confirmable"]:
            continue
        selection = f"{entry['reference']}:{entry['mapping']}"
        print("Eligible assertion (selection is inert; default skip):")
        print(json.dumps(entry, indent=2))
        print("Required scope/representations — exact reviewed Reference page:")
        for reviewed_part in parts:
            for body in reviewed_part["files"]:
                if body["resource"] == "context_layer/" + entry["page"]:
                    print(body["text"])
        print("Verified citation/evidence identities:")
        print(json.dumps(payload["citations"], indent=2))
        print("Optional repeatable argument: " + shlex.join(["--confirm-mapping", selection]))
        if interactive and _ask(
            stdin, f"Select --confirm-mapping {selection} for the final decision?"
        ):
            selected.append(selection)
    argv = [
        "--project",
        str(project),
        "--proposal",
        proposal,
        "--revision",
        payload["revision"],
        "--reviewed-digest",
        payload["review_digest"],
        "--confirm",
    ]
    for selection in selected:
        argv.extend(["--confirm-mapping", selection])
    print("Final Candidate Revision: " + payload["revision"])
    print("Review digest: " + payload["review_digest"])
    print("Complete mapping selection: " + json.dumps(selected))
    print("Exact remaining operator admission command:")
    print(shlex.join(["ariadne-admit", *argv]))
    if not interactive:
        print("Non-interactive: display only; no admission invoked.")
        return 0
    if not _ask(stdin, "Admit this exact revision/digest with the complete selection above?"):
        print("Declined: no admission invoked.")
        return 0
    return _delegate(argv, stdin, project)


def run(args, stdin: Any) -> int:
    interactive = stdin.isatty() and sys.stdout.isatty()
    try:
        project = Path(args.project).resolve()
        if not project.is_dir():
            raise ValueError(f"project directory does not exist: {project}")
        return _managed(project, args.proposal, stdin, interactive)
    except KeyboardInterrupt, EOFError:
        print(
            "Review interrupted before admission: no human decision was recorded.",
            file=sys.stderr,
        )
        return 1
