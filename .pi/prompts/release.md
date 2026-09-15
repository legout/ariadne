---
description: Version, finalize changelog, tag, and publish a release (make-release skill)
argument-hint: "[patch|minor|major] [options]"
---
Load the `make-release` skill — read its `SKILL.md` in full — and follow it exactly for this request. Do not improvise a substitute procedure; the exact release plan requires approval before files change.

Request: ${@:-none given — the skill determines the bump and asks.}

If the `make-release` skill is not installed in this session, stop and tell the user to run `/setup-implementation-orchestrator` first.
