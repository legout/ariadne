# Specification 0033: Managed knowledge authoring and integrated admission

Status: owner-approved complete design, revision 1. Date: 2026-10-23.

Owner decisions: in BB thread `thr_52d92z7irz`, the owner requested shaping
Ariadne follow-ups to the approved Lumio external-agent journey, then selected
“Private local profile” for source configuration. The owner subsequently
explicitly approved “Ariadne specification 0033 revision 1,
the proposed ADR-0026 amendment and Lumio specification 0010 section 2.1” and
requested plan0033 plus reconciliation of Lumio plan0010, with “do not start
implementation.” This approves the complete written behavior below and those
scoped amendments; it grants planning only, not implementation, integration or
publication.

Sources: [bound releases](2026-10-18-0029-lumio-bound-governed-releases.md),
[integrated profiles and queries](2026-10-22-0032-integrated-query-and-profile-expansion.md),
[ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md),
[ADR-0024](../adr/0024-git-only-durable-authored-state.md),
[Lumio journey 0010](../../../lumio/project/specs/2026-10-23-0010-external-agent-authoring-journey.md),
[Lumio SDK contract 0009](../../../lumio/project/specs/2026-10-18-0009-ariadne-context-profile.md).
Planning contract: version 1; installed skill catalog revision unknown.
Inspected baseline: `dcc95a9`.

## 1. Scope and inspected gap

Support external agents using the packaged skills, CLIs and native Git to
contribute managed knowledge to an integrated Content Repository, then let an
operator admit the exact contribution through Ariadne's existing overall route.
Qualify BB with Pi across independent contributor and maintainer environments.
Reuse Lumio's metadata-only baseline bootstrap, bounded private S3-compatible
exchange and manual fallback. Lumio owns extraction, provenance, original
retention, ontology and source transfer; Core owns analytics validation and
overall admission. No source-transfer implementation is duplicated in Core.

At the inspected baseline, `lumio_context.prepare_release` calls native
`preview_publication` and `publish_and_verify` calls `publish_revision` without
`source_registry`, `artifact_store` or `retention_required`. The Lumio CLI's
environment resolution does not run in those SDK calls. Core currently has no
explicit private source selection for the integrated route. Its setup checks
Git/root/identity, but lacks the proposed remote connection diagnosis.

Also add dependency-free Git connection guidance to standalone Ariadne setup.
Standalone document ingestion keeps its existing operator-managed originals;
it does not acquire a mandatory Lumio dependency or managed archive.

Excluded: MCP authoring, Agent/Tau adoption, a new agent runtime, automatic
database access or measurement, Policy-to-SQL generation, raw database transfer,
automatic IAM provisioning, another draft store, a shared Git helper package,
software-repository workflow changes and migration of real projects.

## 2. Explicit private local profile

Lumio owns one versioned private source configuration format and public Python
resolver, usable by its CLI and the optional Ariadne integration. Core must not
import private CLI helpers or independently interpret a second copy of the
format. This is an additive companion amendment to Lumio specification 0010.

One file represents one configuration, selected explicitly by file path. It
lives outside the Content Repository, including ignored directories inside it.
There is no automatic discovery by project name, current directory or namespace.
Setup may create it after displaying the requested configuration; a later edit
must show the existing difference and preserve unrelated operator settings.
The file contains no secret values and is still private operational metadata.
Do not copy it into Git, handoff bundles, public publications or PR bodies.

The exact shared configuration behavior belongs to [Lumio specification 0010 §2.1](../../../lumio/project/specs/2026-10-23-0010-external-agent-authoring-journey.md#21-shared-private-source-configuration).
Its registry, canonical artifact store, namespace and explicit retention policy
are admission inputs. The new guided managed journey requires `required`;
existing explicitly selected low-level hash-only use remains distinct. The
optional exchange has independent credentials and is not an admission dependency
after import. Manual transfer needs no exchange configuration.

Reject unknown versions/fields, ambiguous selectors, credential-bearing URLs,
embedded credential values and paths inside the repository. Relative paths
are rejected in version 1 so worktree/current-directory changes cannot retarget
storage. Resolve local paths before containment and identity checks. A profile's
namespace must equal the selected KB; a matching name alone grants no authority.

Separate contributor and maintainer files may name different registries, stores
and credentials for the same namespace. Their profile identities need not match.
Exact source IDs/digests and the reviewed Git revisions connect environments.
Contributors need no publication access or maintainer-store credentials.

The profile does not select Git credentials, the publication destination,
Core data-source Storage Profiles, Source Approval, Visibility Scope or query
capabilities. Existing Core destination/storage-profile selection remains
authoritative for publication. The exchange is never a canonical artifact store.

Profile selection is explicit for each invocation; a harness may supply that
path from its local configuration. Profile mode rejects competing flags or
environment selections for registry/store/retention instead of merging them.
Declared credential variables are inputs, not competing selections. Unselected
legacy Lumio commands keep their current configuration behavior; Core never
starts consuming global `LUMIO_*` defaults implicitly.

## 3. SDK and operator interfaces

Add one public Lumio profile-loading/resolution seam that supplies validated
configuration, the explicitly selected registry/store adapters when needed,
and a deterministic non-secret binding for the requested operation. Parse and
validate configuration before opening stores; diagnostics/setup inspection do
not create a registry, upload objects or mutate a pointer.

Resolve only operation dependencies: metadata bootstrap needs the registry;
local extraction needs neither S3 nor exchange credentials; publication needs
the registry and canonical artifacts, not exchange credentials. An optional
exchange outage cannot stop publication after successful import.

Add profile selection to the relevant Lumio journey CLI operations and Core's
existing overall preview/confirmation interface. Do not add a second admission
command. The Python Core entry point receives an explicit selection as well;
it does not rely on shell state left by an earlier Lumio CLI invocation.
Exact option names, serialization keys and public Python signatures belong in
the implementation plan, frozen before consumers implement them. These are
configuration interfaces, not changes to `ariadne-context/1` page envelopes.

No private profile is needed for source-free queries or existing immutable
published-reader access. Preserve standalone lazy SDK loading and existing
integrated support revisions; this feature adds admission configuration, not
query/profile capabilities.

## 4. Contributor review and native Git submission

The agent starts from the selected Git base, uses its local profile and obtains
a matching metadata-only baseline snapshot when necessary. Bootstrap can
resolve exact unchanged source bindings; it never proves original availability
or grants database access. New/updated document versions retain original bytes
through Lumio before reporting ingestion success.

Use the existing Core branch/worktree and Lumio operations on `knowledge/`.
Respect each product's registration and containment requirements; no detached
copy or second maintained Context Layer is introduced.

Prepare one human-readable contribution review covering the whole submitted
tree. Knowledge pages display bodies without frontmatter plus meaningful
metadata, ontology, source-binding and visibility changes. Changed Core inputs
display their actual contract, source-declaration, metric-expression, mapping
and Policy-binding differences with plain-language consequences. Never hide
executable changes behind a document-body approval. Unknown/unclassified files
must be shown explicitly or excluded by the author, not silently approved.

Reuse each product's validation/review gates. A contributor without database
permissions can submit a candidate with live validation explicitly pending;
the agent must not claim admission readiness or fabricate evidence. Required
live validation must occur in an authorized environment before admission.

The confirmation names its action: local commit or branch push/GitHub PR. Bind
the complete candidate and selected base, then verify the actual commit tree
after hooks before push/export. Edits, additional staged files, hook mutations
and rebases require a matching renewed review. Reuse native Git and hosting
tools with retry-aware PR lookup. This requires a composed Core/Lumio review;
Lumio's standalone KB-only submission rule remains valid for standalone use.

The private handoff contains only the exact Lumio source versions required by
its transfer contract. It never carries database credentials, source approvals,
Core admission authority or portable claims that live validation passed on
another machine. Transfer preview/confirmation remains separate from submission
and final publication consent; repeated checks alone do not create new approvals.

## 5. Maintainer preview and confirmation

Import private source material using Lumio's existing planned preview/confirm
flow, then reconcile and validate the final integrated Git candidate through
Core. Rebase preserves imported immutable versions, not the old review identity.
Missing final bindings require an additional handoff or operator-supplied exact
versions; never remove bindings to make validation succeed.

Core resolves the selected private profile and supplies its registry, artifact
store and retention policy to both native publication preview and confirmation.
Required retention covers all referenced non-synthetic original versions,
including unchanged baseline bindings. Metadata bootstrap cannot satisfy it.
Profile-backed publication must not fall back to hash-only operation.

The composite review binds the effective namespace, resolved canonical registry
location, canonical artifact-store location/endpoint/region/style, credential
reference names and retention policy, together with the existing exact revision,
native reviews, source-reference manifest, destination, expected current states,
build identities and scope. Store the private binding with existing private
review/admission material; no new pending-authoring database is introduced.
Public knowledge artifacts and reader output carry no private locations,
credential references, source metadata or raw bytes. A safe digest/policy marker
may identify the admission binding where needed; it is not a storage locator.

Re-resolve the explicitly selected profile at confirmation, compare the effective
binding, and recompute the native/composite review before side effects. Changing
the registry/store/endpoint/namespace, retention, credential reference names or
relevant source state invalidates consent. Reformatting a file or moving it
without changing its effective inputs does not. Rotating credential values
under the same declared references does not invalidate the digest; credentials
are never hashed/logged and the operation must still pass actual authorization.
Changes only to unused exchange configuration do not invalidate publication.

Resolve once for the confirmed attempt and pass those same selected adapters
through publication. Do not reread mutable process configuration between the
review check and native side effects. Native source/retention/current-state
checks still run; binding configuration does not freeze mutable store contents.

Overall confirmation remains an explicit operator action. An external agent
may prepare and execute the authorized CLI operation on the operator's behalf;
it cannot invent confirmation or obtain operator authority through an Analyst
or MCP tool. Existing Source Approval precedes any protected live validation.
Knowledge review grants no database access and changes no metric by inference.

Complete and verify the native Lumio publication, then persist/verify Core's
required artifacts and activate the Core descriptor atomically last. Preserve
the previous integrated release on failure. Report completed native publication
and immutable private residue accurately. Retrying reuses verified immutable
results and expected-current checks; it cannot reactivate an older release over
a newer pointer or silently relax retention. Lost/changed authorization or
changed review inputs require fresh consent.

## 6. Git setup and migration

Extend Ariadne's existing setup diagnostics with read-only remote connection
checks, safe remote reporting and host SSH/credential-helper guidance. Keep
Git identity, repository state, read access, push access and PR-tool readiness
distinct. A successful read never proves push permission. Do not create a
probe branch/PR, read private-key contents, print tokens, write Git config or
change credentials as part of the check. Explicit setup remediation remains a
separately requested operation. Use the same guidance as Lumio, without making
standalone Core import Lumio or introducing a shared package for one helper.

The new guided integrated setup requires a selected compatible private profile
and required retention. Existing unmanaged/hash-only configurations and already
admitted releases are not silently migrated or rewritten. A changed installed
Core/SDK build retains the existing revalidation/re-admission requirement.
Do not introduce a runtime profile requirement for previously admitted readers.
Missing SDK profile capability refuses new profile-backed admission clearly;
it does not fall back to global configuration or mutate an existing admission.

## 7. Observable acceptance

- AC1 — Explicit compatible configuration: Lumio CLI and Core resolve the same
  selected profile consistently. Missing selection for managed admission,
  namespace mismatch, ambiguous overrides and missing required credentials
  refuse without publication. No process-global registry fallback occurs.
- AC2 — Independent environments: a fresh contributor clones a nonempty managed
  base, imports metadata only, retains a new original, authors pages/ontology,
  obtains body/semantic review, and submits Git plus private handoff. A maintainer
  with independent stores imports and admits the final reconciled revision.
- AC3 — Whole-contribution consent: a candidate that edits a document and a
  metric shows both changes; approving the body alone is insufficient. An added
  staged file or commit-hook change prevents unreviewed submission.
- AC4 — Retention honesty: baseline metadata with one absent required original
  blocks publication; providing verified bytes enables a new matching review.
  The gate covers unchanged and new source bindings, not just the handoff delta.
- AC5 — Configuration consent: changing the canonical store or endpoint between
  preview and confirm refuses before publication/activation. Credential-value
  rotation with unchanged references/target works when authorized. Changing only
  the optional exchange does not invalidate canonical publication review.
- AC6 — Authority and failure: imported source material grants no database access.
  Pending required live validation blocks admission. Failure after native Lumio
  publication leaves Core on the prior complete release and reports native residue;
  retry with stale current-state expectations refuses.
- AC7 — Reader independence: an admitted source-free page read returns the pinned
  compiled body/citation without profile, registry, raw-store or exchange access.
  Neither reader/export output nor Git/PR content leaks private configuration.
- AC8 — Setup and compatibility: Git diagnostics distinguish identity/read/write
  states without Git mutation or credential disclosure; standalone Core works
  without Lumio. Legacy configuration remains explicit and unchanged.

Use existing native retention, source-approval, composite consent, activation
and standalone checks where they already establish these invariants. New tests
target the profile binding and composed journey, with independently authored
expected content. Reuse the planned Lumio exchange service and transfer evidence
where applicable; test both private transfer paths without duplicating every
transport case. Final qualification uses installed compatible packages, BB/Pi
and distinct environments, local and supported S3 publication, and a real
human confirmation. Service/test/repository authorization belongs to the later
execution plan. This document reports no executed qualification.

## 8. Capture and next handoff

Vocabulary: reuse Lumio Source Registry, Source Artifact, Source Exchange and
Source Baseline Snapshot, and Core Storage Profile, Source Approval and Bound
Release. A private local profile is configuration, not a new domain entity or
an alias for Core's data-source Storage Profile; no glossary term is added.

Architecture: preserve ADR-0026's direct SDK and Core-last activation, and
ADR-0024's operator-managed original boundary. The accepted ADR-0026 amendment
records the private configuration choice over repeated flags or implicit
global defaults. No new ADR is needed. Producer page-profile semantics remain
unchanged; Lumio specification 0010 owns the shared configuration format.

Uncertainty: no material behavior decision remains open. The owner approved
this revision and its scoped amendments on 2026-10-23.
[Plan0033](../plans/2026-10-23-0033-managed-knowledge-authoring.md) and reconciled
Lumio plan0010 own interface spelling, setup and qualification dependencies;
their implementation decompositions remain proposed for review. Do not start
a Core consumer against an
unaccepted producer interface. No tickets, implementation or services are
authorized by this capture.
