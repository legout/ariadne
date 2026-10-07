# Specification: Advisory supplied source-quality evidence

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1 — written review complete** |
| **Written approval** | Owner replied “approved” after receiving both captured specification paths and the written-review request in this Pi conversation, 2026-10-06. This approves written revision 1 and opens separate implementation planning; it does not authorize execution, source/report acquisition or publication. |
| **Approval** | Owner, Pi conversation 2026-10-06: selected “Disclose supplied evidence” over bounded source probes or quality-based refusal. Subsequently approved the complete evaluation/source-quality proposal with “Approve both for capture,” including supplied reports colocated with physical-table OKF pages, separate `data_signals`, existing authoring/admission and the two glossary terms. Approval is for specification/vocabulary capture only; not implementation, source access, external report acquisition, integration, ticket changes or publication. |
| **Scope** | Advisory disclosure of supplied, scoped, as-of source-quality reports and Data Watermarks for directly identified query dependencies. |
| **Sources** | [Anthropic assessment](../research/2026-10-06-anthropic-self-service-analytics-assessment.md), [Context trust specification 0011](2026-10-06-0011-context-trust-signals.md), [schema/identifier specification 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md), [modular-core/Git specification 0009](2026-10-02-0009-modular-core-git-authoring.md), [business-answer evaluation 0012](2026-10-06-0012-business-answer-evaluation.md), [ADR-0016](../adr/0016-modular-core-git-authoring.md), [ADR-0017](../adr/0017-context-schema-and-identifier-knowledge.md), [shared Context implementation](../../src/ariadne/context.py), [Query runtime](../../src/ariadne/query.py), [canonical asset identity](../../src/ariadne/sources.py), [vocabulary](../../CONTEXT.md). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |

## 1. Purpose and boundaries

Make available source-quality evidence visible without presenting a current Context page or admitted definition as proof of current, complete data. A correct query over incomplete input can still produce a misleading answer. A Data Watermark is a qualified observation, not a universal completeness guarantee.

The owner selected advisory supplied evidence over core-generated probes or enforcement. Reuse physical-table OKF pages and the existing authoring/admission architecture rather than introducing a quality service, report registry or mutable pipeline feed. This is the smallest first revision, with a deliberate consequence: refreshing admitted report content uses the ordinary human review/admission route; unattended continuous updates are outside scope.

Non-goals: new source queries/probes; automatic `MAX(event_time)` calculations; upstream pipeline changes; background scanning; external report fetching; continuous feeds or a new store; executable checks or scripts supplied through reports; query refusal based on these signals; quality/confidence scores; inference of business rules from statistics; automatic approval; raw data/result dumps; permission/tool expansion; producer changes to existing schema observations or Context expiry; implementation, ticket changes or publication.

This is **separate from specification 0011**. That source assesses trust/lifecycle metadata in already-consumed Context pages through `context_signals`. This source adds a distinct, bounded source-quality view and its expressly identified table-metadata reads. It does not modify 0011's tasks, warning codes, consumed set, AC1–9, or advisory contract.

## 2. Evidence ownership and authoring

Store Source Quality Evidence in a versioned namespaced metadata section on the corresponding physical-table OKF page. Do not put it in executable OSI, duplicate it in a skill, create a second independently editable quality registry, or overwrite core-generated schema/measurement fields.

The supplied report is a domain owner's/upstream producer's **reported claim**, with identified evidence and scope. It is not a core-produced Mapping Evidence receipt, an authenticated provider result, a new schema observation or an independent numerical oracle. Human admission authorizes the exact artifact; it does not certify the report's current truth. Never synthesize core measurement/verification flags, quality pass outcomes or a report owner from admission or a document actor string.

Use existing typed Context page edits and exact-revision human admission. Validation checks the new profile's shape, source citations, asset binding and bounded content. It cannot grant source permission or establish numerical truth from the report. Legacy staged authoring retains its own Promotion gate; a legacy page without an established canonical table binding cannot be guessed into an asset's quality report.

Citations point to actual supplied source evidence through the page's existing `sources` mechanism. A referenced URL/file is an identity/citation, not permission to fetch it. Report acquisition, document access and any retention/export of internal evidence need their own applicable approvals. The Agent cannot author a successful report merely because a query returned plausible rows.

The execution plan defines the exact versioned metadata schema and finite metadata/result bounds within this contract. It must reject unsupported versions, malformed supported content, contradictory identities, executable content presented as a check, and attempts to overwrite system-owned observations. It does not add report types or acquisition capabilities under the guise of serialization.

## 3. Report and watermark contract

A report identifies:

- Stable report identity and exact canonical physical asset identity, tied to the containing table page rather than a display-name match.
- Stated scope and a clear source citation; private evidence remains in the owner-controlled local project, not copied into tracked/public fixtures.
- Observation/report time, expressed as an unambiguous aware instant for new structured temporal evidence.
- Available source/snapshot/version identity and provenance. Missing version evidence remains missing; the reader cannot prove an unversioned source is unchanged.
- Reported check outcomes and what each check tested. Outcomes distinguish pass, fail and unknown; a completeness claim must state its tested population/period/criterion rather than use an unexplained “healthy” label.
- Optional validity, owner/reporter, update-cadence description and Data Watermark where the source actually supplies them. Absence does not authorize invention or a default pass.

A Data Watermark records its reported value and meaning, such as an event-time boundary, ingestion boundary or snapshot-as-of boundary, with the field/scope, units/timezone and observation needed to interpret it. Do not reinterpret an event maximum as ingestion currency or complete arrival of every record. A source may have recent events and a failed completeness check at the same time; preserve both facts.

No arbitrary formula or check SQL is executed from this metadata. A check description explains the upstream criterion, not instructions to the answering Agent. New temporal evidence cannot silently inherit UTC from naive timestamps. Unsupported or ambiguous supplied facts must not be represented as assessed/current; ordinary pages without this new profile retain their existing behavior.

Report outcomes remain explicitly **reported at/as of** their observation. Supported expiry can establish that the report has expired, but an unexpired report does not establish that live data is healthy. Source-version or scope mismatches make the report inapplicable to the requested use; when correspondence cannot be established, disclose the unknown applicability instead of normalizing or guessing it.

## 4. Query interfaces and bounded consumption

The shared Context module interprets the quality metadata. Existing governed Query operations return an additive `data_signals` view alongside their current results; multi-metric results preserve the association between a metric, its directly identified assets and their reports. Python, CLI and applicable MCP/native adapters preserve this view without independent interpretation or additional tool permissions.

Each view identifies the relevant assets/pages, available reports/citations, observation/watermark semantics, reported outcomes, validity and applicability limitations. Distinguish available as-of evidence, expired evidence, unknown evidence and inapplicable evidence. Disclose missing/partial dependency coverage rather than presenting the known subset as a complete quality assessment. No general “current and healthy” conclusion is inferred from the absence of problems.

Read bounded metadata only for direct table dependencies whose exact identity is established through existing core bindings and admitted table citations. Cross-check binding to the relevant approved/admitted source identity wherever that evidence exists. Same table names in two sources cannot share a report by name alone. Missing binding, missing table citation or an unresolved dependency remains unknown coverage. Do not infer asset equivalence from natural-language aliases, notebook substrings or schema similarity.

No recursive upstream lineage/Reference traversal, directory-wide report discovery or external read is introduced. Reads use the selected admitted/Promoted project roots and existing containment restrictions. This source expressly authorizes only the new bounded local table-metadata consumption once separately implemented; it does not authorize opening new data locations or modifying the pinned snapshot on read.

Scope correspondence must be established from explicit identified evidence and mechanically available query/source facts, not free-text similarity. If the runtime cannot establish that the report covers the actual requested population/time/version, it says so. An asset-wide report is not silently treated as evidence for an unrelated station, period or snapshot.

The plan owns exact payload keys below `data_signals`, version/size handling and the applicable existing operations. It must preserve truthful partial/unknown disclosure and must not silently extend a fixed-role Agent's operations. No new query parameter, arbitrary report path or acquisition tool is required by this design.

## 5. Answer guidance and failures

An answer uses a short, relevant provenance/caveat when it relies on a source with a known failed check, expired evidence or material applicability/coverage limitation. Identify the source/report and its as-of scope rather than dumping every metadata field. Reported pass outcomes are qualified by observation and limitations; a current Policy or human-admitted definition cannot remove those qualifications.

Missing optional owner, cadence, validity or quality metadata stays explicitly unknown/absent; it does not by itself create an invented warning or a new failure. An unrelated report is not cited as support for the answer. A known scope/version mismatch cannot be presented as a matching pass. No model-generated confidence score or “reviewed” checkmark is substituted for provenance.

Keep the existing rows, SQL, rule bodies, governed/ad-hoc labels, admission and `context_signals` intact. These quality signals neither change arithmetic nor refuse an otherwise valid query. Existing source approval, snapshot integrity, compilation and live grain/relationship refusals still bind; a report never bypasses them.

Malformed new metadata fails the appropriate authoring validation before admission. If required report metadata later cannot be read/interpreted through the advisory consumer, expose unknown/partial evidence and the relevant limitation without fabricating a successful assessment or changing the numeric result. Existing source/admission/containment errors keep their established refusal behavior. No exception is turned into a synthetic quality pass.

Reads are pure: they do not restamp evidence, write reports, extend validity or refresh sources. Retrying returns another assessment of the same pinned bytes, potentially across an expiry boundary, not a new upstream check.

## 6. Migration and scope reconciliation

Projects without this optional profile keep their current query behavior and can disclose that quality evidence is unavailable. Do not migrate/restamp existing artifacts, reinterpret old generated schema observations as quality reports, or retroactively claim that an existing Computation/test reference checked the data.

An explicit proposal supplies new evidence with a canonical table binding and citations; it passes applicable validation and stops for human admission. Already-generated schemas, measured mapping receipts, identifiers, Policies and Context lifecycle fields keep their ownership and semantics. No source mentioned in a report is automatically registered or opened.

This is a bounded optional extension to the Context/profile and context-carrying Query contracts. ADR-0016/0017's shared-module, single-Context, source-approval, exact-revision and physical-fact authority remain intact. Neither their unrelated behavior nor the already-approved 0011 execution map is silently rewritten. Separate implementation planning must reconcile the new profile/consumer surfaces against those contracts before dependent work proceeds.

The private Trace Data evaluation in specification 0012 may later exercise source-quality disclosures using explicitly supplied evidence. It does not create genuine quality reports from oracle results or samples. Synthetic fixtures may model failed/expired/unknown evidence without pretending those are real upstream observations.

## 7. Observable acceptance and validation

1. **Distinct axes:** an admitted metric with a current Policy and an expired source-quality report keeps the same rows/SQL/governance, exposes separate `context_signals`/`data_signals`, and states the relevant source-evidence caveat. Neither context expiry nor admission proves source completeness.
2. **Recent but incomplete:** a report with a recent event watermark and a failed completeness check retains both facts. The answer does not call the source healthy or relabel the watermark as ingestion completeness.
3. **Exact identity:** same-named tables from different source assets cannot receive each other's report. Known scope/source-version mismatch is inapplicable; uncertain correspondence is unknown, not a matching pass.
4. **Coverage honesty:** if a metric's directly identified fact/lookup dependencies have only partial reports or binding evidence, the known reports remain visible and assessment coverage remains partial/unknown. No “all sources passed” is inferred.
5. **Unknowns:** no quality profile, missing optional owner/validity, ambiguous temporal evidence or unavailable source version cannot create a current healthy claim. Existing legacy queries remain usable.
6. **Validation authority:** malformed/unsupported new report metadata fails authoring validation; model-authored core measurement flags do not qualify as supplied evidence. Normal source approval/admission remains required.
7. **Bounded reads:** directly bound local table metadata is consumed without recursive traversal, external fetching, source probes, executable checks or directory-wide report scanning. An unrelated report cannot affect the answer.
8. **Adapter consistency:** applicable CLI/MCP/native operations preserve the shared view and old envelopes. No fixed-role tool set gains operations or new approval powers.
9. **Read-only migration:** identical reads/retries, including crossing an expiry boundary, do not alter artifacts, quality reports, producer stamps, admitted snapshots or data. Existing numerical/compile/grain/admission checks stay meaningful.
10. **Relevant answer disclosure:** an observed answer conveys the failed/expired/as-of issue for evidence actually relevant to it, without claiming an independent numerical oracle, execution attestation or live quality measurement.

Implementation obligation: **new-test** for the named profile/disclosure scenarios, with focused failing-first regressions when practical; **existing-check** for preserved numeric, Context, admission, containment and adapter behavior. Changed guidance requires genuine observed Agent evidence, reusing the established approach rather than mechanically edited traces. No quality report was acquired, source opened, probe run or runtime test passed by this documentation capture.

## 8. Capture checkpoint and handoff

- **Vocabulary:** Source Quality Evidence and Data Watermark are captured in [CONTEXT.md](../../CONTEXT.md); existing Context Freshness, admission, Document Verification and independent numerical/execution distinctions retain their meanings.
- **Decisions:** no new ADR is warranted. Colocation and human admission reuse the accepted Context architecture; the optional advisory profile/consumer addition is reversible. A future mutable feed, enforcement policy or quality service would require its own shaping/architectural assessment.
- **Behavior:** this revision owns the approved advisory supplied-evidence boundary, interfaces and acceptance examples, separate from 0011. The research article is supporting evidence, not an executable policy.
- **Uncertainty:** the material alternatives are settled. Planning must define exact metadata serialization, finite limits, binding/coverage disclosure and integration seams within these constraints. Genuine domain reports, oracle/snapshot evidence and applicable source/document permissions remain prerequisites, never facts invented by a writer.

Planning-contract v1; installed skill provenance unknown. Written revision 1 is owner-approved. The [paired implementation plan](../plans/2026-10-06-0013-source-quality-evidence.md) is owner-approved, revision 1, by the planning-only “approved” response in this Pi conversation, 2026-10-06; existing plans/tickets remain unchanged. Implementation, source/report acquisition, integration, commits/pushes, tickets and publication require their own applicable approval gates.
