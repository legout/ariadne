"""Internal confirmed empty managed-KB creation (spec 0010 §2.2, plan 0010 J5a).

One ephemeral preview → digest → guarded apply path shared by the headless
``--confirm`` route and the interactive wizard. Nothing here persists an
approval state: the setup digest authorizes exactly one freshly revalidated
action list, and every write happens only inside :func:`apply_plan` after
that recheck. Native Git keeps ownership of commits; this module never
initializes Git, switches branches, stages, commits or pushes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import msgspec

from lumio_wiki.private_profile import (
    PrivateLocalStore,
    PrivateProfileError,
    PrivateS3Connection,
    PrivateSourceProfile,
    _declaration_from_object,
    _load_declaration,
)
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SOURCE_REFERENCE_MANIFEST_VERSION,
    SourceReferenceError,
    SourceReferenceManifest,
    parse_source_reference_manifest,
    serialize_source_reference_manifest,
)

#: Envelope/result schema version for the creation-only route (plan J5a).
EMPTY_SETUP_SCHEMA_VERSION = 1

_CONTROL_FILE_NAME = "lumio.yaml"


class EmptySetupError(ValueError):
    """A confirmed empty-setup selection is invalid or did not complete."""

    def __init__(self, message: str, *, code: str = "invalid_empty_setup") -> None:
        super().__init__(message)
        self.code = code


class AuthoringFacts(msgspec.Struct, frozen=True):
    """Read-only native Git facts about the selected authoring location."""

    repository_root: Path
    branch: str
    subtree: str
    current_commit: str | None  # None → the named branch is unborn


class SetupAction(msgspec.Struct, frozen=True):
    """One concrete local write intention; ``content_sha256`` only where the
    exact bytes are materialized in the preview (manifest/profile)."""

    kind: str
    path: str
    content_sha256: str | None = None
    detail: str | None = None


class EmptySetupPlan(msgspec.Struct, frozen=True):
    """The recheckable plan: inputs, one action list, digest and guidance."""

    target: Path
    namespace: str
    profile_path: Path
    new_profile_payload: str | None
    submission: dict  # msgspec forbids generic dict params; plain mapping
    project_dir: Path
    agents_enabled: bool
    skill: dict | None
    env_bytes: bytes
    agents_bytes: bytes | None
    facts: AuthoringFacts
    actions: list[SetupAction]
    manifest_bytes: bytes
    next_actions: list[str]
    setup_digest: str


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run one read-only Git plumbing command; callers check the result."""
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=False,
    )


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _canonical_digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _store_view(store: PrivateLocalStore | PrivateS3Connection) -> dict:
    """A non-secret view of one private resource declaration (§2.1)."""
    if isinstance(store, PrivateLocalStore):
        return {"kind": "local", "root": str(store.root)}
    view: dict = {
        "kind": "s3",
        "bucket": store.bucket,
        "prefix": store.prefix,
        "endpoint": store.endpoint,
        "region": store.region,
        "url_style": store.url_style,
    }
    if store.session_token_env is not None:
        view["session_token_env"] = store.session_token_env
    return view


def _declaration_view(profile: PrivateSourceProfile) -> dict:
    """The private non-secret declaration bound into the setup digest."""
    view: dict = {
        "schema_version": profile.schema_version,
        "namespace": profile.namespace,
        "retention": profile.retention,
        "source_registry": str(profile.source_registry),
        "artifact_store": _store_view(profile.artifact_store),
    }
    if profile.exchange is not None:
        view["exchange"] = _store_view(profile.exchange)
    return view


def discover_authoring_location(target: Path) -> AuthoringFacts:
    """Read-only discovery of the registered worktree containing ``target``.

    When the target directory is absent, discovery starts from its nearest
    existing parent — the target is never created just to satisfy a resolver
    precondition (plan J5a). A bare repository, a detached HEAD and a path
    outside any repository are refused with guidance.
    """
    target = target.resolve()
    probe = target
    while not probe.exists():
        if probe == probe.parent:
            break
        probe = probe.parent
    if not probe.is_dir():
        raise EmptySetupError(
            f"the selected authoring path {target} is not inside an existing "
            "directory; native Git prepares the repository/worktree first "
            "(spec 0010 §2.2)"
        )
    bare = _git(probe, "rev-parse", "--is-bare-repository")
    if bare.returncode != 0:
        raise EmptySetupError(
            f"the selected authoring path {target} is not inside a registered Git "
            "worktree; native Git prepares the repository, branch and worktree "
            "before setup (spec 0010 §2.2)"
        )
    if bare.stdout.decode(errors="replace").strip() == "true":
        raise EmptySetupError(
            "a bare repository cannot be an authoring worktree; select a "
            "registered branch worktree (spec 0010 §2.2)"
        )
    toplevel_raw = _git(probe, "rev-parse", "--show-toplevel")
    if toplevel_raw.returncode != 0:
        raise EmptySetupError(
            f"the selected authoring path {target} is not inside a registered Git "
            "worktree; native Git prepares the repository, branch and worktree "
            "before setup (spec 0010 §2.2)"
        )
    toplevel = Path(toplevel_raw.stdout.decode(errors="replace").strip()).resolve()
    if target != toplevel and not target.is_relative_to(toplevel):
        raise EmptySetupError(
            f"the selected authoring path {target} is outside its Git worktree "
            f"{toplevel}; choose a location inside the selected worktree "
            "(spec 0010 §2.2)"
        )
    branch_raw = _git(toplevel, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = branch_raw.stdout.decode(errors="replace").strip()
    if branch_raw.returncode != 0 or not branch:
        raise EmptySetupError(
            "the selected worktree is on a detached HEAD; check out a named "
            "authoring branch first (an unborn named branch is allowed) "
            "(spec 0010 §2.2)"
        )
    commit_raw = _git(toplevel, "rev-parse", "--quiet", "--verify", "HEAD")
    current_commit = commit_raw.stdout.decode(errors="replace").strip() or None
    subtree = "" if target == toplevel else target.relative_to(toplevel).as_posix()
    return AuthoringFacts(
        repository_root=toplevel,
        branch=branch,
        subtree=subtree,
        current_commit=current_commit,
    )


def _target_state(
    target: Path, repo_root: Path
) -> tuple[str, list[str], SourceReferenceManifest | None]:
    """Classify the creation target; every existing entry is visible.

    Ignored content counts: only the repository root may keep its own Git
    administration entry (spec 0010 §2.2).
    """
    if not target.exists():
        return "absent", [], None
    if not target.is_dir():
        return "file", [target.name], None
    entries = sorted(entry.name for entry in target.iterdir())
    if target == repo_root:
        entries = [name for name in entries if name != ".git"]
        if not entries:
            return "repo-root-git-only", entries, None
    elif not entries:
        return "empty", entries, None
    manifest: SourceReferenceManifest | None = None
    if (target / SOURCE_REFERENCE_MANIFEST_BASENAME).exists():
        # A present-but-malformed manifest becomes a bounded setup refusal
        # with recovery guidance (R5): existing manifests are never
        # reinterpreted as an empty KB, and parser failures never escape the
        # public CLI.
        try:
            manifest = parse_source_reference_manifest(
                (target / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
            )
        except (SourceReferenceError, OSError) as exc:
            raise EmptySetupError(
                f"the creation target {target} carries a malformed or unreadable "
                f"Source Reference Manifest ({exc}); recover it manually or "
                "adopt it through the explicit Git-authoring adoption "
                "contract, or choose a different authoring location — setup "
                "never reinterprets or overwrites it (spec 0010 §2.2)",
                code="adoption_required",
            ) from exc
    return "nonempty", entries, manifest


def _refuse_ineligible(
    state: str,
    entries: list[str],
    manifest: SourceReferenceManifest | None,
    *,
    target: Path,
    namespace: str,
) -> None:
    if state in ("absent", "empty", "repo-root-git-only"):
        return
    if state == "file":
        raise EmptySetupError(
            f"the creation target {target} is an existing file; choose an "
            "absent or empty directory inside the selected worktree "
            "(spec 0010 §2.2)"
        )
    control_present = _CONTROL_FILE_NAME in entries
    if manifest is not None:
        if manifest.namespace == namespace and control_present:
            raise EmptySetupError(
                f"an adopted managed Knowledge Base already exists at {target} "
                f"(namespace {manifest.namespace!r}); continue with "
                f"'setup {target} --journey' without --create-empty — a "
                "created or existing Knowledge Base is never reinitialized "
                "(spec 0010 §2.2)",
                code="invalid_empty_setup",
            )
        raise EmptySetupError(
            f"the creation target {target} already carries Source Reference "
            f"Manifest state (namespace {manifest.namespace!r}"
            + ("" if control_present else " without a Control File")
            + f") that does not match an empty creation for namespace "
            f"{namespace!r}; select the existing managed Knowledge Base or "
            "resolve the incomplete/conflicting target manually — setup never "
            "overwrites or reinterprets it (spec 0010 §2.2)",
            code="invalid_empty_setup",
        )
    raise EmptySetupError(
        f"the creation target {target} is not empty"
        + (f" (existing entries: {', '.join(entries[:8])})" if entries else "")
        + "; existing content without a valid Source Reference Manifest "
        "requires the explicit Git-authoring adoption contract (select the "
        "namespace and review source identities and exact bindings) or a "
        "different authoring location — setup never creates an empty manifest "
        "over existing content or guesses private history (spec 0010 §2.2)",
        code="adoption_required",
    )


def plan_empty_setup(
    *,
    target: Path,
    namespace: str,
    profile_path: Path,
    new_profile_payload: str | None,
    submission: dict,
    project_dir: Path,
    agents_enabled: bool,
    env_bytes: bytes,
    agents_bytes: bytes | None,
    skill: dict | None,
) -> EmptySetupPlan:
    """Validate every input and build the one recheckable action list.

    No file, directory or configuration is written here; the prospective
    manifest is validated in memory only (plan J5a).
    """
    if not namespace or namespace != namespace.strip():
        raise EmptySetupError(
            "the Knowledge Base Namespace must be an explicit non-empty "
            "string; it is never generated or taken from an unrelated profile "
            "(spec 0010 §2.2)"
        )
    target = target.resolve()
    facts = discover_authoring_location(target)
    state, entries, manifest = _target_state(target, facts.repository_root)
    _refuse_ineligible(state, entries, manifest, target=target, namespace=namespace)
    # R3: selected project guidance/skill destinations must not land inside
    # the Knowledge Base itself — their Markdown would break KB validation.
    # Refused during planning with actionable guidance; the settled page
    # scanner and the requested actions stay untouched.
    guidance: list[tuple[str, Path]] = []
    if agents_enabled:
        guidance.append(("the setup-generated AGENTS.md", project_dir / "AGENTS.md"))
    if skill is not None:
        guidance.append(("the selected agent skill destination", Path(skill["target"])))
    for label, destination in guidance:
        if destination == target or destination.is_relative_to(target):
            if destination.name == "AGENTS.md":
                raise EmptySetupError(
                    f"{label} at {destination} would land inside the selected "
                    f"Knowledge Base {target} and break its own validation "
                    "(spec 0010 §2.2): run setup from a project directory "
                    "outside the Knowledge Base, or pass --no-agents-md"
                )
            raise EmptySetupError(
                f"{label} at {destination} would land inside the selected "
                f"Knowledge Base {target} and its Markdown would break KB "
                "validation (spec 0010 §2.2): choose a project directory "
                "outside the Knowledge Base, a user-level skill target "
                "(--skill-scope user or an --agent home installation), or "
                "drop the skill selection"
            )
    if new_profile_payload is not None:
        # Interactive collection produced the declaration as text: validate
        # it in memory — the file itself is written only inside apply.
        try:
            payload_object = json.loads(new_profile_payload)
        except json.JSONDecodeError as exc:
            raise EmptySetupError(
                f"the collected private profile declaration is not valid JSON: {exc}"
            ) from exc
        profile = _declaration_from_object(
            payload_object,
            repo_root=facts.repository_root,
            namespace=namespace,
        )
    else:
        profile = _load_declaration(
            profile_path, repo_root=facts.repository_root, namespace=namespace
        )
    if profile.retention != "required":
        # Same rule as the adopted journey: the managed journey requires
        # retention 'required' (spec 0010 §2.1/§2.2).
        raise EmptySetupError(
            "the guided managed journey requires retention 'required' in the "
            "selected private profile (spec 0010 §2.1); authoring and handoff "
            "with 'disabled' retention stay available through the explicit "
            "lower-level commands"
        )
    # Prospective manifest validation without any temporary file (§2.2).
    manifest_bytes = serialize_source_reference_manifest(
        SourceReferenceManifest(version=SOURCE_REFERENCE_MANIFEST_VERSION, namespace=namespace)
    )
    parse_source_reference_manifest(manifest_bytes)
    env_path = project_dir / ".env"
    agents_path = project_dir / "AGENTS.md"
    actions: list[SetupAction] = []
    if state == "absent":
        actions.append(SetupAction("create-directory", str(target), None, "authoring location"))
    actions.append(
        SetupAction(
            "create-control-file",
            str(target / _CONTROL_FILE_NAME),
            None,
            "seeded Control File",
        )
    )
    actions.append(
        SetupAction(
            "create-manifest",
            str(target / SOURCE_REFERENCE_MANIFEST_BASENAME),
            hashlib.sha256(manifest_bytes).hexdigest(),
            "empty Source Reference Manifest (v1)",
        )
    )
    if new_profile_payload is not None:
        actions.append(
            SetupAction(
                "create-profile",
                str(profile_path),
                hashlib.sha256(new_profile_payload.encode("utf-8")).hexdigest(),
                "private profile (stays outside versioned content)",
            )
        )
    submission_detail = "/".join(str(submission.get(key)) for key in ("mode", "remote", "branch"))
    actions.append(
        SetupAction(
            "update-env",
            str(env_path),
            hashlib.sha256(env_bytes).hexdigest(),
            f"journey settings ({submission_detail})",
        )
    )
    if agents_enabled and agents_bytes is not None:
        actions.append(
            SetupAction(
                "update-agents-md",
                str(agents_path),
                hashlib.sha256(agents_bytes).hexdigest(),
                "setup guidance section",
            )
        )
    if skill is not None:
        actions.append(
            SetupAction("install-skill", skill["target"], None, f"{skill['intent']} skill bundle")
        )
    fingerprints = {
        "target_state": state,
        "target_entries": entries,
        "profile_file": _file_digest(profile_path) or "absent",
        "env": _file_digest(env_path) or "absent",
        "agents_md": _file_digest(agents_path) or "absent",
    }
    skill_fingerprint: dict | None = None
    if skill is not None:
        from lumio_wiki.skill import SKILL_FILENAME

        skill_fingerprint = {
            **skill,
            "skill_file": _file_digest(Path(skill["target"]) / SKILL_FILENAME) or "absent",
        }
    digest_payload = {
        "schema_version": EMPTY_SETUP_SCHEMA_VERSION,
        "operation": "setup_empty",
        "authoring": {
            "repository_root": str(facts.repository_root),
            "branch": facts.branch,
            "subtree": facts.subtree,
            "current_commit": facts.current_commit,
        },
        "namespace": namespace,
        "actions": [
            {
                "kind": action.kind,
                "path": action.path,
                "content_sha256": action.content_sha256,
                "detail": action.detail,
            }
            for action in actions
        ],
        "private_declaration": _declaration_view(profile),
        "input_fingerprints": fingerprints,
        "skill": skill_fingerprint,
    }
    next_actions = [
        "stage and commit the created files with native Git — setup never "
        "commits, and the first Authoring Revision is created explicitly",
        f"run: lumio-wiki validate {target}",
        "add your first original with 'lumio-wiki extract <file> --output "
        "<private-dir>' when authoring begins",
    ]
    return EmptySetupPlan(
        target=target,
        namespace=namespace,
        profile_path=profile_path,
        new_profile_payload=new_profile_payload,
        submission=dict(submission),
        project_dir=project_dir,
        agents_enabled=agents_enabled,
        skill=dict(skill) if skill is not None else None,
        env_bytes=env_bytes,
        agents_bytes=agents_bytes,
        facts=facts,
        actions=actions,
        manifest_bytes=manifest_bytes,
        next_actions=next_actions,
        setup_digest=_canonical_digest(digest_payload),
    )


def recheck_plan(
    plan: EmptySetupPlan,
    *,
    env_bytes: bytes,
    agents_bytes: bytes | None,
    skill: dict | None,
) -> None:
    """Rebuild the plan from fresh facts and refuse drift before apply.

    Changed branch, target occupancy, profile bytes, rendered configuration
    bytes or skill destination state each require a new preview and
    confirmation — never silent substitution (spec 0010 §2.2, R2/R4).
    """
    try:
        fresh = plan_empty_setup(
            target=plan.target,
            namespace=plan.namespace,
            profile_path=plan.profile_path,
            new_profile_payload=plan.new_profile_payload,
            submission=plan.submission,
            project_dir=plan.project_dir,
            agents_enabled=plan.agents_enabled,
            env_bytes=env_bytes,
            agents_bytes=agents_bytes,
            skill=skill,
        )
    except (EmptySetupError, PrivateProfileError) as exc:
        raise EmptySetupError(
            f"the selected authoring location or inputs changed after the "
            f"preview ({exc}); re-run the preview for a new confirmation "
            "(spec 0010 §2.2)",
            code="setup_target_changed",
        ) from exc
    if fresh.setup_digest != plan.setup_digest:
        raise EmptySetupError(
            "the selected authoring location or inputs changed after the "
            "preview; re-run the preview for a new confirmation "
            "(spec 0010 §2.2)",
            code="setup_target_changed",
        )


def apply_plan(
    plan: EmptySetupPlan,
    *,
    write_env,
    write_agents,
    install_skill,
) -> list[str]:
    """Perform exactly the confirmed actions in order, reporting honestly.

    An I/O failure reports the operation-owned residue already written and
    never removes or overwrites pre-existing operator content; a retry goes
    through a new preview and never reinitializes (spec 0010 §2.2).
    """
    from lumio_wiki.knowledge_base import seeded_control_file, write_control_file

    written: list[str] = []
    current: SetupAction | None = None
    try:
        for action in plan.actions:
            current = action
            path = Path(action.path)
            if action.kind == "create-directory":
                path.mkdir(parents=True, exist_ok=True)
                written.append(action.path)
            elif action.kind == "create-control-file":
                write_control_file(path.parent, seeded_control_file())
                written.append(action.path)
            elif action.kind == "create-manifest":
                path.write_bytes(plan.manifest_bytes)
                written.append(action.path)
            elif action.kind == "create-profile":
                # Same care as the adopted wizard route: create-only, never
                # following or replacing an existing file.
                if plan.new_profile_payload is None:  # pragma: no cover - action guard
                    raise EmptySetupError(
                        "internal error: profile creation action without a collected declaration"
                    )
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    descriptor = os.open(
                        str(path),
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                    )
                except FileExistsError as exc:
                    raise EmptySetupError(
                        f"the private profile path {path} became occupied "
                        "before apply; nothing was overwritten — re-run the "
                        "preview (spec 0010 §2.2)",
                        code="setup_target_changed",
                    ) from exc
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(plan.new_profile_payload + "\n")
                written.append(action.path)
            elif action.kind == "update-env":
                write_env()
                written.append(action.path)
            elif action.kind == "update-agents-md":
                write_agents()
                written.append(action.path)
            elif action.kind == "install-skill":
                # The skill step reports its own honest outcome (kept/SKIPPED)
                # through the shared setup mechanism.
                install_skill()
    except OSError as exc:
        failing = (
            f"{current.kind} at {current.path}" if current is not None else "an unknown action"
        )
        raise EmptySetupError(
            f"the empty setup stopped on an I/O failure "
            f"({exc.strerror or exc}) while performing {failing}; "
            f"operation-owned paths already written: {', '.join(written) or 'none'}; "
            "the failing path may hold a PARTIAL file — inspect it; "
            "pre-existing operator content outside these action paths was "
            "not modified; resolve the failure and re-run the preview (a "
            "retry never reinitializes a created Knowledge Base) "
            "(spec 0010 §2.2)",
            code="setup_incomplete",
        ) from exc
    return written


def build_envelope(plan: EmptySetupPlan, *, phase: str) -> dict:
    """The creation-only versioned envelope (exact fields frozen in J5a)."""
    return {
        "schema_version": EMPTY_SETUP_SCHEMA_VERSION,
        "ok": True,
        "operation": "setup_empty",
        "phase": phase,
        "ready": True,
        "setup_digest": plan.setup_digest,
        "authoring": {
            "repository_root": str(plan.facts.repository_root),
            "branch": plan.facts.branch,
            "subtree": plan.facts.subtree,
            "current_commit": plan.facts.current_commit,
            "unborn": plan.facts.current_commit is None,
        },
        "namespace": plan.namespace,
        "actions": [
            {
                "kind": action.kind,
                "path": action.path,
                "content_sha256": action.content_sha256,
                "detail": action.detail,
            }
            for action in plan.actions
        ],
        "blockers": [],
        "next_actions": list(plan.next_actions),
    }
