"""Private workspace membership state; tenant membership grants no access."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    object_id: str


class WorkspaceState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memberships (
                    workspace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, tenant_id, object_id, capability)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def grant(self, workspace_id: str, actor: Actor, capability: str = "read") -> None:
        if capability != "read":
            raise ValueError("W1 supports only the read capability")
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO memberships VALUES (?, ?, ?, ?)",
                (workspace_id, actor.tenant_id, actor.object_id, capability),
            )

    def revoke(self, workspace_id: str, actor: Actor) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM memberships WHERE workspace_id = ? "
                "AND tenant_id = ? AND object_id = ?",
                (workspace_id, actor.tenant_id, actor.object_id),
            )

    def capabilities(self, workspace_id: str, actor: Actor) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT capability FROM memberships "
                "WHERE workspace_id = ? AND tenant_id = ? AND object_id = ? ORDER BY capability",
                (workspace_id, actor.tenant_id, actor.object_id),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def permits(self, workspace_id: str, actor: Actor, capability: str = "read") -> bool:
        return capability in self.capabilities(workspace_id, actor)
