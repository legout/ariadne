"""Bounded selection for agent-authored, human-reviewed semantic enrichment."""

from __future__ import annotations

from pathlib import Path

from lumio_wiki.artifact_store import ArtifactAccessDenied, ArtifactStoreError
from lumio_wiki.git_authoring import CapturedRevision, GitAuthoringError, capture_revision
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.source_registry import SourceRegistry, SourceRegistryError

from .contributions import _FULL_COMMIT, ContributionError, ContributionService, _digest
from .state import Actor

LIMITS = {"pages": 20, "characters": 200_000, "proposed_claims": 40}


def source_refresh_impact(
    task: dict, admitted: CapturedRevision, registry: SourceRegistry
) -> list[dict]:
    """Project exact source changes onto admitted pages without inferring Claim lineage."""
    updated_versions: dict[str, str] = {}
    for item in task.get("conversion", []):
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        content_hash = item.get("sha256")
        if isinstance(source_id, str) and isinstance(content_hash, str):
            updated_versions[source_id] = content_hash
    source_ids = {
        source_id for bindings in admitted.manifest.bindings.values() for source_id in bindings
    }
    latest: dict[str, str] = {}
    for source_id in sorted(source_ids):
        if source_id in updated_versions:
            latest[source_id] = updated_versions[source_id]
            continue
        source = registry.get(source_id)
        if source.versions:
            latest[source_id] = source.versions[-1].content_hash

    impact = []
    for page in admitted.kb.pages:
        if page.visibility not in {"public", "internal"}:
            continue
        for source_id, bound_hash in admitted.manifest.bindings.get(page.id, {}).items():
            latest_hash = latest.get(source_id)
            if latest_hash is None or latest_hash == bound_hash:
                continue
            impact.append(
                {
                    "source_id": source_id,
                    "bound_hash": bound_hash,
                    "latest_hash": latest_hash,
                    "page_id": page.id,
                    "page_title": page.title,
                    "claims": [
                        {
                            "id": claim.id,
                            "evidence": [
                                {
                                    "section": anchor.section,
                                    "line_start": anchor.line_start,
                                    "line_end": anchor.line_end,
                                }
                                for anchor in claim.evidence
                            ],
                        }
                        for claim in page.claims
                    ],
                }
            )
    return impact


class EnrichmentService:
    def __init__(self, contributions: ContributionService, *, destination: Path) -> None:
        self.contributions = contributions
        self.destination = destination

    def prepare(
        self,
        actor: Actor,
        *,
        workspace_id: str,
        page_ids: list[str],
        expected_version: str,
        request_key: str,
    ) -> dict:
        """Select exact admitted input; authoring and admission remain separate operations."""
        if workspace_id != self.contributions.workspace_id:
            raise ContributionError(
                "the requested workspace is not this service's configured workspace",
                code="workspace_mismatch",
            )
        if not 1 <= len(request_key) <= 200 or not request_key.isprintable():
            raise ContributionError("request key must be printable and at most 200 characters")
        if not _FULL_COMMIT.fullmatch(expected_version):
            raise ContributionError(
                "expected_version must be a full admitted Git commit", code="invalid_base"
            )
        if not 1 <= len(page_ids) <= LIMITS["pages"] or len(set(page_ids)) != len(page_ids):
            raise ContributionError(
                "select 1 to 20 distinct pages; narrow or split the enrichment batch",
                code="batch_too_large",
            )
        input_digest = _digest(
            {
                "kind": "enrichment",
                "workspace_id": workspace_id,
                "page_ids": page_ids,
                "expected_version": expected_version,
            }
        )
        operation, _created = self.contributions.state.start_operation(
            workspace_id,
            actor,
            "prepare_contribution",
            request_key,
            input_digest,
        )
        if operation.status != "pending":
            return operation.response
        with self.contributions.state.operation_lock(operation) as acquired:
            if not acquired:
                return {
                    **operation.response,
                    "task_id": operation.operation_id,
                    "status": "pending",
                    "published": False,
                }
            current = self.contributions.state.get_operation(
                workspace_id, actor, "prepare_contribution", operation.operation_id
            )
            if current is None:
                raise ContributionError("task is not available", code="task_not_found")
            if current.status != "pending":
                return current.response
            try:
                persisted, disclosed = self._select(
                    page_ids, expected_version, current.operation_id
                )
            except (GitAuthoringError, SourceRegistryError, ArtifactStoreError, OSError) as exc:
                raise ContributionError(
                    f"the exact enrichment selection is unavailable: {exc}",
                    code="selection_unavailable",
                ) from exc
            self.contributions.state.finish_operation(
                workspace_id, actor, current, "pending", persisted
            )
            return disclosed

    def _select(
        self, page_ids: list[str], expected_version: str, task_id: str
    ) -> tuple[dict, dict]:
        self.contributions._require_attachment()
        current = PublishedFilesystemLocation(self.destination).read_pointer()
        if current != expected_version:
            raise ContributionError(
                "expected_version is not the currently admitted version; select the current "
                "version and request a fresh review",
                code="stale_enrichment_base",
            )
        captured = capture_revision(self.contributions.authoring_path, expected_version)
        if not captured.report.is_valid:
            raise ContributionError(
                "the admitted enrichment base is not valid", code="invalid_base"
            )
        resources = self.contributions._resources()
        if resources.source_registry is None or resources.artifact_store is None:
            raise ContributionError(
                "native registry and artifact retention are required", code="invalid_profile"
            )
        by_id = {page.id: page for page in captured.kb.pages}
        missing = [page_id for page_id in page_ids if page_id not in by_id]
        if missing:
            raise ContributionError(
                "every selected Entity ID must name an admitted page; narrow the selection",
                code="page_not_admitted",
            )
        selected = [by_id[page_id] for page_id in page_ids]
        if any(page.visibility != "internal" for page in selected):
            raise ContributionError(
                "enrichment requires workspace-wide internal source visibility",
                code="incompatible_audience",
            )

        control = (captured.source.control_file_bytes() or b"").decode("utf-8")
        pages = []
        selected_characters = len(control)
        sources = []
        for page in selected:
            markdown = captured.source.read_bytes(page.path).decode("utf-8")
            selected_characters += len(markdown)
            pages.append(
                {
                    "id": page.id,
                    "title": page.title,
                    "path": page.path,
                    "published_version": expected_version,
                    "characters": len(markdown),
                    "markdown": markdown,
                }
            )
            for source in page.sources:
                digest = captured.manifest.bindings.get(page.id, {}).get(source.id)
                version = (
                    resources.source_registry.find_version(source.id, digest)
                    if digest is not None
                    else None
                )
                try:
                    available = (
                        resources.artifact_store.artifact_exists(
                            source_id=source.id, content_hash=digest
                        )
                        if digest is not None
                        else None
                    )
                except ArtifactAccessDenied as exc:
                    raise ContributionError(
                        "access to a selected original was denied", code="source_access_failed"
                    ) from exc
                sources.append(
                    {
                        "entity_id": page.id,
                        "source_id": source.id,
                        "attribution": source.title,
                        "content_hash": digest,
                        "created_at": version.created_at if version else None,
                        "filename": version.filename if version else None,
                        "registered": version is not None,
                        "original_available": available,
                        "published_version": expected_version,
                    }
                )
        if selected_characters > LIMITS["characters"]:
            raise ContributionError(
                f"the disclosed selection has {selected_characters} characters, above the "
                "200,000-character bound; narrow or split the batch instead of truncating it",
                code="batch_too_large",
            )

        persisted = {
            "task_id": task_id,
            "status": "pending",
            "kind": "enrichment",
            "native_base": expected_version,
            "selected_page_ids": page_ids,
            "selected_characters": selected_characters,
            "selected_sources": sources,
            "limits": LIMITS,
            "external_lookup": {"enabled": False},
            "published": False,
        }
        identities = [
            {
                "id": page.id,
                "title": page.title,
                "aliases": page.aliases,
                "entity_types": page.entity_types,
                "path": page.path,
            }
            for page in selected
        ]
        disclosed = {
            **persisted,
            "pages": pages,
            "identities": identities,
            "control": control,
            "sources": sources,
            "disclosure": (
                "Only these exact admitted pages and controls are disclosed. No original "
                "passages were added. Anchor checks verify coordinates, not semantic truth."
            ),
        }
        return persisted, disclosed


__all__ = ["EnrichmentService", "LIMITS", "source_refresh_impact"]
