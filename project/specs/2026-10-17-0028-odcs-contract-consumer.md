# Specification: ODCS contract consumer and source comparison

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2 — retain list_datasets' existing live-catalog semantics.** |
| **Approval** | Owner, Pi conversation 2026-10-17: selected v3.2.0-only with an immutable official schema pin, strict unpatched schema validation, a Core validator dependency, SQL-quality evaluation, separate local Git bindings, single-dataset SQL, mandatory live evidence for admission, DuckDB-only SQL and the small field-check profile. Then selected “Design freigeben (Recommended)” for the complete design including the evidence limits and admission behavior. Subsequently selected “Schriftliche Fassung freigeben (Recommended)”, approving this written revision 1, ADR-0025, the glossary additions and spec 0027's scoped notice for implementation planning. Planning inspection then established that `list_datasets` already opens the approved live catalog, unlike `discover`. The owner selected “Live-Katalog erhalten (Recommended)”, explicitly approving revision 2: offline contract discovery, but unchanged live-catalog behavior with snapshot-only contract annotations and no additional reads in `list_datasets`. No implementation, installation, integration or publication was authorized. |
| **Intake** | [#75](https://github.com/legout/ariadne/issues/75). Shared cross-layer identity/provider integration remains [#76](https://github.com/legout/ariadne/issues/76), not an interface selected here. |
| **Baseline** | Main `84004210cce4e3efcc2a9ccc73067e05aa8018f1`; Core and Agent 0.4.1. [Spec 0027](2026-10-16-0027-core-git-only-authoring.md) owns Git-only persistence and human admission. |
| **Evidence / decision** | [Pinned ODCS research](../research/2026-10-16-odcs-consumer-standard-baseline.md), [ADR-0025](../adr/0025-odcs-producer-contracts-and-local-bindings.md), [CONTEXT.md](../../CONTEXT.md). |
| **Contract** | planning-contract v1; exact installed skill provenance unknown. |

**Later integration design (owner, 2026-10-18):** [spec 0029](2026-10-18-0029-lumio-bound-governed-releases.md) binds these native ODCS/OSI/evidence identities to an exact Lumio knowledge snapshot through an opted-in overall admission. It does not change this specification's ODCS pin, limited consumer profile, source permissions, original-time evidence or standalone behavior. Revision 1 remains the full target. The owner-approved 2026-10-19 local MVP design is captured in spec0029 r2 (written r2 approved; separate M1 execution authority is scoped in plan0029 r8): its joint fixture still includes an actual ODCS contract/binding; integrated live `list_datasets` is explicitly unavailable until later support, not silently redefined as an offline result. Standalone `list_datasets` retains this specification's live-catalog behavior. No implementation or publication is authorized here.

## 1. Scope and authority

Consume producer-authored ODCS documents as Git-native expected state. Compare their supported requirements with explicitly bound, operator-approved physical datasets, and expose scoped observations rather than rewriting the contract from source statistics. OSI retains calculation, grain and join authority; explanatory human knowledge and business Policies remain outside the contract evaluator. No ODCS relationship or narrative authorizes a join, a calculation, a Source Approval or human admission.

This is an explicit, limited Ariadne consumer profile, not full ODCS behavioral interoperability. Document validity, binding validity, supported evaluation, observed results and human admission are separate facts. A successful observation means the stated profile requirements passed at the reported scope and time, not that every ODCS commitment was evaluated or that live data remains compliant.

Excluded: contract generation/import from observations, producer-document normalization, automatic model or Policy generation, native SQL engines other than DuckDB, multiple-dataset/join quality queries, variable services, external-reference fetching, third-party quality engines, schedulers, continuous monitoring, shared #76 IDs/provider/manifests, production data access, real-project initialization, releases and deployment. Native DuckDB backing access retains the trusted-source boundary of [ADR-0022](../adr/0022-trusted-native-duckdb-catalogs.md); read-only attachment is not a sandbox.

## 2. Exact ODCS version and document validation

Support only `apiVersion: v3.2.0` and `kind: DataContract`. Preserve the producer's contract `id`, `version`, ownership/team and all schema-valid metadata independently of Git revision and source observations. Missing optional ownership is reported as undeclared, not inferred from a source alias, Git author or filename. The producer version is not the ODCS version; do not impose an additional SemVer requirement.

Vendor the unmodified official `schema/odcs-json-schema-v3.2.0.json` from commit `f0bdad95346905d500be5ef4b2c2d9b1d95223b7`, Git blob `f934075459fce0a20a3c8260dd2076872f91e2b9`, SHA-256 `edb41f33ec46e84780e99872ab2bd67f074959d2bf3e9c9fc54e61f8982b0d93` (110505 bytes). Include the applicable upstream attribution/license with the packaged resource. Schema updates are explicit reviewed changes, never downloads at validation time or rolling filenames.

Use `jsonschema>=4.18` as a Core dependency with Draft 2019-09 support; the repository lock records the resolved dependency. Local CLI and optional MCP use the same packaged schema and structural Draft 2019-09 assertions. JSON Schema `format` remains an annotation; optional, environment-dependent format checkers must not silently change document validity. Required native reference/binding semantics are checked separately. No remote schema retrieval or document-provided schema replacement is permitted. Source-free validation needs no network, credentials, Source Approval or live database.

Contract files contain one UTF-8 YAML document representing a JSON-compatible object; reject ambiguous duplicate mapping keys and non-JSON values rather than silently choosing an interpretation. Report errors with artifact and instance path. Explicit version dispatch rejects other `apiVersion` labels even though the pinned schema accepts some older labels. A valid four-field, schema-less ODCS document remains document-valid; it supplies no dataset binding or data-conformance evidence.

Follow the pin's actual validation: the documentation's combined `mustBeGreaterThan` plus `mustBeLessThan` example fails its `oneOf`. Do not patch the schema, rewrite operators or insert defaults into producer bytes. Explain the discrepancy and retain its diagnostic. Document/profile validity must not be conflated: a schema-valid feature outside this evaluator remains valid ODCS but is explicitly unsupported for evaluation.

## 3. Git artifacts and local bindings

Add only `contracts/*.yaml` / `contracts/*.yml` and the fixed `contract_bindings.yaml` to the existing authored artifact/snapshot grammar. Native typed artifact operations gain contract and contract-bindings identities, not arbitrary file paths or a general file editor. Read/edit, inherited-candidate validation, finalization inventory, review, snapshot digest and admission cover both kinds. Untracked files, traversal, symlinks and stale/foreign revisions retain existing refusals. Contract documents do not enter OKF navigation as human Policies.

The producer contract and consumer binding are separate files. No automatic identifier injection, inferred constraints, missing-ID repair or observed-state rewrite is allowed. Explicitly requested ordinary authoring edits remain reviewable Git changes; loading or validation changes no producer document. Operational reports extend existing `.ariadne/validation/` evidence, not a second contract draft store.

The native binding document has `version: 1` and a `bindings` list. Each binding declares:

- `id`: a unique local binding identifier, not a #76 or Lumio namespace;
- `contract_id`, `contract_version`, `object_id`: exact producer identifiers;
- `asset`: the existing exact `{source, catalog, schema, table}` catalog selector, with native null-catalog semantics;
- `model`, `dataset`: existing native OSI model and dataset identifiers, resolved without fuzzy matching;
- `properties`: a mapping of producer property IDs to exact physical column names;
- `server_id`: the producer's server ID, required when SQL-quality rules apply.

Unknown binding fields, duplicate binding IDs and conflicting bindings for one OSI dataset are errors. Resolve a contract by its exact `(id, version)` pair; duplicate documents for that pair are ambiguous, while different producer versions can coexist with explicit selection. IDs remain scoped within their containing contract/object/array. Enforce the standard's applicable uniqueness and internal reference-resolution rules beyond JSON Schema; dangling internal references fail visibly. Missing optional ODCS IDs do not invalidate the standard document, but an attempted stable binding without the needed IDs is unsupported. Never derive them from names or paths.

All physical properties of the bound object must be identified and mapped; omitting a property or rule is not a way to remove an unsupported requirement. The binding must agree with the selected OSI dataset's actual physical source and column identities, not merely point at an existing unrelated table. A derived source whose relationship cannot be established by the native resolver is unsupported, not guessed equivalent. A declared contract `physicalName` must agree with its mapped physical identity; a binding cannot silently overwrite a producer's expected physical name. Missing tables/columns found during observation are drift, not a reason to redirect the binding. Additional observed columns are informational unless the contract asserts a supported restriction on them.

These are repository-local native references. They do not define portable OSI/Lumio IDs, a cross-component release manifest or #76 admission semantics. Lumio concept links remain explicit producer metadata with no wiki-service dependency and no automatic entity resolution.

## 4. Supported source comparison

Read only the explicitly bound datasets through the existing Source Approval, approved resolved registry and frozen effective Storage Binding. Contract `servers`, URLs, variable tokens, descriptions and binding files cannot create a source, replace its approved endpoint, supply credentials or widen S3 scopes. Do not use the whole-registry profiler to scan unrelated tables. Source-free static checking must not create a connection.

### Field profile

For flat physical properties, compare presence and declared scalar logical types with an explicit mapping, not `profiler.types_compatible` (which owns identifier comparability):

| ODCS logical type | Supported observed scalar family |
| :--- | :--- |
| `string` | character/string types, not binary or automatic casts |
| `integer` | signed/unsigned integer types, not floating-point or decimal coercion |
| `number` | integer, decimal and floating-point numeric types, not booleans |
| `boolean` | boolean |
| `date` | date |
| `time` | time, with the observed variant retained |
| `timestamp` | timestamp, with precision/time-zone variant retained |

Unknown or lossy/unavailable type metadata is not proof of compatibility. A known incompatible type is drift. Retain observed native versus execution/inferred type provenance. A declared `physicalType` passes only when its original type is reliably observable, with recognized source-dialect aliases normalized without dropping width, precision, scale or time-zone distinctions; a known mismatch is drift, otherwise unsupported. Never confirm original physical types from a lossy DuckDB adapter projection.

`required: true` means no observed NULLs over the entire bound dataset; a sample cannot satisfy it. Absent type declarations impose no invented type constraint. The containing schema object's ordinary `logicalType: object` is its tabular container, not a nested-property claim.

Assertions of `unique`, `primaryKey`, `enum`, nested collection/object types, executable transformations or additional nonempty `logicalTypeOptions` are unsupported in this slice. False key flags impose no requirement. Display such limitations per property; do not silently ignore them or infer fulfillment from a different SQL rule. Document formatting, examples and narrative do not become measured constraints.

## 5. SQL-quality profile

Evaluate applicable object/property `type: sql` rules only when the binding selects an unambiguous ODCS server ID of type `duckdb` and a matching approved native DuckDB source. Other/unknown dialects are unsupported, never implicitly transpiled. The declared server's address is not a connection instruction; only the approved native identity is opened.

A rule is one SELECT over the selected dataset, producing exactly one row and one finite numeric or boolean value. No joins, other datasets, mutation, multiple statements, external table functions, environment/secret access or custom engine code. Validate the entire nested SQL tree with the existing reviewed function/relation authority before bind or execution; permitted relation scope is narrowed to the selected asset. Read-only alone is insufficient. Quality execution is a validator capability, not a general Analyst raw-SQL operation and not a governed metric.

Support the pinned SQL documentation's fixed `{object}` and, for property rules, `{property}` identifier placeholders through their exact checked binding. They cannot expand into expressions, paths or arbitrary text. Literal relation references must resolve unambiguously to the same selected asset, without ambient search-path fallback. General `${...}` variables and other unresolved placeholders needed for evaluation are unsupported. Never consult environment values, run a template engine or rewrite producer bytes.

Support the pin's individual comparison operators: `mustBe`, `mustNotBe`, `mustBeGreaterThan`, `mustBeGreaterOrEqualTo`, `mustBeLessThan`, `mustBeLessOrEqualTo`, `mustBeBetween`, `mustNotBeBetween`. Numeric comparisons preserve precision, with no bool/integer conflation, string-to-number coercion or invented tolerance. Boolean results support same-type equality/inequality. Other schema-valid operand shapes are unsupported. NULL, nonfinite values and wrong result cardinality/type are evaluation errors, not false-positive comparisons.

The [quality documentation at the pinned commit](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/docs/data-quality.md) explicitly equates `mustBeBetween: [a, b]` with `> a` and `< b`: this profile uses open endpoints, and the complement for `mustNotBeBetween`. Require increasing bounds rather than sorting or repairing them. This behavior must be documented and boundary-tested, not inferred from SQL's inclusive BETWEEN operator.

Library, text and custom quality rules are preserved but unsupported. All applicable declared schema/quality requirements of a bound object participate: no selection flag, arbitrary `severity` value or unsupported-engine declaration can silently drop a failing/unevaluated requirement. Narrative/team/pricing/context metadata is outside the measured schema/quality profile, not an evaluated commitment. ODCS context instructions are never merged into prompts or native Policies; verified statements never replace fresh numerical execution. Scheduling metadata creates no job.

External reference values are retained without fetching. A reference needed to evaluate a bound requirement is unsupported and blocks proof; an explanatory link is just metadata. Unknown vendor `customProperties` stay intact and confer no execution or identity authority.

## 6. Outcomes, bounded evidence and admission

Report separate document, binding and evaluation results. Each evaluated requirement has one of:

| Outcome | Meaning |
| :--- | :--- |
| `passed` | Its supported check completed and satisfied the expectation at its reported scope/time. |
| `drift` | Observed missing dataset/column, incompatible type, NULL violation or false quality comparison. |
| `unavailable` | The permitted source/observation could not be obtained, including exhausted execution budget. |
| `unsupported` | Valid declaration or required resolution outside this profile; no conformance claim. |
| `refused` | Missing Source Approval or an execution-authority violation; no unauthorized read. |
| `error` | Evaluation could not produce a valid comparable result. |
| `not_run` | Static-only invocation or a prerequisite prevented the check. |

Do not relabel schema errors as source drift. Diagnostics identify the contract ID/version, local binding, object/property/rule ID or exact document pointer, expected versus observed value/type, and actionable reason. Do not leak credential values or raw sample rows. Known literal credential payloads remain subject to the existing authoring credential refusal; a valid schema is not permission to persist secrets. No code path reads credentials from contract metadata.

Use the host operator's existing `inspection` ceilings, explicitly extending their application from mapping inspection to contract inspection: at most 20 execution seconds total across a validation's contract checks, 64 KiB serialized contract-response content, and 24 hours retained-evidence age; the operator may only tighten them. Candidate edits cannot raise limits or permissions. These are not per-rule fresh budgets. A sampled scan or incomplete/budget-exhausted response never becomes a successful full-scope report. Completed subchecks may be retained with their actual scope; remaining checks are explicitly incomplete.

Extend the existing Core-owned validation evidence with contract observations binding:

- the final effective Candidate Revision and contract/binding digests;
- producer identity/version, exact asset/column/OSI selectors and evaluated requirements;
- Source Approval digest and non-secret frozen effective Storage Binding;
- official schema pin, consumer-profile/validator identity and performed checks;
- observation start/end, full-versus-partial scope, known source snapshot/version identifiers when available, and outcomes/limits.

No atomic cross-check/source snapshot is implied when the backend cannot provide one. Mutable unversioned data is honestly as-of, not unchanged or currently compliant. A changed dependency invalidates applicable evidence; age cannot excuse a known mismatch. Still-applicable observations may be reused under the age/scope/dependency rules without repeating a passing scan or restamping its time. A new final-candidate validation must verify and bind any reused observation; authored fields cannot forge it. Existing bounded validation/repair attempts remain binding, with no automatic retry or budget expansion.

Static CLI/CI checks perform document, reference and binding checks only, and label live checks `not_run`. Static success is not the evidence needed for admitting dependent models. Explicit approved-source `validate_proposal` performs the live portion and stores evidence for the exact finalized candidate; no new permission-granting or raw-SQL command is added.

Human Git Review Admission requires all applicable declared schema/quality requirements of each bound OSI dataset to have complete, applicable, unexpired passing evidence. Drift, unavailable, unsupported, refused, error, not_run or forged/stale proof blocks that candidate's admission; technical success still never supplies human approval. Valid unbound contracts can be retained as documents without a data-conformance claim and do not invent dependencies for unrelated models. Projects with no contracts retain their existing applicable checks and context-only behavior.

## 7. Discovery and runtime behavior

Extend source-free `discover` with a bounded contracts group carrying producer ID/version, native binding and model/dataset identity, supported-profile scope/limitations, candidate/admitted revision as appropriate, and the matching stored observation's as-of/eligibility status. `list_datasets` retains its existing approved live-catalog construction, actual table/column fields and refusal behavior; annotate its entries with matching contract metadata from the pinned snapshot without extra source reads or a second inspection. Do not replace its catalog with stale artifact-only data or claim the complete operation is source-free. Authoring review/read uses explicit selected candidates; default Analyst discovery reads only its pinned admitted snapshot. A newer candidate, current worktree or matching filename never replaces that snapshot's contract or evidence.

Absent/mismatched/expired observation evidence is reported honestly, not regenerated by these metadata additions or presented as a current pass. `discover` remains source-free, including before first admission; calling the existing live `list_datasets` route still requires its ordinary admission/source prerequisites. Contract text, private server addresses and instructions are not sprayed into agent prompts. No new tool registration is required: existing CLI/MCP/embedded-Agent adapters expose the native results, preserving their role boundaries. Packaged guidance explains the limited profile and human handoffs.

Admission governs definitions, not permanent source health. Expiry or later drift does not silently rewrite/unadmit definitions, run a background scan, or introduce a new runtime refusal policy. Existing Source Approval, compiler, grain, limits and current query-execution gates remain. An as-of contract pass never turns an ad-hoc metric into a governed one, an Answer Example into an answer cache, or missing Context into a new #76 mandatory-Policy refusal.

## 8. Observable acceptance criteria

1. **AC1 — Standard pin:** an independently sourced official v3.2.0 fixture validates deterministically using packaged bytes matching the recorded hash; malformed documents and a different apiVersion fail visibly offline. The schema-less four-field case is document-valid but never source-compliant. Duplicate scoped IDs and dangling internal references fail their distinct semantic checks.
2. **AC2 — Git binding and ownership:** revision-checked edits retain producer contracts and native bindings in one complete Git candidate; restart/read/review preserves producer ID/version and undeclared ownership without insertion. Wrong/ambiguous selectors or mismatched source/model bindings cannot redirect reads or be admitted. Observations never change the reviewed contract's bytes.
3. **AC3 — Schema drift:** a temporary approved source fixture with independently declared expected columns/types passes the small profile. Removing a required column or changing an integer column to a string yields actionable drift without changing the contract; unsupported physical metadata never passes by coercion.
4. **AC4 — Permission and unavailability:** a contract/server/binding alone cannot open a source or widen S3 scope. Missing permission refuses before inspection; an approved but unavailable source reports unavailable, never compliant. Reuse applicable native approval/storage checks; add only the uncovered contract-route scenario.
5. **AC5 — Quality execution:** a hand-worked DuckDB fixture supplies an independent expected scalar/NULL count; the supported rule passes/fails accordingly. A forbidden relation/function/join is refused before execution; wrong result shape and unsupported dialect/feature do not pass. Pinned open interval endpoints and the schema's combined-operator rejection have independent expectations from the pinned sources, not implementation output.
6. **AC6 — Evidence and admission:** unmeasured static validation cannot admit a dependent model. Complete passing approved-source evidence plus human action can; changed contract/binding/approval/profile dependencies, incomplete/expired/forged evidence and an unsupported required constraint cannot. Reuse retains the original observation time and never asserts unchanged mutable data.
7. **AC7 — Discovery and bounds:** admitted `discover` reports only that snapshot's contract and matching as-of evidence without source access; draft inspection is explicitly selected and labeled. `list_datasets` preserves its actual approved live catalog, with snapshot-based contract annotations causing no extra source reads. Execution/response ceilings cannot be raised from candidates, and timeout/partial work cannot claim full success. Contract-free projects and existing role/tool boundaries remain supported.
8. **AC8 — Honest qualification:** report the exact candidate and focused evidence used; no broad-suite, Docker, transport, live-model or production conformance claim follows from these fixtures. Mandatory named project/CI gates remain binding; further checks need a named reachable failure, independent oracle and cheapest suitable seam. No issue closure, integration or publication is implied.

These criteria define behavior, not a test-count target. The plan assigns one useful verification obligation per uncovered behavior and reuses applicable passing native source/admission/adapter checks. No repeated certification matrix or second evidence ledger is required.

## 9. Scoped extensions and capture checkpoint

This specification extends spec 0027's typed authored/snapshot inventory with contract documents/bindings and its exact-revision validation/admission with the above profile evidence. It does not reopen legacy persistence or add a general SQL submission operation. It extends spec 0010's operator inspection ceilings/evidence-age mechanism to contract checks without changing mapping semantics. ADR-0017's single OKF authority for explanatory knowledge and ADR-0023's frozen effective endpoint/secret rules remain. Physical expectations in producer contracts do not become a second OKF terminology registry or an OSI compiler.

- **Vocabulary:** Data Contract, Contract Binding, Contract Observation and Contract Drift are captured in the owning root glossary; observation is distinct from upstream Source Quality Evidence and human admission.
- **Decision:** ADR-0025 records why producer-owned contracts are separate from native consumer bindings and shared #76 authority rather than embedding consumer configuration into producer documents.
- **Behavior:** the complete in-chat design and written revision 1 with its concrete interfaces, ADR and glossary were owner-approved on 2026-10-17. The owner subsequently approved revision 2's scoped discovery correction after actual caller inspection: only `discover` is source-free; `list_datasets` keeps its live-catalog semantics. All other behavior remains revision 1. Implementation planning is authorized; no implementation readiness or plan approval is inferred.
- **Uncertainty:** no external ABI, other SQL engine or unsupported field semantics are selected. Native resolver, snapshot/admission/validator, static CLI, discovery/Agent adapter and package-resource changes must be mapped in the subsequent plan; a conflict or unsupported resolver case must be surfaced, never guessed away. Actual access/environment qualification remains future work.
- **Handoff:** planning-contract v1, installed provenance unknown. Use the same `2026-10-17-0028-odcs-contract-consumer` prefix for the subsequent implementation plan, which requires its own approval. Implementation, dependencies, integration and publication retain their separate approvals.
