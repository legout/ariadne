# Implementation Plan: Rev 6 — Grain Enforcement + OKF Bundle Maturity

| | |
| :--- | :--- |
| **Goal** | Grain audit in the validation loop (ADR-0006 §5) and the OKF v0.2 bundle structure with agent-authored generation (ADR-0007) |
| **Source** | [project/specs/mvp-vertical-slice.md](../specs/mvp-vertical-slice.md) — approved by owner 2026-09-15, **revision 6** (§6 grain-audit invariant, §8.14–8.17) |
| **Capture checkpoint** | ADR-0007; CONTEXT.md + Bundle, Grain, Policy, Attested Computation; contract v1; provenance: legout/skills via npx skills, per-skill hashes in skills-lock.json |
| **Constraints** | Spec §2 non-goals; invariants §6 (incl. merge-only promotion, no wipe); lanes serial — both touch `author.py` |
| **Runtime** | Python 3.12 (uv venv), existing deps + sqlglot |
| **Global validation** | `pytest` green (xfail sentinel counts as green); `ruff check` clean; `uv lock --check` |

## Lane board

| Lane | Claimed files | Depends on | Validation unit | Obligation | Review |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A — grain enforcement** | ariadne/validate.py, ariadne/author.py (system prompt only), ariadne/serve.py (rejection text only), tests/test_validate.py, tests/test_serve.py | base (rev 6 commit) | audit assertions | new-test | candidate review (normal) |
| **B — OKF maturity** | ariadne/author.py, scripts/promote.py (new), scripts/demo.sh (use promote.py), tests/test_author.py, tests/test_promote.py (new), context_layer/ restructure content | lane A accepted | bundle generation + promotion bookkeeping | new-test | candidate review (normal) |

## Lane A — grain enforcement

- [ ] `validate.py` post-compile audit phase (ADR-0006 §5), run when a db path is available: **Assertion 1** — declared `primary_key` unique over the compiled dataset source; **Assertion 2** — parent aggregate invariance (raw parent-table sum vs post-join sum per parent metric; divergence ≠ 0 → fail). Remediation text references the rubric pattern.
- [ ] `serve.py` grain-rejection text references the ADR-0006 rubric (pivot / child-grain / allocation) instead of bare GROUP BY.
- [ ] `author.py` system prompt gains the golden rules (single declared grain; additive ownership; cardinality elimination) with the ADR reference.
- [ ] Tests (§8.14): fanned authored model fails Assertion 2; non-unique declared grain fails Assertion 1; valid models pass; suite green.

## Lane B — OKF maturity

- [ ] `author.py` generates the full bundle from profile + seed notes + models: `tables/`, `references/joins/` (cardinality from profiler evidence), `policies/` (extracted from seed notes), `metrics/` (existing), `computations/` (sanctioned compiled SQL; `attester: tests/test_evals.py`), `skills/` (run/promote/query guides). Enriched frontmatter per spec: `verified` list, `stale_after`, `grain`, `governed_by`, policy-linked `sources`.
- [ ] `scripts/promote.py`: staged → served **merge** (never wipe), append `verified: [{by, at}]`, regenerate every `index.md` (SPEC §8 body form: sections + links + frontmatter descriptions), append `log.md`; idempotent re-promote. `demo.sh` uses it.
- [ ] `context_layer/` restructured to the bundle; existing metrics pages migrated.
- [ ] Tests (§8.15–8.17): mocked-LLM generation per content type (required frontmatter per type; metric sources cite policies); promote bookkeeping + idempotency; discovery across new folders (served + draft-marked staged); one live run (endpoint from `.env`).

## Requirement → lane map

| Spec criterion | Lane |
| :--- | :--- |
| §8.14 grain audit | A |
| §8.15 bundle generation | B |
| §8.16 promotion bookkeeping | B |
| §8.17 discovery | B |
| Suite + sentinel green | both |

## Residual risks

- **Live-LLM bundle quality** is judged by the mocked-fixture contract + one live run; multi-type authoring quality at scale is exactly what the eval harness grows into later.
- **Frontmatter schema drift** between author output and promote/index consumers — mitigated by the promote tests round-tripping real staged pages.
