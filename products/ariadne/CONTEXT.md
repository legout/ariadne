# Ariadne

Ariadne lets autonomous AI agents query heterogeneous data stores through governed, deterministic metrics instead of raw text-to-SQL. This is the canonical vocabulary for the Ariadne product area.

## Language

### Agents

**Ariadne Agent**:
The conversational Python backend that uses one user-selected role to work with Ariadne's governed query or proposed authoring capabilities. It does not calculate or approve business definitions itself.
_Avoid_: agent framework, semantic engine

**Data Analyst Agent**:
The Ariadne Agent role that answers data questions through governed metrics and Context Layer guidance, or clearly labels an unmodeled Ad-hoc Metric as ungoverned.
_Avoid_: text-to-SQL agent

### Layers

**Context Layer**:
The source-linked physical schemas and business guide: tribal knowledge, filtering rules, terminology, identifier relationships and provenance as version-controlled OKF Markdown. Routes and guides; never calculates.
_Avoid_: documentation, business glossary, wiki

**Semantic Layer**:
The calculation engine: declarative OSI YAML models compiled to dialect SQL with join safety. Calculates; never holds business narrative.
_Avoid_: metrics layer, headless BI

**Ontology**:
The world model: the business entities (Customer, Order) and their relationships across databases, independent of physical tables.
_Avoid_: schema, data model

### Quality

**Data Contract**:
A producer-owned declaration of expected dataset structure and quality, with its own identity and version. It is distinct from observed physical state, executable semantic meaning and human admission.
_Avoid_: observed schema, semantic model, quality guarantee

**Contract Binding**:
An explicit consumer-owned association between a Data Contract's scoped dataset/field identities, an identified physical source and a Semantic Layer dataset. It grants neither source access nor join authority.
_Avoid_: name matching, source approval, shared ontology identity

**Contract Observation**:
A Core-produced, scoped, as-of comparison of supported contract expectations with an identified source. It is distinct from producer-supplied Source Quality Evidence and does not guarantee current conformance or confer human admission.
_Avoid_: contract approval, live quality guarantee, upstream attestation

**Contract Drift**:
An observed difference between a supported contract expectation and its bound source at a stated scope and time. Unavailable, unsupported or unmeasured requirements are not observed drift or proof of compliance.
_Avoid_: rewritten contract, unknown state, failed access

**Governed Metric**:
A named measure with one canonical Semantic Layer definition admitted by human review through the applicable Promotion or Git Review Admission route. Never computed by ad-hoc agent SQL.
_Avoid_: KPI, ad-hoc metric

**Freshness**:
The temporal state of a Context Layer page or measured evidence against its declared expiry or applicable evidence-age rule. It is distinct from human admission and is not proof that live data is unchanged.
_Avoid_: approval, live-data correctness

**Source Quality Evidence**:
A source-linked, scoped, as-of report supplied by a domain owner or upstream producer about data recency or completeness. It is reported evidence, not proof of current source health, artifact admission or independent numerical correctness.
_Avoid_: live quality guarantee, core measurement

**Data Watermark**:
A source-reported boundary with an explicit meaning, such as event time, ingestion progress or snapshot coverage. Its value and observation scope do not by themselves prove that every expected record has arrived.
_Avoid_: last modified, completeness guarantee

**Document Verification**:
Confirmations declared against a Context Layer document's sources or underlying resource. These are advisory trust signals, not artifact admission or execution proof.
_Avoid_: admission, numerical attestation

**Execution Attestation**:
A per-run check that the sanctioned computation produced the result and the reported value matches its authoritative execution result. It is distinct from Independent Numerical Validation.
_Avoid_: compile success, human admission

**Independent Numerical Validation**:
A check of a computed answer against an independent expected-value source. It is distinct from definition admission and Execution Attestation.
_Avoid_: execution fidelity, model agreement

**Fan-out**:
A row join that repeats one fact's measures and inflates their aggregates. Aggregating each fact before alignment avoids cross-fact fan-out, but a pre-joined dataset can still contain it.
_Avoid_: row explosion

**Conformed Dimension**:
An explicitly reviewed equivalence between grouping keys on different fact datasets (such as their business dates), not permission to join their raw rows.
_Avoid_: same-named columns, foreign-key join

**Fact Branch**:
One fact's independently filtered and aggregated part of a multi-fact query, before its result is aligned with other facts.
_Avoid_: joined fact rows

### Authoring workflow

**Authoring Agent**:
The agent that profiles a database and drafts Context Layer and Semantic Layer artifacts from statistical profiles and documentation.
_Avoid_: generator

**Authoring Proposal**:
A proposed change to the project's authored artifacts, including source declarations, Seed Notes, Semantic Layer, Context Layer, Data Contracts, Contract Bindings and explicitly saved Answer Examples, based on an identified artifact revision and awaiting human review. It is distinct from served state and from the legacy ad-hoc Proposal.
_Avoid_: approved change, served branch

**Candidate Revision**:
The exact effective artifact state of an Authoring Proposal, including inherited artifacts and explicit edits, evaluated and reviewed as a unit. It is not an admitted revision merely because validation succeeds.
_Avoid_: admitted revision, validation label

**Storage Profile**:
A named, operator-configured access description shared by data sources using the same storage service and credential binding. It is distinct from a source declaration, a business dataset and Source Approval.
_Avoid_: data source, semantic dataset, source approval

**Source Approval**:
The operator's explicit permission to open identified source locations, including the effective storage endpoint where applicable. Artifact review, a source declaration and technical validation do not grant this permission.
_Avoid_: source discovery, artifact admission

**Staging**:
The legacy holding area for authored artifacts and Answer Examples awaiting their former review routes. It is a historical persistence concept, not a Git-backed Authoring Proposal or Candidate Revision.
_Avoid_: drafts, sandbox

**Promotion**:
The legacy local human act of admitting a staged artifact into its reviewed destination. It is distinct from Git Review Admission; discoverability was never admission.
_Avoid_: publish, deploy

**Git Review Admission**:
The route that serves a human-reviewed Git artifact revision only after validation of the exact revision, including local Git-backed authoring and the production review route. A commit or validator label alone does not mean review; this route is distinct from staged-artifact Promotion.
_Avoid_: automatic promotion, validated commit

**Verbatim Ingestion**:
The intake of a source document whose converted wording is retained rather than model-distilled. Preservation does not confer human admission, business authority or independent correctness.
_Avoid_: automatic approval, lossless binary conversion, policy extraction

**Seed Notes**:
The human-owned data dictionary (`data/seed_notes.md`) carrying business rules that statistics cannot derive; an input to the Authoring Agent alongside the statistical profile. It may be drafted by a harness from domain evidence, but its rules become authoritative only after human approval.
_Avoid_: hints file

**Business Onboarding**:
The targeted clarification of a data project's business meaning using existing owner knowledge and source evidence. Its captured interpretations remain proposals until human admission through the applicable route.
_Avoid_: automatic business-rule approval, setup wizard

### Integrated knowledge and analytics

**Content Repository**:
The jointly reviewed authored knowledge and analytics inputs under one revision history. It is distinct from either software repository and from an admitted runtime snapshot.
_Avoid_: merged codebase, published version, shared draft store

**Context Binding**:
An explicit association between an identified metric, its knowledge Entity and its required Policies in one knowledge snapshot. It grants neither source access nor calculation or join authority.
_Avoid_: title match, Contract Binding, inferred dependency

**Policy Binding**:
The versioned consumer-owned association naming one required Policy's subject, its applicable operations and, when executable, the existing Core check that actually enforces it. Authored in the integration selector and captured by admission; explanatory records prove no SQL equivalence and no binding grants new authority.
_Avoid_: Policy rule, narrative filter, producer applicability field

**Policy Closure**:
The complete finite set of required Policies reached through explicit Policy dependencies for a metric in one knowledge snapshot. Provenance citations and navigation links are not Policy dependencies.
_Avoid_: all linked pages, search results, source closure

**Visibility Scope**:
The operator-authorized set of knowledge access classes for an integrated project and its bound release. It is distinct from authored Visibility and cannot be widened by a query.
_Avoid_: user role, authored permission, visibility hierarchy

**Bound Release**:
An immutable, human-admitted association of exact knowledge, analytics, evidence and execution identities. It is distinct from a package release and does not freeze mutable business data.
_Avoid_: latest, software version, historical answer cache

**Support Revision**:
The per-admission revision of the integrated consumer capability table (profile kinds, operations) recorded in a Bound Release. Older revisions stay valid for their previously qualified operations; capabilities beyond a recorded revision refuse on that release, and expansions require a new admission.
_Avoid_: SDK version, global feature flag, automatic upgrade

### Querying

**Ad-hoc Metric**:
An agent-drafted, one-shot metric: validated by the deterministic compile gate and executed read-only, but not admitted. Queryable now, canonical never, until human admission.
_Avoid_: dynamic metric, on-the-fly metric

**Governed Detail Query**:
A field projection over a human-admitted semantic model and its permitted relationships. It is not an Ad-hoc Record Query or a freestanding metric definition; descriptive Context grants no additional join authority.
_Avoid_: raw record query, ad-hoc metric

**Input Context**:
The version-bound descriptions, applicable Policies and evidence caveats for physical inputs consumed by a query. It is distinct from an admitted metric's Context and does not make an Ad-hoc result governed.
_Avoid_: admitted ad-hoc definition, source approval

**Ad-hoc Record Query**:
A bounded selection of records from a known project dataset, validated and executed read-only but not admitted as a governed definition. It is not a metric and produces no Proposal.
_Avoid_: ad-hoc metric, governed detail query, raw SQL

**Proposal**:
A legacy persisted Ad-hoc Metric definition awaiting its former human review route. An ephemeral Ad-hoc Metric is not a Proposal; an explicitly retained definition is an Authoring Proposal.
_Avoid_: draft, candidate file

**Answer Example**:
An explicitly submitted OKF record of a question, intended meaning, used query method and bounded historical answer. Review approves it as a reusable reference, not a governed definition or an answer cache.
_Avoid_: query snippet, cached answer

**SQL Provenance**:
The historical SQL text retained from the submitted result of an Answer Example. It is evidence of what was submitted, not an executable reuse method or authenticated proof that a computation ran.
_Avoid_: saved query, execution proof, query history

### Context Layer (OKF bundle)

**Bundle**:
The project's version-controlled OKF Context Layer, containing the typed pages relevant to its documented sources and modeled meaning, with generated navigation and change history. It can describe sources before any metric is modeled.
_Avoid_: knowledge base directory, docs folder

**Context Routing Map**:
A human-owned OKF Reference directing business questions to existing definitions, Policies and source evidence. It is a navigational guide, not a second definition catalog or authority to calculate.
_Avoid_: executable router, second metric catalog, bounded-context map

**Dataset Overview**:
An OKF page describing an identified physical source or collection and its related tables. It is not a Semantic Layer dataset or a metric definition.
_Avoid_: OSI dataset, semantic model

**Schema Observation**:
An identified catalog description or measurement of a physical table's structure and statistics at a stated source version or time. Observations do not by themselves establish business meaning or permanent constraints.
_Avoid_: declared business key, permanent guarantee

**Observed Filter Values**:
Bounded measurements of explicitly selected field values and their frequencies at a stated scope and time. They aid filter interpretation, not establish a complete allowed-value domain or current validity.
_Avoid_: business enum, allowed-value constraint, live value validation

**Term Reference**:
An OKF Reference naming a shared business concept, its language aliases and its scoped field representations. A language alias is not proof that field values are interchangeable.
_Avoid_: synonym database, automatic field substitution

**Identifier Mapping**:
A declaration relating identified, scoped identifier representations through equality, prefix construction or an explicit lookup. A hypothesized relationship is distinct from an asserted relationship confirmed by exact-revision human admission.
_Avoid_: same-named columns, approved join

**Mapping Evidence**:
Core-produced measurements of an identified mapping candidate over stated sources, scope and time. Measured matches support investigation, not automatic confirmation of business meaning.
_Avoid_: model confidence, business approval

**Grain**:
The declared row identity of a dataset (its primary key in analytical terms). Each dataset has one grain; a model may contain several differently grained datasets. Base measures stay at their owning dataset's grain, and multi-fact results align only after fact-local aggregation (ADR-0006).
_Avoid_: granularity, level

**Policy**:
A human-owned business rule expressed as Context Layer knowledge (e.g. status exclusion, currency cutover). Standalone metrics cite native OKF Policies; integrated metrics bind required Policies from an exact Lumio snapshot.
_Avoid_: rule note, guideline

**Computation**:
An OKF page carrying the sanctioned way to calculate a value and its Independent Numerical Validation status; a newly modeled metric may still have `attestation: pending` after human review.

**Attested Computation**:
In Ariadne's application profile, a Computation with an actual independent expected-value check identified by its `attester`, not merely a compiled or human-reviewed definition. A cited attester does not establish per-run Execution Attestation or prove that each current answer was independently checked.
_Avoid_: query snippet
