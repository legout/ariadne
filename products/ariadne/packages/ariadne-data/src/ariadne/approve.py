"""``ariadne approve``: the one interactive approval (spec 0040 §3.4–3.5).

A draft is either a **source approval** (it adds or changes a source identity; it may
contain only ``ariadne.yaml``) or a **calculation approval** (everything else, using
only granted identities). A mixed draft is refused.

Source approval: offline checks and display, TTY consent, identity recheck, the bounded
live checks inside the approval transaction, then the grant is appended and the
generation consumed into the approved source baseline. Nothing is read before "yes"; a
failure writes no grant and leaves the served release byte-identical.

Calculation approval: validate (reusing a matching validation), display the review and
composite, TTY consent, then ``admit_revision`` pinned to the displayed generation,
revision, digest and served base.

The TTY prompt is an operator-consent convention, not authentication and not a sandbox
(spec 0040 §3.5). No flag or environment variable skips it; this module is imported by
no agent surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ariadne import admission, authoring, authoring_sources, draft, execution, proposals
from ariadne import profile_pair as profiles

SOURCE_FILES = frozenset({"ariadne.yaml"})


class ApprovalRefused(ValueError):
    """The approval did not happen; nothing changed."""


def require_tty(stdin: Any, stdout: Any) -> None:
    if not (stdin.isatty() and stdout.isatty()):
        raise ApprovalRefused(
            "approve needs an interactive terminal on stdin and stdout; there is no "
            "flag or environment variable that skips the prompt — nothing was changed"
        )


def ask(stdin: Any, stdout: Any, question: str) -> bool:
    stdout.write(f"{question} [yes/no] ")
    stdout.flush()
    return stdin.readline().strip().lower() in ("y", "yes")


def attribution(project: Path) -> str:
    """The resolved Git identity as an attribution LABEL (not authentication)."""
    name = proposals._git(["config", "--get", "user.name"], project, check=False).stdout.strip()
    mail = proposals._git(["config", "--get", "user.email"], project, check=False).stdout.strip()
    if not (name and mail):
        raise ApprovalRefused("no Git identity resolves (user.name/user.email) for attribution")
    return f"human:{name} <{mail}>"


def _view(project: Path) -> tuple[dict, dict]:
    view = draft.status(project)
    if view is None:
        raise ApprovalRefused("there is no active draft to approve")
    if view["stale"]:
        raise ApprovalRefused("the draft is stale — run 'draft rebase' first; nothing changed")
    record = proposals._load_record(project, draft.proposal_of(project, _expect(view)))
    return view, record


def _expect(view: dict) -> tuple[int, str]:
    return (view["generation"], view["candidate_revision"])


def classify(project: Path, view: dict, record: dict) -> dict:
    """``{kind, new, resolved, digest, changed}`` for the draft at ``view``."""
    revision = view["candidate_revision"]
    resolved, digest = authoring_sources.candidate_sources(project, revision)
    new = [
        entry
        for entry in resolved or []
        if authoring_sources._covering(
            project, entry, authoring_sources.storage_bindings_from_identity([entry])
        )
        is None
    ]
    changed = proposals._git(
        ["diff", "--name-only", record["base_revision"], revision], project
    ).stdout.split()
    if new:
        extra = sorted(set(changed) - SOURCE_FILES)
        if extra:
            names = ", ".join(e["name"] for e in new)
            raise ApprovalRefused(
                f"the draft adds or changes a source identity ({names}) "
                f"and also changes {', '.join(extra)} — approve the sources first: a "
                "source approval may contain only source declarations and storage "
                "profiles; move the other changes into a later draft"
            )
    return {
        "kind": "source" if new else "calculation",
        "new": new,
        "resolved": resolved or [],
        "digest": digest,
        "changed": changed,
    }


def _identity_lines(entries: list[dict]) -> list[str]:
    lines = []
    for entry in entries:
        where = entry.get("path") or f"${entry.get('connection_env')}"
        storage = entry.get("storage")
        extra = f" (storage {storage['name']})" if isinstance(storage, dict) else ""
        lines.append(f"  {entry['name']}: {entry['type']} {where}{extra}")
    return lines


def approve_sources(project: Path, view: dict, record: dict, kind: dict, stdin, stdout) -> dict:
    new = kind["new"]
    bindings = authoring_sources.storage_bindings_from_identity(new)  # offline; refuses early
    stdout.write("Source approval (no source has been read):\n")
    stdout.write("\n".join(_identity_lines(new)) + "\n")
    if bindings:
        stdout.write(f"Effective bindings: {json.dumps(bindings, sort_keys=True)}\n")
    stdout.write("Live checks (attach, catalog enumeration) run only after you answer yes.\n")
    by = attribution(project)
    if not ask(stdin, stdout, "Grant read access for authoring to these exact sources?"):
        raise ApprovalRefused("refused at the prompt — no grant was written")
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        # recheck the displayed generation, revision AND resolved identity under the lock
        current = draft._load_slot(project)
        if (
            current is None
            or current["state"] != "active"
            or (current["generation"], current["candidate_revision"]) != _expect(view)
        ):
            raise ApprovalRefused("the draft changed during the prompt — nothing was changed")
        resolved, _digest = authoring_sources.candidate_sources(project, view["candidate_revision"])
        if [e for e in resolved or [] if e in new] != new or (
            authoring_sources.storage_bindings_from_identity(new) != bindings
        ):
            raise ApprovalRefused("the source identity changed during the prompt — nothing changed")
        # live checks inside the transaction: any failure raises before the grant
        owned = execution.DuckDBExecution(
            authoring_sources.identity_registry(new, bindings), locked=True
        )
        try:
            tables = sum(len(source["tables"]) for source in owned.catalog)
        finally:
            owned.close()
        result = authoring_sources.record_grants(
            project,
            new,
            authoring_sources.resolved_digest(new),
            by=by,
            generation=view["generation"],
            _lock_held=True,
        )
        draft.set_source_baseline(project, view["candidate_revision"])
        draft.consume(project, record["id"])
    return {
        "approved": "sources",
        "sources": [e["name"] for e in new],
        "tables_enumerated": tables,
        "grants": result["grants"],
        "approval_digest": result["approval_digest"],
    }


def _summary(review: dict, composite: dict, selections: list) -> list[str]:
    report = review["report"] or {}
    lines = [
        f"Calculation approval of draft revision {review['revision'][:12]}",
        f"Review digest: {review['review_digest']}",
        f"Composite digest: {composite['digest']}",
        "Changes:",
        *(f"  {c['change']} {c['path']}" for c in review["changes"]),
        f"Validation: {report.get('status')}",
    ]
    if selections:
        lines.append("Mapping confirmations (numbered):")
        lines += [f"  {n}. {s}" for n, s in enumerate(selections, 1)]
    return lines


def approve_calculation(
    project: Path, view: dict, record: dict, confirm_mappings: list[str], stdin, stdout
) -> dict:
    settings = profiles.load(project)  # refuses by naming the file; never defaults
    proposal = record["id"]
    validated = draft.validate(project, _expect(view))
    if not validated["ok"]:
        raise ApprovalRefused("validation failed: " + "; ".join(validated["errors"][:5]))
    view = validated["draft"]  # validation may have finalized: display THESE bytes
    review = authoring.review_proposal(project, proposal)
    served = admission.load_current(project)
    expected_current = (
        served["bound_release"]["knowledge"]["published_version"]
        if served and served.get("bound_release")
        else "none"
    )
    composite = admission.overall_review(
        project,
        proposal,
        review["revision"],
        review["review_digest"],
        destination=settings["publication_destination"],
        expected_current=expected_current,
        scope=tuple(settings["visibility_scope"]),
        confirm_mappings=confirm_mappings,
        private_profile=settings["lumio_profile"],
    )
    stdout.write("\n".join(_summary(review, composite, confirm_mappings)) + "\n")
    by = attribution(project)
    if not ask(stdin, stdout, "Approve and serve exactly this revision?"):
        raise ApprovalRefused("refused at the prompt — nothing was changed")
    out = admission.admit_revision(
        project,
        proposal,
        review["revision"],
        review["review_digest"],
        confirmed_by=by,
        confirm_mappings=confirm_mappings,
        overall_preview=composite,
        confirmed_overall_digest=composite["digest"],
        private_profile=settings["lumio_profile"],
        draft_pin={
            "generation": view["generation"],
            "base_served_revision": view["base_served_revision"],
        },
    )
    return {"approved": "calculation", "revision": out["commit"], "digest": composite["digest"]}


def approve(
    project: str | Path,
    *,
    confirm_mappings: list[str] | None = None,
    stdin: Any,
    stdout: Any,
) -> dict:
    """The command body. ``stdin``/``stdout`` must be terminals."""
    project = Path(project).resolve()
    require_tty(stdin, stdout)
    view, record = _view(project)
    kind = classify(project, view, record)
    if kind["kind"] == "source":
        if confirm_mappings:
            raise ApprovalRefused("--confirm-mapping belongs to a calculation approval")
        return approve_sources(project, view, record, kind, stdin, stdout)
    return approve_calculation(project, view, record, list(confirm_mappings or []), stdin, stdout)
