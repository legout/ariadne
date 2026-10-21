# Git-authoring intake: existing state and private consumer impact

Date: 2026-10-15. Evidence and owner decisions for
[Lumio #1](https://github.com/legout/lumio-wiki/issues/1), not runtime execution,
integration, release, or deployment approval. The owning behavior is
[specification 0008 r1](../specs/2026-10-15-0008-git-native-knowledge-authoring.md).
This project-owned note captures the durable findings; no duplicate global wiki
page or private source content is created.

## Repositories and running work

- Public checkout: `/home/volker/coding/lumio-wiki`, now
  `c3b68db233f8aa98a39380a0099ff2b800a70c55`. Initial HEAD was `93951f8` with
  65 staged path-migration/reference edits owned by another session. That
  session confirmed completion and the owner's separate commit/push; subsequent
  `git status --short --branch` showed clean, in-sync main. This task performed
  neither that commit nor push and did not alter the migration/index.
- Private checkout: `/home/volker/coding/lumio`, clean main at
  `43facf97fc40497688b54546b511c5bd392396a6`.
- Ariadne checkout: `/home/volker/coding/ariadne`, main at
  `21f9b29e7c510130ecfc150c34ccffe3eb6e0fff`; one pre-existing unrelated
  research-note modification was observed and left alone. A live peer owns
  #73 work on an isolated `design/issue73-python314-mcp220-20261015` branch.
  Coordination confirmed no agreed #76 Context Provider/ID/manifest contract;
  neither lane can unilaterally supply its approval.
- Two historical public worktrees still exist at `ef91531` and `1a9d637` under
  the old `/home/volker/coding/worktrees/lumio-wiki/` root; both inspected clean.
  Numerous `/tmp/lumio-*` worktree registrations point at missing locations and
  are marked prunable. None was removed or treated as a new baseline.
- Intercom and Paseo agent metadata were inspected; no new implementer was
  launched. Other projects' running jobs were left untouched.

The design checkout alone is owned by this session:
`/home/volker/.local/state/worktrees/0ast0lnx/lumio-issue1-design-20261015`,
branch `design/issue1-git-authoring-20261015`, Paseo workspace
`wks_fc06d6d961475ba2`, common Git directory
`/home/volker/coding/lumio-wiki/.git`. Its pinned source ref is
`orchestrator/lumio-git-20261015/base/design` at `c3b68db`.
The live daemon's configured worktree root and the returned canonical path were
verified beneath `/home/volker/.local/state/worktrees`; the checkout initially
matched the base/branch and was clean. This is a documentation workspace, not
an implementation run or accepted release candidate.

## Observed consumer boundaries

| Evidence at the inspected revisions | Consequence for #1 |
| --- | --- |
| Private `packages/lumio/src/lumio/app.py:19-57` imports SDK records, `IngestStore`, and `ProposalPipeline`; `:2054-2160` creates/lists/discards/publishes proposals. | Removing proposal classes is an actual app break, not dead-code cleanup. |
| Private `app.py:1904-2040` owns a second candidate/apply/backend-publish/version path. `:2179-2340` includes direct-write publication; `:3145-3221` includes Conversation Source promotion. | Disabling only the visible Workshop button or one publish handler is insufficient. |
| Private `app.py:5391-5770` includes Workshop/control-file writes; `:5829-5990` source lifecycle writes; `:6029-6075` registers API/form routes, imports, moves, rename/remove, and source submission. | The read-only candidate needs a complete server-side KB-write boundary. Temporary conversation attachments/read/chat are a separate contract. |
| Private `packages/lumio/src/lumio/ingest.py:179-192` delegates assembly to `ProposalPipeline`; many later functions return `IngestProposal`. `publish.py:23-32` re-exports low-level SDK apply/validation helpers. | A new engine API cannot simply replace old wheels in the current app. |
| Private root `pyproject.toml:15-16` uses sibling editable sources. `packages/lumio/pyproject.toml:17-18,33` ranges both packages `>=0.1.2,<0.2.0`; `uv.lock` resolves them editable. | Even apparently bounded package ranges do not isolate local development from source/API removal. Exact old wheel resolution must replace editable sources in the isolated read-only candidate. |
| Public `proposal_pipeline.py:1807-2033` coordinates mutable KB pages, proposal state, and registry transition/rollback. `source_registry.py:231-243` stores proposal-keyed pending transitions. | Removing proposal persistence requires replacing source lifecycle authority too, not just renaming CLI commands. |
| Public `artifact_store.py:568-600` captures `source_record.versions[-1]`; historical bindings are stored privately. `cli.py:3014-3128` runs the S3 binding hook before activation. | Reviewed Git source pins must replace latest-version resolution while preserving historical manifests and pre-activation retention checks. |
| Public `location.py:165-170` leaves filesystem `published_version` unset; `s3_publish.py` implements create-only versions and pointer CAS. | Local immutable publication/pointer activation needs an explicit new path; the existing plain filesystem view is not already a persisted admitted version. Preserve plain reads. |

The earlier accepted
[Plan 05 consumer inventory](plan-05-consumer-api-inventory.md) remains useful
history and identifies other supported public seams. This inspection did not
use it as permission to perform its unrelated API contractions or reopen its
implementation plans.

## Existing pending data: bounded local observation

Without printing page bodies, source bytes, IDs, filenames, or private registry
content, a read-only aggregation inspected the known local default stores:

- private app `data/ingest`: zero proposal/raw/source-registry entries;
- shared project's `.wiki/.lumio/ingest/proposals`: 20 JSON records, of which
  11 are `published`, 8 `discarded`, and **1 `staged`**;
- that CLI store's `raw` and `source-registry` directories had zero entries.

This is not an inventory of deployment volumes, S3, environment-overridden
stores, backups, or every existing worktree. It proves that assuming "no pending
proposals" is unsafe, not that the sole observed staged proposal is exportable.
No proposal was published, discarded, edited, migrated, or deleted.

## Owner-confirmed design decisions

The owner selected, then approved the complete in-chat #1 design:

1. Use the newly owner-committed migration baseline, verified as `c3b68db`.
2. Require explicit local authorization of the exact reviewed revision/digests,
   independent of Git commit/validation; no signed-tag requirement.
3. Make the private app temporarily KB-read-only and pin unchanged baseline
   wheels in a separate isolated candidate. After the availability check below,
   the owner approved building these locally from `c3b68db`, privately retaining
   and SHA-256-pinning the actual artifacts during later approved implementation.
   A full Git browser Workshop is excluded.
4. Offer operator-confirmed Git export for unreviewed legacy proposals, without
   approval, publication, private-source leakage, or silent loss.
5. Keep private immutable source history, Git exact references, deterministic
   validation, and complete immutable publication with safe activation.
6. Write ADR/spec/glossary on an isolated design branch, present written r1 for
   review, and plan/execute only through the subsequent required gates.

The scoped ADR amendments must reconcile proposal-first instructions and
registry-latest assumptions; they do not relax Evidence, ontology, privacy,
visibility, or read-only MCP guarantees. Issues #2/#76 still need a jointly
approved behavioral contract. Ariadne's #73 lane is not such approval.

## Baseline wheel availability: confirmed prerequisite change

Read-only HTTPS metadata checks on 2026-10-15 returned HTTP 404 for all four:

- `https://pypi.org/pypi/lumio-wiki/json`
- `https://pypi.org/pypi/lumio-wiki/0.1.2/json`
- `https://pypi.org/pypi/lumio-lancedb/json`
- `https://pypi.org/pypi/lumio-lancedb/0.1.2/json`

`gh release list --repo legout/lumio-wiki --limit 6` returned no entries.
This does not prove that private archives/indexes do not exist, but a plan must
not assume those public wheels are installable. The local editable resolution
explains why the current app checkout can declare unpublished version ranges.
The owner selected private, locally built baseline wheels rather than waiting
for supplied artifacts. Building, dependency availability, installed-wheel
adoption, and resulting hash values remain future execution gates; nothing was
built or released by this investigation.

## #2/#76 reconciliation frontier

Ariadne's accepted `project/adr/0011-context-carrying-answers-and-skill.md` and
`project/specs/2026-10-06-0011-context-trust-signals.md` sections 1/5 and
acceptance example 4 explicitly preserve non-failing missing/unreadable required
metric/Policy context: null/empty context plus `context_unavailable`, with
otherwise valid queries continuing. Those sources were read directly after the
peer flagged the conflict. #76's mandatory Policy-closure/refusal direction is
therefore new behavior, not the baseline. It requires a scoped owner-approved
amendment in Ariadne before dependent #2/#76 implementation. Lumio's source
manifest/admission design does not supply that approval, define join authority,
or make generic OKF exchange a lossless Ariadne application profile.

## Knowledge retrieval and limits

The global vault was queried first via `wiki-query`: graph lookup plus lexical
QMD search. `projects/lumio/lumio-architecture.md` is a draft last updated
2026-07-05 and describes the earlier monolithic/proposal design; it was read as
historical context, not used to override current sources. Eight graph candidates
were seen, one read, seven not used. No semantic indexing or embeddings ran.
The source-of-truth evidence above is current repository code, issue bodies,
command output, and explicit owner choices.

No runtime tests, builds, live S3 operations, installed-wheel adoption checks,
or deployed-app checks were run during this design intake. Package compatibility
and migration safety remain implementation acceptance obligations, not proven
outcomes of this note. Catalog skill provenance is planning-contract v1 with
installed file SHA-256
`5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`;
the precise upstream installed catalog commit is unknown.

## 2026-10-16: public-only execution amendment

The owner explicitly directed: “Wir wollen die lumio App vorerst nicht weiter
berücksichtigen. Fokussiere dich nur auf lumio-Wiki und wenn nötig,
lumio-lancedb”. Specification/plan 0008 r2 and ADR-0029 record this scope change.
Do not continue private migration/tests/CI provisioning. The partial C0 commit
`741546a` and its six post-handoff formatter-only deltas are preserved, not
accepted, integrated, or cleaned. The worker confirmed it holds no writer
ownership. Private compatibility is still known-unresolved; this is not release
or integration authorization.

Earlier public baseline preparation at unchanged `c3b68db` actually ran
`test_managed_ingest.py` and `test_s3_publish.py`: 60 passed. Both baseline
wheels were built into the retained private run artifact directory and their
installed bytes independently verified. The former private-wheel provisioning
decision is no longer an implementation dependency. Current public work starts
at G1; existing public manifest/admission/Source/Evidence semantics are unchanged.
No real shared KB proposal or source data was migrated.

A turn-end formatter wrote six C0 files after its reported clean commit. The
parent preserved the delta and independently compared all six ASTs as equal;
the child confirmed harness automation, not a second implementer. The worktree
is intentionally left dirty and unaccepted, with its original patch retained
in the existing run state. No configuration or harness behavior was changed.
