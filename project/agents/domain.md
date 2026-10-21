# Domain documentation

Layout: two scoped contexts in one repository.

- `products/ariadne/CONTEXT.md`: canonical vocabulary for the Ariadne
  context (governed metrics), owned by the Ariadne Core
  (`products/ariadne/packages/ariadne-data`).
- `products/lumio/CONTEXT.md`: canonical vocabulary for the Lumio context
  (Knowledge Base foundation), owned by the Lumio SDK members
  (`products/lumio/packages/lumio-wiki`, `products/lumio/packages/lumio-lancedb`).
- Ariadne decisions: `products/ariadne/project/adr/`; Lumio decisions:
  `products/lumio/project/adr/` (imported with their original IDs and
  numbering); shared monorepo decisions stay in `project/adr/`.
- Scoped package instructions:
  `products/lumio/packages/lumio-wiki/AGENTS.md` and
  `products/lumio/packages/lumio-lancedb/AGENTS.md`; the root instructions
  govern everything else. `CONTEXT-MAP.md` at the repository root maps both
  vocabularies.
