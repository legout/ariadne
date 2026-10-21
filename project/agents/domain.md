# Domain documentation

Layout: two scoped contexts in one repository.

- `CONTEXT.md`: canonical vocabulary for the Ariadne context (governed
  metrics), owned by the Ariadne Core (`packages/ariadne-data`).
- `project/lumio/CONTEXT.md`: canonical vocabulary for the Lumio context
  (Knowledge Base foundation), owned by the Lumio SDK members
  (`packages/lumio-wiki`, `packages/lumio-lancedb`).
- Ariadne decisions: `project/adr/`; Lumio decisions: `project/lumio/adr/`
  (imported with their original IDs and numbering).
- Scoped package instructions: `packages/lumio-wiki/AGENTS.md` and
  `packages/lumio-lancedb/AGENTS.md`; the root instructions govern everything
  else. `CONTEXT-MAP.md` at the repository root maps both vocabularies.
