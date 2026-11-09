

All three sub-audits are in and I've independently verified their load-bearing claims. Here is the consolidated final report, with the subagent findings folded in and my earlier statements corrected where they were wrong.

---

# Ariadne–Lumio Unbiased Goal Audit — Final

*Method: direct source reading only. Planning docs/ADRs/specs were used only as pointers, never as evidence. Three parallel sub-auditors covered data, knowledge, and agent/boundary; I verified their headline claims in source myself (marked ✓ where I did).*

---

```
AREA: 1 — Data pipeline (can an agent actually get data queryable?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - Upload: app.py:606 `POST /uploads` → app.py:614 capability check → intake.py (SHA-256, retry key,
25 MiB cap, suffix allowlist). Exact bytes, not multipart.
  - Source request: app.py:437 `prepare_data_source` → analytics.py:294-468. CSV/JSON/Parquet use native
    handlers; XLSX requires explicit `sheets` (analytics.py:334-339 — actionable error).
  - Profile: analytics.py:470-509 → `self.api.inputs(sample_rows=100)` → profiler.py:391-412/484-516.
    Measured schema/row/type facts, with the approval digest re-checked before AND after
    (analytics.py:478, 493-500). ✓
  - Browser approval: app.py:706-750 GET+POST, gated on `permits(..., "review")` (app.py:716), HTTPS
    (app.py:714), same-origin Origin check (app.py:724), form-urlencoded only (app.py:726), one-use
    action digest bound to task+actor+binding (state.py:543-594, issued only on the browser GET review.py:328).
  - Governed query: query.py:441 `sql = render(self._metrics[name]["model"], ...)` — compiled by the project's
    own sqlglot renderer from served OSI models, never from tool input; query.py:444 single-statement guard;
    query.py:457 EXPLAIN bind; query.py:465 grain guard. Ad-hoc path additionally runs the static
    IO-authority boundary (sql_authority.py:390-620: relation allowlist, function allowlist, no side effects).
  - Pinned + cited + honest status: analytics.py:554-558 `pinned: {commit, source_digest}`;
    query.py:476 `"governed": True`; query.py:1264 & query.py:1448 `"governed": False`;
    query.py:485 `_admission_view`; context.py:330-388 attaches metric page + policies + signals.
GAPS:
  - NOT under 5 steps. Upload → query is 13 application calls and 4 browser reviews:
    upload(1) → prepare_data_source(2) → review GET(3) → review POST(4) → review GET(5) → review POST(6)
    → profile(7) → prepare_contribution(8) → review GET(9) → review POST(10) → review GET(11) →
    review POST(12) → query_data(13). Stage transitions at analytics.py:735-775 (source_approval→
    data_grant) and analytics.py:777-874 (submission→publication). "Bureaucracy" is accurate.
  - The reviewer approves a source they have NOT seen profiled: `profile_data_source` requires status
    `data_granted` (analytics.py:470-476 → analytics.py:185-196), i.e. both reviews must precede profiling.
  - Approval + grant + profiling admit nothing. `query_data` requires the fully admitted revision
    (analytics.py:520 `admission.resolve_admission`).
  - SOURCE IDENTITY IS NOT FULLY PINNED (✓ new finding): the resolved identity binds the *name* of the
    credential env var, not its value — authoring_sources.py:117-118 `entry["connection_env"] =
    src.connection_env`, while the DSN is resolved at runtime (sources.py:1020 `os.environ.get(...)`).
    `storage_bindings_from_identity` (authoring_sources.py:80-95) re-resolves endpoint/region for S3
    storage profiles ONLY (it skips entries with no `storage` dict) and admission.py:1364-1385 compares
    those. A Postgres DSN changed under the same variable name points at a different database with an
    unchanged approval digest. Severity: major.
  - The 100-row profile bound is a *sample* bound, not a physical-I/O bound: profiler.py:484-500 opens the
    connection and catalogs the approved registry BEFORE the selector narrows it, and the sample is a
    LIMIT-ed copy (profiler.py:505-514). Profile stats are labeled `sampled: true, sample_limit: 100`
    (profiler.py:445) — honest, but "bounded" is weaker than it sounds.
  - XLSX sheets are CONVERTED BEFORE EITHER APPROVAL (analytics.py:210-215, 377-387).
  - Env vars: 5 for read-only local-token (app.py:163-181); 10 for the full analytics path (adds
    AUTHORING_PATH, PRIVATE_PROFILE, ANALYTICS_PROJECT_ID/PATH/SOURCE_BINDINGS — app.py:364-385);
    12 counting the optional PRIVATE_ROOT and NAMESPACE; +6 identity vars in Entra mode (auth.py:39-51);
    plus per-storage S3 vars and OPENAI_* for authoring (author.py:42-51).
  - Generic (non-actionable) refusals: app.py:448 "workspace contribution is not available" and app.py:616
    (same string on upload) name neither the missing permission nor the identity.
```

```
AREA: 2 — Knowledge pipeline (can an agent author and publish knowledge?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - Submit: app.py:606 upload → intake.py → authoring_journey.extract_source. PDF = LiteParse
    (source_processor.py:341-351), DOCX = AnyDoc (source_processor.py:367-380 — NOT MarkItDown, correcting
    my earlier note; MarkItDown handles other formats), UTF-8 text needs no converter. Converters are
    optional extras but included in lumio-workspace's deps (pyproject.toml:8-10); a missing one produces
    an actionable `pip install 'lumio-wiki[documents]'` (source_processor.py:215-228).
  - CORRECTION to my earlier report: extraction yields TEXT, not structured pages. The agent must author the
    complete Markdown pages + frontmatter itself (contributions.py:196-235, 647-708; authoring_journey.py:565-647).
    Frontmatter/tags/ontology refs are validated at review, not generated.
  - Enrichment: app.py:494 `prepare_enrichment(page_ids, expected_version, request_key)` → enrichment.py:92-215.
    Bounded to 20 pages / 200k chars / 40 claims. External lookup disabled by default (review.html:34-35).
  - Review diff: review.py:937-953 renders per-page unified `body_diff` plus "Semantic and Claim changes"
    JSON; the analytics variant (review.py:837-893) binds native submission + candidate + expected/observed
    version + overall digest.
  - Publish → immediately readable: review.py:527-552 → publication.py:58-73 atomically moves the destination
    pointer; reads open a fresh snapshot from that destination each call (app.py:280, 306-313).
  - Reject preserves published state: review.py:554-568 sets `published: False` and never calls publish;
    analytics.py:718-733 `_reject` likewise.
GAPS:
  - ★ ENTITY IDs ARE NOT DISCOVERABLE (✓ new, and it breaks a documented flow): `prepare_enrichment` requires
    `page_ids`, and enrichment.py:190 matches them against `page.id` — the Entity ID. But the workspace's
    read/search tools return only title/path/citation (app.py:327-362) and never the entity ID. An agent
    therefore cannot construct a valid enrichment request from workspace output alone, while    `read_knowledge`/`search_knowledge` are the only discovery surfaces it has. Severity: major.
  - ★ BINARY SOURCES ARE UNREVIEWABLE (✓ new): the review source-inspection path UTF-8-decodes the ORIGINAL
    bytes (review.py:619 `fetch_verified_artifact(...).decode("utf-8")`) and the inspect_source route does the
    same (review.py:360-363). For a PDF or DOCX this raises UnicodeDecodeError and renders "Original passage
    unavailable" / "the exact private source resources are unavailable". The reviewer cannot see the document
    they are approving. Severity: major.
  - Rejection does NOT restore private operational state: source versions and originals are already registered
    and retained at preparation time (authoring_journey.py:701-750), so a rejected new source ID can affect a
    later conflicting proposal. Published state is untouched; private state is not rolled back.
  - Review UI is expert-only. templates/review.html is 68 lines, no stylesheet, and opens with a `<dl>` of
    git SHAs and digests ("Exact admitted review base", "Native submission review", "Exact candidate",
    "Expected active version", "Native authoring review"). The analytics path dumps raw JSON into `<pre>`
    blocks (review.py:879-885). Actual instruction text: "Review every displayed change and consequential
    action. This page alone authorizes nothing." A non-technical human sees hashes.
  - LanceDB vector search is NOT on the workspace surface. `rg 'lancedb|vector|embedding'` over
    lumio-workspace/src/ → nothing. `search_knowledge` is lexical zero-index (app.py:347-362 →
    page_search.py:82-93, whose own docstring calls it "the LanceDB-free core of page search"). Even
    lumio-wiki's MCP server exposes no vector tool — `status_rows` hard-codes `retrieval: "zero-index"`
    (mcp_server.py:313-320). Semantic/hybrid exists ONLY in the lumio-wiki CLI (cli.py:620, 2954, 3125)
    with an embedder dependency. The goal's "LanceDB for retrieval" through one workspace is not met.
  - Entity/claim/evidence graph and ontology are not exposed to agents on the workspace. lumio-wiki's own MCP
    has `related`, `paths`, `index`, `hot` (mcp_server.py:346-396); the workspace exposes none of them.
  - No published-version history, diff, or rollback from the workspace (publication.py moves a pointer forward;
    `LUMIO_WORKSPACE_PUBLISHED_VERSION` is a read pin, app.py:168).
  - PDF → searchable is 5 interactions + 1 verification (upload → read_source_material → author pages →
    prepare_contribution → GET review → POST review → search). Acceptable. The 4-review dance is data-specific.
```

```
AREA: 3 — Agent consumption (can an agent actually use this daily?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - The Pi extension is real and targets the real service: index.ts:56-63 `pi.registerMcpServer("lumio-workspace",
    { url: `${url}/mcp`, headers: { Authorization: "Bearer ${LUMIO_WORKSPACE_API_TOKEN}" } })`; Entra OAuth
    path index.ts:66-83. It does NOT start the service (package.json only registers the extension).
  - Search: app.py:347-362 `search_knowledge` → snapshot.search_pages → lexical ranking (page_search.py:82).
  - Metrics with context/citations: app.py:476 `query_data` → analytics.py:511 → query.py; context attached
    at query.py:477-479 → context.py:330-388.
  - Proposals: prepare_contribution (app.py:518), prepare_data_source (app.py:437), prepare_enrichment (app.py:494).
  - Honest labels: governed True at query.py:476/1043/1143, False at query.py:1264/1448; ad-hoc also reports
    `not_saved`; proposals report pending + `published: False`. "governed: true means admitted, not
    independently value-attested" (context.py:381-383).
  - A browser credential can never be minted from an API token: app.py:882 authenticates the login form with
    purpose="browser"; state.py:332-338 refuses a purpose mismatch.
GAPS:
  - ★ NO DISCOVERY TOOL — the largest gap. The workspace MCP has no list_metrics, discover, search_context,
    read_context_page, or page index, although ariadne's own MCP server has all five (serve.py:528-628).
    An agent cannot learn which governed metrics exist, cannot read the context layer as pages, and cannot
    look up ODCS v3.2.0 contracts or semantic terminology as first-class retrieval. Contracts are only
    reachable embedded inside a metric answer (query.py:477, context.py:330-388). Combined with the
    entity-ID gap in Area 2, an agent cannot navigate the knowledge base at all beyond literal title lookup.
  - The packaged skill (ariadne/skill_assets/SKILL.md, 765 lines) documents the STANDALONE ariadne CLI/MCP,
    not the workspace flow. Both skills teach local Git/CLI workflows rather than workspace MCP calls.
  - The agent's actual operating instructions are a ~1000-char prose wall emitted as a UI toast
    (index.ts:236-252).
  - Install/connect is manual: the extension is `private: true`, no publish/install mechanism; the operator
    places the directory in Pi's trusted-extension path, sets 4-5 env vars, reloads Pi, runs /workspace and
    /mcp. ~8-10 steps before the agent reads anything.
  - The model allowlist is CLIENT-SIDE ONLY (index.ts:48-136). The server never sees
    LUMIO_WORKSPACE_ALLOWED_MODELS. The client README admits it: "trusted-client disclosure policy, not remote
    attestation." A modified client or any other MCP client bypasses it entirely. Severity: blocker.
  - The API token leaks into Pi's shell environment — documented as an "accepted interim limitation" in both
    the client README and docs/howto-shared-workspace.md:1-3. Real blocker for deployment.
  - Workspace errors are flattened to strings (app.py:490, 515, 580), discarding ariadne's structured codes.
  - The agent needs internal vocabulary: project/source-task IDs, two distinct grants (source vs data),
    retry keys, four review stages, pinned releases (index.ts:190-204, 235-252).
```

```
AREA: 4 — Collaboration model (does the human-agent boundary actually hold?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - An API token CANNOT approve. The MCP tool list has no approve/decide tool; approval lives only in the
    browser POST (app.py:706-750). The action digest is issued ONLY by a browser GET (review.py:328); the POST
    additionally requires HTTPS (app.py:714), same-origin Origin (app.py:724), form encoding (app.py:726),
    and `permits(..., "review")` (app.py:716). ✓ probed: API-token review POST → 401; API-token browser
    login → 401.
  - Self-approval is browser-only: review.py:395-403 permits actor==submitter only when
    `is_single_person_workspace` (state.py:622-628: exactly one distinct membership row) AND the actor
    holds "contribute" — and it still executes through the browser route.
  - Backup/restore: operations.py:110-156 copies SQLite state, private tree, authoring repo, published
    destination, profile, registry, artifacts, analytics project and bindings under the activation mutation
    locks; restore (operations.py:193-254) re-links worktrees, rebases profile paths, and
    `_invalidate_restored_actions` (operations.py:186-190) deletes every issued/pending review action and all
    browser sessions. Admitted content is preserved.
  - Reviewer surfaces: browser only (/auth/login, /workspace, /setup, /review/{task}, /review/{task}/source/…,
    /membership). The CLI is operator-side, not reviewer-side.
GAPS:
  - ★ REVOKING `read` DOES NOT REMOVE MEMBER ACCESS (✓ new). Capabilities are independent rows and each
    route checks only its own: state.py:356-364 `DELETE … AND capability = ?` removes exactly one grant;
    app.py:614 checks only "contribute"; app.py:716 checks only "review"; app.py:912 checks only "read".
    A member whose "read" is revoked but who retains "contribute" can still upload and prepare contributions;
    one retaining "review" can still review. There is no revoke-all operation. The stated goal "revoking a
    member's access immediately blocks their agent and browser session" is FALSE for partial revocation.
    Full mitigation exists — `local-user disable` (state.py:205-225) invalidates credentials and sessions on
    the next check — but the model is one-grant-at-a-time with no cascade. Severity: major.
  - ★ RESTORE DOES NOT INVALIDATE PENDING REVIEW TASKS (✓ probed). operations.py:186-190 deletes
    issued/pending ACTIONS and browser sessions but leaves `operations` rows in `pending_review`; a fresh
    browser GET can then re-issue an action and approve the restored candidate. Actions are voided, tasks
    are not. Severity: major.
  - ★ THE HUMAN GATE IS A DEPLOYMENT ASSUMPTION, NOT AN ENFORCED BOUNDARY (✓ third bypass path found).
    Three shell paths self-confirm with no human: `ariadne-admit --confirm` (admission.py:1440-1500),
    `ariadne-authoring approve-sources` (authoring_sources.py:371, authoring.py:332), and
    `lumio-wiki publish … --confirm <digest>` (cli.py:5305-5345 — the preview prints "Reading this review does
    not authorize publication; authorize the displayed state explicitly with --confirm", then publish_revision
    runs). An agent with a shell on the server host can approve its own work. Severity: blocker.
  - Entra browser sessions are not revocable per-request: they carry no `local_credential_id`, so
    state.py:205 skips the credential check; only the 1-hour TTL (app.py:61) and IdP expiry apply.
  - The two-human journey has NEVER been run with two humans — products/lumio/examples/shared-workspace-journey/README.md:12-31
    says so outright: "one agent driving every identity proves nothing about human approval". Two real humans,
    installed Pi, private HTTPS, and the Entra leg are all listed as open. No Entra tenant fixture exists.
  - Reviewer UX is poor (Area 2): unstyled 68-line page, SHA/JSON dumps.
```

```
AREA: 5 — Operational simplicity (is it actually "maximally simple"?)
VERDICT: DOES NOT WORK
EVIDENCE:
  - Processes: 1 ASGI service (uvicorn via `lumio-workspace serve`, __main__.py:87) + a MANDATORY TLS
    terminator (external_url must start https://, app.py:184; every browser route requires https,
    app.py:714/791) + the `git` binary as a subprocess + optional converter subprocesses (LiteParse, AnyDoc).
    The ariadne query runtime runs IN-PROCESS (analytics.py:17 imports ariadne.query) — that part is simple.
  - Stores: SQLite state, authoring Git repo + per-task worktrees, DuckDB file(s), published KB dir, private
    profile JSON, source registry dir, artifact store dir, filesystem lock dir (operations.py:30-41), optional
    LanceDB index, optional S3 buckets = 9-10, not 4.
  - Env vars: 5 read-only / 10 full analytics local-token / 16 Entra-analytics, plus S3 + OPENAI.
  - Packages: 4 uv members (pyproject.toml:11-16) + 1 orphan + a TS extension.
  - NO container/service definition for lumio-workspace — only for the ariadne MCP server
    (products/ariadne/deploy/compose.yaml:1-49). The actual platform has no deployment artifact.
  - sysadmin effort: Python 3.14 + uv, 4 packages, TLS + private DNS, author a Lumio KB (lumio.yaml,
    .lumio-authoring.yaml, namespace), write private profile JSON, create the analytics Git project with
    ariadne.yaml + OSI models + DuckDB, install DuckDB httpfs for S3 (ci.yml:143-146), write source bindings,
    publish an initial KB, then create users + memberships + two credentials per person. Half a day to a day;
    several analytics steps have neither code nor documentation.
GAPS:
  - products/ariadne/packages/ariadne-agent is ORPHANED and uninstallable elsewhere: not a uv member
    (pyproject.toml:11-16), not in CI, and pyproject.toml:32 pins
    `tau-mcp = { path = "/home/volker/coding/tau-mcp" }` — an absolute path on the author's machine.
    1,790 LOC of unreferenced code.
  - Stale untracked build output (root build/lib/ariadne, root dist/ariadne_data-0.4.1*, root ariadne-agent/).
  - ariadne/author.py:23 hardcodes    `ENV_PATH = Path(os.environ.get("ARIADNE_ENV", "/home/volker/coding/ariadne/.env"))` — a machine-specific
    default inside a published package.
  - The stated inventory ("one server, one SQLite, one Git, DuckDB, LanceDB") matches neither the code nor    the docs: LanceDB is absent from the workspace path, and there are ~10 stores, not 4.
  - Four overlapping surfaces: lumio-wiki CLI (10,629 LOC), lumio-wiki MCP, ariadne-serve MCP,
    lumio-workspace.
```

---

```
MISSING:
- Vector/semantic search on the workspace MCP: the goal's retrieval story; the workspace imports no vector
  code and search is lexical zero-index (app.py:347-362; mcp_server.py:313-320). [blocker]
- Metric + context discovery tools on the workspace MCP (list_metrics / discover / search_context /
  read_context_page / page index): ariadne has all five on a different server (serve.py:528-628). [blocker]
- Entity IDs in discovery results: prepare_enrichment requires page.id (enrichment.py:190) which read/search
  never return (app.py:327-362) — enrichment is unreachable from workspace output. [blocker]
- Server-side enforcement of the model allowlist: client-side only (index.ts:48-136). [blocker]
- A real multi-user qualification run (two humans, installed Pi, private HTTPS): never performed
  (shared-workspace-journey/README.md:12-31). [blocker]
- Host-level enforcement that human-only approvals cannot be self-confirmed by an agent: three shell paths
  exist (admission.py:1440, authoring_sources.py:371, cli.py:5305-5345). [blocker]
- API-token isolation from the agent's shell/model context: documented accepted interim limitation. [blocker]
- Pinned database endpoint identity at approval time: the digest binds the env var NAME, not the DSN value
  (authoring_sources.py:117-118 vs sources.py:1020); storage re-resolution covers S3 only
  (authoring_sources.py:80-95). [major]
- Revoke-all / cascading revocation: revoking one capability leaves the others live (state.py:356-364). [major]
- Rendered original documents in review: binary sources cannot be inspected (review.py:360-363, 619). [major]
- Health/readiness endpoint on the workspace service: ariadne-serve has /healthz and /readyz
  (serve.py:1180-1184); lumio-workspace has none. [major]
- Metrics, structured logging, tracing: no observability surface in either service. [major]
- Reviewer notification / "something is waiting" queue: no queue view, webhook, or email. [major]
- Rate limiting / quotas on /uploads and the MCP surface: no limiter anywhere. [major]
- Published-knowledge version history and rollback: no list/diff/revert API (publication.py:38-58). [major]
- Audit-trail query surface: the facts exist across operations/review_actions and native receipts, but no
  human-readable view. [major]
- OpenAPI/Swagger for the browser API: every custom route is include_in_schema=False (app.py:606, 642, 706,
  752, 776, 893, 906). [major]
- User management beyond the CLI: local users only via `local-user create` (__main__.py:99-103); /membership
  assigns capabilities to users that already exist (app.py:776-844). No self-registration, no reset, no
  deactivation UI. [major]
- Scheduled/automated refresh of live database and S3 sources: refresh means a new upload + new reviewed
  selection every time (index.ts:196-199 states this). [major]
- Agent-facing "connect this Postgres/DuckDB/SQLite/S3 bucket" operation: only operator-pre-declared handles
  work (analytics.py:294-468). [major]
- Machine-readable error codes in workspace MCP responses: structured refusals flattened to strings
  (app.py:490, 515, 580). [major]
- Published, installable Pi extension package (private:true, manual placement). [major]
- Deployment artifact for the workspace itself (container/compose/systemd). [major]
- A readable, styled review UI (68 unstyled lines + raw JSON dumps). [major]
- Two-identity test of the human approval path. [major]
- Private full-text search across published content (page-level lexical only). [minor]
- Data visualization for humans: no chart surface. [minor]
- Knowledge export from the workspace to other formats. [minor]
- Client libraries beyond Pi: no Python/TS SDK, VS Code extension, web app, or mobile. [minor]
- Localization: all UI strings and errors hardcoded English. [minor]
- Pagination beyond a hard limit of 20 results (app.py:349-350). [minor]
- Multi-workspace per deployment: one workspace_id, one state file, one config (app.py:163-181). [minor]
- Private-state rollback on rejection (rejected source IDs persist). [minor]
- Cleanup of the orphan ariadne-agent package and stale root build/dist artifacts. [minor]
```

```
OVER-COMPLICATED:
- The four-review data pipeline: source_approval → data_grant → submission → publication
  (analytics.py:741-874). Two of the four exist to sequence two permissions that one exact-candidate
  review already binds. Collapse to one review binding source identity + grant + candidate. [~200 LOC, 4 UI
  states, and half the agent-visible steps removed]
- The review-action binding system: one-use nonce (state.py:543-566) + binding-JSON equality + decision column
  + status column + a separate `review_generation` counter threaded through every response (state.py:568-594;
  analytics.py:740/753/771/833/842/862; review.py:526). Four mechanisms for one property. Replace with one
  `approvals(task_id, candidate_digest, reviewer, decision, consumed_at)` row and a conditional UPDATE.
- The workspace state machine: pending_review / pending_data_grant / data_granted / pending_publication /
  published / rejected / failed crossed with stages source_approval / data_grant / submission / publication /
  admitted (analytics.py:433-434, 750-768, 833-861, 1069-1106). Two vocabularies for one lifecycle; collapse
  to one enum.
- The admission-record pinning (admission.py:1325-1400, expected_revision threaded through authoring.py,
  query.py, analytics.py): re-resolves snapshot digests, source approval and storage-binding endpoints on  every query. On a single server, resolve once at open and cache the pinned record — the per-query
  environment re-resolution is paranoia the deployment model does not need.
- The XLSX importer (spreadsheet_import.py, 769 LOC): XML pre-parse for bounds (225-308), cell-order
  validation, shared-formula refusal, staged worker subprocess, digest-keyed caching. It refuses shared
  formulas — a common real Excel feature — and refuses formula sheets without cached values: a narrow
  synthetic slice at high cost. Replace with openpyxl value extraction plus an explicit formula refusal, or
  drop XLSX until real workbooks demand it.
- The enrichment impact projection (enrichment.py: per-page binding coverage + audience filtering +
  registry-latest binding) layered on a feature whose external lookup is already disabled by default
  (review.html:34-35). Speculative depth for an unproven capability.
- Multi-path file mutation_lock across private/published/registry/artifact roots (review.py:377-382,
  operations.py:123-129) plus a separate SQLite operation-locks dir (operations.py:31). On one server, SQLite
  transactions can coordinate.
- Two authoring implementations of the same thing: the lumio-wiki CLI (cli.py, 10,629 LOC) and the  workspace's own review/approval stack (review.py 1,016 + contributions.py 797 + analytics.py 1,130).
  One should own authoring; the other should call it.
- Cross-product bridge duplication: ariadne/lumio_context.py (1,906 LOC) and lumio-wiki/ariadne_context.py
  (2,415 LOC) implement the same context layer from both sides.
- Hand-rolled HTML in Python: review.py:837-1005 builds the page by string substitution and raw JSON dumps
  against a 68-line placeholder template. Use a small Jinja template and a real line diff.
- The model-disclosure machinery: index.ts:48-136 plus a 564-line disclosure-boundary.test.ts implementing
  session-taint tracking, compaction cancellation and branch-summary cancellation. Real security work in the
  wrong place — move the policy server-side where it can be enforced, and delete most of the client taint
  tracking.
- The orphan ariadne-agent package (1,790 LOC) with an absolute-path tau-mcp dependency. Delete it.
- The 10,629-line lumio-wiki CLI as one module: split it, or delete the subcommands the workspace path never
  uses — the workspace needs read/publish/authoring primitives, not a general CLI.
- The test-selection spread across four configs (root pyproject testpaths, products/lumio/pytest.ini, the
  ariadne member config, CI running each separately — ci.yml:9-153) with 12,723 LOC of integration tests over
  6 modules; integration/tests/lumio_local_context.py alone is 4,024 LOC.
```

---

```
OVERALL: PARTIALLY ACHIEVED
SUMMARY: The governance spine is real, not planned: the compile-gated OSI query path, the ODCS v3.2.0 pin, the
browser-only approval with a one-use action digest, live per-capability checks, and a backup/restore that
preserves admitted content are all traced, working code. But the platform as stated does not exist: the agent-
facing surface has no vector search, no metric/context discovery and no entity IDs, so an agent cannot use it
without already knowing every name in it; the data path needs four browser reviews to make one CSV queryable;
the disclosure policy is enforced only in the client; the human-only admissions are self-confirmable from any
shell on the host; and the two-human journey has never been run with two humans. On top of that the
"maximally simple" inventory is off by roughly a factor of three.
BIGGEST_GAP: Discovery on the agent-facing surface. The workspace MCP exposes no list_metrics, discover,
search_context, read_context_page or page index, returns no entity IDs, and has no vector search — so an
agent can read a page only if it already knows its exact title, and cannot prepare an enrichment because the
entity IDs it needs are never returned. The capability exists in ariadne and lumio-wiki; it just is not on the
one surface agents connect to. Everything else on this list is a smaller version of the same problem.
SIMPLICITY_AUDIT: The claim does NOT hold. 2 mandatory long-running processes (ASGI + TLS terminator) plus git
and converter subprocesses; 9-10 durable stores (SQLite, Git repo + worktrees, DuckDB, published dir, profile,
registry, artifacts, lock dir, optional LanceDB, optional S3); 5 env vars read-only / 10 full analytics /
16 Entra, before S3 and LLM credentials; 4 workspace packages + 1 orphan + 1 TS client; no deployment artifact
for the workspace itself; and a genuine setup cost of half a day to a day. The stated inventory of "one
server, one SQLite, one Git, DuckDB, LanceDB" matches neither the code nor the docs.
TOP_3_SIMPLIFICATIONS:
  1. Collapse the four-review data pipeline into one browser review that binds source identity + grant +
     candidate in a single action digest, and collapse the seven statuses × five stages into one enum.
     Biggest UX and LOC win in the codebase.
  2. Collapse the four surfaces (lumio-wiki CLI, lumio-wiki MCP, ariadne-serve MCP, lumio-workspace) into one
     workspace MCP that also exposes discovery: list_metrics, search_context, read_context_page, page index,
     entity IDs, graph/ontology, and vector search. That deletes most of cli.py's 10.6k LOC and fixes the
     biggest functional gap at the same time.
  3. Move the disclosure allowlist and the human-only admission boundary off the client and off the shell:
     enforce the allowlist in the server, and make publication/admission require a server-issued browser
     capability instead of being runnable from any host shell.
MISSING_COUNT: 33
```

**Bottom line:** this is not a finished platform, but it is not vaporware either — the governance engine is real and unusually well built, and the gaps are concentrated rather than diffuse. It is a governance engine with the consumption layer and the ergonomics missing. The highest-value next work is not more governance: it is exposing what already exists (discovery, entity IDs, vector search) on the one MCP surface agents actually use, and cutting the four-review ceremony to one.

💭 **Reasoning:**
```
Confirmed: for S3 storage profiles, the endpoint/region values are re-resolved and compared (admission.py:1364-1385). But for a `postgres` source, the identity binds only `connection_env` (the NAME of the env var, not the DSN value) — authoring_sources.py:117-118 `entry["connection_env"] = src.connection_env`. The DSN value is resolved at runtime (sources.py:1020 `dsn = os.environ.get(src.connection_env)`). So changing the DSN value in the env var while keeping the same var name points at a different database with an unchanged approval digest. That's a real gap — the subagent found it, and I've verified it in code. The storage_bindings mechanism only covers S3 storage profiles (authoring_sources.py:86-94 skips entries without a `storage` dict).

Now let me finalize. I have everything I need. Let me write the final report incorporating:
1. My own findings (Areas 1-7, already written in my previous response)
2. Subagent confirmations
3. New findings from subagents that I verified:
   - **Revoking `read` does NOT remove member access** — capabilities are independent, each route checks only its own capability. Verified: state.py:341-364 (revoke deletes ONE capability row), app.py:614 checks only "contribute", app.py:716 checks only "review". So a user with only "contribute" revoked of "read" can still upload and prepare contributions. This is a real finding I missed.
   - **Restore does not invalidate pending review tasks** — operations.py:186-190 deletes issued/pending review_actions and browser sessions, but leaves operations in pending_review. Already noted by me, but the subagent confirmed via probe.
   - **lumio-wiki publish --confirm <digest>** is a third CLI approval path — cli.py:5305-5345. I found ariadne-admit --confirm and ariadne-authoring approve-sources; the subagent found the lumio-wiki publish path. Verified by reading the CLI code.
   - **DSN not pinned by approval digest** — verified above.
   - **Binary source inspection fails** — review.py:619 `original.decode("utf-8")` on a PDF/DOCX. Actually let me be careful: review.py:611-621 catches UnicodeDecodeError and renders "Original passage unavailable". And review.py:362 catches UnicodeDecodeError → SourceInspectionError. So for PDF/DOCX the source inspection is effectively broken — it can't show the original. That's a legitimate UX finding.
   - **Enrichment needs entity IDs that workspace search/read doesn't return** — verified: read_knowledge/search_knowledge return title/path/citation but no entity id (app.py:327-362), while prepare_enrichment takes page_ids which are entity IDs (enrichment.py:190 `by_id = {page.id: page ...}`). This is a REAL blocker — an agent cannot discover entity IDs through the workspace API. This strengthens my BIGGEST_GAP.
   - **Profiler sample bound is a profile-sample bound not physical IO bound** — profiler.py:484-500 opens the registry/connection and catalogs before selector filtering, and the 100-row sample is a LIMIT-ed copy for stats. Verified.
   - **Profile reports sample stats, not full-table stats** — profiler.py:445 `tables[key].update(sampled=True, sample_limit=sample_rows)` — it IS labeled. Good, that's honest. But row_count for a sampled profile is the sample's count (100), which could mislead. Actually it's labeled `sampled: True`. Moderate.
   - **Steps: 13 application calls** for upload→query (subagent count, more granular than mine).
_... (15 more lines)_
```

All three sub-audits are in and I've independently verified their load-bearing claims. Here is the consolidated final report, with the subagent findings folded in and my earlier statements corrected where they were wrong.

---

# Ariadne–Lumio Unbiased Goal Audit — Final

*Method: direct source reading only. Planning docs/ADRs/specs were used only as pointers, never as evidence. Three parallel sub-auditors covered data, knowledge, and agent/boundary; I verified their headline claims in source myself (marked ✓ where I did).*

---

```
AREA: 1 — Data pipeline (can an agent actually get data queryable?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - Upload: app.py:606 `POST /uploads` → app.py:614 capability check → intake.py (SHA-256, retry key,
25 MiB cap, suffix allowlist). Exact bytes, not multipart.
  - Source request: app.py:437 `prepare_data_source` → analytics.py:294-468. CSV/JSON/Parquet use native
    handlers; XLSX requires explicit `sheets` (analytics.py:334-339 — actionable error).
  - Profile: analytics.py:470-509 → `self.api.inputs(sample_rows=100)` → profiler.py:391-412/484-516.
    Measured schema/row/type facts, with the approval digest re-checked before AND after
    (analytics.py:478, 493-500). ✓
  - Browser approval: app.py:706-750 GET+POST, gated on `permits(..., "review")` (app.py:716), HTTPS
    (app.py:714), same-origin Origin check (app.py:724), form-urlencoded only (app.py:726), one-use
    action digest bound to task+actor+binding (state.py:543-594, issued only on the browser GET review.py:328).
  - Governed query: query.py:441 `sql = render(self._metrics[name]["model"], ...)` — compiled by the project's
    own sqlglot renderer from served OSI models, never from tool input; query.py:444 single-statement guard;
    query.py:457 EXPLAIN bind; query.py:465 grain guard. Ad-hoc path additionally runs the static
    IO-authority boundary (sql_authority.py:390-620: relation allowlist, function allowlist, no side effects).
  - Pinned + cited + honest status: analytics.py:554-558 `pinned: {commit, source_digest}`;
    query.py:476 `"governed": True`; query.py:1264 & query.py:1448 `"governed": False`;
    query.py:485 `_admission_view`; context.py:330-388 attaches metric page + policies + signals.
GAPS:
  - NOT under 5 steps. Upload → query is 13 application calls and 4 browser reviews:
    upload(1) → prepare_data_source(2) → review GET(3) → review POST(4) → review GET(5) → review POST(6)
    → profile(7) → prepare_contribution(8) → review GET(9) → review POST(10) → review GET(11) →
    review POST(12) → query_data(13). Stage transitions at analytics.py:735-775 (source_approval→
    data_grant) and analytics.py:777-874 (submission→publication). "Bureaucracy" is accurate.
  - The reviewer approves a source they have NOT seen profiled: `profile_data_source` requires status
    `data_granted` (analytics.py:470-476 → analytics.py:185-196), i.e. both reviews must precede profiling.
  - Approval + grant + profiling admit nothing. `query_data` requires the fully admitted revision
    (analytics.py:520 `admission.resolve_admission`).
  - SOURCE IDENTITY IS NOT FULLY PINNED (✓ new finding): the resolved identity binds the *name* of the
    credential env var, not its value — authoring_sources.py:117-118 `entry["connection_env"] =
    src.connection_env`, while the DSN is resolved at runtime (sources.py:1020 `os.environ.get(...)`).
    `storage_bindings_from_identity` (authoring_sources.py:80-95) re-resolves endpoint/region for S3
    storage profiles ONLY (it skips entries with no `storage` dict) and admission.py:1364-1385 compares
    those. A Postgres DSN changed under the same variable name points at a different database with an
    unchanged approval digest. Severity: major.
  - The 100-row profile bound is a *sample* bound, not a physical-I/O bound: profiler.py:484-500 opens the
    connection and catalogs the approved registry BEFORE the selector narrows it, and the sample is a
    LIMIT-ed copy (profiler.py:505-514). Profile stats are labeled `sampled: true, sample_limit: 100`
    (profiler.py:445) — honest, but "bounded" is weaker than it sounds.
  - XLSX sheets are CONVERTED BEFORE EITHER APPROVAL (analytics.py:210-215, 377-387).
  - Env vars: 5 for read-only local-token (app.py:163-181); 10 for the full analytics path (adds
    AUTHORING_PATH, PRIVATE_PROFILE, ANALYTICS_PROJECT_ID/PATH/SOURCE_BINDINGS — app.py:364-385);
    12 counting the optional PRIVATE_ROOT and NAMESPACE; +6 identity vars in Entra mode (auth.py:39-51);
    plus per-storage S3 vars and OPENAI_* for authoring (author.py:42-51).
  - Generic (non-actionable) refusals: app.py:448 "workspace contribution is not available" and app.py:616
    (same string on upload) name neither the missing permission nor the identity.
```

```
AREA: 2 — Knowledge pipeline (can an agent author and publish knowledge?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - Submit: app.py:606 upload → intake.py → authoring_journey.extract_source. PDF = LiteParse
    (source_processor.py:341-351), DOCX = AnyDoc (source_processor.py:367-380 — NOT MarkItDown, correcting
    my earlier note; MarkItDown handles other formats), UTF-8 text needs no converter. Converters are
    optional extras but included in lumio-workspace's deps (pyproject.toml:8-10); a missing one produces
    an actionable `pip install 'lumio-wiki[documents]'` (source_processor.py:215-228).
  - CORRECTION to my earlier report: extraction yields TEXT, not structured pages. The agent must author the
    complete Markdown pages + frontmatter itself (contributions.py:196-235, 647-708; authoring_journey.py:565-647).
    Frontmatter/tags/ontology refs are validated at review, not generated.
  - Enrichment: app.py:494 `prepare_enrichment(page_ids, expected_version, request_key)` → enrichment.py:92-215.
    Bounded to 20 pages / 200k chars / 40 claims. External lookup disabled by default (review.html:34-35).
  - Review diff: review.py:937-953 renders per-page unified `body_diff` plus "Semantic and Claim changes"
    JSON; the analytics variant (review.py:837-893) binds native submission + candidate + expected/observed
    version + overall digest.
  - Publish → immediately readable: review.py:527-552 → publication.py:58-73 atomically moves the destination
    pointer; reads open a fresh snapshot from that destination each call (app.py:280, 306-313).
  - Reject preserves published state: review.py:554-568 sets `published: False` and never calls publish;
    analytics.py:718-733 `_reject` likewise.
GAPS:
  - ★ ENTITY IDs ARE NOT DISCOVERABLE (✓ new, and it breaks a documented flow): `prepare_enrichment` requires
    `page_ids`, and enrichment.py:190 matches them against `page.id` — the Entity ID. But the workspace's
    read/search tools return only title/path/citation (app.py:327-362) and never the entity ID. An agent
    therefore cannot construct a valid enrichment request from workspace output alone, while    `read_knowledge`/`search_knowledge` are the only discovery surfaces it has. Severity: major.
  - ★ BINARY SOURCES ARE UNREVIEWABLE (✓ new): the review source-inspection path UTF-8-decodes the ORIGINAL
    bytes (review.py:619 `fetch_verified_artifact(...).decode("utf-8")`) and the inspect_source route does the
    same (review.py:360-363). For a PDF or DOCX this raises UnicodeDecodeError and renders "Original passage
    unavailable" / "the exact private source resources are unavailable". The reviewer cannot see the document
    they are approving. Severity: major.
  - Rejection does NOT restore private operational state: source versions and originals are already registered
    and retained at preparation time (authoring_journey.py:701-750), so a rejected new source ID can affect a
    later conflicting proposal. Published state is untouched; private state is not rolled back.
  - Review UI is expert-only. templates/review.html is 68 lines, no stylesheet, and opens with a `<dl>` of
    git SHAs and digests ("Exact admitted review base", "Native submission review", "Exact candidate",
    "Expected active version", "Native authoring review"). The analytics path dumps raw JSON into `<pre>`
    blocks (review.py:879-885). Actual instruction text: "Review every displayed change and consequential
    action. This page alone authorizes nothing." A non-technical human sees hashes.
  - LanceDB vector search is NOT on the workspace surface. `rg 'lancedb|vector|embedding'` over
    lumio-workspace/src/ → nothing. `search_knowledge` is lexical zero-index (app.py:347-362 →
    page_search.py:82-93, whose own docstring calls it "the LanceDB-free core of page search"). Even
    lumio-wiki's MCP server exposes no vector tool — `status_rows` hard-codes `retrieval: "zero-index"`
    (mcp_server.py:313-320). Semantic/hybrid exists ONLY in the lumio-wiki CLI (cli.py:620, 2954, 3125)
    with an embedder dependency. The goal's "LanceDB for retrieval" through one workspace is not met.
  - Entity/claim/evidence graph and ontology are not exposed to agents on the workspace. lumio-wiki's own MCP
    has `related`, `paths`, `index`, `hot` (mcp_server.py:346-396); the workspace exposes none of them.
  - No published-version history, diff, or rollback from the workspace (publication.py moves a pointer forward;
    `LUMIO_WORKSPACE_PUBLISHED_VERSION` is a read pin, app.py:168).
  - PDF → searchable is 5 interactions + 1 verification (upload → read_source_material → author pages →
    prepare_contribution → GET review → POST review → search). Acceptable. The 4-review dance is data-specific.
```

```
AREA: 3 — Agent consumption (can an agent actually use this daily?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - The Pi extension is real and targets the real service: index.ts:56-63 `pi.registerMcpServer("lumio-workspace",
    { url: `${url}/mcp`, headers: { Authorization: "Bearer ${LUMIO_WORKSPACE_API_TOKEN}" } })`; Entra OAuth
    path index.ts:66-83. It does NOT start the service (package.json only registers the extension).
  - Search: app.py:347-362 `search_knowledge` → snapshot.search_pages → lexical ranking (page_search.py:82).
  - Metrics with context/citations: app.py:476 `query_data` → analytics.py:511 → query.py; context attached
    at query.py:477-479 → context.py:330-388.
  - Proposals: prepare_contribution (app.py:518), prepare_data_source (app.py:437), prepare_enrichment (app.py:494).
  - Honest labels: governed True at query.py:476/1043/1143, False at query.py:1264/1448; ad-hoc also reports
    `not_saved`; proposals report pending + `published: False`. "governed: true means admitted, not
    independently value-attested" (context.py:381-383).
  - A browser credential can never be minted from an API token: app.py:882 authenticates the login form with
    purpose="browser"; state.py:332-338 refuses a purpose mismatch.
GAPS:
  - ★ NO DISCOVERY TOOL — the largest gap. The workspace MCP has no list_metrics, discover, search_context,
    read_context_page, or page index, although ariadne's own MCP server has all five (serve.py:528-628).
    An agent cannot learn which governed metrics exist, cannot read the context layer as pages, and cannot
    look up ODCS v3.2.0 contracts or semantic terminology as first-class retrieval. Contracts are only
    reachable embedded inside a metric answer (query.py:477, context.py:330-388). Combined with the
    entity-ID gap in Area 2, an agent cannot navigate the knowledge base at all beyond literal title lookup.
  - The packaged skill (ariadne/skill_assets/SKILL.md, 765 lines) documents the STANDALONE ariadne CLI/MCP,
    not the workspace flow. Both skills teach local Git/CLI workflows rather than workspace MCP calls.
  - The agent's actual operating instructions are a ~1000-char prose wall emitted as a UI toast
    (index.ts:236-252).
  - Install/connect is manual: the extension is `private: true`, no publish/install mechanism; the operator
    places the directory in Pi's trusted-extension path, sets 4-5 env vars, reloads Pi, runs /workspace and
    /mcp. ~8-10 steps before the agent reads anything.
  - The model allowlist is CLIENT-SIDE ONLY (index.ts:48-136). The server never sees
    LUMIO_WORKSPACE_ALLOWED_MODELS. The client README admits it: "trusted-client disclosure policy, not remote
    attestation." A modified client or any other MCP client bypasses it entirely. Severity: blocker.
  - The API token leaks into Pi's shell environment — documented as an "accepted interim limitation" in both
    the client README and docs/howto-shared-workspace.md:1-3. Real blocker for deployment.
  - Workspace errors are flattened to strings (app.py:490, 515, 580), discarding ariadne's structured codes.
  - The agent needs internal vocabulary: project/source-task IDs, two distinct grants (source vs data),
    retry keys, four review stages, pinned releases (index.ts:190-204, 235-252).
```

```
AREA: 4 — Collaboration model (does the human-agent boundary actually hold?)
VERDICT: PARTIALLY WORKS
EVIDENCE:
  - An API token CANNOT approve. The MCP tool list has no approve/decide tool; approval lives only in the
    browser POST (app.py:706-750). The action digest is issued ONLY by a browser GET (review.py:328); the POST
    additionally requires HTTPS (app.py:714), same-origin Origin (app.py:724), form encoding (app.py:726),
    and `permits(..., "review")` (app.py:716). ✓ probed: API-token review POST → 401; API-token browser
    login → 401.
  - Self-approval is browser-only: review.py:395-403 permits actor==submitter only when
    `is_single_person_workspace` (state.py:622-628: exactly one distinct membership row) AND the actor
    holds "contribute" — and it still executes through the browser route.
  - Backup/restore: operations.py:110-156 copies SQLite state, private tree, authoring repo, published
    destination, profile, registry, artifacts, analytics project and bindings under the activation mutation
    locks; restore (operations.py:193-254) re-links worktrees, rebases profile paths, and
    `_invalidate_restored_actions` (operations.py:186-190) deletes every issued/pending review action and all
    browser sessions. Admitted content is preserved.
  - Reviewer surfaces: browser only (/auth/login, /workspace, /setup, /review/{task}, /review/{task}/source/…,
    /membership). The CLI is operator-side, not reviewer-side.
GAPS:
  - ★ REVOKING `read` DOES NOT REMOVE MEMBER ACCESS (✓ new). Capabilities are independent rows and each
    route checks only its own: state.py:356-364 `DELETE … AND capability = ?` removes exactly one grant;
    app.py:614 checks only "contribute"; app.py:716 checks only "review"; app.py:912 checks only "read".
    A member whose "read" is revoked but who retains "contribute" can still upload and prepare contributions;
    one retaining "review" can still review. There is no revoke-all operation. The stated goal "revoking a
    member's access immediately blocks their agent and browser session" is FALSE for partial revocation.
    Full mitigation exists — `local-user disable` (state.py:205-225) invalidates credentials and sessions on
    the next check — but the model is one-grant-at-a-time with no cascade. Severity: major.
  - ★ RESTORE DOES NOT INVALIDATE PENDING REVIEW TASKS (✓ probed). operations.py:186-190 deletes
    issued/pending ACTIONS and browser sessions but leaves `operations` rows in `pending_review`; a fresh
    browser GET can then re-issue an action and approve the restored candidate. Actions are voided, tasks
    are not. Severity: major.
  - ★ THE HUMAN GATE IS A DEPLOYMENT ASSUMPTION, NOT AN ENFORCED BOUNDARY (✓ third bypass path found).
    Three shell paths self-confirm with no human: `ariadne-admit --confirm` (admission.py:1440-1500),
    `ariadne-authoring approve-sources` (authoring_sources.py:371, authoring.py:332), and
    `lumio-wiki publish … --confirm <digest>` (cli.py:5305-5345 — the preview prints "Reading this review does
    not authorize publication; authorize the displayed state explicitly with --confirm", then publish_revision
    runs). An agent with a shell on the server host can approve its own work. Severity: blocker.
  - Entra browser sessions are not revocable per-request: they carry no `local_credential_id`, so
    state.py:205 skips the credential check; only the 1-hour TTL (app.py:61) and IdP expiry apply.
  - The two-human journey has NEVER been run with two humans — products/lumio/examples/shared-workspace-journey/README.md:12-31
    says so outright: "one agent driving every identity proves nothing about human approval". Two real humans,
    installed Pi, private HTTPS, and the Entra leg are all listed as open. No Entra tenant fixture exists.
  - Reviewer UX is poor (Area 2): unstyled 68-line page, SHA/JSON dumps.
```

```
AREA: 5 — Operational simplicity (is it actually "maximally simple"?)
VERDICT: DOES NOT WORK
EVIDENCE:
  - Processes: 1 ASGI service (uvicorn via `lumio-workspace serve`, __main__.py:87) + a MANDATORY TLS
    terminator (external_url must start https://, app.py:184; every browser route requires https,
    app.py:714/791) + the `git` binary as a subprocess + optional converter subprocesses (LiteParse, AnyDoc).
    The ariadne query runtime runs IN-PROCESS (analytics.py:17 imports ariadne.query) — that part is simple.
  - Stores: SQLite state, authoring Git repo + per-task worktrees, DuckDB file(s), published KB dir, private
    profile JSON, source registry dir, artifact store dir, filesystem lock dir (operations.py:30-41), optional
    LanceDB index, optional S3 buckets = 9-10, not 4.
  - Env vars: 5 read-only / 10 full analytics local-token / 16 Entra-analytics, plus S3 + OPENAI.
  - Packages: 4 uv members (pyproject.toml:11-16) + 1 orphan + a TS extension.
  - NO container/service definition for lumio-workspace — only for the ariadne MCP server
    (products/ariadne/deploy/compose.yaml:1-49). The actual platform has no deployment artifact.
  - sysadmin effort: Python 3.14 + uv, 4 packages, TLS + private DNS, author a Lumio KB (lumio.yaml,
    .lumio-authoring.yaml, namespace), write private profile JSON, create the analytics Git project with
    ariadne.yaml + OSI models + DuckDB, install DuckDB httpfs for S3 (ci.yml:143-146), write source bindings,
    publish an initial KB, then create users + memberships + two credentials per person. Half a day to a day;
    several analytics steps have neither code nor documentation.
GAPS:
  - products/ariadne/packages/ariadne-agent is ORPHANED and uninstallable elsewhere: not a uv member
    (pyproject.toml:11-16), not in CI, and pyproject.toml:32 pins
    `tau-mcp = { path = "/home/volker/coding/tau-mcp" }` — an absolute path on the author's machine.
    1,790 LOC of unreferenced code.
  - Stale untracked build output (root build/lib/ariadne, root dist/ariadne_data-0.4.1*, root ariadne-agent/).
  - ariadne/author.py:23 hardcodes    `ENV_PATH = Path(os.environ.get("ARIADNE_ENV", "/home/volker/coding/ariadne/.env"))` — a machine-specific
    default inside a published package.
  - The stated inventory ("one server, one SQLite, one Git, DuckDB, LanceDB") matches neither the code nor    the docs: LanceDB is absent from the workspace path, and there are ~10 stores, not 4.
  - Four overlapping surfaces: lumio-wiki CLI (10,629 LOC), lumio-wiki MCP, ariadne-serve MCP,
    lumio-workspace.
```

---

```
MISSING:
- Vector/semantic search on the workspace MCP: the goal's retrieval story; the workspace imports no vector
  code and search is lexical zero-index (app.py:347-362; mcp_server.py:313-320). [blocker]
- Metric + context discovery tools on the workspace MCP (list_metrics / discover / search_context /
  read_context_page / page index): ariadne has all five on a different server (serve.py:528-628). [blocker]
- Entity IDs in discovery results: prepare_enrichment requires page.id (enrichment.py:190) which read/search
  never return (app.py:327-362) — enrichment is unreachable from workspace output. [blocker]
- Server-side enforcement of the model allowlist: client-side only (index.ts:48-136). [blocker]
- A real multi-user qualification run (two humans, installed Pi, private HTTPS): never performed
  (shared-workspace-journey/README.md:12-31). [blocker]
- Host-level enforcement that human-only approvals cannot be self-confirmed by an agent: three shell paths
  exist (admission.py:1440, authoring_sources.py:371, cli.py:5305-5345). [blocker]
- API-token isolation from the agent's shell/model context: documented accepted interim limitation. [blocker]
- Pinned database endpoint identity at approval time: the digest binds the env var NAME, not the DSN value
  (authoring_sources.py:117-118 vs sources.py:1020); storage re-resolution covers S3 only
  (authoring_sources.py:80-95). [major]
- Revoke-all / cascading revocation: revoking one capability leaves the others live (state.py:356-364). [major]
- Rendered original documents in review: binary sources cannot be inspected (review.py:360-363, 619). [major]
- Health/readiness endpoint on the workspace service: ariadne-serve has /healthz and /readyz
  (serve.py:1180-1184); lumio-workspace has none. [major]
- Metrics, structured logging, tracing: no observability surface in either service. [major]
- Reviewer notification / "something is waiting" queue: no queue view, webhook, or email. [major]
- Rate limiting / quotas on /uploads and the MCP surface: no limiter anywhere. [major]
- Published-knowledge version history and rollback: no list/diff/revert API (publication.py:38-58). [major]
- Audit-trail query surface: the facts exist across operations/review_actions and native receipts, but no
  human-readable view. [major]
- OpenAPI/Swagger for the browser API: every custom route is include_in_schema=False (app.py:606, 642, 706,
  752, 776, 893, 906). [major]
- User management beyond the CLI: local users only via `local-user create` (__main__.py:99-103); /membership
  assigns capabilities to users that already exist (app.py:776-844). No self-registration, no reset, no
  deactivation UI. [major]
- Scheduled/automated refresh of live database and S3 sources: refresh means a new upload + new reviewed
  selection every time (index.ts:196-199 states this). [major]
- Agent-facing "connect this Postgres/DuckDB/SQLite/S3 bucket" operation: only operator-pre-declared handles
  work (analytics.py:294-468). [major]
- Machine-readable error codes in workspace MCP responses: structured refusals flattened to strings
  (app.py:490, 515, 580). [major]
- Published, installable Pi extension package (private:true, manual placement). [major]
- Deployment artifact for the workspace itself (container/compose/systemd). [major]
- A readable, styled review UI (68 unstyled lines + raw JSON dumps). [major]
- Two-identity test of the human approval path. [major]
- Private full-text search across published content (page-level lexical only). [minor]
- Data visualization for humans: no chart surface. [minor]
- Knowledge export from the workspace to other formats. [minor]
- Client libraries beyond Pi: no Python/TS SDK, VS Code extension, web app, or mobile. [minor]
- Localization: all UI strings and errors hardcoded English. [minor]
- Pagination beyond a hard limit of 20 results (app.py:349-350). [minor]
- Multi-workspace per deployment: one workspace_id, one state file, one config (app.py:163-181). [minor]
- Private-state rollback on rejection (rejected source IDs persist). [minor]
- Cleanup of the orphan ariadne-agent package and stale root build/dist artifacts. [minor]
```

```
OVER-COMPLICATED:
- The four-review data pipeline: source_approval → data_grant → submission → publication
  (analytics.py:741-874). Two of the four exist to sequence two permissions that one exact-candidate
  review already binds. Collapse to one review binding source identity + grant + candidate. [~200 LOC, 4 UI
  states, and half the agent-visible steps removed]
- The review-action binding system: one-use nonce (state.py:543-566) + binding-JSON equality + decision column
  + status column + a separate `review_generation` counter threaded through every response (state.py:568-594;
  analytics.py:740/753/771/833/842/862; review.py:526). Four mechanisms for one property. Replace with one
  `approvals(task_id, candidate_digest, reviewer, decision, consumed_at)` row and a conditional UPDATE.
- The workspace state machine: pending_review / pending_data_grant / data_granted / pending_publication /
  published / rejected / failed crossed with stages source_approval / data_grant / submission / publication /
  admitted (analytics.py:433-434, 750-768, 833-861, 1069-1106). Two vocabularies for one lifecycle; collapse
  to one enum.
- The admission-record pinning (admission.py:1325-1400, expected_revision threaded through authoring.py,
  query.py, analytics.py): re-resolves snapshot digests, source approval and storage-binding endpoints on  every query. On a single server, resolve once at open and cache the pinned record — the per-query
  environment re-resolution is paranoia the deployment model does not need.
- The XLSX importer (spreadsheet_import.py, 769 LOC): XML pre-parse for bounds (225-308), cell-order
  validation, shared-formula refusal, staged worker subprocess, digest-keyed caching. It refuses shared
  formulas — a common real Excel feature — and refuses formula sheets without cached values: a narrow
  synthetic slice at high cost. Replace with openpyxl value extraction plus an explicit formula refusal, or
  drop XLSX until real workbooks demand it.
- The enrichment impact projection (enrichment.py: per-page binding coverage + audience filtering +
  registry-latest binding) layered on a feature whose external lookup is already disabled by default
  (review.html:34-35). Speculative depth for an unproven capability.
- Multi-path file mutation_lock across private/published/registry/artifact roots (review.py:377-382,
  operations.py:123-129) plus a separate SQLite operation-locks dir (operations.py:31). On one server, SQLite
  transactions can coordinate.
- Two authoring implementations of the same thing: the lumio-wiki CLI (cli.py, 10,629 LOC) and the  workspace's own review/approval stack (review.py 1,016 + contributions.py 797 + analytics.py 1,130).
  One should own authoring; the other should call it.
- Cross-product bridge duplication: ariadne/lumio_context.py (1,906 LOC) and lumio-wiki/ariadne_context.py
  (2,415 LOC) implement the same context layer from both sides.
- Hand-rolled HTML in Python: review.py:837-1005 builds the page by string substitution and raw JSON dumps
  against a 68-line placeholder template. Use a small Jinja template and a real line diff.
- The model-disclosure machinery: index.ts:48-136 plus a 564-line disclosure-boundary.test.ts implementing
  session-taint tracking, compaction cancellation and branch-summary cancellation. Real security work in the
  wrong place — move the policy server-side where it can be enforced, and delete most of the client taint
  tracking.
- The orphan ariadne-agent package (1,790 LOC) with an absolute-path tau-mcp dependency. Delete it.
- The 10,629-line lumio-wiki CLI as one module: split it, or delete the subcommands the workspace path never
  uses — the workspace needs read/publish/authoring primitives, not a general CLI.
- The test-selection spread across four configs (root pyproject testpaths, products/lumio/pytest.ini, the
  ariadne member config, CI running each separately — ci.yml:9-153) with 12,723 LOC of integration tests over
  6 modules; integration/tests/lumio_local_context.py alone is 4,024 LOC.
```

---

```
OVERALL: PARTIALLY ACHIEVED
SUMMARY: The governance spine is real, not planned: the compile-gated OSI query path, the ODCS v3.2.0 pin, the
browser-only approval with a one-use action digest, live per-capability checks, and a backup/restore that
preserves admitted content are all traced, working code. But the platform as stated does not exist: the agent-
facing surface has no vector search, no metric/context discovery and no entity IDs, so an agent cannot use it
without already knowing every name in it; the data path needs four browser reviews to make one CSV queryable;
the disclosure policy is enforced only in the client; the human-only admissions are self-confirmable from any
shell on the host; and the two-human journey has never been run with two humans. On top of that the
"maximally simple" inventory is off by roughly a factor of three.
BIGGEST_GAP: Discovery on the agent-facing surface. The workspace MCP exposes no list_metrics, discover,
search_context, read_context_page or page index, returns no entity IDs, and has no vector search — so an
agent can read a page only if it already knows its exact title, and cannot prepare an enrichment because the
entity IDs it needs are never returned. The capability exists in ariadne and lumio-wiki; it just is not on the
one surface agents connect to. Everything else on this list is a smaller version of the same problem.
SIMPLICITY_AUDIT: The claim does NOT hold. 2 mandatory long-running processes (ASGI + TLS terminator) plus git
and converter subprocesses; 9-10 durable stores (SQLite, Git repo + worktrees, DuckDB, published dir, profile,
registry, artifacts, lock dir, optional LanceDB, optional S3); 5 env vars read-only / 10 full analytics /
16 Entra, before S3 and LLM credentials; 4 workspace packages + 1 orphan + 1 TS client; no deployment artifact
for the workspace itself; and a genuine setup cost of half a day to a day. The stated inventory of "one
server, one SQLite, one Git, DuckDB, LanceDB" matches neither the code nor the docs.
TOP_3_SIMPLIFICATIONS:
  1. Collapse the four-review data pipeline into one browser review that binds source identity + grant +
     candidate in a single action digest, and collapse the seven statuses × five stages into one enum.
     Biggest UX and LOC win in the codebase.
  2. Collapse the four surfaces (lumio-wiki CLI, lumio-wiki MCP, ariadne-serve MCP, lumio-workspace) into one
     workspace MCP that also exposes discovery: list_metrics, search_context, read_context_page, page index,
     entity IDs, graph/ontology, and vector search. That deletes most of cli.py's 10.6k LOC and fixes the
     biggest functional gap at the same time.
  3. Move the disclosure allowlist and the human-only admission boundary off the client and off the shell:
     enforce the allowlist in the server, and make publication/admission require a server-issued browser
     capability instead of being runnable from any host shell.
MISSING_COUNT: 33
```

**Bottom line:** this is not a finished platform, but it is not vaporware either — the governance engine is real and unusually well built, and the gaps are concentrated rather than diffuse. It is a governance engine with the consumption layer and the ergonomics missing. The highest-value next work is not more governance: it is exposing what already exists (discovery, entity IDs, vector search) on the one MCP surface agents actually use, and cutting the four-review ceremony to one.