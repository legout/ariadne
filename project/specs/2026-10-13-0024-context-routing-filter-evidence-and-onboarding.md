# Specification: Context routing, observed filter values and business onboarding

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1 — written review complete** |
| **Approval** | Owner, this Pi conversation 2026-10-13: selected a reviewed Context Routing Map, explicitly selected columns and Ariadne-skill-led Business Onboarding. Answered “Ja passt” to the complete V1 design and capture request, then “Passt” to written revision 1, explicitly presented for review including column/type binding, separated core-generated evidence and the 8-KiB bound. This approves the complete written behavioral contract and its concrete interfaces/limits. Planning, tickets, implementation, worker dispatch, installed-skill changes, integration and publication remain separately authorized steps. |
| **Scope** | One ordinary OKF Reference for project routing, opt-in bounded values in existing core-generated Schema Observations, and targeted business clarification through the existing Ariadne skill and Authoring Proposal lifecycle. |
| **Sources** | [nao investigation](../research/2026-10-13-nao-context-builder-vs-ariadne.md), [Context schemas and identifiers 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md), [Git authoring 0009](2026-10-02-0009-modular-core-git-authoring.md), [Context browsing 0015](2026-10-12-0015-context-page-browsing.md), [read-path clarification ADR-0020](../adr/0020-context-read-paths.md), [trust signals 0011](2026-10-06-0011-context-trust-signals.md), [vocabulary](../../CONTEXT.md). Runtime evidence was inspected at `a8d24b18d16854058e6b2b97bd1801cb0687ffbd`; this behavior is not implemented. |
| **Contract** | planning-contract v1; installed skill provenance unknown. This is a behavioral specification, not an execution map. |

## 1. Purpose and boundaries

Help a data-project agent find existing definitions, understand actual observed filter values and ask only the business questions those sources cannot answer. Reuse the existing Context Layer, profiler, proposal edits, explicit schema refresh and page discovery/read interfaces. The Context Layer routes and guides; OSI and its existing deterministic gates calculate.

Alternatives considered: only improving generated index descriptions is smaller but lacks curated question-to-definition routing; an automatically inferred business map risks invented meaning. The owner chose a human-owned Reference alongside generated indexes. Publishing every profiled column is convenient but unnecessarily exposes values and enlarges context; the owner chose explicit column selection. Extending the setup CLI would duplicate an interview surface; the owner chose the existing skill and host model.

Non-goals: new warehouse connectors, external knowledge or SQL-history import, a general sync/resume/scheduling system, hybrid search/embeddings/LanceDB, another context store, a routing DSL or executable rule interpreter, new SQL/metric operations, altered query arithmetic, a second LLM endpoint, a setup-CLI interview, a recommendation service, generic context audits, automatic admission, automatic masking or sensitive-data classification. Source approval, applicable sample permissions, pinned-snapshot reads, compile/bind/grain/read-only checks and honest attestation remain binding.

[#68 / specification 0023 revision 2](2026-10-13-0023-answer-example-sql-provenance.md) already owns SQL provenance and consent-bound feedback after an eligible answer. Do not duplicate or expand that behavior here. Specs 0021/0022 and #66/#67 remain separate. Answer Examples remain in their existing separate store, never in the Context Routing Map or table measurements.

## 2. Context Routing Map

### Representation and ownership

Use an optional ordinary `type: reference` page at `context_layer/references/context-routing.md`, through the existing page-edit interface. It is a data project's Context Routing Map, not a repository's multi-bounded-context `CONTEXT-MAP.md`. No new page type, application database or generated root prompt is introduced.

The map contains only useful project-specific content:

- A short business orientation and relevant question families.
- Pointers to existing metric definitions, Policies, Term References, physical tables or Dataset Overviews.
- Pointers to date/period rules where they exist.
- Explicit unresolved business questions rather than inferred defaults.

Use ordinary Markdown links for Context Layer destinations and exact existing metric identities when naming a metric. Do not copy formulas, SQL, Policy bodies, observed-value lists or a second metric catalog into the map. The target owns its definition. Cited source/owner evidence follows existing Reference conventions; an agent-authored `approved` flag proves nothing.

A proposal updates the same page; it never creates timestamped or suffixed map copies on retry. If the chosen path already holds an unrelated Reference, do not overwrite or rename it automatically: resolve the collision with the owner. Projects without a useful map remain valid. Generated indexes continue to enumerate applicable pages; authoring never edits generated indexes or logs directly.

### Reading behavior

For a novel analysis question, the skill uses the normal selected project/root and existing discovery/list/read operations to consult the map when present. Read relevant definition and full applicable Policy pages, not just the map's summary. The normal metric/catalog/term lookup remains authoritative. The map grants neither source access nor permission to calculate, join, normalize identifiers or execute arbitrary SQL.

A managed analyst reads the admitted pinned snapshot, never a proposal or mutable root fallback. Authoring may inspect its explicitly selected candidate with its unadmitted identity visible. Legacy served/draft distinctions and existing freshness signals remain unchanged.

If the map is absent, use existing discovery/index navigation. If a pointer is missing or ambiguous, flag it and use normal discovery to establish a valid target; do not select an invented metric or weaker source. If definitions or Policies genuinely conflict, resolve the affected interpretation rather than silently overriding a source. A map cannot bypass a failed required-Policy/read gate. This consumer behavior is not a fallback inside a failed `read_page` operation: that operation still returns its existing refusal.

Normal validation checks local links/dependencies under the existing applicable-page contracts; no new remote link fetch or ranking change is introduced. The map is human-reviewed through the existing applicable Admission/Promotion route. It is not independently numerically validated merely because it was admitted.

## 3. Selected Observed Filter Values

### Human-owned selection

Add the optional top-level authored metadata `observed_value_columns` to an existing physical table page. It is a mapping from exact physical column name to its selected catalog type, not an alias, wildcard or permission statement:

```yaml
observed_value_columns:
  region: VARCHAR
  status: VARCHAR
```

The expected type binds selection to the known field representation. A later type change does not silently enable publication for a different representation. The skill shows the exact table/resource, columns and proposed disclosure to the owner and obtains explicit selection confirmation before preparing this metadata. Source approval alone is not confirmation to publish values. The human later reviews the actual generated values with the whole candidate; selected fields may contain sensitive data, so select them deliberately. Do not store secrets or inappropriate sensitive values. Do not silently redact or transform a measurement to make it acceptable.

The selection is edited through the existing complete-page proposal edit with expected revision; it remains outside core-owned `ariadne` facts. Omission/empty mapping means no value publication for that table. Preserve unrelated authored content. A malformed mapping, duplicate declaration or non-string/empty identifier/type is a validation error, not an implicit selection of all columns.

Selection is the publication choice, not a new source-access or sample grant. Retain any applicable existing operator sample/value restrictions; the agent cannot raise ceilings. The explicit refresh asset remains exactly `{source, catalog, schema, table}`. No field-selection flag, changed asset identity, arbitrary query or separate registry is added.

### Core-generated evidence

Existing schema refresh reads the selection and reuses its approved per-table profile. The core extends `ariadne.observations` with `value_evidence` only when a nonempty selection exists. It preserves the current schema, count/candidate-key facts, resource citation, sampled/full scope and observation-timestamp/no-op rules. The table body presents the same evidence readably, not another independently editable copy.

Illustrative complete-profile fragment for three independently known rows, with two `EMEA` values and one `AMER` value:

```yaml
ariadne:
  observations:
    observed_at: "2026-10-13T12:00:00+00:00"
    scope: full
    row_count: 3
    # The existing exact resource citation, column counts and candidate keys remain.
    value_evidence:
      region:
        state: observed
        top_values:
          - value: EMEA
            count: 2
          - value: AMER
            count: 1
```

Only selected columns appear in `value_evidence`. Values/counts come from the measured profile, not Seed Notes, an LLM or a claimed business enum. No additional distinct-value lookup, widened sampling, new profiling strategy or changed cardinality threshold is introduced. Existing profiling may still run during normal inputs/refresh; this feature does not promise zero database cost. The current profiler supplies at most ten top values where its existing eligibility rule applies (currently distinct count greater than one and at most twenty). Do not derive a missing histogram from min/max or fetch a different one.

Preserve native scalar representation for supported text/enum, boolean, integer and finite native floating-point values; never trim, case-fold, stringify nulls or turn integer-looking strings into numbers. Decimal, binary, temporal and complex types are unavailable for this V1 consumer: their current normalization is not an exact typed filter-value contract. Do not convert them automatically. This limits observation hints, not existing legal filter operations. A measured null may remain `null` with its count; it is absence, never the string `"NULL"` or an ordinary equality literal. Column type and existing null/count facts remain visible.

The stored `observed_at` identifies the saved observation under the existing reuse rule; it is not a newly fabricated latest-check time. It does not prove that live data is unchanged. Report scope, timestamp and existing freshness signals. Top values are explicitly partial observations, never a complete allowed-value domain or a business constraint. Even a full-table profile is not permanent domain authority.

### Unavailable, changed and oversized evidence

A selected column without usable values has `state: unavailable`, no `top_values`, and an identifiable reason: `not_in_profile`, `column_missing`, `type_changed`, `unsupported_representation`, `permission_denied` where an applicable permission actually exists, or `too_large`. Missing histogram is distinct from a successful empty allowed-value check. An invalid/malformed supplied measurement is an error, not a valid histogram.

When a previously selected field disappears or differs from its recorded type, refresh removes its formerly usable values and reports unavailable evidence. Preserve the human-owned selection for review; do not guess a rename, substitute a similarly named column or change its expected type. The owner may explicitly clear/rebind selection. Repeating a refresh cannot erase the type binding and silently reactivate publication. Existing schema-change/meaning-history behavior stays intact; unavailability alone does not prohibit an otherwise valid context-only proposal from review.

**Value-evidence bound:** at most 8 KiB UTF-8 for the complete successful `value_evidence` mapping, measured as compact JSON with non-ASCII preserved and non-finite numbers refused. This bounds new value content, not the whole existing table artifact. If the selected content exceeds the bound, emit unavailable/`too_large` outcomes instead of publishing a truncated or arbitrarily reduced histogram. If even that status-only mapping exceeds 8 KiB, refuse atomically. Never clip a literal. Existing artifact, validation and transport bounds also remain applicable; metadata that cannot fit them is an explicit refusal, not an unbounded success. The skill can offer a smaller explicit selection. No adapter-specific quota or new operator configuration is required.

Refresh remains revision-checked and proposal-local; failures retain the existing atomic/no-partial-write contract. Identical selection, schema and profile produce identical bytes and no new revision. Deselection followed by successful refresh removes active evidence but does not scrub old admitted revisions, proposal history or Git history. Do not claim erasure or automatically clean historical artifacts.

### Query use

The skill uses compatible, source-qualified values to understand spelling/representation and clarify filters. Establish the actual physical-to-model field binding first; a same-named dimension is insufficient, and an OSI-transformed/bucketed dimension does not automatically share its raw field's value representation. Do not invent or apply a normalization outside the reviewed model. A missing top value does not establish that it is invalid or absent today. Do not reject a normal compiled filter merely because it was not among the saved top values. Do not silently replace a requested value with a common one, invent a code's business meaning or use unavailable/stale evidence as current validation. Actual filter binding and execution still use the normal model and compile gate. Observations never attest a current result, authorize joins or make an Ad-hoc Metric governed.

## 4. Business Onboarding in the existing skill

This is an authoring-oriented conversational workflow, not a runtime wizard or automatic prompt per query. It is used during requested onboarding/authoring and when an actual unresolved meaning prevents a correct proposal. During ordinary analytics, ask the minimum question necessary to resolve the current ambiguity, not the entire onboarding interview.

1. Read the existing selected project's Seed Notes, applicable admitted/candidate definitions, Policies, References and Context Routing Map before asking for knowledge already recorded.
2. Read schema/profile evidence only through the operator-approved route; lack of source approval remains a human stop. Business questions may use already supplied owner/document evidence without secretly opening sources.
3. Ask the current material frontier together: row meaning/Grain, business date, period completeness/week conventions, units/metric meaning, exclusion rules or status-code meaning as relevant. Distinguish supplied fact, proposed interpretation and unknown. No assumed Monday/UTC/currency or formula inferred from frequency.
4. Show a concise summary of the proposed business interpretation and selected value disclosures for confirmation. Declined, ambiguous or unresolved answers remain unknown; no policy/metric meaning is invented. Do not retain the whole transcript.
5. Reuse current Seed Notes and relevant table/Reference/Policy edits. Source-link owner/document claims; raw measurements stay core-owned. Prepare a Context Routing Map only when there are useful actual destinations or explicit gaps. Confirmed meaning may lead to normal OSI proposals, but no new calculation primitive is introduced.
6. Validate and review the exact candidate, then stop for human Admission/Promotion. A user answer, selection confirmation or successful technical check is not admission, Source Approval or Independent Numerical Validation.

Update stable existing artifact identities, preserving unrelated authored content. Do not create a second business dictionary or overwrite a conflicting admitted rule. Restarts re-read persisted candidate/Seed Notes; no background memory service or session-transcript storage is needed. A context-only proposal can document unknown meaning without inventing a metric; unresolved meaning blocks only dependent assertions/calculations, not unrelated legitimate context work.

## 5. Compatibility and owned behavior

The intended shared producers/consumers are existing table generation/validation in `context.py`, revisioned authoring/schema refresh in `authoring.py`, and the bundled `skill_assets/SKILL.md` guidance. They remain one core behavior behind current adapters; no new public tool registration or MCP/CLI prompting is required. Planning must check every existing caller of table generation, including retained legacy paths, without allowing unselected values by default.

Old tables without selection remain valid and unchanged under unchanged inputs; there is no backfill or forced migration. An optional map does not make old/context-only bundles invalid. Existing search ranking, response shape, full content, draft labels, exact path protections, index generation and snapshot-digest checks remain intact. New value content is visible only as part of the explicitly enriched existing table page. Human-owned selection is not an agent-writable validation/admission stamp. Existing protected generated sections remain protected.

This specification does not install a user skill or advertise candidate behavior as already published. #66/#67/#68 are not changed or execution-authorized by this capture. No semantic dependency on those candidates is introduced.

## 6. Observable acceptance scenarios

1. **Routing without duplicate truth:** an admitted map points “net revenue” to an existing metric and its cancellation/date Policies. The agent reads those actual sources and uses the normal governed method; formulas and Policy bodies are not copied into the map. An absent map retains normal discovery. A missing/ambiguous pointer is flagged without a weaker-root/raw-SQL fallback.
2. **Selection and independent values:** for an approved table containing `EMEA, AMER, EMEA`, explicitly select `region` and leave another profiled column unselected. Refreshed evidence contains exactly the independently expected `EMEA: 2`, `AMER: 1`, existing source/scope/timestamp linkage and no values from the unselected column. A sampled counterpart says sampled; neither says allowed-value domain. Selection alone does not publish the candidate.
3. **Honest absence and exact representation:** select a field with no histogram and one with integer-looking strings; the first is unavailable/`not_in_profile`, the latter preserves the exact strings. Null is never `"NULL"`. An unsupported normalized type does not become an exact filter literal. A user's value missing from saved top values is not automatically rejected or replaced.
4. **Refresh and retry:** identical schema/profile/selection preserves bytes and revision. Removing a selected column or changing its type removes usable values with a visible reason, without a guessed rename; a repeated refresh keeps the old type binding. Explicit reselection can restore appropriate evidence. Clearing selection and refreshing removes active values while preserving unrelated meaning and historical records. A stale candidate revision refuses without partial writes.
5. **Bounded disclosure:** independently supplied long exact strings make successful value evidence exceed the specified byte bound. No clipped/partial histogram is published; the selected outcomes explain unavailability. Invalid measurement or existing artifact-limit failure is not a success. A rejected refresh does not leave half-updated pages/indexes.
6. **Gap-driven onboarding:** owner/document evidence already defines a date rule but leaves status-code meaning unknown. The skill reads the rule, asks only the missing meaning, summarizes it and selected disclosure, and prepares source-linked existing artifacts in the proposal. Declining or giving an ambiguous answer produces no fabricated Policy or metric definition. No unsolicited full interview follows every query.
7. **Authority and existing routes:** candidate map/value pages remain unadmitted; managed analysts use only their pinned admitted snapshot. Existing legacy/root/path, protected-section, Source Approval and compile/grain gates still apply. Technical success/business confirmation is not numeric attestation. Example-save feedback remains #68's separate behavior.

Validation obligations for later planning: `new-test` for deterministic selected measurement projection, unavailable/type-change/deselection/no-op and oversized cases (independent literals/source fixtures, not implementation-generated expected output); `existing-check` for current schema refresh, meaning preservation, source/revision/atomicity gates, page discovery and managed/legacy admission; `no-new-test` for pure Reference/skill prose, with focused written-guidance inspection and **manual owner agent scenarios** for routing/onboarding/filter interpretation. Do not restore recorded-agent traces or claim prose inspection proves a live agent follows the skill. This capture runs no feature tests.

## 7. Capture checkpoint and next handoff

- **Vocabulary:** Context Routing Map, Observed Filter Values and Business Onboarding are captured in [CONTEXT.md](../../CONTEXT.md). Existing Policy, Schema Observation, Seed Notes, Source Approval and admission terms retain their authority.
- **Decisions:** no new ADR is warranted. Ordinary References, optional table enrichment and existing proposal/skill workflows preserve current architecture and remain locally reversible; there is no new storage/engine authority boundary.
- **Behavior:** the owner approved the complete V1 in-chat behavior with “Ja passt” and the complete written revision 1 with “Passt”, including its concrete path/metadata/type-binding and byte-limit contract. This is the approved behavioral source, not an implementation plan or ticket body.
- **Uncertainty:** no material design or written-review decision remains open. Planning/tracker authority and execution readiness still precede implementation; no planning, ticket publication, installed-skill refresh or execution has been authorized. Route separately authorized planning through `write-implementation-plan` and obtain execution authority before writers start.
