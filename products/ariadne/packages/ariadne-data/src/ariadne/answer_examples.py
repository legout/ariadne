"""Native Answer Example authoring and candidate retrieval (issue #19 → spec0035 C4).

ADR-0029 / shared spec0035 §4 with Ariadne spec 2026-09-29-0007 revision 1
and spec 2026-10-13-0023 revision 2: an Answer Example is an explicitly
submitted record of a question, its intended meaning, the Ariadne method
that answered it and a bounded historical answer — a labeled reference for
finding and checking a method, never a governed definition, a Policy or an
answer cache. This module is the transport-neutral core the runtime (and
the optional MCP adapter, issue #21) shares; the operator review command
(issue #20) is deliberately not here.

- ``save_candidate_example`` validates one explicit submission, derives a
  bounded historical answer excerpt and full-result digest, verifies cited
  knowledge pages against the exact selected Git revision, then authors ONE
  native ``knowledge/answer-examples/`` Compiled Page (producer-owned
  ``ariadne_profile`` kind ``answer_example``) through the shared native
  page-batch writer — the same proposal lock/revision discipline and human
  Git admission as every authored artifact. No second Example store or index
  exists.
- Admitted Examples are searched through the pinned scoped SDK views
  (``lumio_context.search_examples``); ``search_candidate`` reads one
  explicitly selected recorded proposal revision as labeled draft history.
  Neither executes queries or returns saved rows. ``include_sql=True`` adds
  the exact submitted SQL provenance to selected hits; SQL never ranks or
  executes.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import (
    UTC,  # pyright: ignore[reportAttributeAccessIssue] — resolver drift: UTC is py3.11+
    datetime,
)
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

EXAMPLES_DIR = "answer-examples"  # the native knowledge/ category slug of one Example
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
# Identity and review state are system-owned: a submission may not claim them
# (spec: local identity is self-declared, never authenticated; review evidence
# is written only by the operator review command, issue #20). sql_provenance
# is likewise system-derived from the validated result envelope — a caller
# may not supply its own (spec 0023 §2).
_RESERVED_FIELDS = frozenset(
    {"id", "status", "verified", "review", "stale", "superseded", "attested", "sql_provenance"}
)
_SLUG_TOKEN_RE = re.compile(r"[a-z0-9]+")
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


def _normalize_submission(submission: Any) -> dict:
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
        raise ValueError("'sources' must be a list of knowledge page paths")
    record["sources"] = cited  # verified against the exact selected revision at save
    return record


def _example_id(question: str, captured: datetime) -> str:
    slug = "-".join(_SLUG_TOKEN_RE.findall(question.lower()))[:48].rstrip("-")
    # lowercase digits only: the id becomes the Entity slug (entity:<id>),
    # which must begin and end with a letter or digit (KB slug rule)
    # Peer proposals cannot see each other's pages, so each save needs fresh entropy.
    return f"{slug or 'example'}-{captured.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _verify_citation(project: Path, revision: str, ref: str) -> dict:
    """One cited knowledge page: a KB-relative ``.md`` path whose exact bytes
    exist at the selected revision and whose producer kind is a metric or a
    Policy (spec rev 1: only served metrics/Policies may back an Example
    dependency; the digest is recorded with it — no guessed or fabricated
    citation is ever recorded)."""
    from . import proposals

    pure = PurePosixPath(ref)
    if pure.is_absolute() or "\\" in ref or ref.startswith("-") or ".." in pure.parts:
        raise ValueError(f"cited path {ref!r} escapes the selected revision")
    if not ref.endswith(".md"):
        raise ValueError(f"cited path must be a knowledge page: {ref!r}")
    blob = proposals._read_blob(project, revision, f"knowledge/{ref}")
    if blob is None:
        raise ValueError(f"cited path does not exist in the selected revision: {ref!r}")
    from lumio_wiki import parse_frontmatter

    meta, _body, _line = parse_frontmatter(blob.decode("utf-8"), pure.name)
    kind = ((meta or {}).get("ariadne_profile") or {}).get("kind")
    if kind not in ("metric", "policy"):
        raise ValueError(
            f"cited page must be a metric or Policy page: {ref!r} (producer kind {kind!r})"
        )
    return {"path": ref, "sha256": _sha256_hex(blob)}


def _page_markdown(record: dict, example_id: str) -> bytes:
    """One native ``knowledge/answer_examples/`` Compiled Page: the shared
    page frontmatter (stable Entity id, canonical title, controlled entity
    type, scoped visibility) plus the producer-owned ``answer_example``
    profile carrying the retained spec0007/0023 native families, and the
    bounded answer excerpt as fenced body evidence. Saved prose and the
    snapshot are evidence only — never an execution shortcut, never an
    instruction to an agent."""
    native = dict(record)
    native["type"] = "answer_example"
    question = " ".join(record["question"].split())  # one heading line, whatever was asked
    interpretation = " ".join(record["interpretation"].split())
    native.update(
        {
            "title": question,
            "description": interpretation,
            "tags": ["answer-example"],
            "sources": [],
        }
    )
    front = {
        "id": f"entity:{example_id}",
        # the canonical title carries the generated identity: two Examples of
        # the same question are two distinct pages under the writer's
        # declared-title addressing, never a title collision; the question's
        # exact bytes stay in native.question and the body heading.
        "title": f"{question} ({example_id})",
        "entity_types": ["answer-example"],
        "tags": ["answer-example"],
        "summary": interpretation,
        "lifecycle": "draft",
        "visibility": "public",
        "sources": [{"id": "src-explicit-submission", "title": "Explicit user submission"}],
        "ariadne_profile": {"version": 1, "kind": "answer_example", "native": native},
    }
    answer = record["answer"]
    return (
        f"---\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True)}---\n\n"
        f"# {question}\n\n"
        "Historical evidence only — never a cached answer; rerun the recorded "
        "method on current data before reuse.\n\n"
        f"Captured answer excerpt ({answer['captured']}; full structured-result "
        f"digest `{answer['result_digest']}`):\n\n"
        f"````json\n{answer['excerpt']}\n````\n"
    ).encode()


def save_candidate_example(
    submission: Any,
    project: str | Path,
    base_revision: str,
    *,
    proposal: str | None = None,
    expected_revision: str | None = None,
) -> dict:
    """Save one explicit Example as a native knowledge page in a candidate —
    the same proposal lock/revision discipline and human Git admission as
    every authored artifact; never an admitted page, never an executed query."""
    from . import proposals

    if (proposal is None) != (expected_revision is None):
        raise ValueError("--proposal and --expected-revision are required together")
    project = Path(project).resolve()
    record = _normalize_submission(submission)
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
    else:
        selected_revision = proposals._validate_revision(project, base_revision)
    # Citations bind the EXACT selected revision bytes (spec rev 1): every
    # cited path must resolve to a metric or Policy page of that revision.
    record["citations"] = [
        _verify_citation(project, selected_revision, ref) for ref in record.pop("sources")
    ]

    now = datetime.now(UTC)
    captured = now.isoformat(timespec="seconds")
    result = submission["result"]
    excerpt = _canonical({key: result[key] for key in ("metric", "governed", "columns", "rows")})
    if len(excerpt.encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise ValueError(
            f"answer excerpt exceeds the {MAX_EXCERPT_BYTES}-byte bound — submit a smaller result"
        )
    record["answer"] = {
        "captured": captured,
        "excerpt": excerpt,
        "result_digest": _sha256_hex(_canonical(result).encode("utf-8")),
    }
    base_id = _example_id(record["question"], now)
    tracked = proposals._git(
        ["ls-tree", "-r", "--name-only", selected_revision, "--", f"knowledge/{EXAMPLES_DIR}"],
        project,
    ).stdout.splitlines()
    existing = {
        PurePosixPath(rel).stem
        for rel in tracked
        if rel.endswith(".md") and PurePosixPath(rel).name not in ("index.md", "log.md")
    }
    example_id = base_id
    suffix = 2
    while example_id in existing:
        example_id = f"{base_id}-{suffix}"
        suffix += 1

    page = _page_markdown(record, example_id)
    if len(page) > MAX_RECORD_BYTES:
        raise ValueError(
            f"encoded example record is {len(page)} bytes, over the "
            f"{MAX_RECORD_BYTES}-byte bound — submit a smaller record"
        )
    created_proposal = proposal is None
    if created_proposal:
        started = proposals.start_proposal(project, base_revision=selected_revision)
        proposal = started["proposal"]
        expected_revision = started["candidate_revision"]
        base_revision = started["base_revision"]
    assert proposal is not None and expected_revision is not None
    try:
        result_record = proposals.edit_page_batch(
            project,
            proposal,
            expected_revision,
            [
                {
                    "path": f"knowledge/{EXAMPLES_DIR}/{example_id}.md",
                    "content": page.decode("utf-8"),
                }
            ],
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
        "path": result_record["paths"][0],
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


def validate_candidate_records(project: Path, record: dict, candidate_root: Path) -> list[str]:
    """Core meaning checks over the candidate's SDK-parsed answer_example
    pages, BEFORE admission (spec0035 C4): a new or changed record carries the
    per-operation required structured arguments, stays within the
    whole-encoded-page bound, keeps valid system-derived SQL provenance and
    its bounded body evidence, and cites only metric/Policy pages that exist
    at this exact candidate with matching digests. Unchanged admitted history
    (exact baseline bytes) is never re-judged: a historical Example may be
    stale, and its file is never rewritten or rejected for it. System-owned
    claim forgery is already refused at the write gate
    (``proposals._refuse_forged_claims``); the producer stays structural-only.
    SDK-parsed profiles only — never a second KB parser. Two retained
    spec0007 obligations are restored over the SDK-parsed bodies: previously
    admitted Example history (typed baseline identities from the exact
    expected-baseline commit via the public ``capture_revision``) cannot be
    removed from a candidate — including by dropping the profile — and the
    bounded historical evidence in the page body must keep its fenced JSON
    excerpt within the 8 KiB UTF-8 bound."""
    from lumio_wiki import load_knowledge_base

    from . import proposals

    kb_root = candidate_root / "knowledge"
    if not kb_root.is_dir():
        return []
    kb, _report = load_knowledge_base(kb_root)
    baseline = record.get("expected_baseline")
    revision = record.get("candidate_revision")
    if not isinstance(revision, str):
        errors: list[str] = ["the candidate record carries no candidate revision"]
        return errors
    errors = []
    # previously admitted Example history, captured from the EXACT
    # expected-baseline commit through the public SDK: typed pages keyed by
    # their actual producer identity (Entity id) — never a filename guess,
    # never a floating HEAD or latest pointer
    baseline_examples: dict[str, Any] = {}
    if baseline is not None:
        from lumio_wiki.git_authoring import capture_revision

        # the baseline commit lives in the PROJECT repository — the candidate
        # root here may be a temporary validation bundle outside any Git repo
        captured_baseline = capture_revision(project / "knowledge", baseline)
        for page in captured_baseline.kb.pages:
            profile = page.ariadne_profile
            if profile is not None and profile.kind == "answer_example":
                baseline_examples[page.id] = page
    candidate_examples: dict[str, str] = {}
    for page in kb.pages:
        profile = page.ariadne_profile
        if profile is None or profile.kind != "answer_example":
            continue
        candidate_examples[page.id] = page.path
        rel = f"knowledge/{page.path}"
        data = (candidate_root / rel).read_bytes()
        if baseline is not None and proposals._read_blob(project, baseline, rel) == data:
            continue  # unchanged admitted history may now be stale history
        native = profile.native or {}
        method = native.get("method")
        operation = method.get("operation") if isinstance(method, dict) else None
        arguments = method.get("arguments") if isinstance(method, dict) else None
        if operation not in OPERATIONS or not isinstance(arguments, dict) or not arguments:
            errors.append(
                f"{rel}: method must record operation {list(OPERATIONS)} with "
                "structured arguments"
            )
        else:
            missing = [
                key
                for key in _OPERATION_ARGUMENTS[operation]
                if not isinstance(arguments.get(key), str) or not arguments[key].strip()
            ]
            if missing:
                errors.append(
                    f"{rel}: the {operation!r} method is missing structured arguments "
                    f"(missing or non-string: {', '.join(missing)})"
                )
        if len(data) > MAX_RECORD_BYTES:
            errors.append(f"{rel}: record exceeds the {MAX_RECORD_BYTES}-byte bound")
        try:
            validated_sql_provenance(native, rel)
        except ValueError as exc:
            errors.append(str(exc))
        if _ANSWER_EVIDENCE_RE.search(page.body) is None:
            errors.append(
                f"{rel}: the bounded historical answer evidence (captured excerpt "
                "and full structured-result digest) must stay in the page body"
            )
        # the retained spec0007 body contract: the fenced JSON excerpt itself
        # must be present and stays within the 8 KiB UTF-8 bound — independent
        # of the structured native.answer.excerpt and of the 64 KiB whole-page
        # bound (byte-bound, not character-bound)
        excerpt_match = re.search(r"````json\n(.*?)\n````", page.body, re.DOTALL)
        if excerpt_match is None:
            errors.append(f"{rel}: the candidate Example's answer excerpt block is missing")
        elif len(excerpt_match.group(1).encode("utf-8")) > MAX_EXCERPT_BYTES:
            errors.append(
                f"{rel}: the candidate Example's answer excerpt is over the "
                f"{MAX_EXCERPT_BYTES}-byte bound — submit a fresh bounded revision"
            )
        for entry in native.get("citations") or []:
            cited = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(cited, str) or not cited:
                errors.append(f"{rel}: a recorded citation carries no path")
                continue
            try:
                verified = _verify_citation(project, revision, cited)
            except ValueError as exc:
                errors.append(f"{rel}: {exc}")
                continue
            if entry.get("sha256") != verified["sha256"]:
                errors.append(
                    f"{rel}: recorded citation {cited!r} does not match this candidate's bytes"
                )
    # admitted history cannot vanish from a candidate — including by dropping
    # the Example profile: the identity set is compared, so a removed page or
    # a stripped profile both refuse with the persisted identity named
    for entity_id in sorted(set(baseline_examples) - set(candidate_examples)):
        baseline_page = baseline_examples[entity_id]
        errors.append(
            f"knowledge/{baseline_page.path}: previously admitted answer-example history "
            f"may not be removed from the candidate ({entity_id})"
        )
    return errors


def _candidate_is_stale(meta: dict, project: Path, revision: str, proposals) -> bool:
    citations = meta.get("citations") or []
    if not isinstance(citations, list):
        return True
    for entry in citations:
        if not isinstance(entry, dict):
            return True
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            return True
        pure = PurePosixPath(path)
        if pure.is_absolute() or "\\" in path or path.startswith("-") or ".." in pure.parts:
            return True
        blob = proposals._read_blob(project, revision, f"knowledge/{path}")
        if blob is None or _sha256_hex(blob) != digest:
            return True
    return False


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
    """Read one recorded candidate revision through the public SDK capture
    (exact commit, typed parsed pages), select by the parsed producer kind —
    never a physical category, a filename-derived identity or a native.type
    gate — and rank with the KnowledgeBase's own lexical search over the
    already-authorized candidate set. Operator authoring plane: reachable
    only with the same capability that saved the candidate (the CLI
    ``--project`` surface / a server toolset that also exposes Example
    save). Draft labels, the exact revision and the SQL opt-in are
    preserved; nothing is executed."""
    from lumio_wiki.git_authoring import capture_revision

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
    captured = capture_revision(project / "knowledge", revision)
    selected = [
        page
        for page in captured.kb.pages
        if page.ariadne_profile is not None and page.ariadne_profile.kind == "answer_example"
    ]
    if not selected:
        return []
    ranked = []
    for result in captured.kb.search_pages(query, limit=len(selected), pages=selected):
        page = result.page
        meta = page.ariadne_profile.native or {}
        stale = _candidate_is_stale(meta, project, revision, proposals)
        if stale and not include_history:
            continue  # stale history never occupies a result slot by default
        submitter = meta.get("submitter")
        submitter = submitter if isinstance(submitter, dict) else {}
        ranked.append(
            (
                0 if not stale else 1,
                -result.score,
                page.path,
                {
                    "id": page.id,
                    "entity_id": page.id,
                    "status": "draft",
                    "stale": stale,
                    "question": meta.get("question"),
                    "interpretation": meta.get("interpretation"),
                    "method": meta.get("method"),
                    "provenance": {
                        "submitter": submitter.get("identity"),
                        "generated": (meta.get("answer") or {}).get("captured"),
                        "sources": meta.get("citations") or [],
                    },
                    "path": f"knowledge/{page.path}",
                    "proposal": proposal,
                    "revision": revision,
                },
                meta,
            )
        )
    ranked.sort(key=lambda item: item[:3])
    selected_hits = ranked[:limit]
    if include_sql:
        for *_, hit, meta in selected_hits:
            hit["provenance"]["sql"] = validated_sql_provenance(
                meta, f"answer example {hit['id']!r}"
            )
    return [hit for *_, hit, _meta in selected_hits]
