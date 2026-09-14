# Implementation review and recovery

## Review policy

Choose one review policy per run:

- `adaptive` (default): parent diff inspection for low-risk work, one independent candidate review for normal-risk work, and immediate plus candidate review for high-risk or dependency-defining work.
- `strict`: immediate task review plus final review.
- `final-only`: one independent candidate review, with no task or wave reviews.
- `parent-only`: parent diff inspection plus focused checks; use for low-risk changes only.

Immediate-review triggers:

```text
public API/schema/shared contract; security/auth/permissions/secrets; money/data-loss/migration; concurrency/distributed behavior; broad cross-cutting diff; weak or missing checks; worker uncertainty/scope expansion; candidate-assembly conflict; a task whose contract will be consumed before the next wave review
```

Review boundaries are branch-scoped. For each mutation lane, record `laneBaseSha`, `laneHeadSha`, and `lastReviewedSha`. Review that lane's exact `lastReviewedSha..laneHeadSha` range in its managed worktree while that worktree exists; once the lane is reconstructed, review the reconstructed branch in its parent-owned review checkout. Never use the orchestrator's `HEAD` to represent unintegrated parallel lanes. After a clean verdict, advance only that lane's `lastReviewedSha`.

At a wave boundary, independently review only high-risk lanes and dependency-defining contracts needed by the next wave. For normal-risk lanes, defer review until the candidate is assembled; for low-risk lanes, the parent inspects the exact candidate diff. Send all accepted blockers for one lane in one batch to one fix worker. After accepted commits are assembled on an explicit candidate branch, record `candidateBaseSha` and `candidateHeadSha` and apply the selected candidate review once. No lane or candidate boundary may advance based on inspection of another branch.

## Execution loop

1. Read source artifacts.
2. Preflight constraints, dependencies, conflicts, and repository state; classify each task's risk and assign its test obligation.
3. Consult configured persistent peers when useful.
4. Create the manifest, briefs, lane board, and gates; record the review policy and each lane's initial `laneBaseSha` and `lastReviewedSha`.
5. Run fresh scouts for load-bearing context.
6. Dispatch workers in safe serial or parallel waves with their validation-unit test obligations.
7. Run the validation unit's focused check once on the tree being accepted; do not repeat equivalent validation on both worker and reconstructed trees unless reconstruction itself is in doubt.
8. Record each completed lane's `laneHeadSha`; immediately review only high-risk or dependency-defining ranges.
9. At a dependency boundary, review only the contract the next task will consume. Batch all accepted blockers for one lane into one fix pass, then rerun affected focused checks.
10. Return valid blockers to the same writer for fix/re-review when its managed worktree still exists and the child is resumable; otherwise launch a fresh fix worker in a new managed worktree from the exact original base, apply the durable prior handoff patch, then apply accepted findings.
11. After every candidate lane is clean, assemble accepted commits according to mode on an explicit candidate branch and record its base and head.
12. Apply the selected candidate policy to the exact candidate range: parent inspection for low risk, one fresh independent review for normal risk, or fresh final review for high risk.
13. Run required repository CI plus only the focused acceptance commands tied to named failure modes; do not automatically run every available typecheck, lint, and test command.
14. Keep push, PR merge, deploy, and release behind separate authority gates.

Default to one correction round. Only findings that identify a reachable defect, security issue, acceptance-criterion violation, or credible regression are blockers. Batch them into one fix pass and recheck only the affected evidence. If a second review still finds material blockers, stop and diagnose the plan or implementation boundary with the owner instead of continuing an uncontrolled loop. Never loop for optional polish.

## Findings and recovery

Classify each finding against the exact reviewed head:

- **valid blocker**: a reachable defect, security issue, acceptance-criterion violation, or credible regression; fix and revalidate now;
- **valid non-blocker**: record or defer explicitly;
- **stale**: absent at current head;
- **invalid**: contradicted by source, tests, or approved scope;
- **speculative**: lacks a reachable failure, named threat, or contract; do not fix in this run; or
- **out of scope/policy**: needs owner authority.

Treat `needs_attention` as a control signal, not proof of failure. Preserve stopped or failed worktrees and artifacts until ownership is clear. Do not launch a replacement while the original writer may still own the seam. Inspect exact head and focused logs before classifying a failed gate.

A completed child's managed worktree may be removed automatically before a later resume. Child cwd or session survival is never the recovery boundary; the pinned named base, durable handoff patch, digest, and registered parent-owned reconstruction are. If the managed worktree still exists and the child is resumable, resume the same writer only after verifying both runtime resumability and worktree ownership. Otherwise:

1. Verify that the named base still resolves to its recorded SHA. If it moved, stop and preserve the handoff for an owner decision; never fall back to current `HEAD`.
2. Create a registered parent-owned review worktree outside extension auto-discovery and the active source checkout at the verified named base.
3. Verify the patch identity/digest, then run `git apply --check` and `git apply --index`. Do not use fuzzy application or omit files. Compare the reconstructed staged tree with the worker-reported clean tree; reports are supporting evidence, not acceptance.
4. Commit the reconstruction, run focused checks on that exact tree, and apply the selected review policy to the exact base/head range. Advance `lastReviewedSha` only after the required review or parent inspection.
5. For an accepted fix, allocate a fresh managed worker from the same verified named base, replay the prior full patch, and apply the findings. The new full patch replaces the old one; reset the review boundary to the pinned base and re-review the complete replacement range.

Preserve failed or uncertain artifacts and owned refs. Delete them only after all consumers are terminal and cleanup is explicitly authorized.

Escalate product, architecture, credential, merge, release, and publication choices instead of guessing.

## Completion evidence

Before accepting a run, verify:

- final diff contains only intended files;
- focused validation covers changed behavior per its assigned obligation;
- high-risk and dependency-defining lane ranges received their required review, and the exact candidate range received the selected review or parent inspection before target integration or publication;
- accepted findings were fixed and revalidated;
- every lane is terminal or blocked with a named next action;
- handoffs are durable before worktree cleanup; and
- skipped validation and residual risks are explicit.

Reviewer reports, CI checks, and receipts are evidence, not publication authority.
