# Implementation overview: Named S3 storage profiles

| | |
| :--- | :--- |
| **Status** | **Proposed, revision 1 — ticketized; execution approval pending** |
| **Goal** | Deliver the approved Multi-S3 profile, effective-source-authority and seven-source-type contract through the existing shared DuckDB execution path. |
| **Behavioral source** | [Specification 0025](../specs/2026-10-14-0025-named-s3-storage-profiles.md), **Approved, revision 1**, SHA-256 `165edc52d55d19d6d90175d4511243992832aa8a2f3010f7274a251530a0f06a`; [accepted ADR-0023](../adr/0023-named-scoped-s3-storage-profiles.md). |
| **Approval / ticket authority** | Owner, Pi conversation 2026-10-14: requested “shape design, dann implementierungsplan und tickets”, approved the complete in-chat design, then written revision 1 with “Schriftliche Fassung freigeben (Recommended)”. This authorizes planning and GitHub ticket publication, not implementation, source access, target integration, code/document commit/push or release. |
| **Documentation publication authority** | Owner's subsequent “Commit und push”, same conversation, authorizes publishing the documentation/design/planning baseline. It does not approve this proposed execution map or authorize implementation/source access. |
| **Canonical tasks** | [#71 — S1: Named scoped profiles and endpoint-bound source authority](https://github.com/legout/ariadne/issues/71); [#72 — S2: Lakehouse compatibility and environment-based onboarding](https://github.com/legout/ariadne/issues/72). Their owned files, steps, interfaces, validation scenarios/oracles and completion criteria live only in the issues. |
| **Capture checkpoint** | Specification §8: Storage Profile and effective Source Approval are captured in root vocabulary; ADR-0023 records the named/scoped shared-connection choice. Unique paths and process-only environment delivery are settled; installed Lakehouse compatibility remains a required verification obligation. |
| **Contract** | planning-contract v1; installed planning/orchestration skill provenance unknown. |

## Coverage and sequencing

**#71 → #72**, sequential writers. S2 consumes S1's parent-accepted committed result, not an issue-closure signal or an uncommitted tree. The native GitHub dependency is #72 blocked by #71. Shared builder/fixture ownership is a real dependency, not a reason to dispatch both in parallel.

S1 is a complete file/native source and human-authority path, not a schema-only layer task. It introduces the shared configuration/binding machinery for existing consumers; S2 qualifies the Lakehouse reader families against the same contract and supplies full user/agent onboarding. S1 alone is not the full feature or permission to publish an unqualified Lakehouse claim.

| Source acceptance | Canonical task / evidence |
| :--- | :--- |
| AC1 declarative/offline contract | #71 shared parsing/proposals; #72 final Lakehouse/example compatibility |
| AC2 independent endpoint/credential routing | #71 real file/native signed S3 fixture + compiled query; #72 actual Lakehouse readers |
| AC3 scope/refusal/unused-profile behavior | #71 pre-read refusal and no unused credential access |
| AC4 lifecycle/confidentiality/budgets | #71 secret setup/redaction/closure + existing deadline/read-only checks; #72 preservation through format reads |
| AC5 human effective approval/rotation | #71 real Git proposal and endpoint-change/grant scenario |
| AC6 validation/evidence/admitted identity | #71 frozen binding, cache/receipt/provenance invalidation and pinned runtime |
| AC7 adapter/legacy compatibility | #71 shared forwarding/materialization and preserved role/legacy checks; #72 final guidance |
| AC8 real Delta/Iceberg/DuckLake reads | #72 two-endpoint format matrix, including local DuckLake metadata/S3 data |
| AC9 honest onboarding/reference/agent guidance | #72 Diátaxis how-to/reference, process/Docker delivery and candidate-versus-release distinctions |

## Sources, ownership and runtime prerequisites

The source artifacts and documentation are included in this overview's owner-authorized documentation baseline commit; the tickets pin exact approved source digests and receive immutable source links after publication. The inspected implementation base `a66a012` is published 0.3.0 code, preceding that documentation commit. Before execution, freeze the approved source bytes/digests and the committed documentation baseline through the existing isolated handoff. Preserve the separate pre-existing modification to `project/research/2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md`, which is excluded from this publication; do not import the whole dirty checkout.

Use the installed `orchestrate-implementation` after plan approval and explicit execution authority/readiness. Resolve the configured/verified current Pi host, exact roles/models/thinking, clean named base and one writer per registered isolated worktree under `${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/`. No host switch, allocator change, worker dispatch or alternative execution procedure is authorized by this plan.

Python >=3.12, the existing shared DuckDB/SQLGlot stack and actual existing source extensions are assumed; no dependency or version bump is approved. A preceding synthetic setting probe reported local DuckDB 1.5.6, not Multi-S3 compatibility. Required local S3-compatible fixtures and `httpfs`/Lakehouse extensions must be explicitly prepared in the authorized writer environment. A missing capability or skipped required format test blocks the relevant gate; any necessary scope/version/dependency change returns to the owner.

The separately configured Native Agent development environment must use the candidate core rather than a cached released wheel and its supported local `tau-mcp` source. Failure of that prerequisite is not permission to repair package publication or switch runtimes.

## Assurance and final candidate validation

Both units touch credentials/source permission or their real engine use: **high risk**. Perform immediate bounded read-only Pi review of S1 before S2 consumes its public contract. Tests cover wrong-endpoint/credential routing, SQL-error disclosure, changed-endpoint authorization and stale evidence through real callers; general hardening and coverage targets do not justify extra work. Scope/refusal checks can use the existing builder canary; live routing/format success cannot be proved by mock SQL statements.

S2's documentation/template portion is low risk: `no-new-test`, existing init/adapter smoke and Markdown link/fragment checks. Do not duplicate the same core behavior across every transport or request another settled S1 review. Apply AGENTS.md and the installed complete reviewer contracts: one parent-authorized fix pass, one delta-only recheck, unresolved blockers to the owner. Final candidate review checks integration and previously unreviewed effects.

Run required whole-project checks once on the assembled exact candidate, not per checkbox:

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check .
(cd ariadne-agent && uv run --group dev pytest -q)
git diff --check
```

Focused checks and independent fixture expectations are in #71/#72. Report their actual runtime/extension versions. Local loopback S3 authentication and format reads do not establish production TLS/CA/IAM behavior or deployment success. Real production endpoints/credentials and real agent usefulness remain separately operator/manual checks; no recorded-agent trace suite is added.

## Delivery boundary

Acceptance requires the approved specification's AC1–AC9 evidence on the combined candidate, green required checks and parent-accepted committed results. Use existing source/result refs and run state, not a new evidence ledger or approval lifecycle. Deliver a reviewed isolated candidate and pause before separately authorized target integration, push/publication, deployment/release, issue closure or cleanup.

This overview records planning and ticketization only. No product tests, extension install, source opening, runtime code change or implementation dispatch occurred during its authoring. The owner's subsequent documentation commit/push authorization is recorded above; it grants no feature execution or deployment authority.
