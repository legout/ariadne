# Implementation plan: Ariadne Agent backend

> **Historical status — 2026-10-07:** Historical execution map: #22–#25 are closed. The proposed `ariadne-core`/`ariadne-agent` distribution names below are superseded by [ADR-0018](../adr/0018-distribution-naming-ariadneai.md): current distributions are `ariadneai`/`ariadneai-agent`, with unchanged import namespaces. Preserve original decisions as history; no retrospective approval is inferred.

| | |
| :--- | :--- |
| **Status** | **Approved — owner approval 2026-09-30; execution authorization still required** |
| **Goal** | Rename the existing root distribution to `ariadne-core`, then deliver a separately installable, Python-callable Ariadne Agent with user-selected Analyst/Authoring roles and events a later UI can consume. |
| **Behavioral source** | [Ariadne Agent specification](../specs/2026-09-29-0006-ariadne-agent-backend.md), approved revision 2 (scoped packaging amendment, owner pi conversation 2026-09-29); revision 1 owns unchanged Agent behavior. Exact scope: `ariadne-core` distribution with unchanged `ariadne.*` imports, CLI names and DuckDB runtime; OpenAI-compatible Tau model/loop, in-memory role-bound sessions, native Ariadne query/authoring tools, curated skills and references, explicitly allowed stdio MCP tools, no `tau_coding` runtime use. `ariadne-query`, BI/UI, multi-engine execution and durable storage are deferred. |
| **Decisions** | [ADR-0014](../adr/0014-embedded-tau-agent-backend.md); existing [ADR-0012](../adr/0012-local-first-artifact-runtime.md) and [ADR-0013](../adr/0013-harness-led-authoring-boundary.md) retain their local-first and human-only gates. Dependency contract: `legout/tau-mcp:project/specs/2026-09-29-0002-embeddable-mcp-core.md`; execution map: `legout/tau-mcp:project/plans/2026-09-29-0002-embeddable-mcp-core.md`. |
| **Contract / provenance** | planning-contract v1; installed skill provenance unknown. |

## Readiness, boundaries and order

- Capture checkpoint: `CONTEXT.md` owns Ariadne Agent and Data Analyst Agent; `ariadne-core` is a distribution identifier, not a new domain term. ADR-0014 owns the separate embedded-Tau choice and approved root-distribution rename; ADR-0012 retains the optional MCP-extra decision, and tau-mcp ADR-0002 owns extraction of its stdio core. The approved specification owns the two role flows, packaging amendment, failures, non-goals and six acceptance examples. No material owner decision remains for DuckDB-only v1; implementation, integration and publication are not authorized by approving this plan.
- Feasibility evidence: a disposable Python 3.12 environment installed `tau-ai==0.4.6`, imported `tau_agent.AgentHarness`/`tau_ai.OpenAICompatibleProvider` without importing `tau_coding`, and passed 21 existing tau-mcp offline/stdio/direct tests (pi preflight 2026-09-29). This does **not** prove the not-yet-built `tau-mcp` wheel. Ariadne A3 is blocked until tau-mcp M1–M2 produce and accept an installable, restricted core. A1–A2 do not consume tau-mcp and may proceed independently in their own worktree.
- Local callers: a Python host chooses the project, role, model and operator-owned MCP settings; model text may only choose among registered tools. The renamed `ariadne-core` wheel still owns the `ariadne.*` import package, all existing entry points, DuckDB-only `AriadneRuntime` and the existing authoring service. Keep the agent's tool wrappers thin and do not import `ariadne.serve` to get its optional MCP transport or add Tau/agent dependencies to the core.
- Security and permissions: source locations, credentials, staged proposals and governed answers are the assets. A model-directed request for an unregistered human command, a `../` skill reference, or a disallowed MCP tool name must not reach a filesystem/source or external tool outside that role. The single operator config is trusted; untrusted model-selected tool arguments and external MCP results are not. An operator must not approve a generic external SQL/file-write tool that bypasses Ariadne's gates. No arbitrary local shell, project-selected server command, remote HTTP agent, Tau TUI, automatic Promotion or BI placeholder.
- One writer per worktree. Within this repo A0 → A1 → A2 → A3 is sequential: Agent dependency metadata must not point at the unrelated PyPI `ariadne` distribution. The root stays at the repository root; the independently installable Agent stays in `ariadne-agent/`. A workspace move is not required. tau-mcp's separate writer may work on M1–M2 concurrently with A0–A2 only after its own plan is approved. A3 consumes the **accepted** M2 interface, never an assumed one.

## Tickets (canonical task bodies)

The linked GitHub issues own files, interfaces, focused checks and completion criteria. They are **proposed**, not executable until the owner approves this plan and separately authorizes implementation. The two repositories have distinct writers; A3 waits for the accepted tau-mcp contract.

| Unit | Ticket | Prerequisite | Test obligation |
| :--- | :--- | :--- | :--- |
| A0 — rename root distribution | [ariadne#22](https://github.com/legout/ariadne/issues/22) | None | `existing-check` |
| A1 — Analyst session | [ariadne#23](https://github.com/legout/ariadne/issues/23) | A0 accepted | `new-test` |
| A2 — Authoring session | [ariadne#24](https://github.com/legout/ariadne/issues/24) | A1 accepted | `new-test` |
| A3 — restricted MCP integration | [ariadne#25](https://github.com/legout/ariadne/issues/25) | A2 and [tau-mcp#7](https://github.com/legout/tau-mcp/issues/7) accepted | `new-test` |

## Coverage, verification and handoff

| Spec acceptance | Tasks and distinct evidence |
| :--- | :--- |
| 1: governed/ad-hoc route, caveats, values and staging | A1 fake-model routing + existing retail-demo numeric oracle |
| 2: first-run Authoring, operator approval and human-only Promotion | A2 empty-project session + existing authoring service checks |
| 3: role limits through native/direct/proxy paths | A2 native tool list; tau-mcp M2 dispatch test; A3 consumer-wiring test |
| 4: stdio discovery, timeout/crash and child cleanup | tau-mcp M1–M2 tests for protocol/lifecycle; A3 one session shutdown check |
| 5: fixed in-memory role/session, no `tau_coding` runtime, unchanged base CLI with `ariadne-core` dependency | A0 renamed-wheel/import/CLI check; A1 session check; A2 role isolation; A3 dependency-resolution and isolated wheel checks |
| 6: real tool-capable OpenAI-compatible endpoint streaming | One live smoke after A3, separately reported from deterministic tests |

Global validation once after A3: from the Ariadne repo root run `.venv/bin/python -m pytest`, `.venv/bin/ruff check .`, `uv lock --check` and `uv build`; in `ariadne-agent/` run `uv run pytest` and build its wheel; install locally built `ariadne-core`, tau-mcp and Agent wheels into a disposable environment at the verified Tau version, checking metadata and import/CLI names. The live-agent smoke uses copied synthetic demo data and an operator-configured tool-capable model: one Analyst governed question and one Authoring first-run review path, recording actual events and final answers without editing observed calls. If credentials/provider are absent, mark live acceptance **unverified**, not passed. No provider-dependent CI gate, duplicate numeric oracle, transcript ledger, HTTP UI or release is part of this plan; creating these tickets is not execution authority. At most one parent-authorized fix pass and one delta-only recheck; unresolved findings go to the owner.

Residual risk: packaged skill text contains CLI examples while the new backend offers native tools; the role mapping and real smoke must prove the model follows Ariadne's governed path rather than trying to invoke a nonexistent shell. `tau-mcp` packaging/version compatibility is a hard prerequisite for A3; local wheel installation is not permission to publish or push.
