# Implementation plan 0029: Git/local-first Lumio integration

| | |
| :--- | :--- |
| **Status** | **Revision 16 — L2 → A2 execution authorized, 2026-10-20.** Q2 is accepted isolated85dbaab. Owner approved the exact written local navigation contract and its autonomous producer → consumer implementation. G2/T2 and other remaining drafts stay proposed. Previous status: Owner requested a next-issue roadmap and reaffirmed Git with local sync as the standard, S3 secondary. No implementation, test execution, ticket publication, integration or release is authorized by this draft. Historical approved M1 execution r12 is complete and preserved in `v0.5.0` and the immutable result refs. |
| **Owner direction** | 2026-10-20: “S3 Anbindung ist für Ariadne zweitrangig. Der bevorzugte Weg bleibt git repo mit lokalem sync.” This approves the priority used for this proposal, not new SDK interfaces or capability expansion. |
| **Goal** | Make the shared Git Content Repository plus a local checkout the normal operator path, then expand useful local knowledge/analytics capabilities without weakening exact admission or standalone behavior. S3 is optional later work, not a prerequisite. |
| **Behavioral sources** | [Spec0029 approved r2](../specs/2026-10-18-0029-lumio-bound-governed-releases.md), especially §§2–6 and preserved full-target AC1–AC9; [ADR0026](../adr/0026-lumio-sdk-bound-governed-releases.md). Companion: `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md` r2 / ADR0030. The r2 MVP refusal boundary remains authoritative until the corresponding source amendments are approved. |
| **Starting artifacts** | Published `ariadne-data==0.5.0`, Core `a9dd5f8ff9ae15b55268cad6dad0841caf0057fa`; published `lumio-wiki==0.3.0` / `lumio-lancedb==0.3.0`, producer `a5127c753a6343629ba3fc7adfa44441c8f82baf`. Use exact accepted successors in later handoffs, never floating `main`. |
| **Tracker** | [#76](https://github.com/legout/ariadne/issues/76): full epic; [#79](https://github.com/legout/ariadne/issues/79): consumer continuation; [#80](https://github.com/legout/ariadne/issues/80): remaining adapters/guidance/qualification. [#81](https://github.com/legout/ariadne/issues/81) and [Lumio #2](https://github.com/legout/lumio-wiki/issues/2) have delivered released code but remain open; no closure is authorized here. Their old ticket text must be reconciled before new execution. |
| **Capture / readiness** | Existing glossary terms suffice. Git/local preference changes sequencing, not ADR0026's architecture; no new ADR is proposed. New operation support and the additive navigation API require written Core/producer source amendments before their writers start. Contract: planning-contract v1; installed catalog provenance unknown. |

## Current execution — approved L2 → A2 navigation

Owner 2026-10-20 answered “ja” to the exact written Lumio navigation contract
and autonomous producer → consumer implementation. Scope is spec0009 navigation
r3 at producer source `818dadeb54ddb931f828a362ca5c233999f3ad86` and Core spec0029 §1.3. Q2 is already
accepted isolated85dbaab; all its existing evidence/review stays valid except
where this navigation delta directly affects support/build/fixtures.
Do not re-run Q2's independent numerical scenario for a fresh label.

Pi host remains BB, explicit isolated registered paths under the shared XDG
root; worker `zai/glm-5.3/high`, reviewer `openai-codex/gpt-6.1-sol/high`.
One producer writer, immediate independent producer public-contract review,
then one sequential Core writer on the accepted Q2 candidate. No S3 service,
new dependency, metadata/version bump, target integration, push, issue changes,
release, real-KB access or cleanup. Native mandatory repository/CI gates remain
binding at their owning final qualification/release stage; do not claim them
from these focused source checks.

L2 owns `packages/lumio-wiki/src/lumio_wiki/ariadne_context.py` and its existing
`packages/lumio-wiki/tests/test_ariadne_context.py`. Native `page_search` and
`evidence` helpers are reused, not rewritten. Preserve existing profile/S3
reader behavior. Prefer an additive facade using the current verified reader
and native immutable resolution; no behavior-changing verification extraction
without an explicitly pinned characterization obligation. Add one focused native
publication/navigation test with independently authored pages/coordinates and
scope/version/mismatch cases from the approved amendment. First return prepared
test data for parent static schema/oracle inspection before the sole invocation.
Then implement and run once, serially:

```sh
$SDK_PY -m pytest -q packages/lumio-wiki/tests/test_ariadne_context.py
```

This covers new disclosure plus existing local/S3 identity and profile failures;
unchanged native ranking tests remain the ranking oracle. Targeted Ruff and
syntax/diff checks cover changed files. A failed invocation freezes WIP for
parent disposition; at most one parent-authorized small fix pass with one exact
affected recheck. Preserve genuine failures, reuse unrelated green nodes, no
repeat-until-green. A fresh Sol/high public-contract review must pass before A2
consumes the exact SDK content/build.

A2 owns Core `lumio_context.py`, `discovery.py`, necessary source-free forwarding
in `query.py`, and only genuinely necessary CLI/MCP forwarding. Tests remain
explicit optional-SDK modules outside default collection: add one focused A2
scenario in `tests/lumio_local_context.py`; adapt only navigation refusals and
now-available pages group in `tests/lumio_metric_mvp.py`. Old unsupported-kind
and remaining operation/role/consent/source checks stay. No technical resolver,
Core YAML parse or alternative ranking. First statically inspect its native
fixture/oracle, then one invocation:

```sh
$CORE_PY -m pytest -q tests/lumio_local_context.py::test_context_navigation_uses_sdk_without_legacy_or_sources tests/lumio_metric_mvp.py tests/test_discovery.py::test_admitted_context_only_discovery_pins_snapshot_and_never_reads_sources tests/test_discovery.py::test_mcp_discovery_starts_source_free_for_every_registration
```

The SDK environment consumes the frozen accepted producer source/build; base
Core still imports without SDK. Reuse Q2 numerical proof while that code/test
and fixture remain unchanged. If a required change invalidates it, parent assigns
its exact affected check before execution. One fresh A2 candidate review covers
new Core integration effects and prior Q2 correspondence; it does not reopen
settled Q2 findings. Same one-small-fix/one-delta limit, with all budgets and
identities recorded in the existing run state, not another ledger.

## Historical Q2 execution — accepted first A1 prerequisite

Authority: current owner requests autonomous implementation and selects BB Pi
worker `zai/glm-5.3/high`, reviewer `openai-codex/gpt-6.1-sol/high`; then directs
work to unmet A1 before Q1. This supersedes planning-only status for **Q2 only**.
Source: spec0029 revision3 §1.2, existing §6 and AC3–AC5/AC7–AC9. No new producer
API, terminology or architecture decision; ADR0026 invariants remain binding.
The other source amendments and task drafts are not approved by this header.
No GitHub task publication/closure or software integration/push/release.

Use BB Pi threads bound explicitly to a parent-created registered isolated Git
worktree under the shared XDG state root. Verify actual child cwd/branch/base
and configured/effective model plus thinking before granting writes. One writer;
independent reviewer is read-only. Preserve original main plan draft and all
prior evidence. Frozen native base is Core0.5.0 a9dd5f8 and producer0.3.0 a5127c7;
record full identities and runtime details in the existing new run state.

Owned Q2 files and behavior are below. Existing SDK qualification tests outside
default collection may adapt only the two superseded refusals; preserve every
remaining integrity/permission/consent oracle. Assigned **one** serial pytest
invocation after the coherent change, combining:

```sh
$CORE_PY -m pytest -q tests/lumio_local_context.py tests/lumio_metric_mvp.py tests/test_serve.py::test_list_datasets_returns_demo_tables_with_columns
```

Only one new focused multi-metric/preflight test is needed. Reuse unchanged
native planner tests and released producer proof; no producer suite, S3 service,
full Core suite or numerical wheel rerun is assigned. Static affected-file
Ruff/syntax/diff inspection is allowed. Failure freezes WIP and stops; no retry
or widened selector without owner disposition. One fresh Sol/high review with
the full inline reviewer contract; at most one parent-authorized small fix and
one delta recheck. Deliver an isolated committed reviewed Q2 candidate, keeping
remaining A1 and #80 acceptance explicitly open.

## Next-issue roadmap — proposed priority

### Requested #80 execution — prerequisite disposition pending

Owner now requests autonomous #80 execution via BB Pi children: worker
`zai/glm-5.3` / `high`, reviewer `openai-codex/gpt-6.1-sol` / `high`.
Both exact pairs are present in the live BB Pi catalog. This grants execution
of the requested task, but does not establish its missing full-A1 prerequisite:
approved spec0029 r2 explicitly defers capabilities from the original #79.
No writer is dispatched until that prerequisite/scope conflict is resolved.

Proposed bounded disposition: **qualify #80 against the released local r2
Metric MVP**, retaining the full-target remainder under the open parent issues.
Owned surfaces and low-risk obligations stay those of #80; do not add G2
status behavior, SDK navigation, multi-metric, Reference validation or S3
consumer support merely to make qualification pass. Inspect actual CLI/MCP
forwarding and role exclusions, correct only necessary wrappers/guidance, keep
optional SDK imports out of base Core, run V3 once, and establish installed
Core/SDK origins and exact profile identity outside the source checkouts.
Use frozen producer/consumer commits and candidate-bound wheel digests.

For unchanged producer code, inspect exact existing CI evidence before deciding
whether its V4/V5 obligations remain applicable; do not assume release status
alone proves those checks. Producer changes invalidate affected evidence and
require its named gates. A missing required gate or disposable-service authority
is reported before that execution, not bypassed. One independent Sol/high
candidate review, at most one parent-authorized small fix pass and one delta
recheck. Preserve isolated committed results; no target integration, push,
release or full #80 closure. The alternative is to complete the separately
planned full A1 capabilities before running original full-target Q1.

Live GitHub issue reads on 2026-10-20 found six open Ariadne issues. #76,
#79 and #80 still describe the original r1 planning state; #81 still presents
the completed r12 correction as pending. Reconcile those descriptions with the
released baseline before using them as execution handoffs. This local roadmap
does not update or close GitHub issues.

| Priority | Existing issue / proposed child | Next useful outcome | Readiness |
| :--- | :--- | :--- | :--- |
| First | #80, G2 local-operator child | Document and expose the standard Git/local journey: sync, distinguish checkout from active release, validate, preview and explicitly admit | Local-operator source amendment before implementation; no new SDK API |
| Second | #79, A2 navigation child; companion Lumio L2 child | Read/search/list ordinary and profiled knowledge through the exact scoped local publication | Producer contract amendment and accepted L2 before A2 |
| Third | #79, Q2 multi-metric child | Answer several predefined metrics with complete per-metric Policy context before execution | Capability/source amendment; does not technically depend on navigation |
| Fourth | #79, T2 Reference child | Resolve a technical term using authentic Core evidence and explicit mapping confirmation | Reference validation/consent amendment; no blanket profile expansion |
| Alongside each slice | #80 remaining adapters/guidance/installed pairing | Expose the delivered capability consistently through CLI/MCP/skills and qualify the exact artifact pairing | Follow the owning accepted slice; avoid a deferred all-at-once adapter project |
| Coordination only | #76 epic | Track the released MVP, these local milestones and later optional work separately | Keep open while full-target acceptance remains incomplete |

Before the first implementation handoff, reconcile the Core/producer behavioral
sources and publish approved child tasks under the existing parents. Do not
dispatch the broad historical #79/#80 bodies unchanged. #81 and Lumio #2 are
delivered-code reconciliation/closure candidates, not the next coding tasks;
closure needs its own disposition against their actual bounded acceptance.

**Later backlog:** Core S3 KB consumption follows the useful local capabilities
and does not block any milestone above. #18 is a separate private-HTTPS
deployment task requiring a concrete deployment choice; Git sync needs no new
remote Ariadne service. #52 is a separate private-data evaluation requiring
reviewed domain oracles, a fixed authorized snapshot and provider readiness.
Neither is a prerequisite for this local integration continuation. Agent/Tau,
ad-hoc/record queries and additional technical profile kinds remain outside it.

## 1. Delivery model and invariants

```text
Shared Content Repository / reviewed Git revision
                    |
      explicit fetch / fast-forward local sync
                    |
      native candidate + joint validation/review
                    |
        one human overall confirmation
                    |
  immutable local Lumio publication + Core snapshot
                    |
    atomic Core activation; sessions pin that binding
```

- Git transports authored revisions; it is not a second activation mechanism.
  `pull`, merge, a scheduler or a remote branch update cannot publish/admit a KB,
  grant Source Approval or overwrite `.ariadne/current.json`.
- Use ordinary Git for clone/fetch/fast-forward. Existing native proposal,
  explicit base-revision and reconcile routes own candidates. Dirty/diverged
  checkouts stop for the operator; no force-sync, reset or discarded proposal.
- No new sync daemon, Provider service, proprietary mirror or GitHub runtime
  requirement. An operator may automate Git transport externally; Core neither
  installs that automation nor turns it into an approval authority.
- Knowledge remains authored in `knowledge/`; no editable copy in
  `context_layer/`. Native Core technical artifacts keep their existing owner.
  Local publication/snapshot copies are derived immutable materializations.
- Before admission, a synced newer revision leaves the old active binding
  unchanged. Existing sessions stay pinned; new sessions use a new binding only
  after explicit matching admission. No zero-downtime promise across incompatible
  code upgrades: retain an old deployment or revalidate/readmit explicitly.
- Source Approval, complete Policy Closure, Visibility Scope, original-time
  evidence, code identity and atomic-last activation remain mandatory.
- Capability additions require a new matching validated admission. Do not edit
  a served manifest in place or merely remove an unsupported-operation guard.
- This priority concerns **KB transport/publication**. Existing native Core S3
  data-source/storage backends and their access gates are not removed.
- Agent, Tau-MCP, the private application, real KB/data migration and automatic
  production admission remain excluded. Base Core stays SDK-independent.

## 2. Source and tracker gate — before coding

- [ ] Reconcile Core spec0029 into an explicitly approved continuation revision:
  local Git transport versus activation, staged operation support, ordinary-page
  disclosure, numeric/mapping safeguards and continued unsupported operations.
- [ ] Reconcile companion spec0009 for the additive scoped navigation API below;
  preserve producer0.3's existing profile snapshot/identity/closure behavior.
- [ ] Update #76/#79/#80 to the released baseline and this local-first ordering.
  Record completed M1/L1 and release evidence without claiming full A1/Q1 done.
  Close delivered tickets only with explicit owner authorization.
- [ ] After plan/source approval, publish the bounded G2/L2/A2/Q2/T2 task drafts
  below as canonical child tickets, then keep this plan as a thin dependency/
  coverage/budget map rather than a second editable task definition.
- [ ] Freeze approved source and producer/consumer refs; assign exact runtime,
  isolated worktrees, environments and check scope before dispatch. No old
  M1/V2/Q1 invocation or repair budget is reusable authorization.

**Readiness:** no new writer is ready now. G2 needs the approved local-operator
contract; L2/A2 need the navigation amendment; Q2/T2 additionally need their
capability/source changes. The proposals below do not silently override r2.

## 3. Ordered vertical slices — unpublished task drafts

Every Core capability slice also owns the affected expectations in existing
`tests/lumio_metric_mvp.py`: replace only explicitly superseded refusals,
preserve money/consent/isolation/unsupported-kind checks. In T2, a Reference
must cease being the unsupported-kind oracle only after its complete approved
validation exists; retain a genuinely unsupported producer-valid kind instead.
Do not delete the strict global gate or rewrite the golden baseline.

### G2 — usable Git/local operator journey (Ariadne)

**Deliverable:** an operator can sync one synthetic Content Repository, see the
local Git revision separately from the admitted Bound Release, and perform the
existing exact preview/confirmation workflow. A sync alone never activates it.

**Files:** `src/ariadne/status.py`; only necessary existing dispatch/help in
`src/ariadne/cli.py` and `src/ariadne/admission.py`; new
`docs/how-to/lumio-git-local.md`, `README.md`, applicable packaged Core
`skill_assets/` guidance; `tests/lumio_local_context.py` (new explicit SDK test
module, deliberately outside default `test_*.py` discovery).

- [ ] Document concrete clone/fetch/fast-forward, native candidate/reconcile,
  Source Approval when needed, joint validation, preview, explicit confirmation
  and source-free catalog calls using the existing commands. No sync wrapper.
- [ ] Add source-free status disclosure: local Git HEAD versus admitted content
  commit/Bound Release digest, immutable local Published Version and supported
  operations. Reuse the verified descriptor, expose no private registry or raw
  Source material. Status does not fetch, mutate or open data sources.
- [ ] Keep stale/build-mismatched admission a refusal, not “ready” because a
  checkout exists; distinguish no admission from an invalid admission.

**Validation:** normal integration scenario, `new-test`
`test_sync_does_not_activate_context`. A local temporary Git remote supplies
revision B while A is admitted: status reports B versus A; current descriptor
bytes and session pin remain A until explicit B admission, then a new session
observes B. No repeated revenue computation is needed. One focused call G.
Parent inspection suffices for the mechanical status/docs delta; include its
integration effects in A2's candidate review. Stop if an activation redesign is
found necessary; it is not hidden in this slice.

### L2 → A2 — ordinary knowledge navigation through the pinned SDK (both repos)

**Why a producer step exists:** producer0.3's `ContextSnapshot.pages` contains
only profiled pages (`ariadne_context.py:1951–1980`); ordinary unprofiled wiki
pages are absent. Its native lexical search consumes `CompiledPage`, not
`ContextPageView`. Do not make Core reparse YAML, reopen an arbitrary directory,
read an unfiltered snapshot or implement another ranking engine.

**L2, Lumio ownership:** `packages/lumio-wiki/src/lumio_wiki/ariadne_context.py`;
reuse `page_search.py` and existing page-reading helpers; change those helpers
only if required for immutable input reuse. Tests:
`packages/lumio-wiki/tests/test_ariadne_context.py`. No LanceDB requirement.

Proposed additive public functions, to freeze in spec0009 before execution:

- `list_published_context_pages(location, expected)` — scoped page metadata;
- `read_published_context_page(location, expected, path)` — exact scoped page;
- `search_published_context_pages(location, expected, query, *, limit=10)` —
  native deterministic lexical results over that same scoped immutable version.

Inputs are explicit version-pinned local `PublishedFilesystemLocation` and
`ContextIdentity`; `current`, branches and plain directories still refuse.
All operations share the existing identity/admission verification, then scope
filter **before** lookup, ranking, excerpts, counts or citation construction.
Results retain namespace, Entity ID, path, Published Version and passage identity.
Proposed read results reuse the immutable `ContextPageView`; navigation may label
an ordinary page `kind: unprofiled`, never technical validation. List/search
rows additionally disclose title and, for hits, snippet/matched passage and
native ranking/completeness metadata. Freeze these additive result contracts in
the producer amendment before coding; old profile snapshot fields do not change.
Read preserves canonical text; search uses the existing Lumio scoring/query
bounds and truthful completeness. No hidden page title/content/topology leaks.
An ordinary page is explicitly unprofiled documentation, not a Core-validated
physical reference. Keep the old `ContextSnapshot.pages`/`bindings` API intact;
no mutable internals or unscoped native snapshot escape through the new facade.

**A2, Ariadne ownership:** `lumio_context.py`, `discovery.py`, `query.py` only
for deferred source-free forwarding; `cli.py`/`serve.py` only if existing
forwarding loses identity or errors; the explicit SDK test module above.

- [ ] Enable `list_context_pages`, `read_context_page`, `search_context` and
  the `discover` pages group using only the new scoped SDK operations.
- [ ] Preserve existing Core outer result shapes and bounds; add exact SDK
  citations/binding metadata. Refuse an output that cannot meet required limits.
- [ ] Preserve source-free startup, role exclusions and standalone paths.
  No fallback to `context_layer/`, raw checkout or a moving Lumio pointer.
- [ ] Do not enable `resolve_term` here: Core's resolver discloses technical
  References/mapping-confirmation state, not merely generic wiki aliases.

**Validation / review:** high-risk disclosure/public-API unit. L2 `new-test`
`test_scoped_published_navigation_includes_ordinary_pages`: visible ordinary
and profiled pages, a hidden page with the same search token, exact citation
and later-version isolation. Native page-search tests remain the ranking oracle.
Immediate independent L2 contract review before A2 consumes it. A2 `new-test`
`test_context_navigation_uses_sdk_without_legacy_or_sources`: SDK text wins
against a deliberately different legacy page; source construction raises if
reached. One producer call L and one consumer call A; one A2 candidate review
also covers G2. Completion needs accepted exact producer/consumer refs and
explicit new support in a newly admitted binding, not just successful imports.

### Q2 — local multi-metric analysis and native catalog (Ariadne)

**Deliverable:** `list_datasets` retains its native approved live-catalog
contract; `query_metrics` calculates multiple predefined metrics with complete
context from one exact local SDK binding. This does **not** depend on T2:
native Core graph/schema/source checks already own execution authority.

**Files:** `src/ariadne/query.py`, `lumio_context.py`, `discovery.py` for necessary
preflight/deferred routing, `query_results.py` only for existing accounting;
`tests/lumio_local_context.py`. Do not change the planner/compiler unless a
separately dispositioned defect requires it.

- [ ] Resolve every requested metric's exact binding and complete Policy Closure
  before operation planning/live audits/bind/SELECT. The union must fit the
  existing complete-response budget; never calculate and only then notice that
  mandatory context is missing or too large.
- [ ] Return per-metric context/citations from one SDK Published Version;
  deduplicate shared Policies without losing each metric's association.
- [ ] Preserve native graph/joins/grain, Source Approval, deadlines, result
  limits, data signals and pending-attestation semantics. No extra contract
  inspection or false source-free claim for live `list_datasets`.
- [ ] Update capability disclosure and the now-retired refusal expectations for
  only these operations; all other unsupported operations still refuse.

**Validation:** high-risk money/output unit, `new-test`
`test_multi_metric_context_precedes_execution`. Independently authored orders
100+50 completed and25 cancelled imply revenue150 and completed-order count2.
Assert both complete contexts/citations. A complete combined context that cannot
fit the configured response budget refuses before planner/audit/SELECT, even if
one metric's context alone fits. Reuse existing planner/containment tests when
unchanged; include the existing native catalog check in call Q. Immediate
candidate review before any dependent capability consumes this result.

### T2 — one complete technical Reference/term slice (Ariadne)

**Deliverable:** accept supported SDK `reference` profiles only after the
existing Core inspection/evidence/mapping gates validate them, and expose
`resolve_term` with exact scoped provenance and confirmation state.

**Files:** `src/ariadne/lumio_context.py`, `authoring.py`, `admission.py`,
`context.py`, `discovery.py`; `authoring_inputs.py`/`validate.py` only where
necessary to reuse current structured validators; explicit integration tests.
Producer0.3 already represents References; no second schema or assumed Lumio
change. Additional producer changes need a concrete missing contract first.

- [ ] Match explicit physical Resource/model/ODCS identities, not titles/aliases.
  Validate every newly supported annotation globally across the candidate.
- [ ] Reuse Core-owned generated observations and authentic measurement receipts
  with their actual time/dependencies. A successful query, old sample digest or
  authored `verified` flag is not evidence. No second curated technical mirror.
- [ ] Bind human mapping selections to the exact claim/evidence/revision in
  composite consent. Term resolution never authorizes a join or applies a
  transform; ambiguity/unconfirmed claims remain explicit.
- [ ] Keep dataset/table/computation/skill profile kinds and any unsupported
  extension refused until their own complete consumer validation is planned.

**Validation:** high-risk evidence/authority unit, `new-test`
`test_reference_term_resolution_requires_real_evidence_and_confirmation`.
Use genuine native inspection on approved synthetic sources and an explicit
candidate edit of the unchanged golden Reference input. Assert exact scoped
field lookup and unconfirmed/confirmed result states; changed dependency/evidence
must not retain confirmation. One call T and immediate candidate review.
Completion is a complete candidate→validation→consent→resolution path, not
metadata preservation alone.

## 4. Dependencies, responsibility and bounded assurance

| Slice | Actual prerequisite, beyond its approved source amendment |
| :--- | :--- |
| G2 | Released local MVP; no new producer API |
| L2 | Released producer0.3 contract; independent of G2's status/docs code |
| A2 | Accepted exact L2 API/build |
| Q2 | Released native Core graph/Metric/Policy binding; no technical dependency on A2 or T2 |
| T2 | Existing Core inspection/evidence/confirmation contracts and producer Reference schema; no numerical dependency on Q2 |

Recommended delivery order is **G2 → L2/A2 → Q2 → T2** for operator usefulness,
not an invented code dependency. G2 and L2 could run independently in separate
repositories after source approval; do not introduce parallel roles just to
fill that possibility. Use one sequential Core writer because A2/Q2/T2 touch
shared discovery/binding code. One writer per registered isolated worktree;
producer acceptance precedes its consumer. Future orchestration uses Pi/verified host and exact roles, not an
implicit continuation of archived M1 agents or stale editable environments.

| Source requirement | Owning slice |
| :--- | :--- |
| §§2,4–5; AC1,AC5,AC6,AC8 — Git candidate is not activation | G2; preserve released native admission checks |
| §§3,4,6; AC2,AC4,AC7,AC9 — scoped pinned knowledge navigation | L2/A2 |
| §6; AC3–AC5,AC7–AC9 — complete predefined metric answers/catalog | Q2 |
| §§2–5; AC2,AC4,AC8 — validated physical references/evidence/mappings | T2 |
| Preserved full-target S3 clause | Separate optional later S3 task; not a local milestone dependency |

Proposed **seven manual pytest invocations**, each once after its coherent slice;
no runtime call is authorized now. New-feature checks need no ceremonial red
call; an actual bug/refactor repro needs a separately assigned failing-first
obligation. `$CORE_PY`, `$SDK_PY` and `$BASE_PY` are future run-qualified
Python>=3.14 environments; Base has no Lumio. Focused development stays serial.

```sh
# G: local Git versus activation
$CORE_PY -m pytest -q tests/lumio_local_context.py::test_sync_does_not_activate_context
# L: producer contract before consumer
$SDK_PY -m pytest -q packages/lumio-wiki/tests/test_ariadne_context.py::test_scoped_published_navigation_includes_ordinary_pages
# A: Core routing, not a second producer test matrix
$CORE_PY -m pytest -q tests/lumio_local_context.py::test_context_navigation_uses_sdk_without_legacy_or_sources
# Q: analytic context + native catalog (existing unchanged catalog oracle)
$CORE_PY -m pytest -q tests/lumio_local_context.py::test_multi_metric_context_precedes_execution tests/test_serve.py::test_list_datasets_returns_demo_tables_with_columns
# T: authentic technical Reference contract
$CORE_PY -m pytest -q tests/lumio_local_context.py::test_reference_term_resolution_requires_real_evidence_and_confirmation
# W: final changed-wrapper/role boundary, existing checks
$CORE_PY -m pytest -q tests/test_discovery.py::test_admitted_context_only_discovery_pins_snapshot_and_never_reads_sources tests/test_discovery.py::test_mcp_discovery_starts_source_free_for_every_registration
# B: final SDK-free default collection, existing capability exclusions only
$BASE_PY -m pytest -q --collect-only --ignore=tests/test_s3_lakehouse.py --ignore=tests/test_s3_storage_access.py --ignore=tests/test_s3_storage_profiles.py
```

These checks target newly reachable failures, not coverage percentages. Retain
and adapt the existing explicit `tests/lumio_metric_mvp.py` behavioral oracles;
run affected nodes in the owning invocation if the actual diff invalidates
prior proof. If that adds required scope, agree the exact combined selector
before execution, never silently expand the seven-call budget or weaken tests.
No SDK imports/skips in default Core collection. Required existing repository/
release gates are **additional binding gates**, not optional alternatives:
Lumio locked sync/lint, full `pytest -q -n 4`, native S3/onboarding and isolated
wheel checks; Core's built-wheel suite keeps its three existing S3 exclusions.
Use CI evidence on the exact candidate when available rather than duplicate
local runs. Any disposable service/transport needs its own explicit execution
scope. No paired numerical rerun merely because an artifact was rebuilt.

Old released Core0.5/Lumio0.3 gates are baseline evidence, not proof of new
interfaces. Unchanged planners/native source controls keep applicable proof;
new SDK data/identity/scope, admission/support or numerical changes invalidate
the corresponding evidence. A failure stops the affected lane with real logs,
no automatic repairs, retries or skipped assertions. At most one subsequently
parent-authorized fix pass and one delta-only recheck; never a third round.

## 5. Explicitly later / out of this local continuation

- **Core S3 KB consumption:** later optional transport work with separate
  location/receipt/failure and native S3 qualification. Keep its refusal today.
  Existing Lumio S3 support does not prove the Core consumer path.
- **Record/detail/ad-hoc queries, Examples:** retain integrated refusals for now.
  Unlike predefined metrics, their required context/Policy/technical binding
  cannot be inferred from one `metric_ref`. Define those contracts explicitly
  before implementation; do not enable them with `context: null` or a guessed
  Policy union. Standalone native behavior is unchanged.
- **Other technical profile kinds:** require their own authentic Core validation
  seam, not a blanket expansion of the supported-kind set after Reference works.
- No Agent/Tau/private-app work, generic search/ontology platform, model-driven
  ranking, background activation, source-permission grant, production migration,
  automatic release or premature full #76/#79 closure.

## 6. Source observations and completion boundary

Planning reads, not runtime probes, established the relevant seams:

- `src/ariadne/status.py:_admission_view/build_report` expose native revision
  but not the full Bound Release/local Git-HEAD distinction.
- `src/ariadne/discovery.py:search_context/read_context_page/resolve_term`
  currently refuse integrated use and otherwise read the legacy Core context.
- `src/ariadne/lumio_context.py:verify_release/metric_context` own the reusable
  cross-binding and per-metric disclosure; preserve them rather than new stores.
- `src/ariadne/query.py:_QueryRuntimeSession.query_metrics` currently refuses
  integration and constructs legacy metric context after execution: Q2 must
  move its required SDK-context preflight ahead of live operation planning.
- Lumio `ariadne_context.py:ContextSnapshot/open_published_context` exposes
  profiled pages only. `page_search.py:search_pages` is existing deterministic,
  LanceDB-free native ranking and must remain the search implementation.

This draft intentionally replaces the completed execution map, not its history:
read the full approved r12 at tag `v0.5.0`; original A1 failed WIP `df72f3f`,
M1 accepted result `9e2e9c1`, merge `e6d474c`, original-doc archive `30470e1`,
producer design archive `62bb41c` and run evidence remain preserved. Old failed
calls/reviews are never reset into a new budget. The published three-package
release is complete; Agent/Tau are excluded under ADR0018.

Next action after owner review: approve/reconcile the source amendments and
canonical task decomposition, then separately authorize the first bounded
implementation slice. Delivery remains supervised: accepted isolated candidate
and pause; integration, push, release, issue closure and real-KB work each keep
their own authority. No product code, tests or GitHub objects are changed by
this planning task.
