"""Bounded exact-byte intake and native text, PDF, and DOCX extraction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterable
from pathlib import Path

from lumio_wiki.authoring_journey import AuthoringJourneyError, extract_source
from lumio_wiki.mutation import atomic_write_bytes
from lumio_wiki.source_processor import MAX_SOURCE_BYTES
from lumio_wiki.source_registry import SourceRegistryError, _validate_source_id

from .state import Actor, Operation, WorkspaceState

_SUPPORTED_EXTENSIONS = frozenset({".docx", ".md", ".markdown", ".pdf", ".txt"})


class UploadError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_upload") -> None:
        super().__init__(message)
        self.code = code


def _input_digest(source_id: str, filename: str, digest: str) -> str:
    payload = json.dumps(
        {"source_id": source_id, "filename": filename, "sha256": digest},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_upload_metadata(source_id: str, filename: str, retry_key: str) -> None:
    try:
        _validate_source_id(source_id)
    except SourceRegistryError as exc:
        raise UploadError("source_id must be a lowercase ASCII label") from exc
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or not filename.isprintable()
        or len(filename) > 160
    ):
        raise UploadError("filename must be a safe basename", code="unsafe_path")
    if Path(filename).suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise UploadError(
            "unsupported original; supported inputs are .txt, .md, .markdown, .pdf, and .docx",
            code="unsupported_original",
        )
    if not 1 <= len(retry_key) <= 200 or not retry_key.isprintable():
        raise UploadError("retry key must be printable and at most 200 characters")


class IntakeService:
    def __init__(self, state: WorkspaceState, private_root: Path) -> None:
        self.state = state
        self.private_root = private_root.resolve()

    async def read_bounded(self, chunks: AsyncIterable[bytes]) -> bytes:
        raw = bytearray()
        async for chunk in chunks:
            raw.extend(chunk)
            if len(raw) > MAX_SOURCE_BYTES:
                raise UploadError("original exceeds the 25 MiB limit", code="source_too_large")
        if not raw:
            raise UploadError("original is empty", code="empty_extraction")
        return bytes(raw)

    def _path(self, operation_id: str, filename: str) -> Path:
        return self.private_root / "uploads" / operation_id / filename

    def save(
        self,
        workspace_id: str,
        actor: Actor,
        source_id: str,
        filename: str,
        retry_key: str,
        raw: bytes,
    ) -> dict:
        validate_upload_metadata(source_id, filename, retry_key)
        digest = hashlib.sha256(raw).hexdigest()
        input_digest = _input_digest(source_id, filename, digest)
        operation, created = self.state.start_operation(
            workspace_id,
            actor,
            "upload",
            retry_key,
            input_digest,
            source_id=source_id,
        )
        path = self._path(operation.operation_id, filename)
        response = {
            "upload_id": operation.operation_id,
            "source_id": source_id,
            "filename": filename,
            "sha256": digest,
            "size": len(raw),
        }
        if operation.status == "ready" and path.is_file():
            try:
                retained = path.read_bytes()
            except OSError:
                retained = b""
            if hashlib.sha256(retained).hexdigest() == digest and len(retained) == len(raw):
                return {**response, "reused": not created}
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, raw)
        self.state.finish_operation(workspace_id, actor, operation, "ready", response)
        return {**response, "reused": not created}

    def load(self, workspace_id: str, actor: Actor, upload_id: str) -> tuple[Operation, Path]:
        operation = self.state.get_operation(workspace_id, actor, "upload", upload_id)
        if operation is None or operation.status != "ready":
            raise UploadError("upload is not available", code="upload_not_found")
        path = self._path(upload_id, operation.response["filename"])
        if not path.is_file():
            raise UploadError("uploaded original is unavailable", code="upload_not_found")
        return operation, path

    def extract(self, workspace_id: str, actor: Actor, upload_id: str) -> tuple[dict, dict]:
        operation, path = self.load(workspace_id, actor, upload_id)
        try:
            extracted = extract_source(
                path,
                output_dir=self.private_root / "extractions",
            )
        except AuthoringJourneyError as exc:
            raise UploadError(str(exc), code=exc.code) from exc
        facts = {
            "source_id": operation.source_id,
            "filename": operation.response["filename"],
            "sha256": extracted.source_sha256,
            "size": extracted.size,
            "processor": extracted.processor,
            "incomplete": extracted.incomplete,
            "section_count": len(extracted.sections),
            "exclusions": [],
        }
        material = {
            **facts,
            "upload_id": upload_id,
            "text": extracted.text,
            "sections": extracted.sections,
        }
        return material, facts
