# Specification: Measured Context Layer retrieval

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-23 — approved the complete design after choosing measured escalation and additive passage evidence |
| **Scope approved** | Revision 1: evaluate policy discovery; improve file-backed lexical ranking only where needed; add passage pointers to `search_context`; conditionally use SQLite FTS5 if it fixes a measured remaining miss |
| **Existing contracts** | [MVP vertical slice](mvp-vertical-slice.md) (search over served and draft Context Layer pages; full-page results; governed policy attachment), [local artifact runtime](2026-09-23-0001-local-artifact-runtime.md) (one transport-neutral operation shared by local CLI and optional MCP), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md) (full policy bodies travel with governed answers) |
| **Evidence** | [Comparison and recommendation 4](../research/2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md); [Lumio retrieval evaluation](https://github.com/legout/lumio-wiki/blob/93951f8/eval/README.md) and [section evidence](https://github.com/legout/lumio-wiki/blob/93951f8/packages/lumio-wiki/src/lumio_wiki/evidence.py); [second-brain disposable FTS5 index](https://github.com/legout/skills/blob/f89af46/skills/second-brain/scripts/sb.py) (patterns considered, not code dependencies) |
| **Contract** | planning-contract v1; installed skill provenance unknown |
| **Later terminology extension** | Owner-approved [specification 0010, revision 1](2026-10-02-0010-context-layer-schema-and-identifiers.md), 2026-10-02: adds structured References and a separate read-only term resolver, plus context-only Git discovery. It does not waive this specification's measured ranking gates, full-page/passage evidence, draft labeling or complete metric/Policy context requirements. |
| **Later browsing extension** | Owner-approved [specification 0015](2026-10-12-0015-context-page-browsing.md), 2026-10-12: adds read-only token-free listing and path-addressed reading plus the skill's local read-only rule. Search semantics, ranking gates and this specification's contracts remain intact and unchanged. |

## Purpose and boundary

Find the right approved Policy when an agent asks a new business question, without assuming embeddings or creating a second knowledge store. This changes discovery through `search_context`, not the authority or content of a governed answer. Promoted OKF Markdown remains the source of truth; Staging remains a separately marked, unapproved search source.

This work follows the approved local-runtime restructuring: retrieval behavior belongs to its shared runtime, so the local JSON command and optional MCP adapter use the same operation. It neither replaces nor changes the scope of the existing local-runtime plan.

Non-goals: embeddings, vector databases, graph traversal, curated hot indexes, new OKF fields, automatic promotion, changes to metric compilation or execution, and replacing the complete metric page or cited Policy bodies in `get_metric` with snippets.

## Approach and decision rule

1. Check in a small, versioned set of natural-language Policy questions against representative served Context Layer pages, with the expected page path and served/draft identity recorded. Include a known-missing question and a staged-versus-served case. Measure current `search_context` before changing ranking; retain the baseline result in the implementation handoff, not in a second permanent ledger.
2. If the existing ranking meets the acceptance cases, leave ranking alone. Otherwise improve the current file-backed scan with deterministic, token-aware ranking that favors meaningful page fields and matched passages over repeated incidental substring occurrences. Keep every currently searchable Markdown page eligible, including non-Policy pages and generated navigation pages; do not make Policy the only searchable type. A generated index may rank below a directly matching page but remains discoverable.
3. Only if that lexical path still misses a recorded positive case, evaluate SQLite FTS5 against the *same* questions. Add FTS5 only when it brings every recorded positive case into the required top five without regressing the missing-term or draft-marking cases. If neither path meets the cases, stop and return the unresolved retrieval behavior to the owner rather than shipping an unmeasured index. This conditional approval does not authorize embeddings or another dependency.

FTS5, if triggered, is a derived, disposable index over the same served and staged files; it is never an independent source of facts. A changed, added, deleted, or promoted page must be reflected on the next search, by freshness validation and rebuild or by an equivalent file-backed read. If SQLite/index creation or refresh fails, return results from the file-backed lexical path instead of stale index results. No manually maintained index or promotion-time indexing requirement is introduced.

## Interface and passage pointers

`search_context(query, limit=10)` continues to return a ranked list of hits, each with the existing `path`, numeric `score`, `draft` boolean, and **full** `content`. Results still cover both the selected served context root and `staging/context_layer/`; a staged hit is always `draft: true`, even if a served page has the same relative path. `score` remains a relative ranking value, not a stable externally meaningful frequency count. The existing query and limit parameters, including local JSON and MCP exposure after the runtime restructuring, are unchanged.

Each hit additionally has `excerpt` (a bounded, verbatim substring of its `content` around a matched term), `line_start` and `line_end` (1-based inclusive file-line coordinates covering that excerpt), and `section` (the containing Markdown heading when reliably identifiable, otherwise `null`). Matching frontmatter can yield an excerpt and line coordinates with `section: null`; no body evidence is fabricated. Excerpts may indicate clipping outside the verbatim substring, but cannot invent supporting text. A caller can cite the hit by its path, draft status, and line range, then read the full returned page to interpret the rule. The excerpt is a *pointer to matching text*, not an assertion that the text answers the question.

For a given query and page, choose a matching passage deterministically; prefer a body match over a frontmatter-only match when both exist. Headings inside fenced code do not establish a section. Full `content` is retained for compatibility and for rule interpretation. A metric response continues to attach its full served metric page and the full bodies of the cited, served Policies; neither staged material nor search excerpts enter that governed `context` field.

## Failure and consistency behavior

An empty or non-matching query returns `[]`; nonpositive limits return `[]`. Equal-score ordering is deterministic, including separate served and staged hits with the same path. Search never represents a draft as approved. Retrieval or indexing must not write into the promoted Context Layer, its generated `index.md`/`log.md`, or Staging pages. There is no migration of existing bundles. Indexes can be deleted and rebuilt from Markdown without changing the answers' source content.

## Acceptance examples

1. The versioned evaluation uses the public `search_context` operation on the existing demo Policy pages plus only the decoys needed to expose a real ranking miss. Every positive Policy question finds its expected page within the first five distinct `(path, draft)` hits. The missing-term question returns no hits. The evaluation report names the path under test (baseline file scan, revised lexical scan, or conditional FTS5) rather than conflating their scores.
2. A staged Policy or metric proposal is discoverable before promotion as `draft: true`; a matching served page is `draft: false`. Same-path staged and served content remains distinct. Editing the staged text changes the next search result without implying promotion.
3. A hit's excerpt occurs in its returned full content, and its line range covers that passage in the returned file. A matched frontmatter-only field has no invented body section. An actual Markdown section match includes its heading; a heading inside a fenced code block is not treated as a section.
4. Existing `get_metric` tests still show complete served metric and cited Policy bodies, with no staged or excerpt-only replacement. Existing `search_context` callers still receive full content, path, score, and draft flags.
5. Only if FTS5 is adopted: removing its index and rerunning search rebuilds equivalent results; changing or deleting a page cannot return its stale excerpt, and an unavailable index falls back to the lexical scan.

Evaluation measures retrieval recall on the named questions, **not** agent tool selection, answer truth, or how consistently an agent cites the returned text.

## Shaping capture checkpoint

- **Vocabulary:** Existing Context Layer, Policy, Staging, Promotion, and Governed Metric terms in [`CONTEXT.md`](../../CONTEXT.md) suffice; no new domain term is introduced.
- **Decisions:** Measured escalation instead of immediate FTS5 and additive evidence instead of replacing full-page results were explicitly approved. They are local, reversible retrieval choices under the existing ADR-0011 constraint, not a new architectural commitment warranting an ADR.
- **Behavior:** This approved revision owns the scope, non-goals, interface, failure behavior, and examples above. It does not authorize implementation, integration, or publication.
- **Uncertainty:** Whether the baseline passes and whether FTS5 earns inclusion are empirical gates, not open product decisions. No material owner decision remains before an implementation plan; a failed measurement returns to the owner.
