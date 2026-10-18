# Implementation plan 0029: Lumio-bound governed releases

| | |
| :--- | :--- |
| **Status** | **Revision 2 — scoped L1 approval record.** The existing revision-1 L1 task is approved for isolated autonomous execution; A1/Q1 remain proposed. Only approval metadata and the release-base reconciliation changed, not task bodies or behavior. |
| **Execution approval** | Owner, Lumio Pi conversation 2026-10-18: “Implementiere #2 autonom mit paseo subagents”, then “Freigeben und #2 starten (Recommended)”. Authorizes local isolated commits of both approved document sets, then only Lumio #2/L1 through Paseo/Pi with V1 and independent review. No Ariadne implementation, target integration, push, issue updates, release or cleanup. |
| **Goal** | Deliver the approved native Lumio profile/SDK and one SDK-bound Ariadne admission/query journey over one Content Commit. |
| **Approved sources** | [Ariadne spec 0029 r1](../specs/2026-10-18-0029-lumio-bound-governed-releases.md), [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md); `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md` r1 and ADR-0030. Owner selected “Schriftliche Fassung freigeben (Recommended)” on 2026-10-18 for both written specifications, ADRs, glossaries and scoped amendments. |
| **Source locations** | Original Ariadne and Lumio design worktrees remain reserved and untouched. Approved document copies are committed in isolated local source branches; the parent records the exact two source commits before dispatch. No source-document push or target integration is authorized. |
| **Inspected/reconciled code** | Ariadne native source remains `24630dbd404870f30602d66b5d5a2d53fa892f86`. Lumio inspected `31b6a3e1ef8d04a968b8605128efbdb519396aa7` is reconciled to execution base `c59a1df4ebc1e619543d04c3c70931145cb5a918`: SDK version/skill metadata plus release/packaging changes only; native behavior is unchanged. Published 0.2.0 does not contain this profile. |
| **Tracker** | Ariadne [#76](https://github.com/legout/ariadne/issues/76), Lumio [#2](https://github.com/legout/lumio-wiki/issues/2). Owner requested corresponding tickets on 2026-10-18: Lumio #2 owns L1, Ariadne #79 owns A1 and #80 owns Q1. This thin joint overview owns readiness/order/coverage/shared budget; tickets alone own the task bodies. Do not maintain a duplicate editable Lumio plan. |
| **Contract** | planning-contract v1; installed catalog revision unknown. `orchestrate-implementation` owns execution; `merge-worktree` owns integration. |

## 1. Readiness, authority and sequence

The capture checkpoint is complete in the two approved source specifications:
resolved vocabulary is in the owning glossaries; ADR-0026/0030 record the real
trade-offs; behavior/ACs have one owner each. No material design decision is
open. The existing L1 slice now has scoped owner approval; exact committed
document sources still precede its writer dispatch. A1/Q1 remain unapproved.
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
A missing capability stops preflight, not a runtime fallback.

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
| L1 | [Lumio #2 — native profile and immutable SDK view](https://github.com/legout/lumio-wiki/issues/2) | Approved/frozen sources, approved plan/execution and qualified host/environment | V1; immediate producer contract review before consumption |
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

The current L1 grant reserves **V1 once** from the existing proposed joint
budget of **five top-level invocations total**, V1–V5 defined in the canonical
tickets. V2–V5 remain reserved for the still-unapproved A1/Q1 tasks. V4/V5 are named mandatory Lumio
gates, not optional broader checks added after a failure. No retry invocation is pre-authorized. A failure
stops the affected lane: diagnose the named failure and ask the owner before
repair/test budget changes. Preserve red output; never weaken an expectation,
add a skip/xfail or borrow another lane's invocation.

Non-pytest checks are the scoped static checks, required existing Lumio
build/verifier/MCP job and one paired installed-origin/profile-read proof
using those artifacts plus the Core wheel. No additional verifier swarm,
certification ledger or ceremonial parent rerun. Preserve still-applicable
passing evidence across handoffs/commits; relevant code/tests/inputs/environment
changes, not labels, decide invalidation.

Review boundaries: immediate L1 before ABI consumption, immediate A1 before
adapter/packaging reliance, then final Q1/integration-only review. Findings
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

Revision 2 records the owner's subsequent approval of the unchanged L1 slice
and local isolated source-document commits only. No task is marked implemented.
A1/Q1 remain proposed; their execution, services, tests and dependency work have
not been authorized. Resolve and record both exact source commits plus the L1
host/model/worktree/runtime identity before dispatch under
`orchestrate-implementation`; do not replace this map with another workflow.

Known later boundary: a published supporting SDK version and truthful consumer
release constraints are required for distribution; source-pinned qualification
is not that publication. The concurrent public Lumio 0.2.0 release is not
assumed to contain this new profile. Private app, numeric replay, production
migration, release/push/cleanup and a new Context Provider service remain out.
