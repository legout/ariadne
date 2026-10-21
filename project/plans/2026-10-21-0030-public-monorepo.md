# Public Ariadne–Lumio monorepo: execution plan

Status: **proposed, revision 1** (2026-10-21). Not execution authority.

Goal: prepare one reviewable monorepo candidate and a reversible external cutover
for the existing repository's approved `ariadne-lumio` name.

Behavior: [specification 0030, approved revision 2](../specs/2026-10-21-0030-public-monorepo.md).
Rationale: [accepted ADR-0027](../adr/0027-public-monorepo.md).
Owner design approval: “ok. passt”, following the revision-2 documents and the
recommendation to rename the existing repository, preserve public package names,
and support Lumio alone, Ariadne alone and explicit integrated use.

Planning Contract version 1; exact installed catalog provenance: unknown.
Capture: no new domain terminology; preserve the two existing glossaries and
map their ownership. ADR-0027 captures the costly repository/release decision.
The architecture and naming choice are settled; service availability, dependency
resolution and repository permissions are prerequisites to verify, not assumed
successes. This plan adds no runtime feature or package-name migration.

## Sources, placement and ownership

Frozen product refs:

- Core: `f6ede240056c35f916e295a03520170b7a0d38eb` in `legout/ariadne`.
- SDK/adapter: `271abfa529f7398c6630f5593efc3bc4be6d26ab` in `legout/lumio-wiki`.

The execution base includes the committed specification/ADR/plan result; the
parent records its actual full SHA in existing run state before dispatch. Recheck
both canonical mains and reconcile newer accepted changes before writer creation.
Never use a floating main as the import pin or publish a fabricated self-SHA.

One serial Pi writer owns the isolated migration branch/worktree. Use the
verified current BB host and shared root `/home/volker/.local/state/worktrees/`;
worker `zai/glm-5.3/high`, reviewer `openai-codex/gpt-6.1-sol/high`. Runtime,
registered cwd, branch, common Git directory and clean pinned HEAD preflight
are mandatory. Children run no memo/shared memory or further delegation.
The parent owns disposition, final qualification and integration decisions.

This is a coupled path/workspace migration. M1–M3 stay on the same isolated
branch, with intermediate commits preserved; only M4 promises the fully green
assembled candidate. No intermediate state is integrated into main. This avoids
temporary runtime compatibility layers added merely to make file moves landable.

Only migration-needed metadata/lock/path changes are allowed. Preserve package
code, formulas, admission semantics, supported extras and versions. Reconcile
existing resolved versions into the shared lock; do not run an upgrade campaign.
A material dependency incompatibility, required runtime change or conflicting
architectural source returns to the parent before dependent edits proceed.

## M0 — Freeze and baseline (parent, read-only)

Prerequisites: plan approval and an explicit isolated-execution grant.

- [ ] Record accepted source refs, canonical paths, approval commit and owned
  resources in the existing run manifest. Check source/main cleanliness and
  source object availability before creating the registered writer worktree.
- [ ] Read both AGENTS files and relevant package/CI configurations. Inventory
  retained paths, installed resources, license files, test namespaces and native
  commands from the frozen sources. This is relocation input, not a new ledger.
- [ ] Reuse actual green native CI/release and onboarding evidence for these
  source refs where applicable; inspect logs rather than assuming success from
  a worker summary. Missing baseline proof is resolved before mutation.
- [ ] Read-only check the proposed repository name and caller permissions;
  inventory repository-bound workflow/environment names without secret values.
  An unavailable name or missing permission blocks external cutover, never
  authorizes a different name or credential-model change.

Validation: low risk, `no-new-test`; Git identity, actual baseline evidence and
source inspection. Completion: parent grants a single writer the pinned import
and owned scope. No tests, installs or services are implied by this preflight.

## M1 — Assemble preserved histories and relocatable workspace

Owns: Git candidate history; root `pyproject.toml`/`uv.lock`; all three package
manifests; Core `src/` and `tests/` moves; imported package trees; Lumio root
`tests`, `eval`, scripts, examples and their actual callers; scoped lint/test
configuration; Agent's relative Core development source path only.

Consumes M0 refs. Produces one shared tree with the original public contracts.

- [ ] Import full public SDK history without rewriting either existing history.
  Preserve retained source files and license/notices and prove both frozen
  source refs are ancestors of the candidate. Do not push imported historical
  tags. Store source tags only under the specification's non-release namespace.
- [ ] Move Core to `packages/ariadne-data`; retain imported SDK/adapter member
  paths. Relocate Lumio repository assets to the specification's namespaces.
  Keep the original runtime modules and packaged-resource destinations intact.
- [ ] Add the non-package uv root and local workspace sources. Keep published
  dependency metadata and optional Core→SDK behavior unchanged. Exclude Agent
  from the workspace; update only its relative Core source location.
- [ ] Adapt actual root discovery, fixture locations, script/README paths and
  component test imports. Preserve independently derived test expectations.
  Do not merge both components' `tests` packages into a shared accidental import.
- [ ] Preserve component-specific lint rules and configure reproducible isolated
  component commands. Inventory lock changes against the two native locks;
  justify resolution-only changes, stopping for material dependency changes.
- [ ] Move existing non-publishing CI callers with the code so their commands
  reference the new paths; M3 handles the release-channel changes.

Validation: public-contract migration, `existing-check` plus `no-new-test`
relocation inspection; M4 supplies native suites and isolated wheel proof once
on the final tree. Before M2, parent inspects ancestry, moves, manifests and lock
changes; source/package/interface conflicts stop dependent work. No broad test
invocation is assigned to an intermediate path layout.

Completion: clean committed intermediate candidate, source refs reachable,
minimum no-adapter Core/SDK developer commands defined, no unpublished runtime
behavior change hidden in the move.

## M2 — Three user entries and scoped architectural records

Owns: root/product READMEs, `CONTRIBUTING.md`, `docs/`, examples, scoped AGENTS,
`CONTEXT-MAP.md`, `project/agents/domain.md`, imported `project/lumio/` records,
license-location guidance and canonical repository URLs in owned metadata.

- [ ] Present three complete entry paths: Lumio standalone, Ariadne standalone,
  both explicitly integrated. Distinguish end-user installation from workspace
  development. Keep the canonical joint tutorial at its current relative path.
- [ ] Preserve existing runnable local examples and the optional S3 guide;
  update real relative paths and installation references without rewriting
  historical release facts or creating new runtime commands.
- [ ] Scope the two existing vocabularies/agent instructions; preserve record
  IDs and apply the explicit public-repository-location amendment to Lumio
  ADR-0025. Its private-application exclusion remains binding.
- [ ] Retain Apache-2.0 with Lumio, existing vendored notices with their assets,
  and Core's current license status. No repository-wide license is inferred.
- [ ] Prepare canonical `ariadne-lumio` URLs, a migration-path reference and old
  Lumio cutover text. Mark external rename/old-repo changes as pending until M5;
  do not announce a currently nonexistent public destination as already live.

Validation: low risk, `existing-check` for affected current doc/skill contracts
in M4; `no-new-test` link/anchor/diff checks. Existing numerical/input evidence
is not invalidated by wording-only changes. Completion: committed usable entry
points, honest staged-URL status and no broken assembled local links.

## M3 — Separate release channels, without publication

Owns: `.github/workflows/` migration of native CI, SDK/adapter wheel verifier
callers, root/component build commands and release documentation. No secrets,
repository settings, tags or upload APIs are mutated.

- [ ] Configure `core-vX.Y.Z` and `lumio-vX.Y.Z` channels per specification §5.
  Normal pushes and `lumio-history/*` refs cannot select publish jobs. Preserve
  existing Core tags/releases and all package versions.
- [ ] Preserve tag/version checks, exact wheel selection and producer-first
  public pairing. Core publishing cannot accidentally select the SDK/adapter
  wheels from a common output directory or test against an unreleased substitute.
- [ ] Retain separate native jobs, installed-wheel isolation, eval/MCP/adapter
  gates, original S3 compatibility job, optional-import checks and explicit
  paired Core modules. No test is removed because relocation makes it fail.
- [ ] Document repository-bound configuration prerequisites. Verify workflow
  references and known action/reusable-workflow callers for the new repo name.
  Missing configuration blocks M5; no token values are read or copied.

Validation: high consequence, `no-new-test` configuration/build inspection plus
existing packaging checks in M4. Independently compare event/tag→channel→artifact
selection against specification §5, inspect the real build outputs/version
metadata and confirm no upload in local dry runs. Do not introduce a runtime
release router or duplicate test framework merely to test YAML literals.
Completion: committed release configurations ready for the one candidate review,
with all external prerequisites disclosed and no release actually triggered.

## M4 — Final qualification and independent candidate review

Consumes the final committed M1–M3 tree. Parent freezes it before tests and
builds; record exact commands and environments in existing run state. Build each
member wheel once and retain those wheels for all installed checks. Tests may
perform their documented subprocess builds; disclose those rather than claiming
three builds is a hidden total. One normal execution of each assigned native
job, no repeat-green parent run or automatic retry.

- [ ] `uv lock --check`; resolve/sync the approved locked environments. Run native
  Ruff with preserved component configuration and diff checks on touched files.
- [ ] Core native release-suite invocation once from its relocated project,
  including both explicitly named paired modules and its default `tests` tree;
  preserve the existing three prepared-S3 module exclusions in native release CI.
  No Agent/Tau suite or live-model campaign is assigned.
- [ ] SDK native full-suite selection once: `pytest -q -n 4` over relocated
  repository tests, both package test trees and eval. Preserve native required
  dependencies. Never use `-n auto` or silently shrink the selected tests.
- [ ] Native SDK onboarding/S3-compatible selection once with its existing
  separately disposable pinned SeaweedFS 4.45 CI configuration and labeled
  synthetic credentials. Plan approval alone does not authorize provisioning:
  require explicit environment/service authority or use actual approved CI.
  Missing required execution tooling blocks this gate; a skipped/empty run is
  not passing proof. Do not reuse unrelated retained services.
- [ ] Reuse the native SDK/adapter isolated-wheel verifiers and MCP smoke with
  relocated fixtures/scripts. Check installed origins/resources and dependency
  metadata outside all checkouts, without PYTHONPATH/editables. Base SDK must
  work with Core absent; standalone Core must work with SDK absent.
- [ ] Use the actual native paired journey as the single assigned numerical
  oracle for 150/2, full Policy/citations, exact human approval and unchanged
  activation semantics. Match source/archive/installed code and fixture bytes
  before reusing it for the wheel pair; installation alone is no new SQL replay.
  Smoke the relocated self-contained example's create/propose/review and local
  Git/update entry points only where path changes invalidate prior example
  proof; reuse unchanged calculation-helper proof from onboarding-20261021.
  A newly discovered behavioral delta needs parent disposition and a named
  focused scenario rather than silently replaying the entire numerical journey.
- [ ] Inspect tag/channel/artifact selection from actual workflow configuration
  and dry-run build outputs; exercise no upload or real tag trigger. Check local
  documentation links/anchors and stale active-path references; historical
  citations are not stale callers to rewrite automatically.
- [ ] One fresh independent Pi candidate review covers previously unreviewed
  migration/package/release effects and criterion correspondence. Give exact
  refs, evidence, real callers and the full reviewer contract inline.

Primary pytest budget: one Core native suite, one SDK native suite and one SDK
S3-compatible selection; existing native verifier/subprocess checks remain part
of their own assigned jobs. No extra collection or exploratory wider suite.
The parent dispositions a failed gate before any repair. At most one bounded
fix pass and one affected delta recheck; the actual recheck nodes follow the
named failure, not an automatic full-suite repeat. Unresolved findings or a
materially changed source contract return to the owner.

Completion: clean frozen committed candidate, retained exact wheels and source
ancestry, actual gate outcomes, independent pass, limitations and external
cutover prerequisites. Stop before M5 pending explicit authority.

## M5 — External cutover (not authorized by this plan)

- [ ] With separate integration/push/rename authority, use `merge-worktree` for
  the accepted candidate, verify exact remote tree, then rename the same GitHub
  repository and update the owned canonical remotes/callers deliberately.
- [ ] Verify new and old supported URL behavior, action/workflow references,
  existing release refs and non-publishing CI on the resulting remote commit.
- [ ] Only if separately authorized, add the old Lumio README notice and disable
  duplicate future development/release paths; preserve old releases/issues.
- [ ] No real package publication, issue transfer, archive/delete, force push or
  unrelated worktree cleanup. Remove only owned disposable resources once their
  consumers finish and cleanup is authorized.

Residual risks: unexpected path assumptions, one-lock dependency conflicts,
repository-bound release settings and externally maintained callers. These are
handled by M0/M1 inspection, M4 native/installed evidence and M5 live read-back;
none authorizes silent product changes or weakened qualification.

## Requirement coverage and approval

Spec acceptance 1–3 → M1 + M4; 4 → M2 + M4; 5 → M1 + M5;
6 → M2 + M4; 7 → M2 + M4; 8 → M2 + M3 + M5; 9 → M3 + M4.

Requested next authority: approve this plan and isolated execution of M0–M4.
Any disposable-service provisioning must be named explicitly. M5, publication
and destructive cleanup remain separate. After approval, use
`orchestrate-implementation`; do not invent another execution procedure.
