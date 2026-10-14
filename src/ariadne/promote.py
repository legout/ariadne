#!/usr/bin/env python
"""Mechanical promotion gate (spec rev 6 §6/§8.16, ADR-0007): staging/ -> served.

Served artifacts only ever arrive by human promotion (spec §6); this script IS
that promotion, reduced to bookkeeping:

- MERGES staged ``context_layer/`` and ``semantic_layer/`` into the served roots
  (never wipes or deletes: a served file absent from staging survives).
- On each promoted OKF page appends one ``verified: {by, at}`` entry and flips
  ``status: draft -> stable``.
- Regenerates EVERY ``index.md`` in the served context bundle (root + each
  folder) from the current served contents (SPEC §8 progressive disclosure:
  section headings, links, the target's frontmatter description).
- Appends ``**Creation**/**Update**`` entries under today's ISO heading in the
  bundle's ``log.md`` (newest-first).

Idempotent: re-promoting an unchanged page is a no-op (no verified entry, no
log line, byte-identical tree). A page counts as changed when anything except
its ``verified`` list or ``status`` differs from the served copy. Pages carrying
``status: review_needed`` are refused — the human gate holds (spec §6/§7).

Usage::

    python ariadne-promote                 # interactive: lists the plan, asks
    python ariadne-promote --yes           # unattended (demo.sh, CI)
    python ariadne-promote --by human:alice

This is the LEGACY staged-project gate. A Git-managed data project does not
call it: its full-bundle route is human Git Review Admission of an exact
reviewed, validated candidate revision (``ariadne-admit --confirm``, issue
#37) — and promoting here never writes a Git admission record. The complete
legacy → new mapping lives in docs/how-to/git-authoring.md (issue #39/G7).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import (
    UTC,  # pyright: ignore[reportAttributeAccessIssue] — resolver drift: UTC is py3.11+
    datetime,
)
from getpass import getuser
from pathlib import Path

from ariadne.authoring import (
    BUNDLE_DISCARD_NAME,
    _digest,
    _graph_citation_errors,
    _registry_identity_payload,
    _tree_digest,
    bundle_lock,
    bundle_staging_dir,
    bundle_state_path,
)

# Shared Context Layer (issue #33, ADR-0016): the deterministic OKF promotion
# bookkeeping (page form, index regeneration, log append) lives in
# ariadne.context; this gate calls the shared implementations.
from ariadne.context import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    _append_log,
    _content_key,
    _load,
    _promoted_text,
    _regenerate_indexes,
)
from ariadne.validate import _digest_files, served_tree_files

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTEXT = "context_layer"


@dataclass
class Change:
    """One promotion action applied (or planned) for a staged file."""

    rel: str  # path relative to the served layer root (context_layer/…)
    action: str  # "created" | "updated"


def _staged_pages(staging: Path) -> list[Path]:
    """Staged OKF pages (bookkeeping applies), root index.md excluded — the
    author never writes one, and a stray staged index must not shadow the
    regenerated one."""
    context = staging / _CONTEXT
    if not context.is_dir():
        return []
    return sorted(p for p in context.rglob("*.md") if p.name != "index.md")


def _staged_files(staging: Path) -> list[Path]:
    """Every staged file EXCEPT the OKF pages (raw merge: models, assets)."""

    def raw(p: Path) -> bool:
        if not p.is_file():
            return False
        in_context = p.relative_to(staging).parts[0] == _CONTEXT
        return not (in_context and p.suffix == ".md")  # pages get bookkeeping

    return sorted(
        p for layer in (_CONTEXT, "semantic_layer") for p in (staging / layer).rglob("*") if raw(p)
    )


# The admission record (issue #30): the human Promotion writes this mapping of
# the staged review digest to the POST-Promotion served digest under the served
# semantic layer, together with the persisted full technical validation scope.
# The runtime refuses any graph whose served bytes do not match it — the record
# is promotion-owned bookkeeping, never a submitted or agent-editable label.
ADMISSION_NAME = "admission.json"
# Checks a multi-fact graph admission requires to have PASSED (a compile-only
# or otherwise partial report is visibly partial, never a full pass — the
# promoter refuses it before any served write; conformance stays a disclosed
# not-run, not a failure).
_ADMISSION_REQUIRED_CHECKS = (
    "structural",
    "compile",
    "bind",
    "grain",
    "relationship_audit",
)


def _admission_files(served_root: Path) -> list[tuple[str, Path, bytes]]:
    """The served admission-scope corpus (one walker with the runtime's
    digest, validate.served_tree_files)."""
    return served_tree_files(served_root / "semantic_layer", served_root / _CONTEXT)


def _write_admission(served_root: Path, digest: str, state: dict, by: str, at: str) -> Path:
    """Record the local admission (issue #30): the exact reviewed digest the
    human promoted, the post-merge served-tree digest that binds it, the
    persisted technical validation scope, and the promotion identity — written
    atomically inside the bundle lock, also on a no-op re-promotion (a deleted
    record is healed rather than silently refusing every graph query). The
    per-file digests give the NEXT admission refresh the provenance to verify
    merge survivors against (mf-t5 fix F2)."""
    target = served_root / "semantic_layer" / ADMISSION_NAME
    files = _admission_files(served_root)
    record = {
        "route": "local-promotion",
        "reviewed_digest": digest,
        "served_digest": _digest_files(files),
        "files": {rel: hashlib.sha256(data).hexdigest() for rel, _path, data in files},
        "revision": state.get("revision"),
        "validation": state.get("validation"),
        "promoted": {"by": by, "at": at, "digest": digest},
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, sort_keys=True)
    os.replace(tmp, target)
    return target


def _refuse_unadmitted_survivors(staging: Path, served_root: Path) -> None:
    """mf-t5 fix F2: admission certifies only reviewed bytes. Every served
    admission-scope file that SURVIVES this merge — present under served/,
    absent from the reviewed proposal — must hash to what the current
    admission record certified (unchanged admitted provenance). A hand-added
    or hand-edited survivor (e.g. a model dropped straight into served
    semantic_layer/models/) refuses BEFORE any served write: the refreshed
    digest would otherwise govern unreviewed content under the original
    validation report (spec rev 1 admission / AC6). Files the proposal stages
    are exempt — the merge serves their reviewed bytes."""
    served = {
        rel: hashlib.sha256(data).hexdigest() for rel, _path, data in _admission_files(served_root)
    }
    if not served:
        return
    staged = {
        rel
        for rel, _path, _data in served_tree_files(staging / "semantic_layer", staging / _CONTEXT)
    }
    record_path = served_root / "semantic_layer" / ADMISSION_NAME
    admitted: dict[str, str] = {}
    if record_path.is_file():
        try:
            admitted = dict(
                (json.loads(record_path.read_text(encoding="utf-8")) or {}).get("files") or {}
            )
        except (OSError, ValueError):
            admitted = {}  # an unreadable record proves no provenance: fail closed
    refused = sorted(
        rel for rel, sha in served.items() if rel not in staged and admitted.get(rel) != sha
    )
    if refused:
        raise ValueError(
            "served admission-scope files are neither in the reviewed proposal nor "
            "unchanged from the recorded admission: "
            + ", ".join(refused)
            + " — a merge survivor with unreviewed provenance never rides an "
            "admission refresh; resubmit the bundle including it (or remove the "
            "file by hand), re-review, and promote that digest; nothing was served"
        )


# Suffixes the spec §7 review_needed marker can live on: OKF page frontmatter
# (markdown) and OSI models (YAML, where the author's marker survives only as a
# ``# status: review_needed`` comment — the schema rejects unknown keys).
_REVIEW_SUFFIXES = {".md", ".yml", ".yaml"}


def _review_needed(staging: Path) -> list[str]:
    """Staging-relative paths of files carrying the spec §7 review_needed marker,
    scanned across the governed staged layers ONLY — ``context_layer/`` and
    ``semantic_layer/`` markdown frontmatter and semantic-layer YAML. Any hit
    refuses the promotion: nothing from the tree is merged. ``staging/
    answer_examples/`` is deliberately outside the scan (ADR-0015, issue #20):
    staged answer examples have their own operator review path and can neither
    block nor slip into unrelated Context Layer/OSI promotion."""
    return [
        p.relative_to(staging).as_posix()
        for layer in (_CONTEXT, "semantic_layer")
        for p in sorted((staging / layer).rglob("*"))
        if p.is_file()
        and p.suffix in _REVIEW_SUFFIXES
        and "review_needed" in p.read_text(encoding="utf-8", errors="replace")
    ]


def _plan(staging: Path, served_root: Path) -> tuple[list[Change], list[Change]]:
    """Compute the promotion plan without writing: (page changes, raw changes).
    Unchanged content plans nothing (idempotency)."""
    by_page, by_raw = [], []
    for src in _staged_pages(staging):
        dst = served_root / _CONTEXT / src.relative_to(staging / _CONTEXT)
        staged_text = src.read_text(encoding="utf-8")
        if dst.is_file() and _content_key(dst.read_text(encoding="utf-8")) == _content_key(
            staged_text
        ):
            continue  # unchanged page: re-promotion is a no-op
        action = "updated" if dst.is_file() else "created"
        by_page.append(Change(src.relative_to(staging).as_posix(), action))
    for src in _staged_files(staging):
        dst = served_root / src.relative_to(staging)
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            continue
        action = "updated" if dst.is_file() else "created"
        by_raw.append(Change(src.relative_to(staging).as_posix(), action))
    return by_page, by_raw


def _apply(staging: Path, served_root: Path, by: str, at: str) -> list[Change]:
    """Execute the plan: merge pages (bookkeeping) + raw files, regenerate all
    index.md files, append log.md entries."""
    served_root = served_root.resolve()

    def contained(dst: Path) -> Path:
        resolved = dst.resolve()
        if not resolved.is_relative_to(served_root):  # same guard as author._safe_path
            raise ValueError(f"promotion target escapes the served root: {dst}")
        return resolved

    applied: list[Change] = []
    page_changes: list[Change] = []
    for src in _staged_pages(staging):
        dst = contained(served_root / _CONTEXT / src.relative_to(staging / _CONTEXT))
        staged_text = src.read_text(encoding="utf-8")
        if dst.is_file() and _content_key(dst.read_text(encoding="utf-8")) == _content_key(
            staged_text
        ):
            continue
        action = "updated" if dst.is_file() else "created"
        prior = []
        if dst.is_file():
            prior = (_load(dst.read_text(encoding="utf-8"))[0] or {}).get("verified") or []
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            _promoted_text(staged_text, by, at, prior_verified=list(prior)), encoding="utf-8"
        )
        change = Change(dst.relative_to(served_root).as_posix(), action)
        applied.append(change)
        page_changes.append(change)
    for src in _staged_files(staging):
        dst = contained(served_root / src.relative_to(staging))
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            continue
        action = "updated" if dst.is_file() else "created"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        applied.append(Change(dst.relative_to(served_root).as_posix(), action))
    _regenerate_indexes(served_root / _CONTEXT)
    _append_log(served_root / _CONTEXT, page_changes, by, at[:10])  # ISO date heading
    return applied


def promote(
    staging_dir: str | Path,
    served_root: str | Path,
    by: str | None = None,
    *,
    assume_yes: bool = False,
    at: str | None = None,
) -> list[Change]:
    """The promotion gate. Returns the applied changes (empty = nothing to do).
    ``at`` pins the verification timestamp (tests); default: now."""
    staging, served_root = Path(staging_dir), Path(served_root)
    by = by or f"human:{getuser()}"
    now = datetime.now(UTC) if at is None else datetime.fromisoformat(at)
    refused = _review_needed(staging)
    if refused:  # spec §6/§7: review_needed artifacts are not promotable
        print(
            "error: staged files carry status: review_needed — human review required:",
            file=sys.stderr,
        )
        for rel in refused:
            print(f"  {rel}", file=sys.stderr)
        raise SystemExit(1)
    page_plan, raw_plan = _plan(staging, served_root)
    if not page_plan and not raw_plan:
        print("nothing to promote: served layers already match staging/")
        return []
    if not assume_yes:
        print("promotion plan (staging/ -> served, merge-only):")
        for change in [*page_plan, *raw_plan]:
            print(f"  {change.action}: {change.rel}")
        answer = input(f"promote {len(page_plan) + len(raw_plan)} file(s) as {by}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted: nothing served")
            raise SystemExit(1)
    applied = _apply(staging, served_root, by, now.isoformat(timespec="seconds"))
    print(f"promoted {len(applied)} file(s); indexes regenerated; log.md updated")
    return applied


def promote_bundle(
    digest: str,
    *,
    staging_root: str | Path,
    served_root: str | Path,
    by: str | None = None,
    assume_yes: bool = False,
    at: str | None = None,
) -> list[Change]:
    """HUMAN-ONLY exact-digest Promotion of the active harness-led bundle
    proposal (spec 2026-09-24-0005, ADR-0003/0013): serves ONLY the exact
    content a human reviewed, and only together — the reviewed Seed Notes plus
    OSI/OKF through the ordinary merge-only bookkeeping above. Refused before
    ANY served write for a missing/changed/incomplete/``review_needed``
    proposal, a digest that is not the exact reviewed content, or an approved
    source registry that changed after the review. No agent-facing tool wraps
    this; the caller names the project's staging and served roots explicitly."""
    staging_root = Path(staging_root)
    served_root = Path(served_root)
    by = by or f"human:{getuser()}"
    now = datetime.now(UTC) if at is None else datetime.fromisoformat(at)
    state_path = bundle_state_path(staging_root)
    bundle = bundle_staging_dir(staging_root)
    # The SAME per-project interprocess lock submit/review use: the digest
    # checks, the served writes, and the state update are one critical section,
    # so a writer submitting mid-Promotion can never split the reviewed digest
    # from the bytes served — it serializes behind the gate and then fails as
    # a stale/promoted writer.
    with bundle_lock(staging_root):
        if not state_path.is_file():
            raise ValueError(
                f"no active bundle proposal state at {state_path} — ariadne-authoring "
                "submit stages one first"
            )
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(
                f"{state_path}: malformed bundle proposal state ({exc}) — human resolution"
            ) from None
        if not isinstance(state, dict) or not state.get("submission_digest"):
            raise ValueError(f"{state_path}: malformed bundle proposal state — human resolution")
        # The owner's fail-closed crash-recovery decision (issue #15): a
        # retained bundle.discarded marks an interrupted transition. Promotion
        # refuses it for the human BEFORE any served write and never modifies
        # or removes either copy.
        discarded = bundle.parent / BUNDLE_DISCARD_NAME
        if discarded.exists() or discarded.is_symlink():
            raise ValueError(
                f"{discarded}: a retained prior-proposal copy marks an interrupted "
                "transition — human resolution required: keep both copies plus "
                f"{state_path}, compare them, copy out anything to keep, and remove the "
                "leftover by hand; nothing was served and no agent command deletes them"
            )
        if digest != state.get("digest"):
            raise ValueError(
                f"digest mismatch: exact-content promotion — the active proposal's "
                f"reviewed digest is {state.get('digest')}, not {digest}; review the "
                "current proposal (ariadne-authoring review) and promote that digest"
            )
        if state.get("status") != "validated" and state.get("status") != "promoted":
            raise ValueError(
                f"the active bundle proposal is '{state.get('status')}' — only a "
                "proposal that passed every deterministic check is promotable"
            )
        if not bundle.is_dir():
            raise ValueError(
                f"the bundle proposal state exists but its staging is gone ({bundle}) — "
                "human resolution"
            )
        # The digest binds the exact staged content: any hand-edited (or otherwise
        # changed) staging tree refuses promotion before a single served write.
        current = _tree_digest(bundle)
        if current != digest:
            raise ValueError(
                "staged content changed after the review (digest "
                f"{current} != reviewed {digest}) — re-review; nothing was served"
            )
        # The approved source identity must still be what the proposal was checked
        # against (spec: a source change while a proposal is active invalidates it;
        # spec 0025 §5: storage profile declarations ride that identity).
        project = Path(str(state.get("project") or staging_root.parent))
        if _digest(_registry_identity_payload(project)) != state.get("sources_digest"):
            raise ValueError(
                "the approved source registry changed after this proposal was "
                "validated — re-validate (resubmit) before promoting; nothing was served"
            )
        refused = _review_needed(bundle)
        if refused:  # spec §6/§7: review_needed artifacts are not promotable
            raise ValueError(
                "staged files carry status: review_needed — human review required: "
                + ", ".join(refused)
            )
        # Issue #30: a multi-fact graph enters the served tree ONLY through this
        # exact-digest Promotion of a bundle that passed the FULL technical
        # validation — a missing, partial (compile-only), or failed-check scope
        # refuses before any served write; there is no free-form label to trust.
        # mf-t5 fix F1: ONLY this graph route issues multi-fact admission — an
        # ordinary legacy (graph-less) Promotion serves its bytes through the
        # ordinary gate but never writes an admission record, so a legacy or
        # pre-upgrade bundle can never serve query_metrics as governed; and
        # the issuing route itself enforces the complete-report AND per-metric
        # citation requirements (independent of what the submission gate
        # happened to check when the proposal was authored).
        graph_staged = (bundle / "semantic_layer" / "graph.yml").is_file()
        validation = state.get("validation")
        if graph_staged:
            outcomes = {
                check.get("name"): check.get("outcome")
                for check in (validation or {}).get("checks") or []
            }
            partial = [
                name for name in _ADMISSION_REQUIRED_CHECKS if outcomes.get(name) != "passed"
            ]
            if not isinstance(validation, dict) or not validation.get("scope") or partial:
                raise ValueError(
                    "the reviewed multi-fact graph proposal carries no complete "
                    "technical validation scope ("
                    + (
                        "no persisted validation state"
                        if not isinstance(validation, dict)
                        else f"scope {validation.get('scope')!r}, "
                        f"checks not passed: {', '.join(partial) or 'absent'}"
                    )
                    + ") — a compile-only or partial report never admits a graph; "
                    "resubmit the bundle so the full validation is recorded, then "
                    "promote that digest"
                )
            citations = _graph_citation_errors(bundle)
            if citations:
                raise ValueError(
                    "the reviewed multi-fact graph proposal breaks the cited-context "
                    "admission requirement: "
                    + "; ".join(citations)
                    + " — re-review a proposal whose metric pages cite resolvable "
                    "policies/ pages; nothing was served"
                )
            # mf-t5 fix F2: no admission refresh while an unreviewed merge
            # survivor sits in the served admission scope — BEFORE any write.
            _refuse_unadmitted_survivors(bundle, served_root)
        notes_src = bundle / "data" / "seed_notes.md"
        if not notes_src.is_file():
            raise ValueError(
                "the reviewed proposal is incomplete: no data/seed_notes.md staged — "
                "resubmit the complete bundle"
            )
        notes_dst = served_root / "data" / "seed_notes.md"
        notes_change = None
        if not (notes_dst.is_file() and notes_dst.read_bytes() == notes_src.read_bytes()):
            notes_change = Change(
                "data/seed_notes.md", "updated" if notes_dst.is_file() else "created"
            )
        page_plan, raw_plan = _plan(bundle, served_root)
        if not page_plan and not raw_plan and notes_change is None:
            # Still (re)write the admission record: a no-op re-promotion heals a
            # missing/deleted record instead of leaving the served graph
            # unadmitted (issue #30) — but ONLY for the graph route (mf-t5 fix
            # F1: legacy Promotion never issues admission).
            if graph_staged:
                _write_admission(served_root, digest, state, by, now.isoformat(timespec="seconds"))
            print("nothing to promote: served layers already match the reviewed bundle/")
            return []
        if not assume_yes:
            print("promotion plan (reviewed bundle staging/ -> served, merge-only):")
            for change in [*page_plan, *raw_plan, *([notes_change] if notes_change else [])]:
                print(f"  {change.action}: {change.rel}")
            answer = input(
                f"promote {len(page_plan) + len(raw_plan) + bool(notes_change)} file(s) "
                f"as {by}? [y/N] "
            )
            if answer.strip().lower() not in ("y", "yes"):
                print("aborted: nothing served")
                raise SystemExit(1)
        applied = _apply(bundle, served_root, by, now.isoformat(timespec="seconds"))
        if notes_change is not None:
            notes_dst.parent.mkdir(parents=True, exist_ok=True)
            notes_dst.write_bytes(notes_src.read_bytes())
            applied.append(notes_change)
        # Issue #30: the served bytes now differ from the reviewed staged bytes by
        # the promotion bookkeeping — record the local admission binding the
        # staged review digest to the POST-merge served digest (the runtime
        # refuses any later served-tree change against it). Graph route only
        # (mf-t5 fix F1: legacy Promotion never issues admission).
        if graph_staged:
            _write_admission(served_root, digest, state, by, now.isoformat(timespec="seconds"))
        # The proposal is served: record it so the active slot's history is honest.
        state["status"] = "promoted"
        state["promoted"] = {"by": by, "at": now.isoformat(timespec="seconds"), "digest": digest}
        fd, tmp = tempfile.mkstemp(dir=state_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, sort_keys=True)
        os.replace(tmp, state_path)
    print(
        f"promoted {len(applied)} file(s) under reviewed digest {digest}; indexes "
        "regenerated; log.md updated"
    )
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python ariadne-promote",
        description="Promote staged layers into the served roots (merge-only, "
        "verified append, index + log bookkeeping).",
    )
    parser.add_argument("--yes", action="store_true", help="promote without prompting")
    parser.add_argument(
        "--staging", default="staging", help="staging directory (default: ./staging)"
    )
    parser.add_argument(
        "--served",
        default=None,
        help="served root (holds context_layer/); default: the project root (.) in a "
        "fresh project (no ./context_layer yet), else this checkout's root",
    )
    parser.add_argument("--by", default=None, help="verifier identity (default: human:<$USER>)")
    parser.add_argument(
        "--digest",
        default=None,
        help="HUMAN-ONLY exact-digest promotion of the harness-led bundle proposal "
        "under <staging>/authoring/: serves ONLY the exact reviewed content "
        "(Seed Notes + OSI + OKF together); refuses changed, incomplete, or "
        "review_needed proposals before any served write",
    )
    args = parser.parse_args(argv)
    if args.digest is not None:
        if args.served is None:  # spec: the human names the served root explicitly
            print(
                "error: --digest promotion requires an explicit --served root (the "
                "human names the project's staging and served roots)",
                file=sys.stderr,
            )
            return 1
        try:
            promote_bundle(
                args.digest,
                staging_root=args.staging,
                served_root=args.served,
                by=args.by,
                assume_yes=args.yes,
            )
        except (ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    # Rev 10 (spec §8.21): a fresh project has no ./context_layer yet — the served
    # root defaults to the project root, so the first promotion creates
    # context_layer/ + semantic_layer/ THERE instead of the misleading "nothing to
    # promote" against a package-relative guess. Explicit --served always wins.
    served = args.served
    if served is None:
        served = "." if not (Path(".") / _CONTEXT).is_dir() else str(_REPO_ROOT)
    promote(args.staging, served, by=args.by, assume_yes=args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
