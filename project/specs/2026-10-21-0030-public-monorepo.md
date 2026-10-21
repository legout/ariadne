# Public Ariadne–Lumio monorepo

Status: **proposed, revision 1** (2026-10-21).

The owner selected the existing `legout/ariadne` repository as the target:
“Welches Zielrepo sollen wir verwenden? Bestehendes ariadne-Repo (empfohlen)”.
This approves the target choice only. The complete architecture below awaits
approval; no package migration, integration, push, release, repository archival,
issue transfer or credential/environment change is authorized by this document.
Rationale: [proposed ADR-0027](../adr/0027-public-monorepo.md).

## 1. Purpose and baseline

Make public Ariadne/Lumio development, documentation and changes to their shared
contract possible in one checkout and one reviewed commit. Preserve separately
installable products and their existing runtime boundaries.

Inspected source baselines:

- Ariadne: `f6ede240056c35f916e295a03520170b7a0d38eb`, Core 0.6.0.
- Lumio foundation: `271abfa529f7398c6630f5593efc3bc4be6d26ab`, wiki/adapter 0.4.0.

The published versions remain unchanged during migration. These are software
source refs, not user Content Commits or admission authority. Before execution,
the plan must reconcile any newer accepted source changes rather than silently
migrating a stale snapshot.

## 2. Repository and package layout

The repository root becomes a non-distributable uv workspace with one development
lockfile for these three members:

```text
packages/
  ariadne-data/             # existing Core src/, tests/, pyproject and package README
  lumio-wiki/               # existing public SDK member, including its package tests
  lumio-lancedb/            # existing optional adapter member and package tests
ariadne-agent/             # retained separate project/environment; not a workspace member
project/                   # existing Ariadne decisions/specifications and workflow map
  lumio/                   # imported Lumio project records, with original IDs
    CONTEXT.md             # original Lumio vocabulary, preserved
    adr/ specs/ plans/ ...
CONTEXT.md                 # existing Ariadne glossary, preserved
CONTEXT-MAP.md             # points to both existing vocabularies and ownership
CONTRIBUTING.md            # one developer entry point and component commands
README.md                  # common entry, links to each product and joint tutorial
pyproject.toml             # coordination/dev tooling; package = false
uv.lock
```

Existing Core document and example URLs remain at their present paths, including
`docs/tutorials/lumio-ariadne-local.md`. Lumio's repository-level user docs and
examples move under `docs/lumio/` and `examples/lumio/`. Its root README becomes
the SDK package README, revised only for accurate monorepo links/paths. Existing
package-local resources retain their installed paths.

Lumio's repository-level tests, eval assets and verification scripts are retained
under `tests/lumio/`, `eval/lumio/` and `scripts/lumio/`. Package-local tests remain
with their packages. Core tests move with Core. Path discovery and test fixtures
must be updated deliberately: importing a different component's `tests` package
is a failure, not a reason to remove tests or weaken assertions. Existing native
package test configurations stay scoped; differing Ruff rules are not replaced
by a blanket new style policy.

Root instructions and `project/agents/domain.md` must map the two contexts and
scoped package instructions. Import Lumio's accepted records with original names
and numbering under its namespace; do not merge glossaries, renumber decisions,
or apply machine-specific Lumio KB configuration globally. Historical records
retain their meaning and source provenance; only relocation links are repaired.
A root migration reference maps old repository paths to their new canonical paths.

## 3. Preserved contracts and dependency direction

Distribution names, import namespaces, CLI names, base dependencies, optional
extras and supported Python versions remain as published. In particular:

- `lumio-wiki` remains independently usable without Ariadne, DuckDB, LanceDB,
  transport SDKs, models or services unless the selected extra requires them.
- `lumio-lancedb` depends on the SDK with its bounded published range.
- `ariadne-data` remains independently usable without the optional Lumio SDK;
  integrated use still requires an installed compatible SDK and exact identity.
- Workspace sources select local members for joint development only. They do
  not replace or erase published dependency metadata.
- `ariadne-agent` keeps its independent environment, existing Core dependency
  and external Tau boundary. Relocation of Core requires correcting its relative
  development source path. No Agent qualification, new Tau installation, Tau
  import or machine-specific path cleanup is included.
- The private Lumio application, Tau repositories, credentials, local admissions
  and real data projects are not imported.

The existing build backends may differ; migration does not standardize them.
Developer instructions provide a Core/SDK path without requiring the optional
LanceDB adapter. Adapter/extra test environments are selected explicitly.

One shared checkout does not change the admitted Content Commit, Policy Closure,
Visibility Scope, source approval, receipt freshness, mapping confirmation,
response budgets or overall admission. Git sync remains separate from activation.
No service, S3-first flow or new umbrella runtime package is introduced.

## 4. Git history, old repository and licensing

Import the complete public Lumio commit history without rewriting existing Core
or Lumio commit IDs or force-updating either published repository. Original
source refs must remain reachable from the migration result, and retained files
must be traceable to the source commit. Existing Core release tags are unchanged.
Historical Lumio refs use an explicit non-release namespace such as
`lumio-history/v0.4.0`; importing them must not trigger publishing workflows.
No historical releases are recreated or retagged.

The old Lumio repository and its existing releases/issues remain available.
After the new source location is verified, a separately authorized cutover can
add a README notice and stop duplicate development/release workflows. Archiving
or deleting the repository, transferring issues and closing tickets are separate
actions, not migration side effects. Links to historical records keep explicit
repository-qualified identifiers.

Preserve Lumio's Apache-2.0 license and notices with the imported code and built
wheels. Core currently declares no project license; this migration grants no
new Core license and introduces no repository-wide Apache claim. Root guidance
must state that licensing is component-specific. Existing vendored notices,
including ODCS, remain attached to their artifacts.

## 5. CI, artifacts and releases

### Development and qualification

Joint source tests consume Core and SDK from the same checked-out commit; the
integration workflow no longer checks out floating or separately pinned Lumio
source from a second repository. Qualification records still identify actual
source/builds and tested artifacts.

Keep separate native Core, SDK and adapter jobs and the combined local journey.
Do not concatenate both repositories' `tests` trees into one default import
namespace. Existing default and explicitly named SDK-paired Core modules remain
covered, including `lumio_metric_mvp.py` and `lumio_local_context.py`.

Retain meaningful existing gates: native validation, SDK eval/retrieval, packaged
skills, no-SDK standalone behavior, no-source-read and role guards, isolated
wheel verification and actual installed Core/SDK pairing. Wheel environments
are outside the checkout, without editable installs or PYTHONPATH overrides;
workspace imports are not evidence of standalone wheel correctness.

S3 remains optional for onboarding but its existing CI qualification is not
removed. Preserve the isolated pinned SeaweedFS CI selection, synthetic
credentials and fixed `-n 4` SDK full-suite setting (never `-n auto`). Running
or provisioning such services locally requires its own explicit execution scope.

### Independent release channels

- Future `core-vX.Y.Z` tags release only `ariadne-data`.
- Future `lumio-vX.Y.Z` tags release the existing lockstep `lumio-wiki` and
  `lumio-lancedb` family.
- Ordinary pushes and migration/import/history tags publish nothing.
- Existing public package names and versions are not bumped by the migration.
- Core and Lumio can still change atomically in one commit without requiring
  every package to release. No all-package lockstep policy is introduced.

Each release builds and verifies only its assigned artifacts, checks the tag
against the relevant member versions, and publishes exactly those tested files.
Core release qualification must consume the exact selected public/producer
Lumio wheel with recorded identity, not an unreleased SDK substituted silently
by the workspace. When a change needs a new SDK, qualify and publish the producer
first, then qualify/release Core against those exact artifacts. Unchanged SDK
releases can be reused. Joint source tests alone do not certify a public pair.

The existing token/environment permission boundaries remain. The implementation
plan must name required GitHub environment/secret availability in the target
repo before release cutover; no credentials are read, copied or invented by
migration. A publishing configuration test builds/validates without uploading,
creating tags or dispatching a real release.

## 6. Migration and failure behavior

Prepare an isolated registered candidate from frozen accepted refs. Import
history, relocate packages and repair paths before changing target branches.
The implementation plan owns exact operations and bounded validation invocations.

Missing source refs, conflicting authoritative records, dependency resolution
failure, missing package resources, unexpected test collection, artifact identity
mismatch or failed required gates stops the affected lane. No force push,
new skip/xfail, dependency refresh or narrowed assertion is an implicit repair.

Keep current target refs and the old Lumio repository intact until the candidate
is qualified and independently reviewed. Integration, push and old-repo cutover
need explicit authority. Before cutover, abandoning the candidate leaves current
users unaffected. After integration, corrective ordinary commits are preferred
to rewriting public history. No data/admission migration is performed.

## 7. Observable acceptance

1. A fresh clone of `legout/ariadne` contains the three package members and can
   resolve the approved workspace with the committed lock. Core/SDK development
   is documented without a machine-specific external checkout or LanceDB need.
2. Built distributions retain their public names, versions, console scripts,
   import roots, extras, licenses and co-packaged resources. Base SDK and
   standalone Core work in isolated environments without sibling packages.
3. Native component tests/eval and installed-wheel gates remain assigned and
   runnable with no accidental cross-import of test packages. Newly discovered
   behavior changes return for disposition; they are not hidden by packaging.
4. The joint installed-pair example still produces revenue 150 EUR and count 2
   for authored 100/50 completed and 25 cancelled rows, full Policies/citations,
   and explicit human source/overall admission. Git movement alone does not
   activate the amended Policy. Reuse source numerical evidence where matching;
   do not duplicate that journey merely to relabel it as installed proof.
5. Both source histories are reachable; old Core tags/releases are unaffected,
   and imported historical Lumio refs cannot initiate a release.
6. All current entry points and example/resource paths resolve in the assembled
   tree. Contexts remain separately owned; scoped historical record IDs and
   license ownership remain unambiguous.
7. A Core-only release dry run selects only its Core artifacts and exact paired
   SDK; a Lumio-family dry run selects exactly its two artifacts. A normal push
   and history tag select no publish job. No real publication is performed.

## 8. Capture and approval boundary

Planning Contract version 1; installed exact catalog provenance: unknown.
No new domain term is introduced. The two existing vocabularies keep their
owners; the proposed context map changes navigation, not definitions. Repository
consolidation warrants ADR-0027 because history, contributor workflow and release
ownership are costly to reverse and there are real separate/new/existing-repo
alternatives. Lumio ADR-0025's private-application exclusion remains intact;
its named public repository location needs an explicit scoped amendment during
migration, not historical replacement.

Only the target repository choice is approved. Revision 1's complete scope,
layout and release policy await owner review. After that approval, write the
linked implementation plan using the same 0030 prefix and reconcile any affected
architectural records before implementation. Execution and integration/release
authority must be explicit; this draft supplies none.
