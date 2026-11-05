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
CAPABILITIES = frozenset({"read", "setup", "contribute"})


class RetryConflict(ValueError):
    """A retry key was reused for different identified input."""


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


@dataclass(frozen=True)
class Operation:
    operation_id: str
    action: str
    retry_key: str
    input_digest: str
    source_id: str | None
    status: str
    response: dict


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _stored_response(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("stored operation response is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("stored operation response is invalid")
    return value


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
                    expires_at INTEGER NOT NULL,
                    rotated_at INTEGER
                )
                """
            )
            session_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(browser_sessions)")
            }
            if "rotated_at" not in session_columns:
                connection.execute(
                    "ALTER TABLE browser_sessions ADD COLUMN rotated_at INTEGER"
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    workspace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    retry_key TEXT NOT NULL,
                    input_digest TEXT NOT NULL,
                    source_id TEXT,
                    operation_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (workspace_id, tenant_id, object_id, action, retry_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS setup_records (
                    workspace_id TEXT NOT NULL,
                    setup_digest TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    base_revision TEXT,
                    created_at INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def load_browser_session(self, session_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data, expires_at FROM browser_sessions "
                "WHERE session_id = ? AND rotated_at IS NULL",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            if row[1] <= int(time.time()):
                connection.execute(
                    "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
                )
                return None
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            return None
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
                "UPDATE browser_sessions SET data = ?, expires_at = ? "
                "WHERE session_id = ? AND rotated_at IS NULL",
                (json.dumps(data), expires_at, session_id),
            )
            return cursor.rowcount == 1

    def rotate_browser_session(
        self, old_session_id: str, new_session_id: str, data: dict, *, expires_at: int
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE browser_sessions SET rotated_at = ? "
                "WHERE session_id = ? AND rotated_at IS NULL",
                (int(time.time()), old_session_id),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO browser_sessions (session_id, data, expires_at) VALUES (?, ?, ?)",
                (new_session_id, json.dumps(data), expires_at),
            )
            return True

    def browser_session_was_rotated(self, session_id: str) -> bool:
        with self._connect() as connection:
            # Obsolete responses can arrive after the old session's expiry.
            row = connection.execute(
                "SELECT 1 FROM browser_sessions "
                "WHERE session_id = ? AND rotated_at IS NOT NULL",
                (session_id,),
            ).fetchone()
        return row is not None

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
        if capability not in CAPABILITIES:
            raise ValueError("capability must be read, setup, or contribute")
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

    def revoke(
        self, workspace_id: str, actor: Actor, capability: str = "read"
    ) -> None:
        if capability not in CAPABILITIES:
            raise ValueError("capability must be read, setup, or contribute")
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM memberships WHERE workspace_id = ? "
                "AND tenant_id = ? AND object_id = ? AND capability = ?",
                (workspace_id, actor.tenant_id, actor.object_id, capability),
            )

    def start_operation(
        self,
        workspace_id: str,
        actor: Actor,
        action: str,
        retry_key: str,
        input_digest: str,
        *,
        source_id: str | None = None,
    ) -> tuple[Operation, bool]:
        """Persist retry identity before repeatable work, or return its existing record."""
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT operation_id, status, response_json FROM operations "
                "WHERE workspace_id = ? AND tenant_id = ? AND object_id = ? "
                "AND action = ? AND retry_key = ?",
                (workspace_id, actor.tenant_id, actor.object_id, action, retry_key),
            ).fetchone()
            if row is not None:
                recorded = connection.execute(
                    "SELECT input_digest, source_id FROM operations "
                    "WHERE operation_id = ?",
                    (row[0],),
                ).fetchone()
                if recorded != (input_digest, source_id):
                    raise RetryConflict("retry key is already bound to different input")
                operation = Operation(
                    row[0],
                    action,
                    retry_key,
                    input_digest,
                    source_id,
                    row[1],
                    _stored_response(row[2]),
                )
                return operation, False
            operation_id = secrets.token_urlsafe(18)
            connection.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    actor.tenant_id,
                    actor.object_id,
                    action,
                    retry_key,
                    input_digest,
                    source_id,
                    operation_id,
                    "pending",
                    "{}",
                    now,
                    now,
                ),
            )
        operation = Operation(
            operation_id, action, retry_key, input_digest, source_id, "pending", {}
        )
        return operation, True

    def finish_operation(
        self,
        workspace_id: str,
        actor: Actor,
        operation: Operation,
        status: str,
        response: dict,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE operations SET status = ?, response_json = ?, updated_at = ? "
                "WHERE operation_id = ? AND workspace_id = ? AND tenant_id = ? AND object_id = ?",
                (
                    status,
                    json.dumps(response, sort_keys=True),
                    int(time.time()),
                    operation.operation_id,
                    workspace_id,
                    actor.tenant_id,
                    actor.object_id,
                ),
            )

    def get_operation(
        self, workspace_id: str, actor: Actor, action: str, operation_id: str
    ) -> Operation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT retry_key, input_digest, source_id, status, response_json "
                "FROM operations WHERE workspace_id = ? AND tenant_id = ? "
                "AND object_id = ? AND action = ? AND operation_id = ?",
                (workspace_id, actor.tenant_id, actor.object_id, action, operation_id),
            ).fetchone()
        if row is None:
            return None
        return Operation(
            operation_id,
            action,
            row[0],
            row[1],
            row[2],
            row[3],
            _stored_response(row[4]),
        )

    def record_setup(
        self,
        workspace_id: str,
        actor: Actor,
        digest: str,
        *,
        kind: str,
        target: Path,
        namespace: str,
        base_revision: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO setup_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    digest,
                    actor.tenant_id,
                    actor.object_id,
                    kind,
                    str(target),
                    namespace,
                    base_revision,
                    int(time.time()),
                ),
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
