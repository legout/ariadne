"""Read-only Git-project readiness diagnostics for ``ariadne status``."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from ariadne import admission, authoring_sources, draft, ossie, proposals, skill, sources

_LABEL = 18


def _git_available() -> bool:
    try:
        proposals._git(["--version"], Path.cwd(), check=False)
    except proposals.GitError:
        return False
    return True


def _repo_root(root: Path) -> str | None:
    proc = proposals._git(["rev-parse", "--show-toplevel"], root, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def _git_identity_ok(root: Path) -> bool:
    if os.environ.get("GIT_AUTHOR_NAME") and os.environ.get("GIT_AUTHOR_EMAIL"):
        return True
    return all(
        (proc := proposals._git(["config", "--get", key], root, check=False)).returncode == 0
        and bool(proc.stdout.strip())
        for key in ("user.name", "user.email")
    )


def _git_head_revision(root: Path, repo_root: str | None) -> str | None:
    """the full exact HEAD of THIS checkout, read from Git
    only — or None when it is unknown (no repository, unborn HEAD), never an
    invented revision. It is transport state, disclosed separately from the
    verified admitted Content Commit."""
    if repo_root is None:
        return None
    proc = proposals._git(["rev-parse", "--verify", "HEAD"], root, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _catalog(snapshot: Path) -> dict:
    models = snapshot / "semantic_layer" / "models"
    files = sorted((*models.glob("*.yml"), *models.glob("*.yaml"))) if models.is_dir() else []
    metrics = 0
    errors: list[str] = []
    for path in files:
        try:
            parsed = ossie.parse_model(ossie.read_document(path), path.name)
            metrics += len(parsed.metrics)
        except Exception as exc:
            lines = str(exc).splitlines()
            detail = lines[0].strip() if lines and lines[0].strip() else type(exc).__name__
            errors.append(f"{path.name}: {detail}")
    return {
        "models": len(files),
        "metrics": metrics,
        "context_only": not files or not metrics,
        "state": "invalid" if errors else "ok",
        "errors": errors,
    }


def _managed_admission(root: Path) -> dict:
    try:
        record = admission.load_current(root)
    except Exception as exc:
        return {"state": "invalid", "reason": str(exc)}
    if record is None:
        return {"state": "none"}
    pinned = {
        "revision": record.get("commit"),
        "artifact_digest": record.get("artifact_digest"),
        "source_digest": record.get("source_digest"),
    }
    try:
        resolved, snapshot = admission.resolve_admission(root)
    except Exception as exc:
        return {"state": "invalid", "reason": str(exc), **pinned}
    return {
        "state": "valid",
        "record": resolved,
        "revision": resolved["commit"],
        "artifact_digest": resolved["artifact_digest"],
        "source_digest": resolved["source_digest"],
        "snapshot": snapshot,
        "catalog": _catalog(snapshot),
    }


def _entries_view(entries: list[dict] | None) -> list[dict]:
    return [
        {
            "name": entry.get("name"),
            "type": entry.get("type"),
            "read_only": entry.get("read_only", True),
        }
        for entry in entries or []
    ]


def _approvals(root: Path) -> dict | None:
    try:
        return {g["source"]["name"]: g for g in authoring_sources._load_grants(root)}
    except Exception:
        return None


def _managed_sources(root: Path, admitted: dict, approvals: dict | None) -> dict:
    if admitted["state"] == "valid":
        record = admitted["record"]
        return {
            "selection": "admitted",
            "entries": _entries_view(record.get("sources")),
            "identity_digest": record.get("source_digest"),
            "approval": True,
            "effective_approval": "current",
            "storage_bindings": record.get("storage_bindings") or {},
            "scaffold": None,
        }
    registry_path = root / "ariadne.yaml"
    scaffold = None
    if registry_path.is_file():
        try:
            registry = sources.load_registry(registry_path)
            resolved = authoring_sources._resolved_entries(registry.sources, registry.storages)
            digest = authoring_sources.resolved_digest(resolved)
            state = authoring_sources.approval_state(root, resolved, digest)
            scaffold = {
                "path": str(registry_path),
                "entries": _entries_view(resolved),
                "identity_digest": digest,
                "approval": state["approved"] if approvals is not None else None,
                "effective_approval": state["state"] if approvals is not None else None,
            }
            if state.get("storage_bindings"):
                scaffold["storage_bindings"] = state["storage_bindings"]
            if state["state"] == "unresolved":
                scaffold["prerequisite"] = state.get("reason")
        except Exception as exc:
            scaffold = {"path": str(registry_path), "error": str(exc)}
    return {
        "selection": "scaffold" if scaffold is not None else "none",
        "entries": None,
        "identity_digest": None,
        "approval": None,
        "scaffold": scaffold,
    }


def _managed_proposals(root: Path, approvals: dict | None) -> list[dict]:
    """Pending work = the ONE active draft (spec 0040 §3.3). Consumed and discarded
    proposals are history, never pending."""
    pending: list[dict] = []
    try:
        view = draft.status(root)
    except Exception as exc:
        return [{"id": "draft", "state": "unreadable", "reason": str(exc)}]
    if view is None:
        return pending
    proposal = draft.proposal_of(root, (view["generation"], view["candidate_revision"]))
    entry: dict[str, Any] = {
        "id": proposal,
        "generation": view["generation"],
        "base_served_revision": view["base_served_revision"],
        "stale": view["stale"],
    }
    try:
        record = proposals._load_record(root, proposal)
    except Exception as exc:
        entry.update(state="unreadable", reason=str(exc))
        return [entry]
    entry["base_revision"] = record.get("base_revision")
    candidate = view["candidate_revision"]
    entry["candidate_revision"] = candidate
    try:
        evidence = proposals.load_validation(root, proposal, candidate)
    except Exception as exc:
        entry["validation"] = {"state": "unreadable", "reason": str(exc)}
    else:
        entry["validation"] = (
            {"state": "unvalidated"}
            if evidence is None
            else {
                "state": "validated" if evidence.get("ok") else "invalid",
                "errors": len(evidence.get("errors") or []),
            }
        )
    repair = (record.get("repair") or {}).get("status")
    if repair:
        entry["repair"] = repair
    try:
        resolved, digest = authoring_sources.candidate_sources(root, candidate)
        entry["source_digest"] = digest
        entry["sources_declared"] = bool(resolved)
        state = authoring_sources.approval_state(root, resolved, digest)
        entry["approved"] = state["approved"] if digest and approvals is not None else None
        if resolved and any(isinstance(item.get("storage"), dict) for item in resolved):
            entry["effective_approval"] = state["state"]
            if state["state"] == "unresolved":
                entry["prerequisite"] = state.get("reason")
    except Exception as exc:
        entry["source_error"] = str(exc)
    return [entry]


def _example_counts(snapshot: Path | None, record: dict | None) -> dict:
    """The admitted release's native Answer-Example count from the pinned
    scoped SDK view: producer-kind pages of the admitted KB
    under the release's authorized visibility scope — never a filename or
    directory guess, never a hidden-page disclosure, never a raw KB parse.
    The pinned release is admitted, so every counted page is admitted
    knowledge; the retired separate-store ``stable`` status is gone."""
    if snapshot is None or record is None:
        return {"total": 0, "by_status": {}}
    try:
        from ariadne import lumio_context

        release = lumio_context.verify_release(record, snapshot)
    except (ValueError, OSError):
        return {"total": 0, "by_status": {}}
    if release is None:
        return {"total": 0, "by_status": {}}
    total = 0
    for page in release.pages:
        # ContextPageView.native is a deep-immutable producer view (never a
        # plain dict) and the producer kind lives on ``page.kind`` — count the
        # scoped pinned answer_example pages directly.
        if page.kind == "answer_example":
            total += 1
    return {"total": total, "by_status": ({"admitted": total} if total else {})}


def _skill_targets(selection: set[tuple[str, str | None]] | None = None) -> list[dict]:
    packaged = skill._dir_hash(skill.ASSETS)
    targets: list[tuple[str, str | None, Path]] = [
        ("user", None, skill._scope_target("user")),
        ("project", None, skill._scope_target("project")),
    ]
    for agent, (user, project) in sorted(skill.AGENT_DIRS.items()):
        targets.extend(
            (("user", agent, Path(user).expanduser()), ("project", agent, Path(project).absolute()))
        )
    views = []
    for scope, agent, path in targets:
        if selection is not None and (scope, agent) not in selection:
            continue
        state = (
            "absent"
            if not path.exists() and not path.is_symlink()
            else "ok"
            if skill._dir_hash(path.resolve()) == packaged
            else "drift"
        )
        views.append({"scope": scope, "agent": agent, "path": str(path), "state": state})
    return views


def _bound_release_view(record: dict) -> dict | None:
    """the verified admission's Bound Release digest, its
    exact immutable local Published Version and its declared supported
    operations — from the verified descriptor only, never the working tree,
    with no destination, registry or source data disclosed. A record without a
    well-formed bound release simply discloses none."""
    manifest = record.get("bound_release")
    if not isinstance(manifest, dict):
        return None
    knowledge = manifest.get("knowledge")
    support = manifest.get("support")
    if not isinstance(knowledge, dict) or not isinstance(support, dict):
        return None
    digest = manifest.get("digest")
    version = knowledge.get("published_version")
    operations = support.get("operations")
    if not digest or not version or not isinstance(operations, list):
        return None
    return {
        "digest": digest,
        "published_version": version,
        "supported_operations": operations,
    }


def _admission_view(admitted: dict) -> dict:
    if admitted["state"] == "valid":
        catalog = admitted["catalog"]
        view = {
            "state": "valid",
            "revision": admitted["revision"],
            "artifact_digest": admitted["artifact_digest"],
            "source_digest": admitted["source_digest"],
            "context_only": catalog["context_only"],
            "catalog": catalog,
        }
        bound = _bound_release_view(admitted["record"])
        if bound is not None:
            view["bound_release"] = bound
        return view
    return {key: admitted.get(key) for key in ("state", "reason") if admitted.get(key) is not None}


def _readiness(admitted: dict) -> tuple[bool, str | None]:
    if admitted["state"] == "none":
        return False, "no human admission recorded for this project"
    if admitted["state"] == "invalid":
        return False, f"admission invalid — {admitted.get('reason')}"
    catalog = admitted["catalog"]
    if catalog["state"] == "invalid":
        shown = "; ".join(catalog["errors"][:3])
        return False, f"admitted catalog metadata is corrupt or unreadable ({shown})"
    if catalog["context_only"]:
        return False, (
            "context-only admission — no metric catalog (the admitted context is available)"
        )
    return True, None


def _proposal_steps(root: str, pending: list[dict]) -> list[str]:
    """Next steps for the one active draft — only commands that exist (spec 0040 §3.1.2)."""
    steps = []
    for entry in pending:
        if entry.get("state") == "unreadable":
            steps.append(
                f"human resolution required: the draft is unreadable ({entry.get('reason')})"
            )
        elif entry.get("stale"):
            steps.append(f"ariadne draft rebase --project {root} — the served revision moved on")
        elif entry.get("repair") == "review_needed":
            steps.append("human review required: the draft exhausted its bounded repair")
        elif entry.get("sources_declared") and not entry.get("approved"):
            steps.append(
                f"ariadne approve --project {root} — HUMAN-ONLY: approve the new sources first "
                "(source approval)"
            )
        elif entry.get("validation", {}).get("state") == "validated":
            steps.append(f"ariadne diff --project {root}, then ariadne approve --project {root}")
        elif entry.get("validation", {}).get("state") == "invalid":
            steps.append(f"repair the reported errors, then ariadne validate --project {root}")
        else:
            steps.append(f"ariadne validate --project {root}")
    return steps


def _next_steps(
    root: Path,
    git: dict,
    repo_ok: bool,
    identity_ok: bool,
    admitted: dict,
    pending: list[dict],
    skill_targets: list[dict],
) -> list[str]:
    steps = []
    root_text = str(root)
    if not git["available"]:
        steps.append(
            "install Git and put 'git' on PATH — Git authoring needs a local git executable"
        )
    elif git["repository_root"] is None:
        steps.append(f"git init {root_text} — the data project must be its own Git repository")
    elif not repo_ok:
        steps.append(f"run from the repository's top-level directory ({git['repository_root']})")
    if git["available"] and git["repository_root"] is not None and not identity_ok:
        steps.append(
            f'git config user.name "…" && git config user.email "…" (repo-local in {root_text})'
        )
    if admitted["state"] == "invalid":
        steps.append(
            "human resolution required: admission state is inconsistent "
            f"({admitted.get('reason')}); "
            f"inspect {proposals.ARIADNE_STATE_DIR}/ and approve a validated draft again"
        )
    elif admitted["state"] == "none":
        steps.extend(
            _proposal_steps(root_text, pending)
            if pending
            else [f"ariadne add <source> --project {root_text} — start the first draft"]
        )
    elif admitted["catalog"]["context_only"]:
        steps.append(f"ariadne draft edit <file> --project {root_text} — author semantic models")
    for target in skill_targets:
        if target["state"] == "drift":
            agent = f" --agent {target['agent']}" if target["agent"] else ""
            steps.append(
                f"ariadne skill install --scope {target['scope']}{agent} — refresh the drifted "
                f"installed skill at {target['path']}"
            )
    return steps


def build_report(args: argparse.Namespace, *, skill_targets=None) -> dict:
    """Assemble source-free status for one explicit Git project or cwd project."""
    root = Path(getattr(args, "project", None) or ".").resolve()
    if not root.is_dir():
        raise ValueError(f"--project {root} is not an existing directory")
    git = {"available": _git_available(), "repository_root": None, "commit_identity": None}
    repo_root = _repo_root(root) if git["available"] else None
    repo_ok = repo_root is not None and Path(repo_root).resolve() == root
    identity_ok = _git_identity_ok(root) if repo_root is not None else False
    git.update(
        repository_root=repo_root,
        commit_identity=identity_ok if repo_root is not None else None,
        head_revision=_git_head_revision(root, repo_root),
    )

    admitted = _managed_admission(root)
    approvals = _approvals(root)
    pending = _managed_proposals(root, approvals)
    sources_section = _managed_sources(root, admitted, approvals)
    if admitted["state"] != "valid":
        sources_section["pending"] = [
            {
                key: entry.get(key)
                for key in ("id", "candidate_revision", "source_digest", "approved")
            }
            for entry in pending
        ]
    snapshot = admitted.get("snapshot") if admitted["state"] == "valid" else None
    catalog = admitted.get("catalog") if admitted["state"] == "valid" else None
    targets = _skill_targets(skill_targets)
    ready, reason = _readiness(admitted)
    project = {
        "kind": "git_managed",
        "logical_root": str(root),
        "artifact_root": str(snapshot) if snapshot else None,
        "artifact_state": "admitted" if snapshot else admitted["state"],
        "catalog": catalog,
        "git": git,
        "admission": _admission_view(admitted),
    }
    return {
        "project": project,
        "sources": sources_section,
        "work_pending": {
            "proposals": pending,
            "answer_examples": _example_counts(snapshot, admitted.get("record")),
        },
        "skill": {"targets": targets},
        "next_steps": _next_steps(root, git, repo_ok, identity_ok, admitted, pending, targets),
        "ready": ready,
        "ready_reason": reason,
    }


def _row(label: str, value: Any) -> str:
    return f"  {label:<{_LABEL}}{value}"


def _render(report: dict) -> str:
    project = report["project"]
    lines = [
        "Project",
        _row("kind:", project["kind"]),
        _row("logical root:", project["logical_root"]),
    ]
    lines.append(_row("artifact root:", project["artifact_root"] or "none"))
    git = project["git"]
    lines.extend(
        [
            _row("git:", "available" if git["available"] else "not available"),
            _row("repository root:", git["repository_root"] or "n/a"),
            _row(
                "git identity:",
                "n/a"
                if git["commit_identity"] is None
                else "set"
                if git["commit_identity"]
                else "missing",
            ),
            # transport state, separate from the admitted Content Commit
            _row("local HEAD:", git["head_revision"] or "unknown"),
            _row("admission:", report["project"]["admission"]["state"]),
        ]
    )
    bound = project["admission"].get("bound_release")
    if bound is not None:
        lines.append(
            _row(
                "bound release:",
                f"{bound['digest'][:12]}… (published {bound['published_version']})",
            )
        )
        lines.append(
            _row(
                "supported ops:",
                f"{len(bound['supported_operations'])} (see --json for the exact list)",
            )
        )
        if git["head_revision"] and git["head_revision"] != bound["published_version"]:
            lines.append(
                _row(
                    "",
                    "local HEAD differs from the admitted revision — sync alone never "
                    "activates a release",
                )
            )
    catalog = project.get("catalog")
    if catalog is not None:
        lines.append(
            _row("catalog:", f"{catalog['models']} model(s), {catalog['metrics']} metric(s)")
        )
    lines.append("")
    lines.append("Sources")
    source = report["sources"]
    lines.append(_row("state:", source["selection"]))
    if source.get("identity_digest"):
        lines.append(_row("identity digest:", source["identity_digest"][:12] + "…"))
    lines.append("")
    lines.append("Work pending")
    proposals_pending = report["work_pending"]["proposals"]
    if proposals_pending:
        entry = proposals_pending[0]
        lines.append(
            _row(
                "draft:",
                f"generation {entry.get('generation')}, base "
                f"{str(entry.get('base_served_revision') or 'none')[:12]}, "
                f"{'STALE' if entry.get('stale') else 'current'}, validation "
                f"{(entry.get('validation') or {}).get('state', 'unknown')}",
            )
        )
    else:
        lines.append(_row("draft:", "none"))
    examples = report["work_pending"]["answer_examples"]
    lines.append(_row("answer examples:", str(examples["total"])))
    lines.append("")
    lines.append("Skill")
    for target in report["skill"]["targets"]:
        lines.append(
            _row(
                f"{target['scope']}/{target['agent'] or 'skill root'}:",
                f"{target['state']}  {target['path']}",
            )
        )
    lines.append("")
    lines.append("Next steps")
    lines.extend(f"  {index}. {step}" for index, step in enumerate(report["next_steps"], 1))
    if not report["next_steps"]:
        lines.append("  (none — no blockers)")
    lines.append("")
    lines.append("Ready: yes" if report["ready"] else f"Ready: no — {report['ready_reason']}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    print(json.dumps(report) if args.json else _render(report))
    return 0
