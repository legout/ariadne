---
status: accepted
---

# ADR-0028: Owner-managed workspaces through existing agent apps

Date: 2026-11-04. Revision: 3.

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

**Scoped owner selections during planning:** Pi over a private network; one owner-managed private server; workspace-wide published knowledge; an authenticated review page opened from the conversation; and subsequently **Entra ID first, standard OIDC, no new password database**, with Google/GitHub deferred. The page is not a new chat application. The owner accepted the identity recommendation with “ok. keep this decision. proceed.” [Spec0034 revision 3](../specs/2026-11-04-0034-agent-first-shared-workspaces.md) records the approved behavioral and technical realization. The linked plans are approved; execution remains separate.

The owner endorsed the [usability assessment](../research/2026-11-04-agent-first-ux-assessment.md), requested simplification, explicitly required Lumio to remain a standalone shared team Knowledge Base, and selected **existing agent apps** as the contributor/reviewer interface. The owner then requested ADR/spec capture. These choices established the direction; the subsequent owner approval above accepts this complete design. Only ticket publication is authorized now, not implementation, deployment, migration, Git push or release.

## Decision

Use the existing company Entra tenant rather than adding passwords or an identity broker. Browser OIDC sign-in and Pi resource-scoped API authorization are separate integrations; neither grants reviewer capability by itself. The authenticated browser action, not the agent's credential or prose, supplies exact human confirmation. The actual private-network/client/registration path must be qualified. The [identity comparison](../research/2026-11-04-agent-client-and-identity-qualification.md) records alternatives and evidence limits.

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
