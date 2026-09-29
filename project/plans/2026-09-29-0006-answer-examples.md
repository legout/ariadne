# Implementation plan: Saved answer examples

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized; implementation not authorized by ticketization** |
| **Goal** | Make explicitly submitted, bounded answer examples discoverable as labeled drafts and reviewed references without caching answers or weakening governed query paths. |
| **Source** | [Approved answer-example specification, revision 1](../specs/2026-09-29-0006-answer-examples.md) |
| **Source approval** | Owner, Pi conversation 2026-09-29 — complete written specification approved after six design decisions. |
| **Plan approval** | Owner, same conversation — “looks good. ticketize”; approved three sequential slices and requested GitHub issues, not implementation. |
| **Decision** | [ADR-0014](../adr/0014-separate-answer-example-store.md) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Constraints and capture checkpoint

- [`CONTEXT.md`](../../CONTEXT.md) owns Answer Example, Staging and Promotion terminology. ADR-0014 owns the separate per-project OKF v0.2 store boundary; the specification owns behavior. No new dependency, database, sync service, raw-SQL execution path, Context Layer page type or metric promotion is authorized.
- One sequential writer. Before starting, resolve ownership of the existing unrelated dirty worktree (`src/ariadne/authoring.py`, `src/ariadne/sources.py`, tests, demo data, lockfile and `.pi/settings.json`); use isolation where necessary and never discard another writer's changes. These tickets share the example-store interface and are not parallel-ready.
- Local JSON CLI and optional MCP adapt one transport-neutral implementation; review remains a separate human-operated local command. A local actor label is self-declared, not an authenticated domain-expert identity. Submitted text and citation paths can affect project Markdown and subsequent answer guidance; preserve containment and draft-versus-reviewed boundaries without inventing a malicious-local-owner scenario.
- **Capture checkpoint:** vocabulary captured in `CONTEXT.md`; durable decision in ADR-0014; scope, non-goals, failures and acceptance in approved specification revision 1; no unresolved material owner decision. Plan/ticket approval does not authorize implementation, integration, pushing or publication.

## Canonical tickets and requirement coverage

GitHub issues own the **only editable task bodies** (files, interfaces, prerequisites, test obligations, red/green steps and completion evidence). This plan retains only dependencies and acceptance coverage. The specification, ADR and this overview are currently local/uncommitted; ticket references point to their approved local copies until separately integrated.

| Specification acceptance | Canonical ticket | Dependency |
| :--- | :--- | :--- |
| AC1 — explicit bounded save, immediate labeled draft lookup, unchanged context | [#19](https://github.com/legout/ariadne/issues/19), [#21](https://github.com/legout/ariadne/issues/21) for agent confirmation | #21 after #20 |
| AC2 — scope mismatch and uncheckable draft cannot support an answer | [#21](https://github.com/legout/ariadne/issues/21) | Accepted #20 |
| AC3 — submitter attestation, operator review, no metric promotion | [#20](https://github.com/legout/ariadne/issues/20), [#21](https://github.com/legout/ariadne/issues/21) for guidance | #20 after #19 |
| AC4 — dependency change suspends reuse, history and revision retained | [#20](https://github.com/legout/ariadne/issues/20) | Accepted #19 |
| AC5 — fresh validated execution and honest governance/attestation | [#21](https://github.com/legout/ariadne/issues/21) | Accepted #20 |
| AC6 — malformed, oversize and escaped input; CLI/MCP parity; review isolation | [#19](https://github.com/legout/ariadne/issues/19), [#20](https://github.com/legout/ariadne/issues/20), [#21](https://github.com/legout/ariadne/issues/21) | Sequential |
| AC7 — unrelated Context Layer/OSI promotion unaffected | [#20](https://github.com/legout/ariadne/issues/20) | Accepted #19 |

## Execution and integration

Sequence [#19 save/search drafts](https://github.com/legout/ariadne/issues/19) → [#20 operator review/staleness/promotion isolation](https://github.com/legout/ariadne/issues/20) → [#21 agent guidance/MCP parity](https://github.com/legout/ariadne/issues/21). Accept each contract-defining slice before the next consumes it. Immediate read-only reviews of #19's input/storage boundary and #20's approved-write boundary cover the named risks; one candidate review of #21 covers new adapters and integration effects, not settled findings. The parent authorizes any small in-scope fix and at most one delta recheck; unresolved findings return to the human.

Use the focused checks in each ticket, then `git diff --check` and a requirement-to-evidence audit over all seven acceptance examples before claiming completion. #21's genuine local-agent smoke must be reported as unverified if no provider is available; do not fabricate a trace or add a provider-dependent CI gate. A material behavioral or interface change returns to the approved specification and its owner before affected tickets resume. No writer has been authorized by this ticketization.
