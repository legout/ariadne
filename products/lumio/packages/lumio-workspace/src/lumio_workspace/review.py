"""Human browser review bound to exact native authoring and publication evidence."""

from __future__ import annotations

import html
import json
import subprocess
from dataclasses import dataclass, replace
from importlib import resources as package_resources
from pathlib import Path
from string import Template
from urllib.parse import quote

import msgspec
from lumio_wiki.artifact_store import ArtifactAccessDenied, ArtifactCorruption, ArtifactUnavailable
from lumio_wiki.authoring_review import (
    AUTHORING_REVIEW_SCHEMA_VERSION,
    AUTHORING_REVIEW_VALIDATOR_CONTRACT,
    AuthoringReview,
    AuthoringReviewError,
    _record_digest,
    check_authoring_commit,
    review_knowledge_changes,
)
from lumio_wiki.git_authoring import (
    CapturedRevision,
    GitAuthoringError,
    PublicationReview,
    capture_revision,
    resolve_full_commit,
    resolve_repository,
)
from lumio_wiki.knowledge_base import KnowledgeBaseError
from lumio_wiki.mutation import mutation_lock
from lumio_wiki.private_profile import PrivateProfileError, ResolvedPrivateSources
from lumio_wiki.source_inspection import (
    SourceInspectionError,
    fetch_verified_artifact,
    resolve_source_reference_binding,
)

from .publication import PublicationService
from .setup import SetupError, current_attachment_digest
from .state import Actor, Operation, WorkspaceState


class ReviewError(ValueError):
    def __init__(self, message: str, *, code: str = "stale_review", status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ReviewContext:
    operation: Operation
    task_kb: Path
    captured: CapturedRevision
    authoring: AuthoringReview
    publication: PublicationReview
    resources: ResolvedPrivateSources
    source_availability: dict[tuple[str, str], bool | None]
    binding: dict
    action_digest: str


def _json(value: object) -> str:
    return json.dumps(msgspec.to_builtins(value), indent=2, ensure_ascii=False)


def _tree(repo: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{revision}^{{tree}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReviewError("the exact native candidate tree is unavailable", code="stale_review")
    return result.stdout.strip()


class ReviewService:
    def __init__(
        self,
        state: WorkspaceState,
        *,
        workspace_id: str,
        authoring_path: Path,
        profile_path: Path,
        private_root: Path,
        destination: Path,
    ) -> None:
        self.state = state
        self.workspace_id = workspace_id
        self.authoring_path = authoring_path
        self.private_root = private_root
        self.destination = destination
        self.publication = PublicationService(
            authoring_path=authoring_path,
            profile_path=profile_path,
            destination=destination,
        )

    def _authoring(
        self,
        task_kb: Path,
        repo_root: Path,
        base: str,
        candidate: str,
        resources: ResolvedPrivateSources,
    ) -> AuthoringReview:
        knowledge = review_knowledge_changes(
            task_kb,
            base,
            source_registry=resources.source_registry,
            candidate_tree=_tree(repo_root, candidate),
        )
        if knowledge.changes_outside_kb or knowledge.unreviewed_paths:
            raise ReviewError(
                "the candidate contains changes outside the supported readable review",
                code="incomplete_review_scope",
            )
        authoring = AuthoringReview(
            schema_version=AUTHORING_REVIEW_SCHEMA_VERSION,
            validator_contract=AUTHORING_REVIEW_VALIDATOR_CONTRACT,
            namespace=knowledge.namespace,
            kb_subtree=knowledge.kb_subtree,
            base_revision=knowledge.base_revision,
            head_revision=knowledge.head_revision,
            base_tree=_tree(repo_root, base),
            submitted_tree=knowledge.candidate_tree,
            excluded_unstaged=[],
            excluded_untracked=[],
            knowledge=knowledge,
            review_digest="",
        )
        object.__setattr__(
            authoring,
            "review_digest",
            _record_digest(authoring, "review_digest"),
        )
        checked = check_authoring_commit(task_kb, authoring, candidate)
        if not checked.matches_reviewed_candidate:
            raise ReviewError(
                "the candidate differs from its exact native review: "
                + "; ".join(checked.mismatches),
                code="candidate_mismatch",
            )
        return authoring

    def _context(self, actor: Actor, task_id: str) -> ReviewContext:
        if not self.state.permits(self.workspace_id, actor, "review"):
            raise ReviewError(
                "workspace review is not available", code="review_forbidden", status=403
            )
        operation = self.state.get_review_task(self.workspace_id, task_id)
        if operation is None:
            raise ReviewError("review task is not available", code="task_not_found", status=404)
        if operation.status != "pending_review":
            raise ReviewError("the candidate is not pending review", code="review_not_pending")
        submission_base = operation.response.get("native_base", "")
        candidate = operation.response.get("native_candidate", "")
        try:
            repo_root, subtree = resolve_repository(self.authoring_path)
            submission_base = resolve_full_commit(repo_root, submission_base)
            candidate = resolve_full_commit(repo_root, candidate)
            task_kb = self.private_root / "worktrees" / task_id / subtree
            attachment = current_attachment_digest(
                target=self.authoring_path,
                profile_path=self.publication.profile_path,
            )
            if not self.state.has_setup_attachment(self.workspace_id, attachment):
                raise ReviewError(
                    "the current authoring target and private binding need owner setup",
                    code="setup_required",
                )
            resources = self.publication.resources()
            # Preserve the native submission ancestry check independently of
            # the complete effective review against the admitted publication.
            self._authoring(task_kb, repo_root, submission_base, candidate, resources)
            admitted = self.publication.current_version()
            if admitted is None:
                raise ReviewError(
                    "no admitted Git baseline is available for a complete effective review",
                    code="incomplete_review_scope",
                )
            base = resolve_full_commit(repo_root, admitted)
            authoring = self._authoring(task_kb, repo_root, base, candidate, resources)
            captured = capture_revision(task_kb, candidate)
            publication = self.publication.preview(task_kb, candidate, admitted, resources)
            availability = self._source_availability(captured, resources)
        except ReviewError:
            raise
        except (
            AuthoringReviewError,
            GitAuthoringError,
            KnowledgeBaseError,
            OSError,
            PrivateProfileError,
            SetupError,
        ) as exc:
            raise ReviewError(str(exc), code="stale_review") from exc

        citations = [
            {
                "title": page.title,
                "path": page.path,
                "published_version": publication.version,
            }
            for page in authoring.knowledge.pages
            if page.change != "removed"
        ]
        binding = {
            "workspace": self.workspace_id,
            "task": task_id,
            "reviewer": {"tenant_id": actor.tenant_id, "object_id": actor.object_id},
            "base": base,
            "candidate": candidate,
            "submission_base": submission_base,
            "submission_review": operation.response.get("native_review", ""),
            "authoring_review": authoring.review_digest,
            "publication_review": publication.review_digest,
            "citations": citations,
            "attachment": attachment,
            "private_binding": resources.binding_digest,
            "retention": publication.retention,
            "destination_identity": publication.destination_identity,
            "expected_current": publication.expected_current,
        }
        return ReviewContext(
            operation,
            task_kb,
            captured,
            authoring,
            publication,
            resources,
            availability,
            binding,
            "",
        )

    @staticmethod
    def _source_availability(
        captured: CapturedRevision, resources: ResolvedPrivateSources
    ) -> dict[tuple[str, str], bool | None]:
        available: dict[tuple[str, str], bool | None] = {}
        for page in captured.kb.pages:
            for source in page.sources:
                digest = captured.manifest.bindings.get(page.id, {}).get(source.id)
                if digest is None or resources.artifact_store is None:
                    available[(page.id, source.id)] = None
                    continue
                try:
                    available[(page.id, source.id)] = resources.artifact_store.artifact_exists(
                        source_id=source.id,
                        content_hash=digest,
                    )
                except (ArtifactAccessDenied, ArtifactCorruption, ArtifactUnavailable):
                    available[(page.id, source.id)] = False
        return available

    def get(self, actor: Actor, task_id: str) -> ReviewContext:
        if not self.state.permits(self.workspace_id, actor, "review"):
            raise ReviewError(
                "workspace review is not available", code="review_forbidden", status=403
            )
        self.reconcile_task(task_id)
        context = self._context(actor, task_id)
        action = self.state.issue_review_action(
            self.workspace_id, actor, task_id, context.binding
        )
        return replace(context, action_digest=action)

    def inspect_source(
        self, actor: Actor, task_id: str, source_id: str, entity_id: str
    ) -> tuple[str, str]:
        if not self.state.permits(self.workspace_id, actor, "inspect_source"):
            raise ReviewError(
                "source inspection requires its separate capability",
                code="source_inspection_forbidden",
                status=403,
            )
        context = self._context(actor, task_id)
        registry = context.resources.source_registry
        artifact_store = context.resources.artifact_store
        if registry is None or artifact_store is None:
            raise ReviewError(
                "the exact private source resources are unavailable", code="source_unavailable"
            )
        try:
            binding = resolve_source_reference_binding(
                registry,
                context.captured.manifest,
                source_id,
                entity_id=entity_id,
            )
            raw = fetch_verified_artifact(artifact_store, binding)
            text = raw.decode("utf-8")
        except (SourceInspectionError, UnicodeDecodeError) as exc:
            raise ReviewError(str(exc), code="source_unavailable") from exc
        return binding.filename or source_id, text

    def decide(self, actor: Actor, task_id: str, action_digest: str, decision: str) -> dict:
        if decision not in {"approve", "reject", "request_changes"}:
            raise ReviewError("unknown review decision", code="invalid_decision", status=400)
        if not self.state.permits(self.workspace_id, actor, "review"):
            raise ReviewError(
                "workspace review is not available", code="review_forbidden", status=403
            )
        try:
            selected = self.publication.resources()
        except PrivateProfileError as exc:
            raise ReviewError(str(exc), code="stale_review") from exc
        lock_resources: list[str | Path] = [self.private_root / "activation", self.destination]
        for adapter in (selected.source_registry, selected.artifact_store):
            root = getattr(adapter, "root", None)
            if root is not None:
                lock_resources.append(root)
        with mutation_lock(*lock_resources):
            if not self.state.permits(self.workspace_id, actor, "review"):
                raise ReviewError(
                    "workspace review is not available", code="review_forbidden", status=403
                )
            self.reconcile_task(task_id)
            context = self._context(actor, task_id)
            if decision == "approve":
                submitter = self.state.review_task_submitter(self.workspace_id, task_id)
                if submitter is None:
                    raise ReviewError(
                        "review task is not available", code="task_not_found", status=404
                    )
                if actor == submitter and not (
                    self.state.is_single_person_workspace(self.workspace_id, actor)
                    and self.state.permits(self.workspace_id, actor, "contribute")
                ):
                    raise ReviewError(
                        "publication approval requires a different workspace member",
                        code="different_reviewer_required",
                        status=403,
                    )
            if not self.state.start_review_action(
                self.workspace_id,
                actor,
                task_id,
                decision,
                action_digest,
                context.binding,
            ):
                raise ReviewError(
                    "this browser review action was already used", code="action_replay"
                )
            try:
                response = self._apply_decision(actor, context, decision)
            except Exception as exc:
                self.state.finish_review_action(action_digest, "failed")
                if isinstance(exc, ReviewError):
                    raise
                raise ReviewError(
                    f"the native review action did not complete: {exc}",
                    code="decision_failed",
                ) from exc
            self.state.finish_review_action(action_digest, "completed")
            return response

    def reconcile_task(self, task_id: str) -> dict | None:
        operation = self.state.get_review_task(self.workspace_id, task_id)
        if operation is None or operation.status != "pending_review":
            return None
        candidate = operation.response.get("native_candidate", "")
        approval = self.state.get_review_approval(self.workspace_id, task_id, candidate)
        if approval is None:
            return None
        try:
            _repo_root, subtree = resolve_repository(self.authoring_path)
            task_kb = self.private_root / "worktrees" / task_id / subtree
            resources = self.publication.resources()
            receipt = self.publication.recover(
                task_kb,
                candidate,
                approval.binding["expected_current"],
                approval.binding["publication_review"],
                resources,
            )
            observed = self.publication.current_version()
        except (
            GitAuthoringError,
            KnowledgeBaseError,
            KeyError,
            OSError,
            PrivateProfileError,
        ) as exc:
            raise ReviewError(
                f"the native publication outcome cannot be verified: {exc}",
                code="publication_recovery_failed",
            ) from exc
        if receipt is None:
            return None

        if receipt.activated:
            if "citations" not in approval.binding:
                raise ReviewError(
                    "the persisted approval lacks its complete citation binding",
                    code="publication_recovery_failed",
                )
            status = "published"
            response = {
                **operation.response,
                "status": status,
                "published": True,
                "publication_outcome": "activated",
                "publication": msgspec.to_builtins(receipt),
                "citations": approval.binding["citations"],
            }
        else:
            status = "pending_review"
            expected = approval.binding["expected_current"]
            baseline = None if expected == "none" else expected
            response = {
                **operation.response,
                "status": status,
                "published": False,
                "publication_outcome": (
                    "not_activated" if observed == baseline else "indeterminate"
                ),
                "publication": msgspec.to_builtins(receipt),
            }
        self.state.finish_review_task(self.workspace_id, task_id, status, response)
        if receipt.activated:
            self.state.finish_review_action(approval.action_digest, "completed")
        return response

    def _apply_decision(self, actor: Actor, context: ReviewContext, decision: str) -> dict:
        if not self.state.permits(self.workspace_id, actor, "review"):
            raise ReviewError(
                "workspace review is not available", code="review_forbidden", status=403
            )
        operation = context.operation
        if decision == "approve":
            if context.publication.blocking_diagnostics:
                raise ReviewError(
                    "blocking publication diagnostics require a corrected candidate",
                    code="publication_blocked",
                )
            receipt = self.publication.publish(
                context.task_kb,
                context.publication,
                context.resources,
            )
            if not receipt.activated:
                raise ReviewError("native publication did not activate", code="publication_failed")
            response = {
                **operation.response,
                "status": "published",
                "published": True,
                "publication_outcome": "activated",
                "publication": msgspec.to_builtins(receipt),
                "citations": context.binding["citations"],
            }
            self.state.finish_review_task(
                self.workspace_id, operation.operation_id, "published", response
            )
            return response

        requested_changes = decision == "request_changes"
        response = {
            **operation.response,
            "status": "pending_review" if requested_changes else "rejected",
            "published": False,
            "review_decision": decision,
        }
        self.state.finish_review_task(
            self.workspace_id,
            operation.operation_id,
            "pending_review" if requested_changes else "rejected",
            response,
        )
        return response


def _items(values: list[str]) -> str:
    if not values:
        return "<p>None.</p>"
    return "<ul>" + "".join(f"<li>{html.escape(value)}</li>" for value in values) + "</ul>"


def render_review(context: ReviewContext, pinned_version: str | None) -> str:
    authoring = context.authoring
    publication = context.publication
    pages = []
    captured_by_path = {page.path: page for page in context.captured.kb.pages}
    for page in authoring.knowledge.pages:
        captured = captured_by_path.get(page.path)
        support = []
        if captured is None:
            support.extend(html.escape(transition) for transition in page.sources)
        else:
            for source in captured.sources:
                source_id = source.id
                availability = context.source_availability.get((captured.id, source_id))
                label = {
                    None: "public-only or no retained original",
                    True: "verified retained original",
                    False: "original unavailable",
                }[availability]
                if availability is True:
                    link = (
                        f'/review/{quote(context.operation.operation_id)}/source/'
                        f'{quote(source_id)}/{quote(captured.id)}'
                    )
                    support.append(f'<a href="{link}">{html.escape(source_id)}</a> ({label})')
                else:
                    support.append(f"{html.escape(source_id)} ({label})")
        support_html = (
            "<p>None.</p>"
            if not support
            else "<ul>" + "".join(f"<li>{item}</li>" for item in support) + "</ul>"
        )
        pages.append(
            "<section>"
            f"<h3>{html.escape(page.title or page.path)} — {html.escape(page.change)}</h3>"
            f"<p><code>{html.escape(page.path)}</code>; lifecycle "
            f"{html.escape(page.lifecycle or 'none')}; visibility "
            f"{html.escape(page.visibility or 'none')}</p>"
            f"<h4>Source support</h4>{support_html}"
            f"<h4>Content diff</h4><pre>{html.escape(page.body_diff or 'No body change.')}</pre>"
            "<h4>Semantic and Claim changes</h4>"
            "<pre>"
            + html.escape(_json({"semantic": page.semantic_changes, "claims": page.claims}))
            + "</pre>"
            "</section>"
        )
    pin = pinned_version or "current pointer"
    template = Template(
        package_resources.files("lumio_workspace")
        .joinpath("templates/review.html")
        .read_text(encoding="utf-8")
    )
    return template.substitute(
        task=html.escape(context.operation.operation_id),
        namespace=html.escape(authoring.namespace),
        base=html.escape(authoring.base_revision),
        submission_base=html.escape(context.binding["submission_base"]),
        submission_review=html.escape(context.binding["submission_review"]),
        candidate=html.escape(publication.revision),
        destination=html.escape(publication.destination),
        expected=html.escape(publication.expected_current),
        observed=html.escape(publication.observed_current or "none"),
        pin=html.escape(pin),
        authoring_digest=html.escape(authoring.review_digest),
        publication_digest=html.escape(publication.review_digest),
        retention=html.escape(publication.retention),
        validation=_items(authoring.knowledge.validation_issues),
        blocking=_items(publication.blocking_diagnostics),
        exclusions=_items(
            authoring.excluded_unstaged
            + authoring.excluded_untracked
            + [
                f"{fact.get('source_id', 'source')}: {fact.get('exclusions', [])}"
                for fact in context.operation.response.get("conversion", [])
            ]
        ),
        pages="\n".join(pages),
        manifest_changes=_items(authoring.knowledge.manifest_changes),
        control_changes=f"<pre>{html.escape(_json(authoring.knowledge.control_changes))}</pre>",
        ontology_changes=f"<pre>{html.escape(_json(authoring.knowledge.ontology_changes))}</pre>",
        publication_details=f"<pre>{html.escape(_json(publication))}</pre>",
        conversion=(
            "<pre>"
            + html.escape(_json(context.operation.response.get("conversion", [])))
            + "</pre>"
        ),
        action_digest=html.escape(context.action_digest, quote=True),
        disabled="disabled" if publication.blocking_diagnostics else "",
    )


def render_source(task_id: str, filename: str, text: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>Source: {html.escape(filename)}</title></head><body><main>"
        f"<p><a href=\"/review/{quote(task_id)}\">Back to exact candidate review</a></p>"
        f"<h1>{html.escape(filename)}</h1><pre>{html.escape(text)}</pre>"
        "</main></body></html>"
    )
