# Specification 0032: Integrated queries and technical Context profiles

**Status:** revision 2 — owner-approved exact contracts, 2026-10-22.
Revision 1 (same day) captured the owner-approved design for review;
revision 2 adds §10's exact interface representation, grounded by source
correspondence against the current runtime. Not implemented or
release-qualified by this document.

**Approval:** in the current BB conversation the owner selected:
“Abfragen und Ad-hoc-Metriken”, “Dataset/Table/Computation zuerst”,
“Explizite Zuordnung, verbindliche Prüfung”, “Nachweise mit Herkunft und
Gültigkeit”, “Bestehende Core-Regeln verwenden”, “Kontext für jede verwendete
Quelle erforderlich”, and “Explizite Inspektion, anschließend Review”. The
owner accepted the profile boundaries and then confirmed the complete design:
“Ich bestätige dieses Gesamtdesign. Halte es in Spec und ADR fest; zunächst
keine Implementierung.” This authorizes the written capture and scoped
contract reconciliation only, not execution, integration, push or publication.

**Revision 2 approval:** on 2026-10-22 the owner instructed “Implementiere die
offenen issues autonom” and, through the orchestration parent, explicitly
selected the Core-owned representation for Policy applicability and
existing-check references: a versioned authored `policy_bindings` block in the
integration selector plus an admission-captured binding inventory, with the
native producer schema unchanged (the considered alternative, a producer-side
applicability extension, was rejected as materially heavier). This authorizes
autonomous completion of this documentation unit and its scoped amendments
only — still no implementation, integration, push or publication.

**Sources:** [vocabulary](../../CONTEXT.md),
[ADR-0026 amendment](../adr/0026-lumio-sdk-bound-governed-releases.md#integrated-query-and-profile-expansion--2026-10-22),
[bound releases](2026-10-18-0029-lumio-bound-governed-releases.md),
[bounded queries](2026-10-08-0014-bounded-record-queries-and-results.md),
[Context profiles](2026-10-02-0010-context-layer-schema-and-identifiers.md),
[trust signals](2026-10-06-0011-context-trust-signals.md),
[quality evidence](2026-10-06-0013-source-quality-evidence.md),
[Lumio producer profile](../../../lumio/project/specs/2026-10-18-0009-ariadne-context-profile.md).

**Planning contract:** version 1; installed skill catalog revision unknown.

## 1. Scope and precedence

Design two separately implementable follow-ups to #76: integrated query
operations, and Dataset/Table/Computation profile consumption. The delivered
Metric/Policy/Reference, navigation, local and optional-S3 contracts of spec0029
remain the baseline. This specification amends its deferred scope and profile
refusals only for the future approved capabilities below. It does not change
the current SUPPORT matrix or claim that a new SDK/package pair is available.

Lumio and Ariadne remain independently installable and usable. Integrated mode
uses one jointly reviewed Content Commit, verified Bound Release and effective
Visibility Scope. Lumio owns curated Knowledge and native profile parsing;
Core owns contracts, semantic definitions, inspection, evidence verification
and execution. No second maintained context_layer copy or KB YAML parser is
introduced. Standalone contracts remain unchanged and SDK-independent.

Non-goals: Skill profiles, save_example/search_examples, a general Policy rule
language or Policy-to-SQL compiler, inferred joins/equivalence, raw-SQL tools,
new engines, automatic measurement/admission, source-data snapshotting,
private application/Agent adoption, deployment and software publication.

## 2. Operations and authority

- query_detail remains a governed detail projection over the admitted semantic
  graph. Existing field/path, grain, cardinality and join proofs remain binding;
  Context content does not replace them or make a new join admissible.
- query_records remains bounded single-dataset record selection with its
  existing request, read-only and output contracts. It always reports
  governed: false, even with approved sources and an admitted Bound Release.
- define_metric remains one-shot, unsaved Ad-hoc Metric execution through the
  existing static IO-authority, compiler, grain, bind and bounded-execution
  gates. It always reports governed: false and creates no proposal, page,
  Computation record or confirmation as a side effect.

None may fall back to legacy Context, a mutable publication pointer or an
unapproved source after integration validation fails. Existing operator and
Analyst role boundaries remain; enabling execution does not grant authoring.

## 3. Complete physical-source Context coverage

Resolve every physical dependency actually consumed by the request to its
canonical Resource identity in the admitted release. Include lookup tables,
joined dependencies permitted by the existing operation, and nested sources
permitted by Ad-hoc authority. Do not broaden which sources/expressions an
operation accepts merely to provide Context coverage.

Every consumed physical table requires an unambiguous, readable Table profile
bound to that exact Resource. A Dataset Overview describes an identified
source/collection and its linked tables; it is additionally required when the
collection itself is consumed or referenced. Do not require an otherwise
unused grouping page for each table. These are not OSI semantic datasets.

Missing, ambiguous, mismatched or out-of-scope mandatory Context refuses before
query SQL execution. An ordinary unprofiled page is not a technical binding.
Titles, aliases and confirmed Identifier Mappings never substitute for Resource
identity or grant join permission. Source Approval remains separate.

The complete captured KB is validated at admission, including hidden and
unreferenced technical profiles. Runtime disclosure is scoped before page
selection, counts and citations. Hidden required dependencies refuse without
leaking their content. These requirements apply equally to local and S3.

## 4. Explicit Policy applicability and existing checks

Each required Policy association identifies its subject (calculation, Dataset
or Table), applicable operation and whether it is explanatory or requires an
existing machine-checkable Core rule. Applicability is an explicit reviewed
binding, not title/alias matching or a model's interpretation of prose.

For an executable obligation, the binding must identify the actual existing
Core check and its relevant reviewed definition/dependencies. Admission must
reject an obligation lacking supported enforcement; runtime cannot execute by
merely citing its narrative. The specification adds no general interpreter,
free-form check dispatch, automatic SQL predicates or access-control system.
Existing supported Core constraints retain their own semantics and authority.

A calculation-specific rule applies to that calculation. For example, a
sanctioned revenue expression excluding cancelled orders does not forbid a
Record Query explicitly asking for cancelled orders. Source-level obligations
must be explicitly applicable to the operation. Do not turn a calculation rule
into a universal source filter or treat every Policy as an access restriction.

Resolve complete transitive required Policy Closure in the pinned snapshot.
Return its required content and citations. Prose is explanation, not proof of
semantic equivalence to SQL. Mandatory unsupported, unavailable or conflicting
obligations refuse; they are never silently downgraded to warnings.

## 5. Profile and evidence contracts

Reuse producer-native Dataset/Table/Computation profiles and Core validators;
never create a second producer schema or silently discard native fields.

- Dataset binds an identified collection/source and its Table references.
  It is neither an OSI model nor a Source Approval.
- Table binds a physical Resource and its curated description, schema inventory
  and available technical observations. Observed schema is not an ODCS contract;
  samples and observed values are not permanent constraints or complete enums.
- Computation binds the exact sanctioned semantic definition, applicable
  Policies and numerical-validation status. Its Entity and semantic reference
  must correspond to the definition reviewed for this release. An unrelated or
  changed Ad-hoc expression cannot inherit that status.

Preserve full supported metadata and honest unknowns. Core-produced technical
claims require their actual verifiable origin, scope/time and relevant
source/definition/Policy dependencies; authored generated/verified/attester
values alone grant no authority. Inspection and measurement remain Core-owned;
Lumio preserves the native result without acquiring execution dependencies.

Use existing evidence eligibility and freshness rules. Missing optional facts
remain unknown; optional stale observations retain their advisory caveats.
Missing, invalid or stale evidence required by the admitted definition blocks
its affected operation. Do not turn every advisory review_after/stale_after
into automatic unadmission. A Computation may remain attestation: pending unless
its definition explicitly requires independent numerical validation.

Human review, compilation, Execution Attestation and Independent Numerical
Validation remain distinct. A historic check proves its identified definition,
data scope and time only. Pinning Knowledge does not freeze mutable data or
prove today's numerical result was independently checked.

## 6. Explicit inspection and one reviewed content lifecycle

Inspection is an explicit operator-authorized action with existing Source
Approval and disclosure-selection controls. Source access permission does not
implicitly authorize publishing sampled values. Curated text stays curated;
Core-generated portions and evidence claims retain their existing protections.

Inspection produces candidate changes through the producer's supported
revision-checked authoring APIs. Changes to reviewed inputs or generated
technical metadata belong to the new final Content Commit. Validation checks
existing evidence and may finalize deterministic metadata under existing
rules; it starts no implicit live measurement. Neither query serving nor page
browsing refreshes, writes, publishes or activates observations.

The operator reviews actual changes and gives the existing overall human
confirmation. Final Core activation remains descriptor-last and atomic, with
native publication residue disclosed on failure. Retrying uses native revision
and expected-current checks. Old sessions retain their original complete pin;
new operations require new matching admission when capabilities change.

## 7. Responses, limits and migration

Preserve existing operation request semantics and successful response fields.
Integrated responses additionally identify the Bound Release, Published Version,
physical dependencies, applicable Context and evidence caveats. Detail remains
governed only by its existing graph-backed definition; source Context does not
create a freestanding governed metric definition.

For define_metric retain context: null: no admitted metric Context exists for
the ephemeral definition. Disclose bound source Context separately as
input_context, with per-Resource Table/Dataset content, required Policies,
version-qualified citations and evidence caveats. Use the same input_context
concept for the added source Context of detail and record responses; do not
reuse a metric-context field to imply Ad-hoc governance.

Preflight the complete mandatory Context before query SQL. Existing source
permission, compiler/planner/bind and runtime rechecks still apply. Final
complete-response, row/cell, deadline and actual CLI/MCP envelope safeguards
remain binding; exceeding a required-output bound refuses the operation,
never truncates required Policies or returns a successful partial report.

Support is explicit in the reviewed capability/consent binding. Existing
admissions cannot silently gain new operations or profile semantics. There is
no automatic page backfill, measurement, migration or activation. Existing
previously admitted operations remain governed by their qualified contract;
a later admission opting into this expansion must satisfy its full coverage.
A release number alone does not prove SDK/Core compatibility.

## 8. Observable acceptance examples

1. A revenue definition explicitly excludes cancelled orders. An admissible
   Record Query can still select those orders when no applicable source-level
   obligation forbids it, and reports governed: false with its source Context.
2. An Ad-hoc source references a Table without bound Context, including through
   an allowed nested source. Refuse before query execution, without fallback.
3. A detail request names an unproved lookup path. Matching wiki text or a
   confirmed Identifier Mapping cannot make the join admissible.
4. A Computation's semantic definition or relevant checked dependency changes.
   Its prior numerical check cannot authenticate the changed definition. A
   mandatory invalid check blocks; an optional absent check remains unknown.
5. A required Policy has no supported existing enforcement. Admission refuses;
   citing its narrative cannot enable execution. Explanatory text produces no
   automatic predicates or claim of verified narrative-to-SQL equivalence.
6. Explicit inspection creates a candidate observation with provenance and
   selected disclosure. Validation and query serving perform no fresh sampling;
   curated text survives, and authored verification stamps do not authenticate.
7. Release B changes Context. An existing local or S3 session still uses A;
   a new session sees B only after complete human admission. A failed activation
   leaves the prior descriptor intact and reports actual publication residue.
8. Complete required input_context exceeds the host/transport ceiling. Refuse
   without query execution when the Context alone cannot fit. Final result
   overflow also refuses; it never removes mandatory Context to fit.
9. A valid Ad-hoc result has governed: false, context: null and pinned
   input_context. It creates no Computation page or saved definition.
10. Both standalone products retain their existing operation, optional import
    and advisory-Context behavior without requiring this integration.

Expected values for later tests come from authored inputs and these contracts,
not implementation output. Planning must name focused coverage and native
compatibility checks; no tests or services are run by this design capture.

## 9. Capture and handoff boundary

Vocabulary uses existing Dataset Overview, Schema Observation, Computation,
Policy and Ad-hoc terms; governed detail and input Context distinctions are
captured in the Ariadne glossary. ADR-0026 and producer ADR-0030 record the
chosen boundaries and alternatives; spec0029 and producer spec0009 link here.

Behavioral choices above are approved. Before execution, planning must ground
the exact Policy association/check-reference representation in the existing
Core contracts and producer schema, and freeze the additive input_context wire
shape and public API correspondence. This is not permission to invent a new
rule language or relax coverage. If existing contracts cannot represent these
approved obligations, return that concrete mismatch for a scoped design
amendment before dependent implementation. No plan, ticket mutation,
implementation, integration or publication is authorized by this capture.

## 10. Exact contracts — revision 2, 2026-10-22

This section grounds §9's readiness prerequisite in the inspected current
source (baseline `1d3f127` at writing time; symbols name actual existing
checks). It changes no approved §1–§9 decision; runtime implementation
belongs to #83/#84. The native producer schema is unchanged: the typed
`required_policies` edge on a subject's own page remains the KB association,
and Dataset/Table/Computation envelopes (producer spec 0009 §2) require no
extension. Applicability and enforcement live in the Core-owned consumer
contract below.

### 10.1 Authored `policy_bindings` block

`context_integration.yaml` keeps its five existing keys, semantics and file
`version: 1` unchanged and gains one optional top-level key, `policy_bindings`,
with its own exact version. Its absence keeps current behavior; an admission
opting into support revision ≥2 (§10.3) requires it.

```yaml
policy_bindings:
  version: 1
  bindings:
    - subject:
        kind: metric | computation | table | dataset
        identity: "<model>::<metric>" | "<semantic id>" | "ariadne://table/<x>" | "ariadne://collection/<x>"
      policy:
        namespace: "<kb namespace>"
        entity_id: "<policy entity id>"
      operations: [get_metric, query_metrics, query_detail, query_records, define_metric]
      enforcement: null  # explanatory
      # or, for an executable obligation:
      # enforcement: {check: "<§10.2 check id>", definition: "<exact reviewed identity>",
      #               dependencies: ["<exact dependency identities>"]}
```

Closed validation, refusing with named diagnostics (never ignoring):

- Exact key sets: the block exactly `{version, bindings}`; each binding
  exactly `{subject, policy, operations, enforcement}`; `subject` exactly
  `{kind, identity}`; `policy` exactly `{namespace, entity_id}`; `enforcement`
  `null` or exactly `{check, definition, dependencies}`. `version` is the
  exact integer 1.
- `(subject, policy)` pairs are unique; conflicting duplicate declarations
  refuse.
- Identity grammar per kind, matched exactly against the captured snapshot:
  `metric` = the native `model::metric` of a bound metric page's `metric_ref`;
  `computation` = the native semantic identity of a computation page's
  `core_ref`; `table`/`dataset` = the canonical `ariadne://table|collection/…`
  of the page's `core_ref`. Titles, aliases and paths never identify a subject.
  `policy.namespace` must be the selected KB namespace (v1 never traverses
  another namespace); the entity must exist and be a Policy page.
- `operations` is a nonempty subset of the five integrated Analyst operation
  identifiers above, closed against the admission's declared support revision
  (§10.3): an operation not in that revision's frozen capability set refuses.
- `enforcement: null` is explanatory. Otherwise `check` must be a §10.2
  catalog id whose executed-for set contains **every** operation in
  `operations` — only a check that actually executes for that operation may be
  a binding target; a name in an allowlist is not proof it was applied.
  `definition` names the exact reviewed definition identity; `dependencies`
  lists exact dependency identities (possibly empty).
- Agreement with the captured KB: for every subject **consumed by an
  operation of the admission's support revision**, the subject page's complete
  typed `required_policies` closure must be exactly classified by authored
  bindings — a closure policy without a matching record is an unclassifiable
  mandatory obligation and refuses; a binding naming a policy outside the
  subject's closure refuses as an invented obligation.
- The block carries only identifiers — no credentials, pointers, code or
  check implementations. Nothing in this contract performs arbitrary code
dispatch, dynamic imports or automatic filters.

### 10.2 Existing-check catalog (stable ids)

Each id names the existing check that actually executes; the current-source
symbol is binding on implementation:

| Check id | Existing check | Executed for |
| :--- | :--- | :--- |
| `adhoc.static_io_authority` | `assert_ad_hoc_authority` over the whole nested source/expression trees, static, before any data read | `define_metric` |
| `adhoc.grain_preserving` | `check_grain_preserving` on the Ad-hoc source | `define_metric` |
| `graph.relationship_audit` | `plan_query` relationship/grain audits over the admitted graph (`plan.audits`, `plan.relationship_audit`) | `query_metrics` |
| `detail.path_proof` | `plan_detail` field/path/join proofs and relationship audit over proven lookup paths | `query_detail` |

Response/transport budget guards, T2 mapping confirmation, admission/identity
rechecks, the single-statement/EXPLAIN bind and evidence freshness/eligibility
are invariants, never attachable targets. `get_metric` executes only invariant
gates in this revision, so its calculation-subject bindings are explanatory
only. Catalog growth requires a spec revision naming the actually-executing
check; implementations add no entries.

### 10.3 Staged capability revisions and the admission-captured inventory

Compatibility uses explicit per-admission capability revisions, not global
support-set equality (which would invalidate old admissions). Each revision
integer names one frozen immutable capability table — supported profile
kinds, supported operations, storage — validated exactly:

- **Revision 1 (existing):** profiles `metric, policy, reference`; the nine
  existing operations; `query_detail`, `query_records`, `define_metric`
  unsupported. No `policy_bindings` requirement.
- **Revision 2 — profile-expanded (#83):** adds `dataset, table, computation`
  profile kinds with their producer-native envelopes; requires the
  `policy_bindings` block; consumed-subject classification covers the
  governed operations' metric closures and the computation pages their
  context assembles. The three query operations **remain unsupported** — a
  revision-2 admission neither advertises nor serves them, and a binding
  naming one refuses (§10.1).
- **Revision 3 — query-expanded (#84):** adds `query_detail`, `query_records`,
  `define_metric` with §10.4/§10.5; consumed-subject classification extends to
  the operations' physical dependencies (§10.5).

Rules: an admission declares exactly one revision; its stored support set
must exactly equal that revision's frozen table (tampering detection);
manifest support is checked against the table **for its recorded revision**,
never against the currently newest set, so previously qualified operations on
older releases stay valid; a revision newer than the installed consumer's
known tables refuses; new capabilities apply only through a new admission
opting into the higher revision — no automatic backfill, upgrade or rewrite
of existing manifests or sessions (§6/§7). Sequencing: #83 lands a coherent
revision 2 before #84 builds revision 3 on it.

The Bound Release manifest gains two digest-bound, admission-captured
fields: `support_revision` (the exact integer) and `policy_bindings` (the
validated binding inventory from the reviewed Content Commit). Admission
validation extends the existing consumer candidate gates with §10.1;
`verify_release` re-derives and equality-checks both fields from the pinned
snapshot.

### 10.4 `input_context` response schema (revision 3)

Additive on `query_detail`, `query_records` and `define_metric` responses.
`query_metrics` keeps its existing context contract; `define_metric.context`
stays `null`. Page views reuse the producer's published page-view contract
(spec 0009 r3 additive facade — the observable `PublishedContextPage` fields);
no parallel page schema is introduced.

```json
"input_context": {
  "bound_release": "<manifest digest>",
  "published_version": "<immutable Published Version>",
  "resources": [
    { "resource": "ariadne://table/<x>",
      "table": "<full published page view>",
      "dataset": "<full published page view> or null" }
  ],
  "policies": [
    { "subject": {"kind": "…", "identity": "…"},
      "association": {"namespace": "…", "entity_id": "…"},
      "operations": ["…"],
      "enforcement": "null or {check, definition, dependencies}",
      "page": "<full published page view>" }
  ],
  "context_signals": {"pages": ["…"], "warnings": ["…"]},
  "evidence_caveats": ["…"]
}
```

Every page view — Table, Dataset Overview and **each required Policy** — is
the exact pinned canonical view with full content and disclosed native
metadata, never a citation-only entry: byte-exact canonical content (CRLF
preserved as published), honest inclusive 1-based line coordinates,
version-qualified citations (namespace, entity id, path, Published Version,
citation), public provenance and advisory lifecycle. No private operational
data: storage keys, private registries, receipt bodies and admission records
stay out; only public page facts and safe digests appear. `resources` lists
every §10.5 physical dependency in canonical order; a Dataset Overview view
appears only when the collection itself is consumed or referenced.
`policies[].enforcement` mirrors the admitted inventory for this operation;
explanatory records prove no narrative-to-SQL equivalence. `evidence_caveats`
reuses the contract-native evidence disclosure (advisory stale/unknown vs
required invalid) with no new numerical measurement interpreter. The complete
envelope is budget-accounted through the existing public seam
(`query_results.account_rows`/`finalize_response`, as `_sdk_metric_contexts`
uses) before any live operation; mandatory-Context overflow refuses without
execution, and final whole-response safeguards never elide mandatory content.

### 10.5 Frozen operation pipeline

For each revision-3 operation, in this order:

1. Capability gate against **this admission's** support revision and request
   shape validation.
2. Existing admission/pin rechecks (identity, registry digest).
3. Static dependency and authority parsing — no live check executes:
   `query_detail` resolves the requested root dataset and requested lookup
   paths by static traversal of the admitted graph's proven edges (granting
   nothing; `plan_detail`'s own proofs still refuse unproven paths);
   `query_records` resolves the one named catalog dataset's canonical
   resource; `define_metric` extracts physical references from the whole
   normalized nested source tree by scope-aware static parsing
   (`_qualified_source_refs` semantics) after the static IO-authority check,
   which precedes any data read.
4. Complete Context/enforcement/budget preflight: per-resource Table binding
   by exact `core_ref` match, optional Dataset Overview, complete typed
   closure classification (§10.1) and scope check, enforcement applicability
   for this operation, then the full `input_context` budget preflight — all
   before any planner, live audit, bind or SELECT work. Dependencies are
   never obtained by prematurely executing live checks (e.g. the Ad-hoc
   grain-preserving guard reads data and stays in stage 5).
5. The existing live sequence unchanged (grain guard where applicable,
   compile, audits, single-statement guard, EXPLAIN bind, guarded collection,
   deadline).
6. Final whole-response safeguards unchanged (completeness, accounting,
   transport preflight, last deadline check).
