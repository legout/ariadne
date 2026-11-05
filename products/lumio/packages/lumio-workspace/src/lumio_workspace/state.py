"""Private workspace membership state; tenant membership grants no access."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

LOCAL_TENANT_ID = "local"


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    object_id: str


@dataclass(frozen=True)
class LocalCredential:
    credential_id: str
    actor: Actor
    purpose: str
    expires_at: int


def local_actor(user_id: str) -> Actor:
    return Actor(tenant_id=LOCAL_TENANT_ID, object_id=user_id)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS local_users (
                    user_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS local_credentials (
                    credential_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
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
        if not isinstance(data, dict):
            return None
        credential_id = data.get("local_credential_id")
        if credential_id is not None:
            with self._connect() as connection:
                current = connection.execute(
                    "SELECT local_credentials.user_id FROM local_credentials "
                    "JOIN local_users USING (user_id) "
                    "WHERE credential_id = ? AND purpose = 'browser' "
                    "AND revoked_at IS NULL AND expires_at > ? AND enabled = 1",
                    (credential_id, int(time.time())),
                ).fetchone()
                actor = data.get("actor")
                if (
                    current is None
                    or not isinstance(actor, dict)
                    or actor.get("tenant_id") != LOCAL_TENANT_ID
                    or actor.get("object_id") != current[0]
                ):
                    connection.execute(
                        "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
                    )
                    return None
        return data

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

    def update_browser_session(
        self, session_id: str, data: dict, *, expires_at: int
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE browser_sessions SET data = ?, expires_at = ? WHERE session_id = ?",
                (json.dumps(data), expires_at, session_id),
            )
            return cursor.rowcount == 1

    def rotate_browser_session(
        self, old_session_id: str, new_session_id: str, data: dict, *, expires_at: int
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM browser_sessions WHERE session_id = ?", (old_session_id,)
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO browser_sessions (session_id, data, expires_at) VALUES (?, ?, ?)",
                (new_session_id, json.dumps(data), expires_at),
            )
            return True

    def delete_browser_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
            )

    def create_local_user(self, user_id: str) -> None:
        if not user_id or user_id.strip() != user_id:
            raise ValueError("local user ID must be nonempty and have no surrounding whitespace")
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO local_users VALUES (?, 1)", (user_id,))

    def disable_local_user(self, user_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE local_users SET enabled = 0 WHERE user_id = ?", (user_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError("unknown local user")

    def issue_local_credential(
        self, user_id: str, purpose: str, *, expires_at: int
    ) -> tuple[str, str]:
        if purpose not in {"api", "browser"} or expires_at <= int(time.time()):
            raise ValueError("credential purpose must be api/browser and expiry must be future")
        credential_id = secrets.token_urlsafe(12)
        token = f"{credential_id}.{secrets.token_urlsafe(32)}"
        with self._connect() as connection:
            user = connection.execute(
                "SELECT enabled FROM local_users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if user is None or user[0] != 1:
                raise ValueError("local user must exist and be enabled")
            connection.execute(
                "INSERT INTO local_credentials "
                "(credential_id, token_hash, user_id, purpose, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (credential_id, _token_hash(token), user_id, purpose, expires_at),
            )
        return credential_id, token

    def revoke_local_credential(self, credential_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE local_credentials SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE credential_id = ?",
                (int(time.time()), credential_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("unknown local credential")

    def authenticate_local_credential(
        self, token: str, *, purpose: str
    ) -> LocalCredential | None:
        credential_id, separator, secret = token.partition(".")
        if not separator or not credential_id or not secret:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT token_hash, local_credentials.user_id, purpose, expires_at "
                "FROM local_credentials JOIN local_users USING (user_id) "
                "WHERE credential_id = ? AND revoked_at IS NULL AND enabled = 1",
                (credential_id,),
            ).fetchone()
        if (
            row is None
            or row[2] != purpose
            or row[3] <= int(time.time())
            or not secrets.compare_digest(row[0], _token_hash(token))
        ):
            return None
        return LocalCredential(credential_id, local_actor(row[1]), row[2], row[3])

    def grant(self, workspace_id: str, actor: Actor, capability: str = "read") -> None:
        if capability != "read":
            raise ValueError("W1 supports only the read capability")
        with self._connect() as connection:
            if actor.tenant_id == LOCAL_TENANT_ID:
                user = connection.execute(
                    "SELECT 1 FROM local_users WHERE user_id = ?", (actor.object_id,)
                ).fetchone()
                if user is None:
                    raise ValueError("local user must exist before membership is granted")
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
