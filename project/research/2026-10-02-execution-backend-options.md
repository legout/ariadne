# Deferred exploration: execution backend options

Status: deferred design exploration, not an approved specification or implementation plan.

## Current decision

The owner chose to retain DuckDB for the Ariadne Core refactoring (Pi conversation, 2026-10-02). Do not add backend plugins, Ibis, native Polars compilation, or a new expression format as part of that refactoring. Preserve Ariadne's existing sqlglot compilation, source-access checks, grain/cardinality audits, read-only query execution, and human review/admission gates.

## Possible later direction

Distinguish **data sources** from **execution engines**: Ariadne already attaches PostgreSQL and SQLite sources to a DuckDB session. Executing natively in those databases is a separate capability, not another source-registry entry.

Two approaches merit comparison if another execution engine is needed:

- Retain Ariadne's SQLGlot compiler and add engine-specific SQL lowering, source access, validation/audits, and result handling.
- Lower Ariadne's semantic query plan into Ibis expressions, then compile/execute through a supported backend. Ibis is a candidate for a computational representation, not a replacement for Ariadne's semantic planning or governance.

Ibis documents DuckDB, PostgreSQL, SQLite, ClickHouse, DataFusion, and Polars backends, with differing operation coverage. Do not assume the ClickHouse backend also supports embedded chDB or that Ibis supplies automatic cross-engine federation. SQL-string integration is not equivalent to converting arbitrary OSI SQL expressions and dataset-source queries into portable Ibis expressions.

Polars' SQL interface is another possible bounded experiment: it lowers supported SQL to its native engine, but compatibility with Ariadne's complete query surface is unverified.

## Existing seams and migration risks

- `src/ariadne/sources.py`: DuckDB session construction, source attachment, credentials and catalog discovery.
- `src/ariadne/render.py` and `planner.py`: SQL expressions, fact-local aggregation, conformed-key alignment, derived metrics, and windows.
- `src/ariadne/profiler.py`: DuckDB relation operations and `SUMMARIZE`.
- `src/ariadne/grain.py` and `validate.py`: database-backed audits and bind checks.
- `src/ariadne/runtime.py`: guarded execution, result envelopes, context and admission provenance.

A future comparison should include a governed aggregate, a cross-fact query, null/decimal/time semantics, and a rejected grain violation. Unsupported operations must fail explicitly; no raw-SQL fallback or silent data movement. Backend support would need its own approved behavioral contract and reconciliation with the current DuckDB-only specifications.

## References

- [Own SQLGlot compiler](../adr/0008-own-sqlglot-compiler-agpl-exit.md)
- [Governed multi-fact planner](../specs/2026-09-30-0008-multi-fact-planner.md)
- [Ibis operation support](https://ibis-project.org/backends/support/matrix)
- [Ibis SQL integration](https://ibis-project.org/how-to/extending/sql)
- [Ibis Polars backend](https://ibis-project.org/backends/polars)
- [Polars SQL introduction](https://docs.pola.rs/user-guide/sql/intro/)
