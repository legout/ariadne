"""Native publication preview and confirmation for reviewed workspace candidates."""

from __future__ import annotations

from pathlib import Path

import msgspec
from lumio_wiki.git_authoring import (
    PRIVATE_OPERATIONS_DIR,
    GitAuthoringError,
    PublicationReceipt,
    PublicationReview,
    preview_publication,
    publish_revision,
)
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.private_profile import (
    ResolvedPrivateSources,
    load_private_profile,
    resolve_private_profile,
)


class PublicationService:
    def __init__(self, *, authoring_path: Path, profile_path: Path, destination: Path) -> None:
        self.authoring_path = authoring_path
        self.profile_path = profile_path
        self.destination = destination

    def resources(self) -> ResolvedPrivateSources:
        profile = load_private_profile(self.profile_path, kb_root=self.authoring_path)
        return resolve_private_profile(
            profile,
            kb_root=self.authoring_path,
            needs=frozenset({"registry", "artifacts"}),
        )

    def current_version(self) -> str | None:
        return PublishedFilesystemLocation(self.destination).read_pointer()

    def preview(
        self,
        task_kb: Path,
        revision: str,
        expected_current: str,
        resources: ResolvedPrivateSources,
    ) -> PublicationReview:
        return preview_publication(
            task_kb,
            revision,
            self.destination,
            expected_current,
            source_registry=resources.source_registry,
            artifact_store=resources.artifact_store,
            retention_required=resources.retention_required,
        )

    def publish(
        self,
        task_kb: Path,
        review: PublicationReview,
        resources: ResolvedPrivateSources,
    ) -> PublicationReceipt:
        return publish_revision(
            task_kb,
            review.revision,
            self.destination,
            review.expected_current,
            review.review_digest,
            source_registry=resources.source_registry,
            artifact_store=resources.artifact_store,
            retention_required=resources.retention_required,
        )

    def overall_preview(
        self,
        project: Path,
        proposal: str,
        revision: str,
        reviewed_digest: str,
        *,
        expected_current: str,
    ) -> dict:
        from ariadne import admission

        return admission.overall_review(
            project,
            proposal,
            revision,
            reviewed_digest,
            destination=self.destination,
            expected_current=expected_current,
            private_profile=self.profile_path,
            scope=("internal",),
        )

    def publish_overall(
        self,
        project: Path,
        proposal: str,
        revision: str,
        reviewed_digest: str,
        overall_preview: dict,
        *,
        confirmed_by: str,
    ) -> dict:
        from ariadne import admission

        return admission.admit_revision(
            project,
            proposal,
            revision,
            reviewed_digest,
            confirmed_by=confirmed_by,
            overall_preview=overall_preview,
            confirmed_overall_digest=overall_preview["digest"],
            private_profile=self.profile_path,
        )

    def recover(
        self,
        task_kb: Path,
        revision: str,
        expected_current: str,
        review_digest: str,
        resources: ResolvedPrivateSources,
    ) -> PublicationReceipt | None:
        receipt_path = (
            self.destination.resolve() / PRIVATE_OPERATIONS_DIR / "receipts" / f"{revision}.json"
        )
        try:
            raw = receipt_path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            receipt = msgspec.json.decode(raw, type=PublicationReceipt)
        except (OSError, msgspec.DecodeError) as exc:
            raise GitAuthoringError(f"native admission receipt is unreadable: {exc}") from exc
        if (
            receipt.version != revision
            or receipt.revision != revision
            or receipt.review_digest != review_digest
            or receipt.expected_current != expected_current
        ):
            raise GitAuthoringError(
                "native admission receipt does not match the persisted browser approval"
            )
        # A prepared receipt alone is not activation. Only verify through the
        # native retry when its activation is recorded or its pointer is visible.
        if not receipt.activated and self.current_version() != revision:
            return receipt
        return publish_revision(
            task_kb,
            revision,
            self.destination,
            expected_current,
            review_digest,
            source_registry=resources.source_registry,
            artifact_store=resources.artifact_store,
            retention_required=resources.retention_required,
        )
