# Independent Audit — glm-5.3-flash (zai)

All claims below were traced in source this session. Repo treated read-only.

```
AREA: 1 Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Upload: app.py:606-640 → intake.py:79-122 (25 MiB bound intake.py:66-74). DB/S3 sources only via operator-written bindings JSON (analytics.py:101-126); the agent can never add one. Profiling gated twice: native Source Approval + per-caller data grant (analytics.py:170-196), both granted ONLY by browser decisions (analytics.py:735-775: approve_sources → separate second approval → status data_granted). Query: app.py:476-491 → analytics.py:511-560 re-checks grant then returns result pinned to admission commit + source_digest (analytics.py:554-560). Compile gate is real sqlglot compilation (query.py:66-70, 392-437); XLSX import verifies retained bytes and refuses encryption/external links/shared-formula inference (analytics.py:210-249; spreadsheet_import.py:84-101, 296-302).
GAPS: Flow is 6 steps for ONE CSV question — upload → prepare_data_source → browser approve #1 (source identity) → browser approve #2 (data grant) → profile_data_source → query_data — plus operator pre-work: analytics Git project, authoring repo, profile.json, bindings file, owner /setup approval, CLI user+token+membership issuance. 10 env vars minimum for analytics mode (app.py:162-189; +6 for Entra, auth.py:38-51). This is bureaucracy, not flow. asyncio.run() inside sync tool (analytics.py:549-551) breaks if the MCP host ever runs sync tools on the loop thread — CANNOT DETERMINE for the vendored mcp>=2.2 (pyproject lumio-workspace). Errors are mostly actionable (codes + "ask the owner to provision…" analytics.py:113-116), a cut above plain refusals.
```

```
AREA: 2 Knowledge pipeline
VERDICT: WORKS (with friction)
EVIDENCE: Document upload → extract (txt/md/pdf/docx, intake.py:152-183) → prepare_contribution builds an isolated Git worktree, ingests candidate, computes a review digest, commits and verifies the commit matches the review (contributions.py:647-756, esp. 703-744). Human review shows body diff, source support with availability, claim anchors, exact-quote lineage against retained originals, conflicts (review.py:896-1005, 571-647). Approve publishes only the exact reviewed tree (review.py:527-551); the served location re-validates on every read (app.py:306-313), so published content is immediately readable via read_knowledge (app.py:327-344). Reject/request_changes leave publication untouched (review.py:554-568). Semantic enrichment bounded to 20 pages / 200k chars / 40 claims (enrichment.py:15, 113-117, 248-253; contributions.py:721-725).
GAPS: Pages must already arrive as frontmatter Markdown with visibility:internal and knowledge-artifact type (contributions.py:88-112); the "PDF → structured page" transformation is delegated to lumio_wiki.authoring_journey.ingest_candidate — parsing depth CANNOT DETERMINE without reading that 851-line module. No tool to list/search one's own pending tasks; agent must track task_ids. Review UI is exhaustive but expert-dense — a non-technical reviewer will rubber-stamp.
```

```
AREA: 3 Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE: Pi extension registers the MCP server from env (index.ts:56-83), guards tool calls for unallowed models (index.ts:129-136), and preserves disclosure taint across compaction (index.ts:87-101). Workspace tools enforce limits (search limit ≤20 app.py:349-350) and return citations + published_version (app.py:334-344, 352-362). Governed/ad-hoc labeling is deeply specified (skill_assets/SKILL.md:133-138, 571-603). No agent-reachable approve path exists — the MCP surface is read/prepare only (app.py:315-604).
GAPS: (a) LanceDB vector search is NOT in the served path: search_knowledge is purely lexical (knowledge_base.py:601-612 → page_search.py:82-100); lumio_lancedb is imported only by tests and its own package (repo-wide grep). Goal claims vector retrieval; delivered is keyword scoring. (b) Model disclosure policy is client-side and, by the code's own comment, fail-open (index.ts:120-128). (c) Onboarding is heavy: 765-line SKILL.md of hedged legalese (SKILL.md:3 alone is a 90-line sentence); 10-minute productivity is unrealistic. (d) /workspace-upload injects a 15-line instruction sermon into the session (index.ts:190-205) — prompt bloat as UX.
```

```
AREA: 4 Collaboration model
VERDICT: WORKS
EVIDENCE: Approvals require a browser session: routes check _browser_actor + review capability + same-origin HTTPS form POST (app.py:706-750); API tokens are purpose='api' (state.py:321-339) and cannot mint sessions (mode mismatch check app.py:86-89). Every approval consumes a one-use 64-hex digest bound to a 17-key evidence binding (state.py:543-594; review.py:267-286); replay raises action_replay (review.py:404-414). Self-approval is blocked in multi-person workspaces (review.py:395-403) but deliberately allowed browser-only in single-person ones. Revocation is immediate: permits() is re-queried per call (state.py:686-687) and sessions re-validate their credential on every load (state.py:205-226). Backup/restore invalidates outstanding actions and all sessions (operations.py:186-190) and relinks worktrees (operations.py:159-172).
GAPS: Single-person self-approval means one human clicking "approve" on their own agent's work is the entire governance for the most likely deployment. No pending-review inbox: a reviewer can only open a task_id handed over by the agent (only /review/{task_id} exists, app.py:706).
```

```
AREA: 5 Operational simplicity
VERDICT: DOES NOT WORK (claim "maximally simple" fails)
EVIDENCE: One process (uvicorn, __main__.py:86-88) behind an implied HTTPS proxy. Stores ≥11 despite "one SQLite, one Git": state.sqlite3 (state.py:79-180), operation-locks dir (state.py:429), private tree (uploads/extractions/worktrees/authored/controls/originals — intake.py:77, contributions.py:668-689, 629-636), authoring Git repo, published Git destination, profile.json, source registry, artifact store, analytics Git project, bindings JSON, DuckDB. Env vars: 5 (bare) → 7 (authoring) → 10 (analytics) → 16 (Entra). Dead weight: root src/ariadne/ is an EMPTY directory (0 .py files); vendored fixture duplicate .orchestrator/issue73-20261015/lumio-fixture/ carries full pyproject copies; operation lock files are never GC'd (state.py:429); setup_previews is an unbounded in-memory dict outside SQLite (app.py:279, 703). 363k lines of tests vs ~100k lines of product code. requires-python >=3.14.
GAPS: The system the goal describes (1 server, 1 SQLite, 1 Git, DuckDB, LanceDB) is not the system built; operations.py exists chiefly to enumerate and copy the sprawl (operations.py:30-40, 110-156).
```

MISSING:
- Pending-review listing/notification: reviewer cannot discover waiting tasks; nothing alerts humans [major]
- Published-version history/diff/rollback UI: pointer is current-only; Git history not exposed via any route [major]
- Web UI for humans to browse knowledge/metrics: /workspace returns JSON status only (app.py:906-916); no client beyond Pi [major]
- Audit trail viewer: review_actions rows store who/when/binding but no route or page reads them [major]
- Health/metrics endpoints for the workspace (ariadne-serve has /healthz; workspace none) [minor]
- Multi-workspace per deployment [minor]
- Self-service user management: credentials via CLI only, Unix-epoch expiry arg (__main__.py:74-83); no reset [minor]
- Rate limiting/quotas beyond 25 MiB upload [minor]
- LanceDB vector search actually wired into serving [major — advertised in goal]
- Data visualization [minor]
- Scheduled refresh of live sources (every source change needs re-approval by design) [minor]
- OpenAPI docs (all custom routes include_in_schema=False, app.py:606+) [minor]
- list-all-pages tool: agents can only search/read by title [minor]
- Export via workspace (SDK public_pages export exists, knowledge_base.py:590-596, but no route) [minor]
- i18n [minor]
- Backup scheduling (manual CLI only) [minor]
- Pagination on operations listing (no ops GC: operations table grows forever) [minor]

OVER-COMPLICATED:
- Review binding + reconcile machinery: 17-key bindings (review.py:267-286), review_generation counters, and two parallel crash-recovery paths (review.py:428-509, analytics.py:1046-1130) that duplicate apply_decision logic; one shared "finish or recover" routine would halve review.py
- BrowserSessionMiddleware state machine (app.py:94-135): rotate/clear/save/update matrix for one cookie; signed server-side sessions would be ~20 lines
- Duplicate dead status check contributions.py:445-452 (identical consecutive if-blocks)
- Three membership management paths: CLI grant/revoke (__main__.py:44-51), local-membership, and browser /membership page (app.py:776-844) — keep the page
- app.py reaching into state._connect() (app.py:227) — layering break acknowledged in its own comment
- asyncio.run-inside-tool (analytics.py:549-551): make the tool async instead
- 5 packages + root coordination layer for one deployed service; lumio-lancedb (972-line index.py + release workflow) is unused in the served path — delete or wire it
- .orchestrator fixture tree and empty root src/ — remove from repo
- 363k test lines including coordination suites duplicating member suites — prune to member-level
- SKILL.md at 765 lines/50 KB — an agent prompt, not a skill; halve it

OVERALL: PARTIALLY ACHIEVED
SUMMARY: The trust architecture is genuinely implemented — one-use browser-bound approvals, per-caller data grants, compile-gated SQL, exact-candidate publication — and the knowledge loop works end-to-end. But the stated shape (one server, one SQLite, one Git, DuckDB, LanceDB) is fiction: the deployment is 1 process over ~11 stores, 5–16 env vars, two sequential browser approvals before the first data query, and a 765-line skill manual. The headline capabilities that miss are LanceDB vector search (not in the serving path) and any way for a human to discover or audit reviews without an agent handing them a task_id.
BIGGEST_GAP: No reviewer-side surface: humans cannot list, get notified about, or audit pending/completed reviews; governance depends on agents voluntarily surfacing review URLs.
SIMPLICITY_AUDIT: Claim fails. 1 process (+TLS proxy), 11+ durable stores, 5–16 env vars, 5 packages, plus dead artifacts (empty src/ariadne, .orchestrator fixture, unbounded lock/preview/operation tables). A competent sysadmin needs on the order of a day, not an hour.
TOP_3_SIMPLIFICATIONS: (1) Collapse the two-stage source-approval/data-grant browser sequence into one approval binding that names both, halving the data path; (2) delete or actually wire lumio-lancedb and drop the root coordination/fixture scaffolding; (3) replace the review reconcile/generation machinery and session middleware with one recovery routine and signed sessions.
MISSING_COUNT: 17
