# Pi workspace client

A dependency-free Pi extension that registers the configured Streamable HTTP MCP server with a pre-registered public Entra client. It never configures a Pi client secret. `/workspace` shows connection guidance and whether the current provider/model is allowed by the owner’s disclosure policy; `/mcp` performs connection inspection and OAuth sign-in.

See [Shared workspace how-to](../../docs/howto-shared-workspace.md) for exact settings. Install this directory as a trusted Pi extension package, then reload Pi. Workspace reads are blocked before the MCP call when `LUMIO_WORKSPACE_ALLOWED_MODELS` does not contain the exact current `provider/model`, including after a model change.

A compatible local build check using the installed Bun runtime is:

```sh
bun build index.ts --target=node \
  --external @earendil-works/pi-coding-agent \
  --outdir /tmp/lumio-pi-workspace-build
```
