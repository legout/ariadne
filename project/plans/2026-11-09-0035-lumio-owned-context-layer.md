# Implementation plan 0035: Lumio-owned Context Layer

**Status:** approved and ticketized overview, revision 2 (editorial transfer; approved decomposition unchanged). Written 2026-11-10 after “Erstelle den plan”; revision 1 approved with “Passt! erstelle die Tickets bzw. passe die bestehenden an”.
**Behavioral source:** [spec0035, approved written revision 2](../specs/2026-11-09-0035-lumio-owned-context-layer.md), approved with “Spec is freigegeben.” on 2026-11-10; AC1–AC15 and §§1–8. [ADR-0029](../adr/0029-lumio-owned-context-layer.md) remains unchanged. [Research and live R-track inspection](../research/2026-11-09-lumio-only-context-layer.md) are evidence, not additional authority.

The owner now authorizes plan approval, the named R-track source/ticket reconciliation and GitHub ticketization. Implementation, source/credential access, worktree execution, integration, commit/push, deployment and release remain unauthorized. Canonical C-task bodies now live in [#109–115 under epic #108](https://github.com/legout/ariadne/issues/108); this file owns sequencing, interfaces and coverage only. The [frozen approved revision-1 plan](https://github.com/legout/ariadne/issues/108#issuecomment-6768382155), [spec0035 r2](https://github.com/legout/ariadne/issues/108#issuecomment-6768381795) and [unchanged ADR-0029](https://github.com/legout/ariadne/issues/108#issuecomment-6768382491) publish exact sources without implying a Git commit/push. Existing R-task bodies remain in #102–107.

## Goal, constraints and current correspondence

Replace Ariadne's independent Context implementation with one Lumio lifecycle, preserving analytical ownership and making the approved fresh-setup contract usable end to end. Dependency direction stays `ariadne-data -> lumio-wiki`; Lumio remains independently installable. No private app, service, LanceDB, S3, MCP or model provider is added to either base journey merely by this change. Preserve source permission, human approval, exact release/scope bindings, required Policy closure and numerical safeguards. No old-project migrator, dual writes, compatibility-only aliases or legacy execution fallback.

Inspected source baseline: `d2f8b75c0970267b42b0d04f5359ae603b7998a9`, with the pre-existing documentation changes preserved. Planning ran no product tests. Existing tests below are selected coverage, **not passing evidence from this session**. Refresh correspondence before execution. Python >=3.14, Git and the existing uv workspace are required; local default fixtures use SQLite/DuckDB and private temporary directories. Lumio focused tests run serially from `products/lumio`; full Lumio CI uses exactly four workers, never `auto`.

Capture checkpoint: the approved spec and existing product glossaries supply all required vocabulary; no new ADR or glossary change is needed. This plan supplies decomposition only. Planning-contract v1; installed skill provenance unknown. Execution, when authorized, follows `orchestrate-implementation`, supervised by default, with one Pi writer per isolated registered worktree and the configured host/model preflight. Preserve dirty work; do not clean, stash or commit unrelated files to manufacture a base.

Path abbreviations below:

- **A** = `products/ariadne/packages/ariadne-data`; **a** = A `src/ariadne`.
- **K** = `products/lumio/packages/lumio-wiki`; **k** = K `src/lumio_wiki`.
- **W** = `products/lumio/packages/lumio-workspace`; **w** = W `src/lumio_workspace`.
- **I** = `integration/tests`; **DA** = `products/ariadne/docs`; **DL** = `products/lumio/docs`.

Written conventions: root `AGENTS.md`, product vocabularies, K `AGENTS.md`, root/member `pyproject.toml`, `products/lumio/.ruff.toml` and `pytest.ini`. Preserve lazy optional imports and isolated-wheel boundaries. No new style convention is introduced.

## Prerequisites and R-track coordination

These are execution gates. Source/ticket reconciliation is authorized by the subsequent ticketization request; product execution is not.

- [ ] Obtain separate implementation authority; this plan is approved. Pin an approved candidate base containing the exact source documents without incorporating unrelated dirty work.
- [x] Reconciled R1/R2/R4/R5 into [spec0034 r6](https://github.com/legout/ariadne/issues/85#issuecomment-6768381020), [plan amendment r2](https://github.com/legout/ariadne/issues/85#issuecomment-6768381402) and canonical #103/#104/#106/#107 under the 2026-11-10 owner approval. Earlier frozen approvals are preserved; R0/#102 and R3/#105 are unchanged.
- [ ] Disposition the concrete pre-existing source-boundary findings named in spec0035 §8: PostgreSQL destination changes under the same environment-variable name, pre-approval XLSX conversion, and profiling bounds. Use the existing approved data contracts. Confirmed required fixes need a separately authorized narrow change or an explicit owner decision on affected scope; no full AC3 claim or completion while a relevant violation remains. This plan does not authorize a connector/importer redesign or silently drop supported sources. Unaffected local work need not wait for a live PostgreSQL fixture.

| Existing canonical task | Consumption / approved ticket adjustment |
| --- | --- |
| [R0 / #102](https://github.com/legout/ariadne/issues/102) | Already owns first reviewed publication and the next contribution's admitted base. Reuse for AC11; no duplicate repair. |
| [R1 / #103](https://github.com/legout/ariadne/issues/103) | Reuse shared-scope resolution. Clarify Entity ID/revision in existing read/search where follow-up operations need them, in spec0034 §12.2/AC22 and the ticket. Preserve standalone Evidence refusal in integrated mode. |
| [R2 / #104](https://github.com/legout/ariadne/issues/104) | Reuse exact original attachments. Explicitly cover binary pending-review inspection in spec0034 §12.3/AC24 and the ticket; keep pending/published authorization separate. |
| [R3 / #105](https://github.com/legout/ariadne/issues/105) | No substantive expansion. Its standalone retention exception never applies to C3's knowledge-only requests in analytics workspaces. |
| [R4 / #106](https://github.com/legout/ariadne/issues/106) | Extend the standalone recovery outcome to the next reviewed publication in spec0034 §12.5/AC26 and the ticket. C5 consumes this operations boundary and owns only the integrated delta. |
| [R5 / #107](https://github.com/legout/ariadne/issues/107) | The amended task includes pending binary inspection and post-restore publication in its existing bounded installed journey. Coordinate its execution with C7 on the same assembled candidate; do not duplicate the standalone live journey. |

All six issues remain OPEN after ticketization; source snapshots and task updates are not implementation evidence. Their existing `new-test`/`no-new-test` assignments and evidence budgets remain theirs. R1's retained “legacy read/search” means existing Lumio workspace APIs, not Ariadne's retired `context_layer/` backend.

## Sequencing and contract handoffs

Default one sequential writer: **source reconciliation → R0 → R1 → R2 → R3 → R4 → C1 → C2 → C3 → C4 → C5 → C6 → C7**, with R5's final installed journey coordinated in C7. This avoids competing writers on `app.py`, native publication, profiles and `operations.py`. C1/C2 have no functional dependency on unfinished standalone retrieval; an explicitly rescheduled run may do them first, but C3 requires accepted R0/R2/R3, C4 requires R1's scoped-view contract, and C5 requires R4. No parallel writes to shared files are planned.

This is a wide breaking refactor. Keep intermediate C commits on one isolated candidate line; per-task coherence is the named new-path check, not a claim that every old-contract fixture is green. Unmigrated legacy code may remain temporarily as existing code until C6, but no new fallback/dual-write path is added and the new path must not use it. C6 closes all caller/fixture migration before full CI and delivery. If a step needs supported legacy behavior rather than merely intermediate source presence, stop: that conflicts with spec0035.

Public SDK seams to reuse, checked in source:

- `write_pages_into_worktree(kb_root, proposed_pages, *, control_file=None, operation=...)` validates a complete candidate and returns `WorktreeMutationResult`; no Git commit. `revise_pages_in_worktree(kb_root, revisions, *, operation=...)` is for existing-page revisions. Mixed new/changed cross-linked pages must validate together, not through sequential single-page writes.
- `CandidateRequest` / `ingest_candidate` validate complete authored pages plus exact source records, retain originals and apply one candidate. `extract_source` produces source material, not automatically approved business meaning.
- `capture_revision`, `inspect_ariadne_candidate`, native review/publication and `ContextIdentity` / `open_published_context` retain exact commit, source and admission identity. `list_published_context_pages`, `read_published_context_page` and `search_published_context_pages` already expose scoped producer metadata; `PublishedContextPageMetadata` includes Entity ID/version and `PublishedContextPage.native` carries producer-owned metadata.
- **Setup gap:** `journey_setup.py` labels itself internal and is not a supported top-level export. C1 must establish supported public exports for the existing `EmptySetupPlan`, `plan_empty_setup`, `recheck_plan` and `apply_plan` contracts before Core consumes them. Preserve their explicit selections, digest-bound recheck and guarded apply semantics; Core supplies only its own declared configuration-write callbacks, with no implicit agent-skill install. Do not import an internal helper as a substitute for that public contract, and do not implement another manifest initializer in Core.
- **Example gap:** producer profile validation and Core's capability table currently exclude Answer Examples. C4 must supply the minimal supported producer metadata/view contract and update the new Core support contract before consumers use it. Do not mutate historical admission capability records or add a Core parser of KB bytes.

Core retains candidate locks, expected-revision checks and durable Git bookkeeping around native uncommitted mutations. A successful native write is not itself a successful Core candidate commit: commit/store interruptions retain recoverable evidence and block further edits rather than report a clean success. No new transaction service or generic plugin abstraction.

## Validation policy

Every C task names its failure, independent oracle, smallest check and invalidating delta. Existing tests may be adapted to native fixtures, but their still-required numerical/permission/provenance expectations are not weakened. `new-test` means one focused recurring-regression scenario, not another test layer; bug repros fail before repair, unchanged behavior is pinned before refactoring when applicable. New feature cases need not incur ceremonial failing-first runs.

High-risk units C1–C5 change public contracts, authorization, persisted state or numerical gates. Check their named boundary immediately; use the project-required independent Pi review before downstream tasks consume changed contracts. Review only those criteria and unreviewed integration effects, one parent-authorized fix pass and one delta recheck. C6's mechanical documentation changes need no separate review. No reviewer is dispatched during planning. Applicable verified evidence survives handoffs and identical-content candidate assembly; a changed caller, schema, authorization, input or relevant build invalidates only its affected evidence.

Required repository CI remains the integration/delivery gate in `.github/workflows/ci.yml` and the applicable wheel/release workflows; do not replicate full suites per task or run release publication actions. C1 changes only the now-invalid Core-without-Lumio expectation. No project-local `verify-*` recipe was found under `.agents`/`.pi`; use the existing wheel walkthrough, protocol/browser drivers and documented installed journeys, not a new verification framework or skill.

## C1 — Install, initialize and edit one native knowledge candidate

Canonical task: [#109](https://github.com/legout/ariadne/issues/109). Source: AC1/4/10; no feature dependency beyond an approved execution base. Consumes existing native setup/mutation APIs; produces supported public empty-setup exports, mandatory packaging, atomic revision-bound page batches and nonmutating legacy refusal for C2.

## C2 — Onboard a table and execute against its exact native Context

Canonical task: [#110](https://github.com/legout/ariadne/issues/110). Source: AC2/3/6/7; depends on C1 and the applicable source-boundary dispositions. Consumes native mutation/identity; produces native technical refresh/finalization, exact admission/Policy closure and preserved query gates for C3.

## C3 — Native document intake and knowledge-only contributions with analytics enabled

Canonical task: [#111](https://github.com/legout/ariadne/issues/111). Source: AC5/11/12/13; depends on C2 and accepted R0/R2/R3. Consumes native intake, reviewed baseline and exact original inspection; produces knowledge-only routing with analytics enabled, without unrelated data grants, executable edits, release repinning or retention exemptions.

## C4 — Save/retrieve Answer Examples and navigate ordinary native pages

Canonical task: [#112](https://github.com/legout/ariadne/issues/112). Source: AC8/9/14; depends on C3 and R1. Consumes scoped producer metadata; produces minimal native Example capabilities, ordinary guides and stable-ID/exact-revision discovery. No Core KB-byte parser, cached answer substitution or stored-SQL execution.

## C5 — Restore one integrated repository and resume approved work

Canonical task: [#113](https://github.com/legout/ariadne/issues/113). Source: AC6/15; depends on C4 and R4. Consumes restored native artifact/identity state; produces one restored shared authoring/analytics repository and explicitly reauthorized/revalidated resumed publication/query, without rewriting history.

## C6 — Remove the retired implementation and reconcile every shipped caller

Canonical task: [#114](https://github.com/legout/ariadne/issues/114). Source: AC1/10 and preservation of AC2–9; depends on C1–C5. Consumes supported native paths; removes retired backend/intake/Example storage and reconciles all shipped callers, fixtures, docs and packaged skills before full CI.

## C7 — Verify the assembled candidate once and hand it back

Canonical task: [#115](https://github.com/legout/ariadne/issues/115). Source: AC1–AC15; depends on C1–C6 and accepted R0–R4, source-contract dispositions and a known final build. Produces one assembled CI/isolated-wheel/local-journey evidence set and coordinates R5's separately authorized live leg on that build. C7 can start final CI after C6; R5 waits for C6, not C7 completion. Missing live prerequisites remain live-unqualified.

## Acceptance ownership

| Criterion | Implementation owner | Final evidence |
| --- | --- | --- |
| AC1 mandatory SDK / independent Lumio | C1, C6 | C7 isolated wheels, no explicit SDK preinstall |
| AC2 native data-only setup | C1, C2 | C7 local journey |
| AC3 source approval / refresh identity | C2; source-boundary prerequisite | Focused source gate and refresh evidence; no unsupported format claim |
| AC4 valid atomic page batches | C1 | Immediate batch/revision check, reused in C7 |
| AC5 native document lifecycle | C3 | Native contribution evidence and applicable R5 document journey |
| AC6 exact association / activation failure | C2, C5 | Existing release-failure evidence and integrated recovery |
| AC7 required Context before SQL | C2 | Existing pre-SQL/Policy checks plus positive local query |
| AC8 saved Example, never answer cache | C4 | Existing provenance check; C7 independently computed 30 → 35 |
| AC9 ordinary guide | C4 | Scoped native navigation and local guide read |
| AC10 fresh cutover / old files unchanged | C1, C6 | Replacement refusal regression and installed guidance |
| AC11 first and next publication | R0, consumed by C3 | R0 evidence and R5 v2 journey; no duplicate bootstrap task |
| AC12 knowledge-only authorization | C3 | Focused managed protocol/browser regression |
| AC13 binary source inspection | Amended R2, consumed by C3 | Candidate/published byte checks and same R5 journey |
| AC14 identity and scoped Context discovery | C4; R1 shared-view prerequisite | Existing native navigation + supported-surface identity readback |
| AC15 integrated supported-format recovery | C5; amended R4 prerequisite | Shared-repository/reauthorization/publication/query regression |

## Approval and residual dependencies

This approved plan changes no approved spec0035 behavior. The owner's “Passt! erstelle die Tickets bzw. passe die bestehenden an” approves this decomposition and authorizes the named R-track source/ticket reconciliation and C-task publication, not implementation. Existing issue changes must explicitly carry their new source revision. Concrete source-boundary defects, public SDK setup/Example contracts and shared-root recovery must be resolved at their named boundaries before dependent acceptance. If they require behavior outside spec0035, return only that affected choice to shaping rather than expanding this plan during implementation.

No product tests, builds, live services, child agents or worktrees were started while writing this plan. GitHub ticket publication is now authorized; Git commits/push and product publication remain unauthorized. A separate implementation grant is still required.
