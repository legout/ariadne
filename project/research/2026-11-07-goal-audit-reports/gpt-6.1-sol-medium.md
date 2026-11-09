# Overall verdict: **PARTIALLY ACHIEVED**

The repository contains substantial working implementations—not just scaffolding. But the managed platform has broken first-use and repeat-use journeys, incomplete integration of its retrieval capabilities, and important governance/recovery gaps. **It is not yet a platform I would hand to a team expecting agents and browser reviewers to operate without manual intervention.**

## Scope and evidence standard

Audited commit: `2f5bc9708f0a7fad33d1f6483c239b8f3116ce9d`.

This was a source-only audit. No plans, specifications, ADRs, issue trackers, or historical implementation claims were used as evidence. No tests or live deployments were run. Consequently, **WORKS below means a traced runtime implementation exists—not that deployment interoperability or production behavior was demonstrated.**

Path abbreviations:

- **W**: `products/lumio/packages/lumio-workspace/src/lumio_workspace/`
- **A**: `products/ariadne/packages/ariadne-data/src/ariadne/`
- **K**: `products/lumio/packages/lumio-wiki/src/lumio_wiki/`
- **L**: `products/lumio/packages/lumio-lancedb/src/lumio_lancedb/`
- **P**: `products/lumio/clients/pi-workspace/`

---

## AREA 1: Data pipeline

**VERDICT: PARTIALLY WORKS**

### EVIDENCE

- Uploads support CSV, JSON, Parquet and XLSX, with actor-scoped receipts, content hashes and a 25 MiB streaming limit: [W/intake.py:17–137](products/lumio/packages/lumio-workspace/src/lumio_workspace/intake.py#L17).
- Source preparation, browser source approval, separate data authorization, profiling and query dispatch are connected: [W/analytics.py:294–560](products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py#L294), [735–874](products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py#L735).
- Native readers exist for SQLite, DuckDB, PostgreSQL, file sources and the advertised S3/lakehouse families: [A/sources.py:678–816](products/ariadne/packages/ariadne-data/src/ariadne/sources.py#L678).
- Governed queries compile through the renderer, enforce a single statement, bind, check grain and collect bounded results. Responses include SQL, governance status, context and admission provenance: [A/query.py:392–507](products/ariadne/packages/ariadne-data/src/ariadne/query.py#L392).
- Workspace results add the admitted commit and source digest: [W/analytics.py:511–560](products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py#L511).

### GAPS

**1. PostgreSQL approval does not pin the actual database destination.**

Approval records `connection_env`, while execution resolves the variable’s current DSN. Unlike the S3 effective-binding mechanism, PostgreSQL does not bind the resolved host/database identity.

Changing that environment variable can therefore redirect an already-approved source without changing its recorded identity.

Evidence: [A/authoring_sources.py:99–130](products/ariadne/packages/ariadne-data/src/ariadne/authoring_sources.py#L99), [A/sources.py:1015–1027](products/ariadne/packages/ariadne-data/src/ariadne/sources.py#L1015).

This is a governance correctness defect, not evidence of SQL injection.

**2. Profiling is row-sampled, but not comprehensively bounded.**

The workspace requests 100 sampled rows, but the profiler constructs the complete registry connection/catalog before narrowing to the selected table. That path supplies no execution deadline, and sampled rows do not bound individual cell sizes or the complete response.

A slow external connection or unusually large text values can still make “bounded profiling” expensive or unresponsive.

Evidence: [W/analytics.py:470–509](products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py#L470), [A/authoring_sources.py:514–577](products/ariadne/packages/ariadne-data/src/ariadne/authoring_sources.py#L514), [A/profiler.py:486–516](products/ariadne/packages/ariadne-data/src/ariadne/profiler.py#L486).

**3. The workspace adapter does not preserve all native query safeguards.**

It does not pass a single request-lifetime budget or MCP-envelope measurement into the runtime, adds `pinned` after native response accounting, and converts structured `QueryResultError` refusals into plain `WorkspaceError` strings.

The numerical query guards still exist. The complete workspace request/response contract is weaker than the underlying engine’s contract.

Evidence: W/analytics.py:528–560; W/app.py:475–491; A/query_results.py:180–208.

**4. External sources require operator provisioning, not merely browser approval.**

An agent cannot submit a new arbitrary PostgreSQL/S3 connection for a human to configure entirely in the browser. It must reference an opaque handle already present in the operator-controlled binding file.

The refusal is actionable—“ask the owner to provision”—but the agent cannot self-correct through the workspace.

Evidence: W/analytics.py:101–127.

**5. The first-query workflow is bureaucratic.**

For a fresh uploaded source and new governed metric, the logical sequence is:

1. Upload.
2. Prepare source.
3. Browser approve source.
4. Browser grant data access.
5. Profile.
6. Prepare knowledge/metric contribution.
7. Browser approve submission.
8. Browser approve publication.
9. Query.

That is **nine actions and four browser decisions**, excluding authoring the metric and navigating back to fresh review pages. It is not shorter than five steps.

**6. Format support is not equivalent to demonstrated real-world interoperability.**

The readers are implemented. Real PostgreSQL deployments, representative XLSX producers, and every S3 table family remain **CANNOT DETERMINE FROM CODE** as operational claims.

### Configuration before the first query

For a fresh integrated local-token deployment:

- **11 server environment settings**: five base, two authoring, namespace, three analytics.
- **Four Pi client settings**.
- Private-profile and operator source-binding configuration.
- Authored registry, semantic and knowledge artifacts.
- Source credentials and DuckDB extensions where applicable.

Entra adds six server settings. Not every authored file needs manual creation, but this is not a one-setting onboarding experience.

---

## AREA 2: Knowledge pipeline

**VERDICT: PARTIALLY WORKS**

### EVIDENCE

- Text/PDF/DOCX originals have actual upload and extraction paths: [W/intake.py:155–183](products/lumio/packages/lumio-workspace/src/lumio_workspace/intake.py#L155), [K/authoring_journey.py:143–236](products/lumio/packages/lumio-wiki/src/lumio_wiki/authoring_journey.py#L143).
- Extraction produces normalized material; **Pi must author the structured pages**. Uploading a PDF does not itself generate a finished knowledge page.
- Typed metadata, entities, claims and evidence anchors are implemented and validated: K/records.py:172–205; K/knowledge_base.py:3043–3181.
- Browser review contains body diffs, semantic changes, source changes and analytics file diffs: [W/review.py:837–1004](products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py#L837), A/contribution_review.py:110–171.
- Publication uses immutable versions and expected-current activation. Rejection does not switch published content: W/review.py:511–568; K/git_authoring.py:2052–2286.

### GAPS

**1. Fresh knowledge-only browser setup cannot reach its first publication. — BLOCKER**

Setup creates and commits the knowledge base and returns `ready: true`, but does not publish a baseline. The ordinary review path then refuses a candidate when no admitted baseline exists.

A fresh user can prepare a contribution but cannot complete the first browser publication through that supplied path.

Evidence: [W/setup.py:280–331](products/lumio/packages/lumio-workspace/src/lumio_workspace/setup.py#L280), [W/review.py:208–218](products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py#L208).

**2. Ordinary document publication does not naturally support the next document. — BLOCKER**

The server chooses the authoring checkout’s `HEAD` as the next contribution base. Publishing advances the publication pointer, not that checkout.

After publishing candidate A, a new candidate B starts from the old checkout HEAD. Publication requires B to descend from A and refuses it. The API also refuses supplying a different `base_revision` from its server-selected base.

The result is a manual Git reconciliation requirement inside a supposedly managed workflow.

Evidence: [W/contributions.py:163–193](products/lumio/packages/lumio-workspace/src/lumio_workspace/contributions.py#L163), W/publication.py:58–74; [K/git_authoring.py:1540–1550](products/lumio/packages/lumio-wiki/src/lumio_wiki/git_authoring.py#L1540).

**3. Enabling analytics blocks ordinary knowledge-only submissions.**

Every ordinary contribution is routed into analytics and requires `source_task_id`, even when there are no metric edits. A handbook submission consequently needs an unrelated data-source grant.

Enrichment has a separate route, but that does not solve ordinary new-document submission.

Evidence: [W/app.py:534–565](products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py#L534).

**4. Agents cannot discover the IDs required for enrichment.**

Search and read return titles, paths and bodies—but omit the page Entity ID and full metadata. Enrichment requires exact Entity IDs before returning its selection.

A new agent can find a page but cannot obtain the identifier necessary to enrich it through the supplied discovery tools.

Evidence: W/app.py:327–362; [W/enrichment.py:184–200](products/lumio/packages/lumio-workspace/src/lumio_workspace/enrichment.py#L184).

**5. Browser source inspection mishandles PDF/DOCX originals.**

The source-inspection route fetches retained original bytes and decodes them as UTF-8. Those are the original binary documents, not their extracted text.

DOCX normally fails; PDF either fails or presents PDF internals rather than readable evidence. Integrated analytics reviews categorically reject this inspection route.

Evidence: [W/review.py:332–365](products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py#L332), K/authoring_journey.py:665–752.

**6. Enrichment has two additional correctness gaps.**

- Selection limits do not impose corresponding page-count/total-character limits on the authored candidate: W/enrichment.py:107–119; W/contributions.py:343–380,476–513.
- Removed claims can display evidence quotations from the candidate body instead of the historical body containing the removed claim: W/review.py:705–727.

**7. “Complete diff” is implemented; “approachable review” is not.**

The analytics review includes actual metric and knowledge changes. It is not missing those changes. However, it renders much of them as escaped JSON, alongside numerous hashes, revisions and native lifecycle concepts.

This is an expert verification page, not a self-explanatory review experience for a nontechnical colleague.

### PDF-to-searchable step count

With an existing usable baseline, the intended path is:

**Upload → extract → agent authors/prepares → browser approves → search/read.**

That is five observable actions including read-back. Fresh setup and repeated ordinary publication encounter the blockers above.

Rejection preserves admitted content, but **does not erase privately retained uploads or registry history** created during preparation.

---

## AREA 3: Agent consumption

**VERDICT: PARTIALLY WORKS**

### EVIDENCE

- The Pi extension actually registers the workspace MCP server for local-token or Entra authentication: [P/index.ts:29–82](products/lumio/clients/pi-workspace/index.ts#L29).
- It implements model allowlisting and retained-content disclosure guards.
- Workspace MCP exposes knowledge lookup/search, source preparation/profiling, query dispatch, contribution/enrichment preparation and task lookup: W/app.py:315–605.
- Governed and ad-hoc query implementations distinguish their status; pending contributions explicitly report `published: false`.

### GAPS

**1. LanceDB retrieval is not exposed by the managed workspace.**

The adapter implements semantic/hybrid retrieval. The workspace’s search calls ordinary lexical `search_pages`, and workspace publication supplies no LanceDB index builder.

Installing the adapter does not connect it to this facade.

Evidence: [L/index.py:567–720](products/lumio/packages/lumio-lancedb/src/lumio_lancedb/index.py#L567), W/app.py:347–362; W/publication.py:58–74.

**2. The managed API omits essential discovery operations.**

There is no managed dispatch for:

- Metric catalog/discovery.
- Dataset/source-handle inventory.
- Terminology resolution.
- Contract inspection.
- Entity resolution and graph traversal.
- Ontology inspection.

Many of these exist in the underlying SDK/Core. Agents restricted to the managed workspace cannot simply use those local interfaces without obtaining the source/Git access the platform is meant to avoid.

Evidence: W/analytics.py:530–549; A/query.py:1555–1585; K/location.py:245–359.

**3. Entra-connected Pi users cannot use the supplied upload command.**

The extension supports Entra MCP authentication but explicitly refuses `/workspace-upload` outside local-token mode.

Evidence: [P/index.ts:138–149](products/lumio/clients/pi-workspace/index.ts#L138).

**4. Installation and connection remain manual.**

The extension registers MCP once configured; that part is real. But the package contains no automatic workspace enrollment or bundled skill installation, and is marked private.

Local-token setup needs the extension, four environment settings, credential provisioning and a reload. Entra needs additional client configuration.

Evidence: P/package.json:1–8; P/index.ts:29–47,212–257.

**5. The supplied Core skill targets another operating surface.**

The 766-line Core skill starts with local CLI/Git-project instructions, including “no server.” That is not an adequate managed-workspace operating guide for an agent prohibited from accessing the repository.

Evidence: A/skill_assets/SKILL.md:8–27.

**Under-ten-minute productivity: CANNOT DETERMINE.** No timed user exercise was performed. The missing discovery tools and identifier seam are concrete obstacles regardless.

**Actual Pi → real workspace → browser approval → subsequent agent consumption: CANNOT DETERMINE as live interoperability.** The code wiring exists; the examined Pi disclosure test uses a synthetic MCP server, not the complete workspace.

---

## AREA 4: Collaboration and human–agent boundary

**VERDICT: PARTIALLY WORKS**

### EVIDENCE

| Requirement | Assessment |
|---|---|
| Agent bearer token cannot approve | **WORKS in the examined API paths.** Approval requires a browser session, current permission, HTTPS and matching Origin. Local API/browser credentials have separate purposes. |
| Single-person browser self-approval | **WORKS.** Explicit exception; otherwise another member must approve. |
| Workspace revocation | **WORKS for subsequent authorization checks.** Credentials and browser sessions are rechecked; review permission is checked again under activation locks. |
| Rejection preserves published state | **WORKS.** No publication activation occurs. |
| Restore invalidates pending actions | **WORKS narrowly.** Issued/pending review actions and browser sessions are deleted. |
| Complete usable restore | **DOES NOT WORK for moved integrated analytics state.** |

Evidence: [W/app.py:706–750](products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py#L706), W/auth.py:75–96; [W/review.py:366–424](products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py#L366), W/state.py:185–227,321–365,622–628; W/operations.py:186–190.

### GAPS

**1. Moving a backup breaks existing analytics admissions. — BLOCKER**

Admissions contain an absolute project path. Restore copies the project and changes configuration paths but does not relocate its admission descriptors and associated bound state.

`query_data` passes the copied admission into `QueryRuntime.open_project`, which rejects the old project identity.

There is an additional structural problem: restore duplicates authoring and analytics repositories even when they originally represented the same Git repository.

Evidence: [A/admission.py:1057–1087](products/ariadne/packages/ariadne-data/src/ariadne/admission.py#L1057), [W/operations.py:193–254](products/lumio/packages/lumio-workspace/src/lumio_workspace/operations.py#L193), [A/query.py:1510–1517](products/ariadne/packages/ariadne-data/src/ariadne/query.py#L1510).

Fixing this requires an explicit relocation/re-admission mechanism—not blindly editing digest-bound records.

**2. Browser approval can stall the shared server.**

The async route directly invokes synchronous review/validation/publication work. Native live validation can connect to external sources without a deadline.

One slow approval can block the application event loop and hold activation locks, delaying unrelated users and browser revocation requests.

Evidence: W/app.py:747–748; W/analytics.py:785–831; A/validate.py:260–275.

**3. Form limits are checked after buffering the complete body.**

Login reads the whole request before checking its 4 KiB limit. Other forms repeat this with 8 KiB limits.

A caller able to reach local-token login can consume substantial memory before rejection. An upstream body limit might mitigate this, but none was established by this audit.

Evidence: W/app.py:665–669,731–735,798–802,867–872.

**4. Revocation guarantees have limits.**

- Workspace membership revocation is checked.
- Cancellation of already-running operations is not established.
- Disabling an Entra directory account is not the same as revoking local workspace membership; there is no per-request directory-enabled check.

**5. Audit records exist, but the audit product is incomplete.**

Approval identities, bindings, decisions and timestamps are persisted. Membership changes, however, overwrite/delete current rows without recording the grantor/revoker and historical event. There is no browser audit explorer.

Evidence: W/state.py:125–175,340–365,543–635.

**6. Two policy questions remain unresolved from code alone.**

- Enrichment can advance knowledge publication independently of the Core bound release. Knowledge reads may show newer content while metrics truthfully use older pinned context.
- Managed readers do not filter page visibility. Ordinary contributions require `internal`, but adopted content can have other valid visibility values. Whether such destinations are prohibited operationally is unverified.

These are limitations requiring explicit ownership decisions—not invented claims of an exploitable bypass.

**No agent-token approval bypass was found in the examined managed routes.** That is narrower than proving no bypass anywhere.

---

## AREA 5: Operational simplicity

**VERDICT: PARTIALLY WORKS**

### EVIDENCE AND COUNTS

| Moving part | Actual implementation |
|---|---|
| Application server | **One Uvicorn worker** in the supplied launcher. |
| HTTPS | Required; termination is an additional deployment responsibility. |
| Agent process | Pi runs separately on the client. |
| Transient processes | Document/XLSX conversion workers and Git subprocesses. |
| Operational database | **One SQLite database.** |
| Data engine | Embedded DuckDB; no separate DuckDB server required. |
| Vector engine | Optional embedded LanceDB; not connected to the managed facade. |
| Authored state | Git repository and task worktrees. |
| Other persistent state | Uploads, extractions, originals, source-registry JSON, publication versions, admission snapshots/receipts and binding/profile files. |
| First-party Python packages | **Three** for managed analytics: workspace, wiki, Core. **Four** with LanceDB. `ariadne-agent` is unnecessary for Pi. |
| Runtime baseline | Python **3.14+**, Git, Pi’s runtime; connector/converter dependencies as selected. |
| Fresh server configuration | **11 local-token settings**, or **17 with Entra**, before optional source credentials/settings. |

Evidence: W/__main__.py:40–43,86–88; W/app.py:141–185; W/auth.py:39–51; W/operations.py:30–40,111–145; package `pyproject.toml` dependency sections.

**Storage has nine separately recognized durable roles in backup code. These are not nine databases—but they are nine things operations must keep coherent.**

### GAPS

- “One application process with embedded engines” is substantially true.
- “Maximally simple” is not.
- Backup requires quiescence/service shutdown; the code copies SQLite directly rather than establishing an online-backup protocol.
- No complete integrated relocation/recovery path.
- No automatic deployment/enrollment path demonstrated by the implementation.
- No dependency-health monitoring, metrics, alerting, aggregate quotas or managed retention lifecycle.
- Multiple configuration locations encode related identity/path facts.

The four workspace-member Python implementations total approximately **98,750 physical lines**, including comments/docstrings. The wiki CLI alone is **10,629 lines**; `knowledge_base.py` is **5,646**.

That size includes real standalone SDK functionality. It is not proof of dead code. Nevertheless, the delivered managed experience is disproportionately thin and fragile relative to its implementation footprint.

**Deployment time: CANNOT DETERMINE FROM CODE.** A confident “30-minute setup” or “two-day deployment” would be an invented estimate.

---

## AREA 6: Missing capabilities

**MISSING:**

“Missing” here means absent as a usable **managed-platform capability**. Where the SDK already implements something, that distinction is stated rather than calling it globally nonexistent.

### Core managed journeys

1. **Browser first-publication bootstrap:** fresh knowledge-only setup cannot complete its first review. **[blocker]**
2. **Repeatable ordinary document publication:** subsequent documents need manual ancestry reconciliation. **[blocker]**
3. **Independent knowledge-only submission with analytics enabled:** unrelated data grants are required. **[major]**
4. **Discoverable page IDs/full metadata:** agents need these to update and enrich existing pages. **[major]**
5. **Readable PDF/DOCX evidence in browser review:** retained originals are incorrectly treated as UTF-8. **[major]**
6. **Usable relocated analytics recovery:** moved backups retain old admission/path identities. **[blocker]**
7. **Pinned effective PostgreSQL destination:** current approval identifies the variable, not its resolved database target. **[major]**

### Retrieval, authoring and agent interfaces

8. **Managed semantic/hybrid retrieval:** implemented in LanceDB adapter, absent from workspace dispatch/publication. **[major]**
9. **Managed entity/claim graph and ontology navigation:** SDK capabilities are not exposed. **[major]**
10. **Managed metric catalog/discovery:** agents should not need known metric names or deliberate error probing. **[major]**
11. **Managed dataset/source-handle inventory:** agents need discoverable valid inputs. **[major]**
12. **Managed terminology and contract inspection:** local Core functionality does not replace remote access. **[major]**
13. **Entra-authenticated bundled Pi upload:** MCP login works; the upload command refuses it. **[major]**
14. **Automatic client enrollment and managed-workspace skill delivery:** configuration remains manual. **[major]**
15. **Browser-only external-source provisioning:** owner binding-file edits remain necessary. **[major]**
16. **Atomic multi-upload data onboarding:** the managed source flow selects one source handle; no batch contribution workflow is exposed. **[minor]**
17. **Managed delete/merge/rename knowledge maintenance:** native capabilities exist, but corresponding workspace operations do not. **[major]**
18. **Paginated discovery/search:** managed search is bounded to twenty results without continuation. **[minor]**
19. **Maintained remote client libraries/native IDE or mobile integrations beyond Pi:** MCP remains a generic protocol option; the local SDK is not a remote workspace client. **[minor]**

### Human collaboration

20. **Review/task inbox:** reviewers need discoverable pending work, not only exact task URLs. **[major]**
21. **Review notifications:** no supplied notification delivery or subscription mechanism. **[major]**
22. **Review comments and change-request reasons:** the form submits only a digest and decision. **[major]**
23. **Published knowledge browsing UI:** `/workspace` is a JSON status response, not a knowledge application. **[major]**
24. **Human browser upload interface:** supplied intake is API/client oriented. **[minor]**
25. **Charts and data dashboards:** humans cannot visualize results through this workspace UI. **[major]**
26. **Published-version/page-history browser:** immutable versions exist without a managed history interface. **[major]**
27. **Managed rollback:** native rollback exists, but no workspace agent/browser operation is exposed. **[major]**
28. **Managed export/download workflow:** SDK/CLI exports exist; the managed interface does not expose them. **[minor]**
29. **Complete account/invitation/credential lifecycle in the browser:** existing membership controls cover only part of administration. **[major]**
30. **General OIDC-provider support:** Entra SSO exists; arbitrary enterprise identity providers are not implemented here. **[minor]**
31. **Multiple-workspace provisioning per application:** IDs scope records, but one application configuration selects one workspace. **[major for multi-team deployment]**
32. **Localization:** fixed English templates/messages, no locale interface. **[minor]**

### Operations and governance

33. **Dedicated dependency-health/readiness endpoints:** authenticated status exists, not a complete health interface. **[minor]**
34. **Operational telemetry/metrics:** no supplied workspace observability surface. **[major]**
35. **Alerting:** no supplied operational alert mechanism. **[major]**
36. **Request rate limiting:** per-item limits are not request-frequency controls. **[major]**
37. **Aggregate storage/member quotas and fair-use controls:** uploads and operational history can accumulate. **[major]**
38. **Scheduled ingestion/quality-check orchestration:** uploads require explicit refresh; live queries are not a scheduler. **[major]**
39. **Managed retention/cleanup lifecycle:** no workspace-level lifecycle for abandoned tasks, uploads and worktrees. **[major]**
40. **Complete membership-change audit history and audit explorer:** approval records exist; access-change provenance is incomplete. **[major]**
41. **Explicit row/column-level authorization or masking:** the managed authorization boundary is principally workspace/source-set access. **[major for sensitive shared data]**
42. **Full ODCS constraint execution:** for example, `unique`/`primaryKey` property flags are explicitly unsupported; declaring ODCS 3.2.0 does not mean every constraint is evaluated. A/contracts.py:110–113. **[minor relative to the stated goal]**
43. **End-to-end request bounds across profiling, validation and final MCP envelopes:** native query bounds do not cover all managed paths. **[major]**

### Things I am explicitly **not** calling missing

- **Full-body lexical search:** implemented, not merely title search.
- **SSO:** Entra is implemented.
- **Audit records:** approval records exist.
- **Versioning and rollback machinery:** native implementations exist.
- **Exports:** SDK/CLI implementations exist.
- **Metric diffs:** included in integrated review.
- **Automatic server-side distillation:** not required if Pi authors the structured candidate, as this architecture permits.

---

## AREA 7: Over-complicated

**OVER-COMPLICATED:**

| Component | Assessment and simplification |
|---|---|
| **Four browser decisions for first data publication** — W/analytics.py:735–874 | Distinct approval facts are valuable; four separately navigated approval ceremonies are not inherently necessary. Combine compatible decisions in one explicit review transaction while preserving source identity, actor authorization and publication bindings. |
| **Analytics-dependent contribution routing** — W/app.py:534–575 | Enabling a feature changes unrelated document submission semantics. Route according to the requested change, not merely whether analytics is configured. |
| **Different baseline rules across ordinary, enrichment and analytics contributions** — W/contributions.py:163–193; W/enrichment.py:165–175 | This complexity causes actual failures. Use the relevant admitted baseline consistently; do not make users reconcile hidden checkout state. |
| **Duplicated preparation logic** — W/contributions.py:195–341,647–755; W/analytics.py:876–1038 | Both validate pages, resolve uploads, collect conversion facts, digest inputs and prepare native candidates. Share the genuinely identical preparation pieces without inventing another orchestration framework. |
| **Repeated extraction of identical uploads** — W/intake.py:155–183; W/contributions.py:225–235 | Read-source and preparation reconvert the same digest-bound document. Reuse verified extraction records. |
| **Separate native/integrated review renderers** — W/review.py:837–1004 | The integrated renderer turns complete review data into JSON while the native renderer presents useful sections. Reuse the readable diff presentation and keep technical details collapsible. |
| **Repeated form parsers** — W/app.py:665–681,731–745,798–815,867–881 | Four nearly identical parsers repeat the same buffer-before-limit defect. One small bounded form parser would reduce code and fix the trust-boundary problem. |
| **Duplicated repository backup roles** — W/operations.py:130–145,212–235 | Copying one original repository into two independent restored repositories adds storage and breaks identity relationships. Record shared roots once and preserve aliases/subtrees. |
| **Status represented in multiple shapes** — W/state.py:127–142; W/analytics.py:718–874 | Durable status, response status and stage require repeated translation. Keep distinctions that affect behavior, but normalize the lifecycle representation rather than carrying competing descriptions. |
| **Duplicate published-state guard** — W/contributions.py:440–451 | Straight duplication with no extra capability. Delete one guard. |
| **Unused direct `itsdangerous` dependency** — workspace pyproject.toml:13; scripts/verify_workspace_wheel.py:45 | No workspace runtime usage was found. The verifier freezes the unnecessary dependency too. Remove the direct requirement and corresponding metadata expectation if transitive consumers do not require it explicitly. |
| **Historical implementation commentary** — notably A/query.py and K/cli.py | Many comments explain past issue moves and resolver drift rather than current invariants. Remove stale history while retaining the actual safety rationale and necessary suppressions. |
| **10,629-line CLI module** — K/cli.py | Command parsing, environment resolution and many product workflows are concentrated in one file. Consolidate repeated option/config handling and separate command bodies by existing capability—not with a new plugin framework. |
| **5,646-line knowledge module** — K/knowledge_base.py | Parsing, ontology validation, graph operations and generated artifacts share a huge module. Separate along those already-real responsibilities; do not replace explicit logic with generic abstractions. |

### Complexity that earns its keep

**Review nonces, generations and digests: KEEP.**  
They answer different questions: was this action already used, which correction generation was reviewed, and exactly which candidate/resources were approved? Concurrent browser tabs and retries make those real requirements even on one server.

**Admission pinning and `expected_revision`: KEEP.**  
Without these, reviewed state can differ from executed or published state. The restore defect is not a reason to weaken admission validation.

**XLSX defensive parsing: MOSTLY KEEP.**  
Archive bounds, stored-value handling and coordinate checks protect against silent mismeasurement and unsafe files. Also, the implementation does **not** reject all shared formulas: it specifically rejects shared-formula cells lacking explicit coordinates.

Its limitations are real: cached values only, no recalculation, strict dimension/order checks, bounded selected cells and refusal of unsupported/error values. Broad workbook compatibility remains unverified. Outward per-cell provenance can be made less repetitive without deleting validation.

**Enrichment binding/coverage checks: MOSTLY KEEP.**  
Source-version pinning and audience checks prevent mistaken provenance and disclosure. Simplify projection/presentation, not those guarantees.

**Package boundaries: LARGELY JUSTIFIED.**  
Core, wiki, optional LanceDB, server and TypeScript client have real independent runtime/dependency roles. Combining them would not fix the broken managed seams.

**Test separation: LARGELY JUSTIFIED.**  
Source tests, independently installed wheel tests and optional-adapter tests examine different boundaries. The naming/configuration is fragmented, but deleting packaging checks merely to reduce the number of suites would lose meaningful validation.

**Dead-code conclusion:** I did not establish that an entire major component can safely be deleted without losing an existing capability. “Not used by the managed server” is not the same as “unused everywhere.”

I also cannot honestly promise a 50% reduction for these modules without performing and validating a rewrite. The duplication and complexity targets above are concrete; an exact reduction percentage would be speculation.

---

## Final verdict

**OVERALL: PARTIALLY ACHIEVED**

**SUMMARY:** The data/query and knowledge foundations are substantial, and the browser approval boundary contains meaningful protections. But first and subsequent knowledge publications can fail, combined-mode authoring is unnecessarily coupled to data grants, managed retrieval omits advertised capabilities, and moved restores do not recover usable analytics admissions. This is a capable set of engines with an incomplete managed product around them.

**BIGGEST_GAP:** The autonomous knowledge contribution loop is not self-contained: fresh knowledge-only publication and subsequent ordinary document publication require intervention outside the promised agent-plus-browser workflow.

**SIMPLICITY_AUDIT:** One application worker and embedded engines are a good foundation. However, three required Python distributions, optional fourth retrieval adapter, external HTTPS, 11–17 server settings, multiple persistent filesystem roles and nine first-query actions do not support “maximally simple.”

**TOP_3_SIMPLIFICATIONS:**
1. Unify contribution routing and admitted-baseline selection.
2. Collapse compatible approval stages into one understandable browser journey.
3. Consolidate deployment/storage identity around one canonical root and preserve it correctly through restore.

**MISSING_COUNT: 43** managed capabilities or working capability gaps enumerated above.

**Disposition: hand back for fixes—not acceptance of the stated goal.**

Not checked: live Pi interoperability, production deployment, representative document fidelity, real external-source matrix or CI execution. No files changed; the verdict is source-backed, not live certification.