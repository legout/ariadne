# Implementation plan 0029: Lumio-bound governed releases

| | |
| :--- | :--- |
| **Status** | **Revision 3 — owner-approved D1–D5 continuation of L1.** The terminal earlier candidate remains unaccepted. A fresh isolated correction uses the candidate-bound Control File catalog in Lumio spec0009 r2, two finite pytest invocations and one independent review; A1/Q1 remain proposed. |
| **Original execution approval** | Owner, Lumio Pi conversation 2026-10-18: “Implementiere #2 autonom mit paseo subagents”, then “Freigeben und #2 starten (Recommended)”. Authorized the original local source freeze and L1 execution; its later failures, owner exceptions and terminal review are retained, not reset. |
| **D1–D5 continuation approval** | Owner, Lumio Pi conversation 2026-10-19: “weiter gehts”, then “Control File + Sol (Recommended)”. Approves the optional versioned `ariadne_context.ontology_catalog` block in canonical `lumio.yaml`, local Spec0009/ADR0030/shared-plan precision, fresh isolated Pi Sol/high implementation of D1–D5, one focused expected-red regression invocation, one full profile-module post-correction invocation and one independent review. No automatic retries, Ariadne implementation, main integration, push, issue update, release or cleanup. |
| **Goal** | Deliver the approved native Lumio profile/SDK and one SDK-bound Ariadne admission/query journey over one Content Commit. |
| **Approved sources** | [Ariadne spec 0029 r1](../specs/2026-10-18-0029-lumio-bound-governed-releases.md), [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md); `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md` r2 and amended ADR-0030 (r1 sources and approval remain historical). Owner selected “Schriftliche Fassung freigeben (Recommended)” on 2026-10-18 for both written specifications, ADRs, glossaries and scoped amendments. |
| **Source locations** | Original Ariadne and Lumio design worktrees remain reserved and untouched. Approved document copies are committed in isolated local source branches; the parent records the exact two source commits before dispatch. No source-document push or target integration is authorized. |
| **Inspected/reconciled code** | Ariadne native source remains `24630dbd404870f30602d66b5d5a2d53fa892f86`. Lumio inspected `31b6a3e1ef8d04a968b8605128efbdb519396aa7` is reconciled to execution base `c59a1df4ebc1e619543d04c3c70931145cb5a918`: SDK version/skill metadata plus release/packaging changes only; native behavior is unchanged. Published 0.2.0 does not contain this profile. The D1–D5 correction starts from frozen **unaccepted** producer `61c5cc93460948acf4278003061e6b8dbef1e485`; source-only commits precede the fresh writer. |
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

Before execution, resolve the actual host and isolated registered worktrees
using the installed skill. Use Pi only, one writer per worktree, isolated
candidate handoffs and immutable result refs. The current L1 mode is autonomous;
it still stops at a reviewed candidate, before target integration. Do not silently inherit an old
Paseo placement, model override or environment. Project role defaults are Pi
`zai/glm-5.3/high` implementers and `openai-codex/gpt-6.1-sol/high` independent
reviewers, subject to explicit current host/model approval and verified availability.
For this owner-approved D1–D5 correction, the explicit implementer override is
Pi `openai-codex/gpt-6.1-sol/high`, with a fresh independent reviewer using that
same pair. This does not alter global/project defaults or reuse the prior
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
| L1 | [Lumio #2 — native profile and immutable SDK view](https://github.com/legout/lumio-wiki/issues/2) | Approved/frozen r2 producer sources and r3 continuation, qualified fresh host/environment; prior candidate unaccepted | B1-R once, B1-P once; one independent D1–D5 producer review before consumption |
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
historical. L1 has actually consumed four invocations: three full profile-module
runs remained red, followed by one owner-authorized S3-node pass; three
unchanged passing tests were reused rather than relabeled as a new full green.
Its initial and one delta review ended in terminal handback with D1–D5. The
parent retains their exact raw logs, refs and findings; that boundary is closed.

The owner now grants the **new bounded b1 correction** exactly two additional
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

Non-pytest checks are the scoped static checks, required existing Lumio
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

Revision 3 records the owner's explicit D1–D5 continuation and candidate-bound
Control File choice after terminal handback. `61c5cc9` remains unaccepted and
must not be consumed by A1. Freeze new local source commits (Lumio spec0009r2,
ADR0030/glossary and this shared plan) before fresh Sol writer dispatch; record
the capture checkpoint, exact refs, host/model/worktree/runtime and B1-R/B1-P
scope in existing parent run state. No new process ledger or duplicate Lumio
plan. A1/Q1 remain proposed; target integration, issue updates, release, private
app/real-KB access and cleanup remain unauthorized.

Known later boundary: a published supporting SDK version and truthful consumer
release constraints are required for distribution; source-pinned qualification
is not that publication. The concurrent public Lumio 0.2.0 release is not
assumed to contain this new profile. Private app, numeric replay, production
migration, release/push/cleanup and a new Context Provider service remain out.
