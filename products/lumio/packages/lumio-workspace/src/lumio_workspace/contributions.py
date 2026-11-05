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
from lumio_wiki.git_authoring import GitAuthoringError, resolve_repository
from lumio_wiki.knowledge_base import (
    ControlFileError,
    document_first_control_file,
    load_control_file,
    write_control_file,
)
from lumio_wiki.mutation import atomic_write_bytes
from lumio_wiki.private_profile import (
    PrivateProfileError,
    load_private_profile,
    resolve_private_profile,
)

from .intake import IntakeService, UploadError
from .state import Actor, Operation, WorkspaceState

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


def _page(filename: str, markdown: str) -> tuple[str, dict]:
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
    if not isinstance(entity_types, list) or "knowledge-artifact" not in entity_types:
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
    ) -> None:
        self.state = state
        self.intake = intake
        self.workspace_id = workspace_id
        self.external_url = external_url.rstrip("/")
        self.authoring_path = authoring_path.resolve()
        self.profile_path = profile_path
        self.private_root = intake.private_root

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

    def prepare(
        self,
        actor: Actor,
        *,
        retry_key: str,
        base_revision: str,
        sources: list[dict],
        pages: list[dict],
    ) -> dict:
        if not 1 <= len(retry_key) <= 200 or not retry_key.isprintable():
            raise ContributionError("retry key must be printable and at most 200 characters")
        if not _FULL_COMMIT.fullmatch(base_revision):
            raise ContributionError("base_revision must be a full Git commit", code="invalid_base")
        if not sources or not pages:
            raise ContributionError("at least one source and one page are required")
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
                "base_revision": base_revision,
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
        operation, created = self.state.start_operation(
            self.workspace_id,
            actor,
            "prepare_contribution",
            retry_key,
            input_digest,
        )
        if not created and operation.response:
            return operation.response
        try:
            response = self._prepare_native(
                actor,
                operation,
                base_revision=base_revision,
                sources=checked_sources,
                pages=checked_pages,
                conversion=conversion,
            )
        except (ContributionError, AuthoringJourneyError, AuthoringReviewError, UploadError) as exc:
            code = getattr(exc, "code", "invalid_contribution")
            response = {
                "task_id": operation.operation_id,
                "status": "failed",
                "error": str(exc),
                "code": code,
            }
            self.state.finish_operation(self.workspace_id, actor, operation, "failed", response)
            raise ContributionError(str(exc), code=code) from exc
        self.state.finish_operation(
            self.workspace_id, actor, operation, "pending_review", response
        )
        return response

    def _prepare_native(
        self,
        actor: Actor,
        operation: Operation,
        *,
        base_revision: str,
        sources: list[tuple[Operation, Path, str]],
        pages: list[tuple[str, str, dict]],
        conversion: list[dict],
    ) -> dict:
        del actor  # Native work is bound to the already-persisted actor-scoped operation.
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
            control = document_first_control_file(load_control_file(task_kb))
            control_path = write_control_file(
                self.private_root / "controls" / operation.operation_id,
                control,
            )
            request = CandidateRequest(
                schema_version=1,
                base_revision=base_revision,
                sources=[
                    CandidateSourceRecord(
                        source_id=source.source_id or "",
                        original_path=str(path),
                        expected_digest=source.response["sha256"],
                        intent=intent,
                    )
                    for source, path, intent in sources
                ],
                pages=page_paths,
                control=str(control_path),
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
        }

    def _remove_interrupted_worktree(self, repo_root: Path, task_path: Path, branch: str) -> None:
        _git(repo_root, "worktree", "remove", "--force", str(task_path))
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", branch],
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
