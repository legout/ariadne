Static inspection only; no tests or services run. References: W = products/lumio/packages/lumio-workspace/src/lumio_workspace/, K = products/lumio/packages/lumio-wiki/src/lumio_wiki/, A = products/ariadne/packages/ariadne-data/src/ariadne/, L = products/lumio/packages/lumio-lancedb/src/lumio_lancedb/, P = products/lumio/clients/pi-workspace/. All key brief paths exist. Absence claims below concern the inspected workspace surface, not every conceivable external integration.

AREA: 1 Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Uploads are bounded and retained (W/intake.py:17-19,66-74,100-122); operator-bound sources and selected XLSX sheets can be staged (W/analytics.py:198-292,314-359). Human source approval and a separate caller grant precede profiling (W/analytics.py:170-196,470-486,735-775). Query opens a pinned admission and dispatches to Core's governed queries (W/analytics.py:511-559); Core plans, audits and binds SQL (A/query.py:978-1011). Records/ad-hoc definitions are explicitly ungoverned (A/query.py:1157-1171,1375-1392).
GAPS: The route involves upload, source preparation, two browser approvals, profiling, candidate preparation, submission review, validation and publication, then query (W/analytics.py:314-359,470-486,735-830,849-873,946-964): not fewer than five steps. Errors include actionable remedies (A/spreadsheet_import.py:381-387), but source-set grants are not table-level isolation (W/analytics.py:170-196,511-543). The workspace lacks native schema-refresh, evidence and metric-discovery tools despite Core implementing them (W/app.py:436-491,517-567; A/authoring.py:339-363,2190-2246). A complete live path cannot be verified statically.

AREA: 2 Knowledge pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Text/PDF/DOCX extraction returns text and sections, not authored pages (W/intake.py:152-183). Agents supply complete Markdown pages and source references (W/contributions.py:196-235); native ingest validates the complete candidate and source bindings (K/authoring_journey.py:480-529,557-583). Enrichment selects admitted pages and source metadata (W/enrichment.py:164-197,199-253). Review displays body diffs and claims (W/review.py:937-954); rejection is distinct from publishing (W/review.py:366-414). Published snapshots verify file digests (K/location.py:499-545).
GAPS: PDF-to-search requires upload, extraction, agent-authored pages, candidate preparation and browser review/publication; structured pages are not automatically produced by the service. Lexical discovery exists (W/app.py:346-361); semantic conflict detection does not: the UI explicitly warns exact matches are insufficient (W/review.py:750-755). Technical IDs, digests and JSON in review make nontechnical usability doubtful (W/templates/review.html:12-25; W/review.py:879-885); actual usability and immediate live read-after-publication are unverified.

AREA: 3 Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE: Pi registers an HTTP MCP server when configured, with local-token or Entra auth and client-side model disclosure guards (P/index.ts:28-82,119-136). Workspace exposes lexical search, contributions and pinned query (W/app.py:326-361,436-491,517-567). The SDK has separate BM25 and vector implementations (L/index.py:412-458,504-539).
GAPS: Workspace search does not call vector search (W/app.py:346-361; K/knowledge_base.py:601-614). The packaged Core skill teaches local CLI/Git commands, not the workspace's complete remote workflow (A/skill_assets/SKILL.md:6-24,59-64); ten-minute productivity cannot be determined. Pi exact-byte upload explicitly refuses Entra mode (P/index.ts:138-149). The local API token is in the extension process environment, so a model-callable shell inheriting it can disclose it (P/index.ts:28-44,56-63,177-181); client-side model policy is not server-side enforcement. Actual connection and authorization cannot be verified without running it.

AREA: 4 Collaboration model
VERDICT: PARTIALLY WORKS
EVIDENCE: API and browser credentials are purpose-bound (W/auth.py:75-83; W/app.py:846-884); review POST requires browser identity and same-origin HTTPS (W/app.py:706-725). Review binds actor, candidate and one-use action; single-person self-review is explicitly conditional (W/review.py:258-286,321-329,366-414). Capabilities are checked from SQLite (W/state.py:677-687); backup invalidates restored sessions/actions (W/operations.py:186-190).
GAPS: HIGH: any read member can search/read all pages in a published snapshot: neither endpoint filters visibility (W/app.py:306-313,326-360; K/knowledge_base.py:601-614). Publication captures canonical content (K/git_authoring.py:302-312,2181-2188); a mixed-visibility publication therefore risks exposing restricted pages. HIGH: restore duplicates a shared authoring/analytics repository into separate roots and points the two subsystems at different copies (W/operations.py:133-142,213-247); subsequent work can diverge (W/analytics.py:946-968). Relocated absolute source and setup bindings need revalidation (A/authoring.py:320-336; W/analytics.py:154-162). Atomic behavior under concurrent revocation, all bypass paths and recovery require live verification, not inference from guards.

AREA: 5 Operational simplicity
VERDICT: DOES NOT WORK
EVIDENCE: One Uvicorn service is launched behind an HTTPS boundary (W/__main__.py:39-43,85-87); an external TLS boundary and Pi client add components. Storage types include SQLite state, Git, published/private files and DuckDB sources/execution; LanceDB is an optional fifth type (W/state.py:76-83,182-183; W/operations.py:110-155; A/sources.py:90-104; L/index.py:504-539). Four Python distributions plus the Pi extension are separate (pyproject.toml:13-19; P/package.json:1-8).
GAPS: Minimal local server configuration requires five environment variables; integrated analytics adds five path/identity variables, plus Pi configuration and HTTPS provisioning (W/app.py:161-180,364-393; P/index.ts:28-44). Multiple approval/recovery stages require substantial operator attention (W/analytics.py:735-830,1046-1129). The review page surfaces hashes and raw JSON (W/templates/review.html:12-25; W/review.py:879-885). Deployment time and production reliability cannot be determined statically. This is not the claimed minimal single-store user experience.

MISSING:
- Workspace vector search: semantic retrieval expected; separate adapter is not called by workspace search (W/app.py:346-361; L/index.py:504-539). Severity: major.
- Remote metric discovery and iterative schema/evidence authoring: agents need to find and model data without local Git access (W/app.py:436-491,517-567; A/authoring.py:339-363,2190-2246). Severity: major.
- Entra Pi file upload: SSO users cannot use the built-in exact-byte command (P/index.ts:138-149). Severity: major.
- Per-page and per-table authorization: mixed-sensitivity teams need narrower boundaries than workspace/source set (W/app.py:306-313,326-360; W/analytics.py:170-196). Severity: blocker.
- Single-deployment multi-workspace routing: configuration fixes one workspace ID (W/app.py:140-155,161-180). Severity: minor.
- Local self-service registration/password reset: local users and tokens are operator-managed; Entra SSO exists (W/__main__.py:53-83; W/app.py:846-884). Severity: minor.
- Reviewer notifications: no delivery route appears in the inspected workspace surface (W/app.py:706-928). Severity: minor.
- Scheduled refresh: no scheduler appears in the workspace source flow (W/analytics.py:314-359,470-486). Severity: minor.
- Rate limits/quotas: no such control is visible in the inspected routes (W/app.py:315-606,706-928). Severity: minor.
- Charts: the browser review displays structured text rather than data visualization (W/review.py:879-885). Severity: minor.
- Rollback UI: the inspected browser routes expose review rather than a rollback operation (W/app.py:706-928). Severity: minor.
- Localized review: the template is English-only (W/templates/review.html:1-68). Severity: minor.

OVER-COMPLICATED:
- Duplicate page validators (W/contributions.py:76-112; W/analytics.py:50-70): reuse basename/frontmatter checks while preserving different entity rules.
- Separate source-approval, caller-grant, candidate and recovery state machines (W/analytics.py:735-830,1046-1129): preserve gates but consolidate transitions and recovery representation.
- Review-action bindings and pinned admission (W/review.py:258-286,366-414; A/admission.py:1325-1354): stale/replay protection earns its keep; do not delete it merely for brevity.
- XLSX raw-XML preflight and refusal rules (A/spreadsheet_import.py:225-325,381-402): integrity checks have value, but can reject real workbooks; real-world compatibility is undetermined, so simplification requires measured cases.
- Enrichment impact projection (W/enrichment.py:38-84): useful to warn reviewers, but exact source/claim projection is not semantic analysis; keep it only if that warning is used.
- Package/test split separates optional retrieval and standalone Core (products/lumio/packages/lumio-lancedb/pyproject.toml:9-23; .github/workflows/ci.yml:19-32,49-82). It has capability value but imposes multiple test selections; offer one unified entry point rather than merge packages blindly.

OVERALL: NOT ACHIEVED
SUMMARY: Real source approval, reviewed publication, bounded uploads and compile-gated queries exist, but the workspace does not expose the full data-authoring or vector-retrieval journey. Static inspection found a mixed-visibility disclosure risk and an integrated restore design that can split the canonical repository (W/app.py:306-313,326-360; W/operations.py:213-247).
BIGGEST_GAP: The managed agent surface does not yet provide a safe, complete knowledge-and-data workflow without direct architectural intervention (W/app.py:436-491,517-567; A/authoring.py:339-363).
SIMPLICITY_AUDIT: Not maximally simple: one service plus HTTPS boundary and Pi; five storage types with optional LanceDB; four Python distributions plus extension; five base server variables plus five analytics variables (W/__main__.py:39-43,85-87; W/app.py:161-180; pyproject.toml:13-19; L/index.py:504-539).
TOP_3_SIMPLIFICATIONS: Share validation; consolidate state transitions; offer one unified verification entry point while preserving security gates (W/contributions.py:76-112; W/analytics.py:50-70,735-830,1046-1129; .github/workflows/ci.yml:19-32,49-82).
MISSING_COUNT: 12 grouped capabilities (each bullet above is one group).
