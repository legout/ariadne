"""Operator-only review of staged answer examples (issue #20).

ADR-0015 / spec 2026-09-29-0007 revision 1, §"Review, staleness and failures":
promotion of an Answer Example is ONE exact, deliberate human decision — a
separate local command (``ariadne-example-review ID --file PATH``), never an
agent-facing runtime operation, MCP tool, or ``ariadne-promote`` batch merge.

The decision file binds the human to one exact staged record: it names the
same ID as the invocation, carries a self-declared maintainer actor, an
explicit outcome (approve / reject / request-revision), the technical and
provenance review, and the sha256 of the staged record bytes it reviews.

- **approve** requires the staged record's own submitter business-meaning
  attestation and every currently cited served metric/Policy to match its
  recorded digest; it moves exactly that record into the selected root's
  ``answer_examples/`` store as ``status: stable`` with the
  maintainer actor/time/outcome retained, and never promotes a metric or
  Policy. A fresh run never counts as verifying the historical numeric value,
  so a decision claiming that is refused. Issue #40 splits the two roots a
  managed project needs: citations validate against the PINNED admitted
  snapshot while the stable record publishes under the LOGICAL project root
  (its example store, where managed search looks); a ``--served`` pointing
  inside ``.ariadne/`` operator state is refused outright — never a review or
  publication root. A legacy root (no admission) keeps its one shared root
  exactly as before.
- **reject / request-revision** write the outcome back to the staged record as
  audit history and never serve anything; the maintainer cannot substitute
  their own business-meaning claim for the submitter's missing one.

Every refusal fails closed before the first served write. The served record is
written complete in one atomic write (mkstemp + fsync + os.replace, the
existing file-backed pattern) — a partial failure can never leave a stable
example without its review evidence. A revision is a NEW staged submission and
review (optionally declaring ``supersedes``), which closes the old served
record while preserving its bytes and digests: the old digest is never flipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import (
    UTC,  # pyright: ignore[reportAttributeAccessIssue] — resolver drift: UTC is py3.11+
    datetime,
)
from pathlib import Path
from typing import Any

import yaml

from ariadne import admission
from ariadne.answer_examples import (
    _FRONTMATTER_RE,
    _OPERATION_ARGUMENTS,
    EXAMPLES_DIR,
    MAX_EXCERPT_BYTES,
    MAX_RECORD_BYTES,
    OPERATIONS,
    _guard_staging,
    _is_stale,
    _resolve_citation,
    _sha256_hex,
    _write_index,
    validated_sql_provenance,
)
from ariadne.authoring import _fsync_path
from ariadne.cli import _resolve_served_root
from ariadne.proposals import ARIADNE_STATE_DIR

OUTCOMES = ("approve", "reject", "request-revision")
# A staged/example ID is one safe path component — never a directory walk,
# bookkeeping page, or hidden file.
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# A recorded sha256 digest (result or cited dependency) is lowercase hex.
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
# The bounded historical answer evidence a staged page records in its body
# (save writes: "Captured answer excerpt (<time>; full structured-result
# digest `<sha256>`):" before the fenced excerpt block).
_ANSWER_EVIDENCE_RE = re.compile(
    r"Captured answer excerpt \((.+?); full structured-result digest `([0-9a-f]{64})`\):"
)
# A decision must not overstate the review (spec): reproducing a current query
# cannot verify the historical numeric value captured in the record.
_NUMERIC_CLAIMS = ("historical_value_verified", "value_verified", "numerically_verified")


def _require(decision: dict, key: str) -> str:
    value = decision.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"incomplete reviewer evidence: the decision needs a non-empty {key!r}")
    return value


def _bounded_page(meta: dict, body: str) -> bytes:
    """Encode a reviewed page inside the spec's whole-record bound: review
    evidence is the only field that grows a record after the bounded save, so
    the final encoded bytes are checked before any write — an oversize record
    is refused, never truncated."""
    page = _page_bytes(meta, body)
    if len(page) > MAX_RECORD_BYTES:
        raise ValueError(
            f"the reviewed record would be {len(page)} bytes, over the "
            f"{MAX_RECORD_BYTES}-byte bound — shorten the technical review"
        )
    return page


def _validated_decision(example_id: str, decision: Any) -> dict:
    """One complete maintainer decision bound to this exact invocation."""
    if not isinstance(decision, dict):
        raise ValueError("the decision file must contain one JSON object")
    if decision.get("id") != example_id:
        raise ValueError(
            f"conflicting reviewed targets: the invocation reviews {example_id!r} but the "
            f"decision names {decision.get('id')!r}"
        )
    outcome = _require(decision, "outcome")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}: {outcome!r}")
    validated = {
        "id": example_id,
        "actor": _require(decision, "actor"),
        "outcome": outcome,
        "technical_review": _require(decision, "technical_review"),
        "staged_digest": _require(decision, "staged_digest"),
    }
    for claim in _NUMERIC_CLAIMS:
        if decision.get(claim):
            raise ValueError(
                f"a review cannot record {claim!r}: a fresh run or a digest never "
                "independently verifies the historical numeric value — approve the "
                "method and provenance, not the captured number"
            )
    supersedes = decision.get("supersedes")
    if supersedes is not None:
        if outcome != "approve":
            raise ValueError("'supersedes' belongs to an approval decision only")
        if not isinstance(supersedes, str) or not _ID_RE.fullmatch(supersedes):
            raise ValueError(f"'supersedes' must be a served example ID: {supersedes!r}")
        validated["supersedes"] = supersedes
    return validated


def _staged_page(example_id: str, staging_dir: Path) -> Path:
    """Resolve ONE exact staged record: a safe ID naming an existing OKF
    answer-example page inside the staging example root."""
    if not _ID_RE.fullmatch(example_id) or example_id in ("index", "log"):
        raise ValueError(f"invalid answer-example ID: {example_id!r}")
    examples = staging_dir / EXAMPLES_DIR
    page = examples / f"{example_id}.md"
    resolved = page.resolve()
    if not resolved.is_relative_to(examples.resolve()):
        raise ValueError(f"answer-example ID escapes the staging example root: {example_id!r}")
    if not resolved.is_file():
        raise ValueError(
            f"no staged answer example with ID {example_id!r} under {examples} — "
            "search-examples lists the staged IDs"
        )
    return resolved


def _split_page(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("the staged record has no OKF frontmatter")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"the staged record frontmatter is invalid: {exc}") from None
    if not isinstance(meta, dict) or meta.get("type") != "answer_example":
        raise ValueError("the staged record is not a typed answer-example page")
    return meta, match.group(2)


def _page_bytes(meta: dict, body: str) -> bytes:
    return (f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---\n{body}").encode()


def _atomic_write(path: Path, payload: bytes) -> None:
    """One complete file: tmp + fsync + rename + dir fsync (issue #15 pattern)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_path(path.parent)


def _log_review(directory: Path, entry: str, at: str) -> None:
    """Append one **Review** entry under the ISO-date heading of the example
    root's log.md (newest-first, the bundle bookkeeping shape)."""
    log = directory / "log.md"
    if log.is_file():
        lines = log.read_text(encoding="utf-8").rstrip("\n").split("\n")
    else:
        lines = ["# Directory Update Log"]
    heading = f"## {at[:10]}"
    if heading in lines:
        pos = lines.index(heading) + 1
        while pos < len(lines) and lines[pos].startswith("**"):
            pos += 1
    else:
        pos = 1 if lines and lines[0].startswith("# ") else 0
        lines[pos:pos] = ["", heading]
        pos += 2
    lines[pos:pos] = [entry]
    _atomic_write(log, ("\n".join(lines) + "\n").encode("utf-8"))


def _served_dir(served_root: Path) -> Path:
    """The served example root: never a symlink, never outside the served root
    (the mirror of the staging-side containment guard)."""
    directory = served_root / EXAMPLES_DIR
    if directory.is_symlink():
        raise ValueError(f"served example directory itself is a symlink — refusing: {directory}")
    resolved = directory.resolve()
    if not resolved.is_relative_to(served_root.resolve()):
        raise ValueError(f"served example directory escapes the served root: {resolved}")
    for name in ("index.md", "log.md"):
        if (directory / name).is_symlink():
            raise ValueError(f"served bundle file {name!r} is a symlink — refusing to write")
    return resolved


def _refuse_operator_state_root(served_root: Path) -> None:
    """Issue #40 finding 2: the review/publication root is never Ariadne's
    operator state. ``.ariadne/`` holds the immutable admitted snapshots,
    proposal worktrees and admission records — a ``--served`` pointing inside
    it would validate citations against a frozen copy while publishing stable
    examples into state managed search never reads (and mutating "immutable"
    snapshot bytes). Fail closed with the actionable alternative: the logical
    project root."""
    resolved = served_root.resolve()
    state = ARIADNE_STATE_DIR.name
    if state not in resolved.parts:
        return
    project = Path(*resolved.parts[: resolved.parts.index(state)])
    raise ValueError(
        f"--served {served_root} points inside {state}/ operator state (pinned "
        "admitted snapshots, proposal worktrees and admission records are never a "
        f"review or publication root) — pass the logical project root instead: "
        f"--served {project}"
    )


def _review_roots(served_root: Path) -> tuple[Path, Path | None]:
    """Split the review's two roots (issue #40 finding 2): a MANAGED project
    — one carrying a current admission — validates citations against its
    pinned admitted snapshot while publishing under the LOGICAL project root's
    example store (where managed search looks), mirroring save. A root without
    an admission record is the legacy shared root and keeps its single-root
    behavior exactly; an INVALID admission is never a legacy fallback — its
    resolution refusal propagates for human resolution."""
    if admission.load_current(served_root) is None:
        return served_root, None
    _record, snapshot = admission.resolve_admission(served_root)
    return snapshot, served_root


def _validate_staged_record(meta: dict, body: str, served_root: Path) -> None:
    """The stored record shape approval requires (spec §"Location, format and
    identity"): question, interpretation, a supported operation with its real
    structured arguments, the bounded historical answer evidence with its
    result digest in the page body, and the recorded dependency list. The
    decision digest binds the reviewed BYTES, not their completeness: a locally
    edited staged page that keeps type and attestation but drops the
    method/answer and tears out the dependency list fails closed (boundary
    review finding 3) — a methodless record must never become a served
    reference. Every recorded citation is validated by its RESOLVED location
    through the save-side citation rule (delta recheck finding 3): a
    metric-looking lexical prefix reaching a served answer-example page through
    ``..`` is a malformed record, not metric evidence. Shape checks over the
    save-side constants; no parallel schema."""
    if meta.get("status") != "draft":
        raise ValueError(
            "the staged record must be a current draft, not "
            f"{meta.get('status')!r} — review admits one exact staged submission"
        )
    for key in ("question", "interpretation"):
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"the staged record needs a non-empty string {key!r}")
    method = meta.get("method")
    operation = method.get("operation") if isinstance(method, dict) else None
    arguments = method.get("arguments") if isinstance(method, dict) else None
    if operation not in OPERATIONS or not isinstance(arguments, dict) or not arguments:
        raise ValueError(
            "the staged record must record operation 'get_metric' or 'define_metric' "
            "with its structured 'arguments' (never standalone SQL)"
        )
    missing = [
        key
        for key in _OPERATION_ARGUMENTS[operation]
        if not isinstance(arguments.get(key), str) or not arguments[key].strip()
    ]
    if missing:
        raise ValueError(
            f"the staged record's {operation!r} method is missing its structured "
            f"arguments (missing or non-string: {', '.join(missing)})"
        )
    # spec 0023 §4: a PRESENT sql_provenance must be the exact result-derived
    # mapping (fixed source, non-whitespace text) before any stable write — a
    # malformed one refuses approval; an ABSENT one is a valid legacy record,
    # never a review failure. The exact text is retained unchanged below (the
    # digest already binds the reviewed bytes, SQL included); nothing is
    # executed, backfilled or rewritten.
    validated_sql_provenance(meta, "the staged record")
    evidence = _ANSWER_EVIDENCE_RE.search(body)
    if evidence is None:
        raise ValueError(
            "the staged record must keep its bounded historical answer evidence "
            "(captured excerpt and full structured-result digest) in the page body"
        )
    excerpt = re.search(r"````json\n(.*?)\n````", body, re.DOTALL)
    if excerpt is None:
        raise ValueError("the staged record's answer excerpt block is missing")
    if len(excerpt.group(1).encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise ValueError(
            f"the staged record's answer excerpt is over the {MAX_EXCERPT_BYTES}-byte "
            "bound — submit a fresh bounded revision"
        )
    sources = meta.get("sources")
    if not isinstance(sources, list):
        raise ValueError(
            "'sources' must be the recorded list of served metric/Policy digests "
            "(an empty list records no dependency)"
        )
    for entry in sources:
        path = entry.get("path") if isinstance(entry, dict) else None
        sha256 = entry.get("sha256") if isinstance(entry, dict) else None
        if (
            not isinstance(path, str)
            or not path.strip()
            or not path.endswith(".md")
            or not isinstance(sha256, str)
            or not _SHA256_RE.fullmatch(sha256)
        ):
            raise ValueError(
                "each recorded citation must be a served metric/Policy page "
                "(context_layer/metrics|policies/*.md) with its sha256 digest"
            )
        # The resolved location, never the lexical prefix, decides the page
        # kind (delta recheck finding 3): reuse the save-side rule, which
        # already checks canonical resolved kind, containment and existence.
        if _resolve_citation(path, served_root)["sha256"] != sha256:
            raise ValueError(
                f"recorded citation {path!r} no longer matches the current served "
                "metric/Policy bytes — submit and review a fresh revision"
            )


def _approve(
    decision: dict,
    meta: dict,
    body: str,
    page: Path,
    staged_dir: Path,
    publish_root: Path,
    citation_root: Path,
    at: str,
) -> dict:
    # Approval needs the submitter's own business-meaning attestation: the
    # maintainer reviews method and provenance and cannot supply it instead.
    submitter = meta.get("submitter")
    if not isinstance(submitter, dict) or not str(submitter.get("attestation") or "").strip():
        raise ValueError(
            "approval requires the submitter's business-meaning attestation — the "
            "maintainer cannot substitute their own; submit an attested revision"
        )
    _validate_staged_record(meta, body, citation_root)
    if _is_stale(meta, citation_root):
        raise ValueError(
            "a cited served metric/Policy is missing, unreadable or changed since the "
            "record was captured — submit and review a fresh revision instead"
        )
    directory = _served_dir(publish_root)
    served_page = directory / f"{decision['id']}.md"
    if served_page.exists() or served_page.is_symlink():
        raise ValueError(f"a served example with ID {decision['id']!r} already exists")
    supersession = None
    if "supersedes" in decision:
        if decision["supersedes"] == decision["id"]:
            raise ValueError("an example cannot supersede itself")
        candidate = directory / f"{decision['supersedes']}.md"
        if not candidate.is_file():
            raise ValueError(f"'supersedes' names no served example: {decision['supersedes']!r}")
        # The predecessor is fully parsed and validated BEFORE the first served
        # write (boundary review findings 1 and 4): invalid frontmatter or a
        # nonstable (e.g. already-superseded) target fails closed with the
        # original served and staged bytes unchanged and no new stable record.
        predecessor = _split_page(candidate.read_text(encoding="utf-8"))
        if predecessor[0].get("status") != "stable":
            raise ValueError(
                "'supersedes' must name a current stable served example, but "
                f"{decision['supersedes']!r} has status {predecessor[0].get('status')!r} "
                "— the first successor link stands; supersede that instead"
            )
        supersession = (candidate, *predecessor)

    review = {
        "actor": decision["actor"],
        "at": at,
        "outcome": "approve",
        "technical_review": decision["technical_review"],
    }
    if supersession is not None:
        review["supersedes"] = decision["supersedes"]
    stable = dict(meta)
    stable["status"] = "stable"
    stable["review"] = review
    _atomic_write(served_page, _bounded_page(stable, body))
    if supersession is not None:
        # A revision closes its predecessor without erasing it: only the status
        # flips — the old question, answer, attestation and dependency digests
        # stay byte-for-byte history (a stale old digest is never flipped).
        old_page, old_meta, old_body = supersession  # parsed before any write above
        old_meta["status"] = "superseded"
        old_meta["superseded_by"] = decision["id"]
        _atomic_write(old_page, _page_bytes(old_meta, old_body))
    _write_index(directory, staged=False)
    _log_review(
        directory,
        f"**Review**: {EXAMPLES_DIR}/{decision['id']}.md — approved by {decision['actor']}"
        + (f" (supersedes {decision['supersedes']})" if supersession is not None else ""),
        at,
    )
    # The exact staged record is consumed: served-first, then the staged copy
    # and its bookkeeping — a failure in between leaves a served record that
    # already carries its full review evidence.
    page.unlink()
    _write_index(staged_dir, staged=True)
    _log_review(
        staged_dir,
        f"**Review**: {EXAMPLES_DIR}/{decision['id']}.md — approved by {decision['actor']}; "
        "moved to the served example store",
        at,
    )
    return {
        "id": decision["id"],
        "outcome": "approve",
        "status": "stable",
        "path": str(served_page),
    }


def review_example(
    example_id: str,
    decision: Any,
    served_root: str | Path,
    staging_dir: str | Path,
    *,
    at: str | None = None,
) -> dict:
    """Apply one maintainer decision to ONE exact staged answer example (spec
    2026-09-29-0007 §"Review, staleness and failures"). ``at`` pins the review
    timestamp (tests); default: now."""
    # The exact staged record resolves first: an invalid, missing or escaped ID
    # fails closed as an ID problem, then the decision binds to that exact ID.
    served_root = Path(served_root)
    # Issue #40 finding 2: never review or publish against .ariadne/ operator
    # state, and split a managed project's citation root (the pinned admitted
    # snapshot) from its publication root (the logical project root's example
    # store) — a legacy root keeps one shared root exactly.
    _refuse_operator_state_root(served_root)
    citation_root, examples_root = _review_roots(served_root)
    # The same stage-vs-served boundary as save (ADR-0015, boundary review
    # finding 2) at the one operator-command choke point: a symlinked or
    # served-overlapping staging example root is refused before either review
    # outcome can access or mutate the staged page.
    _guard_staging(Path(staging_dir) / EXAMPLES_DIR, citation_root, examples_root)
    staged_dir = (Path(staging_dir) / EXAMPLES_DIR).resolve()
    page = _staged_page(example_id, Path(staging_dir))
    validated = _validated_decision(example_id, decision)
    raw = page.read_bytes()
    if _sha256_hex(raw) != validated["staged_digest"]:
        raise ValueError(
            "the staged record changed after the decision was taken (sha256 "
            f"{_sha256_hex(raw)} != reviewed {validated['staged_digest']}) — re-review"
        )
    meta, body = _split_page(raw.decode("utf-8"))
    prior = meta.get("review")
    if isinstance(prior, dict) and prior.get("outcome"):
        raise ValueError(
            f"the staged record already carries a review outcome {prior.get('outcome')!r} — "
            "a revision is a new submission and a new review"
        )
    now = at if at is not None else datetime.now(UTC).isoformat(timespec="seconds")
    if validated["outcome"] == "approve":
        return _approve(validated, meta, body, page, staged_dir, served_root, citation_root, now)
    # reject / request-revision: audit history on the staged record, nothing served.
    meta["review"] = {
        "actor": validated["actor"],
        "at": now,
        "outcome": validated["outcome"],
        "technical_review": validated["technical_review"],
    }
    _atomic_write(page, _bounded_page(meta, body))
    _write_index(staged_dir, staged=True)
    _log_review(
        staged_dir,
        f"**Review**: {EXAMPLES_DIR}/{example_id}.md — {validated['outcome']} by "
        f"{validated['actor']}",
        now,
    )
    return {
        "id": example_id,
        "outcome": validated["outcome"],
        "status": "rejected" if validated["outcome"] == "reject" else "revision_requested",
        "path": str(page),
    }


def main(argv: list[str] | None = None) -> int:
    """Operator-only console entry (``ariadne-example-review``). Same JSON wire
    contract as the ariadne CLI: one value on stdout, or one error object on
    stderr with a nonzero exit."""
    parser = argparse.ArgumentParser(
        prog="ariadne-example-review",
        description="Apply one maintainer review decision to an exact staged answer "
        "example (approve serves it as stable; reject/request-revision keep it as "
        "staged audit history).",
    )
    parser.add_argument(
        "id", help="the exact staged answer-example ID (search-examples lists them)"
    )
    parser.add_argument(
        "--file",
        required=True,
        help="JSON decision file: id, actor, outcome, technical_review, staged_digest "
        "(sha256 of the staged record bytes), optional supersedes",
    )
    parser.add_argument("--staging", default="staging", help="staging root (default: ./staging)")
    parser.add_argument(
        "--served",
        default=None,
        help="served artifact root (same resolution as the ariadne CLI; default: the "
        "working directory or ./served, unambiguously)",
    )
    args = parser.parse_args(argv)
    try:
        decision = json.loads(Path(args.file).read_text(encoding="utf-8"))
        result = review_example(args.id, decision, _resolve_served_root(args.served), args.staging)
    except Exception as exc:
        print(
            json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
