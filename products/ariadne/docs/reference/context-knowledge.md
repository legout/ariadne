# Context knowledge reference

This page describes the context-layer artifacts, generated facts, and tool roles available in Ariadne 0.6.0. For procedures, see [How to manage context knowledge](../how-to/context-knowledge.md). For the authority boundaries shared by all these artifacts, see [How Ariadne works](../explanations/how-ariadne-works.md).

These `context_layer/` paths describe standalone Core projects. In an integrated
project, curated Metric/Policy/Reference pages live once under `knowledge/`, carry
the supported Lumio profile and are consumed through the pinned SDK; ordinary
unprofiled pages are documentation. See [Bound Releases](../../../../integration/docs/reference/lumio-bound-releases.md).
Generated Core technical artifacts remain Core-owned.

## Page types and ownership

| Artifact | Location / type | Meaning and ownership |
| --- | --- | --- |
| Dataset Overview | `context_layer/datasets/`, `type: dataset` | Describes a physical source/schema collection and its represented tables. |
| Table page | `context_layer/tables/`, `type: table` | Contains authored summary and column meaning plus core-generated Schema and Observations sections. |
| Term or Identifier Reference | `context_layer/references/`, `type: reference` | Documents a shared concept, aliases, exact field bindings, required scope, and optional typed mapping assertions. |
| Context Routing Map | `context_layer/references/context-routing.md`, ordinary `type: reference` | Human-owned orientation and pointers to existing context; optional, not a new executable page type. |

A table or collection page identifies its asset with a canonical, credential-free resource such as `ariadne://table/<payload>` or `ariadne://collection/<payload>`. Same-named tables from different sources or schemas are distinct assets. A resource or filename collision is refused rather than overwritten.

### Structured Term and Identifier References

The versioned `ariadne` extension (version `1`) may declare `reference_role: term|identifier|enum|join`, representations, aliases, exact source-qualified field `bindings`, required `scope`, and typed `mappings`. Mapping families are `equality`, `prefix`, or `lookup`; claims are `hypothesis` or `asserted`. Legacy References without this extension remain readable.

## Generated schema and observations

Schema refresh owns the table's `# Schema` block and `ariadne.schema` / `ariadne.observations` metadata. Facts include exact column identity and type, declared nullability/defaults only when the source provides them, measurements such as row/null/distinct counts, candidate keys, profile scope, and `observed_at` with an explicit UTC offset.

Observed uniqueness is a candidate key, not a declared business key. Zero observed nulls do not establish `NOT NULL`; measured table facts do not establish business grain. Generated sections are not hand-authored.

### Selected observed filter values

A table page may declare an optional authored mapping from exact physical column names to selected catalog types:

```yaml
observed_value_columns:
  region: VARCHAR
```

Selection is opt-in and is not source approval or a sample-access grant. Refresh reuses the existing profile and places measurements in core-owned `ariadne.observations.value_evidence`; it does not create a new lookup or widen sampling. Supported values preserve native text/enum, boolean, integer, and finite floating-point representation. Values are partial top-value observations, not normalized business domains or complete allowed-value lists; a value missing from the list is not thereby invalid.

An unavailable selected column reports an explicit state/reason such as `not_in_profile`, `column_missing`, `type_changed`, `unsupported_representation`, `permission_denied` where an applicable permission exists, or `too_large`; malformed measurements fail rather than becoming evidence. Decimal, binary, temporal, and complex representations are not emitted as exact filter hints. A changed or missing field does not trigger a rename guess.

The complete successful `value_evidence` mapping is bounded to 8 KiB as compact UTF-8 JSON. Over-limit content is marked unavailable rather than clipped; if even the status-only mapping cannot fit, refresh refuses atomically. The observation timestamp and profile scope describe when/how values were measured; they do not prove that today's values are unchanged or define an allowed-value domain. Clearing selection removes active evidence after refresh but does not erase historical Git revisions.

## Context Routing Map

The optional map is a normal human-owned Reference at `context_layer/references/context-routing.md`. It may contain brief business orientation, question families, pointers to existing metrics, Policies, Term References, tables or Dataset Overviews, and explicit unresolved questions.

The map contains pointers, not copied formulas, SQL, Policy bodies, observed-value lists, or a second metric catalog. Its target owns the definition. A missing/ambiguous pointer is handled through normal discovery; the map grants no source, calculation, join, or normalization authority and cannot bypass a required Policy read. Managed analysts read it only from the pinned admitted snapshot.

## Term resolution

Term resolution returns bounded matches with concept/representation identifiers, aliases, exact bindings, required scope, ambiguity, claim/confirmation status, evidence freshness, and citations. Matches are whole aliases/phrases (case-insensitive), not substrings; physical field identity is exact. Results are limited to 20 matches per part and 64 KiB serialized.

An unconfirmed mapping remains a labeled lead even if its page is admitted. Confirmation requires recorded human admission evidence bound to the exact reviewed assertion. Term resolution is read-only guidance and never grants join authority.

## Mapping inspection

Mapping inspection accepts a typed object describing a family (`equality|prefix|lookup`), ordered left/right resource-and-column bindings, scope predicates (`eq|in|gte|lt`), optional pairing, and family-specific fields. It accepts no SQL, path, or function.

Inspection uses the operator-approved source identity and fixed ceilings: up to 1,000 sampled rows per asset, 20 seconds execution, 64 KiB response, 4 assets, 16 bindings, 8 scope predicates, and 100 values per `in` list. A request may lower but not raise those bounds. Aggregate counts are the default; up to 10 raw identifier examples require the operator's explicit `inspection.raw_examples` permission.

The integrity-bound receipt reports the tested scope and outcome (`complete` or `inconclusive`), counts and mapping evidence. A partial or inconclusive result never establishes a business rule; validation checks the receipt against the proposal's evidence record and exact dependencies.

## Tool roles and human-only operations

| Capability | Local CLI | MCP surface | Ariadne Agent | Authority |
| --- | --- | --- | --- | --- |
| Refresh schema | `ariadne-authoring refresh-schema` | `authoring_refresh_schema` | `refresh_schema` (Authoring) | Agent, approved sources only |
| Resolve admitted term | `ariadne resolve-term` | `resolve_term` | `resolve_term` (Analyst) | Read-only |
| Resolve candidate term | `ariadne-authoring resolve-term` | `authoring_resolve_term` | `resolve_term` (Authoring) | Read-only |
| Inspect mapping | `ariadne-authoring inspect-mapping` | `authoring_inspect_mapping` | `inspect_mapping` (Authoring) | Bounded evidence only |
| Approve sources | `ariadne-authoring approve-sources` | — | — | Human only |
| Confirm assertion / admit | `ariadne-admit` | — | — | Human only |

The Analyst role resolves terms and queries; it does not edit, inspect, approve, or admit. The Authoring role works inside its selected proposal and may inspect and save hypotheses, but cannot approve sources, admit, enrich legacy pages, or mutate Git. MCP/native registrations do not widen these roles. Core exposes no legacy import
or enrichment command; existing content must be explicitly reauthored through
the supported Git proposal route. Agent/Tau compatibility is independently
versioned and was not qualified by the Core 0.6.0 release.

## Context-only validation

A candidate containing schema pages and References but no metrics can still be validated and admitted through the normal human route. Validation reports applicable checks and explicit `not_applicable` reasons. Semantic compile/bind/Grain checks are omitted only when no effective semantic declaration requires them; inherited models, metrics, Policies, and relationships still receive their applicable checks. Unknown physical grain never weakens semantic grain requirements.
