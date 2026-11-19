# Plan 0036: Production-relevant test-suite cleanup

> **Superseded** by [spec 0038 / plan 0038](2026-11-19-0038-lean-baseline.md) under umbrella spec 0037 (2026-11-19). Never approved; kept as history.

Status: **proposed, revision 1**, 2026-11-12.
Plan requested by the owner: **“ok. erstelle dafür einen Plan”**.
Execution, child dispatch, tests/builds/installs, API removal, tracker mutation,
Git commit/push, integration and release: **not authorized by this request**.

## Goal, sources and capture checkpoint

Keep tests that detect reachable production failures; retire obsolete behavior,
consolidate demonstrated duplicates and repair misleading fixtures/oracles.
No percentage/line-count target, end-to-end-only policy, replacement framework,
new dependency or broad security/coverage campaign.

Authority is the owner's bounded cleanup request **plus the unchanged product
contracts**, not the audit alone:

- [Approved spec0035 r2](https://github.com/legout/ariadne/issues/108#issuecomment-6768381795):
  native Context, exact human admission, pre-SQL refusal, preserved numerical/
  source/provenance safeguards, non-mutating legacy refusal; §§3–6, AC1/3/6/7/10.
- [Approved spec0034 r6](https://github.com/legout/ariadne/issues/85#issuecomment-6768381020):
  scoped Workspace Evidence, original attribution and exact versions.
- [Lumio ADR-0022](../../products/lumio/project/adr/0022-retire-activity-log-artifact.md)
  and [ADR-0025](../../products/lumio/project/adr/0025-repository-split.md):
  retired new Activity Logs versus retained historical recognition; excluded
  private-app alias tests versus supported standalone Lumio.
- Evidence: [test audit, 2026-11-12](../research/2026-11-12-c6-test-suite-audit.md),
  frozen `d351aae1e1eda411f1bfb52d2ddb667ff867a662`. Its parent dispositions,
  especially the rejected LS-05 merge, outrank provisional reviewer suggestions.
- Execution coordination: [plan0035](2026-11-09-0035-lumio-owned-context-layer.md),
  canonical [C6 #114](https://github.com/legout/ariadne/issues/114) and
  [C7 #115](https://github.com/legout/ariadne/issues/115). Do not rewrite them.

The owner requested planning of the audit-backed cleanup, not approval of this
written plan or its execution. This is a bounded maintenance contract preserving
approved behavior; no new feature specification is needed. Capture checkpoint:
no new vocabulary or architectural choice. Existing glossaries/ADRs own those
scopes. Activity Log API retirement remains conditional under L below. Planning
Contract version 1; installed skill provenance `unknown`.

This file owns proposed tasks. No tickets are requested now. Later ticketization
requires its own grant and moves task bodies once to canonical issues, leaving
only links here. Do not create another editable task ledger.

## Baseline, ownership and scope

Observed C6 HEAD during planning:
`023fbfd674709503d12ea40a063466775da2b9f7`, clean at inspection; includes
`0f6f077` (bounded D1–D4 completion) and `023fbfd` (parent-audited changed-first-
member oracle). This is **not** a claim that C6 is accepted or CI is green.
The audit snapshot is older. Current root `main` is still `d2f8b75`; execution
must not silently use that older implementation or the active worker's dirty
files. Obtain a parent-released frozen result/base and ownership handoff.

C6's recorded exception is one D1–D4 completion with 20 approved selectors,
scoped Ruff and parent audit, **no third independent review**. This plan does
not expand/reset that grant. Remaining migration failures still belonging to
C6 need its parent's disposition; they are not silently transferred or waived.
An explicit separate handoff may assign residual test work to T2 without
changing the original product criteria or pretending C6 was complete.

The local audit and this plan are uncommitted. Before an authorized isolated
handoff, make their exact bytes and frozen source links available through the
existing run context; never assume an untracked file exists in a fresh worktree.
Preserve unrelated dirty documentation, historical records and external projects.

Repository-relative roots:

| Name | Root |
| --- | --- |
| A | `products/ariadne/packages/ariadne-data` |
| K | `products/lumio/packages/lumio-wiki` |
| LDB | `products/lumio/packages/lumio-lancedb` |
| W | `products/lumio/packages/lumio-workspace` |
| T | `products/lumio/tests` |
| I | `integration/tests` |

Python >=3.14; existing uv workspace, package configs, scoped AGENTS, Ruff and
pytest selections remain. Core focused checks run from A; Lumio focused checks
from `products/lumio`. Focused pytest is serial; full Lumio/root CI uses exactly
`-n 4`, never `-n auto`. Use existing supported environments; missing tooling
blocks the affected check, not permission to install or change the runtime.
For focused commands, expand K/LDB/W `tests/...` to
`packages/lumio-wiki/tests/...`, `packages/lumio-lancedb/tests/...` and
`packages/lumio-workspace/tests/...` from `products/lumio`; T is `tests/...`
there. A uses its own `tests/...`; I modules run explicitly from repository root.

Default later execution: one sequential Pi writer in an isolated registered
worktree, supervised under installed `orchestrate-implementation`. This plan
is not a second execution router. Test-only work does not change product code,
package metadata, auth, numerical rules, source grants or supported APIs. A
strengthened test exposing a product defect triggers parent disposition and,
when outside this scope, a separate repair grant—not a weaker expected result.

## Cleanup acceptance contract and coverage

Counts in the audit are candidates, not quotas. An already-removed/repaired or
newly non-equivalent candidate is skipped with evidence, not replaced by another
arbitrary deletion. KEEP preserves the actual production protection, not every
old test name. These maintenance criteria add no new product behavior.

| ID | Required maintenance outcome | Task / evidence |
| --- | --- | --- |
| TC1 | Exact released base and ownership; already-fixed audit items excluded; no C6 review reset or invented prerequisite edge | T0; source delta and parent handoff |
| TC2 | Only explicitly obsolete tests/assumptions removed; native refusal, optional/advisory and public SDK protections retained | T1; retained native guards and audit §1 |
| TC3 | All surviving consolidation candidates preserve unique assertions, persisted-manifest readback and legitimate backend/format distinctions | T1; retained nodes; rejected LS-05 merge stays rejected |
| TC4 | No stale/empty/tautological oracle for the named persisted-state, privacy, cache, ranking, eligibility or count scenario | T2/T3; repaired existing nodes against independent expectations |
| TC5 | Residual native fixtures reach their actual scenario without legacy fallback or bypassed consent/revision/Policy checks | T0/T2; explicit residual ownership and selected positive/negative control |
| TC6 | Packaging/CLI/launcher checks enforce current approved contracts, not old literals or ambiguous substrings | T4; source/archive/install/diagnostic checks at their distinct seams |
| TC7 | Claims match tested behavior; no new blanket Computation ban or duplicate attestation/provider journey | T2/T3; existing stronger coverage, source/rule disposition |
| TC8 | Activity Log cleanup is coordinated and separately authorized; legacy marked-log protection and required wheel proof survive | L if activated; otherwise explicitly deferred, not complete |
| TC9 | Scoped checks and required CI once per applicable candidate/delta; real skips/limits disclosed; no unsupported production-readiness claim | V; applicable C7/CI evidence reuse |

## Sequence and validation policy

**T0 → T1 → T2 → T3 → T4 → V**. If separately activated, **T4 → L → V**.
Shared native helpers, `test_git_authoring.py`, `test_kb_control.py` and wheel
verifiers favor one writer. An ownership-blocked Core item need not prevent
independent Lumio preparation in an explicitly rescheduled isolated lane, but
it remains incomplete; never report the whole approved scope finished.

Each unit is `existing-check` except T0 (`no-new-test`). Extend/repair existing
tests, not a new parallel suite. For a changed fixture, first establish the
valid predecessor and the intended named failure. For a genuine product bug or
behavior-pinning refactor, failing-first applies when practical; do not invent
failing-first runs for mechanical deletion or a corrected test oracle.

Focused node lists below are a selection rule, not a mandatory per-task matrix:
run only nodes whose scenario/fixture/assertion actually changed. Reuse existing
verified results when relevant inputs still match. T0 pins the exact applicable
selection in the existing run context before repair; no new ledger or budget
reset. A failure authorizes only its named investigation. Final thorough checks
belong to V; high-risk lost-protection/byte-integrity changes get their immediate
named check before subsequent edits could obscure the evidence.

## T0 — Reconcile the audit with the released C6 result

**Sources:** TC1/5; audit R1 and §6. **Risk:** normal; `no-new-test`.
**Owned surface:** this plan's correspondence/remaining-scope notes and existing
run context only. No source/test edits, new tracker, or change to C6/C7 grants.

- [ ] Obtain the exact committed C6 result, parent acceptance/disposition and
  file ownership. Compare it with both `d351aae` and observed `023fbfd`; inspect
  the actual diff, not an issue's OPEN/CLOSED label.
- [ ] Remove already-settled D1–D4 cases from this cleanup. In particular do not
  repeat the current `test_context_admission.py`, `test_review.py`, recovered
  refresh/bound/integer tests or installed walkthrough repairs just because
  the older audit lists them.
- [ ] For residual canonical migration work, record its owner and explicit
  handoff or return it to that owner. Closed/exhausted grants need a human
  decision, not automatic work under this new plan. Do not insert this cleanup
  as a new native dependency of #114/#115/#107.
- [ ] Confirm each proposed deletion still has its exact retained counterpart
  and authority; identify only actual remaining changed files/selectors.
- [ ] Inspect applicable existing focused evidence. Never assume a green base:
  a known red relevant baseline needs parent disposition before that lane's
  edits. If evidence is missing, use the next task's named minimal check only
  under execution authority, not an extra full baseline suite. A failed keeper
  means repair/handoff or a blocked consolidation, not silently deleting both.

**Check:** source/ref/cleanliness and targeted diff/identifier inspection only;
no broad baseline suite or pytest collection. **Done:** one frozen executable
base, bounded remaining scope and no competing writer. This is the first
execution checkpoint, not a new test audit or product acceptance claim.

## T1 — Prune only proven obsolete/redundant checks

**Sources:** TC2/3; audit §§1–2, including its exact 11-pair table.
**Risk:** normal test maintenance; `existing-check`.
**Owned files:** A `tests/{test_serve,test_init,test_git_authoring,test_evals}.py`;
I `lumio_local_context.py`; K `tests/{test_okf,test_link_candidate_graph_impact,
test_documents_extra,test_s3_publish,test_cli_open_actions,test_citation_actions}.py`;
LDB `tests/test_remote_index_binding.py`; T `test_graph_traversal.py`;
root `tests/test_workspace_certification.py`. Counterparts in other files are
read/reused, not rewritten without a named transferred assertion.

- [ ] Retire the two successful-governed missing-Context/Policy fallback tests
  and the excluded private-app alias test/helper. Keep native required-Context
  refusal and normal optional/advisory behavior.
- [ ] Perform surviving audit §2 consolidations atomically with transfers:
  first-part `complete is False`, persisted manifest JSON readback, and actual
  object-store source-URL suppression plus HTTPS/label controls. The last
  also resolves that part of R3; T3 must not redo it.
- [ ] Remove only the repeated ad-hoc refusal block, not its renderer numerical
  oracle. Remove `ariadne-ingest` from current registration expectations, not
  retained converters. Drop the obsolete classic index-only commit assertion,
  not draft recovery. Remove the three unreferenced P1 classic fixture constants
  only if current whole-tree reference search still finds definitions alone.
- [ ] Keep both flat and categorized rollback target cases; the rejected LS-05
  merge is not a deletion candidate. Keep real endpoint, protocol, install,
  permission, scope and exact historical-version distinctions.

**Check selection:** existing retained nodes for changed assertion transfers:
A `tests/test_git_authoring.py::test_review_parts_retrieve_every_artifacts_later_bodies`;
K `tests/test_s3_publish.py::test_publish_writes_a_digest_and_fingerprint_manifest`;
K `tests/test_citation_actions.py::test_rendered_source_lines_are_never_signed_or_object_urls`.
Use `uv run pytest -q <selected nodes>` from the owning root. Pure deletions also
get scoped Ruff/import/name inspection; do not add a live journey. Reuse native
I `lumio_metric_mvp.py` Context/refusal evidence if still valid; otherwise its
`test_corrupt_missing_or_mixed_release_refuses_before_sql` and
`test_hidden_required_policy_cannot_activate` are the named retained guards.
**Invalidation:** keeper/fixture/mark/oracle or native guard changes.
**Done:** no unique protection lost; counts may shrink below the audit's numbers
if upstream work or a disproved equivalence removed a candidate.

## T2 — Repair remaining Core/native reachability and honest oracles

**Sources:** TC4/5/7; audit R1/R2/R9/R14/R15. **Risk:** normal test work preserving
high-impact numerical/permission/data-loss guarantees; `existing-check`.
**Owned files, only for confirmed residuals handed off in T0:** A `tests/
{test_git_admission,test_context_admission,test_review,test_cli,test_contracts,
test_s3_storage_access,test_answer_examples,test_git_only,test_discovery,
test_mcp2_compatibility,test_mcp_toolsets,test_multifact,test_evals,test_serve,
test_query_results,test_sources,test_status,test_terms,test_git_authoring,
test_git_source_access,test_context_browsing,test_git_proposals,test_init}.py`;
I `{lumio_local_context,lumio_s3_context,workspace_data_sources}.py`.
A `tests/setup_wheel_walkthrough.py` stays with C7 unless explicitly handed off;
W `tests/test_workspace_retrieval.py` attribution adjustment likewise requires
its current owner. No Core/SDK/Workspace production implementation edits.

- [ ] Repair an actual shared native prerequisite once: valid KB/selector and
  Policy classifications; exact composite preview/confirmation; current
  revisions; actual citations/failure injection; correct operation support.
  Use existing native helpers; do not replace real admission with a mock.
- [ ] Preserve independent 150/2, 60, 300/400, endpoint A/B and exact integer
  oracles. Make positive governed tests reach SQL/numerical assertions and
  negative tests reach their named pre-SQL/grant/revision boundary.
- [ ] Upgrade legacy-refusal non-mutation checks to protected before/after bytes,
  retaining every distinct public-open case. For lookup coverage, assert the
  authored 3/6 result, not a fallback to the observed value.
- [ ] Migrate still-required metadata-only/exact-page/path browsing checks;
  discard only unsupported classic/no-title assumptions. Preserve actual
  `sources` attribution and exact historical binding where response shapes grew.
- [ ] Narrow pending-only attestation claims: the existing native integration
  `[changed-computation]` case already has an earned attester. Do not duplicate
  it. For the untitled Computation ownership subcase, retain real generated-
  facts protection, not an invented path-wide ban. Reuse the existing
  `test_native_generated_facts_are_protected_while_curated_body_is_editable`.
  A requested new ownership rule returns to the owner, outside this cleanup.

**Check selection:** one already-existing positive/negative consumer per changed
shared prerequisite, using audit-named functions; pin the exact remaining list
at T0. Explicit oracle nodes include A
`tests/test_mapping_inspection.py::test_the_three_families_report_honest_shape_evidence`,
`tests/test_git_authoring.py::test_unsupported_project_refuses_on_every_public_open_without_mutation`,
`tests/test_init.py::test_scaffold_refuses_a_retired_context_layer_project` and
`tests/test_context_browsing.py` (three existing cases). Do not rerun unrelated
C6 selectors. **Invalidation:** repaired helper, admitted content, consent,
revision/support or the particular oracle. **Done:** only remaining assigned
scenarios are repaired and observed at their intended boundary; unresolved
original feature obligations remain owned, never silently reclassified obsolete.

## T3 — Make existing Lumio production checks discriminate real failures

**Sources:** TC4/7; audit R2–R12/R14, excluding work already resolved by T1/T2.
**Risk:** normal test-only repair of privacy, persistence and retrieval proof;
`existing-check`. No product behavior, threshold policy or dependency changes.
**Owned files:** K `tests/{test_capture,test_managed_ingest,test_git_authoring,
test_graph_exchange,test_graph_state,test_semantic_maintenance,
test_dream_duplicate_candidates,test_dream_synthesis_impact,test_artifact_store,
test_env_loader,test_s3_publish,test_s3_publish_s3_compat,test_cli,test_llm_distiller}.py`;
LDB `tests/{test_remote_index_location,test_remote_lancedb_s3_compat,
test_graph_tables,test_ontology_parity}.py`; T `{test_graph_traversal,test_kb_control}.py`.

- [ ] Recapture persisted files after each refused managed ingest, not stale
  `kb.pages` or a prior `after` map. Compare rollback object bytes/digests, not
  just keys, preserving flat/categorized and real-store scenarios.
- [ ] Check the authored escaped-password/suffix in the real persisted capture.
  Fix the hidden-edge destination and establish a privileged positive edge
  before checking public omission. Keep current metadata/scope assertions.
- [ ] Use current valid nine-field graph edges before corrupting count/mirror;
  use a persisted Claim graph with a known nonempty path before reload equality.
- [ ] Healthy vector/hybrid retrieval must return authored matching Evidence
  through the intended backend, not merely a list or fallback. Add the matching
  graph-ineligible decoy to one existing parity case; retain empty-set and
  topology checks. This is fake-encoder wiring, not real-model certification.
- [ ] Make hub/strongest-first ranking disagree with lexical ordering in the
  fixture; preserve same-tier determinism. Read the first serialized bytes
  before overwriting; capture canonical identity before actual regeneration.
  Remove a bare fingerprint tautology if no distinct real operation belongs
  there; do not invent another invariance suite.
- [ ] Place the competing `.env` in the actual ancestor, remove the fixture
  pointer before absent-pointer rollback, and exercise the existing skipped
  DOCX/None-MIME record. Keep base-import/actual converter evidence separate.
- [ ] For faux provider parity, reuse the existing real-Distiller/fake-I/O
  routing case and preserve unique destination assertions, or name the actual
  default-passthrough contract. No extra provider journey or live model.

**Check selection:** only changed existing functions named in audit R2–R12/R14;
execute their qualified nodes with `uv run pytest -q <nodes>` from
`products/lumio`. A valid predecessor and discriminating authored result are
part of each repaired existing function, not new parallel tests. For the actual
S3 nodes, reuse a qualified named synthetic endpoint and valid unchanged proof;
missing authority/service is explicitly unverified, never a fake green skip.
**Invalidation:** that fixture/schema/parser, storage boundary, backend mode or
oracle. **Done:** each assigned check would detect its stated regression;
strengthened assertions exposing a real product defect stop for disposition,
not source repair or relaxed values under this test-only task.

## T4 — Align packaging and operational judges with current approved contracts

**Sources:** TC6; audit R13. **Risk:** normal artifact/gate repair;
`existing-check`. **Owned files:** root `tests/{test_workspace_layout,
test_workspace_certification}.py`; W `scripts/verify_workspace_wheel.py`;
K `tests/{test_wheel_isolation,test_wheel_isolation_documents}.py`;
A `tests/{test_docker_mcp,test_skill}.py`. Package manifests, lockfile, CI job
selection and globally installed skills remain unchanged.

- [ ] Correct explicit allowed SDK ranges/extras and valid bounded-version
  grammar against the approved producer/capability graph. Keep forbidden Core/
  model/adapter leakage, source/archive/install identity and template checks.
  Do not derive expected dependencies from the installed result under test.
- [ ] Compare the actual console version with installed distribution metadata;
  require the documents capability's affirmative status, not `installed` inside
  `not installed`. Retain genuine conversion/import checks.
- [ ] Resolve opt-in Compose files from `products/ariadne/deploy`; retain its
  auth/mount/recreation assertions. Correct only the packaged-skill test's
  native path expectation, not the installed skill or human/source rules.

**Check selection:** root metadata functions; K
`test_wheel_isolation.py::test_console_script_reports_version` and
`test_wheel_isolation_documents.py::test_doctor_reports_documents_extra_installed`;
A `test_skill.py::test_skill_teaches_context_knowledge_and_typed_page_edits`.
Run changed installed-verifier assertions against matching retained wheels if
all packaging inputs match; otherwise use V's required build, not an extra
per-task build. Compose path/existence/configuration is the immediate mechanical
check; the real opt-in journey runs only with its approved image/authority.
Without that, report launcher repair separately from unverified deployment.
**Invalidation:** manifest, artifact bytes, metadata/CLI status or launcher path.
**Done:** judges no longer reject correct approved artifacts or accept the
specific wrong status, without waiving existing distribution boundaries.

## L — Conditional Activity Log producer/API retirement

**Not activated by approval of the test-only cleanup.** Requires an explicit
owner grant for the residual public API/writer and corresponding gate changes,
or an authoritative decision superseding ADR-0022. Other test work need not wait.
**Sources:** TC8; audit §3; accepted ADR-0022. **Risk:** public SDK removal;
`existing-check`, with scoped interface review before final consumption.

**Bounded owned surfaces if activated:** K `src/lumio_wiki/{knowledge_base,__init__}.py`;
T `test_kb_control.py`; `products/lumio/scripts/verify_lumio_wiki_wheel.py`.
Current source search found the writer/export, four append tests, combined
portability fixture, verifier block and a stale internal docstring; no additional
current production caller. Recheck complete callers, strings/docs and wheel
exports on the released base. Unexpected required consumers stop this lane;
no compatibility alias or deprecation behavior is invented by this plan.

- [ ] Remove the retired producer/formatter/export together with the four
  generation tests and verifier generation block. Preserve all other wheel
  identity, optional-independence and admission checks.
- [ ] Supply authored historical marked bytes if portability needs them.
  Preserve marked-log loading/fingerprint exclusion, wrong/unmarked collisions
  and the existing no-generation tests. Update the obsolete docstring only;
  do not rewrite historical ADRs/audit/frozen issue snapshots.

**Check selection:** T `test_kb_control.py::{test_marked_activity_log_is_excluded_from_pages_and_fingerprint,
test_unmarked_log_md_is_blocking_collision,test_wrong_artifact_on_reserved_basename_is_diagnosed,
test_activity_log_not_created_when_regeneration_runs,test_activity_log_not_created_when_artifact_publish_runs,
test_publish_then_validate_categorized_kb_is_portable}` (expand braces to separate
pytest nodes). Rebuild affected SDK artifacts and run the changed existing
isolated verifier under V once; confirm the public writer is absent in that
installed artifact. **Invalidation:** export, reserved recognition, canonical
fingerprint or wheel input. **Done:** accepted retirement and historical
readability agree across source/tests/wheel; otherwise explicitly defer L.

## V — One assembled verification and handback

**Sources:** TC1–TC9. **Prerequisites:** accepted assigned T1–T4 deltas and any
explicitly activated L; known base/build identity. `existing-check`; no new
verification framework, browser/provider journey or deployment campaign.
**Owned surfaces:** existing checks/CI evidence and this plan's final status;
no product source edits or new sign-off document.

- [ ] Check the actual diff: only approved remaining files; exact retained
  assertions/oracles and no weakened numerical, permission, persistence,
  identity or historical guarantees. No test count or green percentage is
  acceptance evidence. Account for every audit item as handled, upstream-
  resolved, disproved or explicitly deferred within the existing run context.
- [ ] Run applicable required CI **once on the assembled delivery candidate**,
  or reuse C7 evidence for the exact still-applicable code/tests/fixtures/build.
  CI owns its root/member lint/tests, fixed four-worker product selection,
  S3-compatible and isolated-wheel/Pi jobs. Do not duplicate their matrix here,
  remove jobs, or re-run unchanged journeys merely for a handoff label.
- [ ] Reuse matching built artifacts only where packaging inputs are unchanged.
  A changed verifier needs its actual new assertions run; L changes SDK source,
  so its affected wheel must be rebuilt/qualified. Preserve all existing base/
  extra install boundaries. Skips/missing optional environments are named
  unverified limits, not evidence of their successful behavior.
- [ ] One fresh, bounded cleanup-diff review covers what green checks cannot:
  losing a unique guard, wrong/self-confirming oracle, unsupported test
  retirement or erased format/transport distinction. This is not a C6 D1–D4
  re-review. Parent dispositions findings; one authorized fix and one delta
  recheck, then human handback, not a third round.
- [ ] Hand back exact result, changed tests/removed duplicates, evidence reused/
  run, actual skips and open decisions. If L is not activated, label Activity
  Log retirement deferred and do not claim all audit recommendations resolved.
  No merge, issue closure, push, publication or release follows automatically.

**Done:** the approved test-cleanup scope has claim-matched evidence and no
unowned required residual; conditional work remains honestly labeled. A blocked
product correction, canonical C6 obligation or required gate cannot be waived
by fewer tests or a new plan label.

## Approval and present evidence limits

Present **plan0036 revision 1** for approval. Execution remains a separate grant;
L additionally needs explicit public-API scope. No GitHub publication now, and
existing #114/#115/#107 bodies/edges are unchanged. Other work such as GraphRAG
#116–#120 is outside this cleanup; do not alter its host/token gates or CI pin.

Only documentation/source correspondence was inspected while planning. No new
child agents, product edits, test runs/collection, builds, dependency installs,
services, commits or pushes. Audit observations are not current runtime proof;
T0 must refresh them against the released base. Security: no product boundary
changed by planning; existing privacy/authorization regressions remain binding.
