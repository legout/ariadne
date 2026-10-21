# Specification 0029: Lumio-bound governed releases

| | |
| :--- | :--- |
| **Status** | **Revision 5 — approved local G2/T2 continuation, 2026-10-20.** Owner answered “Freigabe” to the concrete written r5/plan24 proposal at commit07439a4. Sections1.4–1.5 activate that bounded scope; approved revision4 remains authoritative elsewhere. No Core S3 or target integration/publication is granted. |
| **Scoped M1 execution approval** | Owner, Ariadne Pi conversation 2026-10-19: “Plan + M1 starten (Recommended)”. Approves plan r8, local source freeze, a new GitHub M1 child of #79 and supervised M1 only via Paseo/Pi: fresh Sol/high writer, exactly M1-R/M1-P, one independent fresh Sol/high candidate review, synthetic local data/KB only. Unexpected failure stops; pause with the isolated candidate. No full A1/Q1, main integration, push, release, real sources/KB or cleanup. |
| **Historical MVP design/writing approval** | Owner, Ariadne Pi conversation 2026-10-19: selected “Umfang zuerst neu zuschneiden”, “Lokaler Metric-Durchstich (Recommended)”, “Strikte Profilgrenze (Recommended)”, then “So ausarbeiten (Recommended)” for the complete six-part local MVP design. Authorizes this isolated written revision and necessary scoped notices only. No code, runtime tests, new budget, tracker changes, target integration, push, release, production/real-KB work or cleanup. |
| **Historical full-target approval** | Owner, Pi conversation 2026-10-18 for #76 and Lumio #2: selected one Content Repository, direct Python SDK, integrated-only strict mandatory Policies, one overall human confirmation, and project-wide Visibility Scope defaulting to public. Then selected “Design freigeben (Recommended)” for the complete six-section V1 design and its capture in both repositories. The owner subsequently selected “Schriftliche Fassung freigeben (Recommended)” for both written revision-1 specifications, ADRs, glossaries and scoped source amendments, opening implementation planning. Plan approval, execution and publication remain separate. |
| **Intake** | [Ariadne #76](https://github.com/legout/ariadne/issues/76), [Lumio #2](https://github.com/legout/lumio-wiki/issues/2). |
| **Baseline** | Ariadne native `24630dbd404870f30602d66b5d5a2d53fa892f86`; accepted Lumio producer `7cdd6e89030f4f1add06d077143e9953b6258894`, tree `47ce31e965f9887a57553a1ff777567625f010e9`. The isolated document fork starts at source `5502300aca23d1afd3f49fb4f73d5fd9374a9b5a`. These are source identities, not proof of an implemented or certified MVP. |
| **Decision** | [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md), [vocabulary](../../CONTEXT.md). |
| **Companion contract** | `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md`, approved behavior revision 2, concretely accepted at Lumio7cdd6e89: owns the application profile, SDK view, knowledge identities, Policy Closure and producer preservation. This specification owns the consumer binding, overall admission and governed query behavior. |
| **Contract** | planning-contract v1; installed catalog provenance unknown. |
| **Scoped L1 authorization** | Owner, Lumio Pi conversation 2026-10-18: “Implementiere #2 autonom mit paseo subagents”, then “Freigeben und #2 starten (Recommended)”. Historical L1-only grant; producer acceptance and full-target revision-1 provenance remain preserved. |
| **Historical A1 authorization (spent)** | Owner, Ariadne Pi conversation 2026-10-19: “A1 via Paseo/Pi starten (Recommended)”. Locally freeze an isolated source/plan copy, GLM-5.3/high implements only #79, V2 once with failure stop, then independent Sol/high review. Use exact accepted Lumio7cdd6e89/fixture, preserve original documents. No Q1, software target/main integration, push, issue updates, release, production/source access, real-KB publication or cleanup. |

## 1. Scope, ownership and non-goals

Join two independently installable packages through a directly consumed,
versioned Lumio Python SDK profile. Lumio owns curated business knowledge,
Policies, terminology, Claims, Evidence and its immutable Published Versions.
Ariadne owns ODCS contracts/bindings, OSI definitions, technical observations,
measurement receipts, SQLGlot/DuckDB execution and governed metric admission.

One Content Repository holds jointly reviewed knowledge and analytics inputs.
It is not a merge of the two software repositories. A Git commit, passing
validation, authored Lifecycle or SDK object is not publication authorization,
Source Approval, mapping confirmation or independent numerical validation.

V1 adds no Context Provider service, generic OKF round-trip dependency,
automatic Policy-to-SQL compiler, ontology equivalence inference, raw-SQL
tool, proprietary proposal store, background updater, user/role management,
mandatory LanceDB or dependency from Lumio back into Ariadne. The private
Lumio application, real project migration, production access, software
publication and deployment are excluded.

Pins reproduce the admitted definition/knowledge/execution path, not necessarily
a historical number from mutable source data. Numeric replay requires separately
identified immutable data; this specification does not create such snapshots.

### 1.1 Local MVP and preserved full target

The first deliverable is a **local Metric MVP**, not completion of #76/#79.
The full-target design approved in revision 1 remains the goal; S3 consumption,
integrated multi-metric queries, Context search/page/term operations and further
Ariadne application annotations require later separately planned work. They are
not implicit capabilities of this MVP or of the accepted Lumio producer.

| Surface | Local MVP contract |
| :--- | :--- |
| Storage | Exact local immutable Published Version through the optional native SDK; no S3 consumer or mutable/current/latest read |
| Application profiles | Only supported `metric` and `policy` profiles, checked across the entire captured KB; no partially validated projection |
| Other KB pages | Ordinary Lumio pages without an Ariadne profile remain native KB content, but are not exposed as Core-validated technical references |
| Calculation | Existing `get_metric` over an admitted native metric; every served metric has one exact Context Binding and complete required Policy Closure |
| Catalog | Source-free `discover`/`list_metrics` disclose the admitted metric catalog, binding identity and the available/unavailable operations; no alternate Context store is searched |
| Other integrated Analyst operations | Explicit unsupported-operation refusal, not execution through a legacy path; this includes `query_metrics`, Context search/page/term operations, record/ad-hoc queries and live `list_datasets` |
| Operator authoring/admission | Existing bounded native proposal/Git and separate Source Approval routes; one overall confirmation still binds the complete local publication/activation operation |
| Standalone | Existing operations, missing-context warnings and Ad-hoc `context: null` remain unchanged; no Lumio requirement |

Here, local-only limits Lumio publication and SDK reading. Existing Ariadne
data-source contracts/backends and Source Approval are not redefined; the MVP
proof uses a synthetic approved local DuckDB source and grants no remote source
access or qualification of an unexecuted backend combination.

At admission, reject any other Ariadne profile kind anywhere in the captured KB,
even when no current metric refers to that page. Likewise reject unsupported
technical application fields, not just an unsupported mandatory dependency.
Physical-reference/identifier-mapping or mapping-evidence extensions and
SDK computation/executor/attester annotations are not supported by this MVP;
they cannot be smuggled into a supported kind and silently ignored. Reuse the
producer schema and applicable existing Core checks for the supported Metric/
Policy metadata; do not define a second producer schema. Ordinary metric
meaning, declared grain/dimension hints and trust/provenance metadata retain
their existing document semantics, not SQL, physical-binding or join authority.
Core-owned generated computations/observations and their existing checks are
not additional SDK application kinds and are not retired by this restriction.

These limits belong to the admitted consumer contract. The manifest and overall
preview state them explicitly; a query, authored page or Agent cannot widen
them. Unsupported operations refuse before planning, audits or SQL for that
operation, without reading legacy Context as a fallback. Required text, source,
semantic, consent, integrity and response-budget guarantees are not deferred.
No consumer-supporting public package release, private-app integration or
production qualification follows from this source-pinned local deliverable.

### 1.2 Local Q2 continuation — 2026-10-20

Owner instruction in the current BB conversation: implement #80 autonomously,
then “Ok. kümmere dich erst um die unerfüllte Voraussetzung”. Together with the
confirmed Git/local standard and secondary S3 priority, execute the local A1
prerequisite in bounded slices. This first slice delivers the existing full-target
multi-metric and live-catalog requirements from §6 and AC3–AC5/AC7–AC9; it does
not activate the unrelated deferred features or change the producer contract.

For a newly validated/admitted local release, `query_metrics` supports multiple
predefined native metrics. Before planning, relationship audits, bind or SELECT,
resolve every requested metric's exact SDK binding and complete required Policy
Closure in the one pinned snapshot. Reject incomplete, mismatched, hidden or
unsupported context before those live operations. Complete combined mandatory
context must fit the existing response/transport bounds; never execute first and
then discover that necessary context cannot be returned. Preserve existing
request validation, native planner/graph/grain/join/source/deadline controls,
per-metric context association, exact citations, data signals and independent
attestation caveats. Shared Policy content may be deduplicated only without
losing those associations; no new output contract or ranking system is required.

`list_datasets` retains its native approved live-catalog semantics and Source
Approval; it is not described as source-free and performs no additional contract
inspection. Update truthful supported-operation disclosure for only these two
operations. Existing bindings do not acquire support in place: changed consumer
build/support requires fresh validation and matching overall admission. All
remaining r2 unsupported operations and unsupported profile kinds still refuse.
Standalone behavior and the optional SDK boundary remain unchanged.

Independent acceptance: synthetic completed orders100+50 and cancelled25 give
revenue150 and completed-order count2, with complete per-metric SDK context and
exact version-qualified citations. If combined required context exceeds the
configured response budget even though one metric alone fits, refuse before
planner/live audit/bind/SELECT. Preserve applicable native catalog and M1
integrity/consent/standalone checks, changing only the superseded operation
refusals. One focused invocation and independent candidate review are assigned
in the reconciled plan; failed checks stop without automatic retry. No S3,
navigation, Reference, ad-hoc or Agent/Tau support is introduced by Q2.

### 1.3 Approved local A2 navigation continuation — 2026-10-20

Owner answered “ja” after reviewing the concrete companion navigation contract
and being asked to authorize autonomous L2 → A2 implementation. Companion
spec0009 approved navigation amendment r3 owns the SDK schema and operations;
this section owns the Core behavior. Q2 remains accepted in the isolated
candidate, not integrated software. Source/role/visibility/consent and build
identity invariants remain those of §§3–6. No new architecture/terms are needed.

Enable `list_context_pages`, exact `read_context_page`, `search_context` and the
`discover` pages group using only the accepted local version-pinned scoped SDK
facade. Navigation includes visible ordinary unprofiled documentation alongside
profiled pages; it never marks an ordinary page as a Core-validated Reference.
Keep existing Core outer list/read/search fields and response limits, adding
Bound Release/SDK namespace, Entity ID, Published Version and exact page/passage
citations. Ranking is native Lumio lexical search, not legacy Core ranking or
another engine. Preserve SDK-provided canonical content, verbatim passages and
coordinates. Missing advisory metadata stays unknown/advisory rather than
inventing verification, freshness or numerical attestation. Source registry,
private artifacts and hidden-page metadata remain undisclosed.

All navigation is source-free and uses the Query/Discovery session's pinned
release and operator-authorized scope. No fallback to legacy context_layer,
mutable checkout, raw/unscoped SDK snapshot, YAML reparsing or moving pointer.
Missing SDK capability/build, mismatched identity and unadmitted/unsupported
inputs refuse explicitly. Source construction is not needed for these operations;
existing role restrictions stay intact. `resolve_term`, technical Reference
profiles, record/ad-hoc operations and S3 consumption remain deferred/refused.
Changing supported operations or SDK/consumer build requires new matching
validation and overall admission; never mutate an existing served manifest.

Independent acceptance: publish/admit visible ordinary documentation whose
text deliberately differs from a legacy page. List/read/search/discover return
only the authorized SDK text/identity and real passage, never the legacy body
or a hidden same-token page. Source construction raises if reached. Preserve
outer shapes, source-free startup/role boundaries and the accepted Q2 behavior.
Required output too large for the existing limits refuses without elision.
The plan assigns the focused A2 check plus affected existing MVP/wrapper checks.

### 1.4 Approved G2 — Git/local operator disclosure

The standard path is one shared Git Content Repository with local sync.
`ariadne status` remains read-only and source-free: it does not fetch, merge,
measure, query a source, publish, grant approval or activate anything.
For an integrated project it additionally reports the local full Git HEAD
separately from the already admitted Content Commit. An unborn HEAD is unknown,
never an invented revision. New integrated information is additive to existing
status sections: the admitted Bound Release digest, its exact immutable local
Published Version and its declared supported operations come only from the
verified admission. Do not turn unverified descriptor fields into active facts.

Keep the existing diagnostic states `none`, `invalid` with a reason, and `valid`.
A stale/build-mismatched, malformed or unverifiable admission cannot produce
ready/valid integrated status. Missing admission is distinct from an invalid
one. No new SDK import is required on the standalone status route. Status output
adds no raw Source, private registry, credential or source-object disclosure.

The operator guide shows existing clone/fetch/fast-forward, native candidate
reconcile, Source Approval if needed, validation, composite preview, explicit
confirmation and source-free discovery. It introduces no sync wrapper or
second admission command. Git sync alone preserves the active descriptor and
already-open session pin; only a newly reviewed/confirmed admission changes
what a new session serves. Existing role exclusions and native failures apply.

Independent acceptance: admit synthetic revision A, fast-forward a local clone
from a disposable local Git remote to B, then observe local HEAD B versus
admitted A. Descriptor bytes and an existing source-free session stay on A.
After the ordinary reviewed B admission, a new session sees B. This proves
activation isolation without calculating revenue again.

### 1.5 Approved T2 — validated technical Reference and term resolution

Extend the integrated profile subset from `metric, policy` to
`metric, policy, reference` ONLY after complete native Core validation of every
newly supported Reference annotation across the captured candidate. Reuse
spec0010's structured Reference/Resource/mapping contract, spec0011's advisory
trust signals, existing authentic inspection receipts and human confirmation.
SDK preservation or an authored `verified`/`ariadne_evidence` value cannot
create Core evidence, grant Source Approval, confirm a mapping or authorize a
join. Dataset/table/computation/skill profiles and unrelated extensions remain
unsupported; no generic profile widening or silent projection is permitted.

Curated Reference content has one maintained source: the KB. Consume the
producer-validated native metadata and immutable SDK page identity. No second
curated `context_layer/` copy, Core-side KB YAML parser or alternative matching
engine is introduced. Core-owned generated observations retain their existing
ownership and validation. Existing producer SDK interfaces are sufficient;
a newly discovered public SDK contract gap returns for a scoped amendment.

Measurement stays explicit through the existing Core inspection operation on
operator-approved synthetic sources. Use the same declared mapping candidate
and native candidate/endpoint/source/OSI/Policy identity checks. Native receipt
records stay in the existing proposal evidence area; integrated validation
verifies them under the current age/dependency rules before attaching their
Core-owned summaries. Inline SDK evidence alone never satisfies receipt
verification. Any required generated-metadata change is an explicit candidate
edit and new final Content Commit, preserving the curated body/profile identity
through the existing producer write contract; it cannot mutate an admitted KB.

The composite preview and its digest bind exact human mapping selections to
the reviewed Reference path, assertion, endpoint correspondence and verified
receipt identities. Retain the existing selection syntax and confirmation
semantics; no second confirmation store or Agent/MCP admission permission is
added. No selection means unconfirmed. Changed declaration, endpoints, source,
evidence, expiry or relevant build requires existing native revalidation and
cannot inherit a current confirmation merely from a stable title or Entity ID.

`resolve_term` then uses the one pinned SDK release and operator scope. Reuse
native exact term/qualified-field matching, stable ordering, ambiguity,
confirmation/freshness disclosure and bounded part/byte semantics. Filter scope
before matching/counting/citations; all cited identities and passages identify
the same Published Version and Bound Release. Missing metadata stays unknown.
No legacy-root fallback, inferred equivalence, transform execution or join
permission follows. Whole-operation response guards and role exclusions remain.
A changed support set requires fresh matching validation/overall admission;
existing releases are never upgraded in place. Standalone behavior is preserved.

Independent acceptance: explicitly adapt the submitted golden Reference in a
synthetic proposal (never rewrite the baseline fixture). Produce real native
inspection receipts against declared local fields, verify the complete
candidate and serve a scoped unconfirmed mapping. Confirm exactly the reviewed
asserted mapping through ordinary human admission and observe confirmed status.
A changed endpoint/dependency or receipt must refuse or become unconfirmed under
the native rules; the old confirmation cannot remain current. Assert exact
Resource/column identity and SDK version-qualified citation. Preserve a
producer-valid unsupported profile as the global refusal oracle.

These two local continuations do not implement Core S3, ad-hoc/record queries,
Agent/Tau integration, a service, production-data access, historical numerical
replay or a package release. Original full-target S3 acceptance remains deferred
and must not be marked complete by these local results.

## 2. One authored revision

Ariadne's project is the Git worktree root; Lumio's Knowledge Base is the
`knowledge/` subtree. Keep existing Core paths such as `ariadne.yaml`,
`contracts/`, `contract_bindings.yaml`, `semantic_layer/`,
`context_layer/` and `answer_examples/`. The KB contains its native
`lumio.yaml`, `.lumio-authoring.yaml` and Compiled Pages.

A new authored `context_integration.yaml` selects version 1, integrated mode,
the `knowledge/` subtree, expected KB Namespace and `ariadne-context/1`.
It carries portable selectors, never credentials, private registry locations,
publication destinations, active pointers or a human-approval flag.
Absence retains the existing standalone route; malformed or unsupported
integration configuration refuses rather than downgrading to standalone.
An existing integrated runtime cannot be downgraded by a query/tool argument.

A candidate is one exact full Git commit over both applicable input scopes.
Joint validation binds captured commit bytes from both scopes, including all
inherited dependencies and integration configuration. A page-only edit cannot
skip inherited OSI, ODCS, source or evidence checks. Operational candidate
evidence must bind the KB input and source-reference digests even when Core
and Lumio retain different native materializations.

Use one selected native branch/worktree, ordinary Git diff and the existing
revision-checking disciplines. An Agent may propose a contract, model and
related knowledge in this same revision through the applicable bounded
authoring/native Git surfaces. It cannot approve, publish, activate, widen
source access or create a second application-owned draft record.

Core-generated technical pages remain Core-owned. Curated knowledge has one
maintained source in Lumio; no bidirectional synchronization or independently
editable mirror in `context_layer/` is introduced. Derived immutable snapshots
and in-memory adapter views are not additional authoring sources.

## 3. SDK consumption and exact identities

The optional integrated dependency is the Lumio SDK implementing the companion
profile; standalone Core imports/installs without it. Both packages retain
Python >=3.14. Optional MCP adapters retain the agreed compatible resolved
SDK 2.x pairing; MCP is not the integration data plane.

The local MVP uses native PublishedFilesystemLocation with an explicit immutable
version, followed by the profile's identity-checked SDK view. An S3 destination
or reader location refuses explicitly before publication or local-path coercion;
S3Location consumption is a deferred full-target capability. Never treat a plain
mutable FilesystemLocation, unadmitted captured revision, `current`, `latest`
or a branch name as served knowledge. Candidate inspection is separately labeled
and cannot produce a governed runtime.

Keep exact typed identities, not a synthesized universal string namespace:

- knowledge: KB Namespace plus Entity ID, bound to a Published Version;
- analytics: native model/metric identity and source-qualified physical Resource;
- contract: producer identity/version and scoped schema/property identifiers;
- ontology: explicit declared namespace, target identifier and immutable revision.

Validate each cross-reference in its owning scope and the combined revision.
Existing `ariadne://` resource spelling and ODCS producer bytes remain intact.
Aliases/titles select investigative leads, never establish equality, substitute
identifier values, confirm a Mapping or authorize a join. Existing mapping
evidence and explicit human confirmations must still match their exact
declarations, scopes and dependencies. The MVP does not accept SDK Reference/
Mapping annotations as a shortcut around those rules: its strict profile gate
refuses them. Native Core validations remain applicable and unchanged.

Native candidate validation uses the captured Control File, including its
producer-owned versioned ontology catalog. Reuse the SDK's authoritative
captured-candidate validation; do not run a second profile pass against an empty
or caller-provided catalog. A valid captured catalog must not become invalid
through the adapter.

## 4. Bound Release manifest and Visibility Scope

A Bound Release is the immutable binding produced by overall admission. Its
credential-free manifest contains:

| Binding | Required facts |
| :--- | :--- |
| Contract | manifest version 1, producer profile `ariadne-context/1`, explicit local consumer operation/profile support, content full commit, selected subtrees and joint input digests |
| Ariadne | admitted commit and native artifact digest; source declaration/effective identity digests; exact ODCS documents/bindings/schema-profile identities and OSI/graph identity |
| Lumio | KB Namespace, immutable Published Version, canonical fingerprint, publication manifest digest, Source Reference Manifest digest and profile identity |
| Context | metric-to-Entity bindings, complete required Policy identities/content digests and effective Visibility Scope, all derived from the reviewed inputs |
| Evidence | exact native validation/review/measurement references and digests with real as-of scope; no fabricated fresh timestamps |
| Execution | exact Ariadne and Lumio build identities and the resolved relevant compiler/execution dependency identities, including SQLGlot and DuckDB |
| Reviewed operations | exact native review digests, targets and expected previous states; actual execution receipts/confirmation evidence are attached separately to the admission record |

Package version and import path alone are insufficient: editable code can
change in the same tree without changing either. Bind actual relevant build/
content identities, including the Ariadne consumer, Lumio SDK and resolved
compiler/execution dependencies. Incompatible or unmatched identities require
explicit revalidation/admission, not a silent new implementation. This is not
a claim of hermetic OS or data replay.

Before an integrated read, verify the manifest's own deterministic digest and
cross-check its commit, artifact/source identities, selector, consumer support,
metric/Policy bindings and scope against the verified Core admission and its
immutable inputs. Also verify the exact SDK identity/location/version. An
integrated selector with a missing Bound Release cannot become standalone;
a self-consistent Lumio pin cannot authorize a different Core revision. Treat
missing, malformed or mixed fields as refusal, not a weaker default.

The publication-manifest digest and Source Reference Manifest digest are
separate identities. Native receipt field names retain their producer meaning;
a receipt's `manifest_digest` must not be mistaken for the immutable Published
Version's publication-manifest digest or the Bound Release's own digest.

The resolved manifest is a derived operational artifact created after the
Content Commit. It is not authored back into that same commit or a self-SHA
placeholder. Its deterministic digest excludes its own digest and incidental
wall-clock fields. Preview binds planned immutable identities and native review
digests, not receipts that do not yet exist. Actual native receipt references,
overall confirmation and admission times are separate facts attached to the
final admission record after they have been verified against the reviewed
binding; they cannot change the manifest or form a self-referential consent hash.

Visibility Scope is operator-authorized, project/release-bound and defaults to
the explicit set `{public}`. Authored content cannot expand it; query inputs,
tool arguments and model prompts cannot select another scope. There is no
implicit public/internal/restricted hierarchy. A later operator restriction can
deny access; it cannot silently relabel or widen a release.

Scope applies before lookup, search, term resolution, graph expansion, citation
assembly and output. Every required Policy must be readable in the same scope;
an invisible dependency is not skipped. Reader diagnostics must not leak the
hidden page's content, title or topology. Native private Source Registries and
raw artifacts remain outside Git, public release records and query output.
The manifest binds safe digests, not private manifest bodies or storage keys.

## 5. Overall Admission

Expose an operator-only overall preview/confirmation using the existing
human admission boundaries. No Agent role or MCP tool receives this capability.

1. Capture one final Content Commit. Run the applicable native and joint
   validation against those bytes. Source Approval/effective endpoint checks
   precede any approved live validation; the overall command cannot grant them.
2. Preview the exact Core candidate/review, Lumio publication review and targets,
   both expected native active states, expected current Bound Release, effective
   scope, execution identities, evidence applicability and joint manifest.
   All automatic native side effects must be named before confirmation.
3. One explicit human confirmation authorizes exactly that displayed composite
   review. Recheck revision, digests, validator contracts, current-state
   expectations, permissions and evidence eligibility. A changed fact or expired
   eligible validation requires a new matching review, never silent consent.
4. Complete and verify Lumio's native Publication Admission and exact SDK reader
   identity. Complete Core preparation/admission checks. Persist necessary
   immutable artifacts/receipts before activation.
5. Publish the extended Core admission descriptor last, atomically, with the
   Bound Release manifest/digest and its exact knowledge pin. Reuse
   `.ariadne/current.json` as the integrated activation authority; do not add a
   third workflow database or alternate active pointer.

A failure before step 5 leaves the previous integrated descriptor serving its
previous complete binding, or no integrated runtime for first admission.
Native Lumio publication may already have completed and its standalone current
pointer may have changed: that was a separately disclosed part of the confirmed
operation. Incomplete overall admission never makes that version an integrated
release. Report observed receipts/residue accurately; do not secretly delete,
roll back or relabel it.

Expected-current checks prevent stale confirmation or concurrent activation
from overwriting newer state. A retry verifies existing immutable identities
and receipts, never rewrites them or reactivates an old version over an advanced
pointer. Recovery continues only still-authorized work under matching facts;
otherwise a new preview/confirmation is required.

Rollback is another explicit reviewed overall activation, with current source,
execution and applicable evidence checks. It neither grants permissions nor
rewrites historical artifacts. No cross-system distributed transaction,
all-standalone-reader simultaneity or production rollout automation is promised.

## 6. Governed runtime and adapters

An integrated Query Session resolves one complete Bound Release and retains it
for its lifetime. Use the exact SDK Published Version, not its changing current
pointer. Existing source-approval revocation, endpoint, snapshot-integrity and
live execution gates still bind; pinning is not permission to ignore them.

Every integrated metric has exactly one explicit profile Context Binding,
including an explicit `required_policies` list (which may intentionally be
empty). Resolve the complete transitive Policy Closure in that same snapshot.
Finite repeated references are deduplicated by exact identity; a finite cycle
does not create new authority or excuse missing nodes. Never traverse arbitrary
Markdown links, generic Claims, Source URLs or external references as mandatory
Policies. Native provenance `sources` and typed Policy dependencies are distinct.

Before SQL execution, refuse missing/unadmitted/mismatched Knowledge, incomplete
or out-of-scope Policy Closure, corrupt binding, unsupported profile or incompatible
relevant execution identity. Also retain existing source, compile, contract,
grain, join, deadline and result-budget refusals. Do not execute first and
then discover that mandatory context cannot be supplied.

Return full required metric/Policy content and existing caveats, plus additive
Bound Release identity and snapshot-qualified Entity/path/passage citations.
Use the existing shared trust/freshness interpretation for supported native
metadata and actually consumed Core technical observations. Preserve
`context_signals`, source-quality warnings and missing independent-numerical-
validation/`attestation: pending` disclosure where applicable. Document
Verification, human admission and compiled execution remain distinct; no
successful query or stored attester invents a current numerical proof.
If existing result limits prevent complete required context, refuse rather
than elide Policies. Do not claim Policy narrative was mechanically proved
equivalent to the sanctioned OSI expression.

Existing wrappers preserve native results and refusals without new privileged
tools; broad adapter/installed-package qualification remains separately planned.
For the MVP, only `get_metric` calculates; `discover`/`list_metrics` disclose the
admitted catalog and explicit consumer capabilities without live source reads.
Other integrated Analyst operations refuse as specified in §1.1, even if the
same callable continues to work standalone. Never return empty success to hide
an unavailable capability, search `context_layer/` instead, or expose an
unvalidated subset of SDK annotations.

The deferred full target includes integrated bounded page reads, Context search,
term resolution and multi-metric answers over the same pinned SDK view/scope,
preserving existing limits, passage pointers, ambiguity and mapping-confirmation
semantics. Its `list_datasets` retains the approved live-catalog behavior without
extra contract inspections. These remain requirements for later work, not MVP
support claims. No independent ranking project or generic filesystem reader is
authorized. Candidate browsing remains unadmitted and cannot execute governed
metrics.

Standalone behavior is unchanged, including non-failing missing-context
warnings and Ad-hoc `context: null`. Switching off integration is an explicit
project change/new admission, never a per-request fallback after SDK failure.
Lumio `review_after` and Ariadne advisory lifecycle/expiry remain advisory.
New admission enforces applicable contract/mapping evidence eligibility; no
background expiry/unadmission or permanent live-data conformance claim is added.

## 7. Observable acceptance and lean validation

The local MVP must meet the MVP column below. The preserved full-target column
records what is still required for the complete #76 design; a local MVP pass
cannot close #76/#79 or imply the deferred capabilities passed.

| Criterion | Local MVP — independent expected behavior | Preserved full target |
| :--- | :--- | :--- |
| AC1 — one revision | One synthetic Content Commit contains an actual new ODCS contract/binding, OSI metric and Lumio Policy/page. Applicable inherited and edited dependencies are validated together. No Agent confirmation or Git commit alone publishes it. | Same joint-revision requirement across later capabilities |
| AC2 — truthful profile | Full supported Metric/Policy metadata, body, sources and scope survive the native path. Reject every unsupported Ariadne kind/technical extension, including an otherwise unreferenced Reference profile. Ordinary unprofiled KB pages remain native content. | Additional supported SDK annotations, physical references, mappings and authentic evidence require their complete Core-owned validation; producer preservation remains companion AC1–AC3 |
| AC3 — bound answer | Approved synthetic orders 100+50 completed, 25 cancelled; an explicitly authored cancellation Policy and sanctioned OSI filter independently imply 150, not 175. Return full required Policies, exact citations, advisory signals and actual pending independent-validation caveats. | Same honesty for additional query surfaces |
| AC4 — explicit refusal | Missing/unadmitted/mismatched knowledge, damaged manifest, mixed Core/KB pin, hidden required Policy or changed relevant build content fails before SQL. Alias/title similarity grants no authority. | Same gates for all later operations |
| AC5 — historical isolation | A later candidate/Published Version cannot change an existing local binding. Query sessions pin a complete verified release; actual mutable-data/as-of limitations remain explicit. | Same isolation for S3 and other supported query surfaces |
| AC6 — activation safety | Fail necessary local publication/SDK verification or final activation: keep the prior complete integrated descriptor, report actual native receipts/residue, and reject stale expected full binding/native states on retry. | Native consumer S3 publication/open/failure behavior and required S3 qualification are deferred, not proved by an SDK-only S3 seam |
| AC7 — standalone and roles | Core standalone needs no Lumio; existing standalone operations and source/role gates remain. Project-bound scope cannot be widened; hidden dependencies are not leaked. Unsupported integrated Analyst operations refuse without legacy execution. | Additional adapters/operations retain these invariants and their own required qualification |
| AC8 — evidence honesty | Actual local SDK/build/content identity, native digest meanings and complete composite consent are verified. No receipt substitutes for review or creates numerical attestation. Unexecuted/unsupported scenarios remain explicit. | Installed/distribution pairing and later adapters/S3 require separately authorized qualification |
| AC9 — capability boundary | Source-free admitted `discover`/`list_metrics` disclose support accurately. `query_metrics`, Context page/search/term operations, record/ad-hoc queries and live `list_datasets` explicitly refuse in integrated MVP mode. | Later planned implementations must use the pinned SDK view and preserve their documented response/limit semantics; enabling them requires new matching admission |

Plan one shared small fixture and reuse relevant existing native checks.
New tests need these named reachable failures and independently derived
expectations, not a per-method matrix. Producer and consumer may share
contract fixtures without deriving expected values from implementation output.

Keep the exact accepted upstream three-file baseline and provenance unchanged.
It contains an Ariadne Reference profile and is therefore not itself an
admissible strict-MVP candidate. Any task-specific adaptation/removal of that
unsupported annotation must be an explicit candidate edit visible in the
joint Git review, never a hidden conversion or producer-fixture rewrite.
The upstream Returns Policy is not a cancellation rule: author the additional
Policy and matching OSI filter explicitly. Example counts/dummy digests are not
authentic measurement receipts. The joint journey must include the actual
ODCS document/binding, not merely an unrelated previous ODCS test pass.

The historical A1 V2 ran once: 3 passed/6 failed, followed by its owner-advanced
read-only fix-first review. Its deeper journey assertions were unreached.
Preserve that WIP and evidence; this scope revision neither repairs it nor
resets its spent budget. Relevant producer evidence remains reusable; it is
not a consumer runtime pass. S3 remains outside this local MVP; no service or
credentials are authorized. Design capture alone authorizes no runtime test,
full suite, wheel matrix, live Agent run or remote campaign. The subsequent
separate M1 grant assigns only plan r8's exact focused checks/evidence reuse;
project/CI gates remain binding and no broader qualification is authorized.

## 8. Scoped amendments and handoff

This is the opted-in consumer exception to ADR-0011/spec 0011's non-failing
Context fallback and direct-only consumption: mandatory typed Policy Closure
is strict only in the integrated mode. Unrelated advisory metadata does not
become a refusal. Standalone semantics and existing source/semantic safety remain.

Spec 0027's native inventory/validation is extended only for the joint input
scope and integration selector; its prohibition on independent draft stores,
automatic authority and real project reset remains. Spec 0028's ODCS pin,
limited profile, original-time evidence reuse and admission checks are reused,
not replaced by Lumio knowledge or Policy admission.

Companion Lumio spec 0009 and ADR-0030 own the additive producer profile/SDK.
Do not fork a second editable definition of that schema in this repository.
Freeze exact approved specification revisions/commits before dependent coding;
cross-repo path references in this uncommitted written design are not runtime
floating-main pins.

Capture checkpoint: existing glossary terms remain sufficient; local MVP is
a delivery scope, not a new domain entity. ADR-0026 retains the repository/SDK/
admission decisions and records the scoped refinement; no new ADR is warranted
for reversible delivery staging. The Lumio companion contract/producer remain
unchanged. Scope, non-goals and AC1–AC9 are above. Material design choices were
approved in chat on 2026-10-19; the owner then approved **this written revision
2 and scoped notices** with “Schriftlich freigeben (Recommended)”, authorizing
local implementation planning only.

The [joint implementation plan](../plans/2026-10-18-0029-lumio-bound-governed-releases.md)
records the separately owner-approved M1 execution boundary. Before dispatch,
freeze these sources, publish/fetch the new canonical M1 child and verify its
host/environment. The prior V2/review allocation stays spent; M1's two checks
and one new review are not a reset or borrowed Q1 budget. Do not silently
narrow/close existing full-target issues. Only the new M1 tracker publication
and its parent/dependency metadata are authorized. Protected original
documents, source freezes, WIP and evidence remain intact. The old six Lumio
design-document bytes are retained in the separately approved archive
`62bb41c36ce7afdfce9fbfe8f25ac45b7fa62a79`; their removed worktree is not a runtime
dependency. The exact accepted producer pin remains required; no floating main
or public 0.2.0 version label substitutes for it.
