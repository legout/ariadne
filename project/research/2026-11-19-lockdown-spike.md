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

## Re-probe under DuckDB 2.0.0 (spec 0039 §4.4)

Date: 2026-11-19, DuckDB 2.0.0 on CPython 3.12 (linux arm64). Throwaway code in `/tmp`,
not in the repository. The same setup order as above: `LOAD`s, read-only attaches, views
over `read_*`, a scoped `TYPE S3, PROVIDER CONFIG` secret, then
`allowed_directories` + `enable_external_access=false` + `lock_configuration=true`.

**Scope of this re-probe.** Local sources and the parse-tree node types were re-probed
directly. The Postgres, S3 (SeaweedFS) and live Delta/Iceberg-on-S3 stages were **not**
re-run, because no servers were started for this task. Their attach and load paths are
covered by the existing source-type tests, which pass under 2.0.0 (offline S3 profile
tests, Delta/Iceberg/DuckLake statement tests). G1 (S3 `..` normalization) and the
Postgres half of G3 are therefore **unverified under 2.x**. B must re-probe them against
live servers before relying on them.

**Extensions:** `sqlite`, `httpfs`, `delta`, `iceberg`, `ducklake` and `postgres` all
install and load.

**Works under lock (2.0.0):** parquet, csv and json views; SQLite attach (a SQLite
`INTEGER` column came back as `BLOB` bytes in this probe, with the probe table declared
untyped); native DuckDB read-only attach; window and CTE queries.

**Refused by lock alone (2.0.0):**

- A file outside the allowed directory, a sibling prefix glob, a symlink that points
  outside, `http(s)`, `~/`, and a `..` path that leaves the directory.
- `ATTACH` of a new file (inside or outside the directory) is refused only outside the
  allowed directory. Inside it the attach **succeeded**, which was already possible
  under 1.5.6 for an allowed path.
- `INSTALL`, `SET s3_endpoint`, `CREATE PERSISTENT SECRET`.
- `read_text` and `glob` on an outside path.
- `COPY TO` outside the allowed directory, and `COPY TO s3://…` without httpfs loaded
  (the S3 write itself, G5, was not re-run against a server).
- `INSERT` into a read-only attach (refused with a type error in this probe, so it does
  not prove the read-only refusal by itself).

**Differences from 1.5.6:** `COPY TO` a local file **inside** the allowed directory
succeeds. That behavior is not in the 1.5.6 list, but the earlier note only recorded
`COPY TO` to a file outside; this is a requirement input for B (the statement guard
already covers it).

**Gap classes under 2.0.0:**

| # | Result |
|---|---|
| G1 | Not re-run (needs an S3 server). |
| G2 | `sqlite_scan` of an outside file is now **refused** by the file system check (was a bypass in 1.5.6). Keep the parse-tree guard as defense in depth. |
| G3 | `postgres_scan` is not a defined function; `postgres_query` on a non-Postgres attach is refused. The live Postgres case was not re-run. |
| G4 | `CREATE SECRET … SCOPE` and `DROP SECRET` are still **allowed** under lock. |
| G5 | Not re-run against an S3 server. |
| G6 | `duckdb_secrets()` still lists name, type and scope. |
| G7 | A directory allow-list still exposes an unapproved file in an approved directory; `allowed_paths` refuses it. |

**`json_serialize_sql` node types:** `TABLE_FUNCTION` appears for plain, subquery and
`LATERAL` table functions; `BASE_TABLE` covers named relations and literal paths
(`FROM 's3://b/p.parquet'`); `SUBQUERY` and `JOIN` appear as before. Only `SELECT`
statements serialize (`COPY`, `ATTACH`, `CREATE SECRET` and `EXPLAIN` return "Only SELECT
statements can be serialized to json!"), and a multi-statement string serializes as a
SELECT with `error=false`, so the statement count must come from `extract_statements`
(`n=2` for `select 1; select 2`).

**Requirement inputs for B (no change to A):** keep all three layers; the statement
guard must run on `extract_statements` and must refuse `COPY` even inside the allowed
directory; re-probe G1, G3 (Postgres) and G5 against live servers; G2 is closed by lock in
2.0.0 but the parse-tree guard should stay.
