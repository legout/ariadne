# Specification: Agent answer-trace evaluation

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-23 — revision 1 approved; owner, pi session 2026-09-24 — approved revision 2's precise ad-hoc USD/customer-ID definition and independent oracle reconciliation after an observed Pi trace exposed the raw-amount mismatch |
| **Scope approved** | Revision 2: evaluate actual Pi routing, numerical answer, caveats, and governance label on the synthetic demo; the ad-hoc mean uses billable order amounts converted to USD for pre-2024 EMEA orders, grouped by customer ID, with its independent SQL oracle reconciled to that definition |
| **Prerequisite** | Complete and accept the [local artifact runtime](2026-09-23-0001-local-artifact-runtime.md) CLI/skill work (#7–#9) before capturing the reference trace; numeric retrieval improvements in [context retrieval](2026-09-23-0002-context-retrieval.md) may land independently |
| **Evidence** | [ktx/nao/OmniGraph comparison, recommendation 2](../research/2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md); existing [`tests/evals/golden.json`](../../tests/evals/golden.json) and [`tests/test_evals.py`](../../tests/test_evals.py) |
| **Contract** | planning-contract v1; installed skill provenance unknown |
| **Retired** | Owner, Pi session 2026-10-12 — the recorded agent answer-trace evidence tier was removed: `tests/test_agent_trace.py` and `tests/evals/agent_trace.json` are deleted, and real-world checks of the packaged skill are performed manually by the owner instead of from a recorded session. The independent numeric oracles remain in [`tests/test_evals.py`](../../tests/test_evals.py); historical plans/research records keep their references. |

## Purpose and scope

The existing golden tests check compiled query values, not whether an agent chooses the governed route, recognizes an unmodeled question, or conveys attached business caveats. Add a small evidence-backed check of an **actual Pi session using the installed packaged Ariadne skill** against the synthetic retail demo. The local `ariadne` command is the default transport; MCP parity remains the local-runtime contract, not a second agent-evaluation matrix.

This is not an agent platform, an evaluator service, a model-scored answer-quality benchmark, or a claim that all Pi/Claude/Hermes models behave identically. The evaluation does not change the runtime's query API or the governed-versus-ad-hoc boundary. Revision 2 corrects the existing ad-hoc independent numeric oracle to the owner-approved USD definition; governed entries and their oracles remain unchanged.

## Two levels of evidence

1. **Recorded run, deterministic check:** Capture a real fresh Pi session's user question, packaged-skill identity (hash or exact installed revision), actual `ariadne` command sequence and arguments, selected JSON outputs, and final answer as a small structured fixture. Record the host and source session reference; do not invent calls by scripting the desired sequence. Store only synthetic demo data and evidence needed for the assertions, not full transcripts, hidden reasoning, credentials, or unrelated tool output. A deterministic test checks that the *recorded run* met the rules below; it does not call a model or claim that the current agent would repeat the trace.
2. **Current-agent smoke:** After a packaged-skill or relevant runtime routing/context change, use a fresh Pi session with the installed skill and the demo to run the same questions, inspect the actual command/answer trace, and refresh the recorded fixture if behavior or the installed skill changed. Record whether this smoke was run in the change's verification report. When Pi or its model provider is unavailable, deterministic checks can still pass, but live-agent acceptance remains unverified; do not describe that as a passing current-agent evaluation. No provider-dependent CI gate is added.

The fixture is tied to the installed skill version so a different packaged skill cannot silently be presented as the recorded run's environment. Changing the trace requires a new observed Pi run; mechanically editing expected calls to make a test pass is not evidence.

## Questions and observable assertions

Keep the first corpus to two representative questions over the existing demo and numeric oracle:

- **Governed:** ask for gross margin by region. The observed path starts with discovery of available governed metrics and uses `get-metric gross_margin` rather than `define-metric` or handwritten SQL. The returned metric, dimensions, and values agree with the independent golden entry. The final answer labels the number governed, cites the served metric/Policy context actually returned, and states both relevant caveats: excluded CANCELLED/RETURNED orders and pre-2024 EMEA currency conversion. Merely receiving the caveats in tool JSON is not enough; the answer must convey them.
- **Unmodeled:** ask for mean order amount per customer, the existing ad-hoc golden scenario. The measure is `AVG` of billable order amounts in USD, grouped by `customer_id`: exclude `CANCELLED`/`RETURNED`, convert pre-2024 EMEA amounts using `currency_conversion_rate.rate_to_usd`, and leave other amounts in USD. After discovery, the observed path uses `list-datasets` and `define-metric` rather than claiming an existing governed metric answers it (a served metric context page alone does not make an unlisted semantic metric governed). Compare the returned rows against the independent SQL oracle in `tests/test_evals.py`; the ad-hoc `tests/evals/golden.json` entry retains `expected: null` with dimension `customer_id`. The tool result has `governed: false`, and the final answer clearly calls it an ungoverned proposal, not a canonical metric. Its proposal remains staged; no agent promotion occurs.

Use exact command/result fields and expected values from the public CLI and `tests/evals/golden.json`/`tests/test_evals.py`; do not maintain a second numeric oracle. Revision 2 updates the independent ad-hoc SQL and golden dimension to the definition above before checking an actual trace, without editing observed calls or results. Check the answer's governance label, supported Policy references and essential caveat text using explicit deterministic assertions, not an LLM judge or a generic similarity score. If these questions stop matching the actual demo/golden set, update the evidence source and obtain review rather than silently weakening the assertions.

## Failure and migration behavior

A wrong command route, wrong value, missing caveat, unsupported Policy citation, false governance claim, or absent real-run provenance fails the relevant deterministic assertion. A saved trace's passing check is reported as **recorded-trace evidence**; a skipped, unavailable, or outdated live smoke is reported separately. No new production dependency or persistent runtime state is introduced. The initial trace is captured only after the local-runtime prerequisite is accepted; older MCP-first traces do not stand in for the local-first skill.

## Acceptance examples

1. A fresh Pi session with only the installed skill and demo answers both questions, with actual command events and final answers saved in the bounded trace fixture; the deterministic check reports both scenarios passing, and independent golden values agree.
2. Replacing `get-metric` with `define-metric` in the governed trace, deleting an answer caveat, or relabeling the ad-hoc answer governed causes the focused check to fail for the named reason.
3. Altering the packaged skill without refreshing its recorded environment invalidates the trace's current-skill claim; a missing live provider does not turn a recorded check into live evidence.
4. The revised independent SQL in `tests/test_evals.py` remains the single ad-hoc value oracle (USD billable-order average per customer ID), and neither the evaluation nor its smoke promotes an ad-hoc proposal.

## Shaping capture checkpoint

- **Vocabulary:** Existing Governed Metric, Ad-hoc Metric, Policy, and Proposal terms in [`CONTEXT.md`](../../CONTEXT.md) suffice; “recorded trace” is an evaluation artifact, not a new domain concept.
- **Decisions:** Recorded Pi evidence plus live smoke was chosen over scripted-only checks and live-provider CI. This is a reversible assurance choice, not a new architectural decision requiring an ADR.
- **Behavior:** This approved revision owns the scope, exclusions, two evidence tiers, USD ad-hoc definition, checks, and acceptance examples. The owner chose this definition after an unscripted Pi answer returned $632.35 for customer ID 1 while the previous raw-amount oracle returned $602.08. No new runtime behavior or ADR is introduced; approval of the design alone does not authorize publication.
- **Uncertainty:** The precise recorded fixture must be captured from an actual Pi run, never rewritten to match the revised oracle. An unavailable or failing real-agent run blocks a live-agent success claim.
