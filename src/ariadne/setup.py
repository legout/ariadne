"""Operator onboarding shell: compose existing seams, never grant human authority."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ariadne import authoring, authoring_sources, init, proposals, skill, sources, status

_FILE_TYPES = {
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".duckdb": "duckdb",
    ".csv": "csv",
    ".json": "json",
    ".parquet": "parquet",
}
_SKIP_DIRS = {"venv", "env", "node_modules", "staging"}
_SCAN_LIMIT = 5000


def _ask(stdin: Any, prompt: str) -> str:
    print(prompt, end=" ", flush=True)
    line = stdin.readline()
    if not line:
        raise EOFError("setup interrupted; completed steps remain; rerun to resume")
    return line.strip()


def _route(root: Path, legacy: bool, interactive: bool, stdin: Any) -> str | None:
    state = root / proposals.ARIADNE_STATE_DIR
    if state.exists() or state.is_symlink():
        route = "managed"
    else:
        agents = root / "AGENTS.md"
        text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
        if "## Admission gate" in text:
            route = "managed"
        elif "## Promotion gate" in text:
            route = "legacy"
        elif any(
            (root / p).exists() for p in ("staging", "context_layer", "semantic_layer", "served")
        ):
            route = "legacy"
        elif any((root / p).exists() for p in ("ariadne.yaml", "data/seed_notes.md", "AGENTS.md")):
            if legacy:
                return "legacy"
            if not interactive:
                print(
                    "Route choice required: rerun interactively to select managed, or use --legacy."
                )
                return None
            choice = _ask(stdin, "Existing scaffold route: managed / legacy / skip?")
            if choice == "skip":
                return None
            if choice not in ("managed", "legacy"):
                raise ValueError("choose managed or legacy; existing files were not changed")
            return choice
        else:
            return "legacy" if legacy else "managed"
    if legacy and route == "managed":
        raise ValueError("--legacy conflicts with the existing managed route; setup never migrates")
    return route


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
                        return sorted(entries, key=lambda e: e["path"])
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
    return sorted(entries, key=lambda e: e["path"])


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
        except (ValueError, TypeError):
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
        except (ValueError, TypeError):
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


def _existing_storages(route: str, root: Path, report: dict) -> dict | None:
    """Storage profiles already declared where new declarations land (spec
    0025 §5): the managed route's first pending candidate registry, else the
    installed legacy registry. Credential-free declarations only — no
    environment reads, no opening; unreadable state declares nothing."""
    if route == "managed":
        pending = (report.get("work_pending") or {}).get("proposals") or []
        for entry in pending:
            revision = entry.get("candidate_revision") if isinstance(entry, dict) else None
            if isinstance(revision, str):
                try:
                    identity = authoring_sources.candidate_identity(root, revision)
                except Exception:
                    return None
                raw = (identity or {}).get("storages") or {}
                return sources.validate_storages(raw, root) or None
        return None
    registry = sources.default_registry_path()
    if not registry:
        return None
    try:
        return sources.load_registry(registry).storages
    except Exception:
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
        started = authoring.AuthoringProject(root).start_proposal()
        pid, revision = started["proposal"], started["candidate_revision"]
    existing, digest = authoring_sources.candidate_sources(root, revision)
    candidate_storages = (authoring_sources.candidate_identity(root, revision) or {}).get(
        "storages"
    )
    existing_storages = sources.validate_storages(candidate_storages, root)
    additions = _new_entries(root, existing or [], selected, existing_storages)
    if additions:
        result = authoring.AuthoringProject(root).propose_sources(
            pid, revision, additions, candidate_storages or None
        )
        revision, digest = result["revision"], result["source_digest"]
    assert digest is not None  # a confirmed nonempty declaration always has a resolved identity
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


def _legacy_declare(root: Path, selected: list[dict]) -> None:
    registry = sources.default_registry_path()
    registry_obj = sources.load_registry(registry) if registry else None
    installed = registry_obj.sources if registry_obj else []
    existing = authoring_sources._resolved_entries(
        installed, registry_obj.storages if registry_obj else None
    )
    additions = (
        _new_entries(
            root, existing, selected, registry_obj.storages if registry_obj else None
        )
        if selected
        else []
    )
    stored = root / authoring.PROPOSAL_REL
    digest = None
    if stored.exists():
        pending = sources.load_registry(stored)
        pending_entries = authoring_sources._resolved_entries(pending.sources, pending.storages)
        # A previously approved legacy proposal stays on disk; it is not another blocker.
        if all(entry in existing for entry in pending_entries):
            print("Legacy source declarations already installed by the operator.")
        else:
            remaining = _new_entries(root, pending_entries, additions) if additions else []
            if remaining:
                raise ValueError(
                    "a source proposal is already pending; resolve it before adding sources"
                )
            digest = authoring._digest(authoring._entries(stored))
    if digest is None:
        if not additions:
            return
        with tempfile.TemporaryDirectory(prefix="ariadne-setup-") as tmp:
            intake = Path(tmp) / "sources.yaml"
            document: dict = {"sources": additions}
            if registry_obj and registry_obj.storages:
                document["storages"] = {
                    name: profile.identity()
                    for name, profile in registry_obj.storages.items()
                }
            intake.write_text(yaml.safe_dump(document), encoding="utf-8")
            digest = authoring.propose_sources(intake, project=root)["digest"]
    print("Source approval pending. HUMAN ONLY — run exactly:")
    print(
        shlex.join(
            ["ariadne-authoring", "approve-sources", "--project", str(root), "--digest", digest]
        )
    )


def _report(route: str, root: Path, args: argparse.Namespace) -> dict:
    targets: set[tuple[str, str | None]] = set()
    if args.agents and args.agent:
        targets.add((args.scope, None))
        if args.agent != "universal":
            targets.add((args.scope, args.agent))
    return status.build_report(
        argparse.Namespace(
            project=str(root) if route == "managed" else None,
            sources=None,
            db=None,
            served=None,
            staging=None,
        ),
        skill_targets=targets,
    )


def _authoring_handoff(route: str, root: Path, interactive: bool, stdin: Any) -> int:
    print(
        "Seed notes: edit data/seed_notes.md with the owner: domain, row grain, business rules, "
        "and intended metrics; clarify unknown meaning before drafting."
    )
    if route == "managed":
        print(
            "Managed authoring: use your harness's own model (no second credential). After HUMAN "
            "source approval, use ariadne-authoring inputs, refresh-schema, edit, "
            "validate, review; "
            "then STOP for human ariadne-admit --confirm. Setup never drafts a full Git bundle."
        )
        return 0
    print(
        "Legacy authoring: after HUMAN source approval, use harness-led ariadne-authoring "
        "inputs/submit/review, then HUMAN ariadne-promote; or deliberately run ariadne-author."
    )
    registry = sources.default_registry_path()
    if not interactive or registry is None:
        print("Authoring skipped: non-interactive or no operator-installed source registry.")
        return 0
    pending = root / authoring.PROPOSAL_REL
    if pending.exists():
        installed = authoring_sources._resolved_entries(sources.load_registry(registry).sources)
        proposed = authoring_sources._resolved_entries(sources.load_registry(pending).sources)
        if not all(entry in installed for entry in proposed):
            print("Authoring paused: source approval pending.")
            return 0
    print(
        "Optional ariadne-author profiles authorized sources and sends profiles/seed notes to "
        "the configured LLM endpoint (network/data egress); stages drafts only, never promotes."
    )
    if _ask(stdin, "Run that existing legacy author now? yes / no") != "yes":
        print("Authoring skipped.")
        return 0
    from ariadne import author

    author._load_env(Path(os.environ.get("ARIADNE_ENV", str(root / ".env"))))
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_MODEL"):
        print(
            "Authoring skipped: configure OPENAI_API_KEY and OPENAI_MODEL in the environment "
            "or ARIADNE_ENV; never commit credentials."
        )
        return 0
    return author.main(["--sources", str(registry), "--notes", "data/seed_notes.md"])


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
    args.agent = target  # retain an interactive selection for the scoped finish diagnostic
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
    root = Path(args.project).absolute()
    route = _route(root, args.legacy, interactive, stdin)
    if route is None:
        print("Setup paused: no route selected, no files changed.")
        return 0
    print(f"Scaffold/resume: {route}; existing init files are never overwritten.")
    if init.main([str(root), *(["--git"] if route == "managed" else [])]):
        return 1
    root = root.resolve()
    code = 0
    # Existing CLI seams are cwd-based; restore the caller even after failure.
    with contextlib.chdir(root):
        report = _report(route, root, args)
        print("Git prerequisites (report + operator handoff, never git init/config by setup):")
        git = report["project"]["git"]
        git_ok = route == "legacy" or (
            git["available"]
            and git["repository_root"] is not None
            and Path(git["repository_root"]).resolve() == root
            and git["commit_identity"]
        )
        if route == "managed" and not git_ok:
            print(
                f"Proposal preparation paused. Operator: install Git if absent; make {root} "
                "its own repository top-level, then configure repository-local commit identity:"
            )
            print(shlex.join(["git", "init", str(root)]))
            print(shlex.join(["git", "-C", str(root), "config", "user.name", "YOUR NAME"]))
            print(shlex.join(["git", "-C", str(root), "config", "user.email", "YOUR EMAIL"]))
        elif route == "managed":
            print("Git available, project is repository root, operator identity configured.")
        else:
            print("Skipped: legacy staged route does not require Git.")
        candidates = detect_files(root)
        print(
            f"Detected {len(candidates)} file(s), filename-only hints "
            "(no content/schema validation):"
        )
        for entry in candidates:
            print(json.dumps(entry))
        existing_storages = _existing_storages(route, root, report)
        try:
            selected = []
            if interactive and git_ok:
                selected = _select_entries(candidates, root, stdin, storages=existing_storages)
                if selected and route == "managed":
                    _managed_declare(root, selected, report, stdin)
            else:
                print(
                    "Declarations skipped: non-interactive or Git prerequisites missing. "
                    "Use interactive setup or ariadne-authoring propose-sources for inert entries."
                )
            if route == "legacy":
                _legacy_declare(root, selected)  # an existing pending handoff is read-only
        except Exception as exc:
            print(
                f"Declarations paused: {exc}; completed scaffold/proposal steps remain.",
                file=sys.stderr,
            )
            code = 1
        try:
            author_code = _authoring_handoff(route, root, interactive and not code, stdin)
            code = code or author_code
        except Exception as exc:
            print(
                f"Authoring interrupted: {exc}; inspect retained drafts before resuming.",
                file=sys.stderr,
            )
            code = 1
        try:
            install_code = _install_skill(args, interactive and not code, stdin)
        except Exception as exc:
            print(f"Skill installation incomplete: {exc}; rerun to resume.", file=sys.stderr)
            install_code = 1
        print("Finish: scaffold/skills are not a query-ready catalog. Diagnostic status:")
        print(status._render(_report(route, root, args)))
        print(
            "Human gates remain: source approval, review/admission or Promotion; "
            "setup invokes none. "
            "After admission/Promotion: list-metrics, then a fresh get-metric; governed does not "
            "mean independently value-attested."
        )
    return code or install_code
