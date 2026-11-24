---
status: proposed
amends: ADR-0013
---

# ADR-0031: Built-in drafting; host agents optional

[Spec 0041](../../../../project/specs/2026-11-24-0041-automatic-authoring.md)
proposes a reproducible local draft from granted source profiles instead of
requiring a harness to interpret profiles before an operator can try a metric.
Host agents still use Ariadne's existing surfaces; no agent package or agent
loop is introduced ([ADR-0027](0027-host-agents-only.md)).

Optional enrichment is a bounded call to an operator-selected endpoint, not an
implicit fallback. Operator-owned consent for exact outbound inputs and their
destination is separate from approval to read a source. This keeps ordinary
drafting usable without a model service and retains ADR-0013's distinction
between access, evidence and human admission. Model suggestions never acquire
calculation, mapping or Policy authority.
