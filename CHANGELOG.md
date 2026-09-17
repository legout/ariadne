# Changelog

## Unreleased

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
