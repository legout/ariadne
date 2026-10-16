# Specification: Modular Ariadne Core and Git-backed authoring

**Proposed scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; its written review is pending. All durable authored Core artifacts use the existing Git route; ad-hoc execution is ephemeral and explicit persistence uses existing Authoring edits. The owner excludes legacy migration/compatibility and real-project reset; the former retained exceptions are retired. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1** |
| **Approval** | Owner, Pi conversation 2026-10-02: retained DuckDB; selected independent model/page editing, permission for breaking interfaces, split MCP toolsets plus the combined server, Analyst ad-hoc proposals and confirmed Answer Examples, and Git-backed proposals now with local Git first. Approved the complete in-chat baseline with “yes. looks good.” After the written specification was presented for review, approved proceeding to planning with “Well done. create the implementation plan (or plans)”. Approval covers revision 1 and implementation planning, not implementation, integration or publication. |
| **Scope** | One modular `ariadne-core` distribution; Authoring, Query and DuckDB Execution workflows over shared artifact modules; multiple Git-backed full-bundle authoring proposals; independent artifact editing; revision-bound validation, review and local human admission. |
| **Sources** | [Vocabulary](../../CONTEXT.md), [local-first runtime](2026-09-23-0001-local-artifact-runtime.md), [harness-led authoring](2026-09-24-0005-harness-led-authoring.md), [context retrieval](2026-09-23-0002-context-retrieval.md), [Answer Examples](2026-09-29-0007-answer-examples.md), [multi-fact planner](2026-09-30-0008-multi-fact-planner.md), [ADR-0016](../adr/0016-modular-core-git-authoring.md). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |
| **Approved native-source extension** | Owner approved written revision 1 with “approved.” in the Pi conversation 2026-10-13, captured in [approved specification 0022](2026-10-13-0022-native-duckdb-sources.md): one native DuckDB source type, including trusted local/remote view catalogs, as a scoped exception to this revision's new-connector non-goal. Shared Sources/Execution ownership, exact human source approval, project/object permissions, credential boundaries, compile gates and human admission remain binding. No broader connector/backend scope, source access, target-integration or publication authority is supplied by this notice. |
| **Later bounded-query amendment** | Owner-approved design [0014, revision 1](2026-10-08-0014-bounded-record-queries-and-results.md), 2026-10-08: Query gains non-metric ungoverned record selection and coordinates shared result/transport preflight before any ad-hoc staging. Output refusal stages nothing. Existing module ownership, compiler/source checks, managed snapshot rules, graph admission and native fixed-role permissions remain binding; no legacy migration or execution authority is implied. |
| **Later scoped Context extension** | Owner-approved [specification 0010, revision 1](2026-10-02-0010-context-layer-schema-and-identifiers.md), 2026-10-02: adds Dataset Overviews/general structured References and richer schema metadata, term resolution, typed mapping inspection and context-only Git admission. This explicitly amends the new-page-type/unchanged-Context-profile non-goals and missing-catalog behavior below, while preserving shared ownership, source approval, revision-bound review/validation and human-only admission. The existing plan/tickets do not acquire this scope automatically. |

## 1. Purpose and scope

Separate workflow orchestration from artifact representation and database execution, without duplicating Ariadne's measurements, compilation, context rules or admission checks. Allow a caller to revise one OSI model or one Context Layer page without resubmitting unchanged artifacts. Use Git's revisions and isolated worktrees for concurrent authoring proposals rather than building a second branching/merge system.

Keep `ariadne-core` as one distribution and retain the `ariadne` import namespace. `ariadne-agent` remains a separately installed conversational host, not part of the deterministic core. Its existing fixed-role session contract is not removed by splitting the core or MCP registrations.

DuckDB remains the sole execution engine; SQLGlot remains the compiler representation. OSI and OKF formats, metric meaning, grain/cardinality rules, cited caveats and independent-attestation distinctions remain unchanged. [Alternative execution backends](../research/2026-10-02-execution-backend-options.md) are deferred.

Non-goals: Ibis, native Polars compilation, backend plugins, new connectors, ETL/database management, per-field/per-metric editing machinery, hosted GitHub/GitLab integration, remote Git publication, HTTP/Open WebUI deployment, arbitrary model-directed Git/shell/file operations, autonomous source approval or admission, and new Context Layer page types. No new multi-fact ad-hoc route is introduced.

## 2. Module ownership

These are responsibility groups, not a requirement for a new abstraction or directory for every row.

| Module | Interface responsibility |
| :--- | :--- |
| **Authoring** | Coordinate typed source proposals, measured inputs/document evidence, independent artifact edits, candidate validation and review. Internal source, semantic and context editing modules use the shared artifact representations. |
| **Query** | Discover datasets/metrics, assemble relevant context, request governed measurements, coordinate compiled ad-hoc proposals and explicitly confirmed Answer Examples. Retrieval is part of Query, not the name of the entire workflow. |
| **Execution** | Own DuckDB connections and catalog inspection; perform guarded database operations used by Query, profiling and validation. It does not own business narrative, artifact admission or a second compiler. |
| **Shared Sources** | Parse the registry, resolve source identities and apply operator-approved access rules. Source types are not execution backends. |
| **Shared Semantic** | Load OSI, normalize the graph, resolve metric dependencies and safe paths, compile through SQLGlot, and own shared grain/cardinality rules. Database-backed checks use Execution. |
| **Shared Context** | Load/search OKF, resolve citations and apply page contracts and deterministic generated bookkeeping. It guides interpretation, never computes metrics. |
| **Shared Proposals** | Coordinate Git authoring identities/revisions, edits and review/admission evidence; reuse proposal rules for existing staged operations without conflating their stores or review meanings. |

CLI, MCP and `ariadne-agent` are adapters over these interfaces. Core modules do not import optional MCP transport or depend on a model to validate or execute. Execution does not import workflow modules. Query can stage an ad-hoc definition without importing the Authoring Agent or invoking an LLM. Existing implementations in `sources.py`, `render.py`, `semantic_graph.py`, `planner.py`, `grain.py`, `validate.py`, `profiler.py`, `runtime.py` and the authoring/context modules are extracted or moved, not independently reimplemented.

## 3. Artifact editing interfaces

The host configures one data project and its operator-owned source/document access. Callers address proposal identities within that project, not arbitrary repository/worktree roots, credentials or filesystem paths.

The authoring interface must support:

- Start a proposal from an identified base artifact revision, including an empty-project onboarding case.
- Read/list the candidate's documented artifacts and measured evidence in bounded responses.
- Propose source-registry changes as typed, credential-free data; access approval remains a separate human operation.
- Add or replace a complete OSI model, its supported graph declaration, a complete OKF page, or proposed Seed Notes. An edit targets a layer-specific documented identity, not a generic file-write capability.
- Validate the effective candidate, and return separate schema/context, compile/bind and live grain/cardinality outcomes.
- Review its changes, effective artifact inventory/bodies, evidence/source identities, candidate revision and validation state.

Exact command/tool spelling and Python parameter types belong to the implementation plan, subject to this behavior. Individual field, relationship or metric mutation interfaces are not required. Artifact deletion/rename and automatic merge-conflict resolution are not added by this revision.

Unchanged artifacts are inherited from the base revision. A model-only or page-only edit need not resend the remaining bundle, but cannot skip its relevant dependency checks. Empty-project authoring remains usable before the first admitted metric; missing served models affect query operations, not proposal creation or approved-source profiling.

## 4. Git proposal lifecycle

Git is used in the **data project**, which need not be Ariadne's code repository. A proposal records its identity, branch, base artifact commit and current candidate commit. Each active writer owns a separate worktree. Multiple proposals may coexist; two writers must not mutate one proposal/worktree simultaneously.

Artifact edits require the expected candidate revision. A stale revision or conflicting writer is refused without overwriting the candidate. A successful edit records the new candidate revision; repeating an identical edit against its still-current revision must not create another distinct candidate. Uncommitted changes are visibly drafts, not validated or admitted state.

The effective candidate is the base project state plus the explicit edits. Deterministic generated artifact content (such as indexes and computation enrichment) is finalized **before** the candidate commit is validated. Agents cannot author system-owned approval or attestation claims. No post-review decoration may change the bytes being admitted.

Validation evidence is stored separately from the committed artifact content to avoid changing the revision it describes. It binds the exact candidate commit, consumed artifact digest, approved resolved source identity, validator identity and checks performed. A compile-only or failed report is not sufficient admission evidence.

Review exposes the exact revision, diff, effective content, validation scope and caveats; reading a review response is not sign-off. Repair, rebase or merge creates a different revision and invalidates earlier review/validation evidence for admission. If the admitted baseline has changed since the proposal started, it must be reconciled explicitly and revalidated before replacing served state; admission must not silently erase another admitted proposal's changes.

Validation failures leave a recoverable proposal with errors, not a served revision. The existing bounded authoring repair policy is not silently reset by creating another commit. Missing Git, conflicts, incomplete transitions or inconsistent proposal/revision metadata produce actionable errors; do not fall back to a mutable served checkout, discard edits or silently reset a proposal. Ordinary Git history is not proof of human review.

## 5. Source approval and artifact admission

Source approval and artifact admission are distinct decisions. A proposed or committed `ariadne.yaml` entry never grants permission to connect to a new location. Worktree-relative paths must resolve to the operator-approved source identity; changing a checkout must not silently retarget that identity. Credentials, uploaded evidence, database files and operational approval records are not committed merely because a proposal is created.

The operator's configured document roots and exact approved object-store references remain authoritative; proposed configuration cannot widen those permissions. Existing upload limits, credential rejection, citation retention and evidence-conversion behavior remain in force.

A local human-operated admission interface admits an explicitly reviewed candidate revision only with full, matching validation evidence and approved source identity. It refuses dirty/different artifact bytes, stale or partial checks, an unreviewed revision and unresolved conflicts. Admission is never an MCP tool or a skill-invocable agent action.

The runtime serves a pinned admitted artifact revision, not a proposal branch's mutable working tree. Activation must preserve the prior served revision if the new snapshot or admission evidence cannot be established coherently. Approval evidence is separate from reviewed artifact bytes. Governed answers identify the admitted revision/route, retain their metric and Policy context, and distinguish technical validation, human review and independent numerical attestation. Mutable-source relationship checks still run as required by the multi-fact contract.

This is the new local Git Review Admission route for full-bundle authoring. Hosted PR approval, remote push/pull and production deployment automation are deferred; their later integration must satisfy the existing same-revision review/validation contract.

## 6. Query and MCP behavior

Query retains governed metrics, safe detail queries, dataset discovery, Context Layer retrieval, Answer Example search, single-dataset ad-hoc definitions and explicit Answer Example submissions. No request bypasses SQLGlot compilation, statement/bind checks, grain/cardinality checks or read-only query execution. Execution is not exposed as an `execute_sql` tool.

Ad-hoc answers remain `governed: false` and leave unadmitted proposals. Their existing staging behavior and explicitly draft-labeled discoverability remain; importing one into a Git authoring proposal is explicit, not automatic admission. Answer Examples retain their separate store, explicit confirmation, bounded historical evidence and independent human review meaning. Standalone document ingestion remains standalone; this revision does not force it into a full Git authoring bundle or authorize direct served writes.

Expose **Authoring**, **Analyst** and **Combined** MCP registrations over the same core. Authoring exposes proposal editing, measured inputs, validation and review. Analyst exposes Query operations, including ad-hoc proposals and confirmed Answer Examples. Combined exposes their union. All are project-bound; none exposes source approval, artifact admission, arbitrary file/shell/Git execution or raw query execution. The registrations are tool-surface separation, not a new account/authentication system.

Local CLI/Python usage remains available without MCP. The combined server remains available, but retaining it does not promise every old authoring payload remains compatible: breaking interfaces are permitted and must be explicitly mapped during migration. Query numeric semantics, required caveats and refusal behavior remain compatible even where extra revision provenance or new interface parameters are needed.

## 7. Migration and failure behavior

The implementation plan must map every affected public caller, command, tool and skill to its replacement or retained interface, including `ariadne-agent` and the combined MCP server. Permission to break interfaces is not permission to silently lose functionality or change numerical semantics.

Existing admitted artifacts and staged evidence must not be automatically discarded, relabeled as Git-reviewed or served from a new revision without the required review/validation. The migration must provide an explicit human-operated path to establish an initial Git artifact revision and admission, preserving outstanding legacy proposals for review. Existing standalone-ingest and Answer Example destinations keep their scoped contracts.

Source-access, artifact-path, credential and payload checks remain at external-input interfaces. Wrong project/proposal identity, stale revision, unauthorized source/document, malformed artifacts, failed grain checks, unavailable bind/audit, Git conflicts and stale review/validation fail explicitly. They cannot trigger fallback raw SQL, automatic admission, silent conflict resolution or hidden replacement of another proposal.

## 8. Observable acceptance examples

1. **Shared query behavior:** existing retail-demo golden/money/guard scenarios retain their values, caveats and governed/ad-hoc labels through Python, CLI and Combined MCP. Analyst MCP has the same Query behavior. DuckDB and SQLGlot remain the actual execution/compile path.
2. **Independent edits:** start from an admitted bundle, replace one OSI model or one OKF page without resending unchanged files, and review the change against the inherited effective bundle. A broken cited Policy or unsafe relationship blocks admission even when only one file changed.
3. **Concurrent proposals:** two branches/worktrees start from the same base. Editing proposal A leaves B unchanged. A stale edit to A fails. After A is admitted, B cannot replace served state without explicit reconciliation, renewed validation and review of the resulting revision.
4. **Exact revision:** validation/review for commit C cannot admit a dirty checkout, commit D, a changed approved source identity or a partial report. Admission of matching reviewed/validated C serves its pinned artifacts and provenance. A subsequent authoring edit does not change governed answers until separately admitted.
5. **Fresh onboarding:** create a proposal in a project with no admitted metrics. A new source entry cannot be profiled before operator approval, even if committed; approved sources and document evidence can be measured, then models/pages drafted and reviewed. Analyst's missing-catalog error does not block this flow.
6. **Git changes and failure:** repair/rebase/merge requires validation again. Missing Git or a conflict reports the actual blocker and preserves evidence and prior served state. Restarting cannot turn an incomplete proposal into an admitted one or silently reset exhausted repair state.
7. **MCP surfaces:** Authoring has editing/input/validation/review operations but no Query-only measurements; Analyst has Query and its explicitly allowed proposal-producing operations but no full-bundle editing. Combined has both. No surface calls source approval, admission, arbitrary Git/shell/files or raw SQL.
8. **Other proposals:** ad-hoc metric output remains ungoverned and staged; invalid definitions execute/stage nothing. Answer Example saving requires explicit confirmation and does not modify the governed catalog. Standalone ingestion remains separately reviewable and never directly serves pages.
9. **Distribution and migration:** base core imports/CLI work without MCP or the Agent package. A documented migration preserves legacy pending work and updates affected callers; a Git commit of existing files alone is never represented as admission.

Focused existing checks cover preserved numeric and transport behavior. New Git proposal, independent-edit and revision-admission behavior needs focused failing-first checks during implementation. This documentation change has an `existing-check` obligation: inspect the approved criteria, local links and documentation diff; no runtime tests are claimed by capturing a design.

## 9. Shaping capture and handoff

- **Vocabulary:** `CONTEXT.md` distinguishes Git-backed Authoring Proposals and Candidate Revisions from existing ad-hoc Proposals and legacy Staging; Git Review Admission now includes the new local authoring route. Internal module names are not new domain entities.
- **Decision:** ADR-0016 records shared modules within one core distribution and Git-backed independent editing/concurrent proposals rather than bespoke branching, with scoped amendments to earlier authoring/admission decisions.
- **Behavior:** revision 1 captures the owner-approved baseline, with acceptance examples above. Earlier specifications retain unaffected computation, source/evidence, retrieval and separate-store rules; scoped amendment notices identify the changed contracts.
- **Uncertainty:** exact command spelling, package/file layout, Git metadata representation and mechanical migration steps must be made concrete by the implementation plan without changing these rules. The available Git tooling and current callers must be verified before execution. Written-specification review is complete; an approved implementation plan and separate execution authority are still required. No implementation, integration or publication is authorized here.
