# Specification: Bounded record queries and query results

**Accepted scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; the owner approved the complete written revision and these scoped amendments with “Schriftliche Fassung freigeben (Recommended)”. Complete-output, source authority, numerical and deadline safeguards remain; successful ad-hoc execution no longer reserves/stages artifacts or returns staging receipts. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved specification, revision 1** |
| **Approval** | Owner approved the revised in-chat design for specification/ADR/vocabulary and scoped contract capture in this Pi conversation, 2026-10-08. The owner then approved this written revision with “approved” after the written-specification review request. The approved behavior is the separate single-dataset record path, corrected brake-suffix rule, Berlin clock, deterministic ordering, shared finite limits, all-or-nothing refusal and no staging on output refusal. Written approval opens preparation of a proposed implementation plan through the shaping handoff; it does not authorize implementation, feature tests/builds, project migration/admission, tickets, commits/pushes, deployment or publication. |
| **Execution map** | [Plan 0014, revision 1](../plans/2026-10-08-0014-bounded-record-queries-and-results.md). Owner requested “ticketize” in this Pi conversation, 2026-10-08, authorizing publication of its S1–S3 decomposition and canonical ownership transfer to GitHub issues only; execution authority remains pending. |
| **Scope** | A first-class ungoverned bounded record operation for known project datasets, plus shared row/cell/serialized-byte safeguards and execution deadlines for result-producing Query operations. |
| **Sources** | [Vocabulary](../../CONTEXT.md), [ADR-0019](../adr/0019-bounded-record-query-boundary.md), [own compiler](../adr/0008-own-sqlglot-compiler-agpl-exit.md), [source registry](../adr/0010-declarative-source-registry.md), [local runtime](2026-09-23-0001-local-artifact-runtime.md), [multi-fact contract](2026-09-30-0008-multi-fact-planner.md), [shared core](2026-10-02-0009-modular-core-git-authoring.md), [source-quality evidence](2026-10-06-0013-source-quality-evidence.md), [Query](../../src/ariadne/query.py), [Execution](../../src/ariadne/execution.py), [Planner](../../src/ariadne/planner.py), [MCP adapter](../../src/ariadne/serve.py). |
| **Contract** | planning-contract v1; installed shape-design/planning-contract provenance unknown. |

## 1. Purpose, evidence and exclusions

Retrieve a bounded set of records without inventing a metric, aggregating away event identity or forcing the existing legacy Trace Data project through migration or graph admission. Separately prevent query results from overwhelming the consuming UI or gateway without changing the calculation's input population.

Initial inspection used HEAD `f5dfca8bf2949c108c19697d92df97c763e57bec`. Before this capture, HEAD advanced to `77d57f32559684b4b8a2e63461822a0f701ec3aa`; the four inspected query/execution/planner/serve files are unchanged between those revisions. `query_detail` still accepts only dataset/fields and requires an admitted graph; aggregate ordering/limits do not extend detail projection. All four existing result-producing Query operations use `DuckDBExecution.fetch`, which calls `fetchall()`. `define_metric` executes, fetches and then stages. `DeadlineBudget` and connection interruption already exist for bounded mapping inspection, but are not wired into these query operations.

The locally available `dist/ariadneai-0.1.0-py3-none-any.whl` has SHA-256 `02da74c4c12721296c6e9a45d946608b4fdb5788af67e939abbcbcf939cb27db`; its execution/serve modules match the inspected HEAD. This does not identify it as the exact deployed wheel. Version `0.1.0` alone is not proof of identical code.

The owner's incident report describes an immediate `define_metric` over `trace_products.products`, using `MAX(genealogydata_assembleddatetime)` grouped by product number, material number, trace data and trace type. Description wording did not create SQL filters, ordering or a limit. Staging followed fetching at 23:14:35 UTC; the gateway rejected a later request at 23:18:03 with HTTP413, “Body buffer overflow” / “protocol.http.TooBigBody”. The reported **945,160,337 bytes is the saved conversation size**, not a measured individual tool response or gateway request. No large query or chat export is needed to establish the design requirement.

Open WebUI 0.11.4 already connects through native Streamable HTTP MCP Analyst tools and the SDC gateway's Responses API. Keep that connection unchanged; this is not a connectivity fix.

Non-goals: generic `execute_sql`, caller-selected filesystem paths/credentials/project roots, joins or unions in the new record operation, distinct-brake selection, metrics or staging merely to retrieve records, automatic admission/Promotion/migration, new execution engines/dependencies, a UI-side wrapper, larger gateway limits/timeouts as the primary remedy, pagination/export/result caches, exactly-once transport delivery, upstream data repair, S3 replay, loading the chat export, or publication. Existing Authoring/inspection payload contracts are not replaced by this Query design.

## 2. Approved Trace Data interpretation

Local-only evidence was read under `examples/trace-data/trace-data/`: `AGENTS.md`, `ariadne.yaml`, `data/seed_notes.md`, `data/docs/notes.txt`, the relevant served policies/table pages and OSI models. These files are private project dependencies, not portable tracked fixtures. Do not copy source locations, order lists, actual identifiers, rows or private snapshots into tracked artifacts. The historical `bremsencharge.py` was inspected as candidate analysis, never executed or treated as an approved oracle.

The owner clarified the following in this conversation:

| Question | Approved meaning |
| :--- | :--- |
| What is returned? | Trace-event rows from `trace_products.products`; the same motor may appear repeatedly. No motor/brake deduplication. |
| What counts as a brake? | The **raw `genealogydata_tracedata` value ends with `/2[0-9][0-9A-Z]$`**. The owner corrected the initially named material-number field to trace data and excluded a literal comma from the final character class. |
| What counts as traced? | Populated trace data. The served model uses non-null and `TRIM(value) <> ''`; the approved suffix predicate already implies presence and excludes null/empty/blank values. |
| Latest by what? | `genealogydata_assembleddatetime`, documented as VARCHAR `YYYY-MM-DD HH:MM:SS`, interpreted in **Europe/Berlin** and ordered by actual instant. |
| Which sources? | Products events only. Batch-only `trace_orders.orders` events are outside this question. |

This direct suffix rule **replaces the intermediate SAP-classifier choice**. No SAP lookup, semi-join or existence predicate is part of revision 1. The notes say K519 means brake or encoder, and raw SAP relationships are many-to-many; neither K519 alone nor notebook substrings become an alternative brake definition.

`productnumber` identifies the motor, not a unique event. No unique physical event key was established. The existing `traced_motor` semantic dataset groups by motor serial and is not an event-projection substitute. The EOL latest-measurement rule is unrelated to assembly-time event ordering. The suffix interpretation is the owner-approved scope of this question, not proof of required-component completeness, a globally unique brake serial or a governed metric definition. Capturing it here does not admit or edit the legacy project.

## 3. Separate record operation

Add transport-neutral `QueryRuntime.query_records(request)`, local `ariadne query-records` with the existing JSON request/legacy-root conventions, and the same tool on Analyst and Combined MCP. Core imports remain independent of MCP.

Alternatives considered: extending admitted `query_detail` alone cannot serve the legacy request; giving detail a second ungoverned mode mixes graph-backed field traversal with catalog-backed physical projection. A separate operation preserves the current detail gate and makes the ungoverned route explicit. No extension of detail filtering/ordering is required by this work.

The record operation selects from exactly one already-known catalog dataset/view. A unique existing dataset name is accepted; use the existing canonical `resource` identity when a display name is ambiguous. Resolve identifiers to the built catalog, never splice caller text into a FROM clause or open a new source. On managed projects retain pinned admission and approved-source construction/rechecks; missing managed admission must not trigger a legacy fallback. On the existing legacy route, record querying requires no graph admission and creates no new source approval.

### Request contract

The example below is normative for the owner-approved Trace Data interpretation, but describes a **future API**, not a command supported by the inspected wheel:

```json
{
  "dataset": "trace_products.products",
  "fields": [
    "productnumber",
    "genealogydata_materialnumber",
    "genealogydata_tracedata",
    "genealogydata_genealogytracetype",
    "genealogydata_assembleddatetime"
  ],
  "filters": [
    {
      "field": "genealogydata_tracedata",
      "op": "regex",
      "value": "/2[0-9][0-9A-Z]$"
    },
    {
      "field": "genealogydata_assembleddatetime",
      "op": "is_not_null"
    }
  ],
  "timestamp": {
    "field": "genealogydata_assembleddatetime",
    "format": "%Y-%m-%d %H:%M:%S",
    "timezone": "Europe/Berlin"
  },
  "order": [
    {"field": "genealogydata_assembleddatetime", "direction": "desc"}
  ],
  "limit": 10
}
```

- `dataset`: one exact known dataset/resource. `fields`: a nonempty list of known physical column names, with duplicates removed preserving first occurrence. No `*`, expressions or traversal to another dataset. Selected columns need not include every filter/order column.
- `filters`: optional AND-combined predicates. Reuse existing comparison/IN parsing and AST literal construction for `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`; add explicit `is_null`/`is_not_null` tests without a value and a bounded `regex` string predicate. Comparison/IN/regex predicates require a value. Reject mistyped values, non-finite numeric parameters, unsupported operators, null comparisons that should use a null test, invalid regex and unknown request keys before result execution. Retain the existing 100-value IN and 4,096-character parameter ceilings for new string/regex values. Regex uses DuckDB's supported semantics, is case-sensitive unless explicitly specified by its supported pattern syntax, and remains a literal, never SQL text.
- `timestamp`: optional typed normalization for one identified temporal field; mandatory when this request orders the documented VARCHAR as time. Revision 1 supports the documented `%Y-%m-%d %H:%M:%S` text encoding, not arbitrary parsing SQL or a conversion DSL. Validate the declared type, format and IANA timezone. Do not order this text lexically or silently infer UTC. Native temporal values retain their type; actual-instant claims for naive clocks require an explicit clock rather than an invented one.
- `order`: required, nonempty known-column entries with `asc`/`desc` (default `asc`). Apply explicit `NULLS LAST`. Ordering on the declared timestamp uses its normalized instant; return the original selected value and disclose the interpretation in the plan.
- `limit`: optional, default **10**, positive integer, maximum **1,000** and no greater than the effective host row ceiling. Booleans are not integers for this contract. No raw SQL, offset or unbounded mode.

Non-temporal eligibility filters precede timestamp interpretation. A malformed non-null timestamp on an eligible row causes refusal, even if it might otherwise fall below the top-N boundary; an ineligible row must not poison the query. Null timestamps remain null. The example explicitly excludes them; a generic request without that filter can include them last. Never silently discard malformed times through `TRY_CAST` and claim a complete latest result.

Normalize valid Berlin wall times to instants. Ambiguous fall-back or nonexistent spring-forward wall times cause an explicit refusal, not an implicit fold/offset choice. No offset/fold recovery capability is added in this revision. Timestamp interpretation must have the required backend/timezone support; absence is a refusal, not a fallback clock.

After requested order keys, append remaining selected sortable scalar columns in field-list order, ascending with NULLS LAST. This gives deterministic visible ordering for the same request and fixed source snapshot without claiming a unique event key. Fully identical projections remain repeated, indistinguishable records. Do not use scan order, a manufactured row ID or a hash claimed as event identity. Different projections can change tie selection; no projection-independent physical event identity is promised. Disclose the effective tie order.

Compile the request through the existing SQLGlot compiler ownership, then the single-statement guard and EXPLAIN bind before guarded execution. Reuse shared parsers/guards; no independent compiler, generic SQL tool or input-row metric limit is introduced.

### Governance and provenance

Return dataset/resource, selected fields, applied filters/order/timestamp interpretation, rows, compiled SQL and bounded plan/provenance. SQL and plan distinguish the logical top-N selection from execution-only overflow/lookahead guards; identify the actual compiled execution statement rather than claiming unexecuted SQL produced the result.

Every Ad-hoc Record Query reports `governed: false`, even on an admitted managed source. Source/artifact admission is a separate provenance fact, not admission of this requested record definition. Legacy host configuration must not be called Git Review Admission or a reviewed graph. Identify the artifact revision/digest when available, the actual route, and source snapshot identity only when established; otherwise disclose unversioned/as-of data. A schema observation or fixed artifact revision is not proof of unchanged live S3 data or independently verified values. Do not fabricate metric context or value attestation for records.

A fitting top-N response carries `result.status: complete`, `result.complete: true`, `result.scope: requested_top_n`, `requested_limit`, `returned_rows` and `has_more_matching`. Complete means **the requested top-N**, not the full matching population or upstream source completeness. Obtain the boolean lookahead within the same execution using at most one additional existence indicator, not a full COUNT or a second mutable-source query. The extra row must not transfer raw payload cells, and an oversized cell only on that extra row must not refuse an otherwise fitting top-N answer.

## 4. Shared output limits and ownership

Apply the safeguards to `get_metric`, `define_metric`, `query_metrics`, `query_detail` and `query_records`, through Execution and shared Query response assembly rather than per-tool patches.

| Bound | Built-in ceiling |
| :--- | ---: |
| Returned result rows | 1,000 |
| Complete serialized core response | 65,536 bytes (64 KiB) |
| One serialized result cell | 16,384 bytes (16 KiB) |
| Complete serialized MCP tool-result envelope | 131,072 bytes (128 KiB) |
| Shared execution deadline | 20 seconds |

Use the existing operator-owned ceiling convention in host-managed configuration; the implementation plan owns its exact serialization keys. Optional overrides can only tighten finite positive ceilings. Row/byte ceilings are integers; reject booleans, zero, negatives, NaN/inf and attempted increases. Models cannot change host configuration or raise ceilings. A requested logical top-N is distinct from the safety budget.

The limits cover the complete representation: rows, column names, SQL, echoed definitions, context/Policy bodies, admission, quality/lifecycle metadata, plan and staging receipt. Preserve established fitting scalar formats, including ISO temporal values and precision-preserving decimal handling. Exact byte accounting is UTF-8 after the actual serializer's escaping, not string length or an estimate of raw cell sizes. The MCP preflight counts the SDK's escaped text and any duplicate structured content, not just its inner dict. Transport framing is accounted for before dispatch; these defaults are not a claim about the SDC gateway's unknown request threshold or accumulated conversation size.

### Before unrestricted collection or serialization

1. **Compiler/Execution:** place a compiler-built output guard outside the completed logical aggregate/window/record query. Collect at most the row ceiling plus an overflow indicator using bounded cursor reads, never `fetchall()` followed by slicing. A caller's existing metric limit remains a logical post-aggregate limit; no new input limit is added to fact branches, source SQL or window lookback.
2. **Execution:** inspect output types and guard variable-size cells inside DuckDB before Python transfer. Oversized strings/blobs become internal overflow markers, not enormous Python values. Bounded raw values may then be encoded for exact cell-byte checking. A cell's serialized form can exceed its raw size because of escaping.
3. **Type boundary:** initially refuse nested/complex or other output types whose size cannot be bounded before transfer; do not materialize or stringify an unrestricted list/struct/blob to discover its size. This explicitly changes previously unbounded output behavior. No new binary/nested serialization feature is required.
4. **Query/encoding:** preflight non-row metadata early where possible, collect only bounded values, and account for the full success envelope incrementally. Never build the full unrestricted JSON or use whole-result `to_json` merely to count it. Required Policies and provenance are not silently omitted to make an answer fit.
5. **Adapter:** preflight the actual selected response representation before sending it. Query must coordinate that preflight before any ad-hoc staging; passing only the core budget is insufficient if the MCP envelope would overflow. An internal adapter/preflight seam may supply the representation without importing MCP into the core or exposing a model-controlled codec/budget.

These are external result-materialization/response bounds, not a promise to cap DuckDB's internal working memory or scanned S3 bytes. ORDER BY, aggregation, parsing and a small LIMIT can still scan or sort substantial input. Execution cost is controlled separately below.

## 5. Refusal, completeness, staging and retries

Choose **all-or-nothing refusal**, not automatic truncation. Row, cell, byte or unsupported-output-type refusal returns no result rows, `complete: false`, a stable code, the exhausted bound and small narrowing guidance. No clipped cell, omitted Policy or prefix can be presented as a complete answer. Use observed counts/lower bounds only; stop counting rather than scanning or serializing the rejected remainder to produce an exact total.

Codes include `result_row_limit`, `result_byte_limit`, `result_cell_limit`, `result_type_unsupported` and `execution_deadline`. Malformed/ambiguous timestamp interpretation has its own stable refusal code and identifies the field/interpretation without dumping the source value. Existing fitting compiler/binder/admission errors retain their established codes/messages; an oversized error representation is replaced with a bounded explicit refusal, not an unrestricted exception dump. All refusal representations must fit their effective response bounds; reject unusably small host budgets before an operation rather than exceeding them with the refusal itself.

A response excerpt, not a complete envelope:

```json
{
  "error": {"code": "result_row_limit", "message": "Narrow the result grouping or population."},
  "result": {"status": "refused", "complete": false, "returned_rows": 0},
  "rows": [],
  "staging_status": "not_staged"
}
```

For fitting existing metric/detail calls, additive completeness metadata identifies `scope: requested_query`. It describes the caller's full logical request, including any explicit post-aggregate limit, not all source rows. Existing admission/governance/attestation and full required caveats remain unchanged. Advisory quality/lifecycle warnings never trigger a semantic refusal; their serialized content participates in the same output budget as every other part of the response.

`define_metric` keeps immediate execution, but success becomes compile → bind/audit → bounded execution/collection → **full core and selected-transport success preflight** → stage → return. Reserve/include the complete bounded staging receipt before the write. Output refusal after successful computation, including MCP-envelope refusal, stages **nothing**. Report computation completion only when observed; stopping collection early is not proof of a completed backend query. No accepted result or Proposal is cached for a refused output.

A narrower retry is a new execution and can observe newer mutable data. Successful calls keep collision-safe non-overwriting staging; identical successful repeats can create suffixed candidates as today. A network failure after successful staging is not an output-budget refusal and can leave the staged proposal despite lost delivery. Do not automatically retry or promise exactly-once delivery. Existing staging I/O failure/non-transactional behavior is not redesigned here.

CLI preserves one JSON success on stdout or one bounded JSON refusal on stderr with nonzero exit. MCP reports a tool error with the structured refusal, not a successful partial tool answer. Native adapters preserve the same bounded core result/error semantics without discarding caveats. Users/models are told to narrow the request or selected fields, not increase a gateway limit or guess an answer from retained fragments.

## 6. Execution deadline and small diagnostics

Reuse `DeadlineBudget`, the shared source builder's deadline support and owned-connection interruption, not another timeout engine. One remaining-seconds budget covers source setup when construction occurs in the request, bind, existing live grain/relationship audits and execution/collection. Early metadata checks and completion/preflight must check exhaustion before staging. Eager source setup also needs the bounded setup mechanism; runtime construction must not open an unbounded source before the guard starts.

Reuse connections where already owned; no connection pool or new concurrency model is required. Interrupt only the operation's owned execution, stop/release the cursor on refusal and clean up watchdogs. A backend without cancellable execution refuses explicitly. Do not return a successful complete result after the budget is exhausted, claim a still-running read stopped, or run remaining audits after cancellation. The execution budget is not a guarantee of end-to-end gateway/network or staging-I/O latency.

Record only phase timings, observed row/byte counts, complete/refused/deadline outcome, exhausted bound and staging status. Unknown scan bytes or completion remain unknown; do not infer scan cost from returned rows. Diagnostics contain no raw results, barcodes, credentials, full SQL/definitions or conversation exports. Bounded SQL in the answer is provenance, not permission to log it indiscriminately.

## 7. Observable acceptance and validation obligations

Use small synthetic fixtures with independently specified values. No production S3 request, private result CSV, notebook execution or gigabyte chat load is part of acceptance setup. Labels below are fixture identities, not a claim that the real source has an event key.

### V1 — records (`new-test`)

A synthetic `fixture.events` uses the real request's five column roles. All non-null assembly strings below are on **2026-01-15**, in Berlin. Trace type is 2 throughout; fixture material strings are MAT-B for e1/e2/e4–e8 and MAT-C for e3.

| Label | Synthetic motor | Synthetic trace data | Assembly time |
| :--- | :--- | :--- | :--- |
| e1 | motor-A | synthetic-A/253 | 09:00:00 |
| e2 | motor-A | synthetic-B/25A | 11:00:00 |
| e3 | motor-B | synthetic-C/259 | 11:00:00 |
| e4 | motor-C | null | 12:00:00 |
| e5 | motor-D | synthetic-X/25, | 13:00:00 |
| e6 | motor-E | empty string | 14:00:00 |
| e7 | motor-F | synthetic-F/251 | null |
| e8 | motor-G | spaces only | 14:00:00 |

1. The approved suffix plus non-null timestamp request with N=2 returns exactly e2, e3 and `has_more_matching: true`. N=3 returns e2, e3, e1; the repeated motor-A is retained. N=10 returns those three rows with no more matches. All fitting answers are complete only for their requested top-N and `governed: false`.
2. An additional equality filter for motor-A returns e2, e1. A timestamp comparison uses the declared temporal interpretation, not the source string's lexical value. Removing the explicit timestamp null test includes e7 last. Reordering fixture insertion does not change visible ties; identical projections remain repeated rather than silently deduplicated.
3. Suffix controls independently accept `/253` and `/25A` and reject `/25,`, `/25a`, `/2530`, trailing whitespace and null/empty/blank values. Match trace data, not material number; no implicit trace-type or SAP filter is added.
4. Berlin `2026-01-15 11:00:00` normalizes to `10:00 UTC`; `2026-07-15 11:00:00` normalizes to `09:00 UTC`. Eligible malformed times, ambiguous `2026-10-25 02:30:00` and nonexistent `2026-03-29 02:30:00` refuse with no rows. A malformed time on a suffix-ineligible row does not poison the result.
5. Unknown/ambiguous datasets, unknown fields, SQL-shaped identifiers, unknown request keys, invalid regex, wrong types/timezone/encoding and excessive limits refuse before result execution. Legacy products events work without a graph admission or any staging write. Missing managed admission still refuses; existing unadmitted `query_detail` still refuses.

### V2 — collection/output (`new-test`)

Use lowered test ceilings, not large payloads. Parameterized cases may share one public-seam fixture; expectations come from this contract, never compiler output.

6. With a test row ceiling of two, three aggregate groups refuse with zero returned rows and an observed lower bound, without `fetchall()` or draining the source. Inputs 10, 20, 30 still yield a fitting single-row SUM **60**, never 30 from an input LIMIT. Existing window lookback and post-aggregate limits remain correct.
7. A 17-byte serialized cell exceeds a lowered 16-byte cell ceiling. Oversized cell markers, not the original value, cross the execution/Python boundary. Small Unicode/JSON-escaping cases catch differences between character counts and serialized bytes. A nested unsupported column refuses before raw materialization. An oversized cell exclusively on the top-N lookahead row does not refuse the selected fitting rows.
8. A response's rows can fit while required context, SQL, definition or provenance exceeds its lowered total byte ceiling; refuse rather than dropping content. MCP text/structured duplication or escaping can exceed its lowered envelope ceiling even when the core dict fits; check the actual representation before dispatch. Refusal/error payloads are bounded too.

### V3 — deadlines and staging (`new-test`, existing deadline checks reused)

9. Output-row, cell, core-byte and MCP-byte refusal after computation leaves no ad-hoc model or draft page. A fitting narrowed retry executes anew and stages normally. Successful name collisions still never overwrite an earlier proposal. No automatic retry follows a lost response.
10. Controlled-clock/interrupt checks exhaust the same budget during setup, bind/audit or collection. Interrupted/uncancellable execution produces no complete answer or staged proposal, leaves no continuing owned read/watchdog and does not claim measured scan costs. A new invocation does not inherit an old watchdog's cancellation.

### V4 — preserved contracts and discovery (`new-test`, existing compatibility/smoke checks reused)

11. Preserve existing golden values, grain/fan-out guards, graph admission/staleness refusals, full Policy/lifecycle/quality disclosure and CLI/MCP/native parity on fitting queries. Source-quality warning state does not change arithmetic or cause quality-based refusal.
12. Analyst/Combined MCP discover the explicit record request schema, supported filter/timestamp/order/limit contract, defaults, ungoverned status and overflow policy. Authoring gains no query tools; no surface gains approval, arbitrary filesystem or SQL execution. Existing native Ariadne Agent tool permissions do not expand automatically.
13. A small installed-candidate CLI and Streamable HTTP MCP smoke performs the synthetic latest-N request and a deliberate overflow followed by a bounded retry. A genuine Open WebUI/model smoke verifies routing and final completeness/governance disclosure separately; unavailable provider/UI evidence is unverified, not a synthetic passing live run. No unbounded real-domain replay is required.

This capture has an **existing-check** obligation: inspect source status, relative links, JSON example and documentation diff. No executable tests, runtime verification, live smoke or security exploit were run by capturing this design. Implementation validation requires separately approved planning/execution and the obligations above.

## 8. Compatibility and downstream surfaces

The new record API is additive; `query_detail` stays an admitted, safe root-grain projection. Existing metric calculations, filters, windows, live audits and admission rules do not change. Large previously returned responses now refuse; complex unbounded types and oversized error/context representations also refuse. Existing `query_metrics` logical limit parsing (currently up to 10,000) is not silently narrowed into an input cap: a logical request can be valid while its actual output exceeds the new safety ceiling.

Required downstream reconciliation:

- Query/Execution/shared compiler/response seams and the local CLI, preserving optional MCP and aliases. Profiling/validation/mapping inspection retain their own operation contracts; do not cap their inputs merely because they share Execution.
- Analyst/Combined MCP tool registration, explicit nested input schemas and bounded structured errors. Descriptions must distinguish record selection from aggregation and never imply description prose becomes WHERE/ORDER/LIMIT.
- Packaged local skill, generated guidance templates, applicable native Analyst descriptions/error handling and exact toolset/schema tests. Do not automatically add `query_records` to the separate native Agent's fixed permission set. Record requests in an unsupported host must be reported unsupported, not converted into metric aggregation.
- Existing legacy project guidance needs an explicit owner-reviewed update to stop routing all unmodeled record questions through `define_metric`. Do not silently rewrite/publish the supplied project's skill or admitted pages; its historical instructions do not waive the new operation's ungoverned disclosure.
- Open WebUI allowlists/preset routing instructions if configured; no repository-owned Open WebUI preset was found during inspection. No endpoint, Responses API base URL, bearer gate, gateway body limit or HTTP transport redesign is required.
- Installed candidate wheel/schema/packaged-skill parity checks, then an identifiable release under [ADR-0018](../adr/0018-distribution-naming-ariadneai.md) if separately authorized. Core distribution is `ariadneai`; imports remain `ariadne`. Do not replace an old wheel and call matching `0.1.0` version text proof of rollout. Publication/build/release authorization is absent here.

This specification narrowly amends the older contracts' unbounded successful-result behavior and success-before-staging interpretation. It adds a non-metric record operation, not a multi-fact ad-hoc metric route. Local-first operation, compiler ownership, context ownership, source approval, human-only admission, the existing graph gate and independently verified versus admitted distinctions remain binding. Existing plans/tickets do not acquire this behavior automatically and require separately approved decomposition/reconciliation.

## 9. Separate containment status

The reported old-wheel defect allowing `define_metric` SELECT sources to read mounted secret files is **not repaired by output caps**. Static inspection at the recorded HEAD finds the Authoring `_authorize_dataset_sources` guard but no call to it from Query's ad-hoc path; render's single-statement guard and read-only attaches are not a source-access allowlist. The deployed mount/environment and exploit were not reverified. Flag this as a separate unresolved containment work item before treating an updated wheel as safe for less-trusted Analyst input; no remediation or ticket creation is authorized by this specification.

The new record operation must not introduce that boundary: dataset/field identities come only from the existing catalog, no file scans/table-function arguments or supplied source SQL. That constraint is part of this operation, not a claim that the legacy metric path is contained.

## 10. Capture checkpoint and handoff

- **Vocabulary:** Ad-hoc Record Query is captured in [CONTEXT.md](../../CONTEXT.md), distinct from an Ad-hoc Metric and its Proposal. Domain-specific brake suffix/clock/event scope are recorded in §2 with owner provenance, not inferred from samples or silently admitted to the private project.
- **Decisions:** [ADR-0019](../adr/0019-bounded-record-query-boundary.md) records the separate query/admission boundary and complete-output success requirement, based on the real alternatives. Existing ADR/spec amendment notices reconcile only this scope; no new connector, compiler, UI service or admission route is introduced.
- **Behavior:** the final in-chat design, including unchanged shared safeguard defaults and the owner's corrected trace-data suffix/Berlin clock, was approved for capture. This written revision's concrete interface, failures, compatibility and independently specified acceptance examples are now owner-approved. The owner subsequently requested ticketization of the linked plan's revision-1 S1–S3 decomposition; this authorizes those three task publications, not execution.
- **Uncertainty:** no material domain decision remains open. Backend pre-transfer size guards, actual codec preflight and timestamp/DST support need implementation planning and prerequisite verification; their absence cannot justify unbounded fetches, post-staging refusal, guessed clocks or new dependencies. Real-source availability, a reproducible source snapshot, deployed wheel identity and genuine live-client evidence remain unverified. They do not authorize opening S3 under this capture.

Planning-contract v1; installed provenance unknown. The owner authorized S1–S3 ticket publication and canonical task ownership transfer; stop at the execution gate. No implementation, executable feature tests, additional tickets, private-project edits/admission, wheel build, integration, commit/push or release/deployment publication is authorized.
