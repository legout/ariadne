# Goal-Achievement Audit: Ariadne-Lumio Managed Workspace Platform (8-model re-run)

**Date:** 2026-11-08
**Scope:** Full monorepo at `2f5bc97` (delivered main, post lumio-v0.6.0 + core-v0.8.0 releases)
**Method:** 8 independent one-shot Hermes agents, each with zero prior context (memory and rules files excluded from their sessions), examined the implementation code only (no plans, ADRs, specs, or issue trackers). Read-only, no sub-agents, identical audit brief. The orchestrator spot-checked every load-bearing cross-model disagreement against the code before synthesizing (2 confirmed, 1 refuted).
**Reports:** [Individual audit reports](2026-11-08-goal-audit-reports/)
**Predecessor:** [2026-11-07 7-agent audit](2026-11-07-goal-achievement-audit.md) — verdict unchanged; delta section at the end.

## Agents

| # | Model | Provider | Reasoning |
|---|-------|----------|-----------|
| 1 | GPT-6.1-Sol | Codex | high |
| 2 | GPT-6.1-Terra | Codex | xhigh |
| 3 | GPT-6-Luna | Codex | max |
| 4 | GLM-5.3 | ZAI | high |
| 5 | GLM-5.3-Flash | ZAI | max |
| 6 | MiniMax-M3.1-Flash | MiniMax | max |
| 7 | K3.1-Pro | Kimi | high |
| 8 | Grok-4.7 | xAI | high |

## Overall verdict: **PARTIALLY ACHIEVED** (7/8; 1× NOT ACHIEVED — GPT-6.1-Terra)

No agent voted GOAL ACHIEVED. The trust architecture is real and holds under code reading; the platform is not yet a self-service daily workplace for agents, and the "maximally simple" claim fails at every measured level.

## Area verdicts

| Model | A1 Data | A2 Knowledge | A3 Agent use | A4 Collab | A5 Simplicity | Overall |
|-------|---------|--------------|--------------|-----------|---------------|---------|
| GPT-6.1-Sol | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIALLY |
| GPT-6.1-Terra | PARTIAL | PARTIAL | PARTIAL | PARTIAL | **DOES NOT WORK** | **NOT ACHIEVED** |
| GPT-6-Luna | PARTIAL | PARTIAL | PARTIAL | WORKS | PARTIAL | PARTIALLY |
| GLM-5.3 | PARTIAL | PARTIAL | PARTIAL | WORKS | PARTIAL | PARTIALLY |
| GLM-5.3-Flash | PARTIAL | WORKS | PARTIAL | WORKS | **DOES NOT WORK** | PARTIALLY |
| MiniMax-M3.1-Flash | PARTIAL | WORKS | PARTIAL | WORKS | **DOES NOT WORK** | PARTIALLY |
| K3.1-Pro | WORKS* | PARTIAL* | PARTIAL* | PARTIAL* | PARTIAL | PARTIALLY |
| Grok-4.7 | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIAL |

\* K3.1-Pro restructured the areas against the brief and made one refuted claim (see "Parent-verified findings").

## What genuinely works (consensus)

1. **Governed query core** — bounded exact-byte upload, SHA-256 persistence, XLSX→DuckDB with provenance limits, sqlglot compile gate, single-statement guard, EXPLAIN bind, grain audit, pinned admission (commit + source digest), truthful `governed: true/false` labeling with ad-hoc paths marked unsaved.
2. **The human gate** — API/browser credentials purpose-separated; approvals only via same-origin HTTPS browser POST; one-use action digests with replay protection; single-person self-approval browser-only; revocation effective on the next call; restore invalidates pending actions and sessions.
3. **Knowledge review mechanics** — real diffs (body, claims, source support), approval publishes exactly the reviewed tree, rejection leaves published state untouched, readers see new content immediately.
4. **One process, one SQLite operational store** — the honest half of the simplicity claim.

## Critical gaps (consensus)

### Agent surface is a sliver of what the libraries implement (Area 3 — unanimous PARTIAL)

The workspace MCP surface is 10 tools with lexical search only. **LanceDB vector search is never wired into the served path** (all 8 agents; `lumio-workspace` declares no `lumio-lancedb` dependency despite the goal promising it). No `list_metrics`/`list_datasets`/`resolve_term`/contracts discovery, no entity/claim/ontology graph access — while `ariadne/serve.py` (30+ tools) and `lumio_wiki/mcp_server.py` already implement them. Pi's Entra mode cannot upload; the 765-line SKILL.md is heavy; the model allowlist is client-side and fail-open; the API token is documented as exposed to Pi's inherited shell env.

### First-use is a 4-approval gauntlet (Area 1 — 7 of 8)

Upload → prepare source → browser approval #1 (source identity) → browser approval #2 (data grant) → profile → prepare contribution → submission review #3 → publication review #4 → query. Database/S3 sources are not agent-requestable at all — operator-authored bindings file only. (K3.1-Pro dissents: rates the data pipeline WORKS as "real end-to-end, deliberately multi-stage".)

### "PDF → structured pages" is agent labour (Area 2 — 6 of 8)

Extraction returns text; every Markdown page, frontmatter entry, claim and evidence anchor is hand-authored by the agent.

### No reviewer-side surface (all 8)

No pending-review inbox, no notification, no audit-trail reader — governance depends on the agent handing over a `review_url`.

### "Maximally simple" fails (Area 5 — 3× DOES NOT WORK, 5× PARTIAL)

8–11 stateful roots (SQLite, **two** Git repos, DuckDB, published tree, private roots, profile/bindings JSONs, registry/artifacts) vs the 5 claimed; 5→10–16 env vars; 5 packages; ~215k tracked Python lines behind a 12.4k-line service. Dead weight named by agents: empty root `src/ariadne/`, `.orchestrator` fixture tree, `lumio-lancedb` unwired, `ariadne-agent` unreferenced by the workspace, 10.6k-line `cli.py` in the dependency closure. The checked-in Compose file deploys `ariadne-serve`, not the workspace.

## Parent-verified findings

The orchestrator re-read the code for every cross-model disagreement:

- **CONFIRMED — first-publication bootstrap deadlock** (GPT-6.1-Sol, unique finding): `setup.py:apply_setup` commits "Initialize workspace knowledge base" but never publishes; `review.py:210-216` refuses any review (`incomplete_review_scope`) when `publication.current_version()` is None; `contributions.py:183-186` bases new work on `HEAD`, which publication never advances. A fresh empty workspace cannot review/publish its **first** knowledge contribution (the adopt-an-existing-KB path avoids it).
- **CONFIRMED — restricted-page disclosure** (GPT-6.1-Sol + GPT-6.1-Terra): `search_pages`' own docstring requires clients to filter visibility; `app.py:327-360` calls it unfiltered and `read_knowledge` checks nothing. Any restricted page inside an admitted snapshot is readable/searchable by every read member.
- **REFUTED — "workspace has no knowledge reader"** (K3.1-Pro): `read_knowledge`/`search_knowledge` exist at `app.py:327/347`; seven other agents cite them.

Additional edge findings worth keeping (single-source but concrete): restore copies admission records with old absolute project identity (rejected on next open) and duplicates the repo into two divergent roots (Sol/Terra); re-granting `read` revives an old `data_granted` with no new browser decision (Grok-4.7); backup is a stopped-service `copy2` with no WAL handling (Grok-4.7); XLSX is parsed into DuckDB during *prepare* while the review page states no source data was opened (Grok-4.7); plain document submissions in analytics workspaces require a data grant (GPT-6.1-Sol).

## Missing capabilities

12–28 per agent (format-dependent); union ≈ 30 items in ~20 themes. **Blockers:** first-publication bootstrap, restricted-page visibility filtering, reviewer inbox/notification. Recurring majors: discovery surface, vector retrieval, graph access, agent-requestable DB/S3 sources, auto-structuring, health/metrics endpoints, multi-workspace, rollback UI. See individual reports for each agent's exhaustive list.

## Over-complicated components (cross-model convergence)

| Simplification | Votes |
|----------------|-------|
| Collapse the 4-browser-approval ladder (bind source identity + grant into one decision per artifact) | 6/8 |
| Mount ariadne's existing MCP facade behind workspace auth instead of the parallel 10-tool layer | 4/8 explicit, echoed by 3 more |
| Delete or actually wire `lumio-lancedb`; drop dead artifacts (`.orchestrator`, empty `src/`, `ariadne-agent`, unused wiki surfaces) | 4/8 |
| One Git repo (two subtrees) instead of two repos + two admission models | 3/8 |
| Consolidate review reconcile/generation machinery + duplicate candidate-prep paths into one recovery routine | 4/8 |
| Replace/shrink the 769-line hand-rolled XLSX XML validator (openpyxl / fail-closed subset check) | 3/8 |

**Counter-consensus:** 5 of 8 agents state the one-use nonces, generations, digests and admission pinning **earn their keep** — keep the guarantees, halve the code. (Note: the XLSX strictness and the source/grant split were deliberate, review-hardened design decisions in this repo; agents judge them as delivered complexity, which is fair, but they are not accidents.)

## Top 3 simplifications (highest impact)

1. **Mount the ariadne MCP facade** (`serve.py`: discovery, term resolution, contracts, graph) behind the workspace's auth — restores the missing agent surface and deletes the parallel-tool drift.
2. **One approval binding source identity + grant** per artifact — halves browser decisions and deletes a state-machine stage.
3. **One repo + delete or wire `lumio-lancedb`** and the dead artifacts — closes the gap between claimed and actual moving parts.

## Comparison with stated goal

| Goal criterion | Status | Evidence |
|---------------|--------|----------|
| Agents manage data | ⚠️ Partial | Upload/profile/query works; 4 approvals; DB/S3 operator-bound only |
| Agents manage knowledge | ⚠️ Partial | Submit/review/publish works; structuring is manual agent work; fresh-workspace bootstrap blocked |
| Serve governed metrics | ✅ Yes | Compile-gated, injection-safe, honestly labeled, pinned |
| Serve context layer | ⚠️ Partial | Implemented in libraries; not exposed through the workspace surface |
| Serve knowledge retrieval | ⚠️ Partial | Lexical only; LanceDB never wired into the workspace |
| Human-agent collaboration | ✅ / ⚠️ | Boundary holds (4×WORKS); edge cases: visibility disclosure, grant revival, restore identity |
| Maximally simple setup | ❌ No | 8–11 stores, 5→16 env vars, 5 packages, 4-approval flow |
| One server, one store | ⚠️ Mixed | One process ✓, SQLite ✓, two Git repos and 6+ filesystem roles beyond the claim |

## Model observations

- **GPT-6.1-Sol (high)** — deepest audit; 3 unique findings, all parent-verified claims confirmed.
- **GPT-6.1-Terra (xhigh)** — harshest (only NOT ACHIEVED); solid but grouped evidence; pessimistic severity calibration.
- **GPT-6-Luna (max) / GLM-5.3 (high)** — reliable, well-cited, mid-range; no unique misses found.
- **GLM-5.3-Flash (max)** — densest gap list of the run; found the dead artifacts.
- **MiniMax-M3.1-Flash (max)** — best structured synthesis; coined "a 10-tool sliver of a 30-tool library".
- **K3.1-Pro (high)** — weakest: restructured the areas and hallucinated a missing-reader blocker (refuted); its Area-1 WORKS is the outlier vote.
- **Grok-4.7 (high)** — sharpest edge-case nits; misread single-person self-approval as a rule violation (the goal explicitly allows it).

## Delta vs the 2026-11-07 run

- **Verdict stable:** PARTIALLY ACHIEVED in both runs; this run adds one dissent (Terra: NOT ACHIEVED) and no vote moved toward ACHIEVED.
- **Collaboration area moved from PARTIAL to split 4×WORKS/4×PARTIAL** — the boundary itself is now broadly judged sound; the 11-07 "reviewer approves blind" concern persists as the reviewer-surface gap (no inbox/notifications/audit reader).
- **New findings unique to this run (parent-verified):** first-publication bootstrap deadlock; restricted-page disclosure in workspace read/search. Plus: data-grant revival on read re-grant, XLSX parsed before approval, restore identity/repo-split issues, dead-artifact inventory.
- **Converged recommendations:** both runs independently propose collapsing the approval ladder and exposing discovery; this run sharpens it into "mount the existing facade" and adds repo consolidation and LanceDB wiring/deletion.
