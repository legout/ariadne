# Pi workspace client

**Accepted interim limitation — 2026-11-05:** The owner explicitly accepted the current API-token exposure for continued development, then authorized commit/merge/push and cleanup in BB `thr_26ccqihn5b`. Pi's default shell inherits its process environment: a model-callable shell or equivalent local tool can expose `LUMIO_WORKSPACE_API_TOKEN` in tool output, session history and model requests. The placeholder header alone does not isolate that secret. Until supported host isolation is qualified, use synthetic credentials/data only; do not claim secret isolation or real-user/private-HTTPS qualification. Browser credentials remain forbidden in Pi. This is a documented accepted development risk, not a fixed defect, a production-use grant, or completion of the remaining live checks.

A dependency-free Pi extension that registers the configured Streamable HTTP MCP server in an explicit `local-token` or `entra` mode. Local mode sends the current user's API token through Pi's supported `Authorization` header environment placeholder; it does not require Entra settings or request the token in conversation. Entra mode retains the pre-registered public-client OAuth flow and never falls back to local authentication. Browser sign-in credentials and cookies are separate and are never supplied to Pi or the model.

`/workspace` shows connection guidance and whether the current provider/model is allowed by the owner’s disclosure policy; `/mcp` inspects the connection and, in Entra mode, performs OAuth sign-in. See [Shared workspace how-to](../../docs/howto-shared-workspace.md) for exact settings and the operator qualification recipe. Install this directory as a trusted Pi extension package, then reload Pi.

Workspace reads are blocked before the MCP call when `LUMIO_WORKSPACE_ALLOWED_MODELS` does not contain the exact current `provider/model`, including after a model change. Once a workspace result enters the session, a provider request carrying that retained history is aborted before network I/O for a nonallowed model, including after switching or resuming. A persistent disclosure marker retains that protection when compaction removes the original tool result; unrelated clean conversations are not blocked. Manual/automatic compaction and branch summarization are cancelled before their separate provider requests for a nonallowed model with retained workspace material; allowed-model and unrelated-conversation summarization remain available. This is trusted-client disclosure policy, not remote attestation.

A compatible local build check using the installed Bun runtime is:

```sh
bun build index.ts --target=node \
  --external @earendil-works/pi-coding-agent \
  --outdir /tmp/lumio-pi-workspace-build
```
