"""Run the service or explicitly manage local owner-granted membership."""

from __future__ import annotations

import argparse
import os

import uvicorn

from .app import WorkspaceConfig, create_app
from .state import Actor, WorkspaceState


def _state() -> tuple[str, WorkspaceState, str]:
    workspace_id = os.environ.get("LUMIO_WORKSPACE_ID", "")
    tenant_id = os.environ.get("LUMIO_WORKSPACE_TENANT_ID", "")
    state_path = os.environ.get("LUMIO_WORKSPACE_STATE_PATH", "")
    if not workspace_id or not tenant_id or not state_path:
        raise ValueError(
            "membership commands require LUMIO_WORKSPACE_ID, "
            "LUMIO_WORKSPACE_TENANT_ID and LUMIO_WORKSPACE_STATE_PATH"
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
    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(create_app(WorkspaceConfig.from_env()), host=args.host, port=args.port)
        return 0
    workspace_id, state, tenant_id = _state()
    actor = Actor(tenant_id=tenant_id, object_id=args.object_id)
    if args.command == "grant":
        state.grant(workspace_id, actor)
    else:
        state.revoke(workspace_id, actor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
