AREA: 1. Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Repository-relative reference keys: W=products/lumio/packages/lumio-workspace/src/lumio_workspace; C=products/ariadne/packages/ariadne-data/src/ariadne; K=products/lumio/packages/lumio-wiki/src/lumio_wiki; P=products/lumio/clients/pi-workspace; L=products/lumio/packages/lumio-lancedb/src/lumio_lancedb. Static inspection only; no execution claims. All brief-named key files exist.
Upload types are implemented (W/intake.py:17-19); operator-bound SQLite/DuckDB/PostgreSQL/S3 families reach native readers (W/analytics.py:101-126; C/sources.py:676-737). Exact source approval and actor grant precede profiling (W/analytics.py:470-500,735-775). Governed execution compiles, binds, audits grain, bounds results, and attaches context/admission (C/query.py:392-505); workspace pins the record (W/analytics.py:511-560).
GAPS: Nine main actions: upload, prepare source, approve source, grant data, profile, prepare contribution, approve submission, approve publication, query—not under five (W/analytics.py:294-469,735-857; W/app.py:606-640). Profiling samples 100 rows but has no deadline or response-byte ceiling along this path (W/analytics.py:481-486; C/profiler.py:486-518; C/execution.py:162-180). Existing connection handles need operator provisioning; refusals explain that dependency rather than resolve it (W/analytics.py:101-115). XLSX requires selected sheets and stored formula caches, never recalculates (C/spreadsheet_import.py:381-407,522-526).

AREA: 2. Knowledge pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: PDF/DOCX/text extraction delegates real converters with subprocess deadlines; agents supply authored Markdown, not automatic structured-page conversion (K/authoring_journey.py:143-235; K/source_processor.py:300-364; W/contributions.py:210-235). Candidate ingestion validates pages/ontology/bindings (K/authoring_journey.py:480-589). Enrichment selects exact admitted pages; publication activates an immutable pointer; rejection does not activate (W/enrichment.py:164-288; W/review.py:511-568; K/git_authoring.py:2274-2286).
GAPS: Empty setup commits but never publishes a baseline; knowledge review refuses without one (W/setup.py:252-331; W/review.py:208-217). Subsequent ordinary submissions start at unchanged repository HEAD, while review requires descent from current publication: publishing never advances HEAD; published tasks cannot supply continuations (W/contributions.py:169-194,673-674; W/review.py:214-215; K/authoring_review.py:1629-1632; K/git_authoring.py:2281-2286). Analytics enablement also makes ordinary document submissions require a data grant (W/app.py:554-567). Even with a baseline, PDF-to-readable publication needs upload/extract/author/review/read; originals cannot be inspected as PDF/DOCX because review decodes retained bytes as UTF-8 (W/review.py:353-363).

AREA: 3. Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE: Pi registers the MCP connection and applies model-disclosure restrictions (P/index.ts:28-134). Workspace offers lexical search and cited pages; query results distinguish governed execution (W/app.py:327-362; C/query.py:470-485).
GAPS: No managed discover/list-metrics/list-datasets/resolve-term/contracts interface: query_data dispatches only five execution operations (W/analytics.py:530-548), despite Core discovery existing (C/discovery.py:563-608). No vector/hybrid route: search_pages is called, not SDK retrieve or LanceDB semantic search (W/app.py:347-360; K/location.py:281-313; L/index.py:567-659). Reads omit entity IDs/ontology/claims frontmatter needed for enrichment discovery (W/app.py:334-343; W/enrichment.py:185-190). Pi's Entra connection cannot upload originals (P/index.ts:146-148). Connection requires explicit environment/token/model configuration; the named skill instead teaches local CLI discovery (P/index.ts:28-44; C/skill_assets/SKILL.md:8-28,59-74). Ten-minute productivity and actual Pi compatibility cannot be established statically.

AREA: 4. Collaboration
VERDICT: PARTIALLY WORKS
EVIDENCE: API/browser credential purposes differ; approvals require browser session, same-origin POST, current review capability, exact one-use binding, and separate reviewer except single-person workspaces (W/auth.py:81-97; W/app.py:707-750; W/review.py:366-425; W/state.py:568-594). Local disable/revocation is checked on subsequent requests (W/state.py:205-225,321-338).
GAPS: If an adopted publication contains restricted pages, any read member can retrieve them: workspace lookup/search applies no visibility selection, and SDK search defaults to all pages (W/app.py:306-360; K/knowledge_base.py:455-461,601-614; K/git_authoring.py:2184-2188,2236-2239). Revoking default read permission leaves contribute/review grants active; those routes do not require read (W/state.py:356-364; W/app.py:531-532,716-717). Restore clears outstanding actions/sessions, but copies admission records unchanged into a relocated project: QueryRuntime rejects their old absolute project identity; bound publications also retain old destinations (W/operations.py:186-254; C/admission.py:132-177; C/query.py:1515-1517; C/lumio_context.py:1274-1278). Review is digest-heavy, without an inbox/discussion (W/templates/review.html:12-65).

AREA: 5. Operational simplicity
VERDICT: PARTIALLY WORKS
EVIDENCE: One Uvicorn service; CLI starts HTTP while routes require HTTPS, requiring a TLS boundary; converters add transient processes (W/__main__.py:41-43,85-87; W/app.py:714-715; K/source_processor.py:310-323). SQLite operational state, embedded DuckDB, optional LanceDB, Git, plus uploads/registry/artifacts/publication filesystem roles exist (W/state.py:76-182; C/execution.py:162-180; L/index.py:593-595; W/operations.py:30-40,129-142).
GAPS: In local-token mode, five required server variables for read-only startup; full analytics adds five path/handle variables, two operator files, and authored configuration; new empty KB adds namespace (W/app.py:162-180,377-384; W/analytics.py:80-105; W/setup.py:101-102). Four Python workspace packages plus Pi; three suffice without LanceDB, whose separation is justified by optional heavy dependencies (pyproject.toml:14-19; products/lumio/packages/lumio-workspace/pyproject.toml:8-19; products/lumio/packages/lumio-lancedb/pyproject.toml:9-23). Deployment duration cannot be established statically. This is not turnkey.

MISSING:
- Restricted-page read/search filtering in adopted publications [blocker] (W/app.py:306-360; K/knowledge_base.py:601-614).
- Bounded/paginated managed page reads: full body returned instead of bounded SDK read [major] (W/app.py:334-343; K/knowledge_base.py:463-479).
- First knowledge publication bootstrap: onboarding stalls [blocker] (W/setup.py:252-331; W/review.py:208-213).
- Publication-aware ordinary authoring base: continued team authoring stalls [major] (W/contributions.py:169-194; K/authoring_review.py:1629-1632).
- Data-independent documents in analytics workspaces [major] (W/app.py:554-567).
- Managed metric/dataset/term/contract discovery [major] (W/analytics.py:530-548).
- Managed vector/hybrid retrieval [major] (W/app.py:347-360).
- Entity-ID/graph/ontology discovery for enrichment [major] (W/app.py:334-360).
- Pi Entra original upload [major] (P/index.ts:146-148).
- Data grants for read-only consumers: task creation requires contribute, grants remain actor-scoped [major] (W/app.py:437-449; W/analytics.py:164-195).
- Profiling deadlines/output ceilings [major] (C/profiler.py:486-518).
- Binary-original browser preview [major] (W/review.py:353-363).
- Relocatable admitted analytics restore [blocker] (W/operations.py:210-254; C/query.py:1515-1517).
- One-action complete membership revocation [major] (W/state.py:356-364).
- Review inbox/task listing [major] (W/app.py:584-604,706-750).
- Reviewer notifications [major] (W/app.py:706-750).
- Review comments/change-request explanations [major] (W/app.py:734-747).
- Multiple workspaces per service [major] (W/app.py:141-155,276-304).
- Browser user/credential creation and recovery [minor] (W/__main__.py:53-83; W/app.py:776-894).
- Monitoring/metrics/alerting interface: only authenticated ready responses exist [major] (W/app.py:316-324,907-928).
- Rate limits/aggregate storage quotas [major] (W/app.py:606-640; W/intake.py:66-74).
- Managed version-history/rollback interface; native rollback exists [major] (W/app.py:316-928; K/git_authoring.py:2868-2925).
- Managed export; native graph export exists [minor] (W/app.py:316-928; K/cli.py:5649-5669).
- Human charts/data exploration [minor] (W/templates/review.html:9-65).
- Scheduled refresh/revalidation [major] (W/__main__.py:85-119; W/app.py:316-928).
- HTTP API schema: custom routes excluded [minor] (W/app.py:606,642,706).
- Turnkey non-Pi client packages; generic MCP remains available [minor] (P/package.json:1-9; W/app.py:919-928).
- Localized review UI [minor] (W/templates/review.html:2-65).

OVER-COMPLICATED:
- Duplicate candidate preparation/recovery: share existing page validation and native transaction plumbing, not two orchestration paths (W/analytics.py:50-70,876-1038; W/contributions.py:76-112,647-756).
- Separate submission/publication clicks: validate before presenting one final bound approval; preserve distinct source-access permissions (W/analytics.py:735-857).
- Absolute paths across multiple private roots: use one data-root layout and portable descriptors, avoiding incomplete restore rebasing (W/operations.py:30-40,210-254).
- XLSX declared-dimension equality rejects otherwise usable worksheets; trust bounded actual coordinates while retaining ZIP, order, formula-cache and timeout safeguards (C/spreadsheet_import.py:225-325,381-407,698-765).
- Enrichment repeats identical status guards; remove duplication, retain audience/source-version binding checks (W/contributions.py:445-452; W/enrichment.py:164-246).
- Coordination/member/wheel verification entrypoints need one driver, not flattened package boundaries (pyproject.toml:46-61; .github/workflows/lumio-lancedb-wheel.yml:17-46).
- Nonces/generations and admission pinning earn their complexity: they prevent replay and mixed-revision authority; do not delete them (W/state.py:568-594; C/admission.py:1325-1398).

OVERALL: PARTIALLY ACHIEVED
SUMMARY: Static inspection finds real governed-query and human-approval machinery, but not a complete managed platform. Restricted-content filtering, knowledge publication lifecycle, and relocated analytics restore have concrete code-path gaps (W/app.py:306-360; W/review.py:208-217; W/contributions.py:169-194; C/query.py:1515-1517).
BIGGEST_GAP: Read/search exposes restricted pages to ordinary read members when such pages exist in an adopted publication (W/app.py:306-360; K/knowledge_base.py:455-461,601-614).
SIMPLICITY_AUDIT: Not maximally simple: one service plus HTTPS termination; SQLite, DuckDB, optional LanceDB, Git, and at least four additional filesystem roles; four Python packages plus Pi (W/__main__.py:85-87; W/operations.py:30-40; pyproject.toml:14-19).
TOP_3_SIMPLIFICATIONS: Unify candidate transaction plumbing; collapse submission/publication review; replace scattered absolute paths with one portable data-root layout (W/analytics.py:735-857,876-1038; W/operations.py:210-254).
MISSING_COUNT: 28
