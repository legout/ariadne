# Plan 0010: External-agent authoring journey

Execution authority — 2026-10-23: after receiving these exact plans, the owner
said “Go ahead with the plan.” This approves this decomposition and supervised
isolated implementation in dependency order. Earlier proposed/no-implementation
status below records planning history and is superseded only for this execution
scope. No target integration, push, PR publication, release or production access.
Harness human confirmations and fixture-remote/service selection remain required
when their planned steps are reached; never fabricate them.

Status: prior slices approved for supervised isolated execution; revision 5's J5a
decomposition is prepared for review before implementation. Plan revision: 5.
Date: 2026-10-25.

Scoped setup amendment — 2026-10-25: the owner selected previewed, confirmed
empty-KB creation with explicit namespace/authoring location, retaining explicit
adoption for nonempty KBs, and requested spec0010/plan0010 reconciliation before
implementation. Specification revision 5 §2.2/AC12 owns that resolved behavior.
This revision adds one sequential J5a slice and its agent-facing confirmation
interface below. No product implementation is part of this reconciliation;
earlier isolated execution authority does not imply that J5a has been implemented
or its new interface reviewed. Target integration/publication remain excluded.

Scoped execution amendment — 2026-10-24: the owner approved the proposed J4 exchange
amendment, directed reconciliation of specification0010, ADR-0031 and this plan,
and authorized continued supervised J4 implementation and validation. Revision 4
adds private per-attempt staging and conditional final copy, operator-managed
residue, and an explicit service capability requirement. No dependency change,
public interface change, target integration, push or publication is authorized.

Readiness: approved spec0010 revision 5 includes metadata-only bootstrap, the
shared §2.1 private profile contract, the scoped §6 exchange amendment and
confirmed empty-KB creation with explicit nonempty adoption in §2.2.
Ariadne spec0033 revision 1 and its public consumption contracts remain unchanged.

## Goal, authority and capture

Deliver the complete BB + Pi document contribution journey in
[specification 0010 revision 5](../specs/2026-10-23-0010-external-agent-authoring-journey.md),
including independent contributor/maintainer environments and the private
S3-compatible exchange with manual bundle fallback.

The owner approved the specification and [ADR-0031](../adr/0031-private-source-handoff-for-external-agents.md)
as written in BB thread `thr_52d92z7irz`, then requested this plan and an assessment
of Ariadne applicability. The owner explicitly said **do not start implementation**.
That planning-only restriction is historical: the execution header and scoped
J4 approval above now authorize isolated implementation. Service fixtures still
require explicit parent allocation; external PR creation, target integration,
push, release and production-data access remain excluded.

Capture: Source Handoff Bundle, Source Exchange and Source Baseline Snapshot are
recorded in [CONTEXT.md](../../CONTEXT.md); ADR-0031 is accepted with the scoped
bootstrap amendment. Spec0010 r1 was approved as written; r2 captures the subsequent
owner-selected metadata-only bootstrap; r3 captures the explicitly approved shared
private profile contract. On 2026-10-23 the owner approved Ariadne spec0033r1,
ADR-0026's amendment and Lumio §2.1 and requested this reconciliation, again
excluding implementation at that planning stage. The owner subsequently granted
execution and approved the J4 amendment. Revision 4 records it in spec §6, the
transfer transport decomposition, J4/V4 and later operator guidance; ADR-0031
records why. Temporary staging introduces no new domain term. Revision 5 captures
the owner's empty-KB setup decision in §2.2/AC12 and J5a/V5a. Existing namespace,
Control File and Source Reference Manifest terms suffice; no glossary addition
or ADR amendment is needed. This is ordinary confirmed creation within ADR-0029,
not a new authoring lifecycle. Shared private-profile format/public signatures,
ADR-0031 and Ariadne spec0033 remain unchanged. J5a's concrete interface and
decomposition below await review before dispatch; the behavior choice is resolved.
Planning Contract version 1; installed skill revision provenance unknown.
Initial baseline inspected: `dcc95a9`; J5a's existing setup/profile/manifest seams
were inspected at reviewed J5 result `6e5bc981`. No tests or runtime changes were
made during this planning reconciliation. New test names below are planned checks,
not passing evidence; prior execution evidence remains in the existing run state.

## Ariadne applicability and scope boundary

There are three distinct repositories/uses of Git: this software monorepo, a
standalone Ariadne data project's authored content, and an integrated Content
Repository containing Core inputs plus Lumio `knowledge/`. The approved journey
does not change this software repository's contribution process.

| Planned capability | Standalone Ariadne | Integrated Ariadne + Lumio | Disposition |
| --- | --- | --- | --- |
| Git authentication diagnostics | Same practical need; current setup checks Git/root/identity but not remote authentication | Same host Git credentials | Share operating guidance. Do not add a mandatory Lumio dependency or a new shared package for one helper. An Ariadne CLI wrapper is a separate follow-up. |
| Document extraction and private originals | Core ADR-0024 keeps originals operator-managed; no Core-owned archive | Lumio owns curated pages and their original-source lineage | Reuse the Lumio operation for integrated knowledge. Do not replace Ariadne's data-source registry or document access approvals. |
| Human-readable candidate review | Existing Core review/admission already binds exact revisions | A KB-only review cannot approve changed contracts, OSI, Policies or measured evidence | Keep both existing Core reviews and overall admission. Do not substitute Lumio's body review for Core's full contract review. |
| Source handoff | Does not transfer database access, data-source approval or numeric validation | Directly useful for managed Knowledge Sources behind `knowledge/` | Transfer Lumio sources only; revalidate Core inputs in the receiving environment. |
| Multi-page and ontology authoring | No automatic migration of standalone Context pages | Useful within the native Lumio subtree and existing profiles | Preserve profile bytes and validate through the existing SDK; no second Context mirror. |
| Final activation | Core Git Admission remains authoritative | Overall Bound Release activates the Core descriptor last | Preserve direct SDK calls, pinned release identity and independent source permissions. |

Evidence and the important gap:

- [Core setup](../../../../products/ariadne/packages/ariadne-data/src/ariadne/setup.py)
  reports Git availability, repository root and commit identity.
- [Core Git-only ADR-0024](../../../ariadne/project/adr/0024-git-only-durable-authored-state.md)
  separates private originals, Source Approval and Git Admission.
- [Integrated ADR-0026](../../../ariadne/project/adr/0026-lumio-sdk-bound-governed-releases.md)
  owns one Content Repository, direct optional SDK consumption, one overall
  confirmation and Core activation last.
- In [lumio_context.py](../../../ariadne/packages/ariadne-data/src/ariadne/lumio_context.py),
  `prepare_release` calls `native.preview_publication` and `publish_and_verify`
  calls `publish_revision` without a private `source_registry`, `artifact_store`
  or `retention_required` argument. CLI environment resolution is not invoked.
- Lumio's existing
  `test_git_authoring.py::test_managed_bindings_require_an_explicitly_selected_registry`
  specifies the resulting refusal for managed bindings without a selected registry.

The approved [Ariadne spec0033](../../../ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md)
and proposed [plan0033](../../../ariadne/project/plans/2026-10-23-0033-managed-knowledge-authoring.md)
own Core wiring, composed contribution review and integrated qualification.
Lumio owns the shared private configuration resolver (JP) and composable
knowledge review (J2). Core consumes their accepted public interfaces; it does
not read global defaults or import CLI internals. J6 qualifies standalone Lumio
and protects existing paired behavior; plan0033 owns the new integrated journey.
Do not expand J6 into a second Core implementation or duplicate that qualification.

## D0 — Fresh contributor baseline: resolved

Code inspection found that `git_authoring._refuse_manifest_drift` calls
`source_references.validate_source_references` with the selected registry; it
resolves **every** binding in the complete candidate, including unchanged baseline
pages. A fresh clone with an empty private registry cannot therefore add a new
managed page to a nonempty managed KB, even when its new source is retained.
Spec0010 r1 defined contribution handoff but did not choose how this initial
contributor history is provisioned. An empty-KB demonstration would hide
this reachable failure and cannot establish the general independent-host journey.

The owner selected a maintainer-approved, namespace/revision-bound
metadata-only bootstrap for the exact baseline Source Versions, leaving existing
originals private to the maintainer. It must preserve metadata integrity, expose
missing originals truthfully, confer no publication permission and never mark
artifacts retained without verification. New/changed sources still follow the
approved raw-byte retention and handoff path. Spec0010 r2 §5.1/AC11 and the scoped
ADR-0031 amendment own this explicit extension: use a distinct artifact kind,
never a full-source bundle with missing payloads.

Rejected alternative: require contributors to receive the exact baseline sources through
the existing full bundle path. This is simpler mechanically but grants access to
originals unrelated to the edited pages and increases initial transfer size.
Do not assume that access from a Git clone or relax exact-version validation.

J0 now delivers the bootstrap prerequisite before J1. J3 reuses its validated
metadata-import path; J4 transports both explicit artifact kinds. J5/J6 cover
fresh-contributor setup against a nonempty baseline. The selected expected digest
must come from maintainer-approved setup or operator selection, not from trusting
an arbitrary archive's claimed origin.

## Execution structure

One sequential Pi writer in an isolated registered worktree; no simultaneous
writers to `cli.py`/`__init__.py`. Runtime and exact role/model preflight are deferred
until execution is authorized and follow `orchestrate-implementation`. Use the
verified host and its lifecycle controls; no provider fallback. New worktrees use
`${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/`. Supervised candidate delivery
does not authorize target integration.

Python 3.14+, existing msgspec/msgpack/PyYAML, Git, retained optional document
processors, and the existing optional `obstore` S3 capability. No new mandatory
dependency, provider, application runtime or central service. The module names
below are owned new files, not a general-purpose framework.

Sequence: **JP → J0 → J1 → J2 → J3 → J4 → J5 → J6**.
Review JP before its public interface is consumed. Default cross-product order is
this sequence followed by Ariadne A0 → A1 → A2 → A3; no parallel writers. Each slice includes its public Python
and CLI route and focused evidence. Review J0's metadata import contract before
J1 consumes it. J1–J2 share the authoring review boundary;
J3's bundle/import contract is reviewed before J4 consumes it; J4's transfer
boundary is reviewed before the live journey. Final candidate review covers
unreviewed setup/skill changes and integration effects, not settled findings.

## Interface inventory for plan approval

Paths here are relative to `products/lumio/packages/lumio-wiki/src/lumio_wiki/`.
All new JSON results include `schema_version: 1`, a bounded operation result and
stable error `code`/safe `message` on failure. Errors have nonzero exit status;
inspect/preview report explicit readiness and blockers, not approval. Preserve
existing commands and their JSON contracts.

| CLI | Public Python interface | Owner |
| --- | --- | --- |
| `private-profile inspect <file> --kb <kb> --json` | `load_private_profile(profile_path, *, kb_root) -> PrivateSourceProfile` | `private_profile.py`; parse/validate only |
| `source-bootstrap export <kb> --revision <commit> --output <snapshot> --source-registry <dir> --json` | `export_source_baseline(kb_root, revision, *, source_registry, output_path) -> BaselineExport` | `source_handoff.py` |
| `source-bootstrap inspect/import <kb> --snapshot <file> --digest <sha256> --revision <commit> --source-registry <dir> [--confirm <preview-digest>] --json` | `inspect_source_baseline(...) -> BaselinePreview`; `import_source_baseline(..., confirmation) -> BaselineImport` | `source_handoff.py`; import without confirmation previews |
| `extract <file> --output <private-dir> --json` | `extract_source(source_path, *, output_dir) -> ExtractionResult` | `authoring_journey.py`, wrapping existing processors |
| `ingest-candidate <kb> --candidate <file> --source-registry <dir> --json` | `ingest_candidate(kb_root, request, *, source_registry, artifact_store) -> CandidateResult` | `authoring_journey.py`, reusing native candidate validation/mutation |
| `authoring-review <kb> --base <full-commit> --json` | `review_authoring_candidate(kb_root, base_revision, *, source_registry=None) -> AuthoringReview` | `authoring_review.py` |
| SDK composition only | `review_knowledge_changes(kb_root, base_revision, *, source_registry=None, candidate_tree=None) -> KnowledgeChangeReview` | `authoring_review.py`; no submission approval |
| `authoring-check <kb> --review <report.json> --revision <full-commit> --json` | `check_authoring_commit(kb_root, review, revision) -> CommitCheck` | `authoring_review.py` |
| `source-handoff export <kb> --base <commit> --revision <commit> --output <bundle> [--references <file>] --source-registry <dir> --json` | `export_source_handoff(kb_root, base_revision, revision, *, source_registry, artifact_store, output_path, references=None) -> HandoffExport` | `source_handoff.py` |
| `source-handoff inspect/import <kb> --bundle <file> --digest <sha256> --revision <commit> --source-registry <dir> [--confirm <preview-digest>] --json` | `inspect_source_handoff(...) -> HandoffPreview`; `import_source_handoff(..., confirmation) -> HandoffImport` | `source_handoff.py`; import without confirmation previews |
| `source-exchange upload --file <transfer> --exchange <s3-uri> --json` | `upload_source_transfer(transfer_path, *, exchange) -> SourceTransfer` | `source_exchange.py`; both explicit artifact kinds |
| `source-exchange download --id <id> --digest <sha256> --exchange <s3-uri> --output <file> --json` | `download_source_transfer(transfer_id, digest, *, exchange, output_path) -> SourceTransfer` | `source_exchange.py`; both explicit artifact kinds |
| `git-check <project> [--remote <name>] --json` | `check_git_connection(project, *, remote=None) -> GitConnectionReport` | `git_connection.py` |
| `setup <kb> --journey --private-profile <file> [existing setup flags]` | existing setup composition | `cli.py` and `env_loader.py` |
| `setup <kb> --journey --create-empty --namespace <namespace> --private-profile <file> [--confirm <setup-digest>] [--json]` | CLI composition; no new public SDK export | J5a; `cli.py`, internal `journey_setup.py`, shared private-profile validation |

### Confirmed empty setup interface (J5a; revision 5 proposal)

`--create-empty` explicitly selects §2.2 creation and requires `--journey`.
`<kb>` is the author-selected path inside an existing registered Git worktree;
the preview identifies its resolved repository root, branch and KB subtree.
`--namespace` supplies the explicit namespace (interactive setup may collect it
when omitted). Namespace is never silently generated or taken from an unrelated
profile. The profile must agree with the selection. Setup never creates/switches
Git branches or commits; native Git prepares the chosen worktree beforehand.

Without `--confirm`, a noninteractive call validates and returns a read-only
preview. `--confirm <setup-digest>` authorizes the exact freshly revalidated
preview; a mismatch refuses before writes. Interactive setup uses the same
preview/apply path and explicit confirmation after collecting required choices.
With a missing private-profile file, only the existing interactive collection
may propose its contents; noninteractive callers select a valid existing profile.
All creation routes validate the proposed manifest/namespace/profile before any
target writes, without weakening ordinary adopted-KB validation.

The creation-only `--json` envelope uses `schema_version: 1`, `ok`,
`operation: setup_empty`, `phase: preview|applied`, `ready`, `setup_digest`,
`authoring` (repository root, branch, subtree, current commit or explicit unborn
state), `namespace`, `actions`, `blockers` and `next_actions`. Actions identify
local paths and create/update/install intentions without credentials. Only the
local preview carries private locations. `setup_digest` is SHA-256 of canonical
JSON for the selected authoring identity, namespace, action paths/content hashes,
private non-secret declaration and relevant existing/absent input fingerprints;
exclude diagnostic timing, live credential values and capability messages.
No persisted setup-approval database or receipt is introduced. Errors use the
existing bounded versioned envelope, including `invalid_empty_setup`,
`setup_confirmation_mismatch`, `setup_target_changed`, `adoption_required` and
`setup_incomplete`; preview blockers are not approval. Existing setup without
`--create-empty` retains its output contract. Reuse existing submission settings
and optional skill flags rather than adding another configuration source.

### Shared private profile interface (JP; consumed by Ariadne A1)

New public exports from `private_profile.py` and `lumio_wiki.__init__`:

- `load_private_profile(profile_path, *, kb_root) -> PrivateSourceProfile` reads
  one explicitly selected file, validates schema/namespace/containment and returns
  an immutable non-secret declaration. It opens no registry/store and reads no
  credential values. `private-profile inspect` uses only this route, reporting
  safe validity and declared capabilities, not private paths or credential names.
- `resolve_private_profile(profile, *, kb_root, needs, environ=None) -> ResolvedPrivateSources`
  accepts a frozen set drawn from `registry`, `artifacts`, `exchange`; default
  `environ=None` uses the current process environment explicitly at call time.
  It resolves only required resources and returns `source_registry`,
  `artifact_store`, `exchange` (unused entries `None`), `binding`, `binding_digest`
  and `retention_required`. These runtime objects are not JSON-serialized.
  Publication requests `registry` and `artifacts`; bootstrap only `registry`;
  exchange upload/download only `exchange`. Extraction does not call it.

Profile JSON v1 (unknown/duplicate keys and wrong types refuse): required
`schema_version: 1`, `namespace`, `source_registry` (absolute directory),
`retention: required|disabled`, `artifact_store`; optional `exchange`.
An artifact store is `{kind: local, root: <absolute-directory>}` or the S3
connection shape below. Exchange accepts the S3 shape only. Omitted exchange
supports manual transfer. No inline secrets, relative paths or default profile.

S3 shape: `kind: s3`, `bucket`, `prefix`, `endpoint`, `region`,
`url_style: path|vhost`, and `credentials` containing `access_key_id_env`,
`secret_access_key_env`, optionally `session_token_env`. Endpoint, region and
style are explicit non-secret literals; credential fields name variables only.
Validate against existing supported S3 transport rules and instantiate existing
adapters with those resolved values, bypassing implicit global/provider fallback.
Never place secrets in adapter representations, public diagnostics or bindings.

`binding` is a private JSON-compatible record with `schema_version: 1`, namespace,
retention and only requested resource declarations/effective identities. Resolve
local roots canonically; bind S3 bucket/prefix/endpoint/region/style and declared
credential references, never secret values. Canonical JSON (sorted keys, compact
separators, UTF-8) SHA-256 defines `binding_digest`. Exclude profile-file location,
formatting and unused connection configuration. No credential value is hashed.
The Core plan owns private review storage and its public-safe digest marker.

Add `--private-profile <file>` to bootstrap, ingest-candidate, knowledge review,
source-handoff, source-exchange and existing native publication CLI routes.
Exchange commands additionally require `--kb <kb>` when a private profile is
selected, supplying the explicit namespace/containment root to the resolver;
legacy explicit-exchange commands need no new KB argument. With it, reject competing explicit flags and configured environment/project
selections for the same registry/store/retention/exchange resources. Do not merge
settings. Without it, retain legacy behavior. No library import resolves profiles.
`--source-registry`/`--exchange` in the inventory above become alternatives to
profile selection, not simultaneous required arguments. Lower-level Python
operations continue accepting explicit adapters, not configuration paths.

Setup `--journey --private-profile <file>` uses an existing file or interactively
previews and writes a new one. Noninteractive missing-file setup reports the
required selection without inventing defaults. Changes use existing setup
confirmation conventions; no silent replacement. Do not store the selected path
in tracked content. Runtime submission-mode/Git settings remain separate.

Full Python import/inspect parameters: `(kb_root, bundle_path, revision, *,
expected_digest, source_registry, artifact_store)`, plus `confirmation` for
`import_source_handoff`. `exchange` is an explicitly constructed private transport
configuration/client, not an implicit global. Result records are frozen msgspec
records. No library import reads credentials or configuration as a side effect.
Baseline inspect/import use `(kb_root, snapshot_path, revision, *, expected_digest,
source_registry)` plus `confirmation` for import; they never need artifact-store
access. Baseline private provenance binds the snapshot digest/revision to imported
records. Transfer kind is explicit in all results. The unreleased transport names
above replace plan r1's handoff-only spellings, sharing one transport implementation.

Candidate request v1: explicit base revision; original source records with stable
`source_id`, local original path, expected digest, and intent `new` or `update`;
authored page paths with explicit Entity/source bindings; optional complete
`lumio.yaml` candidate. Working request and pages live outside the content repo.
The handler computes digests and validates paths/identity rather than trusting
declared values. New/update intent is compared with the selected base manifest;
new IDs absent there cannot silently reuse conflicting private history. This
initial candidate command covers page additions/updates and ontology edits;
existing native helpers still own removal/rename/merge, which review must display.
For a body/ontology edit reusing an exact baseline binding, resolve the already
imported version record; do not require a raw-file field or invent a new Source
Version. New/updated version records require actual original bytes. Candidate
reports separate metadata coverage from verified retained-original coverage.

Review v1: full base commit, namespace, repository-relative KB subtree, complete
submitted Git tree identity, relevant path/blob identities, validator identity,
validation issues, bodies/body diffs, structured semantic changes and review
digest. Read-only Git inspection may prepare Git objects/index in private temporary
storage, but must not alter the user's index/worktree or create a commit.
The agent stages intended paths before review. Capture the full staged tree and
HEAD, disclose excluded unstaged/untracked changes, and run validation against
that captured tree. `candidate_tree` optionally names an existing immutable tree
in the same repository supplied by a composing caller; absence captures the
staged tree. Never mix captured bodies with mutable working-file validation.
The reusable `KnowledgeChangeReview` carries namespace/subtree, base, exact
KB path/blob identities, complete knowledge bodies/semantic changes, validation
issues and digest, but never a whole-repository approval. The standalone wrapper
combines it with the submitted full tree and enforces its existing KB-only rule.
Core A2 composes this result with Core/full-tree review; it does not call a
standalone checker with a bypass flag. A standalone candidate submission contains
only the selected KB changes; changes elsewhere in
the repository need their own review and cannot ride along. `authoring-check`
verifies the whole commit against the reviewed base/candidate, not just a body or
KB-only fingerprint. It does not claim that a human approved the report.

Native `git add`/`git commit` and `gh` remain skill-owned external operations.
After commit verification, export/upload precedes PR creation. Report the exact
submission action before human confirmation, including private source transfer.
Inspect an existing remote branch/PR by exact repository/head/base on retry; never
force-push or auto-merge to recover. Changes after confirmation require rereview.

## Transfer formats v1 and transport bounds

Use an uncompressed tar archive of regular files: `manifest.json` and
`artifacts/<sha256>`. Fixed entry ordering and normalized tar headers make repeated
export of the same captured facts byte-identical. Never extract arbitrary archive
names into a destination tree: validate the complete inventory and stream known
payload entries into verified staging. No dependencies beyond the standard
library are needed for the container.

Full handoff manifest JSON v1 contains `schema_version`, `kind: source-handoff`,
random opaque `transfer_id`, `namespace`,
`kb_subtree`, `base_revision`, `revision`, `source_manifest_digest`, changed binding
records `(entity_id, source_id, old_digest|null, new_digest|null)`, and exact version
records `(source_id, content_hash, size, content_type|null, filename|null,
origin_created_at, intent)`. The ID is created once per export artifact and reused
on retry; reconstructing a new export can create a different ID and must not be
described as resuming the old artifact. The complete archive SHA-256 is supplied
out-of-band in the safe handoff result/PR. Equal payload digests may share an
archive entry, but distinct Source IDs remain distinct identities. Supplementary
references must resolve in the explicitly selected contribution revision.

Metadata snapshot manifest v1 contains `schema_version`, `kind: source-baseline`,
`transfer_id`, `namespace`, `kb_subtree`, `revision`, `source_manifest_digest`,
complete `(entity_id, source_id, content_hash)` binding records and the exact
referenced version metadata `(source_id, content_hash, size, content_type|null,
filename|null, origin_created_at)`. It has no artifact entries, lifecycle intent,
availability flag or original/extracted text. A source-baseline archive contains
only `manifest.json`; the full handoff importer refuses this kind, and the baseline
importer refuses full-source archives. Both share strict archive/metadata parsing.
Metadata snapshots are bounded by the same 4 MiB manifest ceiling, with at most
10,000 exact version records and 50,000 binding records. Lower deployment limits
are allowed; exceeding a limit is an explicit refusal, never partial bootstrap.

Reject duplicate JSON keys, unknown schema versions/fields, duplicate logical
records, invalid digests/IDs, unexpected entries, links, path escapes and mismatched
sizes. Default hard ceilings: 512 MiB per original (current store limit), 2 GiB
total payload, 1,000 unique payloads, 4 MiB manifest, 8 MiB container overhead;
deployment configuration may lower these limits. Stream container I/O and do not
load an entire multi-source bundle into memory. The existing per-original store
API can process one bounded original at a time. Refuse limits before canonical
mutation; no silent truncation or split pretending to be a complete handoff.

Import metadata comparison includes immutable digest, size and populated safe
filename/media type. Local registration timestamps may differ and must not cause
a false identity conflict; retain the contributor's `origin_created_at` as labeled
private provenance rather than falsifying local creation time. An existing
populated immutable value is never overwritten. All sources must match the KB
namespace's explicitly selected registry scope; a registry already explicitly
assigned to another namespace is refused. No automatic whole-registry migration.
The metadata-import method validates complete input before its locked additive
registry commit; it cannot set `artifact_available=True`. Existing locally verified
versions keep their state. The full-source import path uses this metadata seam
then marks availability only after retained-byte verification. Keep origin metadata
in private provenance and maintain honest local timestamps.

The private exchange stores immutable final `<id>/transfer.tar` and a small
`ready.json` completion record containing only format version, artifact kind, ID,
byte count and transfer digest. Capture and validate local input once in bounded
private temporary storage outside the Content Repository, then stream those same
bytes through multipart put to a new private
`_staging/<256-bit-random-attempt-id>/transfer.tar` key under the exchange prefix.
Retries never reuse a staging key. These temporary objects are excluded from the
final-object immutability guarantee and are never published as transfer references.
Use atomic server-side copy-if-absent for the final key, verify its complete byte
count and digest, then publish `ready.json` create-only. Readers never import
without a matching completion record and expected digest. Same ID/different bytes
is a conflict. A lost response is recovered by verifying the existing immutable
final object; a partial upload cannot be reported as ready. Never fall back to
check-then-overwrite if conditional copy is unsupported: report a safe distinct
capability refusal and retain manual transfer.

Temporary objects and abandoned multipart uploads may remain after success or
interruption. Their lifecycle is operator-controlled; no cleanup command,
automatic remote deletion or signed-link distribution is added. Remove
operation-owned local temporary files when finished. The selected service must
support multipart upload and atomic conditional server-side copy. The dedicated
SeaweedFS 4.45 probe proves that service's compatibility only.

New project configuration: `LUMIO_SOURCE_EXCHANGE` (credential-free URI),
`LUMIO_SUBMISSION_MODE=commit|github-pr`, `LUMIO_GIT_REMOTE`, and
`LUMIO_GIT_TARGET_BRANCH` join the existing nonsecret allowlist. Exchange endpoint,
region and credential selection are explicit per invocation/environment using the
existing S3 resolution machinery; exchange construction must not mutate a
canonical artifact/publication client or inherit an unrelated endpoint silently.
Setup records references/settings only; operator-provisioned IAM remains external.

## JP — Resolve an explicit private profile through the public SDK and CLI

- [ ] Add the exact profile parser/resolver/records above with operation-scoped
  resource selection and safe errors; export them from the public SDK.
- [ ] Deliver `private-profile inspect` and profile selection on existing managed
  ingest/publication CLI routes, preserving legacy no-profile behavior. New journey
  commands adopt this selection as their slices land; setup composition stays J5.
- [ ] Preserve existing source containment, store integrity and optional-dependency
  behavior; no new registry lifecycle, transport or credential framework.

Files: create `private_profile.py`, `packages/lumio-wiki/tests/test_private_profile.py`;
modify `cli.py`, `__init__.py`; reuse `source_registry.py`, `artifact_store.py` and
existing explicit S3 construction seams. Prerequisites: approved plan and separate
execution authority, isolated Python 3.14 environment. Produces the public
interface consumed by every profile-backed journey route and Ariadne A1.

Validation VP, high risk public configuration/credential boundary, `new-test`:
`test_profile_selection_is_explicit_and_operation_scoped` uses hand-authored local
and S3 declarations and distinct environment variable names. Assert exact selected
paths, registry-only bootstrap with unavailable S3 credentials, refusal of conflicting
selection, safe missing-credential errors, unchanged digest on credential-value
rotation and changed digest for a different endpoint. Parameterize malformed
version/namespace/inline-credential/relative-path cases from §2.1, not parser output.
Use existing adapter checks for transport correctness; do not duplicate S3 I/O.
`private-profile inspect` must leave selected paths absent and reveal no secret
sentinel. Review VP before downstream consumers; one authorized fix/delta cycle.
Completion: installed API/CLI can select the same explicit source configuration;
profile mode never silently consumes unrelated defaults. Covers spec §2.1 and
setup/credential parts of AC1/AC10; Core consumption is tested in its own plan.

## J0 — Bootstrap a fresh contributor from exact baseline metadata

- [ ] Implement baseline export, inspect and confirmed import using captured Git
  bindings and maintainer metadata, with the distinct metadata-only format above.
- [ ] Add the narrowly scoped additive metadata-registration method and private
  origin record. Validate exact namespace/base/digest/coverage before mutation;
  preserve immutable conflicts and locally verified availability on retry.
- [ ] Demonstrate missing originals honestly through existing source inspection
  and required-retention publication checks. Do not weaken either gate.

Files: create `source_handoff.py` for the two known transfer kinds, initially
implementing baseline operations; modify `source_registry.py`,
`private_provenance.py`, `cli.py`, `__init__.py`. Reuse Git capture/reference
validation; create `packages/lumio-wiki/tests/test_source_baseline.py`.
Prerequisites: accepted JP, plan/execution approval, isolated Python 3.14 environment. Produces
`BaselineExport/Preview/Import` and the exact-version registry entries consumed by
J1 and J3. Covers AC11; no S3 or raw originals needed on the receiving machine.

Validation V0, high risk private-history/public import boundary, `new-test`:
`test_metadata_bootstrap_preserves_history_without_artifacts` uses a nonempty
managed base and separate contributor/maintainer registries. The fixed fixture
defines known source IDs/digests and one locally retained contributor version.
Import/reimport must resolve every exact base binding, preserve prior history and
retained state, and create no original files; publishing with required retention
must still refuse for missing originals. `test_metadata_bootstrap_rejects_mismatch`
parameterizes wrong namespace/base, missing coverage, conflicting metadata and a
forged availability/payload field, using hand-authored invalid v1 manifests.
The oracle is the declared baseline and filesystem/store state, not the exporter.
Review this boundary before J1. Completion: a fresh contributor can resolve its
nonempty base without receiving original documents or approval to publish.

## J1 — Extract a source and author a complete managed candidate

- [ ] Implement the extraction and candidate CLI/API routes above using existing
  `SourceProcessor`, exact source registration, retention and candidate validators.
  Preserve actual extraction provenance and old single-page ingestion behavior.
- [ ] Apply a multi-page/ontology candidate only after complete validation and
  verified retention; rollback authored edits on failure while disclosing reusable
  private residue. Retain existing mutation conflict checks.

Files: create `authoring_journey.py`; modify `cli.py`, `__init__.py`,
`git_authoring.py`, and only the necessary `private_provenance.py` seam. Reuse
`source_processor.py`, `source_references.py`, `source_registry.py`, `artifact_store.py`
and `mutation.py`; no replacement converter or registry lifecycle.
Tests: create `packages/lumio-wiki/tests/test_authoring_journey.py`.
Prerequisites: reviewed J0 and isolated Python 3.14 environment.
Consumes existing processors/store interfaces; produces the candidate and
extraction contracts consumed by J2/J6. Covers AC2 and source portion of AC10.

Validation V1, normal risk, `new-test`: a hand-authored source with two explicitly
specified Entities and a known predicate produces exactly those pages and exact
raw bytes; an invalid cross-reference or retention failure leaves authored content
unchanged. Independent expected text/Claims are fixed from the fixture, not model
output or implementation serialization. Use focused tests
`test_candidate_binds_two_pages_and_ontology` and the parametrized
`test_candidate_failure_preserves_authored_tree`. Reuse existing processor format
checks; no second converter suite. Completion: public CLI demonstrates this slice
without a model provider, commit or publication. The positive candidate test starts
from J0's nonempty metadata-only baseline and adds the retained new source, also
covering AC11's candidate-authoring step; it must not secretly seed baseline bytes.

## J2 — Review bodies and verify the submitted Git commit

- [ ] Add candidate review with complete content identity, readable body changes
  and semantic changes; add exact commit comparison using the captured report.
- [ ] Export `review_knowledge_changes` and `KnowledgeChangeReview` for Core A2
  composition; reuse the same knowledge body/semantic validation in the standalone
  wrapper. The partial result never authorizes whole-repository submission.
- [ ] Include additions/deletions, frontmatter-only and ontology-only edits. Fail
  clearly on unrelated submitted files, incomplete review scope or changed blobs.
  Provide structured results without claiming approval or running Git mutations.

Files: create `authoring_review.py`; modify `cli.py`, `__init__.py`; reuse native
Git capture and Claim-diff helpers in `git_authoring.py`/`ingest.py`.
Create `packages/lumio-wiki/tests/test_authoring_review.py`.
Depends on J1; consumes validated candidates and produces `AuthoringReview` for
native Git submission and J6, plus `KnowledgeChangeReview` for Core A2. Covers AC3 and integrity part of AC4.

Validation V2, high risk public review contract, `new-test`:
`test_review_detects_changed_commit` uses native Git and a hand-written change
set; parameter cases are an unchanged candidate, post-review frontmatter edit,
unrelated staged file, and an actual commit hook altering content. Expected
result: only the exact candidate passes; source bytes never enter the report.
Assertions compare approved fixture facts and Git blobs, not helper internals.
Use the same case to assert the knowledge-only result reports the authored bodies
while the standalone wrapper rejects unrelated changes; Core composition is VA2.
Review J1–J2 together before J3 uses the resulting committed contribution.
Completion: the native Git commit is independently checked before any submission.

## J3 — Transfer and import exact sources manually

- [ ] Implement bundle export, preview and confirmed import with exact Git
  selection, versioned validation, integrity checks and bounded archive handling.
- [ ] Add namespace-scoped registry import and origin metadata handling through
  supported methods, preserving existing history and explicit version intent.
- [ ] Make import retry-safe after partial store/registry I/O; allow supplementary
  exact references and refuse missing originals before successful export.

Files: extend J0's `source_handoff.py`; modify `source_registry.py`,
`private_provenance.py`, `cli.py`, `__init__.py`; reuse artifact store and Git
capture. Create `packages/lumio-wiki/tests/test_source_handoff.py`.
Depends on accepted J0–J2; exports committed reviewed content, produces the exact
bundle contract used by J4. Covers AC5 source state, AC6–8 and AC9 binding reuse.

Validation V3, high risk external bundle/private history boundary, `new-test`:
`test_manual_handoff_preserves_history_and_retries` uses two separate registries,
an existing unrelated source, a deliberate updated version and immutable original
bytes; checks import, repeat, supplementary references and interrupted import.
`test_handoff_rejects_invalid_bundle` parameterizes the distinct AC7 scenarios:
wrong namespace, corrupt payload, missing entry, duplicate/path-escaping entry,
metadata conflict, unknown format and exceeded configured limit. Build invalid
archives directly from the documented v1 contract, not exporter output alone.
Asset: maintainer history/files; realistic input: a malformed contributor bundle
delivered through the actual private transfer path. No arbitrary file writes or
source execution; no invented attacker requiring stolen credentials.
Immediate contract review before J4. Completion: manual transfer succeeds without
S3 and rejects invalid input before canonical registry mutation.

## J4 — Exchange bundles through private S3-compatible storage

- [ ] Implement immutable upload/download for both transfer kinds and completion
  record validation with the existing optional S3 client. Reuse J0/J3 verification; never build another
  importer. Report safe auth, missing-object, conflict and integrity errors.
- [ ] Capture and validate local bytes once, multipart-upload through a unique
  private staging key, and atomically copy-if-absent to the final transfer key.
  Verify the complete final object and publish readiness last. Recover retries
  and lost responses by checking immutable final objects; refuse conflicts and
  unsupported conditional copy without an overwrite fallback.
- [ ] Pin conditional-copy configuration only on exchange clients and keep
  canonical source/publication client configuration independent. Retain temporary
  remote residue under operator lifecycle control; remove local operation-owned
  temporary files.

Files: create `source_exchange.py`; modify `cli.py`, `__init__.py`,
`env_loader.py`; narrowly reuse S3 client construction without unrelated CLI
refactoring. In `private_profile.py`, configure `copy_if_not_exists: multipart`
only for exchange clients, preserving profile endpoint/credential isolation and
leaving artifact/publication clients unchanged. The explicit CLI route pins the
same effective exchange behavior. No public JP contract changes. Create
`packages/lumio-wiki/tests/test_source_exchange_s3_compat.py`.
Depends on reviewed J3. Produces `SourceTransfer` for J5/J6. Covers AC5, AC7, AC11,
network retry and transfer-disclosure part of AC10.

Validation V4, high risk distributed completion/credentials, `new-test`:
`test_exchange_completion_and_retry` runs against an explicitly allocated
disposable S3-compatible endpoint with synthetic source bytes and separate
contributor/maintainer credentials. Interrupt before ready publication, retry,
download/import, and attempt same-ID/different-bytes and denied access. Independent
oracle: ready absent until all bytes verify; final digest equals fixture bytes;
denied credentials never retrieve the object; diagnostics reveal no secret. Cover
both artifact kinds in that transfer fixture, including refusal to import a
metadata snapshot through the full-source importer; do not duplicate V0/V3 parsing
cases at the transport layer. Exercise a bundle larger than 5 MiB through the
multipart streaming path, preservation of existing final bytes on conflict,
interruption before readiness and retry, strict download verification, safe
capability/permission errors and staging disclosure boundaries. Keep every
existing assertion. Reuse the feasibility evidence for named-service compatibility;
the new product behavior still receives V4 and independent review.
Use one retained service for V4/J6 where possible, no repeated successful run.
Execution authorization must name the fixture endpoint/service before startup;
missing tooling or permissions is a blocker, not permission to weaken the check.
Review this boundary before J6. Completion: both automated and manual routes feed
the same importer, with no dependency on exchange availability after import.

## J5 — Guide setup, connection checks and skill refresh

Execution note: the original J5 diagnostic/setup surface and F1–F5 repairs have
scoped passing reviews through frozen result `6e5bc981`; this does not satisfy
the newly resolved empty-creation requirement. J5a completes that requirement
before J6. Reuse applicable J5 evidence rather than reopening settled findings.

- [ ] Add read-only Git diagnosis and journey setup composition, including required
  retention, explicit private profile creation/selection and submission mode.
  Use JP's resolver rather than a second profile parser. Exchange credentials stay
  independently selected in the profile; native publication selection remains separate.
  Explain required conditional-copy service capability and operator-managed
  staging/incomplete-multipart lifecycle; unsupported exchange retains manual
  transfer. Contributor
  setup succeeds without publication credentials. Never claim push permission
  merely from `ls-remote` success or invoke test pushes.
- [ ] For a nonempty managed clone, show missing baseline metadata and guide the
  user through selecting an exact maintainer snapshot/digest and previewing its
  import. Setup does not infer trust from exchange listing or import silently.
- [ ] Integrate existing skill drift reports; explain stale/modified installations
  and offer explicit update using current install/update behavior. Preserve local
  modifications until the user selects a concrete replacement action.

Files: create `git_connection.py`; modify `cli.py`, `env_loader.py`; reuse `skill.py`
and existing atomic skill-update implementation. Create
`packages/lumio-wiki/tests/test_journey_setup.py`.
Depends on J0–J4 interfaces; covers AC1, AC11 and setup portion of AC4/AC10.

Validation V5, high risk credential-facing diagnostic boundary, `new-test`:
`test_journey_setup_reports_capabilities_without_mutation` uses a local Git remote
and a controlled failed-auth command response. It checks read success with push
explicitly unverified, absent publication credentials, and redaction of a supplied
credential-bearing failure. Check repository/config/store writes only match the
selected setup action; git-check alone is read-only. Existing skill status/update
tests cover atomic replacement; no duplicate suite. Actual SSH/HTTPS credential
mechanisms are exercised by the selected harness qualification, not inferred from
the local-remote test. Final candidate review includes this boundary.

## J5a — Preview and confirm empty managed-KB creation

One sequential vertical slice, dependent on reviewed J5 and the owner-approved
spec §2.2/AC12. Real caller: an external agent invokes setup without a TTY, or an
operator uses the interactive wizard. Inputs are operator-selected local paths,
namespace and private profile, not hostile content; existing no-overwrite,
containment and confirmation guarantees remain binding. Security: no new network,
credential or dependency boundary; preserve JP's private-path/secret guarantees.
Risk is premature/incorrect local writes and accidental adoption of existing
content, not an invented malicious-operator threat model.

- [ ] Add the creation interface above and a single internal preview/apply path.
  Discover the containing registered worktree read-only from the selected path's
  nearest existing parent when the KB directory is absent; use native Git facts
  and explicit named-branch/unborn state. Reuse namespace/manifest validation and
  seeded Control File generation. Refuse nonempty or conflicting targets before
  any creation. Do not require the nonexistent KB directory to pass an API whose
  precondition is an existing directory, and do not make it exist to bypass that
  precondition.
- [ ] Factor only the private-profile declaration/schema/namespace/containment
  validation needed to validate a prospective KB. Keep one implementation called
  by the existing public loader and setup's preview, with explicit repository root
  and namespace passed internally. Public `load_private_profile` and
  `resolve_private_profile` signatures, existing adopted-KB checks and all JP
  assertions remain unchanged. Never write a temporary target manifest or resolve
  artifact/exchange credentials just to validate an empty setup.
- [ ] Collect required choices and profile declarations before the preview;
  preview all intended writes, then recheck and apply only confirmed actions.
  Create the seeded Control File and namespace-bound manifest with empty sources
  and bindings. Reuse existing project-setting/skill mechanisms after confirmation,
  preserving local modifications and explicit skill-update choices. Refuse target
  or branch drift before apply; never overwrite content that appeared meanwhile.
  Expected filesystem errors produce bounded incomplete results identifying
  operation-owned residue. Do not delete operator files or add a generic rollback
  framework. Rerun selects matching existing managed state or explains conflict;
  it never reinitializes it.
- [ ] Preserve ordinary adopted-KB selection and explicit nonempty adoption.
  Replace the blanket "create and adopt first" guidance for eligible empty targets
  with the previewed route, while giving actionable prerequisites for nonempty
  unadopted content and missing Git worktrees. Update the setup-generated AGENTS
  guidance in the same slice; it must not claim that empty setup requires manual
  manifest authoring. Never infer existing source identities/private history.

Files: create internal `src/lumio_wiki/journey_setup.py` for the ephemeral setup
plan, digest and guarded apply; modify `cli.py` for interaction/serialization and
`private_profile.py` for the shared internal validation seam. Add
`tests/test_journey_setup_creation.py`; retain `test_journey_setup.py` assertions,
adapting only input instrumentation when question order changes. No new public
SDK exports, profile schema/version, environment variables or base dependencies.
`source_references.py`, `knowledge_base.seeded_control_file`/`write_control_file`,
`git_authoring.resolve_repository` and
existing Git plumbing are consumed; don't refactor their settled lifecycle.
If the private-profile factoring cannot preserve its public contract, return the
specific conflict to the owner before widening JP or Ariadne scope.

Validation V5a, `new-test`, at the public setup CLI seam:

- `test_empty_journey_setup_preview_confirm_and_retry`: hand-authored namespace,
  selected worktree/branch and outside private profile; independent before/after
  filesystem and Git index/ref snapshots. Preview writes nothing; confirmation
  creates only previewed setup files, whose manifest parses with the exact selected
  namespace and empty maps; normal KB validation passes, private history remains
  empty, native Git still owns commits. Retry preserves content. Cover headless
  preview/confirm and the same interactive confirmation path without duplicating
  the existing credential/skill tests.
- `test_empty_journey_setup_refuses_without_writes`: a compact family for declined
  confirmation, missing/invalid namespace/profile selection, changed authoring
  identity or newly occupied target, existing unadopted content and invalid private
  containment. Expected results come from §2.2's stated rules and pre-call facts;
  use directory snapshots including absent parent directories. A named write-failure
  seam checks honest incomplete reporting and preservation of pre-existing files.

One focused new module establishes the creation boundary; no manufactured RED is
required for this new feature. Before factoring private-profile validation, pin its
existing schema/namespace/containment behavior with applicable existing checks;
reuse those results until the factoring changes their code, then rerun those
affected cases. Reuse all unrelated J0–J4 evidence. Existing J5 selection/privacy/
confirmation tests run once against the changed setup route, preserving every
assertion. No test is added merely for another layer or a percentage target.
From `products/lumio`, the new focused command is:

```sh
uv run --locked pytest -q packages/lumio-wiki/tests/test_journey_setup_creation.py
```

The parent binds exact affected existing JP/J5 selectors and scoped lint to the
implementation grant after preflight; no broader repeated suites. Review the
changed confirmation/mutation boundary before J6 consumes it, with one authorized
fix pass and one delta recheck. Completion: AC12 demonstrated, existing adoption/
profile contracts preserved, exact committed result reviewed. No publication or
target integration follows. J6 supplies packaged guidance and harness qualification.

## J6 — Package the skill and qualify the full journey

- [ ] Update `data/skill/SKILL.md`, `data/skill/PROTOCOL.md`, `docs/quickstart.md`,
  package `README.md`, and add `docs/howto-source-handoff.md`. Teach the exact
  commands, user review, configured commit/PR action, retry checks and maintainer
  admission. Document private staging, operator-controlled remote residue and
  required conditional-copy capability without exposing private paths in public
  submission results. Link approved Ariadne spec/plan0033 and distinguish its separately
  delivered integrated admission from standalone Lumio; CLI configuration alone
  cannot qualify the Core journey.
- [ ] Teach J5a's preview/confirm empty-create route, native-Git worktree prerequisite,
  explicit namespace and separate nonempty adoption path in those same documents.
  Do not describe a fresh contributor clone as a new empty KB or replace AC11's
  metadata-bootstrap start with an easier empty-KB demonstration.
- [ ] Add `examples/external-agent-journey/README.md` with the deterministic
  synthetic source/expected output and a manual BB + Pi recipe. Keep this as the
  product's reproducible usage example, not another sign-off ledger.
- [ ] Extend `scripts/verify_lumio_wiki_wheel.py` only for new public exports/data.
  Run package/paired checks through existing CI recipes. Modify CI selection only
  if new tests otherwise escape their intended native/S3 jobs.
- [ ] Begin qualification with a nonempty maintainer KB and a fresh contributor
  clone. Transfer/import baseline metadata while keeping all baseline originals
  unavailable to the contributor. The maintainer retains them independently.
- [ ] Run one real attachment → readable review → confirmation → Git PR → private
  exchange → second-environment import → maintainer admission → cited read journey
  through BB + Pi using installed candidate wheels and explicitly approved fixture
  repository/remote/store. Native Git hosting checks use a disposable authorized
  repository, not a customer repository. Keep tests synthetic and owned.

Depends on all previous slices including J5a; covers AC1–12 integration and AC4 PR retries.
Validation V6, `existing-check` plus the required harness journey: tests establish
deterministic contracts; the host run establishes attachment access, actual skill
use, readable display, human confirmations, native GitHub submission and separate
credentials/environments. A scripted CLI run alone is not harness proof. Reuse
J0/J3/J4 failure checks; do not reproduce every fault in chat. Record exact wheel
identity and retained command/chat artifacts in existing run state. Missing a
second suitable environment or human confirmation makes the relevant criterion
unverified; no fabricated confirmations or shared-registry shortcut.

Existing paired regression evidence is selected from
`integration/tests/lumio_metric_mvp.py::test_local_revenue_release_and_later_policy_isolation`,
`::test_composite_consent_binds_scope_build_and_full_previous_release`,
`::test_standalone_never_imports_optional_lumio`, and
`integration/tests/lumio_local_context.py::test_integrated_technical_profiles_preserve_evidence_and_curated_content`.
Required CI already covers them; do not run duplicate local copies if matching
candidate CI evidence is available. These checks protect existing behavior; they
do not certify the separately planned Ariadne managed-source journey.

Completion: candidate wheel carries the current skill, independent environments
complete the approved journey, and existing standalone/integrated contracts still
pass. Final parent disposition is accept/fix/hand back/ask with no integration or
publication implied. Each review permits one authorized fix pass and one delta
recheck; remaining blockers return to the owner.

## Requirement coverage and verification commands

| Spec AC | Tasks |
| --- | --- |
| 1 | JP, J5, J5a, J6 |
| 2 | J1, J6 |
| 3 | J2, J6 |
| 4 | J2, J5, J6 |
| 5 | J3, J4, J6 |
| 6 | J3 |
| 7 | J3, J4 |
| 8 | J3 |
| 9 | J3, J6 and retained exact-revision publication checks |
| 10 | JP, J0–J6 including J5a with native export/reader checks |
| 11 | J0, J1, J4, J5, J6 |
| 12, §2.2 | J5a, J6 guidance/integration |
| §2.1 shared profile | JP, J5, J5a (internal validation reuse only), J6; Ariadne A1/A3 consume and qualify |

Focused commands (after execution approval), from `products/lumio`:

```sh
uv run --locked pytest -q packages/lumio-wiki/tests/test_private_profile.py
uv run --locked pytest -q packages/lumio-wiki/tests/test_source_baseline.py
uv run --locked pytest -q packages/lumio-wiki/tests/test_authoring_journey.py
uv run --locked pytest -q packages/lumio-wiki/tests/test_authoring_review.py
uv run --locked pytest -q packages/lumio-wiki/tests/test_source_handoff.py
uv run --locked pytest -q packages/lumio-wiki/tests/test_source_exchange_s3_compat.py
uv run --locked pytest -q packages/lumio-wiki/tests/test_journey_setup.py
```

V4 must fail/stop if its designated service is unavailable; a skipped test is not
exchange evidence. Run focused nodes during fixes rather than entire files once
their unrelated cases are green. New feature tests need independent expected
results; failing-first is required only for a bug repro or refactor pinning.

Repository CI remains authoritative: `.github/workflows/ci.yml` owns root
coordination, Lumio native lint/suite (`-n 4`), same-commit Core/SDK paired wheels,
Core-only installed walkthrough, S3 integration and standalone SDK/MCP wheels;
the adapter wheel job retains optional adapter isolation. Do not add a second
matrix or waive a gate. Broad local repetition is unnecessary when corresponding
CI evidence applies. Delivery/release execution and public-package pin updates
are outside this plan.

## Review readiness and remaining boundaries

This is plan revision 5 for approved spec0010 revision 5. D0 and the empty-create
versus nonempty-adoption choice are resolved. Prior slices retain their execution
authority and scoped evidence; J5a's new confirmation interface/decomposition is
prepared for review before implementation. No new product code was written during
this reconciliation. JP/J2 public producer interfaces consumed by Ariadne plan0033
stay unchanged; J5a's internal validation reuse does not grant Core project
creation/adoption. Review the concrete J5a plan before dispatch. Integration,
publication and the selected harness's real human confirmations remain separate.

Ariadne plan0033 owns Core Git diagnostics, managed-source admission, composed
review and integrated qualification. It shares producer interfaces/evidence, not
mutable task bodies or an extra source-transfer implementation. No tickets or
external services are created by these plans. Follow orchestrate-implementation
only after separate execution authorization; integration/publication stay separate.
