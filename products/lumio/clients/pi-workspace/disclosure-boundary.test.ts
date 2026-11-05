import { expect, test } from "bun:test";
import { mkdtemp, readFile } from "node:fs/promises";
import workspaceExtension from "./index.ts";

const SENTINEL = "synthetic-private-workspace-sentinel";
const API_TOKEN = "synthetic-local-api-token-not-a-credential";
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

function successfulResponse(content = "ok") {
  const chunk = {
    id: "chatcmpl-fixture",
    object: "chat.completion.chunk",
    created: 1,
    model: "fixture",
    choices: [{ index: 0, delta: { role: "assistant", content }, finish_reason: null }],
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

function workspaceReadResponse() {
  const chunk = {
    id: "chatcmpl-fixture",
    object: "chat.completion.chunk",
    created: 1,
    model: "fixture",
    choices: [
      {
        index: 0,
        delta: {
          role: "assistant",
          tool_calls: [
            {
              index: 0,
              id: "call-workspace-read",
              type: "function",
              function: {
                name: "mcp__lumio_workspace__read_knowledge",
                arguments: JSON.stringify({ title: "Synthetic" }),
              },
            },
          ],
        },
        finish_reason: null,
      },
    ],
  };
  const done = {
    ...chunk,
    choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  };
  return new Response(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(done)}\n\ndata: [DONE]\n\n`, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

async function createSession(
  cwd: string,
  sessionManager: any,
  selectedModel: any,
  calls: string[],
  compaction: any = { enabled: false, keepRecentTokens: 0 },
  mcp = false,
  respond?: (body: string) => Response,
) {
  const modelRuntime = await agent.ModelRuntime.create({
    authPath: `${cwd}/agent/auth.json`,
    modelsPath: null,
    refreshOnCreate: false,
  });
  const settingsManager = agent.SettingsManager.inMemory({ compaction });
  const resourceLoader = new agent.DefaultResourceLoader({
    cwd,
    agentDir: `${cwd}/agent`,
    settingsManager,
    extensionFactories: [
      workspaceExtension,
      ...(mcp
        ? [
            agent.createMcpExtension({
              loadConfig: () => ({ servers: [], errors: [] }),
              logPath: `${cwd}/agent/mcp.log`,
            }),
          ]
        : []),
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
                const body = String(init?.body ?? "");
                calls.push(body);
                const derivedSummary = body.includes(
                  "Create a structured summary of this conversation branch",
                ) && body.includes(SENTINEL)
                  ? `Derived private branch summary: ${SENTINEL}`
                  : "ok";
                return respond ? respond(body) : successfulResponse(derivedSummary);
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
    noTools: mcp ? "builtin" : "all",
    sessionStartEvent: { type: "session_start", reason: sessionManager.isPersisted() ? "resume" : "startup" },
  });
  await session.bindExtensions({ mode: "json" });
  return session;
}

function appendWorkspaceHistory(manager: any) {
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
  manager.appendMessage({
    role: "assistant",
    content: [{ type: "text", text: `The approved page says ${SENTINEL}` }],
    api: "openai-completions",
    provider: "fixture",
    model: "allowed",
    usage: zeroUsage,
    stopReason: "stop",
    timestamp: 4,
  });
  manager.appendMessage({
    role: "user",
    content: "Continue with the approved result",
    timestamp: 5,
  });
}

test("forbidden model cannot send retained workspace history after switch or resume", async () => {
  const previousAllowlist = process.env.LUMIO_WORKSPACE_ALLOWED_MODELS;
  process.env.LUMIO_WORKSPACE_ALLOWED_MODELS = "fixture/allowed";
  const cwd = await mkdtemp("/tmp/lumio-pi-disclosure-");
  const calls: string[] = [];
  let session: any;
  let resumed: any;
  let clean: any;
  let allowedCompaction: any;
  let manual: any;
  let automatic: any;
  let branch: any;
  let allowedBranch: any;
  let resumedBranch: any;
  try {
    const manager = agent.SessionManager.create(cwd, `${cwd}/sessions`);
    appendWorkspaceHistory(manager);

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
    clean.dispose();
    clean = undefined;

    allowedCompaction = await createSession(
      cwd,
      agent.SessionManager.inMemory(cwd),
      allowedModel,
      calls,
    );
    appendWorkspaceHistory(allowedCompaction.sessionManager);
    await allowedCompaction.compact();
    expect(calls).toHaveLength(3);
    expect(calls[2]).toContain(SENTINEL);
    allowedCompaction.dispose();
    allowedCompaction = undefined;

    manual = await createSession(cwd, agent.SessionManager.inMemory(cwd), forbiddenModel, calls);
    appendWorkspaceHistory(manual.sessionManager);
    const manualStart = calls.length;
    const manualError = await manual.compact().then(
      () => undefined,
      (error) => error,
    );
    const manualEnd = calls.length;

    const automaticManager = agent.SessionManager.inMemory(cwd);
    appendWorkspaceHistory(automaticManager);
    automaticManager.appendMessage({
      role: "assistant",
      content: [{ type: "text", text: "Allowed answer" }],
      api: "openai-completions",
      provider: "fixture",
      model: "allowed",
      usage: { ...zeroUsage, input: 1000, totalTokens: 1000 },
      stopReason: "stop",
      timestamp: 5,
    });
    automatic = await createSession(cwd, automaticManager, forbiddenModel, calls, {
      enabled: true,
      reserveTokens: 127001,
      keepRecentTokens: 0,
    });
    const automaticStart = calls.length;
    await automatic.prompt("Automatic compaction must not disclose the retained history");
    const automaticEnd = calls.length;

    branch = await createSession(cwd, agent.SessionManager.inMemory(cwd), forbiddenModel, calls);
    appendWorkspaceHistory(branch.sessionManager);
    const branchTarget = branch.sessionManager
      .getBranch()
      .find((entry: any) => entry.type === "message" && entry.message.role === "user").id;
    const branchStart = calls.length;
    const branchResult = await branch.navigateTree(branchTarget, { summarize: true });

    expect({
      manualError: manualError?.message,
      manualRequests: calls.slice(manualStart, manualEnd),
      automaticRequests: calls.slice(automaticStart, automaticEnd),
      branchCancelled: branchResult.cancelled,
      branchRequests: calls.slice(branchStart),
    }).toEqual({
      manualError: "Compaction cancelled",
      manualRequests: [],
      automaticRequests: [],
      branchCancelled: true,
      branchRequests: [],
    });

    const allowedBranchManager = agent.SessionManager.create(cwd, `${cwd}/branch-sessions`);
    appendWorkspaceHistory(allowedBranchManager);
    allowedBranch = await createSession(cwd, allowedBranchManager, allowedModel, calls);
    const allowedBranchTarget = allowedBranch.sessionManager
      .getBranch()
      .find((entry: any) => entry.type === "message" && entry.message.role === "user").id;
    const summaryStart = calls.length;
    const allowedBranchResult = await allowedBranch.navigateTree(allowedBranchTarget, {
      summarize: true,
    });
    const summaryEnd = calls.length;
    await allowedBranch.setModel(forbiddenModel);
    await allowedBranch.prompt("The derived summary must not leave Pi");
    const forbiddenEnd = calls.length;
    allowedBranch.dispose();
    allowedBranch = undefined;

    resumedBranch = await createSession(
      cwd,
      agent.SessionManager.open(allowedBranchManager.getSessionFile()),
      forbiddenModel,
      calls,
    );
    await resumedBranch.prompt("The restored derived summary must not leave Pi");

    expect({
      summaryRequests: summaryEnd - summaryStart,
      summaryInputContainsSentinel: calls[summaryStart]?.includes(SENTINEL),
      summaryAttached: allowedBranchResult.summaryEntry?.type,
      summaryContainsSentinel: allowedBranchResult.summaryEntry?.summary.includes(SENTINEL),
      forbiddenRequests: calls.slice(summaryEnd, forbiddenEnd),
      resumedRequests: calls.slice(forbiddenEnd),
    }).toEqual({
      summaryRequests: 1,
      summaryInputContainsSentinel: true,
      summaryAttached: "branch_summary",
      summaryContainsSentinel: true,
      forbiddenRequests: [],
      resumedRequests: [],
    });
  } finally {
    session?.dispose();
    resumed?.dispose();
    clean?.dispose();
    allowedCompaction?.dispose();
    manual?.dispose();
    automatic?.dispose();
    branch?.dispose();
    allowedBranch?.dispose();
    resumedBranch?.dispose();
    if (previousAllowlist === undefined) delete process.env.LUMIO_WORKSPACE_ALLOWED_MODELS;
    else process.env.LUMIO_WORKSPACE_ALLOWED_MODELS = previousAllowlist;
  }
});

test("local API token authenticates real MCP reads without entering model or session material", async () => {
  const environmentNames = [
    "LUMIO_WORKSPACE_AUTH_MODE",
    "LUMIO_WORKSPACE_URL",
    "LUMIO_WORKSPACE_API_TOKEN",
    "LUMIO_WORKSPACE_ALLOWED_MODELS",
    "LUMIO_WORKSPACE_PI_CLIENT_ID",
    "LUMIO_WORKSPACE_SCOPE",
    "LUMIO_WORKSPACE_AUTH_METADATA_URL",
  ];
  const previousEnvironment = new Map(
    environmentNames.map((name) => [name, process.env[name]] as const),
  );
  const actors = new Map([[API_TOKEN, "alice"]]);
  const members = new Set(["alice"]);
  const readActors: string[] = [];
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      const authorization = request.headers.get("authorization") ?? "";
      const actor = authorization.startsWith("Bearer ")
        ? actors.get(authorization.slice("Bearer ".length))
        : undefined;
      if (!actor) return new Response("workspace access is not available", { status: 401 });
      if (request.method === "GET") return new Response(null, { status: 405 });
      if (request.method !== "POST") return new Response(null, { status: 405 });

      const message: any = await request.json();
      if (message.id === undefined) return new Response(null, { status: 202 });
      const respond = (result: unknown) =>
        Response.json({ jsonrpc: "2.0", id: message.id, result });
      if (message.method === "initialize") {
        return respond({
          protocolVersion: message.params.protocolVersion,
          capabilities: { tools: {} },
          serverInfo: { name: "synthetic-workspace", version: "1" },
          instructions: "Read the fixed synthetic publication",
        });
      }
      if (message.method === "tools/list") {
        return respond({
          tools: [
            {
              name: "read_knowledge",
              description: "Read the fixed synthetic page",
              inputSchema: {
                type: "object",
                properties: { title: { type: "string" } },
                required: ["title"],
              },
            },
          ],
        });
      }
      if (message.method === "tools/call" && message.params.name === "read_knowledge") {
        readActors.push(actor);
        if (!members.has(actor)) {
          return respond({
            content: [{ type: "text", text: "workspace access is not available" }],
            isError: true,
          });
        }
        return respond({
          content: [{ type: "text", text: SENTINEL }],
          structuredContent: { found: true, title: "Synthetic", markdown: SENTINEL },
          isError: false,
        });
      }
      return Response.json({
        jsonrpc: "2.0",
        id: message.id,
        error: { code: -32601, message: "method not found" },
      });
    },
  });

  const cwd = await mkdtemp("/tmp/lumio-pi-local-token-");
  const calls: string[] = [];
  const respond = (body: string) => {
    const request = JSON.parse(body);
    return request.messages.at(-1)?.role === "tool"
      ? successfulResponse()
      : workspaceReadResponse();
  };
  let session: any;
  let resumed: any;
  let forbiddenClean: any;
  try {
    for (const name of environmentNames) delete process.env[name];
    process.env.LUMIO_WORKSPACE_AUTH_MODE = "local-token";
    process.env.LUMIO_WORKSPACE_URL = `http://127.0.0.1:${server.port}`;
    process.env.LUMIO_WORKSPACE_API_TOKEN = API_TOKEN;
    process.env.LUMIO_WORKSPACE_ALLOWED_MODELS = "fixture/allowed";

    const manager = agent.SessionManager.create(cwd, `${cwd}/sessions`);
    session = await createSession(
      cwd,
      manager,
      allowedModel,
      calls,
      { enabled: false, keepRecentTokens: 0 },
      true,
      respond,
    );
    await session.prompt("Read the synthetic page");
    expect(readActors).toEqual(["alice"]);
    expect(calls).toHaveLength(2);
    expect(calls[1]).toContain(SENTINEL);

    // Independent oracle: the same valid actor loses its current membership.
    members.delete("alice");
    await session.prompt("Read the synthetic page again");
    expect(readActors).toEqual(["alice", "alice"]);
    expect(calls).toHaveLength(4);

    const toolResults = manager
      .getBranch()
      .filter(
        (entry: any) => entry.type === "message" && entry.message.role === "toolResult",
      )
      .map((entry: any) => entry.message);
    expect(toolResults).toHaveLength(2);
    expect(toolResults[0].isError).toBe(false);
    expect(JSON.stringify(toolResults[0].content)).toContain(SENTINEL);
    expect(toolResults[1].isError).toBe(true);
    expect(JSON.stringify(toolResults[1].content)).not.toContain(SENTINEL);

    await session.setModel(forbiddenModel);
    await session.prompt("Retained workspace content must not leave Pi");
    expect(calls).toHaveLength(4);
    const sessionFile = manager.getSessionFile();
    session.dispose();
    session = undefined;

    resumed = await createSession(
      cwd,
      agent.SessionManager.open(sessionFile),
      forbiddenModel,
      calls,
      { enabled: false, keepRecentTokens: 0 },
      true,
      respond,
    );
    await resumed.prompt("Resumed workspace content must not leave Pi");
    expect(calls).toHaveLength(4);
    resumed.dispose();
    resumed = undefined;

    forbiddenClean = await createSession(
      cwd,
      agent.SessionManager.inMemory(cwd),
      forbiddenModel,
      calls,
      { enabled: false, keepRecentTokens: 0 },
      true,
      respond,
    );
    await forbiddenClean.prompt("Attempt a workspace read without authorization");
    // The blocked tool result is retained, so the forbidden follow-up request is also aborted.
    expect(calls).toHaveLength(5);
    expect(readActors).toEqual(["alice", "alice"]);
    const blockedResult = forbiddenClean.sessionManager
      .getBranch()
      .find(
        (entry: any) => entry.type === "message" && entry.message.role === "toolResult",
      );
    expect(blockedResult.message.isError).toBe(true);
    expect(JSON.stringify(blockedResult.message.content)).toContain("not authorized");

    const history = await readFile(sessionFile, "utf8");
    expect(history).toContain(SENTINEL);
    expect(history).not.toContain(API_TOKEN);
    for (const body of calls) expect(body).not.toContain(API_TOKEN);
  } finally {
    session?.dispose();
    resumed?.dispose();
    forbiddenClean?.dispose();
    server.stop(true);
    for (const [name, value] of previousEnvironment) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});
