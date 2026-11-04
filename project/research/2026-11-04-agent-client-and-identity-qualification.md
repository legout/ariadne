# Agent clients and identity for the shared workspace

Date: 2026-11-04. Status: source-based comparison, not runtime qualification or implementation approval.

## Owner selections during planning

After requesting implementation plans, the owner selected:

- Compare existing clients before choosing; subsequently chose **Pi over a private network**, not the recommended cloud-brokered Claude path.
- One owner-managed private server; all members can read admitted workspace knowledge. Submission, review, original-source inspection, and data-source access remain separately authorized.
- A small authenticated **review page opened from the agent conversation** is acceptable. This is not a new chat application.
- The first usable milestone includes text/Markdown, PDF/Word, CSV/Excel, database tables, and data files/table formats on S3. A document-only slice may come first in implementation order, but does not satisfy the entire milestone.
- Use current documented Ariadne source families and bounded supported modes: SQLite, DuckDB, PostgreSQL, CSV, JSON, Parquet, Delta, Iceberg, and DuckLake. Named S3 profiles retain their existing endpoint/scope/credential boundaries. No arbitrary database vendor or new catalog protocol is implied.
- XLSX uses selected sheets and stored values; no macros or formula recalculation. Refresh is explicit.
- Owner-approved model processing before use; local conversion; retain originals until authorized deletion; the owner delegates reviewers. This is design selection, not permission to disclose live content or delete data now.
- A neutral artifact type with stable identities, collision refusal, and on-request, human-reviewed enrichment. The question used provisional spelling `knowledge_artifact`; Lumio's existing type-slug validator allows hyphens, not underscores. Use proposed spelling `knowledge-artifact` when reconciling the written design, without changing its meaning or widening the validator.

**Identity selection confirmed:** after the explanation of Entra, Google and GitHub, the owner said “ok. keep this decision. proceed.” Retain **Entra ID first, using standard OIDC, no new password database, Google/GitHub deferred**. This confirms the recommendation and continuation of planning, not tenant registration, deployment, live-data processing, or implementation authority. The exact Pi/API integration still requires qualification.

## Client comparison

| Client | Evidence | Consequence for this project |
| --- | --- | --- |
| Pi, installed 1.5.0 | Installed `docs/mcp.md` documents Streamable HTTP, OAuth, pre-registered clients, tool permissions, and resources. It explicitly omits MCP App UI resources because Pi does not render them. `docs/cli.md` documents text/image prompt files; that is not an exact-original document upload protocol. | Selected first client. Private-network connectivity is compatible with a locally originating client, but the actual configured path still needs qualification. Original uploads need a byte-preserving client path; use the accepted browser review link instead of assuming an in-terminal confirmation is server-verifiable approval. |
| Claude Desktop/Cowork | [Remote connector documentation](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) says remote connections originate from Anthropic infrastructure, including Desktop and Cowork; VPN-only servers are not reachable through this route. It documents OAuth, organization configuration, and interactive connectors. [Cowork documentation](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork) distinguishes manual, automatic, and skipped approvals. | Plausible nontechnical interface, but not selected for the first private-network deployment. Local Desktop MCP and cloud-brokered connectors are different routes. Generic tool permission is not proof of exact business-change approval. |
| Codex/ChatGPT desktop | The current [MCP documentation](https://developers.openai.com/codex/mcp) documents Streamable HTTP/OAuth, pre-registered clients, and configurable tool approval. The fetched app-features page now presents ChatGPT features rather than a stable historical Codex-only feature list. | Alternative, not first target. Record and qualify the actual installed app/version before claiming upload/review compatibility; do not transfer capabilities from unrelated OpenAI API file-upload documentation. |

[MCP Apps](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html) defines interactive UI and app-only tool visibility. Hiding a tool from a model is not, by itself, a server-side human authorization proof. [MCP elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation) distinguishes structured forms from URL-based sensitive interactions; protocol support does not establish a particular client's implemented experience.

No examined source proves an automatic transfer of exact original attachment bytes from every selected chat client to an arbitrary remote MCP server. Verify the actual bytes/digest at intake; do not reconstruct a Word/PDF/Excel original from model-visible text.

## Identity options and integration effort

### Entra ID

[Microsoft's OIDC documentation](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc) provides tenant-scoped discovery, authorization, token, and signing-key endpoints. [App registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) establishes the application's trust in that identity provider; a single-tenant registration limits the account audience to the organization's tenant, including explicitly admitted guests.

Selected direction: use the existing Entra tenant for browser sign-in. An administrator registers the application, configures its exact [redirect URI](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri), supplies the server's client credential securely, and controls allowed users. Users then use their existing company login. No workspace password database or separate account-recovery mechanism is necessary.

Microsoft recommends [authorization code flow with PKCE and OIDC](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow). Browser identity and API access remain different: ID tokens establish a sign-in session; resource-scoped access tokens authorize API calls. Pi's API OAuth registration/scopes and the browser session must be designed together. The final configuration may need a separate public-client registration for Pi; do not promise that one browser registration automatically solves MCP login.

A private workspace URL need not become a public content endpoint merely to use browser-redirect login. The user's browser must reach the registered HTTPS callback over the private network, while browser/server need the applicable Microsoft endpoints. This is an architectural inference from the redirect flow, not a successful test of the owner's network or tenant.

Integration effort: routine but security-sensitive server login work, plus the genuinely project-specific work of workspace capabilities, Pi token scope, revocation/session handling, and exact-candidate review receipts. Reuse maintained authentication libraries. No time estimate is established by documentation alone.

### Google

[Google's user authentication](https://developers.google.com/identity/openid-connect/openid-connect) implements OpenID Connect and documents client registration, redirect URIs, discovery, and ID tokens. A standard OIDC browser-login implementation can support a Google-configured deployment, but account admission and organization restrictions still need explicit policy. Provider configuration is not proof that identical Pi/API integration works without qualification.

### GitHub

[GitHub user authorization](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) uses OAuth 2.0 for OAuth Apps and GitHub Apps. Normal “Sign in with GitHub” is not interchangeable with the generic OIDC discovery/ID-token integration described above. It needs a GitHub identity adapter or an identity broker. GitHub Actions workload OIDC is not employee login.

GitHub login does not require repository access merely to identify an account; request additional organization/repository scopes only for an explicitly chosen use. A provider account alone never implies workspace membership or reviewer authority. Do not link accounts merely by matching email addresses.

## Why sign-in is not approval

The identity provider establishes who signed in. The workspace determines what that person may do. The review page displays the exact candidate and records the person's action against that candidate, expected active version, source/retention facts, and current capability. Pi's access credential must not, on its own, mint a human approval. The URL is a locator, not a bearer approval; opening it does not approve anything.

No broad directory, mail, document-store, or repository permissions are needed merely for sign-in. Source onboarding is a separate grant. Supporting Entra first does not imply automatically supporting every OIDC provider's API-token, organization-membership, or revocation behavior.

## Source and verification limits

Local sources: installed Pi 1.5.0 `docs/mcp.md` and `docs/cli.md`; repository `products/ariadne/docs/reference/data-sources.md`; Lumio `knowledge_base.py::_as_ontology` and `_category_name_issue`; package metadata and existing authoring/review/admission seams. The source tree inspected was `34bfe1be` plus the in-progress design documents.

Prior wiki lookup supplied only general cross-harness integration context, not proof of this journey. Web research used the configured web-search backend and direct official-document fetches, with a targeted gap-fill pass. The former Google OIDC URL returned 404; the current URL cited above was located and fetched. No optional research backend registry was present. Project artifact ownership takes precedence over duplicating this research into a separate wiki.

No browser session, installed-client workflow, IdP tenant, live source, database, S3 bucket, service deployment, or runtime test was exercised. Existing tools/features are evidence of seams, not completion of the requested shared workflow. Planning-contract version 1; installed skill revision unknown.
