"""Native publication preview and confirmation for reviewed workspace candidates."""

from __future__ import annotations

from pathlib import Path

from lumio_wiki.git_authoring import (
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
