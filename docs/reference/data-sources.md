# Data source reference

Ariadne reads from named entries in a `sources:` registry, usually `ariadne.yaml`. The source name is the stable alias used to address its tables; it need not match the database or file name.

## Supported source types

| `type` | Required field | Notes |
| --- | --- | --- |
| `sqlite` | `path` | SQLite database file. |
| `duckdb` | `path` | DuckDB database file or operator-trusted DuckDB catalog. |
| `csv` | `path` | CSV file; glob paths require an explicit `table`. |
| `json` | `path` | JSON file; glob paths require an explicit `table`. |
| `parquet` | `path` | Parquet file; glob paths require an explicit `table`. |
| `delta` | `path` | Delta Lake source. |
| `iceberg` | `path` | Iceberg source. |
| `ducklake` | `path` | DuckLake source. |
| `postgres` | `connection_env` | Name of an environment variable containing the DSN; credentials are not stored inline. |

Source names must be unique lowercase slugs. A glob is accepted only for CSV, JSON, and Parquet sources and must use one explicit table name for the glob result.

## Registry example

```yaml
sources:
  - name: shop
    type: sqlite
    path: data/shop.db

  - name: warehouse
    type: duckdb
    path: data/warehouse.duckdb

  - name: events
    type: parquet
    path: data/events/*.parquet
    table: events

  - name: finance
    type: postgres
    connection_env: ARIADNE_FINANCE_DSN
```

For PostgreSQL, set the DSN in the environment and put only its variable name in the registry:

```bash
export ARIADNE_FINANCE_DSN='postgresql://…'
```

Inline connection strings and URL credentials are rejected. Relative paths resolve according to the registry/project route; URI paths such as `https://` or `s3://` are not treated as current-directory-relative paths.

## Remote and native DuckDB paths

Remote-path support depends on the source type and DuckDB runtime configuration. Native DuckDB catalogs may use local files, HTTPS, or S3-compatible paths when the required extensions and runtime credentials are available. Remote catalogs are attached read-only.

A read-only attachment is not a sandbox, snapshot, or guarantee that a view is safe. It protects the catalog file from writes, but does not isolate filesystem/network access or freeze remote backing data. Ariadne does not repair publisher-supplied absolute paths or fully qualified URLs. See [How Ariadne works](../explanations/how-ariadne-works.md#source-access-is-not-metric-governance) for the authority distinction and [Docker MCP](../how-to/docker-mcp.md) for explicitly mounting external data.

## Document inputs are different

Documents supplied as authoring context are not query sources. Markdown and text are handled natively; the optional `ariadne-data[documents]` extra adds supported PDF, Office, and HTML converters. The `ariadne-ingest` command stages document-derived drafts; it does not serve them automatically. See the [CLI reference](cli.md#document-ingestion).
