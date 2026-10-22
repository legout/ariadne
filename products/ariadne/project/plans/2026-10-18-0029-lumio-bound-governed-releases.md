# Implementation plan 0029: Git/local-first Lumio integration

## Approved execution revision 29 — optional S3 completion of #79/#80

**Owner approval, 2026-10-21:** “Ich genehmige Plan 0029 Revision 29 in bacbc32
einschließlich Ticket-Aktualisierung, isolierter Pi-Umsetzung und disposable
SeaweedFS 4.45 über Docker mit synthetischen Testdaten. Keine Integration, kein
Push oder Veröffentlichung.” Exact approved proposal:
`bacbc32cfb70ebb3b6e50228dcb56e446bd319c0`. Written Core r6 / producer navigation r4
amendments were approved with “Go ahead with the plan.” after proposal `b91057c`.
Older revisions below are history, not current execution instructions. Contract:
planning-contract v1; installed provenance unknown. Only the named isolated work,
current ticket sections and disposable environment below are authorized.

### Goal, sources and boundaries

Finish optional S3 Knowledge transport through the existing native SDK,
operator admission and public surfaces. Git/local remains the standard and
both products remain independently installable. Behavior belongs to
[Core spec0029 approved r6](../specs/2026-10-18-0029-lumio-bound-governed-releases.md)
and [producer spec0009 navigation r4](../../../lumio/project/specs/2026-10-18-0009-ariadne-context-profile.md),
under [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md) and producer
ADR-0030. Canonical tasks: [#79](https://github.com/legout/ariadne/issues/79)
(behavior and producer dependency), [#80](https://github.com/legout/ariadne/issues/80)
(public surfaces and qualification). Before dispatch, parent prepares and updates
their current task sections to this approved revision; retain historical evidence.
This proposed map must not be used alongside contradictory old ticket grants.

Inspected baseline: `main` = `6fb0455e3b24d153c8279bafc0ac13b39424fa64`.
No source/code/services changed since that inspection. Freeze the approved source
commit before dispatch; its concrete SHA belongs in parent run state and briefs,
not a self-referential placeholder in this file. Stop if main moved materially.

Capture: existing glossary terms suffice; no terminology changes. Native SDK,
private operational receipts and atomic-last Core activation are already accepted
architecture. No new ADR or service. Receipt synchronization/multi-host provisioning,
private app, Agent/Tau, ad-hoc/record queries and new technical profile kinds are
excluded. No software target integration, push, release/tag or issue closure.

### Ownership and host

Supervised, current verified BB local host; use its Pi bridge with physically
bound registered worktrees under `/home/volker/.local/state/worktrees/`.
One sequential Pi writer: `zai/glm-5.3/high`; independent read-only Pi reviewer:
`openai-codex/gpt-6.1-sol/high`. Exact installed model/thinking catalog and workspace
binding must be verified before creation; no alias, alternate host or fallback.
Current tool observations: uv0.13.3, CPython3.14, Docker server27.4.1. No Agent/Tau env.
The parent prepares run-owned environments; no worker dependency installation.
Children do not delegate, run memo or write shared memory. Parent owns oracle
inspection, failure dispositions, acceptance and candidate assembly.

### Canonical task ownership and sequence

| Order | Canonical task | Consumes / produces | Review boundary |
| --- | --- | --- | --- |
| 1 | [#79: SDK S3 navigation](https://github.com/legout/ariadne/issues/79) | Approved producer r4 → frozen SDK navigation contract, native V-SDK evidence and guidance | Immediate independent review before consumer |
| 2 | [#79: Core S3 admission/session](https://github.com/legout/ariadne/issues/79) | Accepted SDK → full native Core publication/admission and pinned-session journey, V-S3 | Final candidate review includes Core behavior |
| 3 | [#80: surfaces and qualification](https://github.com/legout/ariadne/issues/80) | Accepted producer + Core candidate → coherent public guidance, V-Core, exact installed identities | One final independent assembled review, settled SDK reused |

The current r29 sections of these two issues own exact task bodies/owned files;
the parent transfers the approved definitions verbatim before dispatch. This
plan owns shared order, readiness, validation budget and environment constraints.
Historical task definitions below refer to old local execution and are not a
second editable task store for r29.

### Assigned invocation budget and required checks

No baseline replay: use main `6fb0455`'s green CI39641879894/39641877252 and adapter
CI39641879950/39641877156 for unchanged shared layout, packaging and local evidence.
Changed SDK/Core runtime requires the following native postchecks, each once.
These are three planned pytest invocations, not hidden per-layer passes:

**V-SDK**, from `products/lumio`, source-bound qualified environment:

```sh
uv run --locked pytest -q -n 4
```

**V-S3**, from repo root, after accepted SDK + coherent Core implementation, against
only the separately approved disposable synthetic service:

```sh
uv run --locked pytest -q \
  integration/tests/lumio_s3_context.py \
  products/lumio/tests/test_onboarding_journey.py \
  products/lumio/packages/lumio-wiki/tests/*s3_compat.py \
  products/lumio/packages/lumio-lancedb/tests/*s3_compat.py
```

**V-Core**, from `products/ariadne/packages/ariadne-data`, exact accepted SDK and
Core candidate bound in the source qualification env; never the stale canonical
user `.venv`. The two explicit local modules and native suite are the existing
CI selection; the new S3 module already ran in V-S3, no duplicate journey:

```sh
$CORE_PY -m pytest -q \
  --ignore=tests/test_s3_lakehouse.py \
  --ignore=tests/test_s3_storage_access.py \
  --ignore=tests/test_s3_storage_profiles.py \
  "$CANDIDATE/integration/tests/lumio_metric_mvp.py" \
  "$CANDIDATE/integration/tests/lumio_local_context.py" tests
```

Reuse the root shared-only25-pass layout proof unless root test/config/manifest
inputs change; then stop to assign affected checks before execution. No `-n auto`.
Run native `uv lock --check`, `uv sync --locked` and component-configured Ruff on
changed trees, with logs. Do not regenerate dependencies or bump versions. Parent
prepares compatible run-owned environments from existing tooling/locked inputs;
missing tools/cache/runtime is a blocker, not silent provisioning of another stack.
Native builds/verifiers/walkthroughs above may spawn their documented subprocesses;
record/disclose actual commands rather than claiming only three commands total.

Any failed assigned invocation freezes that lane: preserve the true exit/log/JUnit
and investigate only its cause. No automatic retry, broader suites, new skips/xfails,
weakened oracles or relabeling an old failure. Parent may authorize one small
in-scope fix and one affected recheck per validation/review unit; unused green
checks are reused. One fix pass and one delta review; unresolved material findings
return to the owner. No new round from candidate assembly or publication.

### Explicit approved environment grant

One disposable SeaweedFS4.45 instance through the existing Docker27.4.1 runtime,
CI-pinned image
`chrislusf/seaweedfs@sha256:fc9f76fa993ad69966ffeb2f65d0318fcae39c6f8e20cf68ef7b3a5cb97769e5`
(cached arm64 image observed). Unique owned name and temporary private storage;
loopback-only unused S3 port, CI's synthetic bucket/labelled admin-secret test
credentials. Scrub inherited AWS/LUMIO/profile credential values and populate only
named synthetic test bindings. No real buckets, retained containers, production
credentials, new runtime, public listener, privileged mounts or unrelated service
restart. Stop/remove only this owned instance after its evidence consumers finish;
retain logs/artifacts. Worker cannot start/stop services; parent owns lifecycle.
The grant includes normal run-owned qualification environments/build installs,
not canonical user environments, global package upgrades or general host setup.

### Producer-first release boundary and completion

Current `.github/workflows/publish.yml` deliberately pairs published SDK0.4.1;
it must not silently substitute an unreleased workspace wheel. Leave its pin and
release triggers unchanged in this implementation. S3 source/installed candidate
qualification uses the exact newly built accepted SDK, and cannot be called a
published-pair proof. A separately authorized SDK release must precede a future
Core S3 release; only then may a separate release change pin the actual public
SDK URL/SHA and verify that public pair. No invented future version/artifact.

Completion is a reviewed, parent-accepted isolated source candidate, truthful
capability/docs/CI, exact wheels plus actual V-SDK/V-S3/V-Core evidence and honest
limits. Ticket closure and target integration/push remain separate decisions.
#76 remains the coordination parent, #18/#52 separate unrelated work. No work is
authorized before the current ticket amendments and source commit are frozen.
This owner-approved execution map grants only its named isolated work; integration,
push, publication and closure remain separately gated.

---

| | |
| :--- | :--- |
| **Status** | **Revision 28 — approved integration, push and cleanup, 2026-10-21.** Owner approved normal source integration/push and scoped cleanup for accepted Core2547c8a and SDK26a633b. Earlier isolation restrictions and exhausted test budgets remain historical; no package release or new behavior is authorized. |
| **Owner direction** | 2026-10-20: “S3 Anbindung ist für Ariadne zweitrangig. Der bevorzugte Weg bleibt git repo mit lokalem sync.” This approves the priority used for this proposal, not new SDK interfaces or capability expansion. |
| **Goal** | Make the shared Git Content Repository plus a local checkout the normal operator path, then expand useful local knowledge/analytics capabilities without weakening exact admission or standalone behavior. S3 is optional later work, not a prerequisite. |
| **Behavioral sources** | [Spec0029 approved r2](../specs/2026-10-18-0029-lumio-bound-governed-releases.md), especially §§2–6 and preserved full-target AC1–AC9; [ADR0026](../adr/0026-lumio-sdk-bound-governed-releases.md). Companion: `legout/lumio-wiki:project/specs/2026-10-18-0009-ariadne-context-profile.md` r2 / ADR0030. The r2 MVP refusal boundary remains authoritative until the corresponding source amendments are approved. |
| **Starting artifacts** | Published `ariadne-data==0.5.0`, Core `a9dd5f8ff9ae15b55268cad6dad0841caf0057fa`; published `lumio-wiki==0.3.0` / `lumio-lancedb==0.3.0`, producer `a5127c753a6343629ba3fc7adfa44441c8f82baf`. Use exact accepted successors in later handoffs, never floating `main`. |
| **Tracker** | [#76](https://github.com/legout/ariadne/issues/76): full epic; [#79](https://github.com/legout/ariadne/issues/79): consumer continuation; [#80](https://github.com/legout/ariadne/issues/80): remaining adapters/guidance/qualification. [#81](https://github.com/legout/ariadne/issues/81) and [Lumio #2](https://github.com/legout/lumio-wiki/issues/2) have delivered released code but remain open; no closure is authorized here. Their old ticket text must be reconciled before new execution. |
| **Capture / readiness** | Existing glossary terms suffice. Git/local preference changes sequencing, not ADR0026's architecture; no new ADR is proposed. New operation support and the additive navigation API require written Core/producer source amendments before their writers start. Contract: planning-contract v1; installed catalog provenance unknown. |

## Current authorization — integrate accepted local candidates (revision28)

Owner explicitly requested on 2026-10-21: “Integriere. Commi. Push. Clean up”.
This authorizes local merge commits, normal pushes of the two repository main
branches and cleanup of the completed owned Q1/G2/T2 environments/worktrees.
Exact accepted inputs: Core2547c8a198488dfaf510d17319484cd779232a4d,
SDK26a633b4399ddd5e9d6cad2292cbb317944ead90. The final independent candidate
review's sole P2 was fixed by89f5568, its RED/POST and independent delta passed.
All historical failures remain evidence; no new implementation or test budget.

Use merge-worktree with isolated temporary integration worktrees and explicit
source branches. Preserve reviewed trees; only this authorization text is new.
Reuse still-applicable tests/reviews and exact wheel/member proof, then verify
actual merge commits, product/resource bytes and remote refs freshly. Push
normally, never force. Retain source/result refs, logs, wheel artifacts and
failed/uncertain or unrelated work. Cleanup only released owned resources.
Do not run a numerical journey again for a merge. Normal push-triggered native
CI remains repository-owned and is reported honestly.

This is software-source integration, not a package release: no tags, version
bump, PyPI publication, Agent/Tau, service/private-KB operation or expanded
S3/ad-hoc capability. The open full-target issues are not closed by this grant.
No new behavior, vocabulary or ADR; spec0029r5 and producer sources unchanged.

## Prior approved execution — citation containment (revision27)

After the independent final review, the parent confirmed one remaining P2:
the new KB citation branch classifies escaping relative paths as bundle
evidence without checking the resolved Knowledge subtree boundary. The owner
replied “Freigabe” to the concrete proposed product patch27b5294e, test
patche41bbfe4, one RED/POST of the existing T2 node, an updated Core wheel and
installed pairing proof, and one independent delta review. No integration or
publication. This is an explicit additional bounded allowance; historical
failures/budgets remain unchanged.

Use frozen Core candidatef6e8e20aabdda6c839f8c6859fed631f40977a91 and unchanged
SDK26a633b4399ddd5e9d6cad2292cbb317944ead90. Product patch SHA256
`27b5294ea0007a0888d4a15fd93f504494c3c0ae18862429afbaac2f271b8a0e`
adds resolved containment before the existing KB bundle classification; all
other citation semantics remain unchanged. Test patch SHA256
`e41bbfe4e01ff25a5a4e46ff5c92e308e03970e660fe37cb98bad5d99f8e96cf`
extends the existing third negative validation with an authored real document
outside the captured release and requires its escaping citation to be refused.
No fourth validation, new test node, mock, weakened assertion or new authority.

Same registered sequential BB Pi GLM5.3/high writer, then the existing
Sol6.1/high reviewer for delta-only review. Parent inspects the expected RED
before granting the exact product patch and one same-node POST. Failure stops;
no automatic retry or further repair. Parent builds one updated Core wheel,
checks the affected source/archive/installed pairing outside the checkouts
with unchanged SDK wheel, and reuses unaffected G/status, native compatibility,
Q3, optional base-import, SDK/CI/MCP/adapter and numerical proof. Do not replay
numerical or Core admission journeys merely for packaging.

Behavior remains spec0029r5 §1.5 and native citation/containment rules, especially
spec0011 §5. No new vocabulary, ADR, dependency, interface, schema or SDK change.
Canonical #79 owns the bounded correction; #80 owns affected installed proof.
Parent records exact source/ticket snapshots before dispatch. Capture:
planning-contract v1, installed provenance unknown. No target integration,
push, release/publication, issue closure, service/private-source or cleanup.

## Prior approved execution — test-round correction (revision26)

Owner explicitly approved: “Ich genehmige den vorbereiteten Test-Patch
6c0d6aee und einen Recheck des fehlgeschlagenen T2-Knotens; anschließend die
geplante Q1-Qualifikation und unabhängige Review. Keine Integration oder
Veröffentlichung.”

The r25 RED reproduced the Policy resource defect. Its POST preserves six
passing compatibility nodes but fails the journey's optional last leg at the
native three-round validation limit. This is a fixture-ordering defect; the
limit and assertions remain unchanged. Apply only prepared test patch SHA256
`6c0d6aee350171917ca7b3e476eb06291324681973a1e3584eae98ec89378a1b`:
combine the Policy mutation and hidden-reference edit before the existing
third validation and require both diagnostic families from that result.
Run the failed T2 node once; reuse the six unchanged compatibility passes.
No new product repair or retry is authorized. Preserve r25 failed evidence.
Then complete the previously assigned Q1 wheel/Q/installed proof and one
independent candidate review. All prior behavior sources, roles, ownership,
non-goals and integration/publication restrictions remain unchanged.
Capture: no new vocabulary, ADR or behavior; planning-contract v1,
installed provenance unknown. Canonical #79/#80 are reconciled before dispatch.

## Prior approved execution — bounded F1/F2 remainder (revision25)

**Owner approval — 2026-10-20:** “Ich genehmige eine zusätzliche begrenzte
F1/F2-Korrekturrunde auf 4f6f182 gemäß dem vorbereiteten Patch b236a9da:
ein gezielter Policy-Beleg-RED-Test, ein POST-Recheck der sieben T2-Tests,
danach die geplante Q1-Qualifikation und unabhängige Review.
Keine Integration oder Veröffentlichung.”

Behavior remains approved spec0029r5 §1.5 and native specs0010/0011;
no vocabulary, ADR, SDK/API, output schema or dependency change is assigned.
Canonical [#79](https://github.com/legout/ariadne/issues/79) owns the bounded
repair/test body; [#80](https://github.com/legout/ariadne/issues/80) owns the
remaining installed qualification. Parent reconciles their exact snapshots
before dispatch. Capture: planning-contract v1, installed provenance unknown.

Frozen Core input4f6f1826ab93cae7d82ce623e1772e62d3e0d6ee remains unaccepted:
F1's Core parser still executes before the KB branch; F2 hashes a knowledge
Policy but stores the unqualified path consumed by verification. The prepared
product patch has SHA256
`b236a9da101f392f74c167bb407aed8de0437c274d11435ba0472447963c746e`.
SDK26a633b4399ddd5e9d6cad2292cbb317944ead90 and its wheel stay unchanged.

Use the same isolated registered BB Pi GLM5.3/high writer and one final
read-only Sol6.1/high reviewer. Parent inspects the authored Policy fixture
before execution. Exactly one focused T2 Policy RED before the product patch,
then one POST containing the same seven assigned T2 nodes. These are two
additional invocations, not replacements for the prior green baseline4/G17/
T7/correction7 results. Failure stops the affected lane; no repair/retry or
wider suite follows automatically. Preserve original result refs and logs.

After the repair, complete the previously reserved Q invocation (the V3 pair
and installed optional-MCP skill check), one final Core wheel, Core-only
optional-import check, paired installed proof using the unchanged SDK wheel,
and the one independent candidate review. Reuse unchanged producer CI,
SDK/native wheel/MCP/adapter and numerical evidence. No new matrix or
packaging-only numerical replay. No further automatic correction round.
Freeze committed candidates and honest evidence; pause before target
integration, push, release/publication, issue closure or cleanup.

## Prior approved execution — G2/T2 and affected Q1 qualification (revision24)

**Owner request:** 2026-10-20, “Implementiere den Rest von #80”. This requests
completion. After reviewing the concrete written specification/plan, owner
answered “Freigabe”. This approves spec0029r5 §§1.4–1.5, plan24, isolated
implementation and canonical #79/#80 reconciliation. The prior Q1 checklist
is complete; these are the newly activated local prerequisites. No package
release or full-target S3 completion follows.

**Exact inputs:** accepted isolated Core
`ae3a4f6679844d30267fd67985d756803901b5e1`, SDK
`26a633b4399ddd5e9d6cad2292cbb317944ead90`. Core main remains7e8d84d;
SDK main remainsb1d63b3. Start the next isolated candidates from those accepted
Q1 descendants; do not merge them into main to make implementation possible.
Existing producer profile/navigation interfaces suffice; no producer writer or
new dependency is assigned. Scope-safe SDK identity, native Core receipts and
confirmation remain the consumed contracts. Use spec0010/0011 and spec0029
approved §§2–6; approved §§1.4–1.5 own only the new continuation behavior.

**Capture:** existing glossary terms and ADR0026/0030 suffice; no new term or
ADR. No service/credential/architecture change. Owner approved this local continuation; Core-S3 acceptance remains separate. Contract planning-contract v1, provenance unknown.
Read-only source investigation found all required SDK metadata/identity seams.
Implementation choices (in-memory native input adaptation and reuse of the
existing proposal evidence store) do not create new authority or schema.

### Canonical execution and assurance

[#79](https://github.com/legout/ariadne/issues/79) owns G2/T2 task bodies,
owned surfaces and native baseline/G/T checks;
[#80](https://github.com/legout/ariadne/issues/80) owns affected Q1 qualification,
installed proof and Q. Parent reconciles both before dispatch; exact issue
snapshots/digests and source/SDK identities are in the existing parent run.
The reviewed proposal07439a4 preserves the approved detailed decomposition;
these ticket bodies are now the executable copy, not a parallel task ledger.

Four pytest invocations once each: native Reference/confirmation baseline,
G2 + existing status checks, T2 + affected native/strict-kind/catalog checks,
Q1 discovery/installed-skill checks. No hidden collection/broader suites.
New tests use independent authored oracles inspected before execution.
Necessary native inspection SQL is synthetic and explicit; the changed legacy
capability test constructs one governed answer, disclosed rather than hidden.
Unchanged producer/native numerical/S3/wheel/MCP evidence is reused.
One final independent Pi Sol/high candidate review; at most one parent-authorized
small fix pass and one affected recheck/delta review, no automatic third round.

Use BB Pi GLM5.3/high, one sequential isolated registered Core writer under
shared XDG worktrees. Accepted SDK26a633b remains unchanged. G2 can be
parent-inspected before T2; final high-risk review covers new G2/T2 and assembled
qualification effects without re-reviewing settled Q2/L2/A2/Q1 findings.

Completion: frozen clean candidate, exact final wheel/receipt/confirmation
identities, actual checks and explicit reuse/limits, independent review.
Pause before main integration, push, release, issue closure or cleanup.
No service, production data/private KB, Agent/Tau or Core S3 is assigned.

## Historical execution — approved Q1 for the delivered local scope

**Owner approval — 2026-10-20:** after reviewing this exact scoped plan,
owner answered “Ok. Freigabe. Mach weiter mit Q1”. This approves local-scope
Q1 execution, canonical #80 update and the named Pi roles. It grants no new
capability, service, target integration, push, release or issue closure.
Original full-target requirements remain open. The approval draft is preserved
unchanged in the parent run storage; #80 owns the executable task decomposition.

**Sources / inputs:** spec0029 r4 §§1.1–1.3 and §§2–6, ADR0026; producer
spec0009 navigation r3 and ADR0030. Frozen starting commits: Ariadne
`7e8d84d0820101719f2b43dd74b8a65dd963fa2e`, Lumio
`b1d63b3f01c297296aeeb53f7dfef7acafeb0349`. Their accepted behavioral
candidates are Core36aee079 and SDK86db9f1. No floating-main runtime pin.
Capture: no new vocabulary, architectural decision or supported behavior;
planning-contract v1, installed catalog provenance unknown. The owner approved qualification of this local scope instead of original full-A1.

**Deliverable:** coherent public guidance and actual installed artifact proof
for the delivered Metric/Policy operations, multi-metric context, approved live
catalog, and source-free scoped SDK navigation. Preserve exact identities,
consent, visibility, role exclusions, refusals, citations, limits and standalone
optional-SDK behavior. Git/local sync is the normal operator path; checkout
sync never activates a release. Do not add G2 status behavior, technical
Reference/resolve_term, ad-hoc or Core S3 capability, Agent/Tau, numerical replay,
full-ODCS or production/service claims. This slice alone cannot close full #80.

**Canonical execution:** [GitHub #80](https://github.com/legout/ariadne/issues/80)
owns Q1 task bodies, owned surfaces and validation scope/budget, reconciled to
this approval before dispatch. The parent run state records the issue-body
snapshot/digest and exact frozen candidate identities. Historical drafts below
are not current grants. One writer per isolated repository; worker
`zai/glm-5.3/high`, final reviewer `openai-codex/gpt-6.1-sol/high` through BB Pi.

**Completion:** two frozen clean candidate refs, exact wheel/build identities,
actual installed-origin/profile-resource outputs, applied/reused gate evidence
with limits, one independent final review, and honest remaining full-target
scope. Stop before integration, push, release/publication, issue closure or
cleanup unless separately authorized. The prior merge/cleanup authorization
covered the previous candidates, not this new qualification slice.

## Integration and cleanup — owner-authorized, 2026-10-20

Owner explicitly requested: “merge. Commit. Push. Clean up.” This authorized
local merge commits, normal pushes of both paired repository main branches,
and cleanup of this run's owned resources. It did not request a package release
or issue closure.

- [Ariadne integration e8ae748](https://github.com/legout/ariadne/commit/e8ae74837414ecb8b5c805d046697c52f2836f35)
  contains accepted Q2/A2 source36aee079 and accepted plan outcomea527dbf.
  All product/test files are identical to the reviewed candidate; only the
  latest accepted execution-plan bytes differ from its tree.
- [Lumio integration b1d63b3](https://github.com/legout/lumio-wiki/commit/b1d63b3f01c297296aeeb53f7dfef7acafeb0349)
  has exactly the accepted SDK86db9f1 tree2996ef6.
- Existing focused and independent-review evidence was reused without duplicate
  local pytest calls. Remote refs and actual merge/tree identities were checked.
- Producer [CI39469980783](https://github.com/legout/lumio-wiki/actions/runs/39469980783)
  passed lock/sync/Ruff, full suite with four workers (1651 passed,9 skipped),
  onboarding/S3-compatible selection (40 passed,1 skipped), and isolated wiki
  wheel verification. The separate
  [LanceDB wheel run39469980838](https://github.com/legout/lumio-wiki/actions/runs/39469980838)
  also passed. Existing skips remain disclosed; no test/CI configuration changed.
- Eighteen owned worktrees and three disposable verification environments were
  removed; eleven finished worktree child threads were archived. Unrelated
  worktrees and the stopped shared-checkout scout were retained. Source/result
  refs, run logs, the old main plan draft and six formatter-only states survive
  in archive commits/byte snapshots. Only the two ephemeral integration branches
  were deleted. Details remain in the existing run state.

Q1's paired installed Core/SDK proof and public guidance remain unperformed;
the producer wheel checks are not that paired proof. Core's full tag-triggered
release CI was not run, and package versions/releases are unchanged. Integrated
source still requires exact build matching and fresh native admission; merging
a Git branch does not mutate an existing Bound Release or publish a package.

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
reader behavior. Reuse one verified snapshot per operation. A private extraction of the
existing inline verification pipeline is allowed to avoid an unchecked second
resolution. Preserve its gate order, public reader shapes, keyword arguments
and refusal semantics. Pin current local and S3 reader behavior before that
refactor with exactly the existing two journey nodes, serially, once:

```sh
$SDK_PY -m pytest -q packages/lumio-wiki/tests/test_ariadne_context.py::test_ariadne_context_journey packages/lumio-wiki/tests/test_ariadne_context.py::test_s3_published_context_journey
```

This is the producer's existing in-memory S3 journey, not Core S3 support or a
new service. Add one focused native publication/navigation test with independently
authored pages/coordinates and scope/version/mismatch cases. Its new-function
imports remain inside the new test so existing baseline nodes collect before
implementation. First return prepared test data for parent static schema/oracle
inspection. After baseline passes, implement and run the existing full profile
module once (its changed verification pipeline invalidates the baseline proof):

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

### A2 candidate disposition — correction completed and accepted, 2026-10-20

L2 is accepted at `86db9f14909d095e4fdad270c6ea6d36c326b86b`.
Initial A2 candidate `2375530b18a8b08401b959dff1cdc5bda4aa7ad7` (tree
`3125f639ab439dd0718f2f1a3667fae540e30f5a`) remains the preserved **fix-first**
result, superseded by the accepted correction below.
The one independent candidate review (`thr_9eyrt3e2qz`, Pi Sol/high) identified
two reachable violations of existing response guarantees, not new behavior:

- `discover` catches a pages `QueryResultError` as `ValueError`, replacing
  required oversized page content with an unavailable group. Propagate budget
  refusals so CLI `search` and MCP `discover` refuse the whole operation.
- Source-free MCP navigation bypasses the existing transport-refusal
  representability preflight. Validate the configured `mcp_response_bytes`
  against actual refusal envelopes without constructing QueryRuntime; reject
  unusably small host ceilings before navigation, rather than returning an
  oversized refusal. Reuse the existing refusal forms and wire measurement.

Parent accepted both findings. Owner approved the additional correction below in the current BB conversation on 2026-10-20; that bounded cycle is now complete.
The original assigned A2 invocation remains exit1 (12 passes, one mistaken
bare-dict structured-output test oracle). The worker corrected that oracle,
completed late parent static-gap requests, repeated all13 nodes and committed
without the required failure disposition. This was not authorized; the second
exit0 is observed evidence, never an authorized replacement. Parent also
acknowledges approving the incorrect bare-dict assumption. Installed MCP2.2
source independently confirms the corrected strict form; no product output
flags were changed. Preserve both logs and the committed candidate. The spent
correction/recheck is not reset at review or candidate assembly.

**Owner approval — 2026-10-20:** “Ich genehmige die zusätzliche A2-Korrekturrunde gemäß Planrevision 20, Commit 84d2fe2: beide Budgetfehler, gezielter RED/POST-Test und eine Delta-Review; keine Integration oder Veröffentlichung.” This authorizes one
additional bounded A2 correction cycle for exactly these two findings. Use one
fresh registered Pi `zai/glm-5.3/high` writer based on frozen2375530, one
read-only Pi `openai-codex/gpt-6.1-sol/high` delta reviewer, and the unchanged
accepted producer86db. Owned files: `src/ariadne/discovery.py`, necessary
`src/ariadne/serve.py`, and the existing focused navigation scenario in
`tests/lumio_local_context.py`. No new parser/framework, source runtime,
capabilities, dependencies, metadata/version changes or producer edits.

First prepare the smallest regression extension to the existing navigation
journey and return its independently justified oracle for parent static review:
required page output larger than the Core ceiling must refuse through actual
CLI search and MCP discover; an MCP-only ceiling below the existing refusal
representations must be rejected before navigation. Distinguish configuration
rejection from an oversized tool-result refusal. Reuse existing native limit
semantics and real wire measurement, never weaken old assertions. One serial
RED invocation of only the existing A2 node against unchanged product, then
freeze for parent disposition. If RED matches the named failures, one product
fix pass and one same-node POST invocation; targeted Ruff over touched files.
No rerun of the12 unaffected green nodes, Q2 numerical journey, full suites,
collection/probes, installs or service setup. A failure stops; no automatic
retry. One delta review covers the fix and affected integration only. Any
remaining material finding returns to the owner; no third round.

Commit a clean isolated result and preserve all refs/evidence. No target
integration, push, issue changes, release or cleanup. T2 remains proposed;
full A1/Q1 and installed-artifact qualification are not completed by this slice.

#### Accepted isolated outcome — 2026-10-20

Parent **accepts A2** at `36aee079359c54f8bd5537e604044b2a55587e37`, tree
`cb20d25c466b7a4f975788d1a2eb862115eebb60`, after inspecting the exact committed
delta and one independent Pi Sol/high delta **PASS** (`thr_27addvkgrx`).
Frozen ref: `refs/heads/orchestrator/issue79-local-20261020/result/a2/budget-a1`.
The clean isolated candidate is `a2-candidate-a1` under the recorded shared root.
Paired accepted SDK remains `86db9f14909d095e4fdad270c6ea6d36c326b86b`.

One focused RED reproduced CLI/MCP partial success on oversized required pages
and a1313-byte refusal under a1-byte MCP ceiling. One same-node POST passed
with no errors, failures or skips. The test was byte-identical between RED,
POST and the result commit; targeted Ruff was clean. Product changes only
propagate QueryResultError past availability handling and preflight actual
refusal envelopes before all four source-free navigation handlers. No runtime,
Source, output-schema or capability expansion was introduced by this correction.
The historical failed/unauthorized invocations remain separately recorded;
they have not been relabeled by this acceptance. Q2 query code, metric context
and independent150/2 numerical scenario remain unchanged and their proof reused.

Exact reports, logs, JUnit outputs, hashes, preserved formatter-only dirt and
source/environment bindings are in the existing
`issue79-local-a1-20261020/run.json` run state. No new validation was run for
candidate assembly. This is source-based proof with explicit `.pth` bindings,
not installed-wheel or full Core/Lumio/Q1 qualification. T2 stays proposed;
no target integration, push, issue changes, publication or cleanup occurred.

### L2 F1 disposition — bounded correction, 2026-10-20

Initial independent review of frozen producer018a6962 is **fix-first**, solely
for metadata-only search returning unrelated body evidence when valid YAML
escapes mean parsed matches have no literal canonical substring. Parent accepts
F1 under the approved real-passage requirement; scope and API stay unchanged.
One isolated Pi worker correction owns the same two L2 files. Extend the existing
focused journey with an escaped tag and misleading unrelated frontmatter text,
keeping semantic data and independently authored line/section oracles stable.
First inspect the prepared literal change statically. Run that one navigation
node once against unchanged product code to reproduce F1, then freeze for parent
disposition. After the expected failure is confirmed, authorize one product fix
and one recheck of that same node. No other green tests repeat; preserve baseline2
and unaffected post13 evidence. Targeted Ruff applies to changed files. One delta
review covers F1 and the correction only; unresolved findings go to the owner.
This exact red/post pair replaces no other task's budget and grants no broader
suite, weaker assertion, additional fix round or producer integration.

### L2 CRLF correction — additional owner-approved round, 2026-10-20

Owner answered “Go ahead with the plan” to the concrete remaining CRLF defect
and an additional bounded correction, focused red/post pair and one delta review,
followed by the already approved A2 continuation after L2 acceptance. This is
new explicit authority, not a reset of the exhausted F1 round. Frozen7e7ca6c
and all earlier refs/evidence remain unchanged and unaccepted as historical results.

One fresh isolated Pi GLM5.3/high worker owns only the same producer module and
existing navigation test. Preserve the escaped-tag/distractor regression; extend
the same native publication journey with canonical CRLF text and an independently
authored multiline summary-only match. Parent statically inspects its raw literal
and coordinates before one focused red invocation. After the expected failure,
parent grants one correction preserving original source spans/line endings and
one same-node post-check. No broader suite, new dependency, ranking/verifier
rewrite or extra publication matrix. Targeted Ruff covers both files. One
Sol6.1/high delta review covers7e7ca6c..new result and the text preservation it
changes; earlier settled findings stay settled. On pass accept L2 and resume A2
under its original assigned check/review budget. Failure or unresolved review
returns to owner without another automatic round. No target integration, push,
issue edits, release, service setup or cleanup is authorized.

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
