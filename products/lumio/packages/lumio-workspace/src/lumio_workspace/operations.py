"""Owner operations: quiesced backup and whole-data-root restore for one workspace.

Backup copies every durable role — SQLite operational state, the private
operational tree, the authoring Git repository, the private profile and its
source registry/artifact stores, and the published destination — while holding
the same mutation locks an activation takes. Restore materializes a backup in a
fresh data root, re-links moved task worktrees, rewrites the private profile's
resource paths, invalidates outstanding review actions and browser sessions,
and returns the launch configuration rebased onto the new root. Credentials are
re-established through the operator's secret mechanism, never exported into
content.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

from lumio_wiki.git_authoring import resolve_repository
from lumio_wiki.mutation import mutation_lock
from lumio_wiki.private_profile import load_private_profile, resolve_private_profile

from .app import WorkspaceConfig

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
_MANIFEST = "manifest.json"


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
    artifact_root: Path
    analytics_project: Path | None
    analytics_bindings: Path | None

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
        artifact_root = getattr(resources.artifact_store, "root", None)
        if registry_root is None or artifact_root is None:
            raise OperationsError(
                "the private profile must resolve a source registry and artifact store"
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
            artifact_root=Path(artifact_root),
            analytics_project=(
                Path(config.analytics_project_path)
                if config.analytics_project_path is not None
                else None
            ),
            analytics_bindings=(
                Path(config.analytics_source_bindings_path)
                if config.analytics_source_bindings_path is not None
                else None
            ),
        )


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


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
        layout.artifact_root,
    ]
    with mutation_lock(*lock_resources):
        _copy_file(layout.state_path, staging / _STATE)
        if (layout.state_path.parent / _OPERATION_LOCKS).is_dir():
            shutil.copytree(layout.state_path.parent / _OPERATION_LOCKS, staging / _OPERATION_LOCKS)
        shutil.copytree(layout.private_root, staging / _PRIVATE)
        shutil.copytree(layout.authoring_repo, staging / _AUTHORING_REPO)
        shutil.copytree(layout.published_path, staging / _PUBLISHED)
        _copy_file(layout.profile_path, staging / _PROFILE)
        shutil.copytree(layout.registry_root, staging / _REGISTRY)
        shutil.copytree(layout.artifact_root, staging / _ARTIFACTS)
        if layout.analytics_project is not None:
            shutil.copytree(layout.analytics_project, staging / _ANALYTICS_PROJECT)
        if layout.analytics_bindings is not None:
            _copy_file(layout.analytics_bindings, staging / _ANALYTICS_BINDINGS)
        (staging / _MANIFEST).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "workspace_id": layout.workspace_id,
                    "authoring_subtree": layout.authoring_subtree,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
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


def _rebase_profile(target_root: Path) -> None:
    profile_path = target_root / _PROFILE
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if isinstance(profile.get("source_registry"), str):
        profile["source_registry"] = str(target_root / _REGISTRY)
    store = profile.get("artifact_store")
    if isinstance(store, dict) and isinstance(store.get("root"), str):
        store["root"] = str(target_root / _ARTIFACTS)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def _invalidate_restored_actions(state_path: Path) -> None:
    """Outstanding approvals never survive a restore; sessions sign in again."""
    with sqlite3.connect(state_path) as connection:
        connection.execute("DELETE FROM review_actions WHERE status IN ('issued', 'pending')")
        connection.execute("DELETE FROM browser_sessions")


def restore(backup_root: Path, target_root: Path, config: WorkspaceConfig) -> WorkspaceConfig:
    """Materialize a backup in a fresh data root and rebase the configuration.

    ``config`` carries the operator's launch facts (identity, external URL,
    publication pin); only durable data and its paths come from the backup.
    """
    backup_root = Path(backup_root)
    target_root = Path(target_root)
    if not target_root.is_absolute():
        raise OperationsError("the restore target must be an absolute path")
    manifest = json.loads((backup_root / _MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("workspace_id") != config.workspace_id:
        raise OperationsError("the backup belongs to a different workspace")
    if target_root.exists() and any(target_root.iterdir()):
        raise OperationsError("the restore target must be a new or empty data root")
    target_root.mkdir(parents=True, exist_ok=True)

    _copy_file(backup_root / _STATE, target_root / _STATE)
    if (backup_root / _OPERATION_LOCKS).is_dir():
        shutil.copytree(backup_root / _OPERATION_LOCKS, target_root / _OPERATION_LOCKS)
    shutil.copytree(backup_root / _PRIVATE, target_root / _PRIVATE)
    shutil.copytree(backup_root / _AUTHORING_REPO, target_root / _AUTHORING_REPO)
    shutil.copytree(backup_root / _PUBLISHED, target_root / _PUBLISHED)
    _copy_file(backup_root / _PROFILE, target_root / _PROFILE)
    shutil.copytree(backup_root / _REGISTRY, target_root / _REGISTRY)
    shutil.copytree(backup_root / _ARTIFACTS, target_root / _ARTIFACTS)
    if config.analytics_project_path is not None:
        if not (backup_root / _ANALYTICS_PROJECT).is_dir():
            raise OperationsError("the configured analytics project is absent from this backup")
        shutil.copytree(backup_root / _ANALYTICS_PROJECT, target_root / _ANALYTICS_PROJECT)
    if (
        config.analytics_source_bindings_path is not None
        and (backup_root / _ANALYTICS_BINDINGS).is_file()
    ):
        _copy_file(backup_root / _ANALYTICS_BINDINGS, target_root / _ANALYTICS_BINDINGS)

    _relink_registered_worktrees(
        target_root / _AUTHORING_REPO, target_root / _PRIVATE / "worktrees"
    )
    if config.analytics_project_path is not None:
        _relink_registered_worktrees(
            target_root / _ANALYTICS_PROJECT,
            target_root / _ANALYTICS_PROJECT / ".ariadne" / "worktrees",
        )
    _rebase_profile(target_root)
    _invalidate_restored_actions(target_root / _STATE)
    return replace(
        config,
        state_path=target_root / _STATE,
        authoring_path=target_root / _AUTHORING_REPO / str(manifest["authoring_subtree"]),
        private_profile_path=target_root / _PROFILE,
        private_root=target_root / _PRIVATE,
        published_path=target_root / _PUBLISHED,
        analytics_project_path=(
            target_root / _ANALYTICS_PROJECT if config.analytics_project_path is not None else None
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
        if restored.analytics_project_path is not None:
            print(f"analytics_project_path={restored.analytics_project_path}")
        if restored.analytics_source_bindings_path is not None:
            print(f"analytics_source_bindings_path={restored.analytics_source_bindings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
