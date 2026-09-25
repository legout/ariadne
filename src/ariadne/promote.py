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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from getpass import getuser
from pathlib import Path

import yaml

from ariadne.author import _FRONTMATTER_RE
from ariadne.authoring import (
    BUNDLE_DISCARD_NAME,
    _digest,
    _registry_sources,
    _tree_digest,
    bundle_lock,
    bundle_staging_dir,
    bundle_state_path,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTEXT = "context_layer"

# Section heading for a folder's index.md (SPEC §8 example form: "# Metric").
_SECTION_TITLES = {
    "tables": "Table",
    "references": "Reference",
    "joins": "Join",
    "policies": "Policy",
    "metrics": "Metric",
    "computations": "Computation",
    "skills": "Skill",
}
# One-line blurb used when an index links a subdirectory (directories carry no
# frontmatter to take a description from).
_FOLDER_BLURBS = {
    "tables": "Physical tables: row meaning, schema, join hints.",
    "references": "Cross-table reference notes.",
    "joins": "Join catalog: keys, cardinality evidence, grain safety.",
    "policies": "Human-owned business rules the metrics cite.",
    "metrics": "Governed metrics and the rules that make them right.",
    "computations": "Sanctioned computations: SQL, runtime, attester.",
    "skills": "Operational guides: run, promote, query.",
}


@dataclass
class Change:
    """One promotion action applied (or planned) for a staged file."""

    rel: str  # path relative to the served layer root (context_layer/…)
    action: str  # "created" | "updated"


def _load(text: str) -> tuple[dict | None, str]:
    """Split a file into (frontmatter meta or None, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    return (yaml.safe_load(match.group(1)) or {}), match.group(2)


def _content_key(text: str) -> str:
    """Canonical form for change detection: everything EXCEPT verified/status.
    Equal keys mean the promotion bookkeeping would be byte-identical — no-op."""
    meta, body = _load(text)
    if meta is None:
        return body
    meta = {k: v for k, v in meta.items() if k not in ("verified", "status")}
    return yaml.safe_dump(meta, sort_keys=True) + body


def _promoted_text(text: str, by: str, at: str, prior_verified: list | None = None) -> str:
    """The served form of a staged OKF page: status flipped, verified appended.
    ``prior_verified`` (the served page's existing list) is preserved, so a
    re-promoted update APPENDS to the verification history."""
    meta, body = _load(text)
    if meta is None:  # callers route non-OKF files to the raw merge
        return text
    meta["status"] = "stable"
    verified = list(prior_verified or [])
    verified.append({"by": by, "at": at})
    meta["verified"] = verified
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n{body}"


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


# Suffixes the spec §7 review_needed marker can live on: OKF page frontmatter
# (markdown) and OSI models (YAML, where the author's marker survives only as a
# ``# status: review_needed`` comment — the schema rejects unknown keys).
_REVIEW_SUFFIXES = {".md", ".yml", ".yaml"}


def _review_needed(staging: Path) -> list[str]:
    """Staging-relative paths of files carrying the spec §7 review_needed marker,
    scanned across the WHOLE staging tree — context markdown frontmatter AND
    semantic-layer YAML. Any hit refuses the promotion: nothing from the tree is
    merged."""
    return [
        p.relative_to(staging).as_posix()
        for p in sorted(staging.rglob("*"))
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


def _index_for(directory: Path, served_context: Path) -> str:
    """One index.md body: subdirectory links, then page links with the target's
    frontmatter description (SPEC §8 progressive disclosure)."""
    if directory == served_context:
        heading = "Context Layer"
    else:
        heading = _SECTION_TITLES.get(directory.name, directory.name.capitalize())
    lines = [f"# {heading}", ""]
    for sub in sorted(p for p in directory.iterdir() if p.is_dir()):
        if not any(sub.rglob("*.md")):
            continue
        rel = sub.relative_to(served_context)
        blurb = _FOLDER_BLURBS.get(sub.name, "")
        lines.append(f"* [{sub.name.capitalize()}]({rel.as_posix()}/) - {blurb}".rstrip(" -"))
    for page in sorted(p for p in directory.glob("*.md") if p.name != "index.md"):
        meta, _ = _load(page.read_text(encoding="utf-8"))
        title = str((meta or {}).get("title") or page.stem.replace("_", " "))
        desc = str((meta or {}).get("description") or "")
        lines.append(f"* [{title}]({page.name}) - {desc}".rstrip(" -"))
    return "\n".join(lines).rstrip() + "\n"


def _has_pages(directory: Path) -> bool:
    """True when the directory or any descendant holds .md pages."""
    return any(directory.rglob("*.md"))


def _regenerate_indexes(served_context: Path) -> None:
    """Regenerate index.md at the bundle root and in every folder that holds
    pages (directly or below — the root links its section subdirs), from the
    CURRENT served contents, so merge-surviving pages are indexed too."""
    if not served_context.is_dir():
        return
    dirs = [served_context, *sorted(p for p in served_context.rglob("*") if p.is_dir())]
    for directory in dirs:
        if _has_pages(directory):
            text = _index_for(directory, served_context)
            (directory / "index.md").write_text(text, encoding="utf-8")


def _append_log(served_context: Path, changes: list[Change], by: str, date: str) -> None:
    """Append Creation/Update entries under today's heading (newest-first)."""
    if not changes:
        return
    path = served_context / "log.md"
    if path.is_file():
        lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    else:
        lines = ["# Directory Update Log"]
    heading = f"## {date}"
    entries = [
        f"**{'Update' if c.action == 'updated' else 'Creation'}**: {c.rel} — verified {by}"
        for c in changes
    ]
    if heading in lines:
        pos = lines.index(heading) + 1
        while pos < len(lines) and lines[pos].startswith("**"):
            pos += 1
    else:
        pos = 1 if lines and lines[0].startswith("# ") else 0
        lines[pos:pos] = ["", heading]
        pos += 2
    lines[pos:pos] = entries
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        state = json.loads(state_path.read_text(encoding="utf-8"))
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
        # against (spec: a source change while a proposal is active invalidates it).
        project = Path(str(state.get("project") or staging_root.parent))
        if _digest(_registry_sources(project)) != state.get("sources_digest"):
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
