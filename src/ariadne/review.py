"""Operator-only walkthrough: display native reviews, then delegate unchanged gates.

A terminal is a UX condition, not identity or independent approval authority.
No agent/MCP surface imports this adapter.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from ariadne import admission, authoring, promote, status


def _ask(stdin: Any, prompt: str) -> bool:
    print(prompt + " [y/N] ", end="", flush=True)
    answer = stdin.readline()
    if not answer:
        raise EOFError("review input ended")
    return answer.strip().lower() in ("y", "yes")


def _post_state(project: Path | None, staging: Path | None, served: Path | None) -> None:
    print("Delegation ended without a successful result; do not assume rollback or retry.")
    if project is not None:
        try:
            current = admission.load_current(project)
            print(
                "Current recorded activated revision: " + (current["commit"] if current else "none")
            )
        except (Exception, KeyboardInterrupt) as exc:
            print(f"Admission descriptor inspection refused: {type(exc).__name__}: {exc}")
        print("Read-only admission-status inspection:")
        print(shlex.join(["ariadne", "status", "--project", str(project), "--json"]))
    else:
        print(f"Inspect served content at {served} and retained staging/state at {staging}.")
        print("Read-only status inspection:")
        print(
            shlex.join(
                ["ariadne", "status", "--served", str(served), "--staging", str(staging), "--json"]
            )
        )


def _delegate(
    argv: list[str],
    stdin: Any,
    *,
    project: Path | None = None,
    staging: Path | None = None,
    served: Path | None = None,
) -> int:
    # The promoter's input() keeps its own final prompt; restore injected CLI stdin.
    previous = sys.stdin
    sys.stdin = stdin
    try:
        try:
            code = admission.main(argv) if project is not None else promote.main(argv)
        except (KeyboardInterrupt, EOFError) as exc:
            print(f"Delegated operation interrupted: {type(exc).__name__}", file=sys.stderr)
            code = 1
        except SystemExit as exc:
            code = int(exc.code or 0)
        except Exception:
            _post_state(project, staging, served)
            raise
    finally:
        sys.stdin = previous
    if code:
        _post_state(project, staging, served)
    # Success is the native command's actual result, including retained/lapsed evidence.
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
    # Native bodies are bounded per artifact. Display every part without ever
    # substituting a fresher revision/digest for the identities first displayed.
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
        print("Non-interactive: display only; no admission or Promotion invoked.")
        return 0
    if not _ask(stdin, "Admit this exact revision/digest with the complete selection above?"):
        print("Declined: no admission invoked.")
        return 0
    return _delegate(argv, stdin, project=project)


def _legacy(staging: Path, served: Path, stdin: Any, interactive: bool) -> int:
    print(f"Selected staging: {staging}\nSelected served target: {served}")
    argv = ["--staging", str(staging), "--served", str(served)]
    state_path = authoring.bundle_state_path(staging)
    if state_path.exists() or state_path.is_symlink():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"{state_path}: unreadable bundle state — human resolution: {exc}"
            ) from exc
        if not isinstance(state, dict) or not state.get("project") or not state.get("digest"):
            raise ValueError(
                f"{state_path}: malformed bundle proposal state — human resolution required"
            )
        project = Path(state["project"]).resolve()
        native_staging = project / "staging"
        if staging != native_staging.resolve():
            review_cmd = shlex.join(["ariadne-authoring", "review", "--project", str(project)])
            promote_cmd = shlex.join(["ariadne-promote", *argv, "--digest", state["digest"]])
            raise ValueError(
                f"relocated active bundle: selected staging {staging} differs from recorded native "
                f"project/staging {native_staging}; cannot review one bundle and promote another. "
                f"Nothing invoked. Review at the recorded location: {review_cmd}. "
                f"Or inspect the selected bundle and verify its exact digest before the explicit "
                f"native command (recorded digest, not reviewed here): {promote_cmd}"
            )
        payload = authoring.review_bundle(project=project)
        print("Digest-backed bundle — native ariadne-authoring review payload:")
        print(json.dumps(payload, indent=2))
        print("Review digest: " + payload["digest"])
        argv.extend(["--digest", payload["digest"]])
    else:
        print("Ordinary merge-only Promotion — no bundle digest or validation record.")
        refused = promote._review_needed(staging)
        pages, raw = promote._plan(staging, served)
        print(
            json.dumps(
                {"changes": [vars(change) for change in [*pages, *raw]], "review_needed": refused},
                indent=2,
            )
        )
        if refused:
            raise ValueError(
                "staged files carry status: review_needed — human review required: "
                + ", ".join(refused)
            )
        if not pages and not raw:
            print("No pending Promotion: served layers already match staging.")
            return 0
    print("Exact remaining operator Promotion command (native final prompt decides):")
    print(shlex.join(["ariadne-promote", *argv]))
    if not interactive:
        print("Non-interactive: display only; no admission or Promotion invoked.")
        return 0
    return _delegate(argv, stdin, staging=staging, served=served)


def run(args: argparse.Namespace, stdin: Any) -> int:
    from ariadne.cli import _is_served_root, _resolve_served_root

    if args.proposal is not None and args.project is None:
        raise ValueError("--proposal requires --project")
    interactive = stdin.isatty() and sys.stdout.isatty()
    try:
        if args.project is not None:
            project = Path(args.project).resolve()
            if not project.is_dir():
                raise ValueError(f"project directory does not exist: {project}")
            return _managed(project, args.proposal, stdin, interactive)
        if args.served is not None:
            if not args.served:
                raise ValueError("--served must be a non-empty Promotion target path")
            served = Path(args.served).resolve()  # Fresh targets are not created by review.
        else:
            if not any(_is_served_root(p) for p in (Path.cwd(), Path.cwd() / "served")):
                raise ValueError(
                    "no promoted artifacts found: before first Promotion choose the target "
                    "explicitly with --served PATH"
                )
            served = _resolve_served_root(None).resolve()
        staging = Path(args.staging if args.staging is not None else "staging").resolve()
        return _legacy(staging, served, stdin, interactive)
    except (KeyboardInterrupt, EOFError):
        print(
            "Review interrupted before delegation: no admission or Promotion invoked.",
            file=sys.stderr,
        )
        return 1
