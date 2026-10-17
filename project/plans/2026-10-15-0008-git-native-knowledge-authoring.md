# Implementation plan 0008: Git-native Knowledge Authoring

**Revision/status:** 9 — G1 accepted; G2 fix-first corrections and local
LanceDB completion are owner-authorized for one isolated candidate. Behavioral
specification unchanged.

**Owner-authorized D1 residual follow-up, 2026-10-17 (r9):** after the
independent `8b034283…c393114e` delta review closed D2–D5 and returned two
accepted D1 residuals, the owner answered “Gezielt beheben” to resume the
same GLM/high worker for only those two repairs in the same candidate (base
pin `base/g2-fix-a3` = `c393114e…`, sole future result `result/g2/fix-a3`):
D1-A — the adoption legacy-store fallback must verify the selected binding
manifest's embedded `published_version` and `fingerprint` against the
observed active public manifest before any impact or admission, refusing
mismatches with an explicit repair diagnostic (never absent/latest); D1-B —
`_s3_binding_manifest_store`'s legacy probe must route `ArtifactAccessDenied`
into the existing mapped source-inspection refusal for inspect/fetch/link
and `source resolve --json`, with no traceback and no new error framework.
Budget: repro cases written before the production fix (red observed at the
unfixed `c393114e` baseline, no shared stash/ref manipulation), one small
post-fix selected group (the two negative cases plus the direct positive
legacy adoption/inspection controls), scoped Ruff/format/diff once, then one
parent-only Sol/high `c393114e…fixed` delta review. No design/spec/ADR/
AGENTS changes, no D2–D5 reopening, no broader suite or third round.

**Owner-authorized D1–D5 delta correction, 2026-10-17 (r8):** after the
independent fix-delta review returned findings D1–D5 unresolved on `8b034283`,
the owner explicitly approved one additional bounded repair of exactly those
five findings in a fresh isolated candidate (`g2-fix-a2`, base
`8b034283…`). Worker is Pi `zai/glm-5.3`/high; review is one parent-only
Sol/high delta over `8b034283…fixed` — no worker-dispatched review. Scope:
D1 compatibility reads of exact legacy private S3 binding manifests held in
the configured `LUMIO_SOURCE_STORE` for legacy S3 inspect/resolve and
first-native-adoption comparison (new native metadata stays target-scoped;
no registry-latest, migration, or fallback around missing/corrupt new native
metadata); D2 outgoing reconciliation proving admission/activation truth
without requiring outgoing index health, with the legacy exemption checked
before new inventory validation while target completeness/retention and the
R1 stale-retry closure stay strict; D3 local recovery verifying the actual
`published_version_path(destination, version)` without rewriting immutable
bytes; D4 carrying the explicitly selected `--source-registry` into the
replayable authoring inspect command with normal quoting; D5 adapting only
the `test_s3_publish_uses_one_captured_candidate` fixture to emit a real
representative index object (production empty-inventory gate unchanged).
Budget: one failing-first batch for the new repros where practical, one
coherent selected post-fix check group, scoped Ruff/format/diff, reuse of
still-applicable prior greens; no spec/ADR/AGENTS changes, broader suite,
live services, merge/push, or third correction round. G2 remains unaccepted
until the parent accepts it.

**G2 caller/test-surface amendment, 2026-10-16 (parent-authorized):** G2 routes
`publish-s3`, `rollback-s3`, and public SDK publication/rollback through the same
exact Git preview/confirm/expected-current gate or fails closed; no unadmitted
working-tree bypass is retained. G2 ownership includes directly affected cases
in `packages/lumio-wiki/tests/test_cli_s3.py`, `test_cli_setup_s3.py`,
`test_cli_open_actions.py`, `test_cli_remote_lance_s3_compat.py`, and
`test_cli_status.py`, plus only the S3-compatible portion of
`tests/test_onboarding_journey.py` and minimal steps 8/11 fixture changes in
`examples/onboarding-journey/smoke-journey.sh`. Preserve old-format read
compatibility. Run the assigned six-file serial test command plus directly
changed non-live CLI cases; migrate but do not run live/service-backed journey
proof (G5). `bash -n` is allowed for the changed shell script. No broad
onboarding/doc migration or full-suite expansion is authorized.

**Owner-authorized G2 bounded follow-up, 2026-10-16:** after the worker's
fix-first handback, the owner authorized one separate, bounded diagnosis/repair
for only
`packages/lumio-wiki/tests/test_artifact_store.py::test_rollback_cli_blocked_after_artifact_deletion`.
The observed symptom is successor-B preview returning 0 and confirmation
returning 1 with sanitized JSON `cli_error`; its underlying exception is
unknown. Diagnose from this existing node, preserving JSON/error privacy and the
legitimate A→B publication plus historical-A rollback/deletion refusal contract.
Reuse still-applicable green evidence; one focused investigation execution with
temporary, non-production instrumentation is permitted only if necessary, then
one targeted post-fix node run and scoped Ruff/format/diff checks for changed
files. No broader suite, third correction, new tests, weakened assertion,
behavior/policy change, or run-state edit is authorized. Stop and ask if the
cause is ambiguous or the same defect survives. G2 remains unaccepted; commit
and freeze its reserved result ref only if the authorized fix passes the
specified delta checks.

**Integration/continuation authorization, 2026-10-16:** after the four-defect
follow-up passed parent verification and independent scoped review at
`a8ef28cc2a7a2bdc4725f7e91ce10e279b985e8d`, the owner instructed:
**“Integriere G1. Commit. Push. clean up. Dann Mach weiter mit der
Implementierung.”** This authorizes integration/push of that accepted G1 stage
and cleanup of its owned worktrees, followed by isolated G2 implementation with
the selected Pi/GPT-6 Luna `xhigh` worker. It does not claim completed issue #1,
authorize a package release or real-KB operation, or grant integration/push of
later stages. Private app and #2/#76 remain excluded.

**Follow-up authorization, 2026-10-16:** after G1's single correction and delta
recheck ended with four reproduced blockers at `410e7ac`, the parent handed the
result back rather than starting another automatic round. The owner now replied
**“Ok. Starte die Umsetzung”** to the explicit proposal for an isolated,
four-defect G1 follow-up on that commit using Pi/GPT-6 Luna `xhigh`, with focused
regressions. This authorizes the G1-R unit below, not integration, push, a reset
of the completed review budget, or reopening settled findings. The prior
documentation-only integration at `e55e46d` is not runtime acceptance.

**Scope amendment:** owner, 2026-10-16: “Wir wollen die lumio App vorerst nicht
weiter berücksichtigen. Fokussiere dich nur auf lumio-Wiki und wenn nötig,
lumio-lancedb”. C0/private AC6 is deferred, not accepted; it is no longer an
implementation prerequisite. The other public tasks retain their approved
behavior. No further private edits/tests, CI transport work or private review.

**Goal:** deliver the public Git-only authoring replacement from
[specification 0008 r2](../specs/2026-10-15-0008-git-native-knowledge-authoring.md)
(active AC1–AC5 and AC7). [ADR-0029](../adr/0029-git-native-knowledge-authoring.md)
owns rationale. This plan owns execution order, file ownership and checks.

**Prior approvals:** written public design r1 approved with “Ja Freigabe”
(2026-10-15; presented at `81ed0f7`, recorded in `6107567`), followed by
“Ja. Freigabe” for supervised plan-r1 execution (presented at `299f1f1`,
recorded in `aadfe254`). The earlier public-only scope instruction removes C0
and continues public execution; it does not reopen or change the public
manifest/admission design. Runtime base remains public
`c3b68db233f8aa98a39380a0099ff2b800a70c55`.

**Authority:** the G1-only integration/push/cleanup exception is recorded above.
Subsequent stages prepare isolated public candidates and proportional reviews
under `orchestrate-implementation`; their target integration/push still need
separate authorization. No PR/issue mutation, real KB migration/publication,
deployment or release is authorized.
Checks use disposable fixtures, never the configured shared KB or production
stores. No new tracker tickets or duplicate GitHub task definitions.

## Constraints, capture, and operating context

- Python >=3.14; existing uv/msgspec/msgpack core, Git executable for authoring,
  optional obstore/LanceDB/documents/LLM/MCP as today. No new mandatory database,
  model, GitHub service, Git library, Ariadne, DuckDB, or SQLGlot dependency.
- Capture checkpoint: glossary terms are in `CONTEXT.md`; accepted ADR-0029 and
  linked scoped amendments reconcile the old proposal-first contract; approved
  spec sections 1–9 own retained public behavior/non-goals/acceptance. The
  owner-scoped private deferral is captured in spec r2/ADR-0029. No material
  public #1 design decision is open. #2/#76 Context Provider, ontology mappings, and Ariadne's Policy-fallback
  amendment remain explicitly excluded and unapproved.
- Public callers are CLI, packaged skill/PROTOCOL/setup, ingest/capture/import/
  maintenance helpers, snapshots and optional adapters. The already inspected
  private app has known incompatible imports, but further work on it is deferred
  and is not required for this isolated candidate. See the
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
- One sequential public writer; no private writer is authorized. Never run
  concurrent writers on a checkout. This plan intentionally does not parallelize
  shared `cli.py`, `__init__.py`, registry, publication, or producer surfaces.
  Use committed, frozen result refs and accepted upstream candidate commits.

### Risk and review boundaries

Immutable activation, exact private source bindings, migrations, and public
API retirement are high-risk units. Independently review each such
contract before a downstream task consumes it. Parent inspection applies to all
results. Candidate review covers integration/unreviewed deltas only, not settled
findings. One parent-authorized fix pass and one delta-only recheck per finding;
then hand back unresolved blockers. Every fresh reviewer receives the complete
installed reviewer contract inline, exact source criteria, written conventions,
and real callers. Children never run OptMem or write shared memory.

Touched public boundaries: external import/source bytes and captured Git content
(path confinement/private-source exclusion), existing visibility-scoped export/
retrieval, and local/S3 publication pointers (concurrent legitimate publishers
and failed I/O). User-owned local files are not hostile by default; written
privacy, no-hook-execution and snapshot guarantees still bind. Review actual paths;
do not invent stolen-secret, malicious-admin, or generic-hardening scenarios.

## Order and requirement coverage

`G1 → owner-returned G1-R → G2 → G3 → G4 → G5`.
G1-R is the explicit owner-directed disposition of the four residual G1 defects,
not an automatic continuation/reset of the exhausted correction loop. G2 stays
blocked until the combined G1 result is accepted.
G1–G5 are sequential public candidate descendants. C0 is preserved as incomplete
history only: no private continuation, cleanup, acceptance, or integration.
Deliver a reviewed public candidate, paused before target integration.

| Unit | Source / principal acceptance | Consumed → produced interface |
| --- | --- | --- |
| G1 | §2–4, local §5; AC1, AC2, AC3, AC4, AC7 | v1 Source Reference Manifest + existing page/registry contracts → complete local author/commit/review/admit/publish/read path |
| G1-R | §2/3.3/4.2/5; AC1–AC4, AC7 as affected | frozen `410e7ac` + four owner-returned findings → repaired author preservation, plain reading, retry history and eligible-support disclosure |
| G2 | §3.3/5; AC3, AC4, AC7 | reviewed G1 captured revision/receipt → S3/LanceDB activation, exact source inspection and historical rollback |
| G3 | §1/6/7 producer table; AC1, AC4, AC7 | reviewed authoring/publication seams → all retained ingest/import/maintenance/entity-mutation workflows |
| G4 | §7; AC5 plus no-proposal parts of AC1, AC4 | all migrated callers + original legacy format → explicit export + removal of live proposal lifecycle |
| G5 | §7/9; AC1–AC5, AC7 | frozen G1–G4 results → installed public-package evidence, current guidance, reviewed supervised delivery |

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

## G1 — Complete standalone local Git authoring and publication

**Owner/prerequisite:** public Pi writer from the scope-reconciled approved
source commit. No private dependency remains. Verify clean runtime base and
run/reuse the smallest exact-tree public baseline: the unchanged public
managed-ingest/S3 suites passed 60 tests during earlier preparation; recheck
relevance and isolated environment before mutation. Reuse captured-content
loading, checked paths, registry history and validation, not a new framework.

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

## G1-R — Owner-directed follow-up of four residual G1 defects

**Authority/base:** the explicit owner authorization recorded above; isolated
candidate from `410e7ac6da6eac886a04814b8813bb07e11690a9`. Preserve the original
G1 and correction refs, reports and worktrees. Worker is Pi
`openai-codex/gpt-6-luna` / `xhigh`; the selected Paseo host and shared-root
allocator remain unchanged. No new vocabulary, architectural choice or behavior
is introduced: specification 0008 r2/ADR-0029 still own the contract.

**Owned surface:** `packages/lumio-wiki/src/lumio_wiki/{git_authoring,cli}.py`,
`packages/lumio-wiki/tests/test_git_authoring.py` and only directly affected
existing reader/CLI tests. Do not edit source-authority documents, unrelated
helpers, packages, dependency files, private application or shared KB.

- **R1 / spec §2:** an existing ignored or status-hidden untracked destination
  remains byte-identical when ingest would overwrite it. Refuse before private
  registration/writes; still permit genuinely absent new destinations and the
  intended untracked Source Reference Manifest bootstrap.
- **R2 / spec §5, AC7:** valid plain KB content at `versions/v1/overview.md`
  remains readable/valid without being classified as a publication by directory
  names alone. Real publication roots still resolve one active Snapshot and
  fail closed on missing/corrupt pointers or referenced versions.
- **R3 / spec §4.2/5:** inject failure of B's receipt bookkeeping after B's
  pointer activation; admit C, explicitly roll back to A, then retry B's old
  authorization. A remains active. An ambiguous activation flag is not proof of
  never having activated; reconcile actual success before later transitions or
  refuse ambiguous replay. Keep exact confirmation, expected-current, immutable
  historical evidence, retention and completeness gates; no stronger power-loss
  or hostile-editor guarantees, new proposal state or cross-backend transaction.
- **R4 / spec §3.3:** retirement impact counts alternative support only when
  declared on that Entity, active, and resolved to its exact registered version.
  An unregistered/undeclared alternative must not produce `still-supported`;
  preserve collected blocking diagnostics and valid-alternative behavior.

**Validation / high risk / `new-test`:** one independently specified regression
per distinct failure, parameterizing R1's ignored/status-hidden variants where
useful. Observe the intended red on the frozen base before repair, then green.
Reuse the existing v2 fixtures and actual Git/CLI/SDK seams; inject the real
post-pointer I/O failure for R3 rather than manufacturing an activation flag.
Run the existing G1 four-file focused command and affected checks serially;
any full suite uses exactly `-n 4`. No dependencies, broad cleanup or live service.

**Handoff:** one bounded implementation pass and one scoped acceptance check of
these four changes/affected behavior, without reopening the other settled G1
findings. The previous review/correction history remains intact. If a blocker
survives or a material decision is needed, stop and return to the owner again;
no further automatic repair/review cycle. Frozen committed result, parent
verification and independent high-risk acceptance are required before G2.

**Accepted G1 checkpoint:** the prior thirteen resolved findings plus G1-R's
four scoped repairs establish the local G1 contract at `a8ef28c`. Verified
239 focused tests, the four original parent failure probes plus a failed-receipt-
reconciliation safety case, and the independent scoped pass are retained in
orchestration evidence. This is local G1 acceptance, not G2–G5 certification.

## G2 — Complete optional backends and exact historical inspection

**Owner/prerequisite:** public writer from the verified integrated G1 commit,
pinned in run state after the authorized merge. Worker remains Pi
`openai-codex/gpt-6-luna` / `xhigh`; reviewer defaults stay unchanged. Reuse
still-applicable G1 evidence; do not repeat green checks for ceremony.

**Owned files:** `packages/lumio-wiki/src/lumio_wiki/{git_authoring,publish,
s3_publish,s3_location,location,artifact_store,source_inspection,source_resolution,
cli,__init__}.py` (shared admission/capture reuse and public exports included);
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

### G2 correction and local LanceDB completion (r7)

**Authority and boundary:** the owner selected the complete correction of the
independent G2 R1–R8 findings together with the already-approved local
LanceDB publication requirement. This is one isolated corrected candidate,
one targeted validation selection, and one delta-only independent review; G2
remains unaccepted until the parent accepts it. Specification 0008 r2 and
ADR-0029 remain the behavioral authority. This amendment changes neither
product behavior nor any specification, ADR, AGENTS guidance, private app,
shared KB, release, or integration scope.

**Required corrections:**

- **R1:** before any new S3 pointer transition, reconcile the verified outgoing
  activation/admission truth; fail closed if reconciliation cannot be persisted.
  Preserve the accepted no-stale-replay history after a post-CAS receipt failure
  and later explicit rollback. Reuse the parent's existing red MemoryStore
  probe; do not rerun it as a baseline.
- **R2:** when retention is required, verify exact captured coverage and raw
  artifact availability for every referenced non-synthetic page/source pair
  before CAS, including after an optional costly builder. Preserve public-only
  provenance when retention is disabled. Adapt the existing unregistered-source
  test to the new public owner path, not the retired private primitive.
- **R3:** the immutable manifest/completeness and health gate must cover actual
  requested LanceDB tables and sidecars as well as graph/completion metadata.
  Missing/corrupt requested index content blocks retry or rollback activation;
  do not rebuild, substitute a newer index, or treat read fallback as complete.
- **R4–R5:** use the explicitly selected Git source registry for authoring
  inspect/fetch/link/resolve. Preserve selected Entity identity through exact
  binding lookup and replayable commands; Source-ID-only ambiguity still refuses.
- **R6:** use one target-scoped private metadata selection across preview,
  confirm, rollback and CLI inspection, independent of optional raw artifact
  storage. Without raw retention, disclose the exact sealed binding and raw
  unavailability without requiring or inventing bytes.
- **R7:** compare each historical page/source binding to that Entity in the
  selected historical snapshot. Preserve legacy title bindings; unknown or
  ambiguous identity blocks repair rather than guessing or allowing another
  page's matching hash to mask a replacement.
- **R8:** an explicit local `--published-version` reads that exact historical
  private binding, keeping legacy Published Version labels distinct from Git
  Authoring Revisions. Do not force legacy versions through Git or use latest.
- **Local LanceDB:** complete capture/build/health, fail-closed activation,
  immutable manifest/receipt, version-pinned reading, same-Snapshot fallback,
  and explicit local rollback with the existing optional adapter. Keep the core
  model-free and dependency direction inward; add no adapter hierarchy or
  storage backend.

**Owned surface:** retain the G2 production files above; touch the existing
`lumio-lancedb` `publish.py`, `location.py`, `index.py`, `graph.py`, and
`__init__.py` only where version-bound local/remote composition requires it.
For tests, retain the existing G2 surface, add `test_git_authoring.py` and
only directly affected existing local adapter tests. The owner additionally
authorizes `packages/lumio-wiki/tests/test_cli.py` solely for directly affected
source inspect/fetch/link/resolve and selected historical/pinned-source cases
for R4–R8, with minimal inspection-specific fixture setup. Do not rewrite a
shared fixture globally for unrelated managed-ingest, proposal, lifecycle,
retire/register, or candidate tests; do not run the whole `test_cli.py`.
Preserve its explicit local legacy `--published-version` behavior as a legacy
binding proof, not Git admission.

**Validation / one bounded selected check:** reuse still-applicable evidence
from `logs/g2-focused-validation-first.log` (217 passing cases),
`logs/g2-delta-recheck.log` (6 passing cases), and
`logs/g2-rootcause-node.log` (1 passing case) separately because their frozen
source tree matches this base. Do not rerun those greens or combine them into a
suite claim. Use the existing R1 red probe/log only as prior failure evidence.
Select one focused post-fix execution over the actually changed named scenarios:
R1 S3 history regression; adapted R2 public-owner retention case; R3 actual
requested-index constituent loss; R4–R8 only the affected CLI inspection and
historical-binding cases; and one local authoring/LanceDB publication-read-
rollback journey. Add a case only for a genuinely uncovered reachable behavior;
expected values come from captured Git A/B, independently computed canonical
fingerprints and source hashes, exact Entity bindings, fixture bytes, and the
old expected pointer. Preserve numerical, permission, CAS, and retention
assertions; no generic-error proof or self-confirming mocks. After the one
coherent selected execution, run scoped Ruff, format, and diff checks for
changed files. A failure authorizes only investigating that named failure.
Reuse evidence only while code, tests, inputs, and locked Python 3.14.8
environment still match; no broad suite or whole CLI module.

**Handoff:** one collective correction pass and one independent review of the
`00cbe24..fixed` delta only. No G3 consumption before acceptance. A surviving
same finding after the authorized pass/recheck goes to the owner; no third
round, live S3/onboarding, full suite, wheel/MCP, services, endpoint-path probe,
LSP/type-clean claim, private app, shared KB, merge, push, PR, or release.

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

**Owner/prerequisite:** public writer from accepted G3; original legacy
source formats available. Only synthetic legacy stores are exercised.

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
- [ ] Search public production/import/export/entry-point surfaces and scripts.
  Do not continue private-repo inspection or infer its compatibility. Its known
  imports remain an explicit later release/integration issue. Public old-format
  names may remain only in migration reader/fixtures/history. No renamed queue, dual persistent write mode, custom
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

**Owner/prerequisite:** public writer/parent candidate assembly from G4.
No private work or target integration.

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
  not the earlier baseline wheels or workspace imports. Reuse/update existing wheel
  isolation/verifier tests rather than building a second harness.
- [ ] Run required CI checks below on exact candidate trees. Refresh canonical
  onboarding and existing live S3-compatible checks against an isolated test
  service using the repository's pinned CI image/configuration. No production
  credentials/endpoints, no modification/restart of running services, no
  implicit runtime/architecture installation. Missing capability blocks the
  corresponding certification claim for owner disposition, not a silent skip.
- [ ] Parent verifies exact public commits, built-artifact identity, active
  acceptance coverage and terminal child ownership. One final independent candidate review
  covers unreviewed guidance/packaging and integration effects only. Preserve
  refs/worktrees/artifacts and deliver `merge-worktree` handoffs, paused before
  the public target branch. Do not close #1 or start dependent #2 coding implicitly.

**Validation unit D / `existing-check`** for installed/public-read contracts;
**`no-new-test`** for docs/metadata. Adapt the existing isolation journey to the
new approved flow and Git-free read case; these establish real installation
and command behavior, not a coverage target. Full candidate gates are the
public repository's existing CI: `uv lock --check`, locked sync, locked Ruff and
`uv run --locked pytest -q -n 4` in the public candidate (serial focused
commands above remain development defaults). No `-n auto`.

Live public checks use `tests/test_onboarding_journey.py` and the existing
`*_s3_compat.py` suites under both packages; record actual execution and any
unavailable cross-role policy provisioning. Never call MemoryStore results
live S3 evidence. No private final tests or app-CI provisioning are required
or authorized. Candidate base/head, public artifact identity and actual command
outputs belong in the existing orchestrator/host run state,
not a new assurance ledger.

**Done:** active AC1–AC5 and AC7 have concrete same-surface evidence; the public
candidate is committed, reviewed and preserved. AC6/private compatibility is
explicitly deferred, never marked passed; skipped/unavailable public gates are
explicit. Choose `accept / fix / hand back / ask` against the approved scope.
Separate authorization is still required for integration, real data migration,
publication, issue updates, deployment, push and release.

## Handoff and remaining gates

The plan/execution approval is recorded above. Writing and approving this plan
did not itself run a worker, feature test, wheel build, test service, dependency
installation, real legacy export, or publication. Installed role/runtime
capability, public baseline checks, built-artifact identity and live test-service
availability remain prerequisites to verify during
execution, not invented facts. Changes
to approved behavior/interfaces return to shaping; infrastructure or baseline
failures go to the owner without switching hosts or weakening checks.

Planning-contract v1; installed skill SHA-256
`5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`;
upstream installed catalog commit unknown. The selected `orchestrate-implementation`
skill owns dispatch, review, frozen results and patch-only recovery after approval.
