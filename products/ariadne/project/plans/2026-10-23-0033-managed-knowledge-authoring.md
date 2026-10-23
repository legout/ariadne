# Plan 0033: Managed knowledge authoring and integrated admission

Execution authority — 2026-10-23: after receiving these exact plans, the owner
said “Go ahead with the plan.” This approves this decomposition and supervised
isolated implementation in dependency order. Earlier proposed/no-implementation
status below records planning history and is superseded only for this execution
scope. No target integration, push, PR publication, release or production access.
Harness human confirmations and fixture-remote/service selection remain required
when their planned steps are reached; never fabricate them.

Status: proposed implementation plan, revision 1. Date: 2026-10-23.

## Goal, sources and authority

Deliver [approved spec0033 revision 1](../specs/2026-10-23-0033-managed-knowledge-authoring.md)
through the existing external skill/CLI/Git and overall admission routes.
The owner explicitly approved that specification, the scoped
[ADR-0026 amendment](../adr/0026-lumio-sdk-bound-governed-releases.md) and
[Lumio spec0010 §2.1](../../../lumio/project/specs/2026-10-23-0010-external-agent-authoring-journey.md#21-shared-private-source-configuration),
then requested this plan and reconciliation of Lumio plan0010 with **do not
start implementation**. This plan grants no execution, ticket publication,
service startup, integration, push, PR creation or software release.

Capture: existing scoped glossaries suffice; private configuration is not a
new domain entity. ADR-0026 preserves direct optional SDK consumption and
Core-last activation; no new ADR. No unresolved behavior decision blocks
planning. Exact interfaces below are proposed plan details for approval.
Planning-contract version 1; installed skill catalog revision unknown.
Inspected source baseline `dcc95a9`; documents are currently uncommitted.
Before execution, freeze the approved sources and refresh source correspondence
if that baseline has changed. No runtime verification is claimed here.

## Ownership and sequence

[Lumio plan0010 revision 3](../../../lumio/project/plans/2026-10-23-0010-external-agent-authoring-journey.md)
owns JP and J0–J6: private profile, bootstrap, extraction/candidate, knowledge
review, manual bundle, exchange, setup and standalone qualification. Do not
copy its task bodies or transfer implementation into Core.

Default sequence: **Lumio JP → J0 → J1 → J2 → J3 → J4 → J5 → J6 → Ariadne
A0 → A1 → A2 → A3**. The minimum interface dependencies are JP → A1,
J2 → A2 and all producer delivery → A3. Sequential delivery avoids competing
writers and premature coupling; no parallel execution is planned. A0 is
SDK-independent but shares Core setup/skill surfaces with later slices.

At execution handoff follow root AGENTS and orchestrate-implementation:
verified Pi host/roles, exact model/thinking preflight, one writer per isolated
registered worktree under `${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/`,
committed result handoffs and supervised delivery. Do not create a second
execution procedure here. One authorized fix pass and delta-only recheck per
review; unresolved findings return to the owner. No provider/host fallback.

Python 3.14, existing Core dependencies and optional Lumio SDK. No new mandatory
package or shared Git library. Existing Core data-source profiles, approval,
validation/build evidence, support revisions and publication destination
selection remain authoritative. No MCP admission/authoring extension.

## Interfaces frozen by plan approval

### Source configuration and overall admission (A1)

Consume `load_private_profile`, `resolve_private_profile` and
`ResolvedPrivateSources` exactly as defined in Lumio plan0010 JP. No Core copy
of the JSON parser, transport adapter or credential resolver.

- `ariadne-admit` gains `--context-private-profile <absolute-file>` on both
  preview and confirm. Existing destination, storage-profile, revision,
  reviewed-digest, visibility and overall-digest arguments retain their meanings.
  Reject a private profile on standalone admission; missing selection with
  managed knowledge remains a blocker, never an implicit environment lookup.
- `admission.overall_review(..., private_profile=None)` and
  `admission.admit_revision(..., private_profile=None)` receive the explicit
  path as a keyword-only argument. Resolve requested `registry` and `artifacts`
  in the operator's environment, not from serialized data supplied as a review.
- `lumio_context.prepare_release(..., source_context=None)` and
  `publish_and_verify(preview, *, source_context=None)` receive the resolved
  runtime object. They pass its same registry/store/retention into native
  Lumio calls. During confirmation, resolve once under the existing admission
  locking/check flow, recompute the preview with that object and pass it onward;
  never reconstruct different clients between confirmation and publication.

Profile-backed composite preview adds private `source_configuration` with
`schema_version: 1`, the producer's effective `binding` and `binding_digest`.
Its existing composite digest covers this field. The Bound Release manifest
adds `source_admission: {schema_version: 1, binding_digest, retention}` only for
profile-backed admission; this marker also participates in its manifest digest.
Raw private configuration remains in operator review material, never in the
published knowledge, reader result, PR or authored selector. Store only the
safe marker in the immutable runtime binding. No profile path is a runtime
reader dependency. Legacy absence means no profile-backed admission claim;
do not rewrite legacy bytes/digests or change query support revisions.

On confirm compare re-resolved binding and freshly recomputed native/overall
review, including required-original coverage and existing current-state/build
checks. Credential values are excluded; same-target credential rotation is
allowed if access still succeeds. Exchange-only changes are irrelevant to
publication. Preserve current private receipt location and failure reporting.
Runtime marker integrity is verified against the admission/manifest digest;
reading a release must not reopen or resolve the profile to verify it.

### Whole-contribution review (A2)

Add external CLI operations to `ariadne-authoring`, without exposing them through
MCP or changing native `review`/admission digest meanings:

- `contribution-review --project <root> --proposal <id> --base <full-commit>
  [--context-private-profile <file>]` returns one JSON review.
- `contribution-check --project <root> --proposal <id> --review <private-json>
  --revision <full-commit>` verifies the submitted commit and returns one JSON
  result. Neither operation approves, commits, pushes or admits.
- Public Core helpers in `contribution_review.py`:
  `review_contribution(project, proposal, *, base_revision, private_profile=None)`
  and `check_contribution_commit(project, proposal, review, revision)`.

The selected submission snapshot is the existing proposal worktree's staged
Git tree. The agent stages the intended paths using native Git before review.
Report unstaged/untracked work as excluded; a later staged addition invalidates
review. Use temporary materialization and existing static validation against
that captured tree, never silently validate different worktree bytes or open
an unapproved database. Reuse existing Core change/body/validation disclosure
and Lumio `review_knowledge_changes(..., candidate_tree=<captured-tree>)`.
The producer result covers only knowledge; Core owns the complete Git inventory.

The v1 record binds proposal identity, selected full base, captured HEAD,
complete candidate tree, every changed path/blob/mode, Core/knowledge semantic
review, validation/pending status, validator identities and `review_digest`.
Knowledge uses bodies and semantic metadata changes; Core uses real authored
expression/contract/declaration diffs. Unknown file types must be explicitly
shown, or submission blocks until excluded. Source configuration is private;
no original bytes or credential values appear in review.

After human submission confirmation, compare the real commit's tree and base
ancestry to the captured facts. A new commit must have the captured HEAD as
its parent; an already existing candidate commit is allowed only when its
identity equals the captured HEAD and its tree matches the reviewed snapshot.
Rebases, hook edits and changed staged contents require renewed review. Existing
internal candidate commits remain native authoring history; they are not human
publication or submission consent. Reconcile through the existing Core route
before subsequent validation/admission, never rewrite proposal records by hand.
Pending live validation permits contribution, but never admission readiness.

### Setup (A0, A3)

Add Core-local `git_connection.check_git_connection(project, *, remote=None)`
and `ariadne git-check --project <root> [--remote <name>]`. Its JSON report
separates identity, repository state, read authentication, push capability and
PR-tool readiness. Do not infer write access from read success. Setup uses the
same helper; no Lumio import. Report safe outcomes without token-bearing URLs.

Integrated setup later accepts `--context-private-profile <file>`, uses the
public SDK's declaration-only inspection and guides explicit Lumio setup for
creation/edits. It does not infer a profile, copy it into Git, import a baseline
silently or introduce a second writer for the shared format. First guided
managed use requires required retention; legacy no-profile setup stays intact.

## A0 — Diagnose Git connectivity in Core setup

- [ ] Add the read-only helper, CLI route and existing setup integration above.
- [ ] Extend `docs/how-to/git-authoring.md` with SSH agent/credential-helper
  guidance, safe remediation and the distinction between read and write access.

Owned files under `products/ariadne/packages/ariadne-data/`:
`src/ariadne/git_connection.py` (new), `cli.py`, `setup.py`,
`tests/test_setup.py`; documentation under `products/ariadne/docs/`.
Prerequisite: plan and execution approval; no SDK dependency. Produces a useful
standalone check consumed by A3. Source: spec0033 §6/AC8.

Validation VA0: high risk credential-facing diagnostics, `new-test`.
`test_git_connection_reports_read_without_write_or_mutation` in `test_setup.py`
uses a disposable local remote and a supplied failed-auth diagnostic with a
secret sentinel. Independent expectations: read can succeed while push stays
unverified; diagnostic output excludes the sentinel; Git config/index/refs are
unchanged. Reuse existing setup no-mutation and standalone-wheel checks.
Candidate review covers this boundary; no separate documentation review.
Completion: Core-only installed check works without SDK or credential changes.

## A1 — Admit managed knowledge with the selected private profile

- [ ] Thread the explicit selection through CLI, preview, locked confirmation,
  native publication and safe binding marker; preserve no-profile legacy paths.
- [ ] Recompute binding/retention before side effects; keep native outcome and
  immutable residue reporting and Core-last activation intact.
- [ ] Verify reader marker integrity without introducing private-source runtime
  dependencies, preserving current manifest/build checks.

Owned Core files: `src/ariadne/admission.py`, `lumio_context.py`, and only the
necessary snapshot/descriptor compatibility seams. Add
`integration/tests/lumio_managed_sources.py`. Update existing explicit same-commit
pair test selection in `.github/workflows/ci.yml` so this file actually runs.
Prerequisites: accepted JP API, existing paired candidate environment, A0 in the
default sequence. Produces the admission seam consumed by A3; A2 never replaces
its native reviewed-digest or grants operator authority. Source: §§2–3/5,
AC1/AC4–7.

Validation VA1: high risk public consent/credential boundary, `new-test`.
`test_managed_admission_binds_profile_and_retention` uses a hand-authored managed
base plus new document and distinct local stores. It first blocks on a known
missing baseline original; after verified retention, it previews then switches
the store and must refuse without pointer mutation. A fresh matching review
admits and a source-free read succeeds after profile/registry/raw-store access
is made unavailable. Assert exact fixture body/source digests and unchanged
prior descriptor on refusal, not implementation-computed expected outputs.
S3 endpoint/credential rotation behavior is covered by VP and the A3 S3 leg.
Reuse existing composite-consent, Source Approval and native partial-publication
failure cases; if a touched path invalidates those results, rerun those nodes.
Immediate review before A3 consumes this authority boundary; one fix/delta cycle.
Completion: CLI and Python entry points admit managed local knowledge using the
same reviewed canonical source targets, with no new reader access requirement.

## A2 — Review and check a complete native Git contribution

- [ ] Add the composed review/check helpers and external CLI operations above,
  keeping native Core review/validation results and admission semantics intact.
- [ ] Expose truthful pending live checks and unknown-file blockers; preserve
  full-tree identity through native commit, hook and reconcile transitions.
- [ ] Update Core skill instructions to coordinate Lumio knowledge operations,
  native staging, human review, commit verification and configured submission.

Owned files: new Core `src/ariadne/contribution_review.py`,
`authoring_cli.py`, narrow reusable seams in `authoring.py`,
`src/ariadne/skill_assets/SKILL.md`; add
`integration/tests/lumio_contribution_review.py` to the existing pair CI selection.
Prerequisites: accepted Lumio J2 composition API; A1 in default order.
Consumes `KnowledgeChangeReview`; produces complete contribution review/check,
not an admission receipt. Source: §4, AC2/AC3/AC6.

Validation VA2: high risk human-consent public contract, `new-test`.
`test_contribution_review_covers_document_and_metric` starts with a synthetic
Policy body and a manually authored metric filter change. The fixed expected
review includes both, plus frontmatter-only meaning changes without raw YAML.
Parameterize a matching commit, added staged file and a real modifying commit
hook: only the reviewed tree passes. Live access is unavailable and must remain
pending without any source opening. Reuse native review pagination/digest checks
rather than another per-method matrix. Review before the final harness consumes
this composite submission boundary. Completion: an agent cannot use body-only
consent to submit an undisclosed calculation or other staged change.

## A3 — Guide and qualify the integrated independent-environment journey

- [ ] Wire declaration-only profile selection into Core setup and finish skill
  guidance for explicit human actions, private import and final overall admission.
- [ ] Update `products/ariadne/docs/how-to/git-authoring.md`,
  `products/ariadne/docs/how-to/context-knowledge.md` and
  `integration/docs/tutorials/lumio-ariadne-local.md` with the integrated recipe.
- [ ] Extend `integration/tests/lumio_s3_context.py` with one managed-source leg;
  use existing S3 fixture lifecycle and failure probes, not a second service.
- [ ] Qualify installed same-candidate wheels through BB/Pi on separate contributor
  and maintainer environments, starting with a nonempty managed base and metadata
  bootstrap. Attach a synthetic source, review document plus Core changes, make
  the confirmed GitHub PR, transfer/import privately, reconcile, perform authorized
  Core validation, preview/confirm and read the pinned compiled result.

Own `cli.py`, `setup.py`, skill assets and listed integration documentation/tests; extend
existing wheel verification scripts only for new exports/assets actually missed.
Prerequisites: accepted producer delivery J0–J6 and A0–A2, approved fixture
remote/service and two suitable hosts/workspaces with separate private state.
Reusing one machine with shared registry or scripted fake human responses is not
qualification. Lumio's skill remains separately installed and version-checked.
Source: all criteria, especially AC2/AC5/AC7/AC8.

Validation VA3: high risk cross-machine integration, `existing-check` plus one
`new-test` S3 leg and the specified manual harness qualification.
`test_s3_managed_profile_preserves_binding_and_reader_independence` covers the
actual Core path with canonical raw S3 distinct from publication and exchange.
Change endpoint after preview and assert no publication; rotate credential values
under unchanged references to a second authorized fixture identity and admit.
Remove exchange/profile/raw access for source-free compiled read. If the fixture
cannot supply two valid credential identities, that leg is blocked/unverified,
not replaced by a mock transport or claimed passed from a denied request.
Use hand-authored bodies/digests and the prior descriptor as the oracle.

Exercise S3 exchange in the BB/Pi journey. Reuse Lumio J3 manual-fallback import
proof with the same accepted importer; add a bounded manual transfer in the
integrated recipe if the caller/config path differs. Do not rerun every transport
fault. Record exact wheel/build and retained command/chat evidence in existing
run state; no extra ledger. Failure after native publication and stale retry
reuse existing tests where unchanged, otherwise their focused nodes rerun.
Candidate review covers remaining setup/skill changes and integration effects.
Completion: installed independent-environment journey passes with real human
consent, and Core-only/paired compatibility remains intact. No production grant.

## Coverage and verification handoff

| Approved criterion | Execution owner |
| --- | --- |
| AC1 explicit compatible configuration | Lumio JP; Ariadne A1 |
| AC2 independent environments | Lumio J0–J6; Ariadne A2/A3 |
| AC3 complete contribution consent | Lumio J2; Ariadne A2 |
| AC4 original retention | Lumio native gates; Ariadne A1 |
| AC5 configuration consent | Lumio JP; Ariadne A1/A3 |
| AC6 authority and failure | Ariadne A1/A2/A3 and existing native checks |
| AC7 reader independence/privacy | Ariadne A1/A3; Lumio native reader/export checks |
| AC8 Git setup/compatibility | Ariadne A0/A3 and existing standalone qualification |

Focused commands, after execution authorization, in the approved paired Python
3.14 environment from repository root:

```sh
python -m pytest -q products/ariadne/packages/ariadne-data/tests/test_setup.py -k git_connection
python -m pytest -q integration/tests/lumio_managed_sources.py
python -m pytest -q integration/tests/lumio_contribution_review.py
python -m pytest -q integration/tests/lumio_s3_context.py -k managed_profile
```

The service-dependent command must not count a skip as success. Existing required
`.github/workflows/ci.yml` gates remain authoritative: Core/Lumio native lint and
suites, paired same-commit wheels, S3 integration and Core-only installed
walkthrough. Extend explicit file selection, not the number of matrices. Reuse
matching green evidence; invalidate it only when relevant code, fixture, build
or environment changed. Do not duplicate successful suites across each slice.
Tests named above are planned, not executed. No new tests for prose-only edits.

Existing regression anchors: `lumio_metric_mvp.py` composite-consent and
standalone-import cases, `lumio_local_context.py` source-free SDK navigation,
`lumio_s3_context.py` admission/session pin and credential-redaction cases,
and Core `test_git_admission.py`/`test_context_admission.py` native authority and
activation coverage. Select actual affected nodes at execution preflight;
passing producer tests alone never proves the Core call path.

Residual limits: live SSH/HTTPS provider behavior and actual BB/Pi attachment/
confirmation cannot be established by local unit tests; VA3 owns that evidence.
Profiles are user/operator-owned local configuration, not hostile documents.
Relevant external boundaries are Git diagnostic strings, private source transfer
and credential-backed stores. Protect credentials/private originals from error,
review, Git and reader disclosure; reuse Lumio transfer validation instead of
inventing malicious-admin or stolen-secret scenarios. No access grants migrate
between environments. Missing tooling, accepted producer interfaces or required
human/service authorization blocks the affected work; no silent weaker fallback.

This plan is ready for review, not execution. On approval, hand its exact sources,
coverage and interface inventory to orchestrate-implementation only when the
owner separately authorizes starting. No GitHub tickets are requested or created;
if later ticketized, move canonical task bodies there and retain a thin overview.
