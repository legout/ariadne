# Bounded context reading: MCP browsing tools plus local read-only skill access

Status: accepted (owner, Pi conversation 2026-10-12: approved the two-tool MCP browsing design and the skill read-only rule for specification capture, then requested issue creation; implementation, project admission and release publication remain gated).

`search_context` returns the full body of every hit, so token-addressed retrieval already carries the rules. What was missing: discovery without query tokens (what pages exist at all), path-addressed reading (follow a link or a known path directly), and any access path when the agent is not on the same filesystem. Both gaps matter because the MCP server may run remote while local agents sit on the project directory.

Decision: two read paths, one contract.

1. The MCP analyst surface grows two bounded discovery tools — `list_context_pages` (enumerate served plus staged pages, metadata only, draft-labeled) and `read_context_page` (one exact page by relative path, full body, draft opt-in). Served reads on the managed route re-check the pinned digest exactly like `search_context`/`get_metric`. Behavioral contract: [specification 0015](../specs/2026-10-12-0015-context-page-browsing.md).
2. The packaged agent skill grants local agents direct read/grep access to `context_layer/` and `staging/` — read-only, writes stay under `staging/`, drafts are distinguished by path. This is safe precisely because the gates protect computation and writes, not reads: read bytes bypass no compile gate and mutate nothing. The pinned-digest tamper check does not cover an agent's direct reads; served pages are immutable by convention (promotion owns them) and git-versioned, so this residual is accepted.

Reads introduced here never change authority: a draft stays `draft: true`, never enters a governed `context` field, and no new tool writes anything.

**Considered options:** raw filesystem only (rejected — no path for remote MCP clients, and the skill rule alone leaves the served surface without discovery); serving whole directories over MCP (rejected — unbounded payloads, no draft/admission labeling); no browsing at all (rejected — onboarding and unknown-unknowns questions stay unanswerable); extending `search_context` with a wildcard mode (rejected — overloads ranking semantics that [specification 0002](../specs/2026-09-23-0002-context-retrieval.md) keeps measured and token-driven).
