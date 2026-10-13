# Specification: Native DuckDB sources and trusted view catalogs

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1** |
| **Approved design direction** | Owner, Pi conversation 2026-10-13: add native DuckDB sources; explicitly select local plus HTTPS/S3 catalog files, and operator-reviewed trusted catalogs rather than a new technical backing-resource allowlist. The owner requested written `shape-design` capture before implementation. |
| **Approval** | Owner, this Pi conversation 2026-10-13: “approved.” in response to the written specifications 0021 and 0022 and ADR-0022. Approval covers the complete revision-1 behavior and proceeding to implementation planning; it does not approve unseen plans, source access, target integration or publication. |
| **Scope** | `type: duckdb` in the existing source registry/shared connection builder; native tables and resolvable views, complete catalog identities, default read-only operation, remote catalog prerequisites and filename-only setup hints. |
| **Decision** | [ADR-0022: trusted native DuckDB catalogs](../adr/0022-trusted-native-duckdb-catalogs.md) |
| **Existing contracts** | [ADR-0010](../adr/0010-declarative-source-registry.md), [MVP acceptance example 20](./mvp-vertical-slice.md), [Git authoring 0009](./2026-10-02-0009-modular-core-git-authoring.md), [Context/resource identities 0010](./2026-10-02-0010-context-layer-schema-and-identifiers.md), [bounded execution 0014](./2026-10-08-0014-bounded-record-queries-and-results.md), [setup 0017](2026-10-12-0017-setup-onboarding-wizard.md), [vocabulary](../../CONTEXT.md) |
| **Evidence** | [research and owner follow-up](../research/2026-10-13-ktx-gaps-after-usability.md), [`sources.py`](../../src/ariadne/sources.py) at `a8d24b18d16854058e6b2b97bd1801cb0687ffbd`, [DuckDB view-catalog blog](https://duckdb.org/2026/10/07/view-only-mode) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## 1. Purpose, scope and non-goals

Use an existing native DuckDB database without exporting its tables. Also support an operator-controlled DuckDB file containing only views over separately stored data, including remote Parquet. This is another declared source type, not another execution engine or Semantic Layer.

In scope: registry parsing/validation and source identity, the one shared builder used by execution/profiling/validation/authoring, local files and HTTPS/S3 catalogs, native schemas/tables/views, existing query/compile and source-approval boundaries, documentation and the existing filename-only setup hint for `.duckdb`.

Non-goals: database creation or writes through Ariadne's Query surface, building/publishing view catalogs, automatic source discovery/approval, catalog download/replication or snapshot management, SQL-history ingestion, a Lance/LanceDB connector, unknown/untrusted catalog execution, a technical sandbox or new per-view backing-resource allowlist, another backend/plugin abstraction, arbitrary extension installation, and changes to governed metric semantics.

## 2. Registry and shared execution interface

```yaml
sources:
  - name: warehouse
    type: duckdb
    path: data/warehouse.duckdb
    read_only: true
  - name: rail
    type: duckdb
    path: https://example.com/rail_catalog.duckdb
    read_only: true
  - name: lake_views
    type: duckdb
    path: s3://operator-bucket/catalog.duckdb
    read_only: true
```

These are illustrative declarations, not permission to open their locations. No source is created, opened or approved merely by parsing or proposing the registry.

The new type uses the existing `path`/`name`/`read_only` conventions and source-key validation. Local relative paths resolve against the existing configured project/registry base, not an incidental working directory. Catalog aliases remain validated slugs. Globs are refused for database files; native table/schema names come from the catalog, not a `table:`-derived file view. No new credential field is introduced.

The shared builder emits a native attach, without a SQLite/DuckLake/Postgres scanner:

```sql
ATTACH '/resolved/data/warehouse.duckdb' AS warehouse (READ_ONLY);
```

The default is read-only under the existing registry/builder policy. An explicit operator configuration cannot turn a Query operation into a write operation; compiler, source-authority, single-statement, bind and read-only execution checks remain binding. Remote catalogs always attach read-only; a requested writable remote attach is an explicit refusal, not a fallback.

HTTPS/S3 catalog setup uses the existing `httpfs` extension mechanism before attach, deduplicated with other sources. Local native tables do not acquire a network-extension requirement merely because the source type is DuckDB. A local catalog whose views read remote data may require the existing DuckDB extension/credential prerequisites; this is documented and failures are explicit. Catalog SQL is not rewritten to fix paths or synthesize unavailable dependencies.

Missing files, unsupported database versions, unavailable extensions, absent permissions/credentials and broken view bindings fail through the existing source-setup boundary. Setup closes its incomplete connection and cannot return a partially ready session. Existing deadlines/cancellation and error-redaction contracts remain in force. Neither a failed native attach nor ambiguous file content falls back to SQLite or a file reader.

`--db` remains the legacy SQLite shorthand. A native file is selected explicitly by a `type: duckdb` entry; there is no content sniffing or silent reinterpretation of `.db` files.

## 3. Catalog identity and consumers

Native DuckDB is an attached catalog, not an in-memory file-view schema. Catalog entries retain the complete `(source, catalog, schema, table)` identity and existing canonical `ariadne://table/...` / collection resources. A native source's catalog is its stable registered alias, not the file's incidental basename or worktree path.

Enumerate its user schemas and cheaply discoverable table/view columns through the existing catalog path. Same-named relations in different schemas stay distinct. In a mixed registry, a native schema with the same name as another file-view source must not cause either source to claim the other's tables or identities.

Profiling, schema refresh, validation, dataset discovery and both governed/ad-hoc execution consume the same builder/catalog. A new source-specific connection path, profiler or compiler is not introduced. The existing source/grain checks apply to the relation exposed by the view; catalog existence alone proves no business key, cardinality or correctness.

## 4. Trusted view catalogs and access

The selected first version supports only catalogs expressly chosen by the operator as trustworthy, including their executable view definitions and intended backing-data accesses. A caller cannot turn a newly mentioned URL, document link, uploaded database or proposed registry entry into approved source access.

On managed projects the existing exact source approval is still required before connecting. Worktree placement cannot retarget that identity. The operator must establish that both the catalog and the locations its views reference are permitted under the project's existing access rules and credential capabilities. Catalog trust does not override a configured document root or exact object-store restriction, and agents cannot grant the missing permission.

This is a **trusted-source contract**, not a claim that Ariadne mechanically discovers and sandboxes every transitive dependency inside arbitrary DuckDB SQL. Use of an unknown catalog requiring such a guarantee is refused/out of scope until a separately designed inspection/enforcement mechanism exists. The user-facing source guidance must disclose that views can perform backing-data reads during binding/inspection as well as querying; read-only attaches do not provide filesystem/network isolation.

Credentials stay outside committed registries and catalog SQL, under the existing operator-managed runtime mechanisms. Remote readers need access to both catalog and referenced data; attaching one URL does not create credentials or copy backing objects. Source configuration never becomes agent-managed secret provisioning.

Views use current backing data. `READ_ONLY` protects against changing the attached database; it neither freezes external data nor proves privacy isolation, Freshness, Independent Numerical Validation or human artifact admission. Fully qualified URLs/absolute backing paths are the publisher's responsibility; relative view paths may fail or resolve differently with the client's working directory and are not silently repaired.

A source view is not a governed Ariadne metric. Only the existing human-admitted Semantic Layer definition establishes governed status. Query requests still pass the ordinary compiler/authority path; no raw-SQL execution tool or direct query-replay route is exposed.

## 5. Setup, public guidance and migration

- Add the new type to supported-source documentation and any existing registry templates/type listings that enumerate supported types. Show a local database and a trusted remote view catalog with prerequisites and explicit governance limits.
- Extend the current filename-only setup hints with `*.duckdb` as a proposed `duckdb` type. Detection reads no database content, binds no view, makes no network call, accepts no source declaration by itself and grants no approval. Existing `.db`/`.sqlite` hints retain their meanings.
- Preserve normal typed source proposals, human Source Approval and admission; no new wizard step or source-opening shortcut is added.
- Existing source registries, metrics, resource identities and SQLite `--db` callers need no migration. Their behavior stays unchanged.
- Do not describe an unreleased source type as available in the currently published package. Installed-candidate verification and any release/publication are separate actions.

## 6. Observable acceptance criteria

1. A local DuckDB fixture declared with `type: duckdb` opens through the shared builder. Native tables and a resolvable view are queryable under the configured catalog alias, with independently specified fixture rows and column identities. A default connection refuses writes to the attached file.
2. Two same-named relations in different native schemas remain distinct canonical assets. A native schema whose name matches a second CSV/Parquet source does not contaminate that other source's inventory; source/catalog/schema identity remains exact.
3. Local relative paths resolve against the correct registry/project root from another working directory. Unknown type, invalid alias, database glob, quote-bearing literal and missing file follow existing explicit refusal rules; no fallback source opens.
4. HTTPS and S3 entries construct the required deduplicated extension-load/native-read-only-attach sequence. Writable remote requests refuse. A real HTTP(S) range-capable catalog fixture can expose a view and query its separately hosted backing data with independently known values when the extension/runtime prerequisites are available.
5. Source setup without its required remote access, extension or backing resource fails explicitly and closes the incomplete connection. There is no partial ready catalog, writable remote retry, new credential serialization or bypass of execution deadlines.
6. On a managed project, proposing a native catalog entry still opens nothing before the operator's existing approval. Setup suggests `.duckdb` from filenames only and does not inspect local catalog bytes or remote resources. Trusted catalog/backing-access responsibility is explicitly disclosed, not represented as an implemented sandbox.
7. Existing registered-source and SQLite shorthand checks pass unchanged. At least one compiled Ariadne query uses the native fixture through the normal execution seam, preserving governed/ad-hoc labeling and current source/grain guards rather than executing caller-supplied SQL directly.
8. Source documentation/templates describe the actual supported native/remote behavior and limits without introducing a new engine, implicit trust, admission, snapshot or release claim.

Validation obligations: `new-test` for native table/view/catalog/read-only behavior using local DuckDB fixtures and independent expected values; `new-test` for remote setup/read-only and a focused local range-capable HTTP(S) integration scenario. Existing registered-source, setup, source-approval and compiled-query checks provide `existing-check` coverage for preserved boundaries. Authenticated S3/HTTPS deployment checks require real operator-approved endpoints/credentials; missing prerequisites are reported as unverified, not converted into a live-success claim. No new recorded-agent-trace suite is added.

## 7. Capture checkpoint and handoff

- **Vocabulary:** Source Approval, Schema Observation, Governed Metric and Freshness already express the boundary; no database-format glossary entry is needed.
- **Decisions:** ADR-0022 captures the selected trusted-catalog scope versus a new backing-resource sandbox. ADR-0010's shared registry/builder remains authoritative. This is a scoped connector addition to spec 0009's original new-connector non-goal, not approval for additional connectors or another backend.
- **Behavior:** the owner approved this complete written revision-1 source, catalog, trust, compatibility and acceptance contract with “approved.” in this Pi conversation on 2026-10-13. Spec 0017's filename list is extended only by the inert `.duckdb` hint; its no-access/no-approval rules stay unchanged. Execution decomposition belongs to [plan 0022](../plans/2026-10-13-0022-native-duckdb-sources.md).
- **Uncertainty:** the owner selected trusted catalogs; no technical sandbox guarantee is implied. Concrete remote compatibility still needs the stated integration evidence. Plan approval/readiness precedes writer dispatch; source permissions, actual endpoint credentials, integration and publication retain their own gates.
