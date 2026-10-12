# Specification: Unified discovery search

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2** — Owner, pi session 2026-10-12: approved by the explicit implementation authorization for issues #62–#65 (together with ADR-0021 and the scoped spec-0001 usability amendment) |
| **Origin** | Owner request 2026-10-12: usability gap table from the ktx comparison ("unified `ariadne search` across metrics, pages, terms, examples" instead of four commands) |
| **Scope approved** | Revision 2: grouped CLI/MCP/native discovery over a shared artifact-only seam, preserving native payload/ranking/boundedness and existing root/admission selectors; no eager execution-opening runtime. |
| **Existing contracts** | [ADR-0021](../adr/0021-usability-shell-composition.md) (shared composition, no autonomous authority), [spec 0001](2026-09-23-0001-local-artifact-runtime.md) (selectors and proposed scoped output amendment), [spec 0002](2026-09-23-0002-context-retrieval.md) (context search semantics), [spec 0007](2026-09-29-0007-answer-examples.md) (example retrieval), [spec 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md) (term resolution/context-only admission), [spec 0015](2026-10-12-0015-context-page-browsing.md) (adapter conventions), [ADR-0020](../adr/0020-context-read-paths.md) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Purpose and boundary

Discovery today requires knowing which of `list-metrics`, `search-context`, `resolve-term`, `search-examples` owns which question. An agent — or a new user — asking "what do we have on revenue?" should get one grouped answer. `ariadne search` composes the four mechanisms; it invents no retrieval of its own.

Non-goals: no embeddings, no new indexes, no cross-kind fused ranking, no changes to any underlying command's semantics, filters or contracts; no execution of anything (search never compiles or runs SQL); no new trust signals beyond the envelopes each mechanism already returns.

## Interface

```bash
ariadne search "<text>" [--limit N] [--json]
                        [--project DIR | --sources PATH | --db PATH]
                        [--served PATH] [--staging PATH]
```

Unlike status, managed discovery still requires explicit `--project` and a valid human-admitted snapshot; it never selects a mutable worktree as served. Legacy `--served`, cwd-versus-`./served` ambiguity, source selectors and staging defaults are preserved exactly from query commands. No default managed autodetection is claimed here.

### Shared artifact-only construction

Existing `QueryRuntime.__init__()` renders models and constructs `DuckDBExecution`; simply wrapping its discovery methods does **not** meet this spec. Extract/reuse the artifact metadata, admitted-snapshot consistency/provenance, context/term resolution and example-root seams in one shared source-free discovery path. New CLI/MCP/native discovery adapters and the existing per-kind runtime methods use those same functions and preserve result behavior; do not build a parallel catalog/search implementation. Registry identity and admission checks remain, without source connections, model rendering, SQL binding or execution. Query operations retain their execution construction and compile gates.

Source-free must hold from adapter/toolset startup through the discovery call, not only inside a callback after eager runtime construction. In an admitted context-only project, report metrics unavailable with the existing missing-catalog reason while pages/terms/examples remain discoverable; do not invent a metric catalog. Draft context still comes only from the explicitly labeled staging path.

### Grouped report

Four groups in fixed order:

1. **metrics** — existing `list-metrics` entries with unchanged name/description/dimensions. Filter names/descriptions by the existing context lexical token normalization: all nonempty query tokens must occur as whole tokens in the combined text; no tokens means no metric hits. Preserve catalog order, add a separate follow-up pointer `ariadne get-metric <name>`, and carry the existing ad-hoc routing hint as group metadata rather than treating it as a metric.
2. **pages** — native `search-context` hits, including full content, passage pointers, `draft` labels and `context_signals` envelopes; same text/limit, same order.
3. **terms** — the native `resolve-term` first-part envelope for the text, including representations, scopes, alternative ambiguity, mapping assertion/confirmation, freshness, citations, admission provenance and the no-join-authority reminder. Preserve its bounded completeness/next-part metadata, not just a flattened hit list.
4. **examples** — native `search-examples` hits with existing review/history/staleness labels. Managed example-store location stays at the logical project root; citation staleness uses the pinned artifact root.

`--limit` defaults to 5 for metrics/pages/examples. Terms retain the resolver's own bounded first-part behavior; the shell never trims an assertion away from its scope/evidence or claims complete resolution where the native envelope is incomplete. Follow-up uses the native `resolve-term --part` interface. Each group's existing truncation metadata is retained; where the native mechanism supplies none, report completeness as unknown rather than inventing a total or `has_more: false`. Metric filtering can determine its own result count from the enumerated catalog. Native payload fields/order are unchanged; group status/follow-up metadata is additive. Empty groups remain visible.

`--json` emits one grouped object. Human output summarizes the same groups and labels without replacing authoritative full payloads. This new-command-only exception is the **proposed** amendment in spec 0001; existing JSON query commands remain unchanged.

### MCP/native surface

One `discover` tool is registered on analyst and combined MCP toolsets and the embedded agent's analyst surface, delegating to the same artifact-only composition. It retains the spec-0015 response/schema conventions; core code never imports MCP. Authoring toolsets are unchanged. Other query tools keep their interfaces and execution semantics.

## Skill contract

The packaged skill points discovery before novel questions at `ariadne search` / `discover` first. Native per-kind commands remain authoritative, including full Context/Policy handling, bounded term continuation, draft labels and governance gates. Discovery labels governed artifacts; it does not execute an answer, attest its truth or authorize a join.

## Failure and consistency behavior

- Missing optional example stores are valid empty results, as the existing search already returns. A genuine native read failure (for example an OSError reading a selected context page) reports that group as `unavailable` with its actual reason while the other groups return. Do not reinterpret skipped/invalid records as a whole-store failure if the native mechanism does not raise.
- Invalid/ambiguous roots and managed admission missing or failing existing consistency/identity checks are global existing refusals before serving any group. They are not softened into empty results or partial mutable-worktree discovery.
- No writes, source connections, network calls, model compilation, admission or Promotion. Source bytes may be unreadable/offline and discovery still works from readable governed artifacts, provided the existing identity/admission requirements hold.

## Acceptance criteria

1. A text with independently known metric/page/term/example matches returns four groups with unchanged native payloads, completeness labels and follow-up pointers; metric filtering follows the stated token rule and preserves catalog order/routing hint.
2. A text with no matches yields four explicit empty groups (retaining the native term envelope); missing optional example directories are also empty, not unavailable.
3. A genuine raised context-page read error yields `pages: unavailable` with reason while available metric/term/example groups survive; invalid global roots/admission still refuse the entire operation.
4. Page/example order and complete term envelopes equal native calls for the same admitted/legacy artifact inputs, with assertion/scope/evidence inseparable and native boundedness visible.
5. Draft pages stay `draft: true`; managed admitted context-only discovery reports a missing-catalog metrics group but never blocks valid context/term discovery or substitutes root drafts for served artifacts.
6. `discover` is registered on analyst/combined MCP and embedded analyst surfaces with their existing response/schema conventions; authoring and existing query tool contracts stay unchanged.
7. From adapter initialization through the CLI/MCP/native call, a fixture refuses source connections, model rendering and network access; artifact-only discovery still succeeds and writes nothing. Existing per-kind result behavior is preserved through the shared seam, not duplicated by a shell-specific implementation.

## Shaping capture checkpoint

- **Vocabulary:** no new canonical domain terms; the groups reuse Governed Metric, Context Layer page, Term Reference, Answer Example as defined in [CONTEXT.md](../../CONTEXT.md). "Discovery" names composition, not a new retrieval engine.
- **Decisions:** the required shared artifact-only seam and no cross-kind ranking are recorded in [ADR-0021](../adr/0021-usability-shell-composition.md). The token filter only selects catalog entries; it is not a metric reranker. No retrieval evidence authorizes an embeddings/fusion escalation; the proposed human-output amendment is scoped in spec 0001.
- **Behavior:** scope, non-goals and acceptance above; approved as revision 2 (see Status).
- **Uncertainty:** dataset discovery remains out of v1; `list-datasets` stays separate. Artifact-only construction across transport startup is mandatory execution scope, not future optimization. Approval of revision 2 and the output amendment is recorded in the Status row.
