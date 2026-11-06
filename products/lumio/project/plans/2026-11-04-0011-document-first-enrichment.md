# Plan 0011: Document-first knowledge and reviewed enrichment

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

Canonical task bodies now live in the linked GitHub issues; this file owns the interface/dependency/coverage overview, not duplicate task instructions.

Status: **owner-approved implementation plan, revision 1; ticketized**. Date: 2026-11-04.

## Goal and authority

Make a runbook useful in standalone Lumio before anyone designs a business ontology, then let Pi propose a small, source-supported semantic enrichment for human review. Preserve artifact identity, source history, and admitted-only retrieval.

Behavioral sources: [spec0003 revision 3](../specs/0003-model-assisted-extraction.md), including approved §9 defaults, and [shared spec0034 revision 3](../../../../project/specs/2026-11-04-0034-agent-first-shared-workspaces.md). Architecture: [ADR-0032](../adr/0032-document-first-progressive-enrichment.md); the accepted scoped extension retains ADR-0021's native guarantees. The owner selected neutral artifacts, stable identities/collision refusal, on-request human review, Pi/private networking and Entra-first identity, and requested implementation plans. Complete written defaults and this plan are approved for ticketization; no implementation, processing of private documents, provider call, product publication or Git push is newly authorized.

Capture: existing Entity/Claim/Evidence/Knowledge Source vocabulary suffices. `knowledge-artifact` is a KB-local type identifier, not a new domain lifecycle. Contract version 1; installed skill provenance unknown. Source inspected at `34bfe1be`; no runtime proof is claimed by this plan.

## Boundaries and sequence

[Shared plan0034](../../../../project/plans/2026-11-04-0034-agent-first-shared-workspaces.md) owns W1–W6: authentication, uploads, source retention, browser approval, native publication/recovery, and installed-client qualification. This plan owns only L1–L3. Do not duplicate shared task bodies or create another queue, approval ledger, provider runtime, graph store, or canonical document format.

Order: **L1 → shared W2/W3 → L2 → L3 → shared W5/W6**. L1 can be verified at the SDK boundary without an installed service. It does not claim the full Pi journey is usable before W2/W3. L2/L3 modify shared service/client surfaces and therefore execute serially with those owners.

Path abbreviations:

- **K** = `products/lumio/packages/lumio-wiki/`; Python package `src/lumio_wiki/`.
- **S** = `products/lumio/packages/lumio-workspace/` (created by W1).
- **C** = `products/lumio/clients/pi-workspace/` (created by W1).

Use Python 3.14 and existing native candidate/review/publication APIs. The SDK stays model- and authentication-independent. Local/advanced Git and read-only MCP routes retain existing behavior. No automatic ontology lookup, scheduler, consensus score, semantic-entailment oracle, graph-based join authority, or migration of existing pages.

## L1 — Publish a basic artifact without a business ontology

Canonical task: [#87](https://github.com/legout/ariadne/issues/87). Dependencies: no feature-task prerequisite; follow the approved delivery order.

## L2 — Propose and review one bounded enrichment

Canonical task: [#95](https://github.com/legout/ariadne/issues/95). Dependencies: [L1 / #87](https://github.com/legout/ariadne/issues/87), [W3 / #89](https://github.com/legout/ariadne/issues/89).

## L3 — Refresh source material without rewriting accepted meaning

Canonical task: [#96](https://github.com/legout/ariadne/issues/96). Dependencies: [L2 / #95](https://github.com/legout/ariadne/issues/95), [W4 / #90](https://github.com/legout/ariadne/issues/90).

## Coverage, compatibility and verification handoff

| Spec0003 requirement | Evidence owner |
| --- | --- |
| AC1 basic cited document, AC2 immediate provenance | L1 plus shared W2/W3/W6 |
| AC3 supported relation; AC4 proposal versus policy | L2 deterministic gates plus W6 real-host corpus |
| AC5 contradictory ownership and identity ambiguity | L2 review and W6 corpus |
| AC6 anchor coordinates versus semantic support | Native Claim tests; L2 review presentation |
| AC7 failed/rejected enrichment leaves document usable | L1/L2 |
| AC8 retry identity | Shared W2/W4; L2 |
| AC9 changed source/stale review/history | L3 |
| AC10 confidentiality | Shared W1/W3; L2 selection and review filtering |
| AC11 external vocabulary is suggestion, not authority | L2 skill/request policy and W6 host observation |
| AC12 no automatic join/metric authority | Ariadne D1 native compile/grain gates, unchanged by L2 |
| §8 existing IDs/control/empty-ontology compatibility | L1; native unchanged control serialization checks |

Existing compiled pages, generic setup output, source references and published snapshots remain valid. New defaults are explicitly selected; existing KB adoption is reviewed and collision-blocked. Reverting the new service/SDK feature does not delete published artifacts or sources; native reviewed restoration remains the route for undoing admitted content.

Focused checks above are planned, not executed. Required repository CI and installed SDK/service wheel checks remain in shared W6; no separate enrichment certification matrix. Review only the named source/admission/privacy risks. Reuse passing evidence when its code, corpus and environment remain applicable; one authorized fix and one delta recheck, then return unresolved issues to the owner.

**Validation and verification policy (owner decision, 2026-11-06):** Verification before tests, and both at the minimum `agent-guardrails` justifies. L3 runs at most its one already-named focused `new-test` (VL3) plus existing checks only where the task actually changes that seam; no additional test files, per-task suites, or coverage targets. Per-task verification ends at parent inspection and the task's one independent review — no per-task comprehensive, installed, or real-host verification. One comprehensive verification pass runs once after ALL tasks (L-track, D-track, W5) complete, as part of shared W6: it drives the real installed surfaces and the real Pi drafting/reviewer journey with independently derived expectations (project-verification recipe discipline), covering what deterministic tests cannot establish. Required repository CI runs at candidate integration/delivery batches, never per task.

Manual evidence is limited to the real Pi drafting/reviewer journey that deterministic tests cannot establish. No model accuracy benchmark, live confidential corpus, broad ontology import, or production migration is implied. The shared plan owns final cross-product ordering and qualification; this plan is approved and ticketized, but implementation requires a separate grant.
