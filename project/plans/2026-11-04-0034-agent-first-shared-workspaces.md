# Plan 0034: Agent-first shared workspaces

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

Canonical task bodies now live in the linked GitHub issues; this file owns the interface/dependency/coverage overview, not duplicate task instructions.

Status: **owner-approved implementation plan, revision 3**. Original date: 2026-11-04; local-auth planning: 2026-11-05.

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

### A1 — Complete local credential and browser-session path

- [ ] Modify `products/lumio/packages/lumio-workspace/src/lumio_workspace/{state,auth,app,__main__}.py`; create `local_auth.py` only if credential verification needs a separate cohesive module. Add focused coverage in `products/lumio/packages/lumio-workspace/tests/test_workspace_local_auth.py`; update `test_workspace_identity.py` only where shared identity/session interfaces change. Update service `README.md` for operator commands. No SDK/Core feature changes or new dependencies are planned.
- [ ] Consume existing SQLite membership/session, token-verifier and ASGI boundaries. Produce explicit local-token/Entra configuration, stable provider-separated local identities, administrator create/disable and purpose-specific issue/revoke commands, hashed token persistence with explicit expiry, API bearer verification, and separate same-origin browser login POST/session creation. Local mode needs no Entra configuration. Retain Entra configuration/validation and existing memberships; additive state changes must not reset or silently remap existing identities. Authentication-mode switching creates no grants.
- [ ] Make the whole path observable before handoff: administrator creates users A/B and issues separate credentials, authenticates read requests under current membership, and signs the human into the browser without API-to-browser exchange. Browser sessions retain credential provenance; expiry/revocation/disable is checked on use. Preserve rotation/non-resurrection and late-response cookie invariants. Provision browser credentials outside model/agent-visible channels; no raw credentials in logs, URLs or tracked configuration. No review/admission feature is implemented here; preserve its future browser-only contract.
- [ ] Validation **high risk / new-test**: one focused service lifecycle journey with independent identities/expiry expectations covers correct/wrong-purpose credentials, membership refusal, revocation/disable and derived browser-session refusal. A valid API token must fail browser login; a valid browser credential must fail API authentication. Include the real late-response interleaving if shared middleware/state changed, reusing existing deterministic barrier coverage rather than inventing another race matrix. Run the new file serially once per relevant delta. For behavior-affecting identity refactors pin existing Entra behavior first with the existing identity file; reuse that evidence if the relevant path remains identical. Scoped Lumio Ruff only during development. Commands: `uv run --locked --package lumio-workspace pytest -q products/lumio/packages/lumio-workspace/tests/test_workspace_local_auth.py` and the existing identity-file command only when invalidated. Use the root locked dev group as required for pytest.
- [ ] Immediately review this auth boundary before A2 consumes it. Assets: private knowledge, browser identity and reviewer authority. Real callers: an authenticated but unauthorized contributor tries the wrong credential purpose; a normal user is revoked or changes accounts while requests overlap. Expected refusals come from AC15/20, never implementation-generated values. Complete when lifecycle/refusal checks pass, existing Entra/session guarantees are preserved, the isolated result is frozen and the parent accepts its scoped review.

### A2 — Installed Pi token connection and qualification handoff

- [ ] After A1 review, modify `products/lumio/clients/pi-workspace/{index.ts,disclosure-boundary.test.ts,README.md}` and `products/lumio/docs/howto-shared-workspace.md`. Consume A1's explicit mode and API bearer boundary. Register local-token transport through supported installed Pi 1.5 secret/header facilities; preserve OAuth registration for Entra mode. Never request, persist in session history, or emit the browser credential. Stop for design reconciliation if the actual supported host cannot keep the API secret out of model/session output; do not modify installed Pi or introduce a custom host.
- [ ] Validation **high risk / new-test**: extend the existing actual installed-session/provider-transport fixture with a token-authenticated read of a fixed synthetic sentinel; independently assert correct API identity/current-membership behavior, no credential in model-facing material, and forbidden-provider refusal including derived history/resume where affected. Reuse unchanged compaction/branch-summary proof; no duplicate network-boundary mocks. One focused Bun invocation for the changed client test, plus existing Bun build. No live Entra or real company data.
- [ ] Qualification is **blocked, not waived** until separately authorized private HTTPS and two actual human users are available. Prepare an operator recipe for installed Pi API-token read and independent browser login with synthetic content; do not pretend one agent acting as both people proves human approval. Future W3 proves exact human admission; A2 must not fabricate it. Keep the Entra recipe clearly deferred, not removed or marked passed.
- [ ] Complete when the frozen client/docs result and focused checks establish AC21's automated boundary and a scoped review passes. The parent reports any unperformed live leg separately before deciding readiness for W2.

### Candidate delivery and review budget

- [ ] Assemble accepted results in another isolated candidate. Parent checks source correspondence and integration effects; do not reopen settled original W1/L1 findings. Run applicable mandatory `.github/workflows/ci.yml` and `lumio-lancedb-wheel.yml` gates, reusing prior candidate evidence only where code/tests/inputs/environment remain relevant. Auth/membership changes invalidate corresponding identity/client proof; a new label or doc edit does not invalidate unchanged SDK/Core wheel proof. No extra full matrices or coverage targets.
- [ ] One parent-authorized fix pass and one delta recheck per reviewed unit; surviving material findings return to the owner. No reviewer repairs or self-dispatch. Report exact frozen identities, check artifacts, remaining live prerequisites, and `accept / fix / hand back / ask`. No acceptance claim for deferred Entra. Integration, publication and tracker changes remain separate grants.

Requirement map: §10 explicit mode/preserved Entra and local credential lifecycle → A1; AC20 revocation/purpose/session/current membership → A1; AC21 Pi/disclosure/no fallback → A1+A2; AC15 human/API separation → A1+A2 boundary and unchanged W3 human-admission proof. Remaining ACs and W2–W6 behavior stay with their original owners. These tasks add no password/reset UI, identity broker, automatic local/Entra mapping, uploads, review implementation or production migration.

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
