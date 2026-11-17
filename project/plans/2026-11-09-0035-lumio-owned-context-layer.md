# Implementation plan 0035: Lumio-owned Context Layer

**Status:** approved and ticketized overview, revision 2 (editorial transfer; approved decomposition unchanged). **Revision-3 C6 completion amendment below is owner-approved, 2026-11-13 (“ok. freigegeben”), including its bounded supervised execution.** Written 2026-11-10 after “Erstelle den plan”; revision 1 approved with “Passt! erstelle die Tickets bzw. passe die bestehenden an”.
**Behavioral source:** [spec0035, approved written revision 2](../specs/2026-11-09-0035-lumio-owned-context-layer.md), approved with “Spec is freigegeben.” on 2026-11-10; AC1–AC15 and §§1–8. [ADR-0029](../adr/0029-lumio-owned-context-layer.md) remains unchanged. [Research and live R-track inspection](../research/2026-11-09-lumio-only-context-layer.md) are evidence, not additional authority.

The original ticketization approval authorized plan approval, the named R-track source/ticket reconciliation and GitHub ticketization, not implementation or publication. Subsequent execution grants and accepted results are recorded in the existing `open-issues-20261110` run context. The preparation request, “ok. lass und die gemeinsame C6-Abschlusswell vorbereiten”, initially authorized preparation only. The subsequent “ok. freigegeben” approves revision 3 below and its named Herdr/Pi execution, bounded edits/checks/review, local commits/frozen results and isolated completion-candidate handoff. It grants no target integration, push, tracker mutation, release, live access, C7 execution or plan0036 cleanup. Canonical C-task bodies now live in [#109–115 under epic #108](https://github.com/legout/ariadne/issues/108); this file owns sequencing, interfaces and coverage only. The [frozen approved revision-1 plan](https://github.com/legout/ariadne/issues/108#issuecomment-6768382155), [spec0035 r2](https://github.com/legout/ariadne/issues/108#issuecomment-6768381795) and [unchanged ADR-0029](https://github.com/legout/ariadne/issues/108#issuecomment-6768382491) publish exact sources without implying a Git commit/push. Existing R-task bodies remain in #102–107.

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
  - **PostgreSQL effective destination — DISPOSITIONED 2026-11-10** (owner decision “Ohne Dependency”): narrow no-dependency repair under the existing spec0025 §4 contract; see the disposition note in [spec0035 §8](../specs/2026-11-09-0035-lumio-owned-context-layer.md#8-reconciliation-and-handoff). Current ENV targets bound at approval; same captured connection string verified before ATTACH; `service=`/`PGSERVICE` refuses with explicit-target guidance (owner-approved narrowing); destination-unbound legacy PostgreSQL grants need fresh human approval/revalidation; S3/file grants unchanged. Pre-approval XLSX conversion and profiling bounds remain open for their own disposition.

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

Execution-scope clarification (owner-approved 2026-11-11, “Approve caller scope”, C6 worker capture; documentation only, no new behavioral spec/ADR, no change to historical approvals or frozen issue snapshots): finishing the approved native cutover additionally requires touching five direct callers/files outside the ticket's original owned-file list — `authoring.py` (central classic finalize/refresh/graph-reference branch removal), `query.py` (classic context fallback removal plus wiring the existing advisory quality view to authorized pinned typed SDK metadata), `status.py` (Example counts from pinned producer-kind metadata instead of the retired separate-store path), `review.py` (mapping-confirmation walkthrough prints the exact reviewed native Reference body via canonical payload resource identity), and `products/ariadne/docs/reference/data-sources.md` (one retired-command reference). Live behavior is preserved: the native advisory quality/data_signals view stays (adapted to pinned typed SDK metadata/native facts, honestly unknown when facts are absent), status Example counts come from authorized pinned metadata and actual native identities, the review walkthrough keeps its digest/confirmation/revision safeguards, and the Seed Notes resolver (`data/seed_notes.md`) plus the live document converters and `documents`/`spreadsheets`/`openpyxl` dependencies stay.

Continuation clarification (owner-approved 2026-11-12: concrete quality contract + seven-check budget, C6 worker capture; documentation only): the optional TABLE-native `ariadne_quality` producer contract is approved as specified in the scoped spec0009 §9 quality-profile amendment below (retained sources: Ariadne spec0013 r2 + plan/Core validator grammar; K structural ownership; Core advisory meaning). The continuation COMPLETES the C6 fixture/caller migration in this task — retired page-kind edit flows migrate to the native page batch with all numerical, permission, provenance, scope, revision, admission, quality and mapping assertions preserved meaningfully; exclusively retired backend/builder/index cases are deleted only after per-case proof that each live invariant (authored-meaning preservation, collisions, no-op refresh, forged-generated facts, freshness/verification tiers, permission/revision guards) has an actual native assertion; no pending-migration skips remain as a final state. The retired served-tree advisory reader and orphan read/index helpers retire only after every live consumer/test uses the semantic Core + pinned SDK path. The owner-approved verification budget is EXACTLY seven existing nodes — `integration/tests/lumio_local_context.py::test_multi_metric_context_precedes_execution`, `integration/tests/lumio_local_context.py::test_integrated_technical_profiles_preserve_evidence_and_curated_content`, `integration/tests/lumio_contribution_review.py::test_contribution_review_covers_document_and_metric`, `tests/test_answer_examples.py::test_native_example_save_search_never_opens_sources`, `integration/tests/lumio_metric_mvp.py::test_legacy_project_refuses_without_mutation`, `tests/test_git_proposals.py::test_table_page_edit_adds_supplied_quality_metadata_without_touching_core_claims` (MIGRATE/KEEP), `tests/test_data_signals.py::test_expired_report_preserves_rows_sql_and_discloses_as_of_evidence` (MIGRATE to real supported producer quality metadata, same rows/SQL/as-of oracle) — replacing the earlier single-node budget, with no full-suite/CI/wheel/install campaigns (C7 keeps required full CI). The one additional necessary caller delta is the parent-approved removal of the single vacuous `_bundle_errors` invocation in `ariadne/contribution_review.py::_static_validation` (diff-proven last caller; no stub restoration); no other caller expansions.

Scoped retirement addendum (owner-approved 2026-11-12, host-only decision, C6 fix
pass capture; documentation only, no change to historical approvals or frozen issue
snapshots): the first independent C6 review's remaining ariadne-agent test-migration
items are superseded — the tracked `products/ariadne/packages/ariadne-agent` package,
its Tau dependencies and its tests are REMOVED entirely per [Ariadne
ADR-0027](../../products/ariadne/project/adr/0027-host-agents-only.md) (host agents
only; Core CLI/MCP/skill surfaces and the four-member workspace stay). C6 reconciles
current docs/config/layout claims so none use, depend on or test Tau; historical
records keep explicit retired/superseded markers. The one-fix-pass validation budget
for this addendum is the parent-approved node list in the C6 fix report
(`c6/c6-fix-report.md`), not a new seven-node grant.

Owner-authorized D1–D4 completion (owner-selected "Authorize bounded completion",
2026-11-12, C6 owner-a4 completion capture; documentation only, no change to
historical approvals, frozen verdicts or issue snapshots): with the first review
and the single delta both returned fix-first and the independent review budget
exhausted, the owner authorized ONE D1–D4-only completion pass on the single-delta
findings of `c6-delta-review-report.md` (D1 prewrite named-shape refusal for
quality-gate malformed sources/keys; D2 finishing the context-only composite-
admission migration, the native review-case migration and the wheel walkthrough's
SOURCE validity; D3 correcting the recovered refresh/revision/type-identity/bound/
source-binding tests; D4 host-only README reconciliation) with the exact 20 parent-
approved focused selectors, required scoped member Ruff and parent audit. The
independent fix-first verdicts stay unchanged; no finding, safety or behavior
waiver; NO third independent review — acceptance is the parent's actual audit of
all criteria after execution. The full proposal and closure matrix live in the
append-only C6 fix report; C6/C7 gate status and landing remain governed by actual
evidenced criteria, not by this capture.

Owner-authorized S1 residual batch (owner-selected "Batch S1 freigeben
(Empfohlen)" plus the separate "Sichtbar, weiter" tab admission, 2026-11-12;
documentation only, no change to historical approvals, frozen verdicts or issue
snapshots): with C6's repair budget exhausted and the required C7 `core-source`
run red (144 failed/29 errors on the same frozen base), the owner authorized ONE
S1-only fixture-completion exception: the explicit old `init.main([str(project)])`
callsites in `products/ariadne/packages/ariadne-data/tests/test_setup.py` reach
their existing setup scenarios through a valid native predecessor — the existing
public initializer with an explicit fixed namespace and a machine-local
private-profile path outside each synthetic repository, and each scenario's
already-explicit Git fixture prerequisite arranged before native initialization
(the SDK never initializes Git; no-Git/no-identity/parent-repo negative gates stay
meaningful and untouched). Validation is EXACTLY three existing nodes
(`test_managed_typed_declaration_exact_handoff_and_idempotent_resume`,
`test_setup_declaration_references_an_existing_candidate_profile`,
`test_inline_credential_refused_without_echo_or_declaration`) plus one scoped
Ruff pass on the changed file, on the retained C7 core-pair pair after static
package-input correspondence confirms unchanged Core/SDK inputs; isolated Pi
writer, parent audit without a third independent C6 review. Checkpoint after;
no automatic follow-on batch, no wider repair/cleanup, no test pruning, no
Plan0036 transfer. Global C6 source-ready acceptance stays suspended; D1–D4
evidence and all independent verdicts remain preserved.

Owner-authorized S2 native setup caller repair (owner-selected "Produktfix
vorbereiten (Empfohlen)" then "S2 samt Review freigeben", 2026-11-12;
documentation only, no change to historical approvals, frozen verdicts or issue
snapshots): S1's actual three-node red proved the production defect —
`ariadne/setup.py` unconditionally called the native initializer with the
pre-native signature. The owner approved the bounded native setup behavior
(exact scope in the 2026-11-12 spec0017 native amendment): existing valid native
KB resumes metadata-only and is never reinitialized; re-supplied selections
validate against the existing namespace and the named external profile; fresh
native initialization needs BOTH explicit `--namespace`/`--private-profile`
setup options (initializer names/semantics) plus operator-prepared Git and
delegates once to the public initializer; missing selections or Git/root/identity
report all actionable prerequisites and complete as a diagnostic (exit 0,
Ready: no) with only selected-skill-install writes; retired/incomplete layouts
refuse before any write. Owned files: A/src/ariadne/setup.py, A/src/ariadne/cli.py,
A/tests/test_setup.py (S1 WIP preserved; test_new_managed_scaffold explicitly
adapted to the approved native flow; ONE new focused refusal test), the two
captures (spec0017 native amendment, this addendum) and the affected setup
usage in SKILL.md/cli.md/getting-started.md only. Validation: EXACTLY six
named selectors in serial groups of at most three (180s INT/kill5,
faulthandler 30, `-vv`) on the retained C7 core-pair interpreter with an
explicit own source-root PYTHONPATH overlay (installed Core is stale); scoped
Ruff on the three changed Python files; no baseline rerun, full suite, wheel
rebuild or installed-artifact claim. ONE new independent production review
(Pi openai-codex/gpt-6.1-sol:high), limited to this setup adaptation and its
human/identity/no-overwrite gates — not a third C6 D1–D4 review; one fix pass
plus one delta recheck maximum. Checkpoint after review; no merge/push or
follow-on batch; S2 does not promise the remaining setup/whole-CI migration.
### Approved revision-3 amendment — one C6 completion wave

**Authority and ownership.** This is an owner-approved execution amendment under
[#114](https://github.com/legout/ariadne/issues/114), not a replacement task,
new feature spec or transfer into proposed plan0036. The canonical issue still
owns C6's behavior/surface/removal obligations. This subsection owns only the
remaining grouping and validation. All four groups below belong to ONE wave;
normal in-scope fixture corrections need parent disposition, not a new owner
approval per line. Owner approved this exact amendment and execution with
“ok. freigegeben” on 2026-11-13; its gates and exclusions remain binding.

**Baseline and evidence.** Start from the accepted frozen S6 result
`6394001e062953543cb3833cec79d814ff158823`, tree
`45fa1f16dd93c042419e354d8e9f9b8bd1fb20db`, which already contains S2–S6.
The diagnostic candidate remains `023fbfd`; main is `d2f8b75` with protected
documentation WIP. Neither is the new writer's base. Existing run reports
`c7/c7-report.md` §§12–18 and S2–S6 reports/logs carry evidence and exceptions.
The old 144 failures/29 errors are historical. Twenty of those outcomes have
later named PASS evidence through S6; the other 153 have not been requalified,
NOT demonstrated still failing. Parameter IDs containing spaces must not be
reconstructed with whitespace splitting or copied from truncated log output.

**Capture checkpoint.** No new vocabulary or architecture. Spec0035 §§2–6,
AC1–10 and the preserved spec0007 consent/identity/provenance contract remain
the sources. In particular, spec0007 §“Location, format and identity” already
says repeated intentional saves create separately identified drafts, without
overwriting history. This resolves the earlier F6 *requirement* uncertainty;
the cross-peer implementation defect still needs a bounded repair. F3's
retention lifecycle classification remains open. No new retention exemption,
identity service or global cross-checkout coordination contract is implied.
Planning-contract v1; installed provenance unknown. Coverage: CW0 dispositions
remaining #114 obligations; CW1 preserves AC8's identity/consent contract;
CW2 preserves AC2–9 across native callers; CW3 closes AC1/10 removal/shipped
correspondence. C7 retains the existing AC1–AC15 final verification ownership.

**Approved execution envelope.** One sequential Pi writer in a fresh isolated
registered worktree under the preserved shared root, using Herdr tabs and
explicit `zai/glm-5.3:max`; parent owns audits, fixes and candidate designation.
A fresh Pi reviewer `openai-codex/gpt-6.1-sol:high` is proposed ONLY for the new
F6 production delta before dependent use, not a third review of settled C6
findings. One parent-authorized fix and one delta recheck; survivors go to the
owner. Mechanical fixture/docs work uses parent audit under an explicit
wave-wide exception. Verify actual host/model/tools/worktree and separate-tab
visibility as required by `orchestrate-implementation`; preserve existing tabs.
The checkpoint is **after a verified local result/isolated candidate handoff,
before target integration**. No main writes, push, PR, issue mutation, release,
external data/provider access, live R5, G1 work or plan0036 cleanup.

**Owner-approved recovery control:** after the incomplete CW2/CW3 pass and
STOP/retry breaches, the owner selected “Audit + Neustart (Empfohlen)”.
The preserved `6351bb3bcf3020242798ac4067e581eb2c1e0a15` partial is an
**unaccepted recovery base**, not C6 acceptance. Parent audits it first; a
fresh same-host/model Herdr Pi writer then edits only the remaining migration
and parent-accepted audit repairs. The writer may perform static reads/diffs,
but MUST NOT execute tests, collection, imports/probes, Ruff/lint/format/build
or self-repair failed checks. It releases source for parent audit/checks.
Parent alone runs the named budget on a stable released source revision,
reuses still-applicable greens and dispositions failures; no automatic replay
or reset of prior spent checks/review budgets. Existing authority for a
parent-dispositioned focused check remains limited to a named uncovered
reachable scenario after a relevant delta, not a coverage campaign. Old
execution deviations remain recorded, not retroactively approved. CW1 review
is settled; no third round. Full C7/target integration still needs its own grant.

**Subsequent bounded parent takeover:** after t50 released the unverified
recovery WIP, parent audit found RC1–RC5 (recurring suppression/comment-rule
violations, a misplaced probe-DB registry input, advisory citation/oracle
migration and a missed current standalone how-to introduction) and renewed
STOP/edit-guard deviations. The owner explicitly selected “Parent übernimmt
(Empfohlen)”. This authorizes the current parent Pi (`openai-codex/gpt-6.1-sol`,
`high`) to repair ONLY RC1–RC5 in the released isolated `c6-recovery-a1`
checkout, then run justified parent checks in the existing budget. No further
GLM writer or automatic additional fix round. Original criteria and prior
technical evidence remain; the deviations are not waived. Source-readiness,
exact freeze/candidate audit, protected main and separate C7 authority still bind.
After the advisory case's initial failure and one fixture delta, the owner
explicitly approved ONE further Computation-signal expectation correction
(page-relative locator, not a new full-citation requirement) and ONE same-case
delta run. This named exception preserves both red logs, all numerical/
provenance assertions and the remaining original budget; it is not an
automatic third round or authority to change production output.
After that delta exposed the unchanged admitted-base selection, the owner
separately approved ONE explicit human-fixture base-selection correction,
assertion of the chosen base and ONE same-case delta. Historical failures
remain; no warning/numerical relaxation, product change or implicit next retry.
After that delta reached the correct publication-ancestry refusal, the owner
explicitly approved ONE fast-forward of ONLY the temporary pytest fixture's
human branch to its first admitted commit before metadata authoring, plus ONE
same-case delta. Real main/C6-Source integration remains forbidden; no guard
waiver or automatic further attempt follows.

**Remaining parent source role:** after the Advisory and original query units
passed, the owner selected “Restliche Fixture-Fixes freigeben (Empfohlen)”.
The same parent may finish necessary fixture/caller/shipped-doc corrections
within the ALREADY approved C6 CW2/CW3 surfaces, including independent Source
fixture publication destinations and a genuinely missing typed Policy Entity
in the converted negative case. No product behavior/dependency/storage/
permission change, new writer, broader budget or C7 authority. Existing
one-fix/delta/STOP and exact acceptance/freeze obligations remain unchanged.

**Final documentation-only surface extension:** after the final CW3 scan
found stale public API/standalone-fallback descriptions in `a/query.py`, the
owner selected “Doc-Delta erlauben (Empfohlen)”. The same parent may correct
ONLY that module's docstrings/comments, prove executable AST identity and
run Ruff once for that path, then resume the existing C6 freeze/candidate
audit. No executable mutation, extra pytest, new writer, main integration or
C7 execution is authorized; all prior controls and evidence remain binding.
After source freeze, a parent-added over-strict group-write predicate stopped
candidate allocation before any mutation. Actual existing allocator directory
is owned by `volker:volker`, mode `0775`, with only Volker in that private
group and no POSIX ACL/world write. Owner selected “Einmal fortsetzen
(Empfohlen)”: authorize ONE corrected trusted-private-owner-group preflight
and the same local candidate allocation. No chmod, relocation, allocator
configuration change, new writer, target integration or C7 execution. Any
further failure stops; this is not a general handoff retry exception.
That corrected preflight passed, then Git refused the proposed nested branch
because the protected `orchestrator/open-issues-20261110/candidate` ref already
exists at `023fbfd`. No path/ref was created. Owner separately selected
“Geschwister-Ref freigeben (Empfohlen)”: ONE same-path allocation at sibling
`orchestrator/open-issues-20261110/candidate-c6-completion-a1`, after checking
all ancestor/descendant ref collisions. Preserve the old candidate, source
result and every existing restriction; no automatic further attempt.

#### CW0 — Reconcile the complete residual surface and classify retention

- [ ] Read the current definitions/callers on the frozen result and record
  dispositions in the EXISTING C7 run report, not a new ledger. Match remaining
  historical failure families and stale references to current native contracts;
  preserve later failures as evidence even where older greens exist. No
  blanket claim that an entire family passes after one helper correction.
- [ ] Review the A-test surface explicitly: `test_setup`, `test_init`,
  `test_cli`, `test_serve`, `test_evals`, `test_sources`, `test_query_results`,
  `test_multifact`, `test_contracts`, `test_git_authoring`, `test_git_admission`,
  `test_git_only`, `test_git_proposals`, `test_context_admission`, `test_review`,
  `test_git_source_access`, `test_mapping_inspection`, `test_data_signals`,
  `test_authoring`, `test_context_browsing`, `test_discovery`, `test_terms`,
  `test_status`, `test_answer_examples`, `test_mcp_toolsets`,
  `test_mcp2_compatibility`, `test_skill` (all `A/tests/<name>.py`), plus
  `I/lumio_local_context.py` and `I/lumio_managed_sources.py`. Trace shared
  helpers to additional callers before changing them; a required mutation
  outside this named surface is reported to the parent before extending scope.
- [ ] For F3 trace `supported_candidate`/`reconcile_knowledge` in
  `I/lumio_metric_mvp.py`, the actual managed test's manifest/registry/retained
  bytes, Core-generated Computation provenance in `a/context.py`, and native
  `required_coverage_missing` in `k/artifact_store.py`. The fixture marks
  existing pages synthetic before validation; finalization can generate a
  page referring to `model-retail_sales`, while only the baseline original is
  registered/retained. Establish which binding/bytes are actually required.
  A missing toy-fixture registration may be repaired with genuine exact
  source bytes and native registration/retention/bindings. Do NOT mark new
  pages synthetic, remove attribution or waive required retention to pass.
- [ ] If F3 is instead a production lifecycle defect, return that exact path,
  violated existing requirement and smallest repair proposal to the owner.
  Product/storage/retention changes are NOT silently included. Unaffected
  fixture work may proceed; C6 cannot finish while a required F3 outcome is
  unresolved. Re-shape only if the required behavior itself is ambiguous.

`no-new-test`: static correspondence and existing-evidence review only. Output:
owned residual groups and a precise fixture-versus-product F3 disposition.
No test collection, probes, broad baseline, new tracker or deletion quota.

#### CW1 — Restore distinct native Example identities across peer proposals

- [ ] Owned production mutation: `a/answer_examples.py` ID generation and its
  direct save usage only; owned regression surface:
  `A/tests/test_answer_examples.py`. No generic identity service/dependency,
  format migration or rewriting already persisted IDs/titles/records.
- [ ] Use the existing CLI+MCP save/search case with a controlled identical
  capture instant to reproduce two explicit same-question saves into peer
  unadmitted proposals. Preserve source-free sentinels, exact question bytes,
  distinct returned ID/path/Entity identity and no overwrite of either draft.
  Save/query consent, selected revision checks and historical provenance stay
  unchanged; do not hide the defect by supplying a common proposal selector.
- [ ] Repair once at the shared save seam; verify the peer case and existing
  same-proposal/after-admission repeat-save case. Expected behavior comes from
  spec0007's separately identified draft rule, not generated output. Scope the
  fresh independent review to this new unreviewed delta and these invariants.

`existing-check`, with a deterministic failing-first extension of
`test_native_example_save_search_never_opens_sources`; also run
`test_native_example_repeated_question_creates_distinct_drafts` once after the
ID change because that delta invalidates its earlier evidence. Run from A.
These are two distinct reachable scopes, not two new test layers. No broader
Example campaign or third review of C4/C6. Accepted new IDs are consumed by CW2.

#### CW2 — Complete native caller/fixture migration as one coherent batch

- [ ] Owned mutations: the CW0-listed A tests and the two I modules, with
  `I/lumio_metric_mvp.py` shared fixture edits only if caller tracing requires
  them. Reuse supported native fixtures and real public lifecycle operations;
  no legacy-shape translator, mock-success facade, second index/store or
  production change to accommodate stale tests. Preserve synthetic raw rows,
  independently authored SQL/oracles, exact permissions/provenance and scopes.
- [ ] Reconcile composite admission display/confirmation, native page paths,
  canonical source identities, producer metadata and API/entrypoint shapes.
  Example/ad-hoc/record-query cases explicitly author their required fresh
  selector/Table coverage before admission; do not silently raise the shared
  revision-2 default or rewrite frozen historical capability records.
- [ ] Convert old required-Context “collapse and continue” expectations to the
  approved pre-SQL refusal scenario on the native path; retain independent
  planner/grain/numerical checks and the distinction between optional metadata
  and mandatory Policy closure. A mere path replacement is not proof of this.
- [ ] Dispose each proposed retirement against the removed behavior and name
  the surviving invariant check. Do not delete live numerical/authorization/
  revision/retention checks, weaken malformed-input oracles, add skips/xfails
  or suppressions, or treat absent coverage as proof of obsolete behavior.
  Settled D1–D4 findings are not reopened; later reds still require explanation.
- [ ] Apply the fixture-only F3 repair only after CW0 establishes its branch;
  otherwise preserve the blocker. All other newly exposed production defects
  return to the parent/owner; this is not an unrestricted refactoring grant.

`existing-check`: use the shared validation units below, selected by actual
changed boundary. No automatic whole-module run per edit or renewed S2–S6
certification. Fixture/body changes invalidate only their affected evidence.
Output: every listed residual is migrated, evidenced already resolved, or
explicitly retired against a removed contract; an unexplained/unverified
migration obligation prevents the final source-ready claim.

#### CW3 — Shipped-surface reconciliation and C6 handoff to C7

- [ ] Inspect/fix only current surfaces named by #114: root `README.md`, A
  `README.md`, DA `tutorials/getting-started.md`, `how-to/{context-knowledge,
  git-authoring,pi-agent-workflow,shared-workspace-data}.md`,
  `reference/{context-knowledge,cli,git-authoring-migration}.md`,
  `a/skill_assets/SKILL.md` and affected packaged references,
  `products/ariadne/examples/retail-demo/` config/docs, and tracked
  `examples/trace-data/` authored content only if present. Missing historical
  paths are recorded as absent, not manufactured. No private inputs, globally
  installed skills, historical research, dependencies, lockfiles or versions.
  Load installed skill-editing guidance before modifying packaged skill text.
- [ ] Repeat #114's bounded stale-reference inspection over executable Core,
  shipped docs/assets/examples and live fixtures. Classify retained occurrences
  as current technical purpose, explicit old-format refusal, or historical/
  non-executable material. Permit mechanical removal of proven dead retired
  code, after caller proof and parent disposition, ONLY in #114's named
  `a/{context,ingest,author,authoring_context,answer_examples,discovery,
  lumio_context,proposals,validate,init,cli,serve}.py` paths that still exist.
  No working replacement backend or compatibility adapter may remain merely
  to satisfy old fixtures. This is not blanket refactoring or a zero-match
  deletion target. A reachable path requiring new behavior, a new source
  surface, or a retention/permission/storage change stops for scoped owner
  authority before mutation; CW1 is the only pre-scoped behavioral repair.
- [ ] Parent verifies the final diff, frozen descendant result, clean checkout,
  reused/invalidated evidence and all CW0 dispositions. Preserve all previous
  refs/worktrees and the diagnostic candidate; designate a separate isolated
  completion candidate only after acceptance, without touching target main.
  Record C6 **source-ready for required CI**, not installed/CI/live success.
- [ ] Hand that exact result to existing C7/#115 for its one assembled required
  CI/wheel/installed-journey qualification. C7 is not rerun per internal group,
  and this preparation does not authorize C7 execution. Migration failures
  found there remain C6 obligations, not permission to weaken CI.

`no-new-test` for docs/proven-dead deletion: stale-reference dispositions,
changed-file diff/lint and actual shipped command correspondence; reuse
AC10/packaging evidence only where its inputs match. Deleting a referenced
path is not mechanically dead: that branch needs a named existing boundary
check and separate parent/owner disposition before removal. A changed packaging input invalidates its affected C7 artifact.
No optional test slimming from plan0036 and no new verification framework.

#### Validation units and stopping rules for the approved wave

The units below are the approved execution budget; none ran during preparation. Use the
existing immutable Python3.14 pair environment, own Core/SDK roots, synthetic
HOME and Git-file/optional-locks0/no-bytecode guards. Existing environment
inadequate for a required check means stop, not an install/runtime switch.
Focused pytest is serial with `-x -vv`, faulthandler30 and timeout180s/INT/kill5.
Use actual cwd A, except I selectors use repository root with explicit paths.
Log complete commands/output and immediately captured real exits in existing
run context. Ruff once over changed Python paths after the applicable unit;
no implicit autoformat/autofix/tests or new suppressions. Under the approved
recovery control above, these execution steps belong ONLY to the parent after
writer ownership release; the migration writer has no runtime/check authority.

| Unit / consumed by | Named reachable failure and independent oracle | Smallest existing selection / reuse | Invalidation |
| --- | --- | --- | --- |
| V-ID / CW1 → CW2 | Same-second peer saves alias one identity; separately identified drafts required by spec0007, existing question/bytes and no-source sentinels | The two exact Example cases named in CW1; controlled peer case fails before repair, then once after; repeat-save case once after | Shared ID/save logic or selected proposal/revision |
| V-Lifecycle / CW2 | Old preview/page fields bypass the intended native lifecycle; source/Git prerequisites and bounded reader identity must remain truthful | `tests/test_git_admission.py::test_only_reviewed_validated_revision_activates_without_changing_candidate_bytes`; `tests/test_git_authoring.py::test_repair_state_persists_across_failures_retries_restarts_and_rebases`; `tests/test_setup.py::test_missing_git_prerequisites_pause_declarations`; `tests/test_context_browsing.py::test_invalid_paths_refuse_naming_the_rejected_path` | Relevant shared fixture, caller shape, canonical identity or lifecycle seam; reuse unaffected S2–S6 evidence instead of replay |
| V-Analytics / CW2 | Native Context migration loses grain/numerical rules, Policy-before-SQL or bounded results; golden fixture and independent SQL are the oracle | `tests/test_evals.py::test_golden_entry` (existing six variants); `tests/test_evals.py::test_get_metric_rejects_served_model_with_fanned_source`; `tests/test_multifact.py::test_t5_admitted_graph_returns_same_rows_and_context_over_runtime_cli_and_mcp`; `tests/test_query_results.py::test_query_result_limits[rows_fit_but_metadata_overflows]`; `tests/test_query_results.py::test_query_deadline_contract[expiry_between_phases_never_returns_success]`; `I/lumio_local_context.py::test_multi_metric_context_precedes_execution` only if its inputs changed | Serving fixture, actual graph/Policy inputs, envelope/deadline or source identity; no raw expected-number changes |
| V-Retention / fixture branch of CW0 → CW2 | Required retained original/binding absent or substituted; exact authored digests and native verified bytes, unchanged negative gates | `I/lumio_managed_sources.py::test_managed_admission_binds_profile_and_retention` after genuine fixture registration repair; otherwise blocked, no compensating mock or synthetic flag | Manifest/source/version/raw-byte/store/profile inputs |
| V-Shipped / CW3 | Installed guidance or command inventory advertises retired behavior | `tests/test_skill.py::test_skill_teaches_context_knowledge_and_typed_page_edits`; `tests/test_init.py::test_console_scripts_registered` only for their changed inputs; #114 stale-reference inspection; AC10 and existing dependency evidence otherwise reused | Packaged assets, entrypoint metadata, format-open order or dependency metadata |

This is a boundary-coherence budget, not proof that all historical failures are
gone. Broader required CI and built/installed identity verification stay with
C7. Additional focused checks require a named uncovered reachable scenario and
parent disposition before execution, not an automatic expansion on failure.

An expected failing-first bug repro is labeled in advance; every OTHER nonzero,
timeout or failed handoff prerequisite means STOP/preserve/report. Parent may
authorize one small in-scope correction and one delta check, reusing unaffected
greens; a repeated or material failure goes to the owner. Shell variable/setup
failures also stop: S6's handoff exception is historical, not future authority.
No unbounded repeat-until-green loop, review reset or deletion to meet counts.

**Exit:** all canonical #114 removal/caller/shipped obligations have concrete
current dispositions; no unresolved required F3/product defect, weakened oracle
or migration-only skip; accepted CW1 delta and bounded checks/reuse; verified
clean frozen C6 result ready for C7. Otherwise report the exact unmet condition,
not “C6 complete”. Only then pause for C7/target-integration authority.

**Current execution checkpoint — C6 source-ready for required CI.** Parent
accepted CW0–CW3 against the concrete requirement/evidence map in the existing
run report `c7/c7-report.md` §30. Frozen result
`8690e2e393744ade559ffe488995592c4bb69eed`, tree
`96eeee624fe2b9a41d9d7b5b5bc23b8468fdf7c1`, is protected by
`refs/heads/orchestrator/open-issues-20261110/result/c6-completion-wave/a1`.
The separate registered `c6-completion-candidate-a1` checkout uses branch
`orchestrator/open-issues-20261110/candidate-c6-completion-a1` at that EXACT
commit/tree; full porcelain is empty. Original S6 wave base and all earlier
refs/worktrees remain; main `d2f8b75` and diagnostic `023fbfd` are untouched.
Historical failures/STOP breaches and spent exceptions remain recorded,
not waived. This closes the source migration milestone, not all historical
test outcomes or clean type-analysis. Changed source bytes/packaged skill
require C7's own exact-build/wheel/installed qualification. No C7 execution,
main integration, push, tracker/PR changes, cleanup or publication follows.

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
