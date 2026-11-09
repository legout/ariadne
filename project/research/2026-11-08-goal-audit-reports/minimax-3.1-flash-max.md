# Audit — ariadne-lumio (MiniMax-M3.1-Flash)

Repo: /home/volker/coding/ariadne @ 2f5bc97 (clean). Static inspection only; no tests run. Every citation is a file read this session.

## AREA 1: Data pipeline
```
AREA: Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Real path, not mocks: intake.py:18 accepts .csv/.json/.parquet/.xlsx; analytics.py:294-468 stages a source proposal → pending_source_approval; analytics.py:470-509 profiles it via authoring_sources.inputs (real schema, sample_rows=100); analytics.py:511-560 query_data opens QueryRuntime.open_project(admission_record=record) and dispatches get_metric/query_metrics/query_detail/query_records/define_metric; query.py:441-467 renders SQL then assert_single_statement + EXPLAIN bind + check_grain_preserving before execution — no raw-SQL path exists. sql_authority.py:1-48 and query.py:1387-1391 statically refuse file/network/table-function/metadata-catalog reads in ad-hoc define_metric before any DuckDB call. Results carry commit + source_digest (analytics.py:554-560) plus governed/context/citations.
GAPS: (1) upload→query is 7+ steps, not <5: upload → prepare_data_source → browser review #1 (Source Approval) → review #2 (data grant) → profile → prepare_contribution → review #3 (submission) → review #4 (overall admission) → query_data. (2) No discovery: the workspace exposes 10 tools (app.py:315-604), no list_metrics/list_datasets/search_context, so an agent cannot enumerate what it may query. (3) DB/S3 sources are unreachable from the API: analytics.py:101-126 requires an operator-maintained bindings file; only uploads and pre-bound handles work. (4) XLSX import (spreadsheet_import.py:225-453) refuses shared formulas without explicit r, missing formula caches and dimension mismatch — strict, but it parses real workbooks from cached values only. (5) Profiling is possible only after both grants (analytics.py:180-196): no schema preview before approval.
```

## AREA 2: Knowledge pipeline
```
AREA: Knowledge pipeline
VERDICT: WORKS
EVIDENCE: contributions.py:196-280 stages a Git worktree candidate with no publication authority; pages validated (visibility "internal", entity_types including "knowledge-artifact" — contributions.py:76-112). review.py:511-568 publishes only via PublicationService.publish under a bound review digest; publication.py:58-73 delegates to lumio_wiki.publish_revision with expected_current, so rejection leaves the published pointer unchanged (review.py:554-568). The review UI is a real diff: review.py:937-955 renders page.change, body_diff, semantic/claims JSON and source availability with links to retained originals; review.py:705-778 renders exact Claim quotes, anchors, conflicts, merge implications. Agents discover existing knowledge first via app.py:326-362. Enrichment is bounded and separate: enrichment.py:92-162 selects 1-20 admitted internal pages, exposes exact markdown + registry bindings, external lookup disabled.
GAPS: (1) The agent must hand-author OKF frontmatter, Claims and evidence anchors against a Control File ontology it cannot read through the API — no tool exposes ontology, Entity IDs or admissible predicates. (2) The published KB is text-only through the workspace: no tool lists pages/entities or traverses the Claim graph; lumio_wiki.mcp_server has related/paths/hot/index/graph (mcp_server.py:336-409) but the workspace never imports it. (3) Nothing generates claims from a document; enrichment is agent-authored markdown only.
```

## AREA 3: Agent consumption
```
AREA: Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE: The Pi extension is real and dependency-free: index.ts:57-137 registers the Streamable HTTP MCP server at ${url}/mcp with a Bearer placeholder; index.ts:138-256 adds /workspace-upload, /workspace and a model-allowlist guard (blocks reads for non-allowlisted provider/model; aborts provider requests carrying retained workspace material). Governance status is truthful: query.py:476 "governed": True for governed metrics, query.py:1448 "governed": False + persistence not_saved for ad-hoc define_metric, query.py:415 lists available metrics on an unknown name. Refusals are actionable (query.py:415, analytics.py:180-196, sql_authority.py:76-80). The agent-only-prepares boundary is stated at index.ts:230-252, SKILL.md:641-659.
GAPS: (1) No LanceDB/vector search reachable: lumio-workspace declares no lumio-lancedb dependency; app.py:346-362 search_knowledge calls resolved.search_pages → page_search.py:82-168, a lexical ranker over title/alias/tag/summary/body. Vector search exists (lumio-lancedb/index.py) but is never wired into the managed workspace. (2) No metric discovery, no term resolution — both exist in ariadne/serve.py:530-932 for standalone ariadne-serve; the workspace reimplements a narrower surface. (3) No entity/Claim/ontology/graph retrieval. (4) clients/pi-workspace/README.md and howto-pi-agent.md:18-22 concede LUMIO_WORKSPACE_API_TOKEN is exposed to the model via Pi's inherited shell env — a live, documented secret-isolation gap. (5) Setup: 28 LUMIO_WORKSPACE_* exports across two how-tos plus a source-bindings JSON, a private profile JSON, a control file and two Git repos.
```

## AREA 4: Collaboration model
```
AREA: Collaboration model
VERDICT: WORKS
EVIDENCE: Browser session and agent token are distinct credentials: state.py:321-339 authenticates a purpose-bound credential; LocalTokenVerifier (auth.py:81-97) accepts only purpose="api", browser login (app.py:846-891) only purpose="browser". No MCP tool can decide a review — the 10 tools (app.py:315-604) stop at prepare; the decision path is review.py:366-426, reachable only from the same-origin form POST (app.py:706-750: HTTPS + exact Origin + form body) and requiring permits(...,"review"). Replay is blocked by start_review_action (state.py:568-594: UPDATE ... WHERE decision='' AND status='issued' AND binding_json=?). Single-person self-approval is browser-only and only if is_single_person_workspace (state.py:622-628) and the reviewer holds "contribute" (review.py:389-403). Revocation is immediate: state.revoke deletes the membership row (state.py:356-364) and every request re-checks permits (app.py:308, 369, 383); browser sessions are revalidated against the live credential (state.py:205-226). Backup copies state/private/authoring-repo/published/profile/registry/artifacts plus analytics project and bindings (operations.py:110-156); restore deletes review_actions in ('issued','pending') and all browser_sessions (operations.py:186-190).
GAPS: (1) No notification: a pending review exists only as a review_url string handed to the agent (analytics.py:446, contributions.py:751) — no queue, webhook or /reviews index. (2) No audit-trail read surface: operations and review_actions record who approved what (state.py:144-159) but nothing exposes it. (3) The state machine leaks ~8 free-form status strings across three files.
```

## AREA 5: Operational simplicity
```
AREA: Operational simplicity
VERDICT: DOES NOT WORK (the "maximally simple" claim)
EVIDENCE: Processes: 1 (single ASGI app, app.py:918-928) — honest. Stores: 1 SQLite (state.py:75-180, 7 tables) + 2 Git repos (authoring KB + separate analytics project, operations.py:52-58, 134-142) + in-process DuckDB (query.py:220-231) + published tree + private profile JSON + source bindings JSON + control file. Packages: 4 workspace wheels + ariadne-agent + a TS Pi extension. Tracked Python: 214,680 lines / 807 files; lumio-wiki alone 106,309 lines, incl. a 10,629-line cli.py; the workspace service itself is 12,439 lines.
GAPS: (1) Goal said one Git repo; there are two, each with its own worktree/admission machinery. (2) Goal said LanceDB for retrieval; unreachable from the workspace (Area 3). (3) ~15 env vars for a full deployment. (4) 214k lines for 10 workspace tools is disproportionate. (5) ariadne-agent (1,790 src lines, tau-ai/tau-mcp deps) is referenced only by its own tests — dead weight here. (6) No health/readiness endpoint on the deployed service, while ariadne/serve.py:1181-1185 has both. (7) No rate limiting, quotas, request metrics or structured logging.
```

## MISSING
- Pending-review inbox/notifications: work visible only via an agent-supplied URL (analytics.py:446) [blocker]
- Audit-trail read API: approvals stored (state.py:144-159), never queryable [major]
- Metric/dataset discovery in the workspace: no list_metrics/list_datasets/search_context/resolve_term (app.py:315-604) [major]
- Vector/semantic retrieval: lexical only; LanceDB never imported by lumio-workspace [major]
- Entity/Claim/ontology/graph traversal for agents (exists in mcp_server.py:336-409, unused) [major]
- Database/S3 source request via the workspace API (operator bindings only, analytics.py:101-126) [major]
- Health/readiness/metrics endpoints on the deployed service [major]
- Rate limiting, quotas, per-actor fair use [major]
- Rollback of published knowledge from the workspace (CLI-only, s3://-only, cli.py:5401) [major]
- Published version history/diff for reviewers [major]
- Multi-workspace per deployment: workspace_id is one configured value (app.py:163) though state is keyed by it [major]
- Schema/model discovery before authoring claims (ontology, Entity IDs, predicates unreadable) [major]
- Self-service user management (local-user/credential ops are CLI-only, __main__.py:53-83) [minor]
- Full-text search beyond page-level lexical (hard limit 20, app.py:349) [minor]
- Data visualization of governed results [minor]
- Scheduled refresh of live sources [minor]
- Export of published knowledge from the workspace [minor]
- Reviewer pending-task list [minor]
- Localization/i18n of the review UI [minor]

## OVER-COMPLICATED
- Four-stage review ladder: 2 source stages (analytics.py:433-434, 741-775) + 2 contribution stages (analytics.py:1008-1022) per CSV→metric journey. Bundle identity+grant into one decision per artifact.
- Review-action binding machinery: one-use digests + generations + binding_json equality + 3-state lifecycle (state.py:543-610, review.py:389-426) for single-server SQLite. UPDATE ... WHERE status='pending' plus a random token column gives the same replay protection in ~20 lines, not ~90.
- The workspace reimplements ariadne's MCP facade: 10 thin tools over QueryRuntime vs ariadne/serve.py's 30+ (discover, list_metrics, search_context, resolve_term, get_metric, define_metric...). Mount that facade behind the workspace's auth instead; otherwise the two drift.
- Enrichment impact projection (enrichment.py:38-84) plus per-page Claim rendering with anchors/conflicts (review.py:587-778, ~190 lines) for a feature whose selection is "up to 20 pages, agent re-authors them".
- XLSX importer defensive core (spreadsheet_import.py:225-453, ~230 lines) reimplements OOXML cell-order/dimension validation to refuse workbooks openpyxl would misread; a fail-closed subset check suffices for a derived analytics table.
- Two Git repos + two admission models (Lumio authoring vs Ariadne overall). One repo with two subtrees would delete the worktree-relink and dual-backup code (operations.py:159-183, 229-236).
- ~8 free-form status strings plus reconciliation code (review.py:428-510, analytics.py:1046-1130) that exists because states are strings, not a small enum with legal transitions.
- Separate ariadne-agent package: a second MCP stack (tau-mcp) beside the official mcp SDK, unreferenced by the workspace.
- 10,629-line lumio_wiki/cli.py and 5,646-line knowledge_base.py: per-command-family modules would not add lines and would make this readable.
- Client-side model-allowlist guard (index.ts 57-137, 200-259) plus a 19KB test, where the server already knows the token's capability.

## OVERALL
OVERALL: PARTIALLY ACHIEVED
SUMMARY: The human-agent boundary — the hardest, most safety-critical requirement — is genuinely built: purpose-bound credentials, a browser-only decision path, one-use action bindings, separated source/grant stages and approval-invalidating restore all survive code reading (auth.py:75-97, state.py:321-339/543-610, review.py:366-426, operations.py:186-190). The data pipeline really compiles gated SQL and really pins results. But the platform is not yet a daily workplace for an agent: the workspace is a 10-tool sliver of a 30-tool library, so it cannot list metrics, resolve terms or read the knowledge graph; vector search is declared but unreachable; database/S3 sources need operator-provisioned bindings; one CSV-to-metric journey costs four human browser decisions. "Maximally simple" is not met.
BIGGEST_GAP: The workspace MCP surface is a strict subset of ariadne's own facade, so an agent connected to the managed workspace cannot discover what it may query and cannot read the knowledge graph at all — though the library already implements both (ariadne/serve.py:530-932, lumio_wiki/mcp_server.py:336-409).
SIMPLICITY_AUDIT: The claim does not hold. Processes: 1 (honest). Stateful roots: 8+ (SQLite, 2 Git repos, DuckDB, published tree, 3 JSON configs, control file) vs the 5 claimed. Env vars: ~15. Packages: 4 wheels + 1 agent distribution + 1 TS extension. LOC: 214,680 tracked Python lines for a 12,439-line service. The commit stream is dense, so the bloat is structural, not accidental.
TOP_3_SIMPLIFICATIONS: (1) Mount ariadne's existing MCP facade (serve.py) behind the workspace's auth instead of maintaining a parallel 10-tool layer — instantly restores discovery, term resolution, contract inspection and truthful governance labels, and deletes duplication. (2) Collapse the four-stage review ladder to one human decision per artifact, removing ~150 lines of stage/reconcile code and halving reviewer clicks. (3) Delete the second Git repository and second admission model (one repo, two subtrees), removing the worktree-relink and dual-backup/restore machinery in operations.py.
MISSING_COUNT: 19
