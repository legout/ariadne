---
description: Merge a registered worktree or candidate branch locally or via PR (merge-worktree skill)
argument-hint: "[<worktree or candidate>] [options]"
---
Load the `merge-worktree` skill — read its `SKILL.md` in full — and follow it exactly for this request. Do not improvise a substitute procedure; opening a PR never authorizes merging it.

Request: ${@:-none given — the skill asks which worktree or candidate to integrate.}

If the `merge-worktree` skill is not installed in this session, stop and tell the user to run `/setup-implementation-orchestrator` first.
