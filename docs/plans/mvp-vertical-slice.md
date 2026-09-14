# Implementation Plan: MVP Vertical Slice

| | |
| :--- | :--- |
| **Goal** | Prove the authoring loop: profile → synthesize OKF+OSI → deterministic validate → human promote → governed MCP query |
| **Source** | [docs/specs/mvp-vertical-slice.md](../specs/mvp-vertical-slice.md) — approved by owner 2026-09-14, **revision 2** (grill-with-docs amendments: seed-notes input, `list_metrics`, two metrics, dual demo consumers) |
| **Capture checkpoint** | Recorded: `CONTEXT.md` (8 terms); ADR 0001 (own authoring), 0002 (MCP facade), 0003 (staging gate); open uncertainty: Datus install/call mechanics → Task 0 |
| **Constraints** | Spec §2 non-goals; invariants §6: author writes only to `staging/`, `get_metric` never takes raw SQL, served artifacts only via promotion |
| **Runtime assumptions** | Python 3.11+, venv; deps: `duckdb`, `openai`, `pyyaml`, MCP SDK, Datus (form per Task 0); `pytest`; `OPENAI_API_KEY` |
| **Global validation** | `pytest` green; `ruff check` clean |
| **Contract** | planning-contract v1; provenance: `legout/skills` via `npx skills`, per-skill hashes in `skills-lock.json`, catalog revision unknown |

## Requirement → task map

| Spec acceptance criterion | Task |
| :--- | :--- |
| §8.1 deterministic seed | T1 |
| §8.2 author produces staging artifacts from profile + seed notes, validate ≤3 iterations | T1, T2, T3 |
| §8.3 governed `gross_margin` and `order_count` equal hand-computed fixtures | T4 (enabled by T0, T1) |
| §8.4 `search_context` returns gotchas page | T4 |
| §8.5 unknown-metric error lists available; §8.6 `list_metrics` returns both metrics | T4 |
| §8.7 dual demo consumers (scripted CI client + recorded pi session) | T5 |
| Spec §10 Phase 0 spike verdict | T0 |
| End-to-end demo + README | T5 |

## Tasks

- [ ] **T0 — Datus spike** *(owner: `prototype-question`; gate for T3–T4)*
  - Question: can Datus (a) install in a clean venv, (b) compile the research doc's `orders.yml`, (c) execute the result on DuckDB against SQLite, (d) be called from Python — import or CLI?
  - Evidence threshold: compiled SQL text + one executed governed query + the working call mechanism, recorded in the probe verdict.
  - Produces: integration mechanism decision for T3/T4; durable verdict → `docs/research/datus-spike.md`.
  - Failure handling: if (a)–(d) fail, stop and return to `shape-design` with the escape hatch (spec §11 of the research study: Cube).
  - Validation: probe evidence itself; `no-new-test`.

- [ ] **T1 — `scripts/seed_db.py` + expected-value fixture**
  - Creates `data/demo.db`: `orders` (incl. `CANCELLED`/`RETURNED` rows and pre-2024 EMEA rows in local currency), `customers`, `currency_conversion_rate`; seeded RNG, fixed row counts.
  - Produces `tests/fixtures/expected_metrics.json`: hand-computed `gross_margin` **and** `order_count` by region applying both OKF rules.
  - Authors `data/seed_notes.md`: the human-written data dictionary carrying both gotchas (status exclusion; pre-2024 EMEA currency conversion) — the author's business-rule input.
  - Interface: `python scripts/seed_db.py` idempotent (re-run converges to identical DB).
  - Prereqs: none. Risk: normal — the fixture anchors the T4 money test.
  - Validation: `new-test` — `tests/test_seed.py`: row counts deterministic across two runs; fixture values match an independent hand-written SQL query.

- [ ] **T2 — `ariadne/profiler.py`**
  - DuckDB `sqlite_scanner` over `demo.db`: `SUMMARIZE` per table + PK/FK heuristics (unique-ratio, name-match) → `profile.json`.
  - Interface: `profile(db_path) -> dict`; CLI `python -m ariadne.profiler --db data/demo.db`.
  - Prereqs: T1. Risk: normal.
  - Validation: `new-test` — `tests/test_profiler.py`: finds expected columns, flags `customer_id` as FK candidate, detects the currency column's null spike.

- [ ] **T3 — `ariadne/author.py` + `ariadne/validate.py`** *(one validation unit: the loop)*
  - `author.py`: profile + seed notes + ontology hints → OpenAI → drafts `staging/context_layer/**.md` (OKF frontmatter) + `staging/semantic_layer/**.yml` (OSI, both measures: `gross_margin`, `order_count`). Never writes outside `staging/`.
  - `validate.py`: Datus-compiles staged OSI (mechanism per T0); on error, message feeds back into the next author round; ≤3 rounds, then stop with `status: review_needed` in frontmatter.
  - Interfaces: `author(db_path, notes_path) -> staging paths`; `validate(staging_dir) -> ok | errors`.
  - Prereqs: T0, T2. Risk: normal-high (LLM nondeterminism) — mitigated by mocked test + real compile.
  - Validation: `new-test` — `tests/test_author.py`: fixture-mocked OpenAI response → parseable frontmatter/YAML with required fields (`type`, `status`, `sources`; OSI `name`, `primary_key`, `measures`); `tests/test_validate.py`: doc's `orders.yml` variant compiles via Datus, a deliberately broken model fails with captured error.
  - Red → green: write tests against the doc's example artifacts first, then implement.

- [ ] **T4 — `ariadne/serve.py` (MCP facade)**
  - stdio MCP server, exactly three tools: `list_metrics()` (served metrics + descriptions), `search_context(query)` (ranked match over `context_layer/**/*.md`), and `get_metric(name, dimensions, range)` (Datus compile → DuckDB execute → rows + compiled SQL; `range` = optional `{start,end}` on primary date dimension).
  - Failure modes per spec §7: startup fail-fast if Datus broken; unknown metric → error listing available metrics.
  - Prereqs: T0, T1, promoted sample artifacts (test fixture promotes T3's golden outputs).
  - Validation: `new-test` — `tests/test_serve.py` **money test**: `get_metric("gross_margin", ["region"])` and `get_metric("order_count", ["region"])` equal `expected_metrics.json`; `list_metrics()` returns both with descriptions; `search_context("gross margin")` returns the gotchas page; unknown metric error lists both metrics.

- [ ] **T5 — end-to-end demo + README**
  - `scripts/demo.sh`: seed → author → human-promote step (`cp -r staging/*` with a printed pause) → serve → sample calls via a scripted MCP client (runs in CI). Plus one recorded pi session asking "gross margin by region last quarter" in natural language against the same served artifacts.
  - Audience: owner + technical peers — README quickstart stays lean; no narrative polish.
  - Prereqs: T1–T4. Risk: low — wiring and docs.
  - Validation: `existing-check` — demo script exits 0; no new test.

## Residual risks

- **Datus compile determinism** on our OSI dialect subset — covered by T0 evidence threshold, not by later tests.
- **OpenAI flakiness in the live loop** — T3 tests mock it; the live loop's 3-round cap + `review_needed` fallback is the mitigation, manually checked once in T5.
