# Specification 0009: Ariadne Context Profile and pinned SDK consumption

| | |
| :--- | :--- |
| **Status** | **Approved behavior, written revision 1.** Isolated L1 execution is now approved by the scoped amendment below; integration/publication remain gated. |
| **Approval** | Owner, Pi conversation 2026-10-18 for Lumio #2/Ariadne #76: one Content Repository, direct optional Python SDK, integrated-only strict mandatory Policies, one overall human confirmation and project-wide Visibility Scope defaulting to public. Selected “Design freigeben (Recommended)” for the six-section joint design and documentation capture in both repositories, then “Schriftliche Fassung freigeben (Recommended)” for both written revision-1 specifications, ADRs, glossaries and scoped source amendments, opening implementation planning only. |
| **Intake** | [Lumio #2](https://github.com/legout/lumio-wiki/issues/2), [Ariadne #76](https://github.com/legout/ariadne/issues/76). |
| **Baseline** | Lumio `31b6a3e1ef8d04a968b8605128efbdb519396aa7`; Ariadne `24630dbd404870f30602d66b5d5a2d53fa892f86`. Inspected source identities, not certified installed pairing. |
| **Decision** | [ADR-0030](../adr/0030-ariadne-context-profile-and-sdk-boundary.md), [vocabulary](../../CONTEXT.md). |
| **Companion contract** | `legout/ariadne:project/specs/2026-10-18-0029-lumio-bound-governed-releases.md`, written revision 1: owns overall admission, release manifest, activation and governed query behavior. |
| **Contract** | planning-contract v1; installed catalog provenance unknown. |
| **L1 execution amendment** | Owner, Pi conversation 2026-10-18: “Implementiere #2 autonom mit paseo subagents”, then “Freigeben und #2 starten (Recommended)”. Approves the existing plan-r1 L1 slice and local isolated commits of the approved document sets in both repositories. L1 only: no A1/Q1 implementation, target integration, push, issue update, release, real KB or private-app access. Behavioral revision 1 is unchanged. |
| **Reconciled execution base** | Lumio `c59a1df4ebc1e619543d04c3c70931145cb5a918`; Ariadne native source `24630dbd404870f30602d66b5d5a2d53fa892f86`. The Lumio release delta from the inspected baseline changes SDK version/skill metadata and packaging/release tooling, not native SDK behavior. Profile support is not part of published 0.2.0. |

## 1. Scope and authority

Add one explicitly selected `ariadne-context/1` application profile and
additive Python SDK view over native Lumio content. Lumio remains the canonical
owner of curated Policies, terminology, Claims and business context. Ariadne
owns producer ODCS contracts, local physical bindings, OSI, technical observations,
measurement receipts and safe numerical execution.

The profile preserves explicitly supported Ariadne metadata; it is not a claim
that generic OKF Exchange Profile 1/2 is lossless. Those existing exchange
contracts remain unchanged and retain loss disclosure. Their output cannot
masquerade as this native SDK profile.

Lumio remains independently installable, Python >=3.14, model-free and usable
without Ariadne, DuckDB, SQLGlot, a server, GitHub or mandatory LanceDB.
Existing optional MCP remains read-only and is not the cross-component data
plane. There is no dependency from Lumio into Ariadne.

Excluded: private web-application adaptation, a new service, automatic SQL or
join semantics, implicit ontology equivalence, automatic publication, mandatory
cloud deployment, real KB migration, raw-source exposure, production data,
numeric replay, software release or deployment.

## 2. Native authored representation

One shared Content Repository contains the Ariadne project at its root and
the native `knowledge/` KB subtree. Continue native Git authoring with the
KB's Control File, Source Reference Manifest and private external Source
Registry. A single exact Content Commit can change the contract, metric,
Policy and related knowledge; no cross-repo draft/proposal store is added.

Canonical Lumio page metadata, Entity identity, Claims, sources, Lifecycle,
Visibility and body keep their existing meanings. Native `sources` remain
provenance, not overloaded executable bindings or required Policy edges.

A profiled page adds an optional typed `ariadne_profile` envelope:

| Field | Profile-v1 contract |
| :--- | :--- |
| `version` | Exact integer 1; no coercion or latest-version dispatch. |
| `kind` | One of `dataset`, `table`, `reference`, `policy`, `metric`, `computation`, `skill`. Kind is application metadata, not a global Lumio ontology type. |
| `native` | Losslessly retained supported Ariadne OKF metadata; its existing nested `ariadne` extension/evidence, source-qualified field scope and identifiers are not flattened or guessed. Body remains the native Compiled Page body, not a second body copy. |
| `required_policies` | Explicit list of exact `{namespace, entity_id}` references, mandatory even when empty for metric and Policy pages. It is distinct from native/canonical provenance sources. |
| `metric_ref` | Required for metric pages: exact native model/metric identity. No generated replacement ID or title match. |
| `core_ref` | Explicit native Resource or semantic identity when the page annotates an Ariadne-owned artifact; required for dataset/table/computation annotations. No executable definition is copied into Lumio. |
| `ontology_refs` | Optional explicit declared namespace/identifier/immutable-revision references; no title-derived equivalence. |

The `native` slot supports the existing Ariadne metadata families in the
source contracts below: typed page/resource identity, structured provenance,
generation/verification/lifecycle/freshness, Computation attestation metadata,
and Reference/identifier representation/mapping/evidence metadata. Preserve
scalar types, ordered lists, scoped identifiers and full text, not merely a
selected summary. The profile implementation must encode that v1 supported
schema from these exact approved sources; unknown required keys/variants,
malformed supported structures and incompatible versions fail with a named
path/field diagnostic. They must not become opaque accepted authority.
Supported YAML temporal scalars retain their original published source;
JSON disclosure uses the existing native date/time representation contract,
not a conversion that invents freshness or verification. Existing native
credential/path/resource validation applies to the supported payload and its
diagnostics. No credential, arbitrary Python object, executable attester or
dynamic SQL is interpreted by this slot.

Schema owners for the supported native families are Ariadne specs 0010
(`2026-10-02-0010-context-layer-schema-and-identifiers.md`), 0011
(`2026-10-06-0011-context-trust-signals.md`), 0024
(`2026-10-13-0024-context-routing-filter-evidence-and-onboarding.md`)
and the native Context contracts at the inspected Ariadne baseline.
New producer implementation must freeze those source revisions/fixtures and
be accepted before a dependent consumer implementation starts. This is a
defined support boundary, not permission to invent another native schema.

Dataset/table/computation/metric annotations cannot replace Core observations,
OSI or actual independent numerical validation. Authored `verified`,
`attester`, evidence IDs or human actor strings do not manufacture measurement
receipts, mapping confirmation, Publication Admission or a successful run.

## 3. Preservation, validation and native operations

Profile content is authored content. Include all profile bytes in native
canonical capture, validation, publication manifest/digests and fingerprint
identity. A profile-only change must not reuse an identity from before that
change. Existing plain KB fingerprints/operations remain unchanged when the
extension is absent.

Publication retains exact committed Markdown; the SDK supplies both its full
content and typed supported metadata. A native author/read/revise/publish/read
round-trip retains the complete Policy body, supported native values, canonical
sources, evidence anchors, identifiers and scope. This is semantic metadata
preservation and exact published-source content, not a promise to keep YAML
styling across an explicitly requested edit.

Existing ingest/maintenance/rename/merge/removal helpers must either preserve
profile fields and repair exact impacted references under existing Git review
or refuse the operation with diagnostics before an unsafe rewrite. They may
not rebuild a profiled page through a lossy generic OKF/canonical renderer.
No source/publication receipt is authored into a page to make it authoritative.

Native validation checks the complete captured candidate: envelope schema,
unique Entity and metric bindings, declared profile fields, scope-aware
references, required Policy Closure, controlled ontology declarations and
exact Source Reference Manifest consistency. It performs no database access.

Ariadne validates the other side: actual model/metric/physical references,
supported native metadata semantics requiring Core context, native mapping
receipts/confirmations, contract/source/evidence/grain checks and execution.
Passing Lumio validation alone is not joint validity or numerical governance.

## 4. Identities, ontology and Policy Closure

Knowledge identity is `(KB Namespace, Entity ID)`, not title or path. Preserve
that identity through a supported rename; changed IDs require an explicit
reviewed reference update, not fuzzy repair. Ariadne native Resource and
model/metric identities and producer ODCS IDs retain their own scopes.

Explicit cross-ontology references name a declared target namespace, identifier
and immutable revision. Validate against the pinned declared catalog/reference
scope supplied by the candidate; unknown/ambiguous required targets refuse.
No network lookup, downloaded vocabulary, navigation link or similar alias
establishes correspondence. Declared external reference validity does not prove
real-world semantic equality. Core execution/confirmed Mapping rules remain
separate even for a valid reference.

Each integrated metric has exactly one Context Binding to a metric Entity.
Every native modeled metric in the integrated scope must be covered or the
joint release refuses; context-only candidates remain possible without inventing
metrics. Two pages cannot bind the same exact metric. Empty Policy requirements
must be intentional, explicit and reviewed, not inferred from missing metadata.

Policy Closure is the finite transitive set reachable through only typed
`required_policies` edges from the metric page. Every target must be an
existing Policy Entity in the selected KB Namespace and exact Published Version.
V1 does not traverse another KB Namespace for mandatory Policies. Deduplicate
by exact identity, handle finite cycles deterministically, and never infer edges
from Markdown links, arbitrary Claims, paths or Source references.

Retained native metadata referring to a Policy must agree with the typed
binding; unresolved or contradictory legacy path/Policy references are
diagnosed and rejected for joint admission, never silently dropped. Preserve
the original provenance values while establishing the explicit identity mapping.

Visibility Scope is a fixed operator-authorized set, default `{public}`,
passed from the overall reviewed binding. It is not authored authorization,
a natural-language request, an implicit hierarchy or a new per-user role model.
Filter before lookup, graph expansion, Evidence selection and citation output;
do not merely redact afterward. Every required Policy must be in scope.
Out-of-scope closure refuses, without returning hidden text/titles/topology to
readers. Authorized operator review may inspect its own candidate normally.

## 5. Additive SDK contract

The profile SDK is the sole producer definition for these concepts. Public
Python call/type spellings may follow repository conventions, but the following
required inputs, outputs and guarantees are the consumed version-1 contract:

- **Candidate inspection:** an exact captured Authoring Revision/subtree,
  expected namespace and selected profile; returns structural/dependency
  diagnostics and captured digests, always labeled unadmitted. It cannot be
  used as a served Context Snapshot or grant publication authority.
- **Published Context opening:** a native immutable-version-pinned local/S3
  Location, full expected Context Identity and operator-authorized Visibility
  Scope. No omitted-version/current fallback. Resolve, validate and compare all
  expected identity components before returning a usable SDK Context Snapshot.
- **Context Snapshot view:** immutable identity, scope-filtered full page views,
  typed Context Bindings and complete required Policy views with exact citations.
  Existing search/page/term consumers can use this view without an alternate
  knowledge store, lossy export or independent interpretation of required edges.
- **Page/Citation view:** KB Namespace, Entity ID, kind, original relative path,
  full source content/body, supported typed native metadata, canonical provenance,
  exact Published Version/fingerprint and stable passage/line coordinates.
  Citations never substitute a storage URI or private Source Artifact URL.

Context Identity contains the KB Namespace, selected subtree/profile version,
immutable Published Version, canonical fingerprint, publication manifest digest,
Source Reference Manifest digest and effective scope. Fingerprint alone is
insufficient: existing native source-reference controls are separately bound.

The view never exposes unfiltered underlying KB state as the reader shortcut.
Missing, corrupt, incompatible or identity-mismatched content is a specific
refusal, not an empty successful result or a switch to latest. Distinguish
unsupported profile, malformed profile, unresolved reference, unavailable
snapshot, identity mismatch, out-of-scope dependency and unadmitted input.
Reader-safe diagnostics and complete/refused semantics survive all adapters.

Ordinary native SDK operations remain available. New profile facilities are
additive and selected explicitly; no existing positional signature, generic
exchange format, plain filesystem-read meaning or optional MCP role is silently
repurposed. No SDK method executes native payload contents or grants source
inspection, publication or database permission.

## 6. Publication and coordinated activation boundary

Reuse native Git Publication Review/Admission. The overall operator review in
Ariadne binds the Lumio native review/destination/expected-current facts and
explicitly authorizes its named operation; a Git merge or generic Agent command
cannot call it as implicitly approved work.

Local and S3 Published Versions retain complete immutable version preparation,
manifest/hash verification, sealed private source bindings, native admission
receipts and expected-current activation. The profile SDK then opens the exact
resulting version. Credentials, raw sources and private binding records do not
enter the profile or public release manifest; expose only safe identity/digest
facts required by the companion binding.

Ariadne activates the integrated descriptor last. Lumio's standalone current
may have advanced after a completed native publication while overall admission
later fails; report that truthfully. Integrated readers must ignore that pointer
and retain the old complete Bound Release. This design does not promise
cross-backend distributed transactions or simultaneous standalone activation.

Unchanged retry verifies existing immutable content/receipts and cannot
overwrite an advanced expected-current pointer. A new overall review is needed
when reviewed facts change. No automatic cleanup, destructive rollback or
migration of the real configured KB follows from a failure.

## 7. Temporal, computation and standalone semantics

Lumio `review_after` stays advisory. Native Ariadne lifecycle/freshness,
mapping evidence eligibility and Contract Observation as-of meanings are retained,
not reinterpreted as permanent validity. No per-query restamping, source fetch,
background refresh or implicit unadmission is introduced.

Policy prose and Claims never execute. A Computation annotation is descriptive;
an attester reference is not run. Actual compile, source, grain/join, numerical
and measurement provenance checks belong to Ariadne. Exact execution-version
binding and mandatory integrated-context refusal belong to the companion spec.

Plain KBs keep standalone loading, zero-index retrieval, native publication,
Git-free published reads and optional LanceDB/MCP. Ariadne standalone requires
no Lumio installation. The private app is excluded; avoid breaking existing
public API signatures. Any newly discovered necessary private-consumer/API break
requires explicit owner reconciliation, not a silent expansion of this task.

## 8. Observable acceptance and validation

| Criterion | Independent expected behavior |
| :--- | :--- |
| AC1 — native preservation | A realistic Policy and Reference fixture with full text, sources, required dependencies, identifier scope and supported evidence metadata survives author/revise/publish/exact-SDK-read. Native helpers preserve or explicitly refuse unsupported operations; no silent field loss. |
| AC2 — honest refusal | Unsupported required native fields/profile versions, duplicate metric binding, missing/wrong-kind Policy and contradictory identities refuse with actionable safe diagnostics. Generic OKF loss reports cannot count as successful profile preservation. |
| AC3 — source identity | A profile-only or Source Reference Manifest change alters the appropriate bound identity; the SDK cannot reuse a page fingerprint to hide changed source/reference bindings. Private history/raw material stays private. |
| AC4 — namespace/visibility | Exact identifiers resolve only in their declared scope; aliases/Markdown links cannot grant equality or execution. A hidden mandatory Policy blocks without leaking through search, graph or diagnostics. |
| AC5 — immutable knowledge | A changed Policy/version cannot change an opened Context Snapshot. A deliberately wrong/unadmitted version refuses even when its title or body happens to match. Local/S3 exact pins do not read current as fallback. |
| AC6 — overall fixture | Companion Ariadne retail case returns independently expected revenue 150 with exact Policy citations; failed necessary publication/activation cannot expose a partial integrated release. Numerical correctness and overall activation are consumer-owned criteria. |
| AC7 — standalone/additivity | Built base Lumio still validates/reads locally without Ariadne/DuckDB/SQLGlot/server/model/GitHub; optional profile support does not make them dependencies or alter existing plain/exchange APIs. No new privileged Agent/MCP tool exists. |

Use the companion shared fixture and adapt focused existing native preservation,
snapshot, visibility, source-reference and publication checks where sufficient.
Expectations come from the source fields, exact submitted body, declared policy
graph and independently worked retail result, not SDK output copied as expected.
No coverage campaign, automatic full-suite rerun or real-source migration is
authorized. The implementation plan assigns finite checks and required project/CI
gates, with live S3 environment authorization separate from this capture.

## 9. Scoped amendments and capture checkpoint

ADR-0030 is the specific native application-profile decision anticipated by
ADR-0026: supported Ariadne metadata can now have a native typed envelope.
It does not turn all generic OKF fields/extensions into canonical Lumio fields
or change generic Profile 1/2 loss mappings. Spec 0008/ADR-0029 continue to own
Git authoring, source privacy and Publication Admission; their original scope
did not implement or authorize #2/#76, and this subsequent design does not
retroactively expand their execution/release grant.

Vocabulary: Ariadne Context Profile, Context Binding, Policy Closure,
Visibility Scope and Bound Release are captured or linked in CONTEXT.md;
existing Namespace, Entity, Source and Published Version retain their meanings.
ADR-0030 records real producer ownership/SDK alternatives. This spec owns the
profile/SDK, and companion Ariadne spec 0029 owns the binding/consumer behavior.
Freeze exact approved document/source revisions before dependent coding; no
duplicated mutable contract or floating runtime pin is authorized.

Material design choices and complete written revision 1 are owner-approved.
The one joint implementation plan remains in
`legout/ariadne:project/plans/2026-10-18-0029-lumio-bound-governed-releases.md`.
Its existing L1 slice is now owner-approved for isolated autonomous execution,
with the exact document commits frozen before writer dispatch. A1/Q1 remain
proposed and unstarted. This amendment grants no target integration, push,
issue update, software release, production-source permission, private app adoption
or real KB publication. Earlier planning-only notices record the original
capture; they do not override this narrowly scoped subsequent L1 authorization.
