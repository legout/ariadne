"""Legacy snapshot fixtures; production publication requires a captured Git revision."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lumio_wiki import s3_publish as pub
from lumio_wiki.knowledge_base import (
    KnowledgeBaseError,
    _capture_source,
    _FilesystemKbSource,
    _load_and_validate,
    canonical_content,
)

if TYPE_CHECKING:
    from lumio_wiki.s3_location import S3Manifest
    from lumio_wiki.s3_publish import ActivationHook, IndexBuilder
    from obstore.store import ObjectStore


def publish_legacy_s3_version(
    store: ObjectStore,
    prefix: str,
    *,
    source_root: str | Path,
    version: str,
    expected_pointer_version: str | None = None,
    index_builder: IndexBuilder | None = None,
    before_activation: ActivationHook | None = None,
) -> S3Manifest:
    """Build legacy fixtures through the shared integrity and CAS publication kernel."""
    obstore = pub._require_obstore()
    clean_prefix = str(prefix).strip("/")
    root = Path(source_root)
    observed = pub.observe_current_pointer(store, clean_prefix)
    pub._check_expectation(observed, expected_pointer_version, version)
    if pub._list_keys(obstore, store, pub._join(clean_prefix, version, "")):
        raise KnowledgeBaseError(
            f"cannot publish {version!r}: version prefix already exists at "
            f"{pub._join(clean_prefix, version, '')!r} — immutable versions cannot be "
            "overwritten; an interrupted build's residue is reported by "
            "list_cleanup_candidates()"
        )

    source, fingerprint = _capture_source(_FilesystemKbSource(root.resolve()))
    kb, report = _load_and_validate(source, fingerprint=fingerprint)
    if not report.is_valid:
        blocking = sum(1 for issue in report.issues if issue.severity == "error")
        raise KnowledgeBaseError(
            f"cannot publish {version!r}: canonical Knowledge Base content at "
            f"{root!s} has {blocking} blocking validation error(s)"
        )
    return pub._publish_s3_candidate(
        obstore,
        store,
        clean_prefix,
        version=version,
        observed=observed,
        expected_pointer_version=expected_pointer_version,
        kb=kb,
        report=report,
        content=canonical_content(source),
        fingerprint=fingerprint,
        index_builder=index_builder,
        before_activation=before_activation,
    )
