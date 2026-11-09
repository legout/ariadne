

# Ariadne-Lumio Unbiased Goal Audit

**Verification basis:** six parallel source audits + my own reads of `app.py`, `auth.py`, `state.py`, `intake.py`, `operations.py`, `setup.py`, `analytics.py:511-560`, `admission.py:1401-1412`, `review.py:366-426`, `templates/review.html`, dependency manifests and deploy assets. Every load-bearing claim below was either traced by me personally or spot-verified. Nothing was executed at runtime; findings are code-path analysis (two child findings are explicitly flagged as such below). Planning material (specs/ADRs/plans) was excluded as evidence; one accidental ADR grep was discarded.

---

```
AREA: 1 — Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE:
- POST /uploads exact-byte intake with 25MiB bound, retry-key idempotency, sha256, allowlist (.csv/.json/.parquet/.xlsx): app.py:606-645, intake.py:18-122.
- prepare_data_source (MCP tool app.py:437-462) → analytics.py:294-468: staged under project/.ariadne/managed-sources/<digest>, chmod 0444, digest re-check; XLSX → DuckDB artifact via spreadsheet_import.py:665-761.
- Browser approval of the exact resolved identity + one-time action_digest: app.py:706-750, review.py:837-893; approval keyed by identity digest in .ariadne/source-approvals.json (authoring_sources.py:370-434).
- Profiling re-derives identity before and after measuring and refuses on drift; allowlisted identifiers only: analytics.py:470-509, profiler.py:147-152.
- Compile gate is genuinely strong: static IO-authority predicate over source AND expression in two dialect parses, positive function allowlist, table-function/URI refusals, EXPLAIN bind, live grain guard: sql_authority.py:390-620, query.py:1359-1440, query.py:441-467.
- Results are pinned and truthfully labeled: query_data returns pinned {commit, source_digest} (analytics.py:554-560); governed:true/false explicit per operation (query.py:470-516, 1443-1451).
- VERIFIED BY ME: analytics.py:519-528 — every query_data operation opens with admission.resolve_admission, which hard-fails without .ariadne/current.json (admission.py:1401-1412). No query path — not even query_detail/query_records or ad-hoc define_metric — exists before a full semantic-layer admission record is published.
GAPS:
- No grant-to-query shortcut: data is approved, profiled, sitting in a DuckDB artifact, and the agent still cannot SELECT from it until it authors metric/context pages and two more human gates clear. This contradicts the stated promise that approved data becomes queryable.
- First run needs FOUR browser approvals (source approval, data grant, submission, publication) — two of them on the same source task (analytics.py:742-775).
- resolve_admission's error text tells the human to run the ariadne-admit CLI (admission.py:1406-1410) while the workspace admits via browser — divergent, confusing instruction.
- Approvers approve blind: the review page shows digests/identity only and explicitly opens no data (analytics.py:587-591); the agent cannot show a sample.
- CSV/Parquet get no conversion diagnostics; a malformed CSV surfaces only later at profiling.
- One native source per handle; multi-source setups refused (analytics.py:388-391).
FLOW: 5 agent calls (upload → prepare → profile → prepare_contribution [largest single work item: authoring governed pages] → query) + 4 human browser approvals, plus one-time /setup attachment and CLI-issued tokens. Steady state (already-admitted registry) collapses to ~2 calls; cold start is bureaucratic.
```

```
AREA: 2 — Knowledge pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE:
- Submit: POST /uploads (intake.py:79-122) → intake.extract uses liteparse for PDF and markitdown for DOCX (source_processor.py:177-178, 594-595) — produces TEXT, returned to the agent via read_source_material (app.py:424-434).
- Pages are agent-authored Markdown with YAML frontmatter, string-validated only (contributions.py:76-112): title/tags/ontology refs are the agent's labor, not pipeline output. The "PDF → structured pages" step of the goal is NOT implemented by the pipeline.
- prepare_contribution validates, commits into a per-task Git worktree, binds review digest (contributions.py:647-756, authoring_journey.py:480-560).
- Enrichment: prepare_enrichment selects ≤20 admitted pages with exact source facts (enrichment.py:92-162), entity-ID stability and ≤40 claims enforced (contributions.py:482-502, 721-725).
- Review shows a genuinely complete diff recomputed against BOTH the submission base and the current admitted version (review.py:171-299, 705-774); approval forbidden for the submitter unless single-person workspace (review.py:389-403); publish is an atomic pointer swap (publication.py:58-73, git_authoring.py:2052+).
- Rejection is safe: publication only happens on approve; reject flips status only (review.py:554-568). VERDICT on "rejected content leaves published state unchanged": WORKS.
- Read-after-publish: search/read reopen the published location per call, so the swap is visible immediately (app.py:306-362).
GAPS:
- Review renders semantic/claims/control/ontology sections as raw JSON in <pre> (review.py:952, 989-993) and analytics identity as JSON (review.py:837-885) — complete, but only an expert can verify it.
- The shown diff is against the CURRENT admitted version while the agent prepared against the submission base; divergence is never flagged (review.py:207-215).
- visibility:"internal" is hardcoded in this route (contributions.py:99-103) — no public-page path.
- Rejection/abandonment leaks artifacts: task worktrees, uploads, extractions are never cleaned up (contributions.py:668-673).
- Published enrichment tasks permanently unreopenable — a one-word typo forces a full new contribution (contributions.py:445-452).
FLOW: 7 steps upload→searchable; the heavy step (page authoring) is unassisted. Reviewer discovery depends entirely on the agent handing over the review_url returned by prepare (contributions.py:750-752) — no pending list exists.
```

```
AREA: 3 — Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE:
- pi-workspace is a real Pi extension: registers the workspace Streamable-HTTP MCP server at ${LUMIO_WORKSPACE_URL}/mcp with local-token Bearer or Entra OAuth (index.ts:56-83); functional code is 301 lines (index.ts 259 + upload.ts 42).
- Client/server contract matches: the only direct REST call POST /uploads (upload.ts:20-28) exists (app.py:606-640); all 10 MCP tools the client steers the agent to exist server-side (app.py:315-604). No phantom routes.
- Lexical search works with citations + published_version (app.py:347-362, knowledge_base.py:601-614).
- Governed query response carries compiled SQL, full context block with policy bodies and citations, admission view, data_signals, completeness (query.py:470-516; lumio_context.py:1466-1472).
- Governance status is truthful: governed:false is honestly set even on admitted sources and for ad-hoc definitions (query.py:1264, 1443-1451).
- Refusals are enforced SERVER-side: every tool re-checks state.permits per call (app.py:308-309, 428, 448, 468, 484, 502-505, 531, 587); no MCP tool exposes approve/publish; approval exists only as browser routes with one-time digests.
- SKILL.md spot-checks pass against the real CLI (cli.py:135/347-353; serve.py:115+; authoring_cli.py:151) — but it documents the WRONG surface for a connected agent.
GAPS:
- The 765-line SKILL.md documents the local ariadne CLI/stdio facade; an agent connected through pi-workspace faces the 10 workspace MCP tools. The only agent-facing doc for THAT contract is prose inside index.ts:190-252. An agent following the skill runs commands that don't exist in its tool surface.
- Not consumable in 10 minutes: dense normative caveats, no worked example outputs.
- LanceDB vector search is unreachable from the agent path (see Area 5 dead weight); search is lexical-only with a hard 1..20 limit and no pagination (app.py:349-350).
- POST /uploads hard-requires HTTPS (app.py:608) — localhost dev uploads refused in the very mode (local-token) meant for non-Entra setups.
- No retry_key/upload_id/source_task_id contract doc; invariants live only in client prose.
ONBOARDING: 6 fully manual steps, zero automation: operator CLI user create + membership grant + token issue (token printed once, __main__.py:108-116); hand-install the extension directory as a trusted Pi package; hand-edit 4 env vars (index.ts:29-44); reload. Entra mode adds app registrations and ~8 more steps. No installer, no registration endpoint.
```

```
AREA: 4 — Collaboration / auth boundary
VERDICT: PARTIALLY WORKS
EVIDENCE:
- Agent tokens cannot approve: local tokens are purpose-bound api|browser (state.py:290-339); browser login refuses api-purpose credentials (app.py:861-884, state.py:321-339); MCP verifier refuses browser-purpose (auth.py:75-83); Entra API JWT validated separately from browser OIDC (auth.py:136-153, 196-219). VERIFIED BY ME: review decisions require browser actor + review capability + one-time action_digest (app.py:706-750, state.py:568-594); self-approval only in single-person workspaces (review.py:389-403, state.py:622-628) — and even then only through the browser. The core boundary HOLDS.
- Per-request capability checks on every browser route (app.py:642-650, 706-717, 752-764, 776-785, 906-913); sessions rotate on login; cookies Secure/HttpOnly/SameSite=Lax; POSTs require exact Origin + HTTPS (app.py:68-72, 653-658, 714-725).
- Backup/restore invalidates browser sessions and issued/pending review actions (operations.py:186-191) — VERIFIED BY ME. Admitted content survives (SQLite + authoring repo + published + registry + artifacts are copied).
- Concurrent double-approve: both decisions take the same mutation locks and completion requires pending_review CAS (review.py:377-410, state.py:509-541).
GAPS (child code-path analysis, not reproduced at runtime):
- CRITICAL-ish: capability granularity is not member revocation. Removing read leaves contribute/review/setup intact (state.py:356-364, 677-687); there is no single "disable member" for Entra actors. The goal "revoking a member's access immediately blocks their agent and browser session" only holds if EVERY capability row is revoked; local-user disable exists but covers local credentials only.
- Restore copies the old credentials/memberships DB and deletes only sessions+pending actions (operations.py:130, 186-190): a credential revoked AFTER the backup becomes usable again after restore.
- Restore relocation breaks republishing: setup digests bind old absolute paths and publication checks the active receipt's destination (setup.py:220-248; git_authoring.py:2208-2212, 2257-2262) — a restored workspace needs fresh setup and then still refuses normal publication. Not exercised at runtime.
- Race: get_task reconciliation can mark a task published while the approving POST is still completing, which then fails its CAS and reports decision_failed despite publication (app.py:583-601, review.py:415-424, 469-508).
- Only the CLI can grant setup/inspect_source or create/issue local users/tokens (app.py:819-832, __main__.py:44-118) — routine administration cannot be done from the browser, contradicting "nobody needs direct access".
- No pending-review inbox or notification; the human must be handed a URL by the agent.
USABILITY: a non-technical human can follow the readable page diffs, but digests, Git revisions, paths and raw JSON dominate (templates/review.html:12-25); exact source identity cannot be verified from hashes by a non-expert; viewing source data needs a separate operator grant. Interfaces a reviewer must learn: browser review page + membership page + (inevitably) the operator CLI.
```

```
AREA: 5 — Operational simplicity ("maximally simple")
VERDICT: DOES NOT WORK (the claim fails)
EVIDENCE / MOVING PARTS (counted):
- ~103,500 runtime source lines behind "one server, one SQLite, one Git repo": ariadne-data 35,094; lumio-wiki ~55,400 src (cli.py alone 10,629 lines, 76 subcommands — VERIFIED BY ME); lumio-workspace 6,219; lumio-lancedb 2,034; ariadne-agent 1,790; pi-workspace 301.
- Processes: 3-4 (workspace uvicorn; standalone ariadne MCP container per compose.yaml:4-26 [optional — the workspace pulls ariadne in-process via its analytics extra, analytics.py:13-17]; HTTPS reverse proxy with exact Host/Origin allowlist; Pi client).
- Stores per workspace: 1 SQLite + operation-locks; Git repo #1 (authoring-repo/), Git repo #2 (analytics-project/) plus a worktree per proposal AND per task (proposals.py:57, analytics.py:967-968); registry/ + artifacts/; published/; profile.json; analytics-bindings.json; DuckDB artifacts; (LanceDB dirs unused). That is not "one Git repository".
- Env vars: ~40 across three surfaces (19 LUMIO_WORKSPACE_*, 8 pi client, ~13 ariadne/S3; deploy/.env.example:1-33).
- Auth: two client registrations in Entra, or local-token mode with manual CLI minting. Mandatory HTTPS + exact-match origin allowlists.
- Packages: 5 hard deps in ariadne-data including openai (used only lazily in author.py:48-50); ariadne-agent pins tau-ai==0.4.6 and a LOCAL-PATH tau-mcp source (/home/volker/coding/tau-mcp) — unresolvable on any other machine.
- Test surface: root coordination tests (2 modules) + integration/tests (6 modules, only 2 run from root, pyproject.toml:57-60) + two product suites with separate configs + npm tests + 2 wheel verifiers = 5 entrypoints a contributor must know.
- Deploy estimate from the code's own demands: 0.5-2 days for a competent sysadmin; dominated by auth wiring (Entra registrations + redirect/callback plumbing + exact-match TLS allowlist) and hand-authoring the data project (setup.py:294 hands `git init` back to the operator).
GAPS / DEAD WEIGHT (verified):
- ariadne-agent package: ZERO imports or dependency references outside its own package (verified by repo-wide grep) — a 1.8k-line package + 2 pinned deps serving no runtime path of this platform.
- lumio-lancedb: not a dependency of the workspace, not a wiki extra; production reach is one env-var-gated CLI path (cli.py:656-683). The stated "LanceDB for retrieval" is unreachable from the platform the goal describes.
- Duplicated docs trees (products/lumio/docs vs docs-site, same release notes twice), build/lib/ duplicates of src, .orchestrator archives incl. a vendored site-packages copy in-repo.
- CLI sprawl: 11 console scripts in ariadne-data alone; two parallel agent-skill doc systems.
```

```
MISSING:
1. Grant-to-query shortcut (query_detail/records/ad-hoc on data_granted sources without a published admission): biggest everyday gap [major]
2. Multiple workspaces per deployment — DB keys by workspace_id but config serves exactly one (app.py:163-190) [major]
3. Self-service user management — no self-registration/password reset/invite; SSO = Entra only; local users/tokens are CLI-minted [major]
4. Workspace health endpoint + metrics/alerting/logging config — ariadne serve has /healthz,/readyz (serve.py:1180-1185); the workspace has none; zero observability anywhere [major]
5. Rate limiting/quotas/fair use — only a 25MiB per-file cap (intake.py:70) [major]
6. Version history/rollback reachable from the workspace — publish is forward-only (publication.py:58); rollback-s3 exists only as a maintainer CLI alias (cli.py:9091) [major]
7. Semantic/full-text search beyond page-level lexical incl. attachments/tables — page_search.py is lexical-only, limit 20, no pagination [major]
8. Notifications when a review is ready or a task fails — no email/webhook/queue anywhere; reviewers must be told a URL [major]
9. Data-sample preview for approvers before approving an exact source identity [major]
10. Non-Pi clients — no VS Code/web reader/mobile/generic REST SDK; /workspace is a bare JSON status object [major]
11. Data visualization + CSV export of query results for humans [major]
12. Scheduled/automated refresh of live DB/S3 sources — profiling is on-demand only [major]
13. Queryable/exportable audit trail — review_actions rows exist but restore DELETEs issued/pending ones and no interface lists or exports decisions [major]
14. Agent onboarding installer + a workspace-MCP-facing skill doc (SKILL.md documents the wrong surface) [major]
15. Reviewer feedback notes to the agent — decide() has no note field; request_changes returns no reason (review.py:366-367, 554-559) [major]
16. API documentation — all routes include_in_schema=False, no OpenAPI, no MCP schema docs [minor]
17. Knowledge export to other formats (PDF/HTML/zip) from the workspace; S3 publish is maintainer-CLI-only [minor]
18. i18n — hardcoded English templates [minor]
19. Ingestion formats beyond .csv/.json/.parquet/.xlsx (no .tsv/.ods/gzip) [minor]
20. SQLite schema migration story — two ad-hoc ALTER TABLEs, no versioning (state.py:104,180) [minor]
21. CSRF tokens for /membership and /setup POSTs — SameSite=Lax cookie + Origin only [minor]
22. Local (non-HTTPS) dev mode for uploads [minor]
23. Secrets management beyond env vars/git config [minor]
24. Human direct-edit concurrency detection between agent publications [minor]
25. Async conversion recovery beyond deterministic reuse; cleanup of rejected-task artifacts [minor]
26. Multi-source-per-handle support (one native source per handle refused) [minor]
```

```
OVER-COMPLICATED:
1. lumio_wiki/cli.py — 10,629 lines, 76 subcommands, one god-CLI; commands belong beside the modules they serve.
2. ariadne monolith files — context.py 4,279 + authoring.py 3,932 (+5 satellites) + planner.py 3,030 + lumio_context.py 1,906; git_authoring.py 4,148 + knowledge_base.py 5,646 in wiki. Giants with circular-import shims documented in comments (validate.py:827, authoring.py:40).
3. admission.validate_admission_record — re-hashes the entire snapshot, re-checks git, approvals, bindings AND current-env on EVERY query (admission.py:1332-1397); the attacker model requires local FS write access. Verify once per process or on mtime change.
4. Two-stage source_approval/data_grant split (analytics.py:742-775) — two browser clicks on the same page/digest for one decision; record one row with two columns.
5. analytics.py reconciliation — approval state re-derived 3-5x per call (473-500, 562-595, 630-659, 1046-1130); one identity snapshot per operation suffices.
6. authoring_sources._effective_grant/approval_state historical-grant states (437-508) — three states for one boolean keyed by a sha256.
7. XLSX importer — twin openpyxl workbooks cross-validated cell-by-cell plus XML pre-parse (522-527, 361-409) while REJECTING real-world workbooks: error cells kill the sheet (410-414), stale dimension refs refuse (320-325), mixed types refuse (141-165), no merged-cell handling. Elaborate and brittle at once.
8. contributions.py — duplicated verbatim status guards (445-452), drafts-by-generation idempotency machinery re-implementing what retry-keys already enforce (state.py:366-424); lazy ReviewService import for recovery that belongs in one place (554-578).
9. state.py — five concerns in one 687-line class + ~11 free-string operation statuses defined across two modules; a single Status enum with per-action terminal sets would shrink it by a third.
10. review.py — 1,016 lines hand-rolling HTML with a duplicated analytics render branch (837-893); plus the reconcile-on-read + CAS + generation stack around the (justified) one-use digest mechanism — one consistent completion path would do.
11. pi-workspace disclosure-policy machinery — ~110 of 259 lines of compaction/summary-taint/abort logic the code itself admits is fail-open (index.ts:121) and the README calls non-attestation; server capability gates already do the real enforcement. Plus governance rules as 65-line English prose blobs in the client that will drift from server invariants.
12. Packaging/ceremony — ariadne-agent package (dead), lumio-lancedb unreachable from the platform, 11 console scripts, two skill-doc systems, duplicated docs trees, 5 test entrypoints, sources.py's 4 attach types × 6 file formats against a "one DuckDB file" goal.
13. openai as a HARD dep of ariadne-data for one lazily-imported module (author.py:48-50) — belongs in an extra.
NOT over-complicated (checked and acquitted): enrichment impact projection (~90 lines, one conservative projection — proportionate); the one-use review-action digests and admission pinning concept itself (they are the security core of a browser gate); the 301-line Pi client core; lumio-wiki's zero-index base (msgpack+msgspec only).
```

```
OVERALL: PARTIALLY ACHIEVED
SUMMARY: The governance core is real and honestly built — compile-gated SQL with a genuine IO-authority predicate, browser-only approval with one-time digests and a working self-approval carve-out, truthful governed/ad-hoc status, idempotent intake, and a backup/restore that preserves admitted content. But the two promises that would make this a platform fail in practice: "maximally simple" is contradicted by ~103k source lines, 3-4 processes, 2-3 Git repos plus worktrees, ~40 env vars, a 0.5-2 day deploy, and two whole packages with no runtime consumer; and the everyday agent/human experience is bureaucratic — four human gates before the first query, no query path at all between data grant and admission, six manual onboarding steps, no review inbox or notifications, and an expert-only review page — while the advertised LanceDB vector layer is unreachable from the served platform.
BIGGEST_GAP: Approved-and-profiled data is still unqueryable: resolve_admission hard-fails until a full semantic-layer contribution clears two more human approvals (analytics.py:519-528, admission.py:1401-1412). Closest security gap: capability-granular revocation is not member revocation, and restore resurrects credentials revoked after the backup (operations.py:130,186-190).
SIMPLICITY_AUDIT: Claim does not hold. Count: 3-4 processes; 1 SQLite + 2-3 Git repos + per-task/proposal worktrees + registry + artifact store + DuckDB artifacts (+ unused LanceDB); ~40 env vars; ~25 runtime packages; mandatory HTTPS proxy with exact-match allowlists; optional Entra IdP; 5 test entrypoints; 11 console scripts. Deploy: 0.5-2 days, dominated by auth wiring.
TOP_3_SIMPLIFICATIONS:
1. Collapse the approval ladder: one browser decision per source task (source+grant+submit+publish as one action) and allow bounded ad-hoc queries of data_granted sources without a published admission — removes the biggest workflow gap AND several state-machine branches.
2. Delete the unreachable: ariadne-agent package, lumio-lancedb from the platform path (or wire semantic search into search_knowledge — one or the other), duplicated docs trees, build/lib and .orchestrator archives; publish ONE agent-facing skill doc for the actual 10-tool MCP surface.
3. Collapse the state zoo and re-derivation: single Status enum, one identity snapshot per operation, one reconciliation path, admission validation per process/mtime instead of per query; drop the client-side fail-open disclosure machinery for plain tool allowlisting.
MISSING_COUNT: 26
```

💭 **Reasoning:**
```
Spot-checks pass:
- cli.py = 10,629 lines, 76 add_parser — confirmed.
- ariadne_agent: no runtime imports outside its own package (only comments in ariadne-data tests/pyproject) — confirmed dead weight for the platform.
- git_authoring.py publication does pointer checks and receipt reconciliation against destination — consistent with the restore-relocation claim (plausible; child flagged it as code-path analysis, not reproduced).

The skill `independent-goal-audit` matches what I did — interestingly it describes exactly the workflow I executed (recon personally, dispatch in waves, keep security-critical gates personal, spot-verify, synthesize). Good; no extra work needed. It says reproduce the requested output format exactly — I will.

One more verification before finalizing: the "critical" Area-4 claim about capability independence. From my own read of state.py (I read the whole file), `revoke()` removes one capability row; `permits()` checks per capability; `is_single_person_workspace` counts memberships. So yes — the stated goal "Revoking a member's access immediately blocks their agent and browser session" is only true if ALL capability rows are revoked; there's no member-level disable for Entra users, and restore resurrects revoked credentials. I can also verify quickly that restore copies the SQLite DB (operations.py — I read it myself: restore copies state.sqlite3 + private tree, deletes browser_sessions + issued/pending review actions). Confirmed from my own reading.

Also the Area-4 finding "get_task reconciliation race" — child marked as code-path analysis. I'll carry it as an Important (not Critical) claim with the caveat.

Now synthesize the final report. Format per the audit prompt:

AREA 1-5 blocks with VERDICT/EVIDENCE/GAPS, then MISSING, OVER-COMPLICATED, then OVERALL block. I need to merge six children's outputs + my own verified facts into a coherent, deduplicated report. Keep evidence file:line. Be exhaustive but organized. This is the requested deliverable — full length is appropriate (the user explicitly asked for exhaustive). But I shouldn't just dump everything; I should synthesize with judgment, deduplicate overlapping findings (e.g., LanceDB dead weight appears in B, C, E, F), and rank.

_... (101 more lines)_
```

# Ariadne-Lumio Unbiased Goal Audit

**Verification basis:** six parallel source audits + my own reads of `app.py`, `auth.py`, `state.py`, `intake.py`, `operations.py`, `setup.py`, `analytics.py:511-560`, `admission.py:1401-1412`, `review.py:366-426`, `templates/review.html`, dependency manifests and deploy assets. Every load-bearing claim below was either traced by me personally or spot-verified. Nothing was executed at runtime; findings are code-path analysis (two child findings are explicitly flagged as such below). Planning material (specs/ADRs/plans) was excluded as evidence; one accidental ADR grep was discarded.

---

```
AREA: 1 — Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE:
- POST /uploads exact-byte intake with 25MiB bound, retry-key idempotency, sha256, allowlist (.csv/.json/.parquet/.xlsx): app.py:606-645, intake.py:18-122.
- prepare_data_source (MCP tool app.py:437-462) → analytics.py:294-468: staged under project/.ariadne/managed-sources/<digest>, chmod 0444, digest re-check; XLSX → DuckDB artifact via spreadsheet_import.py:665-761.
- Browser approval of the exact resolved identity + one-time action_digest: app.py:706-750, review.py:837-893; approval keyed by identity digest in .ariadne/source-approvals.json (authoring_sources.py:370-434).
- Profiling re-derives identity before and after measuring and refuses on drift; allowlisted identifiers only: analytics.py:470-509, profiler.py:147-152.
- Compile gate is genuinely strong: static IO-authority predicate over source AND expression in two dialect parses, positive function allowlist, table-function/URI refusals, EXPLAIN bind, live grain guard: sql_authority.py:390-620, query.py:1359-1440, query.py:441-467.
- Results are pinned and truthfully labeled: query_data returns pinned {commit, source_digest} (analytics.py:554-560); governed:true/false explicit per operation (query.py:470-516, 1443-1451).
- VERIFIED BY ME: analytics.py:519-528 — every query_data operation opens with admission.resolve_admission, which hard-fails without .ariadne/current.json (admission.py:1401-1412). No query path — not even query_detail/query_records or ad-hoc define_metric — exists before a full semantic-layer admission record is published.
GAPS:
- No grant-to-query shortcut: data is approved, profiled, sitting in a DuckDB artifact, and the agent still cannot SELECT from it until it authors metric/context pages and two more human gates clear. This contradicts the stated promise that approved data becomes queryable.
- First run needs FOUR browser approvals (source approval, data grant, submission, publication) — two of them on the same source task (analytics.py:742-775).
- resolve_admission's error text tells the human to run the ariadne-admit CLI (admission.py:1406-1410) while the workspace admits via browser — divergent, confusing instruction.
- Approvers approve blind: the review page shows digests/identity only and explicitly opens no data (analytics.py:587-591); the agent cannot show a sample.
- CSV/Parquet get no conversion diagnostics; a malformed CSV surfaces only later at profiling.
- One native source per handle; multi-source setups refused (analytics.py:388-391).
FLOW: 5 agent calls (upload → prepare → profile → prepare_contribution [largest single work item: authoring governed pages] → query) + 4 human browser approvals, plus one-time /setup attachment and CLI-issued tokens. Steady state (already-admitted registry) collapses to ~2 calls; cold start is bureaucratic.
```

```
AREA: 2 — Knowledge pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE:
- Submit: POST /uploads (intake.py:79-122) → intake.extract uses liteparse for PDF and markitdown for DOCX (source_processor.py:177-178, 594-595) — produces TEXT, returned to the agent via read_source_material (app.py:424-434).
- Pages are agent-authored Markdown with YAML frontmatter, string-validated only (contributions.py:76-112): title/tags/ontology refs are the agent's labor, not pipeline output. The "PDF → structured pages" step of the goal is NOT implemented by the pipeline.
- prepare_contribution validates, commits into a per-task Git worktree, binds review digest (contributions.py:647-756, authoring_journey.py:480-560).
- Enrichment: prepare_enrichment selects ≤20 admitted pages with exact source facts (enrichment.py:92-162), entity-ID stability and ≤40 claims enforced (contributions.py:482-502, 721-725).
- Review shows a genuinely complete diff recomputed against BOTH the submission base and the current admitted version (review.py:171-299, 705-774); approval forbidden for the submitter unless single-person workspace (review.py:389-403); publish is an atomic pointer swap (publication.py:58-73, git_authoring.py:2052+).
- Rejection is safe: publication only happens on approve; reject flips status only (review.py:554-568). VERDICT on "rejected content leaves published state unchanged": WORKS.
- Read-after-publish: search/read reopen the published location per call, so the swap is visible immediately (app.py:306-362).
GAPS:
- Review renders semantic/claims/control/ontology sections as raw JSON in <pre> (review.py:952, 989-993) and analytics identity as JSON (review.py:837-885) — complete, but only an expert can verify it.
- The shown diff is against the CURRENT admitted version while the agent prepared against the submission base; divergence is never flagged (review.py:207-215).
- visibility:"internal" is hardcoded in this route (contributions.py:99-103) — no public-page path.
- Rejection/abandonment leaks artifacts: task worktrees, uploads, extractions are never cleaned up (contributions.py:668-673).
- Published enrichment tasks permanently unreopenable — a one-word typo forces a full new contribution (contributions.py:445-452).
FLOW: 7 steps upload→searchable; the heavy step (page authoring) is unassisted. Reviewer discovery depends entirely on the agent handing over the review_url returned by prepare (contributions.py:750-752) — no pending list exists.
```

```
AREA: 3 — Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE:
- pi-workspace is a real Pi extension: registers the workspace Streamable-HTTP MCP server at ${LUMIO_WORKSPACE_URL}/mcp with local-token Bearer or Entra OAuth (index.ts:56-83); functional code is 301 lines (index.ts 259 + upload.ts 42).
- Client/server contract matches: the only direct REST call POST /uploads (upload.ts:20-28) exists (app.py:606-640); all 10 MCP tools the client steers the agent to exist server-side (app.py:315-604). No phantom routes.
- Lexical search works with citations + published_version (app.py:347-362, knowledge_base.py:601-614).
- Governed query response carries compiled SQL, full context block with policy bodies and citations, admission view, data_signals, completeness (query.py:470-516; lumio_context.py:1466-1472).
- Governance status is truthful: governed:false is honestly set even on admitted sources and for ad-hoc definitions (query.py:1264, 1443-1451).
- Refusals are enforced SERVER-side: every tool re-checks state.permits per call (app.py:308-309, 428, 448, 468, 484, 502-505, 531, 587); no MCP tool exposes approve/publish; approval exists only as browser routes with one-time digests.
- SKILL.md spot-checks pass against the real CLI (cli.py:135/347-353; serve.py:115+; authoring_cli.py:151) — but it documents the WRONG surface for a connected agent.
GAPS:
- The 765-line SKILL.md documents the local ariadne CLI/stdio facade; an agent connected through pi-workspace faces the 10 workspace MCP tools. The only agent-facing doc for THAT contract is prose inside index.ts:190-252. An agent following the skill runs commands that don't exist in its tool surface.
- Not consumable in 10 minutes: dense normative caveats, no worked example outputs.
- LanceDB vector search is unreachable from the agent path (see Area 5 dead weight); search is lexical-only with a hard 1..20 limit and no pagination (app.py:349-350).
- POST /uploads hard-requires HTTPS (app.py:608) — localhost dev uploads refused in the very mode (local-token) meant for non-Entra setups.
- No retry_key/upload_id/source_task_id contract doc; invariants live only in client prose.
ONBOARDING: 6 fully manual steps, zero automation: operator CLI user create + membership grant + token issue (token printed once, __main__.py:108-116); hand-install the extension directory as a trusted Pi package; hand-edit 4 env vars (index.ts:29-44); reload. Entra mode adds app registrations and ~8 more steps. No installer, no registration endpoint.
```

```
AREA: 4 — Collaboration / auth boundary
VERDICT: PARTIALLY WORKS
EVIDENCE:
- Agent tokens cannot approve: local tokens are purpose-bound api|browser (state.py:290-339); browser login refuses api-purpose credentials (app.py:861-884, state.py:321-339); MCP verifier refuses browser-purpose (auth.py:75-83); Entra API JWT validated separately from browser OIDC (auth.py:136-153, 196-219). VERIFIED BY ME: review decisions require browser actor + review capability + one-time action_digest (app.py:706-750, state.py:568-594); self-approval only in single-person workspaces (review.py:389-403, state.py:622-628) — and even then only through the browser. The core boundary HOLDS.
- Per-request capability checks on every browser route (app.py:642-650, 706-717, 752-764, 776-785, 906-913); sessions rotate on login; cookies Secure/HttpOnly/SameSite=Lax; POSTs require exact Origin + HTTPS (app.py:68-72, 653-658, 714-725).
- Backup/restore invalidates browser sessions and issued/pending review actions (operations.py:186-191) — VERIFIED BY ME. Admitted content survives (SQLite + authoring repo + published + registry + artifacts are copied).
- Concurrent double-approve: both decisions take the same mutation locks and completion requires pending_review CAS (review.py:377-410, state.py:509-541).
GAPS (child code-path analysis, not reproduced at runtime):
- CRITICAL-ish: capability granularity is not member revocation. Removing read leaves contribute/review/setup intact (state.py:356-364, 677-687); there is no single "disable member" for Entra actors. The goal "revoking a member's access immediately blocks their agent and browser session" only holds if EVERY capability row is revoked; local-user disable exists but covers local credentials only.
- Restore copies the old credentials/memberships DB and deletes only sessions+pending actions (operations.py:130, 186-190): a credential revoked AFTER the backup becomes usable again after restore.
- Restore relocation breaks republishing: setup digests bind old absolute paths and publication checks the active receipt's destination (setup.py:220-248; git_authoring.py:2208-2212, 2257-2262) — a restored workspace needs fresh setup and then still refuses normal publication. Not exercised at runtime.
- Race: get_task reconciliation can mark a task published while the approving POST is still completing, which then fails its CAS and reports decision_failed despite publication (app.py:583-601, review.py:415-424, 469-508).
- Only the CLI can grant setup/inspect_source or create/issue local users/tokens (app.py:819-832, __main__.py:44-118) — routine administration cannot be done from the browser, contradicting "nobody needs direct access".
- No pending-review inbox or notification; the human must be handed a URL by the agent.
USABILITY: a non-technical human can follow the readable page diffs, but digests, Git revisions, paths and raw JSON dominate (templates/review.html:12-25); exact source identity cannot be verified from hashes by a non-expert; viewing source data needs a separate operator grant. Interfaces a reviewer must learn: browser review page + membership page + (inevitably) the operator CLI.
```

```
AREA: 5 — Operational simplicity ("maximally simple")
VERDICT: DOES NOT WORK (the claim fails)
EVIDENCE / MOVING PARTS (counted):
- ~103,500 runtime source lines behind "one server, one SQLite, one Git repo": ariadne-data 35,094; lumio-wiki ~55,400 src (cli.py alone 10,629 lines, 76 subcommands — VERIFIED BY ME); lumio-workspace 6,219; lumio-lancedb 2,034; ariadne-agent 1,790; pi-workspace 301.
- Processes: 3-4 (workspace uvicorn; standalone ariadne MCP container per compose.yaml:4-26 [optional — the workspace pulls ariadne in-process via its analytics extra, analytics.py:13-17]; HTTPS reverse proxy with exact Host/Origin allowlist; Pi client).
- Stores per workspace: 1 SQLite + operation-locks; Git repo #1 (authoring-repo/), Git repo #2 (analytics-project/) plus a worktree per proposal AND per task (proposals.py:57, analytics.py:967-968); registry/ + artifacts/; published/; profile.json; analytics-bindings.json; DuckDB artifacts; (LanceDB dirs unused). That is not "one Git repository".
- Env vars: ~40 across three surfaces (19 LUMIO_WORKSPACE_*, 8 pi client, ~13 ariadne/S3; deploy/.env.example:1-33).
- Auth: two client registrations in Entra, or local-token mode with manual CLI minting. Mandatory HTTPS + exact-match origin allowlists.
- Packages: 5 hard deps in ariadne-data including openai (used only lazily in author.py:48-50); ariadne-agent pins tau-ai==0.4.6 and a LOCAL-PATH tau-mcp source (/home/volker/coding/tau-mcp) — unresolvable on any other machine.
- Test surface: root coordination tests (2 modules) + integration/tests (6 modules, only 2 run from root, pyproject.toml:57-60) + two product suites with separate configs + npm tests + 2 wheel verifiers = 5 entrypoints a contributor must know.
- Deploy estimate from the code's own demands: 0.5-2 days for a competent sysadmin; dominated by auth wiring (Entra registrations + redirect/callback plumbing + exact-match TLS allowlist) and hand-authoring the data project (setup.py:294 hands `git init` back to the operator).
GAPS / DEAD WEIGHT (verified):
- ariadne-agent package: ZERO imports or dependency references outside its own package (verified by repo-wide grep) — a 1.8k-line package + 2 pinned deps serving no runtime path of this platform.
- lumio-lancedb: not a dependency of the workspace, not a wiki extra; production reach is one env-var-gated CLI path (cli.py:656-683). The stated "LanceDB for retrieval" is unreachable from the platform the goal describes.
- Duplicated docs trees (products/lumio/docs vs docs-site, same release notes twice), build/lib/ duplicates of src, .orchestrator archives incl. a vendored site-packages copy in-repo.
- CLI sprawl: 11 console scripts in ariadne-data alone; two parallel agent-skill doc systems.
```

```
MISSING:
1. Grant-to-query shortcut (query_detail/records/ad-hoc on data_granted sources without a published admission): biggest everyday gap [major]
2. Multiple workspaces per deployment — DB keys by workspace_id but config serves exactly one (app.py:163-190) [major]
3. Self-service user management — no self-registration/password reset/invite; SSO = Entra only; local users/tokens are CLI-minted [major]
4. Workspace health endpoint + metrics/alerting/logging config — ariadne serve has /healthz,/readyz (serve.py:1180-1185); the workspace has none; zero observability anywhere [major]
5. Rate limiting/quotas/fair use — only a 25MiB per-file cap (intake.py:70) [major]
6. Version history/rollback reachable from the workspace — publish is forward-only (publication.py:58); rollback-s3 exists only as a maintainer CLI alias (cli.py:9091) [major]
7. Semantic/full-text search beyond page-level lexical incl. attachments/tables — page_search.py is lexical-only, limit 20, no pagination [major]
8. Notifications when a review is ready or a task fails — no email/webhook/queue anywhere; reviewers must be told a URL [major]
9. Data-sample preview for approvers before approving an exact source identity [major]
10. Non-Pi clients — no VS Code/web reader/mobile/generic REST SDK; /workspace is a bare JSON status object [major]
11. Data visualization + CSV export of query results for humans [major]
12. Scheduled/automated refresh of live DB/S3 sources — profiling is on-demand only [major]
13. Queryable/exportable audit trail — review_actions rows exist but restore DELETEs issued/pending ones and no interface lists or exports decisions [major]
14. Agent onboarding installer + a workspace-MCP-facing skill doc (SKILL.md documents the wrong surface) [major]
15. Reviewer feedback notes to the agent — decide() has no note field; request_changes returns no reason (review.py:366-367, 554-559) [major]
16. API documentation — all routes include_in_schema=False, no OpenAPI, no MCP schema docs [minor]
17. Knowledge export to other formats (PDF/HTML/zip) from the workspace; S3 publish is maintainer-CLI-only [minor]
18. i18n — hardcoded English templates [minor]
19. Ingestion formats beyond .csv/.json/.parquet/.xlsx (no .tsv/.ods/gzip) [minor]
20. SQLite schema migration story — two ad-hoc ALTER TABLEs, no versioning (state.py:104,180) [minor]
21. CSRF tokens for /membership and /setup POSTs — SameSite=Lax cookie + Origin only [minor]
22. Local (non-HTTPS) dev mode for uploads [minor]
23. Secrets management beyond env vars/git config [minor]
24. Human direct-edit concurrency detection between agent publications [minor]
25. Async conversion recovery beyond deterministic reuse; cleanup of rejected-task artifacts [minor]
26. Multi-source-per-handle support (one native source per handle refused) [minor]
```

```
OVER-COMPLICATED:
1. lumio_wiki/cli.py — 10,629 lines, 76 subcommands, one god-CLI; commands belong beside the modules they serve.
2. ariadne monolith files — context.py 4,279 + authoring.py 3,932 (+5 satellites) + planner.py 3,030 + lumio_context.py 1,906; git_authoring.py 4,148 + knowledge_base.py 5,646 in wiki. Giants with circular-import shims documented in comments (validate.py:827, authoring.py:40).
3. admission.validate_admission_record — re-hashes the entire snapshot, re-checks git, approvals, bindings AND current-env on EVERY query (admission.py:1332-1397); the attacker model requires local FS write access. Verify once per process or on mtime change.
4. Two-stage source_approval/data_grant split (analytics.py:742-775) — two browser clicks on the same page/digest for one decision; record one row with two columns.
5. analytics.py reconciliation — approval state re-derived 3-5x per call (473-500, 562-595, 630-659, 1046-1130); one identity snapshot per operation suffices.
6. authoring_sources._effective_grant/approval_state historical-grant states (437-508) — three states for one boolean keyed by a sha256.
7. XLSX importer — twin openpyxl workbooks cross-validated cell-by-cell plus XML pre-parse (522-527, 361-409) while REJECTING real-world workbooks: error cells kill the sheet (410-414), stale dimension refs refuse (320-325), mixed types refuse (141-165), no merged-cell handling. Elaborate and brittle at once.
8. contributions.py — duplicated verbatim status guards (445-452), drafts-by-generation idempotency machinery re-implementing what retry-keys already enforce (state.py:366-424); lazy ReviewService import for recovery that belongs in one place (554-578).
9. state.py — five concerns in one 687-line class + ~11 free-string operation statuses defined across two modules; a single Status enum with per-action terminal sets would shrink it by a third.
10. review.py — 1,016 lines hand-rolling HTML with a duplicated analytics render branch (837-893); plus the reconcile-on-read + CAS + generation stack around the (justified) one-use digest mechanism — one consistent completion path would do.
11. pi-workspace disclosure-policy machinery — ~110 of 259 lines of compaction/summary-taint/abort logic the code itself admits is fail-open (index.ts:121) and the README calls non-attestation; server capability gates already do the real enforcement. Plus governance rules as 65-line English prose blobs in the client that will drift from server invariants.
12. Packaging/ceremony — ariadne-agent package (dead), lumio-lancedb unreachable from the platform, 11 console scripts, two skill-doc systems, duplicated docs trees, 5 test entrypoints, sources.py's 4 attach types × 6 file formats against a "one DuckDB file" goal.
13. openai as a HARD dep of ariadne-data for one lazily-imported module (author.py:48-50) — belongs in an extra.
NOT over-complicated (checked and acquitted): enrichment impact projection (~90 lines, one conservative projection — proportionate); the one-use review-action digests and admission pinning concept itself (they are the security core of a browser gate); the 301-line Pi client core; lumio-wiki's zero-index base (msgpack+msgspec only).
```

```
OVERALL: PARTIALLY ACHIEVED
SUMMARY: The governance core is real and honestly built — compile-gated SQL with a genuine IO-authority predicate, browser-only approval with one-time digests and a working self-approval carve-out, truthful governed/ad-hoc status, idempotent intake, and a backup/restore that preserves admitted content. But the two promises that would make this a platform fail in practice: "maximally simple" is contradicted by ~103k source lines, 3-4 processes, 2-3 Git repos plus worktrees, ~40 env vars, a 0.5-2 day deploy, and two whole packages with no runtime consumer; and the everyday agent/human experience is bureaucratic — four human gates before the first query, no query path at all between data grant and admission, six manual onboarding steps, no review inbox or notifications, and an expert-only review page — while the advertised LanceDB vector layer is unreachable from the served platform.
BIGGEST_GAP: Approved-and-profiled data is still unqueryable: resolve_admission hard-fails until a full semantic-layer contribution clears two more human approvals (analytics.py:519-528, admission.py:1401-1412). Closest security gap: capability-granular revocation is not member revocation, and restore resurrects credentials revoked after the backup (operations.py:130,186-190).
SIMPLICITY_AUDIT: Claim does not hold. Count: 3-4 processes; 1 SQLite + 2-3 Git repos + per-task/proposal worktrees + registry + artifact store + DuckDB artifacts (+ unused LanceDB); ~40 env vars; ~25 runtime packages; mandatory HTTPS proxy with exact-match allowlists; optional Entra IdP; 5 test entrypoints; 11 console scripts. Deploy: 0.5-2 days, dominated by auth wiring.
TOP_3_SIMPLIFICATIONS:
1. Collapse the approval ladder: one browser decision per source task (source+grant+submit+publish as one action) and allow bounded ad-hoc queries of data_granted sources without a published admission — removes the biggest workflow gap AND several state-machine branches.
2. Delete the unreachable: ariadne-agent package, lumio-lancedb from the platform path (or wire semantic search into search_knowledge — one or the other), duplicated docs trees, build/lib and .orchestrator archives; publish ONE agent-facing skill doc for the actual 10-tool MCP surface.
3. Collapse the state zoo and re-derivation: single Status enum, one identity snapshot per operation, one reconciliation path, admission validation per process/mtime instead of per query; drop the client-side fail-open disclosure machinery for plain tool allowlisting.
MISSING_COUNT: 26
```