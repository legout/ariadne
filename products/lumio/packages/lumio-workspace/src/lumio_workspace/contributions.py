"""Native, isolated candidate preparation without publication authority."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import msgspec
from lumio_wiki.authoring_journey import (
    AuthoringJourneyError,
    CandidateRequest,
    CandidateSourceRecord,
    ingest_candidate,
)
from lumio_wiki.authoring_review import (
    AuthoringReviewError,
    check_authoring_commit,
    review_authoring_candidate,
)
from lumio_wiki.git_authoring import GitAuthoringError, capture_revision, resolve_repository
from lumio_wiki.knowledge_base import (
    ControlFileError,
    document_first_control_file,
    load_control_file,
    write_control_file,
)
from lumio_wiki.mutation import atomic_write_bytes, mutation_lock
from lumio_wiki.private_profile import (
    PrivateProfileError,
    load_private_profile,
    resolve_private_profile,
)
from lumio_wiki.source_inspection import (
    SourceInspectionError,
    fetch_verified_artifact,
    resolve_source_reference_binding,
)

from .intake import IntakeService, UploadError
from .setup import SetupError, current_attachment_digest
from .state import Actor, Operation, RetryConflict, WorkspaceState

_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ContributionError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_contribution") -> None:
        super().__init__(message)
        self.code = code


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise ContributionError(
            "native Git could not be executed", code="native_git_failed"
        ) from exc
    if result.returncode != 0:
        raise ContributionError("native Git operation failed", code="native_git_failed")
    return result.stdout.decode().strip()


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _page(
    filename: str, markdown: str, *, require_artifact: bool = True
) -> tuple[str, dict]:
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or not filename.isprintable()
        or len(filename) > 160
    ):
        raise ContributionError("page filename must be a safe basename", code="unsafe_path")
    if not filename.lower().endswith((".md", ".markdown")):
        raise ContributionError("candidate pages must be Markdown", code="invalid_page")
    try:
        marker = markdown.index("\n---", 4)
        frontmatter = msgspec.yaml.decode(markdown[4:marker])
    except (ValueError, msgspec.DecodeError) as exc:
        raise ContributionError(
            "candidate page has invalid frontmatter", code="invalid_page"
        ) from exc
    if not isinstance(frontmatter, dict):
        raise ContributionError("candidate page has invalid frontmatter", code="invalid_page")
    if frontmatter.get("visibility") != "internal":
        raise ContributionError(
            "workspace-wide contributions require visibility: internal",
            code="incompatible_audience",
        )
    entity_types = frontmatter.get("entity_types")
    if require_artifact and (
        not isinstance(entity_types, list) or "knowledge-artifact" not in entity_types
    ):
        raise ContributionError(
            "candidate page requires the knowledge-artifact Entity Type",
            code="invalid_page",
        )
    return markdown, frontmatter


class ContributionService:
    def __init__(
        self,
        state: WorkspaceState,
        intake: IntakeService,
        *,
        workspace_id: str,
        external_url: str,
        authoring_path: Path,
        profile_path: Path,
        destination: Path | None = None,
    ) -> None:
        self.state = state
        self.intake = intake
        self.workspace_id = workspace_id
        self.external_url = external_url.rstrip("/")
        self.authoring_path = authoring_path.resolve()
        self.profile_path = profile_path
        self.private_root = intake.private_root
        self.destination = destination

    def _resources(self):
        try:
            profile = load_private_profile(self.profile_path, kb_root=self.authoring_path)
            return resolve_private_profile(
                profile,
                kb_root=self.authoring_path,
                needs=frozenset({"registry", "artifacts"}),
            )
        except PrivateProfileError as exc:
            raise ContributionError(
                "native private profile is unavailable", code="invalid_profile"
            ) from exc

    def _require_attachment(self) -> None:
        try:
            digest = current_attachment_digest(
                target=self.authoring_path,
                profile_path=self.profile_path,
            )
        except SetupError as exc:
            raise ContributionError(str(exc), code=exc.code) from exc
        if not self.state.has_setup_attachment(self.workspace_id, digest):
            raise ContributionError(
                "an owner must confirm setup for the current authoring target and private binding",
                code="setup_required",
            )

    def _managed_base(
        self,
        actor: Actor,
        base_revision: str | None,
        continuation_task_id: str | None,
    ) -> str:
        if continuation_task_id is not None:
            continued = self.state.get_operation(
                self.workspace_id,
                actor,
                "prepare_contribution",
                continuation_task_id,
            )
            if continued is None or continued.status != "pending_review":
                raise ContributionError(
                    "continuation must name this actor's pending candidate",
                    code="invalid_continuation",
                )
            managed = continued.response.get("native_candidate", "")
        else:
            repo_root, _subtree = resolve_repository(self.authoring_path)
            managed = _git(repo_root, "rev-parse", "HEAD")
        if not _FULL_COMMIT.fullmatch(managed):
            raise ContributionError(
                "the managed authoring base is unavailable", code="invalid_base"
            )
        if base_revision is not None and base_revision != managed:
            raise ContributionError(
                "base_revision does not match the server-selected authoring base",
                code="invalid_base",
            )
        return managed

    def prepare(
        self,
        actor: Actor,
        *,
        retry_key: str,
        sources: list[dict],
        pages: list[dict],
        base_revision: str | None = None,
        continuation_task_id: str | None = None,
    ) -> dict:
        if not 1 <= len(retry_key) <= 200 or not retry_key.isprintable():
            raise ContributionError("retry key must be printable and at most 200 characters")
        if base_revision is not None and not _FULL_COMMIT.fullmatch(base_revision):
            raise ContributionError("base_revision must be a full Git commit", code="invalid_base")
        if not sources or not pages:
            raise ContributionError("at least one source and one page are required")
        self._require_attachment()
        checked_pages = []
        for item in pages:
            try:
                filename = item["filename"]
                markdown = item["markdown"]
            except (KeyError, TypeError) as exc:
                raise ContributionError("each page requires filename and markdown") from exc
            if not isinstance(filename, str) or not isinstance(markdown, str):
                raise ContributionError("page filename and markdown must be strings")
            checked_pages.append((filename, *_page(filename, markdown)))
        checked_sources = []
        conversion = []
        for item in sources:
            upload_id = item.get("upload_id") if isinstance(item, dict) else None
            intent = item.get("intent") if isinstance(item, dict) else None
            if not isinstance(upload_id, str) or intent not in {"new", "update"}:
                raise ContributionError("each source requires upload_id and new/update intent")
            operation, path = self.intake.load(self.workspace_id, actor, upload_id)
            if operation.source_id is None:
                raise ContributionError("uploaded source identity is unavailable")
            _material, facts = self.intake.extract(self.workspace_id, actor, upload_id)
            conversion.append(facts)
            checked_sources.append((operation, path, intent))
        input_digest = _digest(
            {
                "requested_base": base_revision,
                "continuation_task_id": continuation_task_id,
                "sources": [
                    {
                        "source_id": operation.source_id,
                        "sha256": operation.response["sha256"],
                        "intent": intent,
                    }
                    for operation, _path, intent in checked_sources
                ],
                "pages": [
                    {"filename": filename, "sha256": hashlib.sha256(markdown.encode()).hexdigest()}
                    for filename, markdown, _frontmatter in checked_pages
                ],
            }
        )
        operation, _created = self.state.start_operation(
            self.workspace_id,
            actor,
            "prepare_contribution",
            retry_key,
            input_digest,
        )
        if operation.status != "pending":
            return operation.response
        with self.state.operation_lock(operation) as acquired:
            if not acquired:
                return {
                    **operation.response,
                    "task_id": operation.operation_id,
                    "status": "pending",
                    "published": False,
                }
            current = self.state.get_operation(
                self.workspace_id,
                actor,
                "prepare_contribution",
                operation.operation_id,
            )
            if current is None:
                raise ContributionError("task is not available", code="task_not_found")
            if current.status != "pending":
                return current.response
            try:
                managed_base = current.response.get("native_base")
                if managed_base is None:
                    managed_base = self._managed_base(
                        actor,
                        base_revision,
                        continuation_task_id,
                    )
                    self.state.finish_operation(
                        self.workspace_id,
                        actor,
                        current,
                        "pending",
                        {
                            "task_id": current.operation_id,
                            "status": "pending",
                            "native_base": managed_base,
                            "published": False,
                        },
                    )
                elif base_revision is not None and managed_base != base_revision:
                    raise ContributionError(
                        "base_revision does not match the persisted authoring base",
                        code="invalid_base",
                    )
                response = self._prepare_native(
                    actor,
                    current,
                    base_revision=managed_base,
                    sources=[
                        CandidateSourceRecord(
                            source_id=source.source_id or "",
                            original_path=str(path),
                            expected_digest=source.response["sha256"],
                            intent=intent,
                        )
                        for source, path, intent in checked_sources
                    ],
                    pages=checked_pages,
                    conversion=conversion,
                )
            except (
                ContributionError,
                AuthoringJourneyError,
                AuthoringReviewError,
                GitAuthoringError,
                UploadError,
            ) as exc:
                code = getattr(exc, "code", "invalid_contribution")
                response = {
                    "task_id": current.operation_id,
                    "status": "failed",
                    "error": str(exc),
                    "code": code,
                }
                self.state.finish_operation(self.workspace_id, actor, current, "failed", response)
                raise ContributionError(str(exc), code=code) from exc
            self.state.finish_operation(
                self.workspace_id, actor, current, "pending_review", response
            )
            return response

    def prepare_enrichment(
        self,
        actor: Actor,
        *,
        task_id: str,
        retry_key: str,
        pages: list[dict],
        control: str | None = None,
    ) -> dict:
        """Author or correct a complete candidate for one persisted bounded selection."""
        if not 1 <= len(retry_key) <= 200 or not retry_key.isprintable():
            raise ContributionError("retry key must be printable and at most 200 characters")
        if control is not None and len(control) > 200_000:
            raise ContributionError(
                "the candidate Control File exceeds the disclosed input bound",
                code="batch_too_large",
            )
        if not pages:
            raise ContributionError("a complete enrichment candidate requires at least one page")
        checked_pages = []
        for item in pages:
            try:
                filename = item["filename"]
                markdown = item["markdown"]
            except (KeyError, TypeError) as exc:
                raise ContributionError("each page requires filename and markdown") from exc
            if not isinstance(filename, str) or not isinstance(markdown, str):
                raise ContributionError("page filename and markdown must be strings")
            checked_pages.append(
                (filename, *_page(filename, markdown, require_artifact=False))
            )
        input_digest = _digest(
            {
                "enrichment_task_id": task_id,
                "pages": [
                    {
                        "filename": filename,
                        "sha256": hashlib.sha256(markdown.encode()).hexdigest(),
                    }
                    for filename, markdown, _frontmatter in checked_pages
                ],
                "control": control,
            }
        )
        operation = self.state.get_operation(
            self.workspace_id, actor, "prepare_contribution", task_id
        )
        if operation is None or operation.response.get("kind") != "enrichment":
            raise ContributionError(
                "enrichment task is not available", code="invalid_enrichment_task"
            )

        lock_resources: list[str | Path] = [self.private_root / "activation"]
        if self.destination is not None:
            lock_resources.append(self.destination)
        native_resources = self._resources()
        for adapter in (native_resources.source_registry, native_resources.artifact_store):
            root = getattr(adapter, "root", None)
            if root is not None:
                lock_resources.append(root)
        with (
            self.state.operation_lock(operation) as acquired,
            mutation_lock(*lock_resources),
        ):
            if not acquired:
                current = self.state.get_operation(
                    self.workspace_id, actor, "prepare_contribution", task_id
                )
                if current is None:
                    raise ContributionError("task is not available", code="task_not_found")
                _drafts, _generation, binding = self._validate_draft_binding(
                    current.response, retry_key, input_digest
                )
                if binding is None:
                    return {
                        "task_id": task_id,
                        "status": "not_prepared",
                        "prepared": False,
                        "published": False,
                    }
                return current.response
            current = self.state.get_operation(
                self.workspace_id, actor, "prepare_contribution", task_id
            )
            if current is None:
                raise ContributionError("task is not available", code="task_not_found")
            self._reconcile_enrichment(current)
            current = self.state.get_operation(
                self.workspace_id, actor, "prepare_contribution", task_id
            )
            if current is None:
                raise ContributionError("task is not available", code="task_not_found")

            drafts, generation, binding = self._validate_draft_binding(
                current.response, retry_key, input_digest
            )
            if binding is not None and current.status in {
                "pending_review",
                "rejected",
                "published",
            }:
                return current.response
            elif current.status not in {"pending", "pending_review", "rejected", "failed"}:
                raise ContributionError(
                    "a published enrichment cannot be replaced", code="invalid_enrichment_task"
                )
            if current.status not in {"pending", "pending_review", "rejected", "failed"}:
                raise ContributionError(
                    "a published enrichment cannot be replaced", code="invalid_enrichment_task"
                )
            if binding is None:
                generation += 1
            working = {
                **current.response,
                "task_id": task_id,
                "status": "pending",
                "draft_generation": generation,
                "drafts": {
                    **drafts,
                    retry_key: {"input_digest": input_digest, "generation": generation},
                },
                "published": False,
            }
            for stale_key in (
                "error",
                "code",
                "publication",
                "publication_outcome",
                "review_decision",
            ):
                working.pop(stale_key, None)
            self.state.finish_operation(self.workspace_id, actor, current, "pending", working)
            try:
                base = capture_revision(self.authoring_path, current.response["native_base"])
                base_ids = {page.id for page in base.kb.pages}
                selected_ids = set(current.response["selected_page_ids"])
                selected_sources = {
                    item["source_id"] for item in current.response["selected_sources"]
                }
                for _filename, _markdown, frontmatter in checked_pages:
                    entity_id = frontmatter.get("id")
                    if not isinstance(entity_id, str) or not entity_id:
                        raise ContributionError(
                            "each enrichment page requires a stable Entity ID",
                            code="invalid_page",
                        )
                    if entity_id in base_ids and entity_id not in selected_ids:
                        raise ContributionError(
                            "an existing page outside the authorized selection cannot be edited",
                            code="page_not_selected",
                        )
                    declared = frontmatter.get("sources", [])
                    if not isinstance(declared, list) or any(
                        not isinstance(source, dict) or source.get("id") not in selected_sources
                        for source in declared
                    ):
                        raise ContributionError(
                            "enrichment pages may declare only exact sources from the selection",
                            code="source_not_selected",
                        )
                sources = self._enrichment_sources(current, checked_pages)
                native = self._prepare_native(
                    actor,
                    current,
                    base_revision=current.response["native_base"],
                    sources=sources,
                    pages=checked_pages,
                    conversion=[],
                    control_markdown=control,
                    enrichment=True,
                )
                response = {**working, **native}
            except (
                ContributionError,
                AuthoringJourneyError,
                AuthoringReviewError,
                GitAuthoringError,
                SourceInspectionError,
            ) as exc:
                code = getattr(exc, "code", "invalid_contribution")
                response = {
                    **working,
                    "status": "failed",
                    "error": str(exc),
                    "code": code,
                }
                self.state.finish_operation(self.workspace_id, actor, current, "failed", response)
                raise ContributionError(str(exc), code=code) from exc
            self.state.finish_operation(
                self.workspace_id, actor, current, "pending_review", response
            )
            return response

    @staticmethod
    def _validate_draft_binding(
        response: dict, retry_key: str, input_digest: str
    ) -> tuple[dict, int, dict | None]:
        """Validate retry identity against the latest serialized draft generation."""
        drafts = response.get("drafts", {})
        generation = response.get("draft_generation", 0)
        binding = drafts.get(retry_key)
        if binding is not None:
            if binding["input_digest"] != input_digest:
                raise RetryConflict("retry key is already bound to different enrichment input")
            if binding["generation"] != generation:
                raise ContributionError(
                    "this draft was superseded; retry the latest draft or author a new correction",
                    code="obsolete_draft",
                )
        return drafts, generation, binding

    def _reconcile_enrichment(self, operation: Operation) -> None:
        """Recover a prior native approval before any candidate/worktree replacement."""
        if operation.status != "pending_review" or not operation.response.get("native_candidate"):
            return
        if self.destination is None:
            raise ContributionError(
                "enrichment recovery requires the configured publication destination",
                code="recovery_unavailable",
            )
        from .review import ReviewService

        recovery = ReviewService(
            self.state,
            workspace_id=self.workspace_id,
            authoring_path=self.authoring_path,
            profile_path=self.profile_path,
            private_root=self.private_root,
            destination=self.destination,
        ).reconcile_task(operation.operation_id)
        if recovery is not None and recovery.get("publication_outcome") == "indeterminate":
            raise ContributionError(
                "the prior native publication outcome is indeterminate; recover it before "
                "correction",
                code="recovery_required",
            )

    def _enrichment_sources(
        self, operation: Operation, pages: list[tuple[str, str, dict]]
    ) -> list[CandidateSourceRecord]:
        """Materialize only exact selected originals needed for new Entity bindings."""
        resources = self._resources()
        if resources.source_registry is None or resources.artifact_store is None:
            raise ContributionError(
                "native registry and artifact retention are required", code="invalid_profile"
            )
        captured = capture_revision(self.authoring_path, operation.response["native_base"])
        selected = operation.response["selected_sources"]
        records = []
        seen = set()
        for _filename, _markdown, frontmatter in pages:
            entity_id = frontmatter["id"]
            for source in frontmatter.get("sources", []):
                source_id = source["id"]
                if source_id in captured.manifest.bindings.get(entity_id, {}):
                    continue
                matches = [
                    item
                    for item in selected
                    if item["source_id"] == source_id and item["content_hash"] is not None
                ]
                digests = {item["content_hash"] for item in matches}
                if len(digests) != 1:
                    raise ContributionError(
                        "a new source binding needs exactly one selected Source Version; "
                        "narrow the selection",
                        code="ambiguous_source_version",
                    )
                item = matches[0]
                key = (source_id, item["content_hash"])
                if key in seen:
                    continue
                seen.add(key)
                if item["original_available"] is not True:
                    raise ContributionError(
                        "a new source binding requires the exact retained original",
                        code="source_unavailable",
                    )
                binding = resolve_source_reference_binding(
                    resources.source_registry,
                    captured.manifest,
                    source_id,
                    entity_id=item["entity_id"],
                    published_version=operation.response["native_base"],
                )
                raw = fetch_verified_artifact(resources.artifact_store, binding)
                path = (
                    self.private_root
                    / "originals"
                    / operation.operation_id
                    / f"selected-{len(records)}"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(path, raw)
                records.append(
                    CandidateSourceRecord(
                        source_id=source_id,
                        original_path=str(path),
                        expected_digest=item["content_hash"],
                        intent="update",
                    )
                )
        return records

    def _prepare_native(
        self,
        actor: Actor,
        operation: Operation,
        *,
        base_revision: str,
        sources: list[CandidateSourceRecord],
        pages: list[tuple[str, str, dict]],
        conversion: list[dict],
        control_markdown: str | None = None,
        enrichment: bool = False,
    ) -> dict:
        del actor  # Native work is bound to the already-persisted actor-scoped operation.
        self._require_attachment()
        resources = self._resources()
        if resources.source_registry is None or resources.artifact_store is None:
            raise ContributionError(
                "native registry and artifact retention are required",
                code="invalid_profile",
            )
        repo_root, subtree = resolve_repository(self.authoring_path)
        task_path = self.private_root / "worktrees" / operation.operation_id
        branch = f"lumio-workspace/{operation.operation_id}"
        if task_path.exists():
            self._remove_interrupted_worktree(repo_root, task_path, branch)
        task_path.parent.mkdir(parents=True, exist_ok=True)
        _git(repo_root, "worktree", "add", "-b", branch, str(task_path), base_revision)
        task_kb = task_path / subtree
        authored = self.private_root / "authored" / operation.operation_id
        page_paths = []
        for filename, markdown, _frontmatter in pages:
            path = authored / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(path, markdown.encode())
            page_paths.append(str(path))
        try:
            control_path = None
            if control_markdown is not None:
                control_path = (
                    self.private_root / "controls" / operation.operation_id / "lumio.yaml"
                )
                control_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(control_path, control_markdown.encode())
            elif not enrichment:
                control = document_first_control_file(load_control_file(task_kb))
                control_path = write_control_file(
                    self.private_root / "controls" / operation.operation_id,
                    control,
                )
            request = CandidateRequest(
                schema_version=1,
                base_revision=base_revision,
                sources=sources,
                pages=page_paths,
                control=str(control_path) if control_path is not None else None,
            )
            result = ingest_candidate(
                task_kb,
                request,
                source_registry=resources.source_registry,
                artifact_store=resources.artifact_store,
            )
            _git(task_kb, "add", "--", ".")
            review = review_authoring_candidate(
                task_kb,
                base_revision,
                source_registry=resources.source_registry,
            )
            proposed_claims = sum(
                1
                for page in review.knowledge.pages
                for claim in page.claims
                if claim.change in {"added", "edited", "status"}
            )
            if enrichment and proposed_claims > 40:
                raise ContributionError(
                    "the candidate proposes more than 40 Claims; narrow or split the batch",
                    code="batch_too_large",
                )
            _git(
                task_kb,
                "-c",
                "user.name=Lumio Workspace",
                "-c",
                "user.email=lumio-workspace@localhost",
                "commit",
                "-qm",
                f"Prepare workspace contribution {operation.operation_id}",
            )
            candidate = _git(task_kb, "rev-parse", "HEAD")
            checked = check_authoring_commit(task_kb, review, candidate)
            if not checked.matches_reviewed_candidate:
                raise ContributionError(
                    "committed candidate differs from its native review",
                    code="candidate_mismatch",
                )
        except (ControlFileError, GitAuthoringError) as exc:
            raise ContributionError(str(exc), code="invalid_candidate") from exc
        return {
            "task_id": operation.operation_id,
            "status": "pending_review",
            "native_base": base_revision,
            "native_candidate": candidate,
            "native_review": review.review_digest,
            "review_url": f"{self.external_url}/review/{operation.operation_id}",
            "candidate": msgspec.to_builtins(result),
            "conversion": conversion,
            "published": False,
            **({"proposed_claims": proposed_claims} if enrichment else {}),
        }

    def _remove_interrupted_worktree(self, repo_root: Path, task_path: Path, branch: str) -> None:
        _git(repo_root, "worktree", "remove", "--force", str(task_path))
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                ],
                check=False,
                capture_output=True,
            )
        except OSError as exc:
            raise ContributionError(
                "native Git could not inspect the interrupted branch",
                code="native_git_failed",
            ) from exc
        if result.returncode == 0:
            _git(repo_root, "branch", "-D", branch)
        elif result.returncode != 1:
            raise ContributionError(
                "native Git could not inspect the interrupted branch",
                code="native_git_failed",
            )

    def get(self, actor: Actor, task_id: str) -> dict:
        operation = self.state.get_operation(
            self.workspace_id, actor, "prepare_contribution", task_id
        )
        if operation is None:
            raise ContributionError("task is not available", code="task_not_found")
        return {
            "task_id": task_id,
            "status": operation.status,
            **operation.response,
        }
