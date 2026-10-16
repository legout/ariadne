"""Separate OKF store for explicitly submitted answer examples (issue #19).

ADR-0015 / spec 2026-09-29-0007 revision 1: an Answer Example is an explicitly
submitted OKF record of a question, its intended meaning, the Ariadne method
that answered it and a bounded historical answer — a labeled reference for
finding and checking a method, never a governed definition, a Policy or an
answer cache. This module is the transport-neutral core the runtime (and the
optional MCP adapter, issue #21) shares; the operator review command (issue
#20) is deliberately not here.

- ``save_example(submission, served_root, staging_dir)`` validates one explicit
  submission, derives a ≤8 KiB answer excerpt plus a digest of the full
  structured result, resolves every cited served metric/Policy path inside the
  selected served root (content digest recorded; missing or escaping citations
  are refused), and stages exactly one ``status: draft`` record under
  ``<staging>/answer_examples/`` with generated ``index.md``/``log.md``.
  Submissions never overwrite: a repeated intentional save stages a separately
  identified draft. Submitter identity and attestation are recorded as
  self-declared evidence — a submission may never claim the system-owned
  verified/reviewed state. Validation precedes every write: a failed or
  malformed submission stores nothing. Every successful save also derives
  ``sql_provenance: {source: submitted_result.sql, text: <exact result.sql>}``
  from the validated result envelope (spec 2026-10-13-0023): reserved against
  caller override, never normalized, inside the same encoded record bound.
- ``search_examples(...)`` re-reads the served and staging example roots on
  each request and returns ranked labeled hits (identity, staleness,
  question/interpretation, method summary, provenance, path). It never
  executes a query and never returns saved rows. With ``include_sql=True``
  each selected hit additionally carries the stored mapping as
  ``provenance.sql`` (``null`` for legacy records without it); SQL is never a
  search or ranking input. ``search_context`` and governed
  ``get_metric.context`` are untouched by construction: examples live
  outside ``context_layer/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import (
    UTC,  # pyright: ignore[reportAttributeAccessIssue] — resolver drift: UTC is py3.11+
    datetime,
)
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

EXAMPLES_DIR = "answer_examples"  # ADR-0015: the separate per-project OKF store
MAX_EXCERPT_BYTES = 8 * 1024  # spec: the timestamped answer excerpt bound
MAX_RECORD_BYTES = 64 * 1024  # spec: the whole encoded record bound
# spec 2026-10-13-0023 §2: the fixed provenance descriptor — the submitted
# result envelope's sql field, not a verified execution origin.
SQL_PROVENANCE_SOURCE = "submitted_result.sql"
# The only methods an example may record (spec: get_metric/define_metric
# structured arguments — never standalone executable SQL).
OPERATIONS = ("get_metric", "define_metric")
# The minimum structured arguments each recorded operation really takes, as
# the runtime public callers pass them (get_metric(name, ...),
# define_metric({name, description, source, expression, ...})) — standalone
# SQL is not a rerunnable argument of either (spec: recorded method).
_OPERATION_ARGUMENTS = {
    "get_metric": ("name",),
    "define_metric": ("name", "description", "source", "expression"),
}
# A citation is an existing served metric or Policy page (spec rev 1): only
# those two OKF page kinds may back an example dependency.
_CITATION_KINDS = ("context_layer/metrics/", "context_layer/policies/")
# Identity and review state are system-owned: a submission may not claim them
# (spec: local identity is self-declared, never authenticated; review evidence
# is written only by the operator review command, issue #20). sql_provenance
# is likewise system-derived from the validated result envelope — a caller
# may not supply its own (spec 0023 §2).
_RESERVED_FIELDS = frozenset(
    {"id", "status", "verified", "review", "stale", "superseded", "attested", "sql_provenance"}
)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")  # same token rule as search_context
_SLUG_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ANSWER_EVIDENCE_RE = re.compile(
    r"Captured answer excerpt \((.+?); full structured-result digest `([0-9a-f]{64})`\):"
)


def _canonical(payload: Any) -> str:
    """Deterministic JSON form for excerpts and digests (sorted keys, compact)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_str(submission: dict, key: str) -> str:
    value = submission.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"save-example requires a non-empty string {key!r}")
    return value


def _validate_result(result: Any) -> None:
    """The observed Ariadne result envelope (get_metric/define_metric shape):
    metric name, compiled SQL, column list, row list and the governed label.
    The storage gate checks structure; it cannot authenticate a prior local
    command or independently establish business truth (spec)."""
    if not isinstance(result, dict):
        raise ValueError("save-example requires the observed Ariadne 'result' envelope")
    if not isinstance(result.get("metric"), str) or not result["metric"]:
        raise ValueError("'result.metric' must be a non-empty string")
    # spec 0023 §2: valid retained SQL text is a non-whitespace string; the
    # retained text itself is never normalized.
    if not isinstance(result.get("sql"), str) or not result["sql"].strip():
        raise ValueError("'result.sql' must be a non-whitespace string (the retained SQL)")
    if not isinstance(result.get("columns"), list) or not all(
        isinstance(column, str) for column in result["columns"]
    ):
        raise ValueError("'result.columns' must be a list of column names")
    if not isinstance(result.get("rows"), list):
        raise ValueError("'result.rows' must be a list of rows")
    if not isinstance(result.get("governed"), bool):
        raise ValueError("'result.governed' must be a boolean")


def _resolve_citation(ref: str, served_root: Path) -> dict:
    """A cited served metric or Policy page: must resolve to an existing .md
    file in the served metric or Policy page directories inside the selected
    served root. Its content digest is recorded with it — no guessed or
    fabricated citation is ever recorded."""
    resolved = (served_root / ref).resolve()
    root = served_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"cited path escapes the selected served root: {ref!r}")
    rel = resolved.relative_to(root).as_posix()
    if not (rel.startswith(_CITATION_KINDS) and resolved.suffix == ".md"):
        raise ValueError(
            "cited path must be a served metric or Policy page "
            f"(context_layer/metrics/*.md or context_layer/policies/*.md): {ref!r}"
        )
    if not resolved.is_file():
        raise ValueError(f"cited path does not exist in the served root: {ref!r}")
    return {"path": ref, "sha256": _sha256_hex(resolved.read_bytes())}


def _normalize_submission(submission: Any, served_root: Path) -> dict:
    """Validate one explicit submission into the canonical record fields."""
    if not isinstance(submission, dict):
        raise ValueError("save-example expects a submission object")
    if claimed := sorted(_RESERVED_FIELDS & submission.keys()):
        raise ValueError(
            f"submission sets reserved field(s) {claimed}: example identity, review "
            "and verification state are written by the system, never claimed by a "
            "submission (identity is self-declared, review is operator-only)"
        )
    record: dict[str, Any] = {
        "question": _require_str(submission, "question"),
        "interpretation": _require_str(submission, "interpretation"),
    }
    method = submission.get("method")
    if (
        not isinstance(method, dict)
        or method.get("operation") not in OPERATIONS
        or not isinstance(method.get("arguments"), dict)
        or not method["arguments"]
    ):
        raise ValueError(
            "'method' must name operation 'get_metric' or 'define_metric' with its "
            "structured 'arguments' (never standalone SQL)"
        )
    operation = method["operation"]
    arguments = method["arguments"]
    missing = [
        key
        for key in _OPERATION_ARGUMENTS[operation]
        if not isinstance(arguments.get(key), str) or not arguments[key].strip()
    ]
    if missing:
        raise ValueError(
            f"'method' for {operation!r} must carry the structured arguments the "
            f"runtime operation takes (missing or non-string: {', '.join(missing)}) — "
            "standalone SQL is not a rerunnable argument"
        )
    record["method"] = {"operation": operation, "arguments": arguments}
    parameters = submission.get("parameters")
    if parameters is not None:
        if not isinstance(parameters, dict):
            raise ValueError("'parameters' must be a mapping (range, filters, dimensions, grain)")
        record["parameters"] = parameters
    project = submission.get("project")
    if project is not None:
        if not isinstance(project, str) or not project.strip():
            raise ValueError("'project' must be a non-empty string")
        record["project"] = project
    _validate_result(submission.get("result"))
    # spec 0023 §2: provenance is DERIVED from the validated result envelope
    # only — exact text, no trimming/normalization; the fixed descriptor never
    # claims a verified execution origin.
    record["sql_provenance"] = {
        "source": SQL_PROVENANCE_SOURCE,
        "text": submission["result"]["sql"],
    }
    record["submitter"] = {
        "identity": _require_str(submission, "submitter"),
        "attestation": _require_str(submission, "attestation"),
    }
    cited = submission.get("sources")
    if cited is None:  # absent and explicit null both mean no citations
        cited = []
    if not isinstance(cited, list) or not all(isinstance(ref, str) and ref for ref in cited):
        raise ValueError("'sources' must be a list of served metric/Policy paths")
    record["sources"] = [_resolve_citation(ref, served_root) for ref in cited]
    return record


def _example_id(question: str, captured: datetime) -> str:
    slug = "-".join(_SLUG_TOKEN_RE.findall(question.lower()))[:48].rstrip("-")
    return f"{slug or 'example'}-{captured:%Y%m%dT%H%M%S}"


def _record_markdown(record: dict) -> bytes:
    """One OKF v0.2 answer-example page: structured frontmatter (question,
    interpretation, parameters, method, cited sources with digests,
    self-declared submitter) plus the bounded answer excerpt as fenced
    evidence. Saved prose and the snapshot are evidence only — never an
    execution shortcut, never an instruction to an agent."""
    front = {key: value for key, value in record.items() if key != "answer"}
    answer = record["answer"]
    heading = " ".join(record["question"].split())  # one heading line, whatever was asked
    return (
        f"---\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True)}---\n\n"
        f"# {heading}\n\n"
        "Historical evidence only — never a cached answer; rerun the recorded "
        "method on current data before reuse.\n\n"
        f"Captured answer excerpt ({answer['captured']}; full structured-result "
        f"digest `{answer['result_digest']}`):\n\n"
        f"````json\n{answer['excerpt']}\n````\n"
    ).encode()


def _claim_draft(directory: Path, example_id: str, payload: bytes) -> Path:
    """Claim one unique draft path — O_CREAT|O_EXCL with a numeric suffix on
    collision (same discipline as the runtime's proposal staging): a repeated
    intentional save (or racing writers) stages a separately identified record
    instead of overwriting."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{example_id}.md"
    suffix = 2
    while True:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            candidate = directory / f"{example_id}-{suffix}.md"
            suffix += 1
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        return candidate


def _frontmatter(path: Path) -> dict | None:
    """The page's frontmatter mapping, or None when it is not an OKF page
    (index.md/log.md, unparsable frontmatter)."""
    match = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) else None


def _staged_state(meta: dict) -> str:
    """A staged page's honest state (issue #20): draft unless the operator
    review command closed it (reject / request-revision audit history). Review
    authority still derives from location (ADR-0015): closure is read only
    from the recorded review evidence, and a staged page can never present
    itself as stable."""
    review = meta.get("review")
    if isinstance(review, dict) and review.get("outcome") in ("reject", "request-revision"):
        return str(review["outcome"])
    return "draft"


def _write_index(directory: Path, *, staged: bool) -> None:
    """Regenerate the example root's ``index.md`` from the current records.
    Staged pages label their honest state (draft or closed history — never a
    self-declared stable); served pages label the system-written status."""
    lines = ["# Answer Examples", ""]
    for page in sorted(p for p in directory.glob("*.md") if p.name not in ("index.md", "log.md")):
        meta = _frontmatter(page) or {}
        question = " ".join(str(meta.get("question") or page.stem).split())
        if staged:
            state = _staged_state(meta)
            label = "draft" if state == "draft" else f"{state} (history)"
        else:
            label = str(meta.get("status") or "stable")
        lines.append(f"* [{question}]({page.name}) — {label}")
    (directory / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_candidate_index(directory: Path) -> None:
    """Candidate navigation is always unadmitted, regardless of file claims."""
    lines = ["# Answer Examples", ""]
    for page in sorted(p for p in directory.glob("*.md") if p.name not in ("index.md", "log.md")):
        meta = _frontmatter(page) or {}
        question = " ".join(str(meta.get("question") or page.stem).split())
        lines.append(f"* [{question}]({page.name}) — draft")
    (directory / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _refresh_bundle(directory: Path, example_id: str, record: dict) -> None:
    """Generated OKF bundle bookkeeping for the example root: a regenerated
    ``index.md`` over the current records and one ``log.md`` Creation entry —
    the same shapes the promotion gate keeps for the Context Layer bundle."""
    _write_index(directory, staged=True)

    log = directory / "log.md"
    if log.is_file():
        entries = log.read_text(encoding="utf-8").rstrip("\n").split("\n")
    else:
        entries = ["# Directory Update Log"]
    heading = f"## {record['generated'][:10]}"
    entry = (
        f"**Creation**: {EXAMPLES_DIR}/{example_id}.md — draft submission by "
        f"{record['submitter']['identity']}"
    )
    if heading in entries:
        pos = entries.index(heading) + 1
        while pos < len(entries) and entries[pos].startswith("**"):
            pos += 1
    else:
        pos = 1 if entries and entries[0].startswith("# ") else 0
        entries[pos:pos] = ["", heading]
        pos += 2
    entries[pos:pos] = [entry]
    log.write_text("\n".join(entries) + "\n", encoding="utf-8")


def _guard_staging(directory: Path, served_root: Path, examples_root: Path | None = None) -> None:
    """Staged examples live under the selected staging root and never in or
    through the served root (ADR-0015): a symlinked or overlapping example
    directory — or a symlinked bundle bookkeeping file — is refused before
    any write, so no save can touch served artifacts. The example directory
    itself is refused as a symlink even when its target stays inside staging
    (ADR-0003): redirects into a staged Context Layer bundle would ride its
    human batch promotion; only the final path component is checked, so the
    operator-selected staging root may still sit behind a symlinked ancestor.
    ``examples_root`` is the separate example-store root (issue #37 fix pass:
    the managed route anchors stable examples at the logical project root) —
    staging overlaps it just as little as the citation/artifact root."""
    if directory.is_symlink():
        raise ValueError(
            f"staging example directory itself is a symlink — refusing to write: {directory}"
        )
    resolved = directory.resolve()
    if not resolved.is_relative_to(directory.parent.resolve()):
        raise ValueError(
            f"staging example directory escapes the staging root (symlink or overlap?): {resolved}"
        )
    if resolved.is_relative_to(served_root.resolve()):
        raise ValueError(f"staging example directory overlaps the served root: {resolved}")
    if examples_root is not None and resolved.is_relative_to(
        (Path(examples_root) / EXAMPLES_DIR).resolve()
    ):
        raise ValueError(f"staging example directory overlaps the example store root: {resolved}")
    for name in ("index.md", "log.md"):
        if (directory / name).is_symlink():
            raise ValueError(f"staged bundle file {name!r} is a symlink — refusing to write")


def save_example(
    submission: Any,
    served_root: str | Path,
    staging_dir: str | Path,
    *,
    examples_root: str | Path | None = None,
) -> dict:
    """Stage one explicit answer-example draft (spec 2026-09-29-0007). Returns
    the unique staged ID/path with ``status: "draft"``. Every validation runs
    before the first write: a failed or malformed submission stores nothing.
    ``served_root`` is the CITATION root cited pages resolve against (the
    pinned artifact root on the managed route); ``examples_root`` optionally
    names the separate example-store root the guard also protects (issue #37
    fix pass — defaults to ``served_root`` for the legacy shared root)."""
    record = _normalize_submission(submission, Path(served_root))
    result = submission["result"]
    captured = datetime.now(UTC).isoformat(timespec="seconds")
    excerpt = _canonical({key: result[key] for key in ("metric", "governed", "columns", "rows")})
    encoded = excerpt.encode("utf-8")
    if len(encoded) > MAX_EXCERPT_BYTES:
        raise ValueError(
            f"answer excerpt is {len(encoded)} bytes, over the {MAX_EXCERPT_BYTES}-byte "
            "bound — bound the submitted result instead of silently truncating its meaning"
        )
    record.update(
        {
            "type": "answer_example",
            "status": "draft",
            "generated": captured,
            "answer": {
                "captured": captured,
                "excerpt": excerpt,
                "result_digest": _sha256_hex(_canonical(result).encode("utf-8")),
            },
        }
    )
    page = _record_markdown(record)
    if len(page) > MAX_RECORD_BYTES:
        raise ValueError(
            f"encoded example record is {len(page)} bytes, over the "
            f"{MAX_RECORD_BYTES}-byte bound — submit a smaller record"
        )
    example_id = _example_id(record["question"], datetime.now(UTC))
    directory = Path(staging_dir) / EXAMPLES_DIR
    _guard_staging(directory, Path(served_root), Path(examples_root) if examples_root else None)
    staged = _claim_draft(directory, example_id, page)
    _refresh_bundle(directory, staged.stem, record)
    return {"id": staged.stem, "path": str(staged), "status": "draft"}


def save_candidate_example(
    submission: Any,
    project: str | Path,
    served_root: str | Path,
    base_revision: str,
    *,
    proposal: str | None = None,
    expected_revision: str | None = None,
) -> dict:
    """Save one explicit Example as a commit in a proposal, never a file-store draft."""
    from ariadne import proposals

    if (proposal is None) != (expected_revision is None):
        raise ValueError("--proposal and --expected-revision are required together")
    project = Path(project).resolve()
    citation_root = Path(served_root)
    record = _normalize_submission(submission, citation_root)
    selected_revision = base_revision
    proposal_record = None
    if proposal is not None:
        proposal_record = proposals._load_record(project, proposal)
        selected_revision = proposal_record["candidate_revision"]
        if expected_revision != selected_revision:
            raise ValueError(
                f"stale revision: proposal {proposal} is at candidate {selected_revision}, "
                f"the save-example expected {expected_revision} — re-read and retry; "
                "nothing was written"
            )
        base_revision = proposal_record["base_revision"]
    for citation in record["sources"]:
        resolved = (citation_root.resolve() / citation["path"]).resolve()
        root = citation_root.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"citation {citation['path']!r} escapes the selected snapshot")
        rel = resolved.relative_to(root).as_posix()
        blob = proposals._read_blob(project, selected_revision, rel)
        if blob is None or _sha256_hex(blob) != citation["sha256"]:
            raise ValueError(
                f"citation {citation['path']!r} does not match the selected candidate revision"
            )

    now = datetime.now(UTC)
    captured = now.isoformat(timespec="seconds")
    result = submission["result"]
    excerpt = _canonical({key: result[key] for key in ("metric", "governed", "columns", "rows")})
    if len(excerpt.encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise ValueError(
            f"answer excerpt exceeds the {MAX_EXCERPT_BYTES}-byte bound — submit a smaller result"
        )
    record.update(
        {
            "type": "answer_example",
            "status": "draft",
            "generated": captured,
            "answer": {
                "captured": captured,
                "excerpt": excerpt,
                "result_digest": _sha256_hex(_canonical(result).encode("utf-8")),
            },
        }
    )
    page = _record_markdown(record)
    if len(page) > MAX_RECORD_BYTES:
        raise ValueError(
            f"encoded example record is {len(page)} bytes, over the "
            f"{MAX_RECORD_BYTES}-byte bound — submit a smaller record"
        )
    base_id = _example_id(record["question"], now)
    tracked = proposals._git(
        ["ls-tree", "-r", "--name-only", selected_revision, "--", EXAMPLES_DIR], project
    ).stdout.splitlines()
    existing = {
        PurePosixPath(rel).stem
        for rel in tracked
        if rel.startswith(f"{EXAMPLES_DIR}/")
        and rel.count("/") == 1
        and rel.endswith(".md")
        and PurePosixPath(rel).name not in ("index.md", "log.md")
    }
    example_id = base_id
    suffix = 2
    while example_id in existing:
        example_id = f"{base_id}-{suffix}"
        suffix += 1

    created_proposal = proposal is None
    if created_proposal:
        started = proposals.start_proposal(project, base_revision=selected_revision)
        proposal = started["proposal"]
        expected_revision = started["candidate_revision"]
        base_revision = started["base_revision"]
    assert proposal is not None and expected_revision is not None
    try:
        result_record = proposals.add_answer_example(
            project, proposal, expected_revision, example_id, page.decode("utf-8")
        )
    except Exception as exc:
        if not created_proposal and isinstance(exc, ValueError):
            raise
        worktree = project / proposals.WORKTREES_REL / proposal
        try:
            head_result = proposals._git(["rev-parse", "HEAD"], worktree, check=False)
            head = head_result.stdout.strip() or head_result.stderr.strip() or "unavailable"
        except Exception:
            head = "unavailable"
        try:
            status_result = proposals._git(
                ["status", "--short", "--untracked-files=all"], worktree, check=False
            )
            worktree_status = status_result.stdout.strip()
            if not worktree_status:
                worktree_status = (
                    "clean" if status_result.returncode == 0 else status_result.stderr.strip()
                ) or "unavailable"
        except Exception:
            worktree_status = "unavailable"
        try:
            recorded = proposals._load_record(project, proposal)["candidate_revision"]
        except Exception:
            recorded = "unavailable"
        raise RuntimeError(
            f"save-example failed; proposal {proposal} remains unadmitted. "
            f"Recorded candidate {recorded}; branch HEAD {head}; "
            f"worktree status: {worktree_status}. "
            f"Preserve the proposal evidence for human resolution: {exc}"
        ) from exc
    return {
        "id": example_id,
        "proposal": proposal,
        "base_revision": base_revision,
        "candidate_revision": result_record["revision"],
        "status": "draft",
        "path": result_record["path"],
    }


def validated_sql_provenance(meta: dict, label: str) -> dict | None:
    """The stored sql_provenance mapping (spec 0023 §§3–4). Absent means a
    legacy record: no provenance was recorded, rendered as ``null``/accepted —
    never a backfilled or excluded record. PRESENT but malformed (not a
    mapping, a foreign source descriptor, whitespace-only text) is invalid
    data: it fails the caller with an identifiable error instead of passing as
    usable provenance or silently missing."""
    if "sql_provenance" not in meta:
        return None
    raw = meta["sql_provenance"]
    if not isinstance(raw, dict):
        raise ValueError(f"{label} carries a malformed sql_provenance (not a mapping): {raw!r}")
    if raw.get("source") != SQL_PROVENANCE_SOURCE:
        raise ValueError(
            f"{label} carries an unsupported sql_provenance.source "
            f"{raw.get('source')!r} (only {SQL_PROVENANCE_SOURCE!r} is defined)"
        )
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(
            f"{label} carries a malformed sql_provenance.text (a non-whitespace string is required)"
        )
    return {"source": SQL_PROVENANCE_SOURCE, "text": text}


def _is_stale(meta: dict, served_root: Path) -> bool:
    """Dependency staleness against the recorded digests (spec): a cited served
    metric/Policy that is missing, unreadable, escaping the root or changed
    makes the record stale — its historical file is never mutated. With no
    cited dependency no staleness claim is invented."""
    entries = meta.get("sources") or []
    if not entries:
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            return True
        try:
            resolved = (served_root / str(entry.get("path"))).resolve()
            if (
                not resolved.is_relative_to(served_root.resolve())
                or not resolved.is_file()
                or _sha256_hex(resolved.read_bytes()) != entry.get("sha256")
            ):
                return True
        except OSError:
            return True
    return False


def validate_staged_record(meta: dict, body: str, served_root: Path) -> None:
    """The stored record shape gate shared by legacy review and Git admission."""
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
    # A present provenance mapping must be the exact result-derived form; an
    # absent mapping remains valid legacy evidence and is never backfilled.
    validated_sql_provenance(meta, "the staged record")
    if _ANSWER_EVIDENCE_RE.search(body) is None:
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
        if _resolve_citation(path, served_root)["sha256"] != sha256:
            raise ValueError(
                f"recorded citation {path!r} no longer matches the current served "
                "metric/Policy bytes — submit and review a fresh revision"
            )


def validate_candidate_records(project: Path, record: dict, candidate_root: Path) -> list[str]:
    """Check new/edited Examples against this candidate; preserve admitted history."""
    from ariadne import proposals

    examples_root = candidate_root / EXAMPLES_DIR
    paths = (
        {
            f"{EXAMPLES_DIR}/{path.name}": path
            for path in sorted(examples_root.glob("*.md"))
            if path.is_file() and path.name not in ("index.md", "log.md")
        }
        if examples_root.is_dir()
        else {}
    )
    baseline = record.get("expected_baseline")
    baseline_paths: set[str] = set()
    if baseline is not None:
        baseline_paths = {
            rel
            for rel in proposals._git(
                ["ls-tree", "-r", "--name-only", baseline, "--", EXAMPLES_DIR], project
            ).stdout.splitlines()
            if rel.startswith(f"{EXAMPLES_DIR}/")
            and rel.count("/") == 1
            and rel.endswith(".md")
            and PurePosixPath(rel).name not in ("index.md", "log.md")
        }
    errors = [
        f"{rel}: previously admitted answer-example history may not be deleted"
        for rel in sorted(baseline_paths - paths.keys())
    ]
    for rel, path in paths.items():
        data = path.read_bytes()
        if baseline is not None and proposals._read_blob(project, baseline, rel) == data:
            continue  # unchanged admission evidence may now be stale history
        try:
            text = data.decode("utf-8")
            match = _FRONTMATTER_RE.match(text)
            if match is None:
                raise ValueError("frontmatter is missing or malformed")
            meta = yaml.safe_load(match.group(1))
            if not isinstance(meta, dict) or meta.get("type") != "answer_example":
                raise ValueError("the candidate page is not an answer_example record")
            if len(data) > MAX_RECORD_BYTES:
                raise ValueError(f"record exceeds the {MAX_RECORD_BYTES}-byte bound")
            forged = sorted(
                {"id", "verified", "review", "stale", "superseded", "superseded_by", "attested"}
                & meta.keys()
            )
            if forged:
                raise ValueError(f"system-owned Example claim(s) are not authored: {forged}")
            submitter = meta.get("submitter")
            if (
                not isinstance(submitter, dict)
                or not isinstance(submitter.get("identity"), str)
                or not submitter["identity"].strip()
                or not isinstance(submitter.get("attestation"), str)
                or not submitter["attestation"].strip()
            ):
                raise ValueError(
                    "the submitter identity and business-meaning attestation are required"
                )
            validate_staged_record(meta, match.group(2), candidate_root)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: {exc}")
    return errors


def _rank_records(
    records: list[tuple[str, dict, str, bool]],
    query: str,
    limit: int,
    include_history: bool,
    include_sql: bool,
    *,
    proposal: str | None = None,
    revision: str | None = None,
) -> list[dict]:
    if limit <= 0:
        return []
    terms = _QUERY_TOKEN_RE.findall(query.lower())
    if not terms:
        return []
    ranked = []
    for path, meta, status, stale in records:
        if not include_history and (stale or status not in ("draft", "stable")):
            continue
        tokens = _QUERY_TOKEN_RE.findall(
            f"{meta.get('question') or ''} {meta.get('interpretation') or ''}".lower()
        )
        score = sum(tokens.count(term) for term in terms)
        if not score:
            continue
        submitter = meta.get("submitter")
        submitter = submitter if isinstance(submitter, dict) else {}
        provenance = {
            "submitter": submitter.get("identity"),
            "generated": meta.get("generated"),
            "sources": meta.get("sources") or [],
        }
        if proposal is None:
            provenance["review"] = meta.get("review")
        hit = {
            "id": PurePosixPath(path).stem,
            "status": status,
            "stale": stale,
            "question": meta.get("question"),
            "interpretation": meta.get("interpretation"),
            "method": meta.get("method"),
            "provenance": provenance,
            "path": path,
        }
        if proposal is not None:
            hit.update({"proposal": proposal, "revision": revision})
        ranked.append((0 if status == "stable" and not stale else 1, -score, path, hit, meta))
    ranked.sort()
    selected = ranked[:limit]
    if include_sql:
        for *_, hit, meta in selected:
            hit["provenance"]["sql"] = validated_sql_provenance(
                meta, f"answer example {hit['id']!r}"
            )
    return [hit for *_, hit, _ in selected]


def _candidate_is_stale(meta: dict, project: Path, revision: str, proposals) -> bool:
    sources = meta.get("sources") or []
    if not isinstance(sources, list):
        return True
    for entry in sources:
        if not isinstance(entry, dict):
            return True
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            return True
        pure = PurePosixPath(path)
        if pure.is_absolute() or "\\" in path or path.startswith("-"):
            return True
        parts: list[str] = []
        for part in pure.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    return True
                parts.pop()
            else:
                parts.append(part)
        citation_kind = "/".join(parts[:2]) + "/" if len(parts) >= 2 else ""
        if len(parts) < 3 or citation_kind not in _CITATION_KINDS or not parts[-1].endswith(".md"):
            return True
        rel = "/".join(parts)
        blob = proposals._read_blob(project, revision, rel)
        if blob is None or _sha256_hex(blob) != digest:
            return True
    return False


def search_admitted(
    snapshot_root: str | Path,
    query: str,
    limit: int = 10,
    include_history: bool = False,
    include_sql: bool = False,
) -> list[dict]:
    """Search only Examples inside one pinned admitted snapshot."""
    root = Path(snapshot_root)
    records = []
    directory = root / EXAMPLES_DIR
    if directory.is_dir():
        for path in sorted(directory.glob("*.md")):
            meta = _frontmatter(path)
            if meta and meta.get("type") == "answer_example":
                records.append(
                    (f"{EXAMPLES_DIR}/{path.name}", meta, "stable", _is_stale(meta, root))
                )
    return _rank_records(records, query, limit, include_history, include_sql)


def search_candidate(
    project: str | Path,
    query: str,
    *,
    proposal: str,
    revision: str,
    limit: int = 10,
    include_history: bool = False,
    include_sql: bool = False,
) -> list[dict]:
    """Read one recorded candidate commit directly; never a worktree or source."""
    from ariadne import proposals

    project = Path(project).resolve()
    if not proposal or not revision:
        raise ValueError("candidate Example search requires both --proposal and --revision")
    record = proposals._load_record(project, proposal)
    if revision != record["candidate_revision"]:
        raise ValueError(
            f"revision {revision} is not proposal {proposal}'s recorded current candidate "
            f"{record['candidate_revision']} — re-read the candidate before searching"
        )
    paths = proposals._git(
        ["ls-tree", "-r", "--name-only", revision, "--", EXAMPLES_DIR], project
    ).stdout.splitlines()
    records = []
    for rel in sorted(paths):
        if (
            not rel.startswith(f"{EXAMPLES_DIR}/")
            or rel.count("/") != 1
            or not rel.endswith(".md")
            or PurePosixPath(rel).name in ("index.md", "log.md")
        ):
            continue
        blob = proposals._read_blob(project, revision, rel)
        if blob is None:
            continue
        if len(blob) > MAX_RECORD_BYTES:
            raise ValueError(f"{rel}: candidate record exceeds the {MAX_RECORD_BYTES}-byte bound")
        match = _FRONTMATTER_RE.match(blob.decode("utf-8"))
        if match is None:
            continue
        try:
            meta = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(meta, dict) and meta.get("type") == "answer_example":
            records.append(
                (rel, meta, "draft", _candidate_is_stale(meta, project, revision, proposals))
            )
    return _rank_records(
        records,
        query,
        limit,
        include_history,
        include_sql,
        proposal=proposal,
        revision=revision,
    )


def search_examples(
    served_root: str | Path,
    staging_dir: str | Path,
    query: str,
    limit: int = 10,
    include_history: bool = False,
    include_sql: bool = False,
    *,
    examples_root: str | Path | None = None,
) -> list[dict]:
    """Ranked labeled example records from the current served and staging
    example roots, read on each request so a new staged draft is immediately
    discoverable in this checkout (spec §interfaces). Approved non-stale
    records rank ahead of drafts; by default stale and closed (superseded/
    rejected) records stay history — ``include_history`` exposes them labeled.
    SQL is never a search or ranking input; ``include_sql`` (spec 0023 §3)
    only attaches each SELECTED hit's stored ``sql_provenance`` mapping as
    ``provenance.sql`` (``null`` for legacy records without it) after ranking
    and slicing — a malformed present mapping on a selected hit refuses the
    whole retrieval with an identifiable error, and ``include_sql`` alone
    never widens record eligibility (history stays behind ``include_history``).
    No query is ever executed and no saved row is returned. ``served_root`` is
    the CITATION root dependency staleness is checked against;
    ``examples_root`` optionally names a separate example-store root (issue
    #37 fix pass: the managed route anchors the operator-reviewed stable
    store at the logical project root, separate from the pinned artifact
    root — default ``served_root`` keeps the legacy shared root)."""
    if limit <= 0:
        return []
    terms = _QUERY_TOKEN_RE.findall(query.lower())
    if not terms:
        return []
    root = Path(served_root)
    examples = Path(examples_root) if examples_root is not None else root
    ranked: list[tuple[int, int, str, dict, dict]] = []
    for is_served, directory in (
        (True, examples / EXAMPLES_DIR),
        (False, Path(staging_dir) / EXAMPLES_DIR),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            meta = _frontmatter(path)
            if not meta or meta.get("type") != "answer_example":
                continue
            status = meta.get("status")
            if not is_served:
                # Issue #20: a staged page's state is draft unless the operator
                # review command closed it (rejected / revision-requested
                # history); location, never self-declaration, remains the
                # review authority — a staged page can never claim stable.
                status = _staged_state(meta)
            stale = _is_stale(meta, root)
            if not include_history and (stale or status not in ("draft", "stable")):
                continue
            tokens = _QUERY_TOKEN_RE.findall(
                f"{meta.get('question') or ''} {meta.get('interpretation') or ''}".lower()
            )
            score = sum(tokens.count(term) for term in terms)
            if not score:
                continue
            submitter = meta.get("submitter")
            submitter = submitter if isinstance(submitter, dict) else {}
            ranked.append(
                (
                    0 if status == "stable" and not stale else 1,  # approved non-stale first
                    -score,
                    str(path),
                    {
                        "id": path.stem,
                        "status": status,
                        "stale": stale,
                        "question": meta.get("question"),
                        "interpretation": meta.get("interpretation"),
                        "method": meta.get("method"),
                        "provenance": {
                            "submitter": submitter.get("identity"),
                            "generated": meta.get("generated"),
                            "sources": meta.get("sources") or [],
                            "review": meta.get("review"),
                        },
                        "path": str(path),
                    },
                    meta,
                )
            )
    ranked.sort()
    selected = ranked[:limit]
    if include_sql:
        for *_, hit, meta in selected:
            hit["provenance"]["sql"] = validated_sql_provenance(
                meta, f"answer example {hit['id']!r}"
            )
    return [hit for *_, hit, _ in selected]
