# Implementation plan: Bounded record queries and query results

| | |
| :--- | :--- |
| **Status** | **Approved for S1–S3 ticketization, revision 1 — execution authority pending** |
| **Goal** | Deliver the approved non-metric record path and shared complete-output safeguards without changing aggregate inputs, admitted detail semantics or human admission. |
| **Behavioral source** | [Specification 0014, revision 1](../specs/2026-10-08-0014-bounded-record-queries-and-results.md). The owner approved its written revision with “approved” in this Pi conversation, 2026-10-08, after being asked for written-specification review. The owner subsequently requested “ticketize” in this Pi conversation, 2026-10-08, authorizing publication of this revision's S1–S3 decomposition and canonical task ownership transfer only, not implementation. |
| **Architecture and terms** | [ADR-0019](../adr/0019-bounded-record-query-boundary.md), [shared ownership](../adr/0016-modular-core-git-authoring.md), [compiler](../adr/0008-own-sqlglot-compiler-agpl-exit.md), [source registry](../adr/0010-declarative-source-registry.md), [CONTEXT.md](../../CONTEXT.md). |
| **Capture checkpoint** | Specification §10: vocabulary and consequential decisions captured; scope/acceptance approved; no material domain choice remains open. Technical prerequisites below must be proved before dependent work consumes them. |
| **Contract** | planning-contract v1; installed planning/shape/orchestration skill revision provenance unknown. |
| **Task ownership** | [S1 #56](https://github.com/legout/ariadne/issues/56), [S2 #57](https://github.com/legout/ariadne/issues/57) and [S3 #58](https://github.com/legout/ariadne/issues/58) in the [configured GitHub tracker](../agents/issue-tracker.md) own the canonical task bodies. This thin overview retains shared prerequisites, interfaces, coverage and global validation/review; do not maintain duplicate editable task definitions. |

## 1. Baseline, authority and prerequisites

Inspected code baseline: `77d57f32559684b4b8a2e63461822a0f701ec3aa`. The approved specification/ADR/glossary and scoped reconciliation are local, uncommitted artifacts; do not dispatch from a remote checkout lacking them. At execution preflight pin the exact approved source files/digests and an owner-accepted clean code base in the orchestrator's existing run manifest. Preserve the original checkout's documentation; no automatic stash, reset, commit or publication follows this plan.

Use **one sequential writer**: S1 → S2 → S3. All slices share Query/adapter/guidance surfaces; none is parallel-ready. Execution routes through `orchestrate-implementation`, supervised by default. Resolve executable worker/reviewer roles and any explicitly selected backend at that later preflight; missing tooling never authorizes silent fallback. Plan approval alone does not authorize writers, tests or builds. Candidate assembly, local integration, commits/pushes, project admission and release retain separate approval gates.

Reuse Python >=3.12, DuckDB, SQLGlot, stdlib serialization/timezone support, PyYAML and the optional existing MCP extra. No new engine, dependency, service, pool, generic SQL tool, export cache or second compiler. Follow root `AGENTS.md`, `pyproject.toml`'s Ruff/format conventions and the scoped specifications. The supplied private Trace Data project is evidence only, never an execution fixture or migration target.

### Blocking technical evidence within the first consuming slice

- **S1:** demonstrate output guards before Python transfer, bounded cursor collection, exact core/actual SDK result-envelope accounting, and a bounded collision-safe staging receipt **before any definition write**. Inspect the resolved supported MCP SDK; do not assume a dict's JSON size equals its tool-result envelope or reserialize differently after preflight. Failure to establish these properties blocks S2, not merely a test assertion.
- **S1:** prove the existing owned-connection deadline/source-setup mechanism covers request-time construction and can stop the operation. No timeout engine replacement or success-after-expiry fallback.
- **S2:** establish available timezone data/backend support for strict Berlin parsing, including both DST rejection examples in specification §7 V1. Use stdlib `zoneinfo` where appropriate; no new dependency, lexical-time ordering or guessed offset. If the prescribed behavior cannot be delivered, stop for source/design reconciliation rather than weakening it.
- **S3:** resolve a candidate-bound native test environment with the declared `tau_agent`/`tau_mcp`, MCP and pytest dependencies, plus an actual provider/client environment for genuine answer evidence. The earlier `uv run --with-editable` recipe has a reported native `tool.uv.sources` path-map problem; do not repeat it blindly or alter manifests. Missing tooling/evidence remains blocked/unverified.

These are prerequisites for implementation and acceptance, not claims that probes/tests have run during planning.

## 2. Shared implementation contracts

Behavior and ceilings remain owned by specification §§3–6. This section fixes only the decomposition's consumed interfaces.

### Operator configuration

Use an optional **`query:`** section in the host project's `ariadne.yaml`, with these closed keys mapped to specification §4:

| Key | Bound |
| :--- | :--- |
| `max_rows` | Returned result rows |
| `response_bytes` | Complete serialized core response |
| `cell_bytes` | One serialized result cell |
| `mcp_response_bytes` | Complete MCP tool-result envelope |
| `execution_seconds` | Shared execution deadline |

Defaults and tightening-only validation come from the specification, not request fields. Validate integer byte/row limits and finite positive seconds, reject booleans/unknown keys/attempted increases, and reject budgets unable to represent the selected transport's compact refusal before using them.

Managed factories read the **logical host project** configuration, never the pinned candidate/snapshot's limit section. CLI legacy use reads the fixed host CWD configuration; MCP reads its one launch-selected project. An explicit legacy `--sources` remains source identity, not a second implicit limit root. Direct Python construction may receive validated limits through a keyword-only host argument, otherwise uses built-ins. No tool/request schema accepts host budgets, a project root or a codec.

### Owners and seams

- **`src/ariadne/query_results.py` (new):** shared query-limit validation, existing-compatible scalar JSON encoding, complete-response accounting and bounded structured refusal. Its job is today's five result operations and adapters, not a generic response framework. Core imports no MCP or workflow module through this helper.
- **`render.py` / `planner.py`:** compiler-owned output-guard construction over an already completed logical query. Output schema/type information permits variable-sized cell guards before transfer. Preserve logical SQL/provenance separately from the actual guarded execution SQL; no result guard enters aggregate inputs or window lookback.
- **`DuckDBExecution`:** add bounded query collection alongside the existing trusted profiling/validation operations. It consumes only compiler output, returns bounded selected values plus overflow/existence facts, and owns cursor/connection cleanup. Migrate all four current Query `fetch` callers together; do not apply query budgets to unrelated audit/profile inputs.
- **`QueryRuntime`:** coordinate limits, one remaining-seconds `DeadlineBudget`, compile/bind/live audits, complete metadata/context, response preflight and ad-hoc staging. Host-only budget/preflight plumbing is private or keyword-only; adapters share it during request-time factory construction. Reused sessions start a fresh operation budget, not a new allowance per statement.
- **Adapters:** supply the actual selected representation's preflight before staging. CLI keeps one JSON stdout success or bounded stderr refusal/nonzero exit. MCP preserves `isError` and structured refusal rather than returning a successful prefix. Native wrappers preserve bounded core errors/results without gaining record-query permissions. Optional MCP remains optional.
- **Proposals:** any receipt-planning extension remains inside the shared ad-hoc staging owner. Establish a safe serialized receipt reservation across valid collision-suffixed paths, or an equally safe preflight-before-write mechanism. An exists-then-stage guess that can choose a longer path after preflight is insufficient; do not redesign Git proposals or promise transactional I/O/exactly-once delivery.

S1 seals these actual internal signatures and codec/receipt behavior before S2 consumes them. S2 adds `plan_records(catalog, request, connection)` / a record plan inside the existing Planner ownership and transport-neutral `QueryRuntime.query_records(request)`; these use known physical catalog identities, never the admitted detail traversal or supplied source SQL. Reuse literal/comparison builders, but record-only null/regex operators must not silently widen existing metric-request semantics.

## 3. Sequential tracer-bullet slices

Canonical sources, owned files, consumed/produced interfaces, checkbox steps, validation obligations, focused commands and completion criteria live only in these issues:

- **S1:** [#56 — Bound existing query answers end to end](https://github.com/legout/ariadne/issues/56) — V2/V3 (`new-test`), high-risk shared collection/preflight/deadline contract.
- **S2:** [#57 — Deliver bounded record selection through core, CLI and MCP](https://github.com/legout/ariadne/issues/57) — blocked by accepted S1; V1/V4 (`new-test`), high-risk record/schema contract, plus V2's new-consumer lookahead control.
- **S3:** [#58 — Reconcile guidance and prove installed-client behavior](https://github.com/legout/ariadne/issues/58) — blocked by accepted S2 and the native/provider/build prerequisites; reuses V4's schema obligation and existing delivery/answer checks rather than duplicating business tests.

Sequence: **#56 → #57 → #58**. Native GitHub blocked-by relations encode the predecessor chain. Closure alone is not accepted contract/source evidence or execution authority. Shared write targets require one sequential writer; no task is parallel-ready.

## 4. Requirement coverage, final validation and review

All numbered criteria refer to specification §7, not new behavioral requirements:

| Criteria | Owning slice / evidence |
| :--- | :--- |
| 1–5 | S2 / V1: records, ties, filters, suffix, clock/DST, request and admission boundaries |
| 6–8 | S1 / V2: post-computation row/cell/type/full-core/MCP limits; S2 adds lookahead control |
| 9 | S1 / V2/V3: refusal stages nothing, bounded retry and collision preservation |
| 10 | S1 / V3: shared setup/audit/collection budget and owned cancellation |
| 11 | S1–S3 / existing golden, grain, admission, context/quality and adapter checks |
| 12 | S2 / V4 schema check; S3 preserves native permission/guidance contracts |
| 13 | S3 / exact installed CLI/Streamable HTTP and genuine Open WebUI/model evidence |

Specification §§1–6 and §8 are covered by the slice sources and shared contracts; §9 is explicitly not a repair task. Operator limit ownership and no-input-limit invariants bind all slices. Do not mark final acceptance while a listed required check or prerequisite is missing.

There is no separate ordinary CI workflow in the inspected checkout; [publish.yml](../../.github/workflows/publish.yml) owns the tag-gated package build/test convention, not permission to trigger publication. On the exact assembled candidate, run the root suite **once** (`uv run --no-sync pytest -q`), existing Ruff/format and active LSP checks on changed Python paths, and `git diff --check`. The focused new tests and preserved numerical/admission/Policy checks cover this change; no production scan/benchmark is required. Separate pre-existing failures from regressions and obtain owner disposition rather than weakening assertions or silently skipping a gate.

Reviews are orchestrator-owned: immediate high-risk boundary review after S1 before S2, immediate record/public-contract review after S2 before S3, then one candidate review of unreviewed S3/integration effects. Paste the complete installed orchestrator/guardrails reviewer contract, actual criteria, written conventions, real callers and generated-test failure modes into every fresh read-only reviewer prompt. Parent alone authorizes repairs: at most one fix pass and one delta-only recheck, then hand unresolved blockers to the human. Do not add a review ledger or reopen settled findings.

Runtime security scope: external/model request identities and filter values must never become SQL fragments or new filesystem/source authority; host ceilings must not be model-controlled. Real callers are CLI/Python, Analyst/Combined MCP (including Open WebUI) and existing native tools. The assets are source/host data outside the selected catalog and bounded result delivery through the gateway. A less-trusted consumer submitting SQL-shaped identifiers/literals is the constrained input path to check, not evidence of an exploit or authorization for a new deployment. Deployment-specific attacker/authorization facts remain unverified; trusted host/project files are not hostile by default. Check the actual serializer before staging, without invented stolen-secret/malicious-admin stories. The separate ad-hoc SELECT-source containment report remains unresolved and unverified in the deployed environment; do not call this candidate safe for less-trusted Analyst source SQL.

Planning validation is **low risk / existing-check**: parent source/decomposition inspection, all criteria mapped, files/links/examples/whitespace checked, and document-only VCS delta. No feature tests, data-source queries, timezone probe, wheel build, provider run or exploit were executed while writing this plan. The vault index had no directly applicable Ariadne bounded-query contract; the approved repository sources remain authoritative.

**Next gate:** explicit execution authority and the source/tooling/evidence prerequisites in §1. The owner requested “ticketize”, authorizing only revision-1 S1–S3 publication and canonical ownership transfer to #56/#57/#58. Hand off those canonical issues, the exact approved revision-1 specification/ADR/shared overview, capture-checkpoint result and planning-contract v1/current installed provenance to `orchestrate-implementation` only after the execution gates are satisfied. No workers, additional tickets, private-project writes/admission, feature tests/builds, candidate assembly/integration, commits/pushes, deployment or release are authorized by ticketization. These new source documents remain local/uncommitted; publishing issues does not publish a runnable source handoff.
