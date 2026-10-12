# Implementation plan: Harness-led authoring

| | |
| :--- | :--- |
| **Status** | **Approved — workflow amendment 2026-10-07; local #13–#17 closed, #18 local transport implemented, remote deployment blocked** |
| **Workflow migration approval** | Owner requested “can you execute the recommende migration for me?” in Pi session `01a115c0-1a8b-7099-87c3-df0aa8d87abc`, 2026-10-07: update progress, remaining #18 scope and workflow handoff only. No new transport behavior, endpoint/proxy selection, feature implementation, exposure, commits/pushes or release is authorized. |
| **Goal** | Let an agent harness use its own model to onboard evidence and author a reviewed Seed Notes + OSI/OKF proposal locally or on one remote Ariadne server. |
| **Behavioral source** | [Harness-led authoring specification](../specs/2026-09-24-0005-harness-led-authoring.md), approved revision 2 by owner in pi session 2026-09-24; exact scope: source approval, evidence preparation, harness submission/checks, local CLI/skill, local stdio MCP, private bearer-token HTTP MCP, human-only Promotion. |
| **Plan approval** | Owner, pi session 2026-09-24: approved the original five-slice map. Owner, pi session 2026-09-25: split the remaining work into local stdio #16, local guidance/acceptance #17, and new private HTTP/deployment #18. GitHub issues #13–#18 own the canonical task bodies. This decomposition approval does not authorize implementation, integration, publication, issue closure, or remote exposure. |
| **Decisions** | [ADR-0013](../adr/0013-harness-led-authoring-boundary.md); preserve ADR-0003's Promotion gate, ADR-0007's bundle structure with the scoped pending-attestation exception, ADR-0009's ordinary ingestion path, ADR-0012's local-first default. |
| **Contract / provenance** | planning-contract v1; installed skill provenance unknown. |

## Scoped execution update — 2026-10-10

The owner approved the bounded Compose-bind and authenticated probes in
[specification 0005's HTTP extension](../specs/2026-09-24-0005-harness-led-authoring.md#scoped-http-extension--owner-approved-2026-10-10).
Owned surfaces: `src/ariadne/serve.py`, focused HTTP checks in
`tests/test_authoring_mcp.py`, README and packaged MCP guidance. Direct parent
implementation; new-test for the bind/probe/Host-Origin behavior, existing-check
for MCP parity. No additional MCP feature, deployment, release or publication.
This extends the historical loopback-only implementation; #18's actual remote
HTTPS/source acceptance remains open and separately gated.

## Container preparation update — 2026-10-10

Source: [0005's approved packaging scope](../specs/2026-09-24-0005-harness-led-authoring.md#container-packaging--owner-approved-2026-10-10).
Direct parent implementation of `Dockerfile`, `.dockerignore`, `compose.yaml`,
`compose.loopback.yaml`, `.env.example` and the operator how-to/README link.
One `new-test` unit: build an image and run a real, isolated network MCP client
against a disposable same-path external Git project; assert bearer probes,
non-root/matching ownership, host Git worktree usability, proposal persistence
on container recreation and no admission. Default/loopback Compose resolution
and existing HTTP/authoring checks are `existing-check`. No server/skill change,
proxy deployment, image publication, release, commit or push is authorized.

## Capture and prerequisites

- Vocabulary: `CONTEXT.md` distinguishes human-owned Seed Notes, pending Computation, and independently Attested Computation.
- Approved behavior: the linked specification and its scoped 0009/0010 amendments own local/remote interfaces and acceptance. #13–#17 are closed. Commit `e178200` implements #18's opt-in loopback-only bearer HTTP and current Git authoring/query toolsets; its issue comment records local auth/transport checks and review, not a deployed private HTTPS service. Remaining #18 work is deployment selection, approved private HTTPS exposure, server/source prerequisites, remote guidance and actual remote-client evidence. Reuse local checks; do not reimplement settled transport or resurrect the superseded full-bundle route for a Git-managed project.
- Runtime: Python ≥3.12, current DuckDB/sqlglot stack; `mcp>=1.2,<2` optional extra for stdio. The installed MCP 1.30.0 exposes `streamable-http` and `streamable_http_app()`, but #18 must verify the selected private-network HTTPS deployment and bearer-token request enforcement against the installed SDK before HTTP work/exposure. If unavailable, return to shaping. Conversion continues to require `[documents]`.
- Security boundary: local stdio uses the configured project without an HTTP token; authenticated remote inputs in #18 may request profiles and submit artifact contents. Source approval and final human Promotion remain out of agent-accessible MCP tools. Use one writer per project staging root; slices remain serial. Local CLI and existing OpenAI-compatible authoring remain available.

## Canonical tickets

| Order | Issue | Deliverable | Depends on | Validation unit |
| :--- | :--- | :--- | :--- | :--- |
| 1 | [#13 — Approve sources before profiling](https://github.com/legout/ariadne/issues/13) | Inert source proposal → operator-approved registry → deterministic profile | Approved spec | S1 `new-test`, high-risk source boundary |
| 2 | [#14 — Prepare profile and document evidence](https://github.com/legout/ariadne/issues/14) | Server-linked converted documents, bounded upload/reference, harness inputs | #13 | S2 `new-test`, document-input boundary |
| 3 | [#15 — Validate and human-promote exact bundles](https://github.com/legout/ariadne/issues/15) | Harness submission, existing gates, digest/retries/review, Seed Notes and pending attestation | #14 | S3 `new-test`, high-risk Promotion boundary |
| 4 | [#16 — Local stdio authoring MCP](https://github.com/legout/ariadne/issues/16) | Local stdio parity, first-run authoring, five legacy query tools preserved; no HTTP token or endpoint | #15 | S4 `new-test`, local tool boundary |
| 5 | [#17 — Local agent guidance and acceptance](https://github.com/legout/ariadne/issues/17) | Packaged local skill/CLI/stdio examples, genuine local harness smoke, local integration checks | #16 | S5 `existing-check`, local candidate review |
| 6 | [#18 — Private HTTPS MCP transport and deployment](https://github.com/legout/ariadne/issues/18) | Remaining approved HTTPS deployment, server prerequisites, remote guidance and real remote-client smoke; local HTTP already implemented | Closed #16–#17 baseline **and** owner HTTPS/deployment decision | S6 `existing-check` for unchanged local contracts, high-risk deployment/auth boundary + actual remote evidence |

Each issue owns its exact files, consumed/produced interfaces, non-goals, red/green or existing check, focused commands, and completion evidence. Do not maintain parallel editable task bodies here.

## Requirement coverage

| Spec acceptance | Tickets |
| :--- | :--- |
| 1 local profile, documents, repairs, no extra model endpoint | #13–#17 |
| 2 local stdio, server-side source/doc preparation, plus remote S3/token/HTTPS | #13–#16 (local); #18 (remote) |
| 3 unsupported rules ask/flag, human review | #14–#15, #17 (local); #18 (remote guidance) |
| 4 concurrency, retry, restart | #15; #16 stdio parity; #18 remote parity |
| 5 reviewed digest, human-only Promotion, honest attestation | #15–#17 (local); #18 (remote) |
| 6 old commands/query modes unchanged, base without MCP | #15–#17; #18 remote regression check |

#17's local acceptance is historical. #18 retains the private HTTPS/auth, genuine server-source access, real remote-client and remote guidance gates. Use the current Git proposal/revision/validation/review and human exact-revision admission contracts from [specification 0009](../specs/2026-10-02-0009-modular-core-git-authoring.md) and [0010](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md); preserve legacy human Promotion only on its supported legacy route. Existing HTTP tests cover unchanged behavior. If authorized deployment work changes a public/auth contract without meaningful coverage, the parent assigns `new-test` for that delta and immediate review before consumption; expected values come from the approved contract, and mandatory failing-first is limited to bug reproduction/refactor pinning. Reuse settled review only after exact tree/range correspondence; candidate review covers new deployment/integration effects. One authorized fix pass and one delta recheck; remaining blockers go to the owner. A local mock/plain HTTP check is not a remote HTTPS/S3/harness pass.

Source/code baseline `fce02c9230397f84736e323ea12efe4b993cc129` is published; this workflow amendment remains local until separately committed/published. Before a later run, provide the exact amended sources and select an accepted clean base without discarding the existing checkout delta. Default to supervised builtin workers/fresh reviewers, or explicitly selected and preflighted Herdr/Paseo lanes. Every mutation lane is accepted via a pinned named base, full binary-capable patch/digest and verified parent-owned reconstruction, even if its worker checkout survives; record exact tree/review/backend identities in the existing run manifest. Integration, deployment/exposure, issue closure and publication remain separately authorized.

## Residual risks

A profile cannot prove a business rule; the human approves Seed Notes and Policy text. A bearer token behind private HTTPS is intentionally single-project/single-user. Private S3 credentials and network access must be verified on the actual server; local Delta and Parquet checks do not prove private S3 connectivity.
