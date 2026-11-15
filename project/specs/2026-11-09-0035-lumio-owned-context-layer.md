# Specification 0035: Lumio-owned Context Layer for every Ariadne project

**Status:** owner-approved behavioral specification, written revision 2. Approved 2026-11-10.
Original date: 2026-11-09; audit amendment: 2026-11-10. Approval authorizes this documentation and read-only review of R0–R5 / #102–107, not implementation, an implementation plan, tracker mutation, commits, integration, publication or changes to real projects.

**Approval source:** In this Pi conversation the owner required Ariadne to always use lumio-wiki while Lumio remains independent, then stated “Wir benötigen keine Backward Compatibility!” The owner selected “Neu aufsetzen”, “Behalten über Lumio” for Answer Examples, “Normale Lumio-Seiten” for guides and “Gültige Seitenpakete” for drafts. The owner then selected “Zielbild freigeben (Recommended)” for the complete architecture/onboarding/review/removal/verification proposal, explicitly including refusal on missing required Context before calculation. That last choice requested ADR/spec capture and presentation for written review, not implementation.

**Revision 2 approval source:** After the audit comparison, the owner stated: “Ok. ARD-0029 behalten wir und passen die Spec0035 gezielt an. Überprüfe auch noch einmal die Tasks R0-R5 bzw. Issues #102-#107, ob diese eventuell auch noch gezielt angepasst werden müssten.” This authorizes the five targeted clarifications below and ticket inspection. It retains ADR-0029 unchanged and does not approve changes to the published tickets or broaden the standalone R-track into all Ariadne implementation work.

**Written approval:** On 2026-11-10, after presentation of revision 2 and the R0–R5 review, the owner stated “Spec is freigegeben.” This approves the complete written spec0035 revision 2, including AC1–AC15. It does not authorize implementation planning, edits to spec0034/its plan or GitHub tickets, implementation, commits or publication; the proposed R-track reconciliation remains a separate action.

**Subsequent planning request:** On 2026-11-10 the owner stated “Erstelle den plan”, separately authorizing creation of the [proposed implementation plan, revision 1](../plans/2026-11-09-0035-lumio-owned-context-layer.md). This does not approve that plan, amend R-track sources/tickets or authorize implementation. The behavioral specification remains approved revision 2.

**Subsequent plan/ticket approval — 2026-11-10:** “Passt! erstelle die Tickets bzw. passe die bestehenden an” approves plan0035 revision 1 and authorizes C-task ticketization plus the named R1/R2/R4/R5 source/ticket reconciliation. Spec0034 revision 6 and its plan amendment revision 2 record those scoped deltas. This supersedes only the earlier action restrictions on planning/source reconciliation/tracker publication, not the prohibition on implementation, live access, Git commit/push or release. Spec0035 behavior and AC1–AC15 remain approved revision 2; ADR-0029 is unchanged.

**Sources:** [ADR-0029](../adr/0029-lumio-owned-context-layer.md), [source inspection and audit comparison](../research/2026-11-09-lumio-only-context-layer.md), [spec0034 revision 5 §12](2026-11-04-0034-agent-first-shared-workspaces.md#12-curated-wiki-retrieval-and-original-references-proposed-revision-5), [Ariadne vocabulary](../../products/ariadne/CONTEXT.md), [Lumio vocabulary](../../products/lumio/CONTEXT.md).
Planning-contract v1; installed skill provenance unknown.

## 1. Scope and ownership

Replace Ariadne's optional Lumio integration plus independent Context Layer implementation with one mandatory `lumio-wiki` foundation. Keep the two product areas and package/release identities. A base Ariadne installation brings a compatible Lumio SDK; installing or using Lumio does not bring or require Ariadne.

| Lumio owns | Ariadne owns |
| --- | --- |
| Knowledge Base, Compiled Page representation, structural/cross-page validation, page mutations, provenance infrastructure, retrieval, knowledge versioning and publication | Source declarations/access/approval, profiling and Schema Observations, OSI, ODCS and Contract Bindings/Observations, semantic validation, numerical execution, analytical evidence and overall analytics admission |

Ariadne-authored technical facts and curated business explanations inhabit the same Lumio Knowledge Base. Core may retain technical content builders and analytics-specific checks; it must not retain a parallel generic parser, bundle store, navigation index, page-maintenance or document-ingestion implementation. No Ariadne/DuckDB/SQLGlot dependency is introduced into Lumio. Native knowledge metadata is consumed through Lumio's public SDK, not a generic OKF export/import round-trip or maintained mirror.

This does not require the private Lumio application, a workspace server, LanceDB, S3, MCP or a model provider. Optional capabilities remain optional unless the selected operation actually needs them. Source authorization, visibility and human admission never follow merely from package installation.

### Non-goals

No backward compatibility with the retired Ariadne Context path, no automatic content migration, no new query engine, connectors, UI redesign, hosting/authentication design, retrieval backend or general Policy execution language. The narrow original-download repair below is not a document previewer; supported-format recovery is not legacy migration. No changes to existing external project data, credentials or releases. Installed agent skills remain distinct from knowledge-page guides.

## 2. One content and authoring path

New Ariadne projects initialize one Lumio Knowledge Base under the established `knowledge/` subtree and the required Ariadne profile/bindings. OSI, contracts and physical source declarations remain Core artifacts in the same jointly reviewed Content Repository. Knowledge can exist before the first semantic model or metric. Local use does not require deployment of a service; managed workspaces compose the same native operations.

There is no optional switch back to `context_layer/`. Configuration identifies the intended KB, publication destination and profile; it is not a choice between two Context implementations. Explicit namespace/location selection, nonempty-target protection and existing source-retention requirements still apply. Setup does not adopt or overwrite an existing unrelated KB implicitly.

All durable Context page edits, including generated technical-page updates, use Lumio's public authoring lifecycle. Core continues coordinating its analytics candidate revision and joint Git review rather than introducing another knowledge proposal store. Page updates and Core candidate bookkeeping must agree on the resulting revision; stale revisions refuse rather than overwrite concurrent work.

**First and subsequent publication:** An empty new project can prepare, review and publish its first knowledge contribution without externally seeded content or automatic blank publication. Ordinary subsequent contributions derive from the actual admitted publication, not a stale repository HEAD; they remain reviewable and publishable without manual ancestry repair. Preserve exact candidate review, stale-action refusal and native receipt reconciliation. A first knowledge publication does not invent an analytics model or activate a Bound Release.

**Structurally valid batches:** Validate the complete resulting knowledge candidate before accepting a batch. Cross-linked new pages may be submitted together; no arbitrary write ordering should require dangling intermediate pages. Invalid metadata, broken required internal references or manifest/profile violations reject the batch without accepting a partial page set. Use existing Lumio mutation/recovery guarantees, not a new transaction service.

A structurally valid draft can explicitly record unknown business meaning, hypotheses or pending verification. It is not admitted or eligible to satisfy required runtime Context merely because it was saved. Semantic and authorized live-data checks remain separate from knowledge structure checks; storing a knowledge draft neither opens a data source nor proves its correctness. OSI draft handling is not tightened into knowledge-page validation by accident.

**Knowledge-only contributions:** Enabling analytics does not by itself require an analytics source-task grant for an ordinary document, guide or saved Example contribution. Apply the permissions and source-evidence requirements of the actual operation. A knowledge-only contribution neither opens analytical data nor changes executable artifacts or the active analytics association. Data access and executable changes retain their applicable grants, validation and whole-candidate review; routing cannot hide Core edits inside a knowledge-only request. Publishing changed knowledge, including a Policy page, does not repin existing Ariadne queries. Integrated original retention remains required even for knowledge-only work.

## 3. Dataset and document onboarding

### Physical data source, including an Iceberg table on S3

1. Identify the requested physical source and its effective storage identity. Obtain Source Approval through the existing operator boundary before profiling or reading data.
2. Ariadne measures the selected source using existing supported access paths. No new Iceberg connector or implicit broad source scan is part of this change.
3. Ariadne supplies Dataset Overview/Table content and identified schema/profile evidence to Lumio's page operations. Preserve observed scope, time, source bindings and evidence limitations. Reuse the existing native Table/Dataset profiles rather than copying classic bundle pages.
4. The authoring agent combines measured facts with existing source-backed knowledge and targeted owner clarification. Names/statistics alone do not establish business rules, identifier equivalence or approved joins. Unresolved meaning remains explicit in the draft.
5. Propose OSI definitions, contracts and bindings where needed. A producer-owned ODCS contract is not automatically inferred truth or mandatory merely because a table was onboarded. A data-only Context candidate can be reviewed without inventing a metric or a Policy.
6. Review the combined knowledge/analytics changes and admit the exact validated candidate through the existing human boundary. Refresh is an explicit new candidate operation, not automatic publication.

Refresh preserves curated text and column meaning for unchanged identities/types, and makes removed/changed schema meaning visible for review. An unchanged refresh remains a no-op. Source permission changes, collisions and invalid evidence refuse rather than silently overwrite or relabel content.

### Documents and business meaning

Use Lumio's document intake, source binding, conversion and knowledge authoring operations. Retire Ariadne's parallel converter/distiller/reconciliation path. Preserve applicable original retention, provenance, verbatim handling and human-review requirements through the native workflow, not a compatibility-only `ariadne-ingest` implementation.

**Inspectable binary originals:** In managed workspaces, for supported PDF/DOCX intake, a separately authorized human can obtain the exact retained original during pending-candidate review and from an admitted page reference after publication. Pending inspection resolves the candidate's binding through its review boundary; published inspection resolves the selected publication's binding. Do not make pending content available through ordinary published-page retrieval. Use verified bytes delivered as a safe browser attachment, not UTF-8 decoding of binary originals, active inline rendering or model-visible bearer URLs. Check current `inspect_source` permission before private metadata/store access; ordinary read or review permission alone is insufficient. Missing/corrupt bytes refuse honestly rather than substituting extracted text or a newer source. Reuse native resolution and the spec0034 original-reference work; no previewer or raw-passage highlighting is required.

Ariadne Seed Notes remain an authoring input where used; they do not create a second served Policy/terminology catalog. Admitted business knowledge is maintained in the KB. No new mirrored dictionary is introduced.

**Native preservation and inspection disposition (2026-11-11, owner-approved):** the owner selected “Scoped SDK repair (Recommended)” and then “Approve contract (Recommended)” for this bounded C3 repair. Native intake must offer explicit verbatim preservation independently of Source lifecycle intent (`new`/`update`); it must not restore Core's retired ingestion workflow. The producer-owned API extension is captured in [Lumio spec0010 §3.1](../../products/lumio/project/specs/2026-10-23-0010-external-agent-authoring-journey.md#31-explicit-verbatim-preservation-scoped-amendment-2026-11-11).

- A selected verbatim document produces one complete page, and existing multi-document candidates remain supported. Preserve the exact converted body, including its newline form, leading/trailing blank lines and literal `<!-- lumio: page-break -->` text (including fenced examples). Do not split, trim, inject summaries into, or interpret that body as authoring instructions. Managed metadata and native routing/identity/ontology/Claim validation still apply; no private-original download or retention guarantee is replaced by a page-body claim.
- Managed preparation compares the authored body with the actual complete native extraction record before constructing the request. Incomplete extraction, body mismatch, missing or ambiguous document/page binding refuses without a partial authored candidate. An expected text digest is a caller expectation checked against bytes, not authentication of conversion provenance. Existing distilled behavior and Source intents remain unchanged by default; the host agent remains the default Distiller, with no mandatory model service.
- On the newly enabled integrated native review route, current separate `inspect_source` permission precedes inspection-specific original availability probing and private registry metadata lookup. A review-only member sees one static authorization-required state, independent of original presence, with no availability-conditioned link or label; authored attribution and reviewed manifest bindings remain reviewable. Inspectors retain the existing exact-binding/verified-byte path. Required-retention admission and publication validation remains mandatory and independent of optional inspection rendering; no broad exception swallowing or alternate download path is added.

Capture checkpoint: planning-contract v1, installed provenance unknown. Existing verbatim/distilled, Source Version, candidate and inspection terms suffice; this additive optional producer seam implements the already approved preservation/permission behavior without a new store, authority model or independent workflow, so no new glossary or separate ADR is warranted. Capture precedes one scoped C3 repair and one delta recheck; publication, target integration, release and live qualification remain separately gated.

## 4. Answer Examples and operational guides

**Answer Examples remain a supported user action.** After an explicit save request, a question, intended meaning, reusable query method, source/definition references and bounded historical answer/provenance can be proposed as a Lumio Compiled Page. Retain the applicable semantics of [Ariadne spec0007](../../products/ariadne/project/specs/2026-09-29-0007-answer-examples.md), replacing its separate store/reader with Lumio. Preserve the distinction between submitted SQL provenance and authenticated execution evidence.

Example retrieval uses Lumio's knowledge retrieval and respects the selected version and visibility scope. An example can guide a new query, but its historical value is never the current answer, its method never bypasses the compile/governance gates, and saving it never creates an admitted metric. Do not leave the operation permanently refused because the old integrated capability table excluded it. Use producer-owned structured metadata where necessary, not a parallel example index or Core parser of KB bytes.

Operational instructions such as “How to query Trace Data” are ordinary Lumio pages. They are searchable/readable without a dedicated Ariadne Skill-profile execution path and grant no additional permissions. The Lumio SDK need not remove generic capabilities used independently by other consumers; Ariadne simply does not require a special Skill profile for these guides.

### Native Context discovery and scope

The supported CLI/MCP Context operations must let a caller discover and read the pages needed for the advertised journey, including guides and Answer Examples, and obtain canonical title, stable Entity ID and exact knowledge revision where needed to target an edit/enrichment. The caller must not need private filesystem access or hidden frontmatter to obtain the identifiers a public operation requires. Consume producer-owned metadata through the public SDK; do not add a parallel catalog. Metric, dataset and contract discovery remain Ariadne responsibilities; this does not require exposing every Core tool, admin action or graph capability through the workspace.

Apply the authorized Visibility Scope before lookup, matching, ranking, counts or snippets on every supported read/search/reference path. Hidden titles, aliases and IDs are indistinguishable from absent ones. Managed shared-audience rules remain those of spec0034; integrated Context remains bound to its exact Bound Release and operator scope. The new standalone `retrieve_knowledge` tool from spec0034 continues to refuse integrated workspaces; it is not a substitute for native pinned Context discovery. Mandatory SDK use introduces neither a moving-latest fallback nor mandatory MCP/LanceDB.

## 5. Review, admission and query failures

Retain joint review of the whole submitted content revision. Show actual executable changes as well as meaningful knowledge/source/visibility changes; a page-body approval cannot hide an OSI change. A structurally valid page batch, a Git commit, or a Lumio publication alone is not overall Ariadne admission.

Reuse native Lumio publication and Core's final activation of the exact Bound Release. Preserve binding to the actual knowledge, analytics, evidence and build/execution identities, source grants and authorized Visibility Scope. Readers use this association, not an independently advancing latest-KB pointer. Failure after publication but before Core activation leaves the prior active release unchanged and discloses any completed standalone publication through the existing recovery contract.

Before executing a query, verify its required Context dependencies under that admitted association. Missing, invalid, mismatched or out-of-scope required Context, including required Policy Closure, causes refusal **before SQL**. Never execute with only an advisory warning, read the retired directory, or select newer unadmitted knowledge as fallback.

Dependencies are explicit and operation-scoped. Do not manufacture a Policy for every metric, treat every provenance/navigation link as a Policy dependency, or block a query because unrelated drafts are present in a working copy. Existing multi-fact and other semantic requirements for governing Policies remain binding; move their proof to native knowledge references instead of deleting it. A draft missing a required dependency cannot become the replacement active release, but does not invalidate the prior admitted release simply by existing.

Ad-hoc results remain ungoverned and governed results remain subject to their existing compile/grain/join checks. Using admitted input Context does not admit an ad-hoc definition. Freshness, document verification, human admission, per-run execution proof and independent numerical validation retain their distinct meanings.

### Recovery of supported projects

For managed workspaces hosting newly created projects using this contract, backup/fresh-root restore must preserve the shared identity of the knowledge/analytics Content Repository rather than materializing two independently advancing copies. Reuse the existing managed backup/recovery boundary, including retained originals and private publication records. Rebase mutable configuration/worktree links only; historical admissions and snapshots are not rewritten to impersonate approval of another destination or source.

Readable restored content is not proof of write/query readiness. Report the owner confirmation, source reauthorization and native revalidation/admission still required by changed identities; deny dependent writes/SQL until those prerequisites are satisfied. After those explicit steps, a fresh contribution can be reviewed/published and a valid analytics query uses an exact newly authorized association. Preserve historical evidence, current scope checks and invalidation of old sessions/actions. This is supported-format recovery, not transfer of legacy approvals or an automatic content migrator. Standalone original recovery in spec0034 is a reusable prerequisite, not proof of this integrated outcome.

## 6. Breaking cutover and removal

The new release supports the new contract only. Do not carry compatibility aliases, old integration-mode branches, legacy support-revision readers or dual writes solely to keep retired Ariadne projects running. Detect unsupported old project/admission formats and explain that fresh setup/re-onboarding is required; do not silently activate or convert them.

No migrator or reset command is part of this work. Existing project files, original documents, private source stores and historical admitted snapshots remain untouched. Necessary content is deliberately re-onboarded into a separately selected new project and reviewed/admitted afresh; old approvals are not transferable to new bytes.

Update repository examples, fixtures, skills and user-facing CLI/MCP/setup documentation to demonstrate only the new path. Retire code/tests whose sole purpose is the removed standalone Context mode. Preserve numerical, source-permission, provenance, visibility, revision and admission coverage by redirecting it to the new path rather than deleting its invariants.

In particular, remove classic bundle finalization/index generation, duplicate document intake, old page editing/search and the requirement for `context_layer/metrics`/Policy pages. Move the necessary Computation and graph-Policy checks to Lumio-native content. Do not delete `context.py` wholesale: its technical evidence/mapping logic still has a job in Core.

## 7. Acceptance examples and validation scope

These are required outcomes for the future implementation, not tests run during design. Reuse existing focused checks where they prove the new behavior; add a test only for an uncovered scenario. No broad suite or live fixture access is authorized here.

| ID | Scenario and expected outcome |
| --- | --- |
| AC1 | Installing the built Ariadne base wheel in isolation installs compatible lumio-wiki. Installing the Lumio base wheel alone neither installs nor imports Ariadne. Neither base journey requires the private app, service, LanceDB, S3 or MCP. |
| AC2 | Fresh local setup followed by explicit approval and onboarding of a supported table produces native Dataset/Table pages in one KB, with no `context_layer/` mirror and no invented metric/Policy. Context can be reviewed before any metric exists. |
| AC3 | An unapproved source cannot be opened by onboarding/refresh. A granted source refresh preserves curated text and evidence binding; identical input is a no-op; changed source identity requires the existing grant checks. |
| AC4 | A batch of mutually linked valid pages is accepted together as a draft. A batch with a required dangling reference or invalid metadata is rejected without accepting a partial page set. Neither outcome publishes or admits analytics automatically. |
| AC5 | Document onboarding uses Lumio's native intake, retains the applicable original/source evidence and supports the selected verbatim/distilled intent without a second Ariadne ingest store. |
| AC6 | Joint admission binds the exact knowledge and analytics revision. Advancing standalone knowledge publication does not change an active Ariadne answer's Context. A failed final activation leaves the previous active association in place and reports the actual publication outcome. |
| AC7 | Removing or mismatching a query's required Policy/Context causes refusal before SQL. A metric without a Policy requirement needs no invented Policy; unrelated working-copy drafts do not block a valid admitted query. Existing graph-Policy and numerical checks still execute. |
| AC8 | An explicitly saved Answer Example becomes reviewable Lumio knowledge and is retrievable after admission under the authorized scope. Reusing it performs a fresh sanctioned query instead of returning the saved number or executing historical SQL directly. |
| AC9 | A normal instructional page is searchable/readable without an Ariadne Skill profile. Its text grants neither source access nor additional calculation authority. |
| AC10 | Opening an unsupported legacy project/admission refuses with fresh-setup guidance and does not alter its files or snapshots. Current repository examples and CLI/MCP documentation use the single new path. |
| AC11 | From empty setup, the first knowledge contribution is published only after explicit human approval. A second ordinary contribution starts from the actual admitted baseline and can also be reviewed/published without manual Git repair. No blank auto-publication, metric or Bound Release is invented. |
| AC12 | With analytics configured, a knowledge contributor without an unrelated analytics data grant can submit an ordinary guide or document for review/publication by an authorized human. No analytical source is opened or active Bound Release changed. Adding data access or executable edits cannot use this route to bypass their grants/validation; integrated retention remains required. |
| AC13 | In a managed workspace, a supported binary original is inspectable as exact verified bytes both during candidate review and after publication, under current separate inspection permission and the respective exact binding. A plain reader/reviewer cannot probe private availability or bytes. The published-reference path cannot expose pending content; corrupt/missing originals never substitute extracted text or latest. |
| AC14 | Through the supported Context CLI/MCP surface, a caller discovers an admitted guide/Example and obtains the stable Entity ID and revision needed by the supported follow-up operation without reading private files. Hidden page titles/aliases/IDs, text and counts do not leak. Advancing standalone publication cannot change the pinned integrated view; the standalone Evidence tool still refuses integrated use. |
| AC15 | A new-format managed integrated project's fresh-root restore preserves one shared authoring/analytics repository and unchanged historical admissions. Before required owner confirmation/revalidation, dependent writes/queries refuse with actionable prerequisites. After the required native approvals, a new contribution publishes and a valid query uses its exact authorized knowledge/analytics association. Reading old pages alone does not satisfy this outcome. |

Existing integration navigation/profile/release checks and isolated wheel verifiers are the starting evidence, not a requirement to build a new test framework. An Iceberg example must not be claimed live-verified from a different local table fixture; later validation scope must name the actual source format/environment.

## 8. Reconciliation and handoff

[ADR-0029](../adr/0029-lumio-owned-context-layer.md) owns the architecture. This specification owns the new behavior and supersedes conflicting scoped statements in the following sources, not their unrelated requirements or historical approvals:

- Shared specs0030/0031: symmetric package independence and the separate standalone-Core integration entry path. Product layout, version families and independent Lumio remain.
- Ariadne specs0009/0010/0027: independent Core Context storage/management and invalid knowledge-page edit persistence. Core Git orchestration, source access and technical evidence safeguards remain.
- Ariadne spec0007/ADR-0015: separate Answer Example persistence/retrieval; explicit consent, meaning and provenance requirements remain.
- Ariadne specs0029/0032/0033: optional consumer selection, classic fallback, legacy compatibility tables, permanently unsupported Answer Example operations and parallel Context validation. Exact identity, visibility, native producer contracts and admission guarantees remain.
- Lumio spec0009: optionality on the Ariadne consumer side only. Lumio's independence, producer metadata ownership and native publication rules remain.
- Shared spec0034 and its Ariadne managed-data plan: all Ariadne data journeys use the mandatory KB path. Hosting, identity, curated retrieval, source-retention decisions and Lumio-only journeys are unchanged. This does not extend document-only retention exceptions to analytics.

### Coordination with R0–R5, not a second implementation plan

The live [R0–R5 issues #102–107](../plans/2026-11-04-0034-agent-first-shared-workspaces.md#curated-wiki-retrieval-and-source-storage-amendment-proposed) were inspected on 2026-11-10. All were OPEN, with no comments and no later issue update than 2026-11-09. Their approved sources remain spec0034 r5 and its frozen issue snapshots; this revision does not silently amend those tasks.

- R0/#102 already includes the actual admitted base for the second contribution. Reuse that work for AC11; do not create a duplicate bootstrap repair.
- R1/#103 already owns shared-scope filtering and version-qualified Evidence. Clarify stable Entity IDs on existing read/search responses where public follow-up operations require them; preserve standalone-tool refusal in integrated mode. Ariadne's pinned Context discovery remains owned here, not a wholesale expansion of R1.
- R2/#104 already owns exact byte attachments after publication. Its pending-review preservation wording needs an explicit binary-original outcome to cover AC13; scope that small repair without adding a previewer or exposing pending candidates via the published route.
- R3/#105 retains its standalone-only retention exception unchanged. Knowledge-only routing under AC12 must not inherit that exception merely because it avoids an unrelated data grant.
- R4/#106 already preserves immutable identities and calls for native revalidation when targets change. Its recovery proof should extend to the next standalone reviewed publication. Shared-repository/integrated query recovery under AC15 remains this specification's responsibility, coordinated at the same operations boundary rather than implemented twice.
- R5/#107 already covers a v2 contribution and historical-original reads after restore. After the corresponding source/task amendments are approved, extend that same bounded journey to binary pending-review inspection and a post-restore publication; do not turn R5 into the complete spec0035 verification suite or add repeated live runs.

The owner subsequently approved these targeted ticket/source clarifications with “Passt! erstelle die Tickets bzw. passe die bestehenden an”. Spec0034 revision 6 and plan amendment revision 2 reconcile the affected text; ticketization publishes the exact amendment alongside, rather than overwriting, earlier frozen snapshots. Keep unaffected R-track requirements and validation budgets; add or alter a check only for a named uncovered scenario. AC12 and integrated AC14/15 need their own mapping when the separate spec0035 implementation plan is authorized.

### Source-boundary disposition: PostgreSQL effective destination (2026-11-10)

The pre-existing finding “a PostgreSQL destination change under the same `connection_env` name is mistaken for harmless secret rotation” is dispositioned by owner decision (2026-11-10, “Ohne Dependency”) as a narrow repair against the existing spec0025 §4 contract, without a new connector, dependency or approval store:

- Offline source proposals stay inert: a proposal reads no environment values, and the declaration digest keeps binding variable NAMES only.
- Approval and grants key the CURRENT effective non-secret destination: the resolved target (explicit connstring components in conninfo order plus PG destination-environment defaults for omitted components, including `PGHOSTADDR` and ordered multi-host lists, with libpq defaults for port/dbname/user) is recorded under collision-free `postgres:<source-name>` binding keys. Password/sslpassword values never enter any record, message or page; credential rotation at the same destination needs no new approval.
- File-based target indirection (`service=`/`PGSERVICE`) refuses at approval with actionable explicit-target guidance instead of guessing the file-resolved destination — an owner-approved narrowing of one previously pass-through form.
- The approved binding freezes through the builder: the ONE captured connection string is verified against the frozen destination and attached — no check-A/open-B window. Transport-only environment values (e.g. `PGSSLMODE`) sit outside the target identity as a stated limit.
- Destination-unbound legacy PostgreSQL approvals/validation evidence refuse through the existing explicit messages and need fresh human approval/revalidation; historical records are never rewritten, and file/S3 grants, keys and digests are unchanged.

The pre-approval XLSX conversion finding is addressed by the separately reviewed source-boundary repair. The profiling policy is dispositioned below; its implementation and qualification remain pending.

### Source-boundary disposition: authoring profiling limits (2026-11-11)

Owner approval: “Use 1. as default, yet make it configurable”, followed by “Raise or lower (Recommended)”. This bounded amendment defines profiling-owned policy for agent-accessible `inputs` and schema refresh; it does not import Query policy or change mapping inspection's existing tighten-only rules.

- A separate **host-owned** `ariadne.yaml` `profiling:` section controls `execution_seconds` (default **20**), `sample_rows` (default **1,000**) and `response_bytes` (default **65,536**, 64 KiB). The operator may raise or lower finite positive ceilings. Rows/bytes are positive integers; booleans, non-finite/zero/negative values and unknown settings refuse actionably before source access. A candidate's committed settings are inert, never authority to widen host policy; agent requests cannot exceed the current host ceilings. Existing `inspection:` behavior is unchanged.
- The execution budget spans approved connection/catalog setup and all profiling statements across the operation, including sampling, statistics and FK inspection. Existing Source Approval remains before physical source access. Expiry explicitly refuses/inconcludes; no partial measurement or generated facts are presented or persisted as complete.
- The row ceiling applies to an **explicit requested per-table sample**, not to the input population of full statistics or numerical queries. Omitting `sample_rows` keeps full profiling under the time/payload bounds. Sampled profiles retain `sampled`/`sample_limit` and existing PK/FK limitations; fitting full-mode counts and metadata keep their existing meaning. No silent clamping or full-as-sampled substitution.
- The byte ceiling covers the **complete serialized profile value**, using its actual existing JSON/UTF-8 representation and escaping. Other document/Seed Notes evidence retains its own bounded-part contract; this is not a new Query or MCP-envelope limit. Guard variable-size statistics before unrestricted Python transfer and account incrementally rather than collecting an unrestricted profile only to measure its size. Oversize or unsupported bounded materialization explicitly refuses with narrowing guidance, without clipping values, omitting required fields, or calling a prefix complete.
- Observable acceptance: ordinary fitting full/sampled profiles retain independently known values; expired budget yields no successful/partial profile or refresh writes; an explicit sample above the host ceiling refuses before opening; oversized profile data refuses without a success payload; valid operator raise/lower takes effect while candidate/model widening does not. Use one focused public-caller regression with independent tiny fixtures and the existing deterministic deadline seam, plus an existing check only for an actually changed seam. The trusted standalone operator profiler CLI is not silently assigned a different contract.

Capture checkpoint (planning-contract v1; installed provenance unknown): existing profiling, Schema Observation, Source Approval and host-configuration terms suffice; no glossary or ADR change is warranted for this bounded operation-policy extension. No new connector, dependency, numerical population limit, or source/admission authority is introduced. Implementation remains isolated under the current execution grant; no target integration, publication or live qualification is granted.

The audit's PostgreSQL effective-destination binding and pre-approval XLSX/profile-bound concerns are not fixed by this dependency change or claimed resolved here. Before claiming AC3 on an affected source path, disposition its concrete source-authorization gap against the existing data contract. Do not add generic connector or profiler rewrites to R0–R5.

Approved earlier task executions remain historical evidence, not authorization for this breaking follow-up. Existing tickets/plans that depend on the superseded contract need reconciliation before new dependent work; no GitHub updates or execution grants are made here.

Capture checkpoint: existing domain terms suffice, with Context Layer/Bundle/Policy/Answer Example definitions reconciled in Ariadne's glossary and the relationship linked from the context map. ADR-0029 records the architectural trade-off and remains unchanged. Revision 2 adds explicit first/next publication, operation-scoped knowledge-only authorization, native scoped discovery, binary inspection and supported-format recovery outcomes. No new vocabulary or ADR is needed. Written revision 2 is owner-approved. Plan writing was separately authorized with “Erstelle den plan”; plan revision 1 and targeted R-track reconciliation/ticketization are now approved with “Passt! erstelle die Tickets bzw. passe die bestehenden an”. Execution authority remains outstanding. The plan maps these acceptance criteria to owned changes and public SDK contracts without changing this specification's behavior. No implementation is authorized by this document.
