"""Exact-version-bound private provenance records for native Git ingest (F5).

One small private helper with a concrete job today: preserve native
URL/research/capture observation metadata immutably under the explicitly
selected private Source Registry root — outside Git, outside public Compiled
Page content — even when raw artifact retention is disabled.

A Source Version's identity is the hash of the original bytes, not the
identity of every observation taken of them: two different capture manifests
or two different URL retrievals CAN describe the same unchanged bytes. Each
record is therefore bound to the exact ``(source_id, content_hash)`` version
AND content-addressed by the canonical serialization of its own metadata:
``<root>/<kind>/<source_id>/<content_hash>/<metadata-sha256>.json``. An
identical retry converges to the existing record; changed metadata
accumulates a new immutable record instead of overwriting the earlier one.

No event bus, database, queue, or reader is introduced: the records are
private operational provenance for authorized inspection, written once per
observation. Path components reuse the existing safe-path conventions (a
single sanitized path segment per component; no traversal, no absolute
components).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lumio_wiki.mutation import atomic_write_bytes

__all__ = [
    "write_observation_record",
]


def _safe_component(value: str) -> str:
    """One sanitized single path segment (never empty, absolute, or traversing)."""
    cleaned = str(value).strip().replace("\\", "/").split("/")[-1].strip()
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"unsafe provenance path component: {value!r}")
    return cleaned


def _canonical_bytes(payload: dict) -> bytes:
    """The stable record serialization the metadata digest is computed over."""
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def write_observation_record(
    root: str | Path,
    kind: str,
    source_id: str,
    content_hash: str,
    payload: dict,
) -> Path:
    """Write one immutable exact-version-bound observation record (F5).

    ``kind`` selects the private record family (``captures``/``provenance``);
    the record lives at
    ``<root>/<kind>/<source_id>/<content_hash>/<metadata-sha256>.json``.
    Identical retries converge on the existing record; a same-path collision
    with different bytes refuses rather than overwrite. Returns the record
    path.
    """
    kind_dir = _safe_component(kind)
    source_dir = _safe_component(source_id)
    version_dir = _safe_component(content_hash)
    record_bytes = _canonical_bytes(payload)
    metadata_digest = hashlib.sha256(record_bytes).hexdigest()
    directory = Path(root) / kind_dir / source_dir / version_dir
    directory.mkdir(parents=True, exist_ok=True)
    record_path = directory / f"{metadata_digest}.json"
    if record_path.exists():
        if record_path.read_bytes() == record_bytes:
            return record_path  # identical retry converges; nothing to write
        raise RuntimeError(
            "private provenance record collision under "
            f"{record_path}: refusing to overwrite an earlier record"
        )
    atomic_write_bytes(record_path, record_bytes)
    return record_path
