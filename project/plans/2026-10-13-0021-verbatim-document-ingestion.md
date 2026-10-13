# Implementation overview: Verbatim document ingestion

| | |
| :--- | :--- |
| **Status** | **Proposed, revision 1 — ticketized; execution approval pending** |
| **Goal** | Deliver optional exact-converted-text, no-LLM intake with safe staging-local retries through the existing Python/CLI seams. |
| **Behavioral source** | [Specification 0021](../specs/2026-10-13-0021-verbatim-document-ingestion.md), **Approved, revision 1**; Owner's “approved.” in the Pi conversation 2026-10-13. Specifications own behavior; tickets own task decomposition. |
| **Ticketization authority** | Owner's “Ticketize erst”, same Pi conversation 2026-10-13: create the two tickets and move task bodies out of the plans. This does not approve execution, target integration, source access or publication of code/docs. |
| **Canonical task** | [#66 — V1: Verbatim document intake without LLM](https://github.com/legout/ariadne/issues/66). Owned files, checkbox steps, interfaces, validation cases/oracles, focused commands and completion criteria live only in the issue. |
| **Capture checkpoint** | Specification §7: Verbatim Ingestion in [CONTEXT.md](../../CONTEXT.md); ADR-0009 retained; no unresolved material behavior choice. |
| **Contract** | planning-contract v1; installed planning/orchestration skill provenance unknown. |

## Coverage and order

| Source acceptance | Canonical unit |
| :--- | :--- |
| Spec 0021 AC1–AC7 | [#66, V1](https://github.com/legout/ariadne/issues/66), including `new-test`, `existing-check` and docs `no-new-test` obligations |

Proposed sequence: **#66 → [#67](https://github.com/legout/ariadne/issues/67)**, coordinated by [overview 0022](2026-10-13-0022-native-duckdb-sources.md). No semantic dependency exists, but both tasks edit `README.md`; one writer at a time. Accept/review V1's committed result before N1 consumes it. Issue closure alone is not acceptance or authority. Do not maintain another editable copy of V1's task body here.

## Shared execution prerequisites

- Execution-map approval/readiness remains open; ticket publication starts no implementation. Use the installed `orchestrate-implementation`, default supervised, and its existing run state at `.orchestrator/intake-duckdb-20261013/state.md`.
- Selected host is Paseo/Pi. Verify the canonical registered isolated workspace beneath `${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/`, exclusive writer, exact effective model/thinking and clean named base before writes. Preserve old allocations; no implicit host/allocator change or cleanup.
- Observed local code HEAD and remote main at ticketization: `a8d24b18d16854058e6b2b97bd1801cb0687ffbd`. The new source docs remain local/uncommitted, with their exact current digests and historical pre-transfer plan digest recorded in #66/#67. Provide/freeze approved sources through the existing isolated handoff; do not pretend that the old commit contains them or auto-commit a dirty target checkout.
- Refresh a tree/environment-specific baseline before mutation. Prior ingest/source baseline: 104 existing tests; not feature acceptance. Missing tooling or a failing required baseline is an owner gate, not permission for a silent workaround.
- No new dependency/framework, automatic admission, Wiki/Lumio, SQL-history/example-provenance or hybrid-search feature. Human Promotion, compile/source/grain/read-only boundaries and manual real-world agent checks remain unchanged; no recorded-session test tier.

## Shared final validation and delivery

The issues own focused checks; run the required global checks **once on the exact combined candidate**, not per checkbox:

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check .
git diff --check
```

A fresh read-only Pi unit review precedes downstream consumption of each public contract. Use the full installed reviewer contracts; one parent-authorized fix pass and one delta recheck, then hand unresolved findings to the owner. Candidate inspection covers unreviewed integration effects without reopening settled findings. Preserve committed result/base/head refs using the existing orchestrator.

Deliver the reviewed isolated candidate and pause. Target integration (`merge-worktree`), push, issue closure, deploy/release and cleanup retain separate authority. Converter fidelity and actual agent usefulness retain the explicit limits/manual checks in #66 and the source specification.
