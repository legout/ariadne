import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const SERVER = "lumio-workspace";
const DISCLOSURE_ENTRY = "lumio-workspace-disclosure";
const TOOL_NAME = /^mcp__lumio[_-]workspace__/;

function modelName(ctx: ExtensionContext): string {
  return ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : "none";
}

function hasWorkspaceMaterial(ctx: ExtensionContext): boolean {
  return ctx.sessionManager.getBranch().some((entry) => {
    if (entry.type === "custom") return entry.customType === DISCLOSURE_ENTRY;
    return (
      entry.type === "message" &&
      entry.message.role === "toolResult" &&
      TOOL_NAME.test(entry.message.toolName)
    );
  });
}

export default function (pi: ExtensionAPI) {
  const url = process.env.LUMIO_WORKSPACE_URL?.replace(/\/$/, "");
  const clientId = process.env.LUMIO_WORKSPACE_PI_CLIENT_ID;
  const scope = process.env.LUMIO_WORKSPACE_SCOPE;
  const metadataUrl = process.env.LUMIO_WORKSPACE_AUTH_METADATA_URL;
  const allowedModels = new Set(
    (process.env.LUMIO_WORKSPACE_ALLOWED_MODELS ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  const missing = !url || !clientId || !scope || !metadataUrl;
  let modelAllowed = false;

  function applyModelPolicy(ctx: ExtensionContext): void {
    modelAllowed = allowedModels.has(modelName(ctx));
    const message = modelAllowed
      ? `workspace model allowed: ${modelName(ctx)}`
      : `workspace reads blocked for model: ${modelName(ctx)}`;
    ctx.ui.setStatus("lumio-workspace", message);
  }

  if (!missing && url && clientId && scope && metadataUrl) {
    const callbackPort = Number(process.env.LUMIO_WORKSPACE_CALLBACK_PORT ?? "8765");
    if (!Number.isInteger(callbackPort) || callbackPort < 1 || callbackPort > 65535) {
      throw new Error("LUMIO_WORKSPACE_CALLBACK_PORT must be a valid TCP port");
    }
    pi.registerMcpServer(SERVER, {
      url: `${url}/mcp`,
      description: "Read admitted knowledge from the configured shared Lumio workspace",
      exposure: "direct",
      oauth: {
        clientId,
        callbackPort,
        scope,
        authServerMetadataUrl: metadataUrl,
      },
    });
  }

  pi.on("session_start", (_event, ctx) => applyModelPolicy(ctx));
  pi.on("model_select", (_event, ctx) => applyModelPolicy(ctx));
  pi.on("tool_execution_end", (event) => {
    if (TOOL_NAME.test(event.toolName) && !event.isError) {
      // Keep disclosure taint after compaction removes the original tool result.
      pi.appendEntry(DISCLOSURE_ENTRY);
    }
  });
  pi.on("before_provider_request", (_event, ctx) => {
    if (!modelAllowed && hasWorkspaceMaterial(ctx)) {
      // Throwing here is fail-open in Pi; aborting reaches the provider signal before fetch.
      ctx.abort();
      ctx.ui.setStatus(
        "lumio-workspace",
        `outbound request aborted: retained workspace content is not allowed for ${modelName(ctx)}`,
      );
    }
  });
  pi.on("tool_call", (event) => {
    if (TOOL_NAME.test(event.toolName) && !modelAllowed) {
      return {
        block: true,
        reason: "The selected model is not authorized for workspace content; check /workspace.",
      };
    }
  });

  pi.registerCommand("workspace", {
    description: "Show Lumio workspace connection guidance and model disclosure status",
    handler: async (_args, ctx) => {
      if (missing) {
        ctx.ui.notify(
          "Set LUMIO_WORKSPACE_URL, LUMIO_WORKSPACE_PI_CLIENT_ID, LUMIO_WORKSPACE_SCOPE, " +
            "LUMIO_WORKSPACE_AUTH_METADATA_URL and LUMIO_WORKSPACE_ALLOWED_MODELS, then reload.",
          "warning",
        );
        return;
      }
      const policy = modelAllowed ? "allowed" : "blocked";
      ctx.ui.notify(
        `Workspace: ${url}/mcp\nModel ${modelName(ctx)}: ${policy}\n` +
          "Use /mcp to inspect the connection and sign in with the pre-registered public client. " +
          "No client secret is configured in Pi.",
        modelAllowed ? "info" : "warning",
      );
    },
  });
}
