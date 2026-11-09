**OVERALL: PARTIALLY ACHIEVED.** The repository contains substantial working data, knowledge, and review machinery, but the stated platform is not ready as a complete, safe, self-service workspace. I reproduced failures in first-time knowledge publication, restricted-page access, and publication after backup/restore; the managed workspace also does not expose LanceDB retrieval.

This audit examined checkout `2f5bc9708f0a7fad33d1f6483c239b8f3116ce9d`. I traced implementation paths and ran disposable local checks through the real ASGI/MCP application. I did not test a deployed Pi-to-workspace connection, a real Entra tenant, PostgreSQL, S3, or representative customer workbooks. Consequently, the findings below do not establish production readiness or prove the absence of every possible defect.

## AREA 1: Data pipeline

**VERDICT: PARTIALLY WORKS**

**EVIDENCE:** The workspace accepts bounded CSV, JSON, Parquet, and XLSX uploads, and its source registry supports SQLite, DuckDB, PostgreSQL, and S3-backed file and table families. Source approval and a separate caller data grant are checked before profiling. Governed metric execution pins an admission, compiles through the semantic layer, checks for a single statement, binds the result, and returns context and governance status. [Upload types and limits](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/intake.py:17), [source connections](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/sources.py:676), [grant and profile checks](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py:170), [query execution](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/query.py:437).

A focused native-service check exercised a real temporary SQLite database through source approval, profiling, combined admission, and a governed query with an independently checkable result of `30`; it passed. That check used an already prepared baseline and did not exercise Pi or an external service.

**GAPS:**

- A new uploaded source takes roughly **nine actions** through the full route: upload, prepare source, approve source identity, grant data access, profile, prepare the metric contribution, approve submission, approve publication, and query. That excludes setup and authoring the model. The four browser decisions are explicit in [analytics.py](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py:735).
- External database and S3 sources must already have an operator-controlled binding. An agent cannot submit a new endpoint or storage scope for the owner to provision through the workspace API. [Source selection](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py:101).
- The published pin identifies the admitted commit and source declaration. For a live database, it does **not** freeze the underlying rows or make a result reproducible after the data changes. [Returned pin](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py:511).
- Uploads are capped at 25 MiB. XLSX import also has 64 MiB expanded-size, 200,000-cell, and 20-second limits; it refuses missing formula caches, mixed column types, external links, and certain XML shapes. Formula caches are not recalculated and their freshness is unknown. These are real limitations; I cannot determine compatibility with ordinary customer workbooks without testing a representative corpus. [XLSX limits](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/spreadsheet_import.py:24), [formula handling](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/spreadsheet_import.py:381).
- Many refusals contain useful corrective text, but errors are inconsistent: a fresh workspace’s `workspace_status` returned only “Error executing tool workspace_status,” hiding the actionable missing-baseline cause from the client.
- The compile and statement checks are substantive defenses. Source inspection and one successful query do **not** prove that every possible SQL-injection or concurrent-access path is safe.

## AREA 2: Knowledge pipeline

**VERDICT: PARTIALLY WORKS**

**EVIDENCE:** Text, PDF, and DOCX uploads have extraction paths; an agent can submit authored Markdown pages with typed frontmatter, sources, and claims. The browser review renders content and semantic changes, and publication activates an immutable version. With a manually seeded baseline, I successfully exercised **upload → prepare → browser approval → search** in a disposable workspace. [Intake](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/intake.py:152), [candidate preparation](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/contributions.py:196), [review rendering](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py:896).

**GAPS:**

- **A fresh knowledge-only workspace cannot publish its first contribution through the normal browser workflow.** In a real local journey, setup returned success, upload and preparation succeeded, and the review page returned `409`: “no admitted Git baseline is available for a complete effective review.” Setup creates a Git baseline but does not publish it; review requires an already published baseline. [Setup](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/setup.py:252), [review requirement](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py:208).
- **When analytics is enabled, an ordinary knowledge-only contribution requires an unrelated data-source grant.** I reproduced the MCP refusal. Enrichment has a separate route, but a new document contribution cannot follow the normal knowledge-only path in the combined configuration. [Dispatch](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:517).
- Extraction returns text and sections; the agent must construct the structured page and metadata itself. This is not an automatic document-to-reviewed-pages pipeline. [Extraction](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/intake.py:152).
- The enrichment API requires exact page IDs, but workspace search and read responses expose titles and paths, not those IDs. A new agent cannot reliably discover the IDs through these workspace tools alone. [Enrichment selection](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/enrichment.py:92), [search and read responses](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:326).
- Review of ordinary knowledge includes a body diff. Integrated analytics review presents large escaped JSON blocks and internal hashes; it is usable by a technical reviewer but not self-explanatory for most nontechnical reviewers. [Review template](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/templates/review.html:10), [analytics rendering](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py:837).
- The original-source viewer decodes retained bytes as UTF-8. It cannot display a normal binary PDF or DOCX original through that path. [Source inspection](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py:331).
- Rejection does not call publication, so the inspected rejection path leaves the active version unchanged. A configured fixed published-version pin, however, makes readers continue seeing that old version after later approval. [Decision path](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py:511), [pinned location](/home/volker/coding/ariadne/products/lumio/packages/lumio-wiki/src/lumio_wiki/location.py:419).

A PDF-to-searchable-page journey has at least five substantive actions after setup: upload, extract, author the page, prepare it, and obtain browser approval. The first-publication blocker currently prevents that journey on a fresh knowledge-only workspace.

## AREA 3: Agent consumption

**VERDICT: PARTIALLY WORKS**

**EVIDENCE:** The Pi extension conditionally registers the workspace MCP server, and the workspace exposes knowledge search, page reads, source preparation, profiling, contribution preparation, and queries. Governed and ad-hoc results carry different governance labels. [Pi registration](/home/volker/coding/ariadne/products/lumio/clients/pi-workspace/index.ts:28), [workspace tools](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:315), [ad-hoc result](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/query.py:1438).

**GAPS:**

- The managed `search_knowledge` tool calls lexical page search. The SDK has a LanceDB adapter, but the workspace neither binds it nor exposes semantic or hybrid retrieval. Installing the adapter alone does not make the managed tool use it. [Workspace search](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:346), [SDK retrieval adapter](/home/volker/coding/ariadne/products/lumio/packages/lumio-wiki/src/lumio_wiki/knowledge_base.py:1693).
- The extension implements upload as a **human-invoked slash command**, not a model-callable Pi tool. That command explicitly refuses Entra mode. The HTTP upload endpoint exists, so a separately implemented client can use it, but the configured Pi extension does not provide the requested autonomous upload in both supported auth modes. [Pi upload command](/home/volker/coding/ariadne/products/lumio/clients/pi-workspace/index.ts:138).
- The workspace API does not expose the Core SDK’s metric catalog, semantic graph, ontology traversal, or ODCS contract discovery as first-class tools. An agent must already know identifiers, infer them from pages, or provoke an error that lists metric names.
- The requested Ariadne skill primarily instructs agents to use a **local CLI and Git project**. It does not describe the managed workspace as the primary interface. [Skill](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/skill_assets/SKILL.md:8).
- A local-token Pi connection needs the extension loaded plus URL, auth mode, API token, and an allowed-model configuration; Entra adds client, scope, and metadata configuration. I cannot determine from source whether a new user can complete this in ten minutes, and I did not verify a live Pi connection end-to-end.

## AREA 4: Collaboration and access boundary

**VERDICT: PARTIALLY WORKS**

**EVIDENCE:** Local API and browser credentials have separate purposes; browser review requires a session and the `review` capability. A single active member can approve their own contribution through the browser. Disabling a local user blocked both their API credential and existing browser session in my local check. [Credential validation](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/state.py:290), [review route](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:706), [self-approval check](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/review.py:389).

**GAPS:**

- **Restricted published pages are disclosed to ordinary workspace readers.** I published a valid page marked `visibility: restricted`, issued a user only `read`, and retrieved its complete body through both `read_knowledge` and `search_knowledge`. The workspace does not filter page visibility, although the SDK distinguishes restricted pages in its visibility scope. [Workspace reads](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:326), [SDK visibility scopes](/home/volker/coding/ariadne/products/lumio/packages/lumio-wiki/src/lumio_wiki/okf.py:634).
- Revoking only `read` is **not** a full member removal. In a local HTTP check, the member received `403` from `/workspace` but could still upload because `contribute` remained, and could still reach the review path because `review` remained. The browser membership page revokes capabilities individually. Disabling the local user does block both credentials, but that operation is CLI-only. [Membership surface](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:776), [upload authorization](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:606).
- Disabling a departed local user leaves their membership rows in place. The single-person check counts those rows, so the remaining person can be incorrectly denied self-approval. I reproduced the state check returning false after disabling the other member. [Member count](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/state.py:622).
- **Restore preserves readable published content but breaks subsequent publication.** After a real backup/restore, owner setup reconfirmation, upload, and review, approval returned `409` because the copied active admission receipt still names the old destination. [Restore](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/operations.py:193), [receipt check](/home/volker/coding/ariadne/products/lumio/packages/lumio-wiki/src/lumio_wiki/git_authoring.py:2416).
- Restore deletes issued/pending review-action tokens and browser sessions; it does **not** delete the pending candidate tasks. They remain available for a fresh review. [Invalidation](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/operations.py:186).
- I found no API-token route that directly approves a contribution. That is narrower than proving that **no** bypass exists under every deployment, concurrency, or compromised-client condition.
- There is no reviewer inbox or notification mechanism. The reviewer must receive a task URL out of band. “Request changes” carries no explanation or comment field. The browser workspace landing endpoint returns JSON rather than a review dashboard.

## AREA 5: Operational simplicity

**VERDICT: PARTIALLY WORKS**

**EVIDENCE AND COUNTS:**

- **Processes:** one workspace/Uvicorn process, plus an HTTPS termination boundary; the supplied `serve` command does not configure TLS itself. A local reverse proxy would be a second long-running process. XLSX conversion starts a temporary worker process. [Server command](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/__main__.py:39), [XLSX worker](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/spreadsheet_import.py:700).
- **Stores:** one operational SQLite database; an in-process DuckDB engine and possibly DuckDB/source database files; Git plus worktrees; filesystem stores for uploads, source registry, originals, published snapshots, and receipts. LanceDB is an additional optional store, but is not connected to managed search. External PostgreSQL/S3 are additional when selected.
- **Configuration:** five environment variables are mandatory to start local-token mode. A full fresh analytics-enabled workspace needs five more for authoring/profile/project/bindings, plus a namespace for a new knowledge base: **at least 11**, before proxy, credentials, source-specific settings, and Pi configuration. Entra adds six identity settings. [Workspace configuration](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:140), [Entra configuration](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/auth.py:27).
- **Packages:** the full managed analytics service requires the workspace, wiki, and Ariadne distributions, plus their transitive dependencies and the Pi extension. LanceDB is a fourth project distribution if installed separately; it is not wired into workspace search. [Dependencies](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/pyproject.toml:7).
- **Size:** approximately **99,051 lines** of tracked Python/TypeScript/JavaScript in the four principal managed-service/SDK source trees and Pi client, excluding the separately packaged Ariadne agent and test files. Line count alone is not proof of waste, but it is substantial relative to the incomplete user journeys.
- **Deployment time:** cannot be determined from source alone. The repository contains a Docker/Compose deployment for the standalone Ariadne MCP service, not an equivalent turnkey deployment for the combined workspace. [Compose](/home/volker/coding/ariadne/products/ariadne/deploy/compose.yaml:1).

**GAPS:** Restore copies an originally shared authoring/analytics Git repository into two separate repositories. I reproduced that split; future commits can diverge between the copies. Restore also requires owner setup reconfirmation. [Copy and restore paths](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/operations.py:129).

Every workspace search/read resolves and validates the published snapshot again, then page search scans the page collection. That is a clear scaling cost; its practical impact requires measurement. [Snapshot resolution](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:306), [lexical search](/home/volker/coding/ariadne/products/lumio/packages/lumio-wiki/src/lumio_wiki/page_search.py:82).

## MISSING

These are capabilities absent from, or materially incomplete in, the **managed workspace**. Some exist in standalone SDK or CLI code.

- **First knowledge publication after normal setup:** a new workspace needs an externally seeded published baseline. **[blocker]**
- **Restricted-page access enforcement:** ordinary readers can retrieve pages marked restricted. **[blocker]**
- **One-step complete member offboarding:** browser capability removal is separate per capability; disabling a local user is CLI-only. **[major]**
- **Reliable publication after restore:** copied destination-bound receipts block the next approval. **[blocker]**
- **Preservation of one shared Git repository after restore:** the integrated paths become independent copies. **[major]**
- **Knowledge-only submission in an analytics-enabled workspace:** it requires an unrelated source grant. **[major]**
- **Model-callable Pi file upload:** the extension offers a human slash command. **[major]**
- **Pi upload in Entra mode:** the extension explicitly refuses it. **[major]**
- **Self-service proposal of a new database/S3 connection:** an operator must first create the source binding. **[major]**
- **Automatic document-to-structured-page generation:** extraction exists; page construction is supplied by the agent. **[major]**
- **Browser viewing of binary PDF/DOCX originals:** the current source viewer expects UTF-8 text. **[major]**
- **Discovery of enrichment page IDs through workspace search/read:** enrichment requires IDs those responses omit. **[major]**
- **Managed LanceDB vector or hybrid retrieval:** the standalone adapter is not wired into the workspace. **[major]**
- **Managed metric and dataset catalog:** the query tool expects names but does not expose normal discovery operations. **[major]**
- **Managed ontology, graph, and ODCS contract browsing:** SDK/Core capabilities are not exposed as workspace tools. **[major]**
- **Reviewer task inbox:** a reviewer needs an individual task link. **[major]**
- **Review notifications:** no email, webhook, or equivalent alerts reviewers to waiting work. **[major]**
- **Review comments and assignments:** “request changes” provides no explanation or discussion. **[major]**
- **Human knowledge browsing and search:** `/workspace` is a status response, not a knowledge UI. **[major]**
- **Human charts and dashboards:** no workspace visualization surface exists. **[major]**
- **Browser publication history, comparison, and rollback:** versioned artifacts exist, but there is no managed reviewable history/rollback interface. **[major]**
- **Search over complete retained originals:** managed lexical search covers compiled page fields and bodies, not the full corpus of uploaded originals. **[major]**
- **Complete browser-based user and credential lifecycle:** local creation/disable/token issuance and Entra capability grants need operator commands. **[major]**
- **Self-registration and password reset:** local authentication uses operator-issued tokens. **[minor]**
- **General SSO support:** Microsoft Entra is implemented; generic OIDC/SAML providers are not exposed. **[minor]**
- **Multiple independently selected workspaces in one deployment:** configuration constructs one workspace identity and its paths per application instance. **[major]**
- **Workspace health, metrics, and alerting:** no dedicated workspace health/metrics endpoints or alert integration were found. The browser status can report ready while the published baseline is absent. **[major]**
- **Rate limits and quotas:** bounded individual uploads and query results exist, but not per-user or workspace-wide fair-use controls. **[major]**
- **Scheduled source refresh:** source changes require a new reviewed selection/task; no managed scheduler was found. **[major]**
- **Human-readable audit trail:** review actions and identities are stored, but no browser audit viewer or audit export is exposed. **[major]**
- **Managed knowledge export:** SDK/CLI export exists, but the workspace has no corresponding user-facing export operation. **[minor]**
- **OpenAPI/Swagger for the workspace:** MCP tool schemas exist; the custom HTTP routes do not provide a workspace OpenAPI UI. **[minor]**
- **Other packaged clients:** no VS Code extension or mobile client was found; generic MCP clients may still connect. **[minor]**
- **Localization:** workspace UI strings are English-only. **[minor]**
- **Safe online backup:** the implementation expects the service to be stopped; it does not provide an online coordinated backup. **[major]**
- **Workspace retention and cleanup controls:** no managed cleanup for accumulated uploads, drafts, worktrees, and review actions was found. **[minor]**
- **Data-version reproducibility:** the result pins the admitted model/source declaration, not a snapshot of a changing live database. **[major]**
- **Turnkey combined deployment:** there is no single installer or combined-workspace container configuration in the inspected deployment files. **[major]**

## OVER-COMPLICATED

- **Four separate analytics review decisions:** [AnalyticsService.apply_decision](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/analytics.py:735) makes a reviewer approve source identity, grant the requester, approve submission, and approve publication separately. Combine the source and requester decision on one explicit page, and make validation an automatic precondition to one final publication decision. Preserve the separate facts and checks in the record.
- **Knowledge coupled to analytics source grants:** [prepare_contribution](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:517) selects the analytics branch merely because analytics is configured. Route document-only work through the document path; require a source grant only when data or metric changes actually depend on it.
- **Restore layout and configuration:** [operations.py](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/operations.py:110) separately copies and rebases many paths, even when they are the same repository. Use one managed root and preserve shared repository identity; derive ordinary paths from it, with overrides only where needed. This would also make backup correctness easier to inspect.
- **Review presentation:** [review.html](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/templates/review.html:10) foregrounds hashes, native terminology, and repeated JSON. Put the human-readable change, source, impact, and decision first; put technical binding details behind one expandable section. The binding itself should remain.
- **Repeated full snapshot loading:** [snapshot](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/app.py:306) rereads and revalidates immutable content on every request. Cache a verified snapshot by published version and invalidate it when the pointer changes.
- **Duplicate condition:** [ContributionService.prepare_enrichment](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/contributions.py:439) repeats the same disallowed-status check immediately after an `elif` that already raises for that condition. The second check is unreachable and can be removed.
- **Pi guidance duplication:** [index.ts](/home/volker/coding/ariadne/products/lumio/clients/pi-workspace/index.ts:190) embeds a long workflow explanation in upload output and repeats much of it in `/workspace`. Keep a short next action in the command and maintain one authoritative agent-facing guide.
- **Test organization:** root coordination tests, member suites, integration modules, and wheel-verification scripts are separately selected in [CI](/home/volker/coding/ariadne/.github/workflows/ci.yml:8). Some separation is justified by independent distributions, but the entry points are hard to understand. A single documented test command with named suites would help. The restore check verifies reading and stale-action refusal but stops before approving a fresh post-restore publication—the failure I reproduced.
- **Large public SDK modules:** `lumio_wiki/cli.py`, `knowledge_base.py`, and Ariadne’s `context.py` contain thousands of lines each. Smaller modules around existing public operations would improve navigation. I cannot honestly claim that deleting half of them preserves all public capabilities or that external users do not depend on them.
- **XLSX importer:** [spreadsheet_import.py](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/spreadsheet_import.py:225) manually parses XML and compares two workbook views. The bounds, isolation, provenance, and refusal of unknown formula values serve real purposes. Its strict XML/dimension handling and use of a private openpyxl worksheet path deserve a compatibility review against real workbooks; replacing parts with a simpler bounded reader is a candidate, not a proven safe deletion.
- **Enrichment impact projection:** [source_refresh_impact](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/enrichment.py:38) is intricate, but it reports which published claims may be affected by changed source versions. I cannot establish that removing its coverage, audience, or latest-version checks would preserve that capability. Simplify the representation and review display before removing those checks.
- **Review nonces, generations, digests, and admission pinning:** these protect against stale tabs, replay, and a changed candidate or source between review and execution. A single server still has concurrent requests and crashes. I do **not** consider their removal justified by the evidence; simplify the user workflow around them. [Review action binding](/home/volker/coding/ariadne/products/lumio/packages/lumio-workspace/src/lumio_workspace/state.py:543), [admission validation](/home/volker/coding/ariadne/products/ariadne/packages/ariadne-data/src/ariadne/query.py:1500).
- **Package split:** the standalone Core, wiki SDK, and LanceDB adapter have usable independent interfaces. I cannot determine external use from this checkout, so deleting or merging packages is not demonstrably safe. The immediate simplification is to make the managed service install and expose the subset it actually uses.

**SUMMARY:** The platform can complete a seeded local knowledge publication and a native SQLite governed-query journey, and its approval binding contains meaningful safeguards. It fails important first-use, confidentiality, recovery, and managed-agent requirements, so it does not yet deliver the stated end-to-end platform.

**BIGGEST_GAP:** The managed workspace lacks a reliable, access-controlled first-use and recovery path: it exposes restricted pages, cannot publish the first knowledge contribution after normal setup, and cannot publish normally after restore.

**SIMPLICITY_AUDIT:** The “maximally simple” claim does not hold operationally: one application process plus HTTPS ingress, at least four distinct local storage roles, at least 11 full-workspace environment settings, three project distributions plus Pi, and multiple human approvals for one new data source.

**TOP_3_SIMPLIFICATIONS:**

1. Establish one managed workspace root and one Git identity, including backup/restore.
2. Reduce the four analytics review decisions to two human decisions while retaining exact binding and validation.
3. Uncouple knowledge-only contributions from analytics grants and provide a first-class first-publication path.

**MISSING_COUNT: 38** identified capabilities or material gaps.