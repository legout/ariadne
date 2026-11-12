---
status: accepted
supersedes: ADR-0014
---

# ADR-0027: Host agents only — no Ariadne-specific agent package

**Owner decision, 2026-11-12:** retire the separately installed Ariadne Agent
entirely, then clarified **host-only** — humans operate their own host agents and
wire them to Ariadne and lumio-wiki through the existing packaged skills and/or
MCP surfaces. No Ariadne-specific agent, no substitute framework or agent loop,
and no replacement design is introduced (the owner explicitly chose retirement
without replacement).

Ariadne ships governed query/authoring capabilities, its CLI, its optional MCP
registrations and its packaged skill surfaces; the conversational agent that
uses them is an externally operated host agent. Calculation and approval
authority remain with Ariadne's deterministic gates and human admission — an
external agent never gains them by being the caller. This reverses ADR-0014's
embedding of the Tau backend: the `ariadne-agent` package, its Tau
(`tau-ai`/`tau-mcp`) dependencies and its tests are removed from this
repository. The root uv workspace stays the four members; no Tau entries exist
in the lock. External Tau repositories, historical worktrees, admissions and
records are untouched.

[ADR-0018](0018-distribution-naming-ariadneai.md)'s `ariadne-agent`
distribution-name clause is historically superseded; its `ariadne-data` naming
and unrelated constraints stand. [ADR-0011](0011-context-carrying-answers-and-skill.md)
(skill surfaces), [ADR-0024](0024-git-only-durable-authored-state.md) (Git-only
authoring) and the human approval gates are unaffected — they are exactly the
surfaces host agents consume. Historical records ([specification
0006](../specs/2026-09-29-0006-ariadne-agent-backend.md), [its
plan](../plans/2026-09-29-0006-ariadne-agent-backend.md), [ADR-0014](0014-embedded-tau-agent-backend.md))
keep their original approvals as history with retired/superseded markers; no
retrospective approval or erasure is implied.

This decision is hard to reverse (package and dependency removal across docs,
CI and layout), surprising without the Tau history, and the result of a real
trade-off (own backend versus external hosts). It grants no integration,
publication or release authority; [shared spec0035](../../../../project/specs/2026-11-09-0035-lumio-owned-context-layer.md)
task C6 executes the repository reconciliation.
