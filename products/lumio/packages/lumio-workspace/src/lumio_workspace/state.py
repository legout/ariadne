"""Private workspace membership state; tenant membership grants no access."""

from __future__ import annotations

import json
import sqlite3
import time
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def load_browser_session(self, session_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data, expires_at FROM browser_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            if row[1] <= int(time.time()):
                connection.execute(
                    "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
                )
                return None
        data = json.loads(row[0])
        return data if isinstance(data, dict) else None

    def save_browser_session(
        self, session_id: str, data: dict, *, expires_at: int
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO browser_sessions (session_id, data, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, "
                "expires_at = excluded.expires_at",
                (session_id, json.dumps(data), expires_at),
            )

    def delete_browser_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
            )

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
