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
import shutil
import stat
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports] — same

from ariadne import (
    authoring_context,
    authoring_inputs,  # noqa: F401 — re-export: the historical seam
    authoring_semantic,
    authoring_sources,
    context,
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
    store_upload,
)
from ariadne.render import render
from ariadne.semantic_graph import load_graph
from ariadne.sources import (
    _URI_SCHEME_RE,
    _resolve_against,
    load_registry,
)
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
    """Validate and store one inert source proposal; return its digest and the
    precise proposed locations. Raises the registry validator's errors (naming
    the offending entry) for any invalid or credential-carrying proposal.
    Never opens a location. Relative paths are resolved against the project
    root — the directory of the eventual ``ariadne.yaml`` — so a location means
    the same thing when proposed, digested, and (after approval) profiled,
    whatever directory the intake file arrived in."""
    proposal_path = Path(file)
    load_registry(proposal_path)  # reuse the ADR-0010 validation, verbatim
    entries = _entries(proposal_path)
    base = Path(project).resolve()  # NOT the intake file's directory (spec §1)
    for entry in entries:
        if isinstance(entry.get("path"), str):
            entry["path"] = _resolve_against(base, entry["path"])
    digest = _digest(entries)
    stored = Path(project) / PROPOSAL_REL
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(
        yaml.safe_dump({"digest": digest, "sources": entries}, sort_keys=False),
        encoding="utf-8",
    )
    return {"digest": digest, "proposal": str(stored), "sources": entries}


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
    current = _digest(entries)
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


def _digest(entries: list[dict]) -> str:
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


def _registry_sources(project: Path) -> list:
    """The APPROVED registry entries (the bundle's source identity), [] when the
    project has none; malformed config is an explicit error."""
    registry_path = project / "ariadne.yaml"
    if not registry_path.is_file():
        return []
    doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    sources = doc.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError(f"{registry_path}: 'sources' is not a list")
    return sources


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
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
    sources_digest = _digest(sources)
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
            registry_path = project / "ariadne.yaml"
            result = (
                validate(tmp, sources_path=registry_path)
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
        if _digest(_registry_sources(project)) != state.get("sources_digest"):
            raise ValueError(
                "the approved source registry changed while this bundle proposal was "
                "active — the proposal is invalidated and needs re-profiling and "
                "resubmission; review is refused, nothing was written or served"
            )
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
                "an artifact identity is a typed object with kind one of "
                f"{EDIT_KINDS}, got {got!r}"
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
        return proposals.edit_proposal(
            self.project, proposal, expected_revision, rel, content
        )

    # ------------------- G3 (issue #35): sources, approval, measured inputs

    def propose_sources(
        self, proposal: str, expected_revision: str, sources: list[dict] | tuple[dict, ...]
    ) -> dict:
        """Append validated typed source entries to the candidate's registry
        (``ariadne.yaml``) through the revision-checked edit seam and return
        ``{proposal, revision, changed, source_digest, sources}`` — the digest
        of the candidate's full RESOLVED identity (paths resolved against the
        host project root) plus the precise resolved locations. Inert data:
        nothing is opened, and the candidate cannot grant itself approval."""
        return authoring_sources.propose_sources(
            self.project, proposal, expected_revision, sources
        )

    def approve_sources(self, proposal: str, revision: str, source_digest: str) -> dict:
        """HUMAN-ONLY (the CLI command; never an MCP/Agent tool): record the
        operator's permission for the EXACT resolved source identity of the
        proposal's current candidate revision, outside Git artifacts under
        ``.ariadne/source-approvals.json`` — without editing the
        already-committed candidate."""
        return authoring_sources.approve_sources(
            self.project, proposal, revision, source_digest
        )

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
            self.project, proposal, documents=documents, part=part, sample_rows=sample_rows
        )

    def upload_document(
        self, name: str, data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES
    ) -> dict:
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



# ------------------------------------- slice 5 (issue #36/G4): validation/review

# The finalize commit's fixed message (the only commits validation itself
# creates): deterministic generated artifacts only, never a review decoration.
FINALIZE_COMMIT_MESSAGE = "ariadne: finalize generated artifacts"


def _cited_resources(meta: dict) -> list[str]:
    """The distinct citation resources of one page's frontmatter ``sources``
    (a mapping's ``resource`` — the rev 10 context field — or the plain
    string itself)."""
    resources: list[str] = []
    for source in meta.get("sources") or []:
        resource = (
            source.get("resource")
            if isinstance(source, dict) and "resource" in source
            else source
        )
        if isinstance(resource, str) and resource and resource not in resources:
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
                f"{rel}: frontmatter is not valid YAML — its citations cannot "
                f"be verified: {exc}"
            )
            continue
        for resource in _cited_resources(meta):
            if (bundle_rel := _tree_citation(tree, page, resource)) is not None:
                citations[("bundle", resource)] = {
                    "resource": resource,
                    "kind": "bundle",
                    "path": bundle_rel,
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
        "citations": list(evidence["citations"]),
        "report": evidence["report"],
        "performed_checks": list(evidence["performed_checks"]),
        "validator_identity": evidence["validator_identity"],
        "evidence": str(evidence_path),
    }
    if idempotent:
        view["idempotent"] = True
    return view


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
        # source identity must carry the operator's approval. The finalize
        # pass touches only context_layer bytes, so the input revision's
        # registry identity IS the final revision's identity.
        resolved_sources, source_digest = authoring_sources.candidate_sources(
            project, current
        )
        approval = None
        if resolved_sources is not None:
            approval = authoring_sources._approved_identity(
                project, source_digest, proposal, current
            )
        # Idempotent no-op retry: stored evidence for the EXACT current commit
        # with unchanged binding context returns as-is — nothing re-runs and
        # the bounded repair state is neither reset nor advanced.
        stored = proposals.load_validation(project, proposal, current)
        if (
            stored is not None
            and stored.get("source_digest") == source_digest
            and _document_digests_current(project, stored.get("citations") or [])
        ):
            return _validate_view(
                stored,
                proposals._validation_path(project, proposal, current),
                idempotent=True,
            )
        repair = dict(record.get("repair") or {"attempts": 0, "status": "open"})
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
        context.finalize_candidate(worktree_root)
        final = (
            proposals.commit_generated(project, record, message=FINALIZE_COMMIT_MESSAGE)
            or current
        )
        with tempfile.TemporaryDirectory(prefix="ariadne-candidate-") as tmp:
            root = Path(tmp)
            tree = root / "bundle"
            tree.mkdir()
            rels = _materialize(project, proposal, final, tree)
            # The audit connection opens ONLY the operator-approved resolved
            # identity (the G3 seam): one temp registry carrying exactly those
            # resolved entries, outside the materialized tree.
            sources_path = None
            if approval is not None:
                sources_path = root / "approved-registry.yaml"
                sources_path.write_text(
                    yaml.safe_dump({"sources": approval["sources"]}, sort_keys=False),
                    encoding="utf-8",
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
                result = validate(tree, sources_path=sources_path)
                errors = list(result.errors)
            else:  # never open the audit connection for an unauthorized source
                result = validate(tree)  # compile-only: the boundary error blocks
                errors = [auth_error, *result.errors]
            page_errors = _bundle_errors(tree) + _graph_citation_errors(tree)
            citations, citation_errors = _verified_citations(tree, project, names)
            errors.extend(page_errors)
            errors.extend(citation_errors)
            # validate() carries no report at all when the tree has no semantic
            # models directory (the empty-project onboarding case): the
            # structural outcome owns that failure explicitly
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
                    "citations",
                    "failed" if citation_errors else "passed",
                    "; ".join(citation_errors),
                ),
            )
            performed = [check.name for check in checks if check.outcome != "not-run"]
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
        # different commit or a changed binding context); an identical retry
        # of the same key consumes nothing.
        key = {
            "commit": final,
            "source_digest": source_digest,
            "documents": sorted(
                f"{c['resource']}:{c['digest']}"
                for c in citations
                if c["kind"] == "document"
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


def _review_candidate(
    project: Path, proposal: str, *, part: int = 1, record: dict | None = None
) -> dict:
    """The lock-free review core (issue #37/G5): exactly the envelope
    :func:`review_proposal` returns, computed for one loaded record — the
    caller holds the proposal lock (the public review takes it; admission
    already holds the project+proposal locks when it re-derives the review
    digest, and a nested lock acquisition would self-deadlock)."""
    if record is None:
        record = proposals._load_record(project, proposal)
    proposals._check_coherent(project, record)
    base = record["base_revision"]
    current = record["candidate_revision"]
    with tempfile.TemporaryDirectory(prefix="ariadne-review-") as tmp:
        tree = Path(tmp) / "bundle"
        tree.mkdir()
        rels = _materialize(project, proposal, current, tree)
        resolved_sources, source_digest = authoring_sources.candidate_sources(
            project, current
        )
        bodies = []
        for rel in rels:
            data = (tree / Path(*PurePosixPath(rel).parts)).read_bytes()
            bodies.append(_review_body(rel, data, part=part))
        source_names = {entry["name"] for entry in resolved_sources or []}
        citations, _citation_errors = _verified_citations(tree, project, source_names)
        approved = (
            authoring_sources._load_approvals(project).get(source_digest or "")
            is not None
        )
        artifact_digest = candidate_scope_digest(tree)
        # The stored report binds the exact candidate commit or is absent:
        # a candidate that moved past its validation, a changed source
        # identity, changed document evidence or changed artifact bytes can
        # never be presented as an unchanged validated candidate.
        report = proposals.load_validation(project, proposal, current)
        stale_reasons: list[str] = []
        if report is not None:
            if report.get("source_digest") != source_digest:
                stale_reasons.append(
                    "the resolved source identity changed since validation"
                )
            if not _document_digests_current(project, report.get("citations") or []):
                stale_reasons.append(
                    "cited document evidence changed since validation"
                )
            if report.get("artifact_digest") != artifact_digest:
                stale_reasons.append(
                    "the candidate's artifact bytes differ from the validated digest"
                )
        inventory = _change_inventory(project, record)
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
            "review_digest": review_digest,
        }
