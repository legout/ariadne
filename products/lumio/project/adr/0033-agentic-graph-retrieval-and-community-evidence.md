---
status: accepted
amends: ADR-0010, ADR-0011, ADR-0021
---

# ADR-0033: Bounded agentic graph retrieval and Community Evidence Bundles

Revision: **2, owner-approved written corrections**. Original date: 2026-11-11.
Written revision 2 approved: 2026-11-12.

**Approval history:** “approved” accepted the revision-1 shaping direction.
After critical review, “ok. lets fix this” authorized document repair; the owner
selected **Host agent** orchestration and **Unverified synthesis** reports.
This revision reconciles those selections and the budget, coverage, and
citation-lifecycle refinements. “ok. create the plan” on 2026-11-12 approves the
presented written revision 2 and authorizes plan drafting.
[Specification 0012 revision 2](../specs/2026-11-11-0012-agentic-graph-retrieval.md)
owns behavior and acceptance. The later written approval, not the original
direction approval, covers the revised operational defaults. The later
“ok. ticketize” (2026-11-12) approves plan0012 revision 1 and its named tracker
publication only: [epic #116](https://github.com/legout/ariadne/issues/116)
links canonical G1–G4 tasks and owns V. No implementation or execution authority follows.

## Context

Lumio already provides reviewed Entities and Claims, bounded graph traversal,
citation-ready Evidence, zero-index lexical retrieval, optional hybrid
retrieval, and lexical Entity-resolution candidates. It lacks an autonomous but
accountable way to select and refine those retrieval strategies, a structured
multi-hop context for reasoning, corpus-wide community synthesis, and optional
semantic Entity matching.

Classical GraphRAG derives its graph and community reports through unattended
model indexing and may use those generated artifacts as answer context. Lumio
instead treats admitted Compiled Pages as canonical and excludes raw sources
from Reader retrieval. Copying GraphRAG wholesale would weaken those boundaries;
adding only more retrieval primitives would leave query planning and global
questions unsolved.

The durable decision must also address a new citation case: aggregate Community
Reports are useful answer context, but generated report prose is not inherently
supported merely because its community membership and citations resolve.

## Decision

### Keep deterministic Core tools and existing host-agent orchestration

The Core SDK owns deterministic Query Plans, retrieval execution, Graph Context,
community/report artifact loading and structural validation, and Entity
candidates. Workspace exposes authenticated tools and enforces version,
visibility, preparation, budget, and exact-readback contracts. The selected host
agent performs understanding, follow-ups, report drafting, passage checking,
and answer synthesis. No new Workspace agent runtime or provider-credential
store is introduced.

This preserves shared [ADR-0028](../../../../project/adr/0028-agent-first-shared-workspaces.md)
and [spec0034 §§1–2](../../../../project/specs/2026-11-04-0034-agent-first-shared-workspaces.md),
not the older private-app runtime assumption. Pi is the first qualified-host
target; local SDK/CLI callers can execute explicit plans/readback without
Workspace or a model. Other hosts require actual qualification. The base stays
model-free, community algorithms remain optional, and no new distribution,
graph database, or report-generation LLM extra is needed.

### Make planning bounded and explicit

The planner has four modes: `basic`, `local`, `path`, and `global`. Every plan
binds an exact Published Version and authorized visible-set identity, records
stable Entity/community identities and graph parameters, and exposes its trace.
The default is one initial retrieval plus at most two refinements. A single
request-wide allowance additionally bounds model calls/tokens, tool operations,
query embedding, report fan-out, Evidence/text, and elapsed time, including all
map/reduce calls and retries. Specification 0012 defines the approved defaults.
Core/Workspace account for tools and artifacts; the supported host must enforce
its model and deadline share or disclose bounded mode as unavailable.

Outcomes are `sufficient`, `unsupported`, `needs_clarification`,
`capability_unavailable`, and `budget_exhausted`. Sufficiency is a host assessment
of a bounded answer with cited support, not deterministic entailment or proof of
corpus-wide absence. Explicit mode/seed execution works without a model; Core
does not promise natural-language classification.

Models may propose structured understanding and follow-ups but cannot change
authorization, version, bounds, identity, or publication state. Global questions
do not silently degrade into local answers.

### Serialize graph structure without making it Evidence

Graph Context contains accepted Claims, Claim Evidence anchors, paths, and
explicitly marked navigation-only Extracted References. It supports reasoning
about multi-hop structure while final claims continue to require Compiled Page
Evidence. Disputed and superseded Claims do not enter ordinary Reader context.

### Derive separate canonical and discovery communities

Operator-side preparation builds hierarchical communities for one exact
Published Version, visible-set identity, and graph scope. Canonical communities
use accepted Claims; discovery communities add Extracted References. Their
artifacts are separate and always disclose scope. Community IDs survive rebuilds
through membership-overlap matching; artifact versions remain content- and
generator-identified.

Preparation and report generation never run implicitly during Reader requests.
Unconnected pages remain visible as singleton/unclustered entries. The first
Global Search release supports exploratory thematic synthesis, not exhaustive
corpus counts, universal negatives, completeness, or “most common” rankings.
It discloses included/omitted members and deduplicates parent/child coverage and
Evidence; repeated summaries are not independent corroboration. Questions
requiring exhaustive aggregation must be narrowed or refused, not answered from
a ranked report sample.

### Make Community Reports citable only through Evidence Bundles

A Community Report is a derived aggregate artifact, not a canonical Synthetic
Page. Every citable section requires an Evidence Bundle containing its exact
report citation, offered member Compiled Page Evidence, generation/coverage
metadata, and an explicit `generated-unverified` label.

Activation checks bindings, coordinates, identities, and completeness, not
semantic entailment. Structurally valid but incorrect prose may pass; it is not
certified as supported. The host must inspect member passages for each answer
assertion, preserve attribution/exceptions/scope, and omit or refuse unsupported
conclusions. “Proposed retention” must not become “adopted policy.” This
behavior needs independent host examples, not a promise of universal model
verification or another report-review lifecycle.

Answers may cite report synthesis only together with the member Evidence
supporting each used assertion. Report-only and mismatched citations fail
structural validation; citation presence alone is not a truth check. Raw Source
Artifacts, unadmitted candidates, and self-supporting report truth remain
excluded.

This additively extends ADR-0021's Evidence model for aggregate reports; it does
not make Claims, Extracted References, Graph Context, or model confidence into
Evidence. Existing page-only Evidence and Citation behavior is unchanged.

### Resolve semantic Entities conservatively

Resolution tries exact unique identity first, then lexical candidates, then
optional semantic vectors through `lumio-lancedb`. FTS candidates alone never
auto-seed by rank. Semantic graph seeding requires configured score and
runner-up-margin thresholds; ambiguity triggers clarification for
entity-critical queries. Candidates never merge Entities, mutate Claims, or
publish content.

Corpus vectors and community artifacts are built operator-side over authorized
visible pages. New query text requires query-time encoding: an explicitly
configured local adapter or owner-authorized remote embedder may perform it
within model-processing policy and the same request budget. No corpus rebuild
or hidden-page upload occurs on a Reader request. The query model/dimension and
encoding roles must match the prepared index; denied, unavailable, or
incompatible encoding is disclosed rather than masked as zero matches.

This is an opted-in follow-up, not a change to #103's initial no-embedding route.
Semantic adoption requires independently authored comparison against
exact/alias/FTS behavior, including ambiguity, negative, hidden-Entity, and
previously unseen query cases.

## Considered Options

- **A new Workspace model runtime** — rejected in favor of the selected host
  agent and existing processing policy; it would duplicate Pi orchestration and
  change the shared architecture.
- **Workspace-only deterministic tools** — rejected because standalone Core SDK
  and CLI consumers must share plans, Graph Context, and artifact readback.
- **A new GraphRAG distribution** — rejected as premature packaging and
  orchestration duplication.
- **A free-form agent tool loop** — rejected because fixed modes, explicit
  outcomes, and bounded refinement are more reproducible and evaluable.
- **Derived reports only as retrieval guides** — not selected; the owner chose
  citable reports, with Evidence Bundles preserving member-page support.
- **Standalone synthetic report Evidence** — rejected because generated aggregate
  prose must not become self-supporting truth.
- **Reviewed canonical Synthetic Pages for every report** — rejected because
  human admission of frequently rebuilt derived reports would be
  disproportionate and would stale quickly.
- **Canonical communities only** — not selected; the owner requires both
  canonical precision and discovery coverage from the first release, kept in
  separate artifacts.
- **Community detection and generation in the base installation** — rejected to
  preserve the model-free lightweight base.
- **Always accept the top semantic Entity candidate** — rejected because a
  confident wrong seed can redirect the entire answer to the wrong subgraph.

## Consequences

Lumio gains additive Query Plan, Graph Context, Community, Community Report,
Evidence Bundle, Global Search, and Semantic Entity Resolution contracts.
`products/lumio/CONTEXT.md` owns their meanings, and specification 0012 owns
their behavior, failures, compatibility, and acceptance examples.

Existing canonical Markdown, Claims, Published Versions, and ordinary retrieval
remain valid without migration. Optional capabilities must fail truthfully when
unprepared. Community Reports require versioned artifact retention for
historical citations. Activations select a complete immutable report-set ID
separately from canonical publication; each query pins that ID once, and exact
report/section readback verifies its digest and current authorization. Explicit
regeneration creates a new preparation key/set even with the same model. Missing
historical bytes cannot be replaced by newly generated prose.

Cited report sets, bundles, and selection metadata enter existing backup/restore
scope and are retained until explicit operator deletion. They are derived but
not disposable-index cleanup targets. Deletion discloses affected citations;
subsequent readback returns unavailable without changing canonical content or
regenerating under the old identity. Specification 0012 §7.5 defines this
lifecycle without a second canonical store.

Open issues #103 and #112 supply scoped Evidence and stable identity/readback;
#107 supplies the baseline evaluation. The new work is a separate follow-up
epic, not an expansion of those approved tickets. Closed #95 and #167–#173
remain the reviewed-enrichment and graph foundations.

Assurance focuses on the six review deltas: compatible query encoding,
structural versus semantic report support, real host ownership, cumulative
budgets, honest thematic coverage, and exact artifact readback/retention.
Independently authored fixtures establish deterministic gates; the bounded real
host examples establish only their observed behavior. No universal entailment
or semantic-quality assumption follows. Written revision 2 is approved for
planning; the implementation plan and execution remain separately gated.
