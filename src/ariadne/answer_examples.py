"""Separate OKF store for explicitly submitted answer examples (issue #19).

ADR-0014 / spec 2026-09-29-0006 revision 1: an Answer Example is an explicitly
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
  malformed submission stores nothing.
- ``search_examples(...)`` re-reads the served and staging example roots on
  each request and returns ranked labeled hits (identity, staleness,
  question/interpretation, method summary, provenance, path). It never
  executes a query and never returns saved rows. ``search_context`` and
  governed ``get_metric.context`` are untouched by construction: examples live
  outside ``context_layer/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

EXAMPLES_DIR = "answer_examples"  # ADR-0014: the separate per-project OKF store
MAX_EXCERPT_BYTES = 8 * 1024  # spec: the timestamped answer excerpt bound
MAX_RECORD_BYTES = 64 * 1024  # spec: the whole encoded record bound
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
# is written only by the operator review command, issue #20).
_RESERVED_FIELDS = frozenset(
    {"id", "status", "verified", "review", "stale", "superseded", "attested"}
)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")  # same token rule as search_context
_SLUG_TOKEN_RE = re.compile(r"[a-z0-9]+")


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
    for key in ("metric", "sql"):
        if not isinstance(result.get(key), str) or not result[key]:
            raise ValueError(f"'result.{key}' must be a non-empty string")
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


def _refresh_bundle(directory: Path, example_id: str, record: dict) -> None:
    """Generated OKF bundle bookkeeping for the example root: a regenerated
    ``index.md`` over the current records and one ``log.md`` Creation entry —
    the same shapes the promotion gate keeps for the Context Layer bundle."""
    lines = ["# Answer Examples", ""]
    for page in sorted(
        p for p in directory.glob("*.md") if p.name not in ("index.md", "log.md")
    ):
        meta = _frontmatter(page) or {}
        question = " ".join(str(meta.get("question") or page.stem).split())
        # A staged page is a draft by location (ADR-0014): its self-declared
        # status never reaches the generated staged index as review authority.
        lines.append(f"* [{question}]({page.name}) — draft")
    (directory / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

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


def _guard_staging(directory: Path, served_root: Path) -> None:
    """Staged examples live under the selected staging root and never in or
    through the served root (ADR-0014): a symlinked or overlapping example
    directory — or a symlinked bundle bookkeeping file — is refused before
    any write, so no save can touch served artifacts. The example directory
    itself is refused as a symlink even when its target stays inside staging
    (ADR-0003): redirects into a staged Context Layer bundle would ride its
    human batch promotion; only the final path component is checked, so the
    operator-selected staging root may still sit behind a symlinked ancestor."""
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
    for name in ("index.md", "log.md"):
        if (directory / name).is_symlink():
            raise ValueError(f"staged bundle file {name!r} is a symlink — refusing to write")


def save_example(submission: Any, served_root: str | Path, staging_dir: str | Path) -> dict:
    """Stage one explicit answer-example draft (spec 2026-09-29-0006). Returns
    the unique staged ID/path with ``status: "draft"``. Every validation runs
    before the first write: a failed or malformed submission stores nothing."""
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
    _guard_staging(directory, Path(served_root))
    staged = _claim_draft(directory, example_id, page)
    _refresh_bundle(directory, staged.stem, record)
    return {"id": staged.stem, "path": str(staged), "status": "draft"}


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


def search_examples(
    served_root: str | Path,
    staging_dir: str | Path,
    query: str,
    limit: int = 10,
    include_history: bool = False,
) -> list[dict]:
    """Ranked labeled example records from the current served and staging
    example roots, read on each request so a new staged draft is immediately
    discoverable in this checkout (spec §interfaces). Approved non-stale
    records rank ahead of drafts; by default stale and closed (superseded/
    rejected) records stay history — ``include_history`` exposes them labeled.
    No query is ever executed and no saved row is returned."""
    if limit <= 0:
        return []
    terms = _QUERY_TOKEN_RE.findall(query.lower())
    if not terms:
        return []
    root = Path(served_root)
    ranked: list[tuple[int, int, str, dict]] = []
    for is_served, directory in (
        (True, root / EXAMPLES_DIR),
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
                # Review authority derives from location (ADR-0014): a staged
                # page is a draft however it labels itself; only a served page
                # may be reviewed/stable.
                status = "draft"
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
                        },
                        "path": str(path),
                    },
                )
            )
    ranked.sort()
    return [hit for _, _, _, hit in ranked][:limit]
