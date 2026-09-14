# Specification: MVP Vertical Slice — Agentic Semantic Layer

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-14 — decision rounds (slice / sources / dataset / runtime; authoring / MCP topology / review gate / LLM provider) and complete-design approval |
| **Scope approved** | Revision 2 (2026-09-14) — grill-with-docs amendments: seed-notes input, `list_metrics`, two governed metrics, dual demo consumers |
| **Evidence base** | [docs/research/agentic-semantic-layer-architecture.md](../research/agentic-semantic-layer-architecture.md) |
| **Contract** | planning-contract v1 |

## 1. Purpose

Prove the full authoring loop end-to-end: an authoring agent generates OKF context and OSI semantic models from a real database, deterministic validation compiles them, a human promotes them, and a consuming agent queries governed metrics over MCP — without writing SQL.

## 2. Scope and non-goals

**In scope:** one synthetic SQLite database; authoring agent (profile + seed notes → synthesize → validate loop); MCP facade server; human promotion gate.

**Non-goals (MVP):** access control/authZ/RLS/audit; semantic-correctness eval harness; Delta/Iceberg mounting; import/export adapters (Cube, MetricFlow, Wren, Malloy); multi-user; release automation; PR-based review gate (see §9); promotion-time revalidation (ADR-0004).

## 3. Architecture

```text
scripts/seed_db.py         # synthetic demo.db: orders/customers, 2 designed gotchas
ariadne/
  profiler.py              # DuckDB sqlite_scanner: SUMMARIZE + PK/FK heuristics → profile.json
  author.py                # OpenAI: profile + docs → OKF .md + OSI .yml drafts → staging/
  validate.py              # datus compile of staged OSI; errors fed back to author (≤3 rounds)
  serve.py                 # MCP facade server (stdio)
data/demo.db
data/seed_notes.md        # human-written data dictionary: business rules statistics cannot derive
staging/                   # author output; human promotes by moving files
context_layer/             # served OKF: ontology/, datasets/, metrics/
semantic_layer/            # served OSI: datasets/, models/, metrics/
```

## 4. Interfaces

- `python -m ariadne.author --db data/demo.db --notes data/seed_notes.md` → writes `staging/{context_layer,semantic_layer}/…`; runs the validate loop internally.
- `python -m ariadne.validate staging/` → exit 0/1 plus compiler errors.
- `serve.py` — MCP stdio facade, exactly three tools:
  - `list_metrics()` → served governed metrics with descriptions (discovery before failure).
  - `search_context(query)` → ranked matches over `context_layer/**/*.md`.
  - `get_metric(name, dimensions, range)` → Datus compiles OSI → SQL → DuckDB executes → returns rows **plus the compiled SQL** (provenance). `range` is an optional `{start, end}` date filter applied to the metric's primary date dimension.
- Datus integration mechanism (Python import vs CLI subprocess) is decided by the Phase 0 spike; the facade hides it either way.

## 5. Data flow

- **Authoring:** seed → profile → profile + seed notes → LLM draft → validate → errors loop (≤3) → `staging/` → human promotes → served dirs.
- **Query:** agent → `get_metric` → facade → Datus compile → DuckDB over `demo.db` → governed rows.

## 6. Invariants

- Served artifacts only ever arrive by human promotion from `staging/`.
- The author never writes outside `staging/`.
- `get_metric` accepts only named governed metrics — never raw SQL.

## 7. Failure behavior

- Invalid OSI/OKF after 3 compile rounds → stop; errors recorded in the staging file's frontmatter as `status: review_needed`.
- Datus absent/broken → `serve.py` fails fast at startup with an install hint.
- Unknown metric requested → error response lists available metrics from `semantic_layer/`.
- Promotion conflict → manual `mv`; the human resolves. No merge machinery.

## 8. Acceptance examples (observable)

1. `python scripts/seed_db.py` produces a deterministic `data/demo.db`; asserted row counts.
2. `python -m ariadne.author --db data/demo.db --notes data/seed_notes.md` exits 0 with at least one OKF metric page and one OSI model in `staging/`, passing `validate` within 3 auto-iterations; the authored OKF page carries both seed-noted gotchas.
3. After promotion, `get_metric("gross_margin", dimensions=["region"])` returns the fixture's hand-computed values: `CANCELLED`/`RETURNED` excluded; pre-2024 EMEA rows currency-converted per the OKF rule. `get_metric("order_count", dimensions=["region"])` likewise matches the fixture.
4. `search_context("gross margin")` returns the OKF page carrying both gotchas.
5. `get_metric("nonexistent")` errors with a list of available metrics.
6. `list_metrics()` returns both governed metrics (`gross_margin`, `order_count`) with descriptions.
7. The demo is consumed two ways: a scripted MCP client runs the acceptance calls in CI; a recorded pi session asks "gross margin by region last quarter" in natural language against the same served artifacts.

## 9. Recorded deviations from the research study

- **Human gate = staging dir**, not research §8's PR flow (MVP pace decision by owner; PR gate returns post-MVP).
- **Facade owns the single MCP endpoint** instead of agents connecting to Datus's MCP server directly.

## 10. Phasing

- **Phase 0 (spike, disposable):** Datus install; compile the research doc's `orders.yml`; execute on DuckDB; call from Python. Verdict gates Phases 1–4.
- **Phase 1:** seed + profiler. **Phase 2:** author + validate loop. **Phase 3:** facade server. **Phase 4:** end-to-end demo + README.
