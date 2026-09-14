# Ariadne

Ariadne lets autonomous AI agents query heterogeneous data stores through governed, deterministic metrics instead of raw text-to-SQL. This is the canonical vocabulary for the whole repository.

## Language

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
Join multiplication that silently inflates aggregates when a query fans one row into many. The Semantic Layer's compile-time safety exists to prevent it.
_Avoid_: row explosion

### Authoring workflow

**Authoring Agent**:
The agent that profiles a database and drafts Context Layer and Semantic Layer artifacts from statistical profiles and documentation.
_Avoid_: generator

**Staging**:
The holding area (`staging/`) where authored artifacts await human review. The Authoring Agent never writes anywhere else.
_Avoid_: drafts, sandbox

**Promotion**:
The human act of moving a staged artifact into the served layers, marking it verified. Served artifacts only ever arrive by Promotion.
_Avoid_: publish, deploy
