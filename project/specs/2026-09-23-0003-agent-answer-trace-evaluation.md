# Specification: Agent answer-trace evaluation

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-23 — complete design and written specification approved; Pi-first recorded real-agent trace plus live smoke |
| **Scope approved** | Revision 1: evaluate the installed Ariadne skill's tool/command routing, numerical answer, caveat use, and governance label on a small synthetic demo; deterministic checks of an actual Pi trace plus a fresh manual Pi smoke when relevant behavior changes |
| **Prerequisite** | Complete and accept the [local artifact runtime](2026-09-23-0001-local-artifact-runtime.md) CLI/skill work (#7–#9) before capturing the reference trace; numeric retrieval improvements in [context retrieval](2026-09-23-0002-context-retrieval.md) may land independently |
| **Evidence** | [ktx/nao/OmniGraph comparison, recommendation 2](../research/2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md); existing [`tests/evals/golden.json`](../../tests/evals/golden.json) and [`tests/test_evals.py`](../../tests/test_evals.py) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Purpose and scope

The existing golden tests check compiled query values, not whether an agent chooses the governed route, recognizes an unmodeled question, or conveys attached business caveats. Add a small evidence-backed check of an **actual Pi session using the installed packaged Ariadne skill** against the synthetic retail demo. The local `ariadne` command is the default transport; MCP parity remains the local-runtime contract, not a second agent-evaluation matrix.

This is not an agent platform, an evaluator service, a model-scored answer-quality benchmark, or a claim that all Pi/Claude/Hermes models behave identically. The evaluation does not change the runtime's query API, the golden numeric oracle, or the governed-versus-ad-hoc boundary.

## Two levels of evidence

1. **Recorded run, deterministic check:** Capture a real fresh Pi session's user question, packaged-skill identity (hash or exact installed revision), actual `ariadne` command sequence and arguments, selected JSON outputs, and final answer as a small structured fixture. Record the host and source session reference; do not invent calls by scripting the desired sequence. Store only synthetic demo data and evidence needed for the assertions, not full transcripts, hidden reasoning, credentials, or unrelated tool output. A deterministic test checks that the *recorded run* met the rules below; it does not call a model or claim that the current agent would repeat the trace.
2. **Current-agent smoke:** After a packaged-skill or relevant runtime routing/context change, use a fresh Pi session with the installed skill and the demo to run the same questions, inspect the actual command/answer trace, and refresh the recorded fixture if behavior or the installed skill changed. Record whether this smoke was run in the change's verification report. When Pi or its model provider is unavailable, deterministic checks can still pass, but live-agent acceptance remains unverified; do not describe that as a passing current-agent evaluation. No provider-dependent CI gate is added.

The fixture is tied to the installed skill version so a different packaged skill cannot silently be presented as the recorded run's environment. Changing the trace requires a new observed Pi run; mechanically editing expected calls to make a test pass is not evidence.

## Questions and observable assertions

Keep the first corpus to two representative questions over the existing demo and numeric oracle:

- **Governed:** ask for gross margin by region. The observed path starts with discovery of available governed metrics and uses `get-metric gross_margin` rather than `define-metric` or handwritten SQL. The returned metric, dimensions, and values agree with the independent golden entry. The final answer labels the number governed, cites the served metric/Policy context actually returned, and states both relevant caveats: excluded CANCELLED/RETURNED orders and pre-2024 EMEA currency conversion. Merely receiving the caveats in tool JSON is not enough; the answer must convey them.
- **Unmodeled:** ask for mean order amount per customer, the existing ad-hoc golden scenario. After discovery, the observed path uses `list-datasets` and `define-metric` rather than claiming an existing governed metric answers it. The value agrees with the independent ad-hoc golden entry, the tool result has `governed: false`, and the final answer clearly calls it an ungoverned proposal, not a canonical metric. Its proposal remains staged; no agent promotion occurs.

Use exact command/result fields and expected values from the existing public CLI and `tests/evals/golden.json`; do not maintain a second numeric oracle. Check the answer's governance label, policy path references and essential caveat text using explicit deterministic assertions, not an LLM judge or a generic similarity score. If these questions stop matching the actual demo/golden set, update the evidence source and obtain review rather than silently weakening the assertions.

## Failure and migration behavior

A wrong command route, wrong value, missing caveat, unsupported Policy citation, false governance claim, or absent real-run provenance fails the relevant deterministic assertion. A saved trace's passing check is reported as **recorded-trace evidence**; a skipped, unavailable, or outdated live smoke is reported separately. No new production dependency or persistent runtime state is introduced. The initial trace is captured only after the local-runtime prerequisite is accepted; older MCP-first traces do not stand in for the local-first skill.

## Acceptance examples

1. A fresh Pi session with only the installed skill and demo answers both questions, with actual command events and final answers saved in the bounded trace fixture; the deterministic check reports both scenarios passing, and independent golden values agree.
2. Replacing `get-metric` with `define-metric` in the governed trace, deleting an answer caveat, or relabeling the ad-hoc answer governed causes the focused check to fail for the named reason.
3. Altering the packaged skill without refreshing its recorded environment invalidates the trace's current-skill claim; a missing live provider does not turn a recorded check into live evidence.
4. The numeric tests in `tests/test_evals.py` remain the value oracle, and neither the evaluation nor its smoke promotes an ad-hoc proposal.

## Shaping capture checkpoint

- **Vocabulary:** Existing Governed Metric, Ad-hoc Metric, Policy, and Proposal terms in [`CONTEXT.md`](../../CONTEXT.md) suffice; “recorded trace” is an evaluation artifact, not a new domain concept.
- **Decisions:** Recorded Pi evidence plus live smoke was chosen over scripted-only checks and live-provider CI. This is a reversible assurance choice, not a new architectural decision requiring an ADR.
- **Behavior:** This approved revision owns the scope, exclusions, two evidence tiers, checks, and acceptance examples. Approval of the design does not authorize implementation or publication.
- **Uncertainty:** The precise observed trace is gathered during implementation; it is not an unresolved product choice. An unavailable or failing real-agent run blocks a live-agent success claim.
