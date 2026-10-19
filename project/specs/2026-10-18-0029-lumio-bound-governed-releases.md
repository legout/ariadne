# Specification 0029: Lumio-bound governed releases

| | |
| :--- | :--- |
| **Status** | **Approved behavior, written revision 1.** Scoped A1/#79 implementation is owner-approved on 2026-10-19; no Q1 or target integration/publication authority. |
| **Approval** | Owner, Pi conversation 2026-10-18 for #76 and Lumio #2: selected one Content Repository, direct Python SDK, integrated-only strict mandatory Policies, one overall human confirmation, and project-wide Visibility Scope defaulting to public. Then selected “Design freigeben (Recommended)” for the complete six-section V1 design and its capture in both repositories. The owner subsequently selected “Schriftliche Fassung freigeben (Recommended)” for both written revision-1 specifications, ADRs, glossaries and scoped source amendments, opening implementation planning. Plan approval, execution and publication remain separate. |
| **Intake** | [Ariadne #76](https://github.com/legout/ariadne/issues/76), [Lumio #2](https://github.com/legout/lumio-wiki/issues/2). |
| **Baseline** | Ariadne `24630dbd404870f30602d66b5d5a2d53fa892f86`; Lumio Wiki `31b6a3e1ef8d04a968b8605128efbdb519396aa7`. These identify inspected source, not a newly certified runtime pairing. |
| **Decision** | [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md), [vocabulary](../../CONTEXT.md). |
| **Companion contract** | `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md`, approved behavior revision 2, concretely accepted at Lumio7cdd6e89: owns the application profile, SDK view, knowledge identities, Policy Closure and producer preservation. This specification owns the consumer binding, overall admission and governed query behavior. |
| **Contract** | planning-contract v1; installed catalog provenance unknown. |
| **Scoped L1 authorization** | Owner, Lumio Pi conversation 2026-10-18: “Implementiere #2 autonom mit paseo subagents”, then “Freigeben und #2 starten (Recommended)”. Historical L1-only grant; behavioral revision 1 is unchanged. |
| **Scoped A1 authorization** | Owner, Ariadne Pi conversation 2026-10-19: “A1 via Paseo/Pi starten (Recommended)”. Locally freeze an isolated source/plan copy, GLM-5.3/high implements only #79, V2 once with failure stop, then independent Sol/high review. Use exact accepted Lumio7cdd6e89/fixture, preserve original documents. No Q1, software target/main integration, push, issue updates, release, production/source access, real-KB publication or cleanup. |

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

Use native PublishedFilesystemLocation or S3Location with an explicit immutable
version, followed by the profile's identity-checked SDK view. Never treat a plain
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
declarations, scopes and dependencies.

## 4. Bound Release manifest and Visibility Scope

A Bound Release is the immutable binding produced by overall admission. Its
credential-free manifest contains:

| Binding | Required facts |
| :--- | :--- |
| Contract | manifest version 1, profile `ariadne-context/1`, content full commit, selected subtrees and joint input digests |
| Ariadne | admitted commit and native artifact digest; source declaration/effective identity digests; exact ODCS documents/bindings/schema-profile identities and OSI/graph identity |
| Lumio | KB Namespace, immutable Published Version, canonical fingerprint, publication manifest digest, Source Reference Manifest digest and profile identity |
| Context | metric-to-Entity bindings, complete required Policy identities/content digests and effective Visibility Scope, all derived from the reviewed inputs |
| Evidence | exact native validation/review/measurement references and digests with real as-of scope; no fabricated fresh timestamps |
| Execution | exact Ariadne and Lumio build identities and the resolved relevant compiler/execution dependency identities, including SQLGlot and DuckDB |
| Reviewed operations | exact native review digests, targets and expected previous states; actual execution receipts/confirmation evidence are attached separately to the admission record |

Package version alone is insufficient where distinct editable/build trees share
a version. An execution identity must distinguish those trees; incompatible or
unmatched relevant execution identities require explicit revalidation/admission,
not a silent new compiler. This is not a claim of hermetic OS or data replay.

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
If existing result limits prevent complete required context, refuse rather
than elide Policies. Do not claim Policy narrative was mechanically proved
equivalent to the sanctioned OSI expression.

Existing CLI/Python/MCP/Agent wrappers preserve these native results without
new privileged tools. Integrated discovery, bounded page reads, context search
and term resolution use the same pinned SDK view and scope; preserve existing
limits, passage pointers, ambiguity and mapping-confirmation semantics.
No independent ranking project or generic filesystem reader is authorized.
Candidate browsing remains explicitly unadmitted and cannot execute governed
metrics. Offline discovery stays source-free; `list_datasets` retains its
approved live catalog semantics without extra contract inspections.

Standalone behavior is unchanged, including non-failing missing-context
warnings and Ad-hoc `context: null`. Switching off integration is an explicit
project change/new admission, never a per-request fallback after SDK failure.
Lumio `review_after` and Ariadne advisory lifecycle/expiry remain advisory.
New admission enforces applicable contract/mapping evidence eligibility; no
background expiry/unadmission or permanent live-data conformance claim is added.

## 7. Observable acceptance and lean validation

| Criterion | Independent expected behavior |
| :--- | :--- |
| AC1 — one revision | One synthetic Content Commit contains a new ODCS contract/binding, OSI metric and related Lumio Policy/page; full candidate review covers inherited and edited dependencies. No Agent confirmation or Git commit alone publishes it. |
| AC2 — truthful profile | Supported metadata, full Policy body, sources, scope, explicit mappings and evidence survive native author/read/revise/publish/read. Unsupported required content refuses with diagnostics, not generic OKF field loss. Producer details belong to companion AC1–AC3. |
| AC3 — bound answer | A reviewed/confirmed release queries the approved retail fixture: completed orders 100 and 50, cancelled order 25; a Policy excludes cancelled orders and sanctioned OSI expresses that filter. Expected revenue is independently 150, not raw 175, with full Policy text and exact citations. |
| AC4 — explicit refusal | Missing, wrong, unadmitted, corrupt or scope-ineligible required knowledge fails before SQL. Title/alias similarity and unconfirmed identifiers cannot establish a binding or bypass existing grain/join/source gates. |
| AC5 — historical isolation | A later candidate or Published Version changes the Policy but cannot alter an existing bound path; deliberate mixed pins refuse. Live data can still change, and the result discloses its actual scope/as-of facts. |
| AC6 — activation safety | Fail a necessary local/S3 publication or final activation step: integrated readers see the prior complete Bound Release, never a mixed release. Disclose actual native residue. Retry/stale expected-current cannot overwrite advanced state. |
| AC7 — standalone and roles | Core standalone works without Lumio installed; Lumio works without Ariadne. Existing role/tool exclusions remain. Integrated scope cannot be widened by a caller; hidden dependencies cannot leak through diagnostics/graphs. |
| AC8 — evidence honesty | Pins bind actual built/installed identities and native source-reference digests, not just page fingerprints/version labels. Scope, unavailable capabilities and unexecuted scenarios are explicit; no live-model, production or full-ODCS claim follows. |

Plan one shared small fixture and reuse relevant existing native checks.
New tests need these named reachable failures and independently derived
expectations, not a per-method matrix. Producer and consumer may share
contract fixtures without deriving expected values from implementation output.

Use existing isolated S3-compatible failure seams where adequate; any live test
service requires explicit environment/scope authorization, never production
credentials. No full-suite, wheel matrix, live Agent run or broad remote
campaign is authorized by this design capture. Project/CI gates remain binding;
the implementation plan must assign commands, evidence reuse and a finite budget
before execution.

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

Capture checkpoint: Content Repository, Context Binding, Policy Closure,
Visibility Scope and Bound Release are captured in the owning glossaries.
ADR-0026 records the genuine repository/SDK/admission trade-offs; the Lumio
companion owns the producer decision. Scope, exclusions and AC1–AC8 are above.
The owner has approved the material design choices and this complete written
revision 1. The [joint implementation plan](../plans/2026-10-18-0029-lumio-bound-governed-releases.md)
now records the subsequent scoped A1/#79 approval and local source freeze.
Only the isolated GLM-high implementation, one V2 invocation and independent
Sol-high review are authorized; Q1, source permission, real-KB access,
software target integration/push/release/migration and cleanup are not.
Original design worktrees remain untouched. The accepted Lumio producer is
pinned exactly; no floating-main runtime pin is introduced.
