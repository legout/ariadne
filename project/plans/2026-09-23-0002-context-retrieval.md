# Implementation plan: Measured Context Layer retrieval

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized; implementation not authorized by ticketization** |
| **Goal** | Improve Policy discovery only as evidence warrants, and add source-located excerpts without weakening full-page or governed-context behavior. |
| **Source** | [Approved retrieval specification, revision 1](../specs/2026-09-23-0002-context-retrieval.md) |
| **Source approval** | Owner, pi session 2026-09-23 — complete design and written specification approved; scope is the source header's revision 1. |
| **Plan approval** | Owner, same session — approved the one-unit measured retrieval plan and requested ticketization. |
| **Prerequisite** | Finish and accept `project/plans/2026-09-23-0001-local-artifact-runtime.md`, issues [#7](https://github.com/legout/ariadne/issues/7) → [#8](https://github.com/legout/ariadne/issues/8) → [#9](https://github.com/legout/ariadne/issues/9). Do not write retrieval code into the in-progress runtime extraction. |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Constraints and capture checkpoint

- The accepted `ariadne.runtime.AriadneRuntime.search_context` is the single behavior seam; the local JSON and optional MCP adapters reuse it. Preserve `Facade` compatibility, full-page `content`, served-plus-draft scope, and complete governed `get_metric` context. No OKF, promotion, compiler, or transport changes. Use Python 3.12, pytest, and only stdlib `sqlite3` if FTS5 earns inclusion; no embeddings or new dependencies.
- **Vocabulary:** existing [`CONTEXT.md`](../../CONTEXT.md) terms suffice. **Decisions:** the approved spec records the reversible retrieval choices; no new ADR. **Behavior:** the approved source owns scope, failures, and acceptance. **Uncertainty:** the baseline and FTS5 selection are empirical gates; if neither allowed path meets the cases, stop for owner direction. Execution needs separate authorization.
- One sequential writer after the local-runtime prerequisite is accepted. User-owned local Context Layer files introduce no new credential, auth, network, or dependency trust boundary (`security: n/a`). Candidate review covers the additive public result shape and draft/freshness risks; at most one parent-authorized fix pass and one delta recheck.

## Canonical ticket and requirement coverage

[#10 — Add measured Context Layer retrieval and passage pointers](https://github.com/legout/ariadne/issues/10) owns the executable task body, files, interfaces, `new-test` obligation, red/green sequence, conditional FTS5 gate, checks, completion evidence, and non-goals. This file only records ordering and coverage; do not maintain duplicate task definitions.

| Specification acceptance | Ticket | Dependency |
| :--- | :--- | :--- |
| AC1 — measured top-five Policy recall, missing query, disclosed ranking path | #10 | Accepted #7–#9 |
| AC2 — served/draft distinction and changed staged content | #10 | Same |
| AC3 — excerpt, file-line coordinates, frontmatter and fenced headings | #10 | Same |
| AC4 — legacy result fields and full governed context | #10 | Same |
| AC5 — disposable index freshness/rebuild/fallback, only if FTS5 is selected | #10, conditional | Lexical miss after AC1 evaluation |

## Execution and integration

Execute #10 only after #7–#9 are accepted and their runtime/CLI/MCP behavior is integrated. Baseline the current search before changing ranking; deliver passage pointers and only the ranking path justified by the same checked-in questions. One candidate review follows the integrated slice. The parent retains approval of implementation, fixes, and target integration; ticket creation alone authorizes none of them. If a material scope or interface change is needed, return to `shape-design` and reconcile the specification before continuing.
