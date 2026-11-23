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
import unicodedata
from pathlib import Path
from typing import Any

from ariadne import (
    admission,
    authoring,
    authoring_inputs,
    authoring_sources,
    draft,
    execution,
    proposals,
)
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


def esc(value: object) -> str:
    """Make an untrusted value safe to print on the human's terminal: every control
    character (C0, DEL, C1, including ESC and CR) becomes a visible ``\\xNN``/``\\uNNNN``."""
    out = []
    for ch in str(value):
        if unicodedata.category(ch) == "Cc" or ch in "\u2028\u2029":
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 256 else f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _identity_lines(entries: list[dict], *, prefix: str = "  ") -> list[str]:
    """One escaped line per source with its COMPLETE identity: type, path or URI (DSN
    variable name for postgres), table, read-only flag, storage profile with endpoint
    variable, region variable and scopes."""
    lines = []
    for entry in entries:
        where = entry.get("path") or f"${entry.get('connection_env')}"
        parts = [f"{esc(entry['name'])}: {esc(entry['type'])} {esc(where)}"]
        if entry.get("table"):
            parts.append(f"table={esc(entry['table'])}")
        parts.append("read-only" if entry.get("read_only", True) else "WRITABLE")
        storage = entry.get("storage")
        if isinstance(storage, dict):
            parts.append(
                f"storage={esc(storage['name'])}"
                f" endpoint-var={esc(storage.get('endpoint_url_env'))}"
                f" region-var={esc(storage.get('region_env'))}"
                f" scopes={esc(','.join(storage.get('scopes') or []))}"
            )
        lines.append(prefix + " ".join(parts))
    return lines


def _previous_identities(project: Path, names: set[str]) -> dict[str, dict]:
    """The identity each named source had before this draft: the served release's, else
    the newest source grant's (None when it is brand new)."""
    previous: dict[str, dict] = {}
    for grant in authoring_sources._load_grants(project):
        if grant["source"]["name"] in names:
            previous[grant["source"]["name"]] = grant["source"]
    served = admission.load_current(project)
    for entry in (served or {}).get("sources") or []:
        if entry["name"] in names:
            previous[entry["name"]] = entry
    return previous


def approve_sources(project: Path, view: dict, record: dict, kind: dict, stdin, stdout) -> dict:
    new = kind["new"]
    bindings = authoring_sources.storage_bindings_from_identity(new)  # offline; refuses early
    previous = _previous_identities(project, {e["name"] for e in new})
    stdout.write("Source approval (no source has been read):\n")
    for entry in new:
        old = previous.get(entry["name"])
        if old is None:
            stdout.write(
                f"NEW source:\n{chr(10).join(_identity_lines([entry], prefix='    + '))}\n"
            )
        else:
            stdout.write(
                f"CHANGED source {esc(entry['name'])}:\n"
                f"{chr(10).join(_identity_lines([old], prefix='    - '))}\n"
                f"{chr(10).join(_identity_lines([entry], prefix='    + '))}\n"
            )
    stdout.write(f"Grant delta: {len(new)} source(s) will be granted read access for authoring.\n")
    if bindings:
        stdout.write(f"Effective bindings: {esc(json.dumps(bindings, sort_keys=True))}\n")
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
        # the host-owned profiling deadline bounds setup and catalog reads: an unreachable
        # remote cannot hold the project lock (spec 0040 §3.4.2.4)
        limits = authoring_inputs.project_profiling_limits(project)
        owned = execution.DuckDBExecution(
            authoring_sources.identity_registry(new, bindings),
            budget=execution.DeadlineBudget(limits["execution_seconds"]),
            locked=True,
        )
        try:
            tables = sum(len(source["tables"]) for source in owned.catalog)
        finally:
            owned.close()
        # ONE recoverable transaction (finding 1): journal first; the grant file is the
        # commit point and is written LAST, so only a committed grant authorizes reads. Any
        # failure restores the previous baseline and the active draft.
        draft.begin_source_txn(project, len(authoring_sources._load_grants(project)) + len(new))
        try:
            draft.set_source_baseline(project, view["candidate_revision"])
            draft.consume(project, record["id"])
            result = authoring_sources.record_grants(
                project,
                new,
                authoring_sources.resolved_digest(new),
                by=by,
                generation=view["generation"],
                _lock_held=True,
            )
        except BaseException:
            draft.recover(project)  # rolls back (grants not committed), drops the journal
            raise
        draft.end_source_txn(project)
    return {
        "approved": "sources",
        "sources": [e["name"] for e in new],
        "tables_enumerated": tables,
        "grants": result["grants"],
        "approval_digest": result["approval_digest"],
    }


def _diff_lines(project: Path, record: dict, review: dict, limit: int = 120) -> list[str]:
    """The changed artifacts and definitions: the escaped, bounded unified diff of the
    draft against its base — the content the operator is actually confirming."""
    out = proposals._git(
        ["diff", "--no-color", "--no-ext-diff", record["base_revision"], review["revision"]],
        project,
        check=False,
    ).stdout.splitlines()
    shown = [f"    {esc(line)}" for line in out[:limit]]
    if len(out) > limit:
        shown.append(f"    … {len(out) - limit} more diff line(s) — run 'ariadne diff' for all")
    return shown


def _summary(
    project: Path, record: dict, review: dict, composite: dict, selected: list[dict]
) -> list[str]:
    report = review["report"] or {}
    lines = [
        f"Calculation approval of draft revision {review['revision'][:12]}",
        f"Review digest: {review['review_digest']}",
        f"Composite digest: {composite['digest']}",
        f"Validation: {esc(report.get('status'))}",
        "Changed artifacts:",
        *(f"  {esc(c['change'])} {esc(c['path'])}" for c in review["changes"]),
        "Changed content:",
        *_diff_lines(project, record, review),
    ]
    if selected:
        lines.append("Mapping confirmations (numbered; each is confirmed ONLY by this approval):")
        for number, item in enumerate(selected, 1):
            assertion = item["assertion"]
            lines.append(f"  {number}. {esc(item['selection'])} claim={esc(assertion['claim'])}")
            lines.append(
                f"     {esc(assertion['from'])} -> {esc(assertion['to'])} "
                f"family={esc(assertion['family'])} digest={esc(assertion['assertion_digest'])}"
            )
            lines.append(
                f"     declaration: {esc(json.dumps(assertion['declaration'], sort_keys=True))}"
            )
            for receipt in assertion["receipts"]:
                lines.append(f"     evidence: {esc(json.dumps(receipt, sort_keys=True))}")
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
        # Open decision (r1-report): the Lumio private profile is NOT passed. It would
        # demand registered original-source retention for every citation, which today's
        # default admission (no --context-private-profile) never required.
    )
    shown = admission.admission_review(
        project,
        proposal,
        review["revision"],
        review["review_digest"],
        confirm_mappings=confirm_mappings,
    )
    stdout.write(
        "\n".join(
            _summary(project, record, review, composite, shown.get("mapping_selections") or [])
        )
        + "\n"
    )
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
    display: Any = None,
) -> dict:
    """The command body. ``stdin``/``stdout`` must be terminals (exactly as strict with
    ``--json``); the summary and prompt go to ``display`` (default ``stdout``), so a JSON
    caller can keep stdout for the result only."""
    project = Path(project).resolve()
    require_tty(stdin, stdout)
    stdout = display if display is not None else stdout
    view, record = _view(project)
    kind = classify(project, view, record)
    if kind["kind"] == "source":
        if confirm_mappings:
            raise ApprovalRefused("--confirm-mapping belongs to a calculation approval")
        return approve_sources(project, view, record, kind, stdin, stdout)
    return approve_calculation(project, view, record, list(confirm_mappings or []), stdin, stdout)
