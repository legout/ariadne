"""Lazy Ariadne analytics for an explicitly enabled shared workspace."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import msgspec
from ariadne import admission, authoring_sources, proposals
from ariadne.authoring import AuthoringProject
from ariadne.contribution_review import check_contribution_commit, review_contribution
from ariadne.query import QueryRuntime
from lumio_wiki.authoring_journey import (
    CandidateRequest,
    CandidateSourceRecord,
    ingest_candidate,
)
from lumio_wiki.git_authoring import resolve_repository
from lumio_wiki.knowledge_base import (
    document_first_control_file,
    load_control_file,
    write_control_file,
)
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.mutation import atomic_write_bytes
from lumio_wiki.private_profile import load_private_profile, resolve_private_profile

from .contributions import _digest, _git
from .intake import IntakeService
from .publication import PublicationService
from .review import AnalyticsReviewContext
from .setup import current_attachment_digest
from .state import Actor, Operation, RetryConflict, WorkspaceState


class AnalyticsError(ValueError):
    """An actionable analytics configuration, authorization, or native-state error."""


def _candidate_page(filename: str, markdown: str) -> tuple[str, dict]:
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or not filename.isprintable()
        or len(filename) > 160
        or not filename.lower().endswith((".md", ".markdown"))
    ):
        raise AnalyticsError("analytics pages require a safe Markdown basename")
    try:
        marker = markdown.index("\n---", 4)
        frontmatter = msgspec.yaml.decode(markdown[4:marker])
    except (ValueError, msgspec.DecodeError) as exc:
        raise AnalyticsError("analytics page has invalid frontmatter") from exc
    if not isinstance(frontmatter, dict) or frontmatter.get("visibility") != "internal":
        raise AnalyticsError("workspace-wide analytics pages require visibility: internal")
    # Native integrated validation, not the document-only Entity Type rule,
    # decides whether the declared Policy/Metric/Reference profile is supported.
    return markdown, frontmatter


class AnalyticsService:
    def __init__(self, config: Any, state: WorkspaceState, intake: IntakeService) -> None:
        self.config = config
        self.state = state
        self.intake = intake
        self.workspace_id = config.workspace_id
        self.project_id = config.analytics_project_id
        self.project = Path(config.analytics_project_path).resolve()
        self.authoring_path = Path(config.authoring_path).resolve()
        self.profile_path = Path(config.private_profile_path)
        self.private_root = Path(config.operational_root)
        self.external_url = config.external_url.rstrip("/")
        self.bindings_path = Path(config.analytics_source_bindings_path)
        self.api = AuthoringProject(self.project)
        self.publication = PublicationService(
            authoring_path=self.authoring_path,
            profile_path=self.profile_path,
            destination=config.published_path,
        )

    def _project(self, project: str) -> None:
        if project != self.project_id:
            raise AnalyticsError("unknown analytics project handle; use the configured project")

    def _retry(self, value: str) -> None:
        if not 1 <= len(value) <= 200 or not value.isprintable():
            raise AnalyticsError("retry key must be printable and at most 200 characters")

    def _entries(self, handles: list[str]) -> list[dict]:
        try:
            bindings = json.loads(self.bindings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AnalyticsError(
                "analytics source bindings are unavailable; the owner must repair the "
                "operator-controlled binding file"
            ) from exc
        entries = []
        for handle in handles:
            selected = bindings.get(handle) if isinstance(bindings, dict) else None
            if not isinstance(selected, list) or not selected:
                raise AnalyticsError(
                    f"source handle {handle!r} has no operator binding; ask the owner to "
                    "provision the exact source before retrying"
                )
            entries.extend(selected)
        return entries

    def _resources(self):
        profile = load_private_profile(self.profile_path, kb_root=self.authoring_path)
        return resolve_private_profile(
            profile,
            kb_root=self.authoring_path,
            needs=frozenset({"registry", "artifacts"}),
        )

    def _require_attachment(self) -> None:
        attachment = current_attachment_digest(
            target=self.authoring_path,
            profile_path=self.profile_path,
        )
        if not self.state.has_setup_attachment(self.workspace_id, attachment):
            raise AnalyticsError(
                "the current analytics target and private binding need owner setup"
            )

    def _operation(self, actor: Actor, action: str, task_id: str) -> Operation:
        operation = self.state.get_operation(self.workspace_id, actor, action, task_id)
        if operation is None:
            raise AnalyticsError("analytics task is not available for this caller")
        return operation

    def _grant(
        self,
        actor: Actor,
        task_id: str,
        project: str,
        resolved: list[dict] | None,
        digest: str | None,
    ) -> Operation:
        operation = self._operation(actor, "prepare_data_source", task_id)
        approval = authoring_sources.approval_state(self.project, resolved, digest)
        if not approval.get("approved"):
            raise AnalyticsError(
                "native Source Approval is absent or stale; approve the current exact "
                "effective source identity before profiling or query"
            )
        if operation.status != "data_granted" or operation.response.get("project") != project:
            raise AnalyticsError(
                "data authorization is required for this caller and exact source set"
            )
        if operation.response.get("source_digest") != digest or operation.response.get(
            "approval_digest"
        ) != approval.get("approval_digest"):
            raise AnalyticsError(
                "data authorization does not match the current complete effective source "
                "set; request a fresh grant"
            )
        return operation

    def prepare_data_source(
        self,
        actor: Actor,
        *,
        retry_key: str,
        project: str,
        source: str,
        table: str,
        business_questions: list[str],
    ) -> dict:
        self._project(project)
        self._retry(retry_key)
        if not table or not isinstance(business_questions, list):
            raise AnalyticsError("a table and known business questions are required")
        entries = self._entries([source])
        input_digest = _digest(
            {
                "project": project,
                "source": source,
                "entries": entries,
                "table": table,
                "business_questions": business_questions,
            }
        )
        operation, _ = self.state.start_operation(
            self.workspace_id,
            actor,
            "prepare_data_source",
            retry_key,
            input_digest,
            source_id=source,
        )
        if operation.status != "pending":
            return operation.response
        with self.state.operation_lock(operation) as acquired:
            if not acquired:
                return {**operation.response, "task_id": operation.operation_id}
            current = self._operation(actor, "prepare_data_source", operation.operation_id)
            if current.status != "pending":
                return current.response
            try:
                started = self.api.start_proposal()
                proposed = self.api.propose_sources(
                    started["proposal"], started["candidate_revision"], entries
                )
                response = {
                    "task_id": current.operation_id,
                    "status": "pending_source_approval",
                    "stage": "source_approval",
                    "project": project,
                    "source": source,
                    "table": table,
                    "business_questions": business_questions,
                    "native_proposal": started["proposal"],
                    "native_base": started["base_revision"],
                    "native_candidate": proposed["revision"],
                    "source_digest": proposed["source_digest"],
                    "review_url": f"{self.external_url}/review/{current.operation_id}",
                    "review_generation": 0,
                    "published": False,
                }
            except ValueError as exc:
                response = {
                    "task_id": current.operation_id,
                    "status": "failed",
                    "error": str(exc),
                    "published": False,
                }
                self.state.finish_operation(self.workspace_id, actor, current, "failed", response)
                raise AnalyticsError(str(exc)) from exc
            self.state.finish_operation(
                self.workspace_id, actor, current, "pending_review", response
            )
            return response

    def profile_data_source(self, actor: Actor, task_id: str) -> dict:
        operation = self._operation(actor, "prepare_data_source", task_id)
        response = operation.response
        resolved, digest = authoring_sources.candidate_sources(
            self.project, response["native_candidate"]
        )
        self._grant(actor, task_id, response["project"], resolved, digest)
        try:
            measured = self.api.inputs(response["native_proposal"])
        except ValueError as exc:
            raise AnalyticsError(str(exc)) from exc
        return {
            "task_id": task_id,
            "project": response["project"],
            "source_digest": digest,
            "approval_digest": response["approval_digest"],
            "table": response["table"],
            "business_questions": response["business_questions"],
            "profile": measured["profile"],
        }

    def query_data(
        self,
        actor: Actor,
        project: str,
        source_task_id: str,
        operation: str,
        request: dict,
    ) -> dict:
        self._project(project)
        record, _snapshot = admission.resolve_admission(self.project)
        self._grant(
            actor,
            source_task_id,
            project,
            record.get("sources") or [],
            record["source_digest"],
        )
        runtime = QueryRuntime.open_project(self.project)
        try:
            if operation == "get_metric":
                result = runtime.get_metric(
                    request["name"],
                    dimensions=request.get("dimensions"),
                    range=request.get("range"),
                )
            elif operation == "query_metrics":
                result = runtime.query_metrics(request)
            elif operation == "query_detail":
                result = runtime.query_detail(request)
            elif operation == "query_records":
                result = runtime.query_records(request)
            elif operation == "define_metric":
                result = runtime.define_metric(request)
            else:
                raise AnalyticsError(
                    "unsupported analytics operation; use a governed metric/detail, bounded "
                    "record, or explicit ad-hoc definition"
                )
            import asyncio

            answer = asyncio.run(result)
        finally:
            runtime.con.close()
        return {
            **answer,
            "pinned": {
                "commit": record["commit"],
                "source_digest": record["source_digest"],
            },
        }

    def _source_context(self, actor: Actor, operation: Operation) -> AnalyticsReviewContext:
        response = operation.response
        resolved, digest = authoring_sources.candidate_sources(
            self.project, response["native_candidate"]
        )
        approval = authoring_sources.approval_state(self.project, resolved, digest)
        stage = response["stage"]
        if stage == "data_grant" and not approval.get("approved"):
            raise AnalyticsError("the approved source identity changed; review it again")
        display = {
            "stage": stage,
            "namespace": "Ariadne source access",
            "base": response["native_base"],
            "candidate": response["native_candidate"],
            "destination": "operator-owned native Source Approval and caller data grant",
            "expected": stage,
            "observed": approval["state"],
            "source": {
                "handle": response["source"],
                "table": response["table"],
                "business_questions": response["business_questions"],
                "resolved_identity": resolved,
                "source_digest": digest,
                "approval": approval,
            },
            "validation": [
                "No source schema or data is opened by this review. Profiling requires "
                "both native Source Approval and the requester's separate data grant."
            ],
            "blocking": [],
            "decision_label": (
                "Approve this exact native source identity"
                if stage == "source_approval"
                else "Grant the requester this exact complete source set"
            ),
        }
        binding = {
            "workspace": self.workspace_id,
            "task": operation.operation_id,
            "reviewer": {"tenant_id": actor.tenant_id, "object_id": actor.object_id},
            "base": response["native_base"],
            "candidate": response["native_candidate"],
            "submission_base": response["native_base"],
            "submission_review": digest,
            "review_generation": response.get("review_generation", 0),
            "stage": stage,
            "source_digest": digest,
            "approval_digest": approval.get("approval_digest"),
        }
        return AnalyticsReviewContext(operation, display, binding, "")

    def _contribution_review(self, response: dict) -> dict:
        return review_contribution(
            self.project,
            response["native_proposal"],
            base_revision=response["native_base"],
            private_profile=self.profile_path,
        )

    def _overall(self, response: dict) -> dict:
        return self.publication.overall_preview(
            self.project,
            response["native_proposal"],
            response["native_candidate"],
            response["native_review"],
            expected_current=self.publication.current_version() or "none",
        )

    def _contribution_context(self, actor: Actor, operation: Operation) -> AnalyticsReviewContext:
        response = operation.response
        stage = response["stage"]
        review = self._contribution_review(response)
        overall = None if stage == "submission" else self._overall(response)
        publication = None if overall is None else overall["publication_review"]
        blocking = list(review["unknown_paths"])
        if publication is not None:
            blocking.extend(publication["blocking_diagnostics"])
        display = {
            "stage": stage,
            "namespace": review["knowledge"]["namespace"] if review["knowledge"] else "Ariadne",
            "base": response["native_base"],
            "candidate": response["native_candidate"],
            "destination": (
                publication["destination"] if publication else "native commit and validation"
            ),
            "expected": publication["expected_current"] if publication else "candidate validation",
            "observed": publication["observed_current"] if publication else "not admitted",
            "review": review,
            "overall": overall,
            "validation": [
                review["validation"]["live"]["reason"]
                if stage == "submission"
                else "Exact candidate validated; one native overall admission is required."
            ],
            "blocking": blocking,
            "decision_label": (
                "Commit and validate exactly this complete contribution"
                if stage == "submission"
                else "Approve and activate exactly this overall native release"
            ),
        }
        candidate = (
            response["native_tree"] if stage == "submission" else response["native_candidate"]
        )
        binding = {
            "workspace": self.workspace_id,
            "task": operation.operation_id,
            "reviewer": {"tenant_id": actor.tenant_id, "object_id": actor.object_id},
            "base": response["native_base"],
            "candidate": candidate,
            "submission_base": response["native_base"],
            "submission_review": review["review_digest"],
            "review_generation": response.get("review_generation", 0),
            "stage": stage,
            "contribution_review": review["review_digest"],
            "overall_digest": overall["digest"] if overall else None,
            "citations": overall.get("citations", []) if overall else [],
        }
        return AnalyticsReviewContext(operation, display, binding, "")

    def review_context(self, actor: Actor, operation: Operation) -> AnalyticsReviewContext:
        if operation.action == "prepare_data_source":
            return self._source_context(actor, operation)
        return self._contribution_context(actor, operation)

    def _reject(self, operation: Operation, decision: str) -> dict:
        requested = decision == "request_changes"
        response = {
            **operation.response,
            "status": "pending_review" if requested else "rejected",
            "review_decision": decision,
            "review_generation": operation.response.get("review_generation", 0) + 1,
            "published": False,
        }
        self.state.finish_review_task(
            self.workspace_id,
            operation.operation_id,
            "pending_review" if requested else "rejected",
            response,
        )
        return response

    def apply_decision(self, actor: Actor, context: AnalyticsReviewContext, decision: str) -> dict:
        operation = context.operation
        if decision != "approve":
            return self._reject(operation, decision)
        response = operation.response
        generation = response.get("review_generation", 0) + 1
        if operation.action == "prepare_data_source":
            if response["stage"] == "source_approval":
                approved = self.api.approve_sources(
                    response["native_proposal"],
                    response["native_candidate"],
                    response["source_digest"],
                )
                updated = {
                    **response,
                    "status": "pending_data_grant",
                    "stage": "data_grant",
                    "approval_digest": approved["approval_digest"],
                    "review_generation": generation,
                }
                self.state.finish_review_task(
                    self.workspace_id, operation.operation_id, "pending_review", updated
                )
                return updated
            resolved, digest = authoring_sources.candidate_sources(
                self.project, response["native_candidate"]
            )
            approval = authoring_sources.approval_state(self.project, resolved, digest)
            if not approval.get("approved"):
                raise AnalyticsError("current native Source Approval is required before data grant")
            updated = {
                **response,
                "status": "data_granted",
                "stage": "data_granted",
                "approval_digest": approval["approval_digest"],
                "review_generation": generation,
            }
            self.state.finish_review_task(
                self.workspace_id, operation.operation_id, "data_granted", updated
            )
            return updated

        if response["stage"] == "submission":
            review = self._contribution_review(response)
            tree = self.project / proposals.WORKTREES_REL / response["native_proposal"]
            _git(
                tree,
                "-c",
                "user.name=Lumio Workspace",
                "-c",
                "user.email=lumio-workspace@localhost",
                "commit",
                "-qm",
                f"Prepare analytics contribution {operation.operation_id}",
            )
            candidate = _git(tree, "rev-parse", "HEAD")
            checked = check_contribution_commit(
                self.project, response["native_proposal"], review, candidate
            )
            if not checked["matches_reviewed_candidate"]:
                raise AnalyticsError(
                    "committed analytics candidate differs from its review: "
                    + "; ".join(checked["mismatches"])
                )
            admission.reconcile(
                self.project,
                response["native_proposal"],
                review["head_revision"],
                candidate,
            )
            validated = self.api.validate_proposal(response["native_proposal"], candidate)
            if not validated["ok"]:
                raise AnalyticsError(
                    "native analytics validation failed: " + "; ".join(validated["errors"])
                )
            native = self.api.review_proposal(response["native_proposal"])
            updated = {
                **response,
                "status": "pending_publication",
                "stage": "publication",
                "native_candidate": validated["revision"],
                "native_review": native["review_digest"],
                "validation": {
                    "ok": True,
                    "revision": validated["revision"],
                    "artifact_digest": validated["artifact_digest"],
                },
                "review_generation": generation,
            }
            self.state.finish_review_task(
                self.workspace_id, operation.operation_id, "pending_review", updated
            )
            return updated

        overall = self._overall(response)
        receipt = self.publication.publish_overall(
            self.project,
            response["native_proposal"],
            response["native_candidate"],
            response["native_review"],
            overall,
            confirmed_by=f"browser:{actor.tenant_id}/{actor.object_id}",
        )
        updated = {
            **response,
            "status": "published",
            "stage": "admitted",
            "published": True,
            "publication_outcome": "activated",
            "bound_release": receipt["bound_release"]["digest"],
            "native_publication": {
                "activated": receipt["native_outcome"]["publication_receipt"]["activated"]
            },
            "citations": context.binding.get("citations", []),
            "review_generation": generation,
        }
        self.state.finish_review_task(
            self.workspace_id, operation.operation_id, "published", updated
        )
        return updated

    def prepare_contribution(
        self,
        actor: Actor,
        *,
        retry_key: str,
        source_task_id: str,
        sources: list[dict],
        pages: list[dict],
        core_edits: list[dict],
    ) -> dict:
        self._retry(retry_key)
        self._require_attachment()
        grant = self._operation(actor, "prepare_data_source", source_task_id)
        if grant.status != "data_granted":
            raise AnalyticsError("the exact source-set data grant is required first")
        source_handles = [grant.response["source"]]
        entries = self._entries(source_handles)
        checked_pages = []
        for item in pages:
            filename = item["filename"]
            markdown = item["markdown"]
            checked_pages.append((filename, *_candidate_page(filename, markdown)))
        checked_sources = []
        conversion = []
        for item in sources:
            upload_id = item.get("upload_id")
            intent = item.get("intent")
            if not isinstance(upload_id, str) or intent not in {"new", "update"}:
                raise AnalyticsError("each source requires upload_id and new/update intent")
            operation, path = self.intake.load(self.workspace_id, actor, upload_id)
            _material, facts = self.intake.extract(self.workspace_id, actor, upload_id)
            conversion.append(facts)
            checked_sources.append((operation, path, intent))
        input_digest = _digest(
            {
                "source_task": source_task_id,
                "source_digest": grant.response["source_digest"],
                "entries": entries,
                "core_edits": core_edits,
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
        operation, _ = self.state.start_operation(
            self.workspace_id, actor, "prepare_contribution", retry_key, input_digest
        )
        if operation.status != "pending":
            return operation.response
        with self.state.operation_lock(operation) as acquired:
            if not acquired:
                return {**operation.response, "task_id": operation.operation_id}
            current = self._operation(actor, "prepare_contribution", operation.operation_id)
            if current.status != "pending":
                return current.response
            try:
                started = self.api.start_proposal()
                proposal = started["proposal"]
                revision = started["candidate_revision"]
                if entries:
                    revision = self.api.propose_sources(proposal, revision, entries)["revision"]
                resolved, source_digest = authoring_sources.candidate_sources(
                    self.project, revision
                )
                self._grant(
                    actor,
                    source_task_id,
                    grant.response["project"],
                    resolved,
                    source_digest,
                )
                for edit in core_edits:
                    revision = self.api.edit_proposal(proposal, revision, edit)["revision"]
                resources = self._resources()
                _repo_root, subtree = resolve_repository(self.authoring_path)
                tree = self.project / proposals.WORKTREES_REL / proposal
                task_kb = tree / subtree
                control = document_first_control_file(load_control_file(task_kb))
                control_path = write_control_file(
                    self.private_root / "controls" / operation.operation_id,
                    control,
                )
                authored = self.private_root / "authored" / operation.operation_id
                page_paths = []
                for filename, markdown, _frontmatter in checked_pages:
                    path = authored / filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_bytes(path, markdown.encode())
                    page_paths.append(str(path))
                ingest_candidate(
                    task_kb,
                    CandidateRequest(
                        schema_version=1,
                        base_revision=started["base_revision"],
                        sources=[
                            CandidateSourceRecord(
                                source_id=source.source_id or "",
                                original_path=str(path),
                                expected_digest=source.response["sha256"],
                                intent=intent,
                            )
                            for source, path, intent in checked_sources
                        ],
                        pages=page_paths,
                        control=str(control_path),
                    ),
                    source_registry=resources.source_registry,
                    artifact_store=resources.artifact_store,
                )
                _git(task_kb, "add", "--", ".")
                review = self._contribution_review(
                    {
                        "native_proposal": proposal,
                        "native_base": started["base_revision"],
                    }
                )
                response = {
                    "task_id": operation.operation_id,
                    "status": "pending_submission",
                    "stage": "submission",
                    "project": grant.response["project"],
                    "source_task_id": source_task_id,
                    "native_proposal": proposal,
                    "native_base": started["base_revision"],
                    "native_candidate": review["head_revision"],
                    "native_tree": review["candidate_tree"],
                    "native_review": review["review_digest"],
                    "review_url": f"{self.external_url}/review/{operation.operation_id}",
                    "review_generation": 0,
                    "conversion": conversion,
                    "published": False,
                }
            except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                response = {
                    "task_id": operation.operation_id,
                    "status": "failed",
                    "error": str(exc),
                    "published": False,
                }
                self.state.finish_operation(self.workspace_id, actor, current, "failed", response)
                if isinstance(exc, RetryConflict):
                    raise
                raise AnalyticsError(str(exc)) from exc
            self.state.finish_operation(
                self.workspace_id, actor, current, "pending_review", response
            )
            return response

    def get(self, actor: Actor, task_id: str) -> dict:
        source = self.state.get_operation(self.workspace_id, actor, "prepare_data_source", task_id)
        if source is not None:
            return source.response
        return self._operation(actor, "prepare_contribution", task_id).response

    def reconcile(self, operation: Operation) -> dict | None:
        response = operation.response
        candidate_key = (
            "native_tree" if response.get("stage") == "submission" else "native_candidate"
        )
        approval = self.state.get_review_approval(
            self.workspace_id,
            operation.operation_id,
            response.get(candidate_key, ""),
        )
        if (
            approval is None
            or approval.status != "completed"
            or approval.binding.get("stage") != response.get("stage")
        ):
            return None
        if operation.action == "prepare_data_source":
            resolved, digest = authoring_sources.candidate_sources(
                self.project, response["native_candidate"]
            )
            native = authoring_sources.approval_state(self.project, resolved, digest)
            if not native.get("approved"):
                return None
            if response["stage"] == "source_approval":
                updated = {
                    **response,
                    "status": "pending_data_grant",
                    "stage": "data_grant",
                    "approval_digest": native["approval_digest"],
                }
                self.state.finish_review_task(
                    self.workspace_id,
                    operation.operation_id,
                    "pending_review",
                    updated,
                    expected_response=response,
                )
                return updated
            if response["stage"] == "data_grant":
                updated = {**response, "status": "data_granted", "stage": "data_granted"}
                self.state.finish_review_task(
                    self.workspace_id,
                    operation.operation_id,
                    "data_granted",
                    updated,
                    expected_response=response,
                )
                return updated
            return None
        if response["stage"] == "publication":
            current = admission.load_current(self.project)
            if current and current["commit"] == response["native_candidate"]:
                updated = {
                    **response,
                    "status": "published",
                    "stage": "admitted",
                    "published": True,
                    "publication_outcome": "activated",
                    "bound_release": current["bound_release"]["digest"],
                }
                self.state.finish_review_task(
                    self.workspace_id,
                    operation.operation_id,
                    "published",
                    updated,
                    expected_response=response,
                )
                return updated
            native_current = PublishedFilesystemLocation(self.config.published_path).read_pointer()
            if native_current == response["native_candidate"]:
                return {
                    **response,
                    "publication_outcome": "native_published_core_pending",
                    "published": False,
                }
        return None
