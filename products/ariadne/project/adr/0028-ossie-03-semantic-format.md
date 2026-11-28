---
status: accepted
amends: ADR-0008, ADR-0006
---

# ADR-0028: Ossie 0.3 as the semantic format, strictly scoped

**Accepted 2026-11-19** with the owner's approval of
[spec 0039](../../../../project/specs/2026-11-19-0039-python312-duckdb2-ossie03.md).

Ariadne's Semantic Layer reads Apache Ossie `0.3.0.dev0` documents:

- one model per file;
- `expression.sql` (`OSSIE_SQL_2026`) is authoritative;
- keys and relationships name fields;
- dataset-scoped metrics, plus model-scoped `AGG(dataset.metric)` compositions.

The schema is pinned to an exact `apache/ossie` commit and validated with
`jsonschema`, because the dev version is unreleased and mutable. Ariadne-only
semantics live in `nonportable_extensions` with `vendor_name: ARIADNE`:

- one-to-one relationship cardinality;
- conformed dimensions;
- metric fill and window rules.

**Note (2026-11-28):** the vendored schema was behind apache/ossie HEAD 4d70c2a (keys name each field once, PR #705; AGG(source.measure), PR #726). Follow-ups: #211 (schema refresh + key uniqueness), #212 (case-insensitive names, owner decision), #213 (AGG(source.measure) scope, owner decision). No decision in this ADR is changed. Update (#211): `ossie-schema.json` is now pinned to 4d70c2a1e8ad6675fa8d0819a7c8bf061997e3d1; the AGG(source.measure) and case follow-ups remain open.

**Decision (2026-11-28, #213):** measure-relation sources and AGG(source.measure) are out of scope; Ariadne refuses them by name.

The cross-model `semantic_layer/graph.yml` remains as a documented non-portable
Ariadne file (owner: "graph.yml behalten").

Name resolution is **strict Ossie** (owner: "Strikt Ossie"). Field→field
references, metric→metric references other than `AGG`, and model-scoped raw
aggregates across several datasets are refused rather than extended. This keeps
models portable to the Ossie converter ecosystem (dbt, Cube, Snowflake,
Databricks, NVIDIA auto-ontology). It also keeps the fan-out guarantee: every
raw aggregate has exactly one owning dataset (ADR-0006).

Metric identities become `model::metric` for model-scoped metrics and
`model::dataset.metric` for dataset-scoped metrics, with no aliases.
`ariadne migrate` converts existing projects once, through the normal review
route.

**Considered options:**

- **Keep the 0.2 envelope (OSI).** Rejected: there is no 0.2 release, and the
  ecosystem moved to 0.3.
- **Ossie plus Ariadne extensions for recursive derivations.** Rejected: such models
  are not portable.
- **Embed the `auto-ontology-server` model format.** Rejected: it is Postgres-bound,
  and Ossie is its own exchange format.
