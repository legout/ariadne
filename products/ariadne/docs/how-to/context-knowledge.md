# How to manage context knowledge

Use these procedures when maintaining schemas, business terms, identifier mappings, and routing guidance in an Ariadne project. They assume the relevant source identity is operator-approved and you are working in the intended project route. For artifact shapes, limits, and role capabilities, see the [context knowledge reference](../reference/context-knowledge.md). For the authority model, see [How Ariadne works](../explanations/how-ariadne-works.md).

Curated context lives in the Lumio `knowledge/` subtree and follows the
[Bound Release contract](../../../../integration/docs/reference/lumio-bound-releases.md).
The standalone `context_layer/` route is retired; do not create a second
editable context mirror. For a new native project, follow
[Getting started](../tutorials/getting-started.md). The
[historical joint tutorial](../../../../integration/docs/tutorials/lumio-ariadne-local.md)
retains the older Core 0.6.0 / SDK 0.4.0 example, not the current setup route.

## Refresh a table schema

Schema facts are generated from an approved source; do not hand-edit the generated Schema or Observations sections. In an active Git proposal, identify the exact asset and refresh it:

```bash
ariadne-authoring refresh-schema --project . --proposal ID \
    --expected-revision REV --file assets.json
```

`assets.json` contains the exact source, catalog, schema, and table identity:

```json
[{"source":"sales","catalog":null,"schema":"sales","table":"orders"}]
```

Use the current proposal revision. A refresh edits a candidate; it does not validate, review, or admit it. An identical refresh is a no-op. Review generated facts and retain authored column meanings; a changed or removed column is not treated as a guessed rename.

In an integrated project whose selector opted into support revision 2, the
same refresh writes the generated technical pages as producer-native
Dataset/Table profile pages inside `knowledge/tables/` and
`knowledge/datasets/` — bound by exact `core_ref` resource identity,
validated with the whole captured KB, and served through the pinned SDK.
Curated descriptions, authored native metadata and page bodies survive
regeneration. C6 (spec0035 §6): the classic `context_layer` refresh route is
retired — a candidate whose capability revision lacks the native technical
kinds refuses the refresh with explicit opt-in guidance before any access,
while historical admitted releases keep their exact read support. These
revision-2 contracts are implemented in this
repository's source candidate; published package pairs have not acquired
them.

## Resolve a business term

Query the admitted project when answering an analyst question, or the selected proposal while authoring:

```bash
ariadne resolve-term "global order number" --project .
ariadne-authoring resolve-term --project . --proposal ID "order number"
```

For an exact physical-field lookup, pass the resource and column as JSON:

```bash
ariadne resolve-term --project . --file - <<'JSON'
{"resource":"ariadne://table/...","column":"store_id"}
JSON
```

Read the returned scope, exact field bindings, ambiguity, and claim status. A match is guidance only: it does not authorize a join, transform, or SQL rewrite. An unconfirmed mapping remains a lead, even when its page is admitted.

## Inspect a candidate mapping

Use bounded mapping inspection only when an owner-approved source is available and a specific mapping hypothesis needs evidence:

```bash
ariadne-authoring inspect-mapping --project . --proposal ID \
    --expected-revision REV --file candidate.json
```

The request describes typed field bindings and predicates, not SQL. Review the returned receipt and its actual scope and outcome; incomplete or inconclusive evidence does not establish a relationship. Raw identifier examples require the operator's separate permission. The [reference](../reference/context-knowledge.md#mapping-inspection) documents request fields and fixed ceilings.

An Authoring agent may save an evidence-backed **hypothesis** through the typed page-edit workflow. Keep its claim labeled as a hypothesis and cite the receipt. A technical match is not proof of business meaning.

## Confirm an asserted mapping

Only a human can confirm an eligible assertion, and only during admission of the reviewed candidate. Inspect the review report for the exact assertion and digest, then select it explicitly:

```bash
ariadne-admit --project . --proposal ID --revision REV \
    --reviewed-digest DIGEST --confirm \
    --confirm-mapping order-number:global-order-concatenation
```

Omitting the selection does not confirm a new assertion. Changed, stale, or conflicting assertions cannot inherit confirmation. Neither a proposal edit nor a successful inspection performs confirmation.

## Add a Context Routing Map

When useful destinations or known business gaps exist, author an ordinary Reference at `knowledge/references/context-routing.md` through the normal proposal edit. Keep it to a short business orientation, question families, links to existing definitions and full Policies, and explicit unresolved questions. Do not copy metric formulas, SQL, Policy bodies, or observed values into it.

Use the stable page on retries. If that path already contains an unrelated Reference, resolve the collision with the owner rather than overwriting it. Review the map with the full candidate; admission does not validate its business interpretation. An absent map is fine: normal discovery remains available.

## Onboard business meaning

During requested authoring, the packaged Ariadne skill reads the existing Seed Notes and admitted/candidate context first. It then asks only for missing information that affects the current proposal—such as row grain, date conventions, units, exclusions, or code meanings. Preserve unresolved answers instead of filling gaps with assumptions.

Before preparing selected observed-value metadata, show the owner the exact table and columns and get explicit selection. Source approval is not consent to publish observed values. Business confirmation, schema refresh, and technical validation never admit the candidate or independently attest metric values.

## Retain sources for a managed publication

These are operator actions for a machine-local Lumio profile with
`retention: required`. Source approval for SQL access does not register or
retain originals. Core does not register cited sources automatically.

1. Inspect every source ID the candidate's pages cite (each page's `sources`),
   not only the authored ones. Generated pages cite technical evidence too:
   - a Computation page cites its OSI model, e.g. `retail_sales::revenue`
     cites `model-retail_sales`, whose original is the exact candidate
     `semantic_layer/models/retail_sales.yml` bytes, not a later working copy;
   - a refreshed Table or Dataset page cites its approved catalog asset
     (`catalog-<source>-<schema>-<table>` / `catalog-<source>-<schema>`), whose
     original is the approved source file the refresh read (for a SQLite
     source, that database file);
   - authored Policy and Metric pages cite their own sources, such as Seed Notes
     or the governing Policy page.

   Validate the candidate first: the finalize pass adds the Computation pages
   and their citations.
2. Use the native operator APIs `SourceRegistry.register_version` and
   `retain_artifact` with those genuine bytes and the selected private registry
   and artifact store. Derive the content digest from the original bytes;
   retain the same version rather than substituting another file.
3. Bind the exact page Entity ID, source ID and digest in the native Source
   Reference Manifest. In the example, the binding is
   `entity:retail-sales-revenue-computation` → `model-retail_sales:<digest>`.
   Keep registry/store paths in the private profile, never in public pages.
4. Revalidate and review the complete candidate after manifest edits. Obtain
   a fresh overall admission preview with an **absolute**
   `--context-private-profile` path, inspect its source configuration and
   retention coverage, then confirm only that preview's exact digest.

A different registry/store configuration needs fresh consent even when its
retained bytes are identical. Missing required coverage refuses activation;
inspect the reported publication outcome before retrying rather than forcing
pointers, inventing hashes or marking genuine originals synthetic. After
admission, ordinary scoped knowledge readers need no private registry or
originals store. See the [Bound Release contract](../../../../integration/docs/reference/lumio-bound-releases.md)
for the preview/confirmation and activation boundaries.

## Work with a context-only candidate

A proposal containing schema pages and References but no metrics can still be reviewed and admitted. Follow the normal source-approval, validation, review, and human-admission sequence. Validation reports checks that are not applicable; it does not relax checks for any inherited semantic declarations, policies, or relationships.

Source approval and Git Admission remain separate human decisions. See [Git-backed authoring](git-authoring.md) for the supported proposal workflow and [CLI reference](../reference/cli.md) for command entry points.
