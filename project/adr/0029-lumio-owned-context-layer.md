---
status: accepted
---

# ADR-0029: Lumio is Ariadne's mandatory Context Layer foundation

Owner decision, Pi conversation 2026-11-09: “ariadne soll IMMER lumio-wiki nutzen. ABER lumio-wiki soll auch ohne ariadne existieren können.” The owner subsequently excluded backward compatibility, selected fresh project setup, Answer Examples through Lumio, ordinary knowledge pages for operational guides, structurally valid page batches, and approved the complete in-chat design including refusal on missing required Context with “Zielbild freigeben (Recommended)”. This accepts the architectural direction and authorizes ADR/specification capture, not implementation. [Shared specification 0035](../specs/2026-11-09-0035-lumio-owned-context-layer.md) owns behavior; its written revision awaits owner review.

Ariadne always uses `lumio-wiki` for creation and management of its Context Layer. Lumio remains a general-purpose Knowledge Base foundation installable and usable without Ariadne. The dependency is one-way: `ariadne-data -> lumio-wiki`. The private Lumio application, a hosted service, LanceDB, S3, MCP and model-provider integrations are not made mandatory by this decision.

Use one Lumio-owned knowledge lifecycle rather than maintaining two bundle implementations. Ariadne supplies physical schema observations, analytical evidence and domain-specific content through that lifecycle; it retains source access, OSI/ODCS, bindings, numerical execution and semantic safety checks. Lumio owns generic page operations, knowledge validation, retrieval and publication. A technical page is not a reason for a second storage/parser/maintenance system, and knowledge does not gain calculation or join authority.

The alternatives were retaining optional integration and a full independent Ariadne bundle implementation, or merely requiring the SDK while keeping both implementations. Both preserve the duplication that prompted this decision. Reuse the existing native profile and SDK path instead. The cost is a required SDK dependency and a coordinated breaking change, while package identities, separate release families and Lumio's independence remain.

There is no compatibility mode, legacy runtime fallback, compatibility-only CLI adapter or automatic content migrator. Existing project data and admitted snapshots are not deleted or rewritten; required content is deliberately re-onboarded and admitted afresh. Repository examples and tests move to the new contract. Explicitly saved Answer Examples remain available through Lumio, never as an answer cache. Operational guides are ordinary knowledge pages, not a separate Ariadne Skill profile. Valid structural drafts remain distinct from human admission.

Queries use their exact admitted knowledge/analytics association and refuse before SQL if a required Context dependency is missing, invalid or unavailable to the authorized scope. Do not fall back to advisory-only execution or a second Context source. This requires neither an invented Policy for every metric nor blocking a query on unrelated drafts. Source Approval and human admission remain separate permissions.

## Scoped amendments

This decision supersedes only the conflicting dependency/Context ownership and compatibility obligations in:

- [Shared ADR-0027](0027-public-monorepo.md): replace symmetric package independence with one-way dependency; keep product-area ownership, package names and release boundaries.
- [Ariadne ADR-0026](../../products/ariadne/project/adr/0026-lumio-sdk-bound-governed-releases.md): replace optional SDK/standalone Context fallback; retain exact revision binding, native publication and Core-last activation.
- [Ariadne ADR-0007](../../products/ariadne/project/adr/0007-okf-bundle-structure-agent-generation.md): retire the independently maintained bundle and bookkeeping implementation, not technical fact ownership or governance.
- [Ariadne ADR-0015](../../products/ariadne/project/adr/0015-separate-answer-example-store.md): replace separate Example storage with Lumio pages while retaining their non-authoritative historical meaning and explicit consent.
- [Lumio ADR-0030](../../products/lumio/project/adr/0030-ariadne-context-profile-and-sdk-boundary.md): the Ariadne consumer is mandatory on the Core side; no reverse dependency or executable analytics is introduced into Lumio.

[ADR-0028](0028-agent-first-shared-workspaces.md)'s hosting, identity, curated retrieval and source-retention decisions remain scoped as approved. Document-only Lumio use remains independent. Mandatory knowledge-library use is not automatic activation, content approval, source access or permission to use the document-only retention exception for Ariadne.
