# How to manage context knowledge

Use these procedures when maintaining schemas, business terms, identifier mappings, and routing guidance in an Ariadne project. They assume the relevant source identity is operator-approved and you are working in the intended project route. For artifact shapes, limits, and role capabilities, see the [context knowledge reference](../reference/context-knowledge.md). For the authority model, see [How Ariadne works](../explanations/how-ariadne-works.md).

The paths and page-edit examples below describe standalone Core. Integrated
projects keep curated context in the Lumio `knowledge/` subtree and use the
[Bound Release contract](../reference/lumio-bound-releases.md); do not create a
second editable context mirror. [The local tutorial](../tutorials/lumio-ariadne-local.md)
shows that route with supplied files.

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

When useful destinations or known business gaps exist, author an ordinary Reference at `context_layer/references/context-routing.md` through the normal proposal edit. Keep it to a short business orientation, question families, links to existing definitions and full Policies, and explicit unresolved questions. Do not copy metric formulas, SQL, Policy bodies, or observed values into it.

Use the stable page on retries. If that path already contains an unrelated Reference, resolve the collision with the owner rather than overwriting it. Review the map with the full candidate; admission does not validate its business interpretation. An absent map is fine: normal discovery remains available.

## Onboard business meaning

During requested authoring, the packaged Ariadne skill reads the existing Seed Notes and admitted/candidate context first. It then asks only for missing information that affects the current proposal—such as row grain, date conventions, units, exclusions, or code meanings. Preserve unresolved answers instead of filling gaps with assumptions.

Before preparing selected observed-value metadata, show the owner the exact table and columns and get explicit selection. Source approval is not consent to publish observed values. Business confirmation, schema refresh, and technical validation never admit the candidate or independently attest metric values.

## Work with a context-only candidate

A proposal containing schema pages and References but no metrics can still be reviewed and admitted. Follow the normal source-approval, validation, review, and human-admission sequence. Validation reports checks that are not applicable; it does not relax checks for any inherited semantic declarations, policies, or relationships.

Source approval and Git Admission remain separate human decisions. See [Git-backed authoring](git-authoring.md) for the supported proposal workflow and [CLI reference](../reference/cli.md) for command entry points.
