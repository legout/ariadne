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
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import profiler
from ariadne.ingest import _ConversionError, _convert
from ariadne.sources import _URI_SCHEME_RE, _resolve_against, load_registry

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
        raise ValueError(
            f"no pending source proposal at {stored} — run propose-sources first"
        )
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
    taken = {
        entry.get("name") for entry in existing if isinstance(entry, dict)
    }
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
            f"{registry_path}: 'documents' must be a mapping with 'roots' and "
            "'object_store' lists"
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

    Reads stay inside what the operator configured in ``ariadne.yaml``: a
    local reference must resolve inside an allowed input root
    (``documents.roots``, default ``data/docs``); a URI reference must be an
    EXACT approved object-store URI (``documents.object_store``, S3 only).
    Traversal, an absolute path outside the roots, an unapproved or
    credentialed URI, a missing file, an unsupported format, or a missing
    converter fails explicitly BEFORE anything is fetched, read beyond the
    check, or written anywhere (never a served artifact)."""
    project_path = Path(project)
    roots, approved_uris = _project_documents_config(project_path)
    ref = str(reference)
    if _URI_SCHEME_RE.match(ref):
        if ref not in approved_uris:  # exact approval only — refused before ANY fetch
            raise ValueError(
                f"{ref}: object-store reference is not approved — approval is the "
                "operator's exact documents.object_store list in ariadne.yaml; "
                "nothing was fetched"
            )
        name = _uri_name(ref)
        retained = (
            project_path / OBJECT_STORE_REL / (_sha256_hex(ref.encode("utf-8")) + Path(name).suffix)
        )
        data = _retained_object_bytes(retained, ref)
        return _evidence_record(
            ref,
            name,
            _sha256_hex(data),
            _convert_snapshot(data, Path(name).suffix, display=name),
            part=part,
            part_chars=part_chars,
        )
    for root in roots:
        resolved = (root / ref).resolve()
        if resolved.is_relative_to(root):
            break
    else:
        raise ValueError(
            f"{ref}: reference escapes the operator-configured input roots "
            f"({', '.join(str(r) for r in roots)}) — reads stay inside them (spec §2)"
        )
    if not resolved.is_file():
        raise ValueError(f"{ref}: no readable document at {resolved}")
    data = resolved.read_bytes()  # the one stable snapshot for digest AND text
    return _evidence_record(
        str(resolved),
        resolved.name,
        _sha256_hex(data),
        _convert_snapshot(data, resolved.suffix, display=resolved.name),
        part=part,
        part_chars=part_chars,
    )


def harness_inputs(
    *, project: str | Path = ".", documents: Sequence[str] = (), part: int = 1
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
            profile = profiler.profile(sources_path=registry_path)
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
