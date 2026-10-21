# Implementation plan: Modular Core and local Git authoring

> **Historical status — 2026-10-07:** Historical execution map: #32–#40 are closed and their implementation commits are present. The original proposed/approval-pending statements below are preserved as capture-time records, not current dispatch gates; ticket closure does not reconstruct missing historical approval. Current distribution naming is owned by [ADR-0018](../adr/0018-distribution-naming-ariadneai.md).

| | |
| :--- | :--- |
| **Status** | **Historical — #32–#40 closed; original approval provenance preserved below** |
| **Goal** | Extract shared core responsibilities, then deliver independent Git-backed authoring edits and exact-revision human admission, with Analyst/Authoring/Combined MCP adapters and migrated callers. |
| **Behavioral source** | [Specification 0009, approved revision 1](../specs/2026-10-02-0009-modular-core-git-authoring.md). Owner approved the in-chat baseline and accepted the written capture with “Well done. create the implementation plan (or plans)”. This authorized planning, not implementation. |
| **Architecture/vocabulary** | [ADR-0016](../adr/0016-modular-core-git-authoring.md), [CONTEXT.md](../../CONTEXT.md), and the specification's linked scoped amendments. |
| **Contract** | planning-contract v1; installed skill provenance unknown. |
| **Follow-up design boundary** | Owner-approved [specification 0010](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md) extends Context taxonomy/schema, measured evidence, applicability/admission and adapter capabilities. The owner subsequently requested “ticketzize”, authorizing [follow-up planning/ticket publication](2026-10-02-0010-context-layer-schema-and-identifiers.md), not implementation. Issues #41–#46 own that added scope and start after #40 is accepted; this plan and #32–#40 keep their existing deliverables. The follow-up plan §1 explicitly maps affected interfaces/consumers, including later native Analyst tool expansion. Both plans still require approval before execution; completing #40 does not claim specification 0010 is implemented. |
| **Task ownership** | GitHub issues [#32–#40](https://github.com/legout/ariadne/issues?q=is%3Aissue+in%3Atitle+%22Modular+core%22) own the canonical task bodies. This document owns shared interfaces, sequencing, coverage and global validation; no duplicate editable task bodies remain here. |
| **Ticket publication** | Owner authorized GitHub issue creation with “ticketize”. This does not imply plan approval or implementation, integration, code-publication or release authority. |

## 1. Readiness and execution boundaries

- One coordinated, sequential plan: extraction, Git identity, source approval, validation and admission share interfaces. Default to one writer in one implementation worktree; the feature's data-project proposal worktrees are separate. No parallel ownership is granted.
- Capture checkpoint: vocabulary is reconciled in `CONTEXT.md`; ADR-0016 and the amended earlier sources record owner decisions; approved specification revision 1 owns behavior and acceptance. A material behavior/interface change returns to shaping and blocks its consumers until reconciled and approved.
- Planning verified Git 2.43.0, Python 3.12.8, uv 0.12.19, Ruff 0.16.9, both lockfiles and the Agent's configured local `tau-mcp` checkout. No runtime tests, live-provider smoke or Git workflow tests were run while planning or ticketizing.
- **Execution blockers:** plan approval and separate execution authorization are pending. The checkout also has pre-existing changes in `src/ariadne/authoring.py`, `src/ariadne/example_review.py`, `src/ariadne/promote.py`, `tests/test_authoring.py` and design documents. G0 must establish an owner-accepted baseline without unauthorized stash/reset/commit/integration.
- Source documents are currently local/uncommitted. Tickets name their repository-relative paths, not nonexistent published revisions. Obtain the matching source checkout before execution; ticket publication does not authorize pushing these documents.
- Use Python >=3.12, current DuckDB/SQLGlot/PyYAML, Git and existing stdlib subprocess/filesystem/locking mechanisms. No new dependency, GitPython, backend abstraction or cross-platform locking project is planned.
- Retain one `ariadne-core` distribution and `ariadne` namespace; MCP is optional and `ariadne-agent` separately installed. Preserve numeric semantics, formats, caveats, compile/grain refusals and independent-attestation distinctions. Alternative backends, hosted Git, push/pull, HTTP/Open WebUI deployment and releases remain excluded. [#18](https://github.com/legout/ariadne/issues/18) is separate deferred HTTPS deployment work.
- Later execution defaults to supervised. Verify builtin `worker` and read-only `reviewer` are executable before dispatch and record resolved names in the orchestrator's runtime manifest. No worker/reviewer is launched by ticketization.

## 2. Concrete interfaces and layout

### Core extraction

- `execution.py`: concrete `DuckDBExecution`, owning the connection, catalog, bind operation, compiled-query statement guard/result collection and close. Internal profiling/audit code may use its connection for existing trusted operations; no external tool receives it. Move existing behavior rather than introducing a second compiler or changing guard order.
- `query.py`: `QueryRuntime`, retaining the current query/discovery/context/ad-hoc/example operations. `runtime.py` may retain `AriadneRuntime` as a single alias for its documented Python consumers; `serve.Facade` likewise aliases the same implementation. Compatibility names are not second implementations.
- `context.py`: move actual context-search/citation logic and deterministic OKF contract/enrichment/bookkeeping functions out of the workflow files. `author.py`, `ingest.py`, legacy `promote.py` and Query call the shared implementations.
- Keep `sources.py`, `render.py`, `semantic_graph.py`, `planner.py`, `grain.py` and `validate.py` as the shared Sources/Semantic implementation group. Do not add a pass-through `semantic.py` merely to label the group.
- `authoring.py`: orchestration and the public `AuthoringProject` interface. New `authoring_sources.py`, `authoring_inputs.py`, `authoring_semantic.py` and `authoring_context.py` hold the source/access workflow, bounded evidence preparation and layer-specific edits. Private staging compatibility remains only as needed by named legacy callers until G7 cleanup.
- `proposals.py`: local Git proposal identity, worktrees, revision-checked edits and persisted proposal state, plus the existing compiled ad-hoc staging/label operation extracted intact as `stage_ad_hoc`. Query calls that shared operation without importing Authoring or changing proposal stores. `admission.py`: human admission evidence, pinned snapshot resolution and its human CLI. `migration.py`: explicit legacy-artifact import, exposed only through the human command adapter.

### Project storage and authority

Use the data project's Git repository. Operator-owned state is under ignored `.ariadne/`: `proposals/<id>.json`, `worktrees/<id>/`, `source-approvals.json`, `validation/`, `snapshots/<commit>/` and `current.json`. Derive locations from the fixed project and system-generated proposal ID; callers do not provide worktree paths or operational-state files. Proposal branches use `ariadne/proposal/<id>`.

The proposal record contains `id`, `base_revision`, `candidate_revision`, expected admitted baseline, verified citation identities and persistent repair/validation state. Git supplies the artifact history; JSON records do not duplicate it. Validation reports wrap the existing `ValidationReport` with commit, complete artifact digest, resolved source-approval identity, verified evidence linkage, performed check set and `validator_identity` (core version plus validation/compiler implementation and check-configuration digest). `current.json` points to one immutable snapshot and its human admission/validation evidence; publish it atomically after the snapshot is complete. Serialize project admissions; admission acquires the project lock before the selected proposal lock and holds both through activation. Edits take only their proposal lock, so candidate bytes/identity cannot change mid-admission without serializing unrelated proposal work.

Candidate/snapshot artifact scope is `ariadne.yaml`, `data/seed_notes.md`, supported `semantic_layer/models/*`, `semantic_layer/graph.yml`, and existing OKF roots. Materialize/admit only this scope, never the entire Git repository. Explicitly stage allowed artifact identities, not `git add .`; do not newly commit credentials, uploads, databases, operational records or unrelated user files. Existing unrelated tracked history is not silently rewritten.

Resolve source paths against the configured data-project root, not each temporary worktree/snapshot. Compare the actual resolved registry identity with the operator's approved identity before any Git-mode source access. The candidate may propose source entries but cannot grant itself approval or widen the operator's document roots/URI permissions. Existing document conversion/retention and per-call bounds are reused. Approval records are keyed by resolved identity: granting access for a concurrent proposal does not overwrite the active snapshot's grant. No automatic revocation accompanies a new proposal.

Git operations use fixed argv through `subprocess`, not a shell or model-supplied Git commands. Validate IDs/commit references and artifact names before dispatch; paths and refs cannot become options. Missing Git, missing operator Git identity, dirty/inconsistent worktrees and command failures are explicit errors. Never alter global Git configuration or perform network operations. Reuse the current lock/atomic-write discipline; after an interrupted commit/state transition, preserve evidence and refuse further mutations until human resolution rather than automatically resetting history.

### Authoring call contract

`AuthoringProject(project)` fixes the host-owned project and operational state. Public methods return JSON-shaped envelopes, reusable by CLI, MCP and native Agent tools:

| Operation | Inputs and result |
| :--- | :--- |
| `start_proposal` | Optional known base revision; default to the current admitted revision or the human-created initial artifact revision. Returns proposal ID, base and candidate revisions. |
| `read_artifact` | Proposal ID, typed artifact identity and bounded part; returns candidate revision/body or a specific missing-artifact error. |
| `edit_proposal` | Proposal ID, expected candidate revision and one complete artifact edit; returns the unchanged or new candidate revision. Reject stale identity before writes. |
| `propose_sources` | Proposal ID, expected revision and typed source entries; stages a registry proposal and returns the resolved source digest, never opens it. |
| `inputs` | Proposal ID, document references/part and optional existing sampling bound; returns the approved profile and verified evidence. |
| `upload_document` | Existing bounded upload contract, under the operator input area; no Git artifact staging. |
| `validate_proposal` | Proposal ID and expected revision; finalize generated artifacts, commit any generated changes, validate the exact final commit and return that revision/report/errors. Never report validation for the earlier input commit if bytes changed. |
| `review_proposal` | Proposal ID/part; returns current/base revisions, change inventory, bounded effective content, citations, report and a review digest. Read-only; not approval. |

An artifact edit is a discriminated JSON object: model `{kind: model, name, content}`, graph `{kind: graph, content}`, page `{kind: page, section, name, content}`, or Seed Notes `{kind: seed_notes, content}`. Sources use the typed `propose_sources` operation. Names/sections are validated and converted into allowed artifact paths inside the core; no arbitrary path field, generated-page edit, deletion, rename or per-metric mutation is exposed. Retain existing payload/credential limits.

CLI additions to `ariadne-authoring`: `start`, `read`, `edit`, `validate`, and Git-aware `review`, `propose-sources`, `inputs`; use `--proposal`, `--expected-revision` and file/stdin input as appropriate. Preserve one-result JSON/error behavior. The human-only `approve-sources` gains proposal/revision/source-digest inputs for Git mode and records permission without editing the already committed candidate. Legacy approval remains available for its legacy route.

The human-only `ariadne-admit --project DIR --proposal ID --revision COMMIT --reviewed-digest DIGEST` displays the matching review/report and records explicit operator confirmation for that exact revision before activation. Review reading alone is insufficient. The confirmation and recorded admission bind the currently expected served baseline, candidate content and source identity. No model-facing adapter exposes this command or its callable.

After a human performs a local rebase/merge, human-only `ariadne-authoring reconcile --proposal ID --expected-revision OLD --revision NEW` records the clean new HEAD in the same proposal. It requires the current admitted revision in the candidate's ancestry, preserves repair history and previous evidence, and invalidates validation/review for the old revision. It neither merges nor clears an inconsistent interrupted transition or exhausted repair state. This is not an MCP/native Agent tool.

`QueryRuntime.open_project(project)` resolves the managed project's pinned snapshot and approved source configuration. It refuses a Git-managed project with no valid admission; it must not silently fall back to the proposal/root files. Existing explicit legacy artifact-root constructors retain their legacy behavior for existing fixtures/operators, never masquerading as the new Git route. Each session pins one coherent admitted revision; opening a later session can pick up a later admission. Recheck that session's bound source identity and snapshot bytes, and retain live mutable-source relationship audits.

## 3. Dependency order and validation units

```text
G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 → G8
```

Each task consumes accepted preceding interfaces. G8 requires acceptance of G1–G7 and explicit candidate-assembly approval. Shared write targets (`authoring.py`, source identity, adapter entry points and fixtures) make one sequential writer the smallest safe approach. Parallelization would first require stable interfaces and non-overlapping ownership.

The task index summarizes validation obligations; issues own the detailed named scenarios, checks and completion criteria. Existing checks cover mechanical extraction, one failing-first public-seam regression starts each `new-test` unit, and global checks run at baseline and candidate assembly rather than at every checkbox.

Reviews are parent-owned: low-risk work gets parent inspection, high-risk contracts get immediate review before consumption, and G8 gets one final candidate integration review. Paste the full guardrails reviewer contract, actual criteria, written conventions and real-use facts into every fresh reviewer prompt. Disposition findings before repair; at most one authorized fix pass and one delta-only recheck. Do not reopen settled findings or create extra sign-off artifacts.

## 4. Canonical task index

| Unit / ticket | Deliverable | Prerequisite | Risk / test obligation |
| :--- | :--- | :--- | :--- |
| [G0 / #32](https://github.com/legout/ariadne/issues/32) | Establish the implementation baseline | Plan approval and separate execution authority | low / `existing-check` |
| [G1 / #33](https://github.com/legout/ariadne/issues/33) | Extract shared execution, Context and Query | G0 accepted | low / `existing-check` |
| [G2 / #34](https://github.com/legout/ariadne/issues/34) | Isolated Git proposals and complete artifact edits | G1 accepted | high / `new-test` |
| [G3 / #35](https://github.com/legout/ariadne/issues/35) | Separate resolved-source approval and measured inputs | G2 accepted | high / `new-test` |
| [G4 / #36](https://github.com/legout/ariadne/issues/36) | Finalized effective-revision validation and review | G3 accepted | high / `new-test` |
| [G5 / #37](https://github.com/legout/ariadne/issues/37) | Human admission and pinned querying | G4 accepted | high / `new-test` |
| [G6 / #38](https://github.com/legout/ariadne/issues/38) | Three MCP surfaces and native Agent migration | G5 accepted | high / `new-test` |
| [G7 / #39](https://github.com/legout/ariadne/issues/39) | Legacy import, guidance and transition cleanup | G6 accepted | high / `new-test` |
| [G8 / #40](https://github.com/legout/ariadne/issues/40) | Candidate verification and installed distributions | G1–G7 accepted and candidate-assembly approval | normal / `existing-check` |

Ticketization transferred the task bodies without changing deliverables or interface definitions. Issues include source paths, file ownership conventions, validation/review obligations, checkbox steps, completion evidence, non-goals and linked blocking tickets. Their source documents remain local until separately authorized publication.

## 5. Requirement coverage

| Source criterion | Tasks/evidence |
| :--- | :--- |
| §1 one distribution, DuckDB/SQLGlot/OSI/OKF and deferred alternatives | G1 extraction; G8 wheels/global checks; no backend dependency changes |
| §2 shared modules, Authoring sub-modules and acyclic adapter dependencies | G1 shared execution/Query/Context; G2 shared proposals/layer edits; G3 sources/inputs; G4 shared checks; G7 cleanup |
| §3 independent complete artifact edits, bounded read/evidence, fresh authoring | G2 edit/read contract; G3 approved inputs; G4 effective validation; G6 adapters; G7 init |
| §4 expected revisions, multiple worktrees, no-op/crash/repair state, pre-validation generation and external evidence | G2 real Git mutation/refusal checks; G4 final-revision binding; G5 baseline conflict refusal |
| §5 separate source authority, pinned human admission, prior-state preservation | G3 source/document boundary; G5 exact revision/activation; G7 migration |
| §6 Query/ad-hoc/examples, optional MCP and three registered surfaces | G1 preserved checks; G5 pinned Query; G6 live toolsets/native tools; G7 separate stores |
| §7 explicit caller migration and no automatic legacy admission | G6 adapters; G7 import/guidance/cleanup; G8 installed checks |
| AC1 shared numeric/context behavior | G1 existing golden/money/guard checks; G5 pinned fixture query; G6 adapter parity |
| AC2 independent edits and inherited dependency validation | G2 complete artifact edits; G4 page/model-only regression |
| AC3 concurrent proposals and advanced admitted baseline | G2 isolation/stale edit; G5 refusal/revalidation before activation |
| AC4 exact reviewed/validated commit | G4 final report/review identity; G5 admission refusal variants |
| AC5 onboarding before first metric and separate access approval | G3 committed-registry canary; G6 missing catalog isolation; G7 initialization |
| AC6 Git failures/restarts/rebase and preserved prior state | G2 HEAD/state failures; G4 repair persistence; G5 activation failure |
| AC7 MCP capability surfaces | G6 actual stdio registry/refusal test and existing native role checks |
| AC8 existing proposal stores/labels | G1/G7 existing ad-hoc, standalone ingestion and Answer Example checks; G5 managed-runtime stores |
| AC9 distribution and migration | G7 preservation regression; G8 installed core/Agent checks |

## 6. Global validation and residual risks

No GitHub Actions workflow was found during planning. Use the established commands once at baseline and once after candidate assembly; focused commands and distinct failure scenarios live in the canonical tickets:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
uv lock --check
uv build
(cd ariadne-agent && uv run python -m pytest)
(cd ariadne-agent && uv run ruff check .)
(cd ariadne-agent && uv lock --check)
(cd ariadne-agent && uv build)
git diff --check
```

Probe changed implementation paths with supported LSP servers; cached empty diagnostics alone are not evidence. Installed-wheel checks must exercise built artifacts rather than checkout imports. Report converter/provider/optional-extra skips explicitly. Fake-provider checks do not prove live-provider compatibility; any optional live smoke needs an operator-approved endpoint and credentials and is reported separately.

Real use comprises host-fixed Python Agent sessions, local JSON CLI, stdio MCP, operator source/document configuration, model-supplied artifact/tool inputs and compiler-produced SQL over synthetic fixtures. Touched future security boundaries are artifact/proposal inputs reaching Git/filesystem and proposed registry entries reaching source/document access. Assets are proposal/served bytes and approved data/credentials; reachable failures include escaped names/options, credential-bearing artifacts, unauthorized resolved locations and fabricated approval/validation claims. Trusted internal callers and human-owned local configuration/Git operations are not hostile by default. Hosted identity/TLS/Git threats are outside scope.

Residual risks are baseline ownership; root identity across worktrees/snapshots; timestamp regeneration breaking no-op revisions; the legacy digest's excluded bookkeeping versus the new full binding; changed authoring/native tool payloads; and ignored legacy layer directories. The canonical G2–G8 checks cover these. A new workflow or incompatible semantic-format change returns to shaping rather than expanding a ticket.

**Handoff:** nine GitHub tickets are published at the owner's request. Plan approval and separate execution authority are still required; candidate assembly, target integration and code/release publication retain their gates. No implementation, runtime test, commit, push or release is performed by ticketization.
