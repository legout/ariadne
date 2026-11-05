# Plan 0034: Agent-first shared workspaces

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

Canonical task bodies now live in the linked GitHub issues; this file owns the interface/dependency/coverage overview, not duplicate task instructions.

Status: **owner-approved implementation plan, revision 4; scoped W2 synthetic-development grant**. Original date: 2026-11-04; local-auth planning: 2026-11-05.

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

Every high-risk boundary names its real inputs: authenticated contributors upload untrusted bytes/candidate paths; authenticated but unauthorized people may attempt reviewer/source actions; normal clients retry or race. Protect published truth, originals, credentials, and permitted data. No speculative malicious-admin or stolen-secret story is needed. Normal-risk enrichment gets one candidate review; low-risk docs get parent inspection. At most one authorized fix pass and one delta-only recheck; unresolved findings return to the owner.

Residual prerequisites: a new execution grant, Python 3.14, installed Pi with verified secret/transport configuration, two local human identities with separately delivered credentials, private HTTPS, and applicable synthetic database/S3 fixtures. Entra fixture registrations/accounts apply only to the explicitly deferred Entra leg. The local-auth execution amendment is approved for supervised isolated implementation; existing checked candidate evidence does not prove that new behavior. Google/GitHub, other clients, mixed per-document audiences, spreadsheet recalculation, scheduled enrichment, and production migration/publication are outside this plan.
