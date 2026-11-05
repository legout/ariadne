---
status: accepted
---

# ADR-0028: Owner-managed workspaces through existing agent apps

Date: 2026-11-04. Revision: 4 (identity amendment approved 2026-11-05).

**Owner approval — 2026-11-05:** In BB thread `thr_26ccqihn5b`, the owner approved per-user revocable API tokens, separate browser sign-in credentials/sessions, explicit authentication mode, and deferred Entra qualification. Record this design and present a bounded implementation plan; no implementation, integration, push, deployment, release or issue mutation is authorized. This supersedes the Entra-first prerequisite below, not the existing Entra implementation or authority/privacy guarantees. [Spec0034 revision 4](../specs/2026-11-04-0034-agent-first-shared-workspaces.md) owns the amended behavior.

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

**Historical selections through revision 3 (identity ordering superseded above):** Pi over a private network; one owner-managed private server; workspace-wide published knowledge; an authenticated review page opened from the conversation; and subsequently **Entra ID first, standard OIDC, no new password database**, with Google/GitHub deferred. The page is not a new chat application. The owner accepted the identity recommendation with “ok. keep this decision. proceed.” [Spec0034 revision 3](../specs/2026-11-04-0034-agent-first-shared-workspaces.md) records the approved behavioral and technical realization. The linked plans are approved; execution remains separate.

The owner endorsed the [usability assessment](../research/2026-11-04-agent-first-ux-assessment.md), requested simplification, explicitly required Lumio to remain a standalone shared team Knowledge Base, and selected **existing agent apps** as the contributor/reviewer interface. The owner then requested ADR/spec capture. These choices established the direction; the subsequent owner approval above accepts this complete design. That historical approval authorized ticket publication, not implementation, deployment, migration, Git push or release. The current amendment authorizes documentation only; no new tracker mutation is permitted.

## Decision

**Accepted interim limitation — 2026-11-05:** The owner explicitly accepted the current API-token exposure for continued development, then authorized commit/merge/push and cleanup in BB `thr_26ccqihn5b`. Pi's default shell inherits its process environment: a model-callable shell or equivalent local tool can expose `LUMIO_WORKSPACE_API_TOKEN` in tool output, session history and model requests. The placeholder header alone does not isolate that secret. Until supported host isolation is qualified, use synthetic credentials/data only; do not claim secret isolation or real-user/private-HTTPS qualification. Browser credentials remain forbidden in Pi. This is a documented accepted development risk, not a fixed defect, a production-use grant, or completion of the remaining live checks.

Use per-user local credentials for the interim managed-workspace milestone: a revocable, expiring API token for Pi and a separate browser sign-in token exchanged for a server-managed session. Store only token hashes; keep browser credentials out of Pi and model context. Neither credential grants membership or reviewer authority by itself. An API token cannot create a browser session or approve a change. The human's separate authenticated browser action supplies exact confirmation.

Choose local-token or Entra authentication explicitly for a deployment; never fall back from failed Entra authentication. Preserve the existing Entra/OIDC implementation and its qualified local evidence, with live Entra qualification deferred to its own approved fixture. Local identities are stable and distinct from validated Entra tenant/object identities; future association requires explicit administrator mapping, never email matching. No password database, password reset/recovery flow, or new identity broker is selected.

Rationale: company tenant registration and laptop/private-network access currently block live Entra qualification, not the remaining product behavior. Local tokens permit the owner to finish that behavior without a password-management subsystem. The trade-off is administrator-managed issuance, expiry, revocation and secure delivery, and two credential purposes per person. A shared token or reusing the API token for browser login would erase the human/API boundary and is rejected. Tokens remain bearer credentials, not proof of human presence; the agent must not automate browser approval. Private HTTPS and actual installed-client qualification remain required. The prior [identity comparison](../research/2026-11-04-agent-client-and-identity-qualification.md) remains historical evidence, not a live Entra pass.

Use a separate optional `lumio-workspace` deployment package with a small Pi extension and one private operational store. Keep authentication/UI out of the SDKs, Git as authoring truth, and native publication/admission as activation truth. This package placement and spec0034 §10's operational details are accepted scoped amendments to the three-member workspace design, not claims that a fourth package already exists.

Make an owner-managed workspace the default team operating model. People join it through supported existing agent apps, provide documents or data, clarify business meaning, and review readable changes. The workspace owns private source history, storage configuration, approved connections, isolated authoring state, and publication mechanics. Contributors do not operate a Git checkout, private registry, baseline transfer, or publication destination on their own machines.

Lumio remains independently installable and useful for internal documentation, runbooks, meeting notes, and cited answers. Ariadne is an explicit optional capability for data exploration and governed calculations. Preserve standalone Ariadne as well. One combined experience does not merge package ownership or give knowledge assertions calculation authority.

Reuse native Git authoring, deterministic validation, and immutable publication underneath a small task-oriented operating boundary. Existing agents remain the authors and analysts; do not introduce a new chat application or mandatory agent runtime. That boundary must enforce actor/workspace permissions independently of an agent's prose or shell privileges. A human decision authorizes a particular reviewed action; software performs the corresponding mechanics. Neither a terminal prompt nor a model-supplied confirmation field authenticates a reviewer.

Separate source access, submission, and admission capabilities. The owner can delegate business review without giving contributors database or publication credentials. Keep exact-revision consent, source privacy, query compilation, grain safety, required Policies, and truthful exploratory labels. Local CLI and independent-host Git/source-handoff workflows remain advanced paths, not the default team onboarding experience.

## Alternatives and trade-off

- **More skill instructions over independent local environments:** lowest product change, but preserves per-contributor state, credential setup, private transfers, and recovery complexity. Not selected as the ordinary team path.
- **A new browser application or mandatory private Lumio app:** could provide a controlled UI, but duplicates interface/runtime work and was not the owner's selected entrypoint. The private app remains separate and is not modified by this decision.
- **Owner-managed workspace with existing clients:** concentrates operational work where the owner requested it. It adds real identity, authorization, intake, recovery, and backup responsibilities. It is not achieved by prompt wrappers alone.

One logical operating boundary does not imply a microservice split, a particular web framework, an umbrella distribution, or a chosen deployment platform. The first client and review surface are now selected. Their concrete transport, identity/confirmation mechanism, and package/host placement must be resolved before execution. The deep SDKs remain framework/model-independent; a team-facing boundary can call both engines directly without making one engine a network service for the other.

## Relationship to existing decisions

[Specification 0034](../specs/2026-11-04-0034-agent-first-shared-workspaces.md) owns behavior, acceptance, unresolved prerequisites, and the scoped reconciliation map. In particular:

- Preserve [shared ADR-0027](0027-public-monorepo.md): independent packages, explicit integration, separate release identities, and no implied private-app dependency.
- Revisit [Lumio ADR-0031](../../products/lumio/project/adr/0031-private-source-handoff-for-external-agents.md)'s independent-environment default, not its exact-source/privacy guarantees.
- Preserve [Lumio ADR-0029](../../products/lumio/project/adr/0029-git-native-knowledge-authoring.md)'s single Git authoring truth and independent publication admission. Task status references that truth rather than becoming another content lifecycle.
- Preserve [Lumio ADR-0028](../../products/lumio/project/adr/0028-read-only-mcp-distribution.md)'s existing read-only interface. Any authenticated contribution/approval surface is a new approved contract, not an implicit widening of its tools.
- Preserve [Ariadne ADR-0024](../../products/ariadne/project/adr/0024-git-only-durable-authored-state.md)'s durable Git state and [ADR-0026](../../products/ariadne/project/adr/0026-lumio-sdk-bound-governed-releases.md)'s native joint admission. Revise the managed route's human-operated mechanics without removing human authority or changing existing release consistency rules.

This accepted ADR changes only the scopes identified by the reconciled notices. Other native contracts remain binding; dependent implementation still requires execution authority and prerequisite evidence.
