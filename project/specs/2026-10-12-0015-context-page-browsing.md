# Specification: Context page browsing

**Proposed scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; its written review is pending. Default browsing reads admitted content; explicit unadmitted Git candidate views replace staging-based drafts. Path/content bounds and read-only authority remain. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, Pi session 2026-10-12 — approved the two-tool browsing design and the skill read-only rule after reviewing the `search_pages` full-content contract and the discovery gap |
| **Scope approved** | Revision 1: two bounded read-only tools on the analyst MCP surface (`list_context_pages`, `read_context_page`) plus the packaged skill's local read-only access rule |
| **Existing contracts** | [Context retrieval 0002](2026-09-23-0002-context-retrieval.md) (search semantics unchanged), [ADR-0002](../adr/0002-mcp-facade-server.md)/[ADR-0016](../adr/0016-modular-core-git-authoring.md) (tool-surface separation), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md) (skill packaging), [ADR-0020](../adr/0020-context-read-paths.md) (the read-path decision), [spec 0011](2026-10-06-0011-context-trust-signals.md) (`context_signals` envelope) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Purpose and boundary

Let an agent discover and read Context Layer pages without query tokens, and follow a known path or cross-reference directly — over MCP, also when the agent is remote. This adds discovery and reading only. It changes no authority: ranking, governed `context` attachment, draft labeling and admission stay exactly as [specification 0002](2026-09-23-0002-context-retrieval.md) and [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md) define them.

Non-goals: graph or link traversal, semantic search, reading anything other than `context_layer/**/*.md` and `staging/context_layer/**/*.md` (no semantic-layer YAML, `ariadne.yaml`, logs or binaries over these tools), any writing tool, changes to `search_context`/`get_metric`/`resolve_term` behavior, and relaxing the promotion gate.

## Interface

### `list_context_pages()`

No parameters. Returns every served page under the served context dir plus every staged draft under `staging/context_layer/`, each entry carrying `path` (relative POSIX), `draft` (staged ⇒ always `true`, served ⇒ always `false`), `title` (frontmatter or first ATX heading, else `null`) and the page's `context_signals` envelope built exactly as `search_context` builds it. Entry order is deterministic: served before staged, then path. The listing never carries page bodies; it is a directory, not a transport for rule text.

### `read_context_page(path, draft=false)`

`path` is one exact relative POSIX `.md` path as reported by `list_context_pages` or `search_context`. Default reads the served root; `draft: true` reads the staged root. Returns `path`, `draft`, the full `content`, and `context_signals`. On the managed route, served reads re-check the pinned digest first and refuse on mid-session tampering exactly like `search_context` (issue #37 behavior); staged reads serve live staging bytes (a draft is by definition not pinned).

## Failure and consistency behavior

A path that is absolute, escapes its root (`..` or otherwise), is not `.md`, or matches no page under the selected root is a structured refusal naming the rejected path — never a fallback to search, never an empty success. No tool result ever reports a staged page as `draft: false`. Neither tool writes; neither appears on the authoring toolset. Both register on the analyst and combined toolsets of `ariadne-serve` and on the embedded agent's analyst surface, as one-line delegations over shared runtime methods (the core never imports MCP).

## Skill contract

The packaged skill (`ariadne/skill_assets/SKILL.md`, distributed per [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md)) gains one agent rule: local agents may read and grep `context_layer/` and `staging/` directly; every write stays under `staging/`; pages under `staging/` are drafts and are never verified guidance; agents not on the project filesystem use `list_context_pages`/`read_context_page` instead. The read rule grants no write and no bypass: the compile gate, promotion and the staging-only write boundary are restated unchanged.

## Acceptance criteria

1. `list_context_pages` enumerates served plus staged pages with `path`/`draft`/`title`/`context_signals`, no bodies, deterministic served-before-staged path order.
2. `read_context_page` returns the full page for an exact served path, and the staged page for the same path with `draft: true`; both carry the correct `draft` flag.
3. Absolute, root-escaping, non-`.md` and unknown paths produce a structured refusal; nothing is read.
4. On the managed route, a served read after mid-session tampering with the pinned context refuses like `search_context` does.
5. `search_context`, `get_metric`, `resolve_term` and the authoring toolset are unchanged (existing tests stay green without modification).
6. Both tools are registered on analyst and combined toolsets and the embedded analyst surface.
7. The packaged skill contains the read-freely/write-staging rule; `ariadne skill status` reports clean after re-install.
