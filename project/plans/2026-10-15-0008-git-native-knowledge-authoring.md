# Implementation plan 0008: Git-native Knowledge Authoring

**Revision/status:** 1 — owner-approved for supervised execution.

**Execution approval:** owner **“Ja. Freigabe”**, 2026-10-15, in response to
“Gibst du Plan r1 zur Umsetzung im Supervised-Modus frei?”, presented at isolated
plan commit `299f1f146e864177cc8e7158cbee3833dd17ab1a`. This approves C0–G5
candidate preparation and proportional review, not target integration or
publication. Preflight begins with C0; no runtime result is claimed by this
approval record.

**Goal:** deliver the Git-only authoring replacement and the bounded private
KB-read-only consumer candidate specified in
[approved specification 0008 r1](../specs/2026-10-15-0008-git-native-knowledge-authoring.md).
That specification owns behavior and AC1–AC7; this plan owns execution order,
file ownership, and checks. [ADR-0029](../adr/0029-git-native-knowledge-authoring.md)
owns architectural rationale and scoped supersession.

**Source approval:** owner **“Ja Freigabe”**, 2026-10-15, approving the written
r1 presented at `81ed0f7c15c8295cf0799c88d08a570749ff5f73`. Approval and source
reconciliation are recorded in `61075674f4150db31dfa7f833f1e578edaeca0a4` on
`design/issue1-git-authoring-20261015`. Source behavior is unchanged by that
approval-record commit. The underlying runtime baseline remains public
`c3b68db233f8aa98a39380a0099ff2b800a70c55`; private base is
`43facf97fc40497688b54546b511c5bd392396a6`.

**Authority:** the explicit execution approval above and original request
authorize supervised execution of this approved plan. Recheck the orchestrator
preflight before every dispatch. Prepare isolated reviewed candidates only;
no target integration, push, PR/issue
mutation, real KB migration/publication, deployment, or release is authorized.
All ingest/export/publication checks below use disposable fixtures, not
`/home/volker/coding/lumio/.wiki` or production stores. This plan does not create
tracker tickets or duplicate task bodies in GitHub; #1 remains the intake issue.

## Constraints, capture, and operating context

- Python >=3.14; existing uv/msgspec/msgpack core, Git executable for authoring,
  optional obstore/LanceDB/documents/LLM/MCP as today. No new mandatory database,
  model, GitHub service, Git library, Ariadne, DuckDB, or SQLGlot dependency.
- Capture checkpoint: glossary terms are in `CONTEXT.md`; accepted ADR-0029 and
  linked scoped amendments reconcile the old proposal-first contract; approved
  spec sections 1–9 own behavior/non-goals/acceptance. No material #1 decision is
  open. #2/#76 Context Provider, ontology mappings, and Ariadne's Policy-fallback
  amendment remain explicitly excluded and unapproved.
- Public callers are CLI, packaged skill/PROTOCOL/setup, ingest/capture/import/
  maintenance helpers, snapshots and optional adapters. Private production
  imports still reach proposal types and low-level publish functions; its
  development metadata resolves sibling editable sources. See the
  [consumer evidence](../research/2026-10-15-git-authoring-consumer-impact.md).
- Existing conventions: aggregate validation and stable public Evidence/citation
  contracts; framework-free core; explicit source identity and private raw bytes;
  authorization before graph expansion; deterministic transformations in code,
  judgment in skills; four test workers only. Use existing mutation locks,
  checked-path handling and compensation where still needed; do not delete them
  merely because proposal-specific orchestration disappears.
- Execution host when authorized: detected Paseo/Pi on oa1. Revalidate live
  allocator root `${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/`, explicit
  workspace/repository/base bindings, exact effective model/thinking, and child
  dependencies. Follow `orchestrate-implementation`; no second scheduler or
  sign-off ledger is introduced here. Default role pairs, unless higher-priority
  configuration overrides them: worker `zai/glm-5.3`/`high`, reviewer
  `openai-codex/gpt-6.1-sol`/`high`; availability is not yet proven for this run.
- One sequential public writer and one separately bound private writer, never
  concurrent writers on a checkout. This plan intentionally does not parallelize
  shared `cli.py`, `__init__.py`, registry, publication, or producer surfaces.
  Use committed, frozen result refs and accepted upstream candidate commits.

### Risk and review boundaries

Consumer permissions, immutable activation, exact private bindings, migrations,
and public API retirement are high-risk units. Independently review each such
contract before a downstream task consumes it. Parent inspection applies to all
results. Candidate review covers integration/unreviewed deltas only, not settled
findings. One parent-authorized fix pass and one delta-only recheck per finding;
then hand back unresolved blockers. Every fresh reviewer receives the complete
installed reviewer contract inline, exact source criteria, written conventions,
and real callers. Children never run OptMem or write shared memory.

Touched boundaries: authenticated app write routes (published knowledge/private
source assets; a real Reader/Maintainer can call endpoints directly), external
import/source bytes (path confinement/private-source exclusion), dependency
artifact resolution (baseline wheel identity), and local/S3 publication pointers
(concurrent legitimate publishers and failed I/O). Review those actual paths;
do not invent stolen-secret, malicious-admin, or generic-hardening scenarios.

## Order and requirement coverage

`C0 → G1 → G2 → G3 → G4 → G5`.
C0 produces a private candidate and retained wheel artifacts, not a public
runtime commit. G1–G5 are sequential public candidate descendants. Neither repo
is merged into a target. Final delivery retains both candidate refs and the
wheel-archive prerequisite.

| Unit | Source / principal acceptance | Consumed → produced interface |
| --- | --- | --- |
| C0 | §8, AC6; baseline part of AC7 | unchanged public packages/private app → hash-pinned wheels + KB-read-only consumer candidate |
| G1 | §2–4, local §5; AC1, AC2, AC3, AC4, AC7 | v1 Source Reference Manifest + existing page/registry contracts → complete local author/commit/review/admit/publish/read path |
| G2 | §3.3/5; AC3, AC4, AC7 | reviewed G1 captured revision/receipt → S3/LanceDB activation, exact source inspection and historical rollback |
| G3 | §1/6/7 producer table; AC1, AC4, AC7 | reviewed authoring/publication seams → all retained ingest/import/maintenance/entity-mutation workflows |
| G4 | §7; AC5 plus no-proposal parts of AC1, AC4 | all migrated callers + original legacy format → explicit export + removal of live proposal lifecycle |
| G5 | §7/9, AC1–AC7 | frozen C0/G1–G4 results → installed/cross-consumer evidence, current operating guidance, reviewed supervised delivery |

The public change is a wide API migration. Expand only the new functions needed
by G1, migrate real callers in G2/G3, then contract in G4. Any temporary old
proposal code exists solely for not-yet-migrated callers/tests and the legacy
format reader; G4 removes its live lifecycle. During expansion, a manifest-bearing
Git ingest and `publish --revision` use the new complete route; original legacy
invocations remain only for not-yet-migrated `test_cli.py`, wheel/onboarding
journeys and producer consumers. A present but invalid manifest never falls back
to legacy staging. Add no temporary flags or new compatibility product. Migrate
those real consumers in G3/G4, then remove the legacy dispatch in G4 together
with its last operating examples/tests. Keep intermediate commits coherent;
no intermediate candidate may be integrated/released as completed #1.

## C0 — Freeze the old foundation and protect the private consumer

**Owner/prerequisite:** private Pi writer, authorized only after plan approval;
private base above and unchanged public runtime baseline. Do this before
incompatible public CLI/SDK edits.

**Owned files:** private `pyproject.toml`, `uv.lock`,
`packages/lumio/pyproject.toml`, `packages/lumio/src/lumio/{app,cli,ui}.py`,
`packages/lumio/src/lumio/storage/{git,shared,hybrid,s3,backends,config}.py` only where a real
reachable write/sync entry needs the boundary; `.github/workflows/ci.yml`,
`AGENTS.md`, `README.md` for artifact prerequisites/read-only disclosure; new
`tests/test_kb_read_only.py`; existing `tests/test_{workshop,publish,
write_mode_config,source_submission,source_promotion,external_import_publish,
okf_import,external_vault_import,import_entrypoints,compound_ingest,ingest,
ingest_surface}.py` where their app-exposure expectations change, plus the
preserved Reader/auth checks below. Do not rewrite private ingest/domain implementations or build a Git Workshop.
Load private instructions/platform sources and Stario guidance before code;
Workshop disclosure follows existing components, not a UI redesign.

- [ ] Allocate an isolated unchanged-public build checkout and private worktree
  through the selected host. Run smallest existing baselines before mutation:
  public source/captured-S3 checks and private Reader/auth checks listed below.
  A failing baseline blocks implementation for owner disposition.
- [ ] Build both baseline wheels with existing uv build metadata, without
  changing versions/dependencies. Keep actual wheels, source SHA and SHA-256s in
  a retained private artifact directory outside disposable worktrees. Do not
  substitute the checked-in prior `0.1.1` fixture, invent a `0.1.2` PyPI release,
  upload anything, or upgrade dependencies to hide an unavailable baseline.
- [ ] Replace sibling editable sources with exact local artifact references and
  hash-locked resolution for both `0.1.2` wheels and matching extras. CI/install
  documentation must require the supplied archive, not clone floating main or
  silently contact a nonexistent index. Prove installed module files match the
  supplied wheels; `uv.lock` text alone is not adoption evidence.
- [ ] Reject every server-side KB mutation named in spec §8, including direct
  requests, old direct-write/override settings and Conversation Source submit/
  promotion. Refuse the private CLI's `lumio import` legacy proposal writer too.
  Existing role denial remains; neither Maintainer nor Owner bypasses the
  transition boundary. Keep historical records untouched.
- [ ] Preserve reading/chat/citations, temporary Conversation Sources, auth and
  account admin. Apply the same boundary to bootstrap/background pulls, HTTP
  sync and the private CLI sync path: consume an immutable published snapshot,
  not a floating Git/shared authoring tree. Keep an explicitly selected existing
  legacy snapshot readable without pretending it has new Git admission.
  Explain refused unadmitted pulls in Workshop/CLI output without adding a
  re-enable-write feature flag.

**Validation unit C / high risk / `new-test`:** one parameterized authenticated
HTTP test in `tests/test_kb_read_only.py` uses an explicit action/route list from
spec §8 and the inspected baseline registrations (`app.py:6029–6075`). For each
KB write, assert refusal and unchanged canonical/private proposal/source state,
including direct-write configuration. Expected refusal/preservation comes from
AC6, never current output or a dynamic router-derived oracle. Exercise the
reachable initial/sync pull of an unadmitted authoring branch without replacing
the selected readable snapshot. Include CLI import at its CLI seam. Migrate
existing success assertions for
retired web writes to the approved read-only contract; do not delete unrelated
Reader, role or account tests.

Focused commands (existing cases retained/migrated as appropriate):

```sh
# unchanged public build checkout
uv run pytest -q packages/lumio-wiki/tests/test_managed_ingest.py packages/lumio-wiki/tests/test_s3_publish.py
uv build --package lumio-wiki --wheel --out-dir "$BASELINE_ARCHIVE/wiki"
uv build --package lumio-lancedb --wheel --out-dir "$BASELINE_ARCHIVE/lancedb"
# isolated private candidate, resolving those exact artifacts
uv run pytest -q tests/test_kb_read_only.py tests/test_import_entrypoints.py tests/test_reader_route_contract.py tests/test_auth_roles.py tests/test_chat_sources.py tests/test_account_admin.py
```

`BASELINE_ARCHIVE` is the validated retained artifact path recorded by the
parent, not a production directory. Before removal of public proposal APIs,
independent C review and real installed-wheel/read-only evidence must pass.
**Done:** committed private result, actual retained hashes/install proof and
server-side refusal/preserved Reader evidence; no private target change.

## G1 — Complete standalone local Git authoring and publication

**Owner/prerequisite:** public Pi writer from the approved-source candidate;
C0 accepted. Reuse existing captured-content loading, checked mutation paths,
registry history and validation; no generic Git/storage framework.

**Owned files:** new `packages/lumio-wiki/src/lumio_wiki/git_authoring.py` and
`source_references.py`; existing `ingest.py`, `source_registry.py`, `publish.py`,
`location.py`, `records.py`, `artifact_store.py`, `mutation.py`, `cli.py`,
`env_loader.py`, `__init__.py`; new `packages/lumio-wiki/tests/test_git_authoring.py`,
related `test_cli.py`, `test_location_snapshot.py`, `test_managed_ingest.py`
assertions affected by the new route. Existing legacy journeys remain until
their G3/G4 migration; new tests explicitly select the Git/manifest route.
Only source-pin-aware authoring/publication metadata enters the new modules;
existing canonical schema and read-only APIs are not reinvented.

- [ ] Implement strict manifest v1 from spec §3.1, append-only private version
  lookup/registration, explicit shared-registry selection, and regular in-scope
  Git-blob capture. Keep exact manifest digest distinct from canonical
  fingerprint. Materialize no hooks, links, raw stores or unrelated Git paths.
- [ ] Provide one complete managed/source-free ingest → ordinary worktree edits
  → native commit → publication preview → exact confirmation → immutable local
  Snapshot journey at CLI and SDK seams. Preserve author edits on rejected
  operations. Helpers never commit implicitly; tests/users invoke Git explicitly.
- [ ] Implement source intent/eligible-support impact, exact historical binding
  metadata even with raw retention disabled, admission digest/private receipt,
  expected-current local activation, retry, legacy adoption and local rollback
  as specified. Native Git reconciles obsolete bases; no custom merge queue.
- [ ] Route local `publish --revision ...` through that one owner. Co-migrate
  changed CLI journey assertions and expose the new public result fields before
  dependent tasks consume them. Retain old SDK proposal callers only for G3/G4;
  do not reinterpret their records as admission.

**Validation unit L / high risk / `new-test`:** a public CLI/SDK journey in
`test_git_authoring.py` authors a small v2 Entity/Claim fixture and binds raw bytes
A. Register bytes B after reviewing A, then publish A: its Evidence, historical
binding, manifest digest and receipt still identify A; no proposal files exist.
Use `hashlib.sha256(b"A")` and independently authored Claim/section expectations,
not implementation snapshots. Extend this journey with distinct refusal cases:
invalid claim/anchor/link/source refs, changed review input/current pointer,
failed local preparation/activation, and edited authoring files. Prior Snapshot
bytes and author files remain unchanged. Reuse existing validation and location
checks rather than duplicating every record field.

```sh
uv run pytest -q packages/lumio-wiki/tests/test_git_authoring.py packages/lumio-wiki/tests/test_location_snapshot.py packages/lumio-wiki/tests/test_entity_claims.py packages/lumio-wiki/tests/test_cli.py
```

**Done:** one usable local vertical path and documented structured outputs;
independent L contract review passes before G2/G3 consume it. Final command/API
names must express the approved semantics; a material change returns to shaping.

## G2 — Complete optional backends and exact historical inspection

**Owner/prerequisite:** public writer from accepted G1 candidate; C0 retained.

**Owned files:** `packages/lumio-wiki/src/lumio_wiki/{publish,s3_publish,s3_location,
location,artifact_store,source_inspection,source_resolution,cli}.py`;
`packages/lumio-lancedb/src/lumio_lancedb/{publish,location,index,graph}.py` only
where version-bound build/read composition needs it; existing `test_s3_publish.py`,
`test_s3_location.py`, `test_artifact_store.py`, `test_source_inspection.py`,
`test_source_resolution.py` in the wiki tests and `test_remote_index_location.py`,
`test_publication_s3_compat.py` in adapter tests. `LanceDBRetrievalAdapter` lives
in `index.py`; do not invent an `adapter.py` or a second adapter hierarchy.

- [ ] Reuse G1's captured revision/receipt, extending existing S3 create-only /
  ETag-CAS operations rather than recapturing working files. Seal the private
  receipt/bindings before activation. No callable CLI/SDK working-tree publish
  or rollback bypass may be retained in the final candidate.
- [ ] Build and verify requested local/remote LanceDB artifacts against that
  same candidate. Failure blocks activation; read fallback remains zero-index
  over the same Snapshot with truthful Trace. Preserve old Published Version
  readers and private binding formats, without fabricating Git admission.
- [ ] Resolve source inspect/fetch/link and rollback from exact authoring pins or
  historical version bindings; never registry-latest fallback. Keep required
  retention gates, source authorization, signed-link redaction and no managed
  remote disk cache.

**Validation unit R / high risk / `existing-check`:** adapt the existing
`test_s3_publish_uses_one_captured_candidate`, CAS/failure/rollback, exact-source
inspection and remote-adapter contracts to consume G1 admission rather than
keeping old bypasses for test convenience. Their oracles already establish old
pointer preservation, source A identity and index/fingerprint consistency.
Add a focused case only if receipt-before-activation or a genuinely distinct
new failure remains unexercised; derive its expectation from spec §4–5.

```sh
uv run pytest -q packages/lumio-wiki/tests/test_s3_publish.py packages/lumio-wiki/tests/test_s3_location.py packages/lumio-wiki/tests/test_artifact_store.py packages/lumio-wiki/tests/test_source_inspection.py packages/lumio-wiki/tests/test_source_resolution.py packages/lumio-lancedb/tests/test_remote_index_location.py
```

**Done:** admitted local/S3 versions and optional indexes/inspection agree;
independent R review passes before producer migration/final contraction.
Live S3 proof remains part of G5, not inferred from MemoryStore.

## G3 — Route every retained producer through ordinary Git edits

**Owner/prerequisite:** public writer from accepted G2; use its established
result/validation contracts, never a renamed proposal wrapper.

**Owned files:** `packages/lumio-wiki/src/lumio_wiki/{git_authoring,ingest,
proposal_pipeline,publish,maintenance,semantic_maintenance,graph_exchange,okf,
capture,url_fetch,distiller,cli,__init__}.py`; existing entity-mutation,
maintenance, ingest/optional-extra, capture and exchange tests. `proposal_pipeline.py`
is only a temporary extraction source here and is removed in G4.

- [ ] Move deterministic rename/move/remove/merge, compound provenance and
  impact/repair behavior to worktree edits. Preserve exact-resolution rules,
  explicit aliases, stable IDs, redirects/pins and collision/path safety; validate
  the complete candidate. Old runtime Snapshots do not change with author edits.
- [ ] Convert maintenance/semantic apply and OKF/graph/external imports to those
  same edits. Reflection/export stays read-only and visibility-safe; generic OKF
  metadata remains lossy-with-disclosure, not a future Ariadne profile.
- [ ] Convert managed/passthrough, URL/research, capture adapters and optional
  unattended distillation. Preserve original-source identity, routing, redaction,
  explicit consent, bounded errors and optional dependency isolation. Private
  Capture Manifests remain outside Git/Reader content.
- [ ] Migrate every actual CLI/SDK producer caller and its affected focused
  tests. Scope helper extraction to live behavior; no unrelated Plan 05 cleanup.

**Validation unit P / high risk / `existing-check`:** adapt existing public-seam
mutation/capture/ingest tests to inspect Git changes and then admitted snapshots,
not staged JSON. Preserve independent expected Claim targets, redirects, pins,
source lists, redaction and visibility outcomes; only obsolete proposal-state
assertions retire. Existing mutation behavior is pinned by the focused baseline
before extraction; do not over-mock the unit or copy generated output as gold.

```sh
uv run pytest -q packages/lumio-wiki/tests/test_entity_merge.py packages/lumio-wiki/tests/test_page_removal.py packages/lumio-wiki/tests/test_source_lifecycle.py packages/lumio-wiki/tests/test_maintenance.py packages/lumio-wiki/tests/test_semantic_maintenance.py packages/lumio-wiki/tests/test_capture.py packages/lumio-wiki/tests/test_capture_adapters.py packages/lumio-wiki/tests/test_url_ingest.py packages/lumio-wiki/tests/test_graph_exchange.py packages/lumio-wiki/tests/test_okf.py packages/lumio-wiki/tests/test_external_vault_import.py
```

**Done:** every retained producer yields ordinary files/diffs, not persisted
proposals. Parent verifies callers; independent P review of destructive repairs
and private-source/consent preservation passes before G4 deletes their old owners.

## G4 — Export legacy intent, then retire the live proposal lifecycle

**Owner/prerequisite:** public writer from accepted G3; C0 consumer proof and
frozen source formats available. Only synthetic legacy stores are exercised.

**Owned files:** new `packages/lumio-wiki/src/lumio_wiki/legacy_proposals.py`;
`{ingest,proposal_pipeline,publish,source_registry,capture,maintenance,
semantic_maintenance,cli,__init__}.py` in that package; new
`packages/lumio-wiki/tests/test_legacy_proposal_export.py` and sanitized fixture
`tests/fixtures/legacy_ingest/`; affected old lifecycle/API tests, including
`test_cli.py`, `test_wheel_isolation.py`, `test_skill_public_surface.py` and
`tests/test_onboarding_journey.py`. Co-switch the existing packaged
`data/skill/{SKILL,PROTOCOL}.md`, CLI-generated guidance,
`docs/quickstart.md`, `examples/onboarding-journey/smoke-journey.sh` and
`scripts/verify_lumio_wiki_wheel.py` where retiring the last old command would
otherwise leave its real installed/documented caller broken.

- [ ] Implement read-only inventory/preview and explicit branch export from the
  original persisted format, including source transitions, compound semantics
  and stale preconditions. Unknown/stale bindings or unsupported operations
  block disposition; never borrow registry-latest or publish on export.
- [ ] Preserve original bytes/private history and a private idempotent export
  receipt. Preview creates nothing; retries recognize matching output, while
  modified output conflicts. Export/archive never erases an original store.
- [ ] After checking every migrated caller, remove live `ProposalPipeline`,
  `IngestProposal`/proposal persistence exports, terminal-state commands and
  proposal-keyed source pending transitions. Retain only explicitly private
  legacy decoding/export and ordinary locks/atomic helpers still used. Pending
  legacy registry state cannot be silently ignored by a new writer.
- [ ] Search production/import/export/entry-point surfaces in both repos and
  scripts. Remaining private old-type imports are allowed only in C0's proved
  old-wheel consumer; public old-format names may remain only in migration
  reader/fixtures/history. No renamed queue, dual persistent write mode, custom
  auto-merge or working-tree publication backdoor survives.

**Validation unit M / high risk / `new-test`:** one export journey with explicit
legacy fixture intent (page mutation plus source transition) asserts no writes
on preview; unadmitted Git output after confirmation; exact original-store/raw
preservation; unchanged published pointer; matching retry and edited-output
conflict. A stale/unknown-binding variant must refuse without losing data.
Expected pages/hash/transition come from the fixture and spec AC5, not the new
exporter's serialization.

```sh
uv run pytest -q packages/lumio-wiki/tests/test_legacy_proposal_export.py packages/lumio-wiki/tests/test_git_authoring.py packages/lumio-wiki/tests/test_ingest_journey.py packages/lumio-wiki/tests/test_source_lifecycle.py
rg -n 'IngestProposal|IngestStore|ProposalPipeline|pending_transitions|proposal (list|inspect|validate)|publish-s3' packages scripts examples tests
```

Disposition every remaining match by actual role; do not require a false global
zero that deletes migration/history evidence. **Done:** operator-safe export and
no live proposal lifecycle; independent M review passes before G5 certification.
The one real observed staged proposal is not migrated by this implementation run.

## G5 — Operating guidance, installed evidence, and supervised delivery

**Owner/prerequisite:** public writer/parent candidate assembly from G4; retain
accepted private C0 ref/artifacts. No target integration.

**Owned files:** `packages/lumio-wiki/src/lumio_wiki/data/skill/{SKILL,PROTOCOL}.md`,
`skill.py` bundle-hash/manifest behavior and `cli.py` setup guidance in that
package; `AGENTS.md`, `README.md`, `docs/{usage,quickstart,kb-format,packaging}.md`,
`examples/onboarding-journey/smoke-journey.sh`,
`scripts/verify_lumio_wiki_wheel.py`, `.github/workflows/ci.yml`;
`packages/lumio-wiki/tests/test_{wheel_isolation,skill_public_surface,
skill_management,mcp_server}.py`, `tests/test_onboarding_journey.py` and
`tests/test_wheel_verifier.py`. G4 already removes obsolete operating examples;
G5 checks the complete installed protocol. Both packaged Markdown files belong
to `lumio_wiki.data.skill`; do not invent a second protocol file under
`data/protocol/` or an unrelated distribution-version bump.

- [ ] Replace current proposal workflow examples with native Git authoring,
  exact review/confirm admission, source privacy and explicit migration. Update
  assertions against installed skill bytes, not just repository Markdown. Do not
  refresh globally installed user skills or edit the real shared KB.
- [ ] Run installed-wheel author/validate/query journey without Ariadne/model/
  server/GitHub/LanceDB; additionally remove Git from the read/query subprocess
  PATH to prove plain reads still work. Use the new built candidate wheels,
  not C0's legacy wheels or workspace imports. Reuse/update existing wheel
  isolation/verifier tests rather than building a second harness.
- [ ] Run required CI checks below on exact candidate trees. Refresh canonical
  onboarding and existing live S3-compatible checks against an isolated test
  service using the repository's pinned CI image/configuration. No production
  credentials/endpoints, no modification/restart of running services, no
  implicit runtime/architecture installation. Missing capability blocks the
  corresponding certification claim for owner disposition, not a silent skip.
- [ ] Parent verifies exact public/private commits, artifact hashes, acceptance
  coverage and terminal child ownership. One final independent candidate review
  covers unreviewed guidance/packaging and integration effects only. Preserve
  refs/worktrees/artifacts and deliver `merge-worktree` handoffs, paused before
  either target branch. Do not close #1 or start dependent #2 coding implicitly.

**Validation unit D / `existing-check`** for installed/public-read contracts;
**`no-new-test`** for docs/metadata. Adapt the existing isolation journey to the
new approved flow and Git-free read case; these establish real installation
and command behavior, not a coverage target. Full candidate gates are the
repositories' existing CI: `uv lock --check`, locked sync, locked Ruff and
`uv run --locked pytest -q -n 4` in each isolated repository (serial focused
commands above remain development defaults). No `-n auto`.

Live public checks use `tests/test_onboarding_journey.py` and the existing
`*_s3_compat.py` suites under both packages; record actual execution and any
unavailable cross-role policy provisioning. Never call MemoryStore results
live S3 evidence. Private final checks run against C0's exact wheel archive,
not the incompatible new public wheel. Candidate base/head plus archive hashes
and actual command outputs belong in the existing orchestrator/host run state,
not a new assurance ledger.

**Done:** AC1–AC7 have concrete same-surface evidence; public and private
candidates are committed, reviewed, and preserved; skipped/unavailable gates are
explicit. Choose `accept / fix / hand back / ask` against the approved scope.
Separate authorization is still required for integration, real data migration,
publication, issue updates, deployment, push and release.

## Handoff and remaining gates

The plan/execution approval is recorded above. Writing and approving this plan
did not itself run a worker, feature test, wheel build, test service, dependency
installation, real legacy export, or publication. Installed role/runtime
capability, baseline checks, actual artifact hashes, private CI archive transport
and live test-service availability remain prerequisites to verify during
execution, not invented facts. Changes
to approved behavior/interfaces return to shaping; infrastructure or baseline
failures go to the owner without switching hosts or weakening checks.

Planning-contract v1; installed skill SHA-256
`5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`;
upstream installed catalog commit unknown. The selected `orchestrate-implementation`
skill owns dispatch, review, frozen results and patch-only recovery after approval.
