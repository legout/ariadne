import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { uploadExactBytes } from "./upload.ts";

const MAX_SOURCE_BYTES = 25 * 1024 * 1024;

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
  const authMode = process.env.LUMIO_WORKSPACE_AUTH_MODE;
  const clientId = process.env.LUMIO_WORKSPACE_PI_CLIENT_ID;
  const scope = process.env.LUMIO_WORKSPACE_SCOPE;
  const metadataUrl = process.env.LUMIO_WORKSPACE_AUTH_METADATA_URL;
  const allowedModels = new Set(
    (process.env.LUMIO_WORKSPACE_ALLOWED_MODELS ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  const missing =
    !url ||
    (authMode === "local-token"
      ? !process.env.LUMIO_WORKSPACE_API_TOKEN
      : authMode !== "entra" || !clientId || !scope || !metadataUrl);
  let modelAllowed = false;
  let summaryNeedsDisclosure = false;

  function applyModelPolicy(ctx: ExtensionContext): void {
    modelAllowed = allowedModels.has(modelName(ctx));
    const message = modelAllowed
      ? `workspace model allowed: ${modelName(ctx)}`
      : `workspace reads blocked for model: ${modelName(ctx)}`;
    ctx.ui.setStatus("lumio-workspace", message);
  }

  if (!missing && url && authMode === "local-token") {
    pi.registerMcpServer(SERVER, {
      url: `${url}/mcp`,
      description:
        "Read admitted knowledge, query authorized pinned data, and prepare contributions/enrichment",
      exposure: "direct",
      headers: { Authorization: "Bearer ${LUMIO_WORKSPACE_API_TOKEN}" },
    });
  }

  if (!missing && url && authMode === "entra" && clientId && scope && metadataUrl) {
    const callbackPort = Number(process.env.LUMIO_WORKSPACE_CALLBACK_PORT ?? "8765");
    if (!Number.isInteger(callbackPort) || callbackPort < 1 || callbackPort > 65535) {
      throw new Error("LUMIO_WORKSPACE_CALLBACK_PORT must be a valid TCP port");
    }
    pi.registerMcpServer(SERVER, {
      url: `${url}/mcp`,
      description:
        "Read admitted knowledge, query authorized pinned data, and prepare contributions/enrichment",
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
  pi.on("session_before_compact", (_event, ctx) => {
    if (!modelAllowed && hasWorkspaceMaterial(ctx)) {
      ctx.ui.setStatus(
        "lumio-workspace",
        `compaction cancelled: retained workspace content is not allowed for ${modelName(ctx)}`,
      );
      return { cancel: true };
    }
  });
  pi.on("session_before_tree", (event, ctx) => {
    summaryNeedsDisclosure = event.preparation.userWantsSummary && hasWorkspaceMaterial(ctx);
    if (summaryNeedsDisclosure && !modelAllowed) {
      ctx.ui.setStatus(
        "lumio-workspace",
        `branch summary cancelled: retained workspace content is not allowed for ${modelName(ctx)}`,
      );
      return { cancel: true };
    }
  });
  pi.on("session_tree", (event) => {
    if (event.summaryEntry && summaryNeedsDisclosure) {
      // A derived summary keeps the abandoned branch's disclosure provenance.
      pi.appendEntry(DISCLOSURE_ENTRY);
    }
    summaryNeedsDisclosure = false;
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

  pi.registerCommand("workspace-upload", {
    description: "Upload exact selected bytes: /workspace-upload <source-id> <path> [retry=<key>]",
    handler: async (args, ctx) => {
      applyModelPolicy(ctx);
      if (missing || !url) {
        ctx.ui.notify("Configure the Lumio workspace before uploading; check /workspace.", "warning");
        return;
      }
      if (authMode !== "local-token") {
        ctx.ui.notify("Exact-byte upload currently requires explicit local-token mode.", "warning");
        return;
      }
      if (!modelAllowed) {
        ctx.ui.notify(
          `Upload blocked before reading the original for model ${modelName(ctx)}.`,
          "warning",
        );
        return;
      }
      const [sourceId, ...rest] = args.trim().split(/\s+/).filter(Boolean);
      let retryKey = randomUUID();
      if (rest.at(-1)?.startsWith("retry=")) {
        retryKey = rest.pop()!.slice("retry=".length);
      }
      const fileArgument = rest.join(" ").trim();
      if (!sourceId || !fileArgument || !retryKey) {
        ctx.ui.notify(
          "Usage: /workspace-upload <source-id> <path> [retry=<key>]",
          "warning",
        );
        return;
      }
      const path = resolve(ctx.cwd, fileArgument.replace(/^@/, ""));
      try {
        const fileStat = await stat(path);
        if (!fileStat.isFile() || fileStat.size === 0 || fileStat.size > MAX_SOURCE_BYTES) {
          ctx.ui.notify("Select a nonempty regular file no larger than 25 MiB.", "warning");
          return;
        }
        const bytes = await readFile(path);
        const receipt = await uploadExactBytes({
          baseUrl: url,
          token: process.env.LUMIO_WORKSPACE_API_TOKEN ?? "",
          sourceId,
          filename: basename(path),
          retryKey,
          bytes,
        });
        ctx.ui.notify(
          `Uploaded ${receipt.filename}: ${receipt.size} bytes, SHA-256 ${receipt.sha256}.`,
          "info",
        );
        pi.sendUserMessage(
          `Exact original uploaded as upload_id ${receipt.upload_id} for source ${receipt.source_id}; ` +
            "this is not a task_id. " +
            `Retain retry=${retryKey} plus the exact source ID, filename, and bytes. After an ` +
            "interrupted upload, repeat the same upload with that key and those exact inputs to " +
            "recover the same upload_id; do not call get_task(upload_id). Use read_source_material " +
            "to inspect normalized text and conversion facts. For prepare_contribution, retain a " +
            "separate stable retry_key and the exact request. Repeat that preparation to recover " +
            "its task_id if interruption hid it, then call get_task with the actual task_id. " +
            "Analytics contributions also require the exact granted source_task_id. Old browser " +
            "approvals must not be replayed, and lost keys or inputs are not recoverable.",
        );
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "warning");
      }
    },
  });

  pi.registerCommand("workspace", {
    description: "Show Lumio workspace connection guidance and model disclosure status",
    handler: async (_args, ctx) => {
      if (missing) {
        const settings =
          authMode === "local-token"
            ? "LUMIO_WORKSPACE_URL, LUMIO_WORKSPACE_API_TOKEN and LUMIO_WORKSPACE_ALLOWED_MODELS"
            : "LUMIO_WORKSPACE_PI_CLIENT_ID, LUMIO_WORKSPACE_SCOPE, " +
              "LUMIO_WORKSPACE_AUTH_METADATA_URL and LUMIO_WORKSPACE_ALLOWED_MODELS";
        ctx.ui.notify(
          `Set LUMIO_WORKSPACE_AUTH_MODE to local-token or entra, then set ${settings}, then reload.`,
          "warning",
        );
        return;
      }
      const policy = modelAllowed ? "allowed" : "blocked";
      const connectionGuidance =
        authMode === "local-token"
          ? "Use /mcp to inspect the token-authenticated connection. " +
            "Use /workspace-upload <source-id> <path> [retry=<key>] for exact bytes. " +
            "Browser sign-in is separate."
          : "Use /mcp to inspect the connection and sign in with the pre-registered public client. " +
            "No client secret is configured in Pi.";
      const guidance =
        connectionGuidance +
        " When analytics is enabled: prepare_data_source, complete its separate source/data " +
        "browser decisions, then profile_data_source; prepare_contribution needs the granted " +
        "source_task_id, and query_data rechecks the caller's complete source-set grant. " +
        "For bounded enrichment, call prepare_enrichment with explicit page IDs, the current " +
        "admitted version, and a stable request_key. Author the complete returned selection " +
        "through prepare_contribution with enrichment_task_id, sources: [], and a separate stable " +
        "retry_key. Repeat the identical selection/draft to resume after interruption. A correction " +
        "or subset needs a new draft retry_key and its fresh exact browser review; never replay an " +
        "old whole-batch action. External lookup is disabled by default.";
      ctx.ui.notify(
        `Workspace: ${url}/mcp\nModel ${modelName(ctx)}: ${policy}\n${guidance}`,
        modelAllowed ? "info" : "warning",
      );
    },
  });
}
