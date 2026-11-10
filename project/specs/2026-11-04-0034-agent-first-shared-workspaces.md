# Specification 0034: Agent-first shared workspaces

**Owner-approved Context foundation amendment — 2026-11-09:** [Shared ADR-0029](../adr/0029-lumio-owned-context-layer.md) records the accepted direction; [shared spec0035](2026-11-09-0035-lumio-owned-context-layer.md) captures its behavior (written revision 2 approved on 2026-11-10). All Ariadne Context creation/management uses Lumio, with no legacy runtime path or content migrator. The shared service remains optional for local library use. Existing hosting, identity, curated retrieval and retention rules are unchanged; the standalone document-only retention exception does not extend to Ariadne. Earlier approvals are retained in their original scope; this notice grants no implementation, integration or publication authority.

Status: **owner-approved behavioral specification, revision 6**. Original date: 2026-11-04; identity amendment: 2026-11-05; retrieval/storage amendment: 2026-11-09. The owner approved the full §12 detail, acceptance examples, ADR reconciliation and plan amendment revision 1 with “Freigegeben. Ticketize” in Hermes on 2026-11-09. GitHub ticket publication is authorized; product implementation, live fixture access, deployment, integration, commit/push and release are not.

**Scoped owner approval — 2026-11-10:** After approving spec0035 revision 2 and reviewing its implementation plan revision 1, the owner stated “Passt! erstelle die Tickets bzw. passe die bestehenden an”. This approves the targeted R1/R2/R4/R5 reconciliation described in that plan and authorizes ticket publication: stable Entity IDs/revisions on existing reads/searches, exact binary originals during pending review, a fresh standalone publication after restore, and those steps in the same final journey. Revision 6 changes only §12.2/3/5 and AC22/24/26 for these outcomes; R0/R3 and all other approved boundaries remain unchanged. Integrated knowledge-only authorization and integrated recovery remain spec0035 work. No implementation, live access, commit/push or deployment is authorized.

**Scoped owner approval — 2026-11-09:** In the Hermes conversation about the [curated-wiki research](../research/2026-11-09-kuratiertes-wiki-retrieval-ariadne-lumio.md), the owner answered “Ja passt.” to: Evidence retrieval with Zero-Index and optional BM25, Hybrid only after real-question evaluation; a shared knowledge audience with consistent filtering and personal/team ACLs deferred; default-required original retention with an explicitly authorized, visibly limited mode without originals, and S3 or persistent server storage selectable. The owner requested specification capture and an implementation plan. This approves these scoped requirements, not product implementation, live fixtures, tracker publication, deployment, integration, commit/push or release. The remainder of revision 4 is unchanged except for the explicit reconciliations below.

**Scoped owner approval — 2026-11-05:** In BB thread `thr_26ccqihn5b`, the owner approved the local-token design including separate API/browser credentials, revocation/session invalidation, explicit authentication mode and deferred Entra qualification. This supersedes revision 3's Entra-first prerequisite only; preserve its implementation and all membership, human approval, private HTTPS and disclosure guarantees. Documentation and planning only: no implementation, integration, push, deployment, release or issue mutation. The rest of revision 3 remains approved unchanged.

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

Revision 2 captures the owner's planning selections from this conversation: Pi over a private network; one owner-managed server; workspace-wide published knowledge; and a small authenticated review page opened from the conversation, not a new chat app. The first usable milestone must include text/Markdown, PDF/Word, CSV/Excel, databases, and S3 files/table formats. The owner accepted stored-value XLSX imports without macros/recalculation, explicit refresh, local conversion, explicit owner permission for model processing, retention until authorized deletion, and delegated reviewers with separate source/data access. The owner then accepted the recommendation to qualify **Entra ID first using standard OIDC, with no new password database and Google/GitHub deferred**, saying “ok. keep this decision. proceed.” Together with the earlier request for implementation plans, this authorizes planning against the selected behavior, not implementation or tenant changes. See the [client and identity comparison](../research/2026-11-04-agent-client-and-identity-qualification.md).
Execution readiness: §10's amended behavior is approved; plan0034 revision 3 is approved for supervised isolated A1/A2 implementation, as subsequently authorized by the owner in BB `thr_26ccqihn5b`. Applicable prerequisite evidence remains required; integration, publication and live Entra are not authorized. Historical Entra-first statements in the revision-2/3 approval history above are superseded by the scoped revision-4 amendment. This document describes target behavior, not implemented capabilities.

## 1. Authority, ownership, and scope

In the 2026-11-04 conversation, the owner requested minimal-technical-complexity setup, prompting-led contribution of documents/tables/databases/files, and simple approval. After the [assessment](../research/2026-11-04-agent-first-ux-assessment.md), the owner endorsed simplification, required standalone shared Lumio use, selected **existing agent apps** rather than a new browser UI or the private Lumio application, and requested ADR/spec capture. Those were the original direction choices; the approval recorded above subsequently covers this complete written revision, not implementation.

[Shared ADR-0028](../adr/0028-agent-first-shared-workspaces.md) owns the architectural rationale. This shared specification owns the cross-product operating experience and authority boundary. [Lumio specification 0003](../../products/lumio/project/specs/0003-model-assisted-extraction.md) owns document-first knowledge and optional enrichment. Existing product specifications continue to own computation, provenance, publication, and retrieval semantics except where an approved scoped amendment explicitly changes them.

“Workspace,” “contributor,” and “reviewer” below are ordinary interaction/capability descriptions, not a new bounded context, storage model, or public role enumeration. Canonical Knowledge Base, Source Approval, Publication Admission, and Bound Release meanings remain in the product glossaries. The Lumio product definition is clarified to include standalone team knowledge; no shared root glossary is introduced.

### Included

- One owner-managed team workspace accessed through a supported existing agent app.
- Complete standalone Lumio contribution, review, publication, search, and cited-answer use for documentation, runbooks, and meeting notes.
- Optional Ariadne data onboarding, bounded exploration, and governed metric authoring through the same user experience.
- Readable approval, exact authorized execution, interruption recovery, and truthful status.

### Excluded

A new chat UI, mandatory private-app or Ariadne Agent/Tau dependency, a new autonomous agent runtime, multi-tenant SaaS, automatic infrastructure/IAM provisioning, unlimited input-format support, unattended semantic publication, source access inferred from upload text, or migration of real projects without a separate authorized transition. No new scheduler, graph database, vector service, or microservice split is required.

## 2. Product boundaries and deployment responsibilities

**Lumio alone is a complete product path.** It must work without Ariadne installed, an analytics source, OSI models, ODCS contracts, metric bindings, or an integrated release. Ordinary local SDK/CLI reading and validation remain model-free. Natural-language interaction uses the selected host agent; that is not a promise of model-free distillation or answering.

**Combined use is explicit.** The owner enables Ariadne for a selected workspace; installing both packages alone activates no integration or permissions. Ariadne owns calculations, approved source execution, grain/join safety, and analytics admission. Lumio owns knowledge, source provenance, and native knowledge publication. Preserve standalone Ariadne and the direct optional SDK integration.

One owner-managed environment holds canonical private source history, credentials/connection bindings, authored content, and admitted state. A contributor's client need not clone a repository, install both packages, replicate a registry, or obtain publication/database credentials. Client connection/authentication is still required once; “no contributor setup” must not conceal that prerequisite.

The managed boundary isolates contributions instead of sharing one writable worktree. Durable task status refers to native candidate revisions, review identities, and receipts; it is not a second editable source of content truth. Storage and versioning choices are implementation details unless a user decision actually changes access, retention, or an existing resource.

The SDKs do not absorb host authentication, UI, or model-runtime dependencies. Section 10 defines a separate optional deployment package; the repository root remains coordination-only. An agent client is supported only after its real attachment, authentication, review, and result-display path is qualified; MCP support alone is not proof of the full journey.

## 3. Owner setup and joining

The owner requests a workspace through the selected client. Setup proposes the smallest supported configuration and asks only for unresolved consequential choices:

- Workspace identity and permitted people/audiences.
- Hosting/storage location and original retention/deletion policy.
- Which agent/model processing is allowed, including external data disclosure.
- Who can submit, review/admit within which scope, and authorize connections.
- Whether analytics is enabled and which connections may be provisioned.

Show the effects before creating or adopting resources. After authorization, software performs supported repository initialization, private-directory creation, generated identifiers/manifests, profile configuration, and client wiring. No routine JSON/YAML editing, UUID selection, ontology design, retrieval-backend selection, or copied revision digest is required. Existing directories, namespaces, identity settings, or stores are not silently adopted, reset, or overwritten.

Credential entry uses an owner-controlled secure mechanism, not model-readable chat, source documents, or tracked configuration. Missing OS/host/deployment prerequisites are named honestly; installation does not imply working authentication, source access, or query readiness.

A team member joins the configured workspace through the selected authenticated connection. Permissions come from the managed boundary, not claims in a prompt or a supplied workspace path. The owner can grant contribution widely and delegate business review narrowly; contributing does not imply approving, and knowledge access does not imply raw-source or row-data access.

Setup finishes by reporting what is ready, what is unavailable, and one actionable next step. Unsupported capabilities are not advertised as configured. Repeating setup preserves existing authorized state and reports differences rather than recreating it.

## 4. Contribution and data onboarding

### 4.1 Documents

“Add this runbook” addresses the actual attachment, not its filename. Under the configured intake policy, software records exact source identity/version, retains originals as required, performs supported conversion, and discloses meaningful loss or unsupported input before claiming success. Originals and private working material remain outside published knowledge and tracked content.

The agent reads existing knowledge and prepares the smallest useful source-backed change. It proposes updates/duplicates based on evidence, asks about uncertain identity, and preserves unrelated content. Identical bytes for an identified existing source are a no-op unless the requested meaning/audience/binding changes; identical bytes alone do not prove two independently supplied sources have the same identity. A changed source gets a new exact version, not overwritten history.

The submission identifies additions, replacements, deletions, contradictions, audience, and source support. Users do not select a registry, namespace, Git branch, or private transfer route. Documents become ordinary reader knowledge only through applicable content admission; successful extraction or contributor assent does not publish them. No domain ontology or canonical metric is a prerequisite for the document-first path in Lumio spec0003.

### 4.2 Data files and spreadsheets

One conversational intake can prepare both knowledge and queryable data, but reports them separately. Distinguish “stored/documented,” “available for permitted exploration,” and “approved business definition.” A document converter's Markdown output is not proof that spreadsheet analytics works.

For a supported structured input, preserve conversion provenance and disclose selected sheets/tables, column/type interpretation, and relevant losses. Read available definitions before asking about row meaning, dates, units/currencies, status codes, exclusions, or refresh expectations. Ask only where uncertainty affects the requested outcome; do not derive business rules from frequency or matching column names.

The selected first milestone includes text/Markdown, PDF/Word, CSV/Excel, database tables, and S3 files/table formats. XLSX uses selected sheets and stored values, never executes macros or recalculates formulas; refresh is explicit. Missing formula caches and conversion losses must be disclosed rather than replaced with invented results. Database and S3 scope starts with the currently documented Ariadne source families/modes, not arbitrary vendors or catalog protocols; the approved initial limits and refusal behavior are in §10. Unsupported input can be retained privately where policy permits, but remains explicitly unqueryable/unconverted; no invented data or silent lossy fallback.

Existing Ariadne source, admission, compile, result-limit, and context preconditions still apply. Exploration may precede a canonical metric once its actual prerequisites are satisfied; neither an upload nor this specification grants a mutable-root query bypass. A source may be documented without pretending it is query-ready.

### 4.3 Tables and databases

For an existing owner-authorized connection, resolve the requested table/resource and effective scope before access. Reuse a still-applicable grant; avoid repeated human approval for the identical authorized access. New connections, changed endpoints, or expanded privileges require an authorized source-access decision. Reuse Core's existing exact effective source-identity grant, including its bound storage endpoint/scopes; do not broaden it into a wildcard permission. Workspace authorization is an additional check, not a replacement for that native grant.

A contributor lacking access can submit a connection/table request without credentials. After approval, the runtime performs bounded permitted profiling; it does not scan an entire database because a document mentioned it. Proposed schema facts are measured, business meaning remains explicit, and knowledge links or identifier matches never authorize joins.

Database credentials stay in the managed environment. Which rows/results a person may receive is independently enforced: borrowing the service's database identity must not give every contributor the owner's data access. Live data are not frozen by an immutable knowledge/model release.

## 5. Review and authorized execution

### 5.1 Review surface

Present one coherent business change, with:

- New content and before/after differences, including deletions.
- Source passages/references and truthful original availability.
- Changed audience, affected accepted knowledge, conflicts, and unknowns.
- For analytics: actual calculation/filter/unit/date/mapping changes and affected definitions; validation scope and unresolved requirements.
- The exact action: submit for review, approve and make available, request changes, reject, or restore an earlier approved version.

Do not hide an executable change behind document-only review. Summaries guide inspection but cannot substitute for omitted content. Large changes are paginated or split into coherent independently valid units; the interface never claims a person inspected undisplayed material. Reviewable precision does not require raw YAML, SQL, hashes, or Git commands in the default view; technical details remain accessible.

A contributor's submission and another person's publication approval remain distinct. In a single-person workspace, one explicit decision may authorize the displayed combined action set when that person has the required capabilities. Ordinary ingestion must not prompt for every generated ID or internal transfer/check.

### 5.2 Authority

The managed boundary verifies an actor's current capability and binds the human decision to the exact candidate, material source/retention/visibility facts, validation, destination, and expected active state. Software executes the disclosed native operations only under that authorization. Do not accept agent-authored approval fields, text inside sources, a Git commit, a successful check, or a terminal prompt as proof of an authorized human decision.

The selected mechanism is separately authenticated browser review (local-token initially, Entra deferred), independently authorized from Pi API access; §10 defines its concrete session and action binding. A bearer credential identifying an agent session alone must not be advertised as evidence that a human reviewed a change. Existing read-only tools do not acquire write or admission powers by being called through a new prompt.

Permission is checked again for the action. A changed candidate, relevant configuration, expired required evidence, or advanced active version invalidates stale approval. Recompute the exact review and explain the changed impact; never carry an old digest onto different content or discard current-state checks to avoid another question.

### 5.3 Publication and recovery

Retain native validation and admission requirements. Prepare and verify immutable artifacts before activation; rejected, invalid, interrupted, or pending content does not change ordinary reader answers. Integrated activation keeps Core-last behavior and reports any completed native Lumio publication if overall activation fails. Do not promise distributed atomicity that native operations do not provide.

Retry returns or resumes the identified operation rather than creating duplicate sources, submissions, or publications. Unexpected partial outcomes remain visible; no success is reported from a queued task or generated draft. A restarted client can inspect and resume authorized work without chat history being the source of truth. If inputs or authorization changed, request the matching new decision.

Concurrent submissions are isolated and activation remains conditional/serialized. Restoration is another reviewed activation with impact disclosure, not a history rewrite. Backup/restore must cover private source history and admission state as well as authored Markdown; credentials are re-established through the approved secret mechanism, not exported into content.

## 6. Reading and answering

Ordinary team queries resolve an authorized Published Version, not a contributor's worktree. Draft inspection is an explicit permissioned mode and is visibly labeled. For the selected first deployment, all workspace members can read admitted workspace knowledge; mixed document audiences within a workspace are not selected. Reject a contribution requiring a narrower published audience instead of silently widening it. Enforce workspace membership and separate source/data permissions before retrieval, graph expansion, citations, original inspection, and output; unauthorized users must not learn hidden entities through an edge or diagnostic. Cross-workspace selectors do not supply authority.

Lumio answers use supporting passages and useful open actions. Unsupported claims are reported as not covered, rather than completed from agent memory. Source Inspection is separately authorized and never replaced with a misleading public/signed URL. When originals are absent, report that fact without inventing inspection evidence.

Ariadne questions route to the applicable governed or exploratory operation without asking the person to choose a command. Answers show the period, units, meaningful caveats, citations, and true governance status. Approval, execution fidelity, and independent numerical validation remain different claims. Keep required Policy/context gates; concise presentation is not permission to skip or truncate mandatory context internally.

Unrelated optional enrichment must not block valid Lumio document use. In an integrated workspace, existing whole-content and Bound Release checks still apply: changing release granularity, build-identity matching, support revisions, or required Policy closure is not authorized by this simplification. Do not create an independently moving governed knowledge view behind a pinned release.

## 7. Native boundaries and migration

| Existing source | Scoped target change or retained constraint |
| --- | --- |
| [Shared ADR-0027](../adr/0027-public-monorepo.md) | Keep standalone packages and explicit integration; no umbrella package or mandatory private app is selected. |
| [Lumio platform spec0001](../../products/lumio/project/specs/0001-knowledge-agent-platform.md) | The new public team path uses existing agent apps, not a mandatory Lumio-owned browser/runtime. Private-app requirements stay scoped to that app. |
| [Lumio ADR-0028](../../products/lumio/project/adr/0028-read-only-mcp-distribution.md) | Existing MCP stays read-only. New permissioned contribution/approval transport needs an explicit contract and qualification. |
| [Lumio ADR-0029](../../products/lumio/project/adr/0029-git-native-knowledge-authoring.md) | Keep Git as authoring truth and publication as separate admission; managed tasks reference, not duplicate, that state. |
| [Lumio ADR-0031](../../products/lumio/project/adr/0031-private-source-handoff-for-external-agents.md), [spec0010](../../products/lumio/project/specs/2026-10-23-0010-external-agent-authoring-journey.md) | Independent environments/bootstrap/exchange remain advanced workflows, not every contributor's required setup. Shared canonical provenance must preserve their exact-version guarantees. |
| [Ariadne ADR-0024](../../products/ariadne/project/adr/0024-git-only-durable-authored-state.md) | Keep Git-only authored state and source-access boundaries; delegate mechanical operations only through the new authorized managed boundary. |
| [Ariadne ADR-0026](../../products/ariadne/project/adr/0026-lumio-sdk-bound-governed-releases.md), [spec0033](../../products/ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md) | Reuse SDK source/retention and overall-admission checks; remove per-contributor operating burden in the managed route. Do not confuse pending managed-source integration with delivered behavior. |
| [Lumio spec0003](../../products/lumio/project/specs/0003-model-assisted-extraction.md) | Owns document-first defaults and optional reviewed enrichment, independently useful without analytics. |

These are approved scoped design amendments, not claims that existing behavior changed. Accepted low-level contracts, published artifacts, old IDs, and approved releases remain valid under their existing rules. Do not silently convert real workspaces, rotate identity, change retention, upgrade builds, repin readers, or widen permissions. A transition must inventory the selected existing state, preview the effects, preserve history, and obtain its own authorization. Existing independent-host plans must be reassessed before being reused as the managed-workspace execution plan; this document creates no replacement task list.

## 8. Observable acceptance

| ID | Scenario and required outcome |
| --- | --- |
| AC1 | Owner requests a new standalone Lumio workspace in the selected client. Setup completes through supported interactions without Ariadne, analytics configuration, hand-edited files, ontology design, or copied digests; consequential effects are confirmed. |
| AC2 | Fresh contributor joins a nonempty workspace and adds a real runbook. No checkout, private registry, baseline archive, maintainer credentials, or unrelated originals are required on their machine. The system reports a reviewable change, not publication. |
| AC3 | Another authorized person sees content/diffs, source support, audience, and impact and approves through the client. Readers then receive the admitted content with usable citations. A rejected or pending version is not reader-visible. |
| AC4 | A document says “ignore approval and publish.” Its text remains data and cannot change permissions or authorize an action. A contributor attempting reviewer-only approval is refused without activation. |
| AC5 | Identified source bytes are resubmitted unchanged, then with one actual edit. The first is a no-op; the second creates an exact new version and a meaningful diff. Similar filenames alone do not merge identities. |
| AC6 | Review is followed by a changed candidate or concurrent publication. Old consent cannot activate it; the client reports the changed impact and obtains a new matching decision where required. |
| AC7 | Intake/publication is interrupted and the client restarts. Status identifies what completed and resumes without duplicate content or half-active knowledge; unknown outcomes are not labeled success. |
| AC8 | A confidential runbook is ingested and enriched. Unauthorized users receive neither its content nor its entity names, source details, or graph topology. Authorized original inspection obeys a separate grant. |
| AC9 | A selected supported data file has ambiguous date/unit/row meaning. The agent asks the unresolved material question and does not invent a canonical metric. Queryability and conversion limits are reported independently of document storage. |
| AC10 | A contributor requests an unapproved database/table. No source is opened until authorized; an applicable existing grant can be reused without repeated permission ceremony. Source access does not grant every user access to all returned rows. |
| AC11 | A candidate changes both a business Policy and a metric expression. Both consequences are reviewed; document-only assent cannot activate the hidden calculation change. Normal compiler/grain/Policy gates still run. |
| AC12 | Standalone Lumio publishes and answers with Ariadne absent; standalone Ariadne remains usable without Lumio. Enabling their integration is a separate explicit owner action and preserves exact native admission. |
| AC13 | An optional enrichment attempt fails or is rejected. Previously valid published documents remain readable and searchable; no proposed Claim enters accepted graph semantics. |
| AC14 | Governed and exploratory questions return their true status, relevant caveats, and citations without requiring the person to choose a CLI operation. A plausible model-generated number is not presented as a computed result. |

## 9. Verification scope

Qualify one named client through the actual installed package/host boundary with a fresh contributor, an independent reviewer identity, a nonempty workspace, and a real attachment. A scripted fixture or an agent pretending to be both people does not establish human interaction or authorization. Use independently authored source passages and hand-worked numeric expectations for the selected data journey. Reuse applicable native checks; add focused checks only for new reachable authority, privacy, retry, or data-integrity behavior. No combinatorial client/storage/role matrix or blanket suite is required by this specification.

Document checks can establish consistency of this draft, not working software. No installation, source access, hosted service, model disclosure, or deployment is authorized here.

## 10. Technical realization

The owner decisions above are fixed inputs to planning. The following concrete realization was approved with the plans in the owner response recorded above. A contrary qualification result returns here for reconciliation, not an implementer-selected change of host, identity provider, or approval mechanism.

### Identity and authority

**Accepted interim limitation — 2026-11-05:** The owner explicitly accepted the current API-token exposure for continued development, then authorized commit/merge/push and cleanup in BB `thr_26ccqihn5b`. Pi's default shell inherits its process environment: a model-callable shell or equivalent local tool can expose `LUMIO_WORKSPACE_API_TOKEN` in tool output, session history and model requests. The placeholder header alone does not isolate that secret. Until supported host isolation is qualified, use synthetic credentials/data only; do not claim secret isolation or real-user/private-HTTPS qualification. Browser credentials remain forbidden in Pi. This is a documented accepted development risk, not a fixed defect, a production-use grant, or completion of the remaining live checks.

- Select one explicit deployment authentication mode: `local-token` for the interim milestone or `entra` for the preserved OIDC/OAuth route. Invalid configuration fails closed; missing credentials or failed Entra authentication never select local-token implicitly. Preserve existing Entra deployments and stored identities; switching modes is an explicit operator action, not an automatic migration or permission change.
- In local-token mode, an administrator creates stable local user identities, independently assigns membership, and issues separate, randomly generated, expiring and individually revocable API and browser sign-in tokens. Persist only token hashes and non-secret lifecycle metadata in private operational state. API tokens authenticate API requests only; browser sign-in tokens are accepted only by the private HTTPS browser login form and exchanged for opaque server-managed sessions. Reject wrong-purpose credentials. No password database, password reset, self-registration or identity broker is introduced.
- Browser sign-in credentials, session cookies and decision tokens never enter Pi, model context, API tool results, URLs, tracked files or logs. Deliver credentials through an operator-controlled secure mechanism; an agent must not issue or capture a human's browser credential. Pi receives only its user's API token through host-supported secret configuration, not conversational input. Keep login/session-changing actions same-origin protected POSTs; GET never authenticates a user or approves content. Tokens do not prove human presence and do not authorize an agent to automate human approval.
- Check token expiry/revocation and local-user enabled state on every API request. Browser sessions retain their sign-in credential provenance: reject subsequent requests/actions when the user is disabled or the source browser credential is revoked or expired, even if the cookie's own lifetime remains valid. Disabling a user prevents new API and browser actions; API-token revocation does not revoke an unrelated browser credential, and vice versa. Existing current-membership checks remain independent. Session invalidation must not resurrect deleted credentials or let late obsolete responses erase a newer browser credential.
- In Entra mode retain one workforce tenant, a confidential web/API registration and pre-registered public Pi client, authorization-code/PKCE, maintained OIDC/token libraries, browser OIDC and resource-scoped API access tokens. Validate tenant/issuer, signature, audience, expiry and permitted client. Keep validated tenant/object identities distinct from stable local identities; do not fabricate Entra identities or associate them by email. Any future local/Entra mapping needs explicit administrator authorization and preserved permissions/history. Qualify the actual Pi registration/discovery/callback flow before claiming Entra support is live-qualified; that leg does not block the separately qualified local-token milestone.
- Workspace membership and capabilities are private operational state. Owner assignment is explicit; tenant membership alone grants no workspace role. Check current workspace permission on every request and again before an action. Removing workspace membership/capability immediately prevents new workspace actions even while an Entra token remains cryptographically valid. Entra account-disable propagation follows the configured provider/session lifetime; do not promise instantaneous tenant-wide revocation.
- Browser review uses a server-managed session separate from Pi credentials, same-origin protected POST actions, and a one-use action record bound to the exact native review and expected active state. A review URL only locates a review; GET, agent text, and API bearer credentials cannot authorize it. Verify current reviewer authority at POST and native admission. Browser session credentials/decision tokens never enter model context or API tool results. Do not let the agent automate the human approval interaction.
- Distinguish contribution, knowledge reading, review/admission, original inspection, connection authorization, and analytics execution. First-release analytics authorization covers a complete approved execution project's source set; it does not introduce arbitrary per-row filtering. If the engine would open a source outside that user's grant, refuse the operation before constructing the catalog. Use restricted database roles/views or separate projects for narrower data access.

### Deployment, client, and state

Use an optional `lumio-workspace` deployment package under `products/lumio/packages/`, consuming Lumio's SDK and optionally Ariadne through a lazy adapter. It is not an umbrella SDK or the private Lumio app. One Python 3.14 service exposes Streamable HTTP MCP, byte-upload endpoints, and the narrow browser review surface over owner-provided private HTTPS. A packaged Pi extension supplies connection guidance, exact-byte upload, and review links; ordinary contributors install no Core/SDK environment or Git checkout.

Git remains authored-content truth; immutable SDK/Core artifacts remain publication truth. Use one private SQLite operational store for memberships, task handles, idempotency keys, review actions, and native receipt references. Do not put a second editable copy of canonical content in it. Use one writer per task worktree and serialize activation per workspace; no distributed queue or separate scheduler. Original storage is private and explicitly selected. The model receives only authorized extracted material through the selected Pi processing policy, never server credentials or unrestricted shell access. The supported extension checks the selected provider/model against the owner's disclosure policy before releasing material and after a model change. This is a trusted-client policy, not remote attestation or a guarantee about what an authorized person does after reading content.

Task operations use opaque workspace/task/upload IDs rather than user-supplied server paths. Bind retry keys to actor, workspace, action, and input digest; a changed payload under the same key conflicts. After interruption, reconcile native state before reporting or retrying a side effect. Backup with writes quiesced covers Git, private source history and derived data artifacts, published artifacts, and SQLite consistently; restore starts read-only, re-establishes secrets, and invalidates outstanding approval actions before accepting new writes.

### Input and lifecycle bounds

- Text/Markdown, PDF and DOCX use the existing Lumio processors and their current bounds: 25 MiB original, 200,000 extracted characters, 200 sections, 20-second conversion timeout, and existing archive checks. Keep truthful incomplete-conversion reporting. Legacy Word formats are unsupported unless the existing local converter actually supports them; no external OCR service is selected.
- CSV/JSON/Parquet and SQLite/DuckDB/PostgreSQL/Delta/Iceberg/DuckLake retain the documented native source and named-S3-profile contracts. A trusted DuckDB catalog is not an arbitrary safe upload: backing access must receive operator approval. No bucket-wide scanning, new catalog protocol, or unsupported vendor is implied. Remote datasets remain remote; bounded profiling/query does not require uploading their complete bytes.
- XLSX is a derived query source, not Markdown conversion. Select sheets explicitly, retain workbook digest and sheet/cell mapping, preserve stored cell types/dates and missing values, and disclose formula-cache age as unknown. Missing/error cached results in a selected formula cell block query activation until corrected or explicitly excluded through a new reviewed selection; never silently substitute zero. No macros, external-link fetching, recalculation, or automatic joins. Importer limits: 25 MiB input, 64 MiB expanded archive, 200,000 selected nonempty cells, and a 20-second worker deadline; refuse excess without partial activation. Limits are operational bounds, not evidence that larger files were imported.
- Refresh is explicit: changed files get new source versions; changed live-source definitions/locations get fresh exact approval and evidence. An unchanged existing exact grant may be reused. Native live-query data freshness remains distinct from immutable model/knowledge releases.
- Retain originals by default without automatic expiry. The explicitly authorized document-only exception in §12.4 may omit durable original retention; it does not delete previously retained bytes or relax integrated/independent-host obligations. Publication retirement does not erase history or bytes. First-release deletion is an owner-operated, explicitly authorized native/private-store procedure, not a contributor tool: show affected bindings, apply existing retention refusals, and report originals/history/backups that remain. Do not claim compliant erasure of every immutable copy. Source/code deployment never triggers cleanup of existing projects.

### Acceptance additions and qualification prerequisites

| ID | Scenario and required outcome |
| --- | --- |
| AC15 | A Pi API credential can submit authorized work but cannot approve it. A separately browser-authenticated reviewer (local-token or qualified Entra mode) approves the exact browser-displayed action; revoked workspace membership and stale actions refuse. |
| AC16 | A supported XLSX fixture has independently known stored values, a selected sheet, and an uncalculated formula. Query activation refuses the missing cache; a corrected version produces the hand-worked result and cell/source provenance without recalculation. |
| AC17 | A named S3 endpoint/scope changes after review. Existing consent cannot authorize the changed target; unchanged-target credential rotation retains native behavior and does not expose credentials. |
| AC18 | The full milestone demonstrates document intake, structured files, database tables, and supported S3 file/table families through the managed path, reusing applicable native adapter evidence. A text-only demo is an intermediate slice, not completion. |
| AC19 | After backup/restore or access revocation, a reader sees only permitted admitted state; pending/rejected content and stale browser approvals do not become active. Retention/deletion outcomes remain truthful. |
| AC20 | Two stable local users use distinct API/browser credentials. Unknown, expired, revoked and wrong-purpose credentials refuse. API bearer tokens cannot create browser sessions or approve actions. Disabling a user and revoking/expiring a browser sign-in credential refuse the corresponding subsequent sessions/actions without stale-session resurrection or loss of a newer login. Membership removal blocks both routes independently of valid credentials. |
| AC21 | An explicitly configured local-token deployment connects the installed Pi client to private HTTPS and reads a pinned synthetic publication with its user's API token; a human signs in separately in the browser. Existing forbidden-model/history protections still apply. Entra mode does not silently fall back, and missing Entra settings do not block explicitly selected local-token mode. No test or status labels deferred live Entra checks as passed. |

The local-token live leg requires two approved human identities with securely delivered purpose-separated credentials, a reachable private HTTPS endpoint, installed Pi and a pinned synthetic publication. Synthetic database/S3 fixtures remain required for their respective journeys. This removes tenant registration as an interim milestone prerequisite, not private connectivity or actual human/client qualification. Real Entra tenant/application configuration is required only for the deferred Entra live leg; retain it as an explicit outstanding obligation. Unit fixtures establish gates, not successful live identity/client integration. Deployment, live access and model processing still require their own authorization.

## 11. Planning handoff

[Shared plan0034](../plans/2026-11-04-0034-agent-first-shared-workspaces.md) owns the service/client/review path and dependency order. [Lumio plan0011](../../products/lumio/project/plans/2026-11-04-0011-document-first-enrichment.md) owns neutral defaults and optional enrichment. [Ariadne data plan0034](../../products/ariadne/project/plans/2026-11-04-0034-managed-data-onboarding.md) owns analytics adapters and input handling. Each task body has one owner; the shared overview only links product tasks.

Capture checkpoint: existing glossary terms suffice; `knowledge-artifact` is a controlled-type identifier, not a new bounded context. ADR-0028 records the operating/identity trade-off; Lumio ADR-0032/spec0003 own enrichment. Behavioral scope is grounded in the owner's recorded choices; §10 and the execution maps are approved; implementation still requires its own grant. Planning-contract version 1; installed skill revision unknown. Historical ticket-publication authority is not a new tracker grant. This revision-4 handoff authorizes recording the design and presenting the proposed plan only; no code, tenant configuration, deployment, source access, integration, Git push, release or issue mutation is authorized.

## 12. Curated-wiki retrieval and original references (proposed revision 5)

**Approved 2026-11-09:** “Freigegeben. Ticketize” accepts this complete revision and plan amendment revision 1, including delivery choices below. The heading is retained for existing fragment links; “proposed” records its drafting history, not current approval status.

### 12.1 Scope and preserved boundaries

Extend the existing standalone managed Lumio/Pi path, reusing SDK Evidence, Citation, Source Registry, Artifact Store and native review/publication. Search only admitted Compiled Pages, never originals, extracted source transcripts or pending candidates. Source inspection through a page reference is a separate authorized operation, not another retrieval source. No original-search mode, answer-generator service, automatic graph expansion, SharePoint connector, new storage protocol, personal/team ACLs or new chat UI is selected. Optional BM25 does not select semantic/Hybrid retrieval; existing advanced SDK users retain those capabilities unchanged.

Ariadne's integrated navigation/calculation remains on its exact Bound Release and operator Visibility Scope. This amendment does not replace `search_context`, repin an integrated session, expose a separately moving knowledge view as governed context, or relax required Policy closure. The first new Evidence tool is for standalone knowledge; an integrated workspace must refuse that tool rather than fall back to a moving standalone publication. Existing integrated operations remain available. Supporting enhanced integrated retrieval is a later scoped change.

### 12.2 Authorized view and evidence

The shared audience includes explicitly `public` and `internal` admitted pages; `restricted` and absent/unknown Visibility are unavailable through ordinary workspace reads, searches, citations, related-page output and original references. There is no implicit Visibility hierarchy. Narrower-audience submissions continue to be refused. All reachable ordinary knowledge paths must use the same authorized candidate set before matching, ranking, limiting, counting or snippet construction. A hidden title/alias/ID and a missing one produce indistinguishable unavailable results; filtering only the final results is insufficient. This establishes shared-scope filtering, not individual ACLs.

Expose bounded Evidence retrieval with the existing zero-index adapter by default and explicitly configured optional LanceDB BM25. Return canonical page/section text, inclusive line coordinates where provided, page identity, exact Published Version and truthful retrieval/fallback information. Enforce the same request bounds as existing search (normalized query at most 256 characters, limit 1–20, default 5); at most 16,000 returned Evidence-text characters are permitted per call. Oversized indivisible units are omitted with truthful omission/truncation disclosure, not returned with false complete spans; no evidence/coordinate fabrication is allowed. Keep page search/read contracts compatible. Existing read/search responses also expose the stable Entity ID and exact Published Version needed by supported follow-up/edit/enrichment operations, using producer-owned metadata; a caller must not inspect private files or infer IDs from titles. Resolving a cited section subsequently must remain on its publication, not silently follow current. Historical reads are restricted to admitted history in the configured namespace/workspace under current authorization; arbitrary paths, buckets and version roots are not selectable.

The index is derived, publication/fingerprint-bound, and never built into an immutable published tree by a reader. Missing or unhealthy BM25 state may use the existing lexical fallback on the same authorized snapshot, explicitly disclosed; no embedding/provider/network call is added. Restricted content must not affect visible scores or counts: BM25 index material is built from the authorized shared view, not merely postfiltered from a broader index. No automatic Lifecycle re-ranking or new `approved`-only metadata filter is implied; native publication admission remains the reader boundary.

### 12.3 Original references and access

From an authorized admitted page, identify an original by page/entity, Source ID and exact Published Version. Resolve the existing private binding and verify returned bytes; never substitute registry-latest, arbitrary hashes or caller-supplied storage paths. Retain all authored source references; do not silently select only the first one. Reader-visible attribution is distinct from private artifact metadata.

Only current workspace members with separate `inspect_source` capability may resolve private original availability or download originals. Review or ordinary read alone does not grant inspection. An ordinary reader may receive a non-secret reference action that still requires authorization when opened; that action conveys no bearer access. Before authorization, do not probe the private store or reveal presence, safe filename, size or digest. Authorized outcomes distinguish not retained, temporarily unavailable, denied backend access, corrupt content and absent historical binding without exposing credentials/object keys. An external URL remains external attribution, not an exact-original substitute.

Original opening must work independently of a pending review/task. Deliver verified bytes through the separately authenticated browser boundary as a safe attachment, not active inline HTML, model-readable signed URLs, or permanent public object links. Recheck current permission on the request. No automatic original content enters the answer/model context. Publication retirement is not authorization to delete originals or to expose retired/private pages.

The existing pending-review source-inspection route must likewise deliver exact verified PDF/DOCX original bytes as a safe attachment instead of decoding binary content as UTF-8. It resolves the selected candidate's binding under the review boundary and current separate `inspect_source` permission; the published-reference route remains restricted to admitted history. Pending content must not become searchable/readable through ordinary knowledge retrieval. Missing or corrupt originals do not substitute extracted text or registry-latest. Share verified byte resolution where appropriate; no previewer or raw-passage highlighting is required.

### 12.4 Retention exception

Default remains required retention. A storage outage or failed upload is an error, never implicit permission to omit originals. Only an explicit owner-confirmed configuration may enable non-required retention for **standalone document knowledge**; submission/review must disclose that no durable original copy is promised. Source identity, digest, exact-version bindings and normal content admission remain mandatory. Review binds the effective retention/configuration; changing it invalidates stale consent.

The exception does not mean secure deletion: temporary uploads, operational files, previously retained originals and backups may exist and must not be mislabeled as erased. Missing artifacts do not make source-backed pages synthetic. New sources can be ingested under the selected exception without fabricating retention success; existing default native callers must still refuse that case. The independent-host bundle journey in Lumio spec0010 and integrated Ariadne admission retain required retention and cannot select this exception. Existing deployments are not auto-migrated; permission/profile changes need owner confirmation and do not delete prior bytes.

### 12.5 Storage and recovery

Reuse local persistent server storage and the private S3-compatible Artifact Store, outside published knowledge. The registry remains server-managed private state; adding S3 does not replace the registry or require client credentials. Do not provision buckets/IAM, introduce a new registry, or claim all S3-compatible providers are equivalent.

A stopped-writer backup must include the original objects/metadata required by retained registry/history and private publication records/bindings, along with consistent authored/published/operational state. A list of remote keys without bytes is not a complete backup. Inspect exact registered identities, not unrelated bucket prefixes; fail visibly on unavailable required bytes, corruption or incomplete copy. Legitimately unretained versions are recorded as such. Restore into a fresh root, never overwrite an existing store; preserve exact historical bindings and pending/rejected visibility, invalidate old sessions/actions, and re-establish credentials separately. Default restore may materialize originals into a new local private store; reconnecting/migrating to S3 is an explicit operator step, not implied by copying configuration. Confirm the restored target before writes and do not silently rewrite immutable admission identities.

After owner reconfirmation and any native revalidation/admission required by changed destination identities, a restored standalone workspace must support a fresh reviewed publication, not merely reads of old originals. Before those prerequisites, dependent writes refuse with actionable guidance. Preserve historical immutable records; do not rewrite them to authorize another target. The shared-repository and analytics-query recovery outcome is owned by spec0035, not added to this standalone task.

### 12.6 Acceptance additions

| ID | Scenario and required outcome |
| --- | --- |
| AC22 | A standalone reader retrieves an independently authored runbook section via Zero-Index and configured BM25; text, section/coordinates and publication identity agree. Cited-version reread after a new activation still returns the old admitted version. An unhealthy index produces explicit same-version lexical fallback; no model call occurs. Existing read/search responses return stable Entity ID and exact publication so supported follow-up requests need no private-file lookup. |
| AC23 | An admitted snapshot contains public/internal pages and a restricted page with a unique marker/alias. Every ordinary read/search/Evidence/reference path hides the latter before ranking/counts; restricted terms do not alter visible ranking. Revoked members receive nothing. New narrower-audience contributions are refused. |
| AC24 | Two source versions support two publications of one page. An authorized inspector opens each publication's exact bytes through its reference without a pending review; a reader/reviewer without inspection permission cannot probe presence or download. Missing/corrupt historical content never substitutes latest or a live URL. Original-only unique text never appears in wiki search. A supported binary original is also inspectable through the pending-review route under its exact candidate binding and separate current permission, without exposing pending content through the published route. |
| AC25 | Default retention refuses an unavailable original before activation. An owner-confirmed standalone exception admits source-backed knowledge with honest unavailable-original disclosure; retries preserve identity and changed retention invalidates old consent. Required independent-host/integrated flows still refuse omission. |
| AC26 | Local and one named S3-compatible artifact configuration preserve exact original bytes/version history. After a stopped-writer self-contained backup, a fresh-root restore can open the same bound originals with the old remote endpoint unavailable; intentionally unretained versions remain unavailable. Old browser sessions/actions cannot activate work. A failed required-object copy does not produce a successful backup. After required owner reconfirmation/native revalidation, a fresh standalone contribution is reviewed and published successfully; historical reads alone do not satisfy recovery. |
| AC27 | From a new empty workspace, a separately authenticated human can review/publish the first document and then retrieve its admitted evidence and open its retained original. If the audited bootstrap defect reproduces, repair only that admission prerequisite without creating an unreviewed initial publication. |
| AC28 | Existing integrated knowledge/calculation tools retain exact Bound Release, Scope and Policy behavior. The new standalone Evidence tool refuses an integrated workspace instead of silently changing its governed knowledge view. |

### 12.7 Delivery details and handoff

Revision 6 and plan amendment revision 2 carry the 2026-11-10 approval above. R1/R2/R4/R5 receive only the named deltas, preserving their existing evidence budgets; the final installed journey includes binary pending-review inspection and a post-restore publication without another live suite. Earlier revision-5 approval/snapshots below remain historical evidence, not the current source for amended requirements.

Approved with the implementation plan: add one standalone MCP tool `retrieve_knowledge`; preserve `search_knowledge` and `read_knowledge` with additive version-aware follow-up where necessary. An operator-only `lumio-workspace prepare-retrieval` command prepares the optional authorized BM25 cache for the configured admitted publication; it never activates content or writes published trees. Missing preparation uses the disclosed lexical fallback. A browser original-reference/download endpoint uses the existing browser authentication and `inspect_source` grant. Reuse existing adapters and private profiles; optional dependency placement remains outside base SDK dependencies. One self-contained backup path restores both local and remote source artifacts into a fresh local store; no remote-to-remote migration protocol is introduced.

These delivery details and plan amendment revision 1 were explicitly approved with “Freigegeben. Ticketize” on 2026-11-09, beyond the earlier scope-only “Ja passt.” GitHub issues now own the canonical task bodies; the [Plan0034 retrieval/source overview](../plans/2026-11-04-0034-agent-first-shared-workspaces.md#curated-wiki-retrieval-and-source-storage-amendment-proposed) links them. Existing historical tickets are not silently redefined. Execution still requires a separate implementation grant.

Capture: existing Knowledge Source, Source Artifact, Evidence, Citation, Publication Admission and Bound Release terms suffice; no glossary or new ADR is needed. ADR-0028 records the scoped operating/retention trade-off. Lumio ADR-0020 already separates originals from retrieval; spec0010 is reconciled with the workspace-only exception, without weakening its independent-host route. Planning-contract v1; installed provenance unknown. Research is evidence, not execution authority. No product code, tracker, credentials, live endpoint or deployment is changed by this document.
