# Specification 0012: Bounded agentic graph retrieval and Global Search

Status: **owner-approved behavioral specification, revision 2**.
Original date: 2026-11-11. Written revision 2 approved: 2026-11-12.

**Written approval — 2026-11-12:** “ok. create the plan” approves the presented
written revision 2 and authorizes implementation-plan drafting. This includes
its request-wide defaults, exploratory-only global conclusions, and exact
report-retention/readback contract. That approval granted no implementation,
issue mutation, commit/push, integration, deployment, release, or production/model access.

**Ticket publication — 2026-11-12:** “ok. ticketize” subsequently approves plan0012
revision 1 and its named epic/issues/source snapshots and cross-reference
comments. The canonical tickets are [epic #116](https://github.com/legout/ariadne/issues/116)
and [G1 #117](https://github.com/legout/ariadne/issues/117),
[G2 #118](https://github.com/legout/ariadne/issues/118),
[G3 #119](https://github.com/legout/ariadne/issues/119),
[G4 #120](https://github.com/legout/ariadne/issues/120); V belongs to the epic.
It changes no behavior in this specification and grants no execution,
commit/push, integration, deployment, or release authority.

**Approval history — 2026-11-11:** “approved” accepted the revision-1 shaping
direction: bounded planning, Graph Context, citable Community Reports with
Evidence Bundles, both graph scopes, optional capabilities, and conservative
Entity resolution. A critical review then found six contract gaps. The owner
requested “ok. lets fix this” and selected **Host agent** orchestration and
**Unverified synthesis** reports. Revision 2 reconciles those selections with
query-time embedding, enforceable request budgets, limited global conclusions,
and exact report readback/retention. Its numerical defaults and remaining
operational refinements were proposed for written review, then approved by the
2026-11-12 decision above; the earlier approval was not used retroactively. No implementation, execution, issue mutation, integration,
deployment, release, or production-data authority is granted.

Architecture: [ADR-0033](../adr/0033-agentic-graph-retrieval-and-community-evidence.md).
Vocabulary: [Lumio `CONTEXT.md`](../../CONTEXT.md). Planning Contract version 1;
installed contract provenance `unknown`.

## 1. Purpose

Add four progressively enhanced retrieval capabilities to Lumio:

1. a bounded agentic Query Planner over basic, local, path, and global modes;
2. a structured Graph Context serializer for multi-hop reasoning;
3. derived community hierarchies, citable Community Reports, and Global Search;
4. conservative semantic Entity resolution for query planning and review.

The design closes graph-retrieval capability gaps without weakening Lumio's
canonical Compiled Pages, reviewed Claims, authorized visibility, exact
Published Versions, or citation/refusal boundary.

## 2. Authoritative context and tracker reconciliation

This specification is a follow-up, not an expansion of existing approved work:

- Open [#103](https://github.com/legout/ariadne/issues/103) owns scoped Evidence,
  exact Published Versions, stable identity/readback, and operator-prepared
  retrieval caches; it explicitly excludes graph/ontology tool expansion. The
  Query Planner consumes that boundary rather than modifying it.
- Open [#112](https://github.com/legout/ariadne/issues/112) owns ordinary-page
  navigation and stable Entity ID/exact revision follow-ups. New retrieval
  operations use stable Entity IDs and exact versions, never title-derived
  identity or mutable-latest substitution.
- Open [#107](https://github.com/legout/ariadne/issues/107) owns the installed
  journey and Zero-Index/BM25 evaluation. Semantic Entity resolution is a later
  evaluated enhancement, not a hidden expansion of that evaluation into an
  embeddings mandate.
- Closed [#95](https://github.com/legout/ariadne/issues/95) preserves bounded,
  source-supported, human-reviewed enrichment. Retrieval and resolution never
  merge Entities, accept Claims, or publish content.
- Closed [#167](https://github.com/legout/lumio/issues/167) through
  [#173](https://github.com/legout/lumio/issues/173) established the Entity /
  Claim graph, projections, claim-aware traces, and lexical Entity-resolution
  candidates. This specification enhances that foundation rather than creating
  a parallel graph or identity system.
- Open epics [#85](https://github.com/legout/ariadne/issues/85) and
  [#108](https://github.com/legout/ariadne/issues/108) retain their approved
  bodies and ordering. Later planning creates a separate follow-up epic and
  cross-references it; no existing ticket is silently repurposed.

ADR-0010's progressive packaging, ADR-0011's canonical/discovery distinction,
ADR-0021's Entity/Claim model, ADR-0029's exact publication admission, and
ADR-0032's on-request human-reviewed enrichment remain binding. Shared
[ADR-0028](../../../../project/adr/0028-agent-first-shared-workspaces.md) and
[spec0034 §§1–2](../../../../project/specs/2026-11-04-0034-agent-first-shared-workspaces.md)
retain host-agent model orchestration; this work adds tools and optional
retrieval capabilities, not a server-side answer runtime. Query-time embedding
in §8 is an explicitly opted-in follow-up capability and does not change #103's
initial no-embedding path or #107's baseline evaluation.

## 3. Scope and non-goals

### Included

- deterministic Core-owned plan records, execution, Graph Context, derived
  artifact loading, validation, and candidate resolution;
- selected host-agent question understanding, bounded follow-up generation,
  Community Report drafting, member-passage checking, and cited answer synthesis;
- Workspace-owned authenticated tools, scoped preparation/publication of derived
  artifacts, and exact report/Evidence readback, without a new model runtime;
- canonical and discovery community artifact families from the first release;
- operator-side preparation of community and semantic derived artifacts;
- standalone Knowledge Base use without Ariadne analytics.

### Not included

- raw Knowledge Source/TextUnit RAG or raw-source citations;
- a new Workspace/server agent runtime, mandatory provider service, or a
  free-form autonomous tool loop;
- automatic Entity merges, Claim mutations, enrichment, or publication;
- Community Reports as self-supporting truth or canonical Synthetic Pages;
- a graph database, a fourth distribution, or a base model/embedding dependency;
- new SQL, join, metric, source-access, or Ariadne execution authority;
- production migration, autonomous scheduling, or universal model-quality
  claims;
- modification of the approved behavior owned by #85, #103, #107, #108, or #112.

## 4. Shared invariants

1. Compiled Pages and `lumio.yaml` remain canonical. Graphs, communities, reports,
   and vectors are derived. Unlike disposable search indexes, cited report bytes
   must be retained: regenerating model prose cannot reproduce a historical
   citation. New generation never replaces exact report readback.
2. Every Reader retrieval operation binds one exact Published Version and one
   authorized visible-set identity. Candidate review operations retain their
   exact Authoring Revision where applicable. Mutable latest state never
   replaces either binding.
3. Authorization applies before lookup, community detection, report generation,
   vector construction, graph expansion, ranking, counts, snippets, traces, and
   citations.
4. Graph Context and Extracted References are navigation, not Evidence.
5. Evidence and Citations continue to resolve to Compiled Pages. A Community
   Report is citable only through the new Evidence Bundle contract in §7.
6. Existing basic retrieval remains available without optional extras. A global
   request never silently becomes a local answer, and a semantic-resolution
   request never silently becomes an unsupported top-1 guess.
7. The selected host agent may propose understanding, follow-ups, and reports,
   but cannot widen visibility, change the bound version, bypass request budgets,
   create accepted Claims, or supply publication admission. Workspace and Core
   enforce their tools' structural/authorization checks, not semantic truth.
8. Every result discloses capability use, fallbacks, omissions, ambiguity, and
   artifact freshness through its existing or extended Retrieval Trace.

## 5. Bounded Agentic Query Planner

### 5.1 Query modes

The planner supports exactly four modes:

| Mode | Required behavior |
| --- | --- |
| `basic` | Retrieve citation-ready Evidence using the configured zero-index, BM25, semantic, or hybrid adapter. |
| `local` | Resolve Entity seeds, perform authorized bounded graph expansion, then rank Evidence from the eligible Compiled Pages. |
| `path` | Resolve path endpoints, perform bounded path discovery, then retrieve Evidence supporting the selected path and answer. |
| `global` | Rank Community Reports, inspect bounded report sections and their Evidence Bundles, then synthesize a corpus-level answer. |

Core accepts explicit mode/seed inputs and executes deterministic plan steps
without a model. Natural-language mode selection and structured
`QueryUnderstanding` come from the selected host agent; Core validates them and
rejects malformed or unauthorized fields. No deterministic natural-language
intent or entailment oracle is promised.

Pi is the first host route, extending the existing client/tool boundary. Local
SDK/CLI callers use the same deterministic operations with explicit parameters;
a supported host may orchestrate them locally. Installing the SDK alone does
not provide autonomous answering. Other hosts are supported only after their
model-policy, budget, citation, and tool journey is qualified. No model-provider
credentials or new answer loop are added to Workspace.

### 5.2 Query Plan

A Query Plan records at least:

- original question and selected mode;
- exact Published Version and visible-set identity;
- resolved Entity IDs, match kinds, scores, and ambiguity state;
- graph seeds, scope, direction, and depth where applicable;
- selected community IDs and exact report-set/artifact IDs for global mode;
- global coverage class and included/omitted member-page identities;
- request identity, iteration, consumed/reserved/remaining request-wide budget;
- used capabilities, fallbacks, omissions, and Retrieval Trace.

A Query Plan is a retrieval strategy, not Evidence, source access, query
execution authority, or publication approval.

### 5.3 Bounded refinement

One initial retrieval plus at most two refinement rounds is the default, not
an adequate cost bound by itself. Every request also receives the following
**approved first-release defaults**, applied across all rounds and global
map/reduce work, not reset per stage:

| Resource | Request-wide default limit |
| --- | --- |
| Host model calls, including classification, partial answers, reduction, and final synthesis | 6 |
| Cumulative model input/output | 24,000 input tokens / 6,000 output tokens |
| Knowledge-tool operations, including reads, graph steps, and follow-ups | 16 |
| Query-embedding requests | 6, at most 2,000 input tokens each |
| Selected Community Reports across all levels/rounds | 6 distinct reports |
| Member Evidence supplied to the host | 32 distinct units / 48,000 text characters cumulatively |
| Wall time from request start | 90 seconds |

Existing graph depth/edge/result limits remain additional per-operation bounds;
#103's existing per-call text cap is not widened. The operator can configure
limits and a caller may request lower limits, never higher effective ones.
Automatic retries and failed calls debit the same budgets. Preparation uses a
separate operator-approved job budget with explicit input, calls/tokens, and
deadline limits; a Reader request cannot trigger or borrow that job.

Core/Workspace own tool, Evidence, graph, and artifact accounting. The supported
host adapter owns model-call/token/deadline accounting for this request. It
reserves call input and maximum output before invocation, checks elapsed time
before each operation, and cancels or bounds in-flight work at the deadline;
unsupported accounting or cancellation must be reported as
`capability_unavailable`, not advertised as an enforced bounded agent. Existing
model usage/cost policy applies in addition. Client-supplied usage assertions
alone are not enforcement. The same request identity shares its counters on
retry/resume; a new request is a distinct user action, not an automatic reset.

A refinement may resolve an additional Entity, narrow or expand graph context,
reformulate retrieval, select another community, or fetch member Evidence. It
must preserve the original question's meaning and exact authorization/version
binding.

Planning stops with one explicit outcome:

- `sufficient` — the host found support for the bounded proposed answer and
  supplied matching Evidence/Bundles; this is not an SDK-certified truth label;
- `unsupported` — no support was established within the disclosed searched
  scope; it does not prove absence throughout the Knowledge Base;
- `needs_clarification` — an entity-critical ambiguity prevents a truthful plan;
- `capability_unavailable` — a required optional capability is not prepared;
- `budget_exhausted` — the configured bound ended before adequate support.

No-new-Evidence and no-new-graph-context rounds stop rather than loop. If support
remains unresolved, the result is `budget_exhausted` with a `no-progress` stop
reason, not a claim of corpus-wide absence. Before an operation exceeds any
remaining allowance, stop with `budget_exhausted` and report the binding limit;
do not launch it and hope later rounds stay small. A supported partial answer
may be returned only with its limited scope explicit, not as a complete answer.
Global mode returns `capability_unavailable` with preparation guidance when its
required artifact is missing; it does not silently answer from a few local
pages.

## 6. Graph Context Serializer

Core exposes a read-only Graph Context operation over stable Entity IDs, exact
Published Versions, authorized visible pages, and existing graph bounds.

A Graph Context contains:

- resolved seed Entities and page references;
- bounded nodes, edges, paths, and hop distances;
- accepted entity-to-entity Claims with Claim ID and Predicate;
- accepted literal Claims attached as node attributes when relevant;
- Claim Evidence anchors and corresponding Compiled Page Citations;
- Extracted References explicitly marked `navigation-only`;
- exact graph scope, direction, bounds, omissions, and freshness.

Disputed and superseded Claims do not enter ordinary Reader Graph Context.
Maintainer diagnostics may inspect them through existing explicit review
surfaces, not by silently adding them to Reader context.

Structured records are canonical for this derived view. JSON and human-readable
renderings serialize the same information; a renderer cannot upgrade an
Extracted Reference into semantic Claim wording.

Graph Context is not Evidence and cannot support an answer without the linked
Compiled Page Evidence.

## 7. Derived Communities and Global Search

### 7.1 Separate artifact families

The first release supports both:

- **canonical communities**, derived only from accepted Claims;
- **discovery communities**, derived from accepted Claims plus Extracted
  References.

The two families have separate community IDs, reports, caches, plans, and
traces. No operation merges them silently or describes an Extracted Reference
as an accepted relationship. Canonical is the default for citable report
preparation; discovery is an explicit broader-coverage selection.

Unconnected pages remain singleton or explicitly unclustered entries. Global
Search discloses whether those entries were searched; it never implies complete
corpus coverage after silently omitting them.

### 7.2 Operator-side preparation

A preparation operation binds:

- exact Published Version and visible-set identity;
- canonical or discovery graph scope;
- community algorithm identity and version;
- report generator/host/model identity and generation parameters affecting meaning;
- operator preparation request key and approved job budget;
- exact input manifest and output content digests.

Core performs hierarchical community detection and matches communities to the
previous preparation by membership overlap for stable IDs. The selected host
agent drafts reports from the exact authorized selection. Workspace or the
local operator path validates bundle structure and activates one complete
versioned report set; it does not generate report prose itself. Activation is
an operator-authorized derived-artifact action, not Publication Admission of
canonical content and not endorsement of report meaning. Partial sets never
activate.

An identical preparation request key and descriptor resume/reuse recorded
outputs. Once output bytes are accepted for that request, retries do not
regenerate them. An explicit regeneration uses a new request key even when the
other settings match, producing a new report set without overwriting prior
citations. Generator identity alone is not a claim of reproducible prose.

The community algorithm is an optional extra. Report generation uses the host's
explicitly permitted model, without a new Workspace model client or runtime.
The model-free base can load and validate previously prepared artifacts.

### 7.3 Community Reports and Evidence Bundles

A Community Report is a derived aggregate artifact, not a canonical Synthetic
Page and not raw-source Claim lineage. Each citable report section has an
Evidence Bundle containing:

- the Community Report Citation, including exact community/report/section and
  artifact identity;
- one or more exact Compiled Page Evidence references offered as that section's
  supporting material;
- `generated-unverified` status, generation origin, and coverage/omissions.

Activation validates required references, exact version/visible-set binding,
section identity, digests, and boundedness. Missing/mismatched references reject
the entire set; sections are not silently dropped to force success. These
checks do **not** establish that prose follows from the referenced passages.
Reports remain generated, unverified synthesis, labeled as such in every read
and retrieval result. There is no new entailment oracle or human report-review
lifecycle.

Before using a report statement, the host must read the referenced member
passages and check the proposed answer's meaning, attribution, exceptions, and
scope against them. It must omit unsupported statements or refuse/narrow the
answer. For example, “Alex proposed 30-day retention” cannot support “the company
adopted 30-day retention,” even when the report makes that assertion and all
anchors resolve. Generation and answer-time checks by a model are not
independent proof of truth; a small independently annotated host evaluation
checks this specific failure without claiming universal entailment.

An answer using a report section must cite both that exact section and the
member Evidence supporting each used assertion, and retain the generated status.
Core/Workspace can reject report-only or mismatched citations; they cannot
certify semantic support merely from their presence. The report remains
citable as synthesis, never as self-supporting domain truth.

Raw Source Artifacts, private source coordinates, and unadmitted candidates do
not enter reports or Evidence Bundles.

### 7.4 Global Search

Global Search:

1. ranks relevant Community Reports for the question;
2. selects a bounded set of communities and report sections;
3. inspects their Evidence Bundles and retrieves the exact member Evidence;
4. synthesizes per-community partial answers using only authorized material;
5. reduces those partial answers into one cited aggregate answer;
6. cites report sections and supporting Compiled Page Evidence together.

The first release provides **exploratory thematic synthesis**, not exhaustive
corpus aggregation. The plan/result reports the authorized page count and the
included/omitted report and distinct member-page sets, including singleton or
unclustered coverage. Disclosure describes what was inspected; it does not
license universal conclusions from a ranked sample.

Questions requiring “all,” “none,” exact corpus counts, “most common,” or a
complete ranking cannot be answered from selected Community Reports. The host
must offer a clearly narrower thematic answer or refuse the exhaustive claim.
An admitted passage explicitly stating a domain-wide rule may still support
that rule; this prohibition concerns unsupported corpus-coverage/aggregation
claims. No new exhaustive aggregation engine is introduced by this revision.

Parent and child reports are overlapping views. Count each member page and
Evidence identity once in coverage and budget accounting, preserve canonical
and discovery scope separation, and never treat repeated summaries or citations
as independent corroboration or additive incident counts. The host prefers a
non-overlapping frontier and discloses any necessary overlap. Insufficient
support produces an appropriately scoped stop/follow-up under §5.3.

### 7.5 Exact report readback, selection, and retention

Every activated report set has an immutable ID/digest binding the Knowledge
Base Namespace, Published Version, visible-set identity, graph scope, input
manifest, algorithm, generator, and exact report/bundle bytes. Community IDs
alone never identify a citation. A new query resolves the operator-selected
active report-set ID for that exact tuple once, then pins it for all rounds.
A later preparation cannot change that request's report selection.

Core exposes exact report/section readback; Workspace exposes the same bounded,
authorized operation through its existing read-only tool boundary. Inputs name
the report-set ID, report ID, section ID, and optional read bounds. Outputs
carry those identities, stored generated prose/status, digest, exact member
Evidence references, and omissions. Reads verify identity/digests and recheck
current authorization; an old citation grants no access. Reopening a citation
selects its stored artifact, not the currently active report set.

Store report sets in the configured derived-artifact location outside immutable
Published Version trees. Activation conditionally changes the separate active
report-set pointer only after a complete set validates, preserving prior state
on handled failure. It neither mutates canonical publication nor claims a new
cross-store atomicity guarantee. Local and managed paths use the same identity
and readback contract; no new canonical content registry is introduced.

Activated report bytes, bundles, and selection metadata are included in the
existing configured backup/restore scope and retained by default until explicit
operator deletion. Ordinary disposable-index cleanup must not remove them. An
explicit deletion previews affected report citations, removes active selection
as needed, and returns a truthful `artifact_unavailable` on later authorized
readback. It does not delete Compiled Pages or authorize regeneration under the
old ID. Restore verifies digests and restores exact bytes; a missing historical
artifact remains unavailable rather than being regenerated or rebound.

## 8. Conservative Semantic Entity Resolution

### 8.1 Resolution ladder

Resolution uses:

1. exact unique Entity ID, Canonical Page Title, or Alias;
2. existing lexical FTS candidates;
3. optional semantic vector candidates through `lumio-lancedb`.

**Corpus vectors and indexes** are prepared operator-side over the authorized
visible set. A Reader request never rebuilds them or includes hidden pages in
vector statistics. Missing corpus vectors produce an explicit unavailable
capability, not a fake empty candidate set.

**Query vectors** are computed for new question/entity text at request time.
The explicitly configured host/local embedding adapter, or an owner-authorized
remote embedding provider, may embed that text under current processing policy
and §5.3's request budget. Provider failure or denied query processing is
`capability_unavailable`, not an empty result. No provider is enabled by default;
no credentials come from model output. Corpus content is not uploaded merely
to embed a query.

Core/LanceDB validate query-vector dimension and embedding identity against the
prepared index, including the document/query encoding roles and preprocessing
contract for that model. A mismatched model refuses semantic resolution rather
than comparing incompatible vectors or rebuilding on demand. Query vectors may
be supplied through the existing Embedder/caller boundary; this needs no
Workspace agent runtime. Matching and scoring remain deterministic after
encoding.

### 8.2 Automatic seeding and ambiguity

- Exact unique matches resolve directly.
- FTS candidates alone never auto-seed by rank; they inform candidate review,
  clarification, or the subsequent semantic-resolution step.
- Semantic seeding requires both a configured score threshold and a configured
  margin over the runner-up.
- Entity-critical local/path queries return `needs_clarification` when those
  conditions are not met.
- When an Entity is incidental, basic retrieval may proceed with the unresolved
  Entity disclosed rather than forcing graph expansion.
- Every candidate and rejected ambiguity is traced with match kind, scores,
  thresholds, and fallback.
- No resolution merges Entities, mutates Claims, publishes content, or grants
  access to another Entity.

Thresholds are operator configuration recorded in the plan and evaluation; no
universal threshold is asserted by this specification.

### 8.3 Adoption evaluation

Semantic resolution is compared with exact/alias/FTS behavior on independently
authored aliases, paraphrases, similar names, ambiguous questions, negative
queries, and hidden Entities. Evaluation reports wrong automatic resolution,
correct ambiguity refusal, candidate recall, coverage, latency, and cost.

The existing Zero-Index/BM25 evaluation informs the decision. Semantic adoption
requires an independently reviewed benefit without an unacceptable wrong-seed
or disclosure regression; deterministic embedding fixtures prove mechanics,
not production semantic quality.

## 9. Failure, freshness, and retry behavior

- A Community Report whose artifact identity does not match the requested
  Published Version, visible set, graph scope, algorithm, or generator contract
  is not Evidence for that request. An exactly bound historical report remains
  valid for historical queries while retained.
- A historical Published Version never consumes reports generated from a newer
  one. Unavailable exact report readback returns `artifact_unavailable`; global
  planning maps a missing required set to `capability_unavailable`, never to a
  report from another publication or generation.
- Visibility-specific communities, reports, vectors, and caches are separate.
  Hidden pages cannot influence membership, labels, statistics, counts, traces,
  omissions, or citations.
- Model structures that are malformed, exceed bounds, reference unknown
  Entities, or have missing/mismatched Evidence bindings are rejected.
  Semantically unsupported report prose is not guaranteed to fail structural
  activation; it remains unverified and must not be repeated as truth.
- Missing optional capabilities name the preparation/install action. Existing
  basic behavior continues unchanged where that does not alter the requested
  mode's meaning.
- Preparation keys preserve recorded report bytes. Planning retries preserve
  pinned inputs and spent budgets but do not promise identical new model prose;
  neither operation silently resets counters or replaces citation targets.

## 10. Compatibility and migration

Existing Compiled Pages, Claims, Source Versions, Published Versions, Evidence,
and Citations remain valid. The change adds derived records and operations; it
does not require a canonical Markdown migration or automatic community build.

Existing `KnowledgeBase.retrieve` behavior remains available. New planned
results carry Query Plan and optional Graph Context alongside existing
citation-ready Evidence rather than redefining existing results as graph truth.

Community Report Citation is an additive aggregate citation form. Existing page
citations remain unchanged. Evidence Bundle requirements apply only to the new
Community Report capability, not retroactively to ordinary Evidence.

Base `lumio-wiki` remains model-free and cloud-free. Optional community and
embedding capabilities load lazily and produce actionable `doctor`/error
guidance. The selected host supplies report drafting and answer synthesis; no
new LLM extra is required for this path, and the existing optional unattended
Distiller is unchanged. `lumio-lancedb` remains the only enhanced persisted
Entity/Claim projection; traversal remains bounded and in memory.

No existing GitHub issue body is rewritten by this specification. Later planning
and ticket updates must preserve the dependencies and tracker boundaries in §2.

## 11. Observable acceptance criteria

| ID | Independently authored scenario and required outcome |
| --- | --- |
| AC1 | Explicit basic/local/path/global inputs and validated host interpretations produce the expected plans naming exact publication, visible set, bounds, stable Entity IDs, and pinned report-set IDs. Model-free use makes no natural-language classification claim. |
| AC2 | An initial local retrieval misses a known supporting page; one refinement finds it. A subsequent refinement yielding no new Evidence stops with a truthful outcome rather than looping. |
| AC3 | A global question without prepared reports returns `capability_unavailable` and preparation guidance; it does not return a local-only answer. |
| AC4 | Graph Context renders an accepted `operated-by` Claim with its Claim ID and Evidence anchors, while a body link remains explicitly navigation-only. Disputed/superseded Claims are absent from ordinary Reader context. |
| AC5 | Structured and human-readable Graph Context contain the same nodes, edges, scope, omissions, and citations. |
| AC6 | Canonical and discovery preparations over one authored graph produce separate artifacts. A discovery-only connection never appears as an accepted Claim in either artifact. |
| AC7 | Unconnected pages remain disclosed singleton/unclustered entries. Selected parent/child reports share a page; coverage counts it once, with included/omitted sets and any overlap disclosed. |
| AC8 | Two authored communities support an exploratory thematic answer. It cites exact report sections and independently expected member passages, retaining the generated-unverified report status rather than claiming exhaustive coverage. |
| AC9 | A missing/mismatched bundle or cross-version anchor rejects the whole report set. A structurally valid report falsely turns an authored proposal into adopted policy: activation labels it unverified, and the host must check the passage and omit/correct/refuse that assertion. Structural fixtures do not stand in for the separate real-host semantic example. |
| AC10 | Report-only citations and mismatched member references fail deterministic validation. A citation-bearing answer is not labeled semantically verified solely because those checks pass. |
| AC11 | A restricted marker cannot affect an unauthorized Reader's community membership, report text, entity vectors, counts, snippets, traces, omissions, or citations. |
| AC12 | For one publication, activate report set A then B. An in-flight request/citation pinned to A reads A's exact stored section, not B; neither can bind to a different publication or visible set. |
| AC13 | An identical preparation key resumes/reuses recorded output; explicit regeneration gets a new key/set even with the same model/settings. Handled activation failure leaves the previous selection usable. |
| AC14 | Exact alias resolution wins. A paraphrase resolves only above both configured thresholds, and two close Entities cause clarification for an entity-critical query. No candidate merges or publishes anything. |
| AC15 | A hidden Entity cannot be returned as a candidate or influence semantic candidates, scores, thresholds, traces, or fallback disclosures. Missing semantic capability is distinguished from zero candidates. |
| AC16 | The base wheel imports and performs existing basic/local/path operations without community or LLM extras. Optional capabilities fail with actionable guidance, not import-time failure. |
| AC17 | A previously unseen paraphrase invokes the configured compatible query encoder without rebuilding corpus vectors. Denied/mismatched encoding reports unavailable. Independent evaluation distinguishes wrong automatic resolution, correct ambiguity refusal, and negatives against exact/alias/FTS; deterministic embeddings prove mechanics only. |
| AC18 | Existing page-only retrieval and citations behave unchanged when no optional capability is selected. No raw source, unadmitted candidate, or graph edge becomes Evidence. |
| AC19 | Host classification, global map/reduce, query embedding, tool calls, retries, and refinements share one budget. Excess fan-out is refused before launch; deadline/cost exhaustion stops truthfully, and resume cannot reset counters. A host unable to enforce its part is unavailable for bounded agentic mode. |
| AC20 | A ranked sample suggests deployment errors, while omitted authored pages contain more authentication incidents. “Most common cause” is refused or explicitly narrowed to selected themes; parent/child repetitions cannot inflate counts. |
| AC21 | Backup/restore preserves exact report bytes and bundle IDs. Disposable-index cleanup preserves them; explicit authorized deletion previews affected citations and later exact read returns unavailable without regeneration. |
| AC22 | The supported Pi host performs model understanding, report drafting, and synthesis through authorized tools without adding a server agent runtime. The local SDK/CLI route executes explicit plans and exact readback without Workspace; host semantic/budget qualification is reported separately from structural checks. |

## 12. Capture and planning handoff

- **Vocabulary:** Query Plan, Graph Context, Community, Community Report,
  Evidence Bundle, Global Search, and Semantic Entity Resolution are captured in
  `products/lumio/CONTEXT.md`; Evidence and Citation are scoped to include the
  new aggregate form.
- **Decision:** ADR-0033 records the durable ownership, planner, derived
  community, Evidence Bundle, packaging, and conservative-resolution choices.
- **Behavior:** this approved revision owns scope, interfaces, failures, and
  AC1–AC22, including the six review corrections. ADR-0033 and the glossary are
  reconciled to the host-agent and unverified-synthesis owner selections.
- **Approval/qualification:** the request-wide numerical defaults, first-release
  exploratory-only global conclusions, and exact report-retention contract are
  covered by written revision-2 approval. Algorithm/library selection belongs
  to planning.
  Actual host budget enforcement, model-policy behavior, and semantic examples
  require qualification; unproven support is not a completed capability. No
  universal entailment or semantic-quality claim is made.
- **Next gate:** the owner-approved [plan0012](../plans/2026-11-11-0012-agentic-graph-retrieval.md)
  maps this behavior to its four canonical feature issues and epic-owned final
  verification. Ticket publication is authorized; cross-references do not change
  §2's existing approved task bodies or dependencies. Execution, integration,
  and publication of product artifacts require separate authority.
