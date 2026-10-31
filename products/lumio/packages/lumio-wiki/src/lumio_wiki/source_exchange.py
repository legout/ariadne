"""Private Source Exchange transport (spec 0010 §6 r4, plan 0010 J4).

Moves the two accepted private transfer kinds — the metadata-only **Source
Baseline Snapshot** (J0) and the full **Source Handoff Bundle** (J3) —
through an explicitly selected private S3-compatible exchange. The archive
formats, integrity contracts and importers stay owned by
:mod:`lumio_wiki.source_handoff`; this module is transport only and never
builds a second importer or validator.

Transport contract (spec 0010 §6 revision 4): local input is captured once
into bounded private temporary storage and validated through the existing
transfer validators; those same captured bytes are streamed through
multipart put to a fresh private ``_staging/<256-bit attempt>/transfer.tar``
key (never reused across attempts, never published as a transfer reference)
and promoted with an atomic server-side copy-if-absent to the immutable
``<transfer_id>/transfer.tar`` final key. The complete final object is
verified by streamed read-back, and only then is the small create-only
``<transfer_id>/ready.json`` completion record published. A lost copy/ready
response is recovered by verifying the remote outcome; matching bytes
converge, different bytes refuse as a conflict, and a service without
conditional copy yields a distinct capability refusal while manual transfer
remains available. Temporary remote residue is operator-controlled; local
operation temporaries are always removed. Importers never depend on the
exchange after import.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any

import msgspec

from lumio_wiki.private_profile import ResolvedS3Exchange
from lumio_wiki.s3_location import _join
from lumio_wiki.source_handoff import (
    _ARCHIVE_OVERHEAD_MAX_BYTES,
    BASELINE_KIND,
    CONTAINER_OVERHEAD_MAX_BYTES,
    HANDOFF_KIND,
    MANIFEST_MAX_BYTES,
    TOTAL_PAYLOAD_MAX_BYTES,
    SourceBaselineError,
    SourceHandoffError,
    _parse_baseline_manifest,
    _read_snapshot_manifest,
    _read_verified_archive,
    _stream_validate_handoff,
)

__all__ = [
    "READY_MAX_BYTES",
    "SOURCE_EXCHANGE_SCHEMA_VERSION",
    "SourceExchangeError",
    "SourceTransfer",
    "download_source_transfer",
    "upload_source_transfer",
]

#: Schema version of the ``SourceTransfer`` result and the ready record.
SOURCE_EXCHANGE_SCHEMA_VERSION = 1

#: The transfer/ready object names under ``<exchange-prefix>/<transfer_id>/``.
TRANSFER_MEMBER = "transfer.tar"
READY_MEMBER = "ready.json"

#: A completion record is a tiny strict JSON object; anything larger refuses.
READY_MAX_BYTES = 64 * 1024

#: Cumulative ceiling on actual local reads while capturing or uploading one
#: transfer (plan 0010 transfer bounds: 4 MiB manifest + 2 GiB payload +
#: 8 MiB container overhead). The ceiling is enforced on bytes actually read,
#: not only on stat/head results.
_UPLOAD_READ_CEILING = MANIFEST_MAX_BYTES + TOTAL_PAYLOAD_MAX_BYTES + CONTAINER_OVERHEAD_MAX_BYTES

#: Kind-specific download ceilings from the same accepted transfer bounds
#: (review F1): a baseline snapshot container is the 4 MiB manifest plus tar
#: overhead; a full handoff adds the 2 GiB payload and container-overhead
#: allowances. The ceiling over the REMOTE declared count is enforced before
#: any archive fetch, and independently on the actual streamed bytes.
_BASELINE_ARCHIVE_CEILING = MANIFEST_MAX_BYTES + _ARCHIVE_OVERHEAD_MAX_BYTES
_FULL_ARCHIVE_CEILING = MANIFEST_MAX_BYTES + TOTAL_PAYLOAD_MAX_BYTES + CONTAINER_OVERHEAD_MAX_BYTES

#: Bounded local I/O unit for capture, download staging and remote streams.
_IO_CHUNK_BYTES = 1024 * 1024

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_READY_KEYS = frozenset({"schema_version", "kind", "transfer_id", "byte_count", "sha256"})
_KNOWN_KINDS = frozenset({BASELINE_KIND, HANDOFF_KIND})


class SourceExchangeError(ValueError):
    """A Source Exchange operation failed with a safe, actionable category.

    ``code`` is one of the stable machine codes (``invalid_source_exchange``,
    ``exchange_not_found``, ``exchange_access_denied``, ``exchange_conflict``,
    ``exchange_integrity_mismatch``, ``exchange_unsupported``). Messages may
    name the operation and capability but never echo raw SDK exceptions, which
    can contain endpoints, bucket/prefix locations or credentials.
    """

    def __init__(self, message: str, *, code: str = "invalid_source_exchange") -> None:
        super().__init__(message)
        self.code = code


class SourceTransfer(msgspec.Struct, frozen=True):
    """The result of one exchange upload or download (public-safe fields only).

    No local path, bucket, prefix, endpoint or credential material appears in
    this record: the caller already knows the paths it selected.
    """

    schema_version: int
    operation: str
    kind: str
    transfer_id: str
    byte_count: int
    sha256: str


def _require_hex64(value: object, what: str) -> str:
    if not isinstance(value, str) or not _HEX64.match(value):
        raise SourceExchangeError(f"{what} must be exactly 64 lowercase hex characters")
    return value


def _require_ready_hex(value: object, what: str) -> str:
    """A malformed REMOTE ready field is an integrity failure (review F2)."""
    if not isinstance(value, str) or not _HEX64.match(value):
        raise SourceExchangeError(
            f"the completion record {what} must be exactly 64 lowercase hex characters",
            code="exchange_integrity_mismatch",
        )
    return value


def _obstore() -> Any:
    """The locked obstore module, normalized to the exchange boundary (F5).

    The optional-extra guard's actionable install guidance is preserved
    verbatim; its foreign exception type never crosses the public boundary.
    """
    from lumio_wiki.knowledge_base import KnowledgeBaseError
    from lumio_wiki.s3_location import _require_obstore

    try:
        return _require_obstore()
    except KnowledgeBaseError as exc:
        raise SourceExchangeError(str(exc)) from exc


def _archive_ceiling(kind: str) -> int:
    """The accepted container bound for one transfer kind (review F1)."""
    if kind == BASELINE_KIND:
        return _BASELINE_ARCHIVE_CEILING
    return _FULL_ARCHIVE_CEILING


def _refuse_inside_git_worktree(path: str | Path, what: str) -> None:
    """Refuse a private selection inside ANY Git worktree (review F4).

    Resolved paths (symlinked parents included) are checked for an enclosing
    ``.git`` marker so private transfers and originals never enter a content
    repository — including ignored directories — regardless of CLI mode.
    """
    resolved = Path(path).resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise SourceExchangeError(
                f"the {what} resolves inside a Git worktree; private transfer "
                "artifacts never enter content repositories — select a private "
                "location outside every worktree"
            )


def _exchange_parts(exchange: ResolvedS3Exchange) -> tuple[Any, str]:
    store = getattr(exchange, "store", None)
    prefix = getattr(exchange, "prefix", None)
    if store is None or not isinstance(prefix, str):
        raise SourceExchangeError(
            "the exchange must be an explicitly resolved private exchange client "
            "(resolve_private_profile with needs={'exchange'}, or the CLI's "
            "explicit exchange selection)"
        )
    return store, prefix.strip("/")


def _classify_remote(exc: BaseException, what: str) -> SourceExchangeError | None:
    """Map the named obstore failures to safe categories; never echo details."""
    from obstore.exceptions import PermissionDeniedError, UnauthenticatedError

    if isinstance(exc, FileNotFoundError):
        return SourceExchangeError(
            f"the {what} is not present in the private exchange", code="exchange_not_found"
        )
    if isinstance(exc, (PermissionDeniedError, UnauthenticatedError)):
        return SourceExchangeError(
            "the private exchange denied access for this operation",
            code="exchange_access_denied",
        )
    return None


def _temp_workspace() -> Path:
    """One private capture workspace outside any Git worktree.

    The system temporary directory is resolved (symlinks included) and refused
    when it sits inside a Git worktree: private captured transfer bytes never
    land inside a content repository through ambient TMPDIR selection.
    """
    root_of_temp = None
    try:
        root_of_temp = Path(tempfile.gettempdir()).resolve()
    except OSError as exc:
        # F5: discovery failures (CPython's documented FileNotFoundError
        # listing candidate directories) stay inside the operation boundary;
        # candidate paths never enter the message.
        raise SourceExchangeError(
            "allocating private temporary storage failed; no usable temporary "
            "directory is available — free space or point TMPDIR at private "
            "storage and retry",
        ) from exc
    _refuse_inside_git_worktree(root_of_temp, "configured temporary directory")
    try:
        return Path(tempfile.mkdtemp(prefix="lumio-source-exchange-"))
    except OSError as exc:
        raise SourceExchangeError(
            "allocating private temporary storage failed; free space or point "
            "TMPDIR at private storage and retry",
        ) from exc


def _capture_transfer(transfer_path: Path, workspace: Path) -> tuple[Path, str, int]:
    """Capture the local transfer once, bounded; return (file, sha256, size).

    The captured file is the single byte source for validation AND upload, so
    a user mutating the original path mid-operation cannot desynchronize the
    advertised digest from the uploaded bytes.
    """
    try:
        size_hint = transfer_path.stat().st_size
    except OSError as exc:
        raise SourceExchangeError(
            "the transfer file could not be opened; select the exported transfer "
            "artifact and retry",
        ) from exc
    if size_hint > _UPLOAD_READ_CEILING:
        raise SourceExchangeError(
            f"the transfer file exceeds the container bound ({size_hint} bytes); an "
            "explicit refusal, never a partial transfer"
        )
    captured = workspace / "transfer.tar"
    digest = hashlib.sha256()
    total = 0
    try:
        with open(transfer_path, "rb") as source, open(captured, "wb") as target:
            while True:
                chunk = source.read(_IO_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _UPLOAD_READ_CEILING:
                    raise SourceExchangeError(
                        "the transfer file exceeds the container bound while being "
                        "read (a changed or growing file); an explicit refusal, never "
                        "a partial transfer"
                    )
                digest.update(chunk)
                target.write(chunk)
    except OSError as exc:
        raise SourceExchangeError(
            "the transfer file could not be read; select the exported transfer artifact and retry",
        ) from exc
    if total == 0:
        raise SourceExchangeError("the transfer file is empty; a transfer archive is required")
    return captured, digest.hexdigest(), total


def _validated_transfer(captured: Path, digest: str) -> tuple[str, str]:
    """Validate the captured bytes through the J0/J3 validators; (kind, id).

    The baseline validator self-bounds to the manifest-only container; any
    archive it refuses falls through to the full streamed handoff validator.
    Exactly one kind can claim the artifact because both parsers refuse the
    other kind by name.
    """
    try:
        data, _ = _read_verified_archive(captured, digest)
        parsed = _parse_baseline_manifest(_read_snapshot_manifest(data))
        return BASELINE_KIND, parsed.transfer_id
    except SourceBaselineError:
        pass
    try:
        parsed_handoff, _ = _stream_validate_handoff(captured, digest, staging_dir=None)
        return HANDOFF_KIND, parsed_handoff.transfer_id
    except SourceHandoffError as exc:
        raise SourceExchangeError(
            "the file is not a valid private source transfer archive: export a Source "
            "Baseline Snapshot or Source Handoff Bundle through their commands first "
            f"({exc})"
        ) from exc


class _BoundedUploadReader(io.RawIOBase):
    """A seekable bounded reader over the captured file for multipart put.

    obstore determines the length through seek/tell and streams in bounded
    chunks (probed against the designated service); this wrapper additionally
    enforces the cumulative read ceiling and never allocates more than one
    bounded chunk per call, whatever the caller requests.
    """

    def __init__(self, path: Path, ceiling: int) -> None:
        self._handle = open(path, "rb")
        self._ceiling = ceiling
        self._consumed = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._handle.seek(offset, whence)

    def tell(self) -> int:
        return self._handle.tell()

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            size = _IO_CHUNK_BYTES
        size = min(size, _IO_CHUNK_BYTES)
        if size == 0:
            return b""
        data = self._handle.read(size)
        self._consumed += len(data)
        if self._consumed > self._ceiling:
            raise SourceExchangeError(
                "the captured transfer exceeded the container bound while being "
                "uploaded; retry the upload with a valid transfer file"
            )
        return data

    def close(self) -> None:
        try:
            self._handle.close()
        finally:
            super().close()


def _get_bounded(store: Any, key: str, limit: int) -> bytes:
    """Read one small remote object fully, refusing anything beyond ``limit``."""
    obstore = _obstore()
    try:
        meta = obstore.head(store, key)
        if meta["size"] > limit:
            raise SourceExchangeError(
                f"the remote object exceeds its expected bound ({meta['size']} bytes)",
                code="exchange_integrity_mismatch",
            )
        result = obstore.get(store, key)
        chunks: list[bytes] = []
        total = 0
        for buf in result.stream(min_chunk_size=_IO_CHUNK_BYTES):
            total += len(buf)
            if total > limit:
                raise SourceExchangeError(
                    "the remote object exceeds its expected bound while being read",
                    code="exchange_integrity_mismatch",
                )
            chunks.append(buf)
    except SourceExchangeError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified below, never echoed
        classified = _classify_remote(exc, "remote object")
        if classified is not None:
            raise classified from exc
        raise SourceExchangeError(
            "the private exchange could not be read; retry the operation",
        ) from exc
    return b"".join(chunks)


def _verify_final(store: Any, key: str, *, digest: str, byte_count: int) -> None:
    """Stream-verify the complete final object's byte count and digest."""
    obstore = _obstore()
    try:
        meta = obstore.head(store, key)
        if meta["size"] != byte_count:
            raise SourceExchangeError(
                f"the remote transfer object carries {meta['size']} bytes, not the "
                f"expected {byte_count}",
                code="exchange_integrity_mismatch",
            )
        result = obstore.get(store, key)
        hasher = hashlib.sha256()
        total = 0
        for buf in result.stream(min_chunk_size=_IO_CHUNK_BYTES):
            total += len(buf)
            if total > byte_count:
                raise SourceExchangeError(
                    "the remote transfer object exceeds its expected byte count",
                    code="exchange_integrity_mismatch",
                )
            hasher.update(buf)
        if total != byte_count or hasher.hexdigest() != digest:
            raise SourceExchangeError(
                "the remote transfer object failed integrity verification against "
                "the expected digest or byte count",
                code="exchange_integrity_mismatch",
            )
    except SourceExchangeError:
        raise
    except Exception as exc:  # noqa: BLE001
        classified = _classify_remote(exc, "remote transfer object")
        if classified is not None:
            raise classified from exc
        raise SourceExchangeError(
            "the private exchange could not be verified; retry the operation",
        ) from exc


def _copy_to_final(
    store: Any, staging_key: str, final_key: str, *, digest: str, byte_count: int
) -> None:
    """Atomic copy-if-absent to the final key with lost-response recovery."""
    from obstore.exceptions import AlreadyExistsError, NotSupportedError

    obstore = _obstore()
    try:
        obstore.copy(store, staging_key, final_key, overwrite=False)
        return
    except AlreadyExistsError:
        try:
            _verify_final(store, final_key, digest=digest, byte_count=byte_count)
            return  # an identical retry converges on the existing immutable object
        except SourceExchangeError as exc:
            if exc.code != "exchange_integrity_mismatch":
                # F7: denied, missing or transient verification keeps its own
                # category — it is not an identity conflict.
                raise
            # Readable verified bytes differ: a genuine identity conflict.
            raise SourceExchangeError(
                "a different transfer already exists under this transfer identifier; "
                "resolve the conflict explicitly — the existing final object is "
                "immutable and was not modified",
                code="exchange_conflict",
            ) from exc
    except NotSupportedError as exc:
        raise SourceExchangeError(
            "the private exchange does not support the required atomic conditional "
            "copy; use manual private transfer or an exchange service with "
            "copy-if-not-exists support",
            code="exchange_unsupported",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        classified = _classify_remote(exc, "final transfer object")
        if classified is not None:
            raise classified from exc
        # A lost response proves neither success nor failure: verify the remote
        # outcome instead of assuming one.
        try:
            _verify_final(store, final_key, digest=digest, byte_count=byte_count)
            return
        except SourceExchangeError as verify_exc:
            if verify_exc.code == "exchange_integrity_mismatch":
                # F7: verified different bytes after a lost response conflict.
                raise SourceExchangeError(
                    "a different transfer already exists under this transfer "
                    "identifier; resolve the conflict explicitly — the existing "
                    "final object is immutable and was not modified",
                    code="exchange_conflict",
                ) from verify_exc
            if verify_exc.code in ("exchange_access_denied", "exchange_not_found"):
                # F7: a denied or genuinely-absent final keeps its truthful
                # classified category after an ambiguous copy response.
                raise verify_exc from exc
            # Absence or a transient outcome after a lost response: retry the
            # operation; absence alone is not an identity conflict.
            raise SourceExchangeError(
                "the conditional copy to the private exchange failed before the "
                "final object was verifiable; retry the upload with the same "
                "transfer file",
            ) from exc


def _ready_payload(kind: str, transfer_id: str, byte_count: int, sha256: str) -> bytes:
    return json.dumps(
        {
            "byte_count": byte_count,
            "kind": kind,
            "schema_version": SOURCE_EXCHANGE_SCHEMA_VERSION,
            "sha256": sha256,
            "transfer_id": transfer_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _publish_ready(store: Any, ready_key: str, payload: bytes) -> None:
    """Create-only ready publication with identical-retry and lost recovery."""
    from obstore.exceptions import AlreadyExistsError, NotSupportedError

    obstore = _obstore()
    try:
        obstore.put(store, ready_key, payload, mode="create")
        return
    except AlreadyExistsError:
        try:
            existing = _get_bounded(store, ready_key, READY_MAX_BYTES)
        except SourceExchangeError as exc:
            if exc.code != "exchange_integrity_mismatch":
                # F7: denied, missing or transient comparison failures keep
                # their own truthful category — only an established different
                # record is a conflict.
                raise
            raise SourceExchangeError(
                "a completion record for this transfer identifier exists but could "
                "not be compared; it is immutable and never rewritten",
                code="exchange_conflict",
            ) from exc
        if existing == payload:
            return  # an identical retry converges; ready is never rewritten
        raise SourceExchangeError(
            "a different completion record already exists for this transfer "
            "identifier; resolve the conflict explicitly",
            code="exchange_conflict",
        ) from None
    except NotSupportedError as exc:
        raise SourceExchangeError(
            "the private exchange does not support the required create-only "
            "publication; use manual private transfer or an exchange service with "
            "conditional put support",
            code="exchange_unsupported",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        classified = _classify_remote(exc, "completion record")
        if classified is not None:
            raise classified from exc
        try:
            existing = _get_bounded(store, ready_key, READY_MAX_BYTES)
        except SourceExchangeError as verify_exc:
            if verify_exc.code == "exchange_access_denied":
                raise verify_exc from exc
            if verify_exc.code == "exchange_integrity_mismatch":
                # F7: an unreadable/oversized existing record after a lost
                # response is a different record: conflict.
                raise SourceExchangeError(
                    "a different completion record already exists for this "
                    "transfer identifier; resolve the conflict explicitly",
                    code="exchange_conflict",
                ) from verify_exc
            # Expected absence after a failed NEW write (or a transient read):
            # the original failed-write category stands — absence alone is not
            # an identity conflict.
        else:
            if existing == payload:
                return  # the write landed; only the response was lost
            raise SourceExchangeError(
                "a different completion record already exists for this transfer "
                "identifier; resolve the conflict explicitly",
                code="exchange_conflict",
            ) from None
        raise SourceExchangeError(
            "publishing the completion record failed; retry the upload with the same transfer file",
        ) from exc


def _parse_ready(payload: bytes) -> tuple[str, str, int, str]:
    """Strictly parse one ready.json: (kind, transfer_id, byte_count, sha256)."""

    def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise SourceExchangeError(
                    f"duplicate completion record key {key!r}",
                    code="exchange_integrity_mismatch",
                )
            seen.add(key)
            result[key] = value
        return result

    try:
        record = json.loads(payload, object_pairs_hook=_reject_duplicates)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceExchangeError(
            "the completion record is not valid JSON",
            code="exchange_integrity_mismatch",
        ) from exc
    if not isinstance(record, dict) or set(record) != _READY_KEYS:
        raise SourceExchangeError(
            "the completion record does not carry exactly the expected fields",
            code="exchange_integrity_mismatch",
        )
    version = record["schema_version"]
    if type(version) is not int or version != SOURCE_EXCHANGE_SCHEMA_VERSION:
        raise SourceExchangeError(
            "unsupported completion record schema version",
            code="exchange_integrity_mismatch",
        )
    kind = record["kind"]
    if not isinstance(kind, str) or kind not in _KNOWN_KINDS:
        raise SourceExchangeError(
            "the completion record names an unknown artifact kind",
            code="exchange_integrity_mismatch",
        )
    transfer_id = _require_ready_hex(record["transfer_id"], "transfer_id")
    sha256 = _require_ready_hex(record["sha256"], "sha256")
    byte_count = record["byte_count"]
    if type(byte_count) is not int or byte_count <= 0:
        raise SourceExchangeError(
            "the completion record byte_count must be a positive integer",
            code="exchange_integrity_mismatch",
        )
    return kind, transfer_id, byte_count, sha256


def upload_source_transfer(
    transfer_path: str | Path, *, exchange: ResolvedS3Exchange
) -> SourceTransfer:
    """Upload one captured, validated transfer; publish readiness LAST.

    The local file is captured once into bounded private temporary storage,
    validated through the J0/J3 transfer validators, streamed to a unique
    private staging key, promoted by atomic copy-if-absent to the immutable
    final key, verified by complete streamed read-back, and only then
    advertised by a create-only completion record. Retries with the same
    bytes converge; different bytes under the same identifier refuse as a
    conflict. The returned record is public-safe.
    """
    obstore = _obstore()
    store, prefix = _exchange_parts(exchange)
    path = Path(transfer_path)
    _refuse_inside_git_worktree(path, "transfer file")
    if not path.is_file():
        raise SourceExchangeError(
            "the transfer file does not exist; select the exported transfer artifact"
        )
    workspace = _temp_workspace()
    try:
        captured, digest, byte_count = _capture_transfer(path, workspace)
        kind, transfer_id = _validated_transfer(captured, digest)
        staging_key = _join(prefix, "_staging", secrets.token_hex(32), TRANSFER_MEMBER)
        try:
            reader = _BoundedUploadReader(captured, _UPLOAD_READ_CEILING)
        except OSError as exc:
            raise SourceExchangeError(
                "the captured transfer could not be reopened for upload; retry "
                "the upload with the same transfer file",
            ) from exc
        try:
            with reader:
                obstore.put(store, staging_key, reader)
        except SourceExchangeError:
            raise
        except Exception as exc:  # noqa: BLE001
            classified = _classify_remote(exc, "temporary staging object")
            if classified is not None:
                raise classified from exc
            raise SourceExchangeError(
                "uploading the transfer to the private exchange failed; retry the "
                "upload with the same transfer file",
            ) from exc
        final_key = _join(prefix, transfer_id, TRANSFER_MEMBER)
        _copy_to_final(store, staging_key, final_key, digest=digest, byte_count=byte_count)
        _verify_final(store, final_key, digest=digest, byte_count=byte_count)
        _publish_ready(
            store,
            _join(prefix, transfer_id, READY_MEMBER),
            _ready_payload(kind, transfer_id, byte_count, digest),
        )
        return SourceTransfer(
            schema_version=SOURCE_EXCHANGE_SCHEMA_VERSION,
            operation="upload",
            kind=kind,
            transfer_id=transfer_id,
            byte_count=byte_count,
            sha256=digest,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _stream_to_staged(
    store: Any, key: str, staged: Path, *, byte_count: int, max_bytes: int
) -> str:
    """Stream the final object into private staging while hashing it.

    Both the declared byte count and the independent kind ceiling bound the
    actual streamed bytes (review F1): a remote-advertised count is never the
    only resource authority.
    """
    obstore = _obstore()
    hasher = hashlib.sha256()
    total = 0
    try:
        result = obstore.get(store, key)
        with open(staged, "wb") as target:
            for buf in result.stream(min_chunk_size=_IO_CHUNK_BYTES):
                total += len(buf)
                if total > byte_count or total > max_bytes:
                    raise SourceExchangeError(
                        "the remote transfer object exceeds its expected byte count",
                        code="exchange_integrity_mismatch",
                    )
                hasher.update(buf)
                target.write(buf)
    except SourceExchangeError:
        raise
    except Exception as exc:  # noqa: BLE001
        classified = _classify_remote(exc, "remote transfer object")
        if classified is not None:
            raise classified from exc
        raise SourceExchangeError(
            "downloading the transfer from the private exchange failed; retry the download",
        ) from exc
    if total != byte_count:
        raise SourceExchangeError(
            f"the remote transfer object carries {total} bytes, not the expected {byte_count}",
            code="exchange_integrity_mismatch",
        )
    return hasher.hexdigest()


def _identical_output(output: Path, *, digest: str, byte_count: int) -> bool:
    """Whether an existing output file already carries the verified bytes."""
    hasher = hashlib.sha256()
    read = 0
    try:
        with open(output, "rb") as handle:
            while True:
                chunk = handle.read(_IO_CHUNK_BYTES)
                if not chunk:
                    break
                read += len(chunk)
                if read > byte_count:
                    return False
                hasher.update(chunk)
    except OSError as exc:
        raise SourceExchangeError(
            "the existing output file could not be read; remove it or choose another output path",
            code="exchange_conflict",
        ) from exc
    return read == byte_count and hasher.hexdigest() == digest


def _publish_output(staged: Path, output: Path, *, digest: str, byte_count: int) -> None:
    """Publish verified bytes atomically onto the destination filesystem (F3).

    The verified archive is copied into an operation-owned private temporary
    ON the destination filesystem (re-verified byte-for-byte while copying),
    then published with a create-only hard link: never a copy into the final
    name, never replace-existing. An unrelated destination appearing
    concurrently makes the link fail; identical bytes converge, different
    bytes conflict, and an unsupported primitive is a safe bounded failure.
    """
    fd, temp_name = tempfile.mkstemp(dir=output.parent, prefix=".lumio-exchange-", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        hasher = hashlib.sha256()
        total = 0
        with os.fdopen(fd, "wb") as target, open(staged, "rb") as source:
            while True:
                chunk = source.read(_IO_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                hasher.update(chunk)
                target.write(chunk)
        if total != byte_count or hasher.hexdigest() != digest:
            raise SourceExchangeError(
                "staging the verified transfer onto the destination filesystem "
                "failed its byte count or digest verification",
                code="exchange_integrity_mismatch",
            )
        try:
            os.link(temp_path, output)
        except FileExistsError:
            if _identical_output(output, digest=digest, byte_count=byte_count):
                return  # a concurrent identical publication converges
            raise SourceExchangeError(
                "the output file already exists with different bytes; remove it "
                "or choose another output path",
                code="exchange_conflict",
            ) from None
        except OSError as exc:
            raise SourceExchangeError(
                "atomic no-clobber publication is not supported on the selected "
                "output filesystem; choose a filesystem supporting atomic "
                "publication",
            ) from exc
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass  # best-effort cleanup of the operation-owned temporary


def download_source_transfer(
    transfer_id: str,
    digest: str,
    *,
    exchange: ResolvedS3Exchange,
    output_path: str | Path,
) -> SourceTransfer:
    """Download one transfer after its completion record and bytes verify.

    The exact identifier plus expected digest are caller-supplied; the ready
    record must match both, the complete artifact is streamed into private
    staging and fully validated (digest, byte count, kind and manifest
    identity through the J0/J3 validators) before anything is exposed at
    ``output_path``. Failures never leave a partial or unverified output and
    never mutate any registry or store.
    """
    store, prefix = _exchange_parts(exchange)
    _require_hex64(transfer_id, "the transfer identifier")
    _require_hex64(digest, "the expected transfer digest")
    output = Path(output_path)
    _refuse_inside_git_worktree(output, "download output path")
    ready_key = _join(prefix, transfer_id, READY_MEMBER)
    final_key = _join(prefix, transfer_id, TRANSFER_MEMBER)
    try:
        ready_bytes = _get_bounded(store, ready_key, READY_MAX_BYTES)
    except SourceExchangeError as exc:
        if exc.code == "exchange_not_found":
            raise SourceExchangeError(
                "no completion record exists for this transfer identifier; the upload "
                "may be incomplete — retry the upload or verify the identifier and "
                "digest",
                code="exchange_not_found",
            ) from exc
        raise
    if not ready_bytes:
        raise SourceExchangeError(
            "no completion record exists for this transfer identifier; the upload "
            "may be incomplete — retry the upload or verify the identifier and digest",
            code="exchange_not_found",
        )
    kind, ready_id, byte_count, ready_sha = _parse_ready(ready_bytes)
    if ready_id != transfer_id or ready_sha != digest:
        raise SourceExchangeError(
            "the completion record does not match the requested transfer identifier "
            "and expected digest",
            code="exchange_integrity_mismatch",
        )
    # F1: the remote declared count is never resource authority — refuse any
    # count above the kind's written container ceiling BEFORE fetching bytes.
    ceiling = _archive_ceiling(kind)
    if byte_count > ceiling:
        raise SourceExchangeError(
            f"the completion record declares {byte_count} bytes, above its "
            "transfer kind's container ceiling; an explicit refusal, never an "
            "unbounded download",
            code="exchange_integrity_mismatch",
        )
    if not output.parent.exists():
        raise SourceExchangeError(
            "the output parent directory does not exist; create it or select "
            "another output location"
        )
    workspace = _temp_workspace()
    staged = workspace / TRANSFER_MEMBER
    try:
        actual = _stream_to_staged(
            store, final_key, staged, byte_count=byte_count, max_bytes=ceiling
        )
        if actual != digest:
            raise SourceExchangeError(
                "the downloaded transfer failed integrity verification against the expected digest",
                code="exchange_integrity_mismatch",
            )
        archive_kind, archive_id = _validated_transfer(staged, digest)
        if archive_kind != kind or archive_id != transfer_id:
            raise SourceExchangeError(
                "the downloaded archive does not match its completion record's kind "
                "or transfer identifier",
                code="exchange_integrity_mismatch",
            )
        if output.exists():
            # Never silently destroy an unrelated existing local file; an
            # identical prior download is the convergent retry.
            if not _identical_output(output, digest=digest, byte_count=byte_count):
                raise SourceExchangeError(
                    "the output file already exists with different bytes; remove it "
                    "or choose another output path",
                    code="exchange_conflict",
                )
        else:
            try:
                _publish_output(staged, output, digest=digest, byte_count=byte_count)
            except OSError as exc:
                raise SourceExchangeError(
                    "publishing the verified transfer failed on a local I/O "
                    "error; retry the download",
                ) from exc
        return SourceTransfer(
            schema_version=SOURCE_EXCHANGE_SCHEMA_VERSION,
            operation="download",
            kind=kind,
            transfer_id=transfer_id,
            byte_count=byte_count,
            sha256=digest,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
