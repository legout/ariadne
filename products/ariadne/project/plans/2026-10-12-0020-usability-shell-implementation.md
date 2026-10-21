# Implementation plan: Usability shell (status, setup, search, review)

| | |
| :--- | :--- |
| **Status** | **Execution-authorized** — Owner, pi session 2026-10-12, explicitly authorized implementation of the open issues #62–#65. This file is the thin coordination overview; the tickets own the canonical task bodies. It grants no target-integration, push, release or publication authority. |
| **Goal** | Implement the four approved usability shells (`ariadne status`, `ariadne setup`, `ariadne search`, `ariadne review`) plus the `discover` MCP/native surface by composing — never bypassing — the existing gates. |
| **Sources** | [spec 0016](../specs/2026-10-12-0016-project-status-command.md) (#62), [spec 0017](../specs/2026-10-12-0017-setup-onboarding-wizard.md) (#63), [spec 0018](../specs/2026-10-12-0018-unified-discovery-search.md) (#64), [spec 0019](../specs/2026-10-12-0019-human-review-walkthrough.md) (#65) — each **Approved, revision 2**; [ADR-0021](../adr/0021-usability-shell-composition.md) (accepted); scoped **usability amendment** in [spec 0001](../specs/2026-09-23-0001-local-artifact-runtime.md). |
| **Contract** | planning-contract v1; installed at `~/.pi/agent/skills/planning-contract` (catalog revision unknown). |
| **Capture checkpoint** | Recorded in each spec's *Shaping capture checkpoint*; no new domain terms; ADR-0021 owns the durable decisions. No unresolved material decision. |

## Out of scope

Issues #18 (HTTPS transport — no owner deployment choice) and #52 (private trace evaluation — owner-deferred 2026-10-10) are open but owner-parked without an approved behavioral source; they are not part of this run. Option C (ktx evidence pipeline) stays on hold. No changes to existing query-command contracts.

## Sequencing constraint (why one lane)

All four tickets share write surfaces: `src/ariadne/cli.py`, the packaged skill text, and (via #62/#64) the query.py seam. The planning-contract parallel rule requires independent owned surfaces, so this runs as **one sequential lane, one writer at a time**, each lane based on the previous lane's accepted result:

1. **Lane 62 — status** (spec 0016): new diagnostic resolver + report; extracts shared read-only artifact/registry/admission-state readers; `new-test` (spec ACs 1–7).
2. **Lane 64 — search** (spec 0018): shared artifact-only discovery seam in/around `query.py`, grouped CLI command, `discover` on analyst/combined MCP + embedded analyst surface (`ariadne-agent`), skill pointer; `new-test` (spec ACs 1–7, incl. agent suite when the embedded surface changes).
3. **Lane 63 — setup** (spec 0017): setup wizard composing `ariadne-init`/typed source seams/`ariadne-skill install`, Git-prerequisite handoff, README PyPI-first quickstart, skill operator rule; `new-test` (spec ACs 1–8; AC 8's candidate-wheel walkthrough is a build-and-smoke step, release stays gated).
4. **Lane 65 — review** (spec 0019): operator-only walkthrough, inert mapping selection, one-call admission delegation, legacy promoter delegation without `--yes`; `new-test` (spec ACs 1–7).

Lane 64 follows 62 directly (both extract from `query.py`; adjacent context, less rebase risk). Lanes 63/65 consume 62's status machinery.

## Global validation (not already per-task)

- Core suite: `uv run --extra dev pytest -q` (baseline 2026-10-12 on 22e7cbe: green, 860 passed / 1 skipped) — rerun per lane and on the final candidate.
- Lint: `uv run --extra dev ruff check src tests` per lane.
- `ariadne-agent` suite (only when lane 64 touches it): run inside `ariadne-agent/` per its own `pyproject.toml`/`uv.lock`.
- Candidate review (fresh Pi reviewer) after each lane and once for the assembled candidate; one fix pass + one delta recheck per finding.

## Delivery boundary

Supervised/autonomous execution prepares and reviews the assembled candidate branch beneath the shared worktree root and pauses there. Target integration (`merge-worktree`), push, issue comments/closure, and release each need separate owner authorization.
