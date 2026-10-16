# Useful tests when agents write both code and tests

**Status:** quick research, 2026-10-16; recommendations, not an audited deletion list or an approved cleanup implementation. Planning-contract v1; installed provenance unknown. No tests, benchmarks, mutation campaigns or agents were run for this research. Existing source changes and the paused #74 worker were left alone.

## Conclusion

A substantial test cleanup may be justified, but AI authorship alone does not establish that a test is useless. The important distinction is **independent evidence about intended behavior versus self-confirmation of the current implementation**. This research does not establish what proportion of Ariadne's tests falls into either category.

Generated tests can execute buggy code, reproduce its mistaken expectations and report success. More tests, higher coverage, another agent's approval or a mutation score do not automatically fix that oracle problem. Conversely, agent-generated tests aimed at concrete, previously undetected faults can be useful. [S1–S3]

## What the sources support

1. **The oracle is a central weakness when code and tests are generated together.** A September 2026 preprint studies five LLMs and four benchmarks, with over 6,000 faulty program instances. Its abstract reports that generated assertions often fail to expose faulty behavior even when test inputs trigger it; prompt-aware oracles help but remain limited. This is benchmark evidence, not a measurement of our repository or proof that most AI-written tests are useless. [S1]
2. **Coverage and mutation scores are context-dependent proxies.** A July 2026 replication study distinguishes regression-style generation against reasonably trusted code from finding faults in potentially buggy code. Its abstract reports that coverage and mutation scores cease to be reliable effectiveness indicators in the latter setting. Do not turn cleanup into a coverage target or a full-repository mutation exercise. [S2]
3. **LLM-generated tests are not inherently worthless.** Meta describes targeting concrete privacy/compliance faults with realistic mutations and generating tests for faults existing tests miss. It reports engineers accepting 73% of generated tests in its trial. That is a vendor-reported, domain-specific result, not a universal quality guarantee, and differs from asking an agent to bless its own newly generated implementation. [S3]
4. **Assess outcomes rather than a prescribed implementation path.** Anthropic recommends deterministic graders where possible and warns that enforcing exact tool-call sequences is brittle. It also requires human calibration for model judges. This article concerns agent evaluations; its outcome-versus-path principle is relevant here, but is not direct evidence for a particular software unit-test/integration-test ratio. [S4]

## Proposed keep / merge / remove criteria

The following is a synthesis, not a claim that any listed defect was found in Ariadne's tests.

| Usually valuable | Necessary independent evidence |
| --- | --- |
| Regression for a real bug | A reachable incident or defect; independently correct expected behavior; reproducing the original failure when practical. |
| Public behavior/contract check | Observable result or state specified by an approved requirement, not an assertion copied from current output. |
| Small unit test for consequential logic | Independently worked arithmetic, boundary rules, dates, grain or other nontrivial domain expectations. Pure unit tests are not the enemy. |
| Focused integration check at a real boundary | Actual serialization, filesystem/Git state, permission enforcement or packaging behavior that isolated mocks cannot establish. Not every calculation needs duplication through every transport. |
| A small number of domain properties | An independently justified invariant, such as no mutation on stale revision or idempotent unchanged ingestion. A round-trip alone is insufficient if both directions share the same mistake. |

Strong cleanup candidates are:

- tests whose entire purpose is a deliberately retired workflow;
- repeated cases with the same behavioral claim and no distinct boundary risk;
- assertions that the implementation returns the value the test just asked a mock to return;
- unnecessary private-helper, internal-call-order or source-text assertions that fail on behavior-preserving refactors;
- expected values calculated by reproducing the production algorithm or captured from its output without an independent oracle;
- generated edge-case inventories with no named reachable scenario or material failure;
- repeated whole-suite runs after formatting, prose changes or an unchanged relevant source/environment.

These are **candidates**, not automatic deletion rules. Call ordering can be essential for authorization-before-I/O; exact text matters for Verbatim content and wire contracts; installed-package import checks can catch real packaging defects. Fault injection at an actual external boundary can be useful. Inspect the claimed behavior before removing such checks.

## Small execution policy, not another testing project

Before adding or running a check, answer:

1. What concrete user-visible failure or written contract does it protect?
2. Where does the correct expectation come from, independently of this implementation?
3. Is that behavior already evidenced by an applicable passing test?
4. What is the cheapest stable seam that proves the remaining risk?

Default to **one focused check for the uncovered changed behavior**, not one test per function, layer or checkbox. Reuse passing evidence only where relevant code, inputs and environment still match; do not claim unchecked changes are covered. If there is no new behavioral risk, no new test is necessary. A genuinely different material risk needs an explicit reason, not an invented quota.

For cleanup, first remove retired-workflow tests and merge demonstrable duplicates. Preserve independently derived numerical oracles and actual admission, source-permission, query-safety and persistence contracts. Do not replace many brittle unit tests with a giant slow end-to-end suite. Do not silently relax expected values to match output. Keep execution frequency separate from suite contents: repeatedly running a useful test can still be wasteful.

## Scope and limitations

Two bounded search batches covered empirical oracle quality, practical generated-test use and outcome-based evaluation. The existing wiki's agent-observability page was checked; it covers framework evaluation rather than this specific oracle problem. The two paper abstracts and relevant engineering-article passages were read; full paper methods and artifacts were not independently audited. Google Testing Blog results were excluded from evidence because readable extraction returned reader comments rather than the article body.

No test inventory, deletion percentage, runtime saving or repository-specific fault-detection claim is established. The next sensible step is a bounded, deletion-first review of existing tests—not generating replacement suites or launching a mutation/coverage campaign. The research is captured only in the project's research namespace under its artifact contract, not duplicated into the global wiki.

## Sources

- **S1 — End-to-end generated code/tests, oracle limitations:** [How effective are traditional test criteria at detecting bugs in large language models generated code?](https://arxiv.org/abs/2609.09315v1), submitted 2026-09-08; abstract inspected.
- **S2 — Proxy metrics depend on setting:** [Do Coverage and Mutation Scores of LLM-Generated Test Suites Correlate with Their Effectiveness? (Replicability Study)](https://arxiv.org/abs/2607.22880v1), submitted 2026-07-24; abstract inspected.
- **S3 — Practical, targeted generated tests:** [Meta: LLMs Are the Key to Mutation Testing and Better Compliance](https://engineering.fb.com/2025/09/30/security/llms-are-the-key-to-mutation-testing-and-better-compliance/), 2025-09-30; relevant design/trial passages inspected.
- **S4 — Deterministic outcome grading and brittle paths:** [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), especially “Evaluating coding agents” and “Step 5: Design graders thoughtfully”; relevant passages inspected.
