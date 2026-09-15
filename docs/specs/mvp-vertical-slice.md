# Specification: MVP Vertical Slice — Agentic Semantic Layer

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-14 — decision rounds (slice / sources / dataset / runtime; authoring / MCP topology / review gate / LLM provider) and complete-design approval |
| **Scope approved** | Revision 5 (2026-09-15) — semantic-correctness eval harness promoted from deferred (§12) to in-scope: golden question→expected-value sets + fan-out trap proof (owner: "proceed housekeeping and eval") |
| **Evidence base** | [docs/research/agentic-semantic-layer-architecture.md](../research/agentic-semantic-layer-architecture.md) |
| **Contract** | planning-contract v1 |

## 1. Purpose

Prove the full authoring loop end-to-end: an authoring agent generates OKF context and OSI semantic models from a real database, deterministic validation compiles them, a human promotes them, and a consuming agent queries governed metrics over MCP. Since revision 3, consuming agents may also derive **ad-hoc metrics on demand** — drafted as structured definitions, validated by the same deterministic compile gate — so any data in the attached database is queryable without prior modeling. No computation ever bypasses the compile gate.

## 2. Scope and non-goals

**In scope:** one synthetic SQLite database; authoring agent (profile + seed notes → synthesize → validate loop); MCP facade server; human promotion gate; ad-hoc query layer (`list_datasets`, `define_metric`, auto-staged proposals).

**Non-goals (MVP):** access control/authZ/RLS/audit; Delta/Iceberg mounting; import/export adapters (Cube, MetricFlow, Wren, Malloy); multi-user; release automation; PR-based review gate (see §9); promotion-time revalidation (ADR-0004); write path of any kind; multi-database ad-hoc; auto-promotion of ad-hoc definitions; expression-injection hardening (deferred — agent-authored SQL fragments are a named, accepted trust boundary capped by the read-only attach + single-statement guard); ad-hoc composition of governed metrics. ~~semantic-correctness eval harness~~ — **in scope since rev 5 (§13)**.

## 3. Architecture

```text
scripts/seed_db.py         # synthetic demo.db: orders/customers, 2 designed gotchas
ariadne/
  profiler.py              # DuckDB sqlite_scanner: SUMMARIZE + PK/FK heuristics → profile.json
  author.py                # OpenAI: profile + docs → OKF .md + OSI .yml drafts → staging/
  validate.py              # datus compile of staged OSI; errors fed back to author (≤3 rounds)
  serve.py                 # MCP facade server (stdio), five tools
staging/semantic_layer/models/adhoc/   # auto-staged ad-hoc proposals (promotion-gated)
data/demo.db
data/seed_notes.md        # human-written data dictionary: business rules statistics cannot derive
staging/                   # author output; human promotes by moving files
context_layer/             # served OKF: ontology/, datasets/, metrics/
semantic_layer/            # served OSI: datasets/, models/, metrics/
```

## 4. Interfaces

- `python -m ariadne.author --db data/demo.db --notes data/seed_notes.md` → writes `staging/{context_layer,semantic_layer}/…`; runs the validate loop internally.
- `python -m ariadne.validate staging/` → exit 0/1 plus compiler errors.
- `serve.py` — MCP stdio facade, exactly five tools:
  - `list_metrics()` → served governed metrics with descriptions **and available dimensions**, ending with an explicit routing hint: unmodeled questions → `list_datasets()` + `define_metric`.
  - `list_datasets()` → `[{name, columns: [{name, type}]}]` for every table in the attached database (the agent's map of queryable data).
  - `search_context(query)` → ranked matches over `context_layer/**/*.md`.
  - `get_metric(name, dimensions, range)` → Datus compiles OSI → SQL → DuckDB executes → returns rows **plus the compiled SQL** (provenance) and `governed: true`. `range` is an optional `{start, end}` date filter applied to the metric's primary date dimension.
  - `define_metric({name, description, source, expression, dimensions?, time_field?})` → the ad-hoc path: facade expands the params into an ephemeral OSI model, compiles via Datus, executes the compiled SQL read-only, and returns rows + SQL + `governed: false` + the echoed definition. `source` is a table name or SELECT (agent-authored, joins allowed); `expression` is an aggregate SQL expression. On success the definition is auto-staged as a proposal at `staging/semantic_layer/models/adhoc/<name>.yml` (numeric suffix on name collision, never overwrite) **plus a minimal OKF draft at `staging/context_layer/metrics/<name>.md`** (frontmatter + description + dimensions — so `search_context` can discover proposals). Promotion remains human per ADR-0003.
- Datus integration (decided by the Phase 0 spike): Python imports of `datus_semantic_osi`, compile-only; the facade owns the DuckDB connection. Ad-hoc compiles use an ephemeral model instance (temp path if the adapter requires files; discarded after the call).

## 5. Data flow

- **Authoring:** seed → profile → profile + seed notes → LLM draft → validate → errors loop (≤3) → `staging/` → human promotes → served dirs.
- **Query (governed):** agent → `get_metric` → facade → Datus compile → DuckDB over `demo.db` → governed rows.
- **Query (ad-hoc):** agent → `list_datasets` → drafts `define_metric` params → facade expands to ephemeral OSI model → Datus compile (invalid → compiler errors verbatim, nothing staged, nothing executed) → read-only execution → rows + SQL + `governed: false` → proposal auto-staged.

## 6. Invariants

- Served artifacts only ever arrive by human promotion from `staging/`.
- The author never writes outside `staging/` (the ad-hoc path writes only to `staging/semantic_layer/models/adhoc/`).
- **No unvalidated execution (revision 3):** every computation — governed or ad-hoc — passes the deterministic Datus compile gate. Agents may author dataset sources and metric expressions; there is no code path from tool arguments to `duckdb.execute` that bypasses the compiler. Governed state changes only by human promotion.

## 7. Failure behavior

- Invalid OSI/OKF after 3 compile rounds → stop; errors recorded in the staging file's frontmatter as `status: review_needed`.
- Datus absent/broken → `serve.py` fails fast at startup with an install hint.
- Unknown metric requested → error response lists available metrics from `semantic_layer/` **and names the ad-hoc path**: `list_datasets()` + `define_metric` for anything unmodeled.
- Invalid ad-hoc definition → Datus compiler errors returned verbatim; nothing staged, nothing executed. The facade stays stateless — retry discipline is the consuming agent's concern.
- Promotion conflict → manual `mv`; the human resolves. No merge machinery.

## 8. Acceptance examples (observable)

1. `python scripts/seed_db.py` produces a deterministic `data/demo.db`; asserted row counts.
2. `python -m ariadne.author --db data/demo.db --notes data/seed_notes.md` exits 0 with at least one OKF metric page and one OSI model in `staging/`, passing `validate` within 3 auto-iterations; the authored OKF page carries both seed-noted gotchas.
3. After promotion, `get_metric("gross_margin", dimensions=["region"])` returns the fixture's hand-computed values: `CANCELLED`/`RETURNED` excluded; pre-2024 EMEA rows currency-converted per the OKF rule. `get_metric("order_count", dimensions=["region"])` likewise matches the fixture.
4. `search_context("gross margin")` returns the OKF page carrying both gotchas.
5. `get_metric("nonexistent")` errors with a list of available metrics.
6. `list_metrics()` returns both governed metrics (`gross_margin`, `order_count`) with descriptions.
7. The demo is consumed two ways: a scripted MCP client runs the acceptance calls in CI; a recorded pi session asks "gross margin by region last quarter" in natural language against the same served artifacts.
8. **Ad-hoc (rev 3):** `define_metric` answering "mean order amount per customer" (agent-authored `orders ⋈ customers` join source) returns rows matching an independently computed fixture, with `governed: false` and provenance SQL, with zero prior promotion.
9. **Ad-hoc failure:** an invalid `define_metric` returns compiler errors; no file appears under `staging/…/adhoc/` and no SQL executes.
10. **Symmetry:** `get_metric` responses carry `governed: true`.
11. **Proposal capture:** each successful ad-hoc definition leaves exactly one `adhoc/<name>.yml` in staging; collisions suffix numerically, never overwrite.
12. **Routing contract (rev 4):** `list_metrics` entries include available dimensions and end with the ad-hoc hint; the unknown-metric error names `list_datasets`/`define_metric`; a successful `define_metric` leaves both the model proposal and a discoverable `context_layer/metrics/<name>.md` draft in staging. The end-to-end check is manual: a fresh consuming-agent session answers an unmodeled question (e.g. "mean order volume per country") via the ad-hoc path without prior knowledge.
13. **Eval harness (rev 5):** `tests/evals/golden.json` + `tests/test_evals.py` — golden entries {question, metric, dimensions, expected} with expected values derived by independent SQL (never from the implementation under test); every served governed metric covered; at least one ad-hoc `define_metric` round-trip; and one **fan-out trap proof**: a scratch orders⋈lines one-to-many model whose naive join would inflate aggregates, asserted equal to the correct deduplicated value when compiled through Datus.

## 9. Recorded deviations from the research study

- **Human gate = staging dir**, not research §8's PR flow (MVP pace decision by owner; PR gate returns post-MVP).
- **Facade owns the single MCP endpoint** instead of agents connecting to Datus's MCP server directly.

## 10. Phasing

- **Phase 0 (spike, disposable):** Datus install; compile the research doc's `orders.yml`; execute on DuckDB; call from Python. Verdict gates Phases 1–4.
- **Phase 1:** seed + profiler. **Phase 2:** author + validate loop. **Phase 3:** facade server. **Phase 4:** end-to-end demo + README.
