# Specification 0032: Integrated queries and technical Context profiles

**Status:** revision 1 — owner-approved design, written capture for review,
2026-10-22. Not implemented or release-qualified by this document.

**Approval:** in the current BB conversation the owner selected:
“Abfragen und Ad-hoc-Metriken”, “Dataset/Table/Computation zuerst”,
“Explizite Zuordnung, verbindliche Prüfung”, “Nachweise mit Herkunft und
Gültigkeit”, “Bestehende Core-Regeln verwenden”, “Kontext für jede verwendete
Quelle erforderlich”, and “Explizite Inspektion, anschließend Review”. The
owner accepted the profile boundaries and then confirmed the complete design:
“Ich bestätige dieses Gesamtdesign. Halte es in Spec und ADR fest; zunächst
keine Implementierung.” This authorizes the written capture and scoped
contract reconciliation only, not execution, integration, push or publication.

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
