---
status: proposed
---

# ADR-0033: SQL promotion keeps joins in the planner

[Spec 0041](../../../../project/specs/2026-11-24-0041-automatic-authoring.md)
decomposes supported ad-hoc SQL into one dataset-scoped measure and a suggested
request over existing planner paths. It refuses shapes the planner cannot
reproduce rather than storing joined SQL as a metric or silently changing the
population. For example, target-key uniqueness prevents fan-out but does not
make an inner join equivalent to the planner's left lookup.

This retains [ADR-0006](0006-grain-governance-multi-cardinality-joins.md)'s grain
and lookup guarantees and [ADR-0028](0028-ossie-03-semantic-format.md)'s strict
dataset scope. No promotion invents a relationship or admits a calculation.
