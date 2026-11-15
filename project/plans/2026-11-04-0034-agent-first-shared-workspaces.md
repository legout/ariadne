# Plan 0034: Agent-first shared workspaces

**Owner-approved Context foundation amendment — 2026-11-09:** [Shared ADR-0029](../adr/0029-lumio-owned-context-layer.md) records the accepted direction; [shared spec0035](../specs/2026-11-09-0035-lumio-owned-context-layer.md) captures its behavior (written revision 2 approved on 2026-11-10). Future Ariadne-dependent work must reconcile the mandatory Lumio Context contract. Lumio-only operation and the separately approved retrieval/source-retention amendment remain intact. No task body, tracker state or execution authority is changed by this notice. Earlier approvals are retained in their original scope; this notice grants no implementation, integration or publication authority.

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

Canonical task bodies now live in the linked GitHub issues; this file owns the interface/dependency/coverage overview, not duplicate task instructions.

Status: **owner-approved implementation plan, revision 4; scoped W2 synthetic-development grant**. Original date: 2026-11-04; local-auth planning: 2026-11-05.

**2026-11-09 amendment — approved:** “Freigegeben. Ticketize” in Hermes approves spec0034 revision 5 and the complete [curated-wiki retrieval/source plan amendment revision 1](#curated-wiki-retrieval-and-source-storage-amendment-proposed), including the reconciled constraints and GitHub ticket publication. No product implementation, deployment, fixture access, integration, commit/push or release is authorized. Original W/A/L/D history remains scoped to its own approvals.

**Scoped design approval — 2026-11-05:** Owner approved spec0034 revision 4's local-token design in BB thread `thr_26ccqihn5b` and requested this bounded plan before implementation. The owner subsequently approved plan revision 3 and authorized supervised isolated A1/A2 implementation with the specified focused checks and reviews in the same BB thread. This execution grant permits isolated candidate preparation only; no main integration, push, deployment, release, issue mutation or live Entra work. Existing ticket snapshots remain historical revision-3 sources; do not execute their superseded Entra-first prerequisites or silently rewrite them. This local amendment defines only new authentication work, not duplicate bodies for W2–W6.

**Scoped execution amendment — 2026-11-04:** The owner approved starting W1 / #86 and L1 / #87 in parallel, supervised, using Pi workers on `kimi-coding/k3.1-pro` with `high` thinking and Pi reviewers on `openai-codex/gpt-6.1-terra` with `xhigh` thinking; the owner subsequently selected BB threads as the host. Use separate registered worktrees and disjoint ownership: W1 owns the new service/client and workspace wiring; L1 owns the SDK neutral-default helper, its focused test and document-first guide. This supersedes only the initial sequential scheduling instruction in #85–87 and the linked overviews. All later task dependencies and review gates remain unchanged. Historically live Entra qualification blocked W1. Spec0034 revision 4 now defers that leg: a qualified local-token W1 may support later slices without claiming an Entra pass. Local automated checks alone still do not prove the installed human/client journey. No target integration, push, deployment or release is authorized. Approval source: owner messages in BB thread `thr_26ccqihn5b`.

## Goal, authority, and boundaries

Deliver the owner-selected Pi/private-network workspace: local-token sign-in initially, preserved Entra sign-in deferred, exact-original contribution, a separate human browser review, admitted cited answers, and optional Ariadne analytics. Standalone Lumio must work without Core. A document-only slice is useful but does not complete the requested first milestone.

Behavioral source: [shared spec0034 revision 4](../specs/2026-11-04-0034-agent-first-shared-workspaces.md), especially §§3–6, §10 and AC1–21. The revision-4 scoped approval above supersedes only the historical Entra-first requirement. Original authority: the owner requested plans, selected the client/hosting/input/access/default policies through structured questions, then accepted **Entra first, standard OIDC, no password database, Google/GitHub deferred** with “ok. keep this decision. proceed.” The specification records those choices. The complete specification revision 3, §10 technical realization and this plan revision 1 are approved by “Approved. lets ticketize” (2026-11-04); this is design and ticket-publication approval, not execution authority.

Capture: existing product glossaries suffice; [shared ADR-0028](../adr/0028-agent-first-shared-workspaces.md) records operating/identity choices; [Lumio ADR-0032](../../products/lumio/project/adr/0032-document-first-progressive-enrichment.md) records neutral artifact pages. Planning-contract version 1; installed skill revision unknown. Inspected code: `34bfe1be`, with this uncommitted documentation set. No live client, tenant, database, or S3 qualification was run while planning.

GitHub issue publication was authorized for the original ticketization; this amendment grants no issue mutation. Implementation, tenant registration, deployment, integration, push and release are not newly authorized. Approval includes spec0034 §10 and its package boundary. Execution remains a separate grant. Follow `orchestrate-implementation` for supervised Pi execution; do not copy an execution procedure into this plan. Existing advanced independent-host workflows are retained, not silently migrated or declared qualified.

## Bounded local-auth execution amendment (approved)

Source: approved spec0034 revision 4 §10, AC15, AC20–21; ADR-0028 revision 4. Approval reference: owner message approving separate API/browser credentials and deferred Entra in BB `thr_26ccqihn5b`. Existing W1/L1 candidate `eee5de37363d17bc2cbc7fd0c178480247bc111a` (tree `df80c5538e556a93d2cd02b4ba171651208db937`) remains frozen; the current documentation branch adds no implementation. Use that candidate plus approved documentation as a future pinned base, not main. Preserve original refs, dirty historical worktrees and verified evidence.

Capture: no new domain concepts/glossary edits; local user/token/mode names describe deployment authentication, not a new bounded context. ADR-0028 records the consequential identity trade-off. Spec0034 owns requirements and new AC20–21. No material design questions remain; supervised isolated execution is now authorized. Live-fixture/deployment authority remains outstanding. Planning-contract version 1; installed provenance unknown.

One sequential writer owns service and client surfaces; no parallel service/client edits. Supervised Pi via owner-selected BB threads, worker `kimi-coding/k3.1-pro`/high, reviewer `openai-codex/gpt-6.1-terra`/xhigh, isolated registered worktrees beneath the existing shared state root. Follow the installed orchestration skill for preflight, frozen handoff and lifecycle; this section is not a second router.

### Canonical local-auth tasks

The owner subsequently requested GitHub issues **before starting implementation**. Ticketization is authorized; no implementation worker has started. This supersedes the earlier no-issue-mutation restriction only for this ticketization. Main integration, push, deployment, release and live Entra remain forbidden. The execution grant remains scoped to A1/A2, with dispatch paused during ticketization.

| Task | Canonical body | Consumes → produces | Dependency |
| --- | --- | --- | --- |
| A1 | [#99: Local user tokens and separate revocable browser sessions](https://github.com/legout/ariadne/issues/99) | Existing W1 service/state → reviewed local credential, identity and browser-session contract | Frozen checked candidate plus approved documentation; no Entra live prerequisite |
| A2 | [#100: Pi token connection and local-auth qualification handoff](https://github.com/legout/ariadne/issues/100) | Reviewed A1 → token-connected Pi, focused proof and operator qualification handoff | #99 review before execution; includes isolated candidate delivery |

Task checklists, exact owned files, independent test oracles, focused commands, immediate reviews and completion criteria now live only in #99/#100. Earlier full plan snapshots are frozen provenance, not parallel editable task bodies. A1 and A2 use one sequential writer; service auth is reviewed before client consumption. The issues carry the one-fix/one-delta limit and preserve existing mandatory CI and valid evidence reuse.

Requirement map: §10 explicit mode/preserved Entra and AC20 credential/session lifecycle → #99; AC21 Pi/disclosure and explicit-mode boundary → #99 + #100; AC15 human/API separation → #99/#100 with actual exact human admission retained by W3/#89. No new review/admission implementation is hidden in A1/A2. W1/#86 depends on #100 for applicable local-token acceptance; W2/#88 still waits for W1 and L1. W6/#98 records local-mode qualification and deferred Entra honestly; its full input milestone is not waived.

## Ownership and order

| Owner | Canonical task bodies | Dependency |
| --- | --- | --- |
| This plan | W1–W6: private service, Pi transport, human review, recovery, operational delivery | W1 → W2 → W3 → W4 → W5 → W6 |
| [Lumio plan0011](../../products/lumio/project/plans/2026-11-04-0011-document-first-enrichment.md) | L1 neutral document defaults; L2 reviewed enrichment; L3 source-update impact | L1 before W2; W3 before managed L2; L2 before L3 |
| [Ariadne data plan0034](../../products/ariadne/project/plans/2026-11-04-0034-managed-data-onboarding.md) | D0 native integration prerequisite; D1–D3 source/file/database/S3 workflows | W3 and D0 before D1; D1 before D2/D3 |

Approved delivery order after the scoped amendment: **(W1 ∥ L1) → W2 → W3 → W4 → D0 → D1 → D2 → D3 → L2 → L3 → W5 → W6**. W1 and L1 may run concurrently in their disjoint owned surfaces; both interfaces must be accepted before W2. Remaining work retains single-writer ordering. W4 makes a full standalone document path available before analytics. Optional enrichment never becomes a prerequisite for that document path. Independent product internals may later be assigned in parallel only after consumed interfaces are accepted and write ownership is disjoint; the service and Pi client are shared write targets, so parallel execution is not assumed.

W6 closes the selected first milestone only after all required input categories and product tasks are covered. Old Lumio J6 and Core A0/A3 independent-host qualifications remain separate obligations for their original route, not requirements to set up every managed contributor machine.

## Implementation shape and approved interfaces

New roots (all paths below are repository-relative):

- **S** = `products/lumio/packages/lumio-workspace/`, a separate optional Python 3.14 deployment package; source package `src/lumio_workspace/`.
- **C** = `products/lumio/clients/pi-workspace/`, a packaged Pi extension; no bundled SDK/Core or server secrets on contributor machines.

S consumes `lumio-wiki[documents,mcp]`, maintained browser OIDC/JWT support (Authlib), and the ASGI HTTP stack. Use the repository's MCP SDK generation, SQLite from the standard library, and native Git. Its optional analytics extra consumes Core lazily; neither deep SDK acquires authentication/UI dependencies. Resolve and lock actual dependency versions in W1; do not add another job queue, model runtime, frontend framework, identity broker, or ORM. Public package compatibility metadata must match the tested SDK/Core build when a release is separately planned.

The service owns these narrow public operations; the plan defines interface names, not a new content lifecycle:

| Surface | Input → result | Authority/invariant |
| --- | --- | --- |
| `workspace_status` | workspace ID → capabilities, ready/unavailable state | Current membership; no secret/config values |
| `read_knowledge` / `search_knowledge` | published selector/query → pinned content/citations | Membership and admitted-only view |
| Byte-upload HTTP endpoint | original byte stream + retry identity → upload ID, server digest, actual size | Contribution permission; bounded streaming, no caller-controlled server path |
| `prepare_contribution` | upload IDs + complete candidate request + base → task ID, native review reference, review URL | Server-owned worktree; native candidate validation; no publication |
| `get_task` | task ID → actual status, permitted evidence, native receipts | Actor/workspace scoped; no success from queued work |
| Browser review GET/POST | opaque review ID; human action → recorded decision and resulting task state | Browser session only; GET is inert; exact one-use review binding |
| Analytics adapter | approved project/task/source handles → native review or pinned query result | Explicit analytics enablement, user grant, and native source/admission checks |

The server validates all candidate paths/control edits through the native authoring boundary; never expose arbitrary shell, Git command, environment, or filesystem-path execution to the remote agent. Content is authored through existing `CandidateRequest`/Git semantics. Source IDs, upload IDs, and task IDs have distinct meanings; identical bytes do not automatically merge two source identities.

Operational records contain actor/workspace/action/input identity, native base/candidate/review references, approval state, and observed receipt/outcome. Git/private stores hold the actual content. A retry key is unique to actor/workspace/action and conflicts if its input digest changes. Browser decisions cannot be created by MCP tools, an agent-provided boolean, or possession of a review URL.

## W1 — Sign in from Pi and read an existing published workspace

Canonical task: [#86](https://github.com/legout/ariadne/issues/86). Dependencies: no feature-task prerequisite; follow the approved delivery order.

## W2 — Initialize and submit a real text document without contributor Git

**Scoped W2 development authorization — 2026-11-05:** In BB `thr_26ccqihn5b`, the owner authorizes isolated implementation of #88 on integrated, locally checked W1/L1 interfaces at `470d7b9a5406dd0a31bae1663aad91062b5dc172`, despite outstanding live qualification. #87/#99 are completed; #86/#100 remain open. This overrides only the W1-live-acceptance prerequisite for synthetic development, not feature acceptance, actual human/browser approval, or later task authority. Use BB Pi workers/reviewers and work largely autonomously. All data and credentials are synthetic; the documented default-Pi token exposure remains an accepted development-only risk, not fixed. No main integration/merge, push, deployment, release or live Entra without further authorization. The explicit request permits recording this grant in the plan and #88 only; do not close #86 or change native blocker edges to imply live qualification.

Canonical task: [#88](https://github.com/legout/ariadne/issues/88). Dependencies: [W1 / #86](https://github.com/legout/ariadne/issues/86), [L1 / #87](https://github.com/legout/ariadne/issues/87).

**Owner-approved W2 scope refinement — 2026-11-05:** In BB `thr_26ccqihn5b`, the owner limits #88 to new empty and already natively adopted Knowledge Bases. A nonempty unadopted target must be refused with a readable `adoption_required` explanation and no mutation; actual native adoption and its preview remain an explicitly OPEN follow-up, not delivered by #88. Existing adopted targets still require an explicit owner preview before managed attachment/setup; no silent adoption, identity reset or fabricated source history. The parent also authorizes the necessary narrow operator CLI/service README surface for explicit `setup`/`contribute` grant/revoke provisioning; default `read` grants remain unchanged, with no first-login owner inference or reader promotion. Exact byte transfer uses a supported Pi extension command selecting/reading original bytes, not normalized `@path` text. Preserve all other #88 acceptance and synthetic-only/no-integration restrictions.

## W3 — Another human reviews and publishes exactly that change

Canonical task: [#89](https://github.com/legout/ariadne/issues/89). Dependencies: [W2 / #88](https://github.com/legout/ariadne/issues/88).

## W4 — Handle PDF/DOCX and recover without duplicate or partial activation

Canonical task: [#90](https://github.com/legout/ariadne/issues/90). Dependencies: [W3 / #89](https://github.com/legout/ariadne/issues/89).

## W5 — Operate, revoke, back up, and restore the single-server workspace

Canonical task: [#97](https://github.com/legout/ariadne/issues/97). Dependencies: [W4 / #90](https://github.com/legout/ariadne/issues/90), [D3 / #94](https://github.com/legout/ariadne/issues/94), [L3 / #96](https://github.com/legout/ariadne/issues/96).

## W6 — Qualify the full selected milestone and installed distributions

Canonical task: [#98](https://github.com/legout/ariadne/issues/98). Dependencies: [W1 / #86](https://github.com/legout/ariadne/issues/86), [L1 / #87](https://github.com/legout/ariadne/issues/87), [W2 / #88](https://github.com/legout/ariadne/issues/88), [W3 / #89](https://github.com/legout/ariadne/issues/89), [W4 / #90](https://github.com/legout/ariadne/issues/90), [D0 / #91](https://github.com/legout/ariadne/issues/91), [D1 / #92](https://github.com/legout/ariadne/issues/92), [D2 / #93](https://github.com/legout/ariadne/issues/93), [D3 / #94](https://github.com/legout/ariadne/issues/94), [L2 / #95](https://github.com/legout/ariadne/issues/95), [L3 / #96](https://github.com/legout/ariadne/issues/96), [W5 / #97](https://github.com/legout/ariadne/issues/97).

## Requirement map and validation handoff

| Spec0034 requirement | Task evidence owner |
| --- | --- |
| AC1, AC2 setup/join/contribution | W1, L1, W2 |
| AC3, AC4 readable human admission and authority | W3 |
| AC5 exact source identity/retry | W2; D2 for spreadsheets |
| AC6, AC7 stale/concurrent/interrupted actions | W3, W4 |
| AC8 privacy and original access | W1, W2, W3, W5; L2 |
| AC9, AC10 data meaning/source access | D1–D3 |
| AC11 combined meaning/calculation review | D0, D1 |
| AC12 independent products/explicit integration | W6, D1 |
| AC13 optional enrichment | L2, L3 |
| AC14 truthful answers/status | D1, W6 |
| AC15 identity versus human action | W1, W3, W5 |
| AC16 XLSX stored-value behavior | D2 |
| AC17 S3 effective identity | D3 |
| AC18 all input categories | W4, D1–D3, W6 |
| AC19 restore/revocation/retention | W5 |
| §§2/7 package, compatibility, migration | W1, W5, W6; no implicit migration |

Focused development checks are the named node/file commands above, serial. For V2–V5 respectively, from the repository root run `uv run --locked --package lumio-workspace pytest -q products/lumio/packages/lumio-workspace/tests/<file>`, selecting exactly `test_workspace_intake.py`, `test_workspace_review.py`, `test_workspace_recovery.py`, or `test_workspace_operations.py` for that changed unit; do not rerun settled units. Lumio checks run from `products/lumio` using its config; Core checks from its member directory; new service checks use S's explicit paths. Existing required `.github/workflows/ci.yml` and `lumio-lancedb-wheel.yml` gates stay intact; extend selection for new files, not the number of certification matrices. Reuse green evidence while relevant code, inputs, identities, and environment match.

**Validation and verification policy (owner decision, 2026-11-06):** Verification before tests, and both at the minimum `agent-guardrails` justifies. Each remaining task runs at most its one already-named focused `new-test` at its high-risk boundary (V5 for W5) plus existing checks only where the task actually changes that seam; no additional test files, per-task suites, or coverage targets. Per-task verification ends at parent inspection and the task's one independent review — no per-task comprehensive, installed, or live verification. One comprehensive verification pass runs once after ALL tasks are complete, as part of W6: it drives the real installed surfaces (wheels, service, Pi client) through the documented user-facing journeys with independently derived expectations (project-verification recipe discipline), instead of another test matrix. Required repository CI runs at candidate integration/delivery batches, never per task.

Every high-risk boundary names its real inputs: authenticated contributors upload untrusted bytes/candidate paths; authenticated but unauthorized people may attempt reviewer/source actions; normal clients retry or race. Protect published truth, originals, credentials, and permitted data. No speculative malicious-admin or stolen-secret story is needed. Normal-risk enrichment gets one candidate review; low-risk docs get parent inspection. At most one authorized fix pass and one delta-only recheck; unresolved findings return to the owner.

Residual prerequisites: a new execution grant, Python 3.14, installed Pi with verified secret/transport configuration, two local human identities with separately delivered credentials, private HTTPS, and applicable synthetic database/S3 fixtures. Entra fixture registrations/accounts apply only to the explicitly deferred Entra leg. The local-auth execution amendment is approved for supervised isolated implementation; existing checked candidate evidence does not prove that new behavior. Google/GitHub, other clients, mixed per-document audiences, spreadsheet recalculation, scheduled enrichment, and production migration/publication are outside this plan.

## Curated-wiki retrieval and source-storage amendment (proposed)

**Approved 2026-11-09:** “Freigegeben. Ticketize” accepts amendment revision 1 and spec0034 revision 5, and authorizes GitHub ticketization. The heading stays stable for existing fragment links; “proposed” is historical. No implementation has been authorized for this new track.

Date: 2026-11-09; targeted amendment: 2026-11-10. Amendment revision: 2, **approved and ticketized**. Owner approval: “Passt! erstelle die Tickets bzw. passe die bestehenden an”, following approval of spec0035 r2 and review of plan0035 r1. This accepts only the R1/R2/R4/R5 clarifications below; R0/R3 stay substantively unchanged. Product implementation remains unauthorized. Inspected baseline: `d2f8b75c0970267b42b0d04f5359ae603b7998a9`; clean before this documentation change. Canonical R0–R5 task bodies now live in GitHub #102–107 under existing epic [#85](https://github.com/legout/ariadne/issues/85). This overview owns sequencing/coverage only. The approval does not authorize implementation, commit/push, deployment or live fixture access. [Current frozen approved spec0034 r6](https://github.com/legout/ariadne/issues/85#issuecomment-6768381020); [approved amendment r2 snapshot](https://github.com/legout/ariadne/issues/85#issuecomment-6768381402); [earlier frozen spec0034 r5](https://github.com/legout/ariadne/issues/85#issuecomment-6747795772); [ADR and source-journey constraints](https://github.com/legout/ariadne/issues/85#issuecomment-6747796289). Local source edits are not yet committed/pushed; snapshots make the exact approved requirements available on GitHub.

### Sources, capture and readiness

- [Spec0034 approved revision 6 §12 / AC22–28](../specs/2026-11-04-0034-agent-first-shared-workspaces.md#12-curated-wiki-retrieval-and-original-references-proposed-revision-5) owns new behavior. “Freigegeben. Ticketize” approved the complete technical amendment and this task breakdown on 2026-11-09, beyond the earlier scope-only “Ja passt.” Implementation still requires a separate grant.
- [ADR-0028 scoped revision](../adr/0028-agent-first-shared-workspaces.md) owns shared operating/retention rationale; [research](../research/2026-11-09-kuratiertes-wiki-retrieval-ariadne-lumio.md) is evidence only. [Lumio spec0010 clarification](../../products/lumio/project/specs/2026-10-23-0010-external-agent-authoring-journey.md) preserves required independent-host retention. Existing vocabulary suffices; no new glossary or ADR. Planning-contract v1, installed skill provenance unknown.
- Scope is standalone managed Lumio, plus preserved Ariadne pin/scope checks. Mandatory Lumio on the Ariadne side is owned by spec0035, not a new reverse dependency or mandatory workspace service. No new integrated Hybrid route, personal ACLs, source search, SharePoint, production migration, scheduler, model runtime or unrelated audit cleanup. One optional retrieval extra and reuse of the existing S3 extra may be needed; no new service/store family.
- GitHub ticket publication is authorized. Product execution, commits, integration, endpoint access and deployment remain unauthorized. Live verification additionally needs separately approved private HTTPS, installed Pi, synthetic human identities/credentials and a named synthetic S3 endpoint. The documented Pi token-exposure limitation still prevents claims of production secret isolation. No recipe creation is authorized or required; reuse documented journeys and existing drivers, without a new verification framework.
- One sequential writer owns shared service/client files. R-track dependencies stay **R0 → R1 → R2 → R3 → R4 → R5**. For the approved joint refactor schedule, complete R0–R4, then plan0035 C1–C6; run R5's final installed journey with C7 on that same assembled candidate. R5 additionally waits for [C6 / #114](https://github.com/legout/ariadne/issues/114), not [C7 / #115](https://github.com/legout/ariadne/issues/115) completion; C7 consumes its final evidence, avoiding a dependency cycle or duplicate live run. R0 is a prerequisite bug check/repair, not a new unreviewed baseline publication. Independent code/fixture evidence may be reused only if its touched code, inputs, permissions and environment still match. Follow `orchestrate-implementation` for supervised Pi host/model preflight and candidate handling; this plan does not replace that router.

Path abbreviations: **S** = `products/lumio/packages/lumio-workspace`; **K** = `products/lumio/packages/lumio-wiki`; **L** = `products/lumio/packages/lumio-lancedb`; **C** = `products/lumio/clients/pi-workspace`; **D** = `products/lumio/docs`. All paths below are repository-relative through these abbreviations. Python >=3.14; preserve standalone base-package import/wheel boundaries.

### R0 — First reviewed publication from an empty workspace

Canonical task: [#102](https://github.com/legout/ariadne/issues/102). Source: AC27, existing AC1/3/15. No R-track dependency; implementation authority is still required. Produces the reviewed initial publication and actual admitted baseline consumed by R1 and the already-required next contribution. Repair only if the bootstrap defect reproduces.

### R1 — Shared-scope Evidence retrieval through MCP

Canonical task: [#103](https://github.com/legout/ariadne/issues/103). Depends on R0 / #102. Source: §12.1–2, AC22/23/28. Consumes admitted pages and native adapters; produces shared-scope, version-qualified Evidence and authorized page resolution consumed by R2, with stable Entity ID/revision on existing read/search for supported follow-ups. Zero-Index default, optional BM25; no Hybrid rollout.

### R2 — Open exact originals from published-page references

Canonical task: [#104](https://github.com/legout/ariadne/issues/104). Depends on R1 / #103. Source: §12.3, AC24. Consumes scoped page/version resolution and private bindings; produces exact-version source-reference opening under current `inspect_source`, without a pending-review dependency or original indexing. The existing pending-review route also returns exact binary originals under its own candidate binding/inspection permission; no previewer or pending-page disclosure.

### R3 — Explicit standalone retention exception

Canonical task: [#105](https://github.com/legout/ariadne/issues/105). Depends on R2 / #104. Source: §12.4, AC25. Consumes owner-bound profile/setup and native admission; produces explicit standalone omission with honest availability. Independent-host and integrated required retention remain unchanged; no cleanup/erasure promise.

### R4 — S3 originals with self-contained recovery

Canonical task: [#106](https://github.com/legout/ariadne/issues/106). Depends on R3 / #105. Source: §12.5, AC26. Consumes existing S3 store, registry and retention policy; produces self-contained backup/fresh-root recovery preserving exact original bindings and the next standalone reviewed publication after owner reconfirmation/native revalidation. Integrated shared-repository/query recovery is owned by spec0035 C5. No bucket-wide discovery or remote migration framework.

### R5 — One final installed journey and evaluation handoff

Canonical task: [#107](https://github.com/legout/ariadne/issues/107). Depends on R4 / #106 and accepted R0–R3, required batch CI and separate live-fixture authority. Source: AC22–28, preserved AC1/3/8/12/19. Produces one real installed Pi/service/local-and-named-S3 journey plus a bounded Zero-Index/BM25 evaluation. The same journey includes pending binary inspection and fresh post-restore publication; coordinate with spec0035 C7 after C6 rather than add a second live suite. `no-new-test`; no live pass inferred from synthetic checks. Existing #98 / #100 qualification scope is not closed or silently replaced by R5.

### Coverage, evidence budget and approval request

| Requirement | Owner |
| --- | --- |
| AC22 exact scoped Evidence, optional BM25/fallback | R1; real surface R5 |
| AC23 common audience, all read/search/reference paths | R1 selection, R2 original gate; R5 denial |
| AC24 exact historical source, no original indexing | R2; R5 byte check |
| AC25 intentional retention exception, preserved defaults | R3; R5 one example |
| AC26 central S3 storage and complete recovery | R4; R5 named live endpoint |
| AC27 first publication | R0; R5 fresh-workspace journey |
| AC28 integrated pin/scope compatibility | R1 refusal, R3 retention refusal; reuse native integration checks/R5 |

Each new task runs at most its one named focused regression check, plus an existing check only where it changes that seam. Synthetic checks at high-risk boundaries run immediately; the comprehensive installed/Pi/S3 journey runs once in R5. Project-mandated independent candidate reviews apply to the named authority/integrity changes, not to low-risk documentation; one parent-authorized fix pass and one delta recheck, then return unresolved findings. Required repository CI stays at integration/delivery batches, never copied into every task. Do not infer fresh passing results from prior research's 28 tests.

Before dispatch: approved plan amendment revision 2 and spec0034 revision 6 own the targeted updates; canonical #103/#104/#106/#107 now carry the approved source snapshot; R0/#102 and R3/#105 remain unchanged; reconcile any later material changes, obtain implementation authority separately, and resolve actual Pi host/model preflight. GitHub ticketization was authorized on 2026-11-09; historical W1–W6/A/L/D tickets do not own R0–R5. No model/host selection from an old run is silently reused.
