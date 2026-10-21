# Specification 0008: Git-native Knowledge Authoring

**Subsequent separate design (owner, 2026-10-18):** [spec 0009](2026-10-18-0009-ariadne-context-profile.md)/[ADR-0030](../adr/0030-ariadne-context-profile-and-sdk-boundary.md) own the explicitly selected native Ariadne Context Profile and direct SDK boundary for #2/#76. They retain this specification's native Git, Source privacy and Publication Admission. Written revision 1 is owner-approved for planning; this is not retroactive #1 implementation/release authority, private-app scope or a change to generic OKF exchange.

**Written revision:** 3 — revision 2's public-foundation-only scope plus the
owner-answered 2026-10-17 reactivation clarification (§3.3). No other
behavior, interface, schema, or scope changes.

**Revision 3 amendment, 2026-10-17:** after the independent G3 review, the
owner approved one collective correction of the nine accepted findings plus
the required native rename/category-move/explicit-alias completion, and
answered the reactivation behavior question: reactivation selects affected
Entities explicitly through stable Entity IDs rather than refusing every
still-declaring page or implicitly rebinding all of them. The exact contract
is recorded in §3.3; execution authority and validation budget live in
implementation plan 0008 r11. ADR-0029 already governs the architecture; no
vocabulary or additional ADR is introduced.

**Scope amendment, 2026-10-16:** the owner explicitly instructed:
“Wir wollen die lumio App vorerst nicht weiter berücksichtigen. Fokussiere dich
nur auf lumio-Wiki und wenn nötig, lumio-lancedb”. This supersedes the private
app slice/AC6 and its prerequisite for isolated public implementation. Public
engine behavior, manifest/admission interfaces and AC1–AC5/AC7 remain the
approved revision-1 contract. Existing supervised execution authority continues
for that retained scope; no new integration, push or release is authorized.

**Approval:** on 2026-10-15 the owner replied **“Ja Freigabe”** to the explicit
request to approve written specification 0008 r1 and ADR-0029, presented in
isolated design commit `81ed0f7c15c8295cf0799c88d08a570749ff5f73`. This includes
the complete Git-authoring design, exact source references, explicit local
Publication Admission, operator-confirmed legacy export, and the temporarily
KB-read-only private app with locally frozen baseline wheels. This approval
opens implementation planning; plan approval, supervised execution, target
integration, and publication retain their separate gates.

**Sources:** [Lumio #1](https://github.com/legout/lumio-wiki/issues/1)
(updated 2026-10-15T20:22:35Z),
[ADR-0029](../adr/0029-git-native-knowledge-authoring.md),
[Core SDK specification](0002-core-sdk.md),
[stabilization specification](0006-library-stabilization.md), and
[consumer inspection](../research/2026-10-15-git-authoring-consumer-impact.md).
The issue is intake, not independent approval of the written interfaces below.

**Baseline:** public `c3b68db233f8aa98a39380a0099ff2b800a70c55`; private
application `43facf97fc40497688b54546b511c5bd392396a6`. Both target checkouts
were clean after the owner's separately performed planning-path migration.

## 1. Scope and ownership

Replace persisted Ingest Proposals with ordinary Git authoring while retaining
source history, Compiled Pages, Evidence, Claims, ontology validation, Knowledge
and Discovery Graphs, retrieval, and immutable Published Versions.

`lumio-wiki` remains the model-free engine; `lumio-lancedb` remains an optional
inward-dependent adapter. Neither imports Ariadne, DuckDB, SQLGlot, a web
framework, or a mandatory model provider. Git is required for authoring and new
publication admission, not ordinary path/S3 reading, zero-index queries, or
validation. GitHub is optional. Existing optional converters, provider-led
distillation, explicit-consent capture, URL/research ingest, graph/OKF exchange,
and maintenance remain supported through the new authoring route.

A later specification owns [Lumio #2](https://github.com/legout/lumio-wiki/issues/2)
and the Context Provider/release-binding agreement in
[Ariadne #76](https://github.com/legout/ariadne/issues/76). This specification
creates no executable metric semantics, join authority, application profile,
mandatory integration service, or cross-repository transaction protocol.

## 2. Authoring Revision and native Git lifecycle

An Authoring Revision is an exact Git commit plus its selected KB subtree.
Preview, validation, admission, and publication use the same captured Git object
bytes, never a moving branch name or a subsequent filesystem read.

Authors edit in a dedicated registered branch/worktree. Operations refuse a
bare repository, detached/unselected mutation target, unresolved Git conflicts,
or an operation that would overwrite unrelated uncommitted edits. There is no
implicit stash, reset, checkout, commit, rebase, merge, push, or branch deletion.
An author may edit files directly; deterministic helpers produce the same
reviewable files and diagnostics. Invalid intermediate files may exist on a
branch but cannot become an admitted publication.

Git owns diff, history, review discussion, and reconciliation. Lumio does not
persist draft objects with `staged/review/published/discarded` states. Validation
and impact reports may be returned or emitted as CI output; they are not
change-management authority or an alternative persistent proposal store.

Every authoring route reaches the complete candidate tree, including its Control
File. A source-only edit, rename, removal, merge/redirect, category move,
maintenance repair, and import must not bypass that gate. Deletions are explicit
Git tree changes relative to the admitted baseline, not omissions from a helper's
partial page list. A branch based on an obsolete admitted revision must be
reconciled using Git before ordinary admission; unrelated intervening changes
must not silently disappear. Deliberate historical rollback is separate from
ordinary candidate admission.

## 3. Sources: private history, reviewed exact references

### 3.1 Source Reference Manifest

New Git authoring carries a versioned `.lumio-authoring.yaml` beside
`lumio.yaml`. This is authored provenance input, not a second deployment
configuration file. Its supported version is `1`; unsupported versions fail
with a diagnostic rather than being ignored.

The manifest declares:

- a stable non-empty KB namespace, assigned once when adopting Git authoring;
- source identities scoped to that namespace, with explicit active/retired
  lifecycle intent; and
- per-Entity source bindings using stable Entity IDs, Source IDs, and exact
  SHA-256 digests. A title/path change does not change a binding's identity.

The v1 shape is normative; this example binds the bytes `hello`:

```yaml
version: 1
namespace: "urn:uuid:2abf9d75-ccdc-42b5-8ca6-f493b16fbb0c"
sources:
  operator-manual:
    status: active
bindings:
  "entity:press":
    operator-manual: "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
```

All four top-level keys are required; `sources`/`bindings` may be empty maps.
Source IDs follow the existing registry ID validation; status is exactly
`active` or `retired`. Binding keys must resolve to an Entity in the selected
KB; each value maps a declared active Source ID also present in that page's
`sources[].id` to a 64-character lowercase SHA-256 digest. Every declared active
managed source on a page requires its exact binding. Different pages may select
different immutable versions of the same active source. Retired source entries
may remain for historical disclosure but cannot have supporting bindings.
Public-only source provenance is not silently promoted to managed provenance.
Once admitted as managed, a source entry is retained (possibly retired), not
silently deleted to evade its support/retirement checks. A managed non-synthetic
page needs at least one eligible supporting binding unless an explicit reviewed
page/provenance reclassification replaces that support contract.

Serialize maps in lexicographic key order for generated output; digest the exact
reviewed file bytes. Reject duplicate keys at every level, ambiguous bindings,
malformed digests, dangling Entity/Source IDs, and unknown fields. An admitted
namespace cannot change in an ordinary successor publication. No other process
may infer identity from matching filenames, titles, aliases, or bytes.

The manifest contains no original bytes, local source paths, private object
keys, credentials, signed URLs, or private capture transcripts. Git tracking
covers safe IDs/digests and approved lifecycle intent only; it is not permission
to publish a confidential source's identifying metadata to a public Git remote.
Operators choose an appropriately access-controlled content repository.

The manifest is excluded from public KB/OKF/graph exports and Reader retrieval.
Its digest is bound separately to the Published Version provenance. The
existing canonical fingerprint still identifies Compiled Pages and Control
File content; a source-only binding change can therefore preserve that
fingerprint while producing a distinct Authoring Revision/Published Version.
An empty KB has no page bindings; legacy flat KB reading remains supported,
but native Entity-based managed authoring requires the existing v2 Entity
contract before adoption. No automatic v1/flat conversion is introduced.

### 3.2 Private source state

The private Knowledge Source Registry retains immutable Source Version history
and optional verified Source Artifact bindings. Registering different bytes
extends explicit identity/history; it does not admit knowledge, activate
retirement, or switch an existing page's supporting version. Repeated identical
registration converges to the same source version.

Authoring worktrees for one KB use the explicitly configured private source
history/store; branch creation must not silently create unrelated histories or
copy raw bytes into Git. Git-tracked raw/registry paths are refused by managed
operations. A `.gitignore` alone is not a confidentiality guarantee.

Lifecycle intent is reviewed in the Git manifest. The registry no longer stores
pending transitions keyed to proposal IDs. Any retained current lifecycle view
is derived from the admitted revision, not a second authoring authority. New
unadmitted registry versions never rewrite Reader Evidence or old bindings.

Managed page bindings resolve exact registered versions, not `versions[-1]`.
An unknown version, missing required binding, or digest mismatch fails closed.
Public-only Source provenance without a managed registry identity remains
supported and is disclosed as such; it never fabricates retained bytes or a
historical managed binding. Existing retention-disabled deployments still work.
Required artifact retention blocks activation until the exact bound artifacts
are available and verified.

### 3.3 Impact and retirement

Compare admitted and candidate source references to report source replacement,
retirement/reactivation, and affected Entity/page identities. Preserve
`still-supported` versus `sole-source-lost` diagnostics. Additional support
counts only when explicitly declared and eligible in the candidate; a matching
name, missing file, or registry-latest lookup is not support.

A replacement selects its exact new version and exposes every affected page for
review. Reaffirming unchanged knowledge against replacement bytes is an
explicit source-binding edit covered by Publication Review, never an automatic
inference from registering the new version. Retirement must leave eligible
support, an explicitly reviewed replacement/reclassification, or an explicit
Page Removal with dependent repairs. Missing files/network failures remain
advisory retirement candidates, never automatic retirement or deletion.

**Reactivation by explicit Entity selection (r3).** Reactivating a retired
managed Source registers the operator's new original bytes as one exact
immutable Source Version and, in the same explicit authoring manifest edit,
flips the source's lifecycle intent to active and records exact
`(Entity, Source, SHA-256)` pins for the Entities the operator explicitly
selects. The selection is a list of stable Entity IDs supplied through the
reactivation interface. The operation first determines every page in the
selected complete candidate that still declares the retired Source ID; each
such Entity must appear in the selection, and the selection may name no other
Entity — unknown or missing IDs refuse with the computed declaring set as
actionable diagnostics. Identity is never inferred from titles, filenames,
the latest private version, or bytes, and there is no implicit rebinding of
all declaring Entities. An empty selection is valid only when no page still
declares the source. The exact SHA-256 digest is computed from the supplied
bytes; the lifecycle flip and the selected Entity pins are written together
as one atomic worktree edit after the repository/target/dirty/
tracked-original/private-selection safety preflight, and the complete
page/Control File/manifest candidate is validated with other exact support
resolved in the explicitly selected private registry. Immutable source/version
history is retained, a conflicting pin choice refuses, and no Snapshot,
commit, admission, or publication is implied.

Historical Source Binding Manifests retain the exact version-to-page/source
mapping and inspection metadata outside public snapshots. Every new publication
seals this private metadata even when raw artifact retention is disabled, using
private operational metadata storage or the configured Source Artifact Store.
They are written and verified before activation and never regenerated from later
registry state.
Rename/merge migration preserves old title-based binding manifests for old
Published Versions; new authoring binds by stable Entity identity. Raw source
inspection remains authorized provenance review, not Claim Evidence or
claim-level source-span lineage.

## 4. Publication Review and Admission

### 4.1 Stateless preview

The target CLI replaces `publish <proposal-id>` with an exact-revision
publication operation. Its interface is:

```text
lumio-wiki publish <kb> --revision <full-commit-id> --to <local-path-or-s3-uri>
    --expected-current <published-version-or-none> [--confirm <review-digest>]
```

Without `--confirm`, it produces a preview only. No raw upload, registration,
source lifecycle change, version preparation, pointer mutation, or persistent
pending admission occurs. `none` explicitly means an absent current pointer,
not "ignore the current state". The full commit ID is obtained by resolving
Git references before review; branch names cannot float through confirmation.

Publication Review discloses the selected namespace/subtree/commit, canonical
fingerprint, Source Reference Manifest digest, source impact, graph/page
mutations, blocking diagnostics, requested derived artifacts, destination, and
expected active version. A deterministic review digest binds those inputs,
the validator/format contract identity, retention policy, and secret-free effective
target identity (including a selected compatible endpoint, not just a bucket
label). Credential values and signed URLs never enter review output, digests,
receipts, or Git.

The SDK exposes the same preview/confirm behavior with explicit arguments and
structured diagnostics, not an `IngestProposal` object. It does not add its own
identity provider. The local CLI's authority is the operator's access to the
publication destination; a hosted consumer must separately enforce its role
and human/authorized-operation boundary. A model-produced assertion of approval
is not sufficient authority. Coding-agent guidance must require the operator's
explicit authorization of the displayed review before invoking confirmation;
a general implementation request is not permission to publish. This is the
trusted local-operator boundary, not cryptographic proof of a human identity.

### 4.2 Explicit confirmation

`--confirm <review-digest>` is an explicit authorized action after review.
Recompute all review-bound facts before mutation. Changed commit, source refs,
validator contract, requested artifacts, target, or active baseline refuses the
old confirmation. Passing validation, `lifecycle: approved`, committing,
merging, or reading the preview never admits automatically. There is no
validation override or legacy direct-write publication bypass.

Admission records one immutable private receipt with the exact revision,
reviewed content/source digests, validator contract identity, target, expected
baseline, and resulting Published Version identity. Persist and verify it before
activation; an inactive receipt proves authorization, not that activation
succeeded. It is operational publication evidence, not a new draft queue or
review state machine. A post-activation bookkeeping failure must not falsely
claim that the old pointer still serves; retry resolves the actual pointer and
complete receipt. Actor attribution comes from the calling environment and is
not fabricated from Git author metadata.

## 5. Captured build, immutable versions, safe activation

Capture the selected Git tree once. Permit regular in-scope canonical KB files
only; never execute repository hooks or materialize source files, symlinks,
submodules, private ingest stores, or unrelated repository content as Reader
knowledge. Validate authored content, generate Navigation/Hot Indexes and graph
state, and build/health-check a requested LanceDB index from the same captured
facts. No fallback to a different revision is allowed on build failure.

For a new local publication, use immutable version directories and an atomic,
expected-current pointer update outside the authoring worktree. S3 retains the
existing create-only version prefixes, completeness checks, and conditional
`current.json` protocol. Both manifests carry exact revision/subtree identity,
canonical fingerprint, source-reference digest, content digests, format identity,
and requested derived-artifact completion. Private source bindings refer to the
same version/fingerprint and exact captured references.

A failed validation/build/binding gate never activates. A CAS conflict never
overrides another publication; retry requires a new review of the new baseline.
Inactive incomplete versions may remain for explicit later cleanup. Retrying an
already successful identical publication returns its existing verified receipt
without rewriting immutable version bytes; it must not reactivate an old
version over a subsequently advanced pointer.

A reader resolves the pointer once and holds one complete Snapshot. Existing
plain filesystem loading remains useful for local preview/query; it is not
silently labelled admitted. Published local locations distinguish their pointer
layout and fail on missing/corrupt referenced versions without falling back to
the authoring worktree. Previously resolved Snapshots remain unchanged after
edits, source registration, publication, or pointer changes. Existing complete
Published Versions remain readable with their historical format and bindings;
missing new Git provenance is not fabricated or retroactively admitted.

The first native successor to a legacy Published Version discloses the missing
Git ancestry and compares against that exact historical snapshot. Explicit
confirmation includes that adoption and its complete diff; no commit ancestry
is guessed from a title or matching fingerprint. Existing private bindings are
preserved exactly; unknown managed bindings require explicit operator repair.
Adopting a plain filesystem KB uses a separate publication destination, never
in-place replacement or relabelling of its working tree.

Rollback is explicit review/confirmation plus expected-current activation of a
complete historical version, verifying its content, requested artifacts, and
historical private bindings under the configured retention policy. It never
rebuilds old bytes or substitutes registry-latest. No distributed transaction
with Ariadne, cross-backend atomic activation, hostile filesystem editor
cooperation, or stronger power-loss durability guarantee is introduced.

## 6. Validation and semantic preservation

Retain aggregate page/ontology validation: unique stable Entity and Claim IDs,
valid Lifecycle/Visibility, provenance, controlled types/predicates,
domain/range and literal kinds, nonempty valid Claim Evidence anchors, resolved
canonical objects, valid redirects, and merge-cycle rejection. Publication
rejects dangling authored internal references in the selected candidate;
external URLs are not fetched as a validation prerequisite. Ambiguous or
escaping references are diagnostics and never guessed repairs.

Lifecycle remains distinct from admission: the existing allowed page lifecycle
values remain; invalid values and proposal-only Claim states cannot publish.
The change does not redefine `review_after` as a blocking expiry or make
Extracted References support answer claims.

Rename, category move, removal, and Entity Merge helpers preserve stable IDs,
provenance, relevant metadata, and explicit alias choices. They repair exactly
resolved links/Claim targets and Control File pins/redirects together, disclose
the impact, and validate the full Git candidate. They never overwrite a
normalized-path collision or infer identity/equivalence. Git, not Lumio custom
merge logic, reconciles competing revisions. Compounding adds source provenance
only as an explicit authoring edit; it cannot silently drop previous Sources.

Read-only diagnostics remain read-only. `cross-link`/`dream` list candidates;
an explicit apply operation edits the selected authoring worktree rather than
staging stored proposals. Link repair never creates an accepted Claim. Model
calls remain opt-in; original/source/tool content never has operational authority.
Read-only MCP names/arguments/semantics remain compatible, with no new write
tools. Visibility-before-expansion, evidence/citation semantics, bounded
traversal, and same-version zero-index fallback remain unchanged.

## 7. Legacy proposal migration and API disposition

Provide an operator-selected legacy-store inventory and preview/export command.
It is a migration reader, not a live implementation of the old pipeline.
Inventory distinguishes terminal and unreviewed records, raw provenance,
private source history, pending source transitions, and decode/integrity errors.
Never assume that the one observed local staged record is every deployment's
pending work.

After explicit export confirmation, each selected unreviewed proposal becomes
an unadmitted Git branch based on an explicitly selected baseline. Materialize
its effective authored content, Control File changes, explicit
removals/renames/merges, compound-provenance semantics, source bindings/lifecycle
intent, and safely representable origin; retain original record/page bytes in
the private archive. Do not silently
rebase stale assumptions or fill missing Source Versions from current registry
state. Incomplete/ambiguous conversion produces blocking diagnostics and leaves
the original untouched. Incompatible operations require operator resolution.
Raw bytes, transcripts, private filenames/keys, and registry history stay in the
private store/archive. Export does not approve, publish, or delete anything.

Repeated export identifies an already matching exported branch rather than
overwriting it or duplicating changes. Modified destinations conflict. A private
migration receipt maps the legacy record digest to its exported branch/commit
and retained private artifacts. It is historical provenance, not a new draft
workflow. Terminal records remain preserved in a read-only archive. Removing
legacy storage requires an explicit operator disposition after a complete,
verifiable export/archive; this implementation never automatically erases it.

| Current surface | Target disposition |
| --- | --- |
| `ingest`, managed/URL/research/capture ingest | Prepare/register private provenance as authorized; write ordinary files/source refs in the selected Git worktree. Capture remains preview/consent-first. |
| `proposal list/inspect/validate`, `discard`, `ProposalPipeline`, `IngestProposal`, persisted `IngestStore` proposal methods | Retire; native Git diff/review/branch lifecycle plus whole-revision validation. Retain only separately named legacy decoding/export internals needed for migration. |
| `publish <proposal>`, `publish-s3` working-tree bypass | Replace/route through the exact-revision preview/confirm admission gate. No retained command can bypass it. |
| Source lifecycle/proposal-bound pending transitions | Git source intent and impact, private immutable history, admitted-revision lifecycle view. |
| Rename/remove/merge/import/maintenance staging helpers | Explicit worktree edits plus structured validation/impact, no persisted proposal wrappers. |
| SDK load/validate/retrieve/Snapshot, read-only MCP, optional adapters | Preserve public read contracts; versioned local publication is added without reclassifying plain reads as admitted. |
| Packaged skill/PROTOCOL/setup guidance and examples | Teach Git authoring, exact admission, migration, source privacy, and read-only consumption; remove current proposal instructions with the implementation. |

Release numbering and public publication are not part of this specification.
Unknown external consumers remain a release risk; absence of repository matches
is not evidence that a supported API is unused.

## 8. Private application: deferred by the owner

The owner removed the private application from this execution scope on
2026-10-16 (instruction quoted in the header). Do not continue its C0 migration,
tests, CI provisioning, review, or rollout, and do not require its candidate
before implementing the public foundation. Preserve its incomplete work and
artifacts without claiming acceptance or cleaning them up.

The initial consumer inventory already established real proposal-facing app
dependencies. That known incompatibility is not disproved or repaired by this
scope change. Public-only isolated implementation may retire those APIs under
this approved design; production integration and a breaking release still need
separate explicit compatibility/adoption disposition under specification 0006.
No new private-repo work, migration, source-wheel vendoring or publication is
authorized here. Revision 1 in Git retains the original private transition
design as history, not current executable scope.

## 9. Observable acceptance and lean assurance

| ID | Reachable scenario and required outcome |
| --- | --- |
| AC1 | In a local isolated Git worktree, edit a page plus `lumio.yaml`, rename/remove/merge with repairs, and commit. Invalid Claim/evidence/ontology/lifecycle or dangling-link variants produce specific collected failures. No proposal files are created. |
| AC2 | Preview a valid commit, then change any admission-bound input or active baseline. Old confirmation is refused. A commit or passing CI alone creates no Published Version. |
| AC3 | Confirm the reviewed revision for local storage and optional S3. Every page, graph/index, private binding, and receipt identifies that captured revision. Inject build/binding/activation failure or S3 CAS conflict: old readers still see only the prior complete version. Identical retry does not overwrite versions. |
| AC4 | Register source B after reviewing a branch pinned to A; publication/inspection still use A. Explicit replacement/retirement reports the affected pages and eligible support accurately, without mutating old Evidence or creating pending proposals. Required retention refuses missing/corrupt exact artifacts. |
| AC5 | Preview then explicitly export an unreviewed legacy proposal with a source transition and page mutation. Export preserves representable intent in an unadmitted Git branch; stale/unknown bindings block disposition, original/private history remains, retry does not overwrite edited output. |
| AC6 | Deferred/out of scope by the owner's 2026-10-16 amendment. Existing private-consumer incompatibility remains recorded; no private candidate or adoption proof is claimed. |
| AC7 | Installed base wheel authors/validates/queries locally without Ariadne, model provider, server, GitHub, or LanceDB. Plain querying needs no Git executable. Optional retrieval/MCP remain same-version, visibility-safe and read-only. |

Use focused existing checks wherever they establish these scenarios. The plan
assigns `existing-check`, `new-test`, or `no-new-test` per coherent validation
unit, independently derived expectations, high-risk contract review before
dependent work, and one parent-authorized fix pass plus one delta recheck.
Full repository validation uses `uv run pytest -q -n 4`, never `-n auto`.
Live S3/visibility checks require their actual environments; unavailable
capability is disclosed, not called passing. Private application checks and AC6
are excluded from this public-only execution, not silently marked passed.

## 10. Capture checkpoint and execution handoff

- Vocabulary: `CONTEXT.md` captures Authoring Revision, Source Reference Manifest,
  Publication Review/Admission, and the legacy status of Ingest Proposal/Write
  Mode. Existing Evidence, Claim, and Source Version meanings remain.
- Decisions: accepted ADR-0029 owns why Git replaces proposals and why admission
  is separate. Its scoped amendments are linked from affected source records;
  governing agent/skill operating examples change alongside the implemented
  replacement, never in advance on main.
- Behavior: approved revision-1 public behavior/interfaces remain unchanged;
  revision 2 records the owner-directed exclusion of private §8/AC6. Active
  acceptance is AC1–AC5 and AC7, with approval references in the header.
- Uncertainty: no shared #76 interface is approved. Do not implement #2 against a
  guessed contract. The v1 manifest schema and semantic publication interface
  above are approved. Python symbol names/module layout remain implementation
  choices; a material behavioral/interface change returns to shaping before
  dependent workers consume it.
- Planning-contract version 1, installed skill SHA-256
  `5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`;
  upstream installed catalog commit is unknown. Execution host, when authorized,
  is Paseo/Pi on oa1 with the configured XDG worktree root, supervised. Role
  model/thinking preflight, clean baseline, candidate review, and separate
  integration/publication authority still apply.
