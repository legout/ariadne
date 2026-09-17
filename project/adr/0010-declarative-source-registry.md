# Declarative source registry with a shared connection builder

Status: accepted (owner, 2026-09-17 shape-design round for spec revision 9).

Every command previously attached a single SQLite file via `--db`. Source breadth lands as a declarative `ariadne.yaml` registry (sources: block) plus one shared connection builder that produces the DuckDB session for serve/author/validate/profiler: native table functions for csv/json/parquet (local and remote via httpfs), DuckDB extensions for delta/iceberg/ducklake, `postgres_scanner` attach for postgres, and the existing read-only SQLite attach. File globs become views so every source is addressable as `<source>.<table>` — envelopes, the compiler, the grain guard, and the audit operate unchanged over the unified connection. Credentials are env-var references (`connection_env`) resolved at runtime and never committed; a registry containing an inline connection string is a validation error. Validation is tiered by what DuckDB can fixture locally: live execution tests for sqlite/csv/json/parquet/delta, exact statement-construction tests for iceberg/ducklake/postgres/s3-https.

**Considered options:** CLI-arg source lists (rejected — no project portability); auto-discovery of files (rejected — explicit registry only, no surprise sources); a separate sources.yaml (rejected — one project config).
