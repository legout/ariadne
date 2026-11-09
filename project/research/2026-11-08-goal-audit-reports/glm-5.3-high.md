# Independent Goal Audit — model glm-5.3 (static inspection only)

## AREA: 1 Data pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Upload path is real: bounded exact-byte stream (`app.py:606-640`, `intake.py:66-74` 25 MiB cap), sha256-addressed persistence (`intake.py:79-122`), structured staging for csv/json/parquet/xlsx (`intake.py:133-150`). XLSX→DuckDB conversion with explicit sheet selection and identity re-verification (`analytics.py:198-292`). Profiling and query run through the real ariadne Core: sqlglot-compiled models, single-statement guard, EXPLAIN bind, live grain audit, row/cell budgets, `governed: True` + pinned admission (`query.py:392-499`). Two-stage browser approval exists: source approval then per-caller data grant (`analytics.py:735-775`), grant re-checked on every profile/query (`analytics.py:170-196,470-509,511-560`).
GAPS: (a) DB/S3 sources (SQLite/DuckDB/Postgres/S3) cannot be requested by an agent at all — only operator-prewritten handles in a JSON bindings file are honored (`analytics.py:101-126`). (b) First governed query needs an already-admitted metric catalog; authoring a new metric requires upload → prepare_data_source → 2 browser approvals → prepare_contribution → 2 more browser approvals (submission + publication, `analytics.py:735-874`) = ~9 steps; "bureaucracy" applies. (c) Two distinct browser approvals (source identity + data grant) before profiling even one CSV. (d) `asyncio.run` inside a sync MCP tool (`analytics.py:549-551`) works only because the SDK runs sync tools in a thread — fragile. (e) Error messages are genuinely actionable (error codes + recovery hints throughout, e.g. `analytics.py:113-116`).

## AREA: 2 Knowledge pipeline
VERDICT: PARTIALLY WORKS
EVIDENCE: Real extraction of txt/md/pdf/docx to normalized text with bounds disclosure (`authoring_journey.py:143-200`, documents extra in `lumio-wiki/pyproject.toml`). Candidate prep in an isolated git worktree per task with server-selected base, retry-idempotent operations (`contributions.py:196-341,647-756`), full-candidate validation before any write, rollback on failure (`authoring_journey.py:480-560`). Browser review shows exact base/candidate trees, per-page body diffs, source support with retained-original status, claim evidence quotes, conflict candidates (`review.py:124-299,571-774`, `templates/review.html`). Publication is CAS-guarded (`expected_current`) and pointer-activated (`publication.py:58-73`); reject/request_changes only update operation status — published state untouched (`review.py:554-568`). Readers see new content immediately via the moved pointer (`location.py:556`, `knowledge_base.py:601-614`). Enrichment is bounded (20 pages / 200k chars / 40 claims, `enrichment.py:15,113-117,248-253`).
GAPS: (a) No automatic PDF/DOCX→structured-pages conversion: the system extracts text and retains the original; the agent hand-authors Markdown pages with frontmatter ("No distiller runs", `authoring_journey.py:158`). The "→ structured pages" step is the agent's job, not the platform's. (b) Rich-text diff exists but reviewer-facing pages lean heavily on digests/trees; a non-expert must trust machinery they cannot verify. (c) Discovery before proposing exists (search/read tools) but there is no page-listing tool — only search by query (`app.py:327-362`).

## AREA: 3 Agent consumption
VERDICT: PARTIALLY WORKS
EVIDENCE: Pi extension is real: MCP registration for local-token and Entra OAuth, model allow-list policy, disclosure taint surviving compaction/tree-summary, upload command with retry keys (`pi-workspace/index.ts:28-210`); CI runs it against installed `pi-coding-agent@1.5.0` (`.github/workflows/ci.yml:37-48`). Server side exposes workspace_status/read_knowledge/search_knowledge/read_source_material/prepare_*/get_task/query_data (`app.py:315-604`). Governance status is truthful: governed results carry pinned commit + source digest (`query.py:470-485`, `analytics.py:554-560`); ad-hoc `define_metric` is compile-gated too (`query.py:1359,1465`). Unauthorized access fails closed: every tool re-checks `state.permits` per call.
GAPS: (a) Search is lexical only — LanceDB exists as a separate wheel (`lumio-lancedb`, 2034 lines) but `lumio-workspace` declares no dependency on it (pyproject.toml deps: lumio-wiki/mcp/authlib/httpx/starlette/uvicorn only); no vector path is wired into the workspace. (b) The ariadne SKILL.md is 765 lines — thorough but a wall of prose; an agent is productive only after significant reading. (c) No live qualification: the docs themselves state live interop "remains blocked" pending real users/HTTPS/Pi install (`howto-shared-workspace.md` header) — everything verified here is code + synthetic tests. (d) Agent must track retry keys, task_id vs upload_id distinctions — usable but cognitively heavy (`index.ts:190-205` guidance text is a paragraph of warnings).

## AREA: 4 Collaboration model
VERDICT: WORKS (as far as code can show)
EVIDENCE: MCP tool surface contains no approve/publish tool (`app.py:315-604`); decisions only via browser POST `/review/{task_id}` requiring session actor, HTTPS scheme, same-origin, form-encoded body ≤8 KiB (`app.py:706-750`). Self-approval allowed only for single-person workspaces with contribute capability (`review.py:390-403`). Revocation is immediate: capabilities read from SQLite per request (`state.py:677-687`); local-credential sessions re-validated against enabled/expiry on load (`state.py:205-226`). Replay protection: one-use `action_digest` bound to exact candidate binding (`state.py:568-594`, `review.py:404-414`); crash recovery reconciles receipts before reuse (`review.py:428-509`). Backup holds the same mutation locks as activation; restore deletes issued/pending review actions and all browser sessions (`operations.py:110-156,186-190`). API vs browser credentials are purpose-separated (`state.py:293,321-339`). Secrets: token hashes only (sha256, `state.py:61-62`); no hardcoded endpoints/keys in workspace source.
GAPS: (a) HTTPS enforcement keys off `request.url.scheme` (`app.py:654,714,761,791,861`) — correct only behind a proxy with uvicorn proxy-headers correctly configured; misconfiguration silently degrades to 403s. (b) `setup_previews` is in-memory (`app.py:279`) — lost on restart (minor). (c) Reviewer UX: one review surface, but digest-heavy; non-technical humans can approve but not deeply verify.

## AREA: 5 Operational simplicity
VERDICT: PARTIALLY WORKS ("maximally simple" does not hold)
EVIDENCE: One process: `lumio-workspace serve` → uvicorn (`__main__.py:41,86-87`). One SQLite operational store (`state.py:76-183`) with lazy migrations. Stores actually involved: SQLite, authoring Git repo, filesystem published destination, private roots (uploads/originals/worktrees/controls), DuckDB (analytics project), optional separate registry/artifact dirs; LanceDB not used by the service. Minimal read-only deployment: 5 env vars; authoring adds 4; analytics adds 3 (+ operator bindings JSON + private profile JSON); Entra adds 6; Pi client adds 4+ (`app.py:161-181`, `howto-shared-workspace.md`). User provisioning is CLI-only (`__main__.py:53-118`).
GAPS: Full deployment = 12 service env vars, 2 hand-written config files, 5 packages (ariadne-data, lumio-wiki, lumio-lancedb, lumio-workspace, pi-workspace client), 98k source lines (35k Core + 55k wiki + 2k lancedb + 6.2k workspace) — plus 214,680 tracked Python lines repo-wide including tests. lumio-wiki ships large surfaces the workspace never touches (s3_publish, okf, graph_exchange, embeddings, distiller, mcp_server, evals). Dead-weight ratio is high relative to the delivered function.

## MISSING
- Multi-workspace/multi-tenancy per deployment: one `workspace_id` per process (`app.py:164`) — blocker for teams with several spaces
- Any user lifecycle beyond CLI (self-registration, password reset, UI user creation): membership page manages grants only; user creation is CLI (`__main__.py:99-103`) — major
- Health/readiness endpoint: none in `app.py` routes — major for ops
- Monitoring/metrics/alerting: nothing emits any operational signal — major
- Per-caller rate limiting/quotas: only row/cell/time budgets per query (`query.py:380-390`) — major
- Rollback or version-diff UI for published knowledge: version pinning exists (`app.py:168`), no rollback operation — major
- Full-text/passage-level search: page-level lexical only (`knowledge_base.py:601-614`) — major
- Vector search wired into the workspace: LanceDB package unused by service — major
- Reviewer notifications (how does a human know a task waits?): none; polling get_task only — major
- OpenAPI/API documentation: all custom routes `include_in_schema=False` — minor
- Clients beyond Pi (VS Code, web UI, mobile): none — minor
- Data visualization without writing SQL: none — minor
- Scheduled/automated refresh of live DB/S3 sources: none; sources are point-in-time uploads — major
- Audit-trail read API/UI: `review_actions`/`operations` tables exist but no query surface for history — minor
- Export of knowledge to other formats beyond OKF exchange: partial only — minor
- Localization: none — minor
- Listing of pending tasks for a reviewer/agent: get_task requires knowing the id (`app.py:584-604`) — minor
- Source deletion/retirement workflow: no tool retires a registered source — minor

## OVER-COMPLICATED
- Review-action nonces + draft generations + dual digests + CAS responses (`state.py:366-641`, `contributions.py:536-578`): defensible correctness, but on a single-process SQLite server a single `review_actions` row with the task row would do; three layers of digest binding could halve
- `analytics.py` (1130 lines): one class mixing grant state machine, git orchestration, publication recovery, and review rendering — split or halve
- The 4-stage data pipeline (pending_source_approval → pending_data_grant → data_granted → submission → publication, `analytics.py:431-468,735-874`): two browser approvals per source set and two per contribution; one approval binding source+grant would remove ~2 round trips and a stage machine
- Hand-rolled XLSX XML parser (`spreadsheet_import.py`, 769 lines): openpyxl is a standard wheel; refusing shared formulas and hand-validating cell order re-implements a library — replace
- Package ceremony: 5 packages + root coordination tests + per-member suites + integration suites + 3 CI jobs (`ci.yml`, `tests/test_workspace_layout.py`) for a product that deploys as one process — merge lumio-lancedb into lumio-wiki extra, fold root tests
- Spec/ADR/issue references inside nearly every comment block (e.g. `query.py:437-495`): an audit trail living in comments inflates every file ~15-20%
- Duplicated `_digest`/`_git` helpers with cross-module private imports (`analytics.py:38` imports `_digest, _git` from `contributions`) — one util module
- lumio-wiki's unused-by-workspace surfaces (s3_*, okf, embeddings, distiller, graph_exchange) shipped in the same dependency as the workspace's foundation

## OVERALL: PARTIALLY ACHIEVED
SUMMARY: The governed-review core genuinely works as code: agent-prepared, browser-only-approvable, CAS-published knowledge and data with truthful governance provenance and a real Pi client. But the data path is only half-real (DB/S3 sources are operator-side config, not agent-requestable), PDF/DOCX are extracted, never structured into pages, vector search is unwired, and nothing has been live-qualified — the project's own docs state live interop is blocked.
BIGGEST_GAP: First-query friction — an agent cannot get a new dataset queryable end-to-end without ~9 steps, four separate browser approvals, and an operator-authored bindings file for anything not uploaded as a file.
SIMPLICITY_AUDIT: No — one process and one SQLite store is real, but 12 env vars, 2 hand-written config files, 5 packages, ~98k source lines (215k repo-wide), and 6 distinct storage mechanisms contradict "maximally simple".
TOP_3_SIMPLIFICATIONS: (1) collapse source-approval + data-grant into one browser approval; (2) replace the hand-rolled XLSX XML parser with openpyxl; (3) fold lumio-lancedb and the unused wiki surfaces out of the workspace's dependency closure.
MISSING_COUNT: 18
