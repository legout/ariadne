"""Operator onboarding for Git-authoring projects; human gates remain handoffs."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from ariadne import authoring_sources, init, proposals, skill, sources, status

_FILE_TYPES = {
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".duckdb": "duckdb",
    ".csv": "csv",
    ".json": "json",
    ".parquet": "parquet",
}
_SKIP_DIRS = {"venv", "env", "node_modules", "staging", ".ariadne"}
_SCAN_LIMIT = 5000


def _ask(stdin: Any, prompt: str) -> str:
    print(prompt, end=" ", flush=True)
    line = stdin.readline()
    if not line:
        raise EOFError("setup interrupted; completed steps remain; rerun to resume")
    return line.strip()


def detect_files(root: Path) -> list[dict]:
    """Bounded metadata scan; no symlink traversal or source-content reads."""
    pending = [root]
    entries = []
    seen = 0
    while pending:
        directory = pending.pop()
        try:
            if (directory / "pyvenv.cfg").exists():
                continue
            with os.scandir(directory) as children:
                for child in children:
                    seen += 1
                    if seen > _SCAN_LIMIT:
                        print(
                            f"Detection bounded at {_SCAN_LIMIT} paths; "
                            "declare other sources manually."
                        )
                        return sorted(entries, key=lambda entry: entry["path"])
                    if child.name.startswith(".") or child.is_symlink():
                        continue
                    if child.is_dir(follow_symlinks=False):
                        if child.name not in _SKIP_DIRS:
                            pending.append(Path(child.path))
                    elif child.is_file(follow_symlinks=False):
                        path = Path(child.path)
                        kind = _FILE_TYPES.get(path.suffix.lower())
                        if kind:
                            name = re.sub(r"[^a-z0-9_]", "_", path.stem.lower())
                            if not name or not name[0].isalpha():
                                name = "source_" + name
                            entries.append(
                                {
                                    "name": name,
                                    "type": kind,
                                    "path": path.relative_to(root).as_posix(),
                                }
                            )
        except OSError:
            print(f"Detection: unreadable directory metadata at {directory}")
    return sorted(entries, key=lambda entry: entry["path"])


def _select_entries(
    candidates: list[dict], root: Path, stdin: Any, storages: dict | None = None
) -> list[dict]:
    selected = []
    for candidate in candidates:
        answer = _ask(stdin, f"Hint {json.dumps(candidate)}: accept / skip / edited JSON object?")
        if answer in ("", "skip"):
            continue
        # Do not echo malformed input: it may contain an inline credential.
        try:
            entry = candidate if answer == "accept" else json.loads(answer)
            sources.validate_entries([entry], "setup declaration", root, storages=storages)
        except ValueError, TypeError:
            raise ValueError(
                "invalid declaration; use registry fields and environment-variable "
                "names, never inline credentials; nothing declared"
            ) from None
        selected.append(entry)
    print(
        "Manual declarations: registry-shaped JSON; "
        "postgres uses connection_env (DSN variable NAME)."
    )
    while True:
        answer = _ask(stdin, "Add a manual JSON source object, or blank to finish?")
        if not answer:
            break
        try:
            entry = json.loads(answer)
            sources.validate_entries([entry], "setup declaration", root, storages=storages)
        except ValueError, TypeError:
            raise ValueError(
                "invalid declaration; use environment-variable names, never "
                "inline credentials; nothing declared"
            ) from None
        selected.append(entry)
    if (
        selected
        and _ask(
            stdin, "Declare selected entries as inert proposals (NOT source approval)? yes / no"
        )
        == "yes"
    ):
        sources.validate_entries(selected, "setup declarations", root, storages=storages)
        return selected
    print("Declaration skipped; no detected source was accepted.")
    return []


def _new_entries(
    root: Path, existing: list[dict], selected: list[dict], storages: dict | None = None
) -> list[dict]:
    resolved = authoring_sources._resolved_entries(
        sources.validate_entries(selected, "setup declarations", root, storages=storages),
        storages,
    )
    by_name = {entry["name"]: entry for entry in existing}
    new = []
    for raw, identity in zip(selected, resolved, strict=True):
        prior = by_name.get(identity["name"])
        if prior is not None:
            if prior != identity:
                raise ValueError(
                    f"conflicting source identity {identity['name']!r}; nothing overwritten"
                )
            print(f"Source {identity['name']}: identical declaration already present; skipped.")
        else:
            new.append(raw)
    return new


def _existing_storages(root: Path, report: dict) -> dict | None:
    """Read storage identities from the first existing candidate, without access."""
    for entry in report["work_pending"]["proposals"]:
        revision = entry.get("candidate_revision") if isinstance(entry, dict) else None
        if isinstance(revision, str):
            try:
                identity = authoring_sources.candidate_identity(root, revision)
            except Exception:
                return None
            raw = (identity or {}).get("storages") or {}
            return sources.validate_storages(raw, root) or None
    return None


def _managed_declare(root: Path, selected: list[dict], report: dict, stdin: Any) -> None:
    pending = report["work_pending"]["proposals"]
    if pending:
        ids = [entry["id"] for entry in pending]
        pid = ids[0] if len(ids) == 1 else _ask(stdin, f"Choose existing proposal ID {ids}:")
        if pid not in ids:
            raise ValueError("select an existing proposal; setup will not replace pending work")
        record = proposals._load_record(root, pid)
        revision = record["candidate_revision"]
    else:
        from ariadne.authoring import AuthoringProject

        started = AuthoringProject(root).start_proposal()
        pid, revision = started["proposal"], started["candidate_revision"]
    existing, digest = authoring_sources.candidate_sources(root, revision)
    candidate_storages = (authoring_sources.candidate_identity(root, revision) or {}).get(
        "storages"
    )
    existing_storages = sources.validate_storages(candidate_storages, root)
    additions = _new_entries(root, existing or [], selected, existing_storages)
    if additions:
        from ariadne.authoring import AuthoringProject

        result = AuthoringProject(root).propose_sources(
            pid, revision, additions, candidate_storages or None
        )
        revision, digest = result["revision"], result["source_digest"]
    assert digest is not None  # a confirmed nonempty declaration resolves to a source identity
    print(f"Proposal: {pid}\nRevision: {revision}\nResolved source digest: {digest}")
    if digest not in authoring_sources._load_approvals(root):
        print("Source approval pending. HUMAN ONLY — run exactly:")
        print(
            shlex.join(
                [
                    "ariadne-authoring",
                    "approve-sources",
                    "--project",
                    str(root),
                    "--proposal",
                    pid,
                    "--revision",
                    revision,
                    "--source-digest",
                    digest,
                ]
            )
        )
    else:
        print("Source approval already recorded for this exact identity/revision.")


def _report(root: Path, args: argparse.Namespace) -> dict:
    targets: set[tuple[str, str | None]] = set()
    if args.agents and args.agent:
        targets.add((args.scope, None))
        if args.agent != "universal":
            targets.add((args.scope, args.agent))
    return status.build_report(
        argparse.Namespace(project=str(root)),
        skill_targets=targets,
    )


def _authoring_handoff(root: Path) -> None:
    print(
        "Git authoring: use ariadne-authoring start, then declare and approve the exact "
        "source identity, refresh-schema, edit, validate and review. Stop for human "
        "ariadne-admit --confirm before governed queries. Original documents stay external; "
        "setup reads filenames only."
    )


def _install_skill(args: argparse.Namespace, interactive: bool, stdin: Any) -> int:
    if not args.agents:
        print("Skill installation skipped (use --agents with an explicit target).")
        return 0
    target = args.agent
    if target is None:
        if not interactive:
            print(
                "Skill target selection required: --agent universal|pi|claude|hermes; "
                "installed nothing."
            )
            return 0
        target = _ask(stdin, "Skill target: universal / pi / claude / hermes / skip?")
        if target == "skip":
            return 0
        if target not in ("universal", *skill.AGENT_DIRS):
            raise ValueError("unknown skill target; installed nothing")
    args.agent = target
    argv = ["install", "--scope", args.scope]
    if target != "universal":
        argv += ["--agent", target]
    code = skill.main(argv)
    if code:
        return code
    packaged = skill._dir_hash(skill.ASSETS)
    paths = [skill._scope_target(args.scope)]
    if target == "universal":
        print("Universal-only installation: no Pi/Claude/Hermes host wiring selected.")
    else:
        paths.append(Path(skill.AGENT_DIRS[target][0 if args.scope == "user" else 1]).expanduser())
    for path in paths:
        state = "ok" if skill._dir_hash(path.resolve()) == packaged else "drift"
        print(f"Selected skill {args.scope}/{target}: {state} {path.absolute()}")
    return 0


def run(args: argparse.Namespace, stdin: Any) -> int:
    interactive = not args.no_input and stdin.isatty() and sys.stdout.isatty()
    root = Path(args.project).expanduser().absolute()
    if init.main([str(root)]):
        return 1
    root = root.resolve()
    code = 0
    with contextlib.chdir(root):
        report = _report(root, args)
        print("Git prerequisites (report + operator handoff; setup never runs git init/config):")
        git = report["project"]["git"]
        git_ok = (
            git["available"]
            and git["repository_root"] is not None
            and Path(git["repository_root"]).resolve() == root
            and git["commit_identity"]
        )
        if not git_ok:
            print(
                f"Proposal preparation paused. Operator: install Git if absent; make {root} "
                "its own repository top-level, then configure repository-local commit identity:"
            )
            print(shlex.join(["git", "init", str(root)]))
            print(shlex.join(["git", "-C", str(root), "config", "user.name", "YOUR NAME"]))
            print(shlex.join(["git", "-C", str(root), "config", "user.email", "YOUR EMAIL"]))
        else:
            print("Git available, project is repository root, operator identity configured.")

        candidates = detect_files(root)
        print(
            f"Detected {len(candidates)} file(s), filename-only hints "
            "(no content/schema validation):"
        )
        for entry in candidates:
            print(json.dumps(entry))
        try:
            if interactive and git_ok:
                selected = _select_entries(
                    candidates, root, stdin, storages=_existing_storages(root, report)
                )
                if selected:
                    _managed_declare(root, selected, report, stdin)
            else:
                print(
                    "Declarations skipped: non-interactive or Git prerequisites missing. "
                    "Use interactive setup or ariadne-authoring propose-sources for inert entries."
                )
        except Exception as exc:
            print(
                f"Declarations paused: {exc}; completed scaffold/proposal steps remain.",
                file=sys.stderr,
            )
            code = 1

        _authoring_handoff(root)
        try:
            install_code = _install_skill(args, interactive and not code, stdin)
        except Exception as exc:
            print(f"Skill installation incomplete: {exc}; rerun to resume.", file=sys.stderr)
            install_code = 1
        print("Finish: scaffold/skills are not a query-ready catalog. Diagnostic status:")
        print(status._render(_report(root, args)))
        print(
            "Human gates remain: source approval and Git Review Admission; setup invokes "
            "neither. After admission, governed does not mean independently value-attested."
        )
    return code or install_code
