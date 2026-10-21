# Specification: Business-answer evaluation

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2 — workflow-policy amendment; behavioral scope unchanged** |
| **Workflow amendment approval** | Owner requested “can you execute the recommende migration for me?” in Pi session `01a115c0-1a8b-7099-87c3-df0aa8d87abc`, 2026-10-07, after the workflow audit. This approves the workflow-policy/source-handoff amendment and existing issue updates only; feature implementation, source/report acquisition, candidate assembly/integration, deployment, commits/pushes and releases remain separately gated. Original revision-1 approvals below remain historical provenance. |
| **Written approval** | Owner replied “approved” after receiving both captured specification paths and the written-review request in this Pi conversation, 2026-10-06. This approves written revision 1 and opens separate implementation planning; it does not authorize execution, source access or publication. |
| **Approval** | Owner, Pi conversation 2026-10-06: authorized the supporting-only Anthropic citation in plan 0011 and separate evaluation/source-quality shaping. Selected “Synthetic plus real domain,” then “Trace Data brakes” and “Reviewed snapshot SQL.” Approved the complete two-design proposal with “Approve both for capture,” covering specification/vocabulary capture only. No implementation, source access, snapshot acquisition, ticket changes, integration or publication is authorized. |
| **Scope** | A compact question-to-answer evaluation using synthetic cases plus a private Trace Data brake-batch/holding-torque slice, independent reviewed snapshot SQL, observed Agent evidence and explicit per-case outcomes. |
| **Sources** | [Anthropic assessment](../research/2026-10-06-anthropic-self-service-analytics-assessment.md), [existing Agent-trace specification](2026-09-23-0003-agent-answer-trace-evaluation.md), [golden numerical harness](../../tests/test_evals.py), [recorded-trace checker](../../tests/test_agent_trace.py), [measured retrieval specification](2026-09-23-0002-context-retrieval.md), [multi-fact specification](2026-09-30-0008-multi-fact-planner.md), [Context trust specification 0011](2026-10-06-0011-context-trust-signals.md), [source-quality design 0013](2026-10-06-0013-source-quality-evidence.md), [vocabulary](../../CONTEXT.md). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |

## 1. Purpose and boundaries

Measure whether an Agent answers the user's intended business question, not merely whether a selected definition compiles. Cover interpretation, route, parameters, values and final caveats/citations/governance labels. A correct calculation for the wrong interpretation fails.

Extend the existing Pi/local-CLI evidence approach rather than creating a service or another Agent framework. The owner selected synthetic plus one real domain over a synthetic-only first slice: synthetic data gives deterministic regression controls, while the real slice tests whether those controls transfer to actual business questions. A hosted evaluator, warehouse telemetry stack or broad model/transport benchmark is unnecessary for this scope.

Non-goals: runtime API/permission changes; new metric definitions or business rules just to improve a score; raw SQL exposed to the answering Agent; automatic admission; a model-scored truth judge; arbitrary accuracy/coverage targets; unattended provider-dependent CI; live-data access or snapshot extraction under this approval; collecting full conversations, hidden reasoning or credentials; copying private Trace Data evidence into tracked/public fixtures; implementation, tickets or publication.

Specification 0011 remains advisory Context reader/disclosure work. Its T1–T3 tasks and AC1–9 are not expanded by this evaluation. Specification 0003 retains its approved two-question trace and independent oracles; new cases are additive rather than rewritten historical evidence.

## 2. Architecture and evidence ownership

The evaluation has three separable inputs:

1. **Question contract:** owner-curated intended meaning and observable expectations, including legitimate clarification or unsupported outcomes.
2. **Ground truth:** an approved fixed data slice plus independently written, human-reviewed SQL where numerical/row expectations apply. Existing synthetic SQL oracles remain authoritative for their scenarios; do not create duplicate competing expectations.
3. **Observed run:** actual calls, bounded results and verbatim final answer from a fresh Pi session using the identified candidate skill and artifact revision.

Reuse the existing trace/checker approach and local structured fixtures. Shared mechanics may be factored only when the new cases require them; no second trace registry or evaluation service is introduced. Keep the original recorded trace and its assertions intact. The implementation plan owns precise fixture/checker organization and commands.

A recorded run's deterministic pass proves that recorded run met its case contract. It is not proof that the current Agent/model would repeat it. A fresh current-Agent run and its model/provider environment are separately reported. Missing provider access cannot become a passing live evaluation.

Evaluation setup/oracle code may execute approved independent SQL in the bounded evaluation environment. That does not grant the answering Agent a raw-SQL, source-approval, admission or Promotion capability. The oracle/expected answer is not added to the Agent's prompt as a shortcut; it receives the normal question, skill, admitted context and permitted tools.

## 3. Question and report contracts

Every case identifies:

- Stable case identity, domain, original question and relevant source references.
- Intended entity/population, period/timezone, units, grain and denominator where applicable.
- Expected outcome: answer, clarification or unsupported response. Clarification cases identify the material ambiguity and any predeclared user follow-up used in the observed conversation.
- Allowed governed/ad-hoc route and relevant parameters/definition constraints; do not demand incidental command ordering unrelated to correctness.
- Fixed data-slice identity and independently reviewed SQL/expected result when applicable, including numerical tolerance or row/key comparison semantics.
- Required explanatory caveats, supported source citations and truthful governance/validation labels.

The run report records the case outcomes and reasons, model identity, available provider identity, skill digest, code/artifact revisions, data-slice/oracle identity and actual-run provenance. Preserve available token/latency measurements; do not invent them when the harness cannot supply them. Store only bounded evidence required for the checks, not a raw transcript archive.

Report failures, coverage gaps and unverified prerequisites distinctly. Aggregate counts may summarize, but cannot conceal which questions failed or lacked trusted evidence. No percentage imported from Anthropic becomes a launch threshold. Domain readiness remains the owner's decision based on the named scenarios and actual evidence.

Compare consequential skill/routing changes on the same case slice and ground truth. A neutral or negative result is legitimate evidence; do not lengthen guidance or add review machinery merely to claim an improvement. No scheduled benchmark or monitoring service is introduced.

## 4. Synthetic and private real-domain slices

### Synthetic cases

Retain the existing governed gross-margin and unmodeled mean-order-amount questions and their independent USD/customer-ID oracles. Add only cases tied to named wrong-answer modes:

- Ambiguous entity/identifier or population requiring clarification instead of an arbitrary interpretation.
- Canonical exclusions/segments, units/currency and denominator selection.
- Calendar period versus trailing window, timezone and partial-period assumptions.
- Cross-fact grain/fan-out and repeated/empty results, using existing fixtures where sufficient.
- A genuinely unsupported question without invented fields, values or definitions.

Reuse 0011's actual lifecycle-caveat evidence/controls when that work is available; do not duplicate its expiry matrix or silently waive its acceptance. A case requiring not-yet-available behavior is marked pending/unverified, not passed.

### Trace Data brakes

The real slice starts from the owner's local question about brake batches and holding-torque measurements for identified orders. Local evidence inspected during shaping:

- `examples/trace-data/questions/bremsen_chargen_und_haltemomente.txt` — existing question and internal identifiers.
- `examples/trace-data/data/docs/notes.txt` — owner descriptions of entities, identifier representations and many-to-many relationships.
- `examples/trace-data/data/docs/bremsencharge.py` — candidate historical analysis logic, not an approved answer oracle.

These are **local-only dependencies**, intentionally not Git-tracked/public source links. Do not copy their order lists, raw identifiers, rows, internal locations or private snapshots into this repository's tracked fixtures, research notes or specifications. Keep real case inputs, expected outputs and run evidence in the owner-controlled local data-project evidence area; track only generic synthetic mechanics/contracts here. Deleting or lacking that private area in a fresh checkout makes the real slice unavailable, not a broken synthetic suite or an invented passing run.

Before a real case can establish accuracy, its reviewed question contract must settle which order representation is meant, applicable site/station/time scope, the meaning and unit of the measurement, and whether it asks for all measurements or the latest one. Batch selection and identifier extraction cannot be inferred into business rules from notebook substrings, casts, barcode patterns or a sample match. Explicitly account for repeats, missing links and joins that could multiply measurements.

Ground truth uses independently written SQL over a fixed approved slice, reviewed against domain evidence by the human. Ariadne compiler output, an unreviewed notebook, statistical agreement or a second model agreeing is not that oracle. Source access, bounded snapshot acquisition and any retention/export permission require their own existing approvals. This design capture does not run the notebook or open remote sources.

If Ariadne lacks the required governed definition or safe operation for a case whose expected outcome is an answer, report a coverage gap. Do not silently change the expectation to unsupported, authorize an unsafe join, expand role tools or add a metric under the evaluation task. Any resulting product change returns to its own shaping/approval route.

## 5. Execution, failures and reproducibility

Identify the tested data slice and artifact/skill revisions before observing the answer. A pinned catalog is not a pinned source dataset. If data changes between oracle and Agent execution or the approved slice cannot be identified, numerical accuracy is unverified until both operate on the same data. Query/parameter checks can still report their own narrower result; they cannot prove complete source data.

Use a fresh Agent session per independent case, or record the declared conversation history for a clarification case. Capture actual command events/results and the final answer; never manufacture the desired command sequence or mechanically update skill hashes in an old trace. Preserve the existing independent re-extraction/check discipline.

Wrong interpretation, unsupported parameter/filter, incorrect value or rows, missing essential caveat, invented citation, false governance/validation claim or broken run provenance fails the applicable assertion. Interpretive expectations must be explicit enough for bounded deterministic checks or human disposition; an LLM opinion is not a substitute for the reviewed contract.

Reports distinguish: failed assertion, uncovered required capability, missing/unreviewed ground truth, unavailable provider and passing recorded/current evidence. Retries are new identified observations; do not overwrite a failure with an unexplained later pass or mutate source artifacts during evaluation. Ad-hoc proposals remain unadmitted and must not be promoted by the Agent.

## 6. Migration and observable acceptance

1. **Preserved evidence:** the original two-question recorded-trace checks and golden SQL oracles remain meaningful; new cases do not rewrite observed historical calls/answers or weaken their caveat/governance assertions.
2. **Correct number, wrong meaning:** a case with an explicitly reviewed population/denominator fails if the Agent uses a different interpretation even when its chosen calculation is internally correct.
3. **Clarification:** an ambiguous case elicits the declared material clarification; a stated follow-up produces the matching parameters and answer. Guessing one representation does not pass.
4. **Temporal/population control:** the fixed case catches a trailing-window substitution for the intended calendar period, missing canonical exclusion or wrong unit. Unsupported defaults are not invented in the Agent prompt or grader.
5. **Cross-fact control:** a result inflated by repeated facts fails against the independent fixed-slice oracle; required safety refusals remain intact.
6. **Private real slice:** reviewed snapshot SQL, matched slice identity, actual calls and final answers support the Trace Data outcomes without leaking private identifiers or data into tracked artifacts. An unavailable real slice is reported separately from synthetic results.
7. **Coverage honesty:** a required-answer brake case unsupported by the catalog is a named coverage gap, not a passing refusal or an unauthorized metric-authoring task.
8. **Current versus recorded:** a passing old trace with a changed skill/model environment cannot be labeled a passing current-Agent run. Missing provider/oracle/snapshot evidence remains unverified.
9. **Scope preservation:** no evaluation run admits artifacts, opens unapproved sources, changes 0011's acceptance or expands Agent tool permissions.

Implementation obligation: **new-test** only for named additional checker behavior lacking meaningful existing coverage, with expectations derived independently from reviewed question contracts and numerical oracles; **existing-check** for observed cases already supported by the accepted checker and preserved numerical, trace, privacy and governance contracts. Ordering for new behavior is the worker's choice; discovered checker bugs require a synthetic reproducing test that fails before repair, and behavior-affecting refactors require characterization before mutation. Actual current-Agent/domain evidence is a separate gate from deterministic checker tests. No tests or evaluations were run by this documentation capture.

## 7. Capture checkpoint and handoff

- **Vocabulary:** existing Governed/Ad-hoc Metric, Grain, Policy, Source Approval, admission and Independent Numerical Validation terms suffice. “Case,” “oracle” and “recorded run” are evaluation artifacts, not new repository domain concepts.
- **Decisions:** no new ADR is warranted; this reuses the accepted local evidence approach and is a reversible assurance extension, not a new runtime/service architecture.
- **Behavior:** this revision captures the owner-approved complete design and observable examples. The Anthropic article is supporting evidence, not a behavioral source or accuracy guarantee.
- **Uncertainty:** material scope choices are settled. Private question contracts, oracle review, fixed-slice acquisition, provider access and exact fixture/checker organization remain explicit planning/execution prerequisites. Their absence blocks relevant evidence, not permission to invent results.

Planning-contract v1; installed skill provenance unknown. Behavioral revision 1 remains approved; revision 2 adds only the owner-approved 2026-10-07 workflow-policy amendment. The [paired implementation plan](../plans/2026-10-06-0012-business-answer-evaluation.md) is owner-approved, revision 2: original revision 1 approval was the planning-only “approved” response in this Pi conversation, 2026-10-06; the workflow amendment expands no feature scope. Implementation, source access, integration, commits/pushes, tickets and publication need their own applicable authority.
