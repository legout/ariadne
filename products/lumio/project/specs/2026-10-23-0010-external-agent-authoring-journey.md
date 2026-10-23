# Specification 0010: External-agent authoring journey

Status: approved design with scoped owner amendment. Written revision: 3.
Date: 2026-10-23.

Approval: in BB thread `thr_52d92z7irz`, 2026-10-23, the owner explicitly
approved “specification 0010 revision 1 and ADR-0031 as written” and requested
glossary capture and an implementation plan, with “do not start implementation.”
The owner subsequently selected **“Metadata-only baseline bootstrap”** to resolve
the fresh-contributor prerequisite discovered during planning. Revision 2 captures
that scoped decision in §5.1 and AC11; other approved behavior remains unchanged.
Planning is authorized; execution is not. This is not a claim that the owner
separately reviewed every new implementation detail in plan revision 2.

Approved scoped amendment, 2026-10-23: after selecting **Private local profile**,
the owner explicitly approved “Ariadne specification 0033 revision 1, the proposed
ADR-0026 amendment and Lumio specification 0010 section 2.1.” Revision 3 captures
that approval and the shared configuration contract in §2.1; all other approved
journey behavior remains unchanged. The owner requested reconciled planning and
repeated “do not start implementation.”

## Owner decisions and scope

The owner selected skill + CLI + native Git as the first complete supported
journey, independent contributor and maintainer environments, BB with Pi as the
first qualified harness, and a private S3-compatible exchange with manual bundle
fallback. Revision 1 and implementation planning were explicitly approved, followed
by the scoped bootstrap decision above. Execution remains excluded.

This specification owns the conversational document-authoring journey in
`lumio-wiki`: guided setup, extraction, original retention, multi-page authoring,
ontology changes, readable review, Git submission, private source handoff and
maintainer publication. The Python API owns reusable behavior; the CLI exposes
operations and structured results; the packaged skill coordinates the external
agent and human. Git and hosting tools own commits and PRs.

Sources: [Git-authoring specification 0008](2026-10-15-0008-git-native-knowledge-authoring.md),
[ADR-0029](../adr/0029-git-native-knowledge-authoring.md),
[ADR-0018](../adr/0018-layered-document-conversion-anydoc.md),
[ADR-0028](../adr/0028-read-only-mcp-distribution.md),
[Lumio vocabulary](../../CONTEXT.md), and the owner decisions in BB thread
`thr_52d92z7irz`. Baseline inspected: `dcc95a9` (Lumio 0.5.1).

## 1. Invariants and exclusions

- Keep Git as the sole persistent authoring lifecycle. Reports and transfer
  artifacts do not create draft/proposal states or another approval database.
- Preserve independent Publication Admission of an exact Authoring Revision,
  destination and expected active Published Version.
- Original bytes, extracted working material, private registry state and
  credentials remain outside the content repository and Reader publications.
- The host Pi agent performs distillation. No Lumio-owned agent runtime or
  additional model provider is required.
- MCP remains read-only. No new web application, central source service,
  authentication service, custom encryption system or Git hosting abstraction.
- Preserve current converter routing and optional dependencies. Do not add a
  converter or claim exact Claim-to-original-span lineage.
- Existing low-level and hash-only installations remain supported. Required
  original retention belongs to explicitly adopting this guided journey.

## 2. Guided setup and Git connection check

Guide the user through creating or selecting a KB, its registered authoring
branch/worktree, namespace, private registry and artifact store. Existing KBs
retain their namespace and bindings; adoption never guesses private history.
Select local-commit or GitHub-PR submission, a Git remote/target branch, an
exchange configuration when needed, and a local or S3 publication destination.
Keep machine-specific settings outside versioned content.

Check CLI availability/version, packaged and installed skill drift, required
extras, Git identity, repository state, remote readability and host credential
configuration. Run read-only connection probes. Report clone/read authentication
separately from push/PR capability: a successful read does not prove write access.
Report unverified capabilities honestly; do not create a test branch or PR.

Use ordinary SSH agent/key configuration or Git credential helpers. Guidance can
reference key paths and process environment variables but must not ask the model
to read secret values. Do not embed credentials in remote URLs or repository
files. Skill updates are explicit and must not overwrite local modifications
silently. Install/update is followed by a harness restart or fresh session.

For this journey, configure a private artifact store before ingest and required
retention before publication. A contributor's publication capability may be
absent; that must not block authoring or handoff. Exchange access and canonical
publication access are configured separately.

### 2.1 Shared private source configuration

The owner chose a reusable machine-local profile over repeated CLI arguments.
Lumio owns its format and public Python resolver; Core consumes that public
interface through its optional integration, never private CLI environment
helpers or a second parser. One explicitly selected file represents one
configuration. No automatic discovery by cwd, namespace or project name.

Version 1 contains the format version, expected KB namespace, an absolute
private local registry directory, an explicit canonical original-artifact store
(absolute local directory or private S3-compatible bucket/prefix), an explicit
`required`/`disabled` retention policy, and optionally a separate private exchange
connection. The guided managed journey requires `required`; existing low-level
hash-only operation remains available outside that journey.

Each S3 connection declares its own credential environment-variable names and
endpoint/region/URL-style configuration. Secret values stay in the host
environment; missing declared credentials refuse without global/provider-chain
fallback. Retain supported transport rules, including explicit synthetic local
test allowances. Connections may intentionally reference the same variables,
but never inherit another connection's credentials by omission. Resolve only
connections needed by the operation; metadata bootstrap needs no artifact or
exchange access, and publication after import needs no exchange access.

The profile, registry, local artifact store and extracted material stay outside
the Content Repository, including ignored directories inside it. Reject unknown
versions/fields, embedded credentials, credential-bearing URLs, ambiguous
selectors and relative local paths. Resolve local paths before containment and
identity checks. Namespace must match the selected KB. Setup previews creation
or changes and preserves unrelated operator settings; no silent overwrite.

Private profile locations/configuration never enter Git, PRs, handoff bundles
or public reader output. Contributor and maintainer profiles can select
different stores for the same namespace; exact source and Git identities bind
their transfer. A profile selects neither publication destination nor Git
credentials, database access, Visibility Scope or admission authority.

Add explicit profile selection to the applicable journey CLI operations.
Reject competing registry/store/retention flags or environment selections in
profile mode; declared credential variables remain valid inputs. Existing
commands without a selected profile keep their current resolution behavior.
Provide safe configuration inspection without creating a registry/store or
mutating publication state. The public resolver supplies validated configuration,
operation-required adapters and a deterministic non-secret effective binding.
Do not read/log/hash secret values for identity; credential references and
resolved effective targets are bound instead. Exact option names/schema keys
and signatures must be frozen in the reconciled plan before implementation.

This additive setup/resolver contract changes no transfer format, native page
profile or reader API. Ariadne specification 0033 owns how Core binds the
resolved choices into overall review and rechecks them at confirmation. Plan0010
revision 3 captures the interface/setup/qualification changes. Its decomposition
remains proposed; no implementation is authorized.

## 3. Source reading and complete candidate authoring

The harness supplies a readable original file. Missing files produce an
actionable failure before registration or mutation. Initial supported input
coverage is UTF-8 text/Markdown plus existing PDF, image, Office and HTML
processors; qualification covers representative formats, not every container.

Expose extraction independently from distillation, using the existing
SourceProcessor seam. Output normalized text, real section/page coordinates when
available, the original digest and the actual processor identity. Persist any
working extraction outside Git. Missing extras, conversion errors, empty results
and detected incomplete results must be disclosed; never claim completeness
merely because conversion returned text. Host-native reading is allowed when
available and is described honestly; never claim a converter ran when it did not.

The agent reads existing vocabulary and relevant pages before authoring. It
reuses stable Entity and Source identities when the source is an explicit update;
new source identities are explicit and collision-resistant. A matching filename
or title alone does not establish source identity.

Support one original producing several pages, and a candidate combining page
changes with ontology changes. Existing page updates retain their identities;
new types/predicates require authored definitions. Evaluate the entire candidate
before applying managed edits so references between new pages do not require
invalid intermediate ingests. Do not overwrite unrelated local edits.

Bind every managed page to the exact selected source digest. Retain and verify
original bytes before reporting successful managed ingestion. A failure may
leave immutable private registration/artifacts that a retry reuses, but must not
report a complete candidate or silently substitute hash-only retention.

## 4. Human review and native Git submission

Generate a review against an explicit base revision and an exact candidate
snapshot. Include the selected KB subtree, candidate content identity, validator
contract and validation result. The identity covers all submitted files, including
ontology, frontmatter and Source Reference Manifest; it is not a body-only hash.
Unrelated staged changes must not enter the submission.

The skill displays new page bodies and readable before/after changes for updated
pages, with explicit deletions. A separate plain-language summary covers changed
Claims, Entity types, ontology, lifecycle, visibility and source support. Hide YAML
in the ordinary review. Large reviews may be paginated; omitted content is
disclosed, and confirmation must not imply review of undisplayed changes.

Human confirmation applies to the displayed candidate. Structural validation
does not establish factual correctness. A changed file, source binding or
ontology invalidates that candidate confirmation. The skill asks for review of
the changed candidate instead of carrying forward an unqualified approval.

After confirmation, the agent invokes native Git to commit. Verify that the
resulting commit contains exactly the reviewed candidate before export/push/PR.
If a hook or concurrent edit changes content, disclose the mismatch and stop
submission until reviewed. Preserve user work; never repair by implicit reset.
The snapshot/report is stateless inspection, not a persisted proposal store, and
does not authenticate a human independently of the host conversation.

Project submission configuration expresses what confirmation authorizes:
local commit, or branch push and GitHub PR. State that action in the review.
Retries inspect the remote branch/PR before creating duplicates. PRs contain a
readable change summary, validation outcome, exact revision, and private handoff
identifier/digest; never original documents or signed download URLs. Native Git
remains usable with other hosts; automated PR qualification initially uses GitHub.

## 5. Private Source Handoff

Approved vocabulary: a **Source Handoff Bundle** is a private, versioned transfer
artifact carrying selected exact Source Versions and their original bytes for a
Git contribution. A **Source Exchange** is the configured private transfer
location. Neither is a Knowledge Base Location, registry synchronization protocol
or Publication Admission. Definitions are captured in CONTEXT.md.

Export consumes explicit base and contribution commits in the same KB namespace.
Select the source versions required by new/changed bindings relative to that
base; repeated references to one version transfer its bytes once. Include a
versioned manifest with namespace, KB subtree, both revision identities,
source-reference digest, binding changes and per-source ID/digest/size/media type
and safe filename. No unrelated source history, physical store keys, credentials,
local paths, publication receipts or mutable lifecycle state is exported.

The bundle ID is opaque and the bundle has a content digest. Its manifest binds
all payloads. Export verifies retained source bytes; unavailable originals block
handoff. A maintainer can request a supplementary export of exact references
missing from its private history without exporting an entire registry.

Import first previews against explicitly selected Git revisions and a
namespace-scoped destination registry/store. Verify the bundle digest, format,
namespace, selected bindings and every artifact's size and digest before applying
registry updates. Validate archive structure and configured size/count bounds;
reject escaping paths, links, duplicate entries and unexpected executable content
handling. Never execute a source or follow instructions inside it.

Existing exact versions are reused. Missing versions are added through supported
registry operations. Existing metadata/history is not overwritten. Conflicting
immutable metadata or an ambiguous Source identity blocks import with an explicit
resolution requirement. A genuinely new version under an existing Source ID must
be an intentional version update reflected in the reviewed Git change, not an
identity inferred from matching labels. Local import time is not presented as
the contributor's original registration time.

Import is retryable: artifacts are create-only and verified; registry availability
is recorded only for verified retained bytes. Partial I/O failure may leave
reusable immutable artifacts/versions, but reports incomplete import. It never
changes authored pages, activates lifecycle intent or publishes a version.

### 5.1 Metadata-only baseline bootstrap

A fresh contributor clones the selected Git base and obtains a **Source Baseline
Snapshot** from the maintainer: private metadata for the exact Source Versions
referenced by that base, without original documents. This is a distinct, versioned
artifact kind, not a Source Handoff Bundle with missing payloads. Both kinds use
the private exchange or manual transfer with the same integrity checks.

The maintainer exports from an explicitly selected namespace, KB subtree and full
Git revision against its private registry. Include only the exact referenced
source identities, digests and necessary version metadata; exclude unrelated
history, original/extracted text, store keys, credentials and local paths. Bind the
snapshot to the exact source-reference manifest and give it a content digest.
Missing required version metadata blocks a complete snapshot export.

The contributor imports against that same explicit Git base, with an expected
digest supplied through maintainer-approved project setup or direct operator
selection. Object readability or a self-declared maintainer field is not approval.
Verify kind, format, namespace, revision, complete binding coverage and metadata
consistency before mutation. The file's digest proves transfer integrity; matching
Git bindings proves identity alignment. Neither establishes that the contributor
has independently verified source bytes or their factual content.

Import is additive and idempotent. It records the transferred metadata's origin
and preserves existing history. Conflicting immutable metadata is an explicit
failure, not an overwrite. It may populate absent exact version records without
raw bytes, but must not copy a sender's artifact-availability flag, manufacture
byte verification, mark source access granted or rewrite lifecycle intent. For
already verified local versions, import must not downgrade their retained state.

This allows complete candidate validation to resolve unchanged baseline bindings.
The contributor needs retained originals for new/changed source versions and any
original it chooses to inspect; metadata alone cannot support extraction or raw
inspection. Body/ontology edits using an unchanged baseline binding remain subject
to complete review and validation, with unavailable originals disclosed honestly.
Publication under required retention still verifies all referenced non-synthetic
originals in the publishing environment; bootstrap never satisfies that gate.

If the selected base changes, compare its exact bindings with locally available
version records and obtain a snapshot for the new base when needed. Never
reinterpret an old snapshot as a different revision or replace exact digests with
latest versions. Do not turn bootstrap into live registry synchronization.

## 6. Exchange transport and manual fallback

The same bundle is exported locally for manual private transfer or uploaded to an
explicit private S3-compatible exchange. Exchange configuration and credentials
are machine-local, separate from the canonical registry and publication target.
Use authenticated transport and existing provider credential resolution. Do not
make objects public or put signed URLs in review history.

Uploads are immutable. Publish the discoverable completion record only after all
required bundle bytes have been uploaded and verified. Downloads require an exact
handoff identifier plus expected digest and verify the complete artifact before
import. The identifier grants no storage access. PR metadata names neither a
private bucket/path nor a bearer credential.

The deployment owner provisions exchange permissions. Contributors need only
their permitted submission/read scope; they do not require access to the
maintainer registry or publication credentials. Lumio does not provision IAM.
Retention/cleanup is operator-controlled; import does not automatically delete
the exchange copy. Loss of a transfer object after successful import must not
make admitted knowledge depend on the exchange.

Network interruption permits retry with the same bundle identity. Authentication,
permission, missing-object and integrity failures remain distinguishable without
printing secret-bearing locations. Manual transfer feeds the identical importer
and verification contract and needs no S3 dependency.

## 7. Maintainer review and publication

The maintainer fetches the Git contribution and imports its private source
handoff, inspects source material as needed, and reviews the final integrated
candidate. Git merge/rebase may change the commit identity; publication always
uses a fresh review of the final exact commit and never reuses the contributor's
publication authorization.

Imported immutable versions remain reusable after a rebase, but the handoff's
original revision binding is not rewritten. Compare the final Source Reference
Manifest against imported and existing exact versions and request a supplementary
handoff if bindings changed or required originals are missing. Validate the whole
candidate, not only the contribution delta.

Publication retains the current preview/confirm interface and destination/current
version checks. Required retention verifies all referenced non-synthetic originals
in the maintainer's canonical store. Neither a PR approval, source import, Git
merge nor valid frontmatter grants Publication Admission.

## 8. Interfaces, compatibility and documentation

Add public operations for source extraction, complete managed-candidate authoring,
candidate review/checking, and handoff export/inspect/import/upload/download as
needed. Exact command spelling and Python signatures belong to the implementation
plan's interface inventory and must trace to this behavior; reuse existing
operations where they already satisfy it. New agent-consumed results use
versioned structured output, stable identifiers and actionable error categories.
Retain existing publication/search/page/status JSON behavior.

Update the packaged skill and canonical onboarding guide together. Replace stale
proposal guidance and explicitly teach original reading, retention, human review,
Git submission, private handoff and final maintainer admission. Existing installed
copies are diagnosed and updated through the existing explicit skill mechanism.
No silent global skill replacement, format migration or private-app work.

## 9. Observable acceptance

1. A fresh BB + Pi contributor project completes guided setup using existing Git
   credentials. Read access is distinguished from unverified push access; a
   contributor without publication credentials can still author and submit.
2. A document produces two related pages and an ontology addition in one valid
   candidate. Original bytes are retained privately and later fetched byte-exact.
   Conversion provenance names only work actually performed.
3. The user sees bodies, explicit deletions where applicable and semantic metadata
   changes. A file edited after confirmation prevents unreviewed submission.
   A post-commit hook mutation also prevents export/push of mismatched content.
4. Confirmation creates the configured native Git submission. Retrying a completed
   submission does not create another PR or duplicate the reviewed change.
5. Contributor and maintainer use separate checkouts, private registries, artifact
   stores and credentials. Git plus the private exchange is sufficient to import
   required new source versions and publish; no contributor filesystem path is
   available to the maintainer.
6. Existing maintainer history survives import. Reimport is idempotent; a valid
   new version of an existing source remains distinct from an identity collision.
7. Interrupted upload/import resumes safely. Corrupt bytes, wrong namespace,
   conflicting metadata, missing payloads and unsafe bundle entries cannot produce
   a successful import or publication.
8. Manual bundle transfer reaches the same imported source state without S3.
9. A rebase with unchanged bindings can reuse imported originals; changed bindings
   require the correct versions. Publication always reviews the final revision and
   refuses stale expected-current state or missing required retained artifacts.
10. Reader exports/retrieval and Git contain no private source bytes or transfer
    credentials. The published pages are queryable with normal citations.
11. A fresh contributor clones a nonempty managed KB and imports the maintainer's
    exact-base metadata snapshot without receiving baseline originals. It can add
    a retained new document and validate the complete candidate. Reimport preserves
    history and any verified local artifacts; wrong namespace/revision, incomplete
    coverage and conflicting metadata are refused. Source inspection truthfully
    reports missing originals, and required-retention publication on that contributor
    still refuses until the missing originals are actually retained. The maintainer
    can publish using its retained baseline originals plus the new contribution's
    full source handoff. The BB + Pi journey must start from this nonempty baseline.

Qualification includes one real BB + Pi attachment/review journey with two
independent environments and a private S3-compatible exchange, plus focused
checks for the named failure cases and the manual path. Representative document
fixtures cover text/Markdown, PDF including OCR, Office and HTML through retained
processors. Record unexercised formats/harnesses explicitly. No claim of universal
harness support or factual correctness from validator success.

## Capture checkpoint and handoff status

Planning Contract version: 1. Installed skill revision provenance: unknown.
Existing Lumio vocabulary remains authoritative; Source Handoff Bundle, Source
Exchange and Source Baseline Snapshot are captured in the owning glossary.
[Accepted ADR-0031](../adr/0031-private-source-handoff-for-external-agents.md)
records the exchange trade-off. This revision defines approved behavior and
acceptance. The [implementation plan](../plans/2026-10-23-0010-external-agent-authoring-journey.md)
freezes the proposed interface spellings, bundle schema/version and numeric bounds
for plan review. Execution is explicitly excluded by the owner. Ariadne impact
assessment is reconciled with separately approved
[Ariadne spec0033](../../../ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md)
and its proposed plan. That source owns the Core admission extension; neither
design approval authorizes runtime implementation.
