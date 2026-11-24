"""Owner operations: quiesced backup and whole-data-root restore for one workspace.

Backup copies every durable role — SQLite operational state (one consistent
snapshot, committed WAL frames included), the private operational tree, the
authoring Git repository, the private profile and its source registry plus
artifact store, and the published destination — while holding the same
mutation locks an activation takes. A private S3 artifact store is backed up
through its supported identity-oriented APIs: exact registered versions and
bound private records are enumerated (never a bucket-wide scan), retained
bytes are copied digest-verified, and a failed required copy aborts without a
final manifest. Restore materializes a backup in a fresh data root, re-links
moved task worktrees, rebases only mutable configuration — a remote-origin
backup materializes originals into a NEW LOCAL store instead of copying the
remote connection — invalidates outstanding review actions and browser
sessions, and returns the launch configuration rebased onto the new root.
Historical immutable identities travel verbatim. Credentials are
re-established through the operator's secret mechanism, never exported into
content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec
from lumio_wiki.artifact_store import (
    ArtifactStoreError,
    ArtifactUnavailable,
    LocalDirectoryArtifactStore,
)
from lumio_wiki.git_authoring import (
    PRIVATE_OPERATIONS_DIR,
    PublicationReceipt,
    build_restored_root_record,
    resolve_repository,
)
from lumio_wiki.knowledge_base import KnowledgeBaseError
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.mutation import mutation_lock
from lumio_wiki.private_profile import (
    PrivateS3Connection,
    load_private_profile,
    resolve_private_profile,
)

from .app import WorkspaceConfig

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from lumio_wiki.artifact_store import SourceArtifactStore
    from lumio_wiki.source_registry import SourceRegistry

_STATE = "state.sqlite3"
_OPERATION_LOCKS = "operation-locks"
_PRIVATE = "private"
_AUTHORING_REPO = "authoring-repo"
_PUBLISHED = "published"
_PROFILE = "profile.json"
_REGISTRY = "registry"
_ARTIFACTS = "artifacts"
_ANALYTICS_PROJECT = "analytics-project"
_ANALYTICS_BINDINGS = "analytics-bindings.json"
_STORE = "store"
_MANIFEST = "manifest.json"

#: Backup manifest schema versions this module reads. Version 1 is the
#: historical local-store layout (``artifacts/`` directory copy); version 2
#: records a remote artifact store materialized under ``store/`` with an
#: exact inventory.
_SUPPORTED_MANIFEST_SCHEMAS = (1, 2)


class OperationsError(ValueError):
    pass


@dataclass(frozen=True)
class WorkspaceLayout:
    workspace_id: str
    state_path: Path
    private_root: Path
    authoring_repo: Path
    authoring_subtree: str
    published_path: Path
    profile_path: Path
    registry_root: Path
    artifact_root: Path | None
    analytics_project: Path | None
    #: True when the analytics project IS the authoring repository — one
    #: physical Git working tree hosting the knowledge subtree and the
    #: Ariadne project (spec0035 §2). Backup copies it once.
    shared_analytics_root: bool
    analytics_bindings: Path | None
    #: The resolved adapters (registry plus artifact store) and whether the
    #: artifact store is remote. A remote store has no local root; backup
    #: enumerates it through supported store APIs instead of copying a tree.
    registry: SourceRegistry | None
    artifact_store: SourceArtifactStore | None
    remote_artifacts: bool

    @classmethod
    def from_config(cls, config: WorkspaceConfig) -> WorkspaceLayout:
        if config.authoring_path is None or config.private_profile_path is None:
            raise OperationsError("backup requires an authoring-enabled workspace")
        repo, subtree = resolve_repository(config.authoring_path)
        profile = load_private_profile(config.private_profile_path, kb_root=config.authoring_path)
        resources = resolve_private_profile(
            profile, kb_root=config.authoring_path, needs=frozenset({"registry", "artifacts"})
        )
        registry_root = getattr(resources.source_registry, "root", None)
        remote_artifacts = isinstance(profile.artifact_store, PrivateS3Connection)
        artifact_root = (
            None if remote_artifacts else getattr(resources.artifact_store, "root", None)
        )
        if registry_root is None or (artifact_root is None and not remote_artifacts):
            raise OperationsError(
                "the private profile must resolve a source registry and artifact store"
            )
        analytics_project = (
            Path(config.analytics_project_path)
            if config.analytics_project_path is not None
            else None
        )
        return cls(
            workspace_id=config.workspace_id,
            state_path=Path(config.state_path),
            private_root=Path(config.operational_root),
            authoring_repo=repo,
            authoring_subtree=subtree,
            published_path=Path(config.published_path),
            profile_path=Path(config.private_profile_path),
            registry_root=Path(registry_root),
            artifact_root=None if artifact_root is None else Path(artifact_root),
            analytics_project=analytics_project,
            shared_analytics_root=(
                analytics_project is not None
                and analytics_project.resolve() == Path(repo).resolve()
            ),
            analytics_bindings=(
                Path(config.analytics_source_bindings_path)
                if config.analytics_source_bindings_path is not None
                else None
            ),
            registry=resources.source_registry,
            artifact_store=resources.artifact_store,
            remote_artifacts=remote_artifacts,
        )


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_state_database(source: Path, target: Path) -> None:
    """Copy SQLite as one consistent snapshot, committed WAL frames included.

    The online backup API reads the database through its journal/WAL, so the
    snapshot contains every committed transaction even when sidecar files
    exist. No lost sessions/tasks; the source is never written.
    """
    if not source.is_file():
        raise FileNotFoundError(f"the workspace state database is missing: {source}")
    connection = sqlite3.connect(source)
    try:
        snapshot = sqlite3.connect(target)
        try:
            connection.backup(snapshot)
        finally:
            snapshot.close()
    finally:
        connection.close()


def _store_record_path(store_dir: Path, category: str, version: str) -> Path:
    # The store adapters validate this exact label shape at every read/write;
    # confine defensively anyway so a hostile label can never escape.
    if (
        not version
        or version in {".", ".."}
        or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for ch in version)
    ):
        raise OperationsError("the artifact store reported an invalid version label")
    return store_dir / category / f"{version}.json"


def _write_store_record(store_dir: Path, category: str, version: str, raw: bytes) -> None:
    path = _store_record_path(store_dir, category, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _backup_remote_store(layout: WorkspaceLayout, store_dir: Path) -> dict:
    """Materialize a remote artifact store into ``store_dir`` (schema 2).

    Enumerates exactly what the registry records and what the store itself
    reports as bound versions — never a bucket-wide scan. Retained original
    bytes are copied digest-verified (the adapter re-verifies on read); a
    required version whose bytes are unavailable, denied, or corrupt aborts
    the backup before any manifest is written. Each bound version's binding
    manifest is required; publication records and activation receipts are
    copied when the store holds them, and their absence is recorded honestly.
    Versions the registry marks unretained are inventoried as unretained —
    never treated as corruption.
    """
    registry = layout.registry
    artifact_store = layout.artifact_store
    if registry is None or artifact_store is None:
        raise OperationsError(
            "the private profile must resolve a source registry and artifact store"
        )
    retained: list[dict] = []
    unretained: list[dict] = []
    artifacts_dir = store_dir / "artifacts"
    for source in registry.list():
        for version in source.versions:
            if not version.artifact_available:
                unretained.append(
                    {"source_id": source.source_id, "content_hash": version.content_hash}
                )
                continue
            try:
                raw = artifact_store.get_artifact(
                    source_id=source.source_id, content_hash=version.content_hash
                )
            except ArtifactStoreError as exc:
                raise OperationsError(
                    "backup aborted: the retained original for source "
                    f"{source.source_id!r} ({version.content_hash}) could not be "
                    "copied from the artifact store; required bytes are unavailable, "
                    "denied, or failed verification"
                ) from exc
            artifact_path = artifacts_dir / source.source_id / version.content_hash
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(raw)
            retained.append(
                {
                    "source_id": source.source_id,
                    "content_hash": version.content_hash,
                    "size": len(raw),
                    "content_type": version.content_type,
                    "filename": version.filename,
                }
            )
    store_versions: list[dict] = []
    for version in artifact_store.list_binding_versions():
        try:
            binding = artifact_store.get_binding_manifest(version)
        except ArtifactStoreError as exc:
            raise OperationsError(
                f"backup aborted: the binding manifest for Published Version "
                f"{version!r} could not be copied from the artifact store; bound "
                "private records are required"
            ) from exc
        _write_store_record(store_dir, "bindings", version, binding)
        entry = {
            "version": version,
            "publication_record": False,
            "activation_receipt": False,
        }
        for category, flag in (
            ("publications", "publication_record"),
            ("activations", "activation_receipt"),
        ):
            try:
                raw = getattr(artifact_store, f"get_{flag}")(version)
            except ArtifactUnavailable:
                continue
            except ArtifactStoreError as exc:
                raise OperationsError(
                    f"backup aborted: the {category.removesuffix('s')} record for "
                    f"Published Version {version!r} could not be copied from the "
                    "artifact store"
                ) from exc
            _write_store_record(store_dir, category, version, raw)
            entry[flag] = True
        store_versions.append(entry)
    return {
        "artifact_store": "s3",
        "retained_source_artifacts": retained,
        "unretained_source_versions": unretained,
        "store_versions": store_versions,
    }


def _restore_store_records(backup_root: Path, target_root: Path, manifest: dict) -> None:
    """Materialize a schema-2 backup into a NEW LOCAL store (supported APIs).

    Every artifact is re-uploaded through the local adapter's create-only,
    digest-verified seam; record bytes replay verbatim, so historical
    immutable identities travel exactly as backed up. The remote endpoint is
    deliberately not contacted: reconnecting it is an explicit operator step.
    """
    store = LocalDirectoryArtifactStore(target_root / _ARTIFACTS)
    store_dir = backup_root / _STORE
    for entry in manifest.get("retained_source_artifacts", []):
        raw = (store_dir / "artifacts" / entry["source_id"] / entry["content_hash"]).read_bytes()
        store.put_artifact(
            source_id=entry["source_id"],
            content_hash=entry["content_hash"],
            raw_bytes=raw,
            content_type=entry.get("content_type"),
            filename=entry.get("filename"),
        )
    for entry in manifest.get("store_versions", []):
        version = entry["version"]
        store.put_binding_manifest(
            version, _store_record_path(store_dir, "bindings", version).read_bytes()
        )
        if entry.get("publication_record"):
            store.put_publication_record(
                version, _store_record_path(store_dir, "publications", version).read_bytes()
            )
        if entry.get("activation_receipt"):
            store.put_activation_receipt(
                version, _store_record_path(store_dir, "activations", version).read_bytes()
            )


def _environment_file_line(name: str, value: Path) -> str:
    """Escape for systemd's documented double-quoted EnvironmentFile parsing."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'{name}="{escaped}"'


def quiesced_backup(config: WorkspaceConfig, backup_root: Path) -> Path:
    """Copy the whole data root under the activation mutation locks.

    The single-process deployment backs up with the service stopped; the lock
    set matches review activation, so an in-flight native mutation either
    drains before the copy or blocks it.
    """
    layout = WorkspaceLayout.from_config(config)
    backup_root = Path(backup_root)
    staging = backup_root.with_name(backup_root.name + ".partial")
    if backup_root.exists() or staging.exists():
        raise OperationsError("the backup destination already exists")
    staging.mkdir(parents=True)
    lock_resources: list[Path] = [
        layout.private_root / "activation",
        layout.published_path,
        layout.registry_root,
    ]
    if layout.artifact_root is not None:
        lock_resources.append(layout.artifact_root)
    with mutation_lock(*lock_resources):
        _copy_state_database(layout.state_path, staging / _STATE)
        if (layout.state_path.parent / _OPERATION_LOCKS).is_dir():
            shutil.copytree(layout.state_path.parent / _OPERATION_LOCKS, staging / _OPERATION_LOCKS)
        shutil.copytree(layout.private_root, staging / _PRIVATE)
        shutil.copytree(layout.authoring_repo, staging / _AUTHORING_REPO)
        shutil.copytree(layout.published_path, staging / _PUBLISHED)
        _copy_file(layout.profile_path, staging / _PROFILE)
        shutil.copytree(layout.registry_root, staging / _REGISTRY)
        inventory: dict = {}
        if layout.remote_artifacts:
            inventory = _backup_remote_store(layout, staging / _STORE)
        elif layout.artifact_root is not None:
            shutil.copytree(layout.artifact_root, staging / _ARTIFACTS)
        else:
            raise OperationsError(
                "the private profile must resolve a source registry and artifact store"
            )
        if layout.analytics_project is not None and not layout.shared_analytics_root:
            shutil.copytree(layout.analytics_project, staging / _ANALYTICS_PROJECT)
        if layout.analytics_bindings is not None:
            _copy_file(layout.analytics_bindings, staging / _ANALYTICS_BINDINGS)
        manifest = {
            "schema_version": 2 if layout.remote_artifacts else 1,
            "workspace_id": layout.workspace_id,
            "authoring_subtree": layout.authoring_subtree,
            **inventory,
        }
        if layout.shared_analytics_root:
            manifest["shared_analytics_root"] = True
        (staging / _MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    staging.rename(backup_root)
    return backup_root


def _relink_registered_worktrees(repo_root: Path, worktrees_root: Path) -> None:
    """Relink task worktrees copied to a new data root (git worktree repair)."""
    registered_root = repo_root / ".git" / "worktrees"
    if not registered_root.is_dir():
        return
    for registered in sorted(registered_root.iterdir()):
        if not registered.is_dir():
            continue
        moved = worktrees_root / registered.name
        if not moved.is_dir():
            shutil.rmtree(registered)
            continue
        (registered / "gitdir").write_text(f"{moved / '.git'}\n", encoding="utf-8")
        (moved / ".git").write_text(f"gitdir: {registered}\n", encoding="utf-8")


def _relink_shared_root_worktrees(repo_root: Path, worktree_roots: list[Path]) -> None:
    """Relink BOTH worktree roles of one shared authoring/analytics repository.

    The same registrations serve authoring task worktrees under the private
    tree and analytics proposal worktrees under ``.ariadne/worktrees``
    inside the repository. Matching by name across each role's root keeps
    every registration whose worktree directory traveled with the backup;
    a single-root match would destroy the other role's registrations.
    """
    registered_root = repo_root / ".git" / "worktrees"
    if not registered_root.is_dir():
        return
    for registered in sorted(registered_root.iterdir()):
        if not registered.is_dir():
            continue
        moved = next(
            (
                root / registered.name
                for root in worktree_roots
                if (root / registered.name).is_dir()
            ),
            None,
        )
        if moved is None:
            shutil.rmtree(registered)
            continue
        (registered / "gitdir").write_text(f"{moved / '.git'}\n", encoding="utf-8")
        (moved / ".git").write_text(f"gitdir: {registered}\n", encoding="utf-8")


def _rebase_profile(target_root: Path, schema: int) -> None:
    """Rebase mutable resource paths; never re-point a remote-origin backup.

    A schema-2 backup materializes its originals into the fresh local store:
    the remote connection is deliberately not copied into the restored
    profile, because reconnecting/migrating to it is an explicit operator
    step, never an implied consequence of restore.
    """
    profile_path = target_root / _PROFILE
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if isinstance(profile.get("source_registry"), str):
        profile["source_registry"] = str(target_root / _REGISTRY)
    store = profile.get("artifact_store")
    if schema >= 2:
        profile["artifact_store"] = {"kind": "local", "root": str(target_root / _ARTIFACTS)}
    elif isinstance(store, dict) and isinstance(store.get("root"), str):
        store["root"] = str(target_root / _ARTIFACTS)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def _invalidate_restored_actions(state_path: Path) -> None:
    """Outstanding approvals never survive a restore; sessions sign in again."""
    with sqlite3.connect(state_path) as connection:
        connection.execute("DELETE FROM review_actions WHERE status IN ('issued', 'pending')")
        connection.execute("DELETE FROM browser_sessions")


def _refuse_unfinished_backup_activation(backup_root: Path) -> None:
    """Preflight the backup BEFORE the target exists.

    A backup whose active pointer names an imported receipt whose activation
    never completed is unsupported by this bounded restore: the owner
    recovers that state at the source root and takes a new backup. Refusing
    here leaves no target and no partially authorized state.
    """
    published = backup_root / _PUBLISHED
    try:
        pointer = PublishedFilesystemLocation(published).read_pointer()
    except KnowledgeBaseError as exc:
        raise OperationsError(f"the backup's publication pointer is unreadable: {exc}") from exc
    if pointer is None:
        return
    receipt_path = published / PRIVATE_OPERATIONS_DIR / "receipts" / f"{pointer}.json"
    if not receipt_path.is_file():
        return  # legacy Published Versions carry no Git-authoring receipt
    try:
        receipt = msgspec.json.decode(receipt_path.read_bytes(), type=PublicationReceipt)
    except msgspec.DecodeError as exc:
        raise OperationsError(
            f"the backup's admission receipt for {pointer!r} is malformed: {exc}"
        ) from exc
    if not receipt.activated:
        raise OperationsError(
            f"the backup's active Published Version {pointer!r} has no completed "
            "activation record; recover it at the source root and take a new "
            "backup before restoring"
        )


def _write_restored_root_record(backup_root: Path, target_root: Path, manifest: dict) -> None:
    """Stamp the completed restore with its private, live-target-bound record.

    Binds the exact resolved destination and the exact imported
    version/receipt-byte digests; workspace/time/backup-manifest digest are
    provenance, not substitute authorization.
    """
    published = target_root / _PUBLISHED
    receipts_dir = published / PRIVATE_OPERATIONS_DIR / "receipts"
    imported_versions: dict[str, str] = {}
    if receipts_dir.is_dir():
        for receipt_path in sorted(receipts_dir.glob("*.json")):
            imported_versions[receipt_path.stem] = hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest()
    record = build_restored_root_record(
        destination=published,
        workspace_id=str(manifest["workspace_id"]),
        restored_at=datetime.now(UTC).isoformat(),
        source_backup_manifest_sha256=hashlib.sha256(
            (backup_root / _MANIFEST).read_bytes()
        ).hexdigest(),
        imported_versions=imported_versions,
    )
    record_path = published / PRIVATE_OPERATIONS_DIR / "restore.json"
    record_path.parent.mkdir(exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def restore(backup_root: Path, target_root: Path, config: WorkspaceConfig) -> WorkspaceConfig:
    """Materialize a backup in a fresh data root and rebase the configuration.

    ``config`` carries the operator's launch facts (identity, external URL,
    publication pin); only durable data and its paths come from the backup.
    A backup whose manifest records ``shared_analytics_root`` materializes
    the ONE authoring/analytics repository once and rebases the analytics
    project onto that restored checkout (spec0035 §2/§5 recovery).
    """
    backup_root = Path(backup_root)
    target_root = Path(target_root)
    if not target_root.is_absolute():
        raise OperationsError("the restore target must be an absolute path")
    manifest = json.loads((backup_root / _MANIFEST).read_text(encoding="utf-8"))
    schema = manifest.get("schema_version")
    if schema not in _SUPPORTED_MANIFEST_SCHEMAS:
        raise OperationsError(
            "unsupported backup format; this restore reads manifest schema versions "
            + ", ".join(str(version) for version in _SUPPORTED_MANIFEST_SCHEMAS)
        )
    if manifest.get("workspace_id") != config.workspace_id:
        raise OperationsError("the backup belongs to a different workspace")
    shared = bool(manifest.get("shared_analytics_root"))
    if target_root.exists() and any(target_root.iterdir()):
        raise OperationsError("the restore target must be a new or empty data root")
    _refuse_unfinished_backup_activation(backup_root)
    target_root.mkdir(parents=True, exist_ok=True)

    _copy_file(backup_root / _STATE, target_root / _STATE)
    if (backup_root / _OPERATION_LOCKS).is_dir():
        shutil.copytree(backup_root / _OPERATION_LOCKS, target_root / _OPERATION_LOCKS)
    shutil.copytree(backup_root / _PRIVATE, target_root / _PRIVATE)
    shutil.copytree(backup_root / _AUTHORING_REPO, target_root / _AUTHORING_REPO)
    shutil.copytree(backup_root / _PUBLISHED, target_root / _PUBLISHED)
    _copy_file(backup_root / _PROFILE, target_root / _PROFILE)
    shutil.copytree(backup_root / _REGISTRY, target_root / _REGISTRY)
    if schema >= 2:
        _restore_store_records(backup_root, target_root, manifest)
    else:
        shutil.copytree(backup_root / _ARTIFACTS, target_root / _ARTIFACTS)
    if config.analytics_project_path is not None and not shared:
        if not (backup_root / _ANALYTICS_PROJECT).is_dir():
            raise OperationsError("the configured analytics project is absent from this backup")
        shutil.copytree(backup_root / _ANALYTICS_PROJECT, target_root / _ANALYTICS_PROJECT)
    if (
        config.analytics_source_bindings_path is not None
        and (backup_root / _ANALYTICS_BINDINGS).is_file()
    ):
        _copy_file(backup_root / _ANALYTICS_BINDINGS, target_root / _ANALYTICS_BINDINGS)

    if shared:
        # One physical repository hosts the knowledge subtree and the
        # Ariadne project: relink both worktree roles against
        # the single restored checkout instead of splitting the repo into
        # independently advancing copies.
        _relink_shared_root_worktrees(
            target_root / _AUTHORING_REPO,
            [
                target_root / _PRIVATE / "worktrees",
                target_root / _AUTHORING_REPO / ".ariadne" / "worktrees",
            ],
        )
    else:
        _relink_registered_worktrees(
            target_root / _AUTHORING_REPO, target_root / _PRIVATE / "worktrees"
        )
        if config.analytics_project_path is not None:
            _relink_registered_worktrees(
                target_root / _ANALYTICS_PROJECT,
                target_root / _ANALYTICS_PROJECT / ".ariadne" / "worktrees",
            )
    # The restored proposal records name the old project path, so an active draft can
    # no longer be read; retire it (its outstanding request is invalidated just below).
    analytics_root = (
        target_root / _AUTHORING_REPO
        if shared
        else target_root / _ANALYTICS_PROJECT
        if config.analytics_project_path is not None
        else None
    )
    if analytics_root is not None:
        from ariadne import draft  # analytics extra; the base package stays independent

        draft.retire_stale(analytics_root)
    _rebase_profile(target_root, schema)
    _invalidate_restored_actions(target_root / _STATE)
    _write_restored_root_record(backup_root, target_root, manifest)
    return replace(
        config,
        state_path=target_root / _STATE,
        authoring_path=target_root / _AUTHORING_REPO / str(manifest["authoring_subtree"]),
        private_profile_path=target_root / _PROFILE,
        private_root=target_root / _PRIVATE,
        published_path=target_root / _PUBLISHED,
        analytics_project_path=(
            (target_root / _AUTHORING_REPO if shared else target_root / _ANALYTICS_PROJECT)
            if config.analytics_project_path is not None
            else None
        ),
        analytics_source_bindings_path=(
            target_root / _ANALYTICS_BINDINGS
            if config.analytics_source_bindings_path is not None
            else None
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lumio_workspace.operations")
    commands = parser.add_subparsers(dest="command", required=True)
    backup_command = commands.add_parser("backup", help="copy the quiesced data root")
    backup_command.add_argument("--backup-root", required=True)
    restore_command = commands.add_parser("restore", help="materialize a backup")
    restore_command.add_argument("--backup-root", required=True)
    restore_command.add_argument("--target-root", required=True)
    args = parser.parse_args(argv)
    config = WorkspaceConfig.from_env()
    if args.command == "backup":
        print(f"backup={quiesced_backup(config, Path(args.backup_root))}")
    else:
        restored = restore(Path(args.backup_root), Path(args.target_root), config)
        print(f"state_path={restored.state_path}")
        print(f"authoring_path={restored.authoring_path}")
        print(f"published_path={restored.published_path}")
        print(f"private_profile_path={restored.private_profile_path}")
        print(f"private_root={restored.private_root}")
        if (
            restored.analytics_project_path is not None
            or restored.analytics_source_bindings_path is not None
        ):
            print("# Paste into an interactive shell:")
            if restored.analytics_project_path is not None:
                print(
                    "export LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH="
                    + shlex.quote(str(restored.analytics_project_path))
                )
            if restored.analytics_source_bindings_path is not None:
                print(
                    "export LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS="
                    + shlex.quote(str(restored.analytics_source_bindings_path))
                )
            print("# systemd EnvironmentFile= lines (no export prefix):")
            if restored.analytics_project_path is not None:
                print(
                    _environment_file_line(
                        "LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH", restored.analytics_project_path
                    )
                )
            if restored.analytics_source_bindings_path is not None:
                print(
                    _environment_file_line(
                        "LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS",
                        restored.analytics_source_bindings_path,
                    )
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
