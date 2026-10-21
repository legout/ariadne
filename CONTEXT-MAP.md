# Context map

This repository hosts two independently owned vocabularies in two product
areas. This file is navigation only — it changes no definitions and merges
nothing.

| Context | Vocabulary | Owner |
| --- | --- | --- |
| Ariadne (governed metrics) | [products/ariadne/CONTEXT.md](products/ariadne/CONTEXT.md) | Ariadne Core (`products/ariadne/packages/ariadne-data`) |
| Lumio (Knowledge Base foundation) | [products/lumio/CONTEXT.md](products/lumio/CONTEXT.md) | Lumio SDK (`products/lumio/packages/lumio-wiki`, `products/lumio/packages/lumio-lancedb`) |

Records keep their original numbering, meaning and provenance in their own
namespaces: Ariadne decisions in
[products/ariadne/project/adr/](products/ariadne/project/adr/), Lumio
decisions in [products/lumio/project/adr/](products/lumio/project/adr/)
(with each product's specs, plans and research under its own
`project/` likewise). Shared monorepo decisions and specifications stay in
the root [project/](project/) (ADR-0027, specs 0030/0031). Scoped package
instructions live in
[products/lumio/packages/lumio-wiki/AGENTS.md](products/lumio/packages/lumio-wiki/AGENTS.md) and
[products/lumio/packages/lumio-lancedb/AGENTS.md](products/lumio/packages/lumio-lancedb/AGENTS.md); the
root instructions govern everything else.
