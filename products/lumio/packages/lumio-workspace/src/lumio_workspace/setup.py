"""Owner-confirmed native empty setup and adopted-KB attachment previews."""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

from lumio_wiki.git_authoring import GitAuthoringError
from lumio_wiki.journey_setup import (
    EmptySetupError,
    EmptySetupPlan,
    apply_plan,
    discover_authoring_location,
    plan_empty_setup,
    recheck_plan,
)
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.mutation import atomic_write_bytes
from lumio_wiki.private_profile import (
    PrivateProfileError,
    load_private_profile,
    resolve_private_profile,
)
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceError,
    load_source_reference_manifest,
)

from .state import Actor, WorkspaceState


class SetupError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_setup") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SetupPreview:
    workspace_id: str
    kind: str
    digest: str
    target: Path
    namespace: str
    base_revision: str | None
    actions: list[dict]
    plan: EmptySetupPlan | None
    profile_path: Path
    private_root: Path
    namespace_input: str | None


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise SetupError("native Git could not be executed", code="native_git_failed") from exc
    if result.returncode != 0:
        raise SetupError("native Git operation failed", code="native_git_failed")
    return result.stdout.decode().strip()


def preview_setup(
    *,
    workspace_id: str,
    authoring_path: Path,
    profile_path: Path,
    private_root: Path,
    namespace: str | None,
) -> SetupPreview:
    """Build a read-only preview; unadopted nonempty targets refuse without writes."""
    target = authoring_path.resolve()
    private_root = private_root.resolve()
    try:
        manifest = load_source_reference_manifest(target)
        if manifest is not None:
            return _adopted_preview(
                workspace_id,
                target,
                profile_path,
                private_root,
                namespace,
                manifest.namespace,
            )
        if not namespace:
            raise SetupError("an explicit namespace is required for a new Knowledge Base")
        project_dir = private_root / "setup"
        env_path = project_dir / ".env"
        try:
            env_bytes = env_path.read_bytes()
        except FileNotFoundError:
            env_bytes = f"LUMIO_WORKSPACE_PRIVATE_PROFILE={profile_path}\n".encode()
        plan = plan_empty_setup(
            target=target,
            namespace=namespace,
            profile_path=profile_path,
            new_profile_payload=None,
            submission={"mode": "managed", "remote": "local", "branch": "current"},
            project_dir=project_dir,
            agents_enabled=False,
            env_bytes=env_bytes,
            agents_bytes=None,
            skill=None,
        )
    except (EmptySetupError, PrivateProfileError, SourceReferenceError, GitAuthoringError) as exc:
        raise SetupError(str(exc), code=getattr(exc, "code", "invalid_setup")) from exc
    commit_action = {
        "kind": "commit",
        "path": str(target),
        "detail": (
            "create 'Initialize workspace knowledge base' from exactly lumio.yaml and "
            f"{SOURCE_REFERENCE_MANIFEST_BASENAME} on base "
            f"{plan.facts.current_commit or 'unborn'}; preserve every other index/worktree entry"
        ),
    }
    return SetupPreview(
        workspace_id=workspace_id,
        kind="empty",
        digest=_digest(
            {"native_setup_digest": plan.setup_digest, "managed_commit": commit_action}
        ),
        target=target,
        namespace=namespace,
        base_revision=plan.facts.current_commit,
        actions=[
            {
                "kind": action.kind,
                "path": action.path,
                "detail": action.detail,
            }
            for action in plan.actions
        ]
        + [commit_action],
        plan=plan,
        profile_path=profile_path,
        private_root=private_root,
        namespace_input=namespace,
    )


def _adopted_preview(
    workspace_id: str,
    target: Path,
    profile_path: Path,
    private_root: Path,
    namespace_input: str | None,
    namespace: str,
) -> SetupPreview:
    if namespace_input is not None and namespace_input != namespace:
        raise SetupError("configured namespace does not match the adopted Knowledge Base")
    if not (target / "lumio.yaml").is_file():
        raise SetupError(
            "existing content requires explicit native adoption",
            code="adoption_required",
        )
    try:
        profile = load_private_profile(profile_path, kb_root=target)
        resolved = resolve_private_profile(
            profile,
            kb_root=target,
            needs=frozenset({"registry", "artifacts"}),
        )
        facts = discover_authoring_location(target)
        _kb, report = load_knowledge_base(target)
    except (PrivateProfileError, EmptySetupError, GitAuthoringError) as exc:
        raise SetupError(str(exc), code=getattr(exc, "code", "invalid_setup")) from exc
    if facts.current_commit is None or not report.is_valid:
        raise SetupError("the adopted Knowledge Base needs a valid committed Authoring Revision")
    actions = [
        {
            "kind": "attach-existing",
            "path": str(target),
            "detail": "preserve the existing manifest, content, history, and private profile",
        }
    ]
    digest = _digest(
        {
            "operation": "setup_attach",
            "repository_root": str(facts.repository_root),
            "branch": facts.branch,
            "subtree": facts.subtree,
            "current_commit": facts.current_commit,
            "namespace": namespace,
            "profile_path": str(profile_path.resolve()),
            "private_binding": resolved.binding_digest,
            "actions": actions,
        }
    )
    return SetupPreview(
        workspace_id=workspace_id,
        kind="adopted",
        digest=digest,
        target=target,
        namespace=namespace,
        base_revision=facts.current_commit,
        actions=actions,
        plan=None,
        profile_path=profile_path,
        private_root=private_root,
        namespace_input=namespace_input,
    )


def current_attachment_digest(*, target: Path, profile_path: Path) -> str:
    """Bind contributions to the confirmed resource identity, not a moving base commit."""
    target = target.resolve()
    try:
        facts = discover_authoring_location(target)
        manifest = load_source_reference_manifest(target)
        if manifest is None:
            raise SetupError("owner setup confirmation is required", code="setup_required")
        profile = load_private_profile(profile_path, kb_root=target)
        resolved = resolve_private_profile(
            profile,
            kb_root=target,
            needs=frozenset({"registry", "artifacts"}),
        )
    except (PrivateProfileError, EmptySetupError, SourceReferenceError, GitAuthoringError) as exc:
        raise SetupError(
            "the current authoring target or private binding is unavailable",
            code="setup_required",
        ) from exc
    return _digest(
        {
            "target": str(target),
            "repository_root": str(facts.repository_root),
            "branch": facts.branch,
            "subtree": facts.subtree,
            "namespace": manifest.namespace,
            "profile_path": str(profile_path.resolve()),
            "private_binding": resolved.binding_digest,
        }
    )


def apply_setup(
    state: WorkspaceState,
    actor: Actor,
    preview: SetupPreview,
) -> dict:
    """Apply only the freshly rechecked preview; adopted content is never reinitialized."""
    if preview.plan is None:
        fresh = preview_setup(
            workspace_id=preview.workspace_id,
            authoring_path=preview.target,
            profile_path=preview.profile_path,
            private_root=preview.private_root,
            namespace=preview.namespace_input,
        )
        if fresh.digest != preview.digest:
            raise SetupError("setup target changed after preview", code="setup_target_changed")
        base_revision = preview.base_revision
    else:
        plan = preview.plan
        try:
            recheck_plan(
                plan,
                env_bytes=plan.env_bytes,
                agents_bytes=None,
                skill=None,
            )
        except EmptySetupError as exc:
            raise SetupError(str(exc), code=exc.code) from exc

        def write_env() -> None:
            path = plan.project_dir / ".env"
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(path, plan.env_bytes)

        try:
            apply_plan(
                plan,
                write_env=write_env,
                write_agents=lambda: None,
                install_skill=lambda: None,
            )
        except EmptySetupError as exc:
            raise SetupError(str(exc), code=exc.code) from exc
        kb = plan.facts.repository_root / plan.facts.subtree
        _git(kb, "add", "--", "lumio.yaml", SOURCE_REFERENCE_MANIFEST_BASENAME)
        _git(
            kb,
            "-c",
            "user.name=Lumio Workspace",
            "-c",
            "user.email=lumio-workspace@localhost",
            "commit",
            "-qm",
            "Initialize workspace knowledge base",
            "--",
            "lumio.yaml",
            SOURCE_REFERENCE_MANIFEST_BASENAME,
        )
        base_revision = _git(kb, "rev-parse", "HEAD")
    state.record_setup(
        preview.workspace_id,
        actor,
        preview.digest,
        kind=preview.kind,
        target=preview.target,
        namespace=preview.namespace,
        base_revision=base_revision,
        attachment_digest=current_attachment_digest(
            target=preview.target,
            profile_path=preview.profile_path,
        ),
    )
    return {
        "ready": True,
        "kind": preview.kind,
        "setup_digest": preview.digest,
        "namespace": preview.namespace,
        "base_revision": base_revision,
        "actions": preview.actions,
    }


def render_setup(preview: SetupPreview) -> str:
    template = Template(
        resources.files("lumio_workspace")
        .joinpath("templates/setup.html")
        .read_text(encoding="utf-8")
    )
    actions = "\n".join(
        "<li><code>"
        + html.escape(action["kind"])
        + "</code> "
        + html.escape(action["path"])
        + (" — " + html.escape(action["detail"]) if action.get("detail") else "")
        + "</li>"
        for action in preview.actions
    )
    return template.substitute(
        workspace=html.escape(preview.workspace_id),
        kind=html.escape(preview.kind),
        namespace=html.escape(preview.namespace),
        target=html.escape(str(preview.target)),
        base=html.escape(preview.base_revision or "unborn"),
        actions=actions,
        digest=html.escape(preview.digest, quote=True),
    )
