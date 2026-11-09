# Goal-Achievement Audit: Ariadne-Lumio Managed Workspace Platform

**Date:** 2026-11-07
**Scope:** Full monorepo at `2f5bc97` (delivered main, post lumio-v0.6.0 + core-v0.8.0 releases)
**Method:** 7 independent coding agents, each with zero prior context, examined the implementation code only (no plans, ADRs, specs, or issue trackers). Each agent used its own sub-agents for parallel deep-dives.
**Reports:** [Individual audit reports](2026-11-07-goal-audit-reports/)

## Agents

| # | Model | Provider | Reasoning |
|---|-------|----------|-----------|
| 1 | MiniMax-M3.1-Flash | Pi | max |
| 2 | GLM-5.3 (ZAI) | Pi | max |
| 3 | GLM-5.3-Flash (ZAI) | Hermes | max |
| 4 | GPT-6.1-Terra | Codex | max |
| 5 | GPT-6-Luna | Codex | max |
| 6 | GPT-6.1-Sol | Pi | medium |
| 7 | MiniMax-M3 | Hermes | high |

## Overall verdict: **PARTIALLY ACHIEVED** (7/7 agents independently)

The repository contains substantial working implementations — not scaffolding. The compile gate, human approval boundary, and governance labeling are genuinely strong. However, the platform is not yet a self-service system that agents and browser reviewers can operate without manual intervention. The workflow is too bureaucratic for the stated "maximally simple" goal, and several integration gaps remain.

## Area verdicts (unanimous across all 7 agents)

| Area | Verdict | Key finding |
|------|---------|-------------|
| Data pipeline | PARTIALLY WORKS | Compile gate real; flow needs 4 browser approvals + 5 agent calls for new source |
| Knowledge pipeline | PARTIALLY WORKS | Upload/parse works; "PDF → structured pages" is agent-authored markdown, not automatic |
| Agent consumption | PARTIALLY WORKS | Pi extension connects; no discovery surface, no vector search via workspace |
| Collaboration | PARTIALLY WORKS | Auth boundary holds; reviewer experience is technical (hashes/JSON, no data preview) |
| Operational simplicity | MIXED | One process ✓; but 10+ env vars for analytics, 5+ packages, complex state machine |

## What genuinely works (consensus)

1. **Compile gate**: sqlglot-compiled models, single-statement guard, function allowlist, grain guard, EXPLAIN bind check — identified by all agents as "genuinely strong"
2. **Human gate**: Agent tokens cannot approve content; browser session with one-use nonce, same-origin, HTTPS enforced
3. **Governance labeling**: `governed: true/false` explicit on every result; pinned commit + source digest; ad-hoc queries marked `not_saved`
4. **Upload pipeline**: Exact-byte, SHA-256, 25 MiB bound, retry idempotency, format allowlist
5. **XLSX import**: Stored-value-only (no recalculation), formula-cache refusal, extent validation, cell-order validation
6. **Backup/restore**: Holistic (SQLite + Git + artifacts), session invalidation, worktree repair

## Critical gaps (consensus)

### Flow is bureaucracy, not a pipeline
- New data source: 5 agent calls + 4 human browser decisions (8 HTTP requests)
- No "profile then answer" shortcut — data must go through metric authoring + admission before any query returns
- Approve-then-profile inversion: both browser reviews must precede profiling
- Fails the stated "<5 steps" criterion outright

### No discovery surface
- `list_metrics`, `list_datasets`, `discover` exist in Ariadne Core but are NOT dispatched by the workspace
- Agent cannot find a metric by asking; must obtain project handle out of band
- Source handles require operator-side bindings file

### "PDF → structured pages" is agent labour
- Document extraction stops at text/sections
- The agent must manually write Markdown with YAML frontmatter (title, tags, ontology)
- No automatic entity extraction, claim extraction, or structured metadata generation

### PostgreSQL identity gap
- Approval records the env-var NAME, not the DSN value
- Changing the DSN under the same variable name redirects to a different database without changing the approval digest
- S3 sources have proper effective-binding resolution; PostgreSQL does not

### Reviewer approves blind
- Review page shows digests and identity hashes but no data sample
- Reviewer cannot see what the data looks like before approving it
- Review UI uses raw identifiers, JSON, `<pre>` blocks — requires technical expertise

### No vector search in workspace
- LanceDB exists in lumio-wiki/lumio-lancedb but is not exposed through the workspace service
- Agent search is lexical only (page-level text matching)

## Missing capabilities (exhaustive list from Area 6)

| Capability | Severity | Note |
|-----------|----------|------|
| Multi-workspace per deployment | major | One workspace per server |
| Self-registration / SSO / password reset | major | CLI-only user management |
| Monitoring, metrics, health checks, alerting | major | No /health, no Prometheus, no alerts |
| Notification system | major | Reviewer must poll for pending reviews |
| API documentation (OpenAPI/Swagger) | major | MCP tools undocumented to callers |
| Data visualization | major | No charts without writing SQL |
| Scheduled/automated data refresh | major | Live sources need manual refresh |
| Audit trail UI | minor | Who approved what is in SQLite only |
| Export capabilities | minor | No export to other formats |
| Vector search via workspace | major | LanceDB not integrated |
| Discovery (list metrics/sources) | major | Core tools not dispatched |
| Multi-source queries | minor | One native source per handle |
| Rate limiting / quotas | minor | No fair-use controls |
| Client libraries beyond Pi | minor | No VS Code, web UI, mobile |
| Localization / i18n | minor | English only |

## Over-complicated components (exhaustive list from Area 7)

| Component | What it does | Why too complex | Simplification |
|-----------|-------------|-----------------|----------------|
| Review-action binding | One-use nonces, generations, digest bindings | Over-engineered for single-server; 3+ round-trips per action | Simple one-use token + task ID |
| Admission-record pinning | validate_admission_record + expected_revision + admission_record param | 3 API parameters for race-free queries | Single pinned admission param |
| XLSX importer edge cases | XML pre-parse, cell-order, shared-formula refusal, implicit-r handling | Extensive for synthetic fixtures; untested with real workbooks | Test with real .xlsx files; simplify edge-case handling |
| Enrichment impact projection | Per-page binding + audience filter + registry-latest binding | Disproportionate to feature value | Simplify to "which pages reference this source" |
| Workspace state machine | pending_review → data_granted → published + action_replay states | Multiple states for a single-server flow | 3 states: draft → pending → published |
| Package modularization | 5+ packages (ariadne-data, lumio-wiki, lumio-lancedb, lumio-workspace, pi-workspace) | Ceremony without clear benefit for a monorepo | 2: core (data+metrics) and workspace (service+knowledge) |
| Environment variables | 5 read-only; 10+ analytics; 12+ optional; 18+ Entra | Not "maximally simple" | Config file with sensible defaults |
| Test suite organization | Root coordination + per-member + integration + verification scripts | Confusing structure; unclear which tests cover what | Single test tree per package |

## Top 3 simplifications (highest impact)

1. **Collapse the approval flow**: Source approval + data grant → single "approve source" step. Submission + publication → single "publish" step. Result: 2 browser decisions instead of 4.
2. **Expose discovery**: Dispatch `list_metrics`, `list_datasets`, `search_context` through the workspace MCP surface. Agents can then find what exists without out-of-band knowledge.
3. **Configuration file instead of 10+ env vars**: A single `workspace.yaml` with sensible defaults; env vars only for secrets.

## Comparison with stated goal

| Goal criterion | Status | Evidence |
|---------------|--------|----------|
| Agents manage data | ⚠️ Partial | Upload/profile/query works but requires 4 approvals + metric authoring first |
| Agents manage knowledge | ⚠️ Partial | Submit/review/publish works but "structuring" is manual agent work |
| Serve governed metrics | ✅ Yes | Compile-gated, injection-safe, honestly labeled |
| Serve context layer | ✅ Yes | Semantic terminology, ODCS contracts, policy caveats |
| Serve knowledge retrieval | ⚠️ Partial | Lexical search works; LanceDB vector search not exposed via workspace |
| Human-agent collaboration | ✅ Yes | Auth boundary holds; agents cannot bypass review |
| Maximally simple setup | ❌ No | 10+ env vars, 5+ packages, 4-approval flow, technical review UI |
| One server, one store | ⚠️ Mixed | One process ✓; SQLite ✓; but 10+ env vars, multiple packages |
