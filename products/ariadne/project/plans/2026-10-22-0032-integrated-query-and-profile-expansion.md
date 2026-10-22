# Plan 0032: Integrated query and technical-profile follow-ups

**Status:** revision 1 — ticketized on owner request, 2026-10-22; execution
proposal only. Owner approved the complete design and Spec/ADR capture, then
requested “ticketize”. No implementation, test/service execution, integration,
push, tag or release is authorized. Contract: planning-contract v1; installed
skill provenance unknown.

## Source and capture

[Specification 0032 revision 1](../specs/2026-10-22-0032-integrated-query-and-profile-expansion.md)
owns behavior and independent acceptance examples. Ariadne ADR-0026 and Lumio
ADR-0030 contain the accepted rationale; the Ariadne glossary captures Governed
Detail Query and Input Context. No new producer schema or Policy interpreter
is assumed. Source text and scoped amendments were local/unpublished at
ticketization. The owner subsequently authorized their commit/push and task-state
update; this does not authorize implementation. Record the actual published
source commit in the tickets before dispatch, never an assumed main-branch URL.

Material choices are settled. Exact Policy/check association and additive
input_context wire details remain an explicit readiness prerequisite in #82,
not an implementer's discretionary behavior change. A necessary schema or
behavior change returns to the owner for an amended source before execution.

## Canonical task ownership and order

GitHub owns the complete task bodies; this file owns only order, coverage and
shared gates. These are follow-ups to #76, not reopened #79/#80 deliverables.

- [#82 — C1: exact contracts](https://github.com/legout/ariadne/issues/82):
  source correspondence and written interface completion; no product edits.
- [#83 — P1: technical profiles](https://github.com/legout/ariadne/issues/83):
  blocked by #82; produce accepted profile/inspection/admission/read behavior
  and its consumer contract before query implementation consumes it.
- [#84 — Q1: integrated queries](https://github.com/legout/ariadne/issues/84):
  blocked by #82 and #83; vertical detail, record and Ad-hoc paths, their public
  surfaces, guidance and final source/installed qualification.

Sequential ownership is preferred because runtime, authoring and integration
tests overlap. No parallel writers or implementation dispatch is authorized.
When execution is approved, follow root AGENTS and orchestrate-implementation:
verified Pi roles, registered isolated worktrees, one writer per worktree,
parent-controlled oracle inspection, committed handoffs and bounded reviews.

## Requirement coverage

- Spec0032 §§1–4 and acceptance 1–3, 5: #82 fixes exact applicability/coverage
  contracts; #83 validates their admitted representation; #84 enforces actual
  operation dependencies and preserves native authority.
- §§5–6 and acceptance 4, 6: #83 owns full native metadata, authentic evidence,
  explicit inspection, curated content and human admission.
- §7 and acceptance 7–10: #84 owns pinned input_context, operation truthfulness,
  budgets, A/B session isolation, standalone/public-surface correspondence and
  final qualification; #83 preserves the underlying admission guarantees.
- §9: #82 owns interface/source readiness; all tickets retain approval gates.

## Shared verification and stop rules

Task bodies assign their focused independent-oracle checks. C1 is no-new-test
source/document correspondence. P1 has one synthetic end-to-end profile
journey; Q1 has one distinct focused case per newly enabled operation, reusing
one authored dataset and shared isolation/budget legs. Names in the tickets
are proposed future tests, not currently existing runnable nodes.

Reuse the repository's required component-configured lint/native CI selections,
source-pair and installed-wheel boundaries as final candidate gates; do not
replicate full suites per step. Frozen-source/dependency/API changes invalidate
only the corresponding reused evidence. A concrete command budget, qualified
environments and any owned synthetic service must be assigned and separately
authorized before execution; this plan starts none. Preserve every raw failure
and actual skip; split corrected-node evidence is never a combined green run.

P1 receives immediate independent review before consumer work; Q1 receives
one final candidate review of new code and integration effects. C1's
low-risk documentation uses source correspondence/owner written review.
At most one parent-authorized correction and delta recheck per reviewed unit;
remaining blockers go to the owner. No extra evidence ledgers or sign-off files.

Source completion is not a new public release. The published-SDK pin,
producer-first package pairing, real sources/private applications/Agent-Tau,
integration, push and releases stay outside this ticketization authorization.
