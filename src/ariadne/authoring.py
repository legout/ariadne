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
:mod:`ariadne.authoring_context` (page/seed notes). Validation, review,
source proposals and measured inputs are LATER slices (G3/G4) and are
deliberately absent here.
"""

from __future__ import annotations

import errno
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
from urllib.parse import urlparse

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports] — same

from ariadne import authoring_context, authoring_semantic, profiler, proposals
from ariadne.author import (
    MAX_ROUNDS,
    _bundle_errors,
    _finalize_bundle,
    _load_frontmatter_meta,
    _mark_review_needed,
    normalize_layer_yaml,
)
from ariadne.ingest import _ConversionError, _convert
from ariadne.render import render
from ariadne.semantic_graph import load_graph
from ariadne.sources import (
    _URI_SCHEME_RE,
    _resolve_against,
    load_registry,
)
from ariadne.validate import _model_entries, validate

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
    proposed content (whitespace and key order do not matter)."""
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- slice 2 (issue #14): bounded document inputs and source-linked evidence ---

INPUT_ROOT_REL = Path("data") / "docs"  # operator-configured input area (init scaffold)
SEED_NOTES_REL = Path("data") / "seed_notes.md"  # optional already-approved Seed Notes
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # bounded upload; large documents are pre-staged (spec §2)
EVIDENCE_PART_CHARS = 20_000  # one bounded page of converted text per response
MAX_DOCUMENTS_PER_CALL = 16  # explicit aggregate bound: 16 parts ≤ 320k chars (spec §3)
# Retained original bytes of approved object-store documents (spec §2: the
# server KEEPS the original bytes and digest in its project-controlled area).
OBJECT_STORE_REL = Path("data") / "object-store"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _input_root(project: str | Path) -> Path:
    """The project-controlled input area every document read stays inside."""
    return (Path(project) / INPUT_ROOT_REL).resolve()


def _lstat(path: Path) -> os.stat_result | None:
    """The entry's own status, symlinks NOT followed (None = nothing claims
    the name, unlike Path.exists which follows — a dangling link claims it)."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _claim_exclusively(path: Path, data: bytes) -> None:
    """Write ``data`` at ``path`` claiming the name exclusively and WITHOUT
    following any symlink already sitting there (O_EXCL | O_NOFOLLOW): a
    racing claimant surfaces as FileExistsError, a pre-planted link as ELOOP."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _project_documents_config(project: Path) -> tuple[list[Path], list[str]]:
    """(allowed local input roots, EXACT approved object-store URIs) from the
    HUMAN-MANAGED project config (``ariadne.yaml``; owner decision 2026-09-24)
    — a client request never adds a root or URI. Defaults keep the scaffolded
    ``data/docs`` root and an empty approval list."""
    registry_path = project / "ariadne.yaml"
    if not registry_path.is_file():
        return [_input_root(project)], []
    doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    section = doc.get("documents")
    if section is None:
        return [_input_root(project)], []
    if not isinstance(section, dict):
        raise ValueError(
            f"{registry_path}: 'documents' must be a mapping with 'roots' and 'object_store' lists"
        )
    roots: list[Path] = []
    for raw in section.get("roots", [str(INPUT_ROOT_REL)]):
        if not isinstance(raw, str) or not raw or _URI_SCHEME_RE.match(raw):
            raise ValueError(
                f"{registry_path}: documents roots are local directory paths, got {raw!r}"
            )
        roots.append(Path(_resolve_against(project.resolve(), raw)).resolve())
    uris: list[str] = []
    for raw in section.get("object_store", []):
        where = f"{registry_path}: documents object_store entry {raw!r}"
        if not isinstance(raw, str):
            raise ValueError(f"{where} must be a URI string")
        parsed = urlparse(raw)
        if parsed.username or parsed.password:
            raise ValueError(
                f"{where} carries inline URL credentials (ADR-0010) — object-store "
                "access uses server-held credentials, never URIs"
            )
        if parsed.scheme != "s3":
            raise ValueError(
                f"{where}: only s3:// object URIs are supported (the spec §2 minimum "
                "object-store case; no https credential policy is defined)"
            )
        if not parsed.netloc or len(parsed.path) <= 1 or parsed.query or parsed.fragment:
            raise ValueError(f"{where} must name one exact object document (bucket and key)")
        uris.append(raw)
    return roots, uris


def _uri_name(uri: str) -> str:
    """The document filename an approved object URI names (key basename)."""
    return Path(urlparse(uri).path).name


def store_upload(
    name: str, data: bytes, *, project: str | Path = ".", max_bytes: int = MAX_UPLOAD_BYTES
) -> dict:
    """Bounded upload (spec §2): retain a harness-submitted document's original
    bytes in the project-controlled input area and return its stable identity
    ``{resource, digest}``. An over-limit upload or a non-plain filename is
    refused BEFORE anything is written; a same-name re-upload with different
    content claims a suffixed name (never overwrites — ingest's staging
    discipline), an identical re-upload keeps the same identity."""
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise ValueError(f"upload name must be a plain filename, got {name!r}")
    if len(data) > max_bytes:
        raise ValueError(
            f"{name}: upload is {len(data)} bytes, over the {max_bytes}-byte limit — "
            "stage large documents in the operator input area or object storage "
            "(spec §2), never upload unbounded payloads"
        )
    root = Path(project) / INPUT_ROOT_REL
    root.mkdir(parents=True, exist_ok=True)
    digest = _sha256_hex(data)
    candidate = root / name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while True:
        entry = _lstat(candidate)  # symlinks claim the name WITHOUT being followed
        if entry is None:
            try:
                _claim_exclusively(candidate, data)
                break  # claimed: the name is ours, no link was followed
            except FileExistsError:  # claimed mid-flight: re-examine it
                continue
        if stat.S_ISLNK(entry.st_mode):
            raise ValueError(
                f"{candidate.name}: refusing a symlinked input-root entry "
                f"({candidate}) — uploads claim plain files only, links are never "
                "followed for reading or writing"
            )
        if not stat.S_ISREG(entry.st_mode):
            raise ValueError(
                f"{candidate.name}: {candidate} is not a regular file — uploads "
                "claim plain files only"
            )
        if _sha256_hex(candidate.read_bytes()) == digest:
            break  # identical re-upload: same identity, nothing rewritten
        candidate = root / f"{stem}-{counter}{suffix}"
        counter += 1
    return {"resource": str(candidate.resolve()), "digest": digest}


def _evidence_record(
    resource: str, title: str, digest: str, text: str, *, part: int, part_chars: int
) -> dict:
    """One bounded part of converted text with its exact source identity:
    ``complete`` is true only when this part IS the whole text (spec §3 — no
    omitted content is ever represented as complete)."""
    parts = max(1, -(-len(text) // part_chars))
    if not 1 <= part <= parts:
        raise ValueError(f"part {part} is out of range (1..{parts}) for {title}")
    return {
        "resource": resource,
        "title": title,
        "digest": digest,
        "chars": len(text),
        "part": part,
        "parts": parts,
        "text": text[(part - 1) * part_chars : part * part_chars],
        "complete": parts == 1,
    }


def _convert_snapshot(data: bytes, suffix: str, *, display: str) -> str:
    """Convert through the SAME optional [documents] dispatch, but from one
    stable in-memory snapshot: the paired digest always describes exactly the
    bytes this text was converted from, even if the file is replaced mid-call
    (concurrent replacement cannot split identity from content)."""
    with tempfile.NamedTemporaryFile(suffix=suffix) as snapshot:
        snapshot.write(data)
        snapshot.flush()
        try:
            return _convert(Path(snapshot.name))
        except _ConversionError as exc:
            raise ValueError(str(exc).replace(snapshot.name, display)) from None


def _fetch_object_bytes(uri: str) -> bytes:
    """Fetch one object's exact bytes through DuckDB's blob reader using
    SERVER-HELD credentials (httpfs reads the server's standard AWS_*
    environment; no client-supplied credential exists). The local-path
    transport is verified in tests; LIVE S3 ACCESS IS UNVERIFIED in this
    lane — no real provider credentials were available."""
    import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages; core dependency, lazy at the network seam

    literal = uri.replace("'", "''")  # config-validated URI; quote it anyway
    try:
        rows = duckdb.connect().execute(f"SELECT content FROM read_blob('{literal}')").fetchall()
    except Exception as exc:  # duckdb/provider errors carry no secret (URIs are credential-free)
        raise ValueError(
            f"{uri}: object retrieval failed ({type(exc).__name__}: {exc}) — live S3 "
            "access is unverified in this lane"
        ) from None
    if len(rows) != 1:
        raise ValueError(f"{uri}: expected exactly one object, read_blob returned {len(rows)}")
    content = rows[0][0]
    if not isinstance(content, bytes):
        raise ValueError(f"{uri}: object content is not bytes")
    return content


def _retained_object_bytes(retained: Path, uri: str) -> bytes:
    """The original bytes of one approved object, retained in the project
    input area: reuse the retained copy (stable, no re-fetch) or fetch once
    with server-held credentials and retain it — never following a symlinked
    or non-regular entry planted in the retention directory."""
    entry = _lstat(retained)
    if entry is not None:
        if not stat.S_ISREG(entry.st_mode):
            raise ValueError(
                f"{retained}: refusing a non-regular retained-object entry — "
                "inspect the project input area"
            )
        return retained.read_bytes()
    data = _fetch_object_bytes(uri)
    retained.parent.mkdir(parents=True, exist_ok=True)
    try:
        _claim_exclusively(retained, data)
    except FileExistsError:  # retained concurrently: the winner's copy is the bytes
        return _retained_object_bytes(retained, uri)
    except OSError as exc:  # ELOOP: a symlink already claimed the retention name
        if exc.errno == errno.ELOOP:
            raise ValueError(
                f"{retained}: refusing a symlinked retained-object entry — "
                "inspect the project input area"
            ) from None
        raise
    return data


def _document_bytes(reference: str, project: Path) -> tuple[str, str, bytes]:
    """Locate ONE document reference inside the operator's boundary and return
    its stable identity ``(resource, title, current snapshot bytes)``: the
    shared seam of converted evidence (spec §2–3) and submit-time citation
    verification. A URI reference must be an EXACT approved object-store URI
    (``documents.object_store``, S3 only — approved objects are read through
    the retained project copy, fetching once with server-held credentials); a
    local reference must resolve inside an allowed input root
    (``documents.roots``, default ``data/docs``). Traversal, an absolute path
    outside the roots, an unapproved or credentialed URI, or a missing file
    fails explicitly BEFORE anything beyond the check is fetched, read, or
    written."""
    roots, approved_uris = _project_documents_config(project)
    if _URI_SCHEME_RE.match(reference):
        if reference not in approved_uris:  # exact approval only — refused before ANY fetch
            raise ValueError(
                f"{reference}: object-store reference is not approved — approval is the "
                "operator's exact documents.object_store list in ariadne.yaml; "
                "nothing was fetched"
            )
        name = _uri_name(reference)
        retained = (
            project
            / OBJECT_STORE_REL
            / (_sha256_hex(reference.encode("utf-8")) + Path(name).suffix)
        )
        return reference, name, _retained_object_bytes(retained, reference)
    for root in roots:
        resolved = (root / reference).resolve()
        if resolved.is_relative_to(root):
            break
    else:
        raise ValueError(
            f"{reference}: reference escapes the operator-configured input roots "
            f"({', '.join(str(r) for r in roots)}) — reads stay inside them (spec §2)"
        )
    if not resolved.is_file():
        raise ValueError(f"{reference}: no readable document at {resolved}")
    return str(resolved), resolved.name, resolved.read_bytes()


def document_evidence(
    reference: str,
    *,
    project: str | Path = ".",
    part: int = 1,
    part_chars: int = EVIDENCE_PART_CHARS,
) -> dict:
    """Convert one input-area document into source-linked evidence (spec §2–3)
    with NO model: the exact resource, its sha256 digest over the original
    bytes, and one bounded part of the converted text — all from ONE stable
    snapshot, so a file replaced mid-call can never split digest from text.

    Reads stay inside what the operator configured in ``ariadne.yaml``
    (:func:`_document_bytes`): a local reference must resolve inside an
    allowed input root (``documents.roots``, default ``data/docs``); a URI
    reference must be an EXACT approved object-store URI
    (``documents.object_store``, S3 only). Traversal, an absolute path outside
    the roots, an unapproved or credentialed URI, a missing file, an
    unsupported format, or a missing converter fails explicitly BEFORE anything
    is fetched, read beyond the check, or written anywhere (never a served
    artifact)."""
    resource, title, data = _document_bytes(str(reference), Path(project))
    return _evidence_record(
        resource,
        title,
        _sha256_hex(data),
        _convert_snapshot(data, Path(title).suffix, display=title),
        part=part,
        part_chars=part_chars,
    )


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
    credentials never appear in the response."""
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
        notes_bytes = notes_path.read_bytes()  # one stable snapshot: digest AND text
        seed_notes = _evidence_record(
            str(notes_path.resolve()),
            notes_path.name,
            _sha256_hex(notes_bytes),
            notes_bytes.decode("utf-8", errors="replace"),
            part=part,
            part_chars=EVIDENCE_PART_CHARS,
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
        meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
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

    This slice (G2) owns proposal lifecycle and complete artifact edits only:
    ``validate_proposal``/``review_proposal`` are G4, ``propose_sources``/
    ``inputs`` in Git mode are G3 — they do not exist here yet.
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
                f"{EDIT_KINDS} (typed source proposals arrive through their own "
                f"later operation), got kind {got!r}"
            )
        rel, content = _LAYER_EDITORS[edit["kind"]].resolve_edit(edit)
        return proposals.edit_proposal(
            self.project, proposal, expected_revision, rel, content
        )
