# Packaging, Ownership, and Migration

This document is the certified packaging contract for the Lumio workspace:
what each distribution owns, how dependencies flow, how optional capabilities
are expressed, how to migrate off the temporary compatibility surface, and
how the assembled product is verified. It is the authoritative companion to
[ADR-0010](../../project/lumio/adr/0010-uv-workspace-and-progressive-packaging.md),
[ADR-0025](../../project/lumio/adr/0025-repository-split.md) (repository split), and
the certification in `tests/lumio/test_workspace_certification.py`.

## Workspace shape

This repository is a [uv](https://docs.astral.sh/uv/) workspace with three
members; this document covers its **Lumio family** — the two independently
buildable, independently installable Lumio members sharing one lockfile
(ADR-0025). The independent Ariadne Core member (`packages/ariadne-data`)
has its own release channel and is documented on the Ariadne side. The web
application lives in a separate private repository and consumes these
published wheels.

| Member | Path | Wheel | Python root |
|---|---|---|---|
| `lumio-wiki` | `packages/lumio-wiki` | `lumio_wiki` | `lumio_wiki` |
| `lumio-lancedb` | `packages/lumio-lancedb` | `lumio_lancedb` | `lumio_lancedb` |

The workspace root (`pyproject.toml`) is coordination only — it declares the
workspace, shared dev tooling, and test/lint config. It is **not** a
distributable package: no `[project]` table, `tool.uv.package = false`.

Invariants (certified in `tests/lumio/test_workspace_certification.py`):

- Each member has its own `[project]` metadata and hatchling build backend.
- Each wheel ships exactly one top-level Python package root.
- The two public roots (`lumio_wiki`, `lumio_lancedb`) are disjoint — no wheel
  owns the other's concrete Python module path. (The private application's
  `lumio` root, owned and consumed by the separate private repository, remains
  a third, separately owned root.)
- One shared lockfile (`uv.lock`); no member carries its own.

## Distribution ownership

### `lumio-wiki` — portable Knowledge Base foundation

The standalone, model-free LLM Wiki toolkit. Owns the canonical contracts:

- Compiled Pages, Sources, Content Categories, the entity-claim ontology
  (Entities, Claims, Predicates), Evidence, citations, Retrieval Results,
  Retrieval Traces, validation records.
- Knowledge Base loading, Control File handling, validation, fingerprinting,
  Navigation Indexes, Hot Index, and OKF interchange. Activity Log production is transitional pending ADR-0022's Plan 05 cleanup; legacy marked-log recognition remains.
- Deterministic metadata/body search, accepted-Claim graph traversal,
  shortest paths, deterministic entity resolution, and the always-available
  zero-index retrieval implementation.
- Knowledge Sources, private immutable Source Versions, exact source bindings,
  Git authoring, complete-candidate validation and explicit Publication Admission.
- The `lumio-wiki` CLI (`setup`, `init`, `validate`, `search`, `page`, `related`,
  `paths`, `ingest`, `publish`, `legacy-proposals`, `health`, `doctor`, `skill`).
  Git is needed for authoring/admission, not plain reads, queries or validation.
- A short coding-agent protocol and a packaged Agent Skill, both shipped as
  wheel data and resolvable via `lumio-wiki skill`.

**Dependencies:** `msgpack`, `msgspec[yaml]` only. It does **not** depend on
LanceDB, PyArrow, Stario, Piccolo, OpenAI, LiteParse, MarkItDown, AnyDoc, or
any application module. Verified in every release by
`scripts/lumio/verify_lumio_wiki_wheel.py` (run from CI in an isolated venv) and
by `packages/lumio-wiki/tests/test_wheel_isolation.py`.

### `lumio-lancedb` — enhanced retrieval adapter

The optional LanceDB retrieval adapter. Depends only on `lumio-wiki` plus
its own retrieval stack. Owns:

- LanceDB index construction, update, freshness, and health.
- BM25 / full-text candidate ranking.
- Vector and semantic ranking when an embedding provider is configured.
- Hybrid and reciprocal-rank-fusion behavior.

It implements `lumio-wiki`'s retrieval interface without changing client
contracts. Importing the canonical `lumio_wiki` package never imports it and
there is no dependency edge from the foundation wheel. The CLI/evaluation
composition boundary may discover and lazily load it only when an operator
explicitly selects a LanceDB backend — the dependency graph remains one-way.

**Dependencies:** `lumio-wiki>=0.4.0,<0.5.0`, `lancedb`, `pyarrow`,
`msgspec[yaml]`. Optional `embeddings` extra pulls in
`sentence-transformers` (Torch stays out of the base adapter and out of
`lumio-wiki`). Verified in every release by the
`lumio-lancedb-wheel` GitHub Actions workflow, which installs the adapter
beside `lumio-wiki` alone in a fresh venv and asserts Stario/Piccolo/OpenAI/
LiteParse/MarkItDown are absent.

### `lumio` — full deployable application (separate private repository)

The deployable product lives in a separate private repository (ADR-0025) and
is **not** a member of this public workspace: nothing here builds, publishes,
or tests it. It consumes the published `lumio-wiki` and `lumio-lancedb` wheels
upward and selects zero-index or LanceDB retrieval through
`LUMIO_RETRIEVAL_BACKEND` and its single selection seam (`build_retrieval_index`
in `lumio.retrieval`). It owns Stario/Datastar presentation, the Chat Gateway,
the Agent Runtime, authentication and roles, operational SQLite/Piccolo state,
storage and synchronization, background work, provider integration, and
browser ingest/review workflows.

Its exact dependency ranges are owned and certified by that private
repository. The last ranges certified inside the former three-package
workspace (`lumio-wiki>=0.1.1,<0.2.0`, `lumio-lancedb>=0.1.1,<0.2.0`) predate
the current 0.4.x public family; the private application's compatibility
with the current family remains a separate integration and release decision,
not a claim of this repository.

## Dependency direction

```text
lumio-wiki  ←  lumio-lancedb
    ↑              ↑
    └────  lumio ──┘   (private application repository; consumes both wheels)
```

- `lumio-wiki` has no inter-member dependency.
- `lumio-lancedb` depends only on `lumio-wiki`.
- The private `lumio` application consumes both upward, from its own
  repository.

The public one-way direction is certified at the metadata level in
`tests/lumio/test_workspace_certification.py` (bounded inter-member ranges, one
package root per wheel) and re-verified per release by the wheel-isolation
jobs below.

## Optional capabilities

`lumio-wiki` is the only member that exposes optional capability extras
(ADR-0010: ingestion heavyweight implementations must be opt-in so the
standalone package stays lightweight). Each extra is self-contained — none
of them pulls in another `lumio-*` distribution.

| Extra | Adds | Capability |
|---|---|---|
| `lumio-wiki[documents]` | LiteParse, MarkItDown, AnyDoc | PDF / scanned-PDF / image (LiteParse, OCR + page numbers), office formats — Word/PowerPoint/Excel/OpenDocument/RTF/EPUB/CSV (AnyDoc), HTML and broad formats (MarkItDown). The base wheel handles text and Markdown. |
| `lumio-wiki[llm]` | `openai` | Unattended Distiller backed by an OpenAI-compatible provider. The base wheel uses the host coding agent as the Distiller (`--distiller passthrough`). |
| `lumio-wiki[all]` | both of the above | Document conversion + unattended distillation together. Still LanceDB-free. |
| `lumio-wiki[mcp]` | `mcp` (official SDK) | Read-only MCP stdio server (`lumio-wiki mcp <location>`) over ONE Knowledge Base Location: search, page, related, paths, hot, index, health, status. Never writes; fresh Snapshot per call. |

The LanceDB adapter and the local-embeddings capabilities live on their
respective distributions:

| Extra | Adds | Capability |
|---|---|---|
| `lumio-lancedb` | LanceDB, PyArrow | BM25 / vector / semantic / hybrid retrieval over the same Knowledge Base. |
| `lumio-lancedb[embeddings]` | `sentence-transformers` | Local embeddings for the LanceDB adapter. |
| `lumio[semantic]` | `sentence-transformers` | Local embeddings for the private application's LanceDB backend (owned by its repository). |

**Actionable missing-extra errors.** Invoking a capability without its extra
fails with the exact install command. PDF/DOCX/image ingestion from a base
install names `pip install 'lumio-wiki[documents]'`; `--distiller llm` from a
base install names `pip install 'lumio-wiki[llm]'`; `lumio-wiki doctor`
reports each extra's install state and the packaged skill location.

## Capability install matrix (certified)

Every capability is verified in isolation from a built wheel:

| Capability | Test | CI |
|---|---|---|
| `lumio-wiki` base (no extras) | `packages/lumio-wiki/tests/test_wheel_isolation.py` + `scripts/lumio/verify_lumio_wiki_wheel.py` | `ci.yml` (`isolated-lumio-wiki-wheel` job) |
| `lumio-wiki[mcp]` | installed-wheel startup + `search` smoke against `tests/lumio/fixtures/valid` | `ci.yml` (`isolated-lumio-wiki-wheel` job, `[mcp]` venv step) |
| `lumio-wiki[documents]` | `packages/lumio-wiki/tests/test_wheel_isolation_documents.py` | `ci.yml` (slow wheel suite) |
| `lumio-wiki[llm]` | `packages/lumio-wiki/tests/test_wheel_isolation_llm.py` | `ci.yml` (slow wheel suite) |
| `lumio-wiki[all]` | `packages/lumio-wiki/tests/test_wheel_isolation_llm.py::test_all_extra_installs_documents_and_llm_without_lancedb` | `ci.yml` (slow wheel suite) |
| `lumio-lancedb` | `packages/lumio-lancedb/tests/test_lancedb_adapter.py` | `lumio-lancedb-wheel.yml` |

## Adapter selection contract

The private `lumio` application (separate private repository) selects
retrieval through configuration and dependency injection — never by importing
adapter types in client modules. Its documented contract, owned there:

- **Single seam.** `lumio.retrieval.build_retrieval_index(kb, index_dir, *,
  backend=None, embedder=None)` is the only sanctioned entry point.
- **Config.** `LUMIO_RETRIEVAL_BACKEND=zero-index|lancedb` (its default is
  `lancedb`). Invalid values raise `RetrievalBackendConfigError` with
  migration guidance.
- **Local import.** `build_retrieval_index` imports `LanceDBRetrievalAdapter`
  inside its LanceDB branch, so zero-index deployments never force client
  modules to name `lumio_lancedb` symbols.

The public foundation has no mandatory dependency on `lumio-lancedb`:
a base install and package-root import work without the adapter. The existing
CLI/evaluation composition seam may name, discover and lazily load the
separately installed `lumio_lancedb` package. Retrieval loads it when the
LanceDB backend is selected. `lumio-wiki eval` includes LanceDB stages when
the adapter is installed; pass `--no-lancedb` to omit those stages. The
isolated wheel jobs below verify base-install and import independence.

## Versioning and compatibility

- Members share one workspace lockfile for development reproducibility.
- The lockfile is **not** a public compatibility contract. Every published
  inter-member dependency declares a bounded range
  (e.g. `lumio-wiki>=0.4.0,<0.5.0`, declared by `lumio-lancedb`). This is
  certified at the metadata level
  (`test_published_member_dependencies_declare_compatible_version_ranges`)
  and at the built-wheel METADATA level
  (`test_built_wheels_declare_bounded_inter_member_ranges`).
- Versions may move together initially. Breaking changes to `lumio-wiki`'s
  public contracts require bumping the upper bound in `lumio-lancedb` in the
  same change.

### Pre-1.0 release policy (issue #181)

Following ADR-0025, the two **public** distributions (`lumio-wiki` and
`lumio-lancedb`) release as one **lockstep family**. The private application
moves independently and is not published or qualified by this repository.
The current public family is 0.4.x.

- Both public members carry the **same version** (certified by
  `test_members_share_one_lockstep_version`). A release tag `lumio-vX.Y.Z` builds
  both public wheels from that one commit; the release workflow refuses a tag
  whose version does not match both members.
- **`0.MINOR` is the compatibility family.** Breaking changes to any public
  contract bump MINOR (and the inter-member upper bounds move in the same
  change). PATCH releases are compatible fixes only — the family never mixes
  a new member version with an older sibling.
- **Partial upgrades fail at install time, actionably.** Because every
  member-to-member range is bounded to the family (`>=X.Y.Z,<0.N+1.0`), a
  family-crossing combination (e.g. `lumio-lancedb==0.5.0` with
  `lumio-wiki==0.4.0`) is rejected by `pip`/`uv` resolution with a conflict
  naming both ranges — never a runtime failure. Certified by
  `test_inter_member_bounds_track_the_released_family`.

## Agent Skills

`lumio-wiki` ships a short coding-agent protocol and a packaged Agent Skill
as wheel data. Coding agents locate them deterministically without cloning
the Lumio repository:

```bash
lumio-wiki skill path                         # print the packaged SKILL.md path
lumio-wiki skill protocol                     # print the packaged PROTOCOL.md path
lumio-wiki skill install --scope user         # explicit shared-scope install
lumio-wiki skill install --agent <name>       # compatibility install for one agent
lumio-wiki doctor                             # report version, optionals, and skill path
```

The protocol and skill are force-included into the wheel via the
`[tool.hatch.build.targets.wheel]` `force-include` map in
`packages/lumio-wiki/pyproject.toml`. Both files also ship under the
importable `lumio_wiki.data` package, so `importlib.resources` resolves them
even under strict build configs.

## Temporary `lumio.core` compatibility (owned by the private application)

Canonical Knowledge Base behavior lives under `lumio_wiki`. The pre-1.0
`lumio.core` and `lumio.core.<module>` re-exports were compatibility shims of
the former three-package workspace; with the repository split (ADR-0025) they
belong to the private application's `lumio` package. Nothing in this public
workspace ships or certifies them — their removal timeline is the private
repository's decision. Consumers still importing `lumio.core` should move to
the final owners below; the mapping remains accurate guidance:

### Migration cheat sheet

| Old import (pre-1.0) | New owner |
|---|---|
| `lumio.core.knowledge_base` | `lumio_wiki.knowledge_base` |
| `lumio.core.records` | `lumio_wiki.records` |
| `lumio.core.retrieval` | `lumio_wiki.retrieval` |
| `lumio.core.index` | `lumio_lancedb` (adapter) / `lumio_wiki.retrieval` (zero-index contract) |
| `lumio.core.evidence` | `lumio_wiki.evidence` |
| `lumio.core.page_search` | `lumio_wiki.page_search` |
| `lumio.core.fingerprint_store` | `lumio_wiki.fingerprint_store` |
| `lumio.core.okf` | `lumio_wiki.okf` |
| `lumio.core.embeddings` | `lumio_wiki.embeddings` |
| `lumio.proposal_pipeline` | Retired: Git authoring and `preview_publication` / `publish_revision`; legacy records use explicit inventory/export only |
| `lumio.source_processor` | `lumio_wiki.source_processor` |

## Build and release

```bash
uv lock --check                              # verify the workspace lockfile is current
uv build --package lumio-wiki --wheel        # build one member wheel
uv build --package lumio-lancedb --wheel
```

Each member builds from the workspace without its siblings having to be
pre-built — the wheel's METADATA carries the bounded range and the installer
resolves the sibling from PyPI (or from a local wheel index) at install time.

CI certifies every release:

1. `ci.yml` (`workspace` job) — locked lint and full suite with four workers.
2. `ci.yml` (`isolated-lumio-wiki-wheel` job) — builds the two public wheels,
   installs `lumio-wiki` alone in a fresh venv, and runs
   `scripts/lumio/verify_lumio_wiki_wheel.py`: candidate wheel/member/installed-byte
   identity, lightweight dependencies, native author/admit/query and Git-free
   reading. Installed MCP gets a separate optional-extra smoke.
3. `lumio-lancedb-wheel.yml` — builds the `lumio-lancedb` and `lumio-wiki`
   wheels, installs them alone in a fresh venv, asserts the app-only deps
   are absent, and runs the adapter smoke.
4. `ci.yml` (`onboarding-s3-compat-journey` job) — canonical onboarding and
   both packages' existing live S3-compatible checks against the pinned
   disposable SeaweedFS service. Cross-role policy checks require separately
   supplied test roles and otherwise remain unverified.

The private application is not tested or certified here (ADR-0025). Its known
proposal-facing incompatibility remains a separate integration/release decision.
No public candidate validation authorizes target integration or publication.

### Releases

`release.yml` (issue #181) turns a pushed `lumio-vX.Y.Z` tag into a certified
publication. One pipeline, no rebuilds:

1. **Build once** — `build-wheels` builds both public wheels from the tagged
   commit, asserts the lockstep version, records SHA-256 hashes (workflow
   summary + artifact) and SLSA build provenance bound to the tag.
2. **Verify the candidates** — both jobs download the build artifact, verify
   its recorded hashes and install those exact wheel files in fresh venvs:
   - `verify-wiki` — isolation, packaged skill, local-library smoke and
     optional-extras resolution (`scripts/lumio/verify_lumio_wiki_wheel.py`).
   - `verify-s3-compat` — the canonical onboarding journey
     (`examples/lumio/onboarding-journey/smoke-journey.sh`) against the disposable
     SeaweedFS service: local Maintainer journey, S3 publication with and
     without LanceDB, remote LanceDB reader and zero-index fallback.
3. **Automatic publication** — `promote-pypi` runs after both candidate
   checks pass. It downloads the same build artifact, verifies its hashes
   (`sha256sum -c`) and publishes those exact wheels directly to PyPI.
   No manual deployment approval or staging-index account/token is required.

**Credential model.** Publishing uses one GitHub Environment secret:
`PYPI_API_TOKEN` in `pypi`. It must authorize both public distributions;
a token for another project is not sufficient.
The workflow fails before upload if a token is missing, never falls back to
Trusted Publishing, and never prints token values. Ordinary CI and pull
requests do not receive these secrets. The `pypi` environment scopes the token;
it has no required reviewers or wait timer. Artifact verification still gates
production publication.

GitHub's tagged-build SLSA provenance and recorded SHA-256/byte comparisons
remain enabled. The publish action's PyPI digital attestations require Trusted
Publishing and are disabled for this token-based mode. No workflow action
shares an Actions cache with PR-triggered workflows.

**One-time owner setup**:

1. Create GitHub environment **`pypi`** without required reviewers or a wait
   timer.
2. Store `PYPI_API_TOKEN` in that environment. For a first publication,
   ensure the token's scope permits creating both projects;
   review the narrowest workable scope after creation. Never put tokens in a
   repository file, command argument, release note or conversation.
3. Protect the `lumio-v*` tag pattern (admins/maintainers only) so only
   authorized pushes can start a release. (Core releases use the separate
   `core-vX.Y.Z` channel; protect that pattern independently for the Core
   side — neither channel can publish the other family.)

Release notes live in `docs/lumio/release-notes/` per published version. The current
public-family notes are [`v0.4.0.md`](release-notes/v0.4.0.md); older notes are
historical and may describe the former private three-package workspace.

## Issue graph certification (issue #104, AC7)

The workspace migration (parent #93) and its contraction (#103) are
certified by this issue (#104) without duplicating any product scope that
lives in the downstream issue graph. The audit was performed against the
live issue tracker; the exact blocker edges verified at certification time
are recorded below so future drift is detectable.

### Closed feature tickets implemented against the workspace

- **#84** (extensible categories) — closed; implemented against
  `lumio_wiki` (Control File + validation).
- **#85** (external-vault import) — closed; reuses the generic OKF import
  path under `lumio_wiki`.
- **#86** (cross-page QA report) — closed; implemented against
  `lumio_wiki` validation + Discovery Graph outcomes.

### Open product tickets and their workspace blockers

| Issue | Blockers | Workspace edge |
|---|---|---|
| #87 (category mapping) | #84, #85 | none (closed-feature blockers only) |
| #88 (navigation regeneration) | #85 | none |
| #89 (import CLI/UI) | #85, **#102** | workspace foundation |
| #90 (link-candidate finder) | #86 | none |
| #91 (lint + cross-linker skills) | #86, #90, **#98** | lumio-wiki CLI/skill |
| #92 (Maintainer QA dashboard) | #86, #91, **#102** | workspace foundation |

Every workspace-coupled blocker points at the foundation tickets (#102
workspace, #98 lumio-wiki CLI/skill) introduced by the migration — never
at #104. #104 owns only certification and documentation.

### Ownership-language note

The prose in #90 and #91 still uses the legacy phrase "Core SDK operation"
rather than naming `lumio_wiki` directly. Updating that prose is owned by
those issues (their scope is the finder/skill behavior), not by this
certification pass. #104's contract is that the **implementation** of those
issues, when it lands, must import from `lumio_wiki` — an invariant locked
at the AST level by
`tests/lumio/test_package_contraction.py::test_production_modules_do_not_import_compatibility_surfaces`.

### Automated dedup guardrails

- `tests/lumio/test_workspace_certification.py` — structural ownership (one
  Python root per wheel, bounded inter-member ranges).
- `tests/lumio/test_package_contraction.py` — no internal caller imports
  `lumio.core.*` compatibility shims; no compatibility module owns a
  duplicate implementation; dependency direction is one-way.

## Out of scope

- A separately published `lumio-web` distribution. The existing `lumio` name
  already represents the deployable web product (ADR-0010).
- Structured dataset query execution. The DuckDB seam remains post-MVP
  (PRD-0001). Ingestion may still create Table or Dataset Descriptors without
  making data queryable.
- Multi-tenant deployments. The MVP is deliberately single-tenant.
