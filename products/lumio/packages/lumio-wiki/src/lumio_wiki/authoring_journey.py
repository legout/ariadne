"""Source extraction and complete managed-candidate authoring (spec 0010 §3).

Two public operations for the external-agent authoring journey:

- :func:`extract_source` wraps the existing SourceProcessor seam: it reads a
  real original, runs the actually routed processor, and persists normalized
  working material OUTSIDE any content repository. No model provider runs
  here; ``processor`` is whatever the processor itself reported, never an
  invented identity, and page/section coordinates are the converter's real
  ones or a stable heading label — never fabricated.
- :func:`ingest_candidate` applies one complete multi-page/ontology candidate
  through the existing managed worktree seams: the WHOLE candidate (pages,
  candidate Control File, cross-page references, exact manifest bindings) is
  validated before any private registration or authoring-file write, so
  references between new pages never require invalid intermediate ingests.
  New/changed original bytes are retained AND verified before success; a
  failure rolls the authored tree back while immutable private registration
  residue stays convergent and retry-safe.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import msgspec

from lumio_wiki.artifact_store import ArtifactStoreError, retain_artifact
from lumio_wiki.git_authoring import (
    GitAuthoringError,
    _apply_worktree_candidate,
    _authored_entity_id,
    _load_authoring_manifest,
    _local_store_root,
    _refuse_manifest_drift,
    _refuse_private_selection_inside_tree,
    _refuse_profile_candidate_violations,
    _refuse_tracked_private_paths,
    _refuse_unsafe_worktree_mutation,
    _registry_root,
    capture_revision,
    resolve_repository,
)
from lumio_wiki.knowledge_base import (
    CONTROL_FILE_BASENAME,
    load_control_file,
    load_knowledge_base,
)
from lumio_wiki.mutation import MutationRollbackError, atomic_write_bytes
from lumio_wiki.publish import (
    DestinationConflict,
    _resolve_proposed_destinations,
    affected_mutation_paths,
    validate_candidate_knowledge_base,
)
from lumio_wiki.source_processor import (
    MAX_EXTRACTED_CHARS,
    MAX_SECTIONS,
    MAX_SOURCE_BYTES,
    MissingDocumentExtraError,
    SourceProcessorError,
    TextMarkdownSourceProcessor,
    select_document_processor,
)
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    parse_source_reference_manifest,
    upsert_binding,
)
from lumio_wiki.source_registry import SourceRegistry

__all__ = [
    "AuthoringJourneyError",
    "CandidateBinding",
    "CandidateRequest",
    "CandidateResult",
    "CandidateSourceRecord",
    "ExtractionResult",
    "extract_source",
    "ingest_candidate",
    "load_candidate_request",
]

SCHEMA_VERSION = 1

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_CONTROL_BASENAME = CONTROL_FILE_BASENAME


class AuthoringJourneyError(ValueError):
    """A journey operation refused with a bounded, actionable message.

    ``code`` is the stable error category of the versioned JSON envelope;
    messages never contain credential values or private registry paths.
    """

    def __init__(self, message: str, *, code: str = "authoring_journey_error") -> None:
        super().__init__(message)
        self.code = code


def _git_worktree_root(path: Path) -> Path | None:
    """The repository root containing ``path``, or ``None`` outside any repo."""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.decode().strip())


# ---------------------------------------------------------------------------
# Extraction (spec 0010 §3): actual processor, truthful output, outside Git.
# ---------------------------------------------------------------------------


class ExtractionResult(msgspec.Struct, frozen=True):
    """What one extraction actually produced for the exact original bytes."""

    schema_version: int
    source_sha256: str
    filename: str | None
    content_type: str | None
    processor: str
    size: int
    text: str
    sections: list[dict]
    incomplete: bool
    output_path: str


def _extraction_record_path(output_dir: Path, digest: str) -> Path:
    return output_dir / f"{digest}.json"


def extract_source(source_path: str | Path, *, output_dir: str | Path) -> ExtractionResult:
    """Extract one real original into normalized working material outside Git.

    Reads the actual file, routes it through the existing SourceProcessor
    seam, and persists one digest-addressed JSON record under ``output_dir``.
    The record and its coordinates never enter a content repository: an
    output directory inside a Git worktree is refused. Missing files refuse
    before anything is written; missing document extras, conversion failures
    and empty results are disclosed as bounded failures; a detected
    extraction bound (character/section ceiling) is reported as
    ``incomplete`` instead of implying completeness. No distiller runs.
    """
    source = Path(source_path)
    if not source.is_file():
        raise AuthoringJourneyError(
            "the original source file does not exist; supply a readable original "
            "before extraction (registration and mutation never start)",
            code="missing_source",
        )
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise AuthoringJourneyError(
            f"the original source could not be read: {exc}", code="unreadable_source"
        ) from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise AuthoringJourneyError(
            "the original exceeds the supported source size ceiling "
            f"({MAX_SOURCE_BYTES} bytes); extraction refused without mutation",
            code="source_too_large",
        )
    output = Path(output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    worktree = _git_worktree_root(output)
    if worktree is not None and (output == worktree or worktree in output.parents):
        raise AuthoringJourneyError(
            "the extraction output directory lies inside a Git worktree; working "
            "extraction material must stay outside the content repository",
            code="output_inside_repository",
        )
    digest = hashlib.sha256(raw).hexdigest()
    filename = source.name
    processor = select_document_processor(filename, None) or TextMarkdownSourceProcessor()
    try:
        normalized = processor.process(filename, None, raw)
    except MissingDocumentExtraError as exc:
        raise AuthoringJourneyError(str(exc), code="missing_documents_extra") from exc
    except SourceProcessorError as exc:
        message = str(exc)
        code = "empty_extraction" if "empty" in message.lower() else "conversion_failed"
        raise AuthoringJourneyError(message, code=code) from exc
    if not normalized.text or not normalized.text.strip():
        raise AuthoringJourneyError(
            "the processor returned no normalized text; the extraction is empty and "
            "is reported as a failure rather than a complete result",
            code="empty_extraction",
        )
    # Detected bounds only: a ceiling hit means the conversion may have been
    # truncated; completeness is never claimed merely because text came back.
    incomplete = (
        len(normalized.text) >= MAX_EXTRACTED_CHARS or len(normalized.sections) >= MAX_SECTIONS
    )
    sections = [msgspec.to_builtins(section) for section in normalized.sections]
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": "source-extraction",
        "source_sha256": digest,
        "filename": filename,
        "content_type": None,
        "processor": normalized.converted_by,
        "size": len(raw),
        "incomplete": incomplete,
        "text": normalized.text,
        "sections": sections,
    }
    record_path = _extraction_record_path(output, digest)
    atomic_write_bytes(record_path, json.dumps(record, indent=2, sort_keys=True).encode("utf-8"))
    return ExtractionResult(
        schema_version=SCHEMA_VERSION,
        source_sha256=digest,
        filename=filename,
        content_type=None,
        processor=normalized.converted_by,
        size=len(raw),
        text=normalized.text,
        sections=sections,
        incomplete=incomplete,
        output_path=str(record_path),
    )


# ---------------------------------------------------------------------------
# Candidate request v1 (plan 0010 interface inventory): explicit base, exact
# source records, authored page paths, optional complete Control File.
# ---------------------------------------------------------------------------


class CandidateSourceRecord(msgspec.Struct, frozen=True):
    """One declared original: explicit identity, local bytes, intent."""

    source_id: str
    original_path: str
    expected_digest: str
    intent: str  # "new" | "update"


class CandidateRequest(msgspec.Struct, frozen=True):
    """A complete managed-candidate request (working files outside the repo)."""

    schema_version: int
    base_revision: str
    sources: list[CandidateSourceRecord]
    pages: list[str]
    control: str | None = None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    payload: dict = {}
    for key, value in pairs:
        if key in payload:
            raise AuthoringJourneyError(
                f"duplicate JSON key {key!r} in the candidate request; refuse ambiguous input",
                code="invalid_candidate_request",
            )
        payload[key] = value
    return payload


def _require_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthoringJourneyError(
            f"{what} must be a non-empty string", code="invalid_candidate_request"
        )
    return value


def load_candidate_request(path: str | Path) -> CandidateRequest:
    """Parse and validate one candidate request file (strict JSON v1).

    Unknown fields, duplicate keys, wrong types, invalid digests/revisions
    and unknown intents refuse up front; declared digests are expectations
    the handler verifies against the actual bytes, never trusted values.
    """
    request_path = Path(path)
    if not request_path.is_file():
        raise AuthoringJourneyError(
            "the candidate request file does not exist", code="invalid_candidate_request"
        )
    try:
        payload = json.loads(request_path.read_bytes(), object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthoringJourneyError(
            f"the candidate request is not valid JSON: {exc}",
            code="invalid_candidate_request",
        ) from exc
    if not isinstance(payload, dict):
        raise AuthoringJourneyError(
            "the candidate request must be a JSON object", code="invalid_candidate_request"
        )
    allowed = {"schema_version", "base_revision", "sources", "pages", "control"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise AuthoringJourneyError(
            f"unknown candidate request field(s): {', '.join(unknown)}",
            code="invalid_candidate_request",
        )
    missing = sorted({"schema_version", "base_revision", "sources", "pages"} - set(payload))
    if missing:
        raise AuthoringJourneyError(
            f"missing candidate request field(s): {', '.join(missing)}",
            code="invalid_candidate_request",
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise AuthoringJourneyError(
            f"unsupported candidate request schema_version "
            f"{payload['schema_version']!r}; expected {SCHEMA_VERSION}",
            code="invalid_candidate_request",
        )
    base_revision = payload["base_revision"]
    if not isinstance(base_revision, str) or not _HEX40.fullmatch(base_revision):
        raise AuthoringJourneyError(
            "base_revision must be the exact FULL commit id (40 hex characters)",
            code="invalid_candidate_request",
        )
    raw_sources = payload["sources"]
    if not isinstance(raw_sources, list):
        raise AuthoringJourneyError(
            "sources must be a list of original records", code="invalid_candidate_request"
        )
    sources: list[CandidateSourceRecord] = []
    seen_ids: set[str] = set()
    for item in raw_sources:
        if not isinstance(item, dict) or set(item) != {
            "source_id",
            "original_path",
            "expected_digest",
            "intent",
        }:
            raise AuthoringJourneyError(
                "each source record needs exactly source_id, original_path, "
                "expected_digest and intent",
                code="invalid_candidate_request",
            )
        source_id = _require_text(item["source_id"], "source_id")
        if source_id in seen_ids:
            raise AuthoringJourneyError(
                f"duplicate source record for {source_id!r}",
                code="invalid_candidate_request",
            )
        seen_ids.add(source_id)
        expected = item["expected_digest"]
        if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
            raise AuthoringJourneyError(
                f"expected_digest for {source_id!r} must be 64 lowercase hex characters",
                code="invalid_candidate_request",
            )
        intent = item["intent"]
        if intent not in ("new", "update"):
            raise AuthoringJourneyError(
                f"intent for {source_id!r} must be 'new' or 'update'",
                code="invalid_candidate_request",
            )
        sources.append(
            CandidateSourceRecord(
                source_id=source_id,
                original_path=_require_text(item["original_path"], "original_path"),
                expected_digest=expected,
                intent=intent,
            )
        )
    raw_pages = payload["pages"]
    if not isinstance(raw_pages, list) or not raw_pages:
        raise AuthoringJourneyError(
            "pages must be a non-empty list of authored page file paths",
            code="invalid_candidate_request",
        )
    pages = [_require_text(item, "each pages entry") for item in raw_pages]
    control = payload.get("control")
    if control is not None:
        control = _require_text(control, "control")
    return CandidateRequest(
        schema_version=SCHEMA_VERSION,
        base_revision=base_revision,
        sources=sources,
        pages=pages,
        control=control,
    )


# ---------------------------------------------------------------------------
# Complete managed candidate (spec 0010 §3, plan J1).
# ---------------------------------------------------------------------------


class CandidateBinding(msgspec.Struct, frozen=True):
    """One exact manifest binding after the candidate, with truthful coverage."""

    entity_id: str
    source_id: str
    content_hash: str
    registered: bool  # this candidate registered/extended the version
    retained: bool  # verified original bytes present in the selected store


class CandidateResult(msgspec.Struct, frozen=True):
    """What one complete candidate wrote into the authoring worktree.

    ``page_paths`` are the EFFECTIVE applied destinations (a same-title
    revision lands at its recorded path, not the proposed slug).
    ``metadata_coverage`` and ``retained_coverage`` both count manifest
    BINDINGS (Entity→Source), not distinct sources: two Entities bound to
    one retained Source Version count as two retained bindings.
    """

    schema_version: int
    base_revision: str
    page_paths: list[str]
    entity_ids: list[str]
    registered_sources: list[str]
    bindings: list[CandidateBinding]
    metadata_coverage: int
    retained_coverage: int
    control_updated: bool
    manifest_path: str


def _refuse_request_files_inside_repository(repo_root: Path, *paths: Path) -> None:
    """Working request/pages/control files live outside the content repo."""
    for raw in paths:
        resolved = raw.expanduser().resolve()
        if resolved == repo_root or repo_root in resolved.parents:
            raise AuthoringJourneyError(
                "candidate request working files (pages, Control File) must live "
                "outside the content repository",
                code="request_inside_repository",
            )


def ingest_candidate(
    kb_root: str | Path,
    request: CandidateRequest,
    *,
    source_registry: SourceRegistry,
    artifact_store=None,
) -> CandidateResult:
    """Validate one complete candidate completely, then apply it once.

    Evaluation order (spec 0010 §3): read and parse every authored page and
    the optional complete Control File, validate the WHOLE candidate
    (ontology, Claims, cross-page references, routing) before any private
    registration or authoring-file write, verify declared digests against
    the actual original bytes, compare new/update intent with the captured
    base manifest, register and RETAIN+VERIFY new/changed originals, re-check
    manifest drift against the fully applied candidate view with exact
    registry resolution, and only then apply pages, Control File and
    manifest atomically. A failure rolls the authored tree back; immutable
    private registration residue converges on retry.
    """
    from lumio_wiki.ingest import (
        ProposedPage,
        _declared_source_ids,
        _extract_page_records,
        _validate_page_routing,
    )

    kb_path = Path(kb_root).resolve()
    manifest = _load_authoring_manifest(kb_path)
    if manifest is None:
        raise AuthoringJourneyError(
            f"no {SOURCE_REFERENCE_MANIFEST_BASENAME} beside the Knowledge Base: "
            "managed candidate authoring requires explicitly adopting a stable "
            "namespace and Source Reference Manifest first",
            code="invalid_worktree_kb",
        )
    repo_root, _subtree = resolve_repository(kb_path)
    _refuse_private_selection_inside_tree(
        kb_path, _registry_root(source_registry), _local_store_root(artifact_store)
    )
    page_paths = [Path(page) for page in request.pages]
    control_path = Path(request.control) if request.control is not None else None
    request_control_paths = [control_path] if control_path is not None else []
    _refuse_request_files_inside_repository(repo_root, *page_paths, *request_control_paths)
    original_paths = [Path(record.original_path) for record in request.sources]
    _refuse_tracked_private_paths(
        repo_root,
        "candidate original/source registry/store",
        *original_paths,
        _registry_root(source_registry),
        _local_store_root(artifact_store),
    )

    # The explicit base must carry a Source Reference Manifest in the same
    # namespace: new/update intent and unchanged bindings are judged
    # against exactly those captured bindings, never against local drift.
    try:
        captured_base = capture_revision(kb_path, request.base_revision)
    except GitAuthoringError as exc:
        raise AuthoringJourneyError(
            f"the selected base revision is not usable: {exc}",
            code="invalid_base_revision",
        ) from exc
    base_manifest = parse_source_reference_manifest(captured_base.manifest_raw)
    if base_manifest.namespace != manifest.namespace:
        raise AuthoringJourneyError(
            "the selected base revision carries a different namespace than the "
            "authoring worktree; select the exact matching base",
            code="base_namespace_mismatch",
        )

    kb, report = load_knowledge_base(kb_path)
    if not report.is_valid:
        raise AuthoringJourneyError(
            "the authoring worktree's Knowledge Base does not validate; refusing "
            "to ingest a candidate over invalid authored content",
            code="invalid_worktree_kb",
        )

    candidate_pages: list[ProposedPage] = []
    page_entities: list[tuple[ProposedPage, str]] = []
    for page_path in page_paths:
        if not page_path.is_file():
            raise AuthoringJourneyError(
                f"an authored page file does not exist: {page_path.name}",
                code="missing_page",
            )
        try:
            markdown = page_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise AuthoringJourneyError(
                f"an authored page could not be read: {exc}", code="missing_page"
            ) from exc
        pages = _extract_page_records(markdown, page_path.name, kb)
        routing_issues = [
            issue for issue in _validate_page_routing(pages, kb) if issue.severity == "error"
        ]
        if routing_issues:
            raise AuthoringJourneyError(
                "an authored page fails ingest routing validation: "
                + "; ".join(f"{issue.file}: {issue.message}" for issue in routing_issues),
                code="page_routing_error",
            )
        for page in pages:
            entity_id = _authored_entity_id(page.markdown)
            if not entity_id:
                raise AuthoringJourneyError(
                    f"the authored page at {page.relative_path!r} carries no Entity ID; "
                    "managed authoring binds sources to stable Entities",
                    code="missing_entity_id",
                )
            page_entities.append((page, entity_id))
        candidate_pages.extend(pages)

    control = None
    if control_path is not None:
        if control_path.name != _CONTROL_BASENAME or not control_path.is_file():
            raise AuthoringJourneyError(
                "the candidate Control File must be a complete lumio.yaml file",
                code="invalid_control_candidate",
            )
        try:
            control = load_control_file(control_path.parent)
        except Exception as exc:
            raise AuthoringJourneyError(
                f"the candidate Control File is invalid: {exc}",
                code="invalid_control_candidate",
            ) from exc

    # F4 for candidates: the complete page/ontology candidate is validated as
    # one fully applied tree — cross-page references between new pages and
    # ontology additions resolve together, with no invalid intermediate ingest.
    candidate_report = validate_candidate_knowledge_base(
        candidate_pages, kb_path, control_file=control
    )
    if not candidate_report.is_valid:
        raise AuthoringJourneyError(
            f"the complete candidate failed validation: {candidate_report}",
            code="invalid_candidate",
        )
    candidate_view = _refuse_profile_candidate_violations(
        kb_path, candidate_pages, removed_titles=None, control_file=control, kb=kb
    )

    # Worktree safety BEFORE any private registration (spec 0008 §2/§3.2):
    # unrelated uncommitted author edits are never overwritten.
    mutation_paths = [
        relative
        for relative in affected_mutation_paths(candidate_pages, kb_path)
        if relative != _CONTROL_BASENAME
    ]
    if control is not None:
        mutation_paths.append(_CONTROL_BASENAME)
    mutation_paths.append(SOURCE_REFERENCE_MANIFEST_BASENAME)
    try:
        _refuse_unsafe_worktree_mutation(repo_root, kb_path, mutation_paths)
    except GitAuthoringError as exc:
        raise AuthoringJourneyError(str(exc), code="unsafe_worktree") from exc

    # Source records: real bytes, handler-computed digests, base-compared intent.
    originals: dict[str, tuple[Path, bytes, str]] = {}
    for record in request.sources:
        original = Path(record.original_path)
        if not original.is_file():
            raise AuthoringJourneyError(
                f"the original for source {record.source_id!r} does not exist; "
                "refusing before registration or mutation",
                code="missing_original",
            )
        try:
            raw = original.read_bytes()
        except OSError as exc:
            raise AuthoringJourneyError(
                f"the original for source {record.source_id!r} could not be read: {exc}",
                code="missing_original",
            ) from exc
        actual = hashlib.sha256(raw).hexdigest()
        if actual != record.expected_digest:
            raise AuthoringJourneyError(
                f"the declared digest for source {record.source_id!r} does not match "
                "the actual original bytes",
                code="digest_mismatch",
            )
        in_base = record.source_id in base_manifest.sources
        if record.intent == "new" and in_base:
            raise AuthoringJourneyError(
                f"source {record.source_id!r} already exists in the selected base; "
                "an update intent records a new reviewed version of that identity",
                code="identity_conflict",
            )
        if record.intent == "update" and not in_base:
            raise AuthoringJourneyError(
                f"source {record.source_id!r} is absent from the selected base; a "
                "new intent introduces it explicitly",
                code="identity_conflict",
            )
        if record.intent == "new":
            # ``SourceRegistry.get`` raises for absent ids, so the non-raising
            # public listing supplies the existence half of the conflict check.
            existing_ids = {source.source_id for source in source_registry.list()}
            if (
                record.source_id in existing_ids
                and source_registry.find_version(record.source_id, actual) is None
            ):
                raise AuthoringJourneyError(
                    f"source {record.source_id!r} is declared new but conflicting "
                    "private history already exists under that identity",
                    code="identity_conflict",
                )
        originals[record.source_id] = (original, raw, actual)

    # Private registration + verified retention before any authoring write.
    # A missing store for new/changed originals is refused up front so no
    # hash-only success is ever reported (and no useless residue is written).
    registered: list[str] = []
    if originals:
        if artifact_store is None:
            raise AuthoringJourneyError(
                "the candidate introduces new/changed originals but no Source "
                "Artifact Store is selected; hash-only retention is never "
                "silently reported as success — select a store and retry",
                code="retention_required",
            )
        store = artifact_store
        for source_id, (original, raw, actual) in originals.items():
            version, _action = source_registry.register_version(
                source_id, raw, filename=original.name
            )
            if version.content_hash != actual:
                raise AuthoringJourneyError(
                    f"the Source Registry recorded a different content hash for "
                    f"{source_id!r} than the candidate binding; refusing inconsistent "
                    "provenance",
                    code="registration_mismatch",
                )
            registered.append(source_id)
        for source_id, (original, raw, actual) in originals.items():
            try:
                retain_artifact(
                    store,
                    source_registry,
                    source_id=source_id,
                    raw_bytes=raw,
                    content_type=None,
                    filename=original.name,
                )
            except (ArtifactStoreError, OSError) as exc:
                raise AuthoringJourneyError(
                    "Source Artifact retention failed; the immutable registration may "
                    "remain hash-only, but authoring files were not written — retry "
                    "the candidate to recover",
                    code="retention_failed",
                ) from exc
            if not store.artifact_exists(source_id=source_id, content_hash=actual):
                raise AuthoringJourneyError(
                    f"retained original bytes for {source_id!r} did not verify in the "
                    "selected store; the registration may remain, but no success is "
                    "reported — retry the candidate",
                    code="retention_failed",
                )

    # Exact bindings: pages bind their declared candidate sources to the
    # actual digest; unchanged baseline bindings are preserved verbatim.
    updated = manifest
    for page, entity_id in page_entities:
        for source_id in sorted(_declared_source_ids(page.markdown) & set(originals)):
            updated = upsert_binding(updated, entity_id, source_id, originals[source_id][2])

    # The rewritten manifest is validated against the FULLY applied candidate
    # with exact selected-registry resolution, after registration and before
    # any authoring-file write (F1): cross-page references resolve together.
    _refuse_manifest_drift(updated, candidate_view, "candidate ingest", registry=source_registry)

    # Effective destinations from the SAME pre-apply resolution the candidate
    # view and apply consume (existing title/path map of the untouched KB):
    # a same-title revision is written at its recorded path, not its slug.
    existing_by_title = {page.title: page.path for page in kb.pages if page.path}
    try:
        destinations = _resolve_proposed_destinations(candidate_pages, kb_path, existing_by_title)
    except DestinationConflict as exc:
        raise AuthoringJourneyError(str(exc), code="invalid_candidate") from exc
    applied_paths = sorted({destination.relative_path for destination in destinations})

    try:
        _apply_worktree_candidate(
            kb_path, candidate_pages, control_file=control, manifest_rewrite=updated
        )
    except MutationRollbackError:
        raise
    except GitAuthoringError as exc:
        residue = ", ".join(registered) if registered else "none"
        raise AuthoringJourneyError(
            f"the candidate could not be applied and the authored tree was "
            f"restored: {exc} (immutable private registration residue: {residue}; "
            "retry is safe)",
            code="apply_failed",
        ) from exc

    bindings = []
    metadata_coverage = 0
    retained_coverage = 0
    for entity_id, entity_bindings in sorted(updated.bindings.items()):
        for source_id, digest in sorted(entity_bindings.items()):
            has_version = source_registry.find_version(source_id, digest) is not None
            retained = artifact_store is not None and artifact_store.artifact_exists(
                source_id=source_id, content_hash=digest
            )
            if has_version:
                metadata_coverage += 1
            if retained:
                retained_coverage += 1
            bindings.append(
                CandidateBinding(
                    entity_id=entity_id,
                    source_id=source_id,
                    content_hash=digest,
                    registered=source_id in registered,
                    retained=retained,
                )
            )
    return CandidateResult(
        schema_version=SCHEMA_VERSION,
        base_revision=request.base_revision,
        page_paths=applied_paths,
        entity_ids=sorted({entity_id for _page, entity_id in page_entities}),
        registered_sources=sorted(registered),
        bindings=bindings,
        metadata_coverage=metadata_coverage,
        retained_coverage=retained_coverage,
        control_updated=control is not None,
        manifest_path=str(kb_path / SOURCE_REFERENCE_MANIFEST_BASENAME),
    )
