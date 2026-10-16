"""Harness-led authoring: source proposal/approval (issue #13) and the
measured harness inputs — source-linked converted document evidence plus the
approved-source profile (issue #14; spec 2026-09-24-0005 "Evidence and
source-access boundary" §1–3, ADR-0013).

Slice 1 — :func:`propose_sources` / :func:`approve_sources`. The harness
proposes registry entries; the proposals are DATA, never active
connections. :func:`propose_sources` shape-checks a registry-shaped proposal
document by reusing the existing registry validator (:func:`ariadne.sources.
load_registry` — slugs, known types, ADR-0010 inline-credential rejection),
stores it inert under the project's agent-writable staging area, and reports a
content digest plus the precise locations. No proposed location is opened:
validation is pure YAML parsing and nothing here builds a connection.

:func:`approve_sources` is the separate, human-operated, server-side step
(the packaged skill and every MCP tool are barred from invoking it). It
installs the stored entries into the project's ``ariadne.yaml`` only when the
operator-supplied digest matches the digest re-derived from the STORED
content — so a re-proposal or a hand-edited staging file fails the earlier
approval — and it never overwrites anything: unrelated config keys, existing
registry entries, and their fields survive verbatim (a YAML round-trip drops
comments; the scaffolded template is inert comments). Once installed, the
source is profileable through the same shared connection as every existing
command (``ariadne-profiler --sources ariadne.yaml``) — including its failure:
profiling an approved-but-absent location reports that location honestly.

Slice 2 — :func:`store_upload`, :func:`document_evidence` and
:func:`harness_inputs` prepare the harness's evidence WITHOUT any model: a
bounded upload retains its original bytes and digest in the project-controlled
input area (``data/docs/`` — the operator-configured root, the same directory
init scaffolds for documents); a reference converts through ariadne-ingest's
optional ``[documents]`` converter dispatch and returns as source-linked
evidence — exact resource, sha256 digest, and ONE bounded part of the text,
never claiming a truncated part complete. Reads stay inside what the operator
configured: the human-managed project config (``ariadne.yaml``) carries the
EXACT approved object-store document URIs (``documents.object_store``, S3 —
the specified minimum object-store case) and the allowed local input roots
(``documents.roots``, default ``data/docs``) — never the server environment
or client-request arguments (owner decision 2026-09-24). A client may not
name an unapproved URI or root: traversal, absolute paths outside the roots,
unapproved or credentialed URI references, unreadable files, unsupported
formats and missing converters all fail explicitly BEFORE anything is
fetched, read, written, or served. Approved objects are retrieved with
server-held credentials (DuckDB's blob reader; no client-supplied credential
exists), their original bytes RETAINED with the digest in the project input
area (``data/object-store/``), and converted from that one stable snapshot.
:func:`harness_inputs` bounds the whole batch (an explicit per-call document
count) and adds the deterministic per-source profile — only
``ariadne-authoring approve-sources`` installs registry entries, so the
profile exists only after approval — plus the optional already-approved Seed
Notes (``data/seed_notes.md``); source credentials never appear (the registry
carries env-var NAMES only; connections resolve server-side). A remote
client's local dataset path is not a server path: it is simply an escaping
reference here.

Slice 3 — :func:`submit_bundle` / :func:`review_bundle` (issue #15; spec
"Authoring interface and lifecycle"): the harness's OWN model drafts the whole
bundle (complete Seed Notes, OSI models, OKF pages) and submits it as relative
paths + bodies into ONE dedicated project staging area
(``staging/authoring/bundle/``); the service runs the SAME deterministic
checks the author loop uses (:func:`ariadne.validate` compile/bind/grain plus
``author._finalize_bundle``/``_bundle_errors``), never the server's
OpenAI-compatible completion. Out-of-scope paths, symlinked staging
components, generated ``index.md``/``log.md``, harness-supplied computations,
credentials, and unbounded payloads are refused BEFORE any write, and nothing
is ever written to the served layers. Proposed dataset sources are authorized
FIRST (:func:`_authorize_dataset_sources`): only SELECT/joins over approved
registry identities ever reach ``validate``'s bind/audit — table functions and
direct file/URI scans never execute, and an empty approved registry cannot
validate a bundle. OKF pages are accepted only in the layout the per-type
gate actually checks (one ``.md`` per section, references under
``references/joins/``); credential classes follow the ingest patterns plus
named AWS assignments, never echoing the value. One active proposal per
project persists in ``staging/authoring/bundle-state.json`` with its exact
digests/revision: repairs require the current submission digest, a
stale/competing submission or a changed source registry fails WITHOUT
replacement, an identical retry is idempotent (no attempt reset), and exhausted
validation (3 rounds) stays ``review_needed`` for the human. Submit, the
review snapshot, and digest Promotion share ONE per-project interprocess lock
(:func:`bundle_lock`), so competing CLI processes serialize instead of
corrupting the active proposal, and the staged swap keeps the prior proposal
recoverable across a crash. :func:`review_bundle` returns the inventory,
provenance, errors, the exact reviewed-content digest with bounded bodies, and
the VERIFIED converted-document citations recorded with the proposal — a
service-generated ``citations.json`` manifest inside the staged tree, each
citation server-derived (exact resource, current-snapshot digest, title) from
the operator's document boundary, so the exact review digest binds citation
changes to the reviewed identity the way it binds bodies — it is never a
signoff. Serving is the human-only exact-digest Promotion
(:func:`ariadne.promote.promote_bundle`), which refuses changed, incomplete,
or ``review_needed`` proposals before any served write.

Slice 4 — :class:`AuthoringProject` (issue #34/G2, spec 2026-10-02-0009 §§3–4,
plan §2 "Project storage and authority" + "Authoring call contract"): the
host-configured data project and its Git-backed authoring proposals —
``start_proposal`` / ``read_artifact`` / ``edit_proposal`` returning
JSON-shaped envelopes reusable by CLI/MCP/Agent adapters. This module keeps
the orchestration only: the Git identity/worktree/revision machinery and the
shared credential/payload boundary live in :mod:`ariadne.proposals`, the
layer-specific edits in :mod:`ariadne.authoring_semantic` (model/graph) and
:mod:`ariadne.authoring_context` (page/seed notes), the Git-aware source
proposals/operator approval/measured inputs in :mod:`ariadne.authoring_sources`
(issue #35/G3), and the bounded document/evidence preparation in
:mod:`ariadne.authoring_inputs`.

Slice 5 — :func:`validate_proposal` / :func:`review_proposal` (issue #36/G4,
spec §§3–4 "Validate the effective candidate"/"Review exposes the exact
revision", AC2/4/6, plan §2 rows ``validate_proposal``/``review_proposal``):
validation finalizes the deterministic generated artifacts (the wall-clock-free
:func:`ariadne.context.finalize_candidate`), commits any generated changes,
validates the EXACT final commit — the complete effective project through the
existing schema/page-contract/compile/bind/grain/citation checks against the
operator-APPROVED resolved source identity (the G3 seam) — and stores the
evidence separately under the operator-owned ignored ``.ariadne/validation/``
bound to that commit, the COMPLETE artifact digest (generated/bookkeeping/Seed
Notes bytes included, unlike the legacy served-tree walker), the source
identity, the verified citations and the validator identity. The bounded
repair policy is per-proposal and never reset by creating another commit.
Review is read-only (reading it is never sign-off; admission is G5): exact
revisions, change inventory, bounded effective bodies, citations, the full
check scope and a review digest, with changed candidates or changed document
evidence reported as stale — never as an unchanged validated candidate.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections import Counter
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages; the guarded statement seam's error type
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports] — same

from ariadne import (
    answer_examples,
    authoring_context,
    authoring_inputs,  # noqa: F401 — re-export: the historical seam
    authoring_semantic,
    authoring_sources,
    context,
    execution,
    profiler,
    proposals,
)
from ariadne.author import (
    MAX_ROUNDS,
    _bundle_errors,
    _finalize_bundle,
    _load_frontmatter_meta,
    _mark_review_needed,
    normalize_layer_yaml,
)
from ariadne.authoring_inputs import (  # noqa: F401 — re-export: the historical seam
    EVIDENCE_PART_CHARS,
    MAX_DOCUMENTS_PER_CALL,
    MAX_RAW_EXAMPLES,
    MAX_UPLOAD_BYTES,
    SEED_NOTES_REL,
    _convert_snapshot,
    _document_bytes,
    _evidence_record,
    _fetch_object_bytes,
    _input_root,
    _lstat,
    _project_documents_config,
    _sha256_hex,
    bytes_evidence,
    document_evidence,
    effective_inspection_limits,
    project_inspection_limits,
    store_upload,
)
from ariadne.context import (  # noqa: F401 — the K1 generated-page seam (issue #41)
    _EVIDENCE_SUMMARY_KEYS,
    _canonical_digest,
    build_dataset_page,
    build_table_page,
    candidate_digest,
    confirmation_binding_digest,  # K4 fix pass: the effective identity a confirmation binds
    evidence_counterevidence,  # K4 fix pass: counterevidence named at validation/review
    generated_page_filename,
    mapping_assertion_digest,  # K4 (issue #44): the declaration identity of a mapping
    resolve_term,  # K2 (issue #42): the shared read-only term resolver
    validate_inspection_candidate,
)
from ariadne.render import render
from ariadne.semantic_graph import load_graph
from ariadne.sources import (
    _URI_SCHEME_RE,
    _resolve_against,
    binding_from_record,
    collection_resource,
    load_registry,
    parse_resource,
    resolve_binding,
    table_resource,
    used_profiles,
)
from ariadne.sources import validate_storages as _validate_storages
from ariadne.validate import (
    VALIDATOR_VERSION,
    CheckOutcome,
    _model_entries,
    candidate_scope_digest,
    validate,
    validator_identity,
)

# One pending source proposal per project, in the agent-writable staging area
# (a dedicated subdir: never collides with ad-hoc metric or ingest proposals).
PROPOSAL_REL = Path("staging") / "authoring" / "source-proposal.yaml"


def propose_sources(file: str | Path, *, project: str | Path = ".") -> dict:
    """Validate and store one inert source proposal — sources plus the
    optional top-level ``storages:`` block of named S3 storage profiles (spec
    0025 §5) — and return its digest and the precise proposed locations.
    Raises the registry validator's errors (naming the offending entry) for
    any invalid or credential-carrying proposal. Never opens a location.
    Relative paths are resolved against the project root — the directory of
    the eventual ``ariadne.yaml`` — so a location means the same thing when
    proposed, digested, and (after approval) profiled, whatever directory the
    intake file arrived in."""
    proposal_path = Path(file)
    load_registry(proposal_path)  # reuse the ADR-0010 + spec 0025 validation, verbatim
    entries = _entries(proposal_path)
    storages = _storages(proposal_path)
    base = Path(project).resolve()  # NOT the intake file's directory (spec §1)
    for entry in entries:
        if isinstance(entry.get("path"), str):
            entry["path"] = _resolve_against(base, entry["path"])
    digest = _digest(_identity_payload(entries, storages))
    stored = Path(project) / PROPOSAL_REL
    stored.parent.mkdir(parents=True, exist_ok=True)
    document: dict = {"digest": digest, "sources": entries}
    if storages:
        document["storages"] = storages
    stored.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    result: dict = {"digest": digest, "proposal": str(stored), "sources": entries}
    if storages:
        result["storages"] = storages
    return result


def approve_sources(digest: str, *, project: str | Path = ".") -> dict:
    """Human-only: install the digest-matched pending proposal into the
    project's ``ariadne.yaml`` (append-only, preserving unrelated config).
    Raises ``ValueError`` — before writing anything — for a missing or edited
    proposal, a digest mismatch, or a proposed name that already exists."""
    project = Path(project)
    stored = project / PROPOSAL_REL
    if not stored.is_file():
        raise ValueError(f"no pending source proposal at {stored} — run propose-sources first")
    load_registry(stored)  # revalidate the stored entries before any install
    entries = _entries(stored)
    storages = _storages(stored)
    current = _digest(_identity_payload(entries, storages))
    if current != digest:
        raise ValueError(
            f"digest mismatch: approval is exact-content — the pending proposal "
            f"digest is {current}, not {digest}; review and approve the current digest"
        )
    registry_path = project / "ariadne.yaml"
    if not registry_path.is_file():
        raise ValueError(
            f"no {registry_path} in this project — approval installs into the "
            "configured project's registry"
        )
    doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    existing = doc.get("sources") or []
    if not isinstance(existing, list):
        raise ValueError(f"{registry_path}: 'sources' is not a list")
    taken = {entry.get("name") for entry in existing if isinstance(entry, dict)}
    clashes = [entry["name"] for entry in entries if entry["name"] in taken]
    if clashes:
        raise ValueError(
            f"source name(s) {clashes} already exist in {registry_path} — approval "
            "appends, it never overwrites an existing entry"
        )
    doc["sources"] = [*existing, *entries]
    merged_storages = _merge_storages(doc.get("storages") or {}, storages, registry_path)
    if merged_storages:
        doc["storages"] = merged_storages
    registry_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return {"digest": digest, "registry": str(registry_path), "sources": entries}


def _entries(path: Path) -> list[dict]:
    """The raw ``sources:`` entries of a proposal/registry document, verbatim
    (validation is load_registry's job; these are what the digest binds and
    the install writes)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = doc.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: no 'sources:' entries")
    return entries


def _storages(path: Path) -> dict:
    """The raw ``storages:`` block of a proposal document, verbatim ({} when
    absent) — the profile definitions approval installs alongside entries."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    storages = doc.get("storages") or {}
    if not isinstance(storages, dict):
        raise ValueError(f"{path}: 'storages' is not a mapping")
    return storages


def _identity_payload(entries: list[dict], storages: dict | None) -> list | dict:
    """The legacy digest input: the raw entries unchanged (old proposals keep
    their exact digests), or entries plus the storages block when profiles
    are declared (spec 0025 §5 — hashing only a reference name would drop the
    definitions)."""
    if not storages:
        return entries
    return {"sources": entries, "storages": storages}


def _merge_storages(existing: dict, incoming: dict | None, where: Path) -> dict:
    """Merge a proposal's storage profiles into the registry's block: new
    names append, an identical definition is reused, a conflicting
    replacement refuses before anything is written (spec 0025 §5)."""
    merged = dict(existing)
    incoming_profiles = _validate_storages(incoming, where)
    existing_profiles = _validate_storages(existing, where)
    for name, profile in incoming_profiles.items():
        current = existing_profiles.get(name)
        if current is not None and current.identity() != profile.identity():
            raise ValueError(
                f"{where}: storage profile {name!r} already exists with a DIFFERENT "
                "definition — a conflicting replacement is refused (spec 0025 §5); "
                "nothing was installed"
            )
        merged[name] = profile.identity()
    return merged


def _digest(entries: object) -> str:
    """sha256 over the canonical form of the entries: identity is the exact
    proposed content (whitespace and key order do not matter). The canonical
    form is shared with the Git route's resolved-identity digest
    (:func:`ariadne.authoring_sources.resolved_digest`)."""
    return authoring_sources.resolved_digest(entries)


# --- slice 2 (issue #14, moved to ariadne.authoring_inputs in #35/G3):
# bounded document inputs and source-linked evidence ---
# The measured-evidence implementations were MOVED INTACT to
# :mod:`ariadne.authoring_inputs` (issue #35/G3) so the legacy route here and
# the Git-backed proposal route share ONE implementation; the names stay
# importable from this module (top-of-module re-export above) for their named
# real consumers — tests/test_authoring.py's legacy-route fixtures (the
# documented retained legacy surface, issue #39/G7) and promote.py's digest
# gate (``_digest``/``_registry_sources``/``_tree_digest`` below).


def harness_inputs(
    *,
    project: str | Path = ".",
    documents: Sequence[str] = (),
    part: int = 1,
    sample_rows: int | None = None,
) -> dict:
    """The harness's measured inputs (spec §3), no model anywhere: the
    deterministic per-source profile of the APPROVED registry (only
    approve-sources installs entries — pre-approval the profile is ``None``
    and nothing is opened), source-linked converted evidence for each
    referenced input-area document, and the optional already-approved Seed
    Notes — bounded the same way. The document batch carries an explicit
    count bound so repeated references cannot force an unbounded aggregate
    response. A failing source or document raises naming it; source
    credentials never appear in the response. (The LEGACY route; the
    Git-proposal route is :func:`ariadne.authoring_sources.inputs`.)"""
    project = Path(project)
    documents = list(documents)
    if len(documents) > MAX_DOCUMENTS_PER_CALL:
        raise ValueError(
            f"{len(documents)} documents exceeds the per-call bound of "
            f"{MAX_DOCUMENTS_PER_CALL} — fetch document evidence in bounded "
            "batches (spec §3)"
        )
    profile = None
    registry_path = project / "ariadne.yaml"
    if registry_path.is_file():
        doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict) and doc.get("sources"):  # approved entries only
            profile = profiler.profile(sources_path=registry_path, sample_rows=sample_rows)
    seed_notes = None
    notes_path = project / SEED_NOTES_REL
    if notes_path.is_file():
        # one stable snapshot: digest AND text (ariadne.authoring_inputs)
        seed_notes = bytes_evidence(
            str(notes_path.resolve()), notes_path.name, notes_path.read_bytes(), part=part
        )
    return {
        "project": str(project.resolve()),
        "profile": profile,
        "documents": [
            document_evidence(reference, project=project, part=part) for reference in documents
        ],
        "seed_notes": seed_notes,
    }


# --- slice 3 (issue #15): full-bundle submission and staged review ---

# The one active full-bundle proposal per project: content under a dedicated
# staging dir (never collides with ad-hoc or standalone-ingest proposals),
# persisted state as a sibling file that survives any restart.
AUTHORING_STAGING = Path("authoring")  # under the project staging root
BUNDLE_DIR_REL = AUTHORING_STAGING / "bundle"
BUNDLE_STATE_REL = AUTHORING_STAGING / "bundle-state.json"
BUNDLE_LOCK_REL = AUTHORING_STAGING / "bundle.lock"
BUNDLE_STAGING_REL = Path("staging") / BUNDLE_DIR_REL  # project-relative content dir
BUNDLE_STATE_PATH_REL = Path("staging") / BUNDLE_STATE_REL  # project-relative state file
BUNDLE_DISCARD_NAME = "bundle.discarded"  # crash-recoverable prior proposal

SEED_NOTES_SUBMIT_REL = "data/seed_notes.md"  # the one required non-artifact file
# The service-generated manifest of VERIFIED document citations at the bundle
# root (candidate review P1): outside the documented submission roots, so the
# harness can never submit or overwrite it, ignored by the promotion merge,
# and included in the exact staged-tree digest — citation changes therefore
# change the review digest human Promotion enforces.
CITATIONS_NAME = "citations.json"
# Documented submission roots (spec "Authoring interface and lifecycle"): the
# complete Seed Notes, the OSI models, and OKF pages. index.md/log.md and the
# computation pages are service-generated, so submitting them is refused.
_OKF_SECTIONS = frozenset({"tables", "references", "policies", "metrics", "skills"})
_GENERATED_FILES = frozenset({"index.md", "log.md"})
_HARNESS_LED_BY = "ariadne-authoring:harness-led"  # provenance (spec: name it)

MAX_BUNDLE_FILES = 256  # bounded submission: one demo-scale bundle is ~30 files
MAX_BUNDLE_BYTES = 2 * 1024 * 1024  # bounded payload; large evidence is referenced, not inlined

# Named env-style credential assignments the URL-password rule misses (review
# finding: ``AWS_SECRET_ACCESS_KEY=...``). The value is never echoed; the
# same-line ``=`` keeps prose that merely MENTIONS the variable from matching.
# The pattern and its checks are SHARED with the Git proposal edits (issue #34):
# one implementation lives in ariadne.proposals (check_artifact_content).
_AWS_ASSIGNMENT_RE = proposals._AWS_ASSIGNMENT_RE


def bundle_state_path(staging_root: str | Path) -> Path:
    """Where the active-bundle state lives under a project's staging root."""
    return Path(staging_root) / BUNDLE_STATE_REL


def bundle_staging_dir(staging_root: str | Path) -> Path:
    """The dedicated bundle-content staging dir under a project's staging root."""
    return Path(staging_root) / BUNDLE_DIR_REL


@contextmanager
def bundle_lock(staging_root: str | Path):
    """ONE shared interprocess lock per project, serializing bundle submit,
    the review snapshot, and digest Promotion (spec "Authoring interface and
    lifecycle": competing writers fail without replacement, and a reviewed
    digest always pairs with the staged bytes it was taken from). ``flock(2)``
    on a lock file under the project staging area — POSIX only; the lock is
    released on close/exit, so a crashed holder never wedges the project.
    ponytail: the lock file lives in agent-writable staging, so an agent that
    DELETES it mid-flight could fork the lock domain; move it under an
    operator-owned directory if staging ever turns hostile."""
    lock_path = Path(staging_root) / BUNDLE_LOCK_REL
    entry = _lstat(lock_path)
    if entry is not None and stat.S_ISLNK(entry.st_mode):
        raise ValueError(
            f"{lock_path}: refusing a symlinked bundle lock file — the project "
            "bundle lock stays a plain staging file"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _submission_doc(file: str | Path) -> tuple[list[tuple[str, str]], str | None, list[str]]:
    """Parse a submission document (``{"files": [{path, content}], "documents":
    [reference, ...], "base_digest": ...}`` — the author response contract plus
    the explicit bounded linkage to prepared documents) into (files,
    base_digest or None, document references). Every shape problem is an
    actionable ValueError before anything is written."""
    raw = Path(file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{file}: submission is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list) or not data["files"]:
        raise ValueError(f"{file}: submission needs a non-empty 'files' list")
    files: list[tuple[str, str]] = []
    for entry in data["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError(f"{file}: every files[] entry needs a 'path' string")
        content = entry.get("content")
        if not isinstance(content, str):
            raise ValueError(f"{file}: files[] entry {entry['path']!r} needs 'content'")
        files.append((entry["path"], content))
    base = data.get("base_digest")
    if base is not None and (not isinstance(base, str) or len(base) != 64):
        raise ValueError(f"{file}: 'base_digest' must be a 64-hex digest string")
    documents = data.get("documents", [])
    if not isinstance(documents, list) or not all(
        isinstance(ref, str) and ref for ref in documents
    ):
        raise ValueError(f"{file}: 'documents' must be a list of document reference strings")
    if len(documents) > MAX_DOCUMENTS_PER_CALL:
        raise ValueError(
            f"{file}: {len(documents)} cited documents exceeds the per-call bound of "
            f"{MAX_DOCUMENTS_PER_CALL} — cite document references in bounded batches"
        )
    return files, base, documents


def _check_submission(files: list[tuple[str, str]]) -> None:
    """The pre-write boundary (spec: remotely controlled bytes and relative
    paths; the assets are staging and everything served). Out-of-scope paths,
    generated/computed file names, credentials, and unbounded payloads fail
    BEFORE any write; no served path is ever touched here."""
    if len(files) > MAX_BUNDLE_FILES:
        raise ValueError(
            f"submission carries {len(files)} files, over the bound of {MAX_BUNDLE_FILES}"
        )
    total = sum(len(content.encode("utf-8")) for _, content in files)
    if total > MAX_BUNDLE_BYTES:
        raise ValueError(
            f"submission is {total} bytes, over the {MAX_BUNDLE_BYTES}-byte bound — "
            "reference evidence by resource instead of inlining it"
        )
    seed_notes = 0
    for rel, content in files:
        where = f"files[] entry {rel!r}"
        pure = PurePosixPath(rel)
        if pure.is_absolute() or not pure.parts or rel.startswith("/") or "\\" in rel:
            raise ValueError(f"{where}: only relative POSIX artifact paths are accepted")
        if any(part in ("", ".", "..") for part in pure.parts):
            raise ValueError(f"{where}: path traversal is refused (no ''/'.'/'..' parts)")
        if pure.name in _GENERATED_FILES:
            raise ValueError(
                f"{where}: index.md and log.md are generated by the promotion gate, never submitted"
            )
        if rel == SEED_NOTES_SUBMIT_REL:
            seed_notes += 1
            continue
        parts = pure.parts
        if len(parts) >= 3 and parts[0] == "context_layer":
            section = parts[1]
            if section == "computations":
                raise ValueError(
                    f"{where}: computation pages are generated by the validation pass "
                    "(attestation is service-owned, ADR-0013) — submit tables/references/"
                    "policies/metrics/skills pages"
                )
            # ONLY the layout the per-type bundle gate actually checks is
            # accepted: one .md directly under each section, and reference
            # pages under references/joins/ (ADR-0007's sixth type). Deeper
            # pages are never checked there, so they are refused before any
            # write — they cannot ride along to validation and Promotion.
            if section == "references":
                if len(parts) != 4 or parts[2] != "joins" or pure.suffix != ".md":
                    raise ValueError(
                        f"{where}: reference pages are .md files directly under "
                        "context_layer/references/joins/ (the checked bundle layout)"
                    )
            elif section not in _OKF_SECTIONS or len(parts) != 3 or pure.suffix != ".md":
                raise ValueError(
                    f"{where}: OKF pages are single .md files directly under "
                    "context_layer/{{tables,references/joins,policies,metrics,skills}}/ "
                    "— nested pages are never checked by the per-type bundle gate and "
                    "are refused before any write"
                )
            continue
        if rel == "semantic_layer/graph.yml":
            # Issue #30: the ONE non-model semantic path a remote submission may
            # carry — the cross-file graph (relationships + conformed dimensions)
            # of the source layout. Nothing broader: any other semantic_layer/
            # path outside models/*.yml stays refused.
            continue
        if (
            len(parts) == 3
            and parts[:2] == ("semantic_layer", "models")
            and pure.suffix
            in (
                ".yml",
                ".yaml",
            )
        ):
            continue
        raise ValueError(
            f"{where}: outside the documented submission roots "
            f"({SEED_NOTES_SUBMIT_REL}, semantic_layer/models/*.yml, "
            "semantic_layer/graph.yml, context_layer/"
            "{tables,references,policies,metrics,skills}/)"
        )
    if seed_notes != 1:
        raise ValueError(
            f"the complete proposed Seed Notes are required exactly once as "
            f"{SEED_NOTES_SUBMIT_REL} (got {seed_notes})"
        )
    for rel, content in files:
        # The SHARED pre-write credential boundary (ariadne.proposals), the
        # same one Git proposal edits pass through — bounds and the three
        # credential classes, values never echoed (issue #34).
        proposals.check_artifact_content(f"files[] entry {rel!r}", content)


def _refuse_symlinked_staging(project: Path, rel: Path) -> None:
    """Refuse before any write when a component of the bundle staging path is a
    symlink (a pre-planted link must never redirect staging writes)."""
    path = project
    for part in rel.parts:
        path = path / part
        entry = _lstat(path)
        if entry is not None and stat.S_ISLNK(entry.st_mode):
            raise ValueError(
                f"{path}: refusing a symlinked staging component — staging stays a "
                "plain project directory"
            )


def _current_storage_bindings(project: Path) -> dict:
    """The legacy route's CURRENT effective storage binding (spec 0025 §5,
    AC7): the used profiles' endpoint/region values resolved from the
    environment — non-secret reads only, no approval store, no Git gate.
    A registry without sources or used profiles resolves to ``{}`` (the
    existing empty-registry gates keep their own refusals); a used profile
    with an unset endpoint/region variable raises the explicit prerequisite
    error (the gates refuse naming it, never a silent empty binding)."""
    doc = _registry_doc(project)
    if not doc.get("sources"):
        return {}
    registry = load_registry(project / "ariadne.yaml")
    used = used_profiles(registry)
    if not used:
        return {}
    return {name: resolve_binding(profile).record() for name, profile in used.items()}


def _refuse_changed_bindings(project: Path, state: dict) -> None:
    """The legacy parity gate (spec 0025 §5/AC7): a bundle proposal validated
    under one effective endpoint never retries idempotently, reviews or
    Promotes under another — the recorded binding must still be the current
    environment's. Legacy human gates stay distinct: no approval record is
    created or consulted."""
    current = _current_storage_bindings(project)
    if current != (state.get("storage_bindings") or {}):
        raise ValueError(
            "the effective storage binding changed while this bundle proposal was "
            "active (spec 0025 §5: it was validated under a different endpoint) — "
            "re-profile and resubmit under the current binding; no agent retry, "
            "review or promotion reuses the old validation"
        )


def _registry_sources(project: Path) -> list:
    """The APPROVED registry entries (the bundle's source identity), [] when the
    project has none; malformed config is an explicit error."""
    return _registry_doc(project).get("sources") or []


def _registry_doc(project: Path) -> dict:
    """The approved registry document — ``sources:`` plus the optional
    ``storages:`` block (spec 0025 §5) — as one coherent unit; malformed
    config is an explicit error."""
    registry_path = project / "ariadne.yaml"
    if not registry_path.is_file():
        return {}
    doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    sources = doc.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError(f"{registry_path}: 'sources' is not a list")
    return doc


def _registry_identity_payload(project: Path) -> list | dict:
    """The bundle gates' digest input: the raw entries alone when no storage
    profiles are declared (old proposals keep their exact digests), or the
    entries PLUS the storages block — so a registry change to either block
    invalidates an active bundle proposal (spec 0025 §5: never hash only a
    reference name)."""
    doc = _registry_doc(project)
    entries = doc.get("sources") or []
    storages = doc.get("storages") or {}
    if not isinstance(storages, dict):
        raise ValueError(f"{project / 'ariadne.yaml'}: 'storages' is not a mapping")
    return _identity_payload(entries, storages)


def _citation_record(reference: str, project: Path) -> dict:
    """One VERIFIED document citation (candidate review P1): the reference is
    checked at the operator's document boundary, the digest taken from the
    CURRENT snapshot bytes, AND conversion verified from that SAME snapshot
    through the exact dispatch :func:`document_evidence` uses — an unsupported
    format or a missing/failing converter is refused here (spec §2–3), so a
    VERIFIED converted-document citation can never exist for bytes that
    ``inputs`` could not convert. The converted body is verified, not stored;
    the resource/title/digest triple is server-derived, never copied from
    client-supplied citation strings."""
    resource, title, data = _document_bytes(reference, project)
    _convert_snapshot(data, Path(title).suffix, display=title)  # verification only
    return {"resource": resource, "title": title, "digest": _sha256_hex(data)}


def _staged_citations(bundle_dir: Path) -> list:
    """The verified citations recorded with the staged proposal — read from
    the service-generated manifest INSIDE the staged tree, so what review
    returns is exactly what the review digest covers. A proposal staged before
    citations existed cites nothing; an unreadable or malformed manifest needs
    human resolution, never an agent reset (a hand-edited manifest already
    fails the staged-tree coherence check first)."""
    manifest = bundle_dir / CITATIONS_NAME
    if not manifest.is_file():
        return []
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{manifest}: unreadable citations manifest ({exc}) — this needs human "
            "resolution, not an agent reset"
        ) from None
    citations = doc.get("documents") if isinstance(doc, dict) else None
    if not isinstance(citations, list):
        raise ValueError(
            f"{manifest}: malformed citations manifest — this needs human resolution, "
            "not an agent reset"
        )
    return citations


def _submission_digest(
    files: list[tuple[str, str]], documents: list[str], citations: list[dict]
) -> str:
    """sha256 over the canonical submitted content INCLUDING the server-verified
    citation triples (spec §25/§34-style source identity, spec §3): identical
    bytes stay idempotent, but changed current-snapshot bytes change the
    proposal identity — a same-reference retry can never silently reuse the
    old staged citations and review digest."""
    canonical = json.dumps(
        {"citations": citations, "documents": list(documents), "files": sorted(files)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tree_digest(root: Path) -> str:
    """sha256 over every file under ``root`` (path + content hash, canonical
    order): the EXACT staged content a human reviews and Promotion enforces."""
    entries = [
        (path.relative_to(root).as_posix(), _sha256_hex(path.read_bytes()))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authorize_dataset_sources(staging: Path, approved: set[str]) -> None:
    """The source-access boundary BEFORE any bind/audit execution (spec
    "Evidence and source-access boundary" §1: no profiling or query opens a
    location outside the approved registry). Remotely authored dataset sources
    and field/metric expressions may reference ONLY approved registry
    identities: every table the compiled SQL touches is walked over the real
    sqlglot AST of the rendered model — table functions (``read_text``,
    ``read_parquet``, ...), direct file/URI scans, unqualified tables, and
    references outside the approved registry names are refused BEFORE
    ``validate`` binds or executes anything. With an empty approved registry
    nothing is approvable, so a full bundle can never be validated by the
    compile-only path."""
    for name, envelope in _model_entries(staging):
        model = envelope["semantic_model"][0]
        if isinstance(model, dict) and len(model.get("datasets") or []) > 1:
            # Fail closed (mf-t1 review F1): render-based authorization walks one
            # dataset per envelope, so a multi-dataset (domain-layout) model could
            # skip it while a graph-aware validator binds its sources. Refused
            # here until authorization understands the normalized graph.
            raise ValueError(
                f"model '{name}': multi-dataset (domain-layout) models are refused "
                "at the source-access boundary until authorization understands the "
                "normalized graph — submit one dataset per model"
            )
        try:
            rendered = render(envelope)
        except Exception:  # RenderError et al.: the compile gate owns the error
            continue  # a bundle with compile errors never reaches bind/audit
        try:
            tree = sqlglot.parse_one(rendered, dialect="duckdb")
        except Exception:
            continue  # render() re-parses its output; unreachable in practice
        ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
        names = ", ".join(sorted(approved)) or "none approved yet"
        for table in tree.find_all(exp.Table):
            this = table.this
            if not isinstance(this, exp.Identifier):
                # a table FUNCTION in FROM (read_parquet('...'), read_text('...')):
                # approved access goes through registry views, never raw scans
                raise ValueError(
                    f"model '{name}': the dataset source uses the table function "
                    f"{this.name or type(this).__name__}(...) — only SELECT/joins over "
                    f"approved registry tables ({names}) enter validation; raw scans "
                    "of server files or object URIs are refused before any execution"
                )
            ref = table.sql(dialect="duckdb")
            if table.catalog or table.db:  # qualified: the leftmost part is the identity
                if (table.catalog or table.db) not in approved:
                    raise ValueError(
                        f"model '{name}': {ref} is not an approved source registry "
                        f"identity (approved: {names}) — validation never opens "
                        "locations outside the approved registry"
                    )
            elif table.name in ctes:
                continue  # a WITH-clause reference; its defining statement is walked too
            elif "/" in table.name or _URI_SCHEME_RE.match(table.name):
                raise ValueError(
                    f"model '{name}': the dataset source scans {table.name!r} directly "
                    "— only SELECT/joins over approved registry tables enter validation; "
                    "direct file/URI scans are refused before any execution"
                )
            else:
                raise ValueError(
                    f"model '{name}': table '{table.name}' is unqualified — qualify "
                    f"tables with an approved source name ({names})"
                )


def _load_bundle_state(project: Path) -> dict | None:
    """The persisted active-proposal state, or None when no proposal exists.
    A corrupt/non-regular state file is a human-resolution failure, never a reset."""
    state_path = project / BUNDLE_STATE_PATH_REL
    entry = _lstat(state_path)
    if entry is None:
        return None
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"{state_path}: refusing a non-regular bundle-state file — inspect the "
            "project staging area"
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{state_path}: unreadable bundle proposal state ({exc}) — this needs "
            "human resolution, not an agent reset"
        ) from None
    if not isinstance(state, dict) or not state.get("submission_digest"):
        raise ValueError(
            f"{state_path}: malformed bundle proposal state — this needs human "
            "resolution, not an agent reset"
        )
    return state


# The shared human-recovery instructions for an interrupted transition (the
# owner's fail-closed decision): name every copy, forbid any agent reset, and
# never offer a command that silently deletes evidence.
_CRASH_HUMAN_RESOLUTION = (
    " — interrupted bundle transition, human resolution required: KEEP both copies "
    "(staging/authoring/bundle and staging/authoring/bundle.discarded) and "
    "staging/authoring/bundle-state.json, compare them, copy out anything to keep, "
    "and remove the leftover directory by hand to resume agent authoring; no agent "
    "command resets or deletes any of them"
)


def _refuse_incoherent_staging(project: Path, state: dict | None) -> None:
    """The owner's fail-closed crash-recovery decision (issue #15 surviving
    P1): after an interrupted transition the staged bundle and the persisted
    state can disagree, and the prior safe proposal may survive ONLY in
    ``bundle.discarded``. Every agent retry, replace, and review is refused
    until a human resolves it — no auto-restore, no silent reset; both copies
    and the state stay exactly as the crash left them."""
    bundle_dir = project / BUNDLE_STAGING_REL
    discarded = bundle_dir.parent / BUNDLE_DISCARD_NAME
    if _lstat(discarded) is not None:
        raise ValueError(
            f"{discarded}: a retained prior-proposal copy marks an interrupted transition"
            + _CRASH_HUMAN_RESOLUTION
        )
    if state is None:
        if bundle_dir.exists():
            raise ValueError(
                f"{bundle_dir}: staged bundle content exists with no bundle-state.json"
                + _CRASH_HUMAN_RESOLUTION
            )
        return
    if not bundle_dir.is_dir():
        raise ValueError(
            f"the bundle proposal state exists but its staging is gone ({bundle_dir})"
            + _CRASH_HUMAN_RESOLUTION
        )
    tree = _tree_digest(bundle_dir)
    if tree != state.get("digest"):
        raise ValueError(
            "the staged bundle no longer matches the recorded proposal state "
            f"(staged {tree} != recorded {state.get('digest')})" + _CRASH_HUMAN_RESOLUTION
        )


def _fsync_path(path: Path) -> None:
    """Sync one file or directory entry to stable storage (POSIX service).
    Opened read-only — ``fsync(2)`` flushes the data/directory entries
    regardless — and any ``OSError`` PROPAGATES so the transition fails closed
    before the prior proposal copy is removed (issue #15 review P1)."""
    proposals._fsync_path(path)


def _fsync_tree(root: Path) -> None:
    """Make a staged tree durable: every file's data, then every directory's
    entries deepest-first (a parent synced before its children's entries could
    miss them on some filesystems), ending with the staged root itself — its
    own top-level entries are persisted only by fsyncing the root, never by a
    descendant's sync (issue #15 review P1)."""
    entries = sorted(root.rglob("*"))
    for path in entries:
        if path.is_file():
            _fsync_path(path)
    for path in sorted(
        (p for p in entries if p.is_dir()), key=lambda p: len(p.parts), reverse=True
    ):
        _fsync_path(path)
    _fsync_path(root)  # root's own entries, last (after its descendants)


def _store_bundle_state(project: Path, state: dict) -> None:
    """Persist the proposal state atomically (tmp + os.replace) and DURABLY
    (issue #15 review P1): the file data is synced BEFORE the rename and the
    containing directory entry afterwards, so a power interruption cannot
    recover a stale or empty state file next to the bundle it must describe."""
    state_path = project / BUNDLE_STATE_PATH_REL
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, state_path)
    _fsync_path(state_path.parent)


def _state_view(state: dict) -> dict:
    """The common submission/review response shape (never a signoff). ``digest``
    is the submission digest (repair chaining / idempotency); callers add the
    exact reviewed-content digest under their own named key."""
    return {
        "digest": state["submission_digest"],
        "revision": state["revision"],
        "attempts": state["attempts"],
        "status": state["status"],
        "errors": state.get("errors") or [],
        "validation": state.get("validation"),
        "provenance": state["provenance"],
        "sources": state.get("sources") or [],
        "project": state["project"],
        "staging": state["staging"],
    }


def _graph_citation_errors(staging: Path) -> list[str]:
    """Issue #30: NEW multi-fact admission requires cited context — every
    metric of the admitted graph carries a staged ``context_layer/metrics/``
    page whose ``sources`` cite at least one ``policies/`` page that RESOLVES
    inside the served Policy directory (the runtime's containment contract —
    mf-t5 fix F3). A missing or broken cited page fails the admission: an
    uncited definition can never become a governed multi-fact answer. Only the
    cross-file graph triggers this (the multi-fact admission form; the
    multi-dataset domain layout is already refused at the source boundary) —
    legacy single-dataset bundles keep the established bundle gate."""
    if not (staging / "semantic_layer" / "graph.yml").is_file():
        return []
    try:
        graph = load_graph(staging / "semantic_layer")
    except Exception:
        return []  # the validator's graph diagnostics already failed the bundle
    context = staging / "context_layer"
    errors: list[str] = []
    for name in sorted(graph.metrics):
        page = context / "metrics" / f"{name}.md"
        rel = f"context_layer/metrics/{name}.md"
        if not page.is_file():
            errors.append(
                f"{rel}: multi-fact admission requires a cited metric page for every "
                f"graph metric — '{name}' has none (issue #30); an uncited definition "
                "cannot become a governed multi-fact answer"
            )
            continue
        try:
            meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{rel}: frontmatter is not valid YAML: {exc}")
            continue
        refs = [
            str(source.get("resource") if isinstance(source, dict) else source or "")
            for source in meta.get("sources") or []
        ]
        cited = [ref for ref in refs if ref.startswith("policies/")]
        if not cited:
            errors.append(
                f"{rel}: multi-fact admission must cite at least one governing policies/... page"
            )
        for ref in cited:
            # mf-t5 fix F3: resolve against — and require containment within —
            # the Policy directory, exactly the runtime's served contract
            # (runtime._metric_context): a 'policies/../…' traversal that stays
            # inside context_layer/ would admit a citation whose served
            # context collapses to null while the answer stays governed.
            body = (context / ref).resolve()
            policies_root = (context / "policies").resolve()
            if not body.is_relative_to(policies_root) or not body.is_file():
                errors.append(
                    f"{rel}: cited policy '{ref}' does not resolve inside "
                    "context_layer/policies/ — a citation outside the Policy "
                    "directory fails multi-fact admission"
                )
    return errors


def _validation_scope(result) -> dict | None:
    """The persisted full technical validation scope (issue #30): the
    digest-bound report of the checks the bundle actually passed, carried in
    the proposal state so human Promotion can bind and record it — never a
    free-form ``validated: true`` label."""
    report = result.report
    if report is None:
        return None
    return {
        "scope": report.scope,
        "digest": report.digest,
        "validator_version": report.validator_version,
        "registry_digest": report.registry_digest,
        "registry_label": report.registry_label,
        "files": list(report.files),
        "checks": [
            {"name": check.name, "outcome": check.outcome, "detail": check.detail}
            for check in report.checks
        ],
    }


def submit_bundle(
    file: str | Path, *, project: str | Path = ".", base_digest: str | None = None
) -> dict:
    """Accept one complete harness-owned-model bundle and run the SAME
    deterministic author checks on it (never the server's completion endpoint):
    compile/bind/grain via :func:`ariadne.validate` against the project's
    approved registry, then the ADR-0007 finalize passes (metric enrichment,
    computation generation with ``attestation: pending``, lifecycle stamping
    naming harness-led provenance) and the per-type bundle gate. Errors are
    actionable and repair the SAME proposal with the returned digest; at most
    three rounds, then the staged files stay ``review_needed`` for the human.
    Nothing is written to the served layers, ever. An interrupted transition
    (a retained prior copy, or state/staging disagreement) is refused for
    human resolution with every copy kept — never auto-reset."""
    project = Path(project)
    files, doc_base, documents = _submission_doc(file)
    base = base_digest or doc_base
    _check_submission(files)  # bounds/paths/credentials — BEFORE any write
    _refuse_symlinked_staging(project, BUNDLE_STAGING_REL)  # same
    # Every requested citation is verified at the operator's document boundary
    # against the CURRENT snapshot bytes BEFORE anything is staged (candidate
    # review P1): an explicit per-submission linkage, never a project-global
    # last-inputs list, and the recorded triples below are server-derived.
    citations = [_citation_record(reference, project) for reference in documents]

    sources = _registry_sources(project)
    sources_digest = _digest(_registry_identity_payload(project))
    storage_bindings = _current_storage_bindings(project)
    submission = _submission_digest(files, documents, citations)
    # ONE interprocess lock per project: the state read, the staged swap, and
    # the state store are a single critical section, so two CLI processes with
    # the same base digest cannot both replace the active proposal and no
    # digest ever pairs with bytes it was not taken from.
    with bundle_lock(project / "staging"):
        state = _load_bundle_state(project)
        # The early coherence guard (owner fail-closed decision) comes BEFORE
        # the idempotent/stale/new-writer branches: a retained discard or a
        # state/staging disagreement marks an interrupted transition, and NO
        # agent retry — not even an identical one — may run on top of it.
        _refuse_incoherent_staging(project, state)
        if state is not None and state.get("status") != "promoted":
            if sources_digest != state.get("sources_digest"):
                raise ValueError(
                    "the approved source registry changed while this bundle proposal was "
                    "active — the proposal is invalidated and needs human resolution; "
                    "no replacement was made"
                )
            # spec 0025 §5/AC7: even an IDENTICAL submission never reuses a
            # validation taken under a different effective endpoint.
            _refuse_changed_bindings(project, state)
            if submission == state["submission_digest"]:
                view = _state_view(state)
                if (project / BUNDLE_STAGING_REL).is_dir():
                    view["review_digest"] = state.get("digest")  # unchanged staging
                    view["documents"] = _staged_citations(project / BUNDLE_STAGING_REL)
                return view  # idempotent retry: no writes, no attempt reset
            if state["attempts"] >= MAX_ROUNDS or state["status"] == "review_needed":
                raise ValueError(
                    "the active bundle proposal exhausted its three authoring rounds and "
                    "remains review_needed — this needs human resolution; no replacement "
                    "was made"
                )
            if base != state["submission_digest"]:
                if citations != _staged_citations(project / BUNDLE_STAGING_REL):
                    raise ValueError(
                        "base-digest mismatch: the cited documents changed since this "
                        "proposal was staged (the server-verified citation digest "
                        "differs) — re-fetch inputs, then retry with the CURRENT "
                        "submission digest as --base-digest; no replacement was made"
                    )
                raise ValueError(
                    "base-digest mismatch: the active proposal moved on (stale or competing "
                    "submission) — repairs need the CURRENT submission digest; no "
                    "replacement was made"
                )
        elif state is not None and base is not None:
            raise ValueError(
                "no active proposal to repair (the previous bundle was promoted) — submit "
                "without --base-digest"
            )

        revision = (state["revision"] if state is not None else 0) + 1
        attempts = (state["attempts"] if state is not None else 0) + 1

        # Stage the exact submission into a fresh tree, validate, finalize — the
        # served layers are never a target and the old proposal survives any crash
        # before the atomic swap (a failed round never replaces prior staging).
        staging_root = project / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=staging_root, prefix="bundle-"))
        try:
            for rel, content in files:
                target = tmp / Path(*PurePosixPath(rel).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if "semantic_layer" in target.parts and target.suffix in (".yml", ".yaml"):
                    # issue #31: readable block scalars for multi-line sources
                    content = normalize_layer_yaml(content)
                target.write_text(content, encoding="utf-8")
            # Source authorization comes BEFORE any bind/audit: nothing outside
            # the approved registry identities is ever opened or executed here.
            _authorize_dataset_sources(tmp, {str(entry.get("name")) for entry in sources})
            # spec 0025 §§3–5/AC7 (fix blocker 2): the audit MEASURES under the
            # binding captured for the state — the captured endpoint/region
            # values are FROZEN into the audit registry, so an environment
            # change between capture and validation can never make validation
            # measure one endpoint while recording another. Legacy human gates
            # stay distinct: no approval record is created or consulted.
            audit_registry = None
            if sources:
                audit_registry = load_registry(project / "ariadne.yaml")
                audit_registry.bindings = {
                    name: binding_from_record(name, record)
                    for name, record in storage_bindings.items()
                } or None
            result = (
                validate(
                    tmp,
                    sources_path=(project / "ariadne.yaml") if sources else None,
                    registry=audit_registry,
                )
                if sources
                else validate(tmp)  # compile-only: an empty project has no audit connection
            )
            errors = list(result.errors)
            if not errors:
                try:
                    _finalize_bundle(tmp, generated_by=_HARNESS_LED_BY, attester=None)
                except Exception as exc:
                    errors = [f"authored bundle violates the OKF frontmatter contract: {exc}"]
                else:
                    errors = _bundle_errors(tmp) + _graph_citation_errors(tmp)
            if errors and attempts >= MAX_ROUNDS:
                _mark_review_needed(tmp, errors)
            status = (
                "review_needed"
                if (errors and attempts >= MAX_ROUNDS)
                else ("invalid" if errors else "validated")
            )
            # The verified citations ride WITH the staged proposal as one
            # service-generated manifest at the bundle root (outside the
            # documented submission roots, so the harness can never submit or
            # overwrite it, and never part of what Promotion serves): because
            # the manifest lives in the staged tree, the EXACT review digest
            # binds citation changes to the reviewed identity exactly as it
            # binds bodies (candidate review P1). No document contents are
            # duplicated — only the verified resource/title/digest triples.
            (tmp / CITATIONS_NAME).write_text(
                json.dumps({"documents": citations}, sort_keys=True) + "\n", encoding="utf-8"
            )
            # Crash-recoverable transition (owner fail-closed decision): the
            # coherence guard above proved no retained discard exists, the prior
            # proposal is RENAMED aside (never deleted first), the fresh tree
            # swaps in atomically, and the state is stored durably BEFORE the
            # superseded copy is dropped — a crash anywhere in between leaves an
            # incoherent layout every gate refuses until a human resolves it.
            # The ordered durability barrier (issue #15 review P1): B's staged
            # file data and directory entries are synced BEFORE the renames,
            # then both sides of the cross-directory rename (the staging root
            # loses the tmp entry; authoring/ gains bundle — initial proposals
            # rename across the same two directories) — so a power interruption
            # cannot recover B as a partial tree.
            bundle_dir = project / BUNDLE_STAGING_REL
            discarded = bundle_dir.parent / BUNDLE_DISCARD_NAME
            bundle_dir.parent.mkdir(parents=True, exist_ok=True)
            _fsync_tree(tmp)
            if bundle_dir.is_dir():
                os.replace(bundle_dir, discarded)  # keep the safe prior proposal
            os.replace(tmp, bundle_dir)
            _fsync_path(staging_root)
            _fsync_path(bundle_dir.parent)
        finally:
            if tmp.is_dir() and tmp.parent.exists():
                shutil.rmtree(tmp, ignore_errors=True)

        new_state = {
            "submission_digest": submission,
            "digest": _tree_digest(project / BUNDLE_STAGING_REL),
            "revision": revision,
            "attempts": attempts,
            "status": status,
            "errors": errors,
            "validation": _validation_scope(result),
            "provenance": {
                "mode": "harness-led",
                "generated_by": _HARNESS_LED_BY,
                "submitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            "sources": sources,
            "sources_digest": sources_digest,
            "storage_bindings": storage_bindings,
            "project": str(project.resolve()),
            "staging": str((project / BUNDLE_STAGING_REL).resolve()),
        }
        _store_bundle_state(project, new_state)
        # The superseded copy is dropped ONLY here — after the replacement state
        # is durable and INSIDE the same lock (issue #15 surviving P1: a cleanup
        # after the lock is released can interleave with the next writer's swap
        # and remove its retained copy). A cleanup failure reports the retained
        # copy instead of hiding it; the coherence guard then fails closed for
        # the human on the next operation.
        retained_note = None
        if discarded.exists():
            try:
                shutil.rmtree(discarded)
            except OSError as exc:
                retained_note = (
                    f"{discarded}: the superseded prior proposal could not be removed "
                    f"({exc}) — it is RETAINED: resolve it by hand; agent operations "
                    "stay blocked while it exists"
                )
        view = _state_view(new_state)
        view["review_digest"] = new_state["digest"]
        view["documents"] = citations
        if retained_note is not None:
            view["retained_prior_copy"] = retained_note
        return view


def review_bundle(*, project: str | Path = ".", part: int = 1) -> dict:
    """The staged review (spec: readable, never a signoff): inventory, source
    identities, the VERIFIED converted-document citations recorded with the
    proposal (spec "Authoring interface and lifecycle": review returns
    converted-document citations), provenance, validation state, the exact
    reviewed-content digest, and every proposed body — Seed Notes and
    artifacts — in bounded parts. The snapshot (bodies, citations, AND digest)
    is taken under the project bundle lock, so the returned digest always
    corresponds to the returned bodies and citations even while another writer
    submits concurrently."""
    project = Path(project)
    with bundle_lock(project / "staging"):
        state = _load_bundle_state(project)
        if state is None:
            raise ValueError(
                f"no active bundle proposal under {project / BUNDLE_STAGING_REL} — submit first"
            )
        # The SAME fail-closed coherence rule as submit (owner crash-recovery
        # decision): a review never reports a readable proposal out of an
        # interrupted transition, and never touches the retained copies.
        _refuse_incoherent_staging(project, state)
        # Spec "Evidence and source-access boundary" §1: a source change while
        # a bundle proposal is active invalidates it. Review refuses the same
        # way submission and Promotion already do — BEFORE any body or status
        # is returned — so it can never describe a source-invalidated proposal
        # as validated (candidate review P2). Nothing is written: the original
        # staging and state stay untouched for the human.
        if _digest(_registry_identity_payload(project)) != state.get("sources_digest"):
            raise ValueError(
                "the approved source registry changed while this bundle proposal was "
                "active — the proposal is invalidated and needs re-profiling and "
                "resubmission; review is refused, nothing was written or served"
            )
        # spec 0025 §5/AC7: review never presents a validation taken under a
        # different effective endpoint as current — same refusal as submit and
        # Promotion, before any body or status is returned.
        _refuse_changed_bindings(project, state)
        bundle_dir = project / BUNDLE_STAGING_REL
        bodies = []
        for path in sorted(p for p in bundle_dir.rglob("*") if p.is_file()):
            if path.relative_to(bundle_dir).as_posix() == CITATIONS_NAME:
                continue  # surfaced as the verified document citations below
            data = path.read_bytes()  # one stable snapshot: digest AND text
            bodies.append(
                _evidence_record(
                    path.relative_to(bundle_dir).as_posix(),
                    path.name,
                    _sha256_hex(data),
                    data.decode("utf-8", errors="replace"),
                    part=part,
                    part_chars=EVIDENCE_PART_CHARS,
                )
            )
        # The headline digest is the EXACT staged content a human reviewed and
        # Promotion enforces; the chaining digest stays available for repairs.
        tree = _tree_digest(bundle_dir)
        view = _state_view(state)
        view["digest"] = tree
        view["submission_digest"] = state["submission_digest"]
        view["documents"] = _staged_citations(bundle_dir)  # covered by that digest
        view["files"] = bodies
    return view


# --- slice 4 (issue #34/G2): Git-backed authoring proposal orchestration ---

# The discriminated edit contract (plan §2): one COMPLETE artifact per edit,
# routed to its layer-specific resolver. Sources are deliberately absent —
# typed source proposals are a later slice (G3), so a source-shaped edit is
# refused cleanly instead of being smuggled through a file write.
_LAYER_EDITORS = {
    "model": authoring_semantic,
    "graph": authoring_semantic,
    "page": authoring_context,
    "seed_notes": authoring_context,
}
EDIT_KINDS = tuple(sorted(_LAYER_EDITORS))


class AuthoringProject:
    """One host-configured data project and its Git-backed authoring proposals
    (spec 2026-10-02-0009 §3–4, plan §2). Callers address system-generated
    proposal IDs and typed artifact identities within this fixed project —
    never repository/worktree roots, operational state files or arbitrary
    filesystem paths. Every method returns a JSON-shaped envelope reusable by
    the CLI, MCP and Agent adapters; every failure is an explicit, actionable
    error that preserves the worktree, history and evidence.

    This slice (G2) owns proposal lifecycle and complete artifact edits;
    ``validate_proposal``/``review_proposal`` are G4. Source proposals,
    operator approval and measured inputs are G3 (issue #35), routed through
    :mod:`ariadne.authoring_sources` (``propose_sources``/``approve_sources``/
    ``inputs``) and :mod:`ariadne.authoring_inputs` (``upload_document``).
    """

    def __init__(self, project: str | Path = "."):
        self.project = Path(project)

    def start_proposal(self, base_revision: str | None = None) -> dict:
        """Start one isolated proposal: a system-generated ID, its branch and
        worktree (derived, never caller-supplied), from the optional known base
        revision or the current one; a repository with no commits yet gets its
        human-created initial artifact revision first. Returns
        ``{proposal, base_revision, candidate_revision}``."""
        return proposals.start_proposal(self.project, base_revision=base_revision)

    def read_artifact(self, proposal: str, identity: dict, *, part: int = 1) -> dict:
        """Read one artifact of the proposal's current candidate revision —
        inherited from the base when never edited — addressed by a typed
        identity (``{kind: model, name}``, ``{kind: graph}``,
        ``{kind: page, section, name}``, ``{kind: seed_notes}``), in bounded
        parts. Returns ``{proposal, revision, path, content, part, parts,
        chars, complete}`` or a specific missing-artifact error."""
        if not isinstance(identity, dict) or identity.get("kind") not in _LAYER_EDITORS:
            got = identity.get("kind") if isinstance(identity, dict) else identity
            raise ValueError(
                f"an artifact identity is a typed object with kind one of {EDIT_KINDS}, got {got!r}"
            )
        rel = _LAYER_EDITORS[identity["kind"]].resolve_identity(identity)
        return proposals.read_artifact(self.project, proposal, rel, part=part)

    def edit_proposal(self, proposal: str, expected_revision: str, edit: dict) -> dict:
        """Apply one complete artifact edit — a discriminated JSON object
        (``{kind: model, name, content}``, ``{kind: graph, content}``,
        ``{kind: page, section, name, content}``, ``{kind: seed_notes,
        content}``) — to the proposal, requiring the expected candidate
        revision (stale or competing writers are refused before any write; an
        identical edit at the current revision is a no-op). Returns
        ``{proposal, revision, changed, path}``."""
        if not isinstance(edit, dict) or edit.get("kind") not in _LAYER_EDITORS:
            got = edit.get("kind") if isinstance(edit, dict) else edit
            raise ValueError(
                "an edit is a discriminated JSON object with kind one of "
                f"{EDIT_KINDS} (typed source proposals arrive through the "
                f"propose_sources operation), got kind {got!r}"
            )
        rel, content = _LAYER_EDITORS[edit["kind"]].resolve_edit(edit)
        return proposals.edit_proposal(self.project, proposal, expected_revision, rel, content)

    # ------------------- G3 (issue #35): sources, approval, measured inputs

    def propose_sources(
        self,
        proposal: str,
        expected_revision: str,
        sources: list[dict] | tuple[dict, ...],
        storages: dict | None = None,
    ) -> dict:
        """Append validated typed source entries — plus optional named storage
        profile definitions (spec 0025 §5) — to the candidate's registry
        (``ariadne.yaml``) through the revision-checked edit seam and return
        ``{proposal, revision, changed, source_digest, sources}`` — the digest
        of the candidate's full RESOLVED identity (paths resolved against the
        host project root) plus the precise resolved locations. Inert data:
        nothing is opened, and the candidate cannot grant itself approval."""
        return authoring_sources.propose_sources(
            self.project, proposal, expected_revision, sources, storages
        )

    def approve_sources(self, proposal: str, revision: str, source_digest: str) -> dict:
        """HUMAN-ONLY (the CLI command; never an MCP/Agent tool): record the
        operator's permission for the EXACT resolved source identity of the
        proposal's current candidate revision, outside Git artifacts under
        ``.ariadne/source-approvals.json`` — without editing the
        already-committed candidate."""
        return authoring_sources.approve_sources(self.project, proposal, revision, source_digest)

    def inputs(
        self,
        proposal: str,
        *,
        documents: Sequence[str] = (),
        part: int = 1,
        sample_rows: int | None = None,
    ) -> dict:
        """The proposal's measured inputs: the profile of the APPROVED
        resolved registry identity (an unapproved or changed entry is an
        explicit error and never opens anything), converted evidence for the
        referenced documents inside the operator's host-root document
        boundary, and the candidate's Seed Notes evidence — bounded, with
        stable digests, from the recorded candidate revision."""
        return authoring_sources.inputs(
            self.project, proposal, documents=list(documents), part=part, sample_rows=sample_rows
        )

    def upload_document(self, name: str, data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> dict:
        """The existing bounded upload contract, under the operator input
        area of the fixed project (never a Git artifact): retain the original
        bytes and return the stable identity ``{resource, digest}``."""
        return store_upload(name, data, project=self.project, max_bytes=max_bytes)

    # ----------------------- G4 (issue #36): validate and review the candidate

    def validate_proposal(self, proposal: str, expected_revision: str) -> dict:
        """Validate the proposal's effective candidate at its EXACT final
        revision: finalize the deterministic generated artifacts, commit any
        generated changes, then run the complete check stack — existing
        schema/compile/bind/grain/relationship audits over the approved source
        identity plus the page-contract and citation gates — against the
        materialized final commit (never the earlier input commit). Returns
        that revision with the report/errors; the evidence is stored separately
        under ``.ariadne/validation/``. Validation is not admission (G5)."""
        return validate_proposal(self.project, proposal, expected_revision)

    def review_proposal(self, proposal: str, *, part: int = 1) -> dict:
        """Read the proposal's candidate (read-only; reading is never
        sign-off): current/base revisions, change inventory, bounded effective
        bodies, citations, the validation report with its full check scope and
        a review digest binding the exact reviewed identity."""
        return review_proposal(self.project, proposal, part=part)

    # ------------- K1 (issue #41): explicit physical schema refresh

    def refresh_schema(
        self, proposal: str, expected_revision: str, assets: list[dict] | tuple[dict, ...]
    ) -> dict:
        """Regenerate the core-owned physical schema facts of an EXPLICIT
        catalog asset list inside the selected proposal (plan §2
        ``refresh_schema``, spec 0010 §4): reads go through the
        operator-APPROVED resolved source identity only, writes are
        revision-checked complete page edits, authored summary/column meaning
        is preserved for identical column identity/type (removed or
        type-changed columns keep their old meaning as reviewable history,
        never a rename guess), and an identical refresh against identical
        inputs is a no-op (the candidate revision does not move). Returns the
        resulting revision, the generated page identities and the schema-change
        flags. Refresh is never admission (K4 owns that)."""
        return refresh_schema(self.project, proposal, expected_revision, assets)

    def resolve_term(self, proposal: str, request: str | dict, *, part: int = 1) -> dict:
        """Resolve one shared business term or exact ``{resource, column}``
        field lookup against an EXPLICITLY selected proposal's current
        candidate revision (plan §2 ``resolve_term`` row, spec 0010 §6):
        read-only — the candidate is materialized from the exact commit, never
        a mutable worktree, and the response keeps the candidate identity
        (proposal + revision + ``candidate: true``) visible beside the shared
        resolver envelope (:func:`ariadne.context.resolve_term`). Authoring
        gains no query, approval or admission authority here."""
        project = self.project.resolve()
        proposals._load_record(project, proposal)  # identity errors early
        with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
            record = proposals._load_record(project, proposal)  # authoritative
            proposals._check_coherent(project, record)
            with tempfile.TemporaryDirectory(prefix="ariadne-resolve-") as tmp:
                tree = Path(tmp) / "bundle"
                tree.mkdir()
                _materialize(project, proposal, record["candidate_revision"], tree)
                result = resolve_term(
                    [(tree / "context_layer", False)],
                    request,
                    part=part,
                    # the operator's evidence age budget drives the candidate
                    # side's explicit as_of/stale freshness states too (K4 fix
                    # pass, finding 3); no confirmations exist on a candidate
                    evidence_max_age_hours=project_inspection_limits(project)[
                        "receipt_max_age_hours"
                    ],
                )
        result.update(
            {
                "proposal": proposal,
                "revision": record["candidate_revision"],
                "candidate": True,
            }
        )
        return result

    # --------------- K3 (issue #43): bounded mapping inspection + receipts

    def inspect_mapping(
        self, proposal: str, expected_revision: str, candidate: object, limits: object = None
    ) -> dict:
        """Measure one structured mapping-inspection candidate (plan §2
        ``inspect_mapping``, spec 0010 §7): a discriminated JSON object of
        exactly the approved families — equality/composite, string prefix
        with an optional scoped prefix lookup, explicit scoped lookup — over
        the operator-APPROVED resolved source identity, through guarded
        core-generated read-only statements with parameterized scope, under
        the operator-owned finite ceilings (a request may only LOWER them).
        Returns the core receipt (eligible/tested denominators, actual scope,
        null/missing/unknown-lookup counts, coverage, mismatches, collisions,
        multiplicity, containment-versus-pairing basis, sampled/full
        designation, ``complete|inconclusive`` outcome with limitations)
        retained atomically in the ``.ariadne/`` evidence area — never a page
        edit, approval or admission. Aggregate counts are the default; raw
        identifier examples need the operator's explicit sample permission.
        """
        return inspect_mapping(self.project, proposal, expected_revision, candidate, limits=limits)


# ------------------------------------- slice 5 (issue #36/G4): validation/review

# The finalize commit's fixed message (the only commits validation itself
# creates): deterministic generated artifacts only, never a review decoration.
FINALIZE_COMMIT_MESSAGE = "ariadne: finalize generated artifacts"


def _cited_resources(meta: dict) -> list[str]:
    """The distinct citation resources of one page's frontmatter ``sources``
    (a mapping's ``resource`` — the rev 10 context field — or the plain
    string itself), plus — K2 (issue #42) — the canonical catalog identities a
    structured Reference's field/scope bindings name: bindings ride the SAME
    verified-citation walk, so a declared binding must parse and name an
    approved source like any other catalog citation."""
    resources: list[str] = []
    for source in meta.get("sources") or []:
        resource = (
            source.get("resource") if isinstance(source, dict) and "resource" in source else source
        )
        if isinstance(resource, str) and resource and resource not in resources:
            resources.append(resource)
    extension = meta.get("ariadne") if isinstance(meta.get("ariadne"), dict) else None
    for representation in (extension or {}).get("representations") or []:
        if not isinstance(representation, dict):
            continue
        bindings = [*(representation.get("fields") or []), *(representation.get("scope") or [])]
        for binding in bindings:
            if isinstance(binding, dict) and isinstance(binding.get("resource"), str):
                resource = binding["resource"]
                if resource not in resources:
                    resources.append(resource)
    return resources


def _tree_citation(tree: Path, page: Path, resource: str) -> str | None:
    """The tree-relative path of a citation that resolves INSIDE the effective
    bundle — context-root-relative first (``policies/x.md`` — the runtime's
    citation contract), then the citing page's own directory (the generated
    computations cite ``../../semantic_layer/...``), then bundle-root-relative
    (``data/seed_notes.md``); None when it resolves nowhere. Containment is
    checked against the materialized TREE (the whole candidate is the citation
    universe): an escaping traversal is just another unresolvable reference."""
    root = tree.resolve()
    context = tree / "context_layer"
    for base in (context, page.parent, tree):
        try:
            resolved = (base / resource).resolve()
        except OSError:  # pragma: no cover - pathological resource spellings
            return None
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved.relative_to(root).as_posix()
    return None


def _verified_citations(
    tree: Path, project: Path, source_names: set[str]
) -> tuple[list[dict], list[str]]:
    """Verify every citation of the effective bundle's OKF pages (spec §3–4):
    a citation resolves as a CANDIDATE page (inside the effective tree), an
    APPROVED source-table identity, or a DOCUMENT inside the operator's input
    boundary — verified through the shared boundary seam with its sha256
    (:func:`_citation_record`), exactly the legacy bundle review's verified
    citation. Returns (verified citations, errors): a citation resolving
    nowhere is broken, and broken INHERITED citations block even when only one
    file changed (AC2)."""
    citations: dict[tuple[str, str], dict] = {}
    errors: list[str] = []
    context_dir = tree / "context_layer"
    pages = sorted(context_dir.rglob("*.md")) if context_dir.is_dir() else []
    for page in pages:
        rel = f"context_layer/{page.relative_to(context_dir)}"
        try:
            meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            # a malformed draft page is a validation FAILURE the page gate
            # already names structurally; here it becomes a citation
            # diagnostic in the report — never an exception that escapes
            # validate_proposal with the whole report (spec §4)
            errors.append(
                f"{rel}: frontmatter is not valid YAML — its citations cannot be verified: {exc}"
            )
            continue
        for resource in _cited_resources(meta):
            if (bundle_rel := _tree_citation(tree, page, resource)) is not None:
                citations[("bundle", resource)] = {
                    "resource": resource,
                    "kind": "bundle",
                    "path": bundle_rel,
                }
            elif resource.startswith("ariadne://"):
                # K1 (issue #41): a canonical catalog asset resource — the
                # identified catalog/profile citation for physical facts. The
                # source it names must be one of the approved registry
                # identities (the approval separately binds the resolved
                # location; a navigation resource can never confer access).
                try:
                    _kind, parts = parse_resource(resource)
                except ValueError as exc:
                    errors.append(
                        f"{rel}: cited catalog resource {resource!r} is not canonical: {exc}"
                    )
                    continue
                if parts[0] not in source_names:
                    errors.append(
                        f"{rel}: cited catalog resource {resource!r} names source "
                        f"{parts[0]!r} which is not an approved registry identity "
                        f"(approved: {', '.join(sorted(source_names)) or 'none'})"
                    )
                    continue
                citations[("asset", resource)] = {
                    "resource": resource,
                    "kind": "catalog_asset",
                    "source": parts[0],
                }
            elif resource in source_names or resource.split(".", 1)[0] in source_names:
                citations[("source", resource)] = {"resource": resource, "kind": "source"}
            else:
                try:  # the operator's document boundary (verified, digest-bound)
                    citation = _citation_record(resource, project)
                except ValueError as exc:
                    errors.append(
                        f"{rel}: cited resource {resource!r} does not resolve as a "
                        "bundle page, approved source identity or operator-bound "
                        f"document — broken citation: {exc}"
                    )
                    continue
                citations[("document", resource)] = {
                    "resource": resource,
                    "kind": "document",
                    "title": citation["title"],
                    "digest": citation["digest"],
                    "location": citation["resource"],
                }
    return [citations[key] for key in sorted(citations)], errors


def _document_digests_current(project: Path, citations: list[dict]) -> bool:
    """True when every recorded DOCUMENT citation still resolves to the exact
    verified bytes — changed document evidence must never be presented as the
    unchanged validated candidate's linkage."""
    for citation in citations or []:
        if citation.get("kind") != "document":
            continue
        try:
            _resource, _title, data = _document_bytes(citation["resource"], project)
        except ValueError:
            return False
        if _sha256_hex(data) != citation.get("digest"):
            return False
    return True


def _materialize(project: Path, proposal: str, revision: str, target: Path) -> list[str]:
    """Materialize the EXACT candidate-scope bytes of ``revision`` into
    ``target`` (read from the commit, never a mutable worktree) and return the
    sorted scope paths — the validated/reviewed effective project. An
    empty-project onboarding candidate (no models yet) materializes fine:
    review stays readable and ``validate`` reports the missing models itself."""
    rels: list[str] = []
    for rel, blob in proposals.scope_blobs(project, revision):
        path = target.joinpath(*PurePosixPath(rel).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        rels.append(rel)
    return rels


def _report_view(report) -> dict:
    """The JSON view of one digest-bound ValidationReport."""
    return {
        "scope": report.scope,
        "digest": report.digest,
        "validator_version": report.validator_version,
        "registry_digest": report.registry_digest,
        "registry_label": report.registry_label,
        "files": list(report.files),
        "checks": [
            {"name": check.name, "outcome": check.outcome, "detail": check.detail}
            for check in report.checks
        ],
    }


def _validate_view(evidence: dict, evidence_path: Path, *, idempotent: bool) -> dict:
    """The validate_proposal response envelope (reused verbatim by the
    idempotent no-op retry)."""
    view = {
        "proposal": evidence["proposal"],
        "revision": evidence["commit"],
        "input_revision": evidence["input_revision"],
        "finalized": evidence["commit"] != evidence["input_revision"],
        "ok": evidence["ok"],
        "status": evidence["status"],
        "errors": list(evidence["errors"]),
        "attempts": evidence["repair"]["attempts"],
        "repair_status": evidence["repair"]["status"],
        "artifact_digest": evidence["artifact_digest"],
        "artifact_files": list(evidence["artifact_files"]),
        "source_digest": evidence["source_digest"],
        "approval_digest": evidence.get("approval_digest"),
        "storage_bindings": dict(evidence.get("storage_bindings") or {}),
        "citations": list(evidence["citations"]),
        "report": evidence["report"],
        "performed_checks": list(evidence["performed_checks"]),
        "validator_identity": evidence["validator_identity"],
        "evidence": str(evidence_path),
    }
    if idempotent:
        view["idempotent"] = True
    return view


def _stale_schema_binding_errors(tree: Path, approval_digest: str | None) -> list[str]:
    """spec 0025 §4 (measurement invalidation): every generated table page
    whose measured observations carry a ``source_binding`` must carry the
    CURRENT effective approval digest — schema and selected-value evidence
    measured under a different endpoint is stale provenance and refuses
    validation until the schema is refreshed under the current binding.
    Pages without a measured binding make no endpoint claim."""
    tables_dir = tree / "context_layer" / "tables"
    if not tables_dir.is_dir() or approval_digest is None:
        return []
    errors: list[str] = []
    for page in sorted(tables_dir.rglob("*.md")):
        rel = f"context_layer/tables/{page.relative_to(tables_dir)}"
        try:
            meta = context._load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue  # the page-contract gate owns malformed pages
        ariadne_meta = meta.get("ariadne") if isinstance(meta, dict) else None
        observations = ariadne_meta.get("observations") if isinstance(ariadne_meta, dict) else None
        bound = observations.get("source_binding") if isinstance(observations, dict) else None
        if isinstance(bound, str) and bound and bound != approval_digest:
            errors.append(
                f"{rel}: its measured schema/value observations are bound to a "
                f"different effective storage identity ({bound[:12]}, the candidate "
                f"now validates under {approval_digest[:12]}) — refresh_schema under "
                "the current endpoint before validation (spec 0025 §4)"
            )
    return errors


def validate_proposal(project: str | Path, proposal: str, expected_revision: str) -> dict:
    """Validate the proposal's effective candidate at its EXACT final revision
    (plan §2 ``validate_proposal``, spec §4): finalize the deterministic
    generated artifacts, commit any generated changes, materialize the final
    commit's candidate scope, and run the complete existing check stack over
    it — :func:`ariadne.validate` schema/compile/bind/grain/relationship
    audits against the operator-APPROVED resolved source identity (the G3
    seam; a declared-but-unapproved identity is an explicit error before
    anything opens), the ADR-0007 per-type page contract, the graph-citation
    gate and the verified-citation check. Returns the FINAL revision with the
    report and errors — never the earlier input commit when bytes changed.

    Evidence is stored separately (``.ariadne/validation/<proposal>/<
    commit>.json``, never a committed artifact) binding the commit, the
    COMPLETE artifact digest (generated/bookkeeping/Seed Notes bytes included,
    unlike the legacy served-tree walker), the resolved source identity, the
    verified citations, the performed check set and the validator identity.
    The bounded repair state is per-proposal and persistent: an unchanged
    retry is idempotent (no attempt consumed, no reset), a changed candidate
    consumes one of the authoring rounds, and exhausting them stays
    ``review_needed`` for the human — creating another commit never resets it."""
    project = Path(project).resolve()
    proposals._load_record(project, proposal)  # identity/belonging errors early
    worktree_root = project / proposals.WORKTREES_REL / proposal
    with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
        record = proposals._load_record(project, proposal)  # authoritative under the lock
        proposals._check_coherent(project, record)
        current = record["candidate_revision"]
        if expected_revision != current:
            raise ValueError(
                f"stale revision: proposal {proposal} is at candidate {current}, the "
                f"validation expected {expected_revision} — re-read the candidate and "
                "retry with the current revision; nothing was written"
            )
        # The G3 seam BEFORE any finalize commit: the candidate's resolved
        # source identity must carry the operator's approval — for its CURRENT
        # effective storage binding (spec 0025 §4: endpoint changes need their
        # own grant; a declaration digest with only a historical grant never
        # authorizes). The finalize pass touches only context_layer bytes, so
        # the input revision's registry identity IS the final revision's.
        resolved_sources, source_digest = authoring_sources.candidate_sources(project, current)
        approval = None
        if resolved_sources is not None:
            assert source_digest is not None
            approval = authoring_sources._effective_grant(
                project, resolved_sources, source_digest, proposal, current
            )
        approval_digest_value = approval.get("approval_digest") if approval else None
        # Idempotent no-op retry: stored evidence for the EXACT current commit
        # with unchanged binding context returns as-is — nothing re-runs and
        # the bounded repair state is neither reset nor advanced.
        stored = proposals.load_validation(project, proposal, current)
        if (
            stored is not None
            and stored.get("source_digest") == source_digest
            and stored.get("approval_digest") == (approval_digest_value or source_digest)
            and stored.get("validator_identity")
            == validator_identity(stored.get("performed_checks") or [])
            and _document_digests_current(project, stored.get("citations") or [])
        ):
            return _validate_view(
                stored,
                proposals._validation_path(project, proposal, current),
                idempotent=True,
            )
        repair: dict = dict(record.get("repair") or {"attempts": 0, "status": "open"})
        if repair["attempts"] >= MAX_ROUNDS or repair["status"] == "review_needed":
            raise ValueError(
                f"proposal {proposal} exhausted its {MAX_ROUNDS} bounded validation "
                f"rounds ({repair['attempts']} attempts) and remains review_needed — "
                "this needs human resolution; no agent validation resets the repair "
                "state (spec §4); nothing was written"
            )
        # Finalize BEFORE validation (spec §4): deterministic generated content
        # (no wall-clock restamp), committed as the exact final candidate.
        proposals.refuse_untracked_scope(project, record)
        # K3 (issue #43): verify every structured mapping's cited receipts
        # against the project's evidence records and the current dependency
        # identities, and attach the bounded verified summaries to the
        # Reference pages (deterministic core-authored page edits, committed
        # BEFORE the finalize pass so the regenerated index trees include
        # them; the validated bytes carry the verified evidence).
        current, receipt_errors = _finalize_mapping_evidence(
            project,
            proposal,
            record,
            current,
            source_digest=source_digest,
            approval=approval,
        )
        context.finalize_candidate(worktree_root)
        final = (
            proposals.commit_generated(project, record, message=FINALIZE_COMMIT_MESSAGE) or current
        )
        with tempfile.TemporaryDirectory(prefix="ariadne-candidate-") as tmp:
            root = Path(tmp)
            tree = root / "bundle"
            tree.mkdir()
            rels = _materialize(project, proposal, final, tree)
            # The audit connection opens ONLY the operator-approved resolved
            # identity (the G3 seam) with the grant's FROZEN effective binding
            # (spec 0025 §4): one registry object carrying exactly those
            # resolved entries and pinned endpoints — never a re-resolved
            # environment value after the check.
            approved_registry = (
                authoring_sources.identity_registry(
                    approval["sources"], approval.get("storage_bindings")
                )
                if approval is not None
                else None
            )
            names = {entry["name"] for entry in (approval["sources"] if approval else [])}
            try:  # the source-access boundary BEFORE any bind/audit execution
                _authorize_dataset_sources(tree, names)
                auth_error = None
            except (ValueError, yaml.YAMLError) as exc:
                # an unauthorizable or unparseable model set never reaches the
                # audit connection; the structural gate reports the parse error
                auth_error = str(exc)
            if auth_error is None:
                result = validate(tree, registry=approved_registry)
                errors = list(result.errors)
            else:  # never open the audit connection for an unauthorized source
                result = validate(tree)  # compile-only: the boundary error blocks
                errors = [auth_error, *result.errors]
            page_errors = (
                _bundle_errors(tree)
                + _graph_citation_errors(tree)
                + _stale_schema_binding_errors(
                    tree, approval.get("approval_digest") if approval else None
                )
            )
            # K4 (issue #44): conflicting asserted claims refuse validation
            # alongside the receipt-verification gate
            claim_errors = _asserted_claim_errors(tree)
            example_errors = answer_examples.validate_candidate_records(project, record, tree)
            citations, citation_errors = _verified_citations(tree, project, names)
            errors.extend(page_errors)
            errors.extend(example_errors)
            errors.extend(citation_errors)
            errors.extend(receipt_errors)
            errors.extend(claim_errors)
            # validate() carries no report at all only when a graph is declared
            # without models (the load owns that failure): the structural
            # outcome owns it explicitly. A context-only candidate (K4, issue
            # #44) arrives WITH a report — its semantic checks are explicitly
            # not_applicable with reasons.
            base_checks = (
                result.report.checks
                if result.report is not None
                else (CheckOutcome("structural", "failed", "; ".join(result.errors)),)
            )
            checks = (
                CheckOutcome(
                    "source_boundary", "failed" if auth_error else "passed", auth_error or ""
                ),
                *base_checks,
                CheckOutcome(
                    "page_contract",
                    "failed" if page_errors else "passed",
                    "; ".join(page_errors),
                ),
                CheckOutcome(
                    "answer_examples",
                    "failed" if example_errors else "passed",
                    "; ".join(example_errors),
                ),
                CheckOutcome(
                    "citations",
                    "failed" if citation_errors else "passed",
                    "; ".join(citation_errors),
                ),
                CheckOutcome(
                    "mapping_evidence",
                    "failed" if (receipt_errors or claim_errors) else "passed",
                    "; ".join([*receipt_errors, *claim_errors]),
                ),
            )
            # K4 (issue #44): an explicitly not_applicable check was NOT
            # performed — the applicability decision rides the report (each
            # not_applicable outcome carries its reason), never the performed
            # set a current validator identity binds.
            performed = [
                check.name for check in checks if check.outcome not in ("not-run", "not_applicable")
            ]
            artifact_digest = candidate_scope_digest(tree)
            report_view = (
                _report_view(result.report)
                if result.report is not None
                else {
                    "scope": "none (no semantic models)",
                    "digest": None,
                    "validator_version": VALIDATOR_VERSION,
                    "registry_digest": None,
                    "registry_label": None,
                    "files": [],
                    "checks": [],
                }
            )
            # the report the evidence binds carries the FULL check scope: the
            # compiler/audit outcomes plus the wrapper-level gates
            report_view["checks"] = [
                {"name": check.name, "outcome": check.outcome, "detail": check.detail}
                for check in checks
            ]
        ok = not errors
        status = "validated" if ok else "invalid"
        # Bounded repair accounting: one round per CHANGED validation (a
        # different commit or a changed binding context — the effective
        # storage binding rides the key, so identical candidate bytes cannot
        # reuse an old-endpoint validation, spec 0025 §4); an identical retry
        # of the same key consumes nothing.
        key = {
            "commit": final,
            "source_digest": source_digest,
            "approval_digest": approval_digest_value or source_digest,
            "documents": sorted(
                f"{c['resource']}:{c['digest']}" for c in citations if c["kind"] == "document"
            ),
        }
        previous = record.get("validation") or {}
        attempts = repair["attempts"] + (1 if previous.get("key") != key else 0)
        repair = {
            "attempts": attempts,
            "status": "review_needed" if (errors and attempts >= MAX_ROUNDS) else "open",
        }
        evidence = {
            "proposal": proposal,
            "project": str(project),
            "commit": final,
            "input_revision": expected_revision,
            "ok": ok,
            "status": status,
            "errors": errors,
            "artifact_digest": artifact_digest,
            "artifact_files": rels,
            "source_digest": source_digest,
            "source_identity": resolved_sources,
            "source_approval": (
                {"digest": source_digest, "approved_at": approval["approved_at"]}
                if approval is not None
                else None
            ),
            "approval_digest": approval_digest_value or source_digest,
            "storage_bindings": (approval.get("storage_bindings") or {}) if approval else {},
            "citations": citations,
            "report": report_view,
            "performed_checks": performed,
            "validator_identity": validator_identity(performed),
            "repair": repair,
            "validated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        # The proposal record's persistent repair/validation state and the
        # verified citation identities (plan §2) — never reset by a new commit.
        record["repair"] = repair
        record["validation"] = {"commit": final, "ok": ok, "key": key, "attempts": attempts}
        record["citations"] = citations
        proposals._store_record(project, record)
        evidence_path = proposals.store_validation(project, evidence)
        return _validate_view(evidence, evidence_path, idempotent=False)


def _review_body(rel: str, data: bytes, *, part: int) -> dict:
    """One bounded body entry of the review inventory: part ``part`` of the
    artifact when it has one, and an honestly EMPTY ``exhausted`` entry when
    the artifact has no such part. The part bound applies PER-ARTIFACT (plan
    §2 bounded-part review contract), so a short artifact (e.g.
    ``ariadne.yaml``) never makes the later parts of a longer one
    unreachable — every part of every artifact stays retrievable through
    successive review calls, and no truncated part is ever claimed complete."""
    text = data.decode("utf-8", errors="replace")
    parts = max(1, -(-len(text) // EVIDENCE_PART_CHARS))
    if part > parts:
        return {
            "resource": rel,
            "title": PurePosixPath(rel).name,
            "digest": _sha256_hex(data),
            "chars": len(text),
            "part": part,
            "parts": parts,
            "text": "",
            "complete": False,
            "exhausted": True,  # no part N exists — earlier parts hold the whole body
        }
    record = _evidence_record(
        rel,
        PurePosixPath(rel).name,
        _sha256_hex(data),
        text,
        part=part,
        part_chars=EVIDENCE_PART_CHARS,
    )
    record["exhausted"] = False
    return record


def _change_inventory(project: Path, record: dict) -> list[dict]:
    """The candidate's change inventory versus its base revision, bounded to
    the candidate artifact scope (an unrelated tracked file never leaks into a
    review)."""
    scope = [
        proposals._literal(prefix)
        for prefix in (
            "ariadne.yaml",
            "data/seed_notes.md",
            "semantic_layer",
            "context_layer",
            "answer_examples",
        )
    ]
    diff = proposals._git(
        [
            "diff",
            "--name-status",
            "--no-renames",
            record["base_revision"],
            record["candidate_revision"],
            "--",
            *scope,
        ],
        project,
    ).stdout
    inventory = []
    for line in diff.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        inventory.append({"change": status[0], "path": path})
    return inventory


def review_proposal(project: str | Path, proposal: str, *, part: int = 1) -> dict:
    """Read the proposal's effective candidate (plan §2 ``review_proposal``;
    spec §4 — reading a review response is NOT sign-off, and admission is a
    separate human decision in G5): current/base revisions, the change
    inventory, bounded effective bodies with stable digests (the requested
    part applies PER-ARTIFACT; artifacts without that many parts keep their
    inventory entry as an honestly empty ``exhausted`` record), the CURRENT
    source identity and approval state, the verified citations (re-verified
    now: changed document evidence or a moved candidate is reported stale,
    never as an unchanged validated candidate), the stored validation report
    with its full check scope, the expected admitted baseline the record
    binds, and a review digest binding exactly what was reviewed (baseline
    included — a review made against a different served baseline is a
    different review identity). Read-only: nothing is written, moved or reset.
    """
    project = Path(project).resolve()
    proposals._load_record(project, proposal)
    with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
        record = proposals._load_record(project, proposal)  # authoritative under the lock
        return _review_candidate(project, proposal, part=part, record=record)


# ------------------------------------ K4 (issue #44): asserted mappings surface


def _reference_mapping_pages(tree: Path) -> list[tuple[str, dict, dict]]:
    """Every structured Reference page of one materialized candidate tree:
    (context-relative page path, frontmatter meta, the ariadne extension).
    Legacy References without the extension stay out; malformed draft pages
    stay out too — the page gate owns their structural errors."""
    context_dir = tree / "context_layer"
    pages: list[tuple[str, dict, dict]] = []
    for page in sorted(context_dir.rglob("*.md")) if context_dir.is_dir() else []:
        if page.name in _GENERATED_FILES:
            continue
        rel = page.relative_to(context_dir).as_posix()
        if not rel.startswith("references/"):
            continue
        try:
            meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue  # the page gate owns the malformed-draft error
        extension = meta.get("ariadne") if isinstance(meta, dict) else None
        if isinstance(extension, dict) and isinstance(extension.get("mappings"), list):
            pages.append((rel, meta, extension))
    return pages


def _asserted_claim_errors(tree: Path) -> list[str]:
    """Conflicting asserted claims refuse validation (spec 0010 §5/§9, K4):
    two ASSERTED mappings of one Reference over the same relationship — the
    same endpoints and family — with different assertion digests are two
    disagreeing confirmed-usage candidates, not alternatives a human confirms
    one by one. Different or conflicting declarations stay separate labeled
    HYPOTHESES (plan §2); only an unambiguous asserted claim reaches human
    confirmation."""
    errors: list[str] = []
    for rel, _meta, extension in _reference_mapping_pages(tree):
        claimed: dict[tuple, dict] = {}
        for mapping in extension["mappings"]:
            if not isinstance(mapping, dict) or mapping.get("claim") != "asserted":
                continue
            key = (mapping.get("from"), mapping.get("to"), mapping.get("family"))
            digest = mapping_assertion_digest(mapping)
            if key in claimed and claimed[key]["digest"] != digest:
                errors.append(
                    f"context_layer/{rel}: asserted mappings "
                    f"{claimed[key]['id']!r} and {mapping.get('id')!r} claim the same "
                    f"relationship ({mapping.get('from')!r} -> {mapping.get('to')!r}, "
                    f"family {mapping.get('family')!r}) with different declarations — "
                    "conflicting asserted claims refuse validation; keep the "
                    "alternatives as separate labeled hypotheses"
                )
            elif key not in claimed:
                claimed[key] = {"id": mapping.get("id"), "digest": digest}
    return errors


def _mapping_assertions(tree: Path) -> list[dict]:
    """The reviewed candidate's structured mapping assertions (K4, plan §2
    "Admission and automatic capture"): each mapping's page resource,
    reference slug, mapping ID, family, endpoints, claim, verbatim
    declaration, assertion digest, dependencies/evidence and confirmation
    eligibility — the exact surface a human selects from with
    ``--confirm-mapping <reference-slug>:<mapping-id>``. Reading this list is
    NEVER confirmation (spec 0010 §5): a hypothesis is listed for the review
    but never selectable, and only an asserted mapping is confirmable — never
    one whose verified receipts show counterevidence (K4 fix pass, finding 1:
    an asserted claim contradicted by its own cited evidence is
    unsupported)."""
    assertions: list[dict] = []
    for rel, meta, extension in _reference_mapping_pages(tree):
        evidence = meta.get("ariadne_evidence")
        summaries = evidence if isinstance(evidence, dict) else {}
        for mapping in extension["mappings"]:
            if not isinstance(mapping, dict):
                continue
            claim = mapping.get("claim")
            receipts = [
                {
                    "id": summary.get("id"),
                    "digest": summary.get("digest"),
                    "observed_at": summary.get("observed_at"),
                    "designation": summary.get("designation"),
                    "outcome": summary.get("outcome"),
                    "mismatch_count": summary.get("mismatch_count"),
                    "comparison_basis": summary.get("comparison_basis"),
                }
                for summary in summaries.get(mapping.get("id")) or []
                if isinstance(summary, dict)
            ]
            # K4 fix pass (finding 1, spec 0010 §§8–9): an asserted mapping
            # contradicted by its own verified receipts (honest mismatches, an
            # ambiguous pairing basis or an inconclusive outcome) is
            # UNSUPPORTED — it is never selectable for confirmation. A
            # hypothesis carrying the same receipt stays listed (openly
            # labeled, never confirmable).
            counterevidence = [
                named
                for named in (evidence_counterevidence(summary) for summary in receipts)
                if named
            ]
            confirmable = claim == "asserted" and not counterevidence
            if claim == "asserted" and counterevidence:
                note = (
                    "the asserted mapping's verified receipts show counterevidence "
                    f"({'; '.join(counterevidence)}) — an asserted claim contradicted by "
                    "its own cited evidence is unsupported; carry it as a labeled "
                    "hypothesis instead"
                )
            elif confirmable:
                note = (
                    "an asserted mapping is eligible for explicit human confirmation "
                    "(--confirm-mapping)"
                )
            else:
                note = (
                    "a hypothesis is investigative knowledge only — it is never "
                    "selectable as a confirmed assertion"
                )
            assertions.append(
                {
                    "page": rel,
                    "reference": PurePosixPath(rel).stem,
                    "mapping": mapping.get("id"),
                    "family": mapping.get("family"),
                    "from": mapping.get("from"),
                    "to": mapping.get("to"),
                    "claim": claim,
                    "declaration": mapping,
                    # the EFFECTIVE identity a confirmation binds (K4 fix pass,
                    # finding 2): the declaration plus its endpoint
                    # representations' normalized correspondence — review,
                    # admission and retention all compare THIS digest
                    "assertion_digest": (
                        confirmation_binding_digest(meta, mapping)
                        if isinstance(mapping.get("id"), str)
                        else None
                    ),
                    "source_ids": list(mapping.get("source_ids") or []),
                    "receipts": receipts,
                    "confirmable": confirmable,
                    "confirmation_note": note,
                }
            )
    return assertions


def _review_candidate(
    project: Path, proposal: str, *, part: int = 1, record: dict | None = None
) -> dict:
    """The lock-free review core (issue #37/G5): exactly the envelope
    :func:`review_proposal` returns, computed for one loaded record — the
    caller holds the proposal lock (the public review takes it; admission
    already holds the project+proposal locks when it re-derives the review
    digest, and a nested lock acquisition would self-deadlock). K4 (issue
    #44): the envelope carries the candidate's structured mapping assertions
    — each mapping's page/ID/digest/dependencies and confirmation eligibility
    — bound into the review digest, so an admission's mapping selections are
    bound to the exact reviewed identity."""
    if record is None:
        record = proposals._load_record(project, proposal)
    proposals._check_coherent(project, record)
    base = record["base_revision"]
    current = record["candidate_revision"]
    with tempfile.TemporaryDirectory(prefix="ariadne-review-") as tmp:
        tree = Path(tmp) / "bundle"
        tree.mkdir()
        rels = _materialize(project, proposal, current, tree)
        resolved_sources, source_digest = authoring_sources.candidate_sources(project, current)
        bodies = []
        for rel in rels:
            data = (tree / Path(*PurePosixPath(rel).parts)).read_bytes()
            bodies.append(_review_body(rel, data, part=part))
        source_names = {entry["name"] for entry in resolved_sources or []}
        citations, _citation_errors = _verified_citations(tree, project, source_names)
        approval = authoring_sources.approval_state(project, resolved_sources, source_digest)
        approved = approval["approved"]
        artifact_digest = candidate_scope_digest(tree)
        # The stored report binds the exact candidate commit or is absent:
        # a candidate that moved past its validation, a changed source
        # identity, changed document evidence or changed artifact bytes can
        # never be presented as an unchanged validated candidate.
        report = proposals.load_validation(project, proposal, current)
        stale_reasons: list[str] = []
        if report is not None:
            if report.get("source_digest") != source_digest:
                stale_reasons.append("the resolved source identity changed since validation")
            if approval["state"] == "unresolved":
                # spec 0025 §4: a required endpoint/region value is unset — the
                # effective binding cannot be resolved offline, so prior
                # validation is never presented as current (and review never
                # crashes on the missing digest key)
                stale_reasons.append(
                    "the effective storage binding is unresolved (a required "
                    "endpoint/region variable is unset, spec 0025 §4) — prior "
                    "validation is not current; resolve the prerequisite and "
                    "revalidate before admission"
                )
            elif approval.get("approval_digest") is not None and report.get(
                "approval_digest"
            ) not in (None, approval["approval_digest"]):
                stale_reasons.append(
                    "the effective storage binding changed since validation "
                    "(spec 0025 §4) — revalidate against the current endpoint grant"
                )
            if not _document_digests_current(project, report.get("citations") or []):
                stale_reasons.append("cited document evidence changed since validation")
            if report.get("artifact_digest") != artifact_digest:
                stale_reasons.append(
                    "the candidate's artifact bytes differ from the validated digest"
                )
        inventory = _change_inventory(project, record)
        # K4 (issue #44): the candidate's structured mapping assertions — the
        # exact identity/digest/dependencies/eligibility surface a human
        # selects from at admission. Reading it is never confirmation.
        mapping_assertions = _mapping_assertions(tree)
        review_digest = hashlib.sha256(
            json.dumps(
                {
                    "proposal": proposal,
                    "base_revision": base,
                    "revision": current,
                    "expected_baseline": record.get("expected_baseline"),
                    "changes": inventory,
                    "artifact_digest": artifact_digest,
                    "citations": citations,
                    # spec 0025 §4 (exact human authority): the review digest
                    # binds the candidate's EFFECTIVE source identity — the
                    # declaration digest, the effective approval digest and
                    # the complete storage bindings — so a reviewed digest
                    # validated under endpoint A can never admit endpoint B
                    # from identical candidate bytes.
                    "source_digest": source_digest,
                    "approval_digest": approval.get("approval_digest"),
                    "storage_bindings": approval.get("storage_bindings") or {},
                    "mapping_assertions": [
                        {
                            "page": entry["page"],
                            "mapping": entry["mapping"],
                            "assertion_digest": entry["assertion_digest"],
                            "receipts": [receipt["digest"] for receipt in entry["receipts"]],
                        }
                        for entry in mapping_assertions
                    ],
                    "validation": None
                    if report is None
                    else {
                        "commit": report["commit"],
                        "ok": report["ok"],
                        "artifact_digest": report["artifact_digest"],
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "proposal": proposal,
            "project": str(project),
            "base_revision": base,
            "revision": current,
            "expected_baseline": record.get("expected_baseline"),
            "part": part,
            "changes": inventory,
            "files": bodies,
            "sources": resolved_sources or [],
            "sources_digest": source_digest,
            "source_approved": approved,
            "source_approval_state": approval["state"],
            "storage_bindings": approval.get("storage_bindings") or {},
            "citations": citations,
            "report": None
            if report is None
            else _validate_view(
                report,
                proposals._validation_path(project, proposal, current),
                idempotent=False,
            ),
            "validation_stale": bool(stale_reasons),
            "stale_reasons": stale_reasons,
            "mapping_assertions": mapping_assertions,
            "review_digest": review_digest,
        }


# ------------------------ K1 (issue #41): the explicit schema refresh seam

# One catalog asset of a refresh request: the COMPLETE identity tuple
# {source, catalog, schema, table} with exact case-sensitive identifiers
# (plan §2). ``catalog`` is null for file views.
_ASSET_KEYS = frozenset({"source", "catalog", "schema", "table"})


def _catalog_asset(asset: object) -> dict:
    """Validate one explicit catalog asset request: exactly the identity-tuple
    keys, plain non-empty identifiers (catalog may be null). Consumers use
    these explicit fields, never display names."""
    if not isinstance(asset, dict) or set(asset) != _ASSET_KEYS:
        raise ValueError(
            "a catalog asset is exactly {source, catalog, schema, table} with exact "
            "case-sensitive identifiers (catalog null for file views), got "
            f"{asset!r}"
        )
    for key in ("source", "schema", "table"):
        if not isinstance(asset[key], str) or not asset[key]:
            raise ValueError(f"catalog asset field {key!r} must be a non-empty string")
    catalog = asset["catalog"]
    if catalog is not None and (not isinstance(catalog, str) or not catalog):
        raise ValueError(
            "catalog asset field 'catalog' must be the stable attached catalog name "
            "or null (file views carry no catalog)"
        )
    return dict(asset)


def _declared_columns(con, catalog: list[dict]) -> dict[tuple[str, str, str], dict[str, dict]]:
    """Declared column metadata (is_nullable/column_default) for ATTACHED
    sources only, read from information_schema: file views carry no declared
    constraints, so their metadata stays unknown (spec 0010 §4 — expose
    declared metadata only where the source provides it)."""
    declared: dict[tuple[str, str, str], dict[str, dict]] = {}
    for entry in catalog:
        if not any(table.get("catalog") for table in entry["tables"]):
            continue  # file views: no declared metadata to read
        rows = con.execute(
            "SELECT table_catalog, table_schema, table_name, column_name, "
            "is_nullable, column_default FROM information_schema.columns "
            "WHERE table_catalog = ? ORDER BY table_schema, table_name, ordinal_position",
            [entry["name"]],
        ).fetchall()
        for catalog_name, schema, table, column, is_nullable, default in rows:
            declared.setdefault((catalog_name, schema, table), {})[column] = {
                # the DECLARED nullability, verbatim: YES -> nullable, NO ->
                # NOT NULL; anything else the source does not declare stays
                # unknown (None), never a manufactured constraint (spec 0010 §4)
                "nullable": (
                    True if is_nullable == "YES" else False if is_nullable == "NO" else None
                ),
                "default": default,
            }
    return declared


def _resource_pages(project: Path, revision: str) -> tuple[dict[str, dict], set[str]]:
    """The candidate's resource-bound schema pages at ``revision`` (read from
    the commit, never a worktree): ``(resource -> {path, meta, text}, tracked
    schema-page paths)``. Two pages carrying the same resource is a collision
    needing human resolution; pages without a canonical resource (legacy
    authored names) are not touched by refresh."""
    tracked = proposals._git(["ls-tree", "-r", "--name-only", revision], project).stdout
    pages: dict[str, dict] = {}
    paths: set[str] = set()
    for rel in tracked.split("\n"):
        if (
            not (
                rel.startswith("context_layer/tables/") or rel.startswith("context_layer/datasets/")
            )
            or PurePosixPath(rel).name in proposals._GENERATED_FILES
        ):
            continue
        blob = proposals._read_blob(project, revision, rel)
        if blob is None:  # pragma: no cover - ls-tree paths always resolve
            continue
        paths.add(rel)
        text = blob.decode("utf-8", "replace")
        try:
            meta = _load_frontmatter_meta(text)
        except yaml.YAMLError:
            continue  # a malformed draft page: the validation gate owns the error
        resource = meta.get("resource") if isinstance(meta, dict) else None
        if isinstance(resource, str) and resource.startswith("ariadne://"):
            if resource in pages:
                raise ValueError(
                    f"the candidate carries two schema pages for {resource!r} "
                    f"({pages[resource]['path']} and {rel}) — a resource collision "
                    "needs human resolution; refresh refuses rather than overwriting"
                )
            pages[resource] = {"path": rel, "meta": meta, "text": text}
    return pages, paths


def _schema_columns(catalog_table: dict, declared: dict) -> list[dict]:
    """The core-owned schema facts of one table: exact column identity/type in
    ordinal order plus only supported declared metadata (unknown stays
    unknown; no manufactured NOT NULL, default or comment)."""
    facts = declared.get(
        (catalog_table.get("catalog"), catalog_table.get("schema"), catalog_table["name"]), {}
    )
    columns: list[dict] = []
    for column in catalog_table["columns"]:
        meta = facts.get(column["name"])
        columns.append(
            {
                "column": column["name"],
                "type": column["type"],
                "nullable": meta["nullable"] if meta is not None else "unknown",
                "default": meta["default"] if meta is not None else "unknown",
                "comment": "unknown",  # no comment source is read in K1
            }
        )
    return columns


def refresh_schema(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    assets: list[dict] | tuple[dict, ...],
) -> dict:
    """The explicit physical schema refresh (plan §2 ``refresh_schema``, spec
    0010 §4; issue #41/K1): regenerate the core-owned schema facts and Dataset
    Overviews of an EXPLICIT catalog asset list inside the selected proposal.

    Reads run ONLY through the operator-approved resolved source identity (the
    G3 seam — an unapproved or changed registry is an explicit error and the
    connection builder is never called); every write is a revision-checked
    complete page edit (an identical refresh is a no-op and the candidate
    revision does not move); authored summary/column meaning is preserved for
    identical column identity/type while removed/type-changed columns keep
    their prior meaning as reviewable history; filename/resource collisions
    refuse instead of overwriting. Returns the resulting revision, the
    generated page identities (resource + path + kind) and per-page
    schema-change flags. Refresh edits a candidate — it is never validation or
    admission (K4 owns context-only admission)."""
    project = Path(project).resolve()
    if not isinstance(assets, (list, tuple)) or not assets:
        raise ValueError(
            "refresh_schema takes an explicit non-empty list of catalog assets "
            "{source, catalog, schema, table}"
        )
    requested = [_catalog_asset(asset) for asset in assets]
    seen: set[tuple] = set()
    for asset in requested:
        key = (asset["source"], asset["catalog"], asset["schema"], asset["table"])
        if key in seen:
            raise ValueError(f"duplicate catalog asset in the refresh request: {asset}")
        seen.add(key)
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if expected_revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the "
            f"refresh expected {expected_revision} — re-read the candidate and retry "
            "with the current revision; nothing was written"
        )
    resolved, digest = authoring_sources.candidate_sources(project, current)
    if resolved is None:
        raise ValueError(
            f"proposal {proposal} declares no source entries in its candidate "
            f"registry at {current[:12]} — there is nothing to refresh"
        )
    assert digest is not None
    approval = authoring_sources._effective_grant(project, resolved, digest, proposal, current)
    storage_bindings = approval.get("storage_bindings") or {}
    binding_digest = approval.get("approval_digest") if storage_bindings else None
    owned = execution.DuckDBExecution(
        authoring_sources.identity_registry(approval["sources"], storage_bindings)
    )
    try:
        con, catalog = owned.con, owned.catalog
        declared = _declared_columns(con, catalog)
        # profile ONLY the requested tables (bounded, explicit refresh work)
        profiles: dict[str, dict] = {}
        matched: dict[tuple, dict] = {}
        for entry in catalog:
            matching = [
                t
                for t in entry["tables"]
                if (t["source"], t.get("catalog"), t.get("schema"), t["name"]) in seen
            ]
            if not matching:
                continue
            for table in matching:
                matched[
                    (table["source"], table.get("catalog"), table.get("schema"), table["name"])
                ] = table
            source_profile = profiler._profile_source(con, {**entry, "tables": matching})
            for table in source_profile["tables"].values():
                profiles[table["resource"]] = table
    finally:
        owned.close()
    missing = [
        asset
        for asset in requested
        if (asset["source"], asset["catalog"], asset["schema"], asset["table"]) not in matched
    ]
    if missing:
        available = sorted(
            f"{t['source']}.{t.get('schema')}.{t['name']}"
            for entry in catalog
            for t in entry["tables"]
        )
        raise ValueError(
            f"catalog asset(s) not present in the approved resolved source identity: "
            f"{missing[0]} — available assets: {', '.join(available) or 'none'}; "
            "nothing was written"
        )
    existing, tracked_paths = _resource_pages(project, current)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    specs: list[dict] = []
    claimed: dict[str, str] = {}
    collections: dict[tuple, dict] = {}
    for asset in requested:
        key = (asset["source"], asset["catalog"], asset["schema"], asset["table"])
        table = matched[key]
        resource = table_resource(
            asset["source"], asset["catalog"], asset["schema"], asset["table"]
        )
        columns = _schema_columns(table, declared)
        page = existing.get(resource)
        path = (
            page["path"]
            if page
            else (f"context_layer/tables/{generated_page_filename(resource, asset['source'])}")
        )
        text, flags = build_table_page(
            asset={
                **asset,
                "resource": resource,
            },
            columns=columns,
            profile=profiles[resource],
            existing_text=page["text"] if page else None,
            now=now,
            source_binding=binding_digest,
        )
        specs.append(
            {
                "resource": resource,
                "path": path,
                "text": text,
                "kind": "table",
                "flags": flags,
            }
        )
        collections.setdefault(
            (asset["source"], asset["catalog"], asset["schema"]),
            {"source": asset["source"], "catalog": asset["catalog"], "schema": asset["schema"]},
        )
    for collection_key, collection in collections.items():
        resource = collection_resource(
            collection["source"], collection["catalog"], collection["schema"]
        )
        page = existing.get(resource)
        path = (
            page["path"]
            if page
            else (
                f"context_layer/datasets/{generated_page_filename(resource, collection['source'])}"
            )
        )
        # Overview membership is the collection's EXISTING represented pages
        # PLUS the requested updates (issue #41): a narrower refresh never
        # drops a still-present table's link — and an approved asset nothing
        # ever documented is never silently asserted (no unrelated additions)
        members: list[dict] = []
        requested_here: set[str] = set()
        for spec in specs:
            if spec["kind"] != "table":
                continue
            parts = parse_resource(spec["resource"])[1]
            if parts[:3] != list(collection_key):
                continue  # the tables of OTHER collections
            members.append(
                {
                    "resource": spec["resource"],
                    "table": parts[3],
                    "link": f"../tables/{PurePosixPath(spec['path']).name}",
                    "column_count": len(profiles[spec["resource"]]["columns"]),
                }
            )
            requested_here.add(spec["resource"])
        carried: list[tuple[str, dict]] = []
        for res, carried_page in existing.items():
            if res in requested_here or not carried_page["path"].startswith(
                "context_layer/tables/"
            ):
                continue
            try:
                kind, parts = parse_resource(res)
            except ValueError:
                continue  # not a canonical resource: nothing it can represent
            if kind != "table" or parts[:3] != list(collection_key):
                continue
            carried_meta = (
                carried_page["meta"].get("ariadne")
                if isinstance(carried_page["meta"], dict)
                else None
            )
            carried_schema = carried_meta.get("schema") if isinstance(carried_meta, dict) else None
            carried.append(
                (
                    parts[3],
                    {
                        "resource": res,
                        "table": parts[3],
                        "link": f"../tables/{PurePosixPath(carried_page['path']).name}",
                        "column_count": (
                            len(carried_schema) if isinstance(carried_schema, list) else 0
                        ),
                    },
                )
            )
        members.extend(member for _table, member in sorted(carried, key=lambda c: c[0]))
        text, flags = build_dataset_page(
            collection={
                **collection,
                "resource": resource,
            },
            tables=members,
            existing_text=page["text"] if page else None,
        )
        specs.append(
            {"resource": resource, "path": path, "text": text, "kind": "dataset", "flags": flags}
        )
    # collision checks BEFORE any write (plan §2: a collision refuses, never
    # overwrites; filename/resource consistency is checked against the
    # candidate's tracked schema pages)
    for spec in specs:
        other = claimed.get(spec["path"])
        if other is not None and other != spec["resource"]:
            raise ValueError(
                f"generated filename collision: {spec['path']} would serve both "
                f"{other!r} and {spec['resource']!r} — refresh refuses rather than "
                "overwriting another asset"
            )
        claimed[spec["path"]] = spec["resource"]
        page = existing.get(spec["resource"])
        if page is None and spec["path"] in tracked_paths:
            raise ValueError(
                f"{spec['path']}: the generated page for {spec['resource']!r} collides "
                "with a different existing candidate page — a filename/resource "
                "collision refuses rather than overwriting; resolve it by hand"
            )
    # Fix F1 (parent-authorized, spec 0024 §3/§6 AC5): pre-flight EVERY
    # generated page against the shared artifact bound BEFORE the first edit.
    # The sequential edit seam checks one page at a time, so an over-limit
    # later page would otherwise refuse only after earlier pages already
    # advanced the candidate — a half-updated refresh. The check is the same
    # one the edit seam itself runs, moved ahead of all writes; no partial
    # state can remain.
    for spec in specs:
        proposals.check_artifact_content(f"generated page {spec['resource']!r}", spec["text"])
    revision = current
    pages: list[dict] = []
    changed_any = False
    for spec in specs:  # revision-checked complete page edits, core-generated
        out = proposals.edit_proposal(
            project, proposal, revision, spec["path"], spec["text"], core_generated=True
        )
        revision = out["revision"]
        changed_any = changed_any or out["changed"]
        pages.append(
            {
                "resource": spec["resource"],
                "path": spec["path"],
                "kind": spec["kind"],
                "changed": out["changed"],
                "changes": spec["flags"],
            }
        )
    return {
        "proposal": proposal,
        "revision": revision,
        "changed": changed_any,
        "pages": pages,
        "assets": requested,
        "source_digest": digest,
    }


# ------------------- K3 (issue #43): bounded mapping inspection + receipts

# The core-controlled measured-evidence area (plan §2: receipts are retained
# in the project's evidence area with atomic persistence — operator-owned
# ignored state beside the validation evidence, never a Git artifact).
EVIDENCE_REL = proposals.ARIADNE_STATE_DIR / "evidence"
_RECEIPT_ID_RE = re.compile(r"mr-[0-9a-f]{16}")


def _receipt_path(project: Path, proposal: str, receipt_id: str) -> Path:
    """Where one mapping-evidence receipt lives (``.ariadne/evidence/<id>/``)."""
    if not isinstance(receipt_id, str) or not _RECEIPT_ID_RE.fullmatch(receipt_id):
        raise ValueError(f"{receipt_id!r} is not a mapping-evidence receipt id (mr-<16 hex>)")
    return project / EVIDENCE_REL / proposal / f"{receipt_id}.json"


def store_receipt(project: Path, proposal: str, receipt: dict) -> Path:
    """Persist one receipt ATOMICALLY and durably (the proposal-record
    discipline: data synced, tmp+os.replace, directory entry synced) under the
    operator-owned ``.ariadne/evidence/<proposal>/`` — separate from committed
    artifacts, so evidence never changes the revision it measures."""
    path = _receipt_path(project, proposal, receipt["receipt_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    proposals._fsync_path(path.parent)
    return path


def load_receipt(project: Path, proposal: str, receipt_id: str) -> dict:
    """Load and INTEGRITY-CHECK one retained receipt: a missing, unreadable,
    tampered or malformed record is an explicit error — never a silent pass
    (an allowlisted id or count proves nothing, spec 0010 §7)."""
    path = _receipt_path(project, proposal, receipt_id)
    entry = proposals._lstat(path)
    if entry is None:
        raise ValueError(
            f"receipt {receipt_id!r} does not resolve in the project's evidence "
            f"records ({path} is absent) — allowlisting an id is not proof"
        )
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(f"{path}: refusing a non-regular receipt — inspect it by hand")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: unreadable receipt ({exc})") from None
    if not isinstance(receipt, dict) or receipt.get("receipt_id") != receipt_id:
        raise ValueError(f"{path}: malformed receipt — it does not carry its own identity")
    recorded = receipt.pop("integrity_digest", None)
    if not isinstance(recorded, str) or _canonical_digest(receipt) != recorded:
        raise ValueError(
            f"{path}: receipt integrity check failed — the recorded measurements do "
            "not match their integrity digest (tampered or truncated evidence)"
        )
    receipt["integrity_digest"] = recorded
    return receipt


def _quote(identifier: str) -> str:
    """Quote one SQL identifier (the profiler discipline: catalog-validated
    names, doubled inner quotes — no identifier is ever interpolated raw)."""
    return '"' + identifier.replace('"', '""') + '"'


def _sql_ref(ref: str) -> str:
    """The catalog entry's plain dotted ``ref`` as a SQL-qualified prefix.
    The builder emits ``<alias>.<schema>`` for attaches (schema-only for
    file views); the alias is everything before the FIRST dot — a schema may
    itself contain dots and is quoted as ONE identifier with the same
    discipline as the table name (``warehouse.sales.west`` renders
    ``"warehouse"."sales.west"``; the table is quoted by the caller)."""
    alias, dot, schema = ref.partition(".")
    return f"{_quote(alias)}.{_quote(schema)}" if dot else _quote(ref)


def _scope_for(resource: str, scope: list[dict]) -> list[dict]:
    return [predicate for predicate in scope if predicate["resource"] == resource]


def _scope_clause(scope: list[dict]) -> tuple[str, list]:
    """The parameterized WHERE conjunct of one asset's scope predicates
    (plan §2: scope values are bound as parameters, never interpolated)."""
    clauses: list[str] = []
    params: list = []
    for predicate in scope:
        column = _quote(predicate["column"])
        if predicate["op"] == "in":
            marks = ", ".join("?" for _ in predicate["value"])
            clauses.append(f"{column} IN ({marks})")
            params.extend(predicate["value"])
        else:
            operator = {"eq": "=", "gte": ">=", "lt": "<"}[predicate["op"]]
            clauses.append(f"{column} {operator} ?")
            params.append(predicate["value"])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def inspection_sample_statement(
    table: dict, columns: list[str], scope: list[dict], limit: int
) -> tuple[str, list]:
    """The bounded, deterministic materialized-sample statement of one
    participating asset (plan §2): exactly the candidate's bound columns are
    projected (no all-column scan), identifiers are quoted catalog-validated
    names, scope values ride as parameters, and the sample is ordered by the
    bound columns so repeated inspections of unchanged inputs measure the
    same rows. The LIMIT bound is itself a parameter."""
    projection = ", ".join(_quote(column) for column in columns)
    ordering = ", ".join(_quote(column) for column in columns)
    where, params = _scope_clause(scope)
    sql = (
        f"SELECT {projection} FROM {_sql_ref(table['ref'])}.{_quote(table['name'])}{where} "
        f"ORDER BY {ordering} LIMIT ?"
    )
    return sql, [*params, int(limit)]


def inspection_count_statement(
    table: dict, columns: list[str], scope: list[dict]
) -> tuple[str, list]:
    """The full-data eligible/null aggregate of one side's measured columns:
    ``eligible`` counts scoped rows whose measured tuple is complete,
    ``nulls`` scoped rows with any null component — the honest denominators a
    sampled coverage ratio reports against (the scan itself stays bounded by
    the shared deadline, never by a cheap LIMIT)."""
    non_null = " AND ".join(f"{_quote(column)} IS NOT NULL" for column in columns)
    any_null = " OR ".join(f"{_quote(column)} IS NULL" for column in columns)
    where, params = _scope_clause(scope)
    sql = (
        f"SELECT COUNT(*) FILTER (WHERE {non_null}) AS eligible, "
        f"COUNT(*) FILTER (WHERE {any_null}) AS nulls "
        f"FROM {_sql_ref(table['ref'])}.{_quote(table['name'])}{where}"
    )
    return sql, params


def _guarded(con, budget, sql: str, params: list):
    """Execute one core-generated guarded statement: single-statement guard,
    read-only by construction, parameters bound, and the shared deadline's
    interrupt armed — an over-budget read STOPS here."""
    execution.assert_single_statement(sql)
    with budget.guard(con):
        return con.execute(sql, params).fetchall()


def _participant(resource: str, catalog: list[dict]) -> dict:
    """The approved catalog table of one canonical resource, with the
    cross-source participation refusal (an unapproved source never
    participates) and the unknown-asset refusal distinct."""
    for entry in catalog:
        for table in entry["tables"]:
            if table.get("resource") == resource:
                return table
    _kind, parts = parse_resource(resource)
    names = {entry["name"] for entry in catalog}
    if parts[0] not in names:
        raise ValueError(
            f"the candidate names source {parts[0]!r} which is not an approved "
            f"registry identity (approved: {', '.join(sorted(names)) or 'none'}) — a "
            "cross-source candidate participates only when EVERY participating "
            "source is approved; nothing was measured"
        )
    raise ValueError(
        f"catalog asset {resource!r} is not present in the approved resolved source "
        "identity — nothing was measured"
    )


def _column_type(table: dict, column: str) -> str:
    for entry in table["columns"]:
        if entry["name"] == column:
            return entry["type"]
    raise ValueError(
        f"column {column!r} is not present in the catalog asset "
        f"{table.get('resource')!r} — the candidate binds exact approved columns only"
    )


def _check_family_types(candidate: dict, tables: dict) -> None:
    """The lossy-coercion refusal (plan §2): equality compares compatible
    types position-by-position; prefix components and the target are
    string-typed; lookup keys/values compare compatibly with the fact side.
    A string beside a numeric column is NEVER silently coerced."""
    family = candidate["family"]
    if family == "equality":
        for left, right in zip(candidate["left"], candidate["right"], strict=True):
            left_type = _column_type(tables[candidate["left"][0]["resource"]], left["column"])
            right_type = _column_type(tables[candidate["right"][0]["resource"]], right["column"])
            if not profiler.types_compatible(left_type, right_type):
                raise ValueError(
                    f"incompatible types for an equality candidate: "
                    f"{left['column']} is {left_type} and {right['column']} is "
                    f"{right_type} — no lossy coercion is applied (string identifier "
                    "equivalence is never inferred from a numeric cast); nothing was "
                    "measured"
                )
    elif family == "prefix":
        components = [*candidate["left"], *candidate["right"]]
        if candidate.get("prefix_lookup"):
            components.append(candidate["prefix_lookup"]["prefix_field"])
        for binding in components:
            the_type = _column_type(tables[binding["resource"]], binding["column"])
            if the_type.split("(")[0].upper() != "VARCHAR":
                raise ValueError(
                    f"a prefix candidate's string components must be VARCHAR: "
                    f"{binding['column']} is {the_type} — no trim/pad/case-fold or "
                    "cast participates; nothing was measured"
                )
    else:  # lookup
        lookup = candidate["lookup"]
        for fact, remote in (
            *zip(candidate["left"], lookup["key_fields"], strict=True),
            *zip(candidate["right"], lookup["value_fields"], strict=True),
        ):
            fact_type = _column_type(tables[candidate["left"][0]["resource"]], fact["column"])
            remote_type = _column_type(tables[lookup["asset"]], remote["column"])
            if not profiler.types_compatible(fact_type, remote_type):
                raise ValueError(
                    f"incompatible types for a lookup candidate: {fact['column']} is "
                    f"{fact_type} and {remote['column']} is {remote_type} — no lossy "
                    "coercion is applied; nothing was measured"
                )


def _collision_view(values: list[tuple]) -> dict:
    """Duplicate tuple values among the tested rows: how many values repeat
    and the highest multiplicity — the fan-out evidence that a bare join on
    the compared value would multiply rows (AC5)."""
    counts = Counter(values)
    repeated = [count for count in counts.values() if count > 1]
    return {
        "values": len(repeated),
        "max_multiplicity": max(repeated, default=1),
    }


def _jsonable(value):
    return profiler._jsonable(value)


def _shape_summary(rows: list[dict], column: str) -> dict:
    """The bounded AGGREGATE identifier-shape summary of one requested binding
    (K3 fix pass, finding 7, spec 0010 §7 "identifier-shape summaries"): nulls,
    distinct-within-sample, string length min/max/avg and disjoint charset
    classes over the asset's EXISTING permitted sample — aggregates only,
    never a raw value (raw examples stay behind the operator's explicit sample
    permission)."""
    values = [row[column] for row in rows]
    present = [value for value in values if value is not None]
    summary: dict = {
        "sampled": len(values),
        "nulls": len(values) - len(present),
        "distinct": len({str(value) for value in present}),
    }
    strings = [value for value in present if isinstance(value, str)]
    if strings:
        lengths = [len(value) for value in strings]
        summary["length"] = {
            "min": min(lengths),
            "max": max(lengths),
            "avg": round(sum(lengths) / len(lengths), 2),
        }
        summary["charset"] = {
            "digits_only": sum(1 for value in strings if value.isdigit()),
            "letters_only": sum(1 for value in strings if value.isalpha()),
            "mixed_alphanumeric": sum(
                1
                for value in strings
                if value.isalnum() and not value.isalpha() and not value.isdigit()
            ),
            "other_characters": sum(1 for value in strings if not value.isalnum()),
        }
    return summary


def _measure(
    con,
    budget,
    candidate: dict,
    tables: dict,
    limits: dict,
) -> dict:
    """Run the guarded statements of one normalized candidate and assemble the
    measured evidence (counts only by default — raw examples ride separately
    under the operator's sample permission). Every statement draws the SAME
    deadline; each participating asset materializes at most ``sample_rows``
    rows (K3 fix pass, finding 2: ONE bounded union-column sample PER ASSET,
    reused by every side/lookup that reads that asset), ordered by the bound
    columns so repeated inspections of unchanged inputs measure the same
    rows."""
    family = candidate["family"]
    left_table = tables[candidate["left"][0]["resource"]]
    right_table = tables[candidate["right"][0]["resource"]]
    left_columns = [binding["column"] for binding in candidate["left"]]
    right_columns = [binding["column"] for binding in candidate["right"]]
    pairing = candidate.get("pairing") or []
    pairing_left = [pair["left"]["column"] for pair in pairing]
    pairing_right = [pair["right"]["column"] for pair in pairing]
    scope = candidate.get("scope") or []
    sample_rows = int(limits["sample_rows"])
    example_budget = int(limits["examples"])

    unavailable: list[str] = []

    # K3 fix pass (finding 2): the union of measured columns per participating
    # asset — exactly one bounded sample is taken per asset, in this
    # deterministic binding order, and every side/lookup reads that sample.
    asset_columns: dict[str, list[str]] = {}

    def _union(resource: str, columns: list[str]) -> None:
        merged = asset_columns.setdefault(resource, [])
        for column in columns:
            if column not in merged:
                merged.append(column)

    lookup = candidate.get("lookup")
    prefix_lookup = candidate.get("prefix_lookup")
    _union(left_table["resource"], left_columns)
    _union(right_table["resource"], right_columns)
    _union(left_table["resource"], pairing_left)
    _union(right_table["resource"], pairing_right)
    if prefix_lookup:
        _union(
            prefix_lookup["asset"],
            [binding["column"] for binding in prefix_lookup["key_fields"]]
            + [prefix_lookup["prefix_field"]["column"]],
        )
    if lookup:
        _union(
            lookup["asset"],
            [binding["column"] for binding in lookup["key_fields"]]
            + [binding["column"] for binding in lookup["value_fields"]],
        )

    def sample(table: dict) -> list[dict]:
        """One asset's bounded materialized sample; a source read that fails
        (an absent location, an unreadable backend) is DISCLOSED as an
        unavailable measurement — an honest empty sample, never a passing
        check and never an invented count."""
        columns = asset_columns[table["resource"]]
        sql, params = inspection_sample_statement(
            table, columns, _scope_for(table["resource"], scope), sample_rows
        )
        try:
            rows = _guarded(con, budget, sql, params)
        except ValueError:
            raise  # the deadline refusal propagates: nothing partial persists
        except duckdb.Error as exc:
            unavailable.append(
                f"the materialized sample of {table['resource']} could not be read "
                f"({type(exc).__name__}) — no rows of this asset were tested"
            )
            return []
        return [dict(zip(columns, row)) for row in rows]

    samples: dict[str, list[dict]] = {
        resource: sample(tables[resource]) for resource in asset_columns
    }
    left_sample = samples[left_table["resource"]]
    right_sample = samples[right_table["resource"]]

    # full-data denominators per side: the deadline bounds the scan itself,
    # and any unavailable count is disclosed, never guessed. For the lookup
    # family the fact side's keys AND values are one complete measured tuple
    # on the SAME asset (K3 fix pass, finding 4: the right side never inherits
    # a keys-only denominator).
    eligible: dict[str, object] = {}
    nulls: dict[str, object] = {}
    fact_tuple = [*left_columns, *right_columns]
    measured_columns = {
        "left": left_columns if family != "lookup" else fact_tuple,
        "right": right_columns if family != "lookup" else fact_tuple,
    }
    for side, table in (("left", left_table), ("right", right_table)):
        if family == "lookup" and table is left_table and "left" in eligible:
            eligible["right"], nulls["right"] = eligible["left"], nulls["left"]
            continue  # keys and values live on the same measured asset/tuple
        sql, params = inspection_count_statement(
            table, measured_columns[side], _scope_for(table["resource"], scope)
        )
        try:
            row = _guarded(con, budget, sql, params)[0]
        except ValueError:
            raise  # the deadline refusal propagates: nothing partial persists
        except duckdb.Error as exc:
            eligible[side], nulls[side] = None, None
            unavailable.append(
                f"counts.{side}: the eligible/null denominator could not be read "
                f"({type(exc).__name__}) — coverage ratios over this side are "
                "not asserted"
            )
            continue
        eligible[side], nulls[side] = int(row[0]), int(row[1])

    # a tested row carries a complete measured tuple: the left components (and,
    # for the lookup family, the mapped fact values too — a null value is not a
    # comparable measurement)
    left_complete = left_columns if family != "lookup" else fact_tuple
    tested_left = [row for row in left_sample if all(row[c] is not None for c in left_complete)]
    tested_right = [row for row in right_sample if all(row[c] is not None for c in right_columns)]
    left_tuples = [tuple(row[c] for c in left_columns) for row in tested_left]
    right_tuples = [tuple(row[c] for c in right_columns) for row in tested_right]

    def lookup_side_measurement(table: dict, columns: list[str]) -> dict:
        """The lookup asset's own honest denominators (K3 fix pass, finding 4):
        complete-tuple eligible/null counts, the sampled tested count and the
        sampled null rows — a truncated lookup sample can never masquerade as
        a fully measured lookup."""
        sql, params = inspection_count_statement(
            table, columns, _scope_for(table["resource"], scope)
        )
        try:
            row = _guarded(con, budget, sql, params)[0]
            count_eligible, count_nulls = int(row[0]), int(row[1])
        except ValueError:
            raise
        except duckdb.Error as exc:
            count_eligible = count_nulls = None
            unavailable.append(
                f"counts of the lookup asset {table['resource']} could not be read "
                f"({type(exc).__name__}) — its sampled/full designation is not "
                "asserted"
            )
        rows = samples[table["resource"]]
        complete = [r for r in rows if all(r[c] is not None for c in columns)]
        return {
            "asset": table["resource"],
            "eligible": count_eligible,
            "nulls": count_nulls,
            "tested": len(complete),
            "null_rows_sampled": len(rows) - len(complete),
            "rows_sampled": len(rows),
        }

    measurement: dict = {
        "counts": {
            "eligible_left": eligible["left"],
            "eligible_right": eligible["right"],
            "tested_left": len(tested_left),
            "tested_right": len(tested_right) if family != "lookup" else len(tested_left),
            "unavailable": unavailable,
        },
        "null_counts": {"left": nulls["left"], "right": nulls["right"]},
        "unknown_lookup_count": 0,
        "missing_key_count": 0,
        "ambiguous_key_count": 0,
        "multiplicity": {"lookup_duplicate_keys": 0, "lookup_max_rows_per_key": 1},
        "collisions": {
            "left": {"values": 0, "max_multiplicity": 1},
            "right": {"values": 0, "max_multiplicity": 1},
        },
        # K3 fix pass (finding 7): every REQUESTED binding's bounded aggregate
        # shape summary, from the existing per-asset samples
        "shapes": [
            {"resource": resource, "column": column, **_shape_summary(samples[resource], column)}
            for resource, columns in asset_columns.items()
            for column in columns
        ],
    }
    limitations: list[str] = []
    examples: list[dict] = []

    if family == "lookup":
        assert lookup is not None  # validate_inspection_candidate requires this family's asset.
        # the explicit approved lookup: missing keys, duplicates, ambiguity and
        # multiplicity are REPORTED — a many-valued lookup never collapses
        key_columns = [b["column"] for b in lookup["key_fields"]]
        value_columns = [b["column"] for b in lookup["value_fields"]]
        lookup_counts = lookup_side_measurement(
            tables[lookup["asset"]], key_columns + value_columns
        )
        measurement["lookup_counts"] = lookup_counts
        fully_measured = (
            lookup_counts["eligible"] is not None
            and lookup_counts["tested"] >= lookup_counts["eligible"]
        )
        lookup_index: dict[tuple, list[tuple]] = {}
        for row in samples[lookup["asset"]]:
            if any(row[c] is None for c in key_columns + value_columns):
                continue  # the null row is counted above, never silently dropped
            lookup_index.setdefault(tuple(row[c] for c in key_columns), []).append(
                tuple(row[c] for c in value_columns)
            )
        repeated = [len(values) for values in lookup_index.values() if len(values) > 1]
        measurement["multiplicity"] = {
            "lookup_duplicate_keys": len(repeated),
            "lookup_max_rows_per_key": max(repeated, default=1),
        }
        matched = mismatched = 0
        for row, keys in zip(tested_left, left_tuples, strict=True):
            values = lookup_index.get(keys)
            fact_values = tuple(row[c] for c in right_columns)
            if values is None:
                # a fact key beyond the SAMPLED lookup rows is an unknown
                # lookup, not a missing key — unless the lookup was fully
                # measured (finding 4)
                if fully_measured:
                    measurement["missing_key_count"] += 1
                    outcome = "missing"
                else:
                    measurement["unknown_lookup_count"] += 1
                    outcome = "unknown-lookup"
            elif len(set(values)) > 1:
                measurement["ambiguous_key_count"] += 1
                outcome = "ambiguous"
            elif values[0] == fact_values:
                matched += 1
                outcome = "matched"
            else:
                mismatched += 1
                outcome = "mismatch"
            if example_budget and len(examples) < example_budget:
                examples.append(
                    {
                        "keys": {column: _jsonable(row[column]) for column in left_columns},
                        "fact_values": {column: _jsonable(row[column]) for column in right_columns},
                        "lookup_values": [list(map(_jsonable, value)) for value in (values or [])],
                        "outcome": outcome,
                    }
                )
        measurement["coverage"] = {
            "left_in_right": {"matched": matched, "tested": len(tested_left)},
            "right_in_left": {"matched": matched, "tested": len(tested_left)},
        }
        measurement["distinct_matched"] = matched
        measurement["mismatch_count"] = mismatched
        measurement["collisions"] = {
            "left": _collision_view(left_tuples),
            "right": _collision_view(right_tuples),
        }
        measurement["pairing"] = {
            "keys": [],
            "status": "absent",
            "paired": 0,
            "ambiguous_keys": 0,
            "max_rows_per_key": 1,
        }
        measurement["comparison_basis"] = "key-paired"
        limitations.append(
            "the lookup's scoped keys pair the sampled fact rows with the lookup "
            "asset's sampled rows"
        )
    else:
        # the compared value of each tested row: the tuple itself (equality)
        # or the constructed prefix value (prefix family)
        lookup_counts = None
        if family == "prefix":
            separator = candidate["separator"]
            key_arity = 0
            prefix_index: dict[tuple, list] = {}
            if prefix_lookup:
                key_arity = len(prefix_lookup["key_fields"])
                key_columns = [b["column"] for b in prefix_lookup["key_fields"]]
                prefix_column = prefix_lookup["prefix_field"]["column"]
                lookup_counts = lookup_side_measurement(
                    tables[prefix_lookup["asset"]], key_columns + [prefix_column]
                )
                measurement["lookup_counts"] = lookup_counts
                for row in samples[prefix_lookup["asset"]]:
                    if any(row[c] is None for c in key_columns) or row[prefix_column] is None:
                        continue
                    prefix_index.setdefault(tuple(row[c] for c in key_columns), []).append(
                        row[prefix_column]
                    )
                repeated = [len(v) for v in prefix_index.values() if len(v) > 1]
                measurement["multiplicity"] = {
                    "lookup_duplicate_keys": len(repeated),
                    "lookup_max_rows_per_key": max(repeated, default=1),
                }
            left_pairs: list[tuple[dict, tuple]] = []
            for row, components in zip(tested_left, left_tuples, strict=True):
                if prefix_lookup:
                    values = prefix_index.get(tuple(components[:key_arity]))
                    if not values:
                        measurement["unknown_lookup_count"] += 1
                        continue
                    if len(set(values)) > 1:
                        measurement["ambiguous_key_count"] += 1
                        continue  # an ambiguous prefix lookup is disclosed, not collapsed
                    prefix_value = values[0]
                    value = separator.join(
                        str(part) for part in (prefix_value, *components[key_arity:])
                    )
                else:
                    value = separator.join(str(part) for part in components)
                row["__constructed"] = value
                left_pairs.append((row, (value,)))
        else:
            left_pairs = list(zip(tested_left, left_tuples, strict=True))
        right_pairs = list(zip(tested_right, right_tuples, strict=True))
        left_compare = [value for _row, value in left_pairs]
        right_compare = [value for _row, value in right_pairs]
        right_values, left_values = set(right_compare), set(left_compare)
        matched_left = [value for value in left_compare if value in right_values]
        matched_right = [value for value in right_compare if value in left_values]
        measurement["coverage"] = {
            # the denominator is every sampled eligible row — an unresolvable
            # row (unknown/ambiguous lookup key) stays in it, unmatched
            "left_in_right": {"matched": len(matched_left), "tested": len(tested_left)},
            "right_in_left": {"matched": len(matched_right), "tested": len(tested_right)},
        }
        measurement["distinct_matched"] = len(set(matched_left))
        measurement["collisions"] = {
            "left": _collision_view(left_compare),
            "right": _collision_view(right_compare),
        }
        measurement["mismatch_count"] = len(left_compare) - len(matched_left)
        # independently paired comparison when pairing keys are supplied and
        # actually pair sampled records. K3 fix pass (finding 3): EVERY right
        # row is retained per pairing key — a key carrying multiple right rows
        # is disclosed as an ambiguous pairing and never silently collapsed to
        # the last row's value, so the basis never claims unique independent
        # pairing.
        paired = mismatches = ambiguous_keys = 0
        by_key: dict[tuple, list[tuple]] = {}
        if pairing:
            for row, value in right_pairs:
                if all(row[c] is not None for c in pairing_right):
                    by_key.setdefault(tuple(row[c] for c in pairing_right), []).append(value)
            ambiguous_keys = sum(1 for values in by_key.values() if len(values) > 1)
        max_rows_per_key = max((len(values) for values in by_key.values()), default=1)
        for row, value in left_pairs:
            if not pairing or not all(row[c] is not None for c in pairing_left):
                continue
            values = by_key.get(tuple(row[c] for c in pairing_left))
            if not values or len(values) > 1:
                continue  # unpaired or ambiguous: disclosed, never collapsed
            paired += 1
            if values[0] != value:
                mismatches += 1
        status = "absent"
        if pairing:
            if ambiguous_keys:
                status = "ambiguous"
            elif paired:
                status = "usable"
            else:
                status = "unusable"
        measurement["pairing"] = {
            "keys": [{"left": pair["left"], "right": pair["right"]} for pair in pairing],
            "status": status,
            "paired": paired,
            "ambiguous_keys": ambiguous_keys,
            "max_rows_per_key": max_rows_per_key,
        }
        if pairing and (paired or ambiguous_keys):
            if ambiguous_keys:
                measurement["comparison_basis"] = "ambiguous-pairing"
                measurement["mismatch_count"] = mismatches
                limitations.append(
                    f"{ambiguous_keys} sampled pairing key(s) carry multiple right "
                    f"rows (up to {max_rows_per_key} per key) — the paired comparison "
                    "cannot claim unique independent pairing"
                )
                if paired:
                    limitations.append(
                        f"paired comparison over {paired} unambiguously keyed sampled record(s)"
                    )
                else:
                    limitations.append("no sampled record pair could be compared unambiguously")
            else:
                measurement["comparison_basis"] = "independently-paired"
                measurement["mismatch_count"] = mismatches
                limitations.append(
                    f"paired comparison over {paired} independently keyed sampled record(s)"
                )
        else:
            measurement["comparison_basis"] = "containment-only"
            if pairing:
                limitations.append(
                    "the supplied pairing keys matched no sampled record pair — only "
                    "value containment was measured"
                )
        if example_budget:
            for row, value in left_pairs:
                if len(examples) >= example_budget:
                    break
                entry: dict = {"matched": value in right_values}
                if family == "prefix":
                    entry["components"] = {
                        column: _jsonable(row[column]) for column in left_columns
                    }
                    entry["constructed"] = value[0]
                    targets = [
                        r[right_columns[0]] for r in tested_right if (r[right_columns[0]],) == value
                    ]
                    entry["target"] = _jsonable(targets[0]) if targets else None
                else:
                    entry["left"] = {column: _jsonable(row[column]) for column in left_columns}
                examples.append(entry)

    complete_counts = (
        measurement["counts"]["eligible_left"] is not None
        and measurement["counts"]["eligible_right"] is not None
    )
    fact_full = complete_counts and (
        measurement["counts"]["tested_left"] >= measurement["counts"]["eligible_left"]
        and measurement["counts"]["tested_right"] >= measurement["counts"]["eligible_right"]
    )
    # K3 fix pass (finding 4): a truncated lookup sample forbids the 'full'
    # designation even when every fact row was tested — and the truncation is
    # disclosed, because keys beyond the sample are unknown lookups.
    lookup_full = lookup_counts is None or (
        lookup_counts["eligible"] is not None
        and lookup_counts["tested"] >= lookup_counts["eligible"]
    )
    measurement["designation"] = designation = "full" if (fact_full and lookup_full) else "sampled"
    if designation == "sampled":
        limitations.append(
            f"sampled completion: {measurement['counts']['tested_left']} of "
            f"{measurement['counts']['eligible_left']} eligible left rows and "
            f"{measurement['counts']['tested_right']} of "
            f"{measurement['counts']['eligible_right']} eligible right rows were "
            "tested — completion of the stated sample, never full-data proof"
        )
    if lookup_counts is not None and not lookup_full:
        limitations.append(
            f"the lookup asset {lookup_counts['asset']} was sampled at "
            f"{lookup_counts['tested']} of {lookup_counts['eligible']} eligible rows — "
            "a fact key beyond the sampled lookup rows is an unknown lookup, not a "
            "missing key"
        )
    if lookup_counts is not None and lookup_counts["null_rows_sampled"]:
        limitations.append(
            f"{lookup_counts['null_rows_sampled']} sampled lookup row(s) carried a "
            "null key or value and were not indexed"
        )
    limitations.append(
        "containment and pairing were measured over the materialized samples of "
        f"each participating asset (at most {sample_rows} rows per asset)"
    )
    limitations.extend(unavailable)
    measurement["outcome"] = "inconclusive" if unavailable else "complete"
    measurement["limitations"] = limitations
    if example_budget:
        measurement["examples"] = examples
    return measurement


def _asset_schema_digest(table: dict | None) -> str | None:
    """The digest of one dependency asset's FULL schema identity (K3 fix
    pass, finding 6): every catalog column's (name, type) at measurement
    time — beside the per-column identity ``dependencies.assets`` already
    carries, this binds the lookup asset's complete schema so ANY schema
    change on it invalidates the receipt immediately."""
    if not table:
        return None
    return _canonical_digest([(column["name"], column["type"]) for column in table["columns"]])


def _cited_policy_digest(worktree: Path, resource: str) -> str | None:
    """The sha256 of one cited dependency page inside the proposal's
    worktree — None (an honestly UNKNOWN dependency identity) when the
    resource is unreadable or escapes the worktree."""
    try:
        resolved = (worktree / resource).resolve()
        if not resolved.is_relative_to(worktree.resolve()):
            return None
        return _sha256_hex(resolved.read_bytes())
    except OSError:
        return None


def _cited_policy_dependencies(
    project: Path, proposal: str, revision: str, measured_digest: str
) -> list[dict]:
    """The cited Policy/OSI dependency identities of every Reference page in
    the proposal's CURRENT candidate that declares THIS exact candidate (K3
    fix pass, finding 6, spec 0010 §8): each such mapping's cited
    ``source_ids`` resolve to the page's ``sources[]`` resources, whose
    current content digests the receipt binds — a changed cited Policy page
    then invalidates the dependent evidence at verification. Resources are
    read from the proposal worktree (the candidate's own tracked pages and
    documents); an unreadable dependency is recorded with a null digest and
    can never verify as unchanged."""
    worktree = project / proposals.WORKTREES_REL / proposal
    entries: dict[str, dict] = {}
    for page in _reference_pages_at(project, revision).values():
        for mapping in page["meta"]["ariadne"].get("mappings") or []:
            if not isinstance(mapping, dict):
                continue
            try:
                if candidate_digest(mapping.get("candidate")) != measured_digest:
                    continue
            except ValueError:
                continue
            sources = {
                source.get("id"): source.get("resource")
                for source in page["meta"].get("sources") or []
                if isinstance(source, dict)
            }
            for source_id in mapping.get("source_ids") or []:
                resource = sources.get(source_id)
                if not isinstance(resource, str) or not resource or resource in entries:
                    continue
                entries[resource] = {
                    "resource": resource,
                    "digest": _cited_policy_digest(worktree, resource),
                }
    return [entries[resource] for resource in sorted(entries)]


def inspect_mapping(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    candidate: object,
    limits: object = None,
) -> dict:
    """The ONE typed mapping-inspection operation (plan §2 ``inspect_mapping``,
    spec 0010 §7; issue #43/K3): measure a structured candidate from exactly
    the approved families — equality/composite, string prefix with an optional
    scoped prefix lookup, explicit scoped lookup — against the
    operator-APPROVED resolved source identity, through guarded core-generated
    read-only statements with parameterized scope, under the operator-owned
    finite ceilings (a request may only LOWER them), and retain the receipt
    atomically in the core-controlled ``.ariadne/`` evidence area. Never a
    page edit, never approval, never admission; aggregate counts are the
    default output and raw identifier examples need the operator's explicit
    sample permission."""
    project = Path(project).resolve()
    normalized = validate_inspection_candidate(candidate)
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if expected_revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the "
            f"inspection expected {expected_revision} — re-read the candidate and "
            "retry with the current revision; nothing was measured"
        )
    resolved, digest = authoring_sources.candidate_sources(project, current)
    if resolved is None:
        raise ValueError(
            f"proposal {proposal} declares no source entries in its candidate "
            f"registry at {current[:12]} — there is nothing to inspect"
        )
    assert digest is not None
    approval = authoring_sources._effective_grant(project, resolved, digest, proposal, current)
    effective = effective_inspection_limits(project_inspection_limits(project), limits)
    budget = execution.DeadlineBudget(effective["execution_seconds"])
    owned = execution.DuckDBExecution(
        authoring_sources.identity_registry(approval["sources"], approval.get("storage_bindings")),
        budget=budget,
    )
    try:
        con, catalog = owned.con, owned.catalog
        tables: dict[str, dict] = {}
        for binding in [
            *normalized["left"],
            *normalized["right"],
            *(normalized.get("scope") or []),
            *(
                pair[pairing_side]
                for pair in (normalized.get("pairing") or [])
                for pairing_side in ("left", "right")
            ),
            *(
                [
                    *normalized["prefix_lookup"]["key_fields"],
                    normalized["prefix_lookup"]["prefix_field"],
                ]
                if normalized.get("prefix_lookup")
                else []
            ),
            *(
                [
                    *normalized["lookup"]["key_fields"],
                    *normalized["lookup"]["value_fields"],
                ]
                if normalized.get("lookup")
                else []
            ),
        ]:
            if binding["resource"] not in tables:
                tables[binding["resource"]] = _participant(binding["resource"], catalog)
            # K3 fix pass (finding 1): EVERY bound column (sides, scope,
            # pairing, lookup fields) exists on its catalog asset BEFORE any
            # statement runs — a missing column is an up-front refusal, never
            # a mid-measurement "unavailable" disclosure.
            _column_type(tables[binding["resource"]], binding["column"])
        _check_family_types(normalized, tables)
        measurement = _measure(con, budget, normalized, tables, effective)
    finally:
        owned.close()
    observed_at = datetime.now(UTC).isoformat(timespec="seconds")
    assets = []
    for resource, table in tables.items():
        bound = {
            binding["column"]
            for binding in [
                *normalized["left"],
                *normalized["right"],
                *(normalized.get("scope") or []),
                *(
                    pair[pairing_side]
                    for pair in (normalized.get("pairing") or [])
                    for pairing_side in ("left", "right")
                ),
                *(
                    [
                        *normalized["prefix_lookup"]["key_fields"],
                        normalized["prefix_lookup"]["prefix_field"],
                    ]
                    if normalized.get("prefix_lookup")
                    else []
                ),
                *(
                    [
                        *normalized["lookup"]["key_fields"],
                        *normalized["lookup"]["value_fields"],
                    ]
                    if normalized.get("lookup")
                    else []
                ),
            ]
            if binding["resource"] == resource
        }
        ordered = [column for column in table["columns"] if column["name"] in bound]
        assets.append(
            {
                "resource": resource,
                "source": table.get("source"),
                "catalog": table.get("catalog"),
                "schema": table.get("schema"),
                "table": table["name"],
                "columns": [{"name": c["name"], "type": c["type"]} for c in ordered],
            }
        )
    receipt = {
        "receipt_id": f"mr-{uuid.uuid4().hex[:16]}",
        "family": normalized["family"],
        "candidate": normalized,
        "candidate_digest": _canonical_digest(normalized),
        "proposal": proposal,
        "inspection_revision": current,
        "source_digest": digest,
        "source_identity": resolved,
        "approval_digest": approval.get("approval_digest") or digest,
        "storage_bindings": approval.get("storage_bindings") or {},
        "dependencies": {
            "assets": sorted(assets, key=lambda asset: asset["resource"]),
            "lookup": normalized.get("prefix_lookup") or normalized.get("lookup"),
            # K3 fix pass (finding 6, spec 0010 §8): the cited Policy/OSI
            # dependencies of the Reference pages that declare THIS candidate
            # in the current proposal candidate — the receipt binds their
            # content digests so a changed cited Policy page invalidates it.
            "policy_osi": _cited_policy_dependencies(
                project, proposal, current, _canonical_digest(normalized)
            ),
            # the lookup asset's FULL schema identity (its measured columns
            # ride dependencies.assets; any schema change on the lookup asset
            # invalidates immediately)
            "lookup_schema_digest": _asset_schema_digest(
                tables.get(
                    (normalized.get("prefix_lookup") or normalized.get("lookup") or {})["asset"]
                    if normalized.get("prefix_lookup") or normalized.get("lookup")
                    else ""
                )
            ),
        },
        "observed_at": observed_at,
        "version_signal": {"state": "as_of", "observed_at": observed_at},
        "scope": normalized.get("scope") or [],
        "pairing": measurement.pop("pairing"),
        "comparison_basis": measurement.pop("comparison_basis"),
        "sample_rows": effective["sample_rows"],
        **measurement,
    }
    receipt["integrity_digest"] = _canonical_digest(receipt)
    envelope = {
        "proposal": proposal,
        "revision": current,
        "receipt_id": receipt["receipt_id"],
        "receipt": receipt,
        # K3 fix pass (finding 8): the COMPLETE final envelope (evidence path
        # included) is what the response ceiling measures — and the receipt is
        # retained only after the complete envelope fits.
        "evidence": str(_receipt_path(project, proposal, receipt["receipt_id"])),
    }
    size = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
    if size > effective["response_bytes"]:
        raise ValueError(
            f"the serialized inspection response is {size} bytes, over the "
            f"{effective['response_bytes']}-byte ceiling — lower the raw-example "
            "count or narrow the candidate; no receipt was retained"
        )
    store_receipt(project, proposal, receipt)
    return envelope


def _receipt_summary(receipt: dict) -> dict:
    """The bounded, credential-free verified summary of one retained receipt —
    exactly the fields a finalized Reference page may cite (plan §2: bounded
    summaries only, never raw examples, never model-authored counts)."""
    counts = receipt["counts"]
    return {
        "id": receipt["receipt_id"],
        "digest": receipt["integrity_digest"],
        "family": receipt["family"],
        "outcome": receipt["outcome"],
        "designation": receipt["designation"],
        "comparison_basis": receipt["comparison_basis"],
        "tested_left": counts["tested_left"],
        "tested_right": counts["tested_right"],
        "eligible_left": counts["eligible_left"],
        "eligible_right": counts["eligible_right"],
        "matched_left_in_right": receipt["coverage"]["left_in_right"]["matched"],
        "matched_right_in_left": receipt["coverage"]["right_in_left"]["matched"],
        "mismatch_count": receipt["mismatch_count"],
        "observed_at": receipt["observed_at"],
    }


def _current_asset_columns(catalog: list[dict]) -> dict[str, list[dict]]:
    """resource -> [{name, type}] of every asset the approved identity holds."""
    columns: dict[str, list[dict]] = {}
    for entry in catalog:
        for table in entry["tables"]:
            columns[table["resource"]] = [
                {"name": column["name"], "type": column["type"]} for column in table["columns"]
            ]
    return columns


def _verify_receipt(
    receipt_id: str,
    project: Path,
    proposal: str,
    *,
    declaration_digest: str,
    source_digest: str | None,
    asset_columns: dict[str, list[dict]],
    endpoints: dict | None = None,
    worktree: Path | None = None,
    max_age_hours: float | None = None,
    storage_bindings: dict | None = None,
) -> tuple[dict | None, str | None]:
    """Verify ONE cited receipt against the project's evidence records and the
    current dependency identities (spec 0010 §§7–8): existence, integrity, the
    normalized DECLARATION the receipt measured, the ENDPOINT correspondence
    of the mapping's representations (K3 fix pass, finding 5: the measured
    left/right bindings and scope must correspond to the declared endpoints —
    a retargeted representation never keeps a verified summary), the resolved
    SOURCE identity it read, the measured ASSET/LOOKUP columns, the lookup
    asset's full schema digest, the bound cited Policy/OSI dependency digests
    (finding 6) and the operator's evidence age budget (finding 6: age bounds
    the RECEIPT's validity for attachment; unversioned data stays as_of).
    Returns (summary, None) or (None, error) — an allowlisted id or an
    author-authored count is never proof. Receipt validity is
    dependency-matched, not candidate-revision matched: an unrelated save
    commit keeps a receipt valid, a changed declaration/input does not
    (plan §2)."""
    try:
        receipt = load_receipt(project, proposal, receipt_id)
    except ValueError as exc:
        return None, str(exc)
    if receipt.get("candidate_digest") != declaration_digest:
        return None, (
            f"receipt {receipt_id!r} measures a different declaration (its normalized "
            f"candidate digest is {str(receipt.get('candidate_digest'))[:12]}, the "
            f"declared candidate's is {declaration_digest[:12]}) — changed mapping "
            "parameters invalidate dependent evidence; re-inspect the changed candidate"
        )
    if endpoints is not None:
        measured = receipt.get("candidate") or {}
        for key, side in (("from", "left"), ("to", "right")):
            declared = [
                (binding.get("resource"), binding.get("column"))
                for binding in endpoints[key]["fields"]
                if isinstance(binding, dict)
            ]
            measured_side = [
                (binding.get("resource"), binding.get("column"))
                for binding in measured.get(side) or []
                if isinstance(binding, dict)
            ]
            if declared != measured_side:
                return None, (
                    f"receipt {receipt_id!r} measured {side} bindings {measured_side} "
                    f"but the mapping's {key!r} representation declares {declared} — "
                    "retargeted endpoint representations invalidate dependent "
                    "evidence; re-inspect against the declared representation"
                )
        scope_columns = {
            (predicate.get("resource"), predicate.get("column"))
            for predicate in measured.get("scope") or []
            if isinstance(predicate, dict)
        }
        for key in ("from", "to"):
            for binding in endpoints[key]["scope"]:
                required = (binding.get("resource"), binding.get("column"))
                if required not in scope_columns:
                    return None, (
                        f"receipt {receipt_id!r} was not measured under the required "
                        f"scope {required} of the mapping's {key!r} representation — "
                        "evidence must correspond to the declared scope"
                    )
    if receipt.get("source_digest") != source_digest:
        return None, (
            f"receipt {receipt_id!r} was measured against a different resolved source "
            f"identity ({str(receipt.get('source_digest'))[:12]}, the candidate now "
            f"resolves to {str(source_digest)[:12]}) — changed inputs invalidate "
            "dependent evidence"
        )
    if storage_bindings is not None and (receipt.get("storage_bindings") or {}) != (
        storage_bindings or {}
    ):
        return None, (
            f"receipt {receipt_id!r} was measured against a different effective "
            "storage binding (spec 0025 §4) — an endpoint change invalidates "
            "dependent evidence; re-inspect against the current binding"
        )
    dependencies = receipt.get("dependencies") or {}
    lookup_asset = (dependencies.get("lookup") or {}).get("asset")
    schema_digest = dependencies.get("lookup_schema_digest")
    if schema_digest is not None and isinstance(lookup_asset, str):
        current = asset_columns.get(lookup_asset)
        if (
            current is None
            or _canonical_digest([(c["name"], c["type"]) for c in current]) != schema_digest
        ):
            return None, (
                f"receipt {receipt_id!r} depends on the lookup asset {lookup_asset!r} "
                "whose schema changed since the measurement — schema changes "
                "invalidate dependent evidence immediately"
            )
    for asset in dependencies.get("assets") or []:
        current = asset_columns.get(asset["resource"])
        if current is None:
            return None, (
                f"receipt {receipt_id!r} depends on asset {asset['resource']!r} which "
                "is no longer present in the approved resolved source identity"
            )
        recorded = [(column["name"], column["type"]) for column in asset["columns"]]
        wanted = {name for name, _type in recorded}
        now = [(column["name"], column["type"]) for column in current if column["name"] in wanted]
        if recorded != now:
            return None, (
                f"receipt {receipt_id!r} depends on asset {asset['resource']!r} whose "
                "measured columns changed since the measurement — schema changes "
                "invalidate dependent evidence immediately"
            )
    for dependency in dependencies.get("policy_osi") or []:
        resource = dependency.get("resource")
        current_digest = (
            _cited_policy_digest(worktree, resource)
            if isinstance(resource, str) and worktree is not None
            else None
        )
        if dependency.get("digest") is None or current_digest != dependency.get("digest"):
            return None, (
                f"receipt {receipt_id!r} depends on the cited Policy/OSI page "
                f"{resource!r} whose content changed since the measurement (or can "
                "no longer be read) — referenced Policy/OSI content changes "
                "invalidate dependent evidence immediately"
            )
    if max_age_hours is not None:
        observed = receipt.get("observed_at")
        try:
            observed_at = datetime.fromisoformat(observed) if isinstance(observed, str) else None
            if observed_at is None:
                raise ValueError(observed)
            age = datetime.now(UTC) - observed_at
        except ValueError, TypeError, OverflowError:
            return None, (
                f"receipt {receipt_id!r} carries no parseable measurement time — "
                "its freshness is unknown and can never be verified as current"
            )
        if age > timedelta(hours=max_age_hours):
            return None, (
                f"receipt {receipt_id!r} was measured at {observed} ({age} ago), "
                f"beyond the operator's {max_age_hours}h evidence age budget — age "
                "bounds the receipt's validity for attachment (unversioned data "
                "stays as-of); re-inspect to attach fresh evidence"
            )
    return _receipt_summary(receipt), None


def _reference_pages_at(project: Path, revision: str) -> dict[str, dict]:
    """The tracked structured Reference pages at one revision: path ->
    {meta, text}. Pages without the ``ariadne`` extension stay out (legacy
    References never carry mapping evidence)."""
    tracked = proposals._git(["ls-tree", "-r", "--name-only", revision], project).stdout
    pages: dict[str, dict] = {}
    for rel in tracked.split("\n"):
        if not rel.startswith("context_layer/references/") or not rel.endswith(".md"):
            continue
        if PurePosixPath(rel).name in proposals._GENERATED_FILES:
            continue
        blob = proposals._read_blob(project, revision, rel)
        if blob is None:  # pragma: no cover - ls-tree paths always resolve
            continue
        text = blob.decode("utf-8", "replace")
        try:
            meta = _load_frontmatter_meta(text)
        except yaml.YAMLError:
            continue  # a malformed draft page: the page gate owns the error
        extension = meta.get("ariadne") if isinstance(meta, dict) else None
        if isinstance(extension, dict) and extension.get("mappings"):
            pages[rel] = {"meta": meta, "text": text}
    return pages


EVIDENCE_COMMIT_MESSAGE = "ariadne: attach verified mapping evidence"


def _commit_core_pages(project: Path, record: dict, rels: list[str], message: str) -> str | None:
    """Commit EXACTLY the named core-authored page changes in the proposal
    worktree (the caller holds the proposal lock): any other change is the
    interrupted-transition refusal, exactly like the finalize commit's
    discipline. Returns the new candidate revision or None when nothing
    changed."""
    proposal = record["id"]
    worktree = project / proposals.WORKTREES_REL / proposal
    changed: list[str] = []
    for line in proposals._git(
        ["status", "--porcelain", "--untracked-files=all"], worktree
    ).stdout.splitlines():
        if not line.strip():
            continue
        rel = line[3:].rsplit(" -> ", 1)[-1]
        if rel in rels:
            changed.append(rel)
        else:
            raise ValueError(
                f"the worktree of proposal {proposal} carries the change {rel!r} "
                "outside the core-authored evidence pages" + proposals._HUMAN_RESOLUTION
            )
    if not changed:
        return None
    proposals._require_git_identity(project)
    literal = [proposals._literal(rel) for rel in changed]
    proposals._git(["add", "-f", "--", *literal], worktree)
    proposals._git(["commit", "-m", message, "--", *literal], worktree)
    record["candidate_revision"] = proposals._git(["rev-parse", "HEAD"], worktree).stdout.strip()
    proposals._store_record(project, record)
    return record["candidate_revision"]


def _finalize_mapping_evidence(
    project: Path,
    proposal: str,
    record: dict,
    revision: str,
    *,
    source_digest: str | None,
    approval: dict | None,
) -> tuple[str, list[str]]:
    """The K3 finalization step (plan §2): verify every structured mapping's
    cited receipts against the project's evidence records and the current
    dependency identities, attach the bounded verified summaries to the
    Reference pages as the core-owned ``ariadne_evidence`` frontmatter block,
    and REMOVE a block whose receipts no longer verify. Returns (the final
    revision, errors) — an unverifiable receipt is a validation error naming
    the mapping, never a silently inherited summary."""
    pages = _reference_pages_at(project, revision)
    cited = any(
        mapping.get("receipt_ids")
        for page in pages.values()
        for mapping in (page["meta"]["ariadne"].get("mappings") or [])
        if isinstance(mapping, dict)
    )
    carried = any("ariadne_evidence" in page["meta"] for page in pages.values())
    if not pages or not (cited or carried):
        return revision, []
    asset_columns: dict[str, list[dict]] = {}
    if approval is not None:
        owned = execution.DuckDBExecution(authoring_sources.identity_registry(approval["sources"]))
        try:
            asset_columns = _current_asset_columns(owned.catalog)
        finally:
            owned.close()
    errors: list[str] = []
    rewrites: dict[str, str] = {}
    # K3 fix pass (finding 6): the operator's evidence age budget (host
    # config only) bounds how old a receipt may be and still attach; the
    # cited Policy/OSI digests re-verify against the proposal worktree.
    max_age_hours = project_inspection_limits(project)["receipt_max_age_hours"]
    worktree = project / proposals.WORKTREES_REL / proposal
    for rel, page in pages.items():
        representations = {
            representation.get("id"): representation
            for representation in (page["meta"]["ariadne"].get("representations") or [])
            if isinstance(representation, dict) and isinstance(representation.get("id"), str)
        }
        desired: dict[str, list[dict]] = {}
        for mapping in page["meta"]["ariadne"].get("mappings") or []:
            if not isinstance(mapping, dict):
                continue
            receipt_ids = mapping.get("receipt_ids") or []
            if not receipt_ids:
                continue
            declaration = mapping.get("candidate")
            try:
                declaration_digest = candidate_digest(declaration)
            except ValueError as exc:
                errors.append(
                    f"{rel}: mapping {mapping.get('id')!r} cites receipts but its "
                    f"candidate declaration is not measurable: {exc}"
                )
                continue
            # K3 fix pass (finding 5): the measured candidate must correspond
            # to the mapping's ENDPOINT representations (fields and required
            # scope) BEFORE any evidence attaches — an endpoint that fails to
            # resolve is the page contract's own error, not a correspondence
            # check (verification then runs without endpoints).
            endpoints: dict | None = {}
            for key in ("from", "to"):
                representation = representations.get(mapping.get(key))
                if not isinstance(representation, dict) or not isinstance(
                    representation.get("fields"), list
                ):
                    endpoints = None
                    break
                endpoints[key] = {
                    "fields": representation.get("fields") or [],
                    "scope": representation.get("scope") or [],
                }
            summaries = []
            for receipt_id in receipt_ids:
                summary, error = _verify_receipt(
                    receipt_id,
                    project,
                    proposal,
                    declaration_digest=declaration_digest,
                    source_digest=source_digest,
                    asset_columns=asset_columns,
                    endpoints=endpoints,
                    worktree=worktree,
                    max_age_hours=max_age_hours,
                    storage_bindings=(approval or {}).get("storage_bindings"),
                )
                if error is not None:
                    errors.append(f"{rel}: mapping {mapping.get('id')!r} — {error}")
                    continue
                assert summary is not None
                summaries.append(summary)
                # K4 fix pass (finding 1, spec 0010 §§8–9): an ASSERTED claim
                # contradicted by its own verified receipts (honest mismatches,
                # an ambiguous pairing basis or an inconclusive outcome) is
                # unsupported and fails the mapping-evidence gate — the same
                # receipt under a hypothesis claim stays admissible as openly
                # labeled investigative knowledge.
                if mapping.get("claim") == "asserted":
                    named = evidence_counterevidence(summary)
                    if named:
                        errors.append(
                            f"{rel}: mapping {mapping.get('id')!r} is asserted but its "
                            f"verified receipt {summary.get('id')!r} shows "
                            f"counterevidence ({named}) — an asserted claim "
                            "contradicted by its own cited evidence is unsupported; "
                            "carry it as a labeled hypothesis instead"
                        )
            if summaries:
                desired[str(mapping.get("id"))] = summaries
        current = page["meta"].get("ariadne_evidence")
        if current != (desired or None):
            rewrites[rel] = context._set_frontmatter_key(
                page["text"], "ariadne_evidence", desired or None
            )
    final = revision
    if rewrites:
        for rel, text in rewrites.items():
            proposals._safe_write(worktree, rel, text)
        final = (
            _commit_core_pages(project, record, sorted(rewrites), EVIDENCE_COMMIT_MESSAGE)
            or revision
        )
    return final, errors
