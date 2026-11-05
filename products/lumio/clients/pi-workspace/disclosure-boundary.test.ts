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

async function createSession(
  cwd: string,
  sessionManager: any,
  selectedModel: any,
  calls: string[],
  compaction: any = { enabled: false, keepRecentTokens: 0 },
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
                return successfulResponse(derivedSummary);
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
