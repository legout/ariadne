"""Human Git Review Admission of a pinned snapshot (issue #37 / G5; spec
2026-10-02-0009 §§4–6, AC3/4/5/6, ADR-0003's scoped amendment + ADR-0016, plan
§2 "Project storage and authority" + the ``ariadne-admit``/``reconcile`` rows).

Source approval and artifact admission are distinct decisions, and admission
itself is a HUMAN-ONLY local decision over an EXACT reviewed and validated
candidate revision (spec §5):

- :func:`admission_review` displays the matching review/report for a proposed
  ``--proposal/--revision/--reviewed-digest`` triple and REFUSES a digest that
  does not match the current review — but displaying is never sign-off.
- :func:`admit_revision` records the operator's EXPLICIT confirmation
  (``--confirm``; a missing confirmation is an error, so no programmatic caller
  can admit by merely reading a review) and, holding the PROJECT lock before
  the PROPOSAL lock through activation, verifies the exact review digest, the
  final commit and its complete artifact bytes, the FULL validation scope
  bound to that exact commit, the validator identity against the CURRENT
  checker configuration, the operator-approved resolved source identity and
  the expected admitted baseline; only then does it materialize the admitted
  artifact scope as an IMMUTABLE snapshot under ``.ariadne/snapshots/<commit>/``
  and publish ``.ariadne/current.json`` atomically AFTER the snapshot is
  complete. A failed snapshot/record activation leaves the previous descriptor
  and answers intact, and admission never mutates the reviewed bytes (no
  frontmatter decoration, no index/log regeneration).
- K4 (issue #44, plan §2 "Admission and automatic capture"): repeated
  ``--confirm-mapping <reference-slug>:<mapping-id>`` selections confirm
  EXACTLY the named asserted mappings of the exact reviewed revision — the
  display resolves each selection and shows its exact assertion content, a
  hypothesis selection refuses, and the recorded operational evidence (the
  selections' assertion/evidence digests) lives inside the descriptor that
  already binds the reviewed revision, source identity and validator identity.
  No selection means no new confirmation; an unchanged assertion with
  unchanged verified dependencies retains its prior human evidence, a
  changed/stale/conflicting one lapses. Context-only candidates (no semantic
  declarations) carry explicit ``not_applicable`` check outcomes with reasons —
  a check is admission evidence only when passed or explained not_applicable.
- :func:`reconcile` is the human-only record of a local rebase/merge
  (``ariadne-authoring reconcile``): it requires the clean new HEAD in the
  proposal worktree and the CURRENT admitted revision in the candidate's
  ancestry, preserves proposal/repair identity, invalidates the old
  revision's validation/review, and never merges automatically or clears an
  inconsistent interrupted transition or exhausted repair state.
- :func:`resolve_admission` resolves the managed project's pinned snapshot
  for :meth:`ariadne.query.QueryRuntime.open_project`: a Git-managed project
  with no valid admission is refused — never a silent fallback to proposal
  worktrees or mutable project files — and the session re-checks the bound
  snapshot bytes and source identity.

The snapshot descriptor and its admission/validation evidence live in
operator-owned ignored state (``.ariadne/``), never inside the reviewed
artifact bytes; the atomic-write/fsync discipline is the one
:mod:`ariadne.proposals` established.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import UTC, datetime
from getpass import getuser
from pathlib import Path, PurePosixPath
from typing import NoReturn, cast

from ariadne import (  # pyright: ignore[reportMissingImports] — analysis env lacks site-packages
    authoring,
    authoring_inputs,
    authoring_sources,
    context,
    contract_inspection,  # pyright: ignore[reportMissingImports,reportAttributeAccessIssue] — new module, stale analysis index; resolves in the qualified env
    proposals,
)
from ariadne.sources import Registry
from ariadne.validate import candidate_scope_digest, validator_identity

# Operator-owned pinned-snapshot state, ignored via the repo-LOCAL exclude file
# proposals maintains (plan §2): ONE immutable snapshot per admitted commit and
# ONE atomic current-admission descriptor.
SNAPSHOTS_REL = proposals.ARIADNE_STATE_DIR / "snapshots"
CURRENT_REL = proposals.ARIADNE_STATE_DIR / "current.json"
ADMISSION_ROUTE = "git-review-admission"

# The checks a FULL, matching validation must show PASSED for admission (spec
# §5: a compile-only or failed report is not sufficient admission evidence).
# ``conformance`` stays disclosed as not-run; the live relationship audit is
# additionally required whenever the candidate carries a multi-fact graph.
# C1 (issue #77, spec 0028 §6): ``contracts`` joins the required set — a
# not_applicable outcome (with its reason) satisfies it for contract-free
# candidates, and the contracted-model gate below additionally requires the
# complete passing live evidence.
REQUIRED_CHECKS = (
    "source_boundary",
    "structural",
    "compile",
    "bind",
    "grain",
    "page_contract",
    "citations",
    "contracts",
)

_HEX64_RE = authoring_sources._HEX64_RE  # the reviewed digest is the review's sha256


class UsageError(ValueError):
    """An invocation the CLI itself rejects (argparse-level) — reported through
    the same one-JSON-error-object contract as failures (authoring_cli pattern)."""


class _Parser(argparse.ArgumentParser):
    """argparse that fails through UsageError instead of exiting with usage
    text, so a malformed invocation still writes exactly one JSON error object
    to stderr."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


# ------------------------------------------------- the current-admission record


def _expected_snapshot(commit: str) -> Path:
    """The derived snapshot location of one admitted commit — callers never
    supply a snapshot path, the descriptor names the derived location."""
    return SNAPSHOTS_REL / commit


def load_current(project: str | Path) -> dict | None:
    """The persisted current-admission descriptor (None when none exists).
    Operator-owned state: a non-regular, unreadable or malformed record is a
    human-resolution failure — never silently reset and never ignored."""
    project = Path(project)
    path = project / CURRENT_REL
    entry = proposals._lstat(path)
    if entry is None:
        return None
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"{path}: refusing a non-regular current-admission record — operator-owned "
            "state, inspect it by hand"
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path}: unreadable current-admission record ({exc}) — this needs human "
            "resolution, not an agent reset"
        ) from None
    required = {
        "route",
        "proposal",
        "commit",
        "snapshot",
        "artifact_digest",
        "review_digest",
        "source_digest",
        "sources",
        "validation",
        "confirmed",
    }
    if (
        not isinstance(record, dict)
        or not required <= set(record)
        or record.get("route") != ADMISSION_ROUTE
        or not isinstance(record.get("commit"), str)
        or not proposals._COMMIT_RE.fullmatch(record["commit"])
        or record.get("snapshot") != _expected_snapshot(record["commit"]).as_posix()
    ):
        raise ValueError(
            f"{path}: malformed current-admission record — this needs human resolution, "
            "not an agent reset"
        )
    return record


def _is_ancestor(project: Path, ancestor: str, revision: str) -> bool:
    """True when ``ancestor`` is reachable from ``revision`` (the admitted
    baseline check, AC3)."""
    proc = proposals._git(["merge-base", "--is-ancestor", ancestor, revision], project, check=False)
    return proc.returncode == 0


# ------------------------------------------------------ snapshot materialization


def _materialize_snapshot(project: Path, revision: str, blobs: list[tuple[str, bytes]]) -> Path:
    """Materialize ONLY the admitted artifact scope of ``revision`` as the
    IMMUTABLE snapshot ``.ariadne/snapshots/<commit>/`` — the exact commit
    bytes, no operational records, no uploads, no credentials (the scope
    walker already enumerates only tracked candidate-scope paths). Built in a
    hidden temporary sibling, fsynced, then atomically renamed into place, so
    no partially written snapshot ever exists under its final name; an
    existing snapshot is accepted only when byte-identical (re-admission) and
    is never overwritten."""
    root = project / SNAPSHOTS_REL
    root.mkdir(parents=True, exist_ok=True)
    final = root / revision
    proposals._refuse_symlinked_component(project, _expected_snapshot(revision))
    if final.exists():
        existing = {
            path.relative_to(final).as_posix(): path.read_bytes()
            for path in sorted(final.rglob("*"))
            if path.is_file()
        }
        if existing == dict(blobs):
            return final
        raise ValueError(
            f"{final}: the existing snapshot of {revision[:12]} does not match the "
            "commit's artifact bytes — an immutable snapshot is never overwritten; this "
            "needs human resolution, nothing was activated"
        )
    tmp = Path(tempfile.mkdtemp(dir=root, prefix=f".{revision[:12]}-"))
    try:
        for rel, blob in blobs:
            path = tmp.joinpath(*PurePosixPath(rel).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        authoring._fsync_tree(tmp)
        os.replace(tmp, final)
        proposals._fsync_path(root)
    finally:
        if tmp.is_dir():
            shutil.rmtree(tmp, ignore_errors=True)
    return final


def _publish_current(project: Path, record: dict) -> Path:
    """Publish the current-admission descriptor ATOMICALLY and durably (the
    proposal-record discipline) — called only AFTER the pinned snapshot is
    complete, so a crash before the rename leaves the previous descriptor
    serving the previous snapshot (spec §5: activation preserves the prior
    served revision). The payload and its directory entry are synced BEFORE
    the rename (the rename is the last step that can fail pre-publication);
    a failure of the post-rename directory fsync RESTORES the previous
    descriptor bytes (or removes a first-ever descriptor) and refuses — a
    reported activation failure never leaves a new descriptor silently
    serving (ticket criterion 3)."""
    path = project / CURRENT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = proposals._lstat(path)
    previous = path.read_bytes() if entry is not None and stat.S_ISREG(entry.st_mode) else None
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    proposals._fsync_path(path.parent)  # the tmp entry is durable pre-rename
    os.replace(tmp, path)
    try:
        proposals._fsync_path(path.parent)  # the rename itself is durable
    except OSError as exc:
        if _restore_previous_descriptor(project, previous):
            raise ValueError(
                "publishing the current-admission descriptor failed after the rename "
                f"({exc}) — the previous admission was restored and still serves; "
                "nothing was activated, resolve the storage failure and retry the "
                "admission"
            ) from exc
        raise ValueError(
            f"publishing the current-admission descriptor failed after the rename "
            f"({exc}) and the previous descriptor could not be restored — inspect "
            f"{path} by hand before serving anything; this needs human resolution, "
            "no agent command resets or deletes operator-owned admission state"
        ) from exc
    return path


def _restore_previous_descriptor(project: Path, previous: bytes | None) -> bool:
    """Best-effort restoration after a post-rename publication failure
    (ticket criterion 3): rewrite the previous descriptor bytes atomically
    (or remove a first-ever descriptor), so a REPORTED failure leaves the
    previous admission serving — never a silent new serve. True when the
    previous state is back in place; False when even the restore failed and
    only human resolution remains."""
    path = project / CURRENT_REL
    try:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                fh.write(previous)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        proposals._fsync_path(path.parent)
        return True
    except OSError:
        return False


# ------------------------------------------------- admission evidence verification


def _verified_evidence(project: Path, proposal: str, revision: str, review: dict) -> dict:
    """The stored validation evidence of the EXACT revision, verified as full,
    matching admission evidence (spec §5, AC4): a passing report for this very
    commit with every required check PASSED (plus the relationship audit for a
    graph candidate), a validator identity matching the CURRENT checker
    configuration, the still-approved resolved source identity the validation
    bound, and unchanged cited document bytes. Returns the evidence record
    with the VERIFIED resolved source identity under ``source_identity``
    (issue #37 fix pass: the COMPLETE resolved identity — not only its digest —
    must match the stored evidence, and the verified resolved entries are what
    the descriptor publishes)."""
    evidence = proposals.load_validation(project, proposal, revision)
    if evidence is None:
        raise ValueError(
            f"no validation evidence for proposal {proposal} at revision {revision[:12]} — "
            "admission requires full, matching validation evidence for the exact "
            "candidate revision; validate it first, nothing was activated"
        )
    if evidence.get("commit") != revision or evidence.get("status") != "validated":
        raise ValueError(
            f"the stored validation of {revision[:12]} is not a passing report for this "
            f"exact revision (status {evidence.get('status')!r}) — revalidate the final "
            "revision before admission; nothing was activated"
        )
    checks = (evidence.get("report") or {}).get("checks") or []
    by_name = {check.get("name"): check for check in checks}
    outcomes = {name: check.get("outcome") for name, check in by_name.items()}
    # K4 (issue #44, spec 0010 §9): a check is sufficient admission evidence
    # when it PASSED or is explicitly not_applicable — and only with its
    # reason: a bare not_applicable outcome is an unexplained partial report,
    # never a complete one.
    partial = [
        name for name in REQUIRED_CHECKS if outcomes.get(name) not in ("passed", "not_applicable")
    ]
    unexplained = [
        name
        for name in REQUIRED_CHECKS
        if outcomes.get(name) == "not_applicable" and not (by_name.get(name) or {}).get("detail")
    ]
    failed = sorted(name for name, outcome in outcomes.items() if outcome == "failed")
    if partial or failed or unexplained:
        detail = f"checks not passed: {', '.join(partial)}" if partial else ""
        detail += (", " if detail and failed else "") + (
            f"failed checks: {', '.join(failed)}" if failed else ""
        )
        detail += (", " if detail and unexplained else "") + (
            "not_applicable without a reason: " + ", ".join(unexplained) if unexplained else ""
        )
        raise ValueError(
            f"the validation report of {revision[:12]} is partial ({detail}) — a "
            "compile-only, failed or trimmed report is not sufficient admission "
            "evidence; revalidate the exact revision; nothing was activated"
        )
    artifact_files = set(evidence.get("artifact_files") or [])
    graph_candidate = "semantic_layer/graph.yml" in artifact_files
    if graph_candidate and outcomes.get("relationship_audit") != "passed":
        raise ValueError(
            f"the candidate of {revision[:12]} carries a multi-fact graph but its live "
            "relationship audit was not passed — revalidate the exact revision before "
            "admission; nothing was activated"
        )
    # The validator identity must be the CURRENT checker configuration (plan §2:
    # validator identity = core version + validation/compiler/execution
    # implementations + check-configuration digest): evidence from an older or
    # hand-edited configuration never poses as current.
    current_identity = validator_identity(list(evidence.get("performed_checks") or []))
    if (evidence.get("validator_identity") or {}).get("check_config_digest") != (
        current_identity["check_config_digest"]
    ):
        raise ValueError(
            f"the validation evidence of {revision[:12]} was produced by a different "
            "validator identity or check configuration — revalidate with the current "
            "validator before admission; nothing was activated"
        )
    # The resolved source identity at this exact commit must still be the
    # validated, operator-approved identity (spec §5: a committed or changed
    # registry entry never grants access) — the COMPLETE identity, not only
    # its digest: an evidence record whose stored entries differ from what the
    # commit actually resolves to (a tampered path keeping a valid digest)
    # never activates, and the runtime opens only the VERIFIED resolved
    # entries (issue #37 fix pass).
    resolved, source_digest = authoring_sources.candidate_sources(project, revision)
    if source_digest != evidence.get("source_digest"):
        raise ValueError(
            f"the resolved source identity at {revision[:12]} changed since validation — "
            "admission binds the validated source identity; revalidate first, nothing "
            "was activated"
        )
    if (evidence.get("source_identity") or []) != (resolved or []):
        raise ValueError(
            f"the stored source identity of {revision[:12]} is inconsistent with the "
            "identity resolved at this exact revision (same digest, different "
            "entries) — admission verifies and activates the COMPLETE resolved "
            "source identity, never unchecked stored evidence; revalidate the exact "
            "revision, nothing was activated"
        )
    # The COMPLETE effective storage binding must still be the validated one
    # (spec 0025 §4): the used profiles' endpoint/region values are resolved
    # here — non-secret identity reads only — and must match the binding the
    # validation measured under, so evidence from endpoint A never activates
    # a B-bound session while identical candidate bytes stay un-revalidated.
    bindings = authoring_sources.storage_bindings_from_identity(resolved)
    if (evidence.get("storage_bindings") or {}) != bindings:
        raise ValueError(
            f"the effective storage binding at {revision[:12]} changed since "
            "validation (spec 0025 §4) — endpoint changes invalidate validation "
            "reuse; revalidate against the current binding, nothing was activated"
        )
    effective = (
        authoring_sources.approval_digest(source_digest, bindings)
        if source_digest is not None
        else None
    )
    evidence = dict(evidence)
    evidence["source_identity"] = resolved or []
    evidence["storage_bindings"] = bindings
    evidence["approval_digest"] = effective
    if effective not in authoring_sources._load_approvals(project):
        raise ValueError(
            f"the source identity of {revision[:12]} ({effective}) carries NO "
            "operator approval for its effective storage binding — source "
            "approval is a separate human decision (spec §5, spec 0025 §4): "
            f"re-approve the exact identity with ariadne-authoring approve-sources; "
            "nothing was activated"
        )
    # C1 (issue #77, spec 0028 §6): the contracted-model admission gate —
    # every binding of the exact validated revision needs a COMPLETE,
    # applicable, unexpired PASSING observation of all its declared
    # schema/quality requirements. Static-only or missing evidence (not_run),
    # drift/unavailable/unsupported/refused/error outcomes, incomplete
    # (budget-exhausted) scope and expired observations all block; reuse
    # retained the original observation time, which is what expires here.
    contracts = evidence.get("contracts") or {}
    if contracts.get("bindings"):
        observations = {
            observation.get("binding"): observation
            for observation in contracts.get("observations") or []
            if isinstance(observation, dict)
        }
        max_age_hours = authoring_inputs.project_inspection_limits(project)["receipt_max_age_hours"]
        for binding in contracts["bindings"]:
            observation = observations.get(binding.get("id"))
            if observation is None:
                raise ValueError(
                    f"the candidate of {revision[:12]} binds dataset "
                    f"{binding.get('model')}.{binding.get('dataset')} to contract "
                    f"{binding.get('contract_id')}@{binding.get('contract_version')} but "
                    "carries no complete contract observation — unmeasured static "
                    "validation can never admit a dependent model (spec 0028 §6); "
                    "revalidate the exact revision, nothing was activated"
                )
            if observation.get("outcome") != "passed":
                raise ValueError(
                    f"the contract observation of binding {binding.get('id')!r} "
                    f"(dataset {binding.get('model')}.{binding.get('dataset')}) is "
                    f"{observation.get('outcome')!r} with non-passing requirement "
                    "outcomes — drift, unavailable, unsupported, refused, error and "
                    "not_run outcomes block admission (spec 0028 §6); nothing was "
                    "activated"
                )
            if contract_inspection.observation_expired(observation, max_age_hours):
                raise ValueError(
                    f"the contract observation of binding {binding.get('id')!r} was "
                    f"measured at {observation.get('observed_at')}, beyond the "
                    f"operator's {max_age_hours}h evidence-age budget — expired "
                    "evidence cannot admit a dependent model; revalidate the exact "
                    "revision, nothing was activated"
                )
    if contracts.get("bindings"):
        limits = authoring_inputs.project_inspection_limits(project)
        approval = {
            "sources": resolved or [],
            "approval_digest": effective,
            "storage_bindings": bindings,
        }
        tree = project / proposals.WORKTREES_REL / proposal
        if contract_inspection.contract_content_bytes(contracts) > limits[
            "response_bytes"
        ] or not contract_inspection.evidence_eligible(tree, contracts, approval, limits):
            raise ValueError(
                "contract observation dependencies, full scope or output limits are "
                "ineligible — revalidate before admission; nothing was activated"
            )
    if not authoring._document_digests_current(project, evidence.get("citations") or []):
        raise ValueError(
            f"the document evidence cited by {revision[:12]} changed since validation — "
            "revalidate the exact revision before admission; nothing was activated"
        )
    if review["report"] is None or review["report"]["revision"] != revision:
        raise ValueError(
            f"the review of {revision[:12]} carries no passing report for this exact "
            "revision — validate the exact candidate revision first; nothing was activated"
        )
    if review["validation_stale"]:
        raise ValueError(
            "the review reports stale validation evidence ("
            + "; ".join(review["stale_reasons"])
            + ") — revalidate the exact revision before admission; nothing was activated"
        )
    return evidence


def _check_reviewed_revision(project: Path, proposal: str, revision: str) -> tuple[dict, str]:
    """Resolve and bind the proposed revision to the proposal's CURRENT
    candidate (an older/different revision refuses before anything runs).
    Returns (record, full commit)."""
    record = proposals._load_record(project, proposal)
    revision = proposals._validate_revision(project, revision)
    if revision != record["candidate_revision"]:
        raise ValueError(
            f"revision {revision[:12]} is not proposal {proposal}'s current candidate "
            f"({record['candidate_revision'][:12]}) — admission activates the exact "
            "reviewed revision; re-review and admit the current candidate, nothing was "
            "activated"
        )
    return record, revision


def _require_digest(reviewed_digest: str) -> str:
    if not isinstance(reviewed_digest, str) or not _HEX64_RE.fullmatch(reviewed_digest):
        raise ValueError(
            "the reviewed digest must be the 64-hex sha256 returned by "
            "ariadne-authoring review --proposal"
        )
    return reviewed_digest


# ----------------------------------------- K4: exact-assertion human confirmation


def _parse_selection(selection: str) -> tuple[str, str]:
    """One ``--confirm-mapping <reference-slug>:<mapping-id>`` selection."""
    reference, sep, mapping = selection.partition(":")
    if not sep or not reference.strip() or not mapping.strip():
        raise ValueError(
            f"a --confirm-mapping selection is '<reference-slug>:<mapping-id>', got {selection!r}"
        )
    return reference.strip(), mapping.strip()


def _resolve_selections(assertions: list[dict], selections: list[str]) -> list[dict]:
    """Resolve every operator mapping selection against the EXACT reviewed
    revision's structured mapping assertions (plan §2): the selection names a
    reference (its page slug, or the full context-relative page path) and a
    mapping ID; only an ASSERTED mapping of the reviewed revision is
    selectable — a hypothesis is investigative knowledge and never a
    confirmed assertion, an unknown reference/mapping refuses, and a repeated
    selection confirms the same assertion once."""
    resolved: list[dict] = []
    seen: set[tuple[str, object]] = set()
    for selection in selections or []:
        reference, mapping_id = _parse_selection(selection)
        if "/" in reference:  # the page-path spelling of the same selection
            candidates = [
                entry
                for entry in assertions
                if entry["page"] == reference or entry["page"] == f"{reference}.md"
            ]
        else:
            candidates = [entry for entry in assertions if entry["reference"] == reference]
        if not candidates:
            raise ValueError(
                f"--confirm-mapping {selection!r}: no structured Reference "
                f"{reference!r} among the reviewed revision's mapping assertions"
            )
        matches = [entry for entry in candidates if entry["mapping"] == mapping_id]
        if not matches:
            available = ", ".join(
                f"{entry['reference']}:{entry['mapping']}" for entry in candidates
            )
            raise ValueError(
                f"--confirm-mapping {selection!r}: mapping {mapping_id!r} is not among "
                f"the reviewed revision's assertions (available: {available})"
            )
        [entry] = matches
        if entry["claim"] != "asserted":
            raise ValueError(
                f"--confirm-mapping {selection!r}: mapping {mapping_id!r} is classified "
                f"{entry['claim']!r} — a hypothesis stays unconfirmed investigative "
                "knowledge even when admitted; only an asserted mapping receives human "
                "confirmation"
            )
        if not entry["confirmable"]:
            raise ValueError(
                f"--confirm-mapping {selection!r}: the asserted mapping is not eligible "
                f"for confirmation ({entry['confirmation_note']})"
            )
        key = (entry["page"], entry["mapping"])
        if key not in seen:
            seen.add(key)
            resolved.append(entry)
    return resolved


def _confirmation_entry(entry: dict, *, by: str, at: str) -> dict:
    """One operational confirmation record: the exact asserted identity the
    human confirmed — page, mapping, endpoints, assertion digest and the
    verified evidence dependency digests — living inside the admission
    descriptor that already binds the exact reviewed revision, review digest,
    source identity, validator identity and admitted baseline."""
    return {
        "page": entry["page"],
        "reference": entry["reference"],
        "mapping": entry["mapping"],
        "family": entry["family"],
        "from": entry["from"],
        "to": entry["to"],
        "claim": "asserted",
        "assertion_digest": entry["assertion_digest"],
        "source_ids": list(entry["source_ids"] or []),
        "receipts": [
            {"id": receipt["id"], "digest": receipt["digest"]}
            for receipt in entry["receipts"]
            if receipt.get("digest") is not None
        ],
        "by": by,
        "at": at,
    }


def _retained_confirmations(
    assertions: list[dict],
    prior: dict | None,
    *,
    by: str,
    at: str,
    max_age_hours: float,
) -> tuple[list[dict], list[dict]]:
    """The prior admission's confirmations that survive into this admission
    WITHOUT a new selection (plan §2: unchanged assertions retain matching
    prior human evidence only with unchanged verified dependencies): an entry
    retains when the SAME page+mapping is still an asserted, confirmable
    assertion of this exact revision with the SAME effective identity digest
    (declaration plus endpoint correspondence, K4 fix pass finding 2), the
    SAME verified receipt digests AND evidence still inside the operator's
    age budget (K4 fix pass finding 3: a stored validation never keeps a
    confirmation alive past the expiry of the evidence it confirmed).
    Changed, stale, expired, conflicting or removed assertions cannot inherit
    confirmation — they lapse, and the lapse is reported for the operator."""
    retained: list[dict] = []
    lapsed: list[dict] = []
    for record in (prior or {}).get("confirmed_mappings") or []:
        if not isinstance(record, dict):
            continue
        current = next(
            (
                entry
                for entry in assertions
                if entry["page"] == record.get("page") and entry["mapping"] == record.get("mapping")
            ),
            None,
        )
        receipt_digests = sorted(
            cast(str, receipt.get("digest"))
            for receipt in record.get("receipts") or []
            if isinstance(receipt, dict)
        )
        current_digests = sorted(
            cast(str, receipt.get("digest"))
            for receipt in (current or {}).get("receipts") or []
            if isinstance(receipt, dict)
        )
        expired = [
            receipt
            for receipt in (current or {}).get("receipts") or []
            if isinstance(receipt, dict)
            and context.evidence_freshness(receipt.get("observed_at"), max_age_hours)["state"]
            == "stale"
        ]
        if (
            current is not None
            and current["claim"] == "asserted"
            and current["confirmable"]
            and current["assertion_digest"] == record.get("assertion_digest")
            and current_digests == receipt_digests
            and not expired
        ):
            entry = _confirmation_entry(current, by=by, at=at)
            entry["retained_from"] = (prior or {}).get("commit")
            entry["by"] = record.get("by")
            entry["at"] = record.get("at")
            retained.append(entry)
        else:
            if current is None:
                reason = "the assertion is no longer among the reviewed revision's mappings"
            elif expired:
                reason = (
                    "the prior verified evidence aged past the operator's "
                    f"{max_age_hours}h age budget — an expired confirmation cannot "
                    "be retained; re-inspect to attach fresh evidence and select again"
                )
            else:
                reason = (
                    "the assertion or its verified evidence dependencies changed — "
                    "a changed assertion cannot inherit prior confirmation"
                )
            lapsed.append(
                {
                    "page": record.get("page"),
                    "mapping": record.get("mapping"),
                    "reason": reason,
                }
            )
    return retained, lapsed


# ------------------------------------------------------------ the human commands


def admission_review(
    project: str | Path,
    proposal: str,
    revision: str,
    reviewed_digest: str,
    *,
    confirm_mappings: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """HUMAN-ONLY display step of ``ariadne-admit``: the matching review/report
    of the exact CURRENT candidate revision, refusing a revision or digest that
    does not match. Displaying is NEVER sign-off — the response names the
    explicit ``--confirm`` step that alone activates. K4 (issue #44): with
    ``--confirm-mapping`` selections the display resolves each selection
    against the EXACT reviewed revision's mapping assertions and shows the
    selected assertions' exact content (declaration, digest, dependencies,
    eligibility) — the operator confirms what they see, never a slug alone."""
    project = Path(project).resolve()
    _require_digest(reviewed_digest)
    _check_reviewed_revision(project, proposal, revision)
    review = authoring.review_proposal(project, proposal)
    if review["review_digest"] != reviewed_digest:
        raise ValueError(
            f"review digest mismatch: the current review of {review['revision'][:12]} is "
            f"{review['review_digest']}, not {reviewed_digest} — admission binds the "
            "exact reviewed identity; review the current candidate and pass its digest"
        )
    response = {
        "route": ADMISSION_ROUTE,
        "project": str(project),
        "proposal": proposal,
        "commit": review["revision"],
        "reviewed_digest": reviewed_digest,
        "confirmation_required": (
            "review the report above, then re-run this command with --confirm to record "
            "the operator's explicit confirmation and activate this exact revision — "
            "displaying this review is never sign-off"
        ),
        "review": review,
    }
    if confirm_mappings:
        resolved = _resolve_selections(review["mapping_assertions"], list(confirm_mappings))
        response["mapping_selections"] = [
            {"selection": f"{entry['reference']}:{entry['mapping']}", "assertion": entry}
            for entry in resolved
        ]
        response["confirmation_required"] += (
            " — the mapping selections above are confirmed ONLY together with "
            "--confirm; nothing is confirmed by this display"
        )
    return response


def _contracts_descriptor_view(contracts: dict) -> dict:
    """The bounded, credential-free contract snapshot view of an admission
    (spec 0028 §7, issue #77/C1): producer/binding identities, live outcomes
    and as-of times only — contract text, quality queries, diagnostics and
    server addresses never enter the descriptor agent surfaces read."""
    return {
        "documents": [
            {
                "path": document.get("path"),
                "digest": document.get("digest"),
                "id": document.get("id"),
                "version": document.get("version"),
                "valid": document.get("valid"),
            }
            for document in contracts.get("documents") or []
            if isinstance(document, dict)
        ],
        "bindings": list(contracts.get("bindings") or []),
        "observations": [
            {
                "binding": observation.get("binding"),
                "contract": observation.get("contract"),
                "object_id": observation.get("object_id"),
                "asset": observation.get("asset"),
                "model": observation.get("model"),
                "dataset": observation.get("dataset"),
                "outcome": observation.get("outcome"),
                "scope": observation.get("scope"),
                "observed_at": observation.get("observed_at"),
                "dependencies": observation.get("dependencies"),
                "limits": observation.get("limits"),
                "requirements": [
                    {
                        "kind": requirement.get("kind"),
                        "pointer": requirement.get("pointer"),
                        "outcome": requirement.get("outcome"),
                    }
                    for requirement in observation.get("requirements") or []
                    if isinstance(requirement, dict)
                ],
            }
            for observation in contracts.get("observations") or []
            if isinstance(observation, dict)
        ],
    }


def admit_revision(
    project: str | Path,
    proposal: str,
    revision: str,
    reviewed_digest: str,
    *,
    confirmed_by: str | None,
    confirm_mappings: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """HUMAN-ONLY activation (the ``--confirm`` half of ``ariadne-admit``):
    record the operator's explicit confirmation for the exact reviewed revision
    and activate it as the pinned served snapshot. Serializes project
    admissions (the PROJECT lock before the PROPOSAL lock, both held through
    activation), then verifies — under the locks — the exact review digest, the
    final commit and its complete artifact bytes (a dirty worktree or a moved
    candidate refuses), the FULL validation scope of that exact commit, the
    current validator identity, the approved source identity (verified as the
    COMPLETE resolved identity, never only its digest), unchanged cited
    documents and the EXPECTED admitted baseline (plan §2: the record's
    start-time baseline must equal the currently served revision — a baseline
    that advanced since, even to an ancestor of the candidate, requires
    reconcile + revalidation + re-review; AC3: a candidate that does not carry
    the currently served revision in its ancestry must be reconciled and
    revalidated, never silently replace served state). Materializes the
    snapshot, publishes ``current.json`` atomically, then marks this admission
    as the proposal's expected baseline.

    K4 (issue #44, plan §2 "Admission and automatic capture"):
    ``--confirm-mapping`` selections confirm EXACTLY the named asserted
    mappings of the exact reviewed revision — a hypothesis selection refuses,
    and the operational evidence (selections + assertion/evidence digests) is
    recorded inside the descriptor that already binds the reviewed revision,
    review digest, source identity and validator identity. No selection means
    no new mapping confirmation; an UNCHANGED prior assertion (same digest,
    same verified evidence dependencies) retains its prior human evidence
    without a new selection, while changed, stale or conflicting assertions
    lapse."""
    project = Path(project).resolve()
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise ValueError(
            "admission requires an explicit operator confirmation of the displayed "
            "review (re-run ariadne-admit with --confirm) — reading a review, or calling "
            "the read-only review operation, is never sign-off"
        )
    confirmed_by = confirmed_by.strip()
    _require_digest(reviewed_digest)
    proposals._load_record(project, proposal)
    with proposals._file_lock(project / proposals.LOCKS_REL / "project.lock"):
        with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
            record, revision = _check_reviewed_revision(project, proposal, revision)
            proposals._check_coherent(project, record)
            # The exact review digest under the lock: the review binds revision,
            # change inventory, artifact bytes and citations (spec §4/§5).
            review = authoring._review_candidate(project, proposal, record=record)
            if review["review_digest"] != reviewed_digest:
                raise ValueError(
                    f"review digest mismatch: the current review of {revision[:12]} is "
                    f"{review['review_digest']}, not {reviewed_digest} — admission binds "
                    "the exact reviewed identity (revision, content, citations); "
                    "re-review and admit the current digest, nothing was activated"
                )
            evidence = _verified_evidence(project, proposal, revision, review)
            # The expected admitted baseline (plan §2: the confirmation binds
            # the CURRENTLY expected served baseline; AC3: admission must not
            # silently erase another admitted proposal's changes). The record
            # persists the baseline the proposal started from — a baseline that
            # advanced since (another proposal's admission) refuses even when
            # the candidate already carries it in its ancestry: reconcile,
            # revalidate and re-review bind the new baseline first.
            baseline = load_current(project)
            current_commit = baseline["commit"] if baseline is not None else None
            if baseline is not None and not _is_ancestor(project, baseline["commit"], revision):
                raise ValueError(
                    f"the admitted baseline advanced to {baseline['commit'][:12]} and "
                    f"{revision[:12]} does not carry it in its ancestry — merge/rebase "
                    "the admitted baseline in by hand, run ariadne-authoring reconcile, "
                    "revalidate and re-review before admission; admission must not "
                    "silently erase another admitted proposal's changes, nothing was "
                    "activated"
                )
            expected = record.get("expected_baseline")
            if expected != current_commit:
                raise ValueError(
                    "the admitted baseline changed since proposal "
                    f"{proposal} started (the proposal expected "
                    f"{'no admission' if expected is None else expected[:12]}, the "
                    f"current admission is "
                    f"{'none' if current_commit is None else current_commit[:12]}) — "
                    "run ariadne-authoring reconcile to record the human "
                    "reconciliation of the advanced baseline, then revalidate and "
                    "re-review before admission; the confirmation binds the currently "
                    "expected served baseline, nothing was activated"
                )
            # K4 (issue #44): resolve the operator's mapping selections against
            # the EXACT reviewed revision under the locks — a hypothesis or an
            # unknown reference/mapping refuses BEFORE anything activates, and
            # unchanged prior confirmations retain only with unchanged verified
            # dependencies (changed/stale/conflicting assertions lapse).
            selected = _resolve_selections(
                review["mapping_assertions"], list(confirm_mappings or [])
            )
            now = datetime.now(UTC).isoformat(timespec="seconds")
            confirmed_mappings = [
                _confirmation_entry(entry, by=confirmed_by, at=now) for entry in selected
            ]
            retained, lapsed = _retained_confirmations(
                review["mapping_assertions"],
                baseline,
                by=confirmed_by,
                at=now,
                # K4 fix pass (finding 3): retention re-checks the operator's
                # evidence age budget at THIS admission — the receipt-attachment
                # gate runs at validation, so a stored validation of an unchanged
                # candidate never keeps a confirmation alive past its evidence's
                # expiry
                max_age_hours=authoring_inputs.project_inspection_limits(project)[
                    "receipt_max_age_hours"
                ],
            )
            selected_keys = {(entry["page"], entry["mapping"]) for entry in selected}
            confirmed_mappings += [
                entry
                for entry in retained
                if (entry["page"], entry["mapping"]) not in selected_keys
            ]
            snapshot = _materialize_snapshot(
                project, revision, proposals.scope_blobs(project, revision)
            )
            if candidate_scope_digest(snapshot) != evidence["artifact_digest"]:
                raise ValueError(
                    f"the materialized snapshot of {revision[:12]} does not match the "
                    "validated artifact digest — nothing was activated"
                )
            descriptor = {
                "route": ADMISSION_ROUTE,
                "project": str(project),
                "proposal": proposal,
                "commit": revision,
                "snapshot": _expected_snapshot(revision).as_posix(),
                "artifact_digest": evidence["artifact_digest"],
                "artifact_files": list(evidence["artifact_files"]),
                "review_digest": reviewed_digest,
                "source_digest": evidence.get("approval_digest") or evidence["source_digest"],
                "source_declaration_digest": evidence["source_digest"],
                "storage_bindings": evidence.get("storage_bindings") or {},
                "sources": evidence["source_identity"] or [],
                "validation": {
                    "commit": evidence["commit"],
                    "ok": evidence["ok"],
                    "status": evidence["status"],
                    "report": evidence["report"],
                    "performed_checks": list(evidence["performed_checks"]),
                    "validator_identity": evidence["validator_identity"],
                    "artifact_digest": evidence["artifact_digest"],
                    "source_digest": evidence["source_digest"],
                    "approval_digest": evidence.get("approval_digest"),
                    "storage_bindings": evidence.get("storage_bindings") or {},
                    "validated_at": evidence["validated_at"],
                    "evidence": str(proposals._validation_path(project, proposal, revision)),
                },
                "confirmed": {
                    "by": confirmed_by,
                    "at": now,
                    "commit": revision,
                    "review_digest": reviewed_digest,
                },
                # K4 (issue #44): the operational mapping-confirmation evidence
                # of this exact admission — fresh operator selections plus the
                # prior human evidence unchanged assertions retained. Empty
                # means no mapping is confirmed by this admission.
                "confirmed_mappings": confirmed_mappings,
                # C1 (issue #77, spec 0028 §7): the bounded, credential-free
                # contract snapshot view discovery/list_datasets annotate from
                # — identities, outcomes and as-of times only; contract text,
                # queries and server addresses never enter the descriptor.
                **(
                    {"contracts": _contracts_descriptor_view(evidence.get("contracts") or {})}
                    if (evidence.get("contracts") or {}).get("present")
                    else {}
                ),
                "admitted_at": now,
            }
            _publish_current(project, descriptor)  # AFTER the snapshot is complete
            # This admission is now the proposal's expected baseline: the next
            # admission of the SAME proposal builds on it without a reconcile
            # (its later candidates descend from this commit). The descriptor
            # is already published, so a record-store failure here leaves a
            # fail-closed stale baseline the next admission reports for
            # reconcile — activation itself succeeded and stays reported.
            record["expected_baseline"] = revision
            try:
                proposals._store_record(project, record)
            except OSError:
                pass
    return {
        "route": ADMISSION_ROUTE,
        "project": str(project),
        "proposal": proposal,
        "commit": revision,
        "reviewed_digest": reviewed_digest,
        "artifact_digest": evidence["artifact_digest"],
        # the ACTIVATED identity is the effective one the descriptor pins
        # (spec 0025 §4): the declaration digest stays visible alongside it
        "source_digest": evidence.get("approval_digest") or evidence["source_digest"],
        "source_declaration_digest": evidence["source_digest"],
        "storage_bindings": evidence.get("storage_bindings") or {},
        "snapshot": descriptor["snapshot"],
        "current": str(project / CURRENT_REL),
        "confirmed_by": confirmed_by,
        "confirmed_mappings": [
            {
                "selection": f"{entry['reference']}:{entry['mapping']}",
                "assertion_digest": entry["assertion_digest"],
            }
            for entry in selected
        ],
        "retained_confirmations": [
            {
                "selection": f"{entry['reference']}:{entry['mapping']}",
                "assertion_digest": entry["assertion_digest"],
                "retained_from": entry.get("retained_from"),
            }
            for entry in retained
            if (entry["page"], entry["mapping"]) not in selected_keys
        ],
        "lapsed_confirmations": lapsed,
        "admitted_at": now,
    }


def _interrupted_core_transition(project: Path, record: dict, new: str) -> bool:
    """True when ``new`` sits on an UNSEEN core-authored commit: along the
    first-parent line, the commit directly on top of the recorded candidate is
    core-authored (the ``ariadne: `` prefix of the edit/finalize seams) and NOT
    part of the admitted history (issue #37 fix pass, spec §4). That is the
    signature an interrupted core transition leaves — the commit landed, the
    record store failed, and the coherence gate blocks every further mutation,
    so at most one unseen core commit can exist. A human rebase/merge never
    matches: its boundary commit on the recorded candidate is human-authored
    (merge/empty/human commits), and a replayed rebase lands on the ADMITTED
    baseline, whose core-authored boundary commits were recorded through the
    admitted proposal."""
    chain = proposals._git(
        ["rev-list", "--first-parent", f"{record['candidate_revision']}..{new}"],
        project,
    ).stdout.split()
    if not chain:
        return False  # the recorded candidate is new itself: nothing unseen
    boundary = chain[-1]  # the oldest first-parent commit the record never saw
    subject = proposals._git(["log", "-1", "--format=%s", boundary], project).stdout.strip()
    if not subject.startswith(proposals._CORE_COMMIT_PREFIX):
        return False  # a human commit builds on the recorded candidate
    current = load_current(project)
    if current is not None and _is_ancestor(project, current["commit"], boundary):
        return False  # admitted history: recorded through another proposal
    return True


def reconcile(project: str | Path, proposal: str, expected_revision: str, revision: str) -> dict:
    """HUMAN-ONLY (``ariadne-authoring reconcile``): record the CLEAN new HEAD
    a human created in the proposal worktree by a local rebase/merge, after the
    admitted baseline advanced past the proposal's branch. Requires the current
    admitted revision in the new revision's ancestry (reconcile NEVER merges
    automatically), the recorded branch, a clean worktree and NO core-authored
    commit the record never saw (an interrupted commit/record transition is
    preserved for human resolution, never recorded over); preserves
    proposal/repair identity (an exhausted repair state is never cleared),
    records the advanced expected admitted baseline and invalidates the old
    revision's validation/review evidence for admission."""
    project = Path(project).resolve()
    proposals._load_record(project, proposal)
    with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
        record = proposals._load_record(project, proposal)
        worktree = project / proposals.WORKTREES_REL / proposal
        if not worktree.is_dir():
            raise ValueError(
                f"the worktree of proposal {proposal} is missing ({worktree})"
                + proposals._HUMAN_RESOLUTION
            )
        branch = proposals._git(["rev-parse", "--abbrev-ref", "HEAD"], worktree).stdout.strip()
        if branch != record["branch"]:
            raise ValueError(
                f"proposal {proposal}'s worktree is on branch {branch!r}, not its "
                f"recorded {record['branch']!r}" + proposals._HUMAN_RESOLUTION
            )
        expected = proposals._validate_revision(project, expected_revision)
        new = proposals._validate_revision(project, revision)
        if expected != record["candidate_revision"]:
            raise ValueError(
                f"stale revision: proposal {proposal}'s record names candidate "
                f"{record['candidate_revision'][:12]}, the reconcile expected "
                f"{expected[:12]} — re-read the record and reconcile from the current "
                "candidate; nothing was recorded"
            )
        head = proposals._git(["rev-parse", "HEAD"], worktree).stdout.strip()
        if head != new:
            raise ValueError(
                f"the worktree of proposal {proposal} is at {head[:12]}, not {new[:12]} — "
                "reconcile records the CLEAN new HEAD the human created (perform the "
                "rebase/merge in the worktree first); nothing was recorded"
            )
        if proposals._git(
            ["status", "--porcelain", "--untracked-files=no"], worktree
        ).stdout.strip():
            raise ValueError(
                f"the worktree of proposal {proposal} carries uncommitted changes — "
                "reconcile records a clean new HEAD only; commit or discard them by "
                "hand, then reconcile; nothing was recorded and no state was cleared"
            )
        # An interrupted core transition (the edit/finalize commit landed, the
        # record store failed) leaves exactly this pattern: an unseen
        # core-authored commit directly on the recorded candidate. Reconcile
        # records intentional HUMAN rebases only — the interrupted transition
        # stays preserved for human resolution, never recorded over (issue #37
        # fix pass, spec §4).
        if _interrupted_core_transition(project, record, new):
            raise ValueError(
                f"the branch of proposal {proposal} sits on a core-authored commit "
                "its record never saw — an interrupted core transition, and "
                "reconcile records intentional human rebases only" + proposals._HUMAN_RESOLUTION
            )
        baseline = load_current(project)
        admitted = baseline["commit"] if baseline is not None else None
        if admitted is not None and not _is_ancestor(project, admitted, new):
            raise ValueError(
                f"revision {new[:12]} does not carry the current admitted revision "
                f"{admitted[:12]} in its ancestry — merge or rebase the admitted baseline "
                "into the proposal branch BY HAND first (reconcile never merges "
                "automatically); nothing was recorded"
            )
        previous = record["candidate_revision"]
        record["candidate_revision"] = new
        record["expected_baseline"] = admitted  # the reconciled baseline is expected now
        record["reconciled"] = {
            "from": previous,
            "to": new,
            "admitted_baseline": admitted,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        record["validation"] = None  # the old revision's evidence no longer binds
        proposals._store_record(project, record)
    return {
        "proposal": proposal,
        "revision": new,
        "previous_revision": previous,
        "admitted_baseline": admitted,
        "validation_invalidated": True,
        "repair": record.get("repair") or {"attempts": 0, "status": "open"},
    }


# ------------------------------------------------ pinned-snapshot resolution


def resolve_admission(project: str | Path) -> tuple[dict, Path]:
    """The managed project's pinned snapshot + admission record for
    :meth:`ariadne.query.QueryRuntime.open_project` (plan §2): a Git-managed
    project with no valid admission is an explicit error — never a silent
    fallback to proposal worktrees or mutable project files — and an admitted
    descriptor whose snapshot bytes or approved source identity no longer
    match refuses the same way."""
    project = Path(project).resolve()
    record = load_current(project)
    if record is None:
        raise ValueError(
            f"{project} has no valid admission ({project / CURRENT_REL} is absent) — the "
            "managed Git route never falls back to proposal worktrees or mutable "
            "project files; a human must review a validated candidate revision and run "
            "ariadne-admit (display the review, then --confirm)"
        )
    proposals._validate_revision(project, record["commit"])
    snapshot = project / _expected_snapshot(record["commit"])
    proposals._refuse_symlinked_component(project, _expected_snapshot(record["commit"]))
    if not snapshot.is_dir():
        raise ValueError(
            f"{snapshot}: the pinned snapshot of admitted revision "
            f"{record['commit'][:12]} is missing — this needs human resolution; the "
            "runtime never falls back to mutable files"
        )
    digest = candidate_scope_digest(snapshot)
    if digest != record["artifact_digest"]:
        raise ValueError(
            f"the pinned snapshot no longer matches the admitted artifact digest "
            f"(snapshot {digest[:12]}… != recorded {record['artifact_digest'][:12]}…) — "
            "the served bytes changed after admission; this needs human resolution and "
            "re-admission of a reviewed/validated revision, never a fallback"
        )
    if not approval_present(project, record["source_digest"]):
        raise ValueError(
            "the admitted source identity no longer carries the operator's approval — "
            "re-approve the exact resolved identity (ariadne-authoring approve-sources) "
            "before serving; the runtime never opens an unapproved identity"
        )
    # The pinned effective storage binding must be COMPLETE, internally
    # consistent AND still be the binding the CURRENT environment resolves
    # (spec 0025 §§4/AC6): every profile the admitted sources reference must
    # carry its binding (removing the block never falls back to environment
    # re-resolution), a hand-mutated stored binding with a claimed old digest
    # refuses, and a host whose endpoint variables now point elsewhere never
    # opens the unapproved endpoint under this admission — the environment
    # check reads endpoint/region values only, never key/token values.
    bindings = record.get("storage_bindings") or {}
    referenced = {
        entry["storage"]["name"]
        for entry in record.get("sources") or []
        if isinstance(entry.get("storage"), dict) and isinstance(entry["storage"].get("name"), str)
    }
    if referenced:
        if set(bindings) != referenced:
            raise ValueError(
                "the admitted record's pinned identity is incomplete: its sources "
                f"reference storage profiles {sorted(referenced)} but the stored "
                f"effective binding covers {sorted(bindings) or 'none'} (spec 0025 "
                "§4/AC6) — a malformed or incomplete pinned identity never serves; "
                "this needs human resolution and re-admission, never a fallback"
            )
        declared = record.get("source_declaration_digest") or record["source_digest"]
        recomputed = authoring_sources.approval_digest(declared, bindings)
        if recomputed != record["source_digest"]:
            raise ValueError(
                "the admitted record's stored storage binding does not match its "
                "claimed effective source digest — a mutated binding never serves; "
                "this needs human resolution and re-admission, never a fallback"
            )
        current = authoring_sources.storage_bindings_from_identity(record.get("sources"))
        if current != bindings:
            raise ValueError(
                "the environment resolves a different effective storage binding "
                "than the admitted one (spec 0025 §4) — the pinned admission binds "
                "its exact endpoint; approve and admit the current binding before "
                "serving, never a silent endpoint switch"
            )
    return record, snapshot


def approval_present(project: str | Path, source_digest: str) -> bool:
    """True when the operator's approval of one resolved source identity is
    still on record (the session's bound source identity recheck)."""
    return source_digest in authoring_sources._load_approvals(Path(project))


def approved_registry(record: dict) -> Registry:
    """The operator-APPROVED resolved identity of an admitted record as the
    runtime's source registry: DuckDB opens exactly these resolved locations
    — the pinned snapshot's registry spelling and any snapshot-relative path
    never reach the connection (spec §5, plan §2). The record's FROZEN
    effective storage bindings (spec 0025 §4) ride the registry so the
    connection opens exactly the admitted endpoints."""
    entries = record.get("sources") or []
    if not entries:
        raise RuntimeError(
            "the admitted snapshot declares no approved source identity — there is "
            "nothing for a managed runtime to query"
        )
    return authoring_sources.identity_registry(entries, record.get("storage_bindings"))


# ------------------------------------------------------------ the ariadne-admit CLI


def main(argv: list[str] | None = None) -> int:
    """``ariadne-admit`` — HUMAN-ONLY Git Review Admission (issue #37/G5; the
    one-JSON-value/one-JSON-error-object contract of the other CLIs). Without
    ``--confirm`` it displays the matching review/report and exits; ONLY
    ``--confirm`` records the operator's explicit confirmation and activates.
    K4 (issue #44): repeated ``--confirm-mapping <reference-slug>:<mapping-id>``
    selections name the ASSERTED mappings of the exact reviewed revision whose
    human confirmation the operator records with ``--confirm`` — the display
    shows each selection's exact assertion content first. No MCP/native Agent
    surface exposes this command or its callables."""
    parser = _Parser(
        prog="ariadne-admit",
        description="Human-only Git Review Admission of a reviewed, validated candidate "
        "revision: displays the matching review, then --confirm activates the pinned "
        "snapshot.",
    )
    parser.add_argument("--project", default=".", help="the managed Git data project (default: .)")
    parser.add_argument("--proposal", required=True, help="the proposal ID")
    parser.add_argument("--revision", required=True, help="the reviewed candidate commit")
    parser.add_argument(
        "--reviewed-digest",
        required=True,
        help="the review digest ariadne-authoring review --proposal returned",
    )
    parser.add_argument(
        "--confirm-mapping",
        action="append",
        default=[],
        dest="confirm_mappings",
        metavar="REFERENCE:MAPPING",
        help="select one ASSERTED mapping of the reviewed revision for explicit "
        "human confirmation (repeatable): <reference-slug>:<mapping-id>; the "
        "display shows the exact assertion content, and the confirmation is "
        "recorded only together with --confirm",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="record the operator's explicit confirmation of the displayed review and "
        "activate this exact revision (without it, the command only displays)",
    )
    parser.add_argument(
        "--by", default=None, help="operator identity recorded with the confirmation"
    )
    try:
        args = parser.parse_args(argv)
        if args.confirm:
            result = admit_revision(
                args.project,
                args.proposal,
                args.revision,
                args.reviewed_digest,
                confirmed_by=args.by or f"human:{getuser()}",
                confirm_mappings=args.confirm_mappings,
            )
        else:
            result = admission_review(
                args.project,
                args.proposal,
                args.revision,
                args.reviewed_digest,
                confirm_mappings=args.confirm_mappings,
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
