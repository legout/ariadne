# Specification: Named S3 storage profiles

**Accepted scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; the owner approved the complete written revision and these scoped amendments with “Schriftliche Fassung freigeben (Recommended)”. Named scoped profiles, secret isolation, effective-endpoint Source Approval, all retained formats and evidence/admission checks remain; only the former legacy-staging compatibility obligations retire. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1** |
| **Approval** | Owner, Pi conversation 2026-10-14: requested “shape design, dann implementierungsplan und tickets”; selected unique S3 paths across endpoints, process-environment values rather than an Ariadne environment-file loader, and inclusion of Lakehouse sources. Approved the complete in-chat design with “Design freigeben (Recommended)”, then this complete written revision with “Schriftliche Fassung freigeben (Recommended)”. Approval covers revision 1, implementation planning and GitHub ticketization; not implementation, source access, target integration, code/document commit/push, deployment or release. |
| **Scope** | Named environment-reference S3 Storage Profiles in the existing shared DuckDB connection; file/native and existing Lakehouse source consumers; inert proposal parity; effective-endpoint Source Approval; credential-free validation/evidence/admission bindings; documentation. |
| **Sources** | [Vocabulary](../../CONTEXT.md), [ADR-0010](../adr/0010-declarative-source-registry.md), [ADR-0023](../adr/0023-named-scoped-s3-storage-profiles.md), [Git authoring specification 0009](2026-10-02-0009-modular-core-git-authoring.md), [schema/evidence specification 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md), [native source specification 0022](2026-10-13-0022-native-duckdb-sources.md), [research evidence](../research/2026-10-14-multi-s3-scoped-secrets.md). |
| **Contract** | planning-contract v1; installed shaping/planning skill provenance unknown. |

## 1. Goal and boundaries

Read independently configured S3-compatible storages through one Ariadne DuckDB connection. Keep registry artifacts portable and credential-free: a Storage Profile names environment variables, while the executing host supplies their values. One profile can serve several sources. A source alias does not select DuckDB credentials; explicit, non-intersecting URI scopes do.

The owner chose unique S3 paths across endpoints. Refuse ambiguous assignments rather than inventing virtual URI rewriting, separate execution engines or an implicit credential fallback. Preserve human Source Approval, read-only Query, compile/source/grain gates and Git Review Admission versus Promotion.

In scope: existing `csv`, `json`, `parquet`, `duckdb`, `delta`, `iceberg` and `ducklake` source types. Iceberg remains file-based `iceberg_scan`; DuckLake reopens existing metadata catalogs and their recorded data paths. Local native catalogs and local DuckLake metadata may use profiles for S3 backing files.

Non-goals: new connectors; Iceberg REST/OAuth catalogs or S3 Tables; creating lakes or overriding their data paths; ETL or remote writes; duplicate S3 paths on distinct endpoints; AWS credential chains, IAM/SSO or a credential vault; automatic `.env` loading or new environment-file CLI flags; a backing-resource sandbox; production deployment, version/dependency bumps or release. PostgreSQL's existing `connection_env` and other profile-free source behavior remain unchanged.

## 2. Registry contract

Add optional top-level `storages`, a mapping from lowercase source-style slugs to strictly validated S3 profile definitions. Add optional `storage` to supported source entries. Names are references, not credentials or URI aliases.

```yaml
storages:
  local:
    type: s3
    access_key_id_env: LOCAL_S3_ACCESS_KEY_ID
    secret_access_key_env: LOCAL_S3_SECRET_ACCESS_KEY
    endpoint_url_env: LOCAL_S3_ENDPOINT_URL
    region_env: LOCAL_S3_REGION
    # session_token_env: LOCAL_S3_SESSION_TOKEN
    url_style: path
    scopes:
      - s3://retail/
  remote:
    type: s3
    access_key_id_env: REMOTE_S3_ACCESS_KEY_ID
    secret_access_key_env: REMOTE_S3_SECRET_ACCESS_KEY
    endpoint_url_env: REMOTE_S3_ENDPOINT_URL
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

### Profile fields

| Field | Contract |
| :--- | :--- |
| `type` | Required; exactly `s3`. |
| `access_key_id_env`, `secret_access_key_env` | Required environment-variable names. Values are read only for authorized connection setup. |
| `endpoint_url_env` | Required environment-variable name containing an absolute HTTP(S) endpoint URL. Its value is non-secret connection identity, not an inline registry URL. |
| `region_env` | Optional environment-variable name. If omitted, use explicit `us-east-1`; do not inherit another profile's/global region. If declared but unset/blank, refuse. |
| `session_token_env` | Optional environment-variable name; if declared but unset/blank, refuse. No automatic token refresh. |
| `url_style` | Optional `path` or `vhost`; default `path` for named profiles. |
| `scopes` | Required nonempty list of unique, literal `s3://bucket/` or directory-prefix URIs ending in `/`. Case-sensitive object paths; no credentials, globs, query, fragment or dot-segment navigation. |

Environment references must be identifiers, not substitutions, connection strings or assignment expressions. Reject unknown fields and inline credentials without echoing their values. Canonical profile representation is deterministic; YAML key ordering does not change identity.

Validate all declarations without reading credential values or opening a source. Only profiles referenced by sources are resolved/installed for execution; unused definitions require no environment values and create no secrets. Profile/source declarations are not permission to access them.

### Source assignment and scopes

- A declared `storage` must resolve and may be used only by the seven supported source types above. SQLite/PostgreSQL cannot take this field.
- A directly declared S3 source must use `s3://` and fall inside at least one scope of its selected profile. New profile-based routes explicitly refuse `s3a://`/`s3n://` rather than relying on extension-specific alias behavior. Existing profile-free URI handling is not silently rewritten.
- A source with a local metadata/catalog path may reference a profile for its remote backing data. Its metadata path keeps existing registry/project-root resolution.
- Used profiles must have non-intersecting scopes across different profile names: equality or either prefix containing the other refuses, even if the endpoint values happen to match. Same-profile scopes have one credential identity.
- A directly declared profile-free S3 path that would fall under an installed named profile also refuses: it must explicitly select that profile. Otherwise installation would silently change the legacy source's credential selection.
- Scopes are credential-selection prefixes, not a per-source filesystem/network allowlist. Trusted views and Lakehouse metadata retain operator responsibility for their backing resources; this feature does not analyze every transitive access.

## 3. Environment and connection lifecycle

Read values from the executing process. Shell, MCP launcher or a Docker `env_file`/`environment` configuration may populate that environment. Do not search the cwd, worktree, admitted snapshot or project for `.env`, and do not expose a model-controlled environment-file path. Existing author/ingest LLM-environment behavior is not expanded into a universal source loader.

Endpoint resolution accepts `http://` or `https://`, a host and optional valid port, and an empty/root path only. Reject userinfo, query, fragment and non-root base paths. Canonicalize the scheme/host and equivalent default ports; preserve the resulting endpoint identity. Derive DuckDB `ENDPOINT` from host/port and `USE_SSL` from the scheme. HTTPS does not trigger an insecure fallback; certificate verification remains enabled and existing host CA configuration remains applicable.

For an authorized setup, resolve/freeze the effective non-secret binding once for that operation. Resolve credential values for each used profile, load the needed existing extensions, and create one temporary `TYPE s3, PROVIDER config` secret per used profile with its scopes. Do this before any source ATTACH/view binding. One profile is installed once even when several sources use it.

Secret creation belongs in the shared connection builder, not in Query/CLI/MCP-specific implementations. Public `plan` output remains a credential-free extension/source-DDL plan; never put resolved secret-creation SQL into it. Registry objects, temporary validation registries, audits, reports, proposals and admission artifacts must not serialize key/token values.

All source setup, including secret creation, stays inside the existing deadline/cancellation ownership. Missing variables, secret/extension setup errors or failed source bindings refuse explicitly and close the incomplete connection. Never return a partly ready catalog, retry with another profile/global provider, or clear operator state. Preserve credential redaction, including library errors that echo SQL and chained error output; report variable/profile identity, not secret contents. Ariadne-managed logs/results must not carry credentials.

Secret lifetime is connection lifetime. Key/token rotation is picked up by a newly constructed connection, not promised as automatic refresh within an existing session. Closing the connection leaves no persistent DuckDB secret file.

## 4. Source Approval and exact effective identity

Preserve offline source declaration and inspection. Missing credential or endpoint values must not prevent a valid inert proposal, source-independent discovery or status report.

Distinguish the registry declaration from its effective storage binding:

1. `source_digest` continues to identify canonical host-root-resolved source declarations. For profile-based sources it includes each complete referenced profile definition, including variable names and scopes, but no resolved key/token/endpoint values. Profile-free identities/digests retain their existing representation.
2. `storage_bindings` identifies the used profiles' canonical resolved endpoints, region, URL style and scopes. It contains no key IDs, secret keys or session tokens.
3. `approval_digest` identifies the declared source identity together with these effective non-secret bindings. For a registry without named profiles it equals its existing source digest, preserving old grants. For named profiles, a changed effective binding produces a different approval identity.

The existing human-only `approve-sources` receives the exact revision and declaration/source digest. On the operator host it resolves endpoint/region variables without making network calls or reading key/token values, and records the effective identity in the existing ignored approval state. Return the declaration digest, effective approval digest and reviewed non-secret bindings. This remains an explicit local human permission for the host-supplied endpoints; no agent or MCP tool can perform it.

Key grants by effective identity; retain other grants rather than overwriting the old endpoint's grant when the same declaration is approved for a new endpoint. Do not invent a second approval store or lifecycle.

Before measured inputs, schema refresh, mapping inspection, validation or a managed runtime opens sources, resolve the effective binding and require the exact matching grant. After validation, store and verify both declaration identity and complete effective binding/digest in existing evidence and admission records. A pinned admitted snapshot cannot substitute a mutable registry, select a newer grant or fall back to unbound files.

Freeze the matched binding through approved-registry reconstruction and builder setup; do not check one endpoint and then open a newly re-resolved endpoint. An existing connection remains bound to its setup identity; later connection construction compares the current environment with the pinned grant.

### Changes and evidence

- Changing a profile reference, variable name, scope or option changes the declaration and requires normal exact-revision review/approval.
- Changing the resolved endpoint or region changes the effective identity, needs a matching human Source Approval, and invalidates validation/admission reuse and applicable measured evidence from the old binding.
- Rotating key/token values with the same declaration and effective binding does not change source identity or require new Source Approval. New connections use the new values; missing/invalid credentials still fail setup.
- Validation cache/idempotency keys, repair accounting, Mapping Evidence receipts and selected-value/schema measurement dependencies must bind the effective identity as well as the declaration. Matching candidate bytes alone must not reuse old-endpoint evidence.
- Old profile-free grants, evidence and admitted records remain valid under their existing checks. Do not globally invalidate or silently migrate them.
- Existing profile-free canonical table/collection resources remain unchanged. Profile-based canonical resources retain source/catalog/schema/table identity; transport binding is provenance, not an endpoint/credential encoded into a resource URI.

Offline status/review may report declaration approval history, but must label an unresolved or changed effective binding as unchecked/not-current. It must not claim that an endpoint is currently approved merely because a declaration digest has a historical grant. Missing runtime variables are a visible prerequisite, not a corrupt source declaration. No credential reads are needed for this inspection.

This section is the scoped extension of spec 0009's complete Source Approval/evidence contract; it does not weaken its exact revision, no-fallback or human admission requirements.

## 5. Proposal and adapter parity

Extend existing Git `propose_sources` with optional `storages` definitions alongside source entries, consistently through `AuthoringProject`, CLI, MCP and the Native Authoring Agent. Existing callers omitting the argument keep working; an existing candidate profile can be referenced without resending it.

Use the same revision-checked candidate edit. Source names remain append-only. New profiles append; an identical existing profile may be reused, but an attempted conflicting replacement refuses. Validate the whole merged candidate before committing it. No environment value, source opening or approval occurs during proposal creation. Preserve unrelated project configuration.

The CLI's existing registry-shaped source input can carry both top-level blocks. Do not add a separate storage CRUD tool or an approval capability. Update Native Agent argument schemas/forwarding to the real registry fields, rather than providing a source-specific credential shortcut.

Retained legacy source-file proposal/approval and staged-bundle submission/Promotion must preserve profile definitions and bind profile configuration/effective identity where source-dependent validation is used. Do not drop `storages` on installation/materialization, hash only a reference name, or accidentally grant the Git route's capabilities to the legacy route. Existing legacy human gates stay distinct.

Setup's inert declaration validation must understand references to already declared profiles and keep filename detection non-opening. A new interactive credential/storage wizard is not required. All workflows consume shared registry/binding behavior; no adapter-specific secret logic.

## 6. Lakehouse support and compatibility evidence

Delta must receive the selected secret in its actual scan engine, not merely a secret installed in DuckDB but ignored by the extension. Iceberg covers the existing file-based scan and its metadata/data object reads. DuckLake covers existing metadata attachment plus remote data-path reads; its metadata credentials and existing source declaration are separate from the S3 data profile.

Explicit scopes cover the required metadata/data prefixes. Do not infer a lake's complete backing-resource inventory, change its DATA_PATH, create a replacement catalog or loosen read-only/source authority to make a test pass.

Use actual installed extension capabilities. Upstream documentation/source are feasibility evidence, not proof of installed compatibility. Missing required extensions or a failing supported-format scenario block the affected implementation acceptance; do not silently remove the owner-selected source types, replace live reads with statement assertions, or claim every historically permitted DuckDB version is compatible. Any necessary dependency/version change returns to the owner.

No implicit extension installation is introduced into Ariadne. Implementation test environments may be prepared explicitly under their execution authorization. Production endpoint/credential/TLS checks remain separately operator-authorized.

## 7. Observable acceptance criteria

1. **AC1 — Declarative profiles:** the example parses as credential-free registry data, references are reusable, and unknown fields/types/variables-as-values, missing references, unsafe scopes and direct-path/profile mismatches refuse. Parsing and proposal creation work without any runtime environment values or network access.
2. **AC2 — Independent routing:** in one shared connection, two loopback S3-compatible endpoints require distinct synthetic credentials and expose distinct known datasets under disjoint scopes. Registered sources read the correct endpoint/data; at least one normal compiled Ariadne query uses them. A credential-routing failure cannot be hidden by global AWS credentials.
3. **AC3 — Selection refusal:** equal or nested scopes of different used profiles, and profile-free direct sources that would accidentally inherit a named secret, refuse before any source request. Unused profiles cause no credential lookup/secret installation.
4. **AC4 — Lifecycle and confidentiality:** temporary secrets exist only in the owned session; key/token values never appear in public plans, Git artifacts, approval/evidence/admission records, tool responses or Ariadne-managed error output. Missing variables and forced secret/source setup failures close/refuse the incomplete session. Existing setup deadlines/read-only rules remain effective.
5. **AC5 — Human effective approval:** a valid proposal opens nothing. Human approval binds the resolved endpoint without credentials. Changing endpoint A to B, while retaining identical candidate bytes, refuses measured reads/managed startup until B receives its own grant; A's grant remains intact. Credential-value rotation at the same binding needs no new approval.
6. **AC6 — Evidence and serving:** validation, mapping/measurement evidence and admission cannot reuse A's binding for B. Approved registry materialization/reconstruction preserves profiles and the frozen binding. Managed serving uses its pinned complete identity; offline status does not require credentials or falsely imply current effective approval.
7. **AC7 — Shared adapters and legacy:** CLI/MCP/Native Agent accept the same optional definitions/references and retain fixed roles and human-only approval. Legacy proposal installation, staged validation and Promotion preserve both blocks/bindings. Existing calls, profile-free source digests/grants, SQLite shorthand and PostgreSQL checks pass unchanged.
8. **AC8 — Lakehouse reads:** real loopback S3-backed Delta, file-based Iceberg and existing DuckLake fixtures read independently specified data using the selected profiles, including a local DuckLake metadata catalog with remote data files. Exercise distinct endpoint/credential routing in the format matrix; record actual runtime/extension versions. Missing capability or a skipped required case is not a pass.
9. **AC9 — Honest guidance:** source reference/how-to/templates/packaged agent guidance show variable references, explicit scopes, process/Docker environment delivery, rotation/restart behavior and human gates. They distinguish this candidate feature from published 0.3.0 and live loopback evidence from production TLS/S3 verification.

Validation obligations: focused `new-test` for routing/refusal/secret lifecycle and for endpoint-bound approval/evidence; real S3-compatible reads for AC2/AC8. Expected rows/authentication outcomes come from independent fixtures, not implementation output. Use existing source/grain/read-only/deadline/role and legacy checks for preserved behavior. Documentation uses `no-new-test` plus existing parse/link/CLI checks. Detailed tasks and focused commands belong to the implementation tickets, not a duplicate task list here.

## 8. Capture checkpoint and handoff

- **Vocabulary:** Storage Profile is captured in the owning root glossary. It is access configuration, not a data source, a Semantic Layer model or Source Approval.
- **Decisions:** ADR-0023 records one shared connection with named scoped environment-reference profiles versus per-source duplication/separate connections. ADR-0010 is explicitly extended; trusted-catalog responsibility in ADR-0022 remains unchanged.
- **Behavior:** the owner approved the complete in-chat design and this written revision 1; it is the behavioral source for the requested implementation planning/GitHub ticketization. No implementation authority follows.
- **Uncertainty:** unique paths and process-only environment delivery are settled. Installed extension compatibility remains an explicit implementation verification obligation, not an unresolved choice to shrink scope. No runtime/deployment success is claimed.
- **Handoff:** planning-contract v1; installed skill provenance unknown. Prepare a thin two-unit plan and canonical GitHub tickets from this approved source. Execution, source access, target integration and publication retain separate authorization.
