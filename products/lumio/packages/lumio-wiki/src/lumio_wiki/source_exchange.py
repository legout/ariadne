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
from lumio_wiki.s3_location import _join, _require_obstore
from lumio_wiki.source_handoff import (
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
    root = Path(tempfile.gettempdir()).resolve()
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            raise SourceExchangeError(
                "the configured temporary directory resolves inside a Git worktree; "
                "point TMPDIR at private storage outside content repositories"
            )
    return Path(tempfile.mkdtemp(prefix="lumio-source-exchange-"))


def _capture_transfer(transfer_path: Path, workspace: Path) -> tuple[Path, str, int]:
    """Capture the local transfer once, bounded; return (file, sha256, size).

    The captured file is the single byte source for validation AND upload, so
    a user mutating the original path mid-operation cannot desynchronize the
    advertised digest from the uploaded bytes.
    """
    try:
        size_hint = transfer_path.stat().st_size
    except OSError as exc:
        raise SourceExchangeError(f"the transfer file could not be opened: {exc}") from exc
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
        raise SourceExchangeError(f"the transfer file could not be read: {exc}") from exc
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
    obstore = _require_obstore()
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
    obstore = _require_obstore()
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

    obstore = _require_obstore()
    try:
        obstore.copy(store, staging_key, final_key, overwrite=False)
        return
    except AlreadyExistsError:
        try:
            _verify_final(store, final_key, digest=digest, byte_count=byte_count)
            return  # an identical retry converges on the existing immutable object
        except SourceExchangeError as exc:
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
        except SourceExchangeError:
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

    obstore = _require_obstore()
    try:
        obstore.put(store, ready_key, payload, mode="create")
        return
    except AlreadyExistsError:
        try:
            if _get_bounded(store, ready_key, READY_MAX_BYTES) == payload:
                return  # an identical retry converges; ready is never rewritten
        except SourceExchangeError as exc:
            raise SourceExchangeError(
                "a completion record for this transfer identifier exists but could "
                "not be compared; it is immutable and never rewritten",
                code="exchange_conflict",
            ) from exc
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
            if _get_bounded(store, ready_key, READY_MAX_BYTES) == payload:
                return  # the write landed; only the response was lost
        except SourceExchangeError:
            pass
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
    if kind not in _KNOWN_KINDS:
        raise SourceExchangeError(
            "the completion record names an unknown artifact kind",
            code="exchange_integrity_mismatch",
        )
    transfer_id = _require_hex64(record["transfer_id"], "the completion record transfer_id")
    sha256 = _require_hex64(record["sha256"], "the completion record sha256")
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
    obstore = _require_obstore()
    store, prefix = _exchange_parts(exchange)
    path = Path(transfer_path)
    if not path.is_file():
        raise SourceExchangeError(f"transfer file not found: {path}")
    workspace = _temp_workspace()
    try:
        captured, digest, byte_count = _capture_transfer(path, workspace)
        kind, transfer_id = _validated_transfer(captured, digest)
        staging_key = _join(prefix, "_staging", secrets.token_hex(32), TRANSFER_MEMBER)
        try:
            reader = _BoundedUploadReader(captured, _UPLOAD_READ_CEILING)
        except OSError as exc:
            raise SourceExchangeError(
                f"the captured transfer could not be reopened for upload: {exc}"
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


def _stream_to_staged(store: Any, key: str, staged: Path, *, byte_count: int) -> str:
    """Stream the final object into private staging while hashing it."""
    obstore = _require_obstore()
    hasher = hashlib.sha256()
    total = 0
    try:
        result = obstore.get(store, key)
        with open(staged, "wb") as target:
            for buf in result.stream(min_chunk_size=_IO_CHUNK_BYTES):
                total += len(buf)
                if total > byte_count:
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
    if not output.parent.exists():
        raise SourceExchangeError(f"the output parent directory does not exist: {output.parent}")
    workspace = _temp_workspace()
    staged = workspace / TRANSFER_MEMBER
    try:
        actual = _stream_to_staged(store, final_key, staged, byte_count=byte_count)
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
            existing = hashlib.sha256()
            read = 0
            try:
                with open(output, "rb") as handle:
                    while True:
                        chunk = handle.read(_IO_CHUNK_BYTES)
                        if not chunk:
                            break
                        read += len(chunk)
                        if read > byte_count:
                            existing = None
                            break
                        existing.update(chunk)
            except OSError as exc:
                raise SourceExchangeError(
                    f"the existing output file could not be read: {exc}",
                    code="exchange_conflict",
                ) from exc
            if existing is None or existing.hexdigest() != digest:
                raise SourceExchangeError(
                    "the output file already exists with different bytes; remove it "
                    "or choose another output path",
                    code="exchange_conflict",
                )
        else:
            os.replace(staged, output)
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
