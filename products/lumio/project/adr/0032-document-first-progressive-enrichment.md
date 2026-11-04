---
status: accepted
---

# ADR-0032: Document-first knowledge with progressive agent enrichment

Date: 2026-11-04. Revision: 3.

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

**Scoped owner selections during planning:** neutral artifact pages with stable identities and collision refusal, plus on-request, human-reviewed enrichment. The provisional identifier in the question was `knowledge_artifact`; the existing lowercase-hyphen slug rule requires `knowledge-artifact`. This does not change the selected meaning or authorize schema-validator changes. The complete written revision is accepted by the approval above.

The owner requires standalone shared Lumio use for documentation, runbooks, and meeting notes, and asked whether agents could derive ontology definitions, typed Entities, Claims, evidence anchors, and manifests after basic onboarding. The owner requested written ADR/spec capture after the proposed answer. This ADR records the accepted design, not automatic processing or implementation authority. [Specification 0003 revision 3](../specs/0003-model-assisted-extraction.md) owns the behavior and acceptance; [shared specification 0034](../../../../project/specs/2026-11-04-0034-agent-first-shared-workspaces.md) owns the managed team interaction.

## Decision

Make documents useful without requiring users to design a business ontology. Record exact source identities, versions, audience, conversion limits, and truthful original retention during intake. Generate source/publication manifests from actual runtime facts at their respective operations; never ask a model to invent missing provenance later.

After normal content admission, documents can be searched, read, and cited independently of semantic enrichment and independently of Ariadne. Agents may later propose useful Entity types, aliases, relationships, Claims, and supporting passages. Human review concerns meaning, conflict, merges, and consequential changes—not hashes, identifiers, or anchor arithmetic. Proposed semantics remain outside accepted graph traversal until admitted. Model confidence or agreement is not an approval or an independent truth check.

For the first approved implementation, retain the existing one-Entity-per-Compiled-Page contract and seed a minimal neutral artifact type. A basic page's identity denotes that knowledge artifact; it does not assert that the document is a business system, person, or Policy. Enrichment can add actual business-Entity pages and supported relationships through review without silently changing an existing ID's referent. This avoids both user-operated ontology setup and a new untyped canonical format. Spec0003 §9 defines the approved default and compatibility handling; no existing KB vocabulary is silently rewritten.

The existing host agent can author candidates through native boundaries. On-request enrichment is the first approved trigger. A new scheduler, provider service, autonomous agent swarm, or auto-publication mechanism is not necessary. Generated indexes and exact manifest bookkeeping remain deterministic and do not each become a human review item.

## Alternatives and consequences

- **Require a domain ontology before the first document:** retains current structured-first teaching, but places modeling before user value and encourages unnecessary inferred structure.
- **Introduce a separate untyped document format immediately:** makes optional domain typing explicit, but changes canonical loading, validation, identity, export, and compatibility contracts. Not recommended for the first implementation without evidence that neutral artifact pages are inadequate.
- **Automatically accept high-confidence extractions:** reduces visible review but confuses model confidence with source support and organizational authority. Not selected.
- **Preserve source-backed pages first; propose semantic structure later:** retains useful portable content and existing validation seams, while accepting that the graph may initially be sparse. Sparse honest structure is preferable to invented completeness.

This is an accepted scoped extension of [ADR-0021](0021-entity-claim-ontology-and-progressive-graph-materialization.md): retain stable identity, controlled types for declared semantics, evidence-bearing Claims, separate canonical/discovery graphs, and bounded traversal. Change the ordinary onboarding default and take the deferred assisted-extraction work into a reviewable target. Do not restore the retired proposal store: [ADR-0029](0029-git-native-knowledge-authoring.md) still supplies Git authoring and exact publication admission.

Claim anchors in compiled content are not proof of raw-source entailment. The reviewer must be able to inspect actual support and attribution; valid coordinates or two agreeing agents cannot turn a meeting suggestion into company policy. Source updates produce visible review needs, not silent revision of accepted history. Confidential input cannot become public graph topology through enrichment.

No OWL/RDF reasoner, automatic Entity merge, independent-source consensus engine, new Claim lineage format, or removal of Ariadne's execution gates follows from this ADR. Existing contracts remain in force except for the explicit scoped amendments accepted here.
