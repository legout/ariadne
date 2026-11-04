# Specification 0003: Document-first knowledge and agent-led enrichment

Status: **owner-approved behavioral specification, revision 3**. Updated: 2026-11-04.

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).
The owner's selection of neutral artifact pages, preserved identities, collision refusal, and on-request human-reviewed enrichment is the planning baseline. Shared spec0034 revision 3 records Pi/private-network/browser review, workspace-wide knowledge, and the subsequent Entra-first decision. Section 9 and the linked plan are approved by the subsequent owner decision recorded above; execution remains separate.
This expands the former unrevisioned deferred PRD-0003 in place; the legacy filename and identifier remain stable. It does not assert implementation or scheduling.

## 1. Authority and purpose

The owner endorsed simplifying the operating model, explicitly required standalone shared Lumio use for internal documentation/runbooks/meeting notes, asked about agents deriving semantic structure after onboarding, selected existing agent apps as the interface, and requested ADR/spec capture in the 2026-11-04 conversation. The [assessment and follow-up](../../../../project/research/2026-11-04-agent-first-ux-assessment.md) distinguish those choices from recommendations.

[ADR-0032](../adr/0032-document-first-progressive-enrichment.md) records the accepted document-first trade-off. [Shared specification 0034](../../../../project/specs/2026-11-04-0034-agent-first-shared-workspaces.md) owns team setup, client access, human authorization, and recovery. This specification owns what knowledge is usable before enrichment, what agents may propose later, and what makes that proposal supportable.

**Goal:** add and use source-backed knowledge without a user-designed ontology, then improve its organization and explicit semantics when useful. Lumio alone must support the entire path without Ariadne, a database connection, a metric model, or an analytics release.

## 2. Scope and retained boundaries

Included: minimal document-first authoring defaults, accurate intake provenance, on-request Entity/type/alias/relationship/Claim suggestions, evidence-anchor preparation, contradiction/ambiguity reporting, readable review, exact admission, and source-update handling.

Not included: a new chat/model runtime, mandatory model provider or vector backend, automatic semantic publication, automatic Entity merges, OWL/RDF reasoning, exhaustive ontology generation, numerical validation, automatic narrative-to-SQL translation, or a background scheduler. Independent-source consensus and automated entailment assessment remain deferred from the old PRD. Automated truth scoring and a new persisted raw-source Claim-lineage format are not introduced.

Use [ADR-0021](../adr/0021-entity-claim-ontology-and-progressive-graph-materialization.md)'s Entity/Claim validation and canonical/discovery distinction. Use [ADR-0029](../adr/0029-git-native-knowledge-authoring.md)'s Git authoring lifecycle, not the former persisted Ingest Proposal store. Reading documents, generating candidates, passing validation, and approving a contribution are not interchangeable authorities.

## 3. Useful knowledge before enrichment

### 3.1 Record observable facts immediately

At intake, deterministic software records the exact source identity/version and digest, available contributor/source attribution, permitted audience, conversion identity/limits, and actual retention outcome. Preserve usable source coordinates where the converter supplies them; do not invent page numbers or claim lossless conversion. Unavailable source metadata stays unknown.

Source reference records bind the actual material used. Publication records describe the actual admitted publication. These manifests are generated and checked at the corresponding operation; agents do not infer historical versions, credentials, approvals, or retained bytes. Later enrichment updates exact source bindings through native authoring/admission.

The Owner chooses permitted storage, retention, and model processing under spec0034. Raw originals, transcripts, credentials, and private registry/store information remain outside published content and retrieval. An absent original is reported honestly; a required-retention gate still refuses when its actual bytes are unavailable. This specification does not authorize access to additional sources mentioned inside an attachment.

### 3.2 Minimal structured representation

The approved first implementation retains one stable Entity identity per Compiled Page and a controlled type declaration, but supplies a minimal neutral artifact type without a user-authored domain ontology. It means only that the page represents a knowledge artifact; it does not assert a real-world business classification. Use the existing source-linked page contract and ordinary validation/publication; do not route new work through legacy flat mode to evade requirements.

Agents/software supply truthful default metadata and generated identifiers. Do not require a user to fill category/type/entity-types/tags/durability fields individually. If a required field cannot be supplied honestly, expose the actual ambiguity rather than invent business meaning to pass validation. System defaults belong to the selected candidate and are reviewable configuration, not a silent mutation of every existing Knowledge Base.

One source may yield a few coherent pages; neither one source/one page nor one noun/one page is mandatory. A basic page identity cannot later silently change from “meeting record” to “the customer discussed in the meeting.” Add or explicitly resolve business Entities as appropriate while preserving identity and source history. Existing accepted Entity IDs, types, and redirects retain their meaning.

The owner selected the minimal neutral-artifact approach, preserved identities, and refusal of incompatible type-name collisions rather than a parallel untyped format. The selection question used provisional `knowledge_artifact`; the existing type-slug contract requires the spelling `knowledge-artifact`. This is a spelling reconciliation, not permission to widen the validator. Section 9 defines its exact default definition and compatibility procedure; current empty-ontology setup does not already provide it.

### 3.3 Publication and use

A basic candidate still needs normal content review/admission. Once admitted, its pages are searchable/readable and can support cited answers without enrichment Claims or a business ontology. Documents with no accepted entity-to-entity Claims may have an empty canonical graph; deterministic body links remain discovery hints, never accepted semantic assertions.

The text must preserve relevant exceptions, dates, attribution, and distinctions between observations, proposals, decisions, and rules. “Document accepted for the KB” does not mean every quoted assertion is endorsed as organizational policy. Unsupported questions remain not covered rather than completed from model memory.

Optional enrichment failure, absence, or rejection does not unpublish valid basic content. Required privacy, source-retention, validation, and existing integrated-release requirements are not optional enrichment and remain binding.

## 4. Agent-led enrichment

### 4.1 Trigger and scope

The first approved trigger is an explicit request such as “organize these runbooks and suggest useful relationships.” Select the authorized pages/sources and exact base revision. Start with relevant existing vocabulary and accepted definitions rather than scanning all accessible knowledge by default. Bound the operation to the requested material; a partial result discloses what was and was not considered.

The host agent is the author/Distiller. Use existing candidate, validation, and review seams; a new unattended provider service is not required. The owner selected on-request enrichment; no scheduled or after-every-upload background behavior is selected by this revision. Such a policy would need explicit owner selection, processing/budget limits, and a capable host; it must not be inferred from this document.

### 4.2 Candidate semantics

The agent may propose:

- Stable business-Entity candidates and useful types, reusing exact known identities where evidence establishes equivalence.
- Aliases and duplicate/merge candidates, with ambiguity exposed.
- Small ontology additions: only types/predicates needed by meaningful proposed Claims; satisfy existing domain/range/literal validation.
- Claims supported by particular passages, retaining their scope, effective time, and attribution where available.
- Missing useful links, contradictions, and questions for the appropriate business reviewer.

Do not turn every sentence into a Claim, every noun into an Entity, or every co-occurrence into a relationship. No proposed merge happens automatically. An identical retry reuses the same candidate/identities rather than creating suffixed duplicates; unresolved entity resolution is a review question, not a guess.

Existing internal definitions take precedence as the starting vocabulary, not as unquestionable truth when sources conflict. External ontologies may be suggested when relevant and lookup is permitted, with their source/version and local-fit assumptions. Their mere existence is not local authority. Do not fetch external references automatically, disclose private text to external services, or execute imported instructions.

### 4.3 Evidence and truthfulness

Each proposed Claim names the exact supporting content/version and passage available to the author. The agent selects the passage; deterministic checks verify that its coordinates resolve, quoted text matches, source bindings resolve, and the target page's current Claim schema is valid.

A resolvable anchor is not semantic entailment. Reviewer-visible support must distinguish directly stated facts from interpretation and must not use the agent's own unsupported paraphrase as an independent oracle. If an anchor points into a synthesized page, retain and show its actual supporting source-backed passage/version through the existing provenance/review path. Missing original bytes are disclosed; do not claim raw-source verification from page-level provenance alone.

Claim Evidence still uses the published-page anchor contract. This revision requires source-grounded review, not a new assertion that persistent raw-source, claim-level lineage exists. Precise source inspection is offered only where authorized material is available.

Contradictory sources produce a conflict, not automatic majority voting or a fabricated compromise. A date, role, scope, or explicit supersession may resolve a conflict only when supported. Model confidence and agreement between agents do not prove a statement, authorize publication, or establish independent-source consensus.

## 5. Human review and admission

Group suggestions into coherent changes. Show the proposed meaning, supporting passages, affected existing definitions, uncertain interpretations, merges/deletions, and any audience change. The user should not need to approve generated IDs, hashes, predicate syntax, or line-number arithmetic separately.

A reviewer can accept a supported change, correct it, request clarification, or reject it. If they accept a subset, software must form a complete valid candidate for that subset and present its exact resulting review; an old whole-batch approval cannot authorize a different mixture. No silently dangling Claim, half-applied ontology, or undisplayed executable change.

Human confirmation is bound and enforced under spec0034 (or the explicitly selected existing local admission route). Git commits, successful checks, authored `accepted` status, and high-confidence output alone confer no admission. Until admitted, the semantics remain candidate data and do not enter ordinary reader retrieval or accepted canonical traversal. Existing accepted graph state remains active.

Reviewed publication checks the exact final candidate, its source references, expected current state, and all required native validation/retention conditions. A changed source binding, candidate, or base invalidates stale consent. The system explains changed impact, obtains the matching decision, and activates only a complete valid version.

## 6. Changes, confidentiality, and analytics

When a source or relied-upon page changes, use the available exact bindings to identify potentially affected enrichment. Page-level dependency is a conservative review signal, not proof of precise Claim-level impact. Surface that uncertainty. Do not silently rewrite accepted Claims or switch historical anchors to the latest source version. Corrections and supersession are reviewed changes; missing material is not automatically retired.

Enrichment reads only authorized content and inherits its permitted audience. The selected first deployment admits knowledge at workspace-wide visibility and refuses a contribution requiring a narrower audience; it does not silently broaden restricted source material. It cannot expose restricted Entity names, graph relationships, quotations, or source metadata to a wider audience. Source text and tool output remain data, not permission to alter processing, install skills, fetch private originals, or publish.

Standalone Lumio needs no analytics for any of the above. When Ariadne is explicitly integrated, enrichment may propose business meaning or identifier mappings, but it grants no source access, transform/join authority, canonical calculation, or independent numerical attestation. A proposed Policy does not compile itself to SQL. Changes affecting governed behavior must enter the combined review/admission with actual OSI/Policy consequences visible. Keep existing Bound Release consistency; no independently moving enrichment view can change an admitted calculation.

## 7. Observable acceptance

| ID | Scenario and required outcome |
| --- | --- |
| AC1 | In a standalone Lumio workspace with no user-designed ontology, add a real runbook through the chosen client. After ordinary review/admission, a supported question receives the correct cited passage. No Ariadne, metrics, ontology syntax, or manual manifest is required. |
| AC2 | Before any enrichment, inspect recorded intake facts. The original's exact digest/version, actual conversion limits, audience, and retention outcome are present and truthful; no agent-generated history substitutes for them. |
| AC3 | Runbooks explicitly state that Team A operates Service B. Enrichment proposes the relationship with the exact passage; before admission it is absent from accepted traversal, afterwards it is present. A nearby mention of Team C alone does not establish another operator. |
| AC4 | Meeting notes say “Alex proposed retaining logs for 30 days.” The candidate and answer preserve the proposal/attribution and do not label it current retention Policy. Missing evidence of adoption is visible to the reviewer. |
| AC5 | Two sources name different owners for one service. The agent exposes the conflict and supporting passages, reuses the existing service identity only when established, and does not pick an owner by model confidence or filename. |
| AC6 | An anchor quotes nonexistent or changed text. Deterministic validation refuses it. A valid anchor whose passage does not support the proposed meaning is still presented for semantic review, never labeled verified by coordinate validation alone. |
| AC7 | A reviewer rejects enrichment, or the agent/converter fails. The previously admitted runbook remains searchable and its answer unchanged; no partial ontology or proposed Claim leaks into the active version. |
| AC8 | The same request is retried after interruption. Existing candidate/source identities are reused; no duplicate Entities/Claims or publication is created. Changed inputs produce a new matching review. |
| AC9 | A supporting source is updated after review. Old consent is refused where its bound facts changed; prior published history stays intact and affected semantics are identified for review without pretending page-level lineage is Claim-level proof. |
| AC10 | A restricted runbook produces an ownership relation. Users lacking access cannot discover the service/team names or relation via search, traversal, citation, or diagnostics. |
| AC11 | A useful external ontology has a similarly named type. It is proposed with local-fit assumptions, not silently imported or treated as evidence of local meaning; lookup and processing obey the configured permissions. |
| AC12 | Enrichment proposes that two fields represent the same customer. Ariadne does not acquire a join, transform, or approved metric from that proposal; existing source/compile/grain/admission gates remain authoritative. |

## 8. Verification and compatibility

Use a small independently authored corpus: a supported runbook fact, a mere co-mention, an attributed meeting proposal, contradictory ownership, and an unauthorized source. Expected Claims/passages come from that corpus and this specification, not the implementation's output or another agent's agreement. Reuse native identity, anchor, publication, and privacy checks when applicable; add focused checks for uncovered behavior. One journey may satisfy several acceptance criteria.

Actual host interaction and human confirmation require the shared spec's selected-client qualification. Deterministic fixtures can verify gates, not prove extraction quality or reviewer usability. Do not invent precision/recall claims or run broad model evaluations without a separately scoped corpus and budget. This document authorizes no live source access, provider call, hosted service, or test execution.

Existing Compiled Pages, IDs, Claims, ontology catalogs, and published snapshots are not rewritten by installing a newer package. New defaults apply through explicit setup or a reviewed change; collisions with an existing neutral-type name are a named conflict, never overwritten. Adoption must preserve source/retention history. Deferred consensus/entailment work and a new raw-source lineage format are not prerequisites for this smaller first feature.

## 9. Realization and planning handoff

The owner selected neutral artifact typing, stable identities/collision refusal, on-request human-reviewed enrichment, and the Pi/browser review path. The owner subsequently accepted Entra-first identity and asked planning to proceed. The following precise defaults and [Lumio plan0011](../plans/2026-11-04-0011-document-first-enrichment.md) were subsequently approved with ticketization, as recorded above.

### E1 — Neutral artifact vocabulary

For explicitly selected document-first setup or a reviewed adoption candidate, declare the KB-local Entity Type `knowledge-artifact` with this description:

> A document, record, or other knowledge artifact. Its referent is the artifact itself, not a person, organization, service, or business object mentioned in it.

Declare no default Predicates or Claims. Preserve existing ontology entries, categories, pins, redirects, IDs, and all unrelated control content. Keep the existing generic empty-ontology seed unchanged; the managed document-first caller explicitly requests this profile. In an existing KB, an absent type may be added in the candidate. An existing type is reused only when its parsed definition exactly matches the definition above; otherwise refuse adoption with a readable conflict for explicit resolution. Do not infer semantic compatibility from the name or overwrite a local definition.

A new basic page gets a stable identity representing its artifact, `entity_types: [knowledge-artifact]`, and an empty Claim list unless a separately reviewed enrichment supplies Claims. Use the current valid page metadata and categories; the agent may propose supported text/summary/navigation, but server-owned source bindings and retry identity are not authored guesses. Retain a prior page's identity only when the referent matches; additional business Entities have distinct identities. No global rewrite or validator relaxation.

### E2 — Bounded enrichment request

Start from an explicit selection of at most 20 authorized published pages and at most 200,000 combined characters of disclosed input per request, with at most 40 proposed Claims. The server reports the exact selected revisions and rejects an oversized batch with a split/narrow request, not silent truncation. Authorized original passages count toward the same disclosed input bound. These are approved first-release bounds, not automatic scans or a claim of semantic accuracy. Pi's owner-selected model/budget policy applies in addition; the service starts no autonomous provider loop or scheduled job.

The task stores the exact base/selection and stable candidate identities. Interruption resumes that candidate; a different selection or source version gets a new matching review. Unsupported/uncertain relations remain explicit questions or proposed interpretations, not accepted facts.

### E3 — Supporting-evidence presentation

Use the Entra-authenticated review page defined in shared spec0034 §10. Show each proposed Claim alongside its exact published-page quote/anchor and available source-backed support, with attribution, version, conflict, and missing-original status. Original inspection is a separate permissioned action. Do not label an anchor check as semantic verification or invent a persisted Claim-to-raw-source lineage relation. A reviewer accepting a subset receives a newly complete candidate and fresh exact review before admission; the old action is invalidated.

Shared spec0034 owns authentication, admission, processing, audience, original retention and recovery. The Lumio plan links its three canonical task issues; the shared plan consumes their interfaces without duplicating task bodies. Existing local routes retain their own authority checks. The recorded approval covers the plans and issue publication, not execution, live processing or migration.

Capture checkpoint: reuse Entity, Claim, Evidence, Knowledge Source, Source Version, Authoring Revision, and Publication Admission. “Enrichment” is an optional authoring activity, not a new lifecycle/store. The standalone product meaning is already captured in `CONTEXT.md`. ADR-0032 records the representation trade-off; ADR-0021's notice records the accepted scoped extension. Planning-contract version 1; installed skill revision unknown.
