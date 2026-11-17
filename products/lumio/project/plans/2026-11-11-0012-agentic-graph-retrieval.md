# Plan 0012: Bounded agentic graph retrieval and Global Search

Status: **owner-approved plan revision 1, ticketized**. Created: 2026-11-12.
Overview editorial revision: **2**, 2026-11-12; no behavior/task-scope change.
Execution authorized: **no**. Tracker publication: **authorized and performed**.

Owner **“ok. ticketize”**, 2026-11-12 approved plan0012 r1 and its named epic,
four feature issues, frozen source publication and scoped cross-reference
comments. This grants no implementation, child dispatch, product tests, package
installation, model/fixture/credential use, Git commit/push, integration,
deployment or release. Later execution remains separately gated by repository
AGENTS and the installed orchestration/validation contracts; this is not a
second executable workflow.

## Goal, authoritative sources and capture checkpoint

Deliver spec0012 written r2's four capabilities through the existing Core SDK,
optional LanceDB adapter, Workspace tools and Pi host, without a new server-side
agent or canonical content format. The model-free/cloud-free base SDK, exact
Published Versions, scoped Evidence and human admission remain unchanged.

- Behavior: [spec0012 written revision 2](../specs/2026-11-11-0012-agentic-graph-retrieval.md),
  approved by “ok. create the plan”, 2026-11-12. Includes request-wide numerical
  defaults, exploratory-only global conclusions and report retention/readback.
- Architecture: [ADR0033 revision 2](../adr/0033-agentic-graph-retrieval-and-community-evidence.md).
- Vocabulary: [Lumio Context](../../CONTEXT.md).
- Execution ownership: [epic #116](https://github.com/legout/ariadne/issues/116) owns V; the four feature issue
  bodies below own their canonical editable tasks. **No duplicate local task
  bodies remain.** Planning Contract version 1; installed provenance `unknown`.
- Capture: terminology and accepted architectural rationale are recorded;
  AC1–AC22 own behavioral acceptance. Pi budget hooks, real model behavior and
  optional installation are qualification gates, not assumed facts.

### Exact approved source readback

Sources remain uncommitted/unpushed. The epic retains these byte-digested frozen
approval snapshots, including the full pre-transfer task decomposition and
shared paths/baseline/evidence policy. They record approval history, not a
second editable execution map or a claim about remote main:

- [Spec0012 r2](https://github.com/legout/ariadne/issues/116#issuecomment-6820554723)
- [ADR0033 r2](https://github.com/legout/ariadne/issues/116#issuecomment-6820555802)
- [Plan0012 r1 before task-body transfer](https://github.com/legout/ariadne/issues/116#issuecomment-6820555227)
- [Approved glossary](https://github.com/legout/ariadne/issues/116#issuecomment-6820556393)

Code inspection baseline: `d2f8b75c0970267b42b0d04f5359ae603b7998a9`.
Preserve unrelated dirty Context-foundation documentation. Refresh actual code
and source correspondence before execution or worktree handoff; issue status
alone does not establish prerequisite delivery.

## Canonical task ownership

| Task | Canonical body | Slice |
| --- | --- | --- |
| G1 | [#117](https://github.com/legout/ariadne/issues/117) | Bounded Core/Workspace/Pi planning, persistent budgets/resume; Pi 1.5.2 capability checkpoint first |
| G2 | [#118](https://github.com/legout/ariadne/issues/118) | Typed bounded Graph Context with exact supporting page Evidence |
| G3 | [#119](https://github.com/legout/ariadne/issues/119) | Separate communities, retained unverified reports/bundles, exact readback and Global Search |
| G4 | [#120](https://github.com/legout/ariadne/issues/120) | Optional semantic Entity-resolution candidate; adoption disabled pending V |
| V | [Epic #116](https://github.com/legout/ariadne/issues/116) | One installed journey, actual-encoder comparison, owner adoption decision and handback |

The epic's native sub-issues are #117–#120. New native blocked-by edges are
#118 ← #117, #119 ← #118, #120 ← #119 only; older issues acquire no new edges.
No task or checkbox is complete merely because its ticket was published.

## Reconciliation with existing issues

Issue bodies/states were re-read through `gh` during planning on 2026-11-12.

| Existing issue | Consumed result / preserved boundary |
| --- | --- |
| [#103 / R1](https://github.com/legout/ariadne/issues/103), open | Supplies the authorized immutable view, exact version/Entity readback, 16,000-character per-call bound, and operator cache convention. G1's managed route waits for its accepted result. Graph tools and opted-in query embedding remain new follow-up work; do not expand R1. |
| [#112 / C4](https://github.com/legout/ariadne/issues/112), open | Consumer of the same stable identity contract for guides/Examples, not a producer of a new planner prerequisite. Preserve its pinned/integrated behavior. Reconcile against its accepted API if it lands during G1–G4; do not block independent local SDK work on the whole analytics migration. |
| [#107 / R5](https://github.com/legout/ariadne/issues/107), open | Owns Zero-Index/BM25 evaluation and its existing live journey. G4 semantic adoption consumes that evidence; it does not add embeddings to R5 or repeat R5's upload/auth/S3 journey. Missing baseline evidence blocks adoption, not preparation of the local vector candidate. |
| [#85](https://github.com/legout/ariadne/issues/85), [#108](https://github.com/legout/ariadne/issues/108), open | Keep approved scope/order and remaining live qualification. New epic links them as foundations, not replacement completion claims. |
| [Ariadne #95](https://github.com/legout/ariadne/issues/95), closed | Reviewed enrichment and identity ambiguity remain unchanged. Reports/candidates confer no merge or admission authority. |
| [Lumio #167–#173](https://github.com/legout/lumio/issues/167), closed | Reuse graph/Claim/trace/lexical candidate foundations. G4 adds semantic resolution rather than reimplementing them. |


Ticketized 2026-11-12. Scoped comments only:
[#85](https://github.com/legout/ariadne/issues/85#issuecomment-6820630598), [#108](https://github.com/legout/ariadne/issues/108#issuecomment-6820632005), [#103](https://github.com/legout/ariadne/issues/103#issuecomment-6820633491),
[#107](https://github.com/legout/ariadne/issues/107#issuecomment-6820634853), [#112](https://github.com/legout/ariadne/issues/112#issuecomment-6820636444).
Existing bodies, states and native relationships are preserved; no R5 dependency
on this follow-up is added. Refresh issue/code correspondence before execution.


## Sequence and dependency contracts

One sequential candidate line: **G1 → G2 → G3 → G4 → V**. Shared records,
Workspace registration, Pi hooks, and packaged guidance make parallel writers
counterproductive. Feature tasks are vertical slices with public CLI/tool
readback, not schema/API/UI layers waiting for later wiring.

| Task | Prerequisites | Produces |
| --- | --- | --- |
| [G1](https://github.com/legout/ariadne/issues/117) | Approved plan + execution grant; #103 accepted before managed wiring; host capability checkpoint below | Explicit/host-interpreted basic/local/path plans, request-wide budget, resumable identity, truthful unavailable global mode |
| [G2](https://github.com/legout/ariadne/issues/118) | G1's accepted plan/authorization/budget contract | Bounded Graph Context with Evidence references and matching renderings |
| [G3](https://github.com/legout/ariadne/issues/119) | G2; compatible optional community dependency | Separate scoped hierarchies, exact retained report sets/bundles/readback, operator preparation, global thematic retrieval |
| [G4](https://github.com/legout/ariadne/issues/120) | G3 for assembled sequencing; G1 budget/identity | Optional Entity-vector/query-encoding candidate and fixed evaluation inputs; semantic adoption remains disabled pending V |
| [V (epic)](https://github.com/legout/ariadne/issues/116) | G1–G3 boundaries accepted; G4 candidate accepted for verification, not yet adopted; R5 baseline plus named host/model/fixture authority; required CI | One assembled installed journey, semantic adoption decision, and evidence-backed handback |

A local-only checkpoint is not the delivered managed feature. If #103 or the Pi
capability is unavailable, complete only explicitly authorized independent work
and report the blocked part; never mark G1 or the whole objective complete.
If G4's evaluation does not justify adoption, hand back the comparison with
semantic mode disabled/unqualified; do not change the source's adoption gate.

### Small shared interface map

Names below are proposed producer APIs/tool contracts, not a replacement for
spec0012's behavior. Keep records additive and export through `lumio_wiki`.

| Interface | Inputs → outputs |
| --- | --- |
| `start_query` / `query-step` | exact namespace/publication + authorized view + explicit mode or validated understanding + request key → plan/request ID, effective budgets, next permitted step/outcome |
| `graph_context` | that plan + stable seed IDs + existing bounds → Graph Context, exact member Evidence/Citations, accounted omissions |
| report preparation / activation | operator-selected exact view/scope + job budget + key → hierarchy/manifest; host-authored report bytes → structurally validated immutable report-set ID |
| `read_report` | exact set/report/section IDs + bounds → stored generated-unverified bytes/digest, bundle references, omissions |
| `global_context` | pinned plan/report set + question → ranked sections, deduplicated coverage, member Evidence and remaining allowance; host supplies synthesis |
| `entity_candidates` | authorized question text/query vector + compatible model identity + thresholds → exact/lexical/semantic candidates, seeded ID or ambiguity/unavailable outcome |
| `validate_query_citations` | plan + answer's report/member citation references → structural validity/errors, never a semantic truth verdict |

Workspace resolves authentication/capabilities and the visible set. Core receives
an already authorized view, not credentials. Preparation/activation/deletion
remain operator actions; ordinary Reader tools cannot invoke them. Keep the
standalone MCP distribution read-only. Every managed new retrieval tool retains
#103's integrated-mode refusal; this plan adds no independent moving view behind
an Ariadne Bound Release. #112's existing governed route is unchanged.

## Assigned verification and evidence boundaries

The canonical issues own VG1–VG4; the epic owns V and its final verification
body. All checks are **planned, not executed**. Reuse unchanged proof; add a
focused check only for an uncovered reachable scenario. Focused Python checks
are serial; full product pytest uses exactly `-n 4`, never `-n auto`.
Required repository CI, installed wheels, Pi guard and disclosure guard remain
binding at their named delivery gates. No independent review, runtime/model
qualification, install or product test is claimed by ticketization.

The frozen approved plan preserves exact K/L/W/C/D roots, source/test/fixture
ownership, security assets/real caller, interface review timing and stop
conditions; issue bodies link that shared context instead of copying it.

## Requirement-to-task and evidence ownership

A mapping proves documentary coverage only. The task/check must establish the
specific scenario; it cannot redefine the expected result.

| Criterion | Producer task | Evidence owner |
| --- | --- | --- |
| AC1 | G1; G3 adds prepared global mode | VG1; V mode journey |
| AC2 | G1 | VG1 plan transitions; V host refinement |
| AC3 | G1 | VG1 unavailable-global result |
| AC4 | G2 | VG2 accepted Claim versus navigation |
| AC5 | G2 | VG2 structured/text rendering |
| AC6 | G3 | VG3 separate graph inputs/artifact scope |
| AC7 | G3 | VG3 isolate/overlap; V coverage disclosure |
| AC8 | G3 | V thematic answer with exact member passages |
| AC9 | G3 | VG3 binding rejection/unverified label; V false-policy example |
| AC10 | G3 | VG3 structural citation validation |
| AC11 | G1–G3 | VG1 managed hidden-marker checks extended at touched graph/report boundary |
| AC12 | G3 | VG3 A/B readback; V installed citation reopen |
| AC13 | G3 | VG3 request-key and failed-activation behavior |
| AC14 | G4 | VG4 exact/threshold/ambiguity; V genuine encoder |
| AC15 | G4 | VG4 plus managed candidate assertion in VG1 fixture |
| AC16 | G1–G4 | V existing isolated-wheel gates plus communities extra |
| AC17 | G4 | VG4 query/model mechanics; V real-encoder comparison |
| AC18 | G1–G4 | Applicable native CI and V no-feature/basic route |
| AC19 | G1; G3/G4 debit it | VG1 service/Pi enforcement; V real host accounting |
| AC20 | G3 | V partial-coverage “most common” refusal/narrowing |
| AC21 | G3 | Extended existing Workspace backup/restore node |
| AC22 | G1–G4 | V actual Pi + installed standalone CLI |

## Next execution gate

Ticket publication is complete; implementation is **not authorized**.
Specific prerequisites remain: #103's accepted managed view, qualified Pi 1.5.2
budget hooks, compatible optional NetworkX installation, #107 baseline evaluation
before adoption, and authority for the final named host/model/fixture journey.
Do not silently switch runtimes, weaken Evidence Bundles or narrow the approved
four-feature goal when a gate fails. Report the blocked capability and needed
decision; no integration/push/release authority follows from ticketization.
