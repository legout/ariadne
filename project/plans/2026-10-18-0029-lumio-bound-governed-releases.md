# Implementation plan 0029: Lumio-bound governed releases

| | |
| :--- | :--- |
| **Status** | **Revision 5 — owner-approved test-oracle exception c2.** C1's two calls are spent: the named guard red was reproduced; its post-check has one final-LF expectation failure and two passing D4 guards. Product delta remains uncommitted/unaccepted. C2 permits only document-boundary LF normalization in the regression and one invocation of that failed node; the previously reserved single delta review remains pending. A1/Q1 remain proposed. |
| **Original execution approval** | Owner, Lumio Pi conversation 2026-10-18: “Implementiere #2 autonom mit paseo subagents”, then “Freigeben und #2 starten (Recommended)”. Authorized the original local source freeze and L1 execution; its later failures, owner exceptions and terminal review are retained, not reset. |
| **D1–D5 continuation approval** | Owner, Lumio Pi conversation 2026-10-19: “weiter gehts”, then “Control File + Sol (Recommended)”. Approves the optional versioned `ariadne_context.ontology_catalog` block in canonical `lumio.yaml`, local Spec0009/ADR0030/shared-plan precision, fresh isolated Pi Sol/high implementation of D1–D5, one focused expected-red regression invocation, one full profile-module post-correction invocation and one independent review. No automatic retries, Ariadne implementation, main integration, push, issue update, release or cleanup. |
| **D4-only correction approval** | Owner, Lumio Pi conversation 2026-10-19: selected “Nur D4 beheben (Recommended)” after the b1 fix-first handback. Authorizes isolated Sol/high correction of the existing destination-kernel mismatch, one independently expected regression, exactly two focused pytest invocations (red, then D4 post-check) and one independent delta review. This explicitly extends execution for D4 only; it neither resets b1 nor authorizes other features, integration or publication. |
| **Test-oracle exception approval** | Owner, Lumio Pi conversation 2026-10-19: selected “Testorakel korrigieren (Recommended)”. Exclude only leading/trailing LF framing in the decoded-body comparison; preserve strict full text, internal newlines, metadata, path and Source-binding assertions. No further product fix. Exactly one additional invocation of the failed regression, reuse the two relevant passing D4 cases, then the already reserved delta review. This is an explicit oracle/budget exception, not a retry loop or new review allocation. |
| **Goal** | Deliver the approved native Lumio profile/SDK and one SDK-bound Ariadne admission/query journey over one Content Commit. |
| **Approved sources** | [Ariadne spec 0029 r1](../specs/2026-10-18-0029-lumio-bound-governed-releases.md), [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md); `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md` r2 and amended ADR-0030 (r1 sources and approval remain historical). Owner selected “Schriftliche Fassung freigeben (Recommended)” on 2026-10-18 for both written specifications, ADRs, glossaries and scoped amendments. |
| **Source locations** | Original Ariadne and Lumio design worktrees remain reserved and untouched. Approved document copies are committed in isolated local source branches; the parent records the exact two source commits before dispatch. No source-document push or target integration is authorized. |
| **Inspected/reconciled code** | Ariadne native source remains `24630dbd404870f30602d66b5d5a2d53fa892f86`. Lumio inspected `31b6a3e1ef8d04a968b8605128efbdb519396aa7` is reconciled to execution base `c59a1df4ebc1e619543d04c3c70931145cb5a918`: SDK version/skill metadata plus release/packaging changes only; native behavior is unchanged. Published 0.2.0 does not contain this profile. B1 started from frozen **unaccepted** producer `61c5cc93460948acf4278003061e6b8dbef1e485`. C1 starts from frozen **unaccepted** b1 `721caf2465a0641be2c75c861dc55b217743151b`; the r4 execution source is frozen before its fresh writer. |
| **Tracker** | Ariadne [#76](https://github.com/legout/ariadne/issues/76), Lumio [#2](https://github.com/legout/lumio-wiki/issues/2). Owner requested corresponding tickets on 2026-10-18: Lumio #2 owns L1, Ariadne #79 owns A1 and #80 owns Q1. This thin joint overview owns readiness/order/coverage/shared budget; tickets alone own the task bodies. Do not maintain a duplicate editable Lumio plan. |
| **Contract** | planning-contract v1; installed catalog revision unknown. `orchestrate-implementation` owns execution; `merge-worktree` owns integration. |

## 1. Readiness, authority and sequence

The capture checkpoint is complete in the two approved source specifications:
resolved vocabulary is in the owning glossaries; ADR-0026/0030 record the real
trade-offs; behavior/ACs have one owner each. The subsequent D1–D5 handback
identified missing catalog plumbing; the owner has now selected the optional
versioned Control File block captured in Lumio spec0009 r2/ADR0030. No mutable
caller-provided catalog authority is selected. Freeze those locally reconciled
source commits before the fresh L1 correction writer. A1/Q1 remain unapproved.
Neither this scoped approval nor an implementation handoff grants target
integration, push/PR, issue updates, package release, private-app adoption,
production access, shared-KB mutation or cleanup.

B1's two checks and one fresh review are now exhausted. Its review and parent
source trace identify one surviving D4 failure: same-title managed Policy
ingest proposes an underscore slug while native apply retains the recorded
hyphen path; the new profile view validates the proposal path instead of the
actual destination. The owner separately approved c1 to reuse the existing
resolved-destination/effective-content kernel and preserve the pre-registration
profile gate. No new vocabulary, architecture or behavior is selected: Lumio
spec0009 r2 §3 and the native recorded-path revision rule already own this
contract. Only this execution map/budget needs reconciliation. Freeze r4 in a
new source copy; original and b1 sources/checkouts/refs remain reserved.

Before execution, resolve the actual host and isolated registered worktrees
using the installed skill. Use Pi only, one writer per worktree, isolated
candidate handoffs and immutable result refs. The current L1 mode is autonomous;
it still stops at a reviewed candidate, before target integration. Do not silently inherit an old
Paseo placement, model override or environment. Project role defaults are Pi
`zai/glm-5.3/high` implementers and `openai-codex/gpt-6.1-sol/high` independent
reviewers, subject to explicit current host/model approval and verified availability.
For b1 and this owner-approved D4-only c1 correction, the explicit implementer
override is Pi `openai-codex/gpt-6.1-sol/high`, with an independent reviewer using
that same pair. C1 uses a fresh writer from frozen721 and a delta-only review. This does not alter global/project defaults or reuse the prior
reviewer as a writer. A missing capability stops preflight, not a runtime fallback.

Use Python 3.14.0 in fresh run-owned environments, not a PATH interpreter or a
deleted prior-task env. Install only approved declared dependencies and the
exact accepted producer source/build. No shared runtime changes, implicit
online fallback, global skill installation or tau/private-app dependency work.

Sequence: **L1 producer contract -> accepted producer -> A1 bound local query/
admission -> accepted consumer -> Q1 adapters/packaging and required gates ->
assembled candidate review -> supervised pause.** These are coupled slices,
not independent parallel writers. L1 defines the consumed ABI before A1 starts.

No newly supported public SDK version is assumed available on PyPI. Isolated
qualification can install the exact accepted source/wheel pairing. Do not
invent a supporting dependency floor, bump versions, add a convenience extra,
or publish packages merely to make that pairing resolvable. Correct published
version constraints are a later coordinated-release decision, not a claim of
this isolated implementation handoff.

## 2. Requirement-to-task map

| Approved criterion | Primary task/evidence |
| :--- | :--- |
| Ariadne AC1, Lumio AC1–AC3 | L1 native profile preservation and exact knowledge identity; A1 one shared Content Commit |
| Ariadne AC2, Lumio AC1/AC2 | L1 supported-field round-trip/refusal, not generic OKF conversion |
| Ariadne AC3/AC5, Lumio AC5/AC6 | A1 independently expected revenue 150, required citations and old-session isolation |
| Ariadne AC4/AC7, Lumio AC4 | L1 namespace/scope/Policy Closure; A1 pre-SQL and permission gates |
| Ariadne AC6, Lumio AC6 | A1 native publication/final-activation fault path; Q1 mandatory native S3 gate |
| Ariadne AC7/AC8, Lumio AC7 | Q1 installed identities, source-free adapter behavior and standalone compatibility; existing gates |

## 3. Canonical task tickets

Task bodies have moved unchanged from the full proposed plan into these
canonical GitHub issues at the owner's 2026-10-18 request. This overview retains
readiness, ordering, requirement coverage and the shared budget only; edit
task decomposition in the tickets, not in a duplicate local/Lumio plan.

| Order | Canonical ticket | Prerequisite | Assigned checks |
| :--- | :--- | :--- | :--- |
| L1 | [Lumio #2 — native profile and immutable SDK view](https://github.com/legout/lumio-wiki/issues/2) | Frozen r2 producer behavior, r5 oracle exception, preserved tested c1 product delta and verified same isolated host/environment; b1 candidate721 unaccepted | B1 and C1 calls spent; C2 failing node once, reuse C1's two unchanged guard passes; the one reserved721-to-fix D4 delta review before consumption |
| A1 | [Ariadne #79 — joint admission and bound revenue](https://github.com/legout/ariadne/issues/79) | Accepted L1 ABI/fixture/ref plus global readiness | V2; immediate consumer review |
| Q1 | [Ariadne #80 — public surfaces and qualification](https://github.com/legout/ariadne/issues/80) | Accepted L1 and A1 | V3–V5, named native build/verifier checks and paired installed proof; final delta/integration review |

All three are native sub-issues of [Ariadne #76](https://github.com/legout/ariadne/issues/76).
Native dependency order is L1 -> A1 -> Q1; L1 also directly blocks Q1.
Lumio #2 is reused with its original architectural intake preserved; no duplicate
producer ticket is created. The current owner request approves its existing L1
slice, subject to frozen sources and host/runtime readiness. The dated planning
state in the remote ticket records the earlier capture; no issue update is
included in this local execution grant. A1/Q1 remain planned and unapproved.

## 4. Finite assurance budget and review rules

The original proposed joint V1–V5 budget and all later owner exceptions remain
historical. The original L1 boundary consumed four invocations: three full profile-module
runs remained red, followed by one owner-authorized S3-node pass; three
unchanged passing tests were reused rather than relabeled as a new full green.
Its initial and one delta review ended in terminal handback with D1–D5. The
parent retains their exact raw logs, refs and findings; that boundary is closed.

For the **bounded b1 correction**, the owner granted exactly two additional
serial pytest invocations, not a reset or borrowed A1/Q1 reservation:

- **B1-R, once before production edits:** the new focused D1–D5 regression
  group in `packages/lumio-wiki/tests/test_ariadne_context.py`, with exact node
  names supplied by the parent brief. Independently expected assertion failures
  on the named surviving defects are the intentional bug-repro result; an
  import/setup failure or wrong oracle is not. No separate baseline/probe run.
- **B1-P, once after the coherent correction:**
  `$LUMIO_PY -m pytest -q packages/lumio-wiki/tests/test_ariadne_context.py`.
  This delta changes shared profile/control/native gates, so the whole focused
  profile module is relevant; it is not a ceremonial rerun of old greens.

No retry is pre-authorized. An unexpected failure stops the lane at its named
cause for owner disposition. Preserve true red output; never weaken assertions,
add skips/xfails, run hidden SDK/import probes, broaden suites or repeat until
green. Scoped static syntax/Ruff/diff checks remain allowed. No installed/live
qualification is added to b1. V2–V5 remain reserved for unapproved A1/Q1;
mandatory Q1 native CI/build/verifier checks are not waived.

B1 actually used B1-R (eight expected defect failures, exit1) and B1-P
(12 passed, exit0), followed by its one fresh independent fix-first review.
The parent source-traced the same-title Policy destination mismatch; D1/D2/D3/D5
named gaps were resolved, but D4 and the overall producer remain unaccepted.
Those six historical pytest invocations and all original review boundaries
remain recorded unchanged. Source-traced D4 is not claimed runtime-reproduced.

For **c1, D4 only**, the owner granted exactly two additional serial invocations:

- **C1-R, once before production edits:**
  `$LUMIO_PY -m pytest -q packages/lumio-wiki/tests/test_ariadne_context.py::test_managed_policy_revision_retains_recorded_path`.
  One new public managed-ingest regression revises the existing canonical
  Policy with valid routing/provenance/profile and no move. Independently
  expect its original recorded path, unchanged metric correspondence and no
  underscore-path duplicate. Before correction the actual guard refusal is
  the expected red; import/setup/oracle failure stops the lane.
- **C1-P, once after the coherent correction:** the same new node plus
  `test_effective_ingest_and_compound_gate_before_writes` in that module
  (its two existing parameter cases). This focused group exercises destination
  parity while preserving the existing missing-Policy/pre-write/compound
  guards. Do not rerun unrelated greens or the whole suite for a new label.

One independent delta-only review covers `721caf2..c1-result` and the original
D4 finding, not settled D1/D2/D3/D5 or the whole L1 implementation. It grants
no repairs or further reviews; a surviving blocker returns to the owner.
No intermediate probes, extra pytest calls, retries, weakened assertions,
new dependencies, live/installed gates or borrowed A1/Q1 budget. Scoped static
syntax/Ruff/diff checks remain allowed. Exact runtime/environment isolation
and commit/freeze/relinquish handoff rules are unchanged. Reuse unaffected
b1 evidence only with its actual surface and delta qualification.

C1 actually used C1-R (one expected Policy path-guard failure, exit1), then
C1-P (one failed final-LF suffix assertion, two passing existing D4 guard
cases, exit1). The public managed revision now returns and its exact metadata
assertion passes, but later duplicate-path, unchanged-metric, Source-digest and
loader assertions were not reached. No success commit/ref or review occurred.
Keep both true failed logs; eight historical invocations remain eight.

Parent source trace identifies the latter assertion as over-strict for this
D4 obligation: unchanged native `ingest._split_distilled_pages` already trims
LF characters at document boundaries before routing. This is not caused by
the destination fix. The parent had approved that unnecessary expectation
and obtained the explicit c2 decision instead of altering it or retrying.
Spec0009 r2's semantic body/metadata preservation and exact **committed**
publication bytes remain unchanged; c2 selects no product behavior change.

**C2, exactly one additional invocation:** only
`test_managed_policy_revision_retains_recorded_path` in the same module.
Compare the entire decoded written body with the submitted fixture-derived
revised body, excluding only leading/trailing LF framing on both sides.
Internal newlines, spaces/tabs, all body text, exact decoded metadata, recorded
path/no duplicate, metric bytes and Source-binding digest checks stay strict.
No generic whitespace stripping, copied output oracle, other test edits or
product repair is permitted. Use the same isolated3.14 environment and tested
c1 semantic product delta. The two existing guard passes survive this test-only
change; do not repeat them, the group or the whole module. Unexpected failure
again stops for owner disposition; no extra repair or test is authorized.

The one previously reserved delta-only review remains unused (0/1); c2 adds
no review allocation. After actual success, commit/freeze the existing D4
product delta plus this test-only correction in a unique result ref, retaining
all failed patches/logs and qualified neutral formatting drift. Review only
721-to-fixed-result and the original D4 finding plus the authorized oracle
change. No settled D1/D2/D3/D5 or general L1 re-review; no integration authority.

Later joint/Q1 non-pytest checks are the scoped static checks, required existing Lumio
build/verifier/MCP job and one paired installed-origin/profile-read proof
using those artifacts plus the Core wheel. No additional verifier swarm,
certification ledger or ceremonial parent rerun. Preserve still-applicable
passing evidence across handoffs/commits; relevant code/tests/inputs/environment
changes, not labels, decide invalidation.

The b1 scope covers only the five surviving producer gaps from the terminal
review of `99598d5..61c5cc9`: native schema fidelity, Policy correspondence,
candidate-bound catalog plumbing, effective pre-write gates and exact
Source/subtree admission binding. The specification owns their behavior; the
existing L1 ticket still owns task decomposition. No duplicate ticket/plan is
created or issue mutation authorized. The new Declared Ontology Catalog term
is captured in Lumio's owning glossary; no Ariadne vocabulary/code change is
required for this producer clarification.

Exactly one fresh independent b1 review covers the new direct correction
and those affected contracts. It is a new explicit owner-approved scope, not
an automatic third review of the closed prior boundary. Any surviving blocker
returns to the human; no automatic extra fix/review or test-budget reset.

Other review boundaries remain: immediate L1 before ABI consumption, immediate
A1 before adapter/packaging reliance, then final Q1/integration-only review. Findings
must meet the canonical guardrails and name a reachable material violation.
The parent dispositions them; at most one authorized fix pass and one delta
recheck per boundary, with remaining blockers handed to the owner. No reviewer
repairs or autonomous third round. Use the installed full reviewer contract
and real criteria in each fresh prompt.

Security scope is concrete: externally supplied KB/profile content crosses
into governed answer context, Visibility Scope protects hidden Policies, and
publication/overall-confirmation inputs control active state. Review those
real paths, source/credential boundaries and the optional dependency change;
not stolen-secret/broken-TLS/malicious-admin stories or generic hardening.

## 5. Handoff state

Revision 5 records the explicit c2 oracle exception after c1's failed
post-check. Frozen61/721 remain unaccepted; neither is an A1-consumable ABI.
Keep the approved r2 behavior/ADR/glossary and tested c1 semantic product
patch unchanged. Freeze this new execution-source copy while preserving r4,
all old worktrees/refs/reports and failed tests. Verify the same idle Sol
worker's placement/runtime and the current patch against tested content before
grants; c2 may edit only the decoded-body LF comparison and execute its one
node. Record actual result/ref/cleanliness, failures/reused passes, unknown
formatting actor and the still-single delta review in existing parent state.
No duplicate plan, new process ledger or issue update. A1/Q1 remain proposed;
target integration, push/release, private app/real-KB access and cleanup remain
unauthorized.

Known later boundary: a published supporting SDK version and truthful consumer
release constraints are required for distribution; source-pinned qualification
is not that publication. The concurrent public Lumio 0.2.0 release is not
assumed to contain this new profile. Private app, numeric replay, production
migration, release/push/cleanup and a new Context Provider service remain out.
