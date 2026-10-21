# Anthropic self-service analytics: implications for Ariadne

Research evidence, 2026-10-06. Recommendations below are proposals, not approved behavior or implementation authority. Planning-contract v1; installed skill provenance unknown.

## Source and assessment boundary

Primary source: Anthropic, [How Anthropic enables self-service data analytics with Claude](https://claude.com/blog/how-anthropic-enables-self-service-data-analytics-with-claude), displayed publication date June 3, 2026; read on October 6, 2026, including its skill appendix. An immutable web capture is retained as wiki source `SRC-2026-10-06-001`.

Compared against checkout `ab8c037` and its current local documents. In particular, [Context trust specification 0011](../specs/2026-10-06-0011-context-trust-signals.md) is an owner-approved design with written-specification review pending, not implemented behavior. Existing unrelated local changes were left untouched. This is a focused architecture/product comparison, not a runtime test or live-data accuracy audit.

Anthropic reports approximately 95% automation and aggregate accuracy, a skills-associated rise from at most 21% to above 95%, maintenance-related deterioration from approximately 95% to 65% over a month, and an adversarial-review gain of 6% with 32% more tokens and 72% higher latency. These are first-party internal results, not reproducible guarantees for Ariadne; the article does not supply its full benchmark, grader or sample distribution. Its workflow principles are more transferable than its percentages.

## Conclusion

The article validates Ariadne's direction rather than suggesting a new semantic engine. Its three dominant failure modes—concept/entity ambiguity, staleness, and retrieval failure—map directly to Ariadne's Semantic Layer, Context Layer, and packaged workflow guidance. The most valuable next work is measuring the complete question-to-answer path, finishing the already-shaped advisory Context signals, and exposing actual data recency separately from document expiry.

A deterministic compiler answers the selected definition consistently. It cannot establish that the selected definition answers the user's intended question, that the source is complete, or that the conversational answer faithfully describes the result.

## Principles to preserve

### Canonical definitions first; humans own business meaning

The article's semantic-layer section reports that automatically generating metric definitions from raw tables and historical SQL was worse than a smaller human-curated layer. Ariadne's AI-assisted authoring is compatible with that lesson only because generated definitions remain proposals until exact-revision human review. Neither measured distributions nor compile success establish business meaning.

Ariadne already instructs agents to discover governed metrics first and label ad-hoc definitions `governed: false`; its runtime compiles definitions, checks joins and executes read-only. Preserve human source approval and Promotion/Git Review Admission. Do not copy the appendix's raw-SQL fallback on compile failure: an Ariadne admission, compile or audit failure is not permission to evade the gate. Genuine uncovered questions retain the existing validated ad-hoc route.

Sources: [packaged skill](../../src/ariadne/skill_assets/SKILL.md), [Query runtime](../../src/ariadne/query.py), [vocabulary](../../CONTEXT.md), [modular-core/Git ADR](../adr/0016-modular-core-git-authoring.md).

### Business context accompanies numbers; it never becomes an alternative calculator

Anthropic distinguishes declarative domain knowledge from procedural skills. Ariadne already follows that separation: OSI calculates; OKF Policies and References explain meaning; the packaged skill describes workflow. Full cited Policy text travels with governed results, a stronger mechanism than expecting an agent to remember to search every caveat.

Preserve the distinction between definition admission, Document Verification, Execution Attestation and Independent Numerical Validation. A human-reviewed definition or stored test reference does not prove that today's number is complete, independently checked, or correctly narrated.

Sources: [Context implementation](../../src/ariadne/context.py) (`metric_context`), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md), [specification 0011](../specs/2026-10-06-0011-context-trust-signals.md), [CONTEXT.md](../../CONTEXT.md).

### Keep the existing grain and execution protections

The article says SQL becomes trivial once the right entities are resolved. That is an emphasis, not a reason to remove Ariadne's deterministic safeguards. Correctly named entities can still create fact fan-out, wrong denominators or mismatched time grains. Keep fact-local aggregation, reviewed conformed dimensions and required live relationship audits.

Sources: [multi-fact specification](../specs/2026-09-30-0008-multi-fact-planner.md), [Query runtime](../../src/ariadne/query.py) (`get_metric`, `query_metrics`), [independent numerical and fan-out checks](../../tests/test_evals.py).

## Recommended additions, in priority order

### 1. Expand evaluation from compiler correctness to business-answer correctness

**Existing foothold:** [golden.json](../../tests/evals/golden.json) has seven entries, [context_retrieval.json](../../tests/evals/context_retrieval.json) has five retrieval cases, and the [agent-trace specification](../specs/2026-09-23-0003-agent-answer-trace-evaluation.md) establishes two actual-Pi question scenarios. Numerical oracles, retrieval checks and observed routing/caveat evidence already exist. They are not a broad current-agent/domain accuracy benchmark; passing a recorded trace cannot establish current-agent performance.

**Smallest useful addition:** a compact owner-curated question set for the first real domain, extending the existing harness rather than creating an evaluation service. Include common approved KPIs and the actual wrong-answer modes:

- Ambiguous terms requiring clarification, including local versus global/scoped identifiers.
- Canonical exclusions and named population segments, currency, units and rate denominators.
- Last complete calendar period versus trailing window, timezone and partial-period data.
- Cross-fact grain, empty results, and legitimate unsupported/unmodeled questions.
- Consumed stale/missing Policy context and honest absence of independent numerical validation.

Check interpretation, route, parameters, independent numerical expectations where available, and final caveats/citations/labels. Pin synthetic or snapshot ground truth; changing live values must not silently invalidate the oracle. Grade the query/parameters or compare independently over the same snapshot where fixed numbers are inappropriate; query correctness alone still does not prove source completeness.

Record model identity, skill digest, artifact revision, per-scenario outcome and available latency/token measurements in a small run artifact. Keep observed traces real. Compare the same question slice before and after consequential skill/routing changes, including negative or neutral results. A domain owner should decide launch readiness; do not import Anthropic's ~90% launch threshold as an Ariadne contract or hide failures in an aggregate score.

### 2. Finish the already-shaped advisory Context trust work; do not duplicate it

**Observed current implementation:** `metric_context` attaches metric/Policy bodies and pending-attestation caveats, but returns a null/empty context fallback without an explicit warning on context-assembly errors. `search_pages` returns full content and passage evidence without a normalized trust envelope. `_freshness_view` accepts date strings, not the complete aware-datetime/YAML-native range required by the new design.

**Existing design:** [specification 0011](../specs/2026-10-06-0011-context-trust-signals.md) already addresses normalized freshness, `context_signals`, stale/deprecated/unavailable consumed context, and brief relevant answer caveats. Progress that work through its existing review/planning/implementation gates, rather than creating a second lifecycle feature.

Respect its selected boundaries: signals are advisory, only already-consumed dependencies are assessed, full rule bodies remain present, optional missing metadata alone does not warn, and search eligibility/arithmetic/admission do not change. The article is evidence, not authorization to introduce expiry-based refusal or ranking changes.

### 3. Distinguish data freshness/completeness from Context freshness

**Important separate gap:** specification 0011 explicitly does not prove live-data correctness. A current Policy page can describe a table whose ingestion stopped yesterday. A valid query can omit an unarrived partition. Existing physical-schema observations and mapping receipts are useful as-of evidence, not a general pipeline health guarantee.

**Smallest useful addition:** allow domain-owned source-quality evidence to accompany relevant answers: source/snapshot identity, observed data watermark and its time semantics, expected update cadence when known, and available freshness/completeness check outcomes. Start by consuming existing upstream checks or bounded domain-specific probes, not by building a transformation/monitoring platform. `MAX(event_time)` alone is not proof of pipeline currency or completeness.

A concise provenance footer could disclose metric and admitted revision, applicable Policy paths, underlying data as-of, known owner, and meaningful warnings. Unknown means unknown; never manufacture an owner, recency or confidence score. Keep document expiry, source observation time, admission and independent numerical validation separate.

For leadership-bound or otherwise consequential analyses, consider explicit human review and comparison of top KPIs to an independent approved reference. This is an answer-use policy, not a claim that existing artifact admission is insufficient or authorization to add a runtime refusal.

Sources: [Context implementation](../../src/ariadne/context.py), [schema/identifier specification](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md), [specification 0011 non-goals](../specs/2026-10-06-0011-context-trust-signals.md), article sections “Data foundations” and “Online validation.”

### 4. Make intent and canonical population discovery explicit

Ariadne's skill starts with metric discovery, term resolution and context search. Add concise guidance to clarify material ambiguity before choosing a metric: entity/population, business purpose where relevant, period/timezone, units and denominator. State reasonable defaults when they are established; ask only when unresolved alternatives change the answer. Separate observations from interpretations and unsupported causal claims.

The graph runtime already accepts declared named segments and time dimensions. However, `list_metrics` currently exposes only name, description and dimensions; making relevant segment/time capabilities discoverable would reduce accidental hand-rolled population filters or premature ad-hoc fallback. This is a potential additive discovery change requiring its own bounded design, not evidence that the compiler lacks these features.

Prefer better domain references over a longer generic skill: grain, scope/exclusions, required filters, ownership, “use for / do not use for,” and neighboring-domain links. Reuse OKF References, Policies and navigation; do not create a second authoritative set of business definitions inside skill Markdown. A richer domain router is warranted only when measured retrieval/agent cases miss the right reference. The article's company knowledge graph does not establish a need for a graph database in Ariadne.

Sources: [packaged skill](../../src/ariadne/skill_assets/SKILL.md), [term/schema specification](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md), [measured retrieval contract](../specs/2026-09-23-0002-context-retrieval.md), [Query runtime](../../src/ariadne/query.py) (`list_metrics`, `query_metrics`), [semantic graph](../../src/ariadne/semantic_graph.py).

### 5. Close the maintenance loop without automatic authority or transcript collection

Ariadne already colocates semantic/context artifacts in a data project, validates exact candidates, and distributes version-matched workflow guidance. Preserve coordinated model/Policy/Reference changes and run affected checks on reviewed candidates. A blind rule that every model edit must touch the generic packaged skill would create meaningless edits; check actual dependent domain content instead. The repository's inspected GitHub workflow runs core tests for tagged publication, not every pull request; affected-check PR CI is worth considering separately where it is not already provided.

Use explicit user corrections as candidate domain-document fixes and regression questions. Keep fixes unadmitted until the normal human review. Reuse the existing Answer Example boundary where applicable: explicit bounded submission, user confirmation and operator review. Do not import the article's channel-scanning/transcript-harvesting bot: the [existing Answer Example specification](../specs/2026-09-29-0007-answer-examples.md) and skill prohibit silent saving/harvesting.

Simple opt-in run records can later reveal governed-route share, uncovered concepts, clarification/refusal outcomes and corrections. No telemetry service or raw conversation retention is needed initially.

Sources: [Git authoring ADR](../adr/0016-modular-core-git-authoring.md), [packaged skill](../../src/ariadne/skill_assets/SKILL.md), [Answer Example specification](../specs/2026-09-29-0007-answer-examples.md), [publication workflow](../../.github/workflows/publish.yml).

## What not to copy by default

- **A reviewer agent for every query.** Test whether bounded semantic/assumption review earns its cost, especially for novel, cross-domain or high-stakes analyses. Independent model agreement is not an independent numerical oracle. Avoid unbounded repair/review loops; retain the repository's existing bounded-review rules.
- **Raw SQL or a giant historical-query retrieval corpus.** Anthropic's own corpus ablation moved accuracy by less than a point. Ariadne's curated, separately labeled Answer Examples are method references, never caches, definitions or query-execution authority.
- **A knowledge graph, vector database, warehouse telemetry stack or Slack integration just to resemble Anthropic.** Start with canonical datasets, a compact question set and clear references. Escalate retrieval only on measured misses under the existing retrieval contract.
- **Broader data access as an accuracy optimization.** Source approval and read-only execution are not per-user/tenant authorization. For a future shared deployment, scope credentials, accessible context and output to the audience's permitted data before exposing it; local HTTP authentication is not a warehouse entitlement model. This is a deployment design prerequisite, not a demonstrated vulnerability in the current trusted-local setup.
- **Identical tool permissions across every surface.** Shared operations should produce the same envelopes and calculations; the native Analyst role intentionally exposes fewer tools than CLI/Analyst MCP. Do not silently expand role authority to pursue feature parity.

Sources: article “Ablation techniques,” “Online validation,” and “Getting started”; [measured retrieval specification](../specs/2026-09-23-0002-context-retrieval.md), [native Analyst tool boundary](../../ariadne-agent/src/ariadne_agent/analyst.py), [README deployment boundary](../../README.md).

## Proposed next step and verification

Keep the architecture. First select a compact owner-approved domain question set and establish the actual answer baseline. Continue specification 0011 through its existing gates; shape source-quality/provenance separately. Use those questions to decide whether discovery, reference structure or targeted review needs changing.

Validation obligation: **existing-check**—primary-source comparison, static inspection of named implementations/specifications and local Markdown link verification. No runtime suite, live agent, S3 access, data-quality probe, benchmark or implementation was run or claimed. No authoritative source, ticket, code or existing dirty file was changed by this assessment.
