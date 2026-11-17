# Mercury memory lessons for Lumio

_Date: 2026-11-11. Scope: architectural research only; no decision,
implementation commitment, or execution authority._

## Research question

How does Mercury Agent's memory subsystem work, which of its features are
actually distinctive, and which patterns could improve Lumio without weakening
its portable, source-backed, human-admitted Knowledge Base?

## Evidence baseline

Mercury was inspected from a clean shallow checkout at commit
[`b6fcd5cee608412dd5b80e78f98654b88a393fd1`][mercury-commit].
The analysis covers `src/memory`, its learning loops in `src/learning`, and the
agent read/write wiring needed to establish real use. Comments referencing
`docs/owner-model.md` point to a file absent at this commit, so behavioral
claims below come from code rather than that missing document. Tests and
performance benchmarks were not run; this is source analysis, not a quality or
recall evaluation.

The Lumio baseline is monorepo commit
`d2f8b75c0970267b42b0d04f5359ae603b7998a9`, with no local modifications in
`products/lumio/packages/lumio-wiki/src` or
`products/lumio/packages/lumio-lancedb/src`. Accepted ADRs and specifications
remain authoritative over every candidate idea in this note.

## Executive finding

Mercury and Lumio solve different problems:

- **Mercury** continuously learns a single owner's preferences, traits,
  relationships, and episodes, then injects the useful ones into later prompts.
- **Lumio** compiles team knowledge into portable, cited Markdown and admits
  changes through explicit review.

Mercury's strongest idea is therefore not “use SQLite for memory” or “copy its
belief lifecycle.” It is **making the evidence and state transitions of learned
knowledge explicit**. Its two-speed learning loop, confidence decay, people
standing, and deterministic thematic map are also distinctive. Only some of
those semantics transfer safely.

The best immediate Lumio candidate is **trust-aware retrieval and review
ranking**. The best longer-term candidate is **corroboration-aware review of
candidate semantics**, without automatic acceptance. Mercury's thematic-map
stability is a useful derived-navigation pattern. Automatic capture, automatic
promotion, implicit support from non-objection, and age-based truth decay should
not be adopted.

## How Mercury works

### Storage and active model

Mercury has four storage tiers below `~/.mercury/memory`:

1. Per-conversation short-term JSON, capped by message count.
2. Append-only long-term `facts.jsonl`, with simple substring search.
3. Append-only episodic `events.jsonl`, pruned by age except for events marked
   important.
4. A SQLite Second Brain in WAL mode containing the active belief model, FTS5,
   evidence, person graph, curation state, and legacy memory archive.

The first three are simple stores ([`store.ts`][mercury-store]). The Second
Brain is the substantive system ([schema][mercury-db-schema]). `BeliefStore`
owns `beliefs`, `beliefs_fts`, `belief_evidence`, and metadata
([`beliefs.ts`][mercury-belief-schema]). `UserMemoryStore` is mostly a
compatibility facade over that store; the old `memories` table remains for
history, quarantine, and person-graph support rather than new belief writes.

### Write path: two learning speeds plus owner control

```text
owner turn + deterministic behavioral signals + relevant existing beliefs
    -> bounded model extraction -> validated belief operations
    -> candidate / support / contradiction / correction

new owner turns across sessions + computed statistics + current beliefs
    -> slower reflection pass -> support / merge / contest / correction / brief

explicit save, edit, confirm, correct, forget, restore
    -> privileged owner operations
```

The per-turn extractor is bounded to a small operation list and strict JSON;
ordinary turns should return no operations ([extractor][mercury-extract]).
The slower reflection pass works across sessions and is the only writer of the
owner brief ([reflection][mercury-reflection]). Model output is validated, and
cheap behavioral signals are computed in code rather than inferred entirely by
the model.

### Belief state and retrieval

A belief has kind, statement, context, timescale, support and counter-evidence,
distinct supporting-session count, status, owner-stated state, validity bounds,
supersession, timestamps, and sharing state. Evidence rows retain an excerpt,
session/turn reference, kind, weight, and time.

The important transitions are:

- inferred claims start as `candidate`;
- support from two distinct sessions makes a candidate `held`;
- owner statements and edits become `confirmed`;
- contradictions can make beliefs `contested` or `retired`;
- correction creates a confirmed replacement and supersedes the old belief;
- forgetting and retirement hide beliefs from ordinary prompt use while keeping
  history (explicit “clear all” is a separate destructive operation).

Confidence is a Beta-mean of support and counter-evidence, multiplied by a
half-life decay unless owner-stated or confirmed
([confidence and operations][mercury-belief-ops]). Retirement additionally
requires contradiction or extended staleness, not merely a low score
([decay][mercury-decay]).

Retrieval uses BM25 over statement and detail. It takes held/confirmed beliefs
first and backfills with candidates, then applies the confidence floor
([retrieval][mercury-retrieval]). The agent labels candidates as unverified.
Retrieval records `last_used`; acting on an injected belief without an owner
objection adds weak supporting evidence ([use feedback][mercury-use-feedback]).
That last rule is a product heuristic, not independent factual evidence.

### Derived person and thematic views

Mercury builds two additional views over beliefs:

- A person graph with alias handling, human curation, optional batched model
  checks, and `known` / `shadow` / `faint` standing. Frequency alone cannot make
  someone known: a relationship or verified tie is also required. A soft cap
  raises the bar for weak entries rather than imposing a hard person limit
  ([standing][mercury-standing], [verifier][mercury-verifier]).
- A local knowledge map with no model calls or embeddings: BM25-like term
  vectors, sparse cosine kNN links, deterministic Louvain communities,
  c-TF-IDF labels, subthemes, and stable theme IDs matched across rebuilds by
  membership overlap ([map pipeline][mercury-map], [map assembly][mercury-map-ids]).

## What is genuinely distinctive

These are distinctive in this implementation, not claims of global novelty:

1. **Beliefs as evidence-bearing state machines.** Mercury does not merely save
   text; it records why a claim is held, contested, corrected, or superseded.
2. **Corroboration across sessions, not just repetitions.** Distinct-session
   support is more meaningful than counting repeated tokens in one interaction.
3. **Fast extraction plus slow reflection.** Immediate learning and cross-session
   consolidation have different costs and responsibilities.
4. **Different trust tiers in retrieval.** Held/confirmed results are preferred,
   while new candidates remain available but visibly unverified.
5. **Context- and timescale-aware confidence.** A situational preference and a
   stable relationship do not fade on the same schedule.
6. **Standing requires connection, not only occurrence.** The person graph keeps
   frequent-but-unconnected names out of the primary view.
7. **Stable, sparse, model-free thematic organization.** The knowledge map is
   designed for navigation rather than a graph “hairball,” and stable theme IDs
   prevent gratuitous UI churn.
8. **Quarantine and reversible migration.** Suspicious legacy rows are parked
   for review, with a backup and restore path, rather than silently promoted or
   deleted ([migration][mercury-migration]).
9. **Explicit privacy controls.** Secret-like candidates are rejected and cloud
   sharing is opt-in per belief ([remember][mercury-remember]).

## Limits that matter for comparison

- Retrieval is lexical BM25, not semantic retrieval.
- The Second Brain is effectively a single-owner model.
- Short-/long-/episodic JSON stores are much simpler than, and largely
  peripheral to, the active belief subsystem.
- Person extraction is English- and regex-heavy, with hard-coded vocabulary.
- Confidence and standing are heuristics, not calibrated truth measurements.
- A stale, uncontradicted candidate can remain indefinitely.
- The analysis found no evidence that Mercury's learning or ranking improves
  factual correctness on a team corpus; no benchmark was run here.

## Lumio already has the relevant foundation

Mercury should not cause Lumio to rediscover existing contracts:

- Compiled Pages and `lumio.yaml`, not SQLite, are canonical knowledge.
- Claims already have stable IDs, Evidence anchors, accepted/disputed/superseded
  lifecycle, optional confidence, origin, and valid-time metadata
  ([ADR-0021](../adr/0021-entity-claim-ontology-and-progressive-graph-materialization.md)).
- Accepted Claims and Extracted References have deliberately different trust.
- Entity merges, content changes, and Publication Admission are reviewed.
- Source Versions, Source Drift, source coverage, and page-level invalidation
  already address source change without claiming raw-source Claim lineage
  ([ADR-0014](../adr/0014-source-versions-and-page-level-invalidation.md)).
- The Dream Cycle already covers validation, graph health, missing-link impact,
  review-due pages, duplicate candidates, synthesis candidates, source drift,
  and bounded transitive impact (`maintenance.py`).
- Semantic Dream findings are bounded, strictly parsed, and reviewable
  (`semantic_maintenance.py`).
- `review_after` supports freshness review; Retrieval Traces support inspection.
- Zero-index lexical plus optional semantic/hybrid retrieval already exists.
- On-request enrichment explicitly rejects automatic semantic publication and
  independent-source consensus in its first implementation
  ([ADR-0032](../adr/0032-document-first-progressive-enrichment.md),
  [specification 0003](../specs/0003-model-assisted-extraction.md)).

## Candidate lessons for Lumio

| Priority | Candidate | Adaptation for Lumio | Main boundary |
| --- | --- | --- | --- |
| 1 | Trust-aware retrieval | Prefer approved knowledge within comparable relevance results and disclose lifecycle; keep lower-trust results available when relevant | Lifecycle is a publication signal, not proof of truth; visibility filtering stays separate and mandatory |
| 2 | Volatility-aware review | Use timescale/volatility hints to propose `review_after` and prioritize Dream reviews | Age schedules review, never automatic falsity, retirement, or loss of Evidence |
| 3 | Corroboration-aware candidate review | Aggregate support and conflict for repeated candidate semantics across independent Source Versions/pages/reviews | No “two sources therefore accepted”; independent-source consensus remains deferred and admission stays human |
| 4 | Stable derived thematic map | Add a rebuildable, sparse theme view for navigation and Dream triage; carry theme IDs across rebuilds | Similarity edges are discovery only, never Claims or automatic authored links |
| 5 | Explicit usage feedback | Use citation opens and explicit useful/not-useful feedback to prioritize navigation and maintenance in the host | Never convert non-objection into support; telemetry stays outside canonical KB content |
| 6 | Evidence-based entity salience | Rank review/navigation candidates using accepted ties, human review, and source diversity rather than raw mention count | Do not copy person regexes, relationship cardinality, or a Dunbar cap into a generic team KB |

### 1. Trust-aware retrieval — best small candidate

Mercury's held/confirmed-first, candidate-backfill retrieval is directly
relevant to Lumio because page Lifecycle exists but the zero-index ranker
currently scores lexical/title matches without using it (`retrieval.py`).

A Lumio-safe version would:

- preserve authorization and eligible-page selection before ranking;
- keep lexical/semantic relevance central rather than letting lifecycle hide
  the best passage;
- prefer `approved` over `review`/`draft` within comparable relevance bands;
- make any lifecycle adjustment visible in Retrieval Trace and result metadata;
- treat `deprecated` as a disclosed ranking signal, not as automatic deletion or
  proof that a historical answer is invalid.

This is smaller and more immediately useful than introducing a new belief
store. It needs independently authored ranking examples before implementation;
no numerical boost should be copied from Mercury.

### 2. Convert decay into review pressure, not truth loss

Mercury's timescales suggest a useful distinction between stable decisions,
changing operational ownership, and short-lived situational notes. Lumio already
has the correct safer mechanism: `review_after` plus Dream Cycle due pages.

A future maintenance pass could recommend review dates from explicit page or
Claim volatility metadata. It must not reduce confidence merely because time
passed. Old runbooks can remain correct, and a frequently used page is not
thereby true. Source Drift, valid-time bounds, and human deprecation retain
their separate meanings.

### 3. Accumulate corroboration for review, not auto-acceptance

Mercury's support/against ledger and distinct-session promotion are useful
reminders that one model observation is weak. Lumio's candidate enrichment could
eventually show:

- the candidate's stable identity;
- exact supporting passages and Source Versions;
- conflicting passages and their attribution;
- first/last observed review;
- independent evidence lineages, with dependent copies collapsed;
- whether a finding is new, repeated, changed, or resolved.

This would improve reviewer prioritization and prevent repeated rediscovery of
the same questionable suggestion. It should be review/derived state, not a new
published `candidate` Claim tier. ADR-0032 explicitly says that model agreement
is not an independent truth check, and specification 0003 defers
independent-source consensus. The safe near-term lesson is evidence bookkeeping,
not Mercury's automatic candidate-to-held transition.

### 4. Stable thematic navigation — promising exploratory feature

Lumio's graph diagnostics and link candidates already identify structural
problems. A Mercury-inspired map would serve a different purpose: summarizing
what broad themes exist and where a page belongs.

The valuable parts are:

- sparse links rather than all pairwise similarity;
- disconnected “loose notes” kept visible instead of forced into a theme;
- deterministic labels and ordering;
- stable theme identity across rebuilds.

The map should be disposable and fingerprint-bound like Lumio's other derived
artifacts. It should not create Extracted References, accepted Claims, or new
canonical categories. A hand-written Louvain implementation is not justified
without a real navigation problem at meaningful KB scale; the first probe
should reuse existing graph and retrieval primitives.

### 5. Usage and standing are feedback, not Evidence

Mercury's `last_used`, `actedOnOk`, and person standing all try to separate
primary knowledge from peripheral material. Lumio could use explicit Reader
feedback and citation interaction to suggest Hot Index pins or Dream review
priorities. `CONTEXT.md` currently keeps the Hot Index curated and defers
citation/access-frequency ranking, so this is a host-side future enhancement,
not a base-package requirement.

The general standing rule is also useful: accepted relationships and human
review should outweigh raw mentions. But usage, salience, and retrieval quality
must remain separate from factual support. “No one objected” is especially not
evidence for a team Claim.

## Patterns not recommended

- **SQLite as canonical knowledge:** conflicts with ADR-0021 and buys no needed
  capability by itself.
- **Automatic per-turn ingestion:** conflicts with consent-only Capture and the
  approved on-request enrichment boundary.
- **Automatic candidate promotion or owner-style confirmation:** Lumio requires
  exact reviewed Publication Admission.
- **Half-life truth decay and automatic retirement:** use review pressure,
  Source Drift, valid-time metadata, and explicit lifecycle changes instead.
- **Support from acting without objection:** useful product telemetry at most,
  never Claim Evidence.
- **Person-specific extraction and social caps:** too narrow and brittle for a
  generic team Knowledge Base.
- **Free-form context strings everywhere:** Lumio should first use its existing
  Namespace, Visibility, valid-time, and Context Binding vocabulary; any new
  applicability scope needs a controlled contract.
- **Copying Mercury's legacy JSON/JSONL tiers:** they are not its strongest or
  most active design.

## Recommended next decision

If only one idea is explored, shape **trust-aware retrieval ranking** as a small
behavioral specification with independently derived examples. Keep
volatility-aware review and corroboration-aware review as separate later
candidates. Do not start a broad “Mercury memory for Lumio” implementation.

Planning Contract version 1 was loaded for this research classification.
Installed contract provenance: locally authored catalog revision `unknown`.
This note supplies evidence only; any behavior change requires its own approved
specification/design and execution authority.

## Primary Mercury sources

- [Pinned Mercury commit][mercury-commit]
- [Legacy short-/long-/episodic stores][mercury-store]
- [Second Brain schema and WAL setup][mercury-db-schema]
- [Belief/evidence schema][mercury-belief-schema]
- [Confidence, state transitions, correction, and use feedback][mercury-belief-ops]
- [Decay pass][mercury-decay]
- [Held-first retrieval with candidate backfill][mercury-retrieval]
- [Per-turn extractor][mercury-extract]
- [Cross-session reflection][mercury-reflection]
- [Agent prompt injection and acted-on support][mercury-agent]
- [Person standing][mercury-standing]
- [Batched person verification][mercury-verifier]
- [Knowledge-map algorithm][mercury-map]
- [Knowledge-map assembly and stable IDs][mercury-map-ids]
- [Legacy migration and quarantine][mercury-migration]
- [Explicit remember/share controls][mercury-remember]

[mercury-commit]: https://github.com/cosmicstack-labs/mercury-agent/tree/b6fcd5cee608412dd5b80e78f98654b88a393fd1
[mercury-store]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/store.ts#L64-L223
[mercury-db-schema]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/second-brain-db.ts#L121-L305
[mercury-belief-schema]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/beliefs.ts#L145-L201
[mercury-belief-ops]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/beliefs.ts#L207-L329
[mercury-decay]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/beliefs.ts#L332-L343
[mercury-retrieval]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/beliefs.ts#L379-L400
[mercury-extract]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/learning/extract.ts#L1-L28
[mercury-reflection]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/learning/reflection.ts#L1-L14
[mercury-agent]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/core/agent.ts#L3475-L3500
[mercury-standing]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/person-standing.ts#L53-L113
[mercury-verifier]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/person-verifier.ts#L1-L120
[mercury-map]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/knowledge-map.ts#L1-L27
[mercury-map-ids]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/knowledge-map.ts#L371-L473
[mercury-migration]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/beliefs.ts#L640-L702
[mercury-remember]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/user-memory.ts#L381-L435
[mercury-use-feedback]: https://github.com/cosmicstack-labs/mercury-agent/blob/b6fcd5cee608412dd5b80e78f98654b88a393fd1/src/memory/beliefs.ts#L315-L329
