# Pi implementation dispatch

## Lane ownership

- Parallel mutation requires separate managed worktrees.
- One writer owns each worktree and source seam.
- Dependent tasks wait for upstream handoffs.
- Read-only children may share a checkout only when they cannot change project state.
- Each worker makes focused commits.
- The orchestrator assembles only accepted, reviewed lane commits in a registered candidate worktree; a worker report alone is never the assembled tree.
- A conflict pauses candidate assembly; it never starts another writer against uncertain ownership.
- Before mutation, create a collision-checked named base ref and record its resolved SHA. Use that supported named ref for managed allocation; do not use a raw SHA or moving parent `HEAD` as a recovery base.
- A lane handoff must include the full binary-capable patch path and digest, worker commit/tree/cleanliness, and runtime cleanup status. A missing or dirty handoff is blocked, not an accepted empty lane.

The runtime boundary was rechecked against `pi-subagents` 0.66.0. Managed workers accept supported named `baseRef` values, and normal completion may remove the worker worktree/branch. The orchestrator therefore treats the captured handoff patch and pinned base ref as durable recovery inputs. It does not depend on an undocumented retention option and does not alter the Pi runtime.

Record a lane board before parallel mutation:

```text
Lane | repo/cwd | task decision | claimed files/contract | worktree | authority | next gate | handoff
```

## Native Pi dispatch recipe

For a coordinated wave, make exactly one top-level `subagent` call with `async: true` and a `workflowScript`.

- Use `runs.run` for dependent stages.
- Use `runs.all` for independent read-only work.
- Use `runs.lanes` for predeclared serial stages across independent lanes.
- Use stable keys and distinct managed output paths.
- Set fresh context for scouts, workers, reviewers, and validators.
- Set `worktree: true` on parallel mutation-capable children.
- Give `new-test` workers the embedded public-seam, behavior-first red/green contract; require evidence matching the assigned test obligation in each report.
- Do not set hard tool budgets on mutation-capable workers.
- Return output references, commit IDs, and handoffs instead of copying full reports into later prompts.

A worker launch names the brief path, repo/cwd/ref, authority, claimed seam, validation, commit requirement, output, and escalation rules. A reviewer launch names the same brief, worker report, and exact diff package.

## Durable lifecycle recipe

Each block below is a runnable command example with inputs supplied as environment variables (`run`, `lane`, `base_sha`, and the artifact paths/digests). Every block defines its own `stop` refusal and runs `set -euo pipefail`. Pin/digest failures abort before allocating review resources; applicability or staged-tree failures abort before the reconstruction commit and preserve the review checkout for inspection.

**Pin the named base before allocation.** `base_sha` is the approved lane base: the checked-out base for a first wave, or a reviewed upstream candidate base for a dependent lane. It is never the moving parent `HEAD`, and creation never overwrites an existing pin.

```bash
stop() { printf 'lifecycle refusal: %s\n' "$*" >&2; exit 1; }
set -euo pipefail
: "${run:?run id}" "${lane:?lane id}" "${base_sha:?approved lane base}"
base_ref="refs/heads/orchestrator/$run/base/$lane"
if git show-ref --verify --quiet "$base_ref"; then
    # Collision-checked reuse: the existing pin must still resolve to the recorded base.
    test "$(git rev-parse "$base_ref")" = "$base_sha" || stop "base pin moved; preserve artifacts for an owner decision"
else
    # Create-only: the empty old-value argument refuses to overwrite an existing pin.
    git update-ref "$base_ref" "$base_sha" "" || stop "base pin creation lost the collision check"
fi
# allocate the managed worker from the named ref; capture a complete binary-capable patch,
# its digest, and the worker-reported clean tree before allowing child finalization
```

**Replay and reconstruct after cleanup.** Verify the pin and the patch digest before creating anything; never fall back to the parent's current `HEAD`. Verify the staged tree against the expected clean worker tree before committing.

```bash
stop() { printf 'lifecycle refusal: %s\n' "$*" >&2; exit 1; }
set -euo pipefail
: "${run:?run id}" "${lane:?lane id}" "${base_sha:?recorded base sha}"
: "${patch:?handoff patch path}" "${patch_digest:?patch digest}" "${expected_tree:?expected clean worker tree}"
: "${review_path:?registered review worktree path}"
base_ref="refs/heads/orchestrator/$run/base/$lane"
review_branch=${review_branch:-"orchestrator/$run/review/$lane"}
git rev-parse --verify --quiet "$base_ref^{commit}" >/dev/null || stop "base pin is missing"
test "$(git rev-parse "$base_ref")" = "$base_sha" || stop "base pin moved; preserve artifacts for an owner decision"
test "$(git hash-object "$patch")" = "$patch_digest" || stop "handoff patch digest mismatch"
git worktree add -b "$review_branch" "$review_path" "$base_ref" || stop "review worktree creation failed"
git -C "$review_path" apply --check "$patch" || stop "handoff patch does not apply cleanly to the pinned base"
git -C "$review_path" apply --index "$patch" || stop "handoff patch could not be staged"
# worker reports are supporting evidence; only the staged tree is the reviewed content
test "$(git -C "$review_path" write-tree)" = "$expected_tree" || stop "staged tree differs from the expected worker tree"
git -C "$review_path" commit -qm "reconstruct $lane for review" || stop "reconstruction commit failed"
# review exactly "$base_sha"..HEAD, then advance lastReviewedSha on this reconstruction only
```

**Assemble accepted reconstructed commits.** The candidate consumes only reconstructed reviewed commits, never a deleted worker path, the parent `HEAD`, or a live worker SHA.

```bash
stop() { printf 'lifecycle refusal: %s\n' "$*" >&2; exit 1; }
set -euo pipefail
: "${run:?run id}" "${lane:?lane id}" "${base_sha:?recorded base sha}"
: "${reviewed_sha:?reconstructed reviewed commit}" "${candidate_path:?registered candidate worktree path}"
base_ref="refs/heads/orchestrator/$run/base/$lane"
test "$(git rev-parse "$base_ref")" = "$base_sha" || stop "base pin moved before candidate assembly"
git worktree add -b "orchestrator/$run/candidate" "$candidate_path" "$base_ref" || stop "candidate worktree creation failed"
git -C "$candidate_path" cherry-pick "$reviewed_sha" >/dev/null || stop "candidate assembly failed"
# fresh review of the exact candidate base..head, then hand merge-worktree the registered
# candidate path, branch, base/head, checks, review evidence, and authorization state
```

The examples are intentionally recipes, not calls to a retention API. Use a binary-capable patch format, verify the digest before applying it, and preserve artifacts and owned refs when any check fails. A fix worker's replacement patch supersedes the prior full lane patch: replay it from the same pinned base with a distinct `review_branch`, reset the lane's review boundary to the pinned base, and re-review the complete replacement range.
