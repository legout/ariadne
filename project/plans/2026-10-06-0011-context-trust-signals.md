# Implementation plan: Advisory Context trust and lifecycle signals

- **Status:** Approved, revision 2 — ticketized. Implementation, integration and code/release publication remain unauthorized.
- **Workflow migration approval:** Owner requested “can you execute the recommende migration for me?” in Pi session `01a115c0-1a8b-7099-87c3-df0aa8d87abc`, 2026-10-07. Revision 2 reconciles validation policy, current handoff facts and review/evidence sequencing without adding feature scope. It authorizes these document and existing-issue edits only; feature implementation, source/report acquisition, candidate assembly/integration, deployment, commits/pushes and releases remain separately gated.
- **Migration provenance:** planning-contract v1; the three installed workflow skills link to `~/.agents/skills` and matched `legout/skills@dfaf232` during migration; setup package `pi-implementation-orchestrator@5d8b56b`. Historical planning provenance remains unknown. Each execution run records its actual installed provenance, selected backend and executable roles.
- **Documentation publication approval:** Owner requested “commit and push all changes” in this Pi conversation, authorizing the current documentation delta only. Implementation, source/report acquisition, candidate assembly/integration and code/release publication remain separately gated.
- **Ticketization approval:** Owner requested “ticketize plan 0011” in this Pi conversation, authorizing the three GitHub tickets and this canonical-ownership transfer only; not implementation, source access, candidate assembly, commits/pushes or releases.
- **Plan approval:** Owner answered “yes” to “Approve proposed plan revision 1?” in this Pi conversation. Approval covers the unchanged three-task decomposition, interfaces, validation and review gates; it does not authorize execution.
- **Goal:** Deliver the approved reader/disclosure improvements through existing Context operations and answer guidance, preserving governance and numeric behavior.
- **Behavioral source:** [Specification 0011, approved revision 2 — workflow amendment only](../specs/2026-10-06-0011-context-trust-signals.md). Original revision-1 approval: owner approved the complete in-chat design and then this written specification with “approved” in the Pi conversation, 2026-10-06. The latter opens planning, not execution.
- **Supporting evidence:** [Anthropic self-service analytics assessment](../research/2026-10-06-anthropic-self-service-analytics-assessment.md) — rationale only; broader domain-answer evaluation and source freshness/completeness remain separate shaping follow-ups, not 0011 tasks or acceptance criteria.
- **Architecture/vocabulary:** [CONTEXT.md](../../CONTEXT.md), [ADR-0007](../adr/0007-okf-bundle-structure-agent-generation.md), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md), [ADR-0016](../adr/0016-modular-core-git-authoring.md), [ADR-0017](../adr/0017-context-schema-and-identifier-knowledge.md).
- **Contract:** planning-contract v1; installed skill provenance unknown.
- **Task ownership:** [#47](https://github.com/legout/ariadne/issues/47), [#48](https://github.com/legout/ariadne/issues/48) and [#49](https://github.com/legout/ariadne/issues/49) own the canonical task bodies in the [configured GitHub tracker](../agents/issue-tracker.md). This thin overview retains shared prerequisites, requirement coverage and global validation/review; never maintain duplicate editable task definitions.

## 1. Readiness and baseline

Capture checkpoint is complete: the owning glossary contains the resolved trust/freshness terms; no new ADR is warranted; scoped source references are reconciled; specification 0011 owns the approved behavior, non-goals and acceptance examples. No material shaping choice remains open. The owner has approved plan revision 1; explicit execution authority and the operational prerequisites below are still required.

Published pre-migration source/code baseline: `fce02c9230397f84736e323ea12efe4b993cc129` (including approved revision-1 specifications/plans). Revision 2 is the owner-approved local workflow amendment until separately committed/published; supply its exact source files/digests in the execution handoff, not a remote checkout containing only revision 1. The `ab8c0377f992db4857678420b3022560c01d2532` code hyperlinks in the issues are historical inspected permalinks, not missing-source claims. Select an owner-accepted clean execution base while preserving the original checkout's unrelated changes, including its existing `AGENTS.md` delta; no stash/reset/deletion or unrelated integration is authorized.

Use one sequential writer; tasks share Context/test files and are not parallel-ready. Execution routes through `orchestrate-implementation`, supervised by default. Use builtin `worker` and fresh read-only `reviewer` by default; explicit `herdr-pane`/`paseo` selections require their own backend/role preflight and recorded identities, not silent fallback. Candidate assembly, integration and publication retain their own approval gates.

Reuse Python >=3.12, stdlib date/time/serialization, PyYAML, existing Query/Authoring wrappers and the installed dependencies. Distribution names are `ariadneai`/`ariadneai-agent`; the import namespace remains `ariadne`. Do not add dependencies, producer changes, new tools/permissions, traversal, receipt infrastructure, arithmetic changes or unrelated cleanup.

Real callers are local JSON CLI, optional MCP registrations, native role tools and Python consumers over admitted/candidate OKF pages. Those paths already distinguish staged/candidate/admitted identity. Trusted project-owned artifacts are not hostile by default; security: n/a for this planned change. Preserve existing containment, source/revision/admission checks and read-only execution. If implementation would touch a new boundary, stop and reconcile scope rather than inventing a threat model.

### Environment prerequisite

Observed during the 2026-10-07 migration: root `.venv` exposes pytest/MCP but not `tau_agent`/`tau_mcp`; `ariadne-agent/.venv` now exists and exposes pytest, `tau_agent` and `tau_mcp`, but not MCP. `/home/volker/coding/tau-mcp` exists and matches the development mapping's location. Import discovery does not establish the approved dependency versions or candidate-bound native test compatibility. Resolve/verify that combination before native checks; the existing candidate-bound invocation below remains the fallback, not permission to change manifests.

Before native-adapter checks, resolve an operator-approved `tau-mcp` checkout or compatible installed environment. Do not change dependency versions/source configuration, guess a checkout, substitute an unrelated package, or label unavailable checks passing. Before actual Agent evidence, resolve a fresh Pi/provider environment. The named `refresh-ariadne-agent-trace` procedure referenced at ticketization is not installed in the checked locations; use specification 0003's evidence discipline explicitly: isolated synthetic fixtures, built/installed candidate skill digest verified before calls, actual CLI events/results and verbatim answers, session reference/hash, independent SQL oracle, independent re-extraction and byte comparison. No second harness or manufactured trace is needed.

Known pre-existing baseline gate: `tests/evals/agent_trace.json` records skill digest `d713bf76b299a6487e1d6359911db9371179b8dee1db90df540e873acc340394`, while the pre-migration packaged skill hashes to `1a420d76f4095c56d2ac2e2fb7a15570f04820f51449748fdda5208cb861a1a9`. `tests/test_agent_trace.py` rejects this mismatch. Separate it from worker regressions at the fast baseline and obtain permission to proceed with that known failure or refresh genuinely observed evidence. T3 owns the candidate-bound refresh; never fix only the hash or claim the root suite was green.

## 2. Sequential tracer-bullet slices

Canonical task bodies, owned files, interfaces, checkbox steps, focused commands and completion criteria live only in these GitHub issues:

- **T1:** [#47 — Correct freshness through the existing term-resolution path](https://github.com/legout/ariadne/issues/47).
- **T2:** [#48 — Disclose shared signals through existing context operations](https://github.com/legout/ariadne/issues/48) — blocked by #47.
- **T3:** [#49 — Carry relevant caveats into actual Agent answers](https://github.com/legout/ariadne/issues/49) — blocked by #48.

Sequence: **#47 → #48 → #49**. Native GitHub blocked-by relations encode the predecessor chain; they do not replace source/environment/execution gates. U1 covers T1/T2 (**high risk**, **new-test**), with its immediate public-contract review accepted after T2 before T3. U2 covers T3 (**normal risk**, **new-test**) and genuine observed Agent evidence. Shared files require one sequential writer; no task is parallel-ready.

## 3. Requirement coverage

All AC numbers reference specification §8:

- AC1/2: T1 — instant/native/legacy/unknown interpretation and boundary behavior.
- AC3/4: T2 — metric/Policy warnings, successful bodies, numeric invariance and non-failing required-context fallback.
- AC5: T2 — separate document/admission axes and staged/candidate restrictions.
- AC6: T2 — lexical payload/ranking preservation and bounded term disclosure.
- AC7: T2 — consumed-set limit and unchanged mapping-evidence gates; T1 preserves its temporal distinctions.
- AC8: T3 — actually observed relevant caveat and controls; no invented attestation.
- AC9: T1/T2 — read-only and producer/admission preservation; T3 — unchanged role permissions and packaged delivery.

The specification's non-goals bind every task. Baseline safety/refusal checks are preserved, not redefined as advisory.

## 4. Global validation, review and handoff

Use the existing [tag-gated build/test workflow](../../.github/workflows/publish.yml) as evidence of packaging conventions, not as permission to release. There is no separate ordinary CI workflow in the inspected checkout. Do not repeat a full lint/build/test matrix in each task.

On the exact assembled candidate:

1. Run the root suite once: `uv run --no-sync pytest -q`. This reuses golden numerical, fan-out, retrieval, admission, producer and trace checks. Build/install the candidate wheel in the isolated trace smoke when validating the changed packaged skill; its installed digest must match the candidate source. No tag or publish job runs.
2. Run the focused native adapter checks in the resolved approved environment. If using an approved local checkout, set `TAU_MCP_CHECKOUT` to that real path and use the following candidate-bound invocation rather than the broken development source mapping:

   ```sh
   uv run --no-project --with pytest --with 'mcp>=1.2,<2' \
     --with-editable . --with-editable ./ariadne-agent \
     --with-editable "$TAU_MCP_CHECKOUT" python -m pytest -q \
     ariadne-agent/tests/test_analyst.py \
     ariadne-agent/tests/test_authoring.py -k 'analyst or resolve_term'
   ```

   This uses the declared packages/versions and candidate sources; it does not change manifests. If the approved dependency source/environment cannot be resolved, stop rather than silently skipping the native contract.
3. Run existing Ruff/format checks scoped to changed Python files and active LSP checks on changed paths; investigate environment-only diagnostics without calling an empty cache clean. Run `git diff --check` and inspect the final source/fixture delta for producer, permission or unrelated changes.
4. Parent owns review/disposition. U1 receives one immediate fresh read-only public-contract review before T3 consumes it. The final candidate review covers T3 and integration effects without reopening settled U1 findings. Use the full guardrails/orchestrator dispatch contract, exact criteria, real callers and written conventions. At most one authorized fix pass and one delta recheck; unresolved blockers go to the human.

Focused new-test expectations come from specification 0011 §3/§8, not parser/helper output. Preserve failing-first evidence for T1's explicit-offset bug; new T2/T3 behavior may choose ordering. The reviewer brief must include the generated-test failure modes in `AGENTS.md` (mirrored structure, over-mocking, weakened assertions, implementation-derived expectations).

Residual operational risks are the native test environment and actual provider-dependent Agent evidence. Both have explicit gates; neither is proven by this planning task. No additional manual production/live-data check is required by this reader-only scope.

Planning-document validation is **existing-check**: source/capture alignment, task/interface/AC coverage, local links, whitespace and the documentation delta. No runtime test pass is claimed here.

Plan revision 2 is owner-approved and ticketized by separate owner request. The next handoff is the canonical tickets, exact revision-2 source, capture result and planning-contract v1/current installed provenance recorded above to `orchestrate-implementation`; explicit execution authority remains pending, so do not dispatch yet. Ticket publication is authorized only for the three listed tasks; candidate assembly, integration, source access, commits/pushes and releases retain separate applicable approval gates.

Use the installed orchestrator's durable acceptance boundary for every mutation lane, even if its worker checkout survives: pinned named base/ref and SHA, complete binary-capable patch/digest, and parent-owned reconstruction with verified tree identity before acceptance. Record identities/review ranges in its existing run manifest, not new ledgers. Reuse focused-check evidence only for the identical tree and relevant environment; otherwise run the affected check on the reconstructed tree. Full replacement patches supersede their lane's prior patch; recheck only the prior-review-to-replacement delta, without resetting the one-fix/one-recheck limit. Candidate assembly and target integration retain their separate authority gates.
