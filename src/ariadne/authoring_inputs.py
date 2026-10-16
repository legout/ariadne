"""Bounded document evidence for Git authoring (issue #35/G3; spec 0027 §5).

Document reads stay inside the human-managed ``documents.roots`` and exact
``documents.object_store`` permissions. Original bytes remain operator-owned
inputs outside the authored Git set; approved objects are fetched for the
current read and are never retained by Core. Conversion and digest identity
share one stable byte snapshot. The bounded Seed Notes evidence record and
:func:`harness_inputs` remain available to the legacy local harness.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.ingest import _ConversionError, _convert
from ariadne.sources import _URI_SCHEME_RE, _resolve_against

INPUT_ROOT_REL = Path("data") / "docs"  # operator-configured input area (init scaffold)
SEED_NOTES_REL = Path("data") / "seed_notes.md"  # optional already-approved Seed Notes
EVIDENCE_PART_CHARS = 20_000  # one bounded page of converted text per response
MAX_DOCUMENTS_PER_CALL = 16  # explicit aggregate bound: 16 parts ≤ 320k chars (spec §3)

# K3 (issue #43, spec 0010 §7, plan §2 "finite limits"): the operator-owned
# inspection ceilings. These are the BUILT-IN defaults; the human-managed
# project config may only TIGHTEN them (lower a numeric ceiling), and a
# request may only lower them further — never raise. ``raw_examples`` is the
# operator's explicit sample permission for raw identifier examples (default
# off; aggregate/shape output is the default response).
DEFAULT_INSPECTION_LIMITS = {
    "sample_rows": 1000,  # materialized sampled rows per participating asset
    "execution_seconds": 20.0,  # total inspection execution across all sources
    "response_bytes": 64 * 1024,  # serialized response ceiling
    "raw_examples": False,
    # K3 fix pass (finding 6, spec 0010 §8): the operator's evidence AGE
    # budget — how old a retained receipt may be and still attach its
    # verified summary. Age bounds the RECEIPT's validity for attachment;
    # unversioned data stays as_of and dependency changes invalidate
    # immediately. Host-config only (tightenable), never a candidate or
    # request field.
    "receipt_max_age_hours": 24.0,
}
MAX_RAW_EXAMPLES = 10  # the optional raw-example cap (with permission)
_INSPECTION_LIMIT_KEYS = frozenset(
    {
        "sample_rows",
        "execution_seconds",
        "response_bytes",
        "raw_examples",
        "receipt_max_age_hours",
    }
)
_REQUEST_LIMIT_KEYS = frozenset({"sample_rows", "execution_seconds", "response_bytes", "examples"})


def _finite_positive(value: object, where: str) -> None:
    """One numeric limit must be a FINITE positive number (K3 fix pass,
    finding 8): NaN/inf compare false against every ceiling, so a non-finite
    limit is an explicit refusal — it can never silently disable a bound."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"{where} must be a finite positive number, got {value!r} — a non-finite "
            "limit disables no ceiling comparison; nothing was measured"
        )


def project_inspection_limits(project: str | Path) -> dict:
    """The effective operator-owned inspection ceilings of one project: the
    built-in defaults tightened by the HUMAN-MANAGED project config's optional
    ``inspection:`` section (spec 0010 §7; read from the HOST project root's
    working tree exactly like the documents boundary — a candidate's committed
    ``inspection:`` section is inert data and can never widen a ceiling or
    grant sample permission). An invalid or RAISING section is an explicit
    error naming the field."""
    root = Path(project)
    registry_path = root / "ariadne.yaml"
    limits = dict(DEFAULT_INSPECTION_LIMITS)
    if not registry_path.is_file():
        return limits
    try:
        doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{registry_path}: not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    section = doc.get("inspection")
    if section is None:
        return limits
    if not isinstance(section, dict):
        raise ValueError(
            f"{registry_path}: 'inspection' must be a mapping with the optional keys "
            f"{sorted(_INSPECTION_LIMIT_KEYS)}"
        )
    unknown = sorted(set(section) - _INSPECTION_LIMIT_KEYS)
    if unknown:
        raise ValueError(
            f"{registry_path}: 'inspection' carries unsupported key(s) {unknown}; "
            f"allowed: {sorted(_INSPECTION_LIMIT_KEYS)}"
        )
    for key in ("sample_rows", "execution_seconds", "response_bytes", "receipt_max_age_hours"):
        if key not in section:
            continue
        value = section[key]
        _finite_positive(value, f"{registry_path}: inspection.{key}")
        if value > DEFAULT_INSPECTION_LIMITS[key]:
            raise ValueError(
                f"{registry_path}: inspection.{key}={value} would RAISE the built-in "
                f"ceiling {DEFAULT_INSPECTION_LIMITS[key]} — the operator config may "
                "only tighten the finite limits (spec 0010 §7)"
            )
        limits[key] = value
    if "raw_examples" in section:
        permission = section["raw_examples"]
        if not isinstance(permission, bool):
            raise ValueError(
                f"{registry_path}: inspection.raw_examples must be a boolean sample "
                f"permission, got {permission!r}"
            )
        limits["raw_examples"] = permission
    return limits


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def effective_inspection_limits(ceilings: dict, request_limits: object) -> dict:
    """The effective limits of one inspection request: the operator ceilings
    possibly lowered by the request (plan §2: requests can lower limits,
    never raise them). ``examples`` additionally requires the operator's
    explicit raw-example sample permission and is capped at ten. A raising or
    invalid request limit is an explicit refusal naming the ceiling."""
    effective = dict(ceilings)
    effective["examples"] = 0
    if request_limits is None:
        return effective
    if not isinstance(request_limits, dict):
        raise ValueError(
            "inspection limits must be a mapping with the optional keys "
            f"{sorted(_REQUEST_LIMIT_KEYS)}"
        )
    unknown = sorted(set(request_limits) - _REQUEST_LIMIT_KEYS)
    if unknown:
        raise ValueError(
            f"inspection limits carry unsupported key(s) {unknown}; allowed: "
            f"{sorted(_REQUEST_LIMIT_KEYS)}"
        )
    for key in ("sample_rows", "execution_seconds", "response_bytes"):
        if key not in request_limits:
            continue
        value = request_limits[key]
        _finite_positive(value, f"inspection limits.{key}")
        if value > ceilings[key]:
            raise ValueError(
                f"inspection limits.{key}={value} would RAISE the operator ceiling "
                f"{ceilings[key]} — a request may only LOWER the finite limits "
                "(spec 0010 §7); nothing was measured"
            )
        effective[key] = value
    if "examples" in request_limits:
        wanted = request_limits["examples"]
        if isinstance(wanted, bool) or not isinstance(wanted, int) or wanted < 0:
            raise ValueError(
                f"inspection limits.examples must be a non-negative integer, got {wanted!r}"
            )
        if wanted > MAX_RAW_EXAMPLES:
            raise ValueError(
                f"inspection limits.examples={wanted} exceeds the raw-example cap of "
                f"{MAX_RAW_EXAMPLES} (spec 0010 §7)"
            )
        if wanted and not ceilings["raw_examples"]:
            raise ValueError(
                "raw identifier examples need the operator's EXPLICIT sample "
                "permission (inspection.raw_examples in the host ariadne.yaml) — "
                "the default response is aggregate evidence and shape summaries"
            )
        effective["examples"] = wanted
    return effective


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
    for position, raw in enumerate(section.get("object_store", []), start=1):
        where = f"{registry_path}: documents object_store entry {position}"
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

    try:
        rows = duckdb.connect().execute("SELECT content FROM read_blob(?)", [uri]).fetchall()
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


def _document_bytes(reference: str, project: Path) -> tuple[str, str, bytes]:
    """Locate ONE document reference inside the operator's boundary and return
    its stable identity ``(resource, title, current snapshot bytes)``: the
    shared seam of converted evidence (spec §2–3) and submit-time citation
    verification. A URI reference must be an EXACT approved object-store URI
    (``documents.object_store``, S3 only — fetched for this read with
    server-held credentials); a local reference must resolve inside an allowed input root
    (``documents.roots``, default ``data/docs``). Traversal, an absolute path
    outside the roots, an unapproved or credentialed URI, or a missing file
    fails explicitly BEFORE anything beyond the check is fetched, read, or
    written."""
    roots, approved_uris = _project_documents_config(project)
    if _URI_SCHEME_RE.match(reference):
        if reference not in approved_uris:  # exact approval only — refused before ANY fetch
            raise ValueError(
                "object-store reference is not approved — approval is the operator's "
                "exact documents.object_store list in ariadne.yaml; nothing was fetched"
            )
        name = _uri_name(reference)
        return reference, name, _fetch_object_bytes(reference)
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
