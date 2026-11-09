# Ariadne-Lumio Unbiased Goal Audit

**Scope note:** I read implementation code only. I did not read plans, specs, ADRs, or the issue tracker (except where the code itself quotes them). Three parallel read-only deep-dives (data pipeline, knowledge pipeline, operational simplicity/agent consumption) were run and their findings independently re-verified against the source by me before inclusion.

---

## AREA: 1 — Data pipeline (can an agent actually get data queryable?)

**VERDICT: PARTIALLY WORKS**

**EVIDENCE**

The path exists and is connected end-to-end, and the *hard* parts (compile gate, injection safety, governance labelling) are genuinely implemented:

- Upload: `app.py:607` (`POST /uploads`, octet-stream, 25 MiB cap at `intake.py:65-73`), exact-byte + SHA-256 receipt.
- Stage: `app.py:437` → `analytics.py:294` `prepare_data_source` → returns `task_id` + `review_url`.
- Profile: `app.py:465` → `analytics.py:470` → `authoring_sources.inputs` → `profiler.profile` (`profiler.py:229-305, 475-516`) — real DuckDB catalog discovery + `SUMMARIZE` stats + low-cardinality values. Not a stub.
- Query: `app.py:476` → `analytics.py:511` → `QueryRuntime`.
- **Compile gate is real:** `query.py:440-467` — `render(model, …)` compiles from the served OSI model (never tool input), `assert_single_statement(sql)`, `EXPLAIN` bind check, live grain guard. Ad-hoc `define_metric` additionally parses both dialects, rejects side effects, restricts functions/relations (`query.py:1375-1438`, `sql_authority.py:390-495`).
- **Governance status reaches the agent:** `governed: true` (`query.py:476`) vs `governed: false` (`query.py:1264, 1448`), plus workspace `pinned: {commit, source_digest}` (`analytics.py:550-558`).
- **Human approval is real:** `/review/{task_id}` (`app.py:707`) takes its actor from a browser session only; approval of a source records native Source Approval (`analytics.py:744-760`).

**GAPS**

1. **The flow is bureaucracy, not a pipeline.** CSV → governed metric costs **5 agent calls + 4 human browser decisions (8 HTTP requests)**: upload → `prepare_data_source` → *approve #1 (source identity)* → *approve #2 (data grant)* → `profile_data_source` → `prepare_contribution` → *approve #3 (submission/validation)* → *approve #4 (publication/admission)* → `query_data`. The double source approval is structural: `analytics.py:744` moves `source_approval → data_grant`, and `analytics.py:761` moves `data_grant → data_granted`. This fails the stated "<5 steps" test outright.
2. **A freshly uploaded source is not queryable.** `query_data` resolves the *project's admitted record* (`analytics.py:511-520`), so the agent must author a metric, get it reviewed, and get it admitted before any query returns. There is no "profile then answer" path.
3. **No discovery surface.** `workspace_status` (`app.py:316-324`) does not expose the analytics project handle, source handles, metric names, or dataset names. The agent must obtain the project handle out of band (`analytics.py:93-95` refuses without revealing it) and source handles from an operator binding file (`analytics.py:101-118`). Ariadne's own `list_metrics`/`discover`/`list_datasets` exist (`query.py:248-289`, `discovery.py:437-480`) but are **not dispatched** by the workspace (`analytics.py:526-545`). An agent cannot find a metric by asking.
4. **Profiling ignores the declared bounds.** `authoring_inputs.py:36-44` declares row/time/byte ceilings; the workspace path passes a hard-coded `sample_rows=100` (`analytics.py:481-486`) straight into `profiler.profile`, which builds `DuckDBExecution(reg)` with no deadline (`authoring_sources.py:549-557`, `execution.py:162-184`) and profiles every discovered column. No row, time, byte, or column cap on the profile path.
5. **XLSX opens data before approval.** `analytics.py:207-218` imports the workbook (reads selected cells) during `prepare_data_source`, i.e. *before* the browser source approval that the CSV path defers until after approval.
6. **Error messages are mixed.** Actionable: *"XLSX requires an explicit nonempty sheet selection"* (`analytics.py:336`), *"source handle … has no operator binding; ask the owner to provision the exact source before retrying"* (`analytics.py:113-116`). Unactionable: *"unknown analytics project handle; use the configured project"* (`analytics.py:95` — does not name it), *"workspace access is not available"* (`app.py:208`), *"upload is not available"* (`intake.py:124`).
7. **10 environment variables** before any data query works: `LUMIO_WORKSPACE_{AUTH_MODE,ID,EXTERNAL_URL,PUBLISHED_PATH,STATE_PATH}` (unconditional, `app.py:163-169`) + `{AUTHORING_PATH,PRIVATE_PROFILE,ANALYTICS_PROJECT_ID,ANALYTICS_PROJECT_PATH,ANALYTICS_SOURCE_BINDINGS}` (required as a group by `analytics_service`, `app.py:364-393`). Entra adds 6 more (`auth.py:39-50`).

---

## AREA: 2 — Knowledge pipeline (can an agent author and publish knowledge?)

**VERDICT: PARTIALLY WORKS**

**EVIDENCE**

- **Parsing is real and wired to the workspace**, not CLI-only: `intake.py:152-180` → `lumio_wiki.authoring_journey.extract_source`; PDF → LiteParse, DOCX → AnyDoc (`source_processor.py:176-187, 341-380`). An agent with HTTPS access can submit a PDF end-to-end.
- **The page model is real**: title, `id` (entity ID), `entity_types`, `aliases`, `tags`, `summary`, lifecycle, visibility, `sources`, `claims`, optional `ariadne_profile.ontology_refs` (`records.py:355-381`), validated at `knowledge_base.py:2963-2998`.
- **Enrichment chain is real**: `prepare_enrichment` (`app.py:494` → `enrichment.py:164-214`) selects exact admitted pages and discloses their full Markdown + control; `prepare_contribution(enrichment_task_id=…)` (`app.py:518-540`) authors the candidate; review and publication machinery are shared with the ordinary path.
- **The review diff is real**: `difflib.unified_diff` on the Markdown body (`authoring_review.py:474-479`), rendered under a literal *"Content diff"* heading with semantic/claim JSON beside it (`review.py:896-1016`, `templates/review.html`).
- **Rejection leaves published state unchanged**: publication is called *only* in the approve branch (`review.py:511-568`); reject/request-changes just rewrites the operation status (`review.py:552-568`).
- Steps for one PDF: 1 HTTP upload + 3 MCP calls + 1 browser decision. That part is acceptable.

**GAPS**

1. **The parser does not produce pages — the agent does.** `extract_source` returns text + sections; it emits no title, tags, entity types, or ontology refs. Those come entirely from agent-authored Markdown frontmatter (`contributions.py:76-109` requires `visibility: internal` and the `knowledge-artifact` entity type). "Parsed to structured pages with frontmatter" is agent labour, not pipeline behaviour.
2. **Enrichment is practically unusable through the workspace API.** `prepare_enrichment` demands `page_ids` — *entity IDs* (`enrichment.py:126`). But `read_knowledge` (`app.py:327-345`) returns `page.body`, and `page.body` **excludes the frontmatter** where `id:` lives (`knowledge_base.py:2975-2982`); `search_knowledge` (`app.py:347-361`) returns title/path/snippet only. Neither returns the entity ID, and `knowledge_base.entity_id_for_title` (`knowledge_base.py:707`) is not exposed. The agent cannot obtain the input the enrichment API requires.
3. **Binary originals cannot be inspected in the browser.** `review.py:331-364` does `raw.decode("utf-8")` and maps `UnicodeDecodeError` to `source_unavailable`. A retained PDF or DOCX original therefore *always* fails the "Source Inspection" link the review page offers (`review.py:908-937`). The enrichment passage renderer repeats the same assumption (`review.py:615-636`). The reviewer is shown a link that cannot work for the two binary formats the platform advertises.
4. **The reviewer UI is unstyled and expert-facing.** No CSS anywhere (`templates/review.html` is 68 lines of bare HTML). For analytics candidates the whole knowledge diff is a raw JSON `<pre>` dump (`review.py:837-893`), and the page leads with `native_base`, `submission_review`, `authoring_review`, `publication_review` digests and `expected`/`observed` version pairs. A non-technical human cannot review this unaided.
5. **No upload MCP tool.** `POST /uploads` is an HTTP route (`app.py:607`), not an MCP tool. The Pi extension bridges it with a slash command; a pure MCP client cannot upload anything.
6. **Enrichment and metric edits cannot share one candidate.** The enrichment branch explicitly rejects `core_edits`/`source_task_id` (`app.py:541-548`); analytics candidates use a different path (`analytics.py:876`). The "complete diff (knowledge + any metric changes)" is shown for analytics candidates but not reachable from an enrichment candidate.
7. **Rejection leaves private residue.** Source versions and retained originals are registered *before* review (`authoring_journey.py:729-745`, `contributions.py:703-710`); rejection does not undo them, and registry-latest comparisons then feed later impact projections (`enrichment.py:38-55`).
8. **"Immediately readable" has an exception**: a pinned reader (`LUMIO_WORKSPACE_PUBLISHED_VERSION`) keeps serving the old version after publication (`app.py:168, 280`).

---

## AREA: 3 — Agent consumption (can an agent actually use this daily?)

**VERDICT: PARTIALLY WORKS**

**EVIDENCE**

- The Pi extension is real: it registers the Streamable-HTTP MCP server in `local-token` or `entra` mode (`index.ts:57-77`), enforces a model allowlist before every call (`index.ts:129-136`), aborts outbound provider requests carrying retained workspace history to a disallowed model (`index.ts:117-127`), and provides `/workspace-upload` for exact bytes (`index.ts:138-210`). CI actually runs the disclosure-boundary test against the installed Pi runtime (`.github/workflows/ci.yml`, "Pi workspace client disclosure guard").
- Knowledge search returns bounded, citation-ready passages with title/path/published version (`app.py:347-361`).
- Governance status reaches the agent for metrics (`governed: true/false` + `pinned`).

**GAPS**

1. **LanceDB vector search is NOT in the agent path.** `search_knowledge` → `ResolvedKnowledgeBase.search_pages` → `search_pages_over` → *"deterministic lexical ranking"* (`knowledge_base.py:601-616`, `page_search.py:19-25, 79-138`). `lumio-lancedb` is **never imported** by `lumio-workspace` and is **not even a dependency** of it (`lumio-workspace/pyproject.toml`). LanceDB exists only as a standalone optional backend inside the `lumio-wiki` CLI (`cli.py:656-695, 2414-2417`). The stated "LanceDB for retrieval" served to agents **does not exist**.
2. **The extension has never been live-qualified.** The project's own how-to states live interoperability is **blocked** and §9 is *"a recipe, not evidence that the leg ran"* (`products/lumio/docs/howto-shared-workspace.md:3-7, 204+`), and the PDF/DOCX upload-to-review journey "remains W6". The code path exists and CI tests the disclosure boundary; no real HTTPS + two humans + installed Pi run has ever happened.
3. **The API token is exposed to the model by design.** The client README and how-to record this as an *accepted, unresolved* risk: Pi's environment is inherited by the shell, so a model-callable tool can exfiltrate `LUMIO_WORKSPACE_API_TOKEN` into output/history. Accepted risk, not a fix.
4. **`LUMIO_WORKSPACE_ALLOWED_MODELS` silently blocks everything if unset.** The set is empty when the var is missing, `modelAllowed` is then false, and `pi.on("tool_call")` blocks every workspace call (`index.ts:34-39, 129-136`). A new install must know the exact `provider/model` string or the agent appears broken.
5. **The shipped skill documents the wrong surface.** `ariadne-data/src/ariadne/skill_assets/SKILL.md` is 765 lines about the **standalone `ariadne` CLI** (`--project DIR`, `ariadne list-metrics`, `ariadne get-metric …`). There is **no skill for the workspace MCP API** — which is the surface an agent actually talks to. The "productive in under 10 minutes" claim is unverified and the document does not target the agent's real API.
6. **Knowledge read/search responses carry no governance field.** `read_knowledge`/`search_knowledge` return title/body/citation only — no visibility, lifecycle, or governance status (`app.py:327-361`).
7. **Discovery is absent**, as in Area 1: no metric/dataset/source listing over MCP.

---

## AREA: 4 — Collaboration model (does the human-agent boundary hold?)

**VERDICT: WORKS** (with real UX and audit gaps)

**EVIDENCE — the boundary genuinely holds**

- **An agent token cannot approve.** Approval is reachable only through `POST /review/{task_id}`, whose actor comes from `_browser_actor(request)` (`app.py:707-730`, `review.py:366-372`). A browser session is created only by `/auth/login`, which authenticates with `purpose="browser"` (`app.py:847-892`); `authenticate_local_credential` rejects a purpose mismatch (`state.py:321-340`), so an `api` credential cannot be replayed as a browser credential. The MCP tool surface contains **no** approve/publish tool (`app.py:316-604`).
- **Single-person self-approval exists but only in the browser.** `review.py:388-402` allows actor == submitter only when `is_single_person_workspace` (`state.py:622-628`, exactly one member) *and* the actor holds `contribute`.
- **Review actions are one-use.** `issue_review_action` → `start_review_action` is a compare-and-swap on `(digest, workspace, task, actor, binding, decision='' AND status='issued')` (`state.py:543-594`); a replayed digest returns `action_replay`.
- **Revocation takes effect immediately.** `revoke` deletes the membership row (`state.py:356-364`); every route and tool re-checks `state.permits` (`state.py:686`). `disable_local_user` invalidates the API credential *and* every browser session, because both paths JOIN `local_users ... enabled = 1` (`state.py:185-215, 282-289`).
- **Backup/restore preserves admitted content and invalidates outstanding reviews.** `operations.py:quiesced_backup` copies state.sqlite3, the private tree, the authoring Git repo, the published tree, the private profile, the source registry, the artifact store, and (optionally) the analytics project + bindings under the same mutation locks an activation takes. `restore()` re-links worktrees, rebases the profile paths, and `_invalidate_restored_actions` deletes every `issued`/`pending` review action **and all browser sessions**.
- **No agent bypass path found.** `define_metric` / `query_records` are explicitly `governed: false` with `persistence: {status: not_saved}` (`query.py:1444-1454`); publication only runs in the approve branch (`review.py:511-568`).

**GAPS**

1. **No review queue.** A reviewer must be handed a `review_url` out of band (`analytics.py:452`, `contributions.py`). There is no list of pending reviews, no dashboard, no "what is waiting for me" page — anywhere in the 7 browser routes (`app.py:607-928`).
2. **No notifications at all.** No email, webhook, or polling signal when a task enters `pending_review`. Combined with (1), a reviewer only finds out by being told.
3. **The membership page cannot create users.** It only grants/revokes `read`/`contribute`/`review` (`app.py:777-845`, `_MEMBERSHIP_CAPABILITIES` at `app.py:47`); `state.grant` refuses unknown local users (`state.py:344-352`), so `local-user create` must happen on the CLI first. `setup` and `inspect_source` are CLI-only capabilities that the browser cannot grant at all.
4. **No health/readiness endpoint and no metrics.** The workspace has zero `/healthz`, `/readyz`, or `/metrics` routes — although the *Ariadne* server does have `/readyz` (`products/ariadne/deploy/compose.yaml` healthcheck). The workspace, which is the actual deployment unit, has none.
5. **No rollback in the workspace.** `preview_rollback` / `rollback_publication` exist in the standalone `lumio-wiki` CLI (`lumio_wiki/__init__.py:379`, `cli.py:5444`) but are **not exposed** by the workspace server or MCP tools. A bad publication can only be undone by an operator running a different CLI against the same Git repo.
6. **No audit-trail query surface.** `operations` and `review_actions` tables record actor/timestamp/decision (`state.py:127-183`), but there is no endpoint, tool, or CLI that reads them. "Who approved what, when" is answerable only by opening SQLite.
7. **Restore does not honour its own docstring.** `operations.py` claims *"Credentials are re-established through the operator's secret mechanism"*, but the copied `state.sqlite3` preserves credential hashes — existing API and browser tokens keep working across a restore.
8. **Failure ≠ nothing published.** Publication writes immutable data and a receipt *before* flipping the pointer (`git_authoring.py:2251-2286`); a failure after the pointer write can leave the candidate published despite an error response. Reconciliation exists (`review.py:428-509`) but an error response must not be read as "nothing happened".

---

## AREA: 5 — Operational simplicity (is it actually "maximally simple"?)

**VERDICT: DOES NOT HOLD**

**EVIDENCE — actual counts**

| Claim | Reality |
|---|---|
| "one server" | 1 ASGI process (`__main__.py:81-83`) **+ an operator-supplied TLS reverse proxy** (undocumented as a process, `howto-shared-workspace.md:148-154`) + the Pi client + Entra (external SaaS) if selected. The only Dockerfile/compose in the repo deploys **`ariadne-serve`**, a different service (`products/ariadne/deploy/compose.yaml`). |
| "one SQLite operational store" | 1 SQLite with **7 tables** (`state.py:81-183`): memberships, browser_sessions, local_users, local_credentials, operations, review_actions, setup_records. Plus **two filesystem trees** the claim never mentions: the published tree and the private tree (`uploads/`, `extractions/`, `worktrees/`, `controls/`, `authored/`, `activation/`, `operation-locks/`). |
| "one Git repository" | True — plus a **separate** Git repo for the analytics project plus per-task worktrees. |
| "DuckDB for data" | True — embedded, often in-memory (`execution.py:193`). |
| "LanceDB for retrieval" | **False in the deployed path.** `lumio-lancedb` is never imported by the workspace and is not a dependency of it. Installing it changes nothing for agents. |
| env vars | **5** mandatory service + **5** for analytics = **10**; Entra adds **6** (16); Pi client adds **4** (20 for the full stack). |
| packages | **5** distributions in the repo; **3** needed for workspace+analytics (`lumio-workspace`, `lumio-wiki`, `ariadne-data`); `lumio-lancedb` optional and unused by the workspace; `ariadne-agent` is a separate product with its own env and a dependency on a **local-path** `tau-mcp` (`ariadne-agent/pyproject.toml:26-30`) that a `pip install` cannot resolve. |
| console scripts | **15** (13 in `ariadne-data` alone: `ariadne`, `-ingest`, `-validate`, `-serve`, `-analyst-mcp`, `-authoring-mcp`, `-init`, `-skill`, `-profiler`, `-authoring`, `-admit`). |
| code size | **~100.5k** implementation LOC + **~94k** test LOC + **~47k** markdown. The platform itself (`lumio-workspace`) is **6.2k** LOC — 6% of the implementation. `lumio-wiki` (55k) + `ariadne-data` (35k) are libraries the workspace barely touches. |
| bootstrap | **None for the workspace.** No Dockerfile, no compose, no systemd unit, no install script. |

**GAPS**

1. **No deployment artifact for the actual product.** A competent sysadmin must hand-assemble: publish a Knowledge Base through the `lumio-wiki` CLI, create a Git authoring repo, hand-write a `profile.json`, set 10–20 env vars, create local users, grant membership, issue **two** credentials per user (api + browser), run the owner `/setup` page, and place a TLS proxy in front. Realistically **half a day**, not "maximally simple".
2. **Stale build artifact in the tree**: `products/ariadne/packages/ariadne-data/build/lib/ariadne/` — **35,094 duplicated LOC** (gitignored but physically present, doubling every naive repo scan).
3. **Two agent surfaces that overlap**: the workspace MCP server *and* `ariadne-serve`/`ariadne-analyst-mcp`/`ariadne-authoring-mcp` over stdio + HTTP (`serve.py:1399-1411`), plus the `ariadne` CLI, plus `ariadne-agent`. An agent does not need to understand which one to use; the workspace is the only one the goal describes, yet it is the least complete of the three.
4. **Dead code:** `ariadne/authoring_context.py`, `ariadne/authoring_contracts.py`, `ariadne/authoring_semantic.py` are imported nowhere.
5. **The `mcp` extra is optional in `ariadne-data` but a hard dependency of `lumio-workspace`** (`lumio-workspace/pyproject.toml`: `lumio-wiki[documents,mcp]` + `mcp>=2.2,<3`). The "optional transport" abstraction does not survive into the product that uses it.

---

## AREA: 6 — What is missing?

```
MISSING:
- Multiple workspaces per deployment: state.py keys everything by workspace_id, but there is exactly one WorkspaceConfig per process, no workspace registry, no routing, no cross-workspace query. [blocker for a team]
- Multi-tenancy / row-level isolation between workspaces in one deployment: memberships are keyed by workspace_id but the server binds one workspace. [major]
- User self-registration / password reset / SSO for non-Entra users: local users are created only by an operator CLI (`local-user create`), and Entra is explicitly "deferred". [major]
- Review queue / pending-review dashboard: no page lists what is waiting for a reviewer (only per-task URLs). [major]
- Notifications (email/webhook/polling): nothing tells a reviewer a task is waiting. [major]
- Health/readiness/metrics endpoints on the workspace server: no /healthz, /readyz, /metrics (Ariadne has /readyz; the workspace has nothing). [major]
- Rate limiting, quotas, fair-use: no throttling anywhere; a single agent can loop prepare_contribution indefinitely. [major]
- Audit trail query surface: operations/review_actions tables record who/what/when but nothing reads them. [major]
- Rollback of a published release in the workspace: exists only in the standalone lumio-wiki CLI, not in the server/MCP surface. [major]
- Metric / dataset / source discovery over MCP: list_metrics, discover, list_datasets exist in ariadne-data but are not dispatched by the workspace. [major]
- Entity-ID exposure in read/search responses: read_knowledge returns body-without-frontmatter, so prepare_enrichment's required page_ids are unobtainable. [major]
- Binary original inspection in the review UI: inspect_source decodes UTF-8, so PDF/DOCX originals always fail. [major]
- Workspace-specific agent skill: the shipped SKILL.md documents the standalone CLI, not the workspace MCP API. [major]
- Full-text search across all published content (body-wide, not page-level snippet ranking): search_pages_over is title/alias/tag/summary/body-token lexical matching, not a real inverted index. [minor]
- LanceDB/vector retrieval wired into the workspace: the stated retrieval stack is absent from the agent path. [major]
- Data visualization: no chart, no table view, no CSV export of a result — a human must read JSON. [major]
- Scheduled/automated refresh of live sources: refresh means a new upload + new review, by hand, forever. [major]
- Export of knowledge to other formats (HTML, PDF, EPUB, plain Markdown bundle): no export path in the workspace. [minor]
- API documentation (OpenAPI/Swagger) for the HTTP routes: /uploads, /setup, /review, /membership are undocumented beyond prose. [minor]
- Client libraries beyond Pi: no VS Code extension, no web client, no CLI client for the workspace. [minor]
- Monitoring/alerting on publication failures: a failed activation is visible only by polling get_task. [minor]
- Structured logging: no logging configuration or correlation IDs anywhere in the workspace. [minor]
- Retention/GC policy for uploads, extractions, and rejected worktrees: private_root grows without bound. [minor]
- Localisation/internationalisation: all workspace UI is hardcoded English. [minor]
- Bulk/multi-item review decisions: one task per page, one page per browser visit. [minor]
- Idempotency UI: the retry_key discipline is mandatory and unexplained to the agent beyond a slash-command message string. [minor]
- Recovery UX when the human rejects with "request changes": the agent must start a brand-new draft with a new retry key; nothing links the two. [minor]
- Per-workspace data-source catalogue in the browser: a reviewer cannot see what sources exist, only what a task proposes. [minor]
- Documentation of the actual API contract for agents (tool-by-tool, with worked examples): absent; only the long CLI skill exists. [minor]
```

**MISSING_COUNT: 32**

---

## AREA: 7 — What is over-complicated?

```
OVER-COMPLICATED:
- The double source approval (analytics.py:744-786): a source needs TWO consecutive browser approvals to become queryable — first native Source Approval, then the requester's data grant. They can be one decision with two checkboxes. Cost: 2 extra browser round trips on every data onboarding. [simplify: one review page, one decision, two recorded outcomes]
- The double contribution approval (analytics.py:790-870): "submission" then "publication" are two separate human decisions over the same candidate. [simplify: one approval that commits, validates, and activates; the intermediate stage should be automatic]
- review_generation (review.py:275, 526, 545, 560; analytics.py:447, 606, 705, 724, 740, 753, 770, 842, 869, 1020): a counter that is written and echoed 20 times and NEVER READ for any decision. Pure dead weight. [delete outright]
- The 18-key review binding dict (review.py:262-283): workspace, task, reviewer, base, candidate, submission_base, submission_review, review_generation, authoring_review, publication_review, citations, attachment, private_binding, retention, destination_identity, expected_current, source_refresh, task_proposed_sources. Most are re-derivable from the Git candidate that the binding already points at. [replace with a digest of the candidate tree + the facts that are not in Git]
- The 7-table SQLite schema (state.py:81-183) for a single-server deployment: browser_sessions could be a signed cookie; setup_records duplicates information already in the operations table; local_users duplicates local_credentials. [collapse to operations + review_actions + memberships]
- review.py:171-229 _context recomputes the entire review twice per decision (once against submission_base, once against the admitted base) and calls _authoring() twice, each running a full diff + commit check. [compute the effective diff once against the admitted base; keep the submission check as a cheap commit-hash comparison]
- The 15 console scripts, 13 of them in ariadne-data (ariadne, -ingest, -validate, -serve, -analyst-mcp, -authoring-mcp, -init, -skill, -profiler, -authoring, -admit): the agent-facing story needs one surface, not five. [collapse to `ariadne` (query/admit) + `ariadne-mcp`; move ingest/validate/profiler/authoring behind the workspace MCP tools]
- The dual agent surfaces (workspace MCP server vs ariadne-serve stdio/HTTP vs the ariadne CLI vs ariadne-agent): four ways for an agent to reach the same engine, each with its own auth model. [pick one agent surface; keep the rest as operator commands]
- The membership page's separation of capabilities (app.py:47, 777-845): a page that can grant read/contribute/review but not setup or inspect_source, and cannot create the user it grants to, forcing CLI round trips for the two most privileged capabilities. [grant all capabilities from the page; create users there too]
- The enrichment impact projection (enrichment.py:38-82, review.py:806-834): computes bound-hash vs registry-latest-hash per page and dumps every claim's evidence anchors — while its own docstring says it "cannot determine Claim-level impact" and the HTML says the same. It is a conservative approximation that re-renders ~40 lines of nested dicts for every affected page. [replace with the diff of the source registry entry; the page list can be derived by the reviewer]
- The XLSX importer (spreadsheet_import.py, 769 lines): XML pre-parse, cell-order validation, explicit shared-formula refusal. It is careful, but the workspace path uses it to convert a workbook whose cells it then *reads before approval* (analytics.py:207-218), and it is exercised only by synthetic fixtures in this repo. [use openpyxl read-only (already an extra) and convert after approval]
- The workspace state machine's status vocabulary: 'pending', 'pending_review', 'pending_data_grant', 'pending_submission', 'pending_publication', 'data_granted', 'data_granted', 'published', 'rejected', 'ready', 'failed', plus 'pending_review' as a separate operation status — spread across state.py, analytics.py, contributions.py and review.py with different meanings per action. [one status enum with an explicit (action, status) table]
- The recovery/reconciliation machinery (review.py:428-509, analytics.py:1030-1100, git_authoring.py:2251-2286, mutation.py:398-620): ~700 lines to recover from a crash between "write receipt" and "flip pointer". For a single-server deployment the simpler answer is: write the pointer flip first with a journal entry, repair on boot. [a single durable journal + a boot-time repair pass]
- The ariadne-data `build/lib/` copy checked into the working tree (35,094 duplicated LOC): pure noise for every tool that scans the repo. [delete; it is a build artifact]
- lumio-wiki's 10,629-line CLI (cli.py) with a 617-line backend registry (`_RETRIEVAL_BACKENDS`, embeddings, S3, remote Lance, distillation) that the workspace never touches. [split the CLI into the operator commands the workspace needs and the rest; or drop the CLI from the deployment image]
- The duplicate byte-digest machinery: `_digest` in contributions.py, `_input_digest` in intake.py, `_token_hash` in state.py, `current_attachment_digest` in setup.py, `approval_digest` in authoring_sources.py, `review_digest` in authoring_review.py — six separate canonical-JSON hashing conventions in one 6k-line service. [one canonical_digest() helper]
- `aead`-style expiry/rotation bookkeeping in browser_sessions (rotated_at column, rotate_browser_session, browser_session_was_rotated): three code paths to model "this cookie is dead". [one signed, short-lived session cookie]
```

---

## OVERALL

```
OVERALL: PARTIALLY ACHIEVED
```

```
SUMMARY: The governance machinery is real and, in places, excellent — the sqlglot compile gate, the admission-record pinning, the one-use review-action CAS, the browser-only approval path, and the purpose-separated api/browser credentials all hold up under inspection, and no agent bypass of the human gate exists. What does not hold up is the product around that machinery: a first governed metric from a CSV costs 5 agent calls and 4 separate human browser approvals (8 HTTP requests), the agent has no discovery surface and must be handed the project handle, source handles and metric names out of band, the semantic-enrichment API requires entity IDs that no workspace read or search response exposes, the advertised LanceDB retrieval layer is not present in the agent path at all, and the project's own documentation states the Pi↔workspace leg has never been live-qualified. The "maximally simple" claim does not survive contact with the code: 15 console scripts, 4 overlapping agent surfaces, 5 distributions, 10–20 environment variables, 7 SQLite tables, two unmentioned filesystem trees, and no deployment artifact for the actual service.
```

```
BIGGEST_GAP: The agent-facing surface of the workspace is not usable as a product. It exposes ten tools with no discovery (no project handle, no metric list, no dataset list, no entity IDs), requires 4 human browser approvals and 8 HTTP round trips to get one governed metric, and has never been live-qualified end-to-end with a real Pi client, real HTTPS and two real humans — as the project's own how-to admits ("Live interoperability remains blocked", "a recipe, not evidence that the leg ran"). Everything below this surface is solid; this surface is where a team would give up on day one.
```

```
SIMPLICITY_AUDIT: The claim does NOT hold.
  Processes:  1 ASGI server + 1 operator-supplied TLS proxy + Pi client (+ Entra SaaS if selected).
              The repo's only Dockerfile/compose deploys a DIFFERENT service (ariadne-serve).
  Stores:     SQLite (7 tables) + Git authoring repo + Git analytics repo + published FS tree
              + private FS tree (uploads/extractions/worktrees/controls/authored) + embedded DuckDB
              + optional LanceDB + optional Postgres + optional S3.
              The claim names 4; the reality is 5 mandatory + 3 optional.
  Env vars:   5 mandatory service / 10 with analytics / 16 with Entra / 20 with the Pi client.
  Packages:   5 distributions (3 needed), 15 console scripts, ~100.5k implementation LOC
              of which the actual platform is 6.2k.
  Bootstrap:  none for the workspace (no Dockerfile, compose, systemd unit, or install script).
  Verdict:    "one server, one SQLite, one Git repo" describes the Ariadne standalone CLI.
              It does not describe the shared workspace product the goal describes.
```

```
TOP_3_SIMPLIFICATIONS:
1. Cut the human interaction count in half. Merge "approve source identity" + "grant data access"
   into one browser decision (analytics.py:744-786), and merge "commit/validate" + "publish"
   into one candidate approval (analytics.py:790-870). That removes 2 of the 4 required human
   approvals and takes CSV→governed metric from 9 round trips to 5, which finally meets the
   stated "<5 steps" bar.

2. Give the agent a discovery tool. One MCP tool — list_sources / list_metrics / list_datasets /
   list_pages, returning the operator-configured project handle, the source handles, the metric
   names, and the page entity IDs — removes the out-of-band handle problem (analytics.py:93-95),
   the "unknown metric" dead end (query.py:409-417), and the enrichment page_ids blocker
   (enrichment.py:126 vs app.py:327-361). This is the single highest-leverage change in the repo.

3. Delete one agent surface and the state-machine vocabulary. Collapse the 13 ariadne-data console
   scripts, ariadne-serve's stdio+HTTP MCP variants, ariadne-agent, and the 10,629-line
   lumio-wiki CLI down to: the workspace MCP server (agent surface) + 3 operator commands
   (publish, admit, backup/restore). Then collapse the 7-table SQLite schema and the 18-key
   review binding to operations + review_actions + memberships with a candidate-tree digest,
   and delete review_generation (written 20 times, never read).
```

```
MISSING_COUNT: 32
```

---

**Audit caveats (what I did not verify):** I did not run the test suites, deploy the service, or execute a live Pi session — all findings are static-code findings with file:line citations, cross-checked by two independent reviewers plus my own reads. Runtime-only behaviours (crash-recovery ordering, SQLite lock contention under concurrent reviewers, DuckDB behaviour on real workbooks, and the actual PDF/DOCX converter output fidelity) are therefore **CANNOT DETERMINE FROM CODE** and are noted as such above rather than asserted.