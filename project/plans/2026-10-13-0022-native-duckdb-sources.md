# Implementation overview: Native DuckDB sources and trusted view catalogs

| | |
| :--- | :--- |
| **Status** | **Proposed, revision 1 — ticketized; execution approval pending** |
| **Goal** | Deliver native local/HTTPS/S3 DuckDB tables and resolvable views through the existing registry/shared builder, without new execution authority. |
| **Behavioral source** | [Specification 0022](../specs/2026-10-13-0022-native-duckdb-sources.md), **Approved, revision 1**, and [accepted ADR-0022](../adr/0022-trusted-native-duckdb-catalogs.md). Owner's “approved.” in the Pi conversation 2026-10-13 covers the written behavior; tickets own task decomposition. |
| **Ticketization authority** | Owner's “Ticketize erst”, same Pi conversation 2026-10-13: create the two tickets and move task bodies out of the plans. This does not approve execution, target integration, source access or publication of code/docs. |
| **Canonical task** | [#67 — N1: Native DuckDB and trusted HTTPS/S3 view catalogs](https://github.com/legout/ariadne/issues/67). Owned files, checkbox steps, interfaces, validation cases/oracles, focused commands and completion criteria live only in the issue. |
| **Capture checkpoint** | Specification §7: existing Source Approval/Schema Observation/governance vocabulary suffices; ADR-0022 owns the trusted-catalog choice. No unresolved material scope choice; remote compatibility remains a real verification obligation. |
| **Contract** | planning-contract v1; installed planning/orchestration skill provenance unknown. |

## Coverage and order

| Source acceptance | Canonical unit |
| :--- | :--- |
| Spec 0022 AC1–AC8 | [#67, N1](https://github.com/legout/ariadne/issues/67), including `new-test`, `existing-check` and docs `no-new-test` obligations |

Proposed sequence: **[#66](https://github.com/legout/ariadne/issues/66) → #67**. N1 consumes V1's parent-accepted committed result to avoid overlapping `README.md` writes; there is no semantic runtime dependency. A separately approved N1-only run uses its own approved clean base. Issue closure alone is not acceptance or authority. Do not maintain another editable copy of N1's task body here.

## Shared constraints and delivery

Follow [overview 0021](2026-10-13-0021-verbatim-document-ingestion.md)'s shared host/source/baseline preflight, global core/lint checks, review budget and supervised delivery boundary. The task's exact source digests and historical pre-transfer plan digest are recorded in #67. The source documents remain local/uncommitted; no matching committed GitHub blob link is claimed. No code/docs commit, push or worker launch follows merely from ticketization.

Only operator-reviewed trusted catalogs and permitted backing-data accesses are in scope. Source declaration/read-only attach grants no Source Approval, sandbox, snapshot or metric governance. Use existing runtime credentials and bounded shared setup; no implicit extension install, new backend/version/dependency, transitive resource allowlist, catalog publishing or raw-SQL route.

The required real range-capable loopback catalog/backing-data check must pass on the actual runtime; recorded statements or a skipped fixture cannot substitute for it. Required capability failure blocks. Authenticated HTTPS/S3 endpoints, credentials/CA behavior and real agent usefulness remain unverified until separately authorized operator checks. Do not silently reduce remote scope or claim deployment validation.

Preserve human gates and existing source identities, compile/grain/read-only checks, error redaction and cancellation. Target integration, publication, issue closure and resource cleanup are separately gated. The issue owns detailed implementation and verification; this overview remains the coordination/source map only.
