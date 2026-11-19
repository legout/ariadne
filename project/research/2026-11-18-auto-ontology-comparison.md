# NVIDIA auto-ontology and Apache Ossie: comparison with Ariadne

Date: 2026-11-18. Evidence for [spec 0037](../specs/2026-11-18-0037-simple-ariadne.md).
Sources: `github.com/NVIDIA/auto-ontology` (single commit, 2026-11-18, server 1.3.0);
`github.com/apache/ossie` core spec `0.3.0.dev0`; `github.com/apache/ossie-converters`
(`nvidia/`, 2026-11-18). README, `docs/architecture.md`, `pyproject.toml` and import
structure were inspected. No auto-ontology code was executed.

## auto-ontology in one paragraph

A server application consisting of a Next.js UI, FastAPI backend, FastAPI ingestion
and compile service, a FastMCP server, Postgres with pgvector, and optional Vault.
Language models are required in four roles (reasoning, non-reasoning, embedding,
reranking). It drafts an ontology from database metadata: terms, column attributes,
data-confirmed foreign keys, term families, and SQL attributes mined from query history.
Questions are answered by a ReAct text-to-SQL loop (`retrieve` → `run_sql` → `submit`)
that uses the ontology as context. "Certify" marks an element as reviewed but "doesn't
change how the agent retrieves". Ossie YAML handles import and export.

## Contrast with Ariadne

| | auto-ontology | Ariadne |
|---|---|---|
| Answer computation | LLM writes SQL per question | Admitted definitions are compiled deterministically |
| Human review | Advisory mark | Gate before serving |
| Join safety | Data-confirmed FK links | Grain/fan-out guard, fact branches |
| Runtime | Multi-service, Postgres, LLM required | Local CLI, Git, no LLM to calculate |
| Draft generation | Automatic, strong (BEAVER #1) | Host agent required |

## Reuse feasibility

- `auto-ontology-server` **as a library: rejected (hard reasons).**
  - Its Python range `>=3.12,<3.14` does not intersect Ariadne's former `>=3.14`.
  - The drafter (`semantic/pipeline.py`, `visit_enter.py`) reads and writes through its
    Postgres data layer (`auto_ontology.dal.*`, SQLAlchemy, Alembic).
  - It is not published on PyPI and has no stable API.
  - It has about 40 heavy dependencies, including a hard pin `openai==2.44.0`.
  - Use it as an external service and exchange Ossie YAML instead.
- `apache-ossie-nvidia-auto-ontology` **as a library: suitable.** It depends only on
  PyYAML and sqlglot, works offline, and requires Python `>=3.11`. It installed and
  imported under CPython 3.14 in an isolated environment and exposes
  `convert_auto_ontology_to_ossie` and `convert_ossie_to_auto_ontology`.
- **Sibling converters** in `ossie-converters` (dbt, Cube, Snowflake, Databricks,
  Lightdash, ThoughtSpot, Palantir, and others) give a way to import existing semantic
  models.
- `apache-ossie` (Pydantic v2 models, `>=3.11`) is optional. Ariadne already
  validates with `jsonschema`.

## Ossie 0.3.0.dev0 deltas relevant to Ariadne

Ossie 0.3.0.dev0 is unreleased and mutable ("do not depend on this version in
production"). Ariadne currently uses `version: 0.2.0.dev0` with a `semantic_model`
array. The breaking changes:

- One model per document at the root.
- `custom_extensions` becomes `nonportable_extensions`, with `data` as an object.
- `expression.sql` (`OSSIE_SQL_2026`) is primary.
- Metric expressions, keys and relationship columns refer to fields, not source
  columns.
- Dataset-scoped metrics, `source.column` and `AGG(dataset.metric)`.
- True division and half-away-from-zero `ROUND`.

Affected Ariadne code:

- `render.py`, `planner.py`, `grain.py`, `validate.py`, `query.py`,
  `semantic_graph.py`, `context.py`, `discovery.py`, `contract_inspection.py`,
  `status.py`, `authoring.py` and `lumio_context.py`.
- 28 YAML files and 20 test files that contain `semantic_model`.

## Python floor

`mcp==2.2.0` and `lancedb` support `>=3.10`. Under 3.12 and 3.13 the only parse
failures in product code are 7 unparenthesized `except A, B:` clauses (PEP 758,
Python 3.14 syntax) in `review.py`, `authoring.py`, `setup.py`, `lumio_context.py`,
`proposals.py`, `context.py` and `init.py`. Runtime behavior under 3.12 was not
executed.

## Size baseline (2026-11-19)

| Area | Production lines | Test lines | Test functions |
|---|---|---|---|
| ariadne-data | 34,392 | 39,156 | 586 |
| lumio-wiki | 56,509 | 50,999 | 1,373 |
| lumio-lancedb | 2,034 | 2,300 | 72 |
| lumio-workspace | 7,705 | 10,117 | 38 |
| products/lumio/tests, integration/tests, tests/ | – | 11,841 | 206 |

Test files that read source text (`read_text`/`getsource`): 44. Test files that use
private names: 58. Both counts are candidates for review, not verdicts.

## Later candidates (not in scope)

- Ossie relational (Layer 2) and wide-table (Layer 3) query interfaces.
- Ossie ontology documents as a formal home for Ariadne's Ontology concept.
- The auto-ontology-eval/BIRD harness to benchmark Ariadne answers.
