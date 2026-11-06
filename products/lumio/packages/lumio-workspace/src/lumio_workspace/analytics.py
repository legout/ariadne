"""Lazy Ariadne analytics for an explicitly enabled shared workspace."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import msgspec
from ariadne import admission, authoring_sources, proposals
from ariadne import sources as native_sources
from ariadne.authoring import AuthoringProject
from ariadne.contribution_review import check_contribution_commit, review_contribution
from ariadne.query import QueryRuntime
from lumio_wiki.authoring_journey import (
    CandidateRequest,
    CandidateSourceRecord,
    ingest_candidate,
)
from lumio_wiki.git_authoring import (
    PRIVATE_OPERATIONS_DIR,
    PublicationReceipt,
    resolve_repository,
)
from lumio_wiki.knowledge_base import (
    KnowledgeBaseError,
    document_first_control_file,
    load_control_file,
    write_control_file,
)
from lumio_wiki.location import PublishedFilesystemLocation, open_knowledge_base
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

    def _selection(self, handles: list[str]) -> tuple[list[dict], dict]:
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
        storages = bindings.get("storages", {}) if isinstance(bindings, dict) else {}
        if not isinstance(storages, dict):
            raise AnalyticsError("operator source binding 'storages' must be a mapping")
        referenced = {
            entry.get("storage")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("storage"), str)
        }
        return entries, {name: storages[name] for name in referenced if name in storages}

    def _declarations_present(
        self, revision: str, entries: list[dict], storages: dict | None = None
    ) -> bool:
        """Match exact declarations in an admitted Git registry without opening sources."""
        try:
            document = msgspec.yaml.decode(_git(self.project, "show", f"{revision}:ariadne.yaml"))
        except (subprocess.CalledProcessError, msgspec.DecodeError):
            return False
        existing = document.get("sources") if isinstance(document, dict) else None
        declared = document.get("storages") if isinstance(document, dict) else {}
        profiles = native_sources.validate_storages(storages, "operator source bindings")
        existing_profiles = native_sources.validate_storages(declared, "candidate registry")
        return (
            isinstance(existing, list)
            and all(entry in existing for entry in entries)
            and all(existing_profiles.get(name) == profile for name, profile in profiles.items())
        )

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

    def _prepare_upload(
        self,
        *,
        path: Path,
        facts: dict,
        table: str,
        sheets: list[str] | None,
        identity: str,
    ) -> tuple[list[dict], list[dict]]:
        native_source = f"upload_{identity[:24]}"
        managed = self.project / ".ariadne" / "managed-sources" / identity
        source_type = facts["source_type"]
        if source_type == "xlsx":
            from ariadne.spreadsheet_import import import_workbook

            imported = import_workbook(path, sheets=sheets or [], output=managed / "workbook")
            if imported["source_sha256"] != facts["sha256"]:
                raise AnalyticsError("the retained XLSX bytes changed after upload")
            if table not in imported["derived_source"]["tables"]:
                raise AnalyticsError(
                    "table must name one normalized table from the explicitly imported sheets"
                )
            artifact = Path(imported["artifact_path"]).resolve()
            try:
                relative = artifact.relative_to(self.project)
            except ValueError as exc:
                raise AnalyticsError(
                    "derived workbook artifact escaped its private destination"
                ) from exc
            entry = {
                "name": native_source,
                "type": "duckdb",
                "path": relative.as_posix(),
            }
            conversion = {
                **facts,
                "conversion_status": "converted_pending_approval",
                "selection_identity": imported["selection_identity"],
                "derived_source": {
                    "identity": imported["derived_source"]["identity"],
                    "type": "duckdb",
                    "tables": imported["derived_source"]["tables"],
                    "registry_path": relative.as_posix(),
                },
                "artifact_sha256": imported["artifact_sha256"],
                "sheets": imported["sheets"],
                "limitations": imported["limitations"],
                "cache_freshness": "unknown",
                "formula_evaluation": False,
                "recalculation": False,
            }
            return [entry], [conversion]

        suffix = Path(facts["filename"]).suffix.lower()
        relative = Path(".ariadne") / "managed-sources" / identity / f"source{suffix}"
        retained = self.project / relative
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != facts["sha256"]:
            raise AnalyticsError("the retained structured bytes changed after upload")
        retained.parent.mkdir(parents=True, exist_ok=True)
        try:
            with retained.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
        if hashlib.sha256(retained.read_bytes()).hexdigest() != facts["sha256"]:
            raise AnalyticsError(
                "an existing managed source does not match its immutable identity; "
                "preserve it for operator resolution"
            )
        retained.chmod(0o444)
        entry = {
            "name": native_source,
            "type": source_type,
            "path": relative.as_posix(),
            "table": table,
        }
        conversion = {
            **facts,
            "conversion_status": "staged_pending_approval",
            "native_handler": source_type,
            "derived_source": {
                "identity": identity,
                "type": source_type,
                "tables": [table],
                "registry_path": relative.as_posix(),
            },
            "limitations": [
                "The existing native handler interprets the file only after exact Source Approval "
                "and caller data authorization; units and joins are not inferred."
            ],
        }
        return [entry], [conversion]

    def prepare_data_source(
        self,
        actor: Actor,
        *,
        retry_key: str,
        project: str,
        source: str,
        table: str,
        business_questions: list[str],
        upload_id: str | None = None,
        sheets: list[str] | None = None,
    ) -> dict:
        self._project(project)
        self._retry(retry_key)
        if not table or not isinstance(business_questions, list):
            raise AnalyticsError("a table and known business questions are required")
        if upload_id is None and sheets is not None:
            raise AnalyticsError("sheet selection requires an XLSX upload_id")
        upload_path = None
        upload_facts = None
        managed_identity = None
        storages = {}
        if upload_id is None:
            entries, storages = self._selection([source])
            input_digest = _digest(
                {
                    "project": project,
                    "source": source,
                    "entries": entries,
                    "storages": storages,
                    "table": table,
                    "business_questions": business_questions,
                }
            )
        else:
            upload_operation, upload_path, upload_facts = self.intake.structured(
                self.workspace_id, actor, upload_id
            )
            if upload_operation.source_id != source:
                raise AnalyticsError("source must match the upload's identified source_id")
            source_type = upload_facts["source_type"]
            if source_type == "xlsx":
                if not isinstance(sheets, list) or not sheets:
                    raise AnalyticsError("XLSX requires an explicit nonempty sheet selection")
            elif sheets is not None:
                raise AnalyticsError("sheets are valid only for XLSX uploads")
            managed_identity = _digest(
                {
                    "source_id": source,
                    "sha256": upload_facts["sha256"],
                    "sheets": sorted(sheets or []),
                    "table": table if source_type != "xlsx" else None,
                }
            )
            entries = []
            input_digest = _digest(
                {
                    "project": project,
                    "source": source,
                    "upload_id": upload_id,
                    "upload_sha256": upload_facts["sha256"],
                    "managed_identity": managed_identity,
                    "table": table,
                    "business_questions": business_questions,
                    "sheets": sorted(sheets or []),
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
                conversion = []
                if upload_facts is not None:
                    assert upload_path is not None and managed_identity is not None
                    entries, conversion = self._prepare_upload(
                        path=upload_path,
                        facts=upload_facts,
                        table=table,
                        sheets=sheets,
                        identity=managed_identity,
                    )
                if len(entries) != 1:
                    raise AnalyticsError(
                        "selected-table profiling requires one native source per source handle"
                    )
                try:
                    record, _snapshot = admission.resolve_admission(self.project)
                except ValueError:
                    record = None
                reused = record is not None and self._declarations_present(
                    record["commit"], entries, storages
                )
                approval = {}
                if reused:
                    assert record is not None
                    started = {"proposal": record["proposal"], "base_revision": record["commit"]}
                    proposed = {
                        "revision": record["commit"],
                        "source_digest": (
                            record.get("source_declaration_digest") or record["source_digest"]
                        ),
                    }
                    approval = authoring_sources.approval_state(
                        self.project, record.get("sources") or [], proposed["source_digest"]
                    )
                    if not approval.get("approved"):
                        raise AnalyticsError(
                            "the admitted declaration needs current native Source Approval"
                        )
                else:
                    started = self.api.start_proposal()
                    if self._declarations_present(started["candidate_revision"], entries, storages):
                        _resolved, source_digest = authoring_sources.candidate_sources(
                            self.project, started["candidate_revision"]
                        )
                        assert source_digest is not None
                        proposed = {
                            "revision": started["candidate_revision"],
                            "source_digest": source_digest,
                        }
                    else:
                        proposed = self.api.propose_sources(
                            started["proposal"], started["candidate_revision"], entries, storages
                        )
                response = {
                    "task_id": current.operation_id,
                    "status": "pending_data_grant" if reused else "pending_source_approval",
                    "stage": "data_grant" if reused else "source_approval",
                    "project": project,
                    "source": source,
                    "native_source": entries[0]["name"],
                    "table": table,
                    "business_questions": business_questions,
                    "native_proposal": started["proposal"],
                    "native_base": started["base_revision"],
                    "native_candidate": proposed["revision"],
                    "source_digest": proposed["source_digest"],
                    "reused_source_declaration": reused,
                    "conversion": conversion,
                    "review_url": f"{self.external_url}/review/{current.operation_id}",
                    "review_generation": 0,
                    "published": False,
                    **({"approval_digest": approval["approval_digest"]} if reused else {}),
                    **(
                        {"upload_id": upload_id, "native_entries": entries}
                        if upload_id is not None
                        else {}
                    ),
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
        approval = authoring_sources.approval_state(self.project, resolved, digest)
        if approval.get("approval_digest") != response["approval_digest"]:
            raise AnalyticsError("the profile effective identity no longer matches its grant")
        try:
            measured = self.api.inputs(
                response["native_proposal"],
                sample_rows=100,
                selector=(response.get("native_source", response["source"]), response["table"]),
                expected_revision=response["native_candidate"],
            )
        except ValueError as exc:
            raise AnalyticsError(str(exc)) from exc
        after, after_digest = authoring_sources.candidate_sources(
            self.project, response["native_candidate"]
        )
        after_approval = authoring_sources.approval_state(self.project, after, after_digest)
        if (
            after != resolved
            or after_digest != digest
            or after_approval.get("approval_digest") != approval.get("approval_digest")
            or measured["revision"] != response["native_candidate"]
            or measured["sources_digest"] != digest
        ):
            raise AnalyticsError("the profiled revision or effective identity changed")
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
            record.get("source_declaration_digest") or record["source_digest"],
        )
        runtime = QueryRuntime.open_project(self.project, admission_record=record)
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

    def _publication_recovery(self, response: dict) -> PublicationReceipt | None:
        candidate = response["native_candidate"]
        destination = self.config.published_path.resolve()
        receipt_path = destination / PRIVATE_OPERATIONS_DIR / "receipts" / f"{candidate}.json"
        try:
            raw = receipt_path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            receipt = msgspec.json.decode(raw, type=PublicationReceipt)
            location = PublishedFilesystemLocation(destination, version=candidate)
            manifest = location.read_manifest(candidate)
            resolved = open_knowledge_base(location)
        except (OSError, msgspec.DecodeError, KnowledgeBaseError) as exc:
            raise AnalyticsError("the native publication evidence is unavailable") from exc
        if not resolved.validation_report.is_valid:
            raise AnalyticsError("the native publication does not validate during recovery")
        if (
            receipt.version != candidate
            or receipt.revision != manifest.revision
            or receipt.subtree != manifest.subtree
            or receipt.fingerprint != manifest.fingerprint
            or receipt.manifest_digest != manifest.source_reference_digest
            or receipt.validator_contract != manifest.format_identity
            or receipt.destination != str(destination)
        ):
            raise AnalyticsError(
                "native publication receipt does not match its immutable published version"
            )
        return receipt

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
            candidate = _git(tree, "rev-parse", "HEAD")
            checked = check_contribution_commit(
                self.project, response["native_proposal"], review, candidate
            )
            if not checked["matches_reviewed_candidate"]:
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
            submitter = self.state.review_task_submitter(self.workspace_id, operation.operation_id)
            if submitter is None or not self.state.permits(
                self.workspace_id, submitter, "contribute"
            ):
                raise AnalyticsError(
                    "the submitter no longer has current workspace contribution permission"
                )
            resolved, source_digest = authoring_sources.candidate_sources(self.project, candidate)
            self._grant(
                submitter,
                response["source_task_id"],
                response["project"],
                resolved,
                source_digest,
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
        if grant.response.get("native_entries"):
            entries = grant.response["native_entries"]
            storages = {}
        else:
            entries, storages = self._selection(source_handles)
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
                "storages": storages,
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
                if entries and not self._declarations_present(revision, entries, storages):
                    revision = self.api.propose_sources(proposal, revision, entries, storages)[
                        "revision"
                    ]
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
            or approval.status not in {"completed", "failed"}
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
            # Native Source Approval alone is not a caller data-grant outcome.
            # A failed action remains retryable until its grant is recorded.
            return None
        if response["stage"] == "publication":
            current = admission.load_current(self.project)
            receipt = self._publication_recovery(response)
            if receipt is None:
                return None
            if current and current["commit"] == response["native_candidate"]:
                if (
                    (current.get("overall_confirmation") or {}).get("digest")
                    != approval.binding.get("overall_digest")
                    or (current.get("confirmed") or {}).get("review_digest")
                    != response["native_review"]
                    or current.get("native_publication") != msgspec.to_builtins(receipt)
                ):
                    raise AnalyticsError(
                        "current admission does not match the persisted browser approval"
                    )
                updated = {
                    **response,
                    "status": "published",
                    "stage": "admitted",
                    "published": True,
                    "publication_outcome": "activated",
                    "bound_release": current["bound_release"]["digest"],
                    "native_publication": msgspec.to_builtins(receipt),
                    "citations": approval.binding.get("citations", []),
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
                    "native_publication": msgspec.to_builtins(receipt),
                    "citations": approval.binding.get("citations", []),
                    "published": False,
                }
        return None
