# Implementation plan 0029: Lumio-bound governed releases

| | |
| :--- | :--- |
| **Status** | **Approved revision 10 — tags-only fixture exception.** Owner 2026-10-19 selected “Nur Tags korrigieren +1 Lauf”: add required top-level cancellation-page tags only, then exactly one P2 invocation of the eight failed MVP nodes; reuse the three unaffected successes. No product/SDK/assertion changes or further retry. The one candidate review remains unused and follows only a passing candidate. |
| **Historical planning authority** | Owner, Ariadne Pi conversation 2026-10-19: after selecting local Metric MVP/strict profile boundary and approving its complete design, selected “Schriftlich freigeben (Recommended)” for written spec r2, ADR/source notices and subsequent local implementation planning only. No implementation, runtime tests, GitHub changes, integration or publication. |
| **Goal / source** | First deliver the strict local journey defined by [spec0029 approved r2](../specs/2026-10-18-0029-lumio-bound-governed-releases.md), §§1.1–7 and [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md). Preserve the full #76/#79 target; deferred features remain open. |
| **Current source identity** | Approved spec SHA256 `22359ad5ab6f01d99b46cb8f8d7a8c6d1df6875d4dc21bb94481b03997a86adf`; document fork descends from source `5502300aca23d1afd3f49fb4f73d5fd9374a9b5a`. Native Core bytes equal `24630dbd404870f30602d66b5d5a2d53fa892f86`. Parent records the actual locally frozen source commit/ref before dispatch; no public source URL is claimed. |
| **Producer** | Accepted Lumio `7cdd6e89030f4f1add06d077143e9953b6258894`, tree `47ce31e965f9887a57553a1ff777567625f010e9`, implementing companion spec0009 approved r2/ADR0030. Exact ABI/fixture identities are in the proposed task. No producer changes or new L1 review. |
| **Tracker** | [#76](https://github.com/legout/ariadne/issues/76) owns the full target; [#79](https://github.com/legout/ariadne/issues/79) stays the larger A1 parent and [#80](https://github.com/legout/ariadne/issues/80) later full qualification. Canonical [M1/#81](https://github.com/legout/ariadne/issues/81) is a new native child of #79, with the native [Lumio #2](https://github.com/legout/lumio-wiki/issues/2) dependency. Existing full-target task bodies were not narrowed or closed. |
| **Capture / contract** | Existing glossary terms suffice. ADR-0026 records the delivery refinement without a new architecture/producer contract. Spec r2 owns scope/behavior/acceptance. No unresolved material design choice is delegated to a writer. Planning-contract v1; installed catalog provenance unknown. |

## 1. One coherent vertical slice

**L1 accepted -> M1 local Metric MVP -> isolated reviewed candidate -> pause.**
M1 crosses the joint authored revision, validation, operator preview/admission,
immutable SDK read and native metric answer. Do not split this into half-working
storage/API/context tasks, independent writers or extra review boundaries.
Later S3, additional annotations and integrated Context/multi-metric operations
are not M1; a local pass does not satisfy or close the complete A1/Q1 target.

The single canonical task is [M1/#81 — local Metric MVP](https://github.com/legout/ariadne/issues/81),
a native child of #79 with the native Lumio #2 dependency recorded. The accepted
producer implementation/CI satisfies M1's code prerequisite; Lumio #2 remains
open on GitHub and this grant does not close or rewrite it. Its issue status is
not substituted for the exact accepted artifact. The original unpublished
runtime draft is preserved as proposal history, not a second editable task body.

The task owns its exact file list, interfaces, checkbox steps, named tests,
commands and completion boundary. This thin overview owns sequencing, coverage
and the shared budget, not a second editable task definition.

| Canonical task | Depends on | Produces | Validation / review |
| :--- | :--- | :--- | :--- |
| [M1/#81](https://github.com/legout/ariadne/issues/81) — local Metric MVP | Approved r2/r8 and scoped M1 grant; accepted L1; locally frozen source and verified host/env required before writes | One jointly validated synthetic Content Commit, one exact overall local admission, SDK-bound `get_metric`=150 with full required context/caveats, and explicit unsupported-operation boundaries | One high-risk unit; approved M1-R/M1-P, two calls total; one immediate independent M1 candidate review, then supervised pause |

### Approved execution settings; verify before dispatch

- Approved host: **Paseo-hosted Pi**, preserving the shared worktree root
  `/home/volker/.local/state/worktrees` and Ariadne allocator subdirectory
  `079pxy11`. Fresh isolated registered writer; no relocation, daemon config
  change or other-runtime fallback. No child is launched by this plan.
- Approved M1 task-specific model override: fresh implementer
  **Pi `openai-codex/gpt-6.1-sol/high`**, not the old GLM worker or the read-only
  reviewer. One independent fresh **Pi Sol/high** reviewer. The owner selected this override for M1 only,
  not new global defaults. Verify exact native backend model/thinking/cwd at
  dispatch.
- Exact **Python3.14.0** and a fresh run-owned offline environment, Core bound
  to the new writer and SDK bound to accepted7cdd. Do not reuse the old env's
  editable Core binding to failed df72. Isolated PEP660/no-deps build discipline
  remains; no global/online install, new dependency, package bump or pretend
  published SDK floor. Public 0.2.0 alone does not contain this profile.
- Use ordinary native Git knowledge edits/reconcile in the same proposal
  worktree, not a new `kb_page` tool/kind or second proposal store. Reuse existing
  Core source/contract/model/technical-metadata checks and complete-output
  accounting. No curated mirror or speculative abstraction.
- Preserve native public outer result types. `list_metrics` is a list with
  entries/routing text; make metadata additive and avoid its legacy Ad-hoc
  fallback hint in integrated MVP mode. `discover` reports unavailable groups
  without invoking legacy Context; identity failures still refuse globally.
  CLI/deferred catalog routing must not instantiate live execution merely to
  disclose the catalog. These callers are concrete ownership, not Q1 expansion.

## 2. Requirement coverage

| Approved spec r2 criterion | M1 proof / exact owner in draft |
| :--- | :--- |
| AC1 | Actual new ODCS contract/binding + OSI + authored cancellation Policy in one synthetic revision, genuine source approval/native review |
| AC2 | Strict globally checked Metric/Policy boundary; accepted fixture unchanged as input, explicit candidate adaptation; authoritative captured SDK catalog/schema |
| AC3 | Independently specified 150 from 100+50 excluding25; full source text/citations, actual stale/pending caveats, unchanged native result contract |
| AC4 | Required-context/scope gate and complete descriptor/manifest/Core/SDK consistency before SQL; no missing-field/latest/standalone fallback |
| AC5 | Existing complete session survives later Policy/native-current change; mixed valid releases refuse |
| AC6 | Actual post-publication reader/final-activation faults preserve previous integrated binding and disclose receipts; full-binding expected-current compare even at the same commit |
| AC7 | Existing native admission/source nodes plus standalone import boundary; unchanged roles and no request-selected scope/capability |
| AC8 | Actual code/build contents, distinct producer digest semantics and complete composite consent; no invented numeric/installed/live qualification |
| AC9 | Closed serving operation set, additive source-free CLI/deferred catalog and explicit refusal of other serving paths |

The prior review remains useful defect evidence, not the new behavioral source.
M1 must not repeat K1/K2 or R1–R5/R9/R10. R6–R8's full operation implementations
are deferred; their unsafe legacy execution is replaced by explicit refusal.
G1 is not falsely declared fixed: unsupported SDK annotations refuse, while
full technical-reference/evidence support remains later work. Preserve T1/T2's
independently established fixture/native-receipt lessons, not their wrong
expectations. The accepted L1 producer is not re-reviewed.

## 3. Approved finite M1 assurance boundary

### Revision 10 exception: shared cancellation-page tags

Original M1-P exited1 with eight named failures: the shared Cancellation page
omitted required top-level tags, while native tags do not satisfy that field.
Seven journeys stopped before admission; the Reference/technical-extension
node stopped in its second subscenario. Governed150/release behavior remained
unverified. WIP0bfae9a/tree d307c50 and raw/native evidence remain preserved.
The owner chose a tags-only fixture correction plus one P2 call of those eight
failed nodes, not the proposed early review. Reuse the unaffected standalone-
import and two native admission/source successes; do not repeat them. Another
failure stops with no further repairs/reruns. The existing AST-identical test
import formatting is archived and explicitly disclosed, not reset silently.

### Preserved revision 9 exception: false-positive M1-R

M1-R exited 0 while accepting a native fixture citation failure: the model name
was changed to retail_sales but its file remained orders.yml, and the broad
substring matcher mistook `unsupported` in pytest's temporary path plus
`reference escapes` for the desired profile refusal. Parent confirmed the
native evidence/source; test-only WIP1f0bdba is clean and no product code exists.
The owner approved aligning the fixture/model citation and strengthening the
oracle, with **one extra invocation of that same node (M1-R2)**. No native gate
is weakened; diagnostic paths/incidental words cannot establish the expected
cause. Statically inspect the correction before the call. An unrelated failure
or another false green stops; no further repair/rerun is allocated. Only the
intended missing-feature failure unlocks the original product/P continuation.
The actual WIP/log/native-validation records stay preserved in the parent run.


**One high-risk unit:** money, Source Approval, exact human consent, Scope,
complete immutable binding and last activation. It needs one immediate
independent candidate review before later work consumes the result. No
per-method/per-layer matrices, baseline suite or second live proof.

| Approved call | Timing | Command ownership / expected evidence |
| :--- | :--- | :--- |
| M1-R, spent | Before product edits | New strict-profile refusal node only, using existing native Core entrypoints and accepted SDK. A native-valid unsupported Reference profile being ignored is the expected defect; import/setup/contract-fixture errors are not accepted red. Exact command is in the task. |
| M1-R2, once | Test-only fixture/oracle correction before any product edits | Same strict-profile node/command as original M1-R, new noclobber logs. Only the intended unsupported-profile defect may be the red; source/contract/citation/setup failures or green stop. |
| M1-P, spent failed | After intended M1-R2/coherent implementation | Eight named nodes failed on the shared tags fixture before admission; three trailing successful nodes remain reusable. Raw log/exit and native records are preserved. |
| M1-P2, once | After tags-only correction | Exactly the eight failed `tests/test_lumio_metric_mvp.py` node selectors, one invocation; no standalone-import or existing-node repeats. Keep real confirmations/receipts/oracles; command is in amended canonical #81. |

Approved M1 budget is now **four invocations in total**: invalid-green M1-R,
intended-red M1-R2, failed M1-P and the one added tags-only M1-P2. No reset,
other retry/fix reserve or borrowed V2/V3–V5 allocation. The original grant was
“Plan + M1 starten (Recommended)”; the one extra call/test-only correction was
separately approved with “Test-only korrigieren +1 Red (Recommended)”. The P2
tags-only exception was approved with “Nur Tags korrigieren +1 Lauf”. Static changed-path syntax/Ruff/diff/diagnostics and exact
upstream blob comparison are the only additional code checks proposed; a
single isolated import/origin env preflight verifies the actual binding, not
product behavior. No behavior probe, collection run or hidden nested pytest.

New tests use spec/hand-worked/trusted-producer oracles. Fault injection may
raise at the named SDK-reader/descriptor boundary but never manufacture a
receipt, successful Context Snapshot or human approval. Temporary code-file
fixtures may test identity drift; protected real Core/SDK files may not be
mutated. Preserve exact committed text/metadata and native receipt meanings;
no output-derived expectations or blanket whitespace relaxation.

Record the tested relevant code/tree after the last formatter pass. If build
identity needs a pre-test WIP commit, label it honestly and do not create a
passed-result ref before success. No unnoticed code/identity changes between
M1-P, freeze and review; a formatter-only delta still needs applicability
assessment when those bytes are part of the identity contract. Do not reset
foreign dirt or silently rerun to obtain a new label.

Reuse still-applicable accepted L1 evidence (merged d798c136 exact accepted tree,
CI39231454102/39231454187, accepted b1/c2 qualification) and exact baseline
blobs. Do not rerun the producer or describe that evidence as consumer proof.
The two existing native nodes are rerun only because M1 changes their shared
admission/source initialization. No extra actor/transport/installed-wheel run.

The one approved fresh M1 review covers the exact new source-to-result range and
integration effects against local r2, not settled L1 or all future #76 features.
Reviewer runs no tests/repairs; parent alone dispositions findings. No repair
is pre-authorized. An unexpected failure stops with preserved WIP/logs; at most
one subsequently authorized fix and one delta recheck may follow. No third
round, unapproved budget extension or assertion weakening.

The existing [tag publication workflow](../../.github/workflows/publish.yml)
retains its built Core wheel suite and the documented exclusion of the three
capability-locked S3 modules. Those publication gates are neither waived nor
run by M1; publication requires its own authorization. Lumio/Q1/native S3,
paired package and role/transport qualification likewise remain later scoped
work, not a reason to run them now or to claim them from this local proof.

## 4. Historical evidence and protected work

- Original A1 source: `5502300aca23d1afd3f49fb4f73d5fd9374a9b5a`.
  WIP `df72f3fcf59a8b2d0781f4a012802557d704b056`, tree
  `a73835a3945178f87363e346e33dbd1f7f077cc3` is **unaccepted**.
  V2 ran once: **3 passed/6 failed, exit1**. Five new journeys stopped at the
  first KB edit; their deeper assertions were not proved. Its one initial
  review was owner-advanced to red WIP and returned fix-first. No slot survives.
- M1-R invalid-green WIP `1f0bdba1e7aa1447d77c96e0c4961c6f4c2726ec`, tree
  `8d8cbb5d1cabec7e21a2c17fbab4ec6ba763b94f`: only five test/baseline files;
  no product changes or passed-result ref. Raw M1-R exit0 and its real native
  citation failure are not repro/feature proof. M1-P/review remain unused.
- Original r1–r6 grants, failed producer calls, owner b1/c1/c2 exceptions and
  retained evidence remain in immutable source history (including source5502300)
  and the parent-owned run. This new proposal does not reset or rewrite them.
- Main stays `24630dbd...`; nine original Ariadne document deltas remain reserved.
  The original six Lumio document bytes are archived at
  `62bb41c36ce7afdfce9fbfe8f25ac45b7fa62a79`. Keep the accepted SDK reader and old
  source/result refs. Known post-handback AST-neutral worker formatting remains
  preserved, not reset or silently imported into a new candidate.

## 5. Approval and handoff gate

The owner separately approved the combined scoped action with “Plan + M1
starten (Recommended)”: local source freeze, new canonical M1 child and its
parent/dependency metadata, exact proposed Sol/high roles, the finite M1 checks
and implementation. This explicit combined grant, not planning approval alone,
is the authority. Freeze/record the actual source and issue identities, verify
host/model/worktree/environment readiness, then use `orchestrate-implementation`
for M1 only. No old/full target ticket is closed or silently rewritten.

After genuine passing evidence, a committed/frozen result and independent
acceptance, hand back the isolated local MVP candidate and pause. No automatic
Q1, full-parent closure, main integration, push, tag/release, real sources/KB,
new permissions, private-app adoption, service, dependency change or cleanup.
No extra ledgers/sign-off artifacts; existing run state owns runtime facts.
