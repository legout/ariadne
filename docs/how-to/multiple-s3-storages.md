# How to read from multiple S3-compatible storages

Read several independently configured S3-compatible storages through one
Ariadne connection using named **Storage Profiles**: the registry names the
environment variables, and the executing host process supplies their values.
Credentials never live in the registry, a proposal, or Git.

> **Optional data-source configuration in Core 0.6.0.** This is separate from
> the local-only Lumio knowledge binding. Compatibility was verified against
> local loopback S3-compatible endpoints with synthetic credentials and the
> runtime's actual `httpfs`/`delta`/`iceberg`/`ducklake` extensions. That
> evidence does not verify your production TLS/CA/IAM configuration or
> deployment.

## Declare two storages

Add a `storages:` block to `ariadne.yaml` and give each S3 source an explicit
`storage:` reference. Every profile declares **literal URI scopes** — the
non-overlapping `s3://` prefixes that select its credentials:

```yaml
storages:
  local:
    type: s3
    access_key_id_env: LOCAL_S3_ACCESS_KEY_ID
    secret_access_key_env: LOCAL_S3_SECRET_ACCESS_KEY
    endpoint_url_env: LOCAL_S3_ENDPOINT_URL
    url_style: path
    scopes:
      - s3://retail/
  remote:
    type: s3
    access_key_id_env: REMOTE_S3_ACCESS_KEY_ID
    secret_access_key_env: REMOTE_S3_SECRET_ACCESS_KEY
    endpoint_url_env: REMOTE_S3_ENDPOINT_URL
    region_env: REMOTE_S3_REGION       # optional; omit -> explicit us-east-1
    # session_token_env: REMOTE_SESSION_TOKEN  # optional, no auto-refresh
    scopes:
      - s3://analytics/

sources:
  - name: orders
    type: parquet
    storage: local
    path: s3://retail/orders/*.parquet
    table: orders
  - name: events
    type: delta
    storage: remote
    path: s3://analytics/events
```

The values are **variable names, never values**: inline credentials,
connection strings and `key=value` expressions are refused, and so are
profiles whose used scopes overlap (equal or nested prefixes). A directly
declared S3 path falling under an installed profile's scope also refuses —
it must select that profile explicitly. See the
[data source reference](../reference/data-sources.md#storage-profiles) for
every field and default.

Only the seven profile-capable types (`csv`, `json`, `parquet`, `duckdb`,
`delta`, `iceberg`, `ducklake`) take `storage:`. A source with a **local
metadata/catalog path** — a local DuckLake catalog or a native DuckDB view
catalog — may reference a profile for its remote *backing* data.

## Supply the values in the process environment

Ariadne reads the variables from the executing process — no `.env` search, no
automatic environment-file loading. Declare and export them wherever that
process runs:

```bash
export LOCAL_S3_ACCESS_KEY_ID='…'
export LOCAL_S3_SECRET_ACCESS_KEY='…'
export LOCAL_S3_ENDPOINT_URL='https://s3.retail.example.org'
export REMOTE_S3_ACCESS_KEY_ID='…'
export REMOTE_S3_SECRET_ACCESS_KEY='…'
export REMOTE_S3_ENDPOINT_URL='https://s3.analytics.example.org'
export REMOTE_S3_REGION='us-east-1'     # supplies the declared region_env above
```

An endpoint URL is absolute `http://`/`https://` with a host and optional
port only — no userinfo, path, query or fragment. For a local MCP launcher,
set them in the launcher's own environment before the server starts.

### Docker is explicit environment injection

A container only sees what its Compose service definition injects. Compose's
`--env-file` flag performs **host-side variable interpolation** — it does
*not* populate the container environment. Forward the profile variables
with exactly ONE mechanism in your local override — an operator-owned
`env_file` entry (shown active below), or explicit `environment` forwarding
of host variables (keep it commented unless the `env_file` line is removed:
with both active, the interpolated `environment` values override the file's,
and unset host variables forward as empty strings):

```yaml
services:
  ariadne:
    env_file:
      - /run/secrets/ariadne_storage.env   # operator-owned file, not Ariadne-managed
    # Alternative (exclusive — remove env_file above first): forward the
    # values from the host variables set in your shell:
    # environment:
    #   LOCAL_S3_ACCESS_KEY_ID: "${LOCAL_S3_ACCESS_KEY_ID}"
    #   LOCAL_S3_SECRET_ACCESS_KEY: "${LOCAL_S3_SECRET_ACCESS_KEY}"
    #   LOCAL_S3_ENDPOINT_URL: "${LOCAL_S3_ENDPOINT_URL}"
```

Ariadne never loads these files itself; the operator owns what enters the
container environment. See [Docker MCP](docker-mcp.md) for the general
credential-forwarding rules of that image.

## Approve once per effective endpoint

Profiles and sources are inert declarations — declaring them opens nothing.

1. An agent or operator proposes the `storages` block together with source
   entries (`ariadne-authoring propose-sources --file sources.yaml`, the
   same registry-shaped file). Proposal creation reads no variables and
   makes no network calls.
2. A **human** runs `ariadne-authoring approve-sources` with the exact
   reported revision and source digest. On the operator host the approval
   resolves the profile's endpoint/region variables — never key or token
   values — and records the effective, non-secret binding.
3. Only then may measured inputs, schema refresh, mapping inspection,
   validation, review and admission run against those sources; evidence and
   admitted snapshots carry both the declaration identity and the effective
   binding.

A **changed resolved endpoint or region** is a new effective identity: it
needs its own human approval and invalidates reuse of the old binding's
validation, mapping evidence and admitted measurements — identical candidate
bytes do not carry permission across endpoints. **Key/token rotation** with
an unchanged declaration and endpoint changes no identity and needs no new
approval: construct a new connection to pick up the new values; an existing
connection keeps the secret it was built with until it is closed (rotation
is not refreshed inside a live session). Restarting or reconstructing the
serving process is the pickup point for changed credentials.

A project without `storages:` keeps its existing grants, digests and gates
unchanged — profile-free registries and old records keep their existing shape
and digests. Profile declarations ride Git candidates with the same
effective-binding approval semantics through source approval, validation
evidence and human Git Review Admission; the legacy staging/Promotion route
they were once preserved through is retired (spec 0027's scoped amendment to
spec 0025 — only the staging-compatibility obligations lapsed, every
retained-format check stands).

## Know the remaining limits

- Scopes select credentials; they are **not** a per-source filesystem or
  network allowlist. Trusted view catalogs and Lakehouse tables keep
  operator responsibility for everything they reference: Ariadne does not
  analyze a lake's complete backing-resource inventory or freeze remote
  data.
- DuckLake reopens existing metadata catalogs and their recorded data paths
  read-only; Ariadne never creates a lake, replaces a catalog or overrides
  its recorded `DATA_PATH`. Iceberg is file-based; REST/OAuth catalogs and
  S3 Tables are out of scope.
- Extensions must already exist in the runtime (`httpfs` plus the format
  extension); Ariadne does not install them, and missing capability is an
  explicit refusal, not a fallback.
- HTTPS stays verified: no insecure fallback, and existing host CA
  configuration applies. Verifying your real endpoints' TLS, CA and IAM
  setup remains an operator task — the recorded runtime qualification was performed
  against signed loopback endpoints only.
