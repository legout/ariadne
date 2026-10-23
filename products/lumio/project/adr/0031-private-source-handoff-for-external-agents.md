---
status: accepted
extends: ADR-0029
---

# ADR-0031: Private source handoff for external agents

## Context

The owner chose skill + CLI + native Git as Lumio's first complete external-agent
authoring journey, with independent contributor and maintainer environments and
BB + Pi as its first qualified harness. On 2026-10-23 the owner selected a private
S3-compatible exchange plus manual bundle fallback in BB thread
`thr_52d92z7irz`. The owner subsequently explicitly approved “specification 0010
revision 1 and ADR-0031 as written” and requested glossary capture and an
implementation plan, with “do not start implementation.” This records acceptance
of this ADR and the detailed behavior in
[specification 0010](../specs/2026-10-23-0010-external-agent-authoring-journey.md),
not execution or integration authority.

Scoped amendment, 2026-10-23: after planning exposed the need to resolve unchanged
baseline bindings on a fresh contributor machine, the owner chose
“Metadata-only baseline bootstrap.” Specification 0010 revision 2 §5.1 captures
that decision; plan revision 2 remains proposed and execution remains excluded.

Git transports compiled content and exact source references, but excludes private
Source Registry history and original artifacts. A maintainer on another machine
cannot admit managed content merely by fetching its PR when those exact Source
Versions are unavailable locally. A shared artifact bucket alone does not solve
the missing private registration/history handoff.

## Decision

Transfer selected exact source versions through a versioned private bundle bound
to the KB namespace and Git contribution. Import adds verified immutable versions
through supported registry operations and preserves existing history. It does
not synchronize or replace registry files, apply Git lifecycle intent, approve
content or activate publication.

Use private S3-compatible object storage as the automated exchange and the same
bundle/import contract for manual private transfer. The exchange is temporary
delivery infrastructure, separate from the maintainer's canonical private store
and public publication destination. Existing deployment credential mechanisms
authorize transport; Lumio introduces no central identity or source service.

Initialize fresh contributor history with a separate Source Baseline Snapshot:
maintainer-provided exact-base metadata, without original bytes. Use the same
exchange/manual transport with an explicit artifact-kind distinction. Preserve
metadata provenance and honest local artifact availability; only verified retained
bytes satisfy required-retention publication. This avoids distributing every
baseline original to contributors while preserving exact-version validation.

The external agent coordinates source reading, distillation, readable human review
and native Git submission through the skill and CLI. Exact-revision Publication
Admission remains a separate maintainer action under ADR-0029. MCP remains
read-only under ADR-0028.

## Alternatives and trade-offs

- A shared authoring host is smaller but fails the chosen independent-environment
  requirement and ties contributor operation to common private mutable state.
- Manual private transfer alone avoids infrastructure but leaves a user-operated
  gap in the complete conversational journey. Retain it as the fallback.
- A central registry/source service could coordinate access but introduces network
  APIs, identity, authorization and service operation beyond the first journey.
- Copying the full registry can overwrite unrelated history and transfer sources
  outside the contribution. A bounded immutable handoff makes scope reviewable.
- Full baseline source transfer was considered for fresh contributors and rejected
  in favor of metadata-only bootstrap: it unnecessarily expands original-document
  access and transfer volume. Removing exact-version checks would lose provenance
  guarantees and is not the chosen solution.
- Putting originals into the Git content repository violates existing source
  privacy/export boundaries and is not an alternative selected by this decision.

## Consequences

The bundle is a versioned compatibility surface and requires explicit identity,
integrity, import-conflict and retry contracts. A digest establishes content
integrity, not author identity or human approval. Deployment permissions and Git
review remain necessary. Exchange cleanup is operator-controlled; canonical
retained originals must survive disappearance of the exchange copy.

No new persisted authoring lifecycle, application dependency, custom encryption,
automatic IAM provisioning or implementation/integration authority follows from
this ADR. Specification 0010 owns observable behavior and qualification.
