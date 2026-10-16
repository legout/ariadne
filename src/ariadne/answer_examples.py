"""Separate OKF store for explicitly submitted answer examples (issue #19).

ADR-0015 / spec 2026-09-29-0007 revision 1: an Answer Example is an explicitly
submitted OKF record of a question, its intended meaning, the Ariadne method
that answered it and a bounded historical answer — a labeled reference for
finding and checking a method, never a governed definition, a Policy or an
answer cache. This module is the transport-neutral core the runtime (and the
optional MCP adapter, issue #21) shares; the operator review command (issue
#20) is deliberately not here.

- ``save_candidate_example`` validates one explicit submission, derives a
  bounded historical answer excerpt and full-result digest, verifies cited
  bytes against the exact selected Git revision, then writes one Example to a
  revision-checked proposal commit. No durable staging store exists.
- ``search_admitted`` reads only the admitted snapshot; ``search_candidate``
  reads one explicitly selected recorded proposal revision. Neither executes
  queries or returns saved rows. ``include_sql=True`` adds the exact submitted
  SQL provenance to selected hits; SQL never ranks or executes. Examples stay
  outside ``context_layer/`` and share human Git Admission with all authored
  artifacts.
"""

from __future__ import annotations

import hashlib
import json
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


def _write_candidate_index(directory: Path) -> None:
    """Candidate navigation is always unadmitted, regardless of file claims."""
    lines = ["# Answer Examples", ""]
    for page in sorted(p for p in directory.glob("*.md") if p.name not in ("index.md", "log.md")):
        meta = _frontmatter(page) or {}
        question = " ".join(str(meta.get("question") or page.stem).split())
        lines.append(f"* [{question}]({page.name}) — draft")
    (directory / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    from . import proposals

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


def validate_example_record(meta: dict, body: str, admitted_root: Path) -> None:
    """Validate a newly authored Example against the selected Git candidate."""
    if meta.get("status") != "draft":
        raise ValueError(
            f"the candidate Example must have draft status, not {meta.get('status')!r}"
        )
    for key in ("question", "interpretation"):
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"the candidate Example needs a non-empty string {key!r}")
    method = meta.get("method")
    operation = method.get("operation") if isinstance(method, dict) else None
    arguments = method.get("arguments") if isinstance(method, dict) else None
    if operation not in OPERATIONS or not isinstance(arguments, dict) or not arguments:
        raise ValueError(
            "the candidate Example must record operation 'get_metric' or 'define_metric' "
            "with its structured 'arguments' (never standalone SQL)"
        )
    missing = [
        key
        for key in _OPERATION_ARGUMENTS[operation]
        if not isinstance(arguments.get(key), str) or not arguments[key].strip()
    ]
    if missing:
        raise ValueError(
            f"the candidate Example's {operation!r} method is missing structured "
            f"arguments (missing or non-string: {', '.join(missing)})"
        )
    validated_sql_provenance(meta, "the candidate Example")
    if _ANSWER_EVIDENCE_RE.search(body) is None:
        raise ValueError(
            "the candidate Example must keep its bounded historical answer evidence "
            "(captured excerpt and full structured-result digest) in the page body"
        )
    excerpt = re.search(r"````json\n(.*?)\n````", body, re.DOTALL)
    if excerpt is None:
        raise ValueError("the candidate Example's answer excerpt block is missing")
    if len(excerpt.group(1).encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise ValueError(
            f"the candidate Example's answer excerpt is over the {MAX_EXCERPT_BYTES}-byte "
            "bound — submit a fresh bounded revision"
        )
    sources = meta.get("sources")
    if not isinstance(sources, list):
        raise ValueError("'sources' must be the recorded list of metric/Policy digests")
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
                "each recorded citation must be a metric/Policy page "
                "(context_layer/metrics|policies/*.md) with its sha256 digest"
            )
        if _resolve_citation(path, admitted_root)["sha256"] != sha256:
            raise ValueError(f"recorded citation {path!r} does not match the selected Git revision")


def validate_candidate_records(project: Path, record: dict, candidate_root: Path) -> list[str]:
    """Check new/edited Examples against this candidate; preserve admitted history."""
    from . import proposals

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
            validate_example_record(meta, match.group(2), candidate_root)
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
    from . import proposals

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
