# Implementation plan: Opt-in document evidence reconciliation

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized; implementation not authorized by ticketization** |
| **Goal** | Make repeated document ingestion show safe source-linked changes against approved pages, with explicitly opted-in and non-authoritative model conflict advice. |
| **Source** | [Approved reconciliation specification, revision 1](../specs/2026-09-23-0004-evidence-reconciliation.md) |
| **Source approval** | Owner, pi session 2026-09-23 — complete design and written specification approved; exact scope is the source header's revision 1. |
| **Plan approval** | Owner, same session — approved this opt-in reconciliation plan and its validation gates; subsequently requested ticketization. |
| **Decisions** | Accepted clarifications to [ADR-0003](../adr/0003-staging-dir-review-gate.md) (single-user real documents keep human Promotion) and [ADR-0009](../adr/0009-standalone-proposal-first-ingestion.md) (approved Policy text goes to the configured model only on explicit reconciliation). |
| **Prerequisite** | Issue [#9](https://github.com/legout/ariadne/issues/9) is closed; confirm its author/init helper baseline is accepted and integrated before modifying `ariadne.ingest`. Retrieval issue #10 and answer-trace evaluation are independent. |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Boundaries and capture checkpoint

- Keep ordinary `ingest()` return shape, ingestion validation/credential refusal, safe Staging, existing `promote()` and OKF `sources[]` schema. Reuse Python 3.12, PyYAML, the existing OpenAI-compatible `complete` boundary and pytest; add no dependency, new ledger, author-loop behavior, or automatic promotion.
- **Vocabulary:** existing Policy, Context Layer, Staging, and Promotion terms suffice. **Decisions:** ADR-0003 and ADR-0009 contain the owner-approved review-gate and opt-in disclosure boundaries. **Behavior:** the approved source owns identity, change classification, advisory, failure, and acceptance. **Uncertainty:** mismatched sources require an operator decision, never path inference; provider suggestions remain fallible advice.
- **Touched security boundary:** an external document author can influence a proposed path that would select an approved Policy. The asset is approved Policy text, possibly containing a credential. Confirm approved-root containment, exact-path/source identity, and credential-pattern refusal before additional provider disclosure; never allow model advice to grant Promotion authority.
- One sequential writer after #9's baseline is accepted; immediately review identity/staging safety before adding provider egress, then review the integrated candidate. At most one parent-authorized fix pass and one delta recheck.

## Canonical ticket and requirement coverage

[#12 — Add opt-in document evidence reconciliation without automatic Promotion](https://github.com/legout/ariadne/issues/12) owns the executable task body, files, interfaces, two `new-test` validation units, red/green sequence, security gates, checks, completion evidence and non-goals. This overview records ordering and coverage; do not maintain duplicate task definitions.

| Specification acceptance | Ticket | Dependency |
| :--- | :--- | :--- |
| AC1 — human-edited Policy preserved, exact-path proposal, source-linked diff | #12, unit A | Accepted and integrated #9 |
| AC2 — unchanged repeat and provenance-only update | #12, unit A | Same |
| AC3 — rename warning, source mismatch, staging collision | #12, unit A | Same |
| AC4 — advisory failure, invented quotes and credential refusal | #12, unit B | Unit A identity/staging review |
| AC5 — ordinary ingestion unchanged | #12, units A–B | Same baseline |

## Execution and integration

After #9's helper changes are accepted and integrated, complete deterministic identity and staging work before Policy disclosure. The immediate post-A review covers the matching boundary; the post-B candidate review covers opt-in egress, failure paths, and default-ingestion integration. The parent retains implementation, fix and integration approval gates; creating #12 authorizes none of them. If Promotion or disclosure rules must change, return to `shape-design` and reconcile ADR/spec authority first.
