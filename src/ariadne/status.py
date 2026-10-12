"""``ariadne status`` — read-only project readiness diagnostics (spec
2026-10-12-0016, ADR-0021).

One command that answers "what is this project, and what is the next step?"
by COMPOSING the existing read-only seams — never the eager
:class:`ariadne.query.QueryRuntime` (whose construction opens a source
connection) and never the HTTP probes (whose lazy factories do the same):

- route resolution is DIAGNOSTIC: an explicit ``--project DIR`` selects
  managed diagnostics at any existing directory (scaffold included), a cwd
  ``.ariadne/`` state directory selects managed diagnostics only (a plain
  ``.git`` is NOT a managed marker), and everything else diagnoses the legacy
  route reusing the query CLI's promoted-root layout rule and its
  cwd-versus-``./served`` ambiguity check. Zero promoted roots is report
  data, not a startup error;
- the report's five fixed sections (project, sources, work_pending, skill,
  next_steps) read admission (:mod:`ariadne.admission`), the source-approval
  seam (:mod:`ariadne.authoring_sources`), proposal/validation records
  (:mod:`ariadne.proposals`), legacy staging (:mod:`ariadne.promote`), the
  Answer Example store (:mod:`ariadne.answer_examples`) and the packaged
  skill drift states (:mod:`ariadne.skill`) — read-only, no connection, no
  compilation, no network;
- ``ready`` means only "artifact prerequisites for governed metric querying
  are present" (readable served catalog metadata + source configuration, and
  a valid managed admission with a metric catalog or a usable legacy served
  state). It proves no compilation, source health or numerical correctness;
  missing optional stores and pending drafts are states, not failures;
- a produced report exits 0 even when not ready; invalid selectors and
  ambiguous legacy roots fail nonzero through the shared CLI error contract.
  ``--json`` prints exactly one structured report; the default is aligned
  human text (the spec-0001 usability amendment, this command only).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import (  # pyright: ignore[reportMissingImports] — drift
    admission,
    answer_examples,
    authoring_sources,
    promote,
    proposals,
    skill,
    sources,
)
from ariadne.cli import _is_served_root  # the shared spec-0001 §5 layout seam

# Section 1/3 label column width: aligned human text.
_LABEL = 18


# --------------------------------------------------------- route resolution


def _resolve_route(args: argparse.Namespace, cwd: Path) -> tuple[str, Path, Path | None]:
    """Diagnostic route selection (spec 0016 Interface): ``(kind, logical
    root, legacy artifact root)``. Never constructs the query runtime; zero
    promoted legacy roots is ``kind "none"``, not an error."""
    if args.project is not None:
        if args.served is not None:  # exactly the managed query route's conflict
            raise ValueError(
                "--project (managed Git route) and --served (explicit legacy root) are "
                "mutually exclusive — pass one artifact root, not both"
            )
        root = Path(args.project)
        if not root.is_dir():
            raise ValueError(f"--project {args.project} is not an existing directory")
        return "git_managed", root.resolve(), None
    # A cwd .ariadne/ state directory (any shape) selects managed DIAGNOSTICS
    # only — malformed state is reported as its own blocker below, never a
    # fallback to root artifacts, and a plain .git alone is no marker.
    state_dir = cwd / proposals.ARIADNE_STATE_DIR
    if state_dir.exists() or state_dir.is_symlink():
        return "git_managed", cwd.resolve(), None
    artifact: Path | None = None
    if args.served is not None:
        served = Path(args.served)
        if not served.is_dir():
            raise ValueError(f"--served {args.served} is not an existing legacy artifact directory")
        artifact = served.resolve()
    else:
        # The query CLI's two-candidate check (spec 0001 §5): two valid roots
        # refuse and name --served; zero is diagnostic data here.
        valid = [p for p in (cwd, cwd / "served") if _is_served_root(p)]
        if len(valid) == 2:
            raise ValueError(
                "ambiguous promoted roots: both the working directory and ./served "
                "contain context_layer/ and semantic_layer/models/ — pass --served "
                "PATH to select one"
            )
        artifact = valid[0].resolve() if valid else None
    return ("legacy_staged" if artifact is not None else "none"), cwd.resolve(), artifact


def _staging_dir(args: argparse.Namespace, logical_root: Path) -> Path:
    """staging/ beneath the logical root (managed project or legacy cwd), or
    the explicit --staging path. An existing non-directory is an invalid
    selector; an absent path is simply an empty store."""
    if args.staging is not None:
        staging = Path(args.staging)
        if staging.exists() and not staging.is_dir():
            raise ValueError(f"--staging {args.staging} is not a directory")
        return staging
    return logical_root / "staging"


# ------------------------------------------------------------ git probes


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
    """The _require_git_identity rule as a probe (never writes config)."""
    if os.environ.get("GIT_AUTHOR_NAME") and os.environ.get("GIT_AUTHOR_EMAIL"):
        return True
    for key in ("user.name", "user.email"):
        proc = proposals._git(["config", "--get", key], root, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            return False
    return True


# ------------------------------------------------------------ admission


def _catalog(snapshot: Path) -> dict:
    """Readable catalog metadata of a pinned snapshot: model/metric counts.
    A context-only admission (no models/metrics) keeps its explicit state."""
    models = snapshot / "semantic_layer" / "models"
    files = sorted((*models.glob("*.yml"), *models.glob("*.yaml"))) if models.is_dir() else []
    metrics = 0
    for path in files:  # metadata only — no compile, no execution
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        for model in doc.get("semantic_model") or []:
            metrics += sum(1 for _ in model.get("metrics") or [])
    return {"models": len(files), "metrics": metrics, "context_only": not files or not metrics}


def _managed_admission(root: Path) -> dict:
    """none | valid | invalid — valid names the checked pinned revision and
    artifact digest exactly as :func:`admission.resolve_admission` verified
    them; corrupt/changed state reports its blocker and never falls back."""
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


# ------------------------------------------------------------- sources


def _entries_view(entries: list[dict] | None) -> list[dict]:
    return [
        {"name": e.get("name"), "type": e.get("type"), "read_only": e.get("read_only", True)}
        for e in entries or []
    ]


def _types_of(entries: list[dict] | None) -> dict[str, int]:
    types: dict[str, int] = {}
    for entry in entries or []:
        kind = str(entry.get("type"))
        types[kind] = types.get(kind, 0) + 1
    return types


def _approvals(root: Path) -> dict | None:
    """The operator's recorded approvals, or None when unreadable (an
    explicit blocker, never a silent empty set)."""
    try:
        return authoring_sources._load_approvals(root)
    except Exception:
        return None


def _managed_sources(root: Path, admitted: dict, approvals: dict | None) -> dict:
    """The managed sources section: admitted configuration when a valid
    admission pins one, otherwise the working-tree scaffold declarations —
    always distinct states, never mixed."""
    if admitted["state"] == "valid":
        record = admitted["record"]
        return {
            "selection": "admitted",
            "entries": _entries_view(record.get("sources")),
            "identity_digest": record.get("source_digest"),
            "approval": True,  # resolve_admission verified approval_present
            "scaffold": None,
        }
    scaffold: dict | None = None
    registry_path = root / "ariadne.yaml"
    if registry_path.is_file():
        try:
            registry = sources.load_registry(registry_path)
            resolved = authoring_sources._resolved_entries(registry.sources)
            digest = authoring_sources.resolved_digest(resolved)
            scaffold = {
                "path": str(registry_path),
                "entries": _entries_view(resolved),
                "identity_digest": digest,
                "approval": (digest in approvals) if approvals is not None else None,
            }
        except Exception as exc:
            scaffold = {"path": str(registry_path), "error": str(exc)}
    return {
        "selection": "scaffold" if scaffold is not None else "none",
        "entries": None,
        "identity_digest": None,
        "approval": None,
        "scaffold": scaffold,
    }


def _legacy_sources(args: argparse.Namespace, cwd: Path) -> dict:
    """--db/--sources/ambient registry as source configuration only (never
    artifact roots); unreadable state is explicit, never a healthy empty."""
    if args.db:
        return {
            "selection": "--db",
            "path": str(Path(args.db)),
            "entries": [{"name": "demo", "type": "sqlite", "read_only": True}],
            "readable": Path(args.db).is_file(),
        }
    path = sources.default_registry_path(args.sources, None)
    if path is None:
        return {"selection": "none", "path": None, "entries": [], "readable": False}
    try:
        registry = sources.load_registry(path)
    except Exception as exc:
        return {"selection": "invalid", "path": str(path), "error": str(exc), "readable": False}
    resolved = authoring_sources._resolved_entries(registry.sources)
    return {
        "selection": "registry",
        "path": str(path),
        "entries": _entries_view(resolved),
        "identity_digest": authoring_sources.resolved_digest(resolved),
        "readable": True,
    }


# --------------------------------------------------------- work pending


def _managed_proposals(root: Path, approvals: dict | None) -> list[dict]:
    """Each pending proposal keeps its own identity/state: id, revisions,
    validation state of its EXACT candidate revision, repair state, and the
    approval of its complete resolved registry identity (the existing seam —
    never a per-source guess). Corrupt records stay visible as blockers."""
    pending: list[dict] = []
    records_dir = root / proposals.PROPOSALS_REL
    if not records_dir.is_dir():
        return pending
    for path in sorted(records_dir.glob("*.json")):
        entry: dict[str, Any] = {"id": path.stem}
        try:
            record = proposals._load_record(root, path.stem)
        except Exception as exc:
            entry["state"] = "unreadable"
            entry["reason"] = str(exc)
            pending.append(entry)
            continue
        entry["base_revision"] = record.get("base_revision")
        candidate = record.get("candidate_revision")
        entry["candidate_revision"] = candidate
        if not isinstance(candidate, str):  # malformed operator-owned state
            entry["state"] = "unreadable"
            entry["reason"] = "malformed proposal record (missing candidate revision)"
            pending.append(entry)
            continue
        try:
            evidence = proposals.load_validation(root, path.stem, candidate)
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
            entry["approved"] = (
                (digest in approvals) if (digest and approvals is not None) else None
            )
        except Exception as exc:
            entry["source_error"] = str(exc)
        pending.append(entry)
    return pending


def _legacy_staging(staging: Path) -> dict:
    """Legacy staged-artifact count plus the spec-0001 §7 review_needed
    markers (the promoter's own scan, reused read-only)."""
    pages = promote._staged_pages(staging)
    raw = promote._staged_files(staging)
    return {
        "count": len(pages) + len(raw),
        "pages": len(pages),
        "raw_files": len(raw),
        "review_needed": promote._review_needed(staging),
    }


def _example_counts(examples_root: Path | None, staging: Path) -> dict:
    """Answer-example counts by review status over the stable and staged
    stores; missing optional stores mean zero, never failure."""
    counts: dict[str, int] = {}
    stores = (
        (False, Path(staging) / answer_examples.EXAMPLES_DIR),
        (True, (examples_root / answer_examples.EXAMPLES_DIR) if examples_root else None),
    )
    total = 0
    for is_stable, directory in stores:
        if directory is None or not directory.is_dir():
            continue
        for page in sorted(directory.glob("*.md")):
            try:
                meta = answer_examples._frontmatter(page)
            except OSError:
                continue
            if not meta or meta.get("type") != "answer_example":
                continue
            status = (
                str(meta.get("status") or "stable")
                if is_stable
                else answer_examples._staged_state(meta)
            )
            counts[status] = counts.get(status, 0) + 1
            total += 1
    return {"total": total, "by_status": counts}


# ----------------------------------------------------------------- skill


def _skill_targets() -> list[dict]:
    """The packaged skill's per-target drift states (ariadne-skill status's
    own scan, as data): scope and agent target retained; an absent optional
    host target is 'absent', never a failed installed target."""
    packaged = skill._dir_hash(skill.ASSETS)
    targets: list[tuple[str, str | None, Path]] = [
        ("user", None, skill._scope_target("user")),
        ("project", None, skill._scope_target("project")),
    ]
    for agent, (user, project) in sorted(skill.AGENT_DIRS.items()):
        targets.append(("user", agent, Path(user).expanduser()))
        targets.append(("project", agent, Path(project).absolute()))
    views = []
    for scope, agent, path in targets:
        if not path.exists() and not path.is_symlink():
            state = "absent"
        else:
            state = "ok" if skill._dir_hash(path.resolve()) == packaged else "drift"
        views.append(
            {
                "scope": scope,
                "agent": agent,
                "path": str(path),
                "state": state,
            }
        )
    return views


# ------------------------------------------------------------- the report


def build_report(args: argparse.Namespace) -> dict:
    """Assemble the five fixed sections plus the overall ready flag. Pure
    reads: no source connection, no compilation, no network, no writes."""
    cwd = Path.cwd()
    kind, logical_root, artifact_root = _resolve_route(args, cwd)
    staging = _staging_dir(args, logical_root)

    git = {"available": _git_available(), "repository_root": None, "commit_identity": None}
    repo_ok = identity_ok = False
    if kind == "git_managed":
        git["repository_root"] = _repo_root(logical_root)
        repo_ok = (
            git["repository_root"] is not None
            and Path(git["repository_root"]).resolve() == logical_root
        )
        identity_ok = _git_identity_ok(logical_root)
        git["commit_identity"] = identity_ok
    admitted = _managed_admission(logical_root) if kind == "git_managed" else None
    artifact_state = None
    if kind == "legacy_staged" and artifact_root is not None:
        artifact_state = "promoted" if _is_served_root(artifact_root) else "incomplete"
    if kind == "git_managed" and admitted is not None and admitted["state"] == "valid":
        # the resolved artifact root of a valid admission is the PINNED snapshot
        artifact_root = admitted["snapshot"]
        artifact_state = "promoted"

    approvals = _approvals(logical_root) if kind == "git_managed" else None
    pending = _managed_proposals(logical_root, approvals) if kind == "git_managed" else []
    if kind == "git_managed":
        assert admitted is not None  # computed for the managed kind just above
        sources_section = _managed_sources(logical_root, admitted, approvals)
        if admitted is not None and admitted["state"] != "valid":
            sources_section["pending"] = [
                {
                    key: entry.get(key)
                    for key in ("id", "candidate_revision", "source_digest", "approved")
                }
                for entry in pending
            ]
        examples_root = logical_root
    else:
        sources_section = _legacy_sources(args, cwd)
        examples_root = artifact_root

    work_pending: dict[str, Any] = {"answer_examples": _example_counts(examples_root, staging)}
    if kind == "git_managed":
        work_pending["proposals"] = pending
    else:
        work_pending["staged_artifacts"] = _legacy_staging(staging)

    report = {
        "project": {
            "kind": kind,
            "logical_root": str(logical_root),
            "artifact_root": str(artifact_root) if artifact_root else None,
            "artifact_state": artifact_state,
            "git": git,
            "admission": _admission_view(admitted),
        },
        "sources": sources_section,
        "work_pending": work_pending,
        "skill": {"targets": _skill_targets()},
        "next_steps": [],
        "ready": False,
        "ready_reason": None,
    }
    steps = _next_steps(
        kind,
        logical_root,
        artifact_state,
        git,
        repo_ok,
        identity_ok,
        admitted,
        sources_section,
        work_pending,
        staging,
        report["skill"]["targets"],
    )
    ready, reason = _readiness(kind, artifact_root, artifact_state, admitted, sources_section)
    report["next_steps"] = steps
    report["ready"] = ready
    report["ready_reason"] = reason
    return report


def _admission_view(admitted: dict | None) -> dict:
    if admitted is None:
        return {"state": "n/a"}
    view = {"state": admitted["state"]}
    if admitted["state"] == "valid":
        view["revision"] = admitted.get("revision")
        view["artifact_digest"] = admitted.get("artifact_digest")
        view["context_only"] = admitted["catalog"]["context_only"]
        view["catalog"] = admitted["catalog"]
    elif admitted["state"] == "invalid":
        view.update(
            {key: admitted.get(key) for key in ("revision", "artifact_digest") if admitted.get(key)}
        )
        view["reason"] = admitted.get("reason")
    return view


def _readiness(
    kind, artifact_root, artifact_state, admitted, sources_section
) -> tuple[bool, str | None]:
    """The bounded ready flag: artifact prerequisites for governed metric
    querying only — never compilation, live source health or correctness."""
    if kind == "none":
        return False, (
            "no managed .ariadne/ state and no promoted legacy artifacts under "
            "the working directory"
        )
    if kind == "legacy_staged":
        if artifact_state != "promoted":
            return False, (
                f"the selected legacy artifact root lacks context_layer/ or "
                f"semantic_layer/models/ ({artifact_root})"
            )
        if not sources_section.get("readable") or not sources_section.get("entries"):
            if sources_section.get("selection") == "--db":
                return False, f"the --db file does not exist ({sources_section.get('path')})"
            if sources_section.get("selection") == "invalid":
                return False, f"the source registry is unreadable ({sources_section.get('error')})"
            return False, (
                "no source configuration readable (pass --sources/--db or declare "
                "sources in ariadne.yaml)"
            )
        return True, None
    # managed
    state = admitted["state"]
    if state == "none":
        return False, (
            "no admission recorded — a human must review and admit a validated candidate revision"
        )
    if state == "invalid":
        return False, f"admission invalid — {admitted.get('reason')}"
    if admitted["catalog"]["context_only"]:
        return False, (
            "context-only admission — no metric catalog (the admitted context is available)"
        )
    return True, None


def _next_steps(
    kind,
    logical_root,
    artifact_state,
    git,
    repo_ok,
    identity_ok,
    admitted,
    sources_section,
    work_pending,
    staging,
    skill_targets,
) -> list[str]:
    """Ordered EXACT commands for actual blockers only (never executed):
    Git preparation, source approval, authoring/repair/validation, human
    review/admission or skill wiring. Backlog counts are not blockers."""
    steps: list[str] = []
    root = str(logical_root)
    if kind == "none":
        steps.append("ariadne-init — scaffold an Ariadne project in this directory")
        return _skill_steps(skill_targets, steps)
    if kind == "git_managed":
        if not git["available"]:
            steps.append(
                "install Git and put 'git' on PATH — Git authoring needs a local git executable"
            )
            return _skill_steps(skill_targets, steps)
        if git["repository_root"] is None:
            steps.append(f"git init {root} — the data project must be its own Git repository")
        elif not repo_ok:
            steps.append(
                f"run from the repository's top-level directory ({git['repository_root']}), "
                f"not a subdirectory of {root}"
            )
        if git["repository_root"] is not None and not identity_ok:
            steps.append(
                f'git config user.name "…" && git config user.email "…" (repo-local in {root}) '
                "— commits need an operator identity"
            )
        state = admitted["state"]
        if state == "invalid":
            steps.append(
                f"human resolution required: the admission state is inconsistent "
                f"({admitted.get('reason')}) — inspect {proposals.ARIADNE_STATE_DIR}/, repair or "
                "re-admit a reviewed/validated revision; never a fallback"
            )
        elif state == "none":
            if not work_pending.get("proposals"):
                if git["repository_root"] is not None and identity_ok:
                    steps.append(
                        f"ariadne-authoring start --project {root} — start the first proposal"
                    )
            else:
                steps.extend(_proposal_steps(root, work_pending["proposals"]))
        elif admitted["catalog"]["context_only"]:
            steps.append(
                f"ariadne-authoring start --project {root} — author semantic models; the admitted "
                "snapshot is context-only (metric operations need a catalog)"
            )
        return _skill_steps(skill_targets, steps)
    # legacy: pending staged work is directed to review or promotion only
    # when it blocks a usable served state; a ready root's drafts are backlog
    # states, not blockers (spec 0016: backlog counts are not failures)
    staged = work_pending.get("staged_artifacts") or {"count": 0, "review_needed": []}
    if staged["review_needed"]:
        steps.append(
            "review required: "
            + ", ".join(staged["review_needed"])
            + " carry status: review_needed — resolve the marker by hand; "
            "promotion refuses them"
        )
    elif artifact_state != "promoted" and staged["count"]:
        steps.append(
            f"ariadne-promote --staging {staging} — human promotion of the staged "
            "artifacts (the command itself prompts for human confirmation)"
        )
    elif artifact_state != "promoted":
        steps.append(
            "no promoted artifacts: expected context_layer/ and semantic_layer/models/ in the "
            "working directory or ./served — author and promote, or pass --served PATH"
        )
    if not sources_section.get("readable") or not sources_section.get("entries"):
        if sources_section.get("selection") == "--db":
            steps.append(
                f"create or point --db at an existing database ({sources_section.get('path')})"
            )
        elif sources_section.get("selection") == "invalid":
            steps.append(f"fix the source registry ({sources_section.get('error')})")
        else:
            steps.append(
                "declare sources in ./ariadne.yaml or pass --sources REGISTRY / --db SQLITE — "
                "the runtime never guesses a database"
            )
    return _skill_steps(skill_targets, steps)


def _proposal_steps(root: str, pending: list[dict]) -> list[str]:
    """The next command per proposal, most-advanced first: approval precedes
    validation, validation precedes the human review/admission pair. A
    review_needed artifact never gets an unconditional recommendation."""
    order = {"validated": 0, "unvalidated": 1, "invalid": 2, "unreadable": 3}
    steps = []
    for entry in sorted(
        pending, key=lambda e: order.get(e.get("validation", {}).get("state", "invalid"), 9)
    ):
        pid = entry["id"]
        revision = entry.get("candidate_revision")
        if entry.get("state") == "unreadable":
            steps.append(
                f"human resolution required: proposal {pid}'s record is unreadable "
                f"({entry.get('reason')})"
            )
            continue
        validation = entry.get("validation", {}).get("state")
        if entry.get("repair") == "review_needed":
            steps.append(
                f"review required: proposal {pid} exhausted its bounded repair — a human decides "
                "whether to keep repairing or discard it"
            )
            continue
        if validation == "validated":
            steps.append(
                f"ariadne-authoring review --project {root} --proposal {pid} — display the exact "
                "candidate for human review"
            )
            steps.append(
                f"ariadne-admit --project {root} --proposal {pid} --revision {revision} "
                "--reviewed-digest <digest from that review> — the human admission step"
            )
            continue
        if validation == "invalid":
            steps.append(
                f"repair proposal {pid}'s reported errors, then ariadne-authoring validate "
                f"--project {root} --proposal {pid} --expected-revision <current revision>"
            )
            continue
        if entry.get("sources_declared") and not entry.get("approved"):
            steps.append(
                f"ariadne-authoring approve-sources --project {root} --proposal {pid} "
                f"--revision {revision} --source-digest {entry.get('source_digest')} "
                "(HUMAN-ONLY: records the operator's source permission)"
            )
            continue
        if validation == "unreadable":
            steps.append(
                f"human resolution required: proposal {pid}'s validation evidence is unreadable "
                f"({entry['validation'].get('reason')})"
            )
            continue
        steps.append(
            f"ariadne-authoring validate --project {root} --proposal {pid} "
            f"--expected-revision {revision}"
        )
    return steps


def _skill_steps(targets: list[dict], steps: list[str]) -> list[str]:
    """Only DRIFTED installed targets need action; absent optional targets
    are honest 'absent' states, never failures or install orders."""
    for target in targets:
        if target["state"] != "drift":
            continue
        agent = f" --agent {target['agent']}" if target["agent"] else ""
        steps.append(
            f"ariadne-skill install --scope {target['scope']}{agent} — refresh the drifted "
            f"installed skill at {target['path']}"
        )
    return steps


# ------------------------------------------------------------- rendering


def _row(label: str, value: Any) -> str:
    return f"  {label:<{_LABEL}}{value}"


def _render(report: dict) -> str:
    """The human view: the same states as --json, as aligned text."""
    lines: list[str] = []
    project = report["project"]
    lines.append("Project")
    lines.append(_row("kind:", project["kind"]))
    lines.append(_row("logical root:", project["logical_root"] or "n/a"))
    artifact = project["artifact_root"]
    if artifact:
        state = "promoted" if project["artifact_state"] == "promoted" else project["artifact_state"]
        shown = artifact if state == "promoted" else f"{artifact} ({state})"
        lines.append(_row("artifact root:", shown))
    else:
        lines.append(_row("artifact root:", "none"))
    git = project["git"]
    lines.append(_row("git:", "available" if git["available"] else "not available"))
    lines.append(_row("repository root:", git["repository_root"] or "n/a"))
    identity = git["commit_identity"]
    identity_text = "n/a" if identity is None else ("set" if identity else "missing")
    lines.append(_row("git identity:", identity_text))
    admission = project["admission"]
    if admission["state"] == "valid":
        text = (
            f"valid — pinned revision {admission['revision'][:12]}…, artifact digest "
            f"{admission['artifact_digest'][:12]}…"
        )
        if admission["context_only"]:
            text += " (context-only: no metric catalog)"
        lines.append(_row("admission:", text))
    elif admission["state"] == "n/a":
        lines.append(_row("admission:", "n/a"))
    else:
        reason = f" — {admission['reason']}" if admission.get("reason") else ""
        lines.append(_row("admission:", f"{admission['state']}{reason}"))
    lines.append("")
    lines.extend(_render_sources(report["sources"]))
    lines.append("")
    lines.extend(_render_work(report["work_pending"]))
    lines.append("")
    lines.append("Skill")
    for target in report["skill"]["targets"]:
        who = target["agent"] or "skill root"
        lines.append(_row(f"{target['scope']}/{who}:", f"{target['state']}  {target['path']}"))
    lines.append("")
    lines.append("Next steps")
    if report["next_steps"]:
        for index, step in enumerate(report["next_steps"], 1):
            lines.append(f"  {index}. {step}")
    else:
        lines.append("  (none — no blockers)")
    lines.append("")
    if report["ready"]:
        lines.append("Ready: yes")
    else:
        lines.append(f"Ready: no — {report['ready_reason']}")
    return "\n".join(lines)


def _render_sources(section: dict) -> list[str]:
    lines = ["Sources"]
    selection = section["selection"]
    if selection == "admitted":
        lines.append(_row("state:", "admitted configuration (pinned by the valid admission)"))
        entries = section["entries"]
        digest = section["identity_digest"]
        approval = section.get("approval")
    elif selection == "scaffold":
        scaffold = section["scaffold"] or {}
        if scaffold.get("error"):
            error = str(scaffold["error"])
            lines.append(_row("state:", f"scaffold declarations — unreadable ({error})"))
            return lines
        lines.append(_row("state:", "scaffold declarations (not admitted)"))
        entries = scaffold.get("entries")
        digest = scaffold.get("identity_digest")
        approval = scaffold.get("approval")
        lines.append(_row("registry:", scaffold.get("path")))
    else:
        lines.append(_row("state:", selection))
        if section.get("error"):
            lines.append(_row("registry error:", section["error"]))
        if section.get("path"):
            lines.append(_row("registry:", section["path"]))
        entries = section.get("entries")
        digest = section.get("identity_digest")
        approval = section.get("approval")
    if entries is not None:
        types = ", ".join(f"{count} {kind}" for kind, count in sorted(_types_of(entries).items()))
        lines.append(_row("count:", f"{len(entries)}" + (f" ({types})" if types else "")))
    if digest:
        lines.append(_row("identity digest:", f"{digest[:12]}…"))
    if selection in ("admitted", "scaffold"):
        approval_text = (
            "recorded" if approval else ("not recorded" if approval is not None else "unreadable")
        )
        lines.append(_row("approval:", approval_text))
    for entry in section.get("pending") or []:
        state = "approved" if entry.get("approved") else "unapproved"
        lines.append(
            _row(
                f"proposal {entry['id']}:",
                f"{state}, revision {str(entry.get('candidate_revision'))[:12]}…",
            )
        )
    return lines


def _render_work(work: dict) -> list[str]:
    lines = ["Work pending"]
    if "proposals" in work:
        if work["proposals"]:
            for entry in work["proposals"]:
                if entry.get("state") == "unreadable":
                    reason = str(entry.get("reason"))
                    lines.append(_row(f"proposal {entry['id']}:", f"unreadable — {reason}"))
                    continue
                validation = entry.get("validation", {})
                state = validation.get("state", "n/a")
                detail = f"revision {str(entry.get('candidate_revision'))[:12]}… — {state}"
                if entry.get("repair") == "review_needed":
                    detail += " (repair exhausted: review needed)"
                lines.append(_row(f"proposal {entry['id']}:", detail))
        else:
            lines.append(_row("proposals:", "none"))
    else:
        staged = work["staged_artifacts"]
        review = ", ".join(staged["review_needed"])
        lines.append(
            _row(
                "staged artifacts:",
                str(staged["count"]) + (f" — review_needed: {review}" if review else ""),
            )
        )
    examples = work["answer_examples"]
    by_status = ", ".join(
        f"{count} {status}" for status, count in sorted(examples["by_status"].items())
    )
    lines.append(_row("answer examples:", by_status or "none"))
    return lines


def run(args: argparse.Namespace) -> int:
    """The status subcommand entry (wired in :mod:`ariadne.cli`): print the
    report — one JSON object with ``--json``, aligned human text otherwise —
    and exit 0. Invalid selectors/ambiguous roots raise before this point and
    keep the shared CLI error contract."""
    report = build_report(args)
    if args.json:
        print(json.dumps(report))
    else:
        print(_render(report))
    return 0
