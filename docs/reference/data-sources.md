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

## Storage profiles

> **Candidate feature** — named storage profiles are current development-candidate behavior, not published Ariadne 0.3.0. See [Multiple S3 storages](../how-to/multiple-s3-storages.md) for the task guide and delivery rules.

An optional top-level `storages:` block maps profile names to S3 declarations. Values are **environment-variable names**: the executing host process supplies the values, and only the profiles referenced by sources are ever resolved or installed.

| Field | Required | Default / contract |
| --- | --- | --- |
| `type` | yes | exactly `s3` |
| `access_key_id_env` | yes | environment-variable name holding the access key ID |
| `secret_access_key_env` | yes | environment-variable name holding the secret access key |
| `endpoint_url_env` | yes | variable holding an absolute `http(s)://` endpoint URL (host + optional port, root path only; no userinfo/query/fragment) |
| `region_env` | no | explicit `us-east-1` when omitted; if declared but unset/blank, setup refuses |
| `session_token_env` | no | if declared but unset/blank, setup refuses; no automatic token refresh |
| `url_style` | no | `path` (or `vhost`) |
| `scopes` | yes | nonempty list of unique literal `s3://bucket/` or directory-prefix URIs ending in `/`; no globs, credentials, query or dot-segment navigation |

A source selects a profile with `storage: <name>` — allowed for `csv`, `json`, `parquet`, `duckdb`, `delta`, `iceberg` and `ducklake` only (never SQLite/PostgreSQL). A profile-based `s3://` path must fall inside at least one scope of its selected profile, and used profiles must not declare intersecting scopes (equal or nested prefixes refuse). A profile-free direct S3 path that would fall under an installed profile's scope also refuses instead of silently inheriting its secret. A source with a local metadata/catalog path (for example a local DuckLake catalog or native DuckDB view catalog) may reference a profile for its remote backing data.

Profile identity is deterministic and credential-free: source digests include the complete referenced profile declaration (names and scopes, never values), while approvals, evidence and admitted records additionally bind the resolved **effective** endpoint/region/URL-style/scopes — so a changed endpoint needs its own human approval and fresh evidence, while key rotation does not. Temporary scoped secrets are created only inside the connection being set up, never in public plans or stored artifacts. See the [how-to](../how-to/multiple-s3-storages.md) for environment delivery, rotation/restart behavior and the human gates.

## Remote and native DuckDB paths

Remote-path support depends on the source type and DuckDB runtime configuration. Native DuckDB catalogs may use local files, HTTPS, or S3-compatible paths when the required extensions and runtime credentials are available. Remote catalogs are attached read-only.

A read-only attachment is not a sandbox, snapshot, or guarantee that a view is safe. It protects the catalog file from writes, but does not isolate filesystem/network access or freeze remote backing data. Ariadne does not repair publisher-supplied absolute paths or fully qualified URLs. See [How Ariadne works](../explanations/how-ariadne-works.md#source-access-is-not-metric-governance) for the authority distinction and [Docker MCP](../how-to/docker-mcp.md) for explicitly mounting external data.

## Data Contracts do not grant access

[Data Contracts](data-contracts.md) declare expected structure/quality separately
from `contract_bindings.yaml`, which selects an existing exact approved asset
and OSI dataset. A contract server address, variable or binding never registers
a source, supplies credentials, changes an endpoint or expands S3 scopes.
SQL-quality execution supports only an approved native DuckDB source, not every
source type above. Native DuckDB’s trusted-backing boundary is unchanged.

`discover` / `ariadne search` reads pinned admitted metadata without opening
sources. `list_datasets` / `ariadne list-datasets` still constructs the approved
live catalog, returns actual columns and retains ordinary admission/approval
refusals. Its matching contract annotation comes from the pinned snapshot and
adds no source read or second contract inspection; it is not a health check.

## Document inputs are different

Documents supplied as authoring context are not query sources. Markdown and text are handled natively; the optional `ariadne-data[documents]` extra adds supported PDF, Office, and HTML converters. The `ariadne-ingest` command stages document-derived drafts; it does not serve them automatically. See the [CLI reference](cli.md#document-ingestion).
