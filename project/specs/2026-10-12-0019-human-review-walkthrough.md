# Specification: Human review walkthrough

**Proposed scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; its written review is pending. Common Git Review Admission replaces the legacy Promotion and separate Example-review branches; explicit human decisions and exact displayed revision/digest remain. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2** — Owner, pi session 2026-10-12: approved by the explicit implementation authorization for issues #62–#65 (together with ADR-0021 and the scoped spec-0001 usability amendment) |
| **Origin** | Owner request 2026-10-12: usability gap table from the ktx comparison ("interactive `ariadne review` walkthrough — wrap, not weaken, the human gate") |
| **Scope approved** | Revision 2: operator-only pre-admission review, inert mapping selection, final explicit confirmation and one unchanged admission call; legacy ordinary/bundle Promotion keeps its existing native final prompt. No source approvals, autonomous confirmations or rollback promises after mutation. |
| **Existing contracts** | [ADR-0021](../adr/0021-usability-shell-composition.md) (shared composition, terminal is not identity), [spec 0001](2026-09-23-0001-local-artifact-runtime.md) (selectors and proposed scoped output amendment), [ADR-0003](../adr/0003-staging-dir-review-gate.md) (staging gate), [spec 0009](2026-10-02-0009-modular-core-git-authoring.md) (review/admit sequence), [ADR-0016](../adr/0016-modular-core-git-authoring.md) (Git Review Admission), [spec 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md) (mapping confirmation during the same admission) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Purpose and boundary

The human gates are the product, but their ergonomics are hostile: the operator must know the `review` → digest → `admit --confirm` sequence, retype revisions and digests, and remember mapping confirmations. Friction here tempts users to script around the gate — the worst outcome. The walkthrough makes the *human* path the *easy* path while changing no authority: every confirmation is the operator's, at a terminal, with the exact digest on screen.

Non-goals: no agent access to this command (skill rule below); no auto-confirmation of digests, revisions or mappings; no rebase/merge/reconcile automation; no batch admission of multiple proposals in one run; no changes to what `ariadne-authoring review`, `ariadne-promote` or `ariadne-admit` compute, validate or record.

## Interface

```bash
ariadne review [--project DIR [--proposal ID]]
               [--served PATH] [--staging PATH]
```

`--project` explicitly selects managed review, not managed query startup: it works before the first admission and conflicts with legacy `--served`. On managed projects `--proposal ID` selects one proposal; without it, list pending proposals and stop. A proposal without `--project` is invalid. Staging retains its existing route-specific default/explicit selector. No QueryRuntime or live source connection is needed to display an existing review.

On legacy projects use the selected `--served`/`--staging` roots. Without `--served`, retain the query CLI's selection/refusal when exactly one/two valid legacy served roots exist. Before the first Promotion, no valid served root is expected: require the operator to choose the target with `--served` instead of guessing or requiring an already-served metric catalog. An explicit fresh target is not created during presentation. This is a named review-before-serving diagnostic addition, not a change to existing query-root requirements.

### Managed walkthrough: all decisions before one admission

1. **Present.** Run the existing `ariadne-authoring review --project DIR --proposal ID` seam and display its exact payload: base/candidate revisions, full change inventory, applicable/`not_applicable` validation, mapping assertions and eligibility, citation/evidence identities and clearly marked review digest. Keep the displayed revision/digest as the values to submit; never silently refresh them.
2. **Select mappings, inertly.** For each eligible **asserted** mapping, show its reference/mapping identity, required scope and verified evidence, then offer the exact `--confirm-mapping reference:mapping` selection. Default is skip. Selections stay in memory; no admission/confirmation record is written yet. Unselected assertions remain assertions with no **new** human confirmation, not hypotheses; actual hypotheses remain ineligible. Existing unchanged prior confirmations may be retained, and changed/stale/conflicting ones lapse, exactly as admission already decides.
3. **Final human confirmation.** Display the candidate revision, digest, chosen mappings (or none) and the exact admission command together. Only an explicit affirmative operator answer at an interactive terminal authorizes one `ariadne-admit --project DIR --proposal ID --revision REV --reviewed-digest DIGEST --confirm` invocation carrying **all** selected repeatable `--confirm-mapping` arguments. No later mapping prompt or second admission is added.
4. **Report the actual outcome.** Show activated revision, selected/retained/lapsed confirmations from admission's result. Refusals preserve their reason; no re-review/retry/reconcile or substitution occurs automatically. If interrupted after invoking admission, do not promise rollback: display/guide read-only admission-status inspection and report any activated revision rather than retrying a potentially completed action.

### Legacy walkthrough

Reuse the existing promoter's read-only inventory/refusal helpers for ordinary staging, or the existing authoring review payload for an active harness-led bundle. Clearly distinguish ordinary merge-only Promotion from a reviewed bundle digest; never invent a digest/validation record for ordinary staging. Display the chosen staging/served targets. Only in operator interactive mode delegate to `ariadne-promote --staging STAGING --served SERVED` with `--digest DISPLAYED_DIGEST` **when an active reviewed bundle requires it**, and never with `--yes`. Its unchanged native final confirmation prompt is the human Promotion decision; no second shell confirmation is necessary. The native `review_needed`, exact-digest/validation and survivor checks still apply. Neither path approves sources or performs Git admission.

**Terminal gate, not authentication.** Interactive terminal input/output is necessary for any final human confirmation, but not proof that the caller is human. In non-interactive mode, render existing review/inventory plus exact remaining operator commands only; never prompt or invoke admission/Promotion. The shell has no `--yes`/`--confirm` bypass option and is not registered on MCP/native agent toolsets. Ordinary TTY-capable agent tools do not acquire authority through this command.

The operator output is the proposed new-command-only exception in spec 0001; existing query JSON/error contracts remain unchanged.

## Skill contract

The packaged skill states: `ariadne review` is operator-only, like `ariadne-admit`/`ariadne-promote`; agents never run it or supply its confirmations even inside terminal sessions. Agents may still use the existing **read-only** `ariadne-authoring review`, return its payload/digest and stop for the human. Source approval, reconciliation and all other existing human-only rules remain unchanged.

## Failure and consistency behavior

- No pending work reports that fact, exit 0, without a human-only call. Invalid explicit proposal/state is a surfaced native refusal, not an empty success.
- Failed or incomplete validation is displayed and blocked by the native admission/Promotion checks; there is no admit-anyway path. Stale revision, digest, approved source identity, baseline or mapping evidence refuses; the shell never silently retries with fresh identities.
- Decline/interrupt during mapping or final confirmation, **before** admission is called (or before the promoter's native confirmation), makes no admission/served/proposal-content change. This is not a transaction/rollback promise for failures after delegated writes have begun; native crash/recovery semantics remain.
- Review can use existing operational lock/cache files. Byte-comparison checks concern governed proposal/staging/served content and admission descriptors, not a new promise of an entirely byte-identical project directory after every read.

## Acceptance criteria

1. Managed review works with a selected unadmitted proposal and renders the exact native inventory/validation/mapping/evidence/digest payload, without opening sources or constructing the query runtime.
2. A recording stub sees **no** admission during presentation or mapping selection, then exactly one call after the final affirmative operator answer, with displayed revision/digest and the complete selected `--confirm-mapping` list. Effect/record equals that one hand-typed native admission command.
3. Skipped assertions retain their assertion status without new confirmation; hypotheses are never offered. Native retained/lapsed evidence behavior is unchanged and reported rather than relabeled.
4. Piped/non-interactive execution displays review plus exact remaining human commands and invokes neither admission nor Promotion, even if stdin contains affirmative-looking input; no agent/MCP tool exposes the wrapper.
5. Decline/interrupt before the mutation call leaves governed proposal/staging/served content and admission descriptors unchanged. A stale review refuses without activation; an interrupt/failure after delegation reports or guides post-state inspection, never claims guaranteed rollback or retries.
6. Legacy ordinary staging and digest-backed bundle routes use the correct native Promotion checks/prompts without `--yes`; explicit fresh targets work before a catalog exists, and ambiguous existing served roots require `--served`.
7. The packaged skill contains the operator-only/no-agent-prompt rule; reinstallation is verified for the **selected** scope/agent target, not by requiring every optional host installation to exist.

## Shaping capture checkpoint

- **Vocabulary:** no new canonical domain terms; the walkthrough speaks in Promotion, Git Review Admission, Candidate Revision, review digest and mapping confirmation as defined in [CONTEXT.md](../../CONTEXT.md).
- **Decisions:** human authority, shared seams and terminal-not-identity are recorded in [ADR-0021](../adr/0021-usability-shell-composition.md). No wrapper confirmation bypass is added; mapping choices precede the single native admission. Legacy keeps its native human prompt. The proposed output amendment is recorded in spec 0001.
- **Behavior:** scope, non-goals and acceptance above; approved as revision 2 (see Status).
- **Uncertainty:** plain-text rendering details are implementation latitude. The two legacy gates, pre-admission selectors, one-call mapping sequence and bounded interruption guarantee are explicit; no TTY-based human-authentication mechanism is claimed. Approval is recorded in the Status row.
