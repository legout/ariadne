# Implementation plan 0008: Git-native Knowledge Authoring

**Revision/status:** 23 — worker implementation/proofs prepared; parent candidate review pending.
Final real base verifier passed after the authorized optional-installer-metadata
correction: 46 wiki package members match candidate ZIP/source/installed bytes,
with actual archive SHA and isolated import identity; installed native
commit/review/confirm/query and Git-free validation/read/query passed. Installed
MCP CI smoke passed (valid EOF exit 0, invalid bounded exit 2, no traceback,
fixture search), with the same candidate member identity. The existing adapter
wheel CI smoke passed with both candidate wheels: 46 wiki + 5 adapter members
match, no automatic inward adapter import or forbidden app-only dependencies.
Both wheels remain version 0.1.2; no dependency/lock/ABI changes.

Evidence is explicitly composed, never relabelled: original workspace Ruff
exit 1 plus authorized affected-file passes; original full suite 1619 passed /
17 failed / 10 skipped, then 13 passed / 4 failed, then 4 passed; original
live group 37 passed / 3 failed / 1 skipped, then 2 passed / 1 failed, then
1 passed. The initial base verifier exit 1 is retained alongside its resumed
exit 0. No group/full green reruns. Read-only malformed-registry recovery is
the only Python production delta (+2 lines); all other native contracts remain
accepted upstream evidence. Automatic type/import/heuristic diagnostics remain
inconclusive or rejected against actual verifier semantics, not a type-clean
claim. Cross-role provisioning/authorization and private AC6 remain unverified/
deferred. The owned service and volume are retained, stopped as recorded below.

The worker now commits/preserves the isolated candidate and reports exact
commit/tree/ref/artifact identities in the existing RUN handoff. Parent alone
owns independent final G5/integration-effects review and acceptance; issue #1,
target integration, publication and release are NOT declared complete.

**Historical r22 checkpoint:** parent-authorized installed identity-oracle correction.
The final affected live node passed (1 pass, exit 0): live evidence is composed
37 + 2 + 1, with cross-role policy unverified. Both final candidate wheels were
built once and independently hash-matched by the parent. The first real base
verifier stopped BEFORE member comparison/SDK author/query because uv 0.11.8
records the exact local wheel URL with optional `archive_info: {}`. Parent
rejected requiring its absent SHA-256 field as an unwritten installer oracle.
Only the verifier helper changes: require the exact resolved archive URI and
no directory/editable install; validate provided SHA-256 metadata, retaining
computed archive SHA, every package ZIP/source/installed-byte match, METADATA,
module/sys.prefix and forbidden-base-dependency checks. Scoped script Ruff/diff
then ONE resumed real verifier in the unchanged base venv with unchanged
retained wheels; no rebuild/reinstall, root-test or broad/live rerun. Continue
only existing installed CI MCP/adapter seams after pass. Stop on any failure.
The owned container is stopped and retained: stop command exit 0, container
exit 137 after the ten-second stop timeout, not a graceful-shutdown claim;
its volume and redacted runtime logs are retained. No production impact.
All previous authority, clean result freeze and parent-owned review bounds bind.

**Historical r21 checkpoint:** parent-authorized single live keyword-oracle delta.
The exact live-three group ran once: onboarding and URL artifact nodes passed;
agent journey failed only on G5's unwritten literal `conflict` requirement after
the stale expected-current preview correctly exited 1. Parent read the full
log and remaining node branches. Replace ONLY that assertion with fixture-known
full v1/v2 identities, bounded expected/current mismatch disclosure and an actual
unchanged-v2 pointer read. Keep all later orphan/rollback/history/fallback
oracles. Scoped Ruff/diff only that changed test, then ONE serial agent node
on the same owned service with fresh prefix/short base/sanitized live env.
Reuse 37 + 2 unaffected live passes; no fresh whole-live green or new group/full
budget. On pass resume unused final installed CI proof and committed handoff;
any failure stops for the owner. No production changes or new service actions.

**Historical r20 checkpoint:** parent-authorized three-node live co-switch.
The r19 four-node delta passed (4 passes, exit 0). The one authorized live
eight-file group then ran against the pinned native-arm64 owned service:
37 passed, 3 failed, 1 cross-role skip, exit 1 (`RUN/logs/g5-live-pytest-a1.log`).
Parent read the complete failures/image identity and verified the same owned
container `619876a318c707221b597a159cbccae703a093a47538affd1a371062e86d593f`
running/healthy, ownership labels and loopback `127.0.0.1:32924` binding.
No new pull/restart/recreate or role provisioning.

Only approved live corrections: onboarding smoke/quickstart distinguish
explicitly authorized private exact-version metadata from optional retained raw
bytes (inspect exact fixture version/Entity/Source/hash and not-retained;
fetch must fail and create no output); the URL artifact node gets one explicit
valid Entity ID while preserving its distinct Source ID; the native agent
ingest oracle checks fixture-derived exact manifest bindings rather than old
console padding. No production change or validation/authorization relaxation.
Scoped formatting/Ruff only the two changed Python tests, changed-shell syntax
and diff check, then ONE serial group of exactly those three failed live nodes
on the SAME service with sanitized live environment, fresh short temp base and
unique object prefixes. Reuse 37 unchanged passes; the prior live command
remains exit 1 and cross-role authorization remains unverified. On pass resume
only unused final candidate-wheel/installed CI/MCP proof. Stop on any failure;
all previous report/freeze/ownership and integration/publication bounds remain.

**Historical r19 checkpoint:** parent-authorized four-node fixture/oracle delta.
The r18 exact-17 serial group ran once: 13 passed, 4 failed, exit 1
(`RUN/logs/g5-integration17-pytest-a1.log`). Parent read its full output and
actual CSV/LLM artifacts. Only three test files change now: isolate each
`_PublishedS3Kb` fixture's XDG metadata state before admission while preserving
within-fixture history; remove only the managed-CSV console converter assertion
(the real conversion/provenance assertion remains); move the fake-provider
title assertion from stdout to persisted page metadata using the input fixture.
No production changes. Scoped format/Ruff/diff only those three files, then
ONE serial group of the four failed selectors on a fresh short temporary base.
Reuse the 13 passes and prior 1619 unchanged passes; neither the 17-group nor
the full-suite command becomes a fresh green. On pass resume only unused
pinned-image/service/live/installed budgets; any failure stops for the owner.
Old receipts, temporary directories and all prior artifacts remain preserved.

**Historical r18 checkpoint:** parent-authorized closure of 17 named G5 integration failures.
The sole authorized four-worker suite ran once: 17 failed, 1619 passed,
10 skipped, exit 1 (`RUN/logs/g5-full-pytest-a1.log`, complete 799-line output).
No fresh full-suite green or new full-suite budget is implied. Parent read
that evidence, actual callers/fixtures and Git history before this grant.

Restore only the bounded, secret-free malformed-registry constructor-error
branch in `cli.py::_source_coverage_registry` (G4 c245 regression); preserve
OSError/no-store handling, no writes and existing lint/dream callers. Exact
additional test repairs: `test_cli_open_actions.py`'s fake resolver gets its
known store URI; `test_s3_publish.py::_fake_builder` gets real constant index
bytes and independently hashed/sized inventory; the one MCP graph node uses
an explicitly private transport kernel; the setup node no longer expects
proposal-store creation; two optional-wheel nodes distinguish derived index
state from forbidden proposal/private writes; the real AnyDoc CSV node keeps
real conversion and positive valid native managed ingest of the original CSV;
the duplicate-guide node removes only the retired staging phrase. Preserve all
retained action/version/replay/CAS/index/health/tamper/citation/privacy oracles.
No socket-test edits: use a collision-checked fresh SHORT temporary base to
avoid AF_UNIX path limits. No other production, registry, schema or ABI change.

Before the post-check, scoped formatting/Ruff only actually changed Python
files plus diff check. Then ONE serial group of EXACTLY the 17 original failed
selectors named in the parent grant, using short disposable TMPDIR/--basetemp
and the original HOME/XDG/AWS/provider isolation. Reuse 1619 passes/10 skips
only on unchanged relevant surfaces. Any affected additional check needs a
named hypothesis and parent grant; any failure stops for disposition, not
automatic repair/retry. After the 17 pass, resume only the unused pinned-image,
one owned service, live group and final installed-wheel CI budgets. Final
candidate wheels must include the new CLI bytes; old wheel tests are not final
artifact identity. No review-budget reset or reopening settled G4 findings.

Lint history remains composite: initial workspace Ruff exit 1 (I001); current
reordered imports were observed before repair with provenance UNVERIFIED;
first scoped check exit 1 (missing E402 annotation); the parent-authorized
one-line annotation restoration then passed the second scoped check. Do not
claim the original workspace command passed. All previous scope, ownership,
report/ref preservation and separate integration/publication gates still bind.

**Historical r17 checkpoint:** G5 public candidate execution authorized.
G4 accepted at `6c333614fbcc1ea7a8d87142a3325f79d22f71c2`, tree
`7c6b9f52eb26c92ed1debaefce2b7fb2fdd8d191`: initial M plus ONE direct
F1/F2 delta PASS; settled G1–G4 findings are not reopened. The owner explicitly
selected “G5 mit Sol/high (Recommended)”, for G5 only, and the parent accepted
the fresh read-only preflight and granted the bounded execution below.

Sole writer: Paseo/Pi `3bdf8ff1-770d-4109-89b1-33fa31216b7b`, workspace
`wks_991a9016a880b9bc`, native Pi `01a14bb7-a781-76b8-aa45-59d861f8df8b`,
verified `openai-codex/gpt-6.1-sol` / high. Physical registered checkout
`/home/volker/.local/state/worktrees/0ast0lnx/lumio-git-g5-worker-a1`, branch
`orchestrator/lumio-git-20261015/g5-worker-a1`, common Git
`/home/volker/coding/lumio-wiki/.git`; clean accepted-6c startup. Pinned base
`refs/heads/orchestrator/lumio-git-20261015/base/g5-a1`; sole future result
`refs/heads/orchestrator/lumio-git-20261015/result/g5/a1` was absent.

Own Python `/home/volker/.local/bin/python3.14` 3.14.8 and uv 0.11.8;
`.venv` absent at preflight. Local Docker 27.4.1 uses only
`unix:///var/run/docker.sock`, native Linux arm64. Exact CI image
`chrislusf/seaweedfs:4.45@sha256:fc9f76fa993ad69966ffeb2f65d0318fcae39c6f8e20cf68ef7b3a5cb97769e5`
is not cached; read-only registry metadata confirms native arm64. ONE pinned
acquisition and ONE uniquely named/labelled owned container are authorized,
using CI test credentials/bucket, loopback-only ephemeral port and bounded CI
health wait. No cached-4.48 fallback, emulation, restart/recreate, existing
service changes or removal. Stop the owned container after preserving logs;
retain it and its artifacts. Cross-role provisioning is not supplied: report
that case unverified, never invent roles.

Owned files remain the G5 list below, plus exactly
`packages/lumio-wiki/tests/test_s3_agent_journey_s3_compat.py` and
`packages/lumio-lancedb/tests/test_publication_s3_compat.py` for actual retired
consumer co-switches. Preserve index/health failure, pointer CAS, cleanup,
rollback and retrieval oracles; private transport proofs are not native
admission proofs. Co-switch the existing isolated research journey too.
Refresh root AGENTS guidance without invoking setup against the shared KB.
Leave already-correct guidance and `skill.py` bundle hashing unchanged unless
an actual G5 job requires a change. No dependency/lock/pyproject/schema/ABI or
unrelated version changes, blanket rewrites or new framework.

All commands use disposable HOME/XDG/temp/cache and empty AWS configuration,
without inherited Lumio/provider/cloud profile/container credentials or
PYTHONPATH. Tests use only disposable KBs/private registries/artifact stores.
Live settings name only the new loopback service/bucket/test credentials in
both AWS and LUMIO_S3 forms. No configured shared KB, private app, real legacy
store or production/provider endpoint is authorized.

Exact budget/order: ONE `uv lock --check`, own `uv sync --locked` with explicit
Python and declared workspace/dev dependencies; minimal implementation and
scoped formatting before meaningful checks, changed-shell syntax/diff checks;
ONE `uv run --locked ruff check .` (no broad fix); ONE
`uv run --locked pytest -q -n 4` with live settings absent; ONE serial
`uv run --locked pytest -q tests/test_onboarding_journey.py packages/lumio-wiki/tests/*s3_compat.py packages/lumio-lancedb/tests/*s3_compat.py`
with a guarded explicit selection and isolated live settings; then existing
CI installed-wheel proof ONCE from newly built retained candidate wiki/adapter
wheels. Bind source/member hashes, wheel SHA-256 and installed bytes/import
identity. The real existing verifier owns installed author/admit/query plus
Git-free reads; existing installed MCP/adapter CI smokes run once where the
full suite did not exercise that installed artifact. Do not duplicate green
installed/live journeys, run baseline suites, or infer live proof from memory
stores. Expectations come from fixture bytes/IDs/hashes, real Git commits,
citations, exact expected-current and public/private prefix contracts.

Any mandatory failure: preserve true exit/raw output, investigate only the
named cause, then STOP for parent disposition. No automatic SDK fixes,
assertion weakening, expanded tests or full-suite reruns. Prior G4 M167+1,
co-switch19+1 and correction4 passes are reused only where applicable, not
installed/live/type/CI certification. Known Pyright findings remain
inconclusive; no LSP/config/runtime experiments.

Commit intended G5 files, verify clean accepted-base ancestry/no merges and
freeze ONLY the unique result ref above. Read back
`RUN/g5-worker-report.md` and unique `RUN/logs/g5-*` evidence with actual
exits, wheel/image/runtime identities and limitations, then relinquish writes.
RUN/run.json, findings, budget, independent final candidate review and
acceptance remain parent-owned. No delegation, memory/wiki/global skill work,
private AC6/#2, real migration, target integration, push/PR/issue updates,
publication/release/deploy or cleanup. Planning-contract v1; catalog revision
unknown.

**Historical r16 status:** G4 initial-M F1/F2 collective correction authorized
in the fresh isolated checkout below; acceptance and the one direct delta
review remain parent-owned. G3 accepted as an isolated component at
`fb2bcf36…` (tree `da4f7351…`, result `result/g3/sol-a1`, closed review
chain ending in `RUN/g3-sol-reviewer-report.md` PASS; the r13 "reviewed
but NOT accepted" state is superseded by the parent's isolated G3
acceptance). G4 execution authorized. Behavioral specification
revision 3 (reactivation clarification only).

**Parent-authorized G4 initial-M correction, 2026-10-17 (r16):** the parent
read the complete `RUN/g4-reviewer-report.md`, accepted P2 F1/F2 as small
in-scope defects, and granted this ONE collective correction under the
existing G4 execution/quota-takeover authority, followed by ONE parent-owned
direct delta review. This is not a new feature, budget, review round or G5.
Sole writer: Paseo/Pi `db5c651f-f0e4-494e-9642-50eede7acdda`, workspace
`wks_068e95a9b25d920f`, native Pi `01a14b94-a35a-7208-b622-a1c4d56d8f76`;
startup/environment/host agree on `openai-codex/gpt-6.1-sol` / high.
Physical registered checkout:
`/home/volker/.local/state/worktrees/0ast0lnx/lumio-git-g4-fix-a1`, branch
`orchestrator/lumio-git-20261015/g4-fix-a1`, common Git
`/home/volker/coding/lumio-wiki/.git`. Clean base
`refs/heads/orchestrator/lumio-git-20261015/base/g4-fix-a1` =
`c2456a063920a67aaf32f81e30d53dc0774898f5`, tree
`47e033b909399e1f97b24e633afc5f8399ef8a88`; sole future result
`refs/heads/orchestrator/lumio-git-20261015/result/g4/fix-a1` was absent.
Old worktree dirt has unverified origin; do not consume, clean or mutate it.
Frozen prior refs/reports/recovery artifacts remain immutable.

Owned source changes: ONLY this plan, `legacy_proposals.py`, and
`test_legacy_proposal_export.py`. F1 uses ordinary non-forced staging, then
refuses any effective candidate Compiled Page, present Control File or manifest
missing from the index before commit/branch/receipt; absent optional controls
remain supported. No force-add or private/unrelated-file staging. F2 blocks
retired-baseline ordinary managed provenance in shared `_export_input` for
preview and confirmation unless matching explicit reactivation passes the
existing exact transition/history/provenance checks. No native/history/registry
semantics, public interface, schema, module, dependency or G3 change.

Exact validation: one serial pre-fix red group containing new
`test_ignored_new_page_refuses_without_data_loss` and
`test_ordinary_record_cannot_reactivate_retired_baseline`; independent original
wire/preconditions/identity/raw hashes/Entity IDs and real Git refs prove the
named failures, not parser/import errors. ONE serial post-fix group contains
those two plus existing `test_export_journey` and
`test_unknown_exact_binding_refuses_without_data_loss`, all in
`packages/lumio-wiki/tests/test_legacy_proposal_export.py`. Preserve true exits
with pipefail. Scoped Ruff/format/diff on the two owned Python files, format
before post-fix tests. No duplicate green reruns after prose/format/commit;
post-fix failure stops for named diagnosis and an affected-node proposal.
Own locked environment setup is authorized with Python 3.14.8 at
`/home/volker/.local/bin/python3.14`, uv 0.11.8 and declared dependencies only;
no sibling environment or lock/config changes. Reuse prior M 167+1 and
co-switch 19+1 only where applicable; no whole-module/group/full-suite,
typecheck, installed/live/provider/G5 certification. Pyright family remains
inconclusive, not type-clean evidence.

Raw logs: unique `RUN/logs/g4-fix-*`; handoff:
`RUN/g4-fix-worker-report.md` with actual commit/tree/base/ref, full porcelain,
commands/exits/red quality and limits. `RUN/run.json` is parent-only. Commit
exactly the three files, verify clean lineage and freeze ONLY the unique result
ref above, then relinquish writes. Parent owns the one `c2456a0..fix` M delta;
any surviving material same finding returns to the owner, never round three.
No delegation, memory/wiki/global automation, private app, real/shared KB/store,
integration, push, PR, issue update, release, deploy or cleanup authority.
No new vocabulary or ADR; planning-contract v1, catalog revision unknown.

**Owner-authorized G4 quota takeover, 2026-10-17 (r15):** after the original
Pi/GLM-high writer stopped with provider 429/1308, the owner explicitly answered
“Sol/high übernimmt”. The parent accepted the read-only takeover audit and
issued a limited repair/finish grant to fresh Paseo/Pi
`7c00a714-90ce-4025-a2f6-a3dff150a888` / native Pi `01a14b51…`, verified
`openai-codex/gpt-6.1-sol` / high in the SAME workspace, branch, common Git,
accepted G3 base `fb2bcf36…`, and reserved future `result/g4/a1` below.
This finishes the initial G4 implementation; it is not a new feature, validation
unit, review round, or budget reset. Old writer is error/no active turn and
has no further write authority. No initial independent M review has occurred.

The approved dirty input is preserved in `RUN/g4-provider-stop.patch`
(SHA-256 `cb8836eacc884426aca52803e7bf084210823ba7dc072f498160e90b72c7c964`)
and `RUN/g4-provider-stop-untracked.tar`
(SHA-256 `235aba1ded904b11ee29c5afc20ee11776d03177e56721f57a4afa473a7d3490`);
40 tracked files (2689 insertions/11430 deletions) and seven untracked files
matched those artifacts before takeover. Recovery artifacts remain immutable.
The predecessor's repeated/broadened tests, broad Ruff fixes, deleted retained
oracles, and unauthorized onboarding execution remain process violations;
its piped summaries are observations, not certified pytest exit statuses.

Parent-authorized repairs: restore the original private wire `kind/digest`;
bind the captured baseline and original reviewed preconditions/content identity;
verify exact private history/raw/version/transition consistency; preserve
namespace and explicit mutation/source intent; make receipts match the complete
export identity and retained artifacts; report history/decode/integrity errors
without preview writes; refuse unresolved pending state at native writer
preflight including reuse. Restore retained permission/compensation/Claim/link/
pin/redirect/source/privacy oracles, not retired staging wrappers. Complete the
approved current CLI/packaged/example co-switch, including the generated block
in `examples/real-world-lumio-wiki/AGENTS.md`; root `AGENTS.md` stays G5-owned.
Restore only the four formatting-only production files `link_candidates.py`,
`page_search.py`, `source_processor.py`, `source_resolution.py` to exact base.
Retain `git_authoring.py`'s three relocated-assembly consumers. Additional actual
test caller source migrations are limited to `test_capture_adapters.py`,
`test_semantic_maintenance.py`, `test_dream_duplicate_candidates.py`,
`test_url_ingest.py`, `test_documents_extra.py`, `test_plan04_agent_workflows.py`,
`test_ingest_journey_isolation.py`, `test_wheel_isolation_documents.py`, and
`test_wheel_isolation_llm.py`. Parent additionally approved SOURCE-ONLY closure
in `test_artifact_store_s3_compat.py` and `test_s3_publish_s3_compat.py`:
real native URL worktree ingestion preserves fetched-byte/artifact/page privacy
oracles; low-level transport tests explicitly call the private S3 transport
kernels, NOT public Git admission. Live certification stays G5-owned; no
HTTP/S3 execution, collection, smoke, or added check budget. Delete ONLY the
unused `_store` helper in `test_dream_synthesis_impact.py`; no unrelated cleanup
or module run. No new production module/dependency/schema;
no changes to spec/ADR/CONTEXT, `skill.py`, wheel verifier, or global guidance.

Takeover execution exception: Sol accidentally submitted selector-free
`uv run --no-sync pytest -q` while preparing the twenty-node command. The shell
timed out after one second without output; whether any test body ran is unknown.
The parent rejected this invocation as assigned evidence and independently
confirmed no surviving own-cwd pytest process. No restart, environment change,
new check budget, or full-suite result follows. The assigned M command produced
167 passes and one invalid-manifest diagnostic-wording failure; restoring the
strict "never a fallback" diagnostic (without changing the assertion) made that
single affected node pass. Parent accepted reuse of 167+1 and forbade another
M-group run. Resume the unrun twenty-selector selection once, with argv guards;
source-only closure/static checks and all other limits below remain unchanged.
The guarded selection then produced 19 passes and one overly strict migrated
research-page byte-comparison failure. Parent approved correcting ONLY that
oracle against the ORIGINAL fixture: independently parsed publishable YAML
minus the documented `category`/`durability_rationale` review/routing fields,
and exact stripped-body equality. Its sole affected-node recheck passed; reuse
M 167+1 and co-switch 19+1, never group reruns. Scoped Ruff/format, changed-script
syntax and diff checks passed; raw evidence and actual-role disposition belong
in the existing `RUN/g4-worker-report.md`. Independent M review and G5 remain
parent-owned gates; these worker results are not feature acceptance.

Exact remaining check authority (serial, own existing locked Python 3.14.8 /
uv 0.11.8 environment; no sync/install):

- ONE meaningful red: `test_legacy_proposal_export.py::test_export_journey`,
  after independently restoring the original-wire fixture, BEFORE decoder fix.
- ONE post-migration M command, not previously executed: `uv run pytest -q`
  with `test_legacy_proposal_export.py`, `test_git_authoring.py`,
  `test_ingest_journey.py`, `test_source_lifecycle.py` under
  `packages/lumio-wiki/tests/`.
- ONE additional selection of exactly these twenty existing/restored functions
  (same test directory; retain names or report exact old-to-new mapping):
  `test_page_removal.py::{test_relationship_repair_drops_edges_and_repairs_exactly_resolved_links,test_external_images_code_and_ambiguous_links_are_untouched}`;
  `test_entity_merge.py::{test_entity_merge_publishes_one_atomic_candidate,test_entity_merge_collision_blocks_publication,test_entity_merge_invalid_resulting_ontology_blocks_publication,test_claim_changes_report_additions_edits_lifecycle_and_removals}`;
  `test_artifact_store.py::{test_managed_ingest_retains_artifacts_through_the_pipeline,test_managed_ingest_wraps_store_failure_actionably}`;
  `test_maintenance.py::{test_stage_cross_link_proposal_is_publishable,test_cli_dream_reports_source_coverage,test_cli_lint_reports_source_coverage}`;
  `test_semantic_maintenance.py::test_cli_semantic_review_reports_and_stages`;
  `test_capture_adapters.py::test_export_then_preview_composes_through_capture_contract`;
  `test_url_ingest.py::{test_ingest_url_stages_https_source_under_stable_id,test_ingest_research_stages_report_with_consulted_provenance}`;
  `test_dream_duplicate_candidates.py::test_discovery_never_writes_and_merge_path_still_works`;
  `test_plan04_agent_workflows.py::{test_machine_mutation_errors_are_stable_and_private,test_copyable_actions_replay_original_kb}`;
  `test_cli.py::{test_source_candidate_leaves_source_active_without_staging,test_source_dismiss_candidate_records_decision_without_staging}`.
- Scoped Ruff/format/diff on changed owned Python files; final actual-role
  inventory. Reuse predecessor `bash -n` results unless a script changes,
  then syntax-check only changed approved scripts. Never execute examples.

Keep full raw command output and true pytest exit statuses in `RUN/logs/g4-*`.
Parent clarification during takeover: preview may resolve an explicit ref once
and display a copyable confirmation command using that captured full commit.
Confirmed CLI/SDK export requires that captured full commit (`plan.baseline`),
refusing floating confirmation input before locks/writes. No persisted preview,
new token, or new approval workflow is introduced; direct explicit full-commit
confirmation is sufficient operator selection, never publication admission.
A failure authorizes only named diagnosis and affected nodes after a real delta;
never widen modules, relax assertions, or repeat unrelated greens. Optional
converter/wheel/isolation source co-switch is not execution authority. No full
suite, whole CLI, onboarding, live services/providers/S3, MCP, wheels, G5,
private app, shared/real KB, integration/push/release, cleanup, delegation,
shared memory, or `run.json` writes. Commit/clean/freeze only `result/g4/a1`,
report to `RUN/g4-worker-report.md`, and relinquish writes before the parent's
ONE initial independent Sol/high M review. Standard subsequent collective fix
and delta recheck budgets remain unchanged. Planning-contract v1 SHA-256
`5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`;
installed catalog commit unknown. No new vocabulary or architectural decision.

**Owner-authorized G4 start, 2026-10-17 (r14):** the parent accepted
isolated G3 (`fb2bcf36cef5093e4b1bdc1a856260f0babc166e`, run-state
`g3Acceptance`) and, after the preflight readback, explicitly selected
"G4 mit GLM/high": sole worker Pi `zai/glm-5.3`/high, Paseo workspace
`wks_a810d2418d7f4c65`, physical checkout
`/home/volker/.local/state/worktrees/0ast0lnx/lumio-git-g4-worker-a1`,
branch `orchestrator/lumio-git-20261015/g4-worker-a1`, common Git
`/home/volker/coding/lumio-wiki/.git`. Frozen base
`refs/heads/orchestrator/lumio-git-20261015/base/g4-a1` = `fb2bcf36…`;
sole future result `refs/heads/orchestrator/lumio-git-20261015/result/g4/a1`.
Scope is G4 below unchanged in behavior, with these execution-decisions
recorded: pure mutation assemblies relocate to the EXISTING `publish.py`
(no new module) with `git_authoring.py`'s three native consumers;
`graph_exchange.py` + `test_graph_exchange.py` join the owned surface for
the legacy `import_graph` staged-producer closure; `distiller.py` may take
docstring-only cleanup of retired surfaces; the four real current callers
in `examples/real-world-lumio-wiki/` (`README.md`, `tools/stage_dream_repair.sh`,
`tools/run_maintenance.sh`, `tools/smoke_lumio.sh`) co-switch with G4;
`scripts/verify_lumio_wiki_wheel.py` and `test_skill_public_surface.py`
stay untouched unless an actual delta requires it. Check budget: unit M
new-test journey plus the four-file serial M command, co-migrated test
nodes only where a retired import/actual contract requires it (named
selection approved by the parent before execution), scoped Ruff/format/diff,
`bash -n` on the four co-switched shell scripts, and the `rg` role
inventory disposition. Locked worktree `.venv` (Python 3.14.8, uv 0.11.8,
declared dependencies only) is authorized. No full suite, live services,
wheels, MCP, G5 certification, private app, shared KB, integration, push,
or release. Review is ONE parent-dispatched independent M delta on
`openai-codex/gpt-6.1-sol`/high before G5, never worker-launched. No new
ADR/vocabulary; spec 0008 r3 owns behavior; planning-contract v1 SHA-256
`5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`,
installed catalog commit unknown.

**Owner-authorized G3-S correction, 2026-10-17 (r13):** after G3-R's
correction and one review exhausted its budget, the parent accepted the five
source-traced residuals R1–R5 and the owner selected **“Frischer Sol/high-Worker”**.
This separately bounded authority creates one fresh, sole Pi
`openai-codex/gpt-6.1-sol`/high candidate; it does not change global worker
defaults or restart the original review. Base
`refs/heads/orchestrator/lumio-git-20261015/base/g3-sol-a1` is
`a1f3ac22883023fbb343c755101dc4fc9824725a` (tree
`7f2e89bd509752329c4a1833474a58f8d26c09f7`); sole future result is
`refs/heads/orchestrator/lumio-git-20261015/result/g3/sol-a1`.
The sole writer is Paseo `3041b2a8-78b7-47de-9dba-d2c3998d1c41`, workspace
`wks_cb0b0df4fd54932a`, physical registered checkout
`/home/volker/.local/state/worktrees/0ast0lnx/lumio-git-g3-sol-a1`, branch
`orchestrator/lumio-git-20261015/g3-sol-a1`; native Pi
`01a14ad4-3792-74fb-86a8-bf91a3e8ae49`. Host, startup and environment verified
that exact model/thinking and clean base; common Git is
`/home/volker/coding/lumio-wiki/.git`.

Owned files are this plan, `src/lumio_wiki/{git_authoring,proposal_pipeline,cli}.py`
and `tests/{test_git_authoring,test_capture}.py` under `packages/lumio-wiki`.
R1 refuses actual compound+move directives in the shared candidate view,
computed before private registration and reused for manifest validation;
ordinary compound Sources/pins remain additive. R2 uses the existing full
link resolver's title/alias/path precedence and preserves supported fragments
and labels in exact repairs (small private helper closure only). R3 requires
an explicit keep/drop/replacement choice for actual title renames through a
tri-state SDK argument and mutually exclusive CLI selectors; move-only is
exempt, unrelated aliases survive unless explicitly replaced, and the contrary
omitted-choice test oracle is corrected. R4 feeds the actual capture record
through the existing pre-apply observation hook and bounded storage-error
mapping. R5 maps the existing rollback error at the actual passthrough ingest
caller, preserving failed paths and recovery location. No publication/move
redesign, module, dependency, schema, adapter or G4 work is authorized.

Exact validation budget: one red group of five residual tests (compound+move
pre-private refusal with independent S1/S2 digests and pins; original canonical/
alias-over-path Entity targets plus section/label preservation; amended
`test_rename_move_preserves_exact_references_and_alias_disposition` beginning
with missing-choice refusal, then explicit drop/keep/empty/move-only; actual
capture atomic-write failure with unchanged KB and truthful private history;
actual non-managed CLI ingest incomplete compensation with paths/location).
New-selector parser errors are not semantic reds. One post-fix group contains
those five plus exactly `test_compound_revision_keeps_retained_source_pin`,
`test_native_rename_moves_and_aliases_with_reference_repair`,
`test_native_capture_preserves_distinct_manifests_per_version`, and execution-only
`test_entity_merge_repairs_alias_links_and_prefers_title_over_alias`: nine nodes.
Scoped Ruff/format/diff once; failures authorize only named diagnosis and
relevant nodes after a delta, not broader suites or weaker assertions. Reuse
unchanged D3/D4/D5, URL/research and G1/G2 evidence only at matching surfaces;
no blanket 26/375, type-clean, installed/live/full-suite claim. Own locked
`.venv` setup is explicitly authorized using uv 0.11.8 and
`/home/volker/.local/bin/python3.14` (3.14.8), existing declared dependencies
only. Pyright import/venv/frozen-Struct findings remain inconclusive, without
configuration experiments.

Commit the six intended files, freeze only the reserved result with Git-handoff
guards, report exact endpoints/raw evidence in `RUN/g3-sol-worker-report.md`
and `RUN/logs/g3-sol-*`, then relinquish writes. Parent alone dispositions and
launches ONE independent Sol/high direct `a1f3ac2..fixed` delta review; a surviving
material item returns to the owner, with no automatic extra round. Prior G3
and G3-R budgets remain exhausted. No integration/publication/private-app/shared
KB/other-worktree/run-state authority is granted. Capture checkpoint: no new
vocabulary or architecture; specification 0008 r3 and accepted ADR-0016 already
own behavior. Planning-contract v1 SHA-256
`5adbbd63616169df00774d926e0daea2074b90c9cf213b508aea62e84942c200`, installed
catalog commit unknown.

**Owner-authorized G3-R residual correction, 2026-10-17 (r12):** after the
one Sol/high `b5e470b…4eee870` delta review returned residuals D1–D7 (all
parent-dispositioned accepted), the owner answered **“G3-R korrigieren”**:
one isolated GLM/high candidate from `4eee870…` correcting EXACTLY those
seven residuals (`base/g3-r-a1` = `4eee870…`, sole future result
`result/g3/residual-a1`). Worker remains Pi `zai/glm-5.3`/high (same writer,
workspace, and placement); review is ONE parent-only Sol/high direct
`4eee870…R` delta. The prior collective-fix budget is exhausted and stays
recorded; this is a separately named bounded authorization, not a third
round. Scope, all minimum-complete changes: D1 the manifest candidate view
derives from the SAME effective compound destination content as
validation/apply (reuse the existing source-merge owner; no parallel
algorithm, no dropped pins); D2 rename/move preserves exact incoming path
targets on move-only, keeps pre-move targets of the moved page's outbound
relative links, repairs the renamed page's own old-title references, and
exposes the explicit old-title keep/drop/replacement disposition plus a
CLI-expressible empty alias set (already-approved ADR-0016 behavior; the
prior narrow publish.py move-owner allowance remains accepted); D3 composes
body/link repairs against original coordinates (one candidate, one apply,
dirty guard intact) and diagnoses conflicting summary replacements like
lifecycle conflicts; D4 the native source register/candidate/dismiss/
confirm writers reuse the repository-relative tracked-original/tracked-
registry and inside-KB refusal before any private write (confirm before
both the manifest edit and the candidate decision; read-only list exempt);
D5 native register uses the existing exact-version registration primitive
(identical retry converges, different bytes extend immutable history, Git
intent/pins untouched) with truthful reused/registered disclosure; D6
required private URL/research/capture observation persistence moves BEFORE
the final worktree apply through one shared native hook with bounded
storage-error mapping (immutable private history may remain on refusal;
never falsely claim no history writes); D7 strict manifest errors translate
at the native owner/dispatch boundary and the existing rollback error maps
through the actual remove/merge/graph/passthrough/source CLI callers
(keeping failed paths + backup location; no new exception hierarchy). No
spec/ADR/CONTEXT/AGENTS change (spec r3 + ADR-0016 already settle the
behavior), no new module/dependency, no G4 work, no legacy format change.
Budget: one focused red residual group on existing seams (D1 compound
additive sources/pins; D2 combined move-only incoming + moved-outbound +
self-title + alias-disposition journey; D3 shifted-frontmatter link repair
plus conflicting summaries; D4 unsafe private-selection refusal before side
effects; D5 identical-retry/different-bytes registration without Git intent
change; D6 injected observation I/O failure leaves the worktree unchanged
with a bounded error; D7 strict-manifest and incomplete-rollback bounded
CLI errors) and one coherent post-fix unit for those scenarios plus
previously green nodes whose shared contracts actually changed; no rerun of
the whole 17/new-interface/P11 groups, no full modules/CLI/baselines. Reuse
prior evidence only where code/tests/inputs/env still match. Scoped
Ruff/format/diff once, formatting before the final behavior proof where
possible; Pyright missing-venv/import/frozen-Struct family stays
UNVERIFIED/inconclusive with no experiments. Env: the existing locked
worktree venv (Python 3.14.8, uv 0.11.8), no re-sync/install/config change.

**Owner-authorized G3 collective correction, 2026-10-17 (r11):** after the
independent G3 P review returned findings F1–F9 (all parent-dispositioned
material/in-scope), the owner approved one collective correction plus the
already-required native rename/category-move/explicit-alias completion, in a
fresh isolated candidate (`base/g3-fix-a1` = `b5e470b…`, sole future result
`result/g3/fix-a1`). Worker is Pi `zai/glm-5.3`/high (sole writer); review is
ONE parent-only Sol/high direct `b5e470b…fixed` delta, never a worker
precondition or autonomous third round. Scope: F1 complete-candidate Source
Manifest validation (revised/new Entities, true deletions only, strict-error
mapping); F2 retirement eligibility resolves exact registered versions in the
selected private history; F3 merge provenance/source-list union + exact pin
transfer with incompatible same-source digest refusal; F4 one shared
complete page/control/source candidate gate before registration/apply for
newly routed producers (no per-command forks); F5 exact-version-bound
immutable private provenance records (content-addressed per observation:
capture manifests and URL/research provenance under the selected registry
root, distinct records for same bytes/different metadata, converging
identical retries; legacy capture record format/route untouched until G4);
F6 actual resolved original transcript path through tracked-input safety and
full repository/target/tracked-private preflight before any private write in
reactivation; F7 both native compensation handlers consume `restore_all`
failures through the existing `MutationRollbackError` (retained backup,
failed paths, no new recovery system); F8 compatible semantic findings and
selected deterministic link repairs compose per page against the same
original into ONE checked apply with incompatible-intent diagnostics; F9 all
actual native source register/candidate/dismiss/confirm/list producers use
the explicitly selected shared private registry, disclosing Git manifest
lifecycle intent for managed sources. Plus: native rename primitive with
optional category move + explicit alias choice and reference/pin/ID safety
(pure `assemble_page_rename_candidate` lives beside the other pure assemblies
in `proposal_pipeline.py` only until G4 relocates them; native code never
invokes persisted ProposalPipeline state), and reactivation by explicit
Entity selection per spec r3 §3.3 (repeatable CLI `--entity`, SDK
`entity_ids`). No schema/ontology/namespace change, no vocabulary/new ADR,
no G1/G2 publication/Reader redesign, no legacy format exercise (G4 owns
export/archive/delete). Budget: one selected red bug group against unfixed
public seams (F1–F9 where deterministic; new rename/reactivation interfaces
are new behavior, not failing-import ceremony), one coherent post-fix native
group covering the eleven named scenarios, scoped Ruff/format/diff once.
Reuse the exact-base G3 P11 375p/1s log and G1/G2 evidence only for
unchanged surfaces. No fresh baseline, no P11/full-`test_cli`/
full-`test_git_authoring` rerun, no full suite, live services, wheels, MCP,
private app, shared KB, integration, push, or release. Env: worktree-local
locked uv environment on `/home/volker/.local/bin/python3.14` (3.14.8) with
declared locked extras only.

**Owner-authorized G3 start, 2026-10-17 (r10):** the parent accepted the
isolated G2 component (`g2Acceptance` in the orchestrator run state; closed
review chain `g2-reviewer` → `g2-fix-reviewer` → `g2-fix2-reviewer` →
`g2-d1-reviewer` PASS) and authorized G3 in a fresh isolated candidate
(`base/g3-a1` = `69cbd715…`, sole future result `result/g3/a1`). Worker is
Pi `zai/glm-5.3`/high (sole writer); review is one parent-only independent
P delta on Sol/high before G4, never a worker precondition. Baseline reuse:
the parent git-verified that the eleven P test files and the legacy
producer/support modules they exercise are byte-identical from the committed
G1 fix tree (`410e7ac…`) to the accepted G2 base, so the committed G1
full-suite (`1732 passed, 9 skipped`, fixed `-n 4`) and regression (`402
passed`) logs pin unchanged legacy producer behavior; no fresh P baseline,
full suite, or repeated green is run for the new worker/path. Post-delta
budget: the plan's eleven-file focused P command runs once after migration
only because every listed producer actually changes; additional checks are
limited to `test_git_authoring.py` nodes whose direct contract changes,
node-selected `test_cli.py` migrated-producer handlers, and directly affected
ingest/optional-extra cases, each justified by the actual diff; semantic
oracles are preserved while obsolete proposal-state assertions migrate to
file/Git-diff plus admitted-snapshot outcomes; tests that explicitly cover
the legacy terminal lifecycle scheduled for G4 stay classified legacy.
Default zero new tests; one focused case only for genuinely uncovered
compound-provenance/binding/redirect-pin/dirty-refusal behavior with
independently derived expectations. One coherent selected post-fix unit plus
scoped Ruff/format/diff; one collective fix pass and one parent-only delta
recheck. No full suite, live services, wheels, MCP, provider calls, private
KB, integration, push, or release. Env: worktree-local locked uv environment
on the explicit Python 3.14.8 with the declared locked workspace/dev extras
needed by the selected cases.

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

- [x] Replace current proposal workflow examples with native Git authoring,
  exact review/confirm admission, source privacy and explicit migration. Update
  assertions against installed skill bytes, not just repository Markdown. Do not
  refresh globally installed user skills or edit the real shared KB.
- [x] Run installed-wheel author/validate/query journey without Ariadne/model/
  server/GitHub/LanceDB; additionally remove Git from the read/query subprocess
  PATH to prove plain reads still work. Use the new built candidate wheels,
  not the earlier baseline wheels or workspace imports. Reuse/update existing wheel
  isolation/verifier tests rather than building a second harness.
- [x] Run required CI checks below on exact candidate trees (composed evidence above;
  original red exits preserved, no fresh whole-suite green claim). Refresh canonical
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
