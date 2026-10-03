# How-to: Context knowledge — schemas, terminology, mappings

This is the operator/agent guide to Ariadne's context knowledge: physical
schema pages, Dataset Overviews, Term References, Identifier Mappings and
bounded mapping evidence
([spec 2026-10-02-0010](../../project/specs/2026-10-02-0010-context-layer-schema-and-identifiers.md),
[ADR-0017](../../project/adr/0017-context-schema-and-identifier-knowledge.md),
issues #41–#46). Everything here runs on the **base install** — the local
`ariadne` / `ariadne-authoring` / `ariadne-admit` commands; MCP and the
separately installed Agent are optional adapters over the same core, never a
requirement.

One rule rides above everything:

> **Aliases, schema observations and mapping measurements never authorize
> joins, transforms or SQL rewrites, and never replace the OSI compile gate or
> the required live grain/relationship audits.** A language alias is not value
> equivalence; observed uniqueness is a candidate key, not a declared business
> key; a sampled high-coverage match is explicitly limited evidence, not a
> business rule. Join authority lives only in reviewed OSI definitions and the
> live audits the gates run.

## What the pages are

- **Dataset Overview** (`context_layer/datasets/`, `type: dataset`): the
  physical collection of one source/schema and its represented tables.
- **Table page** (`context_layer/tables/`, `type: table`): authored summary and
  column meaning plus the CORE-OWNED `# Schema` block and
  `ariadne.schema`/`ariadne.observations` metadata (exact column
  identity/types; declared nullability/defaults only where the source provides
  them; observations are measurements — row/null/distinct counts, candidate
  keys, `observed_at` with an explicit UTC offset). Observed uniqueness or
  zero nulls is never a `NOT NULL` or business-key declaration, and a physical
  table may carry UNKNOWN Grain.
- **Term Reference / Identifier Mapping** (`context_layer/references/`,
  `type: reference`): one shared concept with page-level and
  representation-level `aliases`, exact source-qualified field `bindings`,
  required `scope`, and `mappings` (`family: equality|prefix|lookup`, `claim:
  hypothesis|asserted`). The structured declaration lives in the versioned
  `ariadne` extension (version `1`, `reference_role: term|identifier|enum|join`);
  legacy References without it stay readable.

Every page names the canonical, credential-free `resource` it documents
(`ariadne://table/<payload>` / `ariadne://collection/<payload>`). Same-named
tables of distinct sources/schemas are distinct assets with distinct
resources; a filename/resource collision refuses instead of overwriting.

## Physical schema refresh (explicit)

Schema facts are generated, never hand-authored. Inside a proposal, after the
operator approved the resolved source identity:

```bash
ariadne-authoring refresh-schema --project . --proposal ID \
    --expected-revision REV --file assets.json
# assets.json: [{"source": "sales", "catalog": null, "schema": "sales", "table": "orders"}]
```

- Reads run ONLY through the operator-approved identity; an unapproved or
  changed registry is an explicit error.
- Authored summary/column meaning survives for identical column identity/type;
  removed or type-changed columns keep their prior meaning as reviewable
  history — a rename is never guessed.
- An identical refresh is a no-op: the candidate revision does not move.
- `refresh-schema` edits a candidate — it is never validation or admission.

## Enriching legacy pages explicitly (human-only)

A project imported with `ariadne-authoring import-legacy` carries legacy pages
whose spellings are unqualified (`resource: events.events` citations, no
canonical binding). Binding one is an explicit human migration step:

```bash
ariadne-authoring enrich-legacy --project . --proposal ID --revision REV \
    --page context_layer/tables/events.md            # derive the spelling
ariadne-authoring enrich-legacy --project . --proposal ID --revision REV \
    --page context_layer/tables/orders.md --file asset.json   # name it explicitly
# asset.json: {"source": "sales", "catalog": null, "schema": "sales", "table": "orders"}
```

- Without `--file`, the page's own legacy spelling must resolve to exactly ONE
  approved asset. **Several matches — same-named tables of distinct
  sources/schemas — refuse with every candidate named; the enrichment never
  guesses a source/table binding.** Zero matches, an asset outside the
  approved identity, a non-table page, an already-bound page or a page another
  page's resource already claims are explicit refusals.
- The binding is one complete page edit: the old **filename, links, citations,
  authored meaning and promotion-stamped history are preserved** (historical
  date-only freshness fields stay readable); nothing is renamed, deleted or
  reclassified. Authored explanations found under the headings the bound
  page's refresh owns (`# Schema` / `## Observations`) are re-homed, never
  discarded: column-explanation bullets become authored **Column meanings**
  (identical columns keep them, so refresh never resets a documented column
  to `unknown`), and the remaining prose/links ride as a clearly labeled
  **Authored notes** block that regeneration carries forward verbatim.
- The enrichment never refreshes, validates, reviews or admits. It is never an
  MCP or native Agent tool; an agent never runs it. Afterwards, the explicit
  `refresh-schema` of the bound asset generates the schema facts in place.

## Term resolution — admitted vs candidate

```bash
ariadne resolve-term "global order number" --project .            # pinned admitted snapshot
ariadne resolve-term --project . --file - <<'JSON'                   # exact field lookup
{"resource": "ariadne://table/...", "column": "store_id"}
JSON
ariadne-authoring resolve-term --project . --proposal ID "order number"   # candidate revision
```

- Returns bounded matches (≤20 per part, ≤64 KiB serialized): concept and
  representation ids, aliases, exact field bindings, required scope,
  ambiguity, claim/confirmation status, evidence freshness and page/source
  citations. Whole aliases/phrases match case-insensitively — never
  substrings; field identity is exact.
- The umbrella term "order number" returns the local AND global alternatives;
  an unconfirmed mapping stays a labeled lead even inside an admitted page. A
  mapping is confirmed ONLY by recorded human admission evidence bound to the
  exact reviewed assertion.
- Resolution works on a human-admitted **context-only** Git revision before
  any metric exists; metric operations keep their specific
  `no governed metric catalog` error — no absent model ever triggers a
  fallback to raw SQL.

## Bounded mapping inspection and sample permission

```bash
ariadne-authoring inspect-mapping --project . --proposal ID --expected-revision REV \
    --file candidate.json
```

The candidate is a discriminated JSON object — `family`
(`equality|prefix|lookup`), ordered `left`/`right` `{resource, column}`
bindings, `scope` predicates (`eq|in|gte|lt`, typed values), optional
`pairing` and family fields — **never SQL, a path or a function**. Reads run
through the operator-approved identity only, under operator-owned ceilings
(1,000 sampled rows per asset, 20 s execution, 64 KiB response, 4 assets, 16
bindings, 8 scope predicates, 100 values per `in` list); requests may only
LOWER them. Output is aggregate counts by default; raw identifier examples
(≤10) need the operator's explicit `inspection.raw_examples` permission in the
host registry — never an agent decision.

The retained receipt (`.ariadne/evidence/<proposal>/mr-*.json`, integrity
digest bound) reports eligible/tested counts, null/missing/unknown-lookup
counts, coverage, mismatches, collisions, multiplicity,
containment-versus-pairing basis, the actual tested scope and a
`complete|inconclusive` outcome. An allowlisted id proves nothing: validation
resolves the receipt in the project's evidence records and verifies
declaration and dependency identity. No timeout or partial result becomes a
complete check; no high-match threshold asserts meaning.

## Automatic hypothesis persistence

An Authoring agent reads the existing References/hypotheses first
(`resolve-term`, `read`), then saves a labeled hypothesis through the typed
page edit **automatically — no per-save prompt**: cite the receipt id, keep
`claim: hypothesis`, reuse the same stable representation/mapping ids (an
identical retry is a no-op; never suffixed duplicates), and keep failed,
inconclusive or conflicting results honestly labeled. Hypotheses and receipts
live in the Git proposal and the evidence area, never chat memory; a restarted
session re-reads them.

## Explicit assertion confirmation (human-only)

`ariadne-authoring review` lists every asserted mapping with its page
resource, mapping id, assertion digest, dependencies and confirmation
eligibility. At admission the human selects what is being confirmed:

```bash
ariadne-admit --project . --proposal ID --revision REV \
    --reviewed-digest DIGEST --confirm \
    --confirm-mapping order-number:global-order-concatenation
```

No selection means no new confirmation; admitted hypotheses stay unconfirmed.
Unchanged assertions retain prior human evidence only while their verified
dependencies are unchanged; changed, stale or conflicting assertions cannot
inherit confirmation. An author-fabricated approval flag is never sufficient,
and no MCP/native tool exposes confirmation or admission.

## Context-only admission and `not_applicable` checks

A candidate of schemas and References only (no metrics) validates and admits
through the normal steps (`approve-sources` → `validate` → `review` →
`ariadne-admit --confirm`). Validation lists APPLICABLE checks with explicit
`not_applicable` reasons: semantic compile/bind/Grain are omitted only when no
effective semantic declaration requires them — inherited OSI models, metrics,
Policies and relationships still receive their full checks, and unknown
physical Grain never relaxes semantic Grain.

## Adapter names and fixed role limits

| Capability | Local CLI (base install) | MCP tool | Native Agent tool | Who |
| :--- | :--- | :--- | :--- | :--- |
| Schema refresh | `ariadne-authoring refresh-schema` | `authoring_refresh_schema` (Authoring/Combined) | `refresh_schema` (Authoring) | agent, approved sources only |
| Admitted term resolution | `ariadne resolve-term` | `resolve_term` (Analyst/Combined) | `resolve_term` (Analyst) | agent, read-only |
| Candidate term resolution | `ariadne-authoring resolve-term` | `authoring_resolve_term` (Authoring/Combined) | `resolve_term` (Authoring) | agent, read-only |
| Bounded mapping inspection | `ariadne-authoring inspect-mapping` | `authoring_inspect_mapping` (Authoring/Combined) | `inspect_mapping` (Authoring) | agent, never a page edit |
| Source approval | `ariadne-authoring approve-sources` | — | — | **human only** |
| Assertion confirmation / admission | `ariadne-admit [--confirm-mapping …] --confirm` | — | — | **human only** |
| Legacy import | `ariadne-authoring import-legacy` | — | — | **human only** |
| Legacy-page enrichment | `ariadne-authoring enrich-legacy` | — | — | **human only** |

Fixed role limits: the Analyst resolves terms and queries — it has no
inspection, edit, approval or admission authority; the Authoring role works
inside its explicitly selected proposal and can inspect and save hypotheses,
but never approves sources, admits, enriches legacy pages or mutates Git. The
base install needs no MCP and no Agent package for any local operation above.

## Ordinary ingestion stays ordinary

Standalone document ingestion (`ariadne-ingest`) preserves allowed structured
Reference metadata with the ACTUAL input document's provenance; it never
registers a document-mentioned data source, never measures schemas, never
fabricates receipts or confirmation, and opt-in Policy reconciliation
(`--reconcile`) keeps its own store and gate — never merged into the Git
proposal, ad-hoc or Answer Example stores.

## See also

- [Git-backed authoring — legacy → new mappings](git-authoring.md) — the
  proposal lifecycle, admission and the retained legacy routes.
- [ADR-0017](../../project/adr/0017-context-schema-and-identifier-knowledge.md)
  — one OKF authority for schemas and identifier knowledge.
- The packaged agent skill (`ariadne-skill install`) teaches the same workflow
  to your agent.
