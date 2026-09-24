# Implementation plan: Harness-led authoring

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized; execution authorization still required** |
| **Goal** | Let an agent harness use its own model to onboard evidence and author a reviewed Seed Notes + OSI/OKF proposal locally or on one remote Ariadne server. |
| **Behavioral source** | [Harness-led authoring specification](../specs/2026-09-24-0005-harness-led-authoring.md), approved revision 2 by owner in pi session 2026-09-24; exact scope: source approval, evidence preparation, harness submission/checks, local CLI/skill, local stdio MCP, private bearer-token HTTP MCP, human-only Promotion. |
| **Plan approval** | Owner, pi session 2026-09-24: approved this five-slice execution map. The owner subsequently requested ticketization; GitHub issues #13–#17 now own the canonical task bodies. Neither approval nor ticket creation authorizes code changes, integration, publication, issue closure, or remote exposure. |
| **Decisions** | [ADR-0013](../adr/0013-harness-led-authoring-boundary.md); preserve ADR-0003's Promotion gate, ADR-0007's bundle structure with the scoped pending-attestation exception, ADR-0009's ordinary ingestion path, ADR-0012's local-first default. |
| **Contract / provenance** | planning-contract v1; installed skill provenance unknown. |

## Capture and prerequisites

- Vocabulary: `CONTEXT.md` distinguishes human-owned Seed Notes, pending Computation, and independently Attested Computation.
- Approved behavior: the linked specification owns interfaces, non-goals, failures, and acceptance; the tickets own execution. No unresolved owner decisions remain, but implementation and exposure need separate authorization.
- Runtime: Python ≥3.12, current DuckDB/sqlglot stack; `mcp>=1.2,<2` optional extra. Installed MCP 1.30.0 exposes `streamable-http` and `streamable_http_app()`. Before HTTP work, verify private-network HTTPS deployment and bearer-token request enforcement against the installed SDK; if unavailable, return to shaping. Conversion continues to require `[documents]`.
- Security boundary: authenticated remote inputs can request profiles and submit artifact contents. The source registry approval and final human Promotion remain out of agent-accessible MCP tools. Use one writer per project staging root; the slices are serial because they share authoring state. Local CLI and existing OpenAI-compatible authoring remain available.

## Canonical tickets

| Order | Issue | Deliverable | Depends on | Validation unit |
| :--- | :--- | :--- | :--- | :--- |
| 1 | [#13 — Approve sources before profiling](https://github.com/legout/ariadne/issues/13) | Inert source proposal → operator-approved registry → deterministic profile | Approved spec | S1 `new-test`, high-risk source boundary |
| 2 | [#14 — Prepare profile and document evidence](https://github.com/legout/ariadne/issues/14) | Server-linked converted documents, bounded upload/reference, harness inputs | #13 | S2 `new-test`, document-input boundary |
| 3 | [#15 — Validate and human-promote exact bundles](https://github.com/legout/ariadne/issues/15) | Harness submission, existing gates, digest/retries/review, Seed Notes and pending attestation | #14 | S3 `new-test`, high-risk Promotion boundary |
| 4 | [#16 — Stdio and private HTTP MCP](https://github.com/legout/ariadne/issues/16) | Local stdio parity, private HTTPS bearer token, first-run remote authoring | #15 | S4 `new-test`, high-risk authentication boundary |
| 5 | [#17 — Agent guidance and integrated acceptance](https://github.com/legout/ariadne/issues/17) | Packaged skill, local/remote examples, genuine harness smoke, global verification | #16 | S5 `existing-check`, candidate review |

Each issue owns its exact files, consumed/produced interfaces, non-goals, red/green or existing check, focused commands, and completion evidence. Do not maintain parallel editable task bodies here.

## Requirement coverage

| Spec acceptance | Tickets |
| :--- | :--- |
| 1 local profile, documents, repairs, no extra model endpoint | #13–#15, #17 |
| 2 remote S3/doc upload, token, server-side staging, local stdio | #13–#16 |
| 3 unsupported rules ask/flag, human review | #14–#15, #17 |
| 4 concurrency, retry, restart | #15 |
| 5 reviewed digest, human-only Promotion, honest attestation | #15–#17 |
| 6 old commands/query modes unchanged, base without MCP | #15–#17 |

#17 owns the integrated full-suite, Ruff, lock, live-harness, and real private HTTPS gates; #13, #15, and #16 require immediate boundary review before downstream work, followed by one candidate integration review. At most one owner-authorized fix pass and one delta recheck; report unavailable live provider or remote network as unverified, never passed. Integration, publication, issue closure, and remote exposure require separate owner authorization.

## Residual risks

A profile cannot prove a business rule; the human approves Seed Notes and Policy text. A bearer token behind private HTTPS is intentionally single-project/single-user. Private S3 credentials and network access must be verified on the actual server; local Delta and Parquet checks do not prove private S3 connectivity.
