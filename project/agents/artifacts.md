# Artifact mapping

Mapping: generated defaults. This file is declarative documentation, not executable configuration.

- project/research/: shared tooling investigations and probe reports;
  product-owned research lives under products/ariadne/project/research/ and
  products/lumio/project/research/.
- project/adr/: shared monorepo architecture decisions; product-owned
  decisions live under products/ariadne/project/adr/ and
  products/lumio/project/adr/.
- project/specs/: shared repository specifications; product-owned specs live
  under products/ariadne/project/specs/ and products/lumio/project/specs/.
- project/plans/: shared repository plans; product-owned plans live under
  products/ariadne/project/plans/ and products/lumio/project/plans/.
- project/tickets/: local work items.
- project/agents/: workflow configuration, including the tracker (project/agents/issue-tracker.md) and the context layout (project/agents/domain.md).
- products/ariadne/CONTEXT.md and products/lumio/CONTEXT.md: canonical domain
  vocabularies per the context layout declared in project/agents/domain.md.

Explicit project mappings recorded here override these defaults. Planning artifact and handoff semantics are owned by the `planning-contract` skill from `legout/skills`.

Explicit mappings for this repository:

- `products/lumio/project/`: imported Lumio records — `adr/`, `specs/`,
  `plans/`, `research/` and `agents/` keep their original namespaces and IDs
  under this root; `products/lumio/CONTEXT.md` is the Lumio vocabulary per
  `project/agents/domain.md`. `products/lumio/project/AGENTS.imported.md` is a
  preserved historical reference, not active guidance.
- `products/ariadne/project/`: Ariadne-owned `adr/`, `specs/`, `plans/`,
  `research/` records with their original namespaces and IDs.

Setup never moves existing documents and never fabricates glossaries, ADRs, or placeholder folders to match this map. A misplaced document is evidence of misclassification, not a mapping rule; resolve conflicts explicitly with the owner.
