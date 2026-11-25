---
status: accepted
supersedes: ADR-0010 (separate source approval), ADR-0016 and ADR-0024 (multi-proposal CLI), ADR-0026 (two-step CLI part only)
---

# ADR-0029: Single approval with a source-first gate; consent convention

Accepted with [spec 0040 r3](../../../../project/specs/2026-11-22-0040-one-cli-simple-governance.md) (B1; owner decisions 2026-11-22 to 2026-11-24). It replaces the gate structure of ADR-0010 (separate source approval), ADR-0016 and ADR-0024 (multiple proposals driven from the CLI) where they conflict, and the two-step CLI part of ADR-0026. The Bound Release semantics of ADR-0026 and shared ADR-0029 are unchanged in B1; B3 amends them.

## Decision

1. **One command, `ariadne approve`.** It acts on the project's one active draft, with no proposal or revision IDs.
2. **Source-first gate.** A draft that adds or changes a source identity is a *source approval* and may contain only source declarations and their storage profiles. Every other draft is a *calculation approval* and may use only already granted sources.
3. **A source grant is not a release activation.** It is recorded in `.ariadne/source_grants.json` together with the consumed draft generation and the new source baseline, in one recoverable transaction with a single commit point. It authorizes bounded reads for authoring only (profiling, inspection, schema refresh, preview). Served calculations never silently read a newly granted identity before a calculation approval admits a release bound to it.
4. **Consent convention.** `approve` and `draft discard` need an interactive TTY and ask one question; no flag or environment variable skips it. The record stores the Git identity as an attribution label, the time and the approved digest. This is an operator-consent convention, not authentication and not a sandbox: a process under the operator's account is trusted with the operator's permissions.
5. **What is guaranteed.** No shipped agent interface (MCP tools, packaged skill, documented agent CLI commands) can approve, reject, discard, grant a source or confirm a mapping. Remote review stays the workspace server's separately authenticated browser review.

## Consequences

- The proposal-local `approve_sources` record and grant are removed; `authoring_propose_sources` is removed from MCP.
- Proposal, Staging and Promotion vanish from the vocabulary; proposals remain only as internal machinery under the draft.
- Superseded clauses carry one-line headers in the older specs; their history stays.
