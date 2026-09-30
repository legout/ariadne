# Ariadne

Ariadne lets autonomous AI agents query heterogeneous data stores through governed, deterministic metrics instead of raw text-to-SQL. This is the canonical vocabulary for the whole repository.

## Language

### Agents

**Ariadne Agent**:
The conversational Python backend that uses one user-selected role to work with Ariadne's governed query or staged authoring capabilities. It does not calculate or approve business definitions itself.
_Avoid_: agent framework, semantic engine

**Data Analyst Agent**:
The Ariadne Agent role that answers data questions through governed metrics and Context Layer guidance, or clearly labels an unmodeled Ad-hoc Metric as ungoverned.
_Avoid_: text-to-SQL agent

### Layers

**Context Layer**:
The business guide: tribal knowledge, filtering rules, routing instructions, and provenance as version-controlled OKF Markdown. Routes and guides; never calculates.
_Avoid_: documentation, business glossary, wiki

**Semantic Layer**:
The calculation engine: declarative OSI YAML models compiled to dialect SQL with join safety. Calculates; never holds business narrative.
_Avoid_: metrics layer, headless BI

**Ontology**:
The world model: the business entities (Customer, Order) and their relationships across databases, independent of physical tables.
_Avoid_: schema, data model

### Quality

**Governed Metric**:
A named measure served only through the Semantic Layer, with one canonical definition. Never computed by ad-hoc agent SQL.
_Avoid_: KPI, ad-hoc metric

**Fan-out**:
Join multiplication that silently inflates aggregates when a query fans one row into many. Prevention is the facade's grain guard on agent-authored ad-hoc sources plus modeling discipline (pre-aggregate one-to-many to the fact grain) — the compiler does not prevent it (Datus-ai/Datus-agent#1426).
_Avoid_: row explosion

### Authoring workflow

**Authoring Agent**:
The agent that profiles a database and drafts Context Layer and Semantic Layer artifacts from statistical profiles and documentation.
_Avoid_: generator

**Staging**:
The holding area (`staging/`) where authored artifacts and explicitly submitted Answer Examples await human review. The Authoring Agent never writes anywhere else.
_Avoid_: drafts, sandbox

**Promotion**:
The human act of admitting a staged artifact into its reviewed destination (served layers or the reviewed Answer Example store), marking its review. Discoverability in Staging is never Promotion.
_Avoid_: publish, deploy

**Seed Notes**:
The human-owned data dictionary (`data/seed_notes.md`) carrying business rules that statistics cannot derive; an input to the Authoring Agent alongside the statistical profile. It may be drafted by a harness from domain evidence, but its rules become authoritative only after human approval.
_Avoid_: hints file

### Querying

**Ad-hoc Metric**:
An agent-drafted, one-shot metric: validated by the deterministic compile gate and executed read-only, but never promoted. Queryable now, canonical never, until promoted.
_Avoid_: dynamic metric, on-the-fly metric

**Proposal**:
An auto-staged Ad-hoc Metric definition awaiting human promotion; successful questions leave their definitions in `staging/` as candidates for the catalog.
_Avoid_: draft, candidate file

**Answer Example**:
An explicitly submitted OKF record of a question, intended meaning, used query method and bounded historical answer. Review approves it as a reusable reference, not a governed definition or an answer cache.
_Avoid_: query snippet, cached answer

### Context Layer (OKF bundle)

**Bundle**:
The OKF v0.2 structure of `context_layer/`: typed folders (tables, references, policies, metrics, computations, skills) with an `index.md` per directory and a `log.md` change log.
_Avoid_: knowledge base directory, docs folder

**Grain**:
The declared row identity of a dataset (its primary key in analytical terms). Every model maps to exactly one grain; additive measures only on fields native to it (ADR-0006).
_Avoid_: granularity, level

**Policy**:
A human-owned business rule published as an OKF page in `policies/` (e.g. status exclusion, currency cutover); metrics cite policies in their `sources`.
_Avoid_: rule note, guideline

**Computation**:
An OKF page carrying the sanctioned way to calculate a value and its independent-attestation status; a newly modeled metric may still have `attestation: pending` after human review.

**Attested Computation**:
A Computation with an actual independent expected-value check identified by its `attester`, not merely a compiled or human-reviewed definition.
_Avoid_: query snippet
