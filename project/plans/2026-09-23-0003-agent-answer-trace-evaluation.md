# Implementation plan: Agent answer-trace evaluation

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized; implementation not authorized by ticketization** |
| **Goal** | Test whether a real Pi agent with the installed skill routes and answers two synthetic metric questions correctly, without provider-dependent CI. |
| **Source** | [Approved answer-trace specification, revision 1](../specs/2026-09-23-0003-agent-answer-trace-evaluation.md) |
| **Source approval** | Owner, pi session 2026-09-23 — complete design and written specification approved; exact scope is the source header's revision 1. |
| **Plan approval** | Owner, same session — approved this one-unit trace evaluation plan; subsequently requested ticketization. |
| **Prerequisite** | Issues [#7](https://github.com/legout/ariadne/issues/7) → [#8](https://github.com/legout/ariadne/issues/8) → [#9](https://github.com/legout/ariadne/issues/9) are closed; confirm their local-first CLI/skill baseline is accepted and integrated before recording a Pi trace. Retrieval issue #10 is independent. |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Constraints and capture checkpoint

- Use synthetic retail-demo data and the independent numeric oracle in `tests/evals/golden.json`/`tests/test_evals.py`. A saved trace tests only that recorded Pi run; it is not evidence of current agent behavior after a skill/runtime change. No new production runtime API, model judge, service, provider requirement in CI, raw transcript, or agent-host matrix.
- **Vocabulary:** existing Governed Metric, Ad-hoc Metric, Policy, and Proposal terms suffice. **Decision:** recorded real Pi evidence plus a fresh live smoke is a reversible assurance choice; no ADR. **Behavior:** the approved specification owns questions, routes, caveats, failure and evidence claims. **Uncertainty:** a genuine Pi trace is an execution prerequisite; an unavailable provider leaves live acceptance unverified.
- No new untrusted-input, credential, authentication or dependency boundary is touched: `security: n/a`. Only synthetic demo data enters the recorded fixture; never capture secrets or unrelated session text. One writer, after the accepted local-runtime baseline, owns the evaluation.

## Canonical ticket and requirement coverage

[#11 — Evaluate a real Pi answer trace against Ariadne's governed and ad-hoc routes](https://github.com/legout/ariadne/issues/11) owns the single executable task body, files, interfaces, `new-test` obligation, red/green sequence, checks, completion evidence and non-goals. This overview records ordering and coverage; do not maintain duplicate task definitions.

| Specification acceptance | Ticket | Dependency |
| :--- | :--- | :--- |
| AC1 — actual Pi run, both questions, independent numeric oracle | #11 | Accepted and integrated #7–#9 |
| AC2 — named failures for wrong route, missing caveat, false label | #11 | Same |
| AC3 — packaged-skill provenance and separate current live-smoke status | #11 | Same |
| AC4 — unchanged golden oracle, no agent Promotion | #11 | Same |

## Execution and integration

After #7–#9 are accepted and integrated, observe an actual Pi run rather than scripting a desired trace. The deterministic recorded-trace check and separately reported fresh live smoke must not be conflated. One candidate review covers the observed provenance and integration. The parent retains implementation, fix, and integration approval gates; creating #11 authorizes none of them. Material changes to routing or acceptance return to the approved specification for reconciliation.
