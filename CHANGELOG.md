# Changelog

## Unreleased

## 0.2.0 - 2026-10-12

Second release: from the governed-metrics MVP to the full agent-facing platform.

- **Own compile engine, AGPL exit** — the `datus-semantic-osi[metricflow]` stack is
  gone; metric compilation is now an own SQLGlot-based engine (`ariadne/render.py`,
  ADR-0008). Runtime dependencies are permissive (MIT/Apache) only, and the Python
  floor is `>=3.12`.
- **Ariadne Agent** — new companion distribution `ariadne-agent` (ADR-0018):
  installable Analyst conversation over native Ariadne tools (#23), authoring
  sessions with human-only approval gates (#24), role-restricted stdio MCP
  integration (#25), and automatic mapping-hypothesis capture with restart-readable
  evidence (K5, #45).
- **Harness-led authoring (bring your own agent)** — isolated Git proposals with
  revision-checked complete artifact edits (#34), resolved-source approval and
  measured inputs (#35), finalized effective-revision validation with bounded review
  (#36), human-only Git Review Admission with pinned digest confirmation (#37), and
  safe legacy import with transition guidance (#39).
- **Three MCP toolset surfaces** — Analyst/Authoring/combined registrations over one
  shared core, selected per entry point (#38); context page browsing via
  `list_context_pages`/`read_context_page` (spec 0015, #60/#61).
- **Multifact semantic layer** — normalized single validated OSI graph (#26), fact
  branches aggregated before alignment (#27), scoped filters, typed parameters and
  grain-safe detail (#28), aligned time/compute derived windows (#29), and local
  graph bundles exposed via CLI/MCP (#30).
- **Context layer** — qualified schema facts with deterministic explicit refresh
  (K1, #41), extension-v1 references and scoped term resolution (K2, #42), typed
  bounded identifier inspection (K3, #43), context-only admission (K4, #44),
  explicit legacy enrichment and installed-candidate verification (K6, #46),
  `context_signals` disclosure (#48) with freshness fix (#47), bounded record/result
  queries (spec 0014, #56–#58), supplied-evidence caveats on answers (#54/#55), and
  answer examples with operator-only review (#19–#21).
- **Document ingestion** — proposal-first ingestion of PDF/Office/HTML data
  dictionaries (ADR-0009) with symlink refusal and secret scanning.
- **Source registry** — declarative multi-source registry with a shared connection
  builder (ADR-0010): strict schema, DSN redaction, explicit argument precedence.
- **Context-carrying answers + packaged agent skill** — unmodeled questions capture
  reusable working context into a self-improving catalog; `ariadne-skill` packages it
  (spec rev 10, ADR-0011).
- **HTTP transport + deployment** — opt-in local-only bearer-token streamable-HTTP
  (`ariadne-serve --http`, #18), container/Compose binding with `healthz`/`readyz`
  probes, and Docker/Compose templates for external MCP projects.
- **Security fix: declared-grain SQL injection in validation** — a staged model's
  `primary_key` entries were interpolated raw into the executed grain-audit
  statement (`validate.py` Assertion 1), so agent-authored YAML could run
  arbitrary DuckDB SQL (e.g. `COPY ... TO`) during `validate_proposal`/
  `ariadne-validate`, before any human review. Key entries must now parse as
  plain column references and are re-rendered by sqlglot; the assembled audit
  statement is proven single before execution. Regression test included.
- **Grain guard re-checks live data on every `get_metric`** — the per-process
  memo meant an ETL reload introducing join fan-out under a long-lived
  `ariadne-serve` session was never caught until restart.
- **No implicit demo-database fallback** — `ariadne`/`ariadne-serve` without
  `--sources`, `--db` or an ambient `ariadne.yaml` now refuse explicitly
  instead of silently querying `examples/retail-demo/data/demo.db`.
- **Cleanup** — removed the dead `proposals.stage_ad_hoc` wrapper (superseded
  by the reserve/stage/release split) and an unused authoring helper;
  repo-wide `ruff format` pass.
- **Packaging** — first PyPI release. The distributions are `ariadne-data`
  (core) and `ariadne-agent`; `ariadneai` was rejected by PyPI's name-
  similarity rule (the unrelated `ariadne-ai` project blocks it), so the
  owner re-scoped the names (ADR-0018, amended). Publishing is tag-gated
  via `publish.yml` with the core wheel tested before upload.

## 0.1.0 - 2026-09-17

First release: the governed-metrics MVP for autonomous agents.

- **Authoring agent** — profiles a database, combines with human seed notes, drafts the
  full OKF context bundle + OSI semantic models; ≤3-round compile-feedback loop; writes
  only to `staging/`.
- **OKF v0.2 context bundle** — tables, join references (cardinality + grain-safety
  notes), policies extracted from seed notes, governed metrics, attested computations
  (attester = eval harness), operational skills; `index.md` per directory + `log.md`.
- **MCP facade (five tools)** — `list_metrics` (dimensions + routing hint),
  `list_datasets`, `search_context` (served + draft-marked staged), `get_metric`
  (governed, provenance SQL), `define_metric` (ad-hoc: grain-checked, compiled,
  read-only, auto-staged proposal).
- **No-unvalidated-execution invariant** — no path from tool arguments to execution
  bypassing the compile gate + single-statement guard.
- **Grain governance** — shared join-uniqueness guard (CTE-aware) at both the facade
  and authoring boundaries; audit assertions (declared-grain uniqueness, parent
  aggregate invariance) in `validate.py`; ADR-0006 resolution rubric.
- **Promotion gate** — `promote.py`: merge-only, `verified` trails, index regeneration,
  idempotent.
- **Eval harness** — golden question→value sets; fan-out trap sentinel
  ([Datus-ai/Datus-agent#1426](https://github.com/Datus-ai/Datus-agent/issues/1426)).
- **Packaging** — console scripts (`ariadne-author/validate/serve/promote/init`),
  `ariadne-init` project scaffolder (symlink-safe), `.env.example`.
- **Demo** — deterministic synthetic dataset (status-exclusion + EMEA currency gotchas),
  `demo.sh` end-to-end.
