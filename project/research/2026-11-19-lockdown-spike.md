# Probe report: DuckDB `lock_down` for guarded ad-hoc SQL

Date: 2026-11-19. Spike approved by the owner ("stufe 1 und 2 zusammen") under
[spec 0037 r2](../specs/2026-11-18-0037-simple-ariadne.md). The throwaway code ran in
`/tmp` and has been deleted, and the containers were removed. Nothing was added to the
repository except this report.

**Question:** After Ariadne-style source setup, does
`allowed_directories` + `enable_external_access=false` + `lock_configuration=true`
keep every approved source type queryable while refusing escapes?

**Setup:**

- DuckDB 1.5.6, the version in Ariadne's lock, on CPython 3.14.
- Ariadne's `sources.plan()` shapes:
  - `LOAD`s;
  - `READ_ONLY` attaches;
  - views over `read_*`, `delta_scan` and `iceberg_scan`;
  - one temporary scoped `TYPE S3, PROVIDER CONFIG` secret per profile.
- SeaweedFS as the S3 server (the MinIO image was not pullable), Postgres 17, and
  `deltalake`/`pyiceberg` fixtures.

## Evidence

**Works under lock** (all observed OK):

- Local parquet, csv and json views.
- SQLite attach.
- A native DuckDB catalog table, and its view over a local backing file and over an
  S3 backing file.
- DuckLake.
- Delta, local and on S3; Iceberg, local and on S3.
- Postgres attach, and a join across Postgres and S3.
- `USE`, and window/CTE queries.
- The deadline interrupt.

**Refused by lock alone** (observed):

- Files outside the allowed directories, `~/...`, and `http(s)` URLs.
- A sibling prefix (`data_evil/`, `s3://…/sales_x/`), an S3 bucket or prefix outside
  the scope, and an S3 glob of the bucket.
- Symlinked files and directories that point outside.
- `ATTACH` of a new file or of a new Postgres database.
- `INSTALL`/`LOAD`, every `SET` (including `s3_endpoint`), and `CREATE PERSISTENT
  SECRET`.
- `COPY TO` a local file, and `INSERT` into a read-only attach.

**The allow-list is required:** without `allowed_directories`, every file, S3, Delta,
Iceberg and catalog-view source fails. Ariadne must derive the list from the approved
registry, including Delta/Iceberg folders and catalog backing files.

**Gaps that lock alone does not close** (observed):

| # | Escape | Observed |
|---|---|---|
| G1 | `s3://approved/sales/../private/secret.parquet` | **Read private data.** The check runs on the unnormalized path, and SeaweedFS normalized `..`. Whether this works depends on the S3 server. |
| G2 | `sqlite_scan('<outside>/x.db', …)` | **Read a local file outside the allow-list.** The scanner bypasses DuckDB's file system checks. |
| G3 | `postgres_scan('<dsn>', …)`, `postgres_query('pg', '<sql>')` | Connects to an arbitrary DSN, and runs arbitrary read SQL on the attached database (here a read of `pg_shadow`). |
| G4 | `CREATE SECRET … SCOPE 's3://approved/sales/z'` with a foreign endpoint; `DROP SECRET` | Allowed. Reads under that scope are redirected to the foreign host (SSRF/DoS). |
| G5 | `COPY … TO 's3://approved/sales/w.parquet'` | **Write succeeded.** Lock does not make S3 read-only. |
| G6 | `duckdb_secrets()` | Exposes the key id, endpoint and scope. The secret value is redacted. |
| G7 | Directory allow-list | An unapproved file in an approved directory is readable. `allowed_paths` (per file) refuses it. |

**A parse-tree guard closes G1–G6** (observed with `extract_statements` and
`json_serialize_sql`):

- Statement types distinguish `SELECT`/`EXPLAIN` from `COPY`, `ATTACH`, `CREATE
  SECRET` and multiple statements.
- The JSON tree exposes every `TABLE_FUNCTION`, including those in subqueries and
  `LATERAL` (`read_parquet`, `sqlite_scan`, `postgres_query`, `duckdb_secrets`,
  `glob`, `read_text`).
- A literal path in `FROM 's3://…'` appears as a `BASE_TABLE` whose name contains the
  path.

## Verdict

`lock_down` is necessary and works with every Ariadne source type, but it is not
sufficient on its own. Confidence: high for the observed DuckDB 1.5.6 behavior. G1
depends on the S3 implementation.

**Production recommendation for sub-spec B** (guarded ad-hoc SQL), as three layers:

1. **Statement guard:** exactly one `SELECT`, or `EXPLAIN` of a `SELECT`. This closes
   G4 and G5.
2. **Parse-tree guard** (`json_serialize_sql`):
   - no table functions at all; ad-hoc SQL references only registered views and
     tables;
   - every `BASE_TABLE` resolves to a registered catalog, schema and table, so
     literal paths are refused.

   This closes G2, G3 and G6, and G1 for ad-hoc input.
3. **`lock_down`** after setup:
   - `allowed_paths` per approved file where it is enumerable;
   - `allowed_directories` only for folder-shaped sources (Delta, Iceberg, DuckLake
     data paths, globs, catalog backing folders);
   - registry paths containing `..` are refused at registration.

   This provides defense in depth for anything layer 2 misses.

Postgres attaches expose the whole database to the connected role. Source approval
should therefore recommend a least-privilege role; schemas outside the approved
scope can also be refused by layer 2.

**What would invalidate this:**

- A DuckDB upgrade that changes `json_serialize_sql` node types or the
  lock/permission semantics. Pin the version and add a regression test per gap class.
- Extensions that add new scan paths not modeled as table functions.

The owner decided on DuckDB `>=2.0` (2026-11-19). Sub-spec A re-runs these gap classes
under 2.0 before B relies on them.
