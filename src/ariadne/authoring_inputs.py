"""Bounded document inputs and source-linked evidence for authoring (issue
#35/G3; spec 2026-09-24-0005 "Evidence and source-access boundary" §2–3, spec
2026-10-02-0009 §3, plan §2).

The measured-evidence half of the authoring workflow, MOVED INTACT from
:mod:`ariadne.authoring` (issue #14 slice 2) so the legacy route and the new
Git-backed proposals share ONE implementation: bounded uploads retained in the
project-controlled input area, the operator's document boundary (local input
roots plus EXACT approved object-store URIs from the human-managed project
config), verified conversion/citation identity over one stable snapshot, and
the bounded Seed Notes evidence record. Nothing is rewritten: the legacy
:func:`ariadne.authoring.harness_inputs` calls these same functions.

Uploads and document bytes are operator-side state, never Git artifacts: they
live under the project's input area (``data/docs/`` default), which no proposal
edit can stage (the G2 boundary stages exactly named artifact identities, and
``data/docs/`` is outside the candidate scope).
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.ingest import _ConversionError, _convert
from ariadne.sources import _URI_SCHEME_RE, _resolve_against

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
    ``data/docs`` root and an empty approval list.

    In the Git authoring route this is read from the HOST project root's
    working tree only (issue #35/G3): a candidate's committed ``documents:``
    section is inert data and can never widen these permissions."""
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
            raise ValueError(f"{where}: must name one exact object document (bucket and key)")
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


def bytes_evidence(
    resource: str,
    title: str,
    data: bytes,
    *,
    part: int = 1,
    part_chars: int = EVIDENCE_PART_CHARS,
) -> dict:
    """One bounded evidence record over stable in-memory bytes: the digest AND
    the text come from the SAME snapshot (the Seed Notes discipline), so a file
    replaced mid-call can never split identity from content. Shared by the
    legacy harness inputs and the Git proposal route (issue #35/G3)."""
    return _evidence_record(
        resource,
        title,
        _sha256_hex(data),
        data.decode("utf-8", errors="replace"),
        part=part,
        part_chars=part_chars,
    )


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
