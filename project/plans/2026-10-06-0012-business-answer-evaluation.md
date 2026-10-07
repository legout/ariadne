# Implementation plan: Business-answer evaluation

- **Status:** Approved, revision 1 — ticketized. Implementation, source/report acquisition, integration and code/release publication remain unauthorized.
- **Documentation publication approval:** Owner requested “commit and push all changes” in this Pi conversation, authorizing the current documentation delta only. Implementation, source/report acquisition, candidate assembly/integration and code/release publication remain separately gated.
- **Ticketization approval:** Owner requested “ticketize the plans” in this Pi conversation, 2026-10-06, authorizing this plan's three GitHub task tickets and canonical-ownership transfer only; not implementation, source access, candidate assembly, commits/pushes or release.
- **Plan approval:** Owner replied “approved” to “Approve both plan revisions—planning only?” in this Pi conversation, 2026-10-06. Approval covers this unchanged E1–E3 decomposition, case/checker interfaces and validation/review gates; it does not authorize implementation, private access, integration or publication.
- **Goal:** Extend the existing answer evidence with intended-question checks, a small synthetic corpus and a separately reported private Trace Data brakes slice.
- **Behavioral source:** [Specification 0012, approved written revision 1](../specs/2026-10-06-0012-business-answer-evaluation.md). Owner answered “approved” after the written-specification review request in the Pi conversation, 2026-10-06. That opens planning only.
- **Preserved sources:** [Agent-trace specification 0003](../specs/2026-09-23-0003-agent-answer-trace-evaluation.md), [Context trust specification 0011](../specs/2026-10-06-0011-context-trust-signals.md), [source-quality specification 0013](../specs/2026-10-06-0013-source-quality-evidence.md), [CONTEXT.md](../../CONTEXT.md), [ADR-0016](../adr/0016-modular-core-git-authoring.md).
- **Contract:** planning-contract v1; installed skill provenance unknown.
- **Task ownership:** [50](https://github.com/legout/ariadne/issues/50), [51](https://github.com/legout/ariadne/issues/51), [52](https://github.com/legout/ariadne/issues/52) own the canonical task bodies in the [configured GitHub tracker](../agents/issue-tracker.md). This linked overview retains shared prerequisites, exact interfaces/bounds, requirement coverage and global validation/review; never maintain duplicate editable task definitions.

## 1. Readiness, dependencies and authority

Capture is complete: the specification owns approved behavior/acceptance; existing vocabulary suffices; no new ADR is warranted. This plan resolves fixture/checker organization. Private meanings, reviewed oracles, fixed-slice identity, permitted evidence storage and provider access are evidence prerequisites, not permissions supplied by this document.

Inspected baseline: `ab8c0377f992db4857678420b3022560c01d2532`, with approved sources and unrelated work locally uncommitted at ticketization; the documentation is now included in the separately authorized publication. Before implementation, obtain an owner-accepted clean candidate containing the exact approved sources. Do not reset/stash the original checkout or silently omit its approved documents. Re-read any accepted 0011/0013 candidate before consuming its actual interfaces; neither workstream's tasks or acceptance criteria change here.

Use one sequential writer, existing Python >=3.12, pytest, DuckDB, stdlib JSON/hash/CLI parsing, and the current Pi/local-CLI trace approach. No new dependency, evaluation service, Agent harness, production API, metric definition, automatic judge or permission is needed. Execution routes through `orchestrate-implementation`, supervised by default; confirm executable builtin `worker` and read-only `reviewer` and record resolved names in its existing run manifest before dispatch.

E1 can proceed on an authorized baseline without private data or 0013. E2 consumes 0011 lifecycle evidence only after that work is accepted; until then the dependent evidence is explicitly unverified. Source-quality answer cases are likewise conditional on accepted 0013, not new 0012 requirements. Skill-changing candidates must serialize with E2/E3 observations: a run against a different skill is not evidence for the final candidate. Do not authorize parallel writers by giving them different case files.

The evaluator/operator can use approved oracle SQL; the answering Agent cannot. Inputs are owner-curated local evidence, not public uploads. Security: n/a for this bounded evaluation extension; preserve private-data handling, existing source approval and fixed-role permissions. If implementation requires new external access or a new trust boundary, stop rather than expand this plan.

## 2. Case, observation and report interfaces

Create [tests/evals/business_answer_cases.json](../../tests/evals/) for generic synthetic contracts and [tests/evals/business_answer_trace.json](../../tests/evals/) for their bounded **observed** evidence. Keep [tests/evals/agent_trace.json](../../tests/evals/agent_trace.json) and its original checker/oracles intact. New files are additive fixtures, not a second run registry. A generated report is execution output, not another tracked status ledger.

Both new JSON inputs have `version: 1`. A case has:

- `id`, `domain`, `question`, `source_refs`; `meaning` records entity/population, period/timezone, units, grain and denominator, with explicit null for inapplicable fields.
- `expected_outcome`: `answer`, `clarification` or `unsupported`; clarification uses `clarification: {issue, follow_up}` where the follow-up is declared before observation.
- `route`: allowed operations, governed/ad-hoc status and substantive parameter/definition assertions. Compare parsed operation arguments and returned definitions, not an incidental command sequence.
- `oracle`: existing named synthetic oracle, or operator-supplied reviewed SQL file/digest and snapshot manifest; row/key comparison and absolute/relative tolerance are explicit. Non-numerical cases declare why an oracle is inapplicable.
- `explanation`: required consequential caveats, permitted citations and truthful labels. Unresolved interpretation/prose checks require recorded human disposition; they never default to pass or an LLM vote.

An observation references `case_id`, available model/provider identity, code/artifact revision, installed skill digest, snapshot identity, session/run identity and source hash; ordered actual calls with exit/results; verbatim final answer; and any declared clarification exchange. Token/latency fields are nullable when unavailable. Capture bounded case-relevant events, not hidden reasoning, credentials or a full transcript archive. Keep the original session reference/hash needed for independent re-extraction; private sessions remain private.

The operator snapshot manifest has `version: 1`, `id`, and `inputs: [{source, kind, path, sha256}]`, where kind is `sqlite|duckdb` for this bounded local checker. It also records the same approved snapshot/source identity used in the observation. Paths are operator-resolved local inputs, never fetched/discovered from citations. A numerical `oracle` names either an existing synthetic oracle and its input source, or a reviewed SQL file, its digest, input source and human review reference. `comparison` declares `row_keys`, ordered/unordered semantics and numerical tolerances; no executable callback/plugin or generated Ariadne SQL substitutes for independent truth. Private manifests, review references and SQL remain private.

The checker emits `version`, `candidate`, and `cases` with per-axis `interpretation`, `route_parameters`, `values`, `explanation` and `provenance` outcomes/reasons. Case disposition is `pass`, `fail`, `coverage_gap` or `unverified`; `missing_prerequisites` is explicit. Report recorded-run and current-Agent evidence separately. A detected wrong route/value/meaning remains failed even if another prerequisite is unavailable; otherwise no overall pass is possible with unverified required axes. Summaries count each disposition by domain and cannot hide case IDs/reasons. Do not create an accuracy threshold.

Use input versions and configured JSON/row bounds consistently in the checker: reject malformed/unsupported input rather than silently skipping a case. Start with at most 16 cases and 64 call events per case, at most 1,000 captured rows per result, and a 1-MiB UTF-8 JSON bound per case observation. A cap that prevents complete evidence makes the affected assertion unverified; it is not permission to compare only a convenient result prefix. These are harness bounds, not new runtime limits.

## 3. Sequential slices

Canonical task bodies, owned files, consumed/produced seams, checkbox steps, focused commands and completion criteria live only in these issues. Shared contracts remain in §2 of this overview.

- **E1:** [#50 — Detect a correct calculation for the wrong question](https://github.com/legout/ariadne/issues/50).
- **E2:** [#51 — Observe the bounded synthetic business cases](https://github.com/legout/ariadne/issues/51) — blocked by #50.
- **E3:** [#52 — Evaluate private Trace Data brake cases without publishing them](https://github.com/legout/ariadne/issues/52) — blocked by #51.

Sequence: **#50 → #51 → #52**. Native blocked-by relations encode this predecessor chain; issue closure does not replace source/environment/candidate-acceptance/execution gates. Shared write targets require one sequential writer; no task is parallel-ready.

V1 covers E1's consumed checker contract (**high risk**, **new-test**) and receives immediate review before E2/E3 use it. V2 covers E2 (**normal risk**, **new-test**) plus genuine synthetic observations. V3 covers E3 (**normal risk**, **existing-check**) plus separately authorized private reviewed-SQL/Agent evidence; a generic checker behavior change still requires its named synthetic failing-first reproduction. Conditional 0011/0013 evidence and private/provider gates remain as approved, not invented passing results or unconditional new dependencies.

## 4. Coverage, global verification and handoff

Specification §6 coverage: AC1 → E1/E2 preserved oracles/trace; AC2 → E1/E2 interpretation; AC3 → E2 clarification; AC4 → E2 temporal/population/unit control; AC5 → E2 grain/repeats; AC6 → E3 reviewed private slice; AC7 → E1/E3 coverage gap; AC8 → E1–E3 recorded/current provenance; AC9 → all slices permissions/source/admission preservation.

On the exact assembled candidate, run the root suite once with `uv run --no-sync pytest -q`; run existing Ruff/format and active LSP checks on changed Python paths; run `git diff --check` and inspect the complete source/fixture delta. Root checks include existing retrieval, numerical, grain, admission and historical-trace guarantees. No new native adapter matrix is needed: this work does not change native/runtime contracts. Actual Pi observations, oracle review and privacy inspection are the additional evidence, not substitute suites.

Parent owns disposition and one final fresh read-only candidate review for unreviewed changes/integration effects; V1 receives the earlier contract review only because later cases depend on it. Paste the full guardrails/orchestrator reviewer contract, criteria, written conventions and real callers into each fresh prompt. At most one authorized fix pass and one delta-only recheck; unresolved findings go to the human. A correctly reported failed business answer is evidence, not authorization for evaluator-driven product repairs.

Residual gates: provider access, human case/oracle review, private acquisition/retention, fixed-slice correspondence and conditional 0011/0013 evidence. Planning validation is **low risk / existing-check**: approved-source alignment, coverage, local links, whitespace and parent document inspection. No runtime tests, snapshots or actual Agent runs were performed during planning.

**Next gate:** explicit execution authority and the operational prerequisites in §1. Plan revision 1 is owner-approved and ticketized by separate owner request. Hand off the canonical tickets, exact approved sources and planning-contract v1/provenance unknown to `orchestrate-implementation` only when those gates are satisfied. Ticket publication is authorized only for the three listed tasks; implementation, private access, candidate assembly/integration, commits/pushes and release retain their applicable authority gates.
