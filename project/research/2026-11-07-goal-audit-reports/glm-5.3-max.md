All evidence is in — three parallel deep-dive audits plus my own line-by-line trace of the workspace spine, cross-checked where subagent claims were load-bearing. Final report:

---

# Ariadne–Lumio Unbiased Goal Audit

Method note: static code tracing only (no runtime execution, no tests run). Verdicts cite real code paths. Three independent read-only subagent audits (ariadne-data, lumio-wiki+lancedb, Pi client/skill) were synthesized and spot-checked against my own reads of `lumio_workspace/{app,state,auth,review,analytics,contributions,operations,intake,publication,enrichment}.py`.

```
AREA 1: Data pipeline
VERDICT: PARTIALLY WORKS
```
**EVIDENCE:**
- All source families have real read paths: CSV/JSON/Parquet → DuckDB views (`ariadne/sources.py:676-737`), SQLite/DuckDB/PostgreSQL → `ATTACH` (`sources.py:694-722`), S3 via httpfs + storage-profile secrets (`sources.py:823-943`). XLSX → derived DuckDB via `import_workbook`, wired into the workspace upload path (`lumio_workspace/analytics.py:197-236` — contradicting the subagent-scoped claim it's unwired; it is unwired *inside ariadne-data itself* but called from the workspace with the `spreadsheets` extra).
- Upload works: exact-byte `POST /uploads`, 25 MiB bound, safe filenames, idempotent retry keys (`intake.py:78-134`).
- Governed query is real: sqlglot-compiled models, single-statement guard, allowed-relation/function authority, `governed: true` for metrics vs `governed: false, persistence: not_saved` for ad-hoc `define_metric` (`query.py:398-483,1359-1451`; `sql_authority.py:383-548`; `execution.py:132-288`). Results carry pinned commit + source digest (`analytics.py:527-557`).
- Approval gate: `approve_sources` is excluded from every MCP surface; workspace approval happens only in the browser (`authoring_sources.py:370-429`; `review.py:decide`).

**GAPS:**
- **The flow is inverted from the stated goal**: profiling requires *prior* human approval (`profile_data_source` → `_grant` requires `status == "data_granted"`, `analytics.py:455-474`), i.e. approve-then-profile, not upload→profile→approve.
- **First query on NEW data needs 4 human browser approvals**: source approval → data grant (`analytics.py:806-840`), then a contribution with `core_edits` defining the metric must pass submission + publication (`apply_decision`, `analytics.py:845-930`), because `query_data` calls `admission.resolve_admission` which hard-refuses without an admitted revision (`admission.py:1401-1412`). Agent-side: upload, `prepare_data_source`, `prepare_contribution`, `query_data` = 4 calls + 4 browser decisions. Not "<5 steps"; it is bureaucracy by design. (Operator-prebound, already-admitted sources short-circuit to 2 calls + 1 approval.)
- **PostgreSQL approval pins the env-var *name*, not the endpoint** — changing the DSN value redirects an "approved" identity to a different database without changing any digest (`authoring_sources.py:98-119`; `sources.py:1015-1028`).
- Admitted revisions pin source *identity*, not data — later queries read live rows (fine for live sources, but "pinned, cited result" means governance-pinned, not data-pinned).
- Unbounded profiling on the CLI path (`authoring_inputs` default `sample_rows=None` → full `SUMMARIZE` per table, `serve.py:1034-1061`); the workspace path passes `sample_rows=100` (`analytics.py:480`).
- No agent can register a *new* database/S3 source — operators hand-edit a bindings JSON (`analytics.py:116-137`).

```
AREA 2: Knowledge pipeline
VERDICT: PARTIALLY WORKS
```
**EVIDENCE:**
- Upload + parsing works for txt/md/pdf/docx via liteparse and anydoc/markitdown (`source_processor.py:341-383,740-747`); extraction returns text/sections with honest `incomplete` facts; no distiller runs (`authoring_journey.py:143-153`).
- Real semantic structure: pages are entities with frontmatter (`title,id,entity_types,aliases,tags,lifecycle,visibility,sources,claims`), claims have predicate + entity-object-or-typed-literal + status + evidence anchors, controlled vocabulary in `lumio.yaml`, entity-claims exported to OKF relationships (`knowledge_base.py:2963-2997`; `records.py:85-205`; `okf.py:218-355`).
- Publication is genuinely atomic and safe: Git worktree per task, exact-blob capture, review-digest + expected-version CAS, immutable version dir + pointer swap (`git_authoring.py:2052-2286`); rejection records `published: False` without touching the destination (`review.py:511-568`). Unpinned reads see new publications on the next request; a pinned `LUMIO_WORKSPACE_PUBLISHED_VERSION` deliberately does not follow.
- Review diff is meaningful: per-page title/change/lifecycle, source-support links, unified body diff, claim changes, conflict detection, source-refresh impact (`review.py:896-1000`).

**GAPS:**
- **No document→structured-pages pipeline.** Extraction yields text; the agent must author complete Markdown pages with frontmatter itself (`contributions.py:183-214`; default ingest wraps title-only frontmatter with a passthrough distiller, `lumio_wiki/ingest.py:471-541`). "Submit a PDF → structured pages" as an automated step does not exist.
- **Enrichment is unusable from the read surface**: `prepare_enrichment` needs `page_ids`, but `read_knowledge` returns `title/summary/body` (frontmatter stripped — `_parse_frontmatter` returns body without it, `knowledge_base.py:2532-2558`) and `search_knowledge` returns title/path/passage; neither exposes the Entity ID. No listing/registry tool exists at all (app.py routes/tools confirm).
- **Source inspection breaks on binaries**: the review page links retained originals, but `inspect_source` does `raw.decode("utf-8")` → PDF/DOCX originals render as `source_unavailable` (`review.py:331-365`).
- Review requires expertise: semantic changes are raw JSON dumps, everything is identified by 40-hex digests, and analytics reviews are `<pre>` JSON (`review.py:837-893`; `templates/review.html:43-45`).
- Review-page template crash risk: `Template.substitute` with page content that contains `$identifier` (prices, shell snippets) raises KeyError → review page 500s (`review.py` uses `substitute`, not `safe_substitute`; `html.escape` does not escape `$`).
- Min path "PDF → published & searchable": 6 actions (upload, extract, author pages, prepare, approve, search); with enrichment: ~10.

```
AREA 3: Agent consumption
VERDICT: PARTIALLY WORKS
```
**EVIDENCE:**
- `pi-workspace` is a real Pi extension: registers the MCP server (local-token bearer or Entra OAuth config), adds `/workspace` and `/workspace-upload` commands plus model-disclosure hooks (`clients/pi-workspace/index.ts:29-138,212-256`); `upload.ts` posts exact bytes with headers (`upload.ts:19-41`).
- Server exposes workspace_status, read_knowledge, search_knowledge, read_source_material, prepare_data_source, profile_data_source, query_data, prepare_enrichment, prepare_contribution, get_task (`app.py:315-598`).
- Governance status is truthful: `governed: true/false`, `attestation: pending`, pinned commit/digest on every query result (`query.py`; `analytics.py:527-557`).

**GAPS:**
- **The shipped skill teaches the wrong interface.** `skill_assets/SKILL.md` (765 lines) is a manual for the *local* `ariadne` CLI with 22 numbered steps, Git-project internals, bindings, profiles and namespaces; the managed-workspace section is ~15 lines of authority rules (`SKILL.md:6-19,644-659`). No workspace-native skill exists. Productive in 10 minutes: no.
- **No vector search for agents**: `search_knowledge` is deterministic lexical only (`knowledge_base.py:601-614`); LanceDB lives in a separate package wired only into the `lumio-wiki` CLI behind `LUMIO_RETRIEVAL_BACKEND=lancedb` (`cli.py:608-695`); `lumio-workspace` does not even depend on `lumio-lancedb` (pyproject). The goal's "LanceDB vector search through a single managed workspace" is not implemented.
- README has **zero copyable install commands** ("Install this directory as a trusted Pi extension package"); Entra guidance omits the required `LUMIO_WORKSPACE_URL` (`index.ts:215-223` vs gate at `:40-44`).
- Tests are synthetic: mocked model fetch + fixture MCP server; README itself warns Pi's shell can leak the token (`README.md:3`).
- No discovery: an agent cannot list metrics, pages, or its own tasks (only per-ID `get_task`).

```
AREA 4: Collaboration model
VERDICT: WORKS (with caveats)
```
**EVIDENCE:**
- Agent tokens cannot approve: `/review` decisions require a browser session; local browser login requires a purpose-`browser` credential while MCP verifies purpose-`api` only (`auth.py:63-83`; `state.py:225-245`; `app.py:654-719`).
- Self-approval blocked unless single-person workspace *and* the submitter holds `contribute`, and then only via the browser (`review.py:400-414`).
- One-use action digests bound to full binding JSON; replay → `action_replay` (`state.py:476-505`; `review.py:415-425`).
- Revocation is immediate: every request re-checks membership, credential revocation, and user-enabled (`state.py:132-158,222-245,685-687`).
- Backup holds mutation locks and copies all durable roots; restore invalidates issued/pending review actions and all browser sessions, relinks worktrees (`operations.py:99-240`).
- Crash recovery exists (`reconcile_task`, publication receipts, indeterminate-outcome refusal).

**GAPS (caveats):**
- No reviewer inbox — pending reviews are reachable only by task URL handed over by the agent; a human cannot see "what's waiting" (`app.py` routes: /setup, /review/{id}, /membership, /auth, /workspace only).
- Membership *page* grants only read/contribute/review; user creation, tokens, setup and inspect_source capabilities are CLI-only — onboarding a reviewer = 3-4 operator CLI commands (`__main__.py:44-116`).
- HTTPS is hard-required (scheme checks on every sensitive route) → a TLS-terminating proxy is mandatory even for local-token mode; Entra mode needs 7 more identity env vars.
- A single-person team effectively self-approves 4 times per dataset — the gate holds, but the ceremony multiplies.

```
AREA 5: Operational simplicity ("maximally simple")
VERDICT: DOES NOT HOLD
```
**Counted moving parts:**
- Processes: 1 uvicorn server + a mandatory TLS reverse proxy (HTTPS scheme enforced in code) = 2; Git subprocess dependency throughout.
- Stores per workspace: SQLite state, authoring Git repo, published destination (immutable versions + receipts + pointer), private root (uploads, extractions, worktrees, authored, controls, registry, artifacts, activation locks), analytics Git project + its DuckDB files, optional LanceDB index. ≈ 7 stores.
- Env vars: 5 minimum server (AUTH_MODE, ID, EXTERNAL_URL, PUBLISHED_PATH, STATE_PATH); +5 for authoring+analytics; +7 Entra identity; +3-6 client side; plus operator-authored `analytics-bindings.json` and the browser owner-setup ritual (preview→apply digest). Python **3.14+** required.
- Packages: ariadne-data, ariadne-agent, lumio-wiki, lumio-lancedb, lumio-workspace (5 Python packages, 3 published families with lockstep version pins) + pi-workspace TS client.
- No Dockerfile/compose/systemd unit in the repo; no /health endpoint; deployment is a documented-but-manual operator procedure.
- 216K lines of source (~2,177 tests) for this functionality; `lumio_wiki/cli.py` alone is 10,629 lines.

**Dead/speculative:** `lumio-lancedb` is unused by the managed workspace it was named for; duplicated branch in `discovery._admission_view` (`discovery.py:233-256`); unreachable duplicate status check in `contributions.py:445-452`; in-memory `setup_previews` dict requires a fresh GET before every apply (single-process assumption baked in).

```
MISSING:
```
- **Reviewer inbox / pending-review listing**: reviewers can't see waiting work without agent-supplied URLs — **blocker** for real team use.
- **Notifications** (email/webhook/anything): nobody is told a review is waiting — **major**.
- **LanceDB/semantic search in the workspace**: advertised, exists as a package, not wired — **major**.
- **Entity/page listing or ID discovery tool**: enrichment is unusable without it — **major**.
- **Automated document→page distillation** (LLM distiller): passthrough only — **major** (goal claimed it).
- **Workspace-native agent skill**: the shipped skill documents the local CLI — **major**.
- **Multi-workspace/multi-tenancy**: one workspace per process — **major**.
- **User lifecycle beyond CLI**: no self-registration, passwords, reset, SSO other than single-tenant Entra; browser admin covers only capability grants — **major**.
- **Health checks/monitoring/metrics/alerting**: none — **major** for operations.
- **Rollback/revert of a published version**: immutable versions exist but no revert operation or UI — **major**.
- **Data visualization**: no chart or human-facing data view; humans approve numbers they cannot see — **major** for the "review metrics" promise.
- **Audit-trail surface**: approvals/digests exist in SQLite+Git but no queryable history view — **minor**.
- **Agent-initiated new DB/S3 source registration**: operator bindings JSON only — **minor** (deliberate, but a gap vs the goal's wording).
- **Rate limiting / per-member quotas**: only size/count bounds — **minor**.
- **OpenAPI/typed REST docs**: MCP-only, custom routes return ad-hoc JSON — **minor**.
- **Result caching / scheduled refresh**: everything re-reads live at query time — **minor**.
- **Workspace-side export** (OKF export exists only in the lumio-wiki CLI) — **minor**.
- **Pagination** on search (hard cap 20) and tasks — **minor**.
- **Deployment artifacts** (containers/units) — **minor**.
- **Localization** — **minor**.

MISSING_COUNT: **20**

```
OVER-COMPLICATED:
```
- **Review-action binding machinery** (state.py `review_actions` + issue/start/finish + binding-JSON equality + `action_replay` + `review_generation`/`draft_generation` counters + `expected_response` CAS + reconcile/recovery): correct but baroque for one authenticated same-origin browser on a single server; a CSRF nonce + status compare-and-swap achieves the same safety in a third of the code (state.py:476-580; review.py:374-568).
- **BrowserSessionMiddleware**: ~100 lines of rotated_at/passive-cookie bookkeeping reinventing signed-cookie session management (app.py:75-151).
- **Dual status+stage bookkeeping**: `pending_source_approval/pending_data_grant/data_granted/pending_submission/pending_publication/published/rejected/failed` *plus* a parallel `stage` field on every response (analytics.py passim) — one state enum would remove a whole class of reconcile branches.
- **Admission pinning depth vs the PG hole**: `validate_admission_record` re-verifies artifact bytes, review digests and approvals (admission.py:1325-1401) while PostgreSQL identity pins an env-var *name* — heavy exactly where it doesn't pay.
- **Enrichment selection**: drafts-dict/generation/obsolete-draft machinery + per-page binding coverage + registry-latest binding — a "one active draft per task" model plus the missing ID-discovery tool would deliver the feature with far less code (contributions.py:386-460; enrichment.py).
- **The ceremony itself**: 4 approvals for one new dataset is process complexity without proportional safety over 2 (identity+grant can be one screen; submission+publication can be one for single-person spaces).
- **Package ceremony**: 5 Python packages + lockstep version families + wheel-verifier CI jobs for a single-server product; `lumio-lancedb` (72 tests, published) serves no code path of the managed workspace.
- **`lumio_wiki/cli.py` at 10,629 lines** and `context.py` at 4,279: the "could be 50% shorter" award winners; also `_render_analytics_review`'s `<pre>` JSON dumps passing through fragile `Template.substitute` (should be `safe_substitute` at minimum — it's also a latent 500).
- **Owner setup ritual**: in-memory preview digest → POST digest → attachment_digest persistence (app.py:645-700; setup.py) — an operator confirmation screen would do.
- **Layering smell**: app.py reaching into `state._connect()` private connection for membership rows (app.py:241-259).
- **Dead branches**: `discovery._admission_view` identical both branches; duplicate unreachable status check `contributions.py:449-452`.

```
OVERALL: PARTIALLY ACHIEVED
SUMMARY: The security and governance core is real and well-built — browser-only human approval, atomic Git-backed publication, compile-gated SQL with truthful governed/ad-hoc labels, immediate revocation, and crash recovery all trace to working code. But the platform around that core falls short of its own goal: profiling-before-approval is inverted, a new dataset needs four human approvals before its first query, there is no document-to-pages pipeline, no vector search in the workspace, no way for an agent to discover Entity IDs or pending state, and the shipped agent skill documents the wrong interface. "Maximally simple" is the least true claim: 5 packages, ~7 stores, 10+ env vars, a mandatory TLS proxy, Python 3.14, and a four-stage review ceremony.
BIGGEST_GAP: The agent experience is not actually delivered — no workspace-native skill or discovery surface, enrichment requires IDs the read tools never return, and LanceDB retrieval exists as a package but is wired nowhere in the managed workspace an agent connects to.
SIMPLICITY_AUDIT: Claim fails. 2 processes (server + TLS proxy) + Git; 7 durable stores (SQLite, authoring Git, published dir, private root incl. registry/artifacts/worktrees/uploads, analytics Git project, DuckDB files, optional Lance); 5 env vars minimum / ~12-17 realistic; 5 Python packages + 1 TS client; no containers/health checks; 216K lines.
TOP_3_SIMPLIFICATIONS: (1) Collapse review stages — merge source-approval+data-grant into one browser decision and submission+publication into one for single-person workspaces, deleting two statuses and their reconcile branches; (2) make the workspace the product — fold lumio-lancedb into search_knowledge or drop it from the platform, and ship a workspace-native agent skill with listing/ID-discovery tools; (3) replace hand-rolled session/replay machinery with signed-cookie sessions + one CSRF nonce + status CAS, deleting BrowserSessionMiddleware and the review_actions replay table.
MISSING_COUNT: 20
```

---

**Task recap:** independent goal audit of the Ariadne-Lumio platform, code-only, 7 areas → this report. **Disposition: hand back** — every named defect (PG identity hole, `$`-template crash, missing ID discovery, 4-approval ceremony, unwired LanceDB) is a product decision for you, not something I changed. Nothing in the repo was modified.

*Ponytail: skipped — running the test suite or a live server (verdicts are static-trace only, so runtime-only bugs could exist beyond the ones named); risk — two findings rest on subagent reads that I spot-checked but did not re-trace to the last line (PG `connection_env` binding, upload.ts header handling).*