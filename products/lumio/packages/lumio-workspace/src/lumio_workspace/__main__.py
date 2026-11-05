"""Run the service or explicitly manage identities, credentials, and membership."""

from __future__ import annotations

import argparse
import os

import uvicorn

from .app import WorkspaceConfig, create_app
from .state import Actor, WorkspaceState, local_actor


def _state(*, entra: bool = False) -> tuple[str, WorkspaceState, str]:
    workspace_id = os.environ.get("LUMIO_WORKSPACE_ID", "")
    tenant_id = os.environ.get("LUMIO_WORKSPACE_TENANT_ID", "")
    state_path = os.environ.get("LUMIO_WORKSPACE_STATE_PATH", "")
    if not workspace_id or not state_path or (entra and not tenant_id):
        raise ValueError(
            "membership commands require LUMIO_WORKSPACE_ID and "
            "LUMIO_WORKSPACE_STATE_PATH; Entra commands also require "
            "LUMIO_WORKSPACE_TENANT_ID"
        )
    return workspace_id, WorkspaceState(state_path), tenant_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lumio-workspace")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run behind the configured private HTTPS boundary")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    for name in ("grant", "revoke"):
        command = commands.add_parser(name, help=f"{name} the W1 read capability")
        command.add_argument("--object-id", required=True, help="Entra object ID, never an email")

    local_user = commands.add_parser("local-user", help="create or disable a stable local user")
    local_user_commands = local_user.add_subparsers(dest="local_user_command", required=True)
    for name in ("create", "disable"):
        command = local_user_commands.add_parser(name)
        command.add_argument("--user-id", required=True)

    local_membership = commands.add_parser(
        "local-membership", help="manage membership independently of credentials"
    )
    local_membership_commands = local_membership.add_subparsers(
        dest="local_membership_command", required=True
    )
    for name in ("grant", "revoke"):
        command = local_membership_commands.add_parser(name)
        command.add_argument("--user-id", required=True)

    local_token = commands.add_parser(
        "local-token", help="issue or revoke a purpose-bound local credential"
    )
    local_token_commands = local_token.add_subparsers(dest="local_token_command", required=True)
    issue = local_token_commands.add_parser("issue")
    issue.add_argument("--user-id", required=True)
    issue.add_argument("--purpose", choices=("api", "browser"), required=True)
    issue.add_argument("--expires-at", type=int, required=True, help="Unix expiry in seconds")
    revoke_credential = local_token_commands.add_parser("revoke")
    revoke_credential.add_argument("--credential-id", required=True)

    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(create_app(WorkspaceConfig.from_env()), host=args.host, port=args.port)
        return 0
    if args.command in {"grant", "revoke"}:
        workspace_id, state, tenant_id = _state(entra=True)
        actor = Actor(tenant_id=tenant_id, object_id=args.object_id)
        if args.command == "grant":
            state.grant(workspace_id, actor)
        else:
            state.revoke(workspace_id, actor)
        return 0

    workspace_id, state, _ = _state()
    if args.command == "local-user":
        if args.local_user_command == "create":
            state.create_local_user(args.user_id)
        else:
            state.disable_local_user(args.user_id)
    elif args.command == "local-membership":
        actor = local_actor(args.user_id)
        if args.local_membership_command == "grant":
            state.grant(workspace_id, actor)
        else:
            state.revoke(workspace_id, actor)
    elif args.local_token_command == "issue":
        credential_id, token = state.issue_local_credential(
            args.user_id, args.purpose, expires_at=args.expires_at
        )
        # One intentional operator handoff; never log this value elsewhere.
        print(f"credential_id={credential_id}")
        print(f"token={token}")
    else:
        state.revoke_local_credential(args.credential_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
