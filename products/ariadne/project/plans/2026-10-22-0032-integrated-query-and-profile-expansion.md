# Plan 0032: Integrated query and technical-profile follow-ups

**Status:** revision 2 — exact contracts frozen, 2026-10-22; execution
proposal for the #83/#84 validation assignment. Revision 1 (same day) was the
ticketized execution-order overview. The owner approved the complete design
and capture, then — through the orchestration parent — explicitly approved
the Core-owned Policy-binding carrier and the accompanying namespace repair
before instructing “Implementiere die offenen issues autonom” (spec0032 r2
§10). #82 is a documentation-only unit; #83/#84 isolated execution is
authorized once their contract prerequisites are accepted. No target
integration, push, tag or release. This plan is an execution proposal, not
runtime qualification; parent acceptance of the C1 unit is pending until
its delta inspection. Contract: planning-contract v1; installed skill
provenance unknown.

## Source and capture

[Specification 0032 revision 2](../specs/2026-10-22-0032-integrated-query-and-profile-expansion.md)
owns behavior, acceptance examples and the exact §10 contracts: the authored
versioned `policy_bindings` block, the closed existing-check catalog, staged
capability revisions, the additive `input_context` schema and the frozen
operation pipeline. Ariadne ADR-0026 and Lumio ADR-0030 record the accepted
rationale; the Ariadne glossary captures Governed Detail Query, Input
Context, Policy Binding and Support Revision. The native producer schema is
unchanged. §10's readiness grounding was verified by source correspondence
against the current runtime baseline at writing time; no implementation has
started. Material changes still return to the owner for an amended source
before execution.

## Canonical task ownership and order

GitHub owns the complete task bodies; this file owns only order, coverage and
shared gates. These are follow-ups to #76, not reopened #79/#80 deliverables.

- [#82 — C1: exact contracts](https://github.com/legout/ariadne/issues/82):
  source correspondence and written interface completion; no product edits.
- [#83 — P1: technical profiles](https://github.com/legout/ariadne/issues/83):
  blocked by #82; lands support revision 2 (profile-expanded) — Dataset/Table/
  Computation admission, `policy_bindings` validation/inventory and explicit
  inspection — coherent **before** any query operation is advertised.
- [#84 — Q1: integrated queries](https://github.com/legout/ariadne/issues/84):
  blocked by #82 and #83; builds support revision 3 (query-expanded) on the
  accepted revision-2 behavior — vertical detail, record and Ad-hoc paths,
  `input_context`, budgets and final source/installed qualification.

Sequential ownership is required: a revision-2 admission must not advertise
the three query operations (spec0032 §10.3), so P1 lands coherent before Q1.
No parallel writers. When execution is approved, follow root AGENTS and
orchestrate-implementation: verified Pi roles, registered isolated worktrees,
one writer per worktree, parent-controlled oracle inspection, committed
handoffs and bounded reviews.

## Requirement coverage

- Spec0032 §§1–4, §10.1–§10.3 and acceptance 1–3, 5: #82 froze the exact
  applicability/check/coverage contracts; #83 implements their admitted
  representation (revision 2), applying the binding contract to the existing
  governed operations its revision advertises — explanatory disclosure for
  `get_metric`, executed-check attestation for `query_metrics`, including a
  narrow enforcement touch in the query path — without enabling the
  revision-3 operations; #84 enforces actual operation dependencies and
  preserves native authority (revision 3).
- §§5–6 and acceptance 4, 6: #83 owns full native metadata, authentic
  evidence, explicit inspection, curated content and human admission.
- §7, §10.4–§10.5, §10.3 compatibility and acceptance 7–10: #84 owns pinned
  `input_context`,
  operation truthfulness, budgets, A/B session isolation, staged-revision
  compatibility, standalone/public-surface correspondence and final
  qualification; #83 preserves the underlying admission guarantees.
- §9: #82 complete; all tickets retain approval gates.

## Shared verification and stop rules

Task bodies assign their focused independent-oracle checks; the bounded
assignment is:

- **P1 — one focused synthetic profile journey** (single invocation): author
  a KB with Dataset/Table/Computation and Policy profiles plus a
  `policy_bindings` block; observe the closed-validation refusals (unknown
  check, check not executed for the bound operation, closure policy lacking a
  binding, invented obligation, wrong-revision operation) as fixed-oracle
  refusals; then one explicit inspection → candidate → review → admission
  capturing `support_revision` and the binding inventory, with the three
  query operations still refusing on that admission.
- **Q1 — one focused case family** reusing the same authored dataset: a
  detail leg (requested lookup-path coverage; an unproven path still
  refuses), a records leg (`governed: false` with pinned full-content
  `input_context`), an Ad-hoc leg (`context: null`, `input_context`, static
  IO authority before any read), a budget leg (acceptance 8: mandatory-Context
  overflow refuses without execution) and an A/B session pin (acceptance 7).
  Expected values come from authored inputs and the spec contracts, never
  implementation output.
- **Final gates once, at final scope:** the repository's required
  component-configured lint/native CI selections and source-pair/installed-
  wheel boundaries — once for the completed candidate, not per step and not
  as redundant matrices. Existing green evidence is reused while the relevant
  code, inputs and environment match.

Environment prerequisites: a source-bound Python 3.14 environment is being
prepared by the parent; any S3 leg reuses the same synthetic fixture through
native S3 publication and must be synthetic and run-owned — no real sources,
no real credentials, no reused removed containers. The S3 CI job's
pre-existing `tests._s3_fixtures` ModuleNotFoundError is a separate parent
blocker and is not repaired by these tickets.

Names above are proposed future checks, not currently existing runnable
nodes. Preserve every raw failure and actual skip; split corrected-node
evidence is never a combined green run. Frozen-source/dependency/API changes
invalidate only the corresponding reused evidence.

P1 receives immediate independent review before consumer work (its public
runtime contract — capability tables, binding validation, inventory — gets a
fresh independent review before Q1 consumes it); Q1 receives one final
candidate review of new code and integration effects. C1's low-risk
documentation is subject to parent source inspection of its delta; acceptance
is pending until that inspection. At most one
parent-authorized correction and delta recheck per reviewed unit; remaining
blockers go to the owner. No extra evidence ledgers or sign-off files.

Source completion is not a new public release. The published-SDK pin,
producer-first package pairing, real sources/private applications/Agent-Tau,
integration, push and releases stay outside this authorization.
