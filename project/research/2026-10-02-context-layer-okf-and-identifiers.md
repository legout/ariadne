# Context Layer: OKF examples, schemas and identifier mappings

Research date: 2026-10-02. **Evidence only; not an approval source.** The subsequently owner-approved design is captured in [specification 0010](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md); its approval does not authorize implementation or ticket changes. Requested comparison: Google's OKF v0.2 bundles versus Ariadne's artifacts, existing schema sharing, and persistent discovery of synonyms and derived identifiers.

## Sources and method

Google sources are pinned to [`62883ea36d63ca7cd7178f1381060d7b2617cd6f`](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles). Inspected the directory tree and frontmatter-key census of all 53 concept pages across four bundles, then representative bodies from each bundle and the relevant [OKF specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/SPEC.md). The downloaded corpus has 80 Markdown files including indexes, logs and the README/spec. Not every body was read; no Google example SQL was executed.

Local evidence: current working-tree implementations and both served and staged retail-demo artifacts. Existing modifications were left untouched. Distinguish implemented behavior from the approved, not-yet-implemented [modular-core/Git-authoring design](../specs/2026-10-02-0009-modular-core-git-authoring.md). The installed global Ariadne skill is older than the repository's [packaged skill](../../src/ariadne/skill_assets/SKILL.md); this investigation uses repository sources for current behavior.

Prior-knowledge lookup: the global wiki graph returned eight summary candidates, including OKF and semantic-layer context; it supplied background, not evidence of current Ariadne behavior. The installed `obsidian-wiki` lacks the skill's `memory log` command, so query logging was not performed. Research capture stays here under the project's artifact contract, rather than duplicating the findings in the global vault.

## 1. What Google's examples actually contain

The examples are not one uniform mandatory template:

| Bundle | Concept pages | Structure and emphasis |
| --- | ---: | --- |
| `acme_retail` | 9 | `tables`, `policies`, `metrics`, `computations`, `skills`, `attesters`; business definitions, trust, lifecycle, deprecated definitions and computation receipts. |
| `stackoverflow` | 26 | `datasets`, `tables`, general `references`, `references/joins`, `references/metrics`; full schema descriptions, enum/license catalogs, query patterns and links. |
| `crypto_bitcoin` | 9 | `datasets`, `tables`, `references/joins`, `references/metrics`; nested schemas, units, physical layout and cross-table relationships. |
| `ga4` | 9 | `datasets`, `tables`, `references/metrics`; daily shards, repeated/nested fields, extraction patterns and audience definitions. |

All 53 concepts have `type`, `title`, `description`, `tags`, and `generated`. All 44 non-Acme concepts have `resource` and `sources`; Acme has `resource` on three concepts and `sources` on five. Acme has `verified` on eight concepts, `status` on nine and `stale_after` on seven; the other bundles generally omit those optional fields. Rich trust/lifecycle metadata is illustrated most directly by Acme, not by every bundle.

Representative content:

- [Acme orders](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/acme_retail/tables/orders.md): a column/type/meaning table; claims footnoted to warehouse schema or revenue policy; row grain and consumer pitfalls.
- [Stack Overflow questions](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/stackoverflow/tables/posts_questions.md): column schema, clickable sibling/reference links, common query patterns, metric links and join links. [Post types](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/stackoverflow/references/post_types.md) centralizes shared enum knowledge rather than repeating it in every table.
- [Bitcoin transactions](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/crypto_bitcoin/tables/transactions.md): schema including nested fields and modes, units, partitioning guidance and related assets.
- [GA4 events](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/ga4/tables/events_.md): sharded-table identity, nested schema, repeated-field cautions and extraction examples.
- [Acme gross margin](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/acme_retail/metrics/gross-margin.md): definition, an explicit `not: [{term, why, instead}]` disambiguation extension, historical change and a linked sanctioned computation.
- [Acme computation](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62883ea36d63ca7cd7178f1381060d7b2617cd6f/okf/bundles/acme_retail/computations/gross-margin-period.md): `type: Attested Computation`, runtime, typed parameters, `executor.resource`, receipt fields, `attester.resource`, policy sources and computation body.

The examples illustrate documentation structure, not independently proven query correctness. Acme's gross margin is an absolute currency amount; Ariadne's retail-demo `gross_margin` is a ratio. Borrow the representation, not the formula or BigQuery execution route.

### Format versus Ariadne's application profile

OKF §3 permits domain-specific directory organization. §4 requires only a nonempty `type`, allows producer extensions and uses free-form structured Markdown bodies. Types are not centrally registered. Consequently, Ariadne's lowercase types and `grain`/`governed_by` extensions are not inherently incompatible with OKF.

Ariadne imposes a narrower application profile: fixed types/folders, required per-type fields, all six content groups for a full authored bundle, and model/Policy dependencies. Google's bundles cannot simply be submitted to Ariadne unchanged. Generic OKF acceptance must remain separate from authorization to serve a governed Ariadne model; broader document support must not relax compile, grain, source-approval or admission gates.

OKF §5 recommends explicit-offset datetimes for timestamp-valued fields, stable source IDs for claim footnotes, and objective source signals rather than portable numerical credibility scores. §6 supports ordinary Markdown links and path-valued resources. `aliases` is not a standardized OKF v0.2 field and does not occur in the inspected example concepts; it would be an Ariadne producer extension. Acme's `not` field is an example extension, not a universal required field.

## 2. Comparison with what Ariadne creates

| Aspect | Current Ariadne | Gap / proposed improvement |
| --- | --- | --- |
| Bundle layout | Tables, joins, Policies, metrics, computations, skills; generated directory indexes and log. | Already close to Acme. General reference support is inconsistent across authoring routes; dataset/source overview pages are absent from the full-bundle taxonomy. |
| Table identity | `type: table`; DB/registry in `sources`; filenames such as `tables/orders.md`. | Add an explicit credential-free canonical `resource` and source-qualified identity. Avoid ambiguous `orders` across multiple sources. |
| Table content | Row meaning, column names/types/statistics, join hints and grain evidence. | Standardize `# Schema`, true Markdown cross-links, column meanings, applicable rules and pitfalls. Distinguish declared constraints from observed statistics. |
| Provenance | `sources` lists; harness evidence includes retained document identity/digest. | Attribute individual claims with `[^source-id]`, distinguish profile evidence from domain documents, and expose accurate source author/modification signals when known. Do not fabricate usage counts. |
| Trust/lifecycle | Mechanically stamped `generated`, empty `verified` in drafts, human Promotion events; freshness normally 90 days. | `_stamp_pages` emits a date-only `stale_after`; align future output with OKF datetime guidance. Prefer evidence-appropriate freshness rather than assuming one TTL is appropriate for everything. |
| Metric narrative | Rules, exact statuses/dates and formula explanation; model-derived `governed_by`, dimensions and grain. | Link table, Policy and computation pages; add disambiguations, examples and effective-change explanations where real evidence supports them. |
| Computation | Generated expression fragment, `runtime: duckdb`, `governed_by`, scalar attester path or `attestation: pending`. | Not the richer Google executor/parameter/receipt contract. Any stronger interoperability is a separate scoped decision; preserve honest pending attestation and compiler ownership. |
| Shared meaning | Policies and join references; no dedicated synonym facility. | A Reference for a business term/identifier can centralize scoped representations and link relevant tables/rules. |
| Query retrieval | Token-based scan over full served and staged Markdown, with passage pointers and draft labels. | An alias written into a page is searchable text today, not semantic synonym resolution or guaranteed query-to-field mapping. |

Evidence: [authoring prompt and bundle enrichment/contracts](../../src/ariadne/author.py), [harness submission boundary](../../src/ariadne/authoring.py), [runtime](../../src/ariadne/runtime.py), [ingestion](../../src/ariadne/ingest.py), [promotion](../../src/ariadne/promote.py), [ADR-0007](../adr/0007-okf-bundle-structure-agent-generation.md).

Existing [served orders](../../examples/retail-demo/context_layer/tables/orders.md) and [staged orders](../../examples/retail-demo/staging/context_layer/tables/orders.md) demonstrate the schema/row-grain content. These local generated artifacts are examples, not the newest contract: served content predates later harness changes. Some historical source titles refer to Seed Notes while their resources point to the database; future claim attribution should cite the actual source of the rule, not inherit that ambiguity.

The packaged author prompt remains retail-demo-specific: named Policies/metrics and exactly three operational guides. It does not request a domain-wide synonym catalog or systematic identifier-pattern discovery. A richer page template alone will not add that capability.

## 3. Where schemas are shared today

**Yes, in three surfaces:**

1. **Live catalog:** `sources._catalog_entry` reads `information_schema.columns`; `AriadneRuntime.list_datasets` exposes source-qualified table names plus each column's name and DuckDB type. CLI: `ariadne list-datasets --sources ariadne.yaml`; the same operation is available through MCP and the Analyst adapter.
2. **Measured authoring inputs:** the profiler returns all registered tables with column types, row/null/distinct statistics, single-column primary-key candidates and conventional foreign-key candidates. CLI can persist this as JSON; `authoring.harness_inputs` returns the profile directly to the Authoring Agent. `profile.json` is an output option, not an always-present maintained artifact.
3. **Context table pages:** the author drafts `context_layer/tables/*.md` from that profile. These are persistent, readable schema documentation, though their column inventory/statistics are model-authored narrative rather than a mechanically synchronized schema contract.

OSI models separately describe modeled fields/expressions and declared grains; they need not contain every physical column. `ariadne.yaml` identifies sources/access, not their column schemas.

Current catalog output is **not full DDL**: it does not publish declared nullability, defaults, source comments, constraints or indexes. A profiler observation of zero nulls does not prove a `NOT NULL` constraint. Observed uniqueness does not prove a future business-key guarantee. Schema/profile snapshots also need source identity, measurement scope/time and freshness to remain interpretable after data changes.

## 4. Synonyms are not identifier equivalence

Four distinctions matter:

| Knowledge | Example | Authority / proposed home |
| --- | --- | --- |
| Language alias | “order number”, “order no”, “order identifier”. | A shared Reference; potentially an `aliases` extension for retrieval. |
| Physical representation | `pos.main.orders.order_no` and another system's differently named column represent the same **store-local** number. | Scoped, source-qualified field mappings on that Reference, linked from table schemas. Requires evidence of meaning, not merely names. |
| Identifier derivation | Global order ID is store prefix plus local order-number text. | An identifier-mapping Reference explains the relationship/evidence; an owner-confirmed normative rule belongs in a Policy. Executable expression belongs in OSI. |
| Join/alignment semantics | Store-local keys need store identity; order lines reference an order but are not one row per order. | Declared grain/relationships and, where applicable, conformed dimensions in the Semantic Layer. |

For the user's example:

```text
store ABC + local 123123 -> global ABC123123
store XYZ + local 123123 -> global XYZ123123
```

`123123` is not globally unique. Unless the business uses a different key, local order identity is `(store_id, local_order_number)`, not the plain number. The global representation is equivalent to that **pair** only if the prefix mapping and formatting rule are unambiguous and validated. Concatenation is not inherently injective when both parts have variable lengths. Historical prefix changes or local-number resets may require additional validity scope.

Do not declare local/global columns interchangeable synonyms, join on the local number alone, strip an assumed three-character prefix, or recover identity by arbitrary suffix matching. Preserve leading zeros; converting `00123` through an integer loses information unless the approved rule explicitly canonicalizes it. Missing prefixes, unknown stores and unmatched records must remain visible rather than silently constructing plausible keys.

Ariadne already has OSI field expressions/source queries and `conformed_dimensions` mapping dataset fields to common analytical group keys. Those are reusable execution building blocks, **not** a natural-language synonym store, transformation detector or proof of business equivalence. Normalize and validate a key before declaring conformance; never use conformance to disguise incompatible native values or authorize raw fact-to-fact joins.

## 5. Proposed minimum persistent representation

Recommend **one OKF source of truth**, not a parallel synonym YAML/database. Start with one shared `type: reference` page for order identity, containing:

- Term aliases and an explanation that the umbrella term can mean local or global identity.
- A small mapping table: fully qualified column, local/global representation, store/tenant/time scope, evidence and linked table page.
- The derivation, formatting assumptions, non-equivalences and synthetic examples.
- Links to owner-confirmed Policies and the actual OSI field/source implementing the rule.
- Evidence for observed candidates, unresolved exceptions and freshness/dependencies.

A proposed location is `references/order-identity.md`; introduce a `references/terms/` subdivision only if the volume needs it. A structured `aliases` list and a small namespaced `ariadne` mapping extension may be justified when a consumer actually resolves terms/fields from them. Start with that consumer's required fields, not a generic ontology. Do not duplicate an independently editable executable formula in frontmatter and OSI; link to the OSI expression and describe its business meaning in the page.

This is a taxonomy/interface extension, not existing full-bundle behavior. Today standalone ingestion accepts general `references/`, but harness submission accepts references only directly under `references/joins/`; its gate would refuse the proposed general Reference. Ingestion `_assemble` also constructs a fixed frontmatter subset and does not preserve arbitrary `aliases` or mapping metadata. Both routes and their page contracts would need explicit, reconciled changes for structured support. Do not work around the gate by classifying terminology as a join.

**Available today:** an owner-supplied data dictionary can be ingested into a general Reference/Policy draft and human-promoted, preserving the explanation in Markdown. This does not provide structured alias resolution or autonomous pattern verification.

## 6. How an Authoring Agent could discover and retain patterns

Proposed loop, using the approved Git proposal lifecycle when implemented:

1. **Read before rediscovering.** Read admitted table/reference/Policy pages, pending proposals, measured schemas and source-linked domain documents. Preserve existing accepted knowledge and distinguish it from candidate hypotheses.
2. **Generate a bounded candidate.** Names/descriptions, examples and existing joins suggest a specific mapping: direct equality, store-prefixed representation, or an explicit lookup. Similar names or values are leads, not confirmation.
3. **Measure through Ariadne.** Add a narrow typed mapping-inspection operation backed by existing read-only Execution, not an arbitrary `execute_sql` or shell tool. The service validates approved table/column identities and a supported candidate transform, then performs bounded measurements. Do not add a general expression/rule engine for this one use case.
4. **Record reproducible evidence.** Return source identity, selected columns, candidate rule, measurement time/scope, sampled/full designation, tested and eligible row counts, null/unknown-store counts, mismatches, collisions, match coverage and join multiplicity. Use an independent record key/lookup where available; merely finding the constructed value somewhere in another table is weak evidence. Profile across relevant stores/time periods, not just one convenient shard. Retain aggregate evidence and limited permitted counterexamples, not entire customer/order datasets.
5. **Persist immediately as a proposal.** Save the mapping explanation, evidence and unresolved questions in the same candidate Reference. Propose the related OSI edit only when the rule and required scope are established; otherwise keep the hypothesis without granting it execution authority.
6. **Ask and admit separately.** Ask the owner about unresolved semantics/formatting/exceptions. A perfect sampled match is not universal proof or a business-policy decision. Technical checks, human admission and independent numerical attestation remain separate. Only a human-reviewed, validated candidate is admitted; successful profiling never promotes it.
7. **Retrieve and recheck.** Subsequent sessions find the Reference by aliases, column identity and links. Changes to schema, prefix lookup, formatting or observed scope require dependent mapping revalidation. Conflicting rules remain explicit, not last-write-wins synonyms.

**Current limitation:** the profiler emits numeric/distribution summaries and top values only for low-cardinality columns; unique order identifiers do not receive representative value samples. FK heuristics are conventional `*_id` matches within one source, require single-column uniqueness and test direct containment. They do not find composite/store-scoped keys, arbitrary renamed columns, cross-source transformations or prefix rules. The native Authoring toolset has no general data query or mapping-inspection operation. This is a concrete evidence-access gap, not something stronger prompting alone can fix.

## 7. Choices and bounded next steps

1. **Enrich the existing Ariadne OKF profile (recommended):** explicit resource identity, schema templates, source-keyed footnotes, ordinary links, general References and scoped identifier knowledge; keep OSI and admission ownership. Lowest duplication and directly supports this use case.
2. **Broader generic OKF interoperability:** import arbitrary Google bundles/types and implement a richer computation receipt contract. Larger parser, profile and migration scope; useful only if portable import/export is a near-term requirement. Generic document reading must not imply governed execution.
3. **Separate synonym/rule registry:** structured but duplicates wiki meaning and introduces synchronization/authority questions. No demonstrated need for a second authoritative store.

If direction 1 is approved, shape behavior in this order: artifact contracts/identity first; terminology retrieval second; typed mapping evidence/discovery third. The already approved modular-core design explicitly excludes new Context Layer page types and preserves existing formats. This research is a follow-up scope, not permission to silently widen that design or its plan. Reconcile affected ADR/spec/plan owners before dependent implementation.

Material decisions before a specification: whether broad Google-bundle import is required or only closer generated artifacts; which ambiguous mappings always require owner confirmation; and the actual data-project identity rules (store-prefix uniqueness/history, leading-zero formatting, local-number reset scope and missing-key policy).

Concrete acceptance scenarios for a future design:

- Same table name in two sources remains separately identifiable in schema pages and mappings.
- Different column names for the same scoped identifier resolve to the intended Reference/fields; a word alias alone never authorizes a join.
- ABC and XYZ both have local order `123123`; normalization preserves two global identities and joins do not merge stores or fan out the root grain.
- `00123`, unknown prefixes, variable-length ambiguity and documented exceptions follow an explicit confirmed rule or remain unresolved; they are not silently normalized.
- A high-match sampled hypothesis survives a new session as a labeled proposal, not an admitted fact. Its measured row/scope limits remain visible.
- Revised prefix/schema evidence invalidates dependent validation; a stale or conflicting candidate is not silently admitted.
- Documentation examples never bypass the SQLGlot/compile, grain and read-only execution route; admission remains human-only.

Validation obligation for this research artifact: **existing-check** (primary-source/source-code inspection and local-link verification). No implementation, new dependency or runtime tests are part of this task. Planning-contract v1; installed skill provenance unknown.
