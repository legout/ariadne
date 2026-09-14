# Implementation Plan: MVP Vertical Slice (Overview)

| | |
| :--- | :--- |
| **Goal** | Prove the authoring loop: profile → synthesize OKF+OSI → deterministic validate → human promote → governed MCP query |
| **Source** | [docs/specs/mvp-vertical-slice.md](../specs/mvp-vertical-slice.md) — approved by owner 2026-09-14, **revision 2** (grill-with-docs amendments) |
| **Capture checkpoint** | Recorded: `CONTEXT.md`; ADR 0001–0004; open uncertainty: Datus install/call mechanics → #1 |
| **Constraints** | Spec §2 non-goals; invariants §6: author writes only to `staging/`, `get_metric` never takes raw SQL, served artifacts only via promotion |
| **Runtime assumptions** | Python 3.11+, venv; deps: `duckdb`, `openai`, `pyyaml`, MCP SDK, Datus (form per #1); `pytest`; `OPENAI_API_KEY` |
| **Global validation** | `pytest` green; `ruff check` clean |
| **Contract** | planning-contract v1; provenance: `legout/skills` via `npx skills`, per-skill hashes in `skills-lock.json`, catalog revision unknown |

Canonical task bodies live in the GitHub issues below — edit them there, never here.

## Tickets

| Task | Issue | Depends on | Parallel window |
| :--- | :--- | :--- | :--- |
| T0 — Datus spike (gate) | [#1](https://github.com/legout/ariadne/issues/1) | — | ∥ #2 |
| T1 — seed + fixtures + seed notes | [#2](https://github.com/legout/ariadne/issues/2) | — | ∥ #1 |
| T2 — profiler | [#3](https://github.com/legout/ariadne/issues/3) | #2 | — |
| T3 — author + validate loop | [#4](https://github.com/legout/ariadne/issues/4) | #1, #3 | — |
| T4 — MCP facade (money test) | [#5](https://github.com/legout/ariadne/issues/5) | #1, #2, #4 (golden artifacts) | — |
| T5 — demo + README | [#6](https://github.com/legout/ariadne/issues/6) | #2–#5 | — |

```text
#1 ────────────┐
               ├──► #4 ──► #5 ──► #6
#2 ──► #3 ─────┘      ▲
 #2 ──────────────────┘ (facade fixtures)
```

## Requirement → ticket map

| Spec acceptance criterion | Ticket |
| :--- | :--- |
| §8.1 deterministic seed; seed notes | #2 |
| §8.2 author produces staging artifacts, validate ≤3 iterations | #3, #4 |
| §8.3 both governed metrics equal hand-computed fixtures | #5 (enabled by #1, #2) |
| §8.4 `search_context` returns gotchas page | #5 |
| §8.5 unknown-metric error; §8.6 `list_metrics` | #5 |
| §8.7 dual demo consumers | #6 |
| Spec §10 Phase 0 spike verdict | #1 |

## Residual risks

- **Datus compile determinism** on our OSI dialect subset — covered by #1's evidence threshold, not by later tests.
- **OpenAI flakiness in the live loop** — #4 mocks it; the 3-round cap + `review_needed` fallback is the mitigation, manually checked once in #6.
