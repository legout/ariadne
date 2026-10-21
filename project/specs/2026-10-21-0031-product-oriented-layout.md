# Product-oriented Ariadne–Lumio repository layout

Status: **detailed design draft, revision 1** (2026-10-21).

The owner selected product areas after reviewing the alternative of symmetric
directories grouped by file type: “Ja, arbeite die Produktbereiche als
Zieldesign aus und halte sie in Spec und ADR fest. Zunächst keine Migration.”
That approves the direction and this documentation task. The detailed rules
below are submitted for review; no implementation plan, filesystem migration,
target integration, push, release or repository rename is authorized here.

Rationale: [ADR-0027, product-area amendment](../adr/0027-public-monorepo.md#product-area-amendment--2026-10-21).
Prior migration: [specification 0030 revision 2](2026-10-21-0030-public-monorepo.md).

## 1. Purpose and relationship to the completed migration

Give Ariadne and Lumio equal, explicit ownership in the source tree. Someone
opening either product area can find its packages, documentation, project
records and development assets without knowing which repository existed first.
Keep the common local user journey easy to find in its own integration area.

The inspected baseline is public `legout/ariadne` at
`bb11ee81ba7d6f478f13e4ec275dc3d9494ac09d`: Core 0.6.1, Lumio SDK/adapter
0.4.1. These are software identities, not a user's Content Commit or admission.
An implementation plan must freeze the then-current accepted base rather than
silently execute against a stale snapshot.

Spec 0030 describes the completed first consolidation and remains its historical
contract. Its section 2 intentionally kept Ariadne's root paths and placed Lumio
under additional namespaces. This follow-up proposes replacing that **future
layout and source-path policy**, including the promise to keep old Ariadne
documentation paths on `main`. It does not rewrite the prior approval, migration
record, published commits or release tags. Until a separately approved migration
lands, current paths and the active artifact/domain maps remain authoritative.

The existing independent-product, explicit-integration, licensing, history and
producer-first release requirements of spec 0030 remain binding.

## 2. Ownership and target tree

An area is a repository location, not a new runtime package or business-domain
term. Product code and product-only assets belong to that product; joint user
flows belong to `integration/`; repository coordination belongs to shared roots.
Folders are created only for real content, not to manufacture matching empty
trees.

```text
products/
  ariadne/
    CONTEXT.md
    CHANGELOG.md
    packages/
      ariadne-data/          # package README, manifest, src/, native unit tests
      ariadne-agent/         # separate environment; NOT a workspace member
    docs/
    project/                # Ariadne-owned ADRs, specs, plans and research
    examples/
    deploy/                 # Core Docker/Compose files and env example
  lumio/
    CONTEXT.md
    CHANGELOG.md
    packages/
      lumio-wiki/            # package README, manifest, src/, package tests
      lumio-lancedb/         # optional adapter, unchanged package identity
    docs/
    project/                # Lumio-owned records, original IDs retained
    tests/                  # product-wide SDK/adapter tests and fixtures
    eval/
    scripts/
    experiments/
    examples/
integration/
  docs/                     # using Ariadne and Lumio together
  examples/                 # joint local example and its complete data project
  tests/                    # existing paired Core/SDK scenarios
docs/                       # shared repository/contributor references only
project/                    # shared architecture, planning and agent configuration
tests/                      # shared workspace/packaging coordination checks only
.github/
README.md
CONTRIBUTING.md
AGENTS.md
CONTEXT-MAP.md
pyproject.toml
uv.lock
```

Package-local tests stay with their packages unless an existing scenario has
explicit cross-product ownership in the mapping below. `integration/` contains
no umbrella distribution, alternative SDK, copied runtime or separate workspace.

The root README keeps three clear choices: Lumio alone, Ariadne alone, and both
together. It links directly to their canonical package/documentation entry
points. Product documentation describes independent usage first and links to
the joint guide where appropriate; the joint recipe has one maintained copy.

## 3. Canonical source-path mapping

These are **future destinations**, not links to directories that already exist.
The mapping covers tracked content; ignored local outputs are not product source.

| Current source | Target owner/path |
| --- | --- |
| `packages/ariadne-data/` | `products/ariadne/packages/ariadne-data/` |
| `ariadne-agent/` | `products/ariadne/packages/ariadne-agent/` |
| `packages/lumio-wiki/` | `products/lumio/packages/lumio-wiki/` |
| `packages/lumio-lancedb/` | `products/lumio/packages/lumio-lancedb/` |
| `CONTEXT.md` | `products/ariadne/CONTEXT.md` |
| `project/lumio/CONTEXT.md` | `products/lumio/CONTEXT.md` |
| Root `CHANGELOG.md` | `products/ariadne/CHANGELOG.md` |
| `docs/lumio/CHANGELOG.md` | `products/lumio/CHANGELOG.md` |
| Ariadne-only `docs/tutorials/`, `docs/how-to/`, `docs/reference/`, `docs/explanations/` entries | Same relative categories under `products/ariadne/docs/`, subject to the joint-guide exceptions below |
| Current Ariadne `docs/README.md` | `products/ariadne/docs/README.md`; any root documentation index becomes product-neutral navigation |
| Remaining `docs/lumio/` | `products/lumio/docs/`, including historical release notes |
| `docs/tutorials/lumio-ariadne-local.md` | `integration/docs/tutorials/lumio-ariadne-local.md` |
| `docs/how-to/lumio-git-local.md` | `integration/docs/how-to/lumio-git-local.md` |
| `docs/reference/lumio-bound-releases.md` | `integration/docs/reference/lumio-bound-releases.md` |
| `docs/lumio/ariadne-context.md` | `products/lumio/docs/ariadne-context.md`: producer SDK reference, linked from the joint guide |
| `docs/migration-reference.md` | Remains shared `docs/migration-reference.md`, extended with this second layout transition |
| `examples/retail-demo/` and tracked `examples/trace-data/` content | `products/ariadne/examples/`, preserving supported/retired status and original example names |
| `examples/lumio/` | `products/lumio/examples/` |
| `examples/local-lumio-ariadne/` | `integration/examples/local-lumio-ariadne/`, including its complete synthetic project tree |
| `examples/README.md` | Its three-way navigation is folded into shared entry documentation; it does not remain an Ariadne-default root index |
| `tests/lumio/test_workspace_layout.py` and `test_workspace_certification.py` | Shared `tests/`: they inspect/build the workspace members and packaging boundaries |
| Remaining `tests/lumio/`, including Lumio family release-policy tests | `products/lumio/tests/`, with its fixtures/helpers and native ownership preserved |
| `packages/ariadne-data/tests/lumio_metric_mvp.py` and `lumio_local_context.py` | `integration/tests/`, retaining their filenames, scenarios and release-gate coverage |
| `eval/lumio/` | `products/lumio/eval/` |
| `scripts/lumio/` | `products/lumio/scripts/` |
| `experiments/lumio/` | `products/lumio/experiments/` |
| Root `Dockerfile`, `compose.yaml`, `compose.loopback.yaml`, `.env.example` | `products/ariadne/deploy/`, preserving filenames and deployment behavior |
| `.pi-lens-probe-home/` tracked diagnostic captures | `project/research/pi-lens-probe/`, preserving captured bytes and filenames as tooling evidence |

Example-specific lint configurations follow their examples. Shared helper code
or fixture files needed by relocated tests have one canonical owner; imports and
path lookup are repaired rather than maintaining duplicate fixture trees.

### Project records and vocabulary

- Ariadne-owned `project/adr/`, `specs/`, `plans/` and `research/` entries move
  under `products/ariadne/project/`. They retain their original filenames, IDs,
  approval history and meaning.
- The shared monorepo ADR-0027, spec 0030/plan 0030 and this spec 0031 remain
  in root `project/`. They govern the repository rather than either product.
  Other genuinely shared tooling records are classified by their subject; a
  record mentioning Lumio does not automatically cease to be Ariadne-owned.
- Remaining imported `project/lumio/` records move to
  `products/lumio/project/`, except the glossary destination above. Their original
  numbering/provenance remains separate; no ID renumbering or glossary merger.
- Root `project/agents/` stays the shared workflow/artifact/domain configuration.
  Its mappings, root `AGENTS.md` and `CONTEXT-MAP.md` are updated **when migration
  lands**, pointing to actual product glossaries and record paths.
- The Ariadne glossary's old whole-repository scope sentence is corrected to
  Ariadne ownership during relocation; its business definitions do not change.
  No new root domain glossary is manufactured. The root map remains navigation.
- `AGENTS.imported.md` remains a historical, non-active file. Moving it must not
  activate its machine-specific KB settings. Scoped instructions follow their
  owners and retain existing safety/native-check obligations without duplicating
  the root orchestration procedure.

Future numbered specs/plans continue the existing shared repository sequence;
scan all three owning namespaces before allocation. The same feature's spec and
plan share one date/number/slug. Preserved pre-existing Lumio numbers are historical
namespace-qualified identities, not numbers to rewrite or reuse as global aliases.

## 4. Root responsibilities and configuration

The root is a coordination surface. It may contain common contributor/navigation
documents, shared repository references, shared project records and workspace
contract tests, plus tool-required configuration such as `.github/`, `.gitignore`,
`.dockerignore`, `skills-lock.json` and `.mcp.json`. It contains no default
Ariadne changelog, product glossary, product deployment file, product experiment
tree or directly installable product package.

Root `.mcp.json` remains optional repository client wiring at its discovery
location; references affected by relocation are repaired deliberately. It does
not activate a product integration or grant data access. Do not rewrite personal
client settings, credentials or external environment paths as a side effect.

The root `.dockerignore` is the shared repository build-context configuration.
Its scoped payload paths must follow the relocated Core image. The product-owned
Dockerfile/Compose invocation must explicitly retain the intended build context,
environment-file resolution and relative bind-mount meaning after relocation.
No changed ports, exposure, credentials, source access or service topology.

### Development and test configuration

Keep a non-distributable root uv workspace and its one shared development lock
for the **same three** supported members, now at their product paths. Preserve
every third-party resolution and published requirement, including Core's
`duckdb>=1.0,<2`. Local editable source paths change; package identities do not.

The Agent stays outside that workspace with its separate environment/resolution.
Its repository-relative Core/typing references must resolve the new sibling
location. Moving the directory does not install or qualify Tau, remove its
external dependency, add an Agent release gate or authorize private-path cleanup.

Native Core test/lint settings remain with Core. Lumio's product-wide test/lint
selection is scoped to `products/lumio/` using appropriate configuration files;
this does not create a nested uv workspace or change lint rules. Root defaults
must no longer silently mean “Lumio's suite/style”. If a root pytest default is
provided, it explicitly selects shared coordination tests and the existing joint
scenarios, including the two non-default filenames above. It is documented as
shared coverage, not as the complete native suites of both products.

Document three explicit verification profiles: Ariadne, Lumio, and shared/joint.
Keep their test import namespaces distinct, with intentional helper imports and
no accidental private `lumio` application namespace. Preserve native checks in
CI and retain the existing joint modules in Core release qualification. Root
coordination tests do not become SDK runtime dependencies or a substitute for
standalone wheel evidence. No replacement build system or umbrella test runner
is required just to dispatch the existing commands.

## 5. Preserved public and operational contracts

- Preserve distribution/import/CLI names, Python >=3.14, current versions,
  dependency directions, optional extras, component licenses and installed
  resource locations. Lumio still works without Ariadne, standalone Core still
  works without Lumio, and the adapter remains optional.
- Installation or repository colocation never activates the integrated mode.
  Content Commits, source approval, immutable publication, scope, Policy Closure,
  evidence freshness, response bounds and overall admission remain unchanged.
  A changed installed build still requires genuine matching validation/admission.
- The current public repository name and the already published releases/tags
  remain untouched. Repository renaming is a separate cutover, not part of this
  layout change. No package version bump or publication is implied.
- `.github/workflows/` stays at the GitHub-required root. Preserve ordinary
  non-publishing CI, independent `core-v*` and `lumio-v*` release channels,
  producer-first public SDK URL/hash pinning, artifact-directory isolation,
  action pins, environment/token boundaries and native test exclusions.
- Shared development still uses same-commit Core/SDK wheels. Preserve isolated
  base installs and actual installed origins/resources outside both source trees
  without editable installs or PYTHONPATH overrides. Moving files is not proof
  of installed artifact correctness.
- Existing SDK full-suite parallelism remains `-n 4`, never `-n auto`. Existing
  optional S3 CI gates are retained; this design neither runs nor provisions a
  service. The later plan must assign any affected service gate explicitly.

## 6. Documentation, history and local-file transition

The migration reference records old-to-new canonical paths, including the joint
guide and project records. Root and product entry links, relative links, owned
floating-main source links, workflow callers, build contexts, fixture discovery,
eval data paths and test helpers are repaired against this map. Current source
examples must resolve from their documented working directory in a fresh clone.

Do not keep duplicate product trees, code shims or a forest of old-path stub
documents solely to make the new layout look migrated. GitHub file moves are not
promised HTTP redirects. Repair known repository-owned links and explain changed
source URLs in the migration reference; external tracker/configuration edits need
their separately assigned authority. Historical URLs qualified by immutable
source commits/tags remain historical citations, not floating-main replacements.

Use history-preserving moves and ordinary corrective commits; never rewrite
published commit IDs or tags. Historical record content, approvals and qualification
claims remain intact apart from necessary relocation links/scope labels. Retired
examples remain explicitly retired. The existing 0.6.0/0.4.0 numerical tutorial
baseline and explicit DuckDB 1.x constraint are not relabeled as new qualification.

Ignored outputs such as `.venv/`, `src/`, `build/` or `dist/` may be present in a
working checkout without being tracked source. Inventory them separately; do not
mass-move/delete them or user `.env` files, admissions, real data projects, private
KBs, external Tau checkouts or other worktrees. Cleanup of owned disposable
outputs is an explicit implementation-plan concern, not a side effect of a path
mapping or of this documentation task.

## 7. Observable acceptance for a later migration

1. A fresh clone has two equal product areas and one joint area. The root's
   tracked content is common coordination/tooling; no implicit Ariadne-only docs,
   changelog, glossary, deployment files or standalone Agent directory remain.
2. Each product's packages, guides, records and assets resolve through its own
   area. Shared monorepo decisions/configuration remain shared; original record
   IDs and both glossary ownerships are preserved without duplicated authorities.
3. A reader can start with Lumio alone, Ariadne alone or the joint local recipe
   from the root entry. Product guides do not require installing the whole
   workspace; moved example commands and canonical documentation links resolve.
4. The root lock still covers exactly the same three members at new paths, with
   the same versions and third-party resolutions. The Agent is separately scoped
   and its local Core references resolve without assuming a new Tau installation.
5. Test collection preserves existing native and paired scenarios, their independent
   expected values and required CI coverage. No missing collection, weaker oracle,
   new skip/xfail or import fallback counts as a passing path repair. Root test/lint
   behavior has an explicit shared meaning rather than implicitly favoring Lumio.
6. Artifact checks retain names, dependency boundaries, licenses, console scripts
   and installed resources. Standalone/joint evidence is exercised at the assigned
   affected seam; source imports are not substituted for wheel proof. Document
   unqualified Agent/Tau capabilities honestly.
7. Release trigger/producer-pin/artifact-selection contracts remain intact without
   dispatching publication. Existing history and external repository state remain
   unchanged. Owned local changes and exact final candidate identities are
   independently reviewable before target integration.

Exact command selection, budgets, worktree ownership, execution order and recovery
belong to a future implementation plan. Reuse applicable semantic evidence and
run the affected path/discovery/installed checks required by that plan; do not
repeat an unchanged numerical journey solely for a folder or wheel label.

## 8. Capture checkpoint and current handoff

- **Vocabulary:** existing Ariadne/Lumio domain terms remain unchanged. Product
  area/integration area are source-layout descriptions, so no business glossary
  edit or new root glossary is required now.
- **Decision:** the owner chose product areas over parallel file-type namespaces.
  This materially affects source URLs and build/test callers; the trade-off and
  the earlier layout's historical role are captured in the ADR-0027 amendment.
- **Behavior:** this document defines the proposed path/ownership contract and
  acceptance; spec 0030's independent-product/runtime/release constraints persist.
- **Uncertainty/authority:** detailed revision 1 awaits review. No implementation
  plan or migration is dispatched. Current artifact/domain maps and all runtime,
  workspace, workflow, deployment and package files remain unchanged today.

Planning Contract version: 1; installed skill revision provenance: unknown.
