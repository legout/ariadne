# Implementation plan: Multi-fact planner core and local admission

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized; implementation not authorized by ticketization** |
| **Goal** | Deliver the approved normalized-graph/sqlglot multi-fact query path and dev/test Promotion without changing the existing single-metric or ad-hoc paths. |
| **Source** | [Approved specification, revision 1](../specs/2026-09-30-0008-multi-fact-planner.md), committed and pushed as `8cd2559` (owner approved the written revision in the 2026-09-30 Pi conversation). |
| **Plan approval** | Owner approved the written **core-first** plan in the same conversation, then explicitly requested GitHub ticketization. Neither act authorized implementation, integration, committing this plan, or a further push. |
| **Scope** | Core and dev/test local admission only. Production Git-review admission is a separate **blocked** workstream until the real CI runner, live-audit access, review evidence and deployment target are identified. |
| **Decisions** | [ADR-0006](../adr/0006-grain-governance-multi-cardinality-joins.md) (one grain per dataset, independent fact branches), [ADR-0003](../adr/0003-staging-dir-review-gate.md) (local human Promotion and later production reviewed-Git gate), [ADR-0008](../adr/0008-own-sqlglot-compiler-agpl-exit.md) (own compiler). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |

## Constraints and capture checkpoint

- [`CONTEXT.md`](../../CONTEXT.md) owns Grain, Conformed Dimension, Fact Branch and admission terminology; the linked ADRs own durable choices; the approved specification owns query behavior, failures, non-goals and seven acceptance examples. No unresolved material decision blocks this **core-only** sequence. A fixture-only check is not the production live audit.
- Ariadne's `render()` currently compiles one dataset. Evolve its sqlglot/DuckDB and shared registry/grain seams; do not add another SQL engine, a KTX parser, Dosi runtime, connector or dependency. The existing ad-hoc and pre-joined source guard remains. Relationship-target composite keys need exact tuple uniqueness and non-NULL checks; the legacy source-join guard may stay stricter.
- One writer, sequential acceptance. At ticketization the checkout has unrelated `.gitignore` and `.pi/settings.json` edits; resolve ownership or start from an isolated clean baseline before execution, never discard or include these changes. The reviewed/served artifact tree is the asset at the remote `files[]` submission boundary: permit only the explicit graph path, keep credentials/CA out of artifacts, and preserve the locked human Promotion gate.
- Promotion decorates OKF pages, so served bytes differ from the reviewed staged bytes. Local admission must bind the staged review digest to a post-Promotion served digest without rerunning value checks. Technical validation, human review and independent value attestation remain distinct. Do not expose the multi-fact query publicly until its admission guard is in place.
- Each linked ticket owns its **only editable task body**: exact paths, interfaces, prerequisites, one `new-test` validation obligation with a reachable scenario, red → minimal green → focused command, completion criterion and proportionate review. The tests use the existing synthetic fan-out trap plus independent numeric oracles. This plan retains only order and acceptance coverage, not duplicate task instructions. The plan is still local/uncommitted; issue links to the approved specification at commit `8cd2559` are publicly readable.

## Canonical tickets and requirement coverage

| Specification acceptance | Canonical tickets | Dependency |
| :--- | :--- | :--- |
| AC1 — order/line trap, both authoring layouts, old pre-join refusal | [#26](https://github.com/legout/ariadne/issues/26), [#27](https://github.com/legout/ariadne/issues/27), [#30](https://github.com/legout/ariadne/issues/30) | #27 after accepted #26; #30 after #26–#29 |
| AC2 — unmatched/NULL keys, count/SUM/ratio, unpaired group/filter | [#27](https://github.com/legout/ariadne/issues/27), [#28](https://github.com/legout/ariadne/issues/28), [#29](https://github.com/legout/ariadne/issues/29) | Sequential |
| AC3 — typed paths, bad keys/extensions, source drift | [#26](https://github.com/legout/ariadne/issues/26), [#27](https://github.com/legout/ariadne/issues/27), [#28](https://github.com/legout/ariadne/issues/28) | Sequential |
| AC4 — conformed time, range/grain, lookback, parameters/segments | [#28](https://github.com/legout/ariadne/issues/28), [#29](https://github.com/legout/ariadne/issues/29) | #29 after accepted #28 |
| AC5 — derived metrics, bounded explain, grain-safe detail | [#28](https://github.com/legout/ariadne/issues/28), [#29](https://github.com/legout/ariadne/issues/29), [#30](https://github.com/legout/ariadne/issues/30) | #30 after #29 |
| AC6 — digest-bound checks, local Promotion refusal, attestation separate | [#26](https://github.com/legout/ariadne/issues/26), [#30](https://github.com/legout/ariadne/issues/30) | #30 after #26–#29 |
| AC6 — production reviewed commit, full live CI, deployed artifact | **Separate workstream, blocked** | Needs actual runner, source/CA access, review proof and deployment target; no production ticket yet |
| AC7 — legacy governed/ad-hoc/source/context/fan-out behavior | [#26](https://github.com/legout/ariadne/issues/26)–[#30](https://github.com/legout/ariadne/issues/30), final existing checks | Sequential |

## Integration and handoff

Execute [#26](https://github.com/legout/ariadne/issues/26) → [#27](https://github.com/legout/ariadne/issues/27) → [#28](https://github.com/legout/ariadne/issues/28) → [#29](https://github.com/legout/ariadne/issues/29) → [#30](https://github.com/legout/ariadne/issues/30), accepting the shared graph and planner seams before dependents consume them. Immediate read-only review at the dependency-defining graph, fan-out arithmetic, parsed-filter, and remote-submission/Promotion boundaries; one candidate integration review covers previously unreviewed changes. The parent owns dispositions, at most one in-scope fix pass and one delta-only recheck; unresolved findings go to the human, not another round.

Use each ticket's focused checks, then `uv run --extra dev pytest -q`, `uv run --extra dev ruff check src/ariadne tests`, `git diff --check`, and an AC1–5, AC6-local, AC7 evidence audit. Report production AC6 as **blocked/unverified**, never passed on a synthetic fixture. No implementation, PR, merge, push or release is authorized by these tickets. If implementation requires material behavioral change, return to shaping and owner approval before changing the source contract.

**Production handoff (not ticketized):** identify a real production CI/deployment branch, exact-commit human-review evidence, read-only approved live-source access with verified TLS/CA, and reviewed/validated artifact delivery. Then write and approve a separate plan for the remaining AC6 route; do not invent `.github/workflows/` or accept a mock full-validation pass.
