import { expect, test } from "bun:test";
import { mkdtemp } from "node:fs/promises";
import workspaceExtension from "./index.ts";

const SENTINEL = "synthetic-private-workspace-sentinel";
const agentEntry = process.env.PI_CODING_AGENT_ENTRY;
const aiCompatEntry = process.env.PI_AI_COMPAT_ENTRY;
if (!agentEntry || !aiCompatEntry) {
  throw new Error("Set PI_CODING_AGENT_ENTRY and PI_AI_COMPAT_ENTRY to the installed Pi modules");
}
const agent = await import(agentEntry);
const ai = await import(aiCompatEntry);

const zeroUsage = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

function model(id: string) {
  return {
    id,
    name: id,
    api: "openai-completions",
    provider: "fixture",
    baseUrl: "https://fixture.invalid/v1",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 128,
  };
}

const allowedModel = model("allowed");
const forbiddenModel = model("forbidden");

function successfulResponse() {
  const chunk = {
    id: "chatcmpl-fixture",
    object: "chat.completion.chunk",
    created: 1,
    model: "fixture",
    choices: [{ index: 0, delta: { role: "assistant", content: "ok" }, finish_reason: null }],
  };
  const done = {
    ...chunk,
    choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  };
  return new Response(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(done)}\n\ndata: [DONE]\n\n`, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

async function createSession(cwd: string, sessionManager: any, selectedModel: any, calls: string[]) {
  const modelRuntime = await agent.ModelRuntime.create({
    authPath: `${cwd}/agent/auth.json`,
    modelsPath: null,
    refreshOnCreate: false,
  });
  const settingsManager = agent.SettingsManager.inMemory({ compaction: { enabled: false } });
  const resourceLoader = new agent.DefaultResourceLoader({
    cwd,
    agentDir: `${cwd}/agent`,
    settingsManager,
    extensionFactories: [
      workspaceExtension,
      (pi: any) => {
        pi.registerProvider("fixture", {
          baseUrl: "https://fixture.invalid/v1",
          apiKey: "synthetic-not-a-credential",
          api: "openai-completions",
          models: [allowedModel, forbiddenModel],
          streamSimple: (requestModel: any, context: any, options: any) =>
            ai.openAICompletionsApi().streamSimple(requestModel, context, {
              ...options,
              fetch: async (_input: unknown, init?: { body?: unknown }) => {
                calls.push(String(init?.body ?? ""));
                return successfulResponse();
              },
            }),
        });
      },
    ],
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await resourceLoader.reload();
  const { session } = await agent.createAgentSession({
    cwd,
    agentDir: `${cwd}/agent`,
    model: selectedModel,
    modelRuntime,
    resourceLoader,
    sessionManager,
    settingsManager,
    noTools: "all",
    sessionStartEvent: { type: "session_start", reason: sessionManager.isPersisted() ? "resume" : "startup" },
  });
  await session.bindExtensions({ mode: "json" });
  return session;
}

test("forbidden model cannot send retained workspace history after switch or resume", async () => {
  const previousAllowlist = process.env.LUMIO_WORKSPACE_ALLOWED_MODELS;
  process.env.LUMIO_WORKSPACE_ALLOWED_MODELS = "fixture/allowed";
  const cwd = await mkdtemp("/tmp/lumio-pi-disclosure-");
  const calls: string[] = [];
  let session: any;
  let resumed: any;
  let clean: any;
  try {
    const manager = agent.SessionManager.create(cwd, `${cwd}/sessions`);
    manager.appendMessage({ role: "user", content: "Read the synthetic page", timestamp: 1 });
    manager.appendMessage({
      role: "assistant",
      content: [
        {
          type: "toolCall",
          id: "approved-read",
          name: "mcp__lumio-workspace__read_knowledge",
          arguments: { title: "Synthetic" },
        },
      ],
      api: "openai-completions",
      provider: "fixture",
      model: "allowed",
      usage: zeroUsage,
      stopReason: "toolUse",
      timestamp: 2,
    });
    manager.appendMessage({
      role: "toolResult",
      toolCallId: "approved-read",
      toolName: "mcp__lumio-workspace__read_knowledge",
      content: [{ type: "text", text: SENTINEL }],
      details: {},
      isError: false,
      timestamp: 3,
    });

    session = await createSession(cwd, manager, allowedModel, calls);
    await session.prompt("Use the approved result");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain(SENTINEL);

    await session.setModel(forbiddenModel);
    await session.prompt("This request must not leave Pi");
    expect(calls).toHaveLength(1);
    session.dispose();
    session = undefined;

    const resumedManager = agent.SessionManager.open(manager.getSessionFile());
    resumed = await createSession(cwd, resumedManager, forbiddenModel, calls);
    await resumed.prompt("This resumed request must not leave Pi");
    expect(calls).toHaveLength(1);
    resumed.dispose();
    resumed = undefined;

    clean = await createSession(cwd, agent.SessionManager.inMemory(cwd), forbiddenModel, calls);
    await clean.prompt("A clean conversation remains usable");
    expect(calls).toHaveLength(2);
    expect(calls[1]).not.toContain(SENTINEL);
  } finally {
    session?.dispose();
    resumed?.dispose();
    clean?.dispose();
    if (previousAllowlist === undefined) delete process.env.LUMIO_WORKSPACE_ALLOWED_MODELS;
    else process.env.LUMIO_WORKSPACE_ALLOWED_MODELS = previousAllowlist;
  }
});
